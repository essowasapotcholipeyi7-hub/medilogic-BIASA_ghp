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
from services.tarification_service import repartir_ligne, pbr_prive_valeur, objets_doublons_amu
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
    from services.tarification_service import taux_amu_article   # ⭐ 2026-10-16 : une seule règle
    return taux_amu_article(nom, taux_defaut)


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
    return _lire_tarifs_compagnies(structure_id, [compagnie]).get(compagnie, {})


def _f(v):
    return float(v) if v is not None else None


def _lire_tarifs_compagnies(structure_id, compagnies):
    """{compagnie: {nom_acte: {pbr_1, pbr_2, tarif_prive, tarif_nuit, pbr_nuit}}} en UNE requête.
    to_jsonb : les colonnes de nuit (tarif_nuit / pbr_nuit, 2026-10-19) sont lues si la table les a,
    absentes sinon — le code marche avant comme après la migration."""
    from models import db
    from sqlalchemy import text
    resultat = {c: {} for c in compagnies}
    lignes = db.session.execute(text(
        "SELECT to_jsonb(p) AS j FROM pbr_complementaires p WHERE structure_id = :s AND compagnie = ANY(:c)"),
        {'s': structure_id, 'c': list(compagnies)}).fetchall()
    for (j,) in lignes:
        # ⭐ pbr_1 None = pas de PBR pour ce couple (tarif privé seul) ;
        # tarif_prive None = prix de base — voir services/tarification_service.py.
        resultat.setdefault(j['compagnie'], {})[j['nom_acte']] = {
            'pbr_1': _f(j.get('pbr_1')), 'pbr_2': _f(j.get('pbr_2')), 'tarif_prive': _f(j.get('tarif_prive')),
            'tarif_nuit': _f(j.get('tarif_nuit')), 'pbr_nuit': _f(j.get('pbr_nuit')),
        }
    return resultat


# ⭐ Listes de prix (patron, 2026-10-19, Clinique Valeo) : des « compagnies » dont le nom commence par
# « Liste » (ex. « Liste Expatriés », « Liste SMA 25 % », « Liste SMA 20 % ») portent un tarif par acte
# choisi À LA VENTE pour un patient donné, au lieu du tarif de sa compagnie. Une liste en plusieurs
# pourcentages (SMA : réduction de 20 % ou 25 %) est une liste « remise » : le patient paie le tarif ;
# pour la biologie le pourcentage doit être choisi à chaque ligne, ailleurs le plus grand s'applique.
PREFIXE_LISTE = 'Liste '
_RE_LISTE = re.compile(r'^(Liste .+?)(?:\s+(\d+(?:[.,]\d+)?)\s*%)?\s*$')


def listes_tarifs(structure_id):
    """[{groupe, libelle, remise, variantes: [{cle, pct}], defaut}] — vide pour une structure sans liste."""
    from models import db
    from sqlalchemy import text
    noms = [r[0] for r in db.session.execute(text(
        "SELECT DISTINCT compagnie FROM pbr_complementaires WHERE structure_id = :s AND compagnie LIKE 'Liste %'"),
        {'s': structure_id}).fetchall()]
    groupes = {}
    for nom in sorted(noms):
        m = _RE_LISTE.match(nom)
        if not m:
            continue
        g = groupes.setdefault(m.group(1), {'groupe': m.group(1), 'libelle': m.group(1)[len(PREFIXE_LISTE):], 'variantes': []})
        g['variantes'].append({'cle': nom, 'pct': float(m.group(2).replace(',', '.')) if m.group(2) else None})
    resultat = []
    for g in groupes.values():
        g['variantes'].sort(key=lambda v: -(v['pct'] or 0))
        g['remise'] = all(v['pct'] is not None for v in g['variantes'])
        g['defaut'] = g['variantes'][0]['cle']
        resultat.append(g)
    return resultat


def charger_listes(structure_id, cles):
    """{cle_liste: {nom_acte: {...}}} pour les listes demandées (seulement des noms « Liste … »)."""
    cles = [c for c in (cles or []) if c and str(c).startswith(PREFIXE_LISTE)]
    return _lire_tarifs_compagnies(structure_id, cles) if cles else {}


def appliquer_liste_tarif(structure_id, groupe_nom, articles, contexte, taux_complementaire, privee_patient):
    """Pose la liste choisie (ex. « Liste SMA ») sur les lignes et sur le contexte de tarification ;
    renvoie le groupe, ou None (grande liste). Sans `groupe_nom`, le groupe est retrouvé d'après les
    lignes (proforma déjà enregistrée). Liste « remise » (SMA) : aucune part privée ; sinon la part de
    l'assurance du patient (taux de sa carte) se calcule sur le tarif de la liste."""
    groupes = listes_tarifs(structure_id) if (groupe_nom or any(a.get('liste_tarif') for a in articles)) else []
    groupe = None
    if groupe_nom:
        groupe = next((g for g in groupes if g['groupe'] == groupe_nom), None)
    else:
        cles_lignes = {a.get('liste_tarif') for a in articles if a.get('liste_tarif')}
        groupe = next((g for g in groupes if cles_lignes & {v['cle'] for v in g['variantes']}), None)
    if not groupe:
        for a in articles:
            a.pop('liste_tarif', None)
        return None
    cles = [v['cle'] for v in groupe['variantes']]
    for a in articles:
        if a.get('liste_tarif') not in cles:
            a['liste_tarif'] = groupe['defaut']
    contexte['listes'] = charger_listes(structure_id, cles)
    contexte['privee_patient'] = bool(privee_patient)
    contexte['privee'] = True
    # taux réel du patient : une ligne de la liste « remise » n'a pas de part privée (ligne_remise), une
    # ligne absente de la liste reste couverte par l'assurance réelle du patient
    contexte['taux_privee'] = taux_complementaire if privee_patient else 0
    contexte['listes_remise'] = set(cles) if groupe['remise'] else set()
    return groupe


def type_sejour(sejour):
    """'hospitalisation' | 'ambulatoire' (épisode de soins ambulatoires)."""
    return 'hospitalisation' if sejour.__class__.__name__ == 'Hospitalisation' else 'ambulatoire'


def liste_choisie_sejour(structure_id, type_s, sejour_id):
    """(liste, {id_ligne: variante}) choisis pour ce séjour (table listes_tarif_sejour,
    migrate_tarifs_listes_nuit.py) ; rien de choisi / table absente -> (None, {})."""
    from models import db
    from sqlalchemy import text
    try:
        with db.session.begin_nested():
            r = db.session.execute(text(
                "SELECT liste_tarif, variantes FROM listes_tarif_sejour WHERE structure_id = :s AND type_sejour = :t AND sejour_id = :i"),
                {'s': structure_id, 't': type_s, 'i': sejour_id}).fetchone()
        if r and r[0]:
            return r[0], dict(r[1] or {})
    except Exception:
        pass
    return None, {}


def contexte_tarif_sejour(sejour, pbr_cac_par_acte=None, variante='defaut'):
    """⭐ 2026-10-19 (patron : « corrige aussi pour l'hospitalisation ») : un séjour (hospitalisation ou
    soins ambulatoires) suit la grande liste comme la vente d'actes — tarif de la compagnie privée du
    patient, prix non assuré pour un non assuré — et la liste choisie pour ce séjour (Valeo : SMA,
    Expatriés). Avant, tout était facturé au prix clinique AMU. Gardé sur le séjour pour la page."""
    cle_memo = (variante, id(pbr_cac_par_acte))
    memo = getattr(sejour, '_tarif_sejour', None)
    if memo and memo[0] == cle_memo:
        return memo[1]
    sid = sejour.structure_id
    taux2 = float(sejour.taux_assurance2_effectif or 0)
    privee = bool(sejour.a_cac and taux2 > 0)
    contexte = {'amu': bool(sejour.est_assure_amu), 'taux_amu': sejour.taux_assurance_effectif,
                'privee': privee, 'taux_privee': taux2, 'pbr_prive_par_acte': pbr_cac_par_acte or {},
                'variante': variante or 'defaut'}
    nom_liste, variantes = liste_choisie_sejour(sid, type_sejour(sejour), sejour.id)
    groupe = appliquer_liste_tarif(sid, nom_liste, [], contexte, taux2, privee) if nom_liste else None
    info = {'contexte': contexte, 'groupe': groupe, 'variantes': variantes,
            'na': {'acte': charger_prix_non_assure(sid, 'acte'), 'produit': charger_prix_non_assure(sid, 'produit')}}
    try:
        sejour._tarif_sejour = (cle_memo, info)
    except AttributeError:
        pass
    return info


def article_tarif_soin(soin, info, pbr, prise_amu):
    """Ligne pour repartir_ligne() : soin du séjour + prix non assuré + variante de la liste choisie."""
    type_art = 'produit' if getattr(soin, 'type', '') == 'medicament' else 'acte'
    article = {'nom': soin.nom, 'prix': float(soin.prix or 0), 'pbr': pbr, 'quantite': int(soin.quantite or 0),
               'prise_en_charge_amu': prise_amu, 'prise_en_charge_cac': bool(soin.prise_en_charge_cac),
               'prix_non_assure': info['na'][type_art].get(soin.nom)}
    if info['groupe']:
        article['liste_tarif'] = info['variantes'].get(str(getattr(soin, 'id', ''))) or info['groupe']['defaut']
    return article


def soins_a_taux_liste(soins, info):
    """Lignes dont le prix change selon le taux de la liste « remise » choisie (SMA 20 / 25 % : la biologie)
    — le taux y est obligatoire. [(soin, variante choisie ou None)]."""
    g = info['groupe']
    if not g or not g['remise'] or len(g['variantes']) < 2:
        return []
    listes = info['contexte'].get('listes', {})
    resultat = []
    for soin in soins:
        prix = {((listes.get(v['cle']) or {}).get(soin.nom) or {}).get('tarif_prive') for v in g['variantes']}
        if len(prix) > 1:
            resultat.append((soin, info['variantes'].get(str(getattr(soin, 'id', '')))))
    return resultat


def lignes_sans_taux_liste(structure_id, articles, groupe_nom):
    """Noms des lignes d'une liste « remise » en plusieurs taux (SMA 20 / 25 %) dont le prix change selon le
    taux et dont le taux n'a pas été choisi — le serveur refuse la vente (l'écran le demande déjà)."""
    groupe = next((g for g in listes_tarifs(structure_id) if g['groupe'] == groupe_nom), None) if groupe_nom else None
    if not groupe or not groupe['remise'] or len(groupe['variantes']) < 2:
        return []
    cles = [v['cle'] for v in groupe['variantes']]
    listes = charger_listes(structure_id, cles)
    manquants = []
    for a in articles:
        if a.get('liste_tarif') in cles:
            continue
        prix = {((listes.get(c) or {}).get(a.get('nom')) or {}).get('tarif_prive') for c in cles}
        if len(prix) > 1:
            manquants.append(a.get('nom'))
    return manquants


def pas_arrondi_structure(structure_id):
    """Pas d'arrondi de la part patient réglé pour la structure (ex. 50 FCFA), 0 = pas d'arrondi.
    Table parametrage_tarification (migrate_tarifs_listes_nuit.py) ; absente = 0."""
    from models import db
    from sqlalchemy import text
    try:
        with db.session.begin_nested():
            r = db.session.execute(text("SELECT arrondi_pas FROM parametrage_tarification WHERE structure_id = :s"),
                                   {'s': structure_id}).fetchone()
        return float(r[0]) if r and r[0] else 0.0
    except Exception:
        return 0.0


def charger_prix_non_assure(structure_id, type_article='acte'):
    """{nom: prix non assuré} pour cette structure et ce catalogue ('acte' ou
    'produit', voir PrixNonAssureActe, models.py) — vide tant que rien n'est
    renseigné : les patients non assurés paient alors le prix de base
    (cas 1, "ou prix AMU si non défini")."""
    # ⭐ 2026-10-18 : actes ET produits lus en une requête, gardés pour la page en cours (beaucoup de pages
    # demandent les deux)
    try:
        from flask import g, has_request_context
        memo = g.setdefault('_prix_non_assure', {}) if has_request_context() else None
    except Exception:
        memo = None
    if memo is not None and structure_id in memo:
        return dict(memo[structure_id].get(type_article, {}))
    par_type = _lire_prix_non_assure(structure_id)
    if memo is not None:
        memo[structure_id] = par_type
    return dict(par_type.get(type_article, {}))


def _lire_prix_non_assure(structure_id):
    """{type: {nom: prix}, 'nuit:<type>': {nom: prix de nuit}} — to_jsonb : prix_nuit lu s'il existe."""
    from models import db
    from sqlalchemy import text
    par_type = {}
    for (j,) in db.session.execute(text("SELECT to_jsonb(p) AS j FROM prix_non_assure_actes p WHERE structure_id = :s"),
                                   {'s': structure_id}).fetchall():
        if j.get('prix') is not None:
            par_type.setdefault(j.get('type') or 'acte', {})[j['nom_acte']] = float(j['prix'])
        if j.get('prix_nuit') is not None and float(j['prix_nuit']) > 0:
            par_type.setdefault('nuit:' + (j.get('type') or 'acte'), {})[j['nom_acte']] = float(j['prix_nuit'])
    return par_type


def charger_prix_non_assure_nuit(structure_id, type_article='acte'):
    """{nom: prix non assuré de NUIT} (nuit / dimanche / férié) — vide si rien n'est renseigné."""
    charger_prix_non_assure(structure_id, type_article)   # remplit le mémo de la page
    try:
        from flask import g, has_request_context
        if has_request_context() and structure_id in g.get('_prix_non_assure', {}):
            return dict(g._prix_non_assure[structure_id].get('nuit:' + type_article, {}))
    except Exception:
        pass
    return dict(_lire_prix_non_assure(structure_id).get('nuit:' + type_article, {}))


def enregistrer_prix_non_assure(structure_id, nom_acte, prix, ancien_nom=None, user_nom=None, type_article='acte'):
    """Pose / met à jour / retire (prix vide) le prix non assuré d'un acte —
    appelé par l'admin des actes (api_add_acte / api_delete_acte, app.py)
    en même temps que l'écriture Google Sheets. `ancien_nom` : l'acte a été
    renommé, l'entrée suit le nouveau nom. Ne commit pas : l'appelant le
    fait (ou pas) avec le reste."""
    from models import db
    nom_acte = (nom_acte or '').strip()
    if not nom_acte:
        return
    try:   # mémo de la page en cours (charger_prix_non_assure) : à relire après ce changement
        from flask import g, has_request_context
        if has_request_context():
            g.pop('_prix_non_assure', None)
    except Exception:
        pass
    cles = [nom_acte] + ([ancien_nom.strip()] if ancien_nom and ancien_nom.strip() != nom_acte else [])
    lignes = PrixNonAssureActe.query.filter(
        PrixNonAssureActe.structure_id == structure_id, PrixNonAssureActe.type == type_article,
        PrixNonAssureActe.nom_acte.in_(cles)
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
        db.session.add(PrixNonAssureActe(structure_id=structure_id, type=type_article, nom_acte=nom_acte, prix=prix, created_by=user_nom))


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
    est_assure = hospit.est_assure_amu
    a_cac = hospit.a_cac

    # ⭐ Règles centralisées (patron, 2026-10-04) : voir services/tarification_service.py.
    # ⭐ 2026-10-19 : grande liste (tarif de la compagnie / prix non assuré) et liste choisie pour le
    # séjour — voir contexte_tarif_sejour ; le tarif appliqué est posé sur chaque ligne (tarif_applique).
    info = contexte_tarif_sejour(hospit, pbr_cac_par_acte, pbr_cac_variante)
    contexte = info['contexte']
    sous_total = part_amu = part_cac = 0.0
    doublons_amu = objets_doublons_amu(soins)   # un seul acte par code AMU
    for s in soins:
        ligne = repartir_ligne(article_tarif_soin(
            s, info, float(s.pbr or 0), bool(s.prise_en_charge_amu) and id(s) not in doublons_amu), contexte)
        try:
            s.tarif_applique = ligne['tarif_unitaire']
            # ⭐ liste « remise » (SMA) : prix clinique (prix non assuré) d'où part la réduction, pour l'affichage
            g = info['groupe']
            if g and g['remise'] and ligne['source_tarif'] == 'prive':
                type_art = 'produit' if getattr(s, 'type', '') == 'medicament' else 'acte'
                reference = float(info['na'][type_art].get(s.nom) or s.prix or 0)
                if reference > ligne['tarif_unitaire']:
                    cle = info['variantes'].get(str(getattr(s, 'id', ''))) or g['defaut']
                    s.prix_reference_liste = reference
                    s.pct_liste = next((v['pct'] for v in g['variantes'] if v['cle'] == cle), None)
        except AttributeError:
            pass
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
