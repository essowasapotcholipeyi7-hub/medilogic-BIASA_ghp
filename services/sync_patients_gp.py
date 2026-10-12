# -*- coding: utf-8 -*-
"""⭐ Patients GHP -> gestion_patients, envoi DIRECT (patron, 2026-10-12 : « les
prescriptions et les RDV de gestion_patients arrivent dans GHP directement par
API — pourquoi pas de même pour les patients, pour réduire les synchronisations
inutiles ? »).

Jusqu'ici gestion_patients venait chercher la liste des patients toutes les
3 minutes. Désormais, dès qu'un patient est créé ou modifié dans GHP
(api_add_patient / api_update_patient), sa fiche part tout de suite vers
chaque gestion_patients relié à la structure (/api/patients/sync-externe).
La recherche périodique de gestion_patients ne reste qu'un filet de sécurité
(patients créés par l'application hors ligne, envoi échoué).

Même principe que sync_protocoles_gp.py : envoi en tâche de fond, jamais
bloquant ; la réception là-bas ne renvoie rien (pas de boucle). Les champs
envoyés sont ceux de /api/sync/patients (app.api_sync_patients)."""
import threading

import requests
from sqlalchemy import text

CHAMPS = ('id, nom, prenom, telephone, adresse, date_naissance, type_assurance, taux_prise_charge, '
          'numero_assure, assurance2_nom, taux_assurance2, numero_assure2, personne_a_prevenir_nom, '
          'personne_a_prevenir_telephone, personne_a_prevenir_relation')


def fiche_pour_gp(p):
    """Une ligne de la table patients -> le format attendu par gestion_patients."""
    from crypto_helper import dechiffrer
    return {
        'ID': p.id,
        'nom': dechiffrer(p.nom) or '',
        'prenom': dechiffrer(p.prenom) or '',
        'telephone': dechiffrer(p.telephone) or '',
        'adresse': p.adresse or '',
        'date_naissance': p.date_naissance.strftime('%Y-%m-%d') if p.date_naissance else None,
        'type_assurance': p.type_assurance or 'non_assure',
        'taux_prise_charge': float(p.taux_prise_charge or 0),
        'numero_assure': p.numero_assure or '',
        'assurance2_nom': p.assurance2_nom or '',
        'taux_assurance2': float(p.taux_assurance2 or 0),
        'numero_assure2': p.numero_assure2 or '',
        'personne_a_prevenir_nom': p.personne_a_prevenir_nom or '',
        'personne_a_prevenir_telephone': p.personne_a_prevenir_telephone or '',
        'personne_a_prevenir_relation': p.personne_a_prevenir_relation or '',
    }


def pousser_patients_gp(structure_id, patient_ids):
    """Envoie ces patients à chaque gestion_patients relié à la structure.

    La fiche est lue DANS la requête en cours (elle voit le patient qui vient
    d'être créé ou modifié, pas encore validé), puis envoyée en tâche de fond
    seulement APRÈS la validation de la transaction (after_commit) : rien ne
    part si l'enregistrement échoue, et jamais une version périmée."""
    from sqlalchemy import event
    from models import db, StructureMapping
    ids = [int(i) for i in patient_ids if i]
    cibles = [(m.api_url.rstrip('/'), m.api_key) for m in StructureMapping.query.filter_by(
        local_structure_id=structure_id, source_name='gestion_patients', actif=True).all()
        if m.api_url and m.api_key]
    if not ids or not cibles:
        return
    lignes = db.session.execute(text(
        f"SELECT {CHAMPS} FROM patients WHERE structure_id = :s AND id = ANY(:ids)"),
        {'s': structure_id, 'ids': ids}).fetchall()
    fiches = [fiche_pour_gp(p) for p in lignes]
    if not fiches:
        return

    def envoyer():
        for url, cle in cibles:
            try:
                requests.post(f"{url}/api/patients/sync-externe", params={'token': cle},
                              json={'patients': fiches}, timeout=15)
            except Exception as e:
                # la recherche périodique de gestion_patients rattrapera ce patient
                print(f"⚠️ Envoi patients vers gestion_patients échoué ({url}) : {e}")

    def apres_validation(_session):
        threading.Thread(target=envoyer, daemon=True).start()

    event.listen(db.session(), 'after_commit', apres_validation, once=True)
