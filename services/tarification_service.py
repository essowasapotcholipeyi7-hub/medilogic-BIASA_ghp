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

Garde-fous conservés de l'existant : la base AMU est min(tarif, PBR AMU)
(un PBR officiel supérieur au tarif pratiqué ne fait pas rembourser plus
que le tarif) ; la part privée ne dépasse jamais ce qui reste après l'AMU.
Taux AMU par article : P160 (chambre) 90 %, O101 (oxygène) 100 %, sinon le
taux du patient — voir utils/grille_amu_hospitalisation.py.
"""


def taux_amu_article(nom, taux_defaut):
    if nom and 'O101' in nom:
        return 100
    return 90 if (nom and 'P160' in nom) else taux_defaut


def _nombre(valeur, defaut=0.0):
    try:
        if valeur is None or valeur == '':
            return defaut
        return float(valeur)
    except (TypeError, ValueError):
        return defaut


def pbr_prive_valeur(entree, variante='defaut'):
    """PBR privé applicable (pbr_1 habituel / pbr_2 alternatif) ou None si
    l'entrée n'a pas de PBR (tarif privé seul, "présence ou non d'un PBR")."""
    if not entree:
        return None
    if variante == 'alternatif' and entree.get('pbr_2') is not None:
        return _nombre(entree.get('pbr_2'))
    pbr_1 = entree.get('pbr_1')
    if pbr_1 is None or pbr_1 == '':
        return None
    valeur = _nombre(pbr_1)
    return valeur if valeur > 0 else None


def tarif_unitaire(article, contexte):
    """(tarif, source) — source : 'prive' | 'non_assure' | 'base'."""
    prix = _nombre(article.get('prix'))
    # ⭐ Le caissier a modifié le prix à la main dans le panier : son choix
    # explicite prime sur tout tarif automatique.
    if article.get('prix_modifie'):
        return prix, 'base'
    entree = contexte.get('pbr_prive_par_acte', {}).get(article.get('nom')) if contexte.get('privee') else None
    if entree and contexte.get('appliquer_tarif_prive', True) and _nombre(entree.get('tarif_prive')) > 0:
        return _nombre(entree.get('tarif_prive')), 'prive'
    if not contexte.get('amu') and not contexte.get('privee') and _nombre(article.get('prix_non_assure')) > 0:
        return _nombre(article.get('prix_non_assure')), 'non_assure'
    return prix, 'base'


def repartir_ligne(article, contexte):
    """Répartition d'UNE ligne.

    article : {nom, prix, pbr, quantite, prix_non_assure?, prise_en_charge_amu?,
               prise_en_charge_cac?}
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
    prise_amu = article.get('prise_en_charge_amu', True)
    prise_cac = article.get('prise_en_charge_cac', True)
    prise_amu = prise_amu if isinstance(prise_amu, bool) else str(prise_amu).upper() != 'FALSE'
    prise_cac = prise_cac if isinstance(prise_cac, bool) else str(prise_cac).upper() != 'FALSE'

    base_amu = 0.0
    part_amu = 0.0
    taux_amu = _nombre(contexte.get('taux_amu'))
    if contexte.get('amu') and prise_amu and pbr_amu > 0:
        base_amu = min(tarif, pbr_amu) * quantite
        taux_item = taux_amu_article(article.get('nom'), taux_amu)
        if taux_item > 0:
            part_amu = base_amu * taux_item / 100

    part_privee = 0.0
    base_privee = 0.0
    taux_privee = _nombre(contexte.get('taux_privee'))
    if contexte.get('privee') and prise_cac and taux_privee > 0:
        reste = max(total - part_amu, 0.0)
        entree = contexte.get('pbr_prive_par_acte', {}).get(article.get('nom'))
        # ⭐ Variante choisie LIGNE PAR LIGNE dans le panier (patron, 2026-10-04 :
        # le choix habituel/alternatif ne doit pas s'imposer à tout le panier),
        # sinon la variante globale du contexte.
        variante = article.get('pbr_variante') or contexte.get('variante', 'defaut')
        pbr_prive = pbr_prive_valeur(entree, variante) if contexte.get('applique_pbr_prive', True) else None
        if pbr_prive is not None:
            # Part privée = taux x PBR privé (pas réduite par l'AMU), la PART
            # restant plafonnée à ce qui reste après l'AMU (patient >= 0)
            base_privee = pbr_prive * quantite
            part_privee = min(base_privee * taux_privee / 100, reste)
        else:
            base_privee = reste
            part_privee = base_privee * taux_privee / 100

    part_patient = max(total - part_amu - part_privee, 0.0)
    return {
        'tarif_unitaire': tarif, 'source_tarif': source, 'quantite': quantite, 'total': total,
        'base_amu': base_amu, 'part_amu': part_amu,
        'base_privee': base_privee, 'part_privee': part_privee,
        'part_patient': part_patient,
    }


def repartir_panier(articles, contexte):
    """Somme des lignes + aide hospitalière (patron : sur le reste après
    assurances, en % plafonné à 100 ou en montant plafonné au reste)."""
    lignes = [repartir_ligne(a, contexte) for a in articles]
    sous_total = sum(l['total'] for l in lignes)
    base_amu = sum(l['base_amu'] for l in lignes)
    part_amu = sum(l['part_amu'] for l in lignes)
    part_privee = sum(l['part_privee'] for l in lignes)
    reste = max(sous_total - part_amu - part_privee, 0.0)

    type_aide = contexte.get('type_aide') or 'pourcentage'
    valeur_aide = _nombre(contexte.get('taux_aide'))
    aide = 0.0
    if valeur_aide > 0 and reste > 0:
        if type_aide == 'montant':
            aide = min(valeur_aide, reste)
        else:
            aide = reste * min(valeur_aide, 100) / 100
    net = max(reste - aide, 0.0)
    return {
        'lignes': lignes, 'sous_total': sous_total, 'base_remboursement': base_amu,
        'part_amu': part_amu, 'part_privee': part_privee,
        'reste_apres_assurances': reste, 'aide_hospitaliere': aide, 'net_a_payer': net,
    }
