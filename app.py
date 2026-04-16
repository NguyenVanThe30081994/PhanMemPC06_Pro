import os
import logging
from logging.handlers import RotatingFileHandler
import json
from flask import Flask, session, request, redirect, url_for, send_from_directory, render_template, g
from datetime import datetime, timedelta
from models import db, AppRole
from utils import init_db, get_perms_labels, is_mobile_device
import time

# --- RELIABLE PATH RESOLUTION (Improved for Mắt Bão/Passenger) ---
basedir = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(basedir, 'templates')
STATIC_DIR = os.path.join(basedir, 'static')
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
TASK_FOLDER = os.path.join(basedir, 'task_files')
LIB_FOLDER = os.path.join(basedir, 'library_files')
BACKUP_FOLDER = os.path.join(basedir, 'backups') # Added for safety

# Ensure directories exist with absolute paths
for f in [UPLOAD_FOLDER, TASK_FOLDER, LIB_FOLDER, BACKUP_FOLDER, os.path.join(basedir, 'tmp')]:
    os.makedirs(f, exist_ok=True)

app = Flask(__name__, 
            root_path=basedir, 
            template_folder=TEMPLATE_DIR, 
            static_folder=STATIC_DIR)

app.secret_key = 'PC06_FINAL_V3_5_2026'

# ==================== FILE LOGGING ====================
# Create logs directory
LOG_DIR = os.path.join(basedir, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Configure logging
log_file = os.path.join(LOG_DIR, 'app.log')
file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

# ==================== SECURITY CONFIG ====================
# Session Security
app.config['SESSION_COOKIE_SECURE'] = False  # Set True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent XSS stealing cookies
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # 30 min timeout

# CSRF Protection
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour token lifetime

# File Upload Security
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max

# Allowed extensions for file upload
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'zip', 'rar', 'ppt', 'pptx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== DATABASE CONFIG ====================
# Using abspath for database URI
db_path = os.path.abspath(os.path.join(basedir, 'pc06_system.db'))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
from datetime import datetime, timedelta

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
            from flask import jsonify
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
from routes.forms import forms_bp
from routes.portal import portal_bp
from routes.tasks import tasks_bp
from routes.ranking import ranking_bp
from routes.api import api_bp
from routes.reports_v2 import reports_v2_bp
from routes.shortlink import shortlink_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(forms_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(ranking_bp)
app.register_blueprint(api_bp)
app.register_blueprint(reports_v2_bp)
app.register_blueprint(shortlink_bp)

@app.before_request
def check_auth():
    # 0. Device Detection
    g.is_mobile = is_mobile_device()

    # 1. Inactivity Check
    if session.get('uid'):
        last_active = session.get('last_active')
        now = datetime.now().timestamp()
        if last_active and (now - last_active) > 1800: # 30 mins
            session.clear()
            return redirect(url_for('auth_bp.login'))
        session['last_active'] = now

    allowed = ['auth_bp.login', 'static', 'dl_file', 'shortlink_bp.redirect_short_link', 'shortlink_bp.get_qr', 'favicon']
    if not session.get('uid') and request.endpoint not in allowed and not (request.endpoint and request.endpoint.startswith('static')):
        return redirect(url_for('auth_bp.login'))
    if session.get('uid') and session.get('must_change') and request.endpoint not in ['auth_bp.change_password', 'auth_bp.logout', 'static']:
        return redirect(url_for('auth_bp.change_password'))

@app.context_processor
def inject_global_data():
    if not session.get('uid'):
        return {'perms': {}}
    perms = {}
    is_admin = session.get('is_admin', False)
    role_name = "Thành viên"
    
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

    # 2. Overlap with Admin permissions if flag is set
    if is_admin or role_name == 'Quản trị hệ thống':
        modules = ["dash", "task", "lib", "news", "contact", "form", "sys", "input", "stat", "user"]
        for m in modules:
            perms[f"p_{m}_lead"] = 1
            perms[f"p_{m}_exec"] = 1
        # Backward compatibility keys
        perms.update({f"p_{m}": 1 for m in modules})

    return dict(perms=perms, role_name=role_name, fullname=session.get('fullname', ''), is_admin=is_admin, version="3.5.0", get_labels=get_perms_labels)

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
    for b in [TASK_FOLDER, UPLOAD_FOLDER, LIB_FOLDER]:
        target = os.path.join(b, fn)
        if os.path.exists(target): 
            return send_from_directory(b, fn, as_attachment=True)
    return render_template('404.html'), 404

if __name__ == '__main__': app.run(host='0.0.0.0', port=5000, debug=True)