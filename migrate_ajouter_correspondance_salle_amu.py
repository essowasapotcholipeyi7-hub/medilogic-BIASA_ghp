"""Migration ponctuelle : crée la table "correspondance_salle_amu" (voir
models.py, CorrespondanceSalleAmu) et ajoute la colonne
"chambre_categorie_amu" à "hospitalisations" — nécessaires pour calculer le
PBR par palier (P160) depuis la grille officielle AMU
(utils/grille_amu_hospitalisation.py) au lieu de deviner par le nom dans le
catalogue Sheets de chaque structure.

Additive et idempotente (ADD COLUMN IF NOT EXISTS, create_all() ne touche
pas les tables déjà en place) : aucune donnée existante touchée, sans
risque à relancer par erreur.

Usage :
    python migrate_ajouter_correspondance_salle_amu.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, CorrespondanceSalleAmu

with app.app_context():
    db.create_all()
    db.session.execute(db.text(
        'ALTER TABLE hospitalisations ADD COLUMN IF NOT EXISTS chambre_categorie_amu VARCHAR(40)'
    ))
    db.session.commit()
    print('OK : table "correspondance_salle_amu" et colonne "chambre_categorie_amu" présentes.')
