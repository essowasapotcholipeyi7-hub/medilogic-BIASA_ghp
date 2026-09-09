-- ============================================================
-- MIGRATION PRODUCTION (Neon) — Comptabilité SYSCOHADA + Paie RH
-- ============================================================
-- Script idempotent : peut être relancé sans risque si une partie a déjà
-- été appliquée. Aucun DROP, aucune suppression de données.
-- Faites une sauvegarde (branche Neon ou export) avant de lancer, comme
-- toujours avant une migration de schéma.
-- ============================================================


-- ----------------------------------------------------------
-- 0) Anomalies, immobilisations/amortissements, provisions créances
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomalies_comptables (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    source_type VARCHAR(50),
    source_id INTEGER,
    message TEXT NOT NULL,
    date_creation TIMESTAMP DEFAULT NOW(),
    resolu BOOLEAN DEFAULT FALSE,
    resolu_par VARCHAR(100),
    date_resolution TIMESTAMP,
    commentaire TEXT
);
CREATE INDEX IF NOT EXISTS idx_anomalies_structure ON anomalies_comptables(structure_id, resolu);

CREATE TABLE IF NOT EXISTS immobilisations (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    designation VARCHAR(255) NOT NULL,
    categorie VARCHAR(100),
    compte_immo_numero VARCHAR(20) NOT NULL,
    compte_amort_numero VARCHAR(20) NOT NULL,
    date_acquisition DATE NOT NULL,
    valeur_acquisition NUMERIC NOT NULL DEFAULT 0,
    valeur_residuelle NUMERIC DEFAULT 0,
    duree_annees INTEGER NOT NULL DEFAULT 5,
    statut VARCHAR(20) DEFAULT 'en_service',
    date_cession DATE,
    valeur_cession NUMERIC,
    cumul_amorti NUMERIC DEFAULT 0,
    mode_paiement VARCHAR(50) DEFAULT 'especes',
    ecriture_acquisition_id INTEGER,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_immobilisations_structure ON immobilisations(structure_id);

CREATE TABLE IF NOT EXISTS dotations_amortissement (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    immobilisation_id INTEGER NOT NULL REFERENCES immobilisations(id),
    annee INTEGER NOT NULL,
    montant NUMERIC NOT NULL,
    date_generation TIMESTAMP DEFAULT NOW(),
    ecriture_id INTEGER,
    created_by VARCHAR(100),
    UNIQUE(immobilisation_id, annee)
);
CREATE INDEX IF NOT EXISTS idx_dotations_structure_annee ON dotations_amortissement(structure_id, annee);

CREATE TABLE IF NOT EXISTS provisions_creances (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    facture_id INTEGER,
    patient_id INTEGER,
    patient_nom VARCHAR(255),
    montant_creance NUMERIC NOT NULL,
    taux_provision NUMERIC NOT NULL DEFAULT 50,
    montant_provisionne NUMERIC NOT NULL,
    statut VARCHAR(20) DEFAULT 'active',
    ecriture_provision_id INTEGER,
    ecriture_reprise_id INTEGER,
    date_creation TIMESTAMP DEFAULT NOW(),
    date_cloture TIMESTAMP,
    created_by VARCHAR(100),
    commentaire TEXT
);
CREATE INDEX IF NOT EXISTS idx_provisions_structure ON provisions_creances(structure_id, statut);


-- ----------------------------------------------------------
-- 1) Colonnes d'automatisation sur ecritures_comptables
-- ----------------------------------------------------------
ALTER TABLE ecritures_comptables ADD COLUMN IF NOT EXISTS journal_code VARCHAR(10);
ALTER TABLE ecritures_comptables ADD COLUMN IF NOT EXISTS source_type VARCHAR(50);
ALTER TABLE ecritures_comptables ADD COLUMN IF NOT EXISTS source_id INTEGER;
ALTER TABLE ecritures_comptables ADD COLUMN IF NOT EXISTS generation_erreur TEXT;
ALTER TABLE ecritures_comptables ADD COLUMN IF NOT EXISTS generee_auto BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_ecritures_journal_code ON ecritures_comptables(journal_code);
CREATE INDEX IF NOT EXISTS idx_ecritures_source ON ecritures_comptables(source_type, source_id);


-- ----------------------------------------------------------
-- 1bis) Multi-comptes bancaires pour le rapprochement
-- ----------------------------------------------------------
ALTER TABLE releves_bancaires ADD COLUMN IF NOT EXISTS compte_id INTEGER
    REFERENCES comptes_comptables(id);
CREATE INDEX IF NOT EXISTS idx_releves_compte ON releves_bancaires(compte_id);


-- ----------------------------------------------------------
-- 2) structure_id sur permissions (cohérence multi-structure)
-- ----------------------------------------------------------
ALTER TABLE permissions ADD COLUMN IF NOT EXISTS structure_id INTEGER;

UPDATE permissions p SET structure_id = e.structure_id
FROM employes e
WHERE p.employe_id = e.id AND p.structure_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_permissions_structure ON permissions(structure_id);


-- ----------------------------------------------------------
-- 3) Paramétrage de paie (taux CNSS / INAM / IRPP, éditables)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS parametrage_paie (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL UNIQUE,
    taux_cnss_salarial NUMERIC DEFAULT 4.0,
    taux_cnss_patronal NUMERIC DEFAULT 17.5,
    plafond_cnss NUMERIC DEFAULT 600000,
    taux_inam_salarial NUMERIC DEFAULT 3.5,
    taux_inam_patronal NUMERIC DEFAULT 3.5,
    tranches_irpp JSONB,
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by VARCHAR(100)
);


-- ----------------------------------------------------------
-- 4) Bulletins de paie
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS paies (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    employe_id INTEGER NOT NULL REFERENCES employes(id),
    annee INTEGER NOT NULL,
    mois INTEGER NOT NULL,
    salaire_base NUMERIC DEFAULT 0,
    primes NUMERIC DEFAULT 0,
    indemnites NUMERIC DEFAULT 0,
    salaire_brut NUMERIC DEFAULT 0,
    cnss_salarial NUMERIC DEFAULT 0,
    cnss_patronal NUMERIC DEFAULT 0,
    inam_salarial NUMERIC DEFAULT 0,
    inam_patronal NUMERIC DEFAULT 0,
    irpp NUMERIC DEFAULT 0,
    total_retenues NUMERIC DEFAULT 0,
    total_charges_patronales NUMERIC DEFAULT 0,
    net_a_payer NUMERIC DEFAULT 0,
    statut VARCHAR(20) DEFAULT 'brouillon',
    mode_paiement VARCHAR(50) DEFAULT 'especes',
    date_paiement DATE,
    depense_id INTEGER,
    ecriture_id INTEGER,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(employe_id, annee, mois)
);

CREATE INDEX IF NOT EXISTS idx_paies_structure ON paies(structure_id);
CREATE INDEX IF NOT EXISTS idx_paies_periode ON paies(structure_id, annee, mois);


-- ----------------------------------------------------------
-- 5) Correctif critique : séquences d'auto-incrément manquantes
-- ----------------------------------------------------------
-- Sur la base locale, depenses/factures/paiements_factures (+ proformas_lunettes,
-- même bug, sans lien avec ce chantier mais corrigé au passage) n'avaient
-- AUCUN auto-increment sur leur id (INSERT sans id explicite -> erreur). Ce
-- bloc vérifie et corrige uniquement les tables concernées, sans rien
-- changer si une séquence existe déjà (donc sans danger si la prod est saine).
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['depenses', 'factures', 'paiements_factures', 'proformas_lunettes']
    LOOP
        BEGIN
            IF pg_get_serial_sequence(tbl, 'id') IS NULL THEN
                EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I_id_seq OWNED BY %I.id', tbl, tbl);
                EXECUTE format(
                    'SELECT setval(%L, COALESCE((SELECT MAX(id) FROM %I), 0) + 1, false)',
                    tbl || '_id_seq', tbl
                );
                EXECUTE format('ALTER TABLE %I ALTER COLUMN id SET DEFAULT nextval(%L)', tbl, tbl || '_id_seq');
                RAISE NOTICE 'Sequence creee pour %', tbl;
            ELSE
                RAISE NOTICE 'Sequence deja presente pour % — rien a faire', tbl;
            END IF;
        EXCEPTION WHEN OTHERS THEN
            -- Ne bloque pas les autres tables (ex: probleme de propriétaire
            -- sur une table donnée) — à corriger à la main si ce message
            -- apparaît sur une table qui vous importe.
            RAISE NOTICE 'Impossible de corriger % : %', tbl, SQLERRM;
        END;
    END LOOP;
END $$;


-- ----------------------------------------------------------
-- Vérification finale (à lire après exécution)
-- ----------------------------------------------------------
SELECT table_name, column_name, column_default
FROM information_schema.columns
WHERE column_name = 'id' AND table_name IN ('depenses', 'factures', 'paiements_factures', 'proformas_lunettes')
ORDER BY table_name;

-- ----------------------------------------------------------
-- APRÈS ce script : relancez scripts/seed_plan_comptable_syscohada.py
-- (ou cliquez "Initialiser" dans l'onglet Plan comptable) pour créer les
-- nouveaux comptes 491, 651, 6591, 7591 nécessaires aux provisions pour
-- créances douteuses — sinon ils se créent automatiquement au premier
-- usage, mais n'apparaîtront pas tout de suite dans les listes déroulantes.
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 6) Société souscriptrice de l'assurance complémentaire
-- ----------------------------------------------------------
-- Une assurance complémentaire (GTA, SUNU, NSIA...) est en général un
-- contrat groupe souscrit par un employeur pour ses salariés. On mémorise
-- désormais cette société : sur le patient (valeur courante), sur chaque
-- vente (instantané au moment de la vente, même logique que
-- assurance2_nom/taux_assurance2), et dans une table de référence qui sert
-- à l'autocomplétion ("saisie une fois, choix ensuite").
ALTER TABLE patients ADD COLUMN IF NOT EXISTS societe_assurance2 VARCHAR(150);
ALTER TABLE ventes ADD COLUMN IF NOT EXISTS societe_assurance2 VARCHAR(150);

CREATE TABLE IF NOT EXISTS societes_assurance (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL REFERENCES structures(id),
    assurance_nom VARCHAR(100) NOT NULL,
    nom_societe VARCHAR(150) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_societe_assurance UNIQUE (structure_id, assurance_nom, nom_societe)
);
CREATE INDEX IF NOT EXISTS idx_societes_assurance_lookup ON societes_assurance (structure_id, assurance_nom);
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 7) Génération des factures assurance : ventilation par société
-- ----------------------------------------------------------
-- La génération mensuelle des factures assurance (onglet "Assurances")
-- regroupait tout le monde sous le seul nom de la compagnie complémentaire
-- (ex: "GTA"), sans distinguer les sociétés souscriptrices. On ajoute la
-- colonne pour générer une facture distincte par société sous la même
-- compagnie (ex: GTA/SOTOCO et GTA/TOGOCEL séparément).
ALTER TABLE factures_assurance ADD COLUMN IF NOT EXISTS societe VARCHAR(150);
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 8) Garde-fou : DEFAULT NOW() sur patients.created_at
-- ----------------------------------------------------------
-- Sur la base locale de dev, cette colonne n'avait AUCUN default au niveau
-- de la table (contrairement à Neon, qui l'a déjà) : les patients créés
-- via l'INSERT applicatif (qui ne listait pas created_at) restaient donc
-- avec created_at = NULL, et les statistiques "aujourd'hui / cette semaine
-- / ce mois / cette année" de la page Patients affichaient zéro malgré des
-- patients bien enregistrés. Corrigé aussi côté application (l'INSERT
-- fixe désormais explicitement created_at = NOW()) ; cette ligne est un
-- filet de sécurité si la table est recréée sans le default. Sans effet
-- sur Neon (default déjà présent).
ALTER TABLE patients ALTER COLUMN created_at SET DEFAULT NOW();
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 9) Paie complète Togo : profils Public/Privé, AMU verrouillée, IRPP
-- ----------------------------------------------------------
-- Remplace le paramétrage générique CNSS/INAM par les deux profils réels
-- (privé -> CNSS + AMU-CNSS ; public -> CRT + AMU-INAM), le verrouillage de
-- l'AMU (décret n°2023-096/PR : part salarié <= moitié du taux global, part
-- employeur >= moitié), le nouveau barème IRPP annuel, l'abattement
-- forfaitaire plafonné, la déduction pour personnes à charge, et les
-- dérogations individuelles par salarié (prêts/acomptes/autres retenues,
-- taux personnalisés). paies et parametrage_paie sont vides à ce stade
-- (fonctionnalité non encore utilisée en production) : uniquement des
-- colonnes ADDITIONNELLES ci-dessous, les anciennes colonnes générique
-- (cnss_salarial, inam_salarial, taux_inam_salarial...) restent en place,
-- inutilisées, par sécurité (aucun DROP).

-- Employés : profil de paie individuel
ALTER TABLE employes ADD COLUMN IF NOT EXISTS secteur_paie VARCHAR(10) DEFAULT 'prive';
ALTER TABLE employes ADD COLUMN IF NOT EXISTS personnes_a_charge INTEGER DEFAULT 0;
ALTER TABLE employes ADD COLUMN IF NOT EXISTS taux_retraite_salarial_override NUMERIC;
ALTER TABLE employes ADD COLUMN IF NOT EXISTS taux_retraite_patronal_override NUMERIC;
ALTER TABLE employes ADD COLUMN IF NOT EXISTS taux_amu_salarial_override NUMERIC;
ALTER TABLE employes ADD COLUMN IF NOT EXISTS taux_amu_patronal_override NUMERIC;

-- Paramétrage structure : profils CNSS (privé) / CRT (public) + AMU commune
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS taux_crt_salarial NUMERIC DEFAULT 7.0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS taux_crt_patronal NUMERIC DEFAULT 20.0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS plafond_crt NUMERIC DEFAULT 0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS amu_taux_global NUMERIC DEFAULT 10.0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS taux_amu_salarial_defaut NUMERIC DEFAULT 5.0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS taux_amu_patronal_defaut NUMERIC DEFAULT 5.0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS taux_formation_pro NUMERIC DEFAULT 0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS abattement_taux NUMERIC DEFAULT 28.0;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS abattement_plafond_annuel NUMERIC DEFAULT 10000000;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS deduction_personne_charge NUMERIC DEFAULT 10000;
ALTER TABLE parametrage_paie ADD COLUMN IF NOT EXISTS max_personnes_charge INTEGER DEFAULT 6;
ALTER TABLE parametrage_paie ALTER COLUMN plafond_cnss SET DEFAULT 0;

-- Bulletins de paie : détail complet par ligne + instantané du profil
ALTER TABLE paies ADD COLUMN IF NOT EXISTS secteur VARCHAR(10);
ALTER TABLE paies ADD COLUMN IF NOT EXISTS organisme_retraite VARCHAR(10);
ALTER TABLE paies ADD COLUMN IF NOT EXISTS organisme_amu VARCHAR(20);
ALTER TABLE paies ADD COLUMN IF NOT EXISTS taux_retraite_salarial NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS taux_retraite_patronal NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS retraite_salarial NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS retraite_patronal NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS taux_amu_salarial NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS taux_amu_patronal NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS amu_salarial NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS amu_patronal NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS formation_pro NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS salaire_brut_imposable NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS personnes_a_charge INTEGER DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS abattement NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS deduction_charges_familiales NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS revenu_net_imposable NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS prets_deduction NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS acomptes_deduction NUMERIC DEFAULT 0;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS autres_retenues JSON DEFAULT '[]';
ALTER TABLE paies ADD COLUMN IF NOT EXISTS autres_retenues_total NUMERIC DEFAULT 0;
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 10) Plan comptable OHADA adapté à la paie (CNSS/CRT, AMU-CNSS/AMU-INAM)
-- ----------------------------------------------------------
-- Le moteur de paie utilisait au départ des comptes génériques et
-- partiellement incorrects au regard du plan OHADA :
--   - 664/6641 pour les charges sociales patronales : 664 désigne en
--     réalité les rémunérations du personnel EXTÉRIEUR (intérimaires),
--     pas les charges sociales — corrigé vers la classe 666 dédiée.
--   - 431/432/433/434 réutilisés indifféremment pour CNSS ou CRT, AMU-CNSS
--     ou AMU-INAM selon le salarié — un même compte "CNSS" recevait donc
--     aussi bien les cotisations d'un agent public. Remplacé par un compte
--     dédié par organisme (comme pour les assurances 411211/411221...).
--   - Le compte 421 initialement prévu pour "Personnel — avances et
--     acomptes" (prêts/acomptes sur salaire) s'est révélé DÉJÀ utilisé par
--     plusieurs structures pour "Fournisseurs" — déplacé vers 4211 pour
--     éviter toute collision.
-- utils/plan_comptable_syscohada.py définit désormais les bons numéros
-- (4211, 4311-4319, 6661-6665) ; ce bloc désactive uniquement les ANCIENS
-- comptes 431/432/433/434/664/6641 qui ne sont référencés par AUCUNE
-- écriture (vérifié avant désactivation, ci-dessous) — les écritures déjà
-- passées avec ces numéros restent intactes et lisibles, seule la création
-- de NOUVELLES écritures avec ces anciens numéros est désormais évitée.
UPDATE comptes_comptables cc
SET actif = FALSE
WHERE cc.numero IN ('431', '432', '433', '434', '664', '6641')
AND NOT EXISTS (SELECT 1 FROM lignes_ecritures le WHERE le.compte_id = cc.id);
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 11) Pointage par empreinte (WebAuthn) — tables additives
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS empreintes_employes (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    employe_id INTEGER NOT NULL REFERENCES employes(id),
    credential_id TEXT NOT NULL UNIQUE,
    public_key TEXT NOT NULL,
    sign_count INTEGER DEFAULT 0,
    libelle_appareil VARCHAR(100),
    actif BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    derniere_utilisation TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parametrage_pointage (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL UNIQUE,
    heure_debut TIME DEFAULT '08:00',
    heure_fin TIME DEFAULT '17:00',
    tolerance_retard_minutes INTEGER DEFAULT 10,
    jours_travailles JSON DEFAULT '[0,1,2,3,4,5]',
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pointages (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    employe_id INTEGER NOT NULL REFERENCES employes(id),
    date_jour DATE NOT NULL,
    heure_arrivee TIME,
    methode_arrivee VARCHAR(20),
    statut_arrivee VARCHAR(20),
    retard_minutes INTEGER DEFAULT 0,
    heure_depart TIME,
    methode_depart VARCHAR(20),
    depart_anticipe BOOLEAN DEFAULT FALSE,
    duree_travaillee_minutes INTEGER,
    commentaire TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_pointage_employe_jour UNIQUE (employe_id, date_jour)
);
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 12) Pointage par reconnaissance faciale (complément à l'empreinte)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS visages_employes (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    employe_id INTEGER NOT NULL REFERENCES employes(id),
    descripteur JSON NOT NULL,
    libelle VARCHAR(100),
    actif BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    derniere_utilisation TIMESTAMP
);
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 13) Pièces justificatives du remboursement assurance (traçabilité)
-- ----------------------------------------------------------
ALTER TABLE factures_assurance
    ADD COLUMN IF NOT EXISTS numero_reference_versement VARCHAR(100),
    ADD COLUMN IF NOT EXISTS date_versement DATE;
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 14) Miroir protocoles/ordonnances-types/examens-types synchronisés
--     depuis gestion_patients (voir /api/protocoles/sync-externe)
-- ----------------------------------------------------------
ALTER TABLE protocoles_medicaux
    ADD COLUMN IF NOT EXISTS source_app VARCHAR(30),
    ADD COLUMN IF NOT EXISTS source_model VARCHAR(30),
    ADD COLUMN IF NOT EXISTS source_id INTEGER,
    ADD COLUMN IF NOT EXISTS source_synced_at TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS idx_protocoles_medicaux_source
    ON protocoles_medicaux (structure_id, source_app, source_model, source_id)
    WHERE source_app IS NOT NULL;
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 15) Comptes de tiers fournisseurs (401/4011) — jusqu'ici définis dans le
--     plan comptable mais jamais alimentés (toute dépense était traitée
--     comme payée cash immédiatement). Achat à crédit = charge reconnue
--     tout de suite (Débit charge / Crédit 401), caisse impactée seulement
--     au règlement (Débit 401 / Crédit trésorerie).
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS fournisseurs (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    nom VARCHAR(255) NOT NULL,
    telephone VARCHAR(50),
    email VARCHAR(255),
    adresse TEXT,
    actif BOOLEAN DEFAULT TRUE,
    created_by INTEGER,
    created_by_nom VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fournisseurs_structure ON fournisseurs(structure_id, actif);

CREATE TABLE IF NOT EXISTS achats_fournisseurs (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL,
    fournisseur_id INTEGER NOT NULL REFERENCES fournisseurs(id),
    montant_total NUMERIC NOT NULL,
    montant_paye NUMERIC DEFAULT 0,
    motif VARCHAR(255) NOT NULL,
    motif_personnalise VARCHAR(255),
    description TEXT,
    date_achat TIMESTAMP DEFAULT NOW(),
    date_echeance DATE,
    statut VARCHAR(20) DEFAULT 'a_regler',
    ecriture_id INTEGER,
    created_by INTEGER,
    created_by_nom VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_achats_fournisseurs_structure ON achats_fournisseurs(structure_id, statut);
CREATE INDEX IF NOT EXISTS idx_achats_fournisseurs_fournisseur ON achats_fournisseurs(fournisseur_id);

CREATE TABLE IF NOT EXISTS reglements_fournisseurs (
    id SERIAL PRIMARY KEY,
    achat_id INTEGER NOT NULL REFERENCES achats_fournisseurs(id),
    fournisseur_id INTEGER NOT NULL REFERENCES fournisseurs(id),
    montant NUMERIC NOT NULL,
    date_reglement TIMESTAMP DEFAULT NOW(),
    mode_paiement VARCHAR(50) DEFAULT 'especes',
    reference VARCHAR(255),
    notes TEXT,
    ecriture_id INTEGER,
    created_by INTEGER,
    created_by_nom VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_reglements_fournisseurs_achat ON reglements_fournisseurs(achat_id);

ALTER TABLE depenses ADD COLUMN IF NOT EXISTS fournisseur_id INTEGER REFERENCES fournisseurs(id);
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 16) Non-mélange des journaux SYSCOHADA (VTE conservé, ajout du journal
--     SAL et TR) : chaque opération payée immédiatement (vente, paie)
--     génère désormais DEUX écritures distinctes — la reconnaissance
--     (VTE/SAL) et le mouvement de trésorerie réel (CAI/BQ) — au lieu
--     d'une seule écriture mélangeant les deux. Colonnes de traçabilité
--     de la 2e écriture.
-- ----------------------------------------------------------
ALTER TABLE ventes ADD COLUMN IF NOT EXISTS ecriture_encaissement_id INTEGER;
ALTER TABLE paies ADD COLUMN IF NOT EXISTS ecriture_paiement_id INTEGER;
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- 17) Comptes à 8 chiffres (harmonisation SYSCOHADA) + correction des noms
--     mal étiquetés. Chaque numéro court du plan (401, 4111, 411211...) est
--     complété à droite par des zéros jusqu'à 8 chiffres (401 -> 40100000).
--     ⚠️ À exécuter avec le script Python dédié (pas ce fichier seul) — la
--     logique distingue les comptes SYSCOHADA légitimes (renumérotés +
--     nom corrigé) des comptes ad-hoc hérités AMBIGUS qui partagent le même
--     numéro court qu'un compte SYSCOHADA différent (ex: '611' = "Salaires"
--     dans l'ancien plan ad-hoc vs "Transports sur achats/ventes" dans le
--     plan SYSCOHADA actuel) : ces derniers sont uniquement DÉSACTIVÉS
--     (actif=FALSE), jamais renommés/renumérotés, pour ne jamais mélanger
--     ou effacer leur historique réel (vérifié : des écritures existantes
--     leur sont réellement rattachées, contrairement à ce que supposait la
--     note de la section "Numéros de comptes de l'ancien plan ad-hoc" plus
--     haut dans ce fichier). Voir la table MAPPING et l'ensemble AMBIGUOUS
--     dans le commit correspondant (services/comptabilite_service.py /
--     utils/plan_comptable_syscohada.py) pour la correspondance complète
--     ancien numéro -> (nouveau numéro, nom de référence).
-- ----------------------------------------------------------
