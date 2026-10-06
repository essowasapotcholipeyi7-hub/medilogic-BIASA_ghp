"""La signature pré-enregistrée du prescripteur est apposée (image) sur les
fiches EP (CNSS, INAM) et TPC (renouvellement, modification, rectification
INAM) ; sans signature, rien n'est dessiné (patron, 2026-10-06)."""
import io
from datetime import date

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from utils.remplissage_pdf_amu import remplir_entente_prealable
from utils.remplissage_pdf_tpc import remplir_tpc


class _Permissif:
    """Objet de test : attributs explicites, None pour tout le reste."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, nom):
        return None


def _png():
    img = Image.new('RGBA', (300, 100), (255, 255, 255, 0))
    ImageDraw.Draw(img).line([(10, 80), (120, 20), (200, 70), (290, 30)], fill=(0, 0, 120, 255), width=6)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _images(pdf_bytes):
    """Nombre d'images XObject par page."""
    r = PdfReader(io.BytesIO(pdf_bytes))
    out = []
    for p in r.pages:
        xo = p.get('/Resources', {}).get('/XObject', {}) or {}
        out.append(sum(1 for k in xo if xo[k].get_object().get('/Subtype') == '/Image'))
    return out


def _patient():
    return _Permissif(nom='DUPONT', prenom='Afi', telephone='90000000', numero_assure='123456789012', date_naissance=date(1980, 1, 1))


def _medecin():
    return _Permissif(nom='KOFFI', prenom='Jean', code_prescripteur='P123', telephone='91000000')


def _ep(type_amu):
    return _Permissif(type_amu=type_amu, inclure_actes=True, inclure_produits=False, inclure_hospitalisation=False,
                      lignes_motif=[{'type': 'acte', 'nom': 'Scanner', 'motif': 'Douleur'}],
                      numero_feuille_soins='', date_prescription=date(2026, 10, 6))


@pytest.mark.parametrize('type_amu', ['amu_cnss', 'amu_inam'])
def test_signature_apposee_sur_entente_prealable(type_amu):
    sans = remplir_entente_prealable(_ep(type_amu), _patient(), _medecin(), 'FS001')
    avec = remplir_entente_prealable(_ep(type_amu), _patient(), _medecin(), 'FS001', signature=(_png(), 'image/png'))
    assert _images(sans)[0] == _images_de_base(sans)
    assert _images(avec)[0] == _images(sans)[0] + 1


def _images_de_base(pdf_bytes):
    return _images(pdf_bytes)[0]


def _tpc(type_amu, type_demande):
    return _Permissif(type_amu=type_amu, type_demande=type_demande, date_prescription=date(2026, 10, 6),
                      traitements=[], affections_ald=[], examens_paracliniques=[], resultats_examens_effectues='',
                      motif_modification='', numero_ancien_tpc='', ville_residence='', traitement_a_renouveler=None)


@pytest.mark.parametrize('type_amu, type_demande', [
    ('amu_cnss', 'renouvellement'), ('amu_cnss', 'modification'), ('amu_inam', 'rectification'),
])
def test_signature_apposee_sur_tpc(type_amu, type_demande):
    sans = remplir_tpc(_tpc(type_amu, type_demande), _patient(), _medecin(), 'FS001')
    avec = remplir_tpc(_tpc(type_amu, type_demande), _patient(), _medecin(), 'FS001', signature=(_png(), 'image/png'))
    assert _images(avec)[0] == _images(sans)[0] + 1


def test_signature_illisible_ignoree():
    """Une image corrompue ne doit jamais faire échouer l'impression."""
    pdf = remplir_entente_prealable(_ep('amu_cnss'), _patient(), _medecin(), 'FS001', signature=(b'pas une image', 'image/png'))
    assert _images(pdf)[0] == _images(remplir_entente_prealable(_ep('amu_cnss'), _patient(), _medecin(), 'FS001'))[0]
