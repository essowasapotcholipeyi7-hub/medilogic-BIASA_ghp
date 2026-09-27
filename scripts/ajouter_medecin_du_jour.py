"""
Crée la table `medecin_du_jour` (structure_id, date, medecin_id) et ajoute
la colonne `toujours_demander_medecin` (bool) à `taux_part_medecin`.
Idempotent — peut être relancé sans risque.

Contexte : le sélecteur "Réalisé par" de Actes & Vente demandait le
médecin à CHAQUE ligne pour un acte configuré (Part Médecin), même les
jours où un seul médecin consulte/réalise les radios toute la journée —
patron : "il y a des jours où on sait quel médecin consulte... redemander
à chaque fois... peut devenir gênant". `medecin_du_jour` (une ligne par
structure/date, modifiable en cours de journée) fournit le réalisateur
par défaut pour les actes concernés ; `toujours_demander_medecin` reste
l'échappatoire pour les actes où le réalisateur varie ligne par ligne
(ex : infiltration) — voir models.py (MedecinDuJour/TauxPartMedecin) et
services/part_medecin_service.py.

Usage :
    python scripts/ajouter_medecin_du_jour.py            # Neon GHP (.env)
    python scripts/ajouter_medecin_du_jour.py --biasa     # Neon BIASA
"""
import io
import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_helper import db as db_helper

SQL_TABLE = """
CREATE TABLE IF NOT EXISTS medecin_du_jour (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    date DATE NOT NULL,
    medecin_id INTEGER NOT NULL,
    defini_par VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_structure_medecin_du_jour UNIQUE (structure_id, date)
);
"""

SQL_COLONNE = """
ALTER TABLE taux_part_medecin
    ADD COLUMN IF NOT EXISTS toujours_demander_medecin BOOLEAN NOT NULL DEFAULT FALSE;
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL_TABLE)
    db_helper.execute_query(SQL_COLONNE)

    check = db_helper.execute_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='medecin_du_jour' ORDER BY ordinal_position"
    )
    print("✅ medecin_du_jour :")
    for c in check:
        print(f"   - {c['column_name']} ({c['data_type']})")

    check2 = db_helper.execute_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='taux_part_medecin' AND column_name='toujours_demander_medecin'"
    )
    print("✅ taux_part_medecin :")
    for c in check2:
        print(f"   - {c['column_name']} ({c['data_type']})")
