"""
Ajoute la colonne `assurance_principale_active` à `proformas` (existait déjà
sur `ventes`, absente sur `proformas`) — permet de créer une proforma pour
un patient assuré SANS appliquer son assurance principale (il ne souhaite
pas l'utiliser pour cette proforma). Idempotent — peut être relancé sans
risque.

Usage :
    python scripts/ajouter_assurance_principale_active_proforma.py            # Neon GHP (.env)
    python scripts/ajouter_assurance_principale_active_proforma.py --biasa    # Neon BIASA
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
ALTER TABLE proformas
    ADD COLUMN IF NOT EXISTS assurance_principale_active BOOLEAN NOT NULL DEFAULT TRUE;
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL)
    check = db_helper.execute_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='proformas' AND column_name='assurance_principale_active'"
    )
    print("✅ proformas :")
    for c in check:
        print(f"   - {c['column_name']} ({c['data_type']})")
