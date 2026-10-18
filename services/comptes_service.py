# -*- coding: utf-8 -*-
"""Comptes dans Neon — étape 1 de l'abandon de Google Sheets (patron, 2026-10-18 : « importe tout dans
la base Neon et abandonne le Sheets, vu qu'elle ralentit les requêtes »).

Avant : la feuille « structures » (comptes des responsables, nom, logo, en-tête des reçus...) et les
feuilles « struct_N_users » (comptes du personnel). Maintenant : la table `structures` (déjà là, avec les
liens de la base) et la table `comptes_utilisateurs`. Les numéros (ID) sont ceux de Google Sheets : de
nombreuses tables les gardent (messages, signatures, rôles supplémentaires...).

sheets_helper renvoie ici toute lecture / écriture de ces feuilles (get_all_records, update_record_by_id,
add_record, delete_record_by_id) avec EXACTEMENT la forme qu'avait Google Sheets (mêmes noms de colonnes,
mêmes conversions de nombres) : le reste du code n'a pas à changer. Google Sheets n'est plus ni lu ni
écrit pour les comptes ; ses feuilles restent telles quelles, comme copie de secours.

Connexions à part (pool psycopg2) : marche sans contexte Flask (tâches de fond, mode hors ligne) et
remonte les erreurs, contrairement à db_helper."""
import re
import threading
from datetime import datetime

ENTETES_STRUCTURES = ['ID', 'nom', 'email', 'telephone', 'adresse', 'mot_de_passe', 'statut', 'token',
                      'date_inscription', 'proprietaire', 'date_occupation', 'logo_url', 'derniere_connexion',
                      'reset_token', 'reset_token_expiry', 'webauthn_credentials', 'entete_a4']
ENTETES_UTILISATEURS = ['ID', 'nom', 'email', 'mot_de_passe', 'role', 'structure_id', 'created_at', 'actif',
                        'derniere_connexion', 'reset_token', 'reset_token_expiry', 'webauthn_credentials']
# colonne de la feuille -> colonne de la table
_COL_STRUCTURES = {e: ('id' if e == 'ID' else e) for e in ENTETES_STRUCTURES}
_COL_UTILISATEURS = {e: {'ID': 'sheet_id', 'structure_id': 'structure_id_ligne'}.get(e, e) for e in ENTETES_UTILISATEURS}
_RE_USERS = re.compile(r'^struct_(-?\d+)_users$')

_pool = None
_verrou_pool = threading.Lock()


def _obtenir_pool():
    global _pool
    if _pool is None:
        with _verrou_pool:
            if _pool is None:
                from psycopg2.pool import ThreadedConnectionPool
                from config import Config
                _pool = ThreadedConnectionPool(1, 8, Config.DATABASE_URL)
    return _pool


def executer(sql, params=None, lire=True):
    """Exécute une requête et valide ; une connexion coupée par Neon (inactivité) est remplacée et la
    requête rejouée une fois. Les erreurs remontent (jamais avalées)."""
    import psycopg2
    import psycopg2.extras
    pool = _obtenir_pool()
    for essai in (1, 2):
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                lignes = cur.fetchall() if (lire and cur.description) else None
                compte = cur.rowcount
            conn.commit()
            pool.putconn(conn)
            return lignes if lire else compte
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            try:
                pool.putconn(conn, close=True)
            except Exception:
                pass
            if essai == 2:
                raise
        except Exception:
            try:
                conn.rollback()
            finally:
                pool.putconn(conn)
            raise


# ------------------------------------------------------------------ feuilles
def feuille_comptes(sheet_name):
    """('structures', None) | ('users', structure_id) | None si la feuille n'est pas une feuille de comptes."""
    if sheet_name == 'structures':
        return ('structures', None)
    m = _RE_USERS.match(sheet_name or '')
    if m:
        return ('users', int(m.group(1)))
    return None


def _texte(v):
    if v is None:
        return ''
    return v if isinstance(v, str) else str(v)


def _forme_feuille(ligne, entetes, colonnes, numeriser=True):
    """Ligne de la table -> dict avec les noms de colonnes de la feuille ; numeriser=True : mêmes
    conversions que gspread get_all_records() (« 12 » -> 12, « 9042OO58 » reste un texte)."""
    valeurs = [_texte(ligne.get(colonnes[e])) for e in entetes]
    if numeriser:
        from gspread.utils import numericise_all
        valeurs = numericise_all(valeurs, empty2zero=False, default_blank='')
    return dict(zip(entetes, valeurs))


def _lignes_structures(numeriser=True):
    lignes = executer(f"SELECT {', '.join(_COL_STRUCTURES.values())} FROM structures WHERE est_compte ORDER BY id")
    return [_forme_feuille(l, ENTETES_STRUCTURES, _COL_STRUCTURES, numeriser) for l in lignes]


def _lignes_utilisateurs(structure_id=None, numeriser=True):
    cols = ', '.join(dict.fromkeys(list(_COL_UTILISATEURS.values()) + ['structure_id']))
    if structure_id is None:
        lignes = executer(f"SELECT {cols} FROM comptes_utilisateurs WHERE NOT supprime ORDER BY structure_id, sheet_id")
    else:
        lignes = executer(f"SELECT {cols} FROM comptes_utilisateurs WHERE NOT supprime AND structure_id = %s ORDER BY sheet_id",
                          (structure_id,))
    return [(l['structure_id'], _forme_feuille(l, ENTETES_UTILISATEURS, _COL_UTILISATEURS, numeriser)) for l in lignes]


def lister(sheet_name, numeriser=True):
    """Équivalent de get_all_records() pour une feuille de comptes."""
    genre, structure_id = feuille_comptes(sheet_name)
    if genre == 'structures':
        return _lignes_structures(numeriser)
    return [r for _, r in _lignes_utilisateurs(structure_id, numeriser)]


def utilisateurs_par_feuille():
    """{'struct_N_users': [comptes en texte brut]} — pour la connexion (toutes les structures d'un coup)."""
    res = {}
    for sid, r in _lignes_utilisateurs(None, numeriser=False):
        res.setdefault(f"struct_{sid}_users", []).append(r)
    return res


def trouver(sheet_name, id_compte):
    """Le compte (texte brut) ou None."""
    return next((r for r in lister(sheet_name, numeriser=False) if str(r.get('ID')).strip() == str(id_compte).strip()), None)


# ------------------------------------------------------------------ écritures
def _id_entier(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def maj_par_id(sheet_name, id_compte, champs, id_column='ID'):
    """Équivalent de update_record_by_id() : seules les colonnes connues sont écrites. True si trouvé."""
    genre, structure_id = feuille_comptes(sheet_name)
    colonnes = _COL_STRUCTURES if genre == 'structures' else _COL_UTILISATEURS
    sets, params = [], []
    for cle, valeur in (champs or {}).items():
        if cle in colonnes and cle != 'ID':
            col = colonnes[cle]
            sets.append(f"{col} = %s")
            v = None if valeur is None else _texte(valeur)
            if genre == 'structures' and col == 'email':
                v = (v.strip() or None) if v is not None else None   # e-mail unique : vide = NULL
            params.append(v)
    if not sets:
        return trouver(sheet_name, id_compte) is not None
    if id_column != 'ID':
        cle_col = colonnes.get(id_column)
        if not cle_col:
            return False
        cible = trouver_par(sheet_name, id_column, id_compte)
        if not cible:
            return False
        id_compte = cible.get('ID')
    ident = _id_entier(id_compte)
    if ident is None:
        return False
    if genre == 'structures':
        import psycopg2
        try:
            n = executer(f"UPDATE structures SET {', '.join(sets)} WHERE id = %s AND est_compte", params + [ident], lire=False)
        except psycopg2.errors.UniqueViolation:
            raise ValueError("Cet e-mail est déjà utilisé par une autre structure.")
    else:
        n = executer(f"UPDATE comptes_utilisateurs SET {', '.join(sets)} WHERE structure_id = %s AND sheet_id = %s AND NOT supprime",
                     params + [structure_id, ident], lire=False)
    return bool(n)


def trouver_par(sheet_name, colonne, valeur):
    return next((r for r in lister(sheet_name, numeriser=False) if str(r.get(colonne)).strip() == str(valeur).strip()), None)


def ajouter(sheet_name, donnees):
    """Équivalent de add_record() : `donnees` = liste dans l'ordre des colonnes de la feuille, ou dict.
    Renvoie l'ID du compte."""
    genre, structure_id = feuille_comptes(sheet_name)
    entetes = ENTETES_STRUCTURES if genre == 'structures' else ENTETES_UTILISATEURS
    if isinstance(donnees, (list, tuple)):
        donnees = dict(zip(entetes, list(donnees)))
    donnees = dict(donnees)
    if genre == 'structures':
        ident = _id_entier(donnees.get('ID'))
        if ident is None:
            ident = (executer("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM structures WHERE est_compte")[0]['n'])
        valeurs = {c: (None if donnees.get(e) is None else _texte(donnees.get(e)))
                   for e, c in _COL_STRUCTURES.items() if e != 'ID'}
        valeurs['email'] = (valeurs.get('email') or '').strip() or None
        cols = list(valeurs)
        executer(f"""INSERT INTO structures (id, {', '.join(cols)}, est_compte) VALUES (%s, {', '.join(['%s'] * len(cols))}, true)
                     ON CONFLICT (id) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in cols)}, est_compte = true""",
                 [ident] + [valeurs[c] for c in cols], lire=False)
        return ident
    ident = _id_entier(donnees.get('ID'))
    if ident is None:
        ident = prochain_id_utilisateur(structure_id)
    valeurs = {c: (None if donnees.get(e) is None else _texte(donnees.get(e)))
               for e, c in _COL_UTILISATEURS.items() if e != 'ID'}
    if not valeurs.get('structure_id_ligne'):
        valeurs['structure_id_ligne'] = str(structure_id)
    cols = list(valeurs)
    executer(f"""INSERT INTO comptes_utilisateurs (structure_id, sheet_id, {', '.join(cols)})
                 VALUES (%s, %s, {', '.join(['%s'] * len(cols))})""",
             [structure_id, ident] + [valeurs[c] for c in cols], lire=False)
    return ident


def prochain_id_utilisateur(structure_id):
    """Numéro suivant, comptes supprimés compris : un numéro n'est jamais réattribué (les messages, rôles,
    signatures d'un ancien compte ne passent pas à un nouveau)."""
    return executer("SELECT COALESCE(MAX(sheet_id), 0) + 1 AS n FROM comptes_utilisateurs WHERE structure_id = %s",
                    (structure_id,))[0]['n']


def supprimer_par_id(sheet_name, id_compte):
    """Équivalent de delete_record_by_id(). Compte du personnel : marqué supprimé (numéro gardé) ;
    structure : retirée des comptes (la ligne reste pour les liens de la base)."""
    genre, structure_id = feuille_comptes(sheet_name)
    ident = _id_entier(id_compte)
    if ident is None:
        return False
    if genre == 'structures':
        n = executer("UPDATE structures SET est_compte = false, email = NULL WHERE id = %s AND est_compte", (ident,), lire=False)
    else:
        n = executer("UPDATE comptes_utilisateurs SET supprime = true WHERE structure_id = %s AND sheet_id = %s AND NOT supprime",
                     (structure_id, ident), lire=False)
    return bool(n)


def email_deja_utilise(email, structure_id=None, sauf_id=None):
    """Vrai si un autre compte (personnel de n'importe quelle structure, ou responsable) a cet e-mail :
    la connexion ne saurait pas lequel ouvrir."""
    email = (email or '').strip().lower()
    if not email:
        return False
    for l in executer("SELECT structure_id, sheet_id FROM comptes_utilisateurs WHERE NOT supprime AND lower(trim(email)) = %s", (email,)):
        if not (structure_id is not None and l['structure_id'] == structure_id and sauf_id is not None
                and str(l['sheet_id']) == str(sauf_id)):
            return True
    return bool(executer("SELECT 1 FROM structures WHERE est_compte AND lower(trim(email)) = %s", (email,)))


def marquer_connexion(sheet_name, id_compte):
    """Date de dernière connexion (même format qu'avant : jj/mm/aaaa hh:mm:ss)."""
    try:
        return maj_par_id(sheet_name, id_compte, {'derniere_connexion': datetime.now().strftime('%d/%m/%Y %H:%M:%S')})
    except Exception as e:
        print(f"⚠️ Dernière connexion ({sheet_name} {id_compte}) : {e}")
        return False
