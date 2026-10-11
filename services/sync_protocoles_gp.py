# -*- coding: utf-8 -*-
"""⭐ Protocoles GHP -> gestion_patients (patron, 2026-10-11 : « tu ajoutes ça
dans les protocoles de GHP et tu le récupères dans gestion_patients, c'est
censé se communiquer »). Le sens gestion_patients -> GHP existait déjà
(/api/protocoles/sync-externe dans app.py) ; ceci est le sens inverse.

Seules les 3 catégories que gestion_patients connaît voyagent : protocole de
soins, ordonnance type, bulletin d'examen. Un document né dans
gestion_patients (source_app='gestion_patients') renvoie ses modifications
vers SON original là-bas (gp_id) au lieu d'en créer un second. Envoi en
tâche de fond, jamais bloquant ; la réception là-bas ne renvoie rien (pas de
boucle)."""
import threading

import requests

CATEGORIES_SYNCHRONISEES = ('protocole_soins', 'ordonnance_type', 'bulletin_examen')


def charge_utile(protocole, action='upsert'):
    """Message à envoyer à gestion_patients pour ce protocole, ou None."""
    if protocole.categorie not in CATEGORIES_SYNCHRONISEES:
        return None
    titre = protocole.titre or 'Sans titre'
    contenu = protocole.contenu or ''
    if protocole.source_app == 'gestion_patients':
        identite = {'gp_id': protocole.source_id, 'gp_model': protocole.source_model}
        # gestion_patients préfixe le titre au contenu : on le retire pour ne pas l'empiler
        if contenu.startswith(titre):
            contenu = contenu[len(titre):].lstrip('\r\n')
    elif protocole.source_app:
        return None
    else:
        identite = {'source_app': 'ghp', 'source_id': protocole.id}
    return {
        'categorie': protocole.categorie,
        **identite,
        'titre': titre,
        'description': protocole.description or '',
        'contenu': contenu,
        'medicaments': protocole.medicaments or [],
        'examens': protocole.examens or [],
        # brouillon / en validation / archivé : pas (ou plus) actif là-bas
        'actif': protocole.statut == 'publie' and action != 'archive',
        'action': action,
        'auteur_nom': protocole.auteur_nom,
    }


def pousser_protocole_gp(protocole, action='upsert'):
    """Envoie le protocole à chaque gestion_patients relié à la structure."""
    from models import StructureMapping
    message = charge_utile(protocole, action)
    if not message:
        return
    cibles = [(m.api_url.rstrip('/'), m.api_key) for m in StructureMapping.query.filter_by(
        local_structure_id=protocole.structure_id, source_name='gestion_patients', actif=True).all()
        if m.api_url and m.api_key]
    if not cibles:
        return

    def envoyer():
        for url, cle in cibles:
            try:
                requests.post(f"{url}/api/protocoles/sync-externe", params={'token': cle}, json=message, timeout=10)
            except Exception as e:
                print(f"⚠️ Envoi protocole vers gestion_patients échoué ({url}) : {e}")

    threading.Thread(target=envoyer, daemon=True).start()
