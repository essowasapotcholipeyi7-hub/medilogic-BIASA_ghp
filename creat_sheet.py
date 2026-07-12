import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key('1yLVp-zwjCFhYx5VZVZN1HXRRgYEyak8kiHHtwWpkLEE')

# Pour chaque structure de 1 à 20
for struct_id in range(1, 21):
    print(f"\n📝 Structure {struct_id}...")
    
    # 1. Ajouter les actes
    sheet_name = f"struct_{struct_id}_actes"
    try:
        sheet = spreadsheet.worksheet(sheet_name)
        
        # Vérifier si déjà des données
        existing = sheet.get_all_records()
        if len(existing) == 0:
            actes_catalogue = [
                [1, "Consultation générale", 5000, "Consultation médicale générale", struct_id],
                [2, "Consultation spécialiste", 10000, "Consultation avec spécialiste", struct_id],
                [3, "Échographie", 15000, "Échographie abdominale", struct_id],
                [4, "Analyse sanguine", 8000, "Bilan sanguin complet", struct_id],
                [5, "Radiographie", 12000, "Radio pulmonaire", struct_id],
                [6, "IRM", 50000, "Imagerie par résonance magnétique", struct_id],
                [7, "Scanner", 40000, "Tomodensitométrie", struct_id],
                [8, "ECG", 10000, "Électrocardiogramme", struct_id],
                [9, "Test COVID", 6000, "Test antigénique", struct_id],
                [10, "Vaccination", 8000, "Vaccin contre la fièvre typhoïde", struct_id]
            ]
            
            for acte in actes_catalogue:
                sheet.append_row(acte)
            print(f"   ✅ 10 actes ajoutés pour struct_{struct_id}")
        else:
            print(f"   ⚠️ Actes déjà présents pour struct_{struct_id}")
    except Exception as e:
        print(f"   ❌ Erreur actes: {e}")
    
    time.sleep(0.3)
    
    # 2. Ajouter les produits
    sheet_name = f"struct_{struct_id}_produits"
    try:
        sheet = spreadsheet.worksheet(sheet_name)
        
        existing = sheet.get_all_records()
        if len(existing) == 0:
            produits_catalogue = [
                [1, "Paracétamol 500mg", 500, 100, struct_id],
                [2, "Amoxicilline 500mg", 1500, 50, struct_id],
                [3, "Vitamine C 1000mg", 800, 200, struct_id],
                [4, "Ibuprofène 400mg", 1000, 75, struct_id],
                [5, "Aspirine 100mg", 600, 120, struct_id],
                [6, "Tramadol 50mg", 2000, 30, struct_id],
                [7, "Metformine 500mg", 1200, 60, struct_id],
                [8, "Oméprazole 20mg", 900, 80, struct_id]
            ]
            
            for produit in produits_catalogue:
                sheet.append_row(produit)
            print(f"   ✅ 8 produits ajoutés pour struct_{struct_id}")
        else:
            print(f"   ⚠️ Produits déjà présents pour struct_{struct_id}")
    except Exception as e:
        print(f"   ❌ Erreur produits: {e}")
    
    time.sleep(0.3)

print("\n" + "=" * 50)
print("🎉 Toutes les données ont été ajoutées !")
print("=" * 50)