# -*- coding: utf-8 -*-
"""Remboursement patient d'une vente qui ne peut plus être annulée (plus de 72 h)
— patron, 2026-10-14 : « le montant de la vente concernée devrait être
automatiquement présent, qu'on ne puisse pas le modifier vers le haut mais
possibilité vers le bas ».

Remboursable = ce que le patient a RÉELLEMENT payé pour cette vente
               (encaissement à la vente + règlements de sa créance, hors annulés)
             − remboursements déjà enregistrés pour cette vente
             − remboursements demandés et encore en attente de validation.

Le contrôle est fait à la demande (api_add_depense) ET à la validation
(_executer_ajout_depense) : l'écran ne fait que préremplir et plafonner.
"""
from models import db, Vente, Facture, Recette, Depense, ValidationDemande

MOTIF_REMBOURSEMENT = 'remboursement_patient'


def _fcfa(x):
    return f"{int(round(float(x or 0))):,}".replace(',', ' ') + ' F'


def montant_remboursable(structure_id, vente_id, exclure_demande_id=None):
    """dict {ok, erreur?, vente_id, numero, patient, date, encaisse, deja_rembourse,
    en_attente, remboursable}."""
    try:
        vente_id = int(vente_id)
    except (TypeError, ValueError):
        return {'ok': False, 'erreur': "Vente non précisée : lancez le remboursement depuis l'historique des ventes."}
    vente = Vente.query.filter_by(id=vente_id, structure_id=structure_id).first()
    if not vente:
        return {'ok': False, 'erreur': 'Vente introuvable.'}
    if vente.statut == 'annulee':
        return {'ok': False, 'erreur': 'Cette vente est déjà annulée : son encaissement a déjà été retiré de la caisse.'}

    non_annulee = db.or_(Recette.est_annulation.is_(None), Recette.est_annulation.is_(False))
    encaisse_vente = db.session.query(db.func.coalesce(db.func.sum(Recette.montant), 0)).filter(
        Recette.structure_id == structure_id, Recette.source == 'patients', non_annulee,
        Recette.source_id == vente_id,
        Recette.source_type.in_(['vente_acte', 'vente_pharma', 'vente_proforma'])).scalar()
    factures = db.session.query(Facture.id).filter(Facture.structure_id == structure_id, Facture.vente_id == vente_id)
    encaisse_creance = db.session.query(db.func.coalesce(db.func.sum(Recette.montant), 0)).filter(
        Recette.structure_id == structure_id, Recette.source == 'patients', non_annulee,
        Recette.source_type == 'facture', Recette.source_id.in_(factures)).scalar()
    encaisse = float(encaisse_vente or 0) + float(encaisse_creance or 0)

    deja = db.session.query(db.func.coalesce(db.func.sum(Depense.montant), 0)).filter(
        Depense.structure_id == structure_id, Depense.motif == MOTIF_REMBOURSEMENT,
        Depense.vente_id == vente_id).scalar()
    deja = float(deja or 0)

    en_attente = 0.0
    for d in ValidationDemande.query.filter_by(structure_id=structure_id, type_demande='depense',
                                               statut='en_attente').all():
        p = d.payload or {}
        if d.id != exclure_demande_id and p.get('motif') == MOTIF_REMBOURSEMENT and str(p.get('vente_id')) == str(vente_id):
            en_attente += float(p.get('montant') or 0)

    remboursable = max(round(encaisse - deja - en_attente), 0)
    # n° affiché au patient (colonne de la table, pas toujours mappée sur le modèle)
    numero = db.session.execute(db.text("SELECT numero_local FROM ventes WHERE id = :i"), {'i': vente_id}).scalar()
    return {
        'ok': True, 'vente_id': vente_id, 'numero': numero or vente_id,
        'patient': vente.patient_nom or '',
        'date': vente.date_vente.strftime('%d/%m/%Y') if vente.date_vente else '',
        'encaisse': round(encaisse), 'deja_rembourse': round(deja), 'en_attente': round(en_attente),
        'remboursable': remboursable,
    }


def controler_remboursement(structure_id, vente_id, montant, exclure_demande_id=None):
    """(info, None) si le montant est acceptable, sinon (info, message d'erreur)."""
    info = montant_remboursable(structure_id, vente_id, exclure_demande_id)
    if not info['ok']:
        return info, info['erreur']
    if float(montant or 0) <= 0:
        return info, 'Montant du remboursement invalide.'
    if info['remboursable'] <= 0:
        return info, (f"Rien à rembourser sur la vente n° {info['numero']} : le patient a payé {_fcfa(info['encaisse'])}, "
                      f"déjà remboursé {_fcfa(info['deja_rembourse'])}"
                      + (f", {_fcfa(info['en_attente'])} en attente de validation" if info['en_attente'] else '') + '.')
    if float(montant) > info['remboursable'] + 0.5:
        return info, (f"Le remboursement ne peut pas dépasser {_fcfa(info['remboursable'])} pour la vente n° {info['numero']} "
                      f"(payé par le patient {_fcfa(info['encaisse'])}, déjà remboursé {_fcfa(info['deja_rembourse'])}"
                      + (f", en attente {_fcfa(info['en_attente'])}" if info['en_attente'] else '') + ').')
    return info, None
