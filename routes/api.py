from flask import Blueprint, jsonify, session
from models import db, Notification, ReportData, User
import json, random
from datetime import datetime

api_bp = Blueprint('api_bp', __name__)

@api_bp.route('/api/notifications')
def get_notifications():
    if not session.get('uid'): return jsonify([])
    notifs = Notification.query.filter_by(user_id=session['uid']).order_by(Notification.created_at.desc()).limit(10).all()
    res = []
    for n in notifs:
        res.append({
            'id': n.id,
            'title': n.title,
            'msg': n.msg,
            'link': n.link,
            'is_read': n.is_read or False,
            'time': n.created_at.strftime('%H:%M %d/%m/%Y')
        })
    return jsonify(res)

@api_bp.route('/api/notifications/read', methods=['POST'])
def mark_all_read():
    if not session.get('uid'): return jsonify({'status': 'error'}), 401
    Notification.query.filter_by(user_id=session['uid']).update({'is_read': 1})
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/api/performance-stats')
def get_perf_stats():
    # Dynamic ranking logic based on report count per unit
    raw = db.session.query(ReportData, User).join(User, ReportData.user_id == User.id).all()
    units = {}
    for r, u in raw:
        ua = u.unit_area or "Khác"
        units[ua] = units.get(ua, 0) + 1
    
    # Normalize scores for the UI progress bar (max 100)
    max_val = max(units.values()) if units else 1
    ranking = sorted([
        {'name': k, 'score': (v / max_val) * 100 if max_val > 0 else 0} 
        for k, v in units.items()
    ], key=lambda x: x['score'], reverse=True)
    
    return jsonify({'full_list': ranking})


# ==================== CATEGORY API ====================

@api_bp.route('/api/categories')
def get_categories():
    """
    Lấy danh mục tập trung.
    Query params:
        - type: Lọc theo loại (position, unit, district, rank, duty)
        - parent_id: Lọc theo danh mục cha (cho dropdown phụ thuộc)
        - active: Chỉ lấy danh mục active (default: true)
    """
    from models import Category
    
    cat_type = request.args.get('type')
    parent_id = request.args.get('parent_id')
    active_only = request.args.get('active', 'true').lower() != 'false'
    
    query = Category.query
    if active_only:
        query = query.filter_by(is_active=True)
    if cat_type:
        query = query.filter_by(type=cat_type)
    if parent_id:
        query = query.filter_by(parent_id=int(parent_id))
    
    categories = query.order_by(Category.order, Category.name).all()
    
    return jsonify([{
        'id': c.id,
        'code': c.code,
        'name': c.name,
        'type': c.type,
        'parent_id': c.parent_id,
        'has_children': len(c.children) > 0 if c.children else False
    } for c in categories])


@api_bp.route('/api/categories', methods=['POST'])
def create_category():
    """Tạo danh mục mới (Admin only)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    cat = Category(
        code=data.get('code', data['name'].lower().replace(' ', '_')),
        name=data['name'],
        type=data.get('type', 'other'),
        parent_id=data.get('parent_id'),
        order=data.get('order', 0),
        is_active=data.get('is_active', True),
        description=data.get('description', '')
    )
    db.session.add(cat)
    db.session.commit()
    
    return jsonify({'id': cat.id, 'status': 'created'})


@api_bp.route('/api/categories/<int:cid>', methods=['PUT'])
def update_category(cid):
    """Cập nhật danh mục (Admin only)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    cat = Category.query.get_or_404(cid)
    data = request.get_json()
    
    if 'name' in data:
        cat.name = data['name']
    if 'code' in data:
        cat.code = data['code']
    if 'type' in data:
        cat.type = data['type']
    if 'parent_id' in data:
        cat.parent_id = data['parent_id']
    if 'order' in data:
        cat.order = data['order']
    if 'is_active' in data:
        cat.is_active = data['is_active']
    if 'description' in data:
        cat.description = data['description']
    
    db.session.commit()
    return jsonify({'status': 'updated'})


@api_bp.route('/api/categories/<int:cid>', methods=['DELETE'])
def delete_category(cid):
    """Xóa danh mục (Admin only)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    cat = Category.query.get_or_404(cid)
    
    # Không cho xóa nếu có con
    if cat.children:
        return jsonify({'error': 'Cannot delete category with children'}), 400
    
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'status': 'deleted'})
