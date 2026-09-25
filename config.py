import os
from dotenv import load_dotenv

load_dotenv()

def _url_postgres_generique(url):
    """Schéma bare 'postgresql://...' (sans pilote précisé) — c'est ce que
    comprend psycopg2.connect() en DSN brut (db_helper.py,
    import_produits.py). Neon/Render fournissent parfois un préfixe
    différent (postgres://, postgresql+psycopg://...) : on le ramène
    toujours à ce format générique."""
    if not url or '://' not in url:
        return url
    schema, reste = url.split('://', 1)
    if schema.startswith('postgres'):
        return 'postgresql://' + reste
    return url


def _url_postgres_pour_sqlalchemy(url):
    """⭐⭐ Un simple 'postgresql://...' (sans pilote précisé) NE SUFFIT PLUS
    depuis SQLAlchemy 2.1 — vérifié en reproduisant exactement le crash en
    local : SQLAlchemy 2.1 choisit par défaut le pilote 'psycopg' (v3, PAS
    installé, seul psycopg2-binary l'est) même pour une URL bare
    'postgresql://', alors qu'avant (2.0.x) c'était psycopg2 par défaut.
    SQLAlchemy n'étant pas épinglé dans requirements.txt, Render installe
    la dernière version disponible au moment du build, qui peut changer de
    comportement sans prévenir. On force donc EXPLICITEMENT
    'postgresql+psycopg2://...' pour TOUT ce qui passe par SQLAlchemy —
    jamais pour du psycopg2.connect() brut (voir _url_postgres_generique
    ci-dessus), qui ne comprend pas ce préfixe ('+psycopg2' est une
    convention SQLAlchemy, pas une syntaxe DSN standard)."""
    url = _url_postgres_generique(url)
    if not url or '://' not in url:
        return url
    return 'postgresql+psycopg2://' + url.split('://', 1)[1]


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'medilogic-secret-key-2024')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'essowasainfo60@gmail.com')

    # ⭐ Base de données — schéma générique, pour psycopg2.connect() en DSN
    # brut (db_helper.py, import_produits.py).
    DATABASE_URL = _url_postgres_generique(os.getenv('DATABASE_URL'))

    # ⭐ SQLAlchemy — schéma avec pilote explicite (voir
    # _url_postgres_pour_sqlalchemy), PAS le même que DATABASE_URL
    # ci-dessus.
    SQLALCHEMY_DATABASE_URI = _url_postgres_pour_sqlalchemy(os.getenv('DATABASE_URL')) or 'postgresql+psycopg2://...'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ⭐ Bascule hors-ligne (voir utils/db_failover.py) : n'existe que si
    # DATABASE_URL_LOCAL est définie (jamais le cas sur Render) — sinon
    # aucun changement de comportement.
    _DATABASE_URL_LOCAL = _url_postgres_pour_sqlalchemy(os.getenv('DATABASE_URL_LOCAL'))
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