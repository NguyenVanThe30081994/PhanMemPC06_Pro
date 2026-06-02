# -*- coding: utf-8 -*-
import os
import sys
import sqlite3

# ── UTF-8 Environment (safe for Python 3.9 on Mắt Bão / cPanel) ──
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ.setdefault('LC_ALL', 'C.UTF-8')
os.environ.setdefault('LANG', 'C.UTF-8')

# Reconfigure stdout/stderr to UTF-8 (Python 3.7+)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import logging
from logging.handlers import RotatingFileHandler
import json
from flask import Flask, session, request, redirect, url_for, send_from_directory, render_template, g, jsonify
from datetime import datetime, timedelta
from werkzeug.exceptions import HTTPException
from sqlalchemy import event
from sqlalchemy.engine import Engine
from models import db, AppRole
from storage import bootstrap_storage, build_storage_layout
from utils import (
    get_perms_labels,
    has_any_module_permission,
    has_module_permission,
    init_db,
    is_mobile_device,
    normalize_permission_payload,
)

# --- RELIABLE PATH RESOLUTION (Improved for Mắt Bão/Passenger) ---
basedir = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(basedir, 'templates')
STATIC_DIR = os.path.join(basedir, 'static')
storage_layout = build_storage_layout(basedir)
bootstrap_storage(storage_layout, basedir)

UPLOAD_FOLDER = storage_layout['UPLOAD_FOLDER']
TASK_FOLDER = storage_layout['TASK_FOLDER']
LIB_FOLDER = storage_layout['LIB_FOLDER']
REPORT_TEMPLATE_FOLDER = storage_layout['REPORT_TEMPLATE_FOLDER']
REPORT_EXPORT_FOLDER = storage_layout['REPORT_EXPORT_FOLDER']
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
        SESSION_COOKIE_SECURE,
        SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE,
        CSRF_TOKEN_LIFETIME,
    )
except ImportError:
    SECRET_KEY = 'PC06_FINAL_V3_5_2026'
    SESSION_LIFETIME = 28800
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_TOKEN_LIFETIME = 3600

app.secret_key = SECRET_KEY
app.config['JSON_AS_ASCII'] = False  # Giữ nguyên tiếng Việt trong jsonify()
app.config['PC06_DATA_ROOT'] = storage_layout['data_root']
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['TASK_FOLDER'] = TASK_FOLDER
app.config['LIB_FOLDER'] = LIB_FOLDER
app.config['REPORT_TEMPLATE_FOLDER'] = REPORT_TEMPLATE_FOLDER
app.config['REPORT_EXPORT_FOLDER'] = REPORT_EXPORT_FOLDER
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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=SESSION_LIFETIME)  # 30 min timeout
app.config['PC06_SESSION_TIMEOUT_SECONDS'] = SESSION_LIFETIME

# CSRF Protection
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = CSRF_TOKEN_LIFETIME  # 1 hour token lifetime

# File Upload Security
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH  # 100MB max

# Allowed extensions for file upload
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'zip', 'rar', 'ppt', 'pptx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== DATABASE CONFIG ====================
app.config['SQLALCHEMY_DATABASE_URI'] = storage_layout['DATABASE_URI']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
}

for folder in [UPLOAD_FOLDER, TASK_FOLDER, LIB_FOLDER, REPORT_TEMPLATE_FOLDER, REPORT_EXPORT_FOLDER, BACKUP_FOLDER, TMP_FOLDER]:
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
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # XSS Protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Prevent content type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Strict Transport Security (if HTTPS is enabled)
    # response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # Content Security Policy (basic - can be enhanced later)
    # response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data:;"
    # Referrer Policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# Rate Limiting Configuration (Simple in-memory implementation)
from collections import defaultdict

# Rate limit storage: {ip: [(timestamp, count)]}
rate_limit_store = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 30  # max requests per window

@app.before_request
def check_rate_limit():
    """Simple rate limiting to prevent spam and brute force"""
    # Skip for static files and favicon
    if request.path.startswith('/static') or request.path == '/favicon.ico':
        return
    
    # Skip login route to allow login attempts
    if request.endpoint == 'auth_bp.login':
        return
    
    # Get client IP
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    if not client_ip:
        return
    
    current_time = datetime.now().timestamp()
    
    # Clean old entries
    if client_ip in rate_limit_store:
        rate_limit_store[client_ip] = [
            (t, count) for t, count in rate_limit_store[client_ip]
            if current_time - t < RATE_LIMIT_WINDOW
        ]
        
        # Count requests in current window
        total_requests = sum(count for t, count in rate_limit_store[client_ip])
        
        if total_requests >= RATE_LIMIT_MAX:
            # Too many requests - return 429 with proper JSON response
            return jsonify({'error': 'Quá nhiều yêu cầu. Vui lòng thử lại sau.'}), 429
        
        # Add current request
        if rate_limit_store[client_ip]:
            last_time, last_count = rate_limit_store[client_ip][-1]
            rate_limit_store[client_ip][-1] = (last_time, last_count + 1)
        else:
            rate_limit_store[client_ip].append((current_time, 1))

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
from routes.ranking import ranking_bp
from routes.api import api_bp
from routes.shortlink import shortlink_bp
from routes.reporting import reporting_bp
from routes.ai_assistant import ai_bp
from routes.health import health_bp
from routes.attendance import attendance_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(ranking_bp)
app.register_blueprint(api_bp)
app.register_blueprint(shortlink_bp)
app.register_blueprint(reporting_bp)
app.register_blueprint(health_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(attendance_bp)

@app.before_request
def check_auth():
    # 0. Device Detection
    g.is_mobile = is_mobile_device()

    public_endpoints = {
        'attendance_bp.public_attendance',
        'attendance_bp.submit_attendance',
        'favicon',
    }
    if request.endpoint in public_endpoints:
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


def build_session_activity_marker():
    uid = session.get('uid')
    login_nonce = session.get('login_nonce')
    if not uid or not login_nonce:
        return ''
    return f"{uid}:{login_nonce}"

    allowed = ['auth_bp.login', 'static', 'dl_file', 'shortlink_bp.redirect_short_link', 'shortlink_bp.get_qr', 'favicon']
    if not session.get('uid') and request.endpoint not in allowed and not (request.endpoint and request.endpoint.startswith('static')):
        return redirect(url_for('auth_bp.login'))
    if session.get('uid') and session.get('must_change') and request.endpoint not in ['auth_bp.change_password', 'auth_bp.logout', 'static']:
        return redirect(url_for('auth_bp.change_password'))

@app.context_processor
def inject_global_data():
    is_admin = session.get('is_admin', False)
    role_name = "Thành viên"
    perms = {}

    def can_module(module_code, tier='view'):
        return has_module_permission(perms, module_code, tier=tier, is_admin=is_admin, role_name=role_name)

    def can_any_module(module_codes, tier='view'):
        return has_any_module_permission(perms, module_codes, tier=tier, is_admin=is_admin, role_name=role_name)

    def can_manage_with_system(module_code):
        return bool(can_module(module_code, 'process') or can_module('sys', 'process'))

    def can_access_report_center():
        return bool(
            can_module('form', 'view')
            or can_module('input', 'view')
            or can_module('input', 'process')
            or can_module('input', 'exec')
            or can_module('stat', 'view')
            or can_module('stat', 'process')
            or can_module('stat', 'exec')
        )

    def report_center_url():
        return '/admin/reports' if can_module('form', 'process') else '/reports'

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
            can_access_report_center=can_access_report_center,
            report_center_url=report_center_url,
        )
    
    # 1. Fetch properties from DB role if available
    try:
        rid = session.get('role_id')
        role = db.session.get(AppRole, rid) if rid else None
        if role:
            role_name = role.name
            if role.perms:
                perms = json.loads(role.perms)
    except Exception:
        pass

    perms = normalize_permission_payload(perms, is_admin=is_admin, role_name=role_name)

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
        can_access_report_center=can_access_report_center,
        report_center_url=report_center_url,
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

@app.route('/dl_file/<path:fn>')
def dl_file(fn): 
    legacy_task_folder = os.path.join(app.root_path, 'task_files')
    candidate_dirs = [TASK_FOLDER, UPLOAD_FOLDER, LIB_FOLDER]
    if legacy_task_folder not in candidate_dirs:
        candidate_dirs.append(legacy_task_folder)
    for b in candidate_dirs:
        target = os.path.join(b, fn)
        if os.path.exists(target): 
            return send_from_directory(b, fn, as_attachment=True)
    return render_template('404.html'), 404

if __name__ == '__main__':
    host = os.environ.get('PC06_HOST', '127.0.0.1')
    port = int(os.environ.get('PC06_PORT', '5000'))
    app.run(host=host, port=port, debug=True)
