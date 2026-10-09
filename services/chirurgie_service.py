"""Proforma d'intervention chirurgicale — calcul à partir des K.

Reproduit le document papier des cliniques chirurgicales (patron,
2026-10-09, "FACTURE PROFORMA DE L'INTERVENTION") :

- cotation : chaque acte vaut K (l'acte principal en entier, les actes
  associés souvent divisés : K100/2 = K50), plus un coefficient
  supplémentaire en % du total ; total des K = somme ;
- tout le tableau découle de ce total : acte (valeur du K × total des K),
  second chirurgien et anesthésie (un % des K), bloc (un % des K × valeur
  du K bloc), aide opératoire (un nombre de K) ;
- chambre et soins infirmiers × nombre de jours ;
- forfaits (amplificateur, prévisions pharmacie/analyses...).

Pourcentages, aide opératoire et valeurs du K varient d'une intervention
à l'autre (patron) : ils sont réglés par défaut pour la structure puis
modifiables sur chaque proforma. Ce module est la seule source du calcul :
l'aperçu à l'écran (/api/chirurgie/calculer), l'enregistrement et
l'impression passent tous par calculer_proforma().
"""
from decimal import Decimal, ROUND_HALF_UP

PARAMETRES_DEFAUT = {
    'valeur_k': 1500,        # F par K (acte, second chirurgien, anesthésie, aide)
    'valeur_k_bloc': 1700,   # F par K pour le bloc
    'pct_second': 50,        # % des K pour le second chirurgien
    'pct_anesthesie': 50,    # % des K pour l'anesthésie
    'pct_bloc': 75,          # % des K pour le bloc
    'k_aide': 50,            # K de l'aide opératoire
    'soins_jour': 5000,      # soins infirmiers par jour
}

FORFAITS_DEFAUT = [
    "Location d'amplificateur",
    'Prévision pharmacie',
    'Prévision analyses',
    'ECG',
    'Prévision radiographie',
    'Prévision kinésithérapie',
    'Consultation pré-anesthésique',
]

NOTE_DEFAUT = (
    "Cette facture proforma est basée sur un coût moyen hors complications ; "
    "elle ne constitue nullement un coût fixe prédéfini. La facture définitive "
    "peut varier en fonction des résultats des examens ou de tout autre acte "
    "supplémentaire que requiert l'état du patient.\nNous vous remercions."
)

REGLAGES_DEFAUT = {
    'parametres': PARAMETRES_DEFAUT,
    'chambres': [{'nom': 'Chambre à deux lits', 'prix': 25000}],
    'forfaits': [{'nom': n, 'montant': 0} for n in FORFAITS_DEFAUT],
    'service': 'Service de chirurgie',
    'note': NOTE_DEFAUT,
    'ville': 'Lomé',
    'sigle': '',
    'signature': 'La Comptabilité',
}


def _nombre(valeur, defaut=0.0):
    try:
        n = float(str(valeur).replace(',', '.').replace(' ', '')) if valeur not in (None, '') else defaut
    except (TypeError, ValueError):
        return defaut
    return n if n >= 0 else defaut


def arrondi(montant):
    """Arrondi au franc, demi vers le haut (454 537,5 → 454 538)."""
    return int(Decimal(str(montant)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def fusionner_reglages(reglages):
    """Réglages de la structure complétés par les valeurs par défaut."""
    r = dict(REGLAGES_DEFAUT)
    r.update({k: v for k, v in (reglages or {}).items() if v is not None})
    p = dict(PARAMETRES_DEFAUT)
    p.update({k: v for k, v in ((reglages or {}).get('parametres') or {}).items() if v is not None})
    r['parametres'] = p
    return r


def normaliser_entree(data):
    """Nettoie ce qui vient du formulaire (texte, virgules, négatifs)."""
    params = dict(PARAMETRES_DEFAUT)
    for cle in PARAMETRES_DEFAUT:
        if cle in (data.get('parametres') or {}):
            params[cle] = _nombre(data['parametres'][cle], PARAMETRES_DEFAUT[cle])
    actes = []
    for a in data.get('actes') or []:
        nom = (a.get('nom') or '').strip()
        k = _nombre(a.get('k'))
        if not nom and not k:
            continue
        diviseur = _nombre(a.get('diviseur'), 1) or 1
        actes.append({'nom': nom, 'k': k, 'diviseur': diviseur})
    forfaits = []
    for f in data.get('forfaits') or []:
        nom = (f.get('nom') or '').strip()
        if nom:
            forfaits.append({'nom': nom, 'montant': _nombre(f.get('montant'))})
    return {
        'actes': actes,
        'coef_supp': _nombre(data.get('coef_supp')),
        'parametres': params,
        'chambre_nom': (data.get('chambre_nom') or '').strip(),
        'chambre_prix': _nombre(data.get('chambre_prix')),
        'jours': int(_nombre(data.get('jours'))),
        'forfaits': forfaits,
    }


def calculer_proforma(entree):
    """entree : sortie de normaliser_entree(). Renvoie la cotation détaillée,
    les lignes du tableau et le total."""
    p = entree['parametres']
    actes = []
    base_k = 0.0
    for a in entree['actes']:
        retenu = a['k'] / a['diviseur']
        base_k += retenu
        actes.append(dict(a, retenu=retenu))
    k_supp = base_k * entree['coef_supp'] / 100
    total_k = base_k + k_supp

    lignes = []

    def ajouter(designation, detail, nombre, groupe):
        if detail and nombre:
            lignes.append({'designation': designation, 'detail': detail, 'nombre': nombre,
                           'total': arrondi(detail * nombre), 'groupe': groupe})

    jours = entree['jours']
    ajouter('Chambre', entree['chambre_prix'], jours, 'chambre')
    ajouter('Acte', p['valeur_k'], total_k, 'k')
    ajouter('Acte du second chirurgien', p['valeur_k'], total_k * p['pct_second'] / 100, 'k')
    ajouter('Anesthésie', p['valeur_k'], total_k * p['pct_anesthesie'] / 100, 'k')
    ajouter('Aide opératoire', p['valeur_k'], p['k_aide'], 'k')
    ajouter('Bloc', p['valeur_k_bloc'], total_k * p['pct_bloc'] / 100, 'k')
    ajouter('Soins infirmiers', p['soins_jour'], jours, 'soins')
    for f in entree['forfaits']:
        if f['montant'] > 0:
            lignes.append({'designation': f['nom'], 'detail': None, 'nombre': None,
                           'total': arrondi(f['montant']), 'groupe': 'forfait'})

    return {
        'actes': actes,
        'base_k': base_k,
        'k_supp': k_supp,
        'total_k': total_k,
        'lignes': lignes,
        'total': sum(l['total'] for l in lignes),
    }


def format_k(n):
    """356.5 → '356,5' ; 267.375 → '267,375' ; 220.0 → '220'."""
    texte = ('%.3f' % float(n)).rstrip('0').rstrip('.')
    return texte.replace('.', ',')
