# CHANGELOG / TIMELINE

## 2026-08-16 (Pha 2 — Tách routes/tasks.py theo miền, đợt 7 + 8)
Tách cụm helper màn làm việc + cụm quyền; routes/tasks.py giảm 4.628 → **4.152 dòng** (cộng dồn Pha 2: 11.213 → 4.152), 196 test OK:
- `services/task_workspace_helpers.py` (~435 dòng): thẻ tiến độ theo đơn vị (`_build_assignment_unit_cards`), nhóm theo vai trò (`_build_assignment_role_groups`), nhóm tiến độ assignment, nhóm hợp đồng giao việc theo chế độ nộp (`_task_delivery_contract_groups`), lọc theo phạm vi người xử lý, lưu tệp đính kèm, khóa nhóm nộp + đồng bộ submission trong nhóm, truy vấn assignment/đầu mục, trạng thái nộp — 20 helper (band L689-1096 cũ).
- `_task_assignee_unit_name` chuyển sang `services/task_units.py` (wrapper của `_task_unit_identity`).
- Gỡ mã chết: def `_latest_assignment_submission` trong routes/tasks.py (bản hiệu lực re-export từ `services/task_runtime_sync.py`), 9 helper band không còn nơi gọi ngoài band (`_build_assignment_unit_cards`, `_build_assignment_role_groups`, `_task_file_delivery_labels_for_user`, `_task_form_delivery_labels_for_user`, `_task_assignment_submission_group_key`, `_task_assignment_group_members`, `_task_file_root`, `_task_deadline_display`, `_task_workspace_tone`, `_task_detail_context`...).
- `services/task_guards.py` (~119 dòng): cụm quyền — `_load_task_parent`, `_can_manage_task`, `_can_edit_task`, `_can_delete_task`, `_can_watch_task`, `_can_view_task`, `_filter_comments_for_viewer` (uốn về `task_policies` với ngữ cảnh session).
- routes/tasks.py re-export các tên còn dùng; hợp đồng `migrate.py` và import của test không đổi; không test nào patch các hàm đã chuyển.

## 2026-08-16 (Pha 2 — Tách routes/tasks.py theo miền, đợt 6)
Tách cụm nháp nhập việc (band lớn nhất còn lại); routes/tasks.py giảm 6.347 → **4.628 dòng** (cộng dồn Pha 2: 11.213 → 4.628), 196 test OK:
- `services/task_import_drafts.py` (~1.780 dòng): dựng cấu hình làm việc từ blueprint, phân tích form nháp (đề cương / biểu mẫu / trường báo cáo), xem trước người nhận theo đơn vị/vai trò, kiểm tra hiển thị trước phát hành và phát hành nháp thành công việc thật (kèm assignment, phạm vi, thông báo, email). Gồm 4 hằng số nhãn `TASK_IMPORT_*_LABELS` + 36 helper (`_task_import_working_config_from_blueprint`, `_publish_task_import_draft`, `_task_import_draft_blueprint`, ...).
- `_create_assignment_records` chuyển sang `services/task_assignees.py` (điểm phụ thuộc chung: dùng cả trong band nháp lẫn ngoài band).
- Gỡ mã chết `_sync_task_assignments` (không còn nơi gọi sau khi chuyển band).
- routes/tasks.py re-export toàn bộ 15 tên cũ + `_create_assignment_records`; hợp đồng `migrate.py` và import của test không đổi.

## 2026-08-16 (Pha 2 — Tách routes/tasks.py theo miền, đợt 5)
Tách cụm helper màn xem báo cáo; routes/tasks.py giảm 7.179 → **6.347 dòng** (cộng dồn Pha 2: 11.213 → 6.347), 196 test OK:
- `services/task_report_views.py` (~400 dòng): hằng số điều kiện tiến độ/chất lượng task con (`CHILD_TASK_PROGRESS_CONDITIONS`/`CHILD_TASK_QUALITY_CONDITIONS`), dashboard báo cáo task con theo đơn vị (`_build_child_task_report_dashboard`), định dạng/xem trước/tóm tắt giá trị báo cáo (`_format_report_number`, `_task_report_value_preview`, `_structured_task_report_summary_lines`), dựng bình luận/biểu mẫu/ngữ cảnh báo cáo có cấu trúc (`_build_structured_task_report_comment`, `_build_structured_task_report_form`, `_build_assignment_report_context`) và kiểm tra đầu vào nộp báo cáo file (`_parse_structured_file_report_submission`).
- Gỡ mã chết không còn nơi gọi: `_build_simple_child_task_schema`, `_child_task_numeric_total`, `_build_child_task_unit_summary`, `_build_child_task_reporting_matrix`, `_task_download_slug`, `_task_report_download_name`, `_build_unit_report_cards`, `_build_unit_report_groups`, `_build_discussion_threads`, `_build_unit_report_summary` (chỉ được gọi bởi `_build_unit_report_cards` đã gỡ), cùng def cục bộ trùng lặp của `_parse_report_number` (bản hiệu lực trong `services/task_runtime_sync.py`).
- Dọn kèm: `_format_report_number` vốn là def cục bộ trong routes/tasks.py; chuyển hẳn sang `task_report_views.py` (không có trong `task_runtime_sync`).
- routes/tasks.py re-export toàn bộ tên cũ; hợp đồng `migrate.py` (3 hàm) + import của `tests/test_proposal_runtime.py` không đổi.

## 2026-08-15 (Pha 2 — Tách routes/tasks.py theo miền, đợt 4)
Tách cụm báo cáo Đề án 06 + phân giải người nhận; routes/tasks.py giảm 7.511 → **7.179 dòng** (cộng dồn Pha 2: 11.213 → 7.179), 196 test OK:
- `services/task_da06.py`: nhận diện nhiệm vụ DA06 hằng tháng, phân loại người báo cáo (Sở/ngành theo quy tắc, Tổ công tác cấp xã, Trung tâm PVHCC), dựng biểu mẫu + màn quản lý theo nhóm đơn vị (kèm hằng số `DA06_*`).
- `services/task_assignees.py`: phân giải người nhận/người xem/người xử lý từ form (`_resolve_assignees`, `_resolve_assignees_by_mode`, `_resolve_viewers`, `_resolve_managers`).
- Gỡ mã chết: `_save_task_attachment` (không có nơi gọi), `_should_refresh_assignments` (không có nơi gọi).
- routes/tasks.py re-export toàn bộ tên cũ nên route/test không đổi.

## 2026-08-15 (Pha 2 — Tách routes/tasks.py theo miền, đợt 3)
Tách cụm runtime-sync lớn nhất còn lại; routes/tasks.py giảm 8.302 → **7.511 dòng** (cộng dồn Pha 2: 11.213 → 7.511), 196 test OK:
- `services/task_runtime_sync.py` (~880 dòng): cầu nối Task/TaskAssignment sang TaskItem/TaskParticipant/TaskSubmission (`_sync_task_runtime_models`, `_ensure_task_runtime_bridge`, `_lazy_repair_task_runtime`, `_backfill_task_runtime_models`), phạm vi truy vấn (`_task_scope_identity`, `_query_task_scope`), hàng assignment (`_task_assignment_records/rows`, `_task_assignment_for_user`), executor/visibility, đồng bộ participants/items/submissions, snapshot báo cáo (`_assignment_report_snapshot*`, `_assignment_has_report_submission*`) và tiện ích số liệu (`_parse_report_number`, `_assignment_numeric_report_value`).
- routes/tasks.py re-export toàn bộ tên cũ — `migrate.py` (3 hàm hợp đồng) và mọi route/test không đổi; không test nào patch các hàm đã chuyển nên không phải chỉnh mock.
- Dọn kèm: gỡ def chết bị che khuất của `_latest_assignment_submission` (bản hiệu lực là def sau — được giữ nguyên và chuyển sang module mới).

## 2026-08-15 (Pha 2 — Tách routes/tasks.py theo miền, đợt 2)
Tiếp tục đợt 1 (routes/tasks.py còn ~8.890 dòng), tách thêm 4 module dịch vụ; routes/tasks.py nay còn **8.302 dòng** (cộng dồn Pha 2: 11.213 → 8.302), vẫn giữ nguyên URL/hành vi/bộ test (196 test OK sau mỗi cụm):
- `services/task_report_schema.py`: lược đồ biểu mẫu báo cáo (report schema) — chuẩn hóa phạm vi người nhận theo đơn vị/vai trò/cá nhân (`target_*`), kiểm tra hiển thị đầu mục báo cáo theo người nhận, nạp/chuẩn hóa schema từ cột `report_schema_json`.
- `services/task_form_fields.py`: đọc/lọc trường biểu mẫu `TaskFormField` theo phạm vi người nhận.
- `services/task_import_draft_helpers.py`: nhãn trạng thái/nguồn nháp, tiện ích JSON an toàn, cấu hình lựa chọn trường cho nháp nhập việc.
- `services/task_google_forms.py`: builder schema Google Form + đối sánh phản hồi với assignment theo đơn vị/email người trả lời, cập nhật trường biểu mẫu.
- routes/tasks.py giữ nguyên mọi tên cũ qua import re-export; endpoint đồng bộ Google Form vẫn gọi `build_google_forms_service` / `fetch_google_form_responses` trực tiếp trong routes/tasks.py nên mock tương ứng giữ nguyên; riêng mock `build_google_forms_service` của endpoint tạo qua builder chỉnh về `services.task_google_forms` (nơi `_task_google_form_manage_service` thật sự cư trú) — 196 test OK.

## 2026-08-15 (Pha 2 — Tách routes/tasks.py theo miền, đợt 1)
`routes/tasks.py` giảm từ 11.213 xuống ~8.870 dòng bằng cách tách từng cụm helper tự chứa sang `services/` — giữ nguyên URL, hành vi và bộ test (196 test OK sau mỗi cụm):
- `services/task_modes.py`: hằng số trạng thái/mode + nhãn trạng thái assignment.
- `services/task_permissions.py`: kiểm tra quyền module task (view/process/exec + ủy quyền), is_admin luôn tính từ DB.
- `services/task_categories.py`: danh mục phân loại (lĩnh vực/đội nghiệp vụ/loại/ưu tiên).
- `services/task_deadline.py`: phân tích hạn nộp + cấu hình chu kỳ báo cáo.
- `services/task_units.py`: nhận diện/đối sánh đơn vị, quy đổi người nhận theo đơn vị/vai trò.
- `services/task_scope.py`: phạm vi giao/xem/quản lý + đọc tham số người nhận từ form.
- `services/outline_engine.py` (~980 dòng): engine phân tích đề cương (tiêu đề, phân cấp, nhận diện người nhận, trường số liệu).
- `services/outline_rows.py`: đề cương → dòng (chia block, nhận diện bảng Word/PDF).
- `services/outline_submission.py`: nộp báo cáo đề cương (liên kết đầu mục trùng, lan truyền submission, editor ô số liệu) + `_parse_task_submission_payload`.
- `services/blueprint_parsing.py`: tài liệu tham chiếu → blueprint (Word/Excel/Google Form).
- routes/tasks.py giữ nguyên mọi tên cũ qua import re-export nên `migrate.py`, các route và test import trực tiếp không đổi; các test patch mock được chỉnh về module thật của hàm (`services.outline_engine`, `services.outline_rows`, `services.blueprint_parsing`).

## 2026-08-15 (Pha 1 — Theo dõi tiến độ & cảnh báo hạn)
- **Deadline watchdog** (`services/deadline_watchdog.py`): quét `Task.deadline` của công việc chưa hoàn thành, sinh thông báo theo 3 ngưỡng — sắp đến hạn (mặc định ≤3 ngày), gấp (≤1 ngày / hôm nay), quá hạn. Dedupe theo (user, task, ngưỡng) trong cửa sổ lookback 7 ngày; ngưỡng cấu hình qua `PC06_DEADLINE_*` trong `.env`.
- **Phân giải người nhận**: ưu tiên assignment trực tiếp; assignment theo đơn vị/vai trò quy đổi về lãnh đạo + user cùng `unit_key` + user trùng role; task chạm ngưỡng mà chưa gán cho ai thì báo quản trị.
- **Endpoint `POST /admin/deadline-watchdog/run`** (yêu cầu quyền `sys`/process): chạy quét thủ công hoặc gọi từ cron ngoài; trả flash tổng kết (số thông báo theo ngưỡng, email gửi/bỏ qua).
- **Tích hợp email**: route publish wizard tạo công việc giờ gửi kèm email cho người được giao qua `routes.email_service` (route tạo công việc chính đã có sẵn); watchdog cũng gửi email khi `PC06_DEADLINE_EMAIL_ENABLED=1` và MAIL_* đã cấu hình — tự bỏ qua an toàn nếu chưa.
- **Dashboard lãnh đạo** (`/admin`): thêm thẻ metric "Công việc quá hạn" (số công việc gốc quá hạn còn assignment dang dở).
- Test: `tests/test_deadline_watchdog.py` (9 test — ngưỡng, dedupe, unit resolution, mock email, chặn quyền endpoint).
- `.env.example`: khối cấu hình watchdog + ghi chú MAIL_* là kênh gửi email của watchdog/thông báo giao việc.

## 2026-08-15 (Hoàn thiện khắc phục + gỡ chức năng ADN)
Theo yêu cầu: gỡ toàn bộ tính năng bản đồ ADN liệt sĩ và hoàn thiện các vấn đề tồn đọng sau đánh giá.

### Gỡ tính năng ADN liệt sĩ (không còn cần thiết)
- Xóa route `/ban-do-adn-liet-si` (`routes/portal.py`), entry `portal_bp.martyr_adn_map` khỏi `public_endpoints` trong `check_auth` (`app.py`), thẻ quick-action "Bản đồ ADN liệt sĩ" trên `templates/dashboard.html`.
- Xóa 15 file: `templates/martyr_adn_map.html`, 2 JS metrics + 1 JS schedule (`static/js/martyr-adn-*.js`), script build `scripts/build_martyr_adn_catchment_metrics.py`, thư mục dữ liệu `outputs/adn_collection_points_20260625/`, và 2 test lỗi thời (`tests/test_martyr_adn_map_builder.py` — import module `task_files` không tồn tại, `tests/test_martyr_adn_map_route.py` — route đã bị xóa từ commit trước).

### Sửa lỗi sản phẩm
- **Seeding vai trò chuẩn**: `ensure_standard_system_roles()` tồn tại trong `utils.py` nhưng KHÔNG ĐƯỢC GỌI ở đâu → DB cài mới thiếu 5 vai trò chuẩn CAT/CAX, khiến phân quyền/giao việc không hoạt động đúng. Nay gọi trong `init_db()` sau `apply_migrations` (với `force_update_perms=False`: chỉ tạo vai trò thiếu + chuẩn hóa tên, không ghi đè perms tùy chỉnh).
- **Index DB cho truy vấn nóng**: thêm `index=True` trên `Task(deadline, parent_task_id)`, `TaskAssignment(task_id, user_id, status, assigned_at)`, `Notification(user_id, is_read)`, `TaskSubmission(status)` (`models.py`); thêm khối migration `CREATE INDEX` trong `apply_migrations` để bù cho DB đã tồn tại (chạy cả SQLite lẫn MySQL, kiểm tra index sẵn có, lỗi bỏ qua an toàn).

### Dọn vệ sinh repo & cấu hình
- Untrack file DB: `git rm --cached` `.freebuff/desktop-v2.db*` và `pc06_system.db-journal` (giữ file local); `.gitignore` bổ sung `*.db-journal`, `*.db-shm`, `*.db-wal`.
- `.env.example`: bỏ khối khai báo `DEEPSEEK_*`/AI Assistant (không có mã nào đọc — tính năng LLM mới ở mức ý tưởng), ghi chú "CHƯA TRIỂN KHAI"; khối Zalo ghi chú "CHƯA CÓ MÃ TÍCH HỢP, giữ chỗ cho lộ trình Pha 1".

### Bộ test xanh trở lại
Từ trạng thái 200 test với 7 failure + 12 error + 1 skip, nay còn **187 test, tất cả OK**:
- `tests/test_task_create_wizard.py`: tearDown gom toàn bộ `task_item.id` tạo ra rồi NULL hết tham chiếu FK (`linked_item_id`/`parent_item_id` tự trỏ + cả tham chiếu CHÉO task, `TaskAssignment.task_item_id`, `TaskParticipant`, `TaskSubmission`) TRƯỚC khi xóa — sửa `IntegrityError` khi SQLite bật FK, đồng thời hết gây ô nhiễm test khác (thủ phạm của `test_submit_number_report` 5≠6).
- `tests/test_task_outline_scope.py`, `test_task_file_report_schema.py`, `test_task_form_field_scope.py`: user test dùng vai trò hạn chế ("Cán bộ CAX") thay vì role đầu bảng (vốn là admin) — `is_admin` tính từ `role_id` trong DB, role admin làm mất hết lọc phạm vi nên 3 test scope fail sai.
- `tests/test_security_regressions.py`: gỡ import `AIAssistantConfig` và snapshot cấu hình AI; bỏ 3 test cho tính năng chưa từng tồn tại (ranking permissions, AI API key encryption); sửa test sanitize notification dùng tiêu đề chứa "Công việc mới" để qua bộ lọc nguồn của `/api/notifications`.

## 2026-08-14 (Pha 0 — An toàn bảo mật ngay)
Triển khai theo `docs/BAO_CAO_DANH_GIA_TOAN_DIEN_2026-08.md` (mục B: vấn đề bảo mật xử lý sớm).
- **B1**: Đưa `save_custom_satellite_point` và `delete_custom_satellite_point` khỏi `public_endpoints` trong `check_auth` (`app.py`). Trước đây hai endpoint này cho phép bất kỳ ai ghi/xóa điểm vệ tinh trong DB mà không cần đăng nhập. Endpoint đọc `get_custom_satellite_points` vẫn giữ public để bản đồ hiển thị.
- **B2**: Bỏ các lời gọi `db.create_all()` trong request handler (`routes/api.py`) — bảng đã được tạo trong `init_db()` lúc khởi động.
- **B3**: Không trả nguyên văn `str(e)` / traceback ra client ở các endpoint vệ tinh, `diagnose-db` và `resolve-maps-url` (`routes/api.py`, `routes/health.py`). Chi tiết lỗi chỉ log phía server.
- **CI**: Thêm job chạy `python3 -m unittest discover tests` làm điều kiện bắt buộc trước bước FTP deploy (`.github/workflows/deploy.yml`).
- **B5**: Thêm `.freebuff/` vào `.gitignore`.
- Test hồi quy: `tests/test_satellite_api_security.py` (endpoint ghi/xóa yêu cầu đăng nhập → 401, endpoint đọc public vẫn hoạt động).
- **Cách ly bộ test** (`run_tests.py` + `tests/__init__.py`): mọi cách chạy test (kể cả `python -m unittest discover tests` lẫn chạy nhầm trên server) đều bị ép chạy trên database SQLite tạm dùng xong bỏ + thư mục dữ liệu tạm (`PC06_DATA_DIR`), KHÔNG đụng DB production trong `.env`; mật khẩu admin bootstrap cố định (không in mật khẩu ngẫu nhiên ra log). CI chuyển sang chạy `python3 run_tests.py`.

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
