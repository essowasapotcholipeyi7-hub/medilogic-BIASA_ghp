# -*- coding: utf-8 -*-
"""Recettes par service (patron, 2026-09-30) : "à la fin d'année on doit
[évaluer] les efforts de chaque service... pour décider de ristourne ou
pas". Réutilise ServiceHospitalisation (déjà réel, déjà peuplé pour
Service > Chambre > Lit) comme référentiel UNIQUE des services — pas de
deuxième liste à maintenir.

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
     pharmacie. Tout le reste (P, B, C, actes ambigus...) n'est PAS deviné
     — mieux vaut "Non classé" et visible qu'un mauvais rapprochement.

Jamais de ligne silencieusement absente du rapport : ce qui n'est
résolu par aucun des 3 niveaux tombe dans "Non classé" (service_id NULL),
toujours compté dans les totaux."""
import re
import unicodedata

from models import db, ServiceHospitalisation, ClassificationServiceActe, RecetteService


def _normaliser(texte):
    if not texte:
        return ''
    texte = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in texte if not unicodedata.combining(c))
    return texte.lower().strip()


def charger_services(structure_id):
    """Services actifs de cette structure — {id: nom} — pour peupler le
    sélecteur "Service" et pour la détection automatique."""
    services = ServiceHospitalisation.query.filter_by(structure_id=structure_id, actif=True).order_by(ServiceHospitalisation.nom).all()
    return [{'id': s.id, 'nom': s.nom} for s in services]


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


# ⭐ Uniquement les préfixes que le patron a dits "d'office connus" — le
# reste (P, B, C...) reste volontairement non deviné (voir docstring).
_MOTS_CLES_PAR_PREFIXE = {
    'Q': ['radiologie', 'imagerie'],
    'R': ['laboratoire', 'biologie'],
}


def _charger_classification_manuelle(structure_id):
    """{nom_acte: service_id} — table d'exceptions saisie à la main."""
    lignes = ClassificationServiceActe.query.filter_by(structure_id=structure_id).all()
    return {l.nom_acte: l.service_id for l in lignes}


def deviner_service_acte(nom_acte, services):
    """Détection automatique (niveau 3) — retourne un dict de `services`
    (voir charger_services) ou None si non déterminable. `services` doit
    être la liste déjà chargée de cette structure (jamais rechargée ici,
    pour rester bon marché sur un panier de plusieurs lignes)."""
    if not nom_acte or not services:
        return None
    nom = nom_acte.strip()

    # S100 précisément — "d'office" médecine générale.
    if re.match(r'^S100\b', nom, re.IGNORECASE):
        return _trouver_service_par_mot_cle(services, ['medecine generale', 'generaliste'])

    # Suffixe "(SPECIALITE)" — déjà présent tel quel dans le catalogue
    # (ex. "S101 Consultation specialisee (RHUMATOLOGIE)").
    m = re.search(r'\(([^)]+)\)\s*$', nom)
    if m:
        specialite = _normaliser(m.group(1))
        for s in services:
            nom_service_norm = _normaliser(s['nom'])
            if specialite == nom_service_norm or specialite in nom_service_norm or nom_service_norm in specialite:
                return s
        # Parenthèse présente mais aucun service ne correspond : on ne
        # devine pas plus loin (mieux vaut Non classé qu'un mauvais choix).
        return None

    # Préfixe de code au début du nom (ex. "Q100 Examen...", "R100 ...").
    m = re.match(r'^([A-Z]{1,3})\d{2,4}\b', nom)
    if m:
        mots_cles = _MOTS_CLES_PAR_PREFIXE.get(m.group(1).upper())
        if mots_cles:
            return _trouver_service_par_mot_cle(services, mots_cles)

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

    return None, 'Non classé', 'non_classe'


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

        # ⭐ Vente pharmacie : "d'office" service Pharmacie, pas besoin de
        # sélecteur ni de code — un médicament/consommable n'a pas de
        # code de nomenclature S/Q/R à analyser. Distinct d'un VRAI choix
        # ligne par ligne (origine 'choix_manuel') : personne n'a rien
        # choisi ici, c'est une règle automatique comme les autres.
        service_id_choisi = a.get('service_id')
        origine_si_choisi = 'choix_manuel'
        if type_source == 'produit' and not service_id_choisi and not service_id_force:
            pharmacie = _trouver_service_par_mot_cle(services, ['pharmacie'])
            service_id_choisi = pharmacie['id'] if pharmacie else None
            origine_si_choisi = 'auto'

        service_id, service_nom, origine = resoudre_service_acte(
            structure_id, nom,
            service_id_choisi=service_id_choisi,
            service_id_force=service_id_force,
            classification_cache=classification,
            services_cache=services,
            origine_si_choisi=origine_si_choisi,
        )

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


def generer_rapport_recettes_service(structure_id, date_debut, date_fin):
    """Agrège les RecetteService de la période par service — le rapport
    "Recettes par service" (comparaison + décision de ristourne)."""
    lignes = RecetteService.query.filter(
        RecetteService.structure_id == structure_id,
        RecetteService.created_at >= date_debut,
        RecetteService.created_at < date_fin,
    ).all()

    agrege = {}
    for l in lignes:
        cle = l.service_id if l.service_id else 'non_classe'
        if cle not in agrege:
            agrege[cle] = {'service_id': l.service_id, 'service_nom': l.service_nom or 'Non classé', 'montant_total': 0.0, 'nb_lignes': 0}
        agrege[cle]['montant_total'] += float(l.montant or 0)
        agrege[cle]['nb_lignes'] += 1

    resultat = sorted(agrege.values(), key=lambda r: r['montant_total'], reverse=True)
    for r in resultat:
        r['montant_total'] = round(r['montant_total'], 2)
    return resultat
