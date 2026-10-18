# -*- coding: utf-8 -*-
"""Catalogue Excel (2026-10-18) : règles de comparaison de l'import."""
from datetime import date, datetime

from services.catalogue_excel import _identiques, _texte_excel, COLONNES_PROTEGEES
from services.feuilles_neon import est_feuille_neon


def test_valeurs_identiques():
    assert _identiques('1500', 1500.0) and _identiques('1500', '1 500') and _identiques('0,5', '0.5')
    assert _identiques('', None) and _identiques(' TRUE ', 'TRUE')
    assert not _identiques('1500', '1600') and not _identiques('TRUE', 'FALSE')


def test_textes_venant_d_excel():
    assert _texte_excel(1500.0) == '1500' and _texte_excel(0.5) == '0.5' and _texte_excel(None) == ''
    assert _texte_excel(True) == 'TRUE' and _texte_excel(date(2027, 3, 1)) == '2027-03-01'
    assert _texte_excel(datetime(2027, 3, 1, 0, 0)) == '2027-03-01'


def test_stock_jamais_importe():
    assert 'quantite_stock' in COLONNES_PROTEGEES['produits'] and 'ID' in COLONNES_PROTEGEES['actes']


def test_feuilles_servies_par_neon():
    assert est_feuille_neon('struct_14_actes') and est_feuille_neon('struct_14_produits')
    assert not est_feuille_neon('struct_14_ventes_actes') and not est_feuille_neon('structures')
