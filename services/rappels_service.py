# ============================================================
# SERVICE DE GESTION DES RAPPELS
# ============================================================

from datetime import datetime, date, timedelta
from models import db, RendezVous, Patient, Structure

# Pour accéder à sheets_helper (à importer si nécessaire)
# from utils.sheets_helper import sheets_helper

class RappelsService:
    """Service pour la gestion des rappels de rendez-vous"""
    
    @classmethod
    def envoyer_rappel_manuel(cls, rdv_id, type_rappel='manuel'):
        """Envoie un rappel manuel pour un rendez-vous"""
        try:
            rdv = RendezVous.query.get(rdv_id)
            if not rdv:
                return False, {'error': 'Rendez-vous non trouvé'}
            
            patient = Patient.query.get(rdv.patient_id)
            if not patient:
                return False, {'error': 'Patient non trouvé'}
            
            if not patient.telephone:
                return False, {'error': 'Numéro de téléphone manquant'}
            
            # Récupérer la structure depuis Google Sheets
            structure = cls._get_structure(rdv.structure_id)
            
            if structure:
                structure_nom = structure.get('nom', 'Notre établissement')
                structure_telephone = structure.get('telephone', '')
                structure_adresse = structure.get('adresse', '')
                structure_email = structure.get('email', '')
            else:
                # Fallback: essayer depuis la base de données
                structure_db = Structure.query.get(rdv.structure_id)
                structure_nom = structure_db.nom if structure_db else 'Notre établissement'
                structure_telephone = structure_db.telephone if structure_db else ''
                structure_adresse = structure_db.adresse if structure_db else ''
                structure_email = structure_db.email if structure_db else ''
            
            # Calculer les jours restants
            jours_restants = (rdv.date_rendez_vous - date.today()).days
            
            # Générer le message
            message = cls._generer_message(
                patient_nom=f"{patient.nom} {patient.prenom}".strip(),
                date_rdv=rdv.date_rendez_vous,
                heure_rdv=rdv.heure_rendez_vous,
                motif=rdv.motif,
                structure_nom=structure_nom,
                structure_telephone=structure_telephone,
                structure_adresse=structure_adresse,
                structure_email=structure_email,
                jours_restants=jours_restants
            )
            
            # Construire l'URL WhatsApp
            tel = str(patient.telephone).replace(' ', '').replace('-', '').replace('+', '')
            if not tel.startswith('228') and not tel.startswith('229') and not tel.startswith('221'):
                tel = '228' + tel
            
            import urllib.parse
            message_encode = urllib.parse.quote(message)
            url_whatsapp = f"https://wa.me/{tel}?text={message_encode}"
            
            # Marquer le rappel comme envoyé
            rdv.rappel_envoye = True
            rdv.date_rappel = datetime.utcnow()
            db.session.commit()
            
            return True, {
                'message': 'Rappel envoyé avec succès',
                'url_whatsapp': url_whatsapp,
                'telephone': patient.telephone
            }
            
        except Exception as e:
            db.session.rollback()
            return False, {'error': str(e)}
    
    # ============================================================
    # MÉTHODE POUR RÉCUPÉRER LA STRUCTURE DEPUIS GOOGLE SHEETS
    # ============================================================
    
    @classmethod
    def _get_structure(cls, structure_id):
        """Récupère les informations de la structure depuis Google Sheets"""
        try:
            # Utiliser sheets_helper pour récupérer les structures
            # Décommentez la ligne ci-dessous si sheets_helper est disponible
            # structures = sheets_helper.get_all_records('structures', use_prefix=False)
            
            # Alternative: utiliser une requête directe si vous avez un autre moyen
            # Pour l'instant, on retourne None et on utilisera la base de données comme fallback
            
            # Si vous utilisez sheets_helper, décommentez ce bloc:
            """
            structures = sheets_helper.get_all_records('structures', use_prefix=False)
            for s in structures:
                if str(s.get('ID')) == str(structure_id):
                    return {
                        'nom': s.get('nom') or 'Hopital',
                        'adresse': s.get('adresse') or '',
                        'telephone': s.get('telephone') or '',
                        'email': s.get('email') or '',
                        'logo_url': s.get('logo_url') or ''
                    }
            """
            
            # Fallback: essayer depuis la base de données
            structure = Structure.query.get(structure_id)
            if structure:
                return {
                    'nom': structure.nom or 'Hopital',
                    'adresse': structure.adresse or '',
                    'telephone': structure.telephone or '',
                    'email': structure.email or '',
                    'logo_url': getattr(structure, 'logo_url', '') or ''
                }
                
        except Exception as e:
            print(f"Erreur récupération structure: {e}")
        
        return None
    
    # ============================================================
    # GÉNÉRATION DU MESSAGE
    # ============================================================
    
    @classmethod
    def _generer_message(cls, patient_nom, date_rdv, heure_rdv, motif,
                         structure_nom, structure_telephone, structure_adresse, structure_email, jours_restants):
        """Génère le message WhatsApp avec toutes les informations de la structure"""
        
        # Formater la date
        jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
        mois = ['Janvier', 'Fevrier', 'Mars', 'Avril', 'Mai', 'Juin',
                'Juillet', 'Aout', 'Septembre', 'Octobre', 'Novembre', 'Decembre']
        
        date_formatee = f"{jours[date_rdv.weekday()]} {date_rdv.day} {mois[date_rdv.month - 1]} {date_rdv.year}"
        
        # Déterminer l'emplacement
        if jours_restants == 0:
            emplacement = "AUJOURD'HUI"
        elif jours_restants == 1:
            emplacement = "DEMAIN"
        else:
            emplacement = f"dans {jours_restants} jours"
        
        # Construction du message
        message = []
        
        message.append(f"RAPPEL DE RENDEZ-VOUS - {emplacement}")
        message.append("")
        
        message.append(f"{structure_nom.upper()}")
        if structure_adresse:
            message.append(f"Adresse: {structure_adresse}")
        if structure_telephone:
            message.append(f"Tel: {structure_telephone}")
        if structure_email:
            message.append(f"Email: {structure_email}")
        message.append("")
        
        message.append(f"Cher(e) {patient_nom},")
        message.append("")
        
        message.append("Nous vous rappelons votre rendez-vous :")
        message.append(f"Date : {date_formatee}")
        message.append(f"Heure : {heure_rdv}")
        message.append(f"Motif : {motif}")
        message.append("")
        
        message.append("Merci de votre ponctualite.")
        if structure_telephone:
            message.append(f"Pour toute annulation ou report, contactez-nous au {structure_telephone}.")
        message.append("")
        message.append("Prenez soin de vous.")
        
        return "\n".join(message)
    
    # ============================================================
    # STATISTIQUES DES RAPPELS
    # ============================================================
    
    @classmethod
    def get_stats_rappels(cls, structure_id):
        """Récupère les statistiques des rappels"""
        today = date.today()
        
        # Rendez-vous à moins de 7 jours
        moins_7 = RendezVous.query.filter(
            RendezVous.structure_id == structure_id,
            RendezVous.date_rendez_vous >= today,
            RendezVous.date_rendez_vous <= today + timedelta(days=7),
            RendezVous.statut.in_(['programme', 'confirme'])
        ).count()
        
        # Rendez-vous dépassés
        depasses = RendezVous.query.filter(
            RendezVous.structure_id == structure_id,
            RendezVous.date_rendez_vous < today,
            RendezVous.statut.in_(['programme', 'confirme'])
        ).count()
        
        # Rendez-vous aujourd'hui
        aujourdhui = RendezVous.query.filter(
            RendezVous.structure_id == structure_id,
            RendezVous.date_rendez_vous == today,
            RendezVous.statut.in_(['programme', 'confirme'])
        ).count()
        
        return {
            'moins_7': moins_7,
            'depasses': depasses,
            'aujourdhui': aujourdhui
        }