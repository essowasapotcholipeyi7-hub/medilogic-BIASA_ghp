# -*- coding: utf-8 -*-
"""Migration 2026-10-18 — étape 2 de l'abandon de Google Sheets : feuilles de produits (struct_N_produits,
stock compris) copiées dans Neon, ligne par ligne, à l'identique (mêmes numéros de ligne, mêmes textes).
Voir services/feuilles_neon.py.

    python migrate_produits_neon.py              tables + copie (refusée si Neon a déjà des produits)
    python migrate_produits_neon.py --forcer     recopie depuis Google Sheets (ÉCRASE Neon)
    python migrate_produits_neon.py --comparer   différences Google Sheets / Neon, sans rien écrire
    ... --instantane=f.json                     garde aussi la copie de Google faite à ce moment-là
    python migrate_produits_neon.py --rattraper=f.json
        après la mise en ligne : reporte dans Neon les mouvements de stock que l'ancienne version a encore
        écrits chez Google entre la copie et la mise en ligne (stock Google maintenant - stock de la copie)

    --famille=actes                             étape 3 : feuilles d'actes au lieu des produits
                                                (une seule famille à la fois : ne jamais recopier les
                                                produits par-dessus les ventes faites dans Neon)

Google Sheets n'est jamais modifié."""
import json
import sys

from app import app
from models import db
from services.comptes_service import executer, executer_lot
from services.feuilles_neon import est_feuille_neon, FeuilleNeon


def creer_tables():
    for sql in (
        """CREATE TABLE IF NOT EXISTS feuilles_neon (
               feuille TEXT PRIMARY KEY,
               created_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'))""",
        """CREATE TABLE IF NOT EXISTS feuilles_neon_lignes (
               feuille TEXT NOT NULL,
               rang INTEGER NOT NULL,
               valeurs JSONB NOT NULL DEFAULT '[]'::jsonb,
               CONSTRAINT feuilles_neon_lignes_pk PRIMARY KEY (feuille, rang))""",
        # (une 1re version avait une clé « DEFERRABLE », incompatible avec ON CONFLICT : remplacée)
        """DO $$ BEGIN
               IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'feuilles_neon_lignes_pk' AND condeferrable) THEN
                   ALTER TABLE feuilles_neon_lignes DROP CONSTRAINT feuilles_neon_lignes_pk;
                   ALTER TABLE feuilles_neon_lignes ADD CONSTRAINT feuilles_neon_lignes_pk PRIMARY KEY (feuille, rang);
               END IF;
           END $$""",
        "CREATE INDEX IF NOT EXISTS ix_feuilles_neon_lignes_id ON feuilles_neon_lignes (feuille, (trim(valeurs->>0)))",
        # numéro de version de chaque feuille (copies en mémoire, voir services/feuilles_neon.py)
        "ALTER TABLE feuilles_neon ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0",
    ):
        db.session.execute(db.text(sql))
    db.session.commit()
    print("OK : tables des feuilles Neon")


def _famille():
    f = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--famille=')), 'produits')
    if f not in ('produits', 'actes'):
        raise SystemExit("--famille=produits ou --famille=actes")
    return f


def _de_la_famille(titre):
    import re
    return est_feuille_neon(titre) and re.fullmatch(rf'struct_-?\d+_{_famille()}', titre) is not None


def lire_google():
    """{titre: lignes} pour les feuilles de la famille choisie, lues directement chez Google."""
    from sheets_helper import sheets_helper
    google = getattr(sheets_helper.spreadsheet, '_google', sheets_helper.spreadsheet)
    titres = [w.title for w in google.worksheets() if _de_la_famille(w.title)]
    plages = google.values_batch_get([f"'{t}'" for t in titres])['valueRanges']
    return {t: p.get('values', []) for t, p in zip(titres, plages)}


def _option(nom):
    return next((a.split('=', 1)[1] for a in sys.argv if a.startswith(f'--{nom}=')), None)


def copier(forcer=False):
    deja = executer("SELECT count(*) AS n FROM feuilles_neon_lignes WHERE feuille LIKE %s", (f"%\\_{_famille()}",))[0]['n']
    if deja and not forcer:
        print(f"Neon a déjà {deja} ligne(s) de feuilles : rien copié (--forcer pour recopier, --comparer pour voir les écarts).")
        return
    total = 0
    donnees = lire_google()
    if _option('instantane'):
        json.dump(donnees, open(_option('instantane'), 'w', encoding='utf8'), ensure_ascii=False)
    for titre, lignes in donnees.items():
        executer("INSERT INTO feuilles_neon (feuille) VALUES (%s) ON CONFLICT DO NOTHING", (titre,), lire=False)
        executer("DELETE FROM feuilles_neon_lignes WHERE feuille = %s", (titre,), lire=False)
        if lignes:
            executer_lot("INSERT INTO feuilles_neon_lignes (feuille, rang, valeurs) VALUES %s",
                         [(titre, rang, json.dumps([str(c) for c in ligne], ensure_ascii=False))
                          for rang, ligne in enumerate(lignes, start=1)], modele="(%s, %s, %s::jsonb)")
        executer("UPDATE feuilles_neon SET version = version + 1 WHERE feuille = %s", (titre,), lire=False)
        total += max(len(lignes) - 1, 0)
        print(f"  {titre} : {max(len(lignes) - 1, 0)} produit(s)")
    print(f"OK : {total} ligne(s) de {_famille()} copiées dans Neon")


def comparer():
    ecarts = 0
    for titre, lignes in lire_google().items():
        largeur = max((len(r) for r in lignes), default=0)
        google = [list(r) + [''] * (largeur - len(r)) for r in lignes]
        while google and not any(c != '' for c in google[-1]):
            google.pop()
        neon = FeuilleNeon(titre).get_all_values()
        if google != neon:
            ecarts += 1
            n = next((i for i, (a, b) in enumerate(zip(google, neon)) if a != b), min(len(google), len(neon)))
            print(f"  {titre} : {len(google)} ligne(s) chez Google, {len(neon)} dans Neon ; 1re différence ligne {n + 1}")
    print(f"{ecarts} feuille(s) différente(s)")


def _stock(ligne):
    try:
        v = str(ligne[5] if len(ligne) > 5 else '').strip().replace(',', '.')
        return int(float(v)) if v else 0
    except ValueError:
        return 0


def rattraper(fichier):
    if _famille() != 'produits':
        raise SystemExit("--rattraper ne concerne que les produits (stock)")
    _rattraper_produits(fichier)


def _rattraper_produits(fichier):
    """Stock Google maintenant - stock Google au moment de la copie = ce que l'ancienne version a vendu ou
    reçu entre-temps -> reporté dans Neon. Les autres changements (prix, nouveaux produits) sont signalés."""
    from services.feuilles_neon import ajuster_stock
    avant = json.load(open(fichier, encoding='utf8'))
    maintenant = lire_google()
    for titre, lignes in maintenant.items():
        anciens = {str(l[0]).strip(): l for l in avant.get(titre, [])[1:] if l and str(l[0]).strip()}
        for l in lignes[1:]:
            pid = str(l[0]).strip() if l else ''
            if not pid:
                continue
            if pid not in anciens:
                print(f"  {titre} : produit {pid} ajouté chez Google après la copie — à ressaisir dans le logiciel")
                continue
            delta = _stock(l) - _stock(anciens[pid])
            if delta:
                r = ajuster_stock(titre, pid, delta)
                print(f"  {titre} : produit {pid} ({l[1] if len(l) > 1 else ''}) stock {delta:+d} -> {r[1] if r else 'introuvable dans Neon'}")
            autres = [i for i in range(max(len(l), len(anciens[pid]))) if i != 5
                      and (l[i] if i < len(l) else '') != (anciens[pid][i] if i < len(anciens[pid]) else '')]
            if autres:
                print(f"  {titre} : produit {pid} modifié chez Google après la copie (colonnes {[c + 1 for c in autres]}) — à vérifier")
    print("Rattrapage terminé")


if __name__ == '__main__':
    with app.app_context():
        if _option('rattraper'):
            rattraper(_option('rattraper'))
        elif '--comparer' in sys.argv:
            comparer()
        else:
            creer_tables()
            copier(forcer='--forcer' in sys.argv)
