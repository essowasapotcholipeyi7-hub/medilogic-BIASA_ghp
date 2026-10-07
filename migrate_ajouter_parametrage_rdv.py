"""Migration ponctuelle : table parametrage_rendez_vous (règle de paiement du
bon de consultation sur les rendez-vous, patron 2026-10-07). create_all() ne
touche pas aux tables existantes : sans risque à relancer.

Usage :
    python migrate_ajouter_parametrage_rdv.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, ParametrageRendezVous  # noqa: F401

with app.app_context():
    db.create_all()
    print("OK : table parametrage_rendez_vous créée (si absente).")
