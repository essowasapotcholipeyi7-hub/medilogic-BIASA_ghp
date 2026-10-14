# -*- coding: utf-8 -*-
"""Migration 2026-10-14 : paie par rubriques, bulletin modèle CNSS.
- tables rubriques_paie, rubriques_employe ;
- colonnes employes (catégorie, direction, division, N° CNSS, banque, compte),
  paies (lignes, jours, bases CNSS / IRPP), parametrage_paie (affichage
  des cotisations, arrondi de la base IRPP, jours du mois) ;
- barème IRPP : l'ancien barème par défaut (jamais modifié) est remplacé par
  le barème officiel (confirmé par le bulletin CNSS modèle).
Idempotente. Usage : python migrate_paie_rubriques.py"""
from app import app
from models import db, RubriquePaie, RubriqueEmploye, ParametragePaie
from utils.paie_rubriques import BAREME_IRPP_TOGO, ANCIEN_BAREME_DEFAUT


def _norm(tranches):
    return [(float(t.get('min') or 0), None if t.get('max') in (None, '') else float(t.get('max')), float(t.get('taux') or 0))
            for t in (tranches or [])]


def migrer():
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[RubriquePaie.__table__, RubriqueEmploye.__table__])
        for sql in (
            "ALTER TABLE employes ADD COLUMN IF NOT EXISTS categorie_paie VARCHAR(20)",
            "ALTER TABLE employes ADD COLUMN IF NOT EXISTS direction VARCHAR(150)",
            "ALTER TABLE employes ADD COLUMN IF NOT EXISTS division VARCHAR(150)",
            "ALTER TABLE employes ADD COLUMN IF NOT EXISTS numero_cnss VARCHAR(30)",
            "ALTER TABLE employes ADD COLUMN IF NOT EXISTS banque VARCHAR(100)",
            "ALTER TABLE employes ADD COLUMN IF NOT EXISTS numero_compte VARCHAR(50)",
            "ALTER TABLE paies ADD COLUMN IF NOT EXISTS lignes JSON",
            "ALTER TABLE paies ADD COLUMN IF NOT EXISTS jours_travailles INTEGER",
            "ALTER TABLE paies ADD COLUMN IF NOT EXISTS base_cnss NUMERIC",
            "ALTER TABLE paies ADD COLUMN IF NOT EXISTS base_irpp NUMERIC",
            "ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS affichage_cotisations VARCHAR(12) DEFAULT 'combinee'",
            "ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS irpp_arrondi_base INTEGER DEFAULT 1000",
            "ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS jours_mois INTEGER DEFAULT 30",
        ):
            db.session.execute(db.text(sql))
        db.session.commit()
        n = 0
        for p in ParametragePaie.query.all():
            if p.affichage_cotisations is None:
                p.affichage_cotisations = 'combinee'
            if p.irpp_arrondi_base is None:
                p.irpp_arrondi_base = 1000
            if p.jours_mois is None:
                p.jours_mois = 30
            if not p.tranches_irpp or _norm(p.tranches_irpp) == _norm(ANCIEN_BAREME_DEFAUT):
                p.tranches_irpp = BAREME_IRPP_TOGO
                n += 1
        db.session.commit()
        print(f"OK : rubriques de paie + colonnes ; barème IRPP officiel appliqué à {n} structure(s) au barème d'origine")


if __name__ == '__main__':
    migrer()
