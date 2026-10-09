# -*- coding: utf-8 -*-
"""Migration 2026-10-09 : NIF du médecin + taux RSPS « sans NIF » (patron :
la RSPS concerne les médecins qui ont le NIF). Idempotente.
Usage : python migrate_medecin_nif.py"""
from app import app
from models import db


def migrer():
    with app.app_context():
        for sql in (
            "ALTER TABLE medecins ADD COLUMN IF NOT EXISTS nif VARCHAR(30)",
            "ALTER TABLE parametrage_part_medecin ADD COLUMN IF NOT EXISTS taux_rsps_sans_nif NUMERIC DEFAULT 0",
        ):
            db.session.execute(db.text(sql))
        db.session.commit()
        print("OK : medecins.nif + parametrage_part_medecin.taux_rsps_sans_nif")


if __name__ == '__main__':
    migrer()
