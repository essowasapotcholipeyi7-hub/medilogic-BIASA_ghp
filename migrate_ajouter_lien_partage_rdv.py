"""Migration ponctuelle : table liens_partage_rdv (lien de consultation des
rendez-vous partagé aux médecins, patron 2026-10-07). create_all() ne touche
pas aux tables existantes : sans risque à relancer.

Usage :
    python migrate_ajouter_lien_partage_rdv.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, LienPartageRendezVous  # noqa: F401

with app.app_context():
    db.create_all()
    print("OK : table liens_partage_rdv créée (si absente).")
