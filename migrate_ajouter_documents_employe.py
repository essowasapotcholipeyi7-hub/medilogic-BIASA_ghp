"""Migration ponctuelle : ajoute les colonnes de stockage des documents
employé (photo, pièce d'identité, contrat) — voir models.py, Employe, et
TYPES_DOCUMENT_EMPLOYE dans routes/rh.py. Patron : "documents jamais
gérés (photo, pièce d'identité, contrat — champs présents, jamais
utilisés)".

Les colonnes *_url existent déjà (String(500)) — cette migration ajoute
seulement les colonnes de contenu (base64, en Text : pas de stockage
disque/cloud disponible ici, voir le commentaire sur Employe.photo_data)
et de métadonnées (content_type, nom de fichier d'origine).

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_documents_employe.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

COLONNES = [
    ('photo_data', 'TEXT'),
    ('photo_content_type', 'VARCHAR(100)'),
    ('piece_identite_data', 'TEXT'),
    ('piece_identite_content_type', 'VARCHAR(100)'),
    ('piece_identite_filename', 'VARCHAR(255)'),
    ('contrat_data', 'TEXT'),
    ('contrat_content_type', 'VARCHAR(100)'),
    ('contrat_filename', 'VARCHAR(255)'),
]

with app.app_context():
    for nom, type_sql in COLONNES:
        db.session.execute(db.text(
            f'ALTER TABLE public.employes ADD COLUMN IF NOT EXISTS {nom} {type_sql}'
        ))
    db.session.commit()
    print(f'OK : {len(COLONNES)} colonnes de documents employé présentes sur employes.')
