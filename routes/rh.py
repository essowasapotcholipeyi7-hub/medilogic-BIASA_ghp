# routes/rh.py - VERSION CORRIGÉE ET OPTIMISÉE
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime, date, time, timedelta
from sqlalchemy import or_, and_, extract, func
import json
import traceback

from models import (db, Employe, Service, Conge, Permission, DocumentRH, SignatureRH,
                     Paie, ParametragePaie, EmpreinteEmploye, ParametragePointage, Pointage, VisageEmploye)

rh_bp = Blueprint('rh', __name__, url_prefix='/rh')

# ============================================================
# CONSTANTES
# ============================================================
CONGES_ANNUELS = 30  # ⭐ Nombre de jours de congés par année


def _clamp_personnes_a_charge(valeur, maximum=6):
    """Nombre de personnes à charge (déduction IRPP) : 0 à `maximum`."""
    try:
        n = int(valeur or 0)
    except (TypeError, ValueError):
        n = 0
    return max(0, min(n, maximum))

# ============================================================
# DÉCORATEURS
# ============================================================
def require_structure(f):
    """Décorateur pour vérifier la structure en session"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        structure_id = session.get('structure_id')
        if not structure_id:
            if request.method == 'GET':
                flash('Structure non trouvée. Veuillez vous reconnecter.', 'danger')
                return redirect(url_for('index'))
            return jsonify({'error': 'Structure non trouvée'}), 400
        return f(*args, structure_id=structure_id, **kwargs)
    return decorated


def get_structure_id():
    """Récupère le structure_id de la session"""
    return session.get('structure_id')


def get_statut_label(statut):
    """Retourne le libellé d'un statut"""
    labels = {
        'en_attente': '⏳ En attente',
        'approuve': '✅ Approuvé',
        'refuse': '❌ Refusé',
        'termine': '✔️ Terminé'
    }
    return labels.get(statut, statut)


def calculer_solde_conges(employe_id, annee):
    """
    Calcule le solde de congés pour un employé et une année donnée.
    ⭐ Fine couche au-dessus d'Employe.get_solde_detail() — SOURCE UNIQUE du
    calcul (models.py). Ne pas dupliquer la logique ici : cette fonction
    n'existe que pour garder la signature (employe_id, annee) attendue par
    les appelants historiques de ce module.
    """
    employe = Employe.query.get(employe_id)
    if not employe:
        return {'solde': 0, 'pris': 0, 'conges_pris': 0, 'permissions_pris': 0, 'total_annuel': CONGES_ANNUELS}
    return employe.get_solde_detail(annee)


def verifier_solde_avec_anticipation(employe_id, jours_demandes, annee_demande):
    """
    Vérifie si le solde est suffisant, sinon propose les années futures.
    ⭐ Délègue à Employe.verifier_conges_disponibles() (models.py) — même
    remarque que ci-dessus — en adaptant les noms de clés attendus par les
    appelants existants de ce module (solde_actuel / annees_proposees).
    """
    employe = Employe.query.get(employe_id)
    if not employe:
        return {'disponible': False, 'solde_actuel': 0, 'annee': annee_demande,
                'jours_demandes': jours_demandes, 'annees_proposees': [],
                'message': 'Employé introuvable'}

    resultat = employe.verifier_conges_disponibles(jours_demandes, annee_demande)

    if resultat['disponible']:
        return {
            'disponible': True,
            'solde_actuel': resultat['solde'],
            'annee': resultat['annee'],
            'message': resultat['message'],
        }

    return {
        'disponible': False,
        'solde_actuel': resultat['solde'],
        'annee': resultat['annee'],
        'jours_demandes': resultat.get('jours_demandes', jours_demandes),
        'annees_proposees': resultat.get('annees_futures', []),
        'message': resultat['message'],
    }


# ============================================================
# ROUTES PAGES
# ============================================================

@rh_bp.route('/')
@require_structure
def gestion_rh(structure_id):
    """Page principale de gestion RH"""
    return render_template('rh/gestion_rh.html')


@rh_bp.route('/employes')
@require_structure
def employes(structure_id):
    """⭐ Redirige vers l'onglet correspondant du hub unique (gestion_rh.html
    réimplémentait déjà la même liste — deux pages parallèles à maintenir).
    templates/rh/employes.html est conservé mais n'est plus servi."""
    return redirect(url_for('rh.gestion_rh') + '#personnel')


@rh_bp.route('/conges')
@require_structure
def conges(structure_id):
    """⭐ Voir note sur employes() ci-dessus."""
    return redirect(url_for('rh.gestion_rh') + '#conges')


@rh_bp.route('/permissions')
@require_structure
def permissions(structure_id):
    """⭐ Voir note sur employes() ci-dessus."""
    return redirect(url_for('rh.gestion_rh') + '#permissions')


@rh_bp.route('/services')
@require_structure
def services(structure_id):
    """⭐ Voir note sur employes() ci-dessus."""
    return redirect(url_for('rh.gestion_rh') + '#services')


@rh_bp.route('/dashboard')
@require_structure
def dashboard_rh(structure_id):
    """Dashboard RH — le tableau de bord vit dans l'onglet "Dashboard RH" du
    hub unique (gestion_rh.html) ; il n'y a pas de template dédié
    (rh/dashboard_rh.html n'existe pas — route corrigée)."""
    return redirect(url_for('rh.gestion_rh') + '#dashboardrh')


# ============================================================
# API - EMPLOYÉS
# ============================================================

@rh_bp.route('/api/employes')
@require_structure
def api_employes(structure_id):
    """API: Liste des employés avec filtres"""
    search = request.args.get('search', '').strip()
    service_id = request.args.get('service_id', '').strip()
    statut = request.args.get('statut', '').strip()
    sexe = request.args.get('sexe', '').strip()
    
    query = Employe.query.filter_by(structure_id=structure_id)
    
    if search:
        query = query.filter(
            or_(
                Employe.nom.ilike(f'%{search}%'),
                Employe.prenom.ilike(f'%{search}%'),
                Employe.matricule.ilike(f'%{search}%'),
                Employe.email.ilike(f'%{search}%'),
                Employe.telephone.ilike(f'%{search}%')
            )
        )
    
    if service_id and service_id.isdigit():
        query = query.filter_by(service_id=int(service_id))
    
    if statut:
        query = query.filter_by(statut=statut)
    
    if sexe:
        query = query.filter_by(sexe=sexe)
    
    employes = query.all()
    annee_actuelle = datetime.now().year
    
    result = []
    for e in employes:
        # ⭐ Calcul du solde avec 30 jours
        solde_info = calculer_solde_conges(e.id, annee_actuelle)
        
        result.append({
            'id': e.id,
            'matricule': e.matricule,
            'nom': e.nom,
            'prenom': e.prenom,
            'sexe': e.sexe,
            'service': e.service.nom if e.service else '',
            'poste': e.poste,
            'statut': e.statut,
            'telephone': e.telephone,
            'email': e.email,
            'date_embauche': e.date_embauche.strftime('%d/%m/%Y') if e.date_embauche else '',
            'solde_conges': solde_info['solde'],
            'service_id': e.service_id,
            'age': e.calculer_age() if hasattr(e, 'calculer_age') else None,
            # ⭐ CORRECTION : utiliser la méthode calculer_anciennete()
            'anciennete': e.calculer_anciennete() if hasattr(e, 'calculer_anciennete') else 0
        })
    
    return jsonify(result)

@rh_bp.route('/api/employes/<int:id>')
@require_structure
def api_employe_detail(structure_id, id):
    """API: Détail d'un employé"""
    employe = Employe.query.filter_by(id=id, structure_id=structure_id).first()
    if not employe:
        return jsonify({'error': 'Employé non trouvé'}), 404
    
    annee_actuelle = datetime.now().year
    solde_info = calculer_solde_conges(employe.id, annee_actuelle)
    
    return jsonify({
        'id': employe.id,
        'matricule': employe.matricule,
        'nom': employe.nom,
        'prenom': employe.prenom,
        'sexe': employe.sexe,
        'date_naissance': employe.date_naissance.strftime('%d/%m/%Y') if employe.date_naissance else '',
        'age': employe.calculer_age() if hasattr(employe, 'calculer_age') else None,
        'nationalite': employe.nationalite,
        'quartier': employe.quartier,
        'telephone': employe.telephone,
        'email': employe.email,
        'service_id': employe.service_id,
        'service': employe.service.nom if employe.service else '',
        'poste': employe.poste,
        'numero_poste': employe.numero_poste,
        'date_embauche': employe.date_embauche.strftime('%d/%m/%Y') if employe.date_embauche else '',
        # ⭐ CORRECTION : utiliser la méthode calculer_anciennete()
        'anciennete': employe.calculer_anciennete() if hasattr(employe, 'calculer_anciennete') else 0,
        'type_contrat': employe.type_contrat,
        'salaire_base': float(employe.salaire_base) if employe.salaire_base else 0,
        'personne_a_prevenir': employe.personne_a_prevenir,
        'telephone_prevenir': employe.telephone_prevenir,
        'lien_parente': employe.lien_parente,
        'statut': employe.statut,
        'solde_conges': solde_info['solde'],
        'conges_pris': solde_info['conges_pris'],
        'permissions_pris': solde_info['permissions_pris'],
        'total_annuel': CONGES_ANNUELS,
        'photo_url': employe.photo_url,
        # ⭐ Paramètres de paie individuels
        'secteur_paie': employe.secteur_paie or 'prive',
        'personnes_a_charge': employe.personnes_a_charge or 0,
        'taux_retraite_salarial_override': float(employe.taux_retraite_salarial_override) if employe.taux_retraite_salarial_override is not None else None,
        'taux_retraite_patronal_override': float(employe.taux_retraite_patronal_override) if employe.taux_retraite_patronal_override is not None else None,
        'taux_amu_salarial_override': float(employe.taux_amu_salarial_override) if employe.taux_amu_salarial_override is not None else None,
        'taux_amu_patronal_override': float(employe.taux_amu_patronal_override) if employe.taux_amu_patronal_override is not None else None,
    })

@rh_bp.route('/employe/ajouter', methods=['POST'])
@require_structure
def employe_ajouter(structure_id):
    """Ajouter un employé"""
    try:
        data = request.json
        
        # Validation des champs obligatoires
        required_fields = ['nom', 'prenom', 'sexe', 'telephone', 'service_id', 'poste', 'date_embauche']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Le champ {field} est obligatoire'}), 400
        
        # Génération du matricule
        # ⭐ La colonne matricule est UNIQUE au niveau de toute la table (pas
        # seulement par structure), alors que le compteur ci-dessous ne compte
        # que les employés de CETTE structure. Une structure encore vide (ex:
        # structure 10) recalcule "EMP-{année}-001", déjà pris par une autre
        # structure (ex: structure 1) → IntegrityError à l'ajout. On boucle
        # jusqu'à trouver un matricule réellement libre.
        annee = datetime.now().year
        count = Employe.query.filter_by(structure_id=structure_id).count() + 1
        matricule = f"EMP-{annee}-{str(count).zfill(3)}"
        while Employe.query.filter_by(matricule=matricule).first():
            count += 1
            matricule = f"EMP-{annee}-{str(count).zfill(3)}"

        employe = Employe(
            structure_id=structure_id,
            matricule=matricule,
            nom=data.get('nom').strip(),
            prenom=data.get('prenom').strip(),
            sexe=data.get('sexe'),
            date_naissance=datetime.strptime(data.get('date_naissance'), '%Y-%m-%d').date() if data.get('date_naissance') else None,
            nationalite=data.get('nationalite', '').strip(),
            quartier=data.get('quartier', '').strip(),
            telephone=data.get('telephone').strip(),
            email=data.get('email', '').strip(),
            service_id=int(data.get('service_id')),
            poste=data.get('poste').strip(),
            numero_poste=data.get('numero_poste', '').strip(),
            date_embauche=datetime.strptime(data.get('date_embauche'), '%Y-%m-%d').date(),
            type_contrat=data.get('type_contrat', 'CDI'),
            salaire_base=data.get('salaire_base', 0),
            personne_a_prevenir=data.get('personne_a_prevenir', '').strip(),
            telephone_prevenir=data.get('telephone_prevenir', '').strip(),
            lien_parente=data.get('lien_parente', '').strip(),
            statut='Actif',
            conges_annuels=CONGES_ANNUELS,  # ⭐ 30 jours
            secteur_paie=data.get('secteur_paie', 'prive') if data.get('secteur_paie') in ('prive', 'public') else 'prive',
            personnes_a_charge=_clamp_personnes_a_charge(data.get('personnes_a_charge', 0)),
        )
        
        db.session.add(employe)
        db.session.commit()

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='employe_ajoute',
                description=f"Employé ajouté — {employe.nom} {employe.prenom} ({matricule})",
                reference_type='employe', reference_id=employe.id,
                utilisateur_nom=session.get('user_name', 'System'),
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (employé #{employe.id}): {e}")

        return jsonify({
            'success': True,
            'id': employe.id,
            'matricule': matricule,
            'message': 'Employé ajouté avec succès'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur employe_ajouter: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/employe/<int:id>', methods=['PUT'])
@require_structure
def api_modifier_employe(structure_id, id):
    """Modifier un employé"""
    try:
        employe = Employe.query.filter_by(id=id, structure_id=structure_id).first()
        if not employe:
            return jsonify({'error': 'Employé non trouvé'}), 404
        
        data = request.json
        
        # Mise à jour des champs
        if 'nom' in data:
            employe.nom = data['nom'].strip()
        if 'prenom' in data:
            employe.prenom = data['prenom'].strip()
        if 'sexe' in data:
            employe.sexe = data['sexe']
        if 'date_naissance' in data and data['date_naissance']:
            employe.date_naissance = datetime.strptime(data['date_naissance'], '%Y-%m-%d').date()
        if 'nationalite' in data:
            employe.nationalite = data['nationalite'].strip()
        if 'quartier' in data:
            employe.quartier = data['quartier'].strip()
        if 'telephone' in data:
            employe.telephone = data['telephone'].strip()
        if 'email' in data:
            employe.email = data['email'].strip()
        if 'service_id' in data:
            employe.service_id = int(data['service_id'])
        if 'poste' in data:
            employe.poste = data['poste'].strip()
        if 'numero_poste' in data:
            employe.numero_poste = data['numero_poste'].strip()
        if 'date_embauche' in data and data['date_embauche']:
            employe.date_embauche = datetime.strptime(data['date_embauche'], '%Y-%m-%d').date()
        if 'type_contrat' in data:
            employe.type_contrat = data['type_contrat']
        if 'salaire_base' in data:
            employe.salaire_base = data['salaire_base']
        if 'personne_a_prevenir' in data:
            employe.personne_a_prevenir = data['personne_a_prevenir'].strip()
        if 'telephone_prevenir' in data:
            employe.telephone_prevenir = data['telephone_prevenir'].strip()
        if 'lien_parente' in data:
            employe.lien_parente = data['lien_parente'].strip()
        if 'statut' in data:
            employe.statut = data['statut']

        # ⭐ Paramètres de paie individuels
        if 'secteur_paie' in data and data['secteur_paie'] in ('prive', 'public'):
            employe.secteur_paie = data['secteur_paie']
        if 'personnes_a_charge' in data:
            parametrage = ParametragePaie.get_ou_creer(structure_id)
            employe.personnes_a_charge = _clamp_personnes_a_charge(
                data['personnes_a_charge'], int(parametrage.max_personnes_charge or 6))
        if 'taux_retraite_salarial_override' in data:
            v = data['taux_retraite_salarial_override']
            employe.taux_retraite_salarial_override = float(v) if v not in (None, '') else None
        if 'taux_retraite_patronal_override' in data:
            v = data['taux_retraite_patronal_override']
            employe.taux_retraite_patronal_override = float(v) if v not in (None, '') else None
        if 'taux_amu_salarial_override' in data:
            v = data['taux_amu_salarial_override']
            if v not in (None, ''):
                parametrage = ParametragePaie.get_ou_creer(structure_id)
                demi_amu = float(parametrage.amu_taux_global or 10) / 2.0
                v = min(float(v), demi_amu)  # ⭐ verrou AMU : jamais > moitié du taux global
                employe.taux_amu_salarial_override = v
            else:
                employe.taux_amu_salarial_override = None
        if 'taux_amu_patronal_override' in data:
            v = data['taux_amu_patronal_override']
            if v not in (None, ''):
                parametrage = ParametragePaie.get_ou_creer(structure_id)
                demi_amu = float(parametrage.amu_taux_global or 10) / 2.0
                v = max(float(v), demi_amu)  # ⭐ verrou AMU : jamais < moitié du taux global
                employe.taux_amu_patronal_override = v
            else:
                employe.taux_amu_patronal_override = None

        employe.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'id': employe.id,
            'message': 'Employé modifié avec succès'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur api_modifier_employe: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/employe/<int:id>', methods=['DELETE'])
@require_structure
def api_supprimer_employe(structure_id, id):
    """Supprimer un employé"""
    try:
        employe = Employe.query.filter_by(id=id, structure_id=structure_id).first()
        if not employe:
            return jsonify({'error': 'Employé non trouvé'}), 404
        
        # Vérifier les dépendances
        conges = Conge.query.filter_by(employe_id=id).count()
        permissions = Permission.query.filter_by(employe_id=id).count()
        
        if conges > 0 or permissions > 0:
            return jsonify({
                'error': f'Impossible de supprimer. {conges} congé(s) et {permissions} permission(s) existent.'
            }), 400
        
        db.session.delete(employe)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Employé supprimé avec succès'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur api_supprimer_employe: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/employe/<int:id>')
@require_structure
def employe_detail(structure_id, id):
    """Page de détail d'un employé"""
    employe = Employe.query.filter_by(id=id, structure_id=structure_id).first()
    if not employe:
        flash('Employé non trouvé', 'danger')
        return redirect(url_for('rh.employes'))
    
    # ⭐⭐ CALCULER SOLDE_INFO ⭐⭐
    annee_actuelle = datetime.now().year
    solde_info = calculer_solde_conges(employe.id, annee_actuelle)
    
    return render_template('rh/employe_detail.html', 
                         employe=employe,
                         solde_info=solde_info)  # ⭐ AJOUTER solde_info


@rh_bp.route('/employe/modifier/<int:id>')
@require_structure
def employe_modifier(structure_id, id):
    """Page de modification d'un employé"""
    employe = Employe.query.filter_by(id=id, structure_id=structure_id).first()
    if not employe:
        flash('Employé non trouvé', 'danger')
        return redirect(url_for('rh.employes'))
    
    services = Service.query.filter_by(structure_id=structure_id).all()
    return render_template('rh/employe_modifier.html', employe=employe, services=services)


# ============================================================
# API - CONGÉS
# ============================================================

@rh_bp.route('/api/conges')
@require_structure
def api_conges(structure_id):
    """API: Liste des congés avec filtres"""
    search = request.args.get('search', '').strip()
    statut = request.args.get('statut', '').strip()
    type_conge = request.args.get('type', '').strip()
    
    query = Conge.query.join(Employe).filter(Employe.structure_id == structure_id)
    
    if search:
        query = query.filter(
            or_(
                Employe.nom.ilike(f'%{search}%'),
                Employe.prenom.ilike(f'%{search}%'),
                Employe.matricule.ilike(f'%{search}%')
            )
        )
    if statut:
        query = query.filter(Conge.statut == statut)
    if type_conge:
        query = query.filter(Conge.type_conge == type_conge)
    
    conges = query.order_by(Conge.created_at.desc()).all()
    annee_actuelle = datetime.now().year
    
    result = []
    for c in conges:
        # ⭐ Calcul du solde avec 30 jours
        solde_info = calculer_solde_conges(c.employe_id, annee_actuelle)
        
        result.append({
            'id': c.id,
            'employe_id': c.employe_id,
            'employe_nom': f"{c.employe.nom} {c.employe.prenom}",
            'type_conge': c.type_conge,
            'date_debut': c.date_debut.strftime('%d/%m/%Y'),
            'date_fin': c.date_fin.strftime('%d/%m/%Y'),
            'date_reprise': c.date_reprise.strftime('%d/%m/%Y') if c.date_reprise else '',
            'nombre_jours': c.nombre_jours,
            'annee_utilisation': c.annee_utilisation or c.date_debut.year,
            'solde_restant': solde_info['solde'],
            'solde_epuise': solde_info['solde'] <= 0,
            'motif': c.motif,
            'statut': c.statut,
            'signataire': c.signataire,
            'created_at': c.created_at.strftime('%d/%m/%Y %H:%M')
        })
    
    return jsonify(result)


@rh_bp.route('/conge/demander', methods=['POST'])
@require_structure
def conge_demander(structure_id):
    """Demander un congé"""
    try:
        data = request.json
        print(f"📥 Demande de congé reçue: {data}")
        
        # ⭐ Validation du signataire
        signataire = data.get('signataire', '').strip()
        if not signataire:
            return jsonify({
                'success': False,
                'error': 'Le nom du signataire est obligatoire'
            }), 400
        
        # ⭐ Validation de l'employé
        employe_id = data.get('employe_id')
        if not employe_id:
            return jsonify({
                'success': False,
                'error': 'Veuillez sélectionner un employé'
            }), 400
        
        employe = Employe.query.filter_by(id=employe_id, structure_id=structure_id).first()
        if not employe:
            return jsonify({
                'success': False,
                'error': 'Employé non trouvé dans cette structure'
            }), 404
        
        # ⭐ Validation des dates
        date_debut_str = data.get('date_debut')
        date_fin_str = data.get('date_fin')
        
        if not date_debut_str or not date_fin_str:
            return jsonify({
                'success': False,
                'error': 'Les dates de début et de fin sont obligatoires'
            }), 400
        
        try:
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'Format de date invalide'
            }), 400
        
        if date_debut > date_fin:
            return jsonify({
                'success': False,
                'error': 'La date de fin doit être après la date de début'
            }), 400
        
        # ⭐ Calcul des jours
        jours_demandes = (date_fin - date_debut).days + 1
        type_conge = data.get('type_conge', 'annuel')
        motif = data.get('motif', '').strip()
        
        # ⭐ Vérification des doublons
        conges_existants = Conge.query.filter(
            Conge.employe_id == employe_id,
            Conge.statut.in_(['en_attente', 'approuve']),
            or_(
                and_(
                    Conge.date_debut <= date_fin,
                    Conge.date_fin >= date_debut
                )
            )
        ).all()
        
        if conges_existants:
            chevauchement = []
            for c in conges_existants:
                chevauchement.append(f"{c.date_debut.strftime('%d/%m/%Y')} -> {c.date_fin.strftime('%d/%m/%Y')} ({c.statut})")
            return jsonify({
                'success': False,
                'error': f"L'employé a déjà un congé sur cette période: {', '.join(chevauchement)}"
            }), 400
        
        # ⭐ Récupérer l'année choisie
        annee_choisie = data.get('annee_choisie')
        if annee_choisie:
            annee_choisie = int(annee_choisie)
        else:
            annee_choisie = date_debut.year
        
        print(f"📅 Année choisie: {annee_choisie}")
        
        # ⭐⭐ VÉRIFICATION DU SOLDE AVEC 30 JOURS ⭐⭐
        verification = verifier_solde_avec_anticipation(employe_id, jours_demandes, annee_choisie)
        
        if not verification['disponible']:
            return jsonify({
                'success': False,
                'error': f"Solde insuffisant pour {annee_choisie}",
                'solde_insuffisant': True,
                'solde_actuel': verification['solde_actuel'],
                'jours_demandes': verification['jours_demandes'],
                'annee_courante': verification['annee'],
                'annees_futures': verification['annees_proposees'],
                'message': verification['message']
            }), 400
        
        # ⭐ Créer le congé
        conge = Conge(
            structure_id=structure_id,
            employe_id=employe_id,
            type_conge=type_conge,
            date_debut=date_debut,
            date_fin=date_fin,
            motif=motif,
            signataire=signataire,
            annee_utilisation=annee_choisie,
            nombre_jours=jours_demandes,
            statut='en_attente'
        )
        
        # Calculer les jours ouvrés et la date de reprise
        conge.nombre_jours = conge.calculer_jours_ouvres()
        conge.date_reprise = conge.calculer_date_reprise()
        
        db.session.add(conge)
        db.session.commit()
        
        # ⭐ Calcul du nouveau solde
        nouveau_solde = verification['solde_actuel'] - jours_demandes
        
        print(f"✅ Congé créé pour {employe.nom} {employe.prenom} (ID: {conge.id})")
        
        return jsonify({
            'success': True,
            'id': conge.id,
            'message': 'Demande de congé soumise avec succès',
            'solde_restant': nouveau_solde,
            'annee_utilisation': annee_choisie
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur conge_demander: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@rh_bp.route('/conge/<int:id>/statut', methods=['PUT'])
@require_structure
def conge_changer_statut(structure_id, id):
    """Changer le statut d'un congé"""
    try:
        data = request.json
        nouveau_statut = data.get('statut')
        
        if nouveau_statut not in ['en_attente', 'approuve', 'refuse', 'termine']:
            return jsonify({'error': 'Statut invalide'}), 400
        
        conge = Conge.query.join(Employe).filter(
            Conge.id == id,
            Employe.structure_id == structure_id
        ).first()
        
        if not conge:
            return jsonify({'error': 'Congé non trouvé'}), 404
        
        conge.statut = nouveau_statut
        conge.approuve_par = session.get('user_name', 'System')
        conge.date_approbation = date.today()
        conge.commentaire = data.get('commentaire', '')
        
        # ⭐ Mettre à jour le statut de l'employé
        employe = conge.employe
        employe.mettre_a_jour_statut()

        db.session.commit()

        # ⭐ JOURNAL D'ACTIVITÉ
        if nouveau_statut == 'approuve':
            try:
                from services.journal_service import JournalService
                JournalService.creer_mouvement(
                    structure_id=structure_id, categorie='conge_approuve',
                    description=f"Congé approuvé — {employe.nom} {employe.prenom} ({conge.nombre_jours} j)",
                    reference_type='conge', reference_id=conge.id,
                    utilisateur_nom=session.get('user_name', 'System'),
                )
            except Exception as e:
                print(f"⚠️ Erreur journal d'activité (congé #{conge.id}): {e}")

        return jsonify({
            'success': True,
            'message': f'Statut du congé mis à jour en "{nouveau_statut}"',
            'employe_statut': employe.statut
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur conge_changer_statut: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/conge/<int:id>/autorisation')
@require_structure
def conge_autorisation(structure_id, id):
    """Page d'autorisation de congé"""
    conge = Conge.query.join(Employe).filter(
        Conge.id == id,
        Employe.structure_id == structure_id
    ).first()
    
    if not conge:
        flash('Congé non trouvé', 'danger')
        return redirect(url_for('rh.conges'))
    
    if conge.statut != 'approuve':
        flash('Seuls les congés approuvés peuvent être imprimés', 'warning')
        return redirect(url_for('rh.conges'))
    
    employe = conge.employe
    
    if not conge.signataire:
        flash('Aucun signataire défini pour ce congé', 'danger')
        return redirect(url_for('rh.conges'))
    
    # Génération du numéro d'ordre
    annee = datetime.now().year
    count = DocumentRH.query.filter(
        DocumentRH.type_document == 'conge',
        extract('year', DocumentRH.created_at) == annee
    ).count() + 1
    numero_ordre = f"{annee}/{str(count).zfill(3)}/CONGE"

    # ⭐ Enregistrer le document généré (le compteur ci-dessus n'a de sens
    # que si chaque autorisation imprimée est réellement tracée)
    try:
        db.session.add(DocumentRH(
            structure_id=structure_id, type_document='conge',
            numero_ordre=numero_ordre, employe_id=employe.id,
            statut='genere'
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Erreur enregistrement DocumentRH (congé #{conge.id}): {e}")

    # Détermination des pronoms
    if employe.sexe == 'Feminin':
        titre = 'Madame'
        pronom = 'elle'
        autorisee = 'autorisee'
        interessee = 'interessee'
        reprise = 'Elle reprendra'
    else:
        titre = 'Monsieur'
        pronom = 'il'
        autorisee = 'autorise'
        interessee = 'interesse'
        reprise = 'Il reprendra'
    
    return render_template('rh/autorisation_conge.html',
        conge=conge,
        employe=employe,
        titre=titre,
        pronom=pronom,
        autorisee=autorisee,
        interessee=interessee,
        reprise=reprise,
        numero_ordre=numero_ordre,
        date_actuelle=datetime.now().strftime('%d/%m/%Y'),
        datetime=datetime,
        signataire=conge.signataire
    )


# ============================================================
# API - PERMISSIONS
# ============================================================

@rh_bp.route('/api/permissions')
@require_structure
def api_permissions(structure_id):
    """API: Liste des permissions avec filtres"""
    search = request.args.get('search', '').strip()
    statut = request.args.get('statut', '').strip()
    
    query = Permission.query.join(Employe).filter(Employe.structure_id == structure_id)
    
    if search:
        query = query.filter(
            or_(
                Employe.nom.ilike(f'%{search}%'),
                Employe.prenom.ilike(f'%{search}%'),
                Employe.matricule.ilike(f'%{search}%')
            )
        )
    if statut:
        query = query.filter(Permission.statut == statut)
    
    permissions = query.order_by(Permission.created_at.desc()).all()
    result = []
    
    for p in permissions:
        result.append({
            'id': p.id,
            'employe_id': p.employe_id,
            'employe_nom': f"{p.employe.nom} {p.employe.prenom}",
            'type_permission': p.type_permission,
            'date_permission': p.date_permission.strftime('%d/%m/%Y') if p.date_permission else '',
            'heure_debut': p.heure_debut.strftime('%H:%M') if p.heure_debut else '',
            'heure_fin': p.heure_fin.strftime('%H:%M') if p.heure_fin else '',
            'date_debut': p.date_debut.strftime('%d/%m/%Y') if p.date_debut else '',
            'date_fin': p.date_fin.strftime('%d/%m/%Y') if p.date_fin else '',
            'nombre_jours': p.nombre_jours or 1,
            'motif': p.motif,
            'statut': p.statut,
            'signataire': p.signataire
        })
    
    return jsonify(result)


@rh_bp.route('/permission/demander', methods=['POST'])
@require_structure
def permission_demander(structure_id):
    """Demander une permission"""
    try:
        data = request.json
        
        # ⭐ Validation du signataire
        signataire = data.get('signataire', '').strip()
        if not signataire:
            return jsonify({
                'success': False,
                'error': 'Le nom du signataire est obligatoire'
            }), 400
        
        # ⭐ Validation de l'employé
        employe_id = data.get('employe_id')
        if not employe_id:
            return jsonify({
                'success': False,
                'error': 'Veuillez sélectionner un employé'
            }), 400
        
        employe = Employe.query.filter_by(id=employe_id, structure_id=structure_id).first()
        if not employe:
            return jsonify({
                'success': False,
                'error': 'Employé non trouvé dans cette structure'
            }), 404
        
        type_permission = data.get('type_permission', 'heures')
        motif = data.get('motif', '').strip()
        
        if not motif:
            return jsonify({
                'success': False,
                'error': 'Le motif est obligatoire'
            }), 400
        
        # ⭐ Calcul des jours selon le type
        if type_permission == 'heures':
            date_permission = datetime.strptime(data.get('date_permission'), '%Y-%m-%d').date()
            date_debut = date_permission
            date_fin = date_permission
            nombre_jours = 0.5  # Demi-journée
        else:
            date_debut = datetime.strptime(data.get('date_debut'), '%Y-%m-%d').date()
            date_fin = datetime.strptime(data.get('date_fin'), '%Y-%m-%d').date()
            nombre_jours = (date_fin - date_debut).days + 1
        
        # ⭐ Vérification du solde avec 30 jours
        annee_courante = date_debut.year
        verification = verifier_solde_avec_anticipation(employe_id, nombre_jours, annee_courante)
        
        if not verification['disponible']:
            return jsonify({
                'success': False,
                'error': f'Solde de congés insuffisant pour {annee_courante}',
                'solde_insuffisant': True,
                'solde_actuel': verification['solde_actuel'],
                'jours_demandes': verification['jours_demandes'],
                'annee_courante': verification['annee'],
                'annees_futures': verification['annees_proposees'],
                'message': verification['message']
            }), 400
        
        # ⭐ Créer la permission
        permission = Permission(
            employe_id=employe_id,
            structure_id=structure_id,
            type_permission=type_permission,
            motif=motif,
            signataire=signataire,
            nombre_jours=nombre_jours,
            statut='en_attente'
        )
        
        if type_permission == 'heures':
            permission.date_permission = date_permission
            permission.heure_debut = datetime.strptime(data.get('heure_debut'), '%H:%M').time() if data.get('heure_debut') else None
            permission.heure_fin = datetime.strptime(data.get('heure_fin'), '%H:%M').time() if data.get('heure_fin') else None
            permission.date_debut = date_permission
            permission.date_fin = date_permission
        else:
            permission.date_debut = date_debut
            permission.date_fin = date_fin
        
        db.session.add(permission)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'id': permission.id,
            'message': 'Permission demandée avec succès',
            'solde_restant': verification['solde_actuel'] - nombre_jours
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur permission_demander: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@rh_bp.route('/permission/<int:id>/statut', methods=['PUT'])
@require_structure
def permission_changer_statut(structure_id, id):
    """Changer le statut d'une permission"""
    try:
        data = request.json
        nouveau_statut = data.get('statut')
        
        if nouveau_statut not in ['en_attente', 'approuve', 'refuse']:
            return jsonify({'error': 'Statut invalide'}), 400
        
        permission = Permission.query.join(Employe).filter(
            Permission.id == id,
            Employe.structure_id == structure_id
        ).first()
        
        if not permission:
            return jsonify({'error': 'Permission non trouvée'}), 404
        
        permission.statut = nouveau_statut
        permission.approuve_par = session.get('user_name', 'System')
        permission.date_approbation = date.today()
        permission.commentaire = data.get('commentaire', '')

        db.session.commit()

        # ⭐ JOURNAL D'ACTIVITÉ
        if nouveau_statut == 'approuve':
            try:
                from services.journal_service import JournalService
                employe = permission.employe
                JournalService.creer_mouvement(
                    structure_id=structure_id, categorie='permission_approuvee',
                    description=f"Permission approuvée — {employe.nom} {employe.prenom}",
                    reference_type='permission', reference_id=permission.id,
                    utilisateur_nom=session.get('user_name', 'System'),
                )
            except Exception as e:
                print(f"⚠️ Erreur journal d'activité (permission #{permission.id}): {e}")

        return jsonify({
            'success': True,
            'message': f'Statut de la permission mis à jour en "{nouveau_statut}"'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur permission_changer_statut: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/permission/<int:id>/autorisation')
@require_structure
def permission_autorisation(structure_id, id):
    """Page d'autorisation de permission"""
    permission = Permission.query.join(Employe).filter(
        Permission.id == id,
        Employe.structure_id == structure_id
    ).first()
    
    if not permission:
        flash('Permission non trouvée', 'danger')
        return redirect(url_for('rh.permissions'))
    
    if permission.statut != 'approuve':
        flash('Seules les permissions approuvées peuvent être imprimées', 'warning')
        return redirect(url_for('rh.permissions'))
    
    employe = permission.employe
    
    if not permission.signataire:
        flash('Aucun signataire défini pour cette permission', 'danger')
        return redirect(url_for('rh.permissions'))
    
    # Génération du numéro d'ordre
    annee = datetime.now().year
    count = DocumentRH.query.filter(
        DocumentRH.type_document == 'permission',
        extract('year', DocumentRH.created_at) == annee
    ).count() + 1
    numero_ordre = f"{annee}/{str(count).zfill(3)}/PERM"

    try:
        db.session.add(DocumentRH(
            structure_id=structure_id, type_document='permission',
            numero_ordre=numero_ordre, employe_id=employe.id,
            statut='genere'
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Erreur enregistrement DocumentRH (permission #{permission.id}): {e}")

    # Détermination du titre
    titre = 'Madame' if employe.sexe == 'Feminin' else 'Monsieur'
    autorisee = 'autorisee' if employe.sexe == 'Feminin' else 'autorise'
    
    return render_template('rh/autorisation_permission.html',
        permission=permission,
        employe=employe,
        titre=titre,
        autorisee=autorisee,
        numero_ordre=numero_ordre,
        date_actuelle=datetime.now().strftime('%d/%m/%Y'),
        datetime=datetime,
        signataire=permission.signataire
    )


# ============================================================
# API - SERVICES
# ============================================================

@rh_bp.route('/api/services')
@require_structure
def api_services(structure_id):
    """API: Liste des services"""
    services = Service.query.filter_by(structure_id=structure_id).order_by(Service.nom).all()
    result = []
    for s in services:
        result.append({
            'id': s.id,
            'nom': s.nom,
            'responsable': s.responsable,
            'nb_employes': Employe.query.filter_by(service_id=s.id, structure_id=structure_id).count()
        })
    return jsonify(result)


@rh_bp.route('/api/services', methods=['POST'])
@require_structure
def api_ajouter_service(structure_id):
    """Ajouter un service"""
    try:
        data = request.json
        nom = data.get('nom', '').strip()
        
        if not nom:
            return jsonify({'error': 'Le nom du service est obligatoire'}), 400
        
        service = Service(
            structure_id=structure_id,
            nom=nom,
            responsable=data.get('responsable', '').strip()
        )
        
        db.session.add(service)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'id': service.id,
            'message': 'Service ajouté avec succès'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur api_ajouter_service: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/api/services/<int:id>', methods=['PUT'])
@require_structure
def api_modifier_service(structure_id, id):
    """Modifier un service"""
    try:
        service = Service.query.filter_by(id=id, structure_id=structure_id).first()
        if not service:
            return jsonify({'error': 'Service non trouvé'}), 404
        
        data = request.json
        if 'nom' in data:
            service.nom = data['nom'].strip()
        if 'responsable' in data:
            service.responsable = data['responsable'].strip()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Service modifié avec succès'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur api_modifier_service: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/api/services/<int:id>', methods=['DELETE'])
@require_structure
def api_supprimer_service(structure_id, id):
    """Supprimer un service"""
    try:
        service = Service.query.filter_by(id=id, structure_id=structure_id).first()
        if not service:
            return jsonify({'error': 'Service non trouvé'}), 404
        
        # Vérifier si des employés y sont rattachés
        nb_employes = Employe.query.filter_by(service_id=id, structure_id=structure_id).count()
        if nb_employes > 0:
            return jsonify({
                'error': f'Ce service a {nb_employes} employé(s) rattaché(s). Impossible de le supprimer.'
            }), 400
        
        db.session.delete(service)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Service supprimé avec succès'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur api_supprimer_service: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# API - DASHBOARD
# ============================================================

@rh_bp.route('/api/dashboard/stats')
@require_structure
def api_dashboard_stats(structure_id):
    """API: Statistiques du dashboard"""
    try:
        # Mettre à jour les statuts
        employes = Employe.query.filter_by(structure_id=structure_id).all()
        for employe in employes:
            employe.mettre_a_jour_statut()
        db.session.commit()
        
        # Statistiques
        total_employes = len(employes)
        actifs = sum(1 for e in employes if e.statut == 'Actif')
        en_conge = sum(1 for e in employes if e.statut == 'En conge')
        inactifs = total_employes - actifs - en_conge
        
        # Demandes en attente
        demandes_attente = Conge.query.join(Employe).filter(
            Employe.structure_id == structure_id,
            Conge.statut == 'en_attente'
        ).count()
        
        demandes_attente += Permission.query.join(Employe).filter(
            Employe.structure_id == structure_id,
            Permission.statut == 'en_attente'
        ).count()
        
        # Congés en cours
        today = date.today()
        conges_en_cours = Conge.query.join(Employe).filter(
            Employe.structure_id == structure_id,
            Conge.statut == 'approuve',
            Conge.date_debut <= today,
            Conge.date_fin >= today
        ).count()
        
        return jsonify({
            'total_employes': total_employes,
            'actifs': actifs,
            'en_conge': en_conge,
            'inactifs': inactifs,
            'demandes_attente': demandes_attente,
            'conges_en_cours': conges_en_cours
        })
        
    except Exception as e:
        print(f"❌ Erreur api_dashboard_stats: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/api/update_all_status', methods=['POST'])
@require_structure
def update_all_status(structure_id):
    """Met à jour le statut de tous les employés"""
    try:
        employes = Employe.query.filter_by(structure_id=structure_id).all()
        stats = {
            'Actif': 0,
            'En conge': 0,
            'Inactif': 0
        }
        
        for employe in employes:
            nouveau_statut = employe.mettre_a_jour_statut()
            stats[nouveau_statut] = stats.get(nouveau_statut, 0) + 1
        
        return jsonify({
            'success': True,
            'message': f"{len(employes)} employé(s) mis à jour",
            'stats': stats
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur update_all_status: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/api/update_conge_status', methods=['POST'])
@require_structure
def update_conge_status(structure_id):
    """Met à jour le statut des employés en fonction des congés en cours"""
    try:
        today = date.today()
        employes = Employe.query.filter_by(structure_id=structure_id).all()
        count = 0
        
        for employe in employes:
            # Vérifier si l'employé a un congé approuvé en cours
            conge_en_cours = Conge.query.filter(
                Conge.employe_id == employe.id,
                Conge.statut == 'approuve',
                Conge.date_debut <= today,
                Conge.date_fin >= today
            ).first()
            
            if conge_en_cours:
                if employe.statut != 'En conge':
                    employe.statut = 'En conge'
                    count += 1
            else:
                # Vérifier si reprise après congé
                conge_termine = Conge.query.filter(
                    Conge.employe_id == employe.id,
                    Conge.statut == 'approuve',
                    Conge.date_fin < today
                ).order_by(Conge.date_fin.desc()).first()
                
                if conge_termine and conge_termine.date_reprise and conge_termine.date_reprise <= today:
                    if employe.statut != 'Actif':
                        employe.statut = 'Actif'
                        count += 1
                elif employe.statut == 'En conge':
                    employe.statut = 'Actif'
                    count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{count} employé(s) mis à jour',
            'total_employes': len(employes)
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur update_conge_status: {e}")
        return jsonify({'error': str(e)}), 500


@rh_bp.route('/api/employes/<int:id>/solde_conges')
@require_structure
def api_solde_conges(structure_id, id):
    """API: Solde de congés d'un employé"""
    employe = Employe.query.filter_by(id=id, structure_id=structure_id).first()
    if not employe:
        return jsonify({'error': 'Employé non trouvé'}), 404
    
    annee_actuelle = datetime.now().year
    solde_info = calculer_solde_conges(employe.id, annee_actuelle)
    
    return jsonify({
        'employe': f"{employe.nom} {employe.prenom}",
        'matricule': employe.matricule,
        'annee': annee_actuelle,
        'total_annuel': CONGES_ANNUELS,
        'conges_pris': solde_info['conges_pris'],
        'permissions_pris': solde_info['permissions_pris'],
        'total_pris': solde_info['pris'],
        'solde_restant': solde_info['solde']
    })


@rh_bp.route('/api/conges/stats/<int:employe_id>')
@require_structure
def api_conges_stats(structure_id, employe_id):
    """API: Statistiques des congés par année"""
    employe = Employe.query.filter_by(id=employe_id, structure_id=structure_id).first()
    if not employe:
        return jsonify({'error': 'Employé non trouvé'}), 404
    
    annee_actuelle = datetime.now().year
    stats = []
    
    for an in range(annee_actuelle - 2, annee_actuelle + 3):
        solde_info = calculer_solde_conges(employe_id, an)
        
        stats.append({
            'annee': an,
            'conges_pris': solde_info['conges_pris'],
            'permissions_pris': solde_info['permissions_pris'],
            'total_pris': solde_info['pris'],
            'solde_restant': solde_info['solde'],
            'est_epuise': solde_info['solde'] <= 0
        })
    
    return jsonify({
        'employe': f"{employe.nom} {employe.prenom}",
        'total_annuel': CONGES_ANNUELS,
        'stats': stats,
        'annee_courante': annee_actuelle
    })


# ============================================================
# PAIE (bulletin de paie — CNSS / INAM / IRPP)
# ============================================================

@rh_bp.route('/paie')
@require_structure
def page_paie(structure_id):
    """Page « Paie du mois »"""
    return render_template('rh/paie.html')


@rh_bp.route('/parametres-paie')
@require_structure
def page_parametres_paie(structure_id):
    """Écran des taux CNSS / INAM / IRPP (éditables)"""
    return render_template('rh/parametres_paie.html')


@rh_bp.route('/api/parametres-paie', methods=['GET'])
@require_structure
def api_get_parametres_paie(structure_id):
    p = ParametragePaie.get_ou_creer(structure_id)
    demi_amu = float(p.amu_taux_global or 10) / 2.0
    return jsonify({
        'taux_cnss_salarial': float(p.taux_cnss_salarial or 0),
        'taux_cnss_patronal': float(p.taux_cnss_patronal or 0),
        'plafond_cnss': float(p.plafond_cnss or 0),
        'taux_crt_salarial': float(p.taux_crt_salarial or 0),
        'taux_crt_patronal': float(p.taux_crt_patronal or 0),
        'plafond_crt': float(p.plafond_crt or 0),
        'amu_taux_global': float(p.amu_taux_global or 0),
        'amu_salarial_max': demi_amu,      # verrou (dérivé, non modifiable directement)
        'amu_patronal_min': demi_amu,      # verrou (dérivé, non modifiable directement)
        'taux_amu_salarial_defaut': float(p.taux_amu_salarial_defaut or 0),
        'taux_amu_patronal_defaut': float(p.taux_amu_patronal_defaut or 0),
        'taux_formation_pro': float(p.taux_formation_pro or 0),
        'tranches_irpp': p.tranches_irpp or [],
        'abattement_taux': float(p.abattement_taux or 0),
        'abattement_plafond_annuel': float(p.abattement_plafond_annuel or 0),
        'deduction_personne_charge': float(p.deduction_personne_charge or 0),
        'max_personnes_charge': int(p.max_personnes_charge or 6),
        'updated_at': p.updated_at.strftime('%Y-%m-%d %H:%M') if p.updated_at else None,
    })


@rh_bp.route('/api/parametres-paie', methods=['PUT'])
@require_structure
def api_maj_parametres_paie(structure_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    try:
        data = request.json
        p = ParametragePaie.get_ou_creer(structure_id)

        for champ in ['taux_cnss_salarial', 'taux_cnss_patronal', 'plafond_cnss',
                      'taux_crt_salarial', 'taux_crt_patronal', 'plafond_crt',
                      'amu_taux_global', 'taux_formation_pro',
                      'abattement_taux', 'abattement_plafond_annuel',
                      'deduction_personne_charge']:
            if champ in data:
                setattr(p, champ, data[champ])
        if 'max_personnes_charge' in data:
            p.max_personnes_charge = int(data['max_personnes_charge'])

        # ⭐ Verrouillage AMU (décret n°2023-096/PR) : la part salarié ne
        # peut jamais dépasser la moitié du taux global, la part employeur
        # ne peut jamais être inférieure à cette moitié — appliqué ici
        # avant sauvegarde, quelle que soit la valeur envoyée par le client.
        demi_amu = float(p.amu_taux_global or 10) / 2.0
        if 'taux_amu_salarial_defaut' in data:
            p.taux_amu_salarial_defaut = min(float(data['taux_amu_salarial_defaut']), demi_amu)
        if 'taux_amu_patronal_defaut' in data:
            p.taux_amu_patronal_defaut = max(float(data['taux_amu_patronal_defaut']), demi_amu)

        if 'tranches_irpp' in data:
            p.tranches_irpp = data['tranches_irpp']
        p.updated_by = session.get('user_name', 'Admin')
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@rh_bp.route('/api/paie', methods=['GET'])
@require_structure
def api_liste_paies(structure_id):
    """Liste des employés avec leur bulletin (existant ou à générer) pour
    une période — base de l'écran « Paie du mois »."""
    annee = request.args.get('annee', datetime.now().year, type=int)
    mois = request.args.get('mois', datetime.now().month, type=int)

    employes = Employe.query.filter_by(structure_id=structure_id, statut='Actif').order_by(Employe.nom).all()
    paies_existantes = {p.employe_id: p for p in Paie.query.filter_by(
        structure_id=structure_id, annee=annee, mois=mois).all()}

    result = []
    for e in employes:
        paie = paies_existantes.get(e.id)
        result.append({
            'employe_id': e.id,
            'matricule': e.matricule,
            'nom': e.nom, 'prenom': e.prenom,
            'poste': e.poste, 'salaire_base': float(e.salaire_base or 0),
            'secteur_paie': e.secteur_paie or 'prive',
            'personnes_a_charge': e.personnes_a_charge or 0,
            'paie_id': paie.id if paie else None,
            'salaire_brut': float(paie.salaire_brut) if paie else None,
            'net_a_payer': float(paie.net_a_payer) if paie else None,
            'statut': paie.statut if paie else 'non_generee',
        })

    return jsonify({'annee': annee, 'mois': mois, 'employes': result})


@rh_bp.route('/api/paie/generer', methods=['POST'])
@require_structure
def api_generer_paie(structure_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    try:
        from services.paie_service import generer_ou_maj_paie
        data = request.json
        employe_id = data.get('employe_id')

        # ⭐ Les réglages individuels (secteur, personnes à charge, taux
        # dérogatoires) saisis depuis l'écran de génération sont persistés
        # sur l'employé — "modifiable individuellement par salarié".
        employe = Employe.query.filter_by(id=employe_id, structure_id=structure_id).first()
        if not employe:
            return jsonify({'success': False, 'error': 'Employé introuvable'}), 404

        parametrage = ParametragePaie.get_ou_creer(structure_id)
        demi_amu = float(parametrage.amu_taux_global or 10) / 2.0

        if data.get('secteur_paie') in ('prive', 'public'):
            employe.secteur_paie = data['secteur_paie']
        if 'personnes_a_charge' in data:
            employe.personnes_a_charge = _clamp_personnes_a_charge(
                data['personnes_a_charge'], int(parametrage.max_personnes_charge or 6))
        if 'taux_retraite_salarial_override' in data and data['taux_retraite_salarial_override'] not in (None, ''):
            employe.taux_retraite_salarial_override = float(data['taux_retraite_salarial_override'])
        if 'taux_retraite_patronal_override' in data and data['taux_retraite_patronal_override'] not in (None, ''):
            employe.taux_retraite_patronal_override = float(data['taux_retraite_patronal_override'])
        if 'taux_amu_salarial_override' in data and data['taux_amu_salarial_override'] not in (None, ''):
            employe.taux_amu_salarial_override = min(float(data['taux_amu_salarial_override']), demi_amu)
        if 'taux_amu_patronal_override' in data and data['taux_amu_patronal_override'] not in (None, ''):
            employe.taux_amu_patronal_override = max(float(data['taux_amu_patronal_override']), demi_amu)
        db.session.commit()

        paie, erreur = generer_ou_maj_paie(
            structure_id=structure_id,
            employe_id=employe_id,
            annee=data.get('annee', datetime.now().year),
            mois=data.get('mois', datetime.now().month),
            salaire_base=data.get('salaire_base'),
            primes=data.get('primes', 0),
            indemnites=data.get('indemnites', 0),
            prets=data.get('prets', 0),
            acomptes=data.get('acomptes', 0),
            autres_retenues=data.get('autres_retenues', []),
            personnes_a_charge=employe.personnes_a_charge,
            user_nom=session.get('user_name', 'Admin'),
        )
        if erreur:
            return jsonify({'success': False, 'error': erreur}), 400
        return jsonify({'success': True, 'paie_id': paie.id, 'net_a_payer': float(paie.net_a_payer)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@rh_bp.route('/api/paie/<int:paie_id>', methods=['GET'])
@require_structure
def api_detail_paie(structure_id, paie_id):
    paie = Paie.query.filter_by(id=paie_id, structure_id=structure_id).first()
    if not paie:
        return jsonify({'error': 'Paie non trouvée'}), 404
    e = paie.employe
    return jsonify({
        'id': paie.id, 'periode': paie.get_periode_label(),
        'employe': f"{e.nom} {e.prenom}", 'matricule': e.matricule, 'poste': e.poste,
        'secteur': paie.secteur, 'organisme_retraite': paie.organisme_retraite,
        'organisme_amu': paie.organisme_amu,
        'salaire_base': float(paie.salaire_base), 'primes': float(paie.primes),
        'indemnites': float(paie.indemnites), 'salaire_brut': float(paie.salaire_brut),
        'taux_retraite_salarial': float(paie.taux_retraite_salarial or 0),
        'taux_retraite_patronal': float(paie.taux_retraite_patronal or 0),
        'retraite_salarial': float(paie.retraite_salarial), 'retraite_patronal': float(paie.retraite_patronal),
        'taux_amu_salarial': float(paie.taux_amu_salarial or 0),
        'taux_amu_patronal': float(paie.taux_amu_patronal or 0),
        'amu_salarial': float(paie.amu_salarial), 'amu_patronal': float(paie.amu_patronal),
        'formation_pro': float(paie.formation_pro or 0),
        'salaire_brut_imposable': float(paie.salaire_brut_imposable or 0),
        'personnes_a_charge': paie.personnes_a_charge or 0,
        'abattement': float(paie.abattement or 0),
        'deduction_charges_familiales': float(paie.deduction_charges_familiales or 0),
        'revenu_net_imposable': float(paie.revenu_net_imposable or 0),
        'irpp': float(paie.irpp),
        'prets_deduction': float(paie.prets_deduction or 0),
        'acomptes_deduction': float(paie.acomptes_deduction or 0),
        'autres_retenues': paie.autres_retenues or [],
        'autres_retenues_total': float(paie.autres_retenues_total or 0),
        'total_retenues': float(paie.total_retenues),
        'total_charges_patronales': float(paie.total_charges_patronales),
        'net_a_payer': float(paie.net_a_payer), 'statut': paie.statut,
        'statut_label': paie.get_statut_label(),
        'date_paiement': paie.date_paiement.strftime('%Y-%m-%d') if paie.date_paiement else None,
    })


@rh_bp.route('/api/paie/<int:paie_id>/payer', methods=['POST'])
@require_structure
def api_payer_paie(structure_id, paie_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    try:
        from services.paie_service import marquer_paie_payee
        paie = Paie.query.filter_by(id=paie_id, structure_id=structure_id).first()
        if not paie:
            return jsonify({'success': False, 'error': 'Paie non trouvée'}), 404

        data = request.json or {}
        paie, erreur = marquer_paie_payee(
            paie, mode_paiement=data.get('mode_paiement', 'especes'),
            user_nom=session.get('user_name', 'Admin')
        )
        if erreur:
            return jsonify({'success': False, 'error': erreur}), 400
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@rh_bp.route('/paie/<int:paie_id>/bulletin')
@require_structure
def bulletin_paie(structure_id, paie_id):
    """Bulletin de paie imprimable"""
    paie = Paie.query.filter_by(id=paie_id, structure_id=structure_id).first()
    if not paie:
        flash('Bulletin de paie non trouvé', 'danger')
        return redirect(url_for('rh.page_paie'))
    from utils.structure_info import get_structure_info
    structure = get_structure_info(structure_id)
    return render_template('rh/bulletin_paie.html', paie=paie, employe=paie.employe,
                            structure=structure,
                            date_actuelle=datetime.now().strftime('%d/%m/%Y'))


# ============================================================
# DÉCLARATIONS MENSUELLES (IRPP, CNSS/CRT, AMU-CNSS/AMU-INAM)
# ============================================================
# À déposer avant le 15 du mois suivant — voir services.paie_service.

@rh_bp.route('/declarations')
@require_structure
def page_declarations(structure_id):
    """Écran de synthèse des déclarations sociales/fiscales mensuelles."""
    return render_template('rh/declarations.html')


@rh_bp.route('/api/declarations/summary')
@require_structure
def api_declarations_summary(structure_id):
    from services.paie_service import generer_declaration, date_limite_declaration, TYPES_DECLARATION
    annee = request.args.get('annee', datetime.now().year, type=int)
    mois = request.args.get('mois', datetime.now().month, type=int)

    result = {}
    for type_decl in TYPES_DECLARATION:
        d = generer_declaration(structure_id, annee, mois, type_decl)
        result[type_decl] = {
            'label': d['label'], 'organisme': d['organisme'],
            'nb_employes': d['nb_employes'],
            'total_salarial': d['total_salarial'],
            'total_patronal': d['total_patronal'],
            'total': d['total'],
        }

    date_limite = date_limite_declaration(annee, mois)
    return jsonify({
        'annee': annee, 'mois': mois,
        'declarations': result,
        'date_limite': date_limite.strftime('%Y-%m-%d'),
        'date_limite_label': date_limite.strftime('%d/%m/%Y'),
        'delai_depasse': date.today() > date_limite,
    })


@rh_bp.route('/declarations/<type_declaration>/print')
@require_structure
def declaration_print(structure_id, type_declaration):
    """Document imprimable d'une déclaration (liste par employé + totaux),
    prêt à joindre au dépôt auprès de l'organisme concerné."""
    from services.paie_service import generer_declaration
    from utils.structure_info import get_structure_info

    annee = request.args.get('annee', datetime.now().year, type=int)
    mois = request.args.get('mois', datetime.now().month, type=int)

    d = generer_declaration(structure_id, annee, mois, type_declaration)
    if d is None:
        flash('Type de déclaration inconnu', 'danger')
        return redirect(url_for('rh.page_declarations'))

    mois_noms = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    return render_template(
        'rh/declaration_print.html',
        declaration=d,
        periode_libelle=f"{mois_noms[mois]} {annee}",
        structure=get_structure_info(structure_id),
        now=datetime.now(),
    )


# ============================================================
# POINTAGE PAR EMPREINTE (WebAuthn / Windows Hello)
# ============================================================
# N'est utilisable par le navigateur que sur http://localhost:<port> ou en
# HTTPS (règle du standard WebAuthn, pas de notre fait) — pas sur une IP
# locale en http:// simple.

@rh_bp.route('/pointage')
@require_structure
def page_pointage(structure_id):
    """⭐ Voir note sur employes() : le pointage vit dans l'onglet dédié du hub."""
    return redirect(url_for('rh.gestion_rh') + '#pointage')


@rh_bp.route('/borne')
@require_structure
def page_borne_pointage(structure_id):
    """Borne de pointage plein écran — RIEN d'administratif dessus (pas de
    réglages, pas de gestion des employés/empreintes), pensée pour rester
    ouverte toute la journée sur un poste partagé (accueil...). Un admin
    l'ouvre une fois (session valide), puis le personnel n'a plus qu'à
    poser le doigt — voir onglet Pointage du hub RH pour l'administration."""
    return render_template('rh/borne_pointage.html')


@rh_bp.route('/api/pointage/parametrage', methods=['GET'])
@require_structure
def api_get_parametrage_pointage(structure_id):
    p = ParametragePointage.get_ou_creer(structure_id)
    return jsonify({
        'heure_debut': p.heure_debut.strftime('%H:%M'),
        'heure_fin': p.heure_fin.strftime('%H:%M'),
        'tolerance_retard_minutes': p.tolerance_retard_minutes,
        'jours_travailles': p.jours_travailles or [],
    })


@rh_bp.route('/api/pointage/parametrage', methods=['PUT'])
@require_structure
def api_maj_parametrage_pointage(structure_id):
    data = request.get_json(force=True) or {}
    p = ParametragePointage.get_ou_creer(structure_id)
    try:
        if data.get('heure_debut'):
            h, m = data['heure_debut'].split(':')
            p.heure_debut = time(int(h), int(m))
        if data.get('heure_fin'):
            h, m = data['heure_fin'].split(':')
            p.heure_fin = time(int(h), int(m))
        if 'tolerance_retard_minutes' in data:
            p.tolerance_retard_minutes = max(0, int(data['tolerance_retard_minutes']))
        if 'jours_travailles' in data:
            p.jours_travailles = [int(j) for j in data['jours_travailles'] if 0 <= int(j) <= 6]
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({'success': False, 'message': f'Valeur invalide : {e}'}), 400

    db.session.commit()
    return jsonify({'success': True})


@rh_bp.route('/api/pointage/liste', methods=['GET'])
@require_structure
def api_liste_pointages(structure_id):
    date_str = request.args.get('date')
    jour = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()

    pointages = Pointage.query.filter_by(structure_id=structure_id, date_jour=jour) \
        .join(Employe).order_by(Employe.nom).all()

    # Employés sans pointage ce jour-là (utile pour repérer les absences au fil de l'eau)
    ids_pointes = {p.employe_id for p in pointages}
    tous = Employe.query.filter_by(structure_id=structure_id, statut='Actif').all()
    sans_pointage = [e for e in tous if e.id not in ids_pointes]

    return jsonify({
        'success': True,
        'date': jour.isoformat(),
        'pointages': [{
            'id': p.id,
            'employe_id': p.employe_id,
            'employe_nom': f"{p.employe.prenom or ''} {p.employe.nom}".strip(),
            'heure_arrivee': p.heure_arrivee.strftime('%H:%M') if p.heure_arrivee else None,
            'methode_arrivee': p.methode_arrivee,
            'statut_arrivee': p.statut_arrivee,
            'retard_minutes': p.retard_minutes,
            'heure_depart': p.heure_depart.strftime('%H:%M') if p.heure_depart else None,
            'methode_depart': p.methode_depart,
            'duree_travaillee_minutes': p.duree_travaillee_minutes,
        } for p in pointages],
        'absents': [{'employe_id': e.id, 'employe_nom': f"{e.prenom or ''} {e.nom}".strip()} for e in sans_pointage],
    })


@rh_bp.route('/api/pointage/resume', methods=['GET'])
@require_structure
def api_resume_pointage(structure_id):
    from services.pointage_service import resume_periode
    try:
        date_debut = datetime.strptime(request.args.get('date_debut'), '%Y-%m-%d').date()
        date_fin = datetime.strptime(request.args.get('date_fin'), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Période invalide'}), 400

    resultats = resume_periode(structure_id, date_debut, date_fin)
    return jsonify({'success': True, 'data': resultats})


@rh_bp.route('/api/pointage/manuel', methods=['POST'])
@require_structure
def api_pointage_manuel(structure_id):
    """Saisie manuelle (admin) — pour un employé qui n'a pas encore
    d'empreinte enregistrée, ou en cas d'oubli/panne du capteur."""
    from services.pointage_service import enregistrer_pointage

    data = request.get_json(force=True) or {}
    employe = Employe.query.filter_by(id=data.get('employe_id'), structure_id=structure_id).first()
    if not employe:
        return jsonify({'success': False, 'message': 'Employé introuvable'}), 404

    try:
        resultat = enregistrer_pointage(employe, methode='manuel')
        db.session.commit()
        return jsonify({'success': True, 'data': resultat})
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


# ---- Empreintes (enrôlement) ----

@rh_bp.route('/api/empreintes', methods=['GET'])
@require_structure
def api_liste_empreintes(structure_id):
    employes = Employe.query.filter_by(structure_id=structure_id, statut='Actif').order_by(Employe.nom).all()
    return jsonify({
        'success': True,
        'data': [{
            'employe_id': e.id,
            'employe_nom': f"{e.prenom or ''} {e.nom}".strip(),
            'empreintes': [{
                'id': emp.id,
                'libelle_appareil': emp.libelle_appareil,
                'created_at': emp.created_at.strftime('%d/%m/%Y'),
                'derniere_utilisation': emp.derniere_utilisation.strftime('%d/%m/%Y %H:%M') if emp.derniere_utilisation else None,
            } for emp in e.empreintes if emp.actif],
        } for e in employes],
    })


@rh_bp.route('/api/empreintes/<int:empreinte_id>', methods=['DELETE'])
@require_structure
def api_supprimer_empreinte(structure_id, empreinte_id):
    empreinte = EmpreinteEmploye.query.filter_by(id=empreinte_id, structure_id=structure_id).first()
    if not empreinte:
        return jsonify({'success': False, 'message': 'Empreinte introuvable'}), 404
    empreinte.actif = False
    db.session.commit()
    return jsonify({'success': True})


@rh_bp.route('/api/empreintes/enregistrer/options', methods=['POST'])
@require_structure
def api_options_enregistrement_empreinte(structure_id):
    from services.pointage_service import options_enregistrement

    data = request.get_json(force=True) or {}
    employe = Employe.query.filter_by(id=data.get('employe_id'), structure_id=structure_id).first()
    if not employe:
        return jsonify({'success': False, 'message': 'Employé introuvable'}), 404

    options_json, challenge = options_enregistrement(request, employe)
    session['pointage_challenge'] = challenge
    session['pointage_employe_id'] = employe.id
    return jsonify({'success': True, 'options': json.loads(options_json)})


@rh_bp.route('/api/empreintes/enregistrer/verifier', methods=['POST'])
@require_structure
def api_verifier_enregistrement_empreinte(structure_id):
    from services.pointage_service import verifier_enregistrement

    data = request.get_json(force=True) or {}
    challenge = session.pop('pointage_challenge', None)
    employe_id = session.pop('pointage_employe_id', None)
    if not challenge or not employe_id:
        return jsonify({'success': False, 'message': 'Session expirée, recommencez.'}), 400

    employe = Employe.query.filter_by(id=employe_id, structure_id=structure_id).first()
    if not employe:
        return jsonify({'success': False, 'message': 'Employé introuvable'}), 404

    try:
        verifier_enregistrement(request, employe, data.get('credential'), challenge,
                                 libelle_appareil=data.get('libelle_appareil'))
        return jsonify({'success': True, 'message': 'Empreinte enregistrée avec succès.'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Echec de l'enregistrement : {e}"}), 400


# ---- Pointage kiosque (identification par empreinte) ----

@rh_bp.route('/api/pointage/webauthn/options', methods=['POST'])
@require_structure
def api_options_pointage(structure_id):
    from services.pointage_service import options_pointage

    options_json, challenge = options_pointage(request, structure_id)
    if options_json is None:
        return jsonify({'success': False, 'message': "Aucune empreinte enregistrée pour cette structure."}), 400

    session['pointage_challenge'] = challenge
    return jsonify({'success': True, 'options': json.loads(options_json)})


@rh_bp.route('/api/pointage/webauthn/verifier', methods=['POST'])
@require_structure
def api_verifier_pointage(structure_id):
    from services.pointage_service import verifier_pointage

    data = request.get_json(force=True) or {}
    challenge = session.pop('pointage_challenge', None)
    if not challenge:
        return jsonify({'success': False, 'message': 'Session expirée, recommencez.'}), 400

    try:
        resultat = verifier_pointage(request, structure_id, data.get('credential'), challenge)
        return jsonify({'success': True, 'data': resultat})
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Echec de la vérification : {e}"}), 400


# ---- Pointage par reconnaissance faciale (webcam standard) ----

@rh_bp.route('/api/visages', methods=['GET'])
@require_structure
def api_liste_visages(structure_id):
    employes = Employe.query.filter_by(structure_id=structure_id, statut='Actif').order_by(Employe.nom).all()
    return jsonify({
        'success': True,
        'data': [{
            'employe_id': e.id,
            'employe_nom': f"{e.prenom or ''} {e.nom}".strip(),
            'visages': [{
                'id': v.id,
                'libelle': v.libelle,
                'created_at': v.created_at.strftime('%d/%m/%Y'),
                'derniere_utilisation': v.derniere_utilisation.strftime('%d/%m/%Y %H:%M') if v.derniere_utilisation else None,
            } for v in e.visages if v.actif],
        } for e in employes],
    })


@rh_bp.route('/api/visages/<int:visage_id>', methods=['DELETE'])
@require_structure
def api_supprimer_visage(structure_id, visage_id):
    visage = VisageEmploye.query.filter_by(id=visage_id, structure_id=structure_id).first()
    if not visage:
        return jsonify({'success': False, 'message': 'Visage introuvable'}), 404
    visage.actif = False
    db.session.commit()
    return jsonify({'success': True})


@rh_bp.route('/api/visages/enregistrer', methods=['POST'])
@require_structure
def api_enregistrer_visage(structure_id):
    from services.pointage_service import enregistrer_visage

    data = request.get_json(force=True) or {}
    employe = Employe.query.filter_by(id=data.get('employe_id'), structure_id=structure_id).first()
    if not employe:
        return jsonify({'success': False, 'message': 'Employé introuvable'}), 404

    try:
        enregistrer_visage(employe, data.get('descripteur'), libelle=data.get('libelle'))
        return jsonify({'success': True, 'message': 'Visage enregistré avec succès.'})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Echec de l'enregistrement : {e}"}), 400


@rh_bp.route('/api/pointage/facial/verifier', methods=['POST'])
@require_structure
def api_verifier_pointage_facial(structure_id):
    from services.pointage_service import identifier_par_visage

    data = request.get_json(force=True) or {}
    try:
        resultat = identifier_par_visage(structure_id, data.get('descripteur'))
        return jsonify({'success': True, 'data': resultat})
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Echec de la vérification : {e}"}), 400