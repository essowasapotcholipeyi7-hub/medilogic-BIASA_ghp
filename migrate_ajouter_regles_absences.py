"""Migration ponctuelle : règles congés / permissions du Code du travail
togolais (patron, 2026-10-10 : « je veux une vraie GRH ») — voir
utils/regles_absences.py et models.py (Conge, Permission, ParametragePaie).

- permissions : nature (exceptionnelle / convenance), événement, mode de
  déduction, justificatif, avis du supérieur ; nombre_jours passe en
  NUMERIC (la demi-journée d'une permission « heures » était tronquée) ;
- conges : dérogation d'ancienneté (accord de l'employeur avant 12 mois) ;
- parametrage_paie : regles_absences (JSON des seuils et choix).

Additive et idempotente (ADD COLUMN IF NOT EXISTS ; le changement de type
integer -> numeric conserve toutes les valeurs) : sans risque à relancer.

Usage :
    python migrate_ajouter_regles_absences.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

ORDRES = [
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS nature VARCHAR(30)',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS evenement VARCHAR(60)',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS deduction VARCHAR(20)',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS justificatif_nom VARCHAR(255)',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS justificatif_mime VARCHAR(100)',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS justificatif_data BYTEA',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS justificatif_le TIMESTAMP',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS avis_superieur VARCHAR(20)',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS avis_superieur_par VARCHAR(100)',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS avis_superieur_le TIMESTAMP',
    'ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS avis_superieur_commentaire TEXT',
    'ALTER TABLE public.permissions ALTER COLUMN nombre_jours TYPE NUMERIC(6,2) USING nombre_jours::numeric',
    'ALTER TABLE public.conges ADD COLUMN IF NOT EXISTS derogation_anciennete BOOLEAN DEFAULT FALSE',
    'ALTER TABLE public.conges ADD COLUMN IF NOT EXISTS derogation_motif TEXT',
    'ALTER TABLE public.conges ADD COLUMN IF NOT EXISTS derogation_par VARCHAR(100)',
    'ALTER TABLE public.parametrage_paie ADD COLUMN IF NOT EXISTS regles_absences JSON',
]

with app.app_context():
    for ordre in ORDRES:
        db.session.execute(db.text(ordre))
    db.session.commit()
    print('OK : colonnes des règles congés / permissions présentes (permissions, conges, parametrage_paie).')
