# 🐛 V1 Stats Bug Analysis

## Vấn đề
V1 không xuất ra báo cáo thống kê có dữ liệu được cập nhật của các đơn vị.

## Root Cause

### 1. routes/forms.py (dòng 392-404)
Tạo `submissions` với structure:
```python
row = {
    'unit': unit,
    'sender': user.fullname,
    'date': entry.report_date.strftime('%d/%m/%Y'),
    'values': {str(f['idx']): data.get(str(f['idx']), '') for f in fields}
}
submissions.append(row)
```

✅ Có `values` key

### 2. excel_renderer.py (dòng 315-317)
```python
if matched_sub and r > header_end:
    is_field = any(f['idx'] == c for f in fields)
    if is_field: val = matched_sub['values'].get(str(c), '')
```

❌ Cố gắng lấy `matched_sub['values']` nhưng:
- Không kiểm tra `matched_sub` có `values` key không
- Nếu `values` không tồn tại → KeyError
- Data rows không được render

## Data Flow

```
routes/forms.py
    ↓
Query ReportData từ DB
    ↓
Tạo submissions với values
    ↓
Gọi build_stats_table_html(active.file_blob, active, submissions)
    ↓
excel_renderer.py
    ├─ Render header rows ✅
    ├─ Match submissions to units ✅
    ├─ Cố gắng lấy matched_sub['values'] ❌ ERROR
    └─ Data rows không render
```

## Giải pháp

### Option 1: Thêm defensive check trong excel_renderer.py
```python
if matched_sub and r > header_end:
    is_field = any(f['idx'] == c for f in fields)
    if is_field and 'values' in matched_sub:  # ← Thêm check
        val = matched_sub['values'].get(str(c), '')
```

### Option 2: Đảm bảo submissions luôn có values
```python
# routes/forms.py
row = {
    'unit': unit,
    'sender': user.fullname,
    'date': entry.report_date.strftime('%d/%m/%Y'),
    'values': {str(f['idx']): data.get(str(f['idx']), '') for f in fields}
}
```

## Cần kiểm tra

1. [ ] Submissions có `values` key không?
2. [ ] excel_renderer.py có handle KeyError không?
3. [ ] Data rows có được render không?
4. [ ] Có error log nào không?

## Files cần sửa

1. **excel_renderer.py** (dòng 315-317)
   - Thêm defensive check cho `matched_sub['values']`

2. **routes/forms.py** (dòng 392-404)
   - Đảm bảo `values` luôn được tạo đúng

## Test

```python
# Kiểm tra submissions structure
submissions = [
    {
        'unit': 'Đơn vị A',
        'sender': 'Người A',
        'date': '23/04/2026',
        'values': {'1': '491', '2': '543'}  # ← Phải có values
    }
]
```
