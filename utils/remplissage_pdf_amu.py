# ⭐ Remplissage de l'Entente Préalable AMU par superposition de texte sur
# le PDF officiel — JAMAIS de modification du fichier source (patron,
# répété plusieurs fois : "il ne faut jamais modifier la structure des
# fiches jamais"). Les PDF (static/documents/amu_{cnss,inam}/...) sont
# plats, pas de champs AcroForm (vérifié via pypdf.get_fields() = vide) :
# on dessine le texte aux coordonnées calibrées avec pdfplumber
# (extract_words()/rects, origine en HAUT à gauche) sur un calque
# transparent (reportlab, origine en BAS à gauche — d'où la conversion
# y_pdf = hauteur_page - y_pdfplumber dans chaque fonction ci-dessous),
# puis on fusionne ce calque sur la page d'origine (pypdf merge_page) : le
# fichier sur disque n'est jamais rouvert en écriture.
#
# La fiche a 3 tableaux indépendants — Actes, Médicaments/Produits,
# Hospitalisation — chacun rempli seulement si sa case "inclure_*" est
# cochée (patron : "il peut arriver qu'on demande les trois en même
# temps"). Calibrage initial au mot-clé/rectangle le plus proche sur le
# rendu réel du PDF (page.to_image() de pdfplumber) — un petit ajustement
# pixel-près reste possible en pratique, voir plan de session.

import io
from datetime import date

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

AMU_CNSS_PDF = 'static/documents/amu_cnss/demande_entente_prealable.pdf'
AMU_INAM_PDF = 'static/documents/amu_inam/demande_entente_prealable.pdf'

FONT = 'Helvetica-Bold'  # ⭐ gras — patron : "je veux que le texte saisi soit
                         # affiché en gras pour mettre la différence avec le
                         # texte existant [imprimé sur la fiche]".
FONT_SIZE = 11      # ⭐ augmenté (était 10) — patron : "augmente un peu la
                     # police du texte pour que ça soit même chose que ce
                     # qui est sur la fiche déjà".
FONT_SIZE_TABLE = 10  # était 8 — tableaux Actes/Médicaments/Hospitalisation
FONT_SIZE_MIN = 6     # ⭐ plancher en-dessous duquel on tronque plutôt que
                       # de continuer à rapetisser (devient illisible).


def _overlay(largeur, hauteur, dessiner):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(largeur, hauteur))
    c.setFont(FONT, FONT_SIZE)
    c.setFillColor(black)
    dessiner(c, hauteur)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def preparer_image_signature(data):
    """⭐ Recadre la photo/scan de signature sur l'encre seule et rend le fond
    blanc transparent (patron, 2026-10-06 : "même si la photo de la
    signature est grande, que ça puisse recadrer pour tenir en lieu et
    place prévu"). Une photo A4 où la signature n'occupe qu'un coin donne
    ainsi une signature pleine case, et les lignes de la fiche restent
    visibles autour. Retourne des octets PNG, ou None si illisible."""
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert('RGBA')
        # Photo très grande : réduite d'abord (poids du PDF, vitesse)
        if max(img.size) > 1600:
            img.thumbnail((1600, 1600))
        # Aplatie sur blanc (un PNG déjà transparent garde son rendu)
        fond = Image.new('RGBA', img.size, (255, 255, 255, 255))
        fond.alpha_composite(img)
        gris = ImageOps.grayscale(fond)
        # Encre = pixels nettement plus sombres que le papier (photo : papier
        # gris clair, ombres légères) — seuil adaptatif sur le fond réel.
        histogramme = gris.histogram()
        total = sum(histogramme)
        cumul = 0
        fond_niveau = 255
        for niveau in range(255, -1, -1):  # niveau du papier = clair majoritaire
            cumul += histogramme[niveau]
            if cumul > total * 0.5:
                fond_niveau = niveau
                break
        seuil = max(60, min(200, fond_niveau - 45))
        encre = gris.point(lambda v, s=seuil: 255 if v < s else 0)
        boite = encre.getbbox()
        if not boite:
            return None
        marge_x = max(4, (boite[2] - boite[0]) // 25)
        marge_y = max(4, (boite[3] - boite[1]) // 25)
        boite = (max(0, boite[0] - marge_x), max(0, boite[1] - marge_y),
                 min(fond.width, boite[2] + marge_x), min(fond.height, boite[3] + marge_y))
        fond = fond.crop(boite)
        gris = gris.crop(boite)
        # Fond transparent : opacité proportionnelle à la noirceur (traits
        # fins conservés, papier effacé) — bornes : papier -> 0, encre -> 255
        bas, haut = seuil, max(seuil - 70, 0)
        alpha = gris.point(lambda v, b=bas, h=haut: 0 if v >= b else (255 if v <= h else int(255 * (b - v) / (b - h))))
        fond.putalpha(alpha)
        sortie = io.BytesIO()
        fond.save(sortie, format='PNG')
        return sortie.getvalue()
    except Exception:
        return None


def _nom_medecin(medecin):
    """« Dr NOM Prénom » — via get_nom_complet() quand c'est un vrai Medecin,
    sinon reconstruit depuis titre/nom/prénom (objets de test)."""
    if medecin is None:
        return ''
    fonction = getattr(medecin, 'get_nom_complet', None)
    if callable(fonction):
        try:
            valeur = fonction()
            if valeur:
                return str(valeur)
        except Exception:
            pass
    morceaux = [getattr(medecin, 'titre', None) or 'Dr', getattr(medecin, 'nom', None) or '', getattr(medecin, 'prenom', None) or '']
    return ' '.join(m for m in morceaux if m).strip()


def _signature(c, hauteur, x0, x1, top0, top1, signature, nom_medecin=None):
    """⭐ Appose l'image de signature pré-enregistrée du prescripteur (page
    Signatures électroniques, filière 'prescripteur') dans la zone
    « Signature et cachet » de la fiche — patron, 2026-10-06 — avec le NOM
    du médecin écrit dessous. `signature` : (bytes, mime) ou bytes, ou None
    (rien n'est dessiné). L'image est d'abord recadrée sur l'encre
    (preparer_image_signature), puis mise à l'échelle, proportions
    conservées, centrée dans la boîte [x0, x1] x [top0, top1] (tops mesurés
    depuis le haut de la page, comme _texte). Jamais bloquant : une image
    illisible est ignorée plutôt que de faire échouer l'impression."""
    if not signature:
        return
    data = signature[0] if isinstance(signature, (tuple, list)) else signature
    prepare = preparer_image_signature(data)
    try:
        image = ImageReader(io.BytesIO(prepare or data))
        largeur_img, hauteur_img = image.getSize()
    except Exception:
        return
    if not largeur_img or not hauteur_img:
        return
    boite_l, boite_h = x1 - x0, top1 - top0
    taille_nom = 8
    hauteur_nom = taille_nom + 3 if nom_medecin else 0
    zone_h = boite_h - hauteur_nom
    ratio = min(boite_l / largeur_img, zone_h / hauteur_img)
    l, h_img = largeur_img * ratio, hauteur_img * ratio
    x = x0 + (boite_l - l) / 2
    y = hauteur - top0 - zone_h + (zone_h - h_img) / 2
    c.drawImage(image, x, y, width=l, height=h_img, mask='auto')
    if nom_medecin:
        c.setFont(FONT, taille_nom)
        c.drawCentredString((x0 + x1) / 2, hauteur - top1 + 2, nom_medecin)
        c.setFont(FONT, FONT_SIZE)


def _ajuster_pour_largeur(valeur, largeur_max, taille_base):
    """⭐ Sans ça, une valeur plus longue que prévu (nom composé, libellé
    d'acte/produit tiré du tableau tarifaire, texte libre saisi à la main)
    déborde purement et simplement par-dessus le reste de la fiche — vécu
    en prod (patron : "le texte ne reste pas bien", une valeur chiffrée de
    test qui débordait sur toute la largeur de la page). Rétrécit la
    police par pas de 0.5pt jusqu'à FONT_SIZE_MIN ; si ça ne suffit
    toujours pas, tronque avec une ellipse plutôt que de déborder."""
    if not largeur_max or not valeur:
        return valeur, taille_base
    taille = taille_base
    while taille > FONT_SIZE_MIN and stringWidth(valeur, FONT, taille) > largeur_max:
        taille -= 0.5
    if stringWidth(valeur, FONT, taille) <= largeur_max:
        return valeur, taille
    # Toujours trop large même au plancher : tronque avec "…"
    tronque = valeur
    while tronque and stringWidth(tronque + '…', FONT, taille) > largeur_max:
        tronque = tronque[:-1]
    return (tronque + '…' if tronque else valeur[:1]), taille


def _texte(c, hauteur, x, top, valeur, taille=None, largeur_max=None):
    """Écrit `valeur` avec son coin bas-gauche à (x, top) en coordonnées
    pdfplumber (top = distance depuis le HAUT de la page). Si `largeur_max`
    est fourni, la police rétrécit (puis tronque en dernier recours) pour
    ne jamais déborder de sa colonne/case — voir _ajuster_pour_largeur."""
    if not valeur:
        return
    taille_effective = taille or FONT_SIZE
    valeur, taille_effective = _ajuster_pour_largeur(str(valeur), largeur_max, taille_effective)
    c.setFont(FONT, taille_effective)
    c.drawString(x, hauteur - top, valeur)
    c.setFont(FONT, FONT_SIZE)


def _texte_centree(c, hauteur, x0, x1, top, valeur, taille=None):
    """Comme _texte, mais centre `valeur` dans la case [x0, x1] au lieu de
    partir d'un coin gauche fixe — utilisé pour les cases jour/mois/année
    de la "Date de la prescription" (gabarit CNSS), qui a déjà ses propres
    barres obliques imprimées : on ne dessine jamais de "/" nous-mêmes,
    seulement les chiffres à l'intérieur de chaque case."""
    if not valeur:
        return
    taille_effective = taille or FONT_SIZE
    valeur, taille_effective = _ajuster_pour_largeur(str(valeur), x1 - x0, taille_effective)
    largeur_texte = stringWidth(valeur, FONT, taille_effective)
    c.setFont(FONT, taille_effective)
    c.drawString(x0 + max(0, (x1 - x0 - largeur_texte) / 2), hauteur - top, valeur)
    c.setFont(FONT, FONT_SIZE)


def _texte_cases(c, hauteur, top, cases, valeur, taille=10):
    """⭐ N° AMU / Code formation sanitaire / Code prescripteur (gabarit
    CNSS) sont imprimés en cases séparées par des "/" (ex:
    "/..../..../..../"). Écrire la valeur comme une suite continue (ancien
    code) la fait traverser ces barres imprimées — vécu en prod (patron :
    "on a mis des slash à l'endroit où il faut saisir, fait en sorte que
    ça respecte ça"). On écrit donc un caractère par case, centré dans la
    zone pointillée de chaque case, jamais par-dessus un "/" imprimé.
    `cases` : liste ordonnée de (x_debut, x_fin) de chaque case."""
    if not valeur:
        return
    c.setFont(FONT, taille)
    y = hauteur - top
    for ch, (x0, x1) in zip(str(valeur), cases):
        if ch == ' ':
            continue
        largeur_car = stringWidth(ch, FONT, taille)
        c.drawString(x0 + max(0, (x1 - x0 - largeur_car) / 2), y, ch)
    c.setFont(FONT, FONT_SIZE)


def _texte_precision_inam(c, hauteur, valeur, taille=9):
    """Champ "Si non, catégorie attribuée (préciser) :" du gabarit INAM —
    DEUX lignes de pointillés disponibles : une courte juste après le
    label, sur la MÊME ligne que lui (x=372-472, y=717-727) et une
    complète juste en dessous (x=321-471, y=731-741). Patron : le texte
    saisi doit commencer à la suite du ":" sur la même ligne que le
    label — donc on écrit d'abord sur la ligne courte ; seulement si la
    valeur ne tient pas entière dessus, on déborde sur la ligne complète
    en dessous (début sur la courte, suite sur la complète) — jamais les
    deux en même temps sur une coordonnée qui n'appartient à aucune des
    deux (c'était le bug initial : x de la ligne complète + y de la ligne
    courte, le texte flottait entre les deux pointillés au lieu de
    reposer dessus)."""
    if not valeur:
        return
    ligne_longue = (321, 739, 150)
    ligne_courte = (372, 725, 100)
    tient, _taille = _ajuster_pour_largeur(valeur, ligne_courte[2], taille)
    if tient == valeur:
        _texte(c, hauteur, ligne_courte[0], ligne_courte[1], valeur, taille=taille, largeur_max=ligne_courte[2])
        return
    mots = valeur.split(' ')
    ligne1 = ''
    i = 0
    while i < len(mots) and stringWidth((ligne1 + ' ' + mots[i]).strip(), FONT, taille) <= ligne_courte[2]:
        ligne1 = (ligne1 + ' ' + mots[i]).strip()
        i += 1
    if not ligne1:
        ligne1 = mots[0]
        i = 1
    reste = ' '.join(mots[i:])
    _texte(c, hauteur, ligne_courte[0], ligne_courte[1], ligne1, taille=taille, largeur_max=ligne_courte[2])
    _texte(c, hauteur, ligne_longue[0], ligne_longue[1], reste, taille=taille, largeur_max=ligne_longue[2])


def _coche(c, hauteur, x0, x1, top0, top1):
    """Dessine une croix à l'intérieur d'une case à cocher rectangulaire
    (coordonnées pdfplumber calibrées sur le rect réel de la case)."""
    y0 = hauteur - top1
    y1 = hauteur - top0
    marge = 1.5
    c.setLineWidth(1.2)
    c.line(x0 + marge, y0 + marge, x1 - marge, y1 - marge)
    c.line(x0 + marge, y1 - marge, x1 - marge, y0 + marge)


def _lignes_par_type(lignes, type_):
    return [l for l in (lignes or []) if l.get('type') == type_]


def _ligne_nom(l):
    return (l or {}).get('nom', '')


def _ligne_motif(l):
    return (l or {}).get('motif', '')


# ⭐ Cases séparées par des "/" imprimés sur le gabarit CNSS — une case par
# caractère, jamais une suite continue qui traverserait un "/" (voir
# _texte_cases). Calibrées sur le PDF original (pdfplumber, chars()).
CNSS_CASES_NUMERO_AMU = [
    (95, 109), (113, 126), (130, 144), (148, 161), (165, 178), (182, 196), (200, 213),  # 1er groupe (7 cases)
    (255, 268), (272, 285), (289, 303), (307, 320), (324, 338), (341, 355), (359, 372), (376, 393), (397, 410), (414, 428),  # 2e groupe (10 cases, si N° AMU plus long)
]
CNSS_CASES_CODE_FORMATION_SANITAIRE = [(180, 194), (197, 211), (215, 228), (232, 246), (250, 263), (267, 280)]
CNSS_CASES_CODE_PRESCRIPTEUR = [(419, 433), (437, 450), (454, 468), (471, 485), (489, 502), (506, 520), (523, 540)]
# Case "Date de la prescription" : jour / mois / "20"+année déjà imprimés
# avec leurs propres "/" — on ne dessine que les chiffres, dans la case.
CNSS_ZONE_JOUR = (381, 404)
CNSS_ZONE_MOIS = (409, 439)
CNSS_ZONE_ANNEE = (457, 473)


def remplir_ep_cnss(demande, patient, medecin, code_formation_sanitaire, signature=None):
    """demande: DemandeEntentePrealable ; patient: Patient ; medecin: Medecin.
    Retourne les bytes du PDF (2 pages, page 2 = encart contact imprimé
    tel quel, jamais modifié)."""
    reader = PdfReader(AMU_CNSS_PDF)
    page1 = reader.pages[0]
    largeur, hauteur = float(page1.mediabox.width), float(page1.mediabox.height)

    actes = _lignes_par_type(demande.lignes_motif, 'acte')[:3]
    produits = _lignes_par_type(demande.lignes_motif, 'produit')[:4]

    def dessiner(c, h):
        nom_complet = f"{patient.nom} {patient.prenom}".strip()
        _texte_cases(c, h, 116.5, CNSS_CASES_NUMERO_AMU, patient.numero_assure or '')
        # ⭐ Légèrement décollé des pointillés (patron) — baseline relevée
        # d'un cran de plus que la ligne imprimée.
        _texte(c, h, 132, 137, nom_complet, largeur_max=220)
        _texte(c, h, 430, 137, patient.telephone or '', largeur_max=130)

        _texte_cases(c, h, 180.5, CNSS_CASES_CODE_FORMATION_SANITAIRE, code_formation_sanitaire or '')
        _texte_cases(c, h, 179, CNSS_CASES_CODE_PRESCRIPTEUR, medecin.code_prescripteur or '')
        _texte(c, h, 97, 204, medecin.telephone or '', largeur_max=140)
        d = demande.date_prescription or date.today()
        _texte_centree(c, h, *CNSS_ZONE_JOUR, 204, d.strftime('%d'), taille=FONT_SIZE_TABLE)
        _texte_centree(c, h, *CNSS_ZONE_MOIS, 204, d.strftime('%m'), taille=FONT_SIZE_TABLE)
        _texte_centree(c, h, *CNSS_ZONE_ANNEE, 204, str(d.year)[-2:], taille=FONT_SIZE_TABLE)

        # Tableau "Actes" — N°(27.5-50.2) | Acte(50.2-198.3) | Motif(198.3-361.0)
        if demande.inclure_actes:
            y_rows = [291, 320.5, 346.5]
            for ligne, y in zip(actes, y_rows):
                _texte(c, h, 55, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE, largeur_max=140)
                _texte(c, h, 203, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE, largeur_max=155)

        # Tableau "Médicament et assimilé" — N°(27-55.6) | Médicament(55.6-213.8) | Motif(213.8-418.8)
        if demande.inclure_produits:
            y_rows = [423.5, 450.5, 480.9, 503.4]
            for ligne, y in zip(produits, y_rows):
                _texte(c, h, 60, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE, largeur_max=150)
                _texte(c, h, 218, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE, largeur_max=195)

        # Tableau "Hospitalisation" — colonnes : Date admission(26.5-77.2) |
        # Motif(77.2-203.3) | Catégorie de salle(203.3-324.1, checkboxes
        # Oui/Non) | Durée séjour(324.1-380.0)
        if demande.inclure_hospitalisation:
            if demande.hospit_date_admission:
                _texte(c, h, 29, 615, demande.hospit_date_admission.strftime('%d/%m/%Y'), taille=FONT_SIZE_TABLE, largeur_max=45)
            _texte(c, h, 80, 615, demande.hospit_motif or '', taille=FONT_SIZE_TABLE, largeur_max=120)
            _texte(c, h, 327, 615, demande.hospit_duree_sejour or '', taille=FONT_SIZE_TABLE, largeur_max=50)
            if demande.hospit_categorie_salle == 'cabine_ventilee':
                _coche(c, h, 230.2, 243.5, 645.5, 655.6)  # case "Oui"
            elif demande.hospit_categorie_salle == 'autre':
                _coche(c, h, 230.2, 243.5, 659.4, 669.5)  # case "Non"
                # ⭐ Une seule ligne de pointillés disponible ici (contrairement
                # à l'INAM qui en a deux) : rétrécit/tronque, pas de retour
                # à la ligne possible.
                _texte(c, h, 212, 717, demande.hospit_categorie_autre_precision or '', taille=9, largeur_max=80)

        # Signature du prescripteur : sous « Signature cachet prescripteur » (bas droit)
        _signature(c, h, 350, 560, 771, 838, signature, _nom_medecin(medecin))

    page1.merge_page(_overlay(largeur, hauteur, dessiner))

    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_ep_inam(demande, patient, medecin, code_formation_sanitaire, signature=None):
    """Même principe que remplir_ep_cnss, pour le gabarit INAM (1 page,
    libellés et pointillés sur deux lignes distinctes — voir calibrage)."""
    reader = PdfReader(AMU_INAM_PDF)
    page1 = reader.pages[0]
    largeur, hauteur = float(page1.mediabox.width), float(page1.mediabox.height)

    actes = _lignes_par_type(demande.lignes_motif, 'acte')[:3]
    produits = _lignes_par_type(demande.lignes_motif, 'produit')[:3]

    # ⭐ Patron : le texte saisi doit commencer à la suite des ":" sur la
    # MÊME ligne que le label (et non sur la ligne de pointillés séparée
    # juste en dessous, qui reste alors vide/non utilisée).
    def dessiner(c, h):
        _texte(c, h, 72, 149.5, patient.nom or '', largeur_max=220)
        _texte(c, h, 90, 186, patient.prenom or '', largeur_max=200)
        _texte(c, h, 124, 223, patient.numero_assure or '', largeur_max=165)
        _texte(c, h, 137, 260, demande.numero_feuille_soins or '', largeur_max=150)

        _texte(c, h, 446, 149.5, code_formation_sanitaire or '', largeur_max=95)
        _texte(c, h, 414, 186, medecin.code_prescripteur or '', largeur_max=125)
        _texte(c, h, 414, 223, medecin.telephone or '', largeur_max=125)
        d = demande.date_prescription or date.today()
        _texte(c, h, 437, 260, d.strftime('%d/%m/%Y'), largeur_max=100)

        # Tableau "Actes" — N°(35.3-63.6) | Actes(63.6-311.7) | Motifs(311.7-559.8)
        if demande.inclure_actes:
            y_rows = [333, 365, 396]
            for ligne, y in zip(actes, y_rows):
                _texte(c, h, 68, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE, largeur_max=235)
                _texte(c, h, 316, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE, largeur_max=235)

        # Tableau "Produits pharmaceutiques" — mêmes colonnes que Actes
        if demande.inclure_produits:
            y_rows = [477, 508, 539]
            for ligne, y in zip(produits, y_rows):
                _texte(c, h, 68, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE, largeur_max=235)
                _texte(c, h, 316, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE, largeur_max=235)

        # Tableau "Hospitalisation" — Date admission(35.3-113.3) |
        # Motifs(113.3-297.6) | Catégorie de salle(297.6-481.9, checkboxes
        # Oui/Non) | Durée séjour(481.9-559.8)
        if demande.inclure_hospitalisation:
            if demande.hospit_date_admission:
                _texte(c, h, 38, 650, demande.hospit_date_admission.strftime('%d/%m/%Y'), taille=FONT_SIZE_TABLE, largeur_max=72)
            _texte(c, h, 118, 650, demande.hospit_motif or '', taille=FONT_SIZE_TABLE, largeur_max=175)
            _texte(c, h, 487, 650, demande.hospit_duree_sejour or '', taille=FONT_SIZE_TABLE, largeur_max=68)
            if demande.hospit_categorie_salle == 'cabine_ventilee':
                _coche(c, h, 344.9, 357.9, 678.6, 688.4)  # case "Oui"
            elif demande.hospit_categorie_salle == 'autre':
                _coche(c, h, 396.2, 409.2, 679.7, 689.5)  # case "Non"
                _texte_precision_inam(c, h, demande.hospit_categorie_autre_precision or '')

        # Signature du prescripteur : sous « Signature et cachet du prescripteur » (bas droit)
        _signature(c, h, 372, 565, 772, 838, signature, _nom_medecin(medecin))

    page1.merge_page(_overlay(largeur, hauteur, dessiner))

    writer = PdfWriter()
    writer.add_page(page1)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_entente_prealable(demande, patient, medecin, code_formation_sanitaire, signature=None):
    """Point d'entrée unique — choisit le bon gabarit selon type_amu.
    'amu_cnss' et 'amu_tns' partagent le gabarit CNSS (même administration,
    confirmé par le patron)."""
    if demande.type_amu == 'amu_inam':
        return remplir_ep_inam(demande, patient, medecin, code_formation_sanitaire, signature=signature)
    return remplir_ep_cnss(demande, patient, medecin, code_formation_sanitaire, signature=signature)
