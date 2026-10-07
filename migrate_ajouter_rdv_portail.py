"""Migration ponctuelle : demande de rendez-vous depuis le portail patient
(patron, 2026-10-07). rendez_vous : + source, demande_le, creneau_souhaite,
message_patient, reponse_structure, repondu_le, vu_par_patient_le ;
medecin_id devient optionnel (le patient peut ne pas choisir de médecin).

Additive et idempotente (ADD COLUMN IF NOT EXISTS, DROP NOT NULL sans effet
si déjà fait) : sans risque à relancer.

Usage :
    python migrate_ajouter_rdv_portail.py
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
    for colonne, type_sql in (('source', "VARCHAR(20) DEFAULT 'personnel'"), ('demande_le', 'TIMESTAMP'),
                              ('creneau_souhaite', 'VARCHAR(20)'), ('message_patient', 'TEXT'),
                              ('reponse_structure', 'TEXT'), ('repondu_le', 'TIMESTAMP'), ('vu_par_patient_le', 'TIMESTAMP')):
        db.session.execute(db.text(f'ALTER TABLE rendez_vous ADD COLUMN IF NOT EXISTS {colonne} {type_sql}'))
    db.session.execute(db.text('ALTER TABLE rendez_vous ALTER COLUMN medecin_id DROP NOT NULL'))
    db.session.commit()
    print("OK : colonnes de la demande de rendez-vous (portail) ajoutées, medecin_id optionnel.")
