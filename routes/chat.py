# ============================================================
# ROUTES POUR LE CHAT INTERNE (salon commun + messages privés)
# ============================================================
# Contrairement aux autres blueprints ajoutés cette session
# (comptabilite, rh, journal, protocoles), AUCUN filtre de rôle ici —
# le chat est un outil de communication générale, ouvert à tout le
# personnel connecté de la structure. Seule la connexion est exigée.

from functools import wraps
from datetime import datetime

from flask import Blueprint, request, jsonify, session
from sqlalchemy import or_, and_

from models import db, MessageChat, ChatDernierVu
from sheets_helper import sheets_helper

chat_bp = Blueprint('chat', __name__, url_prefix='/chat')

LONGUEUR_MAX_MESSAGE = 2000
LIMITE_HISTORIQUE = 50


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or 'structure_id' not in session:
            return jsonify({'error': 'Non autorisé'}), 401
        # /api/contacts lit Google Sheets (struct_N_users) — sheets_helper
        # est un singleton global dont le préfixe de structure doit être
        # posé avant chaque lecture, comme le fait déjà login_required
        # dans app.py pour toutes les autres routes.
        sheets_helper.set_structure(session.get('structure_id'))
        return f(*args, **kwargs)
    return decorated_function


def _parse_since(valeur):
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur)
    except ValueError:
        return None


def _serialiser(m):
    return {
        'id': m.id,
        'expediteur_id': m.expediteur_id,
        'expediteur_nom': m.expediteur_nom,
        'destinataire_id': m.destinataire_id,
        'contenu': m.contenu,
        'date_envoi': m.date_envoi.isoformat() if m.date_envoi else None,
        'supprime': m.supprime,
        'de_moi': m.expediteur_id == session.get('user_id'),
    }


def _marquer_vu(structure_id, utilisateur_id, fil):
    ligne = ChatDernierVu.query.filter_by(
        structure_id=structure_id, utilisateur_id=utilisateur_id, fil=fil
    ).first()
    if ligne:
        ligne.date_dernier_vu = datetime.utcnow()
    else:
        db.session.add(ChatDernierVu(
            structure_id=structure_id, utilisateur_id=utilisateur_id,
            fil=fil, date_dernier_vu=datetime.utcnow(),
        ))
    db.session.commit()


def _dernier_vu(structure_id, utilisateur_id, fil):
    ligne = ChatDernierVu.query.filter_by(
        structure_id=structure_id, utilisateur_id=utilisateur_id, fil=fil
    ).first()
    return ligne.date_dernier_vu if ligne else None


# ============================================================
# CONTACTS (pour la liste de discussion privée)
# ============================================================

@chat_bp.route('/api/contacts', methods=['GET'])
@login_required
def api_contacts():
    structure_id = session.get('structure_id')
    moi = session.get('user_id')

    users = sheets_helper.get_all_records('users')
    contacts = [
        u for u in users
        if str(u.get('structure_id')) == str(structure_id)
        and str(u.get('ID')) != str(moi)
        and u.get('actif', 'oui') == 'oui'
    ]

    resultat = []
    for u in contacts:
        autre_id = u.get('ID')
        dernier_vu = _dernier_vu(structure_id, moi, str(autre_id))
        q = MessageChat.query.filter(
            MessageChat.structure_id == structure_id,
            MessageChat.expediteur_id == autre_id,
            MessageChat.destinataire_id == moi,
        )
        if dernier_vu:
            q = q.filter(MessageChat.date_envoi > dernier_vu)
        resultat.append({
            'id': autre_id,
            'nom': u.get('nom'),
            'role': u.get('role'),
            'non_lus': q.count(),
        })
    return jsonify({'success': True, 'contacts': resultat})


# ============================================================
# SALON COMMUN
# ============================================================

@chat_bp.route('/api/salon', methods=['GET'])
@login_required
def api_salon_liste():
    structure_id = session.get('structure_id')
    since = _parse_since(request.args.get('since'))

    q = MessageChat.query.filter(
        MessageChat.structure_id == structure_id,
        MessageChat.destinataire_id.is_(None),
    )
    if since:
        q = q.filter(MessageChat.date_envoi > since).order_by(MessageChat.date_envoi.asc())
        messages = q.all()
    else:
        messages = q.order_by(MessageChat.date_envoi.desc()).limit(LIMITE_HISTORIQUE).all()
        messages.reverse()

    return jsonify({'success': True, 'messages': [_serialiser(m) for m in messages]})


@chat_bp.route('/api/salon', methods=['POST'])
@login_required
def api_salon_envoyer():
    data = request.json or {}
    contenu = (data.get('contenu') or '').strip()[:LONGUEUR_MAX_MESSAGE]
    if not contenu:
        return jsonify({'success': False, 'error': 'Message vide'}), 400

    m = MessageChat(
        structure_id=session.get('structure_id'),
        expediteur_id=session.get('user_id'),
        expediteur_nom=session.get('user_name', 'Utilisateur'),
        destinataire_id=None,
        contenu=contenu,
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({'success': True, 'message': _serialiser(m)})


# ============================================================
# MESSAGES PRIVÉS
# ============================================================

@chat_bp.route('/api/dm/<int:autre_id>', methods=['GET'])
@login_required
def api_dm_liste(autre_id):
    structure_id = session.get('structure_id')
    moi = session.get('user_id')
    since = _parse_since(request.args.get('since'))

    q = MessageChat.query.filter(
        MessageChat.structure_id == structure_id,
        or_(
            and_(MessageChat.expediteur_id == moi, MessageChat.destinataire_id == autre_id),
            and_(MessageChat.expediteur_id == autre_id, MessageChat.destinataire_id == moi),
        ),
    )
    if since:
        q = q.filter(MessageChat.date_envoi > since).order_by(MessageChat.date_envoi.asc())
        messages = q.all()
    else:
        messages = q.order_by(MessageChat.date_envoi.desc()).limit(LIMITE_HISTORIQUE).all()
        messages.reverse()

    return jsonify({'success': True, 'messages': [_serialiser(m) for m in messages]})


@chat_bp.route('/api/dm/<int:autre_id>', methods=['POST'])
@login_required
def api_dm_envoyer(autre_id):
    data = request.json or {}
    contenu = (data.get('contenu') or '').strip()[:LONGUEUR_MAX_MESSAGE]
    if not contenu:
        return jsonify({'success': False, 'error': 'Message vide'}), 400

    destinataire_nom = data.get('destinataire_nom', '')
    m = MessageChat(
        structure_id=session.get('structure_id'),
        expediteur_id=session.get('user_id'),
        expediteur_nom=session.get('user_name', 'Utilisateur'),
        destinataire_id=autre_id,
        destinataire_nom=destinataire_nom,
        contenu=contenu,
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({'success': True, 'message': _serialiser(m)})


# ============================================================
# VU / NON-LUS
# ============================================================

@chat_bp.route('/api/vu', methods=['POST'])
@login_required
def api_marquer_vu():
    data = request.json or {}
    fil = str(data.get('fil', '')).strip()
    if not fil:
        return jsonify({'success': False, 'error': 'Fil manquant'}), 400
    _marquer_vu(session.get('structure_id'), session.get('user_id'), fil)
    return jsonify({'success': True})


@chat_bp.route('/api/non-lus', methods=['GET'])
@login_required
def api_non_lus():
    structure_id = session.get('structure_id')
    moi = session.get('user_id')

    dernier_vu_salon = _dernier_vu(structure_id, moi, 'salon')
    q_salon = MessageChat.query.filter(
        MessageChat.structure_id == structure_id,
        MessageChat.destinataire_id.is_(None),
        MessageChat.expediteur_id != moi,
    )
    if dernier_vu_salon:
        q_salon = q_salon.filter(MessageChat.date_envoi > dernier_vu_salon)
    non_lus_salon = q_salon.count()

    dm_non_lus = {}
    q_dm = MessageChat.query.filter(
        MessageChat.structure_id == structure_id,
        MessageChat.destinataire_id == moi,
    ).all()
    par_expediteur = {}
    for m in q_dm:
        par_expediteur.setdefault(m.expediteur_id, []).append(m)
    for autre_id, msgs in par_expediteur.items():
        dernier_vu = _dernier_vu(structure_id, moi, str(autre_id))
        n = sum(1 for m in msgs if not dernier_vu or m.date_envoi > dernier_vu)
        if n:
            dm_non_lus[autre_id] = n

    total = non_lus_salon + sum(dm_non_lus.values())
    return jsonify({'success': True, 'total': total, 'salon': non_lus_salon, 'dm': dm_non_lus})


# ============================================================
# SUPPRESSION (par l'auteur uniquement)
# ============================================================

@chat_bp.route('/api/messages/<int:message_id>', methods=['DELETE'])
@login_required
def api_supprimer_message(message_id):
    structure_id = session.get('structure_id')
    m = MessageChat.query.filter_by(id=message_id, structure_id=structure_id).first()
    if not m:
        return jsonify({'success': False, 'error': 'Introuvable'}), 404
    if m.expediteur_id != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Vous ne pouvez supprimer que vos propres messages'}), 403

    m.supprime = True
    m.contenu = '[message supprimé]'
    db.session.commit()
    return jsonify({'success': True})
