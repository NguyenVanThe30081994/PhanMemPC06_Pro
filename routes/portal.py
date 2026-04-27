# -*- coding: utf-8 -*-
from flask import Blueprint, request, session, redirect, url_for, flash, current_app
import os, pandas as pd, io, json, re, unicodedata
from werkzeug.utils import secure_filename
from datetime import datetime
from models import db, NewsDoc, DocumentLib, Contact, CategoryItem, AppRole
from category_helpers import get_category_items, get_module_field_items, get_bound_group, get_category_group, slugify_code
from utils import log_action, push_global_notif, render_auto_template as render_template

portal_bp = Blueprint('portal_bp', __name__)

CONTACT_IMPORT_HEADER_ALIASES = {
    'name': {'ho ten', 'ten', 'ten lien he', 'ho va ten'},
    'phone': {'so dien thoai', 'sdt', 'so dt', 'dien thoai'}
}


def _normalize_import_label(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace('đ', 'd').replace('Đ', 'D')
    text = re.sub(r'[^0-9a-zA-Z]+', ' ', text).strip().lower()
    return re.sub(r'\s+', ' ', text)


def _clean_import_text(value):
    if value is None:
        return ''
    text = str(value).strip()
    if text.lower() == 'nan':
        return ''
    return text


def _normalize_import_phone(value):
    raw = _clean_import_text(value)
    if not raw:
        return ''

    digits = re.sub(r'\D+', '', raw)
    if not digits:
        return ''
    if digits.startswith('84') and len(digits) == 11:
        return f"0{digits[2:]}"
    if len(digits) == 9:
        return f"0{digits}"
    return digits


def _find_import_column(columns, field_name):
    aliases = CONTACT_IMPORT_HEADER_ALIASES[field_name]
    for col in columns:
        if _normalize_import_label(col) in aliases:
            return col
    return None


def _get_current_user_unit():
    return session.get('unit_area') or session.get('unit') or 'N/A'


def _load_contacts_from_excel(file_storage, has_header=True):
    read_kwargs = {'dtype': str, 'sheet_name': 0}
    read_kwargs['header'] = 0 if has_header else None
    df = pd.read_excel(io.BytesIO(file_storage.read()), **read_kwargs).fillna('')

    if df.empty:
        raise ValueError('File Excel không có dữ liệu.')

    if has_header:
        name_col = _find_import_column(df.columns, 'name')
        phone_col = _find_import_column(df.columns, 'phone')
        if not name_col or not phone_col:
            raise ValueError('Khi có tiêu đề, file phải có đúng 2 cột nhận diện được: "Họ tên" và "Số điện thoại".')
    else:
        if len(df.columns) < 2:
            raise ValueError('Khi không có tiêu đề, file phải có ít nhất 2 cột: cột A là Họ tên, cột B là Số điện thoại.')
        name_col, phone_col = df.columns[0], df.columns[1]

    contacts = []
    skipped_empty = 0
    invalid_rows = []

    for idx, row in df.iterrows():
        name = _clean_import_text(row.get(name_col, ''))
        phone = _normalize_import_phone(row.get(phone_col, ''))
        excel_row = idx + (2 if has_header else 1)

        if not name and not phone:
            skipped_empty += 1
            continue

        if not name or not phone:
            invalid_rows.append(excel_row)
            continue

        contacts.append({
            'idx': len(contacts),
            'excel_row': int(excel_row),
            'name': name,
            'phone': phone
        })

    if not contacts:
        raise ValueError('Không tìm thấy dòng hợp lệ nào. Mỗi dòng phải có đủ Họ tên và Số điện thoại.')

    return {
        'rows': contacts,
        'total_rows': int(len(df.index)),
        'valid_rows': len(contacts),
        'skipped_empty': skipped_empty,
        'invalid_rows': invalid_rows
    }

@portal_bp.route('/news', methods=['GET', 'POST'])
def news():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_news_lead = perms.get('p_news_lead') or session.get('is_admin')

    if request.method == 'POST' and is_news_lead:
        f = request.files.get('file')
        fn = ""
        if f and f.filename:
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.root_path, 'uploads', fn))
        db.session.add(NewsDoc(
            title=request.form['title'],
            category=request.form['category'],
            content=request.form['content'],
            filename=fn
        ))
        db.session.commit()
        log_action(session['uid'], session['fullname'], "Đăng tin mới", "Bảng tin", request.form['title'])
        push_global_notif(f"Bảng tin: {request.form['category']}", f"{request.form['title']}", "/news", exclude_uid=session['uid'])
        flash('Đã đăng tin mới!', 'success')
        return redirect(url_for('portal_bp.news'))
    now_str = datetime.now().strftime('Ngày %d tháng %m, %Y')

    news_category_items = get_module_field_items('news', 'category')
    if not news_category_items:
        news_category_items = get_category_items('Lĩnh vực', 'Đội nghiệp vụ')
    pro_units = get_module_field_items('tasks', 'domain') or get_category_items('Đội nghiệp vụ')

    return render_template('news.html',
                          news_list=NewsDoc.query.order_by(NewsDoc.uploaded_at.desc()).all(),
                          cats=news_category_items,
                          pro_units=news_category_items or pro_units,
                          now_str=now_str)

@portal_bp.route('/notifications')
def notifications():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    from models import Notification
    notifs = Notification.query.filter_by(user_id=session['uid']).order_by(Notification.created_at.desc()).limit(20).all()
    # Mark as read when viewing the page
    Notification.query.filter_by(user_id=session['uid']).update({'is_read': 1})
    db.session.commit()
    return render_template('notifications.html', notifs=notifs)

@portal_bp.route('/library', methods=['GET', 'POST'])
def library():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_lib_lead = perms.get('p_lib_lead') or session.get('is_admin')

    if request.method == 'POST' and is_lib_lead:
        f = request.files.get('file')
        if f and f.filename:
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.root_path, 'library_files', fn))
            db.session.add(DocumentLib(title=request.form['title'], category=request.form['category'], filename=fn))
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Tải lên tài liệu", "Thư viện", request.form['title'])
            push_global_notif("Thư viện", f"Tài liệu mới: {request.form['title']}", "/library", exclude_uid=session['uid'])
            flash('Đã tải lên tài liệu!', 'success')
        return redirect(url_for('portal_bp.library'))
    
    library_category_items = get_module_field_items('library', 'category')
    if not library_category_items:
        library_category_items = get_category_items('Lĩnh vực', 'Loại tài liệu')

    return render_template('library.html', docs=DocumentLib.query.all(), cats=library_category_items, categories=library_category_items, items=DocumentLib.query.all())

@portal_bp.route('/contacts')
def contacts():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    # Permissions
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_admin = session.get('is_admin')
    is_contact_lead = perms.get('p_contact_lead') or is_admin
    user_unit = session.get('unit_area')

    group_filter = request.args.get('group')
    query = Contact.query
    if group_filter:
        query = query.filter_by(contact_group=group_filter)
    
    if not is_contact_lead:
        query = query.filter_by(unit_name=user_unit)
    
    contact_groups_items = get_module_field_items('contacts', 'contact_group') or get_category_items('Nhóm danh bạ')
    contact_roles_items = get_module_field_items('contacts', 'role') or get_category_items('Chức vụ')
    linhvuc_items = get_module_field_items('contacts', 'category') or get_category_items('Lĩnh vực')
    unit_items = get_module_field_items('contacts', 'unit_name') or get_category_items('Đơn vị')

    return render_template('contacts.html', 
                          contacts=query.all(), 
                          groups=contact_groups_items,
                          categories=contact_groups_items,
                          roles=contact_roles_items, 
                          linhvuc_items=linhvuc_items,
                          unit_items=unit_items,
                          current_group=group_filter)

@portal_bp.route('/contacts/edit/<int:cid>', methods=['POST'])
def contact_edit(cid):
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_contact_lead = perms.get('p_contact_lead') or session.get('is_admin')
    user_unit = session.get('unit_area')

    c = Contact.query.get_or_404(cid)
    
    if not is_contact_lead and c.unit_name != user_unit:
        flash('Bạn không có quyền sửa liên lạc của đơn vị khác!', 'danger')
        return redirect(url_for('portal_bp.contacts'))
    c.name = request.form.get('name')
    c.phone = request.form.get('phone')
    c.role = request.form.get('role')
    c.unit_name = request.form.get('unit_name')
    c.contact_group = request.form.get('contact_group')
    try:
        db.session.commit()
        flash('Đã cập nhật thông tin liên lạc!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi cập nhật: {e}', 'danger')
    return redirect(url_for('portal_bp.contacts'))

@portal_bp.route('/contacts/delete/<int:cid>', methods=['POST'])
def contact_delete(cid):
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_contact_lead = perms.get('p_contact_lead') or perms.get('p_contact_exec') or session.get('is_admin')
    user_unit = session.get('unit')

    c = Contact.query.get_or_404(cid)
    if not is_contact_lead and c.unit_name != user_unit:
        flash('Bạn không có quyền xóa liên lạc của đơn vị khác!', 'danger')
        return redirect(url_for('portal_bp.contacts'))
    try:
        db.session.delete(c)
        db.session.commit()
        flash('Đã xóa liên lạc khỏi danh bạ!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa: {e}', 'danger')
    return redirect(url_for('portal_bp.contacts'))

@portal_bp.route('/contacts/add', methods=['POST'])
def contact_add():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_contact_lead = perms.get('p_contact_lead') or perms.get('p_contact_exec') or session.get('is_admin')
    user_unit = session.get('unit')

    name = request.form.get('name')
    phone = request.form.get('phone')
    role = request.form.get('role')
    unit = request.form.get('unit_name')
    
    if not is_contact_lead:
        unit = user_unit # Force own unit
    group = request.form.get('contact_group')
    new_group_name = request.form.get('new_group_name')

    if group == 'NEW':
        new_group_name = (new_group_name or '').strip()
        if not new_group_name:
            flash('Bạn cần nhập tên nhóm danh bạ mới.', 'danger')
            return redirect(url_for('portal_bp.contacts'))

        group_bucket = get_bound_group('contacts', 'contact_group') or get_category_group('Nhóm danh bạ')
        existing = None
        if group_bucket:
            existing = CategoryItem.query.filter_by(group_id=group_bucket.id, name=new_group_name).first()
        else:
            existing = CategoryItem.query.filter_by(name=new_group_name).first()

        if not existing:
            new_g = CategoryItem(
                group_id=group_bucket.id if group_bucket else None,
                code=slugify_code(new_group_name),
                name=new_group_name,
                is_active=True
            )
            db.session.add(new_g)
            db.session.flush()
            group = new_g.name
        else:
            group = existing.name

    db.session.add(Contact(
        name=name,
        phone=phone,
        role=role,
        unit_name=unit,
        contact_group=group
    ))
    db.session.commit()
    log_action(session['uid'], session['fullname'], "Thêm liên lạc thủ công", "Danh bạ", name)
    flash(f'Đã thêm liên lạc {name} thành công!', 'success')
    return redirect(url_for('portal_bp.contacts'))

# Preview route - returns Excel data as JSON for preview
@portal_bp.route('/contacts/preview-import', methods=['POST'])
def contact_preview_import():
    """Preview Excel file and return data as JSON"""
    if not session.get('uid'): return {'error': 'Unauthorized'}, 401
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_admin = session.get('is_admin')
    can_import_contacts = perms.get('p_contact_lead') or perms.get('p_contact_exec') or is_admin
    if not can_import_contacts:
        return {'error': 'Permission denied'}, 403
    
    f = request.files.get('import_excel')
    has_header = request.form.get('has_header', '1') == '1'
    if not f or not f.filename.lower().endswith(('.xlsx', '.xls')):
        return {'error': 'Invalid file'}, 400
    
    try:
        parsed = _load_contacts_from_excel(f, has_header=has_header)
        return {
            'success': True,
            'data': parsed['rows'][:50],
            'total': parsed['total_rows'],
            'valid_rows': parsed['valid_rows'],
            'skipped_empty': parsed['skipped_empty'],
            'invalid_rows': parsed['invalid_rows'][:20]
        }
    except Exception as e:
        return {'error': str(e)}, 500


@portal_bp.route('/contacts/import', methods=['POST'])
def contact_import():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))

    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_admin = session.get('is_admin')
    can_import_contacts = perms.get('p_contact_lead') or perms.get('p_contact_exec') or is_admin

    if not can_import_contacts:
        flash('Chỉ PC06 mới có quyền nhập danh bạ hàng loạt!', 'danger')
        return redirect(url_for('portal_bp.contacts'))
    
    f = request.files.get('import_excel')
    global_group = (request.form.get('global_group') or '').strip()
    global_role = (request.form.get('global_role') or '').strip()
    has_header = request.form.get('has_header', '1') == '1'

    if not global_group:
        flash('Bạn cần chọn nhóm danh bạ trước khi nhập.', 'danger')
        return redirect(url_for('portal_bp.contacts'))

    if not global_role:
        flash('Bạn cần chọn chức vụ trước khi nhập.', 'danger')
        return redirect(url_for('portal_bp.contacts'))

    if f and f.filename.lower().endswith(('.xlsx', '.xls')):
        try:
            parsed = _load_contacts_from_excel(f, has_header=has_header)
            imported = 0
            user_unit = _get_current_user_unit()

            for row in parsed['rows']:
                db.session.add(Contact(
                    contact_group=global_group,
                    unit_name=user_unit,
                    name=row['name'],
                    phone=row['phone'],
                    role=global_role
                ))
                imported += 1
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Import danh bạ hàng loạt", "Danh bạ", f"File: {f.filename}, {imported} liên hệ")

            warning_parts = []
            if parsed['skipped_empty']:
                warning_parts.append(f"bỏ qua {parsed['skipped_empty']} dòng trống")
            if parsed['invalid_rows']:
                warning_parts.append(f"bỏ qua các dòng thiếu dữ liệu: {', '.join(map(str, parsed['invalid_rows'][:10]))}")

            flash_message = f'Đã nhập {imported} liên lạc thành công!'
            if warning_parts:
                flash_message = f"{flash_message} Đồng thời {'. '.join(warning_parts)}."
            flash(flash_message, 'success')
        except Exception as e: 
            db.session.rollback()
            flash(f'Lỗi import: {e}', 'danger')
    else:
        flash('Vui lòng chọn file Excel hợp lệ (.xlsx hoặc .xls).', 'danger')
    return redirect(url_for('portal_bp.contacts'))
