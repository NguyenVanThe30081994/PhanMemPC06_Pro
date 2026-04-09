import os
import json
from flask import Flask, session, request, redirect, url_for, send_from_directory, render_template
from models import db, AppRole
from utils import init_db, get_perms_labels

# --- RELIABLE PATH RESOLUTION (Improved for Mắt Bão/Passenger) ---
basedir = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(basedir, 'templates')
STATIC_DIR = os.path.join(basedir, 'static')
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
TASK_FOLDER = os.path.join(basedir, 'task_files')
LIB_FOLDER = os.path.join(basedir, 'library_files')
CHAT_FOLDER = os.path.join(basedir, 'chat_files')
BACKUP_FOLDER = os.path.join(basedir, 'backups') # Added for safety

# Ensure directories exist with absolute paths
for f in [UPLOAD_FOLDER, TASK_FOLDER, LIB_FOLDER, CHAT_FOLDER, BACKUP_FOLDER, os.path.join(basedir, 'tmp')]:
    os.makedirs(f, exist_ok=True)

app = Flask(__name__, 
            root_path=basedir, 
            template_folder=TEMPLATE_DIR, 
            static_folder=STATIC_DIR)

app.secret_key = 'PC06_FINAL_V3_5_2026'
# Using abspath for database URI
db_path = os.path.abspath(os.path.join(basedir, 'pc06_system.db'))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

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
from routes.chat import chat_bp
from routes.api import api_bp
from routes.reports_v2 import reports_v2_bp
from routes.shortlink import shortlink_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(forms_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(api_bp)
app.register_blueprint(reports_v2_bp)
app.register_blueprint(shortlink_bp)

@app.before_request
def check_auth():
    allowed = ['auth_bp.login', 'static', 'dl_file', 'shortlink_bp.redirect_short_link', 'shortlink_bp.get_qr', 'favicon']
    if not session.get('uid') and request.endpoint not in allowed and not (request.endpoint and request.endpoint.startswith('static')):
        return redirect(url_for('auth_bp.login'))
    if session.get('uid') and session.get('must_change') and request.endpoint not in ['auth_bp.change_password', 'auth_bp.logout', 'static']:
        return redirect(url_for('auth_bp.change_password'))

@app.context_processor
def inject_global_data():
    if not session.get('uid'):
        return {}
    perms = {}
    is_admin = session.get('is_admin', False)
    role_name = "Không xác định"
    try:
        role = db.session.get(AppRole, session.get('role_id'))
        if role:
            role_name = role.name
            perms = json.loads(role.perms) if role.perms else {}
            if is_admin or role.name == 'Quản trị hệ thống':
                modules = ["dash", "task", "lib", "news", "contact", "form", "sys", "input", "stat", "user"]
                for m in modules:
                    perms[f"p_{m}_lead"] = 1
                    perms[f"p_{m}_exec"] = 1
                # Backward compatibility keys
                perms.update({f"p_{m}": 1 for m in modules})
    except Exception:
        pass
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
    return render_template('500.html'), 500

@app.route('/favicon.ico')
def favicon(): return send_from_directory(STATIC_DIR, 'favicon.ico') if os.path.exists(os.path.join(STATIC_DIR, 'favicon.ico')) else ('', 204)

@app.route('/')
def index(): return redirect(url_for('admin_bp.index'))

@app.route('/dl_file/<path:fn>')
def dl_file(fn): 
    for b in [TASK_FOLDER, UPLOAD_FOLDER, LIB_FOLDER, CHAT_FOLDER]:
        target = os.path.join(b, fn)
        if os.path.exists(target): 
            return send_from_directory(b, fn, as_attachment=True)
    return render_template('404.html'), 404

if __name__ == '__main__': app.run(host='0.0.0.0', port=5000, debug=True)