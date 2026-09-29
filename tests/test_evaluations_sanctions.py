"""Tests pour les évaluations et sanctions disciplinaires (models.py,
SanctionDisciplinaire.type_sanction_label) — pure, aucune dépendance DB
(même remarque que tests/test_contrats.py)."""

from datetime import date

from models import SanctionDisciplinaire, TYPES_SANCTION


def _sanction(type_sanction):
    return SanctionDisciplinaire(structure_id=1, employe_id=1, type_sanction=type_sanction,
                                  date_sanction=date(2026, 1, 1), motif='Test')


def test_type_sanction_label_connu():
    s = _sanction('avertissement_ecrit')
    assert s.type_sanction_label() == 'Avertissement écrit'


def test_type_sanction_label_tous_les_types_connus():
    for code, libelle in TYPES_SANCTION.items():
        s = _sanction(code)
        assert s.type_sanction_label() == libelle


def test_type_sanction_label_valeur_inconnue_retourne_le_code():
    s = _sanction('code_invalide')
    assert s.type_sanction_label() == 'code_invalide'
