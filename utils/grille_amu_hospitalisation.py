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
# ⭐ "Salle commune 7 à 9 lits / 15 jours et plus" : 625 pour le CHR mais
# 375 pour l'hôpital de district — confirmé exact par le patron
# (2026-10-19) : voir EXCEPTIONS_TYPE_PRESTATAIRE (type de prestataire
# réglé dans Paramètres AMU).
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


# ⭐ 2026-10-19 : type de prestataire (Paramètres AMU) -> niveau de la grille. Pas de niveau 1 : les unités
# de soins périphériques n'hospitalisent pas.
TYPES_PRESTATAIRE = [
    ('chu', 'CHU', '3'),
    ('clinique_privee', 'Clinique privée', '3'),
    ('chr', 'CHR', '2'),
    ('hopital_district', 'Hôpital de district (CHP)', '2'),
    ('cabinet_prive', 'Cabinet privé', '2'),
]
NIVEAU_PAR_TYPE = {cle: niveau for cle, _, niveau in TYPES_PRESTATAIRE}

# Seuls écarts du fichier officiel entre prestataires d'un même niveau.
EXCEPTIONS_TYPE_PRESTATAIRE = {
    'hopital_district': {'salle_commune_7_9': {3: 375}},
}


def pbr_amu_chambre(niveau, categorie_salle, palier, type_prestataire=None, prix_clinique=None):
    """⭐ 2026-10-19 (patron) : PBR AMU d'un palier de chambre = tarif de la grille (niveau, et type de
    prestataire pour ses exceptions), RAMENÉ AU PRIX CLINIQUE quand celui-ci est plus bas (« si le prix de
    la clinique, par exemple 4 000, est inférieur à 5 000, on ramène 5 000 à 4 000 »). None si la grille
    n'a pas cette salle à ce niveau."""
    niveau = str(niveau or NIVEAU_PAR_TYPE.get(type_prestataire) or '')
    pbr = (EXCEPTIONS_TYPE_PRESTATAIRE.get(type_prestataire) or {}).get(categorie_salle, {}).get(palier)
    if pbr is None:
        pbr = pbr_officiel_p160(niveau, categorie_salle, palier)
    if pbr is None:
        return None
    try:
        prix = float(prix_clinique or 0)
    except (TypeError, ValueError):
        prix = 0
    return min(pbr, prix) if prix > 0 else pbr


def deviner_niveau(categorie_salle, pbr_premiere_semaine):
    """Niveau ('3' CHU/clinique privée, '2' CHR/district/cabinet privé) dont le tarif « Première semaine »
    de cette salle vaut `pbr_premiere_semaine` — secours quand le niveau de la structure n'est pas réglé
    (Paramètres AMU)."""
    try:
        pbr = float(pbr_premiere_semaine or 0)
    except (TypeError, ValueError):
        return None
    for niveau, salles in GRILLE_AMU_HOSPITALISATION.items():
        if (salles.get(categorie_salle) or {}).get(1) == pbr:
            return niveau
    return None


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


def deduire_categorie_salle(nom):
    """⭐ 2026-10-19 : catégorie AMU d'un tarif de chambre déduite de son NOM quand elle n'a pas été
    renseignée (séjour du 19/10 bloqué à la conversion : « Cabine ventilée avec 2 lits » sur 18 jours,
    sans catégorie, donc sans dégressivité par palier). None si le nom ne dit rien de sûr.
      observation / mise en observation -> 'observation' ; réanimation -> 'reanimation' ;
      cabine, chambre individuelle, 1 ou 2 lits -> 'cabine' ; 3 à 6 lits -> salle commune 3-6 ;
      7 à 9 -> 7-9 ; 10 à 12 -> 10-12."""
    import re
    import unicodedata
    t = unicodedata.normalize('NFD', str(nom or '')).encode('ascii', 'ignore').decode().lower()
    if not t:
        return None
    if 'observation' in t or re.search(r'meo', t):
        return 'observation'
    if 'reanimation' in t:
        return 'reanimation'
    m = re.search(r'(\d+)\s*(?:a|-|à)\s*(\d+)\s*lits?', t) or re.search(r'(\d+)\s*lits?', t)
    nb = int(m.group(m.lastindex)) if m else None
    if nb is not None:
        if nb <= 2:
            return 'cabine'
        if nb <= 6:
            return 'salle_commune_3_6'
        if nb <= 9:
            return 'salle_commune_7_9'
        return 'salle_commune_10_12'
    if 'salle commune' in t:
        return None   # nombre de lits inconnu
    if 'cabine' in t or 'individuelle' in t or 'vip' in t or 'chambre' in t:
        return 'cabine'
    return None


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
