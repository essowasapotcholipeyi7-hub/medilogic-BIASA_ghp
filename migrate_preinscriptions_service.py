"""⭐ 2026-10-21 : préinscriptions (accueil en libre-service) — sexe, âge, service de la visite et file d'attente
(numéro d'ordre compté par motif / service). Idempotent. Usage : python migrate_preinscriptions_service.py"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
with conn, conn.cursor() as cur:
    cur.execute("ALTER TABLE preinscriptions_patients ADD COLUMN IF NOT EXISTS sexe VARCHAR(1)")
    cur.execute("ALTER TABLE preinscriptions_patients ADD COLUMN IF NOT EXISTS age INTEGER")
    cur.execute("ALTER TABLE preinscriptions_patients ADD COLUMN IF NOT EXISTS service_visite VARCHAR(100)")
    cur.execute("ALTER TABLE preinscriptions_patients ADD COLUMN IF NOT EXISTS file_attente VARCHAR(150)")
print('✅ preinscriptions_patients.sexe, .age, .service_visite et .file_attente prêtes')
