# scripts/ajouter_recettes_par_service.py
# ============================================================
# RECETTES PAR SERVICE
# ============================================================
# Demande du patron (2026-09-30) : voir l'effort/le chiffre d'affaires de
# chaque service (département) de la clinique, pas seulement pharmacie
# (déjà séparée) — pour décider des ristournes de fin d'année.
#
# Crée :
#   - parametrage_service          (toggle "choix du service à la vente")
#   - classification_service_actes (service attribué à la main à un acte)
#   - recettes_service              (ligne de recette attribuée à un service,
#                                     générée automatiquement à chaque vente)
# Ajoute :
#   - hospitalisations.service_id
#   - soins_ambulatoires.service_id
#
# Voir models.py (ParametrageService, ClassificationServiceActe,
# RecetteService, Hospitalisation.service_id, SoinsAmbulatoires.service_id)
# et services/service_acte_service.py.
#
# Idempotent (IF NOT EXISTS partout) : peut être relancé sans danger.
#
# Utilisation :
#   python scripts/ajouter_recettes_par_service.py

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config import Config


def migrer():
    conn = psycopg2.connect(Config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            print("=== hospitalisations.service_id ===")
            cur.execute("ALTER TABLE hospitalisations ADD COLUMN IF NOT EXISTS service_id INTEGER")
            conn.commit()

            print("=== soins_ambulatoires.service_id ===")
            cur.execute("ALTER TABLE soins_ambulatoires ADD COLUMN IF NOT EXISTS service_id INTEGER")
            conn.commit()

            print("=== parametrage_service ===")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS parametrage_service (
                    id SERIAL PRIMARY KEY,
                    structure_id INTEGER NOT NULL UNIQUE,
                    choix_service_actif BOOLEAN DEFAULT FALSE,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()

            print("=== classification_service_actes ===")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS classification_service_actes (
                    id SERIAL PRIMARY KEY,
                    structure_id INTEGER NOT NULL,
                    nom_acte VARCHAR(255) NOT NULL,
                    service_id INTEGER NOT NULL,
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_classification_service_actes_unique
                ON classification_service_actes (structure_id, nom_acte)
            """)
            conn.commit()

            print("=== recettes_service ===")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS recettes_service (
                    id SERIAL PRIMARY KEY,
                    structure_id INTEGER NOT NULL,
                    service_id INTEGER,
                    service_nom VARCHAR(255),
                    vente_id INTEGER,
                    nom_acte VARCHAR(255) NOT NULL,
                    type_source VARCHAR(20),
                    origine VARCHAR(20),
                    prix NUMERIC NOT NULL,
                    quantite INTEGER DEFAULT 1,
                    montant NUMERIC NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS ix_recettes_service_structure_service
                ON recettes_service (structure_id, service_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS ix_recettes_service_vente
                ON recettes_service (vente_id)
            """)
            conn.commit()

            print("\nTerminé.")
    finally:
        conn.close()


if __name__ == '__main__':
    migrer()
