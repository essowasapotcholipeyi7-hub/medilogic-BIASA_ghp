# -*- coding: utf-8 -*-
"""Migration 2026-10-09 : thèmes / apparence par structure (patron) —
tables themes_catalogue, theme_structure, licences_theme + catalogue par
défaut. Idempotente. Usage : python migrate_themes.py"""
from app import app
from models import db, ThemeCatalogue, ThemeStructure, LicenceTheme


def migrer():
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[ThemeCatalogue.__table__, ThemeStructure.__table__, LicenceTheme.__table__])
        from services.theme_service import assurer_catalogue
        assurer_catalogue()
        print(f"OK : tables thèmes créées, catalogue = {ThemeCatalogue.query.count()} thème(s)")


if __name__ == '__main__':
    migrer()
