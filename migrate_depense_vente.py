# -*- coding: utf-8 -*-
"""Migration 2026-10-14 : depenses.vente_id — vente rattachée à un « Remboursement
patient » (plafond = payé − déjà remboursé). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE depenses ADD COLUMN IF NOT EXISTS vente_id INTEGER"))
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_depenses_vente_id ON depenses (vente_id)"))
        db.session.commit()
        print("OK : depenses.vente_id")


if __name__ == '__main__':
    migrer()
