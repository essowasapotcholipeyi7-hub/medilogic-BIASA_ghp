"""Tests pour l'organigramme (models.py, Employe.chaine_hierarchique) —
partie testable sans DB : sans manager assigné (manager_id=None), la
relation .manager ne déclenche aucune requête (comportement standard de
SQLAlchemy pour une clé étrangère None sur un objet transitoire)."""

from datetime import date

from models import Employe


def test_chaine_hierarchique_vide_sans_manager():
    e = Employe(nom='X', prenom='Y', sexe='M', telephone='000',
                date_embauche=date(2020, 1, 1))
    assert e.manager_id is None
    assert e.chaine_hierarchique() == []
