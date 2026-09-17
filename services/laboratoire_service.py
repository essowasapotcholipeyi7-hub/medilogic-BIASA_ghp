# -*- coding: utf-8 -*-
"""Circuit Laboratoire / Radiologie : classification des actes (analyse vs
examen), génération automatique des demandes à l'encaissement, et lien
vers les patients externes (ristourne prescripteur).

Le principe central (demandé explicitement) : la demande part
AUTOMATIQUEMENT dès que l'acte est réglé (même partiellement) — jamais de
ressaisie manuelle côté labo/radio. Ce module centralise cette logique
pour qu'elle soit appelée de façon identique depuis les 2 points de vente
directe (actes) et la conversion de proforma, plutôt que dupliquée.
"""
from models import db, ClassificationActe, PatientExterne, DemandeExamen


def charger_classification_actes(structure_id):
    """{nom_acte: 'analyse'|'examen'} pour cette structure — vide tant que
    rien n'a été classé (voir /classification-actes), zéro régression :
    un acte absent d'ici ne génère jamais de demande."""
    lignes = ClassificationActe.query.filter_by(structure_id=structure_id).all()
    return {l.nom_acte: l.type_prestation for l in lignes}


def statut_paiement_depuis_montants(net_a_payer, reste_a_payer):
    """'paye' | 'partiel' | 'impaye' à partir des montants déjà calculés
    par le point de vente (net_a_payer, reste_a_payer) — même lecture
    partout, pas de recalcul propre à ce module."""
    net_a_payer = float(net_a_payer or 0)
    reste_a_payer = float(reste_a_payer or 0)
    if reste_a_payer <= 0.5:
        return 'paye'
    if reste_a_payer >= net_a_payer - 0.5:
        return 'impaye'
    return 'partiel'


def creer_demandes_pour_vente(structure_id, patient_id, patient_nom, articles,
                               vente_id, statut_paiement, motif, user_name):
    """Parcourt les articles d'une vente (ou d'une conversion de proforma)
    tout juste créée et crée une DemandeExamen pour chaque article classé
    analyse/examen — orientée automatiquement vers le Laborantin ou le
    Radiologue. Si le patient a une fiche PatientExterne active couvrant
    cette filière (biologie/imagerie), la demande est rattachée à son
    prescripteur (patient_externe_id) pour la ristourne.

    Ne fait RIEN (retourne []) tant qu'aucune classification n'a été
    saisie pour la structure — comportement inchangé pour une structure
    qui n'utilise pas ce module."""
    classification = charger_classification_actes(structure_id)
    if not classification or not articles:
        return []

    fiche_externe = PatientExterne.query.filter_by(
        structure_id=structure_id, patient_id=patient_id, actif=True
    ).order_by(PatientExterne.id.desc()).first()

    demandes = []
    for a in articles:
        nom = a.get('nom')
        type_prestation = classification.get(nom)
        if not type_prestation:
            continue

        patient_externe_id = None
        if fiche_externe:
            if type_prestation == 'analyse' and fiche_externe.biologie:
                patient_externe_id = fiche_externe.id
            elif type_prestation == 'examen' and fiche_externe.imagerie:
                patient_externe_id = fiche_externe.id

        prix = a.get('prix')
        if prix is None:
            prix = a.get('prix_unitaire') or a.get('prix_reel') or 0

        demande = DemandeExamen(
            structure_id=structure_id,
            patient_id=patient_id,
            patient_nom=patient_nom,
            type_prestation=type_prestation,
            acte_nom=nom,
            quantite=int(a.get('quantite') or 1),
            prix=float(prix or 0),
            vente_id=vente_id,
            patient_externe_id=patient_externe_id,
            statut_paiement=statut_paiement,
            motif=motif if statut_paiement != 'paye' else None,
            created_by=user_name,
        )
        db.session.add(demande)
        demandes.append(demande)

    if demandes:
        db.session.commit()
    return demandes
