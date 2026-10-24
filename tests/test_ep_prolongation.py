"""Entente Préalable d'hospitalisation (patron, 2026-10-24) : jours demandés, rappel quand ils sont
atteints (libérer ou prolonger), prolongation marquée sur la fiche AMU."""
import io
from datetime import date, timedelta
from types import SimpleNamespace

from pypdf import PdfReader

from services.hospitalisation_service import jours_demandes_ep, echeance_ep_sejour, ep_obligatoire_sejour
from utils.remplissage_pdf_amu import mention_prolongation, remplir_entente_prealable


def _ep(**kw):
    base = dict(hospit_jours=None, hospit_duree_sejour=None, definitive_le=None, hospit_date_admission=None,
                prolongation_de_id=None, jours_prolongation=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _sejour(**kw):
    base = dict(statut='en_cours', date_entree=date.today(), est_assure_amu=True, assurance_nom='amu_cnss',
                chambre_categorie_amu=None, chambre_acte_nom=None, chambre_service=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_jours_demandes():
    assert jours_demandes_ep(_ep(hospit_jours=15)) == 15
    # anciennes demandes : le nombre écrit dans la durée probable
    assert jours_demandes_ep(_ep(hospit_duree_sejour='5 jours')) == 5
    assert jours_demandes_ep(_ep(hospit_duree_sejour='quelques jours')) is None
    # demande définitive : la durée écrite est la durée réelle, pas la durée demandée
    assert jours_demandes_ep(_ep(hospit_duree_sejour='7 nuitée(s)', definitive_le=date.today())) is None
    assert jours_demandes_ep(None) is None


def test_echeance_aujourdhui_et_depassee():
    admission = date.today() - timedelta(days=5)
    e = echeance_ep_sejour(_sejour(date_entree=admission), _ep(hospit_jours=5, hospit_date_admission=admission))
    assert e['echeance'] == date.today() and e['retard'] == 0          # « c'est aujourd'hui »
    e = echeance_ep_sejour(_sejour(date_entree=admission), _ep(hospit_jours=3, hospit_date_admission=admission))
    assert e['retard'] == 2
    e = echeance_ep_sejour(_sejour(date_entree=admission), _ep(hospit_jours=15, hospit_date_admission=admission))
    assert e['retard'] == -10                                          # prolongation : plus de rappel


def test_echeance_sans_objet():
    admission = date.today() - timedelta(days=9)
    ep = _ep(hospit_jours=5, hospit_date_admission=admission)
    assert echeance_ep_sejour(_sejour(statut='sortie'), ep) is None    # patient déjà libéré
    assert echeance_ep_sejour(_sejour(), None) is None
    assert echeance_ep_sejour(_sejour(), _ep(hospit_duree_sejour='?')) is None
    # sans date d'admission sur la demande : celle du séjour
    e = echeance_ep_sejour(_sejour(date_entree=admission), _ep(hospit_jours=5))
    assert e['debut'] == admission and e['retard'] == 4


def test_ep_obligatoire():
    assert ep_obligatoire_sejour(_sejour())
    assert not ep_obligatoire_sejour(_sejour(assurance_nom='GTA'))
    assert not ep_obligatoire_sejour(_sejour(est_assure_amu=False))
    assert not ep_obligatoire_sejour(_sejour(chambre_categorie_amu='observation'))
    assert not ep_obligatoire_sejour(_sejour(chambre_service='Urgences > Mise en observation > Lit 2'))


def test_mention_prolongation():
    assert mention_prolongation(_ep(hospit_jours=5)) == ''
    assert mention_prolongation(_ep(prolongation_de_id=3, hospit_jours=15, jours_prolongation=10)) == \
        'PROLONGATION : 5 j déjà demandés + 10 j = 15 jours'


def _texte_pdf(demande):
    patient = SimpleNamespace(nom='TEST', prenom='Patient', telephone='90000000', numero_assure='123')
    medecin = SimpleNamespace(nom='MED', prenom='Test', telephone='', code_prescripteur='', get_nom_complet=lambda: 'Dr Test')
    pdf = remplir_entente_prealable(demande, patient, medecin, '')
    return PdfReader(io.BytesIO(pdf)).pages[0].extract_text()


def test_fiche_marquee_prolongation_cnss_et_inam():
    for type_amu in ('amu_cnss', 'amu_inam'):
        commun = dict(type_amu=type_amu, inclure_actes=False, inclure_produits=False, inclure_hospitalisation=True,
                      lignes_motif=[], date_prescription=date.today(), hospit_date_admission=date.today(),
                      hospit_motif='Paludisme grave', hospit_categorie_salle='cabine_ventilee',
                      hospit_categorie_autre_precision=None, numero_feuille_soins=None)
        texte = _texte_pdf(_ep(**commun, prolongation_de_id=1, hospit_jours=15, jours_prolongation=10,
                               hospit_duree_sejour='15 jours'))
        assert 'PROLONGATION' in texte and '15 jours' in texte
        assert 'PROLONGATION' not in _texte_pdf(_ep(**commun, hospit_jours=5, hospit_duree_sejour='5 jours'))
