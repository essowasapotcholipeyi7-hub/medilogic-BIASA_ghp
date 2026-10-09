"""Logo téléversé : recadrage automatique, fond nettoyé, réduction (patron, 2026-10-09)."""
import io

import pytest
from PIL import Image, ImageDraw

from utils.logo import nettoyer_logo


def _image(w, h, fond, dessin, fmt='PNG'):
    img = Image.new('RGB', (w, h), fond)
    d = ImageDraw.Draw(img)
    dessin(d)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_recadrage_et_fond_transparent():
    # grande photo 1600x900 à fond blanc, logo bleu (disque) avec un coeur blanc à l'intérieur, grandes marges
    octets = _image(1600, 900, 'white', lambda d: (d.ellipse((500, 200, 1100, 700), fill=(20, 90, 200)), d.ellipse((750, 400, 850, 500), fill='white')), 'JPEG')
    png, w, h = nettoyer_logo(octets)
    img = Image.open(io.BytesIO(png))
    assert img.format == 'PNG' and max(w, h) <= 512
    assert abs(w / h - 1.2) < 0.05        # recadré sur le disque (600x500), marges blanches supprimées
    assert img.getpixel((0, 0))[3] == 0    # coin : fond devenu transparent
    cx, cy = w // 2, h // 2
    assert img.getpixel((cx, cy))[3] == 255 and img.getpixel((cx, cy))[:3] == (255, 255, 255)   # blanc INTÉRIEUR conservé
    assert img.getpixel((cx, int(h * 0.15)))[:3][2] > 150   # bleu du disque


def test_petit_logo_jamais_agrandi_et_png_transparent_conserve():
    img = Image.new('RGBA', (120, 60), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((10, 10, 110, 50), fill=(200, 30, 30, 255))
    buf = io.BytesIO(); img.save(buf, format='PNG')
    png, w, h = nettoyer_logo(buf.getvalue())
    assert w <= 110 and h <= 50 and w > 90       # recadré sur le rectangle, pas agrandi
    assert Image.open(io.BytesIO(png)).getpixel((w // 2, h // 2))[:3] == (200, 30, 30)


def test_image_vide_refusee():
    with pytest.raises(ValueError):
        nettoyer_logo(_image(300, 300, 'white', lambda d: None))
