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


def test_journal_propose_d_apres_les_comptes():
    from utils.plan_comptable_syscohada import journal_pour_comptes
    assert journal_pour_comptes(['62200000', '57100000']) == 'CAI'          # loyer payé en espèces
    assert journal_pour_comptes(['62200000', '52100000']) == 'BQU'          # loyer payé par banque
    assert journal_pour_comptes(['60100000', '44520000', '40100000']) == 'ACH'   # facture fournisseur
    assert journal_pour_comptes(['41110000', '70610000']) == 'VTE'          # vente à crédit
    assert journal_pour_comptes(['66100000', '42210000', '43110000']) == 'SAL'   # paie
    assert journal_pour_comptes(['65800000', '63400000']) == 'OD'           # reclassement
    assert journal_pour_comptes([]) == 'OD'


def _soldes(lignes):
    soldes = {}
    for l in lignes:
        soldes[l['numero_compte']] = soldes.get(l['numero_compte'], 0) + l['debit'] - l['credit']
    return soldes


def test_cloture_tva_due():
    """Clôture : 443 et 445 soldés, la différence devient une dette 4441 (la caisse ne bouge pas)."""
    from utils.plan_comptable_syscohada import liquidation_tva
    lignes, a_payer, reporte = liquidation_tva(collectee=18000, deductible=5000)
    assert (a_payer, reporte) == (13000, 0)
    assert sum(l['debit'] for l in lignes) == sum(l['credit'] for l in lignes)
    assert _soldes(lignes) == {'44310000': 18000, '44520000': -5000, '44410000': -13000}
    assert not any(l['numero_compte'].startswith('5') for l in lignes)


def test_cloture_tva_credit_reporte_puis_impute():
    from utils.plan_comptable_syscohada import liquidation_tva
    lignes, a_payer, reporte = liquidation_tva(collectee=2000, deductible=7000)
    assert (a_payer, reporte) == (0, 5000)
    assert _soldes(lignes) == {'44310000': 2000, '44520000': -7000, '44490000': 5000}
    # période suivante : le crédit reporté vient en déduction
    lignes, a_payer, reporte = liquidation_tva(collectee=9000, deductible=1000, credit_anterieur=5000)
    assert (a_payer, reporte) == (3000, 0)
    assert sum(l['debit'] for l in lignes) == sum(l['credit'] for l in lignes)
    assert _soldes(lignes)['44490000'] == -5000


def test_cloture_tva_neant():
    from utils.plan_comptable_syscohada import liquidation_tva
    assert liquidation_tva(0, 0, 0) == ([], 0, 0)


def test_comptes_tva_dans_le_plan():
    from utils.plan_comptable_syscohada import COMPTES_TVA
    for numero in COMPTES_TVA:
        assert numero in PLAN_COMPTABLE_PAR_NUMERO and numero not in RENUMEROTATION_SYSCOHADA
