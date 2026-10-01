# ⭐ Remplissage de l'Entente Préalable AMU par superposition de texte sur
# le PDF officiel — JAMAIS de modification du fichier source (patron,
# répété deux fois : "il ne faut jamais modifier la structure des fiches
# jamais"). Les PDF (static/documents/amu_{cnss,inam}/...) sont plats, pas
# de champs AcroForm (vérifié via pypdf.get_fields() = vide) : on dessine
# le texte aux coordonnées calibrées avec pdfplumber (extract_words(),
# origine en HAUT à gauche) sur un calque transparent (reportlab, origine
# en BAS à gauche — d'où la conversion y_pdf = hauteur_page - y_pdfplumber
# dans chaque fonction ci-dessous), puis on fusionne ce calque sur la page
# d'origine (pypdf merge_page) : le fichier sur disque n'est jamais
# rouvert en écriture.
#
# Calibrage initial au mot-clé le plus proche sur le rendu réel du PDF
# (page.to_image() de pdfplumber) — un petit ajustement pixel-près reste
# possible en pratique, voir plan de session.

import io
from datetime import date

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black

AMU_CNSS_PDF = 'static/documents/amu_cnss/demande_entente_prealable.pdf'
AMU_INAM_PDF = 'static/documents/amu_inam/demande_entente_prealable.pdf'

FONT = 'Helvetica'
FONT_SIZE = 10


def _overlay(largeur, hauteur, dessiner):
    """Crée un calque transparent de la taille de la page et appelle
    dessiner(c, hauteur) pour y écrire le texte — c est un reportlab
    Canvas, hauteur sert à convertir les coordonnées pdfplumber (haut)
    en coordonnées reportlab (bas)."""
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


def _ligne_motif_texte(ligne):
    """{'type': 'acte'|'produit', 'nom': ..., 'saisie_manuelle': bool} -> str"""
    return (ligne or {}).get('nom', '')


def remplir_ep_cnss(demande, patient, medecin, code_formation_sanitaire):
    """demande: DemandeEntentePrealable ; patient: Patient ; medecin: Medecin.
    Retourne les bytes du PDF (2 pages, page 2 = encart contact imprimé
    tel quel, jamais modifié)."""
    reader = PdfReader(AMU_CNSS_PDF)
    page1 = reader.pages[0]
    largeur, hauteur = float(page1.mediabox.width), float(page1.mediabox.height)

    lignes = demande.lignes_motif or []
    actes = [l for l in lignes if l.get('type') == 'acte'][:3]
    produits = [l for l in lignes if l.get('type') == 'produit'][:4]

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

        # Tableau "Actes" — 3 lignes, colonnes Acte (x~110) / Motif (x~240)
        y_actes = [302, 331, 357]
        for ligne, y in zip(actes, y_actes):
            _texte(c, h, 110, y, _ligne_motif_texte(ligne), taille=8)

        # Tableau "Médicament et assimilé" — 4 lignes, colonnes Médicament (x~80) / Motif (x~290)
        y_produits = [434, 461, 491, 514]
        for ligne, y in zip(produits, y_produits):
            _texte(c, h, 80, y, _ligne_motif_texte(ligne), taille=8)

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

    lignes = demande.lignes_motif or []
    actes = [l for l in lignes if l.get('type') == 'acte'][:3]
    produits = [l for l in lignes if l.get('type') == 'produit'][:3]

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

        # Tableau "Actes" — 3 lignes
        y_actes = [335, 367, 398]
        for ligne, y in zip(actes, y_actes):
            _texte(c, h, 110, y, _ligne_motif_texte(ligne), taille=8)

        # Tableau "Produits pharmaceutiques" — 3 lignes
        y_produits = [479, 510, 541]
        for ligne, y in zip(produits, y_produits):
            _texte(c, h, 110, y, _ligne_motif_texte(ligne), taille=8)

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
