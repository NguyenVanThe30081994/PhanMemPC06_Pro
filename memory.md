# MEMORY — PhanMemPC06_Pro

> File này ghi lại toàn bộ kiến trúc, trạng thái, quyết định và việc cần làm của dự án
> để Agent phiên làm việc mới đọc ĐẦU TIÊN là nắm được toàn bộ mã nguồn và biết việc tiếp theo.
> Cập nhật mỗi khi thay đổi trạng thái. (Cập nhật lần cuối: 2026-11-20)

---

## 1. Tổng quan phần mềm

**Là gì / cho ai:**
Phần mềm quản trị điều hành nội bộ phục vụ triển khai **Đề án 06** (chuyển đổi số, cải cách TTHC)
của tỉnh Tuyên Quang. Người dùng: admin + cán bộ các sở/ngành/đơn vị cấp xã (đăng nhập theo vai trò
và đơn vị). Production chạy trên cPanel (host Mắt Bão), domain `https://pc06tuyenquang.net`,
DB MariaDB `dea35688_pc06tuyenquang`. Xem bằng chứng trong `DEPLOY_CPANEL.md`, `database.sql`,
`app.py` (`_security_txt_content` mặc định `pc06tuyenquang.net`).

**Chức năng chính** (đã kiểm chứng qua routes + `docs/THIET_KE_TONG_GIAO_DIEN_2026.md` Mục 5):
- **Công việc/giao việc** (`/tasks`): tạo việc theo 3 hình thức `task_mode` = `OUTLINE` (đề cương,
  tổng hợp Word) / `FILE` (nộp file) / `FORM` (biểu mẫu số liệu); import từ Excel + phân tích AI;
  ma trận tiến độ; xuất Word tổng hợp; biểu mẫu chuyên biệt Đề án 06 (`services/task_da06.py`).
- **Thông báo / Bản tin / Thư viện** (`/thong-bao`, `/news`, `/library`), **Danh bạ** (`/contacts`),
  **QR & Shortlink** (`/links`, `/s/<code>`).
- **Điểm danh công khai** (`/diem-danh`, `/diem-danh/<code>`): người không có tài khoản bấm nút
  theo "đợt"; chống trùng theo (đợt, mã thiết bị localStorage), ghi IP để báo trùng; quản trị ở
  `/admin/diem-danh` (quyền `sys`).
- **Hệ thống**: tài khoản & vai trò (`/roles`), đơn vị (`/admin/units`), ủy quyền
  (`/admin/delegations`), danh mục (`/admin/module-categories`), nhật ký (`/logs`),
  DB tool (`/admin/db-tool`), cập nhật bản vá qua git (`/admin/system/update`).

**Tech stack:**
- Python **Flask 3.1.3** + Flask-SQLAlchemy 3.1.1 (SQLAlchemy 2.x), Jinja2, Bootstrap 5.3.2 (CDN),
  SweetAlert2, Chart.js, font Be Vietnam Pro. Phiên bản app: **3.5.0** (`config.py:APP_VERSION`,
  `version.txt`, `app.py` context `version="3.5.0"`).
- DB: **SQLite** khi dev (`pc06_system.db` ở root) / **MySQL-MariaDB** qua PyMySQL khi prod
  (`DATABASE_URL`), chọn tự động trong `storage.py`.
- openpyxl, pandas, python-docx, pymupdf (đọc PDF), qrcode, phonenumbers, pyotp (2FA TOTP),
  APScheduler (watchdog hạn nộp), google-api-python-client (Google Forms/OAuth).
- Local: `.venv` (Python 3.14.7) đã ghi trong tài liệu **không còn tồn tại** trên máy này —
  `start_server.sh` sẽ tự tạo lại khi chạy. Env test đã cài sẵn (10/09/2026):
  `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python` (3.13, đủ requirements + pytest).
  Prod yêu cầu Python ≥ 3.9 (khuyến nghị 3.11/3.12 — `DEPLOY_CPANEL.md`).

**Entrypoint:**
- Dev: `app.py` (chạy trực tiếp, host/port qua `PC06_HOST`/`PC06_PORT`, mặc định 127.0.0.1:5000),
  hoặc `./START_SERVER_MAC.sh` → forward sang `start_server.sh` (tự tạo venv, tự migrate).
- Prod cPanel: `passenger_wsgi.py` → import `app` của `app.py` (set `PC06_PASSENGER=1`).

**DB & config:**
- ORM toàn bộ trong `models.py` (~32 bảng). Schema migrate **tự động lúc khởi động**
  qua `utils.apply_migrations(app)` (gọi trong `init_db`, `app.py` dòng ~386); `migrate.py`
  chạy bổ sung backfill runtime (task_item/participant/submission) — có `--dry-run`.
- Config qua biến môi trường: mẫu đầy đủ trong `.env.example`; đọc trong `config.py`;
  `env_loader.py` nạp `.env` (Passenger không override). SECRET_KEY tự sinh và lưu file
  `.secret_key` (`security_utils/runtime_security.ensure_persistent_secret_key`).
- Dữ liệu mutable (uploads/task_files/library_files/backups/logs/tmp) gom về 1 data root
  qua `PC06_DATA_DIR` (`storage.py:build_storage_layout`) — trên prod đặt NGOÀI public_html.

---

## 2. Kiến trúc & cấu trúc quan trọng

**Lõi app:**
- `app.py` — bootstrap: layout thư mục + DB URI (`storage.py`), logging file
  (`logs/app.log`, rotate 10MB), các `before_request`: rate limit (240 req/phút, API 120),
  kiểm tra đăng nhập + timeout phiên, session integrity (session_version, user-agent hash,
  IP network hint → step-up), re-auth 15 phút cho endpoint nhạy cảm (`SENSITIVE_REAUTH_ENDPOINTS`),
  force HTTPS (308, `PC06_FORCE_HTTPS`), CSRF mọi POST (header `X-CSRF-Token` hoặc form
  `csrf_token`); `after_request` security headers + CSP + HSTS. Đăng ký 10 blueprint, khởi động
  APScheduler (`services/task_scheduler.start_task_scheduler`, tắt bằng `PC06_TASK_SCHEDULER=0`).
  Route tải file an toàn: `/dl_file/<fn>`, `/preview_file/<fn>`.
- `config.py` — toàn bộ hằng số bảo mật/nghiệp vụ đọc từ env (session, lockout đăng nhập
  5 lần → khóa 15 phút, giới hạn upload 16MB + `MAX_FORM_PARTS=10000`, cờ bật tính năng
  `ADMIN_DB_RESET_ENABLED`, `WEB_GIT_PULL_ENABLED`, `GOOGLE_FORMS_ENABLED`, `GOOGLE_OAUTH_*`).
- `storage.py` — phân giải data root/DB URI; chặn SQLite khi chạy dưới Passenger.
- `utils.py` (64KB) — `init_db`, `apply_migrations` (migrate schema thủ công, dòng ~394),
  **`render_auto_template`** (chọn `xxx_mobile.html` nếu có, fallback desktop — cơ chế template kép),
  `push_notif`/`push_global_notif`, mô hình phân quyền (`has_module_permission` theo tier
  view/process, `normalize_permission_payload`), sinh username theo đơn vị, `eval_f` (công thức
  số liệu), `validate_password_strength`, `seed_units_from_users`.
- `permissions.py` — `load_current_authz()` tính lại quyền từ DB mỗi request (không tin session),
  `current_is_admin()`.
- `security_utils/` — `runtime_security.py` (secret key bền, fingerprint, `resolve_safe_path`
  chống path traversal), `security_helpers.py` (`get_client_ip`, `log_security_event`).

**Blueprints (routes/):**
- `routes/auth.py` (`auth_bp`) — `/login`, `/logout`, `/password`, `/reauth`, 2FA `/login/two-factor`,
  `/security/two-factor` (TOTP mã hóa Fernet trong `User.totp_secret_encrypted`).
- `routes/admin.py` (`admin_bp`, 90KB) — dashboard `/admin`, `/roles` (vai trò + tài khoản, import
  Excel, reset mật khẩu bulk theo tài khoản đã chọn **và theo đơn vị tích chọn**
  `/admin/users/reset-password-by-units`), `/admin/units`, `/admin/delegations`, `/logs`, `/admin/db-tool`,
  `/admin/db-manage`, `/admin/module-categories`, `/admin/categories` (admin danh mục),
  `/admin/system/update` + `/admin/system/git-pull` + `/admin/git/*`, `/admin/styleguide`
  (trang tra cứu design system, chỉ admin), `/admin/deadline-watchdog/run`.
- `routes/tasks.py` (`tasks_bp`, 34KB) — `/tasks` (danh sách + wizard tạo việc), chi tiết
  `/tasks/<id>`, nộp báo cáo `/tasks/<id>/submit_report`, trả lại, bình luận, ma trận tiến độ,
  `/tasks/import-drafts*` (nháp import Excel/Google Form/blueprint), `/tasks/outline-parse`,
  `/tasks/report-dashboard`, xuất Word `/tasks/<id>/export-outline.docx` (⚠️ có 2 route trùng URL —
  xem mục 6), `/tasks/search`, tổng hợp form.
- `routes/portal.py` (`portal_bp`, 52KB) — `/thong-bao` (+edit/delete), `/news`, `/library`,
  `/notifications`, `/contacts*` (import/preview-import/template/bulk).
- `routes/outline.py` (`outline_bp`) — luồng "Giao việc theo đề cương": `/outline-editor`,
  `/api/parse-outline`, `/api/save-outline`, `/outline-giao-viec`, `/api/outline-assignees`,
  `/api/create-outline-task`.
- `routes/api.py` (`api_bp`) — `/api/notifications*`, `/api/performance-stats`, `/api/categories*`,
  `/api/category-picker`, `/api/custom-satellite-points*` (điểm vệ tinh bản đồ),
  `/api/diagnose-db`, `/api/resolve-maps-url`.
- `routes/shortlink.py` (`shortlink_bp`) — `/links`, `/s/<code>` (redirect + đếm click),
  `/download-qr/<code>`.
- `routes/health.py` (`health_bp`) — `/health`, `/ping` (public, miễn HTTPS redirect).
- `routes/checkin.py` (`checkin_bp`) — Điểm danh: public `/diem-danh`, `/diem-danh/<code>`,
  `POST /diem-danh/submit` (3 endpoint đã thêm vào `public_endpoints` ở `app.py`, **vẫn bắt buộc
  CSRF** — không nằm trong `csrf_exempt_endpoints`) + khối quản trị `/admin/diem-danh`,
  `/admin/diem-danh/<id>`, `create|toggle|delete`, `<id>/export.csv` chặn bằng
  `permissions.require_perm('sys', 'view'|'process')`.
- `routes/google_auth.py` (`google_auth_bp`) — `/auth/google`, `/auth/google/callback`.

**Services (services/):** phần nặng nhất là phân hệ task —
- `task_pages.py` (72KB, render/submit `_submit_task_report_v2`), `task_runtime_sync.py` (đồng bộ
  TaskParticipant/Submission khi tạo việc), `task_admin.py`, `task_workspace_views.py`,
  `task_import_drafts.py` (88KB), `task_import_ai.py` ở root (110KB, phân tích AI file import).
- `task_da06.py` — biểu mẫu chuyên biệt "Báo cáo Đề án 06 tháng…": nhận diện 3 nhóm người báo cáo
  (Sở/ngành theo 9 quy tắc, Tổ công tác cấp xã, Trung tâm PVHCC) và dựng biểu mẫu theo nhóm.
- `task_google_forms.py` / `task_google_forms_v2.py` — tích hợp Google Forms (tạo/sync form,
  kéo kết quả về TaskSubmission).
- `task_report_aggregate.py` (tổng hợp + `export_outline_docx`), `task_report_views.py`,
  `task_report_schema.py`, `task_synthesis.py` (văn bản tổng hợp), `task_form_fields.py` +
  `task_form_aggregation.py` (khung FORM).
- `outline_engine.py` (41KB, phân tích đề cương Word/PDF), `outline_rows.py`, `outline_submission.py`.
- `deadline_watchdog.py` + `task_scheduler.py` — APScheduler nền cảnh báo sát/qua hạn.
- `global_search.py`, `task_permissions.py`, `task_guards.py` (`can_view_task(task, session_uid,
  is_admin, ...)` — chữ ký này từng bị gọi sai gây 403, xem mục 6), `task_scope.py`, `task_modes.py`.

**File root khác:** `outline_parser.py` (docx/txt → cây JSON đa tầng), `google_forms.py`,
`task_blueprints.py` (workflow blueprint), `report_cycles.py` (chu kỳ báo cáo), `category_helpers.py`
+ `seed_categories.py` (hệ danh mục tập trung Category/CategoryGroup/ModuleRegistry),
`normalize_mysql_collation.py`, `report_templates/` (33 file mẫu), `migrate.py`, `run_tests.py`.

**Frontend:**
- `templates/` — 44 file, cơ chế kép desktop/`_mobile` (13 trang không có bản mobile, fallback
  desktop responsive). Shell: `base.html`, `base_mobile.html`.
- Design system **`pc-*`**: nguồn sự thật `static/css/pc06-premium.css` (token `--pc-*` light+dark,
  component pc-btn/pc-card/pc-table/pc-empty/pc-skeleton, theme Swal `pc-swal-*`).
  Chuẩn mực bắt buộc: `docs/THIET_KE_TONG_GIAO_DIEN_2026.md` (cấm hardcode hex/px mới, cấm
  `alert alert-*` mới, cấm gọi `Swal.fire` trực tiếp — dùng `pcAlert`/`pcConfirm`).
- Thứ tự nạp CSS bị test khóa (pc06-premium.css nạp CUỐI trong cả 2 base, kèm `?v=` để phá cache —
  hiện `pc06-premium.css ?v=1.3.7`, `style.css ?v=4.2.1`, `bdhvs-layout.css ?v=2.2.4`).
- JS custom: `static/js/main.js`, `static/js/category-picker.js`.

**Test:** `tests/` — 36 module, **326 test**. Runner duy nhất: `python3 run_tests.py` (tự ép DB
SQLite tạm + data dir tạm, an toàn khi lỡ chạy trên server prod). Contract test design system:
`tests/test_design_system.py`. CI: `.github/workflows/deploy.yml` — push `main` → job `test`
(chạy `run_tests.py`) → job `web-deploy` (FTP lên host, secrets `FTP_SERVER/USERNAME/PASSWORD`)
**chỉ chạy khi test pass**.

**Git:** remote `https://github.com/NguyenVanThe30081994/PhanMemPC06_Pro.git`, nhánh `main`,
working tree sạch, `main` == `origin/main` (commit cuối `f3103f5` — Subproject M14, 29/08/2026).

---

## 3. Trạng thái triển khai hiện tại

### ✅ Đã xong (có bằng chứng)
- Nền tảng: auth + 2FA TOTP, phân quyền 3 tầng (vai trò chính + vai trò phụ + ủy quyền,
  data-scope đơn vị theo cây `Unit`), CSRF/session security/lockout/rate limit đầy đủ.
- Phân hệ task theo thiết kế cuối `THIET_KE_CHUC_NANG_TASK_CUOI.md` **Pha 1**: `task_mode`
  (OUTLINE/FILE) hoạt động; mô hình Task→TaskItem→TaskAssignment→TaskParticipant→TaskSubmission
  (+TaskSubmissionFile, TaskFormField) đã migrate và backfill (`migrate.py`); giao việc theo đề
  cương từ file Word thật (ĐA06) chạy tròn vẹn 14/14 bước kiểm tra (26/08/2026,
  `docs/nghien-cuu-giao-viec-test-dau-vao-da06-2026.md`).
- Import việc từ Excel + AI (`task_import_drafts`, `task_import_ai`), Google Forms v2,
  tổng hợp + xuất Word outline, deadline watchdog nền.
- Thông báo/Danh bạ/QR-Shortlink/Logs/DB tool/System update.
- **Làm mới giao diện toàn hệ thống** HOÀN TẤT: giai đoạn 1 (subproject 1→6 + SA→SG), giai đoạn 2
  (M1–M6, 28/08), M7–M14 (28–29/08) — đủ 14 subproject, đã commit hết, design system `pc-*`
  chốt theo `docs/THIET_KE_TONG_GIAO_DIEN_2026.md`.
- **Cải tổ toàn diện Giao diện Lưới Nổi Khối & Quản Trị Hệ Thống (12/11/2026)**:
  1. *Khắc phục lỗi nạp đề cương văn bản*: Khắc phục lệch Jinja2 block (`scripts` & `extra_head`), kiểm thử nạp văn bản Word/PDF thành công; bóc tách cấu trúc La Mã (I, II), mục số (1, 2) và gạch đầu dòng (- / +).
  2. *Rà soát & loại bỏ sạch câu chữ chú thích AI*: Xóa bỏ triệt để các câu tự trần thuật kiểu "Hệ thống tự động bóc tách...", "Hỗ trợ định dạng...", "Đang cấu trúc hóa...". Thiết kế chuẩn mực công vụ cấp tỉnh.
  3. *Tái thiết kế giao diện dạng Lưới Chức Năng Nổi Khối (Grid Launchpad Hub)*: Ẩn sidebar dọc bên trái, mở rộng 100% full-width.
  4. *Xử lý triệt để sự bất hợp lý giữa Menu trên cùng và Lưới chức năng*:
     - **Bỏ 100% thanh menu ngang trên cùng (`nav-top-pills`) khỏi Header**: Vì Trang chủ ĐÃ LÀ BÀN LÀM VIỆC LƯỚI CHỨC NĂNG, việc đặt thêm menu ngang trên đỉnh là hoàn toàn thừa thãi, lặp lại và gây nhiễu thị giác.
     - Header trở về chuẩn mực tối giản: Chỉ giữ Logo nhận diện, Chuông cảnh báo, và Hồ sơ tài khoản.
     - Cơ chế một chạm (One-Click Return): Khi vào các trang con (`/tasks`, `/dossiers`, `/contacts`...), trên Header chỉ xuất hiện duy nhất nút `[ ⊞ Bàn làm việc ]` cạnh Logo để quay về Lưới trung tâm.
  5. *Tinh gọn triệt để Bàn làm việc Lưới chức năng (Launchpad Grid) theo chỉ đạo*:
     - **Bỏ hoàn toàn ô "Ma trận tiến độ nộp"**: Tiến độ đã tích hợp trực tiếp trong trang quản lý công việc và báo cáo, không xé lẻ thành ô lạ hoắc.
     - **Đổi "Thu thập biểu mẫu" thành chuẩn danh xưng "Giao việc theo biểu mẫu"** (`/tasks`).
     - **Bỏ chú thích "2 cấp" ở Danh bạ**: Đổi thành chuẩn mực ngắn gọn "Danh bạ cơ quan" (`/contacts`).
     - **Gom toàn bộ các ô quản trị vụn vặt (Tài khoản, Đơn vị, Nhật ký) thành DUY NHẤT 1 Ô "Quản trị hệ thống"** (`/admin/system-center`).
     - Bàn làm việc chỉ còn đúng 7 ô nghiệp vụ cốt lõi, rõ ràng, mạch lạc, không chú thích thừa.
  6. *Chuẩn hóa dứt điểm Cơ cấu Đơn vị Cấp Tỉnh Tuyên Quang 2026 (Nghị quyết HĐND tỉnh & Đề án 06)*:
     - **Loại bỏ 100% các đơn vị cũ đã giải thể/sáp nhập**: Xóa sạch Sở TT&TT, Sở LĐ-TB&XH, Sở TN&MT, Sở KH&ĐT, Sở GTVT, Sở NN&PTNT.
     - **Cập nhật chuẩn xác cơ cấu các Sở ngành mới**: Sở Nông nghiệp và Môi trường, Sở Khoa học và Công nghệ (bao gồm viễn thông, hạ tầng số), Sở Nội vụ (bao gồm an sinh xã hội), Sở Tài chính (bao gồm đầu tư), Sở Xây dựng (bao gồm giao thông), Sở Dân tộc và Tôn giáo, Trung tâm Phục vụ hành chính công, Bảo hiểm xã hội tỉnh, Thuế tỉnh, Ngân hàng Nhà nước chi nhánh khu vực 4.
     - **Sửa đơn vị "Hệ thống" (`hethong`)**: Cập nhật sang cấp Tỉnh (`level = 'province'`), chấm dứt việc hiển thị sai cấp Xã.
     - Đồng bộ toàn bộ 535 tài khoản `User` và danh mục `CategoryItem` (`contact_unit`).
  7. *Rà soát thực chất & Thanh lọc toàn bộ Chức năng Quản trị Hệ thống*:
     - **Thực tế kiểm tra dữ liệu**:
       * `Ủy quyền điều hành` (`/admin/delegations`): 0 bản ghi trong CSDL, không phù hợp thực tế phân công công vụ ĐA06 -> **ĐÃ GỠ BỎ**.
       * `Danh mục dùng chung cũ` (`/admin/categories`): 0 bản ghi (bảng Category cũ rỗng) -> **ĐÃ GỠ BỎ**.
       * `Quét ngay Deadline Watchdog`: Tiến trình quét hạn đã chạy ngầm tự động qua APScheduler nền, không cần nút bấm thủ công -> **ĐÃ GỠ BỎ**.
       * `Cập nhật bản vá hệ thống qua Web` (`/admin/system/update`): Chức năng kỹ thuật Git/Zip rủi ro cao -> **ĐÃ GỠ KHỎI GIAO DIỆN CÔNG VỤ**.
     - **Giữ lại 5 chức năng CỐT LÕI THỰC SỰ HOẠT ĐỘNG 100%**:
       1. *Tài khoản và vai trò* (`/roles`): 535 tài khoản, 4 vai trò chuẩn 4 tầng, reset mật khẩu hàng loạt theo đơn vị.
       2. *Đơn vị hành chính* (`/admin/units`): 268 đơn vị (19 Sở chuẩn 2026, 124 Xã, 124 CAX) — Bỏ chữ "2 cấp" rườm rà.
       3. *Thiết lập danh mục hệ thống* (`/admin/module-categories`): 9 nhóm danh mục và 384 danh mục nghiệp vụ chuẩn.
       4. *Nhật ký hoạt động (Audit Logs)* (`/logs`): Tra cứu vết đăng nhập và an ninh thời gian thực (bảng `SystemLog`).
       5. *Sao lưu cơ sở dữ liệu* (`/admin/db-tool`): Tải file backup CSDL an toàn.
  8. *Khắc phục triệt để vấn đề Cache & Khởi động lại Server*:
     - Bật `app.config['TEMPLATES_AUTO_RELOAD'] = True` trong `app.py`.
     - Khởi động lại hoàn toàn Server daemon (task-2504) trên cổng 5001.
     - Chạy lại 100% test suite: **304/304 test PASS (36.7s)**.
- Đã sửa 4 nhóm lỗi 06/08/2026 (`BAO_CAO_SUA_LOI_20260806.md`): `/admin` 404, sidebar toggle,
  layout reauth, class CSS dark mode.
- Đã sửa 3 lỗi ĐA06 26/08: L1 (403 export do gọi sai chữ ký `can_view_task`), L2 (thiếu import
  `export_outline_docx`), L3 (đồng bộ 302/403) trong `routes/tasks.py` + `tests/test_task_outline_word_export.py`.
- **Reset mật khẩu hàng loạt theo đơn vị** (02/09/2026): thêm endpoint
  `POST /admin/users/reset-password-by-units` (`routes/admin.py:reset_users_password_by_units`,
  guard `can_module('user','process')`, đã đưa vào `SENSITIVE_REAUTH_ENDPOINTS` trong `app.py`).
  Nhận `unit_values` (JSON list stable-value danh mục Đơn vị) + `temporary_password`/`confirm_password`;
  reset mọi tài khoản thuộc các đơn vị tích chọn, giữ nguyên `admin`, bật `must_change_password`,
  tăng `session_version`. UI: modal "Reset theo đơn vị" (danh sách checkbox đơn vị kèm số tài khoản)
  trên cả `templates/roles.html` + `roles_mobile.html`; đồng thời khôi phục thanh tác vụ hàng loạt
  desktop (nút "Reset mật khẩu đã chọn" + "Xóa đã chọn" vốn bị orphan). Helper `_build_unit_user_query`
  khớp `unit_area` theo MỌI biểu diễn (stable/value/code/name) + `unit_key`. Test mới
  `tests/test_admin_bulk_reset_by_units.py` (7 case).

- **QR & liên kết: sửa file nguồn không đổi QR/link** (10/09/2026): `edit_link`
  (`routes/shortlink.py`) khóa `short_code` (không đọc từ form) — chỉ đổi `original_url`
  + metadata, nên mã QR đã in/vẫn trỏ đúng sau khi sửa; thêm nút "Sửa" + modal trên
  `shortlinks.html` + `shortlinks_mobile.html` (trước đó hoàn toàn không có UI sửa);
  chặn ký tự lạ ở `custom_code` khi tạo; ghi `log_action` old→new.
  **Vá lỗi nền `_normalize_target_url`** (test mới phát hiện): `javascript:alert(1)` bị
  prefix thành `https://javascript:alert(1)` lọt validation → Nay chặn mọi scheme lạ
  khi link thiếu `http(s)://`, vẫn cho `host:8080/x`. Test mới
  `tests/test_shortlink_edit_target.py` (6 case) ✅ ĐÃ CHẠY PASS TOÀN BỘ 10/09/2026 bằng
  `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py` → **295 test / 2 fail
  nền cũ** (test_task_synthesis). Local KHÔNG còn `.venv`; dùng env cô lập pc06 này.
- **Triển khai đường vào PDF và tổng hợp theo dòng (14/09/2026):** bộ đọc PDF dạng bảng
  lấy bảng làm nguồn chuẩn, loại bỏ text tuyến tính nhiễu, giữ nhóm/STT và 7 cột nguồn;
  file phụ lục thật trả đúng **75 dòng / 11 nhóm**. API editor cũ `/api/parse-outline` cũng
  nhận `.pdf` và dựng lại cây 11 section / 75 mục. Wizard lưu deadline ISO đầy đủ theo từng
  `TaskItem` và giao diện chi tiết hiển thị “Hạn riêng”. Các mốc chỉ ghi dạng `Thường xuyên`,
  `2026–2027` hoặc `15/7` không đủ dữ kiện nên vẫn giữ nguyên ô nguồn và dùng hạn Task chung.
- **P0 quy mô 124 đơn vị (14/09/2026):** thêm fixture chính thức 124 mã/tên đơn vị (117 xã,
  7 phường), seed idempotent tài khoản `TEST124_<mã>` và runner cô lập
  `scripts/run_tuyen_quang_124_p0.py`. Chạy trực tiếp với file phụ lục thật: 75 đầu mục,
  9.300/9.300 phân công, mỗi đơn vị 75/75; 124/124 tài khoản mở được trang đơn vị; một đơn vị
  tiếp nhận/nộp thành công; quản trị mở dashboard và xuất DOCX thành công. Đã xử lý nút thắt
  P0 do cache nhận diện đơn vị, cache resolver danh mục theo request và truy vấn submission theo
  lô, giảm trang quản trị xuống 5,572 giây và trang đơn vị mẫu 0,715 giây trong DB SQLite test.
- **Dashboard định kỳ theo OUTLINE (14/09/2026):** tổng hợp cả assignment cấp Task và cấp
  TaskItem, nhóm theo đơn vị; mỗi assignment có thể hiển thị thêm tên dòng nhiệm vụ. Đã thêm
  regression test cho PDF metadata/deadline và dashboard assignment theo TaskItem.
- **Điểm danh công khai (08/10/2026):** chức năng mới `routes/checkin.py` + 2 bảng
  `check_in_session` (đợt: name/code/is_open/start_at/end_at/note) và `check_in`
  (UniqueConstraint `session_id`+`device_token`, `device_kind`, `ip`, `ip_network`,
  `user_agent`, `duplicate_attempts`, `last_attempt_at`, `last_ip`). Trang
  `/diem-danh` và `/diem-danh/<code>` là public thật (3 endpoint trong `public_endpoints`)
  nhưng **vẫn qua `enforce_csrf_protection`** — token do chính trang cấp, response gắn
  `Cache-Control: no-store` để token không bị cache. Chống trùng: khóa `(đợt, device_token)`;
  device token do trình duyệt sinh (crypto.randomUUID, lưu localStorage `pc06_checkin_device`);
  nếu browser chặn localStorage thì rơi về khóa HMAC(ip+UA) với `device_kind='ip_fallback'`
  → hai người dùng chung IP cơ quan vẫn điểm danh được, chỉ thiết bị bấm lại mới báo trùng.
  Bấm lại: message "đã điểm danh lúc …, lần bấm thừa thứ N/5", cộng dồn `duplicate_attempts`,
  ghi `last_ip` (phát hiện đổi IP), `log_security_event('checkin_duplicate')`; quá
  `CHECKIN_MAX_DUPLICATE_ATTEMPTS` (mặc định 5, env) thì chặn hẳn ghi + log
  `checkin_duplicate_blocked`. Trang quản trị `/admin/diem-danh*` dùng
  `permissions.require_perm('sys','view'|'process')`, có tạo đợt (giờ mở/khóa tùy chọn),
  mở/khóa, xóa (cascade lượt), bảng kết quả kèm badge "Chung IP"/"bấm trùng" và xuất CSV
  (`utf-8-sig`). Menu "Điểm danh" đã thêm vào `base.html` (sidebar desktop + offcanvas) và
  `base_mobile.html`. **Lưu ý lịch sử:** module `attendance` cũ từng bị xóa 06/08/2026 vì rà soát
  bảo mật (B1 — ghi ẩn danh không CSRF); bản này khác ở chỗ giữ CSRF, giới hạn theo đợt, có
  rate limit và chỉ ghi dữ liệu tối thiểu. Test mới `tests/test_checkin_public.py` (21 case)
  + 4 contract design system; đã verify trên trình duyệt thật (public: bấm → thành công →
  bấm lại → báo trùng; admin: tạo đợt qua form `datetime-local`, trạng thái "Chưa tới giờ",
  kết quả hiện IP + 1 lượt + 1 bấm trùng).

### 🚧 Đang dở / cần xử lý
- **Kiểm tra trực tiếp giao việc với file phụ lục (14/09/2026):** E2E lõi sau khi dùng 75
  dòng bảng tạo được 75 TaskItem và 75 assignment; đơn vị mở trang/nộp báo cáo; quản trị xem
  chi tiết/dashboard và xuất DOCX thành công. Smoke route thật cũng xác nhận wizard 75 dòng,
  editor cũ 11 section/75 mục. E2E POST `/tasks` trực tiếp từ payload 75 rows tạo đúng 75
  TaskItem, 75 assignment và lưu 33 deadline đầy đủ theo dòng. Đã test browser thật trên DB
  cô lập: admin nhìn thấy 75 lượt giao + ma trận tiến độ; tài khoản đơn vị nhìn thấy 75 đầu mục,
  hạn riêng, nút tiếp nhận, vùng nội dung báo cáo, tệp minh chứng và gửi báo cáo. Ảnh kiểm thử
  lưu tại `ui-admin-assignment.png`, `ui-admin-progress-matrix.png`, `ui-reporting-unit.png`.
- **Đã hoàn tất đánh giá P0 124 xã/phường (14/09/2026):** runner đã tạo bộ tài khoản test và
  chạy đủ ma trận 9.300 assignment trên DB cô lập; JSON credential/report và DOCX kết quả nằm
  trong thư mục `data_dir` của lượt chạy. Đây là dữ liệu test, chưa seed vào production.
- **Database local khi kiểm tra:** chỉ có tài khoản bootstrap admin, chưa có task/assignment/
  submission/unit catalog thực tế; phần phân giải cơ quan chủ trì sang đơn vị phải kiểm tra
  thêm trên dữ liệu triển khai thật.
- **Suite 325 test đã PASS 100% (12/11/2026):** Đã sửa dứt điểm 2 lỗi nền cũ
  `test_task_synthesis` (trong `services/task_report_aggregate.py`: đọc `synthesis_content`
  và loại bỏ tiền tố thừa `assign_N: ` khi xuất đoạn văn bản thuần). Toàn bộ 325 test đã pass sạch.
  CI/CD pipeline deploy đã được mở khóa hoàn toàn.
- **Bổ sung danh mục 19 Sở/Ban/Ngành cấp tỉnh chuẩn vào CSDL (12/11/2026):** cập nhật
  `seed_categories.py` bổ sung đầy đủ Sở Tư pháp, Sở Y tế, Sở GD&ĐT, Sở Nội vụ, Sở Tài chính,
  Sở KH&CN, Sở Công thương, Sở Nông nghiệp & Môi trường, Thuế tỉnh, BHXH tỉnh, Ngân hàng Nhà nước,
  Trung tâm PVHCC... Tăng tỷ lệ tự động nhận diện đơn vị chủ trì từ 0% lên 83.2% trên toàn văn bản đề cương ĐA06 2026.
- **Nâng cấp Bóc tách Đề cương Thông minh theo Heading (12/11/2026):** `services/outline_engine.py`
  và `services/outline_rows.py` bổ sung tham số `group_by_heading=True` (chế độ gom theo mục).
  Thay vì băm nát văn bản thành 95 dòng vụn vặt, hệ thống gom gọn thành **36 mục cấu trúc chuẩn**
  của bản báo cáo tỉnh, toàn bộ các gạch đầu dòng con được giữ nguyên làm hướng dẫn chi tiết của mục đó.

### 🚧 Đang dở / cần xử lý
- **Kiểm tra trực tiếp giao việc với file phụ lục (14/09/2026):** E2E lõi sau khi dùng 75
  dòng bảng tạo được 75 TaskItem và 75 assignment; đơn vị mở trang/nộp báo cáo; quản trị xem
  chi tiết/dashboard và xuất DOCX thành công.
- **Đã hoàn tất đánh giá P0 124 xã/phường (14/09/2026):** runner đã tạo bộ tài khoản test và
  chạy đủ ma trận 9.300 assignment trên DB cô lập.
- **2 route trùng URL** `/tasks/<id>/export-outline.docx`: `routes/tasks.py:174`
  (`task_export_outline_docx`) và `routes/tasks.py:944` (`export_outline_task_word`) — hiện
  `task_export_outline_docx` đã hỗ trợ đầy đủ `synthesis_content` và xuất DOCX sạch. Cần dọn gọn
  về đúng 1 route thống nhất.
- CI/CD: vì job `test` chạy `run_tests.py` và 2 test synthesis fail chắc chắn → pipeline đỏ,
  `web-deploy` (needs: test) bị chặn khi push mới (trạng thái Actions thực tế: cần xác nhận —
  không có `gh` CLI trên máy).
- Smoke thủ công light/dark trên trình duyệt thật cho các bump CSS M5→M14 (changelog ghi
  "verify trực quan" từng phần; M5 ghi rõ còn nợ smoke).

### ⬜ Chưa làm (đã ghi trong tài liệu thiết kế, chưa có code)
- **Pha 3 — `task_mode = FORM` hoàn chỉnh** (form builder, renderer động, export Excel, dashboard
  tổng hợp): khung `TaskFormField` + `services/task_form_fields.py` + `task_form_aggregation.py`
  + trang `task_form_aggregation.html` đã có nhưng chưa phải luồng chính (cần xác nhận mức độ
  dùng được so với mục tiêu "tổng hợp Excel tự động" của thiết kế).
- **Refactor `TaskParticipant`**: thiết kế cuối (`THIET_KE_CHUC_NANG_TASK_CUOI.md` mục 11.3)
  đánh giá trùng vai trò với `TaskAssignment`, đề nghị giảm vai trò/loại bỏ dần — chưa làm.
- Deadline sai định dạng ở `/api/create-outline-task` hiện bị bỏ qua âm thầm — khuyến nghị trả 400.
- Trang mức B trong bản đồ màn hình (`docs/THIET_KE_TONG_GIAO_DIEN_2026.md` Mục 6: module_categories,
  units, delegations, logs, db_tool, system_update, thong_bao, shortlinks) — chỉ migrate khi có
  lô sửa chạm đến, không mở lô riêng.

---

## 4. Việc tiếp theo cần làm (NEXT STEPS)

0. **Đã triển khai P0 bộ đọc PDF theo bảng chuẩn**; cần mở rộng kiểm thử với các mẫu PDF
   không có đường viền/bảng scan và nhiều bảng không có cột STT.
1. **Đã lưu deadline đầy đủ theo dòng**; bước tiếp theo là chuẩn hóa metadata chu kỳ/mốc
   không đủ ngày và tách rõ người thực hiện với đơn vị phối hợp/người theo dõi.
2. **Đã sửa dashboard tổng hợp** cho assignment cấp Task + TaskItem; cần bổ sung tiếp chỉ số
   thiếu hạn, chất lượng và ngoại lệ theo nhóm nhiệm vụ.
3. **[ĐÃ XONG 12/11/2026] Fix dứt điểm CI/CD, Nâng Cấp Bóc Tách Đề Cương & Giao Diện A4 Trực Quan (Word/Google Docs Comment Style)**:
   - **Sửa 2 test `test_task_synthesis`**: Cập nhật `services/task_report_aggregate.py` đọc `synthesis_content` và loại bỏ nhãn thừa `assign_N: `. Mở khóa CI/CD GitHub Actions.
   - **Bổ sung 19 Sở, Ban, Ngành cấp tỉnh chuẩn**: Reseed vào CSDL local `pc06_system.db`, nâng tỷ lệ tự động nhận diện cơ quan chịu trách nhiệm từ 0% lên **83.2%** (79/95 mục).
   - **Nâng cấp thuật toán bóc tách đề cương theo Heading**: Cập nhật `services/outline_engine.py` và `services/outline_rows.py` bổ sung cờ `group_by_heading=True` (gom gọn 95 dòng vụn về **36 mục cấu trúc chuẩn**).
   - **Triển khai Giao diện Giao việc Tờ A4 Sống + Khung Phân Công Comment Rail (Thay thế hoàn toàn bộ phân tích cũ)**:
     - Route chính thức: `/outline-giao-viec` (`templates/outline_assign.html`).
     - **Thay thế hoàn toàn cách quét cũ**:
       * Nút chính nổi bật trên thanh công cụ `/tasks`: `Giao việc Đề cương A4 mới` (trỏ trực tiếp vào `/outline-giao-viec`).
       * Submenu của "Công việc" đặt ngay mục đầu tiên: `Giao việc Đề cương A4`.
       * Trong wizard tạo việc (`#createTaskModal`): Khi click vào "Theo đề cương văn bản" hoặc bấm Tiếp tục, hệ thống chuyển hướng ngay sang `/outline-giao-viec`, gỡ bỏ hoàn toàn bộ phân tích chia dòng vụn vặt cũ.
     - Tích hợp **Phân loại kiểu báo cáo** (Đột xuất, Định kỳ Tuần/Tháng/Quý/Năm, Theo mốc, Thường xuyên) vào modal tạo việc và backend `/api/create-outline-task`.
     - Cho phép click chọn từng đoạn trên trang A4 để bật thẻ gán bên phải; hỗ trợ gán theo Khối Preset (Toàn tỉnh, Khối Sở, 124 Xã), gán theo Đơn vị / Vai trò / Cán bộ; nút "Tự động áp dụng gợi ý AI".
   - **Bỏ hoàn toàn hình thức Nộp file tự do (`FILE` mode)** trên wizard tạo việc; tập trung vào 2 hình thức: `OUTLINE` (văn bản hành chính) và `FORM` (biểu mẫu số liệu Excel).
   - **Chuẩn hóa & Làm sạch toàn bộ CSDL Local (`scripts/admin/cleanup_and_standardize_local_db.py`)**:
     * Bảng `Unit`: Giữ đúng 268 đơn vị (1 Hệ thống, 19 Sở Ban Ngành, 124 UBND Xã, 124 Công an Xã). Xóa sạch toàn bộ 267 bản ghi thừa `tq_*`.
     * Bảng `CategoryItem` (`contact_unit`): Xóa sạch các mục generic cấp huyện cũ ('Công an huyện', 'Công an thị xã', 'Công an thành phố', 'Phòng PC06'...), đồng bộ 100% 267 đơn vị chuẩn 2 cấp.
     * Bảng `User`: Chuẩn hóa 535 tài khoản (1 admin hệ thống, 19*2=38 cán bộ cấp tỉnh, 124*2=248 cán bộ UBND xã, 124*2=248 cán bộ CAX). Mỗi đơn vị có 1 Quản trị (`admin_*`) và 1 Cán bộ báo cáo (`bc_*`). Mật khẩu: `TuyenQuang@2026`, admin: `Dancu@123`.
   - **Nâng Cấp Đột Phá Thẻ Phân Công Đơn Vị (`templates/outline_assign.html` & `routes/outline.py`)**:
     * **Bộ chuyển đổi chế độ kép (Dual-Mode)**: `[🏢 Theo Đơn Vị]` vs `[👤 Theo Cán Bộ]`.
     * **4 Nút Preset gán nhanh 1-Click**: `🌐 Toàn Tỉnh (Sở + Xã)`, `🏛️ 19 Sở Ban Ngành`, `🏡 124 UBND Xã/Phường`, `👮 124 Công an Xã`.
     * **Tabs phân cấp chính quyền 2 cấp**: `🏛️ Sở Ngành (19)`, `🏡 UBND Xã (124)`, `👮 Công an Xã (124)` và tương ứng cho Cán bộ.
     * **Bộ lọc tức thì (Instant Search)**: Gõ tên xã, sở, username hoặc tên cán bộ lọc ngay không độ trễ.
     * **Thao tác hàng loạt**: Nút `[Chọn tất cả]` và `[Bỏ chọn]` theo từng tab.
     * **Hiển thị Badge Tags**: Phân màu rõ ràng theo Đơn vị, Khối và Cán bộ; kèm nút `×` xóa nhanh và nút `[Xóa hết]`.
   - **Tối Giản Hóa Toàn Diện Màn Hình `/tasks` (`templates/tasks_rebuild.html`)**:
     * **1 Nút Duy Nhất**: Thay thế toàn bộ cụm nút rườm rà (filter pills, attention/my/managed buttons) bằng **1 Nút Tạo việc duy nhất** `[+ Tạo công việc mới]`.
     * **Modal Tạo Việc 2 Hướng**: Popup chọn đúng 2 hướng rõ ràng:
       1. `Giao theo đề cương`: Mở bàn giao việc đề cương trực quan trên tờ A4 (`/outline-giao-viec`).
       2. `Giao theo biểu mẫu`: Mở wizard cấu hình biểu mẫu chỉ tiêu số liệu Excel (`FORM`).
     * **Bảng Danh Sách Công Việc Chuẩn (`pc-table`)**: Hiển thị bảng dạng dòng gọn gàng gồm đúng các cột yêu cầu: `#` (STT), `Tên việc`, `Đơn vị giao`, `Thời gian giao`, `Thời hạn báo cáo`, `Kiểu báo cáo`, `Thao tác ở cuối` (Xem chi tiết, Sửa, Xóa). Gỡ bỏ hoàn toàn nút trùng lặp trong thẻ trống (`pc-empty`), đảm bảo toàn trang chỉ có duy nhất 1 nút tạo việc ở góc trên bên phải.
     * **Bộ Lọc Tìm Kiếm Tức Thì**: Ô tìm kiếm nhanh lọc theo tên việc/đơn vị giao theo thời gian thực.
   - **Mô Hình Phân Cấp & Thẩm Quyền Giao Việc 2 Cấp (Đã triển khai & Test 100%)**:
     * **Nguyên tắc Phân cấp & Phi tập trung**:
       + Bất kỳ đơn vị nào có thẩm quyền đều có thể tạo và giao việc (không có đơn vị độc quyền duy nhất).
       + **Ngang hàng (Peer-to-Peer)**: Sở A có thể giao việc cho Sở B, Sở B có thể giao cho Sở A (phối hợp chuyên đề); Xã A phối hợp Xã B.
       + **Cấp trên giao Cấp dưới**: Cấp Tỉnh (19 Sở, VP UBND tỉnh, Công an tỉnh) giao việc và chỉ tiêu xuống 124 Xã.
       + **QUY TẮC BẮT BUỘC (STRICT ENFORCEMENT)**: Cấp Xã **TUYỆT ĐỐI KHÔNG ĐƯỢC** giao việc cho Cấp Tỉnh / Sở. Cấp Xã chỉ được giao việc nội bộ trong xã hoặc phối hợp đồng cấp.
     * **Cơ Cấu 4 Tầng Tài Khoản Chuẩn Hóa**:
       1. *Quản trị Tỉnh (Super Admin / SysAdmin)*: Lớn nhất toàn hệ thống (`admin`), cấu hình cây tổ chức, danh mục toàn tỉnh, reset tài khoản mọi cấp, xem mọi luồng báo cáo.
       2. *Quản trị Đơn vị (Unit Admin)*: `admin_*` quản lý tài khoản nội bộ đơn vị mình, phân vai trò, không can thiệp đơn vị khác.
       3. *Lãnh đạo Đơn vị (Unit Leader)*: `ld_*` (vai trò `Lãnh đạo đơn vị` - id 8, `p_task_process: 1`), thẩm quyền ký giao việc, phê duyệt báo cáo trước khi phát hành.
       4. *Cán bộ Báo cáo (Unit Staff)*: `bc_*` (`p_task_exec: 1`), tiếp nhận và làm báo cáo (thuyết minh, số liệu, file), không có quyền tự ý tạo việc ra ngoài.
     * **Bảo Vệ Kỹ Thuật (Server-side & Client-side)**:
       + API `/api/outline-assignees` nhận diện `caller_level`: nếu là Cấp Xã, tự động ẩn danh mục các Sở, ẩn các Cán bộ Tỉnh, ẩn preset "Khối 19 Sở" và "Toàn Tỉnh"; tự động bổ sung preset "🏢 Nội bộ đơn vị".
       + Backend POST `/api/create-outline-task` kiểm tra mọi mục gán: nếu người tạo là cấp Xã mà gán cho Sở/Tỉnh -> Trả về lỗi 403 Forbidden chặn ngay lập tức.
       + Fix lỗi `match_standard_role`: ưu tiên exact match toàn bộ danh mục vai trò trước khi substring match để tránh "Quản trị đơn vị" bị nhận diện nhầm thành "Quản trị hệ thống".
    - **Baseline Test**: Toàn bộ test suite **304 test / 0 fail** pass sạch 100% (36.5s) (đã dọn bỏ 25 test điểm danh theo yêu cầu).
    - **Chuẩn Hóa Danh Xưng Phương Án Giao Việc & Cải Tổ Toàn Diện Giao Diện Đề Cương (12/11/2026)**:
      * **Loại bỏ triệt để từ ngữ thô sơ / tự phát**: Xóa sạch toàn bộ cụm từ "đề cương A4", "tờ A4", "như Comment trong Word", "Quét đề cương". Rà soát và tinh giản toàn bộ các cụm từ chú thích dài dòng, rườm rà.
      * **Chuẩn hóa Danh xưng Hành chính Công vụ**:
        + Phương thức 1: **Phân công theo Đề cương văn bản** (hoặc *Giao theo Đề cương văn bản*) — Bóc tách nhiệm vụ từ văn bản chỉ đạo (Kế hoạch, Đề cương báo cáo Word/PDF), phân công cơ quan chủ trì, phối hợp và thu thập báo cáo tổng hợp.
        + Phương thức 2: **Thu thập theo Biểu mẫu số liệu** — Cấu hình bảng chỉ tiêu số liệu Excel trực tuyến → Đơn vị nhập số định kỳ → Hệ thống tự động tổng hợp số liệu toàn tỉnh và xuất Excel.
        + Thuật ngữ thao tác: "Bóc tách nhiệm vụ" (thay cho "Quét đề cương"), "Phân công cơ quan thực hiện" (thay cho "Thẻ phân công"), "Phát hành công việc" (thay cho "Hoàn tất & giao việc").
      * **Cải Tổ Toàn Diện Giao Diện [templates/outline_assign.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/outline_assign.html)**:
        + Kế thừa chuẩn mực `{% extends "base.html" %}`, tích hợp 100% thanh Sidebar, Topbar, Dark Mode, font `Be Vietnam Pro` và Design System `pc06-premium.css`.
        + **Trạng thái 1 - Khung Tiếp Nhận Tệp (Hero Upload Dropzone)**: Khi chưa nạp file, hiển thị card trung tâm sang trọng với vùng kéo thả file (drag & drop) Word/PDF, nút chọn file to đẹp và quy trình 3 bước trực quan. Triệt tiêu hoàn toàn tình trạng 2 cột trắng trống huếch hoác cũ.
        + **Trạng thái 2 - Interactive Workspace**: Khi đã nạp tệp, tự động hiển thị Workspace 2 cột hiện đại: Sticky Toolbar đo tiến độ phân công (%), Cột 1 xem văn bản điện tử công vụ (Nghị định 30/2020/NĐ-CP) có badge tags đơn vị dưới từng mục, Cột 2 bảng điều khiển phân công dính (Sticky Panel) có bộ lọc phân cấp (Sở Ngành, UBND Xã, CAX), 4 presets 1-click, Instant Search và danh sách tags có nút gỡ nhanh.
        + Modal Phát Hành Công Việc dùng chuẩn Bootstrap 5 `#confirmPublishModal` hỗ trợ đầy đủ chu kỳ báo cáo và thời hạn.
    - **Tối Ưu & Tái Cấu Trúc Hệ Thống Theo Yêu Cầu Người Dùng (12/11/2026)**:
      * **Bỏ hoàn toàn Chức năng Điểm danh**: Gỡ bỏ menu "Điểm danh" khỏi `base.html` và `base_mobile.html`, gỡ blueprint `checkin_bp` khỏi `app.py`, xóa các template `checkin.html`, `admin_checkin.html`, `admin_checkin_detail.html` và test suite điểm danh cũ.
      * **Đưa Tiện ích Tạo Mã QR & Rút Gọn Link ra Public Ngoài Màn Hình Đăng Nhập (`/login`)**:
        + Tái cấu trúc trang đăng nhập thành layout 2 cột Split View cân đối, sang trọng.
        + Cột 1: Đăng nhập tài khoản điều hành nội bộ PC06.
        + Cột 2: Tiện ích công khai Tạo mã QR & Link rút gọn (không cần đăng nhập), hỗ trợ dán link -> tạo tức thì mã QR xem trước + nút tải ảnh QR PNG + nút copy link rút gọn 1-click. Endpoint `/api/public/create-qr` công khai và an toàn CSRF.
      * **Thiết Kế Lại Chức Năng Quản Trị — Xây Dựng Trung Tâm Quản Trị Hệ Thống (`/admin/system-center`)**:
        + Bổ sung route `@admin_bp.route('/admin/system-center')` và template `admin_center.html`.
        + Phân nhóm 4 trụ cột nghiệp vụ: (1) Tổ chức & Người dùng, (2) Danh mục nghiệp vụ, (3) An ninh & Giám sát vận hành, (4) CSDL & Bản vá.
        + Thêm liên kết trực tiếp "Trung tâm quản trị" lên vị trí nổi bật đầu tiên trong menu Hệ thống.
      * **Nghiên Cứu Bổ Sung Chức Năng Theo Dõi Thời Hạn Văn Bản, Hồ Sơ**:
        + Đã phân tích kiến trúc mã nguồn tại `/Users/thenhung/WorkBuddy AI/2026-10-15-14-57-59/phan-mem-theo-doi-van-ban`: hai nghiệp vụ Theo dõi Văn bản đến (số hiệu, hạn chung/riêng, đơn vị chủ trì, hạn tổng hợp cấp trên) và Hồ sơ TTHC (mã hồ sơ, loại TTHC, hạn trả kết quả, cảnh báo trước 2 ngày và quá hạn).
    - **Tinh Giản Triệt Để Chú Thích Thừa & Rườm Rà Trên Toàn Bộ Giao Diện (12/11/2026)**:
      * **Gỡ bỏ khối 3 bước rườm rà** trong `templates/outline_assign.html` (Bước 1: Nạp văn bản / "Hệ thống tự động bóc tách...", Bước 2: Phân công đơn vị, Bước 3: Phát hành công việc).
      * **Bỏ toàn bộ các câu chú thích, giải thích kiểu AI tự thuyết minh**:
        + `templates/outline_assign.html`: Bỏ câu phụ đề giải thích, bỏ dòng hỗ trợ định dạng/dung lượng và hướng dẫn kéo thả; Dropzone chỉ giữ icon và nút chọn tệp `[ Chọn văn bản (.docx, .pdf) ]`; bỏ các tiêu đề nhãn thừa trong Sticky Control Panel, đổi "Đã giao cho mục này:" thành "Đã phân công:".
        + `templates/tasks_rebuild.html`: Bỏ câu phụ đề giải thích dưới tiêu đề trang, đổi placeholder thành `Tìm kiếm công việc, đơn vị...`; trong popup chọn hình thức tạo việc bỏ toàn bộ các câu thuyết minh dài dòng, chỉ giữ 2 card hành chính dứt khoát với nút `[ Bắt đầu → ]`.
        + `templates/login.html`: Bỏ các subtitle giải thích ở cột Tạo QR, đổi placeholder mã tùy chọn thành ngắn gọn.
        + `templates/admin_center.html`: Bỏ các đoạn chú thích lắt nhắt dưới header và dưới các liên kết chức năng, giữ giao diện sắc sảo, dứt khoát.
    - **Vá Lỗi Lệch Khối Block Jinja2 Gây Tê Liệt Tải File Đề Cương (12/11/2026)**:
      * **Nguyên nhân**: `templates/outline_assign.html` dùng `{% block extra_js %}` và `{% block extra_css %}`, nhưng shell `templates/base.html` chỉ khai báo `{% block scripts %}` và `{% block extra_head %}`. Do đó, toàn bộ 700+ dòng script lắng nghe sự kiện chọn tệp không được nhúng vào trang, dẫn tới hiện tượng sau khi chọn file từ máy tính không có phản hồi.
      * **Đã sửa**:
        + Đồng bộ lại chuẩn block: `{% block scripts %}` và `{% block extra_head %}` trên cả `outline_assign.html` và `admin_center.html`.
        + Thêm phản hồi trực quan tức thì: Nút bấm hiển thị spinner `Đang xử lý văn bản...` + SweetAlert2 loading `Đang tiếp nhận văn bản...`, tự động bắt lỗi HTTP và chuyển cảnh mượt mà khi hoàn tất.
    - **Cải Tổ Toàn Diện Giao Diện, Chức Năng & Nghiệp Vụ Chuẩn Hóa Theo Chỉ Đạo (12/11/2026)**:
      * **Bàn Làm Việc Lưới Chức Năng (App Launchpad Grid) Tại Trang Chủ (`/admin`)**:
        + Bỏ hoàn toàn thanh menu ngang thừa trên Header (`Trang chủ | Công việc | Sổ hồ sơ | ...`). Header tối giản: Logo CAND đỏ + "PC06 PRO" + "ĐỀ ÁN 06 TUYÊN QUANG"; khi vào trang con hiện nút `[ ⊞ Bàn làm việc ]` cạnh logo để 1-click quay về.
        + Tinh gọn Lưới chức năng thành 7 ô ứng dụng nổi khối trực quan: (1) Giao việc theo đề cương văn bản, (2) Giao việc theo biểu mẫu, (3) Theo dõi thời hạn hồ sơ, (4) Bảng tin & Thư viện, (5) Mã QR & Link rút gọn, (6) Danh bạ cơ quan, (7) Quản trị hệ thống.
        + Xóa bỏ triệt để: Ô "Ma trận tiến độ nộp" rườm rà; chữ "2 cấp" ở Danh bạ cơ quan; đổi "Thu thập biểu mẫu" thành "Giao việc theo biểu mẫu".
      * **Chuẩn Hóa Bộ Máy Đơn Vị Cấp Tỉnh Tuyên Quang 2026**:
        + Chuyển đơn vị `hethong` (ID 1) từ cấp Xã thành cấp Tỉnh (`level='province'`).
        + Cập nhật CSDL theo Nghị quyết HĐND tỉnh và thực tế Đề án 06: Bỏ hoàn toàn các sở cũ đã hợp nhất/giải thể (Sở TT&TT, Sở LĐ-TB&XH, Sở TN&MT, Sở KH&ĐT, Sở GTVT, Sở NN&PTNT); chuẩn hóa 19 đơn vị cấp tỉnh mới. Đồng bộ 38 tài khoản `admin_<short>` và `bc_<short>` tương ứng.
      * **Thanh Lọc Triệt Để Trung Tâm Quản Trị Hệ Thống (`/admin/system-center`)**, **Chuẩn Hóa 4 Vai Trò (`/roles`)**, **Phân Hệ Sổ Theo Dõi Thời Hạn Hồ Sơ (`/dossiers`)**, **Đăng Nhập & QR (`/login` & `/public/qr`)**, **Giao Việc Biểu Mẫu (`/tasks`)**.
    - **Vá Triệt Để Thuật Toán Giao Việc Theo Đơn Vị & Phân Quyền Xem/Báo Cáo Công Việc (13/11/2026)**:
      * **Nguyên nhân gốc rễ khi giao việc cho Sở Tư pháp mà `bc_sotuphap` chỉ xem được không báo cáo được**:
        1. **Lệch tên trường API `/api/outline-assignees` ↔ `templates/outline_assign.html`**: Backend trả `key` (cho đơn vị) và `unit` (cho cán bộ), trong khi frontend đọc `u.code` và `u.unit_name` → tích chọn đơn vị đẩy `undefined` thành `[null]` gửi về server → sinh `TaskAssignment(user_id=None, unit_id=None)` mồ côi.
        2. **Lỗi `_users_for_unit` trong `services/task_units.py`**: truy vấn sai nhóm danh mục (`_task_domain_options` thay vì `_task_assignment_unit_options`), không tra bảng `Unit`, và lệch chuẩn `extract_unit_key('Sở Tư pháp')='sotuphap'` vs `User.unit_key='so_tu_phap'`.
        3. **Lệch nghĩa `p_task_view` trong `services/task_permissions.py`**: `normalize_permission_payload` tự bật `p_task_view=1` cho mọi tài khoản có `p_task_exec=1`/`p_task_process=1`, nhưng `_can_view_all_tasks` lại đọc trực tiếp `p_task_view` nên mọi `Cán bộ báo cáo` nhìn thấy toàn bộ công việc chưa được giao cho mình (không có `my_assignment` → không hiện biểu mẫu báo cáo). Ngoài ra `services/task_pages.py` cho phép `or is_lead` vào thẳng chi tiết mọi task không thuộc quyền quản lý.
        4. **Bản ghi danh mục cũ tồn dư**: xóa 29 `CategoryItem` cũ/trùng trong nhóm `contact_unit` trên `pc06_system.db` (còn đúng 267 đơn vị chuẩn) và cập nhật `scripts/admin/cleanup_and_standardize_local_db.py`.
      * **Đã sửa**: [routes/outline.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/outline.py), [templates/outline_assign.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/outline_assign.html), [services/task_units.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_units.py), [services/task_permissions.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_permissions.py), [services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py), [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py) (lọc KPI/biểu đồ `/admin` theo đúng `_visible_dashboard_task_ids`), [templates/admin_dashboard.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard.html) & [templates/admin_dashboard_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard_mobile.html) (ẩn ô `Giao việc theo đề cương` khi không có quyền `task:process`), [scripts/admin/cleanup_and_standardize_local_db.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/scripts/admin/cleanup_and_standardize_local_db.py), bổ sung [tests/test_unit_assignment_and_visibility.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_unit_assignment_and_visibility.py).
    - **Vá Toàn Diện Logic Giao Việc Theo Đề Cương Cho Mục Lá (`bullet`, `plus`, `para`) & Chống Trùng Lặp (13/11/2026)**:
      * **Nguyên nhân gốc rễ lỗi `"Chưa gán mục nào. Hãy gán ít nhất một mục cho cán bộ."`**:
        + Frontend (`templates/outline_assign.html`) cho phép chọn và gán đơn vị/cán bộ trên mọi dòng `.doc-segment` (bao gồm cả `bullet`, `plus`, `para`), gắn thẻ xanh (`Sở Tư pháp`) và đếm vào `Tiến độ phân công: 1 / 51 mục`, nhưng backend `create_items()` trong `routes/outline.py` trước đó bỏ qua mọi node không phải heading (`if not _is_outline_heading(n): ... continue`), khiến `total_items == 0` dù người dùng đã gán mục lá.
      * **Đã rà soát và sửa đồng bộ toàn luồng**:
        + `routes/outline.py`: hỗ trợ tạo `TaskItem` và `TaskAssignment` cho cả heading (`h1..h9`) lẫn mục lá (`bullet`, `plus`, `para`) kèm ngữ cảnh mục cha (vd `[1.1]`) trong `title` và nội dung dòng con trong `content`; thêm `_resolve_item_assignment_specs()` khử trùng lặp `(user_id, role_id)` và tránh tạo `TaskItem` rỗng khi chỉ định không hợp lệ; bổ sung `_annotate_tree_with_hints()` cho nhánh `.pdf` ở `/api/parse-outline`; dùng `_resolve_unit_record()` kiểm tra quy tắc cấp xã khi có node cấp xã.
        + `templates/outline_assign.html`: sửa `renderNode` đếm đủ `h1..h9` và fallback `totalSegments`; chuẩn hóa `removeAssignee()` (xóa cả `unit_domains`/`user_ids` của thẻ preset), `btnAutoApply` (áp dụng đủ `user_ids`/`role_ids`), `hasValidAssignees()` + `updateProgress()` (chống tràn >100%), chặn mở modal khi chưa có mục hợp lệ, và đọc lỗi HTTP ở `btnConfirmTask` kèm đóng modal để không bị kẹt sau popup SweetAlert2.
        + Bổ sung test hồi quy `test_assign_bullet_and_plus_nodes_and_dedupe_overlap` trong [tests/test_unit_assignment_and_visibility.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_unit_assignment_and_visibility.py) + smoke check thực tế gán node `bullet` cho `so_tu_phap` (HTTP 200, `bc_sotuphap` thấy nút `Gửi báo cáo`).
    - **Sửa Lỗi Tràn Ngang & Đơn Giản Hóa Toàn Diện Giao Diện Xem Việc / Nhận Việc (`/tasks` & `/tasks/<tid>`, 13/11/2026)**:
      * **Nguyên nhân lỗi tràn ngang (như ảnh chụp màn hình `/tasks/<tid>`)**: `.task-detail-shell` (và `.task-workspace-shell`) dùng `display: grid` không có `grid-template-columns: minmax(0, 1fr)` / `min-width: 0`, nên bảng ma trận `outline_matrix` bên trong `.table-responsive` kéo giãn toàn bộ trang vượt quá `100vw` làm xô lệch và cắt xén cả hero lẫn cột `"Bước tiếp theo"`.
      * **Đã thiết kế lại đồng bộ chuẩn phẳng `pc-card` / `pc-btn` / `pc-table` ([templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html), [templates/tasks_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html))**:
        + Chuyển `.task-detail-shell` và `.task-workspace-shell` sang `display: flex; flex-direction: column; min-width: 0; max-width: 100%;`; cột `"Đầu mục"` (`.pc-matrix-item-col`) tự ngắt dòng gọn và bảng rộng cuộn ngang độc lập trong `.table-responsive`.
        + Loại bỏ hoàn toàn khối hero bo tròn `28px`, khối thừa `"Bước tiếp theo"`, 4 thẻ KPI to chiếm diện tích và thanh menu dọc `"Khu vực làm việc"` (`col-xl-3`) bóp hẹp vùng làm việc; thay bằng 1 thẻ đầu trang gọn (`pc-detail-header`) gồm tiêu đề, nút quay lại, nút hành động (`Xuất báo cáo Word` / `Xóa`), thông tin tóm tắt 1 dòng, thanh tiến độ mảnh và nội dung yêu cầu.
        + Luồng **Người nhận việc / Báo cáo** mở thẳng phần việc được giao toàn chiều rộng (không tab thừa khi chỉ có 1 nhóm), nút **Tiếp nhận** và biểu mẫu **Gửi báo cáo** hiển thị trực diện trên từng đầu mục; luồng **Quản trị** dùng thanh tab ngang gọn (`.pc-detail-tabs`) phía trên bảng toàn chiều rộng.
        + Sửa lỗi `#taskSearchInput` ở `templates/tasks_rebuild.html` trước đó đặt nhầm trong `{% if is_lead or is_admin %}` khiến tài khoản báo cáo không lọc tìm được công việc.
    - **Sửa 3 Lỗi Bố Cục Toàn Màn Hình, Đếm Gộp Lượt Nộp Theo Đơn Vị & Đệm Khung Thẻ (`/tasks/<tid>`, 13/11/2026)**:
      * **Gỡ khoảng trống ~272px bên trái màn hình desktop**: `static/css/flat-theme.css` nạp sau block `<style>` của `templates/base.html` vẫn giữ `body.pc06-bdhvs-body { padding-left: var(--desktop-sidebar-width); }` và `.top-navbar { left: var(--desktop-sidebar-width); }` trong `@media (min-width: 992px)` dù `.desktop-sidebar` đã ẩn (`display: none !important`). Đã sửa về `padding-left: 0 !important` / `left: 0` ở cả [static/css/flat-theme.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/flat-theme.css) và [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html) (kèm cache-bust `flat-theme.css?v=1.0.1`).
      * **Gộp lượt nộp theo đơn vị / vai trò logic (không nhân đôi theo số tài khoản)**: Giao chỉ 1 đơn vị (`Sở Tư pháp`, gồm `admin_sotuphap` + `bc_sotuphap`) trước đó hiển thị `0/2` do đếm số dòng `TaskAssignment` thô và `_task_unit_identity()` suy đoán theo `unit_area`/`fullname` thay vì `Unit`/`unit_id`. Đã bổ sung `_collapse_logical_task_assignments()` và chuẩn hóa `_task_assignment_submission_group_key()` theo `unit_id` ([services/task_workspace_helpers.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_workspace_helpers.py)), ưu tiên tra `Unit`/`user.unit_id` trong `_task_unit_identity()` ([services/task_units.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_units.py)), áp dụng gộp logic trong `_parse_outline_item_rows()` ([services/task_workspace_views.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_workspace_views.py)) và `_build_outline_progress_matrix()` ([services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py)), đồng thời cập nhật `_return_task_assignment_v2()` ([services/task_google_forms_v2.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_google_forms_v2.py)) trả lại đồng bộ tất cả tài khoản cùng nhóm đơn vị.
      * **Bổ sung padding cho `.pc-card` trong chi tiết công việc**: Thêm `.pc-detail-tab-content .pc-card, .pc-detail-scope-card { padding: 18px 22px; border-radius: 12px; }` (mobile `14px 16px`) trong [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html) để chữ và bảng không còn dính sát viền khung.
      * **Test hồi quy**: Bổ sung `test_single_unit_with_two_accounts_counts_as_one_submission_and_returns_cleanly` và `test_multi_unit_outline_keeps_four_columns_without_unit_tabs` trong [tests/test_unit_assignment_and_visibility.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_unit_assignment_and_visibility.py).
    - **Tối Ưu Hiển Thị Chi Tiết Công Việc Đề Cương Quy Mô Nhiều Đơn Vị (1–267 đơn vị, 13/11/2026)**:
      * **Gỡ bỏ hoàn toàn tab theo từng đơn vị trên thanh tab `#taskWorkspaceTabs`**: Trong [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html) thay vòng lặp `outline_groups` bằng tối đa 3 tab chức năng cố định (`Tiến độ chung`, `Phần việc cần nộp` khi người dùng có đầu mục được giao, `Thiết lập đầu mục`), tránh phình hàng trăm tab khi giao 19 Sở / 124 Xã / 124 CAX.
      * **Bảng `Tiến độ chung` cố định 4 cột (`Đầu mục` | `Đơn vị thực hiện` | `Tiến độ` | `Tổng hợp`) kèm lọc nhanh**: Bổ sung `assigned_cells` và `unit_count` vào `_build_outline_progress_matrix` ([services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py)); cột `Đơn vị thực hiện` hiển thị trực tiếp thẻ đơn vị khi `<= 6` đơn vị hoặc gộp gọn trong `<details class="pc-matrix-units-collapse">` + khung cuộn `.pc-matrix-unit-scroll` khi `> 6` đơn vị; bổ sung bộ lọc `#outlineMatrixSearch`, `#outlineMatrixUnitFilter`, `#outlineMatrixStatusFilter`.
      * **Đồng bộ gộp đơn vị ở Modal Tổng hợp & Xuất Word**: Cập nhật `_task_item_synthesis_data` ([services/task_synthesis.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_synthesis.py)) và `_export_outline_word_v2` ([services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py)) dùng `_collapse_logical_task_assignments` để không nhân đôi dòng theo số tài khoản cùng đơn vị.
    - **Vá Lỗi CSRF 400 `"Yêu cầu không hợp lệ hoặc phiên làm việc đã hết hạn."` Khi Đăng Xuất & Đăng Nhập Lại (13/11/2026)**:
      * **Nguyên nhân gốc rễ**: `routes/auth.py:logout()` và `enforce_session_integrity()` chuyển hướng về `/login?clear_storage=true` sau khi đặt `session['csrf_token']` mới, nhưng `add_security_headers()` trong `app.py` lại gắn `Clear-Site-Data: "cache", "cookies", "storage"` lên response `GET /login?clear_storage=true`. Trình duyệt thật xóa toàn bộ cookie (gồm `pc06_session` chứa `csrf_token` vừa cấp) ngay khi nhận trang đăng nhập, trong khi form HTML vẫn giữ token cũ → `POST /login` bị mất cookie phiên và lỗi 400.
      * **Đã sửa**:
        + [app.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/app.py): Chỉ gửi `Clear-Site-Data: "cache", "storage"` cho `GET`/`HEAD` có `clear_storage=true` (bỏ `"cookies"` để không xóa cookie CSRF vừa cấp sau `session.clear()`); đồng thời trong `enforce_csrf_protection()`, nếu `POST /login` gửi token cũ/lệch từ tab cũ hoặc cookie bị mất, tự làm mới `csrf_token` + flash cảnh báo và redirect về `GET /login` thay vì trả trang lỗi trắng `400` (vẫn trả `400` khi thiếu `csrf_token`).
        + [routes/auth.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/auth.py): Bảo đảm `GET /login` luôn có `csrf_token` và đánh dấu `session.modified = True` khi `clear_storage=true`.
        + [templates/login.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/login.html) & [templates/login_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/login_mobile.html): Khai báo tường minh `action="{{ url_for('auth_bp.login') }}"`, xóa `?clear_storage=true` khỏi thanh địa chỉ bằng `history.replaceState` sau khi dọn `localStorage`, và reload trang khi quay lại từ `bfcache` (`pageshow`).
        + [tests/test_security_regressions.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_security_regressions.py) & [tests/test_auth_security.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_auth_security.py): Cập nhật assertion `Clear-Site-Data` không chứa `cookies`, bổ sung `test_logout_then_login_following_clear_storage_redirect_succeeds` và `test_login_post_with_stale_csrf_token_recovers_gracefully`.
    - **Tái Thiết Kế Hoàn Toàn Giao Diện Chi Tiết Công Việc `/tasks/<tid>` Theo Phong Cách Linear / Notion Tối Giản Hiện Đại (13/11/2026)**:
      * **Phong cách mới (Editorial Linear / Notion)**: Loại bỏ hoàn toàn kiểu "thẻ trắng lồng trong thẻ trắng" và thanh tab bo tròn trải full chiều rộng; chuyển sang phần đầu trang mở không viền kết hợp khối mô tả left-accent Notion, dải thuộc tính 1 dòng (hiển thị đúng 1 lần `N lượt giao · Đã nộp X/Y`), duy nhất 1 nút `Xuất báo cáo Word` trên header và thanh tab đường gạch chân mảnh (`.pc-linear-tabs`).
      * **Đọc trực tiếp báo cáo đơn vị ngay trên màn hình + Ngăn kéo duyệt trượt (`#outlineReviewDrawer`)**:
        + Làm giàu `_build_outline_progress_matrix()` ([services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py)) với `_outline_matrix_display_title()` (hiển thị trọn vẹn nội dung đầu mục khi `title` bị cắt ở mốc 255 ký tự) và `_outline_assignment_report_entry()` (đính kèm nội dung báo cáo đã nộp/gộp số liệu, danh sách tệp, người nộp, thời điểm nộp, `review_payload`, dùng batch `User.query` tránh N+1).
        + Hiển thị trực tiếp nội dung báo cáo và chip tải tệp của từng đơn vị ngay trong cột `Đơn vị thực hiện` ([templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html)), giữ nguyên gom nhóm `<details data-matrix-collapse>` khi `> 6` đơn vị (quy mô 19 Sở / 124 Xã).
        + Ẩn sẵn ô `[Lý do] [Xác nhận gửi]` trong `.pc-return-box.d-none` và chỉ mở khi bấm nút `Trả lại` (hoặc mở `#outlineReviewDrawer` trượt từ cạnh phải để đọc đầy đủ và yêu cầu bổ sung).
      * **Hiển thị lý do trả lại đồng nhất cho cả quản trị và đơn vị**: Gắn `assignee_id` + `created_at` trong `_return_task_assignment_v2()` ([services/task_google_forms_v2.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_google_forms_v2.py)), trích xuất qua `_task_return_comments()` / `_assignment_return_reason()` ([services/task_workspace_views.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_workspace_views.py)) lên cả ma trận quản trị lẫn tab `Phần việc cần nộp` của đơn vị.
      * **Token hóa CSS Light/Dark**: Toàn bộ CSS mới trong [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html) dùng token `var(--pc-*)` chuẩn (`static/css/pc06-premium.css`).
      * **Kiểm thử & Server**: Cập nhật assertion hồi quy trong [tests/test_unit_assignment_and_visibility.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_unit_assignment_and_visibility.py); chạy `run_tests.py` đạt **313 test / 0 fail** (40.675s). Dev Server daemon `task-3916` đang chạy tại `http://127.0.0.1:5001`.
    - **Rà Soát Trước Khi Upload DirectAdmin & Vá Script Khởi Tạo Tài Khoản Hàng Loạt (13/11/2026)**:
      * **Phát hiện khi kiểm tra pre-deploy DirectAdmin**:
        + [scripts/admin/seed_two_tier_government_accounts.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/scripts/admin/seed_two_tier_government_accounts.py) bản cũ dùng danh sách 19 Sở/ngành cũ đã sáp nhập (`so_tttt`, `so_khdt`, `so_ldtbxh`, `so_tnmt`, `so_gtvt`, `so_nnptnt`), gắn nhầm `unit_key` tiền tố `tq_*` (bị `routes/outline.py` bỏ qua), thiếu đồng bộ `CategoryItem` khối UBND/CAX, ghi đè mật khẩu mọi tài khoản khi chạy lại và xuất CSV chứa mật khẩu thô thẳng vào `exports/` trong `public_html`.
        + [.htaccess](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/.htaccess) chưa chặn thư mục `exports/`, `testdata/`, `scratch/`, `__pycache__/` và các script gốc (`run_tests.py`, `migrate.py`, `seed_categories.py`, `*.log`).
        + [scripts/admin/cleanup_and_standardize_local_db.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/scripts/admin/cleanup_and_standardize_local_db.py) thiếu chốt chặn `PC06_CONFIRM=YES`.
      * **Đã sửa**:
        + Cập nhật [scripts/admin/seed_two_tier_government_accounts.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/scripts/admin/seed_two_tier_government_accounts.py) đồng bộ 19 Sở/Ban/Ngành 2026 (`tt_pvhcc`, `bhxh_tinh`, `cuc_thue_tinh`, `so_nn_mt`, `nhnn_khuvuc4`, `so_dt_tg`, ...), chuẩn hóa `unit_key = Unit.code` (không tiền tố `tq_`), gọi `ensure_standard_system_roles()`, đảm bảo đơn vị `hethong` (`province`), đồng bộ đủ 267 `CategoryItem` trong `contact_unit` (chống trùng theo `code` hoặc `name` khi chạy sau `seed_categories.py`), bảo toàn mật khẩu user đã tồn tại (chỉ đặt lại khi truyền `--reset-existing`), chế độ `--dry-run` an toàn 100% không ghi DB/CSV, và xuất CSV bàn giao mặc định vào `BACKUP_FOLDER` ngoài `public_html` (`chmod 600`).
        + Gia cố [.htaccess](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/.htaccess) chặn `exports|testdata|scratch|__pycache__`, `*.log`, `run_tests.py`, `migrate.py`, `seed_categories.py`.
        + Bổ sung `require_confirmation` (`PC06_CONFIRM=YES`) cho [scripts/admin/cleanup_and_standardize_local_db.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/scripts/admin/cleanup_and_standardize_local_db.py).
        + Bổ sung [tests/test_seed_two_tier_accounts.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_seed_two_tier_accounts.py) (3 test); chạy lại `run_tests.py` đạt **316 test / 0 fail** (41.731s).
    - **Chống Lặp Nội Dung Đầu Mục & Thu Gọn Văn Bản Dài Trên `/tasks/<tid>` (13/11/2026)**:
      * **Nguyên nhân lặp lại nội dung**: Mục lá (`bullet`, `plus`, `para`) lưu `item.title` có tiền tố ngữ cảnh (vd `[1.1] ...`, cắt ở 255 ký tự) còn `item.content` giữ dấu gạch đầu dòng (`– ...`, tối đa 5000 ký tự) + các dòng con; trước đây hàm tách `secondary_text` trong `services/task_workspace_views.py` chỉ so sánh chuỗi bằng tuyệt đối với `item.title` nên luôn trượt và in nguyên vẹn đoạn văn thứ hai trùng hệt tiêu đề.
      * **Đã sửa**:
        + Tạo helper dùng chung `_outline_display_and_secondary()` (kèm `_normalize_outline_compare_text()`, `_outline_lines_match_title()`) trong [services/task_workspace_views.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_workspace_views.py) và tái sử dụng qua [services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py): tự động mở rộng tiêu đề đầu mục đầy đủ từ dòng 1 của `content`, bỏ dòng trùng khỏi `secondary_text` nhưng vẫn giữ nguyên `guide_text` khác biệt hoặc các dòng phụ `+` con bên dưới.
        + Áp dụng cơ chế **Progressive Disclosure** (thu gọn 2–4 dòng bằng `.pc-clamp-text` + nút **`Xem thêm` / `Thu gọn`** tự động chỉ hiện khi text tràn khung qua `pcSyncClampToggles()`) cho cột `Đầu mục`, mô tả đầu trang và tab `Phần việc cần nộp` trong [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html); **ẩn hoàn toàn văn xuôi báo cáo & chip tệp khỏi hàng đơn vị trên bảng `Tiến độ chung`** — chỉ giữ nút `Xem báo cáo` cho đơn vị đã nộp và lược bỏ nút trùng lặp `Ngăn kéo duyệt` ở cột `Tổng hợp`.
        + Sửa lỗi nút `Xem báo cáo` bấm không mở khung đọc: do `<div id="outlineReviewDrawer">` trước đó đặt sau thẻ `<script>` bên trong `{% block content %}` nên lúc chạy script `document.getElementById('outlineReviewDrawer')` bị `null` (và chạy trước `bootstrap.bundle.min.js`). Đã đưa `#outlineReviewDrawer` + `#synthesisModal` lên cuối `{% block content %}`, chuyển toàn bộ `<script>` của trang vào `{% block scripts %}` và bổ sung fallback tự mở/đóng nếu Bootstrap chưa sẵn sàng.
        + Bổ sung/cập nhật test hồi quy (kiểm tra DOM/script ordering và xóa nút `Ngăn kéo duyệt`) trong [tests/test_unit_assignment_and_visibility.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_unit_assignment_and_visibility.py); chạy `run_tests.py` đạt **318 test / 0 fail** (42.203s). Dev server daemon `task-4259` đã khởi động lại trên `http://127.0.0.1:5001`.
    - **Gỡ Tab `Thiết lập đầu mục` Cũ Trên `/tasks/<tid>` (13/11/2026)**:
      * **Xác nhận nguồn gốc**: Tab `Thiết lập đầu mục` (`#tab-outline-create` / `#pane-outline-create`: `Cấu hình thủ công`, `Tải file đề cương và cấu hình`, `Tạo đầu mục thủ công`, `#rowAssignModal` kèm script khởi tạo cũ) đúng là UI dư thừa từ luồng tạo đề cương v1 trước khi tách sang `/outline-giao-viec` (`templates/outline_assign.html`).
      * **Đã dọn sạch**:
        + Gỡ nhánh `default_tab = "outline-create"` trong [task_workspace.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/task_workspace.py) để tài khoản quản lý luôn vào thẳng `outline-matrix`.
        + Xóa `#tab-outline-create`, `#pane-outline-create`, `#rowAssignModal` và 776 dòng `<script>` cũ (dòng 2030–2805) khỏi [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html); chỉ hiển thị `#taskWorkspaceTabs` khi có thêm phần việc cá nhân (`my_outline_rows|length > 0`) để không còn thanh tab 1 mục dư thừa, đồng thời đổi thông báo trống ma trận sang *"Công việc này hiện chưa có đầu mục nào được phân công."*
        + Cập nhật [tests/test_task_outline_word_export.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_task_outline_word_export.py) kiểm tra trực tiếp payload `session` backend khi preview và bổ sung assertion chặn hồi quy `Thiết lập đầu mục` / `#taskWorkspaceTabs` trong [tests/test_unit_assignment_and_visibility.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_unit_assignment_and_visibility.py).
        + Đã kiểm tra `node --check` với 3 block `<script>` còn lại (`rc=0`); chạy full suite `run_tests.py` đạt **318 test / 0 fail** (42.366s). Dev server daemon `task-4359` đang chạy trên `http://127.0.0.1:5001` (`/login` trả HTTP `200`).
    - **Thống Nhất Giao Diện Báo Cáo Theo Biểu Mẫu (`FORM`) Đồng Bộ Với Đề Cương & Dọn Wizard Cũ (18/11/2026)**:
      * **Vấn đề trước đó**:
        + Trên `/tasks/<tid>`, luồng `FORM` (`#pane-form-list`, `#pane-form-submit`, header, tabs) vẫn giữ giao diện Bootstrap cũ lồng thẻ trắng (`Tổng quan theo vai trò`, `Tổng quan theo đơn vị`, `Chi tiết theo cán bộ`), lặp nút `Xem dữ liệu`/`Xuất Excel`, không gộp lượt nộp theo đơn vị, in lộ thiên toàn bộ nội dung/số liệu đã nộp + ô `[Lý do trả lại]`, thiếu hiển thị lý do trả lại cho đơn vị ở `#pane-form-submit`, và hiện thanh tab thừa cho tài khoản nộp khi cùng đơn vị có nhiều user.
        + Trên `/tasks`, bấm `Giao theo biểu mẫu` mở lại wizard 4 bước cũ (`#createTaskModal`) vẫn dính Bước 1 chọn lại Đề cương/Biểu mẫu, markup `OUTLINE`/`FILE` cũ (`#wizardRowAssignModal`, ~1.000 dòng JS outline), và thiếu bộ chọn 267 đơn vị (`/api/outline-assignees`) cho `FORM`.
        + **Bug nền phát hiện khi viết test**: `_task_report_item_visible_for_user(item_config, user)` trong [services/task_report_schema.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_report_schema.py) từng kiểm tra `if not item_config`, khiến mọi `TaskFormField` thường (lưu `field_options_json = None` → `{}` khi `target_type='all'`) bị trả về `False` và ẩn sạch khỏi phía đơn vị.
      * **Đã đồng bộ & sửa**:
        + [services/task_report_schema.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_report_schema.py): Sửa `_task_report_item_visible_for_user()` cho phép `dict` rỗng `{}` mặc định `target_type = "all"` (`isinstance(item_config, dict)`).
        + [services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py): Bổ sung `_build_form_progress_matrix()` + `_format_form_field_display_value()` (gộp lượt nộp theo đơn vị qua `_collapse_logical_task_assignments`, tính cộng gộp số liệu tự động, chuẩn hóa `review_payload` cho ngăn kéo duyệt và trích xuất `my_form_return_reason`).
        + [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html): Đồng bộ `FORM` 100% theo chuẩn Linear/Notion như `OUTLINE` (`Tiến độ chung` + `#formMatrixTable` tìm kiếm/lọc trạng thái + ngăn kéo `Xem báo cáo` + nút `Trả lại` ẩn gọn + gộp Google Form admin vào `<details>`, `#pane-form-submit` dùng `.pc-outline-item` + hiển thị `Yêu cầu bổ sung từ người giao`, bỏ nút trùng và ẩn `#taskWorkspaceTabs` khi chỉ có 1 chế độ xem).
        + [templates/tasks_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html): Chuyển `#createTaskModal` thành wizard 3 bước thuần **Giao việc theo biểu mẫu** (1. Thiết lập biểu mẫu / nạp Excel & parses `field_options_json` -> 2. Chọn đơn vị / vai trò / cá nhân qua `/api/outline-assignees` có preset 19 Sở / 124 UBND / 124 CAX -> 3. Thông tin & Phát hành), xóa sạch markup/JS đề cương cũ và `#wizardRowAssignModal`.
        + Kiểm tra `node --check` cho toàn bộ 6 block `<script>` (4 trong `task_detail_rebuild.html`, 2 trong `tasks_rebuild.html`, tất cả `rc=0`); bổ sung 2 test hồi quy trong [tests/test_task_form_field_scope.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_task_form_field_scope.py); chạy full suite `run_tests.py` đạt **320 test / 0 fail** (42.553s).
    - **Kiểm Tra Trình Duyệt Thực Tế & Vá Toàn Bộ Lỗi UI/CSS/Runtime Phát Hiện (18/11/2026)**:
      * **Đã sửa từ kiểm thử trình duyệt thực tế trên `http://127.0.0.1:5001`**:
        + [services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py) (`_build_form_progress_matrix`) & [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html): Chỉ bật `has_submission = True` khi bài nộp thực sự đã nộp/bị trả lại/có dữ liệu, loại bỏ nút `Xem báo cáo` giả và dòng `Đã nhập 0/2 trường` ở bản nháp rỗng từ `_lazy_repair_task_runtime`; hàng chưa nộp hiển thị `—`.
        + [static/css/style.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/style.css), [static/css/flat-theme.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/flat-theme.css), [static/css/pc06-premium.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/pc06-premium.css) (bump `?v=` tại [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html) `style.css?v=4.2.2`, `flat-theme.css?v=1.0.3`, `pc06-premium.css?v=1.3.9` và [templates/base_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base_mobile.html)): Gỡ `!important` ở `padding` của `.form-control, .form-select`, sửa `.pc-linear-search-wrap .form-control { padding-left: 34px !important; }` để icon kính lúp không đè chữ, ẩn `select::picker-icon` + căn lại `.form-select-sm` / `.pc-btn.btn-sm` (hết mũi tên `▼` thừa dòng 2), dịch `.swal2-top-end` xuống dưới navbar, và tối ưu `.pc-linear-drawer` (`width: min(540px, 94vw) !important; transition: transform 0.08s ease-out !important;`, `appendChild` ra `document.body`) để mở đúng khung ở `1024px`.
        + [templates/tasks_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html): Cố định `table-layout: fixed` trên desktop với tỷ lệ 7 cột (`#` `36px`, `Đơn vị giao` `136px`, `Thời gian giao` `98px`, `Thời hạn báo cáo` `112px`, `Kiểu báo cáo` `128px`, `Thao tác` `160px`) để toàn bộ nút `Xem / Sửa / Xóa` lọt khung hoàn toàn ở cả `1024x800` và `1280x800`; sửa cắt chữ stepper `#wizardSteps`, độ rộng input Excel và căn dòng nút `+ Thêm trường`.
        + [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html): Sửa vòng lặp đệ quy `reportValidity()` trong listener `invalid` (gây `Maximum call stack size exceeded`), thêm kiểm tra JSON trong `checkUpdates()` (hết `Poll Error` trên `/password`), và chuyển flashed messages sang thẻ `<span data-pc-flash data-message="...">` (giữ UTF-8 cho test, tránh `SyntaxError`).
        + [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py), [services/task_units.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_units.py), [utils.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/utils.py): Vá `_resolve_unit_id()` + `seed_units_from_users()` + `_resolve_task_unit_label()` để giải mã đúng `category_item:<id>` và khớp `Unit.code` có gạch dưới (tránh tạo `Unit` lỗi `category_item:100` và gộp đúng đơn vị `Sở Tư pháp`), đồng thời bổ sung `_delete_user_cleanly()` cho `delete_user()` và `delete_users_bulk()` (xử lý `UserTrustedDevice`, `UserRole`, `Delegation`, `Notification`, `TaskAssignment`/`TaskSubmission` trước khi xóa User); đã dọn sạch `Unit #269` (`category_item:100`), task test và user test `test_ui_stp` khỏi `pc06_system.db`.
      * **Kết quả kiểm chứng sau chỉnh sửa cuối cùng**:
        + Full unit test suite `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py`: **322 test / 0 fail** (42.677s), đã thêm 2 test mới trong [tests/test_task_form_field_scope.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_task_form_field_scope.py) (`test_resolve_unit_id_matches_category_item_and_underscored_code`, `test_delete_user_cleanly_handles_trusted_device_and_submissions`).
        + Browser E2E trên `http://127.0.0.1:5001`: **0 lỗi JS console, 0 lỗi HTTP >=400**; bảng `/tasks` đạt `delBtnFitsWrap = true` ở cả `1280x800` và `1024x800`; gộp đơn vị `Sở Tư pháp` chuẩn 1 dòng `0/1 (0%)` -> nộp bài -> cộng gộp `25 (1 ĐV)` -> mở `#outlineReviewDrawer` gọn trong `1024px` -> `Trả lại` -> xóa task & tài khoản test thành công. Đã tắt dev server daemon sau khi kiểm thử xong.
    - **Chuyển Toàn Bộ Luồng `Giao việc theo biểu mẫu` (`FORM`) Sang Biểu Mẫu Excel (`.xlsx`) End-to-End (18/11/2026)**:
      * **Theo chỉ đạo `"gIAO VIỆC THEO BIỂU MẪU LÀ BIỂU MẪU EXCEL NHÉ"`**: Gỡ bỏ hoàn toàn tab Google Form và bộ câu hỏi Q&A khỏi `#createTaskModal` trên [templates/tasks_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html); Bước 1 chỉ tập trung tải lên file `.xlsx` mẫu (kèm kéo thả & stage preview tức thì qua `POST /api/tasks/excel-template-preview`) hoặc **Kẻ bảng Excel nhanh**, xem trước đúng cấu trúc tiêu đề gộp ô multi-row + dòng mẫu, cấu hình kiểu cột (`Văn bản` / `Số liệu` tự cộng tổng, `Cố định`, cho phép đơn vị thêm/xóa dòng).
      * **Module xử lý Excel gốc [services/excel_form_template.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/excel_form_template.py)**:
        + Phân tích layout `.xlsx` (`parse_excel_template_layout`): bóc banner, header gộp nhiều tầng (`header_grid`), tên cột phân cấp (`full_label`), suy luận kiểu cột số/chữ chuẩn tiếng Việt (chỉ nhận diện dòng đánh số cột khi có từ `max(2, num_cols // 2)` ô marker trở lên, chuyển đúng `đ/Đ -> d/D` qua `_ascii_vn()`, giữ cột chỉ tiêu chữ là `text`), phát hiện bảng chỉ tiêu cố định vs bảng động.
        + Tạo file `.xlsx` cho đơn vị tải điền giữ nguyên form gốc (`build_unit_prefilled_excel_bytes`), đọc lại file `.xlsx` đơn vị nộp lên (`parse_uploaded_submission_excel`), validate/tính tổng (`normalize_submitted_excel_rows`), và gộp/xuất Excel tổng hợp (`build_aggregated_excel_workbook`: cộng gộp trực tiếp theo từng ô chỉ tiêu ở sheet `Tong hop` + sheet `Chi tiet don vi` khi bảng cố định, hoặc dịch chuẩn cả `merged_cells` và `column_dimensions` sang phải +1 cột cho cột `Đơn vị báo cáo` kèm công thức `=SUM(...)` khi bảng động).
      * **Backend & Route mới ([routes/tasks.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/tasks.py), [services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py), [services/task_runtime_sync.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_runtime_sync.py), [services/task_form_aggregation.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_form_aggregation.py))**:
        + Bổ sung `POST /api/tasks/excel-template-preview`, `GET /tasks/<tid>/excel-template.xlsx`, `POST /tasks/<tid>/excel-upload-preview`; lưu schema trong `Task.outline_table_schema_json` (`form_provider = "excel"`), file `.xlsx` gốc trong `Task.file_path`, bài nộp trong `TaskSubmission.payload_json` (`mode = "excel_sheet"`), giữ tương thích nhánh backend Q&A/Google Form cũ (`form_provider != "excel"`) cho các suite test nền.
        + Cập nhật `_submission_has_report_content` cho `excel_sheet`, `_build_form_progress_matrix` (đếm dòng Excel đã nộp, cộng gộp số liệu cột `number`, gắn `excel_table` + `TaskSubmissionFile` cho ngăn kéo duyệt), và `_export_form_task_v2` (xuất workbook Excel tổng hợp).
      * **Giao diện lưới nhập liệu Excel & trang tổng hợp ([templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html), [templates/task_form_aggregation.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_form_aggregation.html))**:
        + `#pane-form-submit` hiển thị bảng spreadsheet `#pcExcelSubmitGrid` giữ đúng header gộp ô từ `.xlsx`, `+ Thêm dòng`/xóa dòng (tự đánh số STT), tính tổng `<tfoot>` (`#pcExcelSumRow`) realtime, điều hướng bàn phím (`Enter`/mũi tên), dán nhiều ô từ Excel desktop (`\t`/`\n`), tải `.xlsx` mẫu, và nạp trực tiếp từ `.xlsx` đã điền. Sửa nút tải file Excel gốc ở đầu trang trỏ về `/tasks/<tid>/excel-template.xlsx` (thay cho `/dl_file/` vốn chỉ phục vụ bản tin/thư viện).
        + `#outlineReviewDrawer` hiển thị bảng mini Excel của từng đơn vị; `/tasks/<tid>/form-data` hiển thị bảng tổng hợp giữ nguyên bố cục Excel + chi tiết từng đơn vị + nút Xuất Excel tổng hợp.
      * **Kiểm chứng sau chỉnh sửa cuối cùng**:
        + JS syntax (`node --check` 5 block `<script>`): pass (`0` lỗi).
        + Full test suite `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py`: **326 test / 0 fail** (45.269s), gồm 4 test mới trong [tests/test_excel_form_workflow.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_excel_form_workflow.py) phủ đầy đủ parse header gộp ô, upload/tải/nạp `.xlsx`, xuất gộp chỉ tiêu cố định + xuất đa dòng dịch merge + công thức `=SUM(...)`, `/form-data`, trả lại bổ sung.
        + Kiểm thử trình duyệt thật trên `http://127.0.0.1:5001`: **0 lỗi JS console, 0 lỗi HTTP >=400** qua luồng `Kẻ bảng Excel nhanh` -> tạo việc -> nhập nhiều dòng + Auto-SUM (`20`) -> gửi biểu mẫu -> `Cộng gộp số liệu tự động` + `#outlineReviewDrawer` bảng mini -> `/tasks/<tid>/form-data` ở cả Light & Dark Mode. Ghi chú: bước upload `.xlsx` trên trình duyệt tạm dừng bởi `UPLOAD_NEEDS_PERMISSION` của sandbox, phần xử lý file `.xlsx` thật đã được test tích hợp bằng `unittest` trong `ExcelFormWorkflowTests`.
    - **Kiến trúc song song `/bieu-mau-giao-viec` + Tinh gọn UI, Dark Mode & Mobile (`18/11/2026`)**:
      * Tách trang giao việc theo biểu mẫu Excel riêng tại `/bieu-mau-giao-viec` ([routes/tasks.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/tasks.py), [services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py), [templates/form_assign.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/form_assign.html)) với 3 bước đầy đủ tương xứng `/outline-giao-viec`; tách riêng ô **Quản lý công việc & báo cáo** (`/tasks`) thành lưới **8 ô (4x2)** cân đối trên [templates/admin_dashboard.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard.html) & [templates/admin_dashboard_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard_mobile.html); bỏ modal chọn trùng lặp `#chooseTaskTypeModal` và `#createTaskModal` trên [templates/tasks_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html) thay bằng 2 nút điều hướng trực tiếp ở header.
      * Tinh gọn giao diện & sửa triệt để token Dark Mode / Modal / Mobile ([static/css/pc06-premium.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/pc06-premium.css) `?v=1.4.2`, [static/css/bdhvs-layout.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/bdhvs-layout.css) `?v=2.2.6`, [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html), [templates/dossiers.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/dossiers.html), [templates/units.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/units.html), [templates/admin_center.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_center.html), [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html), [templates/outline_assign.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/outline_assign.html) cùng các trang danh mục/liên hệ/thông báo/công cụ DB/log/roles/shortlinks/auth): thay `--pc-card-bg` sai thành `var(--pc-bg-card)`, bỏ `color !important` trên badge `.border` Dark Mode, cố định nền `#111b2e` đặc cho `.modal-content` và tắt fade trung gian gây lọt chữ nền, mở rộng cột thao tác/tổng hợp bảng `/dossiers` & `/tasks` & `/admin/units`, chỉnh responsive nút tác vụ về `768px`, và co gọn `.top-navbar` dưới `576px` tránh chồng lấn logo/chuông trên `390x844`.
      * **Kiểm chứng sau chỉnh sửa cuối cùng**: JS syntax kiểm tra các `<script>` (`bad=0`), `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py` đạt **330 test / 0 fail** (44.011s), kiểm thử trình duyệt thật trên `http://127.0.0.1:5001` Light & Dark Mode tại `1280x800`, `1024x800` và mobile `390x844` đạt **0 lỗi JS console, 0 lỗi HTTP >=400**.
    - **Giao việc theo biểu mẫu trực quan 2 cột + Công thức + Tự sinh dòng theo Đơn vị (`18/11/2026`)**:
      * Thiết kế lại `/bieu-mau-giao-viec` ([templates/form_assign.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/form_assign.html)) theo bố cục 2 cột song song tương tự `/outline-giao-viec`: Cột trái hiển thị bảng Excel trực quan (ký hiệu cột `A..Z`, tiêu đề gộp ô nhiều tầng, dòng `Tổng` ở trên hoặc dưới, badge vai trò/kiểu cột); Cột phải (`Control Rail`) cấu hình trực tiếp từng cột (`Dữ liệu nhập`, `Đơn vị nhận BC`, `STT tự động`, `Công thức (=)` hỗ trợ `=E/C`, `=SUM(...)`, `%`), chọn đơn vị nhận báo cáo tự động sinh ngay các dòng theo tên đơn vị trong bảng và phát hành ngay.
      * Nâng cấp engine Excel ([services/excel_form_template.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/excel_form_template.py), [services/task_pages.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_pages.py), [routes/tasks.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/tasks.py), [services/task_form_aggregation.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_form_aggregation.py), [templates/task_detail_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_detail_rebuild.html), [templates/task_form_aggregation.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/task_form_aggregation.html)):
        + Tăng giới hạn lên 60 cột (`CHỈ TIÊU.xlsx` 43 cột × 124 dòng), nhận diện dòng `Tổng` ở đầu bảng (`summary_position='top'`) & tự tách công thức (`=E{r}/C{r}`, `=J{r}/(I{r}+J{r}+K{r})`), định dạng `%`, gợi ý cột Đơn vị.
        + Khi bật `assign_row_mode='unit_rows'`: cô lập cho từng đơn vị chỉ thấy/tải/nộp đúng dòng của đơn vị mình (`resolve_unit_rows_for_user`), tự tính realtime cột công thức trên web lẫn kiểm toán/tính lại ở server (`evaluate_excel_formula` an toàn không dùng `eval`), khóa tên đơn vị chống sửa nhầm, tổng hợp trên `/tasks/<tid>/form-data` và xuất `/tasks/<tid>/export-form.xlsx` giữ nguyên cột Đơn vị gốc (không chèn thừa cột `Đơn vị báo cáo`) kèm công thức Excel thật (`=SUM(...)` và `=E5/C5`).
      * **Kiểm chứng sau chỉnh sửa cuối cùng**: JS syntax (`6/6` block, `bad=0`), full test suite `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py` đạt **332 test / 0 fail** (44.334s, gồm 2 test mới trong [tests/test_excel_form_workflow.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_excel_form_workflow.py)), parser kiểm chứng trực tiếp trên workbook thật 43 cột × 124 dòng `CHỈ TIÊU`, trình duyệt thật trên `http://127.0.0.1:5001/bieu-mau-giao-viec` (`Kẻ bảng nhanh` + cột `Tỷ lệ =D/C` + tự sinh `19` dòng Sở/Ngành + Dark Mode + Mobile `390x844`) đạt **0 lỗi JS console, 0 lỗi HTTP >=400**. (Ghi chú: upload `.xlsx` trên trình duyệt gặp `UPLOAD_PERMISSION_REQUIRED` timeout của sandbox nên luồng file `.xlsx` thật đã được kiểm chứng trực tiếp qua `unittest` và `parse_excel_template_layout`).
    - **Theo dõi thời hạn hồ sơ & chỉ tiêu hàng ngày đa biểu mẫu Excel / Ảnh OCR (`/dossiers`, `18/11/2026`)**:
      * Mở rộng model `Dossier` ([models.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/models.py)) và tự động migrate an toàn qua [utils.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/utils.py) thêm `category_tab`, `so_ho_so`, `thu_tuc`, `ngay_nop`, `has_deadline`, `tinh_dung_han`, `can_bo`, `trang_thai_nguon`, `unit_code`, `unit_key`, `report_date`, `import_batch_id`, `source_type`, `source_name`, `extra_json`, `hoan_thanh_by`, `hoan_thanh_by_name`, `hoan_thanh_note`.
      * Xây dựng [services/dossier_importer.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/dossier_importer.py) nhận diện và phân loại chuẩn 5 cấu trúc biểu mẫu + hồ sơ khác từ Excel `.xlsx`/`.csv`, văn bản dán bảng và ảnh chụp bảng (`.png`/`.jpg`/`.webp` hỗ trợ Gemini Vision API qua `GEMINI_API_KEY`, macOS Apple Vision `VNRecognizeTextRequest` hoặc Tesseract CLI + tái tạo bảng tọa độ 2D):
        + `tam_tru` (10 cột, có `Ngày nộp`, `Ngày hẹn trả`, `Đơn vị xử lý`, tự cắt dòng `Tổng`/`THỐNG KÊ TỔNG HỢP`)
        + `thuong_tru` (7 cột riêng biệt không có `Ngày hẹn trả`, gắn `Địa bàn tiếp nhận`)
        + `ct10` (header 2 tầng `Lập phiếu xác minh` / `Trả lời xác minh` / `Quá hạn chưa trả lời`, bỏ dòng `Tỉnh Tuyên Quang`)
        + `tich_hop` (cả sheet tổng hợp 43 cột `CHỈ TIÊU` lẫn sub-sheet/ảnh từng nhóm giấy tờ)
        + `lam_sach` (chỉ tiêu làm sạch dữ liệu dân cư theo đơn vị)
      * Nâng cấp [routes/dossier.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/dossier.py), [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py) (`dossier_urgent_count` chỉ đếm hồ sơ có `has_deadline=True` hoặc Legacy `NULL`), và [templates/dossiers.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/dossiers.html): giao diện chia 7 tab riêng (`Tất cả`, `Tạm trú`, `Thường trú`, `Phiếu XM CT10`, `Tích hợp giấy tờ`, `Làm sạch dữ liệu`, `Hồ sơ khác`) với cấu trúc cột đặc thù từng tab, modal tải file/ảnh/dán bảng có bảng xem trước chỉnh sửa được, nút `Hoàn thành` 1 chạm + tích hàng loạt, xuất Excel (`/api/dossiers/export`), và cô lập quyền để từng Công an Xã/Phường (`unit_code`/`unit_key`) chỉ thấy và tự tích hoàn thành phần việc của đơn vị mình.
    - **Chuẩn hóa 1 nút tạo duy nhất + popup chọn hình thức trên toàn hệ thống (`18/11/2026`)**:
      * Áp dụng quy tắc UX nhất quán tại [templates/tasks_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html) (`+ Tạo công việc` -> `#chooseTaskTypeModal` chọn *Giao việc theo đề cương* `/outline-giao-viec` hoặc *Giao việc theo biểu mẫu* `/bieu-mau-giao-viec`, kèm pill lọc danh sách `Tất cả | Theo đề cương | Theo biểu mẫu`), [templates/dossiers.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/dossiers.html) (`+ Thêm hồ sơ` -> `#chooseDossierAddModal` chọn *Tải file / Ảnh bảng* hoặc *Nhập hồ sơ lẻ*, kèm nút phụ `Xuất Excel`), và [templates/contacts.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/contacts.html) (`+ Thêm liên hệ` -> `#chooseContactAddModal` chọn *Thêm từng liên hệ* hoặc *Nhập danh sách từ Excel*, chuyển link tải biểu mẫu mẫu vào trong `#importContactModal`); cập nhật [tests/test_task_form_field_scope.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_task_form_field_scope.py).
      * **Kiểm chứng sau chỉnh sửa cuối cùng**: JS syntax `node --check` exit `0` trên `tasks_rebuild.html`, `dossiers.html`, `contacts.html`; `run_tests.py` đạt **336 test / 0 fail** (`45.391s`); kiểm tra trình duyệt thật trên `http://127.0.0.1:5001` tại `/tasks`, `/dossiers`, `/contacts` ở Light Mode, Dark Mode (`1280x800`) và Mobile `390x844` đạt **0 lỗi console, 0 lỗi HTTP >=400**.
    - **Bổ sung chu kỳ báo cáo Hàng ngày (`day`) & Chọn bôi nhiều cột kiểu Excel (`19/11/2026`)**:
      * Backend `report_cycles.py` & `services/task_deadline.py`: thêm `PERIOD_DAY = "day"` ("Hàng ngày") với key `YYYY-MM-DD`, label `Ngày DD/MM/YYYY`, tính hạn trong ngày (`_periodic_bounds`, `_anchor_within`, `_periodic_cycle`, `cycles_between`, `_parse_deadline`).
      * Đồng bộ `<option value="day">Hàng ngày</option>` và panel hiển thị chu kỳ hàng ngày tại `/bieu-mau-giao-viec` (`templates/form_assign.html`), `/outline-giao-viec` (`templates/outline_assign.html`), và modal sửa cấu hình ở `/tasks` (`templates/tasks_rebuild.html`).
      * Nâng cấp bảng trực quan `#excelVisualTable` trong `templates/form_assign.html` cho phép chọn bôi nhiều cột cùng lúc (`Ctrl/⌘ + Click` bao gồm xử lý `ctrl+mousedown`/`contextmenu` trên macOS, `Shift + Click` chọn dải, hoặc kéo rê chuột trên tiêu đề cột), hiển thị số cột đang chọn tại `#colInspectorPanel` (`#inspColCountBadge`, `#btnClearMultiCol`) và áp dụng hàng loạt vai trò cột / kiểu dữ liệu / khóa cố định / % công thức; cập nhật `tests/test_report_cycles.py` và `tests/test_excel_form_workflow.py` (**338 test / 0 fail**).
    - **Cảnh báo hỏi Lưu / Không lưu / Ở lại khi thoát lúc đang cấu hình (`19/11/2026`)**:
      * Thêm helper dùng chung `static/js/unsaved-guard.js` (`pcPromptUnsavedExit`, `pcSerializeForm`, `pcAttachUnsavedGuard` chặn link điều hướng, đăng xuất, `beforeunload` và tạm tắt focus-trap Bootstrap 5 khi mở SweetAlert2 trên modal), nạp qua `templates/base.html` và `templates/base_mobile.html`.
      * Áp dụng cho `/bieu-mau-giao-viec` (`templates/form_assign.html` + lưu/khôi phục bản nháp localStorage `#formDraftRestoreBanner`), `/outline-giao-viec` (`templates/outline_assign.html` + `#outlineDraftRestoreBanner`, bảo vệ cả nút `Đổi văn bản khác`/`Đặt lại`), modal `#editConfigModal` trên `/tasks` (`templates/tasks_rebuild.html` chặn `hide.bs.modal` khi có thay đổi để hỏi `Lưu thay đổi` / `Không lưu, thoát` / `Tiếp tục sửa`), và `/tasks/import-drafts/<id>` (`templates/task_import_draft_detail.html`); cập nhật `tests/test_excel_form_workflow.py` (**339 test / 0 fail**).
    - **Nâng cấp bộ quét cấu trúc, nhãn tiêu đề, tỉ lệ độ rộng cột Excel & ánh xạ cột động cho `/dossiers` (`19/11/2026`)**:
      * `services/dossier_importer.py` & `routes/dossier.py`: bổ sung `_extract_table_structure`, `_extract_raw_header_rows` & `_extract_sheet_col_widths` / `_compute_column_width_metrics` (quét sâu 25 dòng đầu, tách nhãn tiêu đề `_pick_table_title`, đọc trực tiếp độ rộng cột từ `ws.column_dimensions` tính `col_widths` & `col_ratios` lưu vào `source_col_widths`/`source_col_ratios`, giữ nguyên 100% `raw_headers` / `exact_headers` & `raw_row` không sửa/thêm bớt tiêu đề, không điền nhầm `report_date` vào `ngay_tiep_nhan` khi trống), `_map_columns` 2 vòng, suy luận cột thiếu theo dữ liệu, lưu cột bổ sung `cong_dan`/`custom_fields` & `source_headers`/`row_cells`.
      * `templates/dossiers.html`: dùng `computeDossierColumnLayout` + `<colgroup>` với `table-layout: fixed` theo tỉ lệ cột quét từ Excel bảo đảm cột **`Thủ tục` luôn rộng nhất** (320px+), mã `Số hồ sơ` hiển thị 1 dòng gọn không gãy ngang, cột `Thao tác` sticky-pinned cạnh phải không bị cắt nửa nút trên cửa sổ hẹp (**341 test / 0 fail**).
    - **Chuẩn hóa tiêu đề nguyên bản tab `Tất cả`, quy trình `Hoàn thành` 2 bước & tinh gọn UI `/dossiers` (`19/11/2026`)**:
      * `routes/dossier.py`: `GET /api/dossiers` mặc định lọc `trang_thai=dang_xu_ly` (chỉ trả về hồ sơ chưa hoàn thành); hợp nhất `_is_dossier_awaiting_receive`, `_sync_extra_row_cells` và `_apply_dossier_status_transition` cho `POST /api/dossiers/<id>/status` và `POST /api/dossiers/bulk-status` — hồ sơ thuộc các phân hệ hồ sơ chưa có `ngay_tiep_nhan` (`Chờ tiếp nhận`) khi bấm `Hoàn thành` lần 1 chuyển sang `"Hồ sơ đang xử lý"` và gán `ngay_tiep_nhan` là ngày bấm nút (tiếp tục hiển thị ở danh sách chưa hoàn thành), chỉ hồ sơ đã có `ngay_tiep_nhan` khi bấm `Hoàn thành` mới tính xử lý xong (`trang_thai="da_tra"`).
      * `services/dossier_importer.py` (`_parse_ct10_grid`) & `templates/dossiers.html`: lưu nguyên bản `source_header_rows`, `source_headers`, `row_cells`, `col_widths`/`col_ratios` 15 cột 2 tầng cho CT10; bật ánh xạ bảng nguyên bản cho cả tab `Tất cả` & `Phiếu XM CT10` (tái hiện đúng bảng 2 tầng `Lập phiếu xác minh` / `Trả lời xác minh` / `Quá hạn chưa trả lời` cho cả dữ liệu CT10 đã lưu trước đó qua `getRowExactSchema` + `CT10_FALLBACK_HEADER_ROWS`, lẫn bảng preview upload); bỏ tiêu đề ghép `"/"`, bỏ dropdown lọc trạng thái & nút `Mở lại`; căn đều 2 cột modal upload (`File dữ liệu` / `Loại hồ sơ`, cao `44px`); nâng cấp `distributeSpecsWidth` có trần `maxPx` và kẻ lưới ngang/dọc rõ nét (`--dossier-grid-line`/`--dossier-grid-head`).
      * `tests/test_dossier_import_and_tabs.py`: cập nhật assertion tiêu đề gọn mới và bổ sung `test_two_step_completion_workflow_and_pending_only_list` (**342 test / 0 fail** qua `run_tests.py`).
    - **Quản trị danh mục tập trung & đồng bộ 2 chiều toàn hệ thống (`19/11/2026`)**:
      * `category_helpers.py` & `seed_categories.py`: mở rộng `UNIFIED_MODULE_SPECS`, `DEFAULT_UNIFIED_GROUP_SPECS`, `DEFAULT_UNIFIED_FIELD_BINDINGS` (thêm module `dossiers` / `Sổ theo dõi hồ sơ`, 2 nhóm mới `dossier_tab` / `Phân hệ hồ sơ` và `dossier_type` / `Loại hồ sơ`, và field binding `tasks.category` -> `news_domain`); bổ sung `ensure_unified_category_catalog()`, `harvest_feature_categories_to_admin()` (quét gom tự động danh mục từ `Unit`, `Task`, `TaskImportDraft`, `Contact`, `NotificationDoc`, `NewsDoc`, `DocumentLib`, `ShortLink`, `Dossier`, và các bảng legacy về quản trị trung tâm), cùng các hàm đồng bộ 2 chiều `rename_and_propagate_category_item`, `toggle_and_propagate_category_item`, `merge_category_items`, `safe_delete_category_item` (xóa ORM alias trước khi xóa item tránh lỗi `NOT NULL category_item_alias.item_id`) và `sync_unit_to_category_item`. Cập nhật `_lookup_category_item_by_ref` để bản ghi cũ giữ nguyên nhãn tiếng Việt ngay cả khi mục bị ẩn.
      * `services/dossier_importer.py`, `routes/dossier.py`, `templates/dossiers.html`, `services/task_categories.py`: bỏ danh sách tab/loại hồ sơ fix cứng, đọc động `get_dossier_tab_defs()` / `get_dossier_loai_defs()` từ `ModuleFieldBinding` & `CategoryItem`; ưu tiên `tasks.category` trong `_task_field_options()`.
      * `routes/admin.py` & `templates/module_categories.html`: chuyển hướng `/admin/categories` về `/admin/module-categories?pane=categories`; tự động gom danh mục từ các chức năng khi mở trang + nút `Gom từ chức năng`; hỗ trợ sửa tên (lan truyền sang toàn bộ dữ liệu + `Unit`/`User`/`Dossier`), ẩn/hiện, đổi thứ tự lên/xuống, gộp trùng (`#mergeItemModal`), xóa an toàn, tìm kiếm inline và giữ đúng ngữ cảnh lọc `selected_group` khi POST; đồng bộ ngược từ `/admin/units` (`add_unit`/`edit_unit`/`delete_unit`) sang nhóm `contact_unit`.
      * `tests/test_unified_categories.py` & `tests/test_task_create_wizard.py` (chỉ xóa group/item do test tự tạo thay vì xóa nhầm nhóm `Đơn vị` đã seed): toàn bộ bộ kiểm thử `run_tests.py` đạt **346 test / 0 fail** (48.832s).
    - **Cho phép kéo điều chỉnh độ rộng cột thủ công trên bảng `/dossiers` & lưu dùng chung từ Quản trị (`19/11/2026`)**:
      * [models.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/models.py) & [routes/dossier.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/dossier.py): bổ sung model `AppSetting` (`app_setting`, tự động tạo bảng trong `_ensure_dossier_schema()`), endpoint `POST /api/dossiers/column-widths` (`save`/`reset`, yêu cầu quyền `is_admin`, `403` với tài khoản đơn vị thường) lưu map `{layout_key: [widths...]}` vào DB, và trả về `column_widths_map` qua `/dossiers` và `/api/dossiers` để mọi đơn vị cùng áp dụng bố cục cột chuẩn quản trị viên đã chỉnh.
      * [templates/dossiers.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/dossiers.html): thêm thanh kéo `.dossier-col-resizer` trên các `<th>` lá (hỗ trợ cả tiêu đề 1 tầng lẫn tiêu đề 2 tầng như `Phiếu XM CT10`), kéo trực tiếp theo thời gian thực (`<colgroup>` + tổng bề rộng bảng), nhấp đúp mép cột để khôi phục 1 cột, nút `Mặc định cột` (`#btnResetColWidths`, chỉ hiện khi view hiện tại đang dùng độ rộng thủ công) và toast thông báo `#dossierColWidthToast`.
      * [tests/test_dossier_import_and_tabs.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_dossier_import_and_tabs.py): bổ sung `test_admin_manual_column_widths_persistence_and_permissions`; chạy toàn bộ `run_tests.py` đạt **347 test / 0 fail** (`50.083s`).
    - **Tối ưu giao diện Mobile tổng thể & chuyển `/dossiers` sang dạng Card trên điện thoại (`19/11/2026`)**:
      * [templates/dossiers.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/dossiers.html): trên `< 768px` ẩn hoàn toàn bảng cuộn ngang `.dossier-desktop-table-card`, thay bằng danh sách thẻ di động `.dossier-mobile-list-wrap` / `renderMobileCards()` (hồ sơ đơn lẻ: mã + badge trạng thái + thủ tục đầy đủ + grid thông tin 2 cột; bảng số liệu `Phiếu XM CT10` gom thành 2 cụm thống kê *Lập phiếu XM* / *Trả lời XM*; `Tích hợp` có nút `Chi tiết 16 nhóm`; `Làm sạch` hiển thị chip chỉ tiêu; nút `Hoàn thành`, `Sửa`, `Xóa` đạt tối thiểu `38px` dễ bấm); thu gọn 4 thẻ thống kê thành lưới `2x2`; sửa ô chọn `Tất cả đơn vị` (`col col-md-3`) không bị gãy 2 dòng và đồng bộ nút chọn tất cả `#mobileSelectAllRows`; chỉnh modal `#dossierImportDialog` vừa `100dvh`.
      * [templates/module_categories.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/module_categories.html) & [templates/module_categories_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/module_categories_mobile.html): sửa `minmax(min(100%, 380px), 1fr)` và wrap hàng thao tác danh mục để hết cắt mép phải card trên `390px`; đồng bộ bản mobile với nút `Gom từ chức năng`, `Ẩn/Hiện`, `Đưa lên/xuống`.
      * [templates/units.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/units.html), [templates/contacts.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/contacts.html), [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html): thu gọn bảng cây đơn vị và danh bạ trên `< 768px` thành 2 cột (tên + thông tin phụ ở dưới + nút thao tác luôn thấy ngay không phải cuộn ngang `936px`), rút gọn placeholder tìm kiếm danh bạ và nâng `z-index: 1060` cho `#mobileMenu` không bị thanh bottom nav đè.
    - **Thống kê 4 thẻ theo đúng từng lĩnh vực/bộ lọc, bấm lọc nhanh & khung mô phỏng Mobile (`/dossiers`, `/admin/mobile-preview`, `19/11/2026`)**:
      * [routes/dossier.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/dossier.py): tính đủ 4 chỉ số (`overdue`, `soon`, `pending`, `done`) và danh sách đơn vị (`units`) theo ĐÚNG `category_tab` (dùng `valid_tabs` động bao gồm cả phân hệ quản trị tự thêm) cùng toàn bộ bộ lọc (`unit_filter`, `q`, `loai`, `report_date`); hỗ trợ lọc nhanh `state_filter` (`overdue|soon|pending|done`) mà vẫn giữ nguyên 4 chỉ số tổng quan của lĩnh vực đang chọn.
      * [templates/dossiers.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/dossiers.html): thêm `loadRequestSeq` chống race condition khi chuyển tab nhanh, reset `unitFilterSelect`/`activeStateFilter` khi đổi lĩnh vực, và bật bấm lọc trực tiếp trên cả 4 thẻ (`Quá hạn`, `Sắp đến hạn`, `Đang xử lý`, `Đã hoàn thành`).
      * [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py) & [templates/mobile_preview.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/mobile_preview.html): thêm trang khung mô phỏng điện thoại cho quản trị viên tại `/admin/mobile-preview`.
      * [tests/test_dossier_import_and_tabs.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_dossier_import_and_tabs.py): bổ sung `test_stats_counts_change_accurately_per_tab_and_unit_filter` (**348 test / 0 fail** qua `run_tests.py`).
    - **Chuẩn hóa thương hiệu, menu trái Mobile & tối ưu nút icon/tab 1 hàng trang Quản trị danh mục (`19/11/2026`)**:
      * [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html) & [templates/base_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base_mobile.html): đổi tên hiển thị `PC06 PRO` → `Hệ thống PC06`, bỏ icon chiếc khiên cạnh thương hiệu và ô ký tự `"TÀ"` cạnh tài khoản; căn thẳng trục trái/phải (`16px`) cho menu trượt trái `#mobileMenu`, thêm nút mũi tên thu gọn/mở rộng cho các nhóm có menu con (`[data-mobile-nav-toggle]`), và bổ sung mục **Sổ theo dõi hồ sơ** (`/dossiers`) vào menu trái lẫn thanh bottom nav.
      * [templates/module_categories.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/module_categories.html): tối ưu riêng cho Mobile (`<= 768px`) mà vẫn giữ nguyên đầy đủ chữ trên Desktop — gom 3 thẻ đếm (`Nhóm`, `Phân hệ`, `Field`) thành 1 hàng 3 cột (`.cat-summary-grid`), thu 3 nút thao tác (`Gom từ chức năng`, `Thêm danh mục`, `Xóa danh mục`) thành thanh 3 nút icon gọn 1 hàng (`.cat-top-actions`), đặt 3 tab (`Nhóm`, `Danh mục`, `Liên kết`) kèm icon nằm thẳng trên 1 hàng đều nhau (`.cat-pane-tabs`), dải lọc nhóm vuốt ngang 1 hàng (`.cat-group-chip-bar`), và dùng icon gọn cho nút lưu mục (`.cat-item-save-btn` `fa-check`) và lưu liên kết field (`fa-floppy-disk`). Kiểm chứng JS syntax `node --check`, `run_tests.py` đạt **348 test / 0 fail** (`46.836s`), và kiểm tra trực quan trên trình duyệt thật tại `/admin/mobile-preview` ở cả 3 tab (`groups`, `categories`, `bindings`), Light & Dark Mode với **0 lỗi JS console, 0 lỗi HTTP >=400, 0 tràn ngang**.
    - **Màn hình Tổng hợp nhanh cho Lãnh đạo / Chỉ huy (`/tong-quan-lanh-dao`, `19/11/2026`)**:
      * [services/executive_summary.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/executive_summary.py): xây dựng `build_executive_summary()` (tự phân phạm vi `Toàn tỉnh` cho Quản trị hệ thống & cấp CAT như `Lãnh đạo - Chỉ huy CAT`, và tự cô lập theo đơn vị cho cấp CAX/đơn vị), tổng hợp số liệu hồ sơ theo trạng thái (`overdue`, `soon`, `pending`, `done`), chi tiết từng lĩnh vực động (kèm số liệu tổng phiếu/đã trả lời/quá hạn của `Phiếu XM CT10`), bảng xếp hạng đơn vị cần đôn đốc theo mức độ ưu tiên, tổng hợp tiến độ báo cáo công việc & định kỳ, và xuất Excel 3 sheet (`export_executive_summary_xlsx`).
      * [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py), [routes/dossier.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/dossier.py) & [templates/executive_overview.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/executive_overview.html): thêm route `/tong-quan-lanh-dao` (alias `/admin/overview`), `/api/executive-summary`, `/api/executive-summary/export`; cho phép `Lãnh đạo - Chỉ huy CAT` xem danh sách hồ sơ toàn tỉnh (read-only) khi bấm drill-down; tích hợp banner `Tổng hợp nhanh Lãnh đạo` trên [templates/admin_dashboard.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard.html) & [templates/admin_dashboard_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard_mobile.html), nút `Tổng hợp` (dạng icon trên Mobile) + hỗ trợ tham số URL `?tab=&unit=&state=`, tách dòng nhãn trạng thái (`.dossier-mcard-badges`) xuống dưới mã hồ sơ (`.dossier-mcard-code` `white-space: nowrap` 1 dòng), đưa `Thủ tục` (`span-2`) vào trong khung `.dossier-mcard-meta` và xếp `Trạng thái hồ sơ` sang cột phải ngay dưới `Cán bộ` trên [templates/dossiers.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/dossiers.html), mục menu trong [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html) / [templates/base_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base_mobile.html), và nút pill `Lãnh đạo` trên [templates/mobile_preview.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/mobile_preview.html).
      * [tests/test_executive_summary.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_executive_summary.py): kiểm chứng số liệu tổng hợp, xếp hạng đơn vị, phân quyền `CAT` vs `CAX`, mobile UA và xuất Excel 3 sheet; tinh gọn giao diện `/tong-quan-lanh-dao` chỉ giữ các chỉ số cốt lõi dễ quét mắt (1 hàng header, 4 thẻ số lớn không chữ phụ, thẻ lĩnh vực chỉ hiện chip có số liệu > 0, danh sách đơn vị 1 dòng/đơn vị); toàn bộ bộ kiểm thử `run_tests.py` đạt **351 test / 0 fail** (`47.364s`).
    - **Chuẩn hóa hệ thống tài khoản 4 khối đơn vị & rà soát giao diện/thao tác toàn hệ thống (`19/11/2026`)**:
      * [utils.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/utils.py), [scripts/admin/seed_two_tier_government_accounts.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/scripts/admin/seed_two_tier_government_accounts.py), [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py), [templates/roles.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/roles.html), [templates/roles_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/roles_mobile.html) & [tests/test_seed_two_tier_accounts.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/tests/test_seed_two_tier_accounts.py):
        + Chuẩn hóa `build_account_username` & `build_role_account_username` và đồng bộ toàn bộ CSDL local (`1.061` tài khoản / `271` đơn vị, xóa sạch mã cũ `admin_*`/`bc_*`):
          - **Công an Xã / Phường**: `<cax|cap><ten>` (`caxminhquang`, `capantuong`) + tài khoản nội bộ `<cax|cap><ten>_chihuy`, `<cax|cap><ten>_canbo`, `<cax|cap><ten>_quantri`.
          - **UBND Xã / Phường**: `<ubndxa|ubndphuong><ten>` (`ubndxaminhquang`, `ubndphuongantuong`) + tài khoản nội bộ `<ubndxa|ubndphuong><ten>_lanhdao`, `<ubndxa|ubndphuong><ten>_chuyenvien`, `<ubndxa|ubndphuong><ten>_quantri`.
          - **Sở, Ban, Ngành**: `<tensonganh>_lanhdao`, `<tensonganh>_chuyenvien`, `<tensonganh>_quantri` (ví dụ `sokhoahoccongnghe_lanhdao`, `sokhoahoccongnghe_chuyenvien`, `sokhoahoccongnghe_quantri`).
          - **Phòng nội bộ Công an tỉnh**: `<tenphong>_quantri`, `<tenphong>_lanhdao`, `<tenphong>_canbo` (ví dụ `thammuu_quantri`, `thammuu_lanhdao`, `thammuu_canbo`).
        + Trên `/roles`: tự động gợi ý tên đăng nhập chuẩn ngay khi chọn **Đơn vị** + **Vai trò** trong modal Thêm tài khoản; bỏ giá trị mặc định lỗi `value="123"` ở ô mật khẩu (để trống tự sinh mật khẩu mạnh); thu gọn bảng tài khoản trên Mobile không tràn ngang.
      * [templates/tasks_rebuild.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html), [templates/admin_dashboard.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard.html), [templates/outline_assign.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/outline_assign.html), [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py): đổi `Quản lý công việc & báo cáo` thành **`Quản lý công việc`**; đặt tiêu đề `Quản lý công việc` bên trái và nút `+ Tạo công việc` bên phải trên cùng 1 hàng ở cả Mobile & Desktop, mở rộng 3 pill lọc và ô tìm kiếm full-width trên Mobile, sửa câu hướng dẫn trống; đồng bộ số thẻ KPI `Hồ sơ TTHC sát/quá hạn` (`83`) trên `/admin` khớp 100% với `Tổng hợp Lãnh đạo`.
    - **Tổng rà soát & tối ưu giao diện toàn hệ thống Mobile & PC (`19/11/2026`)**:
      * [static/css/bdhvs-layout.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/bdhvs-layout.css) (`?v=2.2.8` trong [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html)): gỡ ép `width: 100%` ở `.pc06-page-actions` và bỏ `min-width: 148px` trên nút `.pc06-panel-head`/`.pc06-toolbar-actions` ở Mobile (`<= 768px`) để tiêu đề và nút CTA nằm gọn 1 hàng, không cắt cụt tiêu đề.
      * [templates/thong_bao.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/thong_bao.html): gom nút `Đăng thông báo`/`Đăng tin` ngang hàng tiêu đề `Tất cả lĩnh vực`, xếp 4 tab `Tất cả | Bản tin | Tài liệu | Video` gọn trên 1 hàng duy nhất ở Mobile (`.pc06-notify-tabs`).
      * [templates/contacts.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/contacts.html): gom `+ Thêm liên hệ`/`+ Thêm` ngang hàng tiêu đề `Tất cả nhóm` (kèm badge tổng số liên hệ inline), bỏ nhãn `0 liên hệ` lạc lõng dưới ô tìm kiếm.
      * [templates/shortlinks.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/shortlinks.html): xếp 3 ô thống kê `Tổng liên kết`, `Tổng lượt mở`, `Phạm vi` thành lưới 3 cột 1 hàng (`.shortlink-summary-grid`), đặt `Danh sách liên kết` và `+ Tạo liên kết`/`+ Tạo mới` cùng 1 hàng, bảng responsive Mobile 2 cột không tràn ngang.
      * [routes/admin.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py) (`_summarize_role_permissions`) & [templates/roles.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/roles.html):
        + Tab **Vai trò**: loại bỏ danh sách 20 pill quyền rối mắt và thanh cuộn trong thẻ; nhóm quyền gọn theo từng phân hệ với 1 cấp quyền cao nhất (`Xử lý` / `Thực hiện` / `Xem`, hoặc nhãn `Toàn quyền hệ thống`) dạng ma trận 2 cột (`.role-perm-matrix`), đặt `+ Thêm vai trò` ngang hàng tiêu đề.
        + Tab **Tài khoản**: gom 4 nút thao tác (`Xuất Excel`, `Nhập Excel`, `Reset ĐV`, `Thêm tài khoản`) thành thanh 4 nút icon gọn 1 hàng trên Mobile (`.users-action-bar`), bổ sung ô tìm kiếm nhanh `#userLiveSearch` cạnh bộ lọc vai trò, cố định cấu trúc bảng `#usersMainTable` trên Mobile (`table-layout: fixed`, tự ngắt tên đăng nhập dài `break-all`, cột 3 nút thao tác `96px` luôn hiển thị đủ không bị cắt mép).
      * Mở rộng tối ưu đồng bộ các màn hình hệ thống khác: [templates/units.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/units.html) (1 hàng tiêu đề + tìm kiếm nhanh `#unitLiveSearch`), [templates/logs.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/logs.html) (lưới thống kê 2×2 + 2 nút 1 hàng + bảng Mobile 1 cột), [templates/delegations.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/delegations.html) (1 hàng tiêu đề + bảng Mobile 2 cột + modal `col-12 col-md-6`), [templates/db_tool.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/db_tool.html) (lưới 2 cột + tab 2 cột Mobile), [templates/admin_center.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_center.html) (tối ưu padding Mobile + bỏ icon thừa ở danh sách mục), [templates/system_update.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/system_update.html) (3 tab 1 hàng Mobile + `.pc06-page-summary` tự chia lưới gọn trong `bdhvs-layout.css?v=2.2.9`), [templates/module_categories.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/module_categories.html) (thu gọn nút `.cat-op-btn` `28px` để ô nhập tên rộng rõ trên PC và đủ 5 nút trên 1 hàng trên Mobile).
      * Tinh gọn triệt để **Trang chủ** ([templates/admin_dashboard.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard.html) & [templates/admin_dashboard_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/admin_dashboard_mobile.html)) và đổi tên nhất quán màn hình tổng hợp: xếp 4 thẻ KPI thành **lưới 2×2** trên Mobile (`4×1` trên PC), bỏ nhãn `Bàn Làm Việc Chức Năng` (và đổi nút quay về thành `Trang chủ` trong [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html)), bỏ toàn bộ icon box thừa trên banner tổng hợp & 8 ô chức năng (chuyển sang thẻ chữ sạch với viền nhấn cạnh trái), đổi tiêu đề `"Tổng hợp nhanh Lãnh đạo"` / `"Tổng hợp Lãnh đạo"` thành **`Tổng hợp số liệu`** xuyên suốt `admin_dashboard*.html`, `executive_overview.html`, `base*.html`, `mobile_preview.html`, `dossiers.html`, `routes/admin.py`, `tests/test_executive_summary.py`, và hiển thị trạng thái trống rõ ràng cho biểu đồ donut khi chưa có dữ liệu báo cáo.
      * **Xử lý triệt để nguyên nhân gốc CSS & nạp bộ chuẩn UI/UX** ([.agents/skills/pc06-ui-design-standards/SKILL.md](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/.agents/skills/pc06-ui-design-standards/SKILL.md) tổng hợp từ `ui-ux-pro-max-skill`, Vercel `web-design-guidelines`, Anthropic `frontend-design`):
        + [static/css/style.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/style.css) (`?v=4.2.3`) & [static/css/bdhvs-layout.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/bdhvs-layout.css) (`?v=2.3.0`): gỡ `white-space: nowrap` trên `.table td` ở Mobile (nguyên nhân chữ dài vẽ đè lên nút thao tác), giảm `minmax(180px, 1fr)` → `minmax(120px, 1fr)` và thêm breakpoint `1180px` cho `.pc06-page-summary-bar` (hết lỗi 3 thẻ summary xếp dọc ở màn hình laptop `1024px–1200px`).
        + [templates/roles.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/roles.html): sửa lỗi khoảng trắng `240px` trên Mobile do `flex-basis: 240px` khi đổi sang `flex-direction: column` (chuyển sang CSS Grid + `flex: 0 0 auto`), khóa nút thùng rác (`.role-delete-btn` `34px`) nằm gọn 100% trong thẻ Vai trò, và ép `white-space: normal` + cột thao tác `104px` cố định trên `#usersMainTable`.
        + [templates/logs.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/logs.html): mở thẳng danh sách **Nhật ký hoạt động** (chỉ giữ 2 tab sạch `Nhật ký hoạt động` | `Bảo mật 7 ngày`), bỏ icon lộn xộn ở nút hành động, gom bộ lọc (`Từ ngày`, `Đến ngày`, `Người dùng`, `Lọc`, `Đặt lại`) thành **1 hàng ngang gọn** trên Desktop (và lưới 2 cột gọn trên Mobile).
        + [templates/module_categories.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/module_categories.html): cố định 3 cột `.cat-summary-grid` ở mọi độ rộng (`390px`, `1024px`, `1280px`), ẩn tiêu đề lặp khi lọc 1 nhóm, đổi nhãn code hồng thành chữ phụ tinh tế.
        + **Chuẩn hóa đồng nhất kích cỡ toàn bộ Control (`input`, `select`, `search`, `button`, `tab`) trên toàn hệ thống Mobile & PC** ([static/css/pc06-premium.css](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/static/css/pc06-premium.css) `?v=1.5.3` đồng bộ cả 5 template nạp nó): áp dụng thang 3 bậc token từ `ui-ux-pro-max-skill` / Vercel `web-design-guidelines` (`--pc-control-h-sm: 34px`, `--pc-control-h-md: 40px` PC / `38px` Mobile, `--pc-control-h-lg: 46px` PC / `44px` Mobile), chuẩn hóa `<select>` dùng `padding-block: 0; line-height: calc(var(--pc-control-h-*) - 2px)` để chữ căn giữa dọc, căn giữa tuyệt đối thương hiệu `Hệ thống PC06` trên topbar Mobile (`padding: 0`), và gỡ toàn bộ override chiều cao cứng rời rạc trên 12 template Mobile.
        + **Khắc phục triệt để lỗi nghẽn production LiteSpeed `lswsgi` (`2013 Lost connection` + `PendingRollbackError` + `89 MB stderr.log`, `20/11/2026`)**:
          - [app.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/app.py): đóng sạch pool kết nối (`db.session.remove()` + `db.engine.dispose()`) ngay sau `init_db(app)`, đăng ký `os.register_at_fork(after_in_child=...)` và SQLAlchemy `@event.listens_for(Engine, 'checkout')` kiểm tra `pid` chống chia sẻ chung socket MariaDB giữa master & worker con sau `fork()`; tự động `db.session.rollback()` trong `teardown_request` / `errorhandler(500)` / `errorhandler(Exception)` ngăn dây chuyền `PendingRollbackError`; giảm `pool_recycle` từ `3600s` → `240s` + `pool_size=5`, `max_overflow=5`, `connect_timeout=10`; tắt `TEMPLATES_AUTO_RELOAD` trên production (`bool(DEBUG)`); thay `from openpyxl.utils import get_column_letter` mỗi request bằng hàm thuần Python `_excel_col_letter`.
          - [services/task_scheduler.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/services/task_scheduler.py): tắt mặc định luồng `APScheduler` khi chạy dưới `PC06_PASSENGER=1` (tránh `fork()` tiến trình đa luồng trên LiteSpeed; có thể chạy watchdog qua cron cPanel/DirectAdmin).
          - [templates/base.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base.html) & [templates/base_mobile.html](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/base_mobile.html): tăng chu kỳ poll `/api/notifications` từ `10s` → `60s` và dừng hẳn khi ẩn tab trên cả Mobile & PC; sửa câu `print` cuối [seed_categories.py](file:///Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/seed_categories.py). Kiểm thử `run_tests.py` đạt **351 test / 0 fail**.
4. **Môi trường test local**: `.venv` trong dự án KHÔNG còn tồn tại. Dùng env cô lập đã cài đủ
   requirements: `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py`.
5. **Gỡ route trùng** `task_export_outline_docx` (`routes/tasks.py:174`) hoặc v2 — giữ đúng 1,
   chạy lại `run_tests.py` (đề nghị #2 báo cáo DA06).
6. **Xác nhận trạng thái GitHub Actions** (mở tab Actions của repo). Nếu đỏ do bước 3: sau khi
   fix + push, deploy FTP sẽ tự chạy lại. Nếu cần deploy khẩn không qua CI, làm thủ công theo
   `DEPLOY_CPANEL.md` (upload zip + `touch tmp/restart.txt`).
7. **Smoke test giao diện light/dark trên trình duyệt thật**: [ĐÃ XONG 18/11/2026 trên desktop `1280x800` / `1024x800` và mobile `390x844` với `pc06-premium.css?v=1.4.2`, `bdhvs-layout.css?v=2.2.6` qua các luồng chính `/admin`, `/bieu-mau-giao-viec`, `/tasks`, `/tasks/<id>`, `/dossiers`, `/admin/units`, `/admin/system-center`, `/admin/module-categories`, `/contacts`].
8. **Trả 400 khi `deadline` sai định dạng** ở `/api/create-outline-task`
   (`routes/outline.py` / `services/task_admin.py` — cần rà vị trí chính xác) thay vì bỏ qua âm thầm.
9. (Đường dài, theo `THIET_KE_CHUC_NANG_TASK_CUOI.md`) Hoàn thiện pha FORM + tổng hợp Excel;
   gọn dần `TaskParticipant`; sau khi dữ liệu mới ổn định mới dọn bảng/logic cũ.
10. **Điểm danh — hai điểm cần quyết định khi chạy thật** (08/10/2026):
    - Rate limit nền `app.py` là 240 req/phút cho mỗi (IP, endpoint); một hội trường vài trăm
      người quét cùng lúc trên 1 IP có thể nhận 429. Nếu xảy ra: nâng `RATE_LIMIT_MAX_REQUESTS`
      qua env hoặc cân nhắc endpoint riêng cho `/diem-danh/submit`.
    - Trang public chỉ báo trùng SAU khi bấm. Muốn hiện "bạn đã điểm danh lúc …" ngay khi mở
      trang thì thêm 1 endpoint JSON public đọc `X-Device-Token` (đã có khóa device trong
      localStorage), chưa làm vì nằm ngoài phạm vi yêu cầu.

---

## 5. Lệnh nhanh tra cứu

```bash
cd /Users/thenhung/Documents/GitHub/PhanMemPC06_Pro

# Chạy server dev (tự venv, tự migrate; dừng: ./stop_server.sh) → http://localhost:5000
./START_SERVER_MAC.sh                     # hoặc: .venv/bin/python app.py
PC06_PORT=5001 .venv/bin/python app.py    # đổi port khi 5000 bận

# Test (LUÔN dùng runner này — ép SQLite tạm, KHÔNG chạy python -m unittest trực tiếp)
~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py   # env đã cài sẵn
.venv/bin/python run_tests.py                                        # nếu .venv đã được tạo lại

# Migration / backfill runtime
.venv/bin/python migrate.py --dry-run
.venv/bin/python migrate.py               # start_server.sh tự chạy; tắt: PC06_SKIP_MIGRATE=1

# Reset admin / mật khẩu (script admin bắt buộc PC06_CONFIRM=YES)
PC06_CONFIRM=YES .venv/bin/python scripts/admin/reset_admin.py

# Lỗi "database is locked"
pkill -f "python.*app.py" && rm -f pc06_system.db-journal

# Log ứng dụng
tail -f logs/app.log

# Backup SQLite dev
cp pc06_system.db "backups/pc06_system_$(date +%Y%m%d_%H%M%S).db"

# Deploy production: git push origin main → CI chạy test → FTP tự đẩy.
# Restart Passenger sau khi sửa config trên host: touch tmp/restart.txt
# Backup MySQL prod (cron 02:30 hằng đêm, giữ 14 ngày): scripts/admin/backup_mysql.sh
```

---

## 6. Bài học / vấn đề đã gặp

**Bug đã sửa (đừng lặp lại):**
- `routes/admin.py` từng thiếu decorator `@admin_bp.route('/admin')` cho `index()` → 404 trang chủ
  (sửa 06/08, xem `BAO_CAO_SUA_LOI_20260806.md`).
- **Gọi sai chữ ký `can_view_task`**: helper thật nhận `(task, session_uid, is_admin, is_lead,
  is_executor, can_manage, can_watch, ...)`; gọi kiểu `can_view_task(g, task_id)` luôn trả False
  → 403 export. Dùng helper chuẩn `_can_view_task(task)` của `routes/tasks.py` và nạp task bằng
  `db.session.get(Task, task_id)`.
- Thiếu import `export_outline_docx` từ `services/task_report_aggregate.py` → NameError 500.
- Lỗi Flask 2 route cùng URL: **route định nghĩa SAU CÙNG thắng** — v1 thành mã bóng
  (`routes/tasks.py:174` vs `:944`).
- CSS: class copy-paste nền sáng cứng (`rgba(248,250,252,.92)`) chìm chữ ở dark mode — luôn token hóa
  `var(--pc-*)`; rule `content: "Chọn tệp"` trong `style.css` làm hỏng file input Chromium (M14).
- Flash message mobile từng dùng Bootstrap alert → đã chuyển về Swal helper (M4); tại `templates/base.html` đọc qua `<span data-pc-flash data-message="{{ message }}">` (`dataset.message`) để vừa an toàn JS vừa giữ nguyên UTF-8 cho test HTML (tránh `|tojson` escape `\uXXXX`).

**Gotchas vận hành:**
- cPanel Python mặc định rất cũ (3.6) — bắt buộc tìm Python ≥ 3.9 hoặc dùng "Setup Python App";
  không chạy `python3 -m pip` trực tiếp (`DEPLOY_CPANEL.md`).
- Passenger: giữ 1–2 process để APScheduler không nhân bản job watchdog; bản sao phụ đặt
  `PC06_TASK_SCHEDULER=0`.
- `.htaccess` đã chặn `.env*`, `*.db`, `scripts/`, `tests/`, `docs/`… — không xóa file này.
- `.env` prod phải chmod 600; `FLASK_ENV=production` bật SESSION_COOKIE_SECURE + ép HTTPS
  (cần AutoSSL trước); `DATABASE_URL` MySQL host-local; `PC06_DATA_DIR` NGOÀI public_html.
- Test luôn ghi DB thật nếu chạy sai cách → chỉ dùng `run_tests.py`; script admin yêu cầu
  `PC06_CONFIRM=YES` (chống thao tác nhầm trên prod).
- Mọi POST cần CSRF token (`X-CSRF-Token` header hoặc field `csrf_token`) — cả script test
  (`scripts/test_da06_input.py`) phải gửi header này.
- Sửa CSS xong phải bump `?v=` của đúng file CSS đó trong MỌI template nạp nó, nếu không
  người dùng giữ cache cũ.
- Local dev DB là `pc06_system.db` SQLite ở root (có file `-journal` là bình thường); DB prod
  là MariaDB — schema migrate tự chạy lúc khởi động app, không cần SQL thủ công.
- Baseline test theo từng thời điểm: trước 26/08 là 222 test/4 fail; 31/08 là 281 test/3 fail;
  14/09 là 300 test/2 fail; 08/10 là 325 test/2 fail; sau fix UI/E2E trước đó là 322 test/0 fail;
  sau luồng Biểu mẫu Excel `FORM` (18/11/2026): **326 test / 0 fail**; sau tách `/bieu-mau-giao-viec`
  và tinh gọn UI/Dark Mode/Mobile (18/11/2026): **330 test / 0 fail**; hiện tại sau nâng cấp biểu mẫu
  trực quan 2 cột + công thức + tự sinh dòng đơn vị (18/11/2026): **332 test / 0 fail**; sau nâng cấp Sổ theo dõi thời hạn hồ sơ & chỉ tiêu hàng ngày đa biểu mẫu Excel / OCR (`/dossiers`, 18/11/2026): **336 test / 0 fail**; sau bổ sung chu kỳ `Hàng ngày` & chọn bôi nhiều cột kiểu Excel (`19/11/2026`): **338 test / 0 fail**; sau cơ chế cảnh báo hỏi lưu khi thoát cấu hình (`19/11/2026`): **339 test / 0 fail**; sau nâng cấp quét cấu trúc, nhãn tiêu đề & tỉ lệ độ rộng cột động (`/dossiers`, 19/11/2026): **341 test / 0 fail**; sau chuẩn hóa tiêu đề nguyên bản tab `Tất cả`, quy trình `Hoàn thành` 2 bước & tinh gọn UI `/dossiers` (`19/11/2026`): **342 test / 0 fail**; sau tập trung danh mục về Quản trị hệ thống & đồng bộ 2 chiều (`19/11/2026`): **346 test / 0 fail**; sau bổ sung kéo chỉnh độ rộng cột thủ công trên `/dossiers` & lưu DB từ Quản trị (`19/11/2026`): **347 test / 0 fail**; hiện tại sau tối ưu thống kê 4 thẻ theo đúng từng lĩnh vực/bộ lọc & khung mô phỏng mobile (`/dossiers`, `/admin/mobile-preview`, `19/11/2026`): **348 test / 0 fail**; hiện tại sau bổ sung màn hình **Tổng hợp nhanh Lãnh đạo** (`/tong-quan-lanh-dao`, `19/11/2026`): **351 test / 0 fail** (chạy qua `run_tests.py`). Ghi rõ baseline trong mọi CHANGELOG entry.
