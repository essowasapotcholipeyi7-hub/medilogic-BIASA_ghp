# -*- coding: utf-8 -*-
"""Journal des tentatives de connexion (patron, 2026-10-16 : « un collaborateur de la clinique 12
se fait bloquer, il dit que ce n'est pas lui — qui fait ça ? »). Chaque tentative (formulaire,
code QR, empreinte, administration globale) est notée avec l'heure, le compte visé, le résultat,
l'adresse IP et l'appareil, et l'administrateur global la consulte dans /admin_global/connexions.
N'empêche JAMAIS une connexion : toute erreur d'écriture est avalée."""
from datetime import datetime

LIBELLES_RESULTAT = {
    'reussie': 'Connexion réussie',
    'mot_de_passe_incorrect': 'Mot de passe incorrect',
    'blocage_declenche': 'Mot de passe incorrect — compte bloqué 10 min',
    'compte_bloque': 'Refusée : compte déjà bloqué',
    'email_inconnu': 'Email inconnu',
    'structure_inactive': 'Refusée : structure non active',
}
RESULTATS_ECHEC = ('mot_de_passe_incorrect', 'blocage_declenche', 'compte_bloque', 'email_inconnu')

LIBELLES_TYPE = {
    'utilisateur': 'Utilisateur',
    'structure': 'Compte structure',
    'admin_global': 'Administration globale',
    'qr': 'Code QR',
    'empreinte': 'Empreinte / visage',
}


def adresse_ip(requete):
    """Adresse du visiteur. Derrière le proxy de Render, la vraie adresse est la première de
    X-Forwarded-For (remote_addr serait celle du proxy)."""
    transmise = (requete.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return (transmise or requete.remote_addr or '')[:64]


def resumer_appareil(user_agent):
    """'Chrome sur Android', 'Edge sur Windows'… — lisible pour l'administrateur."""
    ua = (user_agent or '').lower()
    if not ua:
        return 'Inconnu'
    if 'android' in ua:
        systeme = 'Android'
    elif 'iphone' in ua or 'ipad' in ua:
        systeme = 'iPhone / iPad'
    elif 'windows' in ua:
        systeme = 'Windows'
    elif 'mac os' in ua or 'macintosh' in ua:
        systeme = 'Mac'
    elif 'linux' in ua:
        systeme = 'Linux'
    else:
        systeme = 'système inconnu'
    if 'edg/' in ua:
        navigateur = 'Edge'
    elif 'opr/' in ua or 'opera' in ua:
        navigateur = 'Opera'
    elif 'samsungbrowser' in ua:
        navigateur = 'Samsung Internet'
    elif 'firefox' in ua or 'fxios' in ua:
        navigateur = 'Firefox'
    elif 'chrome' in ua or 'crios' in ua:
        navigateur = 'Chrome'
    elif 'safari' in ua:
        navigateur = 'Safari'
    elif 'python' in ua or 'curl' in ua or 'bot' in ua or 'wget' in ua:
        navigateur = 'Programme automatique'
    else:
        navigateur = 'Navigateur inconnu'
    return f'{navigateur} sur {systeme}'


def journaliser(resultat, email=None, structure_id=None, compte_nom=None, type_compte=None):
    """Note une tentative. À appeler dans une requête Flask ; n'échoue jamais."""
    try:
        from flask import request
        from models import db, TentativeConnexion
        ua = request.headers.get('User-Agent', '') if request else ''
        db.session.add(TentativeConnexion(
            date=datetime.utcnow(),
            email=(email or '').strip().lower()[:255] or None,
            structure_id=int(structure_id) if str(structure_id or '').isdigit() else None,
            compte_nom=(compte_nom or '')[:255] or None,
            type_compte=type_compte,
            resultat=resultat,
            ip=adresse_ip(request) if request else None,
            appareil=resumer_appareil(ua),
            user_agent=(ua or '')[:400] or None,
        ))
        db.session.commit()
    except Exception as e:
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass
        print(f"⚠️ Journal de connexion non écrit : {e}")
