"""
Crée les 3 tables du système "Part Médecin" (rétrocession au réalisateur
d'un acte — consultation, infiltration, imagerie...) : `taux_part_medecin`,
`prestations_medecin`, `periodes_part_medecin`. Idempotent.

Contexte : même workflow en 3 états (calculée -> validée -> payée) que le
système de ristournes aux prescripteurs externes déjà en place
(periodes_ristournes), mais pour un médecin INTERNE et avec un taux par
ACTE (pas par médecin) — voir models.py (TauxPartMedecin/PrestationMedecin/
PeriodePartMedecin) et services/part_medecin_service.py.

Usage :
    python scripts/ajouter_part_medecin.py            # Neon GHP (.env)
    python scripts/ajouter_part_medecin.py --biasa     # Neon BIASA
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
CREATE TABLE IF NOT EXISTS taux_part_medecin (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    nom_acte VARCHAR(255) NOT NULL,
    taux_medecin NUMERIC NOT NULL,
    actif BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_structure_taux_part_medecin UNIQUE (structure_id, nom_acte)
);

CREATE TABLE IF NOT EXISTS prestations_medecin (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    medecin_id INTEGER NOT NULL,
    medecin_nom VARCHAR(255),
    vente_id INTEGER,
    nom_acte VARCHAR(255) NOT NULL,
    prix NUMERIC NOT NULL,
    quantite INTEGER DEFAULT 1,
    taux_medecin_applique NUMERIC NOT NULL,
    montant_part_medecin NUMERIC NOT NULL,
    periode_part_medecin_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prestations_medecin_medecin ON prestations_medecin (structure_id, medecin_id, periode_part_medecin_id);

CREATE TABLE IF NOT EXISTS periodes_part_medecin (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    medecin_id INTEGER NOT NULL,
    date_debut DATE NOT NULL,
    date_fin DATE NOT NULL,
    base_calcul NUMERIC DEFAULT 0,
    montant_total NUMERIC DEFAULT 0,
    nb_actes INTEGER DEFAULT 0,
    statut VARCHAR(20) DEFAULT 'calculee',
    calculee_par VARCHAR(255),
    calculee_le TIMESTAMP DEFAULT NOW(),
    validee_par VARCHAR(255),
    validee_le TIMESTAMP,
    mode_paiement VARCHAR(20),
    operateur_mobile VARCHAR(50),
    reference_paiement VARCHAR(100),
    date_paiement DATE,
    payee_par VARCHAR(255),
    payee_le TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

if __name__ == "__main__":
    db_helper.execute_query(SQL)
    for table in ("taux_part_medecin", "prestations_medecin", "periodes_part_medecin"):
        check = db_helper.execute_query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name=%s ORDER BY ordinal_position", (table,)
        )
        print(f"✅ {table} :")
        for c in check:
            print(f"   - {c['column_name']} ({c['data_type']})")
