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
import unicodedata
from datetime import timedelta

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


def repartir_jours(nb_jours):
    """16 jours -> [(1, 7), (2, 7), (3, 2)]. Tranches à 0 jour omises."""
    nb_jours = max(int(nb_jours or 0), 0)
    tranches = [
        (1, min(nb_jours, 7)),
        (2, min(max(nb_jours - 7, 0), 7)),
        (3, max(nb_jours - 14, 0)),
    ]
    return [(palier, jours) for palier, jours in tranches if jours > 0]


def construire_lignes_chambre(acte_choisi, nb_jours, date_entree, tous_les_actes, patient_assure):
    """Construit les lignes SoinHospitalisation (sous forme de dicts prêts
    à insérer) pour un acte "chambre" avec `nb_jours` jours facturés.

    - Patient non assuré, séjour <= 7 jours, ou pas de groupe de paliers
      détecté pour cet acte -> une seule ligne, au prix de `acte_choisi`.
    - Sinon -> jusqu'à 3 lignes, une par palier réellement traversé, prix/pbr
      pris sur l'acte sœur du palier correspondant, chacune datée sur sa
      propre période (date_prestation -> date_fin_prestation)."""
    groupe = None if not patient_assure or nb_jours <= 7 else detecter_groupe_palier(
        acte_choisi.get('nom'), tous_les_actes
    )

    if not groupe:
        return [{
            'nom': acte_choisi.get('nom'),
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
