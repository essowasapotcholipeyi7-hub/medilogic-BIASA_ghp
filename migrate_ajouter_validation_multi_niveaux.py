"""Migration ponctuelle : branche la validation à plusieurs niveaux
(SignatureRH/DocumentRH, déjà codée mais jamais utilisée) sur les congés
— voir models.py (ParametragePaie.niveaux_validation_conges,
Conge.document_validation_id, Conge.statut_validation) et
routes/rh.py (_avancer_validation_conge). Patron : "validation à
plusieurs niveaux (SignatureRH) codée mais jamais branchée".

- parametrage_paie.niveaux_validation_conges (défaut 1 = comportement
  inchangé : un seul clic "Approuver" finalise le congé).
- conges.document_validation_id (nullable, FK vers documents_rh) : lien
  vers la chaîne de signatures, créé seulement au premier niveau validé
  quand niveaux_validation_conges > 1.

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur.

Usage :
    python migrate_ajouter_validation_multi_niveaux.py
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
        'ALTER TABLE public.parametrage_paie ADD COLUMN IF NOT EXISTS niveaux_validation_conges INTEGER DEFAULT 1'
    ))
    db.session.execute(db.text(
        'ALTER TABLE public.conges ADD COLUMN IF NOT EXISTS document_validation_id INTEGER REFERENCES public.documents_rh(id)'
    ))
    db.session.commit()
    print('OK : colonnes de validation multi-niveaux présentes sur parametrage_paie/conges.')
