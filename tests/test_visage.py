"""Choix de l'employé reconnu par la borne (utils/visage.py). Pur, sans base."""
from utils.visage import choisir_employe


def test_visage_reconnu_le_plus_proche_par_employe():
    assert choisir_employe([(1, 0.42), (1, 0.30), (2, 0.48)])[0] == 1


def test_visage_inconnu_au_dela_du_seuil():
    assert choisir_employe([(1, 0.55), (2, 0.6)]) == (None, 0.55, 'inconnu')
    assert choisir_employe([]) == (None, None, 'inconnu')


def test_visage_ambigu_entre_deux_employes():
    employe, _, raison = choisir_employe([(1, 0.40), (2, 0.43)])
    assert employe is None and raison == 'ambigu'


def test_un_seul_employe_enregistre():
    assert choisir_employe([(7, 0.35)])[0] == 7
