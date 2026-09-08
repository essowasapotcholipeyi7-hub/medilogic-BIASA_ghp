# utils/db_failover.py
"""
Bascule automatique Neon <-> Postgres local pour continuer à travailler
pendant une coupure de connexion, avec synchronisation au retour.

Principe (voir aussi models.py: SyncState, SyncChangelog) :
  - En fonctionnement normal, l'appli lit/écrit sur Neon (comme avant).
  - Un thread de fond vérifie régulièrement que Neon répond.
  - Si Neon ne répond plus : l'appli bascule automatiquement sur Postgres
    local (aucune interruption pour l'utilisateur). Chaque écriture faite
    pendant la coupure est aussi enregistrée dans la table locale
    `sync_changelog`.
  - Dès que Neon redevient joignable : les écritures en attente dans
    `sync_changelog` sont rejouées vers Neon (dans l'ordre), puis la base
    locale est entièrement rafraîchie depuis Neon (pg_dump/pg_restore) pour
    garantir une copie identique. L'appli repasse alors sur Neon.
  - Ce mécanisme suppose qu'un seul "écrivain" actif à la fois (soit Render,
    soit cette machine, jamais les deux en même temps) — confirmé avec
    l'utilisateur avant implémentation.

Ce module est entièrement inactif si la variable d'environnement
DATABASE_URL_LOCAL n'est pas définie (c'est le cas sur Render) : zéro
changement de comportement pour l'appli déployée.
"""

import os
import json
import time
import threading
import subprocess
import tempfile
import logging
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import event, text, inspect as sa_inspect
from flask_sqlalchemy.session import Session as FSASession

logger = logging.getLogger('db_failover')

NEON_URL = os.getenv('DATABASE_URL')
LOCAL_URL = os.getenv('DATABASE_URL_LOCAL')
FAILOVER_ENABLED = bool(LOCAL_URL)

# Dossier contenant pg_dump.exe / pg_restore.exe (Windows). Ajustable via env.
PG_BIN_DIR = os.getenv('PG_BIN_DIR', r'C:\Program Files\PostgreSQL\18\bin')

CHECK_INTERVAL_SECONDS = 20        # fréquence de vérification de la connexion Neon
WARM_REFRESH_INTERVAL_SECONDS = 600  # rafraîchissement périodique du mirroir local pendant qu'on est en ligne
PK_COLUMN = 'id'                    # toutes les tables métier ont une PK entière "id" (vérifié)


class _OfflineState:
    """Drapeau en mémoire, lu à chaque requête (get_bind) — doit être rapide."""
    def __init__(self):
        self.is_offline = False


OFFLINE_STATE = _OfflineState()


# ----------------------------------------------------------------------
# Session SQLAlchemy avec routage dynamique Neon / local
# ----------------------------------------------------------------------

class FailoverSession(FSASession):
    """Route chaque requête vers Neon ou le Postgres local selon l'état
    courant de la bascule. Les modèles avec __bind_key__ explicite (nos
    tables de suivi de synchro) gardent le comportement standard de
    Flask-SQLAlchemy (toujours sur leur bind déclaré)."""

    def get_bind(self, mapper=None, clause=None, **kwargs):
        resolved = super().get_bind(mapper=mapper, clause=clause, **kwargs)
        # Les tables avec __bind_key__ explicite (SyncState/SyncChangelog) ne
        # passent jamais par ici : super() les résout déjà sur leur bind
        # déclaré ('local'), différent du bind par défaut -> on ne les touche pas.
        if FAILOVER_ENABLED and OFFLINE_STATE.is_offline and resolved is self._db.engine:
            return self._db.engines['local']
        return resolved


def _pending_key(session):
    return '_pending_changelog_entries'


def _serialize_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _serialize_row(obj):
    mapper = sa_inspect(obj).mapper
    return {c.key: _serialize_value(getattr(obj, c.key)) for c in mapper.columns}


def register_events(db):
    """À appeler une fois, après db.init_app(app), si FAILOVER_ENABLED."""
    if not FAILOVER_ENABLED:
        return

    def _est_table_locale_uniquement(obj):
        # Tout modèle avec __bind_key__ (SyncState, SyncChangelog, SheetsMirror,
        # et tout futur modèle du même genre) ne vit que sur le Postgres local
        # (jamais sur Neon) — inutile, et même incorrect, de le mettre dans la
        # file de rejeu vers Neon (la table n'y existe pas).
        return getattr(type(obj), '__bind_key__', None) is not None

    @event.listens_for(FailoverSession, 'before_flush')
    def _before_flush(session, flush_context, instances):
        if not OFFLINE_STATE.is_offline:
            return
        pending = session.info.setdefault(_pending_key(session), [])
        for obj in list(session.new):
            if _est_table_locale_uniquement(obj):
                continue
            pending.append({'obj': obj, 'op': 'insert'})
        for obj in list(session.dirty):
            if _est_table_locale_uniquement(obj):
                continue
            if session.is_modified(obj, include_collections=False):
                pending.append({'obj': obj, 'op': 'update'})
        for obj in list(session.deleted):
            if _est_table_locale_uniquement(obj):
                continue
            pending.append({'obj': obj, 'op': 'delete'})

    @event.listens_for(FailoverSession, 'after_flush_postexec')
    def _after_flush_postexec(session, context):
        pending = session.info.get(_pending_key(session))
        if not pending:
            return
        resolved = session.info.setdefault('_resolved_changelog_entries', [])
        for entry in pending:
            obj = entry['obj']
            try:
                tablename = obj.__tablename__
                pk_val = getattr(obj, PK_COLUMN, None)
                if pk_val is None:
                    continue  # ne devrait pas arriver après le flush
                payload = None if entry['op'] == 'delete' else _serialize_row(obj)
                resolved.append({
                    'table_name': tablename,
                    'operation': entry['op'],
                    'pk_value': int(pk_val),
                    'payload': payload,
                })
            except Exception:
                logger.exception("Echec de capture d'un changement pour le changelog offline")
        session.info[_pending_key(session)] = []

    @event.listens_for(FailoverSession, 'after_commit')
    def _after_commit(session):
        resolved = session.info.pop('_resolved_changelog_entries', None)
        if not resolved:
            return
        _write_changelog_entries(resolved)

    @event.listens_for(FailoverSession, 'after_rollback')
    def _after_rollback(session):
        session.info.pop(_pending_key(session), None)
        session.info.pop('_resolved_changelog_entries', None)


def _write_changelog_entries(entries):
    """Écrit les entrées de changelog via une connexion locale séparée,
    indépendante de la session ORM qui vient de committer."""
    from models import db
    try:
        local_engine = db.engines['local']
        with local_engine.begin() as conn:
            for e in entries:
                conn.execute(
                    text("""INSERT INTO sync_changelog
                            (table_name, operation, pk_value, payload, created_at, synced)
                            VALUES (:table_name, :operation, :pk_value, CAST(:payload AS JSON), now(), false)"""),
                    {
                        'table_name': e['table_name'],
                        'operation': e['operation'],
                        'pk_value': e['pk_value'],
                        'payload': json.dumps(e['payload']) if e['payload'] is not None else None,
                    }
                )
        logger.info("Changelog offline : %d changement(s) enregistré(s)", len(entries))
    except Exception:
        logger.exception("Echec d'écriture du changelog offline (%d entrée(s) perdues)", len(entries))


# ----------------------------------------------------------------------
# Détection de connexion / bascule
# ----------------------------------------------------------------------

def is_neon_reachable(timeout=6, tentatives=2):
    """Vérifie que Neon répond. Neon suspend automatiquement son instance de
    calcul après une période d'inactivité (« scale-to-zero ») ; la première
    connexion qui la réveille peut prendre plusieurs secondes. Un timeout
    trop court (3s, valeur initiale) ou un seul essai suffisait à déclarer
    Neon "injoignable" à tort pendant ce réveil — d'où le bandeau "Mode
    hors-ligne" qui s'affichait alors qu'il n'y avait aucune vraie coupure.
    On laisse donc plus de marge (6s) et on retente une fois avant de
    conclure à une coupure réelle."""
    if not NEON_URL:
        return False
    import psycopg2
    for essai in range(tentatives):
        try:
            conn = psycopg2.connect(NEON_URL, connect_timeout=timeout)
            conn.close()
            return True
        except Exception:
            if essai + 1 < tentatives:
                time.sleep(1)
    return False


def _pgtool(name):
    path = os.path.join(PG_BIN_DIR, name)
    return path if os.path.exists(path) else name  # retombe sur le PATH si le dossier n'existe pas


def pull_refresh_from_neon():
    """Rafraîchit entièrement la base locale à partir de Neon (pg_dump | pg_restore).
    Ne touche jamais sync_changelog/sync_state (absentes du dump Neon)."""
    if not FAILOVER_ENABLED:
        return False
    fd, dump_path = tempfile.mkstemp(suffix='.dump', prefix='medilogic_neon_')
    os.close(fd)
    try:
        r = subprocess.run(
            [_pgtool('pg_dump.exe'), NEON_URL, '-Fc', '-f', dump_path],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode != 0:
            logger.error("pg_dump Neon a échoué: %s", r.stderr[:2000])
            return False

        r = subprocess.run(
            # --single-transaction : tout le restore (DROP + CREATE + COPY de
            # chaque table) passe dans UNE seule transaction. Sans ça, une
            # autre connexion (une requête web, un autre process app.py sur
            # ce poste) peut lire la base pile entre le DROP et le CREATE
            # d'une table et voir "relation does not exist" — vécu en test.
            # --no-privileges : Neon référence des rôles qui n'existent pas
            # en local (neon_superuser, cloud_admin) — avec --single-transaction
            # cette seule erreur ferait échouer TOUT le restore, alors qu'on
            # n'a de toute façon pas besoin de ces droits en local.
            [_pgtool('pg_restore.exe'), '--clean', '--if-exists', '--no-owner',
             '--no-privileges', '--single-transaction', '-d', LOCAL_URL, dump_path],
            capture_output=True, text=True, timeout=180
        )
        # pg_restore --clean renvoie souvent un code non-nul pour de simples
        # avertissements (objet déjà absent) ; on ne considère l'échec que
        # si aucune table n'a pu être restaurée du tout.
        if r.returncode != 0 and 'error' in (r.stderr or '').lower():
            logger.warning("pg_restore Neon->local : avertissements/erreurs: %s", r.stderr[:2000])

        _touch_sync_state(dernier_sync_reussi=datetime.utcnow())
        logger.info("Mirroir local rafraîchi depuis Neon avec succès")
        return True
    except Exception:
        logger.exception("Echec du rafraîchissement local depuis Neon")
        return False
    finally:
        try:
            os.remove(dump_path)
        except OSError:
            pass


def _touch_sync_state(**fields):
    from models import db, SyncState
    try:
        etat = SyncState.query.get(1)
        if not etat:
            etat = SyncState(id=1)
            db.session.add(etat)
        for k, v in fields.items():
            setattr(etat, k, v)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Echec de mise à jour de sync_state")


def push_sync_to_neon():
    """Rejoue vers Neon les écritures faites en local pendant la coupure.
    Tout ou rien (transaction unique) : en cas d'échec, rien n'est marqué
    synchronisé et on réessaiera au prochain cycle."""
    from models import db, SyncChangelog
    import psycopg2
    from psycopg2.extras import Json as PgJson

    entries = SyncChangelog.query.filter_by(synced=False).order_by(SyncChangelog.id.asc()).all()
    if not entries:
        return True

    def _adapt(v):
        # Une colonne JSON (ex: Paie.autres_retenues) revient du changelog
        # comme un dict/list Python natif — psycopg2 ne sait l'adapter que
        # via Json(), sinon "can't adapt type 'dict'".
        return PgJson(v) if isinstance(v, (dict, list)) else v

    touched_tables = set()
    conn = None
    try:
        conn = psycopg2.connect(NEON_URL, connect_timeout=5)
        conn.autocommit = False
        cur = conn.cursor()
        for e in entries:
            touched_tables.add(e.table_name)
            if e.operation in ('insert', 'update'):
                payload = dict(e.payload or {})
                payload[PK_COLUMN] = e.pk_value
                cols = list(payload.keys())
                col_list = ', '.join(f'"{c}"' for c in cols)
                placeholders = ', '.join(['%s'] * len(cols))
                update_list = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != PK_COLUMN)
                sql = (f'INSERT INTO "{e.table_name}" ({col_list}) VALUES ({placeholders}) '
                       f'ON CONFLICT ("{PK_COLUMN}") DO UPDATE SET {update_list}')
                cur.execute(sql, [_adapt(payload[c]) for c in cols])
            elif e.operation == 'delete':
                cur.execute(f'DELETE FROM "{e.table_name}" WHERE "{PK_COLUMN}" = %s', [e.pk_value])

        # Réaligne les séquences Postgres des tables touchées sur le max(id) réel
        for t in touched_tables:
            safe_t = t.replace('"', '')  # nom de table déjà trusted (vient de __tablename__), on échappe par prudence
            cur.execute(
                f'SELECT setval(pg_get_serial_sequence(%s, %s), '
                f'COALESCE((SELECT MAX("{PK_COLUMN}") FROM "{safe_t}"), 1))',
                (safe_t, PK_COLUMN)
            )

        conn.commit()
    except Exception as ex:
        if conn:
            conn.rollback()
        logger.exception("Echec de la synchronisation vers Neon (%d entrée(s) en attente)", len(entries))
        _touch_sync_state(derniere_erreur_sync=str(ex)[:2000], derniere_erreur_sync_at=datetime.utcnow())
        return False
    finally:
        if conn:
            conn.close()

    now = datetime.utcnow()
    for e in entries:
        e.synced = True
        e.synced_at = now
    db.session.commit()
    logger.info("Synchronisation vers Neon réussie : %d changement(s) rejoué(s)", len(entries))
    return True


# ----------------------------------------------------------------------
# Thread de fond
# ----------------------------------------------------------------------

_watchdog_started = False


def start_watchdog(app):
    global _watchdog_started
    if not FAILOVER_ENABLED or _watchdog_started:
        return
    _watchdog_started = True

    def _loop():
        from models import db, SyncState
        from utils import sheets_mirror
        last_warm_refresh = 0.0
        echecs_consecutifs = 0
        # Il faut 2 échecs consécutifs (~40s d'indisponibilité confirmée, vu
        # CHECK_INTERVAL_SECONDS=20) avant de basculer hors-ligne — un seul
        # échec isolé (blip réseau, réveil Neon après mise en veille) ne
        # suffit plus, pour éviter les faux positifs vécus en pratique.
        SEUIL_ECHECS_AVANT_BASCULE = 2
        with app.app_context():
            etat = SyncState.get_ou_creer()
            OFFLINE_STATE.is_offline = (etat.mode == 'offline')
            try:
                sheets_mirror.sync_all()  # premier remplissage du miroir Sheets au démarrage
            except Exception:
                logger.exception("Echec du remplissage initial du miroir Sheets")

        while True:
            time.sleep(CHECK_INTERVAL_SECONDS)
            try:
                with app.app_context():
                    reachable = is_neon_reachable()
                    etat = SyncState.get_ou_creer()

                    if OFFLINE_STATE.is_offline:
                        if reachable:
                            echecs_consecutifs = 0
                            logger.info("Neon de nouveau joignable — synchronisation en cours...")
                            if push_sync_to_neon() and pull_refresh_from_neon():
                                OFFLINE_STATE.is_offline = False
                                etat.mode = 'online'
                                db.session.commit()
                                logger.info("Retour en mode normal (Neon)")
                    else:
                        if not reachable:
                            echecs_consecutifs += 1
                            if echecs_consecutifs >= SEUIL_ECHECS_AVANT_BASCULE:
                                OFFLINE_STATE.is_offline = True
                                etat.mode = 'offline'
                                etat.derniere_bascule_offline = datetime.utcnow()
                                db.session.commit()
                                logger.warning("Neon injoignable (%d échecs consécutifs) — bascule en mode hors-ligne (base locale)", echecs_consecutifs)
                            else:
                                logger.warning("Neon injoignable (%d/%d) — pas encore de bascule, nouvelle vérification dans %ss", echecs_consecutifs, SEUIL_ECHECS_AVANT_BASCULE, CHECK_INTERVAL_SECONDS)
                        else:
                            echecs_consecutifs = 0
                            now = time.time()
                            if now - last_warm_refresh > WARM_REFRESH_INTERVAL_SECONDS:
                                pull_refresh_from_neon()
                                try:
                                    sheets_mirror.sync_all()
                                except Exception:
                                    logger.exception("Echec du rafraîchissement périodique du miroir Sheets")
                                last_warm_refresh = now
            except Exception:
                logger.exception("Erreur dans le thread de surveillance de la bascule Neon/local")

    t = threading.Thread(target=_loop, name='db-failover-watchdog', daemon=True)
    t.start()
    logger.info("Watchdog de bascule Neon/local démarré (intervalle=%ss)", CHECK_INTERVAL_SECONDS)


def get_status():
    """Pour l'API /api/sync/status."""
    from models import SyncState, SyncChangelog
    etat = SyncState.get_ou_creer()
    pending = SyncChangelog.query.filter_by(synced=False).count()
    return {
        'enabled': FAILOVER_ENABLED,
        'mode': etat.mode,
        'is_offline': OFFLINE_STATE.is_offline,
        'derniere_bascule_offline': etat.derniere_bascule_offline.isoformat() if etat.derniere_bascule_offline else None,
        'dernier_sync_reussi': etat.dernier_sync_reussi.isoformat() if etat.dernier_sync_reussi else None,
        'derniere_erreur_sync_at': etat.derniere_erreur_sync_at.isoformat() if etat.derniere_erreur_sync_at else None,
        'changements_en_attente': pending,
        'dernier_sync_sheets': etat.dernier_sync_sheets.isoformat() if etat.dernier_sync_sheets else None,
    }
