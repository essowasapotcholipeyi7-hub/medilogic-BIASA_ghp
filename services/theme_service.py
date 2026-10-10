# -*- coding: utf-8 -*-
"""⭐ Thèmes / apparence (patron, 2026-10-09) — persistance, licences (thèmes
payants : 10 000 F une seule fois, avec période d'essai), CSS mis en cache.
Logique pure dans utils/themes.py.

Portée : l'ADMIN règle le thème de toute la structure (ThemeStructure) ;
tout autre utilisateur peut régler le sien, qui ne s'applique qu'à lui
(ThemeUtilisateur) — patron : « que les autres puissent aussi faire ce
réglage mais que ça s'applique uniquement chez eux ; global uniquement si
c'est l'admin qui règle ». Les licences des thèmes payants restent au
niveau de la structure (un utilisateur ne peut pas démarrer un essai).
"""
import io
import time
from datetime import date, datetime, timedelta

from models import db, ThemeCatalogue, ThemeStructure, ThemeUtilisateur, LicenceTheme
from utils.themes import (THEMES_DEFAUT, THEME_DEFAUT_CLE, generer_css, variables_effectives,
                          normaliser_variables, etat_licence, fin_essai_depuis, libelle_etat,
                          palette_vers_variables)

_CACHE_CSS = {}      # (structure_id, utilisateur_id) -> (expire, css)
_TTL = 10   # court : plusieurs processus serveur, chacun son cache — un changement se voit partout en quelques secondes


def invalider_cache(structure_id=None):
    if structure_id is None:
        _CACHE_CSS.clear()
        return
    sid = int(structure_id)
    for cle in [k for k in _CACHE_CSS if k[0] == sid]:
        _CACHE_CSS.pop(cle, None)


def assurer_catalogue():
    """Copie le catalogue par défaut en base, puis complète les thèmes
    manquants (nouveaux thèmes livrés après coup) sans toucher aux réglages
    que le super-admin a faits sur les existants."""
    existants = {t.cle for t in db.session.query(ThemeCatalogue.cle).all()}
    manquants = [t for t in THEMES_DEFAUT if t['cle'] not in existants]
    if not manquants:
        return
    for t in manquants:
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


def reglage_utilisateur(structure_id, utilisateur_id):
    if utilisateur_id in (None, ''):
        return None
    return ThemeUtilisateur.query.filter_by(structure_id=structure_id, utilisateur_id=str(utilisateur_id)).first()


def _resoudre(structure_id, cle, personnalisation):
    """Thème utilisable pour cette clé (repli sur le défaut si licence non
    valable / thème désactivé) + variables effectives + motif de blocage."""
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
    return theme, bloque, variables_effectives(theme.get('variables') or {}, personnalisation)


def theme_actif(structure_id, utilisateur_id=None):
    """Apparence réellement appliquée à cet utilisateur : son réglage
    personnel s'il en a un, sinon celui de la structure."""
    rs = reglage_structure(structure_id)
    cle_structure = (rs.theme_cle if rs and rs.theme_cle else THEME_DEFAUT_CLE)
    perso_structure = (rs.personnalisation or {}) if rs else {}
    ru = reglage_utilisateur(structure_id, utilisateur_id)
    if ru and (ru.theme_cle or ru.personnalisation):
        source = 'utilisateur'
        cle = ru.theme_cle or cle_structure
        personnalisation = ru.personnalisation or {}
    else:
        source, cle, personnalisation = 'structure', cle_structure, perso_structure
    theme, bloque, variables = _resoudre(structure_id, cle, personnalisation)
    return {'theme': theme, 'cle_choisie': cle, 'personnalisation': personnalisation, 'bloque': bloque,
            'variables': variables, 'source': source, 'cle_structure': cle_structure,
            'reglage_personnel': bool(ru and (ru.theme_cle or ru.personnalisation))}


def css_pour(structure_id, utilisateur_id=None):
    """CSS à injecter dans base.html — cache 60 s par (structure, utilisateur) ;
    chaîne vide = apparence d'origine. Ne lève jamais."""
    if not structure_id:
        return ''
    cle = (int(structure_id), str(utilisateur_id or ''))
    now = time.time()
    hit = _CACHE_CSS.get(cle)
    if hit and hit[0] > now:
        return hit[1]
    try:
        css = generer_css(theme_actif(cle[0], utilisateur_id)['variables'])
    except Exception as e:   # jamais casser une page pour un thème
        print(f"⚠️ Thème structure {cle[0]} : {e}")
        css = ''
        try:
            db.session.rollback()
        except Exception:
            pass
    _CACHE_CSS[cle] = (now + _TTL, css)
    return css


def css_pour_structure(structure_id):
    return css_pour(structure_id, None)


def css_apercu(cle, personnalisation):
    theme = theme_par_cle(cle, inclure_inactifs=True) or {'variables': {}}
    return generer_css(variables_effectives(theme.get('variables') or {}, personnalisation))


def catalogue_pour_structure(structure_id, utilisateur_id=None):
    actif = theme_actif(structure_id, utilisateur_id)
    out = []
    for t in catalogue():
        etat = etat_pour(structure_id, t)
        lic = licence_pour(structure_id, t['cle']) if t['payant'] else None
        out.append({**t, 'etat': etat['etat'], 'utilisable': etat['utilisable'], 'jours_restants': etat['jours_restants'],
                    'paye_verifie': bool(lic and lic.paye_verifie), 'moyen_paiement': (lic.moyen_paiement if lic else None),
                    'fin_essai': etat['fin_essai'].strftime('%d/%m/%Y') if etat['fin_essai'] else None,
                    'libelle_etat': libelle_etat(etat, t), 'actif': t['cle'] == actif['theme']['cle'] and not actif['bloque'],
                    'css': generer_css(t['variables_effectives'])})
    return {'themes': out, 'actif': actif}


def _reglage_ou_creer(structure_id, portee, utilisateur_id):
    if portee == 'utilisateur':
        r = reglage_utilisateur(structure_id, utilisateur_id)
        if not r:
            r = ThemeUtilisateur(structure_id=structure_id, utilisateur_id=str(utilisateur_id))
            db.session.add(r)
        return r
    r = reglage_structure(structure_id)
    if not r:
        r = ThemeStructure(structure_id=structure_id)
        db.session.add(r)
    return r


def choisir_theme(structure_id, cle, user_nom='', demarrer_essai=True, portee='structure', utilisateur_id=None):
    """Choix d'un thème. portee='structure' (admin) : s'applique à tout le
    monde ; un thème payant sans licence démarre un essai (jours_essai).
    portee='utilisateur' : ne s'applique qu'à cet utilisateur ; un thème
    payant exige une licence (essai en cours ou payée) de la structure.
    Lève ValueError sinon."""
    theme = theme_par_cle(cle)
    if not theme:
        raise ValueError('Thème introuvable ou désactivé')
    if theme['payant']:
        lic = licence_pour(structure_id, cle)
        etat = etat_licence(True, lic)
        if etat['etat'] == 'aucune' and demarrer_essai and portee == 'structure':
            if (theme['jours_essai'] or 0) <= 0:
                raise ValueError("Ce thème est payant et n'a pas de période d'essai : demandez son activation à l'éditeur.")
            lic = LicenceTheme(structure_id=structure_id, theme_cle=cle, debut_essai=date.today(),
                               fin_essai=fin_essai_depuis(date.today(), theme['jours_essai']), paye=False, accorde_par=user_nom or 'structure')
            db.session.add(lic)
            db.session.flush()
            etat = etat_licence(True, lic)
        if not etat['utilisable']:
            prix = f"{int(theme['prix']):,} F une seule fois".replace(',', ' ')
            if portee == 'utilisateur':
                raise ValueError(f"Thème payant ({prix}) : demandez à l'administrateur de la structure de l'activer "
                                 f"(essai gratuit de {theme['jours_essai']} jours possible) — il sera alors disponible pour vous.")
            if etat['etat'] == 'expire':
                raise ValueError(f"L'essai de ce thème est terminé ({etat['fin_essai'].strftime('%d/%m/%Y') if etat['fin_essai'] else ''}). "
                                 f"Pour continuer à l'utiliser, demandez son activation à l'éditeur ({prix}).")
            raise ValueError(f"Ce thème est payant ({prix}) : demandez son activation à l'éditeur.")
    r = _reglage_ou_creer(structure_id, portee, utilisateur_id)
    r.theme_cle = cle
    r.personnalisation = {}   # ⭐ un nouveau thème repart propre (les réglages étaient relatifs à l'ancien)
    r.modifie_par = user_nom
    r.modifie_le = datetime.utcnow()
    if portee == 'structure':
        r.proposition_vue = True   # un thème a été choisi : plus de proposition à la connexion
    db.session.commit()
    invalider_cache(structure_id)
    return theme_actif(structure_id, utilisateur_id if portee == 'utilisateur' else None)


THEME_PROPOSE_CLE = 'noir'


def proposition_a_faire(structure_id):
    """⭐ True si la structure est encore en apparence d'origine, n'a jamais
    tranché, et que le thème proposé existe (actif)."""
    r = reglage_structure(structure_id)
    if r and (r.proposition_vue or (r.theme_cle and r.theme_cle != THEME_DEFAUT_CLE)):
        return False
    return theme_par_cle(THEME_PROPOSE_CLE) is not None


def marquer_proposition_vue(structure_id, user_nom=''):
    r = _reglage_ou_creer(structure_id, 'structure', None)
    r.proposition_vue = True
    r.modifie_par = user_nom
    db.session.commit()


def personnaliser(structure_id, personnalisation, user_nom='', portee='structure', utilisateur_id=None):
    r = _reglage_ou_creer(structure_id, portee, utilisateur_id)
    perso = personnalisation or {}
    norm = normaliser_variables(perso)
    # ⭐ Ne garder que ce qui DIFFÈRE du thème actif (patron, 2026-10-10 : le
    # formulaire renvoie tous les champs ; sans ce filtre, enregistrer sous
    # Noir figeait toute la palette noire en réglages, qui restaient
    # appliqués après retour au thème clair — « ça ne revient pas »).
    actif = theme_actif(structure_id, utilisateur_id if portee == 'utilisateur' else None)
    base = variables_effectives(actif['theme'].get('variables') or {})
    r.personnalisation = {k: norm[k] for k in norm if k in perso and norm[k] != base.get(k)}
    r.modifie_par = user_nom
    r.modifie_le = datetime.utcnow()
    db.session.commit()
    invalider_cache(structure_id)
    return theme_actif(structure_id, utilisateur_id if portee == 'utilisateur' else None)


def reinitialiser(structure_id, user_nom='', garder_theme=True, portee='structure', utilisateur_id=None):
    """garder_theme=False : structure -> retour au thème d'origine ;
    utilisateur -> suppression du réglage personnel (retour à celui de la structure)."""
    if portee == 'utilisateur':
        r = reglage_utilisateur(structure_id, utilisateur_id)
        if r:
            if garder_theme:
                r.personnalisation = {}
                r.modifie_le = datetime.utcnow()
            else:
                db.session.delete(r)
            db.session.commit()
        invalider_cache(structure_id)
        return theme_actif(structure_id, utilisateur_id)
    r = _reglage_ou_creer(structure_id, 'structure', None)
    r.personnalisation = {}
    if not garder_theme:
        r.theme_cle = THEME_DEFAUT_CLE
    r.modifie_par = user_nom
    r.modifie_le = datetime.utcnow()
    db.session.commit()
    invalider_cache(structure_id)
    return theme_actif(structure_id, None)


# ------------------------------------------------------------------ couleurs du logo
def couleurs_depuis_image(donnees):
    """Palette quantifiée d'une image (bytes) -> [(poids, (r, g, b)), ...]."""
    from PIL import Image
    img = Image.open(io.BytesIO(donnees))
    img = img.convert('RGBA')
    fond = Image.new('RGBA', img.size, (255, 255, 255, 255))
    fond.paste(img, mask=img.split()[3])   # transparence -> blanc (ignoré ensuite)
    img = fond.convert('RGB')
    img.thumbnail((96, 96))
    q = img.quantize(colors=12, method=Image.Quantize.MEDIANCUT if hasattr(Image, 'Quantize') else 0)
    palette = q.getpalette()
    couleurs = []
    for count, idx in q.getcolors(96 * 96) or []:
        couleurs.append((count, tuple(palette[idx * 3: idx * 3 + 3])))
    return couleurs


def proposer_depuis_octets(donnees):
    """Palette de thème depuis les octets d'une image (logo stocké)."""
    try:
        couleurs = couleurs_depuis_image(donnees)
    except Exception as e:
        raise ValueError(f"Le logo n'est pas une image lisible ({e}).")
    variables, palette = palette_vers_variables(couleurs)
    if not variables:
        raise ValueError("Le logo ne contient pas de couleur franche exploitable (noir, blanc ou gris seulement).")
    return variables, palette


def proposer_depuis_logo(url):
    """Télécharge le logo de la structure et propose des variables de thème.
    Retourne (variables, palette_hex) ou lève ValueError (message clair)."""
    if not (url or '').strip():
        raise ValueError("Aucun logo n'est enregistré pour la structure (Administration générale → Ma structure → Logo URL).")
    try:
        import requests
        r = requests.get(url.strip(), timeout=10, stream=True, headers={'User-Agent': 'SSoftOneV10'})
        r.raise_for_status()
        donnees = r.raw.read(3 * 1024 * 1024 + 1, decode_content=True)
    except Exception as e:
        raise ValueError(f"Impossible de télécharger le logo ({e}).")
    if len(donnees) > 3 * 1024 * 1024:
        raise ValueError('Logo trop lourd (plus de 3 Mo).')
    try:
        couleurs = couleurs_depuis_image(donnees)
    except Exception as e:
        raise ValueError(f"Le logo n'est pas une image lisible ({e}).")
    variables, palette = palette_vers_variables(couleurs)
    if not variables:
        raise ValueError("Le logo ne contient pas de couleur franche exploitable (noir, blanc ou gris seulement).")
    return variables, palette


# ------------------------------------------------------------------ paiement par la structure
MOYENS_PAIEMENT_THEME = {'mixx': 'Mixx by Yas', 'moov': 'Moov Money', 'especes': 'Espèces', 'virement': 'Virement bancaire'}
MOTIF_THEME = 'theme_logiciel'


def payer_theme(structure_id, cle, moyen_paiement, reference_paiement, date_paiement, user_nom='', demande_id=None):
    """⭐ La structure déclare le paiement d'un thème payant : licence payée
    tout de suite (accès immédiat), marquée « à vérifier » par l'éditeur.
    Lève ValueError (thème gratuit, déjà payé, justificatif manquant)."""
    theme = theme_par_cle(cle)
    if not theme or not theme['payant']:
        raise ValueError("Ce thème n'est pas payant (ou n'existe pas).")
    if moyen_paiement not in MOYENS_PAIEMENT_THEME:
        raise ValueError('Moyen de paiement invalide.')
    reference_paiement = (reference_paiement or '').strip()
    if moyen_paiement in ('mixx', 'moov', 'virement') and not reference_paiement:
        raise ValueError(f"La référence du paiement {MOYENS_PAIEMENT_THEME[moyen_paiement]} est obligatoire.")
    if date_paiement > date.today():
        raise ValueError('La date du paiement ne peut pas être dans le futur.')
    lic = licence_pour(structure_id, cle)
    if lic and lic.paye:
        raise ValueError('Ce thème est déjà payé pour votre structure.')
    if not lic:
        lic = LicenceTheme(structure_id=structure_id, theme_cle=cle, debut_essai=date.today(), fin_essai=date.today())
        db.session.add(lic)
    lic.paye = True
    lic.paye_verifie = False
    lic.date_paiement = date_paiement
    lic.montant_paye = float(theme['prix'] or 0)
    lic.moyen_paiement = moyen_paiement
    lic.reference_paiement = reference_paiement[:100] or None
    lic.demande_id = demande_id
    lic.note = f"Paiement déclaré par la structure ({MOYENS_PAIEMENT_THEME[moyen_paiement]}{' réf. ' + reference_paiement if reference_paiement else ''})"[:300]
    lic.accorde_par = user_nom or 'structure'
    db.session.commit()
    invalider_cache(structure_id)
    return lic


def lier_depense_theme(structure_id, cle, depense_id):
    """Après validation de la charge : rattache la Dépense à la licence."""
    lic = licence_pour(structure_id, cle)
    if lic:
        lic.depense_id = depense_id
        db.session.commit()


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
    ThemeUtilisateur.query.filter_by(theme_cle=cle).update({'theme_cle': None})
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
        lic.paye_verifie = True
        lic.date_paiement = lic.date_paiement or date.today()
        lic.montant_paye = float(montant if montant is not None else (lic.montant_paye or theme['prix'] or 0))
    elif action == 'confirmer':
        if not lic.paye:
            raise ValueError("Aucun paiement déclaré à confirmer pour cette licence.")
        lic.paye_verifie = True
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
                    'montant_paye': float(lic.montant_paye or 0), 'note': lic.note or '', 'accorde_par': lic.accorde_par or '',
                    'paye_verifie': bool(lic.paye_verifie), 'moyen_paiement': MOYENS_PAIEMENT_THEME.get(lic.moyen_paiement or '', lic.moyen_paiement or ''),
                    'reference_paiement': lic.reference_paiement or '', 'depense_id': lic.depense_id, 'demande_id': lic.demande_id})
    return out


def themes_choisis():
    """{structure_id: cle} des structures ayant choisi un thème."""
    return {r.structure_id: r.theme_cle for r in ThemeStructure.query.all() if r.theme_cle}
