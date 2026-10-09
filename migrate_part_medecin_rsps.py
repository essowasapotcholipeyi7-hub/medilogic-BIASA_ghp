"""Migration ponctuelle (2026-10-08) : affectation acte -> médecins, RSPS 5 %
à reverser à l'OTR sur la part médecin (tables affectations_part_medecin,
parametrage_part_medecin, versements_rsps + colonnes sur
periodes_part_medecin). Sans risque à relancer.

Usage :
    python migrate_part_medecin_rsps.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from sqlalchemy import text

from app import app
from models import db, AffectationPartMedecin, ParametragePartMedecin, VersementRsps  # noqa: F401

with app.app_context():
    db.create_all()
    for col, typ in (('taux_rsps', 'NUMERIC'), ('montant_rsps', 'NUMERIC DEFAULT 0'),
                     ('montant_net', 'NUMERIC'), ('rsps_versement_id', 'INTEGER')):
        db.session.execute(text(f'ALTER TABLE periodes_part_medecin ADD COLUMN IF NOT EXISTS {col} {typ}'))
    # clôtures antérieures : pas de retenue, net = montant total
    db.session.execute(text('UPDATE periodes_part_medecin SET montant_net = montant_total, montant_rsps = COALESCE(montant_rsps, 0), taux_rsps = COALESCE(taux_rsps, 0) WHERE montant_net IS NULL'))
    db.session.commit()
    print("OK : tables/colonnes part médecin (affectations, RSPS, versements) en place.")
