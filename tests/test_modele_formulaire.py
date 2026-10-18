# -*- coding: utf-8 -*-
"""Modèle de résultat « formulaire » importé d'un Word avec contrôles de contenu (2026-10-18)."""
import io
import zipfile

from services.modele_formulaire import docx_vers_formulaire, docx_a_des_controles, est_formulaire

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def _liste(options, courant='Choisissez un élément.', plc=True):
    items = ''.join(f'<w:listItem w:displayText="{o}" w:value="{o}"/>' for o in options)
    return (f'<w:sdt><w:sdtPr>{"<w:showingPlcHdr/>" if plc else ""}<w:dropDownList>{items}</w:dropDownList></w:sdtPr>'
            f'<w:sdtContent><w:r><w:t>{courant}</w:t></w:r></w:sdtContent></w:sdt>')


def _texte():
    return ('<w:sdt><w:sdtPr><w:showingPlcHdr/><w:text/></w:sdtPr>'
            '<w:sdtContent><w:r><w:t>Cliquez ici pour entrer du texte.</w:t></w:r></w:sdtContent></w:sdt>')


def _cellule(contenu, fond=None):
    tcpr = f'<w:tcPr><w:shd w:val="clear" w:fill="{fond}"/></w:tcPr>' if fond else ''
    return f'<w:tc>{tcpr}<w:p>{contenu}</w:p></w:tc>'


def _docx(corps):
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>{corps}</w:body></w:document>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('word/document.xml', doc)
        z.writestr('word/_rels/document.xml.rels',
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
    return b.getvalue()


def _maquette():
    identite = ('<w:tr>' + _cellule('<w:r><w:t>N° </w:t></w:r>' + _liste(['0', '1']))
                + _cellule(_liste(['Feminin', 'Masculin'])) + '</w:tr>'
                + '<w:tr>' + _cellule(_liste(['Médecine', 'Maternité']))
                + _cellule('<w:r><w:t>Prescripteur:</w:t></w:r>' + _liste(['Dr A', 'Inf B', 'SFE C'])) + '</w:tr>')
    examen = ('<w:tr>' + _cellule('<w:r><w:t>BIOCHIMIE</w:t></w:r>', fond='D9D9D9') + '</w:tr>'
              + '<w:tr>' + _cellule('<w:r><w:t>Glycémie</w:t></w:r>') + _cellule(_texte() + '<w:r><w:t> g/l</w:t></w:r>')
              + _cellule(_liste(['0,70 – 1,10 g/l', 'Nouveau-né : 0,40 – 0,80 g/l'])) + '</w:tr>'
              + '<w:tr>' + _cellule(_liste(['Résultat:', 'Densité:'], courant='Résultat:', plc=False)) + '</w:tr>')
    return _docx(f'<w:tbl>{identite}{examen}</w:tbl>')


def test_detection_des_controles():
    assert docx_a_des_controles(_maquette())
    assert not docx_a_des_controles(_docx('<w:p><w:r><w:t>Texte simple</w:t></w:r></w:p>'))
    assert not docx_a_des_controles(b'pas un docx')


def test_listes_et_zones_gardees():
    html = docx_vers_formulaire(_maquette())
    assert est_formulaire(html)
    assert 'Choisissez un élément' not in html and 'Cliquez ici' not in html
    assert '<option>0,70 – 1,10 g/l</option>' in html          # choix du Word gardés
    assert 'mf-texte' in html and 'Glycémie' in html
    assert 'background:#D9D9D9' in html                        # fond de la ligne de titre
    assert 'data-defaut="1"' in html                           # « Résultat: » = valeur par défaut


def test_cadre_identification():
    html = docx_vers_formulaire(_maquette())
    assert 'class="mf-identite"' in html
    for cle in ('numero', 'nom', 'prenom', 'age', 'telephone', 'date'):
        assert f'data-id="{cle}"' in html
    assert 'data-id="sexe"' in html and '<option>Masculin</option>' in html
    assert 'data-id="prescripteur"' in html and '<option>SFE C</option>' in html
    assert 'data-id="service"' in html and '<option>Maternité</option>' in html
    # les lignes d'origine de l'identification (liste de chiffres du N°) ne sont plus là
    assert '<option>1</option>' not in html
    assert 'mf-texte notranslate' in html                       # noms jamais traduits


def test_echappement():
    html = docx_vers_formulaire(_docx('<w:p><w:r><w:t>&lt;script&gt;x&lt;/script&gt;</w:t></w:r></w:p>'
                                      + '<w:p>' + _liste(['&lt;b&gt;', 'ok']) + '</w:p>'))
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '<option>&lt;b&gt;</option>' in html


def test_proposition_de_modele():
    from services.modele_formulaire import proposer_modele, mots_modele
    biochimie = '<div class="modele-formulaire"><p>BIOCHIMIE</p><p>Glycémie</p><p>Créatininémie</p><p>Urémie</p></div>'
    hemostase = ('<div class="modele-formulaire"><p>HEMOSTASE</p><select class="mf-liste"><option>TS</option>'
                 '<option>Temps de céphaline activée (TCA)</option></select></div>')
    crp = '<div class="modele-formulaire"><p>RECHERCHE DE PROTEINE C REACTIVE (CRP)</p></div>'
    modeles = [(1, 'BIOCHIMIE', biochimie), (2, 'HEMOSTASE', hemostase), (3, 'CRP', crp)]
    assert proposer_modele('R832 Uree glycemie creatininemie', modeles) == 1
    assert proposer_modele('R704 TS + TCA', modeles) == 2
    assert proposer_modele('B123 CRP', modeles) == 3
    assert proposer_modele('R409 Serologie anti-streptococcique (ASLO)', modeles) is None
    # même résultat avec les mots déjà calculés (cache d'app.py)
    assert proposer_modele('R704 TS + TCA', [(i, mots_modele(n, h)) for i, n, h in modeles]) == 2
