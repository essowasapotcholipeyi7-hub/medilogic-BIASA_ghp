# -*- coding: utf-8 -*-
"""Part Médecin : rétrocession au réalisateur d'un acte (consultation,
infiltration, imagerie...) — même principe que le circuit ristourne aux
prescripteurs externes (services/laboratoire_service.py), mais pour un
médecin INTERNE (Medecin) et avec un taux configuré PAR ACTE
(TauxPartMedecin) plutôt qu'un taux unique par prescripteur.

Différence assumée avec la ristourne : chaque PrestationMedecin fige son
propre taux/montant à la VENTE (pas à la clôture), puisque deux lignes
d'une même clôture peuvent avoir des taux différents selon l'acte."""
from models import db, TauxPartMedecin, PrestationMedecin, PeriodePartMedecin, Medecin


def charger_taux_part_medecin(structure_id):
    """{nom_acte: taux} pour les actes actifs de cette structure — chargé
    une fois par actes_vente() pour poser data-taux-medecin sur chaque
    <option>, comme prix_nuit (tarif nuit Valeo)."""
    lignes = TauxPartMedecin.query.filter_by(structure_id=structure_id, actif=True).all()
    return {l.nom_acte: float(l.taux_medecin or 0) for l in lignes}


def creer_lignes_part_medecin(structure_id, articles, vente_id, user_name):
    """Parcourt les articles d'une vente tout juste créée et crée une
    PrestationMedecin pour chaque ligne qui porte un medecin_id ET dont
    l'acte a un taux configuré (TauxPartMedecin) — ignore silencieusement
    tout le reste (vente sans médecin attribué, ou acte non concerné).
    Ne fait RIEN si la vente ne contient aucun article concerné."""
    if not articles:
        return []

    taux_par_acte = charger_taux_part_medecin(structure_id)
    lignes = []
    for a in articles:
        medecin_id = a.get('medecin_id')
        if not medecin_id:
            continue
        nom = a.get('nom')
        taux = taux_par_acte.get(nom)
        if not taux:
            continue

        prix = a.get('prix')
        if prix is None:
            prix = a.get('prix_unitaire') or a.get('prix_reel') or 0
        prix = float(prix or 0)
        quantite = int(a.get('quantite') or 1)
        montant = round(prix * quantite * taux / 100, 2)

        ligne = PrestationMedecin(
            structure_id=structure_id,
            medecin_id=int(medecin_id),
            medecin_nom=a.get('medecin_nom'),
            vente_id=vente_id,
            nom_acte=nom,
            prix=prix,
            quantite=quantite,
            taux_medecin_applique=taux,
            montant_part_medecin=montant,
        )
        db.session.add(ligne)
        lignes.append(ligne)

    if lignes:
        db.session.commit()
    return lignes


def prestations_en_attente(structure_id, medecin_id):
    """PrestationMedecin pas encore incluses dans une clôture, pour ce
    médecin — c'est ce total qui s'affiche sur /part-medecin avant de
    clôturer."""
    return PrestationMedecin.query.filter_by(
        structure_id=structure_id, medecin_id=medecin_id, periode_part_medecin_id=None,
    ).order_by(PrestationMedecin.created_at.asc()).all()


def calculer_periode_part_medecin(structure_id, medecin_id, date_debut, date_fin, user_name):
    """Clôture une période pour CE médecin : somme les PrestationMedecin
    déjà figées (chacune avec son propre taux) sur [date_debut, date_fin],
    crée la PeriodePartMedecin (statut 'calculee') et marque ces lignes
    comme incluses pour qu'elles ne comptent plus dans une prochaine
    clôture."""
    medecin = Medecin.query.filter_by(id=medecin_id, structure_id=structure_id).first()
    if not medecin:
        raise ValueError('Médecin introuvable')

    lignes = [
        p for p in prestations_en_attente(structure_id, medecin_id)
        if date_debut <= p.created_at.date() <= date_fin
    ]
    if not lignes:
        raise ValueError('Aucune prestation en attente pour ce médecin sur cette période')

    base_calcul = sum(float(p.prix or 0) * int(p.quantite or 1) for p in lignes)
    montant_total = round(sum(float(p.montant_part_medecin or 0) for p in lignes), 2)

    periode = PeriodePartMedecin(
        structure_id=structure_id, medecin_id=medecin_id,
        date_debut=date_debut, date_fin=date_fin,
        base_calcul=base_calcul, montant_total=montant_total, nb_actes=len(lignes),
        statut='calculee', calculee_par=user_name,
    )
    db.session.add(periode)
    db.session.flush()  # obtenir periode.id avant de l'assigner aux lignes

    for p in lignes:
        p.periode_part_medecin_id = periode.id

    db.session.commit()
    return periode
