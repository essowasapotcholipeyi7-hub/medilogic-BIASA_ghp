"""Migration ponctuelle : rôles supplémentaires d'un compte utilisateur
(patron, 2026-10-10 : un caissier peut aussi être secrétaire...) — voir
models.py (RoleSupplementaire).

Additive et idempotente (CREATE TABLE IF NOT EXISTS) : sans risque à relancer.

Usage :
    python migrate_ajouter_roles_supplementaires.py
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
        CREATE TABLE IF NOT EXISTS public.roles_supplementaires (
            id SERIAL PRIMARY KEY,
            structure_id INTEGER NOT NULL,
            utilisateur_id INTEGER NOT NULL,
            role VARCHAR(30) NOT NULL,
            accorde_par_nom VARCHAR(255),
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_role_supplementaire UNIQUE (structure_id, utilisateur_id, role)
        )'''))
    db.session.commit()
    print('OK : table roles_supplementaires présente.')
