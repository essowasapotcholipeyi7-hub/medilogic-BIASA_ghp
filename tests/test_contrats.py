"""Tests pour l'alerte de renouvellement de contrat (models.py, Employe) —
pure, aucune dépendance DB (les méthodes testées ici ne touchent jamais
Employe.query — voir tests/test_dates.py pour la même remarque)."""

from datetime import date, timedelta

from models import Employe


def _employe(date_fin_contrat=None):
    return Employe(nom='X', prenom='Y', sexe='M', telephone='000',
                    date_embauche=date(2020, 1, 1), date_fin_contrat=date_fin_contrat)


def test_cdi_sans_date_fin_pas_d_alerte():
    e = _employe(date_fin_contrat=None)
    assert e.jours_avant_fin_contrat() is None
    assert e.contrat_a_renouveler() is False


def test_contrat_qui_expire_bientot_declenche_l_alerte():
    e = _employe(date_fin_contrat=date.today() + timedelta(days=10))
    assert e.jours_avant_fin_contrat() == 10
    assert e.contrat_a_renouveler(seuil_jours=30) is True


def test_contrat_deja_expire_declenche_l_alerte():
    e = _employe(date_fin_contrat=date.today() - timedelta(days=5))
    assert e.jours_avant_fin_contrat() == -5
    assert e.contrat_a_renouveler(seuil_jours=30) is True


def test_contrat_loin_dans_le_futur_pas_d_alerte():
    e = _employe(date_fin_contrat=date.today() + timedelta(days=90))
    assert e.contrat_a_renouveler(seuil_jours=30) is False


def test_seuil_personnalise():
    e = _employe(date_fin_contrat=date.today() + timedelta(days=15))
    assert e.contrat_a_renouveler(seuil_jours=10) is False
    assert e.contrat_a_renouveler(seuil_jours=30) is True
