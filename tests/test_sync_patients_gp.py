"""Patients GHP -> gestion_patients (services/sync_patients_gp.py) — patron, 2026-10-22 : « les patients
enregistrés ce soir ne viennent pas dans gestion_patients »."""
from types import SimpleNamespace

import models
import services.sync_patients_gp as sync


def test_envoi_part_tout_de_suite_sans_attendre_une_validation(monkeypatch):
    """La fiche est déjà enregistrée (db.execute_query) : l'envoi ne dépend plus d'un commit de la session
    SQLAlchemy (qui n'arrivait jamais après une modification de fiche)."""
    mapping = SimpleNamespace(api_url='https://gp.test/', api_key='cle')
    requete = SimpleNamespace(filter_by=lambda **k: SimpleNamespace(all=lambda: [mapping]))
    monkeypatch.setattr(models, 'StructureMapping', SimpleNamespace(query=requete), raising=False)
    session = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchall=lambda: [SimpleNamespace(id=5)]))
    monkeypatch.setattr(models, 'db', SimpleNamespace(session=session), raising=False)
    monkeypatch.setattr(sync, 'fiche_pour_gp', lambda p: {'ID': p.id})
    envois = []
    monkeypatch.setattr(sync, '_poster', lambda url, cle, fiches: envois.append((url, cle, fiches)))

    class FilImmediat:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(sync.threading, 'Thread', FilImmediat)

    sync.pousser_patients_gp(1, [5])
    assert envois == [('https://gp.test', 'cle', [{'ID': 5}])]


def test_deuxieme_essai_quand_gestion_patients_se_reveille(monkeypatch):
    """Premier envoi expiré (gestion_patients en veille) : un second essai, plus patient."""
    appels = []

    def post(url, params, json, timeout):
        appels.append(timeout)
        if len(appels) == 1:
            raise TimeoutError('réveil trop long')
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr(sync.requests, 'post', post)
    monkeypatch.setattr('time.sleep', lambda s: None)
    assert sync._poster('https://gp.test', 'cle', [{'ID': 5}]) == 200
    assert appels == [60, 90]


def test_rien_ne_part_sans_liaison(monkeypatch):
    requete = SimpleNamespace(filter_by=lambda **k: SimpleNamespace(all=lambda: []))
    monkeypatch.setattr(models, 'StructureMapping', SimpleNamespace(query=requete), raising=False)
    monkeypatch.setattr(sync, '_poster', lambda *a: (_ for _ in ()).throw(AssertionError('envoi inattendu')))
    sync.pousser_patients_gp(1, [5])
