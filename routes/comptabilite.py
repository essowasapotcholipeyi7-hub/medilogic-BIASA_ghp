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
    Fournisseur, AchatFournisseur, ReglementFournisseur, Depense
)
from services.comptabilite_service import get_soldes_caisses, creer_ecriture, COMPTE_CLIENTS_PATIENTS
from utils.plan_comptable_syscohada import (
    COMPTE_BANQUE, COMPTE_CAISSE, COMPTE_IMMO_MATERIEL_MEDICAL, COMPTE_AMORT_MATERIEL_MEDICAL,
)

compta_bp = Blueprint('comptabilite', __name__, url_prefix='/comptabilite')


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
    structure_id = session.get('structure_id')
    
    total_ecritures = EcritureComptable.query.filter_by(structure_id=structure_id).count()
    en_attente = EcritureComptable.query.filter_by(structure_id=structure_id, statut='en_attente').count()
    validees = EcritureComptable.query.filter_by(structure_id=structure_id, statut='valide').count()
    
    total_debit = db.session.query(db.func.sum(LigneEcriture.debit)).filter(
        LigneEcriture.ecriture.has(EcritureComptable.structure_id == structure_id)
    ).scalar() or 0
    
    total_credit = db.session.query(db.func.sum(LigneEcriture.credit)).filter(
        LigneEcriture.ecriture.has(EcritureComptable.structure_id == structure_id)
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
            'solde': float(c.get_solde()) if c.get_solde() else 0
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
    
    ecritures = query.order_by(
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
            commentaire=data.get('commentaire')
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
        
        ecriture.date_ecriture = date_ecriture
        ecriture.libelle = data.get('libelle')
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
    """⭐ NOUVEAU : statut de l'exercice comptable en cours — onglet
    "Exercice comptable" (SYSCOHADA : l'exercice comptable coïncide avec
    l'année civile, sauf dérogation)."""
    structure_id = session.get('structure_id')
    annee_courante = datetime.now().year

    clotures = Cloture.query.filter_by(structure_id=structure_id).order_by(Cloture.annee.desc()).all()
    annees_cloturees = {c.annee for c in clotures}

    nb_ecritures_annee = EcritureComptable.query.filter(
        EcritureComptable.structure_id == structure_id,
        EcritureComptable.date_ecriture >= f"{annee_courante}-01-01",
        EcritureComptable.date_ecriture <= f"{annee_courante}-12-31",
    ).count()

    nb_brouillons = EcritureComptable.query.filter(
        EcritureComptable.structure_id == structure_id,
        EcritureComptable.statut.in_(['brouillon', 'en_attente']),
    ).count()

    return jsonify({
        'annee_courante': annee_courante,
        'exercice_ouvert': annee_courante not in annees_cloturees,
        'nb_ecritures_exercice_courant': nb_ecritures_annee,
        'nb_ecritures_a_valider': nb_brouillons,
        'clotures': [{
            'annee': c.annee,
            'date_cloture': c.date_cloture.strftime('%Y-%m-%d %H:%M') if c.date_cloture else '',
            'created_by': c.created_by or '-',
        } for c in clotures],
    })


@compta_bp.route('/api/cloture', methods=['POST'])
def api_cloture():
    structure_id = session.get('structure_id')
    annee = request.json.get('annee')
    
    if not annee:
        return jsonify({'error': 'Annee requise'}), 400
    
    try:
        existing = Cloture.query.filter_by(
            structure_id=structure_id,
            annee=annee
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Cette annee est deja cloturee'}), 400
        
        date_debut = f"{annee}-01-01"
        date_fin = f"{annee}-12-31"
        
        ecritures = EcritureComptable.query.filter(
            EcritureComptable.structure_id == structure_id,
            EcritureComptable.date_ecriture >= date_debut,
            EcritureComptable.date_ecriture <= date_fin,
            EcritureComptable.statut == 'valide'
        ).all()
        
        nb_ecritures = 0
        for ecriture in ecritures:
            ecriture.cloturee = True
            ecriture.date_cloture = datetime.utcnow()
            nb_ecritures += 1
        
        cloture = Cloture(
            structure_id=structure_id,
            annee=annee,
            date_cloture=datetime.utcnow(),
            created_by=session.get('user_name', 'System')
        )
        db.session.add(cloture)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Cloture de l\'annee {annee} effectuee ({nb_ecritures} ecritures)'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


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


@compta_bp.route('/api/rapports/grand_livre')
def api_grand_livre():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    compte_id = request.args.get('compte_id', type=int)  # vue "grand livre d'un seul compte"

    return jsonify(generer_grand_livre(structure_id, date_debut, date_fin, compte_id))


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


@compta_bp.route('/api/rapports/balance')
def api_balance():
    structure_id = session.get('structure_id')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    
    return jsonify(generer_balance(structure_id, date_debut, date_fin))


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
            l.credit
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
        'credit': float(row.credit or 0)
    } for row in rows]


def generer_grand_livre(structure_id, date_debut, date_fin, compte_id=None):
    from sqlalchemy import text

    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None

    result = db.session.execute(text("""
        SELECT
            e.date_ecriture,
            c.numero as compte_numero,
            c.nom as compte_nom,
            e.libelle,
            e.piece_justificative,
            l.debit,
            l.credit
        FROM ecritures_comptables e
        JOIN lignes_ecritures l ON e.id = l.ecriture_id
        JOIN comptes_comptables c ON l.compte_id = c.id
        WHERE e.structure_id = :structure_id
        AND e.statut = 'valide'
        AND (:date_debut IS NULL OR e.date_ecriture >= :date_debut)
        AND (:date_fin IS NULL OR e.date_ecriture <= :date_fin)
        AND (:compte_id IS NULL OR l.compte_id = :compte_id)
        ORDER BY c.numero, e.date_ecriture
    """), {
        'structure_id': structure_id,
        'date_debut': date_debut_obj.strftime('%Y-%m-%d') if date_debut_obj else None,
        'date_fin': date_fin_obj.strftime('%Y-%m-%d') if date_fin_obj else None,
        'compte_id': compte_id,
    })

    rows = result.fetchall()

    return [{
        'date': row.date_ecriture.strftime('%Y-%m-%d') if row.date_ecriture else '',
        'compte_numero': row.compte_numero or '',
        'compte_nom': row.compte_nom or '',
        'libelle': row.libelle or '',
        'piece': row.piece_justificative or '',
        'debit': float(row.debit or 0),
        'credit': float(row.credit or 0)
    } for row in rows]


def generer_balance(structure_id, date_debut, date_fin):
    date_debut_obj = parse_date(date_debut) if date_debut else None
    date_fin_obj = parse_date(date_fin) if date_fin else None
    
    comptes = CompteComptable.query.filter_by(
        structure_id=structure_id,
        actif=True
    ).order_by(CompteComptable.numero).all()
    
    result = []
    for compte in comptes:
        total_debit = 0
        total_credit = 0
        
        for ligne in compte.lignes:
            if ligne.ecriture.statut != 'valide':
                continue
            
            if date_debut_obj and ligne.ecriture.date_ecriture < date_debut_obj:
                continue
            if date_fin_obj and ligne.ecriture.date_ecriture > date_fin_obj:
                continue
            
            total_debit += float(ligne.debit) if ligne.debit else 0
            total_credit += float(ligne.credit) if ligne.credit else 0
        
        solde = total_debit - total_credit
        
        if total_debit > 0 or total_credit > 0:
            result.append({
                'compte_numero': compte.numero,
                'compte_nom': compte.nom,
                'total_debit': total_debit,
                'total_credit': total_credit,
                'solde': solde
            })
    
    return result


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
        resultat_periode = get_compte_resultat(structure_id, None, date_fin)
        resultat_net = resultat_periode.get('resultat', 0)
        if abs(resultat_net) > 0.5:
            capitaux_propres.append({
                'numero': '120' if resultat_net >= 0 else '129',
                'nom': f"Résultat net de l'exercice ({resultat_periode.get('resultat_text', '')})",
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
            'est_equilibre': abs(total_actif - (total_passif + total_capitaux)) < 1
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

    return jsonify([{
        'id': c.id, 'numero': c.numero, 'nom': c.nom,
        'solde_comptable': float(c.get_solde() or 0),
    } for c in comptes])


@compta_bp.route('/api/rapprochement/releves', methods=['GET'])
def api_get_releves():
    structure_id = session.get('structure_id')

    compte_id_filtre = request.args.get('compte_id', type=int)

    query = ReleveBancaire.query.filter_by(structure_id=structure_id)
    if compte_id_filtre:
        query = query.filter_by(compte_id=compte_id_filtre)

    releves = query.order_by(ReleveBancaire.date_releve.desc()).all()

    result = []
    for r in releves:
        compte = r.compte_id and CompteComptable.query.get(r.compte_id)
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

def _donnees_rapport(type_rapport, structure_id, date_debut, date_fin, journal_code=None, compte_id=None):
    """Point d'entrée commun (imprimable ET export TXT) — construit les
    données d'un rapport en respectant les mêmes filtres que l'écran
    (journal sélectionné, compte unique pour le grand livre). ⭐ FIX :
    auparavant, print_rapport() ignorait journal_code/compte_id, donc
    "Imprimer" ressortait TOUJOURS tous les journaux mélangés même si un
    seul était filtré à l'écran."""
    if type_rapport == 'journal':
        data = generer_journal(structure_id, date_debut, date_fin, journal_code)
        titre = "Journal " + (EcritureComptable.JOURNAUX.get(journal_code, journal_code) if journal_code else "comptable (tous journaux)")
    elif type_rapport == 'grand_livre':
        data = generer_grand_livre(structure_id, date_debut, date_fin, compte_id)
        if compte_id:
            compte = CompteComptable.query.get(compte_id)
            titre = f"Grand livre — {compte.numero} {compte.nom}" if compte else "Grand livre"
        else:
            titre = "Grand livre (tous comptes)"
    elif type_rapport == 'balance':
        data = generer_balance(structure_id, date_debut, date_fin)
        titre = "Balance comptable"
    elif type_rapport == 'resultat':
        data = get_compte_resultat(structure_id, date_debut, date_fin)
        titre = "Compte de résultat"
    elif type_rapport == 'bilan':
        data = get_bilan(structure_id, date_fin)
        titre = "Bilan comptable"
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

    data, titre = _donnees_rapport(type_rapport, structure_id, date_debut, date_fin, journal_code, compte_id)
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


def _ligne_txt(*colonnes, largeurs):
    return "  ".join(str(c).ljust(l) for c, l in zip(colonnes, largeurs))


@compta_bp.route('/rapport/export-txt/<type_rapport>')
def export_rapport_txt(type_rapport):
    """Export en texte brut (.txt) d'UN rapport à la fois, avec les mêmes
    filtres que l'écran (journal sélectionné, compte unique, dates) —
    demandé explicitement : pouvoir imprimer/exporter chaque journal
    individuellement, le grand livre, la balance, le résultat, le bilan,
    plutôt qu'un seul export mélangeant tout."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return "Structure non trouvée", 404

    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    journal_code = request.args.get('journal_code') or None
    compte_id = request.args.get('compte_id', type=int)

    data, titre = _donnees_rapport(type_rapport, structure_id, date_debut, date_fin, journal_code, compte_id)
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

    lignes_txt = []
    lignes_txt.append("=" * 78)
    lignes_txt.append((structure_nom or "MEDILOGIC").upper())
    lignes_txt.append(titre.upper())
    periode = f"Période : {date_debut or '...'} au {date_fin or '...'}" if type_rapport != 'bilan' else f"Au {date_fin or datetime.now().strftime('%Y-%m-%d')}"
    lignes_txt.append(periode)
    lignes_txt.append(f"Édité le {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lignes_txt.append("=" * 78)
    lignes_txt.append("")

    if type_rapport == 'journal':
        largeurs = [10, 14, 34, 10, 26, 14, 14]
        lignes_txt.append(_ligne_txt("Date", "Pièce", "Libellé", "Journal", "Compte", "Débit", "Crédit", largeurs=largeurs))
        lignes_txt.append("-" * 78)
        total_d = total_c = 0
        for l in data:
            lignes_txt.append(_ligne_txt(
                l['date'], l['piece'][:14], l['libelle'][:34], l['journal_code'],
                f"{l['compte_numero']} {l['compte_nom']}"[:26],
                _fmt_montant(l['debit']) if l['debit'] else '', _fmt_montant(l['credit']) if l['credit'] else '',
                largeurs=largeurs))
            total_d += l['debit']; total_c += l['credit']
        lignes_txt.append("-" * 78)
        lignes_txt.append(_ligne_txt("", "", "", "", "TOTAL", _fmt_montant(total_d), _fmt_montant(total_c), largeurs=largeurs))

    elif type_rapport == 'grand_livre':
        largeurs = [10, 30, 14, 34, 14, 14]
        lignes_txt.append(_ligne_txt("Date", "Compte", "Pièce", "Libellé", "Débit", "Crédit", largeurs=largeurs))
        lignes_txt.append("-" * 78)
        total_d = total_c = 0
        for l in data:
            lignes_txt.append(_ligne_txt(
                l['date'], f"{l['compte_numero']} {l['compte_nom']}"[:30], l['piece'][:14], l['libelle'][:34],
                _fmt_montant(l['debit']) if l['debit'] else '', _fmt_montant(l['credit']) if l['credit'] else '',
                largeurs=largeurs))
            total_d += l['debit']; total_c += l['credit']
        lignes_txt.append("-" * 78)
        lignes_txt.append(_ligne_txt("", "", "", "TOTAL", _fmt_montant(total_d), _fmt_montant(total_c), largeurs=largeurs))

    elif type_rapport == 'balance':
        largeurs = [40, 16, 16, 16]
        lignes_txt.append(_ligne_txt("Compte", "Débit", "Crédit", "Solde", largeurs=largeurs))
        lignes_txt.append("-" * 78)
        total_d = total_c = total_s = 0
        for l in data:
            lignes_txt.append(_ligne_txt(
                f"{l['compte_numero']} {l['compte_nom']}"[:40],
                _fmt_montant(l['total_debit']), _fmt_montant(l['total_credit']), _fmt_montant(l['solde']),
                largeurs=largeurs))
            total_d += l['total_debit']; total_c += l['total_credit']; total_s += l['solde']
        lignes_txt.append("-" * 78)
        lignes_txt.append(_ligne_txt("TOTAL", _fmt_montant(total_d), _fmt_montant(total_c), _fmt_montant(total_s), largeurs=largeurs))

    elif type_rapport == 'resultat':
        largeurs = [50, 20]
        lignes_txt.append("CHARGES")
        lignes_txt.append("-" * 78)
        for l in data['charges']:
            lignes_txt.append(_ligne_txt(f"{l['numero']} {l['nom']}"[:50], _fmt_montant(l['montant']), largeurs=largeurs))
        lignes_txt.append(_ligne_txt("TOTAL CHARGES", _fmt_montant(data['total_charges']), largeurs=largeurs))
        lignes_txt.append("")
        lignes_txt.append("PRODUITS")
        lignes_txt.append("-" * 78)
        for l in data['produits']:
            lignes_txt.append(_ligne_txt(f"{l['numero']} {l['nom']}"[:50], _fmt_montant(l['montant']), largeurs=largeurs))
        lignes_txt.append(_ligne_txt("TOTAL PRODUITS", _fmt_montant(data['total_produits']), largeurs=largeurs))
        lignes_txt.append("")
        lignes_txt.append("=" * 78)
        lignes_txt.append(_ligne_txt(f"RÉSULTAT ({data['resultat_text']})", _fmt_montant(data['resultat']), largeurs=largeurs))

    elif type_rapport == 'bilan':
        largeurs = [50, 20]
        lignes_txt.append("ACTIF")
        lignes_txt.append("-" * 78)
        for l in data['actifs']:
            lignes_txt.append(_ligne_txt(f"{l['numero']} {l['nom']}"[:50], _fmt_montant(l['montant']), largeurs=largeurs))
        lignes_txt.append(_ligne_txt("TOTAL ACTIF", _fmt_montant(data['total_actif']), largeurs=largeurs))
        lignes_txt.append("")
        lignes_txt.append("PASSIF")
        lignes_txt.append("-" * 78)
        for l in data['passifs']:
            lignes_txt.append(_ligne_txt(f"{l['numero']} {l['nom']}"[:50], _fmt_montant(l['montant']), largeurs=largeurs))
        lignes_txt.append(_ligne_txt("TOTAL PASSIF", _fmt_montant(data['total_passif']), largeurs=largeurs))
        lignes_txt.append("")
        lignes_txt.append("CAPITAUX PROPRES")
        lignes_txt.append("-" * 78)
        for l in data['capitaux_propres']:
            lignes_txt.append(_ligne_txt(f"{l['numero']} {l['nom']}"[:50], _fmt_montant(l['montant']), largeurs=largeurs))
        lignes_txt.append(_ligne_txt("TOTAL CAPITAUX PROPRES", _fmt_montant(data['total_capitaux']), largeurs=largeurs))
        lignes_txt.append("")
        lignes_txt.append("=" * 78)
        lignes_txt.append(_ligne_txt("TOTAL PASSIF + CAPITAUX", _fmt_montant(data['total_passif_capitaux']), largeurs=largeurs))
        lignes_txt.append("Équilibré" if data['est_equilibre'] else "⚠️ NON ÉQUILIBRÉ")

    lignes_txt.append("")
    contenu = "\n".join(lignes_txt)

    nom_fichier = f"{type_rapport}"
    if journal_code:
        nom_fichier += f"_{journal_code}"
    if date_fin:
        nom_fichier += f"_{date_fin}"
    nom_fichier += ".txt"

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
    ecriture = generer_ecriture_provision(structure_id, montant_provisionne, facture.patient_nom, provision.id, user_name)
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
        structure_id, float(provision.montant_provisionne), provision.patient_nom, provision_id, user_name)

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
        provision.patient_nom, provision_id, user_name)

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
    ecriture = generer_ecriture_perte_creance(structure_id, montant, 0, facture.patient_nom, provision_id, user_name)

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

    achat = AchatFournisseur(
        structure_id=structure_id, fournisseur_id=fournisseur_id,
        montant_total=montant, montant_paye=0,
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

    achat = AchatFournisseur.query.filter_by(id=achat_id, structure_id=structure_id).first()
    if not achat:
        return jsonify({'error': 'Achat non trouvé'}), 404

    try:
        montant = float(data.get('montant', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Montant invalide'}), 400

    reste = achat.reste_a_payer()
    if montant <= 0 or montant > reste + 0.5:
        return jsonify({'error': f'Montant invalide (reste à payer : {reste} FCFA)'}), 400

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