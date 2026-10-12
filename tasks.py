"""
Tâches de synchro sortante GHP -> gestion_patients (résultats
d'analyses/examens + modèles de résultats) — voir
/api/resultats-examens/sync-externe côté gestion_patients (app.py) pour la
réception, et scheduler.py ici pour le rattrapage périodique. Même forme
que gestion_patients/tasks.py (boucle sur chaque mapping actif, jamais
.first() — une structure GHP peut en théorie avoir plusieurs cibles).

⭐ 2026-10-12 : à l'enregistrement d'un résultat ou d'un modèle, SEUL celui-ci
part, en tâche de fond (pousser_resultat_en_fond / pousser_modele_en_fond) —
avant, la page de saisie attendait le renvoi de TOUS les résultats en attente
de toutes les structures (fichiers compris, jusqu'à 30 s par envoi).
"""
from app import app, db
from models import StructureMapping, ResultatExamen, ModeleResultat, DemandeExamen, Patient
from crypto_helper import dechiffrer_patients_orm
from sqlalchemy import func, or_
import requests
import base64
import threading
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ⭐ Garde-fou de taille pour le transport base64 — voir le commentaire
# équivalent dans gestion_patients/tasks.py (même valeur des deux côtés).
TAILLE_MAX_FICHIER_SYNC = 5 * 1024 * 1024  # 5 Mo


def _type_prestation_vers_analyse(type_prestation):
    return 'examen' if type_prestation == 'examen' else 'analyse'


def _cibles(structure_id=None):
    requete = StructureMapping.query.filter_by(source_name='gestion_patients', actif=True)
    if structure_id is not None:
        requete = requete.filter_by(local_structure_id=structure_id)
    return requete.all()


def _charge_resultat(r):
    """Message pour gestion_patients, ou None si la demande n'existe plus."""
    demande = DemandeExamen.query.get(r.demande_id)
    if not demande:
        return None
    patient = Patient.query.get(demande.patient_id)
    if patient:
        dechiffrer_patients_orm([patient])
    return {
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


def _charge_modele(m):
    return {
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


def _envoyer(mapping, objet, charge, libelle):
    """Envoie un résultat/modèle à un gestion_patients ; marque l'objet synchronisé si OK.
    Retourne None si envoyé, sinon le message d'échec."""
    if objet.fichier_data and len(objet.fichier_data) > TAILLE_MAX_FICHIER_SYNC:
        logger.error(f"⚠️ Fichier trop volumineux pour la synchro ({libelle} #{objet.id}, {len(objet.fichier_data) // 1024} Ko) — non envoyé, à réduire ou transmettre autrement.")
        return f"structure {mapping.local_structure_id} {libelle} #{objet.id}: fichier trop volumineux ({len(objet.fichier_data) // 1024} Ko), non envoyé"
    message = charge(objet)
    if message is None:
        return None
    url = f"{mapping.api_url}/api/resultats-examens/sync-externe"
    try:
        response = requests.post(url, json=message, params={'token': mapping.api_key}, timeout=30)
    except Exception as e:
        logger.error(f"❌ Push {libelle} gestion_patients échoué (#{objet.id}): {e}")
        return f"structure {mapping.local_structure_id} {libelle} #{objet.id}: échec réseau ({e})"
    if response.status_code == 200:
        objet.source_synced_at = datetime.utcnow()
        db.session.commit()
        return None
    logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur gestion_patients ({libelle} #{objet.id}): {response.status_code} - {response.text[:200]}")
    return f"structure {mapping.local_structure_id} {libelle} #{objet.id}: échec ({response.status_code})"


def _pas_trop_gros(modele):
    """Exclut du rattrapage les fichiers trop gros : ils ne partiront jamais,
    inutile de les relire (et de relancer l'envoi) toutes les 5 minutes."""
    return or_(modele.fichier_data.is_(None), func.octet_length(modele.fichier_data) <= TAILLE_MAX_FICHIER_SYNC)


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
            mappings = _cibles()
            if not mappings:
                return {'success': True, 'message': 'Aucune configuration gestion_patients active', 'count': 0}

            total_envoyes = 0
            messages = []

            for mapping in mappings:
                resultats = ResultatExamen.query.filter(
                    ResultatExamen.structure_id == mapping.local_structure_id,
                    ResultatExamen.source_app.is_(None),
                    ResultatExamen.source_synced_at.is_(None),
                    _pas_trop_gros(ResultatExamen),
                ).all()
                for r in resultats:
                    echec = _envoyer(mapping, r, _charge_resultat, 'resultat')
                    if echec:
                        messages.append(echec)
                    elif r.source_synced_at:
                        total_envoyes += 1

                modeles = ModeleResultat.query.filter(
                    ModeleResultat.structure_id == mapping.local_structure_id,
                    ModeleResultat.source_app.is_(None),
                    ModeleResultat.source_synced_at.is_(None),
                    _pas_trop_gros(ModeleResultat),
                ).all()
                for m in modeles:
                    echec = _envoyer(mapping, m, _charge_modele, 'modele')
                    if echec:
                        messages.append(echec)
                    elif m.source_synced_at:
                        total_envoyes += 1

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


def _pousser_en_fond(classe, objet_id, charge, libelle):
    """Envoie UN résultat/modèle (déjà enregistré) en tâche de fond : la page de
    saisie n'attend pas. Un échec est rattrapé par le planificateur (scheduler.py)."""
    def envoyer():
        with app.app_context():
            try:
                objet = classe.query.get(objet_id)
                if objet is None or objet.source_app is not None or objet.source_synced_at is not None:
                    return
                for mapping in _cibles(objet.structure_id):
                    _envoyer(mapping, objet, charge, libelle)
            except Exception as e:
                logger.error(f"⚠️ Push {libelle} #{objet_id} vers gestion_patients échoué (rattrapage par le planificateur) : {e}")
            finally:
                db.session.remove()

    threading.Thread(target=envoyer, daemon=True).start()


def pousser_resultat_en_fond(resultat_id):
    _pousser_en_fond(ResultatExamen, resultat_id, _charge_resultat, 'resultat')


def pousser_modele_en_fond(modele_id):
    _pousser_en_fond(ModeleResultat, modele_id, _charge_modele, 'modele')
