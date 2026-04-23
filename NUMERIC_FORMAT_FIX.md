# Fix Lỗi Định Dạng Số - Numeric Formatting Fix

## Vấn đề
Trước đây, hàm `_fmt_val` đang format chung cho mọi số mà **bỏ qua `number_format` của từng ô Excel**. Điều này dẫn đến:
- Số nguyên hiển thị sai (ví dụ: 491 → 491,14)
- Mất đi định dạng gốc của ô (phần trăm, hàng nghìn, số thập phân)
- Không khớp với file Excel gốc

## Giải pháp
Tạo hàm `format_excel_number(value, number_format)` để:
1. **Đọc `number_format` từ ô Excel** thay vì format chung
2. **Xử lý các format phổ biến**:
   - `0` → số nguyên (làm tròn)
   - `0.0`, `0.00` → số thập phân (1-2 chữ số)
   - `#,##0`, `#,##0.00` → có phân tách hàng nghìn
   - `0%`, `0.0%`, `0.00%` → phần trăm
3. **Fallback an toàn** nếu format không nhận dạng được

## Thay đổi trong `excel_renderer.py`

### 1. Hàm mới: `format_excel_number(value, number_format)`
- Thay thế logic format chung của `_fmt_val`
- Ưu tiên format gốc của ô Excel
- Xử lý 8 format phổ biến nhất

### 2. Cập nhật các lệnh gọi
Thay `_fmt_val(val)` bằng `format_excel_number(val, cell.number_format)` ở 3 vị trí:

| Hàm | Dòng | Thay đổi |
|-----|------|---------|
| `render_range_to_html` | 287 | `_fmt_val(raw_val)` → `format_excel_number(raw_val, cell.number_format)` |
| `build_stats_table_html` | 378 | `_fmt_val(val)` → `format_excel_number(val, cell.number_format)` |
| `build_v2_stats_table_html` | 445 | `_fmt_val(val)` → `format_excel_number(val, cell.number_format)` |

### 3. Backward compatibility
- `_fmt_val(val)` vẫn tồn tại, gọi `format_excel_number(val, None)`
- Không break code cũ

## Test Results
✓ Tất cả 16 test case pass:
- Integer format: `491` → `491` ✓
- Float to integer: `491.14` → `491` ✓
- Two decimals: `491.14` → `491.14` ✓
- Percentage: `0.5` → `50%` ✓
- Thousand separator: `1234.56` → `1,234.56` ✓
- Và 11 test case khác

## Cách kiểm thử
```bash
python3 test_format_fix.py
```

## Ưu điểm
1. ✓ Hiển thị khớp với file Excel gốc
2. ✓ Xử lý đúng các format phổ biến
3. ✓ Fallback an toàn cho format không nhận dạng
4. ✓ Không break code cũ (backward compatible)
5. ✓ Dễ mở rộng cho format mới

## Lưu ý
- Hàm chỉ xử lý **8 format phổ biến nhất**
- Nếu gặp format đặc thù, có thể mở rộng trong `format_excel_number`
- Locale hiện tại: sử dụng dấu `.` cho thập phân (có thể mở rộng cho `,` nếu cần)
