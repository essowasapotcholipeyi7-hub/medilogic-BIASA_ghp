"""Paie par rubriques — reproduit au franc près le bulletin CNSS modèle
(septembre 2026) fourni par le patron le 2026-10-14."""
from types import SimpleNamespace

import pytest

from services.paie_service import calculer_paie
from utils.paie_rubriques import BAREME_IRPP_TOGO, tronquer, franc, valider_rubrique


def _parametrage(**kw):
    p = dict(taux_cnss_salarial=4.0, taux_cnss_patronal=17.5, plafond_cnss=0,
             taux_crt_salarial=7.0, taux_crt_patronal=20.0, plafond_crt=0,
             amu_taux_global=10.0, taux_amu_salarial_defaut=5.0, taux_amu_patronal_defaut=5.0,
             taux_formation_pro=0, tranches_irpp=BAREME_IRPP_TOGO, abattement_taux=28.0,
             abattement_plafond_annuel=10000000, deduction_personne_charge=10000, max_personnes_charge=6,
             affichage_cotisations='combinee', irpp_arrondi_base=1000, jours_mois=30)
    p.update(kw)
    return SimpleNamespace(**p)


def _employe(**kw):
    e = dict(secteur_paie='prive', personnes_a_charge=0, taux_retraite_salarial_override=None,
             taux_retraite_patronal_override=None, taux_amu_salarial_override=None, taux_amu_patronal_override=None)
    e.update(kw)
    return SimpleNamespace(**e)


RUBRIQUES_MODELE = [
    {'code': '116', 'libelle': 'PRIME ANCIENNETE', 'sens': 'gain', 'mode': 'pourcentage', 'taux': 5, 'soumis_cnss': True, 'soumis_irpp': True},
    {'code': '148', 'libelle': 'INDEMNITE LOGEMENT', 'sens': 'gain', 'mode': 'fixe', 'montant': 52080, 'soumis_cnss': True, 'soumis_irpp': True},
    {'code': '635', 'libelle': 'PRIME ENTRET. & REPARATION', 'sens': 'gain', 'mode': 'fixe', 'montant': 77522, 'soumis_cnss': False, 'soumis_irpp': False},
    {'code': '655', 'libelle': 'SYNTRASTO', 'sens': 'retenue', 'mode': 'fixe', 'montant': 500},
    {'code': '665', 'libelle': 'RETENUE COOPERATIVE', 'sens': 'retenue', 'mode': 'fixe', 'montant': 50000},
    {'code': '667', 'libelle': 'REMBOUR. COOPERATIVE', 'sens': 'retenue', 'mode': 'fixe', 'montant': 172938, 'base': 5706962},
    {'code': '699', 'libelle': 'RETENUE MUTUELLE', 'sens': 'retenue', 'mode': 'fixe', 'montant': 1500},
]


def test_bulletin_cnss_modele_au_franc_pres():
    c = calculer_paie(_employe(), 553014, 0, 0, _parametrage(), rubriques=RUBRIQUES_MODELE)
    lignes = {l['code']: l for l in c['lignes']}
    assert lignes['100']['gain'] == 553014 and lignes['100']['taux'] == 30
    assert lignes['116']['gain'] == 27651 and lignes['116']['base'] == 553014 and lignes['116']['taux'] == 5
    assert lignes['148']['gain'] == 52080
    assert lignes['635']['gain'] == 77522
    assert lignes['408']['base'] == 632745 and lignes['408']['taux'] == 9 and lignes['408']['retenue'] == 56947
    assert lignes['442']['base'] == 414575 and lignes['442']['retenue'] == 21650
    assert lignes['667']['base'] == 5706962 and lignes['667']['retenue'] == 172938
    assert c['salaire_brut'] == 710267          # Totaux gain
    assert c['total_retenues'] == 303535        # Totaux retenue
    assert c['net_a_payer'] == 406732           # Net à payer
    assert c['base_cnss'] == 632745 and c['base_irpp'] == 414000
    assert [l['code'] for l in c['lignes']] == ['100', '116', '148', '408', '442', '635', '655', '665', '667', '699']
    # comptabilité : brut = net + retenues salariales (écriture équilibrée)
    assert c['salaire_brut'] == c['net_a_payer'] + c['retraite_salarial'] + c['amu_salarial'] + c['irpp'] \
        + c['prets_deduction'] + c['acomptes_deduction'] + c['autres_retenues_total']
    assert all(r.get('rubrique') for r in c['autres_retenues'])


def test_cumul_annuel_irpp_neuf_mois():
    c = calculer_paie(_employe(), 553014, 0, 0, _parametrage(), rubriques=RUBRIQUES_MODELE)
    assert 9 * c['irpp'] == 194850 and 9 * c['revenu_net_imposable'] == 3731175 and 9 * c['base_cnss'] == 5694705


def test_presentation_detaillee_et_jours():
    c = calculer_paie(_employe(), 553014, 0, 0, _parametrage(affichage_cotisations='detaillee'), rubriques=RUBRIQUES_MODELE)
    codes = {l['code']: l for l in c['lignes']}
    assert codes['408']['retenue'] + codes['409']['retenue'] == 56947 and codes['408']['taux'] == 4
    demi = calculer_paie(_employe(), 300000, 0, 0, _parametrage(), jours_travailles=15)
    assert demi['salaire_base'] == 150000 and demi['jours_travailles'] == 15


def test_retenues_manuelles_et_rubriques_non_dupliquees():
    c = calculer_paie(_employe(), 200000, 0, 0, _parametrage(), prets=10000, acomptes=5000,
                      autres_retenues=[{'libelle': 'Assurance', 'montant': 2000}, {'libelle': 'MUTUELLE', 'montant': 1500, 'rubrique': True}],
                      rubriques=[RUBRIQUES_MODELE[-1]])
    libelles = [l['libelle'] for l in c['lignes']]
    assert libelles.count('RETENUE MUTUELLE') == 1 and 'MUTUELLE' not in libelles and 'ASSURANCE' in libelles
    assert c['autres_retenues_total'] == 3500


def test_arrondis_et_validation_rubrique():
    assert franc(27650.7) == 27651 and franc(25309.8) == 25310 and tronquer(414575, 1000) == 414000 and tronquer(414575, 1) == 414575
    with pytest.raises(ValueError):
        valider_rubrique({'code': '408', 'libelle': 'x'})
    r = valider_rubrique({'code': '655', 'libelle': 'syntrasto', 'sens': 'retenue', 'soumis_cnss': True})
    assert r['libelle'] == 'SYNTRASTO' and r['soumis_cnss'] is False and r['ordre'] == 655
