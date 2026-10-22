# routes/comptabilite.py - Version complète
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime, date, timedelta
import json
import re
from functools import lru_cache
from sqlalchemy import func

from models import (
    db, CompteComptable, EcritureComptable, LigneEcriture,
    Budget, ValidationComptable, HistoriqueEcriture, ReleveBancaire,
    LigneReleve, Cloture, SequencePiece, AnomalieComptable,
    Immobilisation, DotationAmortissement, ProvisionCreance, Facture,
    Fournisseur, AchatFournisseur, ReglementFournisseur, Depense,
    ParametrageTva, DeclarationTva,
)
from services.comptabilite_service import get_soldes_caisses, creer_ecriture, COMPTE_CLIENTS_PATIENTS, exercice_cloture
from utils.plan_comptable_syscohada import (
    COMPTE_BANQUE, COMPTE_CAISSE, COMPTE_IMMO_MATERIEL_MEDICAL, COMPTE_AMORT_MATERIEL_MEDICAL,
    COMPTE_TVA_COLLECTEE, COMPTE_TVA_DEDUCTIBLE, COMPTE_TVA_DUE, COMPTE_CREDIT_TVA,
)
from utils.permissions import a_acces

compta_bp = Blueprint('comptabilite', __name__, url_prefix='/comptabilite')


# ============================================================
# ACCÈS PAR RÔLE
# ============================================================
# Aucune protection n'existait auparavant sur ce blueprint (ni connexion,
# ni rôle) — seul le lien du menu était masqué aux non-admins, ce qui
# laissait la comptabilité accessible à quiconque connaissait/devinait
# l'URL. Un seul hook pour tout le blueprint plutôt que décorer ~50 routes
# une par une (risque d'en oublier une). a_acces() (utils/permissions.py)
# est le point de vérité unique — rôle par défaut OU octroi d'habilitation
# ponctuel actif pour cet utilisateur précis.
@compta_bp.before_request
def _verifier_role_comptabilite():
    chemin_api = request.path.startswith('/comptabilite/api/')
    if 'user_id' not in session:
        if chemin_api:
            return jsonify({'error': 'Non autorisé'}), 401
        flash('Veuillez vous connecter', 'warning')
        return redirect(url_for('index'))
    if not a_acces('comptabilite'):
        if chemin_api:
            return jsonify({'error': 'Accès non autorisé pour votre rôle'}), 403
        flash("Accès non autorisé pour votre rôle.", 'danger')
        return redirect(url_for('dashboard'))
    # ⭐ Agent comptable (rôle 'sous_comptable') : saisie — les décisions restent
    # au comptable (et à l'administrateur).
    if session.get('role') == 'sous_comptable' and (request.endpoint or '').split('.')[-1] in ENDPOINTS_RESPONSABLE_COMPTA:
        message = "Réservé au comptable : votre compte d'agent comptable permet la saisie, pas cette décision."
        if chemin_api or request.method != 'GET':
            return jsonify({'success': False, 'error': message, 'message': message}), 403
        flash(message, 'warning')
        return redirect(url_for('comptabilite.index'))


# Décisions : interdites à l'agent comptable (voir utils/permissions.ROLES_COMPTA).
ENDPOINTS_RESPONSABLE_COMPTA = {
    # plan comptable, numérotation, TVA, budget
    'api_ajouter_compte', 'api_modifier_compte', 'api_supprimer_compte', 'api_init_comptes',
    'api_reset_sequence', 'api_tva_parametrage_post', 'api_sauvegarder_budget',
    # validation et clôture
    'api_valider_ecriture', 'api_cloture', 'api_cloture_exercice_generer', 'api_report_a_nouveau_generer',
    'api_corriger_arrondi',
    'api_valider_releve',
    # provisions, pertes, amortissements, règlements fournisseurs
    'api_provisionner_creance', 'api_reprendre_provision', 'api_provision_passer_en_perte', 'api_perte_directe',
    'api_generer_dotations', 'api_regler_achat_fournisseur',
    # clôture et paiement de la TVA
    'api_tva_declaration_cloturer', 'api_tva_declaration_payer', 'api_tva_declaration_annuler',
}


# ============================================================
# CACHE
# ============================================================
_compte_cache = {}
_compte_cache_time = {}
_rapport_cache = {}
_rapport_cache_time = {}
_rapport_special_cache = {}
_rapport_special_cache_time = {}


def invalidate_cache(structure_id):
    """Invalide le cache pour une structure"""
    global _compte_cache, _compte_cache_time, _rapport_cache, _rapport_cache_time
    global _rapport_special_cache, _rapport_special_cache_time
    
    keys_to_remove = []
    
    # Comptes
    for key in list(_compte_cache.keys()):
        if f"comptes_{structure_id}" in key:
            keys_to_remove.append(key)
    for key in keys_to_remove:
        if key in _compte_cache:
            del _compte_cache[key]
        if key in _compte_cache_time:
            del _compte_cache_time[key]
    
    # Rapports
    for key in list(_rapport_cache.keys()):
        if f"rapport_{structure_id}" in key:
            if key in _rapport_cache:
                del _rapport_cache[key]
            if key in _rapport_cache_time:
                del _rapport_cache_time[key]
    
    for key in list(_rapport_special_cache.keys()):
        if f"resultat_{structure_id}" in key or f"bilan_{structure_id}" in key:
            if key in _rapport_special_cache:
                del _rapport_special_cache[key]
            if key in _rapport_special_cache_time:
                del _rapport_special_cache_time[key]


# ============================================================
# FONCTION DE PARSING DES DATES
# ============================================================

def parse_date(date_str):
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    
    formats = [
        '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d',
        '%d %b %Y', '%d %B %Y', '%b %d %Y', '%B %d %Y',
        '%Y%m%d', '%d.%m.%Y', '%m/%d/%Y', '%d/%m/%y', '%d-%m-%y'
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    # Format: DD/MM/YYYY ou DD-MM-YYYY
    match = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$', date_str)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass
    
    # Format: YYYY/MM/DD ou YYYY-MM-DD
    match = re.match(r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$', date_str)
    if match:
        year, month, day = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass
    
    return None


# ============================================================
# PAGE PRINCIPALE
# ============================================================

@compta_bp.route('/')
def index():
    return render_template('comptabilite/index.html')


# ============================================================
# TABLEAU DE BORD
# ============================================================

@compta_bp.route('/api/dashboard/stats')
def api_dashboard_stats():
    """⭐ date_debut/date_fin (optionnels) scopent les CHIFFRES DE FLUX
    (nombre d'écritures, masse comptable) sur la période choisie — voir
    le tableau de bord, sélecteur de période. `en_attente` reste
    volontairement NON filtré : c'est un indicateur opérationnel ("qu'est-
    ce qui attend une action MAINTENANT"), pas une statistique
    historique — le filtrer ferait croire à tort que rien n'attend
    quand on consulte un exercice passé."""
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')

    q_ecritures = EcritureComptable.query.filter_by(structure_id=structure_id)
    if date_debut:
        q_ecritures = q_ecritures.filter(EcritureComptable.date_ecriture >= date_debut)
    if date_fin:
        q_ecritures = q_ecritures.filter(EcritureComptable.date_ecriture <= date_fin)

    total_ecritures = q_ecritures.count()
    en_attente = EcritureComptable.query.filter_by(structure_id=structure_id, statut='en_attente').count()
    validees = q_ecritures.filter(EcritureComptable.statut == 'valide').count()

    # ⭐ total_debit/total_credit/solde ne comptent que les écritures
    # VALIDÉES — comme CompteComptable.get_solde() (models.py) et toutes
    # les autres agrégations du module (generer_balance, répartition par
    # journal, créances par assureur). Avant ce correctif, une écriture
    # brouillon/en attente/refusée faussait la "masse comptable" du
    # tableau de bord sans qu'aucune autre carte ne la compte — les
    # totaux ne pouvaient jamais se recouper.
    conditions = [
        EcritureComptable.structure_id == structure_id,
        EcritureComptable.statut == 'valide',
    ]
    if date_debut:
        conditions.append(EcritureComptable.date_ecriture >= date_debut)
    if date_fin:
        conditions.append(EcritureComptable.date_ecriture <= date_fin)

    total_debit = db.session.query(db.func.sum(LigneEcriture.debit)).filter(
        *[LigneEcriture.ecriture.has(c) for c in conditions]
    ).scalar() or 0

    total_credit = db.session.query(db.func.sum(LigneEcriture.credit)).filter(
        *[LigneEcriture.ecriture.has(c) for c in conditions]
    ).scalar() or 0

    return jsonify({
        'total_ecritures': total_ecritures,
        'en_attente': en_attente,
        'validees': validees,
        'total_debit': float(total_debit),
        'total_credit': float(total_credit),
        'solde': float(total_debit - total_credit)
    })


# ============================================================
# PLAN COMPTABLE
# ============================================================

@compta_bp.route('/api/comptes')
def api_comptes():
    structure_id = session.get('structure_id')
    
    search = request.args.get('search', '')
    type_filter = request.args.get('type', '')
    
    comptes = CompteComptable.query.filter_by(
        structure_id=structure_id,
        actif=True
    ).order_by(CompteComptable.numero).all()
    
    soldes = CompteComptable.soldes([c.id for c in comptes])   # ⭐ 2026-10-18 : une requête (avant : 2 par compte)
    result = []
    for c in comptes:
        result.append({
            'id': c.id,
            'numero': c.numero,
            'nom': c.nom,
            'type': c.type,
            'classe': c.classe,
            'niveau': c.niveau,
            'parent_id': c.parent_id,
            'solde': float(soldes[c.id]) if soldes.get(c.id) else 0
        })
    
    if search:
        search_lower = search.lower()
        result = [c for c in result if search_lower in (c['numero'] + ' ' + c['nom']).lower()]
    if type_filter:
        result = [c for c in result if c['type'] == type_filter]
    
    return jsonify(result)


@compta_bp.route('/api/comptes', methods=['POST'])
def api_ajouter_compte():
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'error': 'Structure non trouvee'}), 400
        
        existing = CompteComptable.query.filter_by(
            structure_id=structure_id,
            numero=data.get('numero')
        ).first()
        
        if existing:
            return jsonify({
                'success': False, 
                'error': f'Le compte {data.get("numero")} existe deja'
            }), 400
        
        compte = CompteComptable(
            structure_id=structure_id,
            numero=data.get('numero'),
            nom=data.get('nom'),
            type=data.get('type'),
            classe=data.get('classe') or '',
            parent_id=data.get('parent_id') or None,
            niveau=data.get('niveau', 1)
        )
        
        db.session.add(compte)
        db.session.commit()
        
        invalidate_cache(structure_id)
        
        return jsonify({'success': True, 'id': compte.id})
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/comptes/<int:id>', methods=['PUT'])
def api_modifier_compte(id):
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        compte = CompteComptable.query.filter_by(id=id, structure_id=structure_id).first()
        if not compte:
            return jsonify({'error': 'Compte non trouve'}), 404
        
        compte.numero = data.get('numero')
        compte.nom = data.get('nom')
        compte.type = data.get('type')
        compte.classe = data.get('classe') or ''
        compte.parent_id = data.get('parent_id') or None
        compte.niveau = data.get('niveau', 1)
        compte.updated_at = datetime.utcnow()
        
        db.session.commit()
        invalidate_cache(structure_id)
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/comptes/<int:id>', methods=['DELETE'])
def api_supprimer_compte(id):
    try:
        structure_id = session.get('structure_id')
        
        compte = CompteComptable.query.filter_by(id=id, structure_id=structure_id).first()
        if not compte:
            return jsonify({'error': 'Compte non trouve'}), 404
        
        # Verifier si le compte a des enfants
        enfants = CompteComptable.query.filter_by(parent_id=id).count()
        if enfants > 0:
            return jsonify({'error': 'Ce compte a des sous-comptes'}), 400
        
        compte.actif = False
        db.session.commit()
        invalidate_cache(structure_id)
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ============================================================
# SEQUENCES - NUMEROS DE PIECE
# ============================================================

@compta_bp.route('/api/sequence/next/<type_piece>', methods=['GET'])
def api_get_next_sequence(type_piece):
    """Récupère le prochain numéro de pièce sans l'incrémenter"""
    try:
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'error': 'Structure non trouvee'}), 400
        
        info = SequencePiece.get_info(structure_id, type_piece)
        
        if not info:
            # Créer une séquence si elle n'existe pas
            prochain = SequencePiece.get_next_number(structure_id, type_piece)
            return jsonify({
                'success': True,
                'prochain_numero': prochain,
                'type_piece': type_piece,
                'est_nouvelle_sequence': True
            })
        
        return jsonify({
            'success': True,
            'prochain_numero': info['prochain_numero'],
            'type_piece': info['type_piece'],
            'prefixe': info['prefixe'],
            'annee': info['annee'],
            'numero_actuel': info['numero_actuel']
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/sequence/reset/<type_piece>', methods=['POST'])
def api_reset_sequence(type_piece):
    """Réinitialise une séquence (admin seulement)"""
    try:
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'error': 'Structure non trouvee'}), 400
        
        annee = request.json.get('annee', datetime.now().year)
        
        result = SequencePiece.reset_sequence(structure_id, type_piece, annee)
        
        return jsonify({
            'success': result,
            'message': 'Sequence reinitialisee' if result else 'Sequence non trouvee'
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# ECRITURES COMPTABLES
# ============================================================

@compta_bp.route('/api/ecritures')
def api_ecritures():
    structure_id = session.get('structure_id')
    
    search = request.args.get('search', '')
    statut_filter = request.args.get('statut', '')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    query = EcritureComptable.query.filter_by(structure_id=structure_id)
    
    if search:
        query = query.filter(
            db.or_(
                EcritureComptable.libelle.ilike(f'%{search}%'),
                EcritureComptable.piece_justificative.ilike(f'%{search}%'),
                EcritureComptable.created_by_nom.ilike(f'%{search}%')
            )
        )
    if statut_filter:
        query = query.filter_by(statut=statut_filter)
    
    if date_debut:
        date_debut_obj = parse_date(date_debut)
        if date_debut_obj:
            query = query.filter(EcritureComptable.date_ecriture >= date_debut_obj)
    
    if date_fin:
        date_fin_obj = parse_date(date_fin)
        if date_fin_obj:
            query = query.filter(EcritureComptable.date_ecriture <= date_fin_obj)
    
    total = query.count()
    
    # ⭐ 2026-10-18 : lignes et comptes de la page chargés ensemble (avant : requêtes par écriture et par ligne)
    from sqlalchemy.orm import selectinload, joinedload
    ecritures = query.options(selectinload(EcritureComptable.lignes).joinedload(LigneEcriture.compte)).order_by(
        EcritureComptable.date_ecriture.desc(),
        EcritureComptable.id.desc()
    ).offset((page-1)*per_page).limit(per_page).all()
    
    result = []
    for e in ecritures:
        lignes = []
        for l in e.lignes[:5]:
            lignes.append({
                'compte_numero': l.compte.numero if l.compte else '',
                'compte_nom': l.compte.nom if l.compte else '',
                'debit': float(l.debit),
                'credit': float(l.credit),
                'libelle': l.libelle
            })
        
        result.append({
            'id': e.id,
            'date_ecriture': e.date_ecriture.strftime('%Y-%m-%d') if e.date_ecriture else '',
            'libelle': e.libelle,
            'piece_justificative': e.piece_justificative,
            'statut': e.statut,
            'statut_label': e.get_statut_label(),
            'total_debit': float(e.get_total_debit()),
            'total_credit': float(e.get_total_credit()),
            'est_equilibree': e.est_equilibree(),
            'created_by_nom': e.created_by_nom,
            'created_at': e.created_at.strftime('%Y-%m-%d %H:%M') if e.created_at else '',
            'lignes': lignes,
            'nb_lignes': len(e.lignes)
        })
    
    return jsonify({
        'data': result,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })


@compta_bp.route('/api/ecritures', methods=['POST'])
def api_creer_ecriture():
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvee'}), 400
        
        date_ecriture = parse_date(data.get('date_ecriture'))
        if not date_ecriture:
            return jsonify({'success': False, 'error': 'Format de date invalide'}), 400
        
        total_debit = sum(l.get('debit', 0) for l in data.get('lignes', []))
        total_credit = sum(l.get('credit', 0) for l in data.get('lignes', []))
        
        if total_debit != total_credit:
            return jsonify({'success': False, 'error': 'Les totaux debit et credit doivent etre egaux'}), 400
        
        erreur_tva = _controle_periode_tva(structure_id, date_ecriture, data.get('lignes'))
        if erreur_tva:
            return jsonify({'success': False, 'error': erreur_tva}), 400
        if exercice_cloture(structure_id, date_ecriture):
            return jsonify({'success': False, 'error': _message_exercice_cloture(date_ecriture)}), 400
        # Generer le numero de piece automatiquement
        numero_piece = SequencePiece.get_next_number(structure_id, 'ecriture')
        
        ecriture = EcritureComptable(
            structure_id=structure_id,
            date_ecriture=date_ecriture,
            libelle=data.get('libelle'),
            piece_justificative=numero_piece,
            statut='brouillon' if data.get('soumettre') != 'true' else 'en_attente',
            created_by=session.get('user_id'),
            created_by_nom=user_name,
            commentaire=data.get('commentaire'),
            journal_code=data.get('journal_code') or _journal_deduit(structure_id, data.get('lignes')),
        )
        
        db.session.add(ecriture)
        db.session.flush()
        
        for ligne_data in data.get('lignes', []):
            ligne = LigneEcriture(
                ecriture_id=ecriture.id,
                compte_id=ligne_data.get('compte_id'),
                debit=ligne_data.get('debit', 0),
                credit=ligne_data.get('credit', 0),
                libelle=ligne_data.get('libelle', '')
            )
            db.session.add(ligne)
        
        if data.get('soumettre') == 'true':
            validation = ValidationComptable(
                ecriture_id=ecriture.id,
                niveau=1,
                statut='en_attente'
            )
            db.session.add(validation)
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'id': ecriture.id,
            'numero_piece': numero_piece
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@compta_bp.route('/api/ecritures/<int:id>', methods=['GET'])
def api_get_ecriture(id):
    try:
        structure_id = session.get('structure_id')
        
        ecriture = EcritureComptable.query.filter_by(id=id, structure_id=structure_id).first()
        
        if not ecriture:
            return jsonify({'error': 'Ecriture non trouvee'}), 404
        
        result = {
            'id': ecriture.id,
            'date_ecriture': ecriture.date_ecriture.strftime('%Y-%m-%d') if ecriture.date_ecriture else '',
            'libelle': ecriture.libelle,
            'piece_justificative': ecriture.piece_justificative or '',
            'journal_code': ecriture.journal_code or '',
            'journal_label': ecriture.get_journal_label() if ecriture.journal_code else '',
            'statut': ecriture.statut,
            'statut_label': ecriture.get_statut_label(),
            'commentaire': ecriture.commentaire or '',
            'created_by_nom': ecriture.created_by_nom or '',
            'created_at': ecriture.created_at.strftime('%Y-%m-%d %H:%M') if ecriture.created_at else '',
            'validated_by_nom': ecriture.validated_by_nom or '',
            'date_validation': ecriture.date_validation.strftime('%Y-%m-%d') if ecriture.date_validation else '',
            'total_debit': float(ecriture.get_total_debit()),
            'total_credit': float(ecriture.get_total_credit()),
            'est_equilibree': ecriture.est_equilibree(),
            'lignes': []
        }
        
        for ligne in ecriture.lignes:
            result['lignes'].append({
                'compte_id': ligne.compte_id,
                'compte_numero': ligne.compte.numero if ligne.compte else '',
                'compte_nom': ligne.compte.nom if ligne.compte else '',
                'debit': float(ligne.debit) if ligne.debit else 0,
                'credit': float(ligne.credit) if ligne.credit else 0,
                'libelle': ligne.libelle or ''
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/ecritures/<int:id>', methods=['PUT'])
def api_modifier_ecriture(id):
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        ecriture = EcritureComptable.query.filter_by(id=id, structure_id=structure_id).first()
        
        if not ecriture:
            return jsonify({'error': 'Ecriture non trouvee'}), 404
        
        if ecriture.statut not in ['brouillon', 'refuse']:
            return jsonify({'error': 'Cette ecriture ne peut pas etre modifiee'}), 400
        
        date_ecriture = parse_date(data.get('date_ecriture'))
        if not date_ecriture:
            return jsonify({'success': False, 'error': 'Format de date invalide'}), 400
        
        total_debit = sum(l.get('debit', 0) for l in data.get('lignes', []))
        total_credit = sum(l.get('credit', 0) for l in data.get('lignes', []))
        
        if total_debit != total_credit:
            return jsonify({'success': False, 'error': 'Les totaux debit et credit doivent etre egaux'}), 400
        erreur_tva = _controle_periode_tva(structure_id, date_ecriture, data.get('lignes'))
        if erreur_tva:
            return jsonify({'success': False, 'error': erreur_tva}), 400
        if exercice_cloture(structure_id, date_ecriture):
            return jsonify({'success': False, 'error': _message_exercice_cloture(date_ecriture)}), 400
        
        ecriture.date_ecriture = date_ecriture
        ecriture.libelle = data.get('libelle')
        ecriture.journal_code = data.get('journal_code') or _journal_deduit(structure_id, data.get('lignes'))
        ecriture.commentaire = data.get('commentaire')
        # Ne pas modifier le numero de piece
        
        for ligne in ecriture.lignes:
            db.session.delete(ligne)
        
        for ligne_data in data.get('lignes', []):
            ligne = LigneEcriture(
                ecriture_id=ecriture.id,
                compte_id=ligne_data.get('compte_id'),
                debit=ligne_data.get('debit', 0),
                credit=ligne_data.get('credit', 0),
                libelle=ligne_data.get('libelle', '')
            )
            db.session.add(ligne)
        
        if data.get('soumettre') == 'true':
            ecriture.statut = 'en_attente'
            validation = ValidationComptable(
                ecriture_id=ecriture.id,
                niveau=1,
                statut='en_attente'
            )
            db.session.add(validation)
        
        db.session.commit()
        
        return jsonify({'success': True, 'id': ecriture.id})
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur: {e}")
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/ecritures/<int:id>/valider', methods=['POST'])
def api_valider_ecriture(id):
    data = request.json
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    
    ecriture = EcritureComptable.query.filter_by(id=id, structure_id=structure_id).first_or_404()
    if exercice_cloture(structure_id, ecriture.date_ecriture):
        return jsonify({'success': False, 'error': _message_exercice_cloture(ecriture.date_ecriture)}), 400
    
    niveau = data.get('niveau', 1)
    action = data.get('action', 'approuve')
    commentaire = data.get('commentaire', '')
    
    validation = ValidationComptable.query.filter_by(
        ecriture_id=id,
        niveau=niveau
    ).first()
    
    if not validation:
        validation = ValidationComptable(
            ecriture_id=id,
            niveau=niveau
        )
        db.session.add(validation)
    
    validation.statut = action
    validation.valide_par = session.get('user_id')
    validation.valide_par_nom = user_name
    validation.date_validation = date.today()
    validation.commentaire = commentaire
    
    if niveau == 1 and action == 'approuve':
        ecriture.statut = 'en_attente'
    elif niveau == 2 and action == 'approuve':
        erreur_tva = _controle_periode_tva(structure_id, ecriture.date_ecriture,
                                           [{'compte_id': l.compte_id} for l in ecriture.lignes])
        if erreur_tva:
            db.session.rollback()
            return jsonify({'success': False, 'error': erreur_tva}), 400
        ecriture.statut = 'valide'
        ecriture.validated_by = session.get('user_id')
        ecriture.validated_by_nom = user_name
        ecriture.date_validation = date.today()
    elif action == 'refuse':
        ecriture.statut = 'refuse'
    
    historique = HistoriqueEcriture(
        ecriture_id=id,
        action=f'validation_niveau_{niveau}',
        ancien_statut=validation.statut,
        nouveau_statut=action,
        modifie_par=session.get('user_id'),
        modifie_par_nom=user_name,
        commentaire=commentaire
    )
    db.session.add(historique)
    
    db.session.commit()
    
    return jsonify({'success': True})


# ============================================================
# BUDGET
# ============================================================

@compta_bp.route('/api/budget')
def api_budget():
    structure_id = session.get('structure_id')
    annee = request.args.get('annee', datetime.now().year)
    compte_id = request.args.get('compte_id')
    
    query_comptes = CompteComptable.query.filter_by(
        structure_id=structure_id,
        actif=True
    )
    
    if compte_id:
        query_comptes = query_comptes.filter_by(id=compte_id)
    
    comptes = query_comptes.order_by(CompteComptable.numero).all()
    
    budgets = Budget.query.filter_by(
        structure_id=structure_id,
        annee=annee
    ).all()
    
    budget_dict = {}
    for b in budgets:
        key = (b.compte_id, b.mois)
        budget_dict[key] = b
    
    result = []
    for compte in comptes:
        item = {
            'compte_id': compte.id,
            'compte_numero': compte.numero,
            'compte_nom': compte.nom,
            'mois': None,
            'montant_prevu': 0,
            'montant_reel': 0,
            'ecart': 0,
            'commentaire': ''
        }
        
        a_un_budget = False
        for mois in range(1, 13):
            key = (compte.id, mois)
            if key in budget_dict:
                a_un_budget = True
                b = budget_dict[key]
                if item['mois'] is None:
                    item['mois'] = mois
                    item['montant_prevu'] = float(b.montant_prevu)
                    item['montant_reel'] = float(b.montant_reel)
                    item['ecart'] = float(b.ecart)
                    item['commentaire'] = b.commentaire
        
        if a_un_budget:
            mois_data = []
            for mois in range(1, 13):
                key = (compte.id, mois)
                if key in budget_dict:
                    b = budget_dict[key]
                    mois_data.append({
                        'mois': mois,
                        'montant_prevu': float(b.montant_prevu),
                        'montant_reel': float(b.montant_reel),
                        'ecart': float(b.ecart)
                    })
                else:
                    mois_data.append({
                        'mois': mois,
                        'montant_prevu': 0,
                        'montant_reel': 0,
                        'ecart': 0
                    })
            item['mois_data'] = mois_data
        
        result.append(item)
    
    return jsonify(result)


@compta_bp.route('/api/budget', methods=['POST'])
def api_sauvegarder_budget():
    data = request.json
    structure_id = session.get('structure_id')
    
    budget = Budget.query.filter_by(
        structure_id=structure_id,
        compte_id=data.get('compte_id'),
        annee=data.get('annee'),
        mois=data.get('mois')
    ).first()
    
    if budget:
        budget.montant_prevu = data.get('montant_prevu', 0)
        budget.commentaire = data.get('commentaire', '')
        budget.updated_at = datetime.utcnow()
    else:
        budget = Budget(
            structure_id=structure_id,
            compte_id=data.get('compte_id'),
            annee=data.get('annee'),
            mois=data.get('mois'),
            montant_prevu=data.get('montant_prevu', 0),
            commentaire=data.get('commentaire', '')
        )
        db.session.add(budget)
    
    db.session.commit()
    
    return jsonify({'success': True})


@compta_bp.route('/api/exercice/statut')
def api_exercice_statut():
    """⭐ Statut des exercices comptables — onglet "Exercice comptable" (SYSCOHADA : l'exercice coïncide avec
    l'année civile). ⭐ 2026-10-22 : liste de TOUS les exercices (années ayant des écritures + l'année en cours)
    et exercice proposé à la clôture — le plus ancien exercice terminé et non clôturé, sinon l'année en cours.
    Avant, seule l'année civile du jour était connue : en janvier 2027, « Clôturer » aurait clôturé 2027."""
    structure_id = session.get('structure_id')
    annee_courante = datetime.now().year
    from sqlalchemy import text

    clotures = Cloture.query.filter_by(structure_id=structure_id).order_by(Cloture.annee.desc()).all()
    par_annee = {c.annee: c for c in clotures}
    rows = db.session.execute(text("""
        SELECT EXTRACT(YEAR FROM date_ecriture)::int AS annee, COUNT(*) AS nb,
               COUNT(*) FILTER (WHERE statut IN ('brouillon', 'en_attente')) AS nb_a_valider
        FROM ecritures_comptables WHERE structure_id = :structure_id GROUP BY 1
    """), {'structure_id': structure_id}).fetchall()
    stats = {r.annee: r for r in rows}
    annees = sorted(set(stats) | {annee_courante} | set(par_annee), reverse=True)

    exercices = []
    for a in annees:
        c = par_annee.get(a)
        exercices.append({
            'annee': a,
            'cloture': bool(c),
            'termine': date(a, 12, 31) < date.today(),
            'nb_ecritures': stats[a].nb if a in stats else 0,
            'nb_a_valider': stats[a].nb_a_valider if a in stats else 0,
            'date_cloture': c.date_cloture.strftime('%d/%m/%Y %H:%M') if c and c.date_cloture else '',
            'cloture_par': (c.created_by or '-') if c else '',
        })
    a_cloturer = sorted(e['annee'] for e in exercices if e['termine'] and not e['cloture'] and e['nb_ecritures'])
    annee_proposee = a_cloturer[0] if a_cloturer else annee_courante

    courant = next(e for e in exercices if e['annee'] == annee_courante)
    return jsonify({
        'annee_courante': annee_courante,
        'annee_proposee': annee_proposee,
        'exercices': exercices,
        # champs historiques (cartes du haut)
        'exercice_ouvert': not courant['cloture'],
        'nb_ecritures_exercice_courant': courant['nb_ecritures'],
        'nb_ecritures_a_valider': courant['nb_a_valider'],
        'clotures': [{
            'annee': c.annee,
            'date_cloture': c.date_cloture.strftime('%Y-%m-%d %H:%M') if c.date_cloture else '',
            'created_by': c.created_by or '-',
        } for c in clotures],
    })


# ============================================================
# APERÇU DE L'EXERCICE (avant ET après clôture) — patron, 22/10/2026
# ============================================================
# « Avant de clôturer, qu'on ait un aperçu de tout ce qu'on a fait dans l'année » : ce qui est rentré
# (produits), ce qui est sorti (charges), le résultat (gagné / perdu), la trésorerie (au total combien), ce
# qu'on nous doit et ce que nous devons, le bilan, et les contrôles à faire AVANT de clôturer. Lecture seule,
# même source que les autres états (écritures validées, comptes SYSCOHADA) ; imprimable (PDF) et exportable
# (CSV) comme les autres rapports (type 'exercice').
#
# La clôture ne passe AUCUNE écriture : ce module calcule tout en cumul depuis toujours (bilan, soldes,
# créances), les soldes de l'exercice N se retrouvent donc d'eux-mêmes à l'ouverture de N+1 — une écriture
# de report à nouveau (RAN) les compterait deux fois. Le bilan sépare le résultat de l'exercice des résultats
# des exercices antérieurs (report à nouveau), voir get_bilan().

RUBRIQUES_PRODUITS_SYSCOHADA = {
    '70': 'Ventes et prestations de services', '71': "Subventions d'exploitation", '72': 'Production immobilisée',
    '73': 'Variations des stocks de biens et services produits', '75': 'Autres produits',
    '77': 'Revenus financiers et produits assimilés', '78': 'Transferts de charges', '79': 'Reprises de provisions',
}

# Filtre commun : écriture validée de la structure, sans ligne sur un ancien compte ad-hoc sans classe
# (même exclusion que get_compte_resultat() / get_bilan()).
_SQL_ECRITURE_RETENUE = """
    e.structure_id = :structure_id AND e.statut = 'valide'
    AND NOT EXISTS (SELECT 1 FROM lignes_ecritures l2 JOIN comptes_comptables c2 ON c2.id = l2.compte_id
                    WHERE l2.ecriture_id = e.id AND (c2.classe IS NULL OR c2.classe = ''))
"""


_MESSAGE_CLOTURE_SANS_ECRITURE = (
    "Inutile : la clôture se fait dans l'onglet « Exercice comptable » (aperçu, contrôles, clôture). Les soldes passent "
    "d'eux-mêmes sur l'exercice suivant et le bilan range les résultats passés au report à nouveau ; une écriture de "
    "clôture ou de report à nouveau fausserait le compte de résultat ou doublerait les soldes.")


def _message_exercice_cloture(d):
    return (f"L'exercice {d.year} est clôturé : aucune écriture ne peut plus y être ajoutée, modifiée ou validée. "
            f"Passez l'opération sur l'exercice ouvert.")


def _par_rubrique(lignes, libelles):
    rubriques = {}
    for l in lignes:
        if abs(l['montant']) < 0.5:
            continue
        code = str(l['numero'] or '')[:2]
        rub = rubriques.setdefault(code, {'code': code, 'libelle': libelles.get(code, 'Autres'), 'total': 0.0, 'comptes': []})
        rub['total'] += l['montant']
        rub['comptes'].append({'numero': l['numero'], 'nom': l['nom'], 'montant': round(l['montant'], 2)})
    return [dict(rubriques[k], total=round(rubriques[k]['total'], 2)) for k in sorted(rubriques)]


def _mensuel_exercice(structure_id, debut, fin):
    from sqlalchemy import text
    rows = db.session.execute(text(f"""
        SELECT to_char(e.date_ecriture, 'YYYY-MM') AS mois, c.type,
               COALESCE(SUM(l.debit), 0) AS debit, COALESCE(SUM(l.credit), 0) AS credit
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON l.ecriture_id = e.id
        JOIN comptes_comptables c ON c.id = l.compte_id
        WHERE {_SQL_ECRITURE_RETENUE} AND c.type IN ('charge', 'produit')
          AND e.date_ecriture >= :debut AND e.date_ecriture <= :fin
        GROUP BY 1, 2
    """), {'structure_id': structure_id, 'debut': debut, 'fin': fin}).fetchall()
    mois = {f"{debut.year}-{m:02d}": {'produits': 0.0, 'charges': 0.0} for m in range(1, 13)}
    for r in rows:
        if r.mois not in mois:
            continue
        if r.type == 'produit':
            mois[r.mois]['produits'] += float(r.credit) - float(r.debit)
        else:
            mois[r.mois]['charges'] += float(r.debit) - float(r.credit)
    cumul, liste = 0.0, []
    for m in sorted(mois):
        v = mois[m]
        resultat = v['produits'] - v['charges']
        cumul += resultat
        liste.append({'mois': m, 'produits': round(v['produits'], 2), 'charges': round(v['charges'], 2),
                      'resultat': round(resultat, 2), 'cumul': round(cumul, 2)})
    return liste


def _tresorerie_exercice(structure_id, debut, fin):
    """Caisse / banque / mobile money (classe 5) : solde au 31/12 précédent, au 31/12, et ce qui est
    réellement entré / sorti dans l'année — hors virements internes (écriture uniquement entre comptes de
    trésorerie, ex. versement de la caisse à la banque)."""
    from sqlalchemy import text
    avant = _soldes_comptes_a_date(structure_id, debut - timedelta(days=1), classes=['5'])
    apres = _soldes_comptes_a_date(structure_id, fin, classes=['5'])
    comptes = [{'numero': n, 'nom': (apres.get(n) or avant.get(n))['nom'],
                'debut': round(avant.get(n, {}).get('solde', 0.0), 2), 'fin': round(apres.get(n, {}).get('solde', 0.0), 2)}
               for n in sorted(set(avant) | set(apres))]
    flux = db.session.execute(text(f"""
        SELECT COALESCE(SUM(l.debit), 0) AS entrees, COALESCE(SUM(l.credit), 0) AS sorties
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON l.ecriture_id = e.id
        JOIN comptes_comptables c ON c.id = l.compte_id
        WHERE {_SQL_ECRITURE_RETENUE} AND c.classe = '5'
          AND e.date_ecriture >= :debut AND e.date_ecriture <= :fin
          AND EXISTS (SELECT 1 FROM lignes_ecritures l3 JOIN comptes_comptables c3 ON c3.id = l3.compte_id
                      WHERE l3.ecriture_id = e.id AND c3.classe <> '5')
    """), {'structure_id': structure_id, 'debut': debut, 'fin': fin}).first()
    return {
        'comptes': [c for c in comptes if abs(c['debut']) >= 0.5 or abs(c['fin']) >= 0.5],
        'debut': round(sum(c['debut'] for c in comptes), 2),
        'fin': round(sum(c['fin'] for c in comptes), 2),
        'entrees': round(float(flux.entrees), 2),
        'sorties': round(float(flux.sorties), 2),
    }


def _tiers_exercice(structure_id, fin):
    """Classe 4 au 31/12 : ce qu'on nous doit (soldes débiteurs : patients, assurances, avances...) et ce que
    nous devons (soldes créditeurs : fournisseurs, personnel, organismes sociaux, État...). Les dépréciations
    (49x) viennent en moins des créances."""
    from sqlalchemy import text
    soldes = _soldes_comptes_a_date(structure_id, fin, classes=['4'])
    creances, dettes = [], []
    for numero in sorted(soldes):
        s = soldes[numero]['solde']
        if abs(s) < 0.5:
            continue
        ligne = {'numero': numero, 'nom': soldes[numero]['nom'], 'montant': round(abs(s), 2)}
        if numero.startswith('49'):
            creances.append(dict(ligne, montant=round(s, 2)))
        elif s > 0:
            creances.append(ligne)
        else:
            dettes.append(ligne)
    patients = db.session.execute(text(f"""
        SELECT COALESCE(NULLIF(l.tiers_nom, ''), 'Patient non nommé') AS nom, SUM(l.debit - l.credit) AS montant
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON l.ecriture_id = e.id
        JOIN comptes_comptables c ON c.id = l.compte_id
        WHERE {_SQL_ECRITURE_RETENUE} AND c.numero LIKE '411%' AND e.date_ecriture <= :fin
          AND (l.tiers_type = 'patient' OR l.tiers_type IS NULL)
          AND c.nom NOT ILIKE '%assurance%' AND c.nom NOT ILIKE '%tiers-payant%'
        GROUP BY 1 HAVING SUM(l.debit - l.credit) > 0.5
        ORDER BY 2 DESC LIMIT 10
    """), {'structure_id': structure_id, 'fin': fin}).fetchall()
    return {
        'creances': creances, 'dettes': dettes,
        'total_creances': round(sum(c['montant'] for c in creances), 2),
        'total_dettes': round(sum(d['montant'] for d in dettes), 2),
        'assureurs': generer_creances_par_assureur(structure_id, fin.strftime('%Y-%m-%d')),
        'patients_debiteurs': [{'nom': p.nom, 'montant': round(float(p.montant), 2)} for p in patients],
    }


def diagnostic_bilan(structure_id, fin, debut=None):
    """⭐ 2026-10-22 (patron) : « rechercher l'erreur » quand le bilan ou la balance ne tombe pas juste.
    Chaque écriture doit avoir débit = crédit ; l'écart du bilan est la somme des écarts des écritures qui ne
    le respectent pas. Deux causes possibles, cherchées ici :
      - écriture déséquilibrée : écart ≤ 1 F = arrondi (parts patient / assurances / TVA arrondies
        séparément), corrigeable d'un clic (ligne 658 / 758, voir api_corriger_arrondi) ; au-delà, la pièce
        est à vérifier ;
      - compte au type inconnu (ni actif, ni passif, ni charge, ni produit) : son solde n'est compté nulle
        part ; compte dont le type ne correspond pas à sa classe : rangé du mauvais côté."""
    from sqlalchemy import text
    rows = db.session.execute(text(f"""
        SELECT e.id, e.date_ecriture, e.piece_justificative, e.libelle,
               SUM(l.debit) AS debit, SUM(l.credit) AS credit
        FROM ecritures_comptables e JOIN lignes_ecritures l ON l.ecriture_id = e.id
        WHERE {_SQL_ECRITURE_RETENUE} AND e.date_ecriture <= :fin
          AND (CAST(:debut AS date) IS NULL OR e.date_ecriture >= CAST(:debut AS date))
        GROUP BY e.id HAVING ABS(SUM(l.debit) - SUM(l.credit)) >= 0.01
        ORDER BY e.date_ecriture, e.id
    """), {'structure_id': structure_id, 'fin': fin, 'debut': debut}).fetchall()
    annees_closes = {c.annee for c in Cloture.query.filter_by(structure_id=structure_id).all()}
    ecritures = []
    for r in rows:
        ecart = round(float(r.debit) - float(r.credit), 2)
        ecritures.append({
            'id': r.id, 'date': r.date_ecriture.strftime('%d/%m/%Y'), 'piece': r.piece_justificative or '',
            'libelle': r.libelle or '', 'debit': round(float(r.debit), 2), 'credit': round(float(r.credit), 2),
            'ecart': ecart, 'arrondi': abs(ecart) <= 1, 'cloturee': r.date_ecriture.year in annees_closes,
        })
    comptes = db.session.execute(text(f"""
        SELECT c.numero, c.nom, c.classe, c.type, SUM(l.debit - l.credit) AS solde
        FROM comptes_comptables c
        JOIN lignes_ecritures l ON l.compte_id = c.id JOIN ecritures_comptables e ON e.id = l.ecriture_id
        WHERE {_SQL_ECRITURE_RETENUE} AND e.date_ecriture <= :fin
          AND NOT ((c.classe IN ('1', '2', '3', '4', '5') AND c.type IN ('actif', 'passif'))
                   OR (c.classe = '6' AND c.type = 'charge') OR (c.classe = '7' AND c.type = 'produit'))
        GROUP BY c.numero, c.nom, c.classe, c.type
        HAVING ABS(SUM(l.debit - l.credit)) >= 0.01
        ORDER BY c.numero
    """), {'structure_id': structure_id, 'fin': fin}).fetchall()
    return {
        'ecritures': ecritures,
        'ecart_ecritures': round(sum(e['ecart'] for e in ecritures), 2),
        'comptes': [{'numero': c.numero, 'nom': c.nom, 'classe': c.classe, 'type': c.type or '',
                     'solde': round(float(c.solde), 2),
                     'probleme': ("type inconnu : son solde n'apparaît ni au bilan ni au compte de résultat"
                                  if c.type not in ('actif', 'passif', 'charge', 'produit')
                                  else f"classe {c.classe} rangée en « {c.type} » : mauvais côté du bilan / du résultat")}
                    for c in comptes],
    }


def _controles_cloture(structure_id, annee, debut, fin, bilan, tresorerie):
    """Points à vérifier avant de clôturer. niveau : 'bloquant' (la clôture est refusée), 'attention' (à
    regarder, n'empêche pas), 'ok'."""
    from sqlalchemy import text
    controles = []

    def ajouter(niveau, titre, detail=''):
        controles.append({'niveau': niveau, 'titre': titre, 'detail': detail})

    if fin >= date.today():
        ajouter('bloquant', f"L'exercice {annee} n'est pas terminé",
                f"Il se termine le 31/12/{annee} : la clôture se fait après cette date. L'aperçu montre la situation à ce jour.")
    else:
        ajouter('ok', f"Exercice {annee} terminé (31/12/{annee})")

    anterieures = db.session.execute(text("""
        SELECT DISTINCT EXTRACT(YEAR FROM date_ecriture)::int AS annee FROM ecritures_comptables
        WHERE structure_id = :structure_id AND statut = 'valide' AND date_ecriture < :debut
    """), {'structure_id': structure_id, 'debut': debut}).fetchall()
    cloturees = {c.annee for c in Cloture.query.filter_by(structure_id=structure_id).all()}
    non_cloturees = sorted(r.annee for r in anterieures if r.annee not in cloturees)
    if non_cloturees:
        ajouter('bloquant', "Exercice précédent non clôturé",
                f"Clôturez d'abord : {', '.join(str(a) for a in non_cloturees)} (les exercices se clôturent dans l'ordre).")

    nb_a_valider = EcritureComptable.query.filter(
        EcritureComptable.structure_id == structure_id,
        EcritureComptable.statut.in_(['brouillon', 'en_attente']),
        EcritureComptable.date_ecriture >= debut, EcritureComptable.date_ecriture <= fin,
    ).count()
    if nb_a_valider:
        ajouter('bloquant', f"{nb_a_valider} écriture(s) en brouillon ou en attente de validation",
                "Elles ne comptent dans aucun état : validez-les ou refusez-les (onglet Écritures) avant de clôturer.")
    else:
        ajouter('ok', "Aucune écriture en attente de validation")

    # ⭐ contrôle écriture par écriture (avant : seul le total de l'année, à 1 F près — un écart d'arrondi passait)
    desequilibrees = diagnostic_bilan(structure_id, fin, debut)['ecritures']
    if desequilibrees:
        ajouter('bloquant', f"{len(desequilibrees)} écriture(s) déséquilibrée(s) (débit ≠ crédit)",
                f"Écart total {_fmt_ecart(sum(e['ecart'] for e in desequilibrees))} F — voir "
                f"« Rechercher l'erreur » : un écart d'au plus 1 F est un arrondi, corrigé d'un clic.")
    else:
        ajouter('ok', "Toutes les écritures sont équilibrées (débit = crédit)")

    ecart_bilan = round(bilan.get('total_actif', 0) - bilan.get('total_passif_capitaux', 0), 2)
    if abs(ecart_bilan) < 0.01:
        ajouter('ok', "Bilan équilibré (actif = passif + capitaux propres)")
    else:
        ajouter('attention', f"Bilan déséquilibré de {_fmt_ecart(ecart_bilan)} F",
                f"Actif {_fmt_montant(bilan.get('total_actif', 0))} F, passif + capitaux propres "
                f"{_fmt_montant(bilan.get('total_passif_capitaux', 0))} F — voir « Rechercher l'erreur ».")

    nb_anomalies = AnomalieComptable.query.filter(AnomalieComptable.structure_id == structure_id,
                                                  db.or_(AnomalieComptable.resolu.is_(None), AnomalieComptable.resolu.is_(False))).count()
    if nb_anomalies:
        ajouter('attention', f"{nb_anomalies} anomalie(s) comptable(s) non résolue(s)",
                "Opérations qui n'ont pas pu être comptabilisées automatiquement : à régulariser (Tableau de bord, Anomalies).")

    nb_exclues = db.session.execute(text("""
        SELECT COUNT(DISTINCT e.id) FROM ecritures_comptables e
        JOIN lignes_ecritures l ON l.ecriture_id = e.id JOIN comptes_comptables c ON c.id = l.compte_id
        WHERE e.structure_id = :structure_id AND e.statut = 'valide' AND (c.classe IS NULL OR c.classe = '')
          AND e.date_ecriture >= :debut AND e.date_ecriture <= :fin
    """), {'structure_id': structure_id, 'debut': debut, 'fin': fin}).scalar() or 0
    if nb_exclues:
        ajouter('attention', f"{nb_exclues} écriture(s) sur d'anciens comptes hors plan SYSCOHADA",
                "Elles sont écartées du résultat et du bilan : les repasser sur les bons comptes si elles sont réelles.")

    immos = Immobilisation.query.filter(Immobilisation.structure_id == structure_id,
                                        Immobilisation.statut == 'en_service',
                                        Immobilisation.date_acquisition <= fin).all()
    if immos:
        dotees = {d.immobilisation_id for d in DotationAmortissement.query.filter_by(structure_id=structure_id, annee=annee).all()}
        sans_dotation = [i for i in immos if i.id not in dotees
                         and float(i.cumul_amorti or 0) < float(i.valeur_acquisition or 0) - float(i.valeur_residuelle or 0) - 0.5]
        if sans_dotation:
            ajouter('attention', f"Amortissements {annee} non passés ({len(sans_dotation)} immobilisation(s))",
                    "Générez les dotations de l'année (onglet Immobilisations) pour que la charge figure au résultat.")
        else:
            ajouter('ok', f"Amortissements {annee} passés")

    tva = ParametrageTva.query.filter_by(structure_id=structure_id).first()
    if tva and tva.assujetti:
        derniere = DeclarationTva.query.filter(DeclarationTva.structure_id == structure_id,
                                               DeclarationTva.statut != 'annulee').order_by(DeclarationTva.date_fin.desc()).first()
        if not derniere or derniere.date_fin < fin:
            ajouter('attention', "TVA de fin d'exercice non déclarée",
                    f"Dernière période déclarée jusqu'au {derniere.date_fin.strftime('%d/%m/%Y')}." if derniere
                    else "Aucune déclaration de TVA enregistrée (onglet TVA).")
        else:
            ajouter('ok', "TVA déclarée jusqu'à la fin de l'exercice")

    caisse = next((c for c in tresorerie['comptes'] if c['numero'].startswith('57')), None)
    if caisse and caisse['fin'] < -0.5:
        ajouter('attention', "Caisse négative au 31/12",
                f"Solde {_fmt_montant(caisse['fin'])} F : une caisse ne peut pas être négative, une recette manque ou une dépense est en trop.")
    return controles


def get_apercu_exercice(structure_id, annee):
    debut, fin = date(annee, 1, 1), date(annee, 12, 31)
    resultat = get_compte_resultat(structure_id, debut.isoformat(), fin.isoformat())
    bilan = get_bilan(structure_id, fin.isoformat())
    tresorerie = _tresorerie_exercice(structure_id, debut, fin)
    controles = _controles_cloture(structure_id, annee, debut, fin, bilan, tresorerie)
    cloture = Cloture.query.filter_by(structure_id=structure_id, annee=annee).first()

    n1 = None
    precedent = get_compte_resultat(structure_id, date(annee - 1, 1, 1).isoformat(), date(annee - 1, 12, 31).isoformat())
    if precedent['produits'] or precedent['charges']:
        n1 = {'annee': annee - 1, 'total_produits': round(precedent['total_produits'], 2),
              'total_charges': round(precedent['total_charges'], 2), 'resultat': round(precedent['resultat'], 2),
              'tresorerie_fin': tresorerie['debut']}

    nb_ecritures = EcritureComptable.query.filter(
        EcritureComptable.structure_id == structure_id, EcritureComptable.statut == 'valide',
        EcritureComptable.date_ecriture >= debut, EcritureComptable.date_ecriture <= fin).count()
    return {
        'annee': annee,
        'date_debut': debut.isoformat(), 'date_fin': fin.isoformat(),
        'en_cours': fin >= date.today(),
        'situation_au': min(fin, date.today()).strftime('%d/%m/%Y'),
        'cloture': {'date': cloture.date_cloture.strftime('%d/%m/%Y %H:%M') if cloture.date_cloture else '',
                    'par': cloture.created_by or '-'} if cloture else None,
        'nb_ecritures': nb_ecritures,
        'total_produits': round(resultat['total_produits'], 2),
        'total_charges': round(resultat['total_charges'], 2),
        'resultat': round(resultat['resultat'], 2),
        'resultat_text': 'Bénéfice' if resultat['resultat'] >= 0 else 'Perte',
        'produits': _par_rubrique(resultat['produits'], RUBRIQUES_PRODUITS_SYSCOHADA),
        'charges': _par_rubrique(resultat['charges'], RUBRIQUES_CHARGES_SYSCOHADA),
        'mensuel': _mensuel_exercice(structure_id, debut, fin),
        'tresorerie': tresorerie,
        'tiers': _tiers_exercice(structure_id, fin),
        'bilan': bilan,
        'sig': _sig_et_cafg(structure_id, debut, fin),
        'n1': n1,
        'controles': controles,
        'diagnostic': diagnostic_bilan(structure_id, fin),
        'ecart_bilan': round(bilan.get('total_actif', 0) - bilan.get('total_passif_capitaux', 0), 2),
        'peut_cloturer': not cloture and not any(c['niveau'] == 'bloquant' for c in controles),
    }


def _annee_demandee(valeur):
    try:
        annee = int(valeur)
    except (TypeError, ValueError):
        return None
    return annee if 2000 <= annee <= 2100 else None


@compta_bp.route('/api/exercice/apercu')
def api_exercice_apercu():
    structure_id = session.get('structure_id')
    annee = _annee_demandee(request.args.get('annee')) or datetime.now().year
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404
    return jsonify({'success': True, **get_apercu_exercice(structure_id, annee)})


@compta_bp.route('/api/ecritures/<int:id>/corriger-arrondi', methods=['POST'])
def api_corriger_arrondi(id):
    """⭐ 2026-10-22 : solde l'écart d'arrondi (≤ 1 F) d'une écriture validée déséquilibrée par une ligne
    « Écart d'arrondi » en 658 (charges diverses) ou 758 (produits divers) — l'écriture n'est pas modifiée
    autrement ; la correction est tracée dans son historique."""
    from services.comptabilite_service import ligne_ecart_arrondi, _get_compte_id
    structure_id = session.get('structure_id')
    ecriture = EcritureComptable.query.filter_by(id=id, structure_id=structure_id).first()
    if not ecriture:
        return jsonify({'success': False, 'error': 'Écriture introuvable'}), 404
    if exercice_cloture(structure_id, ecriture.date_ecriture):
        return jsonify({'success': False, 'error': _message_exercice_cloture(ecriture.date_ecriture)}), 400
    ecart = round(sum(float(l.debit or 0) for l in ecriture.lignes) - sum(float(l.credit or 0) for l in ecriture.lignes), 2)
    if abs(ecart) < 0.01:
        return jsonify({'success': False, 'error': "Cette écriture est déjà équilibrée."}), 400
    if abs(ecart) > 1:
        return jsonify({'success': False, 'error': (
            f"Écart de {_fmt_ecart(ecart)} F : ce n'est pas un arrondi. Vérifiez la pièce {ecriture.piece_justificative or ''} "
            f"(montants saisis, ligne oubliée) et passez une écriture de correction.")}), 400
    ligne = ligne_ecart_arrondi(ecart)
    db.session.add(LigneEcriture(ecriture_id=ecriture.id, compte_id=_get_compte_id(structure_id, ligne['numero_compte']),
                                 debit=ligne.get('debit', 0), credit=ligne.get('credit', 0), libelle=ligne['libelle']))
    db.session.add(HistoriqueEcriture(
        ecriture_id=ecriture.id, action='correction_arrondi', ancien_statut=ecriture.statut, nouveau_statut=ecriture.statut,
        modifie_par=session.get('user_id'), modifie_par_nom=session.get('user_name', 'System'),
        commentaire=f"Écart d'arrondi de {_fmt_ecart(ecart)} F soldé en {ligne['numero_compte']} "
                    f"({'débit' if ligne.get('debit') else 'crédit'})"))
    db.session.commit()
    invalidate_cache(structure_id)
    return jsonify({'success': True, 'message': (
        f"Écriture {ecriture.piece_justificative or ecriture.id} équilibrée : écart d'arrondi de {_fmt_ecart(ecart)} F "
        f"passé en {'charges diverses (658)' if ligne.get('debit') else 'produits divers (758)'}.")})


@compta_bp.route('/api/cloture', methods=['POST'])
def api_cloture():
    """Clôture d'un exercice : refusée tant qu'un contrôle bloquant reste (exercice pas terminé, exercice
    précédent ouvert, écritures en attente, balance déséquilibrée — voir _controles_cloture). Fige les
    écritures : plus aucun ajout, modification ou validation dans l'année (routes d'écritures et
    services/comptabilite_service.creer_ecriture)."""
    structure_id = session.get('structure_id')
    annee = _annee_demandee((request.json or {}).get('annee'))
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404
    if not annee:
        return jsonify({'success': False, 'error': 'Année requise'}), 400

    try:
        if Cloture.query.filter_by(structure_id=structure_id, annee=annee).first():
            return jsonify({'success': False, 'error': f"L'exercice {annee} est déjà clôturé"}), 400

        apercu = get_apercu_exercice(structure_id, annee)
        bloquants = [c for c in apercu['controles'] if c['niveau'] == 'bloquant']
        if bloquants:
            return jsonify({'success': False, 'controles': bloquants,
                            'error': "Clôture impossible :\n" + '\n'.join(f"• {c['titre']} — {c['detail']}" for c in bloquants)}), 400

        maintenant = datetime.utcnow()
        nb_ecritures = EcritureComptable.query.filter(
            EcritureComptable.structure_id == structure_id,
            EcritureComptable.date_ecriture >= date(annee, 1, 1),
            EcritureComptable.date_ecriture <= date(annee, 12, 31),
            EcritureComptable.statut == 'valide',
        ).update({'cloturee': True, 'date_cloture': maintenant}, synchronize_session=False)

        db.session.add(Cloture(structure_id=structure_id, annee=annee, date_cloture=maintenant,
                               created_by=session.get('user_name', 'System')))
        db.session.commit()
        return jsonify({
            'success': True,
            'message': (f"Exercice {annee} clôturé ({nb_ecritures} écritures figées). "
                        f"Résultat : {apercu['resultat_text'].lower()} de {_fmt_montant(abs(apercu['resultat']))} F. "
                        f"Les soldes passent automatiquement sur {annee + 1}.")
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# RAPPORTS
# ============================================================

@compta_bp.route('/api/rapports/journal')
def api_journal():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    journal_code = request.args.get('journal_code')  # VTE / CAI / BQ / ACH / OD / None = tous

    return jsonify(generer_journal(structure_id, date_debut, date_fin, journal_code))


@compta_bp.route('/api/rapports/journaux/liste')
def api_liste_journaux():
    """Liste des journaux auxiliaires disponibles (pour le sélecteur)."""
    return jsonify([{'code': code, 'nom': nom} for code, nom in EcritureComptable.JOURNAUX.items()])


@compta_bp.route('/api/rapports/exercices/liste')
def api_liste_exercices():
    """⭐ Sélecteur "Exercice" des rapports — porté depuis GHP (2026-09-30).
    Retourne les années ayant au moins une écriture validée pour cette
    structure, plus l'année civile en cours même si elle est encore vide."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify([])

    from sqlalchemy import text
    rows = db.session.execute(text("""
        SELECT DISTINCT EXTRACT(YEAR FROM date_ecriture)::int AS annee
        FROM ecritures_comptables
        WHERE structure_id = :structure_id AND statut = 'valide'
    """), {'structure_id': structure_id}).fetchall()

    annee_courante = datetime.now().year
    annees = {r.annee for r in rows}
    annees.add(annee_courante)

    def _libelle(a):
        ecart = annee_courante - a
        if ecart == 0:
            return f"Exercice {a} (en cours)"
        if ecart > 0:
            return f"Exercice {a} (N-{ecart})"
        return f"Exercice {a} (N+{-ecart})"

    return jsonify([{'annee': a, 'libelle': _libelle(a)} for a in sorted(annees, reverse=True)])


@compta_bp.route('/api/rapports/grand_livre')
def api_grand_livre():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    compte_id = request.args.get('compte_id', type=int)  # vue "grand livre d'un seul compte"
    tiers_type = request.args.get('tiers_type') or None
    tiers_id = request.args.get('tiers_id', type=int)     # vue "grand livre auxiliaire" (client/fournisseur)

    return jsonify(generer_grand_livre(structure_id, date_debut, date_fin, compte_id, tiers_type, tiers_id))


@compta_bp.route('/api/caisses')
def api_caisses():
    """Les deux caisses bien visibles : Trésorerie (disponible réel) et
    Chiffre d'affaires (total des ventes de la période)."""
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')

    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None

    return jsonify(get_soldes_caisses(structure_id, date_debut_obj, date_fin_obj))


@compta_bp.route('/api/rapports/charges')
def api_etat_charges():
    return jsonify(generer_etat_charges(session.get('structure_id'), request.args.get('date_debut'),
                                        request.args.get('date_fin')))


@compta_bp.route('/api/rapports/balance')
def api_balance():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    
    return jsonify(generer_balance(structure_id, date_debut, date_fin))


@compta_bp.route('/api/rapports/tva')
def api_rapport_tva():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')

    return jsonify(generer_declaration_tva(structure_id, date_debut, date_fin))


@compta_bp.route('/api/rapports/resultat')
def api_rapport_resultat():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    
    return jsonify(get_compte_resultat(structure_id, date_debut, date_fin))


@compta_bp.route('/api/rapports/bilan')
def api_rapport_bilan():
    structure_id = session.get('structure_id')
    date_fin = request.args.get('date_fin')
    
    return jsonify(get_bilan(structure_id, date_fin))


def generer_journal(structure_id, date_debut, date_fin, journal_code=None):
    from sqlalchemy import text

    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None

    result = db.session.execute(text("""
        SELECT
            e.date_ecriture,
            e.piece_justificative,
            e.libelle,
            e.journal_code,
            e.generee_auto,
            c.numero as compte_numero,
            c.nom as compte_nom,
            l.debit,
            l.credit,
            l.tiers_nom
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON e.id = l.ecriture_id
        JOIN comptes_comptables c ON l.compte_id = c.id
        WHERE e.structure_id = :structure_id
        AND e.statut = 'valide'
        AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
        AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        AND (:journal_code IS NULL OR e.journal_code = :journal_code)
        ORDER BY e.date_ecriture DESC, e.id DESC
    """), {
        'structure_id': structure_id,
        'date_debut': date_debut_obj.strftime('%Y-%m-%d') if date_debut_obj else None,
        'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None,
        'journal_code': journal_code or None,
    })

    rows = result.fetchall()

    return [{
        'date': row.date_ecriture.strftime('%Y-%m-%d') if row.date_ecriture else '',
        'piece': row.piece_justificative or '',
        'libelle': row.libelle or '',
        'journal_code': row.journal_code or '',
        'generee_auto': bool(row.generee_auto),
        'compte_numero': row.compte_numero or '',
        'compte_nom': row.compte_nom or '',
        'debit': float(row.debit or 0),
        'credit': float(row.credit or 0),
        'tiers_nom': row.tiers_nom or '',
    } for row in rows]


def generer_grand_livre(structure_id, date_debut, date_fin, compte_id=None, tiers_type=None, tiers_id=None):
    """⭐ tiers_type/tiers_id (en plus de compte_id) : grand livre AUXILIAIRE
    d'un client ou fournisseur précis — mêmes lignes que le grand livre
    général, mais filtrées sur un tiers plutôt que (ou en plus) d'un
    compte, avec solde courant cumulé (comme un relevé de compte client)."""
    from sqlalchemy import text

    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None

    result = db.session.execute(text("""
        SELECT
            l.id as ligne_id,
            e.date_ecriture,
            c.id as compte_id,
            c.numero as compte_numero,
            c.nom as compte_nom,
            e.libelle,
            e.piece_justificative,
            l.debit,
            l.credit,
            l.tiers_type,
            l.tiers_id,
            l.tiers_nom,
            l.lettre,
            l.date_lettrage
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON e.id = l.ecriture_id
        JOIN comptes_comptables c ON l.compte_id = c.id
        WHERE e.structure_id = :structure_id
        AND e.statut = 'valide'
        AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
        AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        AND (:compte_id IS NULL OR l.compte_id = :compte_id)
        AND (:tiers_type IS NULL OR l.tiers_type = :tiers_type)
        AND (:tiers_id IS NULL OR l.tiers_id = :tiers_id)
        ORDER BY c.numero, e.date_ecriture, e.id
    """), {
        'structure_id': structure_id,
        'date_debut': date_debut_obj.strftime('%Y-%m-%d') if date_debut_obj else None,
        'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None,
        'compte_id': compte_id,
        'tiers_type': tiers_type,
        'tiers_id': tiers_id,
    })

    rows = result.fetchall()

    solde = 0.0
    lignes = []
    for row in rows:
        debit, credit = float(row.debit or 0), float(row.credit or 0)
        solde += debit - credit
        lignes.append({
            'ligne_id': row.ligne_id,
            'date': row.date_ecriture.strftime('%Y-%m-%d') if row.date_ecriture else '',
            'compte_id': row.compte_id,
            'compte_numero': row.compte_numero or '',
            'compte_nom': row.compte_nom or '',
            'libelle': row.libelle or '',
            'piece': row.piece_justificative or '',
            'debit': debit,
            'credit': credit,
            'tiers_type': row.tiers_type or '',
            'tiers_nom': row.tiers_nom or '',
            'lettre': row.lettre or '',
            'date_lettrage': row.date_lettrage.strftime('%d/%m/%Y') if row.date_lettrage else '',
            # Solde cumulé — n'a de sens que filtré sur un seul compte/tiers
            # (mélanger plusieurs comptes dans une même colonne "solde" ne
            # voudrait rien dire) ; laissé à None sinon pour ne pas induire
            # en erreur côté affichage/export.
            'solde_courant': round(solde, 2) if (compte_id or tiers_id) else None,
        })
    return lignes


@compta_bp.route('/api/cloture-exercice/apercu')
def api_cloture_exercice_apercu():
    """Calcule (sans rien enregistrer) l'écriture de clôture des comptes
    de gestion (classes 6/7 -> compte 12) pour une période — porté depuis
    GHP (2026-09-30)."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404

    date_debut = parse_date(request.args.get('date_debut'))
    date_fin = parse_date(request.args.get('date_fin'))
    if not date_debut or not date_fin:
        return jsonify({'success': False, 'error': 'Dates de début/fin invalides'}), 400

    from services.comptabilite_service import previsualiser_cloture_exercice
    apercu = previsualiser_cloture_exercice(structure_id, date_debut, date_fin)
    return jsonify({'success': True, **apercu})


@compta_bp.route('/api/cloture-exercice/generer', methods=['POST'])
def api_cloture_exercice_generer():
    """Génère (et valide immédiatement) l'écriture de clôture des comptes
    de gestion — action volontaire, jamais automatique.

    ⭐ 2026-10-22 : désactivé. Cette écriture solde les comptes 6/7 dans le compte 13 : le compte de résultat
    de l'exercice serait ensuite à zéro, puisque tous les états le calculent à partir des comptes 6/7. La
    clôture se fait par l'onglet « Exercice comptable » (aperçu, contrôles, verrouillage) ; le bilan range
    lui-même les résultats passés au report à nouveau (get_bilan)."""
    return jsonify({'success': False, 'error': _MESSAGE_CLOTURE_SANS_ECRITURE}), 400


@compta_bp.route('/api/report-a-nouveau/apercu')
def api_report_a_nouveau_apercu():
    """Calcule (sans rien enregistrer) ce que produirait la génération du
    report à nouveau pour une date de clôture donnée — porté depuis GHP
    (2026-09-30)."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404

    date_cloture = parse_date(request.args.get('date_cloture'))
    if not date_cloture:
        return jsonify({'success': False, 'error': 'Date de clôture invalide'}), 400

    from services.comptabilite_service import previsualiser_report_a_nouveau
    apercu = previsualiser_report_a_nouveau(structure_id, date_cloture)
    return jsonify({'success': True, **apercu})


@compta_bp.route('/api/report-a-nouveau/generer', methods=['POST'])
def api_report_a_nouveau_generer():
    """Génère (et valide immédiatement) l'écriture de report à nouveau —
    action volontaire du comptable, jamais automatique/planifiée.

    ⭐ 2026-10-22 : désactivé. Bilan, soldes, créances et trésorerie sont calculés en cumul depuis toujours :
    les soldes de N sont DÉJÀ ceux d'ouverture de N+1, une écriture RAN les compterait deux fois."""
    return jsonify({'success': False, 'error': _MESSAGE_CLOTURE_SANS_ECRITURE}), 400


@compta_bp.route('/api/tiers')
def api_liste_tiers():
    """Liste des tiers (clients/fournisseurs) ayant AU MOINS une écriture —
    pour peupler le sélecteur "Grand livre auxiliaire" ; volontairement pas
    la liste complète des patients/fournisseurs de la structure (souvent
    bien plus grande, et sans intérêt comptable pour ceux qui n'ont jamais
    mouvementé un compte 411/401)."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify([])

    from sqlalchemy import text
    rows = db.session.execute(text("""
        SELECT DISTINCT l.tiers_type, l.tiers_id, l.tiers_nom
        FROM lignes_ecritures l
        JOIN ecritures_comptables e ON e.id = l.ecriture_id
        WHERE e.structure_id = :structure_id AND l.tiers_id IS NOT NULL
        ORDER BY l.tiers_nom
    """), {'structure_id': structure_id}).fetchall()

    return jsonify([{
        'tiers_type': r.tiers_type, 'tiers_id': r.tiers_id, 'tiers_nom': r.tiers_nom,
    } for r in rows])


# ========== LETTRAGE (rapprochement créance/règlement sur un compte) ==========

@compta_bp.route('/api/lettrage/lettrer', methods=['POST'])
def api_lettrer():
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404

    from services.comptabilite_service import lettrer_lignes
    data = request.json or {}
    ligne_ids = data.get('ligne_ids') or []
    user_nom = session.get('user_name', 'System')

    lettre, erreur = lettrer_lignes(structure_id, ligne_ids, user_nom)
    if erreur:
        return jsonify({'success': False, 'error': erreur}), 400
    return jsonify({'success': True, 'lettre': lettre})


@compta_bp.route('/api/lettrage/delettrer', methods=['POST'])
def api_delettrer():
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404

    from services.comptabilite_service import delettrer_lignes
    data = request.json or {}
    ligne_ids = data.get('ligne_ids') or []

    n = delettrer_lignes(structure_id, ligne_ids)
    return jsonify({'success': True, 'nb_lignes_liberees': n})


@compta_bp.route('/api/lettrage/auto', methods=['POST'])
def api_auto_lettrer():
    """Lettrage automatique — uniquement le cas non ambigu (voir
    auto_lettrer_compte). Un compte est requis : lettrer "tous les
    comptes en même temps" n'a pas de sens (le lettrage compare des
    montants À L'INTÉRIEUR d'un même compte)."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404

    from services.comptabilite_service import auto_lettrer_compte
    data = request.json or {}
    compte_id = data.get('compte_id')
    if not compte_id:
        return jsonify({'success': False, 'error': 'Choisissez un compte précis pour le lettrage automatique.'}), 400

    nb = auto_lettrer_compte(structure_id, compte_id)
    return jsonify({'success': True, 'nb_paires_lettrees': nb})


def generer_balance(structure_id, date_debut, date_fin):
    """⭐ Réécrit en une seule requête SQL agrégée — porté depuis GHP
    (2026-09-30). La version précédente chargeait TOUTES les lignes JAMAIS
    enregistrées de CHAQUE compte (compte.lignes, sans filtre SQL), y
    compris hors période demandée, puis filtrait en Python + déclenchait
    une requête séparée par ligne pour lire ligne.ecriture.statut (N+1),
    avec un vrai risque de crash (AttributeError) sur une ligne orpheline
    (ecriture_id pointant vers une écriture supprimée)."""
    from sqlalchemy import text

    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None

    rows = db.session.execute(text("""
        SELECT c.numero AS compte_numero, c.nom AS compte_nom,
               SUM(l.debit) AS total_debit,
               SUM(l.credit) AS total_credit
        FROM comptes_comptables c
        JOIN lignes_ecritures l ON l.compte_id = c.id
        JOIN ecritures_comptables e ON e.id = l.ecriture_id
        WHERE c.structure_id = :structure_id AND c.actif = true
          AND e.statut = 'valide'
          AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
          AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        GROUP BY c.id, c.numero, c.nom
        HAVING SUM(l.debit) > 0 OR SUM(l.credit) > 0
        ORDER BY c.numero
    """), {
        'structure_id': structure_id,
        'date_debut': date_debut_obj.strftime('%Y-%m-%d') if date_debut_obj else None,
        'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None,
    }).fetchall()

    result = []
    for row in rows:
        total_debit = float(row.total_debit)
        total_credit = float(row.total_credit)
        result.append({
            'compte_numero': row.compte_numero,
            'compte_nom': row.compte_nom,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'solde': total_debit - total_credit,
        })

    return result


def generer_repartition_journaux(structure_id, date_debut=None, date_fin=None):
    """[{journal_code, label, nb}] — nombre d'écritures VALIDÉES par
    journal, pour la barre segmentée du tableau de bord. Même patron SQL
    agrégé que generer_balance() ci-dessus. Labels tirés de
    EcritureComptable.JOURNAUX (models.py) — pas de libellé recopié en dur.

    ⭐ C'est un FLUX (combien d'écritures sur la période) — les deux
    bornes s'appliquent, contrairement à generer_creances_par_assureur()
    juste en dessous qui est un solde (date_fin seule)."""
    from sqlalchemy import text

    rows = db.session.execute(text("""
        SELECT journal_code, COUNT(*) AS nb
        FROM ecritures_comptables
        WHERE structure_id = :structure_id AND statut = 'valide' AND journal_code IS NOT NULL
          AND (:date_debut IS NULL OR date_ecriture >= :date_debut)
          AND (:date_fin IS NULL OR date_ecriture <= :date_fin)
        GROUP BY journal_code
        ORDER BY nb DESC
    """), {'structure_id': structure_id, 'date_debut': date_debut, 'date_fin': date_fin}).fetchall()

    return [
        {'journal_code': row.journal_code, 'label': EcritureComptable.JOURNAUX.get(row.journal_code, row.journal_code), 'nb': row.nb}
        for row in rows
    ]


def generer_creances_par_assureur(structure_id, date_fin=None):
    """[{tiers_nom, montant}] — encours net (débit - crédit, un compte de
    tiers-payant à recevoir est normalement débiteur) par assureur, pour
    la carte "Créances par assureur" du tableau de bord.

    ⭐ Regroupe par COMPTE (chaque assureur a son propre compte dédié dans
    le plan SYSCOHADA, ex. 41122700 "Assurance OLEA"), PAS par
    lignes_ecritures.tiers_type/tiers_nom : vérifié en direct sur des
    données réelles, ce couple n'est renseigné que sur une poignée de
    lignes (2 sur ~260) — la grande majorité des écritures générées par
    generer_ecriture_vente() ne le remplissent pas systématiquement. Le
    compte, lui, est toujours renseigné (c'est la ligne comptable
    elle-même). Même convention de signe que get_soldes_caisses()
    (services/comptabilite_service.py).

    ⭐ C'est un SOLDE (combien reste dû À une date), pas un flux — donc
    SEULE date_fin s'applique (cumul depuis toujours jusqu'à cette date,
    même convention que get_bilan()/_soldes_comptes_a_date()) : une
    créance née avant le début de la période choisie mais toujours
    impayée doit continuer à apparaître, pas de date_debut ici."""
    from sqlalchemy import text

    rows = db.session.execute(text("""
        SELECT cc.numero AS numero, cc.nom AS nom,
               SUM(l.debit) - SUM(l.credit) AS montant
        FROM lignes_ecritures l
        JOIN comptes_comptables cc ON cc.id = l.compte_id
        JOIN ecritures_comptables e ON e.id = l.ecriture_id
        WHERE e.structure_id = :structure_id AND e.statut = 'valide'
          AND (cc.nom ILIKE '%tiers-payant%' OR cc.nom ILIKE '%assurance%')
          AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        GROUP BY cc.numero, cc.nom
        HAVING SUM(l.debit) - SUM(l.credit) > 0
        ORDER BY montant DESC
    """), {'structure_id': structure_id, 'date_fin': date_fin}).fetchall()

    import re
    resultat = []
    for row in rows:
        label = re.split(r'[—/]', row.nom)[0].strip()
        resultat.append({'tiers_nom': label, 'montant': float(row.montant)})
    return resultat


@compta_bp.route('/api/dashboard/repartition-journaux')
def api_dashboard_repartition_journaux():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    return jsonify(generer_repartition_journaux(structure_id, date_debut, date_fin))


@compta_bp.route('/api/dashboard/creances-assureurs')
def api_dashboard_creances_assureurs():
    structure_id = session.get('structure_id')
    date_fin = request.args.get('date_fin')
    return jsonify(generer_creances_par_assureur(structure_id, date_fin))


# ========== TVA (3e chantier comptable : comptes auxiliaires → lettrage → TVA) ==========

def generer_declaration_tva(structure_id, date_debut, date_fin):
    """TVA collectée sur les ventes (lignes créditées sur
    COMPTE_TVA_COLLECTEE — voir generer_ecriture_vente) ET TVA déductible
    sur les achats fournisseurs (lignes débitées sur COMPTE_TVA_DEDUCTIBLE
    — voir generer_ecriture_achat_fournisseur, qui convertit toujours le
    montant saisi en TTC avant de générer l'écriture, que l'utilisateur
    ait choisi TTC ou HT à la création de l'achat). tva_nette = collectée
    - déductible (positif = à payer, négatif = crédit de TVA)."""
    from sqlalchemy import text

    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None
    params_dates = {
        'structure_id': structure_id,
        'date_debut': date_debut_obj.strftime('%Y-%m-%d') if date_debut_obj else None,
        'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None,
    }

    rows_collectee = db.session.execute(text("""
        SELECT e.date_ecriture, e.piece_justificative, e.libelle, l.credit
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON e.id = l.ecriture_id
        JOIN comptes_comptables c ON l.compte_id = c.id
        WHERE e.structure_id = :structure_id
        AND e.statut = 'valide'
        AND c.numero = :compte_tva
        AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
        AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        ORDER BY e.date_ecriture, e.id
    """), {**params_dates, 'compte_tva': COMPTE_TVA_COLLECTEE}).fetchall()

    rows_deductible = db.session.execute(text("""
        SELECT e.date_ecriture, e.piece_justificative, e.libelle, l.debit
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON e.id = l.ecriture_id
        JOIN comptes_comptables c ON l.compte_id = c.id
        WHERE e.structure_id = :structure_id
        AND e.statut = 'valide'
        AND c.numero = :compte_tva
        AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
        AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        ORDER BY e.date_ecriture, e.id
    """), {**params_dates, 'compte_tva': COMPTE_TVA_DEDUCTIBLE}).fetchall()

    lignes_collectee = [{
        'date': r.date_ecriture.strftime('%Y-%m-%d') if r.date_ecriture else '',
        'piece': r.piece_justificative or '',
        'libelle': r.libelle or '',
        'montant': float(r.credit or 0),
    } for r in rows_collectee]

    lignes_deductible = [{
        'date': r.date_ecriture.strftime('%Y-%m-%d') if r.date_ecriture else '',
        'piece': r.piece_justificative or '',
        'libelle': r.libelle or '',
        'montant': float(r.debit or 0),
    } for r in rows_deductible]

    param = ParametrageTva.get_ou_creer(structure_id)
    total_collectee = sum(l['montant'] for l in lignes_collectee)
    total_deductible = sum(l['montant'] for l in lignes_deductible)
    return {
        'lignes': lignes_collectee,
        'lignes_deductible': lignes_deductible,
        'total_collectee': round(total_collectee, 2),
        'total_deductible': round(total_deductible, 2),
        'tva_nette': round(total_collectee - total_deductible, 2),
        'taux': float(param.taux or 0),
        'assujetti': bool(param.assujetti),
    }


@compta_bp.route('/api/tva/parametrage', methods=['GET'])
def api_tva_parametrage_get():
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404
    param = ParametrageTva.get_ou_creer(structure_id)
    return jsonify({'success': True, 'assujetti': param.assujetti, 'taux': float(param.taux or 0),
                    'modifie_par': param.modifie_par or '',
                    'modifie_le': param.updated_at.strftime('%d/%m/%Y %H:%M') if param.updated_at else ''})


@compta_bp.route('/api/tva/parametrage', methods=['POST'])
def api_tva_parametrage_post():
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404

    data = request.json or {}
    taux = data.get('taux')
    try:
        taux = float(taux)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Taux invalide'}), 400
    if taux < 0 or taux > 100:
        return jsonify({'success': False, 'error': 'Le taux doit être entre 0 et 100.'}), 400

    param = ParametrageTva.get_ou_creer(structure_id)
    avant = (bool(param.assujetti), float(param.taux or 0))
    param.assujetti = bool(data.get('assujetti', False))
    param.taux = taux
    param.modifie_par = session.get('user_name', 'Utilisateur')
    db.session.commit()
    # ⭐ trace : qui a activé / désactivé la TVA, et quand (journal des mouvements)
    if avant != (param.assujetti, taux):
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='parametrage_tva',
                description=(f"TVA activée à {taux:g} % sur les prochaines ventes et achats" if param.assujetti
                             else "TVA désactivée : les prochaines ventes et achats sont enregistrés sans TVA"),
                utilisateur_nom=param.modifie_par,
            )
        except Exception as e:
            print(f"⚠️ Journal (paramétrage TVA) : {e}")
    return jsonify({'success': True, 'assujetti': param.assujetti, 'taux': taux})


# ⭐ Clôture et paiement de la TVA (patron, 2026-10-11 : « c'est à quel moment
# la somme de TVA du mois est déduite de la caisse ? il doit y avoir un moment
# où on clôture la TVA pour le mois ou une période choisie, avec respect des
# dates, et c'est à ce moment que la caisse est déduite »).
#   1. Clôture : la TVA accumulée (443 collectée, 445 récupérable, 4449 crédit
#      antérieur) jusqu'à la date de fin est soldée vers 4441 « TVA due »
#      (utils/plan_comptable_syscohada.liquidation_tva). La caisse ne bouge pas.
#   2. Paiement : Débit 4441 / Crédit caisse (ou banque) — c'est ICI que
#      l'argent sort, avec une ligne miroir dans `depenses` pour le solde de
#      caisse de l'appli (même principe que api_regler_achat_fournisseur).
# Les périodes se suivent sans trou ni chevauchement ; une écriture saisie à la
# main qui touche la TVA ne peut plus être datée dans une période clôturée.
# Une vente enregistrée après coup avec une date ancienne n'est pas perdue :
# la clôture solde le compte à sa date de fin, donc elle part dans la
# déclaration suivante (montant « régularisations antérieures »).

MODES_PAIEMENT_TVA = {'especes': 'Espèces (caisse)', 'mixx': 'Mixx by Yas (argent de la caisse)',
                      'moov': 'Moov Money (argent de la caisse)', 'banque': 'Banque (virement ou chèque)'}


def _derniere_declaration_tva(structure_id):
    return (DeclarationTva.query.filter(DeclarationTva.structure_id == structure_id, DeclarationTva.statut != 'annulee')
            .order_by(DeclarationTva.date_fin.desc(), DeclarationTva.id.desc()).first())


def _soldes_tva_a_date(structure_id, date_limite):
    """Soldes des comptes de TVA (écritures validées datées jusqu'à date_limite incluse)."""
    from sqlalchemy import text
    rows = db.session.execute(text("""
        SELECT c.numero, COALESCE(SUM(l.debit), 0) AS d, COALESCE(SUM(l.credit), 0) AS c
        FROM lignes_ecritures l
        JOIN ecritures_comptables e ON e.id = l.ecriture_id
        JOIN comptes_comptables c ON c.id = l.compte_id
        WHERE e.structure_id = :s AND e.statut = 'valide' AND e.date_ecriture <= :fin
          AND c.numero IN (:collectee, :deductible, :credit)
        GROUP BY c.numero
    """), {'s': structure_id, 'fin': date_limite, 'collectee': COMPTE_TVA_COLLECTEE,
           'deductible': COMPTE_TVA_DEDUCTIBLE, 'credit': COMPTE_CREDIT_TVA}).fetchall()
    soldes = {r.numero: (float(r.d), float(r.c)) for r in rows}
    d, c = soldes.get(COMPTE_TVA_COLLECTEE, (0, 0))
    collectee = c - d
    d, c = soldes.get(COMPTE_TVA_DEDUCTIBLE, (0, 0))
    deductible = d - c
    d, c = soldes.get(COMPTE_CREDIT_TVA, (0, 0))
    credit = d - c
    return round(collectee, 2), round(deductible, 2), round(credit, 2)


def calculer_declaration_tva(structure_id, date_debut, date_fin):
    from utils.plan_comptable_syscohada import liquidation_tva
    collectee, deductible, credit = _soldes_tva_a_date(structure_id, date_fin)
    avant_c, avant_d, _ = _soldes_tva_a_date(structure_id, date_debut - timedelta(days=1))
    lignes, a_payer, reporte = liquidation_tva(collectee, deductible, credit)
    return {'date_debut': date_debut.isoformat(), 'date_fin': date_fin.isoformat(),
            'tva_collectee': collectee, 'tva_deductible': deductible, 'credit_anterieur': credit,
            'regularisations_anterieures': round(avant_c - avant_d, 2),
            'tva_a_payer': a_payer, 'credit_reporte': reporte, 'lignes': lignes}


def _bornes_declaration_tva(structure_id, date_debut_txt, date_fin_txt):
    """(date_debut, date_fin, erreur). Après une première déclaration, la
    période commence obligatoirement le lendemain de la précédente."""
    derniere = _derniere_declaration_tva(structure_id)
    if derniere:
        date_debut = derniere.date_fin + timedelta(days=1)
    else:
        date_debut = parse_date(date_debut_txt) if date_debut_txt else None
        if not date_debut:
            return None, None, "Date de début requise."
    date_fin = parse_date(date_fin_txt) if date_fin_txt else None
    if not date_fin:
        return date_debut, None, "Date de fin requise."
    if date_fin < date_debut:
        if derniere:
            return date_debut, date_fin, (f"La période commence le {date_debut.strftime('%d/%m/%Y')} "
                                          f"(lendemain de la dernière clôture) : choisissez une date de fin après.")
        return date_debut, date_fin, "La date de fin doit être après la date de début."
    if date_fin > date.today():
        return date_debut, date_fin, "On ne peut pas clôturer une période qui n'est pas encore passée."
    return date_debut, date_fin, None


def _declaration_tva_dict(d):
    return {'id': d.id, 'date_debut': d.date_debut.isoformat(), 'date_fin': d.date_fin.isoformat(),
            'tva_collectee': float(d.tva_collectee or 0), 'tva_deductible': float(d.tva_deductible or 0),
            'credit_anterieur': float(d.credit_anterieur or 0), 'tva_a_payer': float(d.tva_a_payer or 0),
            'credit_reporte': float(d.credit_reporte or 0), 'statut': d.statut,
            'cree_par': d.cree_par or '', 'created_at': d.created_at.strftime('%d/%m/%Y %H:%M') if d.created_at else '',
            'date_paiement': d.date_paiement.isoformat() if d.date_paiement else '',
            'mode_paiement': MODES_PAIEMENT_TVA.get(d.mode_paiement, d.mode_paiement or ''),
            'reference_paiement': d.reference_paiement or '', 'paye_par': d.paye_par or '',
            'annule_par': d.annule_par or ''}


def _controle_periode_tva(structure_id, date_ecriture, lignes):
    """Message d'erreur si une écriture saisie à la main touche la TVA dans une période clôturée."""
    derniere = _derniere_declaration_tva(structure_id)
    if not derniere or not date_ecriture or date_ecriture > derniere.date_fin:
        return None
    from utils.plan_comptable_syscohada import COMPTES_TVA
    ids = [l.get('compte_id') for l in (lignes or []) if l.get('compte_id')]
    if ids and CompteComptable.query.filter(CompteComptable.structure_id == structure_id, CompteComptable.id.in_(ids),
                                            CompteComptable.numero.in_(COMPTES_TVA)).first():
        return (f"La TVA est clôturée jusqu'au {derniere.date_fin.strftime('%d/%m/%Y')} : une écriture qui touche "
                f"la TVA doit être datée après cette date (ou annulez d'abord la dernière clôture).")
    return None


@compta_bp.route('/api/tva/declarations', methods=['GET'])
def api_tva_declarations():
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404
    declarations = (DeclarationTva.query.filter_by(structure_id=structure_id)
                    .order_by(DeclarationTva.date_fin.desc(), DeclarationTva.id.desc()).limit(60).all())
    derniere = _derniere_declaration_tva(structure_id)
    aujourd_hui = date.today()
    if derniere:
        debut = derniere.date_fin + timedelta(days=1)
    else:
        debut = (aujourd_hui.replace(day=1) - timedelta(days=1)).replace(day=1)
    # fin proposée : fin du mois du début, sans dépasser aujourd'hui
    fin = min((debut.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), aujourd_hui)
    return jsonify({'success': True, 'declarations': [_declaration_tva_dict(d) for d in declarations],
                    'debut_impose': derniere is not None, 'debut_propose': debut.isoformat(),
                    'fin_proposee': fin.isoformat(), 'modes_paiement': MODES_PAIEMENT_TVA,
                    'derniere_id': derniere.id if derniere else None})


@compta_bp.route('/api/tva/declarations/apercu', methods=['GET'])
def api_tva_declaration_apercu():
    structure_id = session.get('structure_id')
    date_debut, date_fin, erreur = _bornes_declaration_tva(structure_id, request.args.get('date_debut'),
                                                           request.args.get('date_fin'))
    if erreur:
        return jsonify({'success': False, 'error': erreur}), 400
    return jsonify({'success': True, **calculer_declaration_tva(structure_id, date_debut, date_fin)})


@compta_bp.route('/api/tva/declarations', methods=['POST'])
def api_tva_declaration_cloturer():
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'Utilisateur')
    data = request.json or {}
    # verrou par structure : deux clôtures simultanées ne peuvent pas se chevaucher
    ParametrageTva.get_ou_creer(structure_id)
    ParametrageTva.query.filter_by(structure_id=structure_id).with_for_update().first()
    date_debut, date_fin, erreur = _bornes_declaration_tva(structure_id, data.get('date_debut'), data.get('date_fin'))
    if erreur:
        db.session.rollback()
        return jsonify({'success': False, 'error': erreur}), 400
    calcul = calculer_declaration_tva(structure_id, date_debut, date_fin)
    declaration = DeclarationTva(
        structure_id=structure_id, date_debut=date_debut, date_fin=date_fin,
        tva_collectee=calcul['tva_collectee'], tva_deductible=calcul['tva_deductible'],
        credit_anterieur=calcul['credit_anterieur'], tva_a_payer=calcul['tva_a_payer'],
        credit_reporte=calcul['credit_reporte'], statut='cloturee', cree_par=user_name,
    )
    db.session.add(declaration)
    db.session.flush()
    periode = f"du {date_debut.strftime('%d/%m/%Y')} au {date_fin.strftime('%d/%m/%Y')}"
    if calcul['lignes']:
        ecriture = creer_ecriture(
            structure_id=structure_id, date_ecriture=date_fin,
            libelle=f"Clôture de la TVA {periode}", lignes=calcul['lignes'], journal_code='OD',
            piece_justificative=f"TVA-{declaration.id}", auto=True,
            source_type='declaration_tva', source_id=declaration.id, user_nom=user_name,
        )
        if not ecriture:
            db.session.rollback()
            return jsonify({'success': False, 'error': "L'écriture de clôture n'a pas pu être créée."}), 500
        declaration.ecriture_id = ecriture.id
    db.session.commit()
    invalidate_cache(structure_id)
    if calcul['tva_a_payer']:
        resume = f"{int(round(calcul['tva_a_payer'])):,} FCFA à payer".replace(',', ' ')
    elif calcul['credit_reporte']:
        resume = f"crédit de {int(round(calcul['credit_reporte'])):,} FCFA reporté".replace(',', ' ')
    else:
        resume = "néant"
    try:
        from services.journal_service import JournalService
        JournalService.creer_mouvement(
            structure_id=structure_id, categorie='declaration_tva', montant=calcul['tva_a_payer'],
            description=f"TVA clôturée {periode} : {resume}", utilisateur_nom=user_name,
        )
    except Exception as e:
        print(f"⚠️ Journal (déclaration TVA) : {e}")
    return jsonify({'success': True, 'declaration': _declaration_tva_dict(declaration)})


@compta_bp.route('/api/tva/declarations/<int:declaration_id>/payer', methods=['POST'])
def api_tva_declaration_payer(declaration_id):
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'Utilisateur')
    data = request.json or {}
    declaration = DeclarationTva.query.filter_by(id=declaration_id, structure_id=structure_id).with_for_update().first()
    if not declaration:
        return jsonify({'success': False, 'error': 'Déclaration non trouvée'}), 404

    def refus(message, **extra):
        db.session.rollback()
        return jsonify({'success': False, 'error': message, **extra}), 400

    if declaration.statut != 'cloturee':
        return refus('Cette déclaration est déjà payée ou annulée.')
    montant = float(declaration.tva_a_payer or 0)
    if montant <= 0:
        return refus("Rien à payer pour cette période.")
    mode = data.get('mode_paiement') or 'especes'
    if mode not in MODES_PAIEMENT_TVA:
        return refus('Mode de paiement invalide')
    date_paiement = parse_date(data.get('date_paiement')) if data.get('date_paiement') else date.today()
    if not date_paiement or date_paiement < declaration.date_fin or date_paiement > date.today():
        return refus(f"La date de paiement doit être entre le {declaration.date_fin.strftime('%d/%m/%Y')} "
                     f"(fin de la période) et aujourd'hui.")
    par_caisse = mode != 'banque'
    if par_caisse and not data.get('force'):
        from services.comptabilite_service import solde_caisse_disponible
        solde = solde_caisse_disponible(structure_id)
        if montant > solde:
            return refus(f"Solde de caisse insuffisant (solde actuel : {int(solde)} FCFA). "
                         f"Payez depuis la banque ou confirmez quand même.", solde_insuffisant=True, solde_actuel=solde)
    reference = (data.get('reference') or '').strip()[:100]
    periode = f"du {declaration.date_debut.strftime('%d/%m/%Y')} au {declaration.date_fin.strftime('%d/%m/%Y')}"
    if par_caisse:
        # ligne miroir : le solde de caisse de l'appli (recettes − dépenses) voit la sortie d'argent ;
        # pas d'écriture de charge (la TVA n'est pas une charge : elle éteint la dette 4441)
        depense = Depense(
            structure_id=structure_id, montant=montant, motif="TVA reversée à l'État",
            description=f"Paiement de la TVA {periode}",
            moyen_paiement=mode if mode in ('mixx', 'moov') else None, reference_paiement=reference or None,
            date_paiement=date_paiement, date_depense=datetime.combine(date_paiement, datetime.now().time()),
            created_by=session.get('user_id'), created_by_nom=user_name,
        )
        db.session.add(depense)
        db.session.flush()
        declaration.depense_id = depense.id
    tresorerie = COMPTE_CAISSE if par_caisse else COMPTE_BANQUE
    ecriture = creer_ecriture(
        structure_id=structure_id, date_ecriture=date_paiement,
        libelle=f"Paiement de la TVA {periode}" + (f" — réf. {reference}" if reference else ''),
        lignes=[{'numero_compte': COMPTE_TVA_DUE, 'libelle': f"TVA payée {periode}", 'debit': montant},
                {'numero_compte': tresorerie, 'libelle': f"TVA payée {periode}", 'credit': montant}],
        journal_code='CAI' if par_caisse else 'BQU', piece_justificative=f"TVA-{declaration.id}-PAIE", auto=True,
        source_type='paiement_tva', source_id=declaration.id, user_nom=user_name,
    )
    if not ecriture:
        db.session.rollback()
        return jsonify({'success': False, 'error': "L'écriture de paiement n'a pas pu être créée."}), 500
    declaration.statut = 'payee'
    declaration.date_paiement = date_paiement
    declaration.mode_paiement = mode
    declaration.reference_paiement = reference or None
    declaration.ecriture_paiement_id = ecriture.id
    declaration.paye_par = user_name
    db.session.commit()
    invalidate_cache(structure_id)
    try:
        from services.journal_service import JournalService
        JournalService.creer_mouvement(
            structure_id=structure_id, categorie='paiement_tva', montant=montant, type_montant='sortie',
            description=f"TVA {periode} payée ({MODES_PAIEMENT_TVA[mode]})", utilisateur_nom=user_name,
        )
    except Exception as e:
        print(f"⚠️ Journal (paiement TVA) : {e}")
    return jsonify({'success': True, 'declaration': _declaration_tva_dict(declaration)})


@compta_bp.route('/api/tva/declarations/<int:declaration_id>/annuler', methods=['POST'])
def api_tva_declaration_annuler(declaration_id):
    """Annule la DERNIÈRE clôture, si elle n'est pas payée : écriture contre-passée
    (jamais supprimée), la période peut ensuite être clôturée à nouveau."""
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'Utilisateur')
    declaration = DeclarationTva.query.filter_by(id=declaration_id, structure_id=structure_id).with_for_update().first()
    if not declaration:
        return jsonify({'success': False, 'error': 'Déclaration non trouvée'}), 404
    derniere = _derniere_declaration_tva(structure_id)
    if declaration.statut != 'cloturee' or not derniere or derniere.id != declaration.id:
        db.session.rollback()
        return jsonify({'success': False, 'error': "Seule la dernière clôture, non payée, peut être annulée."}), 400
    periode = f"du {declaration.date_debut.strftime('%d/%m/%Y')} au {declaration.date_fin.strftime('%d/%m/%Y')}"
    origine = EcritureComptable.query.get(declaration.ecriture_id) if declaration.ecriture_id else None
    if origine:
        lignes = [{'numero_compte': l.compte.numero, 'libelle': f"Annulation clôture TVA {periode}",
                   'debit': float(l.credit or 0), 'credit': float(l.debit or 0)} for l in origine.lignes]
        contre = creer_ecriture(
            structure_id=structure_id, date_ecriture=declaration.date_fin,
            libelle=f"Annulation de la clôture de la TVA {periode}", lignes=lignes, journal_code='OD',
            piece_justificative=f"TVA-{declaration.id}-ANNUL", auto=True,
            source_type='annulation_declaration_tva', source_id=declaration.id, user_nom=user_name,
        )
        if not contre:
            db.session.rollback()
            return jsonify({'success': False, 'error': "L'écriture d'annulation n'a pas pu être créée."}), 500
    declaration.statut = 'annulee'
    declaration.annule_par = user_name
    declaration.annule_le = datetime.utcnow()
    db.session.commit()
    invalidate_cache(structure_id)
    try:
        from services.journal_service import JournalService
        JournalService.creer_mouvement(structure_id=structure_id, categorie='declaration_tva',
                                       description=f"Clôture de la TVA {periode} annulée", utilisateur_nom=user_name)
    except Exception as e:
        print(f"⚠️ Journal (annulation TVA) : {e}")
    return jsonify({'success': True})


# ⭐ État des charges (patron, 2026-10-11 : « n'était-il pas bon d'avoir le
# journal des dépenses ou charges ? ») — plutôt qu'un journal « DEP » (qui
# couperait le journal de caisse en deux), toutes les charges de la période
# par rubrique SYSCOHADA et par mois, quel que soit le journal d'origine
# (caisse, banque, achats, paie, OD).
RUBRIQUES_CHARGES_SYSCOHADA = {
    '60': 'Achats et variations de stocks', '61': 'Transports', '62': 'Services extérieurs',
    '63': 'Autres services extérieurs', '64': 'Impôts et taxes', '65': 'Autres charges',
    '66': 'Charges de personnel', '67': 'Frais financiers et charges assimilées',
    '68': 'Dotations aux amortissements', '69': 'Dotations aux provisions',
}


def generer_etat_charges(structure_id, date_debut, date_fin):
    from sqlalchemy import text
    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None
    rows = db.session.execute(text("""
        SELECT c.numero, c.nom, to_char(e.date_ecriture, 'YYYY-MM') AS mois,
               COALESCE(SUM(l.debit), 0) - COALESCE(SUM(l.credit), 0) AS montant
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON l.ecriture_id = e.id
        JOIN comptes_comptables c ON c.id = l.compte_id
        WHERE e.structure_id = :structure_id AND e.statut = 'valide'
          AND c.type = 'charge' AND LEFT(c.numero, 1) = '6'
          -- même exclusion que le compte de résultat (anciens comptes ad-hoc sans classe)
          AND NOT EXISTS (
              SELECT 1 FROM lignes_ecritures l2 JOIN comptes_comptables c2 ON c2.id = l2.compte_id
              WHERE l2.ecriture_id = e.id AND (c2.classe IS NULL OR c2.classe = ''))
          AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
          AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        GROUP BY c.numero, c.nom, mois
        ORDER BY c.numero, mois
    """), {'structure_id': structure_id,
           'date_debut': date_debut_obj.strftime('%Y-%m-%d') if date_debut_obj else None,
           'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None}).fetchall()

    mois = sorted({r.mois for r in rows})
    rubriques = {}
    for r in rows:
        code = r.numero[:2]
        rub = rubriques.setdefault(code, {'code': code, 'libelle': RUBRIQUES_CHARGES_SYSCOHADA.get(code, 'Autres'),
                                          'comptes': {}, 'total': 0.0, 'par_mois': {}})
        cpt = rub['comptes'].setdefault(r.numero, {'numero': r.numero, 'nom': r.nom, 'par_mois': {}, 'total': 0.0})
        montant = float(r.montant or 0)
        cpt['par_mois'][r.mois] = cpt['par_mois'].get(r.mois, 0.0) + montant
        cpt['total'] += montant
        rub['par_mois'][r.mois] = rub['par_mois'].get(r.mois, 0.0) + montant
        rub['total'] += montant
    liste = []
    for code in sorted(rubriques):
        rub = rubriques[code]
        rub['comptes'] = [rub['comptes'][n] for n in sorted(rub['comptes'])]
        liste.append(rub)
    total_par_mois = {m: sum(rub['par_mois'].get(m, 0.0) for rub in liste) for m in mois}
    return {'mois': mois, 'rubriques': liste, 'total': sum(rub['total'] for rub in liste),
            'total_par_mois': total_par_mois}


def _journal_deduit(structure_id, lignes):
    """⭐ Journal d'une écriture saisie à la main quand il n'a pas été choisi :
    déduit de ses comptes (utils/plan_comptable_syscohada.journal_pour_comptes)."""
    from utils.plan_comptable_syscohada import journal_pour_comptes
    ids = [l.get('compte_id') for l in (lignes or []) if l.get('compte_id')]
    if not ids:
        return 'OD'
    numeros = [c.numero for c in CompteComptable.query.filter(CompteComptable.structure_id == structure_id,
                                                               CompteComptable.id.in_(ids)).all()]
    return journal_pour_comptes(numeros)


def get_compte_resultat(structure_id, date_debut, date_fin):
    from sqlalchemy import text
    
    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None
    
    try:
        result = db.session.execute(text("""
            WITH ecritures_periode AS (
                SELECT 
                    e.id,
                    e.date_ecriture,
                    l.compte_id,
                    c.numero,
                    c.nom,
                    c.type,
                    l.debit,
                    l.credit
                FROM ecritures_comptables e
                JOIN lignes_ecritures l ON e.id = l.ecriture_id
                JOIN comptes_comptables c ON l.compte_id = c.id
                WHERE e.structure_id = :structure_id
                AND e.statut = 'valide'
                AND c.type IN ('charge', 'produit')
                -- ⭐ Exclut l'écriture ENTIÈRE dès qu'UNE de ses lignes touche
                -- un compte sans classe (ancien compte ad-hoc pré-SYSCOHADA,
                -- ex: "706"/"909"/"611"/"616" créés avant la migration,
                -- encore actifs et référencés par de vieilles écritures de
                -- test). Un filtre ligne par ligne laissait passer la charge
                -- (compte à classe correcte) sans sa contrepartie de
                -- trésorerie (souvent l'ancien "211"/"212", sans classe) —
                -- gonflant charges/produits sans cohérence de trésorerie.
                -- Trouvé en fiabilisant le TAFIRE (voir get_tafire ci-après).
                AND NOT EXISTS (
                    SELECT 1 FROM lignes_ecritures l2
                    JOIN comptes_comptables c2 ON c2.id = l2.compte_id
                    WHERE l2.ecriture_id = e.id AND (c2.classe IS NULL OR c2.classe = '')
                )
                AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
                AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
            )
            SELECT
                numero,
                nom,
                type,
                COALESCE(SUM(debit), 0) as total_debit,
                COALESCE(SUM(credit), 0) as total_credit
            FROM ecritures_periode
            GROUP BY numero, nom, type
            ORDER BY type, numero
        """), {
            'structure_id': structure_id,
            'date_debut': date_debut_obj.strftime('%Y-%m-%d') if date_debut_obj else None,
            'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None
        })

        rows = result.fetchall()

        charges = []
        produits = []
        total_charges = 0
        total_produits = 0

        for row in rows:
            # ⭐ FIX : ne bucketer QUE les comptes de charge/produit (la
            # requête SQL les filtre déjà) — l'ancien `else` avalait tout
            # compte non-charge (trésorerie, tiers...) dans les "produits".
            type_compte = row.type
            numero = row.numero
            nom = row.nom
            total_debit = float(row.total_debit or 0)
            total_credit = float(row.total_credit or 0)

            if type_compte == 'charge':
                solde = total_debit - total_credit
                total_charges += solde
                charges.append({'numero': numero, 'nom': nom, 'montant': solde})
            elif type_compte == 'produit':
                solde = total_credit - total_debit
                total_produits += solde
                produits.append({'numero': numero, 'nom': nom, 'montant': solde})
        
        resultat = total_produits - total_charges
        
        return {
            'charges': charges,
            'produits': produits,
            'total_charges': total_charges,
            'total_produits': total_produits,
            'resultat': resultat,
            'resultat_text': 'Bénéfice' if resultat > 0 else 'Perte'
        }
        
    except Exception as e:
        print(f"❌ Erreur get_compte_resultat: {e}")
        return {'charges': [], 'produits': [], 'total_charges': 0, 'total_produits': 0, 'resultat': 0, 'resultat_text': 'Bénéfice'}


def get_bilan(structure_id, date_fin):
    from sqlalchemy import text
    
    date_fin_obj = parse_date(date_fin) if date_fin else None
    
    try:
        result = db.session.execute(text("""
            WITH ecritures_bilan AS (
                SELECT 
                    e.id,
                    l.compte_id,
                    c.numero,
                    c.nom,
                    c.type,
                    l.debit,
                    l.credit
                FROM ecritures_comptables e
                JOIN lignes_ecritures l ON e.id = l.ecriture_id
                JOIN comptes_comptables c ON l.compte_id = c.id
                WHERE e.structure_id = :structure_id
                AND e.statut = 'valide'
                AND c.type IN ('actif', 'passif')
                -- ⭐ voir même remarque que get_compte_resultat() ci-dessus :
                -- exclut l'écriture entière dès qu'une de ses lignes touche
                -- un compte ad-hoc pré-SYSCOHADA sans classe.
                AND NOT EXISTS (
                    SELECT 1 FROM lignes_ecritures l2
                    JOIN comptes_comptables c2 ON c2.id = l2.compte_id
                    WHERE l2.ecriture_id = e.id AND (c2.classe IS NULL OR c2.classe = '')
                )
                AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
            )
            SELECT
                numero,
                nom,
                type,
                COALESCE(SUM(debit), 0) as total_debit,
                COALESCE(SUM(credit), 0) as total_credit
            FROM ecritures_bilan
            GROUP BY numero, nom, type
            ORDER BY type, numero
        """), {
            'structure_id': structure_id,
            'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None
        })

        rows = result.fetchall()

        actifs = []
        passifs = []
        capitaux_propres = []

        total_actif = 0
        total_passif = 0
        total_capitaux = 0

        # ⭐ FIX : ne bucketer QUE les comptes actif/passif (filtrés en SQL).
        # L'ancien `else` récupérait tout compte de charge/produit dont le
        # solde créditeur était positif et l'affichait comme "capitaux
        # propres", ce qui n'a aucun sens comptablement.
        for row in rows:
            type_compte = row.type
            numero = row.numero
            nom = row.nom
            total_debit = float(row.total_debit or 0)
            total_credit = float(row.total_credit or 0)

            if type_compte == 'actif':
                solde = total_debit - total_credit
                total_actif += solde
                actifs.append({'numero': numero, 'nom': nom, 'montant': solde})
            elif type_compte == 'passif':
                solde = total_credit - total_debit
                total_passif += solde
                passifs.append({'numero': numero, 'nom': nom, 'montant': solde})

        # ⭐ Le résultat de l'exercice (charges/produits, non clôturés) fait
        # partie des capitaux propres au bilan tant que l'exercice n'est pas
        # clôturé — présentation OHADA standard : une seule ligne "Résultat
        # net de l'exercice", pas le détail des comptes de charge/produit.
        # ⭐ 2026-10-22 : résultat de l'exercice de date_fin (depuis le 1er janvier) séparé des résultats des
        # exercices antérieurs (report à nouveau, 121/129) — avant, tout le cumul depuis le début était
        # présenté comme « résultat de l'exercice », faux dès le 2e exercice. Aucune écriture de clôture : les
        # comptes 6/7 des exercices passés restent cumulés, c'est ce calcul qui les range au report à nouveau.
        fin_bilan = date_fin_obj or date.today()
        debut_exercice = date(fin_bilan.year, 1, 1)
        resultat_periode = get_compte_resultat(structure_id, debut_exercice.isoformat(), fin_bilan.isoformat())
        resultat_net = resultat_periode.get('resultat', 0)
        anterieur = get_compte_resultat(structure_id, None, (debut_exercice - timedelta(days=1)).isoformat())
        report = anterieur.get('resultat', 0)
        if abs(report) > 0.5:
            capitaux_propres.append({
                'numero': '121' if report >= 0 else '129',   # SYSCOHADA : 121 report créditeur, 129 débiteur
                'nom': "Report à nouveau (résultats des exercices antérieurs)",
                'montant': report,
            })
            total_capitaux += report
        if abs(resultat_net) > 0.5:
            capitaux_propres.append({
                'numero': '131' if resultat_net >= 0 else '139',   # SYSCOHADA : 131 bénéfice, 139 perte
                'nom': f"Résultat net de l'exercice {fin_bilan.year} ({resultat_periode.get('resultat_text', '')})",
                'montant': resultat_net,
            })
            total_capitaux += resultat_net

        return {
            'actifs': actifs,
            'passifs': passifs,
            'capitaux_propres': capitaux_propres,
            'total_actif': total_actif,
            'total_passif': total_passif,
            'total_capitaux': total_capitaux,
            'total_passif_capitaux': total_passif + total_capitaux,
            # ⭐ 2026-10-22 : au centime près (avant : < 1 F — l'écart d'arrondi de 0,40 F de Valeo passait inaperçu) ;
            # l'erreur se cherche et se corrige dans l'onglet Exercice comptable (diagnostic_bilan)
            'est_equilibre': abs(round(total_actif - (total_passif + total_capitaux), 2)) < 0.01
        }
        
    except Exception as e:
        print(f"❌ Erreur get_bilan: {e}")
        return {'actifs': [], 'passifs': [], 'capitaux_propres': [], 'total_actif': 0, 'total_passif': 0, 'total_capitaux': 0, 'total_passif_capitaux': 0, 'est_equilibre': True}


# ============================================================
# TAFIRE OFFICIEL OHADA (méthode indirecte : CAFG + variation FR/BFR)
# ============================================================
# Contrairement à un simple relevé des flux de trésorerie par nature
# d'opération, le TAFIRE SYSCOHADA part du résultat comptable pour calculer
# la CAFG (Capacité d'Autofinancement Globale), puis compare le bilan de
# fin d'exercice à celui de fin d'exercice précédent pour dériver la
# variation du Fonds de Roulement (ressources et emplois durables) et du
# Besoin en Fonds de Roulement (stocks, créances, dettes circulantes).
# Codes de lignes conformes à la nomenclature officielle (FA à FN).
#
# La classification par grande masse (immobilisations, stocks, créances,
# dettes circulantes, capitaux propres, dotations, charges/produits
# financiers) s'appuie sur les colonnes `classe` et `type` du plan
# comptable — donc valable automatiquement pour tout nouveau compte
# ajouté au bon endroit, sans liste de numéros à maintenir à la main.

def _soldes_comptes_a_date(structure_id, date_fin, types=None, classes=None):
    """Solde (débit - crédit) de chaque compte, cumulé depuis toujours
    jusqu'à date_fin incluse (photo de bilan à un instant donné)."""
    from sqlalchemy import text
    filtres_type = "AND c.type = ANY(:types)" if types else ""
    filtres_classe = "AND c.classe = ANY(:classes)" if classes else ""
    params = {'structure_id': structure_id, 'date_fin': date_fin.strftime('%Y-%m-%d')}
    if types:
        params['types'] = list(types)
    if classes:
        params['classes'] = list(classes)
    rows = db.session.execute(text(f"""
        SELECT c.numero, c.nom, c.type, c.classe,
               COALESCE(SUM(l.debit), 0) AS debit, COALESCE(SUM(l.credit), 0) AS credit
        FROM comptes_comptables c
        JOIN lignes_ecritures l ON l.compte_id = c.id
        JOIN ecritures_comptables e ON e.id = l.ecriture_id
        WHERE c.structure_id = :structure_id
        AND e.structure_id = :structure_id
        AND e.statut = 'valide'
        AND e.date_ecriture <= :date_fin
        -- ⭐ exclut l'écriture entière si une de ses lignes touche un compte
        -- ad-hoc pré-SYSCOHADA sans classe (voir get_compte_resultat()).
        AND NOT EXISTS (
            SELECT 1 FROM lignes_ecritures l2
            JOIN comptes_comptables c2 ON c2.id = l2.compte_id
            WHERE l2.ecriture_id = e.id AND (c2.classe IS NULL OR c2.classe = '')
        )
        {filtres_type} {filtres_classe}
        GROUP BY c.numero, c.nom, c.type, c.classe
    """), params).fetchall()
    return {r.numero: {'nom': r.nom, 'solde': float(r.debit) - float(r.credit)} for r in rows}


def _mouvements_charges_produits(structure_id, date_debut, date_fin):
    """Charges/produits de l'exercice (pas cumulés depuis toujours,
    seulement la période) — pour la cascade des soldes intermédiaires."""
    from sqlalchemy import text
    rows = db.session.execute(text("""
        SELECT c.numero, c.nom, c.type,
               COALESCE(SUM(l.debit), 0) AS debit, COALESCE(SUM(l.credit), 0) AS credit
        FROM comptes_comptables c
        JOIN lignes_ecritures l ON l.compte_id = c.id
        JOIN ecritures_comptables e ON e.id = l.ecriture_id
        WHERE c.structure_id = :structure_id
        AND e.structure_id = :structure_id
        AND e.statut = 'valide'
        AND c.type IN ('charge', 'produit')
        -- ⭐ comme get_compte_resultat()/get_bilan() : exclut l'écriture
        -- entière si une de ses lignes touche un compte ad-hoc pré-SYSCOHADA
        -- sans classe renseignée.
        AND NOT EXISTS (
            SELECT 1 FROM lignes_ecritures l2
            JOIN comptes_comptables c2 ON c2.id = l2.compte_id
            WHERE l2.ecriture_id = e.id AND (c2.classe IS NULL OR c2.classe = '')
        )
        AND e.date_ecriture >= :date_debut AND e.date_ecriture <= :date_fin
        GROUP BY c.numero, c.nom, c.type
    """), {
        'structure_id': structure_id,
        'date_debut': date_debut.strftime('%Y-%m-%d'),
        'date_fin': date_fin.strftime('%Y-%m-%d'),
    }).fetchall()
    charges = {r.numero: float(r.debit) - float(r.credit) for r in rows if r.type == 'charge'}
    produits = {r.numero: float(r.credit) - float(r.debit) for r in rows if r.type == 'produit'}
    return charges, produits


# Comptes calculés (non décaissables/encaissables) à isoler du résultat
# d'exploitation/financier pour remonter à la CAFG.
_COMPTES_DOTATIONS = ('681', '6591')       # charges calculées
_COMPTES_REPRISES = ('7591',)              # produits calculés
_COMPTES_CHARGES_FINANCIERES = ('671',)
_COMPTES_PRODUITS_FINANCIERS = ('771',)


def _sig_et_cafg(structure_id, date_debut, date_fin):
    """Cascade des Soldes Intermédiaires de Gestion jusqu'à la CAFG.
    Pas de comptes HAO (cessions d'immobilisations, etc.) ni de
    participation des travailleurs/impôt sur les sociétés dans le plan
    comptable actuel de la structure -> traités à 0, pas ignorés en
    silence (lignes gardées dans le résultat, prêtes si ces comptes
    apparaissent un jour)."""
    charges, produits = _mouvements_charges_produits(structure_id, date_debut, date_fin)

    dotations = sum(v for n, v in charges.items() if n in _COMPTES_DOTATIONS)
    reprises = sum(v for n, v in produits.items() if n in _COMPTES_REPRISES)
    charges_financieres = sum(v for n, v in charges.items() if n in _COMPTES_CHARGES_FINANCIERES)
    produits_financiers = sum(v for n, v in produits.items() if n in _COMPTES_PRODUITS_FINANCIERS)

    charges_exploitation = sum(v for n, v in charges.items()
                                if n not in _COMPTES_DOTATIONS and n not in _COMPTES_CHARGES_FINANCIERES)
    produits_exploitation = sum(v for n, v in produits.items()
                                 if n not in _COMPTES_REPRISES and n not in _COMPTES_PRODUITS_FINANCIERS)

    ebe = produits_exploitation - charges_exploitation
    resultat_exploitation = ebe - dotations + reprises
    resultat_financier = produits_financiers - charges_financieres
    resultat_hao = 0.0            # pas de comptes 82x/83x/84x dans le plan actuel
    participation_travailleurs = 0.0
    impot_resultat = 0.0
    resultat_net = resultat_exploitation + resultat_financier + resultat_hao - participation_travailleurs - impot_resultat

    cafg = resultat_net + dotations - reprises

    return {
        'produits_exploitation': round(produits_exploitation, 2),
        'charges_exploitation': round(charges_exploitation, 2),
        'ebe': round(ebe, 2),
        'dotations_amortissements_provisions': round(dotations, 2),
        'reprises_amortissements_provisions': round(reprises, 2),
        'resultat_exploitation': round(resultat_exploitation, 2),
        'produits_financiers': round(produits_financiers, 2),
        'charges_financieres': round(charges_financieres, 2),
        'resultat_financier': round(resultat_financier, 2),
        'resultat_hao': round(resultat_hao, 2),
        'participation_travailleurs': round(participation_travailleurs, 2),
        'impot_resultat': round(impot_resultat, 2),
        'resultat_net': round(resultat_net, 2),
        'cafg': round(cafg, 2),
    }


def get_tafire(structure_id, annee):
    """TAFIRE officiel OHADA (méthode indirecte), sur l'année civile
    `annee`. N-1 = tout ce qui a été comptabilisé avant le 1er janvier de
    `annee` (peut être incomplet/nul si le système comptable vient de
    démarrer — signalé via `premier_exercice`, pas caché)."""
    date_debut_n = date(annee, 1, 1)
    date_fin_n = date(annee, 12, 31)
    date_fin_n1 = date_debut_n - timedelta(days=1)

    # --- 1) CAFG (cascade SIG sur l'année N) ---
    sig = _sig_et_cafg(structure_id, date_debut_n, date_fin_n)
    cafg = sig['cafg']

    # --- 2) Bilans de fin N et fin N-1, par grande masse ---
    soldes_n = _soldes_comptes_a_date(structure_id, date_fin_n)
    soldes_n1 = _soldes_comptes_a_date(structure_id, date_fin_n1)
    premier_exercice = len(soldes_n1) == 0

    def masse(soldes, predicat):
        return sum(v['solde'] for numero, v in soldes.items() if predicat(numero))

    # Comptes réellement présents dans le plan de CETTE structure, pour
    # savoir à quelle classe/type appartient chaque numéro rencontré.
    comptes_meta = {c.numero: c for c in CompteComptable.query.filter_by(structure_id=structure_id).all()}

    def est(numero, classe=None, type_=None, prefixe_exclu=None):
        c = comptes_meta.get(numero)
        if not c:
            return False
        if classe and c.classe != classe:
            return False
        if type_ and c.type != type_:
            return False
        if prefixe_exclu and numero.startswith(prefixe_exclu):
            return False
        return True

    immobilisations_brutes_n = masse(soldes_n, lambda n: est(n, classe='2') and not n.startswith('28'))
    immobilisations_brutes_n1 = masse(soldes_n1, lambda n: est(n, classe='2') and not n.startswith('28'))
    capitaux_propres_n = masse(soldes_n, lambda n: est(n, classe='1'))
    capitaux_propres_n1 = masse(soldes_n1, lambda n: est(n, classe='1'))
    # Capitaux propres = comptes de passif (solde créditeur -> négatif en
    # debit-credit) : on les remet en valeur positive pour lire "combien
    # de ressources propres", comme au bilan.
    capitaux_propres_n = -capitaux_propres_n
    capitaux_propres_n1 = -capitaux_propres_n1

    stocks_n = masse(soldes_n, lambda n: est(n, classe='3'))
    stocks_n1 = masse(soldes_n1, lambda n: est(n, classe='3'))
    creances_n = masse(soldes_n, lambda n: est(n, classe='4', type_='actif'))
    creances_n1 = masse(soldes_n1, lambda n: est(n, classe='4', type_='actif'))
    dettes_circulantes_n = -masse(soldes_n, lambda n: est(n, classe='4', type_='passif'))
    dettes_circulantes_n1 = -masse(soldes_n1, lambda n: est(n, classe='4', type_='passif'))
    tresorerie_n = masse(soldes_n, lambda n: est(n, classe='5'))
    tresorerie_n1 = masse(soldes_n1, lambda n: est(n, classe='5'))

    # --- 3) Tableau emplois-ressources (variation du Fonds de Roulement) ---
    # Comptes 101 (capital)/131 (report à nouveau) uniquement (classe '1'
    # sans 120/129, jamais mouvementés hors clôture formelle) : leur
    # variation ne reflète QUE des apports/retraits réels de capital, pas
    # le résultat de l'exercice (qui n'y transite jamais dans ce système
    # tant que l'exercice n'est pas formellement clôturé) — donc rien à
    # neutraliser ici, contrairement à un bilan où le résultat est déjà
    # intégré aux capitaux propres.
    variation_capital = capitaux_propres_n - capitaux_propres_n1

    fa_autofinancement = cafg  # pas de distribution de dividendes suivie -> autofinancement = CAFG
    fb_cessions_immobilisations = 0.0   # pas de comptes HAO de cession dans le plan actuel
    fd_augmentation_capital = max(0.0, variation_capital)
    ff_nouveaux_emprunts = 0.0           # pas de comptes de dettes financières (classe 16) dans le plan actuel
    ressources_durables = fa_autofinancement + fb_cessions_immobilisations + fd_augmentation_capital + ff_nouveaux_emprunts

    fi_acquisitions_immobilisations = max(0.0, immobilisations_brutes_n - immobilisations_brutes_n1)
    fk_remboursement_capitaux = max(0.0, -variation_capital)
    fl_remboursement_emprunts = 0.0
    emplois_durables = fi_acquisitions_immobilisations + fk_remboursement_capitaux + fl_remboursement_emprunts

    variation_fr = ressources_durables - emplois_durables

    # --- 4) Variation du Besoin en Fonds de Roulement ---
    variation_stocks = stocks_n - stocks_n1
    variation_creances = creances_n - creances_n1
    variation_dettes_circulantes = dettes_circulantes_n - dettes_circulantes_n1
    variation_bfr = variation_stocks + variation_creances - variation_dettes_circulantes

    # --- 5) Variation de trésorerie (dérivée) vs réelle (constatée) ---
    variation_tresorerie_derivee = variation_fr - variation_bfr
    variation_tresorerie_reelle = tresorerie_n - tresorerie_n1
    ecart_non_affecte = round(variation_tresorerie_reelle - variation_tresorerie_derivee, 2)

    return {
        'annee': annee,
        'premier_exercice': premier_exercice,
        'sig': sig,
        'bilan_n1': {
            'immobilisations_brutes': round(immobilisations_brutes_n1, 2),
            'capitaux_propres': round(capitaux_propres_n1, 2),
            'stocks': round(stocks_n1, 2), 'creances': round(creances_n1, 2),
            'dettes_circulantes': round(dettes_circulantes_n1, 2), 'tresorerie': round(tresorerie_n1, 2),
        },
        'bilan_n': {
            'immobilisations_brutes': round(immobilisations_brutes_n, 2),
            'capitaux_propres': round(capitaux_propres_n, 2),
            'stocks': round(stocks_n, 2), 'creances': round(creances_n, 2),
            'dettes_circulantes': round(dettes_circulantes_n, 2), 'tresorerie': round(tresorerie_n, 2),
        },
        'emplois_ressources': {
            'fa_autofinancement': round(fa_autofinancement, 2),
            'fb_cessions_immobilisations': round(fb_cessions_immobilisations, 2),
            'fd_augmentation_capital': round(fd_augmentation_capital, 2),
            'ff_nouveaux_emprunts': round(ff_nouveaux_emprunts, 2),
            'ressources_durables': round(ressources_durables, 2),
            'fi_acquisitions_immobilisations': round(fi_acquisitions_immobilisations, 2),
            'fk_remboursement_capitaux': round(fk_remboursement_capitaux, 2),
            'fl_remboursement_emprunts': round(fl_remboursement_emprunts, 2),
            'emplois_durables': round(emplois_durables, 2),
            'variation_fr': round(variation_fr, 2),
        },
        'bfr': {
            'variation_stocks': round(variation_stocks, 2),
            'variation_creances': round(variation_creances, 2),
            'variation_dettes_circulantes': round(variation_dettes_circulantes, 2),
            'variation_bfr': round(variation_bfr, 2),
        },
        'tresorerie_debut': round(tresorerie_n1, 2),
        'tresorerie_fin': round(tresorerie_n, 2),
        'variation_tresorerie': round(variation_tresorerie_reelle, 2),
        'variation_tresorerie_derivee': round(variation_tresorerie_derivee, 2),
        'ecart_non_affecte': ecart_non_affecte,
        'coherent': abs(ecart_non_affecte) < 1,
    }


# ============================================================
# RAPPROCHEMENT BANCAIRE
# ============================================================

def _compte_banque_par_defaut(structure_id):
    """Compte de trésorerie utilisé quand un relevé n'a pas de compte_id
    explicite (anciens relevés créés avant le support multi-comptes)."""
    return CompteComptable.query.filter_by(structure_id=structure_id, numero=COMPTE_BANQUE).first()


@compta_bp.route('/api/rapprochement/comptes')
def api_rapprochement_comptes():
    """⭐ NOUVEAU : liste des comptes de trésorerie (classe 5 — banques et
    caisses) disponibles pour le rapprochement, pour gérer plusieurs comptes
    bancaires séparément."""
    structure_id = session.get('structure_id')
    comptes = CompteComptable.query.filter(
        CompteComptable.structure_id == structure_id,
        CompteComptable.classe == '5',
        CompteComptable.actif == True,
    ).order_by(CompteComptable.numero).all()

    soldes = CompteComptable.soldes([c.id for c in comptes])   # ⭐ 2026-10-18 : une requête pour tous
    return jsonify([{
        'id': c.id, 'numero': c.numero, 'nom': c.nom,
        'solde_comptable': float(soldes.get(c.id) or 0),
    } for c in comptes])


@compta_bp.route('/api/rapprochement/releves', methods=['GET'])
def api_get_releves():
    structure_id = session.get('structure_id')

    compte_id_filtre = request.args.get('compte_id', type=int)

    query = ReleveBancaire.query.filter_by(structure_id=structure_id)
    if compte_id_filtre:
        query = query.filter_by(compte_id=compte_id_filtre)

    # ⭐ 2026-10-18 : lignes des relevés et comptes chargés ensemble (avant : requêtes par relevé)
    from sqlalchemy.orm import selectinload
    releves = query.options(selectinload(ReleveBancaire.lignes)).order_by(ReleveBancaire.date_releve.desc()).all()
    ids_comptes = list({r.compte_id for r in releves if r.compte_id})
    comptes_releves = {c.id: c for c in CompteComptable.query.filter(CompteComptable.id.in_(ids_comptes)).all()} \
        if ids_comptes else {}

    result = []
    for r in releves:
        compte = r.compte_id and comptes_releves.get(r.compte_id)
        result.append({
            'id': r.id,
            'date_releve': r.date_releve.strftime('%Y-%m-%d') if r.date_releve else '',
            'compte_id': r.compte_id,
            'compte_numero': compte.numero if compte else COMPTE_BANQUE,
            'compte_nom': compte.nom if compte else 'Banque (compte par défaut)',
            'solde_initial': float(r.solde_initial),
            'solde_final': float(r.solde_final),
            'total_credits': float(r.total_credits) if r.total_credits else 0,
            'total_debits': float(r.total_debits) if r.total_debits else 0,
            'statut': r.statut,
            'created_by': r.created_by or '-',
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
            'nb_lignes': len(r.lignes),
            'nb_rapproche': sum(1 for l in r.lignes if l.rapproche)
        })

    return jsonify(result)


@compta_bp.route('/api/rapprochement/releves', methods=['POST'])
def api_creer_releve():
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        date_releve = parse_date(data.get('date_releve'))
        if not date_releve:
            return jsonify({'error': 'Format de date invalide'}), 400

        compte_id = data.get('compte_id')
        if compte_id:
            compte = CompteComptable.query.filter_by(id=compte_id, structure_id=structure_id).first()
            if not compte:
                return jsonify({'error': 'Compte de trésorerie invalide'}), 400
        else:
            compte = _compte_banque_par_defaut(structure_id)
            compte_id = compte.id if compte else None

        releve = ReleveBancaire(
            structure_id=structure_id,
            compte_id=compte_id,
            date_releve=date_releve,
            solde_initial=data.get('solde_initial', 0),
            created_by=user_name,
            statut='brouillon'
        )
        db.session.add(releve)
        db.session.flush()
        
        total_credits = 0
        total_debits = 0
        solde_courant = float(data.get('solde_initial', 0))
        
        for ligne_data in data.get('lignes', []):
            debit = float(ligne_data.get('debit', 0))
            credit = float(ligne_data.get('credit', 0))
            solde_courant += credit - debit
            total_credits += credit
            total_debits += debit
            
            date_operation = parse_date(ligne_data.get('date_operation'))
            if not date_operation:
                date_operation = date_releve
            
            ligne = LigneReleve(
                releve_id=releve.id,
                date_operation=date_operation,
                libelle=ligne_data.get('libelle'),
                reference=ligne_data.get('reference', ''),
                debit=debit,
                credit=credit,
                solde=solde_courant
            )
            db.session.add(ligne)
        
        releve.total_credits = total_credits
        releve.total_debits = total_debits
        releve.solde_final = solde_courant
        
        db.session.commit()
        
        return jsonify({'success': True, 'id': releve.id, 'solde_final': solde_courant})
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur: {e}")
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/rapprochement/releves/<int:releve_id>/lignes')
def api_get_lignes_releve(releve_id):
    structure_id = session.get('structure_id')
    
    releve = ReleveBancaire.query.filter_by(id=releve_id, structure_id=structure_id).first()
    
    if not releve:
        return jsonify({'error': 'Releve non trouve'}), 404
    
    result = []
    for ligne in releve.lignes:
        result.append({
            'id': ligne.id,
            'date_operation': ligne.date_operation.strftime('%Y-%m-%d') if ligne.date_operation else '',
            'libelle': ligne.libelle,
            'reference': ligne.reference or '',
            'debit': float(ligne.debit),
            'credit': float(ligne.credit),
            'solde': float(ligne.solde),
            'est_rapproche': ligne.rapproche,
            'ecriture_id': ligne.ecriture_id
        })
    
    return jsonify(result)


@compta_bp.route('/api/rapprochement/releves/<int:releve_id>/rapprocher', methods=['POST'])
def api_rapprocher_releve(releve_id):
    """Rapprochement automatique, en 2 passes :
    1) date exacte + montant exact (le plus fiable)
    2) montant exact mais date à ± TOLERANCE_JOURS (la banque poste souvent
       avec un décalage de quelques jours par rapport à la date de l'écriture)
    Tout ce qui n'est pas apparié automatiquement reste disponible pour une
    association manuelle (voir /lignes/<id>/associer)."""
    TOLERANCE_JOURS = 3
    try:
        structure_id = session.get('structure_id')

        releve = ReleveBancaire.query.filter_by(id=releve_id, structure_id=structure_id).first()

        if not releve:
            return jsonify({'error': 'Releve non trouve'}), 404

        # ⭐ FIX : le compte "212" (ancienne numérotation) n'existe plus
        # depuis la migration SYSCOHADA — on utilise le compte du relevé
        # (multi-comptes) ou "521 Banque" par défaut pour les anciens relevés.
        if releve.compte_id:
            compte_bancaire = CompteComptable.query.get(releve.compte_id)
        else:
            compte_bancaire = _compte_banque_par_defaut(structure_id)

        if not compte_bancaire:
            return jsonify({'error': 'Compte de trésorerie introuvable pour ce relevé'}), 400

        ecritures = db.session.query(EcritureComptable, LigneEcriture).join(
            LigneEcriture, EcritureComptable.id == LigneEcriture.ecriture_id
        ).filter(
            EcritureComptable.structure_id == structure_id,
            EcritureComptable.statut == 'valide',
            LigneEcriture.compte_id == compte_bancaire.id
        ).order_by(EcritureComptable.date_ecriture).all()

        # Écritures déjà rapprochées (sur ce compte, tous relevés confondus) à exclure
        deja_utilisees = {
            l.ecriture_id for l in LigneReleve.query.join(ReleveBancaire).filter(
                ReleveBancaire.compte_id == compte_bancaire.id,
                LigneReleve.rapproche == True,
                LigneReleve.ecriture_id != None,
            ).all()
        }

        candidats = []
        for ecriture, ligne in ecritures:
            if ecriture.id in deja_utilisees:
                continue
            montant = float(ligne.debit) if ligne.debit > 0 else float(ligne.credit)
            candidats.append({'ecriture_id': ecriture.id, 'date': ecriture.date_ecriture, 'montant': montant})

        nb_rapproche = 0
        nb_pass1 = 0

        # --- Passe 1 : date exacte + montant exact ---
        for ligne in releve.lignes:
            if ligne.rapproche:
                continue
            montant = float(ligne.debit) if ligne.debit > 0 else float(ligne.credit)
            for c in candidats:
                if c['ecriture_id'] in deja_utilisees:
                    continue
                if c['date'] == ligne.date_operation and abs(c['montant'] - montant) < 0.5:
                    ligne.rapproche = True
                    ligne.ecriture_id = c['ecriture_id']
                    deja_utilisees.add(c['ecriture_id'])
                    nb_rapproche += 1
                    nb_pass1 += 1
                    break

        # --- Passe 2 : montant exact, date à ± TOLERANCE_JOURS ---
        for ligne in releve.lignes:
            if ligne.rapproche:
                continue
            montant = float(ligne.debit) if ligne.debit > 0 else float(ligne.credit)
            meilleur = None
            for c in candidats:
                if c['ecriture_id'] in deja_utilisees:
                    continue
                if abs(c['montant'] - montant) >= 0.5:
                    continue
                ecart_jours = abs((c['date'] - ligne.date_operation).days)
                if ecart_jours <= TOLERANCE_JOURS and (meilleur is None or ecart_jours < meilleur[1]):
                    meilleur = (c, ecart_jours)
            if meilleur:
                c = meilleur[0]
                ligne.rapproche = True
                ligne.ecriture_id = c['ecriture_id']
                deja_utilisees.add(c['ecriture_id'])
                nb_rapproche += 1

        total_lignes = len(releve.lignes)
        total_rapproche = sum(1 for l in releve.lignes if l.rapproche)

        if total_rapproche == total_lignes and total_lignes > 0:
            releve.statut = 'en_attente'

        db.session.commit()

        return jsonify({
            'success': True,
            'nb_rapproche': nb_rapproche,
            'nb_rapproche_exact': nb_pass1,
            'nb_rapproche_tolerance': nb_rapproche - nb_pass1,
            'total_lignes': total_lignes,
            'total_rapproche': total_rapproche,
            'statut': releve.statut
        })

    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur: {e}")
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/rapprochement/releves/<int:releve_id>/lignes/<int:ligne_id>/candidats')
def api_candidats_association(releve_id, ligne_id):
    """⭐ NOUVEAU : liste des écritures candidates (même compte, montant
    identique, non déjà rapprochées) pour associer manuellement une ligne de
    relevé qui n'a pas été appariée automatiquement."""
    structure_id = session.get('structure_id')
    releve = ReleveBancaire.query.filter_by(id=releve_id, structure_id=structure_id).first()
    if not releve:
        return jsonify({'error': 'Releve non trouve'}), 404
    ligne = LigneReleve.query.filter_by(id=ligne_id, releve_id=releve_id).first()
    if not ligne:
        return jsonify({'error': 'Ligne non trouvee'}), 404

    compte = CompteComptable.query.get(releve.compte_id) if releve.compte_id else _compte_banque_par_defaut(structure_id)
    if not compte:
        return jsonify([])

    montant = float(ligne.debit) if ligne.debit > 0 else float(ligne.credit)
    deja_utilisees = {
        l.ecriture_id for l in LigneReleve.query.filter(
            LigneReleve.rapproche == True, LigneReleve.ecriture_id != None
        ).all()
    }

    ecritures = db.session.query(EcritureComptable, LigneEcriture).join(
        LigneEcriture, EcritureComptable.id == LigneEcriture.ecriture_id
    ).filter(
        EcritureComptable.structure_id == structure_id,
        EcritureComptable.statut == 'valide',
        LigneEcriture.compte_id == compte.id,
    ).order_by(EcritureComptable.date_ecriture.desc()).all()

    result = []
    for ecriture, l in ecritures:
        if ecriture.id in deja_utilisees and ecriture.id != ligne.ecriture_id:
            continue
        m = float(l.debit) if l.debit > 0 else float(l.credit)
        result.append({
            'ecriture_id': ecriture.id,
            'date': ecriture.date_ecriture.strftime('%Y-%m-%d'),
            'libelle': ecriture.libelle,
            'piece': ecriture.piece_justificative or '',
            'montant': m,
            'correspond_exactement': abs(m - montant) < 0.5,
        })

    result.sort(key=lambda r: (not r['correspond_exactement'], r['date']), reverse=False)
    return jsonify(result)


@compta_bp.route('/api/rapprochement/releves/<int:releve_id>/lignes/<int:ligne_id>/associer', methods=['POST'])
def api_associer_ligne(releve_id, ligne_id):
    """Association manuelle (ou modification d'une association) d'une
    ligne de relevé à une écriture comptable précise."""
    try:
        structure_id = session.get('structure_id')
        releve = ReleveBancaire.query.filter_by(id=releve_id, structure_id=structure_id).first()
        if not releve:
            return jsonify({'error': 'Releve non trouve'}), 404
        ligne = LigneReleve.query.filter_by(id=ligne_id, releve_id=releve_id).first()
        if not ligne:
            return jsonify({'error': 'Ligne non trouvee'}), 404

        ecriture_id = request.json.get('ecriture_id')
        ecriture = EcritureComptable.query.filter_by(id=ecriture_id, structure_id=structure_id).first()
        if not ecriture:
            return jsonify({'error': 'Ecriture non trouvee'}), 404

        ligne.rapproche = True
        ligne.ecriture_id = ecriture.id
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/rapprochement/releves/<int:releve_id>/lignes/<int:ligne_id>/dissocier', methods=['POST'])
def api_dissocier_ligne(releve_id, ligne_id):
    """Annule un rapprochement (manuel ou automatique) sur une ligne."""
    try:
        structure_id = session.get('structure_id')
        releve = ReleveBancaire.query.filter_by(id=releve_id, structure_id=structure_id).first()
        if not releve:
            return jsonify({'error': 'Releve non trouve'}), 404
        ligne = LigneReleve.query.filter_by(id=ligne_id, releve_id=releve_id).first()
        if not ligne:
            return jsonify({'error': 'Ligne non trouvee'}), 404

        ligne.rapproche = False
        ligne.ecriture_id = None
        if releve.statut == 'en_attente':
            releve.statut = 'brouillon'
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/rapprochement/releves/import', methods=['POST'])
def api_importer_releve():
    """⭐ NOUVEAU : import d'un relevé bancaire depuis un fichier CSV ou
    Excel (.xlsx) au lieu de saisir chaque ligne à la main.

    Colonnes attendues (insensible à la casse, ordre libre) : une colonne
    date, une colonne libellé, et soit deux colonnes débit/crédit séparées,
    soit une seule colonne "montant" (négatif = débit, positif = crédit).
    """
    try:
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')

        fichier = request.files.get('fichier')
        if not fichier or not fichier.filename:
            return jsonify({'error': 'Aucun fichier fourni'}), 400

        date_releve = parse_date(request.form.get('date_releve')) or date.today()
        solde_initial = float(request.form.get('solde_initial', 0) or 0)
        compte_id = request.form.get('compte_id', type=int)
        if compte_id:
            compte = CompteComptable.query.filter_by(id=compte_id, structure_id=structure_id).first()
            if not compte:
                return jsonify({'error': 'Compte de trésorerie invalide'}), 400
        else:
            compte = _compte_banque_par_defaut(structure_id)
            compte_id = compte.id if compte else None

        nom_fichier = fichier.filename.lower()
        lignes_brutes = []  # liste de dicts {date, libelle, reference, debit, credit}

        def _trouver_colonne(en_tetes, *candidats):
            for i, h in enumerate(en_tetes):
                h_norm = (h or '').strip().lower()
                if any(c in h_norm for c in candidats):
                    return i
            return None

        def _to_float_safe(v):
            if v is None or v == '':
                return 0.0
            try:
                return float(str(v).replace(' ', '').replace(',', '.'))
            except ValueError:
                return 0.0

        if nom_fichier.endswith('.xlsx') or nom_fichier.endswith('.xls'):
            import openpyxl
            wb = openpyxl.load_workbook(fichier, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return jsonify({'error': 'Fichier vide'}), 400
            entetes = [str(c) if c is not None else '' for c in rows[0]]
            data_rows = rows[1:]
        else:
            import csv as csv_module
            import io
            contenu = fichier.read().decode('utf-8-sig', errors='replace')
            delimiter = ';' if contenu.count(';') > contenu.count(',') else ','
            reader = csv_module.reader(io.StringIO(contenu), delimiter=delimiter)
            rows = list(reader)
            if not rows:
                return jsonify({'error': 'Fichier vide'}), 400
            entetes = rows[0]
            data_rows = rows[1:]

        idx_date = _trouver_colonne(entetes, 'date')
        idx_libelle = _trouver_colonne(entetes, 'libell', 'description', 'intitul', 'motif')
        idx_ref = _trouver_colonne(entetes, 'ref', 'piece', 'pièce')
        idx_debit = _trouver_colonne(entetes, 'debit', 'débit')
        idx_credit = _trouver_colonne(entetes, 'credit', 'crédit')
        idx_montant = _trouver_colonne(entetes, 'montant', 'amount')

        if idx_date is None:
            return jsonify({'error': "Colonne 'date' introuvable dans le fichier. En-têtes lus : " + ', '.join(entetes)}), 400

        for row in data_rows:
            if not row or all(c in (None, '') for c in row):
                continue
            raw_date = row[idx_date] if idx_date is not None and idx_date < len(row) else None
            if hasattr(raw_date, 'strftime'):
                date_operation = raw_date.date() if hasattr(raw_date, 'date') else raw_date
            else:
                date_operation = parse_date(str(raw_date)) if raw_date else None
            if not date_operation:
                continue

            libelle = str(row[idx_libelle]) if idx_libelle is not None and idx_libelle < len(row) and row[idx_libelle] else 'Opération'
            reference = str(row[idx_ref]) if idx_ref is not None and idx_ref < len(row) and row[idx_ref] else ''

            if idx_debit is not None and idx_credit is not None:
                debit = _to_float_safe(row[idx_debit] if idx_debit < len(row) else 0)
                credit = _to_float_safe(row[idx_credit] if idx_credit < len(row) else 0)
            elif idx_montant is not None:
                montant = _to_float_safe(row[idx_montant] if idx_montant < len(row) else 0)
                debit = abs(montant) if montant < 0 else 0
                credit = montant if montant > 0 else 0
            else:
                continue

            lignes_brutes.append({
                'date_operation': date_operation, 'libelle': libelle,
                'reference': reference, 'debit': debit, 'credit': credit,
            })

        if not lignes_brutes:
            return jsonify({'error': 'Aucune ligne exploitable trouvée dans le fichier'}), 400

        releve = ReleveBancaire(
            structure_id=structure_id, compte_id=compte_id, date_releve=date_releve,
            solde_initial=solde_initial, created_by=user_name, statut='brouillon',
        )
        db.session.add(releve)
        db.session.flush()

        solde_courant = solde_initial
        total_credits = 0.0
        total_debits = 0.0
        for l in sorted(lignes_brutes, key=lambda x: x['date_operation']):
            solde_courant += l['credit'] - l['debit']
            total_credits += l['credit']
            total_debits += l['debit']
            db.session.add(LigneReleve(
                releve_id=releve.id, date_operation=l['date_operation'], libelle=l['libelle'],
                reference=l['reference'], debit=l['debit'], credit=l['credit'], solde=solde_courant,
            ))

        releve.total_credits = total_credits
        releve.total_debits = total_debits
        releve.solde_final = solde_courant
        db.session.commit()

        return jsonify({'success': True, 'id': releve.id, 'nb_lignes': len(lignes_brutes), 'solde_final': solde_courant})

    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur import relevé: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@compta_bp.route('/api/rapprochement/releves/<int:releve_id>/valider', methods=['POST'])
def api_valider_releve(releve_id):
    try:
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        releve = ReleveBancaire.query.filter_by(id=releve_id, structure_id=structure_id).first()
        
        if not releve:
            return jsonify({'error': 'Releve non trouve'}), 404
        
        total_lignes = len(releve.lignes)
        total_rapproche = sum(1 for l in releve.lignes if l.rapproche)
        
        if total_lignes > 0 and total_rapproche < total_lignes:
            return jsonify({
                'error': f'Impossible de valider : {total_lignes - total_rapproche} ligne(s) non rapprochee(s)'
            }), 400
        
        releve.statut = 'valide'
        releve.valide_par = user_name
        releve.date_validation = date.today()
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Releve valide avec succes'})
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# INITIALISATION PLAN COMPTABLE
# ============================================================

@compta_bp.route('/api/init-comptes', methods=['POST'])
def api_init_comptes():
    """Initialise (ou complète) le plan comptable SYSCOHADA de la structure.
    Voir utils/plan_comptable_syscohada.py pour la nomenclature de référence,
    partagée avec scripts/seed_plan_comptable_syscohada.py."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvee'}), 400

    from scripts.seed_plan_comptable_syscohada import seed_pour_structure
    seed_pour_structure(structure_id)
    invalidate_cache(structure_id)

    return jsonify({'success': True})

# routes/comptabilite.py - Ajouter cette route

# routes/comptabilite.py - Route simplifiée

def _donnees_rapport(type_rapport, structure_id, date_debut, date_fin, journal_code=None, compte_id=None,
                      tiers_type=None, tiers_id=None):
    """Point d'entrée commun (imprimable ET export TXT) — construit les
    données d'un rapport en respectant les mêmes filtres que l'écran
    (journal sélectionné, compte unique pour le grand livre, tiers pour le
    grand livre auxiliaire). ⭐ FIX : auparavant, print_rapport() ignorait
    journal_code/compte_id, donc "Imprimer" ressortait TOUJOURS tous les
    journaux mélangés même si un seul était filtré à l'écran."""
    if type_rapport == 'journal':
        data = generer_journal(structure_id, date_debut, date_fin, journal_code)
        # ⭐ FIX : les valeurs de EcritureComptable.JOURNAUX commencent déjà
        # par "Journal " (ex: "Journal des ventes") — le préfixer une 2e
        # fois ici donnait "Journal Journal des ventes" dans l'en-tête
        # imprimé/exporté.
        titre = EcritureComptable.JOURNAUX.get(journal_code, journal_code) if journal_code else "Journal comptable (tous journaux)"
    elif type_rapport == 'grand_livre':
        data = generer_grand_livre(structure_id, date_debut, date_fin, compte_id, tiers_type, tiers_id)
        if tiers_id:
            nom_tiers = data[0]['tiers_nom'] if data else None
            titre = f"Grand livre auxiliaire — {nom_tiers or 'tiers'}"
        elif compte_id:
            compte = CompteComptable.query.get(compte_id)
            titre = f"Grand livre — {compte.numero} {compte.nom}" if compte else "Grand livre"
        else:
            titre = "Grand livre (tous comptes)"
    elif type_rapport == 'balance':
        data = generer_balance(structure_id, date_debut, date_fin)
        titre = "Balance comptable"
    elif type_rapport == 'tva':
        data = generer_declaration_tva(structure_id, date_debut, date_fin)
        titre = "Déclaration TVA"
    elif type_rapport == 'resultat':
        data = get_compte_resultat(structure_id, date_debut, date_fin)
        titre = "Compte de résultat"
    elif type_rapport == 'bilan':
        data = get_bilan(structure_id, date_fin)
        titre = "Bilan comptable"
    elif type_rapport == 'charges':
        data = generer_etat_charges(structure_id, date_debut, date_fin)
        titre = "État des charges (SYSCOHADA)"
    elif type_rapport == 'exercice':
        annee = _annee_demandee(str(date_fin or date_debut or '')[:4]) or datetime.now().year
        data = get_apercu_exercice(structure_id, annee)
        titre = f"États financiers de l'exercice {annee}"
    else:
        return None, None
    return data, titre


@compta_bp.route('/rapport/print/<type_rapport>')
def print_rapport(type_rapport):
    """Génère une version imprimable d'un rapport (PDF via impression)"""
    structure_id = session.get('structure_id')

    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('comptabilite.index'))

    # Récupérer les paramètres
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    journal_code = request.args.get('journal_code') or None
    compte_id = request.args.get('compte_id', type=int)
    tiers_type = request.args.get('tiers_type') or None
    tiers_id = request.args.get('tiers_id', type=int)

    data, titre = _donnees_rapport(type_rapport, structure_id, date_debut, date_fin, journal_code, compte_id,
                                    tiers_type, tiers_id)
    if data is None:
        flash('Type de rapport invalide', 'danger')
        return redirect(url_for('comptabilite.index'))

    # ⭐ PAS DE RECHERCHE DE STRUCTURE - On passe juste les données
    return render_template('comptabilite/print_rapport.html',
                         type_rapport=type_rapport,
                         titre=titre,
                         data=data,
                         date_debut=date_debut,
                         date_fin=date_fin,
                         now=datetime.now())


def _fmt_montant(m):
    return f"{m:,.0f}".replace(',', ' ')


def _fmt_ecart(m):
    """Écart en valeur absolue : les centimes restent visibles (« 0,40 »), sinon un écart de 0,40 F s'afficherait « 0 »."""
    m = abs(round(m, 2))
    return _fmt_montant(m) if m == int(m) else f"{m:,.2f}".replace(',', ' ').replace('.', ',')


def _csv_champ(v):
    """Échappe un champ texte pour le CSV (séparateur ';', comme les
    autres exports CSV de l'appli — voir gestion_stock.html) : entouré de
    guillemets, guillemets internes doublés. Sinon un libellé contenant
    lui-même un ';' casserait l'alignement des colonnes suivantes."""
    s = '' if v is None else str(v)
    return '"' + s.replace('"', '""') + '"'


def _csv_montant(m):
    """Nombre brut (le FCFA n'a pas de sous-unité, donc pas de décimales),
    SANS séparateur de milliers — un montant formaté "125 000" serait lu
    comme du texte par Excel, pas comme un nombre utilisable dans une
    somme. Vide si nul, comme à l'écran."""
    return str(int(round(m))) if m else ''


def _csv_date(d):
    """Date à 6 chiffres JJMMAA, sans séparateur (ex: '2026-09-30' ->
    '300926') — porté depuis GHP (2026-09-30). Distinct du FEC, qui doit
    rester AAAAMMJJ (norme DGFiP, jamais à modifier)."""
    s = '' if d is None else str(d)
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return f"{s[8:10]}{s[5:7]}{s[2:4]}"
    return s


@compta_bp.route('/rapport/export-txt/<type_rapport>')
def export_rapport_txt(type_rapport):
    """Export tableur (.csv, séparateur ';') d'UN rapport à la fois, avec
    les mêmes filtres que l'écran (journal sélectionné, compte unique,
    dates) — demandé explicitement : pouvoir exporter chaque journal
    individuellement, le grand livre, la balance, le résultat, le bilan,
    plutôt qu'un seul export mélangeant tout.

    ⭐ Anciennement un texte à colonnes de largeur FIXE (espaces de
    remplissage) pensé pour être lu/imprimé tel quel — mais ouvert dans
    Excel, une largeur fixe n'est PAS un vrai séparateur de colonnes : tout
    atterrit dans une seule colonne (bug remonté). Le PDF (imprimerRapportPDF,
    /rapport/print/<type>) couvre déjà le besoin d'impression ; cet export-ci
    sert en pratique à être repris dans un tableur, donc il doit l'être
    réellement — d'où le passage en CSV point-virgule, avec somme(BOM UTF-8
    en tête pour qu'Excel reconnaisse direct l'encodage et les accents)."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return "Structure non trouvée", 404

    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    journal_code = request.args.get('journal_code') or None
    compte_id = request.args.get('compte_id', type=int)
    tiers_type = request.args.get('tiers_type') or None
    tiers_id = request.args.get('tiers_id', type=int)

    data, titre = _donnees_rapport(type_rapport, structure_id, date_debut, date_fin, journal_code, compte_id,
                                    tiers_type, tiers_id)
    if data is None:
        return "Type de rapport invalide", 400

    structure_nom = ''
    try:
        from sheets_helper import sheets_helper
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        for s in structures:
            if str(s.get('ID')) == str(structure_id):
                structure_nom = s.get('nom') or ''
                break
    except Exception:
        pass

    # Quelques lignes de contexte avant le tableau — une seule cellule
    # chacune (colonne A), sans casser le tableau à colonnes multiples qui
    # suit : Excel les affiche simplement au-dessus, cellules B/C... vides.
    lignes_csv = [
        _csv_champ((structure_nom or "MEDILOGIC").upper()),
        _csv_champ(titre),
        _csv_champ(f"Période : {date_debut or '...'} au {date_fin or '...'}" if type_rapport != 'bilan'
                    else f"Au {date_fin or datetime.now().strftime('%Y-%m-%d')}"),
        _csv_champ(f"Édité le {datetime.now().strftime('%d/%m/%Y %H:%M')}"),
        '',
    ]

    if type_rapport == 'journal':
        lignes_csv.append(';'.join(_csv_champ(c) for c in
                           ['Date', 'Pièce', 'Libellé', 'Journal', 'N° compte', 'Compte', 'Tiers', 'Débit', 'Crédit']))
        total_d = total_c = 0
        for l in data:
            lignes_csv.append(';'.join([
                _csv_champ(_csv_date(l['date'])), _csv_champ(l['piece']), _csv_champ(l['libelle']), _csv_champ(l['journal_code']),
                _csv_champ(l['compte_numero']), _csv_champ(l['compte_nom']), _csv_champ(l.get('tiers_nom')),
                _csv_montant(l['debit']), _csv_montant(l['credit']),
            ]))
            total_d += l['debit']; total_c += l['credit']
        lignes_csv.append(';'.join([_csv_champ('TOTAL'), '', '', '', '', '', '', _csv_montant(total_d), _csv_montant(total_c)]))

    elif type_rapport == 'grand_livre':
        # ⭐ Solde courant seulement utile (donc affiché) filtré sur un seul
        # compte ou tiers — voir generer_grand_livre : None sinon.
        avec_solde = bool(data and data[0].get('solde_courant') is not None)
        entetes = ['Date', 'N° compte', 'Compte', 'Tiers', 'Pièce', 'Libellé', 'Débit', 'Crédit', 'Lettre']
        if avec_solde:
            entetes.append('Solde')
        lignes_csv.append(';'.join(_csv_champ(c) for c in entetes))
        total_d = total_c = 0
        for l in data:
            ligne = [
                _csv_champ(_csv_date(l['date'])), _csv_champ(l['compte_numero']), _csv_champ(l['compte_nom']), _csv_champ(l.get('tiers_nom')),
                _csv_champ(l['piece']), _csv_champ(l['libelle']),
                _csv_montant(l['debit']), _csv_montant(l['credit']), _csv_champ(l.get('lettre')),
            ]
            if avec_solde:
                ligne.append(_csv_montant(l['solde_courant']))
            lignes_csv.append(';'.join(ligne))
            total_d += l['debit']; total_c += l['credit']
        ligne_totale = [_csv_champ('TOTAL'), '', '', '', '', '', _csv_montant(total_d), _csv_montant(total_c), '']
        if avec_solde:
            ligne_totale.append('')
        lignes_csv.append(';'.join(ligne_totale))

    elif type_rapport == 'balance':
        lignes_csv.append(';'.join(_csv_champ(c) for c in ['N° compte', 'Compte', 'Débit', 'Crédit', 'Solde']))
        total_d = total_c = total_s = 0
        for l in data:
            lignes_csv.append(';'.join([
                _csv_champ(l['compte_numero']), _csv_champ(l['compte_nom']),
                _csv_montant(l['total_debit']), _csv_montant(l['total_credit']), _csv_montant(l['solde']),
            ]))
            total_d += l['total_debit']; total_c += l['total_credit']; total_s += l['solde']
        lignes_csv.append(';'.join([_csv_champ('TOTAL'), '', _csv_montant(total_d), _csv_montant(total_c), _csv_montant(total_s)]))

    elif type_rapport == 'tva':
        lignes_csv.append(_csv_champ(f"Taux appliqué : {data['taux']:g}%" if data['assujetti'] else "Structure non assujettie à la TVA"))
        lignes_csv.append('')
        lignes_csv.append(_csv_champ('TVA COLLECTÉE (ventes)'))
        lignes_csv.append(';'.join(_csv_champ(c) for c in ['Date', 'Pièce', 'Libellé', 'Montant']))
        for l in data['lignes']:
            lignes_csv.append(';'.join([_csv_champ(_csv_date(l['date'])), _csv_champ(l['piece']), _csv_champ(l['libelle']), _csv_montant(l['montant'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL TVA COLLECTÉE'), '', '', _csv_montant(data['total_collectee'])]))
        lignes_csv.append('')
        lignes_csv.append(_csv_champ('TVA DÉDUCTIBLE (achats fournisseurs)'))
        lignes_csv.append(';'.join(_csv_champ(c) for c in ['Date', 'Pièce', 'Libellé', 'Montant']))
        for l in data.get('lignes_deductible', []):
            lignes_csv.append(';'.join([_csv_champ(_csv_date(l['date'])), _csv_champ(l['piece']), _csv_champ(l['libelle']), _csv_montant(l['montant'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL TVA DÉDUCTIBLE'), '', '', _csv_montant(data['total_deductible'])]))
        lignes_csv.append('')
        lignes_csv.append(';'.join([_csv_champ('TVA NETTE À PAYER (collectée - déductible)'), '', '', _csv_montant(data['tva_nette'])]))

    elif type_rapport == 'resultat':
        lignes_csv.append(';'.join(_csv_champ(c) for c in ['Type', 'N° compte', 'Compte', 'Montant']))
        for l in data['charges']:
            lignes_csv.append(';'.join([_csv_champ('Charge'), _csv_champ(l['numero']), _csv_champ(l['nom']), _csv_montant(l['montant'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL CHARGES'), '', '', _csv_montant(data['total_charges'])]))
        for l in data['produits']:
            lignes_csv.append(';'.join([_csv_champ('Produit'), _csv_champ(l['numero']), _csv_champ(l['nom']), _csv_montant(l['montant'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL PRODUITS'), '', '', _csv_montant(data['total_produits'])]))
        lignes_csv.append(';'.join([_csv_champ(f"RÉSULTAT ({data['resultat_text']})"), '', '', _csv_montant(data['resultat'])]))

    elif type_rapport == 'bilan':
        lignes_csv.append(';'.join(_csv_champ(c) for c in ['Type', 'N° compte', 'Compte', 'Montant']))
        for l in data['actifs']:
            lignes_csv.append(';'.join([_csv_champ('Actif'), _csv_champ(l['numero']), _csv_champ(l['nom']), _csv_montant(l['montant'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL ACTIF'), '', '', _csv_montant(data['total_actif'])]))
        for l in data['passifs']:
            lignes_csv.append(';'.join([_csv_champ('Passif'), _csv_champ(l['numero']), _csv_champ(l['nom']), _csv_montant(l['montant'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL PASSIF'), '', '', _csv_montant(data['total_passif'])]))
        for l in data['capitaux_propres']:
            lignes_csv.append(';'.join([_csv_champ('Capitaux propres'), _csv_champ(l['numero']), _csv_champ(l['nom']), _csv_montant(l['montant'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL CAPITAUX PROPRES'), '', '', _csv_montant(data['total_capitaux'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL PASSIF + CAPITAUX'), '', '', _csv_montant(data['total_passif_capitaux'])]))
        lignes_csv.append(';'.join([_csv_champ('Équilibré' if data['est_equilibre'] else 'NON ÉQUILIBRÉ'), '', '', '']))

    elif type_rapport == 'charges':
        lignes_csv.append(';'.join(_csv_champ(c) for c in ['N° compte', 'Compte'] + data['mois'] + ['Total']))
        for rub in data['rubriques']:
            lignes_csv.append(';'.join([_csv_champ(rub['code']), _csv_champ(rub['libelle'].upper())]
                                       + [_csv_montant(rub['par_mois'].get(m, 0)) for m in data['mois']] + [_csv_montant(rub['total'])]))
            for cpt in rub['comptes']:
                lignes_csv.append(';'.join([_csv_champ(cpt['numero']), _csv_champ(cpt['nom'])]
                                           + [_csv_montant(cpt['par_mois'].get(m, 0)) for m in data['mois']] + [_csv_montant(cpt['total'])]))
        lignes_csv.append(';'.join([_csv_champ('TOTAL DES CHARGES'), '']
                                   + [_csv_montant(data['total_par_mois'].get(m, 0)) for m in data['mois']] + [_csv_montant(data['total'])]))

    elif type_rapport == 'exercice':
        # ⭐ 2026-10-22 : aperçu complet de l'exercice, section par section (même contenu que l'écran et le PDF)
        def section(titre_section, entetes):
            lignes_csv.extend(['', _csv_champ(titre_section), ';'.join(_csv_champ(c) for c in entetes)])

        def ligne(*valeurs):
            lignes_csv.append(';'.join(_csv_montant(v) if isinstance(v, (int, float)) else _csv_champ(v) for v in valeurs))

        etat = 'clôturé le ' + data['cloture']['date'] if data['cloture'] else (
            'en cours (situation au ' + data['situation_au'] + ')' if data['en_cours'] else 'terminé, non clôturé')
        section('SYNTHÈSE', ['Rubrique', f"Exercice {data['annee']}"] + ([f"Exercice {data['n1']['annee']}"] if data['n1'] else []))
        n1 = data['n1'] or {}
        ligne('État de l\'exercice', etat)
        ligne('Ce qui est rentré (produits)', data['total_produits'], *([n1['total_produits']] if n1 else []))
        ligne('Ce qui est sorti (charges)', data['total_charges'], *([n1['total_charges']] if n1 else []))
        ligne(f"Résultat ({data['resultat_text']})", data['resultat'], *([n1['resultat']] if n1 else []))
        ligne('Trésorerie au début', data['tresorerie']['debut'])
        ligne('Entrées d\'argent', data['tresorerie']['entrees'])
        ligne('Sorties d\'argent', data['tresorerie']['sorties'])
        ligne('Trésorerie à la fin', data['tresorerie']['fin'])
        ligne('Ce qu\'on nous doit (créances)', data['tiers']['total_creances'])
        ligne('Ce que nous devons (dettes)', data['tiers']['total_dettes'])
        for titre_section, rubriques, total in (('PRODUITS (ce qui est rentré)', data['produits'], data['total_produits']),
                                                ('CHARGES (ce qui est sorti)', data['charges'], data['total_charges'])):
            section(titre_section, ['N° compte', 'Compte', 'Montant'])
            for rub in rubriques:
                ligne(rub['code'], rub['libelle'].upper(), rub['total'])
                for cpt in rub['comptes']:
                    ligne(cpt['numero'], cpt['nom'], cpt['montant'])
            ligne('TOTAL', '', total)
        section('ÉVOLUTION MENSUELLE', ['Mois', 'Produits', 'Charges', 'Résultat', 'Résultat cumulé'])
        for m in data['mensuel']:
            ligne(m['mois'][5:7] + '/' + m['mois'][:4], m['produits'], m['charges'], m['resultat'], m['cumul'])
        section('TRÉSORERIE', ['N° compte', 'Compte', 'Début', 'Fin'])
        for c in data['tresorerie']['comptes']:
            ligne(c['numero'], c['nom'], c['debut'], c['fin'])
        section('CE QU\'ON NOUS DOIT (créances au 31/12)', ['N° compte', 'Compte', 'Montant'])
        for c in data['tiers']['creances']:
            ligne(c['numero'], c['nom'], c['montant'])
        ligne('TOTAL', '', data['tiers']['total_creances'])
        section('CE QUE NOUS DEVONS (dettes au 31/12)', ['N° compte', 'Compte', 'Montant'])
        for c in data['tiers']['dettes']:
            ligne(c['numero'], c['nom'], c['montant'])
        ligne('TOTAL', '', data['tiers']['total_dettes'])
        bilan = data['bilan']
        section('BILAN AU 31/12', ['Type', 'N° compte', 'Compte', 'Montant'])
        for cle, libelle in (('actifs', 'Actif'), ('passifs', 'Passif'), ('capitaux_propres', 'Capitaux propres')):
            for c in bilan[cle]:
                ligne(libelle, c['numero'], c['nom'], c['montant'])
        ligne('TOTAL ACTIF', '', '', bilan['total_actif'])
        ligne('TOTAL PASSIF + CAPITAUX', '', '', bilan['total_passif_capitaux'])
        sig = data['sig']
        section('SOLDES INTERMÉDIAIRES DE GESTION', ['Solde', 'Montant'])
        for libelle, cle in (('Excédent brut d\'exploitation', 'ebe'), ('Résultat d\'exploitation', 'resultat_exploitation'),
                             ('Résultat financier', 'resultat_financier'), ('Résultat net', 'resultat_net'),
                             ('Capacité d\'autofinancement (CAFG)', 'cafg')):
            ligne(libelle, sig[cle])
        section('CONTRÔLES AVANT CLÔTURE', ['Niveau', 'Point', 'Détail'])
        for c in data['controles']:
            ligne({'ok': 'OK', 'attention': 'À vérifier', 'bloquant': 'BLOQUANT'}[c['niveau']], c['titre'], c['detail'])

    # BOM UTF-8 en tête : sans lui, Excel devine souvent un encodage ANSI
    # et affiche les accents mal formés (voire, sur certaines versions,
    # échoue à re-scinder correctement les colonnes) — avec, il reconnaît
    # l'UTF-8 et le séparateur ';' immédiatement, à l'ouverture directe.
    contenu = '﻿' + '\r\n'.join(lignes_csv) + '\r\n'

    nom_fichier = f"{type_rapport}"
    if journal_code:
        nom_fichier += f"_{journal_code}"
    if date_fin:
        nom_fichier += f"_{date_fin}"
    nom_fichier += ".csv"

    from flask import Response
    return Response(
        contenu, mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{nom_fichier}"'}
    )


# ============================================================
# RECETTES PAR SERVICE (patron, 2026-10-22)
# ============================================================
# Le rapport existait déjà côté administration (/rapport-recettes-service), mais
# réservé à l'administrateur : le comptable ne le voyait pas. Mêmes chiffres
# (services/service_acte_service.py), ici sous l'accès de la comptabilité (hook
# _verifier_role_comptabilite), avec en plus un export tableur.

def _periode_recettes_service():
    from services.service_acte_service import bornes_periode_heures
    return bornes_periode_heures(request.args)


def _service_demande():
    """service=<id> ou 'non_classe' → (service_id ou None, demandé ?)."""
    sv = request.args.get('service')
    if not sv:
        return None, False
    return (int(sv) if sv.isdigit() else None), True


@compta_bp.route('/api/recettes-service')
def api_recettes_service():
    from services.service_acte_service import generer_rapport_recettes_service, CLES_SITUATION
    try:
        debut, fin, libelle = _periode_recettes_service()
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Dates ou heures invalides'}), 400
    services = generer_rapport_recettes_service(session.get('structure_id'), debut, fin)
    return jsonify({'success': True, 'services': services, 'periode': libelle,
                    'total': round(sum(s['montant_total'] for s in services), 2),
                    'totaux': {k: round(sum(s[k] for s in services), 2) for k in CLES_SITUATION}})


@compta_bp.route('/api/recettes-service/detail')
def api_recettes_service_detail():
    from services.service_acte_service import detail_recettes_service, CLES_SITUATION
    try:
        debut, fin, libelle = _periode_recettes_service()
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Dates ou heures invalides'}), 400
    service_id, _ = _service_demande()
    lignes = detail_recettes_service(session.get('structure_id'), debut, fin, service_id)
    return jsonify({'success': True, 'lignes': lignes, 'periode': libelle,
                    'total': round(sum(l['montant'] for l in lignes), 2),
                    'totaux': {k: round(sum(l[k] for l in lignes), 2) for k in CLES_SITUATION}})


@compta_bp.route('/recettes-service/print')
def print_recettes_service():
    """Même état imprimable que l'écran administrateur (rapport_recettes_service_print.html)."""
    from services.service_acte_service import (generer_rapport_recettes_service, detail_recettes_service,
                                               CLES_SITUATION)
    structure_id = session.get('structure_id')
    try:
        debut, fin, libelle = _periode_recettes_service()
    except (TypeError, ValueError):
        flash('Dates invalides', 'danger')
        return redirect(url_for('comptabilite.index'))
    service_id, un_service = _service_demande()
    if un_service:
        lignes = detail_recettes_service(structure_id, debut, fin, service_id)
        return render_template('rapport_recettes_service_print.html', services=[], lignes=lignes,
                               totaux={k: round(sum(l[k] for l in lignes), 2) for k in CLES_SITUATION},
                               service_nom=request.args.get('service_nom') or ('Non classé' if not service_id else f'Service {service_id}'),
                               total=round(sum(l['montant'] for l in lignes), 2),
                               libelle_periode=libelle, date_debut=None, date_fin=None, now=datetime.now())
    services = generer_rapport_recettes_service(structure_id, debut, fin)
    return render_template('rapport_recettes_service_print.html', services=services,
                           totaux={k: round(sum(s[k] for s in services), 2) for k in CLES_SITUATION},
                           total=round(sum(s['montant_total'] for s in services), 2),
                           libelle_periode=libelle, date_debut=None, date_fin=None, now=datetime.now())


@compta_bp.route('/recettes-service/export')
def export_recettes_service():
    """Export tableur (.csv ';', BOM UTF-8 — même format que les autres exports de la
    comptabilité, s'ouvre directement dans Excel) des recettes par service.
      contenu=synthese (défaut) : une ligne par service, avec les totaux ;
      contenu=detail            : toutes les lignes (vente, patient, acte) avec leur service ;
      service=<id>|non_classe    : le détail d'un seul service."""
    from services.service_acte_service import generer_rapport_recettes_service, detail_recettes_service
    structure_id = session.get('structure_id')
    try:
        debut, fin, libelle = _periode_recettes_service()
    except (TypeError, ValueError):
        return "Dates ou heures invalides", 400

    service_id, un_service = _service_demande()
    contenu_demande = 'detail' if un_service else (request.args.get('contenu') or 'synthese')
    services = [] if un_service else generer_rapport_recettes_service(structure_id, debut, fin)

    def ligne(*valeurs):
        return ';'.join(_csv_montant(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else _csv_champ(v)
                        for v in valeurs)

    if un_service:
        titre = f"Recettes du service : {request.args.get('service_nom') or ('Non classé' if not service_id else service_id)}"
    elif contenu_demande == 'detail':
        titre = "Recettes par service — détail des lignes"
    else:
        titre = "Recettes par service"
    lignes_csv = [_csv_champ(_nom_structure_export(structure_id).upper()), _csv_champ(titre),
                  _csv_champ(f"Période : {libelle}"),
                  _csv_champ(f"Édité le {datetime.now().strftime('%d/%m/%Y %H:%M')}"), '']

    if contenu_demande == 'detail':
        a_traiter = ([(service_id, request.args.get('service_nom') or '')] if un_service
                     else [(s['service_id'], s['service_nom']) for s in services])
        lignes_csv.append(ligne('Service', 'Date et heure', 'N° vente', 'Patient', 'Acte / produit', 'Type',
                                'Quantité', 'Prix', 'Montant', 'Encaissé', 'Dû assurances', 'Dû patients',
                                'Remboursé', 'Aides / remises'))
        totaux = [0.0] * 6
        for sid, snom in a_traiter:
            for l in detail_recettes_service(structure_id, debut, fin, sid):
                lignes_csv.append(ligne(snom or 'Non classé', l['date'], str(l['numero'] or ''), l['patient'], l['acte'],
                                        l['type'], l['quantite'], l['prix'], l['montant'], l['encaisse'],
                                        l['du_assurances'], l['du_patients'], l['rembourse'], l['aides']))
                for i, k in enumerate(('montant', 'encaisse', 'du_assurances', 'du_patients', 'rembourse', 'aides')):
                    totaux[i] += l[k]
        lignes_csv.append(ligne('TOTAL', '', '', '', '', '', '', '', *totaux))
    else:
        total = sum(s['montant_total'] for s in services)
        lignes_csv.append(ligne('Service', 'Nombre de lignes', 'Recettes', '% du total', 'Encaissé',
                                'Dû assurances', 'Dû patients', 'Remboursé', 'Aides / remises'))
        for s in services:
            pct = f"{(s['montant_total'] / total * 100):.1f}".replace('.', ',') if total else ''
            lignes_csv.append(ligne(s['service_nom'], s['nb_lignes'], s['montant_total'], pct, s['encaisse'],
                                    s['du_assurances'], s['du_patients'], s['rembourse'], s['aides']))
        lignes_csv.append(ligne('TOTAL', sum(s['nb_lignes'] for s in services), total, '100' if total else '',
                                *[sum(s[k] for s in services) for k in
                                  ('encaisse', 'du_assurances', 'du_patients', 'rembourse', 'aides')]))

    contenu = '﻿' + '\r\n'.join(lignes_csv) + '\r\n'
    nom_fichier = ('recettes_service_detail' if contenu_demande == 'detail' else 'recettes_par_service') \
        + f"_{debut.strftime('%Y-%m-%d')}_{(fin - timedelta(minutes=1)).strftime('%Y-%m-%d')}.csv"
    from flask import Response
    return Response(contenu, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{nom_fichier}"'})


def _nom_structure_export(structure_id):
    """Nom de la structure pour l'en-tête des exports (session, sinon « MEDILOGIC »)."""
    return session.get('structure_nom') or 'MEDILOGIC'


# ============================================================
# EXPORT COMPTABLE NORMALISÉ (FORMAT FEC)
# ============================================================
# ⭐ Le TXT ci-dessus est un rapport IMPRIMABLE (colonnes de largeur fixe,
# libellés tronqués pour tenir dedans) — inexploitable tel quel par un
# cabinet comptable externe qui voudrait réimporter les écritures dans son
# propre logiciel. Cet export suit la structure du FEC (Fichier des
# Écritures Comptables, norme française DGFiP — 18 colonnes standard,
# valeurs séparées par tabulation, une ligne par ligne d'écriture) :
# largement reconnu par les logiciels comptables (Sage, Ciel, Excel...),
# donc un format d'échange "FEC ou équivalent" utile même hors de France.
#
# CompAuxNum/CompAuxLib et EcritureLet/DateLet sont désormais renseignés
# (comptes auxiliaires et lettrage — voir models.LigneEcriture.tiers_*/
# lettre/date_lettrage). Champ encore VIDE, non disponible dans le modèle
# actuel : Montantdevise/Idevise (tout est en FCFA, pas de devise
# étrangère à tracer). EcritureNum utilise l'id technique de l'écriture
# (croissant, unique, mais pas une numérotation sans trou par journal — à signaler au
# cabinet comptable si une numérotation stricte est exigée).
FEC_COLONNES = [
    'JournalCode', 'JournalLib', 'EcritureNum', 'EcritureDate',
    'CompteNum', 'CompteLib', 'CompAuxNum', 'CompAuxLib',
    'PieceRef', 'PieceDate', 'EcritureLib', 'Debit', 'Credit',
    'EcritureLet', 'DateLet', 'ValidDate', 'Montantdevise', 'Idevise',
]


def _fec_date(d):
    """Format de date attendu par le FEC : AAAAMMJJ, sans séparateur."""
    return d.strftime('%Y%m%d') if d else ''


def _fec_montant(m):
    """Toujours 2 décimales, séparateur décimal '.', jamais de séparateur
    de milliers — format numérique brut attendu par le FEC (pas un format
    d'affichage)."""
    return f"{float(m or 0):.2f}"


def _fec_champ(v):
    """Neutralise tabulations/retours à la ligne dans un libellé — le FEC
    est un format à colonnes séparées par tabulation, une valeur qui en
    contiendrait déjà casserait l'alignement des colonnes pour toutes les
    lignes suivantes."""
    return (str(v) if v is not None else '').replace('\t', ' ').replace('\r', ' ').replace('\n', ' ').strip()


@compta_bp.route('/rapport/export-fec')
def export_fec():
    """Export de TOUTES les écritures validées de la période, structure
    FEC (18 colonnes, séparateur tabulation) — pour transmission à un
    cabinet comptable externe. Contrairement à l'export TXT (par journal),
    celui-ci couvre systématiquement TOUS les journaux : un FEC ne se
    limite jamais à un seul journal, c'est l'ensemble de l'exercice."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return "Structure non trouvée", 404

    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    if not date_debut or not date_fin:
        return "Les paramètres date_debut et date_fin sont obligatoires pour un export FEC", 400

    lignes = db.session.query(
        EcritureComptable.id,
        EcritureComptable.journal_code,
        EcritureComptable.date_ecriture,
        EcritureComptable.piece_justificative,
        EcritureComptable.libelle.label('ecriture_libelle'),
        EcritureComptable.date_validation,
        LigneEcriture.debit,
        LigneEcriture.credit,
        LigneEcriture.libelle.label('ligne_libelle'),
        LigneEcriture.tiers_type,
        LigneEcriture.tiers_id,
        LigneEcriture.tiers_nom,
        LigneEcriture.lettre,
        LigneEcriture.date_lettrage,
        CompteComptable.numero,
        CompteComptable.nom,
    ).join(
        LigneEcriture, LigneEcriture.ecriture_id == EcritureComptable.id
    ).join(
        CompteComptable, CompteComptable.id == LigneEcriture.compte_id
    ).filter(
        EcritureComptable.structure_id == structure_id,
        EcritureComptable.statut == 'valide',
        EcritureComptable.date_ecriture >= date_debut,
        EcritureComptable.date_ecriture <= date_fin,
    ).order_by(EcritureComptable.date_ecriture, EcritureComptable.id).all()

    if not lignes:
        return "Aucune écriture validée sur cette période", 404

    fec_lignes = ['\t'.join(FEC_COLONNES)]
    for l in lignes:
        journal_code = l.journal_code or 'OD'
        journal_lib = EcritureComptable.JOURNAUX.get(journal_code, journal_code)
        # ⭐ Le libellé de LIGNE (spécifique à un compte de la même écriture,
        # ex: "Client" sur une ligne / "Vente" sur l'autre) est plus précis
        # que le libellé global de l'écriture quand il est renseigné —
        # sinon on retombe sur celui de l'écriture.
        libelle = l.ligne_libelle or l.ecriture_libelle
        # ⭐ Compte auxiliaire (client/fournisseur) — voir models.LigneEcriture.
        # Pas de vraie numérotation de sous-compte dans l'appli : code
        # synthétique lisible (P<id>/F<id>), suffisant pour que le cabinet
        # comptable regroupe/filtre par tiers à l'import.
        comp_aux_num = ''
        if l.tiers_id and l.tiers_type == 'patient':
            comp_aux_num = f"P{l.tiers_id}"
        elif l.tiers_id and l.tiers_type == 'fournisseur':
            comp_aux_num = f"F{l.tiers_id}"
        fec_lignes.append('\t'.join([
            _fec_champ(journal_code),
            _fec_champ(journal_lib),
            str(l.id),
            _fec_date(l.date_ecriture),
            _fec_champ(l.numero),
            _fec_champ(l.nom),
            _fec_champ(comp_aux_num),          # CompAuxNum
            _fec_champ(l.tiers_nom),           # CompAuxLib
            _fec_champ(l.piece_justificative),
            _fec_date(l.date_ecriture),  # PieceDate : pas de date de pièce distincte en base
            _fec_champ(libelle),
            _fec_montant(l.debit),
            _fec_montant(l.credit),
            _fec_champ(l.lettre),                                        # EcritureLet
            _fec_date(l.date_lettrage.date()) if l.date_lettrage else '',  # DateLet
            _fec_date(l.date_validation or l.date_ecriture),
            '',  # Montantdevise
            '',  # Idevise
        ]))

    # BOM UTF-8 en tête (même raisonnement que l'export CSV ci-dessus) :
    # aide Excel à reconnaître direct l'encodage/les colonnes à l'ouverture
    # ; n'affecte pas la conformité FEC (transparent pour un logiciel
    # comptable qui lit le fichier), extension/séparateur tabulation
    # inchangés — ce sont eux qui font foi pour la norme, pas le BOM.
    contenu = '﻿' + '\r\n'.join(fec_lignes) + '\r\n'
    nom_fichier = f"FEC_structure{structure_id}_{date_debut}_{date_fin}.txt"

    from flask import Response
    return Response(
        contenu, mimetype='text/plain; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{nom_fichier}"'}
    )


# routes/comptabilite.py - Ajouter cette route

@compta_bp.route('/budget/print')
def print_budget():
    """Génère une version imprimable du budget"""
    structure_id = session.get('structure_id')
    
    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('comptabilite.index'))
    
    annee = request.args.get('annee', datetime.now().year)
    compte_id = request.args.get('compte_id')
    
    # Récupérer les comptes avec budget
    query_comptes = CompteComptable.query.filter_by(
        structure_id=structure_id,
        actif=True
    )
    
    if compte_id:
        query_comptes = query_comptes.filter_by(id=compte_id)
    
    comptes = query_comptes.order_by(CompteComptable.numero).all()
    
    # Récupérer les budgets
    budgets = Budget.query.filter_by(
        structure_id=structure_id,
        annee=annee
    ).all()
    
    budget_dict = {}
    for b in budgets:
        key = (b.compte_id, b.mois)
        budget_dict[key] = b
    
    # Construire les données
    data = []
    for compte in comptes:
        item = {
            'compte_id': compte.id,
            'compte_numero': compte.numero,
            'compte_nom': compte.nom,
            'total_prevu': 0,
            'total_reel': 0,
            'mois_data': []
        }
        
        total_prevu = 0
        for mois in range(1, 13):
            key = (compte.id, mois)
            if key in budget_dict:
                b = budget_dict[key]
                montant_prevu = float(b.montant_prevu)
                total_prevu += montant_prevu
                item['mois_data'].append({
                    'mois': mois,
                    'montant_prevu': montant_prevu,
                    'montant_reel': float(b.montant_reel) if b.montant_reel else 0
                })
            else:
                item['mois_data'].append({
                    'mois': mois,
                    'montant_prevu': 0,
                    'montant_reel': 0
                })
        
        item['total_prevu'] = total_prevu
        
        # Ne garder que les comptes avec budget
        if total_prevu > 0:
            data.append(item)
    
    # Récupérer les infos de la structure depuis localStorage (passer en variable)
    structure_info = {
        'nom': 'Mon Etablissement',
        'adresse': '',
        'telephone': '',
        'email': '',
        'logo_url': ''
    }
    
    return render_template('comptabilite/print_budget.html',
                         data=data,
                         annee=annee,
                         structure_info=structure_info,
                         now=datetime.now())


# ============================================================
# ANOMALIES COMPTABLES (générations d'écritures automatiques échouées)
# ============================================================

@compta_bp.route('/api/anomalies')
def api_liste_anomalies():
    structure_id = session.get('structure_id')
    resolu_param = request.args.get('resolu')  # 'true' / 'false' / absent = toutes

    query = AnomalieComptable.query.filter_by(structure_id=structure_id)
    if resolu_param == 'true':
        query = query.filter_by(resolu=True)
    elif resolu_param == 'false':
        query = query.filter_by(resolu=False)

    anomalies = query.order_by(AnomalieComptable.date_creation.desc()).limit(200).all()

    return jsonify({
        'total_non_resolues': AnomalieComptable.query.filter_by(structure_id=structure_id, resolu=False).count(),
        'data': [{
            'id': a.id,
            'source_type': a.source_type or '-',
            'source_id': a.source_id,
            'message': a.message,
            'date_creation': a.date_creation.strftime('%Y-%m-%d %H:%M') if a.date_creation else '',
            'resolu': a.resolu,
            'resolu_par': a.resolu_par or '',
            'commentaire': a.commentaire or '',
        } for a in anomalies]
    })


@compta_bp.route('/api/anomalies/<int:id>/resoudre', methods=['POST'])
def api_resoudre_anomalie(id):
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    anomalie = AnomalieComptable.query.filter_by(id=id, structure_id=structure_id).first()
    if not anomalie:
        return jsonify({'error': 'Anomalie non trouvée'}), 404

    anomalie.resolu = True
    anomalie.resolu_par = user_name
    anomalie.date_resolution = datetime.utcnow()
    anomalie.commentaire = (request.json or {}).get('commentaire', '')
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# CRÉANCES DOUTEUSES & PROVISIONS
# ============================================================

@compta_bp.route('/api/creances-douteuses')
def api_creances_douteuses():
    """Balance âgée des créances patients impayées (factures en attente ou
    partielles), pour repérer celles à provisionner."""
    structure_id = session.get('structure_id')
    seuil_jours = request.args.get('seuil_jours', 60, type=int)

    factures = Facture.query.filter(
        Facture.structure_id == structure_id,
        Facture.statut.in_(['en_attente', 'partielle']),
        Facture.reste_a_payer > 0,
    ).order_by(Facture.date_echeance).all()

    provisions_actives = {p.facture_id: p for p in ProvisionCreance.query.filter_by(
        structure_id=structure_id, statut='active').all()}

    today = date.today()
    result = []
    for f in factures:
        jours_retard = (today - f.date_echeance).days if f.date_echeance else 0
        if jours_retard < seuil_jours:
            continue
        prov = provisions_actives.get(f.id)
        tranche = '90j+' if jours_retard >= 90 else ('60-89j' if jours_retard >= 60 else ('31-59j' if jours_retard >= 31 else '0-30j'))
        result.append({
            'facture_id': f.id,
            'numero_facture': f.numero_facture,
            'patient_id': f.patient_id,
            'patient_nom': f.patient_nom,
            'date_echeance': f.date_echeance.strftime('%Y-%m-%d') if f.date_echeance else '',
            'jours_retard': jours_retard,
            'tranche': tranche,
            'reste_a_payer': float(f.reste_a_payer or 0),
            'deja_provisionnee': prov is not None,
            'provision_id': prov.id if prov else None,
            'montant_provisionne': float(prov.montant_provisionne) if prov else 0,
        })

    return jsonify(result)


@compta_bp.route('/api/creances-douteuses/<int:facture_id>/provisionner', methods=['POST'])
def api_provisionner_creance(facture_id):
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    data = request.json or {}
    taux = float(data.get('taux', 50))

    facture = Facture.query.filter_by(id=facture_id, structure_id=structure_id).first()
    if not facture:
        return jsonify({'error': 'Facture non trouvée'}), 404

    existante = ProvisionCreance.query.filter_by(facture_id=facture_id, statut='active').first()
    if existante:
        return jsonify({'error': 'Cette créance est déjà provisionnée'}), 400

    montant_creance = float(facture.reste_a_payer or 0)
    if montant_creance <= 0:
        return jsonify({'error': 'Aucun reste à payer sur cette facture'}), 400

    montant_provisionne = round(montant_creance * taux / 100, 2)

    provision = ProvisionCreance(
        structure_id=structure_id, facture_id=facture.id, patient_id=facture.patient_id,
        patient_nom=facture.patient_nom, montant_creance=montant_creance,
        taux_provision=taux, montant_provisionne=montant_provisionne,
        statut='active', created_by=user_name,
    )
    db.session.add(provision)
    db.session.flush()

    from services.comptabilite_service import generer_ecriture_provision
    ecriture = generer_ecriture_provision(structure_id, montant_provisionne, facture.patient_nom, provision.id, user_name, patient_id=facture.patient_id)
    # ⭐ FIX : generer_ecriture_provision() committe déjà en interne, ce qui
    # expire `provision` (expire_on_commit) — lui assigner un attribut
    # ensuite peut déclencher un rafraîchissement en échec (ObjectDeletedError,
    # observé en production sur un cas similaire). UPDATE direct par id à
    # la place, qui ne nécessite pas de recharger l'instance.
    if ecriture:
        db.session.query(ProvisionCreance).filter(ProvisionCreance.id == provision.id).update(
            {'ecriture_provision_id': ecriture.id}, synchronize_session=False)
        db.session.commit()

    return jsonify({'success': True, 'provision_id': provision.id, 'montant_provisionne': montant_provisionne})


@compta_bp.route('/api/provisions')
def api_liste_provisions():
    structure_id = session.get('structure_id')
    provisions = ProvisionCreance.query.filter_by(structure_id=structure_id).order_by(
        ProvisionCreance.date_creation.desc()).all()
    return jsonify([{
        'id': p.id, 'facture_id': p.facture_id, 'patient_nom': p.patient_nom,
        'montant_creance': float(p.montant_creance), 'taux_provision': float(p.taux_provision),
        'montant_provisionne': float(p.montant_provisionne), 'statut': p.statut,
        'date_creation': p.date_creation.strftime('%Y-%m-%d') if p.date_creation else '',
    } for p in provisions])


@compta_bp.route('/api/provisions/<int:id>/reprendre', methods=['POST'])
def api_reprendre_provision(id):
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    provision = ProvisionCreance.query.filter_by(id=id, structure_id=structure_id, statut='active').first()
    if not provision:
        return jsonify({'error': 'Provision active non trouvée'}), 404

    provision_id = provision.id
    from services.comptabilite_service import generer_ecriture_reprise_provision
    ecriture = generer_ecriture_reprise_provision(
        structure_id, float(provision.montant_provisionne), provision.patient_nom, provision_id, user_name,
        patient_id=provision.patient_id)

    # ⭐ FIX : voir commentaire dans api_provisionner_creance — UPDATE direct
    # plutôt que de muter l'instance chargée avant le commit interne.
    maj = {'statut': 'reprise', 'date_cloture': datetime.utcnow()}
    if ecriture:
        maj['ecriture_reprise_id'] = ecriture.id
    db.session.query(ProvisionCreance).filter(ProvisionCreance.id == provision_id).update(
        maj, synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True})


@compta_bp.route('/api/provisions/<int:id>/passer-en-perte', methods=['POST'])
def api_provision_passer_en_perte(id):
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    provision = ProvisionCreance.query.filter_by(id=id, structure_id=structure_id, statut='active').first()
    if not provision:
        return jsonify({'error': 'Provision active non trouvée'}), 404

    provision_id, facture_id_lie = provision.id, provision.facture_id
    from services.comptabilite_service import generer_ecriture_perte_creance
    ecriture = generer_ecriture_perte_creance(
        structure_id, float(provision.montant_creance), float(provision.montant_provisionne),
        provision.patient_nom, provision_id, user_name, patient_id=provision.patient_id)

    # ⭐ FIX : voir commentaire dans api_provisionner_creance — UPDATE direct
    # (par id, sans recharger les instances) plutôt que de muter provision/
    # facture après le commit interne de generer_ecriture_perte_creance().
    maj = {'statut': 'perte', 'date_cloture': datetime.utcnow()}
    if ecriture:
        maj['ecriture_reprise_id'] = ecriture.id
    db.session.query(ProvisionCreance).filter(ProvisionCreance.id == provision_id).update(
        maj, synchronize_session=False)

    if facture_id_lie:
        # ⭐ Concaténation faite côté SQL (func.coalesce) pour ne jamais avoir
        # à lire `facture.notes` sur une instance potentiellement expirée.
        db.session.query(Facture).filter(Facture.id == facture_id_lie).update(
            {
                'reste_a_payer': 0,
                'statut': 'annulee',
                'notes': func.coalesce(Facture.notes, '') + ' [Créance passée en perte définitive]',
            },
            synchronize_session=False,
        )

    db.session.commit()
    return jsonify({'success': True})


@compta_bp.route('/api/creances-douteuses/<int:facture_id>/perte-directe', methods=['POST'])
def api_perte_directe(facture_id):
    """Passe directement une créance en perte, sans passer par l'étape
    provision (cas d'un abandon de créance décidé immédiatement)."""
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')

    facture = Facture.query.filter_by(id=facture_id, structure_id=structure_id).first()
    if not facture:
        return jsonify({'error': 'Facture non trouvée'}), 404

    montant = float(facture.reste_a_payer or 0)
    if montant <= 0:
        return jsonify({'error': 'Aucun reste à payer sur cette facture'}), 400

    provision = ProvisionCreance(
        structure_id=structure_id, facture_id=facture.id, patient_id=facture.patient_id,
        patient_nom=facture.patient_nom, montant_creance=montant, taux_provision=100,
        montant_provisionne=0, statut='active', created_by=user_name,
        commentaire='Perte directe sans provision préalable',
    )
    db.session.add(provision)
    db.session.flush()

    provision_id, facture_id_lie = provision.id, facture.id
    from services.comptabilite_service import generer_ecriture_perte_creance
    ecriture = generer_ecriture_perte_creance(structure_id, montant, 0, facture.patient_nom, provision_id, user_name, patient_id=facture.patient_id)

    # ⭐ FIX : voir commentaire dans api_provisionner_creance.
    maj = {'statut': 'perte', 'date_cloture': datetime.utcnow()}
    if ecriture:
        maj['ecriture_reprise_id'] = ecriture.id
    db.session.query(ProvisionCreance).filter(ProvisionCreance.id == provision_id).update(
        maj, synchronize_session=False)

    db.session.query(Facture).filter(Facture.id == facture_id_lie).update(
        {
            'reste_a_payer': 0,
            'statut': 'annulee',
            'notes': func.coalesce(Facture.notes, '') + ' [Créance passée en perte définitive]',
        },
        synchronize_session=False,
    )

    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# IMMOBILISATIONS & AMORTISSEMENTS
# ============================================================

@compta_bp.route('/api/immobilisations')
def api_liste_immobilisations():
    structure_id = session.get('structure_id')
    immos = Immobilisation.query.filter_by(structure_id=structure_id).order_by(
        Immobilisation.date_acquisition.desc()).all()
    return jsonify([{
        'id': i.id, 'designation': i.designation, 'categorie': i.categorie or '',
        'compte_immo_numero': i.compte_immo_numero, 'compte_amort_numero': i.compte_amort_numero,
        'date_acquisition': i.date_acquisition.strftime('%Y-%m-%d') if i.date_acquisition else '',
        'valeur_acquisition': float(i.valeur_acquisition or 0), 'valeur_residuelle': float(i.valeur_residuelle or 0),
        'duree_annees': i.duree_annees, 'statut': i.statut,
        'cumul_amorti': float(i.cumul_amorti or 0), 'vnc': i.valeur_nette_comptable(),
        'dotation_annuelle_theorique': round(i.dotation_annuelle_theorique(), 2),
    } for i in immos])


@compta_bp.route('/api/immobilisations', methods=['POST'])
def api_creer_immobilisation():
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    data = request.json or {}

    date_acq = parse_date(data.get('date_acquisition'))
    if not date_acq:
        return jsonify({'error': 'Date d\'acquisition invalide'}), 400

    immo = Immobilisation(
        structure_id=structure_id,
        designation=data.get('designation'),
        categorie=data.get('categorie', ''),
        compte_immo_numero=data.get('compte_immo_numero', COMPTE_IMMO_MATERIEL_MEDICAL),
        compte_amort_numero=data.get('compte_amort_numero', COMPTE_AMORT_MATERIEL_MEDICAL),
        date_acquisition=date_acq,
        valeur_acquisition=data.get('valeur_acquisition', 0),
        valeur_residuelle=data.get('valeur_residuelle', 0),
        duree_annees=data.get('duree_annees', 5),
        mode_paiement=data.get('mode_paiement', 'especes'),
        created_by=user_name,
    )
    db.session.add(immo)
    db.session.flush()

    immo_id = immo.id
    if data.get('generer_ecriture', True):
        from services.comptabilite_service import generer_ecriture_acquisition_immobilisation
        ecriture = generer_ecriture_acquisition_immobilisation(immo, user_name)
        # ⭐ FIX : voir commentaire dans api_provisionner_creance — UPDATE
        # direct plutôt que de muter `immo` après le commit interne.
        if ecriture:
            db.session.query(Immobilisation).filter(Immobilisation.id == immo_id).update(
                {'ecriture_acquisition_id': ecriture.id}, synchronize_session=False)

    db.session.commit()
    return jsonify({'success': True, 'id': immo_id})


@compta_bp.route('/api/immobilisations/dotations/generer', methods=['POST'])
def api_generer_dotations():
    """Génère (une seule fois par immobilisation et par année) la dotation
    aux amortissements de l'année demandée, au prorata du nombre de mois
    de détention si l'acquisition a eu lieu en cours d'année."""
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    annee = (request.json or {}).get('annee', datetime.now().year)

    immos = Immobilisation.query.filter_by(structure_id=structure_id, statut='en_service').all()

    # ⭐ FIX : chaque generer_ecriture_dotation_amortissement() committe en
    # interne, ce qui expire TOUS les objets du session (dont les autres
    # `immo` déjà chargés dans cette liste, pas encore traités par la
    # boucle). Relire leurs attributs plus tard déclenche un rafraîchissement
    # qui peut échouer (ObjectDeletedError, observé en production sur un cas
    # similaire pour les ventes). On extrait donc tout ce dont on a besoin en
    # valeurs Python simples AVANT la boucle, et on met à jour cumul_amorti
    # par UPDATE direct (par id) plutôt qu'en mutant l'instance.
    donnees_immos = [{
        'id': i.id, 'designation': i.designation,
        'date_acquisition': i.date_acquisition,
        'dotation_annuelle_theorique': i.dotation_annuelle_theorique(),
        'base_amortissable': i.base_amortissable(),
        'cumul_amorti': float(i.cumul_amorti or 0),
    } for i in immos]

    from services.comptabilite_service import generer_ecriture_dotation_amortissement

    nb_generees = 0
    erreurs = []
    for d in donnees_immos:
        if d['date_acquisition'].year > annee:
            continue
        deja = DotationAmortissement.query.filter_by(immobilisation_id=d['id'], annee=annee).first()
        if deja:
            continue

        if d['dotation_annuelle_theorique'] <= 0:
            continue

        if d['date_acquisition'].year == annee:
            mois_detention = 12 - d['date_acquisition'].month + 1
        else:
            mois_detention = 12
        montant = round(d['dotation_annuelle_theorique'] * mois_detention / 12, 2)

        # Ne pas amortir au-delà de la base amortissable (dernière année / arrondis)
        restant_amortissable = d['base_amortissable'] - d['cumul_amorti']
        montant = min(montant, max(restant_amortissable, 0))
        if montant <= 0:
            continue

        immo_ref = Immobilisation.query.get(d['id'])
        ecriture = generer_ecriture_dotation_amortissement(immo_ref, montant, annee, user_name)

        db.session.add(DotationAmortissement(
            structure_id=structure_id, immobilisation_id=d['id'], annee=annee,
            montant=montant, ecriture_id=ecriture.id if ecriture else None, created_by=user_name,
        ))
        db.session.query(Immobilisation).filter(Immobilisation.id == d['id']).update(
            {'cumul_amorti': d['cumul_amorti'] + montant}, synchronize_session=False)
        db.session.commit()

        nb_generees += 1
        if not ecriture:
            erreurs.append(d['designation'])

    return jsonify({'success': True, 'nb_generees': nb_generees, 'erreurs': erreurs})


# ============================================================
# FOURNISSEURS (comptes de tiers 401/4011 — achats à crédit + règlements)
# ============================================================

@compta_bp.route('/api/fournisseurs')
def api_liste_fournisseurs():
    """Liste des fournisseurs avec leur solde dû (somme des achats à crédit
    non intégralement réglés)."""
    structure_id = session.get('structure_id')
    fournisseurs = Fournisseur.query.filter_by(structure_id=structure_id).order_by(Fournisseur.nom).all()
    return jsonify([{
        'id': f.id, 'nom': f.nom, 'telephone': f.telephone or '', 'email': f.email or '',
        'adresse': f.adresse or '', 'actif': f.actif, 'solde_du': f.solde_du(),
    } for f in fournisseurs])


@compta_bp.route('/api/fournisseurs', methods=['POST'])
def api_creer_fournisseur():
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    data = request.json or {}

    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'error': 'Le nom du fournisseur est obligatoire'}), 400

    fournisseur = Fournisseur(
        structure_id=structure_id, nom=nom,
        telephone=data.get('telephone', ''), email=data.get('email', ''),
        adresse=data.get('adresse', ''), actif=True, created_by_nom=user_name,
    )
    db.session.add(fournisseur)
    db.session.commit()
    return jsonify({'success': True, 'id': fournisseur.id})


@compta_bp.route('/api/fournisseurs/<int:fournisseur_id>', methods=['PUT'])
def api_modifier_fournisseur(fournisseur_id):
    structure_id = session.get('structure_id')
    fournisseur = Fournisseur.query.filter_by(id=fournisseur_id, structure_id=structure_id).first()
    if not fournisseur:
        return jsonify({'error': 'Fournisseur non trouvé'}), 404

    data = request.json or {}
    if 'nom' in data and data['nom'].strip():
        fournisseur.nom = data['nom'].strip()
    if 'telephone' in data:
        fournisseur.telephone = data['telephone']
    if 'email' in data:
        fournisseur.email = data['email']
    if 'adresse' in data:
        fournisseur.adresse = data['adresse']
    if 'actif' in data:
        fournisseur.actif = bool(data['actif'])
    db.session.commit()
    return jsonify({'success': True})


@compta_bp.route('/api/fournisseurs/achats')
def api_liste_achats_fournisseurs():
    """Liste des achats à crédit, filtrable par statut (a_regler/reglee) et
    par fournisseur — c'est la vue "qui doit-on payer" (balance fournisseurs)."""
    structure_id = session.get('structure_id')
    statut = request.args.get('statut')
    fournisseur_id = request.args.get('fournisseur_id', type=int)

    query = AchatFournisseur.query.filter_by(structure_id=structure_id)
    if statut:
        query = query.filter_by(statut=statut)
    if fournisseur_id:
        query = query.filter_by(fournisseur_id=fournisseur_id)
    achats = query.order_by(AchatFournisseur.date_achat.desc()).all()

    return jsonify([{
        'id': a.id, 'fournisseur_id': a.fournisseur_id,
        'fournisseur_nom': a.fournisseur.nom if a.fournisseur else '',
        'montant_total': float(a.montant_total or 0), 'montant_paye': float(a.montant_paye or 0),
        'montant_saisi': float(a.montant_saisi) if a.montant_saisi is not None else float(a.montant_total or 0),
        'type_montant_saisi': a.type_montant_saisi or 'ttc',
        'reste_a_payer': a.reste_a_payer(), 'motif': a.motif,
        'motif_personnalise': a.motif_personnalise or '', 'description': a.description or '',
        'date_achat': a.date_achat.strftime('%Y-%m-%d') if a.date_achat else '',
        'date_echeance': a.date_echeance.strftime('%Y-%m-%d') if a.date_echeance else '',
        'statut': a.statut,
    } for a in achats])


@compta_bp.route('/api/fournisseurs/achats', methods=['POST'])
def api_creer_achat_fournisseur():
    """Enregistre un achat À CRÉDIT (la charge est comptabilisée tout de
    suite ; la caisse n'est impactée qu'au règlement, voir /regler)."""
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    data = request.json or {}

    try:
        fournisseur_id = int(data.get('fournisseur_id'))
        montant = float(data.get('montant', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'fournisseur_id/montant invalides'}), 400

    if montant <= 0:
        return jsonify({'error': 'Montant invalide'}), 400

    fournisseur = Fournisseur.query.filter_by(id=fournisseur_id, structure_id=structure_id).first()
    if not fournisseur:
        return jsonify({'error': 'Fournisseur non trouvé'}), 404

    date_echeance = parse_date(data.get('date_echeance')) if data.get('date_echeance') else None

    # ⭐ TVA déductible : montant_total doit TOUJOURS représenter le vrai
    # montant dû (TTC) — si l'utilisateur a saisi un montant HT, on le
    # convertit ici, une fois, avant stockage (voir models.AchatFournisseur).
    type_montant = data.get('type_montant') or 'ttc'
    montant_saisi = montant
    if type_montant == 'ht':
        param_tva = ParametrageTva.get_ou_creer(structure_id)
        taux_tva = float(param_tva.taux or 0) if param_tva.assujetti else 0
        montant_total_ttc = round(montant * (1 + taux_tva / 100), 2) if taux_tva > 0 else montant
    else:
        montant_total_ttc = montant

    achat = AchatFournisseur(
        structure_id=structure_id, fournisseur_id=fournisseur_id,
        montant_total=montant_total_ttc, montant_saisi=montant_saisi, type_montant_saisi=type_montant,
        montant_paye=0,
        motif=data.get('motif') or 'Achat', motif_personnalise=data.get('motif_personnalise', ''),
        description=data.get('description', ''), date_echeance=date_echeance,
        statut='a_regler', created_by_nom=user_name,
    )
    db.session.add(achat)
    db.session.flush()

    from services.comptabilite_service import generer_ecriture_achat_fournisseur
    ecriture = generer_ecriture_achat_fournisseur(achat, user_name)
    achat_id = achat.id
    if ecriture:
        db.session.query(AchatFournisseur).filter(AchatFournisseur.id == achat_id).update(
            {'ecriture_id': ecriture.id}, synchronize_session=False)

    db.session.commit()
    return jsonify({'success': True, 'id': achat_id})


@compta_bp.route('/api/fournisseurs/achats/<int:achat_id>/regler', methods=['POST'])
def api_regler_achat_fournisseur(achat_id):
    """Enregistre un règlement (partiel ou total) — c'est le SEUL moment où
    la dette fournisseur impacte réellement la caisse (Débit 401 / Crédit
    trésorerie). Une ligne miroir est aussi insérée dans `depenses` (motif
    "Règlement fournisseur") pour que le calcul de solde de caisse existant
    (SUM(depenses.montant), utilisé tel quel à plusieurs endroits de l'appli)
    reflète cette sortie de caisse sans qu'il faille toucher chacun de ces
    endroits — la charge, elle, a déjà été comptabilisée à l'achat, donc
    cette ligne `depenses` n'est PAS repassée par generer_ecriture_depense
    (qui redébiterait une charge en double)."""
    structure_id = session.get('structure_id')
    user_name = session.get('user_name', 'System')
    data = request.json or {}

    # ⭐⭐ SÉCURITÉ : with_for_update() verrouille la ligne jusqu'au commit
    # de cette requête — sans ça, deux règlements très rapprochés sur le
    # même achat (double-clic, ou deux personnes en même temps) lisaient
    # tous les deux le même reste_a_payer avant que l'un des deux
    # n'écrive, passant chacun la vérification de montant alors que le
    # total des deux dépassait ce qui était réellement dû.
    achat = AchatFournisseur.query.filter_by(id=achat_id, structure_id=structure_id).with_for_update().first()
    if not achat:
        return jsonify({'error': 'Achat non trouvé'}), 404

    try:
        montant = float(data.get('montant', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Montant invalide'}), 400

    reste = achat.reste_a_payer()
    if montant <= 0 or montant > reste + 0.5:
        return jsonify({'error': f'Montant invalide (reste à payer : {reste} FCFA)'}), 400

    # ⭐ Garde-fou solde de caisse — jusqu'ici absent ici alors qu'il existe
    # déjà sur "Ajouter une dépense" (api_add_depense) : un règlement
    # fournisseur en espèces/caisse pouvait faire passer la caisse au
    # négatif sans aucun avertissement. `force=true` permet de passer outre
    # explicitement (ex: règlement par banque alors que la caisse espèces
    # est le seul indicateur suivi ici) — voir bouton "Régler quand même".
    if not data.get('force'):
        from services.comptabilite_service import solde_caisse_disponible
        solde = solde_caisse_disponible(structure_id)
        if montant > solde:
            return jsonify({
                'error': f'Solde de caisse insuffisant (solde actuel : {int(solde)} FCFA). '
                         f'Réglez depuis la banque ou confirmez quand même.',
                'solde_insuffisant': True, 'solde_actuel': solde,
            }), 400

    reglement = ReglementFournisseur(
        achat_id=achat.id, fournisseur_id=achat.fournisseur_id, montant=montant,
        mode_paiement=data.get('mode_paiement', 'especes'),
        reference=data.get('reference', ''), notes=data.get('notes', ''),
        created_by_nom=user_name,
    )
    db.session.add(reglement)
    db.session.flush()

    nouveau_paye = float(achat.montant_paye or 0) + montant
    nouveau_statut = 'reglee' if nouveau_paye >= float(achat.montant_total or 0) - 0.5 else 'a_regler'
    db.session.query(AchatFournisseur).filter(AchatFournisseur.id == achat.id).update(
        {'montant_paye': nouveau_paye, 'statut': nouveau_statut}, synchronize_session=False)

    # ⭐ Ligne miroir dans `depenses` — reflète la sortie de caisse réelle
    # pour le calcul de solde existant, SANS repasser par
    # generer_ecriture_depense (la charge est déjà comptabilisée à l'achat).
    depense_miroir = Depense(
        structure_id=structure_id, montant=montant,
        motif=f"Règlement fournisseur — {achat.fournisseur.nom if achat.fournisseur else ''}",
        description=f"Règlement de l'achat #{achat.id}", fournisseur_id=achat.fournisseur_id,
        created_by_nom=user_name,
    )
    db.session.add(depense_miroir)
    db.session.flush()

    from services.comptabilite_service import generer_ecriture_reglement_fournisseur
    achat_ref = AchatFournisseur.query.get(achat.id)
    ecriture = generer_ecriture_reglement_fournisseur(reglement, achat_ref, user_name)
    reglement_id = reglement.id
    if ecriture:
        db.session.query(ReglementFournisseur).filter(ReglementFournisseur.id == reglement_id).update(
            {'ecriture_id': ecriture.id}, synchronize_session=False)

    db.session.commit()
    return jsonify({'success': True, 'id': reglement_id, 'reste_a_payer': achat_ref.reste_a_payer()})


# ============================================================
# TAFIRE (flux de trésorerie simplifié)
# ============================================================

@compta_bp.route('/api/rapports/tafire')
def api_tafire():
    structure_id = session.get('structure_id')
    annee = request.args.get('annee', datetime.now().year, type=int)
    return jsonify(get_tafire(structure_id, annee))