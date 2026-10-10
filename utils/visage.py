# -*- coding: utf-8 -*-
"""Choix de l'employé reconnu par la borne (visage) — fonction pure, testée
dans tests/test_visage.py.

Patron (2026-10-10) : « le Face ID ne marche pas bien ». Avant : le visage
le plus proche sous le seuil gagnait, même quand un AUTRE employé était
presque aussi proche (risque de pointer pour quelqu'un d'autre). Maintenant
on exige aussi un écart net avec le deuxième employé le plus proche."""

SEUIL_DISTANCE_VISAGE = 0.5     # au-delà : visage inconnu
MARGE_AUTRE_EMPLOYE = 0.06      # écart minimum avec un autre employé
SEUIL_DOUBLON_ENREGISTREMENT = 0.38   # à l'enregistrement : « ressemble trop à … »


def choisir_employe(candidats, seuil=SEUIL_DISTANCE_VISAGE, marge=MARGE_AUTRE_EMPLOYE):
    """`candidats` : [(employe_id, distance)] (plusieurs visages possibles par
    employé). Renvoie (employe_id, distance, None) ou (None, distance, raison)
    avec raison 'inconnu' ou 'ambigu'."""
    meilleurs = {}
    for employe_id, d in candidats:
        if employe_id not in meilleurs or d < meilleurs[employe_id]:
            meilleurs[employe_id] = d
    if not meilleurs:
        return None, None, 'inconnu'
    classes = sorted(meilleurs.items(), key=lambda x: x[1])
    employe_id, d = classes[0]
    if d > seuil:
        return None, d, 'inconnu'
    if len(classes) > 1 and classes[1][1] - d < marge:
        return None, d, 'ambigu'
    return employe_id, d, None
