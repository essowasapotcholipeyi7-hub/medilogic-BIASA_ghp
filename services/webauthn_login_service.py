# services/webauthn_login_service.py
"""
Connexion par biométrie de l'appareil (Face ID / Windows Hello / empreinte),
via WebAuthn — pour SE CONNECTER à l'appli (voir models.IdentifiantWebauthn).
À ne pas confondre avec services/pointage_service.py, qui gère les
empreintes de la borne de pointage RH (employés, table employes) : ici il
s'agit des comptes de connexion (Google Sheets), même univers que
CodeQrConnexion (app.py).

Deux cérémonies :
  - Inscription (un appareil à la fois, par le compte lui-même, une fois
    déjà connecté par mot de passe/QR) : options_inscription() puis
    verifier_inscription().
  - Connexion (à la place du mot de passe) : options_connexion() puis
    verifier_connexion(), qui identifie le compte À PARTIR de la clé
    biométrique (pas de saisie préalable d'email) — via une clé résidente
    ("discoverable credential") : c'est ce qui permet au navigateur de
    proposer directement Face ID/Windows Hello sans qu'on lui dise
    d'avance quel compte chercher. Nécessite donc resident_key=REQUIRED
    (contrairement à la borne de pointage, qui connaît déjà la structure
    et n'a pas besoin de cette découverte).

Important : WebAuthn n'est autorisé par les navigateurs que sur
"localhost" ou en HTTPS — pas sur une adresse IP locale en http:// simple
(voir services/pointage_service.py pour le détail, même contrainte ici).
"""

import base64
from datetime import datetime

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from models import db, IdentifiantWebauthn

RP_NAME = "Medilogic"


def _rp_id_et_origin(request):
    """Voir services/pointage_service.py — même dérivation, dupliquée ici
    pour ne pas faire dépendre la connexion (app.py) du module RH."""
    rp_id = request.host.split(':')[0]
    est_local = rp_id in ('localhost', '127.0.0.1', '::1')
    scheme = request.scheme if est_local else 'https'
    origin = f"{scheme}://{request.host}"
    return rp_id, origin


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode('ascii'))


def _handle_compte(structure_id, utilisateur_id, type_compte) -> bytes:
    """Identifiant WebAuthn interne (≤64 octets) du compte, encodé dans la
    clé résidente par l'authentificateur — c'est ce qui permettra de
    retrouver le compte au moment de la connexion, mais on retrouve en
    fait le compte via credential_id (voir verifier_connexion), donc ceci
    ne sert qu'à satisfaire l'API (user_id) ; pas de retour en clair."""
    return f"{type_compte}:{structure_id}:{utilisateur_id}".encode('utf-8')


# ----------------------------------------------------------------------
# Inscription d'un appareil (compte déjà connecté)
# ----------------------------------------------------------------------

def options_inscription(request, structure_id, utilisateur_id, type_compte, utilisateur_nom):
    rp_id, _ = _rp_id_et_origin(request)

    existants = IdentifiantWebauthn.query.filter_by(
        structure_id=structure_id, utilisateur_id=utilisateur_id,
        type_compte=type_compte, actif=True,
    ).all()
    exclude = [PublicKeyCredentialDescriptor(id=_unb64(e.credential_id)) for e in existants]

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=_handle_compte(structure_id, utilisateur_id, type_compte),
        user_name=utilisateur_nom or f"compte-{utilisateur_id}",
        user_display_name=utilisateur_nom or f"compte-{utilisateur_id}",
        authenticator_selection=AuthenticatorSelectionCriteria(
            # PLATFORM : force le capteur intégré (Face ID/Windows
            # Hello/empreinte), pas une clé de sécurité USB externe — même
            # raisonnement que la borne de pointage.
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            # REQUIRED (contrairement au pointage) : la clé doit être
            # "résidente"/découvrable pour que la page de connexion puisse
            # la proposer SANS connaître le compte à l'avance.
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=exclude,
    )
    challenge_b64 = _b64(options.challenge)
    return webauthn.options_to_json(options), challenge_b64


def verifier_inscription(request, structure_id, utilisateur_id, type_compte, utilisateur_nom,
                          credential_json, challenge_b64, libelle_appareil=None):
    rp_id, origin = _rp_id_et_origin(request)

    verification = webauthn.verify_registration_response(
        credential=credential_json,
        expected_challenge=_unb64(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_verification=True,
    )

    identifiant = IdentifiantWebauthn(
        structure_id=structure_id,
        utilisateur_id=utilisateur_id,
        type_compte=type_compte,
        utilisateur_nom=utilisateur_nom,
        credential_id=_b64(verification.credential_id),
        public_key=_b64(verification.credential_public_key),
        sign_count=verification.sign_count,
        libelle_appareil=libelle_appareil or request.host,
    )
    db.session.add(identifiant)
    db.session.commit()
    return identifiant


# ----------------------------------------------------------------------
# Connexion (identification par la clé biométrique elle-même)
# ----------------------------------------------------------------------

def options_connexion(request):
    """Pas de allow_credentials : c'est justement le principe d'une clé
    résidente — le navigateur retrouve tout seul, sur l'appareil, les
    clés déjà enregistrées pour ce rp_id et les propose (Face ID/Windows
    Hello affiche son propre sélecteur de compte)."""
    rp_id, _ = _rp_id_et_origin(request)
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_b64 = _b64(options.challenge)
    return webauthn.options_to_json(options), challenge_b64


def verifier_connexion(request, credential_json, challenge_b64):
    """Vérifie la clé biométrique et identifie le compte. Retourne la ligne
    IdentifiantWebauthn (structure_id/utilisateur_id/type_compte) — c'est
    à l'appelant (app.py) de résoudre le compte dans Google Sheets et de
    poser la session, exactement comme pour /login/qr. Lève ValueError
    avec un message utilisateur en cas d'échec."""
    import json
    rp_id, origin = _rp_id_et_origin(request)

    cred_dict = json.loads(credential_json) if isinstance(credential_json, str) else credential_json
    credential_id_b64url = cred_dict.get('id') or cred_dict.get('rawId')
    if not credential_id_b64url:
        raise ValueError("Réponse de l'appareil incomplète.")

    raw_id = webauthn.base64url_to_bytes(credential_id_b64url)
    identifiant = IdentifiantWebauthn.query.filter_by(credential_id=_b64(raw_id), actif=True).first()
    if not identifiant:
        raise ValueError("Cet appareil n'est associé à aucun compte (ou a été révoqué).")

    verification = webauthn.verify_authentication_response(
        credential=credential_json,
        expected_challenge=_unb64(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=_unb64(identifiant.public_key),
        credential_current_sign_count=identifiant.sign_count,
        require_user_verification=True,
    )
    identifiant.sign_count = verification.new_sign_count
    identifiant.derniere_utilisation = datetime.utcnow()
    db.session.commit()
    return identifiant
