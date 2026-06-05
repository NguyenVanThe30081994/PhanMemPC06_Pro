# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, send_file, current_app
from utils import render_auto_template, apply_migrations
from models import db, ShortLink, User
from category_helpers import canonicalize_category_value, module_category_options, stable_form_category_options, sync_record_categories
import qrcode
from io import BytesIO
import secrets
import string
import datetime
from urllib.parse import urlparse

shortlink_bp = Blueprint('shortlink_bp', __name__)


def _ensure_shortlink_schema():
    try:
        apply_migrations(current_app)
    except Exception as migration_error:
        current_app.logger.warning(f"SHORTLINK migration safeguard failed: {migration_error}")

def generate_short_code(length=6):
    """Generate unique short code - optimized with batch check"""
    chars = string.ascii_letters + string.digits
    
    # Get all existing codes at once (cache for performance)
    existing_codes = set(s.short_code for s in ShortLink.query.with_entities(ShortLink.short_code).all())
    
    # Try up to 100 times before giving up
    for _ in range(100):
        code = ''.join(secrets.choice(chars) for _ in range(length))
        if code not in existing_codes:
            return code
    
    # Fallback: try longer length
    for length in range(7, 12):
        for _ in range(100):
            code = ''.join(secrets.choice(chars) for _ in range(length))
            if code not in existing_codes:
                return code
    
    raise Exception("Không thể tạo mã rút gọn. Vui lòng thử lại.")


def _normalize_target_url(raw_url):
    candidate = (raw_url or '').strip()
    if not candidate:
        return None
    if not (candidate.startswith('http://') or candidate.startswith('https://')):
        candidate = 'https://' + candidate
    parsed = urlparse(candidate)
    if parsed.scheme not in {'http', 'https'}:
        return None
    if not parsed.netloc or parsed.username or parsed.password:
        return None
    return candidate

@shortlink_bp.route('/links')
def manage_links():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _ensure_shortlink_schema()

    # Optional logic: only show links created by the user, or all if admin
    is_admin = session.get('is_admin', False)
    if is_admin:
        links = ShortLink.query.order_by(ShortLink.created_at.desc()).all()
    else:
        links = ShortLink.query.filter_by(created_by=session['uid']).order_by(ShortLink.created_at.desc()).all()

    link_categories = module_category_options('news', 'category', 'Lĩnh vực', 'Đội nghiệp vụ')
    pro_units = module_category_options('tasks', 'domain', 'Đội nghiệp vụ')
    links = sync_record_categories(links, link_categories, attr_name='category', prefer_stable=True)
    links = sync_record_categories(links, pro_units, attr_name='domain', prefer_stable=True)

    return render_auto_template(
        'shortlinks.html',
        links=links,
        is_admin=is_admin,
        link_categories=stable_form_category_options(link_categories),
        pro_units=stable_form_category_options(pro_units),
    )

@shortlink_bp.route('/links/add', methods=['POST'])
def add_link():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _ensure_shortlink_schema()

    original_url = _normalize_target_url(request.form.get('original_url', ''))
    custom_code = request.form.get('custom_code', '').strip()
    custom_name = request.form.get('custom_name', '').strip()
    info = request.form.get('info', '').strip()
    link_categories = module_category_options('news', 'category', 'Lĩnh vực', 'Đội nghiệp vụ')
    pro_units = module_category_options('tasks', 'domain', 'Đội nghiệp vụ')
    category = canonicalize_category_value(request.form.get('category', ''), link_categories, prefer_stable=True)
    domain = canonicalize_category_value(request.form.get('domain', ''), pro_units, prefer_stable=True)
    
    if not original_url:
        flash('Vui lòng nhập đường dẫn gốc!', 'danger')
        return redirect(url_for('shortlink_bp.manage_links'))

    if custom_code:
        # Check if custom code exists
        existing = ShortLink.query.filter_by(short_code=custom_code).first()
        if existing:
            flash(f'Mã rút gọn "{custom_code}" đã tồn tại. Vui lòng chọn mã khác!', 'danger')
            return redirect(url_for('shortlink_bp.manage_links'))
        code = custom_code
    else:
        code = generate_short_code()
        
    new_link = ShortLink(
        short_code=code,
        original_url=original_url,
        custom_name=custom_name,
        info=info,
        category=category,
        domain=domain,
        created_by=session['uid']
    )
    
    db.session.add(new_link)
    db.session.commit()
    
    from utils import push_global_notif
    lname = custom_name if custom_name else code
    push_global_notif("Rút gọn link mới", f"Có link rút gọn mới: {lname}", "/links", exclude_uid=session['uid'])
    
    flash('Đã tạo link rút gọn thành công!', 'success')
    return redirect(url_for('shortlink_bp.manage_links'))

@shortlink_bp.route('/links/edit/<int:link_id>', methods=['POST'])
def edit_link(link_id):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _ensure_shortlink_schema()

    link = db.session.get(ShortLink, link_id)
    if not link:
        flash('Không tìm thấy liên kết cần sửa.', 'danger')
        return redirect(url_for('shortlink_bp.manage_links'))

    is_admin = session.get('is_admin', False)
    if not (is_admin or link.created_by == session['uid']):
        flash('Bạn không có quyền sửa liên kết này!', 'danger')
        return redirect(url_for('shortlink_bp.manage_links'))

    original_url = _normalize_target_url(request.form.get('original_url', ''))
    custom_code = request.form.get('custom_code', '').strip()
    custom_name = request.form.get('custom_name', '').strip()
    info = request.form.get('info', '').strip()
    link_categories = module_category_options('news', 'category', 'Lĩnh vực', 'Đội nghiệp vụ')
    pro_units = module_category_options('tasks', 'domain', 'Đội nghiệp vụ')

    if not original_url:
        flash('Vui lòng nhập đường dẫn gốc!', 'danger')
        return redirect(url_for('shortlink_bp.manage_links'))

    if not custom_code:
        flash('Mã rút gọn không được để trống khi cập nhật.', 'danger')
        return redirect(url_for('shortlink_bp.manage_links'))

    existing = ShortLink.query.filter(ShortLink.short_code == custom_code, ShortLink.id != link.id).first()
    if existing:
        flash(f'Mã rút gọn "{custom_code}" đã tồn tại. Vui lòng chọn mã khác!', 'danger')
        return redirect(url_for('shortlink_bp.manage_links'))

    link.short_code = custom_code
    link.original_url = original_url
    link.custom_name = custom_name
    link.info = info
    link.category = canonicalize_category_value(request.form.get('category', ''), link_categories, prefer_stable=True)
    link.domain = canonicalize_category_value(request.form.get('domain', ''), pro_units, prefer_stable=True)

    db.session.commit()
    flash('Đã cập nhật liên kết rút gọn!', 'success')
    return redirect(url_for('shortlink_bp.manage_links'))

@shortlink_bp.route('/links/delete/<int:link_id>', methods=['POST'])
def delete_link(link_id):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
        
    link = db.session.get(ShortLink, link_id)
    if link:
        # Check perm
        is_admin = session.get('is_admin', False)
        if is_admin or link.created_by == session['uid']:
            db.session.delete(link)
            db.session.commit()
            flash('Đã xoá link rút gọn!', 'success')
        else:
            flash('Bạn không có quyền xoá link này!', 'danger')
            
    return redirect(url_for('shortlink_bp.manage_links'))

@shortlink_bp.route('/download-qr/<code>')
def get_qr(code):
    try:
        link = ShortLink.query.filter_by(short_code=code).first()
        if not link:
            abort(404)
            
        # Generate QR Code image dynamically
        host_url = request.host_url.rstrip('/')
        target_url = f"{host_url}/s/{code}"
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(target_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        from flask import make_response
        response = make_response(img_io.getvalue())
        response.headers.set('Content-Type', 'image/png')
        response.headers.set('Content-Disposition', 'attachment', filename=f'QR_{code}.png')
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Lỗi hệ thống khi tạo QR: {str(e)}.", 500

@shortlink_bp.route('/s/<code>')
def redirect_short_link(code):
    link = ShortLink.query.filter_by(short_code=code).first()
    if not link:
        return render_template('404.html'), 404
        
    # Increment counter
    link.clicks += 1
    db.session.commit()
    
    return redirect(link.original_url)
