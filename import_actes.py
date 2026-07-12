from app import app, db
import json

with app.app_context():
    result = db.execute_query("""
        INSERT INTO ventes (patient_id, patient_nom, structure_id, type, 
                           sous_total, prise_en_charge, net_a_payer, 
                           mode_paiement, taux_assurance, date_vente, actes)
        VALUES (2, 'TEST FINAL', 1, 'actes', 10000, 8000, 2000, 'especes', 80, NOW(), %s::jsonb)
        RETURNING id
    """, (json.dumps([{"nom": "Test Final", "prix": 10000, "quantite": 1, "total": 10000}]),))
    
    print(f"ID inséré: {result}")
    
    # Vérifier
    check = db.execute_query("SELECT id, type FROM ventes WHERE id = %s", (result[0]['id'],))
    print(f"Vérification: {check}")