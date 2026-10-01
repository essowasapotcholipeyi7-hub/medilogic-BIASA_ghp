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
from reportlab.pdfbase.pdfmetrics import stringWidth

AMU_CNSS_PDF = 'static/documents/amu_cnss/demande_entente_prealable.pdf'
AMU_INAM_PDF = 'static/documents/amu_inam/demande_entente_prealable.pdf'

FONT = 'Helvetica'
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


def _texte_precision_inam(c, hauteur, valeur, taille=9):
    """Champ "Si non, catégorie attribuée (préciser) :" du gabarit INAM —
    DEUX lignes de pointillés disponibles : une courte juste après le
    label sur sa propre ligne (x=372-472, y=717-727) et une complète juste
    en dessous (x=321-471, y=731-741). On préfère écrire sur la ligne
    complète SEULE (plus de place, rendu plus propre) ; seulement si ça ne
    suffit toujours pas au plancher de police, on utilise les deux lignes
    : début sur la courte, suite sur la complète — jamais les deux en même
    temps sur une coordonnée qui n'appartient à aucune des deux (c'était le
    bug : x de la ligne complète + y de la ligne courte, le texte flottait
    entre les deux pointillés au lieu de reposer dessus)."""
    if not valeur:
        return
    ligne_longue = (321, 739, 150)
    ligne_courte = (372, 725, 100)
    tient, _taille = _ajuster_pour_largeur(valeur, ligne_longue[2], taille)
    if tient == valeur:
        _texte(c, hauteur, ligne_longue[0], ligne_longue[1], valeur, taille=taille, largeur_max=ligne_longue[2])
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


def remplir_ep_cnss(demande, patient, medecin, code_formation_sanitaire):
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
        _texte(c, h, 95, 118, patient.numero_assure or '', largeur_max=390)
        _texte(c, h, 132, 139, nom_complet, largeur_max=220)
        _texte(c, h, 430, 139, patient.telephone or '', largeur_max=130)

        _texte(c, h, 180, 182.5, code_formation_sanitaire or '', largeur_max=115)
        _texte(c, h, 419, 181, medecin.code_prescripteur or '', largeur_max=140)
        _texte(c, h, 97, 206, medecin.telephone or '', largeur_max=140)
        d = demande.date_prescription or date.today()
        _texte(c, h, 384, 206, d.strftime('%d/%m'), largeur_max=35)
        _texte(c, h, 463, 206, str(d.year)[-2:], largeur_max=25)

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
                _texte(c, h, 212, 719, demande.hospit_categorie_autre_precision or '', taille=9, largeur_max=80)

    page1.merge_page(_overlay(largeur, hauteur, dessiner))

    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_ep_inam(demande, patient, medecin, code_formation_sanitaire):
    """Même principe que remplir_ep_cnss, pour le gabarit INAM (1 page,
    libellés et pointillés sur deux lignes distinctes — voir calibrage)."""
    reader = PdfReader(AMU_INAM_PDF)
    page1 = reader.pages[0]
    largeur, hauteur = float(page1.mediabox.width), float(page1.mediabox.height)

    actes = _lignes_par_type(demande.lignes_motif, 'acte')[:3]
    produits = _lignes_par_type(demande.lignes_motif, 'produit')[:3]

    def dessiner(c, h):
        _texte(c, h, 44, 157, patient.nom or '', largeur_max=235)
        _texte(c, h, 44, 194, patient.prenom or '', largeur_max=235)
        _texte(c, h, 44, 231, patient.numero_assure or '', largeur_max=235)
        _texte(c, h, 44, 267, demande.numero_feuille_soins or '', largeur_max=235)

        _texte(c, h, 321, 157, code_formation_sanitaire or '', largeur_max=215)
        _texte(c, h, 321, 194, medecin.code_prescripteur or '', largeur_max=215)
        _texte(c, h, 321, 231, medecin.telephone or '', largeur_max=215)
        d = demande.date_prescription or date.today()
        _texte(c, h, 321, 267, d.strftime('%d/%m/%Y'), largeur_max=215)

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

    page1.merge_page(_overlay(largeur, hauteur, dessiner))

    writer = PdfWriter()
    writer.add_page(page1)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_entente_prealable(demande, patient, medecin, code_formation_sanitaire):
    """Point d'entrée unique — choisit le bon gabarit selon type_amu.
    'amu_cnss' et 'amu_tns' partagent le gabarit CNSS (même administration,
    confirmé par le patron)."""
    if demande.type_amu == 'amu_inam':
        return remplir_ep_inam(demande, patient, medecin, code_formation_sanitaire)
    return remplir_ep_cnss(demande, patient, medecin, code_formation_sanitaire)
