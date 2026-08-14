# -*- coding: utf-8 -*-
import os
import secrets
import sys
import sqlite3
from env_loader import load_env_file

# ── UTF-8 Environment (safe for Python 3.9 on Mắt Bão / cPanel) ──
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ.setdefault('LC_ALL', 'C.UTF-8')
os.environ.setdefault('LANG', 'C.UTF-8')

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if os.environ.get('PC06_PASSENGER') != '1':
    load_env_file(os.path.join(APP_ROOT, '.env'), override=True)

# Reconfigure stdout/stderr to UTF-8 (Python 3.7+)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import logging
from logging.handlers import RotatingFileHandler
import json
import time
from urllib.parse import urlparse
from flask import Flask, flash, session, request, redirect, url_for, send_file, send_from_directory, render_template, g, jsonify, Response
from datetime import datetime, timedelta
from werkzeug.exceptions import HTTPException
from sqlalchemy import event
from sqlalchemy.engine import Engine
from models import db, AppRole, DocumentLib, NewsDoc, NotificationDoc, User
from storage import bootstrap_storage, build_storage_layout
from security_utils.runtime_security import (
    build_ip_network_hint,
    ensure_persistent_secret_key,
    fingerprint_security_value,
    resolve_safe_path,
)
from security_utils.security_helpers import get_client_ip, log_security_event
from utils import (
    get_perms_labels,
    has_any_module_permission,
    has_module_permission,
    init_db,
    is_mobile_device,
    normalize_permission_payload,
)

# --- RELIABLE PATH RESOLUTION (Improved for Mắt Bão/Passenger) ---
basedir = APP_ROOT
TEMPLATE_DIR = os.path.join(basedir, 'templates')
STATIC_DIR = os.path.join(basedir, 'static')
storage_layout = build_storage_layout(basedir)
bootstrap_storage(storage_layout, basedir)

UPLOAD_FOLDER = storage_layout['UPLOAD_FOLDER']
TASK_FOLDER = storage_layout['TASK_FOLDER']
LIB_FOLDER = storage_layout['LIB_FOLDER']
BACKUP_FOLDER = storage_layout['BACKUP_FOLDER']
LOG_DIR = storage_layout['LOG_DIR']
TMP_FOLDER = storage_layout['TMP_FOLDER']

app = Flask(__name__, 
            root_path=basedir, 
            template_folder=TEMPLATE_DIR, 
            static_folder=STATIC_DIR)

# Import config
try:
    from config import (
        SECRET_KEY,
        SESSION_LIFETIME,
        MAX_CONTENT_LENGTH,
        MAX_FORM_PARTS,
        SESSION_COOKIE_SECURE,
        SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE,
        SESSION_COOKIE_NAME,
        SESSION_REFRESH_EACH_REQUEST,
        CSRF_TOKEN_LIFETIME,
        HSTS_MAX_AGE_SECONDS,
        HSTS_INCLUDE_SUBDOMAINS,
        HSTS_PRELOAD,
        REFERRER_POLICY,
        LOGIN_FAILURE_WINDOW_SECONDS,
        LOGIN_MAX_FAILURES_PER_USER,
        LOGIN_MAX_FAILURES_PER_IP,
        LOGIN_LOCKOUT_SECONDS,
        LOGIN_LOCKOUT_MULTIPLIER_MAX,
        SECURITY_REAUTH_WINDOW_SECONDS,
        SECURITY_DEVICE_COOKIE_NAME,
        SECURITY_DEVICE_COOKIE_MAX_AGE,
        DEBUG,
        AUTH_FAILURE_DELAY_MS,
        RATE_LIMIT_WINDOW_SECONDS,
        RATE_LIMIT_MAX_REQUESTS,
        RATE_LIMIT_MAX_API_REQUESTS,
        TRUSTED_PROXY_CIDRS,
        ADMIN_DB_RESET_ENABLED,
        ADMIN_DB_BACKUP_ENABLED,
        WEB_SYSTEM_UPDATE_ENABLED,
        WEB_GIT_PULL_ENABLED,
    )
except ImportError:
    SECRET_KEY = (os.environ.get('SECRET_KEY') or '').strip()
    SESSION_LIFETIME = 28800
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_NAME = 'pc06_session'
    SESSION_REFRESH_EACH_REQUEST = True
    CSRF_TOKEN_LIFETIME = 3600
    HSTS_MAX_AGE_SECONDS = 31536000
    HSTS_INCLUDE_SUBDOMAINS = True
    HSTS_PRELOAD = False
    REFERRER_POLICY = 'strict-origin-when-cross-origin'
    LOGIN_FAILURE_WINDOW_SECONDS = 900
    LOGIN_MAX_FAILURES_PER_USER = 5
    LOGIN_MAX_FAILURES_PER_IP = 20
    LOGIN_LOCKOUT_SECONDS = 900
    LOGIN_LOCKOUT_MULTIPLIER_MAX = 4
    SECURITY_REAUTH_WINDOW_SECONDS = 900
    SECURITY_DEVICE_COOKIE_NAME = 'pc06_device'
    SECURITY_DEVICE_COOKIE_MAX_AGE = 31536000
    DEBUG = False
    AUTH_FAILURE_DELAY_MS = 600
    RATE_LIMIT_WINDOW_SECONDS = 60
    RATE_LIMIT_MAX_REQUESTS = 240
    RATE_LIMIT_MAX_API_REQUESTS = 120
    TRUSTED_PROXY_CIDRS = '127.0.0.1/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16'
    ADMIN_DB_RESET_ENABLED = False
    ADMIN_DB_BACKUP_ENABLED = False
    WEB_SYSTEM_UPDATE_ENABLED = False
    WEB_GIT_PULL_ENABLED = False

SECRET_KEY = ensure_persistent_secret_key(storage_layout['data_root'], SECRET_KEY)
app.secret_key = SECRET_KEY
app.config['SECRET_KEY'] = SECRET_KEY
app.config['JSON_AS_ASCII'] = False  # Giữ nguyên tiếng Việt trong jsonify()
app.config['PC06_DATA_ROOT'] = storage_layout['data_root']
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['TASK_FOLDER'] = TASK_FOLDER
app.config['LIB_FOLDER'] = LIB_FOLDER
app.config['BACKUP_FOLDER'] = BACKUP_FOLDER
app.config['LOG_DIR'] = LOG_DIR
app.config['TMP_FOLDER'] = TMP_FOLDER
app.config['SQLITE_DB_PATH'] = storage_layout['SQLITE_DB_PATH']

# ==================== FILE LOGGING ====================
os.makedirs(LOG_DIR, exist_ok=True)

# Configure logging
log_file = os.path.join(LOG_DIR, 'app.log')
file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

# ==================== SECURITY CONFIG ====================
# Session Security
app.config['SESSION_COOKIE_SECURE'] = SESSION_COOKIE_SECURE  # Set True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent XSS stealing cookies
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['SESSION_COOKIE_NAME'] = SESSION_COOKIE_NAME
app.config['SESSION_REFRESH_EACH_REQUEST'] = SESSION_REFRESH_EACH_REQUEST
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=SESSION_LIFETIME)  # 30 min timeout
app.config['PC06_SESSION_TIMEOUT_SECONDS'] = SESSION_LIFETIME
app.config['HSTS_MAX_AGE_SECONDS'] = HSTS_MAX_AGE_SECONDS
app.config['HSTS_INCLUDE_SUBDOMAINS'] = HSTS_INCLUDE_SUBDOMAINS
app.config['HSTS_PRELOAD'] = HSTS_PRELOAD
app.config['REFERRER_POLICY'] = REFERRER_POLICY
app.config['LOGIN_FAILURE_WINDOW_SECONDS'] = LOGIN_FAILURE_WINDOW_SECONDS
app.config['LOGIN_MAX_FAILURES_PER_USER'] = LOGIN_MAX_FAILURES_PER_USER
app.config['LOGIN_MAX_FAILURES_PER_IP'] = LOGIN_MAX_FAILURES_PER_IP
app.config['LOGIN_LOCKOUT_SECONDS'] = LOGIN_LOCKOUT_SECONDS
app.config['LOGIN_LOCKOUT_MULTIPLIER_MAX'] = LOGIN_LOCKOUT_MULTIPLIER_MAX
app.config['SECURITY_REAUTH_WINDOW_SECONDS'] = SECURITY_REAUTH_WINDOW_SECONDS
app.config['SECURITY_DEVICE_COOKIE_NAME'] = SECURITY_DEVICE_COOKIE_NAME
app.config['SECURITY_DEVICE_COOKIE_MAX_AGE'] = SECURITY_DEVICE_COOKIE_MAX_AGE
app.config['AUTH_FAILURE_DELAY_MS'] = AUTH_FAILURE_DELAY_MS
app.config['RATE_LIMIT_WINDOW_SECONDS'] = RATE_LIMIT_WINDOW_SECONDS
app.config['RATE_LIMIT_MAX_REQUESTS'] = RATE_LIMIT_MAX_REQUESTS
app.config['RATE_LIMIT_MAX_API_REQUESTS'] = RATE_LIMIT_MAX_API_REQUESTS
app.config['TRUSTED_PROXY_CIDRS'] = TRUSTED_PROXY_CIDRS
app.config['ADMIN_DB_RESET_ENABLED'] = ADMIN_DB_RESET_ENABLED
app.config['ADMIN_DB_BACKUP_ENABLED'] = ADMIN_DB_BACKUP_ENABLED
app.config['WEB_SYSTEM_UPDATE_ENABLED'] = WEB_SYSTEM_UPDATE_ENABLED
app.config['WEB_GIT_PULL_ENABLED'] = WEB_GIT_PULL_ENABLED

# CSRF Protection
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = CSRF_TOKEN_LIFETIME  # 1 hour token lifetime

# File Upload Security
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH  # 100MB max
app.config['MAX_FORM_PARTS'] = MAX_FORM_PARTS  # cho wizard đề cương lớn (>1000 field)

# Allowed extensions for file upload
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'zip', 'rar', 'ppt', 'pptx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== DATABASE CONFIG ====================
app.config['SQLALCHEMY_DATABASE_URI'] = storage_layout['DATABASE_URI']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
engine_options = {
    'pool_pre_ping': True,
}
if storage_layout['DATABASE_URI'].startswith(('mysql+pymysql://', 'mariadb+pymysql://')):
    engine_options.update(
        {
            'pool_recycle': 3600,
            'connect_args': {
                'charset': 'utf8mb4',
                'init_command': "SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci",
            },
        }
    )
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options

for folder in [UPLOAD_FOLDER, TASK_FOLDER, LIB_FOLDER, BACKUP_FOLDER, TMP_FOLDER]:
    os.makedirs(folder, exist_ok=True)


@event.listens_for(Engine, 'connect')
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.execute('PRAGMA synchronous=FULL')
        cursor.execute('PRAGMA journal_mode=PERSIST')
    finally:
        cursor.close()

# Security Headers Configuration
def _request_is_secure():
    forwarded_proto = (request.headers.get('X-Forwarded-Proto') or '').lower()
    forwarded_ssl = (request.headers.get('X-Forwarded-SSL') or '').lower()
    return bool(request.is_secure or forwarded_proto == 'https' or forwarded_ssl == 'on')


def _get_csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


def _rotate_csrf_token():
    token = secrets.token_urlsafe(32)
    session['csrf_token'] = token
    return token


def _is_same_origin(target_url):
    if not target_url:
        return False
    parsed = urlparse(target_url)
    if not parsed.scheme or not parsed.netloc:
        return True
    expected_scheme = 'https' if _request_is_secure() else request.scheme
    return parsed.scheme == expected_scheme and parsed.netloc == request.host


SENSITIVE_REAUTH_ENDPOINTS = {
    'admin_bp.roles',
    'admin_bp.db_tool',
    'admin_bp.db_manage',
    'admin_bp.reset_users_password_bulk',
    'admin_bp.system_update',
    'admin_bp.git_pull',
}


def _current_user_agent_hash():
    return fingerprint_security_value(
        app.secret_key or app.config.get('SECRET_KEY') or '',
        'user_agent',
        request.headers.get('User-Agent', '') or '',
    )


def _get_reauth_redirect_target():
    for candidate in (request.referrer, request.path):
        if candidate and _is_same_origin(candidate):
            return candidate
    return url_for('admin_bp.index')


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # XSS Protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Prevent content type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Referrer Policy
    response.headers['Referrer-Policy'] = app.config.get('REFERRER_POLICY', 'strict-origin-when-cross-origin')
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https:; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "object-src 'none';"
    )
    if _request_is_secure():
        hsts_value = f"max-age={int(app.config.get('HSTS_MAX_AGE_SECONDS', 31536000))}"
        if app.config.get('HSTS_INCLUDE_SUBDOMAINS', True):
            hsts_value += '; includeSubDomains'
        if app.config.get('HSTS_PRELOAD', False):
            hsts_value += '; preload'
        response.headers['Strict-Transport-Security'] = hsts_value
    if request.endpoint in {'auth_bp.login', 'auth_bp.logout', 'auth_bp.change_password'} or session.get('uid'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    if (request.args.get('clear_storage') or '').strip().lower() == 'true':
        response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage"'
    return response

# Rate limiting storage: {(ip, scope): [timestamp, ...]}
from collections import defaultdict, deque

rate_limit_store = defaultdict(deque)

@app.before_request
def check_rate_limit():
    """Apply a small sliding-window rate limit per IP and request scope."""
    if request.path.startswith('/static') or request.path == '/favicon.ico':
        return

    if request.endpoint == 'auth_bp.login':
        return

    from security_utils.security_helpers import get_client_ip
    client_ip = get_client_ip()
    if not client_ip:
        return

    current_time = datetime.now().timestamp()
    window_seconds = int(app.config.get('RATE_LIMIT_WINDOW_SECONDS', 60))
    default_limit = int(app.config.get('RATE_LIMIT_MAX_REQUESTS', 240))
    api_limit = int(app.config.get('RATE_LIMIT_MAX_API_REQUESTS', 120))
    limit = api_limit if request.path.startswith('/api/') else default_limit
    scope = request.endpoint or request.path
    bucket = rate_limit_store[(client_ip, scope)]
    cutoff = current_time - window_seconds

    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= limit:
        return jsonify({'error': 'Quá nhiều yêu cầu. Vui lòng thử lại sau.'}), 429

    bucket.append(current_time)

db.init_app(app)

with app.app_context():
    try: 
        init_db(app)
    except Exception as e: 
        print(f"Startup DB Error: {e}")

from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.portal import portal_bp
from routes.tasks import tasks_bp
from routes.api import api_bp
from routes.shortlink import shortlink_bp
from routes.health import health_bp
from routes.outline import outline_bp
from routes.google_auth import google_auth_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(api_bp)
app.register_blueprint(shortlink_bp)
app.register_blueprint(health_bp)
app.register_blueprint(outline_bp)
app.register_blueprint(google_auth_bp)

@app.context_processor
def inject_security_tokens():
    return {
        'csrf_token': _get_csrf_token,
        'csrf_token_value': _get_csrf_token(),
    }


@app.before_request
def check_auth():
    # 0. Device Detection
    g.is_mobile = is_mobile_device()

    public_endpoints = {
        'auth_bp.login',
        'portal_bp.martyr_adn_map',
        'api_bp.get_custom_satellite_points',
        'api_bp.save_custom_satellite_point',
        'api_bp.delete_custom_satellite_point',
        'api_bp.resolve_maps_url',
        'shortlink_bp.redirect_short_link',
        'shortlink_bp.get_qr',
        'health_bp.health_check',
        'health_bp.ping',
        'google_auth_bp.google_login',
        'google_auth_bp.google_callback',
        'security_txt',
        'security_txt_well_known',
        'favicon',
    }
    if request.endpoint in public_endpoints or (request.endpoint and request.endpoint.startswith('static')):
        return

    # 1. Inactivity Check
    if session.get('uid'):
        import time
        last_active = session.get('last_active')
        now = time.time()
        session_timeout = int(app.config.get('PC06_SESSION_TIMEOUT_SECONDS') or SESSION_LIFETIME or 1800)
        if last_active and (now - last_active) > session_timeout:
            session.clear()
            return redirect(url_for('auth_bp.login'))
        session['last_active'] = now
    if not session.get('uid'):
        if request.endpoint and request.endpoint.startswith('api_bp.'):
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('auth_bp.login'))

    if session.get('must_change') and request.endpoint not in {'auth_bp.change_password', 'auth_bp.logout'}:
        return redirect(url_for('auth_bp.change_password'))


@app.before_request
def enforce_session_integrity():
    uid = session.get('uid')
    if not uid:
        return

    user = db.session.get(User, uid)
    if not user or not user.is_active:
        session.clear()
        session['csrf_token'] = secrets.token_urlsafe(32)
        return redirect(url_for('auth_bp.login', clear_storage='true'))

    session_version = int(session.get('session_version', -1))
    current_version = int(getattr(user, 'session_version', 0) or 0)
    if session_version != current_version:
        log_security_event('session_revoked', f'uid={uid} | reason=session_version_changed')
        session.clear()
        session['csrf_token'] = secrets.token_urlsafe(32)
        flash('Phiên đăng nhập đã hết hiệu lực do mật khẩu hoặc thông tin bảo mật vừa thay đổi.', 'warning')
        return redirect(url_for('auth_bp.login', clear_storage='true'))

    expected_user_agent_hash = session.get('session_user_agent_hash') or ''
    current_user_agent_hash = _current_user_agent_hash()
    if expected_user_agent_hash and current_user_agent_hash and not secrets.compare_digest(
        str(expected_user_agent_hash),
        str(current_user_agent_hash),
    ):
        log_security_event('session_binding_mismatch', f'uid={uid} | reason=user_agent_changed')
        session.clear()
        session['csrf_token'] = secrets.token_urlsafe(32)
        flash('Phiên đăng nhập không còn an toàn. Vui lòng đăng nhập lại.', 'warning')
        return redirect(url_for('auth_bp.login', clear_storage='true'))

    current_ip_hint = build_ip_network_hint(get_client_ip())
    stored_ip_hint = session.get('session_ip_hint') or ''
    if stored_ip_hint and current_ip_hint and stored_ip_hint != current_ip_hint:
        session['security_step_up_required'] = True
        session['security_step_up_reason'] = 'network_change'


@app.before_request
def enforce_step_up_auth():
    if not session.get('uid'):
        return
    from permissions import current_is_admin
    if not current_is_admin():
        return
    if request.endpoint == 'auth_bp.reauthenticate':
        return
    if request.endpoint not in SENSITIVE_REAUTH_ENDPOINTS:
        return

    reauth_window = int(app.config.get('SECURITY_REAUTH_WINDOW_SECONDS', 900))
    reauth_at = float(session.get('reauth_at') or 0)
    requires_reauth = (
        not reauth_at
        or (time.time() - reauth_at) > reauth_window
        or bool(session.get('security_step_up_required'))
    )
    if not requires_reauth:
        return

    if request.method in {'GET', 'HEAD', 'OPTIONS'}:
        flash('Vui lòng xác minh lại mật khẩu trước khi truy cập khu vực quản trị nhạy cảm.', 'warning')
        return redirect(url_for('auth_bp.reauthenticate', next=request.full_path.rstrip('?')))

    flash('Phiên xác minh đã hết hạn hoặc bối cảnh đăng nhập thay đổi. Hãy xác minh lại rồi thực hiện thao tác một lần nữa.', 'warning')
    return redirect(url_for('auth_bp.reauthenticate', next=_get_reauth_redirect_target()))


@app.before_request
def enforce_csrf_protection():
    if request.method in {'GET', 'HEAD', 'OPTIONS'}:
        return
    if request.endpoint and request.endpoint.startswith('static'):
        return

    csrf_exempt_endpoints = {
        'google_auth_bp.google_callback',  # Google redirects back with its own Referer
    }
    if request.endpoint in csrf_exempt_endpoints:
        return

    origin = request.headers.get('Origin')
    referer = request.headers.get('Referer')
    if origin and not _is_same_origin(origin):
        return jsonify({'error': 'CSRF validation failed.'}), 400
    if referer and not _is_same_origin(referer):
        return jsonify({'error': 'CSRF validation failed.'}), 400

    token = request.headers.get('X-CSRF-Token')
    if not token:
        token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')

    expected_token = session.get('csrf_token')
    if not expected_token or not token or not secrets.compare_digest(str(token), str(expected_token)):
        if request.endpoint and request.endpoint.startswith('api_bp.'):
            return jsonify({'error': 'CSRF validation failed.'}), 400
        return ('Yêu cầu không hợp lệ hoặc phiên làm việc đã hết hạn.', 400)


def build_session_activity_marker():
    uid = session.get('uid')
    login_nonce = session.get('login_nonce')
    if not uid or not login_nonce:
        return ''
    return f"{uid}:{login_nonce}"

@app.context_processor
def inject_global_data():
    # Authz luôn được tính lại từ DB mỗi request (không tin giá trị cũ trong session)
    from permissions import load_current_authz
    authz = load_current_authz()
    is_admin = authz["is_admin"]
    role_name = authz["role_name"]
    perms = authz["perms"]

    def can_module(module_code, tier='view'):
        return has_module_permission(perms, module_code, tier=tier, is_admin=is_admin, role_name=role_name)

    def can_any_module(module_codes, tier='view'):
        return has_any_module_permission(perms, module_codes, tier=tier, is_admin=is_admin, role_name=role_name)

    def can_manage_with_system(module_code):
        return bool(can_module(module_code, 'process') or can_module('sys', 'process'))

    if not session.get('uid'):
        return dict(
            perms=perms,
            role_name=role_name,
            fullname='',
            is_admin=is_admin,
            version="3.5.0",
            session_timeout_ms=int(app.config.get('PC06_SESSION_TIMEOUT_SECONDS', SESSION_LIFETIME)) * 1000,
            session_activity_marker='',
            get_labels=get_perms_labels,
            can_module=can_module,
            can_any_module=can_any_module,
            can_manage_with_system=can_manage_with_system,
        )

    return dict(
        perms=perms,
        role_name=role_name,
        fullname=session.get('fullname', ''),
        is_admin=is_admin,
        version="3.5.0",
        session_timeout_ms=int(app.config.get('PC06_SESSION_TIMEOUT_SECONDS', SESSION_LIFETIME)) * 1000,
        session_activity_marker=build_session_activity_marker(),
        get_labels=get_perms_labels,
        can_module=can_module,
        can_any_module=can_any_module,
        can_manage_with_system=can_manage_with_system,
    )

# --- JINJA HELPERS ---
@app.template_filter('camel_to_kebab')
def camel_to_kebab(s):
    import re
    return re.sub(r'(?<!^)(?=[A-Z])', '-', s).lower()

@app.context_processor
def utility_processor():
    from openpyxl.utils import get_column_letter
    return dict(col_letter_func=get_column_letter)

# --- ERROR HANDLERS ---
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"500 Error: {str(e)}")
    return render_template('500.html'), 500

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    if e.code == 404:
        return render_template('404.html'), 404
    app.logger.warning(f"HTTP Error {e.code}: {e.description}")
    return e

# Global exception handler - logs ALL errors
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled Exception: {str(e)}", exc_info=True)
    return render_template('500.html'), 500

@app.route('/favicon.ico')
def favicon(): return send_from_directory(STATIC_DIR, 'favicon.ico') if os.path.exists(os.path.join(STATIC_DIR, 'favicon.ico')) else ('', 204)

@app.route('/')
def index(): return redirect(url_for('admin_bp.index'))


def _security_txt_content():
    contact_email = os.environ.get('SECURITY_CONTACT_EMAIL', 'security@pc06tuyenquang.net')
    contact_url = os.environ.get('SECURITY_CONTACT_URL', 'https://www.pc06tuyenquang.net/login')
    policy_url = os.environ.get('SECURITY_POLICY_URL', contact_url)
    expires = os.environ.get('SECURITY_TXT_EXPIRES', '2027-06-05T23:59:59+07:00')
    return (
        f"Contact: mailto:{contact_email}\n"
        f"Contact: {contact_url}\n"
        f"Policy: {policy_url}\n"
        f"Expires: {expires}\n"
        "Preferred-Languages: vi, en\n"
    )


@app.route('/security.txt')
def security_txt():
    return Response(_security_txt_content(), mimetype='text/plain')


@app.route('/.well-known/security.txt')
def security_txt_well_known():
    return Response(_security_txt_content(), mimetype='text/plain')

@app.route('/dl_file/<path:fn>')
def dl_file(fn):
    normalized_name = os.path.basename((fn or '').strip())
    if not normalized_name or normalized_name != (fn or '').strip():
        return render_template('404.html'), 404

    candidate_dirs = []
    if NewsDoc.query.filter_by(filename=normalized_name).first():
        candidate_dirs.append(UPLOAD_FOLDER)
    if DocumentLib.query.filter_by(filename=normalized_name).first():
        candidate_dirs.append(LIB_FOLDER)
    if NotificationDoc.query.filter_by(filename=normalized_name).first():
        candidate_dirs.append(UPLOAD_FOLDER)
    if not candidate_dirs:
        return render_template('404.html'), 404

    for b in candidate_dirs:
        try:
            target = resolve_safe_path(b, normalized_name)
        except (FileNotFoundError, ValueError):
            continue
        if target.is_file():
            return send_file(target, as_attachment=True, download_name=target.name)
    return render_template('404.html'), 404


@app.route('/preview_file/<path:fn>')
def preview_file(fn):
    """Phục vụ tệp inline (không gắn attachment) để trình xem tài liệu
    (PDF, video, Word, Excel) có thể nhúng trực tiếp trong trang."""
    import mimetypes as _mimetypes
    normalized_name = os.path.basename((fn or '').strip())
    if not normalized_name or normalized_name != (fn or '').strip():
        return render_template('404.html'), 404

    candidate_dirs = []
    if NewsDoc.query.filter_by(filename=normalized_name).first():
        candidate_dirs.append(UPLOAD_FOLDER)
    if DocumentLib.query.filter_by(filename=normalized_name).first():
        candidate_dirs.append(LIB_FOLDER)
    if NotificationDoc.query.filter_by(filename=normalized_name).first():
        candidate_dirs.append(UPLOAD_FOLDER)
    if not candidate_dirs:
        return render_template('404.html'), 404

    for b in candidate_dirs:
        try:
            target = resolve_safe_path(b, normalized_name)
        except (FileNotFoundError, ValueError):
            continue
        if target.is_file():
            mime_type = _mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            return send_file(
                target,
                as_attachment=False,
                download_name=target.name,
                mimetype=mime_type,
                conditional=True,
            )
    return render_template('404.html'), 404

if __name__ == '__main__':
    host = os.environ.get('PC06_HOST', '127.0.0.1')
    port = int(os.environ.get('PC06_PORT', '5000'))
    app.run(host=host, port=port, debug=DEBUG)
