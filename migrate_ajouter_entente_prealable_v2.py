"""Migration ponctuelle : ajoute les colonnes manquantes à
"demandes_entente_prealable" pour couvrir les 3 tableaux de la fiche
officielle (Actes, Produits, Hospitalisation) et le choix explicite du
régime AMU — voir models.py, DemandeEntentePrealable, et le plan de
session "Entente Préalable (EP)". Patron : "les tableaux ont trois
tableaux : acte, produit et hospitalisation... jusqu'alors tu n'as pas
permis qu'on saisisse motif... on doit pouvoir choisir EP hospitalisation".

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : aucune donnée
existante touchée, sans risque à relancer par erreur. Relâche aussi la
contrainte NOT NULL sur lignes_motif (une demande peut maintenant ne
contenir QUE de l'hospitalisation, sans aucune ligne acte/produit).

Usage :
    python migrate_ajouter_entente_prealable_v2.py
"""
import io
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import app
from models import db

with app.app_context():
    db.session.execute(db.text('''
        ALTER TABLE demandes_entente_prealable
            ADD COLUMN IF NOT EXISTS inclure_actes BOOLEAN DEFAULT false,
            ADD COLUMN IF NOT EXISTS inclure_produits BOOLEAN DEFAULT false,
            ADD COLUMN IF NOT EXISTS inclure_hospitalisation BOOLEAN DEFAULT false,
            ADD COLUMN IF NOT EXISTS hospit_date_admission DATE,
            ADD COLUMN IF NOT EXISTS hospit_motif TEXT,
            ADD COLUMN IF NOT EXISTS hospit_categorie_salle VARCHAR(20),
            ADD COLUMN IF NOT EXISTS hospit_categorie_autre_precision VARCHAR(255),
            ADD COLUMN IF NOT EXISTS hospit_duree_sejour VARCHAR(100)
    '''))
    db.session.execute(db.text(
        'ALTER TABLE demandes_entente_prealable ALTER COLUMN lignes_motif DROP NOT NULL'
    ))
    # ⭐ Les demandes déjà créées avant cette migration contenaient
    # forcément des actes/produits (l'hospitalisation n'existait pas
    # encore) : on les marque explicitement inclure_actes/inclure_produits
    # selon leur contenu réel, pour que l'historique affiche correctement
    # les anciennes lignes.
    db.session.execute(db.text('''
        UPDATE demandes_entente_prealable
        SET inclure_actes = EXISTS (
                SELECT 1 FROM jsonb_array_elements(lignes_motif::jsonb) l WHERE l->>'type' = 'acte'
            ),
            inclure_produits = EXISTS (
                SELECT 1 FROM jsonb_array_elements(lignes_motif::jsonb) l WHERE l->>'type' = 'produit'
            )
        WHERE lignes_motif IS NOT NULL AND inclure_actes IS NOT TRUE AND inclure_produits IS NOT TRUE
    '''))
    db.session.commit()
    print('OK : colonnes Actes/Produits/Hospitalisation ajoutées à "demandes_entente_prealable".')
