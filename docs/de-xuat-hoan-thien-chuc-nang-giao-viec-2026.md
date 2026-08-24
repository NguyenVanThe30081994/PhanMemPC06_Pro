# Nghiên cứu hiện trạng & đề xuất hoàn thiện chức năng Giao việc

Ngày cập nhật: `22/08/2026`
Phạm vi: chức năng **Giao việc – Báo cáo** của PhanMemPC06_Pro (kiến trúc, bảo mật, hiệu năng, chất lượng mã, kiểm thử, nghiệp vụ).
Kế thừa: `docs/thiet-ke-chuc-nang-giao-viec-hop-nhat-2026.md`, `docs/nghien-cuu-phan-mem-giao-viec-2026.md`, `CHANGELOG.md`.

---

## 1. Tóm tắt điều hành

- Kế hoạch đợt trước (G1–G5: xuất Word tổng hợp, ma trận tiến độ, lưới nhập bảng, trả lại bổ sung, trang Việc của tôi) **đã hoàn thành đủ**, cùng Pha 2 tách `routes/tasks.py` (11.213 → ~930 dòng) và Pha 3 (tổng hợp FORM, tìm kiếm toàn cục, báo cáo định kỳ, watchdog nền).
- Nghiên cứu lần này phát hiện **3 nhóm vấn đề còn tồn tại**: (P1) lỗ hổng phân quyền ở luồng tạo việc theo đề cương và thiếu CSRF; (P2) luồng OUTLINE tại `routes/outline.py` đi lạc khỏi pipeline chung (trạng thái sai chuẩn, thiếu runtime bridge/thông báo/email/nhật ký); (P3) hiệu năng (migration check mỗi request, N+1 truy vấn, nạp toàn bộ user mỗi GET).
- Đề xuất lộ trình **3 đợt**: Đợt 1 chốt an toàn & phân quyền (cao nhất), Đợt 2 thống nhất luồng OUTLINE, Đợt 3 hiệu năng – chất lượng – kiểm thử. Không thêm dependency mới, không phá dữ liệu cũ.

---

## 2. Bản đồ hiện trạng kiến trúc

### 2.1 Mô hình dữ liệu (`models.py`, 586 dòng)
```
Task ── 1:N ── TaskItem ── 1:N ── TaskAssignment ── 1:N ── TaskSubmission ── 1:N ── TaskSubmissionFile
Task ── 1:N ── TaskParticipant (người liên quan, phục vụ scope/xem)
Task ── 1:N ── TaskFormField (cấu hình biểu mẫu FORM)
Task ── 1:N ── TaskComment (nhật ký trao đổi)
```
- `TaskAssignment.status` mặc định `'Chưa tiếp nhận'` (models.py:369).
- Điểm yếu dữ liệu: `Task.author_id`, `TaskAssignment.unit_id` (models.py:366), `TaskComment.task_id/user_id` là số nguyên **không có FK**; `author_name`/`user_name` denormalize dễ lỗi thời.

### 2.2 Routes
| Tệp | Dòng | Nội dung |
|---|---|---|
| `routes/tasks.py` | 932 | ~315 dòng route thật; L155–664 dải re-export ~250 tên từ 20+ service module |
| `routes/outline.py` | 421 | Luồng tạo việc theo đề cương độc lập: `/outline-editor`, `/outline-assign`, `/api/outline-assignees`, `/api/create-outline-task` |

### 2.3 Services (chính)
| Module | Dòng | Vai trò |
|---|---|---|
| `services/task_pages.py` | 1.572 | Trang danh sách/chi tiết/tạo wizard/nộp bài/xuất file (`_v2`) |
| `services/task_runtime_sync.py` | 924 | Cầu nối runtime: TaskParticipant, submission hiện hành, suy diễn phạm vi |
| `services/task_guards.py` | — | `_can_manage_task/_can_edit_task/_can_view_task/_can_delete_task` |
| `services/task_scope.py`, `task_policies.py`, `task_modes.py`, `report_cycles.py`, `task_admin.py`, `task_synthesis.py`, `task_form_aggregation.py`, `report_dashboard.py`, `global_search.py`, `deadline_watchdog.py`, `task_scheduler.py` | — | Scope, chính sách, chế độ thu thập, chu kỳ báo cáo, quản trị, tổng hợp, tìm kiếm, nhắc hạn nền |
| `services/task_import_ai.py` / `task_import_drafts.py` | 2.329 / 1.796 | Nhập đề cương AI + nháp phát hành |

### 2.4 Templates & kiểm thử
- `templates/tasks_rebuild.html` (3.434 dòng), `task_detail_rebuild.html` (2.560 dòng) — hai template lớn nhất hệ thống.
- `tests/` ≈ 8.480 dòng / **199 test OK** (CHANGELOG 19/08/2026). `test_task_assignment.py` ở thư mục gốc là script chạy tay, không thuộc suite.

## 3. Đối chiếu kế hoạch đợt trước (G1–G5): đã hoàn thành

| # | Mục tiêu | Bằng chứng |
|---|---|---|
| G1 | Xuất Word tổng hợp OUTLINE | Route `/tasks/<tid>/export-outline.docx` (routes/tasks.py:891) + `tests/test_task_outline_word_export.py` |
| G2 | Ma trận tiến độ đầu mục × đơn vị | `_build_outline_progress_matrix` (services/task_pages.py:1326), tab `outline-matrix` (task_detail_rebuild.html:152–271) |
| G3 | Lưới nhập kiểu Excel cho trường `table` | `data-table-grid` + nút "Thêm dòng" (task_detail_rebuild.html:1144–1168, JS :2288) |
| G4 | Trả lại bổ sung kèm lý do | Route `return_task_assignment` (routes/tasks.py:900) + nút ở ma trận và danh sách (:240, :681, :1006) |
| G5 | Nâng hiển thị "Việc của tôi" | Đã cải thiện cơ bản (đánh dấu Thấp, còn dư địa ở P6) |

---

## 4. Phát hiện còn tồn tại

### P1 — Bảo mật & phân quyền (nghiêm trọng nhất)
> Cập nhật 22/08/2026: mục 1–3 dưới đây **đã được xử lý** (xem §5 Đợt 1). Riêng CSRF (mục 4) sau kiểm chứng lại thấy **đã có sẵn toàn cục** tại app.py:542 (`enforce_csrf_protection`) — phát hiện ban đầu là sai.
1. ~~**`POST /api/create-outline-task` chỉ kiểm tra đăng nhập**~~ ✅ Đã siết bằng `_can_process_task_module` → 403 (routes/outline.py).
2. ~~**`GET /api/outline-assignees` phơi toàn bộ danh bạ user đang hoạt động**~~ ✅ Đã giới hạn cho người có quyền process module Công việc.
3. ~~**Các endpoint phân tích/phát hành nhập liệu chỉ cần đăng nhập**~~ ✅ `preview_workflow_blueprint`, `import_workflow_blueprint`, `parse_outline_file_for_create` đã thêm kiểm quyền như `form-template-preview`.
4. **CSRF**: sau rà lại, hệ thống đã ép CSRF token cho mọi POST (app.py:542–569), trừ static và Google callback. Không cần làm gì thêm.

### P2 — Luồng OUTLINE tại `routes/outline.py` đi lạc khỏi pipeline chung
> Cập nhật 22/08/2026: mục 1 **đã xử lý**; mục 2 sau kiểm chứng là **sai** — `status='assigned'` chính là từ vựng chuẩn của assignment (bảng nhãn tiếng Việt ở `TASK_ASSIGNMENT_STATUS_LABELS`, services/task_modes.py:28), dùng thống nhất ở cả wizard chính.
- ~~Việc tạo từ `/api/create-outline-task` không có thông báo/email/nhật ký/runtime bridge~~ ✅ Đã bổ sung đủ: `_store_assignment_scope` + `_ensure_task_runtime_bridge` + `push_notif` + `send_task_assignment_emails` + `log_action`.
- Trạng thái assignment `'assigned'` hiển thị "Chưa tiếp nhận" qua bảng nhãn — nhất quán với task_pages.py:474, 945 và task_assignees.py:157. Không cần sửa.

### P3 — Hiệu năng
1. `_ensure_task_schema()` → `apply_migrations(current_app)` chạy lại **mỗi request** trên mọi route task.
2. N+1 truy vấn `db.session.get(User, …)` trong vòng lặp: services/task_pages.py:1332, 1347, 1499, 1529; task_workspace_helpers.py:184, 363; task_synthesis.py:86; task_runtime_sync.py:546.
3. `_tasks_page_v2` nạp **toàn bộ user + vai trò đang hoạt động mỗi lần GET** dành cho lead/admin (services/task_pages.py:218–231).
4. Cột TEXT chứa JSON bị parse lại nhiều lần trong cùng một request.

### P4 — Chất lượng mã nguồn
1. Hàm "gốc": `_tasks_page_v2` ~487 dòng (GET render + toàn bộ POST tạo việc), `_submit_task_report_v2` ~200 dòng (services/task_pages.py:203–689, 1061–1262).
2. Dải re-export ~250 tên trong routes/tasks.py (L155–664) tạo hai đường import song song, khó lần vết nơi định nghĩa thật.
3. Mã chết: `TASK_IMPORT_DRAFT_ALLOWED_STATUSES` (routes/tasks.py:309, không nơi nào dùng); import thừa (`html`, `io`, `Decimal`, `MultiDict`, `secure_filename`, `joinedload`…).
4. Chuỗi trạng thái tiếng Việt hard-code rải rác trong model default, `task_modes.py`, `task_workspace.py`, templates — dễ lệch nhau khi sửa.

### P5 — Khoảng trống kiểm thử
- **Chưa có test nào cho các endpoint của `routes/outline.py`** (`/api/create-outline-task`, `/api/outline-assignees`, `/outline-editor`) — đúng vùng có rủi ro P1/P2.
- Chưa có test cấp route cho: render danh sách `/tasks`, `edit_config`, `update_status`, `return_task_assignment`.

### P6 — Nghiệp vụ/trải nghiệm còn thiếu (so với nghiên cứu sản phẩm 04/08/2026)
- Khi một đầu mục giao cho nhiều người: chưa có khái niệm **người chịu trách nhiệm chính** (bài học Asana).
- Trang tổng hợp "Việc của tôi" cho người nhận còn đơn giản (G5 cũ, mức Thấp).

---

## 5. Đề xuất hoàn thiện — lộ trình 3 đợt

### Đợt 1 — Chốt an toàn & phân quyền (ưu tiên cao nhất) — ✅ ĐÃ TRIỂN KHAI 22/08/2026
| # | Việc cần làm | File liên quan | Trạng thái |
|---|---|---|---|
| 1.1 | `/api/create-outline-task` yêu cầu `_can_process_task_module()` (đồng bộ wizard chính); trả 403 nếu không đủ | routes/outline.py | ✅ Xong |
| 1.2 | `/api/outline-assignees`: chỉ trả cho người có quyền process module Công việc | routes/outline.py | ✅ Xong |
| 1.3 | Thêm kiểm quyền cho `preview_workflow_blueprint`, `import_workflow_blueprint`, `parse_outline_file_for_create` | routes/tasks.py | ✅ Xong |
| 1.4 | Token CSRF nhẹ tự làm | app.py:542 | ⛔ Không cần — CSRF đã ép toàn cục từ trước |

Kèm theo: trang `/outline-giao-viec` cũng chặn người không đủ quyền (403). Test mới: `tests/test_task_outline_create_api.py` (5 test).

### Đợt 2 — Thống nhất luồng OUTLINE vào pipeline chung
| # | Việc cần làm | File liên quan | Trạng thái |
|---|---|---|---|
| 2.1 | Sau khi tạo việc từ đề cương: `_store_assignment_scope` + `_ensure_task_runtime_bridge(task)` + Notification/email `send_task_assignment_emails` + `log_action` | routes/outline.py | ✅ Xong 22/08/2026 |
| 2.2 | Sửa `status='assigned'` → hằng chuẩn `'Chưa tiếp nhận'` | routes/outline.py:391 | ⛔ Hủy — `'assigned'` là từ vựng chuẩn có bảng nhãn (services/task_modes.py:28) |
| 2.3 | Tập trung từ vựng trạng thái thành hằng số duy nhất, thay dần chỗ hard-code | models.py, task_modes.py, task_workspace.py, templates | ⏳ Chưa làm (mức trung) |
| 2.4 | Gỡ bản parser trùng `_is_outline_heading`; outline.py dùng bản của `services/outline_engine.py` | routes/outline.py:238, services/outline_engine.py:512 | ⏳ Chưa làm (thấp, hai bản khác chữ ký nên gộp cần cẩn trọng) |

### Đợt 3 — Hiệu năng, chất lượng, kiểm thử
| # | Việc cần làm | File liên quan | Tiêu chí nghiệm thu |
|---|---|---|---|
| 3.1 | Migration check chạy 1 lần lúc khởi động (flag schema-version trong app config) thay vì mỗi request | services/task_admin.py `_ensure_task_schema`, app.py | Mỗi request giảm ≥1 vòng apply_migrations; khởi động vẫn tự vá schema |
| 3.2 | Hết N+1: batch load user bằng truy vấn IN/selectinload tại 8 điểm liệt kê ở P3.2; chỉ nạp toàn bộ user khi POST wizard | task_pages.py, task_workspace_helpers.py, task_synthesis.py, task_runtime_sync.py | Trang danh sách/chi tiết giảm đáng kể số query (đo bằng SQLALCHEMY echo) |
| 3.3 | Dọn mã chết + import thừa trong routes/tasks.py; thu hẹp dải re-export còn những tên thực sự cần cho test/migrate | routes/tasks.py:155–664, :309 | File giảm ~200+ dòng; migrate.py không đổi hợp đồng |
| 3.4 | Tách nốt POST-tạo-việc khỏi `_tasks_page_v2` thành service riêng (tiếp nối Pha 2) | services/task_pages.py:203–689 | `_tasks_page_v2` < 150 dòng; 199 test vẫn xanh |
| 3.5 | Bổ sung route tests: `/api/create-outline-task` (quyền + dữ liệu), `/api/outline-assignees` (phạm vi), `return_task_assignment`, `edit_config`, `update_status` | tests/test_task_outline_scope.py (mở rộng) | Suite ≥ 205 test; phủ hết endpoint P1/P2 |
| 3.6 | Thêm FK + index cho `unit_id`, `author_id`… qua migrate.py (rà dữ liệu mồ côi trước); đồng bộ `author_name` khi đổi tên user | models.py, migrate.py, utils.py | Không còn hàng mồ côi sau migration; tên hiển thị không lỗi thời |
| 3.7 | (Nghiệp vụ) Khái niệm "người chịu trách nhiệm chính" khi giao nhiều người/đầu mục; nâng trang "Việc của tôi" | models.py (thêm cờ `primary_owner`), task_detail_rebuild.html | Ma trận đánh dấu người chính; người nhận ưu tiên việc mình chịu trách nhiệm |

---

## 6. Tiêu chí nghiệm thu tổng

- [x] User thường không thể tạo việc/gán người qua bất kỳ đường API nào (kể cả outline). *(22/08/2026)*
- [x] Danh bạ user không còn phơi rộng cho mọi user đã đăng nhập. *(22/08/2026)*
- [x] POST thay đổi trạng thái đều yêu cầu CSRF token; không dependency mới. *(đã có sẵn, kiểm chứng lại)*
- [x] Việc tạo từ đề cương có participant + thông báo + email + nhật ký; trạng thái chuẩn theo bảng nhãn chung. *(22/08/2026)*
- [ ] Không còn migration-check mỗi request; không còn N+1 tại 8 điểm đã liệt kê. *(Đợt 3)*
- [x] Suite test ≥ 205, gồm test phủ routes/outline.py; 199 test cũ không vỡ. *(204 test OK — 22/08/2026)*

## 7. Rủi ro & tương thích

- Không xóa bảng/cột; mọi thay đổi schema đi qua `migrate.py` theo đúng quy ước hiện hành.
- ~~Script vá trạng thái outline cũ~~ ⛔ Không cần — không đổi từ vựng trạng thái.
- ✅ Đã xử lý: thu hẹp quyền `/api/*` outline kèm chặn trang `/outline-giao-viec` nên user thường không vào được trang rồi gặp lỗi API.
- ~~CSRF áp theo module~~ ⛔ Không cần — đã ép toàn cục ở app.py:542 từ trước, các luồng Google Form/Zalo vẫn hoạt động (đã xác nhận qua 204 test).
