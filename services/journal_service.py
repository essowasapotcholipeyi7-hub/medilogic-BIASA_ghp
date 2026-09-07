# ============================================================
# SERVICE DU JOURNAL DES MOUVEMENTS
# ============================================================

from datetime import datetime, date, timedelta
from models import db, JournalMouvement, Vente, Facture, Recette, Depense, RendezVous
from sqlalchemy import and_, or_, desc

class JournalService:
    """Service pour la gestion du journal des mouvements"""
    
    CATEGORIES = [
        {'id': 'toutes', 'nom': 'Toutes les catégories'},
        {'id': 'vente_actes', 'nom': 'Vente d\'actes'},
        {'id': 'vente_pharmacie', 'nom': 'Vente pharmacie'},
        {'id': 'vente_lunettes', 'nom': 'Vente lunettes'},
        {'id': 'annulation_vente', 'nom': 'Annulation vente'},
        {'id': 'paiement_facture', 'nom': 'Paiement facture'},
        {'id': 'paiement_assurance', 'nom': 'Paiement assurance'},
        {'id': 'facture_emise', 'nom': 'Facture émise'},
        {'id': 'avoir_emis', 'nom': 'Avoir émis'},
        {'id': 'recette_encaisee', 'nom': 'Recette encaissée'},
        {'id': 'depense_enregistree', 'nom': 'Dépense enregistrée'},
        {'id': 'proforma_cree', 'nom': 'Proforma créé'},
        {'id': 'rendez_vous_pris', 'nom': 'Rendez-vous pris'},
        {'id': 'consultation_terminee', 'nom': 'Consultation terminée'},
        # ⭐ Comptabilité / RH (branchés à partir de la refonte SYSCOHADA)
        {'id': 'ecriture_generee', 'nom': 'Écriture comptable générée'},
        {'id': 'salaire_paye', 'nom': 'Salaire payé'},
        {'id': 'employe_ajoute', 'nom': 'Employé ajouté'},
        {'id': 'conge_approuve', 'nom': 'Congé approuvé'},
        {'id': 'permission_approuvee', 'nom': 'Permission approuvée'},
        {'id': 'cloture_exercice', 'nom': 'Clôture d\'exercice'},
    ]
    
    @classmethod
    def get_liste(cls, structure_id, categorie=None, date_debut=None, date_fin=None,
                  search=None, limit=100, offset=0):
        """Récupère la liste des mouvements avec filtres"""
        query = JournalMouvement.query.filter_by(structure_id=structure_id)
        
        if categorie and categorie != 'toutes':
            query = query.filter_by(categorie=categorie)
        
        if date_debut:
            query = query.filter(JournalMouvement.date_mouvement >= date_debut)
        if date_fin:
            # Ajouter un jour pour inclure toute la journée
            date_fin = date_fin + timedelta(days=1)
            query = query.filter(JournalMouvement.date_mouvement < date_fin)
        
        if search:
            query = query.filter(
                db.or_(
                    JournalMouvement.description.ilike(f'%{search}%'),
                    JournalMouvement.patient_nom.ilike(f'%{search}%'),
                    JournalMouvement.utilisateur_nom.ilike(f'%{search}%')
                )
            )
        
        total = query.count()
        
        # Statistiques des montants
        stats = cls.get_stats(structure_id, categorie, date_debut, date_fin)
        
        mouvements = query.order_by(
            desc(JournalMouvement.date_mouvement),
            desc(JournalMouvement.id)
        ).limit(limit).offset(offset).all()
        
        return mouvements, total, stats
    
    @classmethod
    def get_stats(cls, structure_id, categorie=None, date_debut=None, date_fin=None):
        """Récupère les statistiques des mouvements"""
        query = JournalMouvement.query.filter_by(structure_id=structure_id)
        
        if categorie and categorie != 'toutes':
            query = query.filter_by(categorie=categorie)
        
        if date_debut:
            query = query.filter(JournalMouvement.date_mouvement >= date_debut)
        if date_fin:
            date_fin = date_fin + timedelta(days=1)
            query = query.filter(JournalMouvement.date_mouvement < date_fin)
        
        total_credits = db.session.query(
            db.func.coalesce(db.func.sum(JournalMouvement.montant), 0)
        ).filter(
            JournalMouvement.structure_id == structure_id,
            JournalMouvement.type_montant == 'credit'
        )
        
        total_debits = db.session.query(
            db.func.coalesce(db.func.sum(JournalMouvement.montant), 0)
        ).filter(
            JournalMouvement.structure_id == structure_id,
            JournalMouvement.type_montant == 'debit'
        )
        
        if categorie and categorie != 'toutes':
            total_credits = total_credits.filter(JournalMouvement.categorie == categorie)
            total_debits = total_debits.filter(JournalMouvement.categorie == categorie)
        
        if date_debut:
            total_credits = total_credits.filter(JournalMouvement.date_mouvement >= date_debut)
            total_debits = total_debits.filter(JournalMouvement.date_mouvement >= date_debut)
        if date_fin:
            total_credits = total_credits.filter(JournalMouvement.date_mouvement < date_fin)
            total_debits = total_debits.filter(JournalMouvement.date_mouvement < date_fin)
        
        credits = total_credits.scalar() or 0
        debits = total_debits.scalar() or 0
        
        return {
            'total': query.count(),
            'credits': float(credits),
            'debits': float(debits),
            'solde': float(credits) - float(debits)
        }
    
    @classmethod
    def get_par_id(cls, mouvement_id, structure_id):
        """Récupère un mouvement par son ID"""
        return JournalMouvement.query.filter_by(id=mouvement_id, structure_id=structure_id).first()
    
    @classmethod
    def get_categories_stats(cls, structure_id, date_debut=None, date_fin=None):
        """Statistiques par catégorie"""
        query = JournalMouvement.query.filter_by(structure_id=structure_id)
        
        if date_debut:
            query = query.filter(JournalMouvement.date_mouvement >= date_debut)
        if date_fin:
            date_fin = date_fin + timedelta(days=1)
            query = query.filter(JournalMouvement.date_mouvement < date_fin)
        
        results = []
        for cat in cls.CATEGORIES:
            if cat['id'] == 'toutes':
                continue
            
            cat_query = query.filter_by(categorie=cat['id'])
            total = cat_query.count()
            montant = db.session.query(
                db.func.coalesce(db.func.sum(JournalMouvement.montant), 0)
            ).filter(
                JournalMouvement.structure_id == structure_id,
                JournalMouvement.categorie == cat['id']
            )
            if date_debut:
                montant = montant.filter(JournalMouvement.date_mouvement >= date_debut)
            if date_fin:
                montant = montant.filter(JournalMouvement.date_mouvement < date_fin)
            
            results.append({
                'categorie': cat['id'],
                'nom': cat['nom'],
                'total': total,
                'montant': float(montant.scalar() or 0)
            })
        
        return results
    
    # ============================================================
    # CRÉATION DE MOUVEMENTS
    # ============================================================
    
    @classmethod
    def creer_mouvement(cls, structure_id, categorie, description, montant=0,
                        type_montant='neutre', reference_type=None, reference_id=None,
                        patient_id=None, patient_nom=None, utilisateur_id=None,
                        utilisateur_nom=None, details=None, date_mouvement=None):
        """Crée un nouveau mouvement dans le journal"""
        try:
            mouvement = JournalMouvement(
                structure_id=structure_id,
                categorie=categorie,
                description=description,
                montant=abs(montant) if montant else 0,
                type_montant=type_montant,
                reference_type=reference_type,
                reference_id=reference_id,
                patient_id=patient_id,
                patient_nom=patient_nom,
                utilisateur_id=utilisateur_id,
                utilisateur_nom=utilisateur_nom or 'Systeme',
                details=details or {},
                date_mouvement=date_mouvement or datetime.utcnow()
            )
            
            db.session.add(mouvement)
            db.session.commit()
            return True, mouvement
            
        except Exception as e:
            db.session.rollback()
            print(f"Erreur création mouvement: {e}")
            return False, None