# services/comptabilite_service.py
# ============================================================
# MOTEUR DE GÉNÉRATION AUTOMATIQUE DES ÉCRITURES COMPTABLES
# ============================================================
# Remplace la logique morte de scripts/generer_ecritures*.py par un
# générateur SYNCHRONE, PAR TRANSACTION (une écriture par vente / paiement /
# dépense — traçabilité fine, "journal de chaque acte").
#
# Règle : toute écriture générée par ce module est automatiquement VALIDÉE
# (statut='valide'), car elle reflète une opération déjà entièrement
# déterminée par le système (vente, encaissement, dépense...). Seules les
# écritures saisies manuellement par un comptable (routes/comptabilite.py,
# POST /compta/api/ecritures) suivent le circuit de validation humaine
# (brouillon -> en_attente -> validee), qui reste inchangé.
#
# Toute fonction publique de ce module est "safe by design" pour l'appelant :
# elle ne lève jamais d'exception vers la route métier (vente, paiement...).
# En cas d'erreur, elle journalise et retourne None — la vente/le paiement
# doit toujours réussir même si la comptabilisation échoue ; l'anomalie est
# alors visible dans le tableau de bord comptabilité pour reprise manuelle.

from datetime import datetime, date, timedelta
from models import (
    db, CompteComptable, EcritureComptable, LigneEcriture,
    Vente, Facture, PaiementFacture, FactureAssurance,
    AnnulationVente, Recette, Depense, AnomalieComptable,
    Fournisseur, AchatFournisseur, ReglementFournisseur, Paie
)
from utils.plan_comptable_syscohada import (
    PLAN_COMPTABLE_PAR_NUMERO, COMPTE_CLIENTS_PATIENTS, COMPTE_ATTENTE,
    COMPTE_FOURNISSEURS, compte_assurance,
    COMPTES_RETRAITE_PAR_ORGANISME, COMPTES_AMU_PAR_ORGANISME,
    COMPTE_FORMATION_PRO_CHARGE, COMPTE_FORMATION_PRO_A_REVERSER,
    COMPTE_IRPP_A_REVERSER, COMPTE_PERSONNEL_AVANCES, COMPTE_PERSONNEL_A_PAYER,
)
from utils.categorisation import categoriser_acte

# ============================================================
# RÉSOLUTION / CRÉATION DES COMPTES (avec cache mémoire)
# ============================================================

# ⭐ FIX (bug distinct de l'ObjectDeletedError déjà corrigé, propre aux
# serveurs longue durée) : ce cache stockait auparavant l'INSTANCE ORM
# CompteComptable elle-même, au niveau du module — donc partagée entre
# TOUTES les requêtes Flask, alors que chaque requête a sa propre session
# SQLAlchemy (détruite à la fin de la requête). Un compte mis en cache lors
# de la requête N devenait une instance détachée/expirée dès la requête N+1,
# et sa réutilisation pouvait planter (observé : une vente sur 3 échouait
# silencieusement — vente_id renvoyé par l'API mais jamais persistée en
# base — dans un serveur qui tourne longtemps ; invisible dans des scripts
# de test qui ne font qu'une requête par processus). On ne met désormais en
# cache que l'ID (entier immuable, sans état de session, donc sans risque
# à conserver entre requêtes).
_compte_id_cache = {}


def _to_float(v):
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _get_compte_id(structure_id, numero, nom_repli=None, type_repli='charge'):
    """Résout l'ID d'un CompteComptable par numéro pour une structure, en le
    créant à la volée (à partir du plan SYSCOHADA de référence, ou d'un
    repli) s'il n'existe pas encore — robustesse si le seed n'a pas encore
    tourné pour cette structure."""
    cle = (structure_id, numero)
    if cle in _compte_id_cache:
        return _compte_id_cache[cle]

    compte = CompteComptable.query.filter_by(structure_id=structure_id, numero=numero).first()
    if compte and not compte.actif:
        compte.actif = True
    if not compte:
        definition = PLAN_COMPTABLE_PAR_NUMERO.get(numero)
        compte = CompteComptable(
            structure_id=structure_id,
            numero=numero,
            nom=definition['nom'] if definition else (nom_repli or numero),
            type=definition['type'] if definition else type_repli,
            classe=definition['classe'] if definition else numero[0]
        )
        db.session.add(compte)
        db.session.flush()  # pour obtenir compte.id sans committer

    _compte_id_cache[cle] = compte.id
    return compte.id


def invalider_cache_comptes():
    _compte_id_cache.clear()


# ============================================================
# ANOMALIES (générations d'écritures échouées — visibles au tableau de bord)
# ============================================================

def _log_anomalie(structure_id, source_type, source_id, message):
    """Journalise un échec de génération automatique dans une transaction
    SÉPARÉE — ne doit jamais elle-même faire échouer l'appelant."""
    try:
        db.session.rollback()  # au cas où une transaction précédente serait en échec
        db.session.add(AnomalieComptable(
            structure_id=structure_id, source_type=source_type, source_id=source_id,
            message=str(message)[:2000],
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Impossible de journaliser l'anomalie: {e}")


# ============================================================
# NOYAU COMMUN : CRÉATION D'UNE ÉCRITURE
# ============================================================

def creer_ecriture(structure_id, date_ecriture, libelle, lignes, journal_code,
                    piece_justificative=None, auto=True, source_type=None,
                    source_id=None, commentaire=None, user_nom='SYSTEME'):
    """
    Crée une écriture comptable équilibrée.

    lignes : liste de dicts {numero_compte, libelle, debit=0, credit=0}
    auto=True  -> écriture générée automatiquement, validée immédiatement.
    auto=False -> comportement du circuit manuel existant (brouillon).

    Retourne l'EcritureComptable créée, ou None si l'équilibre débit/crédit
    n'est pas respecté (aucune écriture déséquilibrée n'est jamais persistée).
    """
    lignes_valides = [l for l in lignes if _to_float(l.get('debit')) > 0.005 or _to_float(l.get('credit')) > 0.005]
    if not lignes_valides:
        return None

    total_debit = sum(_to_float(l.get('debit')) for l in lignes_valides)
    total_credit = sum(_to_float(l.get('credit')) for l in lignes_valides)

    if abs(total_debit - total_credit) > 1:  # tolérance d'arrondi (1 FCFA)
        message = (f"Écriture déséquilibrée rejetée (débit={total_debit}, "
                   f"crédit={total_credit}) — {libelle}")
        print(f"⚠️ [comptabilite_service] {message}")
        if auto:
            _log_anomalie(structure_id, source_type, source_id, message)
        return None

    if not isinstance(date_ecriture, date):
        date_ecriture = datetime.utcnow().date()

    ecriture = EcritureComptable(
        structure_id=structure_id,
        date_ecriture=date_ecriture,
        libelle=libelle,
        piece_justificative=piece_justificative,
        journal_code=journal_code,
        source_type=source_type,
        source_id=source_id,
        commentaire=commentaire,
        created_by_nom=user_nom,
    )

    if auto:
        ecriture.statut = 'valide'
        ecriture.generee_auto = True
        ecriture.validated_by_nom = 'Validation automatique'
        ecriture.date_validation = datetime.utcnow().date()
    else:
        ecriture.statut = 'brouillon'

    db.session.add(ecriture)
    db.session.flush()

    for l in lignes_valides:
        compte_id = _get_compte_id(structure_id, l['numero_compte'])
        db.session.add(LigneEcriture(
            ecriture_id=ecriture.id,
            compte_id=compte_id,
            debit=round(_to_float(l.get('debit')), 2),
            credit=round(_to_float(l.get('credit')), 2),
            libelle=l.get('libelle') or libelle
        ))

    db.session.commit()
    return ecriture


def _nom_assurance(vente, principale=True):
    """Résout le nom/code de l'assurance réellement utilisée sur une vente.

    BUG CORRIGÉ : les routes de vente (actes, pharmacie, conversion de
    proforma) ne renseignent JAMAIS la colonne simple `ventes.assurance` —
    seul le JSON `ventes.assurances` (`{'principale': {'nom': ...}, ...}`)
    contient le vrai code (ex: 'amu_cnss', 'gta'...). S'appuyer uniquement
    sur `vente.assurance` faisait donc toujours retomber sur le compte
    générique "Autres assurances", quelle que soit l'assurance réelle.
    """
    # 1) Colonne simple, si jamais renseignée (compat future / autres flux)
    champ_simple = vente.assurance if principale else vente.assurance2_nom
    if champ_simple:
        return champ_simple

    # 2) JSON `assurances` : {'principale': {'nom': ...}, 'complementaire': {...}}
    data = vente.assurances
    if isinstance(data, str):
        import json
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            data = None
    if isinstance(data, dict):
        bloc = data.get('principale' if principale else 'complementaire') or {}
        if isinstance(bloc, dict) and bloc.get('nom'):
            return bloc['nom']

    return None


def _compte_tresorerie(mode_paiement):
    """'especes' -> Caisse (571). Tout le reste (carte, mobile money,
    chèque, virement...) -> Banque (521)."""
    if (mode_paiement or 'especes').strip().lower() == 'especes':
        return '571'
    return '521'


def _contre_passer(ecriture_origine, libelle, source_type, source_id, user_nom='SYSTEME'):
    """Crée une écriture miroir (débit <-> crédit inversés) qui annule une
    écriture d'origine — utilisé pour les annulations de vente."""
    lignes = [{
        'numero_compte': l.compte.numero,
        'libelle': libelle,
        'debit': _to_float(l.credit),
        'credit': _to_float(l.debit),
    } for l in ecriture_origine.lignes]

    return creer_ecriture(
        structure_id=ecriture_origine.structure_id,
        date_ecriture=datetime.utcnow().date(),
        libelle=libelle,
        lignes=lignes,
        journal_code=ecriture_origine.journal_code or 'OD',
        piece_justificative=f"ANNUL-{ecriture_origine.piece_justificative or ecriture_origine.id}",
        auto=True,
        source_type=source_type,
        source_id=source_id,
        commentaire=f"Contre-passation de l'écriture #{ecriture_origine.id}",
        user_nom=user_nom,
    )


# ============================================================
# GÉNÉRATEURS PAR ÉVÉNEMENT MÉTIER
# ============================================================

def generer_ecriture_vente(vente, user_nom='SYSTEME'):
    """Génère la ou les écriture(s) d'une vente (actes médicaux, pharmacie ou
    lunetterie). Doit être appelée juste après l'insertion de la vente et
    de sa recette associée.

    ⭐ Non-mélange des journaux (SYSCOHADA) : une vente génère TOUJOURS son
    écriture de reconnaissance au journal VEN (Débit 4111 Clients pour la
    part patient — encaissée ou non — + assurance(s) à recevoir ; Crédit
    ventes par catégorie), puis, SEULEMENT si le patient a payé quelque
    chose sur le moment, une seconde écriture séparée au journal CAI/BQ
    (Débit trésorerie / Crédit 4111) qui éteint immédiatement cette part
    de la créance. Les deux écritures restent liées par le même patient/
    numéro de vente mais ne se mélangent jamais dans le même journal.

    Retourne l'écriture VEN (celle historiquement attendue par les
    appelants existants — `vente.ecriture_id`) ; l'écriture d'encaissement,
    si générée, est stockée séparément sur `vente.ecriture_encaissement_id`.
    """
    try:
        structure_id = vente.structure_id
        montant_donne = _to_float(vente.montant_donne)
        rendu = _to_float(vente.rendu)
        montant_effectif = round(montant_donne - rendu, 2)
        prise_en_charge = _to_float(vente.prise_en_charge)
        prise_en_charge2 = _to_float(vente.prise_en_charge2)
        reste_a_payer = _to_float(vente.reste_a_payer)

        lignes = []
        total_debit = 0.0

        if montant_effectif > 0:
            lignes.append({'numero_compte': COMPTE_CLIENTS_PATIENTS,
                            'libelle': f"Créance client — {vente.patient_nom} (réglée immédiatement)",
                            'debit': montant_effectif})
            total_debit += montant_effectif

        if prise_en_charge > 0:
            nom_assurance = _nom_assurance(vente, principale=True)
            compte_num = compte_assurance(nom_assurance)
            lignes.append({'numero_compte': compte_num,
                            'libelle': f"Tiers-payant à recevoir ({nom_assurance or 'assurance'})",
                            'debit': prise_en_charge})
            total_debit += prise_en_charge

        if prise_en_charge2 > 0:
            nom_assurance2 = _nom_assurance(vente, principale=False)
            compte_num2 = compte_assurance(nom_assurance2)
            # ⭐ La société souscriptrice (contrat groupe employeur) est
            # tracée dans le libellé de la ligne — même compte tiers-payant
            # par assurance (pas d'explosion du plan comptable par société),
            # mais visible dans le grand livre/journal et sur le bordereau.
            societe = getattr(vente, 'societe_assurance2', None)
            libelle_assurance2 = f"Tiers-payant à recevoir ({nom_assurance2 or 'assurance 2'}"
            libelle_assurance2 += f" — {societe})" if societe else ")"
            lignes.append({'numero_compte': compte_num2,
                            'libelle': libelle_assurance2,
                            'debit': prise_en_charge2})
            total_debit += prise_en_charge2

        if reste_a_payer > 0.5:
            lignes.append({'numero_compte': COMPTE_CLIENTS_PATIENTS,
                            'libelle': f"Créance client — {vente.patient_nom} (reste à payer)",
                            'debit': reste_a_payer})
            total_debit += reste_a_payer

        if total_debit <= 0.5:
            return None  # rien à comptabiliser (ex: vente à 0)

        # --- Répartition du crédit "Ventes" par catégorie ---
        # ⭐ On combine `actes` (catégorisés finement via categoriser_acte) et
        # `produits` (pharmacie/lunetterie) plutôt que de se fier uniquement à
        # `vente.type` — une vente issue d'une proforma peut être "mixte"
        # (actes + produits dans la même vente).
        totaux_par_compte = {}

        for item in (vente.actes or []):
            if not isinstance(item, dict):
                continue
            montant_item = _to_float(item.get('total') or item.get('prix') or item.get('montant'))
            info = categoriser_acte(item.get('nom', ''))
            totaux_par_compte[info['compte']] = totaux_par_compte.get(info['compte'], 0) + montant_item

        produits_items = vente.produits or []
        if produits_items:
            compte_produits = '7012' if vente.type in ('lunettes', 'lunetterie', 'optique') else '7011'
            for item in produits_items:
                if not isinstance(item, dict):
                    continue
                montant_item = _to_float(item.get('total') or item.get('prix_reel')
                                          or item.get('prix_vente') or item.get('prix') or item.get('montant'))
                totaux_par_compte[compte_produits] = totaux_par_compte.get(compte_produits, 0) + montant_item

        if not totaux_par_compte:
            # Repli si la vente n'a aucun détail d'articles exploitable
            if vente.type in ('pharma', 'pharmacie'):
                totaux_par_compte['7011'] = total_debit
            elif vente.type in ('lunettes', 'lunetterie', 'optique'):
                totaux_par_compte['7012'] = total_debit
            else:
                totaux_par_compte['7068'] = total_debit

        somme_items = sum(totaux_par_compte.values())
        if somme_items <= 0.5:
            totaux_par_compte = {'7068': total_debit}
        elif abs(somme_items - total_debit) > 1:
            # Ajustement d'arrondi sur "Autres prestations" pour garantir
            # l'équilibre de l'écriture sans bloquer la vente.
            ecart = round(total_debit - somme_items, 2)
            totaux_par_compte['7068'] = totaux_par_compte.get('7068', 0) + ecart

        for compte_num, montant in totaux_par_compte.items():
            if montant <= 0:
                continue
            lignes.append({'numero_compte': compte_num, 'libelle': f"Ventes — {vente.patient_nom}",
                            'credit': round(montant, 2)})

        libelle = f"Vente {vente.type} #{vente.id} — {vente.patient_nom}"
        ecriture = creer_ecriture(
            structure_id=structure_id,
            date_ecriture=(vente.date_vente.date() if vente.date_vente else datetime.utcnow().date()),
            libelle=libelle,
            lignes=lignes,
            journal_code='VEN',
            piece_justificative=f"VTE-{vente.id}",
            auto=True,
            source_type='vente',
            source_id=vente.id,
            user_nom=user_nom,
        )

        # ⭐ Seconde écriture (CAI/BQ), séparée : le SEUL mouvement de
        # trésorerie réel, uniquement si le patient a effectivement payé
        # quelque chose sur le moment. Éteint la part de créance 4111 tout
        # juste reconnue ci-dessus dans l'écriture VEN.
        ecriture_encaissement = None
        if ecriture and montant_effectif > 0:
            lignes_encaissement = [
                {'numero_compte': _compte_tresorerie(vente.mode_paiement),
                 'libelle': f"Encaissement vente — {vente.patient_nom}", 'debit': montant_effectif},
                {'numero_compte': COMPTE_CLIENTS_PATIENTS,
                 'libelle': f"Encaissement vente — {vente.patient_nom}", 'credit': montant_effectif},
            ]
            journal_encaissement = 'CAI' if _compte_tresorerie(vente.mode_paiement) == '571' else 'BQ'
            ecriture_encaissement = creer_ecriture(
                structure_id=structure_id,
                date_ecriture=(vente.date_vente.date() if vente.date_vente else datetime.utcnow().date()),
                libelle=f"Encaissement vente #{vente.id} — {vente.patient_nom}",
                lignes=lignes_encaissement,
                journal_code=journal_encaissement,
                piece_justificative=f"VTE-{vente.id}",
                auto=True,
                source_type='encaissement_vente',
                source_id=vente.id,
                user_nom=user_nom,
            )

        if ecriture:
            # ⭐ FIX : `creer_ecriture()` vient de committer (expire_on_commit
            # expire `vente` avec les autres objets du session). Assigner un
            # attribut sur une instance expirée déclenche un SELECT de
            # rafraîchissement qui peut lever `ObjectDeletedError` selon
            # l'état de la transaction (observé en production sur une vraie
            # vente). Un UPDATE direct par id évite complètement de recharger
            # l'instance — plus robuste.
            maj = {'ecriture_generee': True, 'ecriture_id': ecriture.id}
            if ecriture_encaissement:
                maj['ecriture_encaissement_id'] = ecriture_encaissement.id
            db.session.query(Vente).filter(Vente.id == vente.id).update(
                maj, synchronize_session=False,
            )
            db.session.commit()

        return ecriture

    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_vente(vente#{getattr(vente, 'id', '?')}): {e}")
        import traceback
        traceback.print_exc()
        _log_anomalie(getattr(vente, 'structure_id', None), 'vente', getattr(vente, 'id', None),
                      f"Échec génération écriture de vente: {e}")
        return None


def generer_ecriture_annulation_vente(vente, annulation, user_nom='SYSTEME'):
    """Contre-passe la ou les écriture(s) d'origine d'une vente annulée —
    la reconnaissance (VEN) ET, si elle existe, l'encaissement (CAI/BQ)
    séparé (voir generer_ecriture_vente). Retourne la contre-passation VEN
    (celle historiquement attendue par l'appelant) ; celle de l'encaissement,
    si générée, n'est pas retournée mais reste tracée par sa pièce (VTE-<id>)."""
    try:
        if not vente.ecriture_id:
            return None

        if vente.ecriture_encaissement_id:
            ecriture_encaissement_origine = EcritureComptable.query.get(vente.ecriture_encaissement_id)
            if ecriture_encaissement_origine:
                _contre_passer(
                    ecriture_encaissement_origine,
                    libelle=f"Annulation vente #{vente.id} — {vente.patient_nom} (encaissement)",
                    source_type='annulation_vente',
                    source_id=annulation.id if annulation else vente.id,
                    user_nom=user_nom,
                )

        ecriture_origine = EcritureComptable.query.get(vente.ecriture_id)
        if not ecriture_origine:
            return None
        return _contre_passer(
            ecriture_origine,
            libelle=f"Annulation vente #{vente.id} — {vente.patient_nom}",
            source_type='annulation_vente',
            source_id=annulation.id if annulation else vente.id,
            user_nom=user_nom,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_annulation_vente: {e}")
        _log_anomalie(getattr(vente, 'structure_id', None), 'annulation_vente',
                      getattr(vente, 'id', None), f"Échec génération écriture d'annulation: {e}")
        return None


def generer_ecriture_paiement_facture(paiement, facture, user_nom='SYSTEME'):
    """Un client vient régler (totalement ou partiellement) une créance
    déjà reconnue lors de la vente (compte 4111). Débit trésorerie, crédit
    client — c'est ce qui fait redescendre la créance vers zéro."""
    try:
        montant = _to_float(paiement.montant)
        if montant <= 0:
            return None

        lignes = [
            {'numero_compte': _compte_tresorerie(paiement.mode_paiement),
             'libelle': f"Règlement facture {facture.numero_facture}", 'debit': montant},
            {'numero_compte': COMPTE_CLIENTS_PATIENTS,
             'libelle': f"Solde créance — {facture.patient_nom}", 'credit': montant},
        ]

        return creer_ecriture(
            structure_id=facture.structure_id,
            date_ecriture=(paiement.date_paiement.date() if paiement.date_paiement else datetime.utcnow().date()),
            libelle=f"Règlement facture {facture.numero_facture} — {facture.patient_nom}",
            lignes=lignes,
            journal_code='CAI' if _compte_tresorerie(paiement.mode_paiement) == '571' else 'BQ',
            piece_justificative=f"PAI-{paiement.id}",
            auto=True,
            source_type='paiement_facture',
            source_id=paiement.id,
            user_nom=user_nom,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_paiement_facture: {e}")
        _log_anomalie(getattr(facture, 'structure_id', None), 'paiement_facture',
                      getattr(paiement, 'id', None), f"Échec génération écriture de règlement: {e}")
        return None


def generer_ecriture_remboursement_assurance(montant, assurance_nom, structure_id,
                                              reference, source_id, user_nom='SYSTEME',
                                              numero_reference_versement=None,
                                              date_versement=None):
    """Un assureur règle (par virement bancaire) le tiers-payant déjà
    reconnu en créance lors des ventes prises en charge. Débit banque,
    crédit compte assurance.

    ⭐ Traçabilité : `numero_reference_versement` et `date_versement` sont les
    pièces justificatives (référence du virement/versement bancaire + date)
    exigées côté UI à l'encaissement — elles sont reportées ici dans le
    libellé de la ligne banque (visible directement dans le journal/grand
    livre) et dans le commentaire de l'écriture (visible au détail).
    """
    try:
        montant = _to_float(montant)
        if montant <= 0:
            return None

        compte_num = compte_assurance(assurance_nom)
        ref_txt = f" — réf. {numero_reference_versement}" if numero_reference_versement else ""
        date_txt = f" du {date_versement}" if date_versement else ""
        lignes = [
            {'numero_compte': '521', 'libelle': f"Virement {assurance_nom}{ref_txt}{date_txt}", 'debit': montant},
            {'numero_compte': compte_num, 'libelle': f"Solde tiers-payant {assurance_nom}{ref_txt}", 'credit': montant},
        ]

        commentaire = None
        if numero_reference_versement or date_versement:
            commentaire = (f"Pièce justificative du versement — "
                            f"N° de référence : {numero_reference_versement or 'non renseigné'} — "
                            f"Date de versement : {date_versement or 'non renseignée'}")

        return creer_ecriture(
            structure_id=structure_id,
            date_ecriture=datetime.utcnow().date(),
            libelle=f"Remboursement assurance {assurance_nom} — {reference}{ref_txt}",
            lignes=lignes,
            journal_code='BQ',
            piece_justificative=f"ASS-{source_id}",
            auto=True,
            source_type='paiement_assurance',
            source_id=source_id,
            user_nom=user_nom,
            commentaire=commentaire,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_remboursement_assurance: {e}")
        _log_anomalie(structure_id, 'paiement_assurance', source_id,
                      f"Échec génération écriture de remboursement assurance: {e}")
        return None


# Mots-clés de "motif" de dépense (saisis librement dans l'UI) -> compte de charge
_COMPTE_PAR_MOTIF_DEPENSE = {
    'salaire': '661', 'salaires': '661',
    'loyer': '613', 'location': '613',
    'eau': '614', 'electricite': '614', 'électricité': '614',
    'entretien': '615', 'reparation': '615', 'réparation': '615',
    'assurance': '616',
    'transport': '624',
    'carburant': '624',
    'communication': '626', 'telephone': '626', 'téléphone': '626', 'internet': '626',
    'banque': '627', 'frais bancaire': '627',
    'fourniture': '628', 'bureau': '628',
    'impot': '631', 'impôt': '631', 'taxe': '631',
    'medicament': '601', 'médicament': '601', 'pharmacie': '601',
    'materiel': '604', 'matériel': '604', 'equipement': '604', 'équipement': '604',
}


def _compte_charge_pour_motif(motif):
    if not motif:
        return '628'
    cle = str(motif).strip().lower()
    for mot, compte in _COMPTE_PAR_MOTIF_DEPENSE.items():
        if mot in cle:
            return compte
    return '628'  # charge diverse par défaut


def generer_ecriture_annulation_facture(facture, montant_annule, user_nom='SYSTEME'):
    """Annulation d'une facture (créance) encore partiellement ou totalement
    impayée : la partie non recouvrée est passée en perte (691 Rabais et
    remises accordés), ce qui éteint la créance client sans mouvement de
    trésorerie — la partie déjà réglée avant l'annulation n'est pas touchée
    (elle a déjà sa propre écriture de règlement)."""
    try:
        montant_annule = _to_float(montant_annule)
        if montant_annule <= 0:
            return None

        lignes = [
            {'numero_compte': '691', 'libelle': f"Créance abandonnée — facture {facture.numero_facture}",
             'debit': montant_annule},
            {'numero_compte': COMPTE_CLIENTS_PATIENTS,
             'libelle': f"Annulation créance — {facture.patient_nom}", 'credit': montant_annule},
        ]

        return creer_ecriture(
            structure_id=facture.structure_id,
            date_ecriture=datetime.utcnow().date(),
            libelle=f"Annulation facture {facture.numero_facture} — {facture.patient_nom}",
            lignes=lignes,
            journal_code='OD',
            piece_justificative=f"ANNUL-FAC-{facture.id}",
            auto=True,
            source_type='annulation_facture',
            source_id=facture.id,
            user_nom=user_nom,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_annulation_facture: {e}")
        _log_anomalie(getattr(facture, 'structure_id', None), 'annulation_facture',
                      getattr(facture, 'id', None), f"Échec génération écriture d'annulation facture: {e}")
        return None


def generer_ecriture_depense(depense, user_nom='SYSTEME'):
    """Dépense diverse payée cash sur le champ, sans fournisseur identifié ni
    dette formelle (pour un achat À CRÉDIT chez un fournisseur enregistré,
    voir AchatFournisseur/generer_ecriture_achat_fournisseur — journal ACH —
    puis son règlement séparé en CAI/BQ). Ici, il n'y a pas de créance à
    reconnaître d'abord : c'est un simple décaissement en espèces, donc une
    seule écriture, directement au journal de caisse (CAI) — Débit charge
    (déduite du motif), Crédit trésorerie. Les dépenses n'ont pas de mode de
    paiement dédié dans le modèle actuel (toujours caisse, compte 571)."""
    try:
        montant = _to_float(depense.montant)
        if montant <= 0:
            return None

        compte_charge = _compte_charge_pour_motif(depense.motif or depense.motif_personnalise)
        lignes = [
            {'numero_compte': compte_charge, 'libelle': depense.motif or 'Dépense', 'debit': montant},
            {'numero_compte': '571', 'libelle': depense.motif or 'Dépense', 'credit': montant},
        ]

        return creer_ecriture(
            structure_id=depense.structure_id,
            date_ecriture=(depense.date_depense.date() if depense.date_depense else datetime.utcnow().date()),
            libelle=f"Dépense — {depense.motif or depense.motif_personnalise or 'Divers'}",
            lignes=lignes,
            journal_code='CAI',
            piece_justificative=f"DEP-{depense.id}",
            auto=True,
            source_type='depense',
            source_id=depense.id,
            user_nom=user_nom,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_depense: {e}")
        _log_anomalie(getattr(depense, 'structure_id', None), 'depense',
                      getattr(depense, 'id', None), f"Échec génération écriture de dépense: {e}")
        return None


def generer_ecriture_achat_fournisseur(achat, user_nom='SYSTEME'):
    """Achat À CRÉDIT chez un fournisseur : la charge est reconnue tout de
    suite (comptabilité d'engagement), mais la caisse n'est PAS impactée —
    on ne paie pas encore. Débit charge (déduite du motif) / Crédit 401
    Fournisseurs. La sortie de caisse n'arrivera qu'au règlement (voir
    generer_ecriture_reglement_fournisseur)."""
    try:
        montant = _to_float(achat.montant_total)
        if montant <= 0:
            return None

        compte_charge = _compte_charge_pour_motif(achat.motif or achat.motif_personnalise)
        nom_fournisseur = achat.fournisseur.nom if achat.fournisseur else 'Fournisseur'
        lignes = [
            {'numero_compte': compte_charge,
             'libelle': f"{achat.motif or 'Achat'} — {nom_fournisseur}", 'debit': montant},
            {'numero_compte': COMPTE_FOURNISSEURS,
             'libelle': f"Dette fournisseur — {nom_fournisseur}", 'credit': montant},
        ]

        return creer_ecriture(
            structure_id=achat.structure_id,
            date_ecriture=(achat.date_achat.date() if achat.date_achat else datetime.utcnow().date()),
            libelle=f"Achat à crédit — {nom_fournisseur} ({achat.motif or 'Divers'})",
            lignes=lignes,
            journal_code='ACH',
            piece_justificative=f"ACH-FRS-{achat.id}",
            auto=True,
            source_type='achat_fournisseur',
            source_id=achat.id,
            user_nom=user_nom,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_achat_fournisseur: {e}")
        _log_anomalie(getattr(achat, 'structure_id', None), 'achat_fournisseur',
                      getattr(achat, 'id', None), f"Échec génération écriture d'achat fournisseur: {e}")
        return None


def generer_ecriture_reglement_fournisseur(reglement, achat, user_nom='SYSTEME'):
    """Règlement (partiel ou total) d'une dette fournisseur déjà reconnue à
    l'achat (compte 401). Débit 401 (extinction dette) / Crédit trésorerie —
    c'est ICI, et seulement ici, que la caisse est réellement impactée."""
    try:
        montant = _to_float(reglement.montant)
        if montant <= 0:
            return None

        nom_fournisseur = achat.fournisseur.nom if achat.fournisseur else 'Fournisseur'
        lignes = [
            {'numero_compte': COMPTE_FOURNISSEURS,
             'libelle': f"Règlement — {nom_fournisseur}", 'debit': montant},
            {'numero_compte': _compte_tresorerie(reglement.mode_paiement),
             'libelle': f"Règlement — {nom_fournisseur}", 'credit': montant},
        ]

        return creer_ecriture(
            structure_id=achat.structure_id,
            date_ecriture=(reglement.date_reglement.date() if reglement.date_reglement else datetime.utcnow().date()),
            libelle=f"Règlement fournisseur — {nom_fournisseur} (achat #{achat.id})",
            lignes=lignes,
            # ⭐ Non-mélange SYSCOHADA : CAI/BQ portent TOUT mouvement de
            # trésorerie réel (encaissement ET décaissement en espèces ou en
            # banque) — l'achat lui-même (charge + dette) reste dans ACH,
            # séparément (voir generer_ecriture_achat_fournisseur). Un
            # règlement espèces va donc en CAI, un règlement banque en BQ.
            journal_code='CAI' if _compte_tresorerie(reglement.mode_paiement) == '571' else 'BQ',
            piece_justificative=f"REG-FRS-{reglement.id}",
            auto=True,
            source_type='reglement_fournisseur',
            source_id=reglement.id,
            user_nom=user_nom,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_reglement_fournisseur: {e}")
        _log_anomalie(getattr(achat, 'structure_id', None), 'reglement_fournisseur',
                      getattr(reglement, 'id', None), f"Échec génération écriture de règlement fournisseur: {e}")
        return None


def generer_ecriture_recette_diverse(recette, user_nom='SYSTEME'):
    """Pour une recette saisie manuellement (POST /api/finances/recettes),
    non issue d'une vente (qui est déjà comptabilisée par
    generer_ecriture_vente). Débit trésorerie, crédit produits divers."""
    try:
        montant = _to_float(recette.montant)
        if montant <= 0:
            return None

        lignes = [
            {'numero_compte': '571', 'libelle': recette.source or 'Recette', 'debit': montant},
            {'numero_compte': '758', 'libelle': recette.source or 'Recette', 'credit': montant},
        ]

        return creer_ecriture(
            structure_id=recette.structure_id,
            date_ecriture=(recette.date_recette.date() if recette.date_recette else datetime.utcnow().date()),
            libelle=f"Recette diverse — {recette.source or recette.description or ''}",
            lignes=lignes,
            journal_code='CAI',
            piece_justificative=f"REC-{recette.id}",
            auto=True,
            source_type='recette',
            source_id=recette.id,
            user_nom=user_nom,
        )
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_recette_diverse: {e}")
        _log_anomalie(getattr(recette, 'structure_id', None), 'recette',
                      getattr(recette, 'id', None), f"Échec génération écriture de recette: {e}")
        return None


def generer_ecriture_paie(paie, employe, user_nom='SYSTEME'):
    """Écriture(s) de paie. ⭐ Non-mélange SYSCOHADA : le journal SAL reçoit
    TOUJOURS la reconnaissance complète (charges de personnel + toutes les
    dettes qui en découlent, y compris le net à payer — compte 4231 — tant
    qu'il n'est pas décaissé) ; le journal CAI/BQ reçoit SÉPARÉMENT, si le
    net a effectivement été versé, le seul décaissement réel (Débit 4231 /
    Crédit trésorerie). Les deux écritures restent liées par la même pièce
    (PAIE-<id>) mais jamais mélangées dans un même journal.

    Retourne l'écriture SAL (celle historiquement attendue par l'appelant,
    `paie.ecriture_id`) ; l'écriture de décaissement, si générée, est
    stockée séparément sur `paie.ecriture_paiement_id`.

    Profils : CNSS (privé) ou CRT (public) pour la retraite ; AMU-CNSS ou
    AMU-INAM pour l'assurance maladie — même schéma comptable, seuls les
    libellés diffèrent (organisme_retraite/organisme_amu, capturés sur la
    paie au moment du calcul)."""
    try:
        salaire_brut = _to_float(paie.salaire_brut)
        retraite_sal = _to_float(paie.retraite_salarial)
        retraite_pat = _to_float(paie.retraite_patronal)
        amu_sal = _to_float(paie.amu_salarial)
        amu_pat = _to_float(paie.amu_patronal)
        formation_pro = _to_float(getattr(paie, 'formation_pro', 0))
        irpp = _to_float(paie.irpp)
        net = _to_float(paie.net_a_payer)
        organisme_retraite = paie.organisme_retraite or 'CNSS'
        organisme_amu = paie.organisme_amu or 'AMU-CNSS'

        # Retenues diverses (prêts/acomptes/autres) : réduisent le net versé
        # sans être un décaissement en soi — elles diminuent une créance sur
        # le personnel déjà avancée (compte 421), donc créditées ici.
        autres = (_to_float(getattr(paie, 'prets_deduction', 0))
                  + _to_float(getattr(paie, 'acomptes_deduction', 0))
                  + _to_float(getattr(paie, 'autres_retenues_total', 0)))

        if salaire_brut <= 0:
            return None

        # ⭐ Comptes spécifiques à l'organisme réellement appliqué sur cette
        # paie (CNSS ou CRT, AMU-CNSS ou AMU-INAM) — jamais un compte
        # générique partagé entre secteurs. Repli sur CNSS/AMU-CNSS si
        # l'organisme n'est pas reconnu (ancien bulletin, valeur inattendue).
        comptes_retraite = COMPTES_RETRAITE_PAR_ORGANISME.get(organisme_retraite, COMPTES_RETRAITE_PAR_ORGANISME['CNSS'])
        comptes_amu = COMPTES_AMU_PAR_ORGANISME.get(organisme_amu, COMPTES_AMU_PAR_ORGANISME['AMU-CNSS'])

        libelle = f"Paie {paie.get_periode_label()} — {employe.nom} {employe.prenom}"
        lignes = [
            {'numero_compte': '661', 'libelle': 'Salaires et appointements', 'debit': salaire_brut},
        ]
        if retraite_pat > 0:
            lignes.append({'numero_compte': comptes_retraite['charge'], 'libelle': f'Charges sociales {organisme_retraite} patronal', 'debit': retraite_pat})
        if amu_pat > 0:
            lignes.append({'numero_compte': comptes_amu['charge'], 'libelle': f'Charges sociales {organisme_amu} patronal', 'debit': amu_pat})
        if formation_pro > 0:
            lignes.append({'numero_compte': COMPTE_FORMATION_PRO_CHARGE, 'libelle': 'Taxe formation professionnelle', 'debit': formation_pro})

        if net > 0:
            lignes.append({'numero_compte': COMPTE_PERSONNEL_A_PAYER,
                            'libelle': 'Personnel — net à payer', 'credit': net})
        if retraite_sal > 0:
            lignes.append({'numero_compte': comptes_retraite['salarial'], 'libelle': f'{organisme_retraite} salarial à reverser', 'credit': retraite_sal})
        if retraite_pat > 0:
            lignes.append({'numero_compte': comptes_retraite['patronal'], 'libelle': f'{organisme_retraite} patronal à reverser', 'credit': retraite_pat})
        if amu_sal > 0:
            lignes.append({'numero_compte': comptes_amu['salarial'], 'libelle': f'{organisme_amu} salarial à reverser', 'credit': amu_sal})
        if amu_pat > 0:
            lignes.append({'numero_compte': comptes_amu['patronal'], 'libelle': f'{organisme_amu} patronal à reverser', 'credit': amu_pat})
        if formation_pro > 0:
            lignes.append({'numero_compte': COMPTE_FORMATION_PRO_A_REVERSER, 'libelle': 'Formation professionnelle à reverser', 'credit': formation_pro})
        if irpp > 0:
            lignes.append({'numero_compte': COMPTE_IRPP_A_REVERSER, 'libelle': 'IRPP à reverser', 'credit': irpp})
        if autres > 0:
            lignes.append({'numero_compte': COMPTE_PERSONNEL_AVANCES, 'libelle': 'Avances/acomptes/prêts récupérés sur salaire', 'credit': autres})

        ecriture = creer_ecriture(
            structure_id=paie.structure_id,
            date_ecriture=(paie.date_paiement or datetime.utcnow().date()),
            libelle=libelle,
            lignes=lignes,
            journal_code='SAL',
            piece_justificative=f"PAIE-{paie.id}",
            auto=True,
            source_type='paie',
            source_id=paie.id,
            user_nom=user_nom,
        )

        # ⭐ Décaissement réel du net, en CAI/BQ, séparément — uniquement si
        # un net était dû (voir plus haut, crédité en 4231 dans l'écriture
        # SAL ci-dessus).
        if ecriture and net > 0:
            lignes_paiement = [
                {'numero_compte': COMPTE_PERSONNEL_A_PAYER,
                 'libelle': f"Paiement salaire — {employe.nom} {employe.prenom}", 'debit': net},
                {'numero_compte': _compte_tresorerie(paie.mode_paiement),
                 'libelle': f"Paiement salaire — {employe.nom} {employe.prenom}", 'credit': net},
            ]
            journal_paiement = 'CAI' if _compte_tresorerie(paie.mode_paiement) == '571' else 'BQ'
            ecriture_paiement = creer_ecriture(
                structure_id=paie.structure_id,
                date_ecriture=(paie.date_paiement or datetime.utcnow().date()),
                libelle=f"Paiement salaire {paie.get_periode_label()} — {employe.nom} {employe.prenom}",
                lignes=lignes_paiement,
                journal_code=journal_paiement,
                piece_justificative=f"PAIE-{paie.id}",
                auto=True,
                source_type='paiement_paie',
                source_id=paie.id,
                user_nom=user_nom,
            )
            if ecriture_paiement:
                db.session.query(Paie).filter(Paie.id == paie.id).update(
                    {'ecriture_paiement_id': ecriture_paiement.id}, synchronize_session=False,
                )
                db.session.commit()

        return ecriture
    except Exception as e:
        db.session.rollback()
        print(f"❌ [comptabilite_service] Erreur generer_ecriture_paie: {e}")
        _log_anomalie(getattr(paie, 'structure_id', None), 'paie',
                      getattr(paie, 'id', None), f"Échec génération écriture de paie: {e}")
        return None


# ============================================================
# PROVISIONS POUR CRÉANCES DOUTEUSES
# ============================================================

def generer_ecriture_provision(structure_id, montant_provisionne, patient_nom, provision_id, user_nom='SYSTEME'):
    """Constate une dépréciation estimée sur une créance qui traîne :
    Débit 6591 (charge) / Crédit 491 (dépréciation, contra-actif). Ne
    touche PAS le compte 4111 — la créance reste due en totalité, c'est
    juste une estimation comptable de la perte probable."""
    lignes = [
        {'numero_compte': '6591', 'libelle': f"Provision créance douteuse — {patient_nom}", 'debit': montant_provisionne},
        {'numero_compte': '491', 'libelle': f"Dépréciation créance — {patient_nom}", 'credit': montant_provisionne},
    ]
    return creer_ecriture(
        structure_id=structure_id, date_ecriture=datetime.utcnow().date(),
        libelle=f"Provision pour créance douteuse — {patient_nom}", lignes=lignes,
        journal_code='OD', piece_justificative=f"PROV-{provision_id}", auto=True,
        source_type='provision_creance', source_id=provision_id, user_nom=user_nom,
    )


def generer_ecriture_reprise_provision(structure_id, montant_provisionne, patient_nom, provision_id, user_nom='SYSTEME'):
    """Annule une provision devenue sans objet (le patient a finalement
    payé, ou la créance est recouvrée autrement) : Débit 491 / Crédit 7591."""
    lignes = [
        {'numero_compte': '491', 'libelle': f"Reprise provision — {patient_nom}", 'debit': montant_provisionne},
        {'numero_compte': '7591', 'libelle': f"Reprise provision créance douteuse — {patient_nom}", 'credit': montant_provisionne},
    ]
    return creer_ecriture(
        structure_id=structure_id, date_ecriture=datetime.utcnow().date(),
        libelle=f"Reprise de provision — {patient_nom}", lignes=lignes,
        journal_code='OD', piece_justificative=f"REPR-{provision_id}", auto=True,
        source_type='reprise_provision', source_id=provision_id, user_nom=user_nom,
    )


def generer_ecriture_perte_creance(structure_id, montant_creance, montant_provisionne, patient_nom,
                                    provision_id, user_nom='SYSTEME'):
    """Passe une créance définitivement en perte (client insolvable,
    créance abandonnée) : éteint le 4111 pour le montant total ; la partie
    déjà couverte par une provision sort de 491, le reste est une charge
    exceptionnelle sur 651."""
    montant_creance = _to_float(montant_creance)
    montant_provisionne = min(_to_float(montant_provisionne), montant_creance)
    reste_non_couvert = round(montant_creance - montant_provisionne, 2)

    lignes = [{'numero_compte': COMPTE_CLIENTS_PATIENTS, 'libelle': f"Créance passée en perte — {patient_nom}",
               'credit': montant_creance}]
    if montant_provisionne > 0:
        lignes.append({'numero_compte': '491', 'libelle': f"Consommation provision — {patient_nom}", 'debit': montant_provisionne})
    if reste_non_couvert > 0:
        lignes.append({'numero_compte': '651', 'libelle': f"Perte sur créance irrécouvrable — {patient_nom}", 'debit': reste_non_couvert})

    return creer_ecriture(
        structure_id=structure_id, date_ecriture=datetime.utcnow().date(),
        libelle=f"Créance irrécouvrable — {patient_nom}", lignes=lignes,
        journal_code='OD', piece_justificative=f"PERTE-{provision_id}", auto=True,
        source_type='perte_creance', source_id=provision_id, user_nom=user_nom,
    )


# ============================================================
# IMMOBILISATIONS & AMORTISSEMENTS
# ============================================================

def generer_ecriture_acquisition_immobilisation(immo, user_nom='SYSTEME'):
    """Achat d'une immobilisation : Débit compte d'immobilisation (2xxx) /
    Crédit trésorerie (paiement comptant — le cas le plus courant pour une
    petite structure ; pas de gestion de crédit fournisseur immobilisation
    pour l'instant)."""
    montant = _to_float(immo.valeur_acquisition)
    if montant <= 0:
        return None
    lignes = [
        {'numero_compte': immo.compte_immo_numero, 'libelle': f"Acquisition — {immo.designation}", 'debit': montant},
        {'numero_compte': _compte_tresorerie(immo.mode_paiement), 'libelle': f"Achat — {immo.designation}", 'credit': montant},
    ]
    return creer_ecriture(
        structure_id=immo.structure_id, date_ecriture=immo.date_acquisition,
        libelle=f"Acquisition immobilisation — {immo.designation}", lignes=lignes,
        journal_code='ACH', piece_justificative=f"IMMO-{immo.id}", auto=True,
        source_type='immobilisation_acquisition', source_id=immo.id, user_nom=user_nom,
    )


def generer_ecriture_dotation_amortissement(immo, montant, annee, user_nom='SYSTEME'):
    """Dotation annuelle aux amortissements : Débit 681 / Crédit compte
    d'amortissement (28xx) de l'immobilisation concernée."""
    montant = round(_to_float(montant), 2)
    if montant <= 0:
        return None
    lignes = [
        {'numero_compte': '681', 'libelle': f"Dotation {annee} — {immo.designation}", 'debit': montant},
        {'numero_compte': immo.compte_amort_numero, 'libelle': f"Amortissement {annee} — {immo.designation}", 'credit': montant},
    ]
    return creer_ecriture(
        structure_id=immo.structure_id, date_ecriture=date(annee, 12, 31),
        libelle=f"Dotation aux amortissements {annee} — {immo.designation}", lignes=lignes,
        journal_code='OD', piece_justificative=f"DOTA-{immo.id}-{annee}", auto=True,
        source_type='dotation_amortissement', source_id=immo.id, user_nom=user_nom,
    )


# ============================================================
# LES DEUX CAISSES (tableau de bord comptabilité)
# ============================================================
# ⭐ Le TAFIRE officiel OHADA (méthode CAFG + variation FR/BFR) vit
# maintenant dans routes/comptabilite.py (get_tafire), à côté de
# get_bilan()/get_compte_resultat() dont il dépend directement.

def get_soldes_caisses(structure_id, date_debut=None, date_fin=None):
    """Retourne les deux indicateurs demandés :
    - tresorerie : solde réel disponible (classe 5 : Caisse 571 + Banque 521),
      toutes périodes confondues (c'est un solde, pas un flux).
    - chiffre_affaires : total des ventes (classe 7, comptes 70x) sur la
      période donnée (flux, pas un solde).
    """
    comptes_tresorerie = CompteComptable.query.filter(
        CompteComptable.structure_id == structure_id,
        CompteComptable.numero.in_(['571', '521'])
    ).all()

    tresorerie = 0.0
    detail_tresorerie = []
    for c in comptes_tresorerie:
        solde = _to_float(c.get_solde())
        tresorerie += solde
        detail_tresorerie.append({'numero': c.numero, 'nom': c.nom, 'solde': solde})

    comptes_ca = CompteComptable.query.filter(
        CompteComptable.structure_id == structure_id,
        CompteComptable.numero.like('7%')
    ).all()

    chiffre_affaires = 0.0
    detail_ca = []
    for c in comptes_ca:
        solde = _to_float(c.get_solde(date_debut, date_fin))  # crédit - débit inversé pour un compte de produit
        montant = -solde  # get_solde() = débit - crédit ; un produit est normalement créditeur
        if montant > 0:
            chiffre_affaires += montant
            detail_ca.append({'numero': c.numero, 'nom': c.nom, 'montant': montant})

    return {
        'caisse_tresorerie': round(tresorerie, 2),
        'detail_tresorerie': detail_tresorerie,
        'caisse_chiffre_affaires': round(chiffre_affaires, 2),
        'detail_chiffre_affaires': detail_ca,
    }
