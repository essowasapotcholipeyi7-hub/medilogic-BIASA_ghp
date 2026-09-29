"""Migration ponctuelle : ajoute la colonne "date_depot" à
factures_assurance (voir models.py, FactureAssurance) — date à laquelle un
bordereau (AMU ou complémentaire/CAC) a été réellement déposé chez
l'assureur, saisie manuellement au moment de l'impression.

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_date_depot_factures_assurance.py
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
    db.session.execute(db.text('ALTER TABLE public.factures_assurance ADD COLUMN IF NOT EXISTS date_depot DATE'))
    db.session.commit()
    print('OK : colonne "date_depot" présente sur factures_assurance.')
