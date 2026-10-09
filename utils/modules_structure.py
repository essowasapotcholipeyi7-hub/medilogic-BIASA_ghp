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
    'proformas_chirurgie':  {'label': 'Proformas chirurgie (cotation K)', 'endpoints': ['chirurgie.page_proformas_chirurgie']},
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
    'hospitalisation':       {'label': 'Hospitalisation (suivi de séjour)','endpoints': ['page_hospitalisation']},
    # ⭐ Regroupe en un seul onglet masquable (sidebar_menu.html : un seul
    # dropdown "Laboratoire & Radiologie") ce qui vivait avant en 7 liens
    # séparés — patron : "un seul onglet avec un nom spécifique qui
    # regroupe... et n'oublie pas de les ajouter à contrôler depuis
    # l'espace super admin". page_laboratoire/page_radiologie sont
    # DÉLIBÉRÉMENT absents de cette liste d'endpoints (même raison que
    # dashboard/page_validations plus haut) : ce sont le tableau de bord
    # du laborantin/radiologue lui-même (dashboard() les y redirige
    # inconditionnellement) — les y inclure créerait une boucle de
    # redirection infinie si jamais ce module était désactivé pour une
    # structure qui a pourtant du personnel labo/radio actif. Le lien
    # sidebar reste malgré tout masquable normalement (juste pas le
    # verrou serveur sur ces 2 routes précises).
    'laboratoire_radiologie': {'label': 'Laboratoire & Radiologie', 'endpoints': [
        'page_resultats_analyses', 'page_modeles_resultats', 'page_patients_externes',
        'page_ristournes', 'page_classification_actes', 'page_signatures_intervenants',
    ]},
    # ⭐ Rétrocession au médecin réalisateur (consultation, infiltration,
    # imagerie...) — même esprit que "laboratoire_radiologie" ci-dessus,
    # regroupe la page de clôture/paiement ET la configuration des taux
    # sous un seul module masquable.
    'part_medecin': {'label': 'Part Médecin', 'endpoints': [
        'page_part_medecin', 'page_taux_part_medecin',
    ]},
    # ⭐ Patron, 2026-10-02 : "vérifie maintenant dans admin global [...] les
    # onglets qui ne sont pas là, ajoute-les" — entente_prealable et tpc
    # existaient déjà comme clés de permission par rôle (voir
    # utils/permissions.py, a_acces()) mais n'étaient pas dans ce registre,
    # donc impossibles à masquer en bloc pour une structure depuis
    # admin_global.html. soins_ambulatoires était déjà appelé via
    # onglet_cache() dans base.html/sidebar_menu.html mais absent d'ici —
    # le masquage ne pouvait jamais être activé faute de case à cocher.
    'entente_prealable': {'label': 'Entente Préalable AMU', 'endpoints': ['page_amu_entente_prealable']},
    'tpc':                {'label': 'TPC (Traitement des Pathologies Chroniques)', 'endpoints': ['page_amu_tpc']},
    'soins_ambulatoires': {'label': 'Soins ambulatoires', 'endpoints': ['page_soins_ambulatoires']},
    'factures_amu':       {'label': 'Factures AMU (mensuelles)', 'endpoints': [
        'page_facture_amu_cnss', 'page_facture_amu_inam', 'historique_factures_amu',
    ]},
}
