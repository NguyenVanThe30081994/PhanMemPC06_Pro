# MEMORY — PhanMemPC06_Pro

> File này ghi lại toàn bộ kiến trúc, trạng thái, quyết định và việc cần làm của dự án
> để Agent phiên làm việc mới đọc ĐẦU TIÊN là nắm được toàn bộ mã nguồn và biết việc tiếp theo.
> Cập nhật mỗi khi thay đổi trạng thái. (Cập nhật lần cuối: 2026-08-31)

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
- Local `.venv` đang là **Python 3.14.7**; prod yêu cầu Python ≥ 3.9 (khuyến nghị 3.11/3.12 —
  `DEPLOY_CPANEL.md`).

**Entrypoint:**
- Dev: `app.py` (chạy trực tiếp, host/port qua `PC06_HOST`/`PC06_PORT`, mặc định 127.0.0.1:5000),
  hoặc `./START_SERVER_MAC.sh` → forward sang `start_server.sh` (tự tạo venv, tự migrate).
- Prod cPanel: `passenger_wsgi.py` → import `app` của `app.py` (set `PC06_PASSENGER=1`).

**DB & config:**
- ORM toàn bộ trong `models.py` (~30 bảng). Schema migrate **tự động lúc khởi động**
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
  `csrf_token`); `after_request` security headers + CSP + HSTS. Đăng ký 9 blueprint, khởi động
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
  Excel, reset mật khẩu bulk), `/admin/units`, `/admin/delegations`, `/logs`, `/admin/db-tool`,
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

**Test:** `tests/` — 31 module, **281 test**. Runner duy nhất: `python3 run_tests.py` (tự ép DB
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
- Đã sửa 4 nhóm lỗi 06/08/2026 (`BAO_CAO_SUA_LOI_20260806.md`): `/admin` 404, sidebar toggle,
  layout reauth, class CSS dark mode.
- Đã sửa 3 lỗi ĐA06 26/08: L1 (403 export do gọi sai chữ ký `can_view_task`), L2 (thiếu import
  `export_outline_docx`), L3 (đồng bộ 302/403) trong `routes/tasks.py` + `tests/test_task_outline_word_export.py`.

### 🚧 Đang dở / cần xử lý
- **Suite 281 test còn 3 lỗi có sẵn** (đã chạy lại xác thực ngày 31/08/2026 bằng
  `.venv/bin/python run_tests.py`):
  1. `tests/test_report_aggregate` — **ImportError: No module named 'pytest'** (requirements.txt
     có pytest nhưng `.venv` local chưa cài; lỗi môi trường, không phải code).
  2. `tests.test_task_synthesis.TaskSynthesisTests.test_save_synthesis_then_export_uses_synthesis`
  3. `tests.test_task_synthesis.TaskSynthesisTests.test_clear_synthesis_falls_back_to_auto_merge`
     — Cả 2: Word tổng hợp hiện chèn tiền tố `assign_N:` (`services/task_report_aggregate.py`
     dòng 74/94/96) nên `assertIn("Văn bản tổng hợp...")` thuần không khớp
     (`tests/test_task_synthesis.py:184` và `:211`).
- **2 route trùng URL** `/tasks/<id>/export-outline.docx`: `routes/tasks.py:174`
  (`task_export_outline_docx`) và `routes/tasks.py:944` (`export_outline_task_word`) — Flask chỉ
  chạy route định nghĩa sau (v2); v1 là "mã bóng" cần gỡ (khuyến nghị #2 của báo cáo DA06).
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

1. **Sửa 2 test `test_task_synthesis` để mở khóa CI/CD** (ưu tiên cao nhất — đang làm pipeline
   deploy đỏ). Chọn 1 hướng rồi nhất quán:
   - Nếu tiền tố `assign_N: ` là định dạng chuẩn → sửa assert trong
     `tests/test_task_synthesis.py:184` và `:211` (ví dụ kỳ vọng `"assign_1: Đoạn văn của Đội A."`).
   - Nếu định dạng cũ (đoạn thuần) là chuẩn → sửa phần ghép đoạn trong
     `services/task_report_aggregate.py` / `_export_outline_word_v2` để không chèn nhãn.
   Sau khi sửa, baseline mới là **281 test / 0 fail** — mọi thay đổi sau này không được tăng lỗi.
2. **Cài `pytest` vào `.venv`** (`.venv/bin/pip install pytest`) để hết ImportError của
   `tests/test_report_aggregate` khi chạy local; giữ `pytest` trong `requirements.txt` cho CI.
3. **Gỡ route trùng** `task_export_outline_docx` (`routes/tasks.py:174`) hoặc v2 — giữ đúng 1,
   chạy lại `run_tests.py` (đề nghị #2 báo cáo DA06).
4. **Xác nhận trạng thái GitHub Actions** (mở tab Actions của repo). Nếu đỏ do bước 1: sau khi
   fix + push, deploy FTP sẽ tự chạy lại. Nếu cần deploy khẩn không qua CI, làm thủ công theo
   `DEPLOY_CPANEL.md` (upload zip + `touch tmp/restart.txt`).
5. **Smoke test giao diện light/dark trên trình duyệt thật** các trang vừa bump CSS (M5–M14:
   tasks, roles, contacts, links, logs, db_tool…), kiểm tra droplist/file input sau M14.
6. **Trả 400 khi `deadline` sai định dạng** ở `/api/create-outline-task`
   (`routes/outline.py` / `services/task_admin.py` — cần rà vị trí chính xác) thay vì bỏ qua âm thầm.
7. (Đường dài, theo `THIET_KE_CHUC_NANG_TASK_CUOI.md`) Hoàn thiện pha FORM + tổng hợp Excel;
   gọn dần `TaskParticipant`; sau khi dữ liệu mới ổn định mới dọn bảng/logic cũ.

---

## 5. Lệnh nhanh tra cứu

```bash
cd /Users/thenhung/Documents/GitHub/PhanMemPC06_Pro

# Chạy server dev (tự venv, tự migrate; dừng: ./stop_server.sh) → http://localhost:5000
./START_SERVER_MAC.sh                     # hoặc: .venv/bin/python app.py
PC06_PORT=5001 .venv/bin/python app.py    # đổi port khi 5000 bận

# Test (LUÔN dùng runner này — ép SQLite tạm, KHÔNG chạy python -m unittest trực tiếp)
.venv/bin/python run_tests.py

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
- Baseline test theo từng thời điểm: trước 26/08 là 222 test/4 fail; hiện 281 test/3 fail
  (sau khi fix mục 4.1–4.2 sẽ là 281/0). Ghi rõ baseline trong mọi CHANGELOG entry.
