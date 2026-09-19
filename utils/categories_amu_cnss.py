# utils/categories_amu_cnss.py
# ============================================================
# Les 21 catégories du formulaire officiel "FACTURE AMU" (CNSS Togo),
# dans l'ordre exact du PDF fourni — la clé (col. 1) sert d'identifiant
# stable en base (ClassificationAmuCnss.categorie,
# FactureAmuMensuelle.lignes[].categorie), le libellé (col. 2) est celui
# affiché/imprimé.
#
# Le jour où le patron envoie le formulaire AMU-INAM, ajouter une liste
# CATEGORIES_AMU_INAM du même format ici et brancher
# FactureAmuMensuelle.type_amu == 'inam' dessus — aucune autre
# modification structurelle nécessaire (voir services/facturation_amu_service.py).
# ============================================================

CATEGORIES_AMU_CNSS = [
    ('consultation_generale', 'Consultation de médecine générale'),
    ('consultation_enfant', 'Consultation enfant de moins de 5 ans'),
    ('consultation_specialite', 'Consultation de Spécialité'),
    ('consultation_prenatale', 'Consultation prénatale'),
    ('hospitalisation', 'Hospitalisation (frais de séjour)'),
    ('imagerie', "Actes d'imagerie médicale"),
    ('biologie', 'Actes de biologie médicale'),
    ('chirurgicaux', "Actes chirurgicaux (toutes interventions chirurgicales et petites chirurgies)"),
    ('actes_medicaux', 'Actes médicaux'),
    ('soins_infirmiers', 'Soins infirmiers'),
    ('accouchement', 'Accouchement par voie basse (acte)'),
    ('cesarienne', 'Césarienne (acte)'),
    ('ophtalmologie', "Actes d'ophtalmologie"),
    ('odonto_stomatologie', "Actes d'odonto-stomatologie"),
    ('orl', "Actes d'ORL"),
    ('reeducation', 'Rééducation fonctionnelle'),
    ('pharmacie', 'Produits pharmaceutiques'),
    ('hydrotherapie', 'Hydrothérapie/balnéothérapie, thermothérapie, physiothérapie'),
    ('transport', "Transport de malade à l'intérieur du pays"),
    ('lunetterie', 'Lunetterie médicale'),
    ('protheses', 'Prothèses et fournitures de fabrication'),
    ('autres', 'Autres'),
]

CATEGORIES_AMU_CNSS_DICT = dict(CATEGORIES_AMU_CNSS)

# Catégories déduites automatiquement (voir generer_lignes_facture_amu_cnss)
# — ne nécessitent aucune classification manuelle par acte.
CATEGORIE_HOSPITALISATION = 'hospitalisation'
CATEGORIE_PHARMACIE = 'pharmacie'


def categories_par_type(type_amu):
    if type_amu == 'cnss':
        return CATEGORIES_AMU_CNSS
    return CATEGORIES_AMU_CNSS
