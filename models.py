# models.py - GHP
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, time, timedelta
from utils.db_failover import FailoverSession
# ⭐ Créer db pour les modèles
# session_options : voir utils/db_failover.py — route chaque requête vers
# Neon ou le Postgres local selon l'état de la bascule (inactif si
# DATABASE_URL_LOCAL n'est pas définie, donc aucun changement sur Render).
db = SQLAlchemy(session_options={'class_': FailoverSession})

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
    # Société souscriptrice de l'assurance complémentaire (ex: l'employeur qui
    # a souscrit le contrat groupe auprès de GTA/SUNU/NSIA...)
    societe_assurance2 = db.Column(db.String(150))
    personne_a_prevenir_nom = db.Column(db.String(100))
    personne_a_prevenir_telephone = db.Column(db.String(50))
    personne_a_prevenir_relation = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# SOCIÉTÉS SOUSCRIPTRICES D'ASSURANCE COMPLÉMENTAIRE
# ============================================================
# Une assurance complémentaire (GTA, SUNU, NSIA...) est en général souscrite
# par un employeur pour ses salariés (contrat groupe). Cette table mémorise,
# par structure et par assurance, les sociétés déjà saisies une première
# fois, pour proposer ensuite un simple choix au lieu d'une re-saisie.
class SocieteAssurance(db.Model):
    __tablename__ = 'societes_assurance'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    assurance_nom = db.Column(db.String(100), nullable=False)
    nom_societe = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('structure_id', 'assurance_nom', 'nom_societe', name='uq_societe_assurance'),
    )


# ============================================================
# STRUCTURE MAPPING (pour la synchronisation)
# ============================================================
class StructureMapping(db.Model):
    """⭐ Lien de synchronisation entre une structure gestion_patients et sa
    structure GHP correspondante (même mécanisme utilisé pour appairer une
    nouvelle clinique comme BIASA). Une ligne identique (même api_key) doit
    exister dans les deux bases pour que la synchro fonctionne — pas de
    schéma partagé entre les deux apps, chacune a sa propre copie.
    ⚠️ Les routes GHP existantes lisent tantôt local_structure_id, tantôt
    source_structure_id, comme si l'un ou l'autre était "l'id structure côté
    GHP" — pour rester compatible avec les deux, /sync/gestion-patients
    (routes self-service) pose systématiquement les deux au même id (celui
    de la structure GHP), voir sync_gestion_patients_activer() dans app.py."""
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

# ============================================================
# MODULES RH - CORRIGÉS AVEC structure_id
# ============================================================

class Service(db.Model):
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)  # ⭐ AJOUTÉ
    nom = db.Column(db.String(100), nullable=False)
    responsable = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    employes = db.relationship('Employe', backref='service', lazy=True)


class Employe(db.Model):
    __tablename__ = 'employes'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    matricule = db.Column(db.String(20), unique=True, nullable=False)
    
    # Identite
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    sexe = db.Column(db.String(10), nullable=False)
    date_naissance = db.Column(db.Date)
    age = db.Column(db.Integer)
    nationalite = db.Column(db.String(50))
    quartier = db.Column(db.String(200))
    telephone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    
    # Professionnel
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'))
    poste = db.Column(db.String(100))
    numero_poste = db.Column(db.String(20))
    date_embauche = db.Column(db.Date, nullable=False)
    type_contrat = db.Column(db.String(50))
    salaire_base = db.Column(db.Numeric, default=0)

    # ⭐ Paramètres de paie individuels (modifiables par salarié — chaque
    # agent peut déroger aux valeurs par défaut de ParametragePaie).
    # secteur_paie détermine l'organisme de retraite (CNSS/privé ou
    # CRT/public) et l'organisme AMU (AMU-CNSS ou AMU-INAM) appliqués.
    secteur_paie = db.Column(db.String(10), default='prive')  # 'prive' | 'public'
    personnes_a_charge = db.Column(db.Integer, default=0)     # 0 à 6 (déduction IRPP)
    # Dérogations individuelles aux taux — NULL = utiliser le défaut de la
    # structure (ParametragePaie) selon secteur_paie. Les taux AMU restent
    # verrouillés (salarial <= moitié du taux global, patronal >= moitié)
    # même en cas de dérogation individuelle — voir services/paie_service.py.
    taux_retraite_salarial_override = db.Column(db.Numeric)
    taux_retraite_patronal_override = db.Column(db.Numeric)
    taux_amu_salarial_override = db.Column(db.Numeric)
    taux_amu_patronal_override = db.Column(db.Numeric)

    # Urgence
    personne_a_prevenir = db.Column(db.String(200))
    telephone_prevenir = db.Column(db.String(20))
    lien_parente = db.Column(db.String(50))
    
    # Statut
    statut = db.Column(db.String(20), default='Actif')
    
    # Documents
    photo_url = db.Column(db.String(500))
    piece_identite_url = db.Column(db.String(500))
    contrat_url = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    conges = db.relationship('Conge', backref='employe', lazy=True)
    permissions = db.relationship('Permission', backref='employe', lazy=True)

    # Suivi des congés
    conges_annuels = db.Column(db.Integer, default=30)
    conges_pris_annee = db.Column(db.Integer, default=0)
    annee_reference = db.Column(db.Integer, default=lambda: datetime.now().year)
    

    def calculer_age(self):
        if self.date_naissance:
            today = date.today()
            return today.year - self.date_naissance.year - ((today.month, today.day) < (self.date_naissance.month, self.date_naissance.day))
        return None
    
    def calculer_anciennete(self):
        if self.date_embauche:
            today = date.today()
            years = today.year - self.date_embauche.year - ((today.month, today.day) < (self.date_embauche.month, self.date_embauche.day))
            return years
        return 0
    
    def solde_conges(self):
        """Solde total des congés (ancien système)"""
        anciennete_mois = self.calculer_anciennete() * 12
        total_acquis = anciennete_mois * 2.5
        conges_pris = db.session.query(db.func.sum(Conge.nombre_jours)).filter(
            Conge.employe_id == self.id,
            Conge.statut == 'approuve'
        ).scalar() or 0
        return total_acquis - conges_pris
    
    def get_solde_detail(self, annee):
        """⭐ Source UNIQUE de calcul du solde de congés (jours acquis moins
        congés + permissions pris sur l'année). Tout le reste (routes/rh.py
        compris) doit passer par cette méthode — plus de logique dupliquée."""
        conges_pris = db.session.query(db.func.sum(Conge.nombre_jours)).filter(
            Conge.employe_id == self.id,
            db.extract('year', Conge.date_debut) == annee,
            Conge.statut.in_(['en_attente', 'approuve', 'termine'])
        ).scalar() or 0

        permissions_pris = db.session.query(db.func.sum(Permission.nombre_jours)).filter(
            Permission.employe_id == self.id,
            db.extract('year', Permission.date_debut) == annee,
            Permission.statut.in_(['en_attente', 'approuve'])
        ).scalar() or 0

        total_annuel = self.conges_annuels or 30
        total_pris = conges_pris + permissions_pris
        solde = max(0, total_annuel - total_pris)

        return {
            'solde': solde,
            'pris': total_pris,
            'conges_pris': conges_pris,
            'permissions_pris': permissions_pris,
            'total_annuel': total_annuel,
        }

    def get_solde_par_annee(self, annee):
        """Retourne le solde de congés (nombre) pour une année donnée."""
        return self.get_solde_detail(annee)['solde']
    
    def solde_conges_restant(self):
        """Calcule le solde de congés restant pour l'année en cours (incluant les permissions)"""
        annee_actuelle = datetime.now().year
        
        if self.annee_reference != annee_actuelle:
            self.conges_pris_annee = 0
            self.annee_reference = annee_actuelle
            db.session.commit()
        
        # ⭐ Utiliser la nouvelle méthode
        solde = self.get_solde_par_annee(annee_actuelle)
        
        # ⭐ Mettre à jour le champ conges_pris_annee
        conges_pris = db.session.query(db.func.sum(Conge.nombre_jours)).filter(
            Conge.employe_id == self.id,
            db.extract('year', Conge.date_debut) == annee_actuelle,
            Conge.statut.in_(['en_attente', 'approuve', 'termine'])
        ).scalar() or 0
        
        permissions_pris = db.session.query(db.func.sum(Permission.nombre_jours)).filter(
            Permission.employe_id == self.id,
            db.extract('year', Permission.date_debut) == annee_actuelle,
            Permission.statut.in_(['en_attente', 'approuve'])
        ).scalar() or 0
        
        total_pris = conges_pris + permissions_pris
        
        if self.conges_pris_annee != total_pris:
            self.conges_pris_annee = total_pris
            db.session.commit()
        
        return solde
    
    def verifier_conges_disponibles(self, jours_demandes, annee=None):
        """
        Vérifie si le nombre de jours demandés est disponible
        Si annee est spécifiée, vérifie pour cette année
        """
        if annee is None:
            annee = datetime.now().year
        
        solde = self.get_solde_par_annee(annee)
        
        if jours_demandes <= solde:
            return {
                'disponible': True, 
                'solde': solde, 
                'annee': annee,
                'message': f'Solde disponible: {solde} jours en {annee}'
            }
        else:
            # ⭐ Vérifier les années futures
            annees_futures = []
            for an in range(annee + 1, annee + 6):
                solde_futur = self.get_solde_par_annee(an)
                if solde_futur > 0:
                    annees_futures.append({
                        'annee': an,
                        'solde': solde_futur,
                        'disponible': solde_futur >= jours_demandes
                    })
            
            return {
                'disponible': False, 
                'solde': solde,
                'annee': annee,
                'jours_demandes': jours_demandes,
                'annees_futures': annees_futures,
                'message': f'Solde insuffisant. Restant: {solde} jours en {annee}, Demandé: {jours_demandes} jours'
            }
    
    def verifier_solde_avec_anticipation(self, jours_demandes, annee_demande):
        """Vérifie le solde avec anticipation sur les années futures"""
        return self.verifier_conges_disponibles(jours_demandes, annee_demande)

 
    def mettre_a_jour_statut(self):
        """Met à jour le statut de l'employé en fonction des congés"""
        today = date.today()
        
        # ⭐ 1. Vérifier si l'employé a un congé en cours (approuvé)
        conge_en_cours = Conge.query.filter(
            Conge.employe_id == self.id,
            Conge.statut == 'approuve',
            Conge.date_debut <= today,
            Conge.date_fin >= today
        ).first()
        
        if conge_en_cours:
            self.statut = 'En conge'
            db.session.commit()
            return 'En conge'
        
        # ⭐ 2. Vérifier si l'employé a un congé approuvé qui commence aujourd'hui
        conge_commence = Conge.query.filter(
            Conge.employe_id == self.id,
            Conge.statut == 'approuve',
            Conge.date_debut == today
        ).first()
        
        if conge_commence:
            self.statut = 'En conge'
            db.session.commit()
            return 'En conge'
        
        # ⭐ 3. Vérifier si l'employé était en congé et que la reprise est passée
        conge_termine = Conge.query.filter(
            Conge.employe_id == self.id,
            Conge.statut == 'approuve',
            Conge.date_fin < today
        ).order_by(Conge.date_fin.desc()).first()
        
        if conge_termine:
            # Vérifier si la date de reprise est passée
            if conge_termine.date_reprise and conge_termine.date_reprise <= today:
                self.statut = 'Actif'
                db.session.commit()
                return 'Actif'
        
        # ⭐ 4. Vérifier si l'employé a un solde négatif (a dépassé ses congés)
        solde = self.solde_conges_restant()
        if solde < 0:
            # Vérifier s'il a un congé en attente ou approuvé
            conges_actifs = Conge.query.filter(
                Conge.employe_id == self.id,
                Conge.statut.in_(['en_attente', 'approuve']),
                Conge.date_fin >= today
            ).first()
            
            if conges_actifs:
                self.statut = 'En conge'
                db.session.commit()
                return 'En conge'
        
        # ⭐ 5. Par défaut, Actif
        self.statut = 'Actif'
        db.session.commit()
        return 'Actif'


class Conge(db.Model):
    __tablename__ = 'conges'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)
    
    type_conge = db.Column(db.String(50), nullable=False)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    date_reprise = db.Column(db.Date)
    nombre_jours = db.Column(db.Integer)
    annee_utilisation = db.Column(db.Integer, default=lambda: datetime.now().year)
    
    motif = db.Column(db.Text)
    piece_jointe = db.Column(db.String(500))
    signataire = db.Column(db.String(100))
    
    statut = db.Column(db.String(20), default='en_attente')
    approuve_par = db.Column(db.String(100))
    date_approbation = db.Column(db.Date)
    commentaire = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ========== MÉTHODES DE CALCUL ==========
    
    def calculer_jours_ouvres(self):
        """Calcule le nombre de jours ouvrés (du lundi au vendredi)"""
        from datetime import timedelta
        count = 0
        current = self.date_debut
        while current <= self.date_fin:
            if current.weekday() < 5:  # Lundi=0, Dimanche=6
                count += 1
            current += timedelta(days=1)
        return count
    
    def calculer_date_reprise(self):
        """Calcule la date de reprise = date_fin + 1 jour"""
        from datetime import timedelta
        return self.date_fin + timedelta(days=1)

class Permission(db.Model):
    __tablename__ = 'permissions'

    id = db.Column(db.Integer, primary_key=True)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)
    # ⭐ Cohérence multi-structure avec les autres tables RH (Employe, Conge,
    # Service, DocumentRH) — backfillé depuis employe.structure_id.
    structure_id = db.Column(db.Integer)

    type_permission = db.Column(db.String(20), default='heures')
    
    date_permission = db.Column(db.Date, nullable=True)
    heure_debut = db.Column(db.Time, nullable=True)
    heure_fin = db.Column(db.Time, nullable=True)
    
    date_debut = db.Column(db.Date, nullable=True)
    date_fin = db.Column(db.Date, nullable=True)
    
    nombre_jours = db.Column(db.Integer, default=1)

    motif = db.Column(db.Text, nullable=False)
    signataire = db.Column(db.String(100))
    
    statut = db.Column(db.String(20), default='en_attente')
    approuve_par = db.Column(db.String(100))
    date_approbation = db.Column(db.Date)
    commentaire = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DocumentRH(db.Model):
    __tablename__ = 'documents_rh'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)  # ⭐ AJOUTÉ
    type_document = db.Column(db.String(20), nullable=False)
    numero_ordre = db.Column(db.String(50), unique=True)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'))
    contenu_pdf = db.Column(db.Text)
    statut = db.Column(db.String(20), default='brouillon')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SignatureRH(db.Model):
    __tablename__ = 'signatures_rh'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents_rh.id'))
    validateur_niveau = db.Column(db.Integer)
    validateur_nom = db.Column(db.String(100))
    statut = db.Column(db.String(20), default='en_attente')
    signature_nom = db.Column(db.String(100))
    signature_date = db.Column(db.Date)
    commentaire = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================================
# COMPTABILITE - MODELES (CORRIGES)
# ============================================================

class CompteComptable(db.Model):
    __tablename__ = 'comptes_comptables'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    numero = db.Column(db.String(20), nullable=False)
    nom = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    classe = db.Column(db.String(10))
    parent_id = db.Column(db.Integer, db.ForeignKey('comptes_comptables.id'))
    niveau = db.Column(db.Integer, default=1)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    enfants = db.relationship('CompteComptable', backref='parent', remote_side=[id])
    lignes = db.relationship('LigneEcriture', backref='compte', lazy=True)
    
    def get_solde(self, date_debut=None, date_fin=None):
        query = db.session.query(db.func.sum(LigneEcriture.debit - LigneEcriture.credit)).filter(
            LigneEcriture.compte_id == self.id
        )
        if date_debut:
            query = query.filter(LigneEcriture.ecriture.has(EcritureComptable.date_ecriture >= date_debut))
        if date_fin:
            query = query.filter(LigneEcriture.ecriture.has(EcritureComptable.date_ecriture <= date_fin))
        return query.scalar() or 0


class EcritureComptable(db.Model):
    __tablename__ = 'ecritures_comptables'

    # Journaux auxiliaires (journaux divisionnaires SYSCOHADA)
    JOURNAUX = {
        'VTE': "Journal des ventes",
        'CAI': "Journal de caisse",
        'BQ': "Journal de banque",
        'ACH': "Journal des achats",
        'SAL': "Journal des salaires",
        'TR': "Journal de trésorerie",
        'OD': "Journal des opérations diverses",
    }

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    date_ecriture = db.Column(db.Date, nullable=False)
    libelle = db.Column(db.Text, nullable=False)
    piece_justificative = db.Column(db.String(100))
    statut = db.Column(db.String(20), default='brouillon')
    created_by = db.Column(db.Integer, nullable=True)          # Sans ForeignKey
    created_by_nom = db.Column(db.String(100))
    validated_by = db.Column(db.Integer, nullable=True)        # Sans ForeignKey
    validated_by_nom = db.Column(db.String(100))
    date_validation = db.Column(db.Date)
    commentaire = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cloturee = db.Column(db.Boolean, default=False)
    date_cloture = db.Column(db.DateTime)

    # ⭐ Automatisation (voir services/comptabilite_service.py)
    journal_code = db.Column(db.String(10))          # VTE / CAI / BQ / ACH / OD
    source_type = db.Column(db.String(50))           # 'vente', 'paiement_facture', ...
    source_id = db.Column(db.Integer)                # id de l'objet source
    generee_auto = db.Column(db.Boolean, default=False)
    generation_erreur = db.Column(db.Text)            # renseigné si une génération auto a échoué

    lignes = db.relationship('LigneEcriture', backref='ecriture', lazy=True, cascade='all, delete-orphan')
    validations = db.relationship('ValidationComptable', backref='ecriture', lazy=True)

    def get_journal_label(self):
        return self.JOURNAUX.get(self.journal_code, self.journal_code or '-')

    def est_equilibree(self):
        total_debit = sum(l.debit for l in self.lignes) or 0
        total_credit = sum(l.credit for l in self.lignes) or 0
        return total_debit == total_credit
    
    def get_total_debit(self):
        return sum(l.debit for l in self.lignes) or 0
    
    def get_total_credit(self):
        return sum(l.credit for l in self.lignes) or 0
    
    def get_statut_label(self):
        labels = {
            'brouillon': 'Brouillon',
            'en_attente': 'En attente',
            'valide': 'Validee',
            'refuse': 'Refusee',
            'annulee': 'Annulee'
        }
        return labels.get(self.statut, self.statut)


class LigneEcriture(db.Model):
    __tablename__ = 'lignes_ecritures'
    
    id = db.Column(db.Integer, primary_key=True)
    ecriture_id = db.Column(db.Integer, db.ForeignKey('ecritures_comptables.id'), nullable=False)
    compte_id = db.Column(db.Integer, db.ForeignKey('comptes_comptables.id'), nullable=False)
    debit = db.Column(db.Numeric, default=0)
    credit = db.Column(db.Numeric, default=0)
    libelle = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Budget(db.Model):
    __tablename__ = 'budget'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    compte_id = db.Column(db.Integer, db.ForeignKey('comptes_comptables.id'))
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    montant_prevu = db.Column(db.Numeric, default=0)
    montant_reel = db.Column(db.Numeric, default=0)
    ecart = db.Column(db.Numeric, default=0)
    commentaire = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ValidationComptable(db.Model):
    __tablename__ = 'validations_comptables'
    
    id = db.Column(db.Integer, primary_key=True)
    ecriture_id = db.Column(db.Integer, db.ForeignKey('ecritures_comptables.id'), nullable=False)
    niveau = db.Column(db.Integer, default=1)
    statut = db.Column(db.String(20), default='en_attente')
    valide_par = db.Column(db.Integer, nullable=True)          # Sans ForeignKey
    valide_par_nom = db.Column(db.String(100))
    date_validation = db.Column(db.Date)
    commentaire = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class HistoriqueEcriture(db.Model):
    __tablename__ = 'historique_ecritures'
    
    id = db.Column(db.Integer, primary_key=True)
    ecriture_id = db.Column(db.Integer, db.ForeignKey('ecritures_comptables.id'))
    action = db.Column(db.String(50), nullable=False)
    ancien_statut = db.Column(db.String(20))
    nouveau_statut = db.Column(db.String(20))
    modifie_par = db.Column(db.Integer, nullable=True)         # Sans ForeignKey
    modifie_par_nom = db.Column(db.String(100))
    commentaire = db.Column(db.Text)
    date_action = db.Column(db.DateTime, default=datetime.utcnow)

# models.py - Ajouter à la fin de la section comptabilité

class Cloture(db.Model):
    __tablename__ = 'clotures'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    date_cloture = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# models.py - Ajouter à la fin de la section comptabilité

class ReleveBancaire(db.Model):
    __tablename__ = 'releves_bancaires'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    # ⭐ Compte de trésorerie (classe 5) concerné par ce relevé — permet de
    # gérer plusieurs comptes bancaires/caisses séparément. NULL = ancien
    # relevé créé avant cette colonne, traité comme le compte "521 Banque"
    # par défaut dans le code.
    compte_id = db.Column(db.Integer, db.ForeignKey('comptes_comptables.id'), nullable=True)
    date_releve = db.Column(db.Date, nullable=False)
    solde_initial = db.Column(db.Numeric, default=0)
    solde_final = db.Column(db.Numeric, default=0)
    total_credits = db.Column(db.Numeric, default=0)
    total_debits = db.Column(db.Numeric, default=0)
    statut = db.Column(db.String(20), default='brouillon')  # brouillon, en_attente, valide
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    valide_par = db.Column(db.String(100))
    date_validation = db.Column(db.Date)
    
    lignes = db.relationship('LigneReleve', backref='releve', lazy=True, cascade='all, delete-orphan')


class LigneReleve(db.Model):
    __tablename__ = 'lignes_releves'
    
    id = db.Column(db.Integer, primary_key=True)
    releve_id = db.Column(db.Integer, db.ForeignKey('releves_bancaires.id'), nullable=False)
    date_operation = db.Column(db.Date, nullable=False)
    libelle = db.Column(db.Text, nullable=False)
    reference = db.Column(db.String(100))
    debit = db.Column(db.Numeric, default=0)
    credit = db.Column(db.Numeric, default=0)
    solde = db.Column(db.Numeric, default=0)
    rapproche = db.Column(db.Boolean, default=False)
    ecriture_id = db.Column(db.Integer, db.ForeignKey('ecritures_comptables.id'), nullable=True)
    commentaire = db.Column(db.Text)


# ============================================================
# ANOMALIES COMPTABLES (génération automatique d'écritures en échec)
# ============================================================

class AnomalieComptable(db.Model):
    __tablename__ = 'anomalies_comptables'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    source_type = db.Column(db.String(50))   # 'vente', 'paiement_facture', ...
    source_id = db.Column(db.Integer)
    message = db.Column(db.Text, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    resolu = db.Column(db.Boolean, default=False)
    resolu_par = db.Column(db.String(100))
    date_resolution = db.Column(db.DateTime)
    commentaire = db.Column(db.Text)


# ============================================================
# IMMOBILISATIONS & AMORTISSEMENTS
# ============================================================

class Immobilisation(db.Model):
    __tablename__ = 'immobilisations'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    designation = db.Column(db.String(255), nullable=False)
    categorie = db.Column(db.String(100))
    compte_immo_numero = db.Column(db.String(20), nullable=False)   # ex: 2183
    compte_amort_numero = db.Column(db.String(20), nullable=False)  # ex: 2818
    date_acquisition = db.Column(db.Date, nullable=False)
    valeur_acquisition = db.Column(db.Numeric, nullable=False, default=0)
    valeur_residuelle = db.Column(db.Numeric, default=0)
    duree_annees = db.Column(db.Integer, nullable=False, default=5)
    statut = db.Column(db.String(20), default='en_service')  # en_service, cede, reforme
    date_cession = db.Column(db.Date)
    valeur_cession = db.Column(db.Numeric)
    cumul_amorti = db.Column(db.Numeric, default=0)
    mode_paiement = db.Column(db.String(50), default='especes')
    ecriture_acquisition_id = db.Column(db.Integer)
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    dotations = db.relationship('DotationAmortissement', backref='immobilisation', lazy=True)

    def valeur_nette_comptable(self):
        return float(self.valeur_acquisition or 0) - float(self.cumul_amorti or 0)

    def base_amortissable(self):
        return float(self.valeur_acquisition or 0) - float(self.valeur_residuelle or 0)

    def dotation_annuelle_theorique(self):
        if not self.duree_annees:
            return 0
        return self.base_amortissable() / self.duree_annees


class DotationAmortissement(db.Model):
    __tablename__ = 'dotations_amortissement'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    immobilisation_id = db.Column(db.Integer, db.ForeignKey('immobilisations.id'), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Numeric, nullable=False)
    date_generation = db.Column(db.DateTime, default=datetime.utcnow)
    ecriture_id = db.Column(db.Integer)
    created_by = db.Column(db.String(100))


# ============================================================
# PROVISIONS POUR CRÉANCES DOUTEUSES
# ============================================================

class ProvisionCreance(db.Model):
    __tablename__ = 'provisions_creances'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    facture_id = db.Column(db.Integer)
    patient_id = db.Column(db.Integer)
    patient_nom = db.Column(db.String(255))
    montant_creance = db.Column(db.Numeric, nullable=False)
    taux_provision = db.Column(db.Numeric, nullable=False, default=50)
    montant_provisionne = db.Column(db.Numeric, nullable=False)
    statut = db.Column(db.String(20), default='active')  # active, reprise, perte
    ecriture_provision_id = db.Column(db.Integer)
    ecriture_reprise_id = db.Column(db.Integer)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_cloture = db.Column(db.DateTime)
    created_by = db.Column(db.String(100))
    commentaire = db.Column(db.Text)


# models.py - Modèle Vente EXACT (correspond à ta base)

class Vente(db.Model):
    __tablename__ = 'ventes'
    
    # ⭐ Colonnes existantes dans ta base
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255), nullable=False)
    structure_id = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    sous_total = db.Column(db.Float, default=0)
    prise_en_charge = db.Column(db.Float, default=0)
    net_a_payer = db.Column(db.Float, default=0)
    mode_paiement = db.Column(db.String(50), default='especes')
    taux_assurance = db.Column(db.Integer, default=0)
    date_vente = db.Column(db.DateTime, default=datetime.utcnow)
    actes = db.Column(db.JSON)
    produits = db.Column(db.JSON)
    statut = db.Column(db.String(50), default='validee')
    annulee_le = db.Column(db.DateTime)
    annulee_par = db.Column(db.Integer)
    motif_annulation = db.Column(db.String(255))
    created_by_nom = db.Column(db.String(100))
    vendeur = db.Column(db.String(100))
    assurance = db.Column(db.String(50))
    numero_assure = db.Column(db.String(50))
    assurances = db.Column(db.JSON)
    assurance2_nom = db.Column(db.String(100))
    taux_assurance2 = db.Column(db.Float, default=0)
    prise_en_charge2 = db.Column(db.Float, default=0)
    numero_assure2 = db.Column(db.String(50))
    # Société souscriptrice de l'assurance complémentaire, capturée au moment
    # de la vente (même logique que assurance2_nom/taux_assurance2 : un
    # instantané, pas une référence vivante vers le patient).
    societe_assurance2 = db.Column(db.String(150))
    montant_donne = db.Column(db.Float, default=0)
    rendu = db.Column(db.Float, default=0)
    reste_a_payer = db.Column(db.Float, default=0)
    base_remboursement = db.Column(db.Float, default=0)
    taux_temp_modifie = db.Column(db.Boolean, default=False)
    taux_original = db.Column(db.Float, default=0)
    
    # ⭐ Colonnes d'automatisation
    categorie_actes = db.Column(db.JSON, default=[])
    traite_comptable = db.Column(db.Boolean, default=False)
    ecriture_generee = db.Column(db.Boolean, default=False)
    ecriture_id = db.Column(db.Integer, nullable=True)
    # ⭐ Séparation des journaux (non-mélange SYSCOHADA) : `ecriture_id` porte
    # la reconnaissance de la vente (journal VEN — créance client/assurance,
    # produit), toujours générée. `ecriture_encaissement_id` porte le SEUL
    # mouvement de trésorerie (journal CAI/BQ — extinction de la créance
    # client par le montant réellement encaissé), générée uniquement si le
    # patient a payé quelque chose sur le moment. Les deux entrées restent
    # liées par la même pièce (VTE-<id> / ENC-<id>) mais dans des journaux
    # distincts — voir generer_ecriture_vente().
    ecriture_encaissement_id = db.Column(db.Integer, nullable=True)

    # ⭐ Prescription IDs
    prescription_ids = db.Column(db.JSON, default=[])
    
    assurance_principale_active = db.Column(db.Boolean, default=True)

    # ⭐ NOUVELLES COLONNES À AJOUTER
    taux_aide = db.Column(db.Float, default=0)
    aide_hospitaliere = db.Column(db.Float, default=0)
    proforma_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ============================================================
# MODÈLES POUR LES MÉDECINS ET RENDEZ-VOUS
# ============================================================

class Medecin(db.Model):
    """
    Modèle pour les médecins de la clinique
    """
    __tablename__ = 'medecins'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Identité
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100))
    titre = db.Column(db.String(20), default='Dr')  # Dr, Pr, etc.
    sexe = db.Column(db.String(10))
    date_naissance = db.Column(db.Date)
    telephone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    
    # Professionnel
    specialite = db.Column(db.String(100), nullable=False)
    sous_specialite = db.Column(db.String(100))
    numero_ordre = db.Column(db.String(50))  # Numéro d'inscription à l'ordre
    annees_experience = db.Column(db.Integer)
    
    # Honoraires
    honoraire_consultation = db.Column(db.Float, default=0)
    honoraire_visite = db.Column(db.Float, default=0)
    honoraire_acte = db.Column(db.Float, default=0)
    taux_partage = db.Column(db.Float, default=0)  # Pourcentage pour la clinique
    
    # Horaires par défaut
    horaire_debut = db.Column(db.Time, default='08:00:00')
    horaire_fin = db.Column(db.Time, default='17:00:00')
    duree_consultation = db.Column(db.Integer, default=30)  # en minutes
    jours_travail = db.Column(db.JSON, default=['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'])
    
    # Statut
    actif = db.Column(db.Boolean, default=True)
    disponible = db.Column(db.Boolean, default=True)
    remarques = db.Column(db.Text)
    
    # Photo
    photo_url = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='medecins')
    rendez_vous = db.relationship('RendezVous', backref='medecin', lazy=True)
    
    def get_nom_complet(self):
        """Retourne le nom complet du médecin avec son titre"""
        return f"{self.titre} {self.prenom or ''} {self.nom}".strip()
    
    def get_honoraire(self, type_consultation='consultation'):
        """Retourne l'honoraire selon le type"""
        if type_consultation == 'consultation':
            return self.honoraire_consultation or 0
        elif type_consultation == 'visite':
            return self.honoraire_visite or 0
        elif type_consultation == 'acte':
            return self.honoraire_acte or 0
        return 0
    
    def est_disponible(self, date, heure):
        """Vérifie si le médecin est disponible à une date et heure donnée"""
        from datetime import datetime, time
        
        if not self.actif or not self.disponible:
            return False
        
        # Vérifier le jour de la semaine
        jours_semaine = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
        jour_semaine = jours_semaine[date.weekday()]
        if jour_semaine not in (self.jours_travail or []):
            return False
        
        # Vérifier les horaires
        heure_obj = datetime.strptime(heure, '%H:%M').time() if isinstance(heure, str) else heure
        if heure_obj < self.horaire_debut or heure_obj > self.horaire_fin:
            return False
        
        # Vérifier les rendez-vous existants
        rdv_conflict = RendezVous.query.filter(
            RendezVous.medecin_id == self.id,
            RendezVous.date_rendez_vous == date,
            RendezVous.statut.in_(['programme', 'confirme']),
            RendezVous.heure_rendez_vous == heure
        ).first()
        
        return rdv_conflict is None
    
    def get_consultations_mois(self, annee=None, mois=None):
        """Retourne le nombre de consultations pour un mois donné"""
        if annee is None:
            annee = datetime.now().year
        if mois is None:
            mois = datetime.now().month
        
        return RendezVous.query.filter(
            RendezVous.medecin_id == self.id,
            db.extract('year', RendezVous.date_rendez_vous) == annee,
            db.extract('month', RendezVous.date_rendez_vous) == mois,
            RendezVous.statut == 'termine'
        ).count()
    
    def get_honoraires_mois(self, annee=None, mois=None):
        """Retourne le total des honoraires pour un mois donné"""
        if annee is None:
            annee = datetime.now().year
        if mois is None:
            mois = datetime.now().month
        
        consultations = RendezVous.query.filter(
            RendezVous.medecin_id == self.id,
            db.extract('year', RendezVous.date_rendez_vous) == annee,
            db.extract('month', RendezVous.date_rendez_vous) == mois,
            RendezVous.statut == 'termine'
        ).count()
        
        return consultations * (self.honoraire_consultation or 0)
    
    def to_dict(self):
        """Convertit en dictionnaire pour l'API"""
        return {
            'id': self.id,
            'nom': self.nom,
            'prenom': self.prenom,
            'titre': self.titre,
            'nom_complet': self.get_nom_complet(),
            'specialite': self.specialite,
            'telephone': self.telephone,
            'email': self.email,
            'honoraire_consultation': self.honoraire_consultation,
            'actif': self.actif,
            'disponible': self.disponible,
            'photo_url': self.photo_url
        }


class RendezVous(db.Model):
    """
    Modèle pour les rendez-vous des patients
    """
    __tablename__ = 'rendez_vous'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Patient
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    patient_nom = db.Column(db.String(200), nullable=False)
    patient_telephone = db.Column(db.String(20))
    patient_email = db.Column(db.String(100))
    
    # Médecin
    medecin_id = db.Column(db.Integer, db.ForeignKey('medecins.id'), nullable=False)
    
    # Date et heure
    date_rendez_vous = db.Column(db.Date, nullable=False)
    heure_rendez_vous = db.Column(db.String(10), nullable=False)  # Format: HH:MM
    duree = db.Column(db.Integer, default=30)  # en minutes
    date_fin = db.Column(db.DateTime)  # Calculé automatiquement
    
    # Détails
    motif = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text)
    type_consultation = db.Column(db.String(50), default='consultation')
    priorite = db.Column(db.String(20), default='normal')  # normal, urgent, prioritaire
    
    # Statut
    statut = db.Column(db.String(20), default='programme')
    # programme, confirme, termine, annule, reporte, absent
    
    # Suivi
    rappel_envoye = db.Column(db.Boolean, default=False)
    date_rappel = db.Column(db.DateTime)
    confirme_le = db.Column(db.DateTime)
    termine_le = db.Column(db.DateTime)
    
    # Création
    created_by = db.Column(db.Integer)  # ID de l'utilisateur
    created_by_nom = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='rendez_vous')
    patient = db.relationship('Patient', backref='rendez_vous')
    # medecin est déjà défini via backref
    
    def __init__(self, **kwargs):
        super(RendezVous, self).__init__(**kwargs)
        # Calculer automatiquement la date de fin
        if self.date_rendez_vous and self.heure_rendez_vous and self.duree:
            from datetime import datetime, timedelta
            # [:5] car certains rendez-vous ont été enregistrés avec les
            # secondes (ex. "08:00:00") — on ne garde que HH:MM
            date_heure = datetime.combine(
                self.date_rendez_vous,
                datetime.strptime(self.heure_rendez_vous[:5], '%H:%M').time()
            )
            self.date_fin = date_heure + timedelta(minutes=self.duree)
    
    def get_statut_label(self):
        """Retourne le libellé du statut"""
        labels = {
            'programme': 'Programmé',
            'confirme': 'Confirmé',
            'termine': 'Terminé',
            'annule': 'Annulé',
            'reporte': 'Reporté',
            'absent': 'Absent'
        }
        return labels.get(self.statut, self.statut)
    
    def get_statut_badge_class(self):
        """Retourne la classe CSS pour le badge de statut"""
        classes = {
            'programme': 'bg-warning text-dark',
            'confirme': 'bg-success',
            'termine': 'bg-secondary',
            'annule': 'bg-danger',
            'reporte': 'bg-info',
            'absent': 'bg-dark'
        }
        return classes.get(self.statut, 'bg-secondary')
    
    def est_depasse(self):
        """Vérifie si le rendez-vous est dépassé"""
        if self.statut in ['annule', 'termine', 'absent']:
            return False
        from datetime import datetime
        date_heure = datetime.combine(
            self.date_rendez_vous,
            datetime.strptime(self.heure_rendez_vous[:5], '%H:%M').time()
        )
        return date_heure < datetime.now()
    
    def peut_annuler(self):
        """Vérifie si le rendez-vous peut être annulé"""
        return self.statut in ['programme', 'confirme']
    
    def peut_modifier(self):
        """Vérifie si le rendez-vous peut être modifié"""
        return self.statut not in ['annule', 'termine', 'absent']
    
    def confirmer(self):
        """Confirme le rendez-vous"""
        if self.statut == 'programme':
            self.statut = 'confirme'
            self.confirme_le = datetime.utcnow()
            return True
        return False
    
    def terminer(self):
        """Marque le rendez-vous comme terminé"""
        if self.statut in ['programme', 'confirme']:
            self.statut = 'termine'
            self.termine_le = datetime.utcnow()
            return True
        return False
    
    def annuler(self, motif=None):
        """Annule le rendez-vous"""
        if self.peut_annuler():
            self.statut = 'annule'
            if motif:
                self.notes = (self.notes or '') + f"\nMotif annulation: {motif}"
            return True
        return False
    
    def reporter(self, nouvelle_date, nouvelle_heure, nouveau_medecin_id=None):
        """Reporte le rendez-vous à une nouvelle date/heure"""
        if self.peut_modifier():
            ancien_medecin = self.medecin_id
            self.date_rendez_vous = nouvelle_date
            self.heure_rendez_vous = nouvelle_heure
            if nouveau_medecin_id:
                self.medecin_id = nouveau_medecin_id
            self.statut = 'reporte'
            self.notes = (self.notes or '') + f"\nReporté du {self.date_rendez_vous} au {nouvelle_date} à {nouvelle_heure}"
            if nouveau_medecin_id and nouveau_medecin_id != ancien_medecin:
                self.notes += f" (Médecin: {self.medecin.get_nom_complet()})"
            return True
        return False
    
    def to_dict(self):
        """Convertit en dictionnaire pour l'API"""
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'patient_nom': self.patient_nom,
            'patient_telephone': self.patient_telephone,
            'medecin_id': self.medecin_id,
            'medecin_nom': self.medecin.get_nom_complet() if self.medecin else None,
            'medecin_specialite': self.medecin.specialite if self.medecin else None,
            'date': self.date_rendez_vous.isoformat() if self.date_rendez_vous else None,
            'heure': self.heure_rendez_vous,
            'duree': self.duree,
            'motif': self.motif,
            'notes': self.notes,
            'statut': self.statut,
            'statut_label': self.get_statut_label(),
            'statut_badge': self.get_statut_badge_class(),
            'est_depasse': self.est_depasse(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class HistoriqueRendezVous(db.Model):
    """
    Historique des actions sur les rendez-vous
    """
    __tablename__ = 'historique_rendez_vous'
    
    id = db.Column(db.Integer, primary_key=True)
    rendez_vous_id = db.Column(db.Integer, db.ForeignKey('rendez_vous.id'), nullable=False)
    
    action = db.Column(db.String(50), nullable=False)  # creation, confirmation, annulation, report, etc.
    ancien_statut = db.Column(db.String(20))
    nouveau_statut = db.Column(db.String(20))
    anciennes_donnees = db.Column(db.JSON)
    nouvelles_donnees = db.Column(db.JSON)
    
    utilisateur_id = db.Column(db.Integer)
    utilisateur_nom = db.Column(db.String(100))
    ip_adresse = db.Column(db.String(50))
    commentaire = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relation
    rendez_vous = db.relationship('RendezVous', backref='historique')


class DisponibiliteMedecin(db.Model):
    """
    Gestion des disponibilités spécifiques des médecins
    (congés, jours fériés, horaires exceptionnels)
    """
    __tablename__ = 'disponibilites_medecins'
    
    id = db.Column(db.Integer, primary_key=True)
    medecin_id = db.Column(db.Integer, db.ForeignKey('medecins.id'), nullable=False)
    
    type = db.Column(db.String(20), nullable=False)  # conge, ferie, exception, indisponible
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    heure_debut = db.Column(db.Time)
    heure_fin = db.Column(db.Time)
    
    motif = db.Column(db.String(255))
    approuve_par = db.Column(db.String(100))
    commentaire = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relation
    medecin = db.relationship('Medecin', backref='disponibilites')
    
    def est_disponible(self, date):
        """Vérifie si le médecin est disponible à une date donnée"""
        return not (self.date_debut <= date <= self.date_fin)


class RendezVousStats(db.Model):
    """
    Statistiques agrégées des rendez-vous (pour performance)
    """
    __tablename__ = 'rendez_vous_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    medecin_id = db.Column(db.Integer, db.ForeignKey('medecins.id'), nullable=False)
    
    mois = db.Column(db.Integer, nullable=False)  # 1-12
    annee = db.Column(db.Integer, nullable=False)
    
    nb_consultations = db.Column(db.Integer, default=0)
    nb_consultations_terminees = db.Column(db.Integer, default=0)
    nb_annulations = db.Column(db.Integer, default=0)
    nb_absences = db.Column(db.Integer, default=0)
    
    total_honoraires = db.Column(db.Float, default=0)
    taux_occupation = db.Column(db.Float, default=0)  # Pourcentage
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='rdv_stats')
    medecin = db.relationship('Medecin', backref='rdv_stats')
    
    @classmethod
    def calculer_stats(cls, medecin_id, mois, annee):
        """Calcule et met à jour les stats pour un médecin"""
        from datetime import datetime
        
        # Compter les rendez-vous
        rdvs = RendezVous.query.filter(
            RendezVous.medecin_id == medecin_id,
            db.extract('month', RendezVous.date_rendez_vous) == mois,
            db.extract('year', RendezVous.date_rendez_vous) == annee
        ).all()
        
        stats = {
            'nb_consultations': len(rdvs),
            'nb_consultations_terminees': sum(1 for r in rdvs if r.statut == 'termine'),
            'nb_annulations': sum(1 for r in rdvs if r.statut == 'annule'),
            'nb_absences': sum(1 for r in rdvs if r.statut == 'absent'),
            'total_honoraires': 0
        }
        
        # Calculer les honoraires
        medecin = Medecin.query.get(medecin_id)
        if medecin:
            stats['total_honoraires'] = stats['nb_consultations_terminees'] * (medecin.honoraire_consultation or 0)
        
        # Taux d'occupation (estimation)
        jours_ouvres = 22  # Mois moyen
        stats['taux_occupation'] = min(100, (stats['nb_consultations'] / (jours_ouvres * 8)) * 100) if jours_ouvres > 0 else 0
        
        # Mettre à jour ou créer
        stat_record = cls.query.filter(
            cls.medecin_id == medecin_id,
            cls.mois == mois,
            cls.annee == annee
        ).first()
        
        if stat_record:
            for key, value in stats.items():
                setattr(stat_record, key, value)
            stat_record.updated_at = datetime.utcnow()
        else:
            stat_record = cls(
                structure_id=medecin.structure_id if medecin else None,
                medecin_id=medecin_id,
                mois=mois,
                annee=annee,
                **stats
            )
            db.session.add(stat_record)
        
        db.session.commit()
        return stat_record


# models.py - À ajouter dans la section COMPTABILITE, après Cloture

class SequencePiece(db.Model):
    """
    Gestion des séquences de numéros de pièce comptable
    Chaque structure a ses propres séquences par type de pièce et par année
    """
    __tablename__ = 'sequences_piece'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Type de pièce (ecriture, facture, avoir, bon, etc.)
    type_piece = db.Column(db.String(50), nullable=False, index=True)
    
    # Préfixe (ex: ECR, FAC, AVO, BON)
    prefixe = db.Column(db.String(10), nullable=False)
    
    # Numéro actuel (incrémenté automatiquement)
    numero_actuel = db.Column(db.Integer, default=0, nullable=False)
    
    # Année de référence
    annee = db.Column(db.Integer, nullable=False, index=True)
    
    # Format d'affichage
    # Exemple: {prefixe}-{annee}-{numero:06d} -> ECR-2026-000042
    format_affichage = db.Column(db.String(100), default='{prefixe}-{annee}-{numero:06d}')
    
    # Dates
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Contrainte d'unicité
    __table_args__ = (
        db.UniqueConstraint('structure_id', 'type_piece', 'annee', name='uq_sequence_structure_type_annee'),
    )
    
    @classmethod
    def get_next_number(cls, structure_id, type_piece, prefixe=None):
        """
        Récupère et incrémente le prochain numéro de pièce
        
        Args:
            structure_id: ID de la structure
            type_piece: Type de pièce (ecriture, facture, etc.)
            prefixe: Préfixe personnalisé (optionnel)
        
        Returns:
            str: Numéro de pièce formaté
        """
        now = datetime.now()
        annee = now.year
        
        # Déterminer le préfixe par défaut selon le type
        prefixes_par_defaut = {
            'ecriture': 'ECR',
            'facture': 'FAC',
            'avoir': 'AVO',
            'bon': 'BON',
            'paiement': 'PAI',
            'recette': 'REC',
            'depense': 'DEP'
        }
        
        if not prefixe:
            prefixe = prefixes_par_defaut.get(type_piece, 'PCE')
        
        # Chercher la séquence existante
        sequence = cls.query.filter_by(
            structure_id=structure_id,
            type_piece=type_piece,
            annee=annee
        ).first()
        
        if not sequence:
            # Créer une nouvelle séquence pour l'année
            sequence = cls(
                structure_id=structure_id,
                type_piece=type_piece,
                prefixe=prefixe,
                annee=annee,
                numero_actuel=0
            )
            db.session.add(sequence)
            db.session.flush()
        
        # Incrémenter le numéro
        sequence.numero_actuel += 1
        sequence.updated_at = datetime.utcnow()
        
        # Formater le numéro
        numero_formate = sequence.format_affichage.format(
            prefixe=sequence.prefixe,
            annee=sequence.annee,
            numero=sequence.numero_actuel
        )
        
        db.session.commit()
        
        return numero_formate
    
    @classmethod
    def get_current_number(cls, structure_id, type_piece, annee=None):
        """Récupère le numéro actuel sans l'incrémenter"""
        if not annee:
            annee = datetime.now().year
        
        sequence = cls.query.filter_by(
            structure_id=structure_id,
            type_piece=type_piece,
            annee=annee
        ).first()
        
        if not sequence:
            return None
        
        return sequence.format_affichage.format(
            prefixe=sequence.prefixe,
            annee=sequence.annee,
            numero=sequence.numero_actuel
        )
    
    @classmethod
    def reset_sequence(cls, structure_id, type_piece, annee=None):
        """Réinitialise une séquence à zéro (à utiliser avec précaution)"""
        if not annee:
            annee = datetime.now().year
        
        sequence = cls.query.filter_by(
            structure_id=structure_id,
            type_piece=type_piece,
            annee=annee
        ).first()
        
        if sequence:
            sequence.numero_actuel = 0
            sequence.updated_at = datetime.utcnow()
            db.session.commit()
            return True
        return False
    
    @classmethod
    def get_info(cls, structure_id, type_piece, annee=None):
        """Retourne les informations de la séquence"""
        if not annee:
            annee = datetime.now().year
        
        sequence = cls.query.filter_by(
            structure_id=structure_id,
            type_piece=type_piece,
            annee=annee
        ).first()
        
        if not sequence:
            return None
        
        return {
            'id': sequence.id,
            'type_piece': sequence.type_piece,
            'prefixe': sequence.prefixe,
            'annee': sequence.annee,
            'numero_actuel': sequence.numero_actuel,
            'prochain_numero': sequence.format_affichage.format(
                prefixe=sequence.prefixe,
                annee=sequence.annee,
                numero=sequence.numero_actuel + 1
            ),
            'format_affichage': sequence.format_affichage
        }

# ============================================================
# MODÈLES MANQUANTS (à ajouter)
# ============================================================

class AnnulationVente(db.Model):
    __tablename__ = 'annulations_ventes'
    id = db.Column(db.Integer, primary_key=True)
    vente_id = db.Column(db.Integer, nullable=False)
    vente_type = db.Column(db.String(50))
    motif = db.Column(db.String(255))
    annule_par_id = db.Column(db.Integer)
    annule_par_nom = db.Column(db.String(255))
    ancien_net_a_payer = db.Column(db.Numeric)
    ancien_sous_total = db.Column(db.Numeric)
    data_avant = db.Column(db.JSON)
    date_annulation = db.Column(db.DateTime, default=datetime.utcnow)


class ValidationDemande(db.Model):
    """File d'attente générique pour les actions qu'un caissier/secrétaire
    peut désormais DEMANDER mais que seul un admin peut VALIDER avant
    qu'elles ne prennent effet réellement (annulation de vente,
    enregistrement d'une charge, encaissement d'une facture d'assurance).

    `payload` contient tout ce qu'il faut pour exécuter l'action une fois
    validée — les fonctions `_executer_*` dans app.py savent le relire.
    Rien n'est appliqué (ni écriture comptable, ni mise à jour de caisse)
    tant que `statut` n'est pas passé à 'validee' par un admin."""
    __tablename__ = 'validations_demandes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    type_demande = db.Column(db.String(50), nullable=False)  # annulation_vente | depense | encaissement_assurance
    reference_id = db.Column(db.Integer)  # vente_id / facture_assurance_id (selon le type) — informatif
    payload = db.Column(db.JSON, nullable=False)
    resume = db.Column(db.String(500))  # texte lisible pour la liste de validation admin
    demandeur_id = db.Column(db.Integer)
    demandeur_nom = db.Column(db.String(255))
    statut = db.Column(db.String(20), default='en_attente')  # en_attente | validee | refusee
    motif_refus = db.Column(db.String(500))
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    date_traitement = db.Column(db.DateTime)
    traite_par_nom = db.Column(db.String(255))


class Caisse(db.Model):
    __tablename__ = 'caisse'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)  # ⭐ AJOUTÉ
    solde_actuel = db.Column(db.Numeric, default=0)
    solde_initial = db.Column(db.Numeric, default=0)
    date_mise_a_jour = db.Column(db.DateTime, default=datetime.utcnow)


class Depense(db.Model):
    __tablename__ = 'depenses'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Numeric, nullable=False)
    motif = db.Column(db.String(255), nullable=False)
    motif_personnalise = db.Column(db.String(255))
    description = db.Column(db.Text)
    piece_jointe = db.Column(db.String(255))
    date_depense = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer)
    created_by_nom = db.Column(db.String(255))
    # ⭐ Tag optionnel vers un fournisseur (compte de tiers 401/4011) — pour
    # une dépense payée cash, sert juste au reporting ("qu'a-t-on acheté chez
    # X ?") ; pour un achat À CRÉDIT, l'obligation elle-même est suivie dans
    # AchatFournisseur (pas ici) pour ne jamais fausser le calcul de caisse
    # (SUM(depenses.montant), utilisé tel quel à de nombreux endroits) avec
    # un montant qui n'est pas encore réellement sorti de la caisse.
    fournisseur_id = db.Column(db.Integer, db.ForeignKey('fournisseurs.id'), nullable=True)


class Fournisseur(db.Model):
    """Tiers fournisseur (compte 401/4011 SYSCOHADA) — jusqu'ici le plan
    comptable définissait ces comptes mais rien ne les alimentait jamais
    (toute dépense était traitée comme payée cash immédiatement). Ce modèle
    + AchatFournisseur/ReglementFournisseur permettent enfin un vrai suivi
    "on doit X à ce fournisseur", avec règlement partiel ou total ultérieur."""
    __tablename__ = 'fournisseurs'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(255), nullable=False)
    telephone = db.Column(db.String(50))
    email = db.Column(db.String(255))
    adresse = db.Column(db.Text)
    actif = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer)
    created_by_nom = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def solde_du(self):
        """Somme des achats à crédit non intégralement réglés."""
        total = 0.0
        for achat in self.achats:
            total += float(achat.montant_total or 0) - float(achat.montant_paye or 0)
        return round(total, 2)


class AchatFournisseur(db.Model):
    """Un achat À CRÉDIT chez un fournisseur (charge reconnue immédiatement
    en comptabilité — Débit charge / Crédit 401 — mais qui ne touche PAS la
    caisse tant qu'il n'est pas réglé). Un achat payé cash n'a pas besoin de
    passer par ici : c'est une Depense classique (optionnellement taguée
    `fournisseur_id` pour le reporting)."""
    __tablename__ = 'achats_fournisseurs'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    fournisseur_id = db.Column(db.Integer, db.ForeignKey('fournisseurs.id'), nullable=False)
    montant_total = db.Column(db.Numeric, nullable=False)
    montant_paye = db.Column(db.Numeric, default=0)
    motif = db.Column(db.String(255), nullable=False)
    motif_personnalise = db.Column(db.String(255))
    description = db.Column(db.Text)
    date_achat = db.Column(db.DateTime, default=datetime.utcnow)
    date_echeance = db.Column(db.Date)
    statut = db.Column(db.String(20), default='a_regler')  # a_regler, reglee
    ecriture_id = db.Column(db.Integer)
    created_by = db.Column(db.Integer)
    created_by_nom = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    fournisseur = db.relationship('Fournisseur', backref='achats')

    def reste_a_payer(self):
        return round(float(self.montant_total or 0) - float(self.montant_paye or 0), 2)


class ReglementFournisseur(db.Model):
    """Un règlement (partiel ou total) d'un AchatFournisseur — mirrors
    PaiementFacture côté client. Débit 401 / Crédit trésorerie."""
    __tablename__ = 'reglements_fournisseurs'
    id = db.Column(db.Integer, primary_key=True)
    achat_id = db.Column(db.Integer, db.ForeignKey('achats_fournisseurs.id'), nullable=False)
    fournisseur_id = db.Column(db.Integer, db.ForeignKey('fournisseurs.id'), nullable=False)
    montant = db.Column(db.Numeric, nullable=False)
    date_reglement = db.Column(db.DateTime, default=datetime.utcnow)
    mode_paiement = db.Column(db.String(50), default='especes')
    reference = db.Column(db.String(255))
    notes = db.Column(db.Text)
    ecriture_id = db.Column(db.Integer)
    created_by = db.Column(db.Integer)
    created_by_nom = db.Column(db.String(255))

    achat = db.relationship('AchatFournisseur', backref='reglements')


class Facture(db.Model):
    __tablename__ = 'factures'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255), nullable=False)
    patient_telephone = db.Column(db.String(50))
    numero_facture = db.Column(db.String(50), nullable=False)
    date_emission = db.Column(db.Date, default=db.func.current_date())
    date_echeance = db.Column(db.Date, nullable=False)
    sous_total = db.Column(db.Numeric, default=0, nullable=False)
    taux_assurance = db.Column(db.Numeric, default=0)
    prise_en_charge = db.Column(db.Numeric, default=0)
    taux_assurance2 = db.Column(db.Numeric, default=0)
    prise_en_charge2 = db.Column(db.Numeric, default=0)
    net_a_payer = db.Column(db.Numeric, default=0, nullable=False)
    montant_paye = db.Column(db.Numeric, default=0)
    reste_a_payer = db.Column(db.Numeric, default=0)
    statut = db.Column(db.String(50), default='en_attente')
    articles = db.Column(db.JSON)
    mode_paiement = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(255))
    base_remboursement = db.Column(db.Numeric, default=0)
    assurances_data = db.Column(db.JSON)
    vente_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FactureAssurance(db.Model):
    __tablename__ = 'factures_assurance'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    mois_reference = db.Column(db.String(20), nullable=False)
    assurance = db.Column(db.String(255), nullable=False)
    montant_total = db.Column(db.Numeric, nullable=False)
    montant_rembourse = db.Column(db.Numeric, default=0)
    statut = db.Column(db.String(50), default='en_attente')
    date_facture = db.Column(db.Date, default=db.func.current_date())
    date_remboursement = db.Column(db.Date)
    # ⭐ Pièces justificatives du dernier versement encaissé (traçabilité) :
    # numéro de référence du virement/versement + sa date, saisis obligatoirement
    # à l'encaissement (voir /api/assurances/factures/<id>/payer) et affichés
    # en comptabilité (liste des factures assurance + détail de l'écriture).
    numero_reference_versement = db.Column(db.String(100))
    date_versement = db.Column(db.Date)
    details = db.Column(db.JSON)
    type_assurance = db.Column(db.String(50), default='principale')
    # Société souscriptrice (assurance complémentaire uniquement) : permet de
    # générer une facture distincte par société sous une même compagnie
    # (ex: GTA/SOTOCO et GTA/TOGOCEL séparément).
    societe = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaiementFacture(db.Model):
    __tablename__ = 'paiements_factures'
    id = db.Column(db.Integer, primary_key=True)
    facture_id = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Numeric, nullable=False)
    date_paiement = db.Column(db.DateTime, default=datetime.utcnow)
    mode_paiement = db.Column(db.String(50))
    reference = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(255))
    recu_genere = db.Column(db.Boolean, default=False)


class Proforma(db.Model):
    __tablename__ = 'proformas'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer)
    patient_nom = db.Column(db.String(255), nullable=False)
    patient_telephone = db.Column(db.String(50))
    assurance_nom = db.Column(db.String(255))
    taux_assurance = db.Column(db.Numeric, default=0)
    numero_assure = db.Column(db.String(255))
    type = db.Column(db.String(50), nullable=False, default='mixte')
    articles = db.Column(db.JSON, nullable=False, default=[])
    sous_total = db.Column(db.Numeric, default=0, nullable=False)
    prise_en_charge = db.Column(db.Numeric, default=0, nullable=False)
    net_a_payer = db.Column(db.Numeric, default=0, nullable=False)
    statut = db.Column(db.String(50), default='en_attente')
    vente_id = db.Column(db.Integer)
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    vue_par_patient = db.Column(db.Boolean, default=False)
    date_vue = db.Column(db.DateTime)
    numero_proforma = db.Column(db.Integer)
    assurance2_nom = db.Column(db.String(255), default='')
    taux_assurance2 = db.Column(db.Numeric, default=0)
    numero_assure2 = db.Column(db.String(255), default='')
    assurance2_active = db.Column(db.Boolean, default=False)
    taux_modifie = db.Column(db.Boolean, default=False)
    taux_original = db.Column(db.Numeric, default=0)
    prise_en_charge2 = db.Column(db.Numeric, default=0)
    assurances_data = db.Column(db.JSON)
    base_remboursement = db.Column(db.Numeric, default=0)
    base_cac = db.Column(db.Numeric, default=0)


class ProformaLunette(db.Model):
    __tablename__ = 'proformas_lunettes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255))
    patient_telephone = db.Column(db.String(50))
    patient_date_naissance = db.Column(db.Date)
    patient_age = db.Column(db.Integer)
    numero = db.Column(db.String(255))
    articles = db.Column(db.JSON)
    sous_total = db.Column(db.Numeric, default=0)
    remise = db.Column(db.Numeric, default=0)
    type_remise = db.Column(db.String(50), default='pourcentage')
    valeur_remise = db.Column(db.Numeric, default=0)
    net_a_payer = db.Column(db.Numeric, default=0)
    tva_taux = db.Column(db.Numeric, default=18)
    medecin_prescripteur = db.Column(db.String(255))
    notes = db.Column(db.Text)
    statut = db.Column(db.String(50), default='en_attente')
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    rib = db.Column(db.String(50))
    numero_affiliation = db.Column(db.String(255))


class Recette(db.Model):
    __tablename__ = 'recettes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Numeric, nullable=False)
    source = db.Column(db.String(255))
    description = db.Column(db.Text)
    date_recette = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer)
    created_by_nom = db.Column(db.String(255))
    source_id = db.Column(db.Integer)
    source_type = db.Column(db.String(255))
    est_annulation = db.Column(db.Boolean, default=False)


class VenteLunette(db.Model):
    __tablename__ = 'ventes_lunettes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255))
    lunette_id = db.Column(db.Integer)
    lunette_nom = db.Column(db.String(255))
    marque = db.Column(db.String(255))
    modele = db.Column(db.String(255))
    prix = db.Column(db.Float, default=0)
    remise = db.Column(db.Float, default=0)
    prix_avec_remise = db.Column(db.Float, default=0)
    quantite = db.Column(db.Integer, default=1)
    total = db.Column(db.Float, default=0)
    taux_assurance = db.Column(db.Float, default=0)
    prise_en_charge = db.Column(db.Float, default=0)
    prise_en_charge2 = db.Column(db.Float, default=0)
    net_a_payer = db.Column(db.Float, default=0)
    mode_paiement = db.Column(db.String(50), default='especes')
    montant_donne = db.Column(db.Float, default=0)
    rendu = db.Column(db.Float, default=0)
    reste_a_payer = db.Column(db.Float, default=0)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================================
# MODÈLE RAPPEL RENDEZ-VOUS (À AJOUTER À LA FIN DE models.py)
# ============================================================

class RappelRendezVous(db.Model):
    """Modèle pour l'historique des rappels"""
    
    __tablename__ = 'rappels_rendez_vous'
    
    id = db.Column(db.Integer, primary_key=True)
    rendez_vous_id = db.Column(db.Integer, db.ForeignKey('rendez_vous.id'), nullable=False)
    
    type_rappel = db.Column(db.String(20), nullable=False)
    statut = db.Column(db.String(20), default='en_attente')
    
    date_planifiee = db.Column(db.DateTime, default=datetime.utcnow)
    date_envoyee = db.Column(db.DateTime)
    
    message_envoye = db.Column(db.Text)
    url_whatsapp = db.Column(db.String(500))
    
    erreur = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    rendez_vous = db.relationship('RendezVous', backref='rappels')

# ============================================================
# MODÈLES POUR LA GESTION DES PROTOCOLES ET MODÈLES
# ============================================================

class ProtocoleMedical(db.Model):
    """Modèle pour les protocoles de soins et modèles médicaux"""
    
    __tablename__ = 'protocoles_medicaux'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Catégorie du document
    categorie = db.Column(db.String(50), nullable=False)
    # protocole_soins, ordonnance_type, bulletin_examen, 
    # protocole_patient, fiche_information, protocole_infirmier
    
    # Identité
    titre = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    contenu = db.Column(db.Text, nullable=False)  # Contenu principal
    
    # Métadonnées
    specialite = db.Column(db.String(100))  # Cardiologie, Pédiatrie, etc.
    tags = db.Column(db.JSON, default=[])  # Mots-clés pour recherche
    version = db.Column(db.Integer, default=1)
    statut = db.Column(db.String(20), default='brouillon')
    # brouillon, en_validation, publie, archive
    
    # Auteur
    auteur_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    auteur_nom = db.Column(db.String(100))
    
    # Pour les ordonnances types
    medicaments = db.Column(db.JSON, default=[])  # Liste des médicaments
    examens = db.Column(db.JSON, default=[])  # Liste des examens
    
    # Pour les protocoles patient
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=True)
    date_debut = db.Column(db.Date)
    date_fin = db.Column(db.Date)
    
    # Pour les protocoles de soins
    etapes = db.Column(db.JSON, default=[])  # Étapes du protocole
    duree = db.Column(db.String(50))  # Durée estimée
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ⭐ Origine miroir (synchronisation depuis gestion_patients — voir
    # /api/protocoles/sync-externe) : NULL pour tout document 100% natif GHP,
    # renseigné uniquement pour les catégories synchronisables (protocole_soins,
    # ordonnance_type, bulletin_examen). Un index unique partiel sur
    # (structure_id, source_app, source_model, source_id) garantit qu'un
    # upsert répété ne crée jamais de doublon.
    source_app = db.Column(db.String(30))       # 'gestion_patients'
    source_model = db.Column(db.String(30))     # 'ProtocoleSoins' | 'OrdonnanceType' | 'ExamenType'
    source_id = db.Column(db.Integer)           # id de la ligne source dans gestion_patients
    source_synced_at = db.Column(db.DateTime)

    # Relations
    structure = db.relationship('Structure', backref='protocoles')
    auteur = db.relationship('Utilisateur', backref='protocoles')
    patient = db.relationship('Patient', backref='protocoles')
    
    def to_dict(self):
        return {
            'id': self.id,
            'structure_id': self.structure_id,
            'categorie': self.categorie,
            'categorie_label': self.get_categorie_label(),
            'titre': self.titre,
            'description': self.description,
            'contenu': self.contenu,
            'specialite': self.specialite,
            'tags': self.tags or [],
            'version': self.version,
            'statut': self.statut,
            'statut_label': self.get_statut_label(),
            'auteur_id': self.auteur_id,
            'auteur_nom': self.auteur_nom,
            'medicaments': self.medicaments or [],
            'examens': self.examens or [],
            'patient_id': self.patient_id,
            'date_debut': self.date_debut.isoformat() if self.date_debut else None,
            'date_fin': self.date_fin.isoformat() if self.date_fin else None,
            'etapes': self.etapes or [],
            'duree': self.duree,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'source_app': self.source_app,
            'source_model': self.source_model,
            'source_id': self.source_id,
            'est_synchronise': bool(self.source_app),
        }
    
    def get_categorie_label(self):
        labels = {
            'protocole_soins': 'Protocole de soins',
            'ordonnance_type': 'Ordonnance type',
            'bulletin_examen': 'Bulletin d\'examen',
            'protocole_patient': 'Protocole patient',
            'fiche_information': 'Fiche d\'information',
            'protocole_infirmier': 'Protocole infirmier'
        }
        return labels.get(self.categorie, self.categorie)
    
    def get_statut_label(self):
        labels = {
            'brouillon': 'Brouillon',
            'en_validation': 'En validation',
            'publie': 'Publié',
            'archive': 'Archivé'
        }
        return labels.get(self.statut, self.statut)
    
    def generer_ordonnance(self, patient_nom, date_rdv):
        """Génère une ordonnance à partir d'un modèle"""
        if self.categorie != 'ordonnance_type':
            return None
        
        content = self.contenu
        content = content.replace('{{patient_nom}}', patient_nom)
        content = content.replace('{{date}}', date_rdv)
        
        return content

    def generer_protocole(self, patient_nom):
        """Génère un protocole personnalisé pour un patient"""
        if self.categorie not in ['protocole_soins', 'protocole_patient']:
            return None
        
        content = self.contenu
        content = content.replace('{{patient_nom}}', patient_nom)
        
        return content


class HistoriqueProtocole(db.Model):
    """Historique des modifications des protocoles"""
    
    __tablename__ = 'historique_protocoles'
    
    id = db.Column(db.Integer, primary_key=True)
    protocole_id = db.Column(db.Integer, db.ForeignKey('protocoles_medicaux.id'), nullable=False)
    
    action = db.Column(db.String(50), nullable=False)  # creation, modification, validation, publication
    utilisateur_id = db.Column(db.Integer)
    utilisateur_nom = db.Column(db.String(100))
    ancien_contenu = db.Column(db.Text)
    nouveau_contenu = db.Column(db.Text)
    commentaire = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    protocole = db.relationship('ProtocoleMedical', backref='historique')


class ProtocolePatient(db.Model):
    """Lien entre un patient et un protocole de soins"""
    
    __tablename__ = 'protocoles_patients'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    protocole_id = db.Column(db.Integer, db.ForeignKey('protocoles_medicaux.id'), nullable=False)
    
    statut = db.Column(db.String(20), default='en_cours')
    # en_cours, termine, abandonne
    
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date)
    notes = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    patient = db.relationship('Patient', backref='protocoles_appliques')
    protocole = db.relationship('ProtocoleMedical', backref='patients_associes')
    structure = db.relationship('Structure', backref='protocoles_patients')

# ============================================================
# MODÈLE JOURNAL DES MOUVEMENTS
# ============================================================

class JournalMouvement(db.Model):
    """Journal centralisé des mouvements de l'établissement"""
    
    __tablename__ = 'journal_mouvements'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Catégorie et type
    categorie = db.Column(db.String(50), nullable=False)
    # vente_actes, vente_pharmacie, vente_lunettes, annulation_vente,
    # paiement_facture, paiement_assurance, facture_emise, avoir_emis,
    # recette_encaisee, depense_enregistree, proforma_cree, rendez_vous_pris
    
    sous_categorie = db.Column(db.String(50))
    
    # Référence
    reference_type = db.Column(db.String(50))  # vente, facture, paiement, etc.
    reference_id = db.Column(db.Integer)
    
    # Date du mouvement
    date_mouvement = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Description
    description = db.Column(db.Text)
    
    # Montant
    montant = db.Column(db.Numeric, default=0)
    type_montant = db.Column(db.String(10), default='neutre')  # credit, debit, neutre
    
    # Patient
    patient_id = db.Column(db.Integer)
    patient_nom = db.Column(db.String(200))
    
    # Utilisateur
    utilisateur_id = db.Column(db.Integer)
    utilisateur_nom = db.Column(db.String(100))
    
    # Détails supplémentaires (JSON)
    details = db.Column(db.JSON, default={})
    
    # Statut
    statut = db.Column(db.String(20), default='valide')  # valide, annule, en_attente
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    structure = db.relationship('Structure', backref='journal_mouvements')
    
    def to_dict(self):
        return {
            'id': self.id,
            'structure_id': self.structure_id,
            'categorie': self.categorie,
            'categorie_label': self.get_categorie_label(),
            'sous_categorie': self.sous_categorie,
            'reference_type': self.reference_type,
            'reference_id': self.reference_id,
            'date_mouvement': self.date_mouvement.isoformat() if self.date_mouvement else None,
            'date_affichage': self.date_mouvement.strftime('%d/%m/%Y %H:%M') if self.date_mouvement else '',
            'description': self.description,
            'montant': float(self.montant) if self.montant else 0,
            'type_montant': self.type_montant,
            'montant_affichage': self.get_montant_affichage(),
            'patient_id': self.patient_id,
            'patient_nom': self.patient_nom,
            'utilisateur_id': self.utilisateur_id,
            'utilisateur_nom': self.utilisateur_nom,
            'details': self.details or {},
            'statut': self.statut,
            'statut_label': self.get_statut_label(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def get_categorie_label(self):
        labels = {
            'vente_actes': 'Vente d\'actes',
            'vente_pharmacie': 'Vente pharmacie',
            'vente_lunettes': 'Vente lunettes',
            'annulation_vente': 'Annulation vente',
            'paiement_facture': 'Paiement facture',
            'paiement_assurance': 'Paiement assurance',
            'facture_emise': 'Facture émise',
            'avoir_emis': 'Avoir émis',
            'recette_encaisee': 'Recette encaissée',
            'depense_enregistree': 'Dépense enregistrée',
            'proforma_cree': 'Proforma créé',
            'rendez_vous_pris': 'Rendez-vous pris',
            'consultation_terminee': 'Consultation terminée',
            'ecriture_generee': 'Écriture comptable générée',
            'salaire_paye': 'Salaire payé',
            'employe_ajoute': 'Employé ajouté',
            'conge_approuve': 'Congé approuvé',
            'permission_approuvee': 'Permission approuvée',
            'cloture_exercice': "Clôture d'exercice",
        }
        return labels.get(self.categorie, self.categorie)
    
    def get_statut_label(self):
        labels = {
            'valide': 'Valide',
            'annule': 'Annulé',
            'en_attente': 'En attente'
        }
        return labels.get(self.statut, self.statut)
    
    def get_montant_affichage(self):
        if self.type_montant == 'credit':
            return f"+ {abs(float(self.montant)):,.0f} F"
        elif self.type_montant == 'debit':
            return f"- {abs(float(self.montant)):,.0f} F"
        else:
            return f"{float(self.montant):,.0f} F"


# ============================================================
# PAIE (bulletin de paie — Togo, agents publics et privés)
# ============================================================
# ⚠️ Les taux par défaut ci-dessous (ParametragePaie) sont des valeurs
# indicatives, éditables dans l'écran "Paramètres de paie". À faire
# valider par votre comptable / la DGI avant la première paie réelle —
# la législation sociale et fiscale togolaise évolue.
#
# Deux profils sont gérés (secteur_paie sur Employe) :
#   - Privé : retraite CNSS, assurance maladie AMU-CNSS
#   - Public : retraite CRT, assurance maladie AMU-INAM
# L'AMU est réglementée par le décret n°2023-096/PR du 4 octobre 2023 :
# taux global de 10% de la rémunération, réparti au plus à moitié pour le
# salarié et au moins à moitié pour l'employeur — ce verrou (amu_taux_global/2)
# s'applique quel que soit le profil, et même en cas de dérogation
# individuelle par salarié (voir services/paie_service.py).

class ParametragePaie(db.Model):
    __tablename__ = 'parametrage_paie'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)

    # --- Secteur privé : retraite CNSS ---
    taux_cnss_salarial = db.Column(db.Numeric, default=4.0)      # % de l'assiette (salaire brut)
    taux_cnss_patronal = db.Column(db.Numeric, default=17.5)
    plafond_cnss = db.Column(db.Numeric, default=0)              # FCFA/mois, 0 = pas de plafond

    # --- Secteur public : retraite CRT (assiette = salaire de base / traitement indiciaire) ---
    taux_crt_salarial = db.Column(db.Numeric, default=7.0)
    taux_crt_patronal = db.Column(db.Numeric, default=20.0)
    plafond_crt = db.Column(db.Numeric, default=0)

    # --- AMU (commun aux deux secteurs, assiette = salaire brut) ---
    amu_taux_global = db.Column(db.Numeric, default=10.0)         # décret n°2023-096/PR
    taux_amu_salarial_defaut = db.Column(db.Numeric, default=5.0)   # verrouillé <= amu_taux_global/2
    taux_amu_patronal_defaut = db.Column(db.Numeric, default=5.0)   # verrouillé >= amu_taux_global/2

    # --- Formation professionnelle (privé — taux à confirmer, désactivé par défaut) ---
    taux_formation_pro = db.Column(db.Numeric, default=0)

    # Barème IRPP progressif ANNUEL : liste de {min, max, taux} en JSON,
    # éditable. Le calcul mensuel annualise la base imposable (x12), applique
    # le barème, puis divise l'impôt obtenu par 12.
    tranches_irpp = db.Column(db.JSON, default=lambda: [
        {'min': 0, 'max': 900000, 'taux': 0},
        {'min': 900000, 'max': 3000000, 'taux': 3},
        {'min': 3000000, 'max': 4000000, 'taux': 10},
        {'min': 4000000, 'max': 6000000, 'taux': 15},
        {'min': 6000000, 'max': 10000000, 'taux': 25},
        {'min': 10000000, 'max': None, 'taux': 35},
    ])
    abattement_taux = db.Column(db.Numeric, default=28.0)                 # % sur le brut imposable
    abattement_plafond_annuel = db.Column(db.Numeric, default=10000000)   # FCFA/an
    deduction_personne_charge = db.Column(db.Numeric, default=10000)      # FCFA/mois/personne
    max_personnes_charge = db.Column(db.Integer, default=6)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(100))

    @classmethod
    def get_ou_creer(cls, structure_id):
        """Retourne le paramétrage de la structure, en le créant avec les
        valeurs par défaut (à vérifier) s'il n'existe pas encore."""
        param = cls.query.filter_by(structure_id=structure_id).first()
        if not param:
            param = cls(structure_id=structure_id)
            db.session.add(param)
            db.session.commit()
        return param


class Paie(db.Model):
    __tablename__ = 'paies'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)

    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)  # 1-12

    # Instantané du profil appliqué (utile même si les paramètres/l'employé
    # changent ensuite — le bulletin déjà généré reste cohérent avec lui-même)
    secteur = db.Column(db.String(10))              # 'prive' | 'public'
    organisme_retraite = db.Column(db.String(10))   # 'CNSS' | 'CRT'
    organisme_amu = db.Column(db.String(20))         # 'AMU-CNSS' | 'AMU-INAM'

    salaire_base = db.Column(db.Numeric, default=0)
    primes = db.Column(db.Numeric, default=0)
    indemnites = db.Column(db.Numeric, default=0)
    salaire_brut = db.Column(db.Numeric, default=0)

    taux_retraite_salarial = db.Column(db.Numeric, default=0)
    taux_retraite_patronal = db.Column(db.Numeric, default=0)
    retraite_salarial = db.Column(db.Numeric, default=0)
    retraite_patronal = db.Column(db.Numeric, default=0)

    taux_amu_salarial = db.Column(db.Numeric, default=0)
    taux_amu_patronal = db.Column(db.Numeric, default=0)
    amu_salarial = db.Column(db.Numeric, default=0)
    amu_patronal = db.Column(db.Numeric, default=0)

    formation_pro = db.Column(db.Numeric, default=0)   # charge patronale uniquement

    salaire_brut_imposable = db.Column(db.Numeric, default=0)   # brut - cotisations sociales salariales
    personnes_a_charge = db.Column(db.Integer, default=0)
    abattement = db.Column(db.Numeric, default=0)
    deduction_charges_familiales = db.Column(db.Numeric, default=0)
    revenu_net_imposable = db.Column(db.Numeric, default=0)     # base mensuelle après abattement + charges
    irpp = db.Column(db.Numeric, default=0)

    prets_deduction = db.Column(db.Numeric, default=0)
    acomptes_deduction = db.Column(db.Numeric, default=0)
    autres_retenues = db.Column(db.JSON, default=list)           # [{libelle, montant}]
    autres_retenues_total = db.Column(db.Numeric, default=0)

    total_retenues = db.Column(db.Numeric, default=0)              # retraite+AMU sal. + IRPP + prêts/acomptes/autres
    total_charges_patronales = db.Column(db.Numeric, default=0)    # retraite+AMU patronal + formation pro
    net_a_payer = db.Column(db.Numeric, default=0)

    statut = db.Column(db.String(20), default='brouillon')  # brouillon, valide, payee
    mode_paiement = db.Column(db.String(50), default='especes')
    date_paiement = db.Column(db.Date)

    depense_id = db.Column(db.Integer)
    # ⭐ Non-mélange SYSCOHADA : `ecriture_id` porte la reconnaissance de la
    # paie (journal SAL — charges + dettes, dont la dette "net à payer"
    # envers le personnel) ; `ecriture_paiement_id` porte le SEUL décaissement
    # réel du net (journal CAI/BQ) — voir generer_ecriture_paie().
    ecriture_id = db.Column(db.Integer)
    ecriture_paiement_id = db.Column(db.Integer)

    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employe = db.relationship('Employe', backref='paies', lazy=True)

    def get_statut_label(self):
        return {'brouillon': 'Brouillon', 'valide': 'Validée', 'payee': 'Payée'}.get(self.statut, self.statut)

    def get_periode_label(self):
        mois_noms = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                     'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
        return f"{mois_noms[self.mois]} {self.annee}"


# ============================================================================
# BASCULE HORS-LIGNE — synchronisation base locale <-> Neon (voir utils/db_failover.py)
# __bind_key__ = 'local' : ces 2 tables ne vivent QUE sur Postgres local,
# jamais sur Neon (Neon n'a pas ce bind). Elles ne sont donc jamais écrasées
# par un rapatriement (pg_restore) des données de Neon vers le local.
# ============================================================================

class SyncState(db.Model):
    """État courant de la bascule (une seule ligne, id=1)."""
    __tablename__ = 'sync_state'
    __bind_key__ = 'local'

    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(10), default='online')  # 'online' (Neon) | 'offline' (local)
    derniere_bascule_offline = db.Column(db.DateTime)
    dernier_sync_reussi = db.Column(db.DateTime)
    derniere_erreur_sync = db.Column(db.Text)
    derniere_erreur_sync_at = db.Column(db.DateTime)
    dernier_sync_sheets = db.Column(db.DateTime)  # dernier rafraîchissement du miroir Google Sheets

    @classmethod
    def get_ou_creer(cls):
        etat = cls.query.get(1)
        if not etat:
            etat = cls(id=1, mode='online')
            db.session.add(etat)
            db.session.commit()
        return etat


class SyncChangelog(db.Model):
    """Journal des écritures faites en local pendant une coupure Neon,
    à rejouer vers Neon dès que la connexion revient."""
    __tablename__ = 'sync_changelog'
    __bind_key__ = 'local'

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(100), nullable=False)
    operation = db.Column(db.String(10), nullable=False)  # insert | update | delete
    pk_value = db.Column(db.Integer, nullable=False)
    payload = db.Column(db.JSON)  # snapshot complet de la ligne (insert/update) ; null pour delete
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    synced = db.Column(db.Boolean, default=False)
    synced_at = db.Column(db.DateTime)


class SheetsMirror(db.Model):
    """Miroir local, en LECTURE SEULE, de certaines feuilles Google Sheets
    (actes, produits/médicaments, users, lunettes — par structure — et la
    feuille globale 'structures'). Permet à l'appli (y compris la connexion)
    de continuer à fonctionner quand Google Sheets est injoignable.
    Alimenté par utils/sheets_mirror.py — ne jamais modifier à la main,
    ce n'est pas la source de vérité (contrairement à sync_changelog qui,
    lui, part du local vers Neon)."""
    __tablename__ = 'sheets_mirror'
    __bind_key__ = 'local'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    sheet_type = db.Column(db.String(30), nullable=False)  # actes | produits | users | lunettes | structures
    row_key = db.Column(db.String(50), nullable=False)     # colonne "ID" de la feuille
    data = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('structure_id', 'sheet_type', 'row_key', name='uq_sheets_mirror_row'),
    )


# ============================================================================
# POINTAGE — badgeage par empreinte digitale (WebAuthn / Windows Hello)
# ============================================================================

class EmpreinteEmploye(db.Model):
    """Une empreinte (credential WebAuthn) enregistrée pour un employé.
    Un employé peut en avoir plusieurs (ex: enregistrée sur deux postes)."""
    __tablename__ = 'empreintes_employes'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)

    credential_id = db.Column(db.Text, nullable=False, unique=True)  # base64, identifiant WebAuthn
    public_key = db.Column(db.Text, nullable=False)                  # base64, clé publique COSE
    sign_count = db.Column(db.Integer, default=0)                    # anti-clonage (doit toujours augmenter)

    libelle_appareil = db.Column(db.String(100))   # ex: "PC accueil"
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_utilisation = db.Column(db.DateTime)

    employe = db.relationship('Employe', backref='empreintes')


class ParametragePointage(db.Model):
    """Règles de pointage par structure (horaires, tolérance, jours travaillés)."""
    __tablename__ = 'parametrage_pointage'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)

    heure_debut = db.Column(db.Time, default=lambda: time(8, 0))
    heure_fin = db.Column(db.Time, default=lambda: time(17, 0))
    tolerance_retard_minutes = db.Column(db.Integer, default=10)
    # Jours travaillés : 0=lundi ... 6=dimanche (convention Python date.weekday())
    jours_travailles = db.Column(db.JSON, default=lambda: [0, 1, 2, 3, 4, 5])

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_ou_creer(cls, structure_id):
        param = cls.query.filter_by(structure_id=structure_id).first()
        if not param:
            param = cls(structure_id=structure_id)
            db.session.add(param)
            db.session.commit()
        return param


class Pointage(db.Model):
    """Un pointage = une ligne par employé et par jour (arrivée + départ)."""
    __tablename__ = 'pointages'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)
    date_jour = db.Column(db.Date, nullable=False)

    heure_arrivee = db.Column(db.Time)
    methode_arrivee = db.Column(db.String(20))    # 'empreinte' | 'visage' | 'manuel'
    statut_arrivee = db.Column(db.String(20))     # 'a_l_heure' | 'retard'
    retard_minutes = db.Column(db.Integer, default=0)

    heure_depart = db.Column(db.Time)
    methode_depart = db.Column(db.String(20))
    depart_anticipe = db.Column(db.Boolean, default=False)

    duree_travaillee_minutes = db.Column(db.Integer)
    commentaire = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employe = db.relationship('Employe', backref='pointages')

    __table_args__ = (
        db.UniqueConstraint('employe_id', 'date_jour', name='uq_pointage_employe_jour'),
    )

    def get_statut_label(self):
        if not self.heure_arrivee:
            return 'Absent'
        if self.statut_arrivee == 'retard':
            return f"Retard ({self.retard_minutes} min)"
        return 'À l\'heure'


class VisageEmploye(db.Model):
    """Un visage (descripteur facial à 128 dimensions, calculé par
    face-api.js dans le navigateur — la photo elle-même ne quitte jamais
    l'appareil, seul le descripteur mathématique est envoyé) enregistré
    pour un employé. Reconnaissance par webcam standard, complémentaire au
    pointage par empreinte (WebAuthn) — pas de matériel Windows Hello requis."""
    __tablename__ = 'visages_employes'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)

    descripteur = db.Column(db.JSON, nullable=False)  # liste de 128 nombres flottants

    libelle = db.Column(db.String(100))
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_utilisation = db.Column(db.DateTime)

    employe = db.relationship('Employe', backref='visages')
