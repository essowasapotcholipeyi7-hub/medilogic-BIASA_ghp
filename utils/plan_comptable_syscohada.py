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
    # ⭐⭐ Revu compte par compte sur le plan SYSCOHADA RÉVISÉ (patron, 2026-10-11 :
    # « je t'avais demandé de bien regarder et mettre à jour selon SYSCOHADA ») —
    # plusieurs numéros venaient jusqu'ici du plan comptable FRANÇAIS (PCG) :
    # résultat en 12, loyers en 613, assurances en 616, télécom en 626, frais
    # bancaires en 627, impôts en 631, charges sociales en 666, RRR en 691,
    # stocks en 37... Correspondance ancien -> nouveau : RENUMEROTATION_SYSCOHADA
    # ci-dessous (appliquée aux bases par scripts/migrer_syscohada_revise.py).

    # ---------------- CLASSE 1 — Ressources durables ----------------
    {'numero': '10100000', 'nom': "Capital social", 'type': 'passif', 'classe': '1'},
    {'numero': '12100000', 'nom': "Report à nouveau créditeur", 'type': 'passif', 'classe': '1'},
    {'numero': '12900000', 'nom': "Report à nouveau débiteur", 'type': 'actif', 'classe': '1'},
    {'numero': '13100000', 'nom': "Résultat net de l'exercice : bénéfice", 'type': 'passif', 'classe': '1'},
    {'numero': '13900000', 'nom': "Résultat net de l'exercice : perte", 'type': 'actif', 'classe': '1'},

    # ---------------- CLASSE 2 — Actif immobilisé ----------------
    {'numero': '24100000', 'nom': "Matériel et outillage médical", 'type': 'actif', 'classe': '2'},
    {'numero': '24420000', 'nom': "Matériel informatique", 'type': 'actif', 'classe': '2'},
    {'numero': '24440000', 'nom': "Mobilier de bureau", 'type': 'actif', 'classe': '2'},
    {'numero': '28410000', 'nom': "Amortissements du matériel et outillage", 'type': 'actif', 'classe': '2'},
    {'numero': '28440000', 'nom': "Amortissements du matériel informatique et du mobilier de bureau", 'type': 'actif', 'classe': '2'},

    # ---------------- CLASSE 3 — Stocks ----------------
    {'numero': '31100000', 'nom': "Marchandises — médicaments et produits pharmaceutiques", 'type': 'actif', 'classe': '3'},
    {'numero': '31200000', 'nom': "Marchandises — montures et verres (optique)", 'type': 'actif', 'classe': '3'},
    {'numero': '33100000', 'nom': "Matières consommables — fournitures médicales", 'type': 'actif', 'classe': '3'},

    # ---------------- CLASSE 4 — Tiers ----------------
    {'numero': '40100000', 'nom': "Fournisseurs", 'type': 'passif', 'classe': '4'},
    {'numero': '40110000', 'nom': "Fournisseurs — médicaments et consommables", 'type': 'passif', 'classe': '4'},
    {'numero': '41110000', 'nom': "Clients — patients (ventes courantes)", 'type': 'actif', 'classe': '4'},
    {'numero': '41600000', 'nom': "Créances clients litigieuses ou douteuses", 'type': 'actif', 'classe': '4'},
    {'numero': '49100000', 'nom': "Dépréciation des comptes clients", 'type': 'actif', 'classe': '4'},
    {'numero': '41121100', 'nom': "AMU-CNSS — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41121200', 'nom': "AMU-INAM — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    # ⭐ AMU-TNS (Travailleurs Non-Salariés) — administrée par la CNSS mais
    # panier de soins distinct de l'AMU-CNSS classique : compte tiers-payant séparé.
    {'numero': '41121300', 'nom': "AMU-TNS — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122100', 'nom': "Assurance GTA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122200', 'nom': "Assurance SUNU — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122300', 'nom': "Assurance FIDELIA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122400', 'nom': "Assurance NSIA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122500', 'nom': "Assurance GCA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122600', 'nom': "Assurance C2A — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122700', 'nom': "Assurance OLEA — tiers-payant à recevoir", 'type': 'actif', 'classe': '4'},
    {'numero': '41122800', 'nom': "Autres assurances / tiers-payants à recevoir", 'type': 'actif', 'classe': '4'},
    # Personnel (421 avances et acomptes, 422 rémunérations dues)
    {'numero': '42110000', 'nom': "Personnel — avances et acomptes", 'type': 'actif', 'classe': '4'},
    {'numero': '42210000', 'nom': "Personnel — rémunérations dues (net à payer)", 'type': 'passif', 'classe': '4'},
    # Organismes sociaux (431 sécurité sociale, 432 caisses de retraite, 433 autres organismes)
    {'numero': '43110000', 'nom': "CNSS — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43120000', 'nom': "CNSS — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43150000', 'nom': "AMU-CNSS — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43160000', 'nom': "AMU-CNSS — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43190000', 'nom': "Formation professionnelle — à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43210000', 'nom': "CRT (caisse de retraite) — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43220000', 'nom': "CRT (caisse de retraite) — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43310000', 'nom': "AMU-INAM — part salariale à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '43320000', 'nom': "AMU-INAM — part patronale à reverser", 'type': 'passif', 'classe': '4'},
    # État (443 TVA facturée, 445 TVA récupérable, 447 impôts retenus à la source)
    {'numero': '44310000', 'nom': "État — TVA facturée sur ventes", 'type': 'passif', 'classe': '4'},
    {'numero': '44410000', 'nom': "État — TVA due (déclarée, à payer)", 'type': 'passif', 'classe': '4'},
    {'numero': '44490000', 'nom': "État — crédit de TVA à reporter", 'type': 'actif', 'classe': '4'},
    {'numero': '44520000', 'nom': "État — TVA récupérable sur achats", 'type': 'actif', 'classe': '4'},
    {'numero': '44710000', 'nom': "État — RSPS retenue sur parts médecins, à reverser (OTR)", 'type': 'passif', 'classe': '4'},
    {'numero': '44720000', 'nom': "État — impôts sur salaires (IRPP) à reverser", 'type': 'passif', 'classe': '4'},
    {'numero': '47130000', 'nom': "Écarts et opérations d'attente (caisse)", 'type': 'actif', 'classe': '4'},

    # ---------------- CLASSE 5 — Trésorerie ----------------
    {'numero': '52100000', 'nom': "Banque", 'type': 'actif', 'classe': '5'},
    {'numero': '57100000', 'nom': "Caisse espèces", 'type': 'actif', 'classe': '5'},

    # ---------------- CLASSE 6 — Charges des activités ordinaires ----------------
    # 60 Achats
    {'numero': '60100000', 'nom': "Achats de marchandises — médicaments et produits pharmaceutiques", 'type': 'charge', 'classe': '6'},
    {'numero': '60105000', 'nom': "Achats de marchandises — montures et verres (optique)", 'type': 'charge', 'classe': '6'},
    {'numero': '60410000', 'nom': "Achats stockés de matières et fournitures consommables médicales", 'type': 'charge', 'classe': '6'},
    {'numero': '60500000', 'nom': "Autres achats — eau, électricité, énergie", 'type': 'charge', 'classe': '6'},
    {'numero': '60530000', 'nom': "Autres achats — carburant et autres énergies", 'type': 'charge', 'classe': '6'},
    {'numero': '60550000', 'nom': "Fournitures de bureau non stockables", 'type': 'charge', 'classe': '6'},
    {'numero': '60560000', 'nom': "Achats de petit matériel et outillage", 'type': 'charge', 'classe': '6'},
    # 61 Transports
    {'numero': '61200000', 'nom': "Transports sur ventes", 'type': 'charge', 'classe': '6'},
    {'numero': '61800000', 'nom': "Autres frais de transport — voyages, déplacements et missions", 'type': 'charge', 'classe': '6'},
    # 62 Services extérieurs
    {'numero': '62200000', 'nom': "Locations et charges locatives (loyers)", 'type': 'charge', 'classe': '6'},
    {'numero': '62400000', 'nom': "Entretien, réparations et maintenance", 'type': 'charge', 'classe': '6'},
    {'numero': '62500000', 'nom': "Primes d'assurance", 'type': 'charge', 'classe': '6'},
    {'numero': '62600000', 'nom': "Études, recherches et documentation", 'type': 'charge', 'classe': '6'},
    {'numero': '62800000', 'nom': "Frais de télécommunications (téléphone, internet)", 'type': 'charge', 'classe': '6'},
    # 63 Autres services extérieurs
    {'numero': '63100000', 'nom': "Frais bancaires", 'type': 'charge', 'classe': '6'},
    {'numero': '63200000', 'nom': "Rémunérations d'intermédiaires et de conseils", 'type': 'charge', 'classe': '6'},
    {'numero': '63220000', 'nom': "Commissions et courtages (ristournes aux prescripteurs)", 'type': 'charge', 'classe': '6'},
    {'numero': '63240000', 'nom': "Honoraires — part des médecins réalisateurs", 'type': 'charge', 'classe': '6'},
    {'numero': '63300000', 'nom': "Frais de formation du personnel", 'type': 'charge', 'classe': '6'},
    {'numero': '63400000', 'nom': "Redevances pour logiciels (abonnement SSoftOneV10)", 'type': 'charge', 'classe': '6'},
    # 64 Impôts et taxes
    {'numero': '64100000', 'nom': "Impôts et taxes directs", 'type': 'charge', 'classe': '6'},
    {'numero': '64150000', 'nom': "Formation professionnelle continue (taxe)", 'type': 'charge', 'classe': '6'},
    {'numero': '64800000', 'nom': "Autres impôts et taxes", 'type': 'charge', 'classe': '6'},
    # 65 Autres charges
    {'numero': '65100000', 'nom': "Pertes sur créances clients irrécouvrables", 'type': 'charge', 'classe': '6'},
    {'numero': '65800000', 'nom': "Charges diverses", 'type': 'charge', 'classe': '6'},
    {'numero': '65910000', 'nom': "Dotations aux provisions pour dépréciation des comptes clients", 'type': 'charge', 'classe': '6'},
    # 66 Charges de personnel (661 rémunérations, 663 indemnités, 664 charges sociales)
    {'numero': '66100000', 'nom': "Rémunérations directes versées au personnel (salaires)", 'type': 'charge', 'classe': '6'},
    {'numero': '66300000', 'nom': "Indemnités forfaitaires versées au personnel", 'type': 'charge', 'classe': '6'},
    {'numero': '66411000', 'nom': "Charges sociales — CNSS part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '66412000', 'nom': "Charges sociales — CRT part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '66413000', 'nom': "Charges sociales — AMU-CNSS part patronale", 'type': 'charge', 'classe': '6'},
    {'numero': '66414000', 'nom': "Charges sociales — AMU-INAM part patronale", 'type': 'charge', 'classe': '6'},
    # 67 Frais financiers, 68 Dotations
    {'numero': '67100000', 'nom': "Intérêts des emprunts et frais financiers", 'type': 'charge', 'classe': '6'},
    {'numero': '68100000', 'nom': "Dotations aux amortissements d'exploitation", 'type': 'charge', 'classe': '6'},

    # ---------------- CLASSE 7 — Produits des activités ordinaires ----------------
    {'numero': '70110000', 'nom': "Ventes de marchandises — pharmacie", 'type': 'produit', 'classe': '7'},
    {'numero': '70120000', 'nom': "Ventes de marchandises — lunetterie / optique", 'type': 'produit', 'classe': '7'},
    {'numero': '70610000', 'nom': "Services vendus — consultations", 'type': 'produit', 'classe': '7'},
    {'numero': '70620000', 'nom': "Services vendus — actes de laboratoire", 'type': 'produit', 'classe': '7'},
    {'numero': '70630000', 'nom': "Services vendus — imagerie médicale", 'type': 'produit', 'classe': '7'},
    {'numero': '70640000', 'nom': "Services vendus — hospitalisation", 'type': 'produit', 'classe': '7'},
    {'numero': '70680000', 'nom': "Services vendus — autres prestations médicales", 'type': 'produit', 'classe': '7'},
    # 709 : en diminution des ventes (solde débiteur), comme dans le plan SYSCOHADA
    {'numero': '70900000', 'nom': "Rabais, remises et ristournes accordés", 'type': 'produit', 'classe': '7'},
    {'numero': '71800000', 'nom': "Autres subventions d'exploitation (dons reçus)", 'type': 'produit', 'classe': '7'},
    {'numero': '75800000', 'nom': "Produits divers", 'type': 'produit', 'classe': '7'},
    {'numero': '75910000', 'nom': "Reprises de provisions pour dépréciation des comptes clients", 'type': 'produit', 'classe': '7'},
    {'numero': '77100000', 'nom': "Intérêts et produits financiers", 'type': 'produit', 'classe': '7'},
]

# ⭐ Correspondance ancien numéro (plan d'avant le 2026-10-11, en partie
# PCG français) -> numéro SYSCOHADA révisé. Les comptes sont RENUMÉROTÉS
# sur place (leurs écritures les suivent, aucune perte d'historique) ; deux
# anciens comptes vers le même numéro sont fusionnés. Voir
# scripts/migrer_syscohada_revise.py.
RENUMEROTATION_SYSCOHADA = {
    '12000000': '13100000', '12900000': '13900000', '13100000': '12100000',
    '21830000': '24100000', '21840000': '24440000', '28180000': '28410000',
    '37510000': '31100000', '37520000': '33100000', '37570000': '31200000',
    '41171000': '41600000', '42310000': '42210000',
    '43130000': '43210000', '43140000': '43220000', '43170000': '43310000', '43180000': '43320000',
    '44700000': '44720000',
    '60200000': '60410000', '60400000': '60560000', '60500000': '60105000',
    '61100000': '61200000', '61300000': '62200000', '61400000': '60500000', '61500000': '62400000',
    '61600000': '62500000', '61800000': '62600000',
    '62200000': '63200000', '62400000': '61800000', '62500000': '61800000', '62600000': '62800000',
    '62700000': '63100000', '62800000': '65800000',
    '63100000': '64100000', '63500000': '64800000',
    '66610000': '66411000', '66620000': '66412000', '66630000': '66413000', '66640000': '66414000',
    '66650000': '64150000',
    '69100000': '70900000', '75400000': '71800000',
}

# ⭐ Charges mal classées par l'ancien rapprochement motif -> compte (la plupart
# atterrissaient dans l'ancien 628 « charges diverses ») : reclassées par une
# écriture d'OD (jamais en réécrivant l'écriture d'origine). motif de la
# dépense -> compte SYSCOHADA. Voir scripts/migrer_syscohada_revise.py.
RECLASSEMENT_CHARGES_PAR_MOTIF = {
    'abonnement_ssoftonev10': '63400000',
    'fourniture': '60410000',
    'part médecin': '63240000',
}

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

# Résultat net de l'exercice — voir generer_cloture_exercice()
# (comptabilite_service.py) : bénéfice (crédité) si les produits (classe 7)
# dépassent les charges (classe 6) sur la période, perte (débitée) sinon.
COMPTE_RESULTAT_BENEFICE = '13100000'
COMPTE_RESULTAT_PERTE = '13900000'
COMPTE_REPORT_A_NOUVEAU_CREDITEUR = '12100000'
COMPTE_REPORT_A_NOUVEAU_DEBITEUR = '12900000'

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
# ⭐ TVA collectée (ventes) et déductible (achats fournisseurs) — voir
# models.ParametrageTva (taux/assujettissement, configurable par
# structure), generer_ecriture_vente() et generer_ecriture_achat_fournisseur()
# pour le calcul HT/TVA. Les prix de vente de l'appli sont TTC (montant
# toujours normalisé côté vente) ; côté achat, l'utilisateur choisit à la
# saisie si le montant qu'il entre est TTC ou HT (AchatFournisseur.
# type_montant_saisi) — converti en TTC avant stockage dans montant_total,
# qui reste dans tous les cas le vrai montant dû au fournisseur.
COMPTE_TVA_COLLECTEE = '44310000'
COMPTE_TVA_DEDUCTIBLE = '44520000'
COMPTE_TVA_DUE = '44410000'       # TVA déclarée (clôture de la période), en attente de paiement
COMPTE_CREDIT_TVA = '44490000'    # crédit de TVA reporté sur la déclaration suivante
COMPTES_TVA = (COMPTE_TVA_COLLECTEE, COMPTE_TVA_DEDUCTIBLE, COMPTE_TVA_DUE, COMPTE_CREDIT_TVA)
COMPTE_SALAIRES = '66100000'
COMPTE_DOTATION_PROVISION_CREANCE = '65910000'
COMPTE_DEPRECIATION_CREANCE = '49100000'
COMPTE_REPRISE_PROVISION_CREANCE = '75910000'
COMPTE_PERTE_CREANCE_IRRECOUVRABLE = '65100000'
COMPTE_CREANCE_ABANDONNEE = '70900000'   # geste commercial : RRR accordé (709, en diminution des ventes)
COMPTE_DOTATION_AMORTISSEMENT = '68100000'
COMPTE_IMMO_MATERIEL_MEDICAL = '24100000'   # repli par défaut pour une nouvelle immobilisation
COMPTE_AMORT_MATERIEL_MEDICAL = '28410000'  # repli par défaut pour son amortissement
# compte d'amortissement associé à chaque compte d'immobilisation (formulaire)
AMORTISSEMENT_PAR_IMMOBILISATION = {'24100000': '28410000', '24420000': '28440000', '24440000': '28440000'}

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
COMPTE_CHARGE_DIVERSE = '65800000'

# Correspondance motif de dépense (mots-clés saisis librement dans l'UI) ->
# compte de charge. Reprend le même schéma de sous-comptes que le reste du
# plan (8 chiffres).
COMPTE_PAR_MOTIF_DEPENSE = {
    # ⭐ en tête : « part médecin » doit l'emporter sur toute autre sous-chaîne
    'part médecin': '63240000', 'part medecin': '63240000', 'honoraire': '63240000',
    'abonnement': '63400000', 'ssoftone': '63400000', 'logiciel': '63400000',
    'salaire': '66100000', 'salaires': '66100000',
    'loyer': '62200000', 'location': '62200000',
    'eau': '60500000', 'electricite': '60500000', 'électricité': '60500000',
    'entretien': '62400000', 'reparation': '62400000', 'réparation': '62400000', 'maintenance': '62400000',
    'assurance': '62500000',
    'carburant': '60530000',
    'transport': '61800000', 'deplacement': '61800000', 'déplacement': '61800000', 'mission': '61800000',
    'communication': '62800000', 'telephone': '62800000', 'téléphone': '62800000', 'internet': '62800000',
    'banque': '63100000', 'frais bancaire': '63100000',
    'formation': '63300000', 'documentation': '62600000',
    'bureau': '60550000', 'papeterie': '60550000',
    'fourniture': '60410000',            # « Fourniture médicale » (formulaire des charges)
    'impot': '64100000', 'impôt': '64100000', 'taxe': '64100000',
    'medicament': '60100000', 'médicament': '60100000', 'pharmacie': '60100000',
    'materiel': '60560000', 'matériel': '60560000', 'equipement': '60560000', 'équipement': '60560000',
    'ristourne': '63220000', 'commission': '63220000',
}


def compte_charge_pour_motif(motif):
    """Retourne le compte de charge (classe 6) correspondant à un motif de
    dépense saisi librement — repli sur la charge diverse si non reconnu."""
    if not motif:
        return COMPTE_CHARGE_DIVERSE
    import re
    cle = str(motif).strip().lower()
    for mot, compte in COMPTE_PAR_MOTIF_DEPENSE.items():
        # ⭐ mot ENTIER (pluriel accepté) : avant, « eau » était trouvé dans
        # « bureau » / « réseau » et envoyait des fournitures en eau-électricité.
        if re.search(r'(?<![0-9a-zà-ÿ])' + re.escape(mot) + r'(?:s|x)?(?![0-9a-zà-ÿ])', cle):
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
    'CNSS': {'salarial': '43110000', 'patronal': '43120000', 'charge': '66411000'},
    'CRT': {'salarial': '43210000', 'patronal': '43220000', 'charge': '66412000'},
}
COMPTES_AMU_PAR_ORGANISME = {
    'AMU-CNSS': {'salarial': '43150000', 'patronal': '43160000', 'charge': '66413000'},
    'AMU-INAM': {'salarial': '43310000', 'patronal': '43320000', 'charge': '66414000'},
}
COMPTE_FORMATION_PRO_CHARGE = '64150000'
COMPTE_FORMATION_PRO_A_REVERSER = '43190000'
COMPTE_IRPP_A_REVERSER = '44720000'
COMPTE_RSPS_A_REVERSER = '44710000'   # ⭐ RSPS 5 % retenue sur la part des médecins (OTR)
COMPTE_HONORAIRES_MEDECINS = '63240000'
COMPTE_PERSONNEL_AVANCES = '42110000'   # prêts / acomptes / autres retenues sur salaire
COMPTE_PERSONNEL_A_PAYER = '42210000'   # net à payer — dette avant décaissement (journal SAL -> CAI/BQ)


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
    if cle in COMPTE_PAR_ASSURANCE:
        return COMPTE_PAR_ASSURANCE[cle]
    # ⭐ Compagnie non répertoriée dans COMPTE_PAR_ASSURANCE (patron,
    # 2026-10-01, porté depuis GHP : "je te conseille de faire en sorte
    # que chaque assurance ait son compte même celles qu'on n'a pas encore
    # créées / dès qu'il y a une nouvelle assurance qui s'ajoute, que son
    # compte se crée en même temps") — au lieu de les mélanger toutes dans
    # le même compte fourre-tout 41122800, chaque compagnie reçoit
    # désormais son propre compte, généré à la volée dès sa première
    # utilisation. Le compte lui-même n'est créé qu'au moment de
    # l'écriture (comptabilite_service._get_compte_id, qui a accès à la
    # base) — cette fonction ne fait que calculer un numéro stable, jamais
    # d'accès DB ici. Même principe CRC32 déjà en place pour le tiers_id
    # (_tiers_id_assurance, comptabilite_service.py). Plage 411239xx —
    # juste après les 8 comptes nommés manuellement (41122100-41122700)
    # et le compte générique (41122800).
    return numero_compte_assurance_dynamique(cle)


def numero_compte_assurance_dynamique(nom_normalise):
    import zlib
    return f"41123{zlib.crc32(nom_normalise.encode('utf-8')) % 1000:03d}"


def nom_compte_assurance(nom_assurance):
    """Libellé à donner au compte généré pour une compagnie sans compte
    dédié préexistant — utilisé par comptabilite_service.generer_ecriture_
    vente comme repli de _get_compte_id() quand compte_assurance() a
    renvoyé un numéro absent de PLAN_COMPTABLE_PAR_NUMERO (donc pas encore
    créé pour cette structure)."""
    return f"Assurance {str(nom_assurance).strip().upper()} — tiers-payant à recevoir"


def journal_pour_comptes(numeros):
    """⭐ Journal où ranger une écriture d'après ses comptes (patron, 2026-10-11 :
    « que le journal s'adapte automatiquement »). Une écriture appartient à UN
    seul journal ; une opération qui en concerne deux (ex. vente à crédit puis
    encaissement) se passe en deux écritures liées par la même pièce.
    Priorité : banque > caisse > paie > achats > ventes > opérations diverses."""
    nums = [str(n) for n in numeros if n]

    def a(*prefixes):
        return any(n.startswith(prefixes) for n in nums)

    if a('52', '53', '55'):
        return 'BQU'
    if a('57'):
        return 'CAI'
    if a('66', '42', '43'):
        return 'SAL'
    if a('40') and a('6', '2', '445'):
        return 'ACH'
    if a('70', '71', '75') and a('41'):
        return 'VTE'
    return 'OD'

def liquidation_tva(collectee, deductible, credit_anterieur=0):
    """⭐ Clôture (liquidation) de la TVA d'une période (patron, 2026-10-11 :
    « il doit y avoir un moment où on clôture la TVA du mois, et c'est à ce
    moment que la caisse est déduite »). La TVA n'est pas sortie de la caisse
    à chaque vente : elle s'accumule en 443 (collectée) et 445 (récupérable).
    À la clôture, ces soldes sont soldés :
        Débit 443 collectée / Crédit 445 récupérable / Crédit 4449 crédit antérieur
        et la différence en Crédit 4441 (TVA due) — ou en Débit 4449 si l'État
        nous doit (crédit reporté sur la période suivante).
    Le paiement (Débit 4441 / Crédit caisse ou banque) est une étape à part.
    Retourne (lignes, tva_a_payer, credit_reporte) ; lignes vides = déclaration néant."""
    collectee, deductible, credit_anterieur = (round(float(x or 0), 2) for x in (collectee, deductible, credit_anterieur))
    lignes = []

    def ligne(numero, libelle, montant, sens):
        if abs(montant) > 0.005:
            debit = montant if (sens == 'debit') == (montant > 0) else 0
            lignes.append({'numero_compte': numero, 'libelle': libelle,
                           'debit': abs(montant) if debit else 0, 'credit': 0 if debit else abs(montant)})

    ligne(COMPTE_TVA_COLLECTEE, "TVA collectée sur la période", collectee, 'debit')
    ligne(COMPTE_TVA_DEDUCTIBLE, "TVA récupérable sur la période", deductible, 'credit')
    ligne(COMPTE_CREDIT_TVA, "Crédit de TVA antérieur imputé", credit_anterieur, 'credit')
    net = round(collectee - deductible - credit_anterieur, 2)
    if net > 0:
        ligne(COMPTE_TVA_DUE, "TVA due à l'État", net, 'credit')
    elif net < 0:
        ligne(COMPTE_CREDIT_TVA, "Crédit de TVA à reporter", -net, 'debit')
    return lignes, max(net, 0), max(-net, 0)
