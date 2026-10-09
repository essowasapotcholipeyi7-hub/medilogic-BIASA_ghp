"""Migration ponctuelle : crée les tables des proformas d'intervention
chirurgicale (cotation en K) — voir models.py, ProformaChirurgie /
ModeleInterventionChirurgie / ParametrageChirurgie. Patron (2026-10-09) :
"configurer un truc comme ça dans notre travail [...] ces proformas de
chirurgie pour les interventions".

Additive et idempotente (checkfirst : seules ces trois tables sont créées
si elles manquent, rien d'autre n'est touché) : sans risque à relancer.

Usage :
    python migrate_ajouter_proforma_chirurgie.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, ProformaChirurgie, ModeleInterventionChirurgie, ParametrageChirurgie

with app.app_context():
    for modele in (ProformaChirurgie, ModeleInterventionChirurgie, ParametrageChirurgie):
        modele.__table__.create(db.engine, checkfirst=True)
        print(f"✅ Table {modele.__tablename__} prête")
