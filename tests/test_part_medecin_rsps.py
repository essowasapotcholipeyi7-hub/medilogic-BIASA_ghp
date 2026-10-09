"""Part médecin (patron, 2026-10-08) : taux par (acte, médecin) avec
affectations, RSPS 5 % sur le brut / net au médecin, mapping comptable.
Logique pure, sans base."""
from services.part_medecin_service import calculer_rsps, taux_pour, taux_rsps_pour_medecin
from utils.plan_comptable_syscohada import (COMPTE_HONORAIRES_MEDECINS, COMPTE_RSPS_A_REVERSER,
                                            PLAN_COMPTABLE_PAR_NUMERO, compte_charge_pour_motif)


def test_rsps_5_pour_cent_sur_le_brut():
    assert calculer_rsps(100000, 5) == (5000.0, 95000.0)
    assert calculer_rsps(33333, 5) == (1667.0, 31666.0)       # arrondi au franc
    assert calculer_rsps(100000, 5, actif=False) == (0.0, 100000.0)
    assert calculer_rsps(100000, 0) == (0.0, 100000.0)
    assert calculer_rsps(None, 5) == (0.0, 0.0)


def test_taux_par_acte_et_par_medecin():
    taux_acte = {'Echographie pelvienne': 40.0, 'Consultation cardio': 50.0}
    affect = {'Echographie pelvienne': [{'medecin_id': 1, 'taux': 60.0}, {'medecin_id': 2, 'taux': None}]}
    # médecin 1 : taux propre ; médecin 2 : taux de l'acte ; médecin 3 (non affecté) : taux de l'acte quand même
    assert taux_pour(0, 'Echographie pelvienne', 1, taux_acte, affect) == 60.0
    assert taux_pour(0, 'Echographie pelvienne', '2', taux_acte, affect) == 40.0
    assert taux_pour(0, 'Echographie pelvienne', 3, taux_acte, affect) == 40.0
    assert taux_pour(0, 'Consultation cardio', 1, taux_acte, affect) == 50.0
    assert taux_pour(0, 'Acte sans taux', 1, taux_acte, affect) is None


def test_comptes_part_medecin_et_rsps():
    assert COMPTE_HONORAIRES_MEDECINS in PLAN_COMPTABLE_PAR_NUMERO
    assert COMPTE_RSPS_A_REVERSER in PLAN_COMPTABLE_PAR_NUMERO
    assert PLAN_COMPTABLE_PAR_NUMERO[COMPTE_RSPS_A_REVERSER]['classe'] == '4'
    assert compte_charge_pour_motif('Part médecin — Dr ABALO Marie') == COMPTE_HONORAIRES_MEDECINS
    # « eau » dans un nom de médecin ne doit plus détourner vers 614
    assert compte_charge_pour_motif('Part médecin — Dr BEAUDOIN') == COMPTE_HONORAIRES_MEDECINS
    assert compte_charge_pour_motif('Facture eau du mois') == '61400000'


def test_rsps_seulement_avec_nif():
    """Patron (2026-10-09) : la RSPS concerne les médecins qui ont le NIF."""
    assert taux_rsps_pour_medecin(5, 0, True, '1000123456') == (5.0, True)
    assert taux_rsps_pour_medecin(5, 0, True, None) == (0.0, False)
    assert taux_rsps_pour_medecin(5, 0, True, '   ') == (0.0, False)
    # taux « sans NIF » paramétré par la structure
    assert taux_rsps_pour_medecin(5, 10, True, '') == (10.0, True)
    # RSPS désactivée : rien pour personne
    assert taux_rsps_pour_medecin(5, 10, False, '1000123456') == (0.0, False)

