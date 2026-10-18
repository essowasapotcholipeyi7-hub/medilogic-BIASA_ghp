# -*- coding: utf-8 -*-
"""Modèle de résultat « formulaire » importé d'un Word (patron, 2026-10-18 — maquettes du labo de la
structure 7). Les laboratoires préparent leurs comptes rendus dans Word avec des CONTRÔLES DE CONTENU :
« Choisissez un élément. » = liste déroulante (valeurs, normes, aspects...), « Cliquez ici pour entrer
du texte. » = zone à remplir. La conversion Word -> HTML habituelle (mammoth) perd ces listes et les
tableaux : il ne restait que « Choisissez un élément. » dans le résultat.

docx_vers_formulaire() garde la mise en page (paragraphes, tableaux, gras, tailles, couleurs, fonds) et
transforme chaque contrôle en champ : <select class="mf-liste"> avec les choix du Word, ou
<span class="mf-texte" contenteditable> pour une zone de texte. La saisie du résultat remplit ces champs ;
à l'enregistrement, le formulaire est « figé » côté navigateur (valeurs choisies en texte, lignes
laissées vides retirées) — voir templates/resultats_analyses.html.

Bibliothèque standard uniquement (zipfile + ElementTree), pas de dépendance en plus."""
import re
import zipfile
from html import escape
from io import BytesIO
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
MARQUEUR = 'modele-formulaire'
PLACEHOLDERS = ('choisissez un élément', 'cliquez ici pour entrer du texte', 'cliquez ou appuyez ici pour entrer du texte',
                'click here to enter text', 'choose an item')


def est_formulaire(html):
    return bool(html) and MARQUEUR in html[:300]


def docx_a_des_controles(data):
    """Le .docx contient-il des listes déroulantes ou zones de saisie Word ?"""
    try:
        x = zipfile.ZipFile(BytesIO(data)).read('word/document.xml')
    except Exception:
        return False
    return b'<w:sdt>' in x and (b'w:dropDownList' in x or b'w:comboBox' in x or b'w:showingPlcHdr' in x)


def _val(el, tag, attr='val'):
    if el is None:
        return None
    t = el.find(W + tag)
    return None if t is None else t.get(W + attr)


def _actif(el, tag):
    """Propriété booléenne Word (<w:b/>, <w:b w:val="0"/>...)."""
    if el is None:
        return False
    t = el.find(W + tag)
    return t is not None and t.get(W + 'val') not in ('0', 'false', 'off', 'none')


def _style_run(rpr):
    if rpr is None:
        return ''
    s = []
    if _actif(rpr, 'b'):
        s.append('font-weight:bold')
    if _actif(rpr, 'i'):
        s.append('font-style:italic')
    u = _val(rpr, 'u')
    if u and u != 'none':
        s.append('text-decoration:underline')
    sz = _val(rpr, 'sz')
    if sz and sz.isdigit():
        s.append(f'font-size:{int(sz) / 2:g}pt')
    col = _val(rpr, 'color')
    if col and re.fullmatch(r'[0-9A-Fa-f]{6}', col) and col.upper() != '000000':
        s.append(f'color:#{col}')
    if _actif(rpr, 'caps'):
        s.append('text-transform:uppercase')
    return ';'.join(s)


def _texte_brut(el):
    out = []
    for n in el.iter():
        if n.tag == W + 't':
            out.append(n.text or '')
        elif n.tag == W + 'tab':
            out.append(' ')
        elif n.tag in (W + 'br', W + 'cr'):
            out.append(' ')
    return ''.join(out)


class _Convertisseur:
    def __init__(self):
        self.n = 0
        self.identite_faite = False

    # ------------------------------------------------------------ identification
    def cadre_identite(self, lignes):
        """Le haut du compte rendu (N°, date, nom, sexe, âge, téléphone, service, prescripteur,
        hypothèse, prélèvement) : rempli par le logiciel à la saisie (attribut data-id) ; les listes du
        Word (sexe, service, prescripteurs, hypothèses, prélèvements) sont gardées."""
        listes = {}
        for tr in lignes:
            for sdt in tr.iter(W + 'sdt'):
                pr = sdt.find(W + 'sdtPr')
                if pr is None:
                    continue
                l = pr.find(W + 'dropDownList')
                if l is None:
                    l = pr.find(W + 'comboBox')
                if l is None:
                    continue
                opts = []
                for it in l.findall(W + 'listItem'):
                    t = (it.get(W + 'displayText') or it.get(W + 'value') or '').replace('\xa0', ' ').strip()
                    if t and t not in opts and not t.lower().startswith(PLACEHOLDERS):
                        opts.append(t)
                bas = ' | '.join(opts).lower()
                if any(o.lower() in ('masculin', 'feminin', 'féminin') for o in opts):
                    cle = 'sexe'
                elif sum(1 for o in opts if re.match(r'(dr|pr|inf|ide|sfe|sf|ap|ass)\b', o.lower())) >= 2:
                    cle = 'prescripteur'
                elif 'sang' in bas or 'urine' in bas or 'selles du' in bas:
                    cle = 'prelevement'
                elif 'médecine' in bas or 'medecine' in bas or 'maternité' in bas:
                    cle = 'service'
                elif 'bilan' in bas or 'syndrome' in bas:
                    cle = 'hypothese'
                else:
                    continue
                listes.setdefault(cle, opts)

        def texte(cle, largeur=''):
            self.n += 1
            st = f' style="min-width:{largeur}"' if largeur else ''
            nt = ' notranslate' if cle in ('nom', 'prenom') else ''   # jamais traduire un nom de patient
            return f'<span class="mf-champ mf-texte{nt}" data-mf="{self.n}" data-id="{cle}" contenteditable="true"{st}></span>'

        def champ(cle, largeur=''):
            if cle in listes:
                self.n += 1
                opts = ''.join(f'<option>{escape(o)}</option>' for o in listes[cle])
                return (f'<select class="mf-champ mf-liste" data-mf="{self.n}" data-id="{cle}"><option value=""></option>'
                        f'{opts}<option value="__autre__">✎ Autre…</option></select>')
            return texte(cle, largeur)

        return ('<table class="mf-identite">'
                f'<tr><td style="width:36%">N° {texte("numero", "7em")}</td>'
                f'<td style="width:30%;text-align:center">Compte rendu du <b>{texte("date", "5em")}</b></td>'
                '<td style="text-align:center"><u>Hypothèse de diagnostic :</u></td></tr>'
                f'<tr><td colspan="2" style="text-align:center;font-weight:bold;font-size:12pt">{texte("nom", "8em")} &nbsp; {texte("prenom", "8em")}</td>'
                f'<td style="text-align:center">{champ("hypothese")}</td></tr>'
                f'<tr><td colspan="2" style="text-align:center;font-weight:bold">{champ("sexe")} &nbsp; {texte("age", "3em")}'
                f' &nbsp;&nbsp;&nbsp; {texte("telephone", "6em")}</td>'
                f'<td style="text-align:center">{champ("prelevement")} {texte("date_prelevement", "5em")}</td></tr>'
                f'<tr><td style="font-weight:bold">{champ("service")}</td>'
                f'<td colspan="2"><b>Prescripteur :</b> {champ("prescripteur")}</td></tr>'
                '</table>')

    # ------------------------------------------------------------ champs
    def champ(self, sdt):
        pr = sdt.find(W + 'sdtPr')
        contenu = sdt.find(W + 'sdtContent')
        texte = _texte_brut(contenu) if contenu is not None else ''
        placeholder = pr is not None and pr.find(W + 'showingPlcHdr') is not None
        if not placeholder and texte.strip().lower().rstrip('.') in [p for p in PLACEHOLDERS]:
            placeholder = True
        if placeholder or texte.strip().lower().startswith(PLACEHOLDERS):
            texte = ''
        rpr = pr.find(W + 'rPr') if pr is not None else None
        style = _style_run(rpr)
        if contenu is not None and not style:
            r = contenu.find('.//' + W + 'rPr')
            style = _style_run(r)
        self.n += 1
        liste = None
        if pr is not None:
            liste = pr.find(W + 'dropDownList')
            if liste is None and pr.find(W + 'comboBox') is not None:
                # ⭐ 2026-10-18 (patron : « on n'arrive pas à saisir ») : une « liste modifiable » Word
                # (comboBox) se TAPE — on peut aussi y choisir un élément. Rendue en <select>, elle
                # empêchait d'écrire le résultat (ex. NFS : cases sans aucun choix).
                return self.combo(pr.find(W + 'comboBox'), texte, style)
        if liste is not None:
            options, vus = [], set()
            for it in liste.findall(W + 'listItem'):
                t = it.get(W + 'displayText')
                if t is None:
                    t = it.get(W + 'value') or ''
                t = t.replace('\xa0', ' ')
                if not t.strip() or t.strip().lower().startswith(PLACEHOLDERS):
                    continue
                cle = t.strip()
                if cle in vus:
                    continue
                vus.add(cle)
                options.append(t.strip())
            courant = texte.strip()
            if courant and courant not in vus:
                options.insert(0, courant)
            opts = ['<option value=""></option>'] + [
                f'<option{" selected" if o == courant else ""}>{escape(o)}</option>' for o in options]
            opts.append('<option value="__autre__">✎ Autre…</option>')
            # data-defaut : la valeur montrée par le Word (« Résultat: », « ans »...) ne compte pas comme saisie
            return (f'<select class="mf-champ mf-liste" data-mf="{self.n}"' + (' data-defaut="1"' if courant else '')
                    + (f' style="{style}"' if style else '') + '>' + ''.join(opts) + '</select>')
        # zone de texte (texte simple, texte enrichi, date)
        return (f'<span class="mf-champ mf-texte" data-mf="{self.n}" contenteditable="true"'
                + (f' style="{style}"' if style else '') + f'>{escape(texte.strip())}</span>')

    def combo(self, liste, texte, style):
        """« Liste modifiable » Word : case à taper, avec les choix du Word proposés (datalist) ;
        sans aucun choix, simple zone de texte."""
        options, vus = [], set()
        for it in liste.findall(W + 'listItem'):
            t = it.get(W + 'displayText')
            if t is None:
                t = it.get(W + 'value') or ''
            t = t.replace('\xa0', ' ').rstrip()
            if not t.strip() or t.strip().lower().startswith(PLACEHOLDERS) or t in vus:
                continue
            vus.add(t)
            options.append(t)   # espace / virgule de tête gardés : « , à monocytose » se colle au mot d'avant
        courant = texte.strip()
        if not options:
            return (f'<span class="mf-champ mf-texte" data-mf="{self.n}" contenteditable="true"'
                    + (f' style="{style}"' if style else '') + f'>{escape(courant)}</span>')
        liste_id = f'mfl-{self.n}'
        return (f'<input type="text" class="mf-champ mf-combo" data-mf="{self.n}" list="{liste_id}" autocomplete="off"'
                + (f' value="{escape(courant)}" data-defaut="1"' if courant else '')
                + (f' style="{style}"' if style else '') + '>'
                + f'<datalist id="{liste_id}">' + ''.join(f'<option>{escape(o)}</option>' for o in options) + '</datalist>')

    def _est_champ(self, sdt):
        """Un contrôle « feuille » (liste / zone) — un contrôle qui en contient d'autres est un simple
        regroupement : on rend son contenu."""
        pr = sdt.find(W + 'sdtPr')
        contenu = sdt.find(W + 'sdtContent')
        if pr is not None and (pr.find(W + 'dropDownList') is not None or pr.find(W + 'comboBox') is not None):
            return True
        if contenu is not None and contenu.find('.//' + W + 'sdt') is not None:
            return False
        if pr is not None and (pr.find(W + 'showingPlcHdr') is not None or pr.find(W + 'text') is not None
                               or pr.find(W + 'date') is not None):
            return True
        t = _texte_brut(contenu).strip().lower() if contenu is not None else ''
        return t.startswith(PLACEHOLDERS)

    # ------------------------------------------------------------ en ligne
    def en_ligne(self, parent, remplacement=None):
        """Contenu d'un paragraphe. `remplacement` : champ qui remplace le texte (contrôle posé sur
        tout un paragraphe ou une cellule) — inséré une seule fois."""
        out = []
        for el in parent:
            tag = el.tag
            if tag == W + 'r':
                if remplacement is not None:
                    if remplacement[0]:
                        out.append(remplacement[0])
                        remplacement[0] = ''
                    continue
                out.append(self.run(el))
            elif tag == W + 'sdt':
                if self._est_champ(el):
                    out.append(self.champ(el))
                else:
                    c = el.find(W + 'sdtContent')
                    if c is not None:
                        out.append(self.en_ligne(c, remplacement))
            elif tag in (W + 'hyperlink', W + 'smartTag', W + 'ins', W + 'fldSimple') or tag == W + 'customXml':
                out.append(self.en_ligne(el, remplacement))
        if remplacement is not None and remplacement[0]:
            out.append(remplacement[0])
            remplacement[0] = ''
        return ''.join(out)

    def run(self, r):
        if r.find('.//' + W + 'drawing') is not None or r.find('.//' + MC + 'AlternateContent') is not None \
                or r.find(W + 'pict') is not None:
            # formes / images (traits décoratifs, logos) : ignorées
            if not any(n.tag == W + 't' for n in r):
                return ''
        morceaux = []
        for n in r:
            if n.tag == W + 't':
                morceaux.append(escape((n.text or '').replace('\xa0', ' ')).replace('  ', ' &nbsp;'))
            elif n.tag == W + 'tab':
                morceaux.append('&emsp;')
            elif n.tag in (W + 'br', W + 'cr'):
                morceaux.append('<br>')
            elif n.tag == W + 'sym':
                ch = n.get(W + 'char') or ''
                try:
                    code = int(ch, 16)
                    morceaux.append(escape(chr(code - 0xF000 if code >= 0xF000 else code)))
                except ValueError:
                    pass
        txt = ''.join(morceaux)
        if not txt:
            return ''
        style = _style_run(r.find(W + 'rPr'))
        va = _val(r.find(W + 'rPr'), 'vertAlign')
        if va == 'superscript':
            txt = f'<sup>{txt}</sup>'
        elif va == 'subscript':
            txt = f'<sub>{txt}</sub>'
        return f'<span style="{style}">{txt}</span>' if style else txt

    # ------------------------------------------------------------ blocs
    def paragraphe(self, p, remplacement=None):
        ppr = p.find(W + 'pPr')
        styles = ['margin:0']
        jc = _val(ppr, 'jc')
        if jc in ('center', 'right'):
            styles.append(f'text-align:{jc}')
        elif jc in ('both', 'distribute'):
            styles.append('text-align:justify')
        ind = ppr.find(W + 'ind') if ppr is not None else None
        if ind is not None:
            gauche = ind.get(W + 'left') or ind.get(W + 'start')
            if gauche and gauche.lstrip('-').isdigit() and int(gauche) > 0:
                styles.append(f'padding-left:{min(int(gauche) / 20, 200):.0f}pt')
        shd = ppr.find(W + 'shd') if ppr is not None else None
        if shd is not None and re.fullmatch(r'[0-9A-Fa-f]{6}', shd.get(W + 'fill') or '') and shd.get(W + 'fill').upper() != 'FFFFFF':
            styles.append(f'background:#{shd.get(W + "fill")}')
        contenu = self.en_ligne(p, remplacement)
        if not re.sub(r'<[^>]+>|&nbsp;|&emsp;|\s', '', contenu) and 'mf-champ' not in contenu:
            contenu = '&nbsp;'
        return f'<p style="{";".join(styles)}">{contenu}</p>'

    def blocs(self, parent, remplacement=None):
        out = []
        for el in parent:
            tag = el.tag
            if tag == W + 'p':
                out.append(self.paragraphe(el, remplacement))
                remplacement = None
            elif tag == W + 'tbl':
                out.append(self.tableau(el))
            elif tag == W + 'sdt':
                c = el.find(W + 'sdtContent')
                if c is None:
                    continue
                if self._est_champ(el):
                    out.append(self.blocs(c, [self.champ(el)]))
                else:
                    out.append(self.blocs(c, remplacement))
        return ''.join(out)

    def cellules(self, tr, remplacement=None):
        """Cellules d'une ligne, y compris celles enveloppées dans un contrôle de contenu."""
        res = []
        for el in tr:
            if el.tag == W + 'tc':
                res.append((el, remplacement))
            elif el.tag == W + 'sdt':
                c = el.find(W + 'sdtContent')
                if c is not None:
                    rep = [self.champ(el)] if self._est_champ(el) else remplacement
                    res.extend(self.cellules(c, rep))
        return res

    def lignes(self, tbl):
        res = []
        for el in tbl:
            if el.tag == W + 'tr':
                res.append(el)
            elif el.tag == W + 'sdt':
                c = el.find(W + 'sdtContent')
                if c is not None:
                    res.extend(self.lignes(c))
        return res

    def tableau(self, tbl):
        lignes_id = None
        if not self.identite_faite:
            toutes = self.lignes(tbl)
            for i, tr in enumerate(toutes[:8]):
                if 'prescripteur' in _texte_brut(tr).lower():
                    lignes_id = toutes[:i + 1]
                    break
        if lignes_id:
            self.identite_faite = True
            reste = self.tableau_lignes(tbl, [tr for tr in self.lignes(tbl) if tr not in lignes_id])
            return self.cadre_identite(lignes_id) + reste
        return self.tableau_lignes(tbl, self.lignes(tbl))

    def tableau_lignes(self, tbl, lignes):
        if not lignes:
            return ''
        tblpr = tbl.find(W + 'tblPr')
        bordures = tblpr.find(W + 'tblBorders') if tblpr is not None else None
        avec_bordures = bordures is not None and any(
            (b.get(W + 'val') or 'nil') not in ('nil', 'none') for b in bordures)
        # fusions verticales : on compte les cellules « continue » sous chaque cellule « restart »
        grille = []
        for tr in lignes:
            ligne, col = [], 0
            for tc, rep in self.cellules(tr):
                tcpr = tc.find(W + 'tcPr')
                span = int(_val(tcpr, 'gridSpan') or 1)
                vm = tcpr.find(W + 'vMerge') if tcpr is not None else None
                etat = None if vm is None else (vm.get(W + 'val') or 'continue')
                ligne.append({'tc': tc, 'rep': rep, 'col': col, 'span': span, 'vm': etat, 'rowspan': 1})
                col += span
            grille.append(ligne)
        for i, ligne in enumerate(grille):
            for c in ligne:
                if c['vm'] == 'restart':
                    for suite in grille[i + 1:]:
                        sous = next((x for x in suite if x['col'] == c['col']), None)
                        if sous and sous['vm'] == 'continue':
                            c['rowspan'] += 1
                        else:
                            break
        out = [f'<table class="mf-table{" mf-bordure" if avec_bordures else ""}">']
        for ligne in grille:
            out.append('<tr>')
            for c in ligne:
                if c['vm'] == 'continue':
                    continue
                tcpr = c['tc'].find(W + 'tcPr')
                styles = []
                shd = tcpr.find(W + 'shd') if tcpr is not None else None
                fill = shd.get(W + 'fill') if shd is not None else None
                if fill and re.fullmatch(r'[0-9A-Fa-f]{6}', fill) and fill.upper() != 'FFFFFF':
                    styles.append(f'background:#{fill}')
                tcb = tcpr.find(W + 'tcBorders') if tcpr is not None else None
                if tcb is not None:
                    for cote in ('top', 'bottom', 'left', 'right'):
                        b = tcb.find(W + cote)
                        if b is not None and (b.get(W + 'val') or 'nil') not in ('nil', 'none'):
                            styles.append(f'border-{cote}:1px solid #444')
                va = _val(tcpr, 'vAlign')
                if va in ('center', 'bottom'):
                    styles.append(f'vertical-align:{"middle" if va == "center" else "bottom"}')
                attrs = ''
                if c['span'] > 1:
                    attrs += f' colspan="{c["span"]}"'
                if c['rowspan'] > 1:
                    attrs += f' rowspan="{c["rowspan"]}"'
                if styles:
                    attrs += f' style="{";".join(styles)}"'
                out.append(f'<td{attrs}>{self.blocs(c["tc"], c["rep"])}</td>')
            out.append('</tr>')
        out.append('</table>')
        return ''.join(out)


REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_CONTACT = re.compile(r'(e-?mail|b\.?\s?p\b|web|t[ée]l|http|www|@|lom[ée]|togo|\d{2} \d{2} \d{2})', re.I)


def _en_tete(z, racine):
    """En-tête de la structure tiré de l'en-tête du Word : logo à gauche avec le nom court, titre au
    centre, coordonnées à droite. Rien si le Word n'a pas d'en-tête lisible."""
    import base64
    try:
        rels_doc = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))}
    except Exception:
        return ''
    refs = racine.findall('.//' + W + 'headerReference')
    meilleur = None
    for ref in refs:
        cible = rels_doc.get(ref.get(REL + 'id'))
        if not cible:
            continue
        try:
            h = ET.fromstring(z.read('word/' + cible))
        except Exception:
            continue
        texte = _texte_brut(h)
        if meilleur is None or len(texte.strip()) > len(meilleur[1].strip()):
            meilleur = (cible, texte, h)
    if not meilleur or len(meilleur[1].strip()) < 10:
        return ''
    cible, _, h = meilleur
    logo = ''
    blip = h.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
    if blip is not None:
        try:
            rels_h = {r.get('Id'): r.get('Target')
                      for r in ET.fromstring(z.read('word/_rels/' + cible.split('/')[-1] + '.rels'))}
            chemin = 'word/' + rels_h[blip.get(REL + 'embed')]
            img = z.read(chemin)
            mime = 'image/png' if chemin.lower().endswith('.png') else 'image/jpeg'
            logo = f'<img src="data:{mime};base64,{base64.b64encode(img).decode()}" alt="" style="max-height:80px;max-width:120px">'
        except Exception:
            logo = ''
    contacts, nom, titre, document = [], '', '', ''
    for p in h.iter(W + 'p'):
        brut = ''.join((n.text or '') if n.tag == W + 't' else '\t' for n in p.iter() if n.tag in (W + 't', W + 'tab'))
        segments = [x.strip() for x in re.split(r'[ \xa0]{3,}|\t+', brut.replace('\xa0', ' ')) if x.strip()]
        lignes_contact = [x for x in segments if _CONTACT.search(x)]
        if lignes_contact:
            contacts.append(' — '.join(lignes_contact))
        for x in segments:
            if x in lignes_contact:
                continue
            if 'compte rendu' in x.lower():
                document = re.sub(r'ANALALYSES', 'ANALYSES', re.sub(r'\s+', ' ', x))
            elif len(x.split()) <= 4 and not nom:
                nom = x
            elif not titre:
                titre = x
    if not (logo or nom or titre or contacts):
        return ''
    return ('<table class="mf-entete"><tr>'
            f'<td style="width:22%;text-align:center">{logo}<div style="font-weight:bold;font-size:13pt">{escape(nom)}</div></td>'
            f'<td style="text-align:center;vertical-align:middle"><div style="font-weight:bold;font-style:italic;font-size:12pt">{escape(titre)}</div>'
            f'<div style="margin-top:14px;font-size:11pt">{escape(document)}</div></td>'
            f'<td style="width:30%;font-size:9.5pt;font-weight:bold;vertical-align:middle">{"<br>".join(escape(c) for c in contacts)}</td>'
            '</tr></table>')


STYLE = """<style>
.modele-formulaire{font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#000;line-height:1.25}
.modele-formulaire .mf-table{border-collapse:collapse;width:100%;margin:2px 0}
.modele-formulaire .mf-table td{padding:1px 5px;vertical-align:top}
.modele-formulaire .mf-bordure td{border:1px solid #555}
.modele-formulaire .mf-entete{width:100%;border-collapse:collapse;margin-bottom:4px}
.modele-formulaire .mf-entete td{padding:2px 4px}
.modele-formulaire .mf-identite{width:100%;border-collapse:collapse;border:2px solid #333;border-left:12px solid #666;margin:4px 0 12px}
.modele-formulaire .mf-identite td{padding:3px 8px;border-bottom:1px solid #bbb}
.modele-formulaire .mf-liste{field-sizing:content;min-width:7em;min-height:1.8em;max-width:100%;font:inherit;border:1px solid #0d6efd;border-radius:3px;background:#eef5ff;padding:1px 2px;cursor:pointer}
.modele-formulaire .mf-combo{field-sizing:content;min-width:7em;min-height:1.8em;max-width:100%;font:inherit;border:1px solid #0d6efd;border-radius:3px;background:#eef5ff;padding:1px 4px}
.modele-formulaire .mf-texte{display:inline-block;min-width:5em;min-height:1.2em;border-bottom:1px solid #0d6efd;background:#eef5ff;padding:0 3px;outline:none;cursor:text}
.modele-formulaire .mf-texte:focus,.modele-formulaire .mf-liste:focus,.modele-formulaire .mf-combo:focus{background:#fff8d6}
.modele-formulaire .mf-norme{white-space:nowrap}
.modele-formulaire tr.mf-retiree{opacity:.3;text-decoration:line-through}
</style>"""


def docx_vers_formulaire(data):
    """.docx (octets) -> HTML du formulaire (marqueur MARQUEUR au début)."""
    z = zipfile.ZipFile(BytesIO(data))
    racine = ET.fromstring(z.read('word/document.xml'))
    body = racine.find(W + 'body')
    conv = _Convertisseur()
    contenu = conv.blocs(body)
    # paragraphes vides en série (espacements Word) : un seul
    contenu = re.sub(r'(?:<p style="margin:0">&nbsp;</p>){2,}', '<p style="margin:0">&nbsp;</p>', contenu)
    return f'<div class="{MARQUEUR}" data-champs="{conv.n}">{STYLE}{_en_tete(z, racine)}{contenu}</div>'


def _norm_txt(t):
    import unicodedata
    t = unicodedata.normalize('NFKD', t or '')
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def _libelle_norme(tete):
    """« NORME 16jr – 2 mois » -> « 16 jours – 2 mois », « NORME HOMME » -> « Homme »."""
    t = re.sub(r'^\s*NORMES?\s*', '', tete, flags=re.I).strip(' :').strip()
    t = re.sub(r'(\d+)\s*(?:jr|j)\b', r'\1 jours', t)
    return t[:1].upper() + t[1:].lower() if t.isupper() else t


def nfs_depuis_docx(data):
    """⭐ 2026-10-18 (patron : « quand on prend NFS pour remplir, c'est NFS qui doit venir ») : fiche
    NFS (hémogramme) tirée du Word « NORMES NFS » du labo, où la NFS n'est qu'une partie d'un compte
    rendu mélangé (GE, selles, CRP, VS, biochimie...). On garde : en-tête, cadre d'identification,
    paramètres avec leurs unités (cases à taper), une liste « Normes » avec les jeux de normes du Word
    par âge et par sexe (choisie toute seule selon le patient, elle remplit la colonne NORMES ligne
    par ligne) et l'interprétation (choix du Word). Lève ValueError si le Word n'a pas cette partie."""
    import json
    z = zipfile.ZipFile(BytesIO(data))
    racine = ET.fromstring(z.read('word/document.xml'))
    body = racine.find(W + 'body')
    conv = _Convertisseur()

    identite = ''
    for tbl in body.iter(W + 'tbl'):
        toutes = conv.lignes(tbl)
        for i, tr in enumerate(toutes[:8]):
            if 'prescripteur' in _texte_brut(tr).lower():
                identite = conv.cadre_identite(toutes[:i + 1])
                break
        if identite:
            break

    candidats = [t for t in body.iter(W + 'tbl')
                 if 'hematocrite' in _norm_txt(_texte_brut(t)) and 'biochimie' not in _norm_txt(_texte_brut(t))]
    if not candidats:
        raise ValueError("Pas de tableau NFS (hématocrite) dans ce Word")
    tbl = min(candidats, key=lambda t: len(_texte_brut(t)))
    lignes = conv.lignes(tbl)

    # jeux de normes : la liste de la colonne NORMES (1re ligne, cellule fusionnée vers le bas)
    jeux = {}
    for sdt in lignes[0].iter(W + 'sdt'):
        pr = sdt.find(W + 'sdtPr')
        l = None if pr is None else (pr.find(W + 'comboBox') if pr.find(W + 'comboBox') is not None else pr.find(W + 'dropDownList'))
        if l is None:
            continue
        for it in l.findall(W + 'listItem'):
            brut = (it.get(W + 'displayText') or it.get(W + 'value') or '').replace('\xa0', ' ')
            m = re.match(r'\s*(NORMES?\s.*?)(?::\s*|\s{2,})(.*)$', brut, flags=re.I)
            if not m:
                continue
            valeurs = [v.strip() for v in re.split(r'\s{2,}', m.group(2).strip()) if v.strip()]
            if len(valeurs) != 12:      # ex. « ♀ / ♀enceinte » (deux normes dans une case) : déjà en Femme / Femme enceinte
                continue
            jeux[_libelle_norme(m.group(1))] = [re.sub(r'\s*[-–]\s*', ' – ', v) for v in valeurs]
    if not jeux:
        raise ValueError("Pas de normes NFS lisibles dans ce Word")

    # paramètres : libellé | résultat + unité | % | norme
    lignes_html, i_norme, interpretation = [], 0, ''
    for tr in lignes[1:]:
        cellules = conv.cellules(tr)
        if not cellules:
            continue
        sous = cellules[0][0].find('.//' + W + 'tbl')
        if sous is not None:                       # dernière ligne : interprétation
            interpretation = conv.tableau(sous)
            continue
        libelle = _texte_brut(cellules[0][0]).strip().rstrip(':').strip()
        if not libelle:
            continue
        resultat = conv.blocs(cellules[1][0], cellules[1][1]) if len(cellules) > 1 else ''
        pourcent = conv.blocs(cellules[2][0], cellules[2][1]) if len(cellules) > 2 else ''
        texte_norme = _texte_brut(cellules[3][0]).strip() if len(cellules) > 3 else ''
        if texte_norme:                            # norme écrite dans le Word (plaquettes)
            norme = escape(texte_norme)
        elif i_norme < 12:
            norme = f'<span class="mf-norme" data-i="{i_norme}"></span>'
            i_norme += 1
        else:
            norme = ''
        libelle = libelle.replace('Polynuclaires', 'Polynucléaires')
        # formule leucocytaire : le Word CALCULE le nombre absolu (leucocytes x % / 100) — même calcul
        # à la saisie (templates/resultats_analyses.html, calculerFormuleNfs)
        if 'mf-champ' in pourcent and 'mf-champ' not in resultat:
            resultat = '<span class="mf-calcul" data-nfs="abs"></span> /µL'
            pourcent = pourcent.replace('class="mf-champ', 'data-nfs="pct" class="mf-champ', 1)
        elif 'leucocyte' in _norm_txt(libelle):
            resultat = resultat.replace('class="mf-champ', 'data-nfs="gb" class="mf-champ', 1)
        lignes_html.append(f'<tr><td style="font-weight:bold">{escape(libelle)}</td><td>{resultat}</td>'
                           f'<td>{pourcent}</td><td style="text-align:center">{norme}</td></tr>')

    conv.n += 1
    options = ''.join(f'<option>{escape(n)}</option>' for n in jeux)
    selecteur = (f'<select class="mf-champ mf-liste mf-normes" data-mf="{conv.n}" data-garder="1" '
                 f'data-normes="{escape(json.dumps(jeux, ensure_ascii=False), quote=True)}">'
                 f'<option value=""></option>{options}</select>')
    entete = ('<tr><td style="background:#D9D9D9;font-weight:bold;text-align:center;width:34%">PARAMÈTRES</td>'
              '<td colspan="2" style="background:#D9D9D9;font-weight:bold;text-align:center">RÉSULTATS</td>'
              f'<td style="background:#D9D9D9;font-weight:bold;text-align:center">NORMES {selecteur}</td></tr>')
    titre = ('<p style="margin:6px 0 0;text-align:center;font-weight:bold;font-size:13pt;text-decoration:underline">NFS (Hémogramme)</p>'
             '<p style="margin:0 0 4px;text-align:center;font-style:italic">Méthode par cytométrie en flux et impédance.</p>')
    tableau = f'<table class="mf-table mf-bordure">{entete}{"".join(lignes_html)}</table>'
    if interpretation:
        interpretation = ('<p style="margin:8px 0 2px;font-weight:bold;text-decoration:underline">INTERPRÉTATION :</p>'
                          + interpretation.replace('INTERPRETATION', '', 1))
    return (f'<div class="{MARQUEUR}" data-champs="{conv.n}">{STYLE}{_en_tete(z, racine)}{identite}'
            f'{titre}{tableau}{interpretation}</div>')


# ------------------------------------------------------------ modèle proposé pour un acte
_MOTS_VIDES = {'de', 'du', 'des', 'la', 'le', 'les', 'et', 'ou', 'un', 'une', 'en', 'au', 'aux', 'par', 'sur', 'avec',
               'test', 'tests', 'dosage', 'isole', 'rapide', 'rapides', 'valides', 'recherche', 'examen', 'model', 'modele',
               'serologie', 'taux', 'bilan', 'fractions', 'total', 'totale', 'anticorps', 'bandelettes', 'complete', 'anti',
               'sang', 'sanguin', 'urinaire', 'urinaires', 'directe', 'temps'}


def _norm(t):
    import unicodedata
    t = unicodedata.normalize('NFKD', t or '')
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def _mots(texte, paires=False):
    mots = set()
    brut = re.findall(r'[a-z0-9]+', _norm(texte))
    if paires:   # « Ag HBs » -> « aghbs »
        mots.update(a + b for a, b in zip(brut, brut[1:]) if len(a + b) >= 4 and not (a + b).isdigit())
    for m in brut:
        if m in _MOTS_VIDES or m.isdigit():
            continue
        if len(m) >= 3 or (len(m) == 2 and m.isalpha()):
            mots.add(m)
    return mots


def _texte_html(html, listes=False):
    """Texte d'un modèle, sans l'en-tête ni le cadre d'identification ; listes=True : seulement les
    choix des listes déroulantes (paramètres d'hémostase, normes...), listes=False : le reste."""
    html = re.sub(r'<style.*?</style>|<table class="mf-(?:entete|identite)".*?</table>', ' ', html or '', flags=re.S)
    choix = re.findall(r'<option>(.*?)</option>', html, flags=re.S)
    if listes:
        return ' '.join(choix)
    html = re.sub(r'<select.*?</select>', ' ', html, flags=re.S)
    return re.sub(r'<[^>]+>|&[a-z]+;', ' ', html)


def mots_modele(nom, html):
    """Mots d'un modèle (nom, texte, choix des listes) — calculés une fois, gardés en cache par app.py."""
    return (_mots(nom), _mots(_texte_html(html)), _mots(_texte_html(html, listes=True)))


def proposer_modele(acte_nom, modeles):
    """Modèle formulaire le plus probable pour un acte, d'après son nom et son contenu — None si rien
    de net. `modeles` : [(id, nom, contenu_html)] ou [(id, mots_modele(...))]. Le code de l'acte (R831...)
    est ignoré."""
    acte = re.sub(r'^[A-Z]{1,3}\d{2,4}\s*', '', (acte_nom or '').strip())
    mots_acte = _mots(acte, paires=True)
    if not mots_acte:
        return None

    def present(mot, mots):
        # « creatinine » trouve « creatininemie », « bhcg » contient « hcg »
        return any(m == mot or (len(mot) >= 5 and m.startswith(mot[:max(5, len(mot) - 2)]))
                   or (len(mot) >= 3 and len(m) >= 4 and mot in m) for m in mots)

    def abrege(mot, mots):
        # nom de modèle abrégé : « toxo » pour « toxoplasmose », « copro » pour « coproculture »
        return any(len(m) >= 4 and mot.startswith(m) for m in mots)

    notes = []
    for m in modeles:
        mid, (mots_nom, mots_contenu, mots_listes) = (m[0], m[1]) if len(m) == 2 else (m[0], mots_modele(m[1], m[2]))
        note = sum(3 if present(m, mots_nom) else (2 if abrege(m, mots_nom) else 0) for m in mots_acte)             + sum(1 if present(m, mots_contenu) else (0.5 if present(m, mots_listes) else 0) for m in mots_acte)
        if note:
            notes.append((note, -len(mots_contenu | mots_listes), mid))
    if not notes:
        return None
    notes.sort(reverse=True)
    if len(notes) > 1 and notes[0][0] == notes[1][0] and notes[0][1] == notes[1][1]:
        return None
    return notes[0][2]
