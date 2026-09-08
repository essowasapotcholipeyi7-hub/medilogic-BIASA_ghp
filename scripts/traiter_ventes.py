# scripts/traiter_ventes.py
# ============================================================
# TRAITEMENT DES VENTES NON CATÉGORISÉES
# ============================================================

import sys
import os

# ⭐ AJOUTER LE CHEMIN DU PROJET
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from app import app, db
from sqlalchemy import text
from utils.categorisation import categoriser_acte


def traiter_une_vente(vente):
    """
    Traite une vente spécifique (pour l'automatisation)
    """
    import json
    
    try:
        # ⭐ Récupérer les actes
        actes = vente.actes if isinstance(vente.actes, list) else []
        
        if not actes:
            vente.traite_comptable = True
            db.session.commit()
            return
        
        # ⭐ Catégoriser chaque acte
        actes_categorises = []
        for acte in actes:
            if isinstance(acte, dict):
                nom = acte.get('nom', '')
                info = categoriser_acte(nom)
                acte['categorie'] = info['categorie']
                acte['compte'] = info['compte']
                acte['code'] = info['code']
                actes_categorises.append(acte)
        
        # ⭐ Mettre à jour la vente
        vente.categorie_actes = actes_categorises
        vente.traite_comptable = True
        db.session.commit()
        
    except Exception as e:
        print(f"❌ Erreur traiter_une_vente: {e}")
        db.session.rollback()
        raise

def traiter_ventes_non_categorisees():
    """
    Traite toutes les ventes non catégorisées
    """
    with app.app_context():
        print("🚀 Début du traitement des ventes...")
        
        # ⭐ Récupérer les ventes non traitées
        result = db.session.execute(text("""
            SELECT * FROM ventes 
            WHERE traite_comptable = FALSE 
            AND type = 'actes'
        """))
        
        ventes = result.fetchall()
        print(f"📊 {len(ventes)} ventes à traiter")
        
        for vente in ventes:
            try:
                traiter_une_vente_sql(vente)
                print(f"✅ Vente #{vente.id} traitée")
            except Exception as e:
                print(f"❌ Erreur vente #{vente.id}: {e}")
                db.session.rollback()
        
        print("✅ Traitement terminé")


def traiter_une_vente_sql(vente):
    """
    Traite une vente spécifique
    """
    vente_dict = dict(vente._mapping) if hasattr(vente, '_mapping') else dict(vente)
    
    # ⭐ Récupérer les actes
    actes_data = vente_dict.get('actes')
    
    if isinstance(actes_data, (list, dict)):
        actes = actes_data
    elif isinstance(actes_data, str):
        try:
            actes = json.loads(actes_data) if actes_data else []
        except json.JSONDecodeError:
            actes = []
    else:
        actes = []
    
    if not actes:
        db.session.execute(text("""
            UPDATE ventes 
            SET traite_comptable = TRUE 
            WHERE id = :id
        """), {"id": vente_dict['id']})
        db.session.commit()
        return
    
    # ⭐ Catégoriser chaque acte
    actes_categorises = []
    for acte in actes:
        if isinstance(acte, dict):
            nom = acte.get('nom', '')
            info = categoriser_acte(nom)
            acte['categorie'] = info['categorie']
            acte['compte'] = info['compte']
            acte['code'] = info['code']
            actes_categorises.append(acte)
    
    # ⭐ Mettre à jour la vente
    db.session.execute(text("""
        UPDATE ventes 
        SET categorie_actes = :categorie_actes, 
            traite_comptable = TRUE 
        WHERE id = :id
    """), {
        "id": vente_dict['id'],
        "categorie_actes": json.dumps(actes_categorises)
    })
    db.session.commit()


def traiter_une_vente_par_id(vente_id):
    """
    Traite une vente spécifique par son ID
    """
    with app.app_context():
        result = db.session.execute(text("""
            SELECT * FROM ventes WHERE id = :id
        """), {"id": vente_id})
        
        vente = result.fetchone()
        if vente:
            traiter_une_vente_sql(vente)
            return True
        return False


if __name__ == "__main__":
    traiter_ventes_non_categorisees()