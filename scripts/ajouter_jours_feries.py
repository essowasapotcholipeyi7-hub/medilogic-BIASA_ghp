"""
Crée la table `jours_feries` (structure_id, date, libelle). Idempotent —
peut être relancé sans risque.

Contexte : nouveau tarif nuit/férié/dimanche pour Clinique Valeo
(structure 13, voir scripts/importer_tarifs_valeo.py) — GHP n'avait aucune
notion de jour férié nulle part. Patron : une petite liste par structure,
gérable à la main chaque année (page /admin/jours-feries), plutôt qu'un
calendrier codé en dur qui se périmerait.

Usage :
    python scripts/ajouter_jours_feries.py            # Neon GHP (.env)
    python scripts/ajouter_jours_feries.py --biasa     # Neon BIASA
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
CREATE TABLE IF NOT EXISTS jours_feries (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    date DATE NOT NULL,
    libelle VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_structure_jour_ferie UNIQUE (structure_id, date)
);
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL)
    check = db_helper.execute_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='jours_feries' ORDER BY ordinal_position"
    )
    print("✅ jours_feries :")
    for c in check:
        print(f"   - {c['column_name']} ({c['data_type']})")
