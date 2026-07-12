# models.py - GHP
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# ⭐ Créer db pour les modèles
db = SQLAlchemy()

# ============================================================
# STRUCTURE
# ============================================================
class Structure(db.Model):
    __tablename__ = 'structures'
    
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)
    adresse = db.Column(db.Text)
    telephone = db.Column(db.String(50))
    email = db.Column(db.String(100), unique=True)
    statut = db.Column(db.String(20), default='en_attente')
    logo_url = db.Column(db.String(500))
    primary_color = db.Column(db.String(7), default='#0d6efd')
    secondary_color = db.Column(db.String(7), default='#6c757d')
    reset_question = db.Column(db.String(255))
    reset_answer_hash = db.Column(db.String(255))
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    date_activation = db.Column(db.DateTime)
    
    utilisateurs = db.relationship('Utilisateur', backref='structure', lazy=True)
    patients = db.relationship('Patient', backref='structure', lazy=True)


# ============================================================
# UTILISATEUR
# ============================================================
class Utilisateur(db.Model):
    __tablename__ = 'utilisateurs'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nom = db.Column(db.String(100))
    prenom = db.Column(db.String(100))
    role = db.Column(db.String(50), default='admin')
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'))
    actif = db.Column(db.Boolean, default=True)
    reset_token = db.Column(db.String(255))
    reset_token_expiry = db.Column(db.DateTime)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_connexion = db.Column(db.DateTime)
    
    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)


# ============================================================
# PATIENT (version simplifiée - sans médecin référent)
# ============================================================
class Patient(db.Model):
    __tablename__ = 'patients'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Identité
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    date_naissance = db.Column(db.Date)
    telephone = db.Column(db.String(50))
    adresse = db.Column(db.Text)
    
    # Assurance
    type_assurance = db.Column(db.String(50))
    taux_prise_charge = db.Column(db.Float, default=0)
    numero_assure = db.Column(db.String(50))
    assurance2_nom = db.Column(db.String(100))
    taux_assurance2 = db.Column(db.Float, default=0)
    numero_assure2 = db.Column(db.String(50))
    personne_a_prevenir_nom = db.Column(db.String(100))
    personne_a_prevenir_telephone = db.Column(db.String(50))
    personne_a_prevenir_relation = db.Column(db.String(50))
    

# ============================================================
# STRUCTURE MAPPING (pour la synchronisation)
# ============================================================
class StructureMapping(db.Model):
    __tablename__ = 'structure_mappings'
    
    id = db.Column(db.Integer, primary_key=True)
    local_structure_id = db.Column(db.Integer, nullable=False)
    source_structure_id = db.Column(db.Integer, nullable=False)
    source_name = db.Column(db.String(50), default='ghp')
    api_url = db.Column(db.String(255), nullable=True)
    api_key = db.Column(db.String(255), nullable=True)
    last_sync = db.Column(db.DateTime, nullable=True)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PrescriptionRecue(db.Model):
    __tablename__ = 'prescriptions_recues'
    
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer)
    patient_nom = db.Column(db.String(100))
    patient_prenom = db.Column(db.String(100))
    medicament = db.Column(db.String(200), nullable=False)
    dosage = db.Column(db.String(50))
    forme = db.Column(db.String(50))
    quantite = db.Column(db.String(50))
    duree_jours = db.Column(db.Integer)
    frequence = db.Column(db.String(100))
    instructions = db.Column(db.Text)
    type_prescription = db.Column(db.String(20), default='medicament')
    date_prescription = db.Column(db.DateTime)
    prescripteur = db.Column(db.String(100))
    statut = db.Column(db.String(20), default='EN_ATTENTE')
    recu_le = db.Column(db.DateTime, default=datetime.utcnow)
    delivre_le = db.Column(db.DateTime)
    facture_le = db.Column(db.DateTime)