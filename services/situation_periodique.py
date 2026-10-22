# -*- coding: utf-8 -*-
"""Situation périodique des médicaments (Gestion des stocks).

⭐ 2026-10-22 (patron) : pour une période choisie (ou un seul jour), chaque médicament avec son
stock au début, ses entrées, ses sorties, son stock à la fin, le montant de ses ventes, son prix
et la valeur de son stock — « pour qu'on puisse faire la situation de façon rapide ».

Source : le journal mouvements_stock (une ligne par vente, approvisionnement, inventaire,
annulation, ajustement…, avec le stock après chaque mouvement) + les ventes pour les montants
réellement facturés. Ce module ne fait aucune requête : app.py lui passe les résultats des
requêtes (voir api_situation_periodique), ce qui le rend testable.

Règles (fiche de stock) :
  stock initial = stock après le dernier mouvement AVANT le début de la période
  entrées       = approvisionnements + écarts d'inventaire/ajustements positifs + création du produit
  sorties       = ventes (moins les ventes annulées) + écarts d'inventaire/ajustements négatifs + suppression
  stock final   = stock après le dernier mouvement de la période  (= initial + entrées - sorties)
  Si le stock a été modifié sans être journalisé (correction directe), l'écart est ajouté aux
  entrées ou aux sorties « autres » et la ligne est signalée — le tableau reste juste et équilibré.
"""
import csv
import io
from datetime import datetime

BASES_PRIX = {'vente': 'prix de vente', 'achat': "prix d'achat"}

COLONNES = ['Médicament', 'Unité', 'Stock initial', 'Entrées', 'Sorties', 'Stock final',
            'Montant des ventes', 'Prix unitaire', 'Valeur du stock final']

LIBELLES_TYPES = {
    'vente': 'Vente', 'annulation': 'Annulation de vente (retour en stock)',
    'approvisionnement': 'Approvisionnement', 'inventaire': 'Inventaire (écart)',
    'ajustement': 'Ajustement', 'modification': 'Modification de la fiche',
    'suppression': 'Suppression du produit', 'initial': 'Stock de départ',
}


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _entier(v):
    v = _n(v)
    return int(v) if v == int(v) else round(v, 2)


def construire_situation(produits, avant, periode, premiers_mouvements, ventes_par_produit,
                         fin_periode, base_prix='vente'):
    """Calcule les lignes et les totaux.

    produits            {pid: {nom, unite, prix_vente, prix_achat, stock_actuel}} — fiches actuelles
    avant               {pid: {nom, stock_apres}} — dernier mouvement avant le début
    periode             {pid: {nom, nb, ventes, annulations, entrees_autres, sorties_autres, appro,
                               stock_final, stock_avant_premier, premier_seed, seed_stock}}
    premiers_mouvements {pid: datetime du tout premier mouvement journalisé}
    ventes_par_produit  {pid: {quantite, montant}} — ventes non annulées de la période
    fin_periode         datetime (exclu) de fin de période
    """
    base_prix = base_prix if base_prix in BASES_PRIX else 'vente'
    ids = set(produits) | set(avant) | set(periode)
    lignes = []
    for pid in ids:
        fiche = produits.get(pid) or {}
        p = periode.get(pid)
        a = avant.get(pid)
        premier = premiers_mouvements.get(pid)
        if not a and not p:
            # Aucun mouvement avant ni pendant : créé après la période -> absent ; jamais
            # journalisé -> son stock n'a pas bougé (= stock actuel).
            if premier is not None and premier >= fin_periode:
                continue
            if pid not in produits:
                continue
            initial = _n(fiche.get('stock_actuel'))
        elif a:
            initial = _n(a.get('stock_apres'))
        elif p.get('premier_seed'):
            initial = _n(p.get('seed_stock'))          # point de départ du suivi
        else:
            initial = _n(p.get('stock_avant_premier'))

        if p:
            net_ventes = _n(p.get('ventes')) - _n(p.get('annulations'))
            sorties_ventes = max(net_ventes, 0.0)
            entrees_autres = _n(p.get('entrees_autres')) + max(-net_ventes, 0.0)
            sorties_autres = _n(p.get('sorties_autres'))
            final = _n(p.get('stock_final'))
            nb = int(p.get('nb') or 0)
            appro = _n(p.get('appro'))
        else:
            sorties_ventes = entrees_autres = sorties_autres = appro = 0.0
            final = initial
            nb = 0
        ecart = round(final - (initial + entrees_autres - sorties_ventes - sorties_autres), 4)
        if ecart > 0:
            entrees_autres += ecart
        elif ecart < 0:
            sorties_autres += -ecart

        prix = _n(fiche.get('prix_achat' if base_prix == 'achat' else 'prix_vente'))
        ventes = ventes_par_produit.get(pid) or {}
        entrees = entrees_autres
        sorties = sorties_ventes + sorties_autres
        lignes.append({
            'id': pid,
            'nom': fiche.get('nom') or (p or {}).get('nom') or (a or {}).get('nom') or pid,
            'unite': fiche.get('unite') or '',
            'supprime': pid not in produits,
            'stock_initial': _entier(initial),
            'entrees': _entier(entrees),
            'entrees_appro': _entier(appro),
            'entrees_autres': _entier(entrees - appro),
            'sorties': _entier(sorties),
            'sorties_ventes': _entier(sorties_ventes),
            'sorties_autres': _entier(sorties_autres),
            'stock_final': _entier(final),
            'ecart_non_journalise': _entier(ecart) if ecart else 0,
            'nb_mouvements': nb,
            'quantite_vendue': _entier(ventes.get('quantite')),
            'montant_ventes': round(_n(ventes.get('montant'))),
            'prix_unitaire': prix,
            'valeur_initial': round(max(initial, 0) * prix),
            'valeur_entrees': round(entrees * prix),
            'valeur_sorties': round(sorties * prix),
            'valeur_final': round(max(final, 0) * prix),
        })
    lignes.sort(key=lambda l: (l['nom'] or '').lower())
    return {'lignes': lignes, 'totaux': totaux(lignes), 'base_prix': base_prix,
            'base_prix_libelle': BASES_PRIX[base_prix]}


def totaux(lignes):
    cles = ('stock_initial', 'entrees', 'sorties', 'stock_final', 'montant_ventes',
            'valeur_initial', 'valeur_entrees', 'valeur_sorties', 'valeur_final', 'nb_mouvements')
    t = {k: _entier(sum(_n(l[k]) for l in lignes)) for k in cles}
    t['nb_medicaments'] = len(lignes)
    t['nb_sans_prix'] = sum(1 for l in lignes if not l['prix_unitaire'])
    return t


def filtrer(lignes, recherche='', seulement_bouges=False):
    """Mêmes filtres à l'écran et dans les exports. Par défaut : les médicaments qui ont eu du
    stock ou un mouvement sur la période (un produit supprimé avant et resté à 0 n'apparaît pas)."""
    q = (recherche or '').strip().lower()
    res = []
    for l in lignes:
        if q and q not in (l['nom'] or '').lower():
            continue
        if seulement_bouges and not l['nb_mouvements']:
            continue
        if not l['nb_mouvements'] and not l['stock_initial'] and not l['stock_final']:
            continue
        res.append(l)
    return res


def ventes_par_produit(ventes, lire_liste):
    """{pid: {quantite, montant}} à partir des lignes « produits » des ventes (prix facturé)."""
    res = {}
    for v in ventes:
        for x in lire_liste(v.get('produits')):
            pid = str(x.get('id') or '').strip()
            if not pid:
                continue
            q = _n(x.get('quantite') or 1)
            prix = x.get('prix') if x.get('prix') is not None else x.get('prix_reel')
            total = _n(x.get('total')) if x.get('total') is not None else _n(prix) * q
            d = res.setdefault(pid, {'quantite': 0.0, 'montant': 0.0})
            d['quantite'] += q
            d['montant'] += total
    return res


# ---------------------------------------------------------------- exports
def _f(v):
    return f"{round(_n(v)):,}".replace(',', ' ')


def _q(v):
    v = _n(v)
    return f"{int(v):,}".replace(',', ' ') if v == int(v) else f"{v:.2f}".replace('.', ',')


def _valeurs(l):
    return [l['nom'] + (' (supprimé)' if l['supprime'] else ''), l['unite'], _q(l['stock_initial']),
            _q(l['entrees']), _q(l['sorties']), _q(l['stock_final']), _f(l['montant_ventes']),
            _f(l['prix_unitaire']), _f(l['valeur_final'])]


def _ligne_total(t):
    return ['TOTAL', '', _q(t['stock_initial']), _q(t['entrees']), _q(t['sorties']),
            _q(t['stock_final']), _f(t['montant_ventes']), '', _f(t['valeur_final'])]


def _titre(situation):
    return (f"Situation périodique des médicaments — du {situation['debut_affiche']} au "
            f"{situation['fin_affiche']} — valeur au {situation['base_prix_libelle']}")


def exporter_csv(situation, lignes):
    tampon = io.StringIO()
    w = csv.writer(tampon, delimiter=';')
    w.writerow([_titre(situation)])
    w.writerow([])
    w.writerow(COLONNES)
    for l in lignes:
        w.writerow([l['nom'] + (' (supprimé)' if l['supprime'] else ''), l['unite'],
                    l['stock_initial'], l['entrees'], l['sorties'], l['stock_final'],
                    l['montant_ventes'], round(l['prix_unitaire']), l['valeur_final']])
    t = totaux(lignes)
    w.writerow(['TOTAL', '', t['stock_initial'], t['entrees'], t['sorties'], t['stock_final'],
                t['montant_ventes'], '', t['valeur_final']])
    return '﻿' + tampon.getvalue()          # BOM : Excel lit les accents correctement


def exporter_texte(situation, lignes, structure_nom=''):
    t = totaux(lignes)
    table = [COLONNES] + [_valeurs(l) for l in lignes] + [_ligne_total(t)]
    largeurs = [max(len(str(r[i])) for r in table) for i in range(len(COLONNES))]

    def fmt(r):
        return '  '.join(str(v).ljust(largeurs[i]) if i < 2 else str(v).rjust(largeurs[i])
                         for i, v in enumerate(r)).rstrip()
    sep = '-' * len(fmt(COLONNES))
    entete = [structure_nom or '', _titre(situation),
              f"Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — {len(lignes)} médicament(s)",
              f"Valeur du stock : début {_f(t['valeur_initial'])} F · entrées {_f(t['valeur_entrees'])} F · "
              f"sorties {_f(t['valeur_sorties'])} F · fin {_f(t['valeur_final'])} F",
              '']
    corps = [fmt(COLONNES), sep] + [fmt(r) for r in table[1:-1]] + [sep, fmt(table[-1])]
    return '\n'.join(entete + corps) + '\n'


def exporter_pdf(situation, lignes, structure_nom='', auteur=''):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def esc(t):
        return (str(t or '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title='Situation périodique des médicaments', author=structure_nom or '',
                            creator='SSoftOneV10')
    st = getSampleStyleSheet()
    s_titre = ParagraphStyle('t', parent=st['Title'], fontSize=15, spaceAfter=2)
    s_sous = ParagraphStyle('s', parent=st['Normal'], fontSize=9, alignment=1,
                            textColor=colors.HexColor('#444444'))
    s_cel = ParagraphStyle('c', parent=st['Normal'], fontSize=8, leading=9.5)
    t = totaux(lignes)
    elements = [
        Paragraph(esc(structure_nom or 'Situation périodique'), s_titre),
        Paragraph(f"Situation périodique des médicaments — du {esc(situation['debut_affiche'])} "
                  f"au {esc(situation['fin_affiche'])}", s_sous),
        Paragraph(f"Valeur au {esc(situation['base_prix_libelle'])} · édité le "
                  f"{datetime.now().strftime('%d/%m/%Y à %H:%M')}" + (f" par {esc(auteur)}" if auteur else '')
                  + f" · {len(lignes)} médicament(s)", s_sous),
        Spacer(1, 4 * mm),
    ]
    synthese = Table([
        ['Valeur du stock au début', 'Valeur des entrées', 'Valeur des sorties', 'Valeur du stock à la fin',
         'Montant des ventes'],
        [_f(t['valeur_initial']) + ' F', _f(t['valeur_entrees']) + ' F', _f(t['valeur_sorties']) + ' F',
         _f(t['valeur_final']) + ' F', _f(t['montant_ventes']) + ' F'],
    ], colWidths=[54 * mm] * 5)
    synthese.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, 0), 'Helvetica', 8), ('FONT', (0, 1), (-1, 1), 'Helvetica-Bold', 11),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('BOX', (0, 0), (-1, -1), 0.8, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#999999')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
    ]))
    elements += [synthese, Spacer(1, 4 * mm)]

    donnees = [COLONNES] + [[Paragraph(esc(v[0]), s_cel)] + v[1:] for v in map(_valeurs, lignes)] \
        + [_ligne_total(t)]
    tableau = Table(donnees, repeatRows=1,
                    colWidths=[78 * mm, 18 * mm, 22 * mm, 20 * mm, 20 * mm, 22 * mm, 30 * mm, 24 * mm, 36 * mm])
    tableau.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#333333')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONT', (0, 1), (-1, -1), 'Helvetica', 8),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#bbbbbb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f6f6f6')]),
        ('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 8.5), ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(tableau)
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(
        "Stock final = stock initial + entrées - sorties. Entrées : approvisionnements, écarts d'inventaire "
        "positifs, créations. Sorties : ventes (hors ventes annulées), écarts d'inventaire négatifs, suppressions. "
        "Montant des ventes : prix réellement facturés sur la période.",
        ParagraphStyle('n', parent=s_cel, fontSize=7, textColor=colors.HexColor('#555555'))))
    doc.build(elements)
    return tampon.getvalue()
