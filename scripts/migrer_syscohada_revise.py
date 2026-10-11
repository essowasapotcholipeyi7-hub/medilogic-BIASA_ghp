# scripts/migrer_syscohada_revise.py
# ============================================================
# ⭐ Mise en conformité SYSCOHADA RÉVISÉ (patron, 2026-10-11 : « je t'avais
# demandé de bien regarder et mettre à jour selon SYSCOHADA » — plusieurs
# numéros venaient du plan comptable français). Pour CHAQUE structure :
#
# 1. Renumérotation sur place des comptes (utils/plan_comptable_syscohada.
#    RENUMEROTATION_SYSCOHADA) : les écritures suivent leur compte (aucune
#    ligne réécrite, aucun historique perdu). Les numéros sont d'abord libérés
#    (numéro provisoire) pour permettre les permutations (ex. 622 honoraires ->
#    632 et 613 loyers -> 622). Deux anciens comptes vers le même numéro sont
#    fusionnés (lignes, budget, relevés bancaires rattachés au compte gardé ;
#    l'autre est désactivé sous le numéro « ANC-… »).
# 2. Libellés des comptes standard alignés sur le plan.
# 3. Immobilisations : numéros de compte (2183/2818…) mis à jour.
# 4. Charges mal classées par l'ancien rapprochement motif -> compte
#    (RECLASSEMENT_CHARGES_PAR_MOTIF) : une écriture d'OD par structure
#    (Débit bon compte / Crédit 658), jamais de réécriture des écritures d'origine.
#
# Idempotent : un 2e passage ne retrouve plus aucun ancien numéro (et ne
# recrée pas l'OD déjà passée) — à relancer après la mise en ligne pour
# rattraper un compte créé entre-temps par l'ancien code.
#
# Usage (depuis la racine du projet) :
#     python scripts/migrer_syscohada_revise.py --simuler   # montre tout, n'enregistre rien
#     python scripts/migrer_syscohada_revise.py
# ============================================================
import io
import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import app  # noqa: E402
from models import db  # noqa: E402
from utils.plan_comptable_syscohada import (  # noqa: E402
    PLAN_COMPTABLE_PAR_NUMERO, RENUMEROTATION_SYSCOHADA, RECLASSEMENT_CHARGES_PAR_MOTIF,
    COMPTE_CHARGE_DIVERSE,
)

SIMULER = '--simuler' in sys.argv
SOURCE_OD = 'reclassement_syscohada'


def q(sql, **p):
    return db.session.execute(db.text(sql), p)


def migrer_structure(sid):
    rapport = []
    comptes = {r.numero: r for r in q("SELECT id, numero, nom FROM comptes_comptables WHERE structure_id = :s", s=sid)}
    mouvants = [(ancien, nouveau, comptes[ancien].id) for ancien, nouveau in sorted(RENUMEROTATION_SYSCOHADA.items())
                if ancien in comptes]
    # 1a. libérer les numéros (permutations possibles)
    for ancien, _, cid in mouvants:
        q("UPDATE comptes_comptables SET numero = :n WHERE id = :i", n=f"TMP-{ancien}", i=cid)
    occupes = {num: r.id for num, r in comptes.items() if num not in RENUMEROTATION_SYSCOHADA}
    # 1b. numéros définitifs ou fusion
    for ancien, nouveau, cid in mouvants:
        d = PLAN_COMPTABLE_PAR_NUMERO[nouveau]
        nb = q("SELECT COUNT(*) FROM lignes_ecritures WHERE compte_id = :i", i=cid).scalar()
        if nouveau in occupes:
            garde = occupes[nouveau]
            for table, colonne in (('lignes_ecritures', 'compte_id'), ('budget', 'compte_id'),
                                   ('releves_bancaires', 'compte_id'), ('comptes_comptables', 'parent_id')):
                q(f"UPDATE {table} SET {colonne} = :g WHERE {colonne} = :i", g=garde, i=cid)
            q("UPDATE comptes_comptables SET numero = :n, actif = FALSE, nom = :nom WHERE id = :i",
              n=f"ANC-{ancien}", nom=f"{comptes[ancien].nom} (fusionné dans {nouveau})"[:200], i=cid)
            rapport.append(f"  {ancien} -> {nouveau} fusionné ({nb} ligne(s)) : {d['nom']}")
        else:
            q("UPDATE comptes_comptables SET numero = :n, nom = :nom, type = :t, classe = :c, actif = TRUE WHERE id = :i",
              n=nouveau, nom=d['nom'], t=d['type'], c=d['classe'], i=cid)
            occupes[nouveau] = cid
            rapport.append(f"  {ancien} -> {nouveau} ({nb} ligne(s)) : {d['nom']}")
    # 2. libellés standard
    for num, cid in occupes.items():
        d = PLAN_COMPTABLE_PAR_NUMERO.get(num)
        if d:
            r = q("UPDATE comptes_comptables SET nom = :nom, type = :t, classe = :c WHERE id = :i AND (nom <> :nom OR type IS DISTINCT FROM :t OR classe IS DISTINCT FROM :c)",
                  nom=d['nom'], t=d['type'], c=d['classe'], i=cid)
            if r.rowcount:
                rapport.append(f"  libellé {num} : {d['nom']}")
    # 3. immobilisations
    for ancien, nouveau in RENUMEROTATION_SYSCOHADA.items():
        for col in ('compte_immo_numero', 'compte_amort_numero'):
            r = q(f"UPDATE immobilisations SET {col} = :n WHERE structure_id = :s AND {col} IN (:a, :court)",
                  n=nouveau, s=sid, a=ancien, court=ancien.rstrip('0'))
            if r.rowcount:
                rapport.append(f"  immobilisations : {col} {ancien} -> {nouveau} ({r.rowcount})")
    return rapport


def reclasser_charges(sid):
    """OD : charges d'origine « dépense » restées en 658 alors que leur motif a un compte dédié."""
    if q("SELECT 1 FROM ecritures_comptables WHERE structure_id = :s AND source_type = :t LIMIT 1", s=sid, t=SOURCE_OD).first():
        return []
    lignes = q("""
        SELECT d.motif, SUM(l.debit - l.credit) AS montant
        FROM lignes_ecritures l
        JOIN comptes_comptables c ON c.id = l.compte_id
        JOIN ecritures_comptables e ON e.id = l.ecriture_id
        JOIN depenses d ON d.id = e.source_id AND e.source_type = 'depense'
        WHERE e.structure_id = :s AND c.numero = :n AND e.statut = 'valide'
        GROUP BY d.motif
    """, s=sid, n=COMPTE_CHARGE_DIVERSE).fetchall()
    par_compte = defaultdict(float)
    for motif, montant in lignes:
        cle = (motif or '').strip().lower()
        cible = next((c for m, c in RECLASSEMENT_CHARGES_PAR_MOTIF.items() if cle == m or cle.startswith(m)), None)
        if cible and float(montant or 0) > 0:
            par_compte[cible] += float(montant)
    if not par_compte:
        return []
    from services.comptabilite_service import creer_ecriture
    ecriture_lignes = []
    for cible, montant in sorted(par_compte.items()):
        nom = PLAN_COMPTABLE_PAR_NUMERO[cible]['nom']
        ecriture_lignes.append({'numero_compte': cible, 'libelle': f"Reclassement SYSCOHADA — {nom}", 'debit': round(montant, 2)})
        ecriture_lignes.append({'numero_compte': COMPTE_CHARGE_DIVERSE, 'libelle': f"Reclassement SYSCOHADA — {nom}", 'credit': round(montant, 2)})
    ecriture = creer_ecriture(
        structure_id=sid, date_ecriture=date.today(),
        libelle="Reclassement SYSCOHADA des charges mal classées (ancien compte charges diverses)",
        lignes=ecriture_lignes, journal_code='OD', piece_justificative='RECLASS-SYSCOHADA',
        auto=True, source_type=SOURCE_OD, source_id=None,
        commentaire="Mise en conformité du plan comptable SYSCOHADA révisé (2026-10-11)",
        user_nom='Mise en conformité SYSCOHADA',
    )
    return [f"  OD n°{getattr(ecriture, 'id', '?')} : " + ', '.join(f"{c} {int(m):,} FCFA".replace(',', ' ') for c, m in sorted(par_compte.items()))]


with app.app_context():
    structures = [r[0] for r in q("SELECT DISTINCT structure_id FROM comptes_comptables ORDER BY structure_id")]
    print(('SIMULATION — rien ne sera enregistré' if SIMULER else 'MIGRATION') + f" sur {len(structures)} structure(s)")
    total = 0
    for sid in structures:
        rapport = migrer_structure(sid)
        if SIMULER:
            rapport += ["  (l'écriture d'OD de reclassement serait calculée après la renumérotation)"] if q(
                "SELECT 1 FROM comptes_comptables WHERE structure_id = :s AND numero = :n", s=sid, n=COMPTE_CHARGE_DIVERSE).first() else []
            db.session.rollback()
        else:
            db.session.commit()
            rapport += reclasser_charges(sid)
            db.session.commit()
        if rapport:
            total += 1
            print(f"Structure {sid} :")
            print("\n".join(rapport))
    orphelines = q("""SELECT COUNT(*) FROM lignes_ecritures l JOIN ecritures_comptables e ON e.id = l.ecriture_id
                      LEFT JOIN comptes_comptables c ON c.id = l.compte_id WHERE c.id IS NULL""").scalar()
    print(f"{total} structure(s) modifiée(s) — lignes d'écriture orphelines : {orphelines} (doit être 0)")
