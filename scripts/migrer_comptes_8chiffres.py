# scripts/migrer_comptes_8chiffres.py
# ============================================================
# Migration one-shot : harmonisation des numéros de compte à 8 chiffres
# (format SYSCOHADA détaillé demandé) + correction des noms mal étiquetés.
# ============================================================
# Chaque numéro court du plan comptable de référence (utils/plan_comptable_
# syscohada.py) est complété à droite par des zéros jusqu'à 8 chiffres
# (401 -> 40100000, 4111 -> 41110000, 411211 -> 41121100). Le premier
# chiffre (classe SYSCOHADA) ne change jamais, donc tout filtrage par
# préfixe déjà en place (numero.like('7%'), classe='2'...) continue de
# fonctionner sans adaptation.
#
# ⭐ Distinction essentielle : certains numéros courts existent À LA FOIS
# dans le plan SYSCOHADA actuel ET dans ANCIENS_COMPTES_A_DESACTIVER
# (l'ancien plan ad-hoc pré-SYSCOHADA), avec un sens complètement différent
# (ex: '611' = "Salaires" dans l'ancien plan vs "Transports sur achats/
# ventes" dans le plan SYSCOHADA actuel). Pour ces numéros ambigus, on
# vérifie le NOM actuellement stocké : s'il correspond au nom de référence
# SYSCOHADA, c'est un compte légitime (renumériser) ; sinon c'est l'ancien
# compte ad-hoc — on le DÉSACTIVE (actif=False) sans jamais toucher à son
# numéro ni son nom, pour ne jamais mélanger ou effacer son historique réel
# (des écritures existantes peuvent lui être rattachées).
#
# Idempotent : une fois renumérotés, les comptes SYSCOHADA ont un numéro à
# 8 chiffres qui ne matche plus aucune clé du MAPPING (toutes à ≤6 chiffres)
# — un second passage ne trouve donc plus rien à renumériser. Sûr à
# relancer sans risque (utilisé aussi pour synchroniser BIASA).
#
# Usage : python scripts/migrer_comptes_8chiffres.py
#   (charge DATABASE_URL depuis le .env du répertoire courant)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from utils.plan_comptable_syscohada import ANCIENS_COMPTES_A_DESACTIVER  # noqa: E402

# old_numero -> (new_numero, nom_reference)
MAPPING = {
    '101': ('10100000', "Capital social"),
    '120': ('12000000', "Résultat net de l'exercice (bénéfice)"),
    '129': ('12900000', "Résultat net de l'exercice (perte)"),
    '131': ('13100000', "Report à nouveau"),
    '2183': ('21830000', "Matériel médical et informatique"),
    '2184': ('21840000', "Mobilier et matériel de bureau"),
    '2818': ('28180000', "Amortissements du matériel médical et informatique"),
    '3751': ('37510000', "Stock de médicaments et produits pharmaceutiques"),
    '3752': ('37520000', "Stock de fournitures et consommables médicaux"),
    '3757': ('37570000', "Stock de montures et verres (optique)"),
    '401': ('40100000', "Fournisseurs"),
    '4011': ('40110000', "Fournisseurs — médicaments et consommables"),
    '4111': ('41110000', "Clients — patients (ventes courantes)"),
    '41171': ('41171000', "Clients douteux ou litigieux"),
    '491': ('49100000', "Dépréciation des comptes clients"),
    '411211': ('41121100', "AMU-CNSS — tiers-payant à recevoir"),
    '411212': ('41121200', "AMU-INAM — tiers-payant à recevoir"),
    '411221': ('41122100', "Assurance GTA — tiers-payant à recevoir"),
    '411222': ('41122200', "Assurance SUNU — tiers-payant à recevoir"),
    '411223': ('41122300', "Assurance FIDELIA — tiers-payant à recevoir"),
    '411224': ('41122400', "Assurance NSIA — tiers-payant à recevoir"),
    '411225': ('41122500', "Assurance GCA — tiers-payant à recevoir"),
    '411226': ('41122600', "Assurance C2A — tiers-payant à recevoir"),
    '411227': ('41122700', "Assurance OLEA — tiers-payant à recevoir"),
    '411228': ('41122800', "Autres assurances / tiers-payants à recevoir"),
    '4211': ('42110000', "Personnel — avances et acomptes"),
    '4231': ('42310000', "Personnel — rémunérations dues (net à payer)"),
    '4311': ('43110000', "CNSS — part salariale à reverser"),
    '4312': ('43120000', "CNSS — part patronale à reverser"),
    '4313': ('43130000', "CRT — part salariale à reverser"),
    '4314': ('43140000', "CRT — part patronale à reverser"),
    '4315': ('43150000', "AMU-CNSS — part salariale à reverser"),
    '4316': ('43160000', "AMU-CNSS — part patronale à reverser"),
    '4317': ('43170000', "AMU-INAM — part salariale à reverser"),
    '4318': ('43180000', "AMU-INAM — part patronale à reverser"),
    '4319': ('43190000', "Formation professionnelle — à reverser"),
    '447': ('44700000', "État — IRPP à reverser"),
    '4713': ('47130000', "Écarts et opérations d'attente (caisse)"),
    '521': ('52100000', "Banque"),
    '571': ('57100000', "Caisse espèces"),
    '601': ('60100000', "Achats de médicaments et produits pharmaceutiques"),
    '602': ('60200000', "Achats de fournitures et consommables médicaux"),
    '604': ('60400000', "Achats de matériel et petit équipement médical"),
    '605': ('60500000', "Achats de montures et verres (optique)"),
    '611': ('61100000', "Transports sur achats/ventes"),
    '613': ('61300000', "Locations (loyers)"),
    '614': ('61400000', "Charges locatives (eau, électricité, gaz)"),
    '615': ('61500000', "Entretien, réparations et maintenance"),
    '616': ('61600000', "Primes d'assurances"),
    '618': ('61800000', "Documentation, formation, colloques"),
    '622': ('62200000', "Rémunérations d'intermédiaires et honoraires"),
    '624': ('62400000', "Transport de personnel"),
    '625': ('62500000', "Déplacements, missions et réceptions"),
    '626': ('62600000', "Frais postaux et de télécommunications"),
    '627': ('62700000', "Services bancaires et assimilés"),
    '628': ('62800000', "Fournitures de bureau et charges diverses"),
    '631': ('63100000', "Impôts et taxes directs"),
    '635': ('63500000', "Autres impôts et taxes"),
    '661': ('66100000', "Salaires et appointements du personnel"),
    '663': ('66300000', "Indemnités et avantages divers au personnel"),
    '6661': ('66610000', "Charges sociales — CNSS part patronale"),
    '6662': ('66620000', "Charges sociales — CRT part patronale"),
    '6663': ('66630000', "Charges sociales — AMU-CNSS part patronale"),
    '6664': ('66640000', "Charges sociales — AMU-INAM part patronale"),
    '6665': ('66650000', "Charges sociales — Formation professionnelle"),
    '651': ('65100000', "Pertes sur créances irrécouvrables"),
    '671': ('67100000', "Intérêts et frais financiers"),
    '681': ('68100000', "Dotations aux amortissements"),
    '6591': ('65910000', "Dotations aux provisions pour dépréciation des comptes clients"),
    '691': ('69100000', "Rabais, remises et ristournes accordés"),
    '7011': ('70110000', "Ventes de pharmacie"),
    '7012': ('70120000', "Ventes de lunetterie / optique"),
    '7061': ('70610000', "Consultations"),
    '7062': ('70620000', "Actes de laboratoire"),
    '7063': ('70630000', "Imagerie médicale"),
    '7064': ('70640000', "Hospitalisation"),
    '7068': ('70680000', "Autres prestations médicales"),
    '754': ('75400000', "Subventions et dons reçus"),
    '758': ('75800000', "Produits divers"),
    '771': ('77100000', "Intérêts et produits financiers"),
    '7591': ('75910000', "Reprises de provisions pour dépréciation des comptes clients"),
}


def migrer():
    ambigus = set(ANCIENS_COMPTES_A_DESACTIVER) & set(MAPPING.keys())
    print("Numéros ambigus (ancien plan ad-hoc ET plan SYSCOHADA actuel) :", sorted(ambigus))

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    cur.execute("SELECT id, structure_id, numero, nom, actif FROM comptes_comptables ORDER BY id")
    rows = cur.fetchall()

    a_renumeroter, a_desactiver = [], []
    for cid, sid, numero, nom, actif in rows:
        if numero not in MAPPING:
            continue
        new_numero, nom_ref = MAPPING[numero]
        if numero in ambigus and nom.strip() != nom_ref.strip():
            if actif:
                a_desactiver.append((cid, sid, numero, nom))
        else:
            a_renumeroter.append((cid, sid, numero, new_numero, nom, nom_ref))

    print(f"{len(a_renumeroter)} compte(s) à renuméroter (8 chiffres) + corriger le nom si besoin")
    print(f"{len(a_desactiver)} compte(s) ad-hoc ambigus à désactiver (jamais renommés/renumérotés)")

    for cid, sid, old, new, nom, nom_ref in a_renumeroter:
        cur.execute("UPDATE comptes_comptables SET numero=%s, nom=%s WHERE id=%s", (new, nom_ref, cid))
    for cid, sid, old, nom in a_desactiver:
        cur.execute("UPDATE comptes_comptables SET actif=FALSE WHERE id=%s", (cid,))

    conn.commit()
    print("Migration appliquée et validée (commit).")

    cur.execute("SELECT COUNT(*) FROM lignes_ecritures l LEFT JOIN comptes_comptables c ON c.id = l.compte_id WHERE c.id IS NULL")
    print("Lignes d'écriture orphelines (doit être 0) :", cur.fetchone()[0])

    cur.close()
    conn.close()


if __name__ == '__main__':
    migrer()
