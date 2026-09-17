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
import secrets
import string
from models import db, ClassificationActe, PatientExterne, DemandeExamen, AccesPortailPatient, PeriodeRistourne, PrescripteurExterne


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


# ⭐ Alphabet volontairement sans caractères ambigus à l'oral/à l'écrit
# (pas de 0/O, 1/I/l) — le code est communiqué au patient de vive voix ou
# sur un ticket imprimé, doit rester lisible sans confusion.
_ALPHABET_CODE = string.ascii_uppercase.replace('O', '').replace('I', '') + \
                 string.digits.replace('0', '').replace('1', '') + '#@%'


def obtenir_ou_creer_code_acces(structure_id, patient_id, user_name):
    """Code d'accès actif de ce patient au portail résultats — le crée
    (8 caractères, mélange lettres/chiffres/symboles) s'il n'en a pas
    encore. Ne régénère JAMAIS automatiquement un code existant (un code
    déjà donné au patient doit rester valable) — voir
    regenerer_code_acces() pour un renouvellement volontaire."""
    existant = AccesPortailPatient.query.filter_by(structure_id=structure_id, patient_id=patient_id).first()
    if existant:
        return existant

    for _ in range(10):  # évite en théorie une collision, jamais vue en pratique sur 8 caractères
        code = ''.join(secrets.choice(_ALPHABET_CODE) for _ in range(8))
        if not AccesPortailPatient.query.filter_by(code_acces=code).first():
            break

    acces = AccesPortailPatient(structure_id=structure_id, patient_id=patient_id, code_acces=code, created_by=user_name)
    db.session.add(acces)
    db.session.commit()
    return acces


def regenerer_code_acces(structure_id, patient_id, user_name):
    """Invalide le code existant et en émet un nouveau — pour un patient
    qui l'a perdu ou en cas de doute sur sa confidentialité."""
    AccesPortailPatient.query.filter_by(structure_id=structure_id, patient_id=patient_id).delete()
    db.session.commit()
    return obtenir_ou_creer_code_acces(structure_id, patient_id, user_name)


def demandes_ristourne_en_attente(structure_id, prescripteur_id):
    """DemandeExamen déjà réglées, liées à ce prescripteur (via
    PatientExterne), pas encore incluses dans une clôture — c'est ce
    total qui s'affiche sur /ristournes avant de clôturer, et c'est
    exactement ce que calculer_ristourne() ci-dessous va figer."""
    fiches_ids = [f.id for f in PatientExterne.query.filter_by(structure_id=structure_id, prescripteur_id=prescripteur_id).all()]
    if not fiches_ids:
        return []
    return DemandeExamen.query.filter(
        DemandeExamen.structure_id == structure_id,
        DemandeExamen.patient_externe_id.in_(fiches_ids),
        DemandeExamen.periode_ristourne_id.is_(None),
    ).order_by(DemandeExamen.created_at.asc()).all()


def calculer_ristourne(structure_id, prescripteur_id, date_debut, date_fin, user_name):
    """Clôture une période pour CE prescripteur : fige son taux actuel,
    somme le prix des actes non encore clôturés dans [date_debut,
    date_fin], crée la PeriodeRistourne (statut 'calculee') et marque ces
    DemandeExamen comme inclus (periode_ristourne_id) pour qu'ils ne
    comptent plus dans une prochaine clôture — patron : 'à une date donnée
    on arrête, on calcule sa ristourne selon le taux appliqué et en
    fonction du prix de l'acte enregistré'."""
    prescripteur = PrescripteurExterne.query.filter_by(id=prescripteur_id, structure_id=structure_id).first()
    if not prescripteur:
        raise ValueError('Prescripteur introuvable')
    taux = float(prescripteur.taux_ristourne or 0)

    demandes = [
        d for d in demandes_ristourne_en_attente(structure_id, prescripteur_id)
        if date_debut <= d.created_at.date() <= date_fin
    ]
    if not demandes:
        raise ValueError('Aucun acte réglé pour ce prescripteur sur cette période')

    base_calcul = sum(float(d.prix or 0) * int(d.quantite or 1) for d in demandes)
    montant = round(base_calcul * taux / 100, 2)

    periode = PeriodeRistourne(
        structure_id=structure_id, prescripteur_id=prescripteur_id,
        date_debut=date_debut, date_fin=date_fin, taux_applique=taux,
        base_calcul=base_calcul, montant_ristourne=montant, nb_actes=len(demandes),
        statut='calculee', calculee_par=user_name,
    )
    db.session.add(periode)
    db.session.flush()  # obtenir periode.id avant de l'assigner aux demandes

    for d in demandes:
        d.periode_ristourne_id = periode.id

    db.session.commit()
    return periode
