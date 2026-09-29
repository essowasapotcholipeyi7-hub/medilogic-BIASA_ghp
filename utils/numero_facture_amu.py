# utils/numero_facture_amu.py
"""Formatage du numéro de facture recap AMU (CNSS/TNS/INAM) — fonction pure,
extraite pour être testable sans dépendance Sheets/DB (même motif que
utils/dates.py).

Patron : permettre de retrouver facilement, dans une historique consultable
et cherchable, la facture recap qu'une assurance a réglée et encaissée.
Format : "N° 000000001/AMU/<sigle clinique>/<année>" — le compteur
(FactureAmuMensuelle.numero_local) est auto-incrémenté à la création
(prochain_numero_local, app.py) et modifiable ensuite par l'admin."""

LONGUEUR_COMPTEUR = 9  # "000000001" — 9 chiffres, comme l'exemple du patron


def formater_numero_facture_amu(numero_local, sigle, annee):
    """Ex: formater_numero_facture_amu(1, "ABC", 2026) -> "N° 000000001/AMU/ABC/2026".
    numero_local manquant/invalide -> None (aucune facture générée pour
    l'instant, rien à afficher). sigle manquant -> "CLINIQUE" par défaut
    plutôt qu'un numéro à trou (le sigle se règle une fois pour toutes dans
    Paramètres AMU CNSS)."""
    try:
        numero = int(numero_local)
    except (TypeError, ValueError):
        return None
    if numero <= 0:
        return None
    sigle_affiche = (sigle or '').strip().upper() or 'CLINIQUE'
    return f"N° {numero:0{LONGUEUR_COMPTEUR}d}/AMU/{sigle_affiche}/{annee}"
