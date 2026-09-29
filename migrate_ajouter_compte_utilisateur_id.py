"""Migration ponctuelle : ajoute la colonne "compte_utilisateur_id" à
employes (voir models.py, Employe) — patron : "fiche employé et compte de
connexion séparés (aucun lien)". Lien LOGIQUE (pas une vraie clé
étrangère) vers l'ID de ligne de la feuille Google Sheets
struct_<id>_users, le vrai système de login de l'appli. Nullable : rien
n'oblige à lier un employé à un compte applicatif.

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_compte_utilisateur_id.py
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
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS compte_utilisateur_id INTEGER'
    ))
    db.session.commit()
    print('OK : colonne "compte_utilisateur_id" présente sur employes.')
