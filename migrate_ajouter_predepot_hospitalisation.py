"""⭐ 2026-10-22 : prédépôt à l'admission en hospitalisation (comme en soins ambulatoires) —
colonnes hospitalisations.predepot_montant, .predepot_mode_paiement, .predepot_note.
À lancer AVANT de déployer le code qui les utilise (le modèle Hospitalisation les lit).
Idempotent. Usage : python migrate_ajouter_predepot_hospitalisation.py"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
with conn, conn.cursor() as cur:
    cur.execute("ALTER TABLE hospitalisations ADD COLUMN IF NOT EXISTS predepot_montant NUMERIC DEFAULT 0")
    cur.execute("ALTER TABLE hospitalisations ADD COLUMN IF NOT EXISTS predepot_mode_paiement VARCHAR(50)")
    cur.execute("ALTER TABLE hospitalisations ADD COLUMN IF NOT EXISTS predepot_note TEXT")
print('✅ hospitalisations.predepot_montant, .predepot_mode_paiement et .predepot_note prêtes')
