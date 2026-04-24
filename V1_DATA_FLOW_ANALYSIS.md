# 🔍 V1 Data Flow Analysis - Root Cause

## 📌 Vấn đề Chính

V1 stats không hiển thị dữ liệu mới vì:
1. **Unit key không chuẩn hóa** - Tên đơn vị biến thể (dấu, tiền tố, cách viết)
2. **Không có bản ghi "latest"** - Khi có nhiều submission, không biết lấy cái nào
3. **Map đơn vị → dòng không cố định** - Dựa vào thứ tự query không ổn định
4. **Không refresh sau lưu** - Dữ liệu cũ vẫn được cache

## 📊 Data Flow Hiện Tại

```
POST /form (submit data)
    ↓
Save to ReportData (insert new row)
    ↓
Redirect to /stats?rid=X
    ↓
Query ReportData (order by report_date desc, unit_area)
    ↓
Build submissions list
    ↓
Match unit name → Excel row (PROBLEM!)
    ↓
Render HTML
```

## 🐛 Các Vấn Đề Chi Tiết

### 1. Unit Key Không Chuẩn Hóa
```python
# Hiện tại: So khớp chuỗi thô
unit = user.unit_area or user.fullname  # "Phòng Kế Hoạch"
cell_v = ws.cell(row=r, column=c).value  # "Phòng kế hoạch" hoặc "PK"

# Vấn đề:
# - Dấu tiếng Việt: "Phòng" vs "Phòng"
# - Cách viết: "Phòng Kế Hoạch" vs "phòng kế hoạch"
# - Tiền tố: "Phòng Kế Hoạch" vs "PK"
# - Không match → dữ liệu không render
```

### 2. Không Có "Latest" Flag
```python
# Hiện tại: Lấy tất cả submissions
raw = (db.session.query(ReportData, User)
       .join(User, ReportData.user_id == User.id)
       .filter(ReportData.report_id == rid)
       .order_by(ReportData.report_date.desc(), User.unit_area)
       .all())

# Vấn đề:
# - Nếu đơn vị A submit 2 lần → có 2 row
# - Không biết lấy row nào (mới nhất? cũ nhất?)
# - Render có thể lấy dữ liệu cũ
```

### 3. Map Đơn Vị → Dòng Không Cố Định
```python
# Hiện tại: Dựa vào thứ tự query
for entry, user in raw:
    unit = user.unit_area
    submissions.append({'unit': unit, 'values': {...}})

# Trong render:
for name in unit_names_lower:
    for c_check in range(min_col, max_col + 1):
        cell_v = ws.cell(row=r, column=c_check).value
        if is_unit_match(name, str(cell_v)):
            matched_sub = unit_map_lower[name]
            break

# Vấn đề:
# - Thứ tự query có thể thay đổi
# - Unit matching dựa vào tên → không ổn định
# - Dòng Excel không được map cố định
```

### 4. Không Refresh Sau Lưu
```python
# Hiện tại:
POST /form → Save → Redirect /stats?rid=X

# Vấn đề:
# - Dữ liệu cũ có thể được cache
# - Session/request vẫn giữ dữ liệu cũ
# - Không buộc query lại từ DB
```

## 🔧 Giải Pháp

### 1. Chuẩn Hóa Unit Key
```python
def normalize_unit_key(unit_name):
    """Chuẩn hóa tên đơn vị thành key duy nhất"""
    if not unit_name:
        return ""
    
    # Loại bỏ dấu tiếng Việt
    import unicodedata
    nfc = unicodedata.normalize('NFD', str(unit_name))
    key = ''.join(c for c in nfc if unicodedata.category(c) != 'Mn')
    
    # Chuyển thành chữ thường, loại bỏ khoảng trắng
    key = key.lower().strip()
    key = ' '.join(key.split())  # Normalize spaces
    
    return key

# Ví dụ:
normalize_unit_key("Phòng Kế Hoạch") → "phong ke hoach"
normalize_unit_key("phòng kế hoạch") → "phong ke hoach"
normalize_unit_key("PK") → "pk"
```

### 2. Thêm "Latest" Flag
```python
# Trong ReportData model:
class ReportData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report_config.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    data_json = db.Column(db.Text)
    report_date = db.Column(db.DateTime)
    is_latest = db.Column(db.Boolean, default=True)  # ← NEW
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Khi lưu:
# 1. Mark old records as is_latest=False
# 2. Insert new record with is_latest=True
```

### 3. Map Cố Định Đơn Vị → Dòng
```python
# Tạo bảng ánh xạ:
class UnitMapping(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report_config.id'))
    unit_key = db.Column(db.String(255))  # Normalized key
    excel_row = db.Column(db.Integer)  # Fixed row in template
    display_name = db.Column(db.String(255))  # Display name
    aliases = db.Column(db.Text)  # JSON: ["alias1", "alias2"]

# Khi render:
# 1. Load UnitMapping
# 2. Map unit_key → excel_row (cố định)
# 3. Lấy dữ liệu từ submissions[unit_key]
```

### 4. Refresh Sau Lưu
```python
# Trong route POST:
@forms_bp.route('/form', methods=['POST'])
def submit_form():
    # ... save data ...
    db.session.commit()
    
    # Refresh: Redirect với parameter để buộc query lại
    return redirect(url_for('forms_bp.stats', rid=rid, refresh=1))

# Trong route GET:
@forms_bp.route('/stats')
def stats():
    refresh = request.args.get('refresh') == '1'
    
    if refresh:
        # Clear cache, query lại từ DB
        db.session.expunge_all()
    
    # ... query data ...
```

## 📋 Implementation Plan

### Phase 1: Chuẩn Hóa Unit Key
- [ ] Tạo hàm `normalize_unit_key()`
- [ ] Cập nhật ReportData model
- [ ] Cập nhật routes/forms.py

### Phase 2: Latest Flag
- [ ] Thêm `is_latest` column
- [ ] Migration
- [ ] Cập nhật save logic

### Phase 3: Unit Mapping
- [ ] Tạo UnitMapping model
- [ ] Tạo UI để config mapping
- [ ] Cập nhật render logic

### Phase 4: Refresh
- [ ] Cập nhật redirect logic
- [ ] Clear cache
- [ ] Test

## 🎯 Priority

1. **HIGH:** Chuẩn hóa unit key (quick win)
2. **HIGH:** Latest flag (prevent old data)
3. **MEDIUM:** Unit mapping (stability)
4. **MEDIUM:** Refresh (UX)

## 📝 Files Cần Sửa

1. `utils.py` - Thêm `normalize_unit_key()`
2. `models.py` - Thêm `is_latest`, `UnitMapping`
3. `routes/forms.py` - Cập nhật save/query logic
4. `excel_renderer.py` - Cập nhật render logic
5. Migration files - Database schema

## ✅ Verification

```python
# Test normalize_unit_key
assert normalize_unit_key("Phòng Kế Hoạch") == normalize_unit_key("phòng kế hoạch")

# Test latest flag
latest = ReportData.query.filter_by(report_id=1, is_latest=True).all()
assert len(latest) == len(set(u.user_id for u in latest))  # One per user

# Test unit mapping
mapping = UnitMapping.query.filter_by(report_id=1).all()
assert len(mapping) > 0
```
