# -*- coding: utf-8 -*-
"""Registre des onglets/pages navigables de l'appli, pour la recherche
globale (barre du haut, voir /api/recherche-globale dans app.py) — patron :
"qu'on puisse rechercher un onglet... et nous conduire vers l'onglet en
question". Miroir des conditions de visibilité déjà utilisées dans
templates/base.html (menu horizontal) et sidebar_menu.html : un onglet
n'apparaît dans les résultats de recherche que si l'utilisateur aurait
accès à ce lien depuis l'un de ces deux menus — jamais un raccourci vers
une page qui lui serait de toute façon interdite.

Volontairement une simple fonction (pas une classe/config déclarative) :
chaque ligne se lit comme le `{% if %}` qu'elle recopie, ligne par ligne,
pour rester facile à comparer aux templates quand ceux-ci évoluent."""


def onglets_recherchables(role, is_admin, a_acces, onglet_cache_fn, bloq):
    """Retourne les onglets accessibles à CET utilisateur :
    [{'label': str, 'endpoint': str, 'kwargs': dict}, ...].

    `a_acces` et `onglet_cache_fn` sont les fonctions déjà utilisées
    partout ailleurs (utils/permissions.py, services/abonnement_service.py)
    — passées en argument plutôt qu'importées ici pour éviter tout import
    circulaire avec app.py. `onglet_cache_fn` doit déjà être fixée sur la
    structure courante (ex: `lambda cle: onglet_cache(structure_id, cle)`)."""
    role_labo_radio = role in ('laborantin', 'radiologue')
    if role in ('agent_rh', 'responsable_rh'):
        # ⭐ comptes RH cloisonnés : la GRH et leur compte, rien d'autre
        return [{'label': 'Ressources humaines', 'endpoint': 'rh.gestion_rh', 'kwargs': {}},
                {'label': 'Pointage du personnel', 'endpoint': 'rh.gestion_rh', 'kwargs': {}},
                {'label': 'Mon mot de passe', 'endpoint': 'page_changer_mot_de_passe', 'kwargs': {}}]
    resultat = []

    def ajouter(label, endpoint, condition, **kwargs):
        if condition:
            resultat.append({'label': label, 'endpoint': endpoint, 'kwargs': kwargs})

    ajouter('Tableau de bord', 'dashboard', True)
    ajouter('Liste des patients', 'patients',
            not role_labo_radio and not onglet_cache_fn('patients') and not bloq)
    ajouter('Accueil patient (QR)', 'page_accueil_qr',
            not role_labo_radio and not onglet_cache_fn('patients') and not bloq)
    ajouter('Programmer un rendez-vous', 'rendez_vous',
            not role_labo_radio and a_acces('rendez_vous') and not onglet_cache_fn('rendez_vous') and not bloq)
    ajouter('Rappels des rendez-vous', 'rappels',
            not role_labo_radio and a_acces('rappels') and not onglet_cache_fn('rappels') and not bloq)
    ajouter('Consultation & Prise en charge', 'consultation',
            not role_labo_radio and not onglet_cache_fn('consultation') and not bloq)
    ajouter('Labo/Radio/Hospi/Actes & Vente', 'actes_vente',
            not role_labo_radio and not onglet_cache_fn('actes_vente') and not bloq)
    ajouter('Gestion des actes et stocks de produits', 'gestion_stock',
            not role_labo_radio and not onglet_cache_fn('pharmacie') and not bloq)
    ajouter('Ventes en attente', 'page_ventes_en_attente',
            role in ('admin', 'caissier', 'secretaire') and not bloq)
    ajouter('Hospitalisation (suivi de séjour)', 'page_hospitalisation',
            not role_labo_radio and not onglet_cache_fn('hospitalisation') and not bloq)
    ajouter('Soins ambulatoires', 'page_soins_ambulatoires',
            not role_labo_radio and not onglet_cache_fn('soins_ambulatoires') and not bloq)
    ajouter('Prescriptions reçues', 'prescriptions_recues',
            not role_labo_radio and a_acces('prescriptions_recues') and not onglet_cache_fn('prescriptions_recues') and not bloq)
    ajouter('Vente pharmacie', 'pharma_vente',
            not role_labo_radio and not onglet_cache_fn('pharmacie') and not bloq)
    ajouter('Factures clients & Créances', 'factures',
            not role_labo_radio and not onglet_cache_fn('factures') and not bloq)
    ajouter('Factures Proforma', 'proformas',
            not role_labo_radio and not onglet_cache_fn('proformas') and not bloq)
    ajouter('Factures assurances', 'page_factures_assurances',
            not role_labo_radio and role in ('caissier', 'secretaire') and not bloq)
    ajouter('Facture AMU CNSS (mensuelle)', 'page_facture_amu_cnss',
            not role_labo_radio and not bloq)
    ajouter('Facture AMU TNS (mensuelle)', 'page_facture_amu_cnss',
            not role_labo_radio and not bloq, type_amu='tns')
    ajouter('Facture AMU INAM (mensuelle)', 'page_facture_amu_inam',
            not role_labo_radio and not bloq)
    ajouter('Historique factures AMU', 'historique_factures_amu',
            not role_labo_radio and not bloq)
    ajouter('Enregistrer une charge', 'page_depenses_saisie', not role_labo_radio)
    ajouter('Finances / Caisse & Charges', 'admin_finances',
            not role_labo_radio and a_acces('finances') and not onglet_cache_fn('finances') and not bloq)
    ajouter('Part Médecin', 'page_part_medecin',
            not role_labo_radio and not onglet_cache_fn('part_medecin') and not bloq
            and role in ('admin', 'secretaire', 'caissier', 'gestionnaire', 'comptable'))
    ajouter('Statistiques ventes/assurances', 'statistiques_ventes',
            not role_labo_radio and a_acces('statistiques') and not onglet_cache_fn('statistiques') and not bloq)
    ajouter('Demandes en attente', 'page_validations',
            not role_labo_radio and (is_admin or role == 'gestionnaire'))
    ajouter('Historique des ventes', 'historique_ventes',
            not role_labo_radio and not onglet_cache_fn('historique_ventes') and not bloq)
    ajouter('Médecins & Activités', 'gestion_medecins',
            not role_labo_radio and a_acces('medecins_activites') and not onglet_cache_fn('medecins_activites') and not bloq)
    ajouter('Laboratoire', 'page_laboratoire',
            role == 'laborantin' or (not role_labo_radio and a_acces('demandes_laboratoire')
                                      and not onglet_cache_fn('laboratoire_radiologie') and not bloq))
    ajouter('Radiologie', 'page_radiologie',
            role == 'radiologue' or (not role_labo_radio and a_acces('demandes_radiologie')
                                      and not onglet_cache_fn('laboratoire_radiologie') and not bloq))
    ajouter("Résultats d'analyses", 'page_resultats_analyses',
            not role_labo_radio and role in ('admin', 'medecin', 'secretaire')
            and not onglet_cache_fn('laboratoire_radiologie') and not bloq)
    ajouter('Modèles de résultats', 'page_modeles_resultats',
            not role_labo_radio and role == 'secretaire'
            and not onglet_cache_fn('laboratoire_radiologie') and not bloq)
    ajouter('Signatures électroniques', 'page_signatures_intervenants',
            not role_labo_radio and role == 'secretaire'
            and not onglet_cache_fn('laboratoire_radiologie') and not bloq)
    ajouter('Patients externes & prescripteurs', 'page_patients_externes',
            not role_labo_radio and a_acces('patients_externes')
            and not onglet_cache_fn('laboratoire_radiologie') and not bloq)
    ajouter('Ristournes', 'page_ristournes',
            not role_labo_radio and role in ('admin', 'secretaire', 'caissier')
            and not onglet_cache_fn('laboratoire_radiologie') and not bloq)
    ajouter('Classification Labo/Radio', 'page_classification_actes',
            not role_labo_radio and is_admin and not onglet_cache_fn('laboratoire_radiologie') and not bloq)
    ajouter('Administration', 'admin_structure', role in ('admin', 'gestionnaire'))
    ajouter('Ressources humaines', 'rh.gestion_rh',
            a_acces('rh') and not onglet_cache_fn('rh') and not bloq)
    ajouter('Comptabilité', 'comptabilite.index',
            a_acces('comptabilite') and not onglet_cache_fn('comptabilite') and not bloq)
    ajouter('Historique des annulations', 'historique_annulations',
            a_acces('annulations') and not onglet_cache_fn('annulations') and not bloq)
    ajouter('Synchronisation gestion_patients', 'sync_gestion_patients_config', is_admin)
    ajouter('PBR Complémentaires', 'page_pbr_complementaires',
            role in ('admin', 'comptable', 'gestionnaire'))
    ajouter('Configurer les taux (Part Médecin)', 'page_taux_part_medecin',
            is_admin or role == 'gestionnaire')
    ajouter("Guide d'utilisation", 'guide_utilisation', True)
    ajouter('FAQ', 'page_faq', True)

    return resultat
