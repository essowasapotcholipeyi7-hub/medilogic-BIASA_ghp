# -*- coding: utf-8 -*-
"""Migration 2026-10-16 : journal des tentatives de connexion (heure, compte visé, résultat,
adresse IP, appareil) — consulté par l'administrateur global. Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS tentatives_connexion (
                id SERIAL PRIMARY KEY,
                date TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
                email VARCHAR(255),
                structure_id INTEGER,
                compte_nom VARCHAR(255),
                type_compte VARCHAR(30),
                resultat VARCHAR(40) NOT NULL,
                ip VARCHAR(64),
                appareil VARCHAR(120),
                user_agent VARCHAR(400)
            )"""))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_tentatives_connexion_date ON tentatives_connexion (date DESC)"))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_tentatives_connexion_email ON tentatives_connexion (email)"))
        db.session.commit()
        print("OK : tentatives_connexion")


if __name__ == '__main__':
    migrer()
