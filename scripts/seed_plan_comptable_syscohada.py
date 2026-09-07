# scripts/seed_plan_comptable_syscohada.py
# ============================================================
# INITIALISATION / MIGRATION DU PLAN COMPTABLE SYSCOHADA
# ============================================================
# - Désactive les anciens comptes ad-hoc (non-SYSCOHADA) créés par
#   l'ancienne route /api/init-comptes.
# - Crée (ou réactive) les comptes du plan SYSCOHADA officiel pour une
#   structure donnée, ou pour toutes les structures existantes.
#
# Utilisation :
#   python scripts/seed_plan_comptable_syscohada.py            # toutes les structures
#   python scripts/seed_plan_comptable_syscohada.py 3          # une seule structure (id=3)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import CompteComptable, Structure
from utils.plan_comptable_syscohada import PLAN_COMPTABLE, ANCIENS_COMPTES_A_DESACTIVER


def seed_pour_structure(structure_id):
    """Initialise/complète le plan comptable SYSCOHADA pour une structure."""
    nb_crees = 0
    nb_reactives = 0

    # 1) Désactiver les anciens comptes ad-hoc (jamais utilisés par une écriture
    #    puisque la génération automatique n'existait pas avant ce chantier).
    anciens = CompteComptable.query.filter(
        CompteComptable.structure_id == structure_id,
        CompteComptable.numero.in_(ANCIENS_COMPTES_A_DESACTIVER),
        CompteComptable.actif == True
    ).all()
    for c in anciens:
        c.actif = False

    # 2) Créer/réactiver les comptes SYSCOHADA
    for compte_def in PLAN_COMPTABLE:
        existant = CompteComptable.query.filter_by(
            structure_id=structure_id,
            numero=compte_def['numero']
        ).first()

        if existant:
            if not existant.actif:
                existant.actif = True
                nb_reactives += 1
            # On garde le nom/type existants si déjà personnalisés, sauf s'ils
            # sont vides.
            if not existant.nom:
                existant.nom = compte_def['nom']
            if not existant.type:
                existant.type = compte_def['type']
            if not existant.classe:
                existant.classe = compte_def['classe']
        else:
            nouveau = CompteComptable(
                structure_id=structure_id,
                numero=compte_def['numero'],
                nom=compte_def['nom'],
                type=compte_def['type'],
                classe=compte_def['classe']
            )
            db.session.add(nouveau)
            nb_crees += 1

    db.session.commit()
    print(f"  Structure {structure_id}: {nb_crees} compte(s) créé(s), {nb_reactives} réactivé(s), "
          f"{len(anciens)} ancien(s) compte(s) désactivé(s)")


def main():
    with app.app_context():
        if len(sys.argv) > 1:
            structure_ids = [int(sys.argv[1])]
        else:
            structure_ids = [s.id for s in Structure.query.all()]

        print(f"🚀 Migration du plan comptable SYSCOHADA pour {len(structure_ids)} structure(s)...")
        for sid in structure_ids:
            seed_pour_structure(sid)
        print("✅ Terminé.")


if __name__ == '__main__':
    main()
