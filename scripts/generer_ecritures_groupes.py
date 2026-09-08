# scripts/generer_ecritures_groupes.py
# ============================================================
# GÉNÉRATION DES ÉCRITURES COMPTABLES GROUPÉES PAR TYPE
# ============================================================

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date
from app import app, db
from models import Vente, EcritureComptable, LigneEcriture, CompteComptable
from utils.categorisation import COMPTE_PAR_CATEGORIE
from sqlalchemy import text
from decimal import Decimal
from collections import defaultdict


def to_float(valeur):
    """Convertit une valeur en float"""
    if valeur is None:
        return 0.0
    if isinstance(valeur, Decimal):
        return float(valeur)
    try:
        return float(valeur)
    except (ValueError, TypeError):
        return 0.0


def generer_ecritures_groupes():
    """
    Génère des écritures GROUPÉES PAR TYPE
    """
    with app.app_context():
        print("🚀 Génération des écritures comptables GROUPÉES PAR TYPE...")
        
        # ⭐ Récupérer les ventes non traitées
        result = db.session.execute(text("""
            SELECT * FROM ventes 
            WHERE traite_comptable = TRUE 
            AND ecriture_generee = FALSE 
            AND type = 'actes'
        """))
        
        ventes = result.fetchall()
        total_ventes = len(ventes)
        print(f"📊 {total_ventes} ventes à regrouper")
        
        if total_ventes == 0:
            print("✅ Aucune vente à traiter")
            return
        
        # ⭐ Grouper par date
        ventes_par_date = defaultdict(list)
        
        for vente in ventes:
            vente_dict = dict(vente._mapping) if hasattr(vente, '_mapping') else dict(vente)
            date_vente = vente_dict.get('date_vente')
            
            if date_vente:
                if isinstance(date_vente, date):
                    date_str = date_vente.strftime('%Y-%m-%d')
                else:
                    date_str = date_vente.split(' ')[0] if ' ' in str(date_vente) else str(date_vente)
            else:
                date_str = date.today().strftime('%Y-%m-%d')
            
            ventes_par_date[date_str].append(vente_dict)
        
        print(f"📅 {len(ventes_par_date)} jours de ventes à regrouper")
        
        # ⭐ Pour chaque date, créer une écriture groupée
        for date_str, ventes_jour in ventes_par_date.items():
            try:
                creer_ecriture_groupee(date_str, ventes_jour, len(ventes_jour))
            except Exception as e:
                print(f"❌ Erreur pour le {date_str}: {e}")
                db.session.rollback()
        
        print("✅ Génération des écritures groupées terminée")


# scripts/generer_ecritures_groupes.py (CORRIGÉ)

def creer_ecriture_groupee(date_str, ventes_jour, nb_ventes):
    """
    Crée une écriture groupée pour un jour donné
    """
    from datetime import datetime
    
    print(f"\n📝 Création des écritures groupées pour le {date_str} ({nb_ventes} ventes)")
    
    structure_id = ventes_jour[0].get('structure_id', 1)
    date_vente = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    # ⭐ Récupérer les comptes
    compte_caisse = get_compte_cached(structure_id, '211')
    compte_clients = get_compte_cached(structure_id, '411')
    
    # ⭐ Initialiser les totaux
    total_caisse_effective = 0.0  # ⭐ Ce qui reste vraiment en caisse
    total_assurances = defaultdict(float)
    total_ventes_par_categorie = defaultdict(float)
    total_clients = 0.0  # Restes à payer (dettes)
    total_remboursements = 0.0  # ⭐ UNIQUEMENT pour les trop-perçus réels
    
    # ⭐ Détails
    dettes_details = []
    remboursements_details = []
    
    # ⭐ Parcourir toutes les ventes du jour
    for vente in ventes_jour:
        montant_donne = to_float(vente.get('montant_donne'))
        rendu = to_float(vente.get('rendu'))
        prise_en_charge = to_float(vente.get('prise_en_charge'))
        net_a_payer = to_float(vente.get('net_a_payer'))
        assurance = vente.get('assurance', '')
        patient_nom = vente.get('patient_nom', 'Patient')
        vente_id = vente.get('id')
        
        # ⭐⭐⭐ POINT CLÉ : Montant effectif = ce qui reste en caisse ⭐⭐⭐
        montant_effectif = montant_donne - rendu
        
        # ⭐ Caisse : montant effectif (après rendu de monnaie)
        if montant_effectif > 0:
            total_caisse_effective += montant_effectif
        
        # ⭐ Assurances
        if assurance and assurance != 'non_assure' and prise_en_charge > 0:
            total_assurances[assurance] += prise_en_charge
        
        # ⭐ Reste à payer (dette client)
        reste_a_payer = net_a_payer - montant_effectif
        if reste_a_payer > 0:
            total_clients += reste_a_payer
            dettes_details.append({
                'id': vente_id,
                'patient': patient_nom,
                'montant': reste_a_payer
            })
        elif reste_a_payer < 0:
            # ⭐ CAS RARE : trop-perçu (patient a trop payé et n'a pas pris la monnaie)
            trop_percu = abs(reste_a_payer)
            total_remboursements += trop_percu
            remboursements_details.append({
                'id': vente_id,
                'patient': patient_nom,
                'montant': trop_percu
            })
        
        # ⭐ Ventes par catégorie
        actes = vente.get('categorie_actes', [])
        if isinstance(actes, str):
            try:
                actes = json.loads(actes) if actes else []
            except:
                actes = []
        
        for acte in actes:
            if isinstance(acte, dict):
                categorie = acte.get('categorie', 'autres')
                total_acte = to_float(acte.get('total', 0))
                total_ventes_par_categorie[categorie] += total_acte
    
    # ⭐ Créer l'écriture
    ecriture = EcritureComptable(
        structure_id=structure_id,
        date_ecriture=date_vente,
        libelle=f"Ventes du {date_vente.strftime('%d/%m/%Y')} - {nb_ventes} ventes",
        statut='brouillon',
        created_by_nom='SYSTEME_GROUPE'
    )
    db.session.add(ecriture)
    db.session.flush()
    
    total_debit = 0.0
    total_credit = 0.0
    lignes_ajoutees = []
    
    # ⭐ 1. Débit : Caisse (MONTANT EFFECTIF après rendu)
    if total_caisse_effective > 0 and compte_caisse:
        ligne = LigneEcriture(
            ecriture_id=ecriture.id,
            compte_id=compte_caisse.id,
            debit=total_caisse_effective,
            credit=0,
            libelle="Encaissements (net)"
        )
        db.session.add(ligne)
        total_debit += total_caisse_effective
        lignes_ajoutees.append((f'Caisse (net)', total_caisse_effective))
    
    # ⭐ 2. Débit : Assurances
    for assurance, montant in total_assurances.items():
        if montant > 0:
            compte_assurance = get_compte_assurance_cached(assurance, structure_id)
            if compte_assurance:
                ligne = LigneEcriture(
                    ecriture_id=ecriture.id,
                    compte_id=compte_assurance.id,
                    debit=montant,
                    credit=0,
                    libelle=f"{get_libelle_assurance(assurance)} à recevoir"
                )
                db.session.add(ligne)
                total_debit += montant
                lignes_ajoutees.append((f'Assurance {assurance}', montant))
    
    # ⭐ 3. Débit : Clients (restes à payer)
    if total_clients > 0 and compte_clients:
        ligne = LigneEcriture(
            ecriture_id=ecriture.id,
            compte_id=compte_clients.id,
            debit=total_clients,
            credit=0,
            libelle="Créances clients"
        )
        db.session.add(ligne)
        total_debit += total_clients
        lignes_ajoutees.append(('Clients (créances)', total_clients))
    
    # ⭐ 4. Crédit : Ventes par catégorie
    for categorie, montant in total_ventes_par_categorie.items():
        if montant > 0:
            compte = get_compte_cached(structure_id, COMPTE_PAR_CATEGORIE.get(categorie, '718'))
            if compte:
                ligne = LigneEcriture(
                    ecriture_id=ecriture.id,
                    compte_id=compte.id,
                    debit=0,
                    credit=montant,
                    libelle=f"Ventes {categorie}"
                )
                db.session.add(ligne)
                total_credit += montant
                lignes_ajoutees.append((f'Ventes {categorie}', montant))
    
    # ⭐ 5. Crédit : Remboursements (UNIQUEMENT si trop-perçu réel)
    if total_remboursements > 0 and compte_caisse:
        ligne = LigneEcriture(
            ecriture_id=ecriture.id,
            compte_id=compte_caisse.id,
            debit=0,
            credit=total_remboursements,
            libelle="Remboursements à faire"
        )
        db.session.add(ligne)
        total_credit += total_remboursements
        lignes_ajoutees.append(('Remboursements', total_remboursements))
    
    print(f"📊 Débit total: {total_debit:.2f}, Crédit total: {total_credit:.2f}")
    
    # ⭐ 6. Équilibrage
    diff = total_credit - total_debit
    
    if abs(diff) > 0.01:
        print(f"⚠️ Écart détecté: {abs(diff):.2f} FCFA")
        
        if diff > 0 and compte_clients:
            ligne = LigneEcriture(
                ecriture_id=ecriture.id,
                compte_id=compte_clients.id,
                debit=diff,
                credit=0,
                libelle="Ajustement créances"
            )
            db.session.add(ligne)
            total_debit += diff
            lignes_ajoutees.append(('Ajustement clients', diff))
    
    # ⭐ Vérification finale
    if abs(total_debit - total_credit) > 0.01:
        db.session.rollback()
        raise Exception(f"Écriture déséquilibrée: Débit={total_debit:.2f}, Crédit={total_credit:.2f}")
    
    # ⭐ Commentaire des dettes
    if dettes_details:
        commentaire = "Détails des créances : "
        commentaire += ", ".join([f"{d['patient']} ({d['montant']:.0f} FCFA)" for d in dettes_details[:5]])
        if len(dettes_details) > 5:
            commentaire += f" et {len(dettes_details)-5} autre(s)"
        ecriture.commentaire = commentaire
        db.session.commit()
    
    # ⭐ Marquer les ventes comme générées
    for vente in ventes_jour:
        db.session.execute(text("""
            UPDATE ventes 
            SET ecriture_generee = TRUE, 
                ecriture_id = :ecriture_id 
            WHERE id = :id
        """), {"id": vente['id'], "ecriture_id": ecriture.id})
    
    db.session.commit()
    print(f"✅ Écriture groupée créée (ID: {ecriture.id})")
    
    # ⭐ Récapitulatif
    print(f"\n📋 Récapitulatif:")
    for lib, montant in lignes_ajoutees:
        print(f"   {lib}: {montant:.2f} FCFA")
    print(f"   Total Débit: {total_debit:.2f} FCFA")
    print(f"   Total Crédit: {total_credit:.2f} FCFA")
    if dettes_details:
        print(f"   📋 {len(dettes_details)} client(s) avec créance")
    if remboursements_details:
        print(f"   💰 {len(remboursements_details)} client(s) avec trop-perçu")


# ============================================================
# CACHE DES COMPTES
# ============================================================

_compte_cache = {}

def get_compte_cached(structure_id, numero):
    """Récupère un compte avec cache"""
    key = f"{structure_id}_{numero}"
    if key not in _compte_cache:
        compte = CompteComptable.query.filter_by(
            structure_id=structure_id,
            numero=numero
        ).first()
        _compte_cache[key] = compte
    return _compte_cache[key]


def get_compte_assurance_cached(type_assurance, structure_id):
    """Récupère le compte assurance avec cache"""
    assurance = str(type_assurance).lower().strip()
    
    if 'amu' in assurance:
        if 'cnss' in assurance:
            numero = '4111'
        elif 'inam' in assurance:
            numero = '4112'
        else:
            numero = '4119'
    else:
        COMPTE_ASSURANCE = {
            'gta': '4119', 'sunu': '4119', 'fidelia': '4119',
            'nsia': '4119', 'gca': '4119', 'c2a': '4119', 'olea': '4119'
        }
        numero = COMPTE_ASSURANCE.get(assurance, '4119')
    
    return get_compte_cached(structure_id, numero)


def get_libelle_assurance(type_assurance):
    """Retourne le libellé d'une assurance"""
    assurance = str(type_assurance).lower().strip()
    
    if 'amu' in assurance:
        if 'cnss' in assurance:
            return 'AMU-CNSS'
        elif 'inam' in assurance:
            return 'AMU-INAM'
        else:
            return 'AMU'
    
    LIBELLE = {
        'gta': 'GTA', 'sunu': 'SUNU', 'fidelia': 'FIDELIA',
        'nsia': 'NSIA', 'gca': 'GCA', 'c2a': 'C2A', 'olea': 'OLEA'
    }
    return LIBELLE.get(assurance, 'Autre assurance')
# scripts/generer_ecritures_groupes.py (ajout à la fin)

def mettre_a_jour_ecriture_groupee(vente_id):
    """
    Met à jour ou crée l'écriture groupée pour une vente
    """
    from app import app
    from sqlalchemy import text
    
    with app.app_context():
        try:
            # ⭐ Récupérer la vente
            result = db.session.execute(text("""
                SELECT * FROM ventes WHERE id = :id
            """), {"id": vente_id})
            
            vente = result.fetchone()
            if not vente:
                print(f"❌ Vente #{vente_id} non trouvée")
                return
            
            vente_dict = dict(vente._mapping)
            date_vente = vente_dict.get('date_vente')
            
            if date_vente:
                if isinstance(date_vente, date):
                    date_str = date_vente.strftime('%Y-%m-%d')
                else:
                    date_str = date_vente.split(' ')[0] if ' ' in str(date_vente) else str(date_vente)
            else:
                date_str = date.today().strftime('%Y-%m-%d')
            
            # ⭐ Récupérer toutes les ventes du même jour (non regroupées)
            result2 = db.session.execute(text("""
                SELECT * FROM ventes 
                WHERE traite_comptable = TRUE 
                AND ecriture_generee = FALSE 
                AND type = 'actes'
                AND DATE(date_vente) = :date
            """), {"date": date_str})
            
            ventes_jour = result2.fetchall()
            
            if not ventes_jour:
                print(f"ℹ️ Aucune vente à regrouper pour le {date_str}")
                return
            
            # ⭐ Supprimer l'ancienne écriture groupée si elle existe
            db.session.execute(text("""
                DELETE FROM ecritures_comptables 
                WHERE libelle LIKE :libelle 
                AND date_ecriture = :date
                AND created_by_nom = 'SYSTEME_GROUPE'
            """), {
                "libelle": f"Ventes du {date_str}%",
                "date": date_str
            })
            db.session.commit()
            
            # ⭐ Recréer l'écriture groupée
            ventes_list = [dict(v._mapping) for v in ventes_jour]
            creer_ecriture_groupee(date_str, ventes_list, len(ventes_jour))
            
            print(f"✅ Écriture groupée mise à jour pour le {date_str}")
            
        except Exception as e:
            print(f"❌ Erreur mise à jour écriture groupée: {e}")
            import traceback
            traceback.print_exc()
            db.session.rollback()


if __name__ == "__main__":
    generer_ecritures_groupes()