# -*- coding: utf-8 -*-
"""Régularisation complète d'une vente annulée (patron, 2026-10-14 : « quand on
annule une vente, est-ce que le solde disponible se réduit ? est-ce que la part
d'assurance liée à cette vente est aussi annulée ? … dans la comptabilité aussi
il doit y avoir une diminution »).

_executer_annulation_vente (app.py) retire déjà l'encaissement de la caisse et
contre-passe les écritures de la vente (créance assurance, chiffre d'affaires,
trésorerie). Ce module traite le reste :

1. la créance patient (vente à crédit) : annulée ; ce qui avait déjà été réglé
   dessus est retiré de la caisse (remboursé au patient) et ses écritures de
   règlement sont contre-passées ;
2. les factures assurance du mois qui contiennent la vente : la ligne est
   retirée et le total diminué (si la facture est clôturée, rien n'est modifié
   et un avertissement est rendu : à régulariser avec l'assureur) ;
3. la facture AMU mensuelle du mois : avertissement (brouillon à régénérer,
   ou facture déjà déposée / clôturée à régulariser).

La part médecin et les recettes par service ne sont pas supprimées : elles sont
exclues à la lecture (voir part_medecin_service / service_acte_service).

Renvoie la liste des avertissements à montrer à l'administrateur.
"""
from datetime import datetime

from models import (db, Vente, Facture, PaiementFacture, FactureAssurance, Recette,
                    FactureAmuMensuelle, EcritureComptable)


def _fcfa(x):
    return f"{int(round(float(x or 0))):,}".replace(',', ' ') + ' F'


def _annuler_creances(vente, motif, user_name, avertissements):
    from services.comptabilite_service import annuler_ecriture
    for f in Facture.query.filter(Facture.structure_id == vente.structure_id,
                                  Facture.vente_id == vente.id,
                                  db.or_(Facture.statut.is_(None), Facture.statut != 'annulee')).all():
        deja_paye = 0.0
        for p in PaiementFacture.query.filter_by(facture_id=f.id).all():
            deja_paye += float(p.montant or 0)
            for e in EcritureComptable.query.filter_by(structure_id=vente.structure_id,
                                                       source_type='paiement_facture', source_id=p.id).all():
                annuler_ecriture(e, f"Annulation vente #{vente.id} — règlement créance {f.numero_facture}",
                                 'annulation_vente', vente.id, user_name)
        # ce qui avait été encaissé sur la créance sort de la caisse (rendu au patient)
        Recette.query.filter(Recette.structure_id == vente.structure_id, Recette.source_type == 'facture',
                             Recette.source_id == f.id,
                             db.or_(Recette.est_annulation.is_(None), Recette.est_annulation.is_(False))) \
            .update({'est_annulation': True,
                     'description': db.func.concat(Recette.description, f' [ANNULEE - vente #{vente.id} annulée]')},
                    synchronize_session=False)
        f.statut = 'annulee'
        f.reste_a_payer = 0
        f.notes = ((f.notes or '') + f"\nAnnulée le {datetime.now():%d/%m/%Y} avec la vente #{vente.id} : {motif}").strip()
        if deja_paye > 0.5:
            avertissements.append(f"Créance {f.numero_facture} : {_fcfa(deja_paye)} déjà réglés par le patient, "
                                  f"retirés de la caisse (à lui rembourser).")


def _statut_facture_assurance(total, rembourse):
    if total <= 0.5 and rembourse <= 0.5:
        return 'annulee'
    if rembourse >= total - 0.5:
        return 'payee'
    return 'partielle' if rembourse > 0.5 else 'en_attente'


def _retirer_des_factures_assurance(vente, avertissements):
    if not vente.date_vente:
        return
    mois = vente.date_vente.strftime('%Y-%m')
    for fa in FactureAssurance.query.filter_by(structure_id=vente.structure_id, mois_reference=mois).all():
        details = fa.details or []
        retirees = [d for d in details if isinstance(d, dict) and d.get('id') == vente.id]
        if not retirees:
            continue
        montant = sum(float(d.get('montant_assurance') or 0) for d in retirees)
        if fa.cloturee:
            avertissements.append(f"Facture assurance {fa.assurance} ({mois}) déjà clôturée : la vente #{vente.id} "
                                  f"({_fcfa(montant)}) y figure toujours — à régulariser avec l'assureur.")
            continue
        total = max(float(fa.montant_total or 0) - montant, 0)
        rembourse = float(fa.montant_rembourse or 0)
        fa.details = [d for d in details if not (isinstance(d, dict) and d.get('id') == vente.id)]
        fa.montant_total = round(total, 2)
        fa.statut = _statut_facture_assurance(total, rembourse)
        if rembourse > total + 0.5:
            avertissements.append(f"Facture assurance {fa.assurance} ({mois}) : l'assureur a déjà versé "
                                  f"{_fcfa(rembourse)} pour {_fcfa(total)} désormais dus — trop-perçu à régulariser.")
        if fa.date_depot:
            avertissements.append(f"Bordereau {fa.assurance} ({mois}) déjà déposé le {fa.date_depot:%d/%m/%Y} : "
                                  f"prévenir l'assureur que la vente #{vente.id} ({_fcfa(montant)}) est annulée.")


def _facture_amu_du_mois(vente, avertissements):
    if not vente.date_vente or not float(vente.prise_en_charge or 0):
        return
    for f in FactureAmuMensuelle.query.filter_by(structure_id=vente.structure_id, annee=vente.date_vente.year,
                                                 mois=vente.date_vente.month).all():
        if f.statut in ('deposee', 'cloturee'):
            avertissements.append(f"Facture AMU {f.type_amu.upper()} de {vente.date_vente:%m/%Y} déjà "
                                  f"{'clôturée' if f.statut == 'cloturee' else 'déposée'} : la vente #{vente.id} y est "
                                  f"comptée — à régulariser avec la caisse d'assurance.")
            continue
        # Brouillon : pas de recalcul automatique (ses lignes ont pu être corrigées à la main)
        avertissements.append(f"Facture AMU {f.type_amu.upper()} de {vente.date_vente:%m/%Y} (brouillon) : "
                              f"cliquer sur « Générer » pour la recalculer sans la vente #{vente.id}.")


def regulariser_annulation(vente_id, structure_id, motif, user_name):
    vente = Vente.query.filter_by(id=vente_id, structure_id=structure_id).first()
    if not vente:
        return []
    avertissements = []
    _annuler_creances(vente, motif, user_name, avertissements)
    _retirer_des_factures_assurance(vente, avertissements)
    _facture_amu_du_mois(vente, avertissements)
    db.session.commit()
    return avertissements
