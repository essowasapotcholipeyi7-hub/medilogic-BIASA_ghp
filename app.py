from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mail import Mail, Message
from config import Config
from sheets_helper import sheets_helper
import hashlib
import secrets
from datetime import datetime
from datetime import date
import json
import os
import pandas as pd
from io import BytesIO
from models import Vente
# ⭐ Importer depuis db_helper et models
from db_helper import db as db_helper
from models import db, StructureMapping, Patient, Utilisateur, Structure, Employe, Service, Conge, Permission, DocumentRH, Vente, SignatureRH, AnnulationVente, Facture, PaiementFacture, FactureAssurance, Recette, Depense
from models import RendezVous
from models import Medecin, Patient, Structure
from datetime import datetime, date, timedelta
from routes.protocoles_routes import protocoles_bp
from routes.journal_routes import journal_bp
import secrets
import random
from datetime import datetime, timedelta





from routes.statistiques import statistiques_bp

from services.rendez_vous_service import RendezVousService
from services.rappels_service import RappelsService


# ========== DÉTECTION ENVIRONNEMENT ==========
IS_PRODUCTION = os.environ.get('RENDER') == 'true' or os.environ.get('PRODUCTION') == 'true'

if IS_PRODUCTION:
    BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://medilogic-biasa-ghp.onrender.com')
else:
    BASE_URL = 'http://127.0.0.1:5000'

print(f"🔗 BASE_URL: {BASE_URL}")

# Initialisation de l'application
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# ⭐ Initialiser le db SQLAlchemy
db.init_app(app)

# ⭐ Bascule hors-ligne Neon <-> Postgres local (inactif si DATABASE_URL_LOCAL
# n'est pas définie dans l'environnement — voir utils/db_failover.py)
from utils import db_failover
with app.app_context():
    db_failover.register_events(db)
    if db_failover.FAILOVER_ENABLED:
        try:
            db.create_all(bind_key='local')  # crée sync_state/sync_changelog si absentes
        except Exception as _e:
            print(f"⚠️ Bascule hors-ligne : impossible de préparer la base locale ({_e})")
db_failover.start_watchdog(app)

# ⭐ Importer le blueprint RH
from routes.rh import rh_bp
app.register_blueprint(rh_bp)

from routes.comptabilite import compta_bp
app.register_blueprint(compta_bp)

# Enregistrer le blueprint
app.register_blueprint(statistiques_bp)

app.register_blueprint(protocoles_bp)
app.register_blueprint(journal_bp)


@app.after_request
def auto_commit_after_request(response):
    """
    Commit automatique après chaque requête réussie (status < 400)
    """
    # Ne pas commiter pour les requêtes GET (lecture seule)
    if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
        if response.status_code < 400:
            try:
                if db.session.is_active:
                    db.session.commit()
                    print(f"✅ Auto-commit après {request.method} {request.path}")
            except Exception as e:
                db.session.rollback()
                print(f"❌ Erreur auto-commit: {e}")
        else:
            try:
                if db.session.is_active:
                    db.session.rollback()
                    print(f"🔄 Rollback après {request.method} {request.path} (status: {response.status_code})")
            except:
                pass
    
    return response


def convertir_prix(valeur):
    """Convertit une valeur en float, gère les erreurs"""
    if valeur is None or valeur == '' or valeur == '-':
        return 0
    try:
        valeur_str = str(valeur).strip().replace(',', '.').replace(' ', '')
        if valeur_str == '' or valeur_str == '-':
            return 0
        return float(valeur_str)
    except (ValueError, TypeError):
        return 0


from sqlalchemy import text, inspect

from sqlalchemy.exc import SQLAlchemyError

import json

def execute_query(query, params=None, commit=False):
    """
    Exécute une requête SQL avec SQLAlchemy.
    
    Args:
        query (str): Requête SQL avec paramètres :nom ou %s
        params (tuple|dict|list|None): Paramètres de la requête
        commit (bool): Si True, commit la transaction
    
    Returns:
        list: Résultats en dictionnaires pour SELECT/RETURNING
        dict: Pour INSERT/UPDATE/DELETE sans RETURNING
    """
    try:
        # ⭐ 1. NETTOYAGE DE LA REQUÊTE
        query = query.replace('%%s', '%s')
        
        # ⭐ 2. SUPPRIMER LES CASTS EXPLICITES ::jsonb, ::text, etc.
        # On les retire car SQLAlchemy gère automatiquement les types
        import re
        # Supprimer les ::jsonb, ::text, ::integer, etc. qui posent problème
        query = re.sub(r'::\w+\s*,', ',', query)
        query = re.sub(r'::\w+\s*\)', ')', query)
        query = re.sub(r'::\w+\s*$', '', query)
        
        # ⭐ 3. PRÉPARATION DES PARAMÈTRES
        dict_params = {}
        
        if params is not None:
            if isinstance(params, (tuple, list)):
                # Convertir en dict avec :p0, :p1, ...
                dict_params = {f'p{i}': value for i, value in enumerate(params)}
                # Remplacer les %s par :p0, :p1, ...
                for i in range(len(params)):
                    query = query.replace('%s', f':p{i}', 1)
                    
            elif isinstance(params, dict):
                dict_params = params
            else:
                dict_params = {'p0': params}
                query = query.replace('%s', ':p0', 1)
        
        # ⭐ 4. POUR LES JSON, S'ASSURER QU'ILS SONT EN STRING
        if dict_params:
            for key, value in dict_params.items():
                if isinstance(value, (dict, list)):
                    dict_params[key] = json.dumps(value, ensure_ascii=False)
        
        # ⭐ 5. EXÉCUTION DE LA REQUÊTE
        if dict_params:
            result = db.session.execute(text(query), dict_params)
        else:
            result = db.session.execute(text(query))
        
        # ⭐ 6. GESTION DU COMMIT
        if commit:
            db.session.commit()
        
        # ⭐ 7. RÉCUPÉRATION DES RÉSULTATS
        query_upper = query.upper()
        is_select = query_upper.lstrip().startswith('SELECT')
        has_returning = 'RETURNING' in query_upper
        
        if is_select or has_returning:
            rows = result.fetchall()
            if rows:
                return [dict(row._mapping) for row in rows]
            return []
        else:
            affected_rows = result.rowcount
            return {'affected_rows': affected_rows} if affected_rows >= 0 else None
    
    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"❌ Erreur SQLAlchemy: {e}")
        print(f"   Query: {query[:200]}...")
        import traceback
        traceback.print_exc()
        raise
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        raise
# Assigner la fonction à db.execute_query
db.execute_query = execute_query

print("✅ db.execute_query défini avec succès")  # Pour vérifier


def upsert_societe_assurance(structure_id, assurance_nom, nom_societe):
    """Mémorise (une seule fois) le nom d'une société souscriptrice pour une
    assurance complémentaire donnée, afin que la prochaine saisie propose un
    simple choix au lieu d'une re-saisie manuelle. Ne doit jamais faire
    échouer l'appelant (patient/vente) si l'enregistrement échoue."""
    if not assurance_nom or not nom_societe:
        return
    assurance_nom = str(assurance_nom).strip()
    nom_societe = str(nom_societe).strip()
    if not assurance_nom or not nom_societe or not structure_id:
        return
    try:
        db.execute_query("""
            INSERT INTO societes_assurance (structure_id, assurance_nom, nom_societe)
            VALUES (%s, %s, %s)
            ON CONFLICT (structure_id, assurance_nom, nom_societe) DO NOTHING
        """, (structure_id, assurance_nom, nom_societe), commit=True)
    except Exception as e:
        print(f"⚠️ upsert_societe_assurance: {e}")


# ========== CONFIGURATION EMAIL ==========
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

# Vérification
if app.config['MAIL_USERNAME'] and app.config['MAIL_PASSWORD']:
    print("📧 Email configuré avec succès")
else:
    print("⚠️ Email non configuré (variables manquantes)")

mail = Mail(app)

# ========== FUNCTIONS ==========
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_next_id(records, id_field='ID'):
    """Génère un nouvel ID"""
    if not records:
        return 1
    try:
        max_id = 0
        for r in records:
            rid = r.get(id_field)
            if rid and str(rid).isdigit():
                max_id = max(max_id, int(rid))
        return max_id + 1
    except:
        return len(records) + 1

import threading

def envoyer_email_async(structure_nom, structure_email, structure_id, proprietaire):
    """Envoie l'email dans un thread séparé - ne bloque pas l'inscription"""
    def _send():
        try:
            sujet = f"🏥 Nouvelle inscription - {structure_nom}"
            
            lien_activation = f"{BASE_URL}/admin/activate/{structure_id}"
            lien_admin = f"{BASE_URL}/admin_global"
            
            corps = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px; }}
                    .info {{ background: white; padding: 15px; border-radius: 8px; margin: 15px 0; }}
                    .btn {{ display: inline-block; background: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>🏥 Nouvelle inscription</h2>
                        <p>Medilogic-GHP</p>
                    </div>
                    <div class="content">
                        <h3>Une nouvelle structure s'est inscrite !</h3>
                        <div class="info">
                            <p><strong>🏥 Structure :</strong> {structure_nom}</p>
                            <p><strong>👤 Propriétaire :</strong> {proprietaire}</p>
                            <p><strong>📧 Email :</strong> {structure_email}</p>
                            <p><strong>📅 Date :</strong> {datetime.now().strftime('%d/%m/%Y à %H:%M')}</p>
                        </div>
                        <div style="text-align: center;">
                            <a href="{lien_activation}" class="btn" style="color: white; background: #28a745;">✅ Activer la structure</a>
                            <br><br>
                            <a href="{lien_admin}" style="color: #667eea;">📊 Aller à l'admin global</a>
                        </div>
                    </div>
                    <div class="footer">
                        <p>Medilogic-GHP - Application de gestion hospitalière</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            msg = Message(
                subject=sujet,
                recipients=[Config.ADMIN_EMAIL],
                html=corps
            )
            
            mail.send(msg)
            print(f"✅ Email d'activation envoyé à {Config.ADMIN_EMAIL}")
            
        except Exception as e:
            print(f"⚠️ Email non envoyé: {e}")
    
    thread = threading.Thread(target=_send)
    thread.daemon = True
    thread.start()
    print(f"📧 Envoi email en arrière-plan pour {structure_nom}")


# ========== LOGIN REQUIRED DECORATOR ==========
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter', 'warning')
            return redirect(url_for('index'))
        sheets_helper.set_structure(session.get('structure_id'))
        return f(*args, **kwargs)
    return decorated_function

# ========== ADMIN REQUIRED DECORATOR ==========
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter', 'warning')
            return redirect(url_for('index'))
        if not session.get('is_admin', False):
            flash('Accès non autorisé. Réservé à l\'administrateur.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/api/sync/status')
def api_sync_status():
    """État de la bascule Neon/local — interrogé par la bannière de base.html."""
    if not db_failover.FAILOVER_ENABLED:
        return jsonify({'enabled': False}), 200
    if 'user_id' not in session and 'structure_id' not in session:
        return jsonify({'enabled': False}), 200
    try:
        return jsonify(db_failover.get_status())
    except Exception as e:
        return jsonify({'enabled': False, 'erreur': str(e)}), 200


@app.route('/api/sync/forcer', methods=['POST'])
@admin_required
def api_sync_forcer():
    """Force une synchronisation immédiate (admin) — utile pour vérifier
    manuellement au lieu d'attendre le prochain passage du watchdog."""
    if not db_failover.FAILOVER_ENABLED:
        return jsonify({'success': False, 'message': "Bascule hors-ligne non configurée sur cette machine"}), 400
    if db_failover.OFFLINE_STATE.is_offline:
        if not db_failover.is_neon_reachable():
            return jsonify({'success': False, 'message': 'Neon toujours injoignable'}), 200
        ok = db_failover.push_sync_to_neon() and db_failover.pull_refresh_from_neon()
        if ok:
            db_failover.OFFLINE_STATE.is_offline = False
            from models import SyncState
            etat = SyncState.get_ou_creer()
            etat.mode = 'online'
            db.session.commit()
        return jsonify({'success': ok, 'message': 'Synchronisé, retour en mode normal' if ok else 'Echec de la synchronisation, voir logs serveur'})
    else:
        ok = db_failover.pull_refresh_from_neon()
        try:
            from utils import sheets_mirror
            sheets_mirror.sync_all()
        except Exception:
            pass
        return jsonify({'success': ok, 'message': 'Mirroir local rafraîchi depuis Neon (+ Google Sheets)' if ok else 'Echec du rafraîchissement'})


@app.route('/guide')
@login_required
def guide_utilisation():
    """Guide d'utilisation de l'application, à destination des utilisateurs
    (pas un manuel technique) — accessible à tout le monde, pas seulement
    aux admins."""
    return render_template('guide.html')


@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        print("=" * 50)
        print(f"🔐 TENTATIVE DE CONNEXION")
        print(f"📧 Email: {email}")
        print("=" * 50)
        
        try:
            spreadsheet = sheets_helper.spreadsheet
            all_worksheets = spreadsheet.worksheets()
        except Exception as e:
            print(f"❌ Erreur accès Google Sheets: {e}")
            # ⭐ Google Sheets injoignable (coupure) : on tente une connexion
            # via le miroir local — voir utils/sheets_mirror.py
            try:
                from utils.sheets_mirror import tenter_connexion_hors_ligne
                infos = tenter_connexion_hors_ligne(email, hash_password(password))
            except Exception:
                infos = None
            if infos:
                session['user_id'] = infos['user_id']
                session['user_name'] = infos['user_name']
                session['structure_id'] = infos['structure_id']
                session['structure_nom'] = infos['structure_nom']
                session['structure_email'] = infos['structure_email']
                session['structure_logo'] = infos.get('structure_logo', '')
                session['structure_telephone'] = infos['structure_telephone']
                session['role'] = infos['role']
                session['is_admin'] = infos['is_admin']
                flash(f"Bienvenue {infos['user_name']} (mode hors-ligne — Google Sheets injoignable)", 'warning')
                return redirect(url_for('dashboard'))
            flash('Connexion à Google Sheets impossible, et aucun compte hors-ligne correspondant trouvé.', 'danger')
            return redirect(url_for('index'))
        
        user_trouve = False
        mdp_ok = False
        
        # ========== 1. RECHERCHE DANS LES FEUILLES UTILISATEURS ==========
        for worksheet in all_worksheets:
            title = worksheet.title
            if title.endswith('_users'):
                print(f"📂 Vérification dans: {title}")
                
                try:
                    row_count = len(worksheet.get_all_values())
                    if row_count <= 1:
                        continue
                    
                    records = worksheet.get_all_records()
                    if not records:
                        continue
                        
                except Exception as e:
                    print(f"   ⚠️ Erreur lecture feuille: {e}")
                    continue
                
                for row in records:
                    if str(row.get('email')) == email:
                        user_trouve = True
                        print(f"✅ Utilisateur trouvé dans {title}")
                        
                        # Vérifier si compte actif
                        statut = row.get('actif', 'oui')
                        if statut != 'oui':
                            print("❌ Compte désactivé")
                            flash('Compte désactivé. Veuillez contacter l\'administrateur.', 'danger')
                            return redirect(url_for('index'))
                        
                        if row.get('mot_de_passe') == hash_password(password):
                            mdp_ok = True
                            print("✅ Mot de passe OK")
                            
                            # 🔥 METTRE À JOUR LA DERNIÈRE CONNEXION
                            try:
                                cell = worksheet.find(str(row.get('ID')), in_column=1)
                                if cell:
                                    row_num = cell.row
                                    current_row = worksheet.row_values(row_num)
                                    
                                    while len(current_row) < 9:
                                        current_row.append('')
                                    
                                    date_connexion = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                                    current_row[8] = date_connexion
                                    
                                    worksheet.update(range_name=f'A{row_num}:I{row_num}', values=[current_row])
                                    print(f"✅ Dernière connexion mise à jour: {date_connexion}")
                            except Exception as e:
                                print(f"⚠️ Erreur mise à jour dernière connexion: {e}")
                            
                            try:
                                structure_id = int(title.split('_')[1])
                            except:
                                structure_id = 1
                            
                            structures = sheets_helper.get_all_records('structures', use_prefix=False)
                            structure = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
                            
                            if structure.get('statut') == 'active':
                                # 🔥 Récupérer le rôle
                                role = row.get('role', 'caissier')
                                
                                session['user_id'] = row.get('ID')
                                session['user_name'] = row.get('nom')
                                session['structure_id'] = structure_id
                                session['structure_nom'] = structure.get('nom')
                                session['structure_email'] = structure.get('email', '')
                                session['structure_logo'] = structure.get('logo_url', '')
                                session['structure_telephone'] = structure.get('telephone', '')
                                session['role'] = role  # 🔥 AJOUT DU RÔLE
                                session['is_admin'] = (role == 'admin')  # 🔥 ADMIN SI ROLE = 'admin'
                                
                                print(f"✅ Connexion réussie pour {row.get('nom')} (rôle: {role})")
                                flash(f'Bienvenue {row.get("nom")}', 'success')
                                return redirect(url_for('dashboard'))
                            else:
                                print("❌ Structure non active")
                                flash('Structure non activée', 'warning')
                                return redirect(url_for('index'))
                        else:
                            print("❌ Mot de passe incorrect")
                            flash('Mot de passe incorrect', 'danger')
                            return redirect(url_for('index'))
        
        # ========== 2. RECHERCHE DANS ADMIN GLOBAL ==========
        if not mdp_ok:
            structures = sheets_helper.get_all_records('structures', use_prefix=False)
            for structure in structures:
                if structure.get('email') == email:
                    user_trouve = True
                    if structure.get('mot_de_passe') == hash_password(password):
                        mdp_ok = True
                        if structure.get('statut') == 'active':
                            # Mettre à jour la connexion admin
                            try:
                                sheet_structures = sheets_helper.spreadsheet.worksheet("structures")
                                cell = sheet_structures.find(str(structure.get('ID')), in_column=1)
                                if cell:
                                    row_num = cell.row
                                    current_row = sheet_structures.row_values(row_num)
                                    while len(current_row) < 13:
                                        current_row.append('')
                                    current_row[12] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                                    sheet_structures.update(range_name=f'A{row_num}:M{row_num}', values=[current_row])
                            except:
                                pass
                            
                            session['user_id'] = structure.get('ID')
                            session['user_name'] = structure.get('nom')
                            session['structure_id'] = structure.get('ID')
                            session['structure_nom'] = structure.get('nom')
                            session['structure_email'] = structure.get('email', '')
                            session['structure_telephone'] = structure.get('telephone', '')
                            session['role'] = 'admin'
                            session['is_admin'] = True
                            
                            flash(f'Bienvenue {structure.get("nom")}', 'success')
                            return redirect(url_for('dashboard'))
                        else:
                            flash('Structure en attente d\'activation', 'warning')
                            return redirect(url_for('index'))
                    else:
                        flash('Mot de passe incorrect', 'danger')
                        return redirect(url_for('index'))
        
        # ========== 3. GESTION DES ERREURS ==========
        if not user_trouve:
            flash('Email non trouvé', 'danger')
        elif not mdp_ok:
            flash('Mot de passe incorrect', 'danger')
        
        return redirect(url_for('index'))
    
    return render_template('index.html')

# MODIFIER la route d'inscription

def valider_mot_de_passe(password):
    """Vérifie que le mot de passe respecte les règles de sécurité"""
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères"
    
    if not any(c.isupper() for c in password):
        return False, "Le mot de passe doit contenir au moins une majuscule"
    
    if not any(c.islower() for c in password):
        return False, "Le mot de passe doit contenir au moins une minuscule"
    
    if not any(c.isdigit() for c in password):
        return False, "Le mot de passe doit contenir au moins un chiffre"
    
    caracteres_speciaux = "!@#$%^&*()_+-=[]{}|;:,.<>?/"
    if not any(c in caracteres_speciaux for c in password):
        return False, "Le mot de passe doit contenir au moins un symbole (!@#$%^&*...)"
    
    return True, "OK"


# Stockage temporaire des codes (en production, utiliser Redis ou base de données)
verification_codes = {}

@app.route('/api/auth/send-verification-code', methods=['POST'])
def api_send_verification_code():
    """Envoyer un code de vérification par email"""
    try:
        data = request.json
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'error': 'Email requis'}), 400
        
        # 🔥 RECHERCHER L'UTILISATEUR DANS GOOGLE SHEETS
        user = None
        user_nom = None
        user_id = None
        structure_id = None
        
        # 1. Chercher dans les responsables de structure (feuille structures)
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        for s in structures:
            if s.get('email') and s.get('email').lower() == email.lower():
                user = {
                    'id': s.get('ID'),
                    'nom': s.get('nom') or s.get('proprietaire') or 'Responsable',
                    'email': s.get('email'),
                    'role': 'responsable',
                    'structure_id': s.get('ID')
                }
                user_nom = s.get('nom') or s.get('proprietaire') or 'Responsable'
                user_id = s.get('ID')
                structure_id = s.get('ID')
                print(f"✅ Utilisateur trouvé dans structures: {user}")
                break
        
        # 2. Si non trouvé, chercher dans les collaborateurs (struct_{id}_users)
        if not user:
            try:
                users = sheets_helper.get_all_records('users', use_prefix=True)
                for u in users:
                    if u.get('email') and u.get('email').lower() == email.lower():
                        user = {
                            'id': u.get('ID'),
                            'nom': u.get('nom') or u.get('prenom') or 'Utilisateur',
                            'email': u.get('email'),
                            'role': u.get('role', 'collaborateur'),
                            'structure_id': u.get('structure_id')
                        }
                        user_nom = u.get('nom') or u.get('prenom') or 'Utilisateur'
                        user_id = u.get('ID')
                        structure_id = u.get('structure_id')
                        print(f"✅ Utilisateur trouvé dans users: {user}")
                        break
            except Exception as e:
                print(f"⚠️ Erreur recherche users: {e}")
        
        # ⚠️ Ne pas révéler que l'email n'existe pas (sécurité)
        if not user:
            print(f"⚠️ Email non trouvé: {email}")
            return jsonify({
                'success': True,
                'message': 'Si l\'email existe, un code de vérification a été envoyé',
                'token': 'dummy_token'
            })
        
        # Générer un code à 6 chiffres
        import random
        code = str(random.randint(100000, 999999))
        token = secrets.token_urlsafe(32)
        
        # Stocker le code (expire dans 5 minutes)
        verification_codes[email] = {
            'code': code,
            'token': token,
            'expiry': datetime.now() + timedelta(minutes=5),
            'attempts': 0,
            'max_attempts': 3,
            'user_id': user_id,
            'structure_id': structure_id
        }
        
        # Envoyer le code par email
        send_verification_code_email(email, code, user_nom)
        
        print(f"🔐 Code de vérification pour {email}: {code}")
        
        return jsonify({
            'success': True,
            'message': 'Un code de vérification a été envoyé à votre email',
            'token': token
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Erreur interne'}), 500


@app.route('/api/auth/verify-code', methods=['POST'])
def api_verify_code():
    """Vérifier le code de vérification"""
    try:
        data = request.json
        email = data.get('email')
        code = data.get('code')
        token = data.get('token')
        
        if not email or not code or not token:
            return jsonify({'success': False, 'error': 'Données manquantes'}), 400
        
        stored = verification_codes.get(email)
        
        if not stored:
            return jsonify({'success': False, 'error': 'Code expiré ou invalide'}), 400
        
        if stored.get('token') != token:
            return jsonify({'success': False, 'error': 'Session invalide'}), 400
        
        if datetime.now() > stored.get('expiry'):
            del verification_codes[email]
            return jsonify({'success': False, 'error': 'Code expiré'}), 400
        
        if stored.get('attempts', 0) >= stored.get('max_attempts', 3):
            del verification_codes[email]
            return jsonify({'success': False, 'error': 'Trop de tentatives'}), 400
        
        if stored.get('code') != str(code).strip():
            stored['attempts'] = stored.get('attempts', 0) + 1
            return jsonify({'success': False, 'error': f'Code incorrect ({3 - stored["attempts"]} essai(s) restant(s))'}), 400
        
        # ✅ Code correct
        import secrets
        reset_token = secrets.token_urlsafe(32)
        reset_expiry = datetime.now() + timedelta(hours=24)
        
        user_id = stored.get('user_id')
        structure_id = stored.get('structure_id')
        user_type = stored.get('user_type', 'collaborateur')
        
        if structure_id and user_id:
            try:
                if user_type == 'responsable':
                    # 🔥 UTILISER reset_token, PAS token (pour ne pas écraser le token de synchro)
                    sheets_helper.update_record_by_id(
                        'structures',
                        user_id,
                        {
                            'reset_token': reset_token,      # ← NOUVEAU champ
                            'reset_token_expiry': reset_expiry.isoformat()
                        },
                        id_column='ID',
                        use_prefix=False
                    )
                    print(f"✅ reset_token enregistré dans structures pour l'utilisateur {user_id}")
                else:
                    sheets_helper.update_record_by_id(
                        'users',
                        user_id,
                        {
                            'reset_token': reset_token,      # ← NOUVEAU champ
                            'reset_token_expiry': reset_expiry.isoformat()
                        },
                        id_column='ID'
                    )
                    print(f"✅ reset_token enregistré dans struct_{structure_id}_users pour l'utilisateur {user_id}")
            except Exception as e:
                print(f"⚠️ Erreur mise à jour: {e}")
        
        del verification_codes[email]
        
        reset_link = f"{request.host_url}reset-password?token={reset_token}"
        print(f"🔗 Lien de réinitialisation: {reset_link}")
        
        return jsonify({
            'success': True,
            'reset_link': reset_link
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Page de réinitialisation du mot de passe"""
    token = request.args.get('token')
    
    if not token:
        flash('Token manquant', 'danger')
        return redirect(url_for('index'))
    
    user = None
    
    try:
        # 1. Chercher dans les structures
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        for s in structures:
            # 🔥 Chercher reset_token (pas token)
            if s.get('reset_token') == token:
                expiry = s.get('reset_token_expiry')
                if expiry:
                    try:
                        expiry_date = datetime.fromisoformat(expiry)
                        if expiry_date > datetime.now():
                            user = {
                                'id': s.get('ID'),
                                'nom': s.get('nom') or 'Responsable',
                                'email': s.get('email'),
                                'structure_id': s.get('ID'),
                                'type': 'structure'
                            }
                            break
                    except:
                        pass
        
        # 2. Chercher dans les collaborateurs
        if not user:
            users = sheets_helper.get_all_records('users', use_prefix=True)
            for u in users:
                if u.get('reset_token') == token:
                    expiry = u.get('reset_token_expiry')
                    if expiry:
                        try:
                            expiry_date = datetime.fromisoformat(expiry)
                            if expiry_date > datetime.now():
                                user = {
                                    'id': u.get('ID'),
                                    'nom': u.get('nom') or u.get('prenom') or 'Utilisateur',
                                    'email': u.get('email'),
                                    'structure_id': u.get('structure_id'),
                                    'type': 'user'
                                }
                                break
                        except:
                            pass
    except Exception as e:
        print(f"⚠️ Erreur recherche token: {e}")
    
    if not user:
        flash('🔒 Token invalide ou expiré', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('reset_password.html', token=token)
        
        if len(new_password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
            return render_template('reset_password.html', token=token)
        
        from werkzeug.security import generate_password_hash
        hashed = generate_password_hash(new_password)
        
        try:
            if user['type'] == 'structure':
                # 🔥 NE PAS TOUCHER au champ 'token' (synchronisation)
                sheets_helper.update_record_by_id(
                    'structures',
                    user['id'],
                    {
                        'mot_de_passe': hashed,
                        'reset_token': '',          # ← Nettoyer reset_token
                        'reset_token_expiry': ''    # ← Nettoyer reset_token_expiry
                    },
                    id_column='ID',
                    use_prefix=False
                )
            else:
                sheets_helper.update_record_by_id(
                    'users',
                    user['id'],
                    {
                        'mot_de_passe': hashed,
                        'reset_token': '',
                        'reset_token_expiry': ''
                    },
                    id_column='ID'
                )
            
            flash('✅ Mot de passe réinitialisé avec succès !', 'success')
            return redirect(url_for('index'))
            
        except Exception as e:
            flash(f'❌ Erreur: {e}', 'danger')
            return render_template('reset_password.html', token=token)
    
    return render_template('reset_password.html', token=token)


def send_verification_code_email(email, code, nom):
    """Envoyer un email avec le code de vérification"""
    try:
        from flask_mail import Mail, Message
        
        msg = Message(
            subject="🔐 Code de vérification - SSoftOneV10",
            recipients=[email],
            html=f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px;">
                <h2 style="color: #1a2a6c;">🔐 Code de vérification</h2>
                <p>Bonjour <strong>{nom}</strong>,</p>
                <p>Vous avez demandé la réinitialisation de votre mot de passe.</p>
                <div style="background: #f5f7fa; padding: 20px; border-radius: 10px; text-align: center; margin: 20px 0;">
                    <p style="font-size: 14px; color: #6c7a89; margin-bottom: 5px;">Votre code de vérification est :</p>
                    <div style="font-size: 36px; font-weight: bold; color: #1a2a6c; letter-spacing: 10px; background: white; padding: 15px; border-radius: 8px; border: 2px dashed #1a2a6c;">
                        {code}
                    </div>
                    <p style="font-size: 12px; color: #8e9aaf; margin-top: 10px;">Ce code expire dans <strong>5 minutes</strong></p>
                </div>
                <p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.</p>
                <hr>
                <small style="color: #6c7a89;">SSoftOneV10 - Système de Gestion Hospitalière</small>
            </body>
            </html>
            """
        )
        mail.send(msg)
        print(f"✅ Email de vérification envoyé à {email}")
        return True
    except Exception as e:
        print(f"❌ Erreur envoi email: {e}")
        return False


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        structure_name = request.form.get('structure_name')
        proprietaire_nom = request.form.get('proprietaire_nom')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # VALIDATION DU MOT DE PASSE
        valide, message = valider_mot_de_passe(password)
        if not valide:
            flash(message, 'danger')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('register'))
        
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        
        # ============================================
        # 🔥 TROUVER LE PROCHAIN ID - CORRIGÉ
        # ============================================
        new_id = 1
        for s in structures:
            # Récupérer l'ID
            sid = s.get('ID', 0)
            
            # 🔥 Convertir en int si c'est une chaîne
            if isinstance(sid, str):
                try:
                    sid = int(sid)
                except ValueError:
                    sid = 0
            
            # 🔥 Comparer et incrémenter
            if sid >= new_id:
                new_id = sid + 1
        
        # ============================================
        # CRÉER LA STRUCTURE
        # ============================================
        new_structure = [
            new_id,
            structure_name,
            email,
            phone,
            address,
            hash_password(password),
            'pending',
            secrets.token_hex(16),
            datetime.now().isoformat(),
            proprietaire_nom,
            ''
        ]
        
        sheets_helper.add_record('structures', new_structure, use_prefix=False)
        sheets_helper.init_structure_sheets(new_id)
        
        # 🔥 ENVOYER L'EMAIL EN ARRIÈRE-PLAN
        envoyer_email_async(structure_name, email, new_id, proprietaire_nom)
        
        flash(f'Structure "{structure_name}" créée avec succès ! En attente d\'activation.', 'success')
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    from models import Patient
    from datetime import datetime
    from sqlalchemy import text
    
    # ⭐ Récupérer structure_id depuis la session
    structure_id = session.get('structure_id')
    
    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('logout'))
    
    # ⭐ Compter les patients avec SQL pur (le plus fiable)
    result = db.session.execute(
        text("SELECT COUNT(*) FROM patients WHERE structure_id = :structure_id"),
        {'structure_id': structure_id}
    ).scalar()
    
    total_patients = result if result else 0
    
    # ⭐ FIX : les ventes vivent dans Postgres (table `ventes`) depuis
    # longtemps déjà — ce tableau de bord lisait encore d'anciennes feuilles
    # Google Sheets ('ventes_actes'/'ventes_pharma') qui n'existent plus
    # ("Feuille struct_X_ventes_actes non trouvée"), donc les compteurs du
    # jour et le CA affichaient toujours zéro. Lecture directe en base,
    # comme partout ailleurs dans l'application (historique des ventes,
    # comptabilité...).
    stats_jour = db.session.execute(text("""
        SELECT type,
               COUNT(*) as nb,
               COALESCE(SUM(net_a_payer), 0) as ca
        FROM ventes
        WHERE structure_id = :structure_id
        AND DATE(date_vente) = CURRENT_DATE
        AND (statut IS NULL OR statut != 'annulee')
        GROUP BY type
    """), {'structure_id': structure_id}).fetchall()

    actes_today = 0
    ca_actes_today = 0.0
    ventes_pharma_today = 0
    ca_pharma_today = 0.0
    for row in stats_jour:
        nb, ca = int(row.nb or 0), float(row.ca or 0)
        if row.type in ('pharma', 'pharmacie'):
            ventes_pharma_today += nb
            ca_pharma_today += ca
        else:  # actes, mixte, lunettes...
            actes_today += nb
            ca_actes_today += ca

    ca_today = ca_actes_today + ca_pharma_today

    # ========== ACTIVITÉS RÉCENTES ==========
    ventes_recentes = db.session.execute(text("""
        SELECT id, type, patient_nom, date_vente, net_a_payer
        FROM ventes
        WHERE structure_id = :structure_id
        AND (statut IS NULL OR statut != 'annulee')
        ORDER BY date_vente DESC
        LIMIT 10
    """), {'structure_id': structure_id}).fetchall()

    recentes = [{
        'id': r.id,
        'type': 'pharma' if r.type in ('pharma', 'pharmacie') else (r.type or 'actes'),
        'patient_nom': r.patient_nom or 'Patient',
        'date': r.date_vente.strftime('%Y-%m-%d %H:%M') if r.date_vente else '',
        'montant': float(r.net_a_payer or 0),
    } for r in ventes_recentes]
    
    return render_template('dashboard.html',
                         total_patients=total_patients,
                         actes_today=actes_today,
                         ventes_pharma_today=ventes_pharma_today,
                         ca_today=ca_today,
                         recentes=recentes)

@app.route('/debug_pharma')
@login_required
def debug_pharma():
    structure_id = session.get('structure_id')
    
    ventes_pharma = sheets_helper.get_all_records('ventes_pharma')
    
    result = {
        'structure_id': structure_id,
        'total_ventes_pharma': len(ventes_pharma),
        'ventes': []
    }
    
    for v in ventes_pharma:
        result['ventes'].append({
            'id': v.get('ID'),
            'structure_id': v.get('structure_id'),
            'date': v.get('date'),
            'net_a_payer': v.get('net_a_payer'),
            'type_date': type(v.get('date')).__name__,
            'type_net': type(v.get('net_a_payer')).__name__
        })
    
    return jsonify(result)

# MODIFIER la route des patients pour utiliser le bon format
@app.route('/patients')
@login_required
def patients():
    structure_id = session.get('structure_id')
    
    if not structure_id:
        flash('Structure non trouvée', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        # 🔥 AJOUTER les colonnes de la personne à prévenir
        patients = db.execute_query("""
            SELECT id, nom, prenom, telephone, adresse, date_naissance,
                   type_assurance, taux_prise_charge, numero_assure,
                   assurance2_nom, taux_assurance2, numero_assure2, societe_assurance2,
                   personne_a_prevenir_nom, personne_a_prevenir_telephone, personne_a_prevenir_relation
            FROM patients
            WHERE structure_id = %s
            ORDER BY id DESC
        """, (structure_id,))

        patients_list = []
        if patients:
            for p in patients:
                if isinstance(p, dict):
                    date_naissance = p.get('date_naissance')
                    patients_list.append({
                        'ID': p.get('id'),
                        'nom': p.get('nom', ''),
                        'prenom': p.get('prenom', ''),
                        'telephone': p.get('telephone', ''),
                        'adresse': p.get('adresse', ''),
                        'date_naissance': date_naissance.strftime('%Y-%m-%d') if date_naissance else '',
                        'age': calculer_age(date_naissance) if date_naissance else None,
                        'type_assurance': p.get('type_assurance', 'non_assure'),
                        'taux_prise_charge': p.get('taux_prise_charge', 0),
                        'numero_assure': p.get('numero_assure', ''),
                        'assurance2_nom': p.get('assurance2_nom', ''),
                        'taux_assurance2': p.get('taux_assurance2', 0),
                        'numero_assure2': p.get('numero_assure2', ''),
                        'societe_assurance2': p.get('societe_assurance2', ''),
                        # 🔥 NOUVEAUX CHAMPS
                        'personne_a_prevenir_nom': p.get('personne_a_prevenir_nom', ''),
                        'personne_a_prevenir_telephone': p.get('personne_a_prevenir_telephone', ''),
                        'personne_a_prevenir_relation': p.get('personne_a_prevenir_relation', '')
                    })
                else:
                    date_naissance = p[5] if len(p) > 5 else None
                    patients_list.append({
                        'ID': p[0],
                        'nom': p[1] or '',
                        'prenom': p[2] or '',
                        'telephone': p[3] or '',
                        'adresse': p[4] or '',
                        'date_naissance': date_naissance.strftime('%Y-%m-%d') if date_naissance else '',
                        'age': calculer_age(date_naissance) if date_naissance else None,
                        'type_assurance': p[6] or 'non_assure',
                        'taux_prise_charge': p[7] or 0,
                        'numero_assure': p[8] or '',
                        'assurance2_nom': p[9] if len(p) > 9 else '',
                        'taux_assurance2': p[10] if len(p) > 10 else 0,
                        'numero_assure2': p[11] if len(p) > 11 else '',
                        'societe_assurance2': p[12] if len(p) > 12 else '',
                        # 🔥 NOUVEAUX CHAMPS
                        'personne_a_prevenir_nom': p[13] if len(p) > 13 else '',
                        'personne_a_prevenir_telephone': p[14] if len(p) > 14 else '',
                        'personne_a_prevenir_relation': p[15] if len(p) > 15 else ''
                    })
        
        return render_template('patients.html', patients=patients_list)
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        flash(f'Erreur: {str(e)}', 'error')
        return render_template('patients.html', patients=[])

@app.route('/api/societes-assurance', methods=['GET'])
@login_required
def api_societes_assurance():
    """Autocomplétion : sociétés déjà saisies pour une assurance
    complémentaire donnée (?assurance=GTA) — pour proposer un choix au lieu
    d'une re-saisie manuelle."""
    structure_id = session.get('structure_id')
    assurance = (request.args.get('assurance') or '').strip()
    if not structure_id or not assurance:
        return jsonify([])
    try:
        rows = db.execute_query("""
            SELECT nom_societe FROM societes_assurance
            WHERE structure_id = %s AND assurance_nom = %s
            ORDER BY nom_societe
        """, (structure_id, assurance))
        return jsonify([r['nom_societe'] for r in (rows or [])])
    except Exception as e:
        print(f"❌ api_societes_assurance: {e}")
        return jsonify([])


@app.route('/api/patients', methods=['POST'])
@login_required
def api_add_patient():
    try:
        data = request.json
        structure_id = session.get('structure_id')

        # 🔥 Ajouter les colonnes de la personne à prévenir
        # ⭐ created_at fixé explicitement à NOW() — ne pas compter sur un
        # DEFAULT au niveau de la table (absent sur certaines bases, ce qui
        # laissait created_at NULL et cassait les statistiques
        # aujourd'hui/semaine/mois/année de la page Patients, qui restaient
        # bloquées à zéro malgré des patients bien enregistrés).
        result = db.execute_query("""
            INSERT INTO patients (
                structure_id, nom, prenom, telephone, adresse,
                date_naissance, type_assurance, taux_prise_charge, numero_assure,
                assurance2_nom, taux_assurance2, numero_assure2, societe_assurance2,
                personne_a_prevenir_nom, personne_a_prevenir_telephone, personne_a_prevenir_relation,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (
            structure_id,
            data.get('nom'),
            data.get('prenom', ''),
            data.get('telephone'),
            data.get('adresse', ''),
            data.get('date_naissance', ''),
            data.get('type_assurance', 'non_assure'),
            data.get('taux_prise_charge', 0),
            data.get('numero_assure', ''),
            data.get('assurance2_nom'),
            data.get('taux_assurance2', 0),
            data.get('numero_assure2'),
            data.get('societe_assurance2'),
            data.get('personne_a_prevenir_nom'),
            data.get('personne_a_prevenir_telephone'),
            data.get('personne_a_prevenir_relation')
        ))

        if result and len(result) > 0:
            upsert_societe_assurance(structure_id, data.get('assurance2_nom'), data.get('societe_assurance2'))
            return jsonify({'success': True, 'id': result[0]['id']})
        return jsonify({'success': False, 'error': 'Erreur insertion'}), 500

    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients/<int:id>', methods=['GET'])
@login_required
def api_get_patient(id):
    try:
        structure_id = session.get('structure_id')
        
        result = db.execute_query("""
            SELECT * FROM patients 
            WHERE id = %s AND structure_id = %s
        """, (id, structure_id))
        
        if not result or len(result) == 0:
            return jsonify({'success': False, 'error': 'Patient non trouvé'}), 404
        
        row = result[0]
        
        # Si c'est un dictionnaire
        if isinstance(row, dict):
            created_at = row.get('created_at')
            date_naissance = row.get('date_naissance')
            
            # Formater la date d'enregistrement
            if created_at:
                if hasattr(created_at, 'strftime'):
                    created_at_formatted = created_at.strftime('%d/%m/%Y %H:%M')
                else:
                    created_at_formatted = str(created_at)
            else:
                created_at_formatted = 'Non renseignée'
            
            return jsonify({
                'id': row.get('id'),
                'nom': row.get('nom', ''),
                'prenom': row.get('prenom', ''),
                'telephone': row.get('telephone', ''),
                'adresse': row.get('adresse', ''),
                'date_naissance': date_naissance.strftime('%Y-%m-%d') if date_naissance else '',
                'age': calculer_age(date_naissance) if date_naissance else None,
                'type_assurance': row.get('type_assurance', 'non_assure'),
                'taux_prise_charge': row.get('taux_prise_charge', 0),
                'numero_assure': row.get('numero_assure', ''),
                'assurance2_nom': row.get('assurance2_nom', ''),
                'taux_assurance2': row.get('taux_assurance2', 0),
                'numero_assure2': row.get('numero_assure2', ''),
                'societe_assurance2': row.get('societe_assurance2', ''),
                'personne_a_prevenir_nom': row.get('personne_a_prevenir_nom', ''),
                'personne_a_prevenir_telephone': row.get('personne_a_prevenir_telephone', ''),
                'personne_a_prevenir_relation': row.get('personne_a_prevenir_relation', ''),
                'created_at': created_at_formatted
            })
        
        # Si c'est un tuple
        return jsonify({'error': 'Format de données invalide'}), 500
        
    except Exception as e:
        print(f"❌ Erreur GET patient: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients', methods=['GET'])
@login_required
def api_get_patients():
    """Récupérer tous les patients de la structure"""
    try:
        structure_id = session.get('structure_id')
        
        # 🔥 Ajouter les colonnes de la personne à prévenir
        patients = db.execute_query("""
            SELECT id, nom, prenom, telephone, adresse, date_naissance,
                   type_assurance, taux_prise_charge, numero_assure,
                   assurance2_nom, taux_assurance2, numero_assure2, societe_assurance2,
                   personne_a_prevenir_nom, personne_a_prevenir_telephone, personne_a_prevenir_relation
            FROM patients
            WHERE structure_id = %s
            ORDER BY nom, prenom
        """, (structure_id,))

        result = []
        for p in patients:
            if isinstance(p, dict):
                date_naissance = p.get('date_naissance')
                result.append({
                    'id': p.get('id'),
                    'nom': p.get('nom', ''),
                    'prenom': p.get('prenom', ''),
                    'telephone': p.get('telephone', ''),
                    'adresse': p.get('adresse', ''),
                    'date_naissance': date_naissance.strftime('%Y-%m-%d') if date_naissance else '',
                    'type_assurance': p.get('type_assurance', 'non_assure'),
                    'taux_prise_charge': p.get('taux_prise_charge', 0),
                    'numero_assure': p.get('numero_assure', ''),
                    'assurance2_nom': p.get('assurance2_nom', ''),
                    'taux_assurance2': p.get('taux_assurance2', 0),
                    'numero_assure2': p.get('numero_assure2', ''),
                    'societe_assurance2': p.get('societe_assurance2', ''),
                    # 🔥 NOUVEAUX CHAMPS
                    'personne_a_prevenir_nom': p.get('personne_a_prevenir_nom', ''),
                    'personne_a_prevenir_telephone': p.get('personne_a_prevenir_telephone', ''),
                    'personne_a_prevenir_relation': p.get('personne_a_prevenir_relation', '')
                })
            else:
                date_naissance = p[5] if len(p) > 5 else None
                result.append({
                    'id': p[0],
                    'nom': p[1] if len(p) > 1 else '',
                    'prenom': p[2] if len(p) > 2 else '',
                    'telephone': p[3] if len(p) > 3 else '',
                    'adresse': p[4] if len(p) > 4 else '',
                    'date_naissance': date_naissance.strftime('%Y-%m-%d') if date_naissance else '',
                    'type_assurance': p[6] if len(p) > 6 else 'non_assure',
                    'taux_prise_charge': p[7] if len(p) > 7 else 0,
                    'numero_assure': p[8] if len(p) > 8 else '',
                    'assurance2_nom': p[9] if len(p) > 9 else '',
                    'taux_assurance2': p[10] if len(p) > 10 else 0,
                    'numero_assure2': p[11] if len(p) > 11 else '',
                    'societe_assurance2': p[12] if len(p) > 12 else '',
                    # 🔥 NOUVEAUX CHAMPS
                    'personne_a_prevenir_nom': p[13] if len(p) > 13 else '',
                    'personne_a_prevenir_telephone': p[14] if len(p) > 14 else '',
                    'personne_a_prevenir_relation': p[15] if len(p) > 15 else ''
                })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur GET patients: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500


@app.route('/api/patients/stats', methods=['GET'])
@login_required
def api_patients_stats():
    """Récupère les statistiques des patients"""
    try:
        structure_id = session.get('structure_id')
        
        # 🔥 UTILISER DATE() POUR COMPARER UNIQUEMENT LA DATE SANS L'HEURE
        result = db.execute_query("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN DATE(created_at) = CURRENT_DATE THEN 1 END) as aujourdhui,
                COUNT(CASE WHEN DATE(created_at) >= DATE_TRUNC('week', CURRENT_DATE) 
                          AND DATE(created_at) <= DATE_TRUNC('week', CURRENT_DATE) + INTERVAL '6 days' THEN 1 END) as semaine,
                COUNT(CASE WHEN DATE(created_at) >= DATE_TRUNC('month', CURRENT_DATE) 
                          AND DATE(created_at) <= DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month' - INTERVAL '1 day' THEN 1 END) as mois,
                COUNT(CASE WHEN DATE(created_at) >= DATE_TRUNC('year', CURRENT_DATE) 
                          AND DATE(created_at) <= DATE_TRUNC('year', CURRENT_DATE) + INTERVAL '1 year' - INTERVAL '1 day' THEN 1 END) as annee,
                COUNT(CASE WHEN type_assurance = 'amu_cnss' THEN 1 END) as amu_cnss,
                COUNT(CASE WHEN type_assurance = 'amu_inam' THEN 1 END) as amu_inam,
                COUNT(CASE WHEN assurance2_nom IS NOT NULL AND assurance2_nom != '' THEN 1 END) as cac,
                COUNT(CASE WHEN type_assurance = 'non_assure' OR type_assurance IS NULL THEN 1 END) as non_assure
            FROM patients 
            WHERE structure_id = %s
        """, (structure_id,))
        
        print("=== STATS PATIENTS ===")
        print(f"Résultat: {result}")
        
        if not result or len(result) == 0:
            return jsonify({
                'success': True,
                'total': 0,
                'aujourdhui': 0,
                'semaine': 0,
                'mois': 0,
                'annee': 0,
                'par_assurance': {
                    'amu_cnss': 0,
                    'amu_inam': 0,
                    'cac': 0,
                    'non_assure': 0
                }
            })
        
        row = result[0]
        
        if isinstance(row, dict):
            return jsonify({
                'success': True,
                'total': row.get('total', 0),
                'aujourdhui': row.get('aujourdhui', 0),
                'semaine': row.get('semaine', 0),
                'mois': row.get('mois', 0),
                'annee': row.get('annee', 0),
                'par_assurance': {
                    'amu_cnss': row.get('amu_cnss', 0),
                    'amu_inam': row.get('amu_inam', 0),
                    'cac': row.get('cac', 0),
                    'non_assure': row.get('non_assure', 0)
                }
            })
        else:
            return jsonify({
                'success': True,
                'total': row[0] if len(row) > 0 else 0,
                'aujourdhui': row[1] if len(row) > 1 else 0,
                'semaine': row[2] if len(row) > 2 else 0,
                'mois': row[3] if len(row) > 3 else 0,
                'annee': row[4] if len(row) > 4 else 0,
                'par_assurance': {
                    'amu_cnss': row[5] if len(row) > 5 else 0,
                    'amu_inam': row[6] if len(row) > 6 else 0,
                    'cac': row[7] if len(row) > 7 else 0,
                    'non_assure': row[8] if len(row) > 8 else 0
                }
            })
        
    except Exception as e:
        print(f"❌ Erreur stats patients: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ROUTE de vérification (pour debug)
@app.route('/check_sheets')
@login_required
def check_sheets():
    """Vérifier les feuilles de la structure"""
    try:
        patients = sheets_helper.get_all_records('patients')
        actes = sheets_helper.get_all_records('actes')
        produits = sheets_helper.get_all_records('produits')
        
        return jsonify({
            'structure_prefix': sheets_helper.structure_prefix,
            'structure_id': session.get('structure_id'),
            'patients_count': len(patients),
            'actes_count': len(actes),
            'produits_count': len(produits),
            'patients': patients[:5]  # 5 premiers patients
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/actes_vente')
@login_required
def actes_vente():
    """Page de vente d'actes"""
    from sqlalchemy import text
    
    structure_id = session.get('structure_id')
    
    # 🔥 Récupérer les actes depuis Google Sheets
    actes = sheets_helper.get_all_records('actes', use_prefix=True)
    
    # Filtrer par structure
    actes_filtres = []
    for a in actes:
        if str(a.get('structure_id')) == str(structure_id):
            
            def convertir_prix(valeur):
                if valeur is None or valeur == '' or valeur == '-':
                    return 0
                try:
                    valeur_str = str(valeur).strip().replace(',', '.').replace(' ', '')
                    if valeur_str == '' or valeur_str == '-':
                        return 0
                    return float(valeur_str)
                except (ValueError, TypeError):
                    return 0
            
            prix = convertir_prix(a.get('prix'))
            pbr = convertir_prix(a.get('pbr', a.get('prix')))
            
            prise_amu_raw = a.get('prise_en_charge_amu')
            if prise_amu_raw is None or prise_amu_raw == '':
                prise_amu = True
            elif isinstance(prise_amu_raw, str):
                prise_amu = prise_amu_raw.lower() in ['true', 'oui', 'yes', '1', 'vrai', 't']
            else:
                prise_amu = bool(prise_amu_raw)
            
            prise_cac_raw = a.get('prise_en_charge_cac')
            if prise_cac_raw is None or prise_cac_raw == '':
                prise_cac = True
            elif isinstance(prise_cac_raw, str):
                prise_cac = prise_cac_raw.lower() in ['true', 'oui', 'yes', '1', 'vrai', 't']
            else:
                prise_cac = bool(prise_cac_raw)
            
            # 🔥🔥🔥 RÉCUPÉRER LE STATUT (colonne K) 🔥🔥🔥
            statut_raw = a.get('statut') or a.get('STATUT') or a.get('Statut') or 'direct'
            statut = 'direct'
            if statut_raw and statut_raw != '':
                statut = str(statut_raw).strip().upper()
                if statut not in ['EP', 'DIRECT']:
                    statut = 'direct'
            
            actes_filtres.append({
                'ID': a.get('ID'),
                'nom': a.get('nom', ''),
                'prix': prix,
                'pbr': pbr if pbr > 0 else prix,
                'description': a.get('description', ''),
                'prise_en_charge_amu': prise_amu,
                'commentaire_amu': a.get('commentaire_amu', ''),
                'prise_en_charge_cac': prise_cac,
                'commentaire_cac': a.get('commentaire_cac', ''),
                'statut': statut  # 🔥 AJOUTER ICI
            })
    
    patients = sheets_helper.get_all_records('patients', use_prefix=True)
    
    # ⭐ Récupérer les prescriptions depuis NEON (table prescriptions_recues)
    prescription_ids = request.args.get('prescription_ids', '')
    articles_auto = []
    
    if prescription_ids:
        ids_list = [int(id) for id in prescription_ids.split(',') if id.isdigit()]
        if ids_list:
            print(f"📋 Recherche des prescriptions avec IDs: {ids_list}")
            
            try:
                # 🔥 Récupérer les prescriptions
                result = db.session.execute(
                    text("""
                        SELECT * FROM prescriptions_recues
                        WHERE id = ANY(:ids)
                        AND structure_id = :structure_id
                        AND type_prescription IN ('acte', 'actes', 'acte_pose', 'hospitalisation')
                    """),
                    {"ids": ids_list, "structure_id": structure_id}
                )
                
                prescriptions = result.fetchall()
                print(f"📋 Nombre de prescriptions d'actes trouvées dans Neon: {len(prescriptions)}")
                
                for p in prescriptions:
                    print(f"✅ Prescription trouvée: ID {p.id} - {p.medicament}")
                    
                    # ⭐ CHERCHER L'ACTE CORRESPONDANT DANS Google Sheets
                    acte_trouve = None
                    for acte in actes_filtres:
                        if acte['nom'].lower().strip() == p.medicament.lower().strip():
                            acte_trouve = acte
                            break
                    
                    if acte_trouve:
                        print(f"✅ Acte trouvé dans Sheets: ID {acte_trouve['ID']} - {acte_trouve['nom']}")
                        
                        articles_auto.append({
                            'id': acte_trouve['ID'],
                            'nom': p.medicament,
                            'prix': float(p.prix_total) if p.prix_total else 0,
                            'quantite': int(p.quantite) if p.quantite else 1,
                            'pbr': float(p.pbr) if p.pbr else float(p.prix_total or 0),
                            'prescription_id': p.id,
                            'prise_en_charge_amu': True,
                            'prise_en_charge_cac': True,
                            'commentaire_amu': '',
                            'commentaire_cac': '',
                            'statut': acte_trouve.get('statut', 'direct')  # 🔥 AJOUTER
                        })
                        
                        # ⭐ Mettre à jour le statut dans Neon
                        db.session.execute(
                            text("""
                                UPDATE prescriptions_recues 
                                SET statut = 'AU_PANIER' 
                                WHERE id = :id
                            """),
                            {"id": p.id}
                        )
                        db.session.commit()
                        print(f"📋 Prescription #{p.id} marquée AU_PANIER")
                    else:
                        print(f"⚠️ Acte non trouvé dans Sheets: {p.medicament}")
                        print(f"   📋 Actes disponibles: {[a['nom'] for a in actes_filtres]}")
                    
            except Exception as e:
                print(f"❌ Erreur lors de la récupération des prescriptions: {e}")
                import traceback
                traceback.print_exc()
                db.session.rollback()
    
    print(f"📦 articles_auto (actes): {len(articles_auto)}")
    
    patient_taux = session.get('patient_taux', 0)
    
    return render_template('actes_vente.html', 
                          actes=actes_filtres, 
                          patients=patients,
                          articles_auto=articles_auto,
                          patientTaux=patient_taux)


@app.route('/pharma_vente')
@login_required
def pharma_vente():
    """Page de vente de pharmacie"""
    from sqlalchemy import text
    
    structure_id = session.get('structure_id')
    
    def convertir_prix(valeur):
        if valeur is None or valeur == '' or valeur == '-':
            return 0
        try:
            valeur_str = str(valeur).strip().replace(',', '.').replace(' ', '')
            if valeur_str == '' or valeur_str == '-':
                return 0
            return float(valeur_str)
        except (ValueError, TypeError):
            return 0
    
    # 🔥 Lire les produits depuis Google Sheets
    produits = sheets_helper.get_all_records('produits', use_prefix=True)
    
    # Filtrer par structure
    produits_filtres = []
    for p in produits:
        if str(p.get('structure_id')) == str(structure_id):
            
            prix = convertir_prix(p.get('prix_vente'))
            pbr = convertir_prix(p.get('pbr', p.get('prix_vente')))
            stock = p.get('quantite_stock')
            if stock is None or stock == '' or stock == '-':
                stock = 0
            try:
                stock = int(stock)
            except (ValueError, TypeError):
                stock = 0
            
            produits_filtres.append({
                'ID': p.get('ID'),
                'nom': p.get('nom', ''),
                'prix': prix,
                'pbr': pbr if pbr > 0 else prix,
                'stock': stock,
                'description': p.get('description', ''),
                'dosage': p.get('dosage', ''),
                'forme': p.get('forme', ''),
                'unite': p.get('unite', '')
            })
    
    patients = sheets_helper.get_all_records('patients', use_prefix=True)
    
    print(f"🔍 Produits trouvés dans Sheets: {len(produits_filtres)}")
    
    # ⭐ Récupérer les prescriptions depuis NEON (table prescriptions_recues)
    prescription_ids = request.args.get('prescription_ids', '')
    articles_auto = []
    
    if prescription_ids:
        ids_list = [int(id) for id in prescription_ids.split(',') if id.isdigit()]
        if ids_list:
            print(f"📋 Recherche des prescriptions avec IDs: {ids_list}")
            
            try:
                # 🔥 Récupérer les prescriptions
                result = db.session.execute(
                    text("""
                        SELECT * FROM prescriptions_recues
                        WHERE id = ANY(:ids)
                        AND structure_id = :structure_id
                        AND type_prescription IN ('medicament', 'pharma', 'pharmacie')
                    """),
                    {"ids": ids_list, "structure_id": structure_id}
                )
                
                prescriptions = result.fetchall()
                print(f"📋 Nombre de prescriptions pharmaceutiques trouvées dans Neon: {len(prescriptions)}")
                
                for p in prescriptions:
                    print(f"✅ Prescription trouvée: ID {p.id} - {p.medicament}")
                    
                    # ⭐ CHERCHER LE PRODUIT CORRESPONDANT DANS Google Sheets
                    produit_trouve = None
                    for produit in produits_filtres:
                        if produit['nom'].lower().strip() == p.medicament.lower().strip():
                            produit_trouve = produit
                            break
                    
                    if produit_trouve:
                        print(f"✅ Produit trouvé dans Sheets: ID {produit_trouve['ID']} - {produit_trouve['nom']}")
                        
                        articles_auto.append({
                            'id': produit_trouve['ID'],  # ⭐ Utiliser l'ID du produit (pas celui de la prescription)
                            'nom': p.medicament,
                            'prix': float(p.prix_total) if p.prix_total else 0,
                            'quantite': int(p.quantite) if p.quantite else 1,
                            'pbr': float(p.pbr) if p.pbr else float(p.prix_total or 0),
                            'prescription_id': p.id,
                            'dosage': p.dosage or '',
                            'forme': p.forme or ''
                        })
                        
                        # ⭐ Mettre à jour le statut dans Neon
                        db.session.execute(
                            text("""
                                UPDATE prescriptions_recues 
                                SET statut = 'AU_PANIER' 
                                WHERE id = :id
                            """),
                            {"id": p.id}
                        )
                        db.session.commit()
                        print(f"📋 Prescription #{p.id} marquée AU_PANIER")
                    else:
                        print(f"⚠️ Produit non trouvé dans Sheets: {p.medicament}")
                        print(f"   📋 Produits disponibles: {[prod['nom'] for prod in produits_filtres]}")
                    
            except Exception as e:
                print(f"❌ Erreur lors de la récupération des prescriptions: {e}")
                import traceback
                traceback.print_exc()
                db.session.rollback()
    
    print(f"📦 Articles pharmaceutiques à charger automatiquement: {len(articles_auto)}")
    
    patient_taux = session.get('patient_taux', 0)
    
    return render_template('pharma_vente.html', 
                          produits=produits_filtres, 
                          patients=patients,
                          articles_auto=articles_auto,
                          patientTaux=patient_taux)


@app.route('/facture/<int:vente_id>/<string:type>')
@login_required
def facture(vente_id, type):
    from datetime import datetime
    import json
    
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return "Structure non trouvée", 404
    
    # Récupérer les infos de la structure
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    structure_nom = structure_info.get('nom', 'Medilogic-GHP')
    structure_adresse = structure_info.get('adresse', '')
    structure_telephone = structure_info.get('telephone', '')
    structure_email = structure_info.get('email', '')
    structure_logo = structure_info.get('logo_url', '')
    
    articles = []
    sous_total = 0
    taux_assurance = 0
    prise_en_charge = 0
    net_a_payer = 0
    patient_nom = 'Patient'
    mode_paiement = 'Espèces'
    type_assurance = 'non_assure'
    numero_assure = ''
    patient_id = None
    
    # CHAMPS POUR L'ASSURANCE COMPLÉMENTAIRE
    assurance2_nom = ''
    taux_assurance2 = 0
    prise_en_charge2 = 0
    numero_assure2 = ''
    
    # ⭐ FIX : même correctif que /recu — ne pas exiger v.type = %s en plus
    # de l'id, sinon une vente réelle mais dont le type stocké diverge du
    # type de l'URL (ex: mixte) renvoie un faux "non trouvée". On récupère
    # par id + structure_id, puis on déduit type_bd de la ligne trouvée.
    vente = db.execute_query("""
        SELECT v.*, p.nom, p.prenom, p.type_assurance, p.numero_assure,
               p.assurance2_nom as patient_assurance2_nom,
               p.taux_assurance2 as patient_taux_assurance2,
               p.numero_assure2
        FROM ventes v
        LEFT JOIN patients p ON v.patient_id = p.id
        WHERE v.id = %s AND v.structure_id = %s
    """, (vente_id, structure_id))

    if not vente or len(vente) == 0:
        return f"Vente {vente_id} non trouvée", 404

    v0 = vente[0]
    type_bd_stockee = v0.get('type') if isinstance(v0, dict) else (v0[3] if len(v0) > 3 else None)
    type_bd = type_bd_stockee or ('pharmacie' if type == 'pharma' else type)
    
    if isinstance(vente[0], dict):
        v = vente[0]
        patient_nom = v.get('patient_nom', '')
        if not patient_nom:
            patient_nom = f"{v.get('nom', '')} {v.get('prenom', '')}".strip()
        if not patient_nom:
            patient_nom = 'Patient'
        
        patient_id = v.get('patient_id')
        mode_paiement = v.get('mode_paiement', 'Espèces')
        taux_assurance = float(v.get('taux_assurance', 0))
        prise_en_charge = float(v.get('prise_en_charge', 0))
        net_a_payer = float(v.get('net_a_payer', 0))
        sous_total = float(v.get('sous_total', 0))
        type_assurance = v.get('type_assurance', 'non_assure')
        numero_assure = v.get('numero_assure', '')
        
        # Récupérer les données de l'assurance complémentaire
        assurance2_nom = v.get('assurance2_nom', '')
        taux_assurance2 = float(v.get('taux_assurance2', 0))
        prise_en_charge2 = float(v.get('prise_en_charge2', 0))
        numero_assure2 = v.get('numero_assure2', '')
        societe_assurance2 = v.get('societe_assurance2', '')
        
        # Récupérer le taux original du patient
        patient_taux_original = float(v.get('patient_taux_assurance2', 0))
        
        # Déterminer si le taux a été modifié
        taux_modifie = False
        taux_original = patient_taux_original
        
        if taux_assurance2 > 0 and patient_taux_original > 0:
            if abs(taux_assurance2 - patient_taux_original) > 0.01:
                taux_modifie = True
        
        # Récupérer les articles
        if type_bd == 'pharmacie' or type_bd == 'pharma':
            produits_data = v.get('produits', [])
            if isinstance(produits_data, str):
                produits_data = json.loads(produits_data)
            for p in produits_data:
                articles.append({
                    'nom': p.get('nom', 'Produit'),
                    'quantite': int(p.get('quantite', 1)),
                    'prix_unitaire': float(p.get('prix_reel', p.get('prix', 0))),
                    'total': float(p.get('total', 0))
                })
        else:
            actes_data = v.get('actes', [])
            if isinstance(actes_data, str):
                actes_data = json.loads(actes_data)
            for a in actes_data:
                articles.append({
                    'nom': a.get('nom', 'Acte'),
                    'quantite': int(a.get('quantite', 1)),
                    'prix_unitaire': float(a.get('prix', 0)),
                    'total': float(a.get('total', 0))
                })
    
    # Gestion des assurances
    assurance_text = type_assurance
    if type_assurance == 'amu_cnss':
        assurance_text = 'AMU-CNSS'
    elif type_assurance == 'amu_inam':
        assurance_text = 'AMU-INAM'
    elif type_assurance == 'non_assure':
        assurance_text = 'Non assuré'
    
    # Déterminer si l'assurance complémentaire a été appliquée
    assurance2_appliquee = False
    if assurance2_nom and assurance2_nom != '' and assurance2_nom != 'Aucune' and prise_en_charge2 > 0:
        assurance2_appliquee = True
    
    patient_nom_clean = patient_nom.replace(' ', '_').replace("'", "").replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('à', 'a').replace('ç', 'c')
    nom_fichier = f"facture_client_{patient_nom_clean}_{vente_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    return render_template('facture_client.html',
                         vente_id=vente_id,
                         articles=articles,
                         sous_total=sous_total,
                         taux_assurance=taux_assurance,
                         prise_en_charge=prise_en_charge,
                         net_a_payer=net_a_payer,
                         patient_nom=patient_nom,
                         patient_id=patient_id,
                         type_assurance=assurance_text,
                         numero_assure=numero_assure,
                         mode_paiement=mode_paiement,
                         structure_nom=structure_nom,
                         structure_adresse=structure_adresse,
                         structure_telephone=structure_telephone,
                         structure_email=structure_email,
                         date_actuelle=datetime.now().strftime('%d/%m/%Y %H:%M'),
                         nom_fichier=nom_fichier,
                         structure_logo=structure_logo,
                         nom_caissier=session.get('user_name', ''),
                         assurance2_nom=assurance2_nom,
                         taux_assurance2=taux_assurance2,
                         prise_en_charge2=prise_en_charge2,
                         numero_assure2=numero_assure2,
                         societe_assurance2=societe_assurance2,
                         assurance2_appliquee=assurance2_appliquee,
                         taux_modifie=taux_modifie,
                         taux_original=taux_original)

@app.route('/facture_structure/<int:vente_id>/<string:type>')
@login_required
def facture_structure(vente_id, type):
    from datetime import datetime
    import json
    
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return "Structure non trouvée", 404
    
    # Récupérer les infos de la structure
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    structure_nom = structure_info.get('nom', 'Medilogic-GHP')
    structure_adresse = structure_info.get('adresse', '')
    structure_telephone = structure_info.get('telephone', '')
    structure_email = structure_info.get('email', '')
    structure_logo = structure_info.get('logo_url', '')
    
    articles = []
    sous_total = 0
    taux_assurance = 0
    prise_en_charge = 0
    net_a_payer = 0
    patient_nom = 'Patient'
    mode_paiement = 'Espèces'
    type_assurance = 'non_assure'
    numero_assure = ''
    patient_id = None
    
    # CHAMPS POUR L'ASSURANCE COMPLÉMENTAIRE
    assurance2_nom = ''
    taux_assurance2 = 0
    prise_en_charge2 = 0
    numero_assure2 = ''
    
    # ⭐ FIX : même correctif que /recu — ne pas exiger v.type = %s en plus
    # de l'id, sinon une vente réelle mais dont le type stocké diverge du
    # type de l'URL (ex: mixte) renvoie un faux "non trouvée". On récupère
    # par id + structure_id, puis on déduit type_bd de la ligne trouvée.
    vente = db.execute_query("""
        SELECT v.*, p.nom, p.prenom, p.type_assurance, p.numero_assure,
               p.assurance2_nom as patient_assurance2_nom,
               p.taux_assurance2 as patient_taux_assurance2,
               p.numero_assure2
        FROM ventes v
        LEFT JOIN patients p ON v.patient_id = p.id
        WHERE v.id = %s AND v.structure_id = %s
    """, (vente_id, structure_id))

    if not vente or len(vente) == 0:
        return f"Vente {vente_id} non trouvée", 404

    v0 = vente[0]
    type_bd_stockee = v0.get('type') if isinstance(v0, dict) else (v0[3] if len(v0) > 3 else None)
    type_bd = type_bd_stockee or ('pharmacie' if type == 'pharma' else type)
    
    if isinstance(vente[0], dict):
        v = vente[0]
        patient_nom = v.get('patient_nom', '')
        if not patient_nom:
            patient_nom = f"{v.get('nom', '')} {v.get('prenom', '')}".strip()
        if not patient_nom:
            patient_nom = 'Patient'
        
        patient_id = v.get('patient_id')
        mode_paiement = v.get('mode_paiement', 'Espèces')
        taux_assurance = float(v.get('taux_assurance', 0))
        prise_en_charge = float(v.get('prise_en_charge', 0))
        net_a_payer = float(v.get('net_a_payer', 0))
        sous_total = float(v.get('sous_total', 0))
        type_assurance = v.get('type_assurance', 'non_assure')
        numero_assure = v.get('numero_assure', '')
        
        # Récupérer les données de l'assurance complémentaire
        assurance2_nom = v.get('assurance2_nom', '')
        taux_assurance2 = float(v.get('taux_assurance2', 0))
        prise_en_charge2 = float(v.get('prise_en_charge2', 0))
        numero_assure2 = v.get('numero_assure2', '')
        societe_assurance2 = v.get('societe_assurance2', '')
        
        # Récupérer le taux original du patient
        patient_taux_original = float(v.get('patient_taux_assurance2', 0))
        
        # Déterminer si le taux a été modifié
        taux_modifie = False
        taux_original = patient_taux_original
        
        if taux_assurance2 > 0 and patient_taux_original > 0:
            if abs(taux_assurance2 - patient_taux_original) > 0.01:
                taux_modifie = True
        
        # Récupérer les articles
        if type_bd == 'pharmacie' or type_bd == 'pharma':
            produits_data = v.get('produits', [])
            if isinstance(produits_data, str):
                produits_data = json.loads(produits_data)
            for p in produits_data:
                articles.append({
                    'nom': p.get('nom', 'Produit'),
                    'quantite': int(p.get('quantite', 1)),
                    'prix_unitaire': float(p.get('prix_reel', p.get('prix', 0))),
                    'total': float(p.get('total', 0))
                })
        else:
            actes_data = v.get('actes', [])
            if isinstance(actes_data, str):
                actes_data = json.loads(actes_data)
            for a in actes_data:
                articles.append({
                    'nom': a.get('nom', 'Acte'),
                    'quantite': int(a.get('quantite', 1)),
                    'prix_unitaire': float(a.get('prix', 0)),
                    'total': float(a.get('total', 0))
                })
    
    # Gestion des assurances
    assurance_text = type_assurance
    if type_assurance == 'amu_cnss':
        assurance_text = 'AMU-CNSS'
    elif type_assurance == 'amu_inam':
        assurance_text = 'AMU-INAM'
    elif type_assurance == 'non_assure':
        assurance_text = 'Non assuré'
    
    # Déterminer si l'assurance complémentaire a été appliquée
    assurance2_appliquee = False
    if assurance2_nom and assurance2_nom != '' and assurance2_nom != 'Aucune' and prise_en_charge2 > 0:
        assurance2_appliquee = True
    
    patient_nom_clean = patient_nom.replace(' ', '_').replace("'", "").replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('à', 'a').replace('ç', 'c')
    nom_fichier = f"facture_structure_{patient_nom_clean}_{vente_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    return render_template('facture_structure.html',
                         vente_id=vente_id,
                         articles=articles,
                         sous_total=sous_total,
                         taux_assurance=taux_assurance,
                         prise_en_charge=prise_en_charge,
                         net_a_payer=net_a_payer,
                         patient_nom=patient_nom,
                         patient_id=patient_id,
                         type_assurance=assurance_text,
                         numero_assure=numero_assure,
                         mode_paiement=mode_paiement,
                         structure_nom=structure_nom,
                         structure_adresse=structure_adresse,
                         structure_telephone=structure_telephone,
                         structure_email=structure_email,
                         date_actuelle=datetime.now().strftime('%d/%m/%Y %H:%M'),
                         nom_fichier=nom_fichier,
                         structure_logo=structure_logo,
                         nom_caissier=session.get('user_name', ''),
                         assurance2_nom=assurance2_nom,
                         taux_assurance2=taux_assurance2,
                         prise_en_charge2=prise_en_charge2,
                         numero_assure2=numero_assure2,
                         societe_assurance2=societe_assurance2,
                         assurance2_appliquee=assurance2_appliquee,
                         taux_modifie=taux_modifie,
                         taux_original=taux_original)

@app.route('/admin_global')
def admin_global():
    # 🔥 Vérifier si l'admin est connecté
    if 'super_admin' not in session:
        return redirect(url_for('admin_login'))
    
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    return render_template('admin_global.html', structures=structures)

@app.route('/admin/activate/<int:structure_id>')
def activate_structure(structure_id):
    """Activer une structure"""
    try:
        sheet_structures = sheets_helper.spreadsheet.worksheet("structures")
        
        # Trouver la ligne de la structure
        cell = sheet_structures.find(str(structure_id), in_column=1)
        
        if cell:
            row_num = cell.row
            # Lire toutes les valeurs de la ligne
            current_row = sheet_structures.row_values(row_num)
            
            # Modifier le statut (colonne 7 = index 6)
            if len(current_row) > 6:
                current_row[6] = 'active'  # statut = actif
            
            # Mettre à jour la ligne entière
            sheet_structures.update(f'A{row_num}:K{row_num}', [current_row])
            flash(f'Structure {structure_id} activée avec succès', 'success')
        else:
            flash(f'Structure {structure_id} non trouvée', 'danger')
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'danger')
    
    return redirect(url_for('admin_global'))

@app.route('/admin/suspend/<int:structure_id>')
def suspend_structure(structure_id):
    """Suspendre une structure"""
    try:
        sheet_structures = sheets_helper.spreadsheet.worksheet("structures")
        
        # Trouver la ligne de la structure
        cell = sheet_structures.find(str(structure_id), in_column=1)
        
        if cell:
            row_num = cell.row
            # Lire toutes les valeurs de la ligne
            current_row = sheet_structures.row_values(row_num)
            
            # Modifier le statut (colonne 7 = index 6)
            if len(current_row) > 6:
                current_row[6] = 'suspended'  # statut = suspendu
            
            # Mettre à jour la ligne entière
            sheet_structures.update(f'A{row_num}:K{row_num}', [current_row])
            flash(f'Structure {structure_id} suspendue', 'warning')
        else:
            flash(f'Structure {structure_id} non trouvée', 'danger')
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'danger')
    
    return redirect(url_for('admin_global'))

@app.route('/admin/delete/<int:structure_id>')
def delete_structure(structure_id):
    """Supprimer une structure"""
    try:
        sheet_structures = sheets_helper.spreadsheet.worksheet("structures")
        
        # Trouver la ligne de la structure
        cell = sheet_structures.find(str(structure_id), in_column=1)
        
        if cell:
            sheet_structures.delete_row(cell.row)
            flash(f'Structure {structure_id} supprimée', 'info')
        else:
            flash(f'Structure {structure_id} non trouvée', 'danger')
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'danger')
    
    return redirect(url_for('admin_global'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Déconnecté', 'info')
    return redirect(url_for('index'))

@app.route('/test_sheets')
def test_sheets():
    try:
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        return jsonify({"status": "success", "count": len(structures), "data": structures})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/structures/disponibles', methods=['GET'])
def get_structures_disponibles():
    """Retourne la liste des structures disponibles"""
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    disponibles = [s for s in structures if s.get('statut') == 'disponible']
    return jsonify(disponibles)

@app.route('/recu/<int:vente_id>/<string:type>')
@login_required
def recu(vente_id, type):
    from datetime import datetime
    import json
    
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return "Structure non trouvée", 404
    
    # Récupérer les infos de la structure
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    structure_nom = structure_info.get('nom', 'Medilogic-GHP')


    structure_adresse = sheets_helper.format_adresse(structure_info.get('adresse', ''))
    structure_adresse_html = structure_adresse.replace('\n', '<br>')


    structure_telephone = structure_info.get('telephone', '')
    structure_email = structure_info.get('email', '')
    structure_logo = structure_info.get('logo_url', '')
    
    articles = []
    sous_total = 0
    base_remboursement = 0
    taux_assurance = 0
    prise_en_charge = 0
    net_a_payer = 0
    patient_nom = 'Patient'
    mode_paiement = 'Espèces'
    type_assurance = 'non_assure'
    numero_assure = ''
    
    # CHAMPS POUR L'ASSURANCE COMPLÉMENTAIRE
    assurance2_nom = ''
    taux_assurance2 = 0
    prise_en_charge2 = 0
    numero_assure2 = ''
    
    # CHAMPS POUR LE MONTANT DONNÉ ET LE RENDU
    montant_donne = 0
    rendu = 0
    reste_a_payer = 0
    numero_facture = None
    
    # CHAMPS POUR L'AIDE HOSPITALIÈRE
    taux_aide = 0
    aide_hospitaliere = 0
    assurance_principale_active = True
    
    # ⭐ FIX : la route exigeait avant AND v.type = %s en plus de l'id — si le
    # type stocké en base diverge de la moindre façon du type demandé dans
    # l'URL (ex: vente réellement 'mixte' mais reçu ouvert avec type='actes',
    # ou toute incohérence de saisie historique), une vente pourtant bien
    # réelle et visible partout ailleurs dans l'appli renvoyait un 404. On
    # cherche maintenant par id + structure_id UNIQUEMENT (identifiant fiable
    # à lui seul), puis on détermine le type EFFECTIF à partir de la ligne
    # trouvée pour savoir quels articles afficher.
    vente = db.execute_query("""
        SELECT v.*, p.nom, p.prenom, p.type_assurance, p.numero_assure,
               p.assurance2_nom as patient_assurance2_nom,
               p.taux_assurance2 as patient_taux_assurance2,
               p.numero_assure2,
               v.reste_a_payer,
               v.base_remboursement,
               v.assurance_principale_active,
               v.taux_aide,
               v.aide_hospitaliere
        FROM ventes v
        LEFT JOIN patients p ON v.patient_id = p.id
        WHERE v.id = %s AND v.structure_id = %s
    """, (vente_id, structure_id))

    type_bd_stockee = None
    if vente and len(vente) > 0:
        v0 = vente[0]
        type_bd_stockee = v0.get('type') if isinstance(v0, dict) else (v0[3] if len(v0) > 3 else None)

    if type == 'mixte' or type_bd_stockee == 'mixte':
        type_bd = 'mixte'
    elif type_bd_stockee:
        type_bd = type_bd_stockee  # ⭐ on fait confiance à la valeur réelle en base
    else:
        type_bd = 'pharmacie' if type == 'pharma' else type

    print(f"🔍 Recherche vente {vente_id} (type reçu: {type}, type en base: {type_bd_stockee}, type retenu: {type_bd})")

    if not vente or len(vente) == 0:
        return f"Vente {vente_id} non trouvée (structure {structure_id})", 404
    
    if isinstance(vente[0], dict):
        v = vente[0]
        patient_nom = v.get('patient_nom', '')
        if not patient_nom:
            patient_nom = f"{v.get('nom', '')} {v.get('prenom', '')}".strip()
        if not patient_nom:
            patient_nom = 'Patient'
        
        mode_paiement = v.get('mode_paiement', 'Espèces')
        taux_assurance = float(v.get('taux_assurance', 0))
        
        sous_total = float(v.get('sous_total', 0))
        type_assurance = v.get('type_assurance', 'non_assure')
        numero_assure = v.get('numero_assure', '')
        
        base_remboursement = float(v.get('base_remboursement', 0)) if v.get('base_remboursement') is not None else 0
        
        assurance2_nom = v.get('assurance2_nom', '')
        taux_assurance2 = float(v.get('taux_assurance2', 0))
        prise_en_charge2 = float(v.get('prise_en_charge2', 0))
        numero_assure2 = v.get('numero_assure2', '')
        societe_assurance2 = v.get('societe_assurance2', '')
        
        assurance2_appliquee = assurance2_nom and assurance2_nom != '' and assurance2_nom != 'Aucune' and prise_en_charge2 > 0
        
        montant_donne = float(v.get('montant_donne', 0)) if v.get('montant_donne') is not None else 0
        rendu = float(v.get('rendu', 0)) if v.get('rendu') is not None else 0
        reste_a_payer = float(v.get('reste_a_payer', 0)) if v.get('reste_a_payer') is not None else 0
        
        assurance_principale_active = v.get('assurance_principale_active', True)
        taux_aide = float(v.get('taux_aide', 0)) if v.get('taux_aide') is not None else 0
        aide_hospitaliere = float(v.get('aide_hospitaliere', 0)) if v.get('aide_hospitaliere') is not None else 0
        
        patient_taux_original = float(v.get('patient_taux_assurance2', 0))
        
        taux_modifie = False
        taux_original = patient_taux_original
        
        if taux_assurance2 > 0 and patient_taux_original > 0:
            if abs(taux_assurance2 - patient_taux_original) > 0.01:
                taux_modifie = True
                print(f"🔴 TAUX MODIFIÉ DÉTECTÉ: {taux_assurance2}% (original: {patient_taux_original}%)")
        
        est_assure = type_assurance in ['amu_cnss', 'amu_inam']
        
        # 🔥🔥🔥 CORRECTION : Récupérer les articles (actes + produits) 🔥🔥🔥
        # Récupérer les actes
        actes_data = v.get('actes', [])
        if isinstance(actes_data, str):
            try:
                actes_data = json.loads(actes_data)
            except:
                actes_data = []
        
        # Récupérer les produits
        produits_data = v.get('produits', [])
        if isinstance(produits_data, str):
            try:
                produits_data = json.loads(produits_data)
            except:
                produits_data = []
        
        # 🔥🔥🔥 SI MIXTE : Prendre actes + produits 🔥🔥🔥
        # ⭐ FIX : se base sur type_bd (le type réellement stocké en base,
        # déterminé plus haut) plutôt que sur `type` (paramètre d'URL, qui
        # peut être un ancien lien 'actes'/'pharma' pour une vente en réalité
        # mixte) — sinon une vente mixte affiche uniquement ses actes OU ses
        # produits selon le lien utilisé pour ouvrir le reçu.
        if type_bd == 'mixte':
            # Utiliser actes_data + produits_data
            tous_articles = actes_data + produits_data
            print(f"📊 MIXTE: {len(actes_data)} actes + {len(produits_data)} produits = {len(tous_articles)} articles")
        else:
            # Sinon, prendre uniquement le type demandé
            if type_bd == 'pharmacie' or type_bd == 'pharma':
                tous_articles = produits_data
                print(f"📊 PHARMACIE: {len(produits_data)} produits")
            else:
                tous_articles = actes_data
                print(f"📊 ACTES: {len(actes_data)} actes")
        
        # 🔥 Traiter les articles
        sous_total_amu = 0
        pbr_total_amu = 0
        baseCAC = 0
        articles = []
        
        for item in tous_articles:
            # Déterminer le prix
            prix_unitaire = float(item.get('prix', item.get('prix_reel', item.get('prix_vente', 0))))
            if prix_unitaire == 0:
                prix_unitaire = float(item.get('prix_unitaire', 0))
            
            quantite = int(item.get('quantite', 1))
            total_article = prix_unitaire * quantite

            pbr_article = item.get('pbr')
            if pbr_article is None or pbr_article == '':
                pbr_article = prix_unitaire
            else:
                pbr_article = float(pbr_article)

            
            prise_amu = item.get('prise_en_charge_amu', True)
            prise_cac = item.get('prise_en_charge_cac', True)
            
            # Déterminer le type
            type_article = item.get('type', 'acte')
            if 'produit' in str(type_article).lower() or 'pharmacie' in str(type_article).lower():
                type_article = 'produit'
            else:
                type_article = 'acte'
            
            # 🔥 SEULEMENT SI PBR > 0, on calcule l'AMU et la CAC
            if prise_amu and pbr_article > 0:
                sous_total_amu += total_article
                pbr_total_amu += min(prix_unitaire, pbr_article) * quantite
            
            # CALCUL DE LA CAC
            if prise_cac:
                if est_assure and assurance_principale_active:
                    if prise_amu:
                        baseAMU = min(prix_unitaire, pbr_article)
                        priseAMU = (baseAMU * taux_assurance * quantite) / 100
                        reste = total_article - priseAMU
                        if reste > 0:
                            baseCAC += reste
                    else:
                        baseCAC += total_article
                else:
                    baseCAC += total_article
            
            articles.append({
                'nom': item.get('nom', 'Article'),
                'quantite': quantite,
                'prix_unitaire': prix_unitaire,
                'pbr': pbr_article,
                'total': total_article,
                'prise_en_charge_amu': prise_amu,
                'prise_en_charge_cac': prise_cac,
                'type': type_article
            })
        
        # 🔥 Appliquer le taux CAC
        if baseCAC > 0 and taux_assurance2 > 0:
            prise_en_charge2 = (baseCAC * taux_assurance2) / 100
        else:
            prise_en_charge2 = 0
        
        # ⭐⭐⭐ RECALCUL DE LA PRISE EN CHARGE AMU ⭐⭐⭐
        prise_en_charge = 0
        if est_assure and assurance_principale_active:
            base = pbr_total_amu
            if sous_total_amu < pbr_total_amu:
                base = sous_total_amu
            if base > 0 and taux_assurance > 0:
                prise_en_charge = (base * taux_assurance) / 100
            print(f"📊 Patient assuré - Base PBR: {base}, Prise en charge: {prise_en_charge}")
        else:
            prise_en_charge = 0
            print(f"📊 Patient non assuré ou assurance désactivée - Pas d'AMU")
        
        # 🔥🔥🔥 RECALCUL DE L'AIDE HOSPITALIÈRE 🔥🔥🔥
        aide_hospitaliere_calculee = 0
        
        if taux_aide > 0:
            if est_assure and assurance_principale_active:
                base_aide = sous_total - prise_en_charge - prise_en_charge2
                print(f"📊 Cas 1 - Patient assuré, base aide = reste après AMU+CAC: {base_aide}")
            elif assurance2_appliquee and not est_assure:
                base_aide = sous_total - prise_en_charge2
                print(f"📊 Cas 2 - Patient non assuré avec CAC, base aide = reste après CAC: {base_aide}")
            else:
                base_aide = sous_total
                print(f"📊 Cas 3 - Patient non assuré sans CAC, base aide = sous-total: {base_aide}")
            
            if base_aide > 0 and taux_aide > 0:
                aide_hospitaliere_calculee = (base_aide * taux_aide) / 100
                print(f"📊 Aide hospitalière recalculée: {aide_hospitaliere_calculee} FCFA (taux {taux_aide}%)")
        
        # 🔥🔥🔥 CALCUL DU NET AVEC AIDE HOSPITALIÈRE RECALCULÉE 🔥🔥🔥
        net_a_payer = sous_total - prise_en_charge - prise_en_charge2 - aide_hospitaliere_calculee
        if net_a_payer < 0:
            net_a_payer = 0
        
        print(f"📊 Sous-total: {sous_total}, AMU: {prise_en_charge}, CAC: {prise_en_charge2}, Aide recalculée: {aide_hospitaliere_calculee}, Net: {net_a_payer}")
        
        aide_hospitaliere = aide_hospitaliere_calculee
    
    # Gestion des assurances
    assurance_text = type_assurance
    if type_assurance == 'amu_cnss':
        assurance_text = 'AMU-CNSS'
    elif type_assurance == 'amu_inam':
        assurance_text = 'AMU-INAM'
    elif type_assurance == 'non_assure':
        assurance_text = 'Non assuré'
    
    assurance2_appliquee = False
    if assurance2_nom and assurance2_nom != '' and assurance2_nom != 'Aucune' and prise_en_charge2 > 0:
        assurance2_appliquee = True
        
    return render_template('recu_client.html',
                         vente_id=vente_id,
                         articles=articles,
                         sous_total=sous_total,
                         base_remboursement=base_remboursement,
                         taux_assurance=taux_assurance,
                         prise_en_charge=prise_en_charge,
                         net_a_payer=net_a_payer,
                         patient_nom=patient_nom,
                         type_assurance=assurance_text,
                         numero_assure=numero_assure,
                         mode_paiement=mode_paiement,
                         structure_nom=structure_nom,
                         structure_adresse=structure_adresse,
                         structure_telephone=structure_telephone,
                         structure_email=structure_email,
                         date_actuelle=datetime.now().strftime('%d/%m/%Y %H:%M'),
                         structure_logo=structure_logo,
                         nom_caissier=session.get('user_name', ''),
                         assurance2_nom=assurance2_nom,
                         taux_assurance2=taux_assurance2,
                         prise_en_charge2=prise_en_charge2,
                         numero_assure2=numero_assure2,
                         societe_assurance2=societe_assurance2,
                         assurance2_appliquee=assurance2_appliquee,
                         taux_modifie=taux_modifie,
                         taux_original=taux_original,
                         montant_donne=montant_donne,
                         rendu=rendu,
                         reste_a_payer=reste_a_payer,
                         numero_facture=numero_facture,
                         assurance_principale_active=assurance_principale_active,
                         taux_aide=taux_aide,
                         aide_hospitaliere=aide_hospitaliere)

@app.route('/recu_structure/<int:vente_id>/<string:type>')
@login_required
def recu_structure(vente_id, type):
    """Reçu pour la structure (copie comptable)"""
    from datetime import datetime
    import json
    
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return "Structure non trouvée", 404
    
    # Récupérer les infos de la structure
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    structure_nom = structure_info.get('nom', 'Medilogic-GHP')
    structure_adresse = structure_info.get('adresse', '')
    structure_telephone = structure_info.get('telephone', '')
    structure_email = structure_info.get('email', '')
    structure_logo = structure_info.get('logo_url', '')
    
    articles = []
    sous_total = 0
    taux_assurance = 0
    prise_en_charge = 0
    net_a_payer = 0
    patient_nom = 'Patient'
    mode_paiement = 'Espèces'
    type_assurance = 'non_assure'
    numero_assure = ''
    
    # CHAMPS POUR L'ASSURANCE COMPLÉMENTAIRE
    assurance2_nom = ''
    taux_assurance2 = 0
    prise_en_charge2 = 0
    numero_assure2 = ''
    
    # ⭐ FIX : même correctif que /recu — ne pas exiger v.type = %s en plus
    # de l'id, sinon une vente réelle mais dont le type stocké diverge du
    # type de l'URL (ex: mixte) renvoie un faux "non trouvée". On récupère
    # par id + structure_id, puis on déduit type_bd de la ligne trouvée.
    vente = db.execute_query("""
        SELECT v.*, p.nom, p.prenom, p.type_assurance, p.numero_assure,
               p.assurance2_nom as patient_assurance2_nom,
               p.taux_assurance2 as patient_taux_assurance2,
               p.numero_assure2
        FROM ventes v
        LEFT JOIN patients p ON v.patient_id = p.id
        WHERE v.id = %s AND v.structure_id = %s
    """, (vente_id, structure_id))

    if not vente or len(vente) == 0:
        return f"Vente {vente_id} non trouvée", 404

    v0 = vente[0]
    type_bd_stockee = v0.get('type') if isinstance(v0, dict) else (v0[3] if len(v0) > 3 else None)
    type_bd = type_bd_stockee or ('pharmacie' if type == 'pharma' else type)
    
    if isinstance(vente[0], dict):
        v = vente[0]
        patient_nom = v.get('patient_nom', '')
        if not patient_nom:
            patient_nom = f"{v.get('nom', '')} {v.get('prenom', '')}".strip()
        if not patient_nom:
            patient_nom = 'Patient'
        
        mode_paiement = v.get('mode_paiement', 'Espèces')
        taux_assurance = float(v.get('taux_assurance', 0))
        prise_en_charge = float(v.get('prise_en_charge', 0))
        net_a_payer = float(v.get('net_a_payer', 0))
        sous_total = float(v.get('sous_total', 0))
        type_assurance = v.get('type_assurance', 'non_assure')
        numero_assure = v.get('numero_assure', '')
        
        # Récupérer les données de l'assurance complémentaire
        assurance2_nom = v.get('assurance2_nom', '')
        taux_assurance2 = float(v.get('taux_assurance2', 0))
        prise_en_charge2 = float(v.get('prise_en_charge2', 0))
        numero_assure2 = v.get('numero_assure2', '')
        societe_assurance2 = v.get('societe_assurance2', '')
        
        # Récupérer le taux original du patient
        patient_taux_original = float(v.get('patient_taux_assurance2', 0))
        
        # Déterminer si le taux a été modifié
        taux_modifie = False
        taux_original = patient_taux_original
        
        if taux_assurance2 > 0 and patient_taux_original > 0:
            if abs(taux_assurance2 - patient_taux_original) > 0.01:
                taux_modifie = True
        
        # Récupérer les articles
        if type_bd == 'pharmacie' or type_bd == 'pharma':
            produits_data = v.get('produits', [])
            if isinstance(produits_data, str):
                produits_data = json.loads(produits_data)
            for p in produits_data:
                articles.append({
                    'nom': p.get('nom', 'Produit'),
                    'quantite': int(p.get('quantite', 1)),
                    'prix_unitaire': float(p.get('prix_reel', p.get('prix', 0))),
                    'total': float(p.get('total', 0))
                })
        else:
            actes_data = v.get('actes', [])
            if isinstance(actes_data, str):
                actes_data = json.loads(actes_data)
            for a in actes_data:
                articles.append({
                    'nom': a.get('nom', 'Acte'),
                    'quantite': int(a.get('quantite', 1)),
                    'prix_unitaire': float(a.get('prix', 0)),
                    'total': float(a.get('total', 0))
                })
    
    # Gestion des assurances
    assurance_text = type_assurance
    if type_assurance == 'amu_cnss':
        assurance_text = 'AMU-CNSS'
    elif type_assurance == 'amu_inam':
        assurance_text = 'AMU-INAM'
    elif type_assurance == 'non_assure':
        assurance_text = 'Non assuré'
    
    # Déterminer si l'assurance complémentaire a été appliquée
    assurance2_appliquee = False
    if assurance2_nom and assurance2_nom != '' and assurance2_nom != 'Aucune' and prise_en_charge2 > 0:
        assurance2_appliquee = True
    
    patient_nom_clean = patient_nom.replace(' ', '_').replace("'", "").replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('à', 'a').replace('ç', 'c')
    nom_fichier = f"recu_structure_{patient_nom_clean}_{vente_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    return render_template('recu_structure.html',
                         vente_id=vente_id,
                         articles=articles,
                         sous_total=sous_total,
                         taux_assurance=taux_assurance,
                         prise_en_charge=prise_en_charge,
                         net_a_payer=net_a_payer,
                         patient_nom=patient_nom,
                         type_assurance=assurance_text,
                         numero_assure=numero_assure,
                         mode_paiement=mode_paiement,
                         structure_nom=structure_nom,
                         structure_adresse=structure_adresse,
                         structure_telephone=structure_telephone,
                         structure_email=structure_email,
                         date_actuelle=datetime.now().strftime('%d/%m/%Y %H:%M'),
                         structure_logo=structure_logo,
                         nom_caissier=session.get('user_name', ''),
                         nom_fichier=nom_fichier,
                         assurance2_nom=assurance2_nom,
                         taux_assurance2=taux_assurance2,
                         prise_en_charge2=prise_en_charge2,
                         numero_assure2=numero_assure2,
                         societe_assurance2=societe_assurance2,
                         assurance2_appliquee=assurance2_appliquee,
                         taux_modifie=taux_modifie,
                         taux_original=taux_original)

@app.route('/historique_ventes')
@login_required
def historique_ventes():
    """Affiche l'historique des ventes avec stats"""
    structure_id = session.get('structure_id')
    
    # ========== 1. VENTES ACTES (Neon) ==========
    ventes_actes_db = db.execute_query("""
        SELECT 
            id, patient_nom, net_a_payer, taux_assurance, 
            date_vente, actes, created_by_nom,
            montant_donne, rendu,
            sous_total, prise_en_charge, prise_en_charge2
        FROM ventes 
        WHERE structure_id = %s 
        AND type = 'actes'
        AND (statut IS NULL OR statut != 'annulee')
        ORDER BY date_vente DESC
    """, (structure_id,))
    
    ventes_actes = []
    ca_actes = 0
    
    for v in ventes_actes_db:
        if isinstance(v, dict):
            import json
            actes_data = v.get('actes')
            if isinstance(actes_data, str):
                try:
                    actes_data = json.loads(actes_data)
                except:
                    actes_data = []
            
            nom_acte = 'Acte'
            if actes_data and len(actes_data) > 0:
                nom_acte = actes_data[0].get('nom', 'Acte')
            
            montant_donne = float(v.get('montant_donne', 0))
            rendu = float(v.get('rendu', 0))
            ca_effectif = montant_donne - rendu
            ca_actes += ca_effectif
            
            ventes_actes.append({
                'ID': v.get('id'),
                'patient_nom': v.get('patient_nom', 'Patient'),
                'type': 'actes',
                'acte_nom': nom_acte,
                'net_a_payer': float(v.get('net_a_payer', 0)),
                'taux_assurance': v.get('taux_assurance', 0),
                'date': str(v.get('date_vente', '')),
                'created_by_nom': v.get('created_by_nom', 'System'),
                'montant_donne': montant_donne,
                'rendu': rendu,
                'ca_effectif': ca_effectif
            })
    
    # ========== 2. VENTES PHARMACIE (Neon) ==========
    ventes_pharma_db = db.execute_query("""
        SELECT 
            id, patient_nom, net_a_payer, taux_assurance, 
            date_vente, produits, created_by_nom,
            montant_donne, rendu
        FROM ventes 
        WHERE structure_id = %s 
        AND type IN ('pharma', 'pharmacie')
        AND (statut IS NULL OR statut != 'annulee')
        ORDER BY date_vente DESC
    """, (structure_id,))
    
    ventes_pharma = []
    ca_pharma = 0
    
    for v in ventes_pharma_db:
        if isinstance(v, dict):
            import json
            produits_data = v.get('produits')
            if isinstance(produits_data, str):
                try:
                    produits_data = json.loads(produits_data)
                except:
                    produits_data = []
            
            nom_produit = 'Produit'
            if produits_data and len(produits_data) > 0:
                nom_produit = produits_data[0].get('nom', 'Produit')
            
            montant_donne = float(v.get('montant_donne', 0))
            rendu = float(v.get('rendu', 0))
            ca_effectif = montant_donne - rendu
            ca_pharma += ca_effectif
            
            ventes_pharma.append({
                'ID': v.get('id'),
                'patient_nom': v.get('patient_nom', 'Patient'),
                'type': 'pharma',
                'acte_nom': nom_produit,
                'produit_nom': nom_produit,
                'net_a_payer': float(v.get('net_a_payer', 0)),
                'taux_assurance': v.get('taux_assurance', 0),
                'date': str(v.get('date_vente', '')),
                'created_by_nom': v.get('created_by_nom', 'System'),
                'montant_donne': montant_donne,
                'rendu': rendu,
                'ca_effectif': ca_effectif
            })
    
    # ========== 3. FUSIONNER ET TRIER ==========
    toutes_ventes = ventes_actes + ventes_pharma
    
    def get_date_key(x):
        date_val = x.get('date', '')
        return str(date_val) if date_val else ''
    
    toutes_ventes.sort(key=get_date_key, reverse=True)
    
    # ========== 4. STATISTIQUES ==========
    total_actes = len(ventes_actes)
    total_pharma = len(ventes_pharma)
    
    # 🔥 CA total = somme des CA effectifs
    ca_total = ca_actes + ca_pharma
    
    # Top actes
    actes_count = {}
    for v in ventes_actes:
        nom = v.get('acte_nom', 'Acte')
        # Compter les ventes, pas les quantités (car on a pas la quantité dans la vente)
        if nom not in actes_count:
            actes_count[nom] = {'quantite': 0, 'total': 0}
        actes_count[nom]['quantite'] += 1
        actes_count[nom]['total'] += v.get('net_a_payer', 0)
    
    top_actes = sorted(actes_count.items(), key=lambda x: x[1]['quantite'], reverse=True)[:5]
    top_actes_list = [{'nom': k, 'quantite': v['quantite'], 'total': v['total']} for k, v in top_actes]
    
    # Top produits
    produits_count = {}
    for v in ventes_pharma:
        nom = v.get('produit_nom', 'Produit')
        if nom not in produits_count:
            produits_count[nom] = {'quantite': 0, 'total': 0}
        produits_count[nom]['quantite'] += 1
        produits_count[nom]['total'] += v.get('net_a_payer', 0)
    
    top_produits = sorted(produits_count.items(), key=lambda x: x[1]['quantite'], reverse=True)[:5]
    top_produits_list = [{'nom': k, 'quantite': v['quantite'], 'total': v['total']} for k, v in top_produits]
    
    stats = {
        'total_ventes': len(toutes_ventes),
        'total_actes': total_actes,
        'total_pharma': total_pharma,
        'ca_total': ca_total,  # ✅ CA corrigé
        'top_actes': top_actes_list,
        'top_produits': top_produits_list
    }
    
    return render_template('historique_ventes.html', ventes=toutes_ventes, stats=stats)

# ========== ADMIN STRUCTURE API ==========
@app.route('/api/admin/users', methods=['POST'])
@login_required
def api_add_user():
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        sheet_name = f"struct_{structure_id}_users"
        
        # Récupérer la feuille
        try:
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        except:
            # Si la feuille n'existe pas, la créer
            worksheet = sheets_helper.spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=10)
            # Ajouter les en-têtes
            headers = ['ID', 'nom', 'email', 'mot_de_passe', 'role', 'structure_id', 'created_at', 'actif']
            worksheet.append_row(headers)
        
        user_id = data.get('id')
        
        if user_id and user_id != '' and user_id != 'null' and user_id != 0:
            # Modification
            print(f"✏️ Modification ID: {user_id}")
            cell = worksheet.find(str(user_id), in_column=1)
            if cell:
                row_num = cell.row
                current_row = worksheet.row_values(row_num)
                while len(current_row) < 9:
                    current_row.append('')
                current_row[1] = data.get('nom')
                current_row[2] = data.get('email')
                if data.get('password') and data.get('password').strip():
                    current_row[3] = hash_password(data.get('password'))
                current_row[4] = data.get('role')
                current_row[7] = data.get('actif', 'oui')
                # current_row[8] = dernière connexion (ne pas toucher)

                worksheet.update(range_name=f'A{row_num}:H{row_num}', values=[current_row])
                return jsonify({'success': True, 'id': user_id})
            else:
                return jsonify({'success': False, 'error': 'Utilisateur non trouvé'}), 404
        else:
            # Ajout
            print(f"➕ Ajout nouvel utilisateur")
            all_records = worksheet.get_all_records()
            existing_ids = [int(r.get('ID', 0)) for r in all_records if r.get('ID')]
            new_id = max(existing_ids) + 1 if existing_ids else 1
            
            new_user = [
                new_id,
                data.get('nom'),
                data.get('email'),
                hash_password(data.get('password', 'default123')),
                data.get('role', 'caissier'),
                structure_id,
                datetime.now().isoformat(),
                data.get('actif', 'oui'),
                ''  # dernière connexion (vide)
            ]
            worksheet.append_row(new_user)
            return jsonify({'success': True, 'id': new_id})
            
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>/toggle', methods=['POST'])
@login_required
def api_toggle_user(user_id):
    """Activer/Désactiver un utilisateur"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        nouveau_statut = data.get('actif', 'non')
        
        sheet_name = f"struct_{structure_id}_users"
        worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        
        # Trouver l'utilisateur
        cell = worksheet.find(str(user_id), in_column=1)
        if not cell:
            return jsonify({'success': False, 'error': 'Utilisateur non trouvé'}), 404
        
        row_num = cell.row
        current_row = worksheet.row_values(row_num)
        
        print(f"Ligne actuelle: {current_row}")
        print(f"Nombre de colonnes: {len(current_row)}")
        
        # Ajouter la colonne actif si elle n'existe pas
        if len(current_row) < 9:
            # Étendre la ligne jusqu'à la colonne I
            while len(current_row) < 9:
                current_row.append('')
        
        # Mettre à jour la colonne actif (index 7 = colonne H)
        current_row[7] = nouveau_statut
        
        # 🔥 Correction : update avec les bons paramètres
        worksheet.update(range_name=f'A{row_num}:I{row_num}', values=[current_row])
        
        return jsonify({'success': True, 'message': f'Statut mis à jour'})
        
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def api_delete_user(user_id):
    """Supprimer un utilisateur"""
    try:
        structure_id = session.get('structure_id')
        sheet_name = f"struct_{structure_id}_users"
        
        print(f"Recherche dans la feuille: {sheet_name}")
        
        # Récupérer la feuille
        worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        
        # Chercher l'utilisateur
        cell = worksheet.find(str(user_id), in_column=1)
        
        if cell:
            print(f"Utilisateur trouvé à la ligne {cell.row}, suppression...")
            # 🔥 Utiliser delete_rows au lieu de delete_row
            worksheet.delete_rows(cell.row)
            return jsonify({'success': True, 'message': 'Utilisateur supprimé'})
        else:
            print(f"Utilisateur {user_id} non trouvé")
            return jsonify({'success': False, 'error': 'Utilisateur non trouvé'}), 404
            
    except Exception as e:
        print(f"Erreur suppression: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin_structure')
@login_required
def admin_structure():
    """Administration de la structure"""
    structure_id = session.get('structure_id')

    # Récupérer les utilisateurs avec la dernière connexion
    sheet_name = f"struct_{structure_id}_users"
    users = sheets_helper.get_all_records(sheet_name)
    
    users_list = []
    for u in users:
        users_list.append({
            'ID': u.get('ID'),
            'nom': u.get('nom'),
            'email': u.get('email'),
            'role': u.get('role'),
            'actif': u.get('actif', 'oui'),
            'derniere_connexion': u.get('derniere_connexion', '-'),
            'created_at': u.get('created_at', '')
        })
    
    # Récupérer les utilisateurs
    users = sheets_helper.get_all_records('users')
    users = [u for u in users if str(u.get('structure_id')) == str(structure_id)]
    
    # Récupérer les actes
    actes = sheets_helper.get_all_records('actes')
    actes = [a for a in actes if str(a.get('structure_id')) == str(structure_id)]
    
    # Récupérer les produits
    produits = sheets_helper.get_all_records('produits')
    produits = [p for p in produits if str(p.get('structure_id')) == str(structure_id)]
    
    # Récupérer les infos de la structure
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    return render_template('admin_structure.html', 
                         users=users, 
                         actes=actes, 
                         produits=produits,
                         structure_info=structure_info)

@app.route('/api/admin/actes', methods=['POST'])
@login_required
def api_add_acte():
    """Ajouter ou modifier un acte dans Google Sheets"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvée'}), 400
        
        sheet_name = f"struct_{structure_id}_actes"
        
        try:
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        except:
            # Créer la feuille avec les en-têtes
            worksheet = sheets_helper.spreadsheet.add_worksheet(
                title=sheet_name,
                rows=1000,
                cols=20
            )
            headers = ['ID', 'nom', 'prix', 'pbr', 'description', 'structure_id',
                       'prise_en_charge_amu', 'commentaire_amu', 
                       'prise_en_charge_cac', 'commentaire_cac']
            worksheet.append_row(headers)
        
        acte_id = data.get('id')
        
        if acte_id:
            # 🔥 MODIFICATION
            values = worksheet.get_all_values()
            row_num = None
            for i, row in enumerate(values, start=1):
                if i == 1: continue
                if row and row[0] == str(acte_id):
                    row_num = i
                    break
            
            if row_num:
                worksheet.update_cell(row_num, 2, data.get('nom', ''))
                worksheet.update_cell(row_num, 3, data.get('prix', 0))
                worksheet.update_cell(row_num, 4, data.get('pbr', data.get('prix', 0)))
                worksheet.update_cell(row_num, 5, data.get('description', ''))
                worksheet.update_cell(row_num, 6, structure_id)
                worksheet.update_cell(row_num, 7, data.get('prise_en_charge_amu', True))
                worksheet.update_cell(row_num, 8, data.get('commentaire_amu', ''))
                worksheet.update_cell(row_num, 9, data.get('prise_en_charge_cac', True))
                worksheet.update_cell(row_num, 10, data.get('commentaire_cac', ''))
                print(f"✅ Acte {acte_id} modifié dans Sheets")
                return jsonify({'success': True, 'message': 'Acte modifié avec succès'})
            else:
                return jsonify({'success': False, 'error': 'Acte non trouvé'}), 404
        
        else:
            # 🔥 AJOUT
            all_records = worksheet.get_all_records()
            if all_records:
                ids = [r.get('ID', 0) for r in all_records if r.get('ID')]
                new_id = max(ids) + 1 if ids else 1
            else:
                new_id = 1
            
            new_row = [
                new_id,
                data.get('nom', ''),
                data.get('prix', 0),
                data.get('pbr', data.get('prix', 0)),
                data.get('description', ''),
                structure_id,
                data.get('prise_en_charge_amu', True),
                data.get('commentaire_amu', ''),
                data.get('prise_en_charge_cac', True),
                data.get('commentaire_cac', '')
            ]
            worksheet.append_row(new_row)
            print(f"✅ Nouvel acte ajouté dans Sheets avec ID: {new_id}")
            
            return jsonify({
                'success': True, 
                'message': 'Acte ajouté avec succès',
                'id': new_id
            })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/actes/<int:acte_id>', methods=['DELETE'])
@login_required
def api_delete_acte(acte_id):
    """Supprimer un acte dans Google Sheets"""
    try:
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvée'}), 400
        
        sheet_name = f"struct_{structure_id}_actes"
        worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        
        values = worksheet.get_all_values()
        for i, row in enumerate(values, start=1):
            if i == 1: continue
            if row and row[0] == str(acte_id):
                worksheet.delete_rows(i)
                print(f"✅ Acte {acte_id} supprimé de Sheets")
                return jsonify({'success': True, 'message': 'Acte supprimé avec succès'})
        
        return jsonify({'success': False, 'error': f'Acte {acte_id} non trouvé'}), 404
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/produits/<int:produit_id>', methods=['DELETE'])
@login_required
def api_delete_produit(produit_id):
    # À implémenter
    return jsonify({'success': True})

@app.route('/api/admin/structure', methods=['PUT'])
@login_required
@admin_required
def api_update_structure():
    data = request.json
    structure_id = session.get('structure_id')
    
    try:
        sheet_structures = sheets_helper.spreadsheet.worksheet("structures")
        cell = sheet_structures.find(str(structure_id), in_column=1)
        
        if cell:
            row_num = cell.row
            current_row = sheet_structures.row_values(row_num)
            
            # 🔥 INDEX CORRECTS (0-based)
            # A=0, B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, J=9, K=10, L=11, M=12...
            
            # Mettre à jour les colonnes
            current_row[1] = data.get('nom')           # colonne B (nom)
            current_row[2] = data.get('email')         # colonne C (email)
            current_row[3] = data.get('telephone')     # colonne D (téléphone)
            current_row[4] = data.get('adresse')       # colonne E (adresse)
            
            # 🔥 LOGO_URL à l'index 11 (colonne L)
            if len(current_row) > 11:
                current_row[11] = data.get('logo_url', '')
            else:
                while len(current_row) <= 11:
                    current_row.append('')
                current_row[11] = data.get('logo_url', '')
            
            # Mettre à jour jusqu'à la colonne M (index 12)
            sheet_structures.update(f'A{row_num}:M{row_num}', [current_row])
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404
            
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/debug_ventes')
@login_required
def debug_ventes():
    structure_id = session.get('structure_id')
    
    ventes_actes = sheets_helper.get_all_records('ventes_actes')
    ventes_pharma = sheets_helper.get_all_records('ventes_pharma')
    
    result = {
        'structure_id': structure_id,
        'ventes_actes': [],
        'ventes_pharma': []
    }
    
    for v in ventes_actes:
        if str(v.get('structure_id')) == str(structure_id):
            result['ventes_actes'].append({
                'ID': v.get('ID'),
                'patient_nom': v.get('patient_nom'),
                'date': v.get('date'),
                'total': v.get('total')
            })
    
    for v in ventes_pharma:
        if str(v.get('structure_id')) == str(structure_id):
            result['ventes_pharma'].append({
                'ID': v.get('ID'),
                'patient_nom': v.get('patient_nom'),
                'date': v.get('date'),
                'total': v.get('total')
            })
    
    return jsonify(result)


# ============================================================
# ROUTES POUR LES MEDECINS (NOUVELLES)
# ============================================================

# ============================================================
# ROUTES POUR LA GESTION DES MEDECINS
# ============================================================

@app.route('/medecins')
@login_required
def gestion_medecins():
    """Page de gestion des medecins"""
    structure_id = session.get('structure_id')
    
    # Recuperer les medecins (sans qualification)
    medecins = db.execute_query("""
        SELECT 
            id, nom, prenom, titre, specialite,
            telephone, email, honoraire_consultation, actif
        FROM medecins 
        WHERE structure_id = %s
        ORDER BY nom
    """, (structure_id,))
    
    medecins_list = []
    for m in medecins:
        # Si c'est un dictionnaire, utiliser .get()
        if isinstance(m, dict):
            med_id = m.get('id')
            # Compter les consultations
            nb = db.execute_query("""
                SELECT COUNT(*) FROM rendez_vous 
                WHERE medecin_id = %s AND statut = 'termine'
            """, (med_id,))
            
            # CORRECTION ICI: nb est une liste de dictionnaires
            nb_consultations = nb[0].get('count') if nb and len(nb) > 0 else 0
            # OU si la clé est 'count'
            # nb_consultations = nb[0]['count'] if nb and len(nb) > 0 else 0
            
            medecins_list.append({
                'id': med_id,
                'nom': m.get('nom'),
                'prenom': m.get('prenom'),
                'titre': m.get('titre', 'Dr'),
                'specialite': m.get('specialite'),
                'qualification': m.get('specialite', ''),
                'telephone': m.get('telephone'),
                'email': m.get('email'),
                'honoraire': m.get('honoraire_consultation', 0),
                'actif': m.get('actif', True),
                'nb_consultations': nb_consultations
            })
        else:
            # Si c'est un tuple, utiliser les indices
            med_id = m[0]
            nb = db.execute_query("""
                SELECT COUNT(*) FROM rendez_vous 
                WHERE medecin_id = %s AND statut = 'termine'
            """, (med_id,))
            
            # CORRECTION ICI: nb est une liste de dictionnaires
            nb_consultations = nb[0].get('count') if nb and len(nb) > 0 else 0
            
            medecins_list.append({
                'id': med_id,
                'nom': m[1],
                'prenom': m[2],
                'titre': m[3] if len(m) > 3 else 'Dr',
                'specialite': m[4] if len(m) > 4 else '',
                'qualification': m[4] if len(m) > 4 else '',
                'telephone': m[5] if len(m) > 5 else '',
                'email': m[6] if len(m) > 6 else '',
                'honoraire': m[7] if len(m) > 7 else 0,
                'actif': m[8] if len(m) > 8 else True,
                'nb_consultations': nb_consultations
            })
    
    return render_template('medecins.html', medecins=medecins_list)

@app.route('/api/medecins', methods=['POST'])
@login_required
def api_ajouter_medecin():
    """Ajouter un nouveau medecin"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        # Validation
        required = ['nom', 'specialite']
        for field in required:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Le champ {field} est requis'}), 400
        
        # Verifier si le medecin existe deja
        existant = db.execute_query("""
            SELECT id FROM medecins 
            WHERE nom = %s AND prenom = %s AND structure_id = %s
        """, (data.get('nom'), data.get('prenom', ''), structure_id))
        
        if existant and len(existant) > 0:
            return jsonify({'success': False, 'error': 'Ce medecin existe deja'}), 400
        
        # Inserer le medecin
        result = db.execute_query("""
            INSERT INTO medecins (
                structure_id,
                nom,
                prenom,
                titre,
                specialite,
                qualification,
                telephone,
                email,
                honoraire_consultation,
                actif
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            structure_id,
            data.get('nom'),
            data.get('prenom', ''),
            data.get('titre', 'Dr'),
            data.get('specialite'),
            data.get('qualification', ''),
            data.get('telephone', ''),
            data.get('email', ''),
            data.get('honoraire_consultation', 0),
            data.get('actif', True)
        ))
        
        if result and len(result) > 0:
            medecin_id = result[0]['id'] if isinstance(result[0], dict) else result[0][0]
            return jsonify({'success': True, 'id': medecin_id, 'message': 'Medecin ajoute avec succes'})
        else:
            return jsonify({'success': False, 'error': 'Erreur lors de l\'insertion'}), 500
            
    except Exception as e:
        print(f"Erreur ajout medecin: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/medecins/<int:id>', methods=['PUT'])
@login_required
def api_modifier_medecin(id):
    """Modifier un medecin"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        # Verifier que le medecin existe
        medecin = db.execute_query("""
            SELECT id FROM medecins WHERE id = %s AND structure_id = %s
        """, (id, structure_id))
        
        if not medecin or len(medecin) == 0:
            return jsonify({'success': False, 'error': 'Medecin non trouve'}), 404
        
        # Mettre a jour
        db.execute_query("""
            UPDATE medecins SET
                nom = %s,
                prenom = %s,
                titre = %s,
                specialite = %s,
                qualification = %s,
                telephone = %s,
                email = %s,
                honoraire_consultation = %s,
                actif = %s
            WHERE id = %s AND structure_id = %s
        """, (
            data.get('nom'),
            data.get('prenom', ''),
            data.get('titre', 'Dr'),
            data.get('specialite'),
            data.get('qualification', ''),
            data.get('telephone', ''),
            data.get('email', ''),
            data.get('honoraire_consultation', 0),
            data.get('actif', True),
            id,
            structure_id
        ))
        
        return jsonify({'success': True, 'message': 'Medecin modifie avec succes'})
        
    except Exception as e:
        print(f"Erreur modification medecin: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/medecins/<int:id>/toggle', methods=['POST'])
@login_required
def api_toggle_medecin(id):
    """Activer/Desactiver un medecin"""
    try:
        structure_id = session.get('structure_id')
        
        # Recuperer le statut actuel
        medecin = db.execute_query("""
            SELECT actif FROM medecins WHERE id = %s AND structure_id = %s
        """, (id, structure_id))
        
        if not medecin or len(medecin) == 0:
            return jsonify({'success': False, 'error': 'Medecin non trouve'}), 404
        
        actif = medecin[0][0] if medecin[0] else True
        nouveau_statut = not actif
        
        db.execute_query("""
            UPDATE medecins SET actif = %s WHERE id = %s AND structure_id = %s
        """, (nouveau_statut, id, structure_id))
        
        return jsonify({
            'success': True, 
            'actif': nouveau_statut,
            'message': f'Medecin {"active" if nouveau_statut else "desactive"} avec succes'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/medecins/<int:id>/historique', methods=['GET'])
@login_required
def api_historique_medecin(id):
    """Recupere l'historique complet d'un medecin - Version robuste"""
    structure_id = session.get('structure_id')
    
    try:
        # 1. Recuperer les informations du medecin
        medecin = db.execute_query("""
            SELECT id, nom, prenom, titre, specialite, telephone, email
            FROM medecins 
            WHERE id = %s AND structure_id = %s
        """, (id, structure_id))
        
        if not medecin or len(medecin) == 0:
            return jsonify({'error': 'Medecin non trouve'}), 404
        
        # Extraire les infos du medecin
        if isinstance(medecin[0], dict):
            m = medecin[0]
            info = {
                'id': m.get('id'),
                'nom': m.get('nom'),
                'prenom': m.get('prenom'),
                'titre': m.get('titre', 'Dr'),
                'specialite': m.get('specialite'),
                'telephone': m.get('telephone'),
                'email': m.get('email')
            }
        else:
            m = medecin[0]
            info = {
                'id': m[0],
                'nom': m[1],
                'prenom': m[2],
                'titre': m[3] if len(m) > 3 else 'Dr',
                'specialite': m[4] if len(m) > 4 else '',
                'telephone': m[5] if len(m) > 5 else '',
                'email': m[6] if len(m) > 6 else ''
            }
        
        # 2. Recuperer les statistiques avec TO_CHAR
        stats = db.execute_query("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN statut = 'termine' THEN 1 END) as termines,
                COUNT(CASE WHEN statut = 'annule' THEN 1 END) as annules,
                COUNT(CASE WHEN statut = 'confirme' THEN 1 END) as confirmes,
                COUNT(CASE WHEN statut = 'programme' THEN 1 END) as programmes,
                COUNT(CASE WHEN statut = 'reporte' THEN 1 END) as reportes
            FROM rendez_vous
            WHERE medecin_id = %s AND structure_id = %s
        """, (id, structure_id))
        
        # Extraire les stats
        if stats and len(stats) > 0:
            if isinstance(stats[0], dict):
                s = stats[0]
                stats_data = {
                    'total': int(s.get('total', 0) or 0),
                    'termines': int(s.get('termines', 0) or 0),
                    'annules': int(s.get('annules', 0) or 0),
                    'confirmes': int(s.get('confirmes', 0) or 0),
                    'programmes': int(s.get('programmes', 0) or 0),
                    'reportes': int(s.get('reportes', 0) or 0)
                }
            else:
                s = stats[0]
                stats_data = {
                    'total': int(s[0]) if len(s) > 0 and s[0] else 0,
                    'termines': int(s[1]) if len(s) > 1 and s[1] else 0,
                    'annules': int(s[2]) if len(s) > 2 and s[2] else 0,
                    'confirmes': int(s[3]) if len(s) > 3 and s[3] else 0,
                    'programmes': int(s[4]) if len(s) > 4 and s[4] else 0,
                    'reportes': int(s[5]) if len(s) > 5 and s[5] else 0
                }
        else:
            stats_data = {'total': 0, 'termines': 0, 'annules': 0, 'confirmes': 0, 'programmes': 0, 'reportes': 0}
        
        # 3. Recuperer l'historique - TOUT EN STRING avec TO_CHAR
        # ⭐ FIX : la table rendez_vous a DEUX paires de colonnes date/heure
        # (date_rdv/heure_rdv ET date_rendez_vous/heure_rendez_vous, issues
        # de deux flux de creation de RDV differents dans l'app). Cette
        # requete ne lisait que date_rdv/heure_rdv, systematiquement vides
        # pour les RDV crees via l'autre flux -> l'historique du medecin
        # semblait vide/casse. On prend la colonne renseignee, quelle
        # qu'elle soit.
        historique = db.execute_query("""
            SELECT
                r.id,
                TO_CHAR(COALESCE(r.date_rendez_vous, r.date_rdv), 'YYYY-MM-DD') as date_rdv,
                COALESCE(r.heure_rendez_vous, TO_CHAR(r.heure_rdv, 'HH24:MI')) as heure_rdv,
                COALESCE(r.motif, '') as motif,
                COALESCE(r.statut, 'programme') as statut,
                COALESCE(r.duree, 30) as duree,
                COALESCE(r.patient_nom, '') as patient_nom,
                COALESCE(r.patient_telephone, '') as patient_telephone,
                TO_CHAR(r.created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
            FROM rendez_vous r
            WHERE r.medecin_id = %s AND r.structure_id = %s
            ORDER BY COALESCE(r.date_rendez_vous, r.date_rdv) DESC,
                     COALESCE(r.heure_rendez_vous, TO_CHAR(r.heure_rdv, 'HH24:MI')) DESC
            LIMIT 50
        """, (id, structure_id))
        
        # Construire la liste - tout est deja en string
        historique_list = []
        for r in historique:
            if isinstance(r, dict):
                historique_list.append({
                    'id': r.get('id'),
                    'date_rdv': r.get('date_rdv'),
                    'heure_rdv': r.get('heure_rdv'),
                    'motif': r.get('motif', ''),
                    'statut': r.get('statut', 'programme'),
                    'duree': int(r.get('duree', 30) or 30),
                    'patient_nom': r.get('patient_nom', ''),
                    'patient_telephone': r.get('patient_telephone', ''),
                    'created_at': r.get('created_at')
                })
            else:
                historique_list.append({
                    'id': r[0] if len(r) > 0 else None,
                    'date_rdv': r[1] if len(r) > 1 else None,
                    'heure_rdv': r[2] if len(r) > 2 else None,
                    'motif': r[3] if len(r) > 3 else '',
                    'statut': r[4] if len(r) > 4 else 'programme',
                    'duree': int(r[5]) if len(r) > 5 and r[5] else 30,
                    'patient_nom': r[6] if len(r) > 6 else '',
                    'patient_telephone': r[7] if len(r) > 7 else '',
                    'created_at': r[8] if len(r) > 8 else None
                })
        
        # 4. Statistiques par mois (même fix que ci-dessus : COALESCE des
        # deux paires de colonnes date possibles)
        stats_mois = db.execute_query("""
            SELECT
                EXTRACT(YEAR FROM COALESCE(date_rendez_vous, date_rdv)) as annee,
                EXTRACT(MONTH FROM COALESCE(date_rendez_vous, date_rdv)) as mois,
                COUNT(*) as total
            FROM rendez_vous
            WHERE medecin_id = %s AND structure_id = %s AND statut = 'termine'
            GROUP BY annee, mois
            ORDER BY annee DESC, mois DESC
            LIMIT 12
        """, (id, structure_id))
        
        stats_mois_list = []
        for s in stats_mois:
            if isinstance(s, dict):
                stats_mois_list.append({
                    'annee': int(s.get('annee', 0) or 0),
                    'mois': int(s.get('mois', 0) or 0),
                    'total': int(s.get('total', 0) or 0)
                })
            else:
                stats_mois_list.append({
                    'annee': int(s[0]) if len(s) > 0 and s[0] else 0,
                    'mois': int(s[1]) if len(s) > 1 and s[1] else 0,
                    'total': int(s[2]) if len(s) > 2 and s[2] else 0
                })
        
        # Construire la reponse
        response_data = {
            'info': info,
            'stats': stats_data,
            'historique': historique_list,
            'stats_mois': stats_mois_list
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Erreur dans api_historique_medecin: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/medecins', methods=['GET'])
@login_required
def get_medecins():
    """Recupere la liste des medecins avec leurs statistiques"""
    structure_id = session.get('structure_id')
    
    # Recuperer les medecins depuis Neon
    medecins = db.execute_query("""
        SELECT id, nom, prenom, titre, specialite, qualification, 
               telephone, email, honoraire_consultation, actif
        FROM medecins 
        WHERE structure_id = %s 
        ORDER BY nom
    """, (structure_id,))
    
    result = []
    for m in medecins:
        if isinstance(m, dict):
            med_id = m.get('id')
            nom = m.get('nom')
            prenom = m.get('prenom')
            titre = m.get('titre', 'Dr')
            specialite = m.get('specialite')
            qualification = m.get('qualification')
            telephone = m.get('telephone')
            email = m.get('email')
            honoraire = m.get('honoraire_consultation', 0)
            actif = m.get('actif', True)
        else:
            med_id = m[0]
            nom = m[1]
            prenom = m[2]
            titre = m[3] if len(m) > 3 else 'Dr'
            specialite = m[4] if len(m) > 4 else ''
            qualification = m[5] if len(m) > 5 else ''
            telephone = m[6] if len(m) > 6 else ''
            email = m[7] if len(m) > 7 else ''
            honoraire = m[8] if len(m) > 8 else 0
            actif = m[9] if len(m) > 9 else True
        
        # ⭐ FIX (2 bugs corrigés ici) :
        # 1) `db.execute_query` retourne toujours des dicts (RealDictCursor) —
        #    faire `resultat[0][0]` levait `KeyError: 0` a chaque appel, ce
        #    qui faisait planter la liste ENTIERE des medecins (500) des
        #    qu'une structure avait au moins un medecin.
        # 2) COALESCE(date_rendez_vous, date_rdv) — la table a deux paires de
        #    colonnes date/heure selon le flux de creation du RDV ; se fier
        #    uniquement a date_rdv (souvent vide) faisait ressortir 0
        #    consultation partout meme une fois le crash corrige.
        def _scalar(rows, cle='total'):
            if not rows:
                return 0
            r0 = rows[0]
            if isinstance(r0, dict):
                return r0.get(cle) or next(iter(r0.values()), 0) or 0
            return r0[0] if len(r0) > 0 else 0

        # Compter les consultations terminees
        nb_total = db.execute_query("""
            SELECT COUNT(*) as total FROM rendez_vous
            WHERE medecin_id = %s AND statut = 'termine'
        """, (med_id,))
        nb_total = _scalar(nb_total)

        # Ce mois
        now = datetime.now()
        nb_mois = db.execute_query("""
            SELECT COUNT(*) as total FROM rendez_vous
            WHERE medecin_id = %s AND statut = 'termine'
            AND EXTRACT(YEAR FROM COALESCE(date_rendez_vous, date_rdv)) = %s
            AND EXTRACT(MONTH FROM COALESCE(date_rendez_vous, date_rdv)) = %s
        """, (med_id, now.year, now.month))
        nb_mois = _scalar(nb_mois)

        # Cette semaine
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        nb_semaine = db.execute_query("""
            SELECT COUNT(*) as total FROM rendez_vous
            WHERE medecin_id = %s AND statut = 'termine'
            AND COALESCE(date_rendez_vous, date_rdv) >= %s AND COALESCE(date_rendez_vous, date_rdv) <= %s
        """, (med_id, week_start, week_end))
        nb_semaine = _scalar(nb_semaine)

        # Derniere consultation
        dernier = db.execute_query("""
            SELECT COALESCE(date_rendez_vous, date_rdv) as derniere FROM rendez_vous
            WHERE medecin_id = %s AND statut = 'termine'
            ORDER BY COALESCE(date_rendez_vous, date_rdv) DESC, COALESCE(heure_rendez_vous, TO_CHAR(heure_rdv, 'HH24:MI')) DESC LIMIT 1
        """, (med_id,))
        derniere_val = _scalar(dernier, cle='derniere')
        derniere_date = derniere_val.isoformat() if derniere_val and hasattr(derniere_val, 'isoformat') else None
        
        result.append({
            'id': med_id,
            'nom': nom,
            'prenom': prenom,
            'titre': titre,
            'specialite': specialite,
            'qualification': qualification or specialite,
            'telephone': telephone,
            'email': email,
            'honoraire_consultation': float(honoraire) if honoraire else 0,
            'actif': actif,
            'nb_consultations': nb_total,
            'consultations_mois': nb_mois,
            'consultations_semaine': nb_semaine,
            'derniere_consultation': derniere_date
        })
    
    return jsonify(result)


@app.route('/api/medecins/<int:id>', methods=['GET'])
@login_required
def get_medecin_details(id):
    """Recupere les details d'un medecin"""
    structure_id = session.get('structure_id')
    
    # Une seule requete avec toutes les statistiques
    result = db.execute_query("""
        SELECT 
            m.id,
            m.nom,
            m.prenom,
            m.titre,
            m.specialite,
            m.qualification,
            m.telephone,
            m.email,
            m.honoraire_consultation,
            m.actif,
            COUNT(CASE WHEN r.statut = 'termine' THEN 1 END) as total_consultations,
            COUNT(CASE WHEN r.statut = 'termine'
                AND EXTRACT(YEAR FROM COALESCE(r.date_rendez_vous, r.date_rdv)) = EXTRACT(YEAR FROM CURRENT_DATE)
                AND EXTRACT(MONTH FROM COALESCE(r.date_rendez_vous, r.date_rdv)) = EXTRACT(MONTH FROM CURRENT_DATE)
                THEN 1 END) as consultations_mois,
            COUNT(CASE WHEN r.statut = 'termine'
                AND COALESCE(r.date_rendez_vous, r.date_rdv) >= date_trunc('week', CURRENT_DATE)
                AND COALESCE(r.date_rendez_vous, r.date_rdv) <= date_trunc('week', CURRENT_DATE) + interval '6 days'
                THEN 1 END) as consultations_semaine,
            MAX(CASE WHEN r.statut = 'termine' THEN COALESCE(r.date_rendez_vous, r.date_rdv) END) as derniere_consultation
        FROM medecins m
        LEFT JOIN rendez_vous r ON m.id = r.medecin_id
        WHERE m.id = %s AND m.structure_id = %s
        GROUP BY m.id, m.nom, m.prenom, m.titre, m.specialite, m.qualification,
                 m.telephone, m.email, m.honoraire_consultation, m.actif
    """, (id, structure_id))
    
    if not result or len(result) == 0:
        return jsonify({'error': 'Medecin non trouve'}), 404
    
    if isinstance(result[0], dict):
        r = result[0]
        return jsonify({
            'id': r.get('id'),
            'nom': r.get('nom'),
            'prenom': r.get('prenom'),
            'titre': r.get('titre', 'Dr'),
            'specialite': r.get('specialite'),
            'qualification': r.get('qualification') or r.get('specialite'),
            'telephone': r.get('telephone'),
            'email': r.get('email'),
            'honoraire_consultation': float(r.get('honoraire_consultation', 0)),
            'actif': r.get('actif', True),
            'total_consultations': int(r.get('total_consultations', 0)),
            'consultations_mois': int(r.get('consultations_mois', 0)),
            'consultations_semaine': int(r.get('consultations_semaine', 0)),
            'derniere_consultation': r.get('derniere_consultation').isoformat() 
                if r.get('derniere_consultation') and hasattr(r.get('derniere_consultation'), 'isoformat') 
                else None
        })
    else:
        r = result[0]
        return jsonify({
            'id': r[0],
            'nom': r[1],
            'prenom': r[2],
            'titre': r[3] if len(r) > 3 else 'Dr',
            'specialite': r[4] if len(r) > 4 else '',
            'qualification': r[5] if len(r) > 5 else (r[4] if len(r) > 4 else ''),
            'telephone': r[6] if len(r) > 6 else '',
            'email': r[7] if len(r) > 7 else '',
            'honoraire_consultation': float(r[8] if len(r) > 8 else 0),
            'actif': r[9] if len(r) > 9 else True,
            'total_consultations': int(r[10]) if len(r) > 10 and r[10] else 0,
            'consultations_mois': int(r[11]) if len(r) > 11 and r[11] else 0,
            'consultations_semaine': int(r[12]) if len(r) > 12 and r[12] else 0,
            'derniere_consultation': r[13].isoformat() if len(r) > 13 and r[13] and hasattr(r[13], 'isoformat') else None
        })

@app.route('/api/medecins/<int:id>/consultations', methods=['GET'])
@login_required
def get_medecin_consultations(id):
    """Recupere l'historique des consultations d'un medecin"""
    structure_id = session.get('structure_id')
    
    rendez_vous = db.execute_query("""
        SELECT r.id, COALESCE(r.date_rendez_vous, r.date_rdv) as date_rdv,
               COALESCE(r.heure_rendez_vous, TO_CHAR(r.heure_rdv, 'HH24:MI')) as heure_rdv,
               r.patient_nom, r.patient_telephone, r.motif, r.statut, r.duree
        FROM rendez_vous r
        WHERE r.medecin_id = %s AND r.structure_id = %s
        ORDER BY COALESCE(r.date_rendez_vous, r.date_rdv) DESC,
                 COALESCE(r.heure_rendez_vous, TO_CHAR(r.heure_rdv, 'HH24:MI')) DESC
    """, (id, structure_id))
    
    result = []
    for r in rendez_vous:
        if isinstance(r, dict):
            result.append({
                'id': r.get('id'),
                'date_rendez_vous': r.get('date_rdv').isoformat() if r.get('date_rdv') else None,
                'heure_rendez_vous': r.get('heure_rdv'),
                'patient_nom': r.get('patient_nom'),
                'patient_telephone': r.get('patient_telephone'),
                'motif': r.get('motif'),
                'statut': r.get('statut'),
                'duree': r.get('duree', 30)
            })
        else:
            result.append({
                'id': r[0],
                'date_rendez_vous': r[1].isoformat() if r[1] else None,
                'heure_rendez_vous': r[2],
                'patient_nom': r[3],
                'patient_telephone': r[4],
                'motif': r[5],
                'statut': r[6],
                'duree': r[7] if len(r) > 7 else 30
            })
    
    return jsonify(result)


@app.route('/api/medecins/<int:id>/disponibilites', methods=['GET'])
@login_required
def get_medecin_disponibilites(id):
    """Verifie la disponibilite d'un medecin"""
    structure_id = session.get('structure_id')
    date_str = request.args.get('date')
    
    if not date_str:
        return jsonify({'error': 'Date requise'}), 400
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Format de date invalide'}), 400
    
    # Verifier si le medecin est actif
    medecin = db.execute_query("""
        SELECT actif FROM medecins 
        WHERE id = %s AND structure_id = %s
    """, (id, structure_id))
    
    if not medecin or len(medecin) == 0:
        return jsonify({'error': 'Medecin non trouve'}), 404
    
    actif = medecin[0][0] if medecin[0] else True
    if not actif:
        return jsonify({'disponible': False, 'motif': 'Medecin inactif'})
    
    # Verifier les rendez-vous existants pour cette date
    rdvs = db.execute_query("""
        SELECT COUNT(*) FROM rendez_vous 
        WHERE medecin_id = %s AND date_rdv = %s 
        AND statut IN ('programme', 'confirme')
    """, (id, date_obj))
    nb_rdvs = rdvs[0][0] if rdvs else 0
    
    # 16 creneaux max (8h-17h avec 30 min)
    if nb_rdvs >= 16:
        return jsonify({'disponible': False, 'motif': 'Complet pour ce jour'})
    
    # Generer les creneaux disponibles
    creneaux = []
    for h in range(8, 17):
        for m in [0, 30]:
            heure_str = f"{h:02d}:{m:02d}"
            existe = db.execute_query("""
                SELECT COUNT(*) FROM rendez_vous 
                WHERE medecin_id = %s AND date_rdv = %s 
                AND heure_rdv = %s AND statut IN ('programme', 'confirme')
            """, (id, date_obj, heure_str))
            existe = existe[0][0] if existe else 0
            
            if existe == 0:
                creneaux.append({'heure': heure_str})
    
    return jsonify({
        'disponible': len(creneaux) > 0,
        'creneaux': creneaux[:10]
    })
@app.route('/api/motifs', methods=['GET'])
@login_required
def get_motifs():
    """Recupere la liste des motifs de rendez-vous"""
    structure_id = session.get('structure_id')
    
    motifs = db.execute_query("""
        SELECT id, nom, description, ordre
        FROM motifs_rendez_vous
        WHERE structure_id = %s AND actif = TRUE
        ORDER BY ordre, nom
    """, (structure_id,))
    
    motifs_list = []
    for m in motifs:
        if isinstance(m, dict):
            motifs_list.append({
                'id': m.get('id'),
                'nom': m.get('nom'),
                'description': m.get('description')
            })
        else:
            motifs_list.append({
                'id': m[0],
                'nom': m[1],
                'description': m[2] if len(m) > 2 else ''
            })
    
    # Ajouter l'option "Autre"
    motifs_list.append({
        'id': -1,
        'nom': 'Autre',
        'description': 'Saisir un motif personnalise'
    })
    
    return jsonify(motifs_list)
# ============================================================
# ROUTE RENDEZ_VOUS AVEC FILTRES PAR INTERVALLE
# ============================================================

@app.route('/rendez_vous')
@login_required
def rendez_vous():
    """Page de gestion des rendez-vous"""
    structure_id = session.get('structure_id')
    
    # Récupérer les paramètres de filtrage
    periode = request.args.get('periode', 'tous')
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    statut = request.args.get('statut', 'tous')
    medecin_id = request.args.get('medecin_id', type=int)
    
    today = date.today()
    date_debut = None
    date_fin = None
    
    # Définir les dates selon la période
    if periode == 'tous':
        date_debut = None
        date_fin = None
    elif periode == 'aujourdhui':
        date_debut = today
        date_fin = today
    elif periode == 'semaine':
        jour_semaine = today.weekday()
        date_debut = today - timedelta(days=jour_semaine)
        date_fin = date_debut + timedelta(days=6)
    elif periode == 'mois':
        date_debut = date(today.year, today.month, 1)
        if today.month == 12:
            date_fin = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            date_fin = date(today.year, today.month + 1, 1) - timedelta(days=1)
    elif periode == 'personnalise' and date_debut_str and date_fin_str:
        try:
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
        except ValueError:
            date_debut = today
            date_fin = today
    
    # Récupérer les rendez-vous
    rendez_vous, total = RendezVousService.get_rendez_vous_liste(
        structure_id=structure_id,
        date_debut=date_debut,
        date_fin=date_fin,
        statut=statut if statut != 'tous' else None,
        medecin_id=medecin_id
    )
    
    # Récupérer les médecins et patients
    medecins = Medecin.query.filter_by(structure_id=structure_id, actif=True).all()
    patients = Patient.query.filter_by(structure_id=structure_id).order_by(Patient.nom).all()
    
    return render_template(
        'rendez_vous.html',
        rendez_vous=rendez_vous,
        medecins=medecins,
        patients=patients,
        periode=periode,
        date_debut=date_debut_str,
        date_fin=date_fin_str,
        statut=statut,
        medecin_id=medecin_id,
        total=total,
        today=today.isoformat()
    )


# ============================================================
# API RENDEZ-VOUS
# ============================================================

@app.route('/rendez_vous/api/creer', methods=['POST'])
@login_required
def api_creer_rendez_vous():
    """API: Créer un nouveau rendez-vous"""
    structure_id = session.get('structure_id')
    data = request.json
    
    if not data:
        return jsonify({'success': False, 'error': 'Données manquantes'}), 400
    
    succes, resultat = RendezVousService.creer_rendez_vous(
        data=data,
        structure_id=structure_id,
        utilisateur_nom=session.get('user_nom', 'Systeme')
    )
    
    if succes:
        return jsonify({
            'success': True,
            'data': resultat,
            'message': 'Rendez-vous créé avec succès'
        })
    else:
        return jsonify({
            'success': False,
            'error': resultat.get('error', 'Erreur lors de la création')
        }), 400


@app.route('/api/rendez-vous/creer-externe', methods=['POST'])
def api_creer_rendez_vous_externe():
    """
    API token (comme /api/prescriptions) : reçoit une demande de RDV poussée
    depuis gestion_patients (consultation avec suivi programmé), sans passer
    par une saisie manuelle à l'accueil.

    Contrairement à /rendez_vous/api/creer (session-based), le patient et le
    médecin ne sont pas des ID GHP connus côté appelant — on les retrouve par
    nom, comme pour la réception des prescriptions (/api/prescriptions).
    """
    token = request.args.get('token')
    if not token:
        return jsonify({'success': False, 'error': 'Token manquant'}), 401

    mapping = StructureMapping.query.filter_by(api_key=token, actif=True).first()
    if not mapping:
        return jsonify({'success': False, 'error': 'Token invalide'}), 401

    data = request.json or {}
    structure_id = mapping.local_structure_id

    patient_nom = (data.get('patient_nom') or '').strip()
    patient_prenom = (data.get('patient_prenom') or '').strip()
    medecin_nom = (data.get('medecin_nom') or '').strip()
    date_str = data.get('date')
    heure = data.get('heure') or '08:00'
    motif = (data.get('motif') or 'Suivi programmé').strip()
    notes = data.get('notes') or ''
    source_id = data.get('source_id')

    if not patient_nom or not date_str:
        return jsonify({'success': False, 'error': 'patient_nom et date sont obligatoires'}), 400

    # ⭐ Dédoublonnage : si ce même suivi (source_id) a déjà été poussé, on ne
    # recrée pas un doublon (une consultation peut être resauvegardée
    # plusieurs fois avec la même date de suivi).
    marqueur = f"[gestion_patients:consultation:{source_id}]"
    if source_id and RendezVous.query.filter(
        RendezVous.structure_id == structure_id,
        RendezVous.notes.like(f"%{marqueur}%")
    ).first():
        return jsonify({'success': True, 'message': 'Déjà poussé précédemment', 'deja_existant': True})

    patient = Patient.query.filter(
        Patient.structure_id == structure_id,
        db.func.lower(Patient.nom) == patient_nom.lower(),
        db.func.lower(Patient.prenom) == patient_prenom.lower()
    ).first()
    if not patient:
        return jsonify({'success': False, 'error': 'patient_introuvable'}), 404

    def _tokens_nom(s):
        # ⭐ Certaines structures saisissent "Dr" DANS le champ nom lui-même
        # (ex. Medecin.nom = "Dr GASTON") plutôt que dans le champ titre
        # dédié — une comparaison par sous-chaîne littérale échoue alors
        # ("dr gaston" n'est ni un sous-mot de "gaston koffi" ni l'inverse).
        # On compare par ensembles de mots (hors titres), plus robuste.
        titres = {'dr', 'pr', 'docteur', 'professeur'}
        return {
            mot.strip('.').lower()
            for mot in (s or '').split()
            if mot.strip('.').lower() not in titres and mot.strip('.')
        }

    medecin = None
    if medecin_nom:
        medecin_tokens = _tokens_nom(medecin_nom)
        for m in Medecin.query.filter_by(structure_id=structure_id, actif=True).all():
            m_tokens = _tokens_nom(m.nom) | _tokens_nom(m.prenom)
            if medecin_tokens & m_tokens:
                medecin = m
                break

    if not medecin:
        return jsonify({
            'success': False,
            'error': 'medecin_introuvable',
            'message': f"Médecin \"{medecin_nom}\" non retrouvé dans le catalogue GHP de cette structure — le rendez-vous n'a pas pu être créé automatiquement, à programmer manuellement."
        }), 404

    succes, resultat = RendezVousService.creer_rendez_vous(
        data={
            'patient_id': patient.id,
            'medecin_id': medecin.id,
            'date': date_str,
            'heure': heure,
            'motif': motif,
            'notes': f"{notes}\n{marqueur}".strip() if notes else marqueur
        },
        structure_id=structure_id,
        utilisateur_nom='gestion_patients (auto)'
    )

    if succes:
        return jsonify({'success': True, 'data': resultat})
    return jsonify({'success': False, 'error': resultat.get('error', 'Erreur lors de la création')}), 400


@app.route('/rendez_vous/api/<int:rdv_id>/confirmer', methods=['POST'])
@login_required
def api_confirmer_rendez_vous(rdv_id):
    """API: Confirmer un rendez-vous"""
    structure_id = session.get('structure_id')
    
    succes, resultat = RendezVousService.confirmer_rendez_vous(
        rdv_id=rdv_id,
        structure_id=structure_id,
        utilisateur_nom=session.get('user_nom', 'Systeme')
    )

    if succes:
        return jsonify({
            'success': True,
            'data': resultat,
            'message': 'Rendez-vous confirmé avec succès'
        })
    else:
        return jsonify({
            'success': False,
            'error': resultat.get('error', 'Erreur lors de la confirmation')
        }), 400


@app.route('/rendez_vous/api/<int:rdv_id>/print', methods=['GET'])
@login_required
def api_print_rendez_vous(rdv_id):
    """API: Générer le HTML d'impression d'un rendez-vous"""
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'error': 'Structure non trouvée'}), 404
    
    rdv = RendezVousService.get_rendez_vous_par_id(rdv_id, structure_id)
    if not rdv:
        return jsonify({'success': False, 'error': 'Rendez-vous non trouvé'}), 404
    
    # Récupérer le patient et le médecin
    patient = db.session.get(Patient, rdv.patient_id)
    medecin = db.session.get(Medecin, rdv.medecin_id)
    
    # ============================================================
    # RÉCUPÉRER LA STRUCTURE DEPUIS GOOGLE SHEETS
    # ============================================================
    
    structure = None
    
    try:
        # Récupérer toutes les structures depuis Google Sheets
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        
        for s in structures:
            # Comparer les IDs
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
                break
    except Exception as e:
        print(f"Erreur récupération structure depuis Sheets: {e}")
    
    # Si la structure n'est pas trouvée, utiliser les valeurs par défaut
    if not structure:
        structure = {
            'nom': 'Hopital',
            'adresse': '',
            'telephone': '',
            'email': '',
            'logo_url': ''
        }
    
    return render_template(
        'print_rendez_vous.html',
        rdv=rdv,
        structure=structure,
        patient=patient,
        medecin=medecin,
        now=datetime.now()
    )

@app.route('/api/patients/liste', methods=['GET'])
@login_required
def api_liste_patients():
    """API: Liste des patients pour la recherche"""
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

@app.route('/rendez_vous/api/<int:rdv_id>/terminer', methods=['POST'])
@login_required
def api_terminer_rendez_vous(rdv_id):
    """API: Terminer un rendez-vous"""
    structure_id = session.get('structure_id')
    
    succes, resultat = RendezVousService.terminer_rendez_vous(
        rdv_id=rdv_id,
        structure_id=structure_id,
        utilisateur_nom=session.get('user_nom', 'Systeme')
    )
    
    if succes:
        return jsonify({
            'success': True,
            'data': resultat,
            'message': 'Rendez-vous terminé avec succès'
        })
    else:
        return jsonify({
            'success': False,
            'error': resultat.get('error', 'Erreur lors de la terminaison')
        }), 400


@app.route('/rendez_vous/api/<int:rdv_id>/annuler', methods=['POST'])
@login_required
def api_annuler_rendez_vous(rdv_id):
    """API: Annuler un rendez-vous"""
    structure_id = session.get('structure_id')
    data = request.json or {}
    
    succes, resultat = RendezVousService.annuler_rendez_vous(
        rdv_id=rdv_id,
        structure_id=structure_id,
        utilisateur_nom=session.get('user_nom', 'Systeme'),
        motif=data.get('motif')
    )
    
    if succes:
        return jsonify({
            'success': True,
            'data': resultat,
            'message': 'Rendez-vous annulé avec succès'
        })
    else:
        return jsonify({
            'success': False,
            'error': resultat.get('error', 'Erreur lors de l\'annulation')
        }), 400


@app.route('/rendez_vous/api/reporter', methods=['POST'])
@login_required
def api_reporter_rendez_vous():
    """API: Reporter un rendez-vous"""
    structure_id = session.get('structure_id')
    data = request.json
    
    if not data:
        return jsonify({'success': False, 'error': 'Données manquantes'}), 400
    
    rdv_id = data.get('rdv_id')
    nouvelle_date = data.get('nouvelle_date')
    nouvelle_heure = data.get('nouvelle_heure')
    message = data.get('message')
    
    if not rdv_id or not nouvelle_date or not nouvelle_heure:
        return jsonify({
            'success': False,
            'error': 'rdv_id, nouvelle_date et nouvelle_heure sont obligatoires'
        }), 400
    
    succes, resultat = RendezVousService.reporter_rendez_vous(
        rdv_id=rdv_id,
        structure_id=structure_id,
        nouvelle_date=nouvelle_date,
        nouvelle_heure=nouvelle_heure,
        utilisateur_nom=session.get('user_nom', 'Systeme'),
        message=message
    )
    
    if succes:
        whatsapp_url = None
        if data.get('envoyer_rappel', False):
            # Récupérer les infos du patient
            rdv = RendezVous.query.get(rdv_id)
            if rdv:
                patient = Patient.query.get(rdv.patient_id)
                if patient and patient.telephone:
                    from datetime import datetime
                    import urllib.parse
                    
                    # Récupérer la structure depuis Google Sheets
                    structure = None
                    try:
                        structures = sheets_helper.get_all_records('structures', use_prefix=False)
                        for s in structures:
                            if str(s.get('ID')) == str(structure_id):
                                structure = {
                                    'nom': s.get('nom') or 'Notre établissement',
                                    'adresse': s.get('adresse') or '',
                                    'telephone': s.get('telephone') or '',
                                    'email': s.get('email') or ''
                                }
                                break
                    except Exception as e:
                        print(f"Erreur récupération structure: {e}")
                    
                    if not structure:
                        structure = {
                            'nom': 'Notre établissement',
                            'adresse': '',
                            'telephone': '',
                            'email': ''
                        }
                    
                    # Formater la date en français
                    jours = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']
                    mois = ['Janvier', 'Fevrier', 'Mars', 'Avril', 'Mai', 'Juin',
                            'Juillet', 'Aout', 'Septembre', 'Octobre', 'Novembre', 'Decembre']
                    
                    date_parts = nouvelle_date.split('-')
                    date_obj = datetime(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                    date_formatee = jours[date_obj.weekday()] + ' ' + date_parts[2] + ' ' + mois[date_obj.month - 1] + ' ' + date_parts[0]
                    
                    # Construction du message avec les infos de la structure
                    msg = f"REPORT DE RENDEZ-VOUS%0A%0A"
                    msg += f"{structure['nom'].upper()}%0A"
                    if structure['adresse']:
                        msg += f"Adresse: {structure['adresse']}%0A"
                    if structure['telephone']:
                        msg += f"Tel: {structure['telephone']}%0A"
                    if structure['email']:
                        msg += f"Email: {structure['email']}%0A"
                    msg += f"%0A"
                    msg += f"Cher(e) {rdv.patient_nom},%0A%0A"
                    msg += f"Votre rendez-vous a été reporté au :%0A"
                    msg += f"Date : {date_formatee}%0A"
                    msg += f"Heure : {nouvelle_heure}%0A%0A"
                    
                    if message and message.strip():
                        msg += f"Message: {message}%0A%0A"
                    
                    msg += f"Nous vous attendons. Merci de votre compréhension."
                    
                    # Nettoyer le téléphone
                    tel = str(patient.telephone).replace(' ', '').replace('-', '').replace('+', '')
                    if not tel.startswith('228') and not tel.startswith('229') and not tel.startswith('221'):
                        tel = '228' + tel
                    
                    whatsapp_url = f"https://wa.me/{tel}?text={msg}"
        
        return jsonify({
            'success': True,
            'data': resultat,
            'whatsapp_url': whatsapp_url,
            'message': 'Rendez-vous reporté avec succès'
        })
    else:
        return jsonify({
            'success': False,
            'error': resultat.get('error', 'Erreur lors du report')
        }), 400

@app.route('/rendez_vous/api/check-conflit', methods=['GET'])
@login_required
def api_check_conflit():
    """API: Vérifier les conflits de créneau"""
    medecin_id = request.args.get('medecin_id', type=int)
    date_str = request.args.get('date')
    heure = request.args.get('heure')
    duree = request.args.get('duree', 30, type=int)
    
    if not medecin_id or not date_str or not heure:
        return jsonify({
            'success': False,
            'error': 'medecin_id, date et heure sont obligatoires'
        }), 400
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': 'Format de date invalide'}), 400
    
    try:
        conflit = RendezVousService.verifier_conflit(
            medecin_id=medecin_id,
            date=date_obj,
            heure=heure,
            duree=duree
        )
        return jsonify({
            'success': True,
            'disponible': conflit is None,
            'conflit': conflit.to_dict() if conflit else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/rendez_vous/api/disponibilites/<int:medecin_id>', methods=['GET'])
@login_required
def api_disponibilites_medecin(medecin_id):
    """API: Récupérer les disponibilités d'un médecin"""
    date_str = request.args.get('date')
    
    if not date_str:
        return jsonify({'success': False, 'error': 'Date obligatoire'}), 400
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': 'Format de date invalide'}), 400
    
    disponibilite = RendezVousService.verifier_disponibilite_medecin(
        medecin_id=medecin_id,
        date=date_obj
    )
    
    return jsonify({
        'success': True,
        'data': disponibilite
    })


@app.route('/rendez_vous/api/stats', methods=['GET'])
@login_required
def api_stats():
    """API: Statistiques des rendez-vous"""
    structure_id = session.get('structure_id')
    
    stats = RendezVousService.get_statistiques(structure_id=structure_id)
    
    return jsonify({
        'success': True,
        'data': stats
    })


@app.route('/rendez_vous/api/<int:rdv_id>/rappel', methods=['POST'])
@login_required
def api_envoyer_rappel(rdv_id):
    """API: Envoyer un rappel pour un rendez-vous"""
    structure_id = session.get('structure_id')
    
    rdv = RendezVousService.get_rendez_vous_par_id(rdv_id, structure_id)
    if not rdv:
        return jsonify({'success': False, 'error': 'Rendez-vous non trouvé'}), 404
    
    # Récupérer les infos de la structure depuis Google Sheets
    structure = None
    try:
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        for s in structures:
            if str(s.get('ID')) == str(structure_id):
                structure = {
                    'nom': s.get('nom') or 'Hopital',
                    'adresse': s.get('adresse') or '',
                    'telephone': s.get('telephone') or '',
                    'email': s.get('email') or ''
                }
                break
    except Exception as e:
        print(f"Erreur récupération structure: {e}")
    
    if not structure:
        structure = {
            'nom': 'Hopital',
            'adresse': '',
            'telephone': '',
            'email': ''
        }
    
    # Appeler le service avec les infos de la structure
    succes, resultat = RappelsService.envoyer_rappel_manuel(
        rdv_id=rdv_id,
        structure_info=structure  # Ajout des infos de la structure
    )
    
    if succes:
        return jsonify({
            'success': True,
            'data': resultat,
            'message': 'Rappel envoyé avec succès'
        })
    else:
        return jsonify({
            'success': False,-
            'error': resultat.get('error', 'Erreur lors de l\'envoi du rappel')
        }), 400


@app.route('/rendez_vous/api/rappels/stats', methods=['GET'])
@login_required
def api_stats_rappels():
    """API: Statistiques des rappels"""
    structure_id = session.get('structure_id')
    
    stats = RappelsService.get_stats_rappels(structure_id)
    
    return jsonify({
        'success': True,
        'data': stats
    })

# ============================================================
# ROUTE POUR IMPRIMER LE CALENDRIER
# ============================================================

@app.route('/rendez_vous/print')
@login_required
def print_rendez_vous():
    """Page d'impression du calendrier"""
    structure_id = session.get('structure_id')
    
    periode = request.args.get('periode', 'aujourdhui')
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    
    today = date.today()
    
    # Définir les dates selon la période
    if periode == 'tous':
        date_debut = None
        date_fin = None
        libelle_periode = 'Tous les rendez-vous'
    elif periode == 'aujourdhui':
        date_debut = today
        date_fin = today
        libelle_periode = "Aujourd'hui"
    elif periode == 'semaine':
        jour_semaine = today.weekday()
        date_debut = today - timedelta(days=jour_semaine)
        date_fin = date_debut + timedelta(days=6)
        libelle_periode = "Cette semaine"
    elif periode == 'mois':
        date_debut = date(today.year, today.month, 1)
        if today.month == 12:
            date_fin = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            date_fin = date(today.year, today.month + 1, 1) - timedelta(days=1)
        libelle_periode = "Ce mois"
    elif periode == 'personnalise' and date_debut_str and date_fin_str:
        try:
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
            libelle_periode = f"Du {date_debut_str} au {date_fin_str}"
        except ValueError:
            date_debut = today
            date_fin = today
            libelle_periode = "Période personnalisée"
    else:
        date_debut = today
        date_fin = today
        libelle_periode = "Aujourd'hui"
    
    # Récupérer les rendez-vous
    rendez_vous, _ = RendezVousService.get_rendez_vous_liste(
        structure_id=structure_id,
        date_debut=date_debut,
        date_fin=date_fin
    )
    
    # Organiser par jour
    rdv_par_jour = {}
    for rdv in rendez_vous:
        date_str = rdv.date_rendez_vous.isoformat()
        if date_str not in rdv_par_jour:
            rdv_par_jour[date_str] = []
        rdv_par_jour[date_str].append(rdv)
    
    # Générer la liste des jours
    jours_liste = []
    if date_debut and date_fin:
        current = date_debut
        while current <= date_fin:
            jours_liste.append(current)
            current += timedelta(days=1)
    
    # Statistiques
    stats = {
        'total': sum(len(v) for v in rdv_par_jour.values()),
        'jours_avec_rdv': len([j for j in rdv_par_jour.values() if j]),
        'jours_total': len(jours_liste)
    }
    
    # ============================================================
    # RÉCUPÉRER LA STRUCTURE DEPUIS GOOGLE SHEETS
    # ============================================================
    
    structure = None
    
    try:
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        for s in structures:
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
                break
    except Exception as e:
        print(f"Erreur récupération structure: {e}")
    
    # Fallback: si la structure n'est pas trouvée
    if not structure:
        structure = {
            'nom': 'Hopital',
            'adresse': '',
            'telephone': '',
            'email': '',
            'logo_url': ''
        }
    
    return render_template(
        'print_calendrier.html',
        rdv_par_jour=rdv_par_jour,
        jours_liste=jours_liste,
        libelle_periode=libelle_periode,
        structure=structure,
        stats=stats,
        today=today,
        now=datetime.now()
    )

@app.route('/api/rendez_vous', methods=['POST'])
@login_required
def api_add_rendez_vous():
    """Ajouter un rendez-vous avec medecin"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvee'}), 400
        
        # Verifier que le medecin existe
        if data.get('medecin_id'):
            medecin = db.execute_query("""
                SELECT id FROM medecins 
                WHERE id = %s AND structure_id = %s
            """, (data.get('medecin_id'), structure_id))
            if not medecin or len(medecin) == 0:
                return jsonify({'success': False, 'error': 'Medecin non trouve'}), 404
        
        # Verifier les doublons
        existant = db.execute_query("""
            SELECT id FROM rendez_vous 
            WHERE medecin_id = %s 
            AND date_rdv = %s 
            AND heure_rdv = %s 
            AND statut IN ('programme', 'confirme')
        """, (data.get('medecin_id'), data.get('date'), data.get('heure')))
        
        if existant and len(existant) > 0:
            return jsonify({'success': False, 'error': 'Creneau deja occupe'}), 400
        
        # Insérer le rendez-vous
        result = db.execute_query("""
            INSERT INTO rendez_vous (
                patient_id, 
                structure_id, 
                medecin_id,
                date_rdv, 
                heure_rdv, 
                motif, 
                statut,
                patient_nom,
                patient_telephone,
                duree
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data.get('patient_id'),
            structure_id,
            data.get('medecin_id'),
            data.get('date'),
            data.get('heure'),
            data.get('motif', 'Consultation'),
            'programme',
            data.get('patient_nom'),
            data.get('patient_telephone'),
            data.get('duree', 30)
        ))
        
        if result and len(result) > 0:
            rdv_id = result[0]['id'] if isinstance(result[0], dict) else result[0][0]
            return jsonify({'success': True, 'id': rdv_id})
        else:
            return jsonify({'success': False, 'error': 'Erreur insertion'}), 500
            
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500




@app.route('/api/structure/nom', methods=['GET'])
@login_required
def get_structure_nom():
    """Recupere le nom de la structure"""
    structure_id = session.get('structure_id')
    
    try:
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        for s in structures:
            if str(s.get('ID')) == str(structure_id):
                nom = s.get('nom') or 'Notre etablissement'
                return jsonify({'nom': nom})
    except Exception as e:
        print(f"Erreur récupération structure: {e}")
    
    return jsonify({'nom': 'Notre etablissement'})


@app.route('/mes_rendez_vous')
@login_required
def mes_rendez_vous():
    """Page patient pour voir ses rendez-vous"""
    structure_id = session.get('structure_id')
    patient_id = session.get('patient_id')  # Si patient connecté
    
    if not patient_id:
        flash('Veuillez vous connecter en tant que patient', 'warning')
        return redirect(url_for('index'))
    
    # ============================================================
    # RÉCUPÉRER LES INFORMATIONS DU PATIENT
    # ============================================================
    
    # Essayer depuis PostgreSQL d'abord
    patient = Patient.query.filter_by(id=patient_id, structure_id=structure_id).first()
    
    if not patient:
        # Fallback: depuis Google Sheets
        try:
            patients = sheets_helper.get_all_records('patients')
            patient_info = next((p for p in patients if str(p.get('ID')) == str(patient_id)), {})
        except Exception as e:
            print(f"Erreur récupération patient: {e}")
            patient_info = {}
    else:
        patient_info = {
            'ID': patient.id,
            'nom': patient.nom,
            'prenom': patient.prenom,
            'telephone': patient.telephone,
            'email': patient.email
        }
    
    # ============================================================
    # RÉCUPÉRER LES RENDEZ-VOUS DU PATIENT
    # ============================================================
    
    # Essayer depuis PostgreSQL d'abord
    rendez_vous = RendezVous.query.filter_by(
        patient_id=patient_id,
        structure_id=structure_id
    ).order_by(RendezVous.date_rendez_vous.desc()).all()
    
    mes_rendez_vous = []
    for rdv in rendez_vous:
        # Récupérer le nom du médecin
        medecin_nom = ''
        if rdv.medecin_id:
            medecin = Medecin.query.get(rdv.medecin_id)
            if medecin:
                medecin_nom = f"{medecin.titre} {medecin.nom}"
        
        mes_rendez_vous.append({
            'id': rdv.id,
            'date_rendez_vous': rdv.date_rendez_vous.strftime('%d/%m/%Y') if rdv.date_rendez_vous else '',
            'heure_rendez_vous': rdv.heure_rendez_vous,
            'motif': rdv.motif,
            'statut': rdv.statut,
            'medecin_nom': medecin_nom,
            'notes': rdv.notes or ''
        })
    
    # Si aucun rendez-vous en PostgreSQL, essayer Google Sheets
    if not mes_rendez_vous:
        try:
            rendez_vous_sheets = sheets_helper.get_all_records('rendez_vous')
            for r in rendez_vous_sheets:
                if str(r.get('patient_id')) == str(patient_id) and str(r.get('structure_id')) == str(structure_id):
                    mes_rendez_vous.append({
                        'id': r.get('ID'),
                        'date_rendez_vous': r.get('date_rendez_vous', ''),
                        'heure_rendez_vous': r.get('heure_rendez_vous', ''),
                        'motif': r.get('motif', ''),
                        'statut': r.get('statut', 'programme'),
                        'medecin_nom': r.get('medecin_nom', ''),
                        'notes': r.get('notes', '')
                    })
            mes_rendez_vous.sort(key=lambda x: x.get('date_rendez_vous', ''), reverse=True)
        except Exception as e:
            print(f"Erreur récupération rendez-vous Sheets: {e}")
    
    return render_template(
        'mes_rendez_vous.html',
        patient_info=patient_info,
        mes_rendez_vous=mes_rendez_vous,
        today=datetime.now().strftime('%Y-%m-%d')
    )


@app.route('/patient/rendez_vous/<int:patient_id>/<token>')
def patient_rendez_vous(patient_id, token):
    """Page patient pour CONSULTER ses rendez-vous (lecture seule)"""
    from datetime import datetime
    
    try:
        # ============================================================
        # RÉCUPÉRER LES INFOS DU PATIENT
        # ============================================================
        
        # Essayer depuis PostgreSQL avec SQLAlchemy d'abord
        patient = Patient.query.get(patient_id)
        
        if patient:
            patient_info = {
                'id': patient.id,
                'nom': patient.nom,
                'prenom': patient.prenom,
                'telephone': patient.telephone,
                'structure_id': patient.structure_id
            }
            structure_id = patient.structure_id
        else:
            # Fallback: requête directe
            result = db.execute_query("""
                SELECT id, nom, prenom, telephone, structure_id
                FROM patients 
                WHERE id = %s
            """, (patient_id,))
            
            if not result or len(result) == 0:
                return "Patient non trouvé", 404
            
            row = result[0]
            if isinstance(row, dict):
                patient_info = row
                structure_id = row.get('structure_id')
            else:
                patient_info = {
                    'id': row[0],
                    'nom': row[1],
                    'prenom': row[2],
                    'telephone': row[3],
                    'structure_id': row[4] if len(row) > 4 else None
                }
                structure_id = row[4] if len(row) > 4 else None
        
        # ============================================================
        # RÉCUPÉRER LA STRUCTURE DEPUIS GOOGLE SHEETS
        # ============================================================
        
        structure_nom = 'Notre établissement'
        structure_telephone = ''
        structure_adresse = ''
        
        try:
            structures = sheets_helper.get_all_records('structures', use_prefix=False)
            for s in structures:
                if str(s.get('ID')) == str(structure_id):
                    structure_nom = s.get('nom') or 'Notre établissement'
                    structure_telephone = s.get('telephone') or ''
                    structure_adresse = s.get('adresse') or ''
                    break
        except Exception as e:
            print(f"Erreur récupération structure: {e}")
        
        # ============================================================
        # RÉCUPÉRER LES RENDEZ-VOUS DU PATIENT
        # ============================================================
        
        mes_rendez_vous = []
        
        # Essayer avec SQLAlchemy d'abord
        rendez_vous = RendezVous.query.filter_by(patient_id=patient_id).order_by(
            RendezVous.date_rendez_vous.desc()
        ).all()
        
        if rendez_vous:
            for rdv in rendez_vous:
                # Récupérer le nom du médecin
                medecin_nom = ''
                if rdv.medecin_id:
                    medecin = Medecin.query.get(rdv.medecin_id)
                    if medecin:
                        medecin_nom = f"{medecin.titre} {medecin.nom}"
                
                mes_rendez_vous.append({
                    'id': rdv.id,
                    'date_rendez_vous': rdv.date_rendez_vous.strftime('%d/%m/%Y') if rdv.date_rendez_vous else '',
                    'heure_rendez_vous': rdv.heure_rendez_vous,
                    'motif': rdv.motif,
                    'statut': rdv.statut,
                    'medecin_nom': medecin_nom,
                    'notes': rdv.notes or ''
                })
        else:
            # Fallback: requête directe
            result = db.execute_query("""
                SELECT id, date_rdv, heure_rdv, motif, statut, notes, medecin_id
                FROM rendez_vous
                WHERE patient_id = %s
                ORDER BY date_rdv DESC
            """, (patient_id,))
            
            for r in result:
                if isinstance(r, dict):
                    medecin_nom = ''
                    if r.get('medecin_id'):
                        med = db.execute_query("SELECT nom, titre FROM medecins WHERE id = %s", (r.get('medecin_id'),))
                        if med and len(med) > 0:
                            m = med[0]
                            if isinstance(m, dict):
                                medecin_nom = f"{m.get('titre', 'Dr')} {m.get('nom', '')}"
                            else:
                                medecin_nom = f"{m[1] if len(m) > 1 else 'Dr'} {m[0] if len(m) > 0 else ''}"
                    
                    mes_rendez_vous.append({
                        'id': r.get('id'),
                        'date_rendez_vous': r.get('date_rdv'),
                        'heure_rendez_vous': r.get('heure_rdv'),
                        'motif': r.get('motif'),
                        'statut': r.get('statut', 'programme'),
                        'medecin_nom': medecin_nom,
                        'notes': r.get('notes', '')
                    })
                else:
                    medecin_nom = ''
                    if len(r) > 6 and r[6]:
                        med = db.execute_query("SELECT nom, titre FROM medecins WHERE id = %s", (r[6],))
                        if med and len(med) > 0:
                            m = med[0]
                            if isinstance(m, dict):
                                medecin_nom = f"{m.get('titre', 'Dr')} {m.get('nom', '')}"
                            else:
                                medecin_nom = f"{m[1] if len(m) > 1 else 'Dr'} {m[0] if len(m) > 0 else ''}"
                    
                    mes_rendez_vous.append({
                        'id': r[0],
                        'date_rendez_vous': r[1] if len(r) > 1 else '',
                        'heure_rendez_vous': r[2] if len(r) > 2 else '',
                        'motif': r[3] if len(r) > 3 else '',
                        'statut': r[4] if len(r) > 4 else 'programme',
                        'medecin_nom': medecin_nom,
                        'notes': r[5] if len(r) > 5 else ''
                    })
        
        return render_template('patient_rendez_vous.html',
                             patient=patient_info,
                             rendez_vous=mes_rendez_vous,
                             structure_nom=structure_nom,
                             structure_telephone=structure_telephone,
                             structure_adresse=structure_adresse)
                             
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return f"Erreur: {e}", 500

@app.route('/api/structure/nom')
@login_required
def api_structure_nom():
    """Retourne le nom de la structure"""
    structure_id = session.get('structure_id')
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if s.get('ID') == structure_id), {})
    return jsonify({'nom': structure_info.get('nom', 'Medilogic-GHP')})

@app.route('/api/structure/infos')
@login_required
def api_structure_infos():
    structure_id = session.get('structure_id')
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if s.get('ID') == structure_id), {})
    return jsonify({
        'nom': structure_info.get('nom', ''),
        'adresse': structure_info.get('adresse', ''),  # ← AJOUT
        'telephone': structure_info.get('telephone', ''),
        'logo_url': structure_info.get('logo_url', ''),   # ← AJOUT
        'email': structure_info.get('email', ''),          # ← AJOUT
        'rib': structure_info.get('rib', ''),  # 🔥 Colonne N
        'numero_affiliation': structure_info.get('numero_affiliation', '')  # 🔥 Colonne O
    })
# ========== RAPPELS AUTOMATIQUES RENDEZ-VOUS ==========
import threading
import time
from datetime import datetime, timedelta

def envoyer_rappel_auto(rdv, type_rappel, structure_info):
    """Envoie un rappel automatique WhatsApp"""
    try:
        patient_nom = rdv.get('patient_nom', 'Patient')
        patient_tel = rdv.get('patient_telephone', '')
        date_rdv = rdv.get('date_rendez_vous', '')
        heure_rdv = rdv.get('heure_rendez_vous', '')
        motif = rdv.get('motif', 'Consultation')
        structure_nom = structure_info.get('nom', 'Notre établissement')
        structure_tel = structure_info.get('telephone', '')
        
        if not patient_tel:
            return False
        
        # Nettoyer le numéro
        tel = str(patient_tel).replace(' ', '').replace('+', '').replace('-', '')
        if not tel.startswith('228') and not tel.startswith('229') and not tel.startswith('221'):
            tel = '228' + tel
        
        if type_rappel == 'j7':
            message = f"🔔 *RAPPEL DE RENDEZ-VOUS (J-7)* 🔔%0A%0A"
            message += f"🏥 *{structure_nom}*%0A"
            if structure_tel:
                message += f"📞 {structure_tel}%0A%0A"
            message += f"Bonjour *{patient_nom}*,%0A%0A"
            message += f"Nous vous rappelons votre rendez-vous dans une semaine :%0A"
            message += f"📅 Date : *{date_rdv}*%0A"
            message += f"⏰ Heure : *{heure_rdv}*%0A"
            message += f"📋 Motif : *{motif}*%0A%0A"
            message += f"Merci de votre ponctualité ! 🙏"
        else:
            message = f"🔔 *RAPPEL DE RENDEZ-VOUS (J-1)* 🔔%0A%0A"
            message += f"🏥 *{structure_nom}*%0A"
            if structure_tel:
                message += f"📞 {structure_tel}%0A%0A"
            message += f"Bonjour *{patient_nom}*,%0A%0A"
            message += f"Nous vous rappelons votre rendez-vous de demain :%0A"
            message += f"📅 Date : *{date_rdv}*%0A"
            message += f"⏰ Heure : *{heure_rdv}*%0A"
            message += f"📋 Motif : *{motif}*%0A%0A"
            message += f"À très vite ! 🏥"
        
        whatsapp_url = f"https://wa.me/{tel}?text={message}"
        print(f"📱 [RAPPEL AUTO] {patient_nom} - {type_rappel}")
        print(f"   🔗 Lien WhatsApp: {whatsapp_url}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur envoi rappel: {e}")
        return False

def maj_statut_rappel(rdv_id, type_rappel, structure_id):
    """Met à jour le statut du rappel dans Neon"""
    try:
        # 🔥 Mettre à jour dans Neon
        db.execute_query("""
            UPDATE rendez_vous 
            SET rappel_envoye = %s
            WHERE id = %s AND structure_id = %s
        """, (type_rappel, rdv_id, structure_id))
        return True
    except Exception as e:
        print(f"❌ Erreur maj statut: {e}")
        return False

def verifier_rappels_automatiques():
    """Vérifie les rendez-vous et envoie les rappels si nécessaire"""
    print(f"🔍 Vérification des rappels - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # 🔥 Récupérer toutes les structures actives
        structures = db.execute_query("SELECT id, nom, telephone FROM structures")
        
        for struct in structures:
            if isinstance(struct, dict):
                structure_id = struct.get('id')
                structure_nom = struct.get('nom', 'Notre établissement')
                structure_tel = struct.get('telephone', '')
            else:
                structure_id = struct[0]
                structure_nom = struct[1] if len(struct) > 1 else 'Notre établissement'
                structure_tel = struct[2] if len(struct) > 2 else ''
            
            # 🔥 Récupérer les rendez-vous depuis Neon
            rendez_vous = db.execute_query("""
                SELECT 
                    r.id,
                    r.patient_id,
                    r.date_rdv,
                    r.heure_rdv,
                    r.motif,
                    r.statut,
                    r.rappel_envoye,
                    p.nom,
                    p.prenom,
                    p.telephone
                FROM rendez_vous r
                LEFT JOIN patients p ON r.patient_id = p.id
                WHERE r.structure_id = %s
            """, (structure_id,))
            
            aujourdhui = datetime.now().date()
            j7 = aujourdhui + timedelta(days=7)
            j1 = aujourdhui + timedelta(days=1)
            
            structure_info = {'nom': structure_nom, 'telephone': structure_tel}
            
            for r in rendez_vous:
                if isinstance(r, dict):
                    rdv_id = r.get('id')
                    date_rdv_val = r.get('date_rdv')
                    statut = r.get('statut', 'programme')
                    rappel_envoye = r.get('rappel_envoye', 'non')
                    patient_nom = f"{r.get('nom', '')} {r.get('prenom', '')}".strip()
                    patient_tel = r.get('telephone', '')
                    heure_rdv = r.get('heure_rdv')
                    motif = r.get('motif', 'Consultation')
                else:
                    rdv_id = r[0]
                    date_rdv_val = r[2]
                    statut = r[5] if len(r) > 5 else 'programme'
                    rappel_envoye = r[6] if len(r) > 6 else 'non'
                    patient_nom = f"{r[7]} {r[8]}".strip() if len(r) > 8 else 'Patient'
                    patient_tel = r[9] if len(r) > 9 else ''
                    heure_rdv = r[3]
                    motif = r[4] if len(r) > 4 else 'Consultation'
                
                if not date_rdv_val:
                    continue
                
                try:
                    if isinstance(date_rdv_val, str):
                        date_rdv = datetime.strptime(date_rdv_val, '%Y-%m-%d').date()
                    else:
                        date_rdv = date_rdv_val
                    
                    # Ignorer les rendez-vous déjà terminés ou annulés
                    if statut in ['termine', 'annule']:
                        continue
                    
                    rdv_data = {
                        'ID': rdv_id,
                        'patient_nom': patient_nom,
                        'patient_telephone': patient_tel,
                        'date_rendez_vous': str(date_rdv),
                        'heure_rendez_vous': str(heure_rdv),
                        'motif': motif,
                        'statut': statut,
                        'rappel_envoye': rappel_envoye
                    }
                    
                    # Rappel J-7
                    if date_rdv == j7 and rappel_envoye not in ['j7', 'j1']:
                        if envoyer_rappel_auto(rdv_data, 'j7', structure_info):
                            maj_statut_rappel(rdv_id, 'j7', structure_id)
                            print(f"   ✅ Rappel J-7 envoyé à {patient_nom} (struct {structure_id})")
                    
                    # Rappel J-1
                    elif date_rdv == j1 and rappel_envoye != 'j1':
                        if envoyer_rappel_auto(rdv_data, 'j1', structure_info):
                            maj_statut_rappel(rdv_id, 'j1', structure_id)
                            print(f"   ✅ Rappel J-1 envoyé à {patient_nom} (struct {structure_id})")
                    
                    # Gestion des rendez-vous dépassés
                    elif date_rdv < aujourdhui and statut not in ['termine', 'annule', 'depasse']:
                        db.execute_query("""
                            UPDATE rendez_vous 
                            SET statut = 'depasse'
                            WHERE id = %s AND structure_id = %s
                        """, (rdv_id, structure_id))
                        print(f"   📆 RDV {rdv_id} marqué comme dépassé")
                        
                except Exception as e:
                    print(f"   ⚠️ Erreur traitement RDV {rdv_id}: {e}")
                    
    except Exception as e:
        print(f"❌ Erreur vérification: {e}")

def planifier_verification():
    """Planifie la vérification toutes les heures"""
    print("🚀 Service de rappels automatiques démarré")
    while True:
        time.sleep(3600)  # 1 heure
        with app.app_context():
            verifier_rappels_automatiques()

# Démarrer le thread de rappels automatiques
threading.Thread(target=planifier_verification, daemon=True).start()

@app.route('/api/test/rappels')
@login_required
def test_rappels():
    """Déclencher manuellement la vérification des rappels"""
    verifier_rappels_automatiques()
    return jsonify({'success': True, 'message': 'Vérification des rappels effectuée'})

@app.route('/rappels')
@login_required
def rappels():
    """Page des rappels de rendez-vous"""
    structure_id = session.get('structure_id')
    today = date.today()
    
    # ============================================================
    # RÉCUPÉRER LA STRUCTURE DEPUIS GOOGLE SHEETS
    # ============================================================
    
    structure = None
    
    try:
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        for s in structures:
            if str(s.get('ID')) == str(structure_id):
                structure = {
                    'nom': s.get('nom') or 'Hopital',
                    'adresse': s.get('adresse') or '',
                    'telephone': s.get('telephone') or '',
                    'email': s.get('email') or '',
                    'logo_url': s.get('logo_url') or ''
                }
                break
    except Exception as e:
        print(f"Erreur récupération structure: {e}")
    
    if not structure:
        structure = {
            'nom': 'Hopital',
            'adresse': '',
            'telephone': '',
            'email': '',
            'logo_url': ''
        }
    
    # ============================================================
    # RÉCUPÉRER LES RENDEZ-VOUS
    # ============================================================
    
    # Rendez-vous à moins de 7 jours
    moins_7 = RendezVous.query.filter(
        RendezVous.structure_id == structure_id,
        RendezVous.date_rendez_vous >= today,
        RendezVous.date_rendez_vous <= today + timedelta(days=7),
        RendezVous.statut.in_(['programme', 'confirme'])
    ).order_by(RendezVous.date_rendez_vous).all()
    
    moins_7_list = []
    for rdv in moins_7:
        moins_7_list.append({
            'id': rdv.id,
            'patient_nom': rdv.patient_nom,
            'patient_telephone': rdv.patient_telephone,
            'date_rendez_vous': rdv.date_rendez_vous,
            'heure_rendez_vous': rdv.heure_rendez_vous,
            'motif': rdv.motif,
            'jours_restants': (rdv.date_rendez_vous - today).days
        })
    
    # Rendez-vous dépassés
    depasses = RendezVous.query.filter(
        RendezVous.structure_id == structure_id,
        RendezVous.date_rendez_vous < today,
        RendezVous.statut.in_(['programme', 'confirme'])
    ).order_by(RendezVous.date_rendez_vous).all()
    
    depasses_list = []
    for rdv in depasses:
        depasses_list.append({
            'id': rdv.id,
            'patient_nom': rdv.patient_nom,
            'patient_telephone': rdv.patient_telephone,
            'date_rendez_vous': rdv.date_rendez_vous,
            'heure_rendez_vous': rdv.heure_rendez_vous,
            'motif': rdv.motif,
            'jours_depasse': (today - rdv.date_rendez_vous).days
        })
    
    return render_template(
        'rappels.html',
        moins_7_jours=moins_7_list,
        depasses=depasses_list,
        structure=structure  # Ajout des informations de la structure
    )
@app.route('/api/rappels/stats')
@login_required
def api_rappels_stats():
    """API pour les statistiques des rappels depuis Neon"""
    from datetime import datetime, timedelta
    
    structure_id = session.get('structure_id')
    
    # 🔥 Récupérer les rendez-vous depuis NEON
    rendez_vous = db.execute_query("""
        SELECT id, date_rdv, statut
        FROM rendez_vous 
        WHERE structure_id = %s
    """, (structure_id,))
    
    aujourdhui = datetime.now().date()
    date_limite = aujourdhui + timedelta(days=7)
    
    moins_7 = 0
    depasses = 0
    aujourdhui_count = 0
    
    for r in rendez_vous:
        if isinstance(r, dict):
            statut = r.get('statut', '')
            date_rdv_val = r.get('date_rdv')
        else:
            statut = r[2] if len(r) > 2 else ''
            date_rdv_val = r[1] if len(r) > 1 else None
        
        if statut in ['termine', 'annule']:
            continue
        
        if not date_rdv_val:
            continue
        
        try:
            if isinstance(date_rdv_val, str):
                date_rdv = datetime.strptime(date_rdv_val, '%Y-%m-%d').date()
            else:
                date_rdv = date_rdv_val
            
            if date_rdv < aujourdhui:
                depasses += 1
            elif date_rdv <= date_limite:
                moins_7 += 1
            
            if date_rdv == aujourdhui:
                aujourdhui_count += 1
        except:
            continue
    
    return jsonify({
        'moins_7': moins_7,
        'depasses': depasses,
        'aujourdhui': aujourdhui_count
    })
@app.route('/test_email')
def test_email():
    try:
        msg = Message("Test Medilogic-GHP", 
                      recipients=["essowasainfo60@gmail.com"],
                      body="Ceci est un test d'envoi d'email")
        mail.send(msg)
        return "✅ Email envoyé !"
    except Exception as e:
        return f"❌ Erreur: {e}"
# ========== ADMIN GLOBAL LOGIN ==========
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    """Page de connexion pour l'admin global"""
    if 'super_admin' in session:
        return redirect(url_for('admin_global'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Identifiants par défaut
        ADMIN_EMAIL = "essowasainfo60@gmail.com"
        ADMIN_PASSWORD = "essowasa1234A"
        
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session['super_admin'] = True
            session['super_admin_name'] = 'Super Admin'
            flash('Bienvenue dans l\'administration globale !', 'success')
            return redirect(url_for('admin_global'))
        else:
            flash('Email ou mot de passe incorrect', 'danger')
    
    return render_template('admin_login.html')

@app.route('/admin_logout')
def admin_logout():
    """Déconnexion de l'admin global"""
    session.pop('super_admin', None)
    flash('Déconnecté de l\'administration globale', 'info')
    return redirect(url_for('index'))

@app.route('/referentiel/cnss')
@login_required
def referentiel_cnss():
    return render_template('referentiel.html', 
                         titre="AMU-CNSS - Référentiel des prestataires",
                         url="https://referentiels.amu.tg/#/providers")

@app.route('/referentiel/inam')
@login_required
def referentiel_inam():
    return render_template('referentiel.html', 
                         titre="AMU-INAM - Portail Prestataire",
                         url="https://prestaplus.inam.tg/Vue/index.php")

@app.route('/api/import/actes', methods=['POST'])
@login_required
def import_actes():
    try:
        file = request.files['file']
        structure_id = session.get('structure_id')
        
        # Lire le fichier Excel
        df = pd.read_excel(BytesIO(file.read()))
        
        # Récupérer les actes existants
        actes = sheets_helper.get_all_records('actes')
        next_id = len(actes) + 1
        
        compteur = 0
        for _, row in df.iterrows():
            new_acte = [
                next_id + compteur,
                row.get('code', f"ACT-{compteur+1}"),
                row.get('nom', 'Acte'),
                row.get('prix', 0),
                row.get('description', ''),
                structure_id
            ]
            sheets_helper.add_record('actes', new_acte)
            compteur += 1
        
        return jsonify({'message': f'✅ {compteur} actes importés avec succès'})
        
    except Exception as e:
        return jsonify({'message': f'❌ Erreur: {str(e)}'}), 500

@app.route('/api/import/produits', methods=['POST'])
@login_required
def import_produits():
    try:
        file = request.files['file']
        structure_id = session.get('structure_id')
        
        df = pd.read_excel(BytesIO(file.read()))
        
        produits = sheets_helper.get_all_records('produits')
        next_id = len(produits) + 1
        
        compteur = 0
        for _, row in df.iterrows():
            new_produit = [
                next_id + compteur,
                row.get('code', f"PRD-{compteur+1}"),
                row.get('nom', 'Produit'),
                row.get('prix', 0),
                row.get('stock', 0),
                structure_id
            ]
            sheets_helper.add_record('produits', new_produit)
            compteur += 1
        
        return jsonify({'message': f'✅ {compteur} produits importés avec succès'})
        
    except Exception as e:
        return jsonify({'message': f'❌ Erreur: {str(e)}'}), 500

@app.route('/api/patients/<int:patient_id>', methods=['PUT'])
@login_required
def api_update_patient(patient_id):
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        # 🔥 Ajouter les colonnes de la personne à prévenir
        db.execute_query("""
            UPDATE patients
            SET nom = %s, prenom = %s, telephone = %s, adresse = %s,
                date_naissance = %s,
                type_assurance = %s, taux_prise_charge = %s, numero_assure = %s,
                assurance2_nom = %s, taux_assurance2 = %s, numero_assure2 = %s, societe_assurance2 = %s,
                personne_a_prevenir_nom = %s, personne_a_prevenir_telephone = %s, personne_a_prevenir_relation = %s
            WHERE id = %s AND structure_id = %s
        """, (
            data.get('nom'),
            data.get('prenom', ''),
            data.get('telephone'),
            data.get('adresse', ''),
            data.get('date_naissance', ''),
            data.get('type_assurance', 'non_assure'),
            data.get('taux_prise_charge', 0),
            data.get('numero_assure', ''),
            data.get('assurance2_nom'),
            data.get('taux_assurance2', 0),
            data.get('numero_assure2'),
            data.get('societe_assurance2'),
            data.get('personne_a_prevenir_nom'),
            data.get('personne_a_prevenir_telephone'),
            data.get('personne_a_prevenir_relation'),
            patient_id,
            structure_id
        ))

        upsert_societe_assurance(structure_id, data.get('assurance2_nom'), data.get('societe_assurance2'))

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/produits', methods=['POST'])
@login_required
def api_add_produit():
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        result = db.execute_query("""
            INSERT INTO produits (structure_id, code, nom, prix_vente, prix_achat,
                                  quantite_stock, seuil_alerte, unite, categorie)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            structure_id,
            data.get('code'),
            data.get('nom'),
            data.get('prix_vente'),
            data.get('prix_achat', 0),
            data.get('quantite_stock', 0),
            data.get('seuil_alerte', 10),
            data.get('unite', 'unité'),
            data.get('categorie', '')
        ))
        
        if result:
            return jsonify({'success': True, 'id': result[0]['id']})
        return jsonify({'success': False, 'error': 'Erreur insertion'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/api/produits/<int:produit_id>/stock', methods=['PUT'])
@login_required
def api_update_stock(produit_id):
    try:
        data = request.json
        structure_id = session.get('structure_id')
        quantite = data.get('quantite')
        operation = data.get('operation', 'vendre')  # vendre, ajouter, retirer
        
        if operation == 'vendre':
            sql = "UPDATE produits SET quantite_stock = quantite_stock - %s WHERE id = %s AND structure_id = %s"
        elif operation == 'ajouter':
            sql = "UPDATE produits SET quantite_stock = quantite_stock + %s WHERE id = %s AND structure_id = %s"
        else:
            sql = "UPDATE produits SET quantite_stock = %s WHERE id = %s AND structure_id = %s"
        
        db.execute_query(sql, (quantite, produit_id, structure_id))
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/produits')
@login_required
def api_get_produits():
    """Récupérer les produits depuis Google Sheets"""
    try:
        structure_id = session.get('structure_id')
        
        sheet_name = f"struct_{structure_id}_produits"
        print(f"📂 Chargement des produits pour structure {structure_id}")
        print(f"   Feuille: {sheet_name}")
        
        try:
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
            all_values = worksheet.get_all_values()
            print(f"📊 Lignes brutes: {len(all_values)}")
            
            if len(all_values) <= 1:
                print("⚠️ Aucune donnée trouvée")
                return jsonify([])
            
            produits_liste = []
            for i, row in enumerate(all_values[1:], start=1):
                if not row or len(row) < 3:
                    continue
                
                try:
                    # A=0: ID, B=1: nom, C=2: prix_vente, D=3: pbr, 
                    # E=4: prix_achat, F=5: quantite_stock, G=6: seuil_alerte, 
                    # H=7: unite, I=8: date_peremption, J=9: lot, K=10: structure_id
                    # L=11: prise_en_charge_amu, M=12: commentaire_amu,
                    # N=13: prise_en_charge_cac, O=14: commentaire_cac
                    # 🔥 P=15: statut (NOUVEAU)
                    
                    produit_id = row[0] if len(row) > 0 else None
                    nom = row[1].strip() if len(row) > 1 and row[1] else ''
                    prix_vente = float(row[2]) if len(row) > 2 and row[2] else 0
                    pbr = float(row[3]) if len(row) > 3 and row[3] else prix_vente
                    prix_achat = float(row[4]) if len(row) > 4 and row[4] else 0
                    
                    stock_raw = row[5].strip() if len(row) > 5 and row[5] else '0'
                    quantite_stock = int(float(stock_raw)) if stock_raw and stock_raw != '' else 0
                    
                    seuil_raw = row[6].strip() if len(row) > 6 and row[6] else '10'
                    seuil_alerte = int(float(seuil_raw)) if seuil_raw and seuil_raw != '' else 10
                    
                    unite = row[7] if len(row) > 7 else 'unité'
                    date_peremption = row[8] if len(row) > 8 and row[8] else ''
                    lot = row[9] if len(row) > 9 and row[9] else ''
                    struct_id = row[10] if len(row) > 10 else None
                    
                    # 🔥 RÉCUPÉRER LES CHAMPS COLONNES L, M, N, O
                    prise_en_charge_amu = row[11] if len(row) > 11 and row[11] else True
                    commentaire_amu = row[12] if len(row) > 12 and row[12] else ''
                    prise_en_charge_cac = row[13] if len(row) > 13 and row[13] else True
                    commentaire_cac = row[14] if len(row) > 14 and row[14] else ''
                    
                    # 🔥🔥🔥 RÉCUPÉRER LE STATUT (COLONNE P, INDEX 15) 🔥🔥🔥
                    statut = row[15].strip() if len(row) > 15 and row[15] else 'direct'
                    statut = statut.upper() if statut else 'direct'
                    
                    # Convertir en booléens
                    if isinstance(prise_en_charge_amu, str):
                        prise_en_charge_amu = prise_en_charge_amu.upper() == 'TRUE'
                    if isinstance(prise_en_charge_cac, str):
                        prise_en_charge_cac = prise_en_charge_cac.upper() == 'TRUE'
                    
                    if struct_id is None or str(struct_id) == str(structure_id):
                        if nom:
                            produits_liste.append({
                                'id': produit_id,
                                'nom': nom,
                                'prix_vente': prix_vente,
                                'pbr': pbr,
                                'prix_achat': prix_achat,
                                'quantite_stock': quantite_stock,
                                'seuil_alerte': seuil_alerte,
                                'unite': unite,
                                'date_peremption': date_peremption,
                                'lot': lot,
                                'prise_en_charge_amu': prise_en_charge_amu,
                                'commentaire_amu': commentaire_amu,
                                'prise_en_charge_cac': prise_en_charge_cac,
                                'commentaire_cac': commentaire_cac,
                                'statut': statut  # 🔥 NOUVEAU
                            })
                except Exception as e:
                    print(f"⚠️ Erreur ligne {i}: {e}")
                    continue
            
            print(f"✅ {len(produits_liste)} produits chargés")
            return jsonify(produits_liste)
            
        except Exception as e:
            print(f"⚠️ Feuille {sheet_name} non trouvée: {e}")
            # Fallback
            produits = sheets_helper.get_all_records('produits', use_prefix=False)
            produits_liste = []
            for p in produits:
                if str(p.get('structure_id')) == str(structure_id):
                    try:
                        prise_amu = p.get('prise_en_charge_amu', True)
                        if isinstance(prise_amu, str):
                            prise_amu = prise_amu.upper() == 'TRUE'
                        
                        prise_cac = p.get('prise_en_charge_cac', True)
                        if isinstance(prise_cac, str):
                            prise_cac = prise_cac.upper() == 'TRUE'
                        
                        # 🔥 Récupérer le statut dans le fallback
                        statut = p.get('statut', 'direct')
                        statut = statut.upper() if statut else 'direct'
                        
                        produits_liste.append({
                            'id': p.get('ID'),
                            'nom': p.get('nom', ''),
                            'prix_vente': float(p.get('prix_vente', 0)),
                            'pbr': float(p.get('pbr', p.get('prix_vente', 0))),
                            'prix_achat': float(p.get('prix_achat', 0)),
                            'quantite_stock': int(float(p.get('quantite_stock', 0))),
                            'seuil_alerte': int(float(p.get('seuil_alerte', 10))),
                            'unite': p.get('unite', 'unité'),
                            'date_peremption': p.get('date_peremption', ''),
                            'lot': p.get('lot', ''),
                            'prise_en_charge_amu': prise_amu,
                            'commentaire_amu': p.get('commentaire_amu', ''),
                            'prise_en_charge_cac': prise_cac,
                            'commentaire_cac': p.get('commentaire_cac', ''),
                            'statut': statut  # 🔥 NOUVEAU
                        })
                    except:
                        continue
            
            print(f"✅ {len(produits_liste)} produits chargés (fallback)")
            return jsonify(produits_liste)
        
    except Exception as e:
        print(f"❌ Erreur GET produits: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500


@app.route('/api/produits/search')
@login_required
def api_produits_search():
    """Rechercher des produits depuis Google Sheets (pour proforma)"""
    try:
        structure_id = session.get('structure_id')
        search = request.args.get('search', '').strip()
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        # 🔥 Utiliser la bonne feuille avec préfixe
        sheet_name = f"struct_{structure_id}_produits"
        
        try:
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
            all_values = worksheet.get_all_values()
            
            if len(all_values) <= 1:
                return jsonify({'data': [], 'total': 0, 'has_more': False})
            
            produits_liste = []
            for row in all_values[1:]:
                if not row or len(row) < 3:
                    continue
                
                try:
                    # A=0: ID, B=1: nom, C=2: prix_vente, D=3: pbr, 
                    # E=4: prix_achat, F=5: quantite_stock, G=6: seuil_alerte, 
                    # H=7: unite, I=8: date_peremption, J=9: lot, K=10: structure_id
                    # L=11: prise_en_charge_amu, M=12: commentaire_amu,
                    # N=13: prise_en_charge_cac, O=14: commentaire_cac
                    
                    produit_id = row[0] if len(row) > 0 else None
                    nom = row[1].strip() if len(row) > 1 and row[1] else ''
                    prix_vente = float(row[2]) if len(row) > 2 and row[2] else 0
                    pbr = float(row[3]) if len(row) > 3 and row[3] else prix_vente
                    prix_achat = float(row[4]) if len(row) > 4 and row[4] else 0
                    quantite_stock = int(float(row[5])) if len(row) > 5 and row[5] else 0
                    seuil_alerte = int(float(row[6])) if len(row) > 6 and row[6] else 10
                    unite = row[7] if len(row) > 7 else 'unité'
                    date_peremption = row[8] if len(row) > 8 and row[8] else ''
                    lot = row[9] if len(row) > 9 and row[9] else ''
                    struct_id = row[10] if len(row) > 10 else None
                    
                    # 🔥🔥🔥 AJOUTER LES CHAMPS MANQUANTS 🔥🔥🔥
                    # Colonne L (index 11) : prise_en_charge_amu
                    prise_en_charge_amu = row[11] if len(row) > 11 and row[11] else True
                    # Colonne M (index 12) : commentaire_amu
                    commentaire_amu = row[12] if len(row) > 12 and row[12] else ''
                    # Colonne N (index 13) : prise_en_charge_cac
                    prise_en_charge_cac = row[13] if len(row) > 13 and row[13] else True
                    # Colonne O (index 14) : commentaire_cac
                    commentaire_cac = row[14] if len(row) > 14 and row[14] else ''
                    
                    # 🔥 Convertir les valeurs "FALSE" / "TRUE" en booléens
                    if isinstance(prise_en_charge_amu, str):
                        prise_en_charge_amu = prise_en_charge_amu.upper() == 'TRUE'
                    if isinstance(prise_en_charge_cac, str):
                        prise_en_charge_cac = prise_en_charge_cac.upper() == 'TRUE'
                    
                    if struct_id is None or str(struct_id) == str(structure_id):
                        if nom:
                            produits_liste.append({
                                'id': produit_id,
                                'nom': nom,
                                'prix_vente': prix_vente,
                                'pbr': pbr,
                                'prix_achat': prix_achat,
                                'quantite_stock': quantite_stock,
                                'seuil_alerte': seuil_alerte,
                                'unite': unite,
                                'date_peremption': date_peremption,
                                'lot': lot,
                                'structure_id': struct_id,
                                # 🔥🔥🔥 NOUVEAUX CHAMPS 🔥🔥🔥
                                'prise_en_charge_amu': prise_en_charge_amu,
                                'commentaire_amu': commentaire_amu,
                                'prise_en_charge_cac': prise_en_charge_cac,
                                'commentaire_cac': commentaire_cac
                            })
                except Exception as e:
                    continue
            
            # Filtrer par recherche
            if search:
                search_lower = search.lower()
                produits_liste = [p for p in produits_liste 
                                 if search_lower in p['nom'].lower()]
            
            total = len(produits_liste)
            paginated = produits_liste[offset:offset + limit]
            
            return jsonify({
                'data': paginated,
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total
            })
            
        except Exception as e:
            print(f"⚠️ Feuille {sheet_name} non trouvée: {e}")
            # Fallback: essayer sans préfixe
            produits = sheets_helper.get_all_records('produits')
            produits_liste = []
            for p in produits:
                if str(p.get('structure_id')) == str(structure_id):
                    prix_vente = float(p.get('prix_vente', 0))
                    pbr = float(p.get('pbr', prix_vente))
                    
                    # 🔥 Récupérer les champs avec fallback
                    prise_amu = p.get('prise_en_charge_amu', True)
                    if isinstance(prise_amu, str):
                        prise_amu = prise_amu.upper() == 'TRUE'
                    
                    prise_cac = p.get('prise_en_charge_cac', True)
                    if isinstance(prise_cac, str):
                        prise_cac = prise_cac.upper() == 'TRUE'
                    
                    produits_liste.append({
                        'id': p.get('ID'),
                        'nom': p.get('nom', ''),
                        'prix_vente': prix_vente,
                        'pbr': pbr,
                        'prix_achat': float(p.get('prix_achat', 0)),
                        'quantite_stock': int(p.get('quantite_stock', 0)),
                        'seuil_alerte': int(p.get('seuil_alerte', 10)),
                        'unite': p.get('unite', 'unité'),
                        'date_peremption': p.get('date_peremption', ''),
                        'lot': p.get('lot', ''),
                        'structure_id': p.get('structure_id'),
                        # 🔥🔥🔥 NOUVEAUX CHAMPS 🔥🔥🔥
                        'prise_en_charge_amu': prise_amu,
                        'commentaire_amu': p.get('commentaire_amu', ''),
                        'prise_en_charge_cac': prise_cac,
                        'commentaire_cac': p.get('commentaire_cac', '')
                    })
            
            if search:
                search_lower = search.lower()
                produits_liste = [p for p in produits_liste 
                                 if search_lower in p['nom'].lower()]
            
            total = len(produits_liste)
            paginated = produits_liste[offset:offset + limit]
            
            return jsonify({
                'data': paginated,
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total
            })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'data': [], 'total': 0, 'error': str(e)}), 500


# ========== GESTION PRODUITS (Google Sheets) ==========

@app.route('/api/admin/produits', methods=['POST'])
@login_required
def api_admin_add_produit():
    """Ajouter un produit dans Google Sheets"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        produits = sheets_helper.get_all_records('produits')
        new_id = get_next_id(produits, 'ID')
        
        # A=ID, B=nom, C=prix_vente, D=pbr, E=prix_achat, 
        # F=quantite_stock, G=seuil_alerte, H=unite, 
        # I=date_peremption, J=lot, K=structure_id,
        # L=prise_en_charge_amu, M=commentaire_amu, 
        # N=prise_en_charge_cac, O=commentaire_cac
        new_produit = [
            new_id,
            data.get('nom'),
            float(data.get('prix_vente', 0)),
            float(data.get('pbr', data.get('prix_vente', 0))),
            float(data.get('prix_achat', 0)),
            int(data.get('quantite_stock', 0)),
            int(data.get('seuil_alerte', 10)),
            data.get('unite', 'unité'),
            data.get('date_peremption', ''),
            data.get('lot', ''),
            structure_id,
            'TRUE' if data.get('prise_en_charge_amu', True) else 'FALSE',
            data.get('commentaire_amu', ''),
            'TRUE' if data.get('prise_en_charge_cac', True) else 'FALSE',
            data.get('commentaire_cac', '')
        ]
        
        sheets_helper.add_record('produits', new_produit)
        
        return jsonify({'success': True, 'id': new_id})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/produits/<int:produit_id>', methods=['PUT'])
@login_required
def api_admin_update_produit(produit_id):
    """Modifier un produit dans Google Sheets"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        print(f"✏️ Modification produit ID: {produit_id}")
        print(f"   Données: {data}")
        
        sheet_name = f"struct_{structure_id}_produits"
        worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        
        # Trouver le produit
        cell = worksheet.find(str(produit_id), in_column=1)
        if not cell:
            return jsonify({'success': False, 'error': 'Produit non trouvé'}), 404
        
        row_num = cell.row
        current_row = worksheet.row_values(row_num)
        
        print(f"   Ligne actuelle: {current_row}")
        print(f"   Nombre de colonnes: {len(current_row)}")
        
        # 🔥 S'ASSURER QUE LA LIGNE A ASSEZ DE COLONNES
        # On a besoin de 15 colonnes (A à O)
        while len(current_row) < 15:
            current_row.append('')
        
        # 🔥 Mettre à jour toutes les colonnes
        # A=0: ID (ne pas toucher), B=1: nom, C=2: prix_vente, D=3: pbr, 
        # E=4: prix_achat, F=5: quantite_stock, G=6: seuil_alerte, 
        # H=7: unite, I=8: date_peremption, J=9: lot, K=10: structure_id,
        # L=11: prise_en_charge_amu, M=12: commentaire_amu, 
        # N=13: prise_en_charge_cac, O=14: commentaire_cac
        current_row[1] = data.get('nom', '')
        current_row[2] = str(float(data.get('prix_vente', 0)))
        current_row[3] = str(float(data.get('pbr', data.get('prix_vente', 0))))
        current_row[4] = str(float(data.get('prix_achat', 0)))
        current_row[5] = str(int(data.get('quantite_stock', 0)))
        current_row[6] = str(int(data.get('seuil_alerte', 10)))
        current_row[7] = data.get('unite', 'unité')
        current_row[8] = data.get('date_peremption', '')
        current_row[9] = data.get('lot', '')
        current_row[10] = str(structure_id)
        current_row[11] = 'TRUE' if data.get('prise_en_charge_amu', True) else 'FALSE'
        current_row[12] = data.get('commentaire_amu', '')
        current_row[13] = 'TRUE' if data.get('prise_en_charge_cac', True) else 'FALSE'
        current_row[14] = data.get('commentaire_cac', '')
        
        print(f"   Nouvelle ligne: {current_row}")
        
        # 🔥 Mettre à jour la ligne
        worksheet.update(range_name=f'A{row_num}:O{row_num}', values=[current_row])
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/produits/<int:produit_id>', methods=['DELETE'])
@login_required
def api_admin_delete_produit(produit_id):
    """Supprimer un produit de Google Sheets"""
    try:
        structure_id = session.get('structure_id')
        
        print(f"🗑️ Suppression produit ID: {produit_id}")
        
        # 🔥 Utiliser la feuille avec préfixe
        sheet_name = f"struct_{structure_id}_produits"
        worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        
        # Trouver le produit
        cell = worksheet.find(str(produit_id), in_column=1)
        if not cell:
            return jsonify({'success': False, 'error': 'Produit non trouvé'}), 404
        
        # Supprimer la ligne
        worksheet.delete_rows(cell.row)
        
        return jsonify({'success': True, 'message': 'Produit supprimé'})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/api/produits/<int:id>/approvisionner', methods=['POST'])
@login_required
def api_approvisionner_produit(id):
    """Approvisionner un produit (ajouter au stock)"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        quantite = data.get('quantite', 0)
        
        if not quantite or quantite <= 0:
            return jsonify({'success': False, 'error': 'Quantité invalide'}), 400
        
        sheet_name = f"struct_{structure_id}_produits"
        worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        
        cell = worksheet.find(str(id), in_column=1)
        if not cell:
            return jsonify({'success': False, 'error': 'Produit non trouvé'}), 404
        
        row_num = cell.row
        current_row = worksheet.row_values(row_num)
        
        # 🔥 Stock est en colonne F (index 5) car E=prix_achat
        stock_actuel = int(current_row[5]) if len(current_row) > 5 else 0
        nouveau_stock = stock_actuel + quantite
        
        worksheet.update_cell(row_num, 6, nouveau_stock)  # Colonne F = index 6 (1-based)
        
        return jsonify({'success': True, 'message': f'{quantite} unités ajoutées', 'stock': nouveau_stock})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/produits/<int:id>/stock', methods=['PUT'])
@login_required
def api_modifier_stock(id):
    """Modifier le stock d'un produit (ajouter ou retirer) dans Google Sheets"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        quantite = data.get('quantite', 0)
        operation = data.get('operation', 'ajouter')
        
        print(f"📦 Modification stock produit ID: {id}")
        print(f"   Quantité: {quantite}, Opération: {operation}")
        
        if not quantite or quantite <= 0:
            return jsonify({'success': False, 'error': 'Quantité invalide'}), 400
        
        # 🔥 Lire depuis Google Sheets
        worksheet = sheets_helper.spreadsheet.worksheet("produits")
        
        # Trouver le produit par ID (colonne A)
        cell = worksheet.find(str(id), in_column=1)
        if not cell:
            return jsonify({'success': False, 'error': 'Produit non trouvé'}), 404
        
        row_num = cell.row
        current_row = worksheet.row_values(row_num)
        
        # Colonnes: A=ID, B=nom, C=prix_vente, D=quantite_stock, E=seuil_alerte, F=unite, G=structure_id
        stock_actuel = int(current_row[3]) if len(current_row) > 3 else 0
        nom_produit = current_row[1] if len(current_row) > 1 else 'Produit'
        
        print(f"   Stock actuel de {nom_produit}: {stock_actuel}")
        
        if operation == 'retirer':
            if quantite > stock_actuel:
                return jsonify({'success': False, 'error': f'Stock insuffisant. Stock: {stock_actuel}'}), 400
            nouvelle_quantite = stock_actuel - quantite
        else:
            nouvelle_quantite = stock_actuel + quantite
        
        # Mettre à jour dans Sheets (colonne D = quantite_stock, index 4)
        worksheet.update_cell(row_num, 4, nouvelle_quantite)
        
        print(f"   ✅ Nouveau stock: {nouvelle_quantite}")
        
        return jsonify({'success': True, 'stock': nouvelle_quantite})
        
    except Exception as e:
        print(f"❌ Erreur modification stock: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/ventes/pharma', methods=['POST'])
@login_required
def api_vente_pharma():
    import json
    from datetime import datetime
    
    try:
        data = request.json
        structure_id = session.get('structure_id')
        
        vendeur = session.get('user_name')
        if not vendeur:
            vendeur = 'System'
        
        print("=" * 60)
        print("📦 VENTE PHARMACIE")
        print(f"Patient: {data.get('patient_nom')}")
        print(f"Vendeur: {vendeur}")
        print(f"Produits: {data.get('produits')}")
        print(f"Net à payer: {data.get('net_a_payer')} FCFA")
        print("=" * 60)
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvee'}), 400
        
        patient_id = data.get('patient_id')
        if not patient_id:
            return jsonify({'success': False, 'error': 'ID patient manquant'}), 400
        
        # 🔥 Récupérer les données des assurances
        taux_assurance = float(data.get('taux_assurance', 0))
        assurance2_nom = data.get('assurance2_nom', '')
        taux_assurance2 = float(data.get('taux_assurance2', 0))
        societe_assurance2 = data.get('societe_assurance2', '') or None
        prise_en_charge = float(data.get('prise_en_charge', 0))
        prise_en_charge2 = float(data.get('prise_en_charge2', 0))

        # 🔥 Récupérer le montant donné et le rendu
        montant_donne = float(data.get('montant_donne', 0))
        rendu = float(data.get('rendu', 0))

        # 🔥 Récupérer le base_remboursement (PBR total)
        base_remboursement = float(data.get('base_remboursement', 0))

        # 🔥 Récupérer le reste à payer
        reste_a_payer = float(data.get('reste_a_payer', 0))
        
        # 🔥 Récupérer les infos de modification de taux
        taux_temp_modifie = data.get('taux_temp_modifie', False)
        taux_original = data.get('taux_original', 0)

        # 🔥🔥🔥 RÉCUPÉRER L'AIDE HOSPITALIÈRE 🔥🔥🔥
        assurance_principale_active = data.get('assurance_principale_active', True)
        taux_aide = float(data.get('taux_aide', 0))
        aide_hospitaliere = float(data.get('aide_hospitaliere', 0))

        
        # 🔥 Récupérer les produits avec leurs infos de prise en charge
        produits_data = data.get('produits', [])
        for produit in produits_data:
            # S'assurer que les infos de prise en charge sont présentes
            if 'prise_en_charge_amu' not in produit:
                produit['prise_en_charge_amu'] = True
            if 'prise_en_charge_cac' not in produit:
                produit['prise_en_charge_cac'] = True
            if 'statut' not in produit:
                produit['statut'] = 'direct'  # 🔥 AJOUT
        
        # 🔥 Construire l'objet assurances pour le JSONB
        assurances_data = {
            'principale': {
                'nom': data.get('assurance_nom', 'Assurance'),
                'taux': taux_assurance,
                'montant_prise_en_charge': prise_en_charge
            },
            'complementaire': {
                'nom': assurance2_nom,
                'taux': taux_assurance2,
                'montant_prise_en_charge': prise_en_charge2,
                'taux_modifie': taux_temp_modifie,
                'taux_original': taux_original
            } if assurance2_nom and taux_assurance2 > 0 else None
        }
        
        print(f"📊 Assurances: {assurances_data}")
        print(f"💰 Montant donné: {montant_donne} FCFA, Rendu: {rendu} FCFA")
        print(f"📊 Base remboursement (PBR): {base_remboursement} FCFA")
        print(f"💰 Reste à payer: {reste_a_payer} FCFA")
        
        # ========== 1. ENREGISTRER LA VENTE DANS NEON ==========
        # 🔥 MODIFIER LA REQUÊTE SQL POUR AJOUTER LE CHAMP
        result = db.execute_query("""
            INSERT INTO ventes (
                patient_id, 
                patient_nom, 
                structure_id, 
                type, 
                sous_total, 
                prise_en_charge, 
                net_a_payer, 
                mode_paiement, 
                taux_assurance, 
                date_vente, 
                produits, 
                created_by_nom,
                statut,
                assurances,
                assurance2_nom,
                taux_assurance2,
                societe_assurance2,
                prise_en_charge2,
                montant_donne,
                rendu,
                base_remboursement,
                reste_a_payer,
                taux_temp_modifie,
                taux_original,
                assurance_principale_active,
                taux_aide,
                aide_hospitaliere
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s::jsonb, %s, 'validee', %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            patient_id,
            data.get('patient_nom', 'Patient'),
            structure_id,
            'pharmacie',
            float(data.get('sous_total', 0)),
            prise_en_charge,
            float(data.get('net_a_payer', 0)),
            data.get('mode_paiement', 'especes'),
            taux_assurance,
            json.dumps(produits_data, ensure_ascii=False),
            vendeur,
            json.dumps(assurances_data, ensure_ascii=False),
            assurance2_nom,
            taux_assurance2,
            societe_assurance2,
            prise_en_charge2,
            montant_donne,
            rendu,
            base_remboursement,
            reste_a_payer,
            taux_temp_modifie,
            taux_original,
            assurance_principale_active,  # 🔥 NOUVEAU
            taux_aide,                    # 🔥 NOUVEAU
            aide_hospitaliere             # 🔥 NOUVEAU
        ))

        if not result or len(result) == 0:
            print("❌ Erreur: Aucun ID retourné pour la vente")
            return jsonify({'success': False, 'error': 'Erreur insertion vente'}), 500

        upsert_societe_assurance(structure_id, assurance2_nom, societe_assurance2)

        vente_id = result[0]['id']
        print(f"✅ Vente pharmacie enregistrée dans Neon avec ID: {vente_id}")
        
        # ========== 2. AJOUTER LA RECETTE PATIENT (MONTANT DONNÉ) ==========
        montant_effectif = montant_donne - rendu
        if montant_effectif > 0:
            recette_result = db.execute_query("""
                INSERT INTO recettes (
                    structure_id, 
                    montant, 
                    source, 
                    source_id, 
                    source_type, 
                    description, 
                    created_by_nom,
                    date_recette
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (
                structure_id,
                montant_effectif,
                'patients',
                vente_id,
                'vente_pharma',
                f'Vente pharmacie #{vente_id} - {data.get("patient_nom", "Patient")} - Encaissé: {montant_effectif} FCFA (Donné: {montant_donne}, Rendu: {rendu})',
        vendeur
            ))
            
            if recette_result and len(recette_result) > 0:
                print(f"✅ Recette patient ajoutée: {montant_effectif} FCFA")
            else:
                print("⚠️ Erreur lors de l'insertion de la recette patient")
        else:
            print(f"ℹ️ montant_effectif = 0, pas de recette patient")
        
        
        # ========== 4. METTRE À JOUR LE STOCK DANS GOOGLE SHEETS ==========
        try:
            sheet_name = f"struct_{structure_id}_produits"
            print(f"   📂 Accès à la feuille: {sheet_name}")
            
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
            
            for produit in produits_data:
                produit_id = str(produit.get('id'))
                quantite_vendue = int(produit.get('quantite', 0))
                produit_nom = produit.get('nom', 'Inconnu')
                
                print(f"   🔍 Recherche du produit ID: {produit_id} - {produit_nom}")
                
                cell = worksheet.find(produit_id, in_column=1)
                if cell:
                    row_num = cell.row
                    current_row = worksheet.row_values(row_num)
                    # 🔥 Stock est en colonne F (index 5) car PBR est en colonne D (index 3)
                    stock_actuel = int(current_row[5]) if len(current_row) > 5 else 0
                    nouveau_stock = stock_actuel - quantite_vendue
                    
                    if nouveau_stock < 0:
                        print(f"   ⚠️ Stock négatif! {produit_nom}: {stock_actuel} - {quantite_vendue} = {nouveau_stock}")
                        nouveau_stock = 0
                    
                    print(f"   📊 Stock: {stock_actuel} → {nouveau_stock}")
                    worksheet.update_cell(row_num, 6, nouveau_stock)  # 🔥 Colonne F = index 6 (1-based)
                    print(f"   ✅ Stock Sheets mis à jour pour {produit_nom}")
                else:
                    print(f"   ❌ Produit ID {produit_id} non trouvé dans Sheets!")
                    print(f"   📋 IDs disponibles: {worksheet.col_values(1)}")
                    
        except Exception as e:
            print(f"   ❌ ERREUR mise à jour stock Sheets: {e}")
            import traceback
            traceback.print_exc()
        
        # ========== 5. METTRE À JOUR LE SOLDE DE CAISSE ==========
        try:
            recettes_total = db.execute_query("""
                SELECT COALESCE(SUM(montant), 0) as total 
                FROM recettes 
                WHERE structure_id = %s 
                AND (est_annulation IS NULL OR est_annulation = FALSE)
            """, (structure_id,))
            
            depenses_total = db.execute_query("""
                SELECT COALESCE(SUM(montant), 0) as total 
                FROM depenses 
                WHERE structure_id = %s
            """, (structure_id,))
            
            total_recettes = recettes_total[0]['total'] if recettes_total else 0
            total_depenses = depenses_total[0]['total'] if depenses_total else 0
            nouveau_solde = total_recettes - total_depenses
            
            db.execute_query("""
                INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
                VALUES (%s, %s, NOW())
                ON CONFLICT (structure_id) DO UPDATE SET 
                    solde_actuel = EXCLUDED.solde_actuel,
                    date_mise_a_jour = NOW()
            """, (structure_id, nouveau_solde))
            
            print(f"💰 Solde de caisse mis à jour: {nouveau_solde} FCFA")
            
        except Exception as e:
            print(f"⚠️ Erreur mise à jour solde: {e}")

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE (écriture SYSCOHADA validée) ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_vente
            vente_orm = Vente.query.get(vente_id)
            if vente_orm:
                ecriture = generer_ecriture_vente(vente_orm, user_nom=vendeur)
                if ecriture:
                    print(f"🧾 Écriture comptable #{ecriture.id} générée pour la vente pharma #{vente_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (vente pharma #{vente_id} conservée): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='vente_pharmacie',
                description=f"Vente pharmacie #{vente_id}",
                montant=montant_effectif, type_montant='credit',
                reference_type='vente', reference_id=vente_id,
                patient_id=patient_id, patient_nom=data.get('patient_nom', 'Patient'),
                utilisateur_nom=vendeur,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (vente pharma #{vente_id}): {e}")

        # ========== 6. RETOUR API AVEC TOUTES LES INFOS ==========
        print(f"✅ Vente pharmacie #{vente_id} terminée avec succès!")

        return jsonify({
            'success': True, 
            'vente_id': vente_id,
            'montant_donne': montant_donne,
            'reste_a_payer': reste_a_payer,
            'net_a_payer': float(data.get('net_a_payer', 0)),
            'rendu': rendu
        })
        
    except Exception as e:
        print(f"❌ ERREUR GENERALE: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/produits/<int:id>/stock', methods=['GET'])
@login_required
def api_get_stock_produit(id):
    """Récupérer le stock d'un produit depuis Google Sheets"""
    try:
        structure_id = session.get('structure_id')
        
        # 🔥 Utiliser le bon nom de feuille
        sheet_name = f"struct_{structure_id}_produits"
        worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
        
        # Trouver le produit par ID (colonne A)
        cell = worksheet.find(str(id), in_column=1)
        if not cell:
            return jsonify({'success': False, 'error': 'Produit non trouvé'}), 404
        
        row_num = cell.row
        current_row = worksheet.row_values(row_num)
        
        # Colonnes: A=ID, B=nom, C=prix_vente, D=quantite_stock, E=seuil_alerte, F=unite, G=structure_id
        produit = {
            'id': int(current_row[0]) if len(current_row) > 0 else None,
            'nom': current_row[1] if len(current_row) > 1 else '',
            'quantite_stock': int(current_row[3]) if len(current_row) > 3 else 0,
            'seuil_alerte': int(current_row[4]) if len(current_row) > 4 else 10
        }
        
        return jsonify({'success': True, 'stock': produit})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients/count')
@login_required
def api_patients_count():
    """Retourne le nombre de patients"""
    try:
        structure_id = session.get('structure_id')
        result = db.execute_query("""
            SELECT COUNT(*) as total FROM patients WHERE structure_id = %s
        """, (structure_id,))
        total = result[0]['total'] if result else 0
        return jsonify({'total': total})
    except Exception as e:
        return jsonify({'total': 0}), 500

@app.route('/api/ventes/stats')
@login_required
def api_ventes_stats():
    """Retourne les statistiques des ventes (actes et pharmacie) depuis Neon"""
    try:
        structure_id = session.get('structure_id')
        
        # Date du jour
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 🔥 Récupérer UNIQUEMENT les ventes valides (non annulées)
        ventes = db.execute_query("""
            SELECT type, net_a_payer, sous_total, date_vente
            FROM ventes 
            WHERE structure_id = %s 
            AND (statut IS NULL OR statut != 'annulee')
        """, (structure_id,))
        
        actes_today = 0
        pharma_today = 0
        ca_net_today = 0
        ca_brut_today = 0
        
        for v in ventes:
            if isinstance(v, dict):
                date_vente = v.get('date_vente')
                if date_vente:
                    if hasattr(date_vente, 'strftime'):
                        date_vente_str = date_vente.strftime('%Y-%m-%d')
                    else:
                        date_vente_str = str(date_vente)[:10]
                    
                    if date_vente_str == today:
                        if v.get('type') == 'actes':
                            actes_today += 1
                        else:
                            pharma_today += 1
                        
                        ca_net_today += float(v.get('net_a_payer', 0))
                        ca_brut_today += float(v.get('sous_total', 0))
        
        return jsonify({
            'actes_today': actes_today,
            'pharma_today': pharma_today,
            'ca_net_today': ca_net_today,
            'ca_brut_today': ca_brut_today
        })
        
    except Exception as e:
        print(f"❌ Erreur stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'actes_today': 0, 
            'pharma_today': 0, 
            'ca_net_today': 0,
            'ca_brut_today': 0
        }), 500

@app.route('/api/activites/recentes')
@login_required
def api_activites_recentes():
    """Retourne les 10 dernières activités (hors annulées)"""
    try:
        structure_id = session.get('structure_id')
        
        # 🔥 Récupérer UNIQUEMENT les ventes valides (non annulées)
        ventes = db.execute_query("""
            SELECT 
                v.id,
                v.patient_id,
                v.patient_nom,
                v.type,
                v.net_a_payer,
                v.date_vente,
                p.nom,
                p.prenom
            FROM ventes v
            LEFT JOIN patients p ON v.patient_id = p.id
            WHERE v.structure_id = %s 
            AND (v.statut IS NULL OR v.statut != 'annulee')
            ORDER BY v.date_vente DESC
            LIMIT 10
        """, (structure_id,))
        
        result = []
        for v in ventes:
            if isinstance(v, dict):
                patient_name = v.get('patient_nom', '')
                if not patient_name or patient_name == '':
                    nom = v.get('nom', '')
                    prenom = v.get('prenom', '')
                    patient_name = f"{nom} {prenom}".strip()
                if not patient_name:
                    patient_name = 'Patient'
                
                date_vente = v.get('date_vente')
                if date_vente:
                    if hasattr(date_vente, 'strftime'):
                        date_str = date_vente.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        date_str = str(date_vente)
                else:
                    date_str = ''
                    
                result.append({
                    'id': v.get('id'),
                    'patient_nom': patient_name,
                    'type': v.get('type', 'unknown'),
                    'montant': float(v.get('net_a_payer', 0)),
                    'date': date_str
                })
            else:
                patient_name = v[2] if len(v) > 2 and v[2] else ''
                if not patient_name and len(v) > 6:
                    patient_name = f"{v[6] or ''} {v[7] or ''}".strip()
                if not patient_name:
                    patient_name = 'Patient'
                
                date_vente = v[5] if len(v) > 5 else None
                if date_vente:
                    if hasattr(date_vente, 'strftime'):
                        date_str = date_vente.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        date_str = str(date_vente)
                else:
                    date_str = ''
                    
                result.append({
                    'id': v[0],
                    'patient_nom': patient_name,
                    'type': v[3] if len(v) > 3 else 'unknown',
                    'montant': float(v[4]) if len(v) > 4 else 0,
                    'date': date_str
                })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur activités: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500

@app.route('/api/ventes/actes', methods=['POST'])
@login_required
def api_add_acte_vente():
    import json
    from datetime import datetime
    
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        print("=" * 60)
        print("VENTE ACTES")
        print(f"Patient: {data.get('patient_nom')}")
        print(f"Vendeur: {user_name}")
        print("=" * 60)
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvee'}), 400
        
        patient_id = data.get('patient_id')
        if not patient_id:
            return jsonify({'success': False, 'error': 'ID patient manquant'}), 400
        
        # 🔥 Récupérer les données des assurances
        taux_assurance = float(data.get('taux_assurance', 0))
        assurance2_nom = data.get('assurance2_nom', '')
        taux_assurance2 = float(data.get('taux_assurance2', 0))
        societe_assurance2 = data.get('societe_assurance2', '') or None
        prise_en_charge = float(data.get('prise_en_charge', 0))
        prise_en_charge2 = float(data.get('prise_en_charge2', 0))

        # 🔥 Récupérer le montant donné et le rendu
        montant_donne = float(data.get('montant_donne', 0))
        rendu = float(data.get('rendu', 0))

        # 🔥 Récupérer le base_remboursement (PBR total)
        base_remboursement = float(data.get('base_remboursement', 0))

        # 🔥 Récupérer le reste à payer
        reste_a_payer = float(data.get('reste_a_payer', 0))
        
        # 🔥 Récupérer les infos de modification de taux
        taux_temp_modifie = data.get('taux_temp_modifie', False)
        taux_original = data.get('taux_original', 0)

        # 🔥🔥🔥 RÉCUPÉRER L'AIDE HOSPITALIÈRE 🔥🔥🔥
        assurance_principale_active = data.get('assurance_principale_active', True)
        taux_aide = float(data.get('taux_aide', 0))
        aide_hospitaliere = float(data.get('aide_hospitaliere', 0))

        
        # 🔥 Récupérer les actes avec leurs infos de prise en charge
        actes_data = data.get('actes', [])
        for acte in actes_data:
            if 'prise_en_charge_amu' not in acte:
                acte['prise_en_charge_amu'] = True
            if 'prise_en_charge_cac' not in acte:
                acte['prise_en_charge_cac'] = True

            if 'statut' not in acte:
                acte['statut'] = 'direct'  # 🔥 AJOUT
        
        # 🔥 Construire l'objet assurances pour le JSONB
        assurances_data = {
            'principale': {
                'nom': data.get('assurance_nom', 'Assurance'),
                'taux': taux_assurance,
                'montant_prise_en_charge': prise_en_charge
            },
            'complementaire': {
                'nom': assurance2_nom,
                'taux': taux_assurance2,
                'montant_prise_en_charge': prise_en_charge2,
                'taux_modifie': taux_temp_modifie,
                'taux_original': taux_original
            } if assurance2_nom and taux_assurance2 > 0 else None
        }
        
        print(f"📊 Assurances: {assurances_data}")
        print(f"💰 Montant donné: {montant_donne} FCFA, Rendu: {rendu} FCFA")
        print(f"📊 Base remboursement (PBR): {base_remboursement} FCFA")
        print(f"💰 Reste à payer: {reste_a_payer} FCFA")
        
        # ========== 1. ENREGISTRER LA VENTE DANS NEON ==========
        # 🔥 MODIFIER LA REQUÊTE SQL POUR AJOUTER LE CHAMP
        result = db.execute_query("""
            INSERT INTO ventes (
                patient_id, 
                patient_nom, 
                structure_id, 
                type, 
                sous_total, 
                prise_en_charge, 
                net_a_payer, 
                mode_paiement, 
                taux_assurance, 
                date_vente, 
                actes,
                created_by_nom,
                assurances,
                assurance2_nom,
                taux_assurance2,
                societe_assurance2,
                prise_en_charge2,
                montant_donne,
                rendu,
                base_remboursement,
                reste_a_payer,
                taux_temp_modifie,
                taux_original,
                assurance_principale_active,
                taux_aide,
                aide_hospitaliere
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            patient_id,
            data.get('patient_nom', 'Patient'),
            structure_id,
            'actes',
            float(data.get('sous_total', 0)),
            prise_en_charge,
            float(data.get('net_a_payer', 0)),
            data.get('mode_paiement', 'especes'),
            taux_assurance,
            json.dumps(actes_data, ensure_ascii=False),
            user_name,
            json.dumps(assurances_data, ensure_ascii=False),
            assurance2_nom,
            taux_assurance2,
            societe_assurance2,
            prise_en_charge2,
            montant_donne,
            rendu,
            base_remboursement,
            reste_a_payer,
            taux_temp_modifie,
            taux_original,
            assurance_principale_active,  # 🔥 NOUVEAU
            taux_aide,                    # 🔥 NOUVEAU
            aide_hospitaliere             # 🔥 NOUVEAU
        ))

        if not result or len(result) == 0:
            print("❌ Erreur: Aucun ID retourné pour la vente")
            return jsonify({'success': False, 'error': 'Erreur insertion vente'}), 500

        upsert_societe_assurance(structure_id, assurance2_nom, societe_assurance2)

        vente_id = result[0]['id']
        print(f"✅ Vente actes enregistrée dans Neon avec ID: {vente_id}")
        
        # ========== 2. AJOUTER LA RECETTE PATIENT ==========
        montant_effectif = montant_donne - rendu
        if montant_effectif > 0:
            recette_result = db.execute_query("""
                INSERT INTO recettes (
                    structure_id, 
                    montant, 
                    source, 
                    source_id, 
                    source_type, 
                    description, 
                    created_by_nom,
                    date_recette
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (
                structure_id,
                montant_effectif,
                'patients',
                vente_id,
                'vente_acte',
                f'Vente actes #{vente_id} - {data.get("patient_nom", "Patient")} - Encaissé: {montant_effectif} FCFA',
                user_name
            ))
            
            if recette_result and len(recette_result) > 0:
                print(f"✅ Recette patient ajoutée: {montant_effectif} FCFA")
        
        
        # ========== 4. METTRE À JOUR LE SOLDE DE CAISSE ==========
        try:
            recettes_total = db.execute_query("""
                SELECT COALESCE(SUM(montant), 0) as total 
                FROM recettes 
                WHERE structure_id = %s 
                AND (est_annulation IS NULL OR est_annulation = FALSE)
            """, (structure_id,))
            
            depenses_total = db.execute_query("""
                SELECT COALESCE(SUM(montant), 0) as total 
                FROM depenses 
                WHERE structure_id = %s
            """, (structure_id,))
            
            total_recettes = recettes_total[0]['total'] if recettes_total else 0
            total_depenses = depenses_total[0]['total'] if depenses_total else 0
            nouveau_solde = total_recettes - total_depenses
            
            db.execute_query("""
                INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
                VALUES (%s, %s, NOW())
                ON CONFLICT (structure_id) DO UPDATE SET 
                    solde_actuel = EXCLUDED.solde_actuel,
                    date_mise_a_jour = NOW()
            """, (structure_id, nouveau_solde))
            
            print(f"💰 Solde de caisse mis à jour: {nouveau_solde} FCFA")
            
        except Exception as e:
            print(f"⚠️ Erreur mise à jour solde: {e}")

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE (écriture SYSCOHADA validée) ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_vente
            vente_orm = Vente.query.get(vente_id)
            if vente_orm:
                ecriture = generer_ecriture_vente(vente_orm, user_nom=user_name)
                if ecriture:
                    print(f"🧾 Écriture comptable #{ecriture.id} générée pour la vente #{vente_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (vente #{vente_id} conservée): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='vente_actes',
                description=f"Vente actes #{vente_id}",
                montant=(montant_donne - rendu), type_montant='credit',
                reference_type='vente', reference_id=vente_id,
                patient_id=patient_id, patient_nom=data.get('patient_nom', 'Patient'),
                utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (vente #{vente_id}): {e}")

        print(f"✅ Vente actes #{vente_id} terminée avec succès!")

        return jsonify({
            'success': True,
            'vente_id': vente_id,
            'montant_donne': montant_donne,
            'reste_a_payer': reste_a_payer,
            'net_a_payer': float(data.get('net_a_payer', 0))
        })
        
    except Exception as e:
        print(f"❌ ERREUR GENERALE: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ⭐ NOTE : l'ancien pipeline de traitement asynchrone (catégorisation +
# écritures groupées quotidiennes via scripts/traiter_ventes.py et
# scripts/generer_ecritures_groupes.py) a été retiré — remplacé par la
# génération synchrone, par transaction, dans services/comptabilite_service.py
# (une écriture par vente/paiement, immédiatement validée). Ces scripts
# restent dans le dépôt pour référence mais ne sont plus appelés depuis l'app.

@app.route('/api/ventes/all')
@login_required
def api_get_all_ventes():
    """Récupérer toutes les ventes (actes + pharmacie) depuis Neon (hors annulées)"""
    try:
        structure_id = session.get('structure_id')
        
        # 🔥 Ajouter toutes les colonnes nécessaires
        ventes = db.execute_query("""
            SELECT 
                v.id, 
                v.patient_nom, 
                v.type, 
                v.net_a_payer, 
                v.taux_assurance, 
                v.date_vente, 
                v.actes, 
                v.produits, 
                v.created_by_nom, 
                v.statut,
                v.assurance2_nom,
                v.taux_assurance2,
                v.prise_en_charge2,
                v.societe_assurance2,
                v.assurances,
                v.montant_donne,
                v.rendu,
                v.reste_a_payer,
                v.base_remboursement,
                v.taux_temp_modifie,
                v.taux_original,
                p.type_assurance,
                p.assurance2_nom as patient_assurance2_nom,
                p.taux_assurance2 as patient_taux_assurance2,
                p.societe_assurance2 as patient_societe_assurance2,
                v.taux_aide,
                v.aide_hospitaliere,
                v.prise_en_charge
            FROM ventes v
            LEFT JOIN patients p ON v.patient_id = p.id
            WHERE v.structure_id = %s 
            AND (v.statut IS NULL OR v.statut != 'annulee')
            ORDER BY v.date_vente DESC
        """, (structure_id,))
        
        result = []
        import json
        
        for v in ventes:
            if isinstance(v, dict):
                detail = ""
                articles = []
                
                # 🔥🔥🔥 CORRECTION : Gérer TOUS les types 🔥🔥🔥
                type_vente = v.get('type', 'actes')
                
                # Récupérer les actes
                actes_data = v.get('actes')
                if isinstance(actes_data, str):
                    try:
                        actes_data = json.loads(actes_data)
                    except:
                        actes_data = []
                elif not actes_data:
                    actes_data = []
                
                # Récupérer les produits
                produits_data = v.get('produits')
                if isinstance(produits_data, str):
                    try:
                        produits_data = json.loads(produits_data)
                    except:
                        produits_data = []
                elif not produits_data:
                    produits_data = []
                
                # 🔥 Cas 1: MIXTE → actes + produits
                if type_vente == 'mixte':
                    # Ajouter les actes
                    for a in actes_data:
                        nom = a.get('nom', 'Acte')
                        qte = a.get('quantite', 1)
                        articles.append(f"{nom} x{qte}")
                    # Ajouter les produits
                    for p in produits_data:
                        nom = p.get('nom', 'Produit')
                        qte = p.get('quantite', 1)
                        articles.append(f"{nom} x{qte}")
                    detail = ", ".join(articles) if articles else "-"
                
                # 🔥 Cas 2: ACTES uniquement
                elif type_vente == 'actes':
                    for a in actes_data:
                        nom = a.get('nom', 'Acte')
                        qte = a.get('quantite', 1)
                        if qte > 1:
                            articles.append(f"{nom} x{qte}")
                        else:
                            articles.append(nom)
                    detail = ", ".join(articles) if articles else "-"
                
                # 🔥 Cas 3: PHARMACIE uniquement
                elif type_vente in ['pharma', 'pharmacie']:
                    for p in produits_data:
                        nom = p.get('nom', 'Produit')
                        qte = p.get('quantite', 1)
                        if qte > 1:
                            articles.append(f"{nom} x{qte}")
                        else:
                            articles.append(nom)
                    detail = ", ".join(articles) if articles else "-"
                
                # 🔥 Cas 4: Autre (fallback)
                else:
                    # Essayer de récupérer depuis actes ou produits
                    if actes_data:
                        for a in actes_data:
                            nom = a.get('nom', 'Acte')
                            qte = a.get('quantite', 1)
                            articles.append(f"{nom} x{qte}")
                    if produits_data:
                        for p in produits_data:
                            nom = p.get('nom', 'Produit')
                            qte = p.get('quantite', 1)
                            articles.append(f"{nom} x{qte}")
                    detail = ", ".join(articles) if articles else "-"
                
                # 🔥 Récupérer les infos des assurances
                type_assurance = v.get('type_assurance', 'non_assure')
                
                assurance_principale = type_assurance if type_assurance and type_assurance != '' else 'non_assure'
                
                assurance2_nom = v.get('assurance2_nom', '')
                if not assurance2_nom and v.get('patient_assurance2_nom'):
                    assurance2_nom = v.get('patient_assurance2_nom')
                
                taux_assurance2 = float(v.get('taux_assurance2', 0))
                if taux_assurance2 == 0 and v.get('patient_taux_assurance2'):
                    taux_assurance2 = float(v.get('patient_taux_assurance2', 0))

                societe_assurance2 = v.get('societe_assurance2') or v.get('patient_societe_assurance2') or ''

                prise_en_charge2 = float(v.get('prise_en_charge2', 0))
                montant_donne = float(v.get('montant_donne', 0))
                rendu = float(v.get('rendu', 0))
                reste_a_payer = float(v.get('reste_a_payer', 0))
                base_remboursement = float(v.get('base_remboursement', 0))
                taux_temp_modifie = v.get('taux_temp_modifie', False)
                taux_original = float(v.get('taux_original', 0))
                
                assurances = v.get('assurances')
                if isinstance(assurances, str):
                    try:
                        assurances = json.loads(assurances)
                    except:
                        assurances = None

                taux_aide = float(v.get('taux_aide', 0)) if v.get('taux_aide') is not None else 0
                aide_hospitaliere = float(v.get('aide_hospitaliere', 0)) if v.get('aide_hospitaliere') is not None else 0
                prise_en_charge = float(v.get('prise_en_charge', 0)) if v.get('prise_en_charge') is not None else 0
                
                result.append({
                    'ID': v.get('id'),
                    'patient_nom': v.get('patient_nom', 'Patient'),
                    'type': type_vente,
                    'net_a_payer': float(v.get('net_a_payer', 0)),
                    'taux_assurance': v.get('taux_assurance', 0),
                    'date_vente': str(v.get('date_vente', '')),
                    'detail': detail,
                    'created_by_nom': v.get('created_by_nom', None),
                    'statut': v.get('statut', 'validee'),
                    'assurance_nom': assurance_principale,
                    'type_assurance': type_assurance,
                    'assurance2_nom': assurance2_nom,
                    'taux_assurance2': float(taux_assurance2 or 0),
                    'prise_en_charge2': float(prise_en_charge2 or 0),
                    'societe_assurance2': societe_assurance2,
                    'assurances': assurances,
                    'montant_donne': montant_donne,
                    'rendu': rendu,
                    'reste_a_payer': reste_a_payer,
                    'base_remboursement': base_remboursement,
                    'taux_temp_modifie': taux_temp_modifie,
                    'taux_original': taux_original,
                    'taux_aide': taux_aide,
                    'prise_en_charge': prise_en_charge,
                    'aide_hospitaliere': aide_hospitaliere,
                    # 🔥 Ajouter le nombre d'articles pour l'affichage
                    'nb_actes': len(actes_data),
                    'nb_produits': len(produits_data),
                    'total_articles': len(actes_data) + len(produits_data)
                })
            else:
                # Format tuple (pour compatibilité)
                detail = ""
                articles = []
                vente_type = v[2] if len(v) > 2 else ''
                
                # Récupérer actes et produits depuis le tuple
                actes_data = v[6] if len(v) > 6 else []
                if isinstance(actes_data, str):
                    try:
                        actes_data = json.loads(actes_data)
                    except:
                        actes_data = []
                elif not actes_data:
                    actes_data = []
                
                produits_data = v[7] if len(v) > 7 else []
                if isinstance(produits_data, str):
                    try:
                        produits_data = json.loads(produits_data)
                    except:
                        produits_data = []
                elif not produits_data:
                    produits_data = []
                
                # 🔥 Gérer mixte
                if vente_type == 'mixte':
                    for a in actes_data:
                        articles.append(f"{a.get('nom', 'Acte')} x{a.get('quantite', 1)}")
                    for p in produits_data:
                        articles.append(f"{p.get('nom', 'Produit')} x{p.get('quantite', 1)}")
                    detail = ", ".join(articles) if articles else "-"
                elif vente_type == 'actes':
                    for a in actes_data:
                        articles.append(f"{a.get('nom', 'Acte')} x{a.get('quantite', 1)}")
                    detail = ", ".join(articles) if articles else "-"
                elif vente_type in ['pharma', 'pharmacie']:
                    for p in produits_data:
                        articles.append(f"{p.get('nom', 'Produit')} x{p.get('quantite', 1)}")
                    detail = ", ".join(articles) if articles else "-"
                else:
                    detail = "-"
                
                type_assurance = v[20] if len(v) > 20 else 'non_assure'
                assurance_principale = type_assurance if type_assurance and type_assurance != '' else 'non_assure'
                
                assurance2_nom = v[10] if len(v) > 10 else ''
                if not assurance2_nom and len(v) > 21:
                    assurance2_nom = v[21]
                
                taux_assurance2 = float(v[11]) if len(v) > 11 else 0
                if taux_assurance2 == 0 and len(v) > 22:
                    taux_assurance2 = float(v[22])
                
                prise_en_charge2 = v[12] if len(v) > 12 else 0
                assurances = v[13] if len(v) > 13 else None
                if isinstance(assurances, str):
                    try:
                        assurances = json.loads(assurances)
                    except:
                        assurances = None
                
                montant_donne = float(v[14]) if len(v) > 14 else 0
                rendu = float(v[15]) if len(v) > 15 else 0
                reste_a_payer = float(v[16]) if len(v) > 16 else 0
                base_remboursement = float(v[17]) if len(v) > 17 else 0
                taux_temp_modifie = v[18] if len(v) > 18 else False
                taux_original = float(v[19]) if len(v) > 19 else 0
                
                result.append({
                    'ID': v[0],
                    'patient_nom': v[1] if len(v) > 1 else 'Patient',
                    'type': vente_type,
                    'net_a_payer': float(v[3]) if len(v) > 3 else 0,
                    'taux_assurance': v[4] if len(v) > 4 else 0,
                    'date_vente': str(v[5]) if len(v) > 5 else '',
                    'detail': detail,
                    'created_by_nom': v[8] if len(v) > 8 else None,
                    'statut': v[9] if len(v) > 9 else 'validee',
                    'assurance_nom': assurance_principale,
                    'type_assurance': type_assurance,
                    'assurance2_nom': assurance2_nom,
                    'taux_assurance2': float(taux_assurance2 or 0),
                    'prise_en_charge2': float(prise_en_charge2 or 0),
                    'assurances': assurances,
                    'montant_donne': montant_donne,
                    'rendu': rendu,
                    'reste_a_payer': reste_a_payer,
                    'base_remboursement': base_remboursement,
                    'taux_temp_modifie': taux_temp_modifie,
                    'taux_original': taux_original,
                    'nb_actes': len(actes_data),
                    'nb_produits': len(produits_data),
                    'total_articles': len(actes_data) + len(produits_data)
                })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur chargement ventes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500

@app.route('/api/actes')
@login_required
def api_get_actes():
    """Récupérer les actes depuis Google Sheets avec recherche, PBR et prise en charge"""
    try:
        structure_id = session.get('structure_id')
        search = request.args.get('search', '').strip()
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        print(f"📂 Recherche actes: '{search}' (limit={limit}, offset={offset})")
        
        sheet_name = f"struct_{structure_id}_actes"
        print(f"   Feuille: {sheet_name}")
        
        try:
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
            actes = worksheet.get_all_records()
            print(f"📊 Total actes dans {sheet_name}: {len(actes)}")
        except Exception as e:
            print(f"⚠️ Feuille {sheet_name} non trouvée: {e}")
            actes = sheets_helper.get_all_records('actes', use_prefix=False)
            print(f"📊 Total actes dans 'actes': {len(actes)}")
        
        # Filtrer par structure
        actes_struct = []
        for a in actes:
            sid = a.get('structure_id') or a.get('structure_id') or a.get('structureId')
            if sid is None or str(sid) == str(structure_id):
                actes_struct.append(a)
        
        # Filtrer par recherche
        if search:
            search_lower = search.lower()
            actes_struct = [a for a in actes_struct 
                           if search_lower in str(a.get('nom', '')).lower() 
                           or search_lower in str(a.get('code', '')).lower()]
        
        total = len(actes_struct)
        paginated = actes_struct[offset:offset + limit]
        
        result = []
        for a in paginated:
            # Prix (colonne C)
            prix_raw = a.get('prix') or a.get('PRIX') or a.get('Prix') or 0
            prix_float = 0
            if prix_raw and prix_raw != '' and prix_raw != '-':
                try:
                    prix_str = str(prix_raw).strip().replace(' ', '').replace(',', '').replace('FCFA', '')
                    prix_float = float(prix_str) if prix_str else 0
                except (ValueError, TypeError):
                    prix_float = 0
            
            # PBR (colonne D)
            pbr_raw = a.get('pbr') or a.get('PBR') or a.get('Pbr') or prix_float
            pbr_float = prix_float
            if pbr_raw and pbr_raw != '' and pbr_raw != '-':
                try:
                    pbr_str = str(pbr_raw).strip().replace(' ', '').replace(',', '').replace('FCFA', '')
                    pbr_float = float(pbr_str) if pbr_str else prix_float
                except (ValueError, TypeError):
                    pbr_float = prix_float
            
            # PRISE EN CHARGE AMU (colonne G - index 6)
            prise_en_charge_amu_raw = a.get('prise_en_charge_amu') or a.get('PRISE_EN_CHARGE_AMU') or a.get('Prise_en_charge_amu')
            prise_en_charge_amu = True
            if prise_en_charge_amu_raw is not None and prise_en_charge_amu_raw != '':
                if isinstance(prise_en_charge_amu_raw, str):
                    prise_en_charge_amu = prise_en_charge_amu_raw.lower() in ['true', 'oui', 'yes', '1', 'vrai', 't']
                elif isinstance(prise_en_charge_amu_raw, bool):
                    prise_en_charge_amu = prise_en_charge_amu_raw
                else:
                    prise_en_charge_amu = True
            
            # COMMENTAIRE AMU (colonne H - index 7)
            commentaire_amu = a.get('commentaire_amu') or a.get('COMMENTAIRE_AMU') or a.get('Commentaire_amu') or ''
            
            # PRISE EN CHARGE CAC (colonne I - index 8)
            prise_en_charge_cac_raw = a.get('prise_en_charge_cac') or a.get('PRISE_EN_CHARGE_CAC') or a.get('Prise_en_charge_cac')
            prise_en_charge_cac = True
            if prise_en_charge_cac_raw is not None and prise_en_charge_cac_raw != '':
                if isinstance(prise_en_charge_cac_raw, str):
                    prise_en_charge_cac = prise_en_charge_cac_raw.lower() in ['true', 'oui', 'yes', '1', 'vrai', 't']
                elif isinstance(prise_en_charge_cac_raw, bool):
                    prise_en_charge_cac = prise_en_charge_cac_raw
                else:
                    prise_en_charge_cac = True
            
            # COMMENTAIRE CAC (colonne J - index 9)
            commentaire_cac = a.get('commentaire_cac') or a.get('COMMENTAIRE_CAC') or a.get('Commentaire_cac') or ''
            
            # 🔥🔥🔥 RÉCUPÉRER LE STATUT (colonne K - index 10) 🔥🔥🔥
            statut_raw = a.get('statut') or a.get('STATUT') or a.get('Statut') or 'direct'
            statut = 'direct'
            if statut_raw and statut_raw != '':
                statut = str(statut_raw).strip().upper()
                if statut not in ['EP', 'DIRECT']:
                    statut = 'direct'
            
            acte_nom = a.get('nom') or a.get('NOM') or a.get('Nom')
            if acte_nom and str(acte_nom).strip():
                result.append({
                    'id': a.get('ID') or a.get('id'),
                    'code': str(a.get('code', '') or ''),
                    'nom': str(acte_nom).strip(),
                    'prix': prix_float,
                    'pbr': pbr_float,
                    'description': str(a.get('description', '') or ''),
                    'prise_en_charge_amu': prise_en_charge_amu,
                    'commentaire_amu': str(commentaire_amu),
                    'prise_en_charge_cac': prise_en_charge_cac,
                    'commentaire_cac': str(commentaire_cac),
                    'statut': statut  # 🔥 NOUVEAU
                })
        
        return jsonify({
            'data': result,
            'total': total,
            'limit': limit,
            'offset': offset,
            'has_more': (offset + limit) < total
        })
        
    except Exception as e:
        print(f"❌ Erreur GET actes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'data': [], 'total': 0, 'error': str(e)}), 500

@app.route('/api/ventes/<int:vente_id>/annuler', methods=['POST'])
@login_required
def annuler_vente(vente_id):
    """Annuler une vente (admin uniquement)"""
    import json
    from datetime import datetime
    
    try:
        # Verifier que l'utilisateur est admin
        if not session.get('is_admin'):
            return jsonify({'success': False, 'error': 'Acces non autorise. Reserve a l administrateur.'}), 403
        
        data = request.json
        motif = data.get('motif', 'Annulation manuelle')
        structure_id = session.get('structure_id')
        user_id = session.get('user_id')
        user_name = session.get('user_name', 'Administrateur')
        
        # Recuperer la vente
        vente = db.execute_query("""
            SELECT * FROM ventes 
            WHERE id = %s AND structure_id = %s AND (statut = 'validee' OR statut IS NULL)
        """, (vente_id, structure_id))
        
        if not vente or len(vente) == 0:
            return jsonify({'success': False, 'error': 'Vente non trouvee ou deja annulee'}), 404
        
        v = vente[0] if isinstance(vente[0], dict) else vente[0]
        
        if isinstance(v, dict):
            vente_type = v.get('type')
            produits_data = v.get('produits')
            net_a_payer = float(v.get('net_a_payer', 0))
            sous_total = float(v.get('sous_total', 0))
        else:
            vente_type = v[3] if len(v) > 3 else None
            produits_data = v[12] if len(v) > 12 else None
            net_a_payer = float(v[6]) if len(v) > 6 else 0
            sous_total = float(v[4]) if len(v) > 4 else 0
        
        # ========== POUR LA PHARMACIE : RESTOCKER DANS SHEETS ==========
        if vente_type in ['pharma', 'pharmacie'] and produits_data:
            if isinstance(produits_data, str):
                produits_data = json.loads(produits_data)
            
            try:
                sheet_name = f"struct_{structure_id}_produits"
                worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
                
                for produit in produits_data:
                    produit_id = str(produit.get('id'))
                    quantite = int(produit.get('quantite', 0))
                    
                    if produit_id and quantite > 0:
                        cell = worksheet.find(produit_id, in_column=1)
                        if cell:
                            row_num = cell.row
                            current_row = worksheet.row_values(row_num)
                            stock_actuel = int(current_row[3]) if len(current_row) > 3 else 0
                            nouveau_stock = stock_actuel + quantite
                            worksheet.update_cell(row_num, 4, nouveau_stock)
                            print(f"📦 Restocké dans Sheets: {produit.get('nom')} +{quantite}")
            except Exception as e:
                print(f"⚠️ Erreur restock Sheets: {e}")
        
        # ========== POUR LES ACTES : PAS DE STOCK ==========
        
        # 🔥 ENREGISTRER L'ANNULATION DANS L'HISTORIQUE
        db.execute_query("""
            INSERT INTO annulations_ventes (
                vente_id, vente_type, motif, annule_par_id, annule_par_nom,
                ancien_net_a_payer, ancien_sous_total, data_avant, date_annulation
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            vente_id, vente_type, motif, user_id, user_name,
            net_a_payer, sous_total, json.dumps(v, default=str)
        ))
        
        # 🔥 Mettre à jour la recette (annuler)
        db.execute_query("""
            UPDATE recettes 
            SET est_annulation = TRUE, 
                description = CONCAT(description, ' [ANNULEE - ', %s, ']')
            WHERE source_id = %s 
            AND source_type IN ('vente_acte', 'vente_pharma') 
            AND structure_id = %s
        """, (motif, vente_id, structure_id))
        
        # 🔥 Marquer la vente comme annulée
        db.execute_query("""
            UPDATE ventes 
            SET statut = 'annulee', 
                annulee_le = NOW(), 
                annulee_par = %s,
                motif_annulation = %s
            WHERE id = %s AND structure_id = %s
        """, (user_id, motif, vente_id, structure_id))
        
        # 🔥 METTRE À JOUR LE SOLDE DE CAISSE (recalculer)
        recettes = db.execute_query("""
            SELECT COALESCE(SUM(montant), 0) as total 
            FROM recettes 
            WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)
        """, (structure_id,))
        
        depenses = db.execute_query("""
            SELECT COALESCE(SUM(montant), 0) as total 
            FROM depenses 
            WHERE structure_id = %s
        """, (structure_id,))
        
        total_recettes = recettes[0]['total'] if recettes else 0
        total_depenses = depenses[0]['total'] if depenses else 0
        nouveau_solde = total_recettes - total_depenses
        
        db.execute_query("""
            INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
            VALUES (%s, %s, NOW())
            ON CONFLICT (structure_id) DO UPDATE SET 
                solde_actuel = EXCLUDED.solde_actuel,
                date_mise_a_jour = NOW()
        """, (structure_id, nouveau_solde))
        
        print(f"✅ Vente {vente_id} ({vente_type}) annulee par {user_name}")
        print(f"💰 Nouveau solde: {nouveau_solde} FCFA")

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE : contre-passation de l'écriture ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_annulation_vente
            vente_orm = Vente.query.get(vente_id)
            annulation_orm = AnnulationVente.query.filter_by(vente_id=vente_id).order_by(AnnulationVente.id.desc()).first()
            if vente_orm and vente_orm.ecriture_id:
                ecriture_annul = generer_ecriture_annulation_vente(vente_orm, annulation_orm, user_nom=user_name)
                if ecriture_annul:
                    print(f"🧾 Écriture de contre-passation #{ecriture_annul.id} générée pour l'annulation de la vente #{vente_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture d'annulation (vente #{vente_id} conservée annulée): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='annulation_vente',
                description=f"Annulation vente #{vente_id} ({vente_type}) — {motif}",
                montant=net_a_payer, type_montant='debit',
                reference_type='vente', reference_id=vente_id,
                utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (annulation vente #{vente_id}): {e}")

        return jsonify({
            'success': True,
            'message': f'Vente #{vente_id} annulee avec succes',
            'type': vente_type,
            'nouveau_solde': nouveau_solde
        })
        
    except Exception as e:
        print(f"❌ Erreur annulation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/historique_annulations')
@login_required
def historique_annulations():
    """Page d'historique des annulations (admin uniquement)"""
    if not session.get('is_admin'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    structure_id = session.get('structure_id')
    
    annulations = db.execute_query("""
        SELECT 
            a.id,
            a.vente_id,
            a.vente_type,
            a.motif,
            a.annule_par_nom,
            a.ancien_net_a_payer,
            a.ancien_sous_total,
            a.date_annulation,
            v.patient_nom,
            v.date_vente as vente_date
        FROM annulations_ventes a
        LEFT JOIN ventes v ON a.vente_id = v.id
        WHERE v.structure_id = %s OR v.structure_id IS NULL
        ORDER BY a.date_annulation DESC
    """, (structure_id,))
    
    # Convertir les objets datetime en chaînes
    annulations_list = []
    for a in annulations:
        if isinstance(a, dict):
            date_annulation = a.get('date_annulation')
            if date_annulation and hasattr(date_annulation, 'strftime'):
                date_annulation_str = date_annulation.strftime('%Y-%m-%d %H:%M:%S')
            else:
                date_annulation_str = str(date_annulation) if date_annulation else ''
            
            annulations_list.append({
                'id': a.get('id'),
                'vente_id': a.get('vente_id'),
                'vente_type': a.get('vente_type'),
                'motif': a.get('motif'),
                'annule_par_nom': a.get('annule_par_nom'),
                'ancien_net_a_payer': a.get('ancien_net_a_payer'),
                'ancien_sous_total': a.get('ancien_sous_total'),
                'date_annulation': date_annulation_str,
                'patient_nom': a.get('patient_nom'),
                'vente_date': a.get('vente_date')
            })
        else:
            # Format tuple
            date_annulation = a[7] if len(a) > 7 else None
            if date_annulation and hasattr(date_annulation, 'strftime'):
                date_annulation_str = date_annulation.strftime('%Y-%m-%d %H:%M:%S')
            else:
                date_annulation_str = str(date_annulation) if date_annulation else ''
            
            annulations_list.append({
                'id': a[0],
                'vente_id': a[1],
                'vente_type': a[2],
                'motif': a[3],
                'annule_par_nom': a[4],
                'ancien_net_a_payer': a[5],
                'ancien_sous_total': a[6],
                'date_annulation': date_annulation_str,
                'patient_nom': a[8] if len(a) > 8 else None,
                'vente_date': a[9] if len(a) > 9 else None
            })
    
    return render_template('historique_annulations.html', annulations=annulations_list)

@app.route('/api/annulations')
@login_required
def api_get_annulations():
    """API pour récupérer les annulations (admin uniquement)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Non autorisé'}), 403
    
    structure_id = session.get('structure_id')
    
    annulations = db.execute_query("""
        SELECT 
            a.id,
            a.vente_id,
            a.vente_type,
            a.motif,
            a.annule_par_nom,
            a.ancien_net_a_payer,
            a.ancien_sous_total,
            a.date_annulation,
            v.patient_nom,
            v.date_vente as vente_date
        FROM annulations_ventes a
        LEFT JOIN ventes v ON a.vente_id = v.id
        WHERE v.structure_id = %s OR v.structure_id IS NULL
        ORDER BY a.date_annulation DESC
    """, (structure_id,))
    
    return jsonify(annulations)
# ========== GESTION FINANCIÈRE ==========

@app.route('/admin/finances')
@login_required
def admin_finances():
    """Page d'administration financière"""
    if not session.get('is_admin'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    structure_id = session.get('structure_id')
    
    # 🔥 Récupérer les recettes (exclure les annulations)
    recettes = db.execute_query("""
        SELECT * FROM recettes 
        WHERE structure_id = %s 
        AND (est_annulation IS NULL OR est_annulation = FALSE)
        ORDER BY date_recette DESC
    """, (structure_id,))
    
    # Récupérer les dépenses
    depenses = db.execute_query("""
        SELECT * FROM depenses 
        WHERE structure_id = %s 
        ORDER BY date_depense DESC
    """, (structure_id,))
    
    # Récupérer le solde de caisse
    caisse = db.execute_query("""
        SELECT * FROM caisse WHERE structure_id = %s
    """, (structure_id,))
    
    solde = caisse[0]['solde_actuel'] if caisse and len(caisse) > 0 else 0
    
    # 🔥 Calculer les totaux (exclure annulations)
    total_recettes = db.execute_query("""
        SELECT COALESCE(SUM(montant), 0) as total 
        FROM recettes 
        WHERE structure_id = %s 
        AND (est_annulation IS NULL OR est_annulation = FALSE)
    """, (structure_id,))
    total_recettes = total_recettes[0]['total'] if total_recettes else 0
    
    total_depenses = db.execute_query("""
        SELECT COALESCE(SUM(montant), 0) as total 
        FROM depenses 
        WHERE structure_id = %s
    """, (structure_id,))
    total_depenses = total_depenses[0]['total'] if total_depenses else 0
    
    return render_template('admin_finances.html', 
                         recettes=recettes,
                         depenses=depenses,
                         solde=solde,
                         total_recettes=total_recettes,
                         total_depenses=total_depenses)


# ========== API FINANCES ==========

@app.route('/api/finances/stats')
@login_required
def api_finances_stats():
    if not session.get('is_admin'):
        return jsonify({'error': 'Non autorise'}), 403
    
    try:
        structure_id = session.get('structure_id')
        date_debut = request.args.get('date_debut')
        date_fin = request.args.get('date_fin')
        
        # 🔥 Construction de la condition WHERE (exclure annulations)
        where_clause = "WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)"
        params = [structure_id]
        
        if date_debut and date_fin:
            date_debut_formatted = date_debut + " 00:00:00"
            date_fin_formatted = date_fin + " 23:59:59"
            where_clause += " AND date_recette BETWEEN %s AND %s"
            params.extend([date_debut_formatted, date_fin_formatted])
        
        # 🔥 Recettes (exclure annulations)
        recettes = db.execute_query(f"""
            SELECT COALESCE(SUM(montant), 0) as total
            FROM recettes 
            {where_clause}
        """, params)
        
        # Depenses
        params_dep = [structure_id]
        where_clause_dep = "WHERE structure_id = %s"
        if date_debut and date_fin:
            date_debut_formatted = date_debut + " 00:00:00"
            date_fin_formatted = date_fin + " 23:59:59"
            where_clause_dep += " AND date_depense BETWEEN %s AND %s"
            params_dep.extend([date_debut_formatted, date_fin_formatted])
        
        depenses = db.execute_query(f"""
            SELECT COALESCE(SUM(montant), 0) as total
            FROM depenses 
            {where_clause_dep}
        """, params_dep)
        
        # 🔥 Recettes par source (exclure annulations)
        recettes_par_source = db.execute_query(f"""
            SELECT source, COALESCE(SUM(montant), 0) as total
            FROM recettes 
            {where_clause}
            GROUP BY source
            ORDER BY total DESC
        """, params)
        
        # 🔥 Depenses par motif
        depenses_par_motif = db.execute_query(f"""
            SELECT 
                motif,
                COALESCE(SUM(montant), 0) as total
            FROM depenses 
            {where_clause_dep}
            GROUP BY motif
            ORDER BY total DESC
        """, params_dep)
        
        # 🔥 Traduire les motifs pour l'affichage
        motif_names = {
            'salaire': 'Salaires',
            'assurance': 'Assurances',
            'reparation': 'Reparations',
            'fourniture': 'Fournitures',
            'eau': 'Eau',
            'electricite': 'Electricite',
            'internet': 'Internet',
            'loyer': 'Loyer',
            'materiel': 'Materiel',
            'transport': 'Transport',
            'communication': 'Communication',
            'autres': 'Autres'
        }
        
        depenses_par_motif_list = []
        for d in depenses_par_motif:
            motif = d.get('motif')
            depenses_par_motif_list.append({
                'motif': motif,
                'motif_nom': motif_names.get(motif, motif),
                'total': d.get('total')
            })
        
        total_recettes = recettes[0]['total'] if recettes else 0
        total_depenses = depenses[0]['total'] if depenses else 0
        
        return jsonify({
            'total_recettes': total_recettes,
            'total_depenses': total_depenses,
            'solde': total_recettes - total_depenses,
            'recettes_par_source': recettes_par_source,
            'depenses_par_motif': depenses_par_motif_list
        })
        
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/finances/recettes/detail')
@login_required
def api_recettes_detail():
    if not session.get('is_admin'):
        return jsonify({'error': 'Non autorise'}), 403
    
    try:
        structure_id = session.get('structure_id')
        date_debut = request.args.get('date_debut')
        date_fin = request.args.get('date_fin')
        
        where_clause = "WHERE structure_id = %s AND (statut IS NULL OR statut != 'annulee')"
        params = [structure_id]
        
        if date_debut and date_fin:
            date_debut_formatted = date_debut + " 00:00:00"
            date_fin_formatted = date_fin + " 23:59:59"
            where_clause += " AND date_vente BETWEEN %s AND %s"
            params.extend([date_debut_formatted, date_fin_formatted])
        
        # ✅ CORRECTION : Utiliser net_a_payer
        query = f"""
            SELECT 
                type,
                COUNT(*) as nombre_ventes,
                COALESCE(SUM(net_a_payer), 0) as total_net,
                COALESCE(SUM(montant_donne), 0) as total_donne,
                COALESCE(SUM(rendu), 0) as total_rendu,
                COALESCE(SUM(reste_a_payer), 0) as total_reste
            FROM ventes 
            {where_clause}
            GROUP BY type
        """
        recettes = db.execute_query(query, params)
        
        return jsonify(recettes)
        
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify([]), 500

@app.route('/api/finances/depenses/motif')
@login_required
def api_finances_depenses_motif():
    """Depenses par motif"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Non autorise'}), 403
    
    try:
        structure_id = session.get('structure_id')
        date_debut = request.args.get('date_debut')
        date_fin = request.args.get('date_fin')
        
        where_clause = "WHERE structure_id = %s"
        params = [structure_id]
        
        if date_debut and date_fin:
            date_debut_formatted = date_debut + " 00:00:00"
            date_fin_formatted = date_fin + " 23:59:59"
            where_clause += " AND date_depense BETWEEN %s AND %s"
            params.extend([date_debut_formatted, date_fin_formatted])
        
        # 🔥 Depenses par motif avec traduction
        depenses = db.execute_query(f"""
            SELECT 
                motif,
                COALESCE(SUM(montant), 0) as total
            FROM depenses 
            {where_clause}
            GROUP BY motif
            ORDER BY total DESC
        """, params)
        
        # 🔥 Traduire les motifs pour l'affichage
        motif_names = {
            'salaire': 'Salaires',
            'assurance': 'Assurances',
            'reparation': 'Reparations',
            'fourniture': 'Fournitures',
            'eau': 'Eau',
            'electricite': 'Electricite',
            'internet': 'Internet',
            'loyer': 'Loyer',
            'materiel': 'Materiel',
            'transport': 'Transport',
            'communication': 'Communication',
            'autres': 'Autres'
        }
        
        result = []
        for d in depenses:
            motif = d.get('motif')
            result.append({
                'motif': motif,
                'motif_label': motif_names.get(motif, motif.capitalize() if motif else 'Autres'),
                'total': d.get('total')
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur api_finances_depenses_motif: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500

@app.route('/api/finances/recettes/source')
@login_required
def api_finances_recettes_source():
    """Recettes par source (patients, assurances, autres)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Non autorise'}), 403
    
    try:
        structure_id = session.get('structure_id')
        date_debut = request.args.get('date_debut')
        date_fin = request.args.get('date_fin')
        
        where_clause = "WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)"
        params = [structure_id]
        
        if date_debut and date_fin:
            date_debut_formatted = date_debut + " 00:00:00"
            date_fin_formatted = date_fin + " 23:59:59"
            where_clause += " AND date_recette BETWEEN %s AND %s"
            params.extend([date_debut_formatted, date_fin_formatted])
        
        # 🔥 Recettes par source
        query = f"""
            SELECT 
                source,
                COUNT(*) as nombre,
                COALESCE(SUM(montant), 0) as total
            FROM recettes 
            {where_clause}
            GROUP BY source
            ORDER BY total DESC
        """
        recettes = db.execute_query(query, params)
        
        # 🔥 Traduire les sources pour l'affichage
        source_names = {
            'patients': 'Patients',
            'assurance': 'Assurances',
            'autres': 'Autres'
        }
        
        result = []
        for r in recettes:
            source = r.get('source')
            result.append({
                'source': source,
                'source_label': source_names.get(source, source.capitalize() if source else 'Autres'),
                'nombre': r.get('nombre'),
                'total': r.get('total')
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur api_finances_recettes_source: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500

@app.route('/api/finances/depenses', methods=['POST'])
@login_required
def api_add_depense():
    """Ajouter une depense"""
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorise'}), 403
    
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'Admin')
        
        # 🔥 Verifier le solde suffisant (exclure annulations)
        recettes_total = db.execute_query("""
            SELECT COALESCE(SUM(montant), 0) as total
            FROM recettes 
            WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)
        """, (structure_id,))
        
        depenses_total = db.execute_query("""
            SELECT COALESCE(SUM(montant), 0) as total
            FROM depenses 
            WHERE structure_id = %s
        """, (structure_id,))
        
        solde = (recettes_total[0]['total'] if recettes_total else 0) - (depenses_total[0]['total'] if depenses_total else 0)
        montant = float(data.get('montant', 0))
        
        if montant > solde:
            return jsonify({'success': False, 'error': f'Solde insuffisant. Solde actuel: {int(solde)} FCFA'}), 400
        
        result = db.execute_query("""
            INSERT INTO depenses (structure_id, montant, motif, motif_personnalise, description, created_by_nom)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            structure_id,
            montant,
            data.get('motif'),
            data.get('motif_personnalise', ''),
            data.get('description', ''),
            user_name
        ))
        
        # 🔥 Mettre à jour le solde de caisse
        db.execute_query("""
            INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
            VALUES (%s, 
                (SELECT COALESCE(SUM(montant), 0) FROM recettes WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)) -
                (SELECT COALESCE(SUM(montant), 0) FROM depenses WHERE structure_id = %s),
                NOW())
            ON CONFLICT (structure_id) DO UPDATE SET
                solde_actuel = EXCLUDED.solde_actuel,
                date_mise_a_jour = NOW()
        """, (structure_id, structure_id, structure_id))

        depense_id = result[0]['id']

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_depense
            depense_orm = Depense.query.get(depense_id)
            if depense_orm:
                ecriture_dep = generer_ecriture_depense(depense_orm, user_nom=user_name)
                if ecriture_dep:
                    print(f"🧾 Écriture comptable #{ecriture_dep.id} générée pour la dépense #{depense_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (dépense #{depense_id} conservée): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='depense_enregistree',
                description=f"Dépense — {data.get('motif')}",
                montant=montant, type_montant='debit',
                reference_type='depense', reference_id=depense_id,
                utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (dépense #{depense_id}): {e}")

        return jsonify({'success': True, 'id': depense_id})

    except Exception as e:
        print(f"Erreur api_add_depense: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/finances/recettes', methods=['POST'])
@login_required
def api_add_recette():
    """Ajouter une recette (manuelle ou automatique)"""
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'Admin')
        
        montant = float(data.get('montant', 0))
        source = data.get('source', 'autres')
        description = data.get('description', '')
        
        if montant <= 0:
            return jsonify({'success': False, 'error': 'Montant invalide'}), 400
        
        # 🔥 Sources autorisées
        sources_autorisees = ['patients', 'assurance', 'autres']
        if source not in sources_autorisees:
            source = 'autres'
        
        # 🔥 Si source = assurance, ajouter des infos supplémentaires
        if source == 'assurance':
            assurance_nom = data.get('assurance_nom', '')
            if assurance_nom:
                description = f"{description} - {assurance_nom}".strip()
        
        result = db.execute_query("""
            INSERT INTO recettes (structure_id, montant, source, description, created_by_nom)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            structure_id,
            montant,
            source,
            description,
            user_name
        ))
        
        recette_id = result[0]['id']
        
        # 🔥 Mettre à jour le solde de caisse (exclure annulations)
        db.execute_query("""
            INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
            VALUES (%s, 
                (SELECT COALESCE(SUM(montant), 0) FROM recettes 
                 WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)) - 
                (SELECT COALESCE(SUM(montant), 0) FROM depenses WHERE structure_id = %s), 
                NOW())
            ON CONFLICT (structure_id) DO UPDATE SET
                solde_actuel = EXCLUDED.solde_actuel,
                date_mise_a_jour = NOW()
        """, (structure_id, structure_id, structure_id))

        print(f"✅ Recette #{recette_id} ajoutée: {montant} FCFA ({source}) - {user_name}")

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_recette_diverse
            recette_orm = Recette.query.get(recette_id)
            if recette_orm:
                ecriture_rec = generer_ecriture_recette_diverse(recette_orm, user_nom=user_name)
                if ecriture_rec:
                    print(f"🧾 Écriture comptable #{ecriture_rec.id} générée pour la recette #{recette_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (recette #{recette_id} conservée): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='recette_encaisee',
                description=f"Recette — {source} — {description}",
                montant=montant, type_montant='credit',
                reference_type='recette', reference_id=recette_id,
                utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (recette #{recette_id}): {e}")

        return jsonify({
            'success': True,
            'id': recette_id,
            'montant': montant,
            'source': source
        })
        
    except Exception as e:
        print(f"❌ Erreur api_add_recette: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/finances/sources')
@login_required
def api_finances_sources():
    """Récupérer les sources de recettes disponibles"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Non autorisé'}), 403
    
    sources = [
        {'id': 'patients', 'label': 'Patients'},
        {'id': 'assurance', 'label': 'Assurances'},
        {'id': 'autres', 'label': 'Autres'}
    ]
    return jsonify(sources)

@app.route('/statistiques_ventes')
@login_required
def statistiques_ventes():
    """Page des statistiques de ventes pour les employes"""
    if not session.get('is_admin'):
        flash('Accès non autorisé. Réservé à l\'administrateur.', 'danger')
        return redirect(url_for('dashboard'))
    
    structure_id = session.get('structure_id')
    
    # Recuperer toutes les ventes (y compris annulees pour les stats)
    ventes = db.execute_query("""
        SELECT 
            v.id,
            v.patient_nom,
            v.type,
            v.net_a_payer,
            v.montant_donne,
            v.reste_a_payer,
            v.base_remboursement,
            v.sous_total,
            v.taux_assurance,
            v.date_vente,
            v.mode_paiement,
            v.statut,
            v.created_by_nom as vendeur,
            v.actes,
            v.produits,
            v.assurance2_nom,
            v.taux_assurance2,
            v.prise_en_charge2
        FROM ventes v
        WHERE v.structure_id = %s
        ORDER BY v.date_vente DESC
    """, (structure_id,))
    
    return render_template('statistiques_ventes.html', ventes=ventes)

# ========== API ASSURANCES ==========
@app.route('/api/assurances/factures', methods=['POST'])
@login_required
def api_add_facture_assurance():
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorise'}), 403
    
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'Admin')
        
        result = db.execute_query("""
            INSERT INTO factures_assurance (
                structure_id, patient_nom, assurance, numero_assure,
                montant_facture, mois_reference, notes, created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            structure_id,
            data.get('patient_nom'),
            data.get('assurance'),
            data.get('numero_assure', ''),
            data.get('montant_facture'),
            data.get('mois_reference'),
            data.get('notes', ''),
            user_name
        ))
        
        return jsonify({'success': True, 'id': result[0]['id']})
        
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/assurances/factures/<int:facture_id>/paiement', methods=['POST'])
@login_required
def api_paiement_assurance(facture_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorise'}), 403
    
    try:
        data = request.json
        structure_id = session.get('structure_id')
        montant = float(data.get('montant', 0))
        date_remboursement = data.get('date_remboursement')

        # ⭐ Pièces justificatives obligatoires (traçabilité de l'encaissement)
        numero_reference_versement = (data.get('numero_reference_versement') or '').strip()
        date_versement = data.get('date_versement')
        if not numero_reference_versement or not date_versement:
            return jsonify({'success': False, 'error': "Le numéro de référence du versement et la date de versement sont obligatoires pour tracer l'encaissement."}), 400

        # Recuperer la facture
        facture = db.execute_query("""
            SELECT * FROM factures_assurance
            WHERE id = %s AND structure_id = %s
        """, (facture_id, structure_id))

        if not facture:
            return jsonify({'success': False, 'error': 'Facture non trouvee'}), 404

        f = facture[0]
        deja_rembourse = float(f.get('montant_rembourse', 0))
        nouveau_rembourse = deja_rembourse + montant
        total_facture = float(f.get('montant_facture', 0))

        if nouveau_rembourse > total_facture:
            return jsonify({'success': False, 'error': 'Montant depasse le solde restant'}), 400

        if nouveau_rembourse >= total_facture:
            statut = 'payee'
        else:
            statut = 'partielle'

        # Mettre a jour la facture
        db.execute_query("""
            UPDATE factures_assurance
            SET montant_rembourse = %s,
                statut = %s,
                date_remboursement = %s,
                numero_reference_versement = %s,
                date_versement = %s
            WHERE id = %s AND structure_id = %s
        """, (nouveau_rembourse, statut, date_remboursement,
              numero_reference_versement, date_versement, facture_id, structure_id))
        
        # Ajouter a la caisse (recette)
        db.execute_query("""
            INSERT INTO recettes (structure_id, montant, source, description, created_by_nom)
            VALUES (%s, %s, %s, %s, %s)
        """, (structure_id, montant, 'assurance', f'Remboursement assurance facture #{facture_id} - {f.get("patient_nom")}', session.get('user_name', 'Admin')))
        
        # Mettre a jour le solde de caisse
        db.execute_query("""
            INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
            VALUES (%s, 
                (SELECT COALESCE(SUM(montant), 0) FROM recettes WHERE structure_id = %s) -
                (SELECT COALESCE(SUM(montant), 0) FROM depenses WHERE structure_id = %s),
                NOW())
            ON CONFLICT (structure_id) DO UPDATE SET
                solde_actuel = EXCLUDED.solde_actuel,
                date_mise_a_jour = NOW()
        """, (structure_id, structure_id, structure_id))

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE : extinction de la créance assurance ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_remboursement_assurance
            ecriture_ass = generer_ecriture_remboursement_assurance(
                montant=montant,
                assurance_nom=f.get('assurance'),
                structure_id=structure_id,
                reference=f"Facture assurance #{facture_id} - {f.get('patient_nom')}",
                source_id=facture_id,
                user_nom=session.get('user_name', 'Admin'),
                numero_reference_versement=numero_reference_versement,
                date_versement=date_versement,
            )
            if ecriture_ass:
                print(f"🧾 Écriture comptable #{ecriture_ass.id} générée pour le remboursement assurance #{facture_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (remboursement assurance #{facture_id} conservé): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='paiement_assurance',
                description=f"Remboursement assurance {f.get('assurance')} — facture #{facture_id}",
                montant=montant, type_montant='credit',
                reference_type='facture_assurance', reference_id=facture_id,
                utilisateur_nom=session.get('user_name', 'Admin'),
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (remboursement assurance #{facture_id}): {e}")

        return jsonify({'success': True, 'message': 'Paiement enregistre'})

    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/assurances/generer_factures', methods=['POST'])
@login_required
def generer_factures_assurance():
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorise'}), 403
    
    try:
        import calendar
        import json
        from datetime import datetime
        from decimal import Decimal
        
        data = request.json
        structure_id = session.get('structure_id')
        mois_reference = data.get('mois_reference')
        
        if not mois_reference:
            return jsonify({'success': False, 'error': 'Mois reference requis'}), 400
        
        annee, mois = map(int, mois_reference.split('-'))
        date_debut = f"{annee}-{mois:02d}-01"
        dernier_jour = calendar.monthrange(annee, mois)[1]
        date_fin = f"{annee}-{mois:02d}-{dernier_jour}"
        
        print(f"Periode: du {date_debut} au {date_fin}")
        
        # 🔥 RECUPERER LES VENTES AVEC LES DEUX ASSURANCES
        ventes = db.execute_query("""
            SELECT
                v.id,
                v.patient_nom,
                v.sous_total,
                v.net_a_payer,
                v.taux_assurance,
                v.date_vente,
                v.assurance2_nom,
                v.taux_assurance2,
                v.prise_en_charge,
                v.prise_en_charge2,
                v.assurances,
                v.societe_assurance2,
                p.type_assurance as assurance_principale,
                p.assurance2_nom as assurance2_patient,
                p.societe_assurance2 as patient_societe_assurance2
            FROM ventes v
            LEFT JOIN patients p ON v.patient_id = p.id
            WHERE v.structure_id = %s
            AND v.date_vente >= %s
            AND v.date_vente <= %s
            AND (v.statut IS NULL OR v.statut != 'annulee')
            AND (
                (p.type_assurance IS NOT NULL AND p.type_assurance != 'non_assure')
                OR (p.assurance2_nom IS NOT NULL AND p.assurance2_nom != '')
                OR (v.assurance2_nom IS NOT NULL AND v.assurance2_nom != '')
            )
            ORDER BY p.type_assurance, p.assurance2_nom
        """, (structure_id, date_debut, date_fin))
        
        print(f"Ventes avec assurance trouvees: {len(ventes)}")
        
        if not ventes:
            return jsonify({'success': False, 'error': 'Aucune vente avec assurance pour cette periode'}), 400
        
        # 🔥 Regroupement par CLÉ = (assurance, société). La société n'est
        # pertinente que pour l'assurance complémentaire (contrat groupe
        # employeur) — la principale (AMU-CNSS/INAM) n'en a pas.
        factures_par_cle = {}

        for v in ventes:
            if isinstance(v, dict):
                # 🔥 Récupérer les infos des deux assurances
                assurance_principale = v.get('assurance_principale') or v.get('assurance')
                assurance2 = v.get('assurance2_nom') or v.get('assurance2_patient') or ''
                societe2 = v.get('societe_assurance2') or v.get('patient_societe_assurance2') or None

                # 🔥 Convertir les Decimal en float
                sous_total = float(v.get('sous_total') or 0)
                prise_en_charge = float(v.get('prise_en_charge') or 0)
                prise_en_charge2 = float(v.get('prise_en_charge2') or 0)

                # 🔥 SI L'ASSURANCE PRINCIPALE EST 'non_assure' OU NULL, ON L'IGNORE
                if assurance_principale and assurance_principale != 'non_assure':
                    cle = assurance_principale
                    if cle not in factures_par_cle:
                        factures_par_cle[cle] = {
                            'assurance': assurance_principale,
                            'societe': None,
                            'total': 0,
                            'ventes': [],
                            'type': 'principale'
                        }

                    if prise_en_charge > 0:
                        factures_par_cle[cle]['total'] += prise_en_charge
                        factures_par_cle[cle]['ventes'].append({
                            'id': v.get('id'),
                            'patient_nom': v.get('patient_nom'),
                            'montant_assurance': prise_en_charge,
                            'taux_assurance': float(v.get('taux_assurance', 0)),  # 🔥 Conversion
                            'date_vente': str(v.get('date_vente')),
                            'type': 'principale'
                        })

                # 🔥 SI L'ASSURANCE COMPLÉMENTAIRE EXISTE
                if assurance2 and assurance2 != '' and assurance2 != 'Aucune':
                    cle = f"{assurance2}||{societe2 or ''}"
                    if cle not in factures_par_cle:
                        factures_par_cle[cle] = {
                            'assurance': assurance2,
                            'societe': societe2,
                            'total': 0,
                            'ventes': [],
                            'type': 'complementaire'
                        }

                    if prise_en_charge2 > 0:
                        factures_par_cle[cle]['total'] += prise_en_charge2
                        factures_par_cle[cle]['ventes'].append({
                            'id': v.get('id'),
                            'patient_nom': v.get('patient_nom'),
                            'montant_assurance': prise_en_charge2,
                            'taux_assurance': float(v.get('taux_assurance2', 0)),  # 🔥 Conversion
                            'date_vente': str(v.get('date_vente')),
                            'type': 'complementaire'
                        })

        print(f"Factures a generer: {len(factures_par_cle)}")

        resultats = []

        for cle, data_assurance in factures_par_cle.items():
            if data_assurance['total'] == 0:
                continue

            assurance = data_assurance['assurance']
            societe = data_assurance['societe']

            # 🔥 VERIFIER SI UNE FACTURE EXISTE DEJA (assurance + société,
            # NULL-safe : deux NULL sont considérés égaux ici)
            existing = db.execute_query("""
                SELECT id, montant_rembourse
                FROM factures_assurance
                WHERE structure_id = %s AND mois_reference = %s AND assurance = %s
                AND (societe = %s OR (societe IS NULL AND %s IS NULL))
            """, (structure_id, mois_reference, assurance, societe, societe))

            if existing and len(existing) > 0:
                facture_id = existing[0]['id']
                deja_rembourse = float(existing[0]['montant_rembourse'] or 0)
                nouveau_total = data_assurance['total']
                type_assurance = data_assurance['type']

                if deja_rembourse >= nouveau_total:
                    nouveau_statut = 'payee'
                elif deja_rembourse > 0:
                    nouveau_statut = 'partielle'
                else:
                    nouveau_statut = 'en_attente'

                db.execute_query("""
                    UPDATE factures_assurance
                    SET montant_total = %s,
                        details = %s,
                        statut = %s,
                        type_assurance = %s,
                        societe = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (nouveau_total, json.dumps(data_assurance['ventes']), nouveau_statut, type_assurance, societe, facture_id))

                resultats.append({
                    'assurance': assurance,
                    'societe': societe,
                    'montant': nouveau_total,
                    'statut': 'mise_a_jour',
                    'reste': nouveau_total - deja_rembourse,
                    'type': type_assurance
                })
            else:
                result = db.execute_query("""
                    INSERT INTO factures_assurance (
                        structure_id,
                        mois_reference,
                        assurance,
                        montant_total,
                        details,
                        type_assurance,
                        societe,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id
                """, (structure_id, mois_reference, assurance, data_assurance['total'], json.dumps(data_assurance['ventes']), data_assurance['type'], societe))

                resultats.append({
                    'assurance': assurance,
                    'societe': societe,
                    'montant': data_assurance['total'],
                    'statut': 'nouvelle',
                    'id': result[0]['id'],
                    'type': data_assurance['type']
                })

        return jsonify({
            'success': True,
            'factures': resultats,
            'total_ventes': len(ventes),
            'total_factures': len(factures_par_cle)
        })
        
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/assurances/factures')
@login_required
def api_get_factures_assurance():
    try:
        structure_id = session.get('structure_id')
        mois = request.args.get('mois')
        
        # 🔥 AJOUTER LA COLONNE type_assurance
        query = """
            SELECT
                id,
                structure_id,
                mois_reference,
                assurance,
                montant_total,
                montant_rembourse,
                statut,
                details,
                type_assurance,
                created_at,
                date_remboursement,
                updated_at,
                societe,
                numero_reference_versement,
                date_versement
            FROM factures_assurance
            WHERE structure_id = %s
        """
        params = [structure_id]
        
        if mois:
            query += " AND mois_reference = %s"
            params.append(mois)
        
        query += " ORDER BY mois_reference DESC, assurance"
        
        factures = db.execute_query(query, params)
        
        # 🔥 FORMATER LES DONNÉES POUR L'AFFICHAGE
        result = []
        for f in factures:
            if isinstance(f, dict):
                # Récupérer le type d'assurance
                type_assurance = f.get('type_assurance', 'principale')
                assurance_name = f.get('assurance', '')
                
                # Ajouter un label pour le type
                type_label = 'Principale' if type_assurance == 'principale' else 'Complémentaire'
                
                result.append({
                    'id': f.get('id'),
                    'mois_reference': f.get('mois_reference'),
                    'assurance': assurance_name,
                    'societe': f.get('societe'),
                    'type_assurance': type_assurance,
                    'type_label': type_label,
                    'montant_total': float(f.get('montant_total', 0)),
                    'montant_rembourse': float(f.get('montant_rembourse', 0)),
                    'statut': f.get('statut', 'en_attente'),
                    'details': f.get('details', []),
                    'created_at': str(f.get('created_at')) if f.get('created_at') else None,
                    'date_remboursement': str(f.get('date_remboursement')) if f.get('date_remboursement') else None,
                    'updated_at': str(f.get('updated_at')) if f.get('updated_at') else None,
                    'numero_reference_versement': f.get('numero_reference_versement'),
                    'date_versement': str(f.get('date_versement')) if f.get('date_versement') else None
                })
            else:
                # Format tuple
                result.append({
                    'id': f[0],
                    'mois_reference': f[2] if len(f) > 2 else None,
                    'assurance': f[3] if len(f) > 3 else '',
                    'type_assurance': f[8] if len(f) > 8 else 'principale',
                    'type_label': 'Complémentaire' if (len(f) > 8 and f[8] == 'complementaire') else 'Principale',
                    'montant_total': float(f[4]) if len(f) > 4 and f[4] else 0,
                    'montant_rembourse': float(f[5]) if len(f) > 5 and f[5] else 0,
                    'statut': f[6] if len(f) > 6 else 'en_attente',
                    'details': f[7] if len(f) > 7 else [],
                    'created_at': str(f[9]) if len(f) > 9 and f[9] else None,
                    'date_remboursement': str(f[10]) if len(f) > 10 and f[10] else None,
                    'updated_at': str(f[11]) if len(f) > 11 and f[11] else None,
                    'societe': f[12] if len(f) > 12 else None,
                    'numero_reference_versement': f[13] if len(f) > 13 else None,
                    'date_versement': str(f[14]) if len(f) > 14 and f[14] else None
                })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500
@app.route('/api/factures/<int:facture_id>')
@login_required
def api_get_facture_detail(facture_id):
    """Récupérer les détails d'une facture avec historique des paiements"""
    try:
        structure_id = session.get('structure_id')
        
        # Récupérer la facture
        facture = db.execute_query("""
            SELECT * FROM factures 
            WHERE id = %s AND structure_id = %s
        """, (facture_id, structure_id))
        
        if not facture:
            return jsonify({'success': False, 'error': 'Facture non trouvée'}), 404
        
        f = facture[0]
        
        # Récupérer les paiements
        paiements = db.execute_query("""
            SELECT * FROM paiements_factures 
            WHERE facture_id = %s 
            ORDER BY date_paiement DESC
        """, (facture_id,))
        
        paiements_list = []
        for p in paiements:
            if isinstance(p, dict):
                paiements_list.append({
                    'id': p.get('id'),
                    'montant': float(p.get('montant', 0)),
                    'date_paiement': str(p.get('date_paiement')),
                    'mode_paiement': p.get('mode_paiement'),
                    'notes': p.get('notes'),
                    'created_by': p.get('created_by')
                })
            else:
                paiements_list.append({
                    'id': p[0],
                    'montant': float(p[1]) if len(p) > 1 else 0,
                    'date_paiement': str(p[2]) if len(p) > 2 else '',
                    'mode_paiement': p[3] if len(p) > 3 else '',
                    'notes': p[4] if len(p) > 4 else '',
                    'created_by': p[5] if len(p) > 5 else ''
                })
        
        if isinstance(f, dict):
            result = {
                'id': f.get('id'),
                'numero_facture': f.get('numero_facture'),
                'patient_nom': f.get('patient_nom'),
                'patient_telephone': f.get('patient_telephone'),
                'date_emission': str(f.get('date_emission')),
                'date_echeance': str(f.get('date_echeance')),
                'sous_total': float(f.get('sous_total', 0)),
                'taux_assurance': float(f.get('taux_assurance', 0)),
                'prise_en_charge': float(f.get('prise_en_charge', 0)),
                'taux_assurance2': float(f.get('taux_assurance2', 0)),
                'prise_en_charge2': float(f.get('prise_en_charge2', 0)),
                'net_a_payer': float(f.get('net_a_payer', 0)),
                'montant_paye': float(f.get('montant_paye', 0)),
                'reste_a_payer': float(f.get('reste_a_payer', 0)),
                'statut': f.get('statut'),
                'statut_label': get_statut_label(f.get('statut')),
                'articles': f.get('articles', []),
                'mode_paiement': f.get('mode_paiement'),
                'notes': f.get('notes'),
                'created_by': f.get('created_by'),
                'paiements': paiements_list
            }
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/assurances/factures/<int:facture_id>/payer', methods=['POST'])
@login_required
def payer_facture_assurance(facture_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorise'}), 403
    
    try:
        data = request.json
        structure_id = session.get('structure_id')
        montant = float(data.get('montant', 0))

        if montant <= 0:
            return jsonify({'success': False, 'error': 'Montant invalide'}), 400

        # ⭐ Pièces justificatives obligatoires (traçabilité de l'encaissement) :
        # numéro de référence du virement/versement + sa date. Légitime pour
        # pouvoir rapprocher chaque encaissement d'assurance avec le relevé
        # bancaire — demandé explicitement pour la comptabilité.
        numero_reference_versement = (data.get('numero_reference_versement') or '').strip()
        date_versement = data.get('date_versement')
        if not numero_reference_versement or not date_versement:
            return jsonify({'success': False, 'error': "Le numéro de référence du versement et la date de versement sont obligatoires pour tracer l'encaissement."}), 400

        # Recuperer la facture
        facture = db.execute_query("""
            SELECT * FROM factures_assurance
            WHERE id = %s AND structure_id = %s
        """, (facture_id, structure_id))

        if not facture or len(facture) == 0:
            return jsonify({'success': False, 'error': 'Facture non trouvee'}), 404

        f = facture[0]
        deja_rembourse = float(f.get('montant_rembourse', 0))
        total_facture = float(f.get('montant_total', 0))

        if montant > (total_facture - deja_rembourse):
            return jsonify({'success': False, 'error': f'Montant depasse le solde restant'}), 400

        nouveau_rembourse = deja_rembourse + montant

        if nouveau_rembourse >= total_facture:
            statut = 'payee'
        else:
            statut = 'partielle'

        # 1. Mettre a jour la facture
        db.execute_query("""
            UPDATE factures_assurance
            SET montant_rembourse = %s,
                statut = %s,
                date_remboursement = NOW(),
                numero_reference_versement = %s,
                date_versement = %s
            WHERE id = %s
        """, (nouveau_rembourse, statut, numero_reference_versement, date_versement, facture_id))
        
        # 2. Ajouter le remboursement dans les recettes (CAISSE)
        assurance_name = f.get('assurance')
        if assurance_name == 'amu_cnss':
            assurance_display = 'AMU-CNSS'
        elif assurance_name == 'amu_inam':
            assurance_display = 'AMU-INAM'
        else:
            assurance_display = assurance_name
        
        db.execute_query("""
            INSERT INTO recettes (structure_id, montant, source, description, created_by_nom)
            VALUES (%s, %s, 'assurance', %s, %s)
        """, (
            structure_id, 
            montant, 
            f'Remboursement assurance {assurance_display} - {f.get("mois_reference")}', 
            session.get('user_name', 'Admin')
        ))
        
        # 3. Mettre a jour le solde de la caisse
        # Recalculer le solde total = total_recettes - total_depenses
        db.execute_query("""
            INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
            VALUES (%s, 
                (SELECT COALESCE(SUM(montant), 0) FROM recettes WHERE structure_id = %s) -
                (SELECT COALESCE(SUM(montant), 0) FROM depenses WHERE structure_id = %s),
                NOW())
            ON CONFLICT (structure_id) DO UPDATE SET
                solde_actuel = EXCLUDED.solde_actuel,
                date_mise_a_jour = NOW()
        """, (structure_id, structure_id, structure_id))

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE : extinction de la créance assurance ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_remboursement_assurance
            ecriture_ass = generer_ecriture_remboursement_assurance(
                montant=montant,
                assurance_nom=assurance_name,
                structure_id=structure_id,
                reference=f"Facture assurance #{facture_id} - {f.get('mois_reference')}",
                source_id=facture_id,
                user_nom=session.get('user_name', 'Admin'),
                numero_reference_versement=numero_reference_versement,
                date_versement=date_versement,
            )
            if ecriture_ass:
                print(f"🧾 Écriture comptable #{ecriture_ass.id} générée pour le remboursement assurance #{facture_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (remboursement assurance #{facture_id} conservé): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='paiement_assurance',
                description=f"Remboursement assurance {assurance_display} — {f.get('mois_reference')}",
                montant=montant, type_montant='credit',
                reference_type='facture_assurance', reference_id=facture_id,
                utilisateur_nom=session.get('user_name', 'Admin'),
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (remboursement assurance #{facture_id}): {e}")

        return jsonify({
            'success': True,
            'message': f'Remboursement de {montant} FCFA enregistre',
            'reste': total_facture - nouveau_rembourse
        })

    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def calculer_age(date_naissance):
    """Calcule l'âge à partir d'une date de naissance"""
    if not date_naissance:
        return None
    today = date.today()
    age = today.year - date_naissance.year
    if (today.month, today.day) < (date_naissance.month, date_naissance.day):
        age -= 1
    return age

@app.route('/api/finances/recettes/source')
@login_required
def api_recettes_source():
    if not session.get('is_admin'):
        return jsonify({'error': 'Non autorise'}), 403
    
    try:
        structure_id = session.get('structure_id')
        date_debut = request.args.get('date_debut')
        date_fin = request.args.get('date_fin')
        
        where_clause = "WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)"
        params = [structure_id]
        
        if date_debut and date_fin:
            date_debut_formatted = date_debut + " 00:00:00"
            date_fin_formatted = date_fin + " 23:59:59"
            where_clause += " AND date_recette BETWEEN %s AND %s"
            params.extend([date_debut_formatted, date_fin_formatted])
        
        # 🔥 Recettes par source
        query = f"""
            SELECT 
                source,
                source_type,
                COUNT(*) as nombre,
                COALESCE(SUM(montant), 0) as total
            FROM recettes 
            {where_clause}
            GROUP BY source, source_type
            ORDER BY source, source_type
        """
        recettes = db.execute_query(query, params)
        
        return jsonify(recettes)
        
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify([]), 500

# ============================================
# ROUTES PROFORMA AVEC DOUBLE ASSURANCE
# ============================================

@app.route('/proformas')
@login_required
def proformas():
    """Liste des proformas de la structure"""
    structure_id = session.get('structure_id')
    
    # Récupérer toutes les proformas avec les données d'assurance
    proformas = db.execute_query("""
        SELECT 
            p.*,
            CASE 
                WHEN p.statut = 'en_attente' THEN 'En attente'
                WHEN p.statut = 'accepte' THEN 'Acceptée'
                WHEN p.statut = 'refuse' THEN 'Refusée'
                WHEN p.statut = 'converti_en_vente' THEN 'Convertie en vente'
                WHEN p.statut = 'expire' THEN 'Expirée'
                ELSE p.statut
            END as statut_label
        FROM proformas p
        WHERE p.structure_id = %s
        ORDER BY p.created_at DESC
    """, (structure_id,))
    
    # Statistiques
    stats = db.execute_query("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN statut = 'en_attente' THEN 1 END) as en_attente,
            COUNT(CASE WHEN statut = 'accepte' THEN 1 END) as acceptees,
            COUNT(CASE WHEN statut = 'converti_en_vente' THEN 1 END) as converties,
            COALESCE(SUM(CASE WHEN statut IN ('en_attente', 'accepte') THEN net_a_payer ELSE 0 END), 0) as total_montant
        FROM proformas
        WHERE structure_id = %s
    """, (structure_id,))
    
    stats = stats[0] if stats else {'total': 0, 'en_attente': 0, 'acceptees': 0, 'converties': 0, 'total_montant': 0}
    
    # Récupérer les actes et produits depuis Google Sheets
    actes = sheets_helper.get_all_records('actes')
    produits = sheets_helper.get_all_records('produits')
    
    # Filtrer par structure
    actes_filtres = [a for a in actes if str(a.get('structure_id')) == str(structure_id)]
    produits_filtres = [p for p in produits if str(p.get('structure_id')) == str(structure_id)]
    
    return render_template('proformas/proformas.html', 
                         proformas=proformas,
                         stats=stats,
                         actes=actes_filtres,
                         produits=produits_filtres)


@app.route('/api/proformas', methods=['POST'])
@login_required
def api_creer_proforma():
    """Créer une nouvelle proforma avec double assurance et PBR"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        print("=" * 60)
        print("📄 CRÉATION PROFORMA")
        print(f"Patient: {data.get('patient_nom')}")
        print(f"Articles: {len(data.get('articles', []))}")
        print(f"Assurance principale: {data.get('assurance_nom')} ({data.get('taux_assurance')}%)")
        print(f"Assurance complémentaire: {data.get('assurance2_nom')} ({data.get('taux_assurance2')}%) - Active: {data.get('assurance2_active', False)}")
        if data.get('taux_modifie', False):
            print(f"   ⚠️ Taux modifié: {data.get('taux_assurance2')}% (original: {data.get('taux_original')}%)")
        print("=" * 60)
        
        # 🔥 Récupérer les articles
        articles = data.get('articles', [])
        
        # 🔥🔥🔥 CORRECTION : Convertir les valeurs de prise en charge 🔥🔥🔥
        for article in articles:
            # Conversion de prise_en_charge_amu
            amu_val = article.get('prise_en_charge_amu', True)
            if isinstance(amu_val, str):
                amu_val = amu_val.lower() == 'true'
            elif isinstance(amu_val, bool):
                amu_val = amu_val
            else:
                amu_val = True
            article['prise_en_charge_amu'] = amu_val
            
            # Conversion de prise_en_charge_cac
            cac_val = article.get('prise_en_charge_cac', True)
            if isinstance(cac_val, str):
                cac_val = cac_val.lower() == 'true'
            elif isinstance(cac_val, bool):
                cac_val = cac_val
            else:
                cac_val = True
            article['prise_en_charge_cac'] = cac_val
            
            print(f"🔍 {article.get('nom')}: AMU={amu_val}, CAC={cac_val}")
        
        # 🔥 Calculer les totaux avec PBR
        sous_total = 0
        pbr_total_amu = 0
        sous_total_amu = 0
        base_cac_articles = 0  # 🔥 Base CAC calculée article par article
        
        taux_assurance = float(data.get('taux_assurance', 0))
        
        for article in articles:
            prix = float(article.get('prix', article.get('prix_unitaire', 0)))
            pbr = float(article.get('pbr', prix))
            quantite = float(article.get('quantite', 1))
            total = prix * quantite
            
            article['total'] = total
            article['prix'] = prix
            article['pbr'] = pbr
            sous_total += total
            
            prise_amu = article.get('prise_en_charge_amu', True)
            prise_cac = article.get('prise_en_charge_cac', True)
            
            # 🔥 AMU
            if prise_amu and pbr > 0:
                sous_total_amu += total
                pbr_total_amu += min(prix, pbr) * quantite
            
            # 🔥🔥🔥 CAC article par article 🔥🔥🔥
            if prise_cac:
                if prise_amu and pbr > 0 and taux_assurance > 0:
                    # 🔥 Article avec AMU → CAC sur le reste après AMU
                    base_amu_article = min(prix, pbr) * quantite
                    prise_amu_article = (base_amu_article * taux_assurance) / 100
                    reste = total - prise_amu_article
                    if reste > 0:
                        base_cac_articles += reste
                else:
                    # 🔥 Article sans AMU → CAC sur le prix total
                    base_cac_articles += total
                
                print(f"🔍 {article.get('nom')}: Base CAC={base_cac_articles}")
        
        # 🔥 Vérifier si tous les articles sont non pris en charge
        tout_non_pris = all(
            a.get('prise_en_charge_amu') == False and a.get('prise_en_charge_cac') == False
            for a in articles
        )
        
        print(f"📊 Tout non pris en charge: {tout_non_pris}")
        print(f"📊 Base CAC calculée: {base_cac_articles}")
        
        # 🔥 Vérifier si le patient a une assurance principale
        assurance_nom = data.get('assurance_nom', 'Non assuré')
        est_assure = assurance_nom and assurance_nom != 'Non assuré'
        
        # 🔥 Calcul de l'AMU
        prise_en_charge = 0
        base_remboursement = 0
        
        if est_assure and taux_assurance > 0:
            base_remboursement = min(sous_total_amu, pbr_total_amu)
            if base_remboursement > 0:
                prise_en_charge = (base_remboursement * taux_assurance) / 100
        
        # 🔥 Reste après AMU (pour le calcul global)
        reste_apres_principal = sous_total - prise_en_charge
        
        # 🔥🔥🔥 ASSURANCE COMPLÉMENTAIRE (CAC) - Utilise base_cac_articles 🔥🔥🔥
        assurance2_active = data.get('assurance2_active', False)
        assurance2_nom = data.get('assurance2_nom', '')
        taux_assurance2 = float(data.get('taux_assurance2', 0)) if assurance2_active else 0
        prise_en_charge2 = 0
        
        if assurance2_active and taux_assurance2 > 0 and base_cac_articles > 0:
            prise_en_charge2 = base_cac_articles * (taux_assurance2 / 100)
            print(f"📊 CAC appliquée sur base: {base_cac_articles} x {taux_assurance2}% = {prise_en_charge2} FCFA")
        
        # 🔥 TAUX MODIFIÉ
        taux_modifie = data.get('taux_modifie', False)
        taux_original = float(data.get('taux_original', 0))
        
        # 🔥 Net à payer
        if tout_non_pris:
            net_a_payer = sous_total
            prise_en_charge = 0
            prise_en_charge2 = 0
            print("📊 Tout non pris en charge → patient paye la totalité")
        else:
            net_a_payer = sous_total - prise_en_charge - prise_en_charge2
            if net_a_payer < 0:
                net_a_payer = 0
        
        print(f"📊 Sous-total clinique: {sous_total} FCFA")
        print(f"📊 Base remboursement (PBR): {base_remboursement} FCFA")
        print(f"📊 Prise en charge AMU: {prise_en_charge} FCFA")
        print(f"📊 Base CAC: {base_cac_articles} FCFA")
        print(f"📊 Prise en charge {assurance2_nom}: {prise_en_charge2} FCFA")
        print(f"📊 Net à payer: {net_a_payer} FCFA")
        
        expires_at = datetime.now() + timedelta(days=7)
        
        # Récupérer le prochain numéro
        next_numero = db.execute_query("""
            SELECT COALESCE(MAX(numero_proforma), 0) + 1 as next_num
            FROM proformas 
            WHERE structure_id = %s
        """, (structure_id,))
        
        prochain_numero = next_numero[0]['next_num'] if next_numero else 1
        print(f"   Numéro proforma: {prochain_numero}")
        
        # 🔥 CONSTRUIRE L'OBJET ASSURANCES
        assurances_data = {
            'principale': {
                'nom': assurance_nom,
                'taux': taux_assurance,
                'montant_prise_en_charge': prise_en_charge,
                'base_remboursement': base_remboursement
            },
            'complementaire': {
                'nom': assurance2_nom if assurance2_active else '',
                'taux': taux_assurance2 if assurance2_active else 0,
                'montant_prise_en_charge': prise_en_charge2 if assurance2_active else 0,
                'active': assurance2_active,
                'taux_modifie': taux_modifie,
                'taux_original': taux_original
            } if assurance2_active and assurance2_nom else None
        }
        
        # Insérer la proforma
        result = db.execute_query("""
            INSERT INTO proformas (
                structure_id, 
                patient_id, 
                patient_nom, 
                patient_telephone,
                assurance_nom,
                taux_assurance,
                numero_assure,
                assurance2_nom,
                taux_assurance2,
                numero_assure2,
                assurance2_active,
                taux_modifie,
                taux_original,
                type, 
                articles, 
                sous_total, 
                prise_en_charge, 
                prise_en_charge2,
                net_a_payer,
                base_remboursement,
                notes,
                created_by,
                expires_at,
                numero_proforma,
                assurances_data,
                base_cac
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING id
        """, (
            structure_id,
            data.get('patient_id'),
            data.get('patient_nom'),
            data.get('patient_telephone', ''),
            assurance_nom,
            taux_assurance,
            data.get('numero_assure', ''),
            assurance2_nom if assurance2_active else '',
            taux_assurance2 if assurance2_active else 0,
            data.get('numero_assure2', ''),
            assurance2_active,
            taux_modifie,
            taux_original,
            data.get('type', 'mixte'),
            json.dumps(articles, ensure_ascii=False),
            sous_total,
            prise_en_charge,
            prise_en_charge2,
            net_a_payer,
            base_remboursement,
            data.get('notes', ''),
            user_name,
            expires_at,
            prochain_numero,
            json.dumps(assurances_data, ensure_ascii=False),
            base_cac_articles  # 🔥 NOUVEAU
        ))
        
        proforma_id = result[0]['id']
        
        print(f"✅ Proforma #{proforma_id} créée (Numéro: {prochain_numero})")
        
        return jsonify({
            'success': True,
            'id': proforma_id,
            'numero': prochain_numero,
            'net_a_payer': net_a_payer,
            'sous_total': sous_total,
            'prise_en_charge': prise_en_charge,
            'prise_en_charge2': prise_en_charge2,
            'base_remboursement': base_remboursement,
            'base_cac': base_cac_articles,  # 🔥 NOUVEAU
            'assurance2_nom': assurance2_nom if assurance2_active else '',
            'taux_assurance2': taux_assurance2 if assurance2_active else 0,
            'taux_modifie': taux_modifie,
            'taux_original': taux_original
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/proformas/<int:proforma_id>/statut', methods=['PUT'])
@login_required
def api_changer_statut_proforma(proforma_id):
    """Changer le statut d'une proforma"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        nouveau_statut = data.get('statut')
        
        if nouveau_statut not in ['en_attente', 'accepte', 'refuse', 'converti_en_vente', 'expire']:
            return jsonify({'success': False, 'error': 'Statut invalide'}), 400
        
        db.execute_query("""
            UPDATE proformas 
            SET statut = %s, updated_at = NOW()
            WHERE id = %s AND structure_id = %s
        """, (nouveau_statut, proforma_id, structure_id))
        
        return jsonify({
            'success': True,
            'message': f'Statut mis à jour vers {nouveau_statut}'
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/proforma/<int:proforma_id>/print')
@login_required
def proforma_print(proforma_id):
    """Imprimer une proforma avec double assurance et PBR"""
    import json
    
    structure_id = session.get('structure_id')
    
    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('proformas'))
    
    # Récupérer la proforma avec toutes les données
    proforma = db.execute_query("""
        SELECT * FROM proformas 
        WHERE id = %s AND structure_id = %s
    """, (proforma_id, structure_id))
    
    if not proforma:
        flash('Proforma non trouvée', 'danger')
        return redirect(url_for('proformas'))
    
    proforma = proforma[0]
    
    # Récupérer les infos de la structure depuis Google Sheets
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    # ⭐ Récupérer l'adresse brute et la formater
    adresse_brute = structure_info.get('adresse', '')
    adresse_formatee = sheets_helper.format_adresse(adresse_brute)
    
    # ⭐ Mettre à jour la structure avec l'adresse formatée
    structure_info['adresse'] = adresse_formatee
    
    # Récupérer le logo
    logo_url = structure_info.get('logo_url', '')
    
    # 🔥 Récupérer les données d'assurance
    assurances_data = proforma.get('assurances_data', {})
    if isinstance(assurances_data, str):
        try:
            assurances_data = json.loads(assurances_data)
        except:
            assurances_data = {}
    
    assurance2_nom = proforma.get('assurance2_nom', '')
    taux_assurance2 = float(proforma.get('taux_assurance2', 0))
    assurance2_active = proforma.get('assurance2_active', False)
    taux_modifie = proforma.get('taux_modifie', False)
    taux_original = float(proforma.get('taux_original', 0))
    prise_en_charge2 = float(proforma.get('prise_en_charge2', 0))
    
    # 🔥🔥🔥 CALCUL DU PBR TOTAL ET DE LA BASE REMBOURSEMENT 🔥🔥🔥
    articles = proforma.get('articles', [])
    if isinstance(articles, str):
        try:
            articles = json.loads(articles)
        except:
            articles = []
    
    sous_total = 0
    pbr_total = 0
    sous_total_amu = 0
    pbr_total_amu = 0
    
    for a in articles:
        prix = float(a.get('prix_unitaire', a.get('prix', 0)))
        pbr = float(a.get('pbr', prix))
        quantite = int(a.get('quantite', 1))
        total = prix * quantite
        
        sous_total += total
        pbr_total += min(prix, pbr) * quantite
        
        # 🔥 Si l'article est pris en charge par AMU
        prise_amu = a.get('prise_en_charge_amu', True)
        if prise_amu:
            sous_total_amu += total
            pbr_total_amu += min(prix, pbr) * quantite
    
    # 🔥 Base de remboursement = min(sous_total_amu, pbr_total_amu)
    base_remboursement = min(sous_total_amu, pbr_total_amu)
    
    # 🔥 Taux d'assurance principale
    taux_assurance = float(proforma.get('taux_assurance', 0))
    prise_en_charge = 0
    if base_remboursement > 0 and taux_assurance > 0:
        prise_en_charge = (base_remboursement * taux_assurance) / 100
    
    # 🔥 Vérifier si l'assurance principale est active
    assurance_nom = proforma.get('assurance_nom', 'Non assuré')
    est_assure = assurance_nom and assurance_nom != 'Non assuré' and taux_assurance > 0
    
    print(f"📄 Impression proforma #{proforma_id}")
    print(f"   Patient: {proforma.get('patient_nom')}")
    print(f"   Sous-total: {sous_total} FCFA")
    print(f"   PBR total: {pbr_total} FCFA")
    print(f"   Base remboursement: {base_remboursement} FCFA")
    print(f"   Assurance principale: {assurance_nom} ({taux_assurance}%) - {'Active' if est_assure else 'Inactive'}")
    print(f"   Prise en charge AMU: {prise_en_charge} FCFA")
    print(f"   Assurance2 active: {assurance2_active}")
    print(f"   Assurance2 nom: {assurance2_nom}")
    print(f"   Taux assurance2: {taux_assurance2}%")
    if taux_modifie:
        print(f"   ⚠️ Taux modifié: {taux_assurance2}% (original: {taux_original}%)")
    
    return render_template('proformas/proforma_print.html', 
                         proforma=proforma,
                         structure=structure_info,  # ⭐ Adresse formatée
                         logo_url=logo_url,
                         # 🔥 DONNÉES ASSURANCE COMPLÉMENTAIRE
                         assurance2_nom=assurance2_nom,
                         taux_assurance2=taux_assurance2,
                         prise_en_charge2=prise_en_charge2,
                         assurance2_active=assurance2_active,
                         taux_modifie=taux_modifie,
                         taux_original=taux_original,
                         assurances_data=assurances_data,
                         # 🔥 NOUVEAUX CHAMPS
                         base_remboursement=base_remboursement,
                         prise_en_charge=prise_en_charge,
                         taux_assurance=taux_assurance,
                         sous_total=sous_total,
                         est_assure=est_assure,
                         assurance_nom=assurance_nom)


@app.route('/api/proformas/convertir', methods=['POST'])
@login_required
def api_convertir_proforma():
    """Convertir une proforma en vente avec PBR"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvée'}), 400
        
        proforma_id = data.get('proforma_id')
        if not proforma_id:
            return jsonify({'success': False, 'error': 'ID proforma manquant'}), 400
        
        # Vérifier que la proforma existe
        proforma = db.execute_query("""
            SELECT * FROM proformas 
            WHERE id = %s AND structure_id = %s AND statut IN ('en_attente', 'accepte')
        """, (proforma_id, structure_id))
        
        if not proforma:
            return jsonify({'success': False, 'error': 'Proforma non trouvée ou déjà convertie'}), 404
        
        proforma = proforma[0]
        
        # 🔥 Récupérer les articles
        articles = data.get('articles', [])
        
        # 🔥🔥🔥 CORRECTION : Convertir les valeurs de prise en charge 🔥🔥🔥
        for a in articles:
            # Conversion de prise_en_charge_amu
            amu_val = a.get('prise_en_charge_amu', True)
            if isinstance(amu_val, str):
                amu_val = amu_val.lower() == 'true'
            elif isinstance(amu_val, bool):
                amu_val = amu_val
            else:
                amu_val = True
            a['prise_en_charge_amu'] = amu_val
            
            # Conversion de prise_en_charge_cac
            cac_val = a.get('prise_en_charge_cac', True)
            if isinstance(cac_val, str):
                cac_val = cac_val.lower() == 'true'
            elif isinstance(cac_val, bool):
                cac_val = cac_val
            else:
                cac_val = True
            a['prise_en_charge_cac'] = cac_val
            
            print(f"🔍 {a.get('nom')}: AMU={amu_val}, CAC={cac_val}")

        # 🔥 Récupérer les données d'assurance de la proforma
        assurance_nom = proforma.get('assurance_nom', 'Non assuré')
        est_assure = assurance_nom and assurance_nom != 'Non assuré'
        taux_assurance = float(proforma.get('taux_assurance', 0))
        
        assurance2_active = proforma.get('assurance2_active', False)
        assurance2_nom = proforma.get('assurance2_nom', '')
        taux_assurance2 = float(proforma.get('taux_assurance2', 0))

        # 🔥 Société souscriptrice de l'assurance complémentaire : la proforma
        # ne porte pas ce champ (créée avant son existence éventuelle), on la
        # relit donc depuis la fiche patient au moment de la conversion.
        societe_assurance2 = None
        if assurance2_nom:
            pat_societe = db.execute_query(
                "SELECT societe_assurance2 FROM patients WHERE id = %s AND structure_id = %s",
                (proforma.get('patient_id'), structure_id)
            )
            if pat_societe:
                societe_assurance2 = pat_societe[0].get('societe_assurance2')

        # 🔥🔥🔥 RECALCULER LES TOTAUX AVEC PBR 🔥🔥🔥
        sous_total = 0
        pbr_total_amu = 0
        sous_total_amu = 0
        montant_non_amu = 0
        base_cac = 0
        
        articles_transformes = []
        for a in articles:
            prix = float(a.get('prix', a.get('prix_unitaire', 0)))
            pbr = float(a.get('pbr', prix))
            quantite = int(a.get('quantite', 1))
            total = prix * quantite
            
            sous_total += total
            
            # 🔥 Utiliser les valeurs converties
            prise_amu = a.get('prise_en_charge_amu', True)
            prise_cac = a.get('prise_en_charge_cac', True)
            
            # 🔥 Transformer l'article pour la vente
            article = {
                'id': a.get('id', None),
                'nom': a.get('nom', 'Article'),
                'prix': prix,
                'prix_unitaire': prix,
                'pbr': pbr,
                'quantite': quantite,
                'total': total,
                'prise_en_charge_amu': prise_amu,
                'prise_en_charge_cac': prise_cac,
                'type': a.get('type', 'acte')
            }
            
            # 🔥 AMU
            if prise_amu and pbr > 0:
                sous_total_amu += total
                pbr_total_amu += min(prix, pbr) * quantite
            else:
                montant_non_amu += total
            
            # 🔥 CAC article par article
            if prise_cac:
                if prise_amu and pbr > 0:
                    base_amu = min(prix, pbr) * quantite
                    prise_amu_article = (base_amu * taux_assurance) / 100
                    reste = total - prise_amu_article
                    if reste > 0:
                        base_cac += reste
                else:
                    base_cac += total
            
            articles_transformes.append(article)
        

        # 🔥 Séparer actes et produits
        actes_data = [a for a in articles_transformes if a.get('type') != 'produit']
        produits_data = [a for a in articles_transformes if a.get('type') == 'produit']
        
        # ⭐ Ajouter prix_reel pour les produits
        for p in produits_data:
            p['prix_reel'] = p['prix']
        
        # 🔥 Déterminer le type de vente
        types = set(a.get('type', 'acte') for a in articles_transformes)
        type_vente = 'mixte' if len(types) > 1 else ('pharmacie' if 'produit' in types else 'actes')
        
        
        # 🔥🔥🔥 AMU 🔥🔥🔥
        prise_en_charge = 0
        base_remboursement = 0
        
        if est_assure and taux_assurance > 0:
            base_remboursement = min(sous_total_amu, pbr_total_amu)
            if base_remboursement > 0:
                prise_en_charge = (base_remboursement * taux_assurance) / 100
        
        # 🔥🔥🔥 CAC 🔥🔥🔥
        prise_en_charge2 = 0
        if assurance2_active and taux_assurance2 > 0 and base_cac > 0:
            prise_en_charge2 = (base_cac * taux_assurance2) / 100
        
        # 🔥 Net à payer
        net_a_payer = sous_total - prise_en_charge - prise_en_charge2
        if net_a_payer < 0:
            net_a_payer = 0
        
        print(f"📊 Conversion proforma #{proforma_id}")
        print(f"   Sous-total: {sous_total} FCFA")
        print(f"   Base remboursement (PBR): {base_remboursement} FCFA")
        print(f"   AMU ({taux_assurance}%): {prise_en_charge} FCFA")
        print(f"   Base CAC: {base_cac} FCFA")
        if assurance2_active:
            print(f"   CAC {assurance2_nom} ({taux_assurance2}%): {prise_en_charge2} FCFA")
        print(f"   Net à payer: {net_a_payer} FCFA")
        
        # 🔥 Récupérer les données de paiement
        montant_donne = float(data.get('montant_donne', 0))
        
        # 🔥 Calcul du rendu
        rendu = 0
        reste_a_payer = 0
        if montant_donne > net_a_payer:
            rendu = montant_donne - net_a_payer
        elif montant_donne < net_a_payer:
            reste_a_payer = net_a_payer - montant_donne
        
        import json
        
        # 🔥 Insérer la vente
        result = db.execute_query("""
            INSERT INTO ventes (
                patient_id, patient_nom, structure_id, type, sous_total, 
                prise_en_charge, net_a_payer, mode_paiement, taux_assurance,
                date_vente, actes, produits, created_by_nom, statut,
                assurance2_nom, taux_assurance2, societe_assurance2, prise_en_charge2,
                montant_donne, rendu, reste_a_payer,
                assurance_principale_active, proforma_id,
                base_remboursement,
                taux_aide, aide_hospitaliere
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s::jsonb, %s::jsonb, %s, 'validee', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data.get('patient_id'),
            data.get('patient_nom', 'Patient'),
            structure_id,
            type_vente,
            sous_total,
            prise_en_charge,
            net_a_payer,
            data.get('mode_paiement', 'especes'),
            taux_assurance,
            json.dumps(actes_data, ensure_ascii=False) if actes_data else '[]',
            json.dumps(produits_data, ensure_ascii=False) if produits_data else '[]',
            user_name,
            assurance2_nom if assurance2_active else '',
            taux_assurance2 if assurance2_active else 0,
            societe_assurance2 if assurance2_active else None,
            prise_en_charge2,
            montant_donne,
            rendu,
            reste_a_payer,
            data.get('assurance_principale_active', True),
            proforma_id,
            base_remboursement,
            0,  # taux_aide
            0   # aide_hospitaliere
        ))

        if not result or len(result) == 0:
            return jsonify({'success': False, 'error': 'Erreur insertion vente'}), 500

        vente_id = result[0]['id']
        print(f"✅ Vente créée depuis proforma #{proforma_id} avec ID: {vente_id}")
        if assurance2_active:
            upsert_societe_assurance(structure_id, assurance2_nom, societe_assurance2)
        
        # Marquer la proforma comme convertie
        db.execute_query("""
            UPDATE proformas 
            SET statut = 'converti_en_vente', updated_at = NOW() 
            WHERE id = %s
        """, (proforma_id,))
        
        # 🔥 Ajouter la recette patient
        montant_effectif = montant_donne - rendu
        if montant_effectif > 0:
            db.execute_query("""
                INSERT INTO recettes (structure_id, montant, source, source_id, source_type, description, created_by_nom, date_recette)
                VALUES (%s, %s, 'patients', %s, 'vente_proforma', %s, %s, NOW())
            """, (structure_id, montant_effectif, vente_id, f'Vente depuis proforma #{proforma_id} - {data.get("patient_nom", "Patient")} - Encaissé: {montant_effectif} FCFA', user_name))
            print(f"✅ Recette patient ajoutée: {montant_effectif} FCFA")
        
        # 🔥 Si reste à payer > 0, créer une facture
        if reste_a_payer > 0:
            date_echeance = datetime.now() + timedelta(days=7)
            
            numero_facture = f"FAC-{datetime.now().strftime('%Y%m%d')}-{vente_id}"
            
            db.execute_query("""
                INSERT INTO factures (
                    structure_id, 
                    vente_id, 
                    patient_id, 
                    patient_nom, 
                    patient_telephone,
                    numero_facture,
                    sous_total, 
                    net_a_payer, 
                    montant_paye, 
                    reste_a_payer,
                    taux_assurance,
                    prise_en_charge,
                    taux_assurance2,
                    prise_en_charge2,
                    base_remboursement,
                    date_echeance, 
                    statut, 
                    mode_paiement,
                    notes, 
                    created_by,
                    articles
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'en_attente', %s, %s, %s, %s::jsonb)
            """, (
                structure_id,
                vente_id,
                data.get('patient_id'),
                data.get('patient_nom', 'Patient'),
                data.get('patient_telephone', ''),
                numero_facture,
                sous_total,
                net_a_payer,
                montant_effectif,
                reste_a_payer,
                taux_assurance,
                prise_en_charge,
                taux_assurance2,
                prise_en_charge2,
                base_remboursement,
                date_echeance,
                data.get('mode_paiement', 'especes'),
                f'Facture depuis proforma #{proforma_id} - Reste à payer: {reste_a_payer} FCFA',
                user_name,
                json.dumps(articles_transformes, ensure_ascii=False)
            ))
            print(f"📋 Facture créée pour le reste à payer: {reste_a_payer} FCFA")
        
        # ========== 🔥🔥🔥 METTRE À JOUR LE STOCK (UNIQUEMENT POUR LES PRODUITS) 🔥🔥🔥 ==========
        try:
            sheet_name = f"struct_{structure_id}_produits"
            print(f"   📂 Accès à la feuille: {sheet_name}")
            
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
            
            # 🔥 Filtrer uniquement les produits
            produits_vendus = [a for a in articles_transformes if a.get('type') == 'produit' and a.get('id')]
            
            if produits_vendus:
                print(f"📦 {len(produits_vendus)} produit(s) à mettre à jour dans le stock")
                
                for article in produits_vendus:
                    produit_id = str(article.get('id'))
                    quantite_vendue = int(article.get('quantite', 0))
                    produit_nom = article.get('nom', 'Inconnu')
                    
                    print(f"   🔍 Recherche du produit ID: {produit_id} - {produit_nom}")
                    
                    # Chercher le produit dans la feuille
                    cell = worksheet.find(produit_id, in_column=1)
                    if cell:
                        row_num = cell.row
                        current_row = worksheet.row_values(row_num)
                        # Stock est en colonne F (index 5)
                        stock_actuel = int(current_row[5]) if len(current_row) > 5 else 0
                        nouveau_stock = stock_actuel - quantite_vendue
                        
                        if nouveau_stock < 0:
                            print(f"   ⚠️ Stock négatif! {produit_nom}: {stock_actuel} - {quantite_vendue} = {nouveau_stock}")
                            nouveau_stock = 0
                        
                        print(f"   📊 Stock: {stock_actuel} → {nouveau_stock}")
                        worksheet.update_cell(row_num, 6, nouveau_stock)  # Colonne F = index 6
                        print(f"   ✅ Stock Sheets mis à jour pour {produit_nom}")
                    else:
                        print(f"   ❌ Produit ID {produit_id} non trouvé dans Sheets!")
            else:
                print("ℹ️ Aucun produit à mettre à jour (seulement des actes)")
                    
        except Exception as e:
            print(f"   ❌ ERREUR mise à jour stock Sheets: {e}")
            import traceback
            traceback.print_exc()
        
        # 🔥 Mettre à jour le solde de caisse
        try:
            recettes_total = db.execute_query("""
                SELECT COALESCE(SUM(montant), 0) as total 
                FROM recettes 
                WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)
            """, (structure_id,))
            
            depenses_total = db.execute_query("""
                SELECT COALESCE(SUM(montant), 0) as total 
                FROM depenses 
                WHERE structure_id = %s
            """, (structure_id,))
            
            total_recettes = recettes_total[0]['total'] if recettes_total else 0
            total_depenses = depenses_total[0]['total'] if depenses_total else 0
            nouveau_solde = total_recettes - total_depenses
            
            db.execute_query("""
                INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
                VALUES (%s, %s, NOW())
                ON CONFLICT (structure_id) DO UPDATE SET 
                    solde_actuel = EXCLUDED.solde_actuel,
                    date_mise_a_jour = NOW()
            """, (structure_id, nouveau_solde))
            
            print(f"💰 Solde de caisse mis à jour: {nouveau_solde} FCFA")

        except Exception as e:
            print(f"⚠️ Erreur mise à jour solde: {e}")

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE (écriture SYSCOHADA validée) ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_vente
            vente_orm = Vente.query.get(vente_id)
            if vente_orm:
                ecriture = generer_ecriture_vente(vente_orm, user_nom=user_name)
                if ecriture:
                    print(f"🧾 Écriture comptable #{ecriture.id} générée pour la vente (proforma #{proforma_id}) #{vente_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (vente proforma #{vente_id} conservée): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            categorie_journal = 'vente_pharmacie' if type_vente == 'pharmacie' else 'vente_actes'
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie=categorie_journal,
                description=f"Vente #{vente_id} depuis proforma #{proforma_id}",
                montant=montant_effectif, type_montant='credit',
                reference_type='vente', reference_id=vente_id,
                patient_id=data.get('patient_id'), patient_nom=data.get('patient_nom', 'Patient'),
                utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (vente proforma #{vente_id}): {e}")

        return jsonify({
            'success': True,
            'vente_id': vente_id,
            'type': type_vente,
            'net_a_payer': net_a_payer,
            'montant_donne': montant_donne,
            'rendu': rendu,
            'reste_a_payer': reste_a_payer,
            'message': 'Proforma convertie en vente avec succès'
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/proformas/count')
@login_required
def api_proformas_count():
    """Retourne le nombre de proformas en attente"""
    try:
        structure_id = session.get('structure_id')
        
        result = db.execute_query("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN statut = 'en_attente' THEN 1 END) as en_attente
            FROM proformas
            WHERE structure_id = %s
        """, (structure_id,))
        
        if result:
            return jsonify({
                'total': result[0]['total'],
                'en_attente': result[0]['en_attente']
            })
        return jsonify({'total': 0, 'en_attente': 0})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'total': 0, 'en_attente': 0})

@app.route('/api/proformas/<int:proforma_id>', methods=['GET'])
@login_required
def api_get_proforma(proforma_id):
    """Récupère une proforma par son ID"""
    try:
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'error': 'Structure non trouvée'}), 400
        
        # Récupérer la proforma
        result = db.execute_query("""
            SELECT * FROM proformas 
            WHERE id = %s AND structure_id = %s
        """, (proforma_id, structure_id))
        
        if not result or len(result) == 0:
            return jsonify({'error': 'Proforma non trouvée'}), 404
        
        proforma = result[0]
        
        # Convertir les champs JSON
        if proforma.get('articles') and isinstance(proforma.get('articles'), str):
            import json
            proforma['articles'] = json.loads(proforma['articles'])
        
        if proforma.get('assurances_data') and isinstance(proforma.get('assurances_data'), str):
            import json
            proforma['assurances_data'] = json.loads(proforma['assurances_data'])
        
        return jsonify(proforma)
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/proformas/<int:proforma_id>', methods=['PUT'])
@login_required
def api_update_proforma(proforma_id):
    """Met à jour une proforma"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        if not structure_id:
            return jsonify({'success': False, 'error': 'Structure non trouvée'}), 400
        
        # Vérifier que la proforma existe
        check = db.execute_query("""
            SELECT id, statut FROM proformas 
            WHERE id = %s AND structure_id = %s
        """, (proforma_id, structure_id))
        
        if not check or len(check) == 0:
            return jsonify({'success': False, 'error': 'Proforma non trouvée'}), 404
        
        # 🔥 Vérifier si la proforma est modifiable (en attente)
        if check[0]['statut'] != 'en_attente':
            return jsonify({'success': False, 'error': 'Seules les proformas en attente peuvent être modifiées'}), 400
        
        # Récupérer les données
        articles = data.get('articles', [])
        sous_total = 0
        for item in articles:
            sous_total += item.get('prix_unitaire', 0) * item.get('quantite', 0)
        
        assurance_nom = data.get('assurance_nom', 'Non assuré')
        taux_assurance = float(data.get('taux_assurance', 0))
        numero_assure = data.get('numero_assure', '')
        
        assurance2_active = data.get('assurance2_active', False)
        assurance2_nom = data.get('assurance2_nom', '')
        taux_assurance2 = float(data.get('taux_assurance2', 0))
        
        # Recalculer les prises en charge
        prise_en_charge = (sous_total * taux_assurance) / 100 if taux_assurance > 0 else 0
        reste_apres_principal = sous_total - prise_en_charge
        
        prise_en_charge2 = 0
        if assurance2_active and taux_assurance2 > 0 and reste_apres_principal > 0:
            prise_en_charge2 = (reste_apres_principal * taux_assurance2) / 100
        
        net_a_payer = sous_total - prise_en_charge - prise_en_charge2
        if net_a_payer < 0:
            net_a_payer = 0
        
        # 🔥 Mise à jour
        db.execute_query("""
            UPDATE proformas 
            SET 
                assurance_nom = %s,
                taux_assurance = %s,
                numero_assure = %s,
                assurance2_nom = %s,
                taux_assurance2 = %s,
                assurance2_active = %s,
                articles = %s::jsonb,
                sous_total = %s,
                prise_en_charge = %s,
                prise_en_charge2 = %s,
                net_a_payer = %s,
                notes = %s,
                updated_at = NOW()
            WHERE id = %s AND structure_id = %s
        """, (
            assurance_nom,
            taux_assurance,
            numero_assure,
            assurance2_nom,
            taux_assurance2,
            assurance2_active,
            json.dumps(articles, ensure_ascii=False),
            sous_total,
            prise_en_charge,
            prise_en_charge2,
            net_a_payer,
            data.get('notes', ''),
            proforma_id,
            structure_id
        ))
        
        print(f"✅ Proforma #{proforma_id} mise à jour par {user_name}")
        
        return jsonify({
            'success': True,
            'id': proforma_id,
            'net_a_payer': net_a_payer
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/consultation')
@login_required
def consultation():
    """Page de consultation et prise en charge - Réservé aux admins, médecins et paramédicaux"""
    # Vérifier les droits
    if not session.get('is_admin') and session.get('role') not in ['medecin', 'paramedical']:
        flash('Accès non autorisé. Réservé au personnel médical.', 'danger')
        return redirect(url_for('dashboard'))
    
    return render_template('consultation.html')

@app.route('/api/assurances/stats')
@login_required
def api_assurances_stats():
    """Récupérer les statistiques des assurances"""
    try:
        structure_id = session.get('structure_id')
        
        # Total prise en charge assurance principale
        principale = db.execute_query("""
            SELECT COALESCE(SUM(prise_en_charge), 0) as total
            FROM ventes 
            WHERE structure_id = %s 
            AND (statut IS NULL OR statut != 'annulee')
            AND prise_en_charge > 0
        """, (structure_id,))
        
        # Total prise en charge assurance complementaire
        complementaire = db.execute_query("""
            SELECT COALESCE(SUM(prise_en_charge2), 0) as total
            FROM ventes 
            WHERE structure_id = %s 
            AND (statut IS NULL OR statut != 'annulee')
            AND prise_en_charge2 > 0
        """, (structure_id,))
        
        total_principale = principale[0]['total'] if principale else 0
        total_complementaire = complementaire[0]['total'] if complementaire else 0
        
        return jsonify({
            'total_prise_en_charge': total_principale,
            'total_prise_en_charge2': total_complementaire
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'total_prise_en_charge': 0, 'total_prise_en_charge2': 0}), 500
# ============================================
# ROUTES FACTURES AVEC PAIEMENTS PARTIELS
# ============================================

@app.route('/factures')
@login_required
def factures():
    """Page de gestion des factures"""
    # 🔥 Vérifier les droits
    role = session.get('role', 'caissier')
    if role not in ['admin', 'comptable', 'gestionnaire', 'caissier', 'pharmacien']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    structure_id = session.get('structure_id')
    
    # Récupérer les statistiques
    stats = db.execute_query("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN statut = 'en_attente' THEN 1 END) as en_attente,
            COUNT(CASE WHEN statut = 'partielle' THEN 1 END) as partielles,
            COUNT(CASE WHEN statut = 'payee' THEN 1 END) as payees,
            COUNT(CASE WHEN statut = 'en_retard' THEN 1 END) as en_retard,
            COALESCE(SUM(reste_a_payer), 0) as total_restant
        FROM factures 
        WHERE structure_id = %s AND statut != 'annulee'
    """, (structure_id,))
    
    stats_result = stats[0] if stats else {
        'total': 0, 'en_attente': 0, 'partielles': 0, 
        'payees': 0, 'en_retard': 0, 'total_restant': 0
    }
    
    return render_template('factures/factures.html', stats=stats_result)


@app.route('/facture/detail/<int:facture_id>')
@login_required
def facture_detail(facture_id):
    """Page de détail d'une facture"""
    if not session.get('is_admin'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    structure_id = session.get('structure_id')
    
    # Récupérer la facture
    facture = db.execute_query("""
        SELECT * FROM factures 
        WHERE id = %s AND structure_id = %s
    """, (facture_id, structure_id))
    
    if not facture:
        flash('Facture non trouvée', 'danger')
        return redirect(url_for('factures'))
    
    f = facture[0]
    
    # Récupérer les paiements
    paiements = db.execute_query("""
        SELECT * FROM paiements_factures 
        WHERE facture_id = %s 
        ORDER BY date_paiement DESC
    """, (facture_id,))
    
    # 🔥 DÉFINIR LES LABELS DES STATUTS
    statut_labels = {
        'en_attente': 'En attente',
        'partielle': 'Paiement partiel',
        'payee': 'Payée',
        'en_retard': 'En retard',
        'impayee': 'Impayée',
        'annulee': 'Annulée'
    }
    
    # 🔥 DÉFINIR LES COULEURS DES STATUTS
    statut_colors = {
        'en_attente': 'warning',
        'partielle': 'info',
        'payee': 'success',
        'en_retard': 'danger',
        'impayee': 'dark',
        'annulee': 'secondary'
    }
    
    # 🔥 AJOUTER LE LIBELLÉ DU STATUT À L'OBJET FACTURE
    if isinstance(f, dict):
        f['statut_label'] = statut_labels.get(f.get('statut'), f.get('statut'))
        f['statut_color'] = statut_colors.get(f.get('statut'), 'secondary')

        # Société souscriptrice de l'assurance complémentaire : reprise
        # depuis la vente d'origine (source de vérité), sinon depuis la
        # fiche patient si la vente ne l'a pas (facture antérieure à ce champ).
        f['societe_assurance2'] = None
        if f.get('vente_id'):
            v_societe = db.execute_query(
                "SELECT societe_assurance2 FROM ventes WHERE id = %s", (f.get('vente_id'),)
            )
            if v_societe:
                f['societe_assurance2'] = v_societe[0].get('societe_assurance2')
        if not f.get('societe_assurance2'):
            p_societe = db.execute_query(
                "SELECT societe_assurance2 FROM patients WHERE id = %s AND structure_id = %s",
                (f.get('patient_id'), structure_id)
            )
            if p_societe:
                f['societe_assurance2'] = p_societe[0].get('societe_assurance2')

    return render_template('factures/facture_detail.html',
                         facture=f,
                         paiements=paiements,
                         statut_labels=statut_labels,
                         statut_colors=statut_colors)

@app.route('/facture/print/<int:facture_id>')
@login_required
def facture_print(facture_id):
    """Imprimer une facture"""
    from datetime import datetime
    import json
    
    structure_id = session.get('structure_id')
    
    # Récupérer la facture
    facture = db.execute_query("""
        SELECT * FROM factures 
        WHERE id = %s AND structure_id = %s
    """, (facture_id, structure_id))
    
    if not facture:
        flash('Facture non trouvée', 'danger')
        return redirect(url_for('factures'))
    
    f = facture[0]
    
    # Récupérer les infos de la structure
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    # Récupérer les articles
    articles = f.get('articles', [])
    if isinstance(articles, str):
        try:
            articles = json.loads(articles)
        except:
            articles = []
    
    # Récupérer les paiements
    paiements = db.execute_query("""
        SELECT * FROM paiements_factures 
        WHERE facture_id = %s 
        ORDER BY date_paiement
    """, (facture_id,))
    
    paiements_list = []
    for p in paiements:
        if isinstance(p, dict):
            paiements_list.append({
                'date': str(p.get('date_paiement')),
                'montant': float(p.get('montant', 0)),
                'mode': p.get('mode_paiement'),
                'notes': p.get('notes', '')
            })
        else:
            paiements_list.append({
                'date': str(p[2]) if len(p) > 2 else '',
                'montant': float(p[1]) if len(p) > 1 else 0,
                'mode': p[3] if len(p) > 3 else '',
                'notes': p[4] if len(p) > 4 else ''
            })

    # Société souscriptrice de l'assurance complémentaire (voir facture_detail)
    if isinstance(f, dict):
        f['societe_assurance2'] = None
        if f.get('vente_id'):
            v_societe = db.execute_query(
                "SELECT societe_assurance2 FROM ventes WHERE id = %s", (f.get('vente_id'),)
            )
            if v_societe:
                f['societe_assurance2'] = v_societe[0].get('societe_assurance2')
        if not f.get('societe_assurance2'):
            p_societe = db.execute_query(
                "SELECT societe_assurance2 FROM patients WHERE id = %s AND structure_id = %s",
                (f.get('patient_id'), structure_id)
            )
            if p_societe:
                f['societe_assurance2'] = p_societe[0].get('societe_assurance2')

    return render_template('factures/facture_print.html',
                         facture=f,
                         articles=articles,
                         paiements=paiements_list,
                         structure=structure_info,
                         date_actuelle=datetime.now().strftime('%d/%m/%Y %H:%M'))


@app.route('/facture/recu_paiement/<int:paiement_id>')
@login_required
def recu_paiement(paiement_id):
    """Imprimer un reçu de paiement (partiel ou total)"""
    from datetime import datetime
    import json
    
    structure_id = session.get('structure_id')
    
    # Récupérer le paiement et la facture associée
    paiement = db.execute_query("""
        SELECT p.*, 
               f.numero_facture, f.patient_nom, f.patient_telephone,
               f.net_a_payer, f.reste_a_payer, f.montant_paye, f.articles,
               f.sous_total, f.taux_assurance, f.prise_en_charge,
               f.prise_en_charge2, f.taux_assurance2
        FROM paiements_factures p
        JOIN factures f ON p.facture_id = f.id
        WHERE p.id = %s AND f.structure_id = %s
    """, (paiement_id, structure_id))
    
    if not paiement:
        flash('Paiement non trouvé', 'danger')
        return redirect(url_for('factures'))
    
    p = paiement[0]
    
    # Récupérer les infos de la structure
    structures = sheets_helper.get_all_records('structures', use_prefix=False)
    structure_info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    
    if isinstance(p, dict):
        paiement_data = {
            'id': p.get('id'),
            'montant': float(p.get('montant', 0)),
            'date_paiement': str(p.get('date_paiement')),
            'mode_paiement': p.get('mode_paiement'),
            'notes': p.get('notes'),
            'numero_facture': p.get('numero_facture'),
            'patient_nom': p.get('patient_nom'),
            'patient_telephone': p.get('patient_telephone'),
            'net_a_payer': float(p.get('net_a_payer', 0)),
            'reste_a_payer': float(p.get('reste_a_payer', 0)),
            'montant_total_paye': float(p.get('montant_paye', 0)),
            'sous_total': float(p.get('sous_total', 0)),
            'taux_assurance': float(p.get('taux_assurance', 0)),
            'prise_en_charge': float(p.get('prise_en_charge', 0)),
            'taux_assurance2': float(p.get('taux_assurance2', 0)),
            'prise_en_charge2': float(p.get('prise_en_charge2', 0)),
            'articles': json.loads(p.get('articles')) if isinstance(p.get('articles'), str) else p.get('articles', [])
        }
    else:
        paiement_data = {
            'id': p[0],
            'montant': float(p[1]) if len(p) > 1 else 0,
            'date_paiement': str(p[2]) if len(p) > 2 else '',
            'mode_paiement': p[3] if len(p) > 3 else '',
            'notes': p[4] if len(p) > 4 else '',
            'numero_facture': p[6] if len(p) > 6 else '',
            'patient_nom': p[7] if len(p) > 7 else '',
            'patient_telephone': p[8] if len(p) > 8 else '',
            'net_a_payer': float(p[9]) if len(p) > 9 else 0,
            'reste_a_payer': float(p[10]) if len(p) > 10 else 0,
            'montant_total_paye': float(p[11]) if len(p) > 11 else 0,
            'sous_total': float(p[12]) if len(p) > 12 else 0,
            'taux_assurance': float(p[13]) if len(p) > 13 else 0,
            'prise_en_charge': float(p[14]) if len(p) > 14 else 0,
            'taux_assurance2': float(p[15]) if len(p) > 15 else 0,
            'prise_en_charge2': float(p[16]) if len(p) > 16 else 0,
            'articles': json.loads(p[17]) if len(p) > 17 and p[17] else []
        }
    
    return render_template('factures/recu_paiement.html',
                         paiement=paiement_data,
                         structure=structure_info,
                         date_actuelle=datetime.now().strftime('%d/%m/%Y %H:%M'))


# ============================================
# API ROUTES FACTURES
# ============================================

@app.route('/api/factures/from_vente/<int:vente_id>', methods=['POST'])
@login_required
def api_creer_facture_from_vente(vente_id):
    """Créer une facture à partir d'une vente"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        date_echeance = data.get('date_echeance')
        mode_paiement = data.get('mode_paiement', 'especes')
        
        # Récupérer la vente
        vente = db.execute_query("""
            SELECT * FROM ventes 
            WHERE id = %s AND structure_id = %s
        """, (vente_id, structure_id))
        
        if not vente:
            return jsonify({'success': False, 'error': 'Vente non trouvée'}), 404
        
        v = vente[0]
        
        # Générer le numéro de facture
        numero = db.execute_query("""
            SELECT COUNT(*) as total FROM factures WHERE structure_id = %s
        """, (structure_id,))
        
        count = numero[0]['total'] if numero else 0
        numero_facture = f"F{structure_id}-{count+1:04d}"
        
        # Récupérer le patient
        patient = db.execute_query("""
            SELECT nom, prenom, telephone FROM patients WHERE id = %s
        """, (v.get('patient_id'),))
        
        patient_nom = 'Patient'
        patient_telephone = ''
        if patient:
            p = patient[0]
            if isinstance(p, dict):
                patient_nom = f"{p.get('nom', '')} {p.get('prenom', '')}".strip()
                patient_telephone = p.get('telephone', '')
            else:
                patient_nom = f"{p[0]} {p[1]}".strip() if len(p) > 1 else 'Patient'
                patient_telephone = p[2] if len(p) > 2 else ''
        
        # Récupérer les articles
        articles = []
        if isinstance(v, dict):
            if v.get('type') == 'actes' and v.get('actes'):
                articles = json.loads(v.get('actes')) if isinstance(v.get('actes'), str) else v.get('actes')
            elif v.get('type') in ['pharma', 'pharmacie'] and v.get('produits'):
                articles = json.loads(v.get('produits')) if isinstance(v.get('produits'), str) else v.get('produits')
        
        net_a_payer = float(v.get('net_a_payer', 0))

        # ⭐ FIX : ne pas ignorer ce que le patient a déjà réglé au moment de
        # la vente (montant_donne - rendu), sinon la dette est comptée deux
        # fois (bug historique : montant_paye était toujours mis à 0 ici).
        montant_deja_encaisse = float(v.get('montant_donne', 0) or 0) - float(v.get('rendu', 0) or 0)
        montant_deja_encaisse = max(0.0, min(montant_deja_encaisse, net_a_payer))
        reste_a_payer_initial = round(net_a_payer - montant_deja_encaisse, 2)
        statut_initial = 'payee' if reste_a_payer_initial <= 0 else ('partielle' if montant_deja_encaisse > 0 else 'en_attente')

        # Créer la facture
        result = db.execute_query("""
            INSERT INTO factures (
                structure_id, patient_id, patient_nom, patient_telephone,
                numero_facture, date_emission, date_echeance,
                sous_total, taux_assurance, prise_en_charge,
                taux_assurance2, prise_en_charge2,
                net_a_payer, montant_paye, reste_a_payer, statut,
                articles, mode_paiement, notes, created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            structure_id,
            v.get('patient_id'),
            patient_nom,
            patient_telephone,
            numero_facture,
            datetime.now().date(),
            date_echeance,
            float(v.get('sous_total', 0)),
            float(v.get('taux_assurance', 0)),
            float(v.get('prise_en_charge', 0)),
            float(v.get('taux_assurance2', 0)),
            float(v.get('prise_en_charge2', 0)),
            net_a_payer,
            montant_deja_encaisse,
            reste_a_payer_initial,
            statut_initial,
            json.dumps(articles, ensure_ascii=False),
            mode_paiement,
            data.get('notes', 'Facture issue de la vente #' + str(vente_id)),
            user_name
        ))
        
        facture_id = result[0]['id']

        # Mettre à jour le statut de la vente
        db.execute_query("""
            UPDATE ventes SET statut = 'facturee' WHERE id = %s
        """, (vente_id,))

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='facture_emise',
                description=f"Facture {numero_facture} émise (vente #{vente_id})",
                montant=net_a_payer, type_montant='neutre',
                reference_type='facture', reference_id=facture_id,
                patient_nom=patient_nom, utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (facture #{facture_id}): {e}")

        return jsonify({
            'success': True,
            'facture_id': facture_id,
            'numero_facture': numero_facture,
            'net_a_payer': net_a_payer
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/factures', methods=['GET'])
@login_required
def api_get_factures():
    """Récupérer toutes les factures de la structure"""
    try:
        structure_id = session.get('structure_id')
        statut = request.args.get('statut')
        
        # 🔥 Spécifier explicitement les colonnes au lieu de SELECT *
        query = """
            SELECT 
                f.id,
                f.structure_id,
                f.patient_id,
                f.patient_nom,
                f.patient_telephone,
                f.numero_facture,
                f.date_emission,
                f.date_echeance,
                f.sous_total,
                f.taux_assurance,
                f.prise_en_charge,
                f.taux_assurance2,
                f.prise_en_charge2,
                f.net_a_payer,
                f.montant_paye,
                f.reste_a_payer,
                f.statut,
                f.articles,
                f.mode_paiement,
                f.notes,
                f.created_by,
                f.created_at,
                f.updated_at,
                f.base_remboursement,
                f.assurances_data,
                f.vente_id,
                COALESCE(p.total_paye, 0) as total_paye,
                COALESCE(p.nb_paiements, 0) as nb_paiements
            FROM factures f
            LEFT JOIN (
                SELECT facture_id, 
                       SUM(montant) as total_paye,
                       COUNT(*) as nb_paiements
                FROM paiements_factures
                GROUP BY facture_id
            ) p ON f.id = p.facture_id
            WHERE f.structure_id = %s
        """
        params = [structure_id]
        
        if statut and statut != 'toutes':
            query += " AND f.statut = %s"
            params.append(statut)
        
        query += " ORDER BY f.created_at DESC"
        
        factures = db.execute_query(query, params)
        
        result = []
        for f in factures:
            if isinstance(f, dict):
                result.append({
                    'id': f.get('id'),
                    'numero_facture': f.get('numero_facture', ''),
                    'patient_nom': f.get('patient_nom', 'Patient'),
                    'patient_telephone': f.get('patient_telephone', ''),
                    'date_emission': str(f.get('date_emission')) if f.get('date_emission') else '',
                    'date_echeance': str(f.get('date_echeance')) if f.get('date_echeance') else '',
                    'sous_total': float(f.get('sous_total', 0)),
                    'taux_assurance': float(f.get('taux_assurance', 0)),
                    'prise_en_charge': float(f.get('prise_en_charge', 0)),
                    'taux_assurance2': float(f.get('taux_assurance2', 0)),
                    'prise_en_charge2': float(f.get('prise_en_charge2', 0)),
                    'net_a_payer': float(f.get('net_a_payer', 0)),
                    'montant_paye': float(f.get('montant_paye', 0)),
                    'reste_a_payer': float(f.get('reste_a_payer', 0)),
                    'statut': f.get('statut', 'en_attente'),
                    'statut_label': get_statut_label(f.get('statut')),
                    'nb_paiements': int(f.get('nb_paiements', 0) or 0),
                    'articles': f.get('articles', []),
                    'mode_paiement': f.get('mode_paiement', 'especes'),
                    'notes': f.get('notes', ''),
                    'created_by': f.get('created_by', ''),
                    'created_at': str(f.get('created_at')) if f.get('created_at') else '',
                    'updated_at': str(f.get('updated_at')) if f.get('updated_at') else '',
                    'base_remboursement': float(f.get('base_remboursement', 0)),
                    'assurances_data': f.get('assurances_data', {}),
                    'vente_id': f.get('vente_id')
                })
            else:
                # Format tuple
                result.append({
                    'id': f[0] if len(f) > 0 else None,
                    'numero_facture': f[5] if len(f) > 5 else '',
                    'patient_nom': f[3] if len(f) > 3 else 'Patient',
                    'patient_telephone': f[4] if len(f) > 4 else '',
                    'date_emission': str(f[6]) if len(f) > 6 and f[6] else '',
                    'date_echeance': str(f[7]) if len(f) > 7 and f[7] else '',
                    'sous_total': float(f[8]) if len(f) > 8 else 0,
                    'taux_assurance': float(f[9]) if len(f) > 9 else 0,
                    'prise_en_charge': float(f[10]) if len(f) > 10 else 0,
                    'taux_assurance2': float(f[11]) if len(f) > 11 else 0,
                    'prise_en_charge2': float(f[12]) if len(f) > 12 else 0,
                    'net_a_payer': float(f[13]) if len(f) > 13 else 0,
                    'montant_paye': float(f[14]) if len(f) > 14 else 0,
                    'reste_a_payer': float(f[15]) if len(f) > 15 else 0,
                    'statut': f[16] if len(f) > 16 else 'en_attente',
                    'statut_label': get_statut_label(f[16] if len(f) > 16 else 'en_attente'),
                    'nb_paiements': int(f[26]) if len(f) > 26 and f[26] else 0,  # total_paye est à l'index 26
                    'articles': f[17] if len(f) > 17 else [],
                    'mode_paiement': f[18] if len(f) > 18 else 'especes',
                    'notes': f[19] if len(f) > 19 else '',
                    'created_by': f[20] if len(f) > 20 else '',
                    'created_at': str(f[21]) if len(f) > 21 and f[21] else '',
                    'updated_at': str(f[22]) if len(f) > 22 and f[22] else '',
                    'base_remboursement': float(f[23]) if len(f) > 23 else 0,
                    'assurances_data': f[24] if len(f) > 24 else {},
                    'vente_id': f[25] if len(f) > 25 else None
                })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur GET factures: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 500


@app.route('/api/factures/<int:facture_id>/paiement', methods=['POST'])
@login_required
def api_enregistrer_paiement(facture_id):
    """Enregistrer un paiement (partiel ou total)"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        montant = float(data.get('montant', 0))
        mode_paiement = data.get('mode_paiement', 'especes')
        notes = data.get('notes', '')
        
        if montant <= 0:
            return jsonify({'success': False, 'error': 'Montant invalide'}), 400
        
        # Récupérer la facture
        facture = db.execute_query("""
            SELECT * FROM factures 
            WHERE id = %s AND structure_id = %s
        """, (facture_id, structure_id))
        
        if not facture:
            return jsonify({'success': False, 'error': 'Facture non trouvée'}), 404
        
        f = facture[0]
        reste_actuel = float(f.get('reste_a_payer', 0))
        
        if montant > reste_actuel:
            return jsonify({
                'success': False, 
                'error': f'Le montant ({montant} FCFA) dépasse le reste à payer ({reste_actuel} FCFA)'
            }), 400
        
        # Calculer les nouveaux montants
        nouveau_montant_paye = float(f.get('montant_paye', 0)) + montant
        nouveau_reste = reste_actuel - montant
        
        # Déterminer le statut
        if nouveau_reste <= 0:
            statut = 'payee'
            nouveau_reste = 0
        else:
            statut = 'partielle'
        
        # Enregistrer le paiement
        paiement_result = db.execute_query("""
            INSERT INTO paiements_factures (
                facture_id, montant, mode_paiement, notes, created_by
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (facture_id, montant, mode_paiement, notes, user_name))
        
        paiement_id = paiement_result[0]['id']
        
        # Mettre à jour la facture
        db.execute_query("""
            UPDATE factures 
            SET montant_paye = %s, 
                reste_a_payer = %s, 
                statut = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (nouveau_montant_paye, nouveau_reste, statut, facture_id))
        
        # Ajouter à la recette (caisse)
        db.execute_query("""
            INSERT INTO recettes (structure_id, montant, source, source_id, source_type, description, created_by_nom)
            VALUES (%s, %s, 'patients', %s, 'facture', %s, %s)
        """, (
            structure_id,
            montant,
            facture_id,
            f'Paiement facture #{f.get("numero_facture")} - {f.get("patient_nom")}',
            user_name
        ))
        
        # Mettre à jour le solde de caisse
        db.execute_query("""
            INSERT INTO caisse (structure_id, solde_actuel, date_mise_a_jour)
            VALUES (%s, 
                (SELECT COALESCE(SUM(montant), 0) FROM recettes WHERE structure_id = %s AND (est_annulation IS NULL OR est_annulation = FALSE)) -
                (SELECT COALESCE(SUM(montant), 0) FROM depenses WHERE structure_id = %s),
                NOW())
            ON CONFLICT (structure_id) DO UPDATE SET
                solde_actuel = EXCLUDED.solde_actuel,
                date_mise_a_jour = NOW()
        """, (structure_id, structure_id, structure_id))

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE : la créance client redescend ⭐⭐⭐
        try:
            from services.comptabilite_service import generer_ecriture_paiement_facture
            paiement_orm = PaiementFacture.query.get(paiement_id)
            facture_orm = Facture.query.get(facture_id)
            if paiement_orm and facture_orm:
                ecriture_pai = generer_ecriture_paiement_facture(paiement_orm, facture_orm, user_nom=user_name)
                if ecriture_pai:
                    print(f"🧾 Écriture comptable #{ecriture_pai.id} générée pour le paiement #{paiement_id}")
        except Exception as e:
            print(f"⚠️ Erreur génération écriture comptable (paiement #{paiement_id} conservé): {e}")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='paiement_facture',
                description=f"Paiement facture #{f.get('numero_facture')} — {f.get('patient_nom')}",
                montant=montant, type_montant='credit',
                reference_type='facture', reference_id=facture_id,
                patient_nom=f.get('patient_nom'),
                utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (paiement facture #{facture_id}): {e}")

        return jsonify({
            'success': True,
            'paiement_id': paiement_id,
            'montant_paye': montant,
            'reste_a_payer': nouveau_reste,
            'statut': statut,
            'statut_label': get_statut_label(statut)
        })
        
    except Exception as e:
        print(f"❌ Erreur paiement: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/factures/<int:facture_id>/annuler', methods=['POST'])
@login_required
def api_annuler_facture(facture_id):
    """Annuler une facture (admin uniquement)"""
    try:
        if not session.get('is_admin'):
            return jsonify({'success': False, 'error': 'Non autorisé'}), 403
        
        structure_id = session.get('structure_id')
        motif = request.json.get('motif', 'Annulation manuelle')
        
        # Vérifier que la facture existe
        facture = db.execute_query("""
            SELECT * FROM factures 
            WHERE id = %s AND structure_id = %s
        """, (facture_id, structure_id))
        
        if not facture:
            return jsonify({'success': False, 'error': 'Facture non trouvée'}), 404
        
        f = facture[0]
        reste_a_payer = float(f.get('reste_a_payer', 0) or 0)

        # Marquer comme annulée
        db.execute_query("""
            UPDATE factures
            SET statut = 'annulee',
                notes = CONCAT(COALESCE(notes, ''), ' [ANNULEE - ', %s, ']'),
                updated_at = NOW()
            WHERE id = %s
        """, (motif, facture_id))

        # ⭐⭐⭐ COMPTABILISATION AUTOMATIQUE : la créance restante est abandonnée ⭐⭐⭐
        if reste_a_payer > 0:
            try:
                from services.comptabilite_service import generer_ecriture_annulation_facture
                facture_orm = Facture.query.get(facture_id)
                if facture_orm:
                    ecriture_annul = generer_ecriture_annulation_facture(
                        facture_orm, reste_a_payer, user_nom=session.get('user_name', 'Admin'))
                    if ecriture_annul:
                        print(f"🧾 Écriture d'annulation #{ecriture_annul.id} générée pour la facture #{facture_id}")
            except Exception as e:
                print(f"⚠️ Erreur génération écriture d'annulation (facture #{facture_id} conservée annulée): {e}")

            try:
                from services.journal_service import JournalService
                JournalService.creer_mouvement(
                    structure_id=structure_id, categorie='avoir_emis',
                    description=f"Annulation facture {f.get('numero_facture')} — créance abandonnée ({motif})",
                    montant=reste_a_payer, type_montant='debit',
                    reference_type='facture', reference_id=facture_id,
                    patient_nom=f.get('patient_nom'), utilisateur_nom=session.get('user_name', 'Admin'),
                )
            except Exception as e:
                print(f"⚠️ Erreur journal d'activité (annulation facture #{facture_id}): {e}")

        return jsonify({'success': True, 'message': 'Facture annulée'})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def get_statut_label(statut):
    labels = {
        'en_attente': 'En attente',
        'partielle': 'Paiement partiel',
        'payee': 'Payée',
        'en_retard': 'En retard',
        'impayee': 'Impayée',
        'annulee': 'Annulée'
    }
    return labels.get(statut, statut)
@app.route('/api/factures/creer_automatique', methods=['POST'])
@login_required
def api_creer_facture_automatique():
    """Créer une facture automatiquement pour un paiement partiel"""
    try:
        data = request.json
        structure_id = session.get('structure_id')
        user_name = session.get('user_name', 'System')
        
        vente_id = data.get('vente_id')
        date_echeance = data.get('date_echeance')
        mode_paiement = data.get('mode_paiement', 'especes')
        montant_paye = float(data.get('montant_paye', 0))
        reste_a_payer = float(data.get('reste_a_payer', 0))
        notes = data.get('notes', '')
        
        if not vente_id:
            return jsonify({'success': False, 'error': 'ID vente manquant'}), 400
        
        # Récupérer la vente
        vente = db.execute_query("""
            SELECT v.*, p.nom, p.prenom, p.telephone
            FROM ventes v
            LEFT JOIN patients p ON v.patient_id = p.id
            WHERE v.id = %s AND v.structure_id = %s
        """, (vente_id, structure_id))
        
        if not vente or len(vente) == 0:
            return jsonify({'success': False, 'error': 'Vente non trouvée'}), 404
        
        v = vente[0]
        
        # Récupérer les articles avec leurs prix corrects
        import json
        articles = []
        vente_type = v.get('type') if isinstance(v, dict) else v[3] if len(v) > 3 else 'actes'
        
        if isinstance(v, dict):
            if vente_type == 'actes' and v.get('actes'):
                articles = json.loads(v.get('actes')) if isinstance(v.get('actes'), str) else v.get('actes')
                for article in articles:
                    if 'prix' in article:
                        article['prix_unitaire'] = article.get('prix', 0)
                        article['prix_reel'] = article.get('prix', 0)
                    if 'pbr' not in article:
                        article['pbr'] = article.get('prix', 0)
                    if 'total' not in article or not article['total']:
                        article['total'] = article.get('prix', 0) * article.get('quantite', 1)
                        
            elif vente_type in ['pharma', 'pharmacie'] and v.get('produits'):
                articles = json.loads(v.get('produits')) if isinstance(v.get('produits'), str) else v.get('produits')
                for article in articles:
                    if 'prix_reel' in article:
                        article['prix_unitaire'] = article.get('prix_reel', 0)
                        article['prix'] = article.get('prix_reel', 0)
                    elif 'prix_vente' in article:
                        article['prix_unitaire'] = article.get('prix_vente', 0)
                        article['prix'] = article.get('prix_vente', 0)
                    elif 'prix' in article:
                        article['prix_unitaire'] = article.get('prix', 0)
                        article['prix'] = article.get('prix', 0)
                    if 'pbr' not in article:
                        article['pbr'] = article.get('prix_unitaire', 0)
                    if 'total' not in article or not article['total']:
                        article['total'] = article.get('prix_unitaire', 0) * article.get('quantite', 1)
        else:
            # Format tuple
            if vente_type == 'actes' and len(v) > 6 and v[6]:
                articles_data = v[6]
                if isinstance(articles_data, str):
                    articles_data = json.loads(articles_data)
                for article in articles_data:
                    article['prix_unitaire'] = article.get('prix', 0)
                    article['prix_reel'] = article.get('prix', 0)
                    if 'pbr' not in article:
                        article['pbr'] = article.get('prix', 0)
                    if 'total' not in article or not article['total']:
                        article['total'] = article.get('prix', 0) * article.get('quantite', 1)
                articles = articles_data
            elif vente_type in ['pharma', 'pharmacie'] and len(v) > 7 and v[7]:
                articles_data = v[7]
                if isinstance(articles_data, str):
                    articles_data = json.loads(articles_data)
                for article in articles_data:
                    article['prix_unitaire'] = article.get('prix_reel', article.get('prix_vente', article.get('prix', 0)))
                    article['prix'] = article.get('prix_reel', article.get('prix_vente', article.get('prix', 0)))
                    if 'pbr' not in article:
                        article['pbr'] = article.get('prix_unitaire', 0)
                    if 'total' not in article or not article['total']:
                        article['total'] = article.get('prix_unitaire', 0) * article.get('quantite', 1)
                articles = articles_data
        
        # Récupérer les infos du patient
        patient_nom = v.get('patient_nom', 'Patient') if isinstance(v, dict) else v[2] if len(v) > 2 else 'Patient'
        patient_telephone = v.get('telephone', '') if isinstance(v, dict) else v[13] if len(v) > 13 else ''
        
        if not patient_telephone and isinstance(v, dict):
            patient_telephone = v.get('telephone', '')
        
        net_a_payer = float(v.get('net_a_payer', 0)) if isinstance(v, dict) else float(v[6]) if len(v) > 6 else 0
        
        # Récupérer base_remboursement
        base_remboursement = float(v.get('base_remboursement', 0)) if isinstance(v, dict) else float(v[20]) if len(v) > 20 else 0
        
        if reste_a_payer <= 0:
            reste_a_payer = net_a_payer - montant_paye
        
        if reste_a_payer < 0:
            reste_a_payer = 0
        
        if not date_echeance:
            date_echeance = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Générer le numéro de facture
        count = db.execute_query("""
            SELECT COUNT(*) as total FROM factures WHERE structure_id = %s
        """, (structure_id,))
        total = count[0]['total'] if count else 0
        numero_facture = f"F{structure_id}-{total+1:04d}"
        
        # Récupérer les assurances
        assurances_data = v.get('assurances') if isinstance(v, dict) else None
        if isinstance(assurances_data, str):
            try:
                assurances_data = json.loads(assurances_data)
            except:
                assurances_data = None
        
        # ⭐⭐⭐ CRÉER LA FACTURE AVEC commit=True ⭐⭐⭐
        print(f"📝 Création facture - Vente #{vente_id}, Reste: {reste_a_payer} FCFA")
        
        result = db.execute_query("""
            INSERT INTO factures (
                structure_id, patient_id, patient_nom, patient_telephone,
                numero_facture, date_emission, date_echeance,
                sous_total, taux_assurance, prise_en_charge,
                taux_assurance2, prise_en_charge2,
                net_a_payer, montant_paye, reste_a_payer,
                articles, mode_paiement, notes, created_by,
                base_remboursement, assurances_data,
                vente_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            structure_id,
            v.get('patient_id') if isinstance(v, dict) else v[1] if len(v) > 1 else None,
            patient_nom,
            patient_telephone,
            numero_facture,
            datetime.now().date(),
            date_echeance,
            float(v.get('sous_total', 0)) if isinstance(v, dict) else float(v[4]) if len(v) > 4 else 0,
            float(v.get('taux_assurance', 0)) if isinstance(v, dict) else float(v[9]) if len(v) > 9 else 0,
            float(v.get('prise_en_charge', 0)) if isinstance(v, dict) else float(v[5]) if len(v) > 5 else 0,
            float(v.get('taux_assurance2', 0)) if isinstance(v, dict) else 0,
            float(v.get('prise_en_charge2', 0)) if isinstance(v, dict) else 0,
            net_a_payer,
            montant_paye,
            reste_a_payer,
            json.dumps(articles, ensure_ascii=False),
            mode_paiement,
            f"{notes} - Vente #{vente_id}",
            user_name,
            base_remboursement,
            json.dumps(assurances_data, ensure_ascii=False) if assurances_data else None,
            vente_id
        ), commit=True)  # ⭐⭐⭐ commit=True OBLIGATOIRE ⭐⭐⭐
        
        if not result or len(result) == 0:
            print("❌ Erreur: Aucun ID retourné pour la facture")
            return jsonify({'success': False, 'error': 'Erreur insertion facture'}), 500
        
        facture_id = result[0]['id']
        
        # ⭐⭐⭐ METTRE À JOUR LE STATUT DE LA VENTE AVEC commit=True ⭐⭐⭐
        db.execute_query("""
            UPDATE ventes SET statut = 'partielle' WHERE id = %s
        """, (vente_id,), commit=True)  # ⭐⭐⭐ commit=True OBLIGATOIRE ⭐⭐⭐
        
        print(f"✅ Facture automatique créée: {numero_facture} (ID: {facture_id})")
        print(f"   Reste à payer: {reste_a_payer} FCFA")
        print(f"   Montant payé: {montant_paye} FCFA")
        print(f"   Articles: {len(articles)}")
        print(f"   Base remboursement (PBR): {base_remboursement} FCFA")

        # ⭐ JOURNAL D'ACTIVITÉ
        try:
            from services.journal_service import JournalService
            JournalService.creer_mouvement(
                structure_id=structure_id, categorie='facture_emise',
                description=f"Facture {numero_facture} émise automatiquement (vente #{vente_id}, reste {reste_a_payer} FCFA)",
                montant=reste_a_payer, type_montant='neutre',
                reference_type='facture', reference_id=facture_id,
                patient_nom=patient_nom, utilisateur_nom=user_name,
            )
        except Exception as e:
            print(f"⚠️ Erreur journal d'activité (facture auto #{facture_id}): {e}")

        return jsonify({
            'success': True,
            'facture_id': facture_id,
            'numero_facture': numero_facture,
            'reste_a_payer': reste_a_payer,
            'montant_paye': montant_paye,
            'articles_count': len(articles),
            'base_remboursement': base_remboursement
        })
        
    except Exception as e:
        print(f"❌ Erreur création facture automatique: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/gestion_stock')
@login_required
def gestion_stock():
    """Page de gestion des actes et produits pour le comptable/gestionnaire"""
    structure_id = session.get('structure_id')
    
    # Vérifier les droits (admin, comptable, gestionnaire)
    role = session.get('role', 'caissier')
    if role not in ['admin', 'comptable', 'gestionnaire', 'pharmacien']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer les actes
    actes = sheets_helper.get_all_records('actes')
    actes_filtres = [a for a in actes if str(a.get('structure_id')) == str(structure_id)]
    
    return render_template('gestion_stock.html', actes=actes_filtres)
@app.route('/lunetterie_vente')
@login_required
def lunetterie_vente():
    """Page de vente de lunettes"""
    structure_id = session.get('structure_id')
    
    # Récupérer les lunettes depuis Google Sheets
    lunettes = sheets_helper.get_all_records('lunettes')
    
    # Filtrer par structure
    lunettes_filtrees = []
    for l in lunettes:
        if str(l.get('structure_id')) == str(structure_id):
            lunettes_filtrees.append({
                'ID': l.get('ID'),
                'code': l.get('code', ''),
                'nom': l.get('nom', ''),
                'categorie': l.get('categorie', ''),
                'marque': l.get('marque', ''),
                'modele': l.get('modele', ''),
                'type_verres': l.get('type_verres', ''),
                'couleur': l.get('couleur', ''),
                'prix_vente': float(l.get('prix_vente', 0)),
                'prix_achat': float(l.get('prix_achat', 0)),
                'quantite_stock': int(l.get('quantite_stock', 0)),
                'seuil_alerte': int(l.get('seuil_alerte', 10)),
                'fournisseur': l.get('fournisseur', ''),
                'description': l.get('description', '')
            })
    
    # Taux AMU par défaut pour les lunettes (60% max)
    patient_taux = 60  # Valeur par défaut, sera modifiée par le JS
    
    return render_template('lunetterie_vente.html', 
                         lunettes=lunettes_filtrees,
                         patient_taux=patient_taux)


# ==================== API DE SYNCHRONISATION ====================

def require_api_key(f):
    """Décorateur pour vérifier la clé API (depuis Google Sheets)"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not api_key:
            return jsonify({'error': 'Clé API requise'}), 401
        
        try:
            structures = sheets_helper.get_all_records('structures', use_prefix=False)
            structure = None
            for s in structures:
                if s.get('api_key') == api_key:
                    structure = s
                    break
            
            if not structure:
                return jsonify({'error': 'Clé API invalide'}), 401
            
            return f(structure, *args, **kwargs)
            
        except Exception as e:
            print(f"❌ Erreur vérification clé API: {e}")
            return jsonify({'error': 'Erreur interne'}), 500
            
    return decorated_function


@app.route('/api/test_public')
def api_test_public():
    """Endpoint de test public (sans authentification)"""
    return jsonify({
        'status': 'OK',
        'message': 'API GHP est accessible',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/test')
@require_api_key
def api_test(structure):
    """Endpoint de test pour vérifier la connexion API"""
    return jsonify({
        'status': 'OK',
        'message': 'API GHP fonctionne',
        'structure_id': structure.get('ID'),
        'structure_nom': structure.get('nom')
    })


@app.route('/api/sync/patients')
def api_sync_patients():
    """Récupérer les patients d'une structure (avec token)"""
    from sqlalchemy import text
    
    token = request.args.get('token') or request.headers.get('X-API-Token')
    
    if not token:
        return jsonify({'error': 'Token requis'}), 401
    
    try:
        # Lire les structures depuis Google Sheets
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        
        structure = None
        for s in structures:
            if s.get('token') == token or s.get('TOKEN') == token:
                structure = s
                break
        
        if not structure:
            return jsonify({'error': 'Token invalide'}), 401
        
        structure_id = int(structure.get('ID'))
        structure_nom = structure.get('nom')
        
        print(f"✅ Token valide pour la structure {structure_id} - {structure_nom}")
        
        # ⭐ Remplacer db.execute_query par db.session.execute avec text()
        result = db.session.execute(
            text("""
                SELECT 
                    id, nom, prenom, telephone, adresse, date_naissance,
                    type_assurance, taux_prise_charge, numero_assure,
                    assurance2_nom, taux_assurance2, numero_assure2,
                    personne_a_prevenir_nom, personne_a_prevenir_telephone, 
                    personne_a_prevenir_relation
                FROM patients 
                WHERE structure_id = :structure_id
            """),
            {'structure_id': structure_id}
        )
        
        patients = result.fetchall()
        
        print(f"📊 {len(patients)} patients trouvés")
        
        result_list = []
        for p in patients:
            # p est un tuple ou un objet Row
            # Accéder par index
            date_naissance = p[5] if len(p) > 5 else None  # index 5 = date_naissance
            result_list.append({
                'ID': p[0],  # id
                'nom': p[1] or '',  # nom
                'prenom': p[2] or '',  # prenom
                'telephone': p[3] or '',  # telephone
                'adresse': p[4] or '',  # adresse
                'date_naissance': date_naissance.strftime('%Y-%m-%d') if date_naissance else None,
                'type_assurance': p[6] or 'non_assure',  # type_assurance
                'taux_prise_charge': float(p[7] or 0),  # taux_prise_charge
                'numero_assure': p[8] or '',  # numero_assure
                'assurance2_nom': p[9] or '',  # assurance2_nom
                'taux_assurance2': float(p[10] or 0),  # taux_assurance2
                'numero_assure2': p[11] or '',  # numero_assure2
                'personne_a_prevenir_nom': p[12] or '',  # personne_a_prevenir_nom
                'personne_a_prevenir_telephone': p[13] or '',  # personne_a_prevenir_telephone
                'personne_a_prevenir_relation': p[14] or ''  # personne_a_prevenir_relation
            })
        
        return jsonify({
            'structure_id': structure_id,
            'structure_nom': structure_nom,
            'total': len(result_list),
            'patients': result_list
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

import os
import requests
from datetime import datetime
import socket

def get_webhook_url():
    """
    Retourne l'URL du webhook selon l'environnement
    """
    # ⭐ Variable d'environnement pour définir l'environnement
    env = os.environ.get('APP_ENV', 'development')
    
    if env == 'production':
        # 🚀 URL de production (Render)
        return "https://medilogic-biasa-ghp.onrender.com/api/webhook/patient-created"
    else:
        # 💻 URL de développement (local)
        return "http://10.156.62.79:5000/api/webhook/patient-created"

# Dans GHP - app.py ou le fichier qui fait l'appel webhook

from config import Config
import requests
from datetime import datetime

def notify_consultation_app(patient_id, structure_id):
    """
    Notifier l'application de consultation de la création d'un patient
    Utilise la configuration de config.py
    """
    # ⭐ Récupérer l'URL depuis la config
    webhook_url = Config.WEBHOOK_URL
    
    # ⭐ Récupérer le token depuis la config
    webhook_secret = Config.WEBHOOK_SECRET
    
    headers = {
        'X-Webhook-Token': webhook_secret,
        'Content-Type': 'application/json'
    }
    
    data = {
        'patient_id': patient_id,
        'structure_id': structure_id,
        'timestamp': datetime.now().isoformat()
    }
    
    print(f"📡 Envoi webhook à: {webhook_url}")
    print(f"   Patient ID: {patient_id}")
    print(f"   Structure ID: {structure_id}")
    
    try:
        response = requests.post(webhook_url, json=data, headers=headers, timeout=5)
        
        if response.status_code == 200:
            print(f"✅ Patient {patient_id} synchronisé immédiatement")
            return True
        else:
            print(f"⚠️ Erreur webhook: {response.status_code}")
            print(f"   Réponse: {response.text[:100]}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"⏰ Timeout - Le scheduler fera la synchronisation")
        return False
    except requests.exceptions.ConnectionError:
        print(f"🔌 Connexion impossible - Vérifie que l'app de consultation est allumée")
        return False
    except Exception as e:
        print(f"❌ Erreur webhook: {e}")
        return False

@app.route('/api/actes/disponibles', methods=['GET'])
def api_actes_disponibles():
    """
    API token (comme /api/medicamentos) pour récupérer le catalogue
    d'actes d'une structure — utilisée par gestion_patients pour la
    recherche d'actes posés (onglet "Actes posés"), afin de matcher
    contre le VRAI catalogue de la structure plutôt qu'une copie locale
    qui pourrait diverger.

    ⭐ Construit le nom de la feuille directement (struct_<id>_actes) au
    lieu de passer par sheets_helper.set_structure()/structure_prefix
    (état partagé entre requêtes concurrentes) — cette route n'a pas de
    session (appel cross-app par token), donc pas question de dépendre
    d'un état posé par une AUTRE requête en cours.
    """
    token = request.args.get('token')
    if not token:
        return jsonify({'error': 'Token manquant'}), 401

    mapping = StructureMapping.query.filter_by(api_key=token, actif=True).first()
    if not mapping:
        return jsonify({'error': 'Token invalide'}), 401

    try:
        structure_id = mapping.source_structure_id
        sheet_name = f"struct_{structure_id}_actes"
        try:
            worksheet = sheets_helper.spreadsheet.worksheet(sheet_name)
            actes = worksheet.get_all_records()
        except Exception:
            actes = sheets_helper.get_all_records('actes', use_prefix=False)

        result = []
        for a in actes:
            nom = a.get('nom') or ''
            if nom:
                # ⭐ prix/pbr inclus (en plus du nom) — utilisé par
                # gestion_patients pour afficher un aperçu tarifaire avant
                # envoi (ex. clôture d'hospitalisation), sans dupliquer le
                # catalogue. Champs additifs, ignorés par les appelants qui
                # ne s'intéressent qu'au nom (recherche d'actes posés).
                try:
                    prix = float(a.get('prix') or 0)
                except (TypeError, ValueError):
                    prix = 0
                try:
                    pbr = float(a.get('pbr') or 0)
                except (TypeError, ValueError):
                    pbr = 0
                result.append({'nom': nom, 'prix': prix, 'pbr': pbr})
        result.sort(key=lambda x: x['nom'])

        return jsonify({'success': True, 'actes': result, 'total': len(result)})
    except Exception as e:
        print(f"❌ Erreur /api/actes/disponibles: {e}")
        return jsonify({'success': False, 'actes': [], 'error': str(e)}), 500


@app.route('/api/medicamentos', methods=['GET'])
def api_medicamentos():
    """
    API pour récupérer les médicaments depuis Google Sheets
    """
    import traceback
    
    token = request.args.get('token')
    if not token:
        return jsonify({'error': 'Token manquant'}), 401
    
    try:
        # ⭐ Utiliser StructureMapping (doit être importé)
        mapping = StructureMapping.query.filter_by(api_key=token, actif=True).first()
        if not mapping:
            return jsonify({'error': 'Token invalide'}), 401
        
        from sheets_helper import sheets_helper
        
        if not sheets_helper:
            return jsonify({'error': 'sheets_helper non initialisé'}), 500
        
        medicamentos = sheets_helper.get_medicamentos(mapping.source_structure_id)
        
        return jsonify({
            'success': True,
            'medicamentos': medicamentos or [],
            'total': len(medicamentos) if medicamentos else 0,
            'structure_id': mapping.source_structure_id
        })
        
    except NameError as e:
        print(f"❌ Erreur: {e} - Vérifie que StructureMapping est importé")
        return jsonify({'error': f'StructureMapping non défini: {str(e)}'}), 500
    except Exception as e:
        print(f"❌ Erreur récupération médicaments: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/prescriptions/<int:id>/delivrer', methods=['POST'])
@login_required
def delivrer_prescription(id):
    """
    Marquer une prescription comme délivrée (Pharmacie)
    """
    structure_id = session.get('structure_id')

    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401

    try:
        # ⭐ EN_ATTENTE (jamais touchée) ou AU_PANIER (déjà ajoutée au
        # panier avant la vente — l'état réel une fois la vente terminée,
        # voir finaliserPanier() -> pharma_vente) : les deux sont "pas
        # encore délivrée".
        prescription = db.execute_query("""
            SELECT * FROM prescriptions_recues
            WHERE id = %s AND structure_id = %s AND statut IN ('EN_ATTENTE', 'AU_PANIER')
        """, (id, structure_id))
        
        if not prescription:
            return jsonify({'success': False, 'message': 'Prescription non trouvée ou déjà traitée'}), 404
        
        # ⭐ Mettre à jour le statut
        db.execute_query("""
            UPDATE prescriptions_recues 
            SET statut = 'DELIVREE', delivre_le = %s
            WHERE id = %s AND structure_id = %s
        """, (datetime.now().isoformat(), id, structure_id))
        
        return jsonify({'success': True, 'message': '✅ Prescription délivrée avec succès'})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/prescriptions/<int:id>/facturer', methods=['POST'])
@login_required
def facturer_prescription(id):
    """
    Marquer une prescription comme facturée (Actes)
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        # ⭐ Vérifier que la prescription existe et n'est pas déjà facturée.
        # EN_ATTENTE (jamais touchée) ET AU_PANIER (ajoutée au panier avant
        # la vente — l'état réel une fois la vente terminée, voir
        # finaliserPanier() -> actes_vente) sont tous deux "pas encore
        # facturés" légitimes ici.
        prescription = db.execute_query("""
            SELECT * FROM prescriptions_recues
            WHERE id = %s AND structure_id = %s AND statut IN ('EN_ATTENTE', 'AU_PANIER')
        """, (id, structure_id))

        if not prescription:
            return jsonify({'success': False, 'message': 'Prescription non trouvée ou déjà traitée'}), 404

        # ⭐ Mettre à jour le statut
        db.execute_query("""
            UPDATE prescriptions_recues
            SET statut = 'FACTURE', facture_le = %s
            WHERE id = %s AND structure_id = %s
        """, (datetime.now().isoformat(), id, structure_id))
        
        return jsonify({'success': True, 'message': '✅ Acte facturé avec succès'})
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/prescriptions', methods=['POST'])
def api_receive_prescriptions():
    """
    Reçoit les prescriptions depuis Consultation (API)
    Gère les médicaments et les actes
    """
    from datetime import datetime
    
    # Vérifier le token
    token = request.args.get('token')
    if not token:
        return jsonify({'error': 'Token manquant'}), 401
    
    # Vérifier le mapping
    mapping = StructureMapping.query.filter_by(api_key=token, actif=True).first()
    if not mapping:
        return jsonify({'error': 'Token invalide'}), 401
    
    try:
        data = request.json
        prescriptions = data.get('prescriptions', [])
        
        if not prescriptions:
            return jsonify({'success': True, 'message': 'Aucune prescription'})
        
        print(f"📥 Réception de {len(prescriptions)} prescriptions")
        
        structure_id = mapping.local_structure_id
        recu_le = datetime.now().isoformat()
        inserted_count = 0
        
        for p in prescriptions:
            # ⭐ Détecter le type de prescription
            type_presc = p.get('type_prescription') or 'medicament'

            # ⭐ Éviter les doublons : si cette prescription (même source_id,
            # même structure, même type) a déjà été reçue, on ne la
            # réinsère pas — sans ça, un rattrapage du scheduler (toutes
            # les 5 min) qui retombe sur une prescription déjà envoyée
            # créerait une 2e ligne identique dans prescriptions_recues.
            # Le type est inclus dans la comparaison car gestion_patients a
            # PLUSIEURS sources (Prescription, ActePose...) dont les ID sont
            # des séquences indépendantes qui recommencent chacune à 1 — un
            # acte posé #1 et une prescription #1 partagent donc le même
            # source_id sans être la même chose (vécu en test : ça écrasait
            # silencieusement l'un des deux avant ce fix).
            deja_recue = db.execute_query("""
                SELECT id FROM prescriptions_recues
                WHERE source_id = %s AND structure_id = %s AND type_prescription = %s
            """, (p.get('id'), structure_id, type_presc))
            if deja_recue:
                continue

            # ⭐ Récupérer le nom du patient depuis la prescription
            patient_nom = p.get('patient_nom') or ''
            patient_prenom = p.get('patient_prenom') or ''

            # ⭐ Pour les actes, le nom est dans 'medicament' ou 'acte_nom'
            medicament = p.get('medicament') or p.get('acte_nom') or ''
            
            if type_presc == 'acte' and not medicament:
                medicament = p.get('acte_nom') or p.get('nom_acte') or 'Acte médical'
            
            if type_presc == 'medicament' and not medicament:
                medicament = p.get('medicament') or 'Médicament'
            
            # ⭐⭐ RECHERCHER LE PATIENT PAR NOM ET PRÉNOM ⭐⭐
            telephone = ''
            type_assurance = 'Non assuré'
            taux_prise_charge = 0
            assurance2_nom = ''
            taux_assurance2 = 0
            numero_assure = ''
            patient_id = None
            
            if patient_nom and patient_prenom:
                patient_info = db.execute_query("""
                    SELECT id, telephone, type_assurance, taux_prise_charge,
                           assurance2_nom, taux_assurance2, numero_assure
                    FROM patients 
                    WHERE LOWER(nom) = LOWER(%s) 
                    AND LOWER(prenom) = LOWER(%s)
                    AND structure_id = %s
                """, (patient_nom.strip(), patient_prenom.strip(), structure_id))
                
                if patient_info and len(patient_info) > 0:
                    pat = patient_info[0]
                    patient_id = pat.get('id')
                    telephone = pat.get('telephone', '')
                    type_assurance = pat.get('type_assurance', 'Non assuré')
                    taux_prise_charge = pat.get('taux_prise_charge', 0)
                    assurance2_nom = pat.get('assurance2_nom', '')
                    taux_assurance2 = pat.get('taux_assurance2', 0)
                    numero_assure = pat.get('numero_assure', '')
                    print(f"   ✅ Patient trouvé: {patient_nom} {patient_prenom} (ID: {patient_id})")
                else:
                    print(f"   ⚠️ Patient non trouvé: {patient_nom} {patient_prenom}")
            else:
                print(f"   ⚠️ Nom du patient manquant dans la prescription")
            
            # ⭐ Insérer la prescription
            result = db.execute_query("""
                INSERT INTO prescriptions_recues (
                    source_id, structure_id, patient_id, patient_nom, patient_prenom,
                    medicament, dosage, forme, quantite, duree_jours, frequence,
                    instructions, type_prescription, date_prescription, prescripteur,
                    statut, recu_le,
                    telephone, type_assurance, taux_prise_charge,
                    assurance2_nom, taux_assurance2, numero_assure
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                p.get('id'),
                structure_id,
                patient_id,  # ⭐ ID trouvé ou None
                patient_nom,
                patient_prenom,
                medicament,
                p.get('dosage') or '',
                p.get('forme') or '',
                p.get('quantite') or '1',
                p.get('duree_jours') or 0,
                p.get('frequence') or '',
                p.get('instructions') or '',
                type_presc,
                p.get('date_prescription') or datetime.now().isoformat(),
                p.get('prescripteur') or '',
                'EN_ATTENTE',
                recu_le,
                telephone,
                type_assurance,
                taux_prise_charge,
                assurance2_nom,
                taux_assurance2,
                numero_assure
            ))
            
            if result and len(result) > 0:
                inserted_count += 1
                print(f"   ✅ {type_presc.upper()}: {medicament} - {patient_nom} {patient_prenom}")
        
        return jsonify({
            'success': True,
            'message': f'✅ {inserted_count} prescriptions reçues'
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/protocoles/sync-externe', methods=['POST'])
def api_sync_protocole_externe():
    """
    Reçoit, en miroir, les protocoles de soins / ordonnances-types /
    bulletins d'examen-types créés côté gestion_patients (source réelle,
    utilisée dans le vrai parcours de soins) — voir _pousser_protocole_ghp()
    dans gestion_patients/app.py. Un seul endpoint générique pour les 3
    modèles source, comme /api/prescriptions gère médicaments et actes via
    un seul champ `type_prescription`.

    Upsert idempotent sur (structure_id, source_app, source_model, source_id)
    — jamais de doublon sur un retry (index unique partiel côté DB). Une
    catégorie hors des 3 synchronisables est refusée : une source externe ne
    doit jamais pouvoir créer/modifier un document 100% natif GHP
    (protocole_patient, fiche_information, protocole_infirmier).
    """
    token = request.args.get('token')
    if not token:
        return jsonify({'success': False, 'error': 'Token manquant'}), 401

    mapping = StructureMapping.query.filter_by(api_key=token, actif=True).first()
    if not mapping:
        return jsonify({'success': False, 'error': 'Token invalide'}), 401

    try:
        from models import ProtocoleMedical
        from services.protocoles_service import ProtocolesService

        data = request.json or {}
        categorie = data.get('categorie')
        if categorie not in ('protocole_soins', 'ordonnance_type', 'bulletin_examen'):
            return jsonify({'success': False, 'error': 'Catégorie non synchronisable'}), 400

        source_app = data.get('source_app') or 'gestion_patients'
        source_model = data.get('source_model')
        source_id = data.get('source_id')
        if not source_model or not source_id:
            return jsonify({'success': False, 'error': 'source_model/source_id manquants'}), 400

        action = data.get('action', 'upsert')
        structure_id = mapping.local_structure_id

        existant = ProtocoleMedical.query.filter_by(
            structure_id=structure_id, source_app=source_app,
            source_model=source_model, source_id=source_id,
        ).first()

        if action == 'archive':
            if existant and existant.statut != 'archive':
                ProtocolesService.modifier(
                    existant.id, structure_id, {'statut': 'archive'},
                    utilisateur_nom=data.get('auteur_nom') or 'Sync gestion_patients',
                )
            return jsonify({'success': True, 'message': 'Archivé' if existant else 'Rien à archiver'})

        payload = {
            'categorie': categorie,
            'titre': data.get('titre') or 'Sans titre',
            'description': data.get('description', ''),
            'contenu': data.get('contenu') or '',
            'medicaments': data.get('medicaments') or [],
            'examens': data.get('examens') or [],
            'statut': 'publie' if data.get('actif', True) else 'archive',
        }

        if existant:
            succes, resultat = ProtocolesService.modifier(
                existant.id, structure_id, payload,
                utilisateur_nom=data.get('auteur_nom') or 'Sync gestion_patients',
            )
            protocole_id = existant.id
        else:
            succes, resultat = ProtocolesService.creer(
                payload, structure_id,
                utilisateur_nom=data.get('auteur_nom') or 'Sync gestion_patients',
            )
            protocole_id = resultat.get('id') if succes else None
            if succes and protocole_id:
                p = ProtocoleMedical.query.get(protocole_id)
                p.source_app = source_app
                p.source_model = source_model
                p.source_id = source_id
                p.source_synced_at = datetime.utcnow()
                db.session.commit()

        if not succes:
            return jsonify({'success': False, 'error': resultat.get('error', 'Erreur inconnue')}), 500

        return jsonify({'success': True, 'protocole_id': protocole_id})

    except Exception as e:
        print(f"❌ Erreur sync protocole: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/prescriptions-recues')
@login_required
def prescriptions_recues():
    """
    Affiche les prescriptions reçues avec les prix
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # ⭐ Récupérer les prescriptions (les noms sont déjà dans la table)
        prescriptions = db.execute_query("""
            SELECT * FROM prescriptions_recues 
            WHERE structure_id = %s 
            ORDER BY recu_le DESC
        """, (structure_id,))
        
        # ⭐ Charger les produits et actes pour les prix
        produits = sheets_helper.get_medicamentos(structure_id)
        actes = sheets_helper.get_all_records('actes', use_prefix=True)
        
        # ⭐ Construire les dictionnaires de prix
        produits_dict = {}
        for p in produits:
            nom = p.get('nom', '').lower().strip()
            if nom:
                produits_dict[nom] = {
                    'prix': p.get('prix_vente', 0),
                    'pbr': p.get('pbr', 0),
                    'unite': p.get('unite', 'unité')
                }
        
        actes_dict = {}
        for a in actes:
            nom = a.get('nom', '').lower().strip()
            if nom:
                try:
                    prix = float(a.get('prix', 0)) if a.get('prix') else 0
                except:
                    prix = 0
                try:
                    pbr = float(a.get('pbr', 0)) if a.get('pbr') else 0
                except:
                    pbr = 0
                actes_dict[nom] = {'prix': prix, 'pbr': pbr}
        
        # ⭐ Traiter les prescriptions
        prescriptions_pharma = []
        prescriptions_actes = []
        
        for p in prescriptions:
            type_presc = p.get('type_prescription') or 'medicament'
            nom_recherche = p.get('medicament') or ''
            nom_clean = nom_recherche.lower().strip()

            # ⭐ Le template groupe par patient_id (Jinja groupby → sorted()) :
            # si 2+ lignes ont patient_id=NULL (patient non retrouvé côté
            # GHP par nom/prénom exact), Python plante avec "'<' not
            # supported between instances of 'NoneType' and 'NoneType'" et
            # la page entière part en 500 — plus AUCUNE prescription
            # visible, y compris celles d'autres patients bien identifiés.
            # On neutralise avec un entier négatif regroupant les
            # "non identifiés" plutôt que de laisser None.
            if p.get('patient_id') is None:
                p['patient_id'] = -1

            prix_unitaire = 0
            pbr = 0
            # ⭐ Indépendant du prix : un article trouvé à 0 F (prix pas
            # encore renseigné) reste "trouvé" — seul un article ABSENT du
            # catalogue de la structure doit ressortir en rouge (= la
            # structure ne le propose pas, le patient devra l'obtenir
            # ailleurs).
            article_trouve = False

            if type_presc == 'medicament':
                if nom_clean in produits_dict:
                    article_trouve = True
                    prix_unitaire = produits_dict[nom_clean]['prix']
                    pbr = produits_dict[nom_clean]['pbr']
            else:
                if nom_clean in actes_dict:
                    article_trouve = True
                    prix_unitaire = actes_dict[nom_clean]['prix']
                    pbr = actes_dict[nom_clean]['pbr']

            quantite = int(p.get('quantite', 1))
            p['prix_unitaire'] = prix_unitaire
            p['pbr'] = pbr
            p['prix_total'] = prix_unitaire * quantite
            p['article_trouve'] = article_trouve
            
            # ⭐ Utiliser les noms déjà stockés
            p['patient_nom'] = p.get('patient_nom', 'Patient inconnu')
            p['patient_prenom'] = p.get('patient_prenom', '')
            
            if type_presc == 'medicament':
                prescriptions_pharma.append(p)
            else:
                prescriptions_actes.append(p)
        
        return render_template('prescriptions_recues.html',
                             prescriptions_pharma=prescriptions_pharma,
                             prescriptions_actes=prescriptions_actes)
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Erreur: {str(e)}', 'danger')
        return render_template('prescriptions_recues.html', 
                             prescriptions_pharma=[], 
                             prescriptions_actes=[])

@app.route('/api/prescriptions/<int:id>/details', methods=['GET'])
@login_required
def prescription_details(id):
    """
    Récupère les détails d'une prescription avec son prix
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        # ⭐ Récupérer la prescription
        prescription = db.execute_query("""
            SELECT * FROM prescriptions_recues 
            WHERE id = %s AND structure_id = %s
        """, (id, structure_id))
        
        if not prescription or len(prescription) == 0:
            return jsonify({'success': False, 'message': 'Prescription non trouvée'}), 404
        
        p = prescription[0]
        
        # ⭐ Gérer le cas où medicament est None
        nom_recherche = p.get('medicament')
        if nom_recherche is None:
            nom_recherche = ''
        nom_recherche = str(nom_recherche).strip()
        
        type_presc = p.get('type_prescription') or 'medicament'
        
        if not nom_recherche:
            return jsonify({
                'success': False, 
                'message': 'Nom du médicament/acte manquant'
            }), 400
        
        print(f"🔍 Détails: '{nom_recherche}' (Type: {type_presc})")
        
        # ⭐ RÉCUPÉRER LE PRIX DEPUIS SHEETS
        prix_unitaire = 0
        unite = 'unité'
        found = False
        nom_trouve = ''
        match_info = ''
        
        if type_presc == 'medicament':
            prix_info = sheets_helper.get_prix_produit(structure_id, nom_recherche)
            
            if prix_info.get('trouve'):
                prix_unitaire = prix_info.get('prix', 0)
                unite = prix_info.get('unite', 'unité')
                found = True
                nom_trouve = nom_recherche
                match_info = '✅ Trouvé dans Sheets'
                print(f"✅ Produit trouvé: {nom_trouve} - Prix: {prix_unitaire} FCFA")
            else:
                # Recherche flexible
                produits = sheets_helper.get_medicamentos(structure_id)
                for prod in produits:
                    nom_prod = prod.get('nom', '')
                    if nom_prod and nom_recherche.lower() in nom_prod.lower():
                        prix_unitaire = prod.get('prix_vente', 0)
                        unite = prod.get('unite', 'unité')
                        nom_trouve = nom_prod
                        found = True
                        match_info = f'✅ Match partiel: {nom_trouve}'
                        print(f"✅ Produit trouvé (partiel): {nom_trouve} - Prix: {prix_unitaire} FCFA")
                        break
                
                if not found:
                    print(f"❌ Produit non trouvé: '{nom_recherche}'")
                    match_info = "❌ Absent du catalogue de cette structure"

        else:  # acte
            prix_info = sheets_helper.get_prix_acte(structure_id, nom_recherche)
            
            if prix_info.get('trouve'):
                prix_unitaire = prix_info.get('prix', 0)
                unite = 'acte'
                found = True
                nom_trouve = nom_recherche
                match_info = '✅ Trouvé dans Sheets'
                print(f"✅ Acte trouvé: {nom_trouve} - Prix: {prix_unitaire} FCFA")
            else:
                actes = sheets_helper.get_all_records('actes', use_prefix=True)
                for act in actes:
                    nom_act = act.get('nom', '')
                    if nom_act and nom_recherche.lower() in nom_act.lower():
                        prix_unitaire = float(act.get('prix', 0))
                        nom_trouve = nom_act
                        found = True
                        match_info = f'✅ Match partiel: {nom_trouve}'
                        print(f"✅ Acte trouvé (partiel): {nom_trouve} - Prix: {prix_unitaire} FCFA")
                        break
                
                if not found:
                    print(f"❌ Acte non trouvé: '{nom_recherche}'")
                    match_info = "❌ Absent du catalogue de cette structure"

        quantite = int(p.get('quantite', 1))
        prix_total = prix_unitaire * quantite
        
        return jsonify({
            'success': True,
            'prescription': {
                'id': p.get('id'),
                'patient_nom': p.get('patient_nom') or '',
                'patient_prenom': p.get('patient_prenom') or '',
                'medicament': nom_trouve or nom_recherche,
                'type': type_presc,
                'quantite': quantite,
                'prix_unitaire': prix_unitaire,
                'prix_total': prix_total,
                'unite': unite,
                'date_prescription': p.get('date_prescription'),
                'prescripteur': p.get('prescripteur') or '',
                'statut': p.get('statut') or 'EN_ATTENTE',
                'match_info': match_info,
                'article_trouve': found
            }
        })
        
    except Exception as e:
        print(f"❌ Erreur details: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/prescriptions/<int:id>/ajouter-panier', methods=['POST'])
@login_required
def prescription_ajouter_panier(id):
    """
    Ajoute une prescription au panier
    """
    from datetime import datetime
    
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        # ⭐ Récupérer la prescription
        # On accepte aussi AU_PANIER (pas seulement EN_ATTENTE) : une ligne
        # peut rester bloquée à AU_PANIER si une session précédente l'a
        # ajoutée sans jamais finaliser/vider (onglet fermé, session
        # expirée...) — le rafraîchissement client-side de cette page
        # réaffiche alors cette ligne comme "En attente" (car elle n'est
        # dans AUCUN panier de session active), et un clic "Ajouter au
        # panier" échouait avec "non trouvée ou déjà traitée" alors que
        # rien ne semblait anormal à l'écran. Réajouter la "récupère" pour
        # la session courante au lieu de bloquer.
        prescription = db.execute_query("""
            SELECT * FROM prescriptions_recues
            WHERE id = %s AND structure_id = %s AND statut IN ('EN_ATTENTE', 'AU_PANIER')
        """, (id, structure_id))

        if not prescription:
            return jsonify({'success': False, 'message': 'Prescription non trouvée ou déjà traitée'}), 404

        p = prescription[0]
        
        # ⭐ Récupérer le prix depuis Sheets
        nom_recherche = p.get('medicament') or ''
        type_presc = p.get('type_prescription') or 'medicament'
        prix_unitaire = 0
        nom_trouve = nom_recherche
        
        if type_presc == 'medicament':
            prix_info = sheets_helper.get_prix_produit(structure_id, nom_recherche)
            if prix_info.get('trouve'):
                prix_unitaire = prix_info.get('prix', 0)
        else:
            prix_info = sheets_helper.get_prix_acte(structure_id, nom_recherche)
            if prix_info.get('trouve'):
                prix_unitaire = prix_info.get('prix', 0)
        
        quantite = int(p.get('quantite', 1))
        prix_total = prix_unitaire * quantite
        
        # ⭐ Mettre à jour le statut
        db.execute_query("""
            UPDATE prescriptions_recues 
            SET statut = 'AU_PANIER'
            WHERE id = %s AND structure_id = %s
        """, (id, structure_id))
        
        # ⭐ Ajouter au panier (session)
        panier = session.get('panier_prescriptions', [])
        panier.append({
            'prescription_id': id,
            'type': type_presc,
            'nom': nom_trouve,
            'quantite': quantite,
            'prix_unitaire': prix_unitaire,
            'prix_total': prix_total,
            'patient_id': p.get('patient_id'),
            'patient_nom': p.get('patient_nom') or '',
            'patient_prenom': p.get('patient_prenom') or ''
        })
        session['panier_prescriptions'] = panier
        session.modified = True
        
        return jsonify({
            'success': True,
            'message': f'✅ {nom_trouve} ajouté au panier',
            'panier': panier,
            'total_panier': sum(item['prix_total'] for item in panier)
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/prescriptions/suggestions', methods=['POST'])
@login_required
def api_prescriptions_suggestions():
    """
    Retourne des suggestions pour un nom de médicament/acte non trouvé
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        data = request.json
        nom = data.get('nom', '').strip()
        type_presc = data.get('type', 'medicament')
        
        if not nom or len(nom) < 2:
            return jsonify({'suggestions': []})
        
        suggestions = []
        
        if type_presc == 'medicament':
            # Rechercher des médicaments similaires
            produits = db.execute_query("""
                SELECT nom, prix_vente FROM produits 
                WHERE structure_id = %s
                AND (LOWER(nom) LIKE LOWER(%s) OR LOWER(nom) LIKE LOWER(%s))
                LIMIT 10
            """, (structure_id, '%' + nom + '%', '%' + ' '.join(nom.split()[:2]) + '%'))
            
            suggestions = [p.get('nom') for p in produits]
            
        else:  # actes
            actes = db.execute_query("""
                SELECT nom, prix FROM actes 
                WHERE structure_id = %s
                AND (LOWER(nom) LIKE LOWER(%s) OR LOWER(nom) LIKE LOWER(%s))
                LIMIT 10
            """, (structure_id, '%' + nom + '%', '%' + ' '.join(nom.split()[:2]) + '%'))
            
            suggestions = [a.get('nom') for a in actes]
        
        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions)
        })
        
    except Exception as e:
        print(f"❌ Erreur suggestions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500



@app.route('/api/prescriptions/verifier-prix', methods=['POST'])
@login_required
def api_verifier_prix_prescriptions():
    """
    Vérifie les prix de toutes les prescriptions en attente
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        # ⭐ Récupérer toutes les prescriptions en attente
        prescriptions = db.execute_query("""
            SELECT id, type_prescription, medicament, quantite 
            FROM prescriptions_recues 
            WHERE structure_id = %s AND statut = 'EN_ATTENTE'
        """, (structure_id,))
        
        results = []
        errors = []
        
        for p in prescriptions:
            type_presc = p.get('type_prescription')
            nom = p.get('medicament')
            prix = 0
            
            if type_presc == 'medicament':
                produit = db.execute_query("""
                    SELECT prix_vente FROM produits 
                    WHERE nom ILIKE %s AND structure_id = %s
                """, (nom, structure_id))
                if produit and len(produit) > 0:
                    prix = float(produit[0].get('prix_vente', 0))
                else:
                    errors.append(f"Médicament non trouvé: {nom}")
            else:  # acte
                acte = db.execute_query("""
                    SELECT prix FROM actes 
                    WHERE nom ILIKE %s AND structure_id = %s
                """, (nom, structure_id))
                if acte and len(acte) > 0:
                    prix = float(acte[0].get('prix', 0))
                else:
                    errors.append(f"Acte non trouvé: {nom}")
            
            if prix > 0:
                quantite = int(p.get('quantite', 1))
                results.append({
                    'id': p.get('id'),
                    'nom': nom,
                    'type': type_presc,
                    'prix_unitaire': prix,
                    'prix_total': prix * quantite,
                    'quantite': quantite,
                    'status': 'OK'
                })
            else:
                errors.append(f"Prix non défini pour: {nom}")
        
        return jsonify({
            'success': True,
            'results': results,
            'errors': errors,
            'total_ok': len(results),
            'total_errors': len(errors)
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/prescriptions/<int:id>/retirer-panier', methods=['POST'])
@login_required
def prescription_retirer_panier(id):
    """
    Retire une prescription du panier
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        # ⭐ Marquer comme "EN_ATTENTE"
        db.execute_query("""
            UPDATE prescriptions_recues 
            SET statut = 'EN_ATTENTE'
            WHERE id = %s AND structure_id = %s
        """, (id, structure_id), commit=True)
        
        # ⭐ Retirer du panier
        panier = session.get('panier_prescriptions', [])
        panier = [item for item in panier if item['prescription_id'] != id]
        session['panier_prescriptions'] = panier
        session.modified = True
        
        return jsonify({
            'success': True,
            'message': '✅ Prescription retirée du panier',
            'panier': panier
        })
        
    except Exception as e:
        print(f"❌ Erreur retrait panier: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/panier-prescriptions', methods=['GET'])
@login_required
def api_panier_prescriptions():
    """
    Récupère le contenu du panier
    """
    try:
        panier = session.get('panier_prescriptions', [])
        total = sum(item['prix_total'] for item in panier)
        
        return jsonify({
            'success': True,
            'panier': panier,
            'total': total,
            'count': len(panier)
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/panier-prescriptions/vider', methods=['POST'])
@login_required
def api_vider_panier_prescriptions():
    """
    Vide le panier
    """
    try:
        panier = session.get('panier_prescriptions', [])
        
        # Remettre toutes les prescriptions en "EN_ATTENTE"
        for item in panier:
            db.execute_query("""
                UPDATE prescriptions_recues 
                SET statut = 'EN_ATTENTE'
                WHERE id = %s AND structure_id = %s
            """, (item['prescription_id'], session.get('structure_id')), commit=True)
        
        session['panier_prescriptions'] = []
        session.modified = True
        
        return jsonify({
            'success': True,
            'message': '🗑️ Panier vidé'
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/panier-prescriptions/finaliser', methods=['POST'])
@login_required
def api_finaliser_panier_prescriptions():
    """
    Finalise le panier et crée les ventes
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        panier = session.get('panier_prescriptions', [])
        
        if not panier:
            return jsonify({'success': False, 'message': 'Panier vide'}), 400
        
        # ⭐ Créer une vente pour chaque type (pharma et actes séparément)
        pharma_items = [item for item in panier if item['type'] == 'medicament']
        actes_items = [item for item in panier if item['type'] == 'acte']
        
        results = []
        
        # Ventes pharma
        if pharma_items:
            # Grouper par patient
            patients_pharma = {}
            for item in pharma_items:
                key = item.get('patient_nom', '') + item.get('patient_prenom', '')
                if key not in patients_pharma:
                    patients_pharma[key] = []
                patients_pharma[key].append(item)
            
            for patient_key, items in patients_pharma.items():
                # Créer la vente
                total = sum(item['prix_total'] for item in items)
                # ... création de la vente dans la table ventes
                results.append({
                    'type': 'pharma',
                    'patient': patient_key,
                    'total': total,
                    'items': len(items)
                })
        
        # Ventes actes
        if actes_items:
            patients_actes = {}
            for item in actes_items:
                key = item.get('patient_nom', '') + item.get('patient_prenom', '')
                if key not in patients_actes:
                    patients_actes[key] = []
                patients_actes[key].append(item)
            
            for patient_key, items in patients_actes.items():
                total = sum(item['prix_total'] for item in items)
                results.append({
                    'type': 'actes',
                    'patient': patient_key,
                    'total': total,
                    'items': len(items)
                })
        
        # ⭐ Vider le panier
        for item in panier:
            db.execute_query("""
                UPDATE prescriptions_recues 
                SET statut = 'FACTURE'
                WHERE id = %s AND structure_id = %s
            """, (item['prescription_id'], structure_id), commit=True)
        
        session['panier_prescriptions'] = []
        session.modified = True
        
        return jsonify({
            'success': True,
            'message': f'✅ {len(panier)} prescriptions facturées',
            'results': results
        })
        
    except Exception as e:
        print(f"❌ Erreur finalisation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.template_filter('format_currency')
def format_currency(value):
    """Formate un nombre en devise FCFA"""
    if value is None:
        return '0 FCFA'
    try:
        return f"{int(value):,} FCFA".replace(',', ' ')
    except:
        return f"{value} FCFA"
def generer_numero_ordonnance(structure_id):
    """
    Génère un numéro d'ordonnance unique pour une structure
    Format: ORD-{ANNEE}-{NUMERO_SEQUENTIEL}
    Exemple: ORD-2026-0042
    """
    from datetime import datetime
    import time
    
    annee = datetime.now().strftime('%Y')
    
    # ⭐ Clé pour le compteur (stocké en session ou en base)
    # Option 1: Stocker dans la session (pas persistant)
    # Option 2: Stocker dans Google Sheets ou base de données
    
    # 📌 Utilisation d'un fichier de compteur (simple)
    compteur_file = f'compteur_ordonnance_{structure_id}_{annee}.txt'
    
    try:
        with open(compteur_file, 'r') as f:
            compteur = int(f.read().strip())
    except:
        compteur = 0
    
    compteur += 1
    
    # Sauvegarder le nouveau compteur
    with open(compteur_file, 'w') as f:
        f.write(str(compteur))
    
    return f"ORD-{annee}-{compteur:04d}"


@app.route('/ordonnance/patient/<int:patient_id>')
@login_required
def imprimer_ordonnances_patient(patient_id):
    """
    Imprime toutes les prescriptions d'un patient
    """
    structure_id = session.get('structure_id')
    format_impression = request.args.get('format', '80mm')
    
    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer toutes les prescriptions du patient
    prescriptions = db.execute_query("""
        SELECT * FROM prescriptions_recues 
        WHERE patient_id = %s AND structure_id = %s AND statut = 'EN_ATTENTE'
    """, (patient_id, structure_id))
    
    if not prescriptions:
        flash('Aucune prescription en attente pour ce patient', 'warning')
        return redirect(url_for('prescriptions_recues'))
    
    # ⭐ Route corrigée : 'imprimer_ordonnance' n'a jamais existé (aucune
    # route de ce nom, ni de paramètre prescription_id) — cette redirection
    # plantait (BuildError) si jamais atteinte. Elle n'est en pratique liée
    # nulle part dans l'UI (seules /medicaments et /actes le sont), donc
    # aucune régression visible, mais autant rediriger vers une route qui
    # existe réellement plutôt que de laisser un lien mort.
    return redirect(url_for('imprimer_ordonnances_medicaments',
                         patient_id=patient_id,
                         format=format_impression))

@app.route('/ordonnance/patient/<int:patient_id>/medicaments')
@login_required
def imprimer_ordonnances_medicaments(patient_id):
    """
    Imprime toutes les prescriptions MÉDICAMENTEUSES d'un patient
    """
    from datetime import datetime
    
    structure_id = session.get('structure_id')
    format_impression = request.args.get('format', '80mm')
    
    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # ⭐ Récupérer les prescriptions
        prescriptions = db.execute_query("""
            SELECT * FROM prescriptions_recues 
            WHERE patient_id = %s 
            AND structure_id = %s 
            AND statut = 'EN_ATTENTE'
            AND type_prescription = 'medicament'
            ORDER BY id
        """, (patient_id, structure_id))
        
        if not prescriptions:
            flash('Aucune prescription médicamenteuse en attente pour ce patient', 'warning')
            return redirect(url_for('prescriptions_recues'))
        
        # ⭐⭐ RÉCUPÉRER LE NOM DU PATIENT DEPUIS LA PRESCRIPTION ⭐⭐
        p = prescriptions[0]
        patient_nom = p.get('patient_nom', '')
        patient_prenom = p.get('patient_prenom', '')
        
        if not patient_nom and not patient_prenom:
            flash('❌ Nom du patient manquant dans la prescription', 'danger')
            return redirect(url_for('prescriptions_recues'))
        
        # ⭐⭐ RECHERCHER LE PATIENT PAR NOM ET PRÉNOM ⭐⭐
        patient_info = db.execute_query("""
            SELECT id, nom, prenom, telephone, type_assurance, taux_prise_charge,
                   assurance2_nom, taux_assurance2, numero_assure
            FROM patients 
            WHERE LOWER(nom) = LOWER(%s) 
            AND LOWER(prenom) = LOWER(%s)
            AND structure_id = %s
        """, (patient_nom.strip(), patient_prenom.strip(), structure_id))
        
        # ⭐ SI LE PATIENT EST TROUVÉ → Utiliser ses infos
        if patient_info and len(patient_info) > 0:
            pat = patient_info[0]
            telephone = pat.get('telephone', '')
            type_assurance = pat.get('type_assurance', 'Non assuré')
            taux_prise_charge = pat.get('taux_prise_charge', 0)
            assurance2_nom = pat.get('assurance2_nom', '')
            taux_assurance2 = pat.get('taux_assurance2', 0)
            numero_assure = pat.get('numero_assure', '')
            print(f"✅ Patient trouvé: {patient_nom} {patient_prenom}")
        else:
            # ⭐ Patient non trouvé → infos vides
            telephone = ''
            type_assurance = 'Non assuré'
            taux_prise_charge = 0
            assurance2_nom = ''
            taux_assurance2 = 0
            numero_assure = ''
            print(f"⚠️ Patient non trouvé: {patient_nom} {patient_prenom}")
        
        # ⭐ Récupérer les informations de la structure
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        structure = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
        
        # ⭐ Générer un numéro d'ordonnance unique
        num_ordonnance = generer_numero_ordonnance(structure_id)
        
        # ⭐ Récupérer les prix
        total = 0
        for m in prescriptions:
            prix_info = sheets_helper.get_prix_produit(structure_id, m.get('medicament'))
            prix = prix_info.get('prix', 0)
            pbr = prix_info.get('pbr', 0)
            quantite = int(m.get('quantite', 1))
            m['prix_unitaire'] = prix
            m['pbr'] = pbr
            m['prix_total'] = prix * quantite
            total += prix * quantite
        
        # ⭐ Créer l'objet patient
        patient_obj = {
            'nom': patient_nom,
            'prenom': patient_prenom,
            'telephone': telephone or 'Non renseigné',
            'type_assurance': type_assurance,
            'taux_prise_charge': taux_prise_charge,
            'assurance2_nom': assurance2_nom,
            'taux_assurance2': taux_assurance2,
            'numero_assure': numero_assure or 'Non renseigné',
            'date_naissance': None
        }
        
        return render_template('ordonnance_medicaments.html',
                             prescriptions=prescriptions,
                             patient=patient_obj,
                             structure=structure,
                             num_ordonnance=num_ordonnance,
                             total=total,
                             format=format_impression,
                             now=datetime.now())
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Erreur: {str(e)}', 'danger')
        return redirect(url_for('prescriptions_recues'))


@app.route('/ordonnance/patient/<int:patient_id>/actes')
@login_required
def imprimer_ordonnances_actes(patient_id):
    """
    Imprime toutes les prescriptions D'ACTES d'un patient
    """
    from datetime import datetime
    
    structure_id = session.get('structure_id')
    format_impression = request.args.get('format', '80mm')
    
    if not structure_id:
        flash('Structure non trouvée', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # ⭐ Récupérer les prescriptions d'actes
        prescriptions = db.execute_query("""
            SELECT * FROM prescriptions_recues 
            WHERE patient_id = %s 
            AND structure_id = %s 
            AND statut = 'EN_ATTENTE'
            AND type_prescription = 'acte'
            ORDER BY id
        """, (patient_id, structure_id))
        
        if not prescriptions:
            flash('Aucune prescription d\'acte en attente pour ce patient', 'warning')
            return redirect(url_for('prescriptions_recues'))
        
        # ⭐⭐ RÉCUPÉRER LE NOM DU PATIENT DEPUIS LA PRESCRIPTION ⭐⭐
        p = prescriptions[0]
        patient_nom = p.get('patient_nom', '')
        patient_prenom = p.get('patient_prenom', '')
        
        if not patient_nom and not patient_prenom:
            flash('❌ Nom du patient manquant dans la prescription', 'danger')
            return redirect(url_for('prescriptions_recues'))
        
        # ⭐⭐ RECHERCHER LE PATIENT PAR NOM ET PRÉNOM ⭐⭐
        patient_info = db.execute_query("""
            SELECT id, nom, prenom, telephone, type_assurance, taux_prise_charge,
                   assurance2_nom, taux_assurance2, numero_assure
            FROM patients 
            WHERE LOWER(nom) = LOWER(%s) 
            AND LOWER(prenom) = LOWER(%s)
            AND structure_id = %s
        """, (patient_nom.strip(), patient_prenom.strip(), structure_id))
        
        # ⭐ SI LE PATIENT EST TROUVÉ → Utiliser ses infos
        if patient_info and len(patient_info) > 0:
            pat = patient_info[0]
            telephone = pat.get('telephone', '')
            type_assurance = pat.get('type_assurance', 'Non assuré')
            taux_prise_charge = pat.get('taux_prise_charge', 0)
            assurance2_nom = pat.get('assurance2_nom', '')
            taux_assurance2 = pat.get('taux_assurance2', 0)
            numero_assure = pat.get('numero_assure', '')
            print(f"✅ Patient trouvé: {patient_nom} {patient_prenom}")
        else:
            telephone = ''
            type_assurance = 'Non assuré'
            taux_prise_charge = 0
            assurance2_nom = ''
            taux_assurance2 = 0
            numero_assure = ''
            print(f"⚠️ Patient non trouvé: {patient_nom} {patient_prenom}")
        
        # ⭐ Récupérer les informations de la structure
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        structure = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
        
        # ⭐ Générer un numéro d'ordonnance unique
        num_ordonnance = generer_numero_ordonnance(structure_id)
        
        # ⭐ Récupérer les prix
        total = 0
        for a in prescriptions:
            prix_info = sheets_helper.get_prix_acte(structure_id, a.get('medicament'))
            prix = prix_info.get('prix', 0)
            pbr = prix_info.get('pbr', 0)
            a['prix_unitaire'] = prix
            a['pbr'] = pbr
            a['prix_total'] = prix
            total += prix
        
        # ⭐ Créer l'objet patient
        patient_obj = {
            'nom': patient_nom,
            'prenom': patient_prenom,
            'telephone': telephone or 'Non renseigné',
            'type_assurance': type_assurance,
            'taux_prise_charge': taux_prise_charge,
            'assurance2_nom': assurance2_nom,
            'taux_assurance2': taux_assurance2,
            'numero_assure': numero_assure or 'Non renseigné',
            'date_naissance': None
        }
        
        return render_template('ordonnance_actes.html',
                             prescriptions=prescriptions,
                             patient=patient_obj,
                             structure=structure,
                             num_ordonnance=num_ordonnance,
                             total=total,
                             format=format_impression,
                             now=datetime.now())
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Erreur: {str(e)}', 'danger')
        return redirect(url_for('prescriptions_recues'))

@app.route('/api/prix/produits', methods=['POST'])
@login_required
def api_prix_produits():
    """
    Récupère les prix de plusieurs produits depuis Google Sheets
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        data = request.json
        noms = data.get('noms', [])
        
        if not noms:
            return jsonify({'success': False, 'message': 'Liste de noms requise'}), 400
        
        resultats = {}
        for nom in noms:
            prix_info = sheets_helper.get_prix_produit(structure_id, nom)
            resultats[nom] = {
                'prix': prix_info.get('prix', 0),
                'pbr': prix_info.get('pbr', 0),
                'trouve': prix_info.get('trouve', False)
            }
        
        return jsonify({
            'success': True,
            'resultats': resultats
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/prix/actes', methods=['POST'])
@login_required
def api_prix_actes():
    """
    Récupère les prix de plusieurs actes depuis Google Sheets
    """
    structure_id = session.get('structure_id')
    
    if not structure_id:
        return jsonify({'success': False, 'message': 'Structure non trouvée'}), 401
    
    try:
        data = request.json
        noms = data.get('noms', [])
        
        if not noms:
            return jsonify({'success': False, 'message': 'Liste de noms requise'}), 400
        
        resultats = {}
        for nom in noms:
            prix_info = sheets_helper.get_prix_acte(structure_id, nom)
            resultats[nom] = {
                'prix': prix_info.get('prix', 0),
                'pbr': prix_info.get('pbr', 0),
                'trouve': prix_info.get('trouve', False)
            }
        
        return jsonify({
            'success': True,
            'resultats': resultats
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)