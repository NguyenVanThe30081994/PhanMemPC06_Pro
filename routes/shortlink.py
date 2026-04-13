from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, send_file
from utils import render_auto_template
from models import db, ShortLink, User
import qrcode
from io import BytesIO
import random
import string
import datetime

shortlink_bp = Blueprint('shortlink_bp', __name__)

def generate_short_code(length=6):
    chars = string.ascii_letters + string.digits
    while True:
        code = ''.join(random.choice(chars) for _ in range(length))
        if not ShortLink.query.filter_by(short_code=code).first():
            return code

@shortlink_bp.route('/links')
def manage_links():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    # Optional logic: only show links created by the user, or all if admin
    is_admin = session.get('is_admin', False)
    if is_admin:
        links = ShortLink.query.order_by(ShortLink.created_at.desc()).all()
    else:
        links = ShortLink.query.filter_by(created_by=session['uid']).order_by(ShortLink.created_at.desc()).all()
        
    return render_auto_template('shortlinks.html', links=links, is_admin=is_admin)

@shortlink_bp.route('/links/add', methods=['POST'])
def add_link():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
        
    original_url = request.form.get('original_url', '').strip()
    custom_code = request.form.get('custom_code', '').strip()
    custom_name = request.form.get('custom_name', '').strip()
    info = request.form.get('info', '').strip()
    
    if not original_url:
        flash('Vui lòng nhập đường dẫn gốc!', 'danger')
        return redirect(url_for('shortlink_bp.manage_links'))
        
    if not (original_url.startswith('http://') or original_url.startswith('https://')):
        original_url = 'https://' + original_url

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
        created_by=session['uid']
    )
    
    db.session.add(new_link)
    db.session.commit()
    
    from utils import push_global_notif
    lname = custom_name if custom_name else code
    push_global_notif("Rút gọn link mới", f"Có link rút gọn mới: {lname}", "/links", exclude_uid=session['uid'])
    
    flash('Đã tạo link rút gọn thành công!', 'success')
    return redirect(url_for('shortlink_bp.manage_links'))

@shortlink_bp.route('/links/delete/<int:link_id>')
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
        return f"Lỗi hệ thống khi tạo QR: {str(e)}. Hãy thử F5 lại trang.", 500

@shortlink_bp.route('/s/<code>')
def redirect_short_link(code):
    link = ShortLink.query.filter_by(short_code=code).first()
    if not link:
        return render_template('404.html'), 404
        
    # Increment counter
    link.clicks += 1
    db.session.commit()
    
    return redirect(link.original_url)
