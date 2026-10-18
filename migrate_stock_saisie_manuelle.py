# -*- coding: utf-8 -*-
"""Migration 2026-10-18 : stock labo / radio — utilisation saisie à la main (nombre d'examens faits hors
du logiciel) et choix, par structure et par filière, de déduire ou non le stock automatiquement à la
réalisation des examens. Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE mouvements_consommables ADD COLUMN IF NOT EXISTS nb_examens INTEGER"))
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS parametrage_stock_labo (
                id SERIAL PRIMARY KEY,
                structure_id INTEGER NOT NULL,
                filiere VARCHAR(10) NOT NULL,
                deduction_auto BOOLEAN NOT NULL DEFAULT true,
                UNIQUE (structure_id, filiere)
            )"""))
        db.session.commit()
        print("OK : mouvements_consommables.nb_examens, parametrage_stock_labo")


if __name__ == '__main__':
    migrer()
