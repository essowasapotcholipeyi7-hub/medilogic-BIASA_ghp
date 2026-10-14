# -*- coding: utf-8 -*-
"""Migration 2026-10-14 : N° de bulletin PAR EMPLOYÉ (paies.numero_local) —
1er, 2e, 3e... bulletin de la même personne, dans l'ordre des mois.
Idempotente (renumérote chaque employé selon l'ordre chronologique)."""
from app import app
from models import db, Paie


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE paies ADD COLUMN IF NOT EXISTS numero_local INTEGER"))
        db.session.commit()
        from services.paie_service import numeroter_bulletins
        employes = [e for (e,) in db.session.query(Paie.employe_id).distinct().all()]
        for eid in employes:
            numeroter_bulletins(eid)
        db.session.commit()
        print(f"OK : bulletins numérotés par employé ({len(employes)} employé(s))")


if __name__ == '__main__':
    migrer()
