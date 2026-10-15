"""Part médecin (patron, 2026-10-15) : taux saisi en pourcentage OU en fraction (2/3).
Logique pure, sans base."""
import pytest

from services.part_medecin_service import fraction_du_taux, lire_taux_part, taux_part_texte


@pytest.mark.parametrize('saisie, attendu', [
    ('60', 60.0), (60, 60.0), ('66,5', 66.5), ('60 %', 60.0), (' 2/3 ', 200 / 3), ('1/3', 100 / 3), ('3/4', 75.0),
])
def test_lecture_pourcentage_ou_fraction(saisie, attendu):
    assert lire_taux_part(saisie) == pytest.approx(attendu, abs=1e-12)


@pytest.mark.parametrize('saisie', ['', 'abc', '2/0', '/3', None])
def test_saisie_illisible_refusee(saisie):
    with pytest.raises(ValueError):
        lire_taux_part(saisie)


def test_deux_tiers_exact_sur_le_montant():
    taux = lire_taux_part('2/3')
    assert round(9000 * taux / 100, 2) == 6000.0
    assert round(8000 * taux / 100, 2) == 5333.33


def test_affichage():
    assert taux_part_texte(lire_taux_part('2/3')) == '2/3 (66,67 %)'
    assert taux_part_texte(60) == '60 %'
    assert taux_part_texte(12.5) == '12,5 %'            # tient en 2 décimales : pas de « 1/8 »
    assert fraction_du_taux(100 / 3) == '1/3'
    assert fraction_du_taux(33.33) is None              # 33,33 tapé à la main reste 33,33 %
