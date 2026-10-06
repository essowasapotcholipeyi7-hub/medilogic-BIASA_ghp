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


def test_recadrage_photo_grande_avec_marges():
    """Une grande photo où la signature n'occupe qu'un coin est recadrée sur
    l'encre, le papier devient transparent (patron : "même si la photo est
    grande, que ça puisse recadrer pour tenir en lieu et place prévu")."""
    from utils.remplissage_pdf_amu import preparer_image_signature
    photo = Image.new('RGB', (2400, 1800), (236, 233, 228))  # papier légèrement gris (photo)
    ImageDraw.Draw(photo).line([(300, 1500), (500, 1300), (700, 1520), (900, 1350)], fill=(25, 25, 90), width=14)
    buf = io.BytesIO()
    photo.save(buf, format='JPEG', quality=85)
    sortie = preparer_image_signature(buf.getvalue())
    assert sortie
    img = Image.open(io.BytesIO(sortie))
    assert img.mode == 'RGBA'
    # recadrée sur la signature (environ 600 x 220 px après réduction à 1600 px de large)
    assert img.width < 700 and img.height < 300
    # papier transparent, encre opaque
    alpha = img.getchannel('A')
    assert alpha.getpixel((2, 2)) == 0
    assert alpha.getextrema()[1] == 255


def test_nom_du_medecin_sous_la_signature():
    """Le nom du prescripteur est écrit sous l'image (texte présent dans la page)."""
    pdf = remplir_entente_prealable(_ep('amu_cnss'), _patient(), _medecin(), 'FS001', signature=(_png(), 'image/png'))
    texte = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert 'KOFFI' in texte and 'Jean' in texte
