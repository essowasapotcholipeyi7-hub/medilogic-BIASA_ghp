# -*- coding: utf-8 -*-
"""⭐ Thèmes / apparence par structure (patron, 2026-10-09) — persistance,
licences (thèmes payants avec période d'essai), CSS mis en cache par
structure. Logique pure dans utils/themes.py.

Tables : ThemeCatalogue (défini par le super-admin : nom, couleurs, payant,
prix, jours d'essai), ThemeStructure (choix + réglages d'une structure),
LicenceTheme (essai / payé par structure et thème payant).
"""
import time
from datetime import date, datetime, timedelta

from models import db, ThemeCatalogue, ThemeStructure, LicenceTheme
from utils.themes import (THEMES_DEFAUT, THEME_DEFAUT_CLE, generer_css, variables_effectives,
                          normaliser_variables, etat_licence, fin_essai_depuis, libelle_etat)

_CACHE_CSS = {}      # structure_id -> (expire, css)
_TTL = 60


def invalider_cache(structure_id=None):
    if structure_id is None:
        _CACHE_CSS.clear()
    else:
        _CACHE_CSS.pop(int(structure_id), None)


def assurer_catalogue():
    """Copie le catalogue par défaut en base s'il est vide (une fois)."""
    if ThemeCatalogue.query.first():
        return
    for t in THEMES_DEFAUT:
        db.session.add(ThemeCatalogue(cle=t['cle'], nom=t['nom'], description=t['description'], payant=t['payant'],
                                      prix=t['prix'], jours_essai=t['jours_essai'], ordre=t['ordre'],
                                      variables=t['variables'], actif=True))
    db.session.commit()


def _theme_dict(t):
    return {'cle': t.cle, 'nom': t.nom, 'description': t.description or '', 'payant': bool(t.payant),
            'prix': float(t.prix or 0), 'jours_essai': int(t.jours_essai or 0), 'ordre': int(t.ordre or 0),
            'variables': t.variables or {}, 'actif': bool(t.actif),
            'variables_effectives': variables_effectives(t.variables or {})}


def catalogue(inclure_inactifs=False):
    assurer_catalogue()
    q = ThemeCatalogue.query
    if not inclure_inactifs:
        q = q.filter_by(actif=True)
    return [_theme_dict(t) for t in q.order_by(ThemeCatalogue.ordre, ThemeCatalogue.id).all()]


def theme_par_cle(cle, inclure_inactifs=False):
    assurer_catalogue()
    t = ThemeCatalogue.query.filter_by(cle=cle).first()
    if not t or (not inclure_inactifs and not t.actif):
        return None
    return _theme_dict(t)


def licence_pour(structure_id, cle):
    return LicenceTheme.query.filter_by(structure_id=structure_id, theme_cle=cle).first()


def etat_pour(structure_id, theme):
    return etat_licence(theme['payant'], licence_pour(structure_id, theme['cle']))


def reglage_structure(structure_id):
    return ThemeStructure.query.filter_by(structure_id=structure_id).first()


def theme_actif(structure_id):
    """Thème réellement appliqué (repli sur le thème par défaut si la
    licence n'est plus valable ou le thème désactivé) + réglages propres +
    indication de blocage."""
    reglage = reglage_structure(structure_id)
    cle = (reglage.theme_cle if reglage and reglage.theme_cle else THEME_DEFAUT_CLE)
    theme = theme_par_cle(cle)
    bloque = None
    if theme is None:
        bloque = 'indisponible' if cle != THEME_DEFAUT_CLE else None
        theme = theme_par_cle(THEME_DEFAUT_CLE) or {'cle': THEME_DEFAUT_CLE, 'nom': 'Classique', 'payant': False, 'prix': 0,
                                                     'jours_essai': 0, 'variables': {}, 'description': ''}
    else:
        etat = etat_pour(structure_id, theme)
        if not etat['utilisable']:
            bloque = etat['etat']   # 'expire' | 'aucune'
            theme = theme_par_cle(THEME_DEFAUT_CLE) or theme
    personnalisation = (reglage.personnalisation or {}) if reglage else {}
    return {'theme': theme, 'cle_choisie': cle, 'personnalisation': personnalisation, 'bloque': bloque,
            'variables': variables_effectives(theme.get('variables') or {}, personnalisation)}


def css_pour_structure(structure_id):
    """CSS à injecter dans base.html — mis en cache 60 s par structure ;
    chaîne vide = apparence d'origine. Ne lève jamais."""
    if not structure_id:
        return ''
    sid = int(structure_id)
    now = time.time()
    hit = _CACHE_CSS.get(sid)
    if hit and hit[0] > now:
        return hit[1]
    try:
        css = generer_css(theme_actif(sid)['variables'])
    except Exception as e:   # jamais casser une page pour un thème
        print(f"⚠️ Thème structure {sid} : {e}")
        css = ''
        try:
            db.session.rollback()
        except Exception:
            pass
    _CACHE_CSS[sid] = (now + _TTL, css)
    return css


def css_apercu(cle, personnalisation):
    theme = theme_par_cle(cle, inclure_inactifs=True) or {'variables': {}}
    return generer_css(variables_effectives(theme.get('variables') or {}, personnalisation))


def catalogue_pour_structure(structure_id):
    actif = theme_actif(structure_id)
    out = []
    for t in catalogue():
        etat = etat_pour(structure_id, t)
        out.append({**t, 'etat': etat['etat'], 'utilisable': etat['utilisable'], 'jours_restants': etat['jours_restants'],
                    'fin_essai': etat['fin_essai'].strftime('%d/%m/%Y') if etat['fin_essai'] else None,
                    'libelle_etat': libelle_etat(etat, t), 'actif': t['cle'] == actif['theme']['cle'],
                    'css': generer_css(t['variables_effectives'])})
    return {'themes': out, 'actif': actif}


def _reglage_ou_creer(structure_id):
    r = reglage_structure(structure_id)
    if not r:
        r = ThemeStructure(structure_id=structure_id)
        db.session.add(r)
    return r


def choisir_theme(structure_id, cle, user_nom='', demarrer_essai=True):
    """La structure choisit un thème. Payant : licence payée ou essai en
    cours requis ; sans licence, un essai (jours_essai du thème) démarre
    automatiquement si demarrer_essai. Lève ValueError sinon."""
    theme = theme_par_cle(cle)
    if not theme:
        raise ValueError('Thème introuvable ou désactivé')
    if theme['payant']:
        lic = licence_pour(structure_id, cle)
        etat = etat_licence(True, lic)
        if etat['etat'] == 'aucune' and demarrer_essai:
            if (theme['jours_essai'] or 0) <= 0:
                raise ValueError("Ce thème est payant et n'a pas de période d'essai : demandez son activation à l'éditeur.")
            lic = LicenceTheme(structure_id=structure_id, theme_cle=cle, debut_essai=date.today(),
                               fin_essai=fin_essai_depuis(date.today(), theme['jours_essai']), paye=False, accorde_par=user_nom or 'structure')
            db.session.add(lic)
            db.session.flush()
            etat = etat_licence(True, lic)
        if not etat['utilisable']:
            raise ValueError(f"L'essai de ce thème est terminé ({etat['fin_essai'].strftime('%d/%m/%Y') if etat['fin_essai'] else ''}). "
                             f"Pour continuer à l'utiliser, demandez son activation à l'éditeur ({int(theme['prix']):,} F).".replace(',', ' '))
    r = _reglage_ou_creer(structure_id)
    r.theme_cle = cle
    r.modifie_par = user_nom
    r.modifie_le = datetime.utcnow()
    db.session.commit()
    invalider_cache(structure_id)
    return theme_actif(structure_id)


def personnaliser(structure_id, personnalisation, user_nom=''):
    r = _reglage_ou_creer(structure_id)
    perso = personnalisation or {}
    # on ne garde que les clés connues, normalisées
    norm = normaliser_variables(perso)
    r.personnalisation = {k: norm[k] for k in norm if k in perso}
    r.modifie_par = user_nom
    r.modifie_le = datetime.utcnow()
    db.session.commit()
    invalider_cache(structure_id)
    return theme_actif(structure_id)


def reinitialiser(structure_id, user_nom='', garder_theme=True):
    r = _reglage_ou_creer(structure_id)
    r.personnalisation = {}
    if not garder_theme:
        r.theme_cle = THEME_DEFAUT_CLE
    r.modifie_par = user_nom
    r.modifie_le = datetime.utcnow()
    db.session.commit()
    invalider_cache(structure_id)
    return theme_actif(structure_id)


# ------------------------------------------------------------------ super-admin
def enregistrer_theme(data, nouveau=False):
    """Crée ou modifie un thème du catalogue (super-admin)."""
    cle = (data.get('cle') or '').strip().lower().replace(' ', '_')
    if not cle or not cle.replace('_', '').replace('-', '').isalnum():
        raise ValueError('Clé invalide (lettres, chiffres, _ ou -)')
    t = ThemeCatalogue.query.filter_by(cle=cle).first()
    if nouveau and t:
        raise ValueError('Un thème porte déjà cette clé')
    if not t:
        t = ThemeCatalogue(cle=cle)
        db.session.add(t)
    t.nom = (data.get('nom') or cle).strip()[:100]
    t.description = (data.get('description') or '').strip()[:500]
    t.payant = bool(data.get('payant'))
    try:
        t.prix = max(0.0, float(data.get('prix') or 0))
        t.jours_essai = max(0, int(data.get('jours_essai') or 0))
        t.ordre = int(data.get('ordre') or 0)
    except (TypeError, ValueError):
        raise ValueError('Prix, jours d\'essai ou ordre invalide')
    t.actif = bool(data.get('actif', True))
    if 'variables' in data:
        t.variables = normaliser_variables(data.get('variables') or {}) if cle != THEME_DEFAUT_CLE else {}
    db.session.commit()
    invalider_cache()
    return _theme_dict(t)


def supprimer_theme(cle):
    if cle == THEME_DEFAUT_CLE:
        raise ValueError('Le thème par défaut ne peut pas être supprimé')
    t = ThemeCatalogue.query.filter_by(cle=cle).first()
    if not t:
        raise ValueError('Thème introuvable')
    LicenceTheme.query.filter_by(theme_cle=cle).delete()
    ThemeStructure.query.filter_by(theme_cle=cle).update({'theme_cle': THEME_DEFAUT_CLE})
    db.session.delete(t)
    db.session.commit()
    invalider_cache()


def accorder_licence(structure_id, cle, action, jours=None, montant=None, note='', user_nom='super-admin'):
    """action : 'payer' (activation définitive), 'essai' (démarrer /
    prolonger de `jours`), 'revoquer' (supprime la licence : le thème
    redevient inaccessible, la structure repasse sur le défaut)."""
    theme = theme_par_cle(cle, inclure_inactifs=True)
    if not theme:
        raise ValueError('Thème introuvable')
    lic = licence_pour(structure_id, cle)
    if action == 'revoquer':
        if lic:
            db.session.delete(lic)
        db.session.commit()
        invalider_cache(structure_id)
        return None
    if not lic:
        lic = LicenceTheme(structure_id=structure_id, theme_cle=cle, debut_essai=date.today(),
                           fin_essai=fin_essai_depuis(date.today(), jours or theme['jours_essai']), paye=False)
        db.session.add(lic)
    if action == 'payer':
        lic.paye = True
        lic.date_paiement = date.today()
        lic.montant_paye = float(montant if montant is not None else theme['prix'] or 0)
    elif action == 'essai':
        j = int(jours or theme['jours_essai'] or 14)
        # essai en cours : prolongé de j jours après sa fin ; sinon j jours à partir d'aujourd'hui
        base = lic.fin_essai if (lic.fin_essai and lic.fin_essai >= date.today()) else date.today() - timedelta(days=1)
        lic.fin_essai = base + timedelta(days=j)
        if not lic.debut_essai:
            lic.debut_essai = date.today()
        lic.paye = False
    else:
        raise ValueError('Action inconnue')
    lic.note = (note or lic.note or '')[:300]
    lic.accorde_par = user_nom
    db.session.commit()
    invalider_cache(structure_id)
    return lic


def licences_toutes():
    out = []
    for lic in LicenceTheme.query.order_by(LicenceTheme.structure_id, LicenceTheme.theme_cle).all():
        theme = theme_par_cle(lic.theme_cle, inclure_inactifs=True)
        etat = etat_licence(True, lic)
        out.append({'structure_id': lic.structure_id, 'theme_cle': lic.theme_cle, 'theme_nom': theme['nom'] if theme else lic.theme_cle,
                    'etat': etat['etat'], 'libelle_etat': libelle_etat(etat, theme), 'jours_restants': etat['jours_restants'],
                    'debut_essai': lic.debut_essai.strftime('%d/%m/%Y') if lic.debut_essai else '',
                    'fin_essai': lic.fin_essai.strftime('%d/%m/%Y') if lic.fin_essai else '',
                    'paye': bool(lic.paye), 'date_paiement': lic.date_paiement.strftime('%d/%m/%Y') if lic.date_paiement else '',
                    'montant_paye': float(lic.montant_paye or 0), 'note': lic.note or '', 'accorde_par': lic.accorde_par or ''})
    return out


def themes_choisis():
    """{structure_id: cle} des structures ayant choisi un thème."""
    return {r.structure_id: r.theme_cle for r in ThemeStructure.query.all() if r.theme_cle}
