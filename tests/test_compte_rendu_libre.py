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
