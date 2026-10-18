# -*- coding: utf-8 -*-
"""Migration 2026-10-18 : messages des structures au service SSoftOne (page « Nous contacter »),
envoyés par e-mail à l'adresse du service et gardés ici pour l'administrateur global. Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS messages_support (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
                structure_id INTEGER,
                structure_nom VARCHAR(200),
                user_id INTEGER,
                user_name VARCHAR(255),
                role VARCHAR(50),
                email_reponse VARCHAR(255),
                telephone VARCHAR(50),
                categorie VARCHAR(40),
                objet VARCHAR(200),
                message TEXT NOT NULL,
                statut VARCHAR(20) NOT NULL DEFAULT 'nouveau',
                email_envoye BOOLEAN NOT NULL DEFAULT false,
                erreur_email VARCHAR(300),
                traite_le TIMESTAMP
            )"""))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_messages_support_date ON messages_support (created_at DESC)"))
        db.session.commit()
        print("OK : messages_support")


if __name__ == '__main__':
    migrer()
