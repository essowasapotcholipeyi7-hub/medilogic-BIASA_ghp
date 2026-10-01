"""Migration ponctuelle : ajoute le lien EP <-> Hospitalisation et le
marqueur "demande définitive" à "demandes_entente_prealable" — voir
models.py, DemandeEntentePrealable. Patron (2026-10-01) : "on va faire
une liaison entre hospitalisation [et l'EP] ... ces demandes
actuellement correspondent au pré-accord [...] à la sortie on fait une
demande définitive".

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_entente_prealable_v3.py
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
        ALTER TABLE demandes_entente_prealable
            ADD COLUMN IF NOT EXISTS hospitalisation_id INTEGER,
            ADD COLUMN IF NOT EXISTS definitive_le TIMESTAMP
    '''))
    db.session.commit()
    print('OK : colonnes hospitalisation_id/definitive_le ajoutées à "demandes_entente_prealable".')
