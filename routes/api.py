# -*- coding: utf-8 -*-
import os

from flask import Blueprint, jsonify, session, request, current_app
from models import db, Notification, User
from utils import infer_notification_source, normalize_notification_text, sanitize_notification_link

api_bp = Blueprint('api_bp', __name__)


def _mask_database_uri(uri):
    value = (uri or '').strip()
    if not value or '@' not in value:
        return value
    scheme, rest = value.split('://', 1) if '://' in value else ('', value)
    credentials, host_part = rest.split('@', 1)
    if ':' in credentials:
        username = credentials.split(':', 1)[0]
        masked = f'{username}:***@{host_part}'
    else:
        masked = f'***@{host_part}'
    return f'{scheme}://{masked}' if scheme else masked


def _custom_satellite_storage_meta():
    db_uri = (current_app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip()
    sqlite_path = (current_app.config.get('SQLITE_DB_PATH') or '').strip()
    running_under_passenger = (
        os.environ.get('PC06_PASSENGER') == '1'
        or bool(os.environ.get('PASSENGER_APP_ENV'))
        or bool(os.environ.get('PASSENGER_BASE_URI'))
        or bool(os.environ.get('PASSENGER_SPAWN_METHOD'))
    )
    is_sqlite = db_uri.startswith('sqlite:///')
    backend = 'sqlite' if is_sqlite else ('mysql' if db_uri.startswith(('mysql', 'mysql+pymysql', 'mariadb', 'mariadb+pymysql')) else 'other')
    return {
        'database_uri': db_uri,
        'database_uri_masked': _mask_database_uri(db_uri),
        'sqlite_path': sqlite_path,
        'running_under_passenger': running_under_passenger,
        'backend': backend,
    }


def _ensure_custom_satellite_storage_ready():
    meta = _custom_satellite_storage_meta()
    if meta['running_under_passenger'] and meta['backend'] == 'sqlite':
        raise RuntimeError(
            'Host đang lưu CustomSatellitePoint vào SQLite thay vì database bền vững. '
            'Cần cấu hình DATABASE_URL=mysql://user:password@localhost/db_name, '
            'PC06_DATA_DIR=/home/<cpanel_user>/pc06_data và restart Passenger.'
        )
    return meta

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

@api_bp.route('/api/custom-satellite-points')
def get_custom_satellite_points():
    try:
        from models import CustomSatellitePoint
        meta = _ensure_custom_satellite_storage_ready()
        db.create_all()
        
        points = CustomSatellitePoint.query.all()
        res = {}
        for p in points:
            r_id = p.route_id
            if r_id not in res:
                res[r_id] = []
            res[r_id].append({
                'key': p.key,
                'name': p.name,
                'phone': p.phone,
                'lat': p.lat,
                'lng': p.lng,
                'parentKey': p.parent_key
            })
        return jsonify({
            'pointsByRoute': res,
            'storageBackend': meta['backend'],
            'databaseUriMasked': meta['database_uri_masked'],
            'sqlitePath': meta['sqlite_path'],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/custom-satellite-points', methods=['POST'])
def save_custom_satellite_point():
    try:
        from models import CustomSatellitePoint
        meta = _ensure_custom_satellite_storage_ready()
        db.create_all()
        
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
            
        existing = CustomSatellitePoint.query.filter_by(key=key).first()
        if existing:
            existing.route_id = route_id
            existing.name = name
            existing.phone = phone
            existing.lat = float(lat)
            existing.lng = float(lng)
            existing.parent_key = parent_key
        else:
            new_point = CustomSatellitePoint(
                route_id=route_id,
                key=key,
                name=name,
                phone=phone,
                lat=float(lat),
                lng=float(lng),
                parent_key=parent_key
            )
            db.session.add(new_point)
            
        db.session.commit()
        return jsonify({
            'status': 'success',
            'storageBackend': meta['backend'],
            'databaseUriMasked': meta['database_uri_masked'],
            'sqlitePath': meta['sqlite_path'],
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/custom-satellite-points/delete', methods=['POST'])
def delete_custom_satellite_point():
    try:
        from models import CustomSatellitePoint
        meta = _ensure_custom_satellite_storage_ready()
        db.create_all()
        
        data = request.get_json() or {}
        key = data.get('key')
        if not key:
            return jsonify({'error': 'Missing key'}), 400
            
        existing = CustomSatellitePoint.query.filter_by(key=key).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify({
                'status': 'success',
                'storageBackend': meta['backend'],
                'databaseUriMasked': meta['database_uri_masked'],
                'sqlitePath': meta['sqlite_path'],
            })
        else:
            return jsonify({'error': 'Point not found'}), 404
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/diagnose-db')
def diagnose_db():
    try:
        from models import CustomSatellitePoint
        meta = _custom_satellite_storage_meta()
        
        # 1. Get database URI (mask password)
        db_uri = meta['database_uri']
        masked_uri = meta['database_uri_masked']
        
        # 2. Try to run create_all
        db.create_all()
        
        # 3. Test writing to CustomSatellitePoint
        test_key = "test_diagnose_key"
        CustomSatellitePoint.query.filter_by(key=test_key).delete()
        db.session.commit()
        
        test_point = CustomSatellitePoint(
            route_id="test-route",
            key=test_key,
            name="Test Name",
            phone="0912",
            lat=21.0,
            lng=105.0,
            parent_key="test-parent"
        )
        db.session.add(test_point)
        db.session.commit()
        
        # Query it back
        retrieved = CustomSatellitePoint.query.filter_by(key=test_key).first()
        retrieved_name = retrieved.name if retrieved else None
        
        # Delete it
        if retrieved:
            db.session.delete(retrieved)
            db.session.commit()
        
        return jsonify({
            'status': 'success',
            'database_uri': masked_uri,
            'storage_backend': meta['backend'],
            'sqlite_path': meta['sqlite_path'],
            'running_under_passenger': meta['running_under_passenger'],
            'connection_test': 'passed',
            'retrieved_test_value': retrieved_name,
            'message': 'Database connection and write test passed successfully!'
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return jsonify({
            'status': 'error',
            'database_uri': locals().get('masked_uri', 'unknown'),
            'connection_test': 'failed',
            'error_message': str(e),
            'traceback': error_details
        }), 500


@api_bp.route('/api/resolve-maps-url', methods=['POST'])
def resolve_maps_url():
    import requests
    import re
    
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'status': 'error', 'message': 'Vui lòng cung cấp URL'}), 400
        
    if not url.startswith('http'):
        return jsonify({'status': 'error', 'message': 'URL không hợp lệ'}), 400
        
    try:
        session = requests.Session()
        # DO NOT set a browser User-Agent to make sure Google redirects us to a full maps URL
        current_url = url
        for _ in range(5):
            resp = session.get(current_url, allow_redirects=False, timeout=8)
            loc = resp.headers.get("Location")
            if not loc:
                break
                
            match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", loc)
            if match:
                return jsonify({
                    'status': 'success',
                    'lat': float(match.group(1)),
                    'lng': float(match.group(2))
                })
                
            match_query = re.search(r"[?&](?:query|q)=(-?\d+\.\d+),(-?\d+\.\d+)", loc)
            if match_query:
                return jsonify({
                    'status': 'success',
                    'lat': float(match_query.group(1)),
                    'lng': float(match_query.group(2))
                })
                
            current_url = loc
            
        return jsonify({'status': 'error', 'message': 'Không tìm thấy tọa độ từ link Google Maps này'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Lỗi khi xử lý link: {str(e)}'}), 500

