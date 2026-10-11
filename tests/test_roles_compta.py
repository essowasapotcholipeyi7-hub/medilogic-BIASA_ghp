"""Comptabilité cloisonnée (comptable, agent comptable) : comme la GRH. Pur."""
from utils.navigation import ContexteNavigation, domaines_visibles, ONGLETS_COMPTA
from utils.onglets_recherchables import onglets_recherchables
from utils.permissions import ROLES_PAR_DEFAUT, ROLES_COMPTA, LIBELLES_ROLES


def _ctx(role):
    return ContexteNavigation(role=role, is_admin=False,
                              a_acces=lambda cle: role in ROLES_PAR_DEFAUT.get(cle, set()),
                              onglet_cache=lambda cle: False, bloque=False)


def test_menu_compta_sans_patients_ni_soins():
    for role in ROLES_COMPTA:
        onglets = {o.id for _, liste in domaines_visibles(_ctx(role)) for o in liste}
        assert onglets <= ONGLETS_COMPTA
        assert {'comptabilite', 'factures', 'admin_finances'} <= onglets
        assert not onglets & {'patients', 'actes_vente', 'consultation', 'pharma_vente', 'hospitalisation', 'proformas'}


def test_recherche_compta_sans_pages_cliniques():
    for role in ROLES_COMPTA:
        endpoints = {o['endpoint'] for o in onglets_recherchables(role, False, lambda c: role in ROLES_PAR_DEFAUT.get(c, set()),
                                                                   lambda c: False, False)}
        assert 'patients' not in endpoints and 'actes_vente' not in endpoints
        assert 'comptabilite.index' in endpoints


def test_libelle_agent_comptable():
    assert LIBELLES_ROLES['sous_comptable'] == 'Agent comptable'


def test_gestionnaire_garde_son_menu_large():
    onglets = {o.id for _, liste in domaines_visibles(_ctx('gestionnaire')) for o in liste}
    assert 'patients' in onglets and 'comptabilite' in onglets
