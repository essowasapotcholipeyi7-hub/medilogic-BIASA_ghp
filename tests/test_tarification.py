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
