"""Produits d'un séjour / épisode : sortis du stock à l'ajout de la ligne, la conversion de la proforma ne
décompte plus que la différence (patron, 2026-10-24)."""
from services.hospitalisation_service import ventiler_stock_conversion


def test_deja_sorti_rien_a_decompter():
    assert ventiler_stock_conversion([(88, 3, 'Perfalgan')], {'88': 3}) == ([], [])


def test_sejour_ancien_tout_a_decompter():
    # lignes ajoutées avant le changement : rien n'est sorti, tout se décompte à la conversion (comme avant)
    assert ventiler_stock_conversion([(88, 3, 'Perfalgan'), (2, 1, 'Acupan')], {}) == \
        ([('88', 3, 'Perfalgan'), ('2', 1, 'Acupan')], [])


def test_quantite_augmentee_dans_la_proforma():
    assert ventiler_stock_conversion([(88, 5, 'Perfalgan')], {'88': 3}) == ([('88', 2, 'Perfalgan')], [])


def test_quantite_baissee_ou_ligne_retiree():
    a_sortir, a_rendre = ventiler_stock_conversion([(88, 1, 'Perfalgan')], {'88': 3, '2': 2})
    assert a_sortir == []
    assert ('88', 2, 'Perfalgan') in a_rendre and ('2', 2, None) in a_rendre


def test_meme_produit_sur_deux_lignes():
    # deux lignes du même produit dans la vente, sorties au séjour en deux fois
    assert ventiler_stock_conversion([(88, 2, 'Perfalgan'), ('88', 1, 'Perfalgan')], {'88': 3}) == ([], [])
