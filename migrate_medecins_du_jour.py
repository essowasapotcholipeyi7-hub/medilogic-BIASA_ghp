# -*- coding: utf-8 -*-
"""Migration 2026-10-15 : plusieurs médecins du jour par structure (un par spécialité).
Unicité (structure, date) remplacée par (structure, date, médecin). Compatible avec
l'ancien code (qui lit la première ligne du jour). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE medecin_du_jour DROP CONSTRAINT IF EXISTS uq_structure_medecin_du_jour"))
        db.session.execute(db.text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_structure_date_medecin_du_jour') THEN
                    ALTER TABLE medecin_du_jour ADD CONSTRAINT uq_structure_date_medecin_du_jour UNIQUE (structure_id, date, medecin_id);
                END IF;
            END $$;"""))
        db.session.commit()
        print("OK : medecin_du_jour — plusieurs médecins par jour")


if __name__ == '__main__':
    migrer()
