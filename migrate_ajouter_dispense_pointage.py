"""Migration ponctuelle : employés dispensés de pointage (patron, 2026-10-10)
— voir models.py (Employe.dispense_pointage, dispense_pointage_motif).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : sans risque à relancer.

Usage :
    python migrate_ajouter_dispense_pointage.py
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
    for ordre in (
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS dispense_pointage BOOLEAN DEFAULT FALSE',
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS dispense_pointage_motif VARCHAR(255)',
    ):
        db.session.execute(db.text(ordre))
    db.session.commit()
    print('OK : colonnes de dispense de pointage présentes sur employes.')
