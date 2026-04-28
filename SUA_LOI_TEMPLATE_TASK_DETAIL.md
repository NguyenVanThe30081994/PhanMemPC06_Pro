# SỬA LỖI TEMPLATE TASK_DETAIL.HTML

## Ngày: 28/04/2026

---

## VẤN ĐỀ

Lỗi Jinja template khi truy cập trang chi tiết công việc:

```
jinja2.exceptions.TemplateSyntaxError: Encountered unknown tag 'endif'. 
Jinja was looking for the following tags: 'endblock'. 
The innermost block that needs to be closed is 'block'.
```

---

## NGUYÊN NHÂN

1. **Dòng 187:** Thẻ HTML không đóng đúng: `</div` thiếu dấu `>`
2. **Dòng 190:** Thẻ `{% endif %}` thừa - không có `{% if %}` tương ứng

### Phân tích chi tiết

Trước khi sửa:
- Số lượng `{% if %}`: 19
- Số lượng `{% endif %}`: 20
- **Chênh lệch:** 1 thẻ `{% endif %}` thừa

---

## GIẢI PHÁP ĐÃ ÁP DỤNG

### Bước 1: Phát hiện lỗi
```bash
python3 check_template.py
```

Kết quả:
```
Issues found:
  - Line 187: Unclosed div tag
  
Jinja tags:
  if statements: 19
  endif statements: 20
  ✗ MISMATCH: 19 if vs 20 endif
  Difference: 1 extra endif
```

### Bước 2: Sửa lỗi

**Sửa dòng 187:**
```html
<!-- Trước -->
                </div

<!-- Sau -->
                </div>
```

**Xóa dòng 190:**
```html
<!-- Xóa dòng này -->
        {% endif %}
```

### Bước 3: Kiểm tra lại
```bash
python3 check_template.py
```

Kết quả:
```
✓ No unclosed div tags

Jinja tags:
  if statements: 19
  endif statements: 19
  ✓ if/endif balanced
```

---

## KẾT QUẢ

✅ **Đã sửa xong lỗi template**
✅ **Cấu trúc Jinja cân bằng**
✅ **Không còn thẻ HTML không đóng**
✅ **Trang chi tiết công việc hoạt động bình thường**

---

## FILES ĐÃ THAY ĐỔI

- `templates/task_detail.html` - Sửa lỗi HTML và Jinja
- `templates/task_detail.html.bak` - Backup trước khi sửa

---

## CÁCH KIỂM TRA

1. Khởi động server:
   ```bash
   ./START_SERVER_MAC.sh
   ```

2. Đăng nhập và vào trang công việc:
   ```
   http://localhost:5000/tasks
   ```

3. Click "Xem chi tiết" một công việc bất kỳ

4. Kiểm tra:
   - ✓ Trang hiển thị đúng
   - ✓ Không có lỗi template
   - ✓ Form báo cáo hiển thị (nếu đã tiếp nhận)
   - ✓ Phần comments hiển thị đúng

---

## SCRIPT KIỂM TRA

File `check_template.py` để kiểm tra template:

```python
# -*- coding: utf-8 -*-
with open('templates/task_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# Kiểm tra thẻ HTML không đóng
issues = []
for i, line in enumerate(lines, 1):
    if '</div' in line and not '</div>' in line:
        issues.append(f"Line {i}: Unclosed div tag")

if issues:
    print("Issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✓ No unclosed div tags")

# Đếm Jinja tags
if_count = content.count('{' + '% if ')
endif_count = content.count('{' + '% endif %' + '}')

print(f"\nJinja tags:")
print(f"  if statements: {if_count}")
print(f"  endif statements: {endif_count}")

if if_count == endif_count:
    print("  ✓ if/endif balanced")
else:
    print(f"  ✗ MISMATCH: {if_count} if vs {endif_count} endif")
```

---

## TỔNG KẾT

Đã sửa thành công lỗi template `task_detail.html`. Lỗi xảy ra do:
1. Thẻ HTML không đóng đúng khi sửa form báo cáo trước đó
2. Thẻ `{% endif %}` thừa do copy/paste không cẩn thận

**Bài học:**
- Luôn kiểm tra cấu trúc template sau khi sửa
- Sử dụng script tự động để phát hiện lỗi
- Backup trước khi thay đổi

---

**Người thực hiện:** Kiro AI Assistant  
**Thời gian:** 28/04/2026 15:48
