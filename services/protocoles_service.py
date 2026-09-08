# ============================================================
# SERVICE DE GESTION DES PROTOCOLES MEDICAUX
# ============================================================

from datetime import datetime, date
from models import db, ProtocoleMedical, HistoriqueProtocole, ProtocolePatient, Patient

class ProtocolesService:
    """Service pour la gestion des protocoles et modèles médicaux"""
    
    CATEGORIES = [
        {'id': 'protocole_soins', 'nom': 'Protocole de soins'},
        {'id': 'ordonnance_type', 'nom': 'Ordonnance type'},
        {'id': 'bulletin_examen', 'nom': 'Bulletin d\'examen'},
        {'id': 'protocole_patient', 'nom': 'Protocole patient'},
        {'id': 'fiche_information', 'nom': 'Fiche d\'information'},
        {'id': 'protocole_infirmier', 'nom': 'Protocole infirmier'}
    ]
    
    STATUTS = [
        {'id': 'brouillon', 'nom': 'Brouillon'},
        {'id': 'en_validation', 'nom': 'En validation'},
        {'id': 'publie', 'nom': 'Publié'},
        {'id': 'archive', 'nom': 'Archivé'}
    ]
    
    @classmethod
    def creer(cls, data, structure_id, utilisateur_nom):
        """Crée un nouveau protocole"""
        try:
            protocole = ProtocoleMedical(
                structure_id=structure_id,
                categorie=data.get('categorie'),
                titre=data.get('titre'),
                description=data.get('description', ''),
                contenu=data.get('contenu'),
                specialite=data.get('specialite'),
                tags=data.get('tags', []),
                statut=data.get('statut', 'brouillon'),
                auteur_nom=utilisateur_nom,
                medicaments=data.get('medicaments', []),
                examens=data.get('examens', []),
                patient_id=data.get('patient_id'),
                date_debut=data.get('date_debut'),
                date_fin=data.get('date_fin'),
                etapes=data.get('etapes', []),
                duree=data.get('duree')
            )
            
            db.session.add(protocole)
            db.session.flush()
            
            # Historique
            cls._ajouter_historique(
                protocole_id=protocole.id,
                action='creation',
                utilisateur_nom=utilisateur_nom,
                commentaire=f'Création du protocole: {protocole.titre}'
            )
            
            db.session.commit()
            return True, {'id': protocole.id, 'protocole': protocole.to_dict()}
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    @classmethod
    def get_liste(cls, structure_id, categorie=None, statut=None, 
                  specialite=None, search=None, limit=100, offset=0):
        """Récupère la liste des protocoles"""
        query = ProtocoleMedical.query.filter_by(structure_id=structure_id)
        
        if categorie:
            query = query.filter_by(categorie=categorie)
        if statut:
            query = query.filter_by(statut=statut)
        if specialite:
            query = query.filter_by(specialite=specialite)
        if search:
            query = query.filter(
                db.or_(
                    ProtocoleMedical.titre.ilike(f'%{search}%'),
                    ProtocoleMedical.description.ilike(f'%{search}%'),
                    ProtocoleMedical.tags.cast(db.Text).ilike(f'%{search}%')
                )
            )
        
        total = query.count()
        protocoles = query.order_by(ProtocoleMedical.titre).limit(limit).offset(offset).all()
        
        return protocoles, total
    
    @classmethod
    def get_par_id(cls, protocole_id, structure_id):
        """Récupère un protocole par son ID"""
        return ProtocoleMedical.query.filter_by(id=protocole_id, structure_id=structure_id).first()
    
    @classmethod
    def modifier(cls, protocole_id, structure_id, data, utilisateur_nom):
        """Modifie un protocole"""
        try:
            protocole = cls.get_par_id(protocole_id, structure_id)
            if not protocole:
                return False, {'error': 'Protocole non trouvé'}
            
            ancien_contenu = protocole.contenu
            
            # Mettre à jour les champs
            for champ in ['titre', 'description', 'contenu', 'specialite', 'tags',
                         'statut', 'medicaments', 'examens', 'patient_id',
                         'date_debut', 'date_fin', 'etapes', 'duree']:
                if champ in data:
                    setattr(protocole, champ, data[champ])
            
            protocole.version += 1
            protocole.updated_at = datetime.utcnow()
            
            # Historique
            cls._ajouter_historique(
                protocole_id=protocole.id,
                action='modification',
                utilisateur_nom=utilisateur_nom,
                commentaire=f'Modification du protocole: {protocole.titre}',
                ancien_contenu=ancien_contenu,
                nouveau_contenu=protocole.contenu
            )
            
            db.session.commit()
            return True, {'protocole': protocole.to_dict()}
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    @classmethod
    def changer_statut(cls, protocole_id, structure_id, nouveau_statut, utilisateur_nom):
        """Change le statut d'un protocole"""
        try:
            protocole = cls.get_par_id(protocole_id, structure_id)
            if not protocole:
                return False, {'error': 'Protocole non trouvé'}
            
            ancien_statut = protocole.statut
            protocole.statut = nouveau_statut
            
            cls._ajouter_historique(
                protocole_id=protocole.id,
                action='changement_statut',
                utilisateur_nom=utilisateur_nom,
                commentaire=f'Statut: {ancien_statut} -> {nouveau_statut}'
            )
            
            db.session.commit()
            return True, {'protocole': protocole.to_dict()}
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    @classmethod
    def dupliquer(cls, protocole_id, structure_id, utilisateur_nom):
        """Duplique un protocole"""
        try:
            original = cls.get_par_id(protocole_id, structure_id)
            if not original:
                return False, {'error': 'Protocole non trouvé'}
            
            nouveau = ProtocoleMedical(
                structure_id=structure_id,
                categorie=original.categorie,
                titre=f"{original.titre} (copie)",
                description=original.description,
                contenu=original.contenu,
                specialite=original.specialite,
                tags=original.tags,
                statut='brouillon',
                auteur_nom=utilisateur_nom,
                medicaments=original.medicaments,
                examens=original.examens,
                etapes=original.etapes,
                duree=original.duree
            )
            
            db.session.add(nouveau)
            db.session.flush()
            
            cls._ajouter_historique(
                protocole_id=nouveau.id,
                action='creation',
                utilisateur_nom=utilisateur_nom,
                commentaire=f'Duplication du protocole: {original.titre}'
            )
            
            db.session.commit()
            return True, {'id': nouveau.id, 'protocole': nouveau.to_dict()}
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    # ============================================================
    # SUPPRESSION CORRIGÉE
    # ============================================================
    
    @classmethod
    def supprimer(cls, protocole_id, structure_id, utilisateur_nom):
        """Supprime un protocole"""
        try:
            protocole = cls.get_par_id(protocole_id, structure_id)
            if not protocole:
                return False, {'error': 'Protocole non trouvé'}
            
            # 🔥 SUPPRIMER D'ABORD L'HISTORIQUE
            HistoriqueProtocole.query.filter_by(protocole_id=protocole.id).delete()
            
            # 🔥 SUPPRIMER LES ASSOCIATIONS PATIENT
            ProtocolePatient.query.filter_by(protocole_id=protocole.id).delete()
            
            # 🔥 SUPPRIMER LE PROTOCOLE
            db.session.delete(protocole)
            db.session.commit()
            return True, {'message': 'Protocole supprimé avec succès'}
            
        except Exception as e:
            db.session.rollback()
            print(f"Erreur suppression protocole: {e}")
            import traceback
            traceback.print_exc()
            return False, {'error': str(e)}
    
    @classmethod
    def assigner_a_patient(cls, protocole_id, structure_id, patient_id, date_debut, notes=''):
        """Assigne un protocole à un patient"""
        try:
            protocole = cls.get_par_id(protocole_id, structure_id)
            if not protocole:
                return False, {'error': 'Protocole non trouvé'}
            
            # Vérifier que le patient existe
            patient = Patient.query.filter_by(id=patient_id, structure_id=structure_id).first()
            if not patient:
                return False, {'error': 'Patient non trouvé'}
            
            # Créer l'association
            association = ProtocolePatient(
                structure_id=structure_id,
                patient_id=patient_id,
                protocole_id=protocole_id,
                date_debut=date_debut,
                notes=notes,
                statut='en_cours'
            )
            
            db.session.add(association)
            db.session.commit()
            
            return True, {'message': 'Protocole assigné au patient avec succès'}
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    @classmethod
    def get_protocoles_patient(cls, patient_id, structure_id):
        """Récupère tous les protocoles assignés à un patient"""
        try:
            associations = ProtocolePatient.query.filter_by(
                patient_id=patient_id,
                structure_id=structure_id
            ).all()
            
            resultats = []
            for assoc in associations:
                protocole = ProtocoleMedical.query.get(assoc.protocole_id)
                if protocole:
                    resultats.append({
                        'id': assoc.id,
                        'protocole': protocole.to_dict(),
                        'statut': assoc.statut,
                        'date_debut': assoc.date_debut.isoformat() if assoc.date_debut else None,
                        'date_fin': assoc.date_fin.isoformat() if assoc.date_fin else None,
                        'notes': assoc.notes
                    })
            
            return resultats
            
        except Exception as e:
            print(f"Erreur: {e}")
            return []
    
    @classmethod
    def _ajouter_historique(cls, protocole_id, action, utilisateur_nom, 
                           commentaire='', ancien_contenu=None, nouveau_contenu=None):
        """Ajoute une entrée dans l'historique"""
        try:
            historique = HistoriqueProtocole(
                protocole_id=protocole_id,
                action=action,
                utilisateur_nom=utilisateur_nom or 'Systeme',
                ancien_contenu=ancien_contenu,
                nouveau_contenu=nouveau_contenu,
                commentaire=commentaire
            )
            db.session.add(historique)
        except Exception as e:
            print(f"Erreur ajout historique: {e}")