# ============================================================
# ROUTES POUR LE JOURNAL DES MOUVEMENTS
# ============================================================

from flask import Blueprint, request, jsonify, render_template, session
from functools import wraps
from datetime import datetime, date, timedelta
from services.journal_service import JournalService

journal_bp = Blueprint('journal', __name__, url_prefix='/journal')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Non autorisé'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================
# PAGE PRINCIPALE
# ============================================================

@journal_bp.route('')
@login_required
def page_journal():
    """Page du journal des mouvements"""
    categories = JournalService.CATEGORIES
    today = date.today()
    
    return render_template(
        'journal.html',
        categories=categories,
        today=today.isoformat()
    )

# ============================================================
# API: LISTE DES MOUVEMENTS
# ============================================================

@journal_bp.route('/api/liste', methods=['GET'])
@login_required
def api_liste_mouvements():
    """API: Liste des mouvements avec filtres"""
    structure_id = session.get('structure_id')
    
    categorie = request.args.get('categorie')
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    search = request.args.get('search')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    date_debut = None
    date_fin = None
    
    if date_debut_str:
        try:
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    if date_fin_str:
        try:
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    mouvements, total, stats = JournalService.get_liste(
        structure_id=structure_id,
        categorie=categorie,
        date_debut=date_debut,
        date_fin=date_fin,
        search=search,
        limit=limit,
        offset=offset
    )
    
    return jsonify({
        'success': True,
        'data': [m.to_dict() for m in mouvements],
        'total': total,
        'stats': stats,
        'limit': limit,
        'offset': offset
    })

# ============================================================
# API: STATISTIQUES PAR CATÉGORIE
# ============================================================

@journal_bp.route('/api/stats', methods=['GET'])
@login_required
def api_stats_categories():
    """API: Statistiques par catégorie"""
    structure_id = session.get('structure_id')
    
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    
    date_debut = None
    date_fin = None
    
    if date_debut_str:
        try:
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    if date_fin_str:
        try:
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    stats = JournalService.get_categories_stats(
        structure_id=structure_id,
        date_debut=date_debut,
        date_fin=date_fin
    )
    
    return jsonify({
        'success': True,
        'data': stats
    })

# ============================================================
# API: DÉTAILS D'UN MOUVEMENT
# ============================================================

@journal_bp.route('/api/<int:mouvement_id>', methods=['GET'])
@login_required
def api_get_mouvement(mouvement_id):
    """API: Récupérer un mouvement par son ID"""
    structure_id = session.get('structure_id')
    
    mouvement = JournalService.get_par_id(mouvement_id, structure_id)
    if not mouvement:
        return jsonify({'success': False, 'error': 'Mouvement non trouvé'}), 404
    
    return jsonify({'success': True, 'data': mouvement.to_dict()})

# ============================================================
# API: EXPORT CSV
# ============================================================

@journal_bp.route('/api/export', methods=['GET'])
@login_required
def api_export_csv():
    """API: Exporter les mouvements en CSV"""
    structure_id = session.get('structure_id')
    
    categorie = request.args.get('categorie')
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')
    search = request.args.get('search')
    
    date_debut = None
    date_fin = None
    
    if date_debut_str:
        try:
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    if date_fin_str:
        try:
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    mouvements, total, stats = JournalService.get_liste(
        structure_id=structure_id,
        categorie=categorie,
        date_debut=date_debut,
        date_fin=date_fin,
        search=search,
        limit=10000,
        offset=0
    )
    
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    # En-têtes
    writer.writerow(['Date', 'Catégorie', 'Description', 'Patient', 'Utilisateur', 'Montant', 'Type'])
    
    for m in mouvements:
        writer.writerow([
            m.date_mouvement.strftime('%d/%m/%Y %H:%M') if m.date_mouvement else '',
            m.get_categorie_label(),
            m.description or '',
            m.patient_nom or '',
            m.utilisateur_nom or '',
            f"{abs(float(m.montant)):,.0f}" if m.montant else '0',
            m.type_montant or 'neutre'
        ])
    
    csv_content = output.getvalue()
    output.close()
    
    return jsonify({
        'success': True,
        'csv': csv_content,
        'filename': f"journal_mouvements_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    })