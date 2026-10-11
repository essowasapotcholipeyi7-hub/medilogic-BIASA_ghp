"""Migration ponctuelle : TVA au choix de la structure (2026-10-11) — colonne
modifie_par (qui a activé / désactivé la TVA) et valeur par défaut « sans TVA »
pour les nouvelles structures. Voir models.ParametrageTva.

Additive et idempotente : sans risque à relancer. NE change PAS le réglage
des structures existantes.

Usage :
    python migrate_tva_au_choix.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

with app.app_context():
    db.session.execute(db.text('ALTER TABLE public.parametrage_tva ADD COLUMN IF NOT EXISTS modifie_par VARCHAR(255)'))
    db.session.execute(db.text('ALTER TABLE public.parametrage_tva ALTER COLUMN assujetti SET DEFAULT FALSE'))
    db.session.commit()
    print('OK : paramétrage TVA au choix de la structure.')
