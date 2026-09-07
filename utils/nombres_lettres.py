# utils/nombres_lettres.py
# ============================================================
# Conversion d'un montant en lettres (français), pour les documents
# imprimés qui doivent "arrêter" une facture/un bordereau en toutes lettres
# (ex: bordereau adressé à une compagnie d'assurance).
# ============================================================

UNITES = ['', 'UN', 'DEUX', 'TROIS', 'QUATRE', 'CINQ', 'SIX', 'SEPT', 'HUIT', 'NEUF',
          'DIX', 'ONZE', 'DOUZE', 'TREIZE', 'QUATORZE', 'QUINZE', 'SEIZE',
          'DIX-SEPT', 'DIX-HUIT', 'DIX-NEUF']

DIZAINES = ['', '', 'VINGT', 'TRENTE', 'QUARANTE', 'CINQUANTE', 'SOIXANTE',
            'SOIXANTE', 'QUATRE-VINGT', 'QUATRE-VINGT']


def _moins_de_cent(n):
    if n < 20:
        return UNITES[n]
    d, u = divmod(n, 10)
    if d in (7, 9):
        # soixante-dix / quatre-vingt-dix : la dizaine "cache" un +10.
        # "et" ne s'utilise qu'avec soixante-et-onze (71), jamais avec
        # quatre-vingt-onze (91).
        base = DIZAINES[d]
        reste = 10 + u
        lien = '-ET-' if (reste == 11 and d == 7) else '-'
        return f"{base}{lien}{UNITES[reste]}" if reste else base
    if u == 0:
        return DIZAINES[d] + ('S' if d in (8,) else '')
    lien = '-ET-' if u == 1 and d in (2, 3, 4, 5, 6) else '-'
    return f"{DIZAINES[d]}{lien}{UNITES[u]}"


def _moins_de_mille(n):
    c, r = divmod(n, 100)
    if c == 0:
        return _moins_de_cent(r)
    prefixe = 'CENT' if c == 1 else f"{UNITES[c]} CENT"
    if r == 0:
        return prefixe + ('S' if c > 1 else '')
    return f"{prefixe} {_moins_de_cent(r)}"


def nombre_en_lettres(n):
    """Convertit un entier positif (montant FCFA) en toutes lettres,
    en français, en MAJUSCULES (convention des documents comptables)."""
    try:
        n = int(round(n))
    except (TypeError, ValueError):
        return ''
    if n == 0:
        return 'ZÉRO'
    if n < 0:
        return 'MOINS ' + nombre_en_lettres(-n)

    parties = []
    milliards, n = divmod(n, 1_000_000_000)
    if milliards:
        mot = 'UN MILLIARD' if milliards == 1 else f"{_moins_de_mille(milliards)} MILLIARDS"
        parties.append(mot)

    millions, n = divmod(n, 1_000_000)
    if millions:
        mot = 'UN MILLION' if millions == 1 else f"{_moins_de_mille(millions)} MILLIONS"
        parties.append(mot)

    milliers, n = divmod(n, 1000)
    if milliers:
        mot = 'MILLE' if milliers == 1 else f"{_moins_de_mille(milliers)} MILLE"
        parties.append(mot)

    if n:
        parties.append(_moins_de_mille(n))

    return ' '.join(parties)


def montant_en_lettres_fcfa(montant):
    """Formule complète prête à imprimer : 'DEUX CENT MILLE FRANCS CFA'."""
    texte = nombre_en_lettres(montant)
    if not texte:
        return ''
    unite = 'FRANC CFA' if int(round(montant)) in (0, 1) else 'FRANCS CFA'
    return f"{texte} {unite}"
