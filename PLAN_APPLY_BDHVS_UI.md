# KẾ HOẠCH ÁP DỤNG GIAO DIỆN BDHVS CHO PC06

## Phân tích so sánh

### BDHVS (Nguồn)
- CSS chính: style.css (54KB)
- CSS bổ sung: ai-assistant.css, citizen-assistant.css, digital-services.css, portal-dashboard.css
- Base template: base.html với liquid glass design
- Theme system: Light/Dark mode hoàn chỉnh
- Responsive: Mobile bottom nav + Desktop top nav

### PC06 (Đích)
- CSS chính: style.css (54KB) - tương tự BDHVS
- CSS bổ sung: ai-assistant.css, category-picker.css, reporting-modern.css
- Base template: base.html cần cập nhật
- Theme system: Có nhưng chưa hoàn chỉnh

## Các bước thực hiện

### Bước 1: Backup files hiện tại ✓
- Backup static/css/
- Backup templates/base.html

### Bước 2: Copy CSS từ BDHVS
- Copy style.css (ghi đè)
- Copy các CSS bổ sung cần thiết
- Giữ lại category-picker.css và reporting-modern.css của PC06

### Bước 3: Cập nhật base.html
- Copy cấu trúc header từ BDHVS
- Copy navigation system
- Copy mobile bottom nav
- Giữ lại các menu items của PC06

### Bước 4: Cập nhật các template chính
- dashboard.html
- tasks.html
- contacts.html
- roles.html
- Các template khác

### Bước 5: Test và điều chỉnh
- Test responsive
- Test dark mode
- Test các chức năng
- Fix lỗi nếu có

## Ưu tiên

1. **Cao:** style.css, base.html
2. **Trung bình:** dashboard.html, tasks.html
3. **Thấp:** Các template phụ

## Lưu ý

- Giữ nguyên logic backend
- Chỉ thay đổi giao diện frontend
- Đảm bảo tương thích với các chức năng hiện có
- Test kỹ trước khi deploy
