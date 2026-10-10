"""Règles congés / permissions — Code du travail togolais (utils/regles_absences.py).
Purs, sans base ni application (même principe que test_conges.py)."""
from datetime import date

import pytest

from utils.regles_absences import (
    REGLES_DEFAUT, fusionner_regles, anciennete_mois, droit_conge_annuel, jours_ouvrables,
    jours_dans_le_mois, controler_permission, mode_deduction_convenance, salaire_journalier,
)

R = fusionner_regles({})


@pytest.mark.parametrize('embauche, ref, attendu', [
    (date(2025, 1, 15), date(2026, 1, 15), 12),
    (date(2025, 1, 15), date(2026, 1, 14), 11),
    (date(2026, 4, 1), date(2026, 10, 1), 6),
    (date(2026, 4, 2), date(2026, 10, 1), 5),
    (date(2026, 10, 10), date(2026, 9, 1), 0),
])
def test_anciennete_mois(embauche, ref, attendu):
    assert anciennete_mois(embauche, ref) == attendu


def test_droit_conge_annuel_seuils():
    assert droit_conge_annuel(date(2025, 1, 1), date(2026, 1, 1), R)['statut'] == 'acquis'
    assert droit_conge_annuel(date(2025, 6, 1), date(2026, 1, 1), R)['statut'] == 'derogation'   # 7 mois
    assert droit_conge_annuel(date(2025, 9, 1), date(2026, 1, 1), R)['statut'] == 'bloque'       # 4 mois
    assert 'convenance' not in droit_conge_annuel(date(2025, 9, 1), date(2026, 1, 1), R)['message']


def test_jours_ouvrables_lundi_samedi_hors_feries():
    # du lundi 05/10/2026 au dimanche 11/10/2026 : 6 jours ouvrables
    assert jours_ouvrables(date(2026, 10, 5), date(2026, 10, 11)) == 6
    assert jours_ouvrables(date(2026, 10, 5), date(2026, 10, 11), feries={date(2026, 10, 6)}) == 5
    assert jours_ouvrables(date(2026, 10, 11), date(2026, 10, 5)) == 0


def test_jours_dans_le_mois():
    # 28/09 (lundi) -> 03/10 (samedi) : 3 jours en septembre, 3 en octobre
    assert jours_dans_le_mois(date(2026, 9, 28), date(2026, 10, 3), 2026, 9) == 3
    assert jours_dans_le_mois(date(2026, 9, 28), date(2026, 10, 3), 2026, 10) == 3


def test_permission_exceptionnelle():
    ok = controler_permission('exceptionnelle', 3, R, code_evenement='mariage_travailleur')
    assert ok['erreurs'] == []
    trop = controler_permission('exceptionnelle', 4, R, code_evenement='mariage_travailleur')
    assert 'surplus' in trop['erreurs'][0]
    sans = controler_permission('exceptionnelle', 1, R, code_evenement=None)
    assert sans['erreurs']
    r2 = fusionner_regles({'justificatif_exceptionnelle': 'a_la_demande'})
    assert controler_permission('exceptionnelle', 2, r2, code_evenement='deces_enfant')['erreurs']
    assert controler_permission('exceptionnelle', 2, r2, code_evenement='deces_enfant', justificatif_fourni=True)['erreurs'] == []


def test_permission_convenance_plafond_avertir_ou_bloquer():
    assert controler_permission('convenance', 3, R, deja_pris_convenance=7) == {'erreurs': [], 'avertissements': []}
    avert = controler_permission('convenance', 4, R, deja_pris_convenance=7)
    assert avert['erreurs'] == [] and avert['avertissements']
    bloque = controler_permission('convenance', 4, fusionner_regles({'convenance_depassement': 'bloquer'}), deja_pris_convenance=7)
    assert bloque['erreurs']


def test_deduction_convenance():
    assert mode_deduction_convenance(R, 'conge', True, 30, 2) == 'salaire'
    r = fusionner_regles({'convenance_deduction': 'conge_si_solde'})
    assert mode_deduction_convenance(r, None, True, 30, 2) == 'conge'
    assert mode_deduction_convenance(r, None, False, 30, 2) == 'salaire'   # congé pas encore acquis
    assert mode_deduction_convenance(r, None, True, 1, 2) == 'salaire'     # solde insuffisant
    r = fusionner_regles({'convenance_deduction': 'au_choix'})
    assert mode_deduction_convenance(r, 'conge', True, 30, 2) == 'conge'
    assert mode_deduction_convenance(r, 'salaire', True, 30, 2) == 'salaire'


def test_salaire_journalier():
    assert salaire_journalier(130000, R, 27) == 5000
    assert salaire_journalier(135000, fusionner_regles({'diviseur_journalier': 0}), 27) == 5000


def test_fusion_bornes_et_evenements():
    r = fusionner_regles({'anciennete_conge_mois': 12, 'derogation_conge_mois': 20, 'convenance_max_jours': 'x',
                          'evenements': [{'libelle': 'Mariage', 'jours': 3}, {'libelle': 'Mariage', 'jours': 0}, {'libelle': ''}]})
    assert r['derogation_conge_mois'] == 12
    assert r['convenance_max_jours'] == 10
    assert [e['jours'] for e in r['evenements']] == [3, 1]
    assert len({e['code'] for e in r['evenements']}) == 2
    assert REGLES_DEFAUT['convenance_max_jours'] == 10
