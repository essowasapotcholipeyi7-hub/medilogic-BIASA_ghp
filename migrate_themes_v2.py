# -*- coding: utf-8 -*-
"""Migration 2026-10-09 (2) : thèmes — réglage personnel par utilisateur
(table theme_utilisateur), nouveaux thèmes du catalogue, thèmes payants à
10 000 F une seule fois. Idempotente. Usage : python migrate_themes_v2.py"""
from app import app
from models import db, ThemeCatalogue, ThemeUtilisateur
from utils.themes import THEMES_DEFAUT, PRIX_THEME_PAYANT


def migrer():
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[ThemeUtilisateur.__table__])
        from services.theme_service import assurer_catalogue
        assurer_catalogue()
        cles_defaut_payantes = {t['cle'] for t in THEMES_DEFAUT if t['payant']}
        n = 0
        for t in ThemeCatalogue.query.filter(ThemeCatalogue.payant.is_(True)).all():
            if t.cle in cles_defaut_payantes and float(t.prix or 0) != PRIX_THEME_PAYANT:
                t.prix = PRIX_THEME_PAYANT
                n += 1
        db.session.commit()
        print(f"OK : theme_utilisateur, catalogue = {ThemeCatalogue.query.count()} thème(s), {n} prix ramené(s) à {PRIX_THEME_PAYANT} F")


if __name__ == '__main__':
    migrer()
