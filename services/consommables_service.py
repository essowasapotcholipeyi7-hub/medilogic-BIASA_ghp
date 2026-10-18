# -*- coding: utf-8 -*-
"""Stock du laboratoire et de la radiologie (patron, 2026-10-18) : films (radio), tubes et réactifs
(labo). Chaque article a une quantité disponible et sert à un ou plusieurs types d'examens, avec la
quantité utilisée par examen ; le logiciel en déduit combien d'examens on peut encore réaliser (le
nombre peut être ajusté à la main : la quantité par examen est alors recalculée).

Quand un examen est marqué « réalisé » (Laboratoire / Radiologie), la quantité de chaque article lié à
cet acte est déduite du stock ; s'il repasse « en attente » ou « annulé », elle est remise. Chaque
mouvement est gardé (approvisionnement, examen, retour, inventaire) pour l'inventaire de fin de mois.
Alerte quand le stock atteint le seuil (20 % de la quantité de départ par défaut)."""
import math
from datetime import datetime
from decimal import Decimal

from models import db, ConsommableLabo, UsageConsommable, MouvementConsommable, ParametrageStockLabo

CATEGORIES = {
    'examen': {'film': 'Film', 'autre': 'Autre consommable'},
    'analyse': {'reactif': 'Réactif', 'tube': 'Tube', 'autre': 'Autre consommable'},
}
UNITES_PAR_DEFAUT = {'film': 'film(s)', 'tube': 'tube(s)', 'reactif': 'ml', 'autre': 'unité(s)'}
TYPES_MOUVEMENT = {'entree': 'Approvisionnement', 'sortie': 'Examen réalisé', 'retour': 'Examen annulé (remis en stock)',
                   'utilisation': 'Utilisation saisie', 'inventaire': 'Écart d\'inventaire', 'correction': 'Correction'}
# ce qui compte comme « utilisé » dans l'inventaire (examens enregistrés ou utilisation saisie à la main)
TYPES_UTILISATION = ('sortie', 'retour', 'utilisation')


def deduction_auto(structure_id, filiere):
    """Le stock baisse-t-il tout seul quand un examen est marqué réalisé ? (oui par défaut)"""
    p = ParametrageStockLabo.query.filter_by(structure_id=structure_id, filiere=filiere).first()
    return True if p is None else bool(p.deduction_auto)
SEUIL_PAR_DEFAUT = Decimal('0.20')


def _d(v):
    try:
        return Decimal(str(v if v not in (None, '') else 0).replace(',', '.'))
    except Exception:
        return Decimal(0)


def nombre(v):
    """Decimal -> int si entier, sinon float (affichage / JSON)."""
    v = _d(v)
    return int(v) if v == v.to_integral_value() else float(round(v, 3))


def seuil_par_defaut(quantite):
    q = _d(quantite)
    return Decimal(math.ceil(q * SEUIL_PAR_DEFAUT)) if q > 0 else None


def niveau(c):
    """'epuise' | 'alerte' | 'ok'."""
    q = _d(c.quantite)
    if q <= 0:
        return 'epuise'
    if c.seuil_alerte is not None and q <= _d(c.seuil_alerte):
        return 'alerte'
    return 'ok'


def examens_possibles(quantite, quantite_par_examen):
    qpe = _d(quantite_par_examen)
    if qpe <= 0:
        return None
    return int(max(_d(quantite), 0) / qpe)


def mouvement(c, type_mouvement, quantite, auteur=None, demande=None, commentaire=None, date=None, nb_examens=None):
    """Applique un mouvement (quantité signée) au stock et le garde. Le stock ne descend pas sous 0.
    `date` : jour de l'utilisation saisie à la main (par défaut maintenant)."""
    q = _d(quantite)
    c.quantite = max(_d(c.quantite) + q, Decimal(0))
    m = MouvementConsommable(
        structure_id=c.structure_id, consommable_id=c.id, date=date or datetime.utcnow(), type_mouvement=type_mouvement,
        nb_examens=nb_examens,
        quantite=q, stock_apres=c.quantite, demande_id=demande.id if demande else None,
        acte_nom=demande.acte_nom if demande else None, commentaire=(commentaire or '')[:300] or None, auteur=auteur)
    db.session.add(m)
    return m


def consommer_pour_demande(demande, auteur=None):
    """Examen réalisé : déduit chaque article lié à son acte (une seule fois par demande) — sauf si la
    structure saisit l'utilisation à la main pour cette filière."""
    if not deduction_auto(demande.structure_id, demande.type_prestation):
        return []
    usages = UsageConsommable.query.filter_by(structure_id=demande.structure_id, acte_nom=demande.acte_nom).all()
    if not usages:
        return []
    faits = []
    for u in usages:
        c = ConsommableLabo.query.filter_by(id=u.consommable_id, structure_id=demande.structure_id).first()
        if not c or not c.actif:
            continue
        net = db.session.query(db.func.coalesce(db.func.sum(MouvementConsommable.quantite), 0)).filter(
            MouvementConsommable.consommable_id == c.id, MouvementConsommable.demande_id == demande.id).scalar()
        if _d(net) < 0:   # déjà déduit pour cet examen
            continue
        q = _d(u.quantite_par_examen) * max(int(demande.quantite or 1), 1)
        faits.append(mouvement(c, 'sortie', -q, auteur, demande))
    return faits


def restituer_pour_demande(demande, auteur=None):
    """Examen remis en attente / annulé : remet ce qui avait été déduit pour lui."""
    lignes = db.session.query(MouvementConsommable.consommable_id, db.func.sum(MouvementConsommable.quantite)).filter(
        MouvementConsommable.structure_id == demande.structure_id, MouvementConsommable.demande_id == demande.id,
        MouvementConsommable.type_mouvement.in_(('sortie', 'retour'))).group_by(MouvementConsommable.consommable_id).all()
    faits = []
    for cid, net in lignes:
        if _d(net) < 0:
            c = ConsommableLabo.query.get(cid)
            if c:
                faits.append(mouvement(c, 'retour', -_d(net), auteur, demande))
    return faits


def apres_changement_statut(demande, ancien_statut, auteur=None):
    """À appeler quand le statut d'une demande change (avant le commit)."""
    try:
        if demande.statut == 'realisee' and ancien_statut != 'realisee':
            consommer_pour_demande(demande, auteur)
        elif ancien_statut == 'realisee' and demande.statut != 'realisee':
            restituer_pour_demande(demande, auteur)
    except Exception as e:   # le stock ne doit jamais bloquer le circuit des examens
        print(f"⚠️ Stock labo/radio non mis à jour pour la demande {demande.id} : {e}")


def alertes(structure_id, filiere=None):
    q = ConsommableLabo.query.filter_by(structure_id=structure_id, actif=True)
    if filiere:
        q = q.filter_by(filiere=filiere)
    return [c for c in q.order_by(ConsommableLabo.nom).all() if niveau(c) != 'ok']


def rapport_periode(structure_id, filiere, debut, fin):
    """Inventaire d'une période [debut, fin[ : pour chaque article, stock au début, entrées, examens
    (consommation nette), écarts d'inventaire, stock à la fin, et quantité à commander."""
    articles = ConsommableLabo.query.filter_by(structure_id=structure_id, filiere=filiere)\
        .order_by(ConsommableLabo.categorie, ConsommableLabo.nom).all()
    res = []
    for c in articles:
        def somme(types, depuis, jusqu=None):
            q = db.session.query(db.func.coalesce(db.func.sum(MouvementConsommable.quantite), 0)).filter(
                MouvementConsommable.consommable_id == c.id, MouvementConsommable.date >= depuis,
                MouvementConsommable.type_mouvement.in_(types))
            if jusqu is not None:
                q = q.filter(MouvementConsommable.date < jusqu)
            return _d(q.scalar())
        tous = tuple(TYPES_MOUVEMENT)
        apres_fin = somme(tous, fin)
        stock_fin = _d(c.quantite) - apres_fin
        periode = somme(tous, debut, fin)
        stock_debut = stock_fin - periode
        entrees = somme(('entree',), debut, fin)
        consommation = -(somme(TYPES_UTILISATION, debut, fin))
        ecarts = somme(('inventaire', 'correction'), debut, fin)
        nb_examens = db.session.query(db.func.count(db.func.distinct(MouvementConsommable.demande_id))).filter(
            MouvementConsommable.consommable_id == c.id, MouvementConsommable.date >= debut,
            MouvementConsommable.date < fin, MouvementConsommable.type_mouvement == 'sortie').scalar() or 0
        nb_examens += db.session.query(db.func.coalesce(db.func.sum(MouvementConsommable.nb_examens), 0)).filter(
            MouvementConsommable.consommable_id == c.id, MouvementConsommable.date >= debut,
            MouvementConsommable.date < fin, MouvementConsommable.type_mouvement == 'utilisation').scalar() or 0
        besoin = max(consommation, _d(c.seuil_alerte))
        a_commander = max(math.ceil(besoin - stock_fin), 0) if (consommation > 0 or niveau(c) != 'ok') else 0
        res.append({
            'id': c.id, 'nom': c.nom, 'categorie': c.categorie, 'type_article': c.type_article or '',
            'unite': c.unite or '', 'actif': bool(c.actif), 'niveau': niveau(c),
            'stock_debut': nombre(stock_debut), 'entrees': nombre(entrees), 'consommation': nombre(consommation),
            'nb_examens': int(nb_examens), 'ecarts': nombre(ecarts), 'stock_fin': nombre(stock_fin),
            'stock_actuel': nombre(c.quantite), 'seuil': nombre(c.seuil_alerte) if c.seuil_alerte is not None else None,
            'a_commander': a_commander,
        })
    return res
