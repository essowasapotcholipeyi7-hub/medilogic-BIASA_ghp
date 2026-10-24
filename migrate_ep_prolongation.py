"""⭐ 2026-10-24 (patron) : Entente Préalable d'hospitalisation — jours demandés, prolongation, date de
sortie choisie sur le billet :
  demandes_entente_prealable.hospit_jours        jours demandés, prolongations comprises (rappel à l'échéance)
  demandes_entente_prealable.prolongation_de_id  demande prolongée (même séjour)
  demandes_entente_prealable.jours_prolongation  jours ajoutés par la prolongation
  hospitalisations.date_sortie_billet            date de sortie choisie sur le billet avant la clôture
À lancer AVANT de déployer le code qui les lit. Idempotent. Usage : python migrate_ep_prolongation.py"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
with conn, conn.cursor() as cur:
    cur.execute("ALTER TABLE demandes_entente_prealable ADD COLUMN IF NOT EXISTS hospit_jours INTEGER")
    cur.execute("ALTER TABLE demandes_entente_prealable ADD COLUMN IF NOT EXISTS prolongation_de_id INTEGER")
    cur.execute("ALTER TABLE demandes_entente_prealable ADD COLUMN IF NOT EXISTS jours_prolongation INTEGER")
    cur.execute("ALTER TABLE hospitalisations ADD COLUMN IF NOT EXISTS date_sortie_billet DATE")
print('✅ Entente Préalable : jours demandés / prolongation, hospitalisations.date_sortie_billet prêts')
