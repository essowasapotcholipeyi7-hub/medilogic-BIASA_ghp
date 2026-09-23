"""
Planificateur de tâches de fond pour GHP — nouveau pour cette application
(GHP n'avait jusqu'ici aucun appel HTTP sortant ni thread de fond ; voir
gestion_patients/scheduler.py pour le même principe, déjà en place là-bas
pour la synchro patients/prescriptions/actes/hospitalisations).

Sert uniquement de RATTRAPAGE pour la synchro des résultats
d'analyses/examens et modèles de résultats vers gestion_patients — le push
immédiat se fait à la saisie (voir _pousser_resultat_examen_gestion_patients
/ _pousser_modele_resultat_gestion_patients, app.py) ; ce planificateur
retente toutes les 5 minutes les lignes dont `source_synced_at` est encore
NULL (échec réseau, gestion_patients indisponible un instant...).
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)

scheduler = None


def scheduled_sync_resultats_examens():
    try:
        from tasks import sync_resultats_examens_to_gestion_patients
        result = sync_resultats_examens_to_gestion_patients()
        if result.get('success') and result.get('count'):
            logger.info(f"🔄 Sync résultats examens -> gestion_patients: {result.get('message')}")
    except Exception as e:
        logger.error(f"❌ Erreur sync résultats examens -> gestion_patients: {e}")


def start_scheduler():
    global scheduler
    if scheduler is not None:
        logger.info("ℹ️ Scheduler déjà en cours d'exécution")
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=scheduled_sync_resultats_examens,
        trigger=IntervalTrigger(minutes=5),
        id='sync_resultats_examens_gestion_patients',
        replace_existing=True,
    )
    scheduler.start()
    logger.info("✅ Scheduler GHP démarré — résultats examens -> gestion_patients toutes les 5 minutes")


def stop_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        scheduler = None
        logger.info("⏹️ Scheduler GHP arrêté")
