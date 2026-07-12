import psycopg2
from config import Config

print("=" * 60)
print("📝 CRÉATION DES PRODUITS DE BASE DANS NEON")
print("=" * 60)

conn = psycopg2.connect(Config.DATABASE_URL)
cur = conn.cursor()

# Supprimer les anciens produits
cur.execute("DELETE FROM produits")
print("🗑️ Anciens produits supprimés")

# Liste des produits de base
produits_base = [
    ("PRD-001", "Paracétamol 500mg", 500, 200, 100, "comprimé", "Antalgique"),
    ("PRD-002", "Amoxicilline 500mg", 1500, 50, 50, "gélule", "Antibiotique"),
    ("PRD-003", "Vitamine C 1000mg", 800, 100, 200, "comprimé", "Vitamine"),
    ("PRD-004", "Ibuprofène 400mg", 1000, 75, 75, "comprimé", "Anti-inflammatoire"),
    ("PRD-005", "Aspirine 100mg", 600, 120, 120, "comprimé", "Antalgique"),
    ("PRD-006", "Tramadol 50mg", 2000, 30, 30, "gélule", "Antalgique"),
    ("PRD-007", "Metformine 500mg", 1200, 60, 60, "comprimé", "Antidiabétique"),
    ("PRD-008", "Oméprazole 20mg", 900, 80, 80, "gélule", "Protecteur gastrique"),
    ("PRD-009", "Spasfon 80mg", 850, 45, 45, "comprimé", "Antispasmodique"),
    ("PRD-010", "Doliprane 1000mg", 750, 150, 150, "comprimé", "Antalgique"),
]

compteur = 0
for structure_id in range(1, 21):
    for produit in produits_base:
        cur.execute("""
            INSERT INTO produits (structure_id, code, nom, prix_vente, prix_achat, 
                                  quantite_stock, seuil_alerte, unite, categorie)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            structure_id,
            produit[0],  # code
            produit[1],  # nom
            produit[2],  # prix_vente
            produit[3],  # prix_achat
            produit[4],  # quantite_stock
            10,          # seuil_alerte
            produit[5],  # unite
            produit[6]   # categorie
        ))
        compteur += 1
    
    print(f"✅ Structure {structure_id}/20 terminée")

conn.commit()
cur.close()
conn.close()

print(f"\n🎉 CRÉATION TERMINÉE !")
print(f"   📊 {len(produits_base)} produits x 20 structures = {compteur} lignes insérées")