"""⭐ 2026-10-19 : colonne parametrage_amu_cnss.type_prestataire (grille d'hospitalisation AMU : CHU, clinique
privée, CHR, hôpital de district, cabinet privé). Idempotent. Usage : python migrate_type_prestataire.py"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
with conn, conn.cursor() as cur:
    cur.execute("ALTER TABLE parametrage_amu_cnss ADD COLUMN IF NOT EXISTS type_prestataire VARCHAR(30)")
print('✅ parametrage_amu_cnss.type_prestataire prête')
