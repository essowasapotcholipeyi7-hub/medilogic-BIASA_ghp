"""Migration ponctuelle : ajoute les colonnes "date_depart",
"motif_depart" et "commentaire_depart" à employes (voir models.py,
Employe/MOTIFS_DEPART) — patron : "pas de vrai départ (offboarding) —
suppression brute ou juste un statut". Nullable : aucun départ enregistré
par défaut.

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_depart_employe.py
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
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS date_depart DATE'
    ))
    db.session.execute(db.text(
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS motif_depart VARCHAR(50)'
    ))
    db.session.execute(db.text(
        'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS commentaire_depart TEXT'
    ))
    db.session.commit()
    print('OK : colonnes "date_depart"/"motif_depart"/"commentaire_depart" présentes sur employes.')
