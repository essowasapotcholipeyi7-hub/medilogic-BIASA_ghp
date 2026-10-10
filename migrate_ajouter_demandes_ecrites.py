"""Migration ponctuelle : demandes ÉCRITES de congé / permission (patron,
2026-10-10 : « les demandes sont faites par écrit [...] correspondance entre
le fichier uploadé et la réponse de la RH ») — voir models.py (Conge,
Permission : demande_reference, demande_ecrite_*, demande_recue_le).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : sans risque à relancer.

Usage :
    python migrate_ajouter_demandes_ecrites.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

COLONNES = [
    ('demande_reference', 'VARCHAR(30)'),
    ('demande_ecrite_nom', 'VARCHAR(255)'),
    ('demande_ecrite_mime', 'VARCHAR(100)'),
    ('demande_ecrite_data', 'BYTEA'),
    ('demande_ecrite_date', 'DATE'),
    ('demande_recue_le', 'DATE'),
    ('demande_ecrite_le', 'TIMESTAMP'),
]

with app.app_context():
    for table in ('conges', 'permissions'):
        for nom, type_sql in COLONNES:
            db.session.execute(db.text(f'ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS {nom} {type_sql}'))
        db.session.execute(db.text(
            f'CREATE INDEX IF NOT EXISTS ix_{table}_demande_reference ON public.{table} (demande_reference)'))
    db.session.commit()
    print('OK : colonnes des demandes écrites présentes sur conges et permissions.')
