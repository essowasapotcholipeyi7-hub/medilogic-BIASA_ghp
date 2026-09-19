# utils/categories_amu_inam.py
# ============================================================
# Les 6 sections (avec sous-totaux) et 21 lignes du formulaire officiel
# "FACTURE MENSUELLE" (INAM Togo, "Facture récapitulative INAM_MàJ.pdf"),
# dans l'ordre exact du PDF fourni — miroir de
# utils/categories_amu_cnss.py (CATEGORIES_AMU_CNSS), mais structuré en
# sections car le formulaire INAM regroupe ses lignes par sous-total
# (contrairement à la liste plate de 21 catégories de la CNSS).
#
# Chaque section : (cle_section, libelle_section, libelle_sous_total, [(cle_ligne, libelle_ligne), ...])
# ============================================================

CATEGORIES_AMU_INAM = [
    ('soins', 'Feuilles de soins (soins)', 'Sous-total 1', [
        ('soins_medecine', 'Médecine'),
        ('soins_pediatrie', 'Pédiatrie'),
        ('soins_gynecologie', 'Gynécologie'),
        ('soins_obstetrique', 'Obstétrique/Maternité'),
        ('soins_chirurgie', 'Chirurgie'),
        ('soins_orl', 'ORL'),
        ('soins_stomatologie', 'Stomatologie'),
        ('soins_ophtalmologie', 'Ophtalmologie'),
        ('soins_autres', 'Autres'),
    ]),
    ('ordonnance', 'Feuilles de soins (ordonnance)', 'Sous-total 2', [
        ('ordonnance_pharmacie', 'Produits pharmaceutiques'),
    ]),
    ('ep_hospit', "Entente préalable d'hospitalisation", 'Sous-total 3', [
        ('ep_hospit_medecine', 'Médecine'),
        ('ep_hospit_pediatrie', 'Pédiatrie'),
        ('ep_hospit_gynecologie', 'Gynécologie'),
        ('ep_hospit_obstetrique', 'Obstétrique/Maternité'),
        ('ep_hospit_chirurgie', 'Chirurgie'),
        ('ep_hospit_autres', 'Autres'),
    ]),
    ('hospit', "Feuilles d'Hospitalisation", 'Sous-total 4', [
        ('hospit_actes', 'Actes médicaux et paramédicaux'),
        ('hospit_pharmacie', 'Produits pharmaceutiques'),
    ]),
    ('examens', "Feuilles d'Examens Complémentaires", 'Sous-total 5', [
        ('examens_biologie', 'Biologie médicale'),
        ('examens_imagerie', 'Imagerie médicale'),
    ]),
    ('ep_lunetterie', 'Entente préalable Lunetterie', 'Sous-total 6', [
        ('ep_lunetterie_lunettes', 'Lunettes médicales'),
    ]),
]

# Vue à plat (cle_ligne, libelle_ligne) — pratique pour initialiser les
# compteurs et pour le select de classification manuelle.
CATEGORIES_AMU_INAM_PLATES = [
    (cle_ligne, libelle_ligne)
    for _, _, _, lignes in CATEGORIES_AMU_INAM
    for cle_ligne, libelle_ligne in lignes
]
CATEGORIES_AMU_INAM_DICT = dict(CATEGORIES_AMU_INAM_PLATES)

# Catégories déduites automatiquement (voir generer_lignes_facture_amu) —
# ne nécessitent aucune classification manuelle par acte.
CATEGORIE_HOSPITALISATION = 'hospit_actes'
CATEGORIE_PHARMACIE = 'ordonnance_pharmacie'

REGIMES_AMU_INAM = [
    ('ramo', 'RAMO'),
    ('school_amu', 'SCHOOL AMU'),
    ('wezou', 'WEZOU'),
    ('autres', 'AUTRES'),
]
