# -*- coding: utf-8 -*-
"""Comptes dans Neon (2026-10-18) : même forme de données que Google Sheets."""
from services.comptes_service import feuille_comptes, _forme_feuille, ENTETES_STRUCTURES, _COL_STRUCTURES, \
    ENTETES_UTILISATEURS, _COL_UTILISATEURS


def test_feuilles_concernees():
    assert feuille_comptes('structures') == ('structures', None)
    assert feuille_comptes('struct_14_users') == ('users', 14)
    assert feuille_comptes('struct_-999490_users') == ('users', -999490)
    assert feuille_comptes('struct_14_actes') is None
    assert feuille_comptes('struct_1_produits') is None
    assert feuille_comptes(None) is None


def test_meme_forme_que_google_sheets():
    ligne = {'id': 7, 'nom': 'CMS YAYRA ', 'email': None, 'telephone': '91525154', 'adresse': 'zossime',
             'statut': 'active', 'logo_url': '', 'derniere_connexion': '24/07/2026 13:17:33'}
    r = _forme_feuille(ligne, ENTETES_STRUCTURES, _COL_STRUCTURES)
    assert list(r) == ENTETES_STRUCTURES
    assert r['ID'] == 7 and r['telephone'] == 91525154          # nombres convertis comme get_all_records()
    assert r['email'] == '' and r['nom'] == 'CMS YAYRA '         # vide -> '', texte gardé tel quel
    assert _forme_feuille({'telephone': '9042OO58'}, ['telephone'], {'telephone': 'telephone'})['telephone'] == '9042OO58'
    brut = _forme_feuille(ligne, ENTETES_STRUCTURES, _COL_STRUCTURES, numeriser=False)
    assert brut['ID'] == '7' and brut['telephone'] == '91525154'


def test_comptes_du_personnel():
    ligne = {'sheet_id': 3, 'nom': 'TEST RADIO', 'structure_id_ligne': '1', 'actif': 'oui'}
    r = _forme_feuille(ligne, ENTETES_UTILISATEURS, _COL_UTILISATEURS)
    assert list(r) == ENTETES_UTILISATEURS
    assert r['ID'] == 3 and r['structure_id'] == 1 and r['actif'] == 'oui' and r['mot_de_passe'] == ''
