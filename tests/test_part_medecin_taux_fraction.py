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


# ⭐ 2026-10-15 (patron) : prix de base propre à un médecin pour un acte
def test_prix_base_propre_au_medecin():
    from services.part_medecin_service import prix_base_pour
    aff = {'Consultation cardio': [{'medecin_id': 1, 'taux': None, 'prix_base': 15000.0},
                                   {'medecin_id': 2, 'taux': None, 'prix_base': None}]}
    assert prix_base_pour('Consultation cardio', 1, aff) == 15000.0
    assert prix_base_pour('Consultation cardio', '1', aff) == 15000.0
    assert prix_base_pour('Consultation cardio', 2, aff) is None       # prix de vente
    assert prix_base_pour('Autre acte', 1, aff) is None


@pytest.mark.parametrize('saisie, attendu', [('15 000', 15000.0), ('15000 F', 15000.0), (12000, 12000.0), ('', None), (None, None)])
def test_lecture_prix_base(saisie, attendu):
    from services.part_medecin_service import lire_prix_base
    assert lire_prix_base(saisie) == attendu


@pytest.mark.parametrize('saisie', ['abc', '0', '-5000'])
def test_prix_base_illisible_refuse(saisie):
    from services.part_medecin_service import lire_prix_base
    with pytest.raises(ValueError):
        lire_prix_base(saisie)
