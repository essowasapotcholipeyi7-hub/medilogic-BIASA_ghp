"""Migration ponctuelle : crée les tables "evaluations_rh" et
"sanctions_disciplinaires" (voir models.py, EvaluationRH/
SanctionDisciplinaire/TYPES_SANCTION) — patron : "pas d'évaluations ni
de sanctions disciplinaires".

Utilise db.create_all() plutôt que des ALTER TABLE bruts : ce sont deux
tables entièrement NOUVELLES (pas des colonnes ajoutées à une table
existante) — create_all() ne touche que les tables absentes, sans effet
sur les tables déjà en place.

Usage :
    python migrate_ajouter_evaluations_sanctions.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, EvaluationRH, SanctionDisciplinaire

with app.app_context():
    db.create_all()
    print('OK : tables "evaluations_rh" et "sanctions_disciplinaires" présentes.')
