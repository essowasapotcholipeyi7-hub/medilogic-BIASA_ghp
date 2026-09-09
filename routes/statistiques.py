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
    """Récupère la liste de TOUTES les assurances utilisées"""
    try:
        structure_id = session.get('structure_id')
        
        if not structure_id:
            return jsonify({'error': 'Structure non trouvée'}), 400
        
        # Récupérer les assurances principales depuis Patient.type_assurance
        assurances_patient = db.session.query(
            Patient.type_assurance,
            db.func.count(Patient.id).label('count')
        ).filter(
            Patient.structure_id == structure_id,
            Patient.type_assurance != None,
            Patient.type_assurance != '',
            Patient.type_assurance != 'non_assure'
        ).group_by(Patient.type_assurance).all()
        
        # Récupérer les assurances complémentaires depuis Vente.assurance2_nom
        assurances_complementaires = db.session.query(
            Vente.assurance2_nom,
            db.func.count(Vente.id).label('count')
        ).filter(
            Vente.structure_id == structure_id,
            Vente.statut == 'validee',
            Vente.assurance2_nom != None,
            Vente.assurance2_nom != '',
            Vente.assurance2_nom != 'Aucune'
        ).group_by(Vente.assurance2_nom).all()
        
        toutes_assurances = set()
        
        for row in assurances_patient:
            if row[0]:
                toutes_assurances.add(row[0].lower().strip())
        
        for row in assurances_complementaires:
            if row[0]:
                toutes_assurances.add(row[0].lower().strip())
        
        # Ajouter 'non_assure' si des patients non assurés existent
        non_assures = db.session.query(Patient).filter(
            Patient.structure_id == structure_id,
            or_(
                Patient.type_assurance == None,
                Patient.type_assurance == '',
                Patient.type_assurance == 'non_assure'
            )
        ).first()
        
        if non_assures:
            toutes_assurances.add('non_assure')
        
        result_list = []
        
        for assurance in sorted(toutes_assurances):
            if assurance == 'non_assure':
                nb = db.session.query(Patient.id).filter(
                    Patient.structure_id == structure_id,
                    or_(
                        Patient.type_assurance == None,
                        Patient.type_assurance == '',
                        Patient.type_assurance == 'non_assure'
                    )
                ).count()
                label = 'Non assuré'
                type_assurance = 'non_assure'
            else:
                nb = db.session.query(Patient.id).filter(
                    Patient.structure_id == structure_id,
                    Patient.type_assurance.ilike(f'%{assurance}%')
                ).count()
                
                if assurance in ['amu_cnss', 'amu-cnss']:
                    label = 'AMU-CNSS'
                    type_assurance = 'principale'
                elif assurance in ['amu_inam', 'amu-inam']:
                    label = 'AMU-INAM'
                    type_assurance = 'principale'
                elif assurance in ['amu_tns', 'amu-tns']:
                    label = 'AMU-TNS'
                    type_assurance = 'principale'
                else:
                    label = ASSURANCE_LABELS.get(assurance, assurance.upper())
                    type_assurance = 'complementaire'
            
            result_list.append({
                'key': assurance,
                'label': label,
                'nb_patients': nb or 0,
                'type': type_assurance
            })
        
        def sort_key(x):
            if x['type'] == 'non_assure':
                return (2, x['label'])
            elif x['type'] == 'principale':
                return (0, x['label'])
            else:
                return (1, x['label'])
        
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
    
    # ⭐ Parcourir les actes
    for acte in actes:
        if isinstance(acte, dict):
            prix = float(acte.get('prix', 0))
            pbr = float(acte.get('pbr', 0))
            prise_amu = acte.get('prise_en_charge_amu', False)
            
            total_prix += prix
            
            if prise_amu:
                total_pbr_amu += pbr
    
    # ⭐ Parcourir les produits
    for produit in produits:
        if isinstance(produit, dict):
            prix = float(produit.get('prix_reel', produit.get('prix', 0)))
            pbr = float(produit.get('pbr', 0))
            prise_amu = produit.get('prise_en_charge_amu', False)
            
            total_prix += prix
            
            if prise_amu:
                total_pbr_amu += pbr
    
    # ⭐ Taux d'assurance
    taux_amu = float(vente.taux_assurance or 80) / 100
    taux_cac = float(vente.taux_assurance2 or 0) / 100 if vente.taux_assurance2 else 0
    
    # ⭐ Part AMU = PBR_AMU × Taux AMU
    part_amu = total_pbr_amu * taux_amu
    
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
        Vente.statut == 'validee'
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
    if type_assurance != 'toutes':
        if type_assurance == 'principale':
            query = query.filter(
                or_(
                    Patient.type_assurance.ilike('%amu_cnss%'),
                    Patient.type_assurance.ilike('%amu_inam%')
                )
            )
        elif type_assurance == 'complementaire':
            query = query.filter(
                and_(
                    Vente.assurance2_nom != None,
                    Vente.assurance2_nom != '',
                    Vente.assurance2_nom != 'Aucune'
                )
            )
        elif type_assurance == 'double':
            query = query.filter(
                and_(
                    or_(
                        Patient.type_assurance.ilike('%amu_cnss%'),
                        Patient.type_assurance.ilike('%amu_inam%')
                    ),
                    Vente.assurance2_nom != None,
                    Vente.assurance2_nom != '',
                    Vente.assurance2_nom != 'Aucune'
                )
            )

    # Filtrer par assurance spécifique
    if assurance_filter != 'toutes':
        if assurance_filter == 'non_assure':
            query = query.filter(
                or_(
                    Patient.type_assurance == None,
                    Patient.type_assurance == '',
                    Patient.type_assurance == 'non_assure'
                )
            )
        else:
            if assurance_filter.lower() in ASSURANCES_PRINCIPALES:
                query = query.filter(
                    Patient.type_assurance.ilike(f'%{assurance_filter}%')
                )
            else:
                query = query.filter(
                    Vente.assurance2_nom.ilike(f'%{assurance_filter}%')
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
        assurance_principale = patients_dict.get(vente.patient_id, 'non_assure') or 'non_assure'
        if assurance_principale == '':
            assurance_principale = 'non_assure'

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
        if assurance == 'non_assure':
            assurance_label = 'Non assuré'
        elif assurance == 'amu_cnss':
            assurance_label = 'AMU-CNSS'
        elif assurance == 'amu_inam':
            assurance_label = 'AMU-INAM'
        else:
            assurance_label = ASSURANCE_LABELS.get(assurance, assurance.upper())

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
    
    est_filtre_actif = assurance_filter != 'toutes' and assurance_filter != 'non_assure'
    est_filtre_principale = est_filtre_actif and assurance_filter.lower() in ASSURANCES_PRINCIPALES
    est_filtre_complementaire = est_filtre_actif and not est_filtre_principale
    
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

        
        assurance_principale = patients_dict.get(patient.id, 'non_assure') or 'non_assure'
        if assurance_principale == '':
            assurance_principale = 'non_assure'
        
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
        # CAS 1 : Filtre sur une assurance COMPLÉMENTAIRE
        # ============================================================
        if est_filtre_complementaire:
            if assurance_complementaire == assurance_filter.lower():
                # Ligne de l'assurance COMPLÉMENTAIRE
                result.append({
                    'assurance': assurance_complementaire,
                    'assurance_label': assurance_complementaire.upper(),
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

                # Ligne de l'assurance PRINCIPALE
                if assurance_principale != 'non_assure':
                    if assurance_principale == 'amu_cnss':
                        label = 'AMU-CNSS'
                    elif assurance_principale == 'amu_inam':
                        label = 'AMU-INAM'
                    else:
                        label = assurance_principale.upper()
                    
                    result.append({
                        'assurance': assurance_principale,
                        'assurance_label': label,
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
                        'est_double_assurance': True
                    })
        
        # ============================================================
        # CAS 2 : Filtre sur une assurance PRINCIPALE
        # ============================================================
        elif est_filtre_principale:
            if assurance_principale == assurance_filter.lower():
                if assurance_principale == 'amu_cnss':
                    label = 'AMU-CNSS'
                elif assurance_principale == 'amu_inam':
                    label = 'AMU-INAM'
                else:
                    label = assurance_principale.upper()
                
                result.append({
                    'assurance': assurance_principale,
                    'assurance_label': label,
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
                if assurance_principale == 'amu_cnss':
                    label = 'AMU-CNSS'
                elif assurance_principale == 'amu_inam':
                    label = 'AMU-INAM'
                else:
                    label = assurance_principale.upper()
                
                result.append({
                    'assurance': assurance_principale,
                    'assurance_label': label,
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
                    'assurance_label': assurance_complementaire.upper(),
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

    return render_template(
        'statistiques_liste_patients_print.html',
        structure=structure,
        periode_libelle=dates['libelle'],
        assurance_filtre=assurance_filter,
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

    societe_filtre = (request.args.get('societe') or '').strip()

    periode = request.args.get('periode', 'mois')
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    dates = get_dates_periode(periode, date_debut_str, date_fin_str)

    debut, fin = dates['debut'], dates['fin']
    if isinstance(debut, date) and not isinstance(debut, datetime):
        debut = datetime.combine(debut, datetime.min.time())
        fin = datetime.combine(fin, datetime.max.time())

    est_principale = assurance_code.lower() in ASSURANCES_PRINCIPALES

    query = db.session.query(Vente).join(
        Patient, Vente.patient_id == Patient.id
    ).filter(
        Vente.structure_id == structure_id,
        Vente.date_vente >= debut,
        Vente.date_vente <= fin,
        Vente.statut == 'validee',
    )
    if est_principale:
        query = query.filter(Patient.type_assurance.ilike(f'%{assurance_code}%'))
    else:
        query = query.filter(Vente.assurance2_nom.ilike(f'%{assurance_code}%'))

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

    if assurance_code.lower() in ('amu_cnss', 'amu-cnss'):
        nom_compagnie = 'AMU-CNSS'
    elif assurance_code.lower() in ('amu_inam', 'amu-inam'):
        nom_compagnie = 'AMU-INAM'
    else:
        nom_compagnie = ASSURANCE_LABELS.get(assurance_code.lower(), assurance_code.upper())

    structure = _get_structure_info(structure_id)

    # Numéro de bordereau (traçabilité du document) et montant arrêté en
    # toutes lettres, adressé à la compagnie/société.
    numero_bordereau = f"BDX-{structure_id}-{assurance_code.upper()}-{datetime.now().strftime('%Y%m%d%H%M')}"
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