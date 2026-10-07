"""Règle de paiement du bon de consultation lors d'un rendez-vous.

Patron (2026-10-07) : « les patients doivent payer la consultation après
15 jours dans les privés et 30 jours dans les publics, selon le type de
consultation ». Concrètement :
  - même type de consultation (médecine générale, cardiologie...) et moins
    de N jours depuis la dernière consultation payée  -> contrôle SANS FRAIS ;
  - au-delà de N jours, ou type de consultation différent (cardio alors
    qu'on avait payé une rhumato)                      -> À PAYER (nouveau
    bon de consultation à régler à la caisse avant de passer).
N = délai de la structure (parametrage_rendez_vous.delai_controle_jours),
sinon 30 jours pour une structure publique (statut AMU), 15 jours sinon.

Le résultat est affiché sur l'impression du rendez-vous, dans les messages
WhatsApp (confirmation, rappel, report) et sur le portail patient : « ça
donne une certaine assurance » au patient qui sait avant de venir s'il doit
payer ou non.

Sources d'une « consultation payée » : les ventes d'actes validées du
patient (acte dont le nom contient « consult »), et en secours les
rendez-vous du même type passés au statut « terminé ».
"""
import json
import re
import unicodedata
from datetime import date, datetime, timedelta

DELAI_PUBLIC_JOURS = 30
DELAI_PRIVE_JOURS = 15

# Familles de consultation : (clé, libellé affiché, racines reconnues en
# début de mot dans un motif, une spécialité de médecin ou un nom d'acte).
FAMILLES = [
    ('general', 'médecine générale', ('general', 'omnipratic', 'medecine gen')),
    ('cardio', 'cardiologie', ('cardio',)),
    ('rhumato', 'rhumatologie', ('rhumat',)),
    ('gyneco', 'gynécologie-obstétrique', ('gynec', 'obstet', 'matern', 'grossesse', 'cpn', 'sage-femme', 'sage femme')),
    ('pediatrie', 'pédiatrie', ('pediat',)),
    ('neuro', 'neurologie', ('neuro',)),
    ('ophtalmo', 'ophtalmologie', ('ophtalm', 'ophtam', 'oculi')),
    ('pneumo', 'pneumologie', ('pneumo',)),
    ('stomato', 'stomatologie / dentaire', ('stomato', 'dentaire', 'dentist', 'odont')),
    ('dermato', 'dermatologie', ('dermat',)),
    ('uro', 'urologie', ('urolog',)),
    ('orl', 'ORL', ('orl', 'oto-rhino', 'otorhino')),
    ('psy', 'psychiatrie / psychologie', ('psych',)),
    ('chirurgie', 'chirurgie', ('chirur',)),
    ('gastro', 'gastro-entérologie', ('gastro', 'hepato')),
    ('endocrino', 'endocrinologie / diabétologie', ('endocrin', 'diabet')),
    ('nephro', 'néphrologie', ('nephro',)),
    ('hemato', 'hématologie', ('hemato',)),
    ('onco', 'oncologie', ('oncol', 'cancer')),
    ('traumato', 'traumatologie / orthopédie', ('traumat', 'orthop')),
    ('infectio', 'infectiologie', ('infect',)),
    ('nutrition', 'nutrition', ('nutrit', 'dietet')),
    ('kine', 'kinésithérapie', ('kine', 'physio')),
    ('interne', 'médecine interne', ('interne',)),
    ('radio', 'radiologie', ('radio', 'imager', 'echograph')),
]

# Un motif est une « consultation » (donc concerné par la règle) s'il
# contient l'un de ces mots ; vaccination, prise de sang, pansement,
# certificat... ne le sont pas et n'affichent rien.
MOTS_CONSULTATION = ('consult', 'controle', 'suivi', 'resultat', 'urgence', 'examen medical', 'grossesse', 'visite')


def normaliser(texte):
    """Minuscules, sans accents, espaces simples."""
    texte = unicodedata.normalize('NFKD', str(texte or ''))
    texte = ''.join(c for c in texte if not unicodedata.combining(c)).lower()
    return re.sub(r'\s+', ' ', texte).strip()


def famille(texte):
    """Clé de famille (cardio, general...) trouvée dans le texte, sinon None."""
    t = normaliser(texte)
    if not t:
        return None
    for cle, _libelle, racines in FAMILLES:
        for racine in racines:
            if re.search(r'(?<![a-z])' + re.escape(racine), t):
                return cle
    return None


def libelle_famille(cle):
    for c, libelle, _ in FAMILLES:
        if c == cle:
            return libelle
    return cle


def _slug(texte):
    """Clé de repli pour une spécialité inconnue des familles : premier mot
    significatif tronqué (« acupuncture » et « acupuncteur » -> « acupun »)."""
    mots = [m for m in re.split(r'[^a-z]+', normaliser(texte))
            if len(m) >= 4 and m not in ('consultation', 'specialisee', 'medecin', 'docteur', 'autre')]
    return mots[0][:6] if mots else None


def type_consultation_rdv(motif, specialite_medecin=None):
    """(clé, libellé) du type de consultation d'un rendez-vous, ou None si
    le motif n'est pas une consultation."""
    m = normaliser(motif)
    if not m or not any(mot in m for mot in MOTS_CONSULTATION):
        return None
    # Consultation spécialisée — X : la spécialité est dans le motif
    partie_spec = None
    if '—' in m:
        # « Contrôle — Cardiologie », « Consultation spécialisée — X » : la
        # spécialité est après le tiret (patron : « même si le motif est
        # contrôle on doit choisir dans quelle spécialité »)
        partie_spec = m.split('—', 1)[1].strip()
    elif 'specialis' in m:
        morceaux = re.split(r'[—:\-]', m, maxsplit=1)
        partie_spec = morceaux[1].strip() if len(morceaux) > 1 else ''
    if partie_spec is not None:
        partie_spec = re.sub(r'consult\w*|specialis\w*', ' ', partie_spec).strip()
    cle = famille(partie_spec if partie_spec else m)
    if cle:
        return cle, libelle_famille(cle)
    if partie_spec:
        s = _slug(partie_spec)
        if s:
            return s, partie_spec
    cle = famille(specialite_medecin)
    if cle:
        return cle, libelle_famille(cle)
    s = _slug(specialite_medecin)
    if s:
        return s, normaliser(specialite_medecin)
    return 'general', libelle_famille('general')


def type_consultation_acte(nom_acte):
    """Clé du type pour un acte vendu, ou None si ce n'est pas une consultation."""
    n = normaliser(nom_acte)
    if 'consult' not in n:
        return None
    cle = famille(n)
    if cle:
        return cle
    apres = re.sub(r'consult\w*', ' ', n)
    return _slug(apres) or 'general'


def _en_date(valeur):
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str) and valeur:
        try:
            return datetime.fromisoformat(valeur[:19]).date()
        except ValueError:
            return None
    return None


def _fmt(d):
    return d.strftime('%d/%m/%Y') if d else ''


def evaluer(date_rdv, type_cle, type_libelle, delai_jours, consultations_precedentes):
    """Logique pure. consultations_precedentes : liste de (date, clé_type,
    source) des consultations déjà payées (ventes) ou faites (rdv terminés),
    toutes dates confondues. Retourne le dict de résultat."""
    date_rdv = _en_date(date_rdv)
    memes = sorted([(d, src) for d, c, src in ((_en_date(x[0]), x[1], x[2]) for x in consultations_precedentes)
                    if d and c == type_cle and d < date_rdv], reverse=True)
    derniere = memes[0] if memes else None
    jours = (date_rdv - derniere[0]).days if derniere else None
    doit_payer = derniere is None or jours > delai_jours
    lib = type_libelle
    if not doit_payer:
        titre = 'SANS FRAIS'
        detail = (f"contrôle de {lib} dans les {delai_jours} jours suivant votre consultation du {_fmt(derniere[0])} — "
                  f"pas de nouveau bon de consultation à payer. Présentez-vous directement avec votre reçu.")
        badge = 'Sans frais'
    elif derniere is None:
        titre = 'À PAYER'
        detail = f"nouvelle consultation ({lib}). Merci de régler le bon de consultation à la caisse avant de passer en consultation."
        badge = 'Bon à payer'
    else:
        titre = 'À PAYER'
        detail = (f"votre dernière consultation de {lib} date du {_fmt(derniere[0])} (plus de {delai_jours} jours). "
                  f"Merci de régler le bon de consultation à la caisse avant de passer en consultation.")
        badge = 'Bon à payer'
    texte = f"{titre} : {detail}"
    return {
        'doit_payer': doit_payer,
        'type_cle': type_cle,
        'type_libelle': lib,
        'delai_jours': delai_jours,
        'date_reference': derniere[0].isoformat() if derniere else None,
        'date_reference_fr': _fmt(derniere[0]) if derniere else '',
        'source_reference': derniere[1] if derniere else None,
        'jours_ecoules': jours,
        'badge': badge,
        'titre': titre,
        'detail': detail,
        'texte': texte,
    }


def consultations_depuis_ventes(ventes):
    """[(date, clé, 'vente')] pour chaque acte « consultation » des ventes validées."""
    out = []
    for v in ventes:
        statut = getattr(v, 'statut', None)
        if statut and str(statut).lower().startswith('annul'):
            continue
        actes = getattr(v, 'actes', None)
        if isinstance(actes, str):
            try:
                actes = json.loads(actes)
            except ValueError:
                actes = []
        d = _en_date(getattr(v, 'date_vente', None))
        for a in actes or []:
            nom = a.get('nom') if isinstance(a, dict) else str(a)
            cle = type_consultation_acte(nom)
            if cle and d:
                out.append((d, cle, 'vente'))
    return out


def _specialite(medecin):
    if not medecin:
        return None
    return ' '.join(filter(None, [getattr(medecin, 'specialite', None), getattr(medecin, 'sous_specialite', None)])) or None


class PaiementConsultationService:
    """Accès aux données (délai de la structure, ventes, rendez-vous)."""

    @staticmethod
    def parametres(structure_id):
        """(delai_jours, actif, delai_defaut, statut_structure, delai_personnalise)."""
        from models import ParametrageAmuCnss, ParametrageRendezVous
        statut = None
        try:
            amu = ParametrageAmuCnss.query.filter_by(structure_id=structure_id).first()
            statut = (amu.statut_structure or '').strip().lower() if amu else None
        except Exception:
            statut = None
        delai_defaut = DELAI_PUBLIC_JOURS if statut == 'public' else DELAI_PRIVE_JOURS
        actif, perso = True, None
        try:
            p = ParametrageRendezVous.query.filter_by(structure_id=structure_id).first()
            if p:
                actif = bool(p.regle_paiement_active) if p.regle_paiement_active is not None else True
                perso = p.delai_controle_jours
        except Exception:
            pass
        delai = perso if perso else delai_defaut
        return delai, actif, delai_defaut, statut, perso

    @classmethod
    def evaluer_liste(cls, rdvs, structure_id=None):
        """{rdv.id: résultat ou None} pour une liste de rendez-vous, en deux
        requêtes (ventes + rendez-vous terminés des patients concernés)."""
        from models import Medecin, RendezVous, Vente, db
        from sqlalchemy import or_
        rdvs = [r for r in rdvs if r is not None]
        if not rdvs:
            return {}
        structure_id = structure_id or rdvs[0].structure_id
        delai, actif, _, _, _ = cls.parametres(structure_id)
        resultats = {r.id: None for r in rdvs}
        if not actif:
            return resultats
        medecins = {}

        def medecin_de(mid):
            if not mid:
                return None
            if mid not in medecins:
                medecins[mid] = db.session.get(Medecin, mid)
            return medecins[mid]

        types = {r.id: type_consultation_rdv(r.motif, _specialite(medecin_de(r.medecin_id))) for r in rdvs}
        concernes = [r for r in rdvs if types.get(r.id) and r.date_rendez_vous and r.patient_id]
        if not concernes:
            return resultats
        patients = list({r.patient_id for r in concernes})
        # Un an en arrière (et pas seulement le délai) : pour rappeler au patient
        # la date de sa dernière consultation du même type même hors délai.
        date_min = min(_en_date(r.date_rendez_vous) for r in concernes) - timedelta(days=max(delai + 1, 366))
        date_max = max(_en_date(r.date_rendez_vous) for r in concernes)
        ventes = Vente.query.filter(
            Vente.structure_id == structure_id, Vente.patient_id.in_(patients),
            or_(Vente.statut.is_(None), Vente.statut != 'annulee'),
            Vente.date_vente >= datetime.combine(date_min, datetime.min.time()),
            Vente.date_vente < datetime.combine(date_max + timedelta(days=1), datetime.min.time()),
        ).all()
        par_patient = {}
        for v in ventes:
            par_patient.setdefault(v.patient_id, []).append(v)
        termines = RendezVous.query.filter(
            RendezVous.structure_id == structure_id, RendezVous.patient_id.in_(patients),
            RendezVous.statut == 'termine', RendezVous.date_rendez_vous >= date_min,
            RendezVous.date_rendez_vous <= date_max,
        ).all()
        faits = {}
        for t in termines:
            tt = type_consultation_rdv(t.motif, _specialite(medecin_de(t.medecin_id)))
            if tt:
                faits.setdefault(t.patient_id, []).append((t.date_rendez_vous, tt[0], 'rdv'))
        for r in concernes:
            cle, lib = types[r.id]
            precedents = consultations_depuis_ventes(par_patient.get(r.patient_id, [])) + faits.get(r.patient_id, [])
            resultats[r.id] = evaluer(r.date_rendez_vous, cle, lib, delai, precedents)
        return resultats

    @classmethod
    def evaluer_rdv(cls, rdv):
        if rdv is None:
            return None
        return cls.evaluer_liste([rdv], rdv.structure_id).get(rdv.id)
