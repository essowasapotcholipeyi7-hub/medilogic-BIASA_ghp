# routes/statistiques.py
from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime, timedelta, date
from collections import defaultdict
from sqlalchemy import or_, func, and_
import json
from utils.categorisation import categoriser_acte
from utils.nombres_lettres import montant_en_lettres_fcfa
from sheets_helper import sheets_helper

from models import db, Vente, Patient, Structure

statistiques_bp = Blueprint('statistiques', __name__, url_prefix='/api/statistiques')


def _get_structure_info(structure_id):
    """Infos structure (nom, adresse, téléphone, logo) pour l'en-tête des
    documents imprimables. ⭐ La table Postgres `structures` n'est qu'un
    stub (utilisée pour les FK) — les vraies coordonnées de la structure
    sont dans Google Sheets, comme pour les autres impressions
    (reçus/factures). On y va en priorité, avec repli Postgres si Sheets
    est indisponible."""
    try:
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), None)
        if info:
            return {
                'nom': info.get('nom', ''),
                'adresse': info.get('adresse', ''),
                'telephone': info.get('telephone', ''),
                'email': info.get('email', ''),
                'logo_url': info.get('logo_url', ''),
            }
    except Exception as e:
        print(f"⚠️ _get_structure_info (Sheets): {e}")

    s = Structure.query.get(structure_id)
    if s:
        return {'nom': s.nom, 'adresse': s.adresse, 'telephone': s.telephone,
                'email': s.email, 'logo_url': s.logo_url}
    return {}


# ============================================================
# CONSTANTES
# ============================================================

ASSURANCE_LABELS = {
    'gca': 'GCA',
    'sunu': 'SUNU',
    'fidelia': 'FIDELIA',
    'transvie': 'TRANSVIE',
    'gta': 'GTA',
    'nsia': 'NSIA',
    'olea': 'OLEA',
    'amu_cnss': 'AMU-CNSS',
    'amu_inam': 'AMU-INAM',
    'amu_tns': 'AMU-TNS',
    'non_assure': 'Non assuré'
}

CATEGORIES_ACTES = {
    'consultation': {'label': 'Consultation', 'color': '#4e73df'},
    'laboratoire': {'label': 'Laboratoire', 'color': '#1cc88a'},
    'imagerie': {'label': 'Imagerie', 'color': '#36b9cc'},
    'hospitalisation': {'label': 'Hospitalisation', 'color': '#f6c23e'},
    'lunettes': {'label': 'Lunettes', 'color': '#e74a3b'},
    'pharmacie': {'label': 'Pharmacie', 'color': '#858796'},
    'autres': {'label': 'Autres', 'color': '#6c757d'}
}

ASSURANCES_PRINCIPALES = ['amu_cnss', 'amu_inam', 'amu_tns']


def _label_assurance(nom):
    """Libellé propre pour un nom d'assurance (principale AMU ou société
    libre en principale/complémentaire) : AMU-CNSS/AMU-INAM/AMU-TNS pour les
    3 codes AMU, sinon le nom tel que saisi (en majuscules)."""
    nom_lower = (nom or '').lower()
    if nom_lower == 'amu_cnss':
        return 'AMU-CNSS'
    elif nom_lower == 'amu_inam':
        return 'AMU-INAM'
    elif nom_lower == 'amu_tns':
        return 'AMU-TNS'
    return ASSURANCE_LABELS.get(nom_lower, (nom or '').upper())


def _parse_assurance_filter(assurance_filter):
    """Découpe la valeur du filtre "Assurance" en (type, nom).

    ⭐ FIX : le même nom (ex: "GTA") peut désigner DEUX choses différentes
    et sans rapport — une compagnie choisie comme assurance PRINCIPALE
    "Autre" (Patient.type_assurance = "GTA" littéralement, saisi via le
    champ libre du formulaire patient) et une compagnie utilisée comme
    assurance COMPLÉMENTAIRE (Vente.assurance2_nom = "GTA"). Fusionner les
    deux dans une seule option de filtre "gta" (comme avant) donnait un
    nombre de patients affiché dans le menu qui ne correspondait à AUCUN
    des deux groupes réels, et pouvait mélanger les deux dans la liste
    résultante. Le filtre encode donc maintenant explicitement le type
    ("principale:gta" / "complementaire:gta"), pour ne jamais deviner sur
    quelle colonne filtrer.

    Conserve la compatibilité avec d'anciens liens/favoris sans préfixe
    (ex: "amu_cnss", "gta") en retombant sur l'ancienne heuristique."""
    if assurance_filter in ('toutes', 'non_assure', None, ''):
        return assurance_filter or 'toutes', None
    if ':' in assurance_filter:
        type_hint, nom = assurance_filter.split(':', 1)
        return type_hint, nom
    # Compatibilité ascendante : ancienne valeur sans préfixe
    if assurance_filter.lower() in ASSURANCES_PRINCIPALES:
        return 'principale', assurance_filter
    return 'complementaire', assurance_filter


# ============================================================
# PAGE PRINCIPALE
# ============================================================

@statistiques_bp.route('/')
def index():
    return render_template('statistiques_ventes.html')


# ============================================================
# API : LISTE DES ASSURANCES
# ============================================================

@statistiques_bp.route('/assurances/liste')
def api_assurances_liste():
    """Récupère la liste de TOUTES les assurances utilisées SUR LA PÉRIODE
    demandée, PRINCIPALES et COMPLÉMENTAIRES gardées explicitement séparées.

    ⭐ FIX (mélange) : un même nom (ex: "GTA") peut désigner une compagnie
    choisie en assurance PRINCIPALE "Autre" (Patient.type_assurance = "GTA",
    saisi tel quel via le champ libre du formulaire patient) ET une
    compagnie utilisée comme assurance COMPLÉMENTAIRE (Vente.assurance2_nom
    = "GTA") — deux groupes de patients sans rapport. L'ancienne version
    fusionnait les deux en une seule option de filtre, avec un nombre de
    patients qui ne correspondait à AUCUN des deux groupes réels (toujours
    compté sur Patient.type_assurance, même pour les compagnies
    complémentaires) — et la sélection résultante pouvait mélanger les
    deux. Chaque option porte maintenant une clé explicite
    "principale:xxx" / "complementaire:xxx" (voir _parse_assurance_filter),
    pour qu'on n'ait plus jamais à deviner sur quelle colonne filtrer.

    ⭐ FIX (nombre entre parenthèses ≠ liste affichée) : le décompte
    portait avant sur TOUS les patients de la structure (recensement à
    vie), alors que la liste affichée après sélection ne montre que ceux
    ayant une VENTE dans la période choisie (Ventes tab) — les deux
    chiffres ne pouvaient donc coïncider que par coïncidence (ex: "Non
    assuré (24 patients)" dans le menu, 15 lignes affichées sur "Cette
    année"). Le décompte est maintenant calculé exactement de la même
    façon que la liste : patients distincts ayant au moins une vente dans
    LA MÊME période (paramètres periode/date_debut/date_fin, identiques à
    /stats) — les deux nombres correspondent désormais toujours."""
    try:
        structure_id = session.get('structure_id')

        if not structure_id:
            return jsonify({'error': 'Structure non trouvée'}), 400

        periode = request.args.get('periode', 'mois')
        date_debut_str = request.args.get('date_debut')
        date_fin_str = request.args.get('date_fin')
        dates = get_dates_periode(periode, date_debut_str, date_fin_str)

        from datetime import datetime as dt
        if isinstance(dates['debut'], date) and not isinstance(dates['debut'], datetime):
            debut = dt.combine(dates['debut'], dt.min.time())
            fin = dt.combine(dates['fin'], dt.max.time())
        else:
            debut = dates['debut']
            fin = dates['fin']

        base_filtres = [
            Vente.structure_id == structure_id,
            Vente.date_vente >= debut,
            Vente.date_vente <= fin,
            # ⭐ FIX : "validee OU NULL" excluait à tort tout statut
            # 'partielle' (vente réelle, non annulée, juste partiellement
            # réglée — 86 ventes sur cette seule structure) des
            # statistiques/bordereaux assurance, alors que l'intention
            # documentée ici même était "statut NULL = vente active,
            # IS NULL OR != 'annulee'" — la condition ne correspondait pas
            # au commentaire. Seule une vente explicitement annulée doit
            # être exclue.
            or_(Vente.statut != 'annulee', Vente.statut.is_(None)),
        ]

        result_list = []

        # --- Non assuré : patients distincts, avec vente dans la période,
        # sans AUCUNE assurance (ni principale ni complémentaire) — même
        # définition que le CAS 0 de get_patients_par_assurance.
        nb_non_assure = db.session.query(func.count(func.distinct(Vente.patient_id))).join(
            Patient, Vente.patient_id == Patient.id
        ).filter(
            *base_filtres,
            or_(
                Patient.type_assurance == None,
                Patient.type_assurance == '',
                Patient.type_assurance == 'non_assure'
            ),
            or_(
                Vente.assurance2_nom == None,
                Vente.assurance2_nom == '',
                Vente.assurance2_nom == 'Aucune'
            )
        ).scalar() or 0
        if nb_non_assure:
            result_list.append({
                'key': 'non_assure', 'label': 'Non assuré',
                'nb_patients': nb_non_assure, 'type': 'non_assure'
            })

        # --- Assurances PRINCIPALES : valeurs distinctes de
        # Patient.type_assurance (AMU-CNSS/INAM/TNS, ou une compagnie libre
        # saisie via "Autre"), comptées sur les patients ayant une vente
        # dans la période.
        principales = db.session.query(
            func.lower(Patient.type_assurance),
            func.count(func.distinct(Vente.patient_id))
        ).join(Vente, Vente.patient_id == Patient.id).filter(
            *base_filtres,
            Patient.type_assurance != None,
            Patient.type_assurance != '',
            Patient.type_assurance != 'non_assure'
        ).group_by(func.lower(Patient.type_assurance)).all()

        for nom, nb in principales:
            if not nom or not nb:
                continue
            result_list.append({
                'key': f'principale:{nom}',
                'label': _label_assurance(nom),
                'nb_patients': nb,
                'type': 'principale'
            })

        # --- Assurances COMPLÉMENTAIRES : valeurs distinctes de
        # Vente.assurance2_nom, comptées sur les patients ayant une vente
        # avec cette assurance dans la période.
        complementaires = db.session.query(
            func.lower(Vente.assurance2_nom),
            func.count(func.distinct(Vente.patient_id))
        ).join(Patient, Vente.patient_id == Patient.id).filter(
            *base_filtres,
            Vente.assurance2_nom != None,
            Vente.assurance2_nom != '',
            Vente.assurance2_nom != 'Aucune'
        ).group_by(func.lower(Vente.assurance2_nom)).all()

        for nom, nb in complementaires:
            if not nom or not nb:
                continue
            result_list.append({
                'key': f'complementaire:{nom}',
                'label': _label_assurance(nom),
                'nb_patients': nb,
                'type': 'complementaire'
            })

        def sort_key(x):
            if x['type'] == 'principale':
                return (0, x['label'])
            elif x['type'] == 'complementaire':
                return (1, x['label'])
            else:
                return (2, x['label'])

        result_list.sort(key=sort_key)

        return jsonify(result_list)

    except Exception as e:
        print(f"❌ Erreur api_assurances_liste: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================================
# FONCTION DE CALCUL DES MONTANTS À PARTIR DES ACTES/PRODUITS
# ============================================================

def taux_amu_pour_article(nom_article, taux_defaut):
    """⭐ FIX : taux AMU par article, pas un taux unique pour toute la vente
    — l'acte P160 est remboursé à 90% par l'AMU, tous les autres au taux
    général (par défaut 80%). Copie locale de app.py:taux_amu_pour_article()
    (dupliquée ici plutôt qu'importée depuis app.py, pour éviter un import
    circulaire : app.py enregistre ce blueprint, donc ce module ne doit pas
    importer app.py)."""
    return 90 if (nom_article and 'P160' in nom_article) else taux_defaut


def calculer_montants_vente(vente):
    """
    Calcule les montants pour une vente à partir des actes et produits
    Retourne : (part_amu, part_complementaire, reste_patient)
    """
    actes = vente.actes or []
    produits = vente.produits or []
    
    # ⭐ Si actes/produits sont des strings JSON, les parser
    if isinstance(actes, str):
        try:
            actes = json.loads(actes)
        except:
            actes = []
    
    if isinstance(produits, str):
        try:
            produits = json.loads(produits)
        except:
            produits = []
    
    total_prix = 0
    total_pbr_amu = 0
    # ⭐ FIX : taux AMU par article (P160 = 90%, le reste = taux_amu de la
    # vente) au lieu d'un taux unique appliqué à tout le PBR en bloc — même
    # correctif que celui appliqué côté reçu (app.py, taux_amu_pour_article())
    # et côté vente d'actes (templates/actes_vente.html,
    # tauxAMUPourArticle()). Sans lui, le bordereau assurance affichait un
    # montant erroné pour toute vente contenant un P160 (remboursé à tort
    # au taux général au lieu de 90%).
    part_amu = 0

    # ⭐ Taux d'assurance (calculé avant la boucle : nécessaire à
    # taux_amu_pour_article ci-dessous)
    taux_amu_defaut = float(vente.taux_assurance or 80)
    taux_cac = float(vente.taux_assurance2 or 0) / 100 if vente.taux_assurance2 else 0

    # ⭐ Parcourir les actes
    for acte in actes:
        if isinstance(acte, dict):
            prix = float(acte.get('prix', 0))
            pbr = float(acte.get('pbr', 0))
            # ⭐ FIX : quantité et plafonnement min(prix, pbr) manquants —
            # une ligne à quantité 2+ voyait sa part AMU (et même son prix
            # dans le sous-total) sous-évaluée d'autant, ici alignée sur la
            # formule CANONIQUE utilisée à la création de la vente
            # (api_convertir_proforma/api_facturer_hospitalisation, app.py :
            # min(prix, pbr) × quantité × taux / 100) — constaté sur une
            # vente réelle (2× P160... pardon, 2× S100 à 3500F : part AMU
            # stockée 5 600F, 2 800F calculée ici avant ce correctif).
            quantite = int(acte.get('quantite', 1) or 1)
            # ⭐ FIX (2) : absent (jamais écrit, ventes directes anciennes
            # hors circuit proforma) = couvert par défaut — patron :
            # "couvertes par défaut" ; seule une valeur explicitement False
            # exclut la ligne.
            prise_amu = acte.get('prise_en_charge_amu', True)

            total_prix += prix * quantite

            if prise_amu and pbr > 0:
                base_amu = min(prix, pbr) * quantite
                total_pbr_amu += base_amu
                taux_item = taux_amu_pour_article(acte.get('nom'), taux_amu_defaut)
                part_amu += base_amu * taux_item / 100

    # ⭐ Parcourir les produits
    for produit in produits:
        if isinstance(produit, dict):
            prix = float(produit.get('prix_reel', produit.get('prix', 0)))
            pbr = float(produit.get('pbr', 0))
            quantite = int(produit.get('quantite', 1) or 1)
            prise_amu = produit.get('prise_en_charge_amu', True)

            total_prix += prix * quantite

            if prise_amu and pbr > 0:
                base_amu = min(prix, pbr) * quantite
                total_pbr_amu += base_amu
                taux_item = taux_amu_pour_article(produit.get('nom'), taux_amu_defaut)
                part_amu += base_amu * taux_item / 100
    
    # ⭐ Reste après AMU = Prix total - Part AMU
    reste_apres_amu = total_prix - part_amu
    
    # ⭐ Part CAC = Reste × Taux CAC
    part_cac = reste_apres_amu * taux_cac if taux_cac > 0 else 0
    
    # ⭐ Reste patient = Reste - Part CAC
    reste_patient = reste_apres_amu - part_cac
    
    # ⭐ Sécurité : pas de négatif
    if reste_patient < 0:
        reste_patient = 0
    if part_amu < 0:
        part_amu = 0
    if part_cac < 0:
        part_cac = 0
    
    return {
        'total_prix': total_prix,
        'total_pbr_amu': total_pbr_amu,
        'part_amu': part_amu,
        'part_cac': part_cac,
        'reste_patient': reste_patient
    }


# ============================================================
# API : STATISTIQUES GÉNÉRALES
# ============================================================

def _ventes_filtrees(structure_id, periode, date_debut_str, date_fin_str,
                      assurance_filter='toutes', type_assurance='toutes', categorie_filter='toutes'):
    """Factorisation de la construction de la requête ventes filtrée,
    partagée entre l'API JSON /stats et les routes d'impression (liste des
    patients par assurance, bordereau) pour que les deux affichent
    exactement les mêmes données."""
    dates = get_dates_periode(periode, date_debut_str, date_fin_str)

    from datetime import datetime as dt

    if isinstance(dates['debut'], date) and not isinstance(dates['debut'], datetime):
        debut = dt.combine(dates['debut'], dt.min.time())
        fin = dt.combine(dates['fin'], dt.max.time())
    else:
        debut = dates['debut']
        fin = dates['fin']

    query = db.session.query(Vente).join(
        Patient, Vente.patient_id == Patient.id
    ).filter(
        Vente.structure_id == structure_id,
        Vente.date_vente >= debut,
        Vente.date_vente <= fin,
        # ⭐ FIX : "validee OU NULL" excluait à tort les ventes 'partielle'
        # (réelles, non annulées) — voir le commentaire détaillé plus haut.
        or_(Vente.statut != 'annulee', Vente.statut.is_(None))
    )

    # Filtrer par catégorie d'actes
    if categorie_filter != 'toutes':
        ventes_filtrees = []
        for v in query.all():
            actes = extraire_actes(v)
            if categorie_filter in actes:
                ventes_filtrees.append(v.id)

        if ventes_filtrees:
            query = query.filter(Vente.id.in_(ventes_filtrees))
        else:
            query = query.filter(Vente.id == -1)

    # Filtrer par type d'assurance
    # ⭐ FIX : ne vérifiait que amu_cnss/amu_inam (AMU-TNS oublié — absent au
    # moment de l'introduction de cette 3ᵉ branche AMU) et, plus important,
    # ignorait toute assurance principale "Autre" (compagnie libre saisie
    # via le formulaire patient, ex: Patient.type_assurance = "GTA") — un
    # patient avec une telle principale n'a jamais aucun de ces deux
    # filtres ("principale"/"double") : "a une assurance principale" veut
    # dire concrètement "type_assurance renseigné et différent de
    # non_assure", quelle que soit la compagnie.
    a_une_principale = and_(
        Patient.type_assurance != None,
        Patient.type_assurance != '',
        Patient.type_assurance != 'non_assure'
    )
    a_une_complementaire = and_(
        Vente.assurance2_nom != None,
        Vente.assurance2_nom != '',
        Vente.assurance2_nom != 'Aucune'
    )
    if type_assurance == 'principale':
        query = query.filter(a_une_principale)
    elif type_assurance == 'complementaire':
        query = query.filter(a_une_complementaire)
    elif type_assurance == 'double':
        query = query.filter(a_une_principale, a_une_complementaire)

    # Filtrer par assurance spécifique
    if assurance_filter != 'toutes':
        if assurance_filter == 'non_assure':
            # ⭐ FIX : "Non assuré" doit exclure les ventes avec une assurance
            # COMPLÉMENTAIRE (assurance2_nom) en plus de l'assurance
            # principale — un patient sans assurance principale mais ayant
            # utilisé une assurance complémentaire sur la vente n'est pas
            # "non assuré", il apparaissait à tort dans cette liste (mélangé
            # avec les vrais non-assurés) faute de cette exclusion.
            query = query.filter(
                or_(
                    Patient.type_assurance == None,
                    Patient.type_assurance == '',
                    Patient.type_assurance == 'non_assure'
                ),
                or_(
                    Vente.assurance2_nom == None,
                    Vente.assurance2_nom == '',
                    Vente.assurance2_nom == 'Aucune'
                )
            )
        else:
            # ⭐ FIX : la colonne à filtrer (Patient.type_assurance ou
            # Vente.assurance2_nom) était devinée après coup via
            # ASSURANCES_PRINCIPALES — ça marche pour les 3 codes AMU, mais
            # pas pour une compagnie choisie en principale "Autre" (ex:
            # Patient.type_assurance = "GTA" littéralement) qui porte le
            # MÊME nom qu'une compagnie complémentaire ("GTA" en
            # Vente.assurance2_nom) : les deux tombaient dans la même case
            # "gta" et se mélangeaient. Le type est maintenant explicite
            # dans la clé du filtre (voir _parse_assurance_filter),
            # sélectionnée à partir de la vraie colonne d'origine.
            type_hint, nom = _parse_assurance_filter(assurance_filter)
            if type_hint == 'principale':
                query = query.filter(
                    db.func.lower(Patient.type_assurance) == nom.lower()
                )
            else:
                query = query.filter(
                    db.func.lower(Vente.assurance2_nom) == nom.lower()
                )

    ventes = query.all()

    # Récupérer les patients avec leurs assurances
    patient_ids = list(set([v.patient_id for v in ventes if v.patient_id]))
    patients = []
    patients_dict = {}
    if patient_ids:
        patients = Patient.query.filter(
            Patient.structure_id == structure_id,
            Patient.id.in_(patient_ids)
        ).all()
        patients_dict = {p.id: p.type_assurance for p in patients}

    return ventes, patients, patients_dict, dates


@statistiques_bp.route('/stats')
def api_stats():
    try:
        structure_id = session.get('structure_id')

        if not structure_id:
            return jsonify({'error': 'Structure non trouvée'}), 400

        periode = request.args.get('periode', 'mois')
        date_debut_str = request.args.get('date_debut')
        date_fin_str = request.args.get('date_fin')
        assurance_filter = request.args.get('assurance', 'toutes')
        categorie_filter = request.args.get('categorie', 'toutes')
        type_assurance = request.args.get('type_assurance', 'toutes')

        ventes, patients, patients_dict, dates = _ventes_filtrees(
            structure_id, periode, date_debut_str, date_fin_str,
            assurance_filter, type_assurance, categorie_filter
        )

        # Calcul des statistiques
        stats_actes = calculer_stats_actes(ventes)
        stats_assurances = calculer_stats_assurances(ventes, patients, patients_dict)
        stats_globales = calculer_stats_globales(ventes, patients)
        patients_par_assurance = get_patients_par_assurance(ventes, patients, patients_dict, type_assurance, assurance_filter)
        
        return jsonify({
            'success': True,
            'period': {
                'debut': dates['debut'].strftime('%Y-%m-%d'),
                'fin': dates['fin'].strftime('%Y-%m-%d'),
                'libelle': dates['libelle']
            },
            'stats_actes': stats_actes,
            'stats_assurances': stats_assurances,
            'stats_globales': stats_globales,
            'patients_par_assurance': patients_par_assurance,
            'ventes': [{
                'id': v.id,
                'patient_id': v.patient_id,
                'patient_nom': v.patient_nom,
                'date_vente': v.date_vente.isoformat() if v.date_vente else '',
                'assurance': patients_dict.get(v.patient_id, 'non_assure') or 'non_assure',
                'assurance2_nom': v.assurance2_nom or '',
                'numero_assure': v.numero_assure or '',
                'numero_assure2': v.numero_assure2 or '',
                'net_a_payer': float(v.net_a_payer or 0),
                'montant_donne': float(v.montant_donne or 0),
                'rendu': float(v.rendu or 0),
                'reste_a_payer': float(v.reste_a_payer or 0),
                'prise_en_charge': float(v.prise_en_charge or 0),
                'prise_en_charge2': float(v.prise_en_charge2 or 0) if hasattr(v, 'prise_en_charge2') else 0,
                'type': v.type or '',
                'statut': v.statut,
                'actes': v.actes,
                'produits': v.produits,
                'taux_assurance': v.taux_assurance,
                'taux_assurance2': v.taux_assurance2
            } for v in ventes]
        })
        
    except Exception as e:
        print(f"❌ Erreur api_stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================================
# FONCTIONS DE CALCUL
# ============================================================

def get_dates_periode(periode, date_debut=None, date_fin=None):
    """Retourne les dates de début et fin pour une période donnée"""
    from datetime import datetime as dt
    today = date.today()
    
    if periode == 'aujourdhui':
        debut = dt.combine(today, dt.min.time())
        fin = dt.combine(today, dt.max.time())
        return {'debut': debut, 'fin': fin, 'libelle': "Aujourd'hui"}
    elif periode == 'semaine':
        debut = today - timedelta(days=today.weekday())
        debut = dt.combine(debut, dt.min.time())
        fin = dt.combine(today, dt.max.time())
        return {'debut': debut, 'fin': fin, 'libelle': f'Semaine du {debut.strftime("%d/%m/%Y")}'}
    elif periode == 'mois':
        debut = today.replace(day=1)
        debut = dt.combine(debut, dt.min.time())
        fin = dt.combine(today, dt.max.time())
        return {'debut': debut, 'fin': fin, 'libelle': f'Mois de {debut.strftime("%B %Y")}'}
    elif periode == 'annee':
        debut = today.replace(month=1, day=1)
        debut = dt.combine(debut, dt.min.time())
        fin = dt.combine(today, dt.max.time())
        return {'debut': debut, 'fin': fin, 'libelle': f"Année {today.year}"}
    elif periode == 'personnalise' and date_debut and date_fin:
        try:
            debut = datetime.strptime(date_debut, '%Y-%m-%d').date()
            fin = datetime.strptime(date_fin, '%Y-%m-%d').date()
            debut = dt.combine(debut, dt.min.time())
            fin = dt.combine(fin, dt.max.time())
            return {'debut': debut, 'fin': fin, 'libelle': f'Du {date_debut} au {date_fin}'}
        except ValueError:
            debut = today.replace(day=1)
            debut = dt.combine(debut, dt.min.time())
            fin = dt.combine(today, dt.max.time())
            return {'debut': debut, 'fin': fin, 'libelle': f'Mois de {debut.strftime("%B %Y")}'}
    else:
        debut = today.replace(day=1)
        debut = dt.combine(debut, dt.min.time())
        fin = dt.combine(today, dt.max.time())
        return {'debut': debut, 'fin': fin, 'libelle': f'Mois de {debut.strftime("%B %Y")}'}



def extraire_actes(vente):
    actes = {}
    
    # ⭐ 1. PRIORITÉ : Utiliser categorie_actes (déjà catégorisé)
    if hasattr(vente, 'categorie_actes') and vente.categorie_actes:
        try:
            if isinstance(vente.categorie_actes, str):
                actes_data = json.loads(vente.categorie_actes)
            else:
                actes_data = vente.categorie_actes
                
            if isinstance(actes_data, list):
                for acte in actes_data:
                    if isinstance(acte, dict):
                        categorie = acte.get('categorie', 'autres')
                        montant = acte.get('total', acte.get('prix', 0))
                        if montant and float(montant) > 0:
                            actes[categorie] = actes.get(categorie, 0) + float(montant)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        
        # ⭐ Si on a trouvé des données, on les retourne directement
        if actes:
            return actes
    
    # ⭐ 2. Utiliser les actes avec le fichier de catégorisation
    if hasattr(vente, 'actes') and vente.actes:
        try:
            if isinstance(vente.actes, str):
                actes_data = json.loads(vente.actes)
            else:
                actes_data = vente.actes
                
            if isinstance(actes_data, list):
                for acte in actes_data:
                    if isinstance(acte, dict):
                        nom = acte.get('nom', '')
                        montant = acte.get('total', acte.get('prix', 0))
                        if montant and float(montant) > 0:
                            # ⭐ Utiliser le fichier de catégorisation
                            categorie_info = categoriser_acte(nom)
                            categorie = categorie_info.get('categorie', 'autres')
                            actes[categorie] = actes.get(categorie, 0) + float(montant)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    
    # ⭐ 3. Parcourir les produits (toujours en pharmacie)
    if hasattr(vente, 'produits') and vente.produits:
        try:
            if isinstance(vente.produits, str):
                produits_data = json.loads(vente.produits)
            else:
                produits_data = vente.produits
                
            if isinstance(produits_data, list):
                for produit in produits_data:
                    if isinstance(produit, dict):
                        montant = produit.get('total', produit.get('prix_reel', 0))
                        if montant and float(montant) > 0:
                            # ⭐ Les produits sont en pharmacie
                            actes['pharmacie'] = actes.get('pharmacie', 0) + float(montant)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    
    # ⭐ 4. Fallback sur le type de la vente
    if not actes and vente.type:
        categorie = vente.type
        if categorie == 'actes':
            categorie = 'consultation'
        elif categorie in ['pharmacie', 'pharma']:
            categorie = 'pharmacie'
        elif categorie not in CATEGORIES_ACTES:
            categorie = 'autres'
        
        if vente.net_a_payer and float(vente.net_a_payer) > 0:
            actes[categorie] = float(vente.net_a_payer)
    
    return actes


def calculer_stats_actes(ventes):
    stats = {
        'consultation': {'total': 0, 'nb_actes': 0, 'nb_patients': 0},
        'laboratoire': {'total': 0, 'nb_actes': 0, 'nb_patients': 0},
        'imagerie': {'total': 0, 'nb_actes': 0, 'nb_patients': 0},
        'hospitalisation': {'total': 0, 'nb_actes': 0, 'nb_patients': 0},
        'lunettes': {'total': 0, 'nb_actes': 0, 'nb_patients': 0},
        'pharmacie': {'total': 0, 'nb_actes': 0, 'nb_patients': 0},
        'autres': {'total': 0, 'nb_actes': 0, 'nb_patients': 0},
    }
    
    patients_par_categorie = defaultdict(set)
    
    for vente in ventes:
        patient_id = vente.patient_id
        actes = extraire_actes(vente)
        
        for categorie, montant in actes.items():
            if categorie in stats:
                stats[categorie]['total'] += montant
                stats[categorie]['nb_actes'] += 1
                if patient_id:
                    patients_par_categorie[categorie].add(patient_id)
    
    for categorie, patients in patients_par_categorie.items():
        if categorie in stats:
            stats[categorie]['nb_patients'] = len(patients)
    
    return stats


def _societe_vente(vente, patients_dict_societe=None):
    """Société souscriptrice de l'assurance complémentaire pour une vente :
    l'instantané pris à la vente si disponible, sinon (ventes créées avant
    l'existence du champ) la valeur courante sur la fiche patient."""
    societe = getattr(vente, 'societe_assurance2', None)
    if societe:
        return societe
    if patients_dict_societe:
        return patients_dict_societe.get(vente.patient_id) or ''
    return ''


def calculer_stats_assurances(ventes, patients, patients_dict):
    patients_dict_societe = {p.id: getattr(p, 'societe_assurance2', None) for p in patients}

    assurance_data = defaultdict(lambda: {
        'total_ventes': 0,
        'total_montant': 0,
        'total_prise_en_charge': 0,
        'total_reste': 0,
        'patients': set(),
        'ventes': [],
        'societes': defaultdict(lambda: {'nb_ventes': 0, 'montant': 0, 'prise_en_charge': 0, 'patients': set()})
    })

    for vente in ventes:
        # ⭐ Normalisé en minuscules — Patient.type_assurance peut porter une
        # compagnie "Autre" saisie librement (ex: "GTA"), sinon la même
        # assurance principale finissait dans deux clés différentes selon
        # la casse d'origine ("GTA" / "gta").
        assurance_principale = (patients_dict.get(vente.patient_id) or 'non_assure').strip().lower() or 'non_assure'

        if assurance_principale != 'non_assure':
            data = assurance_data[assurance_principale]
            data['total_ventes'] += 1
            data['total_montant'] += float(vente.net_a_payer or 0)
            data['total_prise_en_charge'] += float(vente.prise_en_charge or 0)
            data['total_reste'] += float(vente.reste_a_payer or 0)
            if vente.patient_id:
                data['patients'].add(vente.patient_id)
            data['ventes'].append(vente)

        if vente.assurance2_nom and vente.assurance2_nom != '' and vente.assurance2_nom != 'Aucune':
            assurance_complementaire = vente.assurance2_nom.lower()
            data = assurance_data[assurance_complementaire]
            data['total_ventes'] += 1
            data['total_montant'] += float(vente.net_a_payer or 0)
            data['total_prise_en_charge'] += float(vente.prise_en_charge2 or 0)
            data['total_reste'] += float(vente.reste_a_payer or 0)
            if vente.patient_id:
                data['patients'].add(vente.patient_id)
            data['ventes'].append(vente)

            societe = _societe_vente(vente, patients_dict_societe)
            if societe:
                sdata = data['societes'][societe]
                sdata['nb_ventes'] += 1
                sdata['montant'] += float(vente.net_a_payer or 0)
                sdata['prise_en_charge'] += float(vente.prise_en_charge2 or 0)
                if vente.patient_id:
                    sdata['patients'].add(vente.patient_id)

        if assurance_principale == 'non_assure' and (not vente.assurance2_nom or vente.assurance2_nom == ''):
            data = assurance_data['non_assure']
            data['total_ventes'] += 1
            data['total_montant'] += float(vente.net_a_payer or 0)
            data['total_prise_en_charge'] += 0
            data['total_reste'] += float(vente.reste_a_payer or 0)
            if vente.patient_id:
                data['patients'].add(vente.patient_id)
            data['ventes'].append(vente)

    result = []
    for assurance, data in assurance_data.items():
        assurance_label = 'Non assuré' if assurance == 'non_assure' else _label_assurance(assurance)

        patients_details = []
        for patient_id in data['patients']:
            patient = next((p for p in patients if p.id == patient_id), None)
            patient_nom = f"{patient.prenom} {patient.nom}" if patient and patient.prenom else (patient.nom if patient else 'Patient')
            patients_details.append({'id': patient_id, 'nom': patient_nom})

        societes_details = [
            {
                'societe': nom_societe,
                'nb_ventes': sdata['nb_ventes'],
                'nb_patients': len(sdata['patients']),
                'montant': round(sdata['montant'], 2),
                'prise_en_charge': round(sdata['prise_en_charge'], 2),
            }
            for nom_societe, sdata in data['societes'].items()
        ]
        societes_details.sort(key=lambda s: s['societe'])

        result.append({
            'assurance': assurance,
            'assurance_label': assurance_label,
            'nb_ventes': data['total_ventes'],
            'nb_patients': len(data['patients']),
            'montant_total': round(data['total_montant'], 2),
            'prise_en_charge': round(data['total_prise_en_charge'], 2),
            'reste_a_payer': round(data['total_reste'], 2),
            'patients': patients_details,
            'societes': societes_details
        })

    return result


def calculer_stats_globales(ventes, patients):
    total_ventes = len(ventes)
    total_ca = 0
    total_reste = 0
    total_prise_en_charge = 0
    total_actes = 0
    
    for vente in ventes:
        ca = float(vente.montant_donne or 0) - float(vente.rendu or 0)
        total_ca += ca if ca > 0 else 0
        total_reste += float(vente.reste_a_payer or 0)
        total_prise_en_charge += float(vente.prise_en_charge or 0)
        
        actes = extraire_actes(vente)
        for _, montant in actes.items():
            if montant > 0:
                total_actes += 1
    
    return {
        'total_ventes': total_ventes,
        'total_patients': len(patients),
        'total_ca': round(total_ca, 2),
        'total_reste': round(total_reste, 2),
        'total_prise_en_charge': round(total_prise_en_charge, 2),
        'total_actes': total_actes
    }


def get_patients_par_assurance(ventes, patients, patients_dict, type_assurance='toutes', assurance_filter='toutes'):
    """Récupère la liste des patients avec leurs assurances (une ligne par assurance)"""
    result = []

    # ⭐ FIX : "Non assuré" était traité comme "pas de filtre" (ni principale
    # ni complémentaire actif) et retombait donc dans le CAS 3 ci-dessous,
    # qui ajoute une ligne "assurance complémentaire" pour tout patient en
    # ayant une — d'où des lignes d'assurance complémentaire mélangées dans
    # la liste "Non assuré". Cas désormais explicite : une seule ligne
    # "Non assuré" par patient, jamais de ligne principale/complémentaire.
    est_filtre_non_assure = assurance_filter == 'non_assure'
    est_filtre_actif = assurance_filter != 'toutes' and not est_filtre_non_assure
    # ⭐ FIX : le type (principale/complémentaire) vient maintenant de la clé
    # explicite du filtre (voir _parse_assurance_filter), plus d'une
    # déduction via ASSURANCES_PRINCIPALES qui ratait toute assurance
    # principale "Autre" (compagnie libre, même nom possible qu'une
    # complémentaire — voir le commentaire détaillé sur _parse_assurance_filter).
    filtre_type_hint, filtre_nom = _parse_assurance_filter(assurance_filter) if est_filtre_actif else (None, None)
    est_filtre_principale = est_filtre_actif and filtre_type_hint == 'principale'
    est_filtre_complementaire = est_filtre_actif and filtre_type_hint == 'complementaire'
    
    for patient in patients:
        ventes_patient = [v for v in ventes if v.patient_id == patient.id]
        if not ventes_patient:
            continue

        # ⭐ Récupérer les détails des actes et produits
        details_liste = []
        for v in ventes_patient:
            # Récupérer les actes
            if hasattr(v, 'actes') and v.actes:
                try:
                    actes_data = json.loads(v.actes) if isinstance(v.actes, str) else v.actes
                    if isinstance(actes_data, list):
                        for acte in actes_data:
                            if isinstance(acte, dict):
                                nom = acte.get('nom', 'Acte')
                                quantite = acte.get('quantite', 1)
                                prix = acte.get('prix', 0)
                                details_liste.append(f"{nom} x{quantite} ({prix} F)")
                except:
                    pass
            
            # Récupérer les produits
            if hasattr(v, 'produits') and v.produits:
                try:
                    produits_data = json.loads(v.produits) if isinstance(v.produits, str) else v.produits
                    if isinstance(produits_data, list):
                        for produit in produits_data:
                            if isinstance(produit, dict):
                                nom = produit.get('nom', 'Produit')
                                quantite = produit.get('quantite', 1)
                                prix = produit.get('prix_reel', produit.get('prix', 0))
                                details_liste.append(f"{nom} x{quantite} ({prix} F)")
                except:
                    pass
        
        # ⭐ Limiter l'affichage à 3 éléments max avec "..."
        if len(details_liste) > 3:
            details_affichage = ", ".join(details_liste[:3]) + f" ... et {len(details_liste) - 3} autre(s)"
        else:
            details_affichage = ", ".join(details_liste)

        
        # ⭐ Normalisé en minuscules dès ici — Patient.type_assurance peut
        # porter une compagnie "Autre" saisie librement (ex: "GTA"), et
        # toutes les comparaisons ci-dessous (avec 'non_assure', avec le nom
        # du filtre actif...) doivent être insensibles à la casse.
        assurance_principale = (patients_dict.get(patient.id) or 'non_assure').strip().lower() or 'non_assure'

        assurance_complementaire = ''
        societe_assurance2 = ''
        for v in ventes_patient:
            if v.assurance2_nom and v.assurance2_nom != '' and v.assurance2_nom != 'Aucune':
                assurance_complementaire = v.assurance2_nom.lower()
                societe_assurance2 = _societe_vente(v) or (patient.societe_assurance2 or '')
                break

        # ⭐ Calcul des montants à partir des actes/produits
        total_prix = 0
        total_part_amu = 0
        total_part_cac = 0
        total_reste_patient = 0
        
        for v in ventes_patient:
            montants = calculer_montants_vente(v)
            total_prix += montants['total_prix']
            total_part_amu += montants['part_amu']
            total_part_cac += montants['part_cac']
            total_reste_patient += montants['reste_patient']
        
        nb_actes = sum(1 for v in ventes_patient for _ in extraire_actes(v).keys())
        derniere_visite = max(v.date_vente for v in ventes_patient) if ventes_patient else None

        # ============================================================
        # CAS 0 : Filtre "Non assuré"
        # ============================================================
        if est_filtre_non_assure:
            if assurance_principale == 'non_assure' and not assurance_complementaire:
                result.append({
                    'assurance': 'non_assure',
                    'assurance_label': 'Non assuré',
                    'type_assurance': 'non_assure',
                    'patient_id': patient.id,
                    'patient_nom': f"{patient.prenom} {patient.nom}".strip() or patient.nom,
                    'numero_assure': patient.numero_assure or '',
                    'numero_assure2': '',
                    'montant_beneficiaire': total_prix,
                    'part_assurance': 0,
                    'nb_actes': nb_actes if nb_actes > 0 else len(ventes_patient),
                    'nb_ventes': len(ventes_patient),
                    'derniere_visite': derniere_visite.strftime('%d/%m/%Y') if derniere_visite else '',
                    'est_double_assurance': False,
                    'details': details_affichage,
                    'details_complet': details_liste
                })
            continue

        # ============================================================
        # CAS 1 : Filtre sur une assurance COMPLÉMENTAIRE
        # ============================================================
        if est_filtre_complementaire:
            if assurance_complementaire == filtre_nom.lower():
                # ⭐ FIX : une SEULE ligne — celle de l'assurance COMPLÉMENTAIRE
                # sélectionnée. Une ligne "principale" séparée était ajoutée
                # en plus pour tout patient à double assurance — hors sujet
                # quand on filtre sur UNE compagnie précise (la liste sert au
                # dépôt de dossier auprès de CETTE compagnie, ex: GCA — une
                # ligne AMU-CNSS n'a rien à y faire) et perçu à tort comme un
                # mélange. Le badge "Double assurance" (déjà présent,
                # est_double_assurance) suffit à signaler le fait sans
                # dupliquer une ligne entière hors du filtre demandé.
                result.append({
                    'assurance': assurance_complementaire,
                    'assurance_label': _label_assurance(assurance_complementaire),
                    'type_assurance': 'complementaire',
                    'patient_id': patient.id,
                    'patient_nom': f"{patient.prenom} {patient.nom}".strip() or patient.nom,
                    'numero_assure': '',
                    'numero_assure2': patient.numero_assure2 or '',
                    'societe': societe_assurance2,
                    'montant_beneficiaire': total_reste_patient,
                    'part_assurance': total_part_cac,
                    'nb_actes': nb_actes if nb_actes > 0 else len(ventes_patient),
                    'nb_ventes': len(ventes_patient),
                    'derniere_visite': derniere_visite.strftime('%d/%m/%Y') if derniere_visite else '',
                    'est_double_assurance': assurance_principale != 'non_assure',
                    'details': details_affichage,
                    'details_complet': details_liste,
                    'dates_ventes': [v.date_vente.strftime('%d/%m/%Y') for v in ventes_patient if v.date_vente]
                })

        # ============================================================
        # CAS 2 : Filtre sur une assurance PRINCIPALE
        # ============================================================
        elif est_filtre_principale:
            if assurance_principale == filtre_nom.lower():
                result.append({
                    'assurance': assurance_principale,
                    'assurance_label': _label_assurance(assurance_principale),
                    'type_assurance': 'principale',
                    'patient_id': patient.id,
                    'patient_nom': f"{patient.prenom} {patient.nom}".strip() or patient.nom,
                    'numero_assure': patient.numero_assure or '',
                    'numero_assure2': '',
                    'montant_beneficiaire': total_reste_patient,
                    'part_assurance': total_part_amu,
                    'nb_actes': nb_actes if nb_actes > 0 else len(ventes_patient),
                    'nb_ventes': len(ventes_patient),
                    'derniere_visite': derniere_visite.strftime('%d/%m/%Y') if derniere_visite else '',
                    'est_double_assurance': bool(assurance_complementaire and assurance_complementaire != '')
                })
        
        # ============================================================
        # CAS 3 : PAS DE FILTRE (Toutes les assurances)
        # ============================================================
        else:
            # Assurance principale
            if assurance_principale != 'non_assure':
                result.append({
                    'assurance': assurance_principale,
                    'assurance_label': _label_assurance(assurance_principale),
                    'type_assurance': 'principale',
                    'patient_id': patient.id,
                    'patient_nom': f"{patient.prenom} {patient.nom}".strip() or patient.nom,
                    'numero_assure': patient.numero_assure or '',
                    'numero_assure2': '',
                    'montant_beneficiaire': total_reste_patient,
                    'part_assurance': total_part_amu,
                    'nb_actes': nb_actes if nb_actes > 0 else len(ventes_patient),
                    'nb_ventes': len(ventes_patient),
                    'derniere_visite': derniere_visite.strftime('%d/%m/%Y') if derniere_visite else '',
                    'est_double_assurance': bool(assurance_complementaire and assurance_complementaire != '')
                })
            
            # Assurance complémentaire
            if assurance_complementaire and assurance_complementaire != '':
                result.append({
                    'assurance': assurance_complementaire,
                    'assurance_label': _label_assurance(assurance_complementaire),
                    'type_assurance': 'complementaire',
                    'patient_id': patient.id,
                    'patient_nom': f"{patient.prenom} {patient.nom}".strip() or patient.nom,
                    'numero_assure': '',
                    'numero_assure2': patient.numero_assure2 or '',
                    'societe': societe_assurance2,
                    'montant_beneficiaire': total_reste_patient,
                    'part_assurance': total_part_cac,
                    'nb_actes': nb_actes if nb_actes > 0 else len(ventes_patient),
                    'nb_ventes': len(ventes_patient),
                    'derniere_visite': derniere_visite.strftime('%d/%m/%Y') if derniere_visite else '',
                    'est_double_assurance': True,
                    'details': details_affichage,
                    'details_complet': details_liste,
                    'dates_ventes': [v.date_vente.strftime('%d/%m/%Y') for v in ventes_patient if v.date_vente]
                })
            
            # Non assuré
            if assurance_principale == 'non_assure' and not assurance_complementaire:
                result.append({
                    'assurance': 'non_assure',
                    'assurance_label': 'Non assuré',
                    'type_assurance': 'non_assure',
                    'patient_id': patient.id,
                    'patient_nom': f"{patient.prenom} {patient.nom}".strip() or patient.nom,
                    'numero_assure': patient.numero_assure or '',
                    'numero_assure2': '',
                    'montant_beneficiaire': total_prix,
                    'part_assurance': 0,
                    'nb_actes': nb_actes if nb_actes > 0 else len(ventes_patient),
                    'nb_ventes': len(ventes_patient),
                    'derniere_visite': derniere_visite.strftime('%d/%m/%Y') if derniere_visite else '',
                    'est_double_assurance': False,
                    'details': details_affichage,  # ⭐ NOUVEAU
                    'details_complet': details_liste  # ⭐ Pour export complet
                })
    
    result.sort(key=lambda x: (x['assurance'], x['patient_nom']))
    return result


# ============================================================
# IMPRESSION DE LA LISTE "PATIENTS PAR ASSURANCE"
# ============================================================
# ⭐ Remplace l'ancien bouton "Imprimer" (JS `imprimerListeAssurance()`) qui
# ouvrait un `window.open('', '_blank')` puis faisait `document.write()` en
# référençant des IDs DOM inexistants (`assuranceTotalMontant` etc.) — la
# fonction plantait avant même d'écrire quoi que ce soit, et le popup pouvait
# de toute façon être bloqué par le navigateur. Ici, page imprimable
# classique côté serveur, avec le même en-tête (logo/nom/adresse structure)
# que les autres documents imprimés (reçus, factures, bordereau).
@statistiques_bp.route('/assurance/liste-patients/print')
def liste_patients_print():
    structure_id = session.get('structure_id')
    if not structure_id:
        return "Structure non trouvée", 400

    periode = request.args.get('periode', 'mois')
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    assurance_filter = request.args.get('assurance', 'toutes')
    type_assurance = request.args.get('type_assurance', 'toutes')
    societe_filtre = (request.args.get('societe') or '').strip()

    ventes, patients, patients_dict, dates = _ventes_filtrees(
        structure_id, periode, date_debut_str, date_fin_str, assurance_filter, type_assurance
    )
    lignes = get_patients_par_assurance(ventes, patients, patients_dict, type_assurance, assurance_filter)

    if societe_filtre and societe_filtre != 'toutes':
        lignes = [l for l in lignes if (l.get('societe') or '').strip().lower() == societe_filtre.lower()]

    total_beneficiaire = 0.0
    total_part_assurance = 0.0
    patients_uniques = set()
    for l in lignes:
        total_part_assurance += float(l.get('part_assurance') or 0)
        if l.get('patient_id') not in patients_uniques:
            patients_uniques.add(l.get('patient_id'))
            total_beneficiaire += float(l.get('montant_beneficiaire') or 0)

    structure = _get_structure_info(structure_id)

    # ⭐ Libellé propre pour l'en-tête imprimé — l'ancienne version affichait
    # la valeur brute du filtre en majuscules (ex: "PRINCIPALE:AMU_CNSS"
    # depuis l'introduction de la clé composée type:nom).
    if assurance_filter == 'toutes':
        assurance_filtre_label = None
    elif assurance_filter == 'non_assure':
        assurance_filtre_label = 'Non assuré'
    else:
        _, nom_filtre = _parse_assurance_filter(assurance_filter)
        assurance_filtre_label = _label_assurance(nom_filtre)

    return render_template(
        'statistiques_liste_patients_print.html',
        structure=structure,
        periode_libelle=dates['libelle'],
        assurance_filtre=assurance_filtre_label,
        societe_filtre=societe_filtre,
        lignes=lignes,
        total_beneficiaire=total_beneficiaire,
        total_part_assurance=total_part_assurance,
        nb_patients=len(patients_uniques),
        now=datetime.now(),
    )


# ============================================================
# BORDEREAU IMPRIMABLE PAR COMPAGNIE D'ASSURANCE
# ============================================================
# ⭐ NOUVEAU : document propre, détaillé, prêt à imprimer/envoyer à une
# compagnie (GTA, SUNU, AMU-CNSS...) pour justifier un remboursement —
# distinct de l'ancien bouton "Imprimer" qui se contentait de dupliquer le
# tableau HTML affiché à l'écran, sans en-tête ni mise en forme dédiée.

@statistiques_bp.route('/assurance/bordereau')
def bordereau_assurance():
    """Génère un bordereau imprimable détaillé pour UNE compagnie
    d'assurance (optionnellement restreint à UNE société souscriptrice) sur
    une période donnée (patients, prestations, montants), arrêté en toutes
    lettres — prêt à imprimer en PDF (Ctrl+P > Enregistrer en PDF, comme les
    autres documents imprimables de l'application) et à adresser à la
    compagnie."""
    structure_id = session.get('structure_id')
    if not structure_id:
        return "Structure non trouvée", 400

    assurance_code = request.args.get('assurance', '').strip()
    if not assurance_code or assurance_code == 'toutes':
        return "Veuillez préciser une compagnie d'assurance (paramètre 'assurance')", 400

    # ⭐ FIX : même correctif que _ventes_filtrees/get_patients_par_assurance
    # — la colonne à filtrer (principale ou complémentaire) vient de la clé
    # explicite du filtre, plus d'une déduction par nom qui mélangeait une
    # compagnie "Autre" en principale avec la même compagnie en
    # complémentaire (voir _parse_assurance_filter pour le détail).
    type_hint, nom_assurance = _parse_assurance_filter(assurance_code)
    est_principale = type_hint == 'principale'

    societe_filtre = (request.args.get('societe') or '').strip()

    periode = request.args.get('periode', 'mois')
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    dates = get_dates_periode(periode, date_debut_str, date_fin_str)

    debut, fin = dates['debut'], dates['fin']
    if isinstance(debut, date) and not isinstance(debut, datetime):
        debut = datetime.combine(debut, datetime.min.time())
        fin = datetime.combine(fin, datetime.max.time())

    query = db.session.query(Vente).join(
        Patient, Vente.patient_id == Patient.id
    ).filter(
        Vente.structure_id == structure_id,
        Vente.date_vente >= debut,
        Vente.date_vente <= fin,
        # ⭐ FIX (2) : "validee OU NULL" excluait encore à tort toute vente
        # au statut 'partielle' (réglée en partie mais bien réelle, non
        # annulée — ~19% des ventes de cette structure) du bordereau,
        # malgré l'intention documentée juste au-dessus ("statut IS NULL
        # OR statut != 'annulee'") — la condition elle-même ne
        # correspondait pas au commentaire.
        or_(Vente.statut != 'annulee', Vente.statut.is_(None)),
    )
    if est_principale:
        query = query.filter(db.func.lower(Patient.type_assurance) == nom_assurance.lower())
    else:
        query = query.filter(db.func.lower(Vente.assurance2_nom) == nom_assurance.lower())

    ventes = query.order_by(Vente.date_vente).all()

    # Regroupement par patient, détail des prestations, calcul des montants
    lignes = []
    total_montant = 0.0
    total_part_assurance = 0.0
    total_reste = 0.0

    for v in ventes:
        patient = Patient.query.get(v.patient_id)

        # Filtre par société souscriptrice (assurance complémentaire
        # uniquement) : instantané pris à la vente, sinon valeur courante
        # sur la fiche patient (ventes antérieures à ce champ).
        if not est_principale and societe_filtre:
            societe_vente = _societe_vente(v) or (patient.societe_assurance2 if patient else '')
            if (societe_vente or '').strip().lower() != societe_filtre.lower():
                continue

        montants = calculer_montants_vente(v)
        part_assurance = montants['part_amu'] if est_principale else montants['part_cac']
        numero_assure = None
        if patient:
            numero_assure = patient.numero_assure if est_principale else patient.numero_assure2

        prestations = []
        for item in (v.actes or []) + (v.produits or []):
            if isinstance(item, dict):
                nom = item.get('nom', 'Prestation')
                qte = item.get('quantite', 1)
                prix = item.get('prix') or item.get('prix_reel') or item.get('total') or 0
                prestations.append(f"{nom} (x{qte}) — {float(prix):,.0f} F".replace(',', ' '))

        lignes.append({
            'date': v.date_vente.strftime('%d/%m/%Y') if v.date_vente else '-',
            'patient_nom': v.patient_nom,
            'numero_assure': numero_assure or '-',
            'prestations': prestations,
            'montant_total': montants['total_prix'],
            'part_assurance': part_assurance,
            'reste_patient': montants['reste_patient'],
        })
        total_montant += montants['total_prix']
        total_part_assurance += part_assurance
        total_reste += montants['reste_patient']

    nom_compagnie = _label_assurance(nom_assurance)

    structure = _get_structure_info(structure_id)

    # Numéro de bordereau (traçabilité du document) et montant arrêté en
    # toutes lettres, adressé à la compagnie/société.
    numero_bordereau = f"BDX-{structure_id}-{nom_assurance.upper()}-{datetime.now().strftime('%Y%m%d%H%M')}"
    montant_lettres = montant_en_lettres_fcfa(total_part_assurance)

    return render_template(
        'statistiques_assurance_print.html',
        structure=structure,
        nom_compagnie=nom_compagnie,
        nom_societe=societe_filtre,
        numero_bordereau=numero_bordereau,
        periode_libelle=dates['libelle'],
        lignes=lignes,
        total_montant=total_montant,
        total_part_assurance=total_part_assurance,
        total_reste=total_reste,
        montant_lettres=montant_lettres,
        nb_patients=len(set(l['patient_nom'] for l in lignes)),
        now=datetime.now(),
    )