"""Migration ponctuelle : un numéro de compte n'existe qu'une fois par structure
(2026-10-11 — doublon 70620000 trouvé en structure 9, fusionné). Voir
services/comptabilite_service._get_compte_id.

Idempotente (CREATE UNIQUE INDEX IF NOT EXISTS) ; échoue proprement si un
doublon existe encore (à fusionner d'abord).

Usage :
    python migrate_unicite_comptes.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

with app.app_context():
    doublons = db.session.execute(db.text(
        "SELECT structure_id, numero, COUNT(*) FROM comptes_comptables GROUP BY 1, 2 HAVING COUNT(*) > 1")).fetchall()
    if doublons:
        print('Doublons à fusionner d\'abord :', doublons)
        sys.exit(1)
    db.session.execute(db.text(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_comptes_structure_numero ON public.comptes_comptables (structure_id, numero)'))
    db.session.commit()
    print('OK : un numéro de compte unique par structure.')
