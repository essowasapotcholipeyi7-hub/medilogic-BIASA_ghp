"""
Crée la table `mouvements_stock` (ledger d'historique des stocks produits),
si elle n'existe pas déjà. Idempotent — peut être relancé sans risque.

Chaque ligne = un événement qui a changé le stock d'un produit (Google
Sheets `struct_<id>_produits`, colonne F) : vente, réapprovisionnement,
annulation de vente, ajustement manuel, ou point de départ initial. Stocke
`stock_apres` (le stock résultant juste après l'événement) pour pouvoir
répondre rapidement à "quel était le stock du produit X à la date T ?" —
il suffit de prendre le `stock_apres` du dernier mouvement à date <= T.

Usage :
    python scripts/create_mouvements_stock_table.py            # Neon GHP (.env)
    python scripts/create_mouvements_stock_table.py --biasa    # Neon BIASA
"""
import io
import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from db_helper import db as db_helper

SQL = """
CREATE TABLE IF NOT EXISTS mouvements_stock (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    produit_id VARCHAR(50) NOT NULL,
    produit_nom VARCHAR(255),
    type_mouvement VARCHAR(30) NOT NULL,
    quantite_delta NUMERIC NOT NULL,
    stock_apres NUMERIC NOT NULL,
    reference_type VARCHAR(30),
    reference_id INTEGER,
    date_mouvement TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by_nom VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mouvements_stock_lookup
    ON mouvements_stock (structure_id, produit_id, date_mouvement);
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL)
    db_helper.execute_query(INDEX_SQL)
    check = db_helper.execute_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='mouvements_stock' ORDER BY ordinal_position"
    )
    print("✅ Table mouvements_stock prête :")
    for c in check:
        print(f"   - {c['column_name']} ({c['data_type']})")
