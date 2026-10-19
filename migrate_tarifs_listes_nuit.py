# -*- coding: utf-8 -*-
"""Migration 2026-10-19 (Clinique Valeo) : tarifs de nuit par liste et arrondi de la part patient.
  - pbr_complementaires.tarif_nuit / pbr_nuit : tarif et PBR de nuit (nuit, dimanche, férié) d'une
    compagnie ou d'une liste (« Liste Expatriés », « Liste SMA 25 % »…) ;
  - prix_non_assure_actes.prix_nuit : prix non assuré de nuit ;
  - parametrage_tarification : pas d'arrondi de la part patient par structure (0 = pas d'arrondi).
Le code lit ces colonnes avec to_jsonb (services/hospitalisation_service.py) : il marche avant comme
après cette migration. Idempotente.

    python migrate_tarifs_listes_nuit.py                 -> colonnes + table
    python migrate_tarifs_listes_nuit.py 13 50           -> + arrondi de 50 F pour la structure 13"""
import sys
from app import app
from models import db


def migrer(structure_id=None, pas=None):
    with app.app_context():
        for sql in ("ALTER TABLE pbr_complementaires ADD COLUMN IF NOT EXISTS tarif_nuit NUMERIC",
                    "ALTER TABLE pbr_complementaires ADD COLUMN IF NOT EXISTS pbr_nuit NUMERIC",
                    "ALTER TABLE prix_non_assure_actes ADD COLUMN IF NOT EXISTS prix_nuit NUMERIC",
                    """CREATE TABLE IF NOT EXISTS parametrage_tarification (
                           id SERIAL PRIMARY KEY,
                           structure_id INTEGER NOT NULL UNIQUE,
                           arrondi_pas NUMERIC NOT NULL DEFAULT 0,
                           updated_at TIMESTAMP DEFAULT NOW()
                       )"""):
            db.session.execute(db.text(sql))
        if structure_id is not None:
            db.session.execute(db.text(
                """INSERT INTO parametrage_tarification (structure_id, arrondi_pas) VALUES (:s, :p)
                   ON CONFLICT (structure_id) DO UPDATE SET arrondi_pas = EXCLUDED.arrondi_pas, updated_at = NOW()"""),
                {'s': int(structure_id), 'p': float(pas or 0)})
        db.session.commit()
        print("OK : tarif_nuit / pbr_nuit, prix_nuit, parametrage_tarification"
              + (f" ; structure {structure_id} : arrondi {pas} F" if structure_id is not None else ""))


if __name__ == '__main__':
    migrer(*(sys.argv[1:3] if len(sys.argv) >= 3 else ()))
