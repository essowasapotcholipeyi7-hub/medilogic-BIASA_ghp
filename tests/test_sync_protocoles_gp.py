"""Protocoles GHP -> gestion_patients (services/sync_protocoles_gp.py). Pur."""
from types import SimpleNamespace

from services.sync_protocoles_gp import charge_utile


def _p(**k):
    base = dict(id=7, categorie='protocole_soins', titre='Ventoline', contenu='Posologie...', description='',
                medicaments=[], examens=[], statut='publie', auteur_nom='Dr X', source_app=None,
                source_model=None, source_id=None)
    base.update(k)
    return SimpleNamespace(**base)


def test_document_ne_dans_ghp():
    m = charge_utile(_p())
    assert m['source_app'] == 'ghp' and m['source_id'] == 7 and m['actif'] is True and 'gp_id' not in m


def test_document_ne_dans_gestion_patients_met_a_jour_l_original():
    m = charge_utile(_p(source_app='gestion_patients', source_model='ProtocoleSoins', source_id=42,
                        contenu='Ventoline\n\nPosologie...'))
    assert m['gp_id'] == 42 and 'source_id' not in m and m['contenu'] == 'Posologie...'


def test_brouillon_ou_archive_inactif_et_categories_non_synchronisees():
    assert charge_utile(_p(statut='brouillon'))['actif'] is False
    assert charge_utile(_p(), action='archive')['actif'] is False
    assert charge_utile(_p(categorie='fiche_information')) is None
    assert charge_utile(_p(source_app='autre')) is None
