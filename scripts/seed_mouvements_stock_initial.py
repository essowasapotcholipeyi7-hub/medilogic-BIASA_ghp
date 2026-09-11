"""
Amorce `mouvements_stock` avec un point de départ "initial" pour chaque
produit déjà existant, sur TOUTES les structures — sinon le nouvel
historique de stock serait vide pour tout ce qui existait avant la mise en
place de cette fonctionnalité (aucun mouvement passé n'a jamais été
journalisé). Idempotent : ignore un produit qui a déjà un mouvement
'initial' enregistré (structure_id + produit_id), donc relançable sans
risque de doublon.

Parcourt toutes les feuilles Google Sheets `struct_<id>_produits` déjà
présentes dans le classeur (une par structure), lit le stock actuel
(colonne F) de chaque produit, et insère 1 ligne 'initial' par produit
avec stock_apres = ce stock actuel et quantite_delta = ce même stock
(convention : on part de 0).

IMPORTANT : ceci ne fabrique PAS d'historique rétroactif réel — c'est un
point de départ daté d'aujourd'hui. Le "stock à la date T" ne sera fiable
qu'à partir du jour où ce script a tourné ; avant, la page l'indique
clairement (voir /api/produits/stock-a-date dans app.py).

Usage :
    python scripts/seed_mouvements_stock_initial.py
"""
import io
import os
import re
import sys
from datetime import datetime, timedelta

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from db_helper import db as db_helper
from sheets_helper import sheets_helper

if __name__ == "__main__":
    # Daté juste avant le début du jour où ce script tourne (23:59:59.999999
    # la veille), pas "maintenant" — sinon /api/produits/stock-a-date (qui
    # exclut volontairement les mouvements DU jour choisi, pour que
    # "aujourd'hui" compare le début de journée au stock actuel plutôt que
    # de se comparer à lui-même) ne trouverait aucun point de départ pour
    # le jour même du seed.
    date_seed = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                 - timedelta(microseconds=1))
    all_sheets = sheets_helper.spreadsheet.worksheets()
    produits_sheets = [
        ws for ws in all_sheets
        if re.match(r"^struct_\d+_produits$", ws.title)
    ]
    print(f"📂 {len(produits_sheets)} feuille(s) struct_*_produits trouvée(s)")

    total_inserted = 0
    total_skipped = 0

    for ws in produits_sheets:
        m = re.match(r"^struct_(\d+)_produits$", ws.title)
        structure_id = int(m.group(1))

        already = db_helper.execute_query(
            "SELECT produit_id FROM mouvements_stock "
            "WHERE structure_id = %s AND type_mouvement = 'initial'",
            (structure_id,)
        )
        deja_ids = {str(r['produit_id']) for r in (already or [])}

        rows = ws.get_all_values()
        inserted_here = 0
        for row in rows[1:]:
            if not row or len(row) < 2:
                continue
            produit_id = (row[0] or '').strip()
            nom = (row[1] or '').strip() if len(row) > 1 else ''
            if not produit_id or not nom:
                continue
            if produit_id in deja_ids:
                total_skipped += 1
                continue
            stock_raw = row[5].strip() if len(row) > 5 and row[5] else '0'
            try:
                stock_actuel = int(float(stock_raw)) if stock_raw else 0
            except ValueError:
                stock_actuel = 0

            db_helper.execute_query("""
                INSERT INTO mouvements_stock
                    (structure_id, produit_id, produit_nom, type_mouvement,
                     quantite_delta, stock_apres, date_mouvement, created_by_nom)
                VALUES (%s, %s, %s, 'initial', %s, %s, %s, 'Système (seed initial)')
            """, (structure_id, produit_id, nom, stock_actuel, stock_actuel, date_seed))
            inserted_here += 1
            total_inserted += 1

        if inserted_here:
            print(f"   struct_{structure_id}_produits : {inserted_here} produit(s) amorcé(s)")

    print(f"✅ Terminé — {total_inserted} mouvement(s) 'initial' créé(s), {total_skipped} déjà présent(s)")
