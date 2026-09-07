# utils/structure_info.py
# ============================================================
# Coordonnées de la structure (nom, adresse, téléphone, logo) pour l'en-tête
# des documents imprimables (reçus, factures, bordereaux, déclarations...).
# ============================================================
# ⭐ La table Postgres `structures` n'est qu'un stub utilisé pour les
# relations (FK) — les vraies coordonnées de la structure sont dans Google
# Sheets. Voir le bug corrigé sur le bordereau assurance : l'en-tête restait
# vide tant que cette fonction n'existait pas et qu'on lisait Postgres.

from models import Structure


def get_structure_info(structure_id):
    """Retourne un dict {nom, adresse, telephone, email, logo_url} — depuis
    Google Sheets en priorité (source de vérité), avec repli Postgres si
    Sheets est indisponible."""
    try:
        from sheets_helper import sheets_helper
        structures = sheets_helper.get_all_records('structures', use_prefix=False)
        info = next((s for s in structures if str(s.get('ID')) == str(structure_id)), None)
        if info:
            return {
                'nom': info.get('nom', ''),
                'adresse': info.get('adresse', ''),
                'telephone': info.get('telephone', ''),
                'email': info.get('email', ''),
                'logo_url': info.get('logo_url', ''),
            }
    except Exception as e:
        print(f"⚠️ get_structure_info (Sheets): {e}")

    s = Structure.query.get(structure_id)
    if s:
        return {'nom': s.nom, 'adresse': s.adresse, 'telephone': s.telephone,
                'email': s.email, 'logo_url': s.logo_url}
    return {}
