# -*- coding: utf-8 -*-
"""Migration 2026-10-10 : interrupteur Soleil / Lune (dernier thème clair / sombre). Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        for t in ('theme_structure', 'theme_utilisateur'):
            for col in ('derniere_cle_claire', 'derniere_cle_sombre'):
                db.session.execute(db.text(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} VARCHAR(40)"))
        # ce qui est choisi aujourd'hui devient le « dernier » de son mode
        db.session.execute(db.text("UPDATE theme_structure SET derniere_cle_claire = theme_cle WHERE theme_cle IN (SELECT cle FROM themes_catalogue WHERE COALESCE((variables->>'mode_sombre')::boolean, FALSE) = FALSE) AND derniere_cle_claire IS NULL"))
        db.session.execute(db.text("UPDATE theme_structure SET derniere_cle_sombre = theme_cle WHERE theme_cle IN (SELECT cle FROM themes_catalogue WHERE COALESCE((variables->>'mode_sombre')::boolean, FALSE) = TRUE) AND derniere_cle_sombre IS NULL"))
        db.session.commit()
        print("OK : derniere_cle_claire / derniere_cle_sombre")


if __name__ == '__main__':
    migrer()
