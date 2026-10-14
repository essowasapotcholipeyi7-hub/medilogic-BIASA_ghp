# -*- coding: utf-8 -*-
"""Migration 2026-10-14 : N° de bulletin propre à chaque structure (paies.numero_local),
numérotation des bulletins existants dans l'ordre chronologique (année, mois, création).
Idempotente : ne renumérote pas les bulletins qui ont déjà un numéro."""
from app import app
from models import db, Paie


def migrer():
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE paies ADD COLUMN IF NOT EXISTS numero_local INTEGER"))
        db.session.commit()
        n = 0
        for (sid,) in db.session.query(Paie.structure_id).distinct().all():
            dernier = db.session.query(db.func.max(Paie.numero_local)).filter(Paie.structure_id == sid).scalar() or 0
            for p in Paie.query.filter(Paie.structure_id == sid, Paie.numero_local.is_(None)) \
                    .order_by(Paie.annee, Paie.mois, Paie.id).all():
                dernier += 1
                p.numero_local = dernier
                n += 1
        db.session.commit()
        print(f"OK : paies.numero_local — {n} bulletin(s) numéroté(s)")


if __name__ == '__main__':
    migrer()
