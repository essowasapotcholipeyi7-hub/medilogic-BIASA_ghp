"""
Ajoute les colonnes `mise_de_cote` (bool) et `mise_de_cote_le` (timestamp) à
`prescriptions_recues`. Idempotent — peut être relancé sans risque.

Contexte : la vue "En attente" de /prescriptions-recues mélangeait tout ce
qui n'était pas encore délivré/facturé, y compris des prescriptions reçues
depuis des semaines (patient qui n'est jamais venu les chercher) — patron :
"les prescriptions de plus de 14 jours restent à part également, et qu'on
ait le choix d'amener un produit qu'on vient de prescrire là-bas également,
pour libérer l'espace pour les nouveaux". Le seuil de 14 jours se calcule à
la volée sur `recu_le` (pas besoin de colonne) ; `mise_de_cote` permet en
plus à un membre du personnel de ranger manuellement une prescription
récente dans cette même vue "Anciennes", sans attendre les 14 jours.

Usage :
    python scripts/ajouter_mise_de_cote_prescriptions.py            # Neon GHP (.env)
    python scripts/ajouter_mise_de_cote_prescriptions.py --biasa     # Neon BIASA
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
ALTER TABLE prescriptions_recues
    ADD COLUMN IF NOT EXISTS mise_de_cote BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS mise_de_cote_le TIMESTAMP;
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL)
    check = db_helper.execute_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='prescriptions_recues' AND column_name IN ('mise_de_cote', 'mise_de_cote_le') "
        "ORDER BY column_name"
    )
    print("✅ prescriptions_recues :")
    for c in check:
        print(f"   - {c['column_name']} ({c['data_type']})")
