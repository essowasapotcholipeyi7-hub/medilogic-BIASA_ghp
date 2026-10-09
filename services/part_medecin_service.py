# -*- coding: utf-8 -*-
"""Part Médecin : rétrocession au réalisateur d'un acte (consultation,
infiltration, imagerie...) — même principe que le circuit ristourne aux
prescripteurs externes (services/laboratoire_service.py), mais pour un
médecin INTERNE (Medecin) et avec un taux configuré PAR ACTE
(TauxPartMedecin) plutôt qu'un taux unique par prescripteur.

Différence assumée avec la ristourne : chaque PrestationMedecin fige son
propre taux/montant à la VENTE (pas à la clôture), puisque deux lignes
d'une même clôture peuvent avoir des taux différents selon l'acte.

⭐ 2026-10-08 (patron) :
  - un acte peut être affecté à UN OU PLUSIEURS médecins
    (AffectationPartMedecin), chacun avec éventuellement son propre taux :
    « plusieurs spécialités en même temps, plusieurs médecins réalisent
    l'échographie pelvienne, et chacun a sa part » ; à la vente, le
    sélecteur « Réalisé par » ne propose que ces médecins (pré-rempli s'il
    n'y en a qu'un) ;
  - RSPS (retenue à la source sur prestations de services, 5 % par
    défaut, ParametragePartMedecin) calculée sur la part brute à la
    clôture : net à payer au médecin, RSPS à reverser à l'OTR (versement
    groupé par mois, voir VersementRsps) ;
  - « point » des prestations d'un médecin (récapitulatif par acte +
    détail daté) — point_prestations().
"""
from collections import OrderedDict
from datetime import date, datetime

from models import (db, TauxPartMedecin, PrestationMedecin, PeriodePartMedecin, Medecin,
                    AffectationPartMedecin, ParametragePartMedecin, VersementRsps)

TAUX_RSPS_DEFAUT = 5.0


def charger_taux_part_medecin(structure_id):
    """{nom_acte: taux} pour les actes actifs de cette structure — chargé
    une fois par actes_vente() pour poser data-taux-medecin sur chaque
    <option>, comme prix_nuit (tarif nuit Valeo)."""
    lignes = TauxPartMedecin.query.filter_by(structure_id=structure_id, actif=True).all()
    return {l.nom_acte: float(l.taux_medecin or 0) for l in lignes}


def charger_toujours_demander_medecin(structure_id):
    """{nom_acte: bool} — actes dont le sélecteur "Réalisé par" doit
    TOUJOURS être demandé ligne par ligne (ex: infiltration), même quand
    un médecin du jour est défini. Voir data-medecin-obligatoire dans
    actes_vente.html."""
    lignes = TauxPartMedecin.query.filter_by(structure_id=structure_id, actif=True).all()
    return {l.nom_acte: bool(l.toujours_demander_medecin) for l in lignes}


def charger_affectations(structure_id):
    """{nom_acte: [{'medecin_id': id, 'taux': taux propre ou None}]} — les
    médecins auxquels chaque acte est affecté (vide = tous les médecins
    restent proposés, comme avant)."""
    out = {}
    for a in AffectationPartMedecin.query.filter_by(structure_id=structure_id).all():
        out.setdefault(a.nom_acte, []).append({
            'medecin_id': a.medecin_id,
            'taux': float(a.taux_medecin) if a.taux_medecin is not None else None,
        })
    return out


def charger_medecins_affectes_csv(structure_id):
    """{nom_acte: '3,7'} pour data-medecins-affectes sur les <option> du
    catalogue (actes_vente.html)."""
    return {nom: ','.join(str(x['medecin_id']) for x in lst) for nom, lst in charger_affectations(structure_id).items()}


def taux_pour(structure_id, nom_acte, medecin_id, taux_par_acte=None, affectations=None):
    """Taux applicable à (acte, médecin) : taux propre de l'affectation s'il
    existe, sinon taux de l'acte, sinon None."""
    if taux_par_acte is None:
        taux_par_acte = charger_taux_part_medecin(structure_id)
    if affectations is None:
        affectations = charger_affectations(structure_id)
    for a in affectations.get(nom_acte, []):
        if str(a['medecin_id']) == str(medecin_id) and a['taux']:
            return float(a['taux'])
    taux = taux_par_acte.get(nom_acte)
    return float(taux) if taux else None


def parametres_rsps(structure_id):
    """(taux_rsps, actif) — 5 % par défaut, modifiable par structure."""
    p = ParametragePartMedecin.query.filter_by(structure_id=structure_id).first()
    if not p:
        return TAUX_RSPS_DEFAUT, True
    taux = float(p.taux_rsps) if p.taux_rsps is not None else TAUX_RSPS_DEFAUT
    return taux, bool(p.rsps_active) if p.rsps_active is not None else True


def calculer_rsps(montant_brut, taux_rsps, actif=True):
    """(montant_rsps, montant_net) arrondis au franc."""
    brut = float(montant_brut or 0)
    if not actif or not taux_rsps:
        return 0.0, round(brut, 2)
    rsps = round(brut * float(taux_rsps) / 100.0)
    return float(rsps), round(brut - rsps, 2)


def creer_lignes_part_medecin(structure_id, articles, vente_id, user_name):
    """Parcourt les articles d'une vente tout juste créée et crée une
    PrestationMedecin pour chaque ligne qui porte un medecin_id ET dont
    l'acte a un taux configuré (TauxPartMedecin, ou taux propre de
    l'affectation acte/médecin) — ignore silencieusement tout le reste
    (vente sans médecin attribué, ou acte non concerné).
    Ne fait RIEN si la vente ne contient aucun article concerné."""
    if not articles:
        return []

    taux_par_acte = charger_taux_part_medecin(structure_id)
    affectations = charger_affectations(structure_id)
    lignes = []
    for a in articles:
        medecin_id = a.get('medecin_id')
        if not medecin_id:
            continue
        nom = a.get('nom')
        taux = taux_pour(structure_id, nom, medecin_id, taux_par_acte, affectations)
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
    clôture. ⭐ Calcule aussi la RSPS (taux de la structure, 5 % par
    défaut) et le net à payer au médecin."""
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
    taux_rsps, rsps_active = parametres_rsps(structure_id)
    montant_rsps, montant_net = calculer_rsps(montant_total, taux_rsps, rsps_active)

    periode = PeriodePartMedecin(
        structure_id=structure_id, medecin_id=medecin_id,
        date_debut=date_debut, date_fin=date_fin,
        base_calcul=base_calcul, montant_total=montant_total, nb_actes=len(lignes),
        taux_rsps=taux_rsps if rsps_active else 0, montant_rsps=montant_rsps, montant_net=montant_net,
        statut='calculee', calculee_par=user_name,
    )
    db.session.add(periode)
    db.session.flush()  # obtenir periode.id avant de l'assigner aux lignes

    for p in lignes:
        p.periode_part_medecin_id = periode.id

    db.session.commit()
    return periode


def montant_net_periode(periode):
    """Net à payer au médecin (clôtures anciennes sans RSPS : montant total)."""
    if periode.montant_net is not None:
        return float(periode.montant_net)
    return float(periode.montant_total or 0)


def point_prestations(structure_id, medecin_id=None, date_debut=None, date_fin=None, periode=None):
    """« Point » des prestations d'un médecin : récapitulatif par acte
    (libellé, nombre, PU, montant, taux, part) + détail daté de chaque
    prestation + totaux (brut, RSPS, net). Soit pour une clôture
    (periode), soit pour les prestations non clôturées d'un médecin sur
    [date_debut, date_fin] (tout si dates absentes)."""
    if periode is not None:
        medecin_id = periode.medecin_id
        lignes = PrestationMedecin.query.filter_by(periode_part_medecin_id=periode.id) \
            .order_by(PrestationMedecin.created_at.asc()).all()
        taux_rsps = float(periode.taux_rsps or 0)
        montant_rsps, montant_net = float(periode.montant_rsps or 0), montant_net_periode(periode)
        date_debut, date_fin = periode.date_debut, periode.date_fin
    else:
        lignes = prestations_en_attente(structure_id, medecin_id)
        if date_debut:
            lignes = [p for p in lignes if p.created_at.date() >= date_debut]
        if date_fin:
            lignes = [p for p in lignes if p.created_at.date() <= date_fin]
        taux_rsps, actif = parametres_rsps(structure_id)
        if not actif:
            taux_rsps = 0
        montant_rsps = montant_net = None  # calculés plus bas sur le brut

    recap = OrderedDict()
    for p in lignes:
        prix = float(p.prix or 0)
        cle = (p.nom_acte, prix, float(p.taux_medecin_applique or 0))
        r = recap.setdefault(cle, {'libelle': p.nom_acte, 'pu': prix, 'taux': float(p.taux_medecin_applique or 0),
                                   'nombre': 0, 'montant': 0.0, 'part': 0.0})
        q = int(p.quantite or 1)
        r['nombre'] += q
        r['montant'] += prix * q
        r['part'] += float(p.montant_part_medecin or 0)

    details = [{
        'date': p.created_at, 'libelle': p.nom_acte, 'pu': float(p.prix or 0), 'quantite': int(p.quantite or 1),
        'montant': float(p.prix or 0) * int(p.quantite or 1), 'taux': float(p.taux_medecin_applique or 0),
        'part': float(p.montant_part_medecin or 0), 'vente_id': p.vente_id,
    } for p in lignes]

    base = sum(d['montant'] for d in details)
    brut = round(sum(d['part'] for d in details), 2)
    if montant_rsps is None:
        montant_rsps, montant_net = calculer_rsps(brut, taux_rsps, bool(taux_rsps))

    medecin = Medecin.query.get(medecin_id) if medecin_id else None
    return {
        'medecin': medecin, 'medecin_nom': medecin.get_nom_complet() if medecin else '—',
        'date_debut': date_debut, 'date_fin': date_fin, 'periode': periode,
        'recap': list(recap.values()), 'details': details, 'nb_actes': sum(d['quantite'] for d in details),
        'base': base, 'brut': brut, 'taux_rsps': taux_rsps, 'rsps': montant_rsps, 'net': montant_net,
    }


def rsps_a_verser(structure_id):
    """Clôtures PAYÉES dont la RSPS n'a pas encore été reversée à l'OTR,
    groupées par mois de paiement : [{'mois': 'YYYY-MM', 'libelle',
    'montant', 'nb', 'periode_ids'}]."""
    periodes = PeriodePartMedecin.query.filter(
        PeriodePartMedecin.structure_id == structure_id, PeriodePartMedecin.statut == 'payee',
        PeriodePartMedecin.montant_rsps > 0, PeriodePartMedecin.rsps_versement_id.is_(None),
    ).order_by(PeriodePartMedecin.date_paiement.asc()).all()
    mois_fr = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
    groupes = OrderedDict()
    for p in periodes:
        d = p.date_paiement or (p.payee_le.date() if p.payee_le else date.today())
        cle = d.strftime('%Y-%m')
        g = groupes.setdefault(cle, {'mois': cle, 'libelle': f"{mois_fr[d.month - 1]} {d.year}", 'montant': 0.0, 'nb': 0,
                                     'periode_ids': [], 'medecins': []})
        g['montant'] += float(p.montant_rsps or 0)
        g['nb'] += 1
        g['periode_ids'].append(p.id)
        med = Medecin.query.get(p.medecin_id)
        g['medecins'].append({'periode_id': p.id, 'medecin': med.get_nom_complet() if med else '—',
                              'brut': float(p.montant_total or 0), 'rsps': float(p.montant_rsps or 0),
                              'date_paiement': d.strftime('%d/%m/%Y')})
    return list(groupes.values())


def enregistrer_versement_rsps(structure_id, periode_ids, libelle, montant, depense_id, date_versement,
                               mode_paiement, reference_paiement, user_name):
    """Marque les clôtures comme reversées et trace le versement."""
    v = VersementRsps(structure_id=structure_id, libelle=libelle, montant=montant, nb_periodes=len(periode_ids),
                      depense_id=depense_id, date_versement=date_versement, mode_paiement=mode_paiement,
                      reference_paiement=reference_paiement, created_by=user_name)
    db.session.add(v)
    db.session.flush()
    PeriodePartMedecin.query.filter(PeriodePartMedecin.id.in_(periode_ids),
                                    PeriodePartMedecin.structure_id == structure_id) \
        .update({'rsps_versement_id': v.id}, synchronize_session=False)
    db.session.commit()
    return v
