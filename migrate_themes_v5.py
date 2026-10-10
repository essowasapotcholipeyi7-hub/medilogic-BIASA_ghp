# -*- coding: utf-8 -*-
"""Migration 2026-10-10 : nettoyage des réglages de thème figés par l'ancien
formulaire (toute la palette d'un thème sombre enregistrée comme réglages,
qui restait appliquée après retour à un thème clair — « ça ne revient
pas »). Supprime les réglages « mode sombre » complets posés sur un thème
qui n'est pas sombre. Idempotente."""
from app import app
from models import db, ThemeStructure, ThemeUtilisateur, ThemeCatalogue


def migrer():
    with app.app_context():
        sombres = {t.cle for t in ThemeCatalogue.query.all() if (t.variables or {}).get('mode_sombre')}
        n = 0
        for Modele in (ThemeStructure, ThemeUtilisateur):
            for r in Modele.query.all():
                perso = r.personnalisation or {}
                if len(perso) >= 10 and perso.get('mode_sombre') and (r.theme_cle or 'classique') not in sombres:
                    r.personnalisation = {}
                    n += 1
        db.session.commit()
        print(f"OK : {n} réglage(s) sombre(s) figé(s) retiré(s)")


if __name__ == '__main__':
    migrer()
