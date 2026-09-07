# utils/sheets_mirror.py
"""
Miroir local en LECTURE SEULE de certaines feuilles Google Sheets, pour que
l'appli (y compris la connexion) reste utilisable quand Google Sheets est
injoignable (coupure internet) — voir aussi utils/db_failover.py pour la
bascule Neon <-> Postgres local, un mécanisme complémentaire mais distinct.

Sens unique : Sheets -> Postgres local (table SheetsMirror, bind 'local').
Ce n'est PAS un système de saisie hors-ligne : on ne peut pas ajouter un
nouveau médicament/acte pendant une coupure, seulement consulter la
dernière version connue (rafraîchie automatiquement toutes les
~10 minutes pendant que la connexion est bonne).

Inactif si DATABASE_URL_LOCAL n'est pas définie (voir db_failover.FAILOVER_ENABLED).
"""

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger('sheets_mirror')

# Feuilles préfixées par structure : struct_{id}_<nom>
SHEET_TYPES_PAR_STRUCTURE = ['actes', 'produits', 'users', 'lunettes']

# Google Sheets limite à 60 lectures/minute/utilisateur : on espace les
# appels pour ne jamais s'en approcher, même avec ~30 structures à parcourir.
DELAI_ENTRE_APPELS_SHEETS = 1.1  # secondes

# Empêche deux passes de synchro de tourner en même temps (watchdog +
# déclenchement manuel) : sans ça, on double le nombre d'appels Sheets et on
# se fait vite jeter par le quota.
_sync_lock = threading.Lock()


def sync_structure(structure_id):
    """Rafraîchit le miroir local pour une structure donnée.

    Construit le nom de feuille complet nous-mêmes et appelle
    get_all_records(..., use_prefix=False) plutôt que de passer par
    sheets_helper.set_structure() : ce dernier modifie un état partagé sur
    l'instance unique sheets_helper (self.structure_prefix), que d'autres
    threads (une requête web concurrente pour une autre structure) peuvent
    changer pendant cette boucle — ce qui mélangerait les données de
    structures différentes. En construisant le nom nous-mêmes, cette
    fonction reste correcte quel que soit ce qui se passe ailleurs."""
    from models import db
    from sheets_helper import sheets_helper

    if not sheets_helper.enabled:
        return False

    total = 0
    for sheet_type in SHEET_TYPES_PAR_STRUCTURE:
        time.sleep(DELAI_ENTRE_APPELS_SHEETS)
        sheet_name = f"struct_{structure_id}_{sheet_type}"
        try:
            records = sheets_helper.get_all_records(sheet_name, use_prefix=False, force_refresh=True)
        except Exception:
            logger.exception("Sheets mirror : échec lecture %s pour structure %s", sheet_type, structure_id)
            continue
        keys_vus = set()
        for rec in records:
            row_key = str(rec.get('ID') or rec.get('id') or '').strip()
            if not row_key:
                continue
            _upsert(structure_id, sheet_type, row_key, rec)
            keys_vus.add(row_key)
            total += 1
        # Ne purge que si on a reçu des données valides : une réponse vide
        # accidentelle (glitch réseau) ne doit pas effacer tout le miroir.
        if records:
            _purge_absent(structure_id, sheet_type, keys_vus)
    db.session.commit()
    logger.info("Sheets mirror : structure %s -> %d ligne(s)", structure_id, total)
    return True


def sync_structures_globales():
    """Rafraîchit le miroir de la feuille globale 'structures' (infos
    nom/adresse/logo/identifiants par structure). Jamais purgé (données
    précieuses, suppression rarissime : mieux vaut une entrée périmée
    qu'une perte accidentelle)."""
    from models import db
    from sheets_helper import sheets_helper

    if not sheets_helper.enabled:
        return False
    try:
        records = sheets_helper.get_all_records('structures', use_prefix=False, force_refresh=True)
    except Exception:
        logger.exception("Sheets mirror : échec lecture structures globales")
        return False
    for rec in records:
        sid = str(rec.get('ID') or '').strip()
        if not sid:
            continue
        try:
            _upsert(int(sid), 'structures', sid, rec)
        except (TypeError, ValueError):
            continue
    db.session.commit()
    return True


def _upsert(structure_id, sheet_type, row_key, data):
    # INSERT ... ON CONFLICT DO UPDATE plutôt qu'un "SELECT puis INSERT/UPDATE" :
    # évite toute course si deux passes de synchro se chevauchent (watchdog +
    # appel manuel), et c'est plus rapide.
    from models import db
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from models import SheetsMirror

    stmt = pg_insert(SheetsMirror.__table__).values(
        structure_id=structure_id, sheet_type=sheet_type, row_key=row_key,
        data=data, updated_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=['structure_id', 'sheet_type', 'row_key'],
        set_={'data': stmt.excluded.data, 'updated_at': stmt.excluded.updated_at},
    )
    db.session.execute(stmt)


def _purge_absent(structure_id, sheet_type, present_keys):
    from models import db, SheetsMirror
    stale = SheetsMirror.query.filter_by(structure_id=structure_id, sheet_type=sheet_type) \
        .filter(~SheetsMirror.row_key.in_(present_keys)).all()
    for row in stale:
        db.session.delete(row)


def sync_all(structure_ids=None):
    """Rafraîchit le miroir pour toutes les structures connues (ou une
    liste donnée). Utilisé au démarrage et périodiquement par le watchdog
    de utils/db_failover.py. Sans effet si une autre passe est déjà en
    cours (évite de doubler les appels Sheets et de se faire limiter)."""
    from models import Structure, SyncState, db

    if not _sync_lock.acquire(blocking=False):
        logger.info("Sheets mirror : synchro déjà en cours, passage ignoré")
        return 0
    try:
        sync_structures_globales()
        if structure_ids is None:
            structure_ids = [s.id for s in Structure.query.all()]
        ok = 0
        for sid in structure_ids:
            try:
                if sync_structure(sid):
                    ok += 1
            except Exception:
                logger.exception("Sheets mirror : échec pour structure %s", sid)

        try:
            etat = SyncState.get_ou_creer()
            etat.dernier_sync_sheets = datetime.utcnow()
            db.session.commit()
        except Exception:
            db.session.rollback()

        logger.info("Sheets mirror : %d/%d structure(s) synchronisée(s)", ok, len(structure_ids))
        return ok
    finally:
        _sync_lock.release()


def get_mirrored_records(structure_id, sheet_type):
    """Repli utilisé par sheets_helper.get_all_records() quand Sheets est
    injoignable — même format qu'un appel Sheets réussi (liste de dict)."""
    from models import SheetsMirror
    rows = SheetsMirror.query.filter_by(structure_id=structure_id, sheet_type=sheet_type).all()
    return [r.data for r in rows]


def get_all_mirrored_structures():
    from models import SheetsMirror
    rows = SheetsMirror.query.filter_by(sheet_type='structures').all()
    return [r.data for r in rows]


def tenter_connexion_hors_ligne(email, mot_de_passe_hash):
    """Tentative de connexion via le miroir local, utilisée par app.py/index()
    quand Google Sheets est injoignable. Reproduit la même logique que la
    connexion en ligne (utilisateur d'une structure, puis compte
    propriétaire de structure). Retourne un dict de champs de session en
    cas de succès, sinon None."""
    from models import SheetsMirror

    # 1) Utilisateur d'une structure (feuille struct_X_users)
    for row in SheetsMirror.query.filter_by(sheet_type='users').all():
        u = row.data or {}
        if str(u.get('email')) != email:
            continue
        if u.get('actif', 'oui') != 'oui':
            continue
        if u.get('mot_de_passe') != mot_de_passe_hash:
            continue
        structure_row = SheetsMirror.query.filter_by(
            sheet_type='structures', structure_id=row.structure_id).first()
        structure = structure_row.data if structure_row else {}
        if structure.get('statut') != 'active':
            continue
        return {
            'user_id': u.get('ID'), 'user_name': u.get('nom'),
            'structure_id': row.structure_id, 'structure_nom': structure.get('nom'),
            'structure_email': structure.get('email', ''),
            'structure_logo': structure.get('logo_url', ''),
            'structure_telephone': structure.get('telephone', ''),
            'role': u.get('role', 'caissier'),
            'is_admin': u.get('role') == 'admin',
        }

    # 2) Compte propriétaire de structure (feuille globale structures)
    for row in SheetsMirror.query.filter_by(sheet_type='structures').all():
        s = row.data or {}
        if str(s.get('email')) != email:
            continue
        if s.get('mot_de_passe') != mot_de_passe_hash:
            continue
        if s.get('statut') != 'active':
            continue
        return {
            'user_id': s.get('ID'), 'user_name': s.get('nom'),
            'structure_id': s.get('ID'), 'structure_nom': s.get('nom'),
            'structure_email': s.get('email', ''),
            'structure_logo': s.get('logo_url', ''),
            'structure_telephone': s.get('telephone', ''),
            'role': 'admin', 'is_admin': True,
        }
    return None
