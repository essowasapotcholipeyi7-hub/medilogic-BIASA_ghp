"""Migration ponctuelle : chiffre nom/prenom/telephone des patients déjà
existants en base (les nouveaux patients créés depuis le déploiement du
chiffrement le sont déjà automatiquement — voir crypto_helper.py).

À exécuter UNE SEULE FOIS, après que PATIENT_ENCRYPTION_KEY soit bien en
place sur Render (et donc dans le .env local utilisé ici, qui doit
contenir la MÊME clé). Idempotent : si relancé par erreur, les patients
déjà chiffrés sont simplement ignorés (aucun risque de double-chiffrement).

Usage :
    python migrate_chiffrement_patients.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db
from crypto_helper import chiffrer, dechiffrer, est_chiffre

with app.app_context():
    rows = db.session.execute(db.text('SELECT id, nom, prenom, telephone FROM patients')).fetchall()
    total = len(rows)
    deja = 0
    migres = 0
    erreurs = []
    for r in rows:
        d = dict(r._mapping)
        pid, nom, prenom, telephone = d['id'], d['nom'], d['prenom'], d['telephone']
        if est_chiffre(nom):
            deja += 1
            continue
        try:
            nom_c = chiffrer(nom)
            prenom_c = chiffrer(prenom)
            tel_c = chiffrer(telephone)
            # Vérification aller-retour avant d'écrire — on n'écrit jamais
            # une valeur qu'on ne pourrait pas relire correctement.
            assert dechiffrer(nom_c) == nom
            assert dechiffrer(prenom_c) == prenom
            assert dechiffrer(tel_c) == telephone
            db.session.execute(
                db.text('UPDATE patients SET nom=:n, prenom=:p, telephone=:t WHERE id=:id'),
                {'n': nom_c, 'p': prenom_c, 't': tel_c, 'id': pid}
            )
            migres += 1
        except Exception as e:
            erreurs.append((pid, str(e)))
    db.session.commit()
    print(f'Total patients : {total}')
    print(f'Déjà chiffrés (ignorés) : {deja}')
    print(f'Migrés maintenant : {migres}')
    print(f'Erreurs : {len(erreurs)}')
    if erreurs:
        print('Détail erreurs (id, message) :', erreurs[:10])
