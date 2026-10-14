# -*- coding: utf-8 -*-
"""⭐ Paie par RUBRIQUES, présentation « bulletin CNSS » (patron, 2026-10-14 :
« je veux régler les paramètres de paie de cette manière et que les bulletins
de paie aussi soient de cette manière » — modèle : bulletin CNSS Togo,
septembre 2026, vérifié au franc près).

Lecture du modèle :
  100 SALAIRE DE BASE        base 553 014, taux 30 (jours)      gain 553 014
  116 PRIME ANCIENNETE       base 553 014, taux 5 %             gain  27 651
  148 INDEMNITE LOGEMENT                                         gain  52 080
  408 CNSS                   base 632 745, taux 9 %          retenue  56 947
  442 I.R.P.P.               base 414 575                    retenue  21 650
  635 PRIME ENTRET. & REPAR. (non soumise CNSS / IRPP)          gain  77 522
  ...retenues internes (syndicat, coopérative, mutuelle)
  -> la base CNSS (632 745) = gains SOUMIS seulement ;
  -> base IRPP = (gains soumis − CNSS salarié) × (1 − 28 %) = 414 575 ;
  -> l'IRPP se calcule sur cette base arrondie au millier inférieur
     (414 000) avec le barème annuel / 12 = 21 650 (×9 mois = cumul 194 850).

Module PUR (aucune base) : catalogue par défaut, codes réservés, barème IRPP
officiel, arrondis. Le calcul lui-même est dans services/paie_service.py.
"""
from decimal import Decimal, ROUND_HALF_UP

# Codes calculés par le logiciel (non saisissables comme rubrique libre)
CODE_SALAIRE_BASE = '100'
CODE_PRIMES_DIVERSES = '190'
CODE_INDEMNITES_DIVERSES = '195'
CODE_RETRAITE = '408'          # CNSS (privé) / CRT (public)
CODE_AMU = '409'               # affiché à part seulement en présentation détaillée
CODE_IRPP = '442'
CODE_PRET = '680'
CODE_ACOMPTE = '690'
CODES_RESERVES = {CODE_SALAIRE_BASE, CODE_PRIMES_DIVERSES, CODE_INDEMNITES_DIVERSES,
                  CODE_RETRAITE, CODE_AMU, CODE_IRPP, CODE_PRET, CODE_ACOMPTE}

# Catalogue proposé à chaque structure (modifiable, désactivable ; d'autres
# rubriques s'ajoutent librement — ex. 655 SYNTRASTO, 665 RETENUE COOPERATIVE,
# 667 REMBOUR. COOPERATIVE, propres à la CNSS, volontairement absentes).
RUBRIQUES_DEFAUT = [
    {'code': '116', 'libelle': "PRIME D'ANCIENNETE", 'sens': 'gain', 'mode': 'pourcentage',
     'taux_defaut': 0, 'montant_defaut': 0, 'soumis_cnss': True, 'soumis_irpp': True, 'ordre': 116},
    {'code': '148', 'libelle': 'INDEMNITE DE LOGEMENT', 'sens': 'gain', 'mode': 'fixe',
     'taux_defaut': 0, 'montant_defaut': 0, 'soumis_cnss': True, 'soumis_irpp': True, 'ordre': 148},
    {'code': '635', 'libelle': "PRIME D'ENTRETIEN ET REPARATION", 'sens': 'gain', 'mode': 'fixe',
     'taux_defaut': 0, 'montant_defaut': 0, 'soumis_cnss': False, 'soumis_irpp': False, 'ordre': 635},
    {'code': '699', 'libelle': 'RETENUE MUTUELLE', 'sens': 'retenue', 'mode': 'fixe',
     'taux_defaut': 0, 'montant_defaut': 0, 'soumis_cnss': False, 'soumis_irpp': False, 'ordre': 699},
]

# Barème IRPP annuel (Togo). Les tranches jusqu'à 6 000 000 sont confirmées
# par le bulletin modèle (21 650 F au franc près) ; au-delà, barème officiel
# à faire valider par le comptable.
BAREME_IRPP_TOGO = [
    {'min': 0, 'max': 900000, 'taux': 0},
    {'min': 900000, 'max': 3000000, 'taux': 3},
    {'min': 3000000, 'max': 6000000, 'taux': 10},
    {'min': 6000000, 'max': 9000000, 'taux': 15},
    {'min': 9000000, 'max': 12000000, 'taux': 20},
    {'min': 12000000, 'max': 15000000, 'taux': 25},
    {'min': 15000000, 'max': 20000000, 'taux': 30},
    {'min': 20000000, 'max': None, 'taux': 35},
]
# Ancien barème par défaut du logiciel (remplacé par la migration s'il n'a
# jamais été modifié par la structure)
ANCIEN_BAREME_DEFAUT = [
    {'min': 0, 'max': 900000, 'taux': 0},
    {'min': 900000, 'max': 3000000, 'taux': 3},
    {'min': 3000000, 'max': 4000000, 'taux': 10},
    {'min': 4000000, 'max': 6000000, 'taux': 15},
    {'min': 6000000, 'max': 10000000, 'taux': 25},
    {'min': 10000000, 'max': None, 'taux': 35},
]

MOIS_MAJ = ['', 'JANVIER', 'FEVRIER', 'MARS', 'AVRIL', 'MAI', 'JUIN', 'JUILLET',
            'AOUT', 'SEPTEMBRE', 'OCTOBRE', 'NOVEMBRE', 'DECEMBRE']


def franc(v):
    """Arrondi au franc, demi vers le haut (27 650,7 -> 27 651)."""
    try:
        return float(Decimal(str(float(v or 0))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def tronquer(v, pas):
    """Arrondi à l'inférieur au multiple de `pas` (414 575 -> 414 000)."""
    pas = int(pas or 1)
    if pas <= 1:
        return franc(v)
    return float(int(franc(v)) // pas * pas)


def cle_tri_code(code):
    c = str(code or '')
    return (0, int(c)) if c.isdigit() else (1, c)


def valider_rubrique(data, codes_existants=()):
    """Normalise une rubrique saisie ; lève ValueError si invalide."""
    code = str(data.get('code') or '').strip().upper()
    libelle = str(data.get('libelle') or '').strip().upper()
    if not code or len(code) > 10:
        raise ValueError('Code de rubrique requis (10 caractères maximum).')
    if code in CODES_RESERVES:
        raise ValueError(f"Le code {code} est réservé au calcul automatique (salaire de base, CNSS, IRPP, prêt, acompte).")
    if code in codes_existants:
        raise ValueError(f"Une rubrique porte déjà le code {code}.")
    if not libelle:
        raise ValueError('Libellé requis.')
    sens = data.get('sens') if data.get('sens') in ('gain', 'retenue') else 'gain'
    mode = data.get('mode') if data.get('mode') in ('fixe', 'pourcentage') else 'fixe'
    try:
        taux = float(data.get('taux_defaut') or 0)
        montant = float(data.get('montant_defaut') or 0)
    except (TypeError, ValueError):
        raise ValueError('Taux ou montant invalide.')
    if taux < 0 or taux > 1000 or montant < 0:
        raise ValueError('Taux ou montant invalide.')
    return {'code': code, 'libelle': libelle[:120], 'sens': sens, 'mode': mode,
            'taux_defaut': taux, 'montant_defaut': montant,
            'soumis_cnss': bool(data.get('soumis_cnss')) if sens == 'gain' else False,
            'soumis_irpp': bool(data.get('soumis_irpp')) if sens == 'gain' else False,
            'actif': bool(data.get('actif', True)),
            'ordre': int(code) if code.isdigit() else 900}
