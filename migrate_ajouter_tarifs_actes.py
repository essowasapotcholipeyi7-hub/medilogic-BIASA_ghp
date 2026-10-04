"""Migration ponctuelle : tarification des actes par type de patient (patron,
2026-10-04, "Vérification de la logique de calcul des tarifs actes").

- pbr_complementaires : + tarif_prive (tarif facturé aux patients de cette
  compagnie), pbr_1 devient optionnel ("présence ou non d'un PBR").
- prix_non_assure_actes : nouvelle table (prix non assuré par acte).

Additive et idempotente (ADD COLUMN IF NOT EXISTS, create_all() ne touche
pas les tables déjà en place, DROP NOT NULL sans effet si déjà fait) :
aucune donnée existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_tarifs_actes.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db, PrixNonAssureActe  # noqa: F401  (create_all)

with app.app_context():
    db.create_all()
    db.session.execute(db.text('''
        ALTER TABLE pbr_complementaires
            ADD COLUMN IF NOT EXISTS tarif_prive NUMERIC
    '''))
    db.session.execute(db.text('ALTER TABLE pbr_complementaires ALTER COLUMN pbr_1 DROP NOT NULL'))
    db.session.commit()
    print('OK : tarif_prive ajouté (pbr_1 optionnel), table prix_non_assure_actes créée.')
