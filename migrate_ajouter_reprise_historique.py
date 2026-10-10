"""Migration ponctuelle : reprise de l'historique des employés présents avant
le logiciel (patron, 2026-10-10) — voir models.py (Employe.reprise_annee,
reprise_conges_jours, reprise_convenance_jours).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : sans risque à relancer.

Usage :
    python migrate_ajouter_reprise_historique.py
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
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS reprise_annee INTEGER',
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS reprise_conges_jours NUMERIC(6,2) DEFAULT 0',
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS reprise_convenance_jours NUMERIC(6,2) DEFAULT 0',
    ):
        db.session.execute(db.text(ordre))
    db.session.commit()
    print('OK : colonnes de reprise de l\'historique présentes sur employes.')
