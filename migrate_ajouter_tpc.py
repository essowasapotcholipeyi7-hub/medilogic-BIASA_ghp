"""Migration ponctuelle : crée les tables du module TPC (Traitement des
Pathologies Chroniques) — voir models.py, DemandeTpc / MedicamentTpcMemorise
/ LieuResidenceMemorise — et ajoute les numéros de dépôt WhatsApp / numéro
vert AMU à parametrage_amu_cnss et parametrage_amu_inam. Patron (2026-10-01) :
"attaque les TPC, même logique que les EP".

Additive et idempotente (ADD COLUMN IF NOT EXISTS, create_all() ne touche
pas les tables déjà en place) : aucune donnée existante touchée, sans
risque à relancer par erreur.

Usage :
    python migrate_ajouter_tpc.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, DemandeTpc, MedicamentTpcMemorise, LieuResidenceMemorise

with app.app_context():
    db.create_all()
    db.session.execute(db.text('''
        ALTER TABLE demandes_tpc
            ADD COLUMN IF NOT EXISTS sexe VARCHAR(20),
            ADD COLUMN IF NOT EXISTS profession VARCHAR(150),
            ADD COLUMN IF NOT EXISTS numero_ancien_tpc VARCHAR(100)
    '''))
    db.session.execute(db.text('''
        ALTER TABLE parametrage_amu_cnss
            ADD COLUMN IF NOT EXISTS whatsapp_depot VARCHAR(20) DEFAULT '71383919',
            ADD COLUMN IF NOT EXISTS numero_vert VARCHAR(20) DEFAULT '8323'
    '''))
    db.session.execute(db.text('''
        ALTER TABLE parametrage_amu_inam
            ADD COLUMN IF NOT EXISTS whatsapp_depot VARCHAR(20),
            ADD COLUMN IF NOT EXISTS numero_vert VARCHAR(20) DEFAULT '8222'
    '''))
    # ⭐ Lignes déjà existantes (structures ayant déjà ouvert la page
    # Paramétrage AMU avant cette migration) : backfill des valeurs par
    # défaut puisque ADD COLUMN...DEFAULT ne s'applique qu'aux futures
    # lignes insérées, pas aux lignes déjà en base sur Postgres.
    db.session.execute(db.text(
        "UPDATE parametrage_amu_cnss SET whatsapp_depot = '71383919' WHERE whatsapp_depot IS NULL"
    ))
    db.session.execute(db.text(
        "UPDATE parametrage_amu_cnss SET numero_vert = '8323' WHERE numero_vert IS NULL"
    ))
    db.session.execute(db.text(
        "UPDATE parametrage_amu_inam SET numero_vert = '8222' WHERE numero_vert IS NULL"
    ))
    db.session.commit()
    print('OK : tables TPC créées, numéros de dépôt WhatsApp/vert ajoutés.')
