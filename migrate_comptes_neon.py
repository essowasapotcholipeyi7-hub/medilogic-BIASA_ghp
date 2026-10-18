# -*- coding: utf-8 -*-
"""Migration 2026-10-18 — étape 1 de l'abandon de Google Sheets : comptes des structures (feuille
« structures ») et du personnel (feuilles « struct_N_users ») copiés dans Neon (tables `structures` et
`comptes_utilisateurs`). Voir services/comptes_service.py.

    python migrate_comptes_neon.py              tables + copie (refusée si Neon a déjà des comptes)
    python migrate_comptes_neon.py --forcer     recopie depuis Google Sheets (ÉCRASE Neon)
    python migrate_comptes_neon.py --comparer   montre les différences Google Sheets / Neon, sans rien écrire

Google Sheets n'est jamais modifié."""
import sys

from app import app
from models import db
from services import comptes_service as cs


def creer_tables():
    for sql in (
        # textes sans limite (Google Sheets n'en avait pas)
        "ALTER TABLE structures ALTER COLUMN nom TYPE TEXT",
        "ALTER TABLE structures ALTER COLUMN telephone TYPE TEXT",
        "ALTER TABLE structures ALTER COLUMN email TYPE TEXT",
        "ALTER TABLE structures ALTER COLUMN statut TYPE TEXT",
        "ALTER TABLE structures ALTER COLUMN logo_url TYPE TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS mot_de_passe TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS token TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS date_inscription TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS proprietaire TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS date_occupation TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS derniere_connexion TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS reset_token TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS reset_token_expiry TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS webauthn_credentials TEXT",
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS entete_a4 TEXT",
        # vrai compte (les autres lignes ne servent qu'aux liens de la base)
        "ALTER TABLE structures ADD COLUMN IF NOT EXISTS est_compte BOOLEAN NOT NULL DEFAULT false",
        """CREATE TABLE IF NOT EXISTS comptes_utilisateurs (
               id SERIAL PRIMARY KEY,
               structure_id INTEGER NOT NULL,
               sheet_id INTEGER NOT NULL,
               nom TEXT, email TEXT, mot_de_passe TEXT, role TEXT, structure_id_ligne TEXT, created_at TEXT,
               actif TEXT, derniere_connexion TEXT, reset_token TEXT, reset_token_expiry TEXT, webauthn_credentials TEXT,
               supprime BOOLEAN NOT NULL DEFAULT false,
               UNIQUE (structure_id, sheet_id))""",
        "CREATE INDEX IF NOT EXISTS ix_comptes_utilisateurs_email ON comptes_utilisateurs (lower(email))",
    ):
        db.session.execute(db.text(sql))
    db.session.commit()
    print("OK : tables des comptes")


def lire_sheets():
    """{'structures': [dict], 'struct_N_users': [dict]} lus directement dans Google Sheets (valeurs brutes)."""
    from sheets_helper import sheets_helper
    sp = sheets_helper.spreadsheet
    titres = ['structures'] + [w.title for w in sp.worksheets() if cs.feuille_comptes(w.title) and w.title != 'structures']
    plages = sp.values_batch_get([f"'{t}'" for t in titres])['valueRanges']
    res = {}
    for titre, plage in zip(titres, plages):
        valeurs = plage.get('values', [])
        entetes = cs.ENTETES_STRUCTURES if titre == 'structures' else cs.ENTETES_UTILISATEURS
        lignes = []
        for ligne in valeurs[1:]:
            ligne = list(ligne) + [''] * (len(entetes) - len(ligne))
            d = dict(zip(entetes, ligne[:len(entetes)]))
            if str(d.get('ID') or '').strip().lstrip('-').isdigit():
                lignes.append(d)
        res[titre] = lignes
    return res


def copier(forcer=False):
    deja = cs.executer("SELECT count(*) AS n FROM structures WHERE est_compte")[0]['n']
    if deja and not forcer:
        print(f"Neon a déjà {deja} compte(s) de structure : rien copié (--forcer pour recopier depuis Google Sheets, --comparer pour voir les écarts).")
        return
    donnees = lire_sheets()
    for d in donnees['structures']:
        cs.ajouter('structures', d)
    n_u = 0
    for titre, lignes in donnees.items():
        if titre == 'structures':
            continue
        _, sid = cs.feuille_comptes(titre)
        for d in lignes:
            valeurs = {c: d.get(e, '') for e, c in cs._COL_UTILISATEURS.items() if e != 'ID'}
            cols = list(valeurs)
            cs.executer(f"""INSERT INTO comptes_utilisateurs (structure_id, sheet_id, {', '.join(cols)})
                            VALUES (%s, %s, {', '.join(['%s'] * len(cols))})
                            ON CONFLICT (structure_id, sheet_id) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in cols)}, supprime = false""",
                        [sid, int(d['ID'])] + [valeurs[c] for c in cols], lire=False)
            n_u += 1
    print(f"OK : {len(donnees['structures'])} structure(s) et {n_u} compte(s) du personnel copiés dans Neon")


def comparer():
    donnees = lire_sheets()
    ecarts = 0
    for titre, lignes in donnees.items():
        neon = {str(r['ID']): r for r in cs.lister(titre, numeriser=False)}
        sheets = {str(d['ID']).strip(): d for d in lignes}
        for ident in sorted(set(neon) | set(sheets), key=lambda x: int(x)):
            a, b = sheets.get(ident), neon.get(ident)
            if a is None or b is None:
                print(f"  {titre} ID {ident} : {'absent de Google Sheets' if a is None else 'absent de Neon'}")
                ecarts += 1
                continue
            diff = [k for k in a if k != 'ID' and str(a.get(k) or '') != str(b.get(k) or '')]
            masque = {'mot_de_passe', 'token', 'reset_token', 'webauthn_credentials'}
            if diff:
                ecarts += 1
                print(f"  {titre} ID {ident} : " + ', '.join(
                    f"{k} (secret différent)" if k in masque else f"{k} Sheets={a.get(k)!r} Neon={b.get(k)!r}" for k in diff))
    print(f"{ecarts} écart(s)")


if __name__ == '__main__':
    with app.app_context():
        if '--comparer' in sys.argv:
            comparer()
        else:
            creer_tables()
            copier(forcer='--forcer' in sys.argv)
