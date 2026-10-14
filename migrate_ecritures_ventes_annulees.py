# -*- coding: utf-8 -*-
"""Migration 2026-10-14 : écritures NON validées (brouillon / en attente) de ventes
déjà annulées — créées après coup par un rattrapage, elles risquaient d'être
validées un jour et de compter une vente annulée dans le chiffre d'affaires.
Elles sont marquées « refusée ». Les écritures validées ont déjà leur
contre-passation. Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        n = db.session.execute(db.text("""
            UPDATE ecritures_comptables e
            SET statut = 'refuse',
                commentaire = TRIM(BOTH ' —' FROM COALESCE(e.commentaire, '') || ' — vente annulée : écriture non validée, écartée (14/10/2026)')
            FROM ventes v
            WHERE v.statut = 'annulee' AND v.structure_id = e.structure_id
            AND e.id IN (v.ecriture_id, v.ecriture_encaissement_id)
            AND e.statut IN ('brouillon', 'en_attente')
        """)).rowcount
        db.session.commit()
        print(f"OK : {n} écriture(s) non validée(s) de ventes annulées écartée(s)")


if __name__ == '__main__':
    migrer()
