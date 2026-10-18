# -*- coding: utf-8 -*-
"""Migration 2026-10-17 : chaque service de la structure a un TYPE (médical, laboratoire, imagerie,
pharmacie, autre) et dit s'il reçoit des HOSPITALISÉS (chambres et lits). Avant, la seule liste
était celle de l'hospitalisation : laboratoire, pharmacie... y étaient créés et proposés à
l'admission d'un séjour. Les services existants sont classés d'après leur nom. Idempotente."""
import unicodedata

from app import app
from models import db


def _norm(t):
    t = unicodedata.normalize('NFKD', t or '')
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def type_d_apres_nom(nom):
    n = _norm(nom)
    if 'pharmac' in n:
        return 'pharmacie'
    if 'laborat' in n or 'biolog' in n:
        return 'laboratoire'
    if 'radiolog' in n or 'imagerie' in n or 'echograph' in n or 'scanner' in n:
        return 'imagerie'
    return 'clinique'


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE services_hospitalisation ADD COLUMN IF NOT EXISTS type_service VARCHAR(20)"))
        db.session.execute(db.text("ALTER TABLE services_hospitalisation ADD COLUMN IF NOT EXISTS hospitalisation BOOLEAN"))
        db.session.commit()
        lignes = db.session.execute(db.text("""
            SELECT s.id, s.structure_id, s.nom,
                   EXISTS (SELECT 1 FROM chambres_hospitalisation c WHERE c.service_id = s.id) AS a_chambres,
                   EXISTS (SELECT 1 FROM hospitalisations h WHERE h.service_id = s.id) AS a_sejours
            FROM services_hospitalisation s WHERE s.type_service IS NULL ORDER BY s.structure_id, s.nom""")).mappings().all()
        for l in lignes:
            t = type_d_apres_nom(l['nom'])
            # un service qui a déjà des chambres ou des séjours garde l'hospitalisation, quel que soit son nom
            hosp = t == 'clinique' or bool(l['a_chambres']) or bool(l['a_sejours'])
            db.session.execute(db.text("UPDATE services_hospitalisation SET type_service = :t, hospitalisation = :h WHERE id = :i"),
                               {'t': t, 'h': hosp, 'i': l['id']})
            print(f"  structure {l['structure_id']:>4}  {l['nom'][:40]:<40} -> {t}{' + hospitalisation' if hosp else ''}")
        db.session.execute(db.text("UPDATE services_hospitalisation SET hospitalisation = true WHERE hospitalisation IS NULL"))
        db.session.commit()
        print(f"OK : services_hospitalisation.type_service / hospitalisation ({len(lignes)} service(s) classé(s))")


if __name__ == '__main__':
    migrer()
