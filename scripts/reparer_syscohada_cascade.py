# scripts/reparer_syscohada_cascade.py
# ============================================================
# Réparation de l'incident du 2026-10-11 : scripts/migrer_syscohada_revise.py
# a été relancé sur des structures déjà migrées (connexion coupée, reprise) —
# plusieurs nouveaux numéros étant aussi d'anciens numéros, certains comptes
# ont été redéplacés (ex. 605 eau-électricité -> 60105 optique).
#
# 1. Note comme « migrées » les structures qui n'ont plus aucun ancien numéro
#    (table syscohada_structures_migrees) : le script de migration ne les
#    retraitera plus jamais.
# 2. Chaque charge issue de « Enregistrer une charge » est remise dans son
#    compte SYSCOHADA d'après son motif (sauf l'ancien « charges diverses »
#    déjà reclassé par l'OD de reclassement).
# 3. Les anciens comptes fusionnés (inactifs, vides) reçoivent un numéro unique.
# 4. Libellés des comptes standard réalignés sur le plan.
#
# Usage : python scripts/reparer_syscohada_cascade.py [--simuler]
# ============================================================
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import app  # noqa: E402
from models import db  # noqa: E402
from utils.plan_comptable_syscohada import (  # noqa: E402
    PLAN_COMPTABLE_PAR_NUMERO, RENUMEROTATION_SYSCOHADA, RECLASSEMENT_CHARGES_PAR_MOTIF,
    COMPTE_CHARGE_DIVERSE, compte_charge_pour_motif,
)

SIMULER = '--simuler' in sys.argv


def q(sql, **p):
    return db.session.execute(db.text(sql), p)


def compte_id(sid, numero):
    r = q("SELECT id FROM comptes_comptables WHERE structure_id = :s AND numero = :n ORDER BY actif DESC, id LIMIT 1",
          s=sid, n=numero).first()
    if r:
        q("UPDATE comptes_comptables SET actif = TRUE WHERE id = :i", i=r[0])
        return r[0]
    d = PLAN_COMPTABLE_PAR_NUMERO[numero]
    return q("""INSERT INTO comptes_comptables (structure_id, numero, nom, type, classe, actif)
                VALUES (:s, :n, :nom, :t, :c, TRUE) RETURNING id""",
             s=sid, n=numero, nom=d['nom'], t=d['type'], c=d['classe']).scalar()


with app.app_context():
    q("""CREATE TABLE IF NOT EXISTS syscohada_structures_migrees (
            structure_id INTEGER PRIMARY KEY, migree_le TIMESTAMP DEFAULT NOW())""")
    purs = sorted(set(RENUMEROTATION_SYSCOHADA) - set(RENUMEROTATION_SYSCOHADA.values()))
    etat = q("""SELECT structure_id, COUNT(*) FILTER (WHERE numero = ANY(:p)) FROM comptes_comptables
                GROUP BY structure_id ORDER BY structure_id""", p=purs).fetchall()
    migrees = [s for s, n in etat if not n]
    print(('SIMULATION — ' if SIMULER else '') + f"structures déjà migrées : {migrees}")
    for sid in migrees:
        q("INSERT INTO syscohada_structures_migrees (structure_id) VALUES (:s) ON CONFLICT DO NOTHING", s=sid)

    od = {r[0] for r in q("SELECT DISTINCT structure_id FROM ecritures_comptables WHERE source_type = 'reclassement_syscohada'")}
    lignes = q("""
        SELECT e.structure_id, l.id, c.numero, d.motif, l.debit
        FROM lignes_ecritures l JOIN ecritures_comptables e ON e.id = l.ecriture_id
        JOIN comptes_comptables c ON c.id = l.compte_id
        JOIN depenses d ON d.id = e.source_id AND e.source_type = 'depense'
        WHERE e.structure_id = ANY(:m) AND c.numero LIKE '6%' AND l.debit > 0
    """, m=migrees).fetchall()
    deplacees = 0
    for sid, lid, numero, motif, debit in lignes:
        attendu = compte_charge_pour_motif(motif)
        cle = (motif or '').strip().lower()
        reclassee_par_od = (numero == COMPTE_CHARGE_DIVERSE and sid in od
                            and any(cle == m or cle.startswith(m) for m in RECLASSEMENT_CHARGES_PAR_MOTIF))
        if attendu != numero and not reclassee_par_od:
            q("UPDATE lignes_ecritures SET compte_id = :c WHERE id = :l", c=compte_id(sid, attendu), l=lid)
            deplacees += 1
            print(f"  structure {sid} : ligne {lid} ({motif}, {int(debit):,} FCFA) {numero} -> {attendu}".replace(',', ' '))

    r = q("""UPDATE comptes_comptables SET numero = numero || '-' || id
             WHERE numero LIKE 'ANC-%' AND numero NOT LIKE 'ANC-%-%'""")
    print(f"anciens comptes fusionnés renumérotés de façon unique : {r.rowcount}")
    # une seule requête (la base distante coupe les traitements trop longs)
    valeurs = ', '.join(f"(:n{i}, :nom{i}, :t{i}, :c{i})" for i in range(len(PLAN_COMPTABLE_PAR_NUMERO)))
    params = {}
    for i, (num, d) in enumerate(PLAN_COMPTABLE_PAR_NUMERO.items()):
        params.update({f'n{i}': num, f'nom{i}': d['nom'], f't{i}': d['type'], f'c{i}': d['classe']})
    libelles = q(f"""UPDATE comptes_comptables c SET nom = v.nom, type = v.type, classe = v.classe
                     FROM (VALUES {valeurs}) AS v(numero, nom, type, classe)
                     WHERE c.numero = v.numero AND c.structure_id = ANY(:m)
                       AND (c.nom <> v.nom OR c.type IS DISTINCT FROM v.type OR c.classe IS DISTINCT FROM v.classe)""",
                 m=migrees, **params).rowcount
    print(f"lignes remises dans leur compte : {deplacees} — libellés réalignés : {libelles}")
    if SIMULER:
        db.session.rollback()
        print("SIMULATION : rien n'a été enregistré.")
    else:
        db.session.commit()
        print("Réparation enregistrée.")
