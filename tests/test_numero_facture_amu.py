"""Tests pour utils/numero_facture_amu.py (aucune dépendance réseau/Sheets/DB)."""

import pytest

from utils.numero_facture_amu import formater_numero_facture_amu


@pytest.mark.parametrize(
    "numero_local, sigle, annee, attendu",
    [
        (1, "ABC", 2026, "N° 000000001/AMU/ABC/2026"),
        (9, "CVC", 2027, "N° 000000009/AMU/CVC/2027"),
        (1234567, "XY", 2026, "N° 001234567/AMU/XY/2026"),
        (1000000000, "XY", 2026, "N° 1000000000/AMU/XY/2026"),  # dépasse 9 chiffres -> pas tronqué
        (1, "abc", 2026, "N° 000000001/AMU/ABC/2026"),  # sigle toujours en majuscules
        (1, "  abc  ", 2026, "N° 000000001/AMU/ABC/2026"),  # espaces retirés
        (1, "", 2026, "N° 000000001/AMU/CLINIQUE/2026"),  # sigle vide -> repli
        (1, None, 2026, "N° 000000001/AMU/CLINIQUE/2026"),
    ],
)
def test_formater_numero_facture_amu(numero_local, sigle, annee, attendu):
    assert formater_numero_facture_amu(numero_local, sigle, annee) == attendu


@pytest.mark.parametrize("numero_local", [None, "", "abc", 0, -1])
def test_formater_numero_facture_amu_invalide(numero_local):
    assert formater_numero_facture_amu(numero_local, "ABC", 2026) is None
