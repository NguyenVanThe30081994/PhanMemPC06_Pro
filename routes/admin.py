# -*- coding: utf-8 -*-
from flask import Blueprint, request, session, redirect, url_for, flash, jsonify, current_app, Response, send_from_directory
from models import db, User, AppRole, MasterData, SystemLog, Task, NewsDoc, DocumentLib, CategoryGroup, CategoryItem, ModuleRegistry, CategoryGroupModule, ModuleFieldBinding

import os, json, shutil, zipfile, io, sqlite3, subprocess
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None
from datetime import datetime, timedelta
from utils import log_action, clear_logs, init_db, render_auto_template as render_template
from category_helpers import slugify_code

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/admin')
def index():
    try:
        if not session.get('uid'): 
            return redirect(url_for('auth_bp.login'))
        
        # Basic Stats - simplified
        stats = {
            'users': 0,
            'reports': 0,
            'roles': 0,
            'news': 0,
            'tasks': 0
        }

        from models_reporting import FormTemplate, ReportingPeriod, ReportInstance
        
        try:
            stats['users'] = User.query.count()
        except: pass
        
        try:
            stats['reports'] = ReportInstance.query.count()
        except: pass
        
        try:
            stats['roles'] = AppRole.query.count()
        except: pass
        
        try:
            stats['news'] = NewsDoc.query.count()
        except: pass
        
        try:
            stats['tasks'] = Task.query.count()
        except: pass
        
        overdue_stats = []
        total_templates = 0
        
        # Calculate Overdue Reports - wrapped in try/except
        try:
            all_units = [u[0] for u in db.session.query(User.unit_area).distinct().all() if u[0]]
            total_templates = FormTemplate.query.filter_by(is_active=True).count()
            active_periods = ReportingPeriod.query.filter_by(is_locked=False).all()
            for period in active_periods:
                submitted = [
                    u[0] for u in db.session.query(ReportInstance.org_unit)
                    .filter(
                        ReportInstance.period_id == period.id,
                        ReportInstance.status == 'submitted',
                        ReportInstance.org_unit.in_(all_units)
                    )
                    .distinct()
                    .all()
                ]
                missing = [u for u in all_units if u not in submitted]
                if missing:
                    label = period.name
                    if period.template_id:
                        template = db.session.get(FormTemplate, period.template_id)
                        if template:
                            label = f"{template.name} - {period.name}"
                    overdue_stats.append({
                        'id': period.id,
                        'name': label,
                        'count': len(missing)
                    })
        except Exception as e:
            print(f"Error in admin dashboard queries: {e}")
            overdue_stats = []
            total_templates = 0

        # Query dữ liệu mới cho mobile dashboard - tạm bỏ
        new_tasks = []
        new_news = []
        new_docs = []
        try:
            new_reports = FormTemplate.query.filter_by(is_active=True).order_by(FormTemplate.created_at.desc()).limit(3).all()
        except Exception:
            new_reports = []
        
        logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(5).all()
        now_str = datetime.now().strftime('Ngày %d tháng %m, %Y')
        
        return render_template('admin_dashboard.html', 
            stats=stats, 
            overdue_stats=overdue_stats, 
            total_templates=total_templates, 
            now_str=now_str, 
            logs=logs,
            new_tasks=new_tasks,
            new_news=new_news,
            new_docs=new_docs,
            new_reports=new_reports)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Lỗi: {str(e)}", 500

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
                p_json = json.dumps({p: 1 for p in p_list}, ensure_ascii=False)
                db.session.add(AppRole(name=name, perms=p_json))
                log_action(session['uid'], session['fullname'], "Thêm vai trò", "Vai trò", name)
            elif action == 'edit_perms':
                rid = request.form['role_id']
                p_list = request.form.getlist('perms')
                r = db.session.get(AppRole, rid)
                if r:
                    r.perms = json.dumps({p: 1 for p in p_list}, ensure_ascii=False)
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
    
    unit_group = CategoryGroup.query.filter((CategoryGroup.name == 'Don vi') | (CategoryGroup.name == 'Đơn vị')).first()
    unit_cats = CategoryItem.query.filter_by(group_id=unit_group.id).all() if unit_group else []
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
                with open(restart, 'w', encoding='utf-8') as f_out: f_out.write(str(datetime.now()))
                
                log_action(session['uid'], session['fullname'], "Cập nhật hệ thống thành công (V3.5.0)", "Hệ thống")
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
            code = request.form.get('code', '').strip() or slugify_code(name)
            targets = request.form.getlist('targets')
            links = ", ".join(targets)
            if name:
                group = CategoryGroup(name=name, code=code, linked_modules=links, is_active=True)
                db.session.add(group)
                db.session.flush()
                for target_name in targets:
                    module = ModuleRegistry.query.filter_by(name=target_name).first()
                    if module:
                        db.session.add(CategoryGroupModule(group_id=group.id, module_id=module.id))
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

        elif action == 'save_binding':
            module_id = request.form.get('module_id')
            field_code = request.form.get('field_code', '').strip()
            field_label = request.form.get('field_label', '').strip()
            group_id = request.form.get('group_id')
            is_required = 1 if request.form.get('is_required') else 0

            if module_id and field_code and group_id:
                binding = ModuleFieldBinding.query.filter_by(module_id=module_id, field_code=field_code).first()
                if not binding:
                    binding = ModuleFieldBinding(module_id=module_id, field_code=field_code)
                    db.session.add(binding)
                binding.field_label = field_label or field_code
                binding.group_id = int(group_id)
                binding.is_required = bool(is_required)
                binding.allow_multiple_groups = False
                db.session.commit()
                flash('Đã cập nhật liên kết field thành công!', 'success')

        return redirect(url_for('admin_bp.module_categories'))

    groups = CategoryGroup.query.order_by(CategoryGroup.sort_order.asc(), CategoryGroup.name.asc()).all()
    modules = ModuleRegistry.query.order_by(ModuleRegistry.sort_order.asc(), ModuleRegistry.name.asc()).all()
    bindings = ModuleFieldBinding.query.all()
    binding_map = {(binding.module_id, binding.field_code): binding for binding in bindings}
    module_fields = {
        'news': [
            {'code': 'category', 'label': 'Danh mục bảng tin'}
        ],
        'library': [
            {'code': 'category', 'label': 'Danh mục thư viện'},
            {'code': 'document_type', 'label': 'Loại tài liệu'}
        ],
        'tasks': [
            {'code': 'domain', 'label': 'Đội nghiệp vụ'},
            {'code': 'task_type', 'label': 'Loại công việc'},
            {'code': 'priority', 'label': 'Mức độ ưu tiên'},
            {'code': 'initial_status', 'label': 'Trạng thái khởi tạo'}
        ],
        'contacts': [
            {'code': 'contact_group', 'label': 'Nhóm danh bạ'},
            {'code': 'role', 'label': 'Chức vụ'},
            {'code': 'unit_name', 'label': 'Đơn vị'},
            {'code': 'category', 'label': 'Lĩnh vực'}
        ]
    }
    return render_template('module_categories.html', groups=groups, modules=modules, module_fields=module_fields, binding_map=binding_map)

@admin_bp.route('/admin/categories/delete-old/<string:cat_type>/<int:cat_id>')
def delete_category_old(cat_type, cat_id):
    """Legacy route - chuyển hướng về module_categories"""
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
        return f"<h3>KẾT QUẢ SỬA LỖI DATABASE:</h3>{msg}<br><br><a href='/reporting'>Quay lại Reporting</a>"
    except Exception as e:
        return f"<h3>LỖI NGHIÊM TRỌNG:</h3>{str(e)}"
