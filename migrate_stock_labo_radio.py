# -*- coding: utf-8 -*-
"""Migration 2026-10-18 : stock du laboratoire et de la radiologie (films, tubes, réactifs), types
d'examens réalisables avec chaque article, et mouvements (approvisionnement, examens réalisés,
inventaire). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS consommables_labo (
                id SERIAL PRIMARY KEY,
                structure_id INTEGER NOT NULL,
                filiere VARCHAR(10) NOT NULL,
                categorie VARCHAR(20) NOT NULL,
                nom VARCHAR(200) NOT NULL,
                type_article VARCHAR(200),
                unite VARCHAR(40),
                quantite NUMERIC NOT NULL DEFAULT 0,
                seuil_alerte NUMERIC,
                actif BOOLEAN NOT NULL DEFAULT true,
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc')
            )"""))
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS usages_consommables (
                id SERIAL PRIMARY KEY,
                structure_id INTEGER NOT NULL,
                consommable_id INTEGER NOT NULL,
                acte_nom VARCHAR(255) NOT NULL,
                quantite_par_examen NUMERIC NOT NULL,
                UNIQUE (consommable_id, acte_nom)
            )"""))
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS mouvements_consommables (
                id SERIAL PRIMARY KEY,
                structure_id INTEGER NOT NULL,
                consommable_id INTEGER NOT NULL,
                date TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
                type_mouvement VARCHAR(20) NOT NULL,
                quantite NUMERIC NOT NULL,
                stock_apres NUMERIC,
                demande_id INTEGER,
                acte_nom VARCHAR(255),
                commentaire VARCHAR(300),
                auteur VARCHAR(255)
            )"""))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_consommables_labo_structure ON consommables_labo (structure_id, filiere)"))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_usages_consommables_acte ON usages_consommables (structure_id, acte_nom)"))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_mouvements_consommables ON mouvements_consommables (consommable_id, date)"))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_mouvements_consommables_demande ON mouvements_consommables (demande_id)"))
        db.session.commit()
        print("OK : consommables_labo, usages_consommables, mouvements_consommables")


if __name__ == '__main__':
    migrer()
