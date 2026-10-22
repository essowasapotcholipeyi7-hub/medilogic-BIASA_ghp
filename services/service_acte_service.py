# -*- coding: utf-8 -*-
"""Recettes par service (patron, 2026-09-30) : "à la fin d'année on doit
[évaluer] les efforts de chaque service... pour décider de ristourne ou
pas". Réutilise ServiceHospitalisation (déjà réel, déjà peuplé pour
Service > Chambre > Lit) comme référentiel UNIQUE des services — pas de
deuxième liste à maintenir. ⭐ 2026-10-17 : ces services se créent dans la page
« Services de la structure », chacun avec un TYPE (TYPES_SERVICE) et la case
« Hospitalisation » ; seuls ces derniers sont proposés à l'admission d'un séjour.

Résolution du service d'une ligne vendue, dans cet ordre (le premier qui
tranche gagne) :
  1. Choix explicite fait à la vente (service_id porté par l'article) —
     ou service_id_force, pour une ligne issue d'une hospitalisation/d'un
     épisode ambulatoire : TOUTE la recette du séjour va au service RÉEL
     du séjour, quel que soit le type de chaque acte facturé dedans
     (patron : "Répartie par service d'hospitalisation réel").
  2. Classification manuelle par acte (ClassificationServiceActe) — pour
     les cas que le nom seul ne permet pas de trancher (ex. un acte
     chirurgical sur l'appareil génital doit aller en Gynéco-Obstétrique,
     pas en Chirurgie générale).
  3. Détection automatique depuis le nom de l'acte — uniquement les cas
     que le patron a explicitement dits "d'office connus" : S100
     (médecine générale), un suffixe "(SPECIALITE)" comme le catalogue en
     porte déjà (ex. "S101 Consultation specialisee (RHUMATOLOGIE)"), les
     codes Q (radiologie/imagerie), les codes R (laboratoire), et la vente
     pharmacie. ⭐ 2026-10-22 (patron) : plus les règles par domaine de
     _REGLES_DOMAINE (soins infirmiers, cardiologie, ophtalmologie,
     gynéco-obstétrique, petit matériel en pharmacie) et les analyses /
     examens d'imagerie reconnus à leur nom. Le reste n'est PAS deviné —
     mieux vaut "Autre" et visible qu'un mauvais rapprochement.

Jamais de ligne silencieusement absente du rapport : ce qui n'est
résolu par aucun des 3 niveaux tombe dans "Autre" (service_id NULL,
anciennement "Non classé"), toujours compté dans les totaux.
reclasser_recettes_service() réapplique les règles aux recettes déjà
enregistrées (après un changement de services ou de classement)."""
import re
import unicodedata

from models import db, ServiceHospitalisation, ClassificationServiceActe, RecetteService


def _normaliser(texte):
    if not texte:
        return ''
    texte = texte.replace('œ', 'oe').replace('Œ', 'OE')
    texte = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in texte if not unicodedata.combining(c))
    return texte.lower().strip()


def _mots(texte):
    """Texte normalisé réduit à des mots séparés par une espace (apostrophes, tirets,
    parenthèses... deviennent des espaces) — pour chercher des mots-clés entiers."""
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', _normaliser(texte)).split())


def _contient(nom_mots, motifs):
    """Un des motifs (expressions régulières sur _mots()) est présent dans le nom."""
    return any(re.search(m, nom_mots) for m in motifs)


# ⭐ 2026-10-17 (patron : « il faut que la création des services soit bien claire ») — avant, la seule
# liste était celle de l'hospitalisation, et le laboratoire ou la pharmacie y étaient créés comme des
# services d'hospitalisation.
TYPES_SERVICE = {
    'clinique': 'Médical / chirurgical',
    'laboratoire': 'Laboratoire',
    'imagerie': 'Imagerie / radiologie',
    'pharmacie': 'Pharmacie',
    'autre': 'Autre (soins, administratif...)',
}
TYPES_SANS_HOSPITALISATION = ('laboratoire', 'imagerie', 'pharmacie')


def charger_services(structure_id, usage=None):
    """Services actifs de cette structure — [{id, nom, type, hospitalisation}] — pour peupler le
    sélecteur "Service" et pour la détection automatique.
    usage='hospitalisation' : seulement ceux qui reçoivent des hospitalisés (admission d'un séjour) ;
    usage='soins' : sans laboratoire / imagerie / pharmacie (épisode de soins ambulatoires)."""
    q = ServiceHospitalisation.query.filter_by(structure_id=structure_id, actif=True)
    if usage == 'hospitalisation':
        q = q.filter(db.or_(ServiceHospitalisation.hospitalisation.is_(None), ServiceHospitalisation.hospitalisation.is_(True)))
    elif usage == 'soins':
        q = q.filter(db.or_(ServiceHospitalisation.type_service.is_(None),
                            ~ServiceHospitalisation.type_service.in_(TYPES_SANS_HOSPITALISATION)))
    services = q.order_by(ServiceHospitalisation.nom).all()
    return [{'id': s.id, 'nom': s.nom, 'type': s.type_service or 'clinique',
             'hospitalisation': s.hospitalisation is not False} for s in services]


def _trouver_service_par_mot_cle(services, mots_cles):
    """Premier service dont le nom (normalisé) contient un des mots-clés
    (eux aussi normalisés) — tolère les variantes d'accent/casse sans
    deviner un service qui n'existe pas réellement chez cette structure."""
    for s in services:
        nom_norm = _normaliser(s['nom'])
        for mc in mots_cles:
            if mc in nom_norm:
                return s
    return None


def _trouver_service_par_type(services, type_service, mots_cles):
    """⭐ 2026-10-17 : d'abord le service déclaré de ce TYPE (page Services de la structure), sinon
    le premier dont le nom contient un des mots-clés (services créés avant les types)."""
    for s in services:
        if s.get('type') == type_service:
            return s
    return _trouver_service_par_mot_cle(services, mots_cles)


# ⭐ Uniquement les préfixes que le patron a dits "d'office connus" — le
# reste (P, B, C...) reste volontairement non deviné (voir docstring).
_MOTS_CLES_PAR_PREFIXE = {
    'Q': ('imagerie', ['radiologie', 'imagerie']),
    'R': ('laboratoire', ['laboratoire', 'biologie']),
}


def _charger_classification_manuelle(structure_id):
    """{nom_acte: service_id} — table d'exceptions saisie à la main."""
    lignes = ClassificationServiceActe.query.filter_by(structure_id=structure_id).all()
    return {l.nom_acte: l.service_id for l in lignes}


# ⭐ 2026-10-22 (patron) : classement automatique par domaine, d'après le nom de l'acte.
# Chaque règle : (motifs cherchés dans le nom, type de service visé ou None, mots-clés du nom
# du service visé dans l'ordre de préférence, motifs qui empêchent la règle). Si la structure
# n'a pas ce service, la règle ne tranche pas et on passe aux suivantes (un écho-doppler
# cardiaque sans service de cardiologie retombe ainsi en radiologie, par son code Q).
_REGLES_DOMAINE = [
    # Petit matériel vendu comme un acte (spéculum, gants...) : c'est de la pharmacie.
    ([r'\bspeculum', r'\bgants?\b', r'\bthermometre', r'\bseringues?\b', r'\bcompresses?\b',
      r'\bsparadrap', r'\bcatheter', r'\bperfuseur', r'\bepicranien'],
     'pharmacie', ['pharmacie'], []),
    # Cardiologie : écho-doppler cardiaque, MAPA, ECG, Holter, épreuve d'effort, IPS.
    ([r'\bdoppler cardiaque', r'\bechodoppler cardiaque', r'\becho doppler cardiaque', r'\bechocardiograph',
      r'\bmapa\b', r'\becg\b', r'\belectrocardiogra', r'\bholter', r'\bepreuve d effort',
      r'\bpression systolique'],
     None, ['cardiolog'], []),
    # Ophtalmologie : kératométrie, pachymétrie, PIO, glaucome, cristallin, fond d'œil...
    ([r'\bkeratometr', r'\bpachymetr', r'\bpio\b', r'\bpression intra ?oculaire', r'\btonometr',
      r'\btonograph', r'\bglaucom', r'\bcristallin', r'\bcataract', r'\bfonds? d oeil', r'\brefraction',
      r'\bchamp visuel', r'\bbiomicroscop', r'\bgonioscop', r'\bacuite visuelle', r'\bophtalm'],
     None, ['ophtalm'], []),
    # Césarienne, accouchement : obstétrique (sinon gynécologie / maternité).
    ([r'\bcesarienne', r'\baccouchement'], None, ['obstetri', 'gyneco', 'maternite'], []),
    # Échographie obstétricale, consultation prénatale : gynécologie.
    ([r'\bech\w* obstetric', r'\bobstetricale', r'\bprenatale?\b'], None, ['gyneco', 'obstetri', 'maternite'], []),
    # Soins infirmiers vendus directement (injections, perfusions, mises en observation...).
    # Au cours d'une hospitalisation, la ligne va au service du séjour (service_id_force).
    # Pas pour « Scanner avec injection » ni un examen codé Q (imagerie) / R (laboratoire).
    ([r'\binjections?\b', r'\bperfusions?\b', r'\bmise en observation', r'\bsalle d observation',
      r'\bsoins? (et surveillance )?infirmier', r'\bsurveillance infirmi', r'\bpansements?\b',
      r'\boxygenotherapie', r'\bnebulisation', r'\baerosol', r'\bsondage', r'\bacte im\b',
      r'\bintramusculaire', r'\bintraveineuse'],
     None, ['soins', 'infirmier'], ['IMAGERIE', r'^[qr]\d']),
]

# Analyses de biologie reconnues au nom quand il n'y a pas de code R (« NFS », « CRP »...).
_MOTIFS_LABORATOIRE = [
    r'\bhemogramme', r'\bnfs\b', r'\bcrp\b', r'\bvs\b', r'\bvitesse de sedimentation', r'\bionogramme',
    r'\bglycemie', r'\bglucose\b', r'\buree\b', r'\bcreatinin', r'\bbilan (lipidique|hepatique|renal)',
    r'\btransaminase', r'\btsh', r'\bft3\b', r'\bft4\b', r'\bpsa\b', r'\btroponine', r'\bd ?dimere',
    r'\bgroupage', r'\bgroupe sanguin', r'\bserologie', r'\bhemoglobine glyquee', r'\bhba1c',
    r'\bgoutte epaisse', r'\becbu\b', r'\btp\b', r'\binr\b', r'\btemps de (quick|cephaline)',
    r'\btaux de prothrombine', r'\bbnp\b', r'\bnt pro', r'\bmicroalbumin', r'\bacide urique', r'\bggt\b',
    r'\bcholesterol', r'\btriglycerid', r'\bferritine', r'\bwidal', r'\bbeta ?hcg', r'\bbhcg',
    r'\btest de grossesse', r'\bvih\b', r'\bhepatite', r'\btoxoplasm', r'\bdengue', r'\bpaludisme',
    r'\btdr\b', r'\bselles\b', r'\bspermogramme', r'\bcalcemie', r'\bmagnesemie', r'\bproteinurie',
    r'\bbilirubin', r'\bamylase', r'\blipase', r'\bcpk\b', r'\bldh\b', r'\bphosphatase',
    r'\belectrophorese', r'\bhemoculture', r'\bantibiogramme', r'\bfibrinog', r'\breticulocyt',
]

# Imagerie reconnue au nom quand il n'y a pas de code Q (« Echodoppler thyroïdienne »...).
_MOTIFS_IMAGERIE = [
    r'\bechograph', r'\becho\b', r'\bechodoppler', r'\bdoppler', r'\bradiograph', r'\bradio\b',
    r'\bscanner', r'\btdm\b', r'\birm\b', r'\bmammograph', r'\bscintigraph',
]


def _racine_service(nom_service):
    """« CARDIOLOGIE » -> « cardiolog » (reconnaît aussi « cardiologique »),
    « PEDIATRIE » -> « pediatr » ; les autres noms sont gardés entiers."""
    nom = _mots(nom_service)
    if nom.endswith('ologie'):
        return nom[:-2]
    if nom.endswith('iatrie'):
        return nom[:-2]
    return nom


def _service_dans_le_nom(texte, services):
    """Service dont le nom (ou sa racine, voir _racine_service) figure dans le texte, le plus
    long d'abord (« MEDECINE GENERALE » plutôt que « MEDECINE ») — ou, à l'inverse, dont le nom
    contient le texte en mots entiers (« (MEDECINE INTERNE) » -> « SERVICE MEDECINE INTERNE »).
    Mots entiers seulement : « (GE) » ne doit plus tomber en « MEDECINE GENERALE »."""
    texte_mots = _mots(texte)
    if not texte_mots:
        return None
    par_longueur = sorted(services, key=lambda s: len(s['nom'] or ''), reverse=True)
    for s in par_longueur:
        racine = _racine_service(s['nom'])
        if racine and re.search(r'\b' + re.escape(racine), texte_mots):
            return s
    if len(texte_mots) >= 4:
        for s in par_longueur:
            if re.search(r'\b' + re.escape(texte_mots) + r'\b', _mots(s['nom'])):
                return s
    return None


def _service_vise(services, type_service, mots_cles):
    """Service visé par une règle : d'abord par son TYPE (s'il y en a un), puis par les mots-clés
    de son nom, dans l'ordre (le premier mot-clé trouvé gagne)."""
    if type_service:
        for s in services:
            if s.get('type') == type_service:
                return s
    for mc in mots_cles:
        trouve = _trouver_service_par_mot_cle(services, [mc])
        if trouve:
            return trouve
    return None


def deviner_service_acte(nom_acte, services):
    """Détection automatique (niveau 3) — retourne un dict de `services`
    (voir charger_services) ou None si non déterminable (la ligne va alors
    dans « Autre »). `services` doit être la liste déjà chargée de cette
    structure (jamais rechargée ici, pour rester bon marché sur un panier de
    plusieurs lignes).

    ⭐ 2026-10-22 (patron) : règles par domaine (voir _REGLES_DOMAINE), puis
    consultation d'une spécialité, puis codes (Q imagerie, R laboratoire),
    puis analyses / imagerie reconnues au nom. Corrige aussi les noms
    finissant par une parenthèse (« R607 Hemogramme(NFS Complete) ») : la
    parenthèse coupait court à toute détection, les analyses restaient
    « Non classé »."""
    if not nom_acte or not services:
        return None
    nom = nom_acte.strip()
    nom_mots = _mots(nom)

    # Carnets (CPN, carnet de consultation, carnet TA...) : « Autre », volontairement.
    if re.search(r'\bcarnets?\b', nom_mots):
        return None

    for motifs, type_service, mots_cles, exclusions in _REGLES_DOMAINE:
        exclusions = [m for e in exclusions for m in (_MOTIFS_IMAGERIE if e == 'IMAGERIE' else [e])]
        if _contient(nom_mots, motifs) and not _contient(nom_mots, exclusions):
            s = _service_vise(services, type_service, mots_cles)
            if s:
                return s

    # S100 précisément — "d'office" médecine générale.
    if re.match(r'^S100\b', nom, re.IGNORECASE):
        s = _trouver_service_par_mot_cle(services, ['medecine generale', 'generaliste'])
        if s:
            return s

    # Spécialité nommée : suffixe "(SPECIALITE)" du catalogue (« S101 Consultation specialisee
    # (RHUMATOLOGIE) », « (UROLOGIQUE) » pour UROLOGIE), ou consultation qui la nomme
    # (« S101 Consultation CARDIOLOGIQUE », « Consultation en pediatrie »).
    m = re.search(r'\(([^)]+)\)\s*$', nom)
    if m:
        s = _service_dans_le_nom(m.group(1), services)
        if s:
            return s
    # (« Chirurgie dentaire » n'est pas la chirurgie générale : laissée en « Autre ».)
    if (re.search(r'\bconsultation', nom_mots) or re.match(r'^S1\d{2}\b', nom, re.IGNORECASE)) \
            and not re.search(r'\bdentaire', nom_mots):
        s = _service_dans_le_nom(nom, services)
        if s:
            return s

    # Préfixe de code au début du nom (ex. "Q100 Examen...", "R100 ...").
    m = re.match(r'^([A-Z]{1,3})\d{2,4}\b', nom)
    if m:
        regle = _MOTS_CLES_PAR_PREFIXE.get(m.group(1).upper())
        if regle:
            s = _trouver_service_par_type(services, regle[0], regle[1])
            if s:
                return s

    # Sans code : analyses de biologie, puis imagerie, reconnues au nom.
    if _contient(nom_mots, _MOTIFS_LABORATOIRE):
        s = _trouver_service_par_type(services, 'laboratoire', ['laboratoire', 'biologie'])
        if s:
            return s
    if _contient(nom_mots, _MOTIFS_IMAGERIE):
        s = _trouver_service_par_type(services, 'imagerie', ['radiologie', 'imagerie'])
        if s:
            return s

    return None


def resoudre_service_acte(structure_id, nom_acte, service_id_choisi=None, service_id_force=None,
                           classification_cache=None, services_cache=None, origine_si_choisi='choix_manuel'):
    """Point d'entrée unique — applique les 3 niveaux dans l'ordre et
    retourne (service_id, service_nom, origine). `service_id_force`
    (venant d'une hospitalisation/d'un épisode ambulatoire) a TOUJOURS
    priorité sur le choix ligne par ligne : la recette d'un séjour va
    entièrement au service du séjour. `classification_cache`/
    `services_cache` : passer le résultat déjà chargé de
    _charger_classification_manuelle()/charger_services() pour éviter de
    les recharger à chaque ligne d'un même panier."""
    services = services_cache if services_cache is not None else charger_services(structure_id)
    services_par_id = {s['id']: s['nom'] for s in services}

    if service_id_force:
        service_id_force = int(service_id_force)
        if service_id_force in services_par_id:
            return service_id_force, services_par_id[service_id_force], 'choix_manuel'

    if service_id_choisi:
        service_id_choisi = int(service_id_choisi)
        if service_id_choisi in services_par_id:
            return service_id_choisi, services_par_id[service_id_choisi], origine_si_choisi

    classification = classification_cache if classification_cache is not None else _charger_classification_manuelle(structure_id)
    if nom_acte in classification:
        sid = classification[nom_acte]
        if sid in services_par_id:
            return sid, services_par_id[sid], 'classification'

    devine = deviner_service_acte(nom_acte, services)
    if devine:
        return devine['id'], devine['nom'], 'auto'

    # ⭐ 2026-10-22 (patron) : « au lieu de dire non classé, mets autre »
    return None, LIBELLE_AUTRE, 'non_classe'


# Libellé des recettes qu'aucune règle ne range dans un service (service_id NULL).
LIBELLE_AUTRE = 'Autre'


def _resoudre_ligne(structure_id, nom, type_source, service_id_choisi, service_id_force,
                    classification, services):
    """Service d'une ligne (acte ou produit) — commun à la vente et au reclassement.
    Vente pharmacie : "d'office" service Pharmacie, pas besoin de sélecteur ni de code — un
    médicament/consommable n'a pas de code de nomenclature S/Q/R à analyser. Distinct d'un
    VRAI choix ligne par ligne (origine 'choix_manuel') : personne n'a rien choisi ici, c'est
    une règle automatique comme les autres."""
    origine_si_choisi = 'choix_manuel'
    if type_source == 'produit' and not service_id_choisi and not service_id_force:
        pharmacie = _trouver_service_par_type(services, 'pharmacie', ['pharmacie'])
        service_id_choisi = pharmacie['id'] if pharmacie else None
        origine_si_choisi = 'auto'
    return resoudre_service_acte(
        structure_id, nom,
        service_id_choisi=service_id_choisi,
        service_id_force=service_id_force,
        classification_cache=classification,
        services_cache=services,
        origine_si_choisi=origine_si_choisi,
    )


def reclasser_recettes_service(structure_id):
    """⭐ 2026-10-22 (patron) : applique les règles ACTUELLES (classement manuel par acte,
    règles automatiques, services existants) aux recettes déjà enregistrées — sinon une
    analyse vendue avant une nouvelle règle (ou avant la création du service) restait
    « Autre » pour toujours. Ne touche que les lignes rangées automatiquement ou pas rangées
    (origine 'auto' / 'non_classe' / 'classification') : jamais un choix fait à la vente, ni une
    ligne d'hospitalisation (toujours au service du séjour). Renvoie le nombre de lignes
    dont le service a changé."""
    services = charger_services(structure_id)
    classification = _charger_classification_manuelle(structure_id)
    lignes = RecetteService.query.filter(
        RecetteService.structure_id == structure_id,
        db.or_(RecetteService.origine.is_(None),
               RecetteService.origine.in_(['auto', 'non_classe', 'classification'])),
        db.or_(RecetteService.type_source.is_(None), RecetteService.type_source != 'hospitalisation'),
    ).all()
    nb = 0
    for l in lignes:
        service_id, service_nom, origine = _resoudre_ligne(
            structure_id, l.nom_acte, l.type_source or 'acte', None, None, classification, services)
        if l.service_id != service_id or l.origine != origine:
            l.service_id, l.service_nom, l.origine = service_id, service_nom, origine
            nb += 1
    if nb:
        db.session.commit()
    return nb


def reclasser_recettes_service_sans_echec(structure_id):
    """Reclassement après un changement de services / de classement : ne doit jamais faire
    échouer l'enregistrement qui l'a déclenché."""
    try:
        return reclasser_recettes_service(structure_id)
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Reclassement des recettes par service (structure {structure_id}) : {e}")
        return 0


def creer_lignes_service(structure_id, articles, vente_id, service_id_force=None, type_source_defaut=None):
    """Parcourt les articles d'une vente tout juste créée et crée une
    RecetteService pour chaque ligne — même principe que
    creer_lignes_part_medecin (part_medecin_service.py). Ne fait RIEN si
    la vente ne contient aucun article (comportement inchangé pour tout
    le reste). `service_id_force` : voir resoudre_service_acte.
    `type_source_defaut` : pour un appelant dédié à un seul type d'article
    (ex. api_vente_pharma, dont le panier ne porte jamais de champ 'type')
    — sert de repli quand l'article lui-même n'en précise pas."""
    if not articles:
        return []

    services = charger_services(structure_id)
    classification = _charger_classification_manuelle(structure_id)
    lignes = []

    for a in articles:
        nom = a.get('nom')
        if not nom:
            continue
        type_article = a.get('type') or type_source_defaut or 'acte'
        type_source = 'produit' if type_article == 'produit' else 'acte'

        service_id, service_nom, origine = _resoudre_ligne(
            structure_id, nom, type_source, a.get('service_id'), service_id_force, classification, services)

        prix = a.get('prix')
        if prix is None:
            prix = a.get('prix_unitaire') or a.get('prix_reel') or 0
        prix = float(prix or 0)
        quantite = int(a.get('quantite') or 1)
        montant = round(prix * quantite, 2)

        ligne = RecetteService(
            structure_id=structure_id,
            service_id=service_id,
            service_nom=service_nom,
            vente_id=vente_id,
            nom_acte=nom,
            type_source='hospitalisation' if service_id_force else type_source,
            origine=origine,
            prix=prix,
            quantite=quantite,
            montant=montant,
        )
        db.session.add(ligne)
        lignes.append(ligne)

    if lignes:
        db.session.commit()
    return lignes


def situation_ventes(structure_id, vente_ids):
    """⭐ 2026-10-17 (patron) : situation financière ACTUELLE de chaque vente, pour répartir ses
    recettes par service. {vente_id: {base, encaisse, rembourse, du_assurances, du_patients, aides}}
      base          = sous-total de la vente (= somme de ses lignes de recettes par service)
      encaisse      = payé par le patient (à la vente + règlements de sa créance) − remboursements
                      + payé par les assurances (factures assurance, au prorata de ce qu'elles ont réglé)
      rembourse     = remboursé au patient (dépenses « remboursement patient »)
      du_assurances = parts AMU + privée − déjà payé par les assurances
      du_patients   = reste impayé par le patient
      aides         = aide hospitalière / remise (ce qui n'est dû par personne)
    Même calcul de « payé par le patient » que services/remboursement_service.py."""
    import json
    from collections import defaultdict
    from models import Vente, Recette, Depense, Facture
    ids = [int(i) for i in set(vente_ids or []) if i]
    if not ids:
        return {}
    ventes = {v.id: v for v in Vente.query.filter(Vente.structure_id == structure_id, Vente.id.in_(ids)).all()}
    non_annulee = db.or_(Recette.est_annulation.is_(None), Recette.est_annulation.is_(False))
    paye_vente = dict(db.session.query(Recette.source_id, db.func.sum(Recette.montant)).filter(
        Recette.structure_id == structure_id, Recette.source == 'patients', non_annulee,
        Recette.source_id.in_(ids), Recette.source_type.in_(['vente_acte', 'vente_pharma', 'vente_proforma'])
    ).group_by(Recette.source_id).all())
    facture_vente = dict(db.session.query(Facture.id, Facture.vente_id).filter(
        Facture.structure_id == structure_id, Facture.vente_id.in_(ids)).all())
    paye_creance = defaultdict(float)
    if facture_vente:
        for fid, total in db.session.query(Recette.source_id, db.func.sum(Recette.montant)).filter(
                Recette.structure_id == structure_id, Recette.source == 'patients', non_annulee,
                Recette.source_type == 'facture', Recette.source_id.in_(list(facture_vente))).group_by(Recette.source_id).all():
            paye_creance[facture_vente[fid]] += float(total or 0)
    rembourse = dict(db.session.query(Depense.vente_id, db.func.sum(Depense.montant)).filter(
        Depense.structure_id == structure_id, Depense.motif == 'remboursement_patient',
        Depense.vente_id.in_(ids)).group_by(Depense.vente_id).all())
    # paiements des assurances : chaque facture assurance liste ses ventes ; ce qu'elle a réglé est
    # réparti sur ses ventes au prorata de leur part
    paye_assurance = defaultdict(float)
    from sqlalchemy import text as _text
    for f in db.session.execute(_text("""SELECT details, montant_total, montant_rembourse FROM factures_assurance
                                         WHERE structure_id = :s AND COALESCE(montant_rembourse, 0) > 0"""),
                                {'s': structure_id}).mappings():
        total = float(f['montant_total'] or 0)
        if total <= 0:
            continue
        ratio = min(float(f['montant_rembourse'] or 0) / total, 1.0)
        det = f['details']
        try:
            det = json.loads(det) if isinstance(det, str) else (det or [])
        except ValueError:
            det = []
        for x in det:
            if isinstance(x, dict) and x.get('id') in ventes:
                paye_assurance[x['id']] += float(x.get('montant_assurance') or 0) * ratio
    res = {}
    for vid, v in ventes.items():
        base = float(v.sous_total or 0)
        part_assurances = max(float(v.prise_en_charge or 0), 0) + max(float(v.prise_en_charge2 or 0), 0)
        net = float(v.net_a_payer or 0)
        paye_patient = float(paye_vente.get(vid) or 0) + paye_creance.get(vid, 0.0)
        remb = float(rembourse.get(vid) or 0)
        assur_payee = min(paye_assurance.get(vid, 0.0), part_assurances)
        du_patients = max(net - paye_patient, 0.0)
        res[vid] = {
            'base': base,
            'encaisse': paye_patient - remb + assur_payee,
            'rembourse': remb,
            'du_assurances': max(part_assurances - assur_payee, 0.0),
            'du_patients': du_patients,
            'aides': max(base - part_assurances - min(paye_patient, net) - du_patients, 0.0),
        }
    return res


CLES_SITUATION = ('encaisse', 'du_assurances', 'du_patients', 'rembourse', 'aides')


def bornes_periode_heures(args):
    """Période du rapport « Recettes par service », heures possibles (prise de service, ex. du
    17/10 16:00 au 18/10 09:00). Renvoie (début, fin EXCLUE, libellé « du … au … »). Sans
    heure : journées entières. ValueError si les dates sont invalides. Partagé par l'écran
    administrateur (app.py) et l'onglet de la comptabilité (routes/comptabilite.py)."""
    from datetime import datetime, timedelta
    d = datetime.strptime(args.get('date_debut') or '', '%Y-%m-%d')
    f = datetime.strptime(args.get('date_fin') or '', '%Y-%m-%d')
    hd = (args.get('heure_debut') or '00:00').strip() or '00:00'
    hf = (args.get('heure_fin') or '23:59').strip() or '23:59'
    debut = datetime.combine(d.date(), datetime.strptime(hd, '%H:%M').time())
    fin_exclue = datetime.combine(f.date(), datetime.strptime(hf, '%H:%M').time()) + timedelta(minutes=1)
    libelle = f"du {d.strftime('%d/%m/%Y')} à {hd} au {f.strftime('%d/%m/%Y')} à {hf}"
    return debut, fin_exclue, libelle


def _repartir(montant_ligne, situation):
    """Part d'une ligne dans la situation de sa vente (au prorata de son montant)."""
    if not situation or situation['base'] <= 0:
        return {k: 0.0 for k in CLES_SITUATION}
    part = float(montant_ligne or 0) / situation['base']
    return {k: situation[k] * part for k in CLES_SITUATION}


def detail_recettes_service(structure_id, date_debut, date_fin, service_id=None):
    """⭐ 2026-10-17 (patron) : lignes d'UN service sur la période (service_id None = non classé),
    avec la vente et le patient — pour le détail et l'impression. Mêmes filtres que le rapport."""
    from sqlalchemy import text
    filtre = 'r.service_id = :sv' if service_id else 'r.service_id IS NULL'
    lignes = db.session.execute(text(f"""
        SELECT r.created_at, r.vente_id, v.numero_local, v.patient_nom, r.nom_acte, r.type_source,
               r.quantite, r.prix, r.montant
        FROM recettes_service r LEFT JOIN ventes v ON v.id = r.vente_id
        WHERE r.structure_id = :s AND r.created_at >= :d AND r.created_at < :f AND {filtre}
          AND (r.vente_id IS NULL OR v.statut IS NULL OR v.statut != 'annulee')
        ORDER BY r.created_at, r.id
    """), {'s': structure_id, 'd': date_debut, 'f': date_fin, 'sv': service_id}).mappings().all()
    situations = situation_ventes(structure_id, [l['vente_id'] for l in lignes])
    return [{
        'date': l['created_at'].strftime('%d/%m/%Y %H:%M') if l['created_at'] else '',
        'vente_id': l['vente_id'], 'numero': l['numero_local'] or l['vente_id'],
        'patient': l['patient_nom'] or '', 'acte': l['nom_acte'], 'type': l['type_source'] or '',
        'quantite': int(l['quantite'] or 1), 'prix': float(l['prix'] or 0), 'montant': float(l['montant'] or 0),
        **{k: round(v, 2) for k, v in _repartir(l['montant'], situations.get(l['vente_id'])).items()},
    } for l in lignes]


def generer_rapport_recettes_service(structure_id, date_debut, date_fin):
    """Agrège les RecetteService de la période par service — le rapport
    "Recettes par service" (comparaison + décision de ristourne)."""
    # ⭐ 2026-10-14 : hors ventes annulées (elles restaient comptées dans le rapport)
    from models import Vente
    ventes_annulees = db.session.query(Vente.id).filter(Vente.structure_id == structure_id,
                                                        Vente.statut == 'annulee')
    lignes = RecetteService.query.filter(
        RecetteService.structure_id == structure_id,
        RecetteService.created_at >= date_debut,
        RecetteService.created_at < date_fin,
        db.or_(RecetteService.vente_id.is_(None), ~RecetteService.vente_id.in_(ventes_annulees)),
    ).all()

    # ⭐ 2026-10-17 (patron) : encaissé / dû assurances / dû patients par service
    situations = situation_ventes(structure_id, [l.vente_id for l in lignes])
    # nom ACTUEL du service (il a pu être renommé depuis la vente)
    noms_actuels = {s.id: s.nom for s in ServiceHospitalisation.query.filter_by(structure_id=structure_id).all()}
    agrege = {}
    for l in lignes:
        cle = l.service_id if l.service_id else 'non_classe'
        if cle not in agrege:
            agrege[cle] = {'service_id': l.service_id,
                           'service_nom': (noms_actuels.get(l.service_id) or l.service_nom or LIBELLE_AUTRE)
                                          if l.service_id else LIBELLE_AUTRE,
                           'montant_total': 0.0,
                           'nb_lignes': 0, **{k: 0.0 for k in CLES_SITUATION}}
        agrege[cle]['montant_total'] += float(l.montant or 0)
        agrege[cle]['nb_lignes'] += 1
        for k, v in _repartir(l.montant, situations.get(l.vente_id)).items():
            agrege[cle][k] += v

    resultat = sorted(agrege.values(), key=lambda r: r['montant_total'], reverse=True)
    for r in resultat:
        for k in ('montant_total',) + CLES_SITUATION:
            r[k] = round(r[k], 2)
    return resultat
