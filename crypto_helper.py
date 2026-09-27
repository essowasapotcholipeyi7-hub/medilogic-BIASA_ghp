"""Chiffrement/déchiffrement des champs patient sensibles (nom, prénom,
téléphone) — confidentialité en base : même avec un accès direct à Neon
(console, dump SQL), ces colonnes restent illisibles sans la clé.

La clé vient de la variable d'environnement PATIENT_ENCRYPTION_KEY (jamais
stockée en base ni dans le code). Si elle est absente (ex. environnement
local sans .env configuré), on se rabat sur du texte en clair pour ne pas
bloquer le développement — mais on le signale bien au démarrage.
"""
import os
from cryptography.fernet import Fernet, InvalidToken

_cle = os.environ.get('PATIENT_ENCRYPTION_KEY')
_fernet = None
if _cle:
    try:
        _fernet = Fernet(_cle.encode() if isinstance(_cle, str) else _cle)
    except Exception as e:
        print(f"❌ PATIENT_ENCRYPTION_KEY invalide, chiffrement désactivé : {e}")
else:
    print("⚠️ PATIENT_ENCRYPTION_KEY absente — les données patient ne seront PAS chiffrées.")


def chiffrer(valeur):
    """Chiffre une valeur avant écriture en base. None/'' repassent tels quels."""
    if valeur is None or valeur == '' or not _fernet:
        return valeur
    return _fernet.encrypt(str(valeur).encode()).decode()


def dechiffrer(valeur):
    """Déchiffre une valeur lue en base. Tolère les valeurs déjà en clair
    (avant migration) ou vides — ne lève jamais d'exception."""
    if valeur is None or valeur == '' or not _fernet:
        return valeur
    try:
        return _fernet.decrypt(str(valeur).encode()).decode()
    except (InvalidToken, ValueError, UnicodeDecodeError):
        return valeur


def dechiffrer_champs(ligne, champs=('nom', 'prenom', 'telephone')):
    """Déchiffre en place les champs donnés d'un dict (résultat de requête
    SQL). Ne fait rien si ligne est None ou n'est pas un dict."""
    if not isinstance(ligne, dict):
        return ligne
    for champ in champs:
        if champ in ligne:
            ligne[champ] = dechiffrer(ligne[champ])
    return ligne


def dechiffrer_lignes(lignes, champs=('nom', 'prenom', 'telephone')):
    """Applique dechiffrer_champs à une liste de dicts."""
    for ligne in (lignes or []):
        dechiffrer_champs(ligne, champs)
    return lignes


def dechiffrer_patients_orm(patients):
    """Déchiffre nom/prenom/telephone sur une liste d'objets ORM Patient
    destinés à l'affichage (jamais une écriture). On les détache de la
    session (expunge) avant de modifier ces attributs en mémoire — comme
    ça, même si une autre partie de la même requête fait un commit plus
    tard, ces objets ne peuvent plus être réécrits en base avec le texte
    en clair à la place du texte chiffré."""
    from models import db
    for p in patients:
        db.session.expunge(p)
        p.nom = dechiffrer(p.nom)
        p.prenom = dechiffrer(p.prenom)
        p.telephone = dechiffrer(p.telephone)
    return patients


def est_chiffre(valeur):
    """True si la valeur se déchiffre correctement (donc déjà chiffrée)."""
    if valeur is None or valeur == '' or not _fernet:
        return False
    try:
        _fernet.decrypt(str(valeur).encode())
        return True
    except (InvalidToken, ValueError, UnicodeDecodeError):
        return False
