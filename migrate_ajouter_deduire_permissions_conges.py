"""Migration ponctuelle : ajoute la colonne "deduire_permissions_des_conges"
à parametrage_paie (voir models.py, ParametragePaie) — patron : "qu'on
décide s'il faut enlever les jours de permission dans les congés ou pas".
Défaut TRUE (comportement déjà en place avant ce commit).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_deduire_permissions_conges.py
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
        'ALTER TABLE public.parametrage_paie '
        'ADD COLUMN IF NOT EXISTS deduire_permissions_des_conges BOOLEAN DEFAULT TRUE'
    ))
    db.session.commit()
    print('OK : colonne "deduire_permissions_des_conges" présente sur parametrage_paie.')
