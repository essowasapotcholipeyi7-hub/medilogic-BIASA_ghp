"""Situation périodique des médicaments (Gestion des stocks, 2026-10-22) : stock initial, entrées, sorties,
stock final, montant des ventes et valeur — toujours équilibré (final = initial + entrées - sorties).
Données fictives."""
from datetime import datetime

from services import situation_periodique as sp

FIN = datetime(2026, 10, 23)

PRODUITS = {
    '1': {'nom': 'Paracétamol 500', 'unite': 'boîte', 'prix_vente': 500, 'prix_achat': 300, 'stock_actuel': 40},
    '2': {'nom': 'Amoxicilline', 'unite': 'boîte', 'prix_vente': 1500, 'prix_achat': 1000, 'stock_actuel': 4},
    '3': {'nom': 'Jamais bougé', 'unite': '', 'prix_vente': 100, 'prix_achat': 0, 'stock_actuel': 7},
    '4': {'nom': 'Créé après la période', 'unite': '', 'prix_vente': 100, 'prix_achat': 0, 'stock_actuel': 9},
    '5': {'nom': 'Départ du suivi', 'unite': '', 'prix_vente': 200, 'prix_achat': 0, 'stock_actuel': 18},
}
AVANT = {'1': {'stock_apres': 50}, '2': {'stock_apres': 10}}


def _periode(**k):
    base = {'nb': 1, 'ventes': 0, 'annulations': 0, 'entrees_autres': 0, 'sorties_autres': 0, 'appro': 0,
            'stock_final': 0, 'stock_avant_premier': 0, 'premier_seed': 0, 'seed_stock': 0}
    base.update(k)
    return base


PERIODE = {
    '1': _periode(nb=3, ventes=12, annulations=2, stock_final=40, stock_avant_premier=50),
    # approvisionnement 20, ventes 20, inventaire -5, et 1 unité retirée sans être journalisée
    '2': _periode(nb=3, ventes=20, entrees_autres=20, appro=20, sorties_autres=5, stock_final=4, stock_avant_premier=10),
    # premier mouvement = point de départ du suivi (20), puis 2 ventes
    '5': _periode(nb=2, ventes=2, stock_final=18, premier_seed=1, seed_stock=20),
}
PREMIERS = {'4': datetime(2026, 11, 1)}


def _lignes(base_prix='vente', ventes=None):
    s = sp.construire_situation(PRODUITS, AVANT, PERIODE, PREMIERS, ventes or {}, FIN, base_prix)
    return {l['id']: l for l in s['lignes']}, s


def test_toujours_equilibre():
    lignes, _ = _lignes()
    for l in lignes.values():
        assert l['stock_initial'] + l['entrees'] - l['sorties'] == l['stock_final'], l['nom']


def test_vente_annulee_deduite_des_sorties():
    l = _lignes()[0]['1']
    assert (l['stock_initial'], l['entrees'], l['sorties'], l['sorties_ventes'], l['stock_final']) == (50, 0, 10, 10, 40)


def test_ecart_non_journalise_signale_et_compte():
    l = _lignes()[0]['2']
    assert l['entrees_appro'] == 20 and l['sorties_ventes'] == 20
    assert l['sorties'] == 26 and l['ecart_non_journalise'] == -1


def test_depart_du_suivi_n_est_pas_une_entree():
    l = _lignes()[0]['5']
    assert (l['stock_initial'], l['entrees'], l['sorties'], l['stock_final']) == (20, 0, 2, 18)


def test_produit_sans_mouvement_et_produit_cree_apres():
    lignes, _ = _lignes()
    assert lignes['3']['stock_initial'] == lignes['3']['stock_final'] == 7
    assert '4' not in lignes


def test_valeur_selon_le_prix_choisi():
    assert _lignes('vente')[0]['1']['valeur_final'] == 40 * 500
    assert _lignes('achat')[0]['1']['valeur_final'] == 40 * 300


def test_montant_des_ventes_aux_prix_factures():
    ventes = sp.ventes_par_produit(
        [{'produits': [{'id': 1, 'quantite': 10, 'prix': 500}, {'id': '1', 'quantite': '2', 'total': 900}]}],
        lambda v: v)
    l = _lignes(ventes=ventes)[0]['1']
    assert l['quantite_vendue'] == 12 and l['montant_ventes'] == 5900


def test_filtres_et_exports():
    _, s = _lignes()
    assert {l['id'] for l in sp.filtrer(s['lignes'], seulement_bouges=True)} == {'1', '2', '5'}
    assert [l['id'] for l in sp.filtrer(s['lignes'], 'amox')] == ['2']
    sit = dict(s, debut_affiche='01/10/2026', fin_affiche='22/10/2026')
    csv = sp.exporter_csv(sit, s['lignes'])
    assert csv.startswith('﻿') and 'Amoxicilline;boîte;10;20;26;4;' in csv
    assert 'TOTAL' in sp.exporter_texte(sit, s['lignes'], 'Test')
    assert sp.exporter_pdf(sit, s['lignes'], 'Test').startswith(b'%PDF')
