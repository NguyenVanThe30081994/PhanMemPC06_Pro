# MEMORY — PhanMemPC06_Pro

> File này ghi lại toàn bộ kiến trúc, trạng thái, quyết định và việc cần làm của dự án
> để Agent phiên làm việc mới đọc ĐẦU TIÊN là nắm được toàn bộ mã nguồn và biết việc tiếp theo.
> Cập nhật mỗi khi thay đổi trạng thái. (Cập nhật lần cuối: 2026-11-13)

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

**Test:** `tests/` — 35 module, **325 test**. Runner duy nhất: `python3 run_tests.py` (tự ép DB
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
4. **Môi trường test local**: `.venv` trong dự án KHÔNG còn tồn tại. Dùng env cô lập đã cài đủ
   requirements: `~/.workbuddy-ai/binaries/python/envs/pc06/bin/python run_tests.py`.
5. **Gỡ route trùng** `task_export_outline_docx` (`routes/tasks.py:174`) hoặc v2 — giữ đúng 1,
   chạy lại `run_tests.py` (đề nghị #2 báo cáo DA06).
6. **Xác nhận trạng thái GitHub Actions** (mở tab Actions của repo). Nếu đỏ do bước 3: sau khi
   fix + push, deploy FTP sẽ tự chạy lại. Nếu cần deploy khẩn không qua CI, làm thủ công theo
   `DEPLOY_CPANEL.md` (upload zip + `touch tmp/restart.txt`).
7. **Smoke test giao diện light/dark trên trình duyệt thật** các trang vừa bump CSS (M5–M14:
   tasks, roles, contacts, links, logs, db_tool…), kiểm tra droplist/file input sau M14.
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
- Flash message mobile từng dùng Bootstrap alert → đã chuyển về Swal helper (M4); giữ nguyên quoting
  flash `|tojson` (escape unicode làm vỡ test chức năng).

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
  14/09 là 300 test/2 fail; hiện **325 test/2 fail** (thêm 25 test Điểm danh 08/10, vẫn đúng
  2 lỗi nền `test_task_synthesis` — sau khi fix mục 4.3 sẽ là 325/0). Ghi rõ baseline trong mọi
  CHANGELOG entry.
