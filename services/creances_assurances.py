# -*- coding: utf-8 -*-
"""Situation des assurances pour le tableau de bord (patron, 2026-10-14 :
« est-ce que ces sommes diminuent quand l'assurance rembourse ? »).

Avant, les cartes affichaient le CUMUL des prises en charge depuis
l'ouverture : il ne baissait jamais, même après un remboursement. On montre
maintenant ce qui reste réellement à percevoir :

    reste à percevoir = prise en charge des ventes (non annulées)
                        − remboursements encaissés (factures_assurance.montant_rembourse)

- prise en charge : ventes.prise_en_charge (principale) / prise_en_charge2
  (complémentaire), c'est ce que l'assurance doit, facture générée ou non ;
- remboursé : seuls les encaissements VALIDÉS par l'admin alimentent
  montant_rembourse (voir _executer_paiement_assurance) ; ceux encore en
  attente de validation sont donnés à part (« en attente ») ;
- facturé ce mois : prises en charge des ventes du mois en cours.
"""
from datetime import date

from sqlalchemy import text

from models import db, FactureAssurance, ValidationDemande

MOIS_FR = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
           'août', 'septembre', 'octobre', 'novembre', 'décembre']


def _type_facture(type_assurance):
    return 'complementaire' if (type_assurance or '').strip().lower() == 'complementaire' else 'principale'


def _encaissements_en_attente(structure_id):
    """Montants d'encaissement demandés mais pas encore validés, par type d'assurance."""
    lignes = []
    for d in ValidationDemande.query.filter(
            ValidationDemande.structure_id == structure_id,
            ValidationDemande.statut == 'en_attente',
            ValidationDemande.type_demande.in_(['encaissement_assurance', 'encaissement_assurance_global'])).all():
        p = d.payload or {}
        if d.type_demande == 'encaissement_assurance':
            lignes.append((p.get('facture_id') or d.reference_id, p.get('montant')))
        else:
            lignes.extend((l.get('facture_id'), l.get('montant')) for l in (p.get('repartition') or []))
    ids = set()
    for fid, _ in lignes:
        try:
            ids.add(int(fid))
        except (TypeError, ValueError):
            pass
    types = {f.id: _type_facture(f.type_assurance) for f in
             FactureAssurance.query.filter(FactureAssurance.structure_id == structure_id,
                                           FactureAssurance.id.in_(ids)).all()} if ids else {}
    resultat = {'principale': 0.0, 'complementaire': 0.0}
    for fid, montant in lignes:
        try:
            t = types.get(int(fid))
            if t:
                resultat[t] += float(montant or 0)
        except (TypeError, ValueError):
            continue
    return resultat


def situation_assurances(structure_id, aujourd_hui=None):
    aujourd_hui = aujourd_hui or date.today()
    debut_mois = aujourd_hui.replace(day=1)
    debut_mois_suivant = (debut_mois.replace(year=debut_mois.year + 1, month=1) if debut_mois.month == 12
                          else debut_mois.replace(month=debut_mois.month + 1))

    pec = db.session.execute(text("""
        SELECT COALESCE(SUM(CASE WHEN prise_en_charge > 0 THEN prise_en_charge ELSE 0 END), 0) AS p1,
               COALESCE(SUM(CASE WHEN prise_en_charge2 > 0 THEN prise_en_charge2 ELSE 0 END), 0) AS p2,
               COALESCE(SUM(CASE WHEN date_vente >= :debut AND date_vente < :fin AND prise_en_charge > 0
                                 THEN prise_en_charge ELSE 0 END), 0) AS m1,
               COALESCE(SUM(CASE WHEN date_vente >= :debut AND date_vente < :fin AND prise_en_charge2 > 0
                                 THEN prise_en_charge2 ELSE 0 END), 0) AS m2
        FROM ventes
        WHERE structure_id = :sid AND (statut IS NULL OR statut != 'annulee')
    """), {'sid': structure_id, 'debut': debut_mois, 'fin': debut_mois_suivant}).first()

    rembourse = {'principale': 0.0, 'complementaire': 0.0}
    for type_assurance, total in db.session.execute(text("""
        SELECT type_assurance, COALESCE(SUM(montant_rembourse), 0)
        FROM factures_assurance WHERE structure_id = :sid GROUP BY type_assurance
    """), {'sid': structure_id}).fetchall():
        rembourse[_type_facture(type_assurance)] += float(total or 0)

    en_attente = _encaissements_en_attente(structure_id)

    def bloc(prise_en_charge, cle):
        prise_en_charge = float(prise_en_charge or 0)
        return {
            'prise_en_charge': round(prise_en_charge),
            'rembourse': round(rembourse[cle]),
            'en_attente': round(en_attente[cle]),
            'reste': round(max(prise_en_charge - rembourse[cle], 0)),
        }

    m1, m2 = float(pec.m1 or 0), float(pec.m2 or 0)
    return {
        'principale': bloc(pec.p1, 'principale'),
        'complementaire': bloc(pec.p2, 'complementaire'),
        'mois': {
            'libelle': f"{MOIS_FR[aujourd_hui.month - 1]} {aujourd_hui.year}",
            'principale': round(m1),
            'complementaire': round(m2),
            'total': round(m1 + m2),
        },
        # compatibilité (anciens écrans) : cumul des prises en charge
        'total_prise_en_charge': round(float(pec.p1 or 0)),
        'total_prise_en_charge2': round(float(pec.p2 or 0)),
    }
