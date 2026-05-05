# CHANGELOG / TIMELINE

## 2026-05-05
- Chuẩn hóa `unit_key` toàn hệ thống cho tài khoản, đăng nhập, giao việc, chấm điểm và báo cáo.
- Báo cáo/view/export dùng lại key đơn vị thống nhất.
- Xuất báo cáo có fallback tự dựng giá trị công thức khi host chưa có LibreOffice.

## 2026-04-28
### Core fixes
- Sửa chức năng công việc: giao theo đơn vị, nút tiếp nhận, form báo cáo.
- Sửa lỗi template Jinja.
- Sửa endpoints và hotfix import.

### Reporting
- Bổ sung báo cáo trực tiếp trên phần mềm.
- Sửa mapping đơn vị trong xem/xuất báo cáo.
- Gắn dữ liệu báo cáo vào file xử lý thay vì chỉ giữ file gốc.

### UI
- Áp dụng cải tiến giao diện theo hướng BDHVS.
- Chuẩn hóa layout, glass effect, shadow và responsive.

### Security / Performance
- V9 security hardening, password policy, CSRF, session flags, input validation.
- Tối ưu index và log bảo mật.

## Archive
File này thay thế các tài liệu markdown rời trước đây, để giữ lịch sử theo một timeline duy nhất.
