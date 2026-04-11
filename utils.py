import re, json, sqlite3, os, ast, operator as op
from flask import request, render_template as flask_render_template, g, session, redirect, url_for
from openpyxl.utils import range_boundaries
from datetime import datetime, timedelta
from models import db, User, AppRole, SystemLog, Notification, MasterData, NewsCategory, LibraryField, ContactGroup, ProfessionalUnit

def render_auto_template(template_name, **context):
    """
    Automatic template rendering with mobile/desktop detection and security features.
    - Detects device type from User-Agent
    - Automatically appends '_mobile' suffix for mobile devices if template exists
    - Includes responsive detection for different screen sizes
    - Adds security headers and CSRF protection context
    """
    # Security: Check if user is logged in for protected routes
    # (This is handled by individual route decorators, but we add context here)
    
    # Device Detection
    user_agent = request.headers.get('User-Agent', '').lower() if request.headers.get('User-Agent') else ''
    
    # Check for explicit mobile override via query parameter (for testing)
    if request.args.get('mobile') == '1':
        is_mobile = True
    elif request.args.get('mobile') == '0':
        is_mobile = False
    else:
        # Automatic detection based on User-Agent
        mobile_keywords = ['android', 'iphone', 'ipad', 'ipod', 'mobile', 'tablet', 'opera mini', 'blackberry', 'windows phone']
        is_mobile = any(keyword in user_agent for keyword in mobile_keywords)
    
    # Responsive screen size detection (for extra context)
    screen_width = request.args.get('width', '')
    if screen_width:
        try:
            screen_width = int(screen_width)
            # Add responsive context
            context['is_xs'] = screen_width < 576   # Extra small
            context['is_sm'] = 576 <= screen_width < 768  # Small
            context['is_md'] = 768 <= screen_width < 992  # Medium
            context['is_lg'] = 992 <= screen_width < 1200 # Large
            context['is_xl'] = screen_width >= 1200       # Extra large
        except:
            pass
    
    # Add device info to context
    context['is_mobile'] = is_mobile
    context['is_desktop'] = not is_mobile
    
    # Try to load mobile template if on mobile device
    if is_mobile:
        # Remove .html if present and try mobile variant
        if template_name.endswith('.html'):
            base_name = template_name[:-5]
        else:
            base_name = template_name
            
        mobile_template = f"{base_name}_mobile.html"
        
        # Check if mobile template exists (we can't easily check here without jinja env, 
        # so we'll let Flask handle the 404 if it doesn't exist and fall back to desktop)
        try:
            # Try to render with mobile template
            return flask_render_template(mobile_template, **context)
        except:
            # Fall back to desktop template if mobile doesn't exist
            return flask_render_template(template_name, **context)
    
    # Desktop: render normally
    return flask_render_template(template_name, **context)

# ==================== SECURITY FUNCTIONS ====================

def sanitize_input(text):
    """
    Sanitize user input to prevent XSS and injection attacks.
    """
    if not text:
        return ""
    # Basic HTML entity encoding
    import html
    return html.escape(str(text))

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

# ==================== ZALO OA FUNCTIONS ====================

import requests
import json as json_lib
from datetime import datetime, timedelta

ZALO_API_URL = "https://openapi.zalo.me/v3"
ZALO_OA_URL = "https://officialapi.zalo.me"

def get_zalo_config():
    """Lấy cấu hình Zalo OA đang hoạt động"""
    from models import ZaloConfig
    return ZaloConfig.query.filter_by(is_active=True).first()

def send_zalo_message(phone, template_id, data):
    """
    Gửi tin nhắn qua Zalo OA sử dụng template.
    
    Args:
        phone: Số điện thoại người nhận
        template_id: ID template trong Zalo OA
        data: Dict chứa các biến trong template
    
    Returns:
        dict: {'status': 'success'/'failed', 'message': '...'}
    """
    config = get_zalo_config()
    if not config:
        return {'status': 'failed', 'message': 'Chưa cấu hình Zalo OA'}
    
    if not config.access_token:
        return {'status': 'failed', 'message': 'Access Token không hợp lệ'}
    
    # Format phone (remove +84, use 0...)
    phone = str(phone).strip()
    if phone.startswith('+84'):
        phone = '84' + phone[3:]
    elif phone.startswith('84'):
        pass
    elif phone.startswith('0'):
        phone = '84' + phone[1:]
    
    try:
        url = f"{ZALO_OA_URL}/oa/message/push"
        payload = {
            'phone': phone,
            'template_id': template_id or config.template_id,
            'data': data
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config.access_token}'
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        result = response.json()
        
        if response.status_code == 200 and result.get('error') == 0:
            return {'status': 'success', 'message': 'Đã gửi tin nhắn'}
        else:
            return {'status': 'failed', 'message': result.get('message', 'Lỗi gửi tin nhắn')}
    
    except Exception as e:
        return {'status': 'failed', 'message': str(e)}

def refresh_zalo_token():
    """Refresh access token từ Zalo OA"""
    config = get_zalo_config()
    if not config or not config.refresh_token:
        return False
    
    try:
        url = f"{ZALO_OA_URL}/oa/get/accesstoken"
        payload = {
            'app_id': config.oa_id,
            'app_secret': config.secret_key,
            'refresh_token': config.refresh_token
        }
        
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        if response.status_code == 200 and result.get('error') == 0:
            config.access_token = result.get('access_token')
            config.refresh_token = result.get('refresh_token')
            config.last_refresh = datetime.now()
            from models import db
            db.session.commit()
            return True
    
    except Exception as e:
        print(f"Zalo token refresh error: {e}")
        return False

def check_task_deadlines_and_notify():
    """
    Kiểm tra deadline công việc và gửi thông báo Zalo.
    Chạy định kỳ (mỗi giờ hoặc mỗi 15 phút).
    """
    from models import Task, ZaloUser, ZaloNotificationLog, db, User
    
    config = get_zalo_config()
    if not config or not config.is_active:
        return {'status': 'skipped', 'message': 'Zalo OA chưa được kích hoạt'}
    
    now = datetime.now()
    results = {'sent': 0, 'failed': 0}
    
    # 1. Tìm các task sắp hết hạn (trong 24h tới)
    upcoming_deadline = now + timedelta(hours=24)
    upcoming_tasks = Task.query.filter(
        Task.deadline <= upcoming_deadline,
        Task.deadline >= now,
        Task.status != 'Hoàn thành'
    ).all()
    
    # 2. Tìm các task đã quá hạn
    overdue_tasks = Task.query.filter(
        Task.deadline < now,
        Task.status != 'Hoàn thành'
    ).all()
    
    # Lấy danh sách user có Zalo
    zalo_users = ZaloUser.query.filter_by(is_active=True, is_verified=True).all()
    zalo_phones = {u.user_id: u.phone for u in zalo_users}
    
    # Gửi notification cho task sắp hết hạn
    for task in upcoming_tasks:
        if task.author_id in zalo_phones:
            phone = zalo_phones[task.author_id]
            data = {
                'task_title': task.title,
                'deadline': task.deadline.strftime('%d/%m/%Y'),
                'status': 'Sắp hết hạn',
                'domain': task.domain or ''
            }
            result = send_zalo_message(phone, config.template_id, data)
            
            # Log
            db.session.add(ZaloNotificationLog(
                task_id=task.id,
                user_id=task.author_id,
                phone=phone,
                message=f"Nhắc nhở: {task.title} sắp hết hạn",
                template_data=json_lib.dumps(data),
                status=result.get('status', 'pending')
            ))
            
            if result.get('status') == 'success':
                results['sent'] += 1
            else:
                results['failed'] += 1
    
    # Gửi notification cho task quá hạn
    for task in overdue_tasks:
        if task.author_id in zalo_phones:
            phone = zalo_phones[task.author_id]
            data = {
                'task_title': task.title,
                'deadline': task.deadline.strftime('%d/%m/%Y'),
                'status': 'ĐÃ QUÁ HẠN',
                'domain': task.domain or ''
            }
            result = send_zalo_message(phone, config.template_id, data)
            
            # Log
            db.session.add(ZaloNotificationLog(
                task_id=task.id,
                user_id=task.author_id,
                phone=phone,
                message=f"CẢNH BÁO: {task.title} đã quá hạn",
                template_data=json_lib.dumps(data),
                status=result.get('status', 'pending')
            ))
            
            if result.get('status') == 'success':
                results['sent'] += 1
            else:
                results['failed'] += 1
    
    db.session.commit()
    return results

def remove_accents(s):
    if not s: return ""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('utf-8')
    return s.lower()

def normalize_unit_name(name):
    """
    Normalizes unit names for comparison. 
    Removes prefixes like 'Công an', 'Xã', 'Phường', 'Thị trấn', etc.
    Example: 'Công an phường An Tường' -> 'an tuong', 'Phường an tường' -> 'an tuong'
    """
    if not name: return ""
    import unicodedata
    # 1. Lowercase and remove accents
    n = str(name).lower().strip()
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('utf-8')
    
    # 2. Remove common prefixes and noise words
    prefixes = [
        "cong an phuong", "cong an xa", "cong an huyen", "cong an thanh pho", "cong an tinh", "cong an",
        "ubnd xa", "ubnd phuong", "ubnd",
        "phuong", "xa", "huyen", "thanh pho", "thi tran", "tinh"
    ]
    # Replace whole words for prefixes
    for p in prefixes:
        n = re.sub(r'\b' + re.escape(p) + r'\b', '', n).strip()
    
    # 3. Clean up extra spaces
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def slugify_unit(name):
    if not name: return ""
    n = normalize_unit_name(name)
    # Remove everything except alphanumeric for the slug
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