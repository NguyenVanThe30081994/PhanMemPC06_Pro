# CHANGELOG / TIMELINE

## 2026-08-04 (fix khởi động trên Python 3.14)
- Sửa lỗi `pip install -r requirements.txt` thất bại trên Python 3.14: `pandas==2.1.1` không build được (numpy yêu cầu Cython 3.0+ nhưng pandas 2.1.1 build bằng Cython cũ), kéo theo server không khởi động (`No module named 'flask'`).
- Nới pin `pandas>=2.2.3` và `numpy>=1.26,<3` để pip chọn bản có wheel sẵn cho Python 3.14 (pandas 3.0.x / numpy 2.x); nới `Pillow>=12.2` cho Python >= 3.10 để có wheel cp314.
- Toàn bộ phần còn lại của requirements giữ nguyên; kiểm tra parse 22 dòng không lỗi cú pháp.

## 2026-08-04
### Giao việc - Báo cáo hợp nhất
- Hoàn thiện chức năng giao việc duy nhất theo 3 hình thái thu thập: biểu mẫu (Google Form), bảng số liệu (Excel), báo cáo văn bản theo đề cương (Word).
- Bổ sung ma trận tiến độ `đầu mục x đơn vị` cho công việc dạng đề cương (OUTLINE) tại tab `Tiến độ chung`.
- Bổ sung xuất `bao_cao_tong_hop_<tên>_<id>.docx`: gộp nội dung các đơn vị đã nộp theo đúng thứ tự đề cương (endpoint `GET /tasks/<id>/export-outline.docx`).
- Bổ sung `Trả lại bổ sung`: trả assignment về trạng thái `returned`, ghi lý do vào nhật ký `[TRẢ LẠI]`, người nhận nộp lại được (endpoint `POST /tasks/<id>/assignments/<aid>/return`).
- Nâng trường `table` của biểu mẫu thành lưới nhập giống bảng tính: thêm/xóa dòng, giữ định dạng payload cũ tương thích.
- Thêm test hồi quy `tests/test_task_outline_word_export.py` cho ma trận, xuất Word và trả lại bổ sung.
- Tài liệu: `docs/nghien-cuu-phan-mem-giao-viec-2026.md` (nghiên cứu phần mềm giao việc), `docs/thiet-ke-chuc-nang-giao-viec-hop-nhat-2026.md` (thiết kế hợp nhất + phân tích lỗ hổng).

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
