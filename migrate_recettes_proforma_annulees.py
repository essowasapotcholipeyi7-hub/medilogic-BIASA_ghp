# -*- coding: utf-8 -*-
"""Migration 2026-10-14 : encaissements de ventes issues d'une proforma convertie,
ventes annulées depuis, mais encaissement resté compté dans la caisse
(l'annulation ne marquait que 'vente_acte' / 'vente_pharma').
Marque ces recettes annulées et recalcule le solde de caisse des structures
concernées. Idempotente."""
from app import app
from models import db


def migrer():
    with app.app_context():
        rows = db.session.execute(db.text("""
            SELECT r.id, r.structure_id, r.montant FROM recettes r
            JOIN ventes v ON v.id = r.source_id AND v.structure_id = r.structure_id
            WHERE r.source_type = 'vente_proforma' AND v.statut = 'annulee'
            AND (r.est_annulation IS NULL OR r.est_annulation = FALSE)
        """)).fetchall()
        for r in rows:
            db.session.execute(db.text("""
                UPDATE recettes SET est_annulation = TRUE,
                    description = CONCAT(description, ' [ANNULEE - vente annulée, corrigé le 14/10/2026]')
                WHERE id = :id
            """), {'id': r.id})
        for sid in {r.structure_id for r in rows}:
            db.session.execute(db.text("""
                INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
                VALUES (:s,
                    (SELECT COALESCE(SUM(montant), 0) FROM recettes
                     WHERE structure_id = :s AND (est_annulation IS NULL OR est_annulation = FALSE))
                    - (SELECT COALESCE(SUM(montant), 0) FROM depenses WHERE structure_id = :s),
                    NOW())
                ON CONFLICT (structure_id) DO UPDATE SET
                    solde_actuel = EXCLUDED.solde_actuel, date_mise_a_jour = NOW()
            """), {'s': sid})
        db.session.commit()
        print(f"OK : {len(rows)} encaissement(s) de vente proforma annulée corrigé(s) "
              f"({sum(float(r.montant) for r in rows):.0f} F)")


if __name__ == '__main__':
    migrer()
