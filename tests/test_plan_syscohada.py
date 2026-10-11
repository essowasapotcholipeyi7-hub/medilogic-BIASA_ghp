"""Plan comptable SYSCOHADA révisé (utils/plan_comptable_syscohada.py) —
patron, 2026-10-11 : plusieurs numéros venaient du plan comptable français.
Pur, sans base."""
from utils.plan_comptable_syscohada import (
    PLAN_COMPTABLE, PLAN_COMPTABLE_PAR_NUMERO, RENUMEROTATION_SYSCOHADA, compte_charge_pour_motif,
    COMPTE_RESULTAT_BENEFICE, COMPTE_RESULTAT_PERTE, COMPTE_REPORT_A_NOUVEAU_CREDITEUR,
    COMPTES_RETRAITE_PAR_ORGANISME, COMPTES_AMU_PAR_ORGANISME, COMPTE_PERSONNEL_A_PAYER,
    COMPTE_CREANCE_ABANDONNEE, COMPTE_IMMO_MATERIEL_MEDICAL, COMPTE_AMORT_MATERIEL_MEDICAL,
)


def _nom(numero):
    return PLAN_COMPTABLE_PAR_NUMERO[numero]['nom'].lower()


def test_numeros_uniques_classe_et_type_coherents():
    nums = [c['numero'] for c in PLAN_COMPTABLE]
    assert len(nums) == len(set(nums))
    for c in PLAN_COMPTABLE:
        assert len(c['numero']) == 8 and c['numero'][0] == c['classe']
        if c['classe'] == '6':
            assert c['type'] == 'charge'
        if c['classe'] == '7':
            assert c['type'] == 'produit'


def test_resultat_et_report_a_nouveau_syscohada():
    assert COMPTE_RESULTAT_BENEFICE == '13100000' and COMPTE_RESULTAT_PERTE == '13900000'
    assert COMPTE_REPORT_A_NOUVEAU_CREDITEUR == '12100000'


def test_rubriques_de_charges_syscohada():
    # 69 = dotations aux provisions (SYSCOHADA) : les remises accordées n'y vont plus (709)
    assert not [c for c in PLAN_COMPTABLE if c['numero'].startswith('69')]
    assert 'loyer' in _nom('62200000') and 'assurance' in _nom('62500000')
    assert 'télécommunications' in _nom('62800000') and 'bancaires' in _nom('63100000')
    assert 'impôts' in _nom('64100000') and 'logiciels' in _nom('63400000')
    assert all(v['charge'].startswith('664') for v in list(COMPTES_RETRAITE_PAR_ORGANISME.values()) + list(COMPTES_AMU_PAR_ORGANISME.values()))
    assert COMPTES_RETRAITE_PAR_ORGANISME['CRT']['salarial'].startswith('432')
    assert COMPTES_AMU_PAR_ORGANISME['AMU-INAM']['salarial'].startswith('433')
    assert COMPTE_PERSONNEL_A_PAYER.startswith('422')
    assert COMPTE_CREANCE_ABANDONNEE == '70900000'


def test_stocks_et_immobilisations():
    assert all(not c['numero'].startswith('37') for c in PLAN_COMPTABLE)
    assert COMPTE_IMMO_MATERIEL_MEDICAL.startswith('24') and COMPTE_AMORT_MATERIEL_MEDICAL.startswith('284')


def test_motifs_du_formulaire_des_charges():
    attendu = {'abonnement_ssoftonev10': '63400000', 'salaire': '66100000', 'assurance': '62500000',
               'reparation': '62400000', 'fourniture': '60410000', 'eau': '60500000', 'electricite': '60500000',
               'internet': '62800000', 'loyer': '62200000', 'materiel': '60560000', 'transport': '61800000',
               'communication': '62800000', 'autres': '65800000'}
    for motif, compte in attendu.items():
        assert compte_charge_pour_motif(motif) == compte, motif
    assert compte_charge_pour_motif('Fournitures de bureau') == '60550000'
    assert compte_charge_pour_motif('réseau wifi') != '60500000'   # « eau » dans « réseau »


def test_renumerotation_vers_le_plan():
    assert all(v in PLAN_COMPTABLE_PAR_NUMERO for v in RENUMEROTATION_SYSCOHADA.values())
    # un ancien numéro encore présent dans le plan n'est valable que s'il est lui-même la cible d'un autre
    cibles = set(RENUMEROTATION_SYSCOHADA.values())
    reutilises = {'12900000'}   # ancien « perte » -> 139 ; 129 = report à nouveau débiteur en SYSCOHADA
    for ancien in RENUMEROTATION_SYSCOHADA:
        assert ancien not in PLAN_COMPTABLE_PAR_NUMERO or ancien in cibles or ancien in reutilises, ancien
