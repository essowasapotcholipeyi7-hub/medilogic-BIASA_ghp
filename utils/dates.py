# utils/dates.py
"""Utilitaires de dates purs (aucune dépendance réseau/Sheets/DB) — extraits
d'app.py pour pouvoir être testés unitairement sans avoir besoin de vraies
credentials Google Sheets (SheetsHelper() se connecte réellement dès
l'import d'app.py, ce qui rend ce module-ci le seul endroit testable en CI
sans secrets)."""

import re
from datetime import datetime

RE_DATE_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# ⭐ Formats vus en pratique quand une date a été tapée à la main dans
# Google Sheets au lieu de venir du sélecteur natif de l'appli (qui ne
# produit que de l'ISO). "/" = JJ/MM/AAAA (hypothèse déjà en place, pas de
# MM/JJ/AAAA pour ne pas créer d'ambiguïté avec ce format) ; "-" et "." sont
# des séparateurs alternatifs vus sur des saisies manuelles FR. Testé dans
# cet ordre : le premier qui matche gagne.
_FORMATS_CONNUS = [
    '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y',   # JJ/MM/AAAA (+ variantes séparateur)
    '%Y/%m/%d', '%Y.%m.%d',               # AAAA/MM/JJ (+ variantes séparateur)
]


def normaliser_date_peremption(valeur):
    """Normalise une date de péremption vers le format ISO (YYYY-MM-DD),
    seul format compris par les champs <input type="date"> et par new
    Date() en JS. Les produits ajoutés depuis l'appli sont déjà en ISO (le
    sélecteur de date natif ne produit que ça), mais certaines structures
    ont des produits dont la date a été tapée à la main directement dans
    Google Sheets, avec des séparateurs variés (ex: "01/03/2027",
    "01-03-2027") — Sheets les affiche alors tel quel, sans les convertir.
    Sans cette normalisation, le champ <input type="date"> refuse
    carrément une valeur non-ISO (il exige du ISO strict) — un produit
    modifié verrait alors sa date de péremption existante silencieusement
    effacée à l'enregistrement, même si la modification ne concernait pas
    du tout ce champ."""
    valeur = (valeur or '').strip()
    if not valeur or RE_DATE_ISO.match(valeur):
        return valeur
    for fmt in _FORMATS_CONNUS:
        try:
            return datetime.strptime(valeur, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return valeur
