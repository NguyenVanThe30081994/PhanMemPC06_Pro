from flask import Blueprint, render_template as flask_render_template, request, session, redirect, url_for, flash, jsonify
from models import db, User, AppRole, MasterData, SystemLog
from utils import log_action, render_auto_template as render_template
from werkzeug.security import check_password_hash
import json, re
from datetime import datetime

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('uid'):
        return redirect(url_for('admin_bp.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        usr = User.query.filter_by(username=username).first()
        
        if not usr:
            flash('Tài khoản không tồn tại trên hệ thống!', 'danger')
        elif not usr.is_active:
            flash('Tài khoản đã bị vô hiệu hóa! Vui lòng liên hệ quản trị viên.', 'warning')
        elif not usr.check_password(password):
            flash('Mật khẩu nhập vào không chính xác!', 'danger')
        else:
            session['uid'] = usr.id
            session['username'] = usr.username
            session['fullname'] = usr.fullname
            session['unit'] = usr.unit_area
            session['role_id'] = usr.role_id
            session['must_change'] = usr.must_change_password
            
            # Check if admin
            role = db.session.get(AppRole, usr.role_id)
            session['is_admin'] = (role and role.name == 'Quản trị hệ thống') or (usr.username == 'admin')
            
            # Log login
            log_action(usr.id, usr.fullname, "Đăng nhập", "Hệ thống", "Đăng nhập thành công")
            
            # Init activity timestamp for security monitor
            import time
            session['last_active'] = time.time()
            session.permanent = False # Shared across browser session only

            
            if usr.must_change_password:
                flash('Bạn cần đổi mật khẩu trong lần đăng nhập đầu tiên.', 'warning')
                return redirect(url_for('auth_bp.change_password'))
                
            flash(f'Chào mừng trở lại, {usr.fullname}!', 'success')
            return redirect('/admin')
        
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Đã đăng xuất an toàn!', 'info')
    return redirect(url_for('auth_bp.login', clear_storage='true'))

@auth_bp.route('/password', methods=['GET', 'POST'])
def change_password():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
        
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')
        
        # Strong password validation: 8+ chars, upper, lower, digit, special
        password_regex = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
        if not re.match(password_regex, new_pw):
            flash('Mật khẩu không đạt yêu cầu bảo mật: Cần ít nhất 8 ký tự, bao gồm chữ hoa, chữ thường, số và ký tự đặc biệt (@$!%*?&).', 'danger')
            return redirect(url_for('auth_bp.change_password'))
            
        usr = db.session.get(User, session['uid'])
        
        if usr and usr.check_password(old_pw):
            usr.set_password(new_pw)
            usr.must_change_password = False
            db.session.commit()
            session['must_change'] = False
            flash('Đổi mật khẩu thành công!', 'success')
            return redirect('/')
        else:
            flash('Mật khẩu cũ không chính xác!', 'danger')
            
    return render_template('password.html')
