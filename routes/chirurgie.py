"""Proformas d'intervention chirurgicale (patron, 2026-10-09).

Page /chirurgie/proformas : création à partir de la cotation en K
(services/chirurgie_service.py), modèles d'intervention réutilisables,
réglages par défaut de la structure, impression A4, puis transformation
en proforma ordinaire (facture réelle, via le circuit existant
/api/proformas → Convertir) et/ou en hospitalisation (via les API
d'hospitalisation existantes) — ces deux transformations sont pilotées
par la page, ce module ne fait que mémoriser le lien.
"""
from datetime import date

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from sqlalchemy import func

from models import db, ProformaChirurgie, ModeleInterventionChirurgie, ParametrageChirurgie
from services.chirurgie_service import (
    REGLAGES_DEFAUT, fusionner_reglages, normaliser_entree, calculer_proforma, format_k,
)
from sheets_helper import sheets_helper

chirurgie_bp = Blueprint('chirurgie', __name__)

# Réglages de la structure (valeurs du K, pourcentages, chambres, texte NB)
ROLES_REGLAGES = ('admin', 'gestionnaire', 'comptable')


@chirurgie_bp.before_request
def _connexion_requise():
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'Session expirée, reconnectez-vous.'}), 401
        flash('Veuillez vous connecter', 'warning')
        return redirect(url_for('index'))
    sheets_helper.set_structure(session.get('structure_id'))


def _sid():
    return session.get('structure_id')


def _peut_regler():
    return bool(session.get('is_admin')) or session.get('role') in ROLES_REGLAGES


def _reglages(structure_id):
    ligne = ParametrageChirurgie.query.filter_by(structure_id=structure_id).first()
    return fusionner_reglages(ligne.reglages if ligne else {})


def _serialiser(p):
    return {
        'id': p.id,
        'numero': p.numero,
        'numero_affiche': p.numero_affiche,
        'patient_id': p.patient_id,
        'patient_nom': p.patient_nom,
        'service': p.service or '',
        'motif': p.motif or '',
        'actes': p.actes or [],
        'coef_supp': float(p.coef_supp or 0),
        'parametres': p.parametres or {},
        'chambre_nom': p.chambre_nom or '',
        'chambre_prix': float(p.chambre_prix or 0),
        'jours': p.jours or 0,
        'forfaits': p.forfaits or [],
        'lignes': p.lignes or [],
        'total_k': float(p.total_k or 0),
        'total': float(p.total or 0),
        'note': p.note or '',
        'proforma_id': p.proforma_id,
        'hospitalisation_id': p.hospitalisation_id,
        'archive': bool(p.archive),
        'created_by': p.created_by or '',
        'created_at': p.created_at.strftime('%Y-%m-%dT%H:%M:%S') if p.created_at else '',
    }


def _numero_affiche(structure_id, sigle):
    """FPI + date (jjmmaa) + lettre du jour (A, B, ...) [+ /SIGLE], comme
    le document papier (FPI030626A/CCL)."""
    aujourdhui = date.today()
    nb_du_jour = ProformaChirurgie.query.filter(
        ProformaChirurgie.structure_id == structure_id,
        func.date(ProformaChirurgie.created_at) == aujourdhui,
    ).count()
    lettre = chr(ord('A') + nb_du_jour) if nb_du_jour < 26 else str(nb_du_jour + 1)
    numero = f"FPI{aujourdhui:%d%m%y}{lettre}"
    return f"{numero}/{sigle}" if sigle else numero


def _appliquer(p, data, structure_id):
    """Recalcule côté serveur (jamais de total venu du navigateur)."""
    patient_nom = (data.get('patient_nom') or '').strip()
    if not patient_nom:
        return 'Le nom du patient est obligatoire.'
    entree = normaliser_entree(data)
    if not entree['actes']:
        return 'Ajoutez au moins un acte coté en K.'
    if any(not a['nom'] for a in entree['actes']):
        return 'Chaque acte doit avoir un nom.'
    calcul = calculer_proforma(entree)
    p.patient_id = data.get('patient_id') or None
    p.patient_nom = patient_nom
    p.service = (data.get('service') or '').strip()
    p.motif = (data.get('motif') or '').strip()
    p.actes = entree['actes']
    p.coef_supp = entree['coef_supp']
    p.parametres = entree['parametres']
    p.chambre_nom = entree['chambre_nom']
    p.chambre_prix = entree['chambre_prix']
    p.jours = entree['jours']
    p.forfaits = entree['forfaits']
    p.lignes = calcul['lignes']
    p.total_k = calcul['total_k']
    p.total = calcul['total']
    p.note = (data.get('note') or '').strip()
    return None


# ---------------------------------------------------------------- pages

@chirurgie_bp.route('/chirurgie/proformas')
def page_proformas_chirurgie():
    structure_id = _sid()
    modeles = ModeleInterventionChirurgie.query.filter_by(structure_id=structure_id) \
        .order_by(ModeleInterventionChirurgie.nom).all()
    return render_template(
        'chirurgie/proformas_chirurgie.html',
        reglages=_reglages(structure_id),
        modeles=[{'id': m.id, 'nom': m.nom, 'contenu': m.contenu or {}} for m in modeles],
        peut_regler=_peut_regler(),
    )


@chirurgie_bp.route('/chirurgie/proformas/<int:proforma_id>/imprimer')
def imprimer_proforma_chirurgie(proforma_id):
    structure_id = _sid()
    p = ProformaChirurgie.query.filter_by(id=proforma_id, structure_id=structure_id).first()
    if not p:
        flash('Proforma introuvable.', 'warning')
        return redirect(url_for('chirurgie.page_proformas_chirurgie'))
    reglages = _reglages(structure_id)
    calcul = calculer_proforma(normaliser_entree(_serialiser(p)))
    try:
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), {})
    except Exception as e:
        print(f"⚠️ Impression proforma chirurgie (structure): {e}")
        info = {}
    return render_template(
        'chirurgie/proforma_chirurgie_print.html',
        p=p, calcul=calcul, reglages=reglages, format_k=format_k,
        fmt=lambda n: '{:,.0f}'.format(n or 0).replace(',', ' '),
        structure_nom=info.get('nom') or session.get('structure_nom') or 'Medilogic-GHP',
        structure_entete_a4=info.get('entete_a4', ''),
        structure_adresse=info.get('adresse', ''),
        structure_telephone=info.get('telephone', ''),
        structure_email=info.get('email', ''),
        structure_logo=info.get('logo_url', ''),
    )


# ---------------------------------------------------------------- API

@chirurgie_bp.route('/api/chirurgie/calculer', methods=['POST'])
def api_calculer():
    """Aperçu en direct du formulaire (même calcul que l'enregistrement)."""
    calcul = calculer_proforma(normaliser_entree(request.json or {}))
    return jsonify({'success': True, **calcul})


@chirurgie_bp.route('/api/chirurgie/proformas')
def api_liste():
    structure_id = _sid()
    archive = request.args.get('archive') == '1'
    q = ProformaChirurgie.query.filter_by(structure_id=structure_id)
    q = q.filter(ProformaChirurgie.archive.is_(True)) if archive else \
        q.filter((ProformaChirurgie.archive.is_(False)) | (ProformaChirurgie.archive.is_(None)))
    return jsonify({'success': True, 'data': [_serialiser(p) for p in q.order_by(ProformaChirurgie.id.desc()).all()]})


@chirurgie_bp.route('/api/chirurgie/proformas/<int:proforma_id>')
def api_detail(proforma_id):
    p = ProformaChirurgie.query.filter_by(id=proforma_id, structure_id=_sid()).first()
    if not p:
        return jsonify({'success': False, 'error': 'Proforma introuvable'}), 404
    return jsonify({'success': True, 'data': _serialiser(p)})


@chirurgie_bp.route('/api/chirurgie/proformas', methods=['POST'])
def api_creer():
    structure_id = _sid()
    data = request.json or {}
    try:
        p = ProformaChirurgie(structure_id=structure_id,
                              created_by=session.get('user_name', ''))
        erreur = _appliquer(p, data, structure_id)
        if erreur:
            return jsonify({'success': False, 'error': erreur}), 400
        # Verrou sur la structure : deux créations simultanées ne prennent
        # pas le même numéro.
        db.session.execute(db.text('SELECT pg_advisory_xact_lock(:cle)'),
                           {'cle': 910000 + int(structure_id)})
        dernier = db.session.query(func.max(ProformaChirurgie.numero)) \
            .filter_by(structure_id=structure_id).scalar() or 0
        p.numero = dernier + 1
        p.numero_affiche = _numero_affiche(structure_id, _reglages(structure_id).get('sigle', ''))
        db.session.add(p)
        db.session.commit()
        return jsonify({'success': True, 'data': _serialiser(p)})
    except Exception as e:
        db.session.rollback()
        print(f"❌ Création proforma chirurgie: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@chirurgie_bp.route('/api/chirurgie/proformas/<int:proforma_id>', methods=['PUT'])
def api_modifier(proforma_id):
    structure_id = _sid()
    p = ProformaChirurgie.query.filter_by(id=proforma_id, structure_id=structure_id).first()
    if not p:
        return jsonify({'success': False, 'error': 'Proforma introuvable'}), 404
    try:
        erreur = _appliquer(p, request.json or {}, structure_id)
        if erreur:
            return jsonify({'success': False, 'error': erreur}), 400
        db.session.commit()
        return jsonify({'success': True, 'data': _serialiser(p)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@chirurgie_bp.route('/api/chirurgie/proformas/<int:proforma_id>/archiver', methods=['POST'])
def api_archiver(proforma_id):
    p = ProformaChirurgie.query.filter_by(id=proforma_id, structure_id=_sid()).first()
    if not p:
        return jsonify({'success': False, 'error': 'Proforma introuvable'}), 404
    p.archive = bool((request.json or {}).get('archive', True))
    db.session.commit()
    return jsonify({'success': True})


@chirurgie_bp.route('/api/chirurgie/proformas/<int:proforma_id>/lien', methods=['POST'])
def api_lien(proforma_id):
    """Mémorise la proforma ordinaire et/ou l'hospitalisation créées depuis
    cette proforma chirurgicale (et le patient, s'il vient d'être choisi)."""
    p = ProformaChirurgie.query.filter_by(id=proforma_id, structure_id=_sid()).first()
    if not p:
        return jsonify({'success': False, 'error': 'Proforma introuvable'}), 404
    data = request.json or {}
    if data.get('proforma_id'):
        p.proforma_id = int(data['proforma_id'])
    if data.get('hospitalisation_id'):
        p.hospitalisation_id = int(data['hospitalisation_id'])
    if data.get('patient_id') and not p.patient_id:
        p.patient_id = int(data['patient_id'])
    db.session.commit()
    return jsonify({'success': True, 'data': _serialiser(p)})


@chirurgie_bp.route('/api/chirurgie/modeles', methods=['POST'])
def api_enregistrer_modele():
    structure_id = _sid()
    data = request.json or {}
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'success': False, 'error': 'Donnez un nom au modèle.'}), 400
    entree = normaliser_entree(data.get('contenu') or {})
    contenu = dict(entree, service=(data.get('contenu') or {}).get('service', ''),
                   motif=(data.get('contenu') or {}).get('motif', ''))
    m = ModeleInterventionChirurgie.query.filter_by(structure_id=structure_id, nom=nom).first()
    if m:
        m.contenu = contenu
    else:
        m = ModeleInterventionChirurgie(structure_id=structure_id, nom=nom, contenu=contenu,
                                        created_by=session.get('user_name', ''))
        db.session.add(m)
    db.session.commit()
    return jsonify({'success': True, 'data': {'id': m.id, 'nom': m.nom, 'contenu': m.contenu}})


@chirurgie_bp.route('/api/chirurgie/modeles/<int:modele_id>', methods=['DELETE'])
def api_supprimer_modele(modele_id):
    m = ModeleInterventionChirurgie.query.filter_by(id=modele_id, structure_id=_sid()).first()
    if not m:
        return jsonify({'success': False, 'error': 'Modèle introuvable'}), 404
    db.session.delete(m)
    db.session.commit()
    return jsonify({'success': True})


@chirurgie_bp.route('/api/chirurgie/reglages', methods=['PUT'])
def api_reglages():
    if not _peut_regler():
        return jsonify({'success': False, 'error': "Réservé à l'administrateur ou au gestionnaire."}), 403
    structure_id = _sid()
    data = request.json or {}
    entree = normaliser_entree({'parametres': data.get('parametres') or {},
                                'forfaits': data.get('forfaits') or []})
    chambres = []
    for c in data.get('chambres') or []:
        nom = (c.get('nom') or '').strip()
        if nom:
            chambres.append({'nom': nom, 'prix': normaliser_entree({'chambre_prix': c.get('prix')})['chambre_prix']})
    reglages = {
        'parametres': entree['parametres'],
        'forfaits': entree['forfaits'],
        'chambres': chambres,
        'service': (data.get('service') or '').strip() or REGLAGES_DEFAUT['service'],
        'note': (data.get('note') or '').strip() or REGLAGES_DEFAUT['note'],
        'ville': (data.get('ville') or '').strip() or REGLAGES_DEFAUT['ville'],
        'sigle': (data.get('sigle') or '').strip(),
        'signature': (data.get('signature') or '').strip() or REGLAGES_DEFAUT['signature'],
    }
    ligne = ParametrageChirurgie.query.filter_by(structure_id=structure_id).first()
    if ligne:
        ligne.reglages = reglages
    else:
        db.session.add(ParametrageChirurgie(structure_id=structure_id, reglages=reglages))
    db.session.commit()
    return jsonify({'success': True, 'reglages': fusionner_reglages(reglages)})
