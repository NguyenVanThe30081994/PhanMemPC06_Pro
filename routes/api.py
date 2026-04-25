# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, session, request
from models import db, Notification, User

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
    from models_reporting import ReportInstance

    raw = db.session.query(
        ReportInstance.org_unit,
        db.func.count(ReportInstance.id)
    ).filter_by(status='submitted').group_by(ReportInstance.org_unit).all()

    units = {}
    for org_unit, count in raw:
        ua = org_unit or "Khác"
        units[ua] = count
    
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


@api_bp.route('/api/category-picker')
def get_category_picker_bundle():
    if not session.get('uid'):
        return jsonify({'error': 'Unauthorized'}), 401

    from models import CategoryGroup, CategoryItem
    from category_helpers import get_bound_group, get_category_group

    module_code = (request.args.get('module') or '').strip()
    field_code = (request.args.get('field') or '').strip()
    group_code = (request.args.get('group_code') or '').strip()
    group_name = (request.args.get('group_name') or '').strip()
    requested_group_id = request.args.get('group_id', type=int)

    selected_group = None
    if requested_group_id:
        selected_group = CategoryGroup.query.filter_by(id=requested_group_id, is_active=True).first()

    if not selected_group and module_code and field_code:
        selected_group = get_bound_group(module_code, field_code)

    if not selected_group and group_code:
        selected_group = CategoryGroup.query.filter_by(code=group_code, is_active=True).first()

    if not selected_group and group_name:
        selected_group = get_category_group(group_name)

    groups = CategoryGroup.query.filter_by(is_active=True).order_by(
        CategoryGroup.sort_order.asc(),
        CategoryGroup.name.asc()
    ).all()

    items = []
    if selected_group:
        items = CategoryItem.query.filter_by(
            group_id=selected_group.id,
            is_active=True
        ).order_by(
            CategoryItem.sort_order.asc(),
            CategoryItem.name.asc()
        ).all()

    return jsonify({
        'groups': [
            {'id': group.id, 'code': group.code, 'name': group.name}
            for group in groups
        ],
        'selected_group_id': selected_group.id if selected_group else None,
        'selected_group_name': selected_group.name if selected_group else None,
        'items': [
            {'id': item.id, 'code': item.code, 'name': item.name}
            for item in items
        ]
    })
