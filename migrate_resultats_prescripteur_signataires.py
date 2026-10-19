"""⭐ 2026-10-19 : colonnes resultats_examens.prescripteur (reproposé ensuite) et .signataires (une ou
plusieurs personnes qui signent).
Idempotent. Usage : python migrate_resultats_prescripteur.py"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
with conn, conn.cursor() as cur:
    cur.execute("ALTER TABLE resultats_examens ADD COLUMN IF NOT EXISTS prescripteur VARCHAR(150)")
    cur.execute("ALTER TABLE resultats_examens ADD COLUMN IF NOT EXISTS signataires TEXT")
print('✅ resultats_examens.prescripteur et .signataires prêtes')
