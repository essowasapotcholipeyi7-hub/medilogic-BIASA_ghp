"""Tests pour le départ structuré d'un employé (models.py, Employe) —
pure, aucune dépendance DB (même remarque que tests/test_contrats.py)."""

from datetime import date

from models import Employe, MOTIFS_DEPART


def _employe(motif_depart=None):
    return Employe(nom='X', prenom='Y', sexe='M', telephone='000',
                   date_embauche=date(2020, 1, 1), motif_depart=motif_depart)


def test_motif_depart_label_connu():
    e = _employe(motif_depart='demission')
    assert e.motif_depart_label() == 'Démission'


def test_motif_depart_label_tous_les_motifs_connus():
    for code, libelle in MOTIFS_DEPART.items():
        e = _employe(motif_depart=code)
        assert e.motif_depart_label() == libelle


def test_motif_depart_label_valeur_inconnue_retourne_le_code():
    e = _employe(motif_depart='code_invalide')
    assert e.motif_depart_label() == 'code_invalide'


def test_pas_de_motif_par_defaut():
    e = _employe()
    assert e.motif_depart is None
