"""Compression gzip des réponses (utils/compression.py) — app Flask minimale, sans base."""
import gzip

from flask import Flask, Response, jsonify

from utils.compression import activer_compression


def _app():
    app = Flask(__name__)
    activer_compression(app)

    @app.route('/page')
    def page():
        return '<html>' + 'Patient KOFFI Ama ' * 500 + '</html>'

    @app.route('/api')
    def api():
        return jsonify({'patients': [{'ID': i, 'nom': 'AMEGAN'} for i in range(300)]})

    @app.route('/petit')
    def petit():
        return 'ok'

    @app.route('/image')
    def image():
        return Response(b'\x89PNG' + b'0' * 5000, mimetype='image/png')

    @app.route('/flux')
    def flux():
        return Response((ligne for ligne in ['a' * 2000, 'b' * 2000]), mimetype='text/csv')

    return app


def test_html_et_json_compresses_et_identiques_une_fois_decompresses():
    c = _app().test_client()
    for url in ('/page', '/api'):
        brut = c.get(url).data
        r = c.get(url, headers={'Accept-Encoding': 'gzip, deflate, br'})
        assert r.headers['Content-Encoding'] == 'gzip'
        assert 'Accept-Encoding' in r.headers['Vary']
        assert int(r.headers['Content-Length']) == len(r.data) < len(brut) / 3
        assert gzip.decompress(r.data) == brut


def test_rien_de_compresse_sans_accept_encoding_ni_pour_les_cas_exclus():
    c = _app().test_client()
    assert 'Content-Encoding' not in c.get('/page').headers                     # client sans gzip
    for url in ('/petit', '/image', '/flux'):                                 # minuscule, binaire, flux
        r = c.get(url, headers={'Accept-Encoding': 'gzip'})
        assert 'Content-Encoding' not in r.headers, url
    assert c.get('/flux', headers={'Accept-Encoding': 'gzip'}).data == b'a' * 2000 + b'b' * 2000
