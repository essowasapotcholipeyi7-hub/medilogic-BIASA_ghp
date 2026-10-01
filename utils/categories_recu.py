# utils/categories_recu.py
# ============================================================
# Classification des articles d'une facture pour le "reçu cumulé"
# (impression sans détail des articles, juste un total par catégorie :
# Consultation / Actes médicaux / Chirurgie / Séjours hospitaliers /
# Pharmacie). Réutilise la classification AMU/CNSS quand la structure
# l'a déjà configurée (classification_amu_cnss), sinon retombe sur des
# mots-clés dans le nom de l'article.
# ============================================================

ORDRE_CATEGORIES_RECU = [
    'Consultation',
    'Actes médicaux',
    'Chirurgie',
    'Séjours hospitaliers',
    'Pharmacie',
]

# Mappe les clés de CATEGORIES_AMU_CNSS vers nos 5 catégories de reçu.
_AMU_VERS_CATEGORIE_RECU = {
    'consultation_generale': 'Consultation',
    'consultation_enfant': 'Consultation',
    'consultation_specialite': 'Consultation',
    'consultation_prenatale': 'Consultation',
    'hospitalisation': 'Séjours hospitaliers',
    'chirurgicaux': 'Chirurgie',
    'actes_medicaux': 'Actes médicaux',
    'pharmacie': 'Pharmacie',
}

_MOTS_CLES_CATEGORIE = [
    ('Séjours hospitaliers', ('chambre', 'séjour', 'sejour', 'hospitalisation', 'lit ')),
    ('Consultation', ('consultation',)),
    ('Chirurgie', ('chirurg', 'opération', 'operation', 'intervention')),
]


def classifier_article_categorie(nom_article, type_article, classification_map):
    """Retourne le libellé de catégorie (voir ORDRE_CATEGORIES_RECU) pour un
    article de facture, afin de le regrouper sur le reçu cumulé.

    classification_map : dict {nom_acte: categorie_amu} déjà filtré sur la
    structure (voir ClassificationAmuCnss), vide si la structure n'a pas
    configuré l'AMU.
    """
    type_article = (type_article or '').lower()
    if 'produit' in type_article or 'pharmacie' in type_article:
        return 'Pharmacie'

    categorie_amu = classification_map.get(nom_article)
    if categorie_amu:
        libelle = _AMU_VERS_CATEGORIE_RECU.get(categorie_amu)
        if libelle:
            return libelle

    nom_lower = (nom_article or '').lower()
    for libelle, mots_cles in _MOTS_CLES_CATEGORIE:
        if any(mot in nom_lower for mot in mots_cles):
            return libelle

    return 'Actes médicaux'


def cumuler_articles_par_categorie(articles, classification_map):
    """Regroupe une liste d'articles (dicts avec 'nom'/'type'/'prix*'/'quantite')
    en totaux par catégorie, dans l'ordre d'ORDRE_CATEGORIES_RECU. Ne renvoie
    que les catégories ayant un total non nul.
    """
    totaux = {}
    for article in articles:
        nom = article.get('nom', '')
        type_article = article.get('type', 'acte')
        categorie = classifier_article_categorie(nom, type_article, classification_map)

        prix = article.get('prix_unitaire', article.get('prix', article.get('prix_reel', article.get('prix_vente', 0))))
        quantite = article.get('quantite', 1)
        try:
            total_ligne = float(prix or 0) * float(quantite or 1)
        except (TypeError, ValueError):
            total_ligne = 0

        totaux[categorie] = totaux.get(categorie, 0) + total_ligne

    cumul = [{'nom': cat, 'total': totaux[cat]} for cat in ORDRE_CATEGORIES_RECU if totaux.get(cat)]
    for categorie, total in totaux.items():
        if categorie not in ORDRE_CATEGORIES_RECU and total:
            cumul.append({'nom': categorie, 'total': total})
    return cumul
