"""Plusieurs rôles pour un même compte (utils/permissions.py). Pur."""
from utils.permissions import roles_supplementaires_valides, LIBELLES_ROLES


def test_roles_supplementaires_filtres():
    assert roles_supplementaires_valides('caissier', ['secretaire', 'caissier', 'admin', 'inconnu', 'secretaire']) == ['secretaire']
    assert roles_supplementaires_valides('comptable', ['pharmacien', 'caissier']) == ['caissier', 'pharmacien']
    assert roles_supplementaires_valides('caissier', None) == []


def test_tous_les_roles_du_formulaire_sont_connus():
    for role in ('caissier', 'secretaire', 'comptable', 'agent_rh', 'responsable_rh', 'admin'):
        assert role in LIBELLES_ROLES
