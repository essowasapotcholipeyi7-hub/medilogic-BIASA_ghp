# scripts/renommer_journal_bq_en_bqu.py
# ============================================================
# RENOMME LE CODE JOURNAL 'BQ' EN 'BQU'
# ============================================================
# Demande du patron (2026-09-29) : le code du journal de banque doit être
# 'BQU', pas 'BQ' — EcritureComptable.JOURNAUX (models.py) a déjà été mis à
# jour, et services/comptabilite_service.py ne génère plus jamais 'BQ'.
#
# Ce script met à jour les écritures DÉJÀ enregistrées en production sous
# l'ancien code 'BQ' (12 lignes au moment où ce script a été écrit), pour
# qu'elles restent visibles dans le sélecteur de journal (qui n'affiche
# plus que les clés actuelles de JOURNAUX) et cohérentes avec les
# nouvelles écritures.
#
# Idempotent : peut être relancé sans danger (l'UPDATE ne touche que les
# lignes encore à 'BQ' ; si aucune n'en reste, il ne fait rien).
#
# Utilisation :
#   python scripts/renommer_journal_bq_en_bqu.py

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config import Config


def migrer():
    conn = psycopg2.connect(Config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ecritures_comptables WHERE journal_code = 'BQ'")
            avant = cur.fetchone()[0]
            print(f"Écritures avec journal_code='BQ' trouvées : {avant}")

            if avant == 0:
                print("Rien à migrer.")
                return

            cur.execute("UPDATE ecritures_comptables SET journal_code = 'BQU' WHERE journal_code = 'BQ'")
            conn.commit()
            print(f"{cur.rowcount} écriture(s) renommée(s) 'BQ' -> 'BQU'.")

            cur.execute("SELECT COUNT(*) FROM ecritures_comptables WHERE journal_code = 'BQ'")
            apres = cur.fetchone()[0]
            print(f"Restantes à 'BQ' après migration : {apres}")
    finally:
        conn.close()


if __name__ == '__main__':
    migrer()
