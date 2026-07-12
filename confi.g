import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = 'medilogic-secret-key-2024'
    GOOGLE_SHEETS_CREDENTIALS = 'credentials.json'
    SPREADSHEET_ID = '1yLVp-zwjCFhYx5VZVZN1HXRRgYEyak8kiHHtwWpkLEE'
    ADMIN_EMAIL = 'essowasainfo60@gmail.com'  # ⚠️ REMPLACEZ PAR VOTRE EMAIL