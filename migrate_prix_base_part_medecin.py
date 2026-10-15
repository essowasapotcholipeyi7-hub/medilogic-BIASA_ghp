# -*- coding: utf-8 -*-
"""Migration 2026-10-15 : prix de base propre à un médecin pour un acte (part médecin).
Vide = la part est calculée sur le prix de vente (comme avant). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE affectations_part_medecin ADD COLUMN IF NOT EXISTS prix_base NUMERIC"))
        db.session.commit()
        print("OK : affectations_part_medecin.prix_base")


if __name__ == '__main__':
    migrer()
