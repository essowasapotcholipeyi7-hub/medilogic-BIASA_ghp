# test_automatisation.py
from app import app
from scripts.traiter_ventes import traiter_une_vente
from scripts.generer_ecritures import creer_ecriture_vente
from models import Vente

with app.app_context():
    # ⭐ Tester sur une vente spécifique
    vente_id = 123  # Mets l'ID d'une vente existante
    vente = Vente.query.get(vente_id)
    
    if vente:
        print(f"📋 Traitement de la vente #{vente_id}")
        traiter_une_vente(vente)
        creer_ecriture_vente(vente)
        print("✅ Terminé !")