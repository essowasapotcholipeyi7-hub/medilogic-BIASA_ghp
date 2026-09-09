# utils/plan_comptable_syscohada.py
# ============================================================
# PLAN COMPTABLE SYSCOHADA (révisé) — adapté à une structure médicale
# ============================================================
# Source unique de vérité pour la nomenclature des comptes, utilisée à la
# fois par le script d'initialisation (scripts/seed_plan_comptable_syscohada.py)
# et par le moteur de génération d'écritures (services/comptabilite_service.py),
# qui peut créer un compte manquant à la volée avec le même libellé/type.
#
# type : 'actif' | 'passif' | 'charge' | 'produit'  (utilisé par les rapports
#        bilan / compte de résultat déjà existants dans routes/comptabilite.py)
# classe : classe SYSCOHADA (1 à 7) du numéro de compte

PLAN_COMPTABLE = [
    # ---------------- CLASSE 1 — Ressources durables ----------------
    {'numero': '101', 'nom': "Capital social", 'type': 'passif', 'classe': '1'},
    {'numero': '120', 'nom': "Résultat net de l'exercice (bénéfice)", 'type': 'passif', 'classe': '1'},
    {'numero': '129', 'nom': "Résultat net de l'exercice (perte)", 'type': 'actif', 'classe': '1'},
    {'numero': '131', 'nom': "Report à nouveau", 'type': 'passif', 'classe': '1'},

    # ---------------- CLASSE 2 — Actif immobilisé ----------------
    {'numero': '2183', 'nom': "Matériel médical et informatique", 'type': 'actif', 'classe': '2'},
    {'numero': '2184', 'nom': "Mobilier et matériel de bureau", 'type': 'actif', 'classe': '2'},
    {'numero': '2818', 'nom': "Amortissements du matériel médical et informatique", 'type': 'actif', 'classe': '2'},

    # ---------------- CLASSE 3 — Stocks ----------------
    {'numero': '3751', 'nom': "Stock de médicaments et produits pharmaceutiques", 'type': 'actif', 'classe': '3'},
    {'numero': '3752', 'nom': "Stock de fournitures et consommables médicaux", 'type': 'actif', 'classe': '3'},
    {'numero': '3757', 'nom': "Stock de montures et verres (optique)", 'type': 'actif', 'classe': '3'},

    # ---------------- CLASSE 4 — Tiers ----------------
    {'numero': '401', 'nom': "Fournisseurs", 'type': 'passif', 'classe': '4'},
    {'numero': '4011', 'nom': "Fournisseurs — médicaments et consommables", 'type': 'passif', 'classe': '4'},
    {'numero': '4111', 'nom': "Clients — patients (ventes courantes)", 'type': 'actif', 'classe': '4'},
    {'numero': '41171', 'nom': "Clients douteux ou litigieux", 'type': 'actif', 'classe': '4'},
    {'numero': '491', 'nom': "Dépréciation des comptes clients", 'type': 'actif', 'classe': '4'},
    {'numero': '411211', 'nom': "AMU-CNSS — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411212', 'nom': "AMU-INAM — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411221', 'nom': "Assurance GTA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411222', 'nom': "Assurance SUNU — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411223', 'nom': "Assurance FIDELIA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411224', 'nom': "Assurance NSIA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411225', 'nom': "Assurance GCA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411226', 'nom': "Assurance C2A — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411227', 'nom': "Assurance OLEA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '411228', 'nom': "Autres assurances / tiers-payants à recevoir", 'type': 'actif', 'classe': '4'},
    # ⭐ Sous-compte dédié (4211), pas 421/422 : ces deux numéros sont déjà
    # utilisés par des structures existantes pour "Fournisseurs" / "Fournisseurs
    # - Effets à payer" — les réutiliser aurait fait atterrir les avances sur
    # salaire dans un compte déjà nommé (et affiché) comme un compte fournisseur.
    {'numero': '4211', 'nom': "Personnel — avances et acomptes", 'type': 'actif', 'classe': '4'},
    # ⭐ Même logique que 4211 (421/422 déjà occupés) : dette envers le
    # personnel pour le NET À PAYER de la paie — reconnue au journal SAL,
    # éteinte au journal CAI/BQ quand le salaire est réellement décaissé
    # (non-mélange SYSCOHADA : la paie et son paiement restent deux
    # écritures distinctes, liées par la même pièce).
    {'numero': '4231', 'nom': "Personnel — rémunérations dues (net à payer)", 'type': 'passif', 'classe': '4'},
    # ⭐ Organismes sociaux, subdivisés par organisme réel (comme pour les
    # assurances 411211/411221...) — un salarié du privé et un salarié du
    # public ne doivent jamais créditer le même compte "CNSS" générique.
    {'numero': '4311', 'nom': "CNSS — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4312', 'nom': "CNSS — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4313', 'nom': "CRT — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4314', 'nom': "CRT — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4315', 'nom': "AMU-CNSS — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4316', 'nom': "AMU-CNSS — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4317', 'nom': "AMU-INAM — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4318', 'nom': "AMU-INAM — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4319', 'nom': "Formation professionnelle — à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '447', 'nom': "État — IRPP à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '4713', 'nom': "Écarts et opérations d'attente (caisse)", 'type': 'actif', 'classe': '4'},

    # ---------------- CLASSE 5 — Trésorerie ----------------
    {'numero': '521', 'nom': "Banque", 'type': 'actif', 'classe': '5'},
    {'numero': '571', 'nom': "Caisse espèces", 'type': 'actif', 'classe': '5'},

    # ---------------- CLASSE 6 — Charges ----------------
    {'numero': '601', 'nom': "Achats de médicaments et produits pharmaceutiques", 'type': 'charge', 'classe': '6'},
    {'numero': '602', 'nom': "Achats de fournitures et consommables médicaux", 'type': 'charge', 'classe': '6'},
    {'numero': '604', 'nom': "Achats de matériel et petit équipement médical", 'type': 'charge', 'classe': '6'},
    {'numero': '605', 'nom': "Achats de montures et verres (optique)", 'type': 'charge', 'classe': '6'},
    {'numero': '611', 'nom': "Transports sur achats/ventes", 'type': 'charge', 'classe': '6'},
    {'numero': '613', 'nom': "Locations (loyers)", 'type': 'charge', 'classe': '6'},
    {'numero': '614', 'nom': "Charges locatives (eau, électricité, gaz)", 'type': 'charge', 'classe': '6'},
    {'numero': '615', 'nom': "Entretien, réparations et maintenance", 'type': 'charge', 'classe': '6'},
    {'numero': '616', 'nom': "Primes d'assurances", 'type': 'charge', 'classe': '6'},
    {'numero': '618', 'nom': "Documentation, formation, colloques", 'type': 'charge', 'classe': '6'},
    {'numero': '622', 'nom': "Rémunérations d'intermédiaires et honoraires", 'type': 'charge', 'classe': '6'},
    {'numero': '624', 'nom': "Transport de personnel", 'type': 'charge', 'classe': '6'},
    {'numero': '625', 'nom': "Déplacements, missions et réceptions", 'type': 'charge', 'classe': '6'},
    {'numero': '626', 'nom': "Frais postaux et de télécommunications", 'type': 'charge', 'classe': '6'},
    {'numero': '627', 'nom': "Services bancaires et assimilés", 'type': 'charge', 'classe': '6'},
    {'numero': '628', 'nom': "Fournitures de bureau et charges diverses", 'type': 'charge', 'classe': '6'},
    {'numero': '631', 'nom': "Impôts et taxes directs", 'type': 'charge', 'classe': '6'},
    {'numero': '635', 'nom': "Autres impôts et taxes", 'type': 'charge', 'classe': '6'},
    {'numero': '661', 'nom': "Salaires et appointements du personnel", 'type': 'charge', 'classe': '6'},
    {'numero': '663', 'nom': "Indemnités et avantages divers au personnel", 'type': 'charge', 'classe': '6'},
    # ⭐ Charges sociales patronales (classe 666 SYSCOHADA), subdivisées par
    # organisme réel (privé/CNSS ou public/CRT, AMU-CNSS ou AMU-INAM) — la
    # classe 664 (rémunérations du personnel extérieur à l'entreprise) ne
    # convient pas ici, elle concerne le personnel intérimaire/prestataire.
    {'numero': '6661', 'nom': "Charges sociales — CNSS part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '6662', 'nom': "Charges sociales — CRT part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '6663', 'nom': "Charges sociales — AMU-CNSS part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '6664', 'nom': "Charges sociales — AMU-INAM part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '6665', 'nom': "Charges sociales — Formation professionnelle", 'type': 'charge', 'classe': '6'},
    {'numero': '651', 'nom': "Pertes sur créances irrécouvrables", 'type': 'charge', 'classe': '6'},
    {'numero': '671', 'nom': "Intérêts et frais financiers", 'type': 'charge', 'classe': '6'},
    {'numero': '681', 'nom': "Dotations aux amortissements", 'type': 'charge', 'classe': '6'},
    {'numero': '6591', 'nom': "Dotations aux provisions pour dépréciation des comptes clients", 'type': 'charge', 'classe': '6'},
    {'numero': '691', 'nom': "Rabais, remises et ristournes accordés", 'type': 'charge', 'classe': '6'},

    # ---------------- CLASSE 7 — Produits ----------------
    {'numero': '7011', 'nom': "Ventes de pharmacie", 'type': 'produit', 'classe': '7'},
    {'numero': '7012', 'nom': "Ventes de lunetterie / optique", 'type': 'produit', 'classe': '7'},
    {'numero': '7061', 'nom': "Consultations", 'type': 'produit', 'classe': '7'},
    {'numero': '7062', 'nom': "Actes de laboratoire", 'type': 'produit', 'classe': '7'},
    {'numero': '7063', 'nom': "Imagerie médicale", 'type': 'produit', 'classe': '7'},
    {'numero': '7064', 'nom': "Hospitalisation", 'type': 'produit', 'classe': '7'},
    {'numero': '7068', 'nom': "Autres prestations médicales", 'type': 'produit', 'classe': '7'},
    {'numero': '754', 'nom': "Subventions et dons reçus", 'type': 'produit', 'classe': '7'},
    {'numero': '758', 'nom': "Produits divers", 'type': 'produit', 'classe': '7'},
    {'numero': '771', 'nom': "Intérêts et produits financiers", 'type': 'produit', 'classe': '7'},
    {'numero': '7591', 'nom': "Reprises de provisions pour dépréciation des comptes clients", 'type': 'produit', 'classe': '7'},
]

# Index rapide numero -> définition, pour la création à la volée dans le service.
PLAN_COMPTABLE_PAR_NUMERO = {c['numero']: c for c in PLAN_COMPTABLE}

# Numéros de comptes de l'ancien plan ad-hoc (non-SYSCOHADA) à désactiver lors
# de la migration — jamais référencés par une ligne d'écriture puisque la
# génération automatique n'a jamais tourné en production.
ANCIENS_COMPTES_A_DESACTIVER = [
    '211', '212', '213', '214',
    '411', '412', '413', '414',
    '421', '422',
    '611', '612', '613', '614', '615', '616', '617', '618', '619',
    '621', '622', '623', '624', '625',
    '631', '632', '633',
    '711', '712', '713', '714', '715', '716', '717', '718',
    '721', '722',
]

# Comptes de trésorerie ("Caisse Trésorerie" — argent réellement disponible)
COMPTES_TRESORERIE = ['521', '571']

# Préfixe des comptes de chiffre d'affaires ("Caisse Chiffre d'affaires")
PREFIXE_COMPTES_CA = '7'

# Compte clients "patients" par défaut (créances courantes)
COMPTE_CLIENTS_PATIENTS = '4111'

# Compte d'attente pour écarts non résolus automatiquement
COMPTE_ATTENTE = '4713'

# Compte fournisseurs par défaut (dettes courantes — achats à crédit).
# Un seul compte partagé pour tous les fournisseurs, comme COMPTE_CLIENTS_PATIENTS
# côté clients : le détail par fournisseur (qui doit quoi) est suivi au niveau
# applicatif (modèle Fournisseur/AchatFournisseur), pas par un sous-compte
# comptable dédié à chacun.
COMPTE_FOURNISSEURS = '401'

# Correspondance assurance (telle qu'utilisée dans les ventes) -> numéro de
# compte de tiers-payant à recevoir.
COMPTE_PAR_ASSURANCE = {
    'amu-cnss': '411211', 'amu_cnss': '411211', 'cnss': '411211',
    'amu-inam': '411212', 'amu_inam': '411212', 'inam': '411212', 'amu': '411212',
    'gta': '411221',
    'sunu': '411222',
    'fidelia': '411223',
    'nsia': '411224',
    'gca': '411225',
    'c2a': '411226',
    'olea': '411227',
}


# ============================================================
# COMPTES DE PAIE — retraite (CNSS/CRT) et AMU (AMU-CNSS/AMU-INAM)
# ============================================================
# ⭐ Adapté aux précisions du bulletin de paie (voir services/paie_service.py) :
# chaque organisme réel a ses propres comptes de tiers à reverser et sa
# propre charge patronale, pour ne jamais mélanger, par exemple, la CNSS
# d'un salarié du privé avec la CRT d'un salarié du public.
COMPTES_RETRAITE_PAR_ORGANISME = {
    'CNSS': {'salarial': '4311', 'patronal': '4312', 'charge': '6661'},
    'CRT': {'salarial': '4313', 'patronal': '4314', 'charge': '6662'},
}
COMPTES_AMU_PAR_ORGANISME = {
    'AMU-CNSS': {'salarial': '4315', 'patronal': '4316', 'charge': '6663'},
    'AMU-INAM': {'salarial': '4317', 'patronal': '4318', 'charge': '6664'},
}
COMPTE_FORMATION_PRO_CHARGE = '6665'
COMPTE_FORMATION_PRO_A_REVERSER = '4319'
COMPTE_IRPP_A_REVERSER = '447'
COMPTE_PERSONNEL_AVANCES = '4211'   # prêts / acomptes / autres retenues sur salaire
COMPTE_PERSONNEL_A_PAYER = '4231'   # net à payer — dette avant décaissement (journal SAL -> CAI/BQ)


def compte_assurance(nom_assurance):
    """Retourne le numéro de compte de tiers-payant pour une assurance donnée."""
    if not nom_assurance:
        return '411228'
    cle = str(nom_assurance).lower().strip()
    if 'amu' in cle:
        if 'cnss' in cle:
            return '411211'
        if 'inam' in cle:
            return '411212'
        return '411212'
    return COMPTE_PAR_ASSURANCE.get(cle, '411228')
