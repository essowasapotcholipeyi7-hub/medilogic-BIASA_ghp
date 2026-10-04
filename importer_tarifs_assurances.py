"""Import des onglets "TARIFS ASSUR. ACTES" / "TARIFS ASSUR. MEDOC" d'un
fichier de collecte rempli par une structure (voir les fichiers CHP / CHU /
CHR "- avec tarifs assurances.xlsx") vers la base :
  - prix non assuré par acte / produit        -> prix_non_assure_actes
  - tarif privé + PBR par acte x compagnie    -> pbr_complementaires

Rapprochement par le NOM exact de la colonne B (celui du catalogue de la
structure, code compris). Par défaut : simulation (rien n'est écrit), avec le
détail de ce qui serait posé et des lignes ignorées. --appliquer pour écrire.

Usage :
    python importer_tarifs_assurances.py <fichier.xlsx> <structure_id> [--appliquer]
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
if (getattr(sys.stdout, 'encoding', '') or '').lower().replace('-', '') != 'utf8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from openpyxl import load_workbook  # noqa: E402

ONGLETS = {'TARIFS ASSUR. ACTES': 'acte', 'TARIFS ASSUR. MEDOC': 'produit'}
PLACEHOLDER = 'écrire son nom ici'
NB_ASSURANCES = 5


def nombre(v):
    if v is None or v == '':
        return None
    try:
        x = float(str(v).replace(' ', '').replace(',', '.'))
    except ValueError:
        return None
    return x if x > 0 else None


def lire_onglet(ws):
    """-> (compagnies: {col_debut: nom}, lignes: [{nom, prix_non_assure, par_compagnie: {nom: (tarif, pbr1, pbr2)}}], ignorees)"""
    compagnies = {}
    for n in range(NB_ASSURANCES):
        c0 = 5 + 3 * n
        v = ws.cell(row=3, column=c0).value
        if v and PLACEHOLDER not in str(v).lower() and str(v).strip():
            compagnies[c0] = str(v).strip()
    lignes, ignorees = [], []
    for r in range(5, ws.max_row + 1):
        nom = ws.cell(row=r, column=2).value
        if nom is None or str(nom).strip() == '':
            continue
        nom = str(nom).strip()
        prix_na = nombre(ws.cell(row=r, column=4).value)
        par_compagnie = {}
        for c0, compagnie in compagnies.items():
            tarif = nombre(ws.cell(row=r, column=c0).value)
            pbr1 = nombre(ws.cell(row=r, column=c0 + 1).value)
            pbr2 = nombre(ws.cell(row=r, column=c0 + 2).value)
            if tarif is None and pbr1 is None and pbr2 is None:
                continue
            if tarif is None and pbr1 is None and pbr2 is not None:
                ignorees.append((r, nom, compagnie, 'PBR alternatif sans PBR habituel ni tarif privé'))
                continue
            par_compagnie[compagnie] = (tarif, pbr1, pbr2)
        # valeurs saisies sous une colonne dont le nom d'assurance n'a pas été rempli
        for n in range(NB_ASSURANCES):
            c0 = 5 + 3 * n
            if c0 not in compagnies and any(nombre(ws.cell(row=r, column=c0 + j).value) for j in range(3)):
                ignorees.append((r, nom, f'assurance n°{n + 1}', "nom de l'assurance non renseigné en ligne 3"))
        if prix_na is None and not par_compagnie:
            continue
        lignes.append({'nom': nom, 'prix_non_assure': prix_na, 'par_compagnie': par_compagnie})
    return compagnies, lignes, ignorees


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    chemin, structure_id = args[0], int(args[1])
    appliquer = '--appliquer' in sys.argv

    wb = load_workbook(chemin, data_only=True)
    resume = {}
    for onglet, type_article in ONGLETS.items():
        if onglet not in wb.sheetnames:
            print(f'(onglet {onglet!r} absent, ignoré)')
            continue
        compagnies, lignes, ignorees = lire_onglet(wb[onglet])
        resume[type_article] = (compagnies, lignes, ignorees)
        n_na = sum(1 for l in lignes if l['prix_non_assure'] is not None)
        n_pc = sum(len(l['par_compagnie']) for l in lignes)
        print(f'\n=== {onglet} ({type_article}) : assurances = {list(compagnies.values()) or "aucune"}')
        print(f'    {n_na} prix non assuré, {n_pc} tarif(s)/PBR par assurance, {len(ignorees)} ligne(s) ignorée(s)')
        for r, nom, comp, motif in ignorees[:30]:
            print(f'    - ligne {r} « {nom} » [{comp}] : {motif}')
        for l in lignes[:8]:
            print(f'    ex. « {l["nom"]} » : prix non assuré={l["prix_non_assure"]} ; {l["par_compagnie"]}')

    if not appliquer:
        print('\nSimulation terminée — rien écrit. Relancez avec --appliquer pour enregistrer.')
        return

    from app import app  # noqa: E402  (connexion base)
    from models import db, PbrComplementaire, PrixNonAssureActe  # noqa: E402
    from services.hospitalisation_service import enregistrer_prix_non_assure  # noqa: E402

    with app.app_context():
        poses_na = poses_pc = 0
        for type_article, (compagnies, lignes, _) in resume.items():
            for l in lignes:
                if l['prix_non_assure'] is not None:
                    enregistrer_prix_non_assure(structure_id, l['nom'], l['prix_non_assure'],
                                                user_nom='import fichier', type_article=type_article)
                    poses_na += 1
                for compagnie, (tarif, pbr1, pbr2) in l['par_compagnie'].items():
                    existante = PbrComplementaire.query.filter_by(
                        structure_id=structure_id, type=type_article, nom_acte=l['nom'], compagnie=compagnie
                    ).first()
                    if existante:
                        existante.tarif_prive, existante.pbr_1, existante.pbr_2 = tarif, pbr1, pbr2
                    else:
                        db.session.add(PbrComplementaire(
                            structure_id=structure_id, type=type_article, nom_acte=l['nom'], compagnie=compagnie,
                            tarif_prive=tarif, pbr_1=pbr1, pbr_2=pbr2, created_by='import fichier'))
                    poses_pc += 1
        db.session.commit()
        print(f'\nOK structure {structure_id} : {poses_na} prix non assuré et {poses_pc} tarifs/PBR par assurance enregistrés.')


if __name__ == '__main__':
    main()
