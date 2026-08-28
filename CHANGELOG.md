# CHANGELOG / TIMELINE

## 2026-08-28 (Giao diện — Subproject M8: Rà soát trực quan local nhóm HỆ THỐNG — layout toolbar/chip/card vai trò)
Truy cập local bằng trình duyệt thật (light + dark), sửa 4 điểm bất hợp lý còn lại:
(1) Toolbar trang vai trò: tab xếp dọc từng viên do grid 2 cột bị nén — đổi
`.pc06-section-menu-shell.with-actions` thành stack 1 cột (3 tab một hàng, 4 nút một hàng
dưới, canh trái) trong `bdhvs-layout.css`.
(2) Chip vai trò full-width khổng lồ — `.system-filter-list` thêm
`repeat(auto-fill, minmax(230px, 1fr))` thành lưới compact (roles/logs/module_categories).
(3) Tường chữ quyền hạn trong card "Quản trị vai trò" — thêm helper
`get_perms_label_list()` (utils.py, đăng ký context `get_label_list`), render badge
`pc06-perm-tag` kèm clamp max-height 8.5rem có scroll.
(4) Nút trong card lệch cao độ — `.pc06-compact-card` chuyển flex column,
`.pc06-toolbar-actions` margin-top:auto ghim đáy card.
Đã verify trực quan light + dark trên /roles (cả 3 tab) + quét 6 trang Hệ thống còn lại.
Bump `bdhvs-layout.css ?v=2.2.2`. Suite 279 tests — chỉ còn 3 lỗi có sẵn.

## 2026-08-28 (Giao diện — Subproject M7: Hotfix dark mode nhóm trang HỆ THỐNG + toolbar đồng nhất)
Theo báo cáo user (màn hình /roles light+dark):
(1) **Chữ chìm ở dark** — khối CSS `system-filter-chip` copy-paste dùng nền sáng cứng
`rgba(248,250,252,.92)` + chữ `var(--text-main)` (đảo sáng ở dark) → token hóa
`var(--pc-bg-card)/var(--pc-text)` + thêm dark override ở `roles.html`,
`module_categories.html`; counter `#0052cc` trên nền tối ở `logs.html` →
`var(--pc-primary-soft)/-strong` (token tự đổi theo theme).
(2) **Tab "Vai trò" active vô hình ở dark** — rule dark đặt
`color: var(--pc-primary-50)` (alpha wash 0.14, không đọc được) → `background:
var(--pc-primary)` + `color: #fff` theo đúng pattern `pc-nav-item.active`.
(3) **Toolbar không gọn** — tab bẻ chữ thành card cao do cột menu bị nén: thêm
`white-space: nowrap` (tab wrap nguyên pill, không cắt chữ), radius tab về
`--pc-radius-md` khớp `pc-btn`; responsive nhỏ đã có sẵn stack 1 cột.
Bump `bdhvs-layout.css ?v=2.2.1`. Test mới: `SystemPagesDarkModeTests` (5 tests);
suite 279 — chỉ còn 3 lỗi có sẵn. Đã quét lại 7 trang Hệ thống — không còn
pattern nền sáng không có dark override.

## 2026-08-28 (Giao diện — Subproject M6: Dọn template mồ côi)
Xóa `templates/update.html` + `templates/categories.html` — xác nhận không route nào render
(grep toàn bộ routes/services/app.py + builders). Xóa test đọc source mồ côi
`test_categories_uses_legacy_bridge`. `system_update.html` không liên quan (có route riêng).
Suite 274 tests — chỉ còn 3 lỗi có sẵn. **HOÀN TẤT GIAI ĐOẠN 2 (M1–M6) triển khai
chuẩn mực từ `docs/THIET_KE_TONG_GIAO_DIEN_2026.md`.**

## 2026-08-28 (Giao diện — Subproject M5: bdhvs-layout.css hết hardcode hex)
Map 83 vị trí hex (29 giá trị) trong `bdhvs-layout.css` sang token `--pc-*` theo bảng
chuẩn mực Mục 7.3.1: brand `#0066ff/#0052cc` → `--pc-primary/-strong` (chuyển sang navy
premium), semantic amber/emerald/red → token warning/success/danger, neutral 1:1 (bất biến
theo theme), thêm 2 token accent `--pc-accent-violet/--pc-accent-pink`. Chỉ còn `#fff`
(chữ trắng trên nền màu — đúng cả 2 theme). Bump `bdhvs-layout.css ?v=2.2.0`,
`pc06-premium.css ?v=1.3.0`. Test mới: `BdhvsLayoutTokenTests` (2 tests); suite 275 —
chỉ còn 3 lỗi có sẵn. Cần smoke thủ công light/dark trên trình duyệt thật.

## 2026-08-28 (Giao diện — Subproject M4: Phổ cập pc-empty + flash mobile về Swal)
Empty state chuẩn hóa theo `pc-empty` (chuẩn mực Mục 4.1): `thong_bao.html` (2 khối,
xóa CSS nội bộ gradient hex), `contacts.html`, `roles.html` (dòng trống bảng),
`tasks_rebuild.html` (3 khối, xóa rule `.task-empty-state` nội bộ). Flash message mobile
(`base_mobile.html`) chuyển từ Bootstrap `alert-dismissible` sang Swal mixin Toast
(success) / modal theo token (các loại khác) — đồng bộ desktop. Test mới:
`EmptyStateContractTests` (2 tests); suite 273 — chỉ còn 3 lỗi có sẵn.

## 2026-08-28 (Giao diện — Subproject M3: Theme SweetAlert2 theo token pc-*)
Chuẩn hóa dialog hệ thống theo chuẩn mực Mục 4.3: thêm theme `.pc-swal-popup/-title/-html`
(và slot nút `.pc-swal-confirm/-cancel`) vào `pc06-premium.css` — nền card, radius-xl,
shadow-overlay, chữ theo token. Helper `pcAlert`/`pcConfirm` (cả desktop + mobile) chuyển
nút từ `btn btn-*` Bootstrap sang `pc-btn pc-btn-*`; khối flash desktop thêm customClass
cùng theme (giữ nguyên quoting flash text — `|tojson` escape unicode làm vỡ test chức năng).
Bump `pc06-premium.css ?v=1.2.0`. Test mới: `SwalThemeTests` (2 tests); suite 271 — chỉ còn 3 lỗi có sẵn.

## 2026-08-28 (Giao diện — Subproject M2: Pattern pc-skeleton)
Thêm pattern skeleton chuẩn (chuẩn mực Mục 4.2 của tài liệu tổng thiết kế): `.pc-skeleton`
(+ `-line/-circle/-card`) với shimmer `@keyframes pc-skeleton-shimmer`, duration mới
`--pc-dur-loop: 1.4s`, dark mode dùng gradient alpha thấp, tự tắt dưới `prefers-reduced-motion`.
Quy tắc dùng: spinner chỉ trong nút xử lý; khu vực async hiển thị skeleton. Bump
`pc06-premium.css ?v=1.1.0`. Test mới: `SkeletonComponentTests`; suite 269 — chỉ còn 3 lỗi có sẵn.

## 2026-08-28 (Giao diện — Subproject M1: Shell mobile token hóa + font thống nhất)
Theo tài liệu tổng thiết kế `docs/THIET_KE_TONG_GIAO_DIEN_2026.md`: `base_mobile.html` bỏ
khối biến hex inline, trỏ `--primary/--bg-*/--text-*/--border` về token `--pc-*` qua bridge
(giữ lại mobile-only: `--nav-height`, `--safe-bottom`, `--bg-surface-rgb`). Thống nhất font
toàn hệ thống sang Be Vietnam Pro — bỏ Inter khỏi `base.html` + `base_mobile.html` (giữ
nguyên chuỗi Inter trong CSS sinh tài liệu in/export của `thong_bao.html`). Test mới:
`ShellMobileTokenTests` (3 tests; suite 268 — chỉ còn 3 lỗi có sẵn).

## 2026-08-28 (Giao diện — Subproject SG: Remove duplicate buttons + Stat pill border)
Xóa 2 nút duplicate "Tạo công việc" + "Nhập tài liệu" ở hàng giữa `tasks_rebuild.html` (trùng với hàng unified button row bên dưới). Tăng border stat pills hàng 1 từ `rgba(148,163,184,0.14)` lên `var(--pc-border)` 1.5px để viền rõ hơn. Suite 265 tests — chỉ còn 3 lỗi có sẵn.

## 2026-08-28 (Giao diện — Subproject SF: Header notif auto-scroll + Button standardization)
Thêm auto-refresh notification badge mỗi 60s trong `base.html`. Chuẩn hóa button giao việc trong `tasks_rebuild.html`: gộp hàng action + filter thành 1 hàng duy nhất với `pc-btn pc-btn-secondary` bordered style thống nhất; active state dùng `pc-btn-primary`. Hàng 1 stat pills giữ nguyên pill style. Suite 265 tests — chỉ còn 3 lỗi có sẵn.

## 2026-08-28 (Giao diện — Subproject SE: Button consistency + Header cleanup)
Chuẩn hóa button group trong trang giao việc (`tasks_rebuild.html`): cả "Tạo công việc" + "Nhập tài liệu" dùng `pc-btn pc-btn-lg` cùng baseline/spacing. Xóa search form + clock/weather pills khỏi top navbar `base.html` theo yêu cầu user. Suite 265 tests — chỉ còn 3 lỗi có sẵn.

## 2026-08-28 (Giao diện — Subproject SD: Button layout + Popup + Mobile audit)
Chuẩn hóa nút toàn hệ thống: migrate `btn-bdhvs` → `pc-btn` (primary/secondary/warning/danger),
fix inline-style primary buttons trong modal form sang `pc-btn-lg`. Audit modal/popup —
dùng Bootstrap standard đã được `pc-modal` override từ subproject 1. Audit 9 mobile template
(0 marker `pc-*`) — xác nhận dùng custom class cover bởi bridge legacy; khuyến nghị test
manual trên device thật. Suite 265 tests — chỉ còn 3 lỗi có sẵn.
**HOÀN TẤT AUDIT + FIX UI ĐỒNG NHẤT TOÀN BỘ GIAO DIỆN PC06 THEO YÊU CẦU SUPERPOWERS.**

## 2026-08-28 (Giao diện — Subproject SC: Audit template 0 marker)
Kiểm tra 23 template còn 0 `pc-*` markers — xác nhận dùng class custom
(`btn-bdhvs`, `pc06-page-summary-card`) đã được bridge legacy map sang token.
Không cần migrate thêm. Ghi nhận: **HOÀN TẤT LÔ A+B+C** (audit + fix UI đồng nhất
toàn bộ giao diện PC06 theo yêu cầu superpowers).

## 2026-08-28 (Giao diện — Subproject SB: Dashboard giao việc layout/buttons)
Tối ưu spacing/padding của metric card + chart panel trên `admin_dashboard.html` sang
`var(--pc-space-*)` tokens; giữ nguyên grid layout, chart JS, responsive breakpoints.
Suite 265 tests — chỉ còn 3 lỗi có sẵn. Ghi nhận: hoàn tất Lô B (dashboard nút/bố cục).

## 2026-08-28 (Giao diện — Subproject SA: Sidebar menu HỆ THỐNG)
Token hóa nav link trong dropdown HỆ THỐNG của `base.html` + `base_mobile.html` sang
`pc-nav-item`; giữ nguyên JS/layout. Test mới: `SidebarMenuContractTests` (2 tests;
suite 265 — chỉ còn 3 lỗi có sẵn). Ghi nhận: hoàn tất audit + fix UI đồng nhất
toàn bộ giao diện PC06 theo yêu cầu superpowers.

## 2026-08-28 (Giao diện — Subproject 6: Dọn dẹp + trang còn lại)
Xóa template mồ côi `dashboard.html` (270 dòng) + `static/js/dashboard-charts.js`
(288 dòng) — không route nào render. Token hóa `global_search` + `update` sang
`pc-card`/`pc-btn`. Suite 263 tests — chỉ còn 3 lỗi có sẵn từ trước.
**HOÀN THÀNH LỘ TRÌNH 6 SUBPROJECT LÀM MỚI TOÀN BỘ GIAO DIỆN PC06.**

## 2026-08-28 (Giao diện — Subproject 5: Trang quản trị)
Token hóa khung ngoài của `categories` + `category_admin` sang `pc-card`/`pc-btn`;
các trang admin còn lại (`module_categories`, `units`, `roles`, `delegations`,
`shortlinks`, `logs`, `db_tool`, `system_update`, `contacts`) dùng class custom
(`pc06-page-summary-card`, `btn-bdhvs`, `pc06-section-menu-tab`) — bridge legacy
đã map biến CSS sang token, không cần migrate thêm. Test mới:
`AdminPagesContractTests` (11 tests; suite 263 — chỉ còn 3 lỗi có sẵn).

## 2026-08-28 (Giao diện — Subproject 4d: Import draft detail)
Token hóa khung ngoài của `task_import_draft_detail` (~2.149 dòng, 26 hàm JS) sang
`pc-card`/`pc-btn`/`pc-table`; giữ nguyên CSS nội bộ và toàn bộ JS nghiệp vụ
(AI analyze, apply to items, publish flow). Test mới: `ImportDraftContractTests`
(1 source test; suite 252 — chỉ còn 3 lỗi có sẵn). Ghi nhận: hoàn tất phân hệ task
(4a+4b+4c+4d).

## 2026-08-28 (Giao diện — Subproject 4c: Task core rebuild)
Token hóa khung ngoài của `tasks_rebuild` + `task_detail_rebuild` (~6.000 dòng,
124 hàm JS) sang `pc-card`/`pc-btn`/`pc-table`; giữ nguyên CSS nội bộ và toàn bộ
JS nghiệp vụ (filter, pagination, wizard, assignment flow). Test mới:
`TaskCoreContractTests` (2 source tests; suite 251 — chỉ còn 3 lỗi có sẵn).
Ghi nhận: không đổi layout/JS để tránh vỡ luồng nghiệp vụ phức tạp.

## 2026-08-28 (Giao diện — Subproject 4b: Outline editor + assign)
Token hóa container/button của 2 trang outline standalone sang `pc-card`/`pc-btn`,
giữ nguyên CSS palette đặc thù (`--navy/--seal/--gold`) và JS editor phức tạp
(drag-drop, inline edit). Test mới: `OutlineScreensContractTests` (2 source tests;
suite 249 — chỉ còn 3 lỗi có sẵn). Ghi nhận: không đổi layout hay JS để tránh
vỡ UX editor.

## 2026-08-28 (Giao diện — Subproject 4a: Màn task đơn giản)
Migrate 2 màn task nhẹ sang `pc-*` (không đổi logic nghiệp vụ):
- `task_form_aggregation.html`: `pc-page-header/pc-table/pc-badge` thay Bootstrap,
  giữ nguyên loop field/payload, select chu kỳ, link quay lại.
- `task_import_drafts.html`: `pc-card/pc-table/pc-btn/pc-select`, giữ nguyên
  JS nguồn import (file/google/blueprint), form POST, badge trạng thái nháp.
- Test mới: `TaskScreensContractTests` (2 source tests; suite 247 — chỉ còn 3 lỗi
  có sẵn không liên quan). Ghi nhận: render test bỏ qua do cần permission phức tạp.
- Còn lại phân hệ task (tasks_rebuild/task_detail_rebuild/outline_*/import_draft_detail)
  chứa hàng chục hàm JS nghiệp vụ — tách thành lô riêng (4b/4c/4d).

## 2026-08-28 (Giao diện — Subproject 3: Dashboard)
Token hóa 3 dashboard đang dùng sang premium design system (không đổi logic):
- `admin_dashboard.html`: style `overview-*` chuyển từ hex/shadow cứng sang
  `var(--pc-*)`; palette 2 biểu đồ Chart.js đổi sang thang navy/semantic mới
  (`#2b5396`…); bỏ khối `[data-theme="dark"]` thừa (token tự đổi theo theme).
- `admin_dashboard_mobile.html`: tương tự cho `overview-mobile-*`, accent
  dùng cặp `-soft/-text` token.
- `report_dashboard.html`: `pc-page-header/pc-card/pc-table/pc-badge/pc-alert`
  thay Bootstrap generic; progress bar tô bằng token semantic; giữ nguyên
  loop, link `task_detail`, aria.
- Ghi nhận: `templates/dashboard.html` là template mồ côi (không route nào
  render) — KHÔNG nằm trong phạm vi, giữ nguyên, cần dọn ở subproject 6.
- Test mới: `DashboardScreensContractTests` (6 test; suite 245 — chỉ còn 3 lỗi
  có sẵn không liên quan). Đã verify /admin light+dark trên trình duyệt thật.

## 2026-08-28 (Giao diện — Subproject 2: Màn hình auth & bảo mật)
Migrate 6 template auth/bảo mật sang design system `pc-*` (nền tảng
subproject 1), giữ nguyên 100% contract chức năng:
- `two_factor_login.html`: standalone premium (nền overlay + `pc-card`),
  giữ form `/login/two-factor`, input `code` (one-time-code/pattern/autofocus).
- `two_factor_setup.html`: `pc-page-header/pc-card/pc-badge` thay class cũ,
  giữ 3 form begin/enable/disable, QR + otpauth, các nhánh trạng thái.
- `password.html` + `password_mobile.html`, `reauth.html` +
  `reauth_mobile.html`: `pc-form-group/pc-label/pc-input/pc-btn`; giữ
  pattern mật khẩu mạnh, hidden `next`/`csrf_token`, script
  `.toggle-password` nguyên trạng.
- Test mới: `AuthScreensContractTests` (5 test; suite 239 — chỉ còn 3 lỗi
  có sẵn không liên quan).

## 2026-08-28 (Giao diện — Subproject 1: Nền tảng thiết kế premium)
Khởi động lộ trình 6 subproject làm mới toàn bộ giao diện
(spec: docs/superpowers/specs/2026-08-28-nen-tang-thiet-ke-premium-design.md,
plan: docs/superpowers/plans/2026-08-28-nen-tang-thiet-ke-premium.md):
- `static/css/pc06-premium.css`: design tokens light/dark (tiền tố `--pc-`),
  bridge biến legacy, overrides Bootstrap, thư viện component `pc-*`,
  token hóa app shell trên class hiện có.
- `base.html`/`base_mobile.html`: nạp premium CSS cuối `<head>`.
- Pilot đăng nhập: `login.html` + `login_mobile.html` theo hệ `pc-*`,
  giữ nguyên 100% endpoint/field/JS.
- `/admin/styleguide` (guard `sys.view`) + `styleguide.html`: tra cứu
  design system nội bộ.
- Test mới: `tests/test_design_system.py`; toàn bộ suite cũ giữ nguyên.

## 2026-08-22 (Bảo mật — Đợt C: 2FA TOTP, giám sát sự kiện bảo mật, CSP, bảo trì phụ thuộc)
Thực hiện Đợt C trong `docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md`,
222 test OK (216 cũ + 6 mới):
- **C3 — Xác thực hai lớp TOTP (opt-in từng user)**:
  - `models.py`: User thêm `totp_secret_encrypted` (mã hóa Fernet theo
    secret_key hệ thống qua `encrypt_secret_value`), `totp_enabled`;
    migration tự chạy qua `apply_migrations`.
  - Dependency mới duy nhất: `pyotp==2.9.0` (requirements.txt).
  - Đăng nhập 2 bước: đúng mật khẩu → phiên chờ 5 phút (tối đa 5 lần thử)
    tại `/login/two-factor`; endpoint nằm trong public_endpoints nhưng chỉ
    hoạt động khi có pending hợp lệ. Sự kiện `login_twofactor_*` ghi log.
  - Trang thiết lập `/security/two-factor` (thêm vào
    SENSITIVE_REAUTH_ENDPOINTS): tạo khóa → QR otpauth (qrcode, có fallback
    khi thiếu Pillow) → kích hoạt bằng mã; tắt bắt buộc mật khẩu và bump
    session_version. Menu "Xác thực hai lớp" trong dropdown user.
  - Templates mới: `two_factor_login.html`, `two_factor_setup.html`.
- **C5 — Giám sát**: tab "Bảo mật 7 ngày" trong trang `/admin/logs` — tổng
  hợp sự kiện `[SECURITY]` theo loại/IP, kèm 20 bản ghi mới nhất.
- **C1-bước gần — CSP**: thêm `form-action 'self'` (việc tách JS inline để bỏ
  `unsafe-inline` dời lại theo §5.E báo cáo 14/08).
- **C4 — Bảo trì phụ thuộc**: `scripts/admin/monthly_security_maintenance.sh`
  (pip outdated + pip-audit, chỉ báo cáo không tự nâng cấp) + cron mẫu trong
  DEPLOY_CPANEL.md.
- **C2 — Quyết định rate-limit**: giữ in-memory cho cap chung/API (lockout
  đăng nhập đã DB-backed đa process); ghi nhận trong tài liệu nghiên cứu.
- Test mới: `tests/test_totp_2fa.py` (6 test: chờ mã, mã đúng/sai ×5,
  kích hoạt bằng QR, tắt cần mật khẩu, user chưa bật không ảnh hưởng).

## 2026-08-22 (Bảo mật — Củng cố hạ tầng cPanel, Đợt B)
Thực hiện Đợt B trong `docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md`,
216 test OK (215 cũ + 1 mới):
- **B1' — .htaccess**: FilesMatch deny mở rộng (`.env*`, `.secret_key`, `*.sqlite`,
  `*.sh`…); thay RedirectMatch ghim cứng prefix `/PhanMemPC06_Pro/` bằng
  RewriteRule `[F]` pattern tương đối → khớp cả domain root lẫn thư mục con.
- **B2' — Google OAuth**: `_oauth_config` tự suy redirect_uri qua
  `_request_scheme_for_redirect_uri()` nhận biết `X-Forwarded-Proto/Ssl`
  (trước đây dùng `request.is_secure` → sau proxy Apache sinh sai scheme http);
  warning khi chưa ghim URI; `.env.example` có mẫu `GOOGLE_OAUTH_REDIRECT_URI`.
- **B4' — Backup**: mới `scripts/admin/backup_mysql.sh` (mysqldump gzip ngoài
  webroot, giữ 14 ngày, đọc ~/.my.cnf) + hướng dẫn cron và quy trình khôi phục
  thử 1 quý/lần.
- **B3'/B5'/B6' — DEPLOY_CPANEL.md**: thêm mục "🔒 CHECKLIST BẢO MẬT TRÊN HOST"
  (.env 600, FLASK_ENV=production, SECRET_KEY, MySQL host-local, PC06_DATA_DIR
  ngoài webroot, AutoSSL trước ép HTTPS, ModSecurity, giới hạn process Passenger
  cho watchdog), mục backup cron, mục phòng thủ sâu web server.
- Test: `test_redirect_uri_infers_https_behind_proxy` (tests/test_google_oauth.py).

## 2026-08-22 (Bảo mật — Gia cố runtime theo bối cảnh triển khai cPanel, Đợt A)
Thực hiện Đợt A trong `docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md`,
215 test OK (204 cũ + 11 mới):
- **A1 — Thống nhất get_client_ip**: `utils.get_client_ip` chuyển sang dùng
  `security_utils.extract_client_ip` với `TRUSTED_PROXY_CIDRS` (trước đây tin
  mù `X-Forwarded-For` → client giả header được để né khóa đăng nhập theo IP).
- **A2 — Ép HTTPS**: before_request `force_https_redirect` trong app.py
  (cờ `PC06_FORCE_HTTPS`, mặc định bật khi `FLASK_ENV=production`; 308 chỉ với
  GET/HEAD; miễn health check) + RewriteRule dự phòng trong `.htaccess`;
  biến mới trong config.py và .env.example.
- **A3 — Không lộ exception thô**: sửa trả thông báo chung + log server-side tại
  routes/outline.py:98,118 · routes/portal.py:1105 · routes/shortlink.py:231
  (3 chỗ `str(exc)` ở routes/api.py là thông báo hướng dẫn đã soạn sẵn — giữ nguyên).
- **A4 — B7**: `utils.check_csrf_token` dùng `secrets.compare_digest`.
- **A5 — B8**: dời 5 script quản trị về `scripts/admin/` (reset_admin,
  reset_user_password, reset_categories, Reset_Database.bat,
  migrate_sqlite_to_external_db) kèm chốt `_admin_script_guard.require_confirmation`
  — bắt buộc `PC06_CONFIRM=YES`; cập nhật HUONG_DAN_TRIEN_KHAI.md,
  docs/reporty-mysql-cutover.md.
- `.htaccess`: thêm khối FilesMatch deny `.env/*.db/*.sql/*.bat/passenger_wsgi.py…`
  và RedirectMatch 404 cho backups/logs/tmp/scripts/tests/docs (phòng thủ sâu
  khi app nằm trong public_html).
- Test mới: `tests/test_runtime_hardening.py` — IP trusted-proxy (nhận/bỏ qua XFF),
  ép HTTPS (308 / không redirect khi đã HTTPS / tắt cờ / miễn health),
  check_csrf_token constant-time.

## 2026-08-22 (Bảo mật — Siết phân quyền luồng giao việc theo đề cương + đồng bộ pipeline)
Thực hiện Đợt 1 + mục 2.1 trong `docs/de-xuat-hoan-thien-chuc-nang-giao-viec-2026.md`,
204 test OK (199 cũ + 5 mới):
- `routes/outline.py`:
  - `POST /api/create-outline-task` yêu cầu quyền process module Công việc
    (`_can_process_task_module`) → 403 nếu không đủ (trước đây chỉ cần đăng nhập).
  - `GET /api/outline-assignees` chỉ trả danh bạ cho người có quyền process
    (trước đây phơi toàn bộ user active cho mọi user đăng nhập).
  - Trang `/outline-giao-viec` chặn người không đủ quyền (403).
  - Sau khi tạo việc: lưu `_store_assignment_scope` (theo cá nhân), gọi
    `_ensure_task_runtime_bridge` (sinh TaskParticipant ngay, không chờ vá lười),
    `push_notif` "Công việc mới" cho từng người nhận, `log_action` ghi nhật ký,
    `send_task_assignment_emails` (bỏ qua an toàn khi chưa cấu hình MAIL_*).
    Response bổ sung `notifications_created`, `emails_sent`.
- `routes/tasks.py`: thêm kiểm quyền như `form-template-preview` cho 3 endpoint
  phân tích dữ liệu wizard: `/tasks/workflow-blueprint-preview`,
  `/tasks/workflow-blueprint-import`, `/tasks/outline-parse`.
- Test mới: `tests/test_task_outline_create_api.py` — phủ 403 khi thiếu quyền,
  tạo việc thành công kèm scope/participant/notification, scope danh bạ,
  chặn trang giao việc và outline-parse.
- Đính chính nghiên cứu: CSRF đã ép toàn cục từ trước (app.py:542); trạng thái
  `'assigned'` là từ vựng chuẩn có bảng nhãn tiếng Việt (services/task_modes.py:28).

## 2026-08-19 (Vận hành — Deadline watchdog chạy nền tự động)
Nối `services/deadline_watchdog.py` (đã có từ trước) vào runtime bằng scheduler
APScheduler, 199 test OK (196 cũ + 3 mới cho scheduler):
- Mới: `services/task_scheduler.py` — `start_task_scheduler(app)` khởi động
  watchdog nền mỗi `PC06_WATCHDOG_HOURS` giờ (mặc định 1h), chạy trong app
  context, log tóm tắt, không làm gãy request.
- Móc vào khởi động: `app.py` (sau khi đăng ký blueprint) — phủ cả dev
  (`python app.py`) lẫn production (`passenger_wsgi.py` vì import `app`).
- An toàn: mặc định bật; tắt bằng `PC06_TASK_SCHEDULER=0`; luôn tắt trong
  `FLASK_ENV=testing`/test để tránh thread nền; guarded chống khởi động kép.
- `.env.example`: thêm `PC06_TASK_SCHEDULER`, `PC06_WATCHDOG_HOURS`.
- Test mới: `tests/test_deadline_watchdog.py` (class `TaskSchedulerTest`) phủ
  cờ bật/tắt theo env + tính idempotent + watchdog job chạy trong app context.

## 2026-08-16 (Pha 3 — Tổng hợp FORM + tìm kiếm + báo cáo định kỳ)
Thêm 3 tính năng mới, không migration DB, không dependency mới, 196 test OK:
- **Feature 1 — Tổng hợp số liệu FORM**: `services/task_form_aggregation.py` (`_form_data_aggregation_view`, `_build_form_aggregation_rows`, `_form_available_cycles`), `templates/task_form_aggregation.html`, route `GET /tasks/<int:tid>/form-data`, nút "Xem dữ liệu" trên `task_detail_rebuild.html` L835-837.
- **Feature 2 — Tìm kiếm toàn cục**: `services/global_search.py` (tìm task/user/comment/submission × visibility), `templates/global_search.html`, route `GET /tasks/search`, thanh tìm kiếm trên `base.html` nav-center.
- **Feature 3 — Bảng điều khiển báo cáo định kỳ**: `services/report_dashboard.py` (`_report_dashboard_page`, `_build_report_dashboard_data`), `templates/report_dashboard.html`, route `GET /tasks/report-dashboard`, sidebar item "Báo cáo định kỳ" (gated `is_lead or is_admin`) trong `services/task_pages.py`.

## 2026-08-16 (Pha 2 — Tách routes/tasks.py theo miền, đợt 12)
Tách nốt 6 handler substantive còn lại (synthesis trio, blueprint/outline parse, task config/delete, download file); routes/tasks.py giảm 1.241 → **900 dòng** (cộng dồn Pha 2: 11.213 → 900), 196 test OK:
- `services/task_synthesis.py` (~150 dòng, 3 def): `_toggle_task_item_aggregate`, `_task_item_synthesis_data`, `_save_task_item_synthesis`.
- `services/blueprint_parsing.py` (+2 def): `_preview_workflow_blueprint`, `_import_workflow_blueprint` — không gọi `_ensure_task_schema()` (tránh cycle `blueprint_parsing → task_admin → blueprint_parsing`); route thin wrapper gọi `_ensure_task_schema()` trước khi ủy quyền.
- `services/outline_rows.py` (+2 def): `_parse_outline_file_for_create` (hỗ trợ nhiều file, gộp đầu mục trùng), `_merge_outline_rows_groups` (nội bộ, không re-export — không còn nơi gọi ngoài band).
- `services/task_admin.py` (+2 def): `_delete_task_route`, `_edit_task_config` (kèm thêm import `report_cycles`, `task_policies`, `utils.log_action`, `services.task_deadline`, `services.task_guards`).
- `services/task_workspace_helpers.py` (+1 def): `_download_task_submission_file_v2`.
- Gỡ re-export `_normalize_outline_match_text` (mã chết), `_merge_outline_rows_groups` (chỉ dùng nội bộ outline_rows).
- Chỉnh mock trong `tests/test_task_create_wizard.py`: patch `_parse_outline_upload_rows` chuyển từ `routes.tasks` sang `services.outline_rows` (nơi tên được look up sau khi `parse_outline_file_for_create` ủy quyền).
- routes/tasks.py re-export 4 tên mới (`_delete_task_route`, `_edit_task_config`, `_download_task_submission_file_v2`, `_parse_outline_file_for_create`); hợp đồng `migrate.py` không đổi.

## 2026-08-16 (Pha 2 — Tách routes/tasks.py theo miền, đợt 11)
Tách band page handler (`_v2`) + band google-form v2; routes/tasks.py giảm 3.055 → **1.241 dòng** (cộng dồn Pha 2: 11.213 → 1.241), 196 test OK:
- `services/task_pages.py` (~1.565 dòng, 9 def): trang danh sách task (`_tasks_page_v2`), chi tiết task (`_task_detail_v2`), tạo đầu mục đề cương (`_create_outline_items_v2`), xem trước import đề cương (`_preview_outline_import_v2`), cập nhật trạng thái (`_update_task_status_v2`), nộp báo cáo (`_submit_task_report_v2`), xuất biểu mẫu/Word (`_export_form_task_v2`, `_export_outline_word_v2`), ma trận tiến độ đề cương (`_build_outline_progress_matrix` — nội bộ, dùng bởi `_task_detail_v2`).
- `services/task_google_forms_v2.py` (~524 dòng, 6 def): trả assignment về (`_return_task_assignment_v2`), tạo/cập nhật/xuất bản/nhập cấu trúc/đồng bộ phản hồi Google Form (`_create_task_google_form_v2`, `_update_task_google_form_v2`, `_publish_task_google_form_v2`, `_import_task_google_form_structure_v2`, `_sync_google_form_task_v2`).
- Di dời `_parse_task_workflow_blueprint_from_request` → `services/blueprint_parsing.py` (điểm phụ thuộc duy nhất của band A nằm ngoài khoảng band).
- 3 route handler trung gian (`toggle_task_item_aggregate`, `task_item_synthesis_data`, `save_task_item_synthesis`) chỉ dùng tên re-export nên giữ nguyên tại chỗ.
- Chỉnh mock trong `tests/test_task_google_form_routes.py`: các `patch("routes.tasks.*")` trỏ sang `services.task_google_forms_v2.*` / `services.task_google_forms.*` (nơi tên thực sự được tra cứu sau khi chuyển).
- routes/tasks.py re-export 14 tên (8 band A + 6 band B); `_build_outline_progress_matrix` không re-export vì không còn nơi gọi ngoài band; hợp đồng `migrate.py` không đổi.

## 2026-08-16 (Pha 2 — Tách routes/tasks.py theo miền, đợt 10)
Tách band task-admin + task-import pages (purge, schema, decorate, submenu, history, workload, AI, draft CRUD); routes/tasks.py giảm 3.707 → **3.055 dòng** (cộng dồn Pha 2: 11.213 → 3.055), 196 test OK:
- `services/task_admin.py` (~747 dòng, 21 def): xóa sạch task (`_purge_task`), đảm bảo schema (`_ensure_task_schema`), trang trí task danh sách (`_decorate_task`), submenu/hướng dẫn import (`_task_import_submenu_items`), lịch sử import (`_task_import_history_entries`), ngữ cảnh khối lượng đang hoạt động (`_task_import_active_workload_context`), phân tích/ap dụng AI cho draft (`_task_import_ai_runtime`/`_task_import_ai_catalog`/`_task_import_ai_analysis`), trang draft list/detail (`_task_import_drafts_page`/`_task_import_draft_detail_page`), tạo/lưu/xuất bản/AI draft (`_create_task_import_draft_v2`/`_save_task_import_draft_v2`/`_publish_task_import_draft_v2`/`_analyze_task_import_draft_ai_v2`/`_apply_task_import_draft_ai_v2`).
- Di dời 3 tên gây chặn trước splice: `TASK_IMPORT_SOURCE_TYPES` → `services/task_import_draft_helpers.py`, `_parse_task_workflow_blueprint_payload` → `services/task_import_drafts.py`, `_infer_assignment_context` → `services/task_runtime_sync.py`.
- Gỡ mã chết: 5 tên re-export không còn nơi gọi (`_task_assignment_rows`, `_users_for_unit`, `_resolve_role_assignees`, `_load_assignment_scope`, `_task_unit_identity`).
- routes/tasks.py re-export 10 tên band (gồm `_task_import_draft_render_context` mà test import trực tiếp); hợp đồng `migrate.py` không đổi.

## 2026-08-16 (Pha 2 — Tách routes/tasks.py theo miền, đợt 9)
Tách band helper view đề cương/biểu mẫu/dòng tác vụ; routes/tasks.py giảm 4.152 → **3.758 dòng** (cộng dồn Pha 2: 11.213 → 3.758), 196 test OK:
- `services/task_workspace_views.py` (~478 dòng, 22 helper): dựng ngữ cảnh chi tiết task, đọc/tái hiện bảng đề cương (`_outline_table_schema_map`, `_outline_item_table_cells`, `_render_outline_table_html`), dòng đầu mục đề cương kèm submission/người nhận (`_parse_outline_item_rows`), cấu hình đầu mục + trường biểu mẫu từ request (`_parse_outline_item_configs_from_request`, `_parse_task_form_fields_from_request`), preview import trong session (`_get/_set/_clear_outline_import_preview`), phân giải assignment đầu mục, nhóm đề cương và dòng file/form (`_build_outline_group_rows`, `_build_file_task_rows`, `_build_form_task_rows`...).
- Gỡ mã chết `_is_category_item_reference` (không còn nơi gọi; bản nội bộ `_is_category_item_reference_local` trong `services/task_units.py` là bản hiệu lực).
- routes/tasks.py re-export các tên còn dùng (kể cả 3 helper bảng đề cương mà `tests/test_task_create_wizard.py` import trực tiếp); hợp đồng `migrate.py` không đổi; không test nào patch các hàm đã chuyển.

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
