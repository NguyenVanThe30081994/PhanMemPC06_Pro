# -*- coding: utf-8 -*-
import re, json, sqlite3, os, ast, operator as op
from urllib.parse import urlparse
from flask import request, render_template as flask_render_template, g, session, redirect, url_for
from openpyxl.utils import range_boundaries
from datetime import datetime, timedelta
from sqlalchemy import inspect, text
from models import db, User, AppRole, SystemLog, Notification, MasterData, NewsCategory, LibraryField, ContactGroup, ProfessionalUnit
from security_utils.runtime_security import generate_temporary_password


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
        "cax", "cap", "catt", "cah", "cat",
        "phuong", "xa", "huyen", "thanh pho", "thi tran", "tinh", "don vi", "ban"
    ]
    
    # First pass: try whole words
    for p in prefixes:
        n = re.sub(r'\b' + re.escape(p) + r'\b', ' ', n)
        
    # Second pass: remove common prefixes as substrings (handles smushed names)
    for p in ["congan", "ubnd", "catt", "cah", "cat", "cax", "cap", "phuong", "xapp", "ca"]:
        if n.startswith(p):
            n = n[len(p):].strip()

    # 3. Clean up extra spaces and non-alphanumeric (keep spaces for now)
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def extract_unit_key(name):
    """
    Extracts the core unit key from a unit name.
    'Công an xã An Tường' -> 'xaatuong'
    'UBND phường An Tường' -> 'phuongantuong'
    'phường An Tường' -> 'phuongantuong'
    """
    if not name: return ""

    import unicodedata

    n = str(name).lower().strip()
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('utf-8')
    n = re.sub(r'[^a-z0-9\s]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()

    tokens = n.split()
    if not tokens:
        return ""

    prefixes = [
        ('cong', 'an'),
        ('ubnd',),
        ('phong',),
        ('doi',),
        ('ban',),
        ('trung', 'tam'),
    ]
    while tokens:
        matched = False
        for prefix in prefixes:
            if len(tokens) >= len(prefix) and tuple(tokens[:len(prefix)]) == prefix:
                tokens = tokens[len(prefix):]
                matched = True
                break
        if not matched:
            break

    if not tokens:
        return ""

    unit_prefixes = {
        'phuong', 'xa', 'thi', 'tran', 'thi-tran', 'thixa', 'thixa',
        'huyen', 'quan', 'tp', 'thanhpho', 'thanh', 'pho', 'thi', 'xa', 'thi', 'tran'
    }

    lead = []
    while tokens and tokens[0] in {'phuong', 'xa', 'huyen', 'quan', 'tp', 'thi', 'tran'}:
        lead.append(tokens.pop(0))
        if lead[-1] == 'thi' and tokens and tokens[0] == 'tran':
            lead.append(tokens.pop(0))
            break

    if not lead and tokens:
        # No geographic prefix was present, keep the remaining slug.
        return re.sub(r'\s+', '', ' '.join(tokens))

    slug = ''.join(lead + tokens)
    return slug or re.sub(r'\s+', '', n)

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


def _ascii_unit_text(value):
    if not value:
        return ""
    import unicodedata
    text = str(value).strip().lower().replace('đ', 'd')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _unit_tail_slug(unit_name, prefix_text):
    normalized = _ascii_unit_text(unit_name)
    if not normalized.startswith(prefix_text):
        return ""
    tail = normalized[len(prefix_text):].strip()
    return re.sub(r'[^a-z0-9]+', '', tail)


def _person_slug(fullname):
    normalized = _ascii_unit_text(fullname)
    return re.sub(r'[^a-z0-9]+', '', normalized)


def _commander_title_suffix(position_name):
    normalized = _ascii_unit_text(position_name)
    if not normalized:
        return ""
    if "pho doi truong" in normalized or "doi pho" in normalized:
        return "pdt"
    if "doi truong" in normalized:
        return "dt"
    return ""

def build_account_username(unit_name, unit_key=None):
    """
    Tạo tên đăng nhập theo unit_key đã chuẩn hóa.
    """
    specialized_patterns = (
        ("cong an xa ", "cax"),
        ("cong an phuong ", "cap"),
        ("ubnd xa ", "ubndxa"),
        ("ubnd phuong ", "ubndphuong"),
    )
    for prefix_text, account_prefix in specialized_patterns:
        tail_slug = _unit_tail_slug(unit_name, prefix_text)
        if tail_slug:
            return f"{account_prefix}{tail_slug}"
    key = (unit_key or extract_unit_key(unit_name) or slugify_unit(unit_name) or '').strip().lower()
    key = re.sub(r'[^a-z0-9]+', '', key)
    return key


def build_role_account_username(role_name, unit_name, unit_key=None):
    """
    Tạo tên đăng nhập theo vai trò nếu có quy tắc riêng.
    """
    normalized_role = _ascii_unit_text(role_name)
    if normalized_role == 'to cong tac cap xa':
        normalized_unit = _ascii_unit_text(unit_name)
        if normalized_unit.startswith('to cong tac '):
            normalized_unit = normalized_unit[len('to cong tac '):].strip()
        key = (extract_unit_key(normalized_unit) or slugify_unit(normalized_unit) or unit_key or '').strip().lower()
        key = re.sub(r'[^a-z0-9]+', '', key)
        if key:
            return f"tct{key}"
    return build_account_username(unit_name, unit_key)


def build_commander_username(fullname, position_name):
    """
    Tạo tên đăng nhập cho chỉ huy đội theo dạng:
    pc06.<hotenkhongdau><.dt|.pdt>
    """
    name_slug = _person_slug(fullname)
    title_suffix = _commander_title_suffix(position_name)
    if not name_slug or not title_suffix:
        return ""
    return f"pc06.{name_slug}.{title_suffix}"

def normalize_unit_key(unit_name):
    """
    Chuẩn hóa tên đơn vị thành key duy nhất.
    
    Xử lý:
    - Loại bỏ dấu tiếng Việt (NFD decomposition)
    - Chuyển thành chữ thường
    - Normalize khoảng trắng
    
    Ví dụ:
    - "Phòng Kế Hoạch" → "phong ke hoach"
    - "phòng kế hoạch" → "phong ke hoach"
    - "PK" → "pk"
    - "Đơn Vị A" → "don vi a"
    
    Dùng cho: chuẩn hóa tên đơn vị để dò khớp dữ liệu
    """
    if not unit_name:
        return ""
    
    import unicodedata
    
    # 0. Convert to string and lowercase
    key = str(unit_name).lower().strip()
    
    # 1. Handle special Vietnamese character Đ/đ → d
    key = key.replace('đ', 'd')
    
    # 2. Loại bỏ dấu tiếng Việt (NFD decomposition)
    nfc = unicodedata.normalize('NFD', key)
    key = ''.join(c for c in nfc if unicodedata.category(c) != 'Mn')
    
    # 3. Normalize khoảng trắng (multiple spaces → single space)
    key = ' '.join(key.split())
    
    return key



def _repair_task_item_fk_constraints(app):
    """Sửa FK sai: task_submission.task_item_id / task_participant.task_item_id.

    Trước đây 2 cột này khai báo FOREIGN KEY trỏ nhầm sang task.id thay vì
    task_item.id, khiến nộp báo cáo đầu mục (OUTLINE) vỡ ràng buộc
    (IntegrityError: FOREIGN KEY constraint failed) khi task_item_id không
    trùng số hiệu task. Chạy an toàn: bỏ qua khi đã đúng hoặc gặp lỗi.
    """
    try:
        from sqlalchemy.schema import CreateTable
        from models import TaskSubmission, TaskParticipant
    except Exception:
        return

    engine = db.engine
    dialect = engine.dialect.name
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "task_item" not in existing_tables:
        return

    for table, model in (("task_submission", TaskSubmission), ("task_participant", TaskParticipant)):
        if table not in existing_tables:
            continue
        fk_defs = inspector.get_foreign_keys(table)
        target_fk = next(
            (
                fk
                for fk in fk_defs
                if fk.get("constrained_columns") == ["task_item_id"]
                and fk.get("referred_table") == "task"
            ),
            None,
        )
        if not target_fk:
            continue  # đã đúng hoặc chưa có ràng buộc cần sửa
        constraint_name = target_fk.get("name") or f"fk_{table}_task_item_id"
        try:
            with engine.begin() as conn:
                if dialect == "mysql":
                    conn.execute(text(f"ALTER TABLE {table} DROP FOREIGN KEY {constraint_name}"))
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
                            f"FOREIGN KEY (task_item_id) REFERENCES task_item(id)"
                        )
                    )
                elif dialect == "sqlite":
                    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                    try:
                        new_name = f"{table}__fkfix"
                        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{new_name}"')
                        ddl = str(CreateTable(model.__table__).compile(engine))
                        ddl = ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {new_name}", 1)
                        ddl = ddl.replace(f'CREATE TABLE "{table}"', f'CREATE TABLE "{new_name}"', 1)
                        conn.exec_driver_sql(ddl)
                        cols = ", ".join(c.name for c in model.__table__.columns)
                        conn.exec_driver_sql(
                            f'INSERT INTO "{new_name}" ({cols}) SELECT {cols} FROM "{table}"'
                        )
                        conn.exec_driver_sql(f'DROP TABLE "{table}"')
                        conn.exec_driver_sql(f'ALTER TABLE "{new_name}" RENAME TO "{table}"')
                        from sqlalchemy.schema import CreateIndex

                        for index in model.__table__.indexes:
                            conn.exec_driver_sql(str(CreateIndex(index).compile(engine)))
                    finally:
                        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                else:
                    continue
            app.logger.info("FIXED task_item FK on %s (was referencing task.id)", table)
        except Exception as exc:
            app.logger.warning("FK repair failed on %s: %s", table, exc)


def apply_migrations(app):
    with app.app_context():
        engine = db.engine
        dialect_name = engine.dialect.name
        migrations = [
        ("user", "must_change_password", "BOOLEAN DEFAULT 1"), 
        ("user", "unit_key", "VARCHAR(100)"),
        ("user", "session_version", "INTEGER DEFAULT 0"),
        ("app_role", "perms", "TEXT"),
        ("notification", "is_read", "BOOLEAN DEFAULT 0"),
        ("news_doc", "content", "TEXT"),
        ("news_doc", "target_scope", "VARCHAR(50) DEFAULT 'Toàn tỉnh'"),
        ("document_lib", "uploaded_at", "DATETIME"),
        ("task", "priority", "VARCHAR(50)"),
        ("task", "task_type", "VARCHAR(100)"),
        ("task", "initial_status", "VARCHAR(50) DEFAULT 'Chưa bắt đầu'"),
        ("task", "category", "VARCHAR(100)"),
        ("task", "parent_task_id", "INTEGER"),
        ("task", "assign_type", "VARCHAR(20) DEFAULT 'unit'"),
        ("task", "assignment_scope_json", "TEXT"),
        ("task", "viewer_scope_json", "TEXT"),
        ("task", "manager_scope_json", "TEXT"),
        ("task", "task_mode", "VARCHAR(20) DEFAULT 'FILE'"),
        ("task", "form_provider", "VARCHAR(20) DEFAULT 'internal'"),
        ("task", "google_form_url", "VARCHAR(500)"),
        ("task", "google_form_id", "VARCHAR(255)"),
        ("task", "google_form_match_mode", "VARCHAR(50)"),
        ("task", "google_form_match_field", "VARCHAR(255)"),
        ("task", "google_form_builder_json", "TEXT"),
        ("task", "google_form_runtime_json", "TEXT"),
        ("task", "google_form_sync_state_json", "TEXT"),
        ("task", "report_schema_json", "TEXT"),
        ("task", "outline_table_schema_json", "TEXT"),
        ("task", "created_at", "DATETIME"),
        ("task_import_draft", "source_type", "VARCHAR(50)"),
        ("task_import_draft", "source_name", "VARCHAR(255)"),
        ("task_import_draft", "source_ref", "VARCHAR(500)"),
        ("task_import_draft", "workflow_blueprint_json", "TEXT"),
        ("task_import_draft", "working_config_json", "TEXT"),
        ("task_import_draft", "status", "VARCHAR(30) DEFAULT 'draft'"),
        ("task_import_draft", "created_by", "INTEGER"),
        ("task_import_draft", "published_task_id", "INTEGER"),
        ("task_import_draft", "created_at", "DATETIME"),
        ("task_import_draft", "updated_at", "DATETIME"),
        ("task_import_draft", "published_at", "DATETIME"),
        ("task_item", "parent_item_id", "INTEGER"),
        ("task_item", "item_code", "VARCHAR(50)"),
        ("task_item", "guide_text", "TEXT"),
        ("task_item", "linked_item_id", "INTEGER"),
        ("task_item", "allow_aggregate", "BOOLEAN DEFAULT 0"),
        ("task_item", "report_sources_json", "TEXT"),
        ("task_item", "table_cells_json", "TEXT"),
        ("task_item", "is_required", "BOOLEAN DEFAULT 1"),
        ("task_item", "output_type", "VARCHAR(30) DEFAULT 'OUTLINE'"),
        ("task_assignment", "task_item_id", "INTEGER"),
        ("task_assignment", "assignee_type", "VARCHAR(20) DEFAULT 'user'"),
        ("task_assignment", "unit_id", "INTEGER"),
        ("task_assignment", "role_id", "INTEGER"),
        ("task_assignment", "title_snapshot", "VARCHAR(500)"),
        ("task_assignment", "is_required", "BOOLEAN DEFAULT 1"),
        ("task_assignment", "assigned_at", "DATETIME"),
        ("task_assignment", "submitted_at", "DATETIME"),
        ("task_assignment", "returned_at", "DATETIME"),
        ("task_assignment", "completed_at", "DATETIME"),
        ("task_assignment", "last_submission_id", "INTEGER"),
        ("task_assignment", "report_payload_json", "TEXT"),
        ("task_submission", "returned_at", "DATETIME"),
        ("task_submission", "approved_at", "DATETIME"),
        ("task_submission", "external_submission_id", "VARCHAR(255)"),
        ("task_submission", "external_source", "VARCHAR(30)"),
        ("task_submission", "synced_at", "DATETIME"),
        ("short_link", "category", "VARCHAR(100)"),
        ("short_link", "domain", "VARCHAR(100)"),
        ("task_comment", "assignee_id", "INTEGER DEFAULT 0"),
        ("system_log", "module", "VARCHAR(100)"),
        ("category_group", "code", "VARCHAR(100)"),
        ("category_group", "description", "VARCHAR(255)"),
        ("category_group", "is_active", "BOOLEAN DEFAULT 1"),
        ("category_group", "sort_order", "INTEGER DEFAULT 0"),
        ("category_item", "code", "VARCHAR(100)"),
        ("category_item", "is_active", "BOOLEAN DEFAULT 1"),
        ("category_item", "sort_order", "INTEGER DEFAULT 0"),
        ("notification_doc", "kind", "VARCHAR(20) DEFAULT 'notice'"),
        ("notification_doc", "description", "TEXT"),
        ("notification_doc", "file_ext", "VARCHAR(20)"),
        ("notification_doc", "video_url", "VARCHAR(500)"),
        ("notification_doc", "has_attachment", "BOOLEAN DEFAULT 0"),
        ("notification_doc", "posted_by", "VARCHAR(100)"),
        ("login_security_state", "last_failed_secret_hash", "VARCHAR(64)")
    ]
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        existing_columns = {}
        quote_identifier = engine.dialect.identifier_preparer.quote_identifier

        with engine.begin() as conn:
            for table, col, col_type in migrations:
                if table not in existing_tables:
                    continue
                if table not in existing_columns:
                    try:
                        existing_columns[table] = {column["name"] for column in inspector.get_columns(table)}
                    except Exception as e:
                        print(f"Schema Inspect Error on {table}: {e}")
                        existing_columns[table] = set()
                if col in existing_columns[table]:
                    continue
                try:
                    alter_sql = (
                        f"ALTER TABLE {quote_identifier(table)} "
                        f"ADD COLUMN {quote_identifier(col)} {col_type}"
                    )
                    conn.execute(text(alter_sql))
                    existing_columns[table].add(col)
                except Exception as e:
                    print(f"Migration Error on {table}.{col}: {e}")

        try:
            user_columns = existing_columns.get("user")
            if user_columns is None and "user" in existing_tables:
                user_columns = {column["name"] for column in inspector.get_columns("user")}
            if user_columns and "unit_key" in user_columns:
                users_to_update = []
                for user_id, fullname, unit_area, unit_key in db.session.query(
                    User.id,
                    User.fullname,
                    User.unit_area,
                    User.unit_key,
                ).all():
                    if unit_key:
                        continue
                    computed_key = extract_unit_key(fullname or unit_area or '')
                    if computed_key:
                        users_to_update.append({"id": user_id, "unit_key": computed_key})
                if users_to_update:
                    db.session.execute(
                        text("UPDATE user SET unit_key = :unit_key WHERE id = :id"),
                        users_to_update,
                    )
                    db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Backfill Error on user.unit_key: {e}")

    _repair_task_item_fk_constraints(app)

    if dialect_name != 'sqlite':
        return

    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_path = db_uri.replace('sqlite:///', '')
    if not os.path.exists(db_path):
        db_path = app.config.get('SQLITE_DB_PATH') or os.path.join(app.root_path, 'pc06_system.db')
        if not os.path.exists(db_path):
            return

    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
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
        """,
        """
        CREATE TABLE IF NOT EXISTS category_item_alias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            alias_name VARCHAR(255) NOT NULL,
            alias_slug VARCHAR(255)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_participant (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            task_item_id INTEGER,
            user_id INTEGER NOT NULL,
            role_id INTEGER,
            participant_type VARCHAR(30) DEFAULT 'executor',
            source_type VARCHAR(30) DEFAULT 'direct',
            source_ref VARCHAR(255),
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            source_task_id INTEGER,
            title VARCHAR(255),
            content TEXT,
            report_kind VARCHAR(30) DEFAULT 'narrative',
            attachment_required BOOLEAN DEFAULT 0,
            status VARCHAR(50) DEFAULT 'Chưa tiếp nhận',
            deadline DATE,
            sort_order INTEGER DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_submission (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            task_item_id INTEGER,
            participant_id INTEGER,
            assignment_id INTEGER,
            submitted_by INTEGER NOT NULL,
            submission_type VARCHAR(30) DEFAULT 'narrative',
            status VARCHAR(30) DEFAULT 'draft',
            narrative_content TEXT,
            numeric_value REAL,
            payload_json TEXT,
            attachment_name VARCHAR(255),
            attachment_path VARCHAR(500),
            submitted_at DATETIME,
            created_at DATETIME,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_submission_file (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            original_name VARCHAR(255),
            stored_name VARCHAR(255),
            stored_path VARCHAR(500),
            file_ext VARCHAR(20),
            mime_type VARCHAR(100),
            file_size INTEGER,
            is_signed BOOLEAN DEFAULT 0,
            uploaded_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_form_field (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            task_item_id INTEGER,
            field_key VARCHAR(100) NOT NULL,
            field_label VARCHAR(255) NOT NULL,
            field_type VARCHAR(50) DEFAULT 'text',
            field_options_json TEXT,
            sort_order INTEGER DEFAULT 0,
            is_required BOOLEAN DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_import_draft (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type VARCHAR(50),
            source_name VARCHAR(255),
            source_ref VARCHAR(500),
            workflow_blueprint_json TEXT,
            working_config_json TEXT,
            status VARCHAR(30) DEFAULT 'draft',
            created_by INTEGER NOT NULL,
            published_task_id INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            published_at DATETIME
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
                full_perms = {k:1 for k in ["p_dash", "p_task", "p_task_assign", "p_task_do", "p_notify", "p_contact", "p_form", "p_sys", "p_input", "p_stat", "p_user"]}
                admin_role = AppRole(name='admin_system', perms=json.dumps(full_perms, ensure_ascii=False))
                db.session.add(admin_role)
                db.session.commit()
            except Exception:
                db.session.rollback()
                admin_role = AppRole.query.filter_by(name='admin_system').first()
            
        # Admin User
        if admin_role and not User.query.filter_by(username='admin').first():
            try:
                bootstrap_password = (os.environ.get('BOOTSTRAP_ADMIN_PASSWORD') or '').strip() or generate_temporary_password()
                u = User(
                    username='admin',
                    fullname='Tài khoản quản trị',
                    role_id=admin_role.id,
                    unit_area='Hệ thống',
                    unit_key=extract_unit_key('Hệ thống')
                )
                u.must_change_password = True
                u.set_password(bootstrap_password)
                db.session.add(u)
                db.session.commit()
                print(f"[SECURITY] Initial admin account created with a temporary password: {bootstrap_password}")
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


def normalize_notification_text(value, max_length=255):
    text = str(value or '').replace('\x00', ' ').strip()
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    if max_length and len(text) > int(max_length):
        return text[: int(max_length)].rstrip()
    return text


def sanitize_notification_link(link):
    candidate = str(link or '').strip()
    if not candidate:
        return ''

    parsed = urlparse(candidate)
    if not parsed.scheme and not parsed.netloc:
        return candidate if candidate.startswith('/') else ''

    if parsed.scheme not in {'http', 'https'}:
        return ''
    if parsed.netloc != request.host:
        return ''

    path = parsed.path or '/'
    if parsed.query:
        path += f'?{parsed.query}'
    if parsed.fragment:
        path += f'#{parsed.fragment}'
    return path


def infer_notification_source(title="", msg="", link=""):
    title_text = (title or "").strip().lower()
    msg_text = (msg or "").strip().lower()
    link_text = (link or "").strip().lower()
    combined = " ".join([title_text, msg_text, link_text])

    if link_text.startswith("/tasks") or "công việc" in combined or "nhiệm vụ" in combined:
        return {
            "code": "task",
            "label": "Công việc",
            "icon": "fa-list-check",
            "class_name": "task",
        }
    if (link_text.startswith("/thong-bao")
            or link_text.startswith("/news")
            or link_text.startswith("/library")
            or "thông báo" in combined
            or "thong bao" in remove_accents(combined)
            or "bảng tin" in combined
            or "thư viện" in combined):
        return {
            "code": "notify",
            "label": "Thông báo",
            "icon": "fa-bullhorn",
            "class_name": "notify",
        }
    if link_text.startswith("/reports") or link_text.startswith("/admin/reports") or "báo cáo" in combined:
        return {
            "code": "report",
            "label": "Báo cáo",
            "icon": "fa-chart-column",
            "class_name": "report",
        }
    return {
        "code": "other",
        "label": "Khác",
        "icon": "fa-bell",
        "class_name": "other",
    }

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

PERMISSION_MODULES = [
    ("dash", "Tổng quan"),
    ("task", "Công việc"),
    ("notify", "Thông báo"),
    ("contact", "Danh bạ"),
    ("link", "QR và liên kết"),
    ("form", "Quản lý báo cáo"),
    ("input", "Nhập và gửi báo cáo"),
    ("stat", "Tiến độ báo cáo"),
    ("user", "Tài khoản"),
    ("sys", "Hệ thống"),
]

DEFAULT_ROLE_MODULE_CODES = (
    "dash",
    "task",
    "notify",
    "contact",
    "link",
)

# Vai trò chuẩn theo cơ cấu CAT / CAX
# process = tạo/sửa/xóa/giao | exec = tiếp nhận/báo cáo | view = chỉ xem
STANDARD_SYSTEM_ROLES = (
    {
        "name": "Quản trị hệ thống",
        "aliases": ("admin_system", "admin", "quản trị"),
        "level": "system",
        "description": "Toàn quyền hệ thống: cấu hình, tài khoản, mọi nghiệp vụ.",
        "perms": {
            "dash": ("view", "process", "exec"),
            "task": ("view", "process", "exec"),
            "notify": ("view", "process"),
            "contact": ("view", "process"),
            "link": ("view", "process"),
            "form": ("view", "process", "exec"),
            "input": ("view", "process", "exec"),
            "stat": ("view", "process"),
            "user": ("view", "process"),
            "sys": ("view", "process"),
        },
    },
    {
        "name": "Cán bộ CAT",
        "aliases": ("cán bộ pc06", "can bo pc06", "cán bộ tỉnh"),
        "level": "cat",
        "description": "Cán bộ nghiệp vụ cấp Tỉnh: giao việc, sửa việc mình tạo, thông báo, danh bạ, QR.",
        "perms": {
            "dash": ("view",),
            "task": ("view", "process"),
            "notify": ("view", "process"),
            "contact": ("view", "process"),
            "link": ("view", "process"),
        },
    },
    {
        "name": "Lãnh đạo - Chỉ huy CAT",
        "aliases": ("lãnh đạo cat", "chỉ huy cat", "chỉ huy pc06", "lãnh đạo pc06"),
        "level": "cat",
        "description": "Lãnh đạo cấp Tỉnh: xem công việc toàn cục, đăng thông báo, tra cứu danh bạ/QR.",
        "perms": {
            "dash": ("view",),
            "task": ("view",),
            "notify": ("view", "process"),
            "contact": ("view",),
            "link": ("view", "process"),
        },
    },
    {
        "name": "Cán bộ CAX",
        "aliases": ("cán bộ cax", "cán bộ xã", "can bo xa"),
        "level": "cax",
        "description": "Cán bộ cấp Xã: tiếp nhận và báo cáo công việc, xem thông báo/danh bạ/QR.",
        "perms": {
            "dash": ("view",),
            "task": ("view", "exec"),
            "notify": ("view",),
            "contact": ("view",),
            "link": ("view",),
        },
    },
    {
        "name": "Chỉ huy CAX",
        "aliases": ("chỉ huy cax", "chỉ huy xã", "chi huy xa"),
        "level": "cax",
        "description": "Chỉ huy cấp Xã: báo cáo/giám sát việc đơn vị, xem thông báo/danh bạ, tạo QR đơn vị.",
        "perms": {
            "dash": ("view",),
            "task": ("view", "exec"),
            "notify": ("view",),
            "contact": ("view",),
            "link": ("view", "process"),
        },
    },
)


def _role_name_key(role_name):
    return " ".join(str(role_name or "").strip().lower().split())


def match_standard_role(role_name):
    key = _role_name_key(role_name)
    if not key:
        return None
    for role_def in STANDARD_SYSTEM_ROLES:
        names = {_role_name_key(role_def["name"])}
        names.update(_role_name_key(alias) for alias in role_def.get("aliases") or ())
        if key in names:
            return role_def
        # Khớp gần: chứa đủ cụm chính trong tên vai trò
        for candidate in names:
            if candidate and candidate in key:
                return role_def
    return None


def build_permission_payload_from_module_map(module_map):
    payload = {}
    for module_code, tiers in (module_map or {}).items():
        for tier in tiers or ():
            normalized = str(tier or "").strip().lower()
            if normalized in {"view", "process", "exec"}:
                payload[f"p_{module_code}_{normalized}"] = 1
    return normalize_permission_payload(payload)


def standard_role_permission_payload(role_name):
    role_def = match_standard_role(role_name)
    if not role_def:
        return None
    return build_permission_payload_from_module_map(role_def.get("perms") or {})


def ensure_standard_system_roles(force_update_perms=False):
    """Tạo/cập nhật 5 vai trò chuẩn CAT-CAX. Trả về số vai trò đã chạm."""
    touched = 0
    for role_def in STANDARD_SYSTEM_ROLES:
        name = role_def["name"]
        payload = build_permission_payload_from_module_map(role_def.get("perms") or {})
        perms_json = json.dumps(payload, ensure_ascii=False)

        role = AppRole.query.filter_by(name=name).first()
        if not role:
            # Thử tìm alias cũ (vd admin_system)
            for alias in role_def.get("aliases") or ():
                role = AppRole.query.filter_by(name=alias).first()
                if role:
                    role.name = name
                    break
        if not role:
            role = AppRole(name=name, perms=perms_json)
            db.session.add(role)
            touched += 1
            continue

        if force_update_perms or not (role.perms or "").strip():
            role.perms = perms_json
            touched += 1
        elif role.name != name:
            role.name = name
            touched += 1
    if touched:
        db.session.commit()
    return touched


def role_default_permission_tier(role_name):
    """Suy ra tier mặc định khi tạo vai trò mới (fallback heuristic)."""
    role_def = match_standard_role(role_name)
    if role_def:
        # Ưu tiên process > exec > view theo định nghĩa chuẩn
        all_tiers = set()
        for tiers in (role_def.get("perms") or {}).values():
            all_tiers.update(tiers or ())
        if "process" in all_tiers and role_def.get("level") in {"system", "cat"}:
            # Cán bộ CAT / admin → process; lãnh đạo chỉ view
            if "lãnh đạo" in _role_name_key(role_def["name"]) or "chỉ huy cat" in _role_name_key(role_def["name"]):
                return "view"
            if role_def.get("level") == "cax":
                return "exec"
            return "process"
        if "exec" in all_tiers:
            return "exec"
        return "view"

    normalized_name = _role_name_key(role_name)
    if not normalized_name:
        return "exec"
    if any(marker in normalized_name for marker in ("quản trị", "admin")):
        return "process"
    if "cán bộ cat" in normalized_name or "can bo cat" in normalized_name:
        return "process"
    if "cán bộ pc06" in normalized_name or "can bo pc06" in normalized_name:
        return "process"
    if any(marker in normalized_name for marker in ("lãnh đạo", "lanh dao")):
        return "view"
    if "chỉ huy cat" in normalized_name or "chi huy cat" in normalized_name:
        return "view"
    if "chỉ huy" in normalized_name or "chi huy" in normalized_name:
        return "exec"
    if "cax" in normalized_name or "xã" in normalized_name or "xa " in normalized_name:
        return "exec"
    return "exec"


def build_default_role_permissions(role_name, module_codes=None):
    standard_payload = standard_role_permission_payload(role_name)
    if standard_payload is not None:
        if module_codes:
            allowed = set(module_codes)
            return {
                key: value
                for key, value in standard_payload.items()
                if any(key.startswith(f"p_{code}_") or key == f"p_{code}" for code in allowed)
            }
        return standard_payload

    selected_tier = role_default_permission_tier(role_name)
    payload = {}
    allowed_modules = set(module_codes or DEFAULT_ROLE_MODULE_CODES)
    for module_code, _label in PERMISSION_MODULES:
        if module_code not in allowed_modules:
            continue
        payload[f"p_{module_code}_{selected_tier}"] = 1
    return payload


# Ánh xạ mã module cũ -> mã module hiện tại để giữ tương thích dữ liệu quyền cũ
# (ví dụ trước đây module "Thông báo" có mã `news`, nay là `notify`).
PERMISSION_MODULE_ALIASES = {
    "notify": ("news",),
}

# Các khóa quyền cũ (không theo chuẩn *_view/*_process/*_exec) mà dữ liệu app_role.perms
# trước đây vẫn lưu, cần được ánh xạ sang tầng quyền hiện tại.
PERMISSION_LEGACY_TIER_KEYS = {
    "task": {
        "view": ("p_task_assign", "p_task_do"),
        "process": ("p_task_assign",),
        "exec": ("p_task_do",),
    },
}

PERMISSION_MODULE_CANONICAL = {}
for _module_code, _label in PERMISSION_MODULES:
    PERMISSION_MODULE_CANONICAL[_module_code] = _module_code
for _module_code, _aliases in PERMISSION_MODULE_ALIASES.items():
    for _alias in _aliases:
        PERMISSION_MODULE_CANONICAL[_alias] = _module_code


def _permission_module_keys(module_code):
    """Trả về danh sách khóa nguồn (cũ + mới) áp dụng cho một module quyền."""
    aliases = PERMISSION_MODULE_ALIASES.get(module_code, ())
    legacy_tiers = PERMISSION_LEGACY_TIER_KEYS.get(module_code, {})
    return {
        "aliases": aliases,
        "legacy": tuple(f"p_{alias}" for alias in aliases),
        "view": tuple([f"p_{module_code}_view"] + [f"p_{alias}_view" for alias in aliases] + list(legacy_tiers.get("view", ()))),
        "process": tuple([f"p_{module_code}_process", f"p_{module_code}_lead"] + [f"p_{alias}_process" for alias in aliases] + [f"p_{alias}_lead" for alias in aliases] + list(legacy_tiers.get("process", ()))),
        "exec": tuple([f"p_{module_code}_exec"] + [f"p_{alias}_exec" for alias in aliases] + list(legacy_tiers.get("exec", ()))),
    }


def _source_has_any(source, *keys):
    return any(bool(source.get(key)) for key in keys)


def role_permission_form_payload(perms_json, is_admin=False, role_name=""):
    try:
        source = json.loads(perms_json) if isinstance(perms_json, str) else dict(perms_json or {})
    except Exception:
        source = {}

    payload = {}
    role_name_normalized = (role_name or "").strip().lower()
    is_super_role = bool(is_admin or role_name_normalized in {"quản trị hệ thống", "admin_system"})

    for module_code, _label in PERMISSION_MODULES:
        keys = _permission_module_keys(module_code)
        legacy_key = f"p_{module_code}"
        view_key = f"p_{module_code}_view"
        process_key = f"p_{module_code}_process"
        exec_key = f"p_{module_code}_exec"

        if is_super_role:
            payload[view_key] = 1
            payload[process_key] = 1
            payload[exec_key] = 1
            for alias in keys["aliases"]:
                payload[f"p_{alias}_view"] = 1
                payload[f"p_{alias}_process"] = 1
                payload[f"p_{alias}_exec"] = 1
            continue

        has_view = _source_has_any(source, *keys["view"])
        has_process = _source_has_any(source, *keys["process"])
        has_exec = _source_has_any(source, *keys["exec"])

        if _source_has_any(source, legacy_key, *keys["legacy"]) and not (has_view or has_process or has_exec):
            has_view = True
            has_process = True
            has_exec = True

        if has_view:
            payload[view_key] = 1
            for alias in keys["aliases"]:
                payload[f"p_{alias}_view"] = 1
        if has_process:
            payload[process_key] = 1
            for alias in keys["aliases"]:
                payload[f"p_{alias}_process"] = 1
                payload[f"p_{alias}_lead"] = 1
        if has_exec:
            payload[exec_key] = 1
            for alias in keys["aliases"]:
                payload[f"p_{alias}_exec"] = 1

    return payload


def normalize_permission_payload(perms_json, is_admin=False, role_name=""):
    normalized = role_permission_form_payload(perms_json, is_admin=is_admin, role_name=role_name)
    role_name_normalized = (role_name or "").strip().lower()
    is_super_role = bool(is_admin or role_name_normalized in {"quản trị hệ thống", "admin_system"})

    for module_code, _label in PERMISSION_MODULES:
        keys = _permission_module_keys(module_code)
        legacy_key = f"p_{module_code}"
        lead_key = f"p_{module_code}_lead"
        view_key = f"p_{module_code}_view"
        process_key = f"p_{module_code}_process"
        exec_key = f"p_{module_code}_exec"

        has_view = _source_has_any(normalized, view_key, *[f"p_{alias}_view" for alias in keys["aliases"]])
        has_process = _source_has_any(normalized, process_key, lead_key, *[f"p_{alias}_process" for alias in keys["aliases"]], *[f"p_{alias}_lead" for alias in keys["aliases"]])
        has_exec = _source_has_any(normalized, exec_key, *[f"p_{alias}_exec" for alias in keys["aliases"]])

        if _source_has_any(normalized, legacy_key, *keys["legacy"]):
            has_view = True
            has_process = True
            has_exec = True

        if _source_has_any(normalized, lead_key, *[f"p_{alias}_lead" for alias in keys["aliases"]]):
            has_view = True
            has_process = True

        if has_exec:
            has_view = True

        if is_super_role:
            has_view = True
            has_process = True
            has_exec = True

        if has_process or has_exec:
            has_view = True

        if has_view:
            normalized[view_key] = 1
            for alias in keys["aliases"]:
                normalized[f"p_{alias}_view"] = 1
        if has_process:
            normalized[process_key] = 1
            normalized[lead_key] = 1
            for alias in keys["aliases"]:
                normalized[f"p_{alias}_process"] = 1
                normalized[f"p_{alias}_lead"] = 1
        if has_exec:
            normalized[exec_key] = 1
            for alias in keys["aliases"]:
                normalized[f"p_{alias}_exec"] = 1
        if has_view or has_process or has_exec:
            normalized[legacy_key] = 1

    return normalized


def module_permission_flags(perms_json, module_code, is_admin=False, role_name=""):
    normalized = normalize_permission_payload(perms_json, is_admin=is_admin, role_name=role_name)
    module = PERMISSION_MODULE_CANONICAL.get((module_code or "").strip().lower(), (module_code or "").strip().lower())
    if not module:
        return {"view": False, "process": False, "exec": False, "any": False}
    flags = {
        "view": bool(normalized.get(f"p_{module}_view")),
        "process": bool(normalized.get(f"p_{module}_process")),
        "exec": bool(normalized.get(f"p_{module}_exec")),
    }
    flags["any"] = bool(flags["view"] or flags["process"] or flags["exec"])
    return flags


def has_module_permission(perms_json, module_code, tier="view", is_admin=False, role_name=""):
    flags = module_permission_flags(perms_json, module_code, is_admin=is_admin, role_name=role_name)
    normalized_tier = (tier or "view").strip().lower()
    if normalized_tier in {"any", "access"}:
        return flags["any"]
    if normalized_tier in {"manage", "process"}:
        return flags["process"]
    if normalized_tier in {"execute", "exec"}:
        return flags["exec"]
    return flags["view"]


def has_any_module_permission(perms_json, module_codes, tier="view", is_admin=False, role_name=""):
    return any(
        has_module_permission(perms_json, module_code, tier=tier, is_admin=is_admin, role_name=role_name)
        for module_code in (module_codes or [])
    )

def get_perms_labels(perms_json):
    if not perms_json: return ""
    labels_map = {code: label for code, label in PERMISSION_MODULES}
    try:
        p = role_permission_form_payload(perms_json)
        if not p: return ""
        res = []
        for module_code, module_label in PERMISSION_MODULES:
            if p.get(f"p_{module_code}_view"):
                res.append(f"{module_label} (Xem)")
            if p.get(f"p_{module_code}_process"):
                res.append(f"{module_label} (Xử lý)")
            if p.get(f"p_{module_code}_exec"):
                res.append(f"{module_label} (Thực hiện)")
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
