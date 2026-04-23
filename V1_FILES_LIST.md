# 📋 V1 Stats - Files Liên Quan

## 🎯 Main Route File
- **routes/forms.py** - Route chính cho V1 stats
  - `@forms_bp.route('/stats')` - Hiển thị báo cáo thống kê
  - `@forms_bp.route('/stats/export')` - Export báo cáo
  - Gọi `build_stats_table_html()` từ `excel_renderer.py`

## 🔧 Core Implementation Files

### 1. excel_renderer.py
- `build_stats_table_html(file_blob, config, submissions)` - Render V1 stats table
- `format_excel_number(value, number_format)` - Format số (NEW)
- `_fmt_val(val)` - Format value (deprecated)
- `render_range_to_html()` - Render range to HTML
- `_build_merge_lookup()` - Build merge cell lookup
- `_cell_css()` - Get cell CSS

### 2. models.py
- `ReportConfig` - Cấu hình báo cáo
  - `header_start` - Dòng bắt đầu header
  - `header_rows` - Số dòng header
  - `config_json` - JSON config (fields)
- `Submission` - Dữ liệu đơn vị
  - `unit` - Tên đơn vị
  - `values` - Dict giá trị {column: value}

### 3. pc06_excel_engine.py
- `ExcelEngineV2._detect_active_regions()` - Phát hiện vùng render
- `ExcelEngineV2._get_true_max_row_col()` - Lấy max row/col

### 4. utils.py
- `is_unit_match()` - Kiểm tra khớp tên đơn vị
- Unit name normalization

## 📊 Data Flow

```
routes/forms.py (/stats)
    ↓
GET active report config
    ↓
GET submissions (dữ liệu đơn vị)
    ↓
build_stats_table_html(file_blob, config, submissions)
    ↓
excel_renderer.py
    ├─ Load Excel file (2 workbooks)
    ├─ Detect active regions
    ├─ Render header rows
    ├─ Match submissions to units
    ├─ Render data rows with format_excel_number()
    └─ Return HTML table
    ↓
Render template with HTML
```

## 🔍 Key Functions

### routes/forms.py
```python
@forms_bp.route('/stats')
def stats():
    # 1. Get active report
    # 2. Get submissions
    # 3. Call build_stats_table_html()
    # 4. Render template
```

### excel_renderer.py
```python
def build_stats_table_html(file_blob, config, submissions):
    # 1. Load workbook (2 lần)
    # 2. Detect regions
    # 3. Render headers
    # 4. Match & render data rows
    # 5. Return HTML
```

## 📁 File Structure

```
PhanMemPC06_Pro/
├── routes/
│   ├── forms.py ⭐ (V1 stats route)
│   ├── api.py
│   ├── tasks.py
│   └── admin.py
├── excel_renderer.py ⭐ (V1 render engine)
├── models.py ⭐ (ReportConfig, Submission)
├── pc06_excel_engine.py ⭐ (Region detection)
├── utils.py ⭐ (Unit matching)
└── templates/
    └── stats.html (V1 stats template)
```

## 🐛 Vấn đề hiện tại

**V1 không xuất ra báo cáo thống kê có dữ liệu được cập nhật của các đơn vị**

Nguyên nhân có thể:
1. Submissions không được lấy đúng
2. Unit matching không hoạt động
3. Data rows không được render
4. Format_excel_number() có lỗi
5. Template không hiển thị đúng

## 🔧 Cần kiểm tra

1. [ ] routes/forms.py - Lấy submissions đúng không?
2. [ ] utils.py - is_unit_match() hoạt động không?
3. [ ] excel_renderer.py - build_stats_table_html() render data rows không?
4. [ ] models.py - Submission.values có dữ liệu không?
5. [ ] templates/stats.html - Hiển thị HTML đúng không?

