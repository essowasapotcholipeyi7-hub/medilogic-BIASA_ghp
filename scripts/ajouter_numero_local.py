# scripts/ajouter_numero_local.py
# ============================================================
# NUMÉROTATION LOCALE PAR STRUCTURE
# ============================================================
# Aujourd'hui, l'id (clé technique) de patients/ventes/employes/factures
# est une séquence GLOBALE partagée par toutes les structures : structure 1
# enregistre l'id 1, structure 2 l'id 2, structure 1 reprend l'id 3, etc.
# Les utilisateurs voient cet id brut à l'écran (ex: colonne "ID" de la
# liste patients) — d'où l'impression que la numérotation "saute" et se
# mélange entre structures.
#
# Ce script ajoute une colonne `numero_local` (entier) à chacune de ces 4
# tables : une numérotation 1, 2, 3... propre à CHAQUE structure, sans
# toucher à l'id technique (qui reste la clé utilisée pour les jointures,
# les reçus, les écritures comptables — zéro risque sur l'historique).
#
# Idempotent : peut être relancé sans danger (ALTER ... IF NOT EXISTS,
# backfill uniquement des lignes où numero_local est encore NULL).
#
# Utilisation :
#   python scripts/ajouter_numero_local.py

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text

TABLES = ['patients', 'ventes', 'employes', 'factures']


def migrer():
    with app.app_context():
        for table in TABLES:
            print(f"\n=== {table} ===")

            # 1) Colonne
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS numero_local INTEGER"))
            db.session.commit()
            print("  colonne numero_local OK")

            # 2) Backfill : numérotation par structure, dans l'ordre de
            #    création (id croissant = ordre d'insertion), seulement là
            #    où elle n'est pas déjà posée.
            db.session.execute(text(f"""
                UPDATE {table} t
                SET numero_local = sub.rn
                FROM (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY structure_id ORDER BY id) AS rn
                    FROM {table}
                ) sub
                WHERE t.id = sub.id AND t.numero_local IS NULL
            """))
            db.session.commit()

            # 3) Index unique (structure_id, numero_local) — empêche toute
            #    collision future (même logique que le fix du matricule
            #    employé : on préfère une contrainte DB + retry applicatif
            #    plutôt qu'un simple compteur non protégé).
            db.session.execute(text(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_structure_numero_local
                ON {table} (structure_id, numero_local)
            """))
            db.session.commit()
            print("  backfill + index unique OK")

            # Vérification rapide
            trous = db.session.execute(text(f"SELECT COUNT(*) FROM {table} WHERE numero_local IS NULL")).scalar()
            total = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            max_par_structure = db.session.execute(text(f"""
                SELECT structure_id, COUNT(*), MAX(numero_local)
                FROM {table} GROUP BY structure_id ORDER BY structure_id
            """)).fetchall()
            print(f"  total={total} sans_numero={trous}")
            for row in max_par_structure:
                assert row[1] == row[2], f"INCOHÉRENCE {table} structure {row[0]}: count={row[1]} max={row[2]}"
            print("  vérification : count == max(numero_local) par structure, partout OK")


if __name__ == '__main__':
    migrer()
    print("\n✅ Migration numero_local terminée.")
