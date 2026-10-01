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

AMU_CNSS_PDF = 'static/documents/amu_cnss/demande_entente_prealable.pdf'
AMU_INAM_PDF = 'static/documents/amu_inam/demande_entente_prealable.pdf'

FONT = 'Helvetica'
FONT_SIZE = 11      # ⭐ augmenté (était 10) — patron : "augmente un peu la
                     # police du texte pour que ça soit même chose que ce
                     # qui est sur la fiche déjà".
FONT_SIZE_TABLE = 10  # était 8 — tableaux Actes/Médicaments/Hospitalisation


def _overlay(largeur, hauteur, dessiner):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(largeur, hauteur))
    c.setFont(FONT, FONT_SIZE)
    c.setFillColor(black)
    dessiner(c, hauteur)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _texte(c, hauteur, x, top, valeur, taille=None):
    """Écrit `valeur` avec son coin bas-gauche à (x, top) en coordonnées
    pdfplumber (top = distance depuis le HAUT de la page)."""
    if not valeur:
        return
    if taille:
        c.setFont(FONT, taille)
    c.drawString(x, hauteur - top, str(valeur))
    if taille:
        c.setFont(FONT, FONT_SIZE)


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
        _texte(c, h, 95, 118, patient.numero_assure or '')
        _texte(c, h, 132, 139, nom_complet)
        _texte(c, h, 430, 139, patient.telephone or '')

        _texte(c, h, 180, 182.5, code_formation_sanitaire or '')
        _texte(c, h, 419, 181, medecin.code_prescripteur or '')
        _texte(c, h, 97, 206, medecin.telephone or '')
        d = demande.date_prescription or date.today()
        _texte(c, h, 384, 206, d.strftime('%d/%m'))
        _texte(c, h, 463, 206, str(d.year)[-2:])

        # Tableau "Actes" — N°(27.5-50.2) | Acte(50.2-198.3) | Motif(198.3-361.0)
        if demande.inclure_actes:
            y_rows = [291, 320.5, 346.5]
            for ligne, y in zip(actes, y_rows):
                _texte(c, h, 55, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE)
                _texte(c, h, 203, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE)

        # Tableau "Médicament et assimilé" — N°(27-55.6) | Médicament(55.6-213.8) | Motif(213.8-418.8)
        if demande.inclure_produits:
            y_rows = [423.5, 450.5, 480.9, 503.4]
            for ligne, y in zip(produits, y_rows):
                _texte(c, h, 60, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE)
                _texte(c, h, 218, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE)

        # Tableau "Hospitalisation" — colonnes : Date admission(26.5-77.2) |
        # Motif(77.2-203.3) | Catégorie de salle(203.3-324.1, checkboxes
        # Oui/Non) | Durée séjour(324.1-380.0)
        if demande.inclure_hospitalisation:
            if demande.hospit_date_admission:
                _texte(c, h, 32, 615, demande.hospit_date_admission.strftime('%d/%m/%Y'), taille=FONT_SIZE_TABLE)
            _texte(c, h, 80, 615, demande.hospit_motif or '', taille=FONT_SIZE_TABLE)
            _texte(c, h, 327, 615, demande.hospit_duree_sejour or '', taille=FONT_SIZE_TABLE)
            if demande.hospit_categorie_salle == 'cabine_ventilee':
                _coche(c, h, 230.2, 243.5, 645.5, 655.6)  # case "Oui"
            elif demande.hospit_categorie_salle == 'autre':
                _coche(c, h, 230.2, 243.5, 659.4, 669.5)  # case "Non"
                _texte(c, h, 212, 718, demande.hospit_categorie_autre_precision or '', taille=9)

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
        _texte(c, h, 44, 157, patient.nom or '')
        _texte(c, h, 44, 194, patient.prenom or '')
        _texte(c, h, 44, 231, patient.numero_assure or '')
        _texte(c, h, 44, 267, demande.numero_feuille_soins or '')

        _texte(c, h, 321, 157, code_formation_sanitaire or '')
        _texte(c, h, 321, 194, medecin.code_prescripteur or '')
        _texte(c, h, 321, 231, medecin.telephone or '')
        d = demande.date_prescription or date.today()
        _texte(c, h, 321, 267, d.strftime('%d/%m/%Y'))

        # Tableau "Actes" — N°(35.3-63.6) | Actes(63.6-311.7) | Motifs(311.7-559.8)
        if demande.inclure_actes:
            y_rows = [333, 365, 396]
            for ligne, y in zip(actes, y_rows):
                _texte(c, h, 68, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE)
                _texte(c, h, 316, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE)

        # Tableau "Produits pharmaceutiques" — mêmes colonnes que Actes
        if demande.inclure_produits:
            y_rows = [477, 508, 539]
            for ligne, y in zip(produits, y_rows):
                _texte(c, h, 68, y, _ligne_nom(ligne), taille=FONT_SIZE_TABLE)
                _texte(c, h, 316, y, _ligne_motif(ligne), taille=FONT_SIZE_TABLE)

        # Tableau "Hospitalisation" — Date admission(35.3-113.3) |
        # Motifs(113.3-297.6) | Catégorie de salle(297.6-481.9, checkboxes
        # Oui/Non) | Durée séjour(481.9-559.8)
        if demande.inclure_hospitalisation:
            if demande.hospit_date_admission:
                _texte(c, h, 40, 650, demande.hospit_date_admission.strftime('%d/%m/%Y'), taille=FONT_SIZE_TABLE)
            _texte(c, h, 118, 650, demande.hospit_motif or '', taille=FONT_SIZE_TABLE)
            _texte(c, h, 487, 650, demande.hospit_duree_sejour or '', taille=FONT_SIZE_TABLE)
            if demande.hospit_categorie_salle == 'cabine_ventilee':
                _coche(c, h, 344.9, 357.9, 678.6, 688.4)  # case "Oui"
            elif demande.hospit_categorie_salle == 'autre':
                _coche(c, h, 396.2, 409.2, 679.7, 689.5)  # case "Non"
                _texte(c, h, 326, 726, demande.hospit_categorie_autre_precision or '', taille=9)

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
