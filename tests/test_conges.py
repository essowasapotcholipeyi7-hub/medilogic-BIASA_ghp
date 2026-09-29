"""Tests pour la classification des types de congés (models.py) — pure,
aucune dépendance DB (models.py ne se connecte pas à l'import, contrairement
à app.py/sheets_helper — voir tests/test_dates.py pour la même remarque)."""

import pytest

from models import TYPES_CONGE_DEDUCTIBLES, conge_est_deductible


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
