# services/facturation_amu_service.py
# ============================================================
# Génération du brouillon de la FACTURE AMU mensuelle (bordereau CNSS,
# puis INAM plus tard) — voir utils/categories_amu_cnss.py pour les 21
# catégories et models.py pour ClassificationAmuCnss/FactureAmuMensuelle.
# ============================================================

import json
from datetime import datetime, timedelta

from sqlalchemy import or_

from models import db, Vente, Patient, ClassificationAmuCnss
from utils.categories_amu_cnss import (
    CATEGORIES_AMU_CNSS, CATEGORIE_HOSPITALISATION, CATEGORIE_PHARMACIE,
)
from utils.nomenclature_amu_cnss import deviner_categorie_par_code


def _taux_amu_pour_article(nom_article, taux_defaut):
    """Copie locale de app.py:taux_amu_pour_article() (P160 = 90%, reste =
    taux de la vente) — même raison de duplication que
    routes/statistiques.py:taux_amu_pour_article() et
    services/hospitalisation_service.py:_taux_amu_article() : éviter un
    import circulaire avec app.py."""
    return 90 if (nom_article and 'P160' in nom_article) else taux_defaut


def _part_amu_ligne(item, taux_defaut):
    """Part AMU d'UNE ligne (acte ou produit) — réplique exactement
    l'addend utilisé par calculer_montants_vente()
    (routes/statistiques.py), pour que la somme des lignes d'une vente,
    catégorie par catégorie, redonne le même total que le bordereau
    assurance déjà existant sur la même vente."""
    if not isinstance(item, dict) or not item.get('prise_en_charge_amu'):
        return 0.0
    pbr = float(item.get('pbr', 0) or 0)
    taux_item = _taux_amu_pour_article(item.get('nom'), taux_defaut)
    return pbr * taux_item / 100


def charger_classification_amu_cnss(structure_id):
    """{nom_acte: categorie} pour cette structure — vide tant qu'aucun
    acte n'a été classé (tout atterrit alors dans "non_classes")."""
    entrees = ClassificationAmuCnss.query.filter_by(structure_id=structure_id).all()
    return {e.nom_acte: e.categorie for e in entrees}


def generer_lignes_facture_amu_cnss(structure_id, annee, mois):
    """Parcourt les ventes AMU-CNSS validées du mois (année/mois donnés),
    ligne par ligne (actes + produits), et retourne :
      {
        'lignes': {categorie_key: {'nombre_feuilles': int, 'montant': float}, ...},
        'non_classes': [{'nom_acte': str, 'occurrences': int}, ...],
      }
    Même filtre (patient AMU-CNSS, vente non annulée, période) que
    bordereau_assurance() (routes/statistiques.py) ; même formule de part
    AMU par ligne (_part_amu_ligne ci-dessus)."""
    debut = datetime(annee, mois, 1)
    fin = (datetime(annee + 1, 1, 1) if mois == 12 else datetime(annee, mois + 1, 1)) - timedelta(seconds=1)

    ventes = db.session.query(Vente).join(
        Patient, Vente.patient_id == Patient.id
    ).filter(
        Vente.structure_id == structure_id,
        Vente.date_vente >= debut,
        Vente.date_vente <= fin,
        or_(Vente.statut == 'validee', Vente.statut.is_(None)),
        db.func.lower(Patient.type_assurance) == 'amu_cnss',
    ).all()

    classification = charger_classification_amu_cnss(structure_id)

    lignes = {cle: {'nombre_feuilles': 0, 'montant': 0.0} for cle, _ in CATEGORIES_AMU_CNSS}
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
                categorie = CATEGORIE_HOSPITALISATION
            else:
                # ⭐ Priorité à la classification explicite de la structure
                # (ClassificationAmuCnss) ; à défaut, proposition automatique
                # via le code de l'acte dans la nomenclature officielle
                # (utils/nomenclature_amu_cnss.py) — reste corrigeable via
                # une classification explicite qui la surclassera toujours,
                # et le montant/nombre par catégorie reste de toute façon
                # modifiable à la main avant impression.
                categorie = classification.get(nom) or deviner_categorie_par_code(nom)
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
            lignes[CATEGORIE_PHARMACIE]['nombre_feuilles'] += 1
            lignes[CATEGORIE_PHARMACIE]['montant'] += montant

    non_classes_liste = [{'nom_acte': nom, 'occurrences': n} for nom, n in sorted(non_classes.items())]

    return {'lignes': lignes, 'non_classes': non_classes_liste}
