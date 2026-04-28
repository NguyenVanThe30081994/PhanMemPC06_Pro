# HOTFIX - Import Error Fix

**Ngày:** 28/04/2026
**Vấn đề:** ImportError khi deploy lên production
**Trạng thái:** ✅ Đã fix

## 🐛 Vấn đề

Khi deploy lên production, gặp lỗi:
```
ImportError: cannot import name 'init_db' from 'utils'
```

**Nguyên nhân:** 
- Tạo package `utils/` mới nhưng file `utils.py` cũ vẫn tồn tại
- Python ưu tiên import từ package `utils/` thay vì file `utils.py`
- Package mới không có các functions cũ: `init_db`, `get_perms_labels`, `is_mobile_device`

## ✅ Giải pháp

Đổi tên package `utils/` thành `security_utils/` để tránh conflict:

```bash
# 1. Rename package
mv utils/ security_utils/

# 2. Update imports trong các file đã sửa
# routes/admin.py
# routes/portal.py  
# routes/auth.py
```

## 📝 Thay đổi

### File structure
```
TRƯỚC:
utils.py              # File cũ
utils/                # Package mới (CONFLICT!)
  __init__.py
  file_validator.py
  password_validator.py
  security_helpers.py

SAU:
utils.py              # File cũ (giữ nguyên)
security_utils/       # Package mới (renamed)
  __init__.py
  file_validator.py
  password_validator.py
  security_helpers.py
```

### Import changes

**routes/admin.py:**
```python
# TRƯỚC
from utils.security_helpers import validate_table_name

# SAU
from security_utils.security_helpers import validate_table_name
```

**routes/portal.py:**
```python
# TRƯỚC
from utils.file_validator import validate_file_upload

# SAU
from security_utils.file_validator import validate_file_upload
```

**routes/auth.py:**
```python
# TRƯỚC
from utils.security_helpers import log_security_event

# SAU
from security_utils.security_helpers import log_security_event
```

## 🧪 Kiểm tra

```bash
# Test old utils.py
python3 -c "from utils import init_db, get_perms_labels, is_mobile_device; print('✅ OK')"

# Test new security_utils
python3 -c "from security_utils import validate_file_upload, validate_password; print('✅ OK')"

# Test app.py syntax
python3 -c "import ast; ast.parse(open('app.py').read()); print('✅ OK')"

# Test all modified routes
for file in routes/admin.py routes/portal.py routes/auth.py routes/health.py; do
    python3 -c "import ast; ast.parse(open('$file').read())" && echo "✅ $file"
done
```

## 🚀 Deploy

Sau khi fix, deploy lại:

```bash
# 1. Commit changes
git add security_utils/ routes/
git commit -m "Hotfix: Rename utils/ to security_utils/ to avoid import conflict"

# 2. Deploy
git push origin main

# 3. Restart application
# (trên server production)
touch tmp/restart.txt
# hoặc
sudo systemctl restart pc06
```

## 📊 Kết quả

✅ Không còn ImportError
✅ utils.py cũ vẫn hoạt động bình thường
✅ security_utils mới hoạt động độc lập
✅ Tất cả syntax checks passed

## 📚 Cập nhật tài liệu

Các file cần cập nhật:
- [x] HOTFIX_IMPORT_ERROR.md (file này)
- [ ] README_SECURITY_UPDATES.md - Update package name
- [ ] IMPLEMENTATION_SUMMARY.md - Update package name
- [ ] SECURITY_FIXES.md - Update import examples

---

**Người fix:** Kiro AI Assistant
**Thời gian:** 28/04/2026 - 12:23
**Trạng thái:** ✅ Đã fix và test thành công
