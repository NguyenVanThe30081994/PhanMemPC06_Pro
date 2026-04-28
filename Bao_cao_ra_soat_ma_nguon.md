# BÁO CÁO RÀ SOÁT MÃ NGUỒN - PHẦN MỀM PC06

**Ngày rà soát:** 28/04/2026  
**Phiên bản:** 3.5.0  
**Người thực hiện:** Kiro AI Assistant

---

## TỔNG QUAN

Đã thực hiện rà soát toàn bộ mã nguồn của phần mềm PC06, bao gồm:
- 27 file Python chính
- 12 module routes
- 2 module services
- 47+ file templates HTML
- 1 database SQLite với 38 bảng

**Kết quả:** Phát hiện **19 vấn đề** cần xử lý, phân loại theo mức độ nghiêm trọng.

---

## 1. VẤN ĐỀ BẢO MẬT (SECURITY) - CRITICAL

### 1.1 ⚠️ Hardcoded Secret Key
**Vị trí:** `app.py:43`
```python
app.secret_key = 'PC06_FINAL_V3_5_2026'
```
**Rủi ro:** Secret key bị lộ khi push code lên Git, attacker có thể forge session cookies  
**Giải pháp:**
```python
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
```

### 1.2 ⚠️ SQL Injection Risk
**Vị trí:** `routes/admin.py:898-901`
```python
cursor.execute(f"PRAGMA table_info({table})")
cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
```
**Rủi ro:** Có thể bị SQL injection nếu table name không được validate  
**Giải pháp:** Whitelist table names và validate input

### 1.3 ⚠️ File Upload Security
**Vị trí:** `routes/portal.py:124-128, 172-175`
**Rủi ro:**
- Không giới hạn kích thước file
- Không kiểm tra MIME type thực tế
- Có thể upload file độc hại

**Giải pháp:**
```python
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'pdf', 'docx', 'png', 'jpg'}
ALLOWED_MIME_TYPES = {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/pdf',
    'image/png',
    'image/jpeg'
}

def validate_file(file):
    # Check extension
    if not allowed_file(file.filename):
        return False
    # Check MIME type
    mime = magic.from_buffer(file.read(1024), mime=True)
    file.seek(0)
    return mime in ALLOWED_MIME_TYPES
```

---

## 2. VẤN ĐỀ BẢO MẬT (SECURITY) - HIGH

### 2.1 Default Weak Password
**Vị trí:** `routes/admin.py:249, 413`
```python
password = request.form.get('password', '123456')
u.set_password('123456')
```
**Rủi ro:** Mật khẩu mặc định quá yếu, dễ bị brute force  
**Giải pháp:** Yêu cầu mật khẩu mạnh (min 8 ký tự, có chữ hoa, số, ký tự đặc biệt)

### 2.2 XSS Vulnerabilities
**Vị trí:** `templates/roles.html`, `templates/roles_mobile.html`
```html
{{ r.perms|safe if r.perms else "{}" }}
```
**Rủi ro:** Nếu perms chứa script độc hại, sẽ được execute  
**Giải pháp:** Validate và sanitize JSON trước khi render

### 2.3 Missing Session Security
**Vị trí:** `app.py`
**Rủi ro:** Session cookies không có security flags  
**Giải pháp:**
```python
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
```

### 2.4 Missing CSRF Protection
**Vị trí:** Nhiều POST endpoints
**Rủi ro:** Có thể bị CSRF attack  
**Giải pháp:** Đã có WTF_CSRF_TIME_LIMIT nhưng cần kiểm tra xem có áp dụng đầy đủ không

### 2.5 Missing Input Validation
**Vị trí:** Nhiều routes
**Rủi ro:** Không validate đầy đủ input có thể dẫn đến data corruption hoặc injection  
**Ví dụ cần validate:**
- Email format
- Phone number (E.164)
- Date ranges
- Numeric ranges
- Username format

---

## 3. VẤN ĐỀ HIỆU NĂNG (PERFORMANCE) - MEDIUM

### 3.1 Missing Database Indexes
**Phát hiện:** 8 bảng thiếu indexes quan trọng

| Bảng | Cột thiếu index | Impact |
|------|----------------|--------|
| `notification` | `user_id`, `created_at` | Slow notification queries |
| `task` | `author_id`, `deadline`, `domain` | Slow task listing |
| `task_assignment` | `task_id`, `user_id`, `status` | Slow assignment queries |
| `task_comment` | `task_id`, `created_at` | Slow comment loading |
| `system_log` | `user_id`, `created_at`, `module` | Slow log queries |
| `report_submission_v2` | `user_id`, `version_id`, `status` | Slow report queries |
| `report_value_v2` | `submission_id`, `cell_key` | Slow value lookups |
| `zalo_message_log` | `created_at`, `status` | Slow log queries |

**Giải pháp:** Tạo migration script để thêm indexes:
```python
# migrate_add_indexes.py
def add_indexes():
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_user_created ON notification(user_id, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_author_deadline ON task(author_id, deadline)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_assignment_composite ON task_assignment(task_id, user_id, status)')
    # ... thêm các indexes khác
```

### 3.2 N+1 Query Problem
**Vị trí:** `routes/admin.py:280-285`
```python
users = users_query.order_by(User.fullname.asc()).all()
# Sau đó loop qua users và access user.role -> N+1 queries
```
**Giải pháp:**
```python
from sqlalchemy.orm import joinedload
users = users_query.options(joinedload(User.role)).order_by(User.fullname.asc()).all()
```

### 3.3 Large Data Loading
**Vị trí:** Nhiều nơi load toàn bộ data không phân trang  
**Giải pháp:** Implement pagination cho các danh sách lớn

---

## 4. VẤN ĐỀ MÃ NGUỒN (CODE QUALITY) - MEDIUM

### 4.1 Poor Exception Handling
**Vị trí:** Nhiều file trong `routes/`
```python
except Exception:
    perms = {}
```
**Vấn đề:**
- Catch quá rộng, không biết lỗi gì
- Không log chi tiết
- Không có error recovery

**Giải pháp:**
```python
except json.JSONDecodeError as e:
    app.logger.error(f"Failed to parse perms JSON: {e}")
    perms = {}
except Exception as e:
    app.logger.exception(f"Unexpected error loading perms: {e}")
    perms = {}
```

### 4.2 Transaction Management Issues
**Phát hiện:** 39 lần gọi `db.session.commit()` nhưng chỉ 13 nơi có `rollback()`  
**Rủi ro:** Nếu có lỗi sau commit, data có thể bị inconsistent  
**Giải pháp:** Sử dụng context manager:
```python
try:
    # operations
    db.session.commit()
except Exception as e:
    db.session.rollback()
    app.logger.error(f"Transaction failed: {e}")
    raise
```

### 4.3 Temporary Files in Root
**Phát hiện:** 5 file `tmp_*.py` trong root directory
```
tmp_cleanup_report_docx.py
tmp_dedupe_report_docx.py
tmp_rebuild_report_sections.py
tmp_reorder_report_docx.py
tmp_reorder_report_docx_v2.py
```
**Giải pháp:** Xóa hoặc di chuyển vào `scratch/` hoặc `scripts/`

### 4.4 Code Duplication
**Vấn đề:** Logic kiểm tra permissions lặp lại nhiều nơi  
**Giải pháp:** Tạo decorator:
```python
def require_permission(perm_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not has_permission(perm_name):
                flash('Bạn không có quyền truy cập', 'danger')
                return redirect(url_for('tasks_bp.tasks'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@admin_bp.route('/admin')
@require_permission('is_admin')
def index():
    # ...
```

### 4.5 Magic Numbers
**Ví dụ:** `app.py:70`
```python
app.config['WTF_CSRF_TIME_LIMIT'] = 3600
```
**Giải pháp:**
```python
# constants.py
CSRF_TOKEN_LIFETIME = 3600  # 1 hour
SESSION_LIFETIME = 28800  # 8 hours
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB
```

---

## 5. VẤN ĐỀ CẤU HÌNH (CONFIGURATION) - MEDIUM

### 5.1 Incomplete .env.example
**Hiện tại:**
```
AI_ASSISTANT_PROVIDER=deepseek
AI_ASSISTANT_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your_new_deepseek_key_here
```

**Cần bổ sung:**
```
# Security
SECRET_KEY=your-secret-key-here
SESSION_LIFETIME=28800

# Database
DATABASE_URL=sqlite:///pc06_system.db

# File Upload
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216

# Email (if needed)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=

# Zalo Integration
ZALO_APP_ID=
ZALO_APP_SECRET=

# Environment
FLASK_ENV=production
DEBUG=False
```

### 5.2 Missing Production Settings
**Vấn đề:** Không rõ app chạy ở mode nào  
**Giải pháp:** Thêm vào `app.py`:
```python
if os.environ.get('FLASK_ENV') == 'production':
    app.debug = False
    app.config['TESTING'] = False
```

---

## 6. VẤN ĐỀ LOGGING & MONITORING - LOW

### 6.1 Insufficient Security Logging
**Thiếu log cho:**
- Failed login attempts
- Permission denials
- File upload attempts
- Data modifications

**Giải pháp:**
```python
@auth_bp.route('/login', methods=['POST'])
def login():
    # ...
    if not usr or not usr.check_password(pwd):
        app.logger.warning(f"Failed login attempt for username: {uname} from IP: {request.remote_addr}")
        # ...
```

### 6.2 No Health Check Endpoint
**Giải pháp:**
```python
@app.route('/health')
def health_check():
    try:
        # Check database
        db.session.execute('SELECT 1')
        return jsonify({'status': 'healthy', 'database': 'ok'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503
```

---

## 7. VẤN ĐỀ DOCUMENTATION - LOW

### 7.1 Missing API Documentation
**Giải pháp:** Sử dụng Flask-RESTX hoặc tạo OpenAPI spec

### 7.2 Missing Docstrings
**Nhiều function phức tạp không có docstring**  
**Ví dụ:** `routes/reporting.py` có nhiều function phức tạp cần document

---

## 8. ĐIỂM TÍCH CỰC

✅ **Cấu trúc code tốt:** Tách biệt routes, models, services  
✅ **Syntax đúng:** Tất cả 41 file Python đều compile thành công  
✅ **Database integrity:** Không có orphaned records, không có duplicate keys  
✅ **Foreign keys:** Đã có foreign key constraints đầy đủ  
✅ **Authentication:** Có kiểm tra authentication ở hầu hết routes  
✅ **UTF-8 handling:** Đã xử lý tốt tiếng Việt  
✅ **Logging infrastructure:** Đã có RotatingFileHandler  

---

## 9. KHUYẾN NGHỊ ƯU TIÊN

### 🔴 CRITICAL - Xử lý ngay (1-2 ngày)
1. **Fix hardcoded secret key** - Chuyển sang environment variable
2. **Fix SQL injection risk** - Validate table names
3. **Add file upload validation** - Kiểm tra MIME type và size

### 🟠 HIGH - Xử lý trong tuần
4. **Strengthen default password** - Yêu cầu mật khẩu mạnh
5. **Fix XSS vulnerabilities** - Sanitize JSON data
6. **Add session security flags** - Secure cookies
7. **Add input validation** - Validate tất cả user input
8. **Add database indexes** - Cải thiện performance

### 🟡 MEDIUM - Xử lý trong tháng
9. **Improve exception handling** - Log chi tiết hơn
10. **Fix transaction management** - Thêm rollback đầy đủ
11. **Remove temporary files** - Dọn dẹp code
12. **Refactor duplicate code** - Tạo decorators/helpers
13. **Add constants file** - Loại bỏ magic numbers
14. **Complete .env.example** - Document đầy đủ config
15. **Fix N+1 queries** - Sử dụng eager loading

### 🟢 LOW - Khi có thời gian
16. **Add security logging** - Log security events
17. **Add health check endpoint** - Monitoring
18. **Add API documentation** - OpenAPI spec
19. **Add docstrings** - Document functions

---

## 10. SCRIPT HỖ TRỢ

### Script 1: Thêm Database Indexes
```python
# scripts/add_indexes.py
import sqlite3

def add_indexes():
    conn = sqlite3.connect('pc06_system.db')
    cursor = conn.cursor()
    
    indexes = [
        'CREATE INDEX IF NOT EXISTS idx_notification_user_created ON notification(user_id, created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_task_author_deadline ON task(author_id, deadline)',
        'CREATE INDEX IF NOT EXISTS idx_task_domain ON task(domain)',
        'CREATE INDEX IF NOT EXISTS idx_task_assignment_composite ON task_assignment(task_id, user_id, status)',
        'CREATE INDEX IF NOT EXISTS idx_task_comment_task_created ON task_comment(task_id, created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_system_log_user_created ON system_log(user_id, created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_system_log_module ON system_log(module)',
        'CREATE INDEX IF NOT EXISTS idx_report_submission_user ON report_submission_v2(user_id)',
        'CREATE INDEX IF NOT EXISTS idx_report_submission_version ON report_submission_v2(version_id)',
        'CREATE INDEX IF NOT EXISTS idx_report_submission_status ON report_submission_v2(status)',
        'CREATE INDEX IF NOT EXISTS idx_report_value_submission ON report_value_v2(submission_id)',
        'CREATE INDEX IF NOT EXISTS idx_report_value_cell ON report_value_v2(cell_key)',
        'CREATE INDEX IF NOT EXISTS idx_zalo_log_created ON zalo_message_log(created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_zalo_log_status ON zalo_message_log(status)',
    ]
    
    for idx_sql in indexes:
        try:
            cursor.execute(idx_sql)
            print(f"✓ {idx_sql[:50]}...")
        except Exception as e:
            print(f"✗ Error: {e}")
    
    conn.commit()
    conn.close()
    print("\n✓ All indexes added successfully!")

if __name__ == '__main__':
    add_indexes()
```

### Script 2: Validate File Security
```python
# utils/file_validator.py
import magic
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg'}
ALLOWED_MIME_TYPES = {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
    'image/png',
    'image/jpeg'
}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file_upload(file):
    """Validate uploaded file for security"""
    if not file or not file.filename:
        return False, "No file provided"
    
    # Check filename
    if not allowed_file(file.filename):
        return False, "File type not allowed"
    
    # Check file size
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)  # Reset
    
    if size > MAX_FILE_SIZE:
        return False, f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)"
    
    # Check MIME type
    mime = magic.from_buffer(file.read(1024), mime=True)
    file.seek(0)
    
    if mime not in ALLOWED_MIME_TYPES:
        return False, f"Invalid file type: {mime}"
    
    return True, secure_filename(file.filename)
```

---

## KẾT LUẬN

Phần mềm PC06 có **cấu trúc tốt** và **hoạt động ổn định**, nhưng cần xử lý **19 vấn đề** để đảm bảo:
- ✅ Bảo mật cao hơn
- ✅ Hiệu năng tốt hơn  
- ✅ Code quality cao hơn
- ✅ Dễ maintain hơn

**Ưu tiên cao nhất:** Xử lý 3 vấn đề CRITICAL về bảo mật trong 1-2 ngày tới.

---

**Người lập báo cáo:** Kiro AI Assistant  
**Ngày:** 28/04/2026  
**Phiên bản phần mềm:** 3.5.0
