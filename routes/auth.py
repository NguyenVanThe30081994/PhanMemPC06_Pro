# -*- coding: utf-8 -*-
from flask import Blueprint, current_app, request, session, redirect, url_for, flash
from datetime import datetime, timedelta
import time

from models import AppRole, LoginSecurityState, User, UserTrustedDevice, db
from utils import extract_unit_key, is_safe_redirect_url, log_action, push_notif, render_auto_template as render_template
from category_helpers import module_category_options, resolve_category_display
import re
import secrets
from security_utils.runtime_security import build_ip_network_hint, describe_user_agent, fingerprint_security_value
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
    state.last_failed_secret_hash = None


def _parse_lock_schedule(raw_value, fallback_seconds, fallback_multiplier_max):
    schedule = []
    for chunk in (raw_value or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except (TypeError, ValueError):
            continue
        if value > 0:
            schedule.append(value)

    if schedule:
        return schedule

    max_multiplier = max(1, int(fallback_multiplier_max or 1))
    base_lock_seconds = max(1, int(fallback_seconds or 1))
    return [base_lock_seconds * multiplier for multiplier in range(1, max_multiplier + 1)]


def _fingerprint_failed_secret(scope_key, secret_value):
    if not scope_key or not secret_value:
        return None

    return fingerprint_security_value(
        current_app.secret_key or current_app.config.get('SECRET_KEY') or '',
        f'login_failed:{scope_key}',
        secret_value,
    ) or None


def _safe_next_url(next_url, fallback_endpoint='admin_bp.index'):
    candidate = (next_url or '').strip()
    if candidate and is_safe_redirect_url(candidate):
        return candidate
    return url_for(fallback_endpoint)


def _current_user_agent_hash():
    return fingerprint_security_value(
        current_app.secret_key or current_app.config.get('SECRET_KEY') or '',
        'user_agent',
        request.headers.get('User-Agent', '') or '',
    )


def _issue_device_cookie(response, device_token):
    if not response or not device_token:
        return response
    response.set_cookie(
        current_app.config.get('SECURITY_DEVICE_COOKIE_NAME', 'pc06_device'),
        device_token,
        max_age=int(current_app.config.get('SECURITY_DEVICE_COOKIE_MAX_AGE', 31536000)),
        secure=bool(current_app.config.get('SESSION_COOKIE_SECURE', False)),
        httponly=True,
        samesite=current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax') or 'Lax',
        path='/',
    )
    return response


def _register_trusted_device(user, client_ip):
    cookie_name = current_app.config.get('SECURITY_DEVICE_COOKIE_NAME', 'pc06_device')
    raw_token = (request.cookies.get(cookie_name) or '').strip()
    issued_new_token = False
    if len(raw_token) < 24:
        raw_token = secrets.token_urlsafe(32)
        issued_new_token = True

    try:
        device_key = fingerprint_security_value(
            current_app.secret_key or current_app.config.get('SECRET_KEY') or '',
            'trusted_device',
            raw_token,
        )
        device_label = describe_user_agent(request.headers.get('User-Agent', ''))
        known_device = UserTrustedDevice.query.filter_by(user_id=user.id, device_key=device_key).first()
        is_new_device = known_device is None

        if is_new_device:
            known_device = UserTrustedDevice(
                user_id=user.id,
                device_key=device_key,
                device_label=device_label,
                first_seen_ip=(client_ip or 'unknown')[:64],
                last_seen_ip=(client_ip or 'unknown')[:64],
                last_user_agent=(request.headers.get('User-Agent', '') or '')[:255],
            )
            db.session.add(known_device)
        else:
            known_device.device_label = device_label
            known_device.last_seen_ip = (client_ip or 'unknown')[:64]
            known_device.last_user_agent = (request.headers.get('User-Agent', '') or '')[:255]
            known_device.last_seen_at = _now()

        db.session.commit()

        if is_new_device:
            timestamp = _now().strftime('%H:%M %d/%m/%Y UTC')
            push_notif(
                user.id,
                'Cảnh báo bảo mật',
                f'Đăng nhập mới từ {device_label} | IP {client_ip or "unknown"} | {timestamp}',
                '/notifications',
            )
            log_security_event('login_new_device', f'username={user.username} | device={device_label} | ip={client_ip}')

        return raw_token, device_key, issued_new_token or is_new_device
    except Exception as exc:
        db.session.rollback()
        log_security_event('login_device_tracking_failed', f'username={user.username} | error={exc}')
        return raw_token, '', issued_new_token


def _apply_session_security_state(user, client_ip, device_key=''):
    session['session_version'] = int(getattr(user, 'session_version', 0) or 0)
    session['session_user_agent_hash'] = _current_user_agent_hash()
    session['session_ip_hint'] = build_ip_network_hint(client_ip)
    session['session_device_key'] = device_key or ''
    session['security_step_up_required'] = False
    session['security_step_up_reason'] = ''
    session['reauth_at'] = time.time()


def _remaining_lock_seconds(state, now):
    if not state or not state.locked_until:
        return 0
    if state.locked_until <= now:
        lock_anchor = state.last_failed_at or state.locked_until
        state.locked_until = None
        _reset_failure_window(state)
        state.last_failed_at = lock_anchor
        return 0
    return int((state.locked_until - now).total_seconds())


def _should_decay_lock_count(state, decay_seconds, now):
    if not state or not state.lock_count or not decay_seconds or decay_seconds <= 0:
        return False
    if not state.last_failed_at:
        return True
    return (now - state.last_failed_at).total_seconds() > decay_seconds


def _record_login_failure(
    state,
    threshold,
    window_seconds,
    lock_schedule,
    now,
    decay_seconds,
    attempted_secret=None,
    collapse_repeated_secret=False,
):
    if not state:
        return 0

    remaining = _remaining_lock_seconds(state, now)
    if remaining > 0:
        return remaining

    if _should_decay_lock_count(state, decay_seconds, now):
        state.lock_count = 0

    if state.last_failed_at and (now - state.last_failed_at).total_seconds() > window_seconds:
        _reset_failure_window(state)

    if not state.first_failed_at:
        state.first_failed_at = now
    state.last_failed_at = now

    repeated_secret = False
    if collapse_repeated_secret:
        current_secret_hash = _fingerprint_failed_secret(state.scope_key, attempted_secret)
        repeated_secret = bool(current_secret_hash and current_secret_hash == state.last_failed_secret_hash)
        state.last_failed_secret_hash = current_secret_hash
    else:
        state.last_failed_secret_hash = None

    if not repeated_secret:
        state.failed_attempts = int(state.failed_attempts or 0) + 1

    if state.failed_attempts < threshold:
        return 0

    state.lock_count = int(state.lock_count or 0) + 1
    schedule_index = min(max(0, state.lock_count - 1), max(0, len(lock_schedule) - 1))
    state.locked_until = now + timedelta(seconds=lock_schedule[schedule_index])
    _reset_failure_window(state)
    state.last_failed_at = now
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


def _register_login_failure(username, password, client_ip):
    now = _now()
    window_seconds = int(current_app.config.get('LOGIN_FAILURE_WINDOW_SECONDS', 900))
    user_threshold = int(current_app.config.get('LOGIN_MAX_FAILURES_PER_USER', 5))
    ip_threshold = int(current_app.config.get('LOGIN_MAX_FAILURES_PER_IP', 20))
    lock_seconds = int(current_app.config.get('LOGIN_LOCKOUT_SECONDS', 900))
    lock_multiplier_max = int(current_app.config.get('LOGIN_LOCKOUT_MULTIPLIER_MAX', 4))
    user_lock_schedule = _parse_lock_schedule(
        current_app.config.get('LOGIN_USER_LOCK_SCHEDULE'),
        lock_seconds,
        lock_multiplier_max,
    )
    ip_lock_schedule = _parse_lock_schedule(
        current_app.config.get('LOGIN_IP_LOCK_SCHEDULE'),
        lock_seconds,
        lock_multiplier_max,
    )
    collapse_repeated_secret = bool(current_app.config.get('LOGIN_COLLAPSE_REPEAT_PASSWORD', True))
    lockout_decay_seconds = int(current_app.config.get('LOGIN_LOCKOUT_DECAY_SECONDS', 86400))

    username_state = _get_security_state('username', _normalize_scope_key(username))
    ip_state = _get_security_state('ip', client_ip)
    remaining = max(
        _record_login_failure(
            username_state,
            user_threshold,
            window_seconds,
            user_lock_schedule,
            now,
            lockout_decay_seconds,
            attempted_secret=password,
            collapse_repeated_secret=collapse_repeated_secret,
        ),
        _record_login_failure(
            ip_state,
            ip_threshold,
            window_seconds,
            ip_lock_schedule,
            now,
            lockout_decay_seconds,
            attempted_secret=None,
            collapse_repeated_secret=False,
        ),
    )
    db.session.commit()
    return remaining


def _register_login_success(username, client_ip):
    now = _now()
    _clear_login_security_state(_get_security_state('username', _normalize_scope_key(username)), now, client_ip)
    _clear_login_security_state(_get_security_state('ip', client_ip), now, client_ip)
    db.session.commit()


def _build_login_session(user, client_ip, csrf_rotate=True):
    """Shared logic to establish a full authenticated session for a user.
    Returns (response, should_refresh_device_cookie, device_token).
    """
    _register_login_success(user.username, client_ip)
    session.clear()
    if csrf_rotate:
        session['csrf_token'] = secrets.token_urlsafe(32)
    unit_display = resolve_category_display(
        user.unit_area,
        module_category_options('contacts', 'unit_name', 'Đơn vị'),
        fallback_label=user.unit_area or '',
    )['display_name']
    session['uid'] = user.id
    session['username'] = user.username
    session['fullname'] = user.fullname
    session['unit'] = unit_display
    session['unit_area'] = unit_display
    session['unit_area_ref'] = user.unit_area
    session['unit_key'] = user.unit_key or extract_unit_key(user.fullname or unit_display or user.username)
    session['role_id'] = user.role_id
    session['must_change'] = user.must_change_password

    # KHÔNG lưu is_admin vào session — mỗi request tính lại từ DB (permissions.load_current_authz)
    # để việc thay đổi/thu hồi vai trò có hiệu lực ngay, không chờ đăng nhập lại.
    from permissions import user_is_admin
    is_admin = user_is_admin(user)

    log_action(user.id, user.fullname, "Đăng nhập", "Hệ thống", "Đăng nhập thành công")
    log_security_event('login_success', f'username={user.username}')

    session['last_active'] = time.time()
    session['login_nonce'] = secrets.token_urlsafe(16)
    session.permanent = True
    device_token, device_key, should_refresh_device_cookie = _register_trusted_device(user, client_ip)
    _apply_session_security_state(user, client_ip, device_key=device_key)

    if user.must_change_password:
        flash('Bạn cần đổi mật khẩu trong lần đăng nhập đầu tiên.', 'warning')
        response = redirect(url_for('auth_bp.change_password'))
    elif is_admin:
        flash(f'Chào mừng trở lại, {user.fullname}!', 'success')
        response = redirect(url_for('admin_bp.index'))
    else:
        flash(f'Chào mừng trở lại, {user.fullname}!', 'success')
        response = redirect(url_for('tasks_bp.tasks'))
    if should_refresh_device_cookie:
        _issue_device_cookie(response, device_token)
    return response

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
            remaining = _register_login_failure(username, password, client_ip)
            log_security_event('login_failed', f'username={username} | reason={reason} | locked_seconds={remaining}')
            delay_ms = int(current_app.config.get('AUTH_FAILURE_DELAY_MS', 600))
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            flash(_get_lock_message(remaining) if remaining > 0 else 'Thông tin đăng nhập không hợp lệ.', 'danger')
        else:
            # 2FA TOTP (Đợt C3): nếu user đã bật, chuyển sang bước xác minh mã
            if usr.totp_enabled and usr.totp_secret_encrypted:
                session['twofactor_pending'] = {'uid': usr.id, 'ts': time.time(), 'attempts': 0}
                return redirect(url_for('auth_bp.two_factor_login'))
            response = _build_login_session(usr, client_ip)
            return response
        
    return render_template('login.html')


@auth_bp.route('/reauth', methods=['GET', 'POST'])
def reauthenticate():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    next_url = _safe_next_url(request.args.get('next') or request.form.get('next'))

    if request.method == 'POST':
        password = request.form.get('password') or ''
        usr = db.session.get(User, session['uid'])
        if usr and usr.is_active and usr.check_password(password):
            session['reauth_at'] = time.time()
            session['security_step_up_required'] = False
            session['security_step_up_reason'] = ''
            session['session_ip_hint'] = build_ip_network_hint(get_client_ip())
            session['session_user_agent_hash'] = _current_user_agent_hash()
            session['csrf_token'] = secrets.token_urlsafe(32)
            flash('Đã xác minh lại danh tính. Bạn có thể tiếp tục thao tác nhạy cảm.', 'success')
            log_security_event('reauth_success', f'username={usr.username}')
            return redirect(next_url)

        log_security_event('reauth_failed', f'uid={session.get("uid")}')
        flash('Xác minh lại thất bại. Vui lòng kiểm tra lại mật khẩu hiện tại.', 'danger')

    return render_template('reauth.html', next_url=next_url)

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
            usr.session_version = int(getattr(usr, 'session_version', 0) or 0) + 1
            db.session.commit()
            session['must_change'] = False
            session['session_version'] = usr.session_version
            session['reauth_at'] = time.time()
            session['csrf_token'] = secrets.token_urlsafe(32)
            flash('Đổi mật khẩu thành công!', 'success')
            return redirect('/')
        else:
            flash('Mật khẩu cũ không chính xác!', 'danger')
            
    return render_template('password.html')


# ═══════════════════════════════════════════════════════════════════════
#  Xác thực hai lớp TOTP — Đợt C3 (docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md)
#  Secret lưu MÃ HÓA (encrypt_secret_value, Fernet theo secret_key hệ thống).
#  Tự ngừng tham gia (opt-in từng user); tắt phải xác nhận mật khẩu.
# ═══════════════════════════════════════════════════════════════════════

TWOFACTOR_PENDING_SECONDS = 300   # phiên chờ nhập mã sau bước mật khẩu: 5 phút
TWOFACTOR_MAX_ATTEMPTS = 5        # số lần nhập sai tối đa mỗi phiên chờ


def _system_secret_key():
    return current_app.secret_key or current_app.config.get('SECRET_KEY') or ''


def _totp_secret_for(user):
    """Giải mã secret TOTP của user; trả '' nếu chưa có/lỗi giải mã."""
    if not user or not user.totp_secret_encrypted:
        return ''
    from security_utils.runtime_security import decrypt_secret_value
    try:
        return decrypt_secret_value(_system_secret_key(), user.totp_secret_encrypted)
    except ValueError:
        current_app.logger.error('Giải mã totp_secret thất bại cho uid=%s', getattr(user, 'id', '?'))
        return ''


def _twofactor_pending_user():
    """Trả về user đang ở bước chờ mã 2FA, hoặc None nếu phiên không hợp lệ."""
    pending = session.get('twofactor_pending')
    if not pending:
        return None
    if time.time() - float(pending.get('ts') or 0) > TWOFACTOR_PENDING_SECONDS:
        session.pop('twofactor_pending', None)
        return None
    usr = db.session.get(User, pending.get('uid')) if pending.get('uid') else None
    if not usr or not usr.is_active or not usr.totp_enabled:
        session.pop('twofactor_pending', None)
        return None
    return usr


@auth_bp.route('/login/two-factor', methods=['GET', 'POST'])
def two_factor_login():
    """Bước 2 của đăng nhập: nhập mã từ ứng dụng authenticator."""
    usr = _twofactor_pending_user()
    if not usr:
        flash('Phiên xác minh hai lớp đã hết hạn. Hãy đăng nhập lại.', 'warning')
        return redirect(url_for('auth_bp.login'))

    if request.method == 'POST':
        code = (request.form.get('code') or '').strip().replace(' ', '')
        pending = session['twofactor_pending']
        attempts = int(pending.get('attempts') or 0)
        verified = False
        if code and len(code) <= 8:
            import pyotp
            secret = _totp_secret_for(usr)
            if secret:
                verified = pyotp.TOTP(secret).verify(code, valid_window=1)
        if verified:
            session.pop('twofactor_pending', None)
            log_security_event('login_twofactor_success', f'username={usr.username}')
            return _build_login_session(usr, get_client_ip())
        attempts += 1
        log_security_event('login_twofactor_failed', f'username={usr.username} | attempt={attempts}')
        if attempts >= TWOFACTOR_MAX_ATTEMPTS:
            session.pop('twofactor_pending', None)
            flash('Bạn đã nhập sai mã xác minh quá số lần cho phép. Hãy đăng nhập lại từ đầu.', 'danger')
            return redirect(url_for('auth_bp.login'))
        session['twofactor_pending'] = {**pending, 'attempts': attempts}
        flash(f'Mã xác minh không đúng. Còn {TWOFACTOR_MAX_ATTEMPTS - attempts} lần thử.', 'danger')

    return render_template('two_factor_login.html')


@auth_bp.route('/security/two-factor', methods=['GET', 'POST'])
def two_factor_setup():
    """Trang quản lý xác thực hai lớp: bật mới / kích hoạt / tắt.

    Endpoint nằm trong SENSITIVE_REAUTH_ENDPOINTS → yêu cầu re-auth gần đây.
    """
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    usr = db.session.get(User, session['uid'])
    if not usr or not usr.is_active:
        return redirect(url_for('auth_bp.login'))

    qr_data_uri = None
    otpauth_url = None

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'begin':
            if usr.totp_enabled:
                flash('Xác thực hai lớp đang bật. Hãy tắt trước khi thiết lập lại.', 'warning')
            else:
                import pyotp
                from security_utils.runtime_security import encrypt_secret_value
                new_secret = pyotp.random_base32()
                try:
                    usr.totp_secret_encrypted = encrypt_secret_value(
                        _system_secret_key(), new_secret
                    )
                    db.session.commit()
                    log_security_event('twofactor_setup_started', f'username={usr.username}')
                    flash('Đã tạo khóa mới. Quét mã QR rồi nhập mã 6 số để kích hoạt.', 'success')
                except ValueError as enc_error:
                    db.session.rollback()
                    current_app.logger.error(f'twofactor setup encrypt failed: {enc_error}')
                    flash('Không thể tạo khóa bảo mật. Kiểm tra SECRET_KEY của hệ thống.', 'danger')
            return redirect(url_for('auth_bp.two_factor_setup'))

        if action == 'enable':
            code = (request.form.get('code') or '').strip().replace(' ', '')
            secret = _totp_secret_for(usr)
            ok = False
            if code and secret:
                import pyotp
                ok = pyotp.TOTP(secret).verify(code, valid_window=1)
            if ok:
                usr.totp_enabled = True
                db.session.commit()
                log_security_event('twofactor_enabled', f'username={usr.username}')
                flash('Đã bật xác thực hai lớp! Từ lần đăng nhập sau bạn cần nhập mã xác minh.', 'success')
            else:
                flash('Mã không đúng. Hãy kiểm tra giờ trên điện thoại và thử lại.', 'danger')
            return redirect(url_for('auth_bp.two_factor_setup'))

        if action == 'disable':
            password = request.form.get('password') or ''
            if usr.check_password(password):
                usr.totp_enabled = False
                usr.totp_secret_encrypted = None
                usr.session_version = int(usr.session_version or 0) + 1
                db.session.commit()
                session['session_version'] = usr.session_version
                log_security_event('twofactor_disabled', f'username={usr.username}')
                flash('Đã tắt xác thực hai lớp cho tài khoản của bạn.', 'info')
            else:
                log_security_event('twofactor_disable_failed', f'username={usr.username}')
                flash('Mật khẩu không chính xác, chưa tắt được xác thực hai lớp.', 'danger')
            return redirect(url_for('auth_bp.two_factor_setup'))

    # GET: dựng QR nếu có secret chưa kích hoạt
    if usr.totp_secret_encrypted and not usr.totp_enabled:
        secret = _totp_secret_for(usr)
        if secret:
            import base64
            import io as io_module

            import pyotp
            totp = pyotp.TOTP(secret)
            otpauth_url = totp.provisioning_uri(
                name=usr.email or usr.username, issuer_name='PC06'
            )
            try:
                import qrcode
                img = qrcode.make(otpauth_url)
                buf = io_module.BytesIO()
                img.save(buf, format='PNG')
                qr_data_uri = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
            except Exception as qr_error:  # thiếu Pillow/cấu hình ảnh — vẫn dùng otpauth dạng chữ
                current_app.logger.warning('Không dựng được mã QR 2FA: %s', qr_error)

    return render_template(
        'two_factor_setup.html',
        enabled=bool(usr.totp_enabled),
        has_pending_secret=bool(usr.totp_secret_encrypted) and not usr.totp_enabled,
        qr_data_uri=qr_data_uri,
        otpauth_url=otpauth_url,
    )
