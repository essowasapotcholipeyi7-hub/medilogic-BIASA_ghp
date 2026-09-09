# utils/plan_comptable_syscohada.py
# ============================================================
# PLAN COMPTABLE SYSCOHADA (révisé) — adapté à une structure médicale
# ============================================================
# Source unique de vérité pour la nomenclature des comptes, utilisée à la
# fois par le script d'initialisation (scripts/seed_plan_comptable_syscohada.py)
# et par le moteur de génération d'écritures (services/comptabilite_service.py),
# qui peut créer un compte manquant à la volée avec le même libellé/type.
#
# ⭐ Numéros à 8 chiffres (harmonisation demandée, format SYSCOHADA détaillé) :
# chaque numéro "court" du plan SYSCOHADA de référence (classe + sous-comptes,
# ex. 401, 4111, 411211) est complété à droite par des zéros jusqu'à 8
# chiffres (401 -> 40100000, 4111 -> 41110000, 411211 -> 41121100). Le
# premier chiffre (la classe SYSCOHADA) et tous les préfixes existants restent
# donc inchangés — tout filtrage par préfixe (numero.like('7%'), classe='2'...)
# continue de fonctionner sans adaptation.
#
# type : 'actif' | 'passif' | 'charge' | 'produit'  (utilisé par les rapports
#        bilan / compte de résultat déjà existants dans routes/comptabilite.py)
# classe : classe SYSCOHADA (1 à 7) du numéro de compte

PLAN_COMPTABLE = [
    # ---------------- CLASSE 1 — Ressources durables ----------------
    {'numero': '10100000', 'nom': "Capital social", 'type': 'passif', 'classe': '1'},
    {'numero': '12000000', 'nom': "Résultat net de l'exercice (bénéfice)", 'type': 'passif', 'classe': '1'},
    {'numero': '12900000', 'nom': "Résultat net de l'exercice (perte)", 'type': 'actif', 'classe': '1'},
    {'numero': '13100000', 'nom': "Report à nouveau", 'type': 'passif', 'classe': '1'},

    # ---------------- CLASSE 2 — Actif immobilisé ----------------
    {'numero': '21830000', 'nom': "Matériel médical et informatique", 'type': 'actif', 'classe': '2'},
    {'numero': '21840000', 'nom': "Mobilier et matériel de bureau", 'type': 'actif', 'classe': '2'},
    {'numero': '28180000', 'nom': "Amortissements du matériel médical et informatique", 'type': 'actif', 'classe': '2'},

    # ---------------- CLASSE 3 — Stocks ----------------
    {'numero': '37510000', 'nom': "Stock de médicaments et produits pharmaceutiques", 'type': 'actif', 'classe': '3'},
    {'numero': '37520000', 'nom': "Stock de fournitures et consommables médicaux", 'type': 'actif', 'classe': '3'},
    {'numero': '37570000', 'nom': "Stock de montures et verres (optique)", 'type': 'actif', 'classe': '3'},

    # ---------------- CLASSE 4 — Tiers ----------------
    {'numero': '40100000', 'nom': "Fournisseurs", 'type': 'passif', 'classe': '4'},
    {'numero': '40110000', 'nom': "Fournisseurs — médicaments et consommables", 'type': 'passif', 'classe': '4'},
    {'numero': '41110000', 'nom': "Clients — patients (ventes courantes)", 'type': 'actif', 'classe': '4'},
    {'numero': '41171000', 'nom': "Clients douteux ou litigieux", 'type': 'actif', 'classe': '4'},
    {'numero': '49100000', 'nom': "Dépréciation des comptes clients", 'type': 'actif', 'classe': '4'},
    {'numero': '41121100', 'nom': "AMU-CNSS — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41121200', 'nom': "AMU-INAM — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    # ⭐ AMU-TNS (Travailleurs Non-Salariés) — administrée par la CNSS mais
    # panier de soins distinct de l'AMU-CNSS classique (colonne dédiée
    # "AMU-TNS" dans le Sheet actes/produits) : compte tiers-payant séparé.
    {'numero': '41121300', 'nom': "AMU-TNS — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122100', 'nom': "Assurance GTA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122200', 'nom': "Assurance SUNU — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122300', 'nom': "Assurance FIDELIA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122400', 'nom': "Assurance NSIA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122500', 'nom': "Assurance GCA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122600', 'nom': "Assurance C2A — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122700', 'nom': "Assurance OLEA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122800', 'nom': "Autres assurances / tiers-payants à recevoir", 'type': 'actif', 'classe': '4'},
    # ⭐ Sous-compte dédié (4211), pas 421/422 : ces deux numéros sont déjà
    # utilisés par des structures existantes pour "Fournisseurs" / "Fournisseurs
    # - Effets à payer" — les réutiliser aurait fait atterrir les avances sur
    # salaire dans un compte déjà nommé (et affiché) comme un compte fournisseur.
    {'numero': '42110000', 'nom': "Personnel — avances et acomptes", 'type': 'actif', 'classe': '4'},
    # ⭐ Même logique que 4211 (421/422 déjà occupés) : dette envers le
    # personnel pour le NET À PAYER de la paie — reconnue au journal SAL,
    # éteinte au journal CAI/BQ quand le salaire est réellement décaissé
    # (non-mélange SYSCOHADA : la paie et son paiement restent deux
    # écritures distinctes, liées par la même pièce).
    {'numero': '42310000', 'nom': "Personnel — rémunérations dues (net à payer)", 'type': 'passif', 'classe': '4'},
    # ⭐ Organismes sociaux, subdivisés par organisme réel (comme pour les
    # assurances 411211/411221...) — un salarié du privé et un salarié du
    # public ne doivent jamais créditer le même compte "CNSS" générique.
    {'numero': '43110000', 'nom': "CNSS — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43120000', 'nom': "CNSS — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43130000', 'nom': "CRT — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43140000', 'nom': "CRT — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43150000', 'nom': "AMU-CNSS — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43160000', 'nom': "AMU-CNSS — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43170000', 'nom': "AMU-INAM — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43180000', 'nom': "AMU-INAM — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43190000', 'nom': "Formation professionnelle — à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '44700000', 'nom': "État — IRPP à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '47130000', 'nom': "Écarts et opérations d'attente (caisse)", 'type': 'actif', 'classe': '4'},

    # ---------------- CLASSE 5 — Trésorerie ----------------
    {'numero': '52100000', 'nom': "Banque", 'type': 'actif', 'classe': '5'},
    {'numero': '57100000', 'nom': "Caisse espèces", 'type': 'actif', 'classe': '5'},

    # ---------------- CLASSE 6 — Charges ----------------
    {'numero': '60100000', 'nom': "Achats de médicaments et produits pharmaceutiques", 'type': 'charge', 'classe': '6'},
    {'numero': '60200000', 'nom': "Achats de fournitures et consommables médicaux", 'type': 'charge', 'classe': '6'},
    {'numero': '60400000', 'nom': "Achats de matériel et petit équipement médical", 'type': 'charge', 'classe': '6'},
    {'numero': '60500000', 'nom': "Achats de montures et verres (optique)", 'type': 'charge', 'classe': '6'},
    {'numero': '61100000', 'nom': "Transports sur achats/ventes", 'type': 'charge', 'classe': '6'},
    {'numero': '61300000', 'nom': "Locations (loyers)", 'type': 'charge', 'classe': '6'},
    {'numero': '61400000', 'nom': "Charges locatives (eau, électricité, gaz)", 'type': 'charge', 'classe': '6'},
    {'numero': '61500000', 'nom': "Entretien, réparations et maintenance", 'type': 'charge', 'classe': '6'},
    {'numero': '61600000', 'nom': "Primes d'assurances", 'type': 'charge', 'classe': '6'},
    {'numero': '61800000', 'nom': "Documentation, formation, colloques", 'type': 'charge', 'classe': '6'},
    {'numero': '62200000', 'nom': "Rémunérations d'intermédiaires et honoraires", 'type': 'charge', 'classe': '6'},
    {'numero': '62400000', 'nom': "Transport de personnel", 'type': 'charge', 'classe': '6'},
    {'numero': '62500000', 'nom': "Déplacements, missions et réceptions", 'type': 'charge', 'classe': '6'},
    {'numero': '62600000', 'nom': "Frais postaux et de télécommunications", 'type': 'charge', 'classe': '6'},
    {'numero': '62700000', 'nom': "Services bancaires et assimilés", 'type': 'charge', 'classe': '6'},
    {'numero': '62800000', 'nom': "Fournitures de bureau et charges diverses", 'type': 'charge', 'classe': '6'},
    {'numero': '63100000', 'nom': "Impôts et taxes directs", 'type': 'charge', 'classe': '6'},
    {'numero': '63500000', 'nom': "Autres impôts et taxes", 'type': 'charge', 'classe': '6'},
    {'numero': '66100000', 'nom': "Salaires et appointements du personnel", 'type': 'charge', 'classe': '6'},
    {'numero': '66300000', 'nom': "Indemnités et avantages divers au personnel", 'type': 'charge', 'classe': '6'},
    # ⭐ Charges sociales patronales (classe 666 SYSCOHADA), subdivisées par
    # organisme réel (privé/CNSS ou public/CRT, AMU-CNSS ou AMU-INAM) — la
    # classe 664 (rémunérations du personnel extérieur à l'entreprise) ne
    # convient pas ici, elle concerne le personnel intérimaire/prestataire.
    {'numero': '66610000', 'nom': "Charges sociales — CNSS part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '66620000', 'nom': "Charges sociales — CRT part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '66630000', 'nom': "Charges sociales — AMU-CNSS part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '66640000', 'nom': "Charges sociales — AMU-INAM part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '66650000', 'nom': "Charges sociales — Formation professionnelle", 'type': 'charge', 'classe': '6'},
    {'numero': '65100000', 'nom': "Pertes sur créances irrécouvrables", 'type': 'charge', 'classe': '6'},
    {'numero': '67100000', 'nom': "Intérêts et frais financiers", 'type': 'charge', 'classe': '6'},
    {'numero': '68100000', 'nom': "Dotations aux amortissements", 'type': 'charge', 'classe': '6'},
    {'numero': '65910000', 'nom': "Dotations aux provisions pour dépréciation des comptes clients", 'type': 'charge', 'classe': '6'},
    {'numero': '69100000', 'nom': "Rabais, remises et ristournes accordés", 'type': 'charge', 'classe': '6'},

    # ---------------- CLASSE 7 — Produits ----------------
    {'numero': '70110000', 'nom': "Ventes de pharmacie", 'type': 'produit', 'classe': '7'},
    {'numero': '70120000', 'nom': "Ventes de lunetterie / optique", 'type': 'produit', 'classe': '7'},
    {'numero': '70610000', 'nom': "Consultations", 'type': 'produit', 'classe': '7'},
    {'numero': '70620000', 'nom': "Actes de laboratoire", 'type': 'produit', 'classe': '7'},
    {'numero': '70630000', 'nom': "Imagerie médicale", 'type': 'produit', 'classe': '7'},
    {'numero': '70640000', 'nom': "Hospitalisation", 'type': 'produit', 'classe': '7'},
    {'numero': '70680000', 'nom': "Autres prestations médicales", 'type': 'produit', 'classe': '7'},
    {'numero': '75400000', 'nom': "Subventions et dons reçus", 'type': 'produit', 'classe': '7'},
    {'numero': '75800000', 'nom': "Produits divers", 'type': 'produit', 'classe': '7'},
    {'numero': '77100000', 'nom': "Intérêts et produits financiers", 'type': 'produit', 'classe': '7'},
    {'numero': '75910000', 'nom': "Reprises de provisions pour dépréciation des comptes clients", 'type': 'produit', 'classe': '7'},
]

# Index rapide numero -> définition, pour la création à la volée dans le service.
PLAN_COMPTABLE_PAR_NUMERO = {c['numero']: c for c in PLAN_COMPTABLE}

# Numéros de comptes de l'ancien plan ad-hoc (non-SYSCOHADA) à désactiver lors
# de la migration — jamais référencés par une ligne d'écriture puisque la
# génération automatique n'a jamais tourné en production. ⭐ Numéros courts
# (format historique de ces comptes en base, jamais migrés vers le format à
# 8 chiffres puisqu'ils sont désactivés, pas réutilisés).
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
COMPTES_TRESORERIE = ['52100000', '57100000']

# Préfixe des comptes de chiffre d'affaires ("Caisse Chiffre d'affaires")
PREFIXE_COMPTES_CA = '7'

# Compte clients "patients" par défaut (créances courantes)
COMPTE_CLIENTS_PATIENTS = '41110000'

# Compte d'attente pour écarts non résolus automatiquement
COMPTE_ATTENTE = '47130000'

# Compte fournisseurs par défaut (dettes courantes — achats à crédit).
# Un seul compte partagé pour tous les fournisseurs, comme COMPTE_CLIENTS_PATIENTS
# côté clients : le détail par fournisseur (qui doit quoi) est suivi au niveau
# applicatif (modèle Fournisseur/AchatFournisseur), pas par un sous-compte
# comptable dédié à chacun.
COMPTE_FOURNISSEURS = '40100000'

# Comptes de trésorerie par mode de paiement (caisse espèces / banque).
COMPTE_CAISSE = '57100000'
COMPTE_BANQUE = '52100000'

# Autres comptes référencés directement (ventes, provisions créances douteuses,
# amortissements, recettes/produits divers) — centralisés ici pour que plus
# aucun numéro de compte ne soit codé en dur ailleurs dans le code.
COMPTE_VENTES_PHARMACIE = '70110000'
COMPTE_VENTES_LUNETTERIE = '70120000'
COMPTE_CONSULTATIONS = '70610000'
COMPTE_LABORATOIRE = '70620000'
COMPTE_IMAGERIE = '70630000'
COMPTE_HOSPITALISATION = '70640000'
COMPTE_AUTRES_PRESTATIONS = '70680000'
COMPTE_PRODUITS_DIVERS = '75800000'
COMPTE_SALAIRES = '66100000'
COMPTE_DOTATION_PROVISION_CREANCE = '65910000'
COMPTE_DEPRECIATION_CREANCE = '49100000'
COMPTE_REPRISE_PROVISION_CREANCE = '75910000'
COMPTE_PERTE_CREANCE_IRRECOUVRABLE = '65100000'
COMPTE_CREANCE_ABANDONNEE = '69100000'
COMPTE_DOTATION_AMORTISSEMENT = '68100000'
COMPTE_IMMO_MATERIEL_MEDICAL = '21830000'   # repli par défaut pour une nouvelle immobilisation
COMPTE_AMORT_MATERIEL_MEDICAL = '28180000'  # repli par défaut pour son amortissement

# Correspondance assurance (telle qu'utilisée dans les ventes) -> numéro de
# compte de tiers-payant à recevoir.
COMPTE_PAR_ASSURANCE = {
    'amu-cnss': '41121100', 'amu_cnss': '41121100', 'cnss': '41121100',
    'amu-inam': '41121200', 'amu_inam': '41121200', 'inam': '41121200', 'amu': '41121200',
    'amu-tns': '41121300', 'amu_tns': '41121300', 'tns': '41121300',
    'gta': '41122100',
    'sunu': '41122200',
    'fidelia': '41122300',
    'nsia': '41122400',
    'gca': '41122500',
    'c2a': '41122600',
    'olea': '41122700',
}

# Compte générique de charge diverse, utilisé par défaut quand un motif de
# dépense n'est reconnu par aucun mot-clé de _COMPTE_PAR_MOTIF_DEPENSE.
COMPTE_CHARGE_DIVERSE = '62800000'

# Correspondance motif de dépense (mots-clés saisis librement dans l'UI) ->
# compte de charge. Reprend le même schéma de sous-comptes que le reste du
# plan (8 chiffres).
COMPTE_PAR_MOTIF_DEPENSE = {
    'salaire': '66100000', 'salaires': '66100000',
    'loyer': '61300000', 'location': '61300000',
    'eau': '61400000', 'electricite': '61400000', 'électricité': '61400000',
    'entretien': '61500000', 'reparation': '61500000', 'réparation': '61500000',
    'assurance': '61600000',
    'transport': '62400000',
    'carburant': '62400000',
    'communication': '62600000', 'telephone': '62600000', 'téléphone': '62600000', 'internet': '62600000',
    'banque': '62700000', 'frais bancaire': '62700000',
    'fourniture': '62800000', 'bureau': '62800000',
    'impot': '63100000', 'impôt': '63100000', 'taxe': '63100000',
    'medicament': '60100000', 'médicament': '60100000', 'pharmacie': '60100000',
    'materiel': '60400000', 'matériel': '60400000', 'equipement': '60400000', 'équipement': '60400000',
}


def compte_charge_pour_motif(motif):
    """Retourne le compte de charge (classe 6) correspondant à un motif de
    dépense saisi librement — repli sur la charge diverse si non reconnu."""
    if not motif:
        return COMPTE_CHARGE_DIVERSE
    cle = str(motif).strip().lower()
    for mot, compte in COMPTE_PAR_MOTIF_DEPENSE.items():
        if mot in cle:
            return compte
    return COMPTE_CHARGE_DIVERSE


# ============================================================
# COMPTES DE PAIE — retraite (CNSS/CRT) et AMU (AMU-CNSS/AMU-INAM)
# ============================================================
# ⭐ Adapté aux précisions du bulletin de paie (voir services/paie_service.py) :
# chaque organisme réel a ses propres comptes de tiers à reverser et sa
# propre charge patronale, pour ne jamais mélanger, par exemple, la CNSS
# d'un salarié du privé avec la CRT d'un salarié du public.
COMPTES_RETRAITE_PAR_ORGANISME = {
    'CNSS': {'salarial': '43110000', 'patronal': '43120000', 'charge': '66610000'},
    'CRT': {'salarial': '43130000', 'patronal': '43140000', 'charge': '66620000'},
}
COMPTES_AMU_PAR_ORGANISME = {
    'AMU-CNSS': {'salarial': '43150000', 'patronal': '43160000', 'charge': '66630000'},
    'AMU-INAM': {'salarial': '43170000', 'patronal': '43180000', 'charge': '66640000'},
}
COMPTE_FORMATION_PRO_CHARGE = '66650000'
COMPTE_FORMATION_PRO_A_REVERSER = '43190000'
COMPTE_IRPP_A_REVERSER = '44700000'
COMPTE_PERSONNEL_AVANCES = '42110000'   # prêts / acomptes / autres retenues sur salaire
COMPTE_PERSONNEL_A_PAYER = '42310000'   # net à payer — dette avant décaissement (journal SAL -> CAI/BQ)


def compte_assurance(nom_assurance):
    """Retourne le numéro de compte de tiers-payant pour une assurance donnée."""
    if not nom_assurance:
        return '41122800'
    cle = str(nom_assurance).lower().strip()
    if 'amu' in cle:
        if 'tns' in cle:
            return '41121300'
        if 'cnss' in cle:
            return '41121100'
        if 'inam' in cle:
            return '41121200'
        return '41121200'
    return COMPTE_PAR_ASSURANCE.get(cle, '41122800')
