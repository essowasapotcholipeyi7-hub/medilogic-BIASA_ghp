"""Migration ponctuelle : ajoute la colonne "sigle" à parametrage_amu_cnss
(voir models.py) — nécessaire pour le numéro de facture recap AMU
(CNSS/TNS/INAM) "N° 000000001/AMU/<sigle>/<année>".

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_sigle_amu.py
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
    db.session.execute(db.text('ALTER TABLE parametrage_amu_cnss ADD COLUMN IF NOT EXISTS sigle VARCHAR(20)'))
    db.session.commit()
    print('OK : colonne "sigle" présente sur parametrage_amu_cnss.')
