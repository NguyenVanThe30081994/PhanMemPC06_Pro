# Nghiên cứu sâu chức năng Giao việc & Báo cáo kết quả test đầu vào với biểu mẫu "Đề cương báo cáo ĐA06 - H.T.Q.docx"

*Ngày thực hiện: 26/08/2026 · Phân tích + test thực tế trên mã nguồn PhanMemPC06_Pro*

---

## PHẦN I — NGHIÊN CỨU SÂU CHỨC NĂNG GIAO VIỆC

### 1. Tổng quan kiến trúc

Chức năng giao việc theo đề cương là luồng biến một file biểu mẫu Word (.docx) của cấp trên
(thí điểm: "Đề cương báo cáo ĐA06 - H.T.Q.docx" — Đề cương báo cáo tiến độ năm 2026 triển khai
Đề án 06) thành **công việc cụ thể gán cho từng cán bộ**, theo dõi nộp báo cáo và tổng hợp lại
thành văn bản Word.

Các lớp chính:

| Lớp | File | Vai trò |
|---|---|---|
| Parser đề cương | `outline_parser.py` | Đọc .docx/.txt → cây JSON đa tầng (I. → 1. → 1.1. → 1.1.1. → gạch đầu dòng → mục `+`) |
| Engine phân tích | `services/outline_engine.py` (1015 dòng) | Nhận diện heading, tách tiêu đề, nhận diện người nhận (hint "Sở Y tế", "Thuế tỉnh"...), nhận diện trường số liệu trong văn bản |
| Phân tích thành dòng | `services/outline_rows.py` (584 dòng) | Chia block, parse bảng nhiệm vụ trong Word/PDF, gộp trùng, gán hint đơn vị |
| Route trình biên tập | `routes/outline.py` | `/outline-editor`, `/api/parse-outline`, `/api/save-outline`, `/outline-giao-viec`, `/api/outline-assignees`, `/api/create-outline-task` |
| Route wizard tạo việc | `routes/tasks.py` | `/tasks/outline-parse` (parse ngay trong bước tạo công việc), `/tasks/<tid>/outline/import-preview` |
| Nộp & tổng hợp | `services/task_pages.py` (`_submit_task_report_v2`), `services/outline_submission.py`, `services/task_report_aggregate.py` | Nhận báo cáo từng đầu mục, tổng hợp, xuất `/tasks/<tid>/export-outline.docx` |
| Biểu mẫu chuyên biệt ĐA06 | `services/task_da06.py` | Nhận diện nhiệm vụ "Báo cáo Đề án 06 tháng…" (marker "bao cao de an 06 thang"), phân 3 nhóm người báo cáo: **Sở/ngành** (9 quy tắc nhận diện: BHXH, Thuế, Tư pháp, GD&ĐT, NN&MT, Công Thương, Nội vụ, Tòa án, Y tế — mỗi ngành một bộ DVC/Dịch vụ công trực tuyến tương ứng), **Tổ công tác cấp xã** (role marker "to cong tac cap xa"), **Trung tâm PVHCC** (username `ttpvhcctq`) — dựng biểu mẫu riêng theo nhóm và màn quản lý gộp theo đơn vị |
| Phân quyền | `services/task_permissions.py`, `services/task_guards.py`, `task_policies.py` | `p_task_process` để giao việc; `can_view_task(task, session_uid, is_admin, is_lead, is_executor, can_manage, can_watch, has_visible_child_tasks)` để xem |

### 2. Hai luồng giao việc theo đề cương

**Luồng A — Trang "Giao việc theo đề cương" (`/outline-giao-viec` + `template/outline_assign.html`):**
1. Upload .docx → `POST /api/parse-outline` → `parse_docx()` → cây JSON (giữ nguyên đa tầng).
2. Người dùng tick mục, gán cán bộ (chỉ gán trực tiếp cho người, `assignments[node_id] = {ids:[...]}`).
3. `POST /api/create-outline-task` → mỗi **mục heading được gán** tạo 1 `TaskItem`
   (`output_type='OUTLINE'`, `report_kind='narrative'`, `item_code` chạy số, nội dung =
   toàn bộ dòng bullet/plus/para dưới mục gộp lại, tối đa 5000 ký tự) + 1..n
   `TaskAssignment` (status `assigned`) + phạm vi `assignment_scope_json` (mode `user`)
   + cầu nối runtime `TaskParticipant` + thông báo trong ứng dụng `push_notif` + email.

**Luồng B — Wizard tạo công việc (`/tasks/outline-parse`):** parse theo **hierarchy → rows**:
mỗi **gạch đầu dòng cấp 1** là một việc riêng (khác Luồng A: mỗi *mục* là một việc);
dòng `+` là việc con (`parent_row_index`); tự nhận diện người nhận từ văn bản
(`_resolve_outline_assignee_hint` với catalog đơn vị/vai trò/người dùng) và nhận diện
trường số liệu để sinh biểu mẫu nhập số (`report_kind='number'`).

### 3. Sơ đồ luồng dữ liệu sau khi giao

```
Task (task_mode='OUTLINE')
 ├── TaskItem (item_code, title, content, report_kind, sort_order)
 │     └── TaskAssignment (user_id, status: assigned→submitted/returned)
 │             ├── TaskSubmission (narrative/number/file, cycle_key)
 │             └── report_payload_json (mode, narrative, numeric_value, attachment)
 ├── TaskParticipant (cầu nối runtime, executor)
 ├── assignment_scope_json {mode:'user', user_ids:[...]}
 └── Notification (link /tasks/<id>) + email (send_task_assignment_emails)
```

Trạng thái & vòng đời: `Chưa tiếp nhận` → `assigned` → (nộp) `submitted` → (trả lại kèm lý do
`POST /tasks/<tid>/assignments/<aid>/return`, ghi `[TRẢ LẠI]` vào bình luận) → nộp lại.
Định kỳ có `services/deadline_watchdog.py` + `task_scheduler.py` theo dõi hạn.

### 4. Đối chiếu biểu mẫu ĐA06 với chức năng

File "Đề cương báo cáo ĐA06 - H.T.Q.docx" (43.926 bytes, 131 đoạn):
- **Tiêu đề**: "ĐỀ CƯƠNG BÁO CÁO TIẾN ĐỘ NĂM 2026" / phụ đề "TRONG TRIỂN KHAI, THỰC HIỆN ĐỀ ÁN 06, CẢI CÁCH TTHC, CHUYỂN ĐỔI SỐ GẮN VỚI ĐỀ ÁN 06".
- **Cấu trúc** parse được: 51 mục heading (2 h1, 12 h2, 25 h3, 12 h4), 60 gạch đầu dòng, 9 mục `+`, 6 đoạn văn tự do — cây 4 tầng, đúng với thuật toán phân cấp bất kể số tầng của `outline_parser.py`.
- Nội dung khớp chính xác với các "marker" nghiệp vụ đã hard-code trong `services/task_da06.py`: mục 3.2 "Trung tâm Phục vụ hành chính công", mục 4.2 "Thuế tỉnh", các mục "Về hoàn thiện thể chế", "Về cải cách TTHC", "Về phát triển kinh tế xã hội"… đều nằm trong danh sách `structural_markers` của engine.
- Biểu mẫu có các **chỉ số dạng %/số** (tỷ lệ DVC trực tuyến toàn trình ≥80%, tỷ lệ hồ sơ đúng hạn/quá hạn, tỷ lệ thanh toán điện tử…) — luồng B sẽ tự sinh trường nhập số; luồng A gộp thành nội dung narrative.

**Hai điểm bất thường của biểu mẫu (đề nghị bổ khuyết khi sử dụng):**
1. Đánh số nhảy: mục `I.1.1` nhảy thẳng sang `1.6` (thiếu 1.2–1.5); các cụm h2 sau mục 7 quay lại đánh số `1..4` trong phần Kiến nghị (III) — parser vẫn xử lý đúng vì phân cấp theo số chấm, nhưng khi giao việc cần lưu ý nhãn trùng "1", "2", "3", "4" xuất hiện 2 lần.
2. Phần đầu tài liệu có nhãn `I. KẾT QUẢ CÁC MẶT CÔNG TÁC` nhưng sau mục 8 đi thẳng sang `III KIẾN NGHỊ, ĐỀ XUẤT` (thiếu II) — cây vẫn hợp lệ, không ảnh hưởng parse.

---

## PHẦN II — KẾT QUẢ TEST ĐẦU VÀO (INPUT TESTING)

### 1. Phương pháp

- Môi trường: venv độc lập `/tmp/pc06_venv` (Flask 3.1.3, SQLAlchemy 2.0.52, python-docx), SQLite test do `app.py` tự tạo cách ly, user admin tự seed.
- Script test end-to-end **`scripts/test_da06_input.py`** (mới) — dùng chính file biểu mẫu .docx trong Downloads làm đầu vào thật, chạy qua Flask test client theo đúng luồng người dùng: parse → giao → kiểm DB → người nhận xem & nộp → xuất Word.
- Chạy lại bộ unit test liên quan: `test_task_outline_create_api`, `test_task_outline_scope`, `test_task_outline_word_export`, `test_report_aggregate`, `test_proposal_runtime`, sau đó toàn bộ 222 test của dự án.

### 2. Kết quả 14 bước kiểm tra — 14/14 PASS (sau khi sửa 2 lỗi)

| # | Bước kiểm tra | Kết quả | Ghi chú |
|---|---|---|---|
| P1 | Parser .docx → cây cấu trúc | **PASS** | title + 51 heading, stats: {h1:2, h2:12, h3:25, h4:12, bullet:60, plus:9, para:6} |
| P2 | `POST /api/parse-outline` (upload file thật) | **PASS** | Lần 1 trả 400 vì thiếu `X-CSRF-Token` → **hành vi bảo mật đúng**, bổ sung header rồi PASS |
| P3a | Chọn 3 mục đại diện (1, 2.2, 8) để gán | **PASS** | Tìm đúng mục theo nhãn trong cây |
| P3b | `POST /api/create-outline-task` | **PASS** | task_id tạo mới, 3 items, 3 lượt giao, 2 thông báo |
| P4a | Task trong DB | **PASS** | `task_mode=OUTLINE`, trạng thái "Chưa tiếp nhận", deadline 2026-09-30 |
| P4b | TaskItem | **PASS** | 3 đầu mục, nội dung gộp đúng (mục 1 gộp 7 dòng, mục 2.2 gộp 2 dòng, mục 8 gộp 1 dòng) |
| P4c | TaskAssignment | **PASS** | 3 bản ghi, đúng user, status `assigned` |
| P4d | TaskParticipant (cầu nối runtime) | **PASS** | 2 người thực hiện được đồng bộ ngay sau tạo |
| P4e | Notification | **PASS** | 2 thông báo link `/tasks/<id>` |
| P4f | assignment_scope | **PASS** | `{mode:'user', user_ids:[4,5]}` |
| P5a | Người được giao xem chi tiết việc | **PASS** | HTTP 200, chỉ thấy đúng đầu mục của mình (scope) |
| P5b | `POST /tasks/<id>/submit_report` nộp báo cáo | **PASS** | Trước đó FAIL 404 vì test cũ gọi sai route (`/assignments/<id>/submit` không tồn tại); route chuẩn là `/submit_report` với `task_item_id` + `report_content` |
| P5c | TaskSubmission lưu DB | **PASS** | Bản ghi narrative + comment `[BÁO CÁO]` |
| P6 | `GET /tasks/<id>/export-outline.docx` | **PASS** | File Word hợp lệ (PK header, wordprocessingml) — sau khi sửa 2 lỗi bên dưới |

### 3. Lỗi phát hiện được & đã sửa

| # | Mức độ | Lỗi | Nguyên nhân gốc | Cách sửa |
|---|---|---|---|---|
| L1 | **Cao** | Xuất Word tổng hợp luôn 403 kể cả admin (kéo theo 2 unit test có sẵn fail: `test_outline_matrix_and_word_export`, `test_word_export_requires_permission`) | `routes/tasks.py` gọi `can_view_task(g, task_id)` — sai chữ ký; hàm thật nhận `(task, session_uid, is_admin, ...)` nên luôn trả False. Lỗi tồn tại ở **2 route**: `/api/tasks/<id>/report/aggregate` và `/tasks/<id>/export-outline.docx` | Thay bằng helper chuẩn của dự án `_can_view_task(task)` (đã tính is_admin từ DB, executor, manage, watch, việc con) + nạp task bằng `db.session.get(Task, task_id)` |
| L2 | **Cao** | Sau khi sửa L1, route xuất Word v1 chuyển sang 500 `NameError: export_outline_docx` | `routes/tasks.py` gọi hàm nhưng thiếu import (hàm nằm ở `services/task_report_aggregate.py`; file chỉ import `build_aggregate_context` gián tiếp qua `task_report_views`) | Bổ sung `from services.task_report_aggregate import export_outline_docx` |
| L3 | Thấp (chuẩn hoá) | Hành vi phân quyền route xuất Word chưa nhất quán giữa 2 route trùng URL | Route v1 (JSON 403) và route v2 `/tasks/<tid>/export-outline.docx` (redirect 302) cùng khớp một URL; Flask dùng route định nghĩa sau cùng | Đồng bộ: chưa đăng nhập → 302 về login; đã đăng nhập thiếu quyền → 403. Cập nhật test `test_word_export_requires_permission` từ kỳ vọng 302 → 403 |

Điểm cần lưu ý kiến trúc: hiện có **2 route trùng URL** `/tasks/<int>/export-outline.docx`
(`task_export_outline_docx` dòng 173 và `export_outline_task_word` dòng 939). Flask chỉ thực thi
route định nghĩa sau cùng (v2 → `_export_outline_word_v2`), nên bản v1 hiện là "mã bóng" —
sửa lỗi L1/L2 vẫn cần thiết để route v1 an toàn nếu được dùng, và nên **gỡ một trong hai route**
trong đợt kế tiếp để tránh nhầm lẫn.

### 4. Kết quả chạy lại bộ test

- Bộ test chức năng (5 module, 20 test): **OK — 20/20 PASS** (trước sửa: 8/10).
- Toàn bộ suite 222 test: 218 PASS, 4 FAIL **tồn tại từ trước thay đổi** (xác minh bằng `git stash` rồi chạy lại):
  - `test_deadline_watchdog.TaskSchedulerTest.test_enabled_flag_respects_env_and_testing`, `test_start_is_idempotent_and_not_running_in_testing` — cấu hình scheduler trong môi trường test (không liên quan giao việc).
  - `test_task_synthesis.TaskSynthesisTests.test_clear_synthesis_falls_back_to_auto_merge`, `test_save_synthesis_then_export_uses_synthesis` — xuất tổng hợp đang thêm nhãn đơn vị `assign_1:`/`assign_2:` vào đầu mỗi đoạn nên assert `assertIn` với chuỗi thuần không khớp; nội dung vẫn đầy đủ (lỗi assertion/kỳ vọng hoặc hồi quy định dạng — cần rà `_export_outline_word_v2` nếu muốn giữ định dạng cũ).

### 5. Các trường hợp đầu vào biên đã kiểm chứng qua code + test có sẵn

- File sai định dạng/đọc không được → 400 với thông báo tiếng Việt rõ ràng (`_parse_outline_docx_rows`).
- Sai đuôi file (chỉ .docx/.txt cho editor; .docx/.txt/.pdf cho wizard) → 400 `ValueError`.
- Chưa đăng nhập → 401; thiếu quyền `p_task_process` → 403 (5 test trong `test_task_outline_create_api`).
- Thiếu CSRF token → 400 (kiểm chứng trực tiếp trong P2).
- Cây rỗng / không gán mục nào → 400 "Chưa gán mục nào…", có rollback transaction.
- Deadline sai định dạng → bỏ qua âm thầm (đặt là không hạn) — có thể cân nhắc trả lỗi 400 rõ ràng hơn.
- Ký tự `<255` title, content cắt 5000 — chống tràn dữ liệu có sẵn.

---

## PHẦN III — ĐÁNH GIÁ & KIẾN NGHỊ

**Đánh giá chung:** Chức năng giao việc theo đề cương đáp ứng tốt biểu mẫu ĐA06 thật: parse đúng
cây 4 tầng 51 mục, giao việc đúng mục, dữ liệu nhất quán 6 lớp (Task/TaskItem/TaskAssignment/
TaskParticipant/Notification/scope), người thực hiện nộp báo cáo và tổng hợp xuất Word hoạt động
tròn vẹn sau khi vá 2 lỗi quyền/import. Phân quyền nhiều tầng chặt (CSRF, 403 đúng chỗ, admin
tính từ DB không tin session).

**Kiến nghị thứ tự ưu tiên:**
1. *(Đã sửa)* L1 + L2 — quyền xem & thiếu import ở route aggregate/export-outline v1; L3 — đồng bộ hành vi 302/403.
2. Gỡ hoặc tách URL route xuất Word trùng nhau (v1/v2) để bỏ "mã bóng".
3. Rà 2 fail `test_task_synthesis` (định dạng đoạn tổng hợp có tiền tố `assign_N:`) — quyết định định dạng chuẩn và sửa assert hoặc engine.
4. Rà 2 fail `test_deadline_watchdog` liên quan cấu hình scheduler khi test.
5. Cân nhắc trả 400 thay vì bỏ qua khi `deadline` sai định dạng ở `/api/create-outline-task`.
6. Với biểu mẫu ĐA06: vì 1 mục ĐA06 thường cần số liệu theo chỉ tiêu, khuyến nghị dùng **luồng B (wizard + rows số liệu)** hoặc mở rộng `services/task_da06.py` thêm bộ trường theo từng chỉ tiêu 3.1/3.2 để tổng hợp tỷ lệ % tự động thay vì narrative tự do.

**Tệp thay đổi trong đợt này:**
- `routes/tasks.py` — sửa 2 lỗi quyền (L1) + thiếu import (L2) + đồng bộ 302/403 (L3).
- `tests/test_task_outline_word_export.py` — cập nhật kỳ vọng hành vi đúng (403).
- `scripts/test_da06_input.py` — script test đầu vào tái sử dụng được với file biểu mẫu bất kỳ.
- `docs/nghien-cuu-giao-viec-test-dau-vao-da06-2026.md` — báo cáo này.
