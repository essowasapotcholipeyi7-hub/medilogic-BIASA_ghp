"""Migration ponctuelle : crée la table "codes_barres_articles" (voir
models.py, CodeBarreArticle) — correspondance code-barres <-> acte/produit,
par structure, pour le scan rapide (Actes/Vente, Pharmacie, Hospitalisation,
Proforma).

Table entièrement NOUVELLE : db.create_all() ne touche pas les tables déjà
en place, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_codes_barres_articles.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, CodeBarreArticle

with app.app_context():
    db.create_all()
    print('OK : table "codes_barres_articles" présente.')
