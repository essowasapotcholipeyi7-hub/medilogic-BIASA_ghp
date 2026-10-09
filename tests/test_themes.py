"""Thèmes / apparence par structure (patron, 2026-10-09) — logique pure."""
from datetime import date

from utils.themes import (generer_css, normaliser_variables, variables_effectives, etat_licence,
                          fin_essai_depuis, DEFAUT, THEMES_DEFAUT, libelle_etat)


def test_apparence_origine_ne_genere_aucun_css():
    assert generer_css(DEFAUT) == ''
    assert generer_css({}) == ''


def test_css_reflete_les_couleurs_choisies():
    css = generer_css({'bouton': '#ff0000', 'fond': '#112233', 'fond_image': False, 'police': 'Poppins', 'rayon': 8})
    assert '--th-bouton: #FF0000' in css
    assert 'background-color: #112233 !important; background-image: none !important' in css
    assert "fonts.googleapis.com/css2?family=Poppins" in css
    assert '.main-content' in css and 'border-radius: 8px' in css
    assert 'mode sombre' not in css


def test_mode_sombre_ajoute_le_bloc_sombre():
    css = generer_css({'mode_sombre': True, 'carte_fond': '#1E293B', 'texte': '#E2E8F0'})
    assert '/* mode sombre */' in css and '.form-control, .form-select' in css


def test_normalisation_valeurs_invalides():
    v = normaliser_variables({'primaire': 'rouge', 'rayon': 'abc', 'police': 'Comic Sans', 'fond_image': 'false', 'bouton': '#abc'})
    assert v['primaire'] == DEFAUT['primaire'] and v['rayon'] == DEFAUT['rayon'] and v['police'] == 'Inter'
    assert v['fond_image'] is False and v['bouton'] == '#AABBCC'


def test_personnalisation_prime_sur_le_theme():
    v = variables_effectives({'primaire': '#111111', 'fond': '#222222'}, {'fond': '#333333', 'texte': ''})
    assert v['primaire'] == '#111111' and v['fond'] == '#333333' and v['texte'] == DEFAUT['texte']


def test_catalogue_par_defaut_valide():
    cles = [t['cle'] for t in THEMES_DEFAUT]
    assert 'classique' in cles and len(cles) == len(set(cles))
    for t in THEMES_DEFAUT:
        assert normaliser_variables(t['variables'])  # ne lève pas
        assert (t['payant'] and t['prix'] > 0) or (not t['payant'])


def test_etat_licence_gratuit_essai_paye_expire():
    auj = date(2026, 10, 9)
    assert etat_licence(False)['etat'] == 'gratuit'
    assert etat_licence(True, None)['etat'] == 'aucune' and not etat_licence(True, None)['utilisable']
    e = etat_licence(True, {'paye': False, 'fin_essai': fin_essai_depuis(auj, 14)}, auj)
    assert e['etat'] == 'essai' and e['utilisable'] and e['jours_restants'] == 14
    e = etat_licence(True, {'paye': False, 'fin_essai': date(2026, 10, 8)}, auj)
    assert e['etat'] == 'expire' and not e['utilisable']
    e = etat_licence(True, {'paye': True, 'fin_essai': date(2026, 10, 8)}, auj)
    assert e['etat'] == 'paye' and e['utilisable']
    assert libelle_etat({'etat': 'aucune'}, {'prix': 15000, 'jours_essai': 14}) == 'Payant — 15 000 F (une seule fois) / essai 14 jours'
    assert fin_essai_depuis(date(2026, 10, 1), 14) == date(2026, 10, 14)


def test_prix_payant_10000_une_fois():
    from utils.themes import PRIX_THEME_PAYANT, libelle_prix
    assert PRIX_THEME_PAYANT == 10000
    for t in THEMES_DEFAUT:
        assert (not t['payant']) or t['prix'] == 10000
    assert libelle_prix({'prix': 10000}) == '10 000 F (une seule fois)'
    assert len(THEMES_DEFAUT) >= 15 and len({t['cle'] for t in THEMES_DEFAUT}) == len(THEMES_DEFAUT)


def test_palette_depuis_logo():
    from utils.themes import palette_vers_variables
    # logo : beaucoup de blanc, un bleu dominant, un orange, du noir (contours)
    v, palette = palette_vers_variables([(5000, (255, 255, 255)), (900, (20, 90, 200)), (300, (240, 120, 30)), (400, (10, 10, 10)), (200, (128, 128, 128))])
    assert palette[0] == '#145AC8' and palette[1] == '#F0781E'
    assert v['primaire'] == '#145AC8' and v['bouton'] == '#F0781E' and v['fond_image'] is False
    assert v['navbar_fond'] == v['primaire_fonce'] and v['navbar_texte'] == '#FFFFFF'
    # rien d'exploitable
    assert palette_vers_variables([(100, (255, 255, 255)), (50, (0, 0, 0))]) == (None, [])


def test_css_nom_structure_lisible():
    css = generer_css({'navbar_fond': '#0B1220', 'navbar_texte': '#E2E8F0'})
    assert '.navbar .structure-brand .structure-name { color: #E2E8F0 !important; }' in css
    assert '.navbar .structure-brand { background: rgba(226, 232, 240, 0.1)' in css
