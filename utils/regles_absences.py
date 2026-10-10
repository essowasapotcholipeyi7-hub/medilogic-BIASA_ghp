"""Règles congés / permissions — Code du travail togolais (patron, 2026-10-10 :
« je veux une vraie GRH », « fais ce qui sera bon avec possibilité de choix »).

Fonctions PURES (aucun accès base) pour être testées sans application
(tests/test_regles_absences.py) ; routes/rh.py et services/paie_service.py
les appellent avec les données lues en base.

1. Congé annuel payé : acquis après `anciennete_conge_mois` (12) de service ;
   entre `derogation_conge_mois` (6) et 12 mois, seulement avec l'accord
   exprès de l'employeur (dérogation motivée) ; avant 6 mois, jamais.
2. Permission exceptionnelle (événement familial, dite aussi
   « conventionnelle ») : dès l'embauche, payée, non déduite du congé,
   durée fixée par événement (liste modifiable), justificatif obligatoire.
3. Permission de convenance personnelle : accord préalable, plafond annuel
   (10 jours), déduite du salaire (ou, au choix de la structure, du solde
   de congé quand il est acquis).
Tous les seuils et choix sont réglables par structure (ParametragePaie.
regles_absences), ces valeurs-ci sont les défauts.
"""
from datetime import date, timedelta

NATURES_PERMISSION = {
    'exceptionnelle': 'Exceptionnelle (événement familial)',
    'convenance': 'Convenance personnelle',
}

# ⚠️ Durées : les deux premières viennent du cahier des charges du patron
# (mariage 3 j, décès conjoint/enfant 4 j) ; les autres sont des valeurs de
# départ à vérifier selon la convention collective — modifiables dans
# « Paramètres paie & RH ».
EVENEMENTS_DEFAUT = [
    {'code': 'mariage_travailleur', 'libelle': 'Mariage du travailleur', 'jours': 3},
    {'code': 'deces_conjoint', 'libelle': 'Décès du conjoint', 'jours': 4},
    {'code': 'deces_enfant', 'libelle': "Décès d'un enfant", 'jours': 4},
    {'code': 'naissance_enfant', 'libelle': "Naissance d'un enfant", 'jours': 3},
    {'code': 'deces_parent', 'libelle': 'Décès du père ou de la mère', 'jours': 3},
    {'code': 'mariage_enfant', 'libelle': "Mariage d'un enfant", 'jours': 1},
    {'code': 'deces_frere_soeur', 'libelle': "Décès d'un frère ou d'une sœur", 'jours': 2},
]

REGLES_DEFAUT = {
    'anciennete_conge_mois': 12,          # congé annuel acquis après N mois de service effectif
    'derogation_conge_mois': 6,           # congé réduit possible à partir de N mois, avec accord de l'employeur
    'derogation_reservee_admin': True,    # seule la direction (admin) peut accorder la dérogation
    'convenance_max_jours': 10,           # plafond annuel des permissions de convenance
    'convenance_depassement': 'avertir',  # 'avertir' (accepté avec alerte) | 'bloquer'
    'convenance_deduction': 'salaire',    # 'salaire' | 'conge_si_solde' | 'au_choix'
    'justificatif_exceptionnelle': 'avant_approbation',  # 'a_la_demande' | 'avant_approbation' | 'facultatif'
    'validation_superieur': False,        # avis du supérieur hiérarchique (N+1) avant l'approbation finale
    'diviseur_journalier': 26,            # salaire journalier = salaire de base / N ; 0 = jours ouvrables du mois
    'evenements': EVENEMENTS_DEFAUT,
}

CHOIX = {
    'convenance_depassement': ('avertir', 'bloquer'),
    'convenance_deduction': ('salaire', 'conge_si_solde', 'au_choix'),
    'justificatif_exceptionnelle': ('a_la_demande', 'avant_approbation', 'facultatif'),
}

JOURS_OUVRABLES = (0, 1, 2, 3, 4, 5)   # lundi..samedi, comme Conge.calculer_jours_ouvres


def _entier(valeur, defaut, minimum=0, maximum=None):
    try:
        n = int(float(str(valeur).replace(',', '.')))
    except (TypeError, ValueError):
        return defaut
    if n < minimum:
        return defaut
    return min(n, maximum) if maximum is not None else n


def normaliser_evenements(evenements):
    sortie, codes = [], set()
    for e in evenements or []:
        libelle = str((e or {}).get('libelle') or '').strip()
        if not libelle:
            continue
        code = str(e.get('code') or '').strip() or ''.join(c if c.isalnum() else '_' for c in libelle.lower())[:50]
        base, i = code, 2
        while code in codes:
            code = f"{base}_{i}"
            i += 1
        codes.add(code)
        sortie.append({'code': code, 'libelle': libelle[:120], 'jours': _entier(e.get('jours'), 1, 1, 60)})
    return sortie


def fusionner_regles(stockees):
    """Règles de la structure complétées par les défauts, valeurs bornées."""
    s = stockees or {}
    r = dict(REGLES_DEFAUT)
    r['anciennete_conge_mois'] = _entier(s.get('anciennete_conge_mois'), 12, 0, 60)
    r['derogation_conge_mois'] = min(_entier(s.get('derogation_conge_mois'), 6, 0, 60), r['anciennete_conge_mois'])
    r['convenance_max_jours'] = _entier(s.get('convenance_max_jours'), 10, 0, 365)
    r['diviseur_journalier'] = _entier(s.get('diviseur_journalier'), 26, 0, 31)
    for cle in ('derogation_reservee_admin', 'validation_superieur'):
        if cle in s:
            r[cle] = bool(s[cle])
    for cle, valeurs in CHOIX.items():
        if s.get(cle) in valeurs:
            r[cle] = s[cle]
    if 'evenements' in s:
        r['evenements'] = normaliser_evenements(s.get('evenements'))
    return r


def anciennete_mois(date_embauche, date_ref):
    """Mois de service COMPLETS entre l'embauche et date_ref."""
    if not date_embauche or not date_ref or date_ref < date_embauche:
        return 0
    mois = (date_ref.year - date_embauche.year) * 12 + (date_ref.month - date_embauche.month)
    if date_ref.day < date_embauche.day:
        mois -= 1
    return max(0, mois)


def droit_conge_annuel(date_embauche, date_debut_conge, regles):
    """'acquis' | 'derogation' (possible seulement avec l'accord de
    l'employeur) | 'bloque', avec un message clair pour l'écran."""
    mois = anciennete_mois(date_embauche, date_debut_conge)
    seuil, seuil_derog = regles['anciennete_conge_mois'], regles['derogation_conge_mois']
    if mois >= seuil:
        return {'statut': 'acquis', 'mois': mois, 'message': ''}
    if mois >= seuil_derog:
        return {'statut': 'derogation', 'mois': mois,
                'message': (f"{mois} mois de service au début du congé : le congé annuel n'est acquis qu'après "
                            f"{seuil} mois. Un congé réduit peut être accordé à partir de {seuil_derog} mois, "
                            "uniquement avec l'accord exprès de l'employeur (dérogation motivée).")}
    return {'statut': 'bloque', 'mois': mois,
            'message': (f"{mois} mois de service au début du congé : aucun congé annuel avant {seuil_derog} mois "
                        f"(droit acquis après {seuil} mois). Une permission exceptionnelle (événement familial) "
                        "reste possible dès l'embauche.")}


def jours_ouvrables(debut, fin, feries=frozenset(), jours_travailles=JOURS_OUVRABLES):
    """Jours ouvrables (lundi..samedi par défaut) entre deux dates incluses,
    hors jours fériés — même décompte que les congés."""
    if not debut or not fin or fin < debut:
        return 0
    n, jour = 0, debut
    while jour <= fin:
        if jour.weekday() in jours_travailles and jour not in feries:
            n += 1
        jour += timedelta(days=1)
    return n


def jours_dans_le_mois(debut, fin, annee, mois, feries=frozenset()):
    """Jours ouvrables d'une période qui tombent dans le mois donné."""
    import calendar
    premier = date(annee, mois, 1)
    dernier = date(annee, mois, calendar.monthrange(annee, mois)[1])
    return jours_ouvrables(max(debut, premier), min(fin, dernier), feries)


def evenement(regles, code):
    return next((e for e in regles.get('evenements') or [] if e['code'] == code), None)


def controler_permission(nature, jours, regles, deja_pris_convenance=0, code_evenement=None,
                         justificatif_fourni=False):
    """Vérifie une demande de permission. Renvoie {'erreurs': [...],
    'avertissements': [...]} — une erreur bloque l'enregistrement."""
    erreurs, avertissements = [], []
    if nature not in NATURES_PERMISSION:
        return {'erreurs': ['Choisissez le type de permission : exceptionnelle ou convenance personnelle.'],
                'avertissements': []}
    if nature == 'exceptionnelle':
        ev = evenement(regles, code_evenement)
        if not ev:
            erreurs.append("Choisissez l'événement familial (mariage, naissance, décès...).")
        elif jours > ev['jours']:
            erreurs.append(f"« {ev['libelle']} » donne droit à {ev['jours']} jour(s) ouvrable(s) ; la demande en compte "
                           f"{jours:g}. Le surplus doit faire l'objet d'une permission de convenance personnelle.")
        if regles['justificatif_exceptionnelle'] == 'a_la_demande' and not justificatif_fourni:
            erreurs.append("Le justificatif (acte de mariage, de naissance, de décès...) est obligatoire.")
    else:
        plafond = regles['convenance_max_jours']
        total = (deja_pris_convenance or 0) + jours
        if total > plafond:
            texte = (f"Permissions de convenance cette année : {deja_pris_convenance:g} jour(s) déjà pris + {jours:g} "
                     f"demandé(s) = {total:g}, au-delà du plafond de {plafond} jours par an.")
            (erreurs if regles['convenance_depassement'] == 'bloquer' else avertissements).append(texte)
    return {'erreurs': erreurs, 'avertissements': avertissements}


def mode_deduction_convenance(regles, choix_demande, droit_conge_acquis, solde_conge, jours):
    """'salaire' ou 'conge' pour une permission de convenance personnelle.
    Le solde de congé n'est utilisé que si le congé est acquis ET suffisant."""
    conge_possible = droit_conge_acquis and (solde_conge or 0) >= jours
    mode = regles['convenance_deduction']
    if mode == 'conge_si_solde':
        return 'conge' if conge_possible else 'salaire'
    if mode == 'au_choix':
        return 'conge' if (choix_demande == 'conge' and conge_possible) else 'salaire'
    return 'salaire'


def salaire_journalier(salaire_base, regles, jours_ouvrables_mois):
    diviseur = regles.get('diviseur_journalier') or 0
    if diviseur <= 0:
        diviseur = jours_ouvrables_mois or 26
    return float(salaire_base or 0) / diviseur
