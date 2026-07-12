from sheets_helper import sheets_helper
import gspread
from oauth2client.service_account import ServiceAccountCredentials

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key('1yLVp-zwjCFhYx5VZVZN1HXRRgYEyak8kiHHtwWpkLEE')

# Lire directement la feuille
sheet = spreadsheet.worksheet("struct_1_patients")
all_records = sheet.get_all_records()

print(f"📊 Lecture directe: {len(all_records)} patients")
for record in all_records:
    print(record)