# PC06 Software Error Log
# Bình dân học vụ số - Lỗi & Khắc phục

---

## Ngày: 2026-04-15

### Lỗi 1: Sidebar đè lên content (Layout Overlap)

**Mô tả**: Khi cuộn trang, sidebar đè lên main content
**Nguyên nhân**: Flexbox layout không đúng
**Giải pháp**: Dùng Bootstrap grid (`col-lg-2` + `col-lg-10`)
**File sửa**: `templates/bdhv_base.html`

---

### Lỗi 2: Sidebar không ngang hàng với content

**Mô tả**: Sidebar nằm trên, content nằm dưới
**Nguyên nhân**: Thiếu `align-items-stretch` trong flex container
**Giải pháp**: Thêm wrapper div với Bootstrap grid
**File sửa**: `templates/bdhv_base.html`

---

### Lỗi 3: Thiếu template bdhv_xep_hang.html

**Mô tả**: Lỗi 500 khi truy cập `/bdhv/xep-hang`
**Nguyên nhân**: Template file không tồn tại
**Giải pháp**: Tạo file mới `templates/bdhv_xep_hang.html`
**File tạo**: `templates/bdhv_xep_hang.html`

---

### Lỗi 4: CSS không load được

**Mô tả**: Custom CSS từ bdhv_base.html không áp dụng
**Nguyên nhân**: base.html thiếu `{% block extra_head %}`
**Giải pháp**: Thêm block vào base.html
**File sửa**: `templates/base.html` (thêm dòng 393-394)

---

### Lỗi 5: Export Excel - Internal Error (500)

**URL**: 
- `/bdhv/export/danh-sach`
- `/bdhv/export/thong-ke`

**Mô tả**: Lỗi "Internal Error" hoặc "Connection reset by peer"

**Nguyên nhân**:
1. Server LiteSpeed/OpenLiteSpeed crash
2. Process bị kill trước khi gửi response
3. Memory limit exceeded
4. Timeout khi tạo Excel

**Giải pháp đã thử**:
1. Thêm try-catch error handling vào routes
2. Test local - hoạt động bình thường (200 OK)

**Log lỗi server**:
```
2026-04-15 21:04:11.027015 [INFO] [522086] [T0] [113.181.240.145:62972-4#APVH_www.pc06tuyenquang.net] 
connection to [uds://...] on request #4, confirmed, 0, associated process: 603661, 
running: 1, error: Connection reset by peer!
```

**Trạng thái**: ⚠️ Chưa giải quyết được - cần kiểm tra server resources

---

### Lỗi 6: Mobile interface chưa có

**Mô tả**: Không có mobile template riêng cho BDHV
**Nguyên nhân**: Thiếu files `bdhv_*_mobile.html`
**Giải pháp**: Tạo `bdhv_base_mobile.html` với responsive design
**File tạo**: `templates/bdhv_base_mobile.html`

---

## Tổng kết

| Lỗi | Trạng thái |
|-----|-----------|
| Sidebar layout | ✅ Đã sửa |
| Thiếu template xep_hang | ✅ Đã tạo |
| CSS không load | ✅ Đã sửa |
| Export Excel | ⚠️ Chưa xử lý được |
| Mobile template | ✅ Đã tạo |

---

## Cần theo dõi

1. **Export Excel**: Kiểm tra memory/timeout trên server LiteSpeed
2. **Server logs**: Xem chi tiết lỗi trong error logs của LiteSpeed
3. **Process monitoring**: Kiểm tra RAM/CPU khi gọi export
