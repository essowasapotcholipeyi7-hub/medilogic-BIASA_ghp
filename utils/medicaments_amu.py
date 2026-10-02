# utils/medicaments_amu.py
# ============================================================
# Référentiel des médicaments AMU — fourni par le patron en CSV, modifiable
# par lui à tout moment sans toucher au code (patron, 2026-10-02 :
# "pour amu cnss également pour amu inam dans ce cas [...] pour tns est un
# peu réduit donc cette liste aussi est à part [...] on les mettra dans les
# fichiers de notre projet"). Deux listes distinctes, par type_amu :
#   - data/medicaments_amu_ts.csv  -> amu_cnss ET amu_inam (même liste)
#   - data/medicaments_amu_tns.csv -> amu_tns uniquement (liste réduite)
#
# Rechargé automatiquement dès que le fichier change sur disque (comparaison
# de la date de modification) — le patron peut remplacer le CSV par un
# nouvel export à tout moment, sans redéploiement ni redémarrage du serveur.
# ============================================================

import csv
import os

CHEMINS_PAR_TYPE_AMU = {
    'amu_cnss': 'data/medicaments_amu_ts.csv',
    'amu_inam': 'data/medicaments_amu_ts.csv',
    'amu_tns': 'data/medicaments_amu_tns.csv',
}

_cache = {}  # chemin -> {'mtime': float, 'donnees': [...]}


def _premiere_valeur(row, *noms_colonnes):
    """Essaie plusieurs noms d'en-tête possibles pour la même donnée — les
    deux fichiers fournis par le patron n'utilisent pas exactement les
    mêmes intitulés de colonnes (ex: \"Nom commercial\" pour AMU-CNSS/INAM
    contre \"Nom du médicament\" pour AMU-TNS), même si le contenu est
    équivalent."""
    for nom in noms_colonnes:
        valeur = (row.get(nom) or '').strip()
        if valeur:
            return valeur
    return ''


def _charger(chemin):
    if not os.path.exists(chemin):
        return []
    mtime = os.path.getmtime(chemin)
    entree = _cache.get(chemin)
    if entree and entree['mtime'] == mtime:
        return entree['donnees']

    donnees = []
    with open(chemin, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = _premiere_valeur(row, 'Nom commercial', 'Nom du médicament')
            if not nom:
                continue
            donnees.append({
                'nom': nom,
                'dci': _premiere_valeur(row, 'DCI'),
                'forme': _premiere_valeur(row, 'Forme pharmaceutique'),
                'dosage': _premiere_valeur(row, 'Dosage'),
                'statut': _premiere_valeur(row, 'Statut').upper(),
            })
    _cache[chemin] = {'mtime': mtime, 'donnees': donnees}
    return donnees


def rechercher_medicaments_amu(type_amu, recherche, limite=20):
    """Recherche par nom commercial OU DCI (principe actif) — patron :
    la secrétaire/le médecin peut taper l'un ou l'autre selon ce dont il
    se souvient."""
    chemin = CHEMINS_PAR_TYPE_AMU.get(type_amu)
    if not chemin:
        return []
    q = (recherche or '').strip().lower()
    if len(q) < 2:
        return []
    donnees = _charger(chemin)
    resultats = [
        m for m in donnees
        if q in m['nom'].lower() or q in m['dci'].lower()
    ]
    return resultats[:limite]
