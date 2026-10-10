# utils/navigation.py
# ============================================================
# Registre unique des onglets de l'application, rangés par domaine —
# patron, 2026-10-04 : "quand on y entre on ne sait pas par où commencer,
# quoi et comment [...] accès facile entre les onglets". Sert à deux
# endroits à la fois, pour qu'ils ne divergent jamais :
#   1. la page d'accueil (dashboard.html) : recherche "Que voulez-vous
#      faire ?", parcours du patient en 4 étapes, tous les onglets par
#      domaine ;
#   2. la barre de liens en haut de chaque page (base.html) : les autres
#      onglets du même domaine que la page ouverte.
#
# Les conditions `visible` reprennent À L'IDENTIQUE celles du menu
# horizontal de base.html (a_acces, onglet_cache, rôle, abonnement
# bloqué) : un lien n'apparaît ici que s'il apparaît aussi dans le menu.
# Ce n'est qu'un raccourci d'affichage — chaque route garde ses propres
# contrôles d'accès côté serveur.
# ============================================================

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ContexteNavigation:
    role: str
    is_admin: bool
    a_acces: Callable[[str], bool]
    onglet_cache: Callable[[str], bool]
    bloque: bool


@dataclass
class Onglet:
    id: str
    libelle: str
    endpoint: str
    icone: str
    description: str
    mots_cles: str = ''
    kwargs: dict = field(default_factory=dict)
    visible: Callable[[ContexteNavigation], bool] = lambda c: True
    # Faux uniquement pour les échappatoires qui restent accessibles même
    # abonnement non réglé (même logique que base.html).
    bloquable: bool = True


@dataclass
class Domaine:
    id: str
    libelle: str
    icone: str
    onglets: list
    # Le laborantin/radiologue n'a accès qu'au domaine Labo/Radio (même
    # restriction que le menu horizontal).
    pour_labo_radio: bool = False


def _pas_cache(module):
    return lambda c: not c.onglet_cache(module)


DOMAINES = [
    Domaine('patients', 'Patients', 'fa-users', [
        Onglet('patients', 'Liste des patients', 'patients', 'fa-user-plus',
               'Chercher ou créer un patient', 'nouveau patient dossier inscription',
               visible=_pas_cache('patients')),
        Onglet('accueil_qr', 'Accueil patient (QR)', 'page_accueil_qr', 'fa-qrcode',
               'Enregistrer par QR code', 'qr scan arrivée',
               visible=_pas_cache('patients')),
        Onglet('rendez_vous', 'Rendez-vous', 'rendez_vous', 'fa-calendar-check',
               'Programmer un rendez-vous', 'rdv agenda planning',
               visible=lambda c: not c.onglet_cache('patients') and c.a_acces('rendez_vous') and not c.onglet_cache('rendez_vous')),
        Onglet('rappels', 'Rappels', 'rappels', 'fa-bell',
               'Rappels des rendez-vous', 'sms relance',
               visible=lambda c: not c.onglet_cache('patients') and c.a_acces('rappels') and not c.onglet_cache('rappels')),
    ]),
    Domaine('soins', 'Soins et actes', 'fa-stethoscope', [
        Onglet('actes_vente', "Vente d'actes", 'actes_vente', 'fa-stethoscope',
               'Labo, radio, actes, hospit.', 'acte encaisser consultation vente',
               visible=_pas_cache('actes_vente')),
        Onglet('consultation', 'Consultation', 'consultation', 'fa-user-doctor',
               'Prise en charge médicale', 'médecin examen',
               visible=_pas_cache('consultation')),
        Onglet('hospitalisation', 'Hospitalisation', 'page_hospitalisation', 'fa-bed',
               'Suivi de séjour', 'hospit chambre lit séjour',
               visible=_pas_cache('hospitalisation')),
        Onglet('soins_ambulatoires', 'Soins ambulatoires', 'page_soins_ambulatoires', 'fa-kit-medical',
               'Soins sans hospitalisation', 'pansement injection',
               visible=_pas_cache('soins_ambulatoires')),
        Onglet('prescriptions', 'Prescriptions reçues', 'prescriptions_recues', 'fa-file-prescription',
               'Ordonnances à traiter', 'ordonnance prescription',
               visible=lambda c: c.a_acces('prescriptions_recues') and not c.onglet_cache('prescriptions_recues')),
        Onglet('protocoles', 'Protocoles et modèles', 'protocoles.page_protocoles', 'fa-clipboard-list',
               'Modèles de soins', 'protocole modèle',
               visible=lambda c: c.a_acces('protocoles') and not c.onglet_cache('protocoles')),
    ]),
    Domaine('pharmacie', 'Pharmacie', 'fa-pills', [
        Onglet('pharma_vente', 'Vente pharmacie', 'pharma_vente', 'fa-cart-shopping',
               'Vendre des médicaments', 'médicament vente caisse',
               visible=_pas_cache('pharmacie')),
        Onglet('gestion_stock', 'Actes et stock', 'gestion_stock', 'fa-boxes-stacked',
               'Catalogue, stock, inventaire', 'stock inventaire produit approvisionner tarif',
               visible=lambda c: not c.onglet_cache('pharmacie') and c.role in ('admin', 'comptable', 'gestionnaire', 'pharmacien')),
        Onglet('ventes_attente', 'Ventes en attente', 'page_ventes_en_attente', 'fa-hourglass-half',
               'Ventes à finaliser', 'attente panier',
               visible=lambda c: c.role in ('admin', 'caissier', 'secretaire')),
        Onglet('codes_barres', 'Codes-barres', 'page_codes_barres', 'fa-barcode',
               'Codes des articles', 'douchette scan',
               visible=lambda c: c.is_admin or c.role in ('gestionnaire', 'secretaire', 'caissier', 'pharmacien')),
    ]),
    Domaine('amu', 'AMU', 'fa-shield-heart', [
        Onglet('entente_prealable', 'Entente préalable', 'page_amu_entente_prealable', 'fa-file-medical',
               'Demander un accord AMU', 'ep accord cnss inam tns',
               visible=lambda c: c.a_acces('entente_prealable') and not c.onglet_cache('entente_prealable')),
        Onglet('tpc', 'TPC', 'page_amu_tpc', 'fa-prescription-bottle-medical',
               'Pathologies chroniques', 'ald chronique traitement',
               visible=lambda c: c.a_acces('tpc') and not c.onglet_cache('tpc')),
        Onglet('facture_amu_cnss', 'Facture AMU CNSS', 'page_facture_amu_cnss', 'fa-file-invoice',
               'Facture mensuelle CNSS', 'cnss bordereau',
               visible=_pas_cache('factures_amu')),
        Onglet('facture_amu_tns', 'Facture AMU TNS', 'page_facture_amu_cnss', 'fa-file-invoice',
               'Facture mensuelle TNS', 'tns bordereau', kwargs={'type_amu': 'tns'},
               visible=_pas_cache('factures_amu')),
        Onglet('facture_amu_inam', 'Facture AMU INAM', 'page_facture_amu_inam', 'fa-file-invoice',
               'Facture mensuelle INAM', 'inam bordereau',
               visible=_pas_cache('factures_amu')),
        Onglet('historique_factures_amu', 'Historique factures AMU', 'historique_factures_amu', 'fa-clock-rotate-left',
               'Factures AMU passées', 'historique bordereau',
               visible=_pas_cache('factures_amu')),
        Onglet('supports_cnss', 'Supports AMU CNSS', 'page_amu_supports', 'fa-folder-open',
               'Fiches à imprimer', 'fiche document cnss', kwargs={'type_amu': 'cnss'}),
        Onglet('supports_inam', 'Supports AMU INAM', 'page_amu_supports', 'fa-folder-open',
               'Fiches à imprimer', 'fiche document inam', kwargs={'type_amu': 'inam'}),
    ]),
    Domaine('finances', 'Finances', 'fa-sack-dollar', [
        Onglet('factures', 'Factures et créances', 'factures', 'fa-file-invoice-dollar',
               'Factures clients', 'créance impayé facture',
               visible=_pas_cache('factures')),
        Onglet('proformas', 'Factures proforma', 'proformas', 'fa-file-lines',
               'Devis pour les patients', 'devis proforma',
               visible=_pas_cache('proformas')),
        Onglet('proformas_chirurgie', 'Proformas chirurgie', 'chirurgie.page_proformas_chirurgie', 'fa-user-doctor',
               "Devis d'intervention en K", 'chirurgie intervention bloc devis proforma k',
               visible=_pas_cache('proformas_chirurgie')),
        Onglet('factures_assurances', 'Factures assurances', 'page_factures_assurances', 'fa-file-shield',
               'Assurances privées', 'assurance cac',
               visible=lambda c: c.role in ('caissier', 'secretaire')),
        Onglet('depenses_saisie', 'Enregistrer une charge', 'page_depenses_saisie', 'fa-receipt',
               'Dépense ou abonnement', 'dépense charge achat abonnement',
               visible=lambda c: not c.is_admin, bloquable=False),
        Onglet('admin_finances', 'Caisse et charges', 'admin_finances', 'fa-cash-register',
               'Caisse, dépenses, bilan', 'caisse finances bilan',
               visible=lambda c: c.a_acces('finances') and not c.onglet_cache('finances')),
        Onglet('statistiques', 'Statistiques', 'statistiques_ventes', 'fa-chart-line',
               'Ventes et assurances', 'statistiques chiffre affaires',
               visible=lambda c: c.a_acces('statistiques') and not c.onglet_cache('statistiques')),
        Onglet('recettes_service', 'Recettes par service', 'page_rapport_recettes_service', 'fa-chart-pie',
               'Recettes par service', 'service rapport',
               visible=lambda c: c.is_admin),
        Onglet('validations', 'Demandes en attente', 'page_validations', 'fa-circle-check',
               'Valider les demandes', 'validation approuver',
               visible=lambda c: c.is_admin or c.role == 'gestionnaire', bloquable=False),
    ]),
    Domaine('suivi', 'Historique et médecins', 'fa-clock-rotate-left', [
        Onglet('historique_ventes', 'Historique des ventes', 'historique_ventes', 'fa-clock-rotate-left',
               'Toutes les ventes passées', 'historique vente reçu réimprimer',
               visible=_pas_cache('historique_ventes')),
        Onglet('medecins', 'Médecins et activités', 'gestion_medecins', 'fa-user-doctor',
               'Liste des médecins', 'médecin prescripteur',
               visible=lambda c: c.a_acces('medecins_activites') and not c.onglet_cache('medecins_activites')),
        Onglet('part_medecin', 'Part médecin', 'page_part_medecin', 'fa-hand-holding-dollar',
               'Rétrocession aux médecins', 'part rétrocession',
               visible=lambda c: c.a_acces('medecins_activites') and not c.onglet_cache('medecins_activites')
               and not c.onglet_cache('part_medecin') and c.role in ('admin', 'secretaire', 'caissier', 'gestionnaire', 'comptable')),
        Onglet('taux_part_medecin', 'Taux part médecin', 'page_taux_part_medecin', 'fa-percent',
               'Configurer les taux', 'taux pourcentage',
               visible=lambda c: c.a_acces('medecins_activites') and not c.onglet_cache('medecins_activites')
               and (c.is_admin or c.role == 'gestionnaire')),
    ]),
    Domaine('labo', 'Labo et radio', 'fa-vial', pour_labo_radio=True, onglets=[
        Onglet('laboratoire', 'Laboratoire', 'page_laboratoire', 'fa-vial',
               'Demandes de laboratoire', 'labo analyse',
               visible=lambda c: not c.onglet_cache('laboratoire_radiologie') and (c.role == 'laborantin' or c.a_acces('demandes_laboratoire'))),
        Onglet('radiologie', 'Radiologie', 'page_radiologie', 'fa-x-ray',
               'Demandes de radiologie', 'radio imagerie',
               visible=lambda c: not c.onglet_cache('laboratoire_radiologie') and (c.role == 'radiologue' or c.a_acces('demandes_radiologie'))),
        Onglet('resultats', "Résultats d'analyses", 'page_resultats_analyses', 'fa-file-waveform',
               'Saisir et imprimer', 'résultat analyse',
               visible=lambda c: not c.onglet_cache('laboratoire_radiologie') and c.role in ('admin', 'medecin', 'laborantin', 'radiologue', 'secretaire')),
        Onglet('modeles_resultats', 'Modèles de résultats', 'page_modeles_resultats', 'fa-file-word',
               'Modèles de compte rendu', 'modèle compte rendu',
               visible=lambda c: not c.onglet_cache('laboratoire_radiologie') and c.role in ('laborantin', 'radiologue', 'secretaire')),
        Onglet('patients_externes', 'Patients externes', 'page_patients_externes', 'fa-user-tag',
               'Patients et prescripteurs', 'externe prescripteur',
               visible=lambda c: not c.onglet_cache('laboratoire_radiologie') and c.a_acces('patients_externes')),
        Onglet('ristournes', 'Ristournes', 'page_ristournes', 'fa-money-bill-transfer',
               'Ristournes prescripteurs', 'ristourne commission',
               visible=lambda c: not c.onglet_cache('laboratoire_radiologie') and c.role in ('admin', 'secretaire', 'caissier')),
    ]),
    Domaine('administration', 'Administration', 'fa-gear', [
        Onglet('admin_structure', 'Administration générale', 'admin_structure', 'fa-gear',
               'Utilisateurs, droits, réglages', 'utilisateur droit mot de passe paramètre',
               visible=lambda c: c.role in ('admin', 'gestionnaire'), bloquable=False),
        Onglet('theme', 'Thème & apparence', 'page_parametres_theme', 'fa-palette',
               'Couleurs, boutons, fond, police', 'thème apparence couleur design fond bouton police sombre',
               visible=lambda c: True, bloquable=False),
        Onglet('mot_de_passe', 'Mon mot de passe', 'page_changer_mot_de_passe', 'fa-key',
               'Changer son mot de passe', 'mot de passe changer sécurité compte',
               visible=lambda c: True, bloquable=False),
        Onglet('rh', 'Ressources humaines', 'rh.gestion_rh', 'fa-id-card',
               'Employés, congés, permissions', 'employé congé salaire',
               visible=lambda c: c.a_acces('rh') and not c.onglet_cache('rh')),
        Onglet('comptabilite', 'Comptabilité', 'comptabilite.index', 'fa-book',
               'Journal comptable', 'comptable écriture',
               visible=lambda c: c.a_acces('comptabilite') and not c.onglet_cache('comptabilite')),
        Onglet('annulations', 'Historique des annulations', 'historique_annulations', 'fa-ban',
               'Ventes annulées', 'annulation',
               visible=lambda c: c.a_acces('annulations') and not c.onglet_cache('annulations')),
        Onglet('journal', 'Journal des mouvements', 'journal.page_journal', 'fa-list-check',
               'Qui a fait quoi', 'journal trace mouvement',
               visible=lambda c: c.a_acces('journal') and not c.onglet_cache('journal')),
        Onglet('pbr', 'PBR complémentaires', 'page_pbr_complementaires', 'fa-tags',
               'Prix de base AMU', 'pbr tarif',
               visible=lambda c: c.role in ('admin', 'comptable', 'gestionnaire')),
        Onglet('config_services', 'Configuration des services', 'page_hospitalisation_configuration', 'fa-hospital',
               'Chambres et services', 'chambre salle service',
               visible=lambda c: c.is_admin or c.role == 'gestionnaire'),
        Onglet('classification_actes', 'Classification labo/radio', 'page_classification_actes', 'fa-sitemap',
               'Ranger les actes', 'classification',
               visible=lambda c: c.is_admin),
        Onglet('classification_services', 'Classification par service', 'page_classification_services', 'fa-sitemap',
               'Actes par service', 'classification service',
               visible=lambda c: c.is_admin),
        Onglet('sync_gp', 'Synchronisation gestion_patients', 'sync_gestion_patients_config', 'fa-rotate',
               'Lien avec gestion_patients', 'synchronisation',
               visible=lambda c: c.is_admin),
    ]),
]

# Parcours d'un patient dans la journée — une vraie séquence (accueil ->
# soins -> paiement -> suivi), d'où la numérotation des étapes.
PARCOURS = [
    {'titre': 'Accueillir', 'icone': 'fa-user-plus', 'description': 'Chercher ou créer le patient',
     'onglets': ['patients', 'accueil_qr']},
    {'titre': 'Soigner', 'icone': 'fa-stethoscope', 'description': 'Acte, consultation, hospitalisation',
     'onglets': ['actes_vente', 'consultation', 'hospitalisation']},
    {'titre': 'Encaisser', 'icone': 'fa-cash-register', 'description': 'Pharmacie, AMU, factures',
     'onglets': ['pharma_vente', 'entente_prealable', 'ventes_attente', 'factures']},
    {'titre': 'Suivre', 'icone': 'fa-calendar-check', 'description': 'Rendez-vous et historique',
     'onglets': ['rendez_vous', 'historique_ventes']},
]


def _onglet_visible(onglet, ctx):
    if ctx.bloque and onglet.bloquable:
        return False
    return onglet.visible(ctx)


def domaines_visibles(ctx):
    """Domaines et onglets que CET utilisateur verrait aussi dans le menu,
    sans les domaines devenus vides."""
    labo_radio = ctx.role in ('laborantin', 'radiologue')
    role_rh = ctx.role in ('agent_rh', 'responsable_rh')   # ⭐ comptes RH cloisonnés
    resultat = []
    for domaine in DOMAINES:
        if labo_radio and not domaine.pour_labo_radio:
            continue
        if role_rh and domaine.id != 'administration':
            continue
        onglets = [o for o in domaine.onglets if _onglet_visible(o, ctx)
                   and (not role_rh or o.id in ('rh', 'theme', 'mot_de_passe'))]
        if onglets:
            resultat.append((domaine, onglets))
    return resultat


def parcours_visible(domaines):
    """Étapes du parcours ne gardant que les onglets visibles ; une étape
    sans aucun onglet visible disparaît (la numérotation suit)."""
    par_id = {o.id: o for _, onglets in domaines for o in onglets}
    etapes = []
    for etape in PARCOURS:
        onglets = [par_id[i] for i in etape['onglets'] if i in par_id]
        if onglets:
            etapes.append({**etape, 'onglets': onglets})
    return etapes


def onglet_courant(domaines, endpoint, arguments):
    """(domaine, onglet) correspondant à la page ouverte, ou (None, None).
    Quand plusieurs onglets partagent le même endpoint (Facture AMU CNSS/
    TNS, Supports CNSS/INAM), celui dont les paramètres correspondent le
    mieux à l'URL l'emporte."""
    meilleur = (None, None, -1)
    for domaine, onglets in domaines:
        for o in onglets:
            if o.endpoint != endpoint:
                continue
            if any(str(arguments.get(k)) != str(v) for k, v in o.kwargs.items()):
                continue
            score = len(o.kwargs)
            if score > meilleur[2]:
                meilleur = (domaine, o, score)
    return meilleur[0], meilleur[1]
