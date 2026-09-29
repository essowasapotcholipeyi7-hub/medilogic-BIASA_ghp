# scripts/ajouter_medecin_soins.py
# ============================================================
# PART MÉDECIN SUR LES SOINS D'HOSPITALISATION / AMBULATOIRES
# ============================================================
# Demande du patron (2026-09-30) : "au cours d'hospitalisation un médecin
# qui doit prendre de pourcentage réalise une écho... on doit pouvoir
# récupérer ça". Ni les soins d'hospitalisation ni les soins ambulatoires
# ne capturaient quel médecin avait réalisé l'acte — impossible d'y
# appliquer la part médecin ensuite.
#
# Ajoute medecin_id/medecin_nom à soins_hospitalisation et
# lignes_soins_ambulatoires (voir models.py: SoinHospitalisation,
# LigneSoinAmbulatoire).
#
# Idempotent (ADD COLUMN IF NOT EXISTS) : peut être relancé sans danger.
#
# Utilisation :
#   python scripts/ajouter_medecin_soins.py

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config import Config

TABLES = ['soins_hospitalisation', 'lignes_soins_ambulatoires']


def migrer():
    conn = psycopg2.connect(Config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            for table in TABLES:
                print(f"\n=== {table} ===")
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS medecin_id INTEGER")
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS medecin_nom VARCHAR(255)")
                conn.commit()
                print("Colonnes medecin_id/medecin_nom présentes.")
    finally:
        conn.close()
    print("\nTerminé.")


if __name__ == '__main__':
    migrer()
