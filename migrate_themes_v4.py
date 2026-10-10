# -*- coding: utf-8 -*-
"""Migration 2026-10-10 : proposition du thème Noir à la connexion (theme_structure.proposition_vue). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE theme_structure ADD COLUMN IF NOT EXISTS proposition_vue BOOLEAN DEFAULT FALSE"))
        db.session.commit()
        print("OK : theme_structure.proposition_vue")


if __name__ == '__main__':
    migrer()
