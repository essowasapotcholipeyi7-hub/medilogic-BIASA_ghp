"""
Ajoute la colonne `type_aide` ('pourcentage' | 'montant') à `ventes`, et les
colonnes `taux_aide` / `aide_hospitaliere` / `type_aide` à `proformas` (elles
n'existaient pas du tout sur cette table). Idempotent — peut être relancé
sans risque.

Contexte : l'aide hospitalière (remise) n'existait qu'en pourcentage, sans
plafond réellement appliqué (juste un `max="100"` HTML décoratif) — un taux
mal saisi (ex: 500 au lieu de 50) donnait un net à payer négatif. On ajoute
un second mode "montant direct en FCFA", d'où le besoin de savoir lequel des
deux a été utilisé pour chaque vente/proforma.

Usage :
    python scripts/ajouter_type_aide.py            # Neon GHP (.env)
    python scripts/ajouter_type_aide.py --biasa     # Neon BIASA
"""
import io
import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_helper import db as db_helper

SQL_VENTES = """
ALTER TABLE ventes
    ADD COLUMN IF NOT EXISTS type_aide VARCHAR(20) NOT NULL DEFAULT 'pourcentage';
"""

SQL_PROFORMAS = """
ALTER TABLE proformas
    ADD COLUMN IF NOT EXISTS taux_aide NUMERIC DEFAULT 0,
    ADD COLUMN IF NOT EXISTS aide_hospitaliere NUMERIC DEFAULT 0,
    ADD COLUMN IF NOT EXISTS type_aide VARCHAR(20) NOT NULL DEFAULT 'pourcentage';
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL_VENTES)
    db_helper.execute_query(SQL_PROFORMAS)
    for table in ("ventes", "proformas"):
        check = db_helper.execute_query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name=%s AND column_name IN ('taux_aide', 'aide_hospitaliere', 'type_aide') "
            "ORDER BY column_name", (table,)
        )
        print(f"✅ {table} :")
        for c in check:
            print(f"   - {c['column_name']} ({c['data_type']})")
