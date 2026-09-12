"""
Corrige deux problèmes constatés sur `proformas` (signalé par le patron :
proforma créée sur BIASA structure 1 sans date, statut affiché "None") :

1. Les colonnes `created_at`/`statut` n'avaient PAS de DEFAULT au niveau de
   la base BIASA (alors que GHP en avait un, `now()` / 'en_attente' —
   pur écart de schéma entre les deux bases Neon). Le code applicatif
   (api_creer_proforma) ne les renseignait jamais explicitement non plus
   et comptait donc sur ce DEFAULT — absent sur BIASA, il laissait ces
   colonnes NULL pour CHAQUE proforma créée là-bas. Un correctif séparé
   dans app.py fixe désormais created_at=NOW()/statut='en_attente'
   explicitement dans l'INSERT (ne dépend plus du DEFAULT), mais on aligne
   quand même le DEFAULT ici en filet de sécurité pour tout autre chemin
   d'insertion existant ou futur.
2. Rattrape les lignes déjà NULL créées avant ce correctif.

Idempotent — peut être relancé sans risque (sur GHP, où le DEFAULT
existait déjà et aucune ligne n'est NULL, ce script ne change rien).

Usage :
    python scripts/fix_proformas_created_at_statut.py            # Neon GHP (.env)
    python scripts/fix_proformas_created_at_statut.py --biasa    # Neon BIASA
"""
import io
import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_helper import db as db_helper

SQL_DEFAULTS = """
ALTER TABLE proformas ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE proformas ALTER COLUMN statut SET DEFAULT 'en_attente';
"""

SQL_BACKFILL = """
UPDATE proformas SET statut = 'en_attente' WHERE statut IS NULL;
UPDATE proformas SET created_at = NOW() WHERE created_at IS NULL;
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL_DEFAULTS)
    db_helper.execute_query(SQL_BACKFILL)

    check = db_helper.execute_query(
        "SELECT COUNT(*) as total, COUNT(created_at) as with_date, "
        "COUNT(statut) as with_statut FROM proformas"
    )
    print("✅ proformas :", dict(check[0]))
