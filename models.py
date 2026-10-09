# models.py - GHP
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, time, timedelta
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
    # ⭐ nom/prenom/telephone chiffrés en base (voir crypto_helper.py) —
    # Text plutôt que String(100)/String(50) : un texte chiffré est
    # nettement plus long que le texte en clair d'origine.
    nom = db.Column(db.Text, nullable=False)
    prenom = db.Column(db.Text, nullable=False)
    date_naissance = db.Column(db.Date)
    telephone = db.Column(db.Text)
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
    # ⭐ Pour l'envoi des résultats par email — patron : "dans les résultats
    # qu'on puisse envoyer résultat par mail au patient". Facultatif,
    # capturé à la volée depuis le bouton d'envoi si absent (voir
    # PUT /api/patients/<id>/email, app.py).
    email = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# PRÉINSCRIPTIONS PATIENT — saisie par le patient lui-même (tablette à
# l'accueil ou QR code scanné avec son téléphone), à valider par la
# réception avant de devenir une vraie fiche patient. Jamais insérée
# directement dans `patients` : le nom peut être mal orthographié, le
# patient peut déjà exister, le numéro d'assuré doit être vérifiable —
# un coup d'œil de la réception avant validation évite ça.
# ============================================================
class PreinscriptionPatient(db.Model):
    __tablename__ = 'preinscriptions_patients'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)

    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100))
    telephone = db.Column(db.String(50))
    date_naissance = db.Column(db.Date)
    adresse = db.Column(db.Text)

    type_assurance = db.Column(db.String(50), default='non_assure')
    numero_assure = db.Column(db.String(50))

    # Assurance complémentaire (CAC) — pas de taux ici : un patient ne
    # connaît pas son taux négocié, c'est la réception qui le complète à
    # la validation (comme le taux de l'assurance principale, déjà absent
    # de ce formulaire pour la même raison).
    assurance2_nom = db.Column(db.String(100))
    numero_assure2 = db.Column(db.String(50))
    societe_assurance2 = db.Column(db.String(150))

    personne_a_prevenir_nom = db.Column(db.String(100))
    personne_a_prevenir_telephone = db.Column(db.String(50))
    personne_a_prevenir_relation = db.Column(db.String(50))

    email = db.Column(db.String(255))

    # Motif de la visite — 'consultation' | 'controle' | 'resultat_analyse' |
    # 'realisation_examen' | texte libre (si "Autre" choisi côté formulaire)
    motif_visite = db.Column(db.String(100))

    # Numéro de passage dans la file d'attente du jour — imprimé sur le
    # ticket remis au patient juste après l'enregistrement (voir
    # api_accueil_patient, app.py). Remis à zéro chaque jour (compté parmi
    # les préinscriptions du jour pour la structure).
    numero_ordre = db.Column(db.Integer)

    # 'en_attente' | 'validee' | 'rejetee'
    statut = db.Column(db.String(20), nullable=False, default='en_attente')
    # Rempli au moment de la validation, vers la fiche patient créée
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'))

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
    mise_de_cote = db.Column(db.Boolean, default=False)
    mise_de_cote_le = db.Column(db.DateTime)

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


# ⭐ Patron : "pas de vrai départ (offboarding) — suppression brute ou
# juste un statut" — motifs valides pour un départ structuré (voir
# Employe.date_depart/motif_depart/commentaire_depart et
# routes/rh.py api_enregistrer_depart). Un motif hors de cette liste est
# refusé côté API plutôt que silencieusement accepté.
MOTIFS_DEPART = {
    'demission': 'Démission',
    'licenciement': 'Licenciement',
    'fin_contrat': 'Fin de contrat',
    'retraite': 'Retraite',
    'rupture_conventionnelle': 'Rupture conventionnelle',
    'deces': 'Décès',
    'autre': 'Autre',
}


class Employe(db.Model):
    __tablename__ = 'employes'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    matricule = db.Column(db.String(20), unique=True, nullable=False)
    # ⭐ Numérotation propre à CETTE structure (1, 2, 3...) — distincte du
    # matricule (unique dans toute la table, ne suit donc pas forcément
    # 1/2/3 par structure) et de l'id technique (séquence globale).
    numero_local = db.Column(db.Integer)

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
    # ⭐ Patron : "pas d'organigramme réel" — responsable hiérarchique
    # DIRECT de cet employé (auto-référence, nullable : tout le monde n'a
    # pas de manager, ex. le/la directeur·rice). Distinct de
    # Service.responsable (texte libre, non lié à un employé précis) —
    # voir _valider_manager (routes/rh.py) pour la protection anti-cycle
    # (X ne peut pas devenir manager de son propre manager, direct ou
    # indirect) et Employe.chaine_hierarchique ci-dessous.
    manager_id = db.Column(db.Integer, db.ForeignKey('employes.id'))
    date_embauche = db.Column(db.Date, nullable=False)
    type_contrat = db.Column(db.String(50))
    # ⭐ Patron : "pas de date de fin de contrat ni d'alerte de
    # renouvellement" — nullable : un CDI (ou tout contrat à durée
    # indéterminée) n'en a simplement pas. Voir
    # Employe.jours_avant_fin_contrat / contrats_a_renouveler ci-dessous
    # pour l'alerte (jamais de désactivation automatique de l'employé à
    # l'échéance — décision volontairement laissée à l'admin).
    date_fin_contrat = db.Column(db.Date)
    salaire_base = db.Column(db.Numeric, default=0)

    # ⭐ Patron : "fiche employé et compte de connexion séparés (aucun
    # lien)" — le VRAI système de connexion de l'appli n'est PAS la table
    # SQL Utilisateur (jamais interrogée pour le login) mais une feuille
    # Google Sheets par structure (struct_<id>_users, lignes ID/nom/email/
    # mot_de_passe/role/actif — voir app.py, route index()). Ce champ ne
    # peut donc pas être une vraie clé étrangère : c'est un lien logique
    # vers l'ID de ligne de cette feuille. Nullable : rien n'oblige à
    # lier un employé à un compte (agent de terrain sans accès appli...).
    compte_utilisateur_id = db.Column(db.Integer)

    # ⭐ Patron : "pas de vrai départ (offboarding) — suppression brute ou
    # juste un statut" — trace structurée d'un départ, distincte du simple
    # changement de `statut`. Voir MOTIFS_DEPART ci-dessus et
    # api_enregistrer_depart (routes/rh.py) : un vrai départ NE supprime
    # JAMAIS l'historique (congés, permissions, paie), contrairement à
    # DELETE /rh/employe/<id> (réservé aux erreurs de saisie).
    date_depart = db.Column(db.Date)
    motif_depart = db.Column(db.String(50))
    commentaire_depart = db.Column(db.Text)

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
    # ⭐ Patron : "documents jamais gérés (photo, pièce d'identité, contrat
    # — champs présents, jamais utilisés)" — les *_url ci-dessus existaient
    # déjà mais rien ne les remplissait. Le contenu réel est stocké en base
    # (base64, comme DocumentRH.contenu_pdf le fait déjà pour les
    # documents générés) plutôt que sur disque : le filesystem de Render
    # est éphémère (un fichier uploadé ne survivrait pas à un redeploy),
    # et aucun service de stockage cloud n'est configuré dans ce projet.
    # *_url pointe vers la route de téléchargement (voir
    # telecharger_document_employe, routes/rh.py) qui sert ce contenu —
    # rien d'autre dans l'appli n'a besoin de savoir comment il est
    # réellement stocké. `db.deferred` : ces blobs ne sont PAS chargés par
    # les requêtes Employe.query habituelles (listes paie/congés/RH...),
    # seulement quand on y accède explicitement (téléchargement).
    photo_url = db.Column(db.String(500))
    photo_data = db.deferred(db.Column(db.Text))
    photo_content_type = db.Column(db.String(100))
    piece_identite_url = db.Column(db.String(500))
    piece_identite_data = db.deferred(db.Column(db.Text))
    piece_identite_content_type = db.Column(db.String(100))
    piece_identite_filename = db.Column(db.String(255))
    contrat_url = db.Column(db.String(500))
    contrat_data = db.deferred(db.Column(db.Text))
    contrat_content_type = db.Column(db.String(100))
    contrat_filename = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    conges = db.relationship('Conge', backref='employe', lazy=True)
    permissions = db.relationship('Permission', backref='employe', lazy=True)
    # ⭐ Patron : "pas d'organigramme réel" — voir manager_id ci-dessus.
    # employe.manager (le N+1) / employe.subordonnes (l'équipe directe).
    subordonnes = db.relationship('Employe', backref=db.backref('manager', remote_side=[id]), lazy=True)

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

    def jours_avant_fin_contrat(self):
        """None si pas de date de fin (CDI/indéterminé) — sinon nombre de
        jours restants (négatif si déjà expiré)."""
        if not self.date_fin_contrat:
            return None
        return (self.date_fin_contrat - date.today()).days

    def contrat_a_renouveler(self, seuil_jours=30):
        """⭐ Patron : "alerte de renouvellement" — True si un contrat à
        durée déterminée expire dans moins de `seuil_jours` jours (y
        compris déjà expiré). Jamais de désactivation automatique : cette
        méthode sert uniquement à signaler, l'admin décide."""
        jours = self.jours_avant_fin_contrat()
        return jours is not None and jours <= seuil_jours

    @classmethod
    def contrats_a_renouveler(cls, structure_id, seuil_jours=30):
        """Employés actifs de la structure dont le contrat expire dans
        moins de `seuil_jours` jours (ou déjà expiré) — pour l'alerte du
        tableau de bord RH."""
        limite = date.today() + timedelta(days=seuil_jours)
        return cls.query.filter(
            cls.structure_id == structure_id,
            cls.statut == 'Actif',
            cls.date_fin_contrat.isnot(None),
            cls.date_fin_contrat <= limite,
        ).order_by(cls.date_fin_contrat.asc()).all()

    def chaine_hierarchique(self):
        """⭐ Patron : "pas d'organigramme réel" — liste des managers
        successifs, du plus proche (N+1) au plus haut. Protégée contre un
        cycle accidentel (ex. manager_id mal réaffecté en base
        directement) : s'arrête dès qu'un employé déjà vu réapparaît,
        plutôt que de boucler indéfiniment."""
        chaine = []
        courant = self.manager
        vus = {self.id}
        while courant is not None and courant.id not in vus:
            chaine.append(courant)
            vus.add(courant.id)
            courant = courant.manager
        return chaine

    def motif_depart_label(self):
        """Libellé lisible du motif de départ (voir MOTIFS_DEPART) — la
        valeur brute stockée reste le code, pas le libellé, pour rester
        stable si le libellé français est reformulé plus tard."""
        return MOTIFS_DEPART.get(self.motif_depart, self.motif_depart)

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
        congés déductibles + permissions prises sur l'année). Tout le reste
        (routes/rh.py compris) doit passer par cette méthode — plus de
        logique dupliquée.

        Deux corrections importantes apportées à cette méthode :
        - Filtre sur `annee_utilisation` (l'année à laquelle le congé est
          RÉELLEMENT imputé) et non plus sur l'année de `date_debut` — sans
          ça, un congé "force majeure" attribué à l'année suivante (voir
          Conge.annee_utilisation) n'était décompté NULLE PART : ni sur
          l'année de la demande (exclue exprès par l'admin), ni sur l'année
          suivante (le filtre regardait la mauvaise colonne).
        - Seuls les congés de type déductible comptent (voir
          TYPES_CONGE_DEDUCTIBLES) — un congé maladie/maternité/paternité/
          exceptionnel (conventionnel) ou sans solde n'entame plus le solde
          des 30 jours de congé annuel payé.
        """
        types_non_deductibles = [t for t, deductible in TYPES_CONGE_DEDUCTIBLES.items() if not deductible]
        conges_pris = db.session.query(db.func.sum(Conge.nombre_jours)).filter(
            Conge.employe_id == self.id,
            Conge.annee_utilisation == annee,
            ~Conge.type_conge.in_(types_non_deductibles),
            Conge.statut.in_(['en_attente', 'approuve', 'termine'])
        ).scalar() or 0

        # ⭐ Patron : "qu'on décide s'il faut enlever les jours de
        # permission dans les congés ou pas" — configurable par structure
        # (ParametragePaie.deduire_permissions_des_conges), défaut = True
        # pour ne rien changer au calcul existant tant que l'admin ne
        # bascule pas ce réglage lui-même.
        deduire_permissions = True
        try:
            parametrage = ParametragePaie.query.filter_by(structure_id=self.structure_id).first()
            if parametrage is not None:
                deduire_permissions = bool(parametrage.deduire_permissions_des_conges)
        except Exception:
            pass

        permissions_pris = db.session.query(db.func.sum(Permission.nombre_jours)).filter(
            Permission.employe_id == self.id,
            db.extract('year', Permission.date_debut) == annee,
            Permission.statut.in_(['en_attente', 'approuve'])
        ).scalar() or 0
        if not deduire_permissions:
            permissions_pris = 0

        total_annuel = self.conges_annuels or 30
        total_pris = conges_pris + permissions_pris
        solde = max(0, total_annuel - total_pris)

        return {
            'solde': solde,
            'pris': total_pris,
            'conges_pris': conges_pris,
            'permissions_pris': permissions_pris,
            'total_annuel': total_annuel,
            'permissions_deduites': deduire_permissions,
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

        # ⭐ Utiliser la nouvelle méthode — get_solde_detail() est déjà la
        # source unique, plus besoin de recalculer conges_pris/
        # permissions_pris ici en double avec une logique différente
        # (l'ancienne version ignorait annee_utilisation et les types non
        # déductibles, contrairement à get_solde_detail).
        detail = self.get_solde_detail(annee_actuelle)
        solde = detail['solde']

        if self.conges_pris_annee != detail['pris']:
            self.conges_pris_annee = detail['pris']
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


# ⭐ Congés conventionnels — patron : "les congés conventionnels tu les
# connais ils sont non déductibles des jours de congés". Seul le congé
# 'annuel' (le vrai congé payé légal, 30j/an) est décompté du solde ;
# maladie/maternité/paternité/exceptionnel (mariage, décès, naissance...)
# et sans_solde sont des droits séparés, distincts du Code du travail —
# les compter dans le même pot que le congé annuel les punirait deux fois
# (déjà sans salaire ou déjà encadrés par ailleurs). Avant ce commit,
# Employe.get_solde_detail() sommait TOUS les types sans distinction.
TYPES_CONGE_DEDUCTIBLES = {
    'annuel': True,
    'maladie': False,
    'maternite': False,
    'paternite': False,
    'sans_solde': False,
    'exceptionnel': False,
}


def conge_est_deductible(type_conge):
    """True seulement pour les types explicitement marqués déductibles —
    un type inconnu/mal saisi ne doit jamais échapper silencieusement au
    décompte du solde (mieux vaut décompter à tort que l'inverse)."""
    return TYPES_CONGE_DEDUCTIBLES.get(type_conge, True)


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
    # ⭐ Année à laquelle ce congé est réellement imputé — distincte de
    # l'année calendaire de date_debut pour le cas "force majeure" (patron :
    # "si les congés d'un employé est fini [...] en cas de force majeur on
    # lui donne des congés, que ça propose l'année suivante et les calculs
    # se suivent"). Ex: congé pris en décembre 2026 mais annee_utilisation=
    # 2027 -> décompté du solde 2027, pas 2026. Employe.get_solde_detail()
    # DOIT filtrer sur ce champ, jamais sur l'année de date_debut (bug
    # corrigé par ce commit : le champ existait déjà mais n'était utilisé
    # nulle part dans le calcul du solde, rendant ce mécanisme inopérant).
    annee_utilisation = db.Column(db.Integer, default=lambda: datetime.now().year)

    motif = db.Column(db.Text)
    piece_jointe = db.Column(db.String(500))
    signataire = db.Column(db.String(100))

    statut = db.Column(db.String(20), default='en_attente')
    approuve_par = db.Column(db.String(100))
    date_approbation = db.Column(db.Date)
    commentaire = db.Column(db.Text)

    # ⭐ Patron : "validation à plusieurs niveaux (SignatureRH) codée mais
    # jamais branchée" — lien vers le DocumentRH qui porte la chaîne de
    # signatures (SignatureRH) quand ParametragePaie.niveaux_validation_conges
    # > 1 pour la structure. NULL par défaut (comportement à un seul
    # niveau inchangé) : créé seulement au moment où le PREMIER niveau est
    # validé pour ce congé (voir _valider_conge, routes/rh.py).
    document_validation_id = db.Column(db.Integer, db.ForeignKey('documents_rh.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ========== MÉTHODES DE CALCUL ==========

    def est_deductible(self):
        return conge_est_deductible(self.type_conge)

    def statut_validation(self):
        """⭐ Résumé de la chaîne de validation multi-niveaux (SignatureRH)
        pour ce congé, ou None si aucune chaîne n'a été créée (validation
        à un seul niveau — cas par défaut, voir document_validation_id ci-
        dessus). Ordre croissant des niveaux."""
        if not self.document_validation_id:
            return None
        signatures = SignatureRH.query.filter_by(
            document_id=self.document_validation_id
        ).order_by(SignatureRH.validateur_niveau.asc()).all()
        if not signatures:
            return None
        prochain = next((s for s in signatures if s.statut == 'en_attente'), None)
        return {
            'niveaux_requis': len(signatures),
            'niveaux_valides': sum(1 for s in signatures if s.statut == 'approuve'),
            'prochain_niveau': prochain.validateur_niveau if prochain else None,
            'signatures': [{
                'niveau': s.validateur_niveau,
                'statut': s.statut,
                'signature_nom': s.signature_nom,
                'signature_date': s.signature_date.isoformat() if s.signature_date else None,
                'commentaire': s.commentaire,
            } for s in signatures],
        }

    def calculer_jours_ouvres(self, structure_id=None):
        """⭐ Jours OUVRABLES (lundi à samedi inclus), pas jours ouvrés —
        patron : "normalement les weekends font partie des jours de
        congés", confirmé par le Code du travail togolais (congé acquis à
        raison de 2,5 jours OUVRABLES/mois, soit 30/an — voir
        Employe.conges_annuels) et la pratique standard francophone : le
        samedi compte, seul le dimanche (repos hebdomadaire légal, jamais
        travaillé) et les jours fériés chômés déclarés par la structure
        (JourFerie) sont exclus. Avant ce fix, seuls lundi-vendredi
        étaient comptés (jours OUVRÉS), sous-comptant systématiquement le
        samedi.

        `structure_id` : passé explicitement pour les calculs de
        simulation (objet Conge non persisté, sans structure_id) — sinon
        celui de l'instance."""
        from datetime import timedelta
        sid = structure_id if structure_id is not None else self.structure_id
        feries = set()
        if sid is not None:
            feries = {jf.date for jf in JourFerie.query.filter(
                JourFerie.structure_id == sid,
                JourFerie.date >= self.date_debut,
                JourFerie.date <= self.date_fin,
            ).all()}
        count = 0
        current = self.date_debut
        while current <= self.date_fin:
            if current.weekday() < 6 and current not in feries:  # Lundi=0 ... Samedi=5 ; Dimanche=6 exclu
                count += 1
            current += timedelta(days=1)
        return count

    def calculer_date_reprise(self, structure_id=None):
        """⭐ Date de reprise SUGGÉRÉE = lendemain de la fin, avancée si ce
        jour tombe un dimanche ou un jour férié déclaré — reste modifiable
        au cas par cas après coup (voir PUT /rh/conge/<id>/reprise) : ex.
        un médecin de garde dont le congé finit un samedi doit parfois
        reprendre le dimanche (jour de garde), pas le lundi comme le
        suggérerait ce calcul par défaut."""
        from datetime import timedelta
        sid = structure_id if structure_id is not None else self.structure_id
        feries = set()
        if sid is not None:
            feries = {jf.date for jf in JourFerie.query.filter(
                JourFerie.structure_id == sid,
                JourFerie.date > self.date_fin,
                JourFerie.date <= self.date_fin + timedelta(days=14),
            ).all()}
        candidate = self.date_fin + timedelta(days=1)
        while candidate.weekday() == 6 or candidate in feries:
            candidate += timedelta(days=1)
        return candidate

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


# ⭐ Patron : "pas d'évaluations ni de sanctions disciplinaires" — types de
# sanction valides (voir SanctionDisciplinaire.type_sanction et
# routes/rh.py api_ajouter_sanction). Un type hors de cette liste est
# refusé côté API plutôt que silencieusement accepté.
TYPES_SANCTION = {
    'avertissement_verbal': 'Avertissement verbal',
    'avertissement_ecrit': 'Avertissement écrit',
    'blame': 'Blâme',
    'mise_a_pied': 'Mise à pied',
    'retrogradation': 'Rétrogradation',
    'licenciement_faute': 'Licenciement pour faute',
    'autre': 'Autre',
}


class EvaluationRH(db.Model):
    """⭐ Patron : "pas d'évaluations ni de sanctions disciplinaires" —
    évaluation périodique d'un employé (entretien annuel, bilan de
    période d'essai...). Immuable une fois créée (pas de champ statut ni
    de workflow de validation — une correction se fait en supprimant
    l'entrée erronée et en recréant, comme pour une écriture comptable
    dont on ne modifie jamais le contenu après coup)."""
    __tablename__ = 'evaluations_rh'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)

    periode = db.Column(db.String(100))  # ex. "Annuelle 2026", "Fin de période d'essai"
    date_evaluation = db.Column(db.Date, nullable=False)
    evaluateur_nom = db.Column(db.String(100), nullable=False)
    # ⭐ Note sur 20 (usage francophone courant) — nullable : une
    # évaluation qualitative pure, sans note chiffrée, reste possible.
    note = db.Column(db.Numeric)
    points_forts = db.Column(db.Text)
    axes_amelioration = db.Column(db.Text)
    commentaire = db.Column(db.Text)

    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employe = db.relationship('Employe', backref='evaluations')


class SanctionDisciplinaire(db.Model):
    """⭐ Patron : "pas d'évaluations ni de sanctions disciplinaires" —
    sanction disciplinaire appliquée à un employé. Immuable une fois
    créée, même logique que EvaluationRH ci-dessus."""
    __tablename__ = 'sanctions_disciplinaires'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    employe_id = db.Column(db.Integer, db.ForeignKey('employes.id'), nullable=False)

    type_sanction = db.Column(db.String(50), nullable=False)
    date_sanction = db.Column(db.Date, nullable=False)
    motif = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    # ⭐ Nombre de jours — pertinent seulement pour une mise à pied, mais
    # laissé générique (nullable, ignoré pour les autres types) plutôt
    # que d'ajouter une table/un champ spécifique à un seul type.
    duree_jours = db.Column(db.Integer)
    decide_par = db.Column(db.String(100))

    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employe = db.relationship('Employe', backref='sanctions')

    def type_sanction_label(self):
        return TYPES_SANCTION.get(self.type_sanction, self.type_sanction)


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
        """⭐ Ne compte que les écritures VALIDÉES (statut='valide') — corrigé
        car c'était le seul endroit du module comptable à ne pas filtrer le
        statut (generer_balance/generer_journal/generer_grand_livre le font
        déjà). Sans ce filtre, une écriture brouillon/en attente/refusée
        faussait la trésorerie, le chiffre d'affaires, le solde du plan
        comptable ET le rapprochement bancaire — 4 endroits qui utilisent
        cette méthode — ce qui rendait les totaux du tableau de bord
        incohérents entre eux (repéré par le patron : "mes calculs ne
        tombent pas")."""
        query = db.session.query(db.func.sum(LigneEcriture.debit - LigneEcriture.credit)).filter(
            LigneEcriture.compte_id == self.id,
            LigneEcriture.ecriture.has(EcritureComptable.statut == 'valide'),
        )
        if date_debut:
            query = query.filter(LigneEcriture.ecriture.has(EcritureComptable.date_ecriture >= date_debut))
        if date_fin:
            query = query.filter(LigneEcriture.ecriture.has(EcritureComptable.date_ecriture <= date_fin))
        return query.scalar() or 0


class EcritureComptable(db.Model):
    __tablename__ = 'ecritures_comptables'

    # Journaux auxiliaires (journaux divisionnaires SYSCOHADA)
    # ⭐ 'BQ' -> 'BQU', 'RAN' ajouté — porté depuis GHP (2026-09-30), voir
    # son commentaire équivalent. Les écritures déjà enregistrées sous
    # 'BQ' sont migrées par scripts/renommer_journal_bq_en_bqu.py.
    JOURNAUX = {
        'VTE': "Journal des ventes",
        'CAI': "Journal de caisse",
        'BQU': "Journal de banque",
        'ACH': "Journal des achats",
        'SAL': "Journal des salaires",
        'TR': "Journal de trésorerie",
        'OD': "Journal des opérations diverses",
        'RAN': "Journal des à-nouveaux (report à nouveau)",
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

    # ⭐ Compte auxiliaire (tiers) — demande explicite du comptable : pouvoir
    # suivre le solde d'un client/fournisseur précis, pas seulement le compte
    # général 4111/401 où tout le monde est mélangé. Rempli UNIQUEMENT sur
    # les lignes qui touchent réellement un compte de tiers (voir
    # services/comptabilite_service.py) — vide sur les autres (une ligne de
    # charge/vente/trésorerie n'a pas de tiers). Pas de vraie FK : 'patient'
    # pointe vers Patient.id, 'fournisseur' vers Fournisseur.id — deux
    # univers d'id différents partageant ce même champ, comme ailleurs dans
    # l'appli (CodeQrConnexion, IdentifiantWebauthn...). tiers_nom est
    # dénormalisé pour l'affichage/le FEC (CompAuxLib) sans jointure.
    tiers_type = db.Column(db.String(20))   # 'patient' | 'fournisseur'
    tiers_id = db.Column(db.Integer, index=True)
    tiers_nom = db.Column(db.String(255))

    # ⭐ Lettrage — 2e chantier demandé par le comptable après les comptes
    # auxiliaires : rapprocher une créance/dette (ligne débit) avec son ou
    # ses règlement(s) (ligne(s) crédit) sur un MÊME compte, en leur
    # attribuant un code commun ("A", "B"...). Uniquement manuel pour
    # l'instant (voir services/comptabilite_service.py: lettrer_lignes) —
    # c'est le comptable qui sait quelles lignes se correspondent
    # vraiment ; seul le cas non-ambigu (un seul débit + un seul crédit du
    # même montant, encore non lettrés, sur le même compte) est proposé en
    # un clic ("auto-lettrage"), le reste se sélectionne à la main.
    lettre = db.Column(db.String(10), index=True)
    date_lettrage = db.Column(db.DateTime)


class ParametrageTva(db.Model):
    """Assujettissement et taux de TVA par structure — 3e chantier demandé
    par le comptable (comptes auxiliaires → lettrage → TVA). Volontairement
    configurable (pas un COMPTE_TVA_TAUX codé en dur) : le taux togolais
    actuel est 18%, mais peut changer, et toutes les structures utilisant
    ce logiciel ne sont pas forcément assujetties (soins médicaux souvent
    exonérés selon les cas — chaque structure garde la main). Les prix
    saisis dans l'appli sont TTC (confirmé) : voir
    services/comptabilite_service.py:generer_ecriture_vente pour le calcul
    HT/TVA qui en découle."""
    __tablename__ = 'parametrage_tva'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    assujetti = db.Column(db.Boolean, default=True)
    taux = db.Column(db.Numeric, default=18.0)  # en %
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_ou_creer(cls, structure_id):
        param = cls.query.filter_by(structure_id=structure_id).first()
        if not param:
            param = cls(structure_id=structure_id)
            db.session.add(param)
            db.session.commit()
        return param


class ParametrageAbonnement(db.Model):
    """Abonnement mensuel SSoftOneV10 par structure — paramétré depuis
    l'administration globale (super-admin), pas par la structure elle-même.
    `prix_mensuel` et `date_debut_suivi` restent à None tant que le
    super-admin n'a rien configuré : dans ce cas aucun verrouillage ne
    s'applique (voir services/abonnement_service.py:statut_abonnement).
    Le paiement lui-même n'est pas suivi ici : c'est une Depense réelle
    (donc déjà validée, voir _demander_validation) avec
    motif='abonnement_ssoftonev10' dans le mois courant qui fait foi."""
    __tablename__ = 'parametrage_abonnement'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    prix_mensuel = db.Column(db.Numeric)
    date_debut_suivi = db.Column(db.Date)
    onglets_masques = db.Column(db.Text, default='')  # clés MODULES_STRUCTURE séparées par virgules
    grace_active = db.Column(db.Boolean, default=False)
    grace_note = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_ou_creer(cls, structure_id):
        param = cls.query.filter_by(structure_id=structure_id).first()
        if not param:
            param = cls(structure_id=structure_id)
            db.session.add(param)
            db.session.commit()
        return param

    def liste_onglets_masques(self):
        return [c.strip() for c in (self.onglets_masques or '').split(',') if c.strip()]


class PaiementInstallation(db.Model):
    """Paiement de la somme d'installation de SSoftOneV10 par une structure
    — enregistré directement par le super-admin depuis admin_global.html
    (pas de circuit de validation ici, c'est lui-même qui encaisse). Un
    même versement peut être réparti sur plusieurs moyens à la fois (ex.
    espèces + Mixx by Yas) — d'où trois montants distincts plutôt qu'un
    unique moyen_paiement comme pour l'abonnement mensuel (voir Depense).
    Le montant total est la somme des trois, calculée à l'affichage."""
    __tablename__ = 'paiements_installation'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    montant_espece = db.Column(db.Numeric, default=0)
    montant_mixx = db.Column(db.Numeric, default=0)
    reference_mixx = db.Column(db.String(100))
    montant_moov = db.Column(db.Numeric, default=0)
    reference_moov = db.Column(db.String(100))
    date_paiement = db.Column(db.Date, nullable=False)
    date_enregistrement = db.Column(db.DateTime, default=datetime.utcnow)
    enregistre_par = db.Column(db.String(255))
    note = db.Column(db.Text)

    @property
    def montant_total(self):
        return (self.montant_espece or 0) + (self.montant_mixx or 0) + (self.montant_moov or 0)


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
    # ⭐ L'aide hospitalière pouvait seulement être saisie en % — un taux mal
    # tapé (ex: 500 au lieu de 50) donnait un net à payer négatif. Ajout
    # d'un mode "montant direct" ; ce champ trace lequel des deux a été
    # utilisé (taux_aide reste le % dans un cas, le montant brut saisi dans
    # l'autre — voir calculerTotal() dans pharma_vente.html/actes_vente.html).
    # Défaut 'pourcentage' : les lignes existantes (toutes en %) restent
    # correctement interprétées sans migration de données.
    type_aide = db.Column(db.String(20), default='pourcentage')  # 'pourcentage' | 'montant'
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
    # ⭐ Code prescripteur AMU (CNSS/INAM/TNS) — patron : "il va falloir
    # qu'on ajoute dans la table des medecin code prescripteur". Même code
    # pour les 3 régimes (contrairement au code formation sanitaire,
    # propre à la structure — voir ParametrageAmuCnss.code_prestataire) :
    # réutilisé tel quel pour pré-remplir l'Entente Préalable.
    code_prescripteur = db.Column(db.String(50))
    # ⭐ NIF (numéro d'identification fiscale) — patron (2026-10-09) : la RSPS
    # retenue sur la part médecin « concerne les médecins qui ont le NIF ».
    # Sans NIF : taux_rsps_sans_nif de la structure (0 par défaut) — voir
    # services/part_medecin_service.parametres_rsps().
    nif = db.Column(db.String(30))
    
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
    # ⭐ Nullable depuis la demande de RDV par le portail (2026-10-07) : le
    # patient peut ne pas choisir de médecin, la structure l'attribue en confirmant.
    medecin_id = db.Column(db.Integer, db.ForeignKey('medecins.id'), nullable=True)
    
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
    # ⭐ Demande de rendez-vous par le patient depuis son portail (patron,
    # 2026-10-07 : "le patient lui-même depuis chez lui puisse demander un
    # rendez-vous, l'hôpital reçoit, examine et lui confirme, et le patient
    # reçoit une notification"). statut 'demande' tant que la structure n'a
    # pas répondu ; la réponse (confirmation ou refus) est conservée et
    # affichée au patient jusqu'à ce qu'il l'ait vue.
    source = db.Column(db.String(20), default='personnel')  # 'personnel' | 'portail'
    demande_le = db.Column(db.DateTime)
    creneau_souhaite = db.Column(db.String(20))  # 'matin' | 'apres_midi' | 'indifferent'
    message_patient = db.Column(db.Text)
    reponse_structure = db.Column(db.Text)
    repondu_le = db.Column(db.DateTime)
    vu_par_patient_le = db.Column(db.DateTime)
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
            'absent': 'Absent',
            'demande': 'Demande du patient'
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
            'absent': 'bg-dark',
            'demande': 'bg-primary'
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


# ⭐ Lien de consultation des rendez-vous partagé aux médecins (patron,
# 2026-10-07 : "que les secrétaires puissent envoyer dans le groupe WhatsApp
# un lien pour que les médecins consultent les rdv et le calendrier
# uniquement"). Un jeton par structure, lecture seule, sans connexion ;
# régénérer le jeton invalide l'ancien lien.
class AffectationPartMedecin(db.Model):
    """⭐ Un acte affecté à UN OU PLUSIEURS médecins réalisateurs (patron,
    2026-10-08 : « plusieurs spécialités que les patients peuvent consulter
    en même temps ; plusieurs médecins réalisent l'échographie pelvienne,
    et chacun a sa part »). À la vente, le sélecteur « Réalisé par » ne
    propose que ces médecins (pré-rempli s'il n'y en a qu'un). taux_medecin
    vide = taux de l'acte (TauxPartMedecin), sinon taux propre à ce médecin."""
    __tablename__ = 'affectations_part_medecin'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom_acte = db.Column(db.String(255), nullable=False)
    medecin_id = db.Column(db.Integer, nullable=False)
    taux_medecin = db.Column(db.Numeric)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('structure_id', 'nom_acte', 'medecin_id', name='uq_affectation_part_medecin'),
    )


class ParametragePartMedecin(db.Model):
    """⭐ RSPS (retenue à la source sur prestations de services) appliquée
    par défaut sur la part brute du médecin — 5 % à reverser à l'OTR
    (patron, 2026-10-08). Une ligne par structure."""
    __tablename__ = 'parametrage_part_medecin'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    taux_rsps = db.Column(db.Numeric, default=5)
    rsps_active = db.Column(db.Boolean, nullable=False, default=True)
    # ⭐ Médecin SANS NIF (patron, 2026-10-09 : la RSPS concerne les médecins
    # qui ont le NIF) — 0 par défaut = aucune retenue ; modifiable si la
    # règle fiscale de la structure prévoit un autre taux.
    taux_rsps_sans_nif = db.Column(db.Numeric, default=0)
    modifie_le = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    modifie_par = db.Column(db.String(150))


class VersementRsps(db.Model):
    """⭐ Versement groupé à l'OTR de la RSPS retenue sur les parts médecins
    payées (en général un versement par mois) : dépense + écriture
    comptable (447 RSPS à reverser / caisse), les clôtures concernées
    pointent dessus (PeriodePartMedecin.rsps_versement_id)."""
    __tablename__ = 'versements_rsps'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    libelle = db.Column(db.String(255))
    montant = db.Column(db.Numeric, nullable=False)
    nb_periodes = db.Column(db.Integer, default=0)
    depense_id = db.Column(db.Integer)
    date_versement = db.Column(db.Date)
    mode_paiement = db.Column(db.String(20))
    reference_paiement = db.Column(db.String(100))
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ParametrageRendezVous(db.Model):
    """Réglages du module rendez-vous propres à une structure. Pour l'instant
    la règle de paiement du bon de consultation (patron, 2026-10-07) : un
    contrôle du même type de consultation dans les N jours est sans frais,
    au-delà (ou autre type de consultation) le patient repaie. N vient d'ici
    s'il est renseigné, sinon 30 jours (structure publique, statut AMU) ou
    15 jours (privée) — voir services/paiement_consultation_service.py."""
    __tablename__ = 'parametrage_rendez_vous'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    delai_controle_jours = db.Column(db.Integer)            # NULL = délai par défaut selon public/privé
    regle_paiement_active = db.Column(db.Boolean, nullable=False, default=True)
    modifie_le = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    modifie_par = db.Column(db.String(150))


class LienPartageRendezVous(db.Model):
    __tablename__ = 'liens_partage_rdv'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    token = db.Column(db.String(80), nullable=False, unique=True)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    regenere_le = db.Column(db.DateTime)

    @classmethod
    def obtenir_ou_creer(cls, structure_id, user_nom=None):
        import secrets
        lien = cls.query.filter_by(structure_id=structure_id).first()
        if not lien:
            lien = cls(structure_id=structure_id, token=secrets.token_hex(24), created_by=user_nom)
            db.session.add(lien)
            db.session.commit()
        return lien

    def regenerer(self):
        import secrets
        self.token = secrets.token_hex(24)
        self.regenere_le = datetime.utcnow()
        db.session.commit()
        return self


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


class HabilitationTemporaire(db.Model):
    """Octroi ponctuel, par l'admin, d'un accès à une section normalement
    fermée au rôle de l'utilisateur visé — révocable à tout moment (voir
    utils/permissions.py:a_acces, seul endroit qui lit cette table). Les
    comptes utilisateurs vivent dans Google Sheets (struct_N_users), pas
    en base : comme ValidationDemande.demandeur_id/nom ci-dessus, on
    stocke l'ID Sheets + le nom en clair plutôt qu'une vraie clé
    étrangère. On garde la ligne après révocation (active=False) au lieu
    de la supprimer, pour l'historique."""
    __tablename__ = 'habilitations_temporaires'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    utilisateur_id = db.Column(db.Integer, nullable=False)  # ID Sheets (struct_N_users)
    utilisateur_nom = db.Column(db.String(255))
    permission_cle = db.Column(db.String(50), nullable=False)  # voir utils/permissions.py:PERMISSIONS
    accordee_par_nom = db.Column(db.String(255))
    date_octroi = db.Column(db.DateTime, default=datetime.utcnow)
    date_expiration = db.Column(db.DateTime)  # optionnelle, null = indéfini (jusqu'à révocation manuelle)
    active = db.Column(db.Boolean, default=True)
    date_revocation = db.Column(db.DateTime)
    revoque_par_nom = db.Column(db.String(255))


class CodeQrConnexion(db.Model):
    """Connexion par code QR (badge personnel), en plus d'email/mot de
    passe — jamais obligatoire. Seul l'admin génère/révoque, depuis
    Administration (voir app.py: /api/admin/qr/*, /login/qr). Comme les
    autres tables de cette session, les comptes vivent dans Google
    Sheets, pas en base : `type_compte` distingue une ligne de
    struct_N_users ('user') du compte admin/propriétaire lui-même
    ('structure', ligne de la feuille structures) — deux univers
    d'ID Sheets différents partagant ce même mécanisme."""
    __tablename__ = 'codes_qr_connexion'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    utilisateur_id = db.Column(db.Integer, nullable=False)  # ID Sheets
    type_compte = db.Column(db.String(20), nullable=False)  # 'user' | 'structure'
    utilisateur_nom = db.Column(db.String(255))
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    actif = db.Column(db.Boolean, default=True)
    genere_par_nom = db.Column(db.String(255))
    date_generation = db.Column(db.DateTime, default=datetime.utcnow)
    date_revocation = db.Column(db.DateTime)
    date_derniere_utilisation = db.Column(db.DateTime)
    # 🔥 PAS de contrainte unique sur (structure_id, utilisateur_id,
    # type_compte) : régénérer un code après une révocation crée une
    # NOUVELLE ligne (l'ancienne reste, actif=False, pour l'historique —
    # même principe que HabilitationTemporaire) ; une contrainte unique
    # sur ce triplet interdirait justement cette 2e ligne et ferait
    # planter toute régénération après révocation (détecté en testant
    # en direct : 500 sur /api/admin/qr/generer après une révocation).


# ⭐ Code-barres interne (scan douchette USB/Bluetooth ou caméra téléphone)
# pour ajouter rapidement un acte/produit au panier (Actes/Vente, Pharmacie,
# Hospitalisation, Proforma) — patron, 2026-10-02. Le catalogue actes/
# produits lui-même reste dans Google Sheets (identifié par NOM, comme
# O101/CorrespondanceSalleAmu plus haut) ; SEULE la correspondance
# code-barres <-> article vit ici en Postgres. Le code généré commence
# TOUJOURS par l'ID de la structure (voir generer_code()) : unique entre
# structures sans vérification globale, et la contrainte unique ci-dessous
# ne fait que confirmer cette garantie.
class CodeBarreArticle(db.Model):
    __tablename__ = 'codes_barres_articles'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    type_article = db.Column(db.String(10), nullable=False)  # 'acte' | 'produit'
    nom_article = db.Column(db.String(255), nullable=False)
    code_barre = db.Column(db.String(40), unique=True, nullable=False, index=True)
    created_by_nom = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def generer_code(cls, structure_id, type_article):
        """Code lisible par CODE128 : "<structure_id><A|P><0001>", ex.
        "12A0007" = 7e acte codé par la structure 12. Le numéro de séquence
        repart du plus grand suffixe numérique déjà utilisé pour ce couple
        (structure, type) — pas un simple COUNT(), qui réutiliserait un
        numéro déjà attribué après une suppression."""
        prefixe = 'A' if type_article == 'acte' else 'P'
        base = f"{structure_id}{prefixe}"
        max_seq = 0
        for entree in cls.query.filter_by(structure_id=structure_id, type_article=type_article).all():
            suffixe = entree.code_barre[len(base):]
            if suffixe.isdigit():
                max_seq = max(max_seq, int(suffixe))
        return f"{base}{max_seq + 1:04d}"


class IdentifiantWebauthn(db.Model):
    """Connexion par biométrie de l'appareil (Face ID / Windows Hello /
    empreinte), via WebAuthn — à ne PAS confondre avec EmpreinteEmploye
    (services/pointage_service.py), qui sert à la borne de pointage RH et
    concerne les employés (table employes) : ceci sert à SE CONNECTER à
    l'appli et concerne les comptes de connexion (Google Sheets, comme
    CodeQrConnexion). Contrairement au QR (bearer secret imprimable, donc
    volable/copiable), la clé privée ne quitte jamais la puce sécurisée de
    l'appareil ; ce qu'on stocke ici (clé PUBLIQUE) ne permet à personne de
    se connecter sans l'appareil physique + le capteur biométrique.

    Auto-enregistrement uniquement : contrairement au QR, l'admin ne peut
    pas générer ça pour quelqu'un d'autre (il faudrait le visage/doigt de
    la personne) — chaque compte enregistre lui-même son propre appareil,
    une fois connecté par mot de passe/QR (voir app.py: /api/webauthn/*).
    Un compte peut avoir plusieurs appareils enregistrés (poste accueil,
    téléphone personnel...)."""
    __tablename__ = 'identifiants_webauthn'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    utilisateur_id = db.Column(db.Integer, nullable=False)  # ID Sheets
    type_compte = db.Column(db.String(20), nullable=False)  # 'user' | 'structure'
    utilisateur_nom = db.Column(db.String(255))
    credential_id = db.Column(db.Text, unique=True, nullable=False, index=True)  # base64, identifiant WebAuthn
    public_key = db.Column(db.Text, nullable=False)                              # base64, clé publique COSE
    sign_count = db.Column(db.Integer, default=0)                                # anti-clonage (doit toujours augmenter)
    libelle_appareil = db.Column(db.String(100))   # ex: "PC accueil", saisi par l'utilisateur
    actif = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_revocation = db.Column(db.DateTime)
    derniere_utilisation = db.Column(db.DateTime)


class VerrouillageConnexion(db.Model):
    """Anti-brute-force sur la connexion : 4 mots de passe erronés
    consécutifs verrouillent le compte 10 minutes (voir app.py:
    _verrouillage_actif/_enregistrer_echec/_reinitialiser_echecs, seuls
    endroits qui lisent/écrivent cette table). Clé sur l'email plutôt que
    sur un ID Sheets : la connexion cherche par email et peut aboutir à
    un compte utilisateur OU un compte structure/admin, deux univers
    d'ID différents — l'email est le seul identifiant commun aux deux."""
    __tablename__ = 'verrouillage_connexion'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    tentatives_echouees = db.Column(db.Integer, default=0)
    verrouille_jusqu_a = db.Column(db.DateTime)  # null = pas verrouillé
    derniere_tentative = db.Column(db.DateTime)


class MessageChat(db.Model):
    """Chat interne : salon commun (destinataire_id NULL) + messages
    privés entre deux employés. Comptes utilisateurs en Google Sheets, pas
    en base — même pattern que ValidationDemande/HabilitationTemporaire
    ci-dessus : ID Sheets + nom en clair plutôt qu'une clé étrangère."""
    __tablename__ = 'messages_chat'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    expediteur_id = db.Column(db.Integer, nullable=False)
    expediteur_nom = db.Column(db.String(255))
    destinataire_id = db.Column(db.Integer, nullable=True)  # NULL = salon commun
    destinataire_nom = db.Column(db.String(255))
    contenu = db.Column(db.Text, nullable=False)
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow)
    supprime = db.Column(db.Boolean, default=False)  # suppression douce, par l'auteur


class ChatDernierVu(db.Model):
    """Un seul mécanisme de 'non lus' pour le salon ET chaque DM : `fil`
    vaut 'salon' ou l'ID Sheets (str) de l'autre utilisateur. Non-lus d'un
    fil = messages de ce fil postérieurs à date_dernier_vu."""
    __tablename__ = 'chat_dernier_vu'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    utilisateur_id = db.Column(db.Integer, nullable=False)
    fil = db.Column(db.String(50), nullable=False)
    date_dernier_vu = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('structure_id', 'utilisateur_id', 'fil', name='uq_chat_vu'),)


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
    # ⭐ Justificatif de paiement mobile money — obligatoire pour la charge
    # "Abonnement SSoftOneV10" (voir api_add_depense), laissé vide pour les
    # autres motifs. moyen_paiement: 'mixx' | 'moov'.
    moyen_paiement = db.Column(db.String(20))
    reference_paiement = db.Column(db.String(100))
    date_paiement = db.Column(db.Date)


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

    # ⭐ TVA déductible — `montant_total` reste TOUJOURS le vrai montant dû
    # au fournisseur (TTC), inchangé quoi que l'utilisateur ait saisi : ça
    # garde tout le suivi existant (reste_a_payer, ReglementFournisseur)
    # valide sans y toucher. Ces deux champs ne servent qu'à la génération
    # de l'écriture (HT/TVA, voir generer_ecriture_achat_fournisseur) et à
    # l'affichage ("vous avez saisi 1000 HT") — si l'utilisateur choisit
    # HT à la saisie, la route convertit en TTC AVANT d'écrire montant_total.
    montant_saisi = db.Column(db.Numeric)          # ce que l'utilisateur a tapé, avant conversion
    type_montant_saisi = db.Column(db.String(5), default='ttc')  # 'ttc' | 'ht'

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
    # ⭐ Date à laquelle le bordereau papier a été réellement déposé chez
    # l'assureur — saisie manuellement (jamais déduite automatiquement d'un
    # encaissement, qui peut arriver des semaines après le dépôt réel) au
    # moment de l'impression du bordereau (voir routes/statistiques.py:
    # bordereau_assurance / /api/assurances/factures/<id>/marquer_depose).
    # Même logique que FactureAmuMensuelle.date_depot, mais ici pour le
    # bordereau détaillé (AMU ET complémentaire/CAC).
    date_depot = db.Column(db.Date)
    # ⭐ Clôture — patron : "faire en sorte que si qu'on puisse cloturer
    # une facture amu comme cac [...] apres cette étape aucune modification
    # n'est plus possible". Verrou définitif (contrairement à date_depot,
    # qui n'a jamais bloqué de modification) posé sur ce bordereau — la
    # regénération mensuelle (generer_factures_assurance) et le nouveau
    # dépôt (marquer_depose) le respectent. L'encaissement (/payer) reste
    # volontairement possible après clôture : un assureur peut régler des
    # semaines après le dépôt du bordereau, ça n'a rien à voir avec le
    # contenu du document lui-même.
    cloturee = db.Column(db.Boolean, default=False)
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
    # ⭐ Même compagnie complémentaire, même acte : un PBR peut exister pour
    # CE patient précis (son contrat/sa police) et pas pour un autre assuré
    # chez la même compagnie (contrat différent, remboursé directement sur
    # le prix clinique) — voir PbrComplementaire (plus bas dans ce fichier)
    # et charger_pbr_complementaires() (services/hospitalisation_service.py).
    # True par défaut = comportement le plus courant (appliquer le plafond
    # quand une entrée existe) ; décoché ici, le calcul retombe sur le
    # reste après AMU non plafonné même si une entrée existe pour l'acte.
    applique_pbr_cac = db.Column(db.Boolean, default=True)
    # ⭐ Lequel des deux PBR (PbrComplementaire.pbr_1/pbr_2) utiliser quand
    # applique_pbr_cac est actif — 'defaut' (pbr_1, celui qu'on applique
    # d'habitude) ou 'alternatif' (pbr_2, si ce contrat précis diffère).
    # Choisissable en direct depuis la vente.
    pbr_cac_variante = db.Column(db.String(20), default='defaut')
    # ⭐ Affichage HT/TVA/TTC sur le reçu/facture papier — décoché par
    # défaut (les prix de l'appli sont déjà TTC, voir ParametrageTva ;
    # cocher n'ajoute AUCUN montant, ça affiche juste la décomposition
    # Sous-total HT / TVA / Total TTC pour un document plus formel, ex. une
    # facture demandée par une compagnie/assurance). Taux repris de
    # ParametrageTva.taux (18% par défaut, configurable par structure) —
    # pas de taux propre ici, un seul réglage cohérent partout.
    applique_tva = db.Column(db.Boolean, default=False)
    taux_modifie = db.Column(db.Boolean, default=False)
    taux_original = db.Column(db.Numeric, default=0)
    prise_en_charge2 = db.Column(db.Numeric, default=0)
    assurances_data = db.Column(db.JSON)
    base_remboursement = db.Column(db.Numeric, default=0)
    base_cac = db.Column(db.Numeric, default=0)
    # ⭐ Aide hospitalière (remise) — absente jusqu'ici du formulaire de
    # création proforma ; ajoutée pour que le même mécanisme (% ou montant
    # direct, voir Vente.type_aide) fonctionne aussi ici, pas seulement en
    # vente directe. Portée telle quelle à la vente à la conversion.
    taux_aide = db.Column(db.Numeric, default=0)
    aide_hospitaliere = db.Column(db.Numeric, default=0)
    type_aide = db.Column(db.String(20), default='pourcentage')  # 'pourcentage' | 'montant'
    # ⭐ Permet de créer une proforma pour un patient assuré SANS appliquer
    # son assurance principale (il ne souhaite pas l'utiliser) — même
    # mécanisme que Vente.assurance_principale_active, absent jusqu'ici du
    # formulaire de création proforma.
    assurance_principale_active = db.Column(db.Boolean, default=True)
    # ⭐ Traçabilité : proforma générée automatiquement depuis "Facturer le
    # séjour" (module Hospitalisation) — NULL pour une proforma classique.
    hospitalisation_id = db.Column(db.Integer)


# ============================================================
# HOSPITALISATION — suivi jour par jour + tarification par palier
# ============================================================
class Hospitalisation(db.Model):
    """Un séjour hospitalier. Les soins (actes/médicaments) administrés
    jour après jour sont enregistrés à part (SoinHospitalisation) et
    convertis en Proforma puis en Vente à la clôture — voir
    services/hospitalisation_service.py et la route
    /api/hospitalisation/<id>/facturer, qui réutilisent intégralement le
    pipeline proforma→vente existant (créance, caisse, comptabilité,
    journal, facturation assurance mensuelle) plutôt que d'en écrire un
    parallèle."""
    __tablename__ = 'hospitalisations'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    numero_local = db.Column(db.Integer)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255), nullable=False)
    date_entree = db.Column(db.Date, nullable=False)
    date_sortie = db.Column(db.Date)  # NULL tant que le séjour est en cours
    # ⭐ chambre_service reste le texte affiché partout (dérivé automatiquement
    # de service > chambre > lit à la création si lit_id est fourni, saisi
    # à la main sinon — structure n'ayant pas encore configuré son
    # inventaire, comportement inchangé). lit_id est la référence
    # structurée qui pilote l'occupation automatique (voir
    # LitHospitalisation) ; NULL si pas d'inventaire utilisé pour ce séjour.
    chambre_service = db.Column(db.String(255))
    lit_id = db.Column(db.Integer)
    # ⭐ Tarif de chambre du séjour (acte du catalogue, choisi tôt — pas
    # seulement à la clôture) : permet de PROJETER en direct, tant que le
    # séjour est en cours, une charge chambre = ce tarif x nombre_jours
    # dans "Solde en cours" et la répartition assurance (voir
    # page_hospitalisation_suivi) — sans quoi ces deux totaux ne bougent
    # jamais avant la clôture, même si on corrige la date d'entrée
    # (signalé). Optionnel : NULL si la structure facture uniquement des
    # actes/médicaments au jour le jour sans tarif de chambre dédié.
    chambre_acte_id = db.Column(db.Integer)
    chambre_acte_nom = db.Column(db.String(255))
    chambre_prix = db.Column(db.Numeric)
    chambre_pbr = db.Column(db.Numeric)
    chambre_prise_en_charge_amu = db.Column(db.Boolean, default=True)
    chambre_prise_en_charge_cac = db.Column(db.Boolean, default=True)
    # ⭐ Catégorie officielle de salle AMU (observation/cabine/salle_commune_
    # 3_6/.../reanimation — voir utils/grille_amu_hospitalisation.py),
    # choisie au moment où le tarif de chambre est défini (pas de page de
    # configuration séparée) — sert à calculer le PBR par palier depuis la
    # grille officielle au lieu de deviner par le nom dans le catalogue
    # Sheets. NULL tant que non précisée (repli sur l'ancien mécanisme).
    chambre_categorie_amu = db.Column(db.String(40))
    # Snapshot de l'assurance du patient au moment de l'admission (même
    # schéma que Proforma/Vente) — éditable ligne par ligne à la conversion.
    assurance_nom = db.Column(db.String(255))
    taux_assurance = db.Column(db.Numeric, default=0)
    assurance2_nom = db.Column(db.String(255))
    taux_assurance2 = db.Column(db.Numeric, default=0)
    societe_assurance2 = db.Column(db.String(255))
    # ⭐ Activable/désactivable pour CE séjour précisément (ex. le patient
    # n'a pas apporté sa carte d'assurance aujourd'hui, ou n'est plus
    # assuré) — sans effacer assurance_nom/assurance2_nom, réactivable à
    # tout moment. Même paire de champs que Vente/Proforma
    # (assurance_principale_active/assurance2_active), par cohérence.
    assurance_principale_active = db.Column(db.Boolean, default=True)
    assurance2_active = db.Column(db.Boolean, default=True)
    # ⭐ Même compagnie complémentaire, même acte : un PBR peut exister pour
    # CE patient précis (son contrat) et pas pour un autre assuré de la
    # même compagnie (remboursé directement sur le prix clinique) — voir
    # PbrComplementaire plus bas et charger_pbr_complementaires()
    # (services/hospitalisation_service.py). Décoché, le calcul retombe
    # sur le reste après AMU non plafonné même si une entrée existe.
    applique_pbr_cac = db.Column(db.Boolean, default=True)
    # ⭐ Voir le même champ sur Proforma — 'defaut' (pbr_1) ou 'alternatif'
    # (pbr_2), choisissable en direct depuis le suivi du séjour.
    pbr_cac_variante = db.Column(db.String(20), default='defaut')
    # ⭐ Voir le même champ sur Proforma — affichage HT/TVA/TTC sur le
    # reçu/facture papier, décoché par défaut, choisissable en direct
    # depuis le suivi du séjour avant facturation.
    applique_tva = db.Column(db.Boolean, default=False)
    statut = db.Column(db.String(50), default='en_cours')  # en_cours/sortie/facturee
    proforma_id = db.Column(db.Integer)
    vente_id = db.Column(db.Integer)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # ⭐ Recettes par service (patron, 2026-09-30) : service RÉEL du séjour
    # (ServiceHospitalisation), pour attribuer TOUTE la recette du séjour à
    # ce service à la facturation — indépendant de lit_id (un séjour sans
    # lit/chambre assigné doit quand même pouvoir être rattaché à un
    # service). Choisi à l'admission ; dérivé automatiquement du service de
    # la chambre si un lit est choisi, mais toujours modifiable/forçable.
    # Voir services/service_acte_service.py.
    service_id = db.Column(db.Integer)

    @property
    def nombre_jours(self):
        fin = self.date_sortie or date.today()
        if not self.date_entree:
            return 0
        return max((fin - self.date_entree).days, 0)

    @property
    def dernier_jour_facture(self):
        """Dernière nuitée réellement facturée (convention hôtelière déjà
        utilisée pour nombre_jours : la date de sortie elle-même n'est pas
        une nuit facturée, c'est le jour du départ). Ex. entrée 10/09,
        sortie 19/09 -> 9 jours facturés, du 10/09 au 18/09 inclus.
        Affiché explicitement dans les templates pour éviter la confusion
        entre "nombre de jours" et la date de sortie brute (signalé comme
        source de confusion)."""
        if not self.date_entree or self.nombre_jours <= 0:
            return None
        return self.date_entree + timedelta(days=self.nombre_jours - 1)

    # ⭐ Valeurs "effectives" — respectent le toggle actif/inactif de CE
    # séjour (assurance_principale_active/assurance2_active), sans jamais
    # effacer assurance_nom/assurance2_nom eux-mêmes (réactivable). Point de
    # vérité unique utilisé par le calcul de répartition, la détection du
    # groupe de paliers et le rappel EP — pour que les trois restent
    # toujours cohérents entre eux quand le caissier bascule un toggle.
    @property
    def est_assure_amu(self):
        if not self.assurance_principale_active:
            return False
        return bool(self.assurance_nom) and self.assurance_nom not in ('non_assure', 'Non assuré') \
            and float(self.taux_assurance or 0) > 0

    @property
    def taux_assurance_effectif(self):
        return float(self.taux_assurance or 0) if self.est_assure_amu else 0

    @property
    def a_cac(self):
        return self.assurance2_active and bool(self.assurance2_nom) and float(self.taux_assurance2 or 0) > 0

    @property
    def taux_assurance2_effectif(self):
        return float(self.taux_assurance2 or 0) if self.a_cac else 0


class SoinHospitalisation(db.Model):
    """Une ligne de soin (acte ou médicament) administrée à une date/heure
    donnée pendant un séjour. `date_fin_prestation` n'est renseigné que
    pour une tranche de palier "chambre" (période de plusieurs jours au
    même tarif) — NULL pour un acte/médicament ponctuel, dont la date
    unique suffit à le distinguer d'une même prestation un autre jour."""
    __tablename__ = 'soins_hospitalisation'
    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, nullable=False)
    structure_id = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'acte' | 'medicament'
    reference_id = db.Column(db.Integer)
    nom = db.Column(db.String(255), nullable=False)
    prix = db.Column(db.Numeric, default=0)
    pbr = db.Column(db.Numeric, default=0)
    quantite = db.Column(db.Integer, default=1)
    prise_en_charge_amu = db.Column(db.Boolean, default=True)
    prise_en_charge_cac = db.Column(db.Boolean, default=True)
    date_prestation = db.Column(db.Date, nullable=False)
    heure_prestation = db.Column(db.Time)
    date_fin_prestation = db.Column(db.Date)
    note = db.Column(db.Text)
    enregistre_par = db.Column(db.String(255))
    date_enregistrement = db.Column(db.DateTime, default=datetime.utcnow)
    statut = db.Column(db.String(20), default='en_cours')  # en_cours/facture

    # ⭐ Part médecin — porté depuis GHP (2026-09-30) : capturé ICI, au
    # moment du soin, pas à la facturation en fin de séjour (voir
    # services/part_medecin_service.py, déclenché à la conversion en
    # Vente via api_convertir_proforma).
    medecin_id = db.Column(db.Integer)
    medecin_nom = db.Column(db.String(255))

    @property
    def total(self):
        return float(self.prix or 0) * int(self.quantite or 0)


# ============================================================
# PBR COMPLÉMENTAIRE (CAC) — plafond propre à chaque compagnie
# ============================================================
# Contrairement à l'AMU (un seul PBR partagé par acte/produit, colonne
# `pbr` du catalogue Google Sheets), chaque compagnie complémentaire
# (SUNU, OLEA, GTA, FIDELIA...) a sa PROPRE base de remboursement sur un
# même acte — et pas sur tous les actes. D'où une vraie table de
# correspondance (acte/produit x compagnie) plutôt qu'une colonne de plus
# dans le catalogue. Voir calculer_repartition_assurance()
# (services/hospitalisation_service.py) et api_convertir_proforma()
# (app.py) pour son utilisation : absence d'entrée pour un (acte,
# compagnie) donné = comportement inchangé (reste après AMU, non
# plafonné), donc zéro régression tant que la table n'est pas remplie.
class PbrComplementaire(db.Model):
    __tablename__ = 'pbr_complementaires'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'acte' | 'produit'
    nom_acte = db.Column(db.String(255), nullable=False)
    compagnie = db.Column(db.String(150), nullable=False)  # = Patient.assurance2_nom
    # ⭐ Deux PBR possibles pour le même (acte, compagnie) — signalé : une
    # même compagnie applique parfois une autre base selon le contrat du
    # patient. pbr_1 = celui qu'on applique d'habitude (utilisé par
    # défaut) ; pbr_2 = l'alternatif, optionnel, choisissable EN DIRECT
    # depuis la vente (voir pbr_cac_variante sur Hospitalisation/
    # Proforma/Vente) si le premier ne correspond pas pour ce patient.
    # ⭐ Patron (2026-10-04, "Vérification de la logique de calcul des tarifs
    # actes") : "pour chaque acte et chaque assurance privée : tarif privé,
    # présence ou non d'un PBR, montant du PBR" — pbr_1 devient OPTIONNEL
    # (NULL = pas de PBR pour ce couple : la part privée se calcule sur le
    # tarif / le reste après AMU), et tarif_prive porte le tarif facturé au
    # patient de cette compagnie (NULL = prix de base du catalogue). Voir
    # services/tarification_service.py.
    pbr_1 = db.Column(db.Numeric)
    pbr_2 = db.Column(db.Numeric)
    tarif_prive = db.Column(db.Numeric)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ Prix "non assuré" d'un acte (patron, 2026-10-04 : "Patient non assuré :
# prix non assuré (ou prix AMU par défaut)") — le catalogue Google Sheets ne
# porte que prix (= prix AMU, prix de base) et pbr ; cette table Postgres
# dédiée (même motif que ClassificationActe/PbrComplementaire, clé = nom de
# l'acte) évite une colonne positionnelle de plus dans chaque feuille. Absent
# -> prix de base, zéro changement pour les actes non renseignés.
class PrixNonAssureActe(db.Model):
    __tablename__ = 'prix_non_assure_actes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    # ⭐ 'acte' | 'produit' (patron, 2026-10-04 : "tu feras de même pour la
    # pharmacie") — même table pour les deux catalogues, comme PbrComplementaire.
    type = db.Column(db.String(20), nullable=False, default='acte')
    nom_acte = db.Column(db.String(255), nullable=False)
    prix = db.Column(db.Numeric, nullable=False)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ⭐ Liste canonique des compagnies complémentaires (SUNU, OLEA, GTA...)
# d'UNE structure — évite qu'une même compagnie soit saisie sous deux
# orthographes différentes (ex. "SUNU" vs "SUNOU") à la fiche patient et
# à la page PBR complémentaires, ce qui romprait silencieusement le
# rapprochement (acte, compagnie) -> PBR. Alimentée automatiquement dès
# qu'un nom nouveau est saisi quelque part (voir
# upsert_compagnie_complementaire(), app.py) — même mécanisme déjà en
# place pour societes_assurance (société souscriptrice).
class CompagnieComplementaire(db.Model):
    __tablename__ = 'compagnies_complementaires'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# FACTURE AMU MENSUELLE (bordereau CNSS/INAM) — voir
# services/facturation_amu_service.py et utils/categories_amu_cnss.py.
# ============================================================

# ⭐ Quelle catégorie CNSS (une des 21 du formulaire officiel) relève un
# acte du catalogue — table Postgres dédiée (même motif que
# ClassificationActe/PbrComplementaire plus haut) : un acte non encore
# classé n'est PAS silencieusement rangé dans "Autres", il apparaît dans
# la section "Non classés" de l'écran de vérification tant qu'il n'a pas
# reçu une catégorie explicite ici.
class ClassificationAmuCnss(db.Model):
    __tablename__ = 'classification_amu_cnss'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom_acte = db.Column(db.String(255), nullable=False)
    categorie = db.Column(db.String(40), nullable=False)  # clé CATEGORIES_AMU_CNSS ou _INAM
    # ⭐ Une même structure peut vouloir classer un acte différemment selon
    # l'assureur (les 21 catégories CNSS et INAM ne se recouvrent pas
    # forcément) — 'cnss' par défaut pour rester compatible avec les
    # entrées déjà saisies avant l'ajout de l'AMU-INAM.
    type_amu = db.Column(db.String(20), nullable=False, default='cnss')  # 'cnss' | 'inam'
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ En-tête de la FACTURE AMU (N° CNSS, code prestataire...) — saisi une
# fois par structure, réutilisé à chaque impression mensuelle. Même motif
# que ParametrageTva (une ligne par structure_id, get_ou_creer()).
class ParametrageAmuCnss(db.Model):
    __tablename__ = 'parametrage_amu_cnss'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    numero_cnss = db.Column(db.String(50))
    code_prestataire = db.Column(db.String(50))
    statut_structure = db.Column(db.String(20))  # 'public' | 'prive' | 'confessionnel'
    niveau_soins = db.Column(db.String(5))  # '1' | '2' | '3'
    nom_banque = db.Column(db.String(150))
    numero_compte = db.Column(db.String(50))
    # ⭐ Sigle de la clinique — utilisé dans le numéro de facture recap AMU
    # (CNSS/TNS/INAM, voir FactureAmuMensuelle.numero_local +
    # formater_numero_facture_amu) : "N° 000000001/AMU/<sigle>/<année>".
    # Commun aux deux assureurs, comme le reste de ce paramétrage.
    sigle = db.Column(db.String(20))
    # ⭐ Dépôt EP/TPC par WhatsApp + numéro vert AMU (patron, 2026-10-01 :
    # "le numéro c'est 71383919 [...] ce numéro est valable pour l'envoi
    # des EP aussi [...] le numéro vert c'est 8323 avec possibilité de
    # modifier ça") — éditables (page Paramétrage AMU), jamais codés en dur
    # dans les templates d'impression EP/TPC.
    whatsapp_depot = db.Column(db.String(20), default='71383919')
    numero_vert = db.Column(db.String(20), default='8323')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_ou_creer(cls, structure_id):
        param = cls.query.filter_by(structure_id=structure_id).first()
        if not param:
            param = cls(structure_id=structure_id, whatsapp_depot='71383919', numero_vert='8323')
            db.session.add(param)
            db.session.commit()
        return param


# ⭐ Mémorise, par structure, à quelle catégorie officielle de salle AMU
# (voir CATEGORIES_SALLE_AMU, utils/grille_amu_hospitalisation.py) un acte
# "chambre" du catalogue correspond — PAS une page de configuration
# séparée : rempli automatiquement la première fois qu'une chambre donnée
# est choisie (voir api_definir_chambre_tarif_hospitalisation /
# api_sortie_hospitalisation, app.py), pré-remplit ensuite le choix pour
# toutes les prochaines fois que ce même nom d'acte est utilisé. Sert à
# calculer le PBR par palier (P160) depuis la grille officielle au lieu de
# deviner par le nom dans le catalogue Sheets de la structure.
class CorrespondanceSalleAmu(db.Model):
    __tablename__ = 'correspondance_salle_amu'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom_acte = db.Column(db.String(255), nullable=False)
    categorie_salle = db.Column(db.String(40), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def memoriser(cls, structure_id, nom_acte, categorie_salle):
        if not nom_acte or not categorie_salle:
            return
        entree = cls.query.filter_by(structure_id=structure_id, nom_acte=nom_acte).first()
        if not entree:
            entree = cls(structure_id=structure_id, nom_acte=nom_acte)
            db.session.add(entree)
        entree.categorie_salle = categorie_salle

    @classmethod
    def connues_pour(cls, structure_id):
        """{nom_acte: categorie_salle} pour toute la structure — utilisé par
        /api/actes pour pré-remplir le menu de chaque résultat de recherche."""
        return {
            e.nom_acte: e.categorie_salle
            for e in cls.query.filter_by(structure_id=structure_id).all()
        }


# ⭐ Champs propres au formulaire INAM ("Régime", "Type") — les champs déjà
# communs aux deux assureurs (code prestataire, statut, banque, compte)
# restent sur ParametrageAmuCnss et sont réutilisés tels quels côté INAM,
# pas de ressaisie. Même motif get_ou_creer() que les autres paramétrages.
class ParametrageAmuInam(db.Model):
    __tablename__ = 'parametrage_amu_inam'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    regime = db.Column(db.String(20))  # 'ramo' | 'school_amu' | 'wezou' | 'autres'
    type_etablissement = db.Column(db.String(100))
    # ⭐ Même principe que ParametrageAmuCnss.whatsapp_depot/numero_vert —
    # patron : "leur numéro d'envoi des EP et TPC aussi est là, peux-tu
    # permettre qu'on ajoute cela après [...] numéro vert c'est 8222".
    # whatsapp_depot laissé vide par défaut : pas encore communiqué,
    # éditable dès qu'il le sera.
    whatsapp_depot = db.Column(db.String(20))
    numero_vert = db.Column(db.String(20), default='8222')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_ou_creer(cls, structure_id):
        param = cls.query.filter_by(structure_id=structure_id).first()
        if not param:
            param = cls(structure_id=structure_id, numero_vert='8222')
            db.session.add(param)
            db.session.commit()
        return param


# ⭐ Un brouillon éditable par (structure, type d'AMU, mois) — régénérable
# depuis les ventes à tout moment (écrase les lignes), ou corrigé à la
# main et enregistré tel quel. "deposee" est un simple marqueur de
# traçabilité (date de dépôt physique à la CNSS/l'INAM), pas un verrou :
# on peut toujours rouvrir/réimprimer après coup.
class FactureAmuMensuelle(db.Model):
    __tablename__ = 'factures_amu_mensuelles'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    type_amu = db.Column(db.String(20), nullable=False, default='cnss')  # 'cnss' | 'inam'
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)  # 1-12
    numero_local = db.Column(db.Integer)  # numérotation locale — voir prochain_numero_local() ; "N° facture" côté INAM
    lignes = db.Column(db.JSON)  # [{categorie, nombre_feuilles, montant}, ...]
    # ⭐ 'cloturee' ajouté — patron : "cloturer une facture [...] apres
    # cette étape aucune modification n'est plus possible". Contrairement
    # à 'deposee' (simple marqueur de traçabilité, jamais un verrou),
    # 'cloturee' bloque réellement : régénération, enregistrement manuel,
    # numéro de facture, nouveau dépôt. Voir api_cloturer_facture_amu.
    statut = db.Column(db.String(20), default='brouillon')  # 'brouillon' | 'deposee' | 'cloturee'
    date_depot = db.Column(db.DateTime)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# VENTE EN ATTENTE — service admission sépare de la caisse (patron :
# "il ya dans certaines structures des services séparés le patient se
# fait enregistrer au service admission... il part à la caisse... la
# caisse fait sortir le reçu"). L'admission constitue le panier SANS
# choisir de patient (contrairement à Proforma, qui en exige un dès la
# création) ; la caisse choisit le patient au moment de finaliser —
# voir api_creer_vente_en_attente/api_finaliser_vente_en_attente (app.py).
# ============================================================
class VenteEnAttente(db.Model):
    __tablename__ = 'ventes_en_attente'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    numero_local = db.Column(db.Integer)  # code communiqué au patient — voir prochain_numero_local()
    type = db.Column(db.String(20), nullable=False)  # 'actes' | 'pharmacie'
    nom_patient = db.Column(db.String(255))  # saisi librement par l'admission (pas de sélection formelle) — patron : "doit contenir le nom du patient pour ne pas qu'on souffre"
    patient_id = db.Column(db.Integer)  # rempli seulement si un vrai patient était déjà sélectionné à l'admission (comme avant) — permet de sauter la resélection à la finalisation
    articles = db.Column(db.JSON)  # panier tel que soumis par l'admission (nom/prix/pbr/quantite/prise_en_charge_amu/cac)
    sous_total = db.Column(db.Numeric, default=0)  # informatif seulement — le vrai calcul se refait à la finalisation
    statut = db.Column(db.String(20), default='en_attente')  # 'en_attente' | 'finalisee' | 'annulee'
    vente_id = db.Column(db.Integer)  # rempli une fois finalisée — lien vers la Vente réellement créée
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finalise_par = db.Column(db.String(255))
    finalise_at = db.Column(db.DateTime)
    annule_par = db.Column(db.String(255))
    annule_at = db.Column(db.DateTime)
    motif_annulation = db.Column(db.Text)


# ============================================================
# LABORATOIRE / RADIOLOGIE — circuit de demandes + ristournes
# ============================================================
# ⭐ Quel acte du catalogue relève de la biologie (laborantin) ou de
# l'imagerie (radiologue) — table Postgres plutôt qu'une colonne de plus
# sur le catalogue Sheets (même choix que PbrComplementaire cette
# session) : évite de toucher au schéma des feuilles struct_<id>_actes,
# et une entrée absente = acte "standard" (ni labo ni radio), zéro
# régression. Voir /classification-actes et charger_classification_actes()
# (services/laboratoire_service.py).
class ClassificationActe(db.Model):
    __tablename__ = 'classification_actes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom_acte = db.Column(db.String(255), nullable=False)
    type_prestation = db.Column(db.String(20), nullable=False)  # 'analyse' | 'examen'
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# ⭐ RECETTES PAR SERVICE (patron, 2026-09-30) : "à la fin d'année on doit
# [évaluer] les efforts de chaque service... pour décider de ristourne ou
# pas". Réutilise la liste de services déjà réelle et déjà peuplée
# (ServiceHospitalisation, Service > Chambre > Lit) comme référentiel
# unique plutôt que d'en créer une deuxième — voir
# services/service_acte_service.py pour la résolution à 3 niveaux (choix
# explicite à la vente > classification manuelle ci-dessous > détection
# automatique depuis le code de nomenclature dans le nom de l'acte).
# ============================================================
class ParametrageService(db.Model):
    """Active/désactive, pour CETTE structure, le sélecteur "Service" au
    moment de la vente — patron : "chaque structure décide de le faire
    ainsi ou pas, parce que certains centres n'ont pas besoin de ça".
    Désactivé par défaut ; la classification manuelle et la détection
    automatique restent actives dans tous les cas, même désactivé."""
    __tablename__ = 'parametrage_service'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    choix_service_actif = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_ou_creer(cls, structure_id):
        param = cls.query.filter_by(structure_id=structure_id).first()
        if not param:
            param = cls(structure_id=structure_id)
            db.session.add(param)
            db.session.commit()
        return param


class ClassificationServiceActe(db.Model):
    """Service attribué manuellement à un acte précis — même forme que
    ClassificationActe ci-dessus (structure_id + nom_acte, upsert) : pour
    les cas que la détection automatique ne peut pas trancher seule (ex.
    un acte chirurgical sur l'appareil génital doit aller en
    Gynéco-Obstétrique, pas en Chirurgie générale — indiscernable depuis
    le seul nom de l'acte)."""
    __tablename__ = 'classification_service_actes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom_acte = db.Column(db.String(255), nullable=False)
    service_id = db.Column(db.Integer, nullable=False)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RecetteService(db.Model):
    """Une ligne facturée attribuée à un service — créée automatiquement à
    la vente (même principe que PrestationMedecin). Rapport de GESTION
    pour comparer l'activité des services (décision de ristourne en fin
    d'année) : ne touche jamais aux écritures comptables SYSCOHADA
    elles-mêmes, qui restent scopées par compte, pas par service.
    service_id/service_nom restent NULL (service_nom='Non classé') quand
    aucun des 3 niveaux de résolution n'a pu trancher — jamais de ligne
    silencieusement absente du rapport."""
    __tablename__ = 'recettes_service'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    service_id = db.Column(db.Integer)
    service_nom = db.Column(db.String(255))  # dénormalisé, figé au moment de la vente
    vente_id = db.Column(db.Integer)
    nom_acte = db.Column(db.String(255), nullable=False)
    type_source = db.Column(db.String(20))  # 'acte' | 'produit' | 'hospitalisation'
    origine = db.Column(db.String(20))  # 'choix_manuel' | 'classification' | 'auto' | 'non_classe'
    prix = db.Column(db.Numeric, nullable=False)
    quantite = db.Column(db.Integer, default=1)
    montant = db.Column(db.Numeric, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ Médecin EXTÉRIEUR à la clinique qui envoie un patient réaliser une
# analyse/un examen — a droit à une ristourne sur le prix de l'acte, à un
# taux propre à lui (voir taux_ristourne : mémorisé, proposé par défaut la
# prochaine fois, modifiable au cas par cas — patron : "si on saisit un
# taux pour la première fois que ce taux se propose pour les prochaines
# fois"). Distinct des Medecin internes (services/medecins) qui, eux,
# consultent à la clinique et n'ouvrent jamais droit à ristourne.
class PrescripteurExterne(db.Model):
    __tablename__ = 'prescripteurs_externes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(200), nullable=False)
    telephone = db.Column(db.String(50))  # ⭐ pour l'envoi du reçu par WhatsApp
    email = db.Column(db.String(150))
    specialite = db.Column(db.String(150))
    taux_ristourne = db.Column(db.Numeric)  # % — dernier taux saisi, proposé par défaut
    actif = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ Un patient signalé par la secrétaire comme venu d'un prescripteur
# EXTERNE pour réaliser une analyse et/ou un examen — le patient lui-même
# reste enregistré normalement (Patient, inchangé) ; cette fiche est
# juste le lien vers son prescripteur, posé une fois depuis l'onglet
# "Patients externes" (patron : "les secrétaires depuis un onglet
# constituent la liste des patients externes tout en leur assignant
# obligatoirement un prescripteur"). biologie/imagerie indiquent ce que
# couvre CETTE référence (sert à filtrer quelles DemandeExamen comptent
# pour la ristourne de ce prescripteur — voir calculer_ristournes()).
class PatientExterne(db.Model):
    __tablename__ = 'patients_externes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255))
    prescripteur_id = db.Column(db.Integer, nullable=False)
    biologie = db.Column(db.Boolean, default=False)
    imagerie = db.Column(db.Boolean, default=False)
    actif = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ Le cœur du circuit : une ligne par acte "analyse"/"examen" réglé
# (même partiellement) — créée AUTOMATIQUEMENT à l'encaissement (vente
# directe ou conversion de proforma), jamais saisie à la main. Oriente
# vers le Laborantin ou le Radiologue selon type_prestation ; si le
# patient a une fiche PatientExterne active, patient_externe_id est
# renseigné et cette ligne compte dans la ristourne de son prescripteur.
class DemandeExamen(db.Model):
    __tablename__ = 'demandes_examens'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255))
    type_prestation = db.Column(db.String(20), nullable=False)  # 'analyse' | 'examen'
    acte_nom = db.Column(db.String(255), nullable=False)
    quantite = db.Column(db.Integer, default=1)
    prix = db.Column(db.Numeric, default=0)
    vente_id = db.Column(db.Integer)  # traçabilité — vente d'origine
    patient_externe_id = db.Column(db.Integer)  # NULL = patient interne, pas de ristourne
    # ⭐ Renseigné dès que cette ligne a été incluse dans une clôture de
    # ristourne (voir PeriodeRistourne) — évite qu'une même DemandeExamen
    # soit comptée deux fois si on clôture le même prescripteur plusieurs
    # fois. NULL = pas encore clôturée, entre dans le calcul de la
    # prochaine clôture pour ce prescripteur.
    periode_ristourne_id = db.Column(db.Integer)
    # ⭐ Statut du RÈGLEMENT de cet acte précis, au moment de la création
    # de la demande — pas rafraîchi ensuite (un paiement complété plus
    # tard nécessite de le rouvrir/le resservir, pas de le recalculer en
    # silence). 'motif' expliqué par la caissière si partiel/impayé, pour
    # que le labo/radio décide de servir ou non (patron : "afin de
    # décider s'il faut le servir ou pas").
    statut_paiement = db.Column(db.String(20), default='paye')  # 'paye' | 'partiel' | 'impaye'
    motif = db.Column(db.Text)
    statut = db.Column(db.String(20), default='en_attente')  # 'en_attente' | 'realisee' | 'annulee'
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ⭐ Origine miroir (synchronisation depuis gestion_patients — voir
    # /api/resultats-examens/sync-externe) : NULL pour toute demande
    # 100% native GHP. Même principe que ProtocoleMedical.source_app —
    # index unique partiel sur (structure_id, source_app, source_model,
    # source_id) pour qu'un retry du rattrapage ne crée jamais de doublon.
    source_app = db.Column(db.String(30))       # 'gestion_patients'
    source_model = db.Column(db.String(30))     # 'AnalyseDemande'
    source_id = db.Column(db.Integer)
    source_synced_at = db.Column(db.DateTime)


# ⭐ Entente Préalable AMU, remplie depuis l'appli puis imprimée par-dessus
# le PDF officiel (jamais recréé — voir utils/remplissage_pdf_amu.py) —
# patron : "permettre qu'on remplisse une entente préalable directement là
# et imprimer". Workflow à 2 temps : la secrétaire/caisse saisit
# (statut='en_attente'), un médecin doit vérifier et approuver avant que
# l'impression ne soit autorisée — jamais l'inverse.
class DemandeEntentePrealable(db.Model):
    __tablename__ = 'demandes_entente_prealable'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    medecin_id = db.Column(db.Integer, nullable=False)
    # 'amu_cnss' | 'amu_inam' — CHOIX EXPLICITE dans le formulaire (patron :
    # "on devrait avoir la possibilité de choisir EP inam ou cnss"), plus
    # seulement déduit du patient — pré-rempli depuis patient.type_assurance
    # mais modifiable. 'amu_tns' réutilise le gabarit 'amu_cnss' (même
    # administration CNSS, voir utils/remplissage_pdf_amu.py) : jamais
    # stocké tel quel ici.
    type_amu = db.Column(db.String(20), nullable=False)
    # ⭐ La fiche officielle contient 3 tableaux indépendants (Actes,
    # Médicaments/Produits, Hospitalisation) — patron : "il peut arriver
    # qu'on demande les trois en même temps". Chaque "inclure_*" active son
    # tableau ; au moins un des trois doit être vrai (voir validation
    # api_amu_ep_creer).
    inclure_actes = db.Column(db.Boolean, default=False)
    inclure_produits = db.Column(db.Boolean, default=False)
    inclure_hospitalisation = db.Column(db.Boolean, default=False)
    # Lignes "motif" : [{type: 'acte'|'produit', nom, motif, saisie_manuelle}]
    # — JSON car longueur variable (3-4 lignes selon le gabarit) et ne sert
    # qu'à reconstituer l'impression, jamais interrogé en SQL. 'motif' est
    # la colonne "Motif ou indication" à côté de l'acte/produit sur la
    # fiche — distincte du nom de l'acte lui-même.
    lignes_motif = db.Column(db.JSON)
    numero_feuille_soins = db.Column(db.String(50))  # INAM uniquement
    date_prescription = db.Column(db.Date, nullable=False)
    # ⭐ Tableau "Hospitalisation" de la fiche — rempli seulement si
    # inclure_hospitalisation=True. categorie_salle : 'cabine_ventilee' (la
    # case "Oui" cochée) ou 'autre' (case "Non" cochée + precision sur les
    # pointillés "Si non, catégorie attribuée (préciser) : ...").
    hospit_date_admission = db.Column(db.Date)
    hospit_motif = db.Column(db.Text)
    hospit_categorie_salle = db.Column(db.String(20))  # 'cabine_ventilee' | 'autre'
    hospit_categorie_autre_precision = db.Column(db.String(255))
    hospit_duree_sejour = db.Column(db.String(100))
    statut = db.Column(db.String(20), default='en_attente')  # en_attente | approuvee | refusee
    cree_par_id = db.Column(db.Integer)
    cree_par_nom = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approuve_par_id = db.Column(db.Integer)
    approuve_par_nom = db.Column(db.String(255))
    approuve_le = db.Column(db.DateTime)
    motif_refus = db.Column(db.String(500))
    imprime_le = db.Column(db.DateTime)  # dernière impression, informatif
    # ⭐ Lien EP <-> Hospitalisation (patron, 2026-10-01 : "on va faire une
    # liaison entre hospitalisation [et l'EP]") — posé automatiquement dans
    # un sens ou dans l'autre selon lequel des deux est créé en premier
    # (voir page_amu_entente_prealable/api_creer_hospitalisation dans
    # app.py), jamais par saisie manuelle. Pas de contrainte FK (comme
    # patient_id/medecin_id ci-dessus, même style dans tout ce modèle) —
    # sert à retrouver hospit.date_entree/date_sortie pour la synchro des
    # dates et le lien vers le billet d'hospitalisation.
    hospitalisation_id = db.Column(db.Integer)
    # ⭐ "Pré-accord" (fait à l'entrée, durée probable) -> "demande
    # définitive" (faite à la sortie, durée réelle en nuitées) — patron :
    # "ces demandes actuellement correspondent au pré-accord [...] à la
    # sortie on fait une demande définitive". Non-null = la durée réelle a
    # été calculée et écrite dans hospit_duree_sejour (remplace la durée
    # probable). Pas de nouveau cycle d'approbation médecin pour ce passage
    # pré-accord -> définitive, seulement pour inclure_hospitalisation=True.
    definitive_le = db.Column(db.DateTime)


# ⭐⭐ TPC (Traitement des Pathologies Chroniques) — même logique que l'EP
# ci-dessus (patron, 2026-10-01 : "attaque les TPC, même logique que les
# EP") : rempli par la secrétaire/caisse, vérifié et approuvé par un
# médecin avant impression, jamais de modification des fiches PDF
# originales (overlay uniquement, voir utils/remplissage_pdf_tpc.py).
#
# Contrairement à l'EP (1 seule étape), le TPC a un cycle de vie en 3
# temps sur les fiches CNSS/TNS (2 sur INAM) :
#   1. 'identification' — première demande, avec examen clinique complet,
#      ALD(s) + code(s), traitement initial. C'est le "dossier" racine.
#   2. 'renouvellement' — le patient revient, on cherche son dossier
#      d'identification, on recopie son traitement (modifiable) et on
#      réimprime avec une nouvelle date — PAS de nouveau cycle
#      d'approbation obligatoire côté métier mais on garde le même
#      workflow de validation médecin pour rester cohérent avec l'EP.
#      INAM n'a pas de fiche dédiée : son renouvellement réutilise la
#      fiche d'identification elle-même (patron : "leur renouvellement
#      peut se faire sur la fiche d'identification tpc").
#   3. 'modification' (CNSS/TNS) / 'rectification' (INAM) — changement de
#      traitement en cours de route (ajustement posologie, changement ou
#      ajout de médicament) : motif obligatoire, ne touche PAS
#      l'identité patient/médecin sur la fiche officielle (même si rien
#      n'empêche de les corriger dans l'appli, patron : "possibilité de
#      modifier les informations du patient et du prescripteur pas de
#      souci").
# Chaque renouvellement/modification est une NOUVELLE ligne, liée au
# dossier d'origine par `dossier_id` (le premier 'identification' a
# dossier_id = son propre id une fois créé) — ça donne l'historique
# complet par simple requête `dossier_id=X`, sans jamais écraser les
# demandes précédentes (patron : "on doit voir l'historique des
# renouvellements/modifications aussi").
class DemandeTpc(db.Model):
    __tablename__ = 'demandes_tpc'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    medecin_id = db.Column(db.Integer, nullable=False)
    type_amu = db.Column(db.String(20), nullable=False)  # 'amu_cnss' | 'amu_tns' | 'amu_inam'
    type_demande = db.Column(db.String(20), nullable=False)  # identification | renouvellement | modification | rectification
    # ⭐ Pointe vers la ligne 'identification' racine du dossier (vers
    # elle-même pour l'identification elle-même) — jamais de contrainte FK
    # (même style que patient_id/medecin_id partout ailleurs dans ce
    # fichier), posé en code à la création.
    dossier_id = db.Column(db.Integer)

    # ⭐ I. Identité du patient — ville de résidence mémorisée pour
    # suggestion rapide la prochaine fois (voir LieuResidenceMemorise),
    # jamais un champ figé : certains patients changent de ville. sexe et
    # profession n'existent pas sur Patient (non applicable à la majorité
    # des autres modules) : saisis ici, propres au dossier TPC. L'âge n'est
    # pas stocké, calculé à l'impression depuis patient.date_naissance.
    ville_residence = db.Column(db.String(150))
    sexe = db.Column(db.String(20))
    profession = db.Column(db.String(150))

    # ⭐ II. ALD(s) + code(s) — jusqu'à 4 lignes {affection, code_ald}.
    # Codes en texte libre tant que le patron n'a pas fourni le fichier
    # référentiel des codes ALD ("je vais préparer ce fichier [...] il
    # faut le prévoir") — ce champ reste compatible avec une liste
    # déroulante le jour où ce référentiel est chargé, sans migration.
    affections_ald = db.Column(db.JSON)

    # ⭐ III. Examen physique (identification uniquement)
    poids = db.Column(db.String(20))
    taille = db.Column(db.String(20))
    imc = db.Column(db.String(20))
    ta_bg = db.Column(db.String(20))
    ta_bd = db.Column(db.String(20))
    etat_general = db.Column(db.String(255))
    resume_examen_physique = db.Column(db.Text)
    autres_examen = db.Column(db.Text)

    # ⭐ IV. Examens paracliniques — [{examen, date, resultat}], choisis
    # parmi les résultats déjà enregistrés du patient (DemandeExamen /
    # ResultatExamen) ou saisis à la main si l'examen n'y est pas.
    examens_paracliniques = db.Column(db.JSON)

    # ⭐ V. Traitements — [{code_ald, medicament, forme_dosage, posologie,
    # duree}]. `medicament` vient soit du tableau tarifaire de la
    # structure, soit de MedicamentTpcMemorise (médicaments hors tableau
    # déjà prescrits une fois en TPC, proposés ensuite en saisie rapide —
    # patron : "souvent c'est des médicaments qui ne sont pas dans la
    # base [...] qu'on le propose la prochaine fois").
    traitements = db.Column(db.JSON)

    # ⭐ VI. Comorbidités — jusqu'à 3 lignes libres + date du prochain RDV.
    comorbidites = db.Column(db.JSON)
    date_prochain_rdv = db.Column(db.Date)

    # ⭐ Renouvellement : "Traitement à renouveler : OUI/NON"
    traitement_a_renouveler = db.Column(db.Boolean)

    # ⭐ Modification (CNSS/TNS) / Rectification (INAM) — motif obligatoire
    # (patron : "quand il s'agit d'une modification il faut forcément le
    # motif de modification"), mémorisé pour suggestion rapide la
    # prochaine fois comme la ville de résidence et les médicaments.
    motif_modification = db.Column(db.Text)
    resultats_examens_effectues = db.Column(db.Text)  # case "Résultats des examens effectués" (modif/rectif)
    # ⭐ "N° Ancien TPC" (fiche de rectification INAM uniquement) — référence
    # LIBRE d'un TPC déjà identifié par le passé, potentiellement hors de
    # l'application (l'identification TPC INAM n'est pas encore implémentée,
    # voir utils/remplissage_pdf_tpc.py) : jamais un lien vers un
    # DemandeTpc.id comme dossier_id ci-dessus, une simple case texte de la
    # fiche officielle.
    numero_ancien_tpc = db.Column(db.String(100))

    date_prescription = db.Column(db.Date, nullable=False)
    statut = db.Column(db.String(20), default='en_attente')  # en_attente | approuvee | refusee
    cree_par_id = db.Column(db.Integer)
    cree_par_nom = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approuve_par_id = db.Column(db.Integer)
    approuve_par_nom = db.Column(db.String(255))
    approuve_le = db.Column(db.DateTime)
    motif_refus = db.Column(db.String(500))
    imprime_le = db.Column(db.DateTime)


# ⭐ Mémorisation de valeurs saisies à la main pour suggestion rapide la
# prochaine fois — même principe que CorrespondanceSalleAmu.memoriser()
# plus haut dans ce fichier, appliqué ici aux médicaments TPC hors
# tableau tarifaire et aux lieux de résidence (patron, 2026-10-01 : voir
# DemandeTpc ci-dessus pour le contexte complet de chaque usage).
class MedicamentTpcMemorise(db.Model):
    __tablename__ = 'medicaments_tpc_memorises'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def memoriser(structure_id, nom):
        nom = (nom or '').strip()
        if not nom:
            return
        existe = MedicamentTpcMemorise.query.filter_by(structure_id=structure_id).filter(
            db.func.lower(MedicamentTpcMemorise.nom) == nom.lower()
        ).first()
        if not existe:
            db.session.add(MedicamentTpcMemorise(structure_id=structure_id, nom=nom))

    @staticmethod
    def connues_pour(structure_id):
        return [m.nom for m in MedicamentTpcMemorise.query.filter_by(structure_id=structure_id).order_by(MedicamentTpcMemorise.nom).all()]


class LieuResidenceMemorise(db.Model):
    __tablename__ = 'lieux_residence_memorises'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    valeur = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def memoriser(structure_id, valeur):
        valeur = (valeur or '').strip()
        if not valeur:
            return
        existe = LieuResidenceMemorise.query.filter_by(structure_id=structure_id).filter(
            db.func.lower(LieuResidenceMemorise.valeur) == valeur.lower()
        ).first()
        if not existe:
            db.session.add(LieuResidenceMemorise(structure_id=structure_id, valeur=valeur))

    @staticmethod
    def connues_pour(structure_id):
        return [l.valeur for l in LieuResidenceMemorise.query.filter_by(structure_id=structure_id).order_by(LieuResidenceMemorise.valeur).all()]


# ⭐ Modèle de résultat (Word/Excel) réutilisable — le laborantin/radiologue
# le télécharge, le complète sur son poste, puis renvoie le résultat final
# via ResultatExamen.fichier_data ci-dessous. Stocké EN BASE (bytea), pas
# sur le disque du serveur : l'appli tourne sur Render, dont le disque
# n'est pas garanti persister entre redéploiements — un fichier local
# aurait pu disparaître silencieusement au prochain déploiement.
class ModeleResultat(db.Model):
    __tablename__ = 'modeles_resultats'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    type_prestation = db.Column(db.String(20), nullable=False)  # 'analyse' | 'examen'
    nom = db.Column(db.String(200), nullable=False)
    fichier_nom = db.Column(db.String(255))
    fichier_mime = db.Column(db.String(100))
    fichier_data = db.Column(db.LargeBinary)
    # ⭐ Contenu rédigeable directement dans l'appli (éditeur en ligne) —
    # alternative au fichier Word/Excel importé. patron : "est-ce possible
    # que les modèles... qu'on puisse directement les ouvrir dans la base,
    # les modifier et enregistrer en PDF ? Tout se fera dans la base". NULL
    # pour un modèle resté fichier (jamais retapé) — repli explicite.
    contenu_html = db.Column(db.Text)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ⭐ Origine miroir (voir DemandeExamen.source_app ci-dessus)
    source_app = db.Column(db.String(30))
    source_model = db.Column(db.String(30))
    source_id = db.Column(db.Integer)
    source_synced_at = db.Column(db.DateTime)


# ⭐ Le résultat final d'une DemandeExamen réalisée — un fichier (PDF de
# préférence, Word/Excel accepté aussi) + le nom de celui qui interprète
# (biologiste ou radiologue), imprimé sur le résultat quel que soit qui
# déclenche l'impression ensuite (patron : "peu importe celui qui va
# imprimer le résultat que le nom du radiologue et/ou de l'interpréteur
# soit sur le résultat"). Même stockage bytea que ModeleResultat.
class ResultatExamen(db.Model):
    __tablename__ = 'resultats_examens'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    demande_id = db.Column(db.Integer, nullable=False)
    fichier_nom = db.Column(db.String(255))
    fichier_mime = db.Column(db.String(100))
    # ⭐ NULL désormais possible : un résultat peut être rédigé directement
    # dans l'éditeur en ligne (voir contenu_html ci-dessous) au lieu d'être
    # importé — dans ce cas fichier_data/nom/mime restent NULL. L'un des
    # deux (fichier_data OU contenu_html) est toujours présent, vérifié
    # côté route (api_enregistrer_resultat, app.py), jamais les deux vides.
    fichier_data = db.Column(db.LargeBinary)
    # ⭐ Résultat rédigé directement dans l'appli (éditeur en ligne) —
    # remplace le détour actuel par Word/Excel + conversion PDF manuelle.
    # Imprimé en flux normal (resultat_imprimer.html), jamais dans un
    # cadre <iframe> isolé — ce qui garantit une pagination correcte à
    # l'impression, contrairement à un PDF importé affiché dans un iframe.
    contenu_html = db.Column(db.Text)
    modele_utilise_id = db.Column(db.Integer)  # traçabilité — modèle de départ, si utilisé
    nom_interprete = db.Column(db.String(200), nullable=False)  # biologiste (analyse) / radiologue (examen)
    # ⭐ Signature électronique — patron : "on met Le Laboratoire et on met
    # le titre de celui qui signe avec son nom" / "on met Le Radiologue...
    # dès qu'on sélectionne son nom sa signature s'appose s'il y en a".
    # titre_interprete et signature_data/mime sont une COPIE figée
    # (snapshot) de SignatureIntervenant au moment de la saisie — jamais
    # une clé étrangère vive : si la signature enregistrée de la personne
    # change plus tard (nouvelle photo, titre corrigé...), les résultats
    # déjà imprimés/signés dans le passé ne doivent JAMAIS changer
    # rétroactivement (même principe que PeriodeRistourne.taux_applique
    # figé au calcul). NULL si saisie libre (nom tapé à la main, aucune
    # signature dans le registre pour cette personne) — repli explicite,
    # zéro régression pour un nom non encore enregistré.
    signature_intervenant_id = db.Column(db.Integer)  # traçabilité seulement, jamais relu pour l'affichage
    titre_interprete = db.Column(db.String(100))
    signature_data = db.Column(db.LargeBinary)
    signature_mime = db.Column(db.String(100))
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ⭐ Origine miroir (voir DemandeExamen.source_app ci-dessus)
    source_app = db.Column(db.String(30))
    source_model = db.Column(db.String(30))
    source_id = db.Column(db.Integer)
    source_synced_at = db.Column(db.DateTime)


# ⭐ Registre des signatures électroniques pré-enregistrées — patron :
# "chaque intervenant préenregistre sa ou ses signatures dans
# paramétrage... parce que les résultats, les saisir directement on ne
# peut pas imprimer signer avant de scanner et envoyer". Une signature
# saisie UNE fois (photo/scan d'une vraie signature sur papier blanc)
# s'appose ensuite automatiquement sur chaque document — voir
# ResultatExamen.signature_data pour comment elle est figée à l'usage.
# 'filiere' distingue les registres (analyse=biologistes, examen=
# radiologues) ; conçu pour rester extensible à d'autres contextes plus
# tard (ex. 'facture') sans changement de schéma.
class SignatureIntervenant(db.Model):
    __tablename__ = 'signatures_intervenants'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    filiere = db.Column(db.String(20), nullable=False)  # 'analyse' | 'examen' | 'prescripteur'
    nom = db.Column(db.String(200), nullable=False)
    titre = db.Column(db.String(100))  # un des 4 titres labo ; vide/« Radiologue » pour la radio
    # ⭐ filière 'prescripteur' (patron, 2026-10-06 : "les signatures des
    # prescripteurs s'apposent sur les demandes d'EP et tous les TPC") :
    # signature rattachée à un médecin de la structure (Medecin.id) — relue
    # à l'impression de l'EP / du TPC dont il est le prescripteur.
    medecin_id = db.Column(db.Integer)
    signature_data = db.Column(db.LargeBinary, nullable=False)
    signature_mime = db.Column(db.String(100))
    actif = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ Code d'accès du portail patient (voir /portail-patient, app.py) — un
# code actif par patient, régénérable à tout moment par le personnel
# (régénérer invalide l'ancien). Table séparée plutôt qu'un champ sur
# Patient : fonctionnalité optionnelle, facile à ignorer/retirer sans
# toucher au modèle Patient central. Vérifié en plus du numéro de
# téléphone du patient (2 facteurs) à l'entrée du portail.
class AccesPortailPatient(db.Model):
    __tablename__ = 'acces_portail_patients'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    patient_id = db.Column(db.Integer, nullable=False)
    code_acces = db.Column(db.String(20), nullable=False, unique=True)
    # ⭐ Code rapide (4-6 chiffres, choisi par le patient lui-même une fois
    # connecté au moins une fois avec téléphone+code_acces) — patron :
    # "le patient puisse mettre son code de téléphone mot de passe ou
    # empreinte ou face id pour y accéder ... pour la première fois c'est
    # avec numéro téléphone et code d'accès". Stocké haché (hash_password,
    # même convention que les mots de passe du personnel) — jamais en
    # clair. Le code_acces d'origine (donné par la clinique) reste
    # valable indéfiniment : ce PIN est un raccourci, pas un remplacement.
    # "Empreinte/Face ID" n'est pas une biométrie traitée côté serveur :
    # champ <input type="password"> avec autocomplete="current-password"
    # dans un <form> → le téléphone propose de MÉMORISER ce PIN dans son
    # trousseau (Face ID/empreinte du téléphone déverrouille le
    # trousseau), exactement comme pour n'importe quel site — aucune
    # donnée biométrique ne transite jamais par ce serveur.
    pin_hash = db.Column(db.String(255))
    pin_defini_le = db.Column(db.DateTime)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ Une clôture de ristourne pour UN prescripteur externe sur UNE
# période — circuit à 3 étapes demandé par le patron :
#   1. 'calculee'  : secrétaire/caissière calcule (taux × prix des actes
#      DemandeExamen non encore clôturées de ce prescripteur).
#   2. 'validee'   : admin vérifie et valide.
#   3. 'payee'     : le paiement est réellement enregistré (Mobile Money
#      avec référence+date obligatoires, ou espèces avec date) — un reçu
#      devient alors imprimable et envoyable par WhatsApp au médecin.
# taux_applique/base_calcul sont un INSTANTANÉ au moment du calcul (le
# taux du prescripteur peut changer plus tard sans jamais modifier une
# clôture déjà calculée).
class PeriodeRistourne(db.Model):
    __tablename__ = 'periodes_ristournes'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    prescripteur_id = db.Column(db.Integer, nullable=False)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    taux_applique = db.Column(db.Numeric, nullable=False)
    base_calcul = db.Column(db.Numeric, default=0)       # somme des prix des actes inclus
    montant_ristourne = db.Column(db.Numeric, default=0)  # base_calcul * taux_applique / 100
    nb_actes = db.Column(db.Integer, default=0)
    statut = db.Column(db.String(20), default='calculee')  # 'calculee' | 'validee' | 'payee'
    calculee_par = db.Column(db.String(255))
    calculee_le = db.Column(db.DateTime, default=datetime.utcnow)
    validee_par = db.Column(db.String(255))
    validee_le = db.Column(db.DateTime)
    # ⭐ 'especes' | 'mobile_money' — si mobile_money, operateur (Tmoney,
    # Moov_money...) et reference obligatoires ; si especes, seule la
    # date compte (voir garde-fou api_payer_ristourne, app.py).
    mode_paiement = db.Column(db.String(20))
    operateur_mobile = db.Column(db.String(50))
    reference_paiement = db.Column(db.String(100))
    date_paiement = db.Column(db.Date)
    payee_par = db.Column(db.String(255))
    payee_le = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# PART MÉDECIN — rétrocession au réalisateur d'un acte (consultation,
# infiltration, imagerie...), même workflow en 3 états que
# PeriodeRistourne ci-dessus mais pour un médecin INTERNE (Medecin)
# plutôt qu'un PrescripteurExterne. Différence assumée : le taux est par
# ACTE (TauxPartMedecin), pas par médecin — chaque PrestationMedecin fige
# donc son propre taux/montant à la vente, plutôt qu'un taux unique
# appliqué à toute une période comme pour la ristourne.
# ============================================================
class TauxPartMedecin(db.Model):
    """Pourcentage reversé au réalisateur, par acte exact — même forme
    que ClassificationActe (structure_id + nom_acte, upsert). Absent ou
    à 0% = pas de partage pour cet acte (comportement par défaut,
    inchangé pour tout le reste du catalogue)."""
    __tablename__ = 'taux_part_medecin'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom_acte = db.Column(db.String(255), nullable=False)
    taux_medecin = db.Column(db.Numeric, nullable=False)  # % pour le réalisateur
    actif = db.Column(db.Boolean, default=True)
    # Toujours demander le médecin ligne par ligne, même si un "médecin du
    # jour" est défini (ex: infiltration, où le réalisateur varie).
    toujours_demander_medecin = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('structure_id', 'nom_acte', name='uq_structure_taux_part_medecin'),
    )


class PrestationMedecin(db.Model):
    """Une ligne facturée attribuée à un médecin réalisateur — créée
    automatiquement à la vente (même principe que DemandeExamen pour les
    ristournes, voir services/part_medecin_service.py). Taux et montant
    FIGÉS au moment de la vente (pas de la clôture) : contrairement à la
    ristourne où un seul taux s'applique à tout le prescripteur, ici
    chaque ligne peut avoir un taux différent selon l'acte vendu — les
    figer seulement à la clôture n'aurait pas de sens."""
    __tablename__ = 'prestations_medecin'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    medecin_id = db.Column(db.Integer, nullable=False)
    medecin_nom = db.Column(db.String(255))  # dénormalisé (Medecin.get_nom_complet())
    vente_id = db.Column(db.Integer)
    nom_acte = db.Column(db.String(255), nullable=False)
    prix = db.Column(db.Numeric, nullable=False)
    quantite = db.Column(db.Integer, default=1)
    taux_medecin_applique = db.Column(db.Numeric, nullable=False)
    montant_part_medecin = db.Column(db.Numeric, nullable=False)
    periode_part_medecin_id = db.Column(db.Integer)  # NULL tant que pas clôturé
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PeriodePartMedecin(db.Model):
    """Clôture pour UN médecin sur une période — même 3 états que
    PeriodeRistourne (calculee/validee/payee) et mêmes champs de
    paiement. base_calcul/montant_total sont la SOMME des
    PrestationMedecin déjà individuellement figées (pas un taux unique
    × base)."""
    __tablename__ = 'periodes_part_medecin'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    medecin_id = db.Column(db.Integer, nullable=False)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    base_calcul = db.Column(db.Numeric, default=0)
    montant_total = db.Column(db.Numeric, default=0)
    nb_actes = db.Column(db.Integer, default=0)
    # ⭐ RSPS (2026-10-08) : retenue sur la part brute (montant_total), net payé
    # au médecin ; rsps_versement_id = versement groupé à l'OTR (VersementRsps).
    taux_rsps = db.Column(db.Numeric)
    montant_rsps = db.Column(db.Numeric, default=0)
    montant_net = db.Column(db.Numeric)
    rsps_versement_id = db.Column(db.Integer)
    statut = db.Column(db.String(20), default='calculee')  # 'calculee' | 'validee' | 'payee'
    calculee_par = db.Column(db.String(255))
    calculee_le = db.Column(db.DateTime, default=datetime.utcnow)
    validee_par = db.Column(db.String(255))
    validee_le = db.Column(db.DateTime)
    mode_paiement = db.Column(db.String(20))
    operateur_mobile = db.Column(db.String(50))
    reference_paiement = db.Column(db.String(100))
    date_paiement = db.Column(db.Date)
    payee_par = db.Column(db.String(255))
    payee_le = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# HOSPITALISATION — inventaire chambres/lits + occupation
# ============================================================
# Pré-créé une bonne fois par la structure (page de configuration), pour
# qu'ouvrir un séjour se fasse en choisissant un service puis un lit LIBRE
# plutôt qu'en tapant un texte libre à chaque fois — occupation/libération
# automatique, voir api_creer_hospitalisation / api_sortie_hospitalisation
# (app.py). `actif` = suppression douce : désactiver un service/chambre/lit
# ne casse pas l'historique des séjours qui le référencent déjà.
class ServiceHospitalisation(db.Model):
    __tablename__ = 'services_hospitalisation'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(255), nullable=False)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChambreHospitalisation(db.Model):
    __tablename__ = 'chambres_hospitalisation'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    service_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(255), nullable=False)  # ex. "Chambre 12"
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LitHospitalisation(db.Model):
    __tablename__ = 'lits_hospitalisation'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    chambre_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(100), nullable=False)  # ex. "Lit 1"
    statut = db.Column(db.String(20), default='libre')  # libre / occupe
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ⭐ Soins ambulatoires : mirroir de Hospitalisation (mêmes propriétés
# "effectives" d'assurance, mêmes noms) mais SANS chambre/lit — un patient
# suit des soins sur plusieurs jours (ex. pansement) sans être hospitalisé,
# avec un prédépôt versé le 1er jour. calculer_repartition_assurance() et
# charger_pbr_complementaires() (services/hospitalisation_service.py)
# s'utilisent tels quels grâce à ces propriétés identiques — aucun fork du
# service partagé.
class SoinsAmbulatoires(db.Model):
    __tablename__ = 'soins_ambulatoires'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    numero_local = db.Column(db.Integer)
    patient_id = db.Column(db.Integer, nullable=False)
    patient_nom = db.Column(db.String(255))
    motif = db.Column(db.String(255))
    mise_en_observation = db.Column(db.Boolean, default=False)
    date_debut = db.Column(db.DateTime, nullable=False)
    date_fin = db.Column(db.DateTime)
    predepot_montant = db.Column(db.Numeric, default=0)
    predepot_mode_paiement = db.Column(db.String(50))
    predepot_note = db.Column(db.Text)
    assurance_nom = db.Column(db.String(255))
    taux_assurance = db.Column(db.Numeric, default=0)
    assurance2_nom = db.Column(db.String(255))
    taux_assurance2 = db.Column(db.Numeric, default=0)
    societe_assurance2 = db.Column(db.String(255))
    assurance_principale_active = db.Column(db.Boolean, default=True)
    assurance2_active = db.Column(db.Boolean, default=True)
    applique_pbr_cac = db.Column(db.Boolean, default=True)
    pbr_cac_variante = db.Column(db.String(20), default='defaut')
    applique_tva = db.Column(db.Boolean, default=False)
    statut = db.Column(db.String(20), default='en_cours')  # en_cours / termine / facturee
    proforma_id = db.Column(db.Integer)
    vente_id = db.Column(db.Integer)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # ⭐ Recettes par service — même principe que Hospitalisation.service_id
    # (voir son commentaire équivalent).
    service_id = db.Column(db.Integer)

    # ⭐ Mêmes propriétés "effectives", mot pour mot, que Hospitalisation
    # (models.py) — y compris le garde-fou taux > 0, sans quoi un patient
    # avec assurance_nom renseigné mais taux_assurance=0 serait compté
    # "assuré" à tort par calculer_repartition_assurance().
    @property
    def est_assure_amu(self):
        if not self.assurance_principale_active:
            return False
        return bool(self.assurance_nom) and self.assurance_nom not in ('non_assure', 'Non assuré') \
            and float(self.taux_assurance or 0) > 0

    @property
    def taux_assurance_effectif(self):
        return float(self.taux_assurance or 0) if self.est_assure_amu else 0

    @property
    def a_cac(self):
        return bool(self.assurance2_active) and bool(self.assurance2_nom) and float(self.taux_assurance2 or 0) > 0

    @property
    def taux_assurance2_effectif(self):
        return float(self.taux_assurance2 or 0) if self.a_cac else 0

    @property
    def nombre_jours(self):
        fin = self.date_fin or datetime.utcnow()
        jours = (fin.date() - self.date_debut.date()).days + 1
        return max(jours, 1)


class LigneSoinAmbulatoire(db.Model):
    __tablename__ = 'lignes_soins_ambulatoires'
    id = db.Column(db.Integer, primary_key=True)
    soins_ambulatoires_id = db.Column(db.Integer, nullable=False)
    structure_id = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20))  # 'acte' | 'medicament'
    reference_id = db.Column(db.Integer)
    nom = db.Column(db.String(255))
    prix = db.Column(db.Numeric, default=0)
    pbr = db.Column(db.Numeric, default=0)
    quantite = db.Column(db.Integer, default=1)
    prise_en_charge_amu = db.Column(db.Boolean, default=True)
    prise_en_charge_cac = db.Column(db.Boolean, default=True)
    date_prestation = db.Column(db.Date, nullable=False)
    heure_prestation = db.Column(db.Time)
    note = db.Column(db.Text)
    enregistre_par = db.Column(db.String(255))
    date_enregistrement = db.Column(db.DateTime, default=datetime.utcnow)
    statut = db.Column(db.String(20), default='en_cours')  # en_cours / facture

    # ⭐ Part médecin — même principe que SoinHospitalisation ci-dessus.
    medecin_id = db.Column(db.Integer)
    medecin_nom = db.Column(db.String(255))

    @property
    def total(self):
        return float(self.prix or 0) * int(self.quantite or 0)


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


# ⭐ Proforma d'intervention chirurgicale (patron, 2026-10-09) : devis
# calculé à partir de la cotation des actes en K (lettre clé), comme le
# document papier "FACTURE PROFORMA DE L'INTERVENTION" des cliniques
# chirurgicales. Calcul centralisé dans services/chirurgie_service.py ;
# `lignes`, `total_k` et `total` sont l'instantané calculé à
# l'enregistrement (ce qui a été remis au patient). Peut ensuite devenir
# une proforma ordinaire (facture réelle) et/ou une hospitalisation.
class ProformaChirurgie(db.Model):
    __tablename__ = 'proformas_chirurgie'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    numero_affiche = db.Column(db.String(50))
    patient_id = db.Column(db.Integer)
    patient_nom = db.Column(db.String(255), nullable=False)
    service = db.Column(db.String(255))
    motif = db.Column(db.Text)
    actes = db.Column(db.JSON, nullable=False, default=list)       # [{nom, k, diviseur}]
    coef_supp = db.Column(db.Numeric, default=0)                    # % du total des K
    parametres = db.Column(db.JSON, nullable=False, default=dict)   # valeurs du K, pourcentages...
    chambre_nom = db.Column(db.String(255))
    chambre_prix = db.Column(db.Numeric, default=0)
    jours = db.Column(db.Integer, default=0)
    forfaits = db.Column(db.JSON, nullable=False, default=list)    # [{nom, montant}]
    lignes = db.Column(db.JSON, nullable=False, default=list)      # tableau calculé
    total_k = db.Column(db.Numeric, default=0)
    total = db.Column(db.Numeric, default=0)
    note = db.Column(db.Text)
    proforma_id = db.Column(db.Integer)          # proforma ordinaire créée (facture réelle)
    hospitalisation_id = db.Column(db.Integer)   # séjour créé
    archive = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Modèle réutilisable ("Prothèse de hanche"...) : actes en K, forfaits et
# paramètres habituels d'une intervention.
class ModeleInterventionChirurgie(db.Model):
    __tablename__ = 'modeles_intervention_chirurgie'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(255), nullable=False)
    contenu = db.Column(db.JSON, nullable=False, default=dict)  # service, motif, actes, coef_supp, parametres, chambre, jours, forfaits
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Réglages par défaut de la structure (une ligne par structure).
class ParametrageChirurgie(db.Model):
    __tablename__ = 'parametrage_chirurgie'
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    reglages = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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

    # ⭐ Congés — patron : "qu'on décide s'il faut enlever les jours de
    # permission dans les congés ou pas". Configurable plutôt que figé en
    # dur : True = comportement déjà en place (Employe.get_solde_detail
    # décomptait déjà les permissions avant ce commit) — garde le calcul
    # inchangé pour les structures existantes tant que l'admin ne bascule
    # pas ce réglage lui-même.
    deduire_permissions_des_conges = db.Column(db.Boolean, default=True)

    # ⭐ Patron : "pointage déconnecté de la paie [...] qu'on décide
    # d'appliquer ou pas". Désactivé par défaut — aucun bulletin de paie
    # n'est modifié tant que l'admin n'active pas ce réglage lui-même. Une
    # fois actif, une retenue "Absences (pointage)" est calculée au
    # prorata (voir services/paie_service._retenue_absences) à partir des
    # jours sans aucun pointage sur les jours ouvrés du paramétrage de
    # pointage (ParametragePointage). Les retards ne sont PAS déduits
    # (portée volontairement limitée aux absences journée complète).
    appliquer_absences_sur_paie = db.Column(db.Boolean, default=False)

    # ⭐ Patron : "validation à plusieurs niveaux (SignatureRH) codée mais
    # jamais branchée". 1 = comportement inchangé (un clic "Approuver"
    # valide directement le congé, comme aujourd'hui). > 1 : chaque
    # "Approuver" ne valide qu'UN niveau de la chaîne SignatureRH/
    # DocumentRH — le congé ne passe à statut='approuve' qu'une fois tous
    # les niveaux validés (voir _valider_conge, routes/rh.py). Un refus à
    # n'importe quel niveau refuse le congé immédiatement.
    niveaux_validation_conges = db.Column(db.Integer, default=1)

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


class ParametrageAffichageStructure(db.Model):
    """Personnalisation d'affichage propre à une structure — pour l'instant
    juste l'acronyme montré dans le coin "SI <acronyme>" en haut à gauche
    (voir injecter_acronyme_structure(), app.py). Table dédiée plutôt que
    d'ajouter une colonne à `structures` : ce nom vient de Google Sheets
    (sheets_helper), pas de la table Postgres du même nom — voir
    api_structure_nom()/api_structure_infos() — donc une structure peut ne
    pas y avoir de ligne du tout."""
    __tablename__ = 'parametrage_affichage_structure'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False, unique=True)
    acronyme = db.Column(db.String(10))
    # Format papier par défaut pour le ticket de passage de la préinscription
    # accueil — 'A4' | 'A5' | '80mm' (imprimante à ticket thermique). Réglé
    # une fois pour la structure (le matériel d'impression à l'accueil ne
    # change pas d'un patient à l'autre) — voir page_accueil_qr, app.py.
    format_ticket_accueil = db.Column(db.String(10), default='80mm')
    # ⭐ Mot de passe appliqué au PDF du guide d'utilisation téléchargé
    # (voir api_guide_pdf_mot_de_passe, app.py) — patron : "verrouiller notre
    # pdf si quelqu'un le télécharge qu'il ne puisse pas l'ouvrir sans nous
    # demander". Vide = pas de protection (comportement d'origine).
    guide_pdf_mot_de_passe = db.Column(db.String(50))
    # ⭐ Autorisation posée par le SUPERADMIN uniquement (/admin_global,
    # jamais par la structure elle-même) — patron : "par défaut aucune
    # structure n'aura la main de télécharger... je veux pas qu'ils
    # divulguent ce pdf". Faux par défaut : le bouton "Télécharger en PDF"
    # n'apparaît même pas tant que ce n'est pas activé ici.
    guide_pdf_autorise = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# FAQ — commune à toutes les structures, préparée par le SUPERADMIN
# ============================================================
class FaqQuestion(db.Model):
    """Une question/réponse de la FAQ, commune à toutes les structures —
    gérée uniquement depuis /admin_global/faq (jamais par une structure).
    Visibilité filtrée par rôle comme le guide d'utilisation
    (guide_section_visible, app.py) : roles_autorises vide/NULL = visible
    par tous les rôles."""
    __tablename__ = 'faq_questions'

    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    reponse = db.Column(db.Text, nullable=False)
    # CSV des rôles autorisés (ex: "caissier,secretaire") — vide/NULL = tous.
    roles_autorises = db.Column(db.String(255))
    ordre = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FaqQuestionUtilisateur(db.Model):
    """Question posée librement par un utilisateur d'une structure, en
    complément de la FAQ préparée (patron : "les utilisateurs peuvent
    aussi poser une nouvelle question") — en attente de réponse du
    superadmin (/admin_global/faq), puis visible par son auteur sur la
    page /faq de sa structure une fois répondue."""
    __tablename__ = 'faq_questions_utilisateurs'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    # Dénormalisé (comme patient_nom sur Hospitalisation) : le nom de la
    # structure vit dans Google Sheets, pas dans cette table Postgres —
    # capturé à la soumission pour que l'écran superadmin l'affiche sans
    # aller-retour Sheets par ligne.
    structure_nom = db.Column(db.String(200))
    user_id = db.Column(db.Integer)
    user_name = db.Column(db.String(150))
    role = db.Column(db.String(50))
    question = db.Column(db.Text, nullable=False)
    reponse = db.Column(db.Text)
    statut = db.Column(db.String(20), nullable=False, default='en_attente')  # 'en_attente' | 'repondue'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    repondue_at = db.Column(db.DateTime)


class JourFerie(db.Model):
    """Jours fériés déclarés par une structure — utilisé par
    est_tarif_nuit_actif() (app.py) pour savoir si le tarif majoré
    nuit/férié/dimanche s'applique à un acte, en plus de l'horaire et du
    dimanche (calculables sans table). Par structure (pas global) : chaque
    clinique gère sa propre liste, réutilisable chaque année sans toucher
    au code. Introduit pour Clinique Valeo (structure 13) et sa convention
    d'assurance privée locale, mais générique pour toute structure."""
    __tablename__ = 'jours_feries'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    libelle = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('structure_id', 'date', name='uq_structure_jour_ferie'),
    )


class MedecinDuJour(db.Model):
    """Médecin par défaut pour toutes les consultations/imageries d'une
    journée donnée, par structure — évite de redemander le médecin à
    chaque ligne de vente (voir toujours_demander_medecin sur
    TauxPartMedecin pour les actes qui doivent continuer à demander,
    ex: infiltration). Modifiable en cours de journée (upsert), même
    patron que JourFerie."""
    __tablename__ = 'medecin_du_jour'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    medecin_id = db.Column(db.Integer, nullable=False)
    defini_par = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('structure_id', 'date', name='uq_structure_medecin_du_jour'),
    )
