# -*- coding: utf-8 -*-
"""Migration 2026-10-18 : sexe du patient ('F' / 'M', vide = non renseigné). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS sexe VARCHAR(1)"))
        db.session.commit()
        print("OK : patients.sexe")


if __name__ == '__main__':
    migrer()
