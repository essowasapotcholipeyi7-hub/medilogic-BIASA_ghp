"""
Tâches de synchro sortante GHP -> gestion_patients (résultats
d'analyses/examens + modèles de résultats) — voir
/api/resultats-examens/sync-externe côté gestion_patients (app.py) pour la
réception, et scheduler.py ici pour le rattrapage périodique. Même forme
que gestion_patients/tasks.py (boucle sur chaque mapping actif, jamais
.first() — une structure GHP peut en théorie avoir plusieurs cibles).
"""
from app import app, db
from models import StructureMapping, ResultatExamen, ModeleResultat, DemandeExamen, Patient
import requests
import base64
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def _type_prestation_vers_analyse(type_prestation):
    return 'examen' if type_prestation == 'examen' else 'analyse'


def sync_resultats_examens_to_gestion_patients():
    """
    Pousse vers gestion_patients tout ResultatExamen / ModeleResultat
    NATIF de GHP (source_app IS NULL — jamais un résultat lui-même reçu de
    gestion_patients, voir la règle anti-boucle dans
    api_sync_resultat_examen_externe) pas encore synchronisé
    (source_synced_at IS NULL).
    """
    with app.app_context():
        try:
            mappings = StructureMapping.query.filter_by(source_name='gestion_patients', actif=True).all()
            if not mappings:
                return {'success': True, 'message': 'Aucune configuration gestion_patients active', 'count': 0}

            total_envoyes = 0
            messages = []

            for mapping in mappings:
                url = f"{mapping.api_url}/api/resultats-examens/sync-externe"
                params = {'token': mapping.api_key}

                # ---- Résultats (ResultatExamen natif, non synchronisé) ----
                resultats = ResultatExamen.query.filter(
                    ResultatExamen.structure_id == mapping.local_structure_id,
                    ResultatExamen.source_app.is_(None),
                    ResultatExamen.source_synced_at.is_(None),
                ).all()

                for r in resultats:
                    demande = DemandeExamen.query.get(r.demande_id)
                    if not demande:
                        continue
                    patient = Patient.query.get(demande.patient_id)

                    payload = {
                        'categorie': 'resultat',
                        'source_app': 'ghp',
                        'source_model': 'ResultatExamen',
                        'source_id': r.id,
                        'patient_source_id': demande.patient_id,
                        'patient_nom': patient.nom if patient else (demande.patient_nom or '').split(' ')[0],
                        'patient_prenom': patient.prenom if patient else '',
                        'type_prestation': _type_prestation_vers_analyse(demande.type_prestation),
                        'nom_analyse': demande.acte_nom,
                        'motif': demande.motif or '',
                        'contenu_html': r.contenu_html or '',
                        'fichier_nom': r.fichier_nom,
                        'fichier_mime': r.fichier_mime,
                        'fichier_data_b64': base64.b64encode(r.fichier_data).decode('ascii') if r.fichier_data else None,
                        'nom_interprete': r.nom_interprete or '',
                        'titre_interprete': r.titre_interprete,
                        'signature_mime': r.signature_mime,
                        'signature_data_b64': base64.b64encode(r.signature_data).decode('ascii') if r.signature_data else None,
                        'auteur_nom': r.created_by,
                    }

                    try:
                        response = requests.post(url, json=payload, params=params, timeout=30)
                    except Exception as e:
                        messages.append(f"structure {mapping.local_structure_id} resultat #{r.id}: échec réseau ({e})")
                        logger.error(f"❌ Push résultat gestion_patients échoué (#{r.id}): {e}")
                        continue

                    if response.status_code == 200:
                        r.source_synced_at = datetime.utcnow()
                        db.session.commit()
                        total_envoyes += 1
                    else:
                        messages.append(f"structure {mapping.local_structure_id} resultat #{r.id}: échec ({response.status_code})")
                        logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur gestion_patients (resultat #{r.id}): {response.status_code} - {response.text[:200]}")

                # ---- Modèles de résultats ----
                modeles = ModeleResultat.query.filter(
                    ModeleResultat.structure_id == mapping.local_structure_id,
                    ModeleResultat.source_app.is_(None),
                    ModeleResultat.source_synced_at.is_(None),
                ).all()

                for m in modeles:
                    payload = {
                        'categorie': 'modele',
                        'source_app': 'ghp',
                        'source_model': 'ModeleResultat',
                        'source_id': m.id,
                        'type_prestation': _type_prestation_vers_analyse(m.type_prestation),
                        'nom': m.nom,
                        'fichier_nom': m.fichier_nom,
                        'fichier_mime': m.fichier_mime,
                        'fichier_data_b64': base64.b64encode(m.fichier_data).decode('ascii') if m.fichier_data else None,
                        'contenu_html': m.contenu_html or '',
                        'auteur_nom': m.created_by,
                    }

                    try:
                        response = requests.post(url, json=payload, params=params, timeout=30)
                    except Exception as e:
                        messages.append(f"structure {mapping.local_structure_id} modele #{m.id}: échec réseau ({e})")
                        logger.error(f"❌ Push modèle gestion_patients échoué (#{m.id}): {e}")
                        continue

                    if response.status_code == 200:
                        m.source_synced_at = datetime.utcnow()
                        db.session.commit()
                        total_envoyes += 1
                    else:
                        messages.append(f"structure {mapping.local_structure_id} modele #{m.id}: échec ({response.status_code})")
                        logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur gestion_patients (modele #{m.id}): {response.status_code} - {response.text[:200]}")

            if total_envoyes == 0 and not messages:
                return {'success': True, 'message': 'Aucun résultat à synchroniser', 'count': 0}

            return {
                'success': True,
                'message': f"✅ {total_envoyes} résultat(s)/modèle(s) synchronisé(s)" + (" — " + "; ".join(messages) if messages else ""),
                'count': total_envoyes,
            }

        except Exception as e:
            logger.error(f"❌ Erreur sync résultats examens -> gestion_patients: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e), 'count': 0}
