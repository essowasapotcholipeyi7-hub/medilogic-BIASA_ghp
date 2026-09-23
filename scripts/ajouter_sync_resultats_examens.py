"""
Ajoute les colonnes de traçabilité de synchro (`source_app`, `source_model`,
`source_id`, `source_synced_at`) à `demandes_examens`, `resultats_examens` et
`modeles_resultats`, plus un index unique partiel par table sur
(structure_id, source_app, source_model, source_id) — même schéma que
`protocoles_medicaux` (voir /api/protocoles/sync-externe, app.py). Permet à
/api/resultats-examens/sync-externe de faire un upsert idempotent : un
retry du rattrapage (scheduler gestion_patients) ne crée jamais de doublon.
Idempotent — peut être relancé sans risque.

Usage :
    python scripts/ajouter_sync_resultats_examens.py            # Neon GHP (.env)
    python scripts/ajouter_sync_resultats_examens.py --biasa    # Neon BIASA (depuis ce repo-là)
"""
import io
import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_helper import db as db_helper

TABLES = ("demandes_examens", "resultats_examens", "modeles_resultats")

SQL_COLONNES = """
ALTER TABLE {table}
    ADD COLUMN IF NOT EXISTS source_app VARCHAR(30),
    ADD COLUMN IF NOT EXISTS source_model VARCHAR(30),
    ADD COLUMN IF NOT EXISTS source_id INTEGER,
    ADD COLUMN IF NOT EXISTS source_synced_at TIMESTAMP;
"""

SQL_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_source
    ON {table} (structure_id, source_app, source_model, source_id)
    WHERE (source_app IS NOT NULL);
"""

if __name__ == "__main__":
    for table in TABLES:
        db_helper.execute_query(SQL_COLONNES.format(table=table))
        db_helper.execute_query(SQL_INDEX.format(table=table))

    for table in TABLES:
        check = db_helper.execute_query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name=%s AND column_name IN "
            "('source_app','source_model','source_id','source_synced_at') "
            "ORDER BY column_name", (table,)
        )
        print(f"OK {table} :")
        for c in check:
            print(f"   - {c['column_name']} ({c['data_type']})")
        idx = db_helper.execute_query(
            "SELECT indexname FROM pg_indexes WHERE tablename=%s AND indexname=%s",
            (table, f"idx_{table}_source")
        )
        print(f"   index idx_{table}_source : {'OK' if idx else 'MANQUANT'}")
