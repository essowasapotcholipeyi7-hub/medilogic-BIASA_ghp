"""Tests pour la classification des types de congés (models.py) — pure,
aucune dépendance DB (models.py ne se connecte pas à l'import, contrairement
à app.py/sheets_helper — voir tests/test_dates.py pour la même remarque)."""

from datetime import date

import pytest

from models import TYPES_CONGE_DEDUCTIBLES, conge_est_deductible, Conge


def test_seul_annuel_est_deductible():
    """Patron : "les congés conventionnels [...] sont non déductibles des
    jours de congés" — seul le vrai congé payé annuel entame le solde."""
    assert TYPES_CONGE_DEDUCTIBLES['annuel'] is True
    for type_conge in ('maladie', 'maternite', 'paternite', 'sans_solde', 'exceptionnel'):
        assert TYPES_CONGE_DEDUCTIBLES[type_conge] is False


@pytest.mark.parametrize(
    "type_conge, attendu",
    [
        ('annuel', True),
        ('maladie', False),
        ('maternite', False),
        ('paternite', False),
        ('sans_solde', False),
        ('exceptionnel', False),
        # Type inconnu/mal saisi -> déductible par défaut (ne doit jamais
        # échapper silencieusement au décompte du solde).
        ('typo_inconnu', True),
        ('', True),
    ],
)
def test_conge_est_deductible(type_conge, attendu):
    assert conge_est_deductible(type_conge) is attendu


# ⭐ Jours OUVRABLES (lundi-samedi), pas jours ouvrés — patron : "normalement
# les weekends font partie des jours de congés", confirmé par le Code du
# travail togolais (congé acquis à 2,5 jours OUVRABLES/mois = 30/an). Ces
# tests passent sans DB : structure_id non fourni -> aucune requête
# JourFerie n'est exécutée (voir Conge.calculer_jours_ouvres).
@pytest.mark.parametrize(
    "debut, fin, jours_attendus",
    [
        (date(2026, 9, 28), date(2026, 10, 4), 6),  # lundi -> dimanche : samedi compte, dimanche non
        (date(2026, 9, 26), date(2026, 9, 26), 1),  # un seul samedi -> compte
        (date(2026, 9, 27), date(2026, 9, 27), 0),  # un seul dimanche -> ne compte pas
        (date(2026, 9, 21), date(2026, 9, 25), 5),  # lundi -> vendredi
    ],
)
def test_calculer_jours_ouvres_inclut_samedi_exclut_dimanche(debut, fin, jours_attendus):
    conge = Conge(date_debut=debut, date_fin=fin)
    assert conge.calculer_jours_ouvres() == jours_attendus


@pytest.mark.parametrize(
    "date_fin, reprise_attendue",
    [
        (date(2026, 9, 26), date(2026, 9, 28)),  # fin samedi -> reprise lundi (dimanche sauté)
        (date(2026, 9, 25), date(2026, 9, 26)),  # fin vendredi -> reprise samedi (jour ouvrable normal)
    ],
)
def test_calculer_date_reprise_saute_le_dimanche(date_fin, reprise_attendue):
    conge = Conge(date_debut=date_fin, date_fin=date_fin)
    assert conge.calculer_date_reprise() == reprise_attendue
