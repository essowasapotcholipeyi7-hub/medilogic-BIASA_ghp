# -*- coding: utf-8 -*-
"""Logique du module Hospitalisation : détection des groupes de paliers
tarifaires (1ère semaine / 8e-14e jour / 15e jour et +) et répartition
automatique du nombre de jours facturés sur ces paliers.

Ces paliers existent déjà, ligne par ligne, dans le catalogue d'actes de
chaque structure (feuille Google Sheets struct_<id>_actes) — voir par
exemple structure 1 : "P160 Hospi Cabine climatisee avec 1 lit Premiere
Semaine" / "... 8e jour au 14e jour" / "... 15 jours et plus", prix
identique sur les 3 lignes (le prix clinique ne baisse pas), pbr dégressif
(la base de remboursement assurance, elle, baisse). Ce module ne modifie
rien au catalogue : il détecte le groupe par le nom, à la volée.
"""
import re
import unicodedata
from datetime import timedelta

# ⭐ Import différé (pas de circularité : models.py n'importe jamais ce
# module) — utilisé uniquement par charger_pbr_complementaires() ci-dessous.
from models import PbrComplementaire, PrixNonAssureActe
from services.tarification_service import repartir_ligne, pbr_prive_valeur
from utils.grille_amu_hospitalisation import pbr_officiel_p160, JOURS_MAX_SANS_PALIER

# Suffixe (normalisé) -> palier 1/2/3. Plusieurs variantes tolérées
# (accents/orthographe observés dans le catalogue réel).
_SUFFIXES_PALIER = {
    'premiere semaine': 1,
    '1ere semaine': 1,
    '8e jour au 14e jour': 2,
    '15 jours et plus': 3,
    '15 jour et plus': 3,
}

# Ordre du plus long au plus court, pour ne jamais couper un suffixe plus
# court qui serait contenu dans un plus long.
_SUFFIXES_TRIES = sorted(_SUFFIXES_PALIER.keys(), key=len, reverse=True)


def _normaliser(texte):
    """minuscule + accents retirés + espaces multiples réduits — tolère les
    incohérences de casse déjà observées dans le catalogue réel
    ("Climatisee" vs "climatisee")."""
    if not texte:
        return ''
    texte = unicodedata.normalize('NFKD', str(texte)).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(texte.lower().split())


def _decouper_suffixe(nom_normalise):
    """Si nom_normalise se termine par un suffixe de palier connu, retourne
    (prefixe, palier) ; sinon (nom_normalise, None)."""
    for suffixe in _SUFFIXES_TRIES:
        if nom_normalise.endswith(suffixe):
            prefixe = nom_normalise[: -len(suffixe)].strip()
            return prefixe, _SUFFIXES_PALIER[suffixe]
    return nom_normalise, None


def detecter_groupe_palier(nom_acte, tous_les_actes):
    """Si `nom_acte` porte un suffixe de palier connu, cherche ses actes
    sœurs (même préfixe, autres suffixes) parmi `tous_les_actes` (liste de
    dicts avec au moins 'nom', déjà chargée via /api/actes).

    Retourne {1: acte|None, 2: acte|None, 3: acte|None} si au moins 2
    paliers sont trouvés (un seul palier isolé n'est pas un "groupe" —
    comportement inchangé), sinon None."""
    prefixe, palier = _decouper_suffixe(_normaliser(nom_acte))
    if palier is None:
        return None

    groupe = {}
    for acte in tous_les_actes:
        p2, pal2 = _decouper_suffixe(_normaliser(acte.get('nom')))
        if pal2 is not None and p2 == prefixe:
            groupe[pal2] = acte

    if len(groupe) < 2:
        return None
    for p in (1, 2, 3):
        groupe.setdefault(p, None)
    return groupe


def nom_sans_palier(nom):
    """Retire un suffixe de palier hebdomadaire (ex. "Premiere Semaine") du
    nom d'un acte chambre — utilisé quand aucune répartition par palier ne
    s'applique réellement (patient non assuré AMU) : garder ce suffixe sur
    la facture/le reçu d'un patient qui paie cash n'a pas de sens et prête à
    confusion (signalé). Les suffixes connus sont en ASCII pur (aucun
    n'utilise d'accent), donc une simple recherche insensible à la casse
    suffit — pas besoin de _normaliser()/repositionnement d'index."""
    if not nom:
        return nom
    for suffixe in _SUFFIXES_TRIES:
        motif = re.compile(re.escape(suffixe) + r'\s*$', re.IGNORECASE)
        if motif.search(nom):
            return motif.sub('', nom).strip(' -').strip()
    return nom


def repartir_jours(nb_jours):
    """16 jours -> [(1, 7), (2, 7), (3, 2)]. Tranches à 0 jour omises."""
    nb_jours = max(int(nb_jours or 0), 0)
    tranches = [
        (1, min(nb_jours, 7)),
        (2, min(max(nb_jours - 7, 0), 7)),
        (3, max(nb_jours - 14, 0)),
    ]
    return [(palier, jours) for palier, jours in tranches if jours > 0]


def _lignes_palier_depuis_grille(acte_choisi, nb_jours, date_entree, niveau_soins, categorie_salle):
    """Construit les lignes par palier à partir de la grille officielle AMU
    (utils/grille_amu_hospitalisation.py) au lieu de deviner par le nom dans
    le catalogue Sheets de la structure — prix clinique CONSTANT sur les 3
    paliers (celui d'`acte_choisi`, comme déjà le cas avec l'ancien
    mécanisme), seul le PBR change par palier. Retourne None si la grille
    n'a pas ce niveau/cette catégorie (niveau 1 non couvert, ou
    salle_commune_10_12 au niveau 2) — l'appelant se replie alors sur
    l'ancien mécanisme (détection par nom)."""
    prix = float(acte_choisi.get('prix') or 0)
    lignes = []
    curseur = date_entree
    for palier, jours in repartir_jours(nb_jours):
        pbr = pbr_officiel_p160(niveau_soins, categorie_salle, palier)
        if pbr is None:
            return None
        lignes.append({
            'nom': acte_choisi.get('nom'),
            'reference_id': acte_choisi.get('id') or acte_choisi.get('ID'),
            'prix': prix,
            'pbr': float(pbr),
            'quantite': jours,
            'date_prestation': curseur,
            'date_fin_prestation': curseur + timedelta(days=jours - 1),
        })
        curseur = curseur + timedelta(days=jours)
    return lignes


def construire_lignes_chambre(acte_choisi, nb_jours, date_entree, tous_les_actes, patient_assure,
                               niveau_soins=None, categorie_salle=None):
    """Construit les lignes SoinHospitalisation (sous forme de dicts prêts
    à insérer) pour un acte "chambre" avec `nb_jours` jours facturés.

    - Patient non assuré, séjour <= 7 jours -> une seule ligne, au prix de
      `acte_choisi`.
    - Sinon, si `niveau_soins` et `categorie_salle` sont fournis (voir
      CorrespondanceSalleAmu, models.py) -> jusqu'à 3 lignes dont le PBR
      vient de la grille officielle AMU (prix clinique inchangé).
    - Sinon, si un groupe de paliers est détecté par nom dans le catalogue
      de la structure -> jusqu'à 3 lignes, prix/pbr pris sur l'acte sœur du
      palier correspondant (ancien mécanisme, inchangé).
    - Sinon -> une seule ligne, au prix de `acte_choisi`.
    Chaque ligne par palier est datée sur sa propre période
    (date_prestation -> date_fin_prestation)."""
    lignes_grille = None
    groupe = None
    if patient_assure and nb_jours > JOURS_MAX_SANS_PALIER:
        if niveau_soins and categorie_salle:
            lignes_grille = _lignes_palier_depuis_grille(
                acte_choisi, nb_jours, date_entree, niveau_soins, categorie_salle
            )
        if lignes_grille is None:
            groupe = detecter_groupe_palier(acte_choisi.get('nom'), tous_les_actes)

    if lignes_grille is not None:
        return lignes_grille

    if not groupe:
        # ⭐ Pas de répartition réelle par palier ici : si le patient n'est
        # pas assuré AMU, un nom d'acte se terminant par "Premiere Semaine"
        # (ou une autre variante) induirait en erreur sur un reçu qui n'a
        # rien à voir avec l'assurance — on le retire. Gardé tel quel pour
        # un patient assuré sur un court séjour (<=7 jours) : la mention
        # reste exacte et utile pour son propre bordereau d'assurance.
        nom_ligne = acte_choisi.get('nom')
        if not patient_assure:
            nom_ligne = nom_sans_palier(nom_ligne)
        return [{
            'nom': nom_ligne,
            'reference_id': acte_choisi.get('id') or acte_choisi.get('ID'),
            'prix': float(acte_choisi.get('prix') or 0),
            'pbr': float(acte_choisi.get('pbr') or acte_choisi.get('prix') or 0),
            'quantite': nb_jours,
            'date_prestation': date_entree,
            'date_fin_prestation': date_entree + timedelta(days=max(nb_jours - 1, 0)),
        }]

    lignes = []
    curseur = date_entree
    for palier, jours in repartir_jours(nb_jours):
        acte_palier = groupe.get(palier) or acte_choisi
        lignes.append({
            'nom': acte_palier.get('nom'),
            'reference_id': acte_palier.get('id') or acte_palier.get('ID'),
            'prix': float(acte_palier.get('prix') or 0),
            'pbr': float(acte_palier.get('pbr') or acte_palier.get('prix') or 0),
            'quantite': jours,
            'date_prestation': curseur,
            'date_fin_prestation': curseur + timedelta(days=jours - 1),
        })
        curseur = curseur + timedelta(days=jours)

    return lignes


def _taux_amu_article(nom, taux_defaut):
    """Même règle que taux_amu_pour_article() (app.py) et
    tauxAMUPourArticle() (JS, actes_vente.html/pharma_vente.html/
    proformas.html) — dupliquée ici plutôt qu'importée d'app.py pour éviter
    un import circulaire (app.py importe déjà ce module). O101
    (oxygénothérapie) remboursé à 100% quel que soit le taux général — voir
    utils/grille_amu_hospitalisation.py."""
    if nom and 'O101' in nom:
        return 100
    return 90 if (nom and 'P160' in nom) else taux_defaut


def charger_pbr_complementaires(structure_id, compagnie):
    """{nom_acte: {'pbr_1':.., 'pbr_2': .. ou None}} pour CETTE structure et
    CETTE compagnie complémentaire précisément (ex. "SUNU") — contrairement
    à l'AMU, chaque compagnie a sa propre base de remboursement sur un même
    acte, d'où la table PbrComplementaire (models.py) plutôt qu'une colonne
    de plus dans le catalogue. pbr_1 = celui qu'on applique d'habitude
    (utilisé par défaut), pbr_2 = un alternatif optionnel, pour un contrat
    de ce patient qui diffère de l'habitude (voir pbr_cac_variante_valeur
    ci-dessous). Vide si `compagnie` est vide/absente ou si aucune entrée
    n'a encore été saisie pour elle -> calculer_repartition_assurance()
    retombe alors naturellement sur le comportement d'avant (reste après
    AMU, non plafonné), donc zéro régression tant que rien n'est saisi."""
    if not compagnie:
        return {}
    lignes = PbrComplementaire.query.filter_by(
        structure_id=structure_id, compagnie=compagnie
    ).all()
    return {
        l.nom_acte: {
            # ⭐ pbr_1 None = pas de PBR pour ce couple (tarif privé seul) ;
            # tarif_prive None = prix de base — voir services/tarification_service.py.
            'pbr_1': float(l.pbr_1) if l.pbr_1 is not None else None,
            'pbr_2': float(l.pbr_2) if l.pbr_2 is not None else None,
            'tarif_prive': float(l.tarif_prive) if l.tarif_prive is not None else None,
        }
        for l in lignes
    }


def charger_prix_non_assure(structure_id):
    """{nom_acte: prix non assuré} pour cette structure (voir
    PrixNonAssureActe, models.py) — vide tant que rien n'est renseigné :
    les patients non assurés paient alors le prix de base (cas 1,
    "ou prix AMU si non défini")."""
    return {
        l.nom_acte: float(l.prix)
        for l in PrixNonAssureActe.query.filter_by(structure_id=structure_id).all()
        if l.prix is not None
    }


def enregistrer_prix_non_assure(structure_id, nom_acte, prix, ancien_nom=None, user_nom=None):
    """Pose / met à jour / retire (prix vide) le prix non assuré d'un acte —
    appelé par l'admin des actes (api_add_acte / api_delete_acte, app.py)
    en même temps que l'écriture Google Sheets. `ancien_nom` : l'acte a été
    renommé, l'entrée suit le nouveau nom. Ne commit pas : l'appelant le
    fait (ou pas) avec le reste."""
    from models import db
    nom_acte = (nom_acte or '').strip()
    if not nom_acte:
        return
    cles = [nom_acte] + ([ancien_nom.strip()] if ancien_nom and ancien_nom.strip() != nom_acte else [])
    lignes = PrixNonAssureActe.query.filter(
        PrixNonAssureActe.structure_id == structure_id, PrixNonAssureActe.nom_acte.in_(cles)
    ).all()
    if prix is None or prix == '' or float(prix) <= 0:
        for l in lignes:
            db.session.delete(l)
        return
    prix = float(prix)
    if lignes:
        ligne = lignes[0]
        ligne.nom_acte = nom_acte
        ligne.prix = prix
        for doublon in lignes[1:]:
            db.session.delete(doublon)
    else:
        db.session.add(PrixNonAssureActe(structure_id=structure_id, nom_acte=nom_acte, prix=prix, created_by=user_nom))


def pbr_cac_variante_valeur(entree, variante):
    """Choisit pbr_1 (défaut/habituel) ou pbr_2 (alternatif) dans une entrée
    de charger_pbr_complementaires() ci-dessus, selon `variante`
    ('defaut'|'alternatif' — voir Hospitalisation/Proforma.pbr_cac_variante).
    Se replie sur pbr_1 si l'alternatif est demandé mais absent pour cet
    acte (toutes les compagnies n'ont pas forcément un second tarif)."""
    # ⭐ Peut renvoyer None depuis 2026-10-04 (entrée "tarif privé sans PBR") —
    # voir services/tarification_service.pbr_prive_valeur.
    return pbr_prive_valeur(entree, variante)


def calculer_repartition_assurance(soins, hospit, pbr_cac_par_acte=None, pbr_cac_variante='defaut'):
    """Part AMU / part CAC / part patient pour une liste de soins (objets
    SoinHospitalisation ou équivalents avec .nom/.prix/.pbr/.quantite/
    .prise_en_charge_amu/.prise_en_charge_cac) et un séjour `hospit`
    (Hospitalisation — utilise ses propriétés "effectives", qui respectent
    le toggle assurance_principale_active/assurance2_active de CE séjour).

    `pbr_cac_par_acte` (optionnel, voir charger_pbr_complementaires ci-
    dessus) : {nom_acte: {'pbr_1':.., 'pbr_2':..}} propre à la compagnie
    complémentaire du patient — plafonne la base CAC de chaque article qui
    y figure, comme l'AMU le fait déjà avec son propre PBR. `pbr_cac_variante`
    choisit pbr_1 (défaut) ou pbr_2 (alternatif, voir pbr_cac_variante_valeur
    ci-dessus). Absent ou vide (par défaut) : comportement inchangé (reste
    après AMU, non plafonné).

    Même formule que celle utilisée à la facturation finale
    (api_facturer_hospitalisation, app.py) — un seul endroit pour ce
    calcul, réutilisé aussi pour l'aperçu "en cours" affiché pendant le
    séjour, pour que les deux restent toujours cohérents."""
    pbr_cac_par_acte = pbr_cac_par_acte or {}
    est_assure = hospit.est_assure_amu
    taux_assurance = hospit.taux_assurance_effectif
    a_cac = hospit.a_cac
    taux_assurance2 = hospit.taux_assurance2_effectif

    # ⭐ Règles centralisées (patron, 2026-10-04) : voir
    # services/tarification_service.py. Ici le prix de chaque soin est celui
    # déjà enregistré au séjour (jamais remplacé par un tarif privé après
    # coup : appliquer_tarif_prive=False), seules les parts AMU / privée /
    # patient en découlent.
    contexte = {
        'amu': bool(est_assure), 'taux_amu': taux_assurance,
        'privee': bool(a_cac), 'taux_privee': taux_assurance2,
        'pbr_prive_par_acte': pbr_cac_par_acte, 'variante': pbr_cac_variante,
        'appliquer_tarif_prive': False,
    }
    sous_total = part_amu = part_cac = 0.0
    for s in soins:
        ligne = repartir_ligne({
            'nom': s.nom, 'prix': float(s.prix or 0), 'pbr': float(s.pbr or 0),
            'quantite': int(s.quantite or 0),
            'prise_en_charge_amu': bool(s.prise_en_charge_amu),
            'prise_en_charge_cac': bool(s.prise_en_charge_cac),
        }, contexte)
        sous_total += ligne['total']
        part_amu += ligne['part_amu']
        part_cac += ligne['part_privee']
    part_patient = max(sous_total - part_amu - part_cac, 0.0)

    return {
        'sous_total': sous_total,
        'part_amu': part_amu,
        'part_cac': part_cac,
        'part_patient': part_patient,
        'est_assure_amu': est_assure,
        'a_cac': a_cac,
    }
