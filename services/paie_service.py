# services/paie_service.py
# ============================================================
# MOTEUR DE CALCUL DE LA PAIE — TOGO (agents publics et privés)
# ============================================================
# ⚠️ Les taux utilisés viennent de ParametragePaie (modifiable dans l'écran
# "Paramètres de paie") et, par salarié, des dérogations individuelles sur
# Employe. Les valeurs par défaut sont indicatives — à faire valider par
# votre comptable / la DGI avant la première paie réelle.
#
# Deux profils :
#   - Privé  : retraite CNSS, assurance maladie AMU-CNSS
#   - Public : retraite CRT (assiette = salaire de base), AMU-INAM
# L'AMU (décret n°2023-096/PR du 4 octobre 2023) a un taux global fixe
# (10% par défaut) réparti entre salarié et employeur : la part salarié ne
# peut jamais dépasser la moitié du taux global, la part employeur ne peut
# jamais être inférieure à cette moitié — ce verrou s'applique même si un
# taux personnalisé est saisi pour un salarié donné (voir resoudre_taux_paie).

from datetime import date
from models import db, Paie, ParametragePaie, Employe, Depense


def _d(v):
    """Convertit en float en tolérant None/Decimal/str."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def calculer_irpp(base_imposable_annuelle, tranches):
    """Calcule l'IRPP ANNUEL par application successive du barème
    progressif (les tranches sont exprimées en revenu annuel)."""
    if base_imposable_annuelle <= 0 or not tranches:
        return 0.0

    impot = 0.0
    for tranche in sorted(tranches, key=lambda t: t.get('min', 0)):
        seuil_min = _d(tranche.get('min'))
        seuil_max = tranche.get('max')
        seuil_max = _d(seuil_max) if seuil_max is not None else None
        taux = _d(tranche.get('taux')) / 100.0

        if base_imposable_annuelle <= seuil_min:
            continue

        haut_tranche = min(base_imposable_annuelle, seuil_max) if seuil_max is not None else base_imposable_annuelle
        montant_tranche = max(0.0, haut_tranche - seuil_min)
        impot += montant_tranche * taux

    return round(impot, 2)


def resoudre_taux_paie(employe, parametrage):
    """Résout le profil et les taux effectifs d'un employé : dérogation
    individuelle si renseignée, sinon valeur par défaut de la structure
    selon son secteur. Le verrou AMU (salarié <= moitié du taux global,
    employeur >= moitié) est toujours appliqué en dernier, qu'il s'agisse
    d'un taux par défaut ou d'une dérogation."""
    secteur = (getattr(employe, 'secteur_paie', None) or 'prive').lower()
    if secteur not in ('prive', 'public'):
        secteur = 'prive'

    if secteur == 'public':
        organisme_retraite = 'CRT'
        organisme_amu = 'AMU-INAM'
        taux_retraite_sal_defaut = _d(parametrage.taux_crt_salarial)
        taux_retraite_pat_defaut = _d(parametrage.taux_crt_patronal)
        plafond_retraite = _d(parametrage.plafond_crt)
    else:
        organisme_retraite = 'CNSS'
        organisme_amu = 'AMU-CNSS'
        taux_retraite_sal_defaut = _d(parametrage.taux_cnss_salarial)
        taux_retraite_pat_defaut = _d(parametrage.taux_cnss_patronal)
        plafond_retraite = _d(parametrage.plafond_cnss)

    override_retraite_sal = getattr(employe, 'taux_retraite_salarial_override', None)
    taux_retraite_sal = _d(override_retraite_sal) if override_retraite_sal is not None else taux_retraite_sal_defaut

    override_retraite_pat = getattr(employe, 'taux_retraite_patronal_override', None)
    taux_retraite_pat = _d(override_retraite_pat) if override_retraite_pat is not None else taux_retraite_pat_defaut

    # --- Verrou AMU : part salarié <= moitié du taux global, part
    # employeur >= moitié — décret n°2023-096/PR, non contournable.
    demi_amu = _d(parametrage.amu_taux_global) / 2.0

    override_amu_sal = getattr(employe, 'taux_amu_salarial_override', None)
    taux_amu_sal = _d(override_amu_sal) if override_amu_sal is not None else _d(parametrage.taux_amu_salarial_defaut)
    taux_amu_sal = min(taux_amu_sal, demi_amu)

    override_amu_pat = getattr(employe, 'taux_amu_patronal_override', None)
    taux_amu_pat = _d(override_amu_pat) if override_amu_pat is not None else _d(parametrage.taux_amu_patronal_defaut)
    taux_amu_pat = max(taux_amu_pat, demi_amu)

    return {
        'secteur': secteur,
        'organisme_retraite': organisme_retraite,
        'organisme_amu': organisme_amu,
        'taux_retraite_salarial': taux_retraite_sal,
        'taux_retraite_patronal': taux_retraite_pat,
        'plafond_retraite': plafond_retraite,
        'taux_amu_salarial': taux_amu_sal,
        'taux_amu_patronal': taux_amu_pat,
        'demi_amu': demi_amu,
    }


def calculer_paie(employe, salaire_base, primes, indemnites, parametrage,
                   prets=0, acomptes=0, autres_retenues=None, personnes_a_charge=None):
    """Calcule un bulletin de paie complet en suivant l'ordre du cahier des
    charges :
      1) Salaire de base (+ primes/indemnités) = Salaire brut
      2) - Cotisations sociales salariales (retraite + AMU) = Brut imposable
      3) - Abattement forfaitaire 28% (plafonné/an) - Déduction personnes à
         charge (10 000 F/mois/personne, max 6) = Revenu net imposable
      4) Barème IRPP (annuel, annualisé x12 puis impôt /12)
      5) - Autres retenues (prêts, acomptes, autres) = Net à payer
    Ne persiste rien — fonction pure, testable isolément."""
    salaire_base = _d(salaire_base)
    primes = _d(primes)
    indemnites = _d(indemnites)
    brut = salaire_base + primes + indemnites

    taux = resoudre_taux_paie(employe, parametrage)

    # Assiette retraite : salaire brut (privé/CNSS) ou salaire de base /
    # traitement indiciaire (public/CRT) — cf. cahier des charges §7.
    assiette_retraite = brut if taux['secteur'] == 'prive' else salaire_base
    plafond_retraite = taux['plafond_retraite']
    if plafond_retraite and plafond_retraite > 0:
        assiette_retraite = min(assiette_retraite, plafond_retraite)

    retraite_salarial = round(assiette_retraite * taux['taux_retraite_salarial'] / 100.0, 2)
    retraite_patronal = round(assiette_retraite * taux['taux_retraite_patronal'] / 100.0, 2)

    # Assiette AMU : salaire brut, pour les deux secteurs.
    amu_salarial = round(brut * taux['taux_amu_salarial'] / 100.0, 2)
    amu_patronal = round(brut * taux['taux_amu_patronal'] / 100.0, 2)

    formation_pro = 0.0
    if taux['secteur'] == 'prive':
        formation_pro = round(brut * _d(parametrage.taux_formation_pro) / 100.0, 2)

    brut_imposable = max(0.0, brut - retraite_salarial - amu_salarial)

    # --- IRPP : barème ANNUEL -> on annualise la base mensuelle (x12),
    # applique l'abattement et les déductions (également annualisées),
    # calcule l'impôt annuel puis le ramène au mois (/12).
    brut_imposable_annuel = brut_imposable * 12.0
    abattement_annuel = min(
        brut_imposable_annuel * _d(parametrage.abattement_taux) / 100.0,
        _d(parametrage.abattement_plafond_annuel)
    )

    nb_charges = personnes_a_charge if personnes_a_charge is not None else getattr(employe, 'personnes_a_charge', 0)
    try:
        nb_charges = int(nb_charges or 0)
    except (TypeError, ValueError):
        nb_charges = 0
    max_charges = int(parametrage.max_personnes_charge or 6)
    nb_charges = max(0, min(nb_charges, max_charges))
    deduction_charges_annuelle = nb_charges * _d(parametrage.deduction_personne_charge) * 12.0

    revenu_net_imposable_annuel = max(0.0, brut_imposable_annuel - abattement_annuel - deduction_charges_annuelle)
    irpp_annuel = calculer_irpp(revenu_net_imposable_annuel, parametrage.tranches_irpp or [])
    irpp = round(irpp_annuel / 12.0, 2)

    abattement = round(abattement_annuel / 12.0, 2)
    deduction_charges_familiales = round(deduction_charges_annuelle / 12.0, 2)
    revenu_net_imposable = round(revenu_net_imposable_annuel / 12.0, 2)

    autres_retenues = [r for r in (autres_retenues or []) if isinstance(r, dict) and r.get('libelle')]
    autres_retenues_total = round(sum(_d(r.get('montant')) for r in autres_retenues), 2)
    prets = round(_d(prets), 2)
    acomptes = round(_d(acomptes), 2)

    total_retenues = round(retraite_salarial + amu_salarial + irpp + prets + acomptes + autres_retenues_total, 2)
    total_charges_patronales = round(retraite_patronal + amu_patronal + formation_pro, 2)
    net_a_payer = round(brut - total_retenues, 2)

    return {
        'secteur': taux['secteur'],
        'organisme_retraite': taux['organisme_retraite'],
        'organisme_amu': taux['organisme_amu'],
        'salaire_base': salaire_base,
        'primes': primes,
        'indemnites': indemnites,
        'salaire_brut': round(brut, 2),
        'taux_retraite_salarial': taux['taux_retraite_salarial'],
        'taux_retraite_patronal': taux['taux_retraite_patronal'],
        'retraite_salarial': retraite_salarial,
        'retraite_patronal': retraite_patronal,
        'taux_amu_salarial': taux['taux_amu_salarial'],
        'taux_amu_patronal': taux['taux_amu_patronal'],
        'amu_salarial': amu_salarial,
        'amu_patronal': amu_patronal,
        'formation_pro': formation_pro,
        'salaire_brut_imposable': round(brut_imposable, 2),
        'personnes_a_charge': nb_charges,
        'abattement': abattement,
        'deduction_charges_familiales': deduction_charges_familiales,
        'revenu_net_imposable': revenu_net_imposable,
        'irpp': irpp,
        'prets_deduction': prets,
        'acomptes_deduction': acomptes,
        'autres_retenues': autres_retenues,
        'autres_retenues_total': autres_retenues_total,
        'total_retenues': total_retenues,
        'total_charges_patronales': total_charges_patronales,
        'net_a_payer': net_a_payer,
    }


def generer_ou_maj_paie(structure_id, employe_id, annee, mois, salaire_base=None,
                         primes=0, indemnites=0, prets=0, acomptes=0,
                         autres_retenues=None, personnes_a_charge=None, user_nom='System'):
    """Crée (ou recalcule si encore en brouillon/validée, pas encore payée)
    le bulletin de paie d'un employé pour une période donnée."""
    employe = Employe.query.get(employe_id)
    if not employe:
        return None, "Employé introuvable"

    parametrage = ParametragePaie.get_ou_creer(structure_id)
    base = salaire_base if salaire_base is not None else employe.salaire_base
    calc = calculer_paie(employe, base, primes, indemnites, parametrage,
                          prets=prets, acomptes=acomptes, autres_retenues=autres_retenues,
                          personnes_a_charge=personnes_a_charge)

    paie = Paie.query.filter_by(employe_id=employe_id, annee=annee, mois=mois).first()
    if paie and paie.statut == 'payee':
        return None, "Cette paie a déjà été payée — impossible de la recalculer"

    if not paie:
        paie = Paie(structure_id=structure_id, employe_id=employe_id, annee=annee, mois=mois,
                     created_by=user_nom)
        db.session.add(paie)

    for champ, valeur in calc.items():
        setattr(paie, champ, valeur)
    paie.statut = 'valide'

    db.session.commit()
    return paie, None


def marquer_paie_payee(paie, mode_paiement='especes', user_nom='System'):
    """Marque une paie comme payée : crée la Dépense correspondante puis
    l'écriture comptable auto-validée (débit charges de personnel, crédit
    trésorerie + organismes sociaux/fiscaux à reverser)."""
    if paie.statut == 'payee':
        return paie, None

    employe = paie.employe

    depense = Depense(
        structure_id=paie.structure_id,
        montant=_d(paie.net_a_payer),
        motif='salaire',
        motif_personnalise=f"Salaire {paie.get_periode_label()} — {employe.nom} {employe.prenom}",
        description=f"Bulletin de paie #{paie.id}",
        created_by_nom=user_nom,
    )
    db.session.add(depense)
    db.session.flush()

    paie.statut = 'payee'
    paie.mode_paiement = mode_paiement
    paie.date_paiement = date.today()
    paie.depense_id = depense.id
    db.session.commit()

    try:
        from services.comptabilite_service import generer_ecriture_paie
        ecriture = generer_ecriture_paie(paie, employe, user_nom=user_nom)
        if ecriture:
            paie.ecriture_id = ecriture.id
            db.session.commit()
    except Exception as e:
        print(f"⚠️ Erreur génération écriture comptable (paie #{paie.id} conservée payée): {e}")

    try:
        from services.journal_service import JournalService
        JournalService.creer_mouvement(
            structure_id=paie.structure_id, categorie='salaire_paye',
            description=f"Salaire {paie.get_periode_label()} payé — {employe.nom} {employe.prenom}",
            montant=_d(paie.net_a_payer), type_montant='debit',
            reference_type='paie', reference_id=paie.id,
            utilisateur_nom=user_nom,
        )
    except Exception as e:
        print(f"⚠️ Erreur journal d'activité (paie #{paie.id}): {e}")

    return paie, None


# ============================================================
# DÉCLARATIONS MENSUELLES (IRPP, CNSS/CRT, AMU-CNSS/AMU-INAM)
# ============================================================
# À déposer avant le 15 du mois suivant (délai usuel pour ces organismes au
# Togo — à confirmer avec votre comptable). Une déclaration = l'agrégation,
# pour un mois donné, des bulletins déjà calculés (statut valide ou payée —
# un brouillon n'a pas vocation à être déclaré).

TYPES_DECLARATION = {
    'irpp': {'label': 'IRPP', 'organisme': 'DGI'},
    'cnss': {'label': 'CNSS (retraite — secteur privé)', 'organisme': 'CNSS'},
    'crt': {'label': 'CRT (retraite — secteur public)', 'organisme': 'CRT'},
    'amu-cnss': {'label': 'AMU-CNSS (secteur privé)', 'organisme': 'AMU-CNSS'},
    'amu-inam': {'label': 'AMU-INAM (secteur public)', 'organisme': 'AMU-INAM'},
}


def date_limite_declaration(annee, mois):
    """Le 15 du mois suivant la période déclarée."""
    from datetime import date as _date
    if mois == 12:
        return _date(annee + 1, 1, 15)
    return _date(annee, mois + 1, 15)


def generer_declaration(structure_id, annee, mois, type_declaration):
    """Agrège les bulletins de paie du mois pour un type de déclaration
    donné (irpp, cnss, crt, amu-cnss, amu-inam). Retourne un dict prêt à
    afficher/imprimer : lignes par employé + totaux."""
    if type_declaration not in TYPES_DECLARATION:
        return None

    paies = Paie.query.filter_by(structure_id=structure_id, annee=annee, mois=mois) \
        .filter(Paie.statut.in_(['valide', 'payee'])).all()

    lignes = []
    total_salarial = 0.0
    total_patronal = 0.0

    for p in paies:
        e = p.employe
        nom_employe = f"{e.nom} {e.prenom}" if e else f"Employé #{p.employe_id}"
        matricule = e.matricule if e else '-'

        if type_declaration == 'irpp':
            montant = _d(p.irpp)
            if montant <= 0:
                continue
            lignes.append({
                'matricule': matricule, 'employe': nom_employe,
                'base': _d(p.revenu_net_imposable), 'taux': None,
                'salarial': montant, 'patronal': 0.0, 'total': montant,
            })
            total_salarial += montant

        elif type_declaration in ('cnss', 'crt'):
            organisme_attendu = 'CNSS' if type_declaration == 'cnss' else 'CRT'
            if (p.organisme_retraite or '') != organisme_attendu:
                continue
            sal, pat = _d(p.retraite_salarial), _d(p.retraite_patronal)
            if sal <= 0 and pat <= 0:
                continue
            lignes.append({
                'matricule': matricule, 'employe': nom_employe,
                'base': _d(p.salaire_base) if organisme_attendu == 'CRT' else _d(p.salaire_brut),
                'taux': f"{_d(p.taux_retraite_salarial):.2f}% / {_d(p.taux_retraite_patronal):.2f}%",
                'salarial': sal, 'patronal': pat, 'total': round(sal + pat, 2),
            })
            total_salarial += sal
            total_patronal += pat

        elif type_declaration in ('amu-cnss', 'amu-inam'):
            organisme_attendu = 'AMU-CNSS' if type_declaration == 'amu-cnss' else 'AMU-INAM'
            if (p.organisme_amu or '') != organisme_attendu:
                continue
            sal, pat = _d(p.amu_salarial), _d(p.amu_patronal)
            if sal <= 0 and pat <= 0:
                continue
            lignes.append({
                'matricule': matricule, 'employe': nom_employe,
                'base': _d(p.salaire_brut),
                'taux': f"{_d(p.taux_amu_salarial):.2f}% / {_d(p.taux_amu_patronal):.2f}%",
                'salarial': sal, 'patronal': pat, 'total': round(sal + pat, 2),
            })
            total_salarial += sal
            total_patronal += pat

    lignes.sort(key=lambda l: l['employe'])

    return {
        'type': type_declaration,
        'label': TYPES_DECLARATION[type_declaration]['label'],
        'organisme': TYPES_DECLARATION[type_declaration]['organisme'],
        'annee': annee, 'mois': mois,
        'lignes': lignes,
        'nb_employes': len(lignes),
        'total_salarial': round(total_salarial, 2),
        'total_patronal': round(total_patronal, 2),
        'total': round(total_salarial + total_patronal, 2),
        'date_limite': date_limite_declaration(annee, mois),
    }
