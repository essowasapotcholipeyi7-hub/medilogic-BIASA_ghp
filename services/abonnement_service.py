# ============================================================
# STATUT D'ABONNEMENT MENSUEL SSOFTONEV10 PAR STRUCTURE
# ============================================================
# Voir utils/modules_structure.py pour le registre des modules et le plan
# de session (C:\Users\HP\.claude\plans\wild-inventing-bubble.md) pour le
# contexte complet.
#
# Le paiement d'un mois n'est PAS un statut qu'on coche à la main : c'est
# l'existence d'une vraie ligne Depense (donc déjà validée — toute dépense
# passe par _demander_validation() dans app.py avant d'atterrir dans la
# table `depenses`) avec motif='abonnement_ssoftonev10', datée dans le mois
# courant, pour cette structure.

from calendar import monthrange
from datetime import date

MOTIF_ABONNEMENT = 'abonnement_ssoftonev10'

MOIS_FR = [
    '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
]


def mois_paye(structure_id, annee, mois):
    """Existe-t-il une charge d'abonnement validée pour ce mois ?"""
    from datetime import datetime, time
    from models import Depense
    debut = datetime.combine(date(annee, mois, 1), time.min)
    fin = datetime.combine(date(annee, mois, monthrange(annee, mois)[1]), time(23, 59, 59))
    return Depense.query.filter(
        Depense.structure_id == structure_id,
        Depense.motif == MOTIF_ABONNEMENT,
        Depense.date_depense >= debut,
        Depense.date_depense <= fin,
    ).first() is not None


def _parametrage(structure_id):
    from models import ParametrageAbonnement
    return ParametrageAbonnement.query.filter_by(structure_id=structure_id).first()


def onglet_cache(structure_id, module_key):
    """True si le super-admin a masqué ce module pour cette structure."""
    if not structure_id:
        return False
    param = _parametrage(structure_id)
    if not param:
        return False
    return module_key in param.liste_onglets_masques()


def statut_abonnement(structure_id):
    """Statut complet de l'abonnement pour cette structure, calculé à la
    volée (pas de champ à rafraîchir) : {suivi_actif, mois_paye,
    niveau_alerte, bloque_effectif, grace_active, prix_mensuel, message}."""
    aujourdhui = date.today()
    param = _parametrage(structure_id)

    base = {
        'suivi_actif': False,
        'mois_paye': True,
        'niveau_alerte': 'ok',
        'bloque_effectif': False,
        'grace_active': False,
        'prix_mensuel': None,
        'message': '',
    }

    if not param or not param.date_debut_suivi:
        return base
    if aujourdhui < param.date_debut_suivi:
        base['prix_mensuel'] = param.prix_mensuel
        return base

    base['suivi_actif'] = True
    base['prix_mensuel'] = param.prix_mensuel
    base['grace_active'] = bool(param.grace_active)

    paye = mois_paye(structure_id, aujourdhui.year, aujourdhui.month)
    base['mois_paye'] = paye

    if paye:
        return base

    if param.grace_active:
        base['niveau_alerte'] = 'jaune'
        base['bloque_effectif'] = False
        base['message'] = ("Dérogation accordée par l'administration — l'abonnement "
                            "SSoftOneV10 de ce mois reste à régulariser dès que possible.")
        return base

    jour = aujourdhui.day
    mois_libelle = f"{MOIS_FR[aujourdhui.month]} {aujourdhui.year}"

    if jour <= 5:
        base['niveau_alerte'] = 'jaune'
        base['message'] = (f"Pensez à régler l'abonnement SSoftOneV10 de {mois_libelle} "
                            f"avant le 10 du mois.")
    elif jour <= 10:
        base['niveau_alerte'] = 'rouge'
        base['message'] = (f"Urgent : l'abonnement SSoftOneV10 de {mois_libelle} doit être réglé "
                            f"avant le 10, sinon l'accès à l'application sera limité.")
    else:
        base['niveau_alerte'] = 'bloque'
        base['bloque_effectif'] = True
        base['message'] = (f"Accès limité : l'abonnement SSoftOneV10 de {mois_libelle} n'a pas été "
                            f"réglé avant le 10. Seuls le tableau de bord et « Enregistrer une "
                            f"charge » restent accessibles.")

    return base
