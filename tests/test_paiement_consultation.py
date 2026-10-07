"""Règle de paiement du bon de consultation (patron, 2026-10-07) : même type
de consultation dans le délai -> sans frais ; au-delà du délai ou autre type
-> à payer. Logique pure, sans base."""
from datetime import date, datetime

from services.paiement_consultation_service import (
    consultations_depuis_ventes, evaluer, famille, type_consultation_acte, type_consultation_rdv,
)


class _Vente:
    def __init__(self, d, actes, statut='validee'):
        self.date_vente, self.actes, self.statut = d, actes, statut


def test_familles_reconnues_malgre_les_graphies():
    assert famille('CARDIO') == famille('Cardiologie') == famille('S101 Consultation CARDIOLOGIQUE') == 'cardio'
    assert famille('RHUMATO') == famille('RHUMATOLOGUE') == 'rhumato'
    assert famille('generaliste') == famille('Consultation medecine generale') == 'general'
    assert famille('GYNECO-OBSTETRIQUE') == famille('MATERNITE') == famille('Suivi de grossesse') == 'gyneco'
    assert famille('accident du travail') is None  # « dent » ne doit pas matcher
    assert famille('') is None


def test_type_du_rendez_vous():
    assert type_consultation_rdv('Consultation générale') == ('general', 'médecine générale')
    assert type_consultation_rdv('Consultation spécialisée — Cardiologie')[0] == 'cardio'
    assert type_consultation_rdv('Consultation spécialisée — CARDIO')[0] == 'cardio'
    # contrôle / suivi / résultats avec la spécialité choisie dans le motif
    assert type_consultation_rdv('Contrôle — Cardiologie', 'Generaliste')[0] == 'cardio'
    assert type_consultation_rdv('Contrôle / suivi — Médecine générale', 'CARDIOLOGUE')[0] == 'general'
    assert type_consultation_rdv("Résultats d'examens — Rhumatologie")[0] == 'rhumato'
    assert type_consultation_rdv('Suivi médical — Acupuncture')[0] == type_consultation_acte('Consultation acupuncture')
    # contrôle sans spécialité dans le motif : celle du médecin
    assert type_consultation_rdv('Contrôle', 'RHUMATOLOGUE')[0] == 'rhumato'
    assert type_consultation_rdv('Contrôle / suivi', None)[0] == 'general'
    # spécialité inconnue des familles : clé de repli commune au motif et à l'acte
    assert type_consultation_rdv('Consultation spécialisée — Acupuncture')[0] == type_consultation_acte('Consultation acupuncteur')
    # pas une consultation : rien à afficher
    assert type_consultation_rdv('Vaccination') is None
    assert type_consultation_rdv('Prise de sang', 'CARDIOLOGIE') is None
    assert type_consultation_rdv('') is None


def test_type_de_l_acte_vendu():
    assert type_consultation_acte('S100 Consultation medecine generale') == 'general'
    assert type_consultation_acte('Consultation') == 'general'
    assert type_consultation_acte('S101 Consultation CARDIOLOGIQUE') == 'cardio'
    assert type_consultation_acte('R828 CRP quantitative') is None


def test_meme_type_dans_le_delai_sans_frais():
    rdv = date(2026, 10, 20)
    prec = [(date(2026, 10, 10), 'general', 'vente')]
    r = evaluer(rdv, 'general', 'médecine générale', 15, prec)
    assert r['doit_payer'] is False and r['jours_ecoules'] == 10 and r['badge'] == 'Sans frais'
    assert '10/10/2026' in r['texte'] and 'SANS FRAIS' in r['texte']


def test_limite_du_delai():
    rdv = date(2026, 10, 20)
    assert evaluer(rdv, 'general', 'médecine générale', 15, [(date(2026, 10, 5), 'general', 'vente')])['doit_payer'] is False  # 15e jour
    r = evaluer(rdv, 'general', 'médecine générale', 15, [(date(2026, 10, 4), 'general', 'vente')])  # 16 jours
    assert r['doit_payer'] is True and 'plus de 15 jours' in r['texte'] and '04/10/2026' in r['texte']
    # structure publique : 30 jours
    assert evaluer(rdv, 'general', 'médecine générale', 30, [(date(2026, 10, 4), 'general', 'vente')])['doit_payer'] is False


def test_autre_type_de_consultation_a_payer():
    rdv = date(2026, 10, 20)
    r = evaluer(rdv, 'cardio', 'cardiologie', 15, [(date(2026, 10, 15), 'rhumato', 'vente')])
    assert r['doit_payer'] is True and r['date_reference'] is None and 'nouvelle consultation (cardiologie)' in r['texte']


def test_la_plus_recente_compte_et_le_futur_est_ignore():
    rdv = date(2026, 10, 20)
    prec = [(date(2026, 9, 1), 'general', 'vente'), (date(2026, 10, 12), 'general', 'rdv'), (date(2026, 10, 25), 'general', 'vente')]
    r = evaluer(rdv, 'general', 'médecine générale', 15, prec)
    assert r['doit_payer'] is False and r['date_reference'] == '2026-10-12' and r['source_reference'] == 'rdv'


def test_consultations_depuis_ventes():
    ventes = [
        _Vente(datetime(2026, 10, 7, 16, 21), [{'nom': 'S101 Consultation CARDIOLOGIQUE'}, {'nom': 'R828 CRP'}]),
        _Vente(datetime(2026, 10, 6, 9, 0), '[{"nom": "S100 Consultation medecine generale"}]'),
        _Vente(datetime(2026, 10, 5, 9, 0), [{'nom': 'Consultation'}], statut='annulee'),
    ]
    assert consultations_depuis_ventes(ventes) == [(date(2026, 10, 7), 'cardio', 'vente'), (date(2026, 10, 6), 'general', 'vente')]
