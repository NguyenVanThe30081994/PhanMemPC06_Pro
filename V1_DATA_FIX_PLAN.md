# 🛠️ V1 Data Fix - Implementation Plan

## 📌 Tóm tắt

V1 stats không hiển thị dữ liệu mới vì:
1. Unit key không chuẩn hóa → không match
2. Không có "latest" flag → lấy dữ liệu cũ
3. Map đơn vị → dòng không cố định → render sai
4. Không refresh sau lưu → cache cũ

## 🎯 Giải pháp

### Phase 1: Chuẩn Hóa Unit Key (QUICK WIN)

**File:** `utils.py`

```python
import unicodedata

def normalize_unit_key(unit_name):
    """
    Chuẩn hóa tên đơn vị thành key duy nhất.
    
    Xử lý:
    - Loại bỏ dấu tiếng Việt
    - Chuyển thành chữ thường
    - Normalize khoảng trắng
    
    Ví dụ:
    - "Phòng Kế Hoạch" → "phong ke hoach"
    - "phòng kế hoạch" → "phong ke hoach"
    - "PK" → "pk"
    """
    if not unit_name:
        return ""
    
    # Loại bỏ dấu tiếng Việt (NFD decomposition)
    nfc = unicodedata.normalize('NFD', str(unit_name))
    key = ''.join(c for c in nfc if unicodedata.category(c) != 'Mn')
    
    # Chuyển thành chữ thường
    key = key.lower().strip()
    
    # Normalize khoảng trắng (multiple spaces → single space)
    key = ' '.join(key.split())
    
    return key
```

**Sử dụng:**
```python
# Khi lưu dữ liệu
unit_key = normalize_unit_key(user.unit_area)

# Khi render
unit_key = normalize_unit_key(cell_value)
```

---

### Phase 2: Latest Flag (PREVENT OLD DATA)

**File:** `models.py`

```python
class ReportData(db.Model):
    __tablename__ = 'report_data'
    
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report_config.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data_json = db.Column(db.Text)
    report_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    # NEW: Latest flag
    is_latest = db.Column(db.Boolean, default=True, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='report_data')
    config = db.relationship('ReportConfig', backref='data_entries')
```

**Migration:**
```bash
flask db migrate -m "Add is_latest flag to ReportData"
flask db upgrade
```

---

### Phase 3: Save Logic (UPSERT)

**File:** `routes/forms.py`

```python
@forms_bp.route('/form', methods=['POST'])
def submit_form():
    # ... validate data ...
    
    rid = request.form.get('report_id')
    user_id = session.get('uid')
    data_json = json.dumps(form_data)
    
    # 1. Mark old records as not latest
    old_records = ReportData.query.filter_by(
        report_id=rid,
        user_id=user_id,
        is_latest=True
    ).all()
    
    for old in old_records:
        old.is_latest = False
    
    # 2. Insert new record with is_latest=True
    new_record = ReportData(
        report_id=rid,
        user_id=user_id,
        data_json=data_json,
        report_date=datetime.utcnow(),
        is_latest=True
    )
    
    db.session.add(new_record)
    db.session.commit()
    
    # 3. Redirect với refresh flag
    return redirect(url_for('forms_bp.stats', rid=rid, refresh=1))
```

---

### Phase 4: Query Logic (LATEST ONLY)

**File:** `routes/forms.py`

```python
@forms_bp.route('/stats')
def stats():
    rid = request.args.get('rid')
    refresh = request.args.get('refresh') == '1'
    
    if refresh:
        # Clear cache
        db.session.expunge_all()
    
    # Query ONLY latest records
    raw = (db.session.query(ReportData, User)
           .join(User, ReportData.user_id == User.id)
           .filter(
               ReportData.report_id == rid,
               ReportData.is_latest == True  # ← ONLY LATEST
           )
           .order_by(User.unit_area)
           .all())
    
    # Build submissions
    submissions = []
    for entry, user in raw:
        try:
            data = json.loads(entry.data_json or '{}')
        except:
            data = {}
        
        unit = user.unit_area or user.fullname
        unit_key = normalize_unit_key(unit)  # ← NORMALIZE
        
        row = {
            'unit': unit,
            'unit_key': unit_key,  # ← ADD KEY
            'sender': user.fullname,
            'date': entry.report_date.strftime('%d/%m/%Y'),
            'values': {str(f['idx']): data.get(str(f['idx']), '') for f in fields}
        }
        submissions.append(row)
    
    # Render
    try:
        from excel_renderer import build_stats_table_html
        excel_html = build_stats_table_html(active.file_blob, active, submissions)
    except Exception as e:
        excel_html = f'<div class="alert alert-danger">Lỗi render: {e}</div>'
    
    # ... render template ...
```

---

### Phase 5: Render Logic (USE NORMALIZED KEY)

**File:** `excel_renderer.py`

```python
def build_stats_table_html(file_blob, config, submissions):
    # ... existing code ...
    
    # Build unit map with normalized keys
    unit_map = {}
    for sub in submissions:
        unit_key = sub.get('unit_key') or normalize_unit_key(sub.get('unit', ''))
        unit_map[unit_key] = sub
    
    unit_map_lower = {k.lower(): v for k, v in unit_map.items()}
    unit_names_lower = sorted(list(unit_map_lower.keys()), key=len, reverse=True)
    
    # ... render rows ...
    
    for r in range(render_start_row, max_row + 1):
        matched_sub = None
        
        # Try to match unit in this row
        for name in unit_names_lower:
            found_match = False
            for c_check in range(min_col, max_col + 1):
                cell_v = ws.cell(row=r, column=c_check).value
                if cell_v:
                    cell_key = normalize_unit_key(str(cell_v))
                    if cell_key == name:  # ← EXACT MATCH WITH NORMALIZED KEY
                        found_match = True
                        break
            
            if found_match:
                matched_sub = unit_map_lower[name]
                break
        
        # Render row
        for c in range(min_col, max_col + 1):
            # ... existing code ...
            
            val = cell_values.value
            if matched_sub and r > header_end:
                is_field = any(f['idx'] == c for f in fields)
                if is_field and 'values' in matched_sub:
                    val = matched_sub['values'].get(str(c), '')
            
            display = format_excel_number(val, cell.number_format)
            # ... render cell ...
```

---

## 📋 Implementation Checklist

### Step 1: Add normalize_unit_key()
- [ ] Thêm hàm vào `utils.py`
- [ ] Test hàm
- [ ] Import vào `routes/forms.py` và `excel_renderer.py`

### Step 2: Add is_latest column
- [ ] Thêm column vào `models.py`
- [ ] Tạo migration
- [ ] Run migration

### Step 3: Update save logic
- [ ] Cập nhật `routes/forms.py` POST handler
- [ ] Mark old records as not latest
- [ ] Insert new record with is_latest=True
- [ ] Redirect với refresh=1

### Step 4: Update query logic
- [ ] Cập nhật `routes/forms.py` GET handler
- [ ] Query ONLY is_latest=True
- [ ] Add unit_key to submissions
- [ ] Clear cache khi refresh=1

### Step 5: Update render logic
- [ ] Cập nhật `excel_renderer.py`
- [ ] Use normalized keys
- [ ] Exact match instead of fuzzy match

### Step 6: Test
- [ ] Unit test normalize_unit_key()
- [ ] Integration test: submit → stats
- [ ] Test with different unit name variations
- [ ] Test with multiple submissions

---

## 🧪 Test Cases

```python
# Test 1: Normalize unit key
assert normalize_unit_key("Phòng Kế Hoạch") == normalize_unit_key("phòng kế hoạch")
assert normalize_unit_key("Phòng Kế Hoạch") == "phong ke hoach"

# Test 2: Latest flag
# Submit twice → only latest should be rendered
submit_form(unit="A", data={"1": "100"})
submit_form(unit="A", data={"1": "200"})
# Stats should show 200, not 100

# Test 3: Unit matching
# Excel has "Phòng Kế Hoạch"
# Submission has "phòng kế hoạch"
# Should match and render data

# Test 4: Refresh
# Submit → redirect /stats?refresh=1
# Should query latest from DB, not cache
```

---

## 📊 Before & After

### Before ❌
```
Submit: "Phòng Kế Hoạch" → Save
Stats: Excel has "phòng kế hoạch" → No match → No data
```

### After ✅
```
Submit: "Phòng Kế Hoạch" → Normalize → "phong ke hoach" → Save with is_latest=True
Stats: Excel has "phòng kế hoạch" → Normalize → "phong ke hoach" → Match → Show data
```

---

## ⏱️ Estimated Time

- Phase 1 (normalize): 30 min
- Phase 2 (is_latest): 30 min
- Phase 3 (save logic): 30 min
- Phase 4 (query logic): 30 min
- Phase 5 (render logic): 30 min
- Phase 6 (test): 1 hour

**Total: ~3.5 hours**

---

## 🚀 Deployment

```bash
# 1. Backup DB
mysqldump -u user -p db > backup.sql

# 2. Deploy code
git add models.py routes/forms.py utils.py excel_renderer.py
git commit -m "Fix: V1 data - normalize unit key, add latest flag"
git push

# 3. Run migration
flask db upgrade

# 4. Test
python3 test_v1_data_flow.py

# 5. Monitor
# Check V1 stats after submissions
```

---

**Status:** READY TO IMPLEMENT

Tất cả phase đều rõ ràng, có thể bắt đầu ngay.
