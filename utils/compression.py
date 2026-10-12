"""⭐ Compression gzip des réponses (2026-10-12 : bande passante Render dépassée).

Les pages HTML (≈ 200 Ko chacune, 2,6 Mo pour la liste des patients), le JSON
des API (dont la liste des patients que gestion_patients relit toutes les
3 minutes) et les fichiers JS/CSS sont du texte : compressés, ils pèsent 5 à
10 fois moins. Le navigateur (et la bibliothèque requests côté
gestion_patients) les décompresse tout seul — rien ne change à l'usage.

Pas de dépendance externe : gzip de la bibliothèque standard. Ne touche pas
aux réponses en flux (exports, flux continus), aux fichiers déjà compressés
(images, PDF, ZIP) ni aux réponses minuscules.
"""
import gzip

from flask import request

TYPES_COMPRESSIBLES = (
    'text/html', 'text/css', 'text/plain', 'text/csv', 'text/javascript', 'text/xml',
    'application/json', 'application/javascript', 'application/xml', 'image/svg+xml',
    'application/manifest+json',
)
TAILLE_MIN = 1024              # en dessous, le gain ne vaut pas l'effort
TAILLE_MAX = 8 * 1024 * 1024   # au-delà, on laisse tel quel (mémoire)
NIVEAU = 6


def doit_compresser(response, accept_encoding):
    if 'gzip' not in (accept_encoding or '').lower():
        return False
    # un fichier statique (direct_passthrough) se présente comme un flux mais a
    # une taille connue : compressible ; un vrai flux (export, flux continu) non
    if response.status_code != 200 or (response.is_streamed and not response.direct_passthrough):
        return False
    if response.headers.get('Content-Encoding'):
        return False
    if response.mimetype not in TYPES_COMPRESSIBLES:
        return False
    longueur = response.calculate_content_length()
    if longueur is None and response.direct_passthrough:
        longueur = response.content_length
    if longueur is None and response.direct_passthrough:
        return False   # taille inconnue : on ne lit pas un fichier peut-être énorme
    if longueur is not None and not (TAILLE_MIN <= longueur <= TAILLE_MAX):
        return False
    return True


def compresser_reponse(response):
    if not doit_compresser(response, request.headers.get('Accept-Encoding')):
        return response
    # fichiers statiques : servis en « direct_passthrough » (lecture du fichier)
    response.direct_passthrough = False
    donnees = response.get_data()
    if len(donnees) < TAILLE_MIN:
        return response
    compresse = gzip.compress(donnees, compresslevel=NIVEAU)
    if len(compresse) >= len(donnees):
        return response
    response.set_data(compresse)
    response.headers['Content-Encoding'] = 'gzip'
    response.headers['Content-Length'] = str(len(compresse))
    response.vary.add('Accept-Encoding')
    etag = response.headers.get('ETag')
    if etag and not etag.startswith('W/'):
        response.headers['ETag'] = 'W/' + etag   # même contenu, octets différents
    return response


def activer_compression(app):
    """À appeler juste après la création de l'app : enregistré en premier, ce
    after_request s'exécute en DERNIER (Flask les exécute en ordre inverse),
    donc après tout ce qui pourrait encore lire ou modifier la réponse."""
    app.after_request(compresser_reponse)
