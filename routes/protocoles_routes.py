# ============================================================
# ROUTES POUR LES PROTOCOLES MEDICAUX
# ============================================================

from flask import Blueprint, request, jsonify, render_template, session
from functools import wraps
from datetime import datetime

from models import db, Structure, ProtocoleMedical, HistoriqueProtocole, ProtocolePatient, Patient, Medecin
from services.protocoles_service import ProtocolesService

protocoles_bp = Blueprint('protocoles', __name__, url_prefix='/protocoles')

from sheets_helper import sheets_helper


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Non autorisé'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================ 
# PAGE PRINCIPALE
# ============================================================

@protocoles_bp.route('')
@login_required
def page_protocoles():
    """Page de gestion des protocoles"""
    structure_id = session.get('structure_id')
    
    categories = ProtocolesService.CATEGORIES
    statuts = ProtocolesService.STATUTS
    
    return render_template(
        'protocoles.html',
        categories=categories,
        statuts=statuts
    )

# ============================================================
# API: LISTE DES PROTOCOLES
# ============================================================

@protocoles_bp.route('/api/liste', methods=['GET'])
@login_required
def api_liste_protocoles():
    """API: Liste des protocoles"""
    structure_id = session.get('structure_id')
    
    categorie = request.args.get('categorie')
    statut = request.args.get('statut')
    specialite = request.args.get('specialite')
    search = request.args.get('search')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    protocoles, total = ProtocolesService.get_liste(
        structure_id=structure_id,
        categorie=categorie,
        statut=statut,
        specialite=specialite,
        search=search,
        limit=limit,
        offset=offset
    )
    
    return jsonify({
        'success': True,
        'data': [p.to_dict() for p in protocoles],
        'total': total,
        'limit': limit,
        'offset': offset
    })

# ============================================================
# API: CRÉER UN PROTOCOLE
# ============================================================

@protocoles_bp.route('/api/creer', methods=['POST'])
@login_required
def api_creer_protocole():
    """API: Créer un nouveau protocole"""
    structure_id = session.get('structure_id')
    data = request.json

    # Récupérer le nom depuis la session ou Google Sheets
    utilisateur_nom = session.get('user_nom')
    if not utilisateur_nom or utilisateur_nom == 'Systeme':
        user_id = session.get('user_id')
        if user_id:
            # Essayer de récupérer depuis Google Sheets
            utilisateur_nom = sheets_helper.get_user_by_id(user_id, structure_id)
            if utilisateur_nom:
                session['user_nom'] = utilisateur_nom
    
    if not utilisateur_nom:
        utilisateur_nom = 'Systeme'  # ← CORRIGÉ : guillemet fermant ajouté
    
    # 🔥 LOG POUR VOIR CE QUI EST ENVOYE
    print("=== DONNEES RECUES ===")
    print(data)
    
    if not data:
        return jsonify({'success': False, 'error': 'Données manquantes'}), 400
    
    # Vérifier les champs obligatoires
    if not data.get('titre'):
        return jsonify({'success': False, 'error': 'Le titre est obligatoire'}), 400
    if not data.get('categorie'):
        return jsonify({'success': False, 'error': 'La catégorie est obligatoire'}), 400
    if not data.get('contenu'):
        return jsonify({'success': False, 'error': 'Le contenu est obligatoire'}), 400
    
    succes, resultat = ProtocolesService.creer(
        data=data,
        structure_id=structure_id,
        utilisateur_nom=utilisateur_nom  # ← CORRIGÉ : utiliser la variable locale
    )
    
    if succes:
        return jsonify({'success': True, 'data': resultat})
    else:
        return jsonify({'success': False, 'error': resultat.get('error')}), 400

# ============================================================
# API: RÉCUPÉRER UN PROTOCOLE
# ============================================================

@protocoles_bp.route('/api/<int:protocole_id>', methods=['GET'])
@login_required
def api_get_protocole(protocole_id):
    """API: Récupérer un protocole"""
    structure_id = session.get('structure_id')
    
    protocole = ProtocolesService.get_par_id(protocole_id, structure_id)
    if not protocole:
        return jsonify({'success': False, 'error': 'Protocole non trouvé'}), 404
    
    return jsonify({'success': True, 'data': protocole.to_dict()})

# ============================================================
# API: MODIFIER UN PROTOCOLE
# ============================================================

@protocoles_bp.route('/api/<int:protocole_id>', methods=['PUT'])
@login_required
def api_modifier_protocole(protocole_id):
    """API: Modifier un protocole"""
    structure_id = session.get('structure_id')
    data = request.json
    
    # Récupérer le nom depuis la session ou Google Sheets
    utilisateur_nom = session.get('user_nom')
    if not utilisateur_nom or utilisateur_nom == 'Systeme':
        user_id = session.get('user_id')
        if user_id:
            utilisateur_nom = sheets_helper.get_user_by_id(user_id, structure_id)
            if utilisateur_nom:
                session['user_nom'] = utilisateur_nom
    
    if not utilisateur_nom:
        utilisateur_nom = 'Systeme'
    
    if not data:
        return jsonify({'success': False, 'error': 'Données manquantes'}), 400
    
    succes, resultat = ProtocolesService.modifier(
        protocole_id=protocole_id,
        structure_id=structure_id,
        data=data,
        utilisateur_nom=utilisateur_nom
    )
    
    if succes:
        return jsonify({'success': True, 'data': resultat})
    else:
        return jsonify({'success': False, 'error': resultat.get('error')}), 400

# ============================================================
# API: CHANGER LE STATUT
# ============================================================

@protocoles_bp.route('/api/<int:protocole_id>/statut', methods=['POST'])
@login_required
def api_changer_statut(protocole_id):
    """API: Changer le statut d'un protocole"""
    structure_id = session.get('structure_id')
    data = request.json
    
    nouveau_statut = data.get('statut')
    if not nouveau_statut:
        return jsonify({'success': False, 'error': 'Statut requis'}), 400
    
    succes, resultat = ProtocolesService.changer_statut(
        protocole_id=protocole_id,
        structure_id=structure_id,
        nouveau_statut=nouveau_statut,
        utilisateur_nom=session.get('user_nom', 'Systeme')
    )
    
    if succes:
        return jsonify({'success': True, 'data': resultat})
    else:
        return jsonify({'success': False, 'error': resultat.get('error')}), 400

# ============================================================
# API: DUPLIQUER UN PROTOCOLE
# ============================================================

@protocoles_bp.route('/api/<int:protocole_id>/dupliquer', methods=['POST'])
@login_required
def api_dupliquer_protocole(protocole_id):
    """API: Dupliquer un protocole"""
    structure_id = session.get('structure_id')
    
    succes, resultat = ProtocolesService.dupliquer(
        protocole_id=protocole_id,
        structure_id=structure_id,
        utilisateur_nom=session.get('user_nom', 'Systeme')
    )
    
    if succes:
        return jsonify({'success': True, 'data': resultat})
    else:
        return jsonify({'success': False, 'error': resultat.get('error')}), 400

# ============================================================
# API: SUPPRIMER UN PROTOCOLE
# ============================================================

@protocoles_bp.route('/api/<int:protocole_id>', methods=['DELETE'])
@login_required
def api_supprimer_protocole(protocole_id):
    """API: Supprimer un protocole"""
    structure_id = session.get('structure_id')
    
    succes, resultat = ProtocolesService.supprimer(
        protocole_id=protocole_id,
        structure_id=structure_id,
        utilisateur_nom=session.get('user_nom', 'Systeme')
    )
    
    if succes:
        return jsonify({'success': True, 'data': resultat})
    else:
        return jsonify({'success': False, 'error': resultat.get('error')}), 400

# ============================================================
# API: ASSIGNER À UN PATIENT
# ============================================================

@protocoles_bp.route('/api/<int:protocole_id>/assigner', methods=['POST'])
@login_required
def api_assigner_protocole(protocole_id):
    """API: Assigner un protocole à un patient"""
    structure_id = session.get('structure_id')
    data = request.json
    
    patient_id = data.get('patient_id')
    date_debut = data.get('date_debut')
    notes = data.get('notes', '')
    
    if not patient_id or not date_debut:
        return jsonify({'success': False, 'error': 'patient_id et date_debut requis'}), 400
    
    succes, resultat = ProtocolesService.assigner_a_patient(
        protocole_id=protocole_id,
        structure_id=structure_id,
        patient_id=patient_id,
        date_debut=date_debut,
        notes=notes
    )
    
    if succes:
        return jsonify({'success': True, 'data': resultat})
    else:
        return jsonify({'success': False, 'error': resultat.get('error')}), 400

# ============================================================
# API: PROTOCOLES D'UN PATIENT
# ============================================================

@protocoles_bp.route('/api/patient/<int:patient_id>', methods=['GET'])
@login_required
def api_protocoles_patient(patient_id):
    """API: Récupérer les protocoles d'un patient"""
    structure_id = session.get('structure_id')
    
    protocoles = ProtocolesService.get_protocoles_patient(
        patient_id=patient_id,
        structure_id=structure_id
    )
    
    return jsonify({'success': True, 'data': protocoles})

@protocoles_bp.route('/api/<int:protocole_id>/print', methods=['GET'])
@login_required
def api_print_protocole(protocole_id):
    """API: Page d'impression d'un protocole avec sélection patient/médecin"""
    structure_id = session.get('structure_id')
    
    protocole = ProtocolesService.get_par_id(protocole_id, structure_id)
    if not protocole:
        return jsonify({'success': False, 'error': 'Protocole non trouvé'}), 404
    
    # ============================================================
    # RÉCUPÉRER LA STRUCTURE DEPUIS GOOGLE SHEETS
    # ============================================================
    
    structure = None
    
    try:
        print("=== RECHERCHE STRUCTURE ===")
        print(f"structure_id: {structure_id}")
        
        # Récupérer toutes les structures
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        print(f"Nombre de structures trouvées: {len(structures)}")
        
        # Afficher la première structure pour voir sa structure
        if structures:
            print(f"Première structure: {structures[0]}")
        
        # Chercher la structure avec le bon ID
        for s in structures:
            print(f"ID dans Sheets: {s.get('ID')} vs {structure_id}")
            if str(s.get('ID')) == str(structure_id):
                # ⭐ Récupérer l'adresse brute
                adresse_brute = s.get('adresse') or ''
                
                # ⭐ Formater l'adresse avec la fonction
                adresse_formatee = sheets_helper.format_adresse(adresse_brute)
                
                structure = {
                    'nom': s.get('nom') or 'Hopital',
                    'adresse': adresse_formatee,  # ⭐ Adresse formatée
                    'telephone': s.get('telephone') or '',
                    'email': s.get('email') or '',
                    'logo_url': s.get('logo_url') or ''
                }
                print(f"Structure trouvée: {structure}")
                break
        
        if not structure:
            print("Structure non trouvée dans Sheets")
            
    except Exception as e:
        print(f"Erreur récupération structure: {e}")
        import traceback
        traceback.print_exc()
    
    # Fallback
    if not structure:
        structure = {
            'nom': 'Hopital',
            'adresse': '',
            'telephone': '',
            'email': '',
            'logo_url': ''
        }
    
    # Récupérer les patients et médecins
    patients = Patient.query.filter_by(structure_id=structure_id).order_by(Patient.nom).all()
    medecins = Medecin.query.filter_by(structure_id=structure_id, actif=True).order_by(Medecin.nom).all()
    
    return render_template(
        'print_protocole.html',
        protocole=protocole,
        structure=structure,
        patients=patients,
        medecins=medecins,
        now=datetime.now()
    )

@protocoles_bp.route('/api/patients/liste', methods=['GET'])
@login_required
def api_patients_liste():
    """API: Liste des patients pour sélection"""
    structure_id = session.get('structure_id')
    
    patients = Patient.query.filter_by(structure_id=structure_id).order_by(Patient.nom).all()
    
    result = []
    for p in patients:
        result.append({
            'id': p.id,
            'nom': p.nom,
            'prenom': p.prenom or '',
            'telephone': p.telephone or ''
        })
    
    return jsonify({'success': True, 'data': result})


@protocoles_bp.route('/api/medecins/liste', methods=['GET'])
@login_required
def api_medecins_liste():
    """API: Liste des médecins pour sélection"""
    structure_id = session.get('structure_id')
    
    medecins = Medecin.query.filter_by(structure_id=structure_id, actif=True).order_by(Medecin.nom).all()
    
    result = []
    for m in medecins:
        result.append({
            'id': m.id,
            'nom': m.nom,
            'prenom': m.prenom or '',
            'titre': m.titre or 'Dr',
            'specialite': m.specialite or ''
        })
    
    return jsonify({'success': True, 'data': result})

@protocoles_bp.route('/api/<int:protocole_id>/historique', methods=['GET'])
@login_required
def api_historique_protocole(protocole_id):
    """API: Récupérer l'historique d'un protocole"""
    structure_id = session.get('structure_id')
    
    protocole = ProtocolesService.get_par_id(protocole_id, structure_id)
    if not protocole:
        return jsonify({'success': False, 'error': 'Protocole non trouvé'}), 404
    
    historique = HistoriqueProtocole.query.filter_by(
        protocole_id=protocole_id
    ).order_by(HistoriqueProtocole.created_at.desc()).all()
    
    result = []
    for h in historique:
        result.append({
            'id': h.id,
            'action': h.action,
            'utilisateur_nom': h.utilisateur_nom or 'Systeme',
            'commentaire': h.commentaire or '',
            'date': h.created_at.strftime('%d/%m/%Y à %H:%M') if h.created_at else '',
            'ancien_contenu': h.ancien_contenu,
            'nouveau_contenu': h.nouveau_contenu
        })
    
    return jsonify({'success': True, 'data': result})