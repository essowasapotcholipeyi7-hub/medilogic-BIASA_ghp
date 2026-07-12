import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

print("=" * 60)
print("🗑️ SUPPRESSION DES FEUILLES DOSSIERS, CONSULTATIONS, PRESCRIPTIONS")
print("=" * 60)

# Connexion
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key('1yLVp-zwjCFhYx5VZVZN1HXRRgYEyak8kiHHtwWpkLEE')

# Liste des types de feuilles à supprimer
types = ['dossiers', 'consultations', 'prescriptions']

total_supprimees = 0

for struct_id in range(1, 21):
    print(f"\n🏥 Structure {struct_id}/20...")
    
    for type_feuille in types:
        sheet_name = f"struct_{struct_id}_{type_feuille}"
        
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
            spreadsheet.del_worksheet(worksheet)
            print(f"   ✅ supprimée: {sheet_name}")
            total_supprimees += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"   ⚠️ {sheet_name} n'existe pas ou erreur: {e}")

print("\n" + "=" * 60)
print(f"🎉 SUPPRESSION TERMINÉE !")
print(f"   📊 Total feuilles supprimées: {total_supprimees}")
print("=" * 60)