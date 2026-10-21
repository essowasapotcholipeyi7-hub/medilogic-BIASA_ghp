# -*- coding: utf-8 -*-
"""⭐ 2026-10-21 (patron) — accueil en libre-service (QR code / tablette) :

- services proposés au patient qui vient pour une consultation ou un contrôle, tirés des actes de
  consultation du catalogue de la structure (« S101 Consultation specialisee (CARDIOLOGIE) » -> Cardiologie) :
  chaque structure ne propose que les services qu'elle a vraiment ;
- file d'attente du ticket : le numéro d'ordre est compté par motif, et par service pour une consultation
  ou un contrôle (Contrôle — Cardiologie n° 1, Contrôle — Rhumatologie n° 1, Contrôle — Cardiologie n° 2...).
  Indicatif seulement : jamais repris dans les ventes."""
import re
import unicodedata

MOTIFS = {
    'consultation': 'Consultation',
    'controle': 'Contrôle',
    'resultat_analyse': "Résultat d'analyse",
    'realisation_examen': "Réalisation d'examen",
}
MOTIFS_AVEC_SERVICE = ('consultation', 'controle')
AUTRE_SERVICE = 'Autre / je ne sais pas'

# libellés en clair (le catalogue est souvent en majuscules sans accents)
_LIBELLES = {
    'cardiologie': 'Cardiologie', 'gynecologie': 'Gynécologie', 'ophtalmologie': 'Ophtalmologie',
    'rhumatologie': 'Rhumatologie', 'dermatologie': 'Dermatologie', 'traumatologie': 'Traumatologie',
    'medecine interne': 'Médecine interne', 'medecine du travail': 'Médecine du travail', 'chirurgie': 'Chirurgie',
    'orl': 'ORL', 'pneumologie': 'Pneumologie', 'urologique': 'Urologie', 'urologie': 'Urologie',
    'genetique medicale': 'Génétique médicale', 'neo nat': 'Néonatologie', 'neonatologie': 'Néonatologie',
    'pediatrique': 'Pédiatrie', 'pediatrie': 'Pédiatrie', 'neurologie': 'Neurologie', 'gastro-enterologie': 'Gastro-entérologie',
    'gastroenterologie': 'Gastro-entérologie', 'endocrinologie': 'Endocrinologie', 'nephrologie': 'Néphrologie',
    'psychiatrie': 'Psychiatrie', 'stomatologie': 'Stomatologie', 'gyneco-obstetrique': 'Gynéco-obstétrique',
}


def _norm(t):
    t = unicodedata.normalize('NFKD', t or '')
    return ' '.join(''.join(c for c in t if not unicodedata.combining(c)).lower().split())


def _libelle(brut):
    cle = _norm(brut)
    if cle in _LIBELLES:
        return _LIBELLES[cle]
    t = ' '.join(brut.split())
    return t[:1].upper() + t[1:].lower() if t.isupper() else t


def services_de_consultation(noms_actes):
    """Noms des actes du catalogue -> services proposés (Médecine générale d'abord, puis par ordre
    alphabétique), sans doublon."""
    trouves = {}
    for nom in noms_actes or []:
        n = _norm(nom)
        if 'consultation' not in n:
            continue
        if any(x in n for x in ('hospitalisation', 'reference', 'carnet', 'urgence', 'programmee', 'domicile')):
            continue
        if 'generale' in n:
            lib = 'Médecine générale'
        elif 'pediatri' in n:
            lib = 'Pédiatrie'
        elif 'prenatale' in n:
            lib = 'Consultation prénatale'
        elif 'dentaire' in n:
            lib = 'Chirurgie dentaire'
        else:
            m = re.search(r'\(([^)]+)\)', nom)
            # une spécialité tient en quelques mots, sans chiffre (« avec maximum de 4 séances... » : non)
            if not m or re.search(r'\d', m.group(1)) or len(m.group(1).split()) > 3 \
                    or _norm(m.group(1)).split()[0] in ('avec', 'y', 'sauf', 'par', 'pour', 'hors', 'en'):
                continue
            lib = _libelle(m.group(1))
        trouves.setdefault(_norm(lib), lib)
    return sorted(trouves.values(), key=lambda s: (s != 'Médecine générale', _norm(s)))


def file_attente(motif, service=None, autre=''):
    """Libellé de la file d'attente (« Contrôle — Cardiologie ») — sert aussi de clé de comptage."""
    if motif in MOTIFS:
        lib = MOTIFS[motif]
        if motif in MOTIFS_AVEC_SERVICE and service:
            lib += ' — ' + service
        return lib
    return 'Autre motif'
