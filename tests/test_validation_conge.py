"""Tests pour la validation à plusieurs niveaux des congés (models.py,
Conge.statut_validation) — partie testable sans DB : sans
document_validation_id (cas par défaut, niveaux_validation_conges <= 1),
la méthode court-circuite avant toute requête SignatureRH."""

from datetime import date

from models import Conge


def test_statut_validation_none_par_defaut():
    c = Conge(structure_id=1, employe_id=1, type_conge='annuel',
              date_debut=date(2026, 1, 1), date_fin=date(2026, 1, 5))
    assert c.document_validation_id is None
    assert c.statut_validation() is None
