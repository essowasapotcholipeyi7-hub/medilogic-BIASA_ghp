"""Tests pour utils/dates.py (aucune dépendance réseau/Sheets/DB — voir la
note en tête de ce module sur pourquoi il vit en dehors d'app.py)."""

import pytest

from utils.dates import normaliser_date_peremption


@pytest.mark.parametrize(
    "valeur_brute, attendu",
    [
        # Déjà au format ISO -> inchangé
        ("2028-07-30", "2028-07-30"),
        ("2026-09-01", "2026-09-01"),
        # JJ/MM/AAAA tapé à la main dans Google Sheets -> converti en ISO
        ("01/03/2027", "2027-03-01"),
        ("08/09/2026", "2026-09-08"),
        ("1/1/2026", "2026-01-01"),
        ("8/9/2026", "2026-09-08"),  # jour et mois sans zéro de tête
        # Vide / blanc / None -> chaîne vide
        ("", ""),
        ("   ", ""),
        (None, ""),
        # Format inconnu -> laissé tel quel plutôt que de le casser
        ("texte libre", "texte libre"),
    ],
)
def test_normaliser_date_peremption(valeur_brute, attendu):
    assert normaliser_date_peremption(valeur_brute) == attendu


def test_idempotent():
    """Normaliser une date déjà normalisée ne doit rien changer — important
    car /api/produits applique cette fonction à chaque lecture, y compris
    sur des dates déjà en ISO."""
    for valeur in ("2027-03-01", "", "texte"):
        une_fois = normaliser_date_peremption(valeur)
        deux_fois = normaliser_date_peremption(une_fois)
        assert une_fois == deux_fois
