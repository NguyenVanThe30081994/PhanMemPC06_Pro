# -*- coding: utf-8 -*-
import re, json, sqlite3, os, ast, operator as op
from flask import request, render_template as flask_render_template, g, session, redirect, url_for
from openpyxl.utils import range_boundaries
from datetime import datetime, timedelta
from models import db, User, AppRole, SystemLog, Notification, MasterData, NewsCategory, LibraryField, ContactGroup, ProfessionalUnit


# ==================== SECURITY FUNCTIONS ====================


def check_csrf_token(session_token, form_token):
    """
    Check if CSRF token matches (basic implementation).
    More robust CSRF should be handled by Flask-WTF or similar.
    """
    if not session_token or not form_token:
        return False
    return session_token == form_token

def is_safe_redirect_url(url):
    """
    Prevent open redirect vulnerabilities by checking if URL is internal.
    """
    from urllib.parse import urlparse
    if not url:
        return False
    parsed = urlparse(url)
    # Only allow relative URLs or same-domain URLs
    return not parsed.netloc or parsed.netloc == request.host

def get_client_ip():
    """
    Get client IP address, considering proxy headers.
    """
    # Check for forwarded headers (when behind proxy)
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

def log_security_event(event_type, details):
    """
    Log security-related events for monitoring.
    """
    try:
        uid = session.get('uid', 'anonymous')
        ip = get_client_ip()
        log_action(uid, session.get('fullname', 'N/A'), f"[SECURITY] {event_type}", "Security", f"{details} | IP: {ip}")
    except:
        pass

def remove_accents(s):
    if not s: return ""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('utf-8')
    return s.lower()

def normalize_unit_name(name):
    """
    Normalizes unit names for comparison. 
    Removes prefixes like 'Công an', 'Xã', 'Phường', 'Thị trấn', etc.
    Handles both spaced and smushed names (e.g., 'ubndphuongantuong' -> 'antuong').
    """
    if not name: return ""
    import unicodedata
    # 1. Lowercase and remove accents
    n = str(name).lower().strip()
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('utf-8')
    
    # 2. Clean noise and prefixes (Aggressive - handles smushed words)
    # We remove longer prefixes first to avoid partial matches on prefixes
    prefixes = [
        "cong an phuong", "cong an xa", "cong an huyen", "cong an thanh pho", "cong an tinh", 
        "ubnd xa", "ubnd phuong", "cong an", "ubnd",
        "phuong", "xa", "huyen", "thanh pho", "thi tran", "tinh", "don vi", "ban"
    ]
    
    # First pass: try whole words
    for p in prefixes:
        n = re.sub(r'\b' + re.escape(p) + r'\b', ' ', n)
        
    # Second pass: remove common prefixes as substrings (handles smushed names)
    for p in ["congan", "ubnd", "phuong", "xapp", "cap", "ca"]:
        if n.startswith(p):
            n = n[len(p):].strip()

    # 3. Clean up extra spaces and non-alphanumeric (keep spaces for now)
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def extract_unit_key(name):
    """
    Extracts the core unit key from a unit name.
    'Công an xã An Tường' -> 'antuong'
    'ubndphuongantuong' -> 'antuong'
    """
    if not name: return ""
    n = normalize_unit_name(name)
    # Remove all spaces to get the pure slug/key
    return re.sub(r'\s+', '', n)

def is_unit_match(name1, name2):
    """
    Smart matching for unit names.
    Handles 'UBND xã A' vs 'Công an xã A' as the same unit.
    """
    if not name1 or not name2: return False
    
    # 1. Exact normalized match
    norm1 = normalize_unit_name(name1)
    norm2 = normalize_unit_name(name2)
    if norm1 and norm2 and norm1 == norm2: return True
    
    # 2. Core key match (slug comparison)
    key1 = extract_unit_key(name1)
    key2 = extract_unit_key(name2)
    if key1 and key2 and key1 == key2: return True
    
    # 3. Partial match (one key contained in another)
    if key1 and key2 and (key1 in key2 or key2 in key1):
        # Additional safety: ensure key is not just 'a' or something too short
        if len(key1) > 2 and len(key2) > 2:
            return True
        
    return False

def slugify_unit(name):
    if not name: return ""
    n = normalize_unit_name(name)
    # Remove everything except alphanumeric for the slug
    n = re.sub(r'[^a-z0-9]', '', n)
    return n

def apply_migrations(app):
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if not db_uri.startswith('sqlite:///'): return
        db_path = db_uri.replace('sqlite:///', '')
        if not os.path.exists(db_path):
            # Try relative to root_path as fallback
            db_path = os.path.join(app.root_path, 'pc06_system.db')
            if not os.path.exists(db_path): return
    
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    migrations = [
        ("user", "must_change_password", "BOOLEAN DEFAULT 1"), 
        ("app_role", "perms", "TEXT"),
        ("notification", "is_read", "BOOLEAN DEFAULT 0"),
        ("report_config", "is_daily", "BOOLEAN DEFAULT 0"),
        ("report_config", "header_start", "INTEGER DEFAULT 1"),
        ("report_config", "header_rows", "INTEGER DEFAULT 1"),
        ("report_config", "is_excel", "BOOLEAN DEFAULT 1"),
        ("report_config", "author_name", "VARCHAR(100)"),
        ("report_config", "description", "TEXT"),
        ("report_config", "created_at", "DATETIME"),
        ("news_doc", "content", "TEXT"),
        ("news_doc", "target_scope", "VARCHAR(50) DEFAULT 'Toàn tỉnh'"),
        ("document_lib", "uploaded_at", "DATETIME"),
        ("task", "priority", "VARCHAR(50)"),
        ("task", "task_type", "VARCHAR(100)"),
        ("task", "initial_status", "VARCHAR(50) DEFAULT 'Chưa bắt đầu'"),
        ("task", "created_at", "DATETIME"),
        ("task_comment", "assignee_id", "INTEGER DEFAULT 0"),
        ("system_log", "module", "VARCHAR(100)"),
        ("category_group", "code", "VARCHAR(100)"),
        ("category_group", "description", "VARCHAR(255)"),
        ("category_group", "is_active", "BOOLEAN DEFAULT 1"),
        ("category_group", "sort_order", "INTEGER DEFAULT 0"),
        ("category_item", "code", "VARCHAR(100)"),
        ("category_item", "is_active", "BOOLEAN DEFAULT 1"),
        ("category_item", "sort_order", "INTEGER DEFAULT 0")
    ]
    for table, col, col_type in migrations:
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            if col not in [c[1] for c in cursor.fetchall()]:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                conn.commit()
        except Exception as e: 
            print(f"Migration Error on {table}.{col}: {e}")

    create_table_statements = [
        """
        CREATE TABLE IF NOT EXISTS module_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(50) UNIQUE,
            name VARCHAR(100) UNIQUE,
            is_active BOOLEAN DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS category_group_module (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            module_id INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS module_field_binding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id INTEGER NOT NULL,
            field_code VARCHAR(100) NOT NULL,
            field_label VARCHAR(255),
            group_id INTEGER NOT NULL,
            is_required BOOLEAN DEFAULT 0,
            allow_multiple_groups BOOLEAN DEFAULT 0
        )
        """
    ]
    for stmt in create_table_statements:
        try:
            cursor.execute(stmt)
            conn.commit()
        except Exception as e:
            print(f"Create Table Migration Error: {e}")
    conn.close()

def init_db(app):
    with app.app_context():
        db.create_all()
        apply_migrations(app)
        
        # Admin Role - More robust check and insert
        admin_role = AppRole.query.filter_by(name='Quản trị hệ thống').first()
        if not admin_role:
            try:
                full_perms = {k:1 for k in ["p_dash", "p_task", "p_task_assign", "p_task_do", "p_lib", "p_news", "p_contact", "p_form", "p_sys", "p_input", "p_stat", "p_user"]}
                admin_role = AppRole(name='admin_system', perms=json.dumps(full_perms, ensure_ascii=False))
                db.session.add(admin_role)
                db.session.commit()
            except Exception:
                db.session.rollback()
                admin_role = AppRole.query.filter_by(name='admin_system').first()
            
        # Admin User
        if admin_role and not User.query.filter_by(username='admin').first():
            try:
                u = User(username='admin', fullname='Tài khoản quản trị', role_id=admin_role.id, unit_area='Hệ thống')
                u.set_password('123')
                db.session.add(u)
                db.session.commit()
            except Exception:
                db.session.rollback()

def log_action(uid, fullname, act, module="Hệ thống", det=""):
    try: 
        db.session.add(SystemLog(user_id=uid, fullname=fullname, module=module, action=act, details=det))
        db.session.commit()
    except Exception as e: 
        db.session.rollback()
        # Silent log to console for debugging
        print(f"Log Action Error: {e}")

def push_notif(uid, title, msg, link):
    try: 
        db.session.add(Notification(user_id=uid, title=title, msg=msg, link=link))
        db.session.commit()
    except: db.session.rollback()

def is_mobile_device():
    """
    Detects if the request is coming from a mobile device using User-Agent.
    """
    ua = request.headers.get('User-Agent', '').lower()
    mobile_keywords = ['android', 'iphone', 'ipad', 'mobi', 'opera mini', 'blackberry', 'webos', 'phone']
    return any(keyword in ua for keyword in mobile_keywords)

def render_auto_template(template_name, **context):
    """
    Automatically selects between PC and Mobile templates based on g.is_mobile.
    Expected naming convention: name.html (PC) -> name_mobile.html (Mobile)
    """
    if g.get('is_mobile'):
        # Construct the mobile template path
        mobile_path = template_name.replace('.html', '_mobile.html')
        
        # Check if mobile template exists in the templates folder
        from flask import current_app
        import os
        full_mobile_path = os.path.join(current_app.template_folder, mobile_path)
        
        if os.path.exists(full_mobile_path):
            return flask_render_template(mobile_path, **context)
    
    return flask_render_template(template_name, **context)

def push_global_notif(title, msg, link, exclude_uid=None):
    from models import db, User, Notification
    try:
        users = User.query.all()
        for u in users:
            if exclude_uid and u.id == exclude_uid: continue
            db.session.add(Notification(user_id=u.id, title=title, msg=msg, link=link))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Global Notif Error: {e}")

def safe_float(v):
    if v is None or v == "": return 0.0
    try: 
        # Handle Vietnamese formatting: 1.234,56 or 1 234,56
        s = str(v).replace(' ', '').replace('%', '').strip()
        if ',' in s and '.' in s: # Mixed format, usually dot is thousands, comma is decimal
            s = s.replace('.', '').replace(',', '.')
        elif ',' in s: # Only comma, treat as decimal separator
            s = s.replace(',', '.')
        return float(s)
    except: return 0.0

def format_vi_float(f): 
    if isinstance(f, (int, float)): 
        return f"{int(f)}" if float(f).is_integer() else f"{f:.2f}".replace('.', ',')
    return str(f)

# --- EXCEL FORMULA EVALUATION ---
_operators = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow, ast.BitXor: op.xor, ast.USub: op.neg}
def _eval_node(node):
    if isinstance(node, ast.Num): return node.n
    elif isinstance(node, ast.BinOp): return _operators[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    elif isinstance(node, ast.UnaryOp): return _operators[type(node.op)](_eval_node(node.operand))
    else: raise TypeError(node)

def eval_f(formula_str, data_dict):
    if not formula_str or not str(formula_str).startswith('='): 
        return safe_float(formula_str)
    s = str(formula_str)[1:].upper()
    try:
        def col2num(c): 
            e = 0; n = 0
            for ch in reversed(c.upper()): 
                n += (ord(ch) - ord('A') + 1) * (26 ** e)
                e += 1
            return n
        # Replace cell references like A1, B12 with values from data_dict
        for r in sorted(set(re.findall(r'[A-Z]+\d+', s)), key=len, reverse=True):
            c_idx = col2num(re.search(r'[A-Z]+', r).group())
            val = str(safe_float(data_dict.get(str(c_idx), "0")))
            s = re.sub(r'\b' + r + r'\b', val, s)
        
        # Safe evaluation using ast
        node = ast.parse(s, mode='eval').body
        result = float(_eval_node(node))
        return result
    except Exception as e:
        # Silently fail for formulas to avoid crashing the whole report
        return 0.0

def get_perms_labels(perms_json):
    if not perms_json: return ""
    labels_map = {
        "dash": "Tổng quan", "task": "Công việc", "lib": "Thư viện", 
        "news": "Bảng tin", "contact": "Danh bạ", "form": "Cấu hình biểu mẫu", 
        "sys": "Hệ thống", "input": "Nhập liệu", "stat": "Thống kê", "user": "Tài khoản"
    }
    try:
        p = json.loads(perms_json) if isinstance(perms_json, str) else perms_json
        if not p: return ""
        res = []
        for k, v in p.items():
            if v == 1:
                # New format: p_module_lead/exec
                if k.startswith('p_') and (k.endswith('_lead') or k.endswith('_exec')):
                    parts = k.split('_')
                    if len(parts) >= 3:
                        mod = parts[1]
                        suf = " (Chỉ đạo)" if parts[2] == 'lead' else " (Thực hiện)"
                        res.append(f"{labels_map.get(mod, mod)}{suf}")
                # Old/Legacy formats
                elif k.startswith('p_') and k[2:] in labels_map:
                    res.append(labels_map[k[2:]])
                elif k in labels_map:
                    res.append(labels_map[k])
        return ", ".join(res)
    except Exception as e:
        print(f"Perms Label Error: {e}")
        return ""

def clear_logs(start_date=None, end_date=None):
    try:
        q = SystemLog.query
        if start_date:
            q = q.filter(SystemLog.created_at >= start_date)
        if end_date:
            q = q.filter(SystemLog.created_at <= end_date)
        q.delete()
        db.session.commit()
    except: db.session.rollback()


# ==================== SECURITY FUNCTIONS ====================

def sanitize_input(text):
    """
    Sanitize input to prevent XSS attacks.
    Escapes HTML special characters.
    """
    if not text:
        return ""
    import html
    return html.escape(str(text).strip())


def validate_password_strength(password):
    """
    Validate password meets security requirements.
    Returns: (is_valid, message)
    """
    import re
    if not password:
        return False, "Mật khẩu không được để trống"
    if len(password) < 8:
        return False, "Mật khẩu phải có ít nhất 8 ký tự"
    if not re.search(r'[A-Z]', password):
        return False, "Phải có ít nhất 1 chữ cái viết hoa"
    if not re.search(r'[a-z]', password):
        return False, "Phải có ít nhất 1 chữ cái viết thường"
    if not re.search(r'[0-9]', password):
        return False, "Phải có ít nhất 1 số"
    return True, "Mật khẩu hợp lệ"


# ==================== NUMBER FORMATTING (V2 Support) ====================

def format_cell_value(value, number_format):
    """
    Apply Excel number format to a value.
    
    Supports common Excel formats:
      "0"           -> Integer (no decimals)
      "0.00"        -> 2 decimal places
      "0.0"         -> 1 decimal place
      "#,##0"       -> Integer with thousand separator
      "#,##0.00"    -> 2 decimals with thousand separator
      "0.0%"        -> Percentage (multiply by 100)
      "0%"          -> Percentage integer
      
    SMART FALLBACK: If format says "0" (integer) but value has decimals,
    intelligently detect the needed decimal places.
      
    Args:
        value: The cell value (number, float, int, or string)
        number_format: Excel format code (e.g., "0.00", "#,##0")
        
    Returns:
        Formatted string representation
    """
    if value is None or value == '':
        return ''
    
    # Handle None and empty formats - use default
    if not number_format:
        return _format_cell_value_default(value)
    
    number_format = str(number_format).strip()
    
    try:
        # Try to convert to float if not already numeric
        if isinstance(value, str):
            if value.startswith('='):  # Formula - don't format
                return ''
            try:
                numeric_val = float(value)
            except ValueError:
                return str(value)  # Not a number, return as-is
        else:
            numeric_val = float(value)
        
        # Handle percentage formats
        if '%' in number_format:
            if 'h' not in number_format.lower():  # Not time format
                numeric_val = numeric_val * 100
        
        # Determine if we have thousand separators and how many decimals
        has_thousand_sep = ',' in number_format
        decimal_places = 0
        
        if '.' in number_format:
            # Count zeros after the decimal point
            format_after_decimal = number_format.split('.')[-1]
            # Count only the leading zeros (until we hit a non-zero char)
            decimal_places = 0
            for ch in format_after_decimal:
                if ch == '0':
                    decimal_places += 1
                elif ch in ['#', '%']:
                    break
                else:
                    break
        else:
            # No decimal point in format - check if it's "0" or similar
            # SMART FALLBACK: If value has decimals, detect how many to show
            if number_format.replace(',', '').replace('#', '') == '0':
                # Format is pure integer, but check if value needs decimals
                if numeric_val != int(numeric_val):
                    # Value has decimal part - detect needed decimal places
                    val_str = f"{numeric_val:.10f}".rstrip('0').rstrip('.')
                    if '.' in val_str:
                        decimal_places = len(val_str.split('.')[-1])
        
        # Format based on components
        if decimal_places > 0:
            # Has decimal places
            formatted = f"{numeric_val:.{decimal_places}f}"
            if has_thousand_sep:
                # Add thousand separators
                parts = formatted.split('.')
                parts[0] = f"{int(parts[0]):,}"
                formatted = '.'.join(parts)
            return formatted
        else:
            # Integer format
            int_val = int(round(numeric_val))
            if has_thousand_sep:
                return f"{int_val:,}"
            else:
                return str(int_val)
        
    except (ValueError, TypeError):
        return str(value)


def _format_cell_value_default(val):
    """Default formatting when no format code or fallback."""
    if val is None or val == '':
        return ''
    if isinstance(val, str):
        val = val.strip()
        if val.startswith('='):
            return ''
        try:
            fval = float(val)
            fval = round(fval, 10)
            if fval == int(fval):
                return str(int(fval))
            return f"{fval:.6f}".rstrip('0').rstrip('.')
        except ValueError:
            return val
    if isinstance(val, float):
        val = round(val, 10)
        if val == int(val):
            return str(int(val))
        return f"{val:.6f}".rstrip('0').rstrip('.')
    return str(val)