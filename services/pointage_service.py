# services/pointage_service.py
"""
Pointage par empreinte digitale, via WebAuthn (norme du navigateur qui
pilote les capteurs d'empreinte/Windows Hello/Face ID — utilisée pour se
connecter sans mot de passe sur beaucoup de sites). L'appli ne voit jamais
l'empreinte elle-même (elle ne quitte jamais l'appareil) : le navigateur
renvoie juste une preuve cryptographique signée par le capteur, que ce
module vérifie.

Important : WebAuthn n'est autorisé par les navigateurs que sur
"localhost" ou en HTTPS — pas sur une adresse IP locale en http:// simple.
Sur un poste de travail (réception, accueil...), le pointage doit donc se
faire via http://localhost:<port>, ou via le site déployé en HTTPS.

Deux cérémonies :
  - Enregistrement (une fois par employé/appareil) : options_enregistrement()
    puis verifier_enregistrement().
  - Pointage (au quotidien) : options_pointage() puis verifier_pointage(),
    qui identifie l'employé À PARTIR de l'empreinte (pas de saisie
    préalable) et enregistre arrivée ou départ selon ce qui manque pour
    la journée en cours.

Complément : pointage par reconnaissance FACIALE (voir plus bas,
enregistrer_visage()/identifier_par_visage()) — utile quand le poste n'a
pas de capteur d'empreinte/Windows Hello compatible, juste une webcam
standard. La détection/le calcul du visage se font entièrement dans le
navigateur (face-api.js) : la photo ne quitte jamais l'appareil, seul un
descripteur mathématique (128 nombres) est envoyé au serveur, comparé par
distance euclidienne aux descripteurs déjà enregistrés de la structure.
"""

import base64
import math
from datetime import datetime, date, timedelta

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from models import (db, Employe, EmpreinteEmploye, ParametragePointage, Pointage, VisageEmploye,
                    Conge, Permission, JourFerie, TentativePointage)
from utils.regles_absences import absent_ce_jour

RP_NAME = "Medilogic — Pointage"


def _rp_id_et_origin(request):
    """Dérive le rp_id (domaine) et l'origin attendus depuis la requête —
    fonctionne aussi bien en local (localhost) qu'en production (Render).

    request.scheme n'est pas fiable derrière le proxy de Render (pas de
    ProxyFix configuré : Flask voit la connexion interne en http même
    quand le visiteur est en https) — on force https dès que ce n'est pas
    une adresse locale, plutôt que de se fier à l'en-tête."""
    rp_id = request.host.split(':')[0]
    est_local = rp_id in ('localhost', '127.0.0.1', '::1')
    scheme = request.scheme if est_local else 'https'
    origin = f"{scheme}://{request.host}"
    return rp_id, origin


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode('ascii'))


# ----------------------------------------------------------------------
# Enregistrement d'une empreinte
# ----------------------------------------------------------------------

def options_enregistrement(request, employe):
    """Prépare la cérémonie WebAuthn de création d'une empreinte pour un employé."""
    rp_id, _ = _rp_id_et_origin(request)

    existantes = EmpreinteEmploye.query.filter_by(employe_id=employe.id, actif=True).all()
    exclude = [
        PublicKeyCredentialDescriptor(id=_unb64(e.credential_id))
        for e in existantes
    ]

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=str(employe.id).encode('utf-8'),
        user_name=employe.matricule or f"employe-{employe.id}",
        user_display_name=f"{employe.prenom or ''} {employe.nom}".strip(),
        authenticator_selection=AuthenticatorSelectionCriteria(
            # ⭐ Sans authenticator_attachment, le navigateur propose AUSSI
            # une "clé de sécurité" externe (USB/FIDO2) en plus du capteur
            # intégré — c'est cette boîte de dialogue "clé d'accès" que le
            # personnel voit et ne sait pas remplir. PLATFORM force le
            # capteur intégré de l'appareil (empreinte Windows Hello,
            # Touch ID, capteur Android...), seule option pertinente pour
            # une borne de pointage.
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=exclude,
    )
    challenge_b64 = _b64(options.challenge)
    return webauthn.options_to_json(options), challenge_b64


def verifier_enregistrement(request, employe, credential_json, challenge_b64, libelle_appareil=None):
    """Vérifie la réponse du navigateur et enregistre la nouvelle empreinte."""
    rp_id, origin = _rp_id_et_origin(request)

    verification = webauthn.verify_registration_response(
        credential=credential_json,
        expected_challenge=_unb64(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_verification=True,
    )

    empreinte = EmpreinteEmploye(
        structure_id=employe.structure_id,
        employe_id=employe.id,
        credential_id=_b64(verification.credential_id),
        public_key=_b64(verification.credential_public_key),
        sign_count=verification.sign_count,
        libelle_appareil=libelle_appareil or request.host,
    )
    db.session.add(empreinte)
    db.session.commit()
    return empreinte


# ----------------------------------------------------------------------
# Pointage (arrivée / départ)
# ----------------------------------------------------------------------

def options_pointage(request, structure_id):
    """Prépare la cérémonie WebAuthn de pointage : on ne sait pas encore
    QUI va poser le doigt, donc la liste des empreintes autorisées couvre
    tous les employés actifs de la structure — l'identification se fait
    ensuite via le credential_id renvoyé par le capteur."""
    rp_id, _ = _rp_id_et_origin(request)

    empreintes = (
        EmpreinteEmploye.query
        .join(Employe, Employe.id == EmpreinteEmploye.employe_id)
        .filter(EmpreinteEmploye.structure_id == structure_id,
                EmpreinteEmploye.actif == True,  # noqa: E712
                Employe.statut.in_(Employe.STATUTS_EN_SERVICE))
        .all()
    )
    if not empreintes:
        return None, None

    allow = [PublicKeyCredentialDescriptor(id=_unb64(e.credential_id)) for e in empreintes]
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_b64 = _b64(options.challenge)
    return webauthn.options_to_json(options), challenge_b64


def verifier_pointage(request, structure_id, credential_json, challenge_b64):
    """Vérifie l'empreinte, identifie l'employé, et enregistre l'arrivée ou
    le départ du jour selon ce qui manque déjà. Retourne un dict prêt à
    renvoyer en JSON, ou lève ValueError avec un message utilisateur."""
    import json
    rp_id, origin = _rp_id_et_origin(request)

    cred_dict = json.loads(credential_json) if isinstance(credential_json, str) else credential_json
    credential_id_b64 = cred_dict.get('id') or cred_dict.get('rawId')
    if not credential_id_b64:
        raise ValueError("Réponse du capteur incomplète.")

    # L'id renvoyé par le navigateur est en base64url ; on le convertit au
    # même format que celui stocké (base64 standard) pour la recherche.
    raw_id = webauthn.base64url_to_bytes(credential_id_b64)
    empreinte = EmpreinteEmploye.query.filter_by(
        credential_id=_b64(raw_id), structure_id=structure_id, actif=True
    ).first()
    if not empreinte:
        raise ValueError("Empreinte non reconnue pour cette structure.")

    verification = webauthn.verify_authentication_response(
        credential=credential_json,
        expected_challenge=_unb64(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=_unb64(empreinte.public_key),
        credential_current_sign_count=empreinte.sign_count,
        require_user_verification=True,
    )
    empreinte.sign_count = verification.new_sign_count
    empreinte.derniere_utilisation = datetime.utcnow()

    employe = Employe.query.get(empreinte.employe_id)
    resultat = enregistrer_pointage(employe, methode='empreinte')
    db.session.commit()
    resultat['employe_nom'] = f"{employe.prenom or ''} {employe.nom}".strip()
    return resultat


# ----------------------------------------------------------------------
# Logique métier du pointage (arrivée/départ, retard, durée) — appelée
# aussi bien par le flux empreinte que par une saisie manuelle (admin).
# ----------------------------------------------------------------------

class AbsenceEnCours(ValueError):
    """Pointage refusé : l'employé est en congé ou en permission ce jour-là."""


LIBELLES_CONGE = {'annuel': 'congé annuel', 'maladie': 'congé maladie', 'maternite': 'congé de maternité',
                  'paternite': 'congé de paternité', 'sans_solde': 'congé sans solde',
                  'exceptionnel': 'congé exceptionnel'}


def _jj(d):
    return d.strftime('%d/%m/%Y')


def absence_du_jour(employe, jour):
    """Congé APPROUVÉ (du début à la veille de la reprise) ou permission
    approuvée d'une ou plusieurs journées qui couvre `jour` — None sinon.
    Les permissions de quelques heures ne bloquent pas le pointage (l'employé
    vient travailler avant ou après)."""
    for c in Conge.query.filter(Conge.employe_id == employe.id, Conge.statut == 'approuve',
                                Conge.date_debut <= jour).order_by(Conge.date_debut.desc()).all():
        if absent_ce_jour(jour, c.date_debut, c.date_fin, c.date_reprise):
            periode = f"du {_jj(c.date_debut)} au {_jj(c.date_fin)}"
            if c.date_reprise:
                periode += f" (reprise le {_jj(c.date_reprise)})"
            return {'type': 'conge', 'id': c.id, 'libelle': LIBELLES_CONGE.get(c.type_conge, 'congé'),
                    'periode': periode, 'reference': c.demande_reference}
    p = Permission.query.filter(Permission.employe_id == employe.id, Permission.statut == 'approuve',
                                Permission.type_permission != 'heures',
                                Permission.date_debut <= jour, Permission.date_fin >= jour).first()
    if p:
        periode = f"du {_jj(p.date_debut)} au {_jj(p.date_fin)}" if p.date_fin != p.date_debut else f"le {_jj(p.date_debut)}"
        return {'type': 'permission', 'id': p.id, 'libelle': 'permission', 'periode': periode,
                'reference': p.demande_reference}
    return None


def _signaler_tentative(employe, absence, methode, maintenant):
    """Garde la trace du passage pour la RH (une ligne par jour, compteur) et
    COMMIT tout de suite : l'appelant annule la transaction sur l'erreur."""
    t = TentativePointage.query.filter_by(employe_id=employe.id, date_jour=maintenant.date()).first()
    if t:
        t.nombre = (t.nombre or 1) + 1
        t.vue_par, t.vue_le = None, None      # nouveau passage : à revoir
    else:
        t = TentativePointage(structure_id=employe.structure_id, employe_id=employe.id,
                              date_jour=maintenant.date(), premiere_heure=maintenant.time(), nombre=1)
        db.session.add(t)
    t.derniere_heure = maintenant.time()
    t.methode = methode
    t.absence_type, t.absence_id = absence['type'], absence['id']
    t.motif = f"En {absence['libelle']} {absence['periode']}"[:255]
    db.session.commit()


def enregistrer_pointage(employe, methode='empreinte', maintenant=None):
    """Enregistre l'arrivée si l'employé n'a pas encore pointé aujourd'hui,
    sinon le départ. Calcule retard et durée travaillée selon le
    paramétrage de la structure. Ne fait PAS le commit (laissé à l'appelant),
    sauf pour signaler à la RH le passage d'un employé en congé/permission."""
    maintenant = maintenant or datetime.now()
    aujourdhui = maintenant.date()
    heure_actuelle = maintenant.time()
    nom = f"{employe.prenom or ''} {employe.nom}".strip()

    if employe.date_depart and aujourdhui > employe.date_depart:
        raise ValueError(f"{nom} a quitté la structure le {_jj(employe.date_depart)} : pointage impossible.")

    # ⭐ Patron (2026-10-10) : en congé ou en permission, on ne pointe pas.
    absence = absence_du_jour(employe, aujourdhui)
    if absence:
        if methode == 'manuel':
            raise ValueError(f"{nom} est en {absence['libelle']} {absence['periode']} : pointage refusé. "
                             "S'il a repris plus tôt, corrigez d'abord la fin de l'absence (ou la date de reprise).")
        _signaler_tentative(employe, absence, methode, maintenant)
        raise AbsenceEnCours(
            f"{employe.prenom or nom}, vous êtes en {absence['libelle']} {absence['periode']}. "
            "Vous n'êtes pas censé(e) pointer aujourd'hui : rien n'a été enregistré. "
            "Votre passage a été signalé au service RH.")

    param = ParametragePointage.get_ou_creer(employe.structure_id)

    pointage = Pointage.query.filter_by(employe_id=employe.id, date_jour=aujourdhui).first()

    if not pointage or not pointage.heure_arrivee:
        # Arrivée
        if not pointage:
            pointage = Pointage(structure_id=employe.structure_id, employe_id=employe.id, date_jour=aujourdhui)
            db.session.add(pointage)

        pointage.heure_arrivee = heure_actuelle
        pointage.methode_arrivee = methode

        minutes_actuelles = heure_actuelle.hour * 60 + heure_actuelle.minute
        minutes_debut = param.heure_debut.hour * 60 + param.heure_debut.minute
        retard = minutes_actuelles - minutes_debut - param.tolerance_retard_minutes
        if retard > 0:
            pointage.statut_arrivee = 'retard'
            pointage.retard_minutes = retard
        else:
            pointage.statut_arrivee = 'a_l_heure'
            pointage.retard_minutes = 0

        return {
            'type': 'arrivee',
            'heure': heure_actuelle.strftime('%H:%M'),
            'statut': pointage.statut_arrivee,
            'retard_minutes': pointage.retard_minutes,
        }

    if pointage.heure_depart:
        raise ValueError("Arrivée ET départ déjà enregistrés aujourd'hui pour cet employé.")

    # Départ
    pointage.heure_depart = heure_actuelle
    pointage.methode_depart = methode

    minutes_actuelles = heure_actuelle.hour * 60 + heure_actuelle.minute
    minutes_fin = param.heure_fin.hour * 60 + param.heure_fin.minute
    pointage.depart_anticipe = minutes_actuelles < minutes_fin

    minutes_arrivee = pointage.heure_arrivee.hour * 60 + pointage.heure_arrivee.minute
    pointage.duree_travaillee_minutes = max(0, minutes_actuelles - minutes_arrivee)

    return {
        'type': 'depart',
        'heure': heure_actuelle.strftime('%H:%M'),
        'depart_anticipe': pointage.depart_anticipe,
        'duree_travaillee_minutes': pointage.duree_travaillee_minutes,
    }


def resume_periode(structure_id, date_debut, date_fin, employe_id=None):
    """Récapitulatif pointages sur une période : jours travaillés, retards,
    absences (jours ouvrés du paramétrage sans aucune ligne de pointage),
    heures totales — par employé. Utile pour le tableau du mois et, plus
    tard, comme base d'éventuelles primes/retenues de paie.

    ⭐ Ne sont PAS des absences (avant : comptées, et retenues sur le salaire
    si la retenue « absences (pointage) » est activée) : les jours de congé
    ou de permission approuvés (« justifiés »), les jours fériés déclarés,
    les jours avant l'embauche ou après le départ."""
    from sqlalchemy import or_
    param = ParametragePointage.get_ou_creer(structure_id)

    q = Employe.query.filter(Employe.structure_id == structure_id,
                             or_(Employe.statut.in_(Employe.STATUTS_EN_SERVICE), Employe.date_depart >= date_debut))
    if employe_id:
        q = q.filter(Employe.id == employe_id)
    employes = q.all()

    feries = {j.date for j in JourFerie.query.filter(JourFerie.structure_id == structure_id,
                                                     JourFerie.date >= date_debut, JourFerie.date <= date_fin).all()}
    jours_ouvres = []
    d = date_debut
    while d <= date_fin:
        if d.weekday() in (param.jours_travailles or []) and d not in feries:
            jours_ouvres.append(d)
        d += timedelta(days=1)

    aujourdhui = date.today()
    resultats = []
    for emp in employes:
        jours_emp = [j for j in jours_ouvres
                     if (not emp.date_embauche or j >= emp.date_embauche) and (not emp.date_depart or j <= emp.date_depart)]
        pointages = Pointage.query.filter(
            Pointage.employe_id == emp.id,
            Pointage.date_jour >= date_debut,
            Pointage.date_jour <= date_fin,
        ).all()
        par_date = {p.date_jour: p for p in pointages}
        conges = Conge.query.filter(Conge.employe_id == emp.id, Conge.statut.in_(('approuve', 'termine')),
                                    Conge.date_debut <= date_fin).all()
        permissions = Permission.query.filter(Permission.employe_id == emp.id,
                                              Permission.statut.in_(('approuve', 'termine')),
                                              Permission.type_permission != 'heures',
                                              Permission.date_debut <= date_fin, Permission.date_fin >= date_debut).all()

        def justifie(j):
            return (any(absent_ce_jour(j, c.date_debut, c.date_fin, c.date_reprise) for c in conges)
                    or any(p.date_debut <= j <= p.date_fin for p in permissions))

        passes = [j for j in jours_emp if j <= aujourdhui]
        jours_presents = sum(1 for j in jours_emp if j in par_date and par_date[j].heure_arrivee)
        jours_retard = sum(1 for p in pointages if p.statut_arrivee == 'retard')
        non_pointes = [j for j in passes if j not in par_date]
        jours_justifies = sum(1 for j in non_pointes if justifie(j))
        jours_absents = len(non_pointes) - jours_justifies
        minutes_totales = sum(p.duree_travaillee_minutes or 0 for p in pointages)

        resultats.append({
            'employe_id': emp.id,
            'employe_nom': f"{emp.prenom or ''} {emp.nom}".strip(),
            'jours_ouvres': len(passes),
            'jours_presents': jours_presents,
            'jours_retard': jours_retard,
            'jours_absents': jours_absents,
            'jours_justifies': jours_justifies,
            'heures_travaillees': round(minutes_totales / 60, 1),
        })
    return resultats


# ----------------------------------------------------------------------
# Pointage par reconnaissance FACIALE (webcam standard, sans WebAuthn)
# ----------------------------------------------------------------------
# Seuil de distance euclidienne entre deux descripteurs face-api.js en
# dessous duquel on considère qu'il s'agit de la même personne. La
# documentation face-api.js recommande ~0.6 comme limite haute ; on prend
# plus strict pour réduire le risque de faux positifs sur un pointage
# (mieux vaut demander à réessayer qu'identifier le mauvais employé).
SEUIL_DISTANCE_VISAGE = 0.5


def _distance_euclidienne(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _valider_descripteur(descripteur):
    if not isinstance(descripteur, list) or len(descripteur) != 128 or \
       not all(isinstance(x, (int, float)) for x in descripteur):
        raise ValueError("Descripteur facial invalide (attendu : 128 nombres).")


def enregistrer_visage(employe, descripteur, libelle=None):
    """Enregistre un nouveau visage de référence pour un employé."""
    _valider_descripteur(descripteur)
    visage = VisageEmploye(
        structure_id=employe.structure_id,
        employe_id=employe.id,
        descripteur=descripteur,
        libelle=libelle or 'Visage enregistré',
    )
    db.session.add(visage)
    db.session.commit()
    return visage


def identifier_par_visage(structure_id, descripteur):
    """Compare le descripteur reçu à tous les visages enregistrés de la
    structure (employés actifs uniquement), retient le plus proche sous le
    seuil, et enregistre le pointage (même logique arrivée/départ que pour
    l'empreinte). Lève ValueError avec un message utilisateur sinon."""
    _valider_descripteur(descripteur)

    visages = (
        VisageEmploye.query
        .join(Employe, Employe.id == VisageEmploye.employe_id)
        .filter(VisageEmploye.structure_id == structure_id,
                VisageEmploye.actif == True,  # noqa: E712
                Employe.statut.in_(Employe.STATUTS_EN_SERVICE))
        .all()
    )
    if not visages:
        raise ValueError("Aucun visage enregistré pour cette structure.")

    meilleur, meilleure_distance = None, None
    for v in visages:
        d = _distance_euclidienne(descripteur, v.descripteur)
        if meilleure_distance is None or d < meilleure_distance:
            meilleure_distance, meilleur = d, v

    if meilleur is None or meilleure_distance > SEUIL_DISTANCE_VISAGE:
        raise ValueError("Visage non reconnu. Rapprochez-vous de la caméra et réessayez.")

    meilleur.derniere_utilisation = datetime.utcnow()
    employe = Employe.query.get(meilleur.employe_id)
    resultat = enregistrer_pointage(employe, methode='visage')
    db.session.commit()
    resultat['employe_nom'] = f"{employe.prenom or ''} {employe.nom}".strip()
    resultat['distance'] = round(meilleure_distance, 3)
    return resultat
