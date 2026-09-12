"""
Crée la table `validations_demandes` (file d'attente générique des actions
soumises par un caissier/secrétaire et en attente de validation par un
admin : annulation de vente, dépense, encaissement facture assurance),
si elle n'existe pas déjà. Idempotent — peut être relancé sans risque.

Usage :
    python scripts/create_validations_table.py            # Neon GHP (.env)
    python scripts/create_validations_table.py --biasa    # Neon BIASA
"""
import io
import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_helper import db as db_helper

SQL = """
CREATE TABLE IF NOT EXISTS validations_demandes (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    type_demande VARCHAR(50) NOT NULL,
    reference_id INTEGER,
    payload JSON NOT NULL,
    resume VARCHAR(500),
    demandeur_id INTEGER,
    demandeur_nom VARCHAR(255),
    statut VARCHAR(20) NOT NULL DEFAULT 'en_attente',
    motif_refus VARCHAR(500),
    date_demande TIMESTAMP NOT NULL DEFAULT NOW(),
    date_traitement TIMESTAMP,
    traite_par_nom VARCHAR(255)
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_validations_demandes_lookup
    ON validations_demandes (structure_id, statut, date_demande);
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL)
    db_helper.execute_query(INDEX_SQL)
    check = db_helper.execute_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='validations_demandes' ORDER BY ordinal_position"
    )
    print("✅ Table validations_demandes prête :")
    for c in check:
        print(f"   - {c['column_name']} ({c['data_type']})")
