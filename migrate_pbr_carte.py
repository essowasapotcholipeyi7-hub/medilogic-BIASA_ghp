# -*- coding: utf-8 -*-
"""Migration 2026-10-21 (Clinique Valeo, Convention CAT / ONMT) : base de remboursement de la carte d'assurance.
  - parametrage_tarification.libelle_pbr_1 / libelle_pbr_2 : noms des deux PBR d'une compagnie pour la
    structure (Valeo : « PBR CAT » / « PBR ONMT ») — renseignés = choix obligatoire sur la fiche patient ;
  - patients_liste_tarif.pbr_variante : base inscrite sur la carte du patient ('defaut' = PBR 1,
    'alternatif' = PBR 2), appliquée seule à la vente, en proforma et à l'hospitalisation.
Le code lit ces colonnes avec to_jsonb (services/hospitalisation_service.py) : il marche avant comme
après cette migration. Idempotente.

    python migrate_pbr_carte.py                              -> colonnes
    python migrate_pbr_carte.py 13 "PBR CAT" "PBR ONMT"      -> + libellés de la structure 13"""
import sys
from app import app
from models import db


def migrer(structure_id=None, libelle_1=None, libelle_2=None):
    with app.app_context():
        for sql in ("ALTER TABLE parametrage_tarification ADD COLUMN IF NOT EXISTS libelle_pbr_1 VARCHAR(40)",
                    "ALTER TABLE parametrage_tarification ADD COLUMN IF NOT EXISTS libelle_pbr_2 VARCHAR(40)",
                    "ALTER TABLE patients_liste_tarif ADD COLUMN IF NOT EXISTS pbr_variante VARCHAR(20)"):
            db.session.execute(db.text(sql))
        if structure_id is not None:
            db.session.execute(db.text(
                """INSERT INTO parametrage_tarification (structure_id, libelle_pbr_1, libelle_pbr_2) VALUES (:s, :l1, :l2)
                   ON CONFLICT (structure_id) DO UPDATE SET libelle_pbr_1 = EXCLUDED.libelle_pbr_1,
                       libelle_pbr_2 = EXCLUDED.libelle_pbr_2, updated_at = NOW()"""),
                {'s': int(structure_id), 'l1': libelle_1, 'l2': libelle_2})
        db.session.commit()
        print("OK : libelle_pbr_1 / libelle_pbr_2, patients_liste_tarif.pbr_variante"
              + (f" ; structure {structure_id} : {libelle_1} / {libelle_2}" if structure_id is not None else ""))


if __name__ == '__main__':
    migrer(*(sys.argv[1:4] if len(sys.argv) >= 4 else ()))
