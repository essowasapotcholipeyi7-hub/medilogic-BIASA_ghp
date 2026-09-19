# services/facturation_amu_service.py
# ============================================================
# Génération du brouillon de la FACTURE AMU mensuelle (bordereau CNSS et
# INAM) — voir utils/categories_amu_cnss.py / utils/categories_amu_inam.py
# pour les catégories et models.py pour
# ClassificationAmuCnss/FactureAmuMensuelle.
# ============================================================

import json
from datetime import datetime, timedelta

from sqlalchemy import or_

from models import db, Vente, Patient, ClassificationAmuCnss
from utils.categories_amu_cnss import (
    CATEGORIES_AMU_CNSS, CATEGORIE_HOSPITALISATION as CATEGORIE_HOSPITALISATION_CNSS,
    CATEGORIE_PHARMACIE as CATEGORIE_PHARMACIE_CNSS,
)
from utils.categories_amu_inam import (
    CATEGORIES_AMU_INAM_PLATES, CATEGORIE_HOSPITALISATION as CATEGORIE_HOSPITALISATION_INAM,
    CATEGORIE_PHARMACIE as CATEGORIE_PHARMACIE_INAM,
)
from utils.nomenclature_amu_cnss import deviner_categorie_par_code as deviner_categorie_cnss
from utils.nomenclature_amu_inam import deviner_categorie_par_code as deviner_categorie_inam

# ⭐ Un seul endroit qui sait, pour un type d'AMU donné : le filtre
# Patient.type_assurance, la liste (plate) des catégories, les catégories
# auto-déduites (chambre/pharmacie), et la fonction de proposition
# automatique par code — tout le reste de generer_lignes_facture_amu()
# est identique pour les deux assureurs.
_CONFIG_PAR_TYPE = {
    'cnss': {
        'type_assurance': 'amu_cnss',
        'categories_plates': CATEGORIES_AMU_CNSS,
        'categorie_hospitalisation': CATEGORIE_HOSPITALISATION_CNSS,
        'categorie_pharmacie': CATEGORIE_PHARMACIE_CNSS,
        'deviner_categorie': deviner_categorie_cnss,
    },
    'inam': {
        'type_assurance': 'amu_inam',
        'categories_plates': CATEGORIES_AMU_INAM_PLATES,
        'categorie_hospitalisation': CATEGORIE_HOSPITALISATION_INAM,
        'categorie_pharmacie': CATEGORIE_PHARMACIE_INAM,
        'deviner_categorie': deviner_categorie_inam,
    },
}


def _taux_amu_pour_article(nom_article, taux_defaut):
    """Copie locale de app.py:taux_amu_pour_article() (P160 = 90%, reste =
    taux de la vente) — même raison de duplication que
    routes/statistiques.py:taux_amu_pour_article() et
    services/hospitalisation_service.py:_taux_amu_article() : éviter un
    import circulaire avec app.py."""
    return 90 if (nom_article and 'P160' in nom_article) else taux_defaut


def _part_amu_ligne(item, taux_defaut):
    """Part AMU d'UNE ligne (acte ou produit) — réplique la formule
    CANONIQUE utilisée à la création de la vente
    (api_convertir_proforma/api_facturer_hospitalisation, app.py) :
    min(prix, pbr) × quantité × taux / 100. ⭐ FIX : la version précédente
    (et calculer_montants_vente() dans routes/statistiques.py, dont
    celle-ci reprenait le calcul) oubliait à la fois la quantité et le
    plafonnement à min(prix, pbr) — une ligne à quantité 2 ou plus voyait
    sa part AMU sous-évaluée de moitié (ou plus), constaté sur des ventes
    réelles (ex. vente #1098 : 2× "S100 Consultation medecine generale" à
    3500F, part AMU stockée 5 600F, mais 2 800F recalculée ici avant ce
    correctif — le patron a demandé de vérifier que la Facture AMU CNSS/
    INAM concorde avec les montants réellement facturés)."""
    if not isinstance(item, dict) or not item.get('prise_en_charge_amu'):
        return 0.0
    pbr = float(item.get('pbr', 0) or 0)
    if pbr <= 0:
        return 0.0
    # ⭐ Un produit (médicament) porte son prix réellement vendu dans
    # `prix_reel` (peut différer du prix catalogue `prix`) — même priorité
    # que calculer_montants_vente() ; absent sur un acte, repli sur
    # prix/prix_unitaire comme avant.
    prix = float(item.get('prix_reel', item.get('prix', item.get('prix_unitaire', 0))) or 0)
    quantite = int(item.get('quantite', 1) or 1)
    taux_item = _taux_amu_pour_article(item.get('nom'), taux_defaut)
    return min(prix, pbr) * quantite * taux_item / 100


def charger_classification_amu(structure_id, type_amu):
    """{nom_acte: categorie} pour cette structure ET ce type d'AMU précis
    (les 21 catégories CNSS et INAM ne se recouvrent pas) — vide tant
    qu'aucun acte n'a été classé (tout atterrit alors dans "non_classes")."""
    entrees = ClassificationAmuCnss.query.filter_by(structure_id=structure_id, type_amu=type_amu).all()
    return {e.nom_acte: e.categorie for e in entrees}


def charger_classification_amu_cnss(structure_id):
    """Compat ascendante — équivaut à charger_classification_amu(structure_id, 'cnss')."""
    return charger_classification_amu(structure_id, 'cnss')


def generer_lignes_facture_amu(structure_id, annee, mois, type_amu='cnss'):
    """Parcourt les ventes AMU (CNSS ou INAM selon type_amu) validées du
    mois (année/mois donnés), ligne par ligne (actes + produits), et
    retourne :
      {
        'lignes': {categorie_key: {'nombre_feuilles': int, 'montant': float}, ...},
        'non_classes': [{'nom_acte': str, 'occurrences': int}, ...],
      }
    Même filtre (patient AMU, vente non annulée, période) que
    bordereau_assurance() (routes/statistiques.py) ; même formule de part
    AMU par ligne (_part_amu_ligne ci-dessus)."""
    config = _CONFIG_PAR_TYPE[type_amu]

    debut = datetime(annee, mois, 1)
    fin = (datetime(annee + 1, 1, 1) if mois == 12 else datetime(annee, mois + 1, 1)) - timedelta(seconds=1)

    ventes = db.session.query(Vente).join(
        Patient, Vente.patient_id == Patient.id
    ).filter(
        Vente.structure_id == structure_id,
        Vente.date_vente >= debut,
        Vente.date_vente <= fin,
        or_(Vente.statut == 'validee', Vente.statut.is_(None)),
        db.func.lower(Patient.type_assurance) == config['type_assurance'],
    ).all()

    classification = charger_classification_amu(structure_id, type_amu)
    deviner_categorie = config['deviner_categorie']
    categorie_hospitalisation = config['categorie_hospitalisation']
    categorie_pharmacie = config['categorie_pharmacie']

    lignes = {cle: {'nombre_feuilles': 0, 'montant': 0.0} for cle, _ in config['categories_plates']}
    non_classes = {}  # nom_acte -> occurrences

    for v in ventes:
        taux_defaut = float(v.taux_assurance or 80)

        actes = v.actes or []
        if isinstance(actes, str):
            try:
                actes = json.loads(actes)
            except Exception:
                actes = []
        for item in actes:
            if not isinstance(item, dict) or not item.get('prise_en_charge_amu'):
                continue
            montant = _part_amu_ligne(item, taux_defaut)
            nom = item.get('nom') or 'Acte'
            if item.get('date_fin_prestation'):
                categorie = categorie_hospitalisation
            else:
                # ⭐ Priorité à la classification explicite de la structure
                # (ClassificationAmuCnss, filtrée par type_amu) ; à défaut,
                # proposition automatique via le code de l'acte dans la
                # nomenclature officielle — reste corrigeable via une
                # classification explicite qui la surclassera toujours, et
                # le montant/nombre par catégorie reste de toute façon
                # modifiable à la main avant impression.
                categorie = classification.get(nom) or deviner_categorie(nom)
            if not categorie:
                non_classes[nom] = non_classes.get(nom, 0) + 1
                continue
            lignes[categorie]['nombre_feuilles'] += 1
            lignes[categorie]['montant'] += montant

        produits = v.produits or []
        if isinstance(produits, str):
            try:
                produits = json.loads(produits)
            except Exception:
                produits = []
        for item in produits:
            if not isinstance(item, dict) or not item.get('prise_en_charge_amu'):
                continue
            montant = _part_amu_ligne(item, taux_defaut)
            lignes[categorie_pharmacie]['nombre_feuilles'] += 1
            lignes[categorie_pharmacie]['montant'] += montant

    non_classes_liste = [{'nom_acte': nom, 'occurrences': n} for nom, n in sorted(non_classes.items())]

    return {'lignes': lignes, 'non_classes': non_classes_liste}


def generer_lignes_facture_amu_cnss(structure_id, annee, mois):
    """Compat ascendante — équivaut à generer_lignes_facture_amu(structure_id, annee, mois, 'cnss')."""
    return generer_lignes_facture_amu(structure_id, annee, mois, 'cnss')
