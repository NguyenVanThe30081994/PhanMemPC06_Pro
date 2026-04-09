import re, json, sqlite3, os, ast, operator as op
from openpyxl.utils import range_boundaries
from datetime import datetime, timedelta
from models import db, User, AppRole, SystemLog, Notification, MasterData, NewsCategory, LibraryField, ContactGroup, ProfessionalUnit

def remove_accents(s):
    if not s: return ""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('utf-8')
    return s.lower()

def slugify_unit(name):
    if not name: return ""
    import unicodedata
    # Lowercase and handle common abbreviations
    n = str(name).lower().strip()
    n = n.replace("công an nhân dân", "cand")
    n = n.replace("công an xã", "cax")
    n = n.replace("công an huyện", "cah")
    n = n.replace("ủy ban nhân dân xã", "ubndxa")
    n = n.replace("ủy ban nhân dân", "ubnd")
    n = n.replace("tỉnh tuyên quang", "ttq")
    n = n.replace("thành phố", "tp")
    n = n.replace("thị trấn", "tt")
    n = n.replace("phòng cảnh sát", "pcs")
    
    # Remove accents
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('utf-8')
    # Remove everything except alphanumeric
    n = re.sub(r'[^a-z0-9]', '', n)
    return n

def apply_migrations(app):
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
        ("task", "created_at", "DATETIME"),
        ("task_comment", "assignee_id", "INTEGER DEFAULT 0"),
        ("system_log", "module", "VARCHAR(100)")
    ]
    for table, col, col_type in migrations:
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            if col not in [c[1] for c in cursor.fetchall()]:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                conn.commit()
        except Exception as e: 
            print(f"Migration Error on {table}.{col}: {e}")
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
                admin_role = AppRole(name='Quản trị hệ thống', perms=json.dumps(full_perms))
                db.session.add(admin_role)
                db.session.commit()
            except Exception:
                db.session.rollback()
                admin_role = AppRole.query.filter_by(name='Quản trị hệ thống').first()
            
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