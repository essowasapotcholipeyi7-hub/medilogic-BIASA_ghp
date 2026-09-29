"""Migration ponctuelle : ajoute la colonne "manager_id" à employes (voir
models.py, Employe.manager_id/subordonnes/chaine_hierarchique) — patron :
"pas d'organigramme réel". Auto-référence nullable (FK vers employes.id
lui-même) : tout le monde n'a pas de responsable hiérarchique (ex. le/la
directeur·rice).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_manager_employe.py
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
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS manager_id INTEGER REFERENCES public.employes(id)'
    ))
    db.session.commit()
    print('OK : colonne "manager_id" présente sur employes.')
