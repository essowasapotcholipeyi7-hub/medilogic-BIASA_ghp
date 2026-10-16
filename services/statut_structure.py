# -*- coding: utf-8 -*-
"""Statut de la structure (public / privé / confessionnel), réglé dans les paramètres AMU
(ParametrageAmuCnss.statut_structure). ⭐ 2026-10-16 (patron) : le forfait césarienne K233 n'est
remboursé à 100 % que dans les structures PUBLIQUES (aide de l'État)."""
import time

_cache = {}          # {structure_id: (est_publique, horodatage)}
DUREE_CACHE = 60     # secondes


def oublier(structure_id):
    """À appeler quand le statut est modifié (page des paramètres AMU)."""
    _cache.pop(structure_id, None)


def structure_est_publique(structure_id=None):
    """True si la structure (celle de la session par défaut) est déclarée « public ».
    Jamais d'exception : en cas de doute -> False (taux normal du patient)."""
    try:
        if structure_id is None:
            from flask import has_request_context, session
            if not has_request_context():
                return False
            structure_id = session.get('structure_id')
        if not structure_id:
            return False
        en_cache = _cache.get(structure_id)
        if en_cache and time.time() - en_cache[1] < DUREE_CACHE:
            return en_cache[0]
        from models import ParametrageAmuCnss
        p = ParametrageAmuCnss.query.filter_by(structure_id=structure_id).first()
        resultat = bool(p and (p.statut_structure or '').strip().lower() == 'public')
        _cache[structure_id] = (resultat, time.time())
        return resultat
    except Exception:
        return False
