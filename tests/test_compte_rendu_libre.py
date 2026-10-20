"""Comptes rendus en texte libre importés de Word (radiologie Clinique Valeo, 2026-10-19) : identité du
patient effacée et remplacée par des cases remplies par le logiciel, texte modifiable, en-tête du Word gardé.
Word fictif construit ici (aucune donnée réelle)."""
import io
import re
import zipfile

from services.modele_formulaire import adapter_entete, docx_compte_rendu_libre, proposer_modele

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _p(*morceaux):
    return '<w:p>' + ''.join(f'<w:r><w:t xml:space="preserve">{m}</w:t></w:r>' for m in morceaux) + '</w:p>'


def _docx():
    corps = ''.join([
        _p('Baguida, le', '11 09 2025'),
        _p('Patient(e) : ', 'DUPONT Jean'),
        _p('Sexe :', 'Masculin'),
        _p('Age : ', '30 ans'),
        _p('Numéro de dossier : 12/2025'),
        _p('Prescripteur : Dr MARTIN'),
        _p('RADIOGRAPHIE DU GENOU'),
        _p('INDICATION :'), _p('Traumatisme.'),
        _p('Conclusion :'), _p('Genou normal.'),
        _p('Bien confraternellement,'),
    ])
    entete = (f'<w:hdr {NS}>' + '<w:p><w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr><w:t>RADIOLOGIE ET IMAGERIE MEDICALE</w:t></w:r></w:p>'
              '<w:p><w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:t>Route nationale 2 - Baguida</w:t></w:r></w:p></w:hdr>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('word/document.xml', f'<w:document {NS}><w:body>{corps}'
                   '<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/></w:sectPr></w:body></w:document>')
        z.writestr('word/header1.xml', entete)
        z.writestr('word/_rels/document.xml.rels',
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rIdH" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
                   '</Relationships>')
    return out.getvalue()


def test_identite_remplacee_par_des_cases_et_effacee_du_word():
    html, propre = docx_compte_rendu_libre(_docx())
    assert re.findall(r'data-id="(\w+)"', html) == ['date_complete', 'patient', 'sexe', 'age', 'dossier', 'prescripteur']
    xml = zipfile.ZipFile(io.BytesIO(propre)).read('word/document.xml').decode()
    for valeur in ('DUPONT', 'Masculin', '30 ans', '12/2025', 'MARTIN', '11 09 2025'):
        assert valeur not in html and valeur not in xml
    assert 'RADIOGRAPHIE DU GENOU' in xml and 'Genou normal.' in xml   # le compte rendu lui-même reste


def test_texte_modifiable_du_titre_a_la_conclusion():
    html, _ = docx_compte_rendu_libre(_docx())
    libre = re.search(r'<div class="mf-libre" contenteditable="true"[^>]*>(.*?)</div><p', html, re.S).group(1)
    assert 'RADIOGRAPHIE DU GENOU' in libre and 'Genou normal.' in libre
    assert 'confraternellement' not in libre and 'Prescripteur' not in libre


def test_entete_du_word_garde_tel_quel():
    html, _ = docx_compte_rendu_libre(_docx())
    assert 'mf-entete-fixe' in html and 'RADIOLOGIE ET IMAGERIE MEDICALE' in html
    assert 'font-size:14pt;font-weight:bold' in html
    # une autre structure ne remplace pas cet en-tête par le sien
    assert adapter_entete(html, {'nom': 'CLINIQUE VALEO', 'adresse': 'Lomé'}, 'examen') == html


def test_proposition_radiologie():
    modeles = [(1, 'Genou - normal', '<p>RADIOGRAPHIE DU GENOU incidence de face</p>'),
               (2, 'Genou - traumatique', '<p>RADIOGRAPHIE DU GENOU incidence de face et profil</p>'),
               (3, 'Thorax - normal', '<p>RADIOGRAPHIE DU THORAX</p>'),
               (4, 'Hystérosalpingographie', '<p>HYSTEROSALPINGOGRAPHIE</p>')]
    assert proposer_modele('Q132 Examen radiologique du genou inferieur ou egal a deux incidences.', modeles) == 1
    assert proposer_modele('Q201 Examen radiologique des poumons et du coeur sans opacification', modeles) == 3
    assert proposer_modele("Q212 Hystero-salpingograhie incluant l'abdomen sans preparation", modeles) == 4
    assert proposer_modele('Q100 Examen radiologique du doigt', modeles) is None


def test_signatures_apposees_sous_le_radiologue():
    from services.modele_formulaire import apposer_signatures
    html = ('<div class="modele-formulaire"><p>Conclusion : normal.</p><p>Bien confraternellement,</p>'
            '<p> &nbsp; &nbsp;Le Radiologue&emsp;</p><p>Merci</p></div>')
    sg = [{'nom': 'Dr A', 'titre': 'Radiologue', 'mime': 'image/png', 'image': 'QUJD'},
          {'nom': 'Dr B', 'titre': '', 'mime': '', 'image': ''}]
    out = apposer_signatures(html, sg)
    i_ligne, i_bloc, i_merci = out.index('Le Radiologue'), out.index('mf-signatures'), out.index('Merci')
    assert i_ligne < i_bloc < i_merci
    assert out.count('<img') == 1 and 'Radiologue — Dr A' in out and 'Dr B' in out
    assert apposer_signatures(out, sg) == out                       # jamais deux fois
    assert apposer_signatures('<p>Résultat sans mention</p>', sg) == '<p>Résultat sans mention</p>'


def test_mise_en_page_comme_le_word_de_valeo():
    """Patron, 2026-10-20 (photo du Word) : date à droite, « Examen réalisé sur » sous le titre, nom du
    radiologue centré sous « Le Radiologue » — à l'ouverture du modèle comme sur un compte rendu enregistré."""
    from services.modele_formulaire import ajuster_compte_rendu, apposer_signatures
    html = ('<style></style><table class="mf-entete"></table>'
            '<p style="margin:0;padding-left:200pt">Baguida, le <span class="mf-valeur" data-id="date_complete">20/10/2026</span></p>'
            '<div class="mf-libre" contenteditable="true">'
            '<p class="mf-titre-examen" style="text-align:center"><span>RADIOGRAPHIE DU RACHIS LOMBAIRE</span></p>'
            '<p><b>TECHNIQUE :</b></p><p>Incidence de face et profil.</p>'
            '<p style="margin:2px 0 0"><span>Examen réalisé sur J@DIX-I mise en service le 18/01/2023</span></p>'
            '<p><b>RESULTATS :</b></p><p>Normal.</p></div>'
            '<p>Bien confraternellement,</p><p style="margin:0">&nbsp; &nbsp; &nbsp; Le Radiologue </p>')
    # compte rendu déjà enregistré (nom apposé avant l'ajustement)
    imprime = ajuster_compte_rendu(apposer_signatures(html, [{'nom': 'Dr AYIVI', 'titre': '', 'image': ''}]))
    assert '<p style="margin:0;text-align:right">Baguida, le' in imprime
    titre = imprime.index('mf-titre-examen')
    assert titre < imprime.index('mf-appareil') < imprime.index('TECHNIQUE')
    assert imprime.count('Examen réalisé sur') == 1
    bloc = imprime[imprime.index('mf-bloc-signature'):]
    assert bloc.index('Le Radiologue') < bloc.index('Dr AYIVI') and 'justify-content:center' in bloc
    assert ajuster_compte_rendu(imprime) == imprime
    # modèle ajusté à l'ouverture, nom apposé à l'enregistrement : même résultat
    ouvert = ajuster_compte_rendu(html)
    enregistre = ajuster_compte_rendu(apposer_signatures(ouvert, [{'nom': 'Dr AYIVI', 'titre': '', 'image': ''}]))
    bloc = enregistre[enregistre.index('mf-bloc-signature'):]
    assert bloc.index('Le Radiologue') < bloc.index('Dr AYIVI') and 'justify-content:flex-end;flex-wrap' not in bloc


# ------------------------------------------------------------ biologie (Clinique Valeo, 2026-10-20)
def _cellule(texte, span=1):
    pr = f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>' if span > 1 else ''
    return f'<w:tc>{pr}{_p(texte)}</w:tc>'


def _docx_bio():
    tableau = ('<w:tbl><w:tblPr/>'
               '<w:tr>' + _cellule('Paramètres') + _cellule('Résultats') + _cellule('Valeurs de références') + '</w:tr>'
               '<w:tr>' + _cellule('Glycémie') + _cellule('0,91') + _cellule('0,70 – 1,10 g/l') + '</w:tr>'
               '<w:tr>' + _cellule('Troponine') + _cellule('10,0 ng/l') + _cellule('&gt; = 8 ng/l') + '</w:tr>'
               '<w:tr>' + _cellule('CRP') + _cellule('Négative') + _cellule('Inférieur à 6 mg/l') + '</w:tr></w:tbl>')
    serologie = ('<w:tbl><w:tr>' + _cellule('Résultat') + '</w:tr><w:tr><w:tc>'
                 + _p('Recherche des anticorps IgM :', '   NEGATIVE ') + _p('DP =   374', ' p/µl') + '</w:tc></w:tr></w:tbl>')
    page_patient = ('<w:tbl><w:tr>' + _cellule('COMPTE-RENDU D’ANALYSES MÉDICALES') + '</w:tr><w:tr>' + _cellule('Prescrit par')
                    + _cellule('Pr DURAND') + '</w:tr></w:tbl>' + _p('Enfant DUPONT Jean') + _p('BIOCHIMIE')
                    + '<w:tbl><w:tr>' + _cellule('Type') + _cellule('Résultats') + '</w:tr><w:tr>' + _cellule('Procalcitonine')
                    + _cellule('0,01 ng/ml') + '</w:tr></w:tbl>' + _p('Le Biologist', 'e'))
    corps = (_p('BIOCHIMIE') + tableau + serologie + _p('INTERPRÉTATION :') + _p('Anémie sévère.')
             + _p('             ', 'Le Biologiste') + page_patient)
    entete = (f'<w:hdr {NS}><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>LABORATOIRE</w:t></w:r></w:p>'
              '<w:p><w:r><w:t>Route nationale n 2 - Baguida</w:t></w:r></w:p></w:hdr>')
    pied = f'<w:ftr {NS}><w:p><w:r><w:t>Merci de ramener vos examens.</w:t></w:r></w:p></w:ftr>'
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('word/document.xml', f'<w:document {NS}><w:body>{corps}<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/>'
                   '<w:footerReference w:type="default" r:id="rIdF"/></w:sectPr></w:body></w:document>')
        z.writestr('word/header1.xml', entete)
        z.writestr('word/footer1.xml', pied)
        z.writestr('word/_rels/document.xml.rels',
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rIdH" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
                   '<Relationship Id="rIdF" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
                   '</Relationships>')
    return out.getvalue()


def test_biologie_valeurs_effacees_et_pages_de_patients_retirees():
    from services.modele_formulaire import docx_compte_rendu_biologie
    html, propre = docx_compte_rendu_biologie(_docx_bio(), prelevement='Sérum', interpretation='Hémogramme normal.',
                                              suggestions=['Hémogramme normal.', 'Thrombopénie.'])
    xml = zipfile.ZipFile(io.BytesIO(propre)).read('word/document.xml').decode()
    for reste in ('0,91', '10,0', '374', 'DUPONT', 'DURAND', 'Procalcitonine', 'Anémie sévère'):
        assert reste not in html, reste
    for reste in ('0,91', '10,0', '374', 'DUPONT', 'DURAND', 'Procalcitonine'):
        assert reste not in xml, reste
    # valeurs -> cases (unité gardée), négative / positive -> liste ; normes jamais touchées
    assert html.count('mf-texte mf-resultat') == 3 and html.count('<select class="mf-champ mf-liste mf-resultat"') == 2
    assert 'ng/l' in html and '0,70 – 1,10 g/l' in html and '&gt; = 8 ng/l' in html and 'p/µl' in html
    # cadre d'identité rempli par le logiciel, en-tête et pied du Word, interprétation modifiable
    for cle in ('prescripteur', 'age', 'dossier', 'prelevement', 'date_prelevement_complete', 'heure_prelevement',
                'patient_civilite', 'sexe', 'telephone'):
        assert f'data-id="{cle}"' in html, cle
    assert 'value="Sérum"' in html and 'mf-entete-fixe' in html and 'LABORATOIRE' in html
    assert 'Merci de ramener vos examens.' in html and html.count('Le Biologiste') == 1
    assert '<p class="mf-titre-analyse"' in html and 'mf-bordure' in html
    libre = re.search(r'<div class="mf-libre"[^>]*>(.*?)</div>', html, re.S).group(1)
    assert 'Hémogramme normal.' in libre and 'mf-suggestion' in html and 'Thrombopénie.' in html


def test_biologie_modele_tire_d_une_partie_du_word():
    from services.modele_formulaire import docx_compte_rendu_biologie
    html, _ = docx_compte_rendu_biologie(_docx_bio(), section=('BIOCHIMIE', None))
    # la 1re « BIOCHIMIE » est prise : partie de la page 1, jusqu'à « Le Biologiste »
    assert 'Glycémie' in html and 'DUPONT' not in html and html.count('Le Biologiste') == 1


def test_biologie_pas_de_titre_encadre_ni_d_appareil():
    from services.modele_formulaire import docx_compte_rendu_biologie, mettre_en_forme_compte_rendu
    html, _ = docx_compte_rendu_biologie(_docx_bio(), interpretation='Hémogramme normal.')
    assert mettre_en_forme_compte_rendu(html) == html


def test_proposition_biologie_selon_le_patient():
    from services.modele_formulaire import proposer_modele, profil_patient
    modeles = [(1, 'Hémogramme (NFS) - homme', '<p>HEMOGRAMME Hématies</p>'),
               (2, 'Hémogramme (NFS) - femme', '<p>HEMOGRAMME Hématies</p>'),
               (3, 'Hémogramme (NFS) - enfant', '<p>HEMOGRAMME Hématies</p>'),
               (4, 'Hémogramme (NFS) - nouveau-né', '<p>HEMOGRAMME Hématies</p>'),
               (5, 'Biochimie (glycémie, urée, créatinine, ASAT, ALAT, GGT, PAL)', '<p>Valeurs de références</p>'),
               (6, 'Sérologie de la dengue (IgM, IgG, Ag NS1)', '<p>Recherche des Ag NS1</p>'),
               (7, 'Hémoglobine glyquée (HbA1c)', '<p>Diabète équilibré</p>'),
               (8, 'Goutte épaisse (GE) - négative', '<p>GOUTTE EPAISSE</p>'),
               (9, 'Goutte épaisse - positive', '<p>GOUTTE EPAISSE GE : Plasmodium</p>')]
    nfs = 'R607 Hemogramme(NFS Complete)'
    assert proposer_modele(nfs, modeles, profil_patient('M', 40 * 365)) == 1
    assert proposer_modele(nfs, modeles, profil_patient('F', 40 * 365)) == 2
    assert proposer_modele(nfs, modeles, profil_patient('F', 6 * 365)) == 3
    assert proposer_modele(nfs, modeles, profil_patient('M', 3)) == 4
    assert proposer_modele('R823 Glucose (glycemie veineuse)', modeles) == 5
    assert proposer_modele('R877 Bilan hepatique (Transaminases, GGT, PAL)', modeles) == 5
    assert proposer_modele('R101 Frottis mince et goutte epaisse (GE)', modeles) == 8
    assert proposer_modele('R824 Hemoglobine glyquee', modeles) == 7
    # un seul mot en commun, ou au milieu d'un autre mot : rien
    assert proposer_modele('R416 Serologie de l’hepatite B : Ag HBs (ELISA et autres)', modeles) is None
    assert proposer_modele("R610 Electrophorese de l’hemoglobine a pH alcalin", modeles) is None
    assert proposer_modele('R842 Fer', modeles) is None
    assert proposer_modele('R819 Estradiol (libre)', modeles) is None


def test_modeles_harmonises_tailles_et_nom_du_radiologue_retire():
    """Patron, 2026-10-20 (« c'est discordant ») : même taille de texte dans tous les modèles de radiologie,
    plus de nom de radiologue écrit en dur sous « Le Radiologue », mise en page de l'impression dans le modèle."""
    from services.modele_formulaire import harmoniser_compte_rendu
    html = ('<div class="modele-formulaire"><style></style><table class="mf-entete mf-entete-fixe"><tr><td>X</td></tr></table>'
            '<p style="margin:0;padding-left:200pt"><span style="font-size:10pt">Baguida, le <span class="mf-champ mf-texte" data-id="date_complete"></span></span></p>'
            '<p style="margin:0"><span style="font-weight:bold;font-size:10pt">Patient(e) : <span class="mf-champ mf-texte" data-id="patient"></span></span></p>'
            '<p style="margin:0">Prescripteur : <span class="mf-champ mf-texte" data-id="prescripteur"></span></p>'
            '<div class="mf-libre" contenteditable="true" spellcheck="true">'
            '<p style="margin:0"><span style="font-weight:bold;font-size:10pt">RADIOGRAPHIE DE LA CUISSE</span></p>'
            '<p style="margin:0"><span style="font-size:10pt">TECHNIQUE :</span></p><p><span style="font-size:13pt">Face.</span></p>'
            '<p><span style="font-size:10pt">Examen réalisé sur J@DIX-I</span></p>'
            '<table class="mf-table"><tr><td><span style="font-size:16pt">GENOUX</span></td></tr></table>'
            '<p><span style="font-size:16pt">Conclusion : normal.</span></p></div>'
            '<p style="margin:0">Bien confraternellement,</p>'
            '<p style="margin:0">&nbsp; &nbsp; &nbsp;<span style="font-size:10pt">Le Radiologue</span></p>'
            '<p style="margin:0">&nbsp;</p><p style="margin:0"><span style="font-size:10pt">Dr KOMLANVI</span></p></div>')
    out = harmoniser_compte_rendu(html)
    assert 'KOMLANVI' not in out and 'mf-bloc-signature' in out
    libre = out[out.index('<div class="mf-libre"'):out.index('Bien confraternellement')]
    tailles = set(re.findall(r'font-size:([\d.]+pt)', re.sub(r'<p class="mf-(titre-examen|appareil)".*?</p>|<table.*?</table>', '', libre, flags=re.S)))
    assert tailles == {'14pt'}, tailles
    assert '<table style="font-size:12pt"' in libre and '16pt' not in out
    assert 'mf-titre-examen' in out and out.index('mf-titre-examen') < out.index('mf-appareil') < out.index('TECHNIQUE')
    identite = out[out.index('</table>'):out.index('<div class="mf-libre"')]
    assert '10pt' not in identite and identite.count('font-size:12pt') == 3
    assert harmoniser_compte_rendu(out) == out


def test_modele_biologie_tableaux_d_une_seule_taille():
    from services.modele_formulaire import docx_compte_rendu_biologie, harmoniser_compte_rendu
    html, _ = docx_compte_rendu_biologie(_docx_bio())
    assert '<table class="mf-table mf-bordure" style="font-size:12pt">' in html and 'mf-bloc-signature' in html
    assert harmoniser_compte_rendu(html) == html


def test_couleurs_du_theme_sombre_jamais_gardees():
    """Patron, 2026-10-20 : NFS saisie en thème sombre -> texte blanc à l'impression."""
    from services.modele_formulaire import retirer_couleurs_du_theme
    html = ('<div class="modele-formulaire" data-th-sombre="1" style="color: rgb(232, 232, 232) !important;">'
            '<span class="mf-valeur" style="font-weight: bold; background-color: rgb(20, 20, 20) !important; '
            'transition: none !important; border-color: rgba(255, 255, 255, 0.14) !important; white-space: pre-wrap;">67</span>'
            '<p style="margin:0;color:#c00">rouge du modèle</p></div>')
    out = retirer_couleurs_du_theme(html)
    assert out.startswith('<div class="modele-formulaire">') and '!important' not in out and 'data-th-sombre' not in out
    assert 'font-weight: bold; white-space: pre-wrap' in out and 'color:#c00' in out
    assert retirer_couleurs_du_theme(out) == out
