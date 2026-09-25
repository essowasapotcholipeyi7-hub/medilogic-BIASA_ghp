import os
from dotenv import load_dotenv

load_dotenv()

def _normaliser_url_postgres(url):
    """Neon/Render fournissent parfois postgresql+psycopg://... (préfixe
    pointant vers psycopg v3) au lieu de postgresql://... — seul
    psycopg2-binary est installé (requirements.txt), pas psycopg v3, donc
    ce préfixe fait planter l'appli au démarrage (ModuleNotFoundError:
    No module named 'psycopg'). On force le schéma générique pour que
    SQLAlchemy choisisse psycopg2 (déjà installé), quel que soit le
    format exact renvoyé par Render/Neon si la chaîne de connexion est
    régénérée plus tard."""
    if url and url.startswith('postgresql+'):
        return 'postgresql://' + url.split('://', 1)[1]
    return url


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'medilogic-secret-key-2024')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'essowasainfo60@gmail.com')

    # ⭐ Base de données (pour SQLAlchemy)
    DATABASE_URL = _normaliser_url_postgres(os.getenv('DATABASE_URL'))

    # ⭐ SQLAlchemy
    SQLALCHEMY_DATABASE_URI = DATABASE_URL or 'postgresql://...'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ⭐ Bascule hors-ligne (voir utils/db_failover.py) : n'existe que si
    # DATABASE_URL_LOCAL est définie (jamais le cas sur Render) — sinon
    # aucun changement de comportement.
    _DATABASE_URL_LOCAL = os.getenv('DATABASE_URL_LOCAL')
    SQLALCHEMY_BINDS = {'local': _DATABASE_URL_LOCAL} if _DATABASE_URL_LOCAL else {}
    
    # ⭐ Google Sheets
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', '1yLVp-zwjCFhYx5VZVZN1HXRRgYEyak8kiHHtwWpkLEE')
    
    # ⭐ WEBHOOK CONFIGURATION
    CONSULTATION_APP_URL = os.getenv('CONSULTATION_APP_URL', 'http://127.0.0.1:5000')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'mon_secret_webhook_123456')
    
    @property
    def WEBHOOK_URL(self):
        return f"{self.CONSULTATION_APP_URL}/api/webhook/patient-created"
    
    @property
    def WEBHOOK_URL(self):
        return f"{self.CONSULTATION_APP_URL}/api/webhook/patient-created"
    
    @property
    def IS_DEVELOPMENT(self):
        return self.FLASK_ENV == 'development'
    
    @property
    def IS_PRODUCTION(self):
        return self.FLASK_ENV == 'production'
    
    # Email configuration
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_USERNAME', '')