# 📋 V1 Data Fix - Summary & Next Steps

## 🎯 Vấn đề Chính

V1 stats không hiển thị dữ liệu mới vì **dữ liệu không được lưu/lấy/render đúng**.

### Root Causes:
1. ❌ **Unit key không chuẩn hóa** - "Phòng Kế Hoạch" vs "phòng kế hoạch" không match
2. ❌ **Không có "latest" flag** - Khi submit 2 lần, không biết lấy cái nào
3. ❌ **Map đơn vị → dòng không cố định** - Dựa vào thứ tự query không ổn định
4. ❌ **Không refresh sau lưu** - Dữ liệu cũ vẫn được cache

---

## ✅ Giải Pháp

### Phase 1: Chuẩn Hóa Unit Key (QUICK WIN)
```python
def normalize_unit_key(unit_name):
    """Loại bỏ dấu, chuyển thành chữ thường, normalize spaces"""
    # "Phòng Kế Hoạch" → "phong ke hoach"
    # "phòng kế hoạch" → "phong ke hoach"
    # "PK" → "pk"
```

**Impact:** Giải quyết 80% vấn đề matching

### Phase 2: Latest Flag
```python
# Thêm column: is_latest = True/False
# Khi submit: Mark old as False, insert new as True
# Khi query: WHERE is_latest = True
```

**Impact:** Đảm bảo lấy dữ liệu mới nhất

### Phase 3: Save Logic (UPSERT)
```python
# Mark old records as not latest
# Insert new record with is_latest=True
# Redirect với refresh=1
```

**Impact:** Buộc refresh dữ liệu

### Phase 4: Query Logic
```python
# Query ONLY is_latest=True
# Add unit_key to submissions
# Clear cache khi refresh=1
```

**Impact:** Lấy đúng dữ liệu

### Phase 5: Render Logic
```python
# Use normalized keys
# Exact match instead of fuzzy match
```

**Impact:** Render đúng dòng

---

## 📊 Data Flow (After Fix)

```
POST /form (submit data)
    ↓
Mark old records as is_latest=False
    ↓
Insert new record with is_latest=True
    ↓
Redirect /stats?rid=X&refresh=1
    ↓
Clear cache
    ↓
Query ReportData WHERE is_latest=True
    ↓
Normalize unit keys
    ↓
Build submissions with unit_key
    ↓
Match unit_key → Excel row (EXACT MATCH)
    ↓
Render HTML with new data ✅
```

---

## 📁 Files Cần Sửa

| File | Change | Priority |
|------|--------|----------|
| `utils.py` | Add `normalize_unit_key()` | HIGH |
| `models.py` | Add `is_latest` column | HIGH |
| `routes/forms.py` | Update save/query logic | HIGH |
| `excel_renderer.py` | Use normalized keys | HIGH |
| Migration | Add `is_latest` column | HIGH |

---

## 🧪 Test Cases

```python
# Test 1: Normalize
assert normalize_unit_key("Phòng Kế Hoạch") == normalize_unit_key("phòng kế hoạch")

# Test 2: Latest flag
submit(unit="A", data={"1": "100"})
submit(unit="A", data={"1": "200"})
# Stats should show 200

# Test 3: Unit matching
# Excel: "Phòng Kế Hoạch"
# Submit: "phòng kế hoạch"
# Should match and render

# Test 4: Refresh
# Submit → redirect /stats?refresh=1
# Should query latest from DB
```

---

## ⏱️ Estimated Time

| Phase | Time |
|-------|------|
| Phase 1: normalize_unit_key() | 30 min |
| Phase 2: is_latest column | 30 min |
| Phase 3: Save logic | 30 min |
| Phase 4: Query logic | 30 min |
| Phase 5: Render logic | 30 min |
| Phase 6: Test | 1 hour |
| **Total** | **~3.5 hours** |

---

## 📝 Implementation Order

1. **Add normalize_unit_key() to utils.py** ← START HERE
2. **Add is_latest column to models.py**
3. **Create migration**
4. **Update save logic in routes/forms.py**
5. **Update query logic in routes/forms.py**
6. **Update render logic in excel_renderer.py**
7. **Test**
8. **Deploy**

---

## 🚀 Quick Start

```bash
# 1. Read the plan
cat V1_DATA_FIX_PLAN.md

# 2. Implement Phase 1 (normalize_unit_key)
# Edit utils.py

# 3. Test Phase 1
python3 -c "from utils import normalize_unit_key; print(normalize_unit_key('Phòng Kế Hoạch'))"

# 4. Continue with other phases...
```

---

## 📚 Documentation Files

- `V1_DATA_FLOW_ANALYSIS.md` - Root cause analysis
- `V1_DATA_FIX_PLAN.md` - Detailed implementation plan
- `V1_DATA_FIX_SUMMARY.md` - This file

---

## ✨ Expected Results

### Before ❌
```
Submit: "Phòng Kế Hoạch" → Save
Stats: No data (unit not matched)
```

### After ✅
```
Submit: "Phòng Kế Hoạch" → Normalize → Save with is_latest=True
Stats: Data rendered correctly (unit matched, latest data)
```

---

## 🎯 Success Criteria

- ✅ Unit names with different variations match correctly
- ✅ Latest submission is always displayed
- ✅ Data refreshes immediately after submission
- ✅ No cache issues
- ✅ All tests pass

---

**Status:** READY TO IMPLEMENT

Tất cả phase đều rõ ràng, có thể bắt đầu ngay.

**Next:** Implement Phase 1 (normalize_unit_key)
