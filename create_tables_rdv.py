# Créer un script séparé ou l'exécuter dans le shell Flask
# Fichier: create_tables_rdv.py

import psycopg2
from datetime import datetime

# Configuration de la base de données Neon
DB_CONFIG = {
    'host': 'votre_host_neon',
    'database': 'votre_database',
    'user': 'votre_user',
    'password': 'votre_password',
    'port': 5432
}

def create_tables():
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Créer la table des médecins
        cur.execute("""
            CREATE TABLE IF NOT EXISTS medecins (
                id SERIAL PRIMARY KEY,
                structure_id INTEGER NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
                nom VARCHAR(100) NOT NULL,
                prenom VARCHAR(100),
                titre VARCHAR(20) DEFAULT 'Dr',
                sexe VARCHAR(10),
                date_naissance DATE,
                telephone VARCHAR(20),
                email VARCHAR(100),
                specialite VARCHAR(100) NOT NULL,
                sous_specialite VARCHAR(100),
                numero_ordre VARCHAR(50),
                annees_experience INTEGER,
                honoraire_consultation DECIMAL(10,2) DEFAULT 0,
                honoraire_visite DECIMAL(10,2) DEFAULT 0,
                honoraire_acte DECIMAL(10,2) DEFAULT 0,
                taux_partage DECIMAL(5,2) DEFAULT 0,
                horaire_debut TIME DEFAULT '08:00:00',
                horaire_fin TIME DEFAULT '17:00:00',
                duree_consultation INTEGER DEFAULT 30,
                jours_travail JSONB DEFAULT '["lundi","mardi","mercredi","jeudi","vendredi"]',
                actif BOOLEAN DEFAULT TRUE,
                disponible BOOLEAN DEFAULT TRUE,
                remarques TEXT,
                photo_url VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Créer la table des rendez-vous
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rendez_vous (
                id SERIAL PRIMARY KEY,
                structure_id INTEGER NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
                patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                patient_nom VARCHAR(200) NOT NULL,
                patient_telephone VARCHAR(20),
                patient_email VARCHAR(100),
                medecin_id INTEGER REFERENCES medecins(id) ON DELETE SET NULL,
                date_rdv DATE NOT NULL,
                heure_rdv VARCHAR(10) NOT NULL,
                duree INTEGER DEFAULT 30,
                date_fin TIMESTAMP,
                motif VARCHAR(255) NOT NULL,
                notes TEXT,
                type_consultation VARCHAR(50) DEFAULT 'consultation',
                priorite VARCHAR(20) DEFAULT 'normal',
                statut VARCHAR(20) DEFAULT 'programme',
                rappel_envoye BOOLEAN DEFAULT FALSE,
                date_rappel TIMESTAMP,
                confirme_le TIMESTAMP,
                termine_le TIMESTAMP,
                created_by INTEGER,
                created_by_nom VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Créer la table d'historique des rendez-vous
        cur.execute("""
            CREATE TABLE IF NOT EXISTS historique_rendez_vous (
                id SERIAL PRIMARY KEY,
                rendez_vous_id INTEGER NOT NULL REFERENCES rendez_vous(id) ON DELETE CASCADE,
                action VARCHAR(50) NOT NULL,
                ancien_statut VARCHAR(20),
                nouveau_statut VARCHAR(20),
                anciennes_donnees JSONB,
                nouvelles_donnees JSONB,
                utilisateur_id INTEGER,
                utilisateur_nom VARCHAR(100),
                ip_adresse VARCHAR(50),
                commentaire TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Créer la table des disponibilités
        cur.execute("""
            CREATE TABLE IF NOT EXISTS disponibilites_medecins (
                id SERIAL PRIMARY KEY,
                medecin_id INTEGER NOT NULL REFERENCES medecins(id) ON DELETE CASCADE,
                type VARCHAR(20) NOT NULL,
                date_debut DATE NOT NULL,
                date_fin DATE NOT NULL,
                heure_debut TIME,
                heure_fin TIME,
                motif VARCHAR(255),
                approuve_par VARCHAR(100),
                commentaire TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Créer la table des statistiques
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rendez_vous_stats (
                id SERIAL PRIMARY KEY,
                structure_id INTEGER NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
                medecin_id INTEGER NOT NULL REFERENCES medecins(id) ON DELETE CASCADE,
                mois INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                nb_consultations INTEGER DEFAULT 0,
                nb_consultations_terminees INTEGER DEFAULT 0,
                nb_annulations INTEGER DEFAULT 0,
                nb_absences INTEGER DEFAULT 0,
                total_honoraires DECIMAL(10,2) DEFAULT 0,
                taux_occupation DECIMAL(5,2) DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(medecin_id, mois, annee)
            )
        """)
        
        # Ajouter les index pour les performances
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rendez_vous_date ON rendez_vous(date_rdv)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rendez_vous_statut ON rendez_vous(statut)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rendez_vous_medecin ON rendez_vous(medecin_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rendez_vous_patient ON rendez_vous(patient_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rendez_vous_structure ON rendez_vous(structure_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_medecins_structure ON medecins(structure_id)")
        
        conn.commit()
        print("✅ Tables créées avec succès !")
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    create_tables()