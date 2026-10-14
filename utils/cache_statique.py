"""⭐ Cache navigateur des fichiers statiques (patron, 2026-10-14 : « certains onglets
prennent du temps pour s'afficher »).

Jusqu'ici chaque fichier de /static était servi en « no-cache » : à CHAQUE changement
d'onglet, le navigateur redemandait au serveur si fenetre_app.js, theme_sombre.js... avaient
changé — un aller-retour Togo ↔ serveur (≈ 0,4 s) par fichier, et fenetre_app.js est chargé
dans <head> : la page attendait cette réponse avant de s'afficher.

Maintenant, url_for('static', ...) ajoute ?v=<empreinte du contenu> et ces adresses-là
sont gardées un an par le navigateur. Un fichier modifié change d'empreinte, donc
d'adresse : la nouvelle version est prise dès le déploiement, sans rien vider.
Les adresses écrites à la main (« /static/... » sans ?v=) restent en « no-cache »,
comme avant.
"""
import hashlib
import os

from flask import request

UN_AN = 365 * 24 * 3600
_empreintes = {}


def _empreinte(dossier, nom):
    if nom not in _empreintes:
        try:
            with open(os.path.join(dossier, nom), 'rb') as f:
                _empreintes[nom] = hashlib.md5(f.read()).hexdigest()[:10]
        except OSError:
            _empreintes[nom] = None
    return _empreintes[nom]


def activer_cache_statique(app):
    @app.url_defaults
    def _versionner_statique(endpoint, values):
        if endpoint == 'static' and 'v' not in values and values.get('filename'):
            v = _empreinte(app.static_folder, values['filename'])
            if v:
                values['v'] = v

    def _duree_cache(filename):
        return UN_AN if request.args.get('v') else None

    app.get_send_file_max_age = _duree_cache
