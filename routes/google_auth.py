# -*- coding: utf-8 -*-
"""
Đăng nhập bằng tài khoản Google (OAuth 2.0 authorization code + PKCE).

Yêu cầu cấu hình (biến môi trường / .env):
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REDIRECT_URI   (tùy chọn — nếu trống tự suy từ host)
  GOOGLE_OAUTH_ALLOWED_DOMAINS (tùy chọn — giới hạn email theo đuôi miền, cách nhau bằng dấu phẩy)

Luồng hoạt động:
  1. GET /auth/google → tạo state + code_verifier (lưu session), redirect sang Google.
  2. Google gọi lại GET /auth/google/callback → trao đổi code lấy token, gọi userinfo
     để lấy email, tìm tài khoản PC06 có email khớp, đăng nhập như bình thường.
"""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime

import requests
from flask import Blueprint, current_app, flash, redirect, request, session, url_for

from models import AppRole, User, db
from utils import log_action, render_auto_template as render_template

google_auth_bp = Blueprint('google_auth_bp', __name__)

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'
GOOGLE_SCOPE = 'openid email profile'


def _oauth_config():
    client_id = (current_app.config.get('GOOGLE_OAUTH_CLIENT_ID') or '').strip()
    client_secret = (current_app.config.get('GOOGLE_OAUTH_CLIENT_SECRET') or '').strip()
    redirect_uri = (current_app.config.get('GOOGLE_OAUTH_REDIRECT_URI') or '').strip()
    if not redirect_uri:
        scheme = 'https' if request.is_secure else request.scheme
        redirect_uri = f"{scheme}://{request.host}/auth/google/callback"
    return {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
    }


def oauth_enabled():
    cfg = _oauth_config()
    return bool(cfg['client_id'] and cfg['client_secret'])


def _b64url_encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b'=').decode('ascii')


def _sign_state(raw_state):
    return hmac.new(
        (current_app.secret_key or '').encode('utf-8'),
        raw_state.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _is_state_valid(raw_state, signature):
    if not raw_state or not signature:
        return False
    expected = _sign_state(raw_state)
    return hmac.compare_digest(expected, signature)


@google_auth_bp.route('/auth/google')
def google_login():
    """Bắt đầu luồng đăng nhập Google."""
    if session.get('uid'):
        return redirect(url_for('admin_bp.index'))
    if not oauth_enabled():
        flash('Đăng nhập Google chưa được cấu hình. Vui lòng liên hệ quản trị viên.', 'danger')
        return redirect(url_for('auth_bp.login'))

    raw_state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = _b64url_encode(hashlib.sha256(code_verifier.encode('ascii')).digest())

    session['google_oauth_state'] = raw_state
    session['google_oauth_state_sig'] = _sign_state(raw_state)
    session['google_oauth_verifier'] = code_verifier

    cfg = _oauth_config()
    params = {
        'client_id': cfg['client_id'],
        'redirect_uri': cfg['redirect_uri'],
        'response_type': 'code',
        'scope': GOOGLE_SCOPE,
        'state': f"{raw_state}.{session['google_oauth_state_sig']}",
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'access_type': 'online',
        'prompt': 'select_account',
    }
    query = '&'.join(f'{key}={requests.utils.quote(str(value), safe="")}' for key, value in params.items())
    return redirect(f"{GOOGLE_AUTH_URL}?{query}")


@google_auth_bp.route('/auth/google/callback')
def google_callback():
    """Google chuyển hướng về đây sau khi người dùng đồng ý."""
    error = request.args.get('error')
    if error:
        flash(f'Không thể đăng nhập bằng Google: {error}', 'danger')
        return redirect(url_for('auth_bp.login'))

    # Kiểm tra state chống CSRF
    state_payload = request.args.get('state') or ''
    raw_state, dot, signature = state_payload.partition('.')
    expected_raw = session.get('google_oauth_state') or ''
    if not dot or raw_state != expected_raw or not _is_state_valid(raw_state, signature):
        flash('Phiên đăng nhập Google không hợp lệ. Vui lòng thử lại.', 'danger')
        return redirect(url_for('auth_bp.login'))
    code_verifier = session.get('google_oauth_verifier') or ''
    session.pop('google_oauth_state', None)
    session.pop('google_oauth_state_sig', None)
    session.pop('google_oauth_verifier', None)

    code = request.args.get('code') or ''
    if not code or not code_verifier:
        flash('Không nhận được mã xác thực từ Google. Vui lòng thử lại.', 'danger')
        return redirect(url_for('auth_bp.login'))

    cfg = _oauth_config()
    try:
        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                'code': code,
                'client_id': cfg['client_id'],
                'client_secret': cfg['client_secret'],
                'redirect_uri': cfg['redirect_uri'],
                'grant_type': 'authorization_code',
                'code_verifier': code_verifier,
            },
            timeout=20,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
    except requests.RequestException as exc:
        current_app.logger.error('Google OAuth token exchange failed: %s', exc)
        flash('Lỗi kết nối tới Google. Vui lòng thử lại sau.', 'danger')
        return redirect(url_for('auth_bp.login'))

    access_token = token_payload.get('access_token') or ''
    if not access_token:
        flash('Không nhận được quyền truy cập từ Google. Vui lòng thử lại.', 'danger')
        return redirect(url_for('auth_bp.login'))

    try:
        userinfo_response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=20,
        )
        userinfo_response.raise_for_status()
        google_info = userinfo_response.json()
    except requests.RequestException as exc:
        current_app.logger.error('Google OAuth userinfo failed: %s', exc)
        flash('Không thể xác minh thông tin tài khoản Google. Vui lòng thử lại.', 'danger')
        return redirect(url_for('auth_bp.login'))

    email = (google_info.get('email') or '').strip().lower()
    if not email:
        flash('Tài khoản Google không có email. Không thể xác thực.', 'danger')
        return redirect(url_for('auth_bp.login'))

    allowed_domains = current_app.config.get('GOOGLE_OAUTH_ALLOWED_DOMAINS') or []
    if allowed_domains and email.split('@')[-1] not in allowed_domains:
        flash('Email Google của bạn không thuộc phạm vi cho phép đăng nhập.', 'danger')
        return redirect(url_for('auth_bp.login'))

    usr = User.query.filter_by(email=email).first()
    if not usr:
        flash(
            'Không tìm thấy tài khoản PC06 ứng với email này. '
            'Hãy nhờ quản trị viên khai báo email của bạn trong mục Hệ thống → Người dùng, hoặc đăng nhập bằng tài khoản/mật khẩu.',
            'danger',
        )
        return redirect(url_for('auth_bp.login'))
    if not usr.is_active:
        flash('Tài khoản của bạn đã bị khóa. Vui lòng liên hệ quản trị viên.', 'danger')
        return redirect(url_for('auth_bp.login'))

    from routes.auth import _get_login_lock_seconds, _build_login_session
    from security_utils.security_helpers import get_client_ip, log_security_event
    client_ip = get_client_ip()
    locked_seconds = _get_login_lock_seconds(usr.username, client_ip)
    if locked_seconds > 0:
        from routes.auth import _get_lock_message
        flash(_get_lock_message(locked_seconds), 'danger')
        log_security_event('login_blocked_locked', f'username={usr.username} | via=google')
        return redirect(url_for('auth_bp.login'))

    try:
        response = _build_login_session(usr, client_ip)
        log_security_event('login_success', f'username={usr.username} | via=google')
        return response
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error('Google OAuth login finalization failed: %s', exc)
        flash('Đã xác thực Google nhưng không thể hoàn tất đăng nhập. Vui lòng thử lại.', 'danger')
        return redirect(url_for('auth_bp.login'))
