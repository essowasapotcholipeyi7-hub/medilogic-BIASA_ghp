# ⭐⭐ TPC (Traitement des Pathologies Chroniques) — même principe de
# remplissage que l'Entente Préalable (voir utils/remplissage_pdf_amu.py,
# dont ce module réutilise les briques génériques) : overlay reportlab sur
# le PDF officiel, jamais de modification du fichier source. Calibrage aux
# coordonnées pdfplumber (extract_words()/chars()/rects, origine en haut à
# gauche) sur les PDF fournis par le patron.
#
# 4 fiches couvertes dans cette passe (patron, 2026-10-01 : "attaque les
# TPC, même logique que les EP") :
#   - CNSS/TNS : identification, renouvellement, modification
#   - INAM : rectification
# La fiche d'identification INAM (grille détaillée de 12 systèmes
# d'examen + ~20 analyses nommées une par une, page en paysage) est
# volontairement HORS PÉRIMÈTRE de cette passe — structurellement bien
# plus détaillée que les 4 autres, elle suivra dans une passe dédiée une
# fois celles-ci validées (même logique de phasage que EP -> TPC).

import io
from datetime import date

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth

from utils.remplissage_pdf_amu import (
    FONT,
    _overlay, _ajuster_pour_largeur, _texte, _texte_centree, _texte_cases, _coche,
)

# ⭐ Tailles propres au TPC (patron, 2026-10-02 : "augmente un peu la
# police et l'écriture en gras... fait que ce qu'on écrit ne se repose
# pas directement sur les pointillés, tout ce que tu as fait pour EP") —
# des constantes LOCALES à ce module plutôt que de relever
# FONT_SIZE_TABLE partagé avec l'EP (déjà validé par le patron tel quel,
# jamais y toucher ici). Le gras est déjà hérité de FONT ci-dessus
# (Helvetica-Bold, voir utils/remplissage_pdf_amu.py) — rien à changer
# pour ça, il s'applique déjà à tout le texte saisi.
FONT_SIZE_TPC_IDENTITE = 11
FONT_SIZE_TPC_TABLE = 11     # était 10 (FONT_SIZE_TABLE de l'EP)
FONT_SIZE_TPC_BOITE = 10     # était 9

AMU_CNSS_TPC_IDENTIFICATION_PDF = 'static/documents/amu_cnss/fiche_identification_patients_chroniques.pdf'
AMU_CNSS_TPC_RENOUVELLEMENT_PDF = 'static/documents/amu_cnss/fiche_renouvellement_tpc.pdf'
AMU_CNSS_TPC_MODIFICATION_PDF = 'static/documents/amu_cnss/fiche_modification_tpc.pdf'
AMU_INAM_TPC_RECTIFICATION_PDF = 'static/documents/amu_inam/fiche_rectification_tpc.pdf'


def _texte_boite(c, hauteur, x0, x1, top0, top1, valeur, taille=FONT_SIZE_TPC_BOITE):
    """Texte libre multi-lignes dans une case rectangulaire (ex: "Motif de
    la modification", "Résultats des examens effectués") — coupe par mot à
    la largeur de la case, une ligne par rangée, tronque avec '…' sur la
    dernière ligne si ça déborde encore. Jamais une seule ligne géante
    comme _texte() : ces cases du formulaire sont volontairement hautes
    pour plusieurs lignes de texte libre."""
    if not valeur:
        return
    largeur_max = x1 - x0 - 6
    hauteur_ligne = 13
    nb_lignes = max(1, int((top1 - top0) // hauteur_ligne))
    mots = str(valeur).split(' ')
    lignes, ligne_courante = [], ''
    for mot in mots:
        essai = (ligne_courante + ' ' + mot).strip()
        if stringWidth(essai, FONT, taille) <= largeur_max:
            ligne_courante = essai
        else:
            if ligne_courante:
                lignes.append(ligne_courante)
            ligne_courante = mot
        if len(lignes) >= nb_lignes:
            break
    if ligne_courante and len(lignes) < nb_lignes:
        lignes.append(ligne_courante)
    lignes = lignes[:nb_lignes]
    if lignes:
        lignes[-1], _ = _ajuster_pour_largeur(lignes[-1], largeur_max, taille)
    for i, ligne in enumerate(lignes):
        _texte(c, hauteur, x0 + 3, top0 + 10 + i * hauteur_ligne, ligne, taille=taille, largeur_max=largeur_max)


# ⭐ Cases "N° AMU" / "Code formation sanitaire" / "Code prescripteur" —
# mêmes gabarits CNSS que l'Entente Préalable (même administration), mais
# positionnées différemment sur chaque fiche TPC : constantes par fiche,
# calibrées aux "/" imprimés (voir _texte_cases, utils/remplissage_pdf_amu.py).
CASES_IDENTIFICATION = {
    'numero_amu': [
        (95.8, 108.8), (112.7, 126.1), (130.0, 143.5), (147.5, 160.9), (164.7, 178.3), (182.1, 195.7), (199.5, 213.1),
        (254.7, 268.0), (271.9, 285.4), (289.2, 302.8), (306.6, 320.2), (324.0, 337.6), (341.5, 355.0), (358.8, 372.4),
        (376.2, 392.7), (396.5, 410.2), (414.2, 427.7),
        (460.2, 473.5), (477.5, 499.5),
    ],
    'code_formation_sanitaire': [(178.7, 192.9), (196.8, 211.0), (214.9, 229.1), (233.0, 247.3), (251.2, 268.3), (272.2, 289.4)],
    'code_prescripteur': [(414.4, 428.7), (432.6, 446.8), (450.7, 464.9), (468.8, 483.0), (486.9, 504.1), (508.0, 525.2), (529.1, 546.3)],
}

CASES_RENOUVELLEMENT = {
    'numero_amu': [
        (163.4, 177.2), (181.1, 194.8), (198.7, 212.5), (216.4, 230.2), (234.1, 247.8), (251.7, 265.5), (269.4, 283.2),
        (308.2, 322.0), (325.9, 339.7), (343.6, 357.3), (361.2, 375.0), (378.9, 392.7), (396.6, 410.3), (414.2, 428.0),
        (431.9, 449.1), (453.0, 466.8), (470.7, 484.4),
        (512.4, 526.2), (530.1, 543.9),
    ],
    'code_formation_sanitaire': [(199.7, 213.5), (217.4, 231.3), (235.2, 249.0), (252.9, 266.8), (270.7, 284.5), (288.4, 302.3)],
    'code_prescripteur': [(437.4, 451.3), (455.2, 469.0), (472.9, 486.7), (490.6, 504.5), (508.4, 522.2), (526.1, 540.0), (543.9, 557.7)],
}

CASES_MODIFICATION = {
    'numero_amu': [
        (163.3, 177.0), (180.9, 194.7), (198.6, 212.4), (216.3, 230.0), (233.9, 247.7), (251.6, 265.4), (269.3, 283.0),
        (308.1, 321.9), (325.8, 339.5), (343.4, 357.2), (361.1, 374.8), (378.7, 392.5), (396.4, 410.2), (414.1, 427.8),
        (431.7, 449.0), (452.9, 466.6), (470.5, 484.3),
        (512.3, 526.0), (529.9, 543.7),
    ],
    'code_formation_sanitaire': [(193.5, 207.1), (211.0, 224.5), (228.4, 242.0), (245.9, 259.4), (263.3, 276.9), (280.8, 294.3)],
    'code_prescripteur': [(434.4, 447.9), (451.8, 465.4), (469.3, 482.8), (486.7, 500.3), (504.2, 517.7), (521.6, 535.2), (539.1, 552.6)],
}


def remplir_tpc_cnss_identification(demande, patient, medecin, code_formation_sanitaire):
    """Fiche d'identification TPC CNSS/TNS (4 pages : 3 remplies, 1 mode
    d'emploi statique jamais touchée)."""
    reader = PdfReader(AMU_CNSS_TPC_IDENTIFICATION_PDF)
    pages = reader.pages
    largeur, hauteur = float(pages[0].mediabox.width), float(pages[0].mediabox.height)

    def dessiner_page1(c, h):
        nom_complet = f"{patient.nom} {patient.prenom}".strip()
        age = ''
        if patient.date_naissance:
            aujourd_hui = demande.date_prescription or date.today()
            age = str(aujourd_hui.year - patient.date_naissance.year - (
                (aujourd_hui.month, aujourd_hui.day) < (patient.date_naissance.month, patient.date_naissance.day)
            ))
        _texte_cases(c, h, 149.0, CASES_IDENTIFICATION['numero_amu'], patient.numero_assure or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte(c, h, 136, 170.5, nom_complet, largeur_max=420)
        _texte(c, h, 70.2, 188.3, demande.sexe or '', largeur_max=95)
        _texte(c, h, 209.8, 188.3, age, largeur_max=60)
        _texte(c, h, 350.2, 188.3, demande.profession or '', largeur_max=205)
        _texte(c, h, 101, 207.0, patient.telephone or '', largeur_max=155)
        _texte(c, h, 420, 207.0, demande.ville_residence or '', largeur_max=135)

        y_rows = [295, 327, 359, 391]
        for ligne, y in zip((demande.affections_ald or [])[:4], y_rows):
            _texte(c, h, 198, y, ligne.get('affection', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=265)
            _texte(c, h, 470, y, ligne.get('code_ald', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=85)

        _texte(c, h, 71.7, 448.5, demande.poids or '', largeur_max=40)
        _texte(c, h, 213.1, 448.3, demande.taille or '', largeur_max=40)
        _texte(c, h, 350.8, 448.3, demande.imc or '', largeur_max=55)
        _texte(c, h, 148.3, 465.1, demande.ta_bg or '', largeur_max=75)
        _texte(c, h, 274.4, 465.1, demande.ta_bd or '', largeur_max=35)
        _texte(c, h, 107.2, 486.0, demande.etat_general or '', largeur_max=410)
        _texte_boite(c, h, 31.2, 559.7, 524.0, 724.9, demande.resume_examen_physique or '')
        # ⭐ "Autres :" a son propre texte de label sur la 1ère ligne de
        # pointillés (727.9) — y écrire par-dessus se superposait au mot
        # "Autres". On démarre donc sur la ligne pleine largeur suivante
        # (744.9), 3 lignes disponibles jusqu'à 792.9.
        _texte_boite(c, h, 31.2, 559.7, 744.9, 792.9, demande.autres_examen or '')

    def dessiner_page2(c, h):
        y_rows = [94.5, 134.1, 175.8, 218.1, 259.8, 303.1, 344.8, 387.1, 428.8, 474.1, 517.8, 562.1, 603.8, 647.1]
        for ligne, y in zip((demande.examens_paracliniques or [])[:14], y_rows):
            _texte(c, h, 36, y + 12, ligne.get('examen', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=105)
            _texte(c, h, 151, y + 12, ligne.get('date', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=58)
            _texte(c, h, 218, y + 12, ligne.get('resultat', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=340)

    def dessiner_page3(c, h):
        y_rows = [102.3, 159.5, 217.5, 274.5, 331.5, 390.5]
        for ligne, y in zip((demande.traitements or [])[:6], y_rows):
            _texte(c, h, 38, y + 14, ligne.get('code_ald', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=80)
            _texte(c, h, 124, y + 14, ligne.get('medicament', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=145)
            _texte(c, h, 274, y + 14, ligne.get('forme_dosage', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=108)
            _texte(c, h, 388, y + 14, ligne.get('posologie', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=84)
            _texte(c, h, 478, y + 14, ligne.get('duree', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=78)

        comorbidites = demande.comorbidites or []
        x_comorb = [58.6, 208.5, 364.3]
        for i, x in enumerate(x_comorb):
            if i < len(comorbidites) and comorbidites[i]:
                _texte(c, h, x + 12, 522.5, comorbidites[i], taille=FONT_SIZE_TPC_BOITE, largeur_max=105)
        if demande.date_prochain_rdv:
            d = demande.date_prochain_rdv
            _texte_centree(c, h, 227.9, 269.4, 552.7, d.strftime('%d'), taille=FONT_SIZE_TPC_TABLE)
            _texte_centree(c, h, 272.7, 317.2, 552.7, d.strftime('%m'), taille=FONT_SIZE_TPC_TABLE)
            _texte_centree(c, h, 332.4, 359.1, 552.7, d.strftime('%y'), taille=FONT_SIZE_TPC_TABLE)

        _texte_cases(c, h, 615.3, CASES_IDENTIFICATION['code_formation_sanitaire'], code_formation_sanitaire or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte_cases(c, h, 615.3, CASES_IDENTIFICATION['code_prescripteur'], medecin.code_prescripteur or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte(c, h, 101.8, 652.2, medecin.telephone or '', largeur_max=155)

    for i, dessiner in enumerate([dessiner_page1, dessiner_page2, dessiner_page3]):
        pages[i].merge_page(_overlay(largeur, hauteur, dessiner))

    writer = PdfWriter()
    for p in pages:
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_tpc_cnss_renouvellement(demande, patient, medecin, code_formation_sanitaire):
    reader = PdfReader(AMU_CNSS_TPC_RENOUVELLEMENT_PDF)
    page1 = reader.pages[0]
    largeur, hauteur = float(page1.mediabox.width), float(page1.mediabox.height)

    def dessiner(c, h):
        nom_complet = f"{patient.nom} {patient.prenom}".strip()
        _texte_cases(c, h, 139.5, CASES_RENOUVELLEMENT['numero_amu'], patient.numero_assure or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte(c, h, 160, 162.1, nom_complet, largeur_max=395)
        _texte(c, h, 160, 191.6, patient.telephone or '', largeur_max=150)
        _texte(c, h, 420.8, 191.6, demande.ville_residence or '', largeur_max=135)

        if demande.traitement_a_renouveler is True:
            _coche(c, h, 377.1, 392.6, 239.5, 252.5)
        elif demande.traitement_a_renouveler is False:
            _coche(c, h, 438.4, 453.9, 239.4, 252.5)

        y_rows = [359.6, 387.6, 415.3, 443.9]
        for ligne, y in zip((demande.traitements or [])[:4], y_rows):
            _texte(c, h, 39, y + 14, ligne.get('code_ald', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=90)
            _texte(c, h, 134, y + 14, ligne.get('medicament', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=150)
            _texte(c, h, 291, y + 14, ligne.get('forme_dosage', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=100)
            _texte(c, h, 397, y + 14, ligne.get('posologie', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=72)
            _texte(c, h, 476, y + 14, ligne.get('duree', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=78)

        _texte_cases(c, h, 533.3, CASES_RENOUVELLEMENT['code_formation_sanitaire'], code_formation_sanitaire or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte_cases(c, h, 533.6, CASES_RENOUVELLEMENT['code_prescripteur'], medecin.code_prescripteur or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte(c, h, 111.9, 561.9, medecin.telephone or '', largeur_max=235)
        d = demande.date_prescription or date.today()
        _texte_centree(c, h, 183.3, 207.3, 593.4, d.strftime('%d'), taille=FONT_SIZE_TPC_TABLE)
        _texte_centree(c, h, 211.1, 241.8, 593.4, d.strftime('%m'), taille=FONT_SIZE_TPC_TABLE)
        _texte_centree(c, h, 259.3, 276.3, 593.4, str(d.year)[-2:], taille=FONT_SIZE_TPC_TABLE)

    page1.merge_page(_overlay(largeur, hauteur, dessiner))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_tpc_cnss_modification(demande, patient, medecin, code_formation_sanitaire):
    reader = PdfReader(AMU_CNSS_TPC_MODIFICATION_PDF)
    page1 = reader.pages[0]
    largeur, hauteur = float(page1.mediabox.width), float(page1.mediabox.height)

    def dessiner(c, h):
        nom_complet = f"{patient.nom} {patient.prenom}".strip()
        _texte_cases(c, h, 137.0, CASES_MODIFICATION['numero_amu'], patient.numero_assure or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte(c, h, 160, 160.6, nom_complet, largeur_max=395)
        _texte(c, h, 160, 189.1, patient.telephone or '', largeur_max=150)
        _texte(c, h, 420, 189.1, demande.ville_residence or '', largeur_max=135)

        _texte_boite(c, h, 38.3, 556.8, 260.7, 317.3, demande.motif_modification or '')
        _texte_boite(c, h, 38.3, 556.8, 354.3, 421.4, demande.resultats_examens_effectues or '')

        y_rows = [492.2, 512.9, 533.5, 554.1, 574.8, 595.4]
        for ligne, y in zip((demande.traitements or [])[:6], y_rows):
            _texte(c, h, 39, y + 13, ligne.get('code_ald', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=64)
            _texte(c, h, 107, y + 13, ligne.get('medicament', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=150)
            _texte(c, h, 263, y + 13, ligne.get('forme_dosage', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=115)
            _texte(c, h, 384, y + 13, ligne.get('posologie', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=88)
            _texte(c, h, 476, y + 13, ligne.get('duree', ''), taille=FONT_SIZE_TPC_TABLE, largeur_max=78)

        _texte_cases(c, h, 659.3, CASES_MODIFICATION['code_formation_sanitaire'], code_formation_sanitaire or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte_cases(c, h, 659.6, CASES_MODIFICATION['code_prescripteur'], medecin.code_prescripteur or '', taille=FONT_SIZE_TPC_IDENTITE)
        _texte(c, h, 106.5, 679.6, medecin.telephone or '', largeur_max=235)
        d = demande.date_prescription or date.today()
        _texte_centree(c, h, 444.0, 467.7, 700.9, d.strftime('%d'), taille=FONT_SIZE_TPC_TABLE)
        _texte_centree(c, h, 471.5, 502.0, 700.9, d.strftime('%m'), taille=FONT_SIZE_TPC_TABLE)
        _texte_centree(c, h, 519.4, 536.3, 700.9, str(d.year)[-2:], taille=FONT_SIZE_TPC_TABLE)

    page1.merge_page(_overlay(largeur, hauteur, dessiner))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_tpc_inam_rectification(demande, patient, medecin, code_formation_sanitaire):
    reader = PdfReader(AMU_INAM_TPC_RECTIFICATION_PDF)
    page1 = reader.pages[0]
    largeur, hauteur = float(page1.mediabox.width), float(page1.mediabox.height)

    def dessiner(c, h):
        nom_complet = f"{patient.nom} {patient.prenom}".strip()
        _texte(c, h, 172, 161.0, nom_complet, largeur_max=385)
        _texte(c, h, 172, 184.4, patient.numero_assure or '', largeur_max=385)
        _texte(c, h, 172, 207.8, patient.telephone or '', largeur_max=385)
        _texte(c, h, 172, 225.0, demande.numero_ancien_tpc or '', largeur_max=385)

        _texte_boite(c, h, 38.3, 557.0, 269.1, 373.1, demande.motif_modification or '')
        _texte_boite(c, h, 38.3, 557.0, 411.9, 527.6, demande.resultats_examens_effectues or '')

        lignes = demande.traitements or []
        resume = '; '.join(
            f"{l.get('medicament','')} ({l.get('forme_dosage','')}, {l.get('posologie','')}, {l.get('code_ald','')})".strip()
            for l in lignes if l.get('medicament')
        )
        _texte_boite(c, h, 38.3, 557.0, 566.4, 666.7, resume)

        _texte(c, h, 452, 706.9, code_formation_sanitaire or '', taille=FONT_SIZE_TPC_BOITE, largeur_max=95)
        _texte(c, h, 408, 721.5, medecin.code_prescripteur or '', taille=FONT_SIZE_TPC_BOITE, largeur_max=135)
        _texte(c, h, 417, 736.2, medecin.telephone or '', taille=FONT_SIZE_TPC_BOITE, largeur_max=125)
        d = demande.date_prescription or date.today()
        _texte_centree(c, h, 391.5, 419.4, 765.4, d.strftime('%d'), taille=FONT_SIZE_TPC_BOITE)
        _texte_centree(c, h, 426.8, 484.6, 765.4, d.strftime('%m'), taille=FONT_SIZE_TPC_BOITE)
        _texte_centree(c, h, 489.3, 533.8, 765.4, str(d.year), taille=FONT_SIZE_TPC_BOITE)

    page1.merge_page(_overlay(largeur, hauteur, dessiner))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def remplir_tpc(demande, patient, medecin, code_formation_sanitaire):
    """Point d'entrée unique — choisit le bon gabarit selon type_amu +
    type_demande. 'amu_tns' réutilise les gabarits CNSS (même
    administration, même règle que l'Entente Préalable)."""
    inam = demande.type_amu == 'amu_inam'
    if demande.type_demande == 'identification':
        if inam:
            raise NotImplementedError(
                "La fiche d'identification TPC INAM (grille d'examen détaillée) "
                "n'est pas encore disponible — seule la fiche de rectification l'est."
            )
        return remplir_tpc_cnss_identification(demande, patient, medecin, code_formation_sanitaire)
    if demande.type_demande == 'renouvellement':
        return remplir_tpc_cnss_renouvellement(demande, patient, medecin, code_formation_sanitaire)
    if demande.type_demande in ('modification', 'rectification'):
        if inam:
            return remplir_tpc_inam_rectification(demande, patient, medecin, code_formation_sanitaire)
        return remplir_tpc_cnss_modification(demande, patient, medecin, code_formation_sanitaire)
    raise ValueError(f"type_demande TPC inconnu : {demande.type_demande}")
