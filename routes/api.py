# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, session, request
from models import db, Notification, User
from utils import infer_notification_source, normalize_notification_text, sanitize_notification_link

api_bp = Blueprint('api_bp', __name__)

@api_bp.route('/api/notifications')
def get_notifications():
    if not session.get('uid'): return jsonify([])
    notifs = Notification.query.filter_by(user_id=session['uid']).order_by(Notification.created_at.desc()).limit(40).all()
    res = []
    for n in notifs:
        source_info = infer_notification_source(n.title, n.msg, n.link)
        if source_info['code'] not in {'task', 'news', 'library', 'report'}:
            continue
        res.append({
            'id': n.id,
            'title': normalize_notification_text(n.title, max_length=255),
            'msg': normalize_notification_text(n.msg, max_length=1000),
            'link': sanitize_notification_link(n.link),
            'is_read': n.is_read or False,
            'time': n.created_at.strftime('%H:%M %d/%m/%Y'),
            'source': source_info['code'],
            'source_label': source_info['label'],
            'source_icon': source_info['icon'],
            'source_class': source_info['class_name'],
        })
        if len(res) >= 10:
            break
    return jsonify(res)

@api_bp.route('/api/notifications/read', methods=['POST'])
def mark_all_read():
    if not session.get('uid'): return jsonify({'status': 'error'}), 401
    Notification.query.filter_by(user_id=session['uid']).update({'is_read': 1})
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/api/performance-stats')
def get_perf_stats():
    return jsonify({'full_list': []})


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
    from models import Category
    
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
    from models import Category
    
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
    from models import Category
    
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
            {
                'id': item.id,
                'code': item.code,
                'name': item.name,
                'value': (item.code or item.name or '').strip(),
                'stable_value': f'category_item:{item.id}',
            }
            for item in items
        ]
    })


# ==================== CUSTOM SATELLITE POINTS API ====================
import os
import sqlite3

def get_db_connection():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pc06_system.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_custom_satellite_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_satellite_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            phone TEXT,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            parent_key TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

@api_bp.route('/api/custom-satellite-points')
def get_custom_satellite_points():
    try:
        init_custom_satellite_table()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT route_id, key, name, phone, lat, lng, parent_key FROM custom_satellite_points')
        rows = cursor.fetchall()
        conn.close()
        
        res = {}
        for row in rows:
            r_id = row['route_id']
            if r_id not in res:
                res[r_id] = []
            res[r_id].append({
                'key': row['key'],
                'name': row['name'],
                'phone': row['phone'],
                'lat': row['lat'],
                'lng': row['lng'],
                'parentKey': row['parent_key']
            })
        return jsonify(res)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/custom-satellite-points', methods=['POST'])
def save_custom_satellite_point():
    try:
        init_custom_satellite_table()
        data = request.get_json() or {}
        route_id = data.get('route_id')
        key = data.get('key')
        name = data.get('name')
        phone = data.get('phone')
        lat = data.get('lat')
        lng = data.get('lng')
        parent_key = data.get('parentKey')
        
        if not route_id or not key or not name or lat is None or lng is None or not parent_key:
            return jsonify({'error': 'Missing required fields'}), 400
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO custom_satellite_points (route_id, key, name, phone, lat, lng, parent_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (route_id, key, name, phone, lat, lng, parent_key))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/custom-satellite-points/delete', methods=['POST'])
def delete_custom_satellite_point():
    try:
        init_custom_satellite_table()
        data = request.get_json() or {}
        key = data.get('key')
        if not key:
            return jsonify({'error': 'Missing key'}), 400
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM custom_satellite_points WHERE key = ?', (key,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

