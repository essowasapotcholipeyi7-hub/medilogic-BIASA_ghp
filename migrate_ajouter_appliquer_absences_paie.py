"""Migration ponctuelle : ajoute la colonne "appliquer_absences_sur_paie" à
parametrage_paie (voir models.py, ParametragePaie) — patron : "pointage
déconnecté de la paie [...] qu'on décide d'appliquer ou pas". Défaut
FALSE : n'affecte aucun bulletin de paie tant que l'admin ne l'active pas.

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_appliquer_absences_paie.py
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
        'ALTER TABLE public.parametrage_paie ADD COLUMN IF NOT EXISTS appliquer_absences_sur_paie BOOLEAN DEFAULT FALSE'
    ))
    db.session.commit()
    print('OK : colonne "appliquer_absences_sur_paie" présente sur parametrage_paie.')
