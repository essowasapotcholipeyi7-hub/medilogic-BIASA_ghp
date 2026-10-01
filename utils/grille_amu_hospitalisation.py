# utils/grille_amu_hospitalisation.py
# ============================================================
# Grille tarifaire officielle AMU pour l'hospitalisation (code P160) et
# l'oxygénothérapie (code O101) — extraite le 2026-10-01 du fichier fourni
# par le patron "ACTES HOSPITALISATION oxygène AMU.xlsx" (feuille HOSPI).
#
# Le fichier liste 5 libellés de prestataire (CHU, Clinique privée, CHR,
# Hôpital de district, Cabinet privé) mais leurs montants ne forment en
# réalité que 2 paliers de prix distincts, confirmé par le patron
# (2026-10-01) :
#   - niveau 3 = CHU + Clinique privée (tarifs les plus élevés)
#   - niveau 2 = CHR + Hôpital de district + Cabinet privé (tarifs bas)
# Niveau 1 n'apparaît pas dans ce fichier (pas de tarif ici pour l'instant).
#
# Le nombre de lits (1 ou 2) et le type de cabine (ventilée/climatisée)
# n'ont AUCUN effet sur le montant dans le fichier source (toujours le même
# montant dans chaque groupe) — une seule catégorie "cabine" suffit donc.
#
# ⭐ Remarque sur une incohérence du fichier source : "Salle commune 7 à 9
# lits / 15 jours et plus / niveau 2" affiche 625 pour CHR mais 375 pour
# Hôpital de district (seule valeur qui casse la progression régulière
# observée partout ailleurs ~2500/1625/875 proportionnellement) — retenu
# ici : 625 (cohérent avec le reste de la grille). À corriger si le patron
# confirme que 375 est la bonne valeur.
#
# "Salle commune 10 à 12 lits" n'existe que pour le niveau 3 dans le
# fichier source (aucune ligne niveau 2) — absente ici au niveau 2.
#
# "Mise en observation" n'a qu'un seul montant (pas de dégressivité par
# semaine) — mémorisé ici comme valant pour les 3 paliers. Une mise en
# observation est par nature un court séjour : le patron (2026-10-01) a
# demandé qu'elle ne dépasse jamais JOURS_MAX_OBSERVATION jours — voir la
# validation dans app.py (api_definir_chambre_tarif_hospitalisation /
# api_sortie_hospitalisation).
#
# Utilisation (Phase 2) : pbr_officiel_p160(niveau, categorie_salle, palier)
# — reste SANS EFFET tant qu'une structure n'a pas explicitement fait
# correspondre un de ses actes "chambre" à une catégorie via
# CorrespondanceSalleAmu (zéro régression pour les structures qui n'ont
# rien configuré).
#
# Hors périmètre, volontairement : le forfait "Réa Polyvalente CHU SO"
# (5000F, statut EP) — spécifique au CHU SO de Lomé, le patron a demandé de
# le laisser tel quel, pas de généralisation.
# ============================================================

TAUX_AMU_P160 = 90  # déjà en place ailleurs (taux_amu_pour_article), rappelé ici pour référence
TAUX_AMU_O101 = 100

# Une "mise en observation" (catégorie 'observation') ne peut pas dépasser
# ce nombre de jours — au-delà, ce n'est plus une observation mais une
# vraie hospitalisation, qui doit être catégorisée dans une autre salle
# (cabine, salle commune...). Voir app.py, routes chambre_tarif/sortie.
JOURS_MAX_OBSERVATION = 3

# Au-delà de ce nombre de jours, un acte P160 (hospitalisation) doit être
# facturé avec la dégression par palier (1ère semaine / 8e-14e jour / 15e
# jour et plus) — voir construire_lignes_chambre(),
# services/hospitalisation_service.py. En dessous ou à ce seuil, une seule
# ligne au PBR plat est exacte (aucun palier n'est traversé).
JOURS_MAX_SANS_PALIER = 7

# Catégories canoniques de salle — libellé affiché dans la future page de
# correspondance (Phase 2).
CATEGORIES_SALLE_AMU = [
    ('observation', "Salle d'observation"),
    ('cabine', 'Cabine (ventilée ou climatisée, 1 ou 2 lits)'),
    ('salle_commune_3_6', 'Salle commune 3 à 6 lits'),
    ('salle_commune_7_9', 'Salle commune 7 à 9 lits'),
    ('salle_commune_10_12', 'Salle commune 10 à 12 lits'),
    ('reanimation', 'Réanimation'),
]

# {niveau: {categorie_salle: {palier: base_remboursement}}}
# palier 1 = Première semaine (jours 1-7), 2 = 8e au 14e jour, 3 = 15e jour et plus.
GRILLE_AMU_HOSPITALISATION = {
    '3': {  # CHU + Clinique privée
        'observation': {1: 1250, 2: 1250, 3: 1250},
        'cabine': {1: 5000, 2: 3375, 3: 1625},
        'salle_commune_3_6': {1: 3125, 2: 2125, 3: 1000},
        'salle_commune_7_9': {1: 2500, 2: 1625, 3: 875},
        'salle_commune_10_12': {1: 1875, 2: 1250, 3: 625},
        'reanimation': {1: 3125, 2: 2125, 3: 1000},
    },
    '2': {  # CHR + Hôpital de district + Cabinet privé
        'observation': {1: 625, 2: 625, 3: 625},
        'cabine': {1: 3750, 2: 2500, 3: 1250},
        'salle_commune_3_6': {1: 2500, 2: 1625, 3: 875},
        'salle_commune_7_9': {1: 1875, 2: 1250, 3: 625},
        'reanimation': {1: 2500, 2: 1625, 3: 875},
    },
}


def erreur_duree_observation(categorie_salle, nb_jours):
    """None si `categorie_salle`/`nb_jours` ne posent pas de problème,
    sinon le message d'erreur à renvoyer — une "mise en observation" ne
    peut pas dépasser JOURS_MAX_OBSERVATION jours (voir ce nom)."""
    if categorie_salle == 'observation' and nb_jours and nb_jours > JOURS_MAX_OBSERVATION:
        return (
            f"Une mise en observation ne peut pas dépasser {JOURS_MAX_OBSERVATION} jours "
            f"({nb_jours} jours ici). Choisissez une autre catégorie de salle si le séjour est plus long."
        )
    return None


def erreur_p160_quantite_hors_hospitalisation(nom, quantite, prise_en_charge_amu, est_assure_amu):
    """None si rien ne cloche, sinon le message d'erreur à renvoyer.

    Vendre directement (vente d'actes, conversion de proforma...) un acte
    "chambre" P160 avec plus de JOURS_MAX_SANS_PALIER jours calcule le PBR
    à plat (pbr_unitaire x quantité) — faux dès qu'un patient assuré AMU
    franchit un palier (1ère semaine / 8e-14e jour / 15e jour et plus), qui
    doit dégresser le PBR jour par jour (voir construire_lignes_chambre,
    services/hospitalisation_service.py). Bloqué UNIQUEMENT quand ça
    fausserait réellement un remboursement AMU (patient assuré AMU, acte
    pris en charge AMU) — sans ça, par exemple un patient non assuré payant
    cash une chambre 15 jours n'a aucune ambiguïté de PBR à régler, le prix
    clinique restant constant quel que soit le palier."""
    if not (nom and 'P160' in nom):
        return None
    if not quantite or quantite <= JOURS_MAX_SANS_PALIER:
        return None
    if not (prise_en_charge_amu and est_assure_amu):
        return None
    return (
        f"\"{nom}\" est un tarif d'hospitalisation (P160) vendu ici avec {quantite} jours. "
        f"Au-delà de {JOURS_MAX_SANS_PALIER} jours, le remboursement AMU doit être calculé par palier "
        f"dégressif (1ère semaine / 8e-14e jour / 15e jour et plus) — utilisez le module Hospitalisation "
        f"pour ce séjour, pas la vente directe d'actes."
    )


def pbr_officiel_p160(niveau, categorie_salle, palier):
    """Base de remboursement officielle AMU pour un palier (1/2/3) d'une
    catégorie de salle, au niveau de soins donné. None si niveau/catégorie
    absents de la grille (niveau 1 non couvert, ou salle_commune_10_12 au
    niveau 2) — à charge de l'appelant de se replier sur l'ancien
    comportement (détection par nom dans le catalogue Sheets)."""
    return GRILLE_AMU_HOSPITALISATION.get(str(niveau), {}).get(categorie_salle, {}).get(palier)


def acte_virtuel_o101():
    """Acte O101 (Oxygénothérapie) — même forme brute qu'une ligne du
    catalogue Google Sheets (clés attendues par api_get_actes/page_actes_vente),
    pour être injecté tel quel dans la liste d'actes de CHAQUE structure sans
    toucher à leurs feuilles Sheets. Tarif unique (pas de palier, pas de
    dépendance au niveau de soins), remboursé directement (pas d'EP)."""
    return {
        'ID': 'O101',
        'nom': 'O101 - Oxygénothérapie',
        'code': 'O101',
        'prix': 5000,
        'pbr': 5000,
        'statut': 'DIRECT',
        'prise_en_charge_amu': True,
        'prise_en_charge_cac': True,
        'prise_en_charge_amu_tns': True,
        'description': '5000 FCFA par jour, quelle que soit la structure — remboursé à 100% par l\'AMU',
    }
