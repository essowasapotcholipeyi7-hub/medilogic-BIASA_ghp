import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config

class DatabaseHelper:
    def __init__(self):
        self.conn = None
        self.connect()
    
    def connect(self):
        try:
            self.conn = psycopg2.connect(Config.DATABASE_URL)
            self.conn.autocommit = True
            print("✅ Connexion à PostgreSQL (Neon) réussie !")
        except Exception as e:
            print(f"⚠️ Erreur connexion PostgreSQL: {e}")
    
    def execute_query(self, query, params=None):
        try:
            if self.conn is None or self.conn.closed:
                self.connect()
            
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                
                if 'RETURNING' in query.upper() or query.upper().strip().startswith('SELECT'):
                    result = cur.fetchall()
                    self.conn.commit()  # 🔥 AJOUTE CETTE LIGNE !
                    return result
                else:
                    self.conn.commit()
                    return True
                
        except Exception as e:
            print(f"❌ Erreur requête: {e}")
            if self.conn:
                self.conn.rollback()
            return []
    
    def get_patients(self, structure_id):
        return self.execute_query("""
            SELECT id, nom, prenom, telephone, adresse, date_naissance,
                   type_assurance, taux_prise_charge, numero_assure
            FROM patients 
            WHERE structure_id = %s 
            ORDER BY id
        """, (structure_id,))

db = DatabaseHelper()