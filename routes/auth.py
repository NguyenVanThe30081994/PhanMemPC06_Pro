# -*- coding: utf-8 -*-
from flask import Blueprint, current_app, request, session, redirect, url_for, flash
from datetime import datetime, timedelta
import time

from models import AppRole, LoginSecurityState, User, db
from utils import extract_unit_key, log_action, render_auto_template as render_template
from category_helpers import module_category_options, resolve_category_display
import re
import secrets
try:
    from security_utils.password_validator import validate_password
    from security_utils.security_helpers import get_client_ip, log_security_event
except ImportError:
    def validate_password(password):
        password_regex = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
        if not re.match(password_regex, password or ''):
            return False, 'Mật khẩu không đạt yêu cầu bảo mật.'
        return True, 'OK'

    def get_client_ip():
        forwarded = request.headers.get('X-Forwarded-For', '') or ''
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.remote_addr or 'unknown'

    def log_security_event(event, details=""):
        pass

auth_bp = Blueprint('auth_bp', __name__)


def _now():
    return datetime.utcnow()


def _normalize_scope_key(value):
    return (value or '').strip().lower()


def _get_lock_message(locked_seconds):
    minutes = max(1, int((locked_seconds + 59) // 60))
    return f'Tài khoản đang tạm khóa do nhập sai nhiều lần. Vui lòng thử lại sau khoảng {minutes} phút.'


def _get_security_state(scope_type, scope_key):
    if not scope_key:
        return None
    state = LoginSecurityState.query.filter_by(scope_type=scope_type, scope_key=scope_key).first()
    if not state:
        state = LoginSecurityState(scope_type=scope_type, scope_key=scope_key)
        db.session.add(state)
    return state


def _reset_failure_window(state):
    state.failed_attempts = 0
    state.first_failed_at = None
    state.last_failed_at = None


def _remaining_lock_seconds(state, now):
    if not state or not state.locked_until:
        return 0
    if state.locked_until <= now:
        state.locked_until = None
        _reset_failure_window(state)
        return 0
    return int((state.locked_until - now).total_seconds())


def _record_login_failure(state, threshold, window_seconds, lock_seconds, lock_multiplier_max, now):
    if not state:
        return 0

    remaining = _remaining_lock_seconds(state, now)
    if remaining > 0:
        return remaining

    if state.last_failed_at and (now - state.last_failed_at).total_seconds() > window_seconds:
        _reset_failure_window(state)

    if not state.first_failed_at:
        state.first_failed_at = now
    state.last_failed_at = now
    state.failed_attempts = int(state.failed_attempts or 0) + 1

    if state.failed_attempts < threshold:
        return 0

    state.lock_count = int(state.lock_count or 0) + 1
    multiplier = min(max(1, state.lock_count), max(1, lock_multiplier_max))
    state.locked_until = now + timedelta(seconds=lock_seconds * multiplier)
    _reset_failure_window(state)
    return int((state.locked_until - now).total_seconds())


def _clear_login_security_state(state, now, client_ip):
    if not state:
        return
    state.failed_attempts = 0
    state.lock_count = 0
    state.first_failed_at = None
    state.last_failed_at = None
    state.locked_until = None
    state.last_success_at = now
    state.last_success_ip = client_ip[:64] if client_ip else None


def _get_login_lock_seconds(username, client_ip):
    now = _now()
    username_state = _get_security_state('username', _normalize_scope_key(username))
    ip_state = _get_security_state('ip', client_ip)
    remaining = max(
        _remaining_lock_seconds(username_state, now),
        _remaining_lock_seconds(ip_state, now),
    )
    db.session.commit()
    return remaining


def _register_login_failure(username, client_ip):
    now = _now()
    window_seconds = int(current_app.config.get('LOGIN_FAILURE_WINDOW_SECONDS', 900))
    user_threshold = int(current_app.config.get('LOGIN_MAX_FAILURES_PER_USER', 5))
    ip_threshold = int(current_app.config.get('LOGIN_MAX_FAILURES_PER_IP', 20))
    lock_seconds = int(current_app.config.get('LOGIN_LOCKOUT_SECONDS', 900))
    lock_multiplier_max = int(current_app.config.get('LOGIN_LOCKOUT_MULTIPLIER_MAX', 4))

    username_state = _get_security_state('username', _normalize_scope_key(username))
    ip_state = _get_security_state('ip', client_ip)
    remaining = max(
        _record_login_failure(username_state, user_threshold, window_seconds, lock_seconds, lock_multiplier_max, now),
        _record_login_failure(ip_state, ip_threshold, window_seconds, lock_seconds, lock_multiplier_max, now),
    )
    db.session.commit()
    return remaining


def _register_login_success(username, client_ip):
    now = _now()
    _clear_login_security_state(_get_security_state('username', _normalize_scope_key(username)), now, client_ip)
    _clear_login_security_state(_get_security_state('ip', client_ip), now, client_ip)
    db.session.commit()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('uid'):
        return redirect(url_for('admin_bp.index'))
        
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        client_ip = get_client_ip()
        locked_seconds = _get_login_lock_seconds(username, client_ip)
        if locked_seconds > 0:
            flash(_get_lock_message(locked_seconds), 'danger')
            log_security_event('login_blocked_locked', f'username={username}')
            return render_template('login.html')

        usr = User.query.filter_by(username=username).first()

        login_success = bool(usr and usr.is_active and usr.check_password(password))

        if not login_success:
            reason = 'invalid_credentials'
            if usr and not usr.is_active:
                reason = 'inactive_account'
            elif usr:
                reason = 'wrong_password'
            remaining = _register_login_failure(username, client_ip)
            log_security_event('login_failed', f'username={username} | reason={reason} | locked_seconds={remaining}')
            delay_ms = int(current_app.config.get('AUTH_FAILURE_DELAY_MS', 600))
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            flash(_get_lock_message(remaining) if remaining > 0 else 'Thông tin đăng nhập không hợp lệ.', 'danger')
        else:
            _register_login_success(username, client_ip)
            session.clear()
            session['csrf_token'] = secrets.token_urlsafe(32)
            unit_display = resolve_category_display(
                usr.unit_area,
                module_category_options('contacts', 'unit_name', 'Đơn vị'),
                fallback_label=usr.unit_area or '',
            )['display_name']
            session['uid'] = usr.id
            session['username'] = usr.username
            session['fullname'] = usr.fullname
            session['unit'] = unit_display
            session['unit_area'] = unit_display
            session['unit_area_ref'] = usr.unit_area
            session['unit_key'] = usr.unit_key or extract_unit_key(usr.fullname or unit_display or usr.username)
            session['role_id'] = usr.role_id
            session['must_change'] = usr.must_change_password
            
            # Check if admin
            role = db.session.get(AppRole, usr.role_id)
            session['is_admin'] = (role and role.name == 'Quản trị hệ thống') or (usr.username == 'admin')
            
            # Log login
            log_action(usr.id, usr.fullname, "Đăng nhập", "Hệ thống", "Đăng nhập thành công")
            log_security_event('login_success', f'username={usr.username}')
            
            # Init activity timestamp for security monitor
            session['last_active'] = time.time()
            session['login_nonce'] = secrets.token_urlsafe(16)
            session.permanent = True  # Keep session persistent with PERMANENT_SESSION_LIFETIME (30 mins)

            
            if usr.must_change_password:
                flash('Bạn cần đổi mật khẩu trong lần đăng nhập đầu tiên.', 'warning')
                return redirect(url_for('auth_bp.change_password'))
                
            flash(f'Chào mừng trở lại, {usr.fullname}!', 'success')
            if session.get('is_admin'):
                return redirect(url_for('admin_bp.index'))
            return redirect(url_for('tasks_bp.tasks'))
        
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    session['csrf_token'] = secrets.token_urlsafe(32)
    flash('Đã đăng xuất an toàn!', 'info')
    return redirect(url_for('auth_bp.login', clear_storage='true'))

@auth_bp.route('/password', methods=['GET', 'POST'])
def change_password():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
        
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')

        is_valid, validation_message = validate_password(new_pw)
        if not is_valid:
            flash(validation_message, 'danger')
            return redirect(url_for('auth_bp.change_password'))
            
        usr = db.session.get(User, session['uid'])
        
        if usr and usr.check_password(old_pw):
            usr.set_password(new_pw)
            usr.must_change_password = False
            db.session.commit()
            session['must_change'] = False
            session['csrf_token'] = secrets.token_urlsafe(32)
            flash('Đổi mật khẩu thành công!', 'success')
            return redirect('/')
        else:
            flash('Mật khẩu cũ không chính xác!', 'danger')
            
    return render_template('password.html')
