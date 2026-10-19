"""Règles de tarification/répartition des actes (services/tarification_service.py)
— les 6 exemples de vérification du patron (2026-10-04) + cas limites.
Purs, sans DB."""

import pytest

from services.tarification_service import repartir_ligne, repartir_panier, tarif_unitaire


def ctx(amu=False, taux_amu=0, privee=False, taux_privee=0, pbr_prive=None, tarif_prive=None, nom='Acte', **extra):
    entree = None
    if pbr_prive is not None or tarif_prive is not None:
        entree = {'pbr_1': pbr_prive, 'pbr_2': None, 'tarif_prive': tarif_prive}
    c = {'amu': amu, 'taux_amu': taux_amu, 'privee': privee, 'taux_privee': taux_privee,
         'pbr_prive_par_acte': {nom: entree} if entree else {}, 'variante': 'defaut'}
    c.update(extra)
    return c


def arrondi(r):
    return (round(r['part_amu']), round(r['part_privee']), round(r['part_patient']))


@pytest.mark.parametrize("label, article, contexte, attendu", [
    ("Ex1 AMU + GTA avec PBR GTA 8 500", {'nom': 'Acte', 'prix': 15000, 'pbr': 5250, 'quantite': 1},
     ctx(amu=True, taux_amu=80, privee=True, taux_privee=80, pbr_prive=8500), (4200, 6800, 4000)),
    ("Ex2 AMU + GTA sans PBR GTA", {'nom': 'Acte', 'prix': 15000, 'pbr': 5250, 'quantite': 1},
     ctx(amu=True, taux_amu=80, privee=True, taux_privee=80), (4200, 8640, 2160)),
    ("Ex3 GTA seule avec PBR 8 500", {'nom': 'Acte', 'prix': 15000, 'pbr': 5250, 'quantite': 1},
     ctx(privee=True, taux_privee=80, pbr_prive=8500), (0, 6800, 8200)),
    ("Ex4 GTA seule sans PBR", {'nom': 'Acte', 'prix': 15000, 'pbr': 5250, 'quantite': 1},
     ctx(privee=True, taux_privee=80), (0, 12000, 3000)),
    ("Ex5 AMU seule", {'nom': 'Acte', 'prix': 10000, 'pbr': 5250, 'quantite': 1},
     ctx(amu=True, taux_amu=80), (4200, 0, 5800)),
    ("Ex6 Non assuré", {'nom': 'Acte', 'prix': 10000, 'pbr': 5250, 'quantite': 1},
     ctx(), (0, 0, 10000)),
])
def test_six_exemples_du_patron(label, article, contexte, attendu):
    assert arrondi(repartir_ligne(article, contexte)) == attendu, label


def test_pbr_prive_superieur_au_reste_apres_amu():
    """Cas 4 avec PBR privé : part privée = taux x PBR privé (pas réduite par
    l'AMU), mais jamais plus que ce qui reste après l'AMU."""
    article = {'nom': 'Acte', 'prix': 15000, 'pbr': 5250, 'quantite': 1}
    r = repartir_ligne(article, ctx(amu=True, taux_amu=80, privee=True, taux_privee=80, pbr_prive=12000))
    assert arrondi(r) == (4200, 9600, 1200)
    # PBR privé énorme : la part privée est plafonnée au reste (patient = 0, jamais négatif)
    r = repartir_ligne(article, ctx(amu=True, taux_amu=80, privee=True, taux_privee=100, pbr_prive=50000))
    assert arrondi(r) == (4200, 10800, 0)


def test_tarif_prive_remplace_le_prix_de_base():
    """Cas 3/4 : le tarif appliqué est le tarif privé de la compagnie."""
    article = {'nom': 'Acte', 'prix': 10000, 'pbr': 5250, 'quantite': 1}
    c = ctx(privee=True, taux_privee=80, tarif_prive=15000, pbr_prive=8500)
    assert tarif_unitaire(article, c) == (15000, 'prive')
    assert arrondi(repartir_ligne(article, c)) == (0, 6800, 8200)
    # tarif privé sans PBR : part privée = taux x tarif privé
    c = ctx(privee=True, taux_privee=80, tarif_prive=15000)
    assert arrondi(repartir_ligne(article, c)) == (0, 12000, 3000)


def test_prix_non_assure_uniquement_sans_aucune_assurance():
    article = {'nom': 'Acte', 'prix': 10000, 'pbr': 5250, 'prix_non_assure': 12000, 'quantite': 1}
    assert tarif_unitaire(article, ctx()) == (12000, 'non_assure')
    assert arrondi(repartir_ligne(article, ctx())) == (0, 0, 12000)
    # dès qu'une assurance s'applique, on revient au prix AMU / tarif privé
    assert tarif_unitaire(article, ctx(amu=True, taux_amu=80)) == (10000, 'base')
    assert tarif_unitaire(article, ctx(privee=True, taux_privee=80)) == (10000, 'base')
    # prix non assuré absent -> prix AMU par défaut (cas 1, "ou prix AMU si non défini")
    assert tarif_unitaire({'nom': 'Acte', 'prix': 10000, 'pbr': 5250}, ctx()) == (10000, 'base')


def test_variante_pbr_prive_par_ligne():
    """Le choix habituel/alternatif se fait ligne par ligne : une ligne peut
    prendre l'alternatif alors que le contexte (panier) reste sur l'habituel."""
    entree = {'pbr_1': 8500, 'pbr_2': 12000, 'tarif_prive': None}
    c = {'amu': False, 'taux_amu': 0, 'privee': True, 'taux_privee': 80,
         'pbr_prive_par_acte': {'Acte': entree}, 'variante': 'defaut'}
    base = {'nom': 'Acte', 'prix': 15000, 'pbr': 5250, 'quantite': 1}
    assert round(repartir_ligne(base, c)['part_privee']) == 6800
    assert round(repartir_ligne(dict(base, pbr_variante='alternatif'), c)['part_privee']) == 9600
    # et inversement : contexte alternatif, ligne forcée en habituel
    assert round(repartir_ligne(dict(base, pbr_variante='defaut'), dict(c, variante='alternatif'))['part_privee']) == 6800


def test_pbr_amu_absent_ou_zero():
    """PBR absent -> le tarif sert de base AMU ; PBR explicitement 0 (pharmacie :
    produit non pris en charge) -> aucune part AMU."""
    c = ctx(amu=True, taux_amu=80)
    assert round(repartir_ligne({'nom': 'Produit', 'prix': 1000, 'quantite': 2}, c)['part_amu']) == 1600
    assert round(repartir_ligne({'nom': 'Produit', 'prix': 1000, 'pbr': '', 'quantite': 2}, c)['part_amu']) == 1600
    assert repartir_ligne({'nom': 'Produit', 'prix': 1000, 'pbr': 0, 'quantite': 2}, c)['part_amu'] == 0


def test_base_amu_plafonnee_au_tarif():
    """PBR AMU supérieur au tarif : l'AMU ne rembourse pas plus que le tarif."""
    r = repartir_ligne({'nom': 'Acte', 'prix': 4000, 'pbr': 5250, 'quantite': 1}, ctx(amu=True, taux_amu=80))
    assert arrondi(r) == (3200, 0, 800)


def test_taux_amu_par_article_p160_o101():
    c = ctx(amu=True, taux_amu=80)
    assert round(repartir_ligne({'nom': 'P160 Chambre', 'prix': 10000, 'pbr': 10000, 'quantite': 2}, c)['part_amu']) == 18000
    assert round(repartir_ligne({'nom': 'O101 Oxygène', 'prix': 5000, 'pbr': 5000, 'quantite': 1}, c)['part_amu']) == 5000


def test_articles_non_pris_en_charge():
    article = {'nom': 'Acte', 'prix': 10000, 'pbr': 5250, 'quantite': 1, 'prise_en_charge_amu': False, 'prise_en_charge_cac': False}
    r = repartir_ligne(article, ctx(amu=True, taux_amu=80, privee=True, taux_privee=80, pbr_prive=8500))
    assert arrondi(r) == (0, 0, 10000)


def test_panier_complet_amu_plus_privee():
    """Panier : Ex1 (15 000, PBR GTA 8 500) + Ex2-like acte sans PBR GTA (15 000)
    + un acte 10 000 x 2 non pris en charge par la privée."""
    articles = [
        {'nom': 'Scanner', 'prix': 15000, 'pbr': 5250, 'quantite': 1},
        {'nom': 'Echo', 'prix': 15000, 'pbr': 5250, 'quantite': 1},
        {'nom': 'Consultation', 'prix': 10000, 'pbr': 5250, 'quantite': 2, 'prise_en_charge_cac': False},
    ]
    c = ctx(amu=True, taux_amu=80, privee=True, taux_privee=80, pbr_prive=8500, nom='Scanner')
    p = repartir_panier(articles, c)
    assert p['sous_total'] == 50000
    # AMU : 4200 + 4200 + 2 x 4200 = 16 800 ; base remboursement = 5250 x 4 = 21 000
    assert round(p['part_amu']) == 16800 and round(p['base_remboursement']) == 21000
    # privée : Scanner 6 800 (PBR) + Echo 8 640 (reste) + Consultation 0 (non prise en charge)
    assert round(p['part_privee']) == 15440
    assert round(p['net_a_payer']) == 50000 - 16800 - 15440


def test_panier_aide_hospitaliere():
    articles = [{'nom': 'Acte', 'prix': 10000, 'pbr': 5250, 'quantite': 1}]
    p = repartir_panier(articles, ctx(amu=True, taux_amu=80, taux_aide=50, type_aide='pourcentage'))
    assert round(p['reste_apres_assurances']) == 5800 and round(p['aide_hospitaliere']) == 2900 and round(p['net_a_payer']) == 2900
    p = repartir_panier(articles, ctx(amu=True, taux_amu=80, taux_aide=10000, type_aide='montant'))
    assert round(p['aide_hospitaliere']) == 5800 and p['net_a_payer'] == 0
    p = repartir_panier(articles, ctx(taux_aide=150, type_aide='pourcentage'))
    assert p['net_a_payer'] == 0  # % plafonné à 100


def test_pbr_prive_saisi_a_la_main_sans_pbr_enregistre():
    """Patron (2026-10-05) : sans PBR enregistré chez la compagnie, le taux privé
    s'appliquerait au prix clinique ; un PBR privé saisi sur la ligne sert de
    base à la place. Le PBR AMU ne change pas."""
    article = {'nom': 'Echo', 'prix': 15000, 'pbr': 5250, 'quantite': 1, 'pbr_prive_modifie': 8000}
    r = repartir_ligne(article, ctx(amu=True, taux_amu=80, privee=True, taux_privee=80))
    # AMU 80 % x 5 250 = 4 200 (inchangé) ; privée 80 % x 8 000 = 6 400 ; patient 4 400
    assert arrondi(r) == (4200, 6400, 4400) and r['base_amu'] == 5250
    # Privée seule : 80 % x 8 000 au lieu de 80 % x 15 000
    r = repartir_ligne(article, ctx(privee=True, taux_privee=80))
    assert arrondi(r) == (0, 6400, 8600)
    # Vide / 0 / absent = règle normale (taux sur le reste)
    for vide in (None, '', 0):
        r = repartir_ligne(dict(article, pbr_prive_modifie=vide), ctx(privee=True, taux_privee=80))
        assert arrondi(r) == (0, 12000, 3000)


def test_pbr_prive_saisi_plafonne_et_quantite():
    """La part privée reste plafonnée au reste après AMU, et le PBR saisi est
    unitaire (multiplié par la quantité)."""
    article = {'nom': 'Echo', 'prix': 10000, 'pbr': 5250, 'quantite': 2, 'pbr_prive_modifie': 9000}
    r = repartir_ligne(article, ctx(amu=True, taux_amu=80, privee=True, taux_privee=100))
    # total 20 000 ; AMU 2 x 4 200 = 8 400 ; privée 100 % x 18 000 = 18 000 plafonnée au reste 11 600
    assert arrondi(r) == (8400, 11600, 0)


def test_assurance_decochee_sur_la_ligne_patron_2026_10_15():
    """« Si on désactive un article pour une assurance, l'article se comporte comme
    non assuré » — sauf si l'AMU prend encore l'article (prix de base / PBR AMU).
    Exemple du patron : consultation génétique médicale, patient ASK AFRICA (80 %)
    qui n'est plus couvert. Prix non assuré distinct du prix clinique pour bien voir."""
    base = {'nom': 'S101 Consultation specialisee (GENETIQUE MEDICALE)', 'prix': 10000, 'pbr': 5250,
            'prix_non_assure': 9000, 'quantite': 1}
    ask = dict(privee=True, taux_privee=80, pbr_prive=8500, tarif_prive=15000, nom=base['nom'])
    # ASK seule, cochée : tarif privé
    assert tarif_unitaire(base, ctx(**ask)) == (15000, 'prive')
    assert arrondi(repartir_ligne(base, ctx(**ask))) == (0, 6800, 8200)
    # ASK seule, décochée sur la ligne : comme un non-assuré
    sans_ask = {**base, 'prise_en_charge_cac': False}
    assert tarif_unitaire(sans_ask, ctx(**ask)) == (9000, 'non_assure')
    assert arrondi(repartir_ligne(sans_ask, ctx(**ask))) == (0, 0, 9000)
    # AMU + ASK, ASK décochée : cas AMU seule (prix de base, part AMU sur le PBR AMU)
    amu_ask = dict(amu=True, taux_amu=80, **ask)
    assert tarif_unitaire(sans_ask, ctx(**amu_ask)) == (10000, 'base')
    assert arrondi(repartir_ligne(sans_ask, ctx(**amu_ask))) == (4200, 0, 5800)
    # AMU + ASK, AMU décochée : cas privée seule (tarif privé)
    sans_amu = {**base, 'prise_en_charge_amu': False}
    assert tarif_unitaire(sans_amu, ctx(**amu_ask)) == (15000, 'prive')
    assert arrondi(repartir_ligne(sans_amu, ctx(**amu_ask))) == (0, 6800, 8200)
    # AMU + ASK, les deux décochées (ou valeurs texte 'FALSE' venant du catalogue) : non assuré
    aucune = {**base, 'prise_en_charge_amu': 'FALSE', 'prise_en_charge_cac': False}
    assert tarif_unitaire(aucune, ctx(**amu_ask)) == (9000, 'non_assure')
    assert arrondi(repartir_ligne(aucune, ctx(**amu_ask))) == (0, 0, 9000)


# ⭐ 2026-10-16 (patron) : taux AMU particuliers
from services.tarification_service import taux_amu_article, code_acte


@pytest.mark.parametrize("nom, taux, publique, attendu", [
    ('S102 Consultation en pediatrie (Enfants 0 a 05 ans)', 80, False, 100),
    ('S113 Consultation specialisee interne pour enfant de 0 a 5 ans', 80, False, 100),
    ('S102 Consultation en pediatrie (Enfants 0 a 05 ans)', 0, False, 0),      # non assuré : jamais d'AMU
    ('K233 Cesarienne dans les formations sanitaires publiques', 80, True, 100),
    ('K233 Cesarienne dans les formations sanitaires publiques', 80, False, 80),  # structure privée
    ('K223 Cesarienne', 80, True, 80),
    ('K211 Cesarienne', 80, True, 80),
    ('O101 - Oxygénothérapie', 80, False, 100),
    ('P160 Hospitalisation', 80, False, 90),
    ('S101 Consultation specialisee', 80, True, 80),
    ('Consultation S1020 sans code en tête', 80, True, 80),
])
def test_taux_amu_particuliers(nom, taux, publique, attendu):
    assert taux_amu_article(nom, taux, publique) == attendu


def test_code_acte():
    assert code_acte('  S102 Consultation') == 'S102'
    assert code_acte('O101 - Oxygénothérapie') == 'O101'
    assert code_acte('Consultation') == ''


def test_pediatrie_0_5_ans_100_pour_cent_du_pbr_patron_2026_10_16():
    # Cabinet Médical Élite : S102 à 8 000, PBR AMU 5 250 -> l'AMU rembourse 5 250, le patient paie 2 750
    art = {'nom': 'S102 Consultation en pediatrie (Enfants 0 a 05 ans)', 'prix': 8000, 'pbr': 5250, 'quantite': 1}
    assert arrondi(repartir_ligne(art, ctx(amu=True, taux_amu=80, nom=art['nom']))) == (5250, 0, 2750)
    # le surplus est couvert par l'assurance privée s'il y en a une (comme d'habitude)
    assert arrondi(repartir_ligne(art, ctx(amu=True, taux_amu=80, privee=True, taux_privee=100, nom=art['nom'])))[0] == 5250


def test_cesarienne_k233_publique_seulement_patron_2026_10_16():
    art = {'nom': 'K233 Cesarienne dans les formations sanitaires publiques', 'prix': 10000, 'pbr': 10000, 'quantite': 1}
    assert arrondi(repartir_ligne(art, ctx(amu=True, taux_amu=80, structure_publique=True))) == (10000, 0, 0)
    assert arrondi(repartir_ligne(art, ctx(amu=True, taux_amu=80, structure_publique=False))) == (8000, 0, 2000)


def test_bordereau_amu_mensuel_meme_taux_que_la_vente_patron_2026_10_16():
    # facture AMU mensuelle (CNSS / INAM) : avant, seul P160 était connu (O101 compté à 80 %)
    from services.facturation_amu_service import _part_amu_ligne
    assert _part_amu_ligne({'nom': 'O101 - Oxygénothérapie', 'prix': 5000, 'pbr': 5000, 'quantite': 2}, 80) == 10000
    assert _part_amu_ligne({'nom': 'S102 Consultation en pediatrie', 'prix': 8000, 'pbr': 5250, 'quantite': 1}, 80) == 5250
    assert _part_amu_ligne({'nom': 'K233 Cesarienne', 'prix': 10000, 'pbr': 10000, 'quantite': 1}, 80, True) == 10000
    assert _part_amu_ligne({'nom': 'K233 Cesarienne', 'prix': 10000, 'pbr': 10000, 'quantite': 1}, 80, False) == 8000
    assert _part_amu_ligne({'nom': 'S101 Consultation', 'prix': 8000, 'pbr': 5250, 'quantite': 1}, 80) == 4200
# ⭐ Un seul acte par code AMU dans une même vente (patron, 2026-10-17 — Cabinet Elite,
# Q436 éclaté en écho-doppler artériel / veineux / TSA / artério-veineux).
def test_un_seul_acte_par_code_amu_exemple_du_patron():
    from services.tarification_service import repartir_panier
    articles = [
        {'nom': 'Q436 Echodoppler artériel', 'prix': 40000, 'pbr': 17680, 'quantite': 1},
        {'nom': 'Q436 Echodoppler artério-veineux', 'prix': 50000, 'pbr': 17680, 'quantite': 1},
    ]
    r = repartir_panier(articles, {'amu': True, 'taux_amu': 80})
    assert round(r['part_amu']) == 14144            # une seule fois 80 % x 17 680
    assert round(r['net_a_payer']) == 75856          # 90 000 - 14 144
    assert articles[0].get('prise_en_charge_amu', True) is True and not articles[0].get('amu_doublon')
    assert articles[1]['prise_en_charge_amu'] is False and articles[1]['amu_doublon'] is True


def test_doublon_amu_couvert_par_la_complementaire():
    from services.tarification_service import repartir_panier
    articles = [
        {'nom': 'Q436 Echodoppler artériel', 'prix': 40000, 'pbr': 17680, 'quantite': 1},
        {'nom': 'Q436 Echodoppler veineux', 'prix': 40000, 'pbr': 17680, 'quantite': 1},
    ]
    r = repartir_panier(articles, {'amu': True, 'taux_amu': 80, 'privee': True, 'taux_privee': 80})
    # ligne 1 : AMU 14 144, privée 80 % x (40 000 - 14 144) ; ligne 2 : privée 80 % x 40 000
    assert round(r['part_amu']) == 14144
    assert round(r['part_privee']) == round(0.8 * (40000 - 14144) + 0.8 * 40000)


def test_meme_acte_sur_deux_lignes_et_chambre_restent_couverts():
    from services.tarification_service import repartir_panier
    articles = [
        {'nom': 'Q436 Echodoppler artériel', 'prix': 40000, 'pbr': 17680, 'quantite': 1},
        {'nom': 'Q436 Echodoppler artériel', 'prix': 40000, 'pbr': 17680, 'quantite': 1},
        {'nom': 'P160 Chambre commune', 'prix': 5000, 'pbr': 5000, 'quantite': 1},
        {'nom': 'P160 Chambre individuelle', 'prix': 10000, 'pbr': 5000, 'quantite': 1},
    ]
    r = repartir_panier(articles, {'amu': True, 'taux_amu': 80})
    assert not any(a.get('amu_doublon') for a in articles)
    assert round(r['part_amu']) == round(2 * 14144 + 5000 * 0.9 + 5000 * 0.9)


def test_regle_rejouable_quand_on_retire_le_premier_acte():
    from services.tarification_service import appliquer_code_amu_unique
    articles = [
        {'nom': 'Q436 Echodoppler artériel', 'prise_en_charge_amu': True},
        {'nom': 'Q436 Echodoppler veineux', 'prise_en_charge_amu': True},
    ]
    appliquer_code_amu_unique(articles)
    assert articles[1]['prise_en_charge_amu'] is False
    reste = articles[1:]                       # le premier acte est retiré de la proforma
    appliquer_code_amu_unique(reste)
    assert reste[0]['prise_en_charge_amu'] is True and 'amu_doublon' not in reste[0]


# ---------------------------------------------------------------- Clinique Valeo (patron, 2026-10-19)
@pytest.mark.parametrize("brut, attendu", [
    (3696, 3700), (9044, 9050), (4757, 4750), (10635, 10650), (2928, 2950), (1725, 1750), (1464, 1450), (0, 0), (25, 50),
])
def test_arrondi_part_patient_aux_50(brut, attendu):
    from services.tarification_service import arrondir_part_patient
    assert arrondir_part_patient(brut, 50) == attendu
    assert arrondir_part_patient(brut, 0) == brut


def test_panier_arrondi_par_defaut_parts_assurance_inchangees():
    # Radio du doigt (jour) : prix clinique AMU 9 000, PBR 6 630, AMU 80 % -> patient 3 696 -> 3 700
    articles = [{'nom': 'Q100 Examen radiologique du doigt', 'prix': 9000, 'pbr': 6630, 'quantite': 1}]
    r = repartir_panier(articles, {'amu': True, 'taux_amu': 80, 'arrondi': 50})
    assert round(r['part_amu']) == 5304
    assert r['net_a_payer'] == 3700 and round(r['arrondi']) == 4
    r = repartir_panier([dict(articles[0])], {'amu': True, 'taux_amu': 80})
    assert round(r['net_a_payer']) == 3696 and r['arrondi'] == 0


def test_liste_sma_choisie_par_ligne_patient_paie_le_tarif():
    listes = {'Liste SMA 25 %': {'R607 NFS': {'tarif_prive': 3750}, 'Q100 Doigt': {'tarif_prive': 5250}},
              'Liste SMA 20 %': {'R607 NFS': {'tarif_prive': 4000}}}
    articles = [{'nom': 'R607 NFS', 'prix': 6000, 'pbr': 3850, 'quantite': 1, 'liste_tarif': 'Liste SMA 20 %'},
                {'nom': 'Q100 Doigt', 'prix': 9000, 'pbr': 6630, 'quantite': 1, 'liste_tarif': 'Liste SMA 25 %'}]
    r = repartir_panier(articles, {'privee': True, 'taux_privee': 0, 'listes': listes})
    assert [l['tarif_unitaire'] for l in r['lignes']] == [4000, 5250]
    assert r['part_privee'] == 0 and r['net_a_payer'] == 9250


def test_liste_expatries_avec_assurance_du_patient():
    # Expatrié assuré 80 % : tarif 14 400, PBR 12 960 -> assurance 10 368, patient 4 032 (fichier Valeo)
    listes = {'Liste Expatriés': {'Q100 Doigt': {'tarif_prive': 14400, 'pbr_1': 12960}}}
    a = {'nom': 'Q100 Doigt', 'prix': 9000, 'pbr': 6630, 'quantite': 1, 'liste_tarif': 'Liste Expatriés'}
    r = repartir_ligne(a, {'privee': True, 'taux_privee': 80, 'listes': listes, 'pbr_prive_par_acte': {}})
    assert (r['tarif_unitaire'], round(r['part_privee']), round(r['part_patient'])) == (14400, 10368, 4032)


def test_tarifs_de_nuit_compagnie_et_non_assure():
    entree = {'tarif_prive': 12000, 'pbr_1': 10800, 'tarif_nuit': 14000, 'pbr_nuit': 10800}
    a = {'nom': 'Q100 Doigt', 'prix': 11500, 'pbr': 6630, 'quantite': 1, 'nuit': True}
    r = repartir_ligne(a, ctx(privee=True, taux_privee=80, nom='Q100 Doigt', **{'pbr_prive_par_acte': {'Q100 Doigt': entree}}))
    assert (r['tarif_unitaire'], round(r['part_privee']), round(r['part_patient'])) == (14000, 8640, 5360)
    jour = dict(a, nuit=False)
    assert repartir_ligne(jour, ctx(privee=True, taux_privee=80, **{'pbr_prive_par_acte': {'Q100 Doigt': entree}}))['tarif_unitaire'] == 12000
    na = {'nom': 'Q100 Doigt', 'prix': 11500, 'pbr': 6630, 'quantite': 1, 'nuit': True, 'prix_non_assure': 7000, 'prix_non_assure_nuit': 9500}
    assert repartir_ligne(na, ctx())['tarif_unitaire'] == 9500
    assert repartir_ligne(dict(na, nuit=False), ctx())['tarif_unitaire'] == 7000


def test_ligne_absente_de_la_liste_suit_l_assurance_reelle():
    # liste SMA choisie pour un non-assuré : un médicament absent de la liste reste au prix non assuré
    listes = {'Liste SMA 25 %': {'Q100 Doigt': {'tarif_prive': 5250}}}
    ctx_liste = {'privee': True, 'taux_privee': 0, 'listes': listes, 'privee_patient': False}
    medoc = {'nom': 'Paracetamol', 'prix': 1000, 'pbr': 0, 'quantite': 1, 'prix_non_assure': 1200, 'liste_tarif': 'Liste SMA 25 %'}
    assert repartir_ligne(medoc, ctx_liste)['tarif_unitaire'] == 1200
    # expatrié assuré SUNU : un acte absent de la liste prend le tarif SUNU et la part SUNU
    ctx_exp = {'privee': True, 'taux_privee': 80, 'privee_patient': True, 'listes': {'Liste Expatriés': {}},
               'pbr_prive_par_acte': {'Acte X': {'tarif_prive': 10000, 'pbr_1': None}}}
    r = repartir_ligne({'nom': 'Acte X', 'prix': 8000, 'pbr': 0, 'quantite': 1, 'liste_tarif': 'Liste Expatriés'}, ctx_exp)
    assert (r['tarif_unitaire'], round(r['part_privee'])) == (10000, 8000)


def test_sma_avec_assurance_reelle_ligne_hors_liste_couverte():
    # SMA choisie pour un patient assuré SUNU 80 % : la radio de la liste SMA n'a aucune part privée,
    # le médicament absent de la liste prend le tarif SUNU et SUNU en paie 80 %
    listes = {'Liste SMA 25 %': {'Q100': {'tarif_prive': 5250}}}
    ctx_sma = {'privee': True, 'taux_privee': 80, 'privee_patient': True, 'listes': listes,
               'listes_remise': {'Liste SMA 25 %'}, 'pbr_prive_par_acte': {'Medoc': {'tarif_prive': 1000, 'pbr_1': None}}}
    r = repartir_panier([{'nom': 'Q100', 'prix': 9000, 'pbr': 6630, 'quantite': 1, 'liste_tarif': 'Liste SMA 25 %'},
                         {'nom': 'Medoc', 'prix': 800, 'pbr': 0, 'quantite': 1, 'liste_tarif': 'Liste SMA 25 %'}], ctx_sma)
    assert [(l['tarif_unitaire'], round(l['part_privee'])) for l in r['lignes']] == [(5250, 0), (1000, 800)]


def test_sma_patient_amu_l_amu_paie_puis_reduction_sur_le_reste():
    # patron 19/10 : « AMU paie sa part et SMA s'applique sur le reste ». Radio du doigt 9 000 (PBR 6 630),
    # AMU 80 % -> 5 304 ; reste 3 696 ; SMA 25 % -> 924 ; patient 2 772 -> 2 750 arrondi
    listes = {'Liste SMA 25 %': {'Q100': {'tarif_prive': 5250}}}
    ctx_sma = {'amu': True, 'taux_amu': 80, 'privee': True, 'taux_privee': 0, 'listes': listes,
               'listes_remise': {'Liste SMA 25 %'}, 'remise_pct': {'Liste SMA 25 %': 25}, 'arrondi': 50}
    r = repartir_panier([{'nom': 'Q100', 'prix': 9000, 'pbr': 6630, 'quantite': 1, 'liste_tarif': 'Liste SMA 25 %'}], ctx_sma)
    l = r['lignes'][0]
    assert (l['tarif_unitaire'], round(l['part_amu']), round(l['reduction_liste']), round(l['part_patient'])) == (9000, 5304, 924, 2772)
    assert r['net_a_payer'] == 2750
    # AMU à 100 % (enfant 0-5 ans) : le patient ne paie rien
    r = repartir_panier([{'nom': 'S102 Consultation enfant', 'prix': 6000, 'pbr': 6000, 'quantite': 1, 'liste_tarif': 'Liste SMA 25 %'}],
                        dict(ctx_sma, listes={'Liste SMA 25 %': {'S102 Consultation enfant': {'tarif_prive': 4500}}}))
    assert r['net_a_payer'] == 0
    # patient non AMU : tarif SMA de la liste, sans réduction en plus
    r = repartir_panier([{'nom': 'Q100', 'prix': 9000, 'pbr': 6630, 'quantite': 1, 'liste_tarif': 'Liste SMA 25 %'}], dict(ctx_sma, amu=False))
    assert (r['lignes'][0]['tarif_unitaire'], r['reduction_liste'], r['net_a_payer']) == (5250, 0, 5250)


def test_categorie_chambre_deduite_du_nom_et_paliers():
    # séjour du 19/10 : « Cabine ventilée avec 2 lits » 18 jours sans catégorie AMU -> paliers de la grille
    from datetime import date
    from utils.grille_amu_hospitalisation import deduire_categorie_salle
    from services.hospitalisation_service import construire_lignes_chambre
    assert deduire_categorie_salle('P160 Hospitalisation Cabine ventillee avec 2 lits') == 'cabine'
    assert deduire_categorie_salle('P160 Hospitalisation Salle commune 3 a 6 lits') == 'salle_commune_3_6'
    assert deduire_categorie_salle('P160 Reanimation') == 'reanimation'
    assert deduire_categorie_salle('P160 Hospitalisation Salle commune') is None
    lignes = construire_lignes_chambre({'nom': 'P160 Hospitalisation Cabine ventillee avec 2 lits', 'prix': 7000, 'pbr': 5000},
                                       18, date(2026, 10, 1), [], True, niveau_soins='3')
    assert [(l['quantite'], l['pbr']) for l in lignes] == [(7, 5000), (7, 3375), (4, 1625)]
