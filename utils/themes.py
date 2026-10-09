# -*- coding: utf-8 -*-
"""⭐ Thèmes / apparence du logiciel par structure (patron, 2026-10-09) :
« un système de réglage de thème ou design du logiciel à la convenance
d'une structure, couleur de fond d'écran, couleur des boutons, la
présentation... chaque structure pourra régler ; on peut même
commercialiser certains thèmes (payer, avec une ou deux semaines
d'essai), contrôlé depuis la page admin ».

Ce module est PUR (aucune base) : définition des variables, catalogue par
défaut, génération de la feuille CSS injectée dans base.html, état d'une
licence. La persistance et le cache sont dans services/theme_service.py.
"""
from datetime import date, timedelta

# (clé, libellé, type, valeur par défaut, aide)
VARIABLES_THEME = [
    ('primaire', 'Couleur principale', 'color', '#0E9D67', 'Liens, onglet actif, en-têtes colorés, icônes'),
    ('primaire_fonce', 'Couleur principale foncée', 'color', '#0B7C52', 'Dégradés, survol'),
    ('bouton', 'Couleur des boutons principaux', 'color', '#0E9D67', 'Boutons « Enregistrer », « Valider »...'),
    ('bouton_texte', 'Texte des boutons (au survol)', 'color', '#FFFFFF', ''),
    ('fond', "Couleur de fond d'écran", 'color', '#EEF2F5', 'Derrière les pages'),
    ('fond_image', "Garder l'image de fond", 'bool', True, 'Décochez pour un fond uni de la couleur ci-dessus'),
    ('carte_fond', 'Fond des pages / cartes', 'color', '#FFFFFF', 'Zone de contenu'),
    ('texte', 'Couleur du texte', 'color', '#0A3D5C', 'Titres et textes du contenu'),
    ('navbar_fond', 'Fond de la barre du haut', 'color', '#FFFFFF', 'Barre avec le nom de la structure et le menu'),
    ('navbar_texte', 'Texte de la barre du haut', 'color', '#0A3D5C', ''),
    ('rayon', 'Arrondi des cartes (px)', 'number', 15, '0 = angles droits, 24 = très arrondi'),
    ('police', 'Police de caractères', 'select', 'Inter', ''),
    ('mode_sombre', 'Mode sombre', 'bool', False, 'Fond et cartes sombres, texte clair'),
]
POLICES = ['Inter', 'Roboto', 'Poppins', 'Nunito', 'Montserrat', 'Lato', 'Open Sans', 'Segoe UI', 'Georgia']
POLICES_GOOGLE = {'Roboto', 'Poppins', 'Nunito', 'Montserrat', 'Lato', 'Open Sans'}

DEFAUT = {cle: val for cle, _, _, val, _ in VARIABLES_THEME}
THEME_DEFAUT_CLE = 'classique'

# Catalogue de départ — copié en base au premier appel (le super-admin peut
# ensuite modifier prix / essai / couleurs, désactiver, ajouter).
THEMES_DEFAUT = [
    {'cle': 'classique', 'nom': 'Classique SSoftOneV10', 'description': "L'apparence d'origine : vert et bleu, image de fond.",
     'payant': False, 'prix': 0, 'jours_essai': 14, 'ordre': 1, 'variables': {}},
    {'cle': 'ocean', 'nom': 'Océan', 'description': 'Bleus profonds, fond uni clair, très lisible.',
     'payant': False, 'prix': 0, 'jours_essai': 14, 'ordre': 2,
     'variables': {'primaire': '#1E6FD9', 'primaire_fonce': '#174F9B', 'bouton': '#1E6FD9', 'fond': '#E8F0FB', 'fond_image': False,
                   'texte': '#102A43', 'navbar_fond': '#174F9B', 'navbar_texte': '#FFFFFF', 'rayon': 12}},
    {'cle': 'foret', 'nom': 'Forêt', 'description': 'Verts sobres et naturels, barre du haut vert sombre.',
     'payant': False, 'prix': 0, 'jours_essai': 14, 'ordre': 3,
     'variables': {'primaire': '#2E7D32', 'primaire_fonce': '#1B5E20', 'bouton': '#2E7D32', 'fond': '#EEF5EE', 'fond_image': False,
                   'texte': '#1B3A1F', 'navbar_fond': '#1B5E20', 'navbar_texte': '#FFFFFF', 'rayon': 10}},
    {'cle': 'sable', 'nom': 'Sable', 'description': 'Tons chauds beige et terracotta, doux pour les yeux.',
     'payant': False, 'prix': 0, 'jours_essai': 14, 'ordre': 4,
     'variables': {'primaire': '#C0612B', 'primaire_fonce': '#8F4620', 'bouton': '#C0612B', 'fond': '#F6EFE6', 'fond_image': False,
                   'carte_fond': '#FFFBF6', 'texte': '#4A2E1C', 'navbar_fond': '#FFF8F0', 'navbar_texte': '#4A2E1C', 'rayon': 18, 'police': 'Nunito'}},
    {'cle': 'nuit', 'nom': 'Nuit', 'description': 'Mode sombre complet : fond anthracite, texte clair, accents turquoise.',
     'payant': True, 'prix': 15000, 'jours_essai': 14, 'ordre': 5,
     'variables': {'primaire': '#2DD4BF', 'primaire_fonce': '#14B8A6', 'bouton': '#2DD4BF', 'bouton_texte': '#0B1220', 'fond': '#0F172A', 'fond_image': False,
                   'carte_fond': '#1E293B', 'texte': '#E2E8F0', 'navbar_fond': '#0B1220', 'navbar_texte': '#E2E8F0', 'rayon': 12, 'mode_sombre': True}},
    {'cle': 'royal', 'nom': 'Royal', 'description': 'Violet et or, présentation premium.',
     'payant': True, 'prix': 10000, 'jours_essai': 14, 'ordre': 6,
     'variables': {'primaire': '#6D28D9', 'primaire_fonce': '#4C1D95', 'bouton': '#B45309', 'fond': '#F3EFFA', 'fond_image': False,
                   'texte': '#2E1065', 'navbar_fond': '#4C1D95', 'navbar_texte': '#FDE68A', 'rayon': 20, 'police': 'Poppins'}},
    {'cle': 'corail', 'nom': 'Corail', 'description': 'Rose corail et marine, moderne et chaleureux.',
     'payant': True, 'prix': 10000, 'jours_essai': 7, 'ordre': 7,
     'variables': {'primaire': '#E11D48', 'primaire_fonce': '#9F1239', 'bouton': '#E11D48', 'fond': '#FFF1F2', 'fond_image': False,
                   'texte': '#1E293B', 'navbar_fond': '#1E293B', 'navbar_texte': '#FFE4E6', 'rayon': 16, 'police': 'Montserrat'}},
]


# ------------------------------------------------------------------ utilitaires
def _hex(v, defaut):
    v = str(v or '').strip()
    if len(v) == 4 and v.startswith('#'):
        v = '#' + ''.join(c * 2 for c in v[1:])
    if len(v) == 7 and v.startswith('#'):
        try:
            int(v[1:], 16)
            return v.upper()
        except ValueError:
            pass
    return defaut


def _rgb(hexa):
    return tuple(int(hexa[i:i + 2], 16) for i in (1, 3, 5))


def _rgba(hexa, a):
    r, g, b = _rgb(hexa)
    return f'rgba({r}, {g}, {b}, {a})'


def _assombrir(hexa, facteur=0.75):
    r, g, b = _rgb(hexa)
    return '#%02X%02X%02X' % (int(r * facteur), int(g * facteur), int(b * facteur))


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'oui', 'on', 'yes')
    return bool(v)


def normaliser_variables(variables):
    """Valide/complète un dict de variables (valeurs inconnues -> défaut)."""
    variables = variables or {}
    out = {}
    for cle, _, typ, defaut, _ in VARIABLES_THEME:
        v = variables.get(cle, defaut)
        if typ == 'color':
            out[cle] = _hex(v, defaut)
        elif typ == 'bool':
            out[cle] = _bool(v) if v is not None else defaut
        elif typ == 'number':
            try:
                out[cle] = max(0, min(40, int(float(v))))
            except (TypeError, ValueError):
                out[cle] = defaut
        elif typ == 'select':
            out[cle] = v if v in POLICES else defaut
    return out


def variables_effectives(theme_variables, personnalisation=None):
    """Thème + réglages propres à la structure (qui priment)."""
    base = dict(DEFAUT)
    base.update(theme_variables or {})
    base.update({k: v for k, v in (personnalisation or {}).items() if v is not None and v != ''})
    return normaliser_variables(base)


def est_defaut(variables):
    return normaliser_variables(variables) == normaliser_variables(DEFAUT)


# ------------------------------------------------------------------ CSS
def generer_css(variables):
    """Feuille CSS injectée dans <head> (après les styles de base.html) —
    chaîne vide si tout est à la valeur d'origine (aucun impact)."""
    v = normaliser_variables(variables)
    if est_defaut(v):
        return ''
    p, pf, b, bt = v['primaire'], v['primaire_fonce'], v['bouton'], v['bouton_texte']
    fond, carte, texte = v['fond'], v['carte_fond'], v['texte']
    nb_fond, nb_texte, rayon = v['navbar_fond'], v['navbar_texte'], v['rayon']
    police = v['police']
    pr, pg, pb = _rgb(p)
    css = []
    if police in POLICES_GOOGLE:
        css.append(f"@import url('https://fonts.googleapis.com/css2?family={police.replace(' ', '+')}:wght@300;400;500;600;700&display=swap');")
    css.append(f""":root {{ --th-primaire: {p}; --th-primaire-fonce: {pf}; --th-bouton: {b}; --th-fond: {fond}; --th-carte: {carte}; --th-texte: {texte};
  --bs-primary: {p}; --bs-primary-rgb: {pr}, {pg}, {pb}; --bs-link-color: {p}; --bs-link-hover-color: {pf}; --bs-link-color-rgb: {pr}, {pg}, {pb}; }}
body, .btn, .form-control, .form-select, .navbar, .top-nav, .table {{ font-family: '{police}', 'Segoe UI', sans-serif !important; }}
body {{ background-color: {fond} !important; {'background-image: none !important;' if not v['fond_image'] else ''} }}
.main-content {{ background-color: {_rgba(carte, 0.94)} !important; color: {texte}; border-radius: {rayon}px !important; }}
.card {{ border-radius: {max(4, rayon - 3)}px !important; }}
.btn {{ border-radius: {max(4, rayon // 2 + 2)}px !important; }}
.navbar {{ background: {nb_fond} !important; }}
.navbar .structure-name, .navbar .nav-link, .navbar .navbar-brand, .navbar .text-dark {{ color: {nb_texte} !important; }}
.top-nav {{ background: {nb_fond} !important; border-bottom-color: {_rgba(nb_texte, 0.12)} !important; }}
.top-nav .nav-link-top {{ color: {nb_texte} !important; }}
.top-nav .nav-link-top:hover, .top-nav .nav-link-top.active {{ color: {p} !important; border-bottom-color: {p} !important; background: {_rgba(p, 0.08)} !important; }}
.sidebar {{ background: linear-gradient(135deg, {pf} 0%, {_assombrir(pf, 0.7)} 100%) !important; border-radius: {rayon}px !important; }}
.btn-primary {{ background: {_rgba(b, 0.12)} !important; color: {_assombrir(b, 0.8)} !important; border: 1px solid {_rgba(b, 0.3)} !important; }}
.btn-primary:hover, .btn-primary:focus, .btn-primary:active {{ background: {b} !important; color: {bt} !important; border-color: transparent !important; box-shadow: 0 5px 15px {_rgba(b, 0.35)} !important; }}
.btn-outline-primary {{ color: {b} !important; border-color: {b} !important; }}
.btn-outline-primary:hover {{ background: {b} !important; color: {bt} !important; }}
.bg-primary, .badge.bg-primary, .card-header.bg-primary, .modal-header.bg-primary, .progress-bar {{ background-color: {p} !important; }}
.text-primary {{ color: {p} !important; }}
a:not(.btn):not(.nav-link):not(.nav-link-top):not(.dropdown-item):not(.list-group-item):not(.page-link) {{ color: {p}; }}
.card-modern .card-header {{ color: {texte} !important; }}
.card-modern .card-header i, .nav-tabs .nav-link.active {{ color: {p} !important; }}
.nav-tabs .nav-link.active {{ border-bottom-color: {p} !important; }}
.form-check-input:checked {{ background-color: {p} !important; border-color: {p} !important; }}
.form-control:focus, .form-select:focus {{ border-color: {p} !important; box-shadow: 0 0 0 0.2rem {_rgba(p, 0.2)} !important; }}
.page-item.active .page-link {{ background-color: {p} !important; border-color: {p} !important; }}
.navbar-brand span {{ color: {nb_texte} !important; }}
.table thead th {{ background: {_rgba(p, 0.07)} !important; color: {texte} !important; }}""")
    if v['mode_sombre']:
        css.append(f"""/* mode sombre */
.main-content, .card, .modal-content, .dropdown-menu, .list-group-item, .offcanvas, .accordion-item, .table, .table-light, .table > :not(caption) > * > * {{ background-color: {carte} !important; color: {texte} !important; }}
.card-header, .card-footer, .modal-header, .modal-footer {{ background-color: {_assombrir(carte, 0.85)} !important; color: {texte} !important; border-color: {_rgba(texte, 0.1)} !important; }}
.card-header.bg-primary, .modal-header.bg-primary {{ background-color: {p} !important; }}
.card-header.bg-success, .card-header.bg-danger, .card-header.bg-warning, .card-header.bg-info, .card-header.bg-dark, .card-header.bg-secondary, .modal-header.bg-success, .modal-header.bg-danger, .modal-header.bg-info, .modal-header.bg-dark, .modal-header.bg-secondary {{ background-color: inherit; }}
.form-control, .form-select, .input-group-text {{ background-color: {_assombrir(carte, 0.8)} !important; color: {texte} !important; border-color: {_rgba(texte, 0.2)} !important; }}
.form-control::placeholder {{ color: {_rgba(texte, 0.5)} !important; }}
.text-muted, .text-dark, .text-secondary {{ color: {_rgba(texte, 0.7)} !important; }}
.bg-light, .table-light, .alert-light, .bg-white {{ background-color: {_assombrir(carte, 0.85)} !important; color: {texte} !important; }}
h1, h2, h3, h4, h5, h6, label, .form-label, .nav-tabs .nav-link {{ color: {texte}; }}
.table-hover > tbody > tr:hover > * {{ background-color: {_rgba(p, 0.12)} !important; color: {texte} !important; }}
.btn-light, .btn-outline-secondary, .btn-secondary {{ background-color: {_assombrir(carte, 0.8)} !important; color: {texte} !important; border-color: {_rgba(texte, 0.25)} !important; }}
.alert-info, .alert-warning, .alert-success, .alert-danger {{ color: #111 !important; }}
.card-modern .card-header {{ color: {texte} !important; }}
body::after {{ color: {_rgba(p, 0.25)} !important; }}""")
    return '\n'.join(css)


# ------------------------------------------------------------------ licences
def etat_licence(payant, licence=None, aujourd_hui=None):
    """État d'utilisation d'un thème pour une structure :
    {'etat': 'gratuit'|'paye'|'essai'|'expire'|'aucune', 'utilisable': bool,
     'jours_restants': int|None, 'fin_essai': date|None}.
    `licence` : objet/dict avec paye, fin_essai (date) — None si jamais activé."""
    aujourd_hui = aujourd_hui or date.today()
    if not payant:
        return {'etat': 'gratuit', 'utilisable': True, 'jours_restants': None, 'fin_essai': None}
    if licence is None:
        return {'etat': 'aucune', 'utilisable': False, 'jours_restants': None, 'fin_essai': None}
    get = (lambda k: licence.get(k)) if isinstance(licence, dict) else (lambda k: getattr(licence, k, None))
    if get('paye'):
        return {'etat': 'paye', 'utilisable': True, 'jours_restants': None, 'fin_essai': get('fin_essai')}
    fin = get('fin_essai')
    if fin and aujourd_hui <= fin:
        return {'etat': 'essai', 'utilisable': True, 'jours_restants': (fin - aujourd_hui).days + 1, 'fin_essai': fin}
    return {'etat': 'expire', 'utilisable': False, 'jours_restants': 0, 'fin_essai': fin}


def fin_essai_depuis(debut, jours):
    """Dernier jour inclus de l'essai (14 jours à partir du 1er -> le 14)."""
    return debut + timedelta(days=max(0, int(jours or 0)) - 1)


def libelle_etat(etat_info, theme=None):
    e = etat_info['etat']
    if e == 'gratuit':
        return 'Gratuit'
    if e == 'paye':
        return 'Payé — activé'
    if e == 'essai':
        j = etat_info['jours_restants']
        return f"Essai : {j} jour{'s' if j > 1 else ''} restant{'s' if j > 1 else ''}"
    if e == 'expire':
        return 'Essai terminé'
    if theme:
        return f"Payant — {int(theme.get('prix') or 0):,} F / essai {theme.get('jours_essai') or 0} jours".replace(',', ' ')
    return 'Payant'
