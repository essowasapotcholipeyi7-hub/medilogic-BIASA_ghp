# generate_api_key.py
from sheets_helper import sheets_helper
import secrets
from datetime import datetime
import sys

def generate_api_key(structure_id=1):
    """Génère une clé API pour une structure"""
    api_key = secrets.token_urlsafe(32)
    
    try:
        sheet_structures = sheets_helper.spreadsheet.worksheet("structures")
        cell = sheet_structures.find(str(structure_id), in_column=1)
        
        if cell:
            row_num = cell.row
            current_row = sheet_structures.row_values(row_num)
            
            while len(current_row) < 15:
                current_row.append('')
            
            current_row[13] = api_key
            current_row[14] = datetime.now().isoformat()
            
            sheet_structures.update(f'A{row_num}:O{row_num}', [current_row])
            
            print(f"✅ Clé API générée pour la structure {structure_id}")
            print(f"🔑 {api_key}")
            return api_key
        else:
            print(f"❌ Structure {structure_id} non trouvée")
            return None
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return None

if __name__ == '__main__':
    structure_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    generate_api_key(structure_id)