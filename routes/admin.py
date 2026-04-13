from flask import Blueprint, render_template as flask_render_template, request, session, redirect, url_for, flash, jsonify, current_app, Response, send_from_directory
from models import db, User, AppRole, MasterData, SystemLog, NewsCategory, LibraryField, ContactGroup, ReportData, Task, NewsDoc, DocumentLib, ReportConfig, ReportTemplateV2, ReportSubmissionV2, ProfessionalUnit, ContactRole, Contact, CategoryGroup, CategoryItem
import os, json, shutil, zipfile, io, pandas as pd, sqlite3, subprocess
from datetime import datetime, timedelta
from utils import log_action, clear_logs, init_db, render_auto_template as render_template

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/admin')
def index():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    # Basic Stats
    stats = {
        'users': User.query.count(),
        'reports': ReportData.query.count(),
        'roles': AppRole.query.count(),
        'news': NewsDoc.query.count(),
        'tasks': Task.query.count()
    }

    # Calculate Overdue Reports
    all_units = [u[0] for u in db.session.query(User.unit_area).distinct().all() if u[0]]
    overdue_stats = []
    today = datetime.now().date()
    curr_period = f"Tuần {datetime.now().strftime('%U-%Y')}"

    # V1 Reports
    for r in ReportConfig.query.all():
        q = db.session.query(User.unit_area).join(ReportData, User.id == ReportData.user_id)\
            .filter(ReportData.report_id == r.id)
        if r.is_daily: q = q.filter(ReportData.report_date == today)
        submitted = [u[0] for u in q.distinct().all()]
        missing = [u for u in all_units if u not in submitted]
        if missing: overdue_stats.append({'id': r.id, 'name': r.name, 'count': len(missing)})

    # V2 Reports
    total_templates = ReportConfig.query.count()
    try:
        v2_templates = ReportTemplateV2.query.filter_by(is_active=True).all()
        total_templates += len(v2_templates)
        for t in v2_templates:
            q = db.session.query(ReportSubmissionV2.org_unit).filter(ReportSubmissionV2.status != 'draft')
            submitted = [u[0] for u in q.filter(ReportSubmissionV2.org_unit.in_(all_units)).distinct().all()]
            missing = [u for u in all_units if u not in submitted]
            if missing: overdue_stats.append({'id': t.id, 'name': t.name, 'count': len(missing)})
    except: pass

    # Query dữ liệu mới cho mobile dashboard
    from datetime import timedelta
    recent_date = datetime.now() - timedelta(days=7)
    
    new_tasks = Task.query.filter(Task.created_at >= recent_date).order_by(Task.created_at.desc()).limit(5).all()
    new_news = NewsDoc.query.filter(NewsDoc.uploaded_at >= recent_date).order_by(NewsDoc.uploaded_at.desc()).limit(5).all()
    new_docs = DocumentLib.query.filter(DocumentLib.uploaded_at >= recent_date).order_by(DocumentLib.uploaded_at.desc()).limit(5).all()
    new_reports = ReportConfig.query.order_by(ReportConfig.created_at.desc()).limit(5).all()
    
    logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(5).all()
    now_str = datetime.now().strftime('Ngày %d tháng %m, %Y')
    
    return render_auto_template('admin_dashboard.html', 
        stats=stats, 
        overdue_stats=overdue_stats, 
        total_templates=total_templates, 
        now_str=now_str, 
        logs=logs,
        new_tasks=new_tasks,
        new_news=new_news,
        new_docs=new_docs,
        new_reports=new_reports)

@admin_bp.route('/admin/db-tool', methods=['GET', 'POST'])
def db_tool():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    return render_template('db_tool.html')


@admin_bp.route('/admin/categories')
def category_admin():
    """Trang quản lý danh mục tập trung"""
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    from models import Category
    categories = Category.query.order_by(Category.type, Category.order, Category.name).all()
    return render_template('category_admin.html', categories=categories)


@admin_bp.route('/admin/db-manage', methods=['POST'])
def db_manage():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    action = request.form.get('action')
    try:
        if action == 'reset':
            from utils import init_db
            db.drop_all()
            db.create_all()
            init_db(current_app)
            
            flash('Hệ thống đã được Reset về trạng thái ban đầu!', 'success')
            session.clear() # Force re-login
            return redirect(url_for('auth_bp.login'))
            
        elif action == 'backup':
            # Use the correct database name from app.py
            db_path = os.path.join(current_app.root_path, 'pc06_system.db')
            if os.path.exists(db_path):
                return send_from_directory(current_app.root_path, 'pc06_system.db', as_attachment=True)
            else: 
                flash(f'Không tìm thấy file database tại {db_path}!', 'danger')
    except Exception as e:
        flash(f'Lỗi thao tác: {e}', 'danger')
    return redirect(url_for('admin_bp.db_tool'))

@admin_bp.route('/roles', methods=['GET', 'POST'])
def roles():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add_role':
                name = request.form['name']
                p_list = request.form.getlist('perms')
                p_json = json.dumps({p: 1 for p in p_list})
                db.session.add(AppRole(name=name, perms=p_json))
                log_action(session['uid'], session['fullname'], "Thêm vai trò", "Vai trò", name)
            elif action == 'edit_perms':
                rid = request.form['role_id']
                p_list = request.form.getlist('perms')
                r = db.session.get(AppRole, rid)
                if r:
                    r.perms = json.dumps({p: 1 for p in p_list})
                    log_action(session['uid'], session['fullname'], "Sửa quyền vai trò", "Vai trò", r.name)
            elif action == 'add_user':
                username = request.form.get('username')
                fullname = request.form.get('fullname')
                unit = request.form.get('unit', 'Chưa xác định')
                role_id = request.form.get('role_id')
                password = request.form.get('password', '123456')
                
                if not username or not role_id:
                    flash('Thiếu thông tin bắt buộc!', 'danger')
                else:
                    u = User(username=username, fullname=fullname, unit_area=unit, role_id=role_id)
                    u.set_password(password)
                    db.session.add(u)
                    log_action(session['uid'], session['fullname'], "Thêm tài khoản", "Tài khoản", u.username)
            elif action == 'edit_user':
                uid = request.form.get('user_id')
                u = db.session.get(User, uid)
                if u:
                    u.username = request.form.get('username')
                    u.fullname = request.form.get('fullname')
                    u.unit_area = request.form.get('unit')
                    u.role_id = request.form.get('role_id')
                    pwd = request.form.get('password')
                    if pwd and pwd.strip() and pwd != '******':
                        u.set_password(pwd)
                    log_action(session['uid'], session['fullname'], "Sửa tài khoản", "Tài khoản", u.username)
            db.session.commit()
            flash('Thao tác thành công!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi: {e}', 'danger')
        return redirect(url_for('admin_bp.roles'))
    
    unit_group = CategoryGroup.query.filter_by(name='Đơn vị').first()
    unit_cats = unit_group.items if unit_group else []
    return render_template('roles.html', roles=AppRole.query.all(), users=User.query.all(), units=[u[0] for u in db.session.query(MasterData.name).distinct().all() if u[0]], unit_cats=unit_cats)

@admin_bp.route('/admin/user/delete/<int:uid>')
def delete_user(uid):
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    u = db.session.get(User, uid)
    if u:
        if u.username == 'admin':
            flash('Không thể xóa tài khoản Quản trị hệ thống!', 'danger')
        else:
            name = u.username
            db.session.delete(u)
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Xóa tài khoản", "Tài khoản", name)
            flash(f'Đã xóa tài khoản {name} thành công!', 'success')
    return redirect(url_for('admin_bp.roles'))

@admin_bp.route('/admin/user/toggle-status/<int:uid>')
def toggle_user_status(uid):
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    u = db.session.get(User, uid)
    if u:
        if u.username == 'admin':
            flash('Không thể vô hiệu hóa tài khoản Quản trị hệ thống!', 'danger')
        else:
            u.is_active = not u.is_active
            db.session.commit()
            status_text = "kích hoạt" if u.is_active else "vô hiệu hóa"
            log_action(session['uid'], session['fullname'], f"{status_text.capitalize()} tài khoản", "Tài khoản", u.username)
            flash(f'Đã {status_text} tài khoản {u.username}!', 'success')
    return redirect(url_for('admin_bp.roles'))

@admin_bp.route('/logs', methods=['GET', 'POST'])
def logs():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    
    # Get distinct list of users for dropdown filter
    user_list = [u[0] for u in db.session.query(SystemLog.fullname).distinct().order_by(SystemLog.fullname).all() if u[0]]
    
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    user_str = request.args.get('user')
    q = SystemLog.query
    
    if start_str: 
        try: q = q.filter(SystemLog.created_at >= datetime.strptime(start_str, '%Y-%m-%d'))
        except: pass
    if end_str: 
        try: q = q.filter(SystemLog.created_at <= datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1))
        except: pass
    if user_str:
        q = q.filter(SystemLog.fullname.ilike(f'%{user_str}%'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'clear_all':
            clear_logs()
            flash('Đã xóa toàn bộ nhật ký!', 'success')
        elif action == 'clear_range':
            s = request.form.get('s_date')
            e = request.form.get('e_date')
            clear_logs(datetime.strptime(s, '%Y-%m-%d'), datetime.strptime(e, '%Y-%m-%d') + timedelta(days=1))
            flash(f'Đã xóa nhật ký từ {s} đến {e}', 'success')
        elif action == 'backup':
            logs_all = q.order_by(SystemLog.created_at.desc()).all()
            df = pd.DataFrame([{ 'Thời gian': l.created_at, 'Người dùng': l.fullname, 'Chức năng': l.module, 'Hành động': l.action, 'Chi tiết': l.details } for l in logs_all])
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
            return Response(output.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-disposition": "attachment; filename=system_logs.xlsx"})
        return redirect(url_for('admin_bp.logs'))

    return render_template('logs.html', logs=q.order_by(SystemLog.created_at.desc()).limit(200).all(), 
                           start=start_str, end=end_str, user_search=user_str, user_list=user_list)

@admin_bp.route('/admin/users/import', methods=['POST'])
def import_users():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    f = request.files.get('import_excel')
    role_id = request.form.get('role_id', 2) # Default to 2 if not selected
    
    if f and f.filename.endswith(('.xlsx', '.xls')):
        try:
            from utils import slugify_unit
            df = pd.read_excel(io.BytesIO(f.read())).fillna('')
            # Find the best column name for "Tên đơn vị"
            col_name = next((c for c in df.columns if 'đơn vị' in str(c).lower()), df.columns[0])
            
            for _, row in df.iterrows():
                unit_name = str(row.get(col_name, '')).strip()
                if not unit_name: continue
                
                # Auto-generate username
                base_uname = slugify_unit(unit_name)
                uname = base_uname
                
                # Handle duplicates
                counter = 2
                while User.query.filter_by(username=uname).first():
                    uname = f"{base_uname}_{counter}"
                    counter += 1
                
                u = User(
                    username=uname,
                    fullname=unit_name,
                    unit_area=unit_name,
                    role_id=role_id
                )
                u.set_password('123456')
                db.session.add(u)
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Import tài khoản hàng loạt", "Tài khoản", f"Số lượng: {len(df)}")
            flash('Đã nhập tài khoản thành công!', 'success')
        except Exception as e: 
            db.session.rollback()
            flash(f'Lỗi import: {e}', 'danger')
    return redirect(url_for('admin_bp.roles'))



@admin_bp.route('/admin/system/update', methods=['GET', 'POST'])
def system_update():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    if request.method == 'POST':
        f = request.files.get('update_pkg')
        if f and f.filename.endswith('.zip'):
            upload_dir = os.path.join(current_app.root_path, 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            p = os.path.join(upload_dir, 'pkg.zip')
            f.save(p)
            
            # 1. Validate ZIP
            if not zipfile.is_zipfile(p):
                flash('File không phải định dạng ZIP hợp lệ!', 'danger')
                return redirect(url_for('admin_bp.system_update'))
            
            try:
                # 2. Safety Backup
                backup_dir = os.path.join(current_app.root_path, 'backups', 'auto_update', datetime.now().strftime('%Y%m%d_%H%M%S'))
                os.makedirs(backup_dir, exist_ok=True)
                
                # Correct DB Path for backup
                db_path = os.path.join(current_app.root_path, 'pc06_system.db')
                if os.path.exists(db_path):
                    shutil.copy2(db_path, os.path.join(backup_dir, 'pc06_system_pre_update.db'))
                
                # Snapshot core logic folders
                for folder in ['routes', 'templates', 'static']:
                    src = os.path.join(current_app.root_path, folder)
                    if os.path.exists(src):
                        # Use dirs_exist_ok=True if available or just skip if exists
                        shutil.copytree(src, os.path.join(backup_dir, folder), dirs_exist_ok=True)
                
                # 3. Unpack and Restart
                shutil.unpack_archive(p, current_app.root_path)
                restart = os.path.join(current_app.root_path, 'tmp', 'restart.txt')
                os.makedirs(os.path.dirname(restart), exist_ok=True)
                with open(restart, 'w') as f_out: f_out.write(str(datetime.now()))
                
                log_action(session['uid'], session['fullname'], "Cập nhật hệ thống thành công (V3.5.2)", "Hệ thống")
                flash('Cập nhật thành công! Hệ thống đang khởi động lại...', 'success')
            except Exception as e: 
                flash(f'Lỗi cập nhật: {e}', 'danger')
                log_action(session['uid'], session['fullname'], f"Cập nhật thất bại: {e}", "Hệ thống")
        return redirect(url_for('admin_bp.system_update'))
    
    # Get git info
    git_info = {'branch': 'main', 'version': 'v3.5.0', 'commit_msg': 'Phiên bản hiện tại', 'commit_author': 'PC06', 'commit_date': datetime.now().strftime('%d/%m/%Y')}
    try:
        br = subprocess.run(['git', 'branch', '--show-current'], cwd=current_app.root_path, capture_output=True, text=True)
        if br.stdout: git_info['branch'] = br.stdout.strip()
        
        ver = subprocess.run(['git', 'describe', '--tags', '--always'], cwd=current_app.root_path, capture_output=True, text=True)
        if ver.stdout: git_info['version'] = ver.stdout.strip()
        
        msg = subprocess.run(['git', 'log', '-1', '--format=%s'], cwd=current_app.root_path, capture_output=True, text=True)
        if msg.stdout: git_info['commit_msg'] = msg.stdout.strip()
        
        author = subprocess.run(['git', 'log', '-1', '--format=%an'], cwd=current_app.root_path, capture_output=True, text=True)
        if author.stdout: git_info['commit_author'] = author.stdout.strip()
        
        date = subprocess.run(['git', 'log', '-1', '--format=%ad', '--date=short'], cwd=current_app.root_path, capture_output=True, text=True)
        if date.stdout: git_info['commit_date'] = date.stdout.strip()
    except: pass
    
    return render_template('system_update.html', git_info=git_info)

@admin_bp.route('/admin/system/git-pull', methods=['POST'])
def git_pull():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    
    try:
        # Check if git is available
        git_check = subprocess.run(['git', '--version'], capture_output=True, text=True)
        if git_check.returncode != 0:
            flash('Git không khả dụng trên máy chủ này!', 'danger')
            return redirect(url_for('admin_bp.system_update'))
        
        # Check if this is a git repo
        repo_check = subprocess.run(['git', 'rev-parse', '--git-dir'], 
                                cwd=current_app.root_path, capture_output=True, text=True)
        if repo_check.returncode != 0:
            flash('Thư mục này không phải là Git repository!', 'danger')
            return redirect(url_for('admin_bp.system_update'))
        
        # Check remote
        remote_check = subprocess.run(['git', 'remote', '-v'], 
                                    cwd=current_app.root_path, capture_output=True, text=True)
        if not remote_check.stdout.strip():
            flash('Chưa cấu hình Git remote! Vui lòng thêm remote: git remote add origin <url>', 'warning')
            return redirect(url_for('admin_bp.system_update'))
        
        # Perform Git Pull
        result = subprocess.run(['git', 'pull', 'origin', 'main'], 
                             cwd=current_app.root_path, 
                             capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            # Check if it's auth error
            if 'Permission denied' in result.stderr or 'authentication' in result.stderr.lower():
                flash('Lỗi xác thực GitHub! Cần cấu hình SSH Key hoặc Personal Access Token.', 'danger')
                log_action(session['uid'], session['fullname'], "Git pull thất bại: Lỗi xác thực", "Hệ thống")
            else:
                flash(f'Lỗi Git: {result.stderr}', 'danger')
                log_action(session['uid'], session['fullname'], f"Git pull thất bại: {result.stderr}", "Hệ thống")
            return redirect(url_for('admin_bp.system_update'))
        
        # Reload Database Migrations
        init_db(current_app)
        
        # Restart Passenger App
        restart_path = os.path.join(current_app.root_path, 'tmp', 'restart.txt')
        os.makedirs(os.path.dirname(restart_path), exist_ok=True)
        with open(restart_path, 'w') as f: f.write(str(datetime.now()))
        
        log_action(session['uid'], session['fullname'], "Cập nhật via GitHub thành công", "Hệ thống")
        flash(f'Đã cập nhật từ GitHub! {result.stdout}', 'success')
    except subprocess.TimeoutExpired:
        flash('Git pull quá thời gian! Kiểm tra kết nối mạng.', 'danger')
        log_action(session['uid'], session['fullname'], "Git pull thất bại: Timeout", "Hệ thống")
    except Exception as e:
        flash(f'Lỗi hệ thống: {str(e)}', 'danger')
        log_action(session['uid'], session['fullname'], f"Git pull thất bại: {str(e)}", "Hệ thống")
    
    return redirect(url_for('admin_bp.system_update'))

@admin_bp.route('/admin/git/status')
def git_status():
    """API: Get git status"""
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    try:
        result = subprocess.run(['git', 'status', '--short'], cwd=current_app.root_path, 
                              capture_output=True, text=True)
        return jsonify({'output': result.stdout or 'Không có thay đổi'})
    except Exception as e:
        return jsonify({'output': f'Lỗi: {str(e)}'})

@admin_bp.route('/admin/git/log')
def git_log():
    """API: Get recent commits"""
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    try:
        result = subprocess.run(['git', 'log', '--oneline', '-5'], cwd=current_app.root_path, 
                              capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        commits = []
        for line in lines:
            if ' ' in line:
                hash_msg = line.split(' ', 1)
                commits.append({'hash': hash_msg[0], 'msg': hash_msg[1] if len(hash_msg) > 1 else '', 
                              'author': 'Admin', 'date': ' recently'})
        return jsonify({'commits': commits[:5]})
    except Exception as e:
        return jsonify({'commits': []})

@admin_bp.route('/admin/git/remote', methods=['GET', 'POST'])
def git_remote():
    """API: Get or set git remote"""
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    
    if request.method == 'POST':
        remote_url = request.form.get('remote_url', '').strip()
        if not remote_url:
            return jsonify({'status': 'error', 'message': 'Thiếu URL'})
        
        try:
            # Check if remote exists
            check = subprocess.run(['git', 'remote'], cwd=current_app.root_path, capture_output=True, text=True)
            if 'origin' in check.stdout:
                # Update existing
                subprocess.run(['git', 'remote', 'set-url', 'origin', remote_url], 
                             cwd=current_app.root_path, capture_output=True)
            else:
                # Add new
                subprocess.run(['git', 'remote', 'add', 'origin', remote_url], 
                             cwd=current_app.root_path, capture_output=True)
            return jsonify({'status': 'success', 'message': 'Đã cập nhật remote URL'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    
    # GET: Return current remote
    try:
        result = subprocess.run(['git', 'remote', '-v'], cwd=current_app.root_path, 
                              capture_output=True, text=True)
        return jsonify({'output': result.stdout})
    except Exception as e:
        return jsonify({'output': '', 'error': str(e)})

@admin_bp.route('/admin/module-categories', methods=['GET', 'POST'])
def module_categories():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_group':
            name = request.form.get('name', '').strip()
            # Handle multiple checkboxes for linked modules
            targets = request.form.getlist('targets')
            links = ", ".join(targets)
            if name:
                db.session.add(CategoryGroup(name=name, linked_modules=links))
                db.session.commit()
                flash(f'Đã thêm danh mục hệ thống: {name}', 'success')
                
        elif action == 'delete_group':
            group_id = request.form.get('group_id')
            group = CategoryGroup.query.get(group_id)
            if group:
                name = group.name
                # Delete all items in group first
                CategoryItem.query.filter_by(group_id=group_id).delete()
                db.session.delete(group)
                db.session.commit()
                flash(f'Đã xóa danh mục hệ thống: {name}', 'warning')
                
        elif action == 'add_item':
            group_id = request.form.get('group_id')
            item_name = request.form.get('item_name', '').strip()
            if group_id and item_name:
                db.session.add(CategoryItem(group_id=group_id, name=item_name))
                db.session.commit()
                flash(f'Đã thêm thành phần: {item_name}', 'success')

        elif action == 'import_items_excel':
            group_id = request.form.get('group_id')
            excel_file = request.files.get('items_excel')

            if not group_id:
                flash('Thiếu nhóm danh mục để import!', 'danger')
            elif not excel_file or not excel_file.filename:
                flash('Vui lòng chọn file Excel để import!', 'danger')
            elif not excel_file.filename.lower().endswith(('.xlsx', '.xls')):
                flash('Chỉ hỗ trợ file .xlsx hoặc .xls', 'danger')
            else:
                try:
                    group = CategoryGroup.query.get(group_id)
                    if not group:
                        flash('Không tìm thấy nhóm danh mục!', 'danger')
                    else:
                        df = pd.read_excel(io.BytesIO(excel_file.read()), sheet_name=0)
                        if len(df.columns) == 0:
                            flash('File Excel không có cột dữ liệu!', 'danger')
                        else:
                            total_rows = len(df.index)
                            first_col = df.columns[0]
                            raw_values = [str(v).strip() for v in df[first_col].tolist() if pd.notna(v)]

                            seen = set()
                            deduped = []
                            for val in raw_values:
                                if not val:
                                    continue
                                key = val.lower()
                                if key in seen:
                                    continue
                                seen.add(key)
                                deduped.append(val)

                            existing = {
                                str(i.name).strip().lower()
                                for i in CategoryItem.query.filter_by(group_id=group_id).all()
                            }

                            added = 0
                            for name in deduped:
                                if name.lower() in existing:
                                    continue
                                db.session.add(CategoryItem(group_id=group_id, name=name))
                                existing.add(name.lower())
                                added += 1

                            db.session.commit()
                            skipped = max(total_rows - added, 0)
                            flash(
                                f'Import thành công: tổng dòng {total_rows}, thêm mới {added}, bỏ qua trống/trùng {skipped}.',
                                'success'
                            )
                except Exception as e:
                    db.session.rollback()
                    flash(f'Lỗi import Excel: {e}', 'danger')
                
        elif action == 'delete_item':
            item_id = request.form.get('item_id')
            item = CategoryItem.query.get(item_id)
            if item:
                name = item.name
                db.session.delete(item)
                db.session.commit()
                flash(f'Đã xóa thành phần: {name}', 'info')
                
        return redirect(url_for('admin_bp.module_categories'))

    # GET: Fetch all groups and their items
    groups = CategoryGroup.query.all()
    return render_template('module_categories.html', groups=groups)

@admin_bp.route('/admin/categories/delete-old/<string:cat_type>/<int:cat_id>')
def delete_category_old(cat_type, cat_id):
    # Keeping old route structure for any legacy links if needed, but logic is redirected
    return redirect(url_for('admin_bp.module_categories'))
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    force = request.args.get('force') == '1'
    try:
        obj = None
        count = 0
        if cat_type == 'news': 
            obj = NewsCategory.query.get(cat_id)
            if obj: count = NewsDoc.query.filter_by(category=obj.name).count()
        elif cat_type == 'lib': 
            obj = LibraryField.query.get(cat_id)
            if obj: count = DocumentLib.query.filter_by(category=obj.name).count()
        elif cat_type == 'contact': 
            obj = ContactGroup.query.get(cat_id)
            if obj: count = Contact.query.filter_by(contact_group=obj.name).count()
        elif cat_type == 'role_contact':
            obj = ContactRole.query.get(cat_id)
            if obj: count = Contact.query.filter_by(role=obj.name).count()
        elif cat_type == 'pro_unit': 
            obj = ProfessionalUnit.query.get(cat_id)
            if obj: 
                # Check NewsDoc and Task as ProfessionalUnit is used in both now
                count = Task.query.filter_by(domain=obj.name).count()
                count += NewsDoc.query.filter_by(category=obj.name).count()
        
        if not obj:
            flash('Không tìm thấy danh mục!', 'warning')
            return redirect(url_for('admin_bp.module_categories'))

        # Safety Check
        if count > 0 and not force:
            flash(f'CẢNH BÁO: Danh mục "{obj.name}" đang có {count} mục dữ liệu liên quan. <a href="{url_for("admin_bp.delete_category", cat_type=cat_type, cat_id=cat_id, force=1)}" class="fw-bold text-danger">XÁC NHẬN VẪN XÓA?</a>', 'warning')
            return redirect(url_for('admin_bp.module_categories'))

        name = obj.name
        db.session.delete(obj)
        db.session.commit()
        log_action(session['uid'], session['fullname'], f"Xóa danh mục {cat_type}", "Danh mục", name)
        flash(f'Đã xóa danh mục: {name}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa: {e}', 'danger')
    return redirect(url_for('admin_bp.module_categories'))
@admin_bp.route('/admin/fix-db')
def fix_db_manually():
    if not session.get('is_admin'): return "Unauthorized", 403
    from flask import current_app
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_path = db_uri.replace('sqlite:///', '')
    
    results = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Danh sách các cột cần bổ sung (nếu thiếu)
        migrations = [
            ("report_config", "description", "TEXT"),
            ("report_config", "is_daily", "BOOLEAN DEFAULT 0"),
            ("report_config", "author_name", "VARCHAR(100)")
        ]
        
        for table, col, col_type in migrations:
            try:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [c[1] for c in cursor.fetchall()]
                if col not in cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    conn.commit()
                    results.append(f"✅ Đã thêm cột {col} vào bảng {table}")
                else:
                    results.append(f"ℹ️ Cột {col} đã tồn tại trong bảng {table}")
            except Exception as e:
                results.append(f"❌ Lỗi tại bảng {table}, cột {col}: {str(e)}")
        
        conn.close()
        msg = "<br>".join(results)
        return f"<h3>KẾT QUẢ SỬA LỖI DATABASE:</h3>{msg}<br><br><a href='/admin-forms'>Quay lại Thiết lập mẫu</a>"
    except Exception as e:
        return f"<h3>LỖI NGHIÊM TRỌNG:</h3>{str(e)}"


# ==================== ZALO OA ROUTES ====================

@admin_bp.route('/admin/zalo', methods=['GET', 'POST'])
def zalo_config():
    """Trang cấu hình Zalo OA"""
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    if not session.get('is_admin'): flash('Bạn không có quyền truy cập', 'danger'); return redirect('/')
    
    from models import ZaloConfig, ZaloNotificationLog
    
    if request.method == 'POST':
        # Lưu hoặc cập nhật cấu hình
        config = ZaloConfig.query.filter_by(oa_id=request.form.get('oa_id')).first()
        if not config:
            config = ZaloConfig(oa_id=request.form.get('oa_id'))
            db.session.add(config)
        
        config.oa_id = request.form.get('oa_id')
        config.access_token = request.form.get('access_token')
        config.refresh_token = request.form.get('refresh_token')
        config.secret_key = request.form.get('secret_key')
        config.template_id = request.form.get('template_id')
        config.is_active = 'is_active' in request.form
        config.updated_at = datetime.now()
        
        db.session.commit()
        flash('Đã lưu cấu hình Zalo OA!', 'success')
        return redirect(url_for('admin_bp.zalo_config'))
    
    config = ZaloConfig.query.filter_by(is_active=True).first()
    logs = ZaloNotificationLog.query.order_by(ZaloNotificationLog.sent_at.desc()).limit(20).all()
    
    return render_template('zalo_config.html', config=config, logs=logs)


@admin_bp.route('/admin/zalo/test', methods=['POST'])
def zalo_test():
    """Test kết nối Zalo OA"""
    if not session.get('uid'): return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    from utils import get_zalo_config, send_zalo_message
    
    config = get_zalo_config()
    if not config:
        return jsonify({'status': 'error', 'message': 'Chưa cấu hình Zalo OA'})
    
    if not config.access_token:
        return jsonify({'status': 'error', 'message': 'Access Token trống'})
    
    # Thử gửi tin nhắn test (sẽ gửi đến chính mình)
    test_data = {
        'task_title': 'TEST - Kết nối Zalo OA',
        'deadline': datetime.now().strftime('%d/%m/%Y'),
        'status': 'Kết nối thành công!',
        'domain': 'PC06 System'
    }
    
    result = send_zalo_message(session.get('username'), config.template_id, test_data)
    return jsonify(result)


@admin_bp.route('/admin/zalo/trigger', methods=['POST'])
def zalo_trigger_check():
    """Trigger kiểm tra deadline và gửi thông báo (có thể gọi qua cronjob)"""
    if not session.get('uid') and not request.headers.get('X-API-Key') == 'pc06_internal':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    from utils import check_task_deadlines_and_notify
    
    result = check_task_deadlines_and_notify()
    return jsonify(result)


# ==================== SMS BRANDNAME ROUTES ====================

@admin_bp.route('/admin/sms', methods=['GET', 'POST'])
def sms_config():
    """Trang cấu hình SMS Brandname"""
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    if not session.get('is_admin'): flash('Bạn không có quyền truy cập', 'danger'); return redirect('/')
    
    from models import SMSConfig, SMSLog
    
    if request.method == 'POST':
        config = SMSConfig.query.first()
        if not config:
            config = SMSConfig()
            db.session.add(config)
        
        config.provider = request.form.get('provider')
        config.api_url = request.form.get('api_url')
        config.username = request.form.get('username')
        config.password = request.form.get('password')
        config.brandname = request.form.get('brandname')
        config.is_active = 'is_active' in request.form
        config.updated_at = datetime.now()
        
        db.session.commit()
        flash('Đã lưu cấu hình SMS!', 'success')
        return redirect(url_for('admin_bp.sms_config'))
    
    config = SMSConfig.query.first()
    logs = SMSLog.query.order_by(SMSLog.sent_at.desc()).limit(20).all()
    
    return render_template('sms_config.html', config=config, logs=logs)


@admin_bp.route('/admin/sms/test', methods=['POST'])
def sms_test():
    """Test gửi SMS"""
    if not session.get('uid'): return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    from utils import send_sms
    
    data = request.get_json()
    phone = data.get('phone')
    message = data.get('message')
    
    if not phone or not message:
        return jsonify({'status': 'failed', 'message': 'Thiếu số điện thoại hoặc nội dung'})
    
    result = send_sms(phone, message)
    return jsonify(result)


@admin_bp.route('/admin/sms/trigger', methods=['POST'])
def sms_trigger_check():
    """Trigger kiểm tra deadline và gửi SMS (cho cronjob)"""
    if not session.get('uid') and not request.headers.get('X-API-Key') == 'pc06_internal':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    from utils import check_sms_deadlines_and_notify
    
    result = check_sms_deadlines_and_notify()
    return jsonify(result)
