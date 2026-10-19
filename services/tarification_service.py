"""Tarification d'une ligne d'acte et répartition AMU / assurance privée /
patient — UN SEUL endroit pour les règles (patron, 2026-10-04 : "Vérification
de la logique de calcul des tarifs actes"), réutilisé par la vente d'actes
(recalcul serveur), le reçu, les proformas, l'hospitalisation et mis en
miroir en JS dans les paniers.

Règles (termes du patron) :
  Cas 1 — Non assuré        : tarif = prix non assuré (ou prix AMU si non
                              défini), le patient paie tout.
  Cas 2 — AMU seule         : tarif = prix AMU ; part AMU = taux AMU x PBR AMU.
  Cas 3 — Privée seule      : tarif = tarif privé ; part privée = taux privé x
                              PBR privé s'il existe, sinon taux privé x tarif.
  Cas 4 — AMU + privée      : tarif = tarif privé ; part AMU comme au cas 2 ;
                              part privée = taux privé x PBR privé s'il existe,
                              sinon taux privé x (tarif - part AMU).
  Patient = tarif - part AMU - part privée (jamais négatif).

⭐ Par LIGNE (patron, 2026-10-15) : une assurance décochée sur un article (refus,
patient qui n'est plus couvert…) ou non prise en charge au catalogue ne compte
plus pour cet article — il suit le cas des assurances qui restent : AMU seule
-> prix de base / PBR AMU ; aucune -> prix non assuré (cas 1).

Garde-fous conservés de l'existant : la base AMU est min(tarif, PBR AMU)
(un PBR officiel supérieur au tarif pratiqué ne fait pas rembourser plus
que le tarif) ; la part privée ne dépasse jamais ce qui reste après l'AMU.
Taux AMU par article : P160 (chambre) 90 %, O101 (oxygène) 100 %, S102 / S113
(consultation enfant 0-5 ans) 100 %, K233 (forfait césarienne) 100 % en structure
publique, sinon le taux du patient — voir utils/grille_amu_hospitalisation.py.
"""
import re

# ⭐ 2026-10-16 (patron) : consultation des enfants de 0 à 5 ans remboursée à 100 % du PBR AMU
CODES_ENFANT_0_5_ANS = ('S102', 'S113')
# forfait césarienne : 100 % seulement dans une structure PUBLIQUE (aide de l'État)
CODE_CESARIENNE_PUBLIQUE = 'K233'
_CODE_ACTE = re.compile(r'\s*([A-Z]\d{3})\b')


# ⭐ Un seul acte par code AMU dans une même vente (patron, 2026-10-17) : une clinique
# peut éclater un code AMU en plusieurs actes (ex. Q436 « Echo Doppler des vaisseaux
# quelle que soit la région » -> écho-doppler artériel / veineux / TSA / artério-veineux),
# mais l'AMU n'en prend en charge qu'UN par vente : les lignes suivantes du même code
# (sous un AUTRE nom) passent « non prises en charge AMU » — le patient ou son
# assurance complémentaire (taux / PBR privé) les couvrent. Le même acte sur deux lignes
# reste couvert (comme une quantité 2). Chambre (P160) et lunettes jamais concernées.
CODES_HORS_REGLE_UNIQUE = {'P160', 'D000293'}


def _vrai(valeur):
    return valeur if isinstance(valeur, bool) else str(valeur).upper() not in ('FALSE', '0', '', 'NONE')


def appliquer_code_amu_unique(articles):
    """Marque (sur place) les doublons de code AMU d'un panier : prise_en_charge_amu
    passe à False, amu_doublon=True, et la valeur d'origine est gardée dans
    prise_amu_origine — rejouable : un premier passage restaure tout avant de remarquer
    (retirer le premier acte d'une proforma rend sa prise en charge au suivant)."""
    from utils.categorisation import extraire_code_acte
    for a in articles or []:
        if isinstance(a, dict):
            if 'prise_amu_origine' in a:
                a['prise_en_charge_amu'] = a.pop('prise_amu_origine')
            a.pop('amu_doublon', None)
    vus = {}
    for a in articles or []:
        if not isinstance(a, dict) or not _vrai(a.get('prise_en_charge_amu', True)):
            continue
        code = extraire_code_acte(a.get('nom'))
        if not code or code in CODES_HORS_REGLE_UNIQUE:
            continue
        nom = str(a.get('nom') or '').strip()
        if code not in vus:
            vus[code] = nom
        elif vus[code] != nom:
            a['prise_amu_origine'] = a.get('prise_en_charge_amu', True)
            a['prise_en_charge_amu'] = False
            a['amu_doublon'] = True
    return articles


def objets_doublons_amu(lignes):
    """Même règle pour des lignes-objets (soins d'hospitalisation, soins ambulatoires :
    attributs .nom / .prise_en_charge_amu) — renvoie l'ensemble des id() des doublons."""
    articles = [{'nom': l.nom, 'prise_en_charge_amu': bool(l.prise_en_charge_amu), '_obj': id(l)} for l in lignes]
    appliquer_code_amu_unique(articles)
    return {a['_obj'] for a in articles if a.get('amu_doublon')}


def code_acte(nom):
    """'S102 Consultation en pediatrie…' -> 'S102' ; '' si le nom ne commence pas par un code."""
    m = _CODE_ACTE.match(nom or '')
    return m.group(1) if m else ''


def taux_amu_article(nom, taux_defaut, structure_publique=None):
    """Taux AMU de CET article. `structure_publique` : None = lu dans les paramètres AMU de la
    structure de la session (services/statut_structure.py)."""
    if nom and 'O101' in nom:
        return 100
    if nom and 'P160' in nom:
        return 90
    code = code_acte(nom)
    if _nombre(taux_defaut) > 0:   # seulement pour un patient AMU (jamais pour un non assuré)
        if code in CODES_ENFANT_0_5_ANS:
            return 100
        if code == CODE_CESARIENNE_PUBLIQUE:
            if structure_publique is None:
                from services.statut_structure import structure_est_publique
                structure_publique = structure_est_publique()
            if structure_publique:
                return 100
    return taux_defaut


def _nombre(valeur, defaut=0.0):
    try:
        if valeur is None or valeur == '':
            return defaut
        return float(valeur)
    except (TypeError, ValueError):
        return defaut


def pbr_prive_valeur(entree, variante='defaut', nuit=False):
    """PBR privé applicable (pbr_1 habituel / pbr_2 alternatif) ou None si
    l'entrée n'a pas de PBR (tarif privé seul, "présence ou non d'un PBR").
    `nuit` : ligne vendue la nuit / un dimanche / un férié — PBR de nuit s'il existe."""
    if not entree:
        return None
    if nuit and _nombre(entree.get('pbr_nuit')) > 0 and variante != 'alternatif':
        return _nombre(entree.get('pbr_nuit'))
    if variante == 'alternatif' and entree.get('pbr_2') is not None:
        return _nombre(entree.get('pbr_2'))
    pbr_1 = entree.get('pbr_1')
    if pbr_1 is None or pbr_1 == '':
        return None
    valeur = _nombre(pbr_1)
    return valeur if valeur > 0 else None


def _pris(valeur):
    """Prise en charge d'une ligne : absente = oui ; False / 'FALSE' = non."""
    if valeur is None or valeur == '':
        return True
    return valeur if isinstance(valeur, bool) else str(valeur).strip().upper() != 'FALSE'


def entree_privee(article, contexte):
    """Tarif / PBR privé de CETTE ligne. ⭐ Listes de prix (Clinique Valeo, patron 2026-10-19 :
    « liste SMA et liste des expatriés ») : une ligne qui porte `liste_tarif` (ex. 'Liste SMA 20 %')
    prend le tarif de cette liste ; sinon le tarif de la compagnie complémentaire du patient."""
    nom = article.get('nom')
    cle = article.get('liste_tarif')
    if cle and contexte.get('listes'):
        entree = (contexte['listes'].get(cle) or {}).get(nom)
        if entree is not None or not contexte.get('privee_patient'):
            return entree
    return (contexte.get('pbr_prive_par_acte') or {}).get(nom)


def privee_ligne(article, contexte):
    """L'assurance privée (ou la liste choisie) prend-elle cette ligne ? Une ligne absente de la liste
    choisie (médicament, acte sans tarif dans la liste) suit l'assurance RÉELLE du patient : sans
    assurance privée, elle est au prix non assuré comme pour tout patient non assuré."""
    if not _pris(article.get('prise_en_charge_cac')):
        return False
    cle = article.get('liste_tarif')
    if cle and contexte.get('listes'):
        if ((contexte['listes'].get(cle) or {}).get(article.get('nom'))) is not None:
            return True
        return bool(contexte.get('privee_patient'))
    return bool(contexte.get('privee'))


def ligne_remise(article, contexte):
    """Ligne tarifée par une liste « remise » (SMA : réduction de l'hôpital) : le patient paie le tarif
    réduit, AUCUNE part d'assurance privée (patron 2026-10-19). Une ligne absente de cette liste n'en
    est pas une : elle suit l'assurance réelle du patient, avec son taux."""
    cle = article.get('liste_tarif')
    return bool(cle and cle in (contexte.get('listes_remise') or ())
                and ((contexte.get('listes') or {}).get(cle) or {}).get(article.get('nom')) is not None)


def pct_remise_ligne(article, contexte):
    """Pourcentage de réduction de la liste « remise » de cette ligne (SMA : 20 ou 25), 0 sinon."""
    if not ligne_remise(article, contexte):
        return 0.0
    return _nombre((contexte.get('remise_pct') or {}).get(article.get('liste_tarif')))


def _tarif_entree(entree, article):
    """Tarif privé de l'entrée — celui de nuit pour une ligne vendue la nuit, s'il existe."""
    if article.get('nuit') and _nombre(entree.get('tarif_nuit')) > 0:
        return _nombre(entree.get('tarif_nuit'))
    return _nombre(entree.get('tarif_prive'))


def arrondir_part_patient(montant, pas):
    """Part patient arrondie au multiple de `pas` le plus proche (moitié vers le haut) — patron
    2026-10-19, d'après les listes de la Clinique Valeo : 3 696 -> 3 700, 9 044 -> 9 050, 4 757 -> 4 750."""
    pas = _nombre(pas)
    if pas <= 0 or montant <= 0:
        return montant
    return float(int(montant / pas + 0.5 + 1e-9) * pas)


def tarif_unitaire(article, contexte):
    """(tarif, source) — source : 'prive' | 'non_assure' | 'base'."""
    prix = _nombre(article.get('prix'))
    # ⭐ Le caissier a modifié le prix à la main dans le panier : son choix
    # explicite prime sur tout tarif automatique.
    if article.get('prix_modifie'):
        return prix, 'base'
    # ⭐ 2026-10-15 : seules les assurances qui prennent ENCORE cet article comptent
    amu_ligne = bool(contexte.get('amu')) and _pris(article.get('prise_en_charge_amu'))
    # ⭐ 2026-10-19 (patron) : SMA pour un patient AMU — « l'AMU paie sa part et la SMA s'applique sur le
    # reste » : la ligne reste au prix clinique, la réduction se calcule après l'AMU (repartir_ligne)
    if amu_ligne and pct_remise_ligne(article, contexte) > 0:
        return prix, 'base'
    prend_privee = privee_ligne(article, contexte)
    entree = entree_privee(article, contexte) if prend_privee else None
    if entree and contexte.get('appliquer_tarif_prive', True) and _tarif_entree(entree, article) > 0:
        return _tarif_entree(entree, article), 'prive'
    if not amu_ligne and not prend_privee:
        # ⭐ prix non assuré de nuit (nuit / dimanche / férié) s'il existe
        if article.get('nuit') and _nombre(article.get('prix_non_assure_nuit')) > 0:
            return _nombre(article.get('prix_non_assure_nuit')), 'non_assure'
        if _nombre(article.get('prix_non_assure')) > 0:
            return _nombre(article.get('prix_non_assure')), 'non_assure'
    return prix, 'base'


def repartir_ligne(article, contexte):
    """Répartition d'UNE ligne.

    article : {nom, prix, pbr, quantite, prix_non_assure?, prise_en_charge_amu?,
               prise_en_charge_cac?, pbr_variante?, pbr_prive_modifie?}
    contexte : {amu: bool, taux_amu: %, privee: bool, taux_privee: %,
                pbr_prive_par_acte: {nom: {pbr_1, pbr_2, tarif_prive}},
                variante: 'defaut'|'alternatif'}
    Valeurs NON arrondies (le panier arrondit une fois, après la somme).
    """
    q = article.get('quantite')
    quantite = 1.0 if q is None or q == '' else _nombre(q)
    tarif, source = tarif_unitaire(article, contexte)
    total = tarif * quantite
    # PBR AMU absent (None / '') = le tarif sert de base ; PBR explicitement 0
    # (pharmacie : "non pris en charge") = aucune part AMU.
    pbr_raw = article.get('pbr')
    pbr_amu = tarif if pbr_raw is None or pbr_raw == '' else _nombre(pbr_raw)
    prise_amu = _pris(article.get('prise_en_charge_amu'))
    prise_cac = _pris(article.get('prise_en_charge_cac'))

    base_amu = 0.0
    part_amu = 0.0
    taux_amu = _nombre(contexte.get('taux_amu'))
    if contexte.get('amu') and prise_amu and pbr_amu > 0:
        base_amu = min(tarif, pbr_amu) * quantite
        taux_item = taux_amu_article(article.get('nom'), taux_amu, contexte.get('structure_publique'))
        if taux_item > 0:
            part_amu = base_amu * taux_item / 100

    part_privee = 0.0
    base_privee = 0.0
    taux_privee = _nombre(contexte.get('taux_privee'))
    if privee_ligne(article, contexte) and prise_cac and taux_privee > 0 and not ligne_remise(article, contexte):
        reste = max(total - part_amu, 0.0)
        entree = entree_privee(article, contexte)
        # ⭐ Variante choisie LIGNE PAR LIGNE dans le panier (patron, 2026-10-04 :
        # le choix habituel/alternatif ne doit pas s'imposer à tout le panier),
        # sinon la variante globale du contexte.
        variante = article.get('pbr_variante') or contexte.get('variante', 'defaut')
        # ⭐ PBR privé saisi à la main sur la ligne (patron, 2026-10-05 : « si
        # jamais le taux ne sera pas appliqué sur le prix clinique ») — offert
        # dans le panier seulement quand la compagnie n'a PAS de PBR enregistré
        # pour cet article ; un PBR enregistré et le PBR AMU ne bougent pas.
        pbr_manuel = _nombre(article.get('pbr_prive_modifie'))
        if pbr_manuel > 0:
            pbr_prive = pbr_manuel
        else:
            pbr_prive = pbr_prive_valeur(entree, variante, bool(article.get('nuit'))) if contexte.get('applique_pbr_prive', True) else None
        if pbr_prive is not None:
            # Part privée = taux x PBR privé (pas réduite par l'AMU), la PART
            # restant plafonnée à ce qui reste après l'AMU (patient >= 0)
            base_privee = pbr_prive * quantite
            part_privee = min(base_privee * taux_privee / 100, reste)
        else:
            base_privee = reste
            part_privee = base_privee * taux_privee / 100

    # ⭐ SMA + AMU : réduction de la liste (20 / 25 %) sur ce qui reste au patient après l'AMU (et la
    # part privée, nulle sur une ligne SMA) — l'hôpital la consent, elle est comptabilisée en remise
    reduction = 0.0
    if contexte.get('amu') and prise_amu and source == 'base' and pct_remise_ligne(article, contexte) > 0:
        reduction = max(total - part_amu - part_privee, 0.0) * pct_remise_ligne(article, contexte) / 100
    part_patient = max(total - part_amu - part_privee - reduction, 0.0)
    return {
        'tarif_unitaire': tarif, 'source_tarif': source, 'quantite': quantite, 'total': total,
        'base_amu': base_amu, 'part_amu': part_amu,
        'base_privee': base_privee, 'part_privee': part_privee,
        'reduction_liste': reduction, 'part_patient': part_patient,
    }


def repartir_panier(articles, contexte):
    """Somme des lignes + aide hospitalière (patron : sur le reste après
    assurances, en % plafonné à 100 ou en montant plafonné au reste)."""
    appliquer_code_amu_unique(articles)   # un seul acte par code AMU (voir plus haut)
    lignes = [repartir_ligne(a, contexte) for a in articles]
    sous_total = sum(l['total'] for l in lignes)
    base_amu = sum(l['base_amu'] for l in lignes)
    part_amu = sum(l['part_amu'] for l in lignes)
    part_privee = sum(l['part_privee'] for l in lignes)
    reduction_liste = sum(l['reduction_liste'] for l in lignes)   # SMA après l'AMU
    reste = max(sous_total - part_amu - part_privee - reduction_liste, 0.0)

    type_aide = contexte.get('type_aide') or 'pourcentage'
    valeur_aide = _nombre(contexte.get('taux_aide'))
    aide = 0.0
    if valeur_aide > 0 and reste > 0:
        if type_aide == 'montant':
            aide = min(valeur_aide, reste)
        else:
            aide = reste * min(valeur_aide, 100) / 100
    net = max(reste - aide, 0.0)
    # ⭐ Arrondi de la part patient (patron, 2026-10-19 : appliqué par défaut là où la structure l'a
    # réglé, bouton pour l'enlever) — les parts des assurances ne bougent pas ; l'écart (+/- moitié du
    # pas) est comptabilisé à part (services/comptabilite_service.py).
    net_arrondi = arrondir_part_patient(net, contexte.get('arrondi')) if contexte.get('arrondi') else net
    return {
        'lignes': lignes, 'sous_total': sous_total, 'base_remboursement': base_amu,
        'part_amu': part_amu, 'part_privee': part_privee,
        'reste_apres_assurances': reste, 'aide_hospitaliere': aide, 'net_a_payer': net_arrondi,
        'reduction_liste': reduction_liste,
        'arrondi': net_arrondi - net,
    }
