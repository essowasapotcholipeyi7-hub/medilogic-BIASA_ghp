"""Migration ponctuelle : logique des dates des congés et permissions (patron,
2026-10-10) — voir models.py (Conge / Permission : saisie_retroactive,
regularisation_motif, ecart_force_motif, exceptions_par).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : sans risque à relancer.

Usage :
    python migrate_ajouter_controle_dates_absences.py
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
    for table in ('conges', 'permissions'):
        for ordre in (
            f'ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS saisie_retroactive BOOLEAN DEFAULT FALSE',
            f'ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS regularisation_motif TEXT',
            f'ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS exceptions_par VARCHAR(100)',
        ):
            db.session.execute(db.text(ordre))
    db.session.execute(db.text('ALTER TABLE public.conges ADD COLUMN IF NOT EXISTS ecart_force_motif TEXT'))
    db.session.commit()
    print('OK : colonnes du contrôle des dates présentes sur conges et permissions.')
