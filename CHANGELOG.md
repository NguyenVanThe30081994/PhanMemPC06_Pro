# CHANGELOG / TIMELINE

## 2026-08-04 (wizard tạo công việc 4 bước)
- Chuyển hộp thoại "Tạo công việc" từ dạng liệt kê nhiều ô cấu hình sang wizard 4 bước: `1. Loại công việc -> 2. Tải nguồn -> 3. Cấu hình -> 4. Phát hành`.
- Mỗi loại công việc có giao diện riêng:
  - **Theo đề cương**: tải file `.docx/.txt`, hệ thống phân tích ngay trong lúc tạo (`POST /tasks/outline-parse`) thành danh sách việc nhỏ; quản trị gán từng việc (nút Gán) hoặc gán hàng loạt, rồi tạo cả công việc + đầu mục + người nhận trong một lần.
  - **Biểu mẫu / bảng số**: 3 nguồn — tự dựng / tải Excel mẫu, **lấy từ biểu mẫu báo cáo có sẵn** (endpoint `POST /tasks/form-template-preview` đọc các trường của ReportTemplate để nạp sang builder kiểm tra chỉnh sửa), hoặc Google Form thật (khai báo câu hỏi theo nguyên lý Google Form, gắn link + trường đối sánh).
  - **Nộp file / văn bản**: giao trực tiếp, kèm file mẫu, chọn đối tượng nhận.
- Bước 4 gom thông tin chung (tiêu đề, lĩnh vực, đội nghiệp vụ, hạn, mô tả) + phạm vi xem/quản lý + tóm tắt trước khi "Xuất việc".
- Test: `tests/test_task_create_wizard.py` (phân tích đề cương, nạp trường từ biểu mẫu báo cáo, tạo công việc đề cương kèm đầu mục + gán trong 1 POST).

## 2026-08-04 (gán việc theo dòng cho quản trị)
- Màn hình "Bước 2" sau khi nạp đề cương giờ là danh sách việc nhỏ; mỗi dòng có nút **Gán** để quản trị gán việc đó cho đơn vị / vai trò / cá nhân ngay trên dòng (mở hộp thoại chọn người nhận).
- Giữ nguyên gán hàng loạt (tích nhiều dòng → chọn người nhận → "Gán cho dòng tích"); kết quả phân tích tự động chỉ là gợi ý và luôn có thể sửa hoặc gán lại — quyết định giao việc hoàn toàn do quản trị trước khi bấm Tạo.
- Làm rõ hướng dẫn trên màn hình và kiểm tra JS render (node --check) đạt.

## 2026-08-04 (giao việc theo đề cương: tự nhận diện người nhận)
- Bổ sung phân tích đề cương: khi tải file `.docx` / `.txt`, hệ thống đọc và nhận diện "giao cho ai" ngay trong đề cương.
- Hỗ trợ nhiều cách ghi người nhận: `Đơn vị thực hiện: X`, `Giao cho: X`, `Cán bộ phụ trách: X`, đuôi tiêu đề `— Đội A`, `(Đơn vị)` và cột "Đơn vị thực hiện" trong bảng Word.
- Đối sánh tự động với danh mục đơn vị (contacts/professional unit), vai trò (AppRole) và cán bộ (User đang hoạt động); điền sẵn `đơn vị / vai trò / cá nhân` vào từng dòng của màn hình gán việc trước khi tạo.
- Nhận diện nhiều người nhận trong cùng một đầu mục (ví dụ "Đơn vị thực hiện: Công an huyện X, Đội B").
- Nới lỏng nhận diện đầu mục cho các dòng đánh số/bullet ngắn (trước đây bị lọc nhầm thành tiêu đề cấu trúc); vẫn lọc tiêu đề La Mã (I., II., ...).
- Test: `tests/test_task_outline_word_export.py` có thêm `test_outline_import_preview_auto_detects_assignee` (tải đề cương .docx -> preview gán sẵn người nhận).

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
