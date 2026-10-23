"""⭐ 2026-10-23 : méthode de calcul de l'assurance complémentaire quand le patient a aussi l'AMU —
colonne compagnies_complementaires.calcul_complementaire :
  'reste' (défaut) : taux x le plus petit de (son PBR, ce que l'AMU laisse) — patron, d'après un
                     décompte OLEA réel (ECG : CNSS 8 568, reste 6 432, OLEA 80 % = 5 145,6) ;
  'base'           : taux x son PBR, plafonné à ce que l'AMU laisse (ancienne règle du logiciel).
À lancer AVANT de déployer le code qui la lit (le modèle CompagnieComplementaire la lit).
Idempotent. Usage : python migrate_calcul_complementaire.py"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
with conn, conn.cursor() as cur:
    cur.execute("ALTER TABLE compagnies_complementaires ADD COLUMN IF NOT EXISTS calcul_complementaire VARCHAR(10) DEFAULT 'reste'")
    cur.execute("UPDATE compagnies_complementaires SET calcul_complementaire = 'reste' WHERE calcul_complementaire IS NULL")
print('✅ compagnies_complementaires.calcul_complementaire prête')
