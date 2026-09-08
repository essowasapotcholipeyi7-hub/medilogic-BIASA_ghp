# utils/categorisation.py
# ============================================================
# CATÉGORISATION DES ACTES PAR CODE
# ============================================================

import re

# ⭐ Correspondance code → catégorie
CATEGORIES = {
    # Hospitalisation
    'P160': 'hospitalisation',
    
    # Lunettes
    'D000293': 'lunettes',
    
    # Consultation (S100 à S130)
    **{f'S{i}': 'consultation' for i in range(100, 131)},
    
    # Laboratoire (R100 à R919)
    **{f'R{i}': 'laboratoire' for i in range(100, 920)},
    
    # Imagerie (Q100 à Q510)
    **{f'Q{i}': 'imagerie' for i in range(100, 511)},
}


# ⭐ Correspondance catégorie → compte comptable (plan SYSCOHADA, voir
# utils/plan_comptable_syscohada.py, source unique de vérité pour les numéros)
COMPTE_PAR_CATEGORIE = {
    'laboratoire': '7062',       # Actes de laboratoire
    'imagerie': '7063',          # Imagerie médicale
    'hospitalisation': '7064',   # Hospitalisation
    'consultation': '7061',      # Consultations
    'lunettes': '7012',          # Ventes de lunetterie / optique
    'autres': '7068',            # Autres prestations médicales
    'pharmacie': '7011',         # Ventes de pharmacie
}


def extraire_code_acte(nom_acte):
    """
    Extrait le code du nom d'un acte
    Exemple: "R100 Hémogramme" → "R100"
    """
    if not nom_acte:
        return None
    
    # ⭐ Prendre le premier mot
    mots = str(nom_acte).strip().split()
    if not mots:
        return None
    
    premier_mot = mots[0].upper().strip()
    
    # ⭐ Vérifier si c'est un code valide
    patterns = [
        r'^P160$',           # Hospitalisation
        r'^D000293$',        # Lunettes
        r'^S1[0-2][0-9]$',   # S100 à S129
        r'^S130$',           # S130
        r'^R[1-9][0-9]{2}$', # R100 à R919
        r'^Q[1-5][0-9]{2}$', # Q100 à Q510
    ]
    
    for pattern in patterns:
        if re.match(pattern, premier_mot):
            return premier_mot
    
    # ⭐ Vérifier si le code est collé avec le nom
    for pattern in patterns:
        match = re.search(pattern, nom_acte.upper())
        if match:
            return match.group()
    
    return None


def get_categorie_par_code(code):
    """
    Retourne la catégorie d'un acte à partir de son code
    """
    if not code:
        return 'inconnu'
    
    code = code.upper().strip()
    
    # ⭐ Vérifier dans le dictionnaire
    if code in CATEGORIES:
        return CATEGORIES[code]
    
    # ⭐ Plages (fallback)
    if len(code) >= 2:
        lettre = code[0]
        try:
            numero = int(code[1:])
            if lettre == 'S' and 100 <= numero <= 130:
                return 'consultation'
            if lettre == 'R' and 100 <= numero <= 919:
                return 'laboratoire'
            if lettre == 'Q' and 100 <= numero <= 510:
                return 'imagerie'
        except ValueError:
            pass
    
    return 'inconnu'


def get_compte_par_categorie(categorie):
    """
    Retourne le compte comptable pour une catégorie
    """
    return COMPTE_PAR_CATEGORIE.get(categorie, '7068')


def categoriser_acte(nom_acte):
    """
    Catégorise un acte et retourne (categorie, compte, code)
    """
    code = extraire_code_acte(nom_acte)
    
    if not code:
        return {
            'categorie': 'autres',
            'compte': '7068',
            'code': None
        }

    categorie = get_categorie_par_code(code)

    if categorie != 'inconnu':
        compte = get_compte_par_categorie(categorie)
        return {
            'categorie': categorie,
            'compte': compte,
            'code': code
        }

    # ⭐ Code inconnu → Autres produits
    return {
        'categorie': 'autres',
        'compte': '7068',
        'code': code
    }