"""
Phân hệ Sổ Theo Dõi Thời Hạn Hồ Sơ — PhanMemPC06_Pro
Theo dõi thời hạn trả kết quả hồ sơ (Căn cước, cư trú, xác thực ĐA06...).
Cán bộ nhập mã/tên hồ sơ và hạn trả -> Hệ thống cảnh báo Đỏ / Vàng / Xanh.
"""
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify, session, g
from models import db, Dossier, User
from permissions import load_current_authz
from utils import render_auto_template

dossier_bp = Blueprint('dossier_bp', __name__)

REMIND_DAYS_DEFAULT = 2


def _require_login():
    return bool(session.get('uid'))


def _calc_dossier_state(dossier, today):
    """Tính trạng thái cảnh báo trực quan: overdue | soon | pending | done"""
    if dossier.trang_thai == 'da_tra':
        return 'done'
    if not dossier.han_tra:
        return 'pending'
    diff = (dossier.han_tra - today).days
    if diff < 0:
        return 'overdue'
    if diff <= REMIND_DAYS_DEFAULT:
        return 'soon'
    return 'pending'


@dossier_bp.route('/dossiers')
def list_dossiers_page():
    """Giao diện Sổ theo dõi thời hạn hồ sơ."""
    if not _require_login():
        return render_template('login.html')
    authz = load_current_authz()
    return render_auto_template('dossiers.html', is_admin=authz['is_admin'])


@dossier_bp.route('/api/dossiers', methods=['GET'])
def api_list_dossiers():
    """API lấy danh sách hồ sơ và tổng hợp số liệu cảnh báo."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    authz = load_current_authz()
    uid = session.get('uid')
    current_user = db.session.get(User, uid)

    q = Dossier.query

    # Phân quyền: Cán bộ chỉ quản lý hồ sơ đơn vị mình; Admin tỉnh xem được tất cả
    if not authz['is_admin']:
        user_unit = getattr(current_user, 'unit_area', '') or ''
        q = q.filter((Dossier.created_by == uid) | (Dossier.unit_area == user_unit))

    # Bộ lọc tìm kiếm
    search = request.args.get('q', '').strip().lower()
    if search:
        q = q.filter(Dossier.ma_ho_so.ilike(f'%{search}%') | Dossier.ghi_chu.ilike(f'%{search}%'))

    loai_filter = request.args.get('loai', '').strip()
    if loai_filter:
        q = q.filter(Dossier.loai == loai_filter)

    status_filter = request.args.get('trang_thai', '').strip()
    if status_filter:
        q = q.filter(Dossier.trang_thai == status_filter)

    dossiers = q.order_by(Dossier.trang_thai.asc(), Dossier.han_tra.asc()).all()

    today = date.today()
    counts = {'overdue': 0, 'soon': 0, 'pending': 0, 'done': 0}

    loai_labels = {
        'can-cuoc': 'Căn cước',
        'cu-tru': 'Cư trú',
        'dinh-danh': 'Định danh VNeID',
        'xac-thuc': 'Xác thực ĐA06',
        'khac': 'Hồ sơ khác'
    }

    result = []
    for d in dossiers:
        state = _calc_dossier_state(d, today)
        counts[state] += 1
        days_left = (d.han_tra - today).days if d.han_tra else None

        result.append({
            'id': d.id,
            'ma_ho_so': d.ma_ho_so,
            'loai': d.loai,
            'loai_label': loai_labels.get(d.loai, d.loai or 'Hồ sơ khác'),
            'ngay_tiep_nhan': d.ngay_tiep_nhan.strftime('%Y-%m-%d') if d.ngay_tiep_nhan else '',
            'han_tra': d.han_tra.strftime('%Y-%m-%d') if d.han_tra else '',
            'ghi_chu': d.ghi_chu or '',
            'trang_thai': d.trang_thai,
            'da_tra_at': d.da_tra_at.strftime('%d/%m/%Y %H:%M') if d.da_tra_at else '',
            'state': state,
            'days_left': days_left,
            'created_by': d.created_by,
            'author_name': d.author.fullname if d.author else '',
            'unit_area': d.unit_area or ''
        })

    return jsonify({
        'dossiers': result,
        'counts': counts,
        'remind_days': REMIND_DAYS_DEFAULT,
        'today': today.strftime('%Y-%m-%d')
    })


@dossier_bp.route('/api/dossiers', methods=['POST'])
def api_create_dossier():
    """Thêm mới một hồ sơ theo dõi hạn."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    ma_ho_so = (data.get('ma_ho_so') or data.get('name') or data.get('code') or data.get('dossier_code') or data.get('title') or '').strip()
    han_tra_str = (data.get('han_tra') or data.get('deadline') or data.get('due_date') or '').strip()

    if not ma_ho_so:
        return jsonify({'error': 'Vui lòng nhập mã hoặc tên hồ sơ'}), 400
    if not han_tra_str:
        return jsonify({'error': 'Vui lòng chọn ngày hết hạn trả kết quả'}), 400

    try:
        han_tra = datetime.strptime(han_tra_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Ngày hết hạn không đúng định dạng YYYY-MM-DD'}), 400

    ngay_tn_str = (data.get('ngay_tiep_nhan') or '').strip()
    ngay_tiep_nhan = None
    if ngay_tn_str:
        try:
            ngay_tiep_nhan = datetime.strptime(ngay_tn_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    uid = session.get('uid')
    usr = db.session.get(User, uid)
    unit_area = getattr(usr, 'unit_area', '') or ''

    dossier = Dossier(
        ma_ho_so=ma_ho_so,
        loai=data.get('loai') or 'can-cuoc',
        ngay_tiep_nhan=ngay_tiep_nhan or date.today(),
        han_tra=han_tra,
        ghi_chu=(data.get('ghi_chu') or '').strip(),
        trang_thai='dang_xu_ly',
        created_by=uid,
        unit_area=unit_area
    )

    db.session.add(dossier)
    db.session.commit()

    return jsonify({'success': True, 'id': dossier.id})


@dossier_bp.route('/api/dossiers/<int:id>', methods=['PUT'])
def api_update_dossier(id):
    """Cập nhật thông tin hồ sơ."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    dossier = db.session.get(Dossier, id)
    if not dossier:
        return jsonify({'error': 'Không tìm thấy hồ sơ'}), 404

    data = request.get_json(silent=True) or {}
    ma_ho_so = (data.get('ma_ho_so') or data.get('name') or data.get('code') or data.get('dossier_code') or data.get('title') or '').strip()
    han_tra_str = (data.get('han_tra') or data.get('deadline') or data.get('due_date') or '').strip()

    if ma_ho_so:
        dossier.ma_ho_so = ma_ho_so
    if data.get('loai'):
        dossier.loai = data.get('loai')

    if han_tra_str:
        try:
            dossier.han_tra = datetime.strptime(han_tra_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Ngày hết hạn không hợp lệ'}), 400

    ngay_tn_str = (data.get('ngay_tiep_nhan') or '').strip()
    if ngay_tn_str:
        try:
            dossier.ngay_tiep_nhan = datetime.strptime(ngay_tn_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    if 'ghi_chu' in data:
        dossier.ghi_chu = (data.get('ghi_chu') or '').strip()

    db.session.commit()
    return jsonify({'success': True})


@dossier_bp.route('/api/dossiers/<int:id>', methods=['DELETE'])
def api_delete_dossier(id):
    """Xóa hồ sơ."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    dossier = db.session.get(Dossier, id)
    if not dossier:
        return jsonify({'error': 'Không tìm thấy hồ sơ'}), 404

    db.session.delete(dossier)
    db.session.commit()
    return jsonify({'success': True})


@dossier_bp.route('/api/dossiers/<int:id>/status', methods=['POST'])
def api_set_dossier_status(id):
    """Đổi trạng thái hồ sơ (dang_xu_ly <-> da_tra)."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    dossier = db.session.get(Dossier, id)
    if not dossier:
        return jsonify({'error': 'Không tìm thấy hồ sơ'}), 404

    data = request.get_json(silent=True) or {}
    trang_thai = data.get('trang_thai')
    if trang_thai not in ('dang_xu_ly', 'da_tra'):
        return jsonify({'error': 'Trạng thái không hợp lệ'}), 400

    dossier.trang_thai = trang_thai
    if trang_thai == 'da_tra':
        dossier.da_tra_at = datetime.now()
    else:
        dossier.da_tra_at = None

    db.session.commit()
    return jsonify({'success': True, 'trang_thai': dossier.trang_thai})
