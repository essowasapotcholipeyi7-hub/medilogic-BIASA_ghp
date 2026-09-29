"""Migration ponctuelle : ajoute la colonne "cloturee" à factures_assurance
(voir models.py, FactureAssurance) — verrou définitif posé sur un
bordereau (AMU ou complémentaire/CAC) une fois clôturé : plus aucune
modification possible (montant, date de dépôt), voir
api_cloturer_facture_assurance / api_cloturer_facture_amu (app.py).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_cloturee_factures_assurance.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

with app.app_context():
    db.session.execute(db.text(
        'ALTER TABLE public.factures_assurance ADD COLUMN IF NOT EXISTS cloturee BOOLEAN DEFAULT FALSE'
    ))
    db.session.commit()
    print('OK : colonne "cloturee" présente sur factures_assurance.')
