"""Migration ponctuelle : synchro des patients vers gestion_patients limitée aux
patients modifiés (2026-10-12). Voir app.api_sync_patients (?depuis=).

- colonne patients.sync_modifie_le (date UTC du dernier changement d'un champ
  synchronisé) ;
- déclencheur SQL qui la pose à chaque création, et à chaque modification d'un
  de ces champs — quel que soit le code qui modifie le patient (ORM ou SQL brut) ;
- index (structure_id, sync_modifie_le).

Additive et idempotente : sans risque à relancer. Les patients existants
gardent sync_modifie_le vide : gestion_patients les a déjà (et refait de toute
façon une synchro complète une fois par jour).

Usage :
    python migrate_sync_patients_incrementale.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

CHAMPS = ['structure_id', 'nom', 'prenom', 'telephone', 'adresse', 'date_naissance', 'type_assurance',
          'taux_prise_charge', 'numero_assure', 'assurance2_nom', 'taux_assurance2', 'numero_assure2',
          'personne_a_prevenir_nom', 'personne_a_prevenir_telephone', 'personne_a_prevenir_relation']

with app.app_context():
    existants = {r[0] for r in db.session.execute(db.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'patients'"))}
    manquants = [c for c in CHAMPS if c not in existants]
    if manquants:
        sys.exit(f"Colonnes absentes de patients : {manquants} — migration annulée.")
    nouveaux = ', '.join(f'NEW.{c}' for c in CHAMPS)
    anciens = ', '.join(f'OLD.{c}' for c in CHAMPS)
    db.session.execute(db.text('ALTER TABLE patients ADD COLUMN IF NOT EXISTS sync_modifie_le TIMESTAMP'))
    db.session.execute(db.text(f"""
        CREATE OR REPLACE FUNCTION patients_sync_modifie_le() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR ROW({nouveaux}) IS DISTINCT FROM ROW({anciens}) THEN
                NEW.sync_modifie_le := (now() AT TIME ZONE 'UTC');
            END IF;
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """))
    db.session.execute(db.text('DROP TRIGGER IF EXISTS trg_patients_sync_modifie_le ON patients'))
    db.session.execute(db.text("""
        CREATE TRIGGER trg_patients_sync_modifie_le BEFORE INSERT OR UPDATE ON patients
        FOR EACH ROW EXECUTE FUNCTION patients_sync_modifie_le()
    """))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_patients_structure_sync ON patients (structure_id, sync_modifie_le)'))
    db.session.commit()
    print('OK : synchro des patients modifiés prête (colonne, déclencheur, index).')
