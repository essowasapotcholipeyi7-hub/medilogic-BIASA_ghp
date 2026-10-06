"""Migration ponctuelle : signatures des prescripteurs sur EP / TPC (patron,
2026-10-06). signatures_intervenants : + medecin_id (filière 'prescripteur',
signature rattachée à un médecin de la structure).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : sans risque à relancer.

Usage :
    python migrate_ajouter_signature_prescripteur.py
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
    db.session.execute(db.text('ALTER TABLE signatures_intervenants ADD COLUMN IF NOT EXISTS medecin_id INTEGER'))
    db.session.commit()
    print("OK : signatures_intervenants.medecin_id ajouté (filière 'prescripteur').")
