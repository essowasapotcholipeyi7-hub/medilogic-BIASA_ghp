# -*- coding: utf-8 -*-
"""Stock du laboratoire et de la radiologie (2026-10-18) : calculs sans base de données."""
from decimal import Decimal, ROUND_DOWN
from types import SimpleNamespace

from services.consommables_service import examens_possibles, niveau, seuil_par_defaut, nombre


def test_examens_possibles():
    assert examens_possibles(100, 1) == 100          # 100 films, 1 par radio
    assert examens_possibles(50, Decimal('2')) == 25  # 2 films par examen
    assert examens_possibles(100, Decimal('1.25')) == 80
    assert examens_possibles(0, 1) == 0
    assert examens_possibles(-3, 1) == 0
    assert examens_possibles(10, 0) is None


def test_nombre_ajuste_jamais_un_examen_de_moins():
    # nombre d'examens corrigé à la main -> quantité par examen arrondie vers le bas
    for stock in (100, 7, 250, 33):
        for n in range(1, 120):
            qpe = (Decimal(stock) / n).quantize(Decimal('0.0001'), rounding=ROUND_DOWN)
            if qpe > 0:
                assert examens_possibles(stock, qpe) >= n


def test_alerte_et_seuil():
    assert seuil_par_defaut(100) == 20
    assert seuil_par_defaut(7) == 2
    assert seuil_par_defaut(0) is None
    article = lambda q, s: SimpleNamespace(quantite=Decimal(q), seuil_alerte=None if s is None else Decimal(s))
    assert niveau(article(50, 20)) == 'ok'
    assert niveau(article(20, 20)) == 'alerte'
    assert niveau(article(0, 20)) == 'epuise'
    assert niveau(article(5, None)) == 'ok'


def test_affichage_des_quantites():
    assert nombre(Decimal('12')) == 12 and isinstance(nombre(Decimal('12.000')), int)
    assert nombre(Decimal('1.25')) == 1.25
    assert nombre(None) == 0
