# -*- coding: utf-8 -*-
"""Migration 2026-10-09 (3) : paiement d'un thème depuis l'application
(moyen, référence, vérification éditeur, charge liée). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        for col in ("moyen_paiement VARCHAR(30)", "reference_paiement VARCHAR(100)", "paye_verifie BOOLEAN DEFAULT FALSE",
                    "demande_id INTEGER", "depense_id INTEGER"):
            db.session.execute(db.text(f"ALTER TABLE licences_theme ADD COLUMN IF NOT EXISTS {col}"))
        # licences déjà marquées payées par l'éditeur = vérifiées
        db.session.execute(db.text("UPDATE licences_theme SET paye_verifie = TRUE WHERE paye = TRUE AND paye_verifie IS NULL"))
        db.session.commit()
        print("OK : licences_theme — colonnes de paiement ajoutées")


if __name__ == '__main__':
    migrer()
