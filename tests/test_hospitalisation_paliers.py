"""Hospitalisation AMU P160 (patron, 2026-10-19) : seule la première semaine est au catalogue, les
8e-14e jours et 15 jours et plus sont calculés tout seuls (catégorie d'après le nom, niveau de la
structure). Purs, sans DB."""
from datetime import date

import pytest

from services.hospitalisation_service import construire_lignes_chambre, est_ligne_semaine_suivante
from utils.grille_amu_hospitalisation import deduire_categorie_salle, deviner_niveau


@pytest.mark.parametrize("nom, attendu", [
    ("P160 Hospi Cabine climatisee avec 1 lit Premiere Semaine", 'cabine'),
    ("P160 Hospitalisation Cabine ventillee avec 2 lits", 'cabine'),
    ("P160 Hospi Salle commune 3 à 6 lits Premiere Semaine", 'salle_commune_3_6'),
    ("P160 Hospi Salle commune 7 à 9 lits Premiere Semaine", 'salle_commune_7_9'),
    ("P160 Salle commune 10 a 12 lits", 'salle_commune_10_12'),
    ("P160 Hospi Reanimation Premiere Semaine", 'reanimation'),
    ("P160 Hospitalisation Salle d'observation", 'observation'),
    ("P160 Hospitalisation Chambre categorie 2 (2 personnes, non climatisee)", 'cabine'),
    ("P160 Hospitalisation Chambre ventilée à 3lits", 'salle_commune_3_6'),   # 3 lits : plus une cabine
    ("P160 Forfait journalier Réa Polyvalente 5000Fr", None),          # forfait CHU SO : hors grille
    ("HOSPITALISATION CLIMEE", None),                                  # pas un acte P160
    ("K233 Césarienne", None),
])
def test_categorie_devinee(nom, attendu):
    assert deduire_categorie_salle(nom) == attendu


def test_niveau_devine_par_tarif_premiere_semaine():
    assert deviner_niveau('cabine', 5000) == '3'
    assert deviner_niveau('cabine', 3750) == '2'
    assert deviner_niveau('cabine', 4200) is None


@pytest.mark.parametrize("nom, attendu", [
    ("P160 Hospi Cabine ventillee avec 1 lit 8e jour au 14e jour", True),
    ("P160 Hospi Cabine ventillee avec 1 lit 15 jours et plus", True),
    ("P160 Hospi Cabine Climatisee avec 2 lits 8e-14e jour", True),
    ("P160 Hospi Cabine Climatisee avec 2 lits 15e jour et plus", True),
    ("P160 Hospi Cabine ventillee avec 1 lit Premiere Semaine", False),
    ("P160 Hospitalisation Cabine ventillee avec 2 lits", False),
    ("Z999 Bilan 15 jours et plus", False),                           # pas un acte P160
])
def test_lignes_semaines_suivantes_masquees(nom, attendu):
    assert est_ligne_semaine_suivante(nom) is attendu


CABINE_CHU = {'id': 'A1', 'nom': 'P160 Hospi Cabine climatisee avec 1 lit Premiere Semaine', 'prix': 7000, 'pbr': 5000}


def test_sept_jours_une_seule_ligne():
    lignes = construire_lignes_chambre(CABINE_CHU, 7, date(2026, 10, 1), [], True, niveau_soins='3')
    assert [(l['quantite'], l['pbr']) for l in lignes] == [(7, 5000)]


def test_seize_jours_paliers_automatiques_sans_categorie_choisie():
    lignes = construire_lignes_chambre(CABINE_CHU, 16, date(2026, 10, 1), [], True, niveau_soins='3')
    assert [(l['quantite'], l['pbr'], l['prix']) for l in lignes] == [(7, 5000, 7000), (7, 3375, 7000), (2, 1625, 7000)]
    assert lignes[1]['date_prestation'] == date(2026, 10, 8) and lignes[2]['date_prestation'] == date(2026, 10, 15)


def test_niveau_2_salle_commune():
    acte = {'id': 'B', 'nom': 'P160 Hospi Salle commune 3 à 6 lits Premiere Semaine', 'prix': 3000, 'pbr': 2500}
    lignes = construire_lignes_chambre(acte, 10, date(2026, 10, 1), [], True, niveau_soins='2')
    assert [(l['quantite'], l['pbr']) for l in lignes] == [(7, 2500), (3, 1625)]


def test_niveau_non_regle_devine_par_le_tarif():
    acte = {'id': 'C', 'nom': 'P160 Hospi Reanimation Premiere Semaine', 'prix': 3500, 'pbr': 3125}
    lignes = construire_lignes_chambre(acte, 15, date(2026, 10, 1), [], True)
    assert [(l['quantite'], l['pbr']) for l in lignes] == [(7, 3125), (7, 2125), (1, 1000)]


def test_patient_non_assure_une_ligne_au_prix_clinique():
    lignes = construire_lignes_chambre(CABINE_CHU, 20, date(2026, 10, 1), [], False, niveau_soins='3')
    assert len(lignes) == 1 and lignes[0]['quantite'] == 20 and lignes[0]['prix'] == 7000


def test_prix_clinique_plus_bas_que_la_grille():
    """Règle du patron : PBR AMU ramené au prix clinique quand celui-ci est plus bas (4 000 < 5 000)."""
    acte = {'id': 'D', 'nom': 'P160 Hospitalisation chambre ventilée à 2lits', 'prix': 4000, 'pbr': 4000}
    sept = construire_lignes_chambre(acte, 7, date(2026, 10, 1), [], True, niveau_soins='3')
    huit = construire_lignes_chambre(acte, 8, date(2026, 10, 1), [], True, niveau_soins='3')
    assert [(l['quantite'], l['pbr']) for l in sept] == [(7, 4000)]
    assert [(l['quantite'], l['pbr']) for l in huit] == [(7, 4000), (1, 3375)]


def test_faute_chamvre_toleree():
    assert deduire_categorie_salle("P160 Hospitalisation Chamvre ventilee a  2lits") == 'cabine'
    assert deduire_categorie_salle("P160 Hospitalisation Chamvre ventilee a  3lits") == 'salle_commune_3_6'


def test_prix_clinique_plafonne_chaque_semaine():
    acte = {'id': 'E', 'nom': 'P160 Hospi Cabine ventillee avec 2 lits Premiere Semaine', 'prix': 2000, 'pbr': 5000}
    lignes = construire_lignes_chambre(acte, 16, date(2026, 10, 1), [], True, niveau_soins='3')
    assert [(l['quantite'], l['pbr']) for l in lignes] == [(7, 2000), (7, 2000), (2, 1625)]


def test_sept_jours_pbr_du_catalogue_trop_haut_ramene_a_la_grille():
    acte = {'id': 'F', 'nom': 'P160 Hospi Cabine Climatisee avec 2 lits Premiere Semaine', 'prix': 7000, 'pbr': 7000}
    lignes = construire_lignes_chambre(acte, 5, date(2026, 10, 1), [], True, niveau_soins='3')
    assert [(l['quantite'], l['pbr']) for l in lignes] == [(5, 5000)]


def test_hopital_de_district_375_chr_625():
    acte = {'id': 'G', 'nom': 'P160 Hospi Salle commune 7 à 9 lits Premiere Semaine', 'prix': 3000, 'pbr': 1875}
    district = construire_lignes_chambre(acte, 16, date(2026, 10, 1), [], True, type_prestataire='hopital_district')
    chr_ = construire_lignes_chambre(acte, 16, date(2026, 10, 1), [], True, type_prestataire='chr')
    assert [(l['quantite'], l['pbr']) for l in district] == [(7, 1875), (7, 1250), (2, 375)]
    assert [(l['quantite'], l['pbr']) for l in chr_] == [(7, 1875), (7, 1250), (2, 625)]
