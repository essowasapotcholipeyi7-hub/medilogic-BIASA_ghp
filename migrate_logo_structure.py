# -*- coding: utf-8 -*-
"""Migration 2026-10-09 : logo de la structure téléversé (table logos_structure). Idempotente."""
from app import app
from models import db, LogoStructure


def migrer():
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[LogoStructure.__table__])
        print("OK : table logos_structure")


if __name__ == '__main__':
    migrer()
