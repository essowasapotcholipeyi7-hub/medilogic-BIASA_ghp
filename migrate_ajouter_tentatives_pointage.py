"""Migration ponctuelle : passages à la borne d'employés en congé ou en
permission (patron, 2026-10-10) — voir models.py (TentativePointage) et
services/pointage_service.enregistrer_pointage.

Additive et idempotente (CREATE TABLE IF NOT EXISTS) : sans risque à relancer.

Usage :
    python migrate_ajouter_tentatives_pointage.py
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
    db.session.execute(db.text('''
        CREATE TABLE IF NOT EXISTS public.tentatives_pointage (
            id SERIAL PRIMARY KEY,
            structure_id INTEGER NOT NULL,
            employe_id INTEGER NOT NULL REFERENCES public.employes(id),
            date_jour DATE NOT NULL,
            premiere_heure TIME,
            derniere_heure TIME,
            nombre INTEGER DEFAULT 1,
            methode VARCHAR(20),
            absence_type VARCHAR(20),
            absence_id INTEGER,
            motif VARCHAR(255),
            vue_par VARCHAR(100),
            vue_le TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_tentative_pointage_employe_jour UNIQUE (employe_id, date_jour)
        )'''))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_tentatives_pointage_structure ON public.tentatives_pointage (structure_id, vue_le)'))
    db.session.commit()
    print('OK : table tentatives_pointage présente.')
