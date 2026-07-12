from app import app
from models import Patient
from flask import session

with app.app_context():
    # 1. Voir tous les patients en base
    print("👥 Tous les patients:")
    for p in Patient.query.all():
        print(f"  - ID: {p.id}, Nom: {p.nom}, Structure: {p.structure_id}")
    
    # 2. Voir la session (si tu es connecté)
    # print("Session:", dict(session))