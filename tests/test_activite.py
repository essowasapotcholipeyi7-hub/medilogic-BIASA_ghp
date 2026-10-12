"""utils/activite.py : les tâches automatiques ne tournent que s'il y a eu de l'activité récente."""
import os
import time

from utils import activite


def test_sans_activite_puis_avec(tmp_path, monkeypatch):
    monkeypatch.setattr(activite, 'FICHIER', str(tmp_path / 'activite'))
    monkeypatch.setattr(activite, '_derniere_ecriture', [0.0])
    assert not activite.activite_recente()          # jamais d'activité : la base peut dormir
    activite.noter_activite()
    assert activite.activite_recente()
    # activité vieille de 20 minutes : plus « récente » à 15 min, encore à 60 min
    ancien = time.time() - 20 * 60
    os.utime(activite.FICHIER, (ancien, ancien))
    assert not activite.activite_recente()
    assert activite.activite_recente(60)


def test_ecriture_au_plus_une_fois_par_minute(tmp_path, monkeypatch):
    monkeypatch.setattr(activite, 'FICHIER', str(tmp_path / 'activite'))
    monkeypatch.setattr(activite, '_derniere_ecriture', [0.0])
    activite.noter_activite()
    ancien = time.time() - 300
    os.utime(activite.FICHIER, (ancien, ancien))
    activite.noter_activite()                        # moins d'une minute après : rien d'écrit
    assert not activite.activite_recente(4)
