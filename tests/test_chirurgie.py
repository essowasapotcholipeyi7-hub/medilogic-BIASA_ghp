"""Proforma d'intervention chirurgicale (services/chirurgie_service.py) —
l'exemple papier du patron (Clinique chirurgicale, prothèse de hanche,
total 3 189 038 F) doit être reproduit au franc près. Purs, sans DB."""

from services.chirurgie_service import calculer_proforma, normaliser_entree, format_k, arrondi


def exemple(**surcharges):
    data = {
        'actes': [
            {'nom': 'Arthroplastie intéressant fémur et bassin gauches', 'k': 220, 'diviseur': 1},
            {'nom': 'Butée ostéoplastique', 'k': 100, 'diviseur': 2},
            {'nom': 'Comblement osseux', 'k': 80, 'diviseur': 2},
        ],
        'coef_supp': 15,
        'parametres': {'valeur_k': 1500, 'valeur_k_bloc': 1700, 'pct_second': 50,
                       'pct_anesthesie': 50, 'pct_bloc': 75, 'k_aide': 50, 'soins_jour': 5000},
        'chambre_nom': 'Chambre à deux lits', 'chambre_prix': 25000, 'jours': 15,
        'forfaits': [
            {'nom': "Location d'amplificateur", 'montant': 100000},
            {'nom': 'Prévision pharmacie', 'montant': 600000},
            {'nom': 'Prévision analyses', 'montant': 200000},
            {'nom': 'ECG', 'montant': 15000},
            {'nom': 'Prévision radiographie', 'montant': 35000},
            {'nom': 'Prévision kinésithérapie (20 séances)', 'montant': 180000},
            {'nom': 'Consultation pré-anesthésique', 'montant': 10000},
        ],
    }
    data.update(surcharges)
    return calculer_proforma(normaliser_entree(data))


def test_exemple_papier_au_franc_pres():
    r = exemple()
    assert r['base_k'] == 310
    assert r['k_supp'] == 46.5
    assert r['total_k'] == 356.5
    totaux = {l['designation']: l['total'] for l in r['lignes']}
    assert totaux['Chambre'] == 375000
    assert totaux['Acte'] == 534750
    assert totaux['Acte du second chirurgien'] == 267375
    assert totaux['Anesthésie'] == 267375
    assert totaux['Aide opératoire'] == 75000
    assert totaux['Bloc'] == 454538          # 1 700 × 267,375 = 454 537,5
    assert totaux['Soins infirmiers'] == 75000
    assert r['total'] == 3189038


def test_pourcentages_et_aide_variables():
    r = exemple(parametres={'valeur_k': 1500, 'valeur_k_bloc': 1700, 'pct_second': 0,
                            'pct_anesthesie': 40, 'pct_bloc': 60, 'k_aide': 30, 'soins_jour': 5000})
    noms = [l['designation'] for l in r['lignes']]
    assert 'Acte du second chirurgien' not in noms   # 0 % : ligne absente
    totaux = {l['designation']: l['total'] for l in r['lignes']}
    assert totaux['Anesthésie'] == arrondi(1500 * 356.5 * 0.40)
    assert totaux['Bloc'] == arrondi(1700 * 356.5 * 0.60)
    assert totaux['Aide opératoire'] == 45000


def test_saisie_texte_et_lignes_vides():
    r = calculer_proforma(normaliser_entree({
        'actes': [{'nom': 'Appendicectomie', 'k': '60', 'diviseur': ''}, {'nom': '', 'k': ''}],
        'coef_supp': '', 'chambre_prix': '15 000', 'jours': '3',
        'forfaits': [{'nom': 'ECG', 'montant': ''}, {'nom': '', 'montant': 5000}],
    }))
    assert r['total_k'] == 60
    assert [l['designation'] for l in r['lignes']][0] == 'Chambre'
    assert all(l['designation'] != 'ECG' for l in r['lignes'])   # forfait à 0 non imprimé


def test_format_k():
    assert format_k(356.5) == '356,5'
    assert format_k(267.375) == '267,375'
    assert format_k(220) == '220'
