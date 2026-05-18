# CHANGELOG / TIMELINE

## 2026-05-18
- Chuẩn hóa helper quyền dùng chung `view / process / exec` cho app context, route và điều hướng desktop/mobile.
- Dọn các màn chính khỏi check quyền legacy rải rác ở `base`, `base_mobile`, `contacts`, `library`, `news_mobile`.
- Hoàn thiện mobile task detail: sửa lỗi tiếng Việt vỡ mã, khôi phục logic trạng thái, bổ sung theo dõi task con.
- Bổ sung lớp dữ liệu đích `task_item` và bridge đồng bộ từ `task con` hiện có.
- Nâng `migrate.py` thành lệnh migration/backfill chính thức cho runtime task (`task_item`, `task_participant`, `task_submission`, `task_report_link`) với `dry-run`.
- Bổ sung test hồi quy cho normalize quyền và task runtime backfill tại `tests/test_proposal_runtime.py`.

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
