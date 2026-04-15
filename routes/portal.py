from flask import Blueprint, render_template as flask_render_template, request, session, redirect, url_for, flash, current_app, send_from_directory
import os, pandas as pd, io, json
from werkzeug.utils import secure_filename
from datetime import datetime
from models import db, NewsDoc, DocumentLib, Contact, MasterData, CategoryGroup, CategoryItem, AppRole
from utils import log_action, push_global_notif, render_auto_template as render_template

portal_bp = Blueprint('portal_bp', __name__)

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
    
    # === LẤY DANH MỤC THEO NHÓM ===
    group_danhba = CategoryGroup.query.filter((CategoryGroup.name == 'Nhom danh ba') | (CategoryGroup.name == 'Nhóm danh bạ')).first()
    danhba_items = CategoryItem.query.filter_by(group_id=group_danhba.id).all() if group_danhba else []
    
    group_donvi = CategoryGroup.query.filter((CategoryGroup.name == 'Don vi') | (CategoryGroup.name == 'Đơn vị')).first()
    donvi_items = CategoryItem.query.filter_by(group_id=group_donvi.id).all() if group_donvi else []
    
    # Linh vuc (for news)
    group_linhvuc = CategoryGroup.query.filter((CategoryGroup.name == 'Linh vuc') | (CategoryGroup.name == 'Lĩnh vực')).first()
    linhvuc_items = CategoryItem.query.filter_by(group_id=group_linhvuc.id).all() if group_linhvuc else []
    
    # Dong nghiep vu (for tasks)
    group_dongnghiepvu = CategoryGroup.query.filter((CategoryGroup.name == 'Dong nghiep vu') | (CategoryGroup.name == 'Đội nghiệp vụ')).first()
    dongnghiepvu_items = CategoryItem.query.filter_by(group_id=group_dongnghiepvu.id).all() if group_dongnghiepvu else []
    
    return render_template('news.html',
                          news_list=NewsDoc.query.order_by(NewsDoc.uploaded_at.desc()).all(),
                          cats=linhvuc_items, 
                          pro_units=dongnghiepvu_items,
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
    
    # === LẤY DANH MỤC LĨNH VỰC ===
    # Tìm nhóm Lĩnh vực - ưu tiên tìm theo linked_modules = "Thu vien"
    group_linhvuc = None
    
    # Cách 1: Tìm theo linked_modules có chứa "Thu vien"
    for g in CategoryGroup.query.all():
        if g.linked_modules and 'Thu vien' in g.linked_modules:
            group_linhvuc = g
            break
    
    # Cách 2: Nếu không có, tìm theo tên chứa "Lĩnh vực"
    if not group_linhvuc:
        group_linhvuc = CategoryGroup.query.filter(
            CategoryGroup.name.ilike('%Lĩnh vực%')
        ).first()
    
    # Cách 3: Thử tên không dấu
    if not group_linhvuc:
        group_linhvuc = CategoryGroup.query.filter(
            CategoryGroup.name.ilike('%Linh vuc%')
        ).first()
    
    if group_linhvuc:
        linhvuc_items = CategoryItem.query.filter_by(group_id=group_linhvuc.id).all()
    else:
        linhvuc_items = []
    
    return render_template('library.html', docs=DocumentLib.query.all(), cats=linhvuc_items, categories=linhvuc_items)

@portal_bp.route('/contacts')
def contacts():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    # Permissions
    from models import AppRole
    import json
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
    
    # Lấy danh mục từ CategoryItem
    group_danhba = CategoryGroup.query.filter((CategoryGroup.name == 'Nhom danh ba') | (CategoryGroup.name == 'Nhóm danh bạ')).first()
    contact_groups_items = CategoryItem.query.filter_by(group_id=group_danhba.id).all() if group_danhba else []
    
    group_chucvu = CategoryGroup.query.filter((CategoryGroup.name == 'Chuc vu') | (CategoryGroup.name == 'Chức vụ')).first()
    contact_roles_items = CategoryItem.query.filter_by(group_id=group_chucvu.id).all() if group_chucvu else []
    
    # Lấy nhóm "Lĩnh vực" cho danh bạ
    group_linhvuc = CategoryGroup.query.filter((CategoryGroup.name == 'Linh vuc') | (CategoryGroup.name == 'Lĩnh vực')).first()
    linhvuc_items = CategoryItem.query.filter_by(group_id=group_linhvuc.id).all() if group_linhvuc else []
    
    return render_template('contacts.html', 
                          contacts=query.all(), 
                          groups=contact_groups_items,
                          categories=contact_groups_items,
                          roles=contact_roles_items, 
                          linhvuc_items=linhvuc_items,
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

@portal_bp.route('/contacts/delete/<int:cid>')
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

    if group == 'NEW' and new_group_name:
        # Check if group exists
        existing = CategoryItem.query.filter_by(name=new_group_name).first()
        if not existing:
            # Assuming CategoryItem is used for dynamic groups
            new_g = CategoryItem(name=new_group_name)
            db.session.add(new_g)
            db.session.commit()
            group = new_group_name
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

@portal_bp.route('/contacts/import', methods=['POST'])
def contact_import():
    from models import AppRole
    import json
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_admin = session.get('is_admin')
    is_contact_lead = perms.get('p_contact_lead') or is_admin

    if not is_contact_lead: 
        flash('Chỉ PC06 mới có quyền nhập danh bạ hàng loạt!', 'danger')
        return redirect(url_for('portal_bp.contacts'))
    f = request.files.get('import_excel')
    group_from_form = request.form.get('contact_group')
    
    if f and f.filename.endswith(('.xlsx', '.xls')):
        try:
            df = pd.read_excel(io.BytesIO(f.read())).fillna('')
            for _, row in df.iterrows():
                # Use group from form if provided, otherwise fallback to Excel column
                contact_group = group_from_form if group_from_form else str(row.get('Nhóm', 'Kế hoạch'))
                db.session.add(Contact(
                    contact_group=contact_group,
                    unit_name=str(row.get('Đơn vị', 'N/A')),
                    name=str(row.get('Họ tên', 'Vô danh')),
                    phone=str(row.get('SĐT', '')),
                    role=str(row.get('Chức vụ', 'Cán bộ'))
                ))
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Import danh bạ hàng loạt", "Danh bạ")
            flash('Đã nhập danh bạ thành công!', 'success')
        except Exception as e: flash(f'Lỗi import: {e}', 'danger')
    return redirect(url_for('portal_bp.contacts'))
