# utils/dates.py
"""Utilitaires de dates purs (aucune dépendance réseau/Sheets/DB) — extraits
d'app.py pour pouvoir être testés unitairement sans avoir besoin de vraies
credentials Google Sheets (SheetsHelper() se connecte réellement dès
l'import d'app.py, ce qui rend ce module-ci le seul endroit testable en CI
sans secrets)."""

import re

RE_DATE_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}$')
RE_DATE_JJMMAAAA = re.compile(r'^(\d{1,2})/(\d{1,2})/(\d{4})$')


def normaliser_date_peremption(valeur):
    """Normalise une date de péremption vers le format ISO (YYYY-MM-DD),
    seul format compris par les champs <input type="date"> et par new
    Date() en JS. Les produits ajoutés depuis l'appli sont déjà en ISO (le
    sélecteur de date natif ne produit que ça), mais certaines structures
    ont des produits dont la date a été tapée à la main directement dans
    Google Sheets au format JJ/MM/AAAA (ex: "01/03/2027") — Sheets les
    affiche alors tel quel, sans les convertir. Sans cette normalisation,
    new Date("01/03/2027") est lu par le navigateur en MM/JJ/AAAA (3 janvier
    au lieu du 1er mars) et le champ <input type="date"> refuse carrément la
    valeur (il exige du ISO strict) — un produit modifié verrait alors sa
    date de péremption existante silencieusement effacée à l'enregistrement."""
    valeur = (valeur or '').strip()
    if not valeur or RE_DATE_ISO.match(valeur):
        return valeur
    m = RE_DATE_JJMMAAAA.match(valeur)
    if m:
        jour, mois, annee = m.groups()
        try:
            return f"{annee}-{int(mois):02d}-{int(jour):02d}"
        except ValueError:
            return valeur
    return valeur
