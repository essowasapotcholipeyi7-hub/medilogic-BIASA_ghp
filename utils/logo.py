# -*- coding: utf-8 -*-
"""⭐ Logo de la structure téléversé depuis l'application (patron, 2026-10-09 :
« que chaque structure puisse uploader son logo depuis son interface avec
un recadrage automatique peu importe la taille de la photo, bien propre,
bien lisible »).

nettoyer_logo(octets) :
  1. orientation EXIF corrigée, conversion RGBA ;
  2. fond extérieur (blanc, couleur unie, ou déjà transparent) rendu
     transparent par remplissage depuis les 4 coins (tolérance) — les zones
     de même couleur À L'INTÉRIEUR du logo sont conservées ;
  3. recadrage automatique sur le contenu (+ petite marge) ;
  4. réduction à 512 px maximum (sans jamais agrandir), PNG.
Retourne (png_bytes, largeur, hauteur). Pur PIL, testable sans base.
"""
import io

from PIL import Image, ImageChops, ImageDraw, ImageOps

TAILLE_MAX = 512
TOLERANCE_FOND = 48      # distance RGB max pour être considéré « fond »
MARGE = 0.03             # 3 % de marge autour du contenu recadré
FORMATS_ACCEPTES = {'PNG', 'JPEG', 'GIF', 'BMP', 'WEBP', 'TIFF', 'ICO'}


def _distance(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _couleur_fond(img):
    """Couleur de fond probable = coin le plus fréquent (pixels opaques)."""
    w, h = img.size
    coins = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)), img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))]
    opaques = [c[:3] for c in coins if c[3] > 0]
    if not opaques:
        return None
    # majorité : couleur la plus proche des autres
    meilleur, score = opaques[0], 10 ** 9
    for c in opaques:
        s = sum(_distance(c, d) for d in opaques)
        if s < score:
            meilleur, score = c, s
    return meilleur


def nettoyer_logo(octets, taille_max=TAILLE_MAX):
    img = Image.open(io.BytesIO(octets))
    if (img.format or '').upper() not in FORMATS_ACCEPTES and img.format is not None:
        raise ValueError(f"Format d'image non pris en charge ({img.format}). Utilisez PNG, JPG, GIF, BMP ou WEBP.")
    img = ImageOps.exif_transpose(img)
    if getattr(img, 'n_frames', 1) > 1:
        img.seek(0)
    img = img.convert('RGBA')
    w, h = img.size
    if w < 8 or h < 8:
        raise ValueError('Image trop petite.')

    fond = _couleur_fond(img)
    if fond is not None and (img.getchannel('A').getextrema()[0] == 255):
        # Fond opaque : rendre transparent tout ce qui est relié aux bords et
        # de couleur proche du fond (remplissage par les 4 coins).
        marqueur = Image.new('RGB', (w, h))
        marqueur.paste(img.convert('RGB'))
        sentinelle = (254, 0, 254) if _distance(fond, (254, 0, 254)) > TOLERANCE_FOND else (0, 254, 0)
        for coin in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if _distance(marqueur.getpixel(coin), fond) <= TOLERANCE_FOND:
                ImageDraw.floodfill(marqueur, coin, sentinelle, thresh=TOLERANCE_FOND)
        # pixels == sentinelle -> alpha 0
        r, g, b = marqueur.split()
        est_sentinelle = Image.eval(r, lambda v: 255 if v == sentinelle[0] else 0)
        est_sentinelle_g = Image.eval(g, lambda v: 255 if v == sentinelle[1] else 0)
        est_sentinelle_b = Image.eval(b, lambda v: 255 if v == sentinelle[2] else 0)
        masque = ImageChops.multiply(ImageChops.multiply(est_sentinelle, est_sentinelle_g), est_sentinelle_b)
        alpha = img.getchannel('A')
        alpha = ImageChops.subtract(alpha, masque)
        img.putalpha(alpha)

    # Recadrage sur le contenu visible
    bbox = img.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:
        raise ValueError("L'image semble vide (ou entièrement de la couleur du fond).")
    x0, y0, x1, y1 = bbox
    mx, my = int((x1 - x0) * MARGE), int((y1 - y0) * MARGE)
    img = img.crop((max(0, x0 - mx), max(0, y0 - my), min(w, x1 + mx), min(h, y1 + my)))

    # Réduction (jamais d'agrandissement)
    img.thumbnail((taille_max, taille_max), Image.LANCZOS)
    sortie = io.BytesIO()
    img.save(sortie, format='PNG', optimize=True)
    return sortie.getvalue(), img.size[0], img.size[1]
