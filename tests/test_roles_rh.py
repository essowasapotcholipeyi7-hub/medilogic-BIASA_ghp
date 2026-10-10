"""Rôles de la GRH (agent RH, responsable RH) : comptes cloisonnés qui ne
voient que les ressources humaines. Purs, sans base ni application."""
from utils.navigation import ContexteNavigation, domaines_visibles
from utils.onglets_recherchables import onglets_recherchables
from utils.permissions import ROLES_PAR_DEFAUT, ROLES_RH


def _ctx(role):
    return ContexteNavigation(role=role, is_admin=False,
                              a_acces=lambda cle: role in ROLES_PAR_DEFAUT.get(cle, set()),
                              onglet_cache=lambda cle: False, bloque=False)


def test_roles_rh_ont_acces_a_la_grh_seulement():
    for role in ROLES_RH:
        assert role in ROLES_PAR_DEFAUT['rh']
        for cle, roles in ROLES_PAR_DEFAUT.items():
            if cle != 'rh':
                assert role not in roles, (role, cle)


def test_menu_d_un_compte_rh():
    for role in ROLES_RH:
        onglets = {o.id for _, liste in domaines_visibles(_ctx(role)) for o in liste}
        assert onglets == {'rh', 'theme', 'mot_de_passe'}


def test_recherche_d_un_compte_rh_sans_patients():
    for role in ROLES_RH:
        endpoints = {o['endpoint'] for o in onglets_recherchables(role, False, lambda c: False, lambda c: False, False)}
        assert 'patients' not in endpoints and 'rh.gestion_rh' in endpoints


def test_un_secretaire_garde_son_menu():
    onglets = {o.id for _, liste in domaines_visibles(_ctx('secretaire')) for o in liste}
    assert 'patients' in onglets and 'rh' not in onglets
