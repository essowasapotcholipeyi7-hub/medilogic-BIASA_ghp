"""Accueil en libre-service (patron, 2026-10-21) : services proposés au patient (tirés du catalogue) et file
d'attente qui numérote les tickets (par motif, et par service pour une consultation ou un contrôle)."""
from services.accueil_service import services_de_consultation, file_attente


def test_services_tires_des_consultations_du_catalogue():
    actes = ['S100 Consultation medecine Generale', 'S101 Consultation specialisee (CARDIOLOGIE)',
             'S101 Consultation specialisee(RHUMATOLOGIE )', 'S101 Consultation specialisee (UROLOGIQUE)',
             'S101 Consultation specialisee', "S112 Consultation specialisee interne (en cours d'hospitalisation)",
             'S102 Consultation en pediatrie (Enfants 0 a 05 ans)', 'S111 Consultation en pediatrie (Enfants 05 ans et plus)',
             'S115 Consultation prenatale (y compris les supports)', 'Consultation specialisee programmee (Professeur)',
             'Consultation kinesitherapie (avec maximum de 4 seances sauf entente prealable)',
             'R607 Hemogramme(NFS Complete)', 'S101 Consultation specialisee (ORL)']
    assert services_de_consultation(actes) == ['Médecine générale', 'Cardiologie', 'Consultation prénatale', 'ORL',
                                               'Pédiatrie', 'Rhumatologie', 'Urologie']
    assert services_de_consultation([]) == []


def test_file_attente_par_motif_et_service():
    assert file_attente('controle', 'Cardiologie') == 'Contrôle — Cardiologie'
    assert file_attente('consultation', 'Rhumatologie') == 'Consultation — Rhumatologie'
    assert file_attente('controle', 'Cardiologie') != file_attente('controle', 'Rhumatologie')
    # pas de service pour un résultat ou un examen : une file par motif
    assert file_attente('resultat_analyse', 'Cardiologie') == "Résultat d'analyse"
    assert file_attente('realisation_examen') == "Réalisation d'examen"
    assert file_attente('autre') == file_attente('n importe quoi') == 'Autre motif'
