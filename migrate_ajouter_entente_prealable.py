"""Migration ponctuelle : crée la table "demandes_entente_prealable" (voir
models.py, DemandeEntentePrealable) et ajoute la colonne
"code_prescripteur" à "medecins" — nécessaires pour remplir et imprimer
l'Entente Préalable AMU depuis l'application (patron : "permettre qu'on
remplisse une entente préalable directement là et imprimer").

Additive et idempotente (ADD COLUMN IF NOT EXISTS, create_all() ne touche
pas les tables déjà en place) : aucune donnée existante touchée, sans
risque à relancer par erreur.

Usage :
    python migrate_ajouter_entente_prealable.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, DemandeEntentePrealable

with app.app_context():
    db.create_all()
    db.session.execute(db.text(
        'ALTER TABLE medecins ADD COLUMN IF NOT EXISTS code_prescripteur VARCHAR(50)'
    ))
    db.session.commit()
    print('OK : table "demandes_entente_prealable" et colonne "code_prescripteur" présentes.')
