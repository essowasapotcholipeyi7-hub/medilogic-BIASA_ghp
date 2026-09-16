# ============================================================
# REGISTRE UNIQUE DES MODULES DE STRUCTURE
# ============================================================
# Sert à trois usages à la fois — même esprit que PERMISSIONS/a_acces()
# dans utils/permissions.py, mais à l'échelle de la structure entière (pas
# du rôle d'un utilisateur) :
#   1. Curation super-admin : quels onglets masquer durablement pour une
#      structure qui n'en a pas besoin (voir admin_global.html).
#   2. Verrou d'abonnement : quels endpoints bloquer si la structure n'a
#      pas réglé son abonnement du mois (voir app.py, boucle de
#      verrouillage programmatique en fin de fichier).
#   3. Affichage : masquer les liens correspondants dans sidebar_menu.html
#      et le mega-menu de base.html.
#
# Volontairement absents (toujours accessibles, jamais masquables) :
# dashboard, page_depenses_saisie ("Enregistrer une charge" — l'échappatoire
# qui permet de payer même verrouillé), page_validations ("Demandes en
# attente" — sinon un admin bloqué ne pourrait jamais valider SA propre
# charge d'abonnement), admin_structure (même logique que l'exclusion
# volontaire de "administration_generale" dans utils/permissions.py),
# guide_utilisation, logout.
#
# Simplification assumée, cohérente avec a_acces() aujourd'hui : on ne
# verrouille que la page d'entrée de chaque module (ex. comptabilite.index,
# rh.gestion_rh), pas chaque route API interne du blueprint — ces modules
# sont des SPA à onglets internes, inaccessibles sans passer par la page
# d'entrée, elle-même retirée du nav.

MODULES_STRUCTURE = {
    'patients':             {'label': 'Liste Patients',                  'endpoints': ['patients']},
    'actes_vente':          {'label': 'Labo/Radio/Hospi/Actes&Vente',    'endpoints': ['actes_vente']},
    'consultation':         {'label': 'Consultation & Prise en charge',  'endpoints': ['consultation']},
    'prescriptions_recues': {'label': 'Prescriptions reçues',            'endpoints': ['prescriptions_recues']},
    'pharmacie':            {'label': 'Pharmacie & Vente',               'endpoints': ['pharma_vente', 'gestion_stock']},
    'factures':             {'label': 'Factures clients & Créances',     'endpoints': ['factures']},
    'proformas':            {'label': 'Factures Proforma',               'endpoints': ['proformas']},
    'historique_ventes':    {'label': 'Historique des ventes',           'endpoints': ['historique_ventes']},
    'medecins_activites':   {'label': 'Médecins & Activités',            'endpoints': ['gestion_medecins']},
    'protocoles':           {'label': 'Protocoles et Modèles',           'endpoints': ['protocoles.page_protocoles']},
    'rendez_vous':          {'label': 'Programmer Rendez-vous',          'endpoints': ['rendez_vous']},
    'rappels':              {'label': 'Rappels des rendez-vous',         'endpoints': ['rappels']},
    'statistiques':         {'label': 'Statistiques ventes/assurances',  'endpoints': ['statistiques_ventes']},
    'annulations':          {'label': 'Historique des annulations',      'endpoints': ['historique_annulations']},
    'journal':               {'label': 'Journal des mouvements',          'endpoints': ['journal.page_journal']},
    'finances':              {'label': 'Finances / Caisse & Charges',     'endpoints': ['admin_finances']},
    'comptabilite':          {'label': 'Comptabilité',                    'endpoints': ['comptabilite.index']},
    'rh':                    {'label': 'Ressources humaines',             'endpoints': ['rh.gestion_rh']},
}
