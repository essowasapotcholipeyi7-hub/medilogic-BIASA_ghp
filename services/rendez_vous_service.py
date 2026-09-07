# ============================================================
# SERVICE DE GESTION DES RENDEZ-VOUS
# ============================================================

from datetime import datetime, date, timedelta
import re
from models import db, RendezVous, Medecin, Patient

class RendezVousService:
    """Service pour la gestion des rendez-vous"""
    
    STATUTS_VALIDES = ['programme', 'confirme', 'termine', 'annule', 'reporte', 'absent']
    STATUTS_ACTIFS = ['programme', 'confirme']
    DUREE_MIN = 15
    DUREE_MAX = 120
    DUREE_DEFAUT = 30
    
    @classmethod
    def creer_rendez_vous(cls, data, structure_id, utilisateur_nom='Systeme'):
        """Crée un nouveau rendez-vous"""
        try:
            # Vérifier les champs obligatoires
            champs = ['patient_id', 'medecin_id', 'date', 'heure', 'motif']
            for champ in champs:
                if not data.get(champ):
                    return False, {'error': f'Le champ {champ} est obligatoire'}
            
            # Vérifier le patient
            patient = Patient.query.get(data['patient_id'])
            if not patient:
                return False, {'error': 'Patient non trouvé'}
            
            # Vérifier le médecin
            medecin = Medecin.query.filter_by(
                id=data['medecin_id'],
                structure_id=structure_id,
                actif=True
            ).first()
            if not medecin:
                return False, {'error': 'Médecin non trouvé ou inactif'}
            
            # Valider la date
            try:
                date_rdv = datetime.strptime(data['date'], '%Y-%m-%d').date()
            except ValueError:
                return False, {'error': 'Format de date invalide'}
            
            if date_rdv < date.today():
                return False, {'error': 'La date ne peut pas être dans le passé'}
            
            # Valider l'heure
            if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', data['heure']):
                return False, {'error': 'Format d\'heure invalide'}
            
            # Vérifier les conflits
            conflit = cls.verifier_conflit(
                data['medecin_id'],
                date_rdv,
                data['heure'],
                data.get('duree', cls.DUREE_DEFAUT)
            )
            if conflit:
                return False, {'error': f'Créneau déjà occupé'}
            
            # Créer le rendez-vous
            rdv = RendezVous(
                structure_id=structure_id,
                patient_id=data['patient_id'],
                patient_nom=f"{patient.nom} {patient.prenom}".strip(),
                patient_telephone=patient.telephone,
                medecin_id=data['medecin_id'],
                date_rendez_vous=date_rdv,
                heure_rendez_vous=data['heure'],
                duree=data.get('duree', cls.DUREE_DEFAUT),
                motif=data['motif'],
                notes=data.get('notes', ''),
                statut='programme'
            )
            
            db.session.add(rdv)
            db.session.commit()
            
            return True, {
                'id': rdv.id,
                'message': 'Rendez-vous créé avec succès',
                'rendez_vous': rdv.to_dict()
            }
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    @classmethod
    def get_rendez_vous_liste(cls, structure_id, date_debut=None, date_fin=None, 
                              statut=None, medecin_id=None):
        """Récupère la liste des rendez-vous"""
        query = RendezVous.query.filter_by(structure_id=structure_id)
        
        if date_debut:
            query = query.filter(RendezVous.date_rendez_vous >= date_debut)
        if date_fin:
            query = query.filter(RendezVous.date_rendez_vous <= date_fin)
        if statut and statut != 'tous':
            query = query.filter(RendezVous.statut == statut)
        if medecin_id:
            query = query.filter(RendezVous.medecin_id == medecin_id)
        
        total = query.count()
        rendez_vous = query.order_by(
            RendezVous.id.desc()
        ).all()
        
        return rendez_vous, total
    
    @classmethod
    def get_rendez_vous_par_id(cls, rdv_id, structure_id):
        """Récupère un rendez-vous par son ID"""
        return RendezVous.query.filter_by(id=rdv_id, structure_id=structure_id).first()
    
    @classmethod
    def verifier_conflit(cls, medecin_id, date, heure, duree=DUREE_DEFAUT, exclude_id=None):
        """Vérifie si un créneau est occupé"""
        query = RendezVous.query.filter(
            RendezVous.medecin_id == medecin_id,
            RendezVous.date_rendez_vous == date,
            RendezVous.statut.in_(cls.STATUTS_ACTIFS)
        )
        if exclude_id:
            query = query.filter(RendezVous.id != exclude_id)
        
        rendez_vous = query.all()
        
        # Convertir l'heure en minutes
        h, m = map(int, heure.split(':'))
        debut = h * 60 + m
        fin = debut + duree
        
        for rdv in rendez_vous:
            h2, m2 = map(int, rdv.heure_rendez_vous.split(':'))
            rdv_debut = h2 * 60 + m2
            rdv_fin = rdv_debut + (rdv.duree or cls.DUREE_DEFAUT)
            
            if (debut < rdv_fin and fin > rdv_debut):
                return rdv
        
        return None
    
    @classmethod
    def verifier_disponibilite_medecin(cls, medecin_id, date):
        """Vérifie la disponibilité d'un médecin"""
        try:
            medecin = Medecin.query.get(medecin_id)
            if not medecin or not medecin.actif:
                return {'disponible': False, 'motif': 'Médecin non disponible'}
            
            duree = medecin.duree_consultation or cls.DUREE_DEFAUT
            
            # Générer les créneaux
            creneaux = []
            for h in range(8, 17):
                for m in [0, 30]:
                    heure_str = f"{h:02d}:{m:02d}"
                    conflit = cls.verifier_conflit(medecin_id, date, heure_str, duree)
                    if not conflit:
                        creneaux.append(heure_str)
            
            return {
                'disponible': len(creneaux) > 0,
                'creneaux': creneaux[:10],
                'duree': duree
            }
            
        except Exception as e:
            return {'disponible': False, 'motif': str(e)}
    
    @classmethod
    def confirmer_rendez_vous(cls, rdv_id, structure_id, utilisateur_nom='Systeme'):
        """Confirme un rendez-vous"""
        return cls._changer_statut(rdv_id, structure_id, 'confirme', utilisateur_nom)
    
    @classmethod
    def terminer_rendez_vous(cls, rdv_id, structure_id, utilisateur_nom='Systeme'):
        """Termine un rendez-vous"""
        return cls._changer_statut(rdv_id, structure_id, 'termine', utilisateur_nom)
    
    @classmethod
    def annuler_rendez_vous(cls, rdv_id, structure_id, utilisateur_nom='Systeme', motif=None):
        """Annule un rendez-vous"""
        return cls._changer_statut(rdv_id, structure_id, 'annule', utilisateur_nom)
    
    @classmethod
    def _changer_statut(cls, rdv_id, structure_id, nouveau_statut, utilisateur_nom):
        """Change le statut d'un rendez-vous"""
        try:
            rdv = cls.get_rendez_vous_par_id(rdv_id, structure_id)
            if not rdv:
                return False, {'error': 'Rendez-vous non trouvé'}
            
            if nouveau_statut not in cls.STATUTS_VALIDES:
                return False, {'error': f'Statut invalide: {nouveau_statut}'}
            
            # Transitions valides
            transitions = {
                'programme': ['confirme', 'termine', 'annule', 'reporte'],  # ← MODIFIÉ
                'confirme': ['termine', 'annule', 'reporte'],
                'termine': [],
                'annule': [],
                'reporte': ['confirme', 'annule', 'programme'],
                'absent': []
            }
            
            if nouveau_statut not in transitions.get(rdv.statut, []):
                return False, {'error': f'Transition invalide: {rdv.statut} -> {nouveau_statut}'}
            
            rdv.statut = nouveau_statut
            db.session.commit()
            
            return True, {
                'message': f'Rendez-vous {nouveau_statut} avec succès',
                'rendez_vous': rdv.to_dict()
            }
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    @classmethod
    def reporter_rendez_vous(cls, rdv_id, structure_id, nouvelle_date, nouvelle_heure,
                            utilisateur_nom='Systeme', message=None):
        """Reporte un rendez-vous"""
        try:
            rdv = cls.get_rendez_vous_par_id(rdv_id, structure_id)
            if not rdv:
                return False, {'error': 'Rendez-vous non trouvé'}
            
            if rdv.statut in ['termine', 'annule']:
                return False, {'error': f'Impossible de reporter un rendez-vous {rdv.statut}'}
            
            try:
                date_obj = datetime.strptime(nouvelle_date, '%Y-%m-%d').date()
            except ValueError:
                return False, {'error': 'Format de date invalide'}
            
            if date_obj < date.today():
                return False, {'error': 'La date ne peut pas être dans le passé'}
            
            if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', nouvelle_heure):
                return False, {'error': 'Format d\'heure invalide'}
            
            # Vérifier conflit
            conflit = cls.verifier_conflit(rdv.medecin_id, date_obj, nouvelle_heure, rdv.duree, rdv.id)
            if conflit:
                return False, {'error': 'Crénau déjà occupé'}
            
            ancienne_date = rdv.date_rendez_vous.isoformat()
            ancienne_heure = rdv.heure_rendez_vous
            
            rdv.date_rendez_vous = date_obj
            rdv.heure_rendez_vous = nouvelle_heure
            rdv.statut = 'reporte'
            
            if message:
                rdv.notes = (rdv.notes or '') + f"\nReporté: {message}"
            
            db.session.commit()
            
            return True, {
                'message': 'Rendez-vous reporté avec succès',
                'rendez_vous': rdv.to_dict()
            }
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    @classmethod
    def get_statistiques(cls, structure_id):
        """Récupère les statistiques des rendez-vous"""
        query = RendezVous.query.filter_by(structure_id=structure_id)
        
        stats = {
            'total': query.count(),
            'par_statut': {}
        }
        
        for statut in cls.STATUTS_VALIDES:
            stats['par_statut'][statut] = query.filter_by(statut=statut).count()
        
        return stats