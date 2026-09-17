# ============================================================
# POINT DE VÉRITÉ UNIQUE POUR LES ACCÈS PAR SECTION
# ============================================================
# Avant ce fichier, chaque route/blueprint/template comparait
# `session.get('role')` à sa propre liste de rôles autorisés, dupliquée
# à chaque endroit (voir l'historique de app.py, routes/comptabilite.py,
# routes/rh.py, routes/journal_routes.py, templates/sidebar_menu.html).
# `a_acces()` centralise la décision — rôle par défaut OU octroi
# d'habilitation ponctuel actif — pour que le sidebar et chaque route
# posent exactement la même question, une seule fois.
#
# Volontairement sans dépendance à `app.py` (seulement flask.session et
# models) : importable depuis app.py ET depuis chaque blueprint sans
# import circulaire.

from datetime import datetime
from flask import session

# clé -> libellé affiché dans l'onglet Habilitation (Administration)
PERMISSIONS = {
    'medecins_activites': 'Médecins & Activités',
    'protocoles': 'Protocoles et Modèles',
    'rendez_vous': 'Programmer Rendez-vous',
    'prescriptions_recues': 'Prescriptions reçues',
    'rappels': 'Rappels des rendez-vous',
    'comptabilite': 'Comptabilité',
    'finances': 'Finances / Caisse & Charges',
    'statistiques': 'Statistiques ventes/assurances',
    'annulations': 'Historique des annulations',
    'journal': 'Journal des mouvements',
    'rh': 'Ressources humaines',
    'demandes_laboratoire': 'Demandes de laboratoire',
    'demandes_radiologie': 'Demandes de radiologie',
    'patients_externes': 'Patients externes & prescripteurs',
}

# Rôles ayant accès par défaut à chaque section, sans octroi nécessaire.
# NOTE : "administration_generale" (utilisateurs, actes médicaux,
# paramètres structure) n'apparaît volontairement nulle part ici — cette
# section reste strictement admin, non habilitable (voir plan de session :
# l'ouvrir à un octroi temporaire recréerait la faille de privilège
# corrigée plus tôt cette session).
ROLES_PAR_DEFAUT = {
    'medecins_activites':   {'admin', 'caissier', 'secretaire', 'medecin', 'paramedical', 'pharmacien'},
    'protocoles':           {'admin', 'caissier', 'secretaire', 'medecin', 'paramedical', 'pharmacien'},
    'rendez_vous':          {'admin', 'caissier', 'secretaire', 'medecin', 'paramedical', 'pharmacien'},
    'prescriptions_recues': {'admin', 'caissier', 'secretaire', 'medecin', 'paramedical', 'pharmacien'},
    'rappels':              {'admin', 'caissier', 'secretaire', 'medecin', 'paramedical', 'pharmacien'},
    'comptabilite':       {'admin', 'comptable', 'sous_comptable', 'gestionnaire'},
    'finances':           {'admin', 'comptable', 'sous_comptable', 'gestionnaire'},
    'statistiques':       {'admin', 'comptable', 'sous_comptable', 'gestionnaire'},
    'annulations':        {'admin', 'comptable', 'sous_comptable', 'gestionnaire'},
    'journal':            {'admin', 'comptable', 'sous_comptable', 'gestionnaire'},
    'rh':                 {'admin', 'comptable', 'gestionnaire'},
    # ⭐ Circuit Laboratoire/Radiologie — cloisonnement strict demandé :
    # le laborantin ne voit jamais une demande de radiologie et
    # inversement (médecin/admin gardent les deux, ce sont eux qui
    # prescrivent). Le laborantin/radiologue lui-même n'a PAS besoin
    # d'être listé ici : sa route dédiée (/laboratoire, /radiologie) se
    # garde directement sur son propre rôle, ce fichier ne gère que le
    # cas "en plus du rôle propriétaire".
    'demandes_laboratoire': {'admin', 'medecin'},
    'demandes_radiologie':  {'admin', 'medecin'},
    'patients_externes':    {'admin', 'secretaire', 'caissier'},
}


def a_acces(permission_cle):
    """Vrai si le rôle de la session donne l'accès par défaut à cette
    section, OU s'il existe un octroi d'habilitation actif (et non
    expiré) pour cet utilisateur précis sur cette section."""
    role = session.get('role')
    if role in ROLES_PAR_DEFAUT.get(permission_cle, set()):
        return True
    if 'user_id' not in session or 'structure_id' not in session:
        return False
    from models import HabilitationTemporaire
    octrois = HabilitationTemporaire.query.filter_by(
        structure_id=session.get('structure_id'),
        utilisateur_id=session.get('user_id'),
        permission_cle=permission_cle,
        active=True,
    ).all()
    maintenant = datetime.utcnow()
    return any(o.date_expiration is None or o.date_expiration > maintenant for o in octrois)
