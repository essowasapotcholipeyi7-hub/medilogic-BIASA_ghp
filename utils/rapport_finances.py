"""⭐ Rapport financier de « Caisse et charges » (patron, 2026-10-14 : « au niveau de rapport,
je veux qu'on affiche plus de détails selon les sources de recettes et dépenses par motif ;
l'export CSV, c'est mieux en PDF, pour que ça s'affiche bien et non modifiable »).

Un seul calcul pour l'écran (/api/finances/rapport) et pour le PDF (/finances/rapport/pdf),
donc les mêmes chiffres partout, et des sommes qui se recoupent :
- recettes = la table `recettes` (l'argent réellement entré en caisse), détaillée par
  origine ; la somme des lignes = le total des recettes ;
- charges = la table `depenses` (charges validées), par motif, avec chaque charge ;
- solde de la période = recettes − charges ;
- activité des ventes : à part, pour information (ce qui a été vendu, encaissé à la vente,
  laissé en créance, à recevoir des assurances) — ce n'est pas de l'argent en caisse.
"""
import re
import secrets
from datetime import date, datetime, timedelta
from io import BytesIO

LIBELLES_RECETTES = {
    ('patients', 'vente_acte'): "Ventes d'actes (encaissé)",
    ('patients', 'vente_pharma'): 'Ventes pharmacie (encaissé)',
    ('patients', 'vente_proforma'): 'Ventes issues de proformas (encaissé)',
    ('patients', 'facture'): 'Règlements de créances (factures)',
    ('patients', None): 'Autres recettes patients',
    ('assurance', None): 'Remboursements des assurances',
    ('assurance', 'vente_acte'): "Parts d'assurance comptées à la vente (ancien fonctionnement)",
    ('assurance', 'vente_pharma'): "Parts d'assurance comptées à la vente (ancien fonctionnement)",
    ('autres', None): 'Autres recettes',
}
GROUPES_RECETTES = {'patients': 'Patients', 'assurance': 'Assurances', 'autres': 'Autres recettes'}
ORDRE_GROUPES = ['patients', 'assurance', 'autres']

LIBELLES_MOTIFS = {
    'abonnement_ssoftonev10': 'Abonnement SSoftOneV10',
    'theme_logiciel': 'Thème du logiciel',
    'salaire': 'Salaires',
    'assurance': 'Versements assurance',
    'reparation': 'Réparations',
    'fourniture': 'Fournitures médicales',
    'eau': 'Eau',
    'electricite': 'Électricité',
    'internet': 'Internet',
    'loyer': 'Loyer',
    'materiel': 'Matériel informatique',
    'transport': 'Transport',
    'communication': 'Communication',
    'autres': 'Autres charges',
}
LIBELLES_TYPES_VENTE = {'actes': 'Actes', 'pharmacie': 'Pharmacie', 'pharma': 'Pharmacie', 'mixte': 'Mixtes (actes + produits)'}

_ASSURANCE_RE = re.compile(r'^Remboursement assurance\s+(.+?)\s+[-—]\s', re.IGNORECASE)
_NOMS_ASSURANCE = {'AMU_CNSS': 'AMU-CNSS', 'AMU_INAM': 'AMU-INAM', 'AMU_TNS': 'AMU-TNS'}


def lire_periode(date_debut, date_fin):
    """Période demandée ('AAAA-MM-JJ') ; par défaut le mois en cours jusqu'à aujourd'hui."""
    def lire(v):
        try:
            return datetime.strptime(v, '%Y-%m-%d').date() if v else None
        except ValueError:
            return None
    aujourdhui = date.today()
    debut = lire(date_debut) or aujourdhui.replace(day=1)
    fin = lire(date_fin) or aujourdhui
    if fin < debut:
        debut, fin = fin, debut
    return debut, fin


def _f(v):
    return float(v or 0)


def _nom_assurance(description):
    m = _ASSURANCE_RE.match(description or '')
    if not m:
        return 'Assurance non précisée'
    nom = m.group(1).strip().upper()
    return _NOMS_ASSURANCE.get(nom, nom)


def _libelle_motif(motif):
    if not motif:
        return 'Autres charges'
    if motif.lower().startswith('part médecin') or motif.lower().startswith('part medecin'):
        return 'Parts médecins'
    return LIBELLES_MOTIFS.get(motif, motif[:1].upper() + motif[1:])


def calculer_rapport(execute_query, structure_id, debut, fin):
    borne_debut = datetime.combine(debut, datetime.min.time())
    borne_fin = datetime.combine(fin + timedelta(days=1), datetime.min.time())

    # ---------------------------------------------------------------- recettes
    lignes_rec = execute_query("""
        SELECT source, source_type, description, montant, date_recette, created_by_nom
        FROM recettes
        WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)
          AND date_recette >= %s AND date_recette < %s
        ORDER BY date_recette
    """, (structure_id, borne_debut, borne_fin)) or []

    lignes = {}   # (source, type) -> ligne
    for r in lignes_rec:
        source = (r.get('source') or 'autres').lower()
        if source not in GROUPES_RECETTES:
            source = 'autres'
        type_ = r.get('source_type') or None
        if source == 'assurance' and type_ == 'vente_pharma':
            type_ = 'vente_acte'   # même ligne « ancien fonctionnement », actes ou pharmacie
        cle = (source, type_)
        if cle not in LIBELLES_RECETTES:
            cle = (source, None) if (source, None) in LIBELLES_RECETTES else ('autres', None)
        ligne = lignes.setdefault(cle, {'libelle': LIBELLES_RECETTES[cle], 'nombre': 0, 'total': 0.0, 'details': {}})
        montant = _f(r.get('montant'))
        ligne['nombre'] += 1
        ligne['total'] += montant
        if cle == ('assurance', None):
            d = ligne['details'].setdefault(_nom_assurance(r.get('description')), {'libelle': _nom_assurance(r.get('description')), 'nombre': 0, 'total': 0.0})
            d['nombre'] += 1
            d['total'] += montant
        elif cle[1] is None:
            # recettes saisies à la main : chacune est listée
            libelle = (r.get('description') or '').strip() or 'Sans description'
            quand = r.get('date_recette')
            cle_d = f"{len(ligne['details'])}"
            ligne['details'][cle_d] = {'libelle': libelle, 'nombre': 1, 'total': montant,
                                       'date': quand.strftime('%d/%m/%Y') if hasattr(quand, 'strftime') else ''}

    groupes = []
    for source in ORDRE_GROUPES:
        cles = [c for c in lignes if c[0] == source]
        cles.sort(key=lambda c: list(LIBELLES_RECETTES).index(c) if c in LIBELLES_RECETTES else 99)
        if not cles:
            continue
        lignes_groupe = []
        for c in cles:
            l = lignes[c]
            details = list(l['details'].values())
            if c == ('assurance', None):
                details.sort(key=lambda d: -d['total'])
            lignes_groupe.append({'libelle': l['libelle'], 'nombre': l['nombre'], 'total': round(l['total'], 2), 'details': details})
        groupes.append({'groupe': GROUPES_RECETTES[source], 'lignes': lignes_groupe,
                        'total': round(sum(l['total'] for l in lignes_groupe), 2)})
    total_recettes = round(sum(g['total'] for g in groupes), 2)

    # ---------------------------------------------------------------- charges
    lignes_dep = execute_query("""
        SELECT id, motif, motif_personnalise, description, montant, date_depense, created_by_nom
        FROM depenses
        WHERE structure_id = %s AND date_depense >= %s AND date_depense < %s
        ORDER BY date_depense
    """, (structure_id, borne_debut, borne_fin)) or []
    motifs = {}
    for d in lignes_dep:
        libelle_motif = _libelle_motif(d.get('motif'))
        m = motifs.setdefault(libelle_motif, {'libelle': libelle_motif, 'nombre': 0, 'total': 0.0, 'details': []})
        montant = _f(d.get('montant'))
        m['nombre'] += 1
        m['total'] += montant
        precision = (d.get('motif_personnalise') or '').strip() or (d.get('description') or '').strip()
        if libelle_motif == 'Parts médecins' and d.get('motif') not in LIBELLES_MOTIFS:
            precision = precision or d.get('motif')
        quand = d.get('date_depense')
        m['details'].append({'date': quand.strftime('%d/%m/%Y') if hasattr(quand, 'strftime') else '',
                             'libelle': precision or libelle_motif, 'par': d.get('created_by_nom') or '',
                             'total': montant})
    total_charges = round(sum(m['total'] for m in motifs.values()), 2)
    charges = sorted(motifs.values(), key=lambda m: -m['total'])
    for m in charges:
        m['total'] = round(m['total'], 2)
        m['pourcentage'] = round(m['total'] / total_charges * 100, 1) if total_charges else 0

    # ---------------------------------------------------------------- activité des ventes
    ventes = execute_query("""
        SELECT type, COUNT(*) AS nombre,
               COALESCE(SUM(net_a_payer), 0) AS net_patient,
               COALESCE(SUM(COALESCE(montant_donne, 0) - COALESCE(rendu, 0)), 0) AS encaisse,
               COALESCE(SUM(reste_a_payer), 0) AS reste,
               COALESCE(SUM(COALESCE(prise_en_charge, 0) + COALESCE(prise_en_charge2, 0)), 0) AS part_assurances
        FROM ventes
        WHERE structure_id = %s AND (statut IS NULL OR statut != 'annulee')
          AND date_vente >= %s AND date_vente < %s
        GROUP BY type
    """, (structure_id, borne_debut, borne_fin)) or []
    activite = {}
    for v in ventes:
        libelle = LIBELLES_TYPES_VENTE.get(v.get('type'), v.get('type') or 'Autres')
        a = activite.setdefault(libelle, {'libelle': libelle, 'nombre': 0, 'net_patient': 0.0, 'encaisse': 0.0, 'reste': 0.0, 'part_assurances': 0.0})
        for k in ('nombre', 'net_patient', 'encaisse', 'reste', 'part_assurances'):
            a[k] += _f(v.get(k)) if k != 'nombre' else int(v.get(k) or 0)
    activite = sorted(activite.values(), key=lambda a: -a['net_patient'])
    total_activite = {k: round(sum(a[k] for a in activite), 2) for k in ('net_patient', 'encaisse', 'reste', 'part_assurances')}
    total_activite['nombre'] = sum(a['nombre'] for a in activite)

    solde = round(total_recettes - total_charges, 2)
    return {
        'periode': {'debut': debut.isoformat(), 'fin': fin.isoformat(),
                    'libelle': f"du {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')}"},
        'total_recettes': total_recettes,
        'total_charges': total_charges,
        'solde': solde,
        'marge': round(solde / total_recettes * 100, 1) if total_recettes else 0,
        'recettes': groupes,
        'charges': charges,
        'ventes': activite,
        'total_ventes': total_activite,
    }


# ====================================================================== PDF
def _fcfa(v):
    return f"{round(float(v or 0)):,}".replace(',', ' ') + ' FCFA'


def generer_pdf(rapport, structure_nom, auteur):
    """PDF du rapport — verrouillé : impression autorisée, modification / copie interdites."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

    tampon = BytesIO()
    verrou = StandardEncryption('', ownerPassword=secrets.token_hex(16), canPrint=1,
                                canModify=0, canCopy=0, canAnnotate=0)
    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm, encrypt=verrou,
                            title=f"Rapport financier {rapport['periode']['libelle']}",
                            author=structure_nom or '', creator='SSoftOneV10')
    st = getSampleStyleSheet()
    s_titre = ParagraphStyle('t', parent=st['Title'], fontSize=16, spaceAfter=2)
    s_sous = ParagraphStyle('s', parent=st['Normal'], fontSize=9, textColor=colors.HexColor('#555555'), alignment=1)
    s_h2 = ParagraphStyle('h2', parent=st['Heading2'], fontSize=12, spaceBefore=8, spaceAfter=4)
    s_n = ParagraphStyle('n', parent=st['Normal'], fontSize=8.5, leading=10.5)
    s_d = ParagraphStyle('d', parent=s_n, textColor=colors.HexColor('#444444'), leftIndent=8)
    s_note = ParagraphStyle('note', parent=s_n, fontSize=7.5, textColor=colors.HexColor('#666666'))

    def esc(t):
        return (str(t or '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    gris = colors.HexColor('#eeeeee')
    sombre = colors.HexColor('#333333')

    def tableau(entetes, lignes, largeurs, lignes_total=(), lignes_groupe=(), lignes_detail=()):
        t = Table([entetes] + lignes, colWidths=largeurs, repeatRows=1)
        style = [
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8.5),
            ('BACKGROUND', (0, 0), (-1, 0), sombre),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONT', (0, 1), (-1, -1), 'Helvetica', 8.5),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#cccccc')),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ]
        for i in lignes_groupe:
            style += [('FONT', (0, i), (-1, i), 'Helvetica-Bold', 8.5), ('BACKGROUND', (0, i), (-1, i), gris)]
        for i in lignes_detail:
            style += [('FONT', (0, i), (-1, i), 'Helvetica', 7.5), ('TEXTCOLOR', (0, i), (-1, i), colors.HexColor('#555555'))]
        for i in lignes_total:
            style += [('FONT', (0, i), (-1, i), 'Helvetica-Bold', 9), ('LINEABOVE', (0, i), (-1, i), 1, sombre)]
        t.setStyle(TableStyle(style))
        return t

    elements = [
        Paragraph(esc(structure_nom or 'Rapport financier'), s_titre),
        Paragraph(f"Rapport financier — période {esc(rapport['periode']['libelle'])}", s_sous),
        Paragraph(f"Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')}" + (f" par {esc(auteur)}" if auteur else ''), s_sous),
        Spacer(1, 6 * mm),
    ]

    # synthèse
    synthese = [
        ['Total des recettes', _fcfa(rapport['total_recettes'])],
        ['Total des charges', _fcfa(rapport['total_charges'])],
        ['Solde de la période (recettes - charges)', _fcfa(rapport['solde'])],
        ['Marge', f"{rapport['marge']} %"],
    ]
    elements += [Paragraph('Synthèse', s_h2), tableau(['', 'Montant'], synthese, [120 * mm, 60 * mm], lignes_total=(3,))]

    # recettes
    lignes, groupes_i, details_i, total_i = [], [], [], []
    for g in rapport['recettes']:
        lignes.append([g['groupe'], '', _fcfa(g['total'])]); groupes_i.append(len(lignes))
        for l in g['lignes']:
            lignes.append([Paragraph(esc(l['libelle']), s_n), str(l['nombre']), _fcfa(l['total'])])
            for d in l['details']:
                lib = (f"{d['date']} — " if d.get('date') else '') + d['libelle']
                lignes.append([Paragraph(esc(lib), s_d), str(d['nombre']), _fcfa(d['total'])]); details_i.append(len(lignes))
    lignes.append(['TOTAL DES RECETTES', '', _fcfa(rapport['total_recettes'])]); total_i.append(len(lignes))
    elements += [Paragraph('Recettes par source', s_h2)]
    elements += [tableau(['Origine', 'Opérations', 'Montant'], lignes, [120 * mm, 22 * mm, 38 * mm], total_i, groupes_i, details_i)
                 if rapport['recettes'] else Paragraph('Aucune recette sur la période.', s_n)]

    # charges
    lignes, groupes_i, details_i, total_i = [], [], [], []
    for m in rapport['charges']:
        lignes.append([m['libelle'], str(m['nombre']), f"{m['pourcentage']} %", _fcfa(m['total'])]); groupes_i.append(len(lignes))
        for d in m['details']:
            lib = f"{d['date']} — {d['libelle']}" + (f" (par {d['par']})" if d.get('par') else '')
            lignes.append([Paragraph(esc(lib), s_d), '', '', _fcfa(d['total'])]); details_i.append(len(lignes))
    lignes.append(['TOTAL DES CHARGES', '', '100 %' if rapport['charges'] else '', _fcfa(rapport['total_charges'])]); total_i.append(len(lignes))
    elements += [Paragraph('Charges par motif', s_h2)]
    elements += [tableau(['Motif / charge', 'Nombre', '%', 'Montant'], lignes, [110 * mm, 18 * mm, 16 * mm, 36 * mm], total_i, groupes_i, details_i)
                 if rapport['charges'] else Paragraph('Aucune charge sur la période.', s_n)]

    # activité des ventes
    if rapport['ventes']:
        lignes = [[a['libelle'], str(a['nombre']), _fcfa(a['net_patient']), _fcfa(a['encaisse']), _fcfa(a['reste']), _fcfa(a['part_assurances'])]
                  for a in rapport['ventes']]
        t = rapport['total_ventes']
        lignes.append(['TOTAL', str(t['nombre']), _fcfa(t['net_patient']), _fcfa(t['encaisse']), _fcfa(t['reste']), _fcfa(t['part_assurances'])])
        elements += [KeepTogether([
            Paragraph('Activité des ventes (pour information)', s_h2),
            tableau(['Type', 'Ventes', 'Net patient', 'Encaissé', 'Reste dû', 'Part assurances'], lignes,
                    [38 * mm, 15 * mm, 32 * mm, 32 * mm, 30 * mm, 33 * mm], lignes_total=(len(lignes),)),
            Spacer(1, 2 * mm),
            Paragraph("« Encaissé » est déjà compté dans les recettes ci-dessus. « Reste dû » est la part laissée "
                      "en créance par les patients (elle entre en recette quand elle est réglée) ; « Part assurances » "
                      "est ce que les assurances doivent (elle entre en recette à leur remboursement).", s_note),
        ])]

    def pied(canvas, d):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawString(15 * mm, 9 * mm, f"{structure_nom or ''} — Rapport financier {rapport['periode']['libelle']}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=pied, onLaterPages=pied)
    return tampon.getvalue()
