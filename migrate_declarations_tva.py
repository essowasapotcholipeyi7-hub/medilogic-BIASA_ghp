"""Migration ponctuelle : clôture et paiement de la TVA par période (2026-10-11)
— table declarations_tva. Voir models.DeclarationTva et
routes/comptabilite.api_tva_declaration_cloturer.

Additive et idempotente : sans risque à relancer.

Usage :
    python migrate_declarations_tva.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, DeclarationTva

with app.app_context():
    DeclarationTva.__table__.create(bind=db.engine, checkfirst=True)
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_declarations_tva_structure_fin ON declarations_tva (structure_id, date_fin)'))
    db.session.commit()
    print('OK : table declarations_tva prête.')
