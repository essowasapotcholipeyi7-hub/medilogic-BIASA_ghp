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
                return (f'<select class="mf-champ mf-liste" data-mf="{self.n}" data-id="{cle}"><option value="">— choisir —</option>'
                        f'{opts}<option value="__autre__">✎ Autre…</option></select>')
            return texte(cle, largeur)

        def saisie(cle, largeur='12em'):
            """Case à taper avec les choix du Word proposés (hypothèse, nature du prélèvement)."""
            if cle not in listes:
                return texte(cle, largeur)
            self.n += 1
            liste_id = f'mfl-{self.n}'
            return (f'<input type="text" class="mf-champ mf-combo" data-mf="{self.n}" data-id="{cle}" list="{liste_id}" '
                    f'autocomplete="off" placeholder="taper ou choisir" style="min-width:{largeur}">'
                    f'<datalist id="{liste_id}">' + ''.join(f'<option>{escape(o)}</option>' for o in listes[cle]) + '</datalist>')

        def item(libelle, contenu):
            # ⭐ 2026-10-18 (patron : « là où il y a les listes déroulantes, il n'y a aucun titre ») : chaque
            # case a son intitulé ; à l'impression, une case laissée vide disparaît avec son intitulé
            return f'<span class="mf-item"><span class="mf-libelle">{libelle} :</span> {contenu}</span>'

        # ⭐ 2026-10-18 : numéro, dates (compte rendu, prélèvement), identité, sexe et âge remplis par le
        # logiciel depuis la fiche du patient (le sexe n'est à choisir que s'il manque dans la fiche)
        return ('<table class="mf-identite">'
                f'<tr><td style="width:30%">{item("N°", texte("numero", "5em"))}</td>'
                f'<td style="width:35%">{item("Compte rendu du", texte("date", "6em"))}</td>'
                f'<td>{item("Prélèvement du", texte("date_prelevement", "6em"))}</td></tr>'
                f'<tr><td colspan="2" style="font-size:12pt">{item("Nom et prénom", "<b>" + texte("nom", "8em") + " " + texte("prenom", "8em") + "</b>")}</td>'
                f'<td>{item("Sexe", champ("sexe"))} &nbsp; {item("Âge", texte("age", "4em"))}</td></tr>'
                f'<tr><td>{item("Téléphone", texte("telephone", "7em"))}</td>'
                f'<td>{item("Service", champ("service"))}</td>'
                f'<td>{item("Prescripteur", champ("prescripteur"))}</td></tr>'
                f'<tr><td colspan="2">{item("Hypothèse de diagnostic", saisie("hypothese", "16em"))}</td>'
                f'<td>{item("Nature du prélèvement", saisie("prelevement", "10em"))}</td></tr>'
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
            opts = ['<option value="">— choisir —</option>'] + [
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
        return (f'<input type="text" class="mf-champ mf-combo" data-mf="{self.n}" list="{liste_id}" autocomplete="off" placeholder="taper ou choisir"'
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
.modele-formulaire .mf-item{display:inline-block;margin-right:6px}
.modele-formulaire .mf-libelle{font-size:9.5pt;color:#555;font-weight:normal}
.modele-formulaire .mf-a-completer{outline:2px solid #fd7e14}
.modele-formulaire .mf-combo::placeholder{color:#8aa;font-style:italic;font-size:9pt}
.modele-formulaire tr.mf-retiree{opacity:.3;text-decoration:line-through}
.modele-formulaire .mf-libre{outline:1px dashed #9ec5fe;outline-offset:3px;border-radius:3px;cursor:text}
.modele-formulaire .mf-libre:focus{outline:2px solid #0d6efd;background:#fffef5}
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


def adapter_entete(html, structure, type_prestation='analyse'):
    """⭐ 2026-10-18 (patron : « je me suis connecté dans une autre structure, mais je vois le logo et
    les informations d'une autre structure ») : l'en-tête d'un modèle formulaire vient du Word de la
    structure qui l'a fourni. On le garde s'il est bien celui de la structure connectée (même nom ou
    même e-mail), sinon il est remplacé par l'en-tête de la structure connectée (logo, nom, adresse,
    téléphone, e-mail). `structure` : fiche de la structure (dict : nom, adresse, telephone, email,
    logo_url)."""
    if not est_formulaire(html):
        return html
    if 'mf-entete-fixe' in html[:20000]:
        return html   # ⭐ 2026-10-19 : en-tête du Word gardé tel quel (voulu par la structure, ex. radiologie Valeo)
    structure = structure or {}
    nom = (structure.get('nom') or '').strip()
    email = (structure.get('email') or '').strip().lower()
    m = re.search(r'<table class="mf-entete">.*?</table>', html, flags=re.S)
    if m:
        texte = _norm_txt(re.sub(r'<[^>]+>', ' ', m.group(0)))
        if (nom and _norm_txt(nom) in texte) or (email and email in texte):
            # en-tête du Word de la structure elle-même : gardé, mais avec le logo ENREGISTRÉ de la
            # structure (s'il existe) plutôt que la copie collée dans le Word
            if structure.get('logo_url'):
                nouvel = re.sub(r'<img src="data:image/[^"]*"', f'<img src="{escape(structure["logo_url"])}"', m.group(0), count=1)
                return html.replace(m.group(0), nouvel, 1)
            return html
    if not nom:
        return html
    logo = structure.get('logo_url') or ''
    titre = "COMPTE RENDU D'ANALYSES MÉDICALES" if type_prestation == 'analyse' else "COMPTE RENDU D'EXAMEN"
    contacts = [c for c in (structure.get('adresse') or '', f"Tél : {structure['telephone']}" if structure.get('telephone') else '',
                            f"E-mail : {structure['email']}" if structure.get('email') else '') if c]
    entete = ('<table class="mf-entete"><tr>'
              f'<td style="width:22%;text-align:center">'
              + (f'<img src="{escape(logo)}" alt="" style="max-height:80px;max-width:120px">' if logo else '') + '</td>'
              f'<td style="text-align:center;vertical-align:middle"><div style="font-weight:bold;font-size:14pt">{escape(nom)}</div>'
              f'<div style="margin-top:10px;font-size:11pt">{titre}</div></td>'
              f'<td style="width:30%;font-size:9.5pt;font-weight:bold;vertical-align:middle;white-space:pre-line">{escape(chr(10).join(contacts))}</td>'
              '</tr></table>')
    if m:
        return html.replace(m.group(0), entete, 1)
    i = html.find('</style>')
    return html[:i + 8] + entete + html[i + 8:] if i >= 0 else html


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
                 f'<option value="">— âge / sexe —</option>{options}</select>')
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
               'sang', 'sanguin', 'urinaire', 'urinaires', 'directe', 'temps',
               # ⭐ 2026-10-19 : radiologie (Valeo) — mots présents dans presque tous les actes et comptes rendus
               'radiologique', 'radiologiques', 'radiographie', 'radiographique', 'incidence', 'incidences',
               'minimum', 'deux', 'trois', 'face', 'profil', 'standard', 'sans', 'preparation', 'element',
               'quel', 'que', 'soit', 'nombre', 'plus', 'inferieur', 'egal', 'incluant', 'davantage',
               'acide', 'quantitative', 'quantitatif', 'qualitative', 'qualitatif', 'tri', 'totales', 'totaux',
               'elisa', 'autres', 'autre', 'methode', 'methodes', 'immunologique', 'immunologiques', 'realisation',
               'segment', 'segments', 'squelette', 'membre', 'membres'}
# acte -> mot du modèle (ex. « Examen radiologique des poumons et du cœur » -> modèle Thorax)
_SYNONYMES = {'poumon': 'thorax', 'poumons': 'thorax', 'coeur': 'thorax', 'pulmonaire': 'thorax',
              'hanche': 'bassin', 'salpingograhie': 'hysterosalpingographie', 'salpingographie': 'hysterosalpingographie',
              # ⭐ 2026-10-20 : biologie (Valeo) — nom de l'acte -> mot du compte rendu
              'uree': 'uremie', 'urique': 'uricemie', 'albuminemie': 'albumine', 'calcemie': 'calcium',
              'magnesemie': 'magnesium', 'iodothyronine': 'thyroidiennes', 'thyroxine': 'thyroidiennes',
              'thyreostimuline': 'thyroidiennes', 'ggt': 'gamma', 'glucose': 'glycemie', 'nfs': 'hemogramme',
              'transaminases': 'asat', 'sgot': 'asat', 'sgpt': 'alat',
              'phosphatases': 'pal', 'alcalines': 'pal'}
# ⭐ 2026-10-20 : modèles propres à une population (hémogramme homme / femme / enfant / nouveau-né)
_PROFILS = {'nouveau': {'nouveau', 'nne', 'neonatal'}, 'enfant': {'enfant', 'enfants', 'pediatrique'},
            'femme': {'femme', 'femmes'}, 'homme': {'homme', 'hommes'}}


def profil_patient(sexe, age_jours):
    """'nouveau' (28 jours au plus), 'enfant' (moins de 15 ans), sinon 'femme' / 'homme' (ou None)."""
    if age_jours is not None and age_jours <= 28:
        return 'nouveau'
    if age_jours is not None and age_jours < 15 * 365:
        return 'enfant'
    return {'F': 'femme', 'M': 'homme'}.get(sexe or '')


def note_profil(mots_nom, profil):
    """+1 : modèle fait pour ce patient ; -1 : fait pour un autre (ex. « femme » pour un homme) ; 0 : général."""
    pour = {p for p, mots in _PROFILS.items() if mots_nom & mots}
    if not profil or not pour:
        return 0
    return 1 if profil in pour else -1


def _norm(t):
    import unicodedata
    t = unicodedata.normalize('NFKD', t or '')
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def _mots(texte, paires=False):
    mots = set()
    brut = re.findall(r'[a-z0-9]+', _norm(texte))
    if paires:   # « Ag HBs » -> « aghbs »
        mots.update(a + b for a, b in zip(brut, brut[1:]) if len(a + b) >= 4 and not (a + b).isdigit()
                    and a not in _MOTS_VIDES and b not in _MOTS_VIDES)
    for m in brut:
        if m in _MOTS_VIDES or m.isdigit():
            continue
        if len(m) >= 3 or (len(m) == 2 and m.isalpha()):
            mots.add(m)
    return mots


def _texte_html(html, listes=False):
    """Texte d'un modèle, sans l'en-tête ni le cadre d'identification ; listes=True : seulement les
    choix des listes déroulantes (paramètres d'hémostase, normes...), listes=False : le reste."""
    html = re.sub(r'<style.*?</style>|<table class="mf-(?:entete|identite)[^"]*".*?</table>', ' ', html or '', flags=re.S)
    choix = re.findall(r'<option>(.*?)</option>', html, flags=re.S)
    if listes:
        return ' '.join(choix)
    html = re.sub(r'<select.*?</select>', ' ', html, flags=re.S)
    return re.sub(r'<[^>]+>|&[a-z]+;', ' ', html)


def mots_modele(nom, html):
    """Mots d'un modèle (nom, texte, choix des listes) — calculés une fois, gardés en cache par app.py."""
    return (_mots(nom), _mots(_texte_html(html)), _mots(_texte_html(html, listes=True)))


def proposer_modele(acte_nom, modeles, profil=None, couverture=0.5):
    """Modèle formulaire le plus probable pour un acte, d'après son nom et son contenu — None si rien
    de net. `modeles` : [(id, nom, contenu_html)] ou [(id, mots_modele(...))]. Le code de l'acte (R831...)
    est ignoré. `profil` (voir profil_patient) départage les modèles propres à une population ; `couverture` :
    part des mots de l'acte que le modèle doit couvrir (radiologie : 0.25, ses actes sont longs et descriptifs)."""
    acte = re.sub(r'^[A-Z]{1,3}\d{2,4}\s*', '', (acte_nom or '').strip())
    mots_acte = _mots(acte, paires=True)
    mots_acte |= {_SYNONYMES[m] for m in mots_acte if m in _SYNONYMES}
    if not mots_acte:
        return None

    def present(mot, mots):
        # « creatinine » trouve « creatininemie », « bhcg » finit par « hcg » ; un mot de 3 lettres au milieu
        # d'un autre ne compte pas (2026-10-20 : « fer » dans « référence »)
        return any(m == mot or (len(mot) >= 5 and m.startswith(mot[:max(5, len(mot) - 2)]))
                   or (len(mot) >= 3 and len(m) >= 4 and (m.startswith(mot) or (m.endswith(mot) and len(m) - len(mot) <= 3)))
                   for m in mots)

    def abrege(mot, mots):
        # nom de modèle abrégé : « toxo » pour « toxoplasmose », « copro » pour « coproculture »
        return any(len(m) >= 4 and mot.startswith(m) for m in mots)

    # ⭐ 2026-10-20 : un modèle n'est proposé que s'il couvre au moins la moitié des mots de l'acte (avant :
    # « Ag » seul envoyait l'hépatite B vers la dengue, « hémoglobine » seul l'électrophorèse de l'hémoglobine
    # vers l'hémoglobine glyquée). Un synonyme ne donne des points que dans le NOM du modèle (« calcémie » ->
    # « Ionogramme (..., calcium) », pas l'ECBU qui parle de cristaux d'oxalate de calcium).
    simples = _mots(acte)
    paires = {m for m in mots_acte if m not in simples and m not in _SYNONYMES.values()}

    notes = []
    for m in modeles:
        mid, (mots_nom, mots_contenu, mots_listes) = (m[0], m[1]) if len(m) == 2 else (m[0], mots_modele(m[1], m[2]))
        tous = mots_nom | mots_contenu | mots_listes

        def trouve(mot):
            return present(mot, tous) or abrege(mot, mots_nom)

        def synonyme(w):
            return w in _SYNONYMES and present(_SYNONYMES[w], mots_nom)
        couverts = {w for w in simples if trouve(w) or (w in _SYNONYMES and trouve(_SYNONYMES[w]))}
        couverts |= {w for w in simples for p in paires if trouve(p) and w in p}
        if len(couverts) < couverture * len(simples):
            continue

        def score(mot):
            return ((3 if present(mot, mots_nom) else (2 if abrege(mot, mots_nom) else 0))
                    + (1 if present(mot, mots_contenu) else (0.5 if present(mot, mots_listes) else 0)))
        note = sum(max(score(w), 3 if synonyme(w) else 0) for w in simples) + sum(score(p) for p in paires)
        if note:
            # ⭐ 2026-10-19 : à égalité, la version « normale » d'un examen (radiologie : Genou - normal avant
            # Genou - traumatique), puis le modèle le plus court
            # ⭐ 2026-10-20 : d'abord le modèle fait pour ce patient (hémogramme enfant pour un enfant) ;
            # biologie : « négative » joue le rôle de « normal » (goutte épaisse négative avant positive)
            notes.append((note, note_profil(mots_nom, profil),
                          int(bool(mots_nom & {'normal', 'normale', 'negative', 'negatif'})),
                          -len(mots_contenu | mots_listes), mid))
    if not notes:
        return None
    notes.sort(reverse=True)
    if len(notes) > 1 and notes[0][:4] == notes[1][:4]:
        return None
    return notes[0][4]


# ============================================================
# ⭐ 2026-10-19 (patron, Clinique Valeo — modèles de comptes rendus de RADIOLOGIE) : comptes rendus en
# texte libre (pas de listes Word). Le cadre d'identité (date, patient, sexe, âge, n° de dossier,
# prescripteur) devient des cases remplies par le logiciel ; le texte, du titre de l'examen à la
# conclusion, reste modifiable ; l'en-tête du Word est reproduit tel quel (ligne par ligne, logo à gauche).
# Les valeurs d'identité restées dans le Word (vrais patients) sont effacées, y compris dans la copie
# du Word gardée avec le modèle.
# ============================================================
_ETIQUETTES_IDENTITE = [
    ('date_complete', re.compile(r'^\s*[^\W\d][\w\'\- ]*,\s*le(?=\s|\d|$)\s*', re.I)),   # « Baguida, le11 09 2025 » aussi
    ('patient', re.compile(r'^\s*patient\s*\(?\s*e?\s*\)?\s*:\s*', re.I)),
    ('sexe', re.compile(r'^\s*sexe\s*:\s*', re.I)),
    ('age', re.compile(r'^\s*[aâ]ge\s*:\s*', re.I)),
    ('dossier', re.compile(r'^\s*num[ée]ro\s+de\s+dossier\s*:\s*', re.I)),
    ('prescripteur', re.compile(r'^\s*prescripteur\s*:\s*', re.I)),
]
_MARQUE = '⟦{}⟧'


def _vider_identite_xml(xml, avec_marques):
    """document.xml (texte) : dans les paragraphes d'identité (avant « INDICATION »), garde l'intitulé et
    efface la valeur — remplacée par une marque ⟦clé⟧ si `avec_marques`. Édition au niveau du texte XML :
    rien d'autre n'est touché (le Word reste ouvrable)."""
    from html import unescape
    from xml.sax.saxutils import escape as xml_escape
    sortie, pos, vus = [], 0, set()
    for mp in re.finditer(r'<w:p[ >].*?</w:p>', xml, re.S):
        p = mp.group(0)
        runs = list(re.finditer(r'(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)', p, re.S))
        textes = [unescape(m.group(2)) for m in runs]
        complet = ''.join(textes)
        if re.search(r'indication', complet, re.I):
            break
        cle = next((c for c, motif in _ETIQUETTES_IDENTITE if c not in vus and motif.match(complet)), None)
        if not cle:
            continue
        vus.add(cle)
        fin = dict(_ETIQUETTES_IDENTITE)[cle].match(complet).end()
        nouveaux, consomme, marque_mise = [], 0, False
        for t in textes:
            garde = t[:max(0, fin - consomme)]
            consomme += len(t)
            if not marque_mise and consomme >= fin:
                garde += _MARQUE.format(cle) if avec_marques else ''
                marque_mise = True
            nouveaux.append(garde)
        for m, t in reversed(list(zip(runs, nouveaux))):
            ouv = m.group(1) if 'xml:space' in m.group(1) else m.group(1).replace('<w:t', '<w:t xml:space="preserve"', 1)
            p = p[:m.start()] + ouv + xml_escape(t) + m.group(3) + p[m.end():]
        sortie.append(xml[pos:mp.start()] + p)
        pos = mp.end()
    sortie.append(xml[pos:])
    return ''.join(sortie)


def _docx_remplace(data, nom, contenu):
    z = zipfile.ZipFile(BytesIO(data))
    out = BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in z.infolist():
            zo.writestr(item, contenu if item.filename == nom else z.read(item.filename))
    return out.getvalue()


def _entete_fixe(z, racine):
    """En-tête du Word reproduit ligne par ligne (gras, taille), logo à gauche, filet dessous."""
    import base64
    MCNS = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
    try:
        rels_doc = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))}
    except Exception:
        return ''
    meilleur = None
    for ref in racine.findall('.//' + W + 'headerReference'):
        cible = rels_doc.get(ref.get(REL + 'id'))
        try:
            h = ET.fromstring(z.read('word/' + cible))
        except Exception:
            continue
        if meilleur is None or len(_texte_brut(h)) > len(_texte_brut(meilleur[1])):
            meilleur = (cible, h)
    if not meilleur:
        return ''
    cible, h = meilleur
    logo = ''
    blip = h.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
    if blip is not None:
        try:
            rels_h = {r.get('Id'): r.get('Target')
                      for r in ET.fromstring(z.read('word/_rels/' + cible.split('/')[-1] + '.rels'))}
            chemin = 'word/' + rels_h[blip.get(REL + 'embed')]
            mime = 'image/png' if chemin.lower().endswith('.png') else 'image/jpeg'
            logo = f'<img src="data:{mime};base64,{base64.b64encode(z.read(chemin)).decode()}" alt="" style="max-height:95px;max-width:100%">'
        except Exception:
            logo = ''
    for fb in h.iter(MCNS + 'Fallback'):   # zones de texte : la version de secours répète le texte
        fb.clear()
    lignes, vues = [], set()
    for p in h.iter(W + 'p'):
        if p.find('.//' + W + 'p') is not None:
            continue
        texte = ''.join(t.text or '' for t in p.iter(W + 't')).strip()
        if not texte or texte in vues:
            continue
        vues.add(texte)
        rpr = next((r.find(W + 'rPr') for r in p.iter(W + 'r') if r.find(W + 'rPr') is not None), None)
        gras = rpr is not None and _actif(rpr, 'b')
        sz = _val(rpr, 'sz') if rpr is not None else None
        taille = f'font-size:{int(sz) / 2:g}pt;' if sz and str(sz).isdigit() else ''
        lignes.append(f'<div style="{taille}{"font-weight:bold;" if gras else ""}">{escape(texte)}</div>')
    if not (logo or lignes):
        return ''
    return ('<table class="mf-entete mf-entete-fixe"><tr>'
            f'<td style="width:30%;vertical-align:middle">{logo}</td>'
            f'<td style="text-align:center;vertical-align:middle">{"".join(lignes)}</td>'
            '</tr></table><div style="border-top:1.5px solid #000;margin:2px 0 10px"></div>')


def docx_compte_rendu_libre(data):
    """Word de compte rendu en texte libre -> (HTML du modèle, copie du Word sans identité de patient)."""
    z = zipfile.ZipFile(BytesIO(data))
    xml = z.read('word/document.xml').decode('utf-8')
    propre = _docx_remplace(data, 'word/document.xml', _vider_identite_xml(xml, False).encode('utf-8'))
    marque = _docx_remplace(data, 'word/document.xml', _vider_identite_xml(xml, True).encode('utf-8'))
    html = docx_vers_formulaire(marque)
    for cle, _ in _ETIQUETTES_IDENTITE:
        html = html.replace(_MARQUE.format(cle),
                            f'<span class="mf-champ mf-texte" data-id="{cle}" contenteditable="true"></span>', 1)
    zm = zipfile.ZipFile(BytesIO(marque))
    entete = _entete_fixe(zm, ET.fromstring(zm.read('word/document.xml')))
    m = re.search(r'<table class="mf-entete">.*?</table>', html, flags=re.S)
    if entete:
        html = html.replace(m.group(0), entete, 1) if m else html.replace('</style>', '</style>' + entete, 1)
    # texte modifiable : du titre de l'examen (après le prescripteur) jusqu'avant « Bien confraternellement »
    i = html.find('data-id="prescripteur"')
    debut = html.find('</p>', i) + 4 if i >= 0 else html.find('<p', max(0, html.lower().find('indication') - 300))
    j = html.lower().find('confraternellement')
    fin = html.rfind('<p', 0, j) if j >= 0 else html.rfind('</div>')
    if 0 < debut < fin:
        html = (html[:debut] + '<div class="mf-libre" contenteditable="true" spellcheck="true">'
                + html[debut:fin] + '</div>' + html[fin:])
        html = mettre_en_forme_compte_rendu(html)
    return harmoniser_compte_rendu(html), propre


# ⭐ 2026-10-19 (patron) : signature(s) apposée(s) LÀ OÙ le compte rendu dit « Le Radiologue » (ou « Le
# Laboratoire » / « Le Biologiste ») — sous la dernière ligne qui le dit ; rien si le texte ne le dit pas
# (l'impression ajoute alors son bloc de signature habituel en bas).
# ⭐ 2026-10-22 : « Le Responsable du laboratoire » (biologie du Cabinet Médical Elite)
_LIGNE_SIGNATURE = re.compile(r'\ble\s+(radiologue|laboratoire|biologiste|m[ée]decin\s+radiologue|responsable\s+du\s+laboratoire)\b',
                              re.I)


def apposer_signatures(html, signataires):
    if not html or not signataires or 'mf-signatures' in html:
        return html
    trouve = None
    for m in re.finditer(r'<p\b[^>]*>.*?</p>', html, flags=re.S):
        texte = re.sub(r'<[^>]+>|&nbsp;|&emsp;', ' ', m.group(0))
        if _LIGNE_SIGNATURE.search(texte):
            trouve = m
    if not trouve:
        return html
    blocs = []
    for sg in signataires:
        img = (f'<img src="data:{escape(sg.get("mime") or "image/png")};base64,{sg["image"]}" alt="Signature" '
               'style="max-height:60px;max-width:170px;display:block;margin:0 auto 2px">') if sg.get('image') else ''
        nom = ' — '.join(x for x in (sg.get('titre') or '', sg.get('nom') or '') if x)
        blocs.append(f'<div style="text-align:center;min-width:150px">{img}<div style="font-size:10.5pt">{escape(nom)}</div></div>')
    bloc = ('<div class="mf-signatures" style="display:flex;justify-content:flex-end;flex-wrap:wrap;gap:28px;'
            'margin:4px 0 6px">' + ''.join(blocs) + '</div>')
    return html[:trouve.end()] + bloc + html[trouve.end():]


# ⭐ 2026-10-19 (patron) : titre de l'examen mis en exergue. Mention de l'appareil (« Examen réalisé sur ... ») :
# d'abord rangée dans TECHNIQUE, puis (2026-10-20, photo du patron) juste sous le titre — ajuster_compte_rendu.
def _texte_p(p):
    return ' '.join(re.sub(r'<[^>]+>', '', p.replace('&nbsp;', ' ').replace('&emsp;', ' ')).split())


def mettre_en_forme_compte_rendu(html):
    if not html or 'mf-titre-examen' in html or 'mf-identite-bio' in html:   # biologie : pas de titre à encadrer
        return html
    m = re.search(r'<div class="mf-libre"[^>]*>', html)
    if not m:   # compte rendu enregistré : la zone de texte est figée en <div class=""> après le prescripteur
        i = html.find('data-id="prescripteur"')
        m = re.compile(r'<div class="">').search(html, i) if i >= 0 else None
    if not m:
        return html
    debut = m.end()
    paras = [(x.start(), x.end(), x.group(0)) for x in re.finditer(r'<p\b[^>]*>.*?</p>', html[debut:], flags=re.S)]
    paras = [(debut + a, debut + b, t) for a, b, t in paras]
    # mention de l'appareil : retirée de sous le titre
    appareil = next(((a, b, t) for a, b, t in paras if re.search(r'examen\s+r[ée]alis[ée]\s+sur', _texte_p(t), re.I)), None)
    titre = next(((a, b, t) for a, b, t in paras if _texte_p(t)), None)
    if not titre or (appareil and titre[0] == appareil[0]):
        return html
    morceaux = []   # (début, fin, remplacement), appliqués de la fin vers le début
    morceaux.append((titre[0], titre[1],
                     '<p class="mf-titre-examen" style="text-align:center;margin:10px 0 10px">'
                     '<span style="display:inline-block;border:2px solid #1a1a1a;padding:5px 18px;font-weight:bold;'
                     f'font-size:15pt;letter-spacing:.5px">{escape(_texte_p(titre[2]))}</span></p>'))
    if appareil:
        ligne = ('<p style="margin:2px 0 0;text-align:justify"><span style="font-style:italic;font-size:12pt">'
                 f'{escape(_texte_p(appareil[2]))}</span></p>')
        resultats = next((i for i, (a, b, t) in enumerate(paras) if re.match(r'r[ée]sultats?\b', _texte_p(t), re.I)), None)
        technique = next((i for i, (a, b, t) in enumerate(paras) if re.match(r'technique\b', _texte_p(t), re.I)), None)
        if technique is not None and resultats is not None and technique < resultats:
            # après le dernier paragraphe non vide de la partie TECHNIQUE
            dernier = max(i for i in range(technique, resultats) if _texte_p(paras[i][2]))
            morceaux.append((paras[dernier][1], paras[dernier][1], ligne))
            morceaux.append((appareil[0], appareil[1], ''))
        else:   # pas de partie TECHNIQUE : centrée juste sous le titre
            morceaux.append((appareil[0], appareil[1], ligne.replace('text-align:justify', 'text-align:center')))
    for a, b, t in sorted(morceaux, key=lambda x: (x[0], x[1]), reverse=True):
        html = html[:a] + t + html[b:]
    return ajuster_compte_rendu(html)


# ⭐ 2026-10-20 (patron, photo d'un compte rendu Word de Valeo) : « que les résultats ressemblent à ceci » —
#   - la date (« Baguida, le ... ») bien à droite ;
#   - « Examen réalisé sur J@DIX-I ... » juste sous le titre de l'examen (petit, italique, centré) ;
#   - le nom du radiologue (et sa signature) centré sous « Le Radiologue », le tout à droite.
# Appliqué à l'affichage (impression, portail) et à l'ouverture d'un modèle : les comptes rendus déjà
# enregistrés en profitent aussi, rien n'est réécrit en base. Sans effet sur un texte déjà ajusté.
_APPAREIL = re.compile(r'examen\s+r[ée]alis[ée]\s+sur', re.I)


def _fin_div(html, debut):
    """Indice de fin du <div> ouvert à `debut` (divs imbriqués compris)."""
    profondeur = 0
    for m in re.finditer(r'<div\b|</div>', html[debut:]):
        profondeur += 1 if m.group(0) == '<div' else -1
        if profondeur == 0:
            return debut + m.end()
    return len(html)


def ajuster_compte_rendu(html):
    if not html or 'mf-' not in html:
        return html
    # 1) date à droite
    html = re.sub(r'<p\b[^>]*>(?=(?:(?!</p>).)*data-id="date_complete")',
                  '<p style="margin:0;text-align:right">', html, count=1, flags=re.S)
    # 2) mention de l'appareil juste sous le titre de l'examen
    titre = re.search(r'<p class="mf-titre-examen"[^>]*>.*?</p>', html, flags=re.S)
    if titre and 'mf-appareil' not in html:
        appareil = next((m for m in re.finditer(r'<p\b[^>]*>.*?</p>', html, flags=re.S)
                         if _APPAREIL.search(_texte_p(m.group(0)))), None)
        if appareil:
            ligne = ('<p class="mf-appareil" style="text-align:center;margin:-6px 0 12px">'
                     f'<span style="font-style:italic;font-size:9.5pt">{escape(_texte_p(appareil.group(0)))}</span></p>')
            html = html[:appareil.start()] + html[appareil.end():]
            titre = re.search(r'<p class="mf-titre-examen"[^>]*>.*?</p>', html, flags=re.S)
            html = html[:titre.end()] + ligne + html[titre.end():]
    # 3) « Le Radiologue » + nom(s) centrés dessous, le bloc à droite
    if 'mf-bloc-signature' not in html:
        ligne_sig = None
        for m in re.finditer(r'<p\b[^>]*>.*?</p>', html, flags=re.S):
            if _LIGNE_SIGNATURE.search(_texte_p(m.group(0))):
                ligne_sig = m
        if ligne_sig:
            libelle = _texte_p(ligne_sig.group(0))
            fin, noms = ligne_sig.end(), ''
            suite = re.match(r'\s*(?=<div class="mf-signatures")', html[fin:])
            if suite:
                debut_sg = fin + suite.end()
                fin_sg = _fin_div(html, debut_sg)
                interieur = re.sub(r'^<div class="mf-signatures"[^>]*>|</div>$', '', html[debut_sg:fin_sg])
                noms = ('<div class="mf-signatures" style="display:flex;justify-content:center;flex-wrap:wrap;'
                        f'gap:24px;margin:2px 0 0">{interieur}</div>')
                fin = fin_sg
            bloc = ('<div class="mf-bloc-signature" style="display:flex;justify-content:flex-end;margin:6px 0 6px">'
                    f'<div style="text-align:center;min-width:170px"><p style="margin:0">{escape(libelle)}</p>{noms}</div></div>')
            html = html[:ligne_sig.start()] + bloc + html[fin:]
    if 'mf-bloc-signature' in html:   # signature apposée après coup dans un bloc déjà prêt : centrée aussi
        html = html.replace('<div class="mf-signatures" style="display:flex;justify-content:flex-end',
                            '<div class="mf-signatures" style="display:flex;justify-content:center')
    return html


# ============================================================
# ⭐ 2026-10-20 (patron, Clinique Valeo — modèles de comptes rendus de BIOLOGIE, « dans le même esprit que la
# radio ») : Word sans listes déroulantes, faits de tableaux remplis pour un vrai patient. À l'import :
#   - seule la 1re page (jusqu'à « Le Biologiste ») est gardée — certains Word contenaient à la suite les
#     comptes rendus complets de vrais patients (nom, âge, dossier) ;
#   - chaque valeur de la colonne « Résultats » devient une case vide à remplir (l'unité écrite à côté est
#     gardée), « NEGATIVE » devient une liste Négative / Positive, « DP = 374 » une case ;
#   - cadre d'identité de Valeo (Prescrit par, Âge, Dossier N°, Type d'échantillon, date et heure de
#     prélèvement ; patient, sexe, téléphone) rempli par le logiciel ;
#   - interprétation modifiable, avec des phrases toutes prêtes à cliquer ; « Le Biologiste » à droite (les
#     signatures s'y apposent) ; pied de page du Word gardé.
# Les mêmes valeurs sont effacées dans la copie du Word gardée avec le modèle.
# ============================================================
_RE_BALISE = re.compile(r'<(/?)([A-Za-z][\w.-]*:[A-Za-z][\w.-]*)\b[^>]*?(/?)>')


def _enfants(xml, debut, fin):
    """Éléments enfants directs (balise, début, fin) du contenu xml[debut:fin] (texte XML du Word)."""
    res, profondeur, ouvert = [], 0, None
    for m in _RE_BALISE.finditer(xml, debut, fin):
        if m.group(1):
            profondeur -= 1
            if profondeur == 0 and ouvert:
                res.append((ouvert[0], ouvert[1], m.end()))
        elif m.group(3):
            if profondeur == 0:
                res.append((m.group(2), m.start(), m.end()))
        else:
            if profondeur == 0:
                ouvert = (m.group(2), m.start())
            profondeur += 1
    return res


def _interieur(xml, el):
    """Contenu d'un élément (entre sa balise ouvrante et sa balise fermante)."""
    _, a, b = el
    return xml.index('>', a) + 1, xml.rindex('<', a, b)


def _textes_w(fragment):
    from html import unescape
    return [unescape(m.group(2)) for m in re.finditer(r'(<w:t(?:\s[^>]*)?>)(.*?)</w:t>', fragment, re.S)]


def _texte_w(fragment):
    return ''.join(_textes_w(fragment))


def _remplacer_texte(fragment, debut, fin, marque):
    """Dans un paragraphe Word (texte XML) : remplace les caractères [debut, fin) de son texte par `marque`,
    sans toucher à la mise en forme des morceaux (runs)."""
    from html import unescape
    from xml.sax.saxutils import escape as xml_escape
    runs = list(re.finditer(r'(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)', fragment, re.S))
    pos, nouveaux, mise = 0, [], False
    for m in runs:
        t = unescape(m.group(2))
        a, b = pos, pos + len(t)
        garde = t[:max(0, min(len(t), debut - a))]
        if not mise and debut < b or (not mise and debut == b and m is runs[-1]):
            garde += marque
            mise = True
        garde += t[max(0, fin - a):] if fin < b else ''
        nouveaux.append(garde)
        pos = b
    for m, t in reversed(list(zip(runs, nouveaux))):
        ouv = m.group(1) if 'xml:space' in m.group(1) else m.group(1).replace('<w:t', '<w:t xml:space="preserve"', 1)
        fragment = fragment[:m.start()] + ouv + xml_escape(t) + m.group(3) + fragment[m.end():]
    return fragment


_MARQUE_VALEUR, _MARQUE_CHOIX = '⟦v⟧', '⟦c⟧'
_RE_VALEUR_CELLULE = re.compile(r'\s*((?:[<>]=?\s*)?\d[\d\s\u00a0,.]*\d|\d|n[ée]gati\w*|positi\w*)', re.I)


def _norm_simple(t):
    return ' '.join(_norm_txt(t).replace('\xa0', ' ').split())


def _marquer_tableau(xml, tbl, remplacements):
    """Valeurs d'un tableau de résultats -> marques. `remplacements` : [(début, fin, nouveau texte)]."""
    _, ta, tb = tbl
    lignes = [e for e in _enfants(xml, *_interieur(xml, tbl)) if e[0] == 'w:tr']
    col_res = None
    for tr in lignes:
        cellules, col = [], 0
        for tc in _enfants(xml, *_interieur(xml, tr)):
            if tc[0] != 'w:tc':
                continue
            frag = xml[tc[1]:tc[2]]
            m = re.search(r'<w:gridSpan w:val="(\d+)"', frag)
            span = int(m.group(1)) if m else 1
            cellules.append((col, span, tc))
            col += span
        if col_res is None:
            for c, span, tc in cellules:
                if re.fullmatch(r'r[ée]sultats?', _norm_simple(_texte_w(xml[tc[1]:tc[2]]))):
                    col_res = c
            if col_res is not None:
                continue
        for c, span, tc in cellules:
            # cellule de la colonne « Résultats » : la valeur en tête de cellule ; ailleurs (goutte épaisse,
            # sérologie) : « IgM : NEGATIVE », « DP = 374 »
            dans_resultats = col_res is not None and c <= col_res < c + span
            if col_res is not None and not dans_resultats:
                continue   # paramètres, normes (« > = 8% ») : jamais touchés
            for p in re.finditer(r'<w:p[ >].*?</w:p>', xml[tc[1]:tc[2]], re.S):
                frag, a = p.group(0), tc[1] + p.start()
                marque = _marque_paragraphe(_texte_w(frag), dans_resultats)
                if marque:
                    remplacements.append((a, a + len(frag), _remplacer_texte(frag, *marque)))


def _marque_paragraphe(texte, dans_resultats):
    """(début, fin, marque) de la valeur d'un paragraphe de résultat, ou None."""
    if dans_resultats:
        m = _RE_VALEUR_CELLULE.match(texte)
        if m:
            choix = not (m.group(1)[0].isdigit() or m.group(1)[0] in '<>')
            return m.start(1), m.end(1), (_MARQUE_CHOIX if choix else _MARQUE_VALEUR)
    m = re.search(r':\s*(n[ée]gati\w*|positi\w*)\s*$', texte, re.I)
    if m:
        return m.start(1), m.end(1), _MARQUE_CHOIX
    m = re.search(r'=\s*(\d[\d\s\u00a0,.]*\d|\d)', texte)
    if m:
        return m.start(1), m.end(1), _MARQUE_VALEUR
    return None


def _pied_de_page(z, racine):
    try:
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))}
    except Exception:
        return ''
    lignes = []
    for ref in racine.findall('.//' + W + 'footerReference'):
        try:
            f = ET.fromstring(z.read('word/' + rels.get(ref.get(REL + 'id'), '')))
        except Exception:
            continue
        for p in f.iter(W + 'p'):
            if p.find('.//' + W + 'p') is not None:
                continue
            t = ' '.join(''.join(x.text or '' for x in p.iter(W + 't')).split())
            if t and t not in lignes:
                lignes.append(t)
    return ' '.join(lignes)


def identite_biologie(prelevement=''):
    """Cadre d'identité des comptes rendus de biologie de Valeo (à gauche : compte rendu, prescripteur,
    âge, dossier, échantillon, prélèvement ; à droite, encadré : patient, sexe, téléphone)."""
    def case(cle, largeur='7em'):
        return (f'<span class="mf-champ mf-texte" data-id="{cle}" contenteditable="true" '
                f'style="min-width:{largeur}"></span>')
    echantillons = ('Sang total', 'Sang', 'Sérum', 'Plasma', 'Urines', 'Selles', 'Liquide de ponction', 'Pus', 'Sécrétions vaginales')
    echantillon = ('<input type="text" class="mf-champ mf-combo" data-id="prelevement" list="mfl-echantillon" autocomplete="off" '
                   f'placeholder="taper ou choisir" value="{escape(prelevement)}" style="min-width:7em">'
                   '<datalist id="mfl-echantillon">' + ''.join(f'<option>{escape(e)}</option>' for e in echantillons) + '</datalist>')
    td = 'border:0;padding:0 14px 0 0;vertical-align:top'
    lignes = [('Prescrit par', case('prescripteur', '10em')), ('Age', case('age', '5em')), ('Dossier N°', case('dossier', '6em')),
              ("Type d’échantillon", echantillon), ('Date de prélèvement', case('date_prelevement_complete', '6em')),
              ('Heure de prélèvement', case('heure_prelevement', '4em'))]
    gauche = ''.join(f'<tr><td style="{td}">{escape(l)}</td><td style="border:0;padding:0">{v}</td></tr>' for l, v in lignes)
    return ('<table class="mf-identite mf-identite-bio" style="border:0;width:100%;margin:6px 0 16px;font-size:10.5pt"><tr>'
            '<td style="border:0;padding:0;width:58%;vertical-align:top">'
            '<div style="font-style:italic">COMPTE-RENDU D’ANALYSES MÉDICALES</div>'
            f'<table style="border-collapse:collapse">{gauche}</table></td>'
            '<td style="border:0;padding:0;vertical-align:top">'
            '<div style="border:1px solid #000;padding:3px 8px;min-height:4.2em">'
            f'<div style="font-size:11.5pt">{case("patient_civilite", "12em")}</div>'
            f'<div>Sexe : {case("sexe", "6em")}</div><div>Téléphone : {case("telephone", "7em")}</div>'
            '</div></td></tr></table>')


def docx_compte_rendu_biologie(data, section=None, prelevement='', interpretation=None, suggestions=(), pied=''):
    """Word de compte rendu de biologie (tableaux remplis pour un patient) -> (HTML du modèle, copie du Word
    sans valeurs ni pages de patients). `section` : (titre de début, titre de fin exclu ou None) pour tirer
    un modèle d'une partie du Word (ex. CRP) ; `prelevement` : type d'échantillon proposé ; `interpretation`
    : texte mis par défaut dans l'interprétation ; `suggestions` : phrases à cliquer sous l'interprétation."""
    z = zipfile.ZipFile(BytesIO(data))
    xml = z.read('word/document.xml').decode('utf-8')
    corps = re.search(r'<w:body>', xml).end(), xml.rindex('</w:body>')
    enfants = _enfants(xml, *corps)
    textes = [_norm_simple(_texte_w(xml[a:b])) if t in ('w:p', 'w:tbl') else '' for t, a, b in enfants]
    biologiste = [i for i, t in enumerate(textes) if enfants[i][0] == 'w:p' and re.fullmatch(r'le biologiste', t)]
    patient = [i for i, t in enumerate(textes) if 'prescrit par' in t or 'compte-rendu d' in t]
    fin_page = min([i for i in biologiste] + [i - 1 for i in patient] + [len(enfants) - 1])
    if section:
        debut = next(i for i, t in enumerate(textes) if t == _norm_simple(section[0]))
        fins = [i for i, t in enumerate(textes) if i > debut and ((section[1] and t == _norm_simple(section[1]))
                                                                 or i in biologiste or i in patient)]
        garder = list(range(debut, (fins[0] if fins else len(enfants)))) + biologiste[:1]
    else:
        garder = list(range(0, fin_page + 1))
    garder += [i for i, e in enumerate(enfants) if e[0] == 'w:sectPr' and i not in garder]
    remplacements = []
    for i in garder:
        if enfants[i][0] == 'w:tbl':
            _marquer_tableau(xml, enfants[i], remplacements)
        elif enfants[i][0] == 'w:p' and re.fullmatch(r'[\s²]*²[\s²]*', _texte_w(xml[enfants[i][1]:enfants[i][2]]) or 'x'):
            remplacements.append((enfants[i][1], enfants[i][2], ''))   # « ² » tapé par erreur
    remplacements.sort()

    def morceau(a, b):
        out, pos = [], a
        for ra, rb, nouveau in remplacements:
            if a <= ra and rb <= b:
                out.append(xml[pos:ra] + nouveau)
                pos = rb
        return ''.join(out) + xml[pos:b]

    marque = xml[:corps[0]] + ''.join(morceau(enfants[i][1], enfants[i][2]) for i in garder) + xml[corps[1]:]
    propre = _docx_remplace(data, 'word/document.xml',
                            marque.replace(_MARQUE_VALEUR, '').replace(_MARQUE_CHOIX, '').encode('utf-8'))
    donnees_marquees = _docx_remplace(data, 'word/document.xml', marque.encode('utf-8'))
    html = docx_vers_formulaire(donnees_marquees)
    html = html.replace(_MARQUE_VALEUR, '<span class="mf-champ mf-texte mf-resultat" contenteditable="true"></span>')
    html = html.replace(_MARQUE_CHOIX, '<select class="mf-champ mf-liste mf-resultat"><option value="">— choisir —</option>'
                                       '<option>NÉGATIVE</option><option>POSITIVE</option>'
                                       '<option value="__autre__">✎ Autre…</option></select>')
    zm = zipfile.ZipFile(BytesIO(donnees_marquees))
    racine = ET.fromstring(zm.read('word/document.xml'))
    entete = _entete_fixe(zm, racine)
    m = re.search(r'<table class="mf-entete">.*?</table>', html, flags=re.S)
    if m:
        html = html.replace(m.group(0), '', 1)
    html = html.replace('</style>', '</style>' + entete + identite_biologie(prelevement), 1)
    # tableaux de résultats toujours encadrés (certains Word tenaient leurs bordures d'un style de tableau)
    html = html.replace('<table class="mf-table">', '<table class="mf-table mf-bordure">')
    # titre de l'analyse (1er paragraphe écrit après le cadre d'identité) : centré, gras, comme dans les Word
    # (certains le tenaient d'un style Word, perdu à la conversion)
    i = html.find('mf-identite-bio')
    for m in re.finditer(r'<p\b[^>]*>.*?</p>', html[i:], flags=re.S):
        titre = _texte_p(m.group(0))
        if titre:
            a, b = i + m.start(), i + m.end()
            html = (html[:a] + '<p class="mf-titre-analyse" style="margin:10px 0 8px;text-align:center;font-weight:bold;'
                    f'font-size:14pt">{escape(titre)}</p>' + html[b:])
            break
    # « Le Biologiste » : à droite (les espaces du Word ne suffisent pas à l'écran)
    html = re.sub(r'<p style="[^"]*">(?:(?!</p>).)*Le Biologist(?:(?!</p>).)*</p>',
                  '<p style="margin:26px 60px 0 0;text-align:right;font-size:12pt">Le Biologiste</p>', html, count=1, flags=re.S)
    if 'Le Biologiste' not in html:   # Word sans la mention (ex. hémogramme femme)
        i = html.rfind('</div>')
        html = html[:i] + '<p style="margin:26px 60px 0 0;text-align:right;font-size:12pt">Le Biologiste</p>' + html[i:]
    # interprétation (hémogramme) : modifiable, phrases toutes prêtes
    i = html.find('INTERPR')
    if i >= 0:
        debut = html.find('</p>', i) + 4
        fin = html.find('<p style="margin:26px 60px 0 0', debut)
        fin = fin if fin >= 0 else html.rfind('</div>')
        contenu = html[debut:fin]
        if interpretation is not None:
            contenu = f'<p style="margin:0;font-weight:bold;font-size:12pt">{escape(interpretation)}</p>'
        boutons = ''.join(
            f'<button type="button" class="mf-suggestion" data-texte="{escape(s, quote=True)}" '
            'style="font-size:9pt;margin:2px 4px 0 0;padding:0 6px;border:1px solid #0d6efd;border-radius:10px;'
            f'background:#eef5ff;color:#0d6efd;cursor:pointer">+ {escape(s)}</button>' for s in suggestions)
        html = (html[:debut] + '<div class="mf-interpretation"><div class="mf-libre" contenteditable="true" spellcheck="true">'
                + contenu + '</div>' + (f'<div class="mf-suggestions">{boutons}</div>' if boutons else '') + '</div>' + html[fin:])
    pied = _pied_de_page(zm, racine) or pied
    if pied:
        i = html.rfind('</div>')
        html = (html[:i] + f'<p class="mf-pied" style="margin:34px 0 0;text-align:center;font-size:8pt">{escape(pied)}</p>'
                + html[i:])
    return harmoniser_compte_rendu(html), propre



# ============================================================
# ⭐ 2026-10-20 (patron : « regarde dans les modèles mêmes et apporte les corrections, c'est discordant ») :
# un même rendu pour tous les MODÈLES de comptes rendus importés des Word (radiologie, biologie) —
#   - mise en page de l'impression écrite dans le modèle lui-même (date à droite, appareil sous le titre,
#     « Le Radiologue » / « Le Biologiste » à droite) : l'écran de saisie montre ce qui sera imprimé ;
#   - radiologie : identité en 12 pt, texte du compte rendu en 14 pt (selon les Word : 10, 12, 13, 14 ou
#     16 pt), tableaux en 12 pt ;
#   - biologie : tableaux de résultats en 12 pt (une ligne à 16 pt dans un Word) ;
#   - nom d'un radiologue resté écrit sous « Le Radiologue » retiré (ce sont les signataires cochés à
#     l'enregistrement qui s'y inscrivent).
# Pour les modèles seulement — jamais pour un compte rendu enregistré.
# ============================================================
_TAILLE = re.compile(r'font-size:\s*[\d.]+pt;?')


def _retirer_noms_sous_signature(html):
    lignes = list(re.finditer(r'<p\b[^>]*>.*?</p>', html, flags=re.S))
    i = next((k for k, m in enumerate(lignes) if _LIGNE_SIGNATURE.search(_texte_p(m.group(0)))), None)
    if i is None:
        return html
    morceaux = []
    p = lignes[i]
    texte = _texte_p(p.group(0))
    libelle = _LIGNE_SIGNATURE.search(texte)
    if texte[libelle.end():].strip():          # « Le Radiologue Dr KOMLANVI » dans le même paragraphe
        morceaux.append((p.start(), p.end(), f'<p style="margin:0">{escape(texte[:libelle.end()])}</p>'))
    for m in lignes[i + 1:i + 4]:
        t = _texte_p(m.group(0))
        if re.fullmatch(r'(dr|pr|docteur|professeur)\.?\s+[\w\s\'\-.]+', t, flags=re.I):
            morceaux.append((m.start(), m.end(), ''))
        elif t:
            break
    for a, b, t in sorted(morceaux, reverse=True):
        html = html[:a] + t + html[b:]
    return html


def harmoniser_compte_rendu(html):
    if not html or 'mf-entete-fixe' not in html:
        return html
    html = ajuster_compte_rendu(mettre_en_forme_compte_rendu(_retirer_noms_sous_signature(html)))
    if 'mf-identite-bio' in html:
        def tableau(m):
            t = _TAILLE.sub('', m.group(0))
            return t.replace('<table class="mf-table mf-bordure">', '<table class="mf-table mf-bordure" style="font-size:12pt">', 1)
        return re.sub(r'<table class="mf-table mf-bordure">.*?</table>', tableau, html, flags=re.S)
    i = html.find('<div class="mf-libre"')
    if i < 0:
        return html
    j = _fin_div(html, i)
    debut_id = html.find('</table>', html.find('mf-entete-fixe')) + len('</table>')
    # identité (date, patient, sexe, âge, dossier, prescripteur) : 12 pt
    identite = _TAILLE.sub('', html[debut_id:i])
    identite = re.sub(r'<p style="([^"]*)">', lambda m: f'<p style="{m.group(1).rstrip(";")};font-size:12pt">', identite)
    # texte du compte rendu : 14 pt (titre encadré et ligne de l'appareil gardés), tableaux 12 pt
    libre = html[i:j]
    gardes = []

    def garder(m):
        gardes.append(m.group(0))
        return f'⟦garde{len(gardes) - 1}⟧'
    libre = re.sub(r'<p class="mf-(?:titre-examen|appareil)"[^>]*>.*?</p>', garder, libre, flags=re.S)

    def garder_tableau(m):
        t = _TAILLE.sub('', re.sub(r'^<table style="font-size:12pt"', '<table', m.group(0)))
        gardes.append(re.sub(r'<table\b', '<table style="font-size:12pt"', t, count=1))
        return f'⟦garde{len(gardes) - 1}⟧'
    libre = re.sub(r'<table\b.*?</table>', garder_tableau, libre, flags=re.S)
    ouverture = libre[:libre.index('>') + 1]
    if 'font-size' not in ouverture:
        ouverture = ouverture[:-1] + ' style="font-size:14pt">'
    libre = ouverture + _TAILLE.sub('font-size:14pt;', libre[libre.index('>') + 1:])
    for k, g in enumerate(gardes):
        libre = libre.replace(f'⟦garde{k}⟧', g)
    # « Bien confraternellement, » : même taille que le texte
    suite = re.sub(r'<p style="([^"]*)">((?:(?!</p>).)*confraternellement(?:(?!</p>).)*</p>)',
                   lambda m: f'<p style="{_TAILLE.sub("", m.group(1)).rstrip(";")};font-size:14pt">{_TAILLE.sub("", m.group(2))}',
                   html[j:], count=1, flags=re.S)
    return html[:debut_id] + identite + libre + suite


# ⭐ 2026-10-20 (patron : « à l'impression le texte est blanc » / « en thème sombre c'est presque invisible ») :
# le thème sombre (static/js/theme_sombre.js) repeint la page en posant des couleurs « !important » sur les
# éléments ; enregistrées avec le compte rendu, elles donnaient du texte blanc sur le papier. Un compte rendu
# ou un modèle ne garde jamais ces couleurs (aucun modèle n'utilise « !important »).
_DECL_THEME = re.compile(r'^\s*(background-color|color|transition|border-color)\s*:[^;]*!\s*important\s*$', re.I)


def retirer_couleurs_du_theme(html):
    if not html or ('!important' not in html and 'data-th-sombre' not in html):
        return html
    html = re.sub(r'\sdata-th-sombre="[^"]*"', '', html)

    def style(m):
        decl = [d.strip() for d in m.group(2).split(';') if d.strip() and not _DECL_THEME.match(d)]
        return f'{m.group(1)}style="{"; ".join(decl)}"' if decl else m.group(1).rstrip()
    return re.sub(r'(<[a-zA-Z][^>]*?\s)style="([^"]*!\s*important[^"]*)"', style, html)


# ============================================================
# ⭐ 2026-10-22 (patron : « un patient qui fait NFS, CRP, GE, hépatite C… : tout regrouper en un seul fichier,
# avec une seule en-tête et le logo, et pour chaque rubrique son titre ») — comptes rendus de plusieurs
# analyses d'un même patient réunis en un seul document : l'en-tête et le cadre du patient du premier
# compte rendu fait sur un modèle, puis chaque analyse (son titre, ses résultats), la signature et le pied
# de page une seule fois, à la fin.
# ============================================================
def _fin_balise(html, debut, balise):
    """Indice de fin de l'élément <balise> ouvert à `debut` (éléments imbriqués de même nom compris)."""
    profondeur = 0
    for m in re.finditer(rf'<{balise}\b|</{balise}>', html[debut:]):
        profondeur += 1 if not m.group(0).startswith('</') else -1
        if profondeur == 0:
            return debut + m.end()
    return len(html)


def _extraire(html, motif, balise):
    """(élément trouvé, html sans lui) — premier élément dont la balise ouvrante correspond à `motif`."""
    m = re.search(motif, html)
    if not m:
        return '', html
    fin = _fin_balise(html, m.start(), balise)
    return html[m.start():fin], html[:m.start()] + html[fin:]


def regrouper_comptes_rendus(sections):
    """sections : [(titre de l'analyse, HTML du compte rendu)] dans l'ordre voulu -> HTML d'un seul document."""
    if not sections:
        return ''
    haut, style, corps = '', '', []
    for titre, html in sections:
        html = html or ''
        if 'mf-entete' in html:
            entete, html = _extraire(html, r'<table class="mf-entete\b[^"]*"', 'table')
            identite, html = _extraire(html, r'<table class="mf-identite\b[^"]*"', 'table')
            if not haut:
                m = re.search(r'<style>.*?</style>', html, flags=re.S)
                style = m.group(0) if m else ''
                haut = entete + identite
            html = re.sub(r'<div style="border-top:1\.5px solid #000;margin:2px 0 10px"></div>', '', html, count=1)
            corps.append({'html': html, 'formulaire': True, 'titre': titre})
        else:
            corps.append({'html': f'<p class="mf-titre-section" style="margin:14px 0 6px;font-weight:bold;font-size:13pt;'
                                  f'text-decoration:underline">{escape(titre)}</p>' + html, 'formulaire': False, 'titre': titre})
    # signature et pied de page : seulement ceux du dernier compte rendu qui en a
    avec_signature = [i for i, c in enumerate(corps) if 'mf-bloc-signature' in c['html'] or 'mf-signatures' in c['html']]
    avec_pied = [i for i, c in enumerate(corps) if 'mf-pied' in c['html']]
    for i, c in enumerate(corps):
        h = c['html']
        if avec_signature and i != avec_signature[-1]:
            bloc, h2 = _extraire(h, r'<div class="mf-bloc-signature\b', 'div')
            if not bloc:
                bloc, h2 = _extraire(h, r'<div class="mf-signatures\b', 'div')
            h = h2
            # « Lomé, le [date] » et la mention « Le Responsable du laboratoire » restées seules : retirées (la
            # dernière occurrence, celle qui accompagne la signature)
            for motif in (r'<p\b[^>]*>(?:(?!</p>).)*data-id="date_complete"(?:(?!</p>).)*</p>',
                          r'<p\b[^>]*>(?:(?!</p>).)*\ble\s+(?:radiologue|laboratoire|biologiste|responsable\s+du\s+laboratoire)\b(?:(?!</p>).)*</p>'):
                trouves = list(re.finditer(motif, h, flags=re.S | re.I))
                if trouves:
                    h = h[:trouves[-1].start()] + h[trouves[-1].end():]
        if avec_pied and i != avec_pied[-1]:
            h = re.sub(r'<p class="mf-pied\b.*?</p>', '', h, flags=re.S)
        c['html'] = h
    separateur = '<div class="mf-separateur-section" style="border-top:1px dashed #999;margin:14px 0 10px"></div>'
    morceaux = []
    for k, c in enumerate(corps):
        morceaux.append(('' if k == 0 else separateur) + f'<div class="cr-section">{c["html"]}</div>')
    tete = f'<div class="modele-formulaire">{style}{haut}</div>' if haut else ''
    return tete + ''.join(morceaux)
