# TỔNG THIẾT KẾ TOÀN BỘ GIAO DIỆN — PhanMemPC06_Pro

**Ngày ban hành:** 2026-08-28
**Trạng thái:** Chuẩn mực hiện hành (normative) — áp dụng cho mọi lần tạo/sửa giao diện từ nay về sau
**Nền tảng:** `static/css/pc06-premium.css` (design system `pc-*` v1, Subproject 1) + chuỗi subproject 1→6, SA→SG
**Tài liệu liên quan:**
- Spec nền tảng: `docs/superpowers/specs/2026-08-28-nen-tang-thiet-ke-premium-design.md`
- Trang tra cứu trực quan: `/admin/styleguide` (`templates/styleguide.html`, chỉ admin)
- Kiểm thử: `tests/test_design_system.py`

> Tài liệu này vừa **ghi nhận hiện trạng** (đã kiểm chứng qua source ngày 2026-08-28) vừa **chốt quyết định** cho các khoảng trống. Khi hiện trạng và chuẩn mực khác nhau, phần "Chuẩn mực" là đích cần đạt; phần "Hiện trạng" là điểm xuất phát đã ghi nhận.

---

## MỤC 1 — NGUYÊN TẮC & THẨM MỸ

### 1.1 Định hướng thẩm mỹ

Premium navy/slate: nền sáng trung tính (slate 50), card trắng viền mảnh đổ bóng rất nhẹ, màu chủ đạo **navy `#2b5396`** dùng tiết chế (nav item active, nút primary, link, focus ring), màu semantic (xanh/lá/vàng/đỏ) chỉ dùng cho trạng thái. Không gradient trang trí, không màu bão hòa lớn, không viền đậm. Thẩm mỹ đến từ: nhịp spacing đều (bước 4px), bo góc trung bình 12–16px, typography Be Vietnam Pro đậm rõ cấp bậc, bóng phân tầng tinh tế.

### 1.2 Ba nguyên tắc bất biến

1. **Không đổi contract chức năng.** Không đổi route, tên field form, endpoint, id/hook JS nghiệp vụ, model. Chỉ thay đổi tầng trình bày (class CSS, markup trình bày, style).
2. **Token-first.** Mọi màu/kích thước/bóng/thời gian chuyển động mới phải dùng biến `--pc-*`. Cấm hardcode hex/px mới trong template và CSS tùy chỉnh. Giá trị ngoài bảng token phải được thêm vào `pc06-premium.css` dưới dạng token trước khi dùng.
3. **Mobile theo template kép có fallback.** `render_auto_template()` (`utils.py:805`) tự chọn `name_mobile.html` nếu tồn tại, không thì fallback bản desktop. Không đổi cơ chế này.

### 1.3 Bối cảnh kỹ thuật cố định

- Flask + Jinja, Bootstrap 5.3.2 (CDN), Font Awesome 6.4 (CDN), Google Fonts.
- Theme light/dark qua `data-theme` trên `<html>`, lưu `localStorage` key `theme`, mặc định light. Mobile đồng bộ thêm `data-bs-theme`.
- CSS tùy chỉnh: `style.css` (2.527 dòng), `bdhvs-layout.css` (1.778), `flat-theme.css` (702), `mobile-responsive.css` (205), `pc06-premium.css` (588).

---

## MỤC 2 — NỀN TẢNG TOKEN (`--pc-*`)

Nguồn sự thật duy nhất: `static/css/pc06-premium.css`, mục 1 (dòng 8–164). Light trong `:root`, dark override trong `[data-theme="dark"]` (dark chỉ đổi màu + bóng; typography/spacing giữ nguyên).

### 2.1 Màu chủ đạo (navy) — 11 bậc + alias

| Token | Light | Dark override |
|---|---|---|
| `--pc-primary-50` | `#f2f6fc` | `rgba(79,127,208,.14)` |
| `--pc-primary-100` | `#e3ebf7` | — |
| `--pc-primary-200` | `#c5d7ee` | — |
| `--pc-primary-300` | `#98b7df` | `#9db9e6` |
| `--pc-primary-400` | `#6491cb` | — |
| `--pc-primary-500` | `#3f6db3` | — |
| `--pc-primary-600` (**primary**) | `#2b5396` | `#4f7fd0` |
| `--pc-primary-700` (**strong**) | `#24437a` | `#6b95dd` |
| `--pc-primary-800` | `#203963` | — |
| `--pc-primary-900` | `#1d3053` | — |
| `--pc-primary-950` | `#121f38` | — |
| `--pc-primary-ring` | `rgba(43,83,150,.28)` | `rgba(79,127,208,.35)` |

Alias dùng nhanh: `--pc-primary` (= 600), `--pc-primary-strong` (= 700), `--pc-primary-soft` (= 50).

### 2.2 Màu semantic — 4 nhóm × 4 biến

Mỗi nhóm có: màu chính (`-X`), nền nhạt (`-X-bg`), viền (`-X-border`), chữ trên nền nhạt (`-X-text`).

| Nhóm | Light (main / bg / border / text) | Dark (main / bg) |
|---|---|---|
| success | `#15803d` / `#ecfdf3` / `#bbe7c9` / `#14532d` | `#4ade80` / `rgba(34,197,94,.12)` |
| warning | `#b45309` / `#fffbeb` / `#fde5ae` / `#7c3d05` | `#fbbf24` / `rgba(245,158,11,.12)` |
| danger | `#dc2626` / `#fef2f2` / `#fecaca` / `#7f1d1d` | `#f87171` / `rgba(239,68,68,.12)` |
| info | `#0369a1` / `#f0f9ff` / `#bae6fd` / `#075985` | `#38bdf8` / `rgba(14,165,233,.12)` |

### 2.3 Neutral (slate) — 13 bậc + surface/text

`--pc-neutral-0` `#ffffff` → `--pc-neutral-950` `#020617` (0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950).

| Token vai trò | Light | Dark |
|---|---|---|
| `--pc-bg` | `#f8fafc` | `#0b1220` |
| `--pc-bg-subtle` | `#f1f5f9` | `#0e1627` |
| `--pc-bg-card` | `#ffffff` | `#111b2e` |
| `--pc-border` | `#e2e8f0` | `#22304a` |
| `--pc-border-strong` | `#cbd5e1` | `#2e3f5e` |
| `--pc-text` | `#1e293b` | `#e7edf7` |
| `--pc-text-muted` | `#64748b` | `#9fb0c8` |
| `--pc-text-subtle` | `#94a3b8` | `#64778f` |

### 2.4 Typography

- Font: `--pc-font-sans: 'Be Vietnam Pro', 'Segoe UI', system-ui, -apple-system, sans-serif`.
- Scale: `--pc-text-display` 2rem · `--pc-text-h1` 1.75rem · `--pc-text-h2` 1.375rem · `--pc-text-h3` 1.125rem · `--pc-text-body` .9375rem · `--pc-text-sm` .8125rem · `--pc-text-xs` .6875rem.
- Line-height: `--pc-leading-tight` 1.25 (tiêu đề), `--pc-leading-body` 1.6 (nội dung). Tracking: `--pc-tracking-wide` .06em (label/heading dạng uppercase).

### 2.5 Spacing — 12 bước 4px

`--pc-space-1` .25rem → `--pc-space-12` 6rem (1:.5:.75:1:1.25:1.5:2:2.5:3:4:5:6 rem).

### 2.6 Radius, shadow, motion, z-index, focus

| Nhóm | Giá trị |
|---|---|
| Radius | `sm` 8px · `md` 12px · `lg` 16px · `xl` 22px · `pill` 999px |
| Shadow | `xs` · `sm` · `md` · `lg` · `overlay` (tăng dần độ đậm; dark dùng alpha đậm hơn trên nền tối) |
| Motion | `--pc-dur-fast` 120ms · `--pc-dur-base` 200ms · `--pc-dur-slow` 320ms · `--pc-ease: cubic-bezier(.2,0,0,1)` |
| Z-index | dropdown 1000 · sticky 1020 · modal 1055 · toast 1080 |
| Focus | `--pc-focus-ring` (primary) · `--pc-focus-ring-danger` |

### 2.7 Chuẩn mực đặt tên token mới

- Tiền tố `--pc-` bắt buộc; nhóm theo dạng `--pc-<nhóm>-<bậc/vai trò>`.
- Token màu mới phải khai báo cả light và dark trong cùng vị trí với các token hiện có.
- Không tạo token trùng nghĩa với token có sẵn (ví dụ không thêm `--pc-gray-500` khi có `--pc-neutral-500`).

---

## MỤC 3 — THƯ VIỆN COMPONENT `pc-*`

Nguồn: `pc06-premium.css` mục 4 (dòng 254–545). Trạng thái: **đã triển khai, đang dùng**.

### 3.1 Button

| Class | Dùng khi |
|---|---|
| `pc-btn` | Bắt buộc là class gốc của mọi nút (kết hợp variant bên dưới) |
| `pc-btn-primary` | Hành động chính của màn hình (mỗi khối action tối đa 1 nút primary) |
| `pc-btn-secondary` | Hành động phụ — nền card, viền mạnh |
| `pc-btn-ghost` | Hành động nhẹ trong dòng/khối dày đặc (transparent) |
| `pc-btn-danger` | Hành động hủy/xóa |
| `pc-btn-sm` / `pc-btn-lg` | Cỡ nhỏ (trong bảng/hàng dày) / cỡ lớn (action chính trang) |
| `pc-btn-loading` | Trạng thái đang xử lý (opacity .75 + pointer-events none) |

Nút disabled: opacity .55. Active: `translateY(1px)`. Focus: focus ring primary.

### 3.2 Form

`pc-form-group` (khối field, margin-bottom space-5) → `pc-label` (uppercase, xs, đậm, muted) → `pc-input` / `pc-select` (nền subtle, focus chuyển nền card + viền primary + focus ring) → `pc-help` (gợi ý) / `pc-error` (lỗi, đỏ) + `pc-invalid` (viền đỏ cho input).

### 3.3 Card

`pc-card` + `pc-card-header` (flex space-between, viền dưới) + `pc-card-body` (padding space-5) + `pc-card-footer` (viền trên). Mọi khối nội dung "hộp" trên trang dùng card này, không tự viết box-shadow riêng.

### 3.4 Alert & Badge

- `pc-alert` + variant `success/warning/danger/info` — thông báo inline trong trang.
- `pc-badge` + variant `primary/success/warning/danger/info/neutral` — trạng thái bản ghi, pill, viền theo semantic.

### 3.5 Table & Pagination

- `pc-table`: thead uppercase xs trên nền subtle, hàng viền dưới mảnh; `pc-table-hover` thêm hover nền subtle.
- `pc-pagination`: bọc markup Bootstrap pagination chuẩn (`page-item`/`page-link`) — không cần đổi DOM.

### 3.6 Modal

Override toàn cục `.modal-content` (+ `pc-modal` dùng trực tiếp): nền card, radius-xl, shadow-overlay; header/body/footer theo token. Modal vẫn dùng cơ chế Bootstrap JS — **không tự viết modal JS mới**.

### 3.7 Nav & page header

- `pc-topbar`, `pc-sidebar` — nền card, viền ranh giới.
- `pc-nav-section` — tiêu đề nhóm menu (uppercase xs subtle).
- `pc-nav-item` — link menu pill; hover nền primary-soft; active nền primary chữ trắng.
- `pc-page-header` + `pc-page-title` (h1 1.75rem, đậm 800, letter-spacing -0.02em) + `pc-page-actions` — đầu mọi trang chức năng.

### 3.8 Empty state & login helper

- `pc-empty` + `pc-empty-icon` + `pc-empty-title` — trạng thái không có dữ liệu (xem Mục 4.1).
- `pc-login-divider`, `pc-login-google` — chuyên cho màn login (pilot Subproject 1).

### 3.9 App shell (token hóa class cũ, KHÔNG đổi DOM)

`.desktop-sidebar`, `.desktop-brand-badge`, `.sidebar-nav-link`, `.nav-link-top`, `.mobile-header`, `.mobile-bottom-nav` — các class shell hiện có được ghi đè style bằng token trong `pc06-premium.css` mục 5. Template shell giữ nguyên markup.

---

## MỤC 4 — PATTERN HÀNH VI CHUẨN (CHỐT MỚI)

Phần này là **quyết định chuẩn mực** cho các khoảng trống mà design system v1 chưa phủ. Hiện trạng ghi ở từng mục.

### 4.1 Empty state — chuẩn `pc-empty` (duy nhất)

- **Chuẩn mực:** mọi danh sách/bảng không có dữ liệu render khối `pc-empty` gồm icon (Font Awesome, 2rem, subtle) + `pc-empty-title` (đậm) + một dòng mô tả muted + (tùy) nút `pc-btn-primary` hành động gợi ý.
- **Hiện trạng:** chỉ styleguide dùng; các trang tự viết kiểu "td colspan + text-muted" (`thong_bao.html:156`, `contacts.html:180`, `roles.html:150`, `tasks_rebuild.html:143/176/2569`). Các trang này migrate dần khi đụng đến; trang mới bắt buộc dùng `pc-empty`.

### 4.2 Loading — chốt pattern `pc-skeleton` (chưa có trong CSS)

- **Chuẩn mực:** design system bổ sung pattern skeleton (triển khai ở subproject tiếp theo, spec như sau):
  - `pc-skeleton` — khối xám `var(--pc-bg-subtle)`, radius `--pc-radius-md`, animation shimmer bằng `--pc-dur-loop` + `--pc-ease`, tôn trọng `prefers-reduced-motion`.
  - Biến thể: `pc-skeleton-line` (cao 1em, width %), `pc-skeleton-circle` (radius pill), `pc-skeleton-card` (cao ~5rem, dùng thay card đang load).
  - Quy tắc dùng: khu vực load async (fetch/AI analyze) hiển thị skeleton thay vì spinner đứng yên; spinner Bootstrap chỉ chấp nhận trong nút đang xử lý.
- **Hiện trạng:** không có skeleton chung; `spinner-border` rải rác (`thong_bao.html:180`…).

### 4.3 Toast / Confirm / Flash — chuẩn SweetAlert2 theo token

- **Chuẩn mực:** giữ SweetAlert2 làm nền tảng duy nhất cho toast + confirm + flash message (đã là de facto qua `window.pcAlert` / `window.pcConfirm` — `base.html:1078-1100`, `base_mobile.html:658`). Chốt:
  1. Mọi Swal gọi qua helper `pcAlert`/`pcConfirm`, không gọi `Swal.fire` trực tiếp trong template.
  2. Bổ sung theme Swal ăn token: map `customClass` sang class `pc-swal-*` và định nghĩa CSS tương ứng trong `pc06-premium.css` (nền `--pc-bg-card`, radius `--pc-radius-xl`, nút confirm = `pc-btn-primary`, cancel = `pc-btn-secondary`, title/body theo `--pc-text*`).
  3. Flash message success = toast top-end 3s; lỗi/warning = modal Swal.
  4. Thông báo inline trong trang (không phải flash) dùng `pc-alert-*`, không dùng Swal.
- **Hiện trạng:** desktop dùng Swal toast; `base_mobile.html:514-525` vẫn dùng Bootstrap `alert alert-*` cho flash — cần chuyển về helper chung. Swal hiện chưa ăn token `pc-*` (nút confirm là `btn btn-primary` generic).
- **Cấm:** thêm mới `alert alert-*` Bootstrap trong template (cũ migrate dần).

### 4.4 Form validation

- **Chuẩn mực:** lỗi field → thêm `pc-invalid` vào input + `pc-error` (icon + text) ngay dưới; lỗi toàn trang → `pc-alert-danger` phía trên form. Không tự tô viền đỏ inline-style.
- **Hiện trạng:** class `pc-invalid/pc-error` đã có trong CSS, mức độ áp dụng chưa đồng đều.

### 4.5 Phân trang & sắp xếp

- **Chuẩn mực:** phân trang server-side dùng markup Bootstrap pagination + class `pc-pagination` bọc ngoài. Không viết pagination JS tùy biến mới.

---

## MỤC 5 — APP SHELL & ĐIỀU HƯỚNG

### 5.1 Desktop (`base.html`, 1.489 dòng)

- **Sidebar trái** (`d-none d-lg-flex`): brand badge PC06; nhóm menu — Trang chủ; Công việc (+ submenu động theo `sidebar_submenu_items`); Thông báo; Danh bạ; QR và liên kết; Hệ thống (Tài khoản và vai trò, Module categories, Units, Delegations, Logs, System update, DB tool) — ẩn/hiện theo `can_module()`.
- **Top navbar:** hamburger mở offcanvas `#mobileMenu` (dùng khi màn < lg), logo, chuông thông báo (badge `#notifCount`, auto-refresh 60s — Subproject SF), dropdown user (Đổi mật khẩu / 2FA / Đăng xuất), nút đổi theme.
- **Offcanvas mobile-sidebar** nằm trong base.html, lặp nav dạng `mobile-nav-link`.
- Font Awesome cho icon menu; menu phân cấp bằng markup lồng nhau.

### 5.2 Mobile (`base_mobile.html`, 811 dòng)

- Header cố định 60px: hamburger, tiêu đề, chuông, theme toggler.
- **Bottom-nav 3 mục:** TRANG CHỦ `/` · NHIỆM VỤ `/tasks` · THÔNG BÁO `/thong-bao`.
- Offcanvas drawer đầy đủ nav (dùng `sidebar-nav-link pc-nav-item`).

### 5.3 Cơ chế theme

Khởi tạo ngay đầu `<head>` từ `localStorage('theme') || 'light'` → set `data-theme` trên `<html>` (desktop `base.html:22-23`; mobile `base_mobile.html:751-752` + đồng bộ `data-bs-theme`). Toggle ghi lại localStorage. Không dùng media query `prefers-color-scheme` tự động (chốt giữ hành vi hiện tại).

### 5.4 Chuẩn mực shell

- Menu item mới: desktop thêm vào sidebar đúng nhóm + offcanvas; mobile thêm vào drawer (bottom-nav chỉ dành cho 3 đích chính, không mở rộng nếu không có quyết định riêng).
- Shell chỉ thay đổi qua token/class có sẵn; mọi style shell mới viết vào `pc06-premium.css` mục 5.

---

## MỤC 6 — BẢN ĐỒ TOÀN BỘ MÀN HÌNH (45 template)

Mức token hóa (3 mức, đồng bộ với test contract):
- **A — migrated:** dùng trực tiếp `pc-*`.
- **B — bridge-only:** dùng class cũ/biến legacy đã được alias sang token (hiển thị đúng hệ màu premium nhưng chưa gắn class `pc-*`).
- **L — legacy:** chưa đụng (hiếm, chủ yếu template mồ côi).

### 6.1 Shell (2)

| Template | Mức | Mobile |
|---|---|---|
| `base.html` | A | — (chính là shell desktop, có offcanvas) |
| `base_mobile.html` | B | — (shell mobile; inline CSS riêng chưa qua token — xem 6.8) |

### 6.2 Auth (8)

| Cặp màn hình | Route | Mức | Mobile |
|---|---|---|---|
| `login` | `/login` | A (pilot) | Có |
| `password` | `/password` | A | Có |
| `reauth` | `/reauth` | A | Có |
| `two_factor_login` | `/login/two-factor` | A | **Không** (fallback desktop) |
| `two_factor_setup` | `/security/two-factor` | A | **Không** (fallback desktop) |

### 6.3 Dashboard (4)

| Template | Route | Mức | Mobile |
|---|---|---|---|
| `admin_dashboard` | `/admin` | A | Có |
| `report_dashboard` | `/tasks/report-dashboard` | A | **Không** |

### 6.4 Task (5 — tất cả không có bản mobile, fallback desktop responsive)

| Template | Route | Mức |
|---|---|---|
| `tasks_rebuild` (3.447 dòng) | `/tasks` | A |
| `task_detail_rebuild` (2.561 dòng) | `/tasks/<id>` | A |
| `task_import_drafts` | `/tasks/import-drafts` | A |
| `task_import_draft_detail` (2.149 dòng) | `/tasks/import-drafts/<id>` | A |
| `task_form_aggregation` | tổng hợp số liệu form | A |

### 6.5 Outline (2 — không mobile)

| Template | Mức | Ghi chú |
|---|---|---|
| `outline_editor` | A | giữ palette đặc thù `--navy/--seal/--gold` (chấp nhận locally, không lan rộng) |
| `outline_assign` | A | |

### 6.6 Quản trị & hệ thống (10)

| Template | Route | Mức | Mobile |
|---|---|---|---|
| `category_admin` | `/admin/categories` | A | Không |
| `module_categories` | `/admin/module-categories` | B (`pc06-page-summary-card`) | Có |
| `units` | `/admin/units` | B (Bootstrap + bridge) | Không |
| `delegations` | `/admin/delegations` | B (Bootstrap + bridge) | Không |
| `roles` | `/roles` | A | Có |
| `logs` | `/logs` | B (`pc06-page-summary-card`) | Có |
| `db_tool` | `/admin/db-tool` | B (`pc06-page-summary-card`) | Có |
| `system_update` | `/admin/system/update` | B (`pc06-page-summary-card`) | Có |

### 6.7 Trang khác (9 + 2 mồ côi)

| Template | Route | Mức | Mobile |
|---|---|---|---|
| `thong_bao` | `/thong-bao` | B | Có |
| `contacts` | `/contacts` | A | Có |
| `shortlinks` | `/links` | B | Có |
| `global_search` | tìm kiếm toàn cục | A | Không |
| `404` / `500` | error handler | L | Không |
| `styleguide` | `/admin/styleguide` (admin) | A | Không |
| `update.html`, `categories.html` | **mồ côi — không route nào render** | L | Cần dọn (đã dọn `dashboard.html` ở Subproject 6) |

### 6.8 Tổng kết khoảng cách

- 13 màn hình không có bản mobile riêng (fallback desktop) — chấp nhận theo chuẩn mực Mục 7.3.
- Shell mobile (`base_mobile.html`) còn khối biến CSS inline riêng + font Inter — chuẩn mực: thống nhất token + font (7.4).
- Các trang mức B: migrate khi có lô sửa giao diện chạm đến trang đó; không mở lô riêng chỉ để đổi class.

---

## MỤC 7 — BRIDGE LEGACY & QUY TẮC MIGRATE

### 7.1 Cơ chế bridge (variable aliasing)

`pc06-premium.css` mục 2 khai báo lại biến legacy trỏ vào token: `--primary`, `--primary-light`, `--primary-soft`, `--primary-rgb`, `--primary-gradient`, `--bg-body`, `--bg-surface`, `--bg-sidebar`, `--bg-subtle`, `--text-main`, `--text-muted`, `--border`, `--border-light`, `--shadow-sm/md/lg`, `--shadow-lvl1/2/3`, `--shadow-primary`, `--radius-sm/md/lg`, `--corner-card`, `--transition` (+ dark override cho `--primary-light`, `--primary-rgb`). Lớp 2: override biến Bootstrap `--bs-primary`, `--bs-body-*`, `--bs-border-color`, `--bs-link-*`, `--bs-font-sans-serif`.

→ Trang cũ hưởng hệ màu premium **mà không cần đổi markup**. Bridge là lớp tương thích, **không thêm alias mới** trừ khi có lý do chính đáng ghi trong PR.

### 7.2 Thứ tự nạp CSS (được test khóa)

Desktop `base.html`: bootstrap CDN → font-awesome → fonts → `style.css` → `bdhvs-layout.css` → `category-picker.css` → `<style>` inline → `mobile-responsive.css` → `flat-theme.css` → `{% block extra_head %}` → **`pc06-premium.css` (cuối cùng, kèm `?v=<bump>`)**.
Mobile `base_mobile.html`: fonts → font-awesome → bootstrap → `category-picker.css` → inline → `mobile-responsive.css` → `flat-theme.css` → **`pc06-premium.css`**.

Sửa token xong phải bump `?v=` để phá cache. Test `DesignSystemContractTests` chốt thứ tự này — không đổi mà không cập nhật test.

### 7.3 Quy tắc cho template mới / đang sửa

1. Template mới: dùng trực tiếp `pc-*` (mức A), thêm contract test marker (`pc-card`, `pc-btn`…) theo mẫu `tests/test_design_system.py`.
2. Template đang sửa: phần bị sửa phải nâng lên mức A; phần còn lại có thể giữ mức B.
3. Bản mobile: chỉ tạo `_mobile.html` khi bố cục mobile thực sự khác (không phải chỉ thu nhỏ); ngược lại dùng responsive trên bản desktop. Không bắt buộc tạo mobile cho 13 trang còn thiếu.
4. Cấm: hardcode hex/px mới; thêm `alert alert-*` mới; gọi `Swal.fire` trực tiếp (dùng `pcAlert`/`pcConfirm`); tự viết box-shadow/radius riêng ngoài token.
5. Class đặc thù sẵn có (`btn-bdhvs`, `pc06-page-summary-card`, `overview-*`, palette `--navy/--seal/--gold` của outline) được chấp nhận ở mức B — đã được bridge cover; không mở rộng phạm vi dùng của chúng sang template mới.

### 7.4 Nợ kỹ thuật đã ghi nhận (không chặn, có lộ trình ngầm)

| Nợ | Ưu tiên |
|---|---|
| `bdhvs-layout.css` còn hardcode hex (`#0066ff`, `#8b5cf6`…) trong `bdhvs-*`, `pc06-page-*` | Trung bình — map dần sang token khi sửa trang liên quan |
| `base_mobile.html` biến inline riêng + font Inter | Cao — thống nhất Be Vietnam Pro + token (chốt 7.5) |
| `style.css` còn khối token trùng lặp + utilities `glass-card/bento-card` | Thấp |
| `update.html`, `categories.html` mồ côi | Thấp — dọn khi rảnh lô |
| Flash mobile dùng Bootstrap alert | Trung bình — chuyển về helper Swal chung |

### 7.5 Chốt font thống nhất

Desktop đang dùng Be Vietnam Pro, mobile đang dùng Inter. **Chốt: toàn hệ thống dùng Be Vietnam Pro** (font của design system, hỗ trợ tiếng Việt tốt). Việc thay font mobile là sửa một dòng cấu hình font trong `base_mobile.html`, thực hiện trong lô sửa shell mobile gần nhất.

---

## MỤC 8 — ACCESSIBILITY & MOTION

- **Focus:** `:focus-visible` toàn cục dùng `--pc-focus-ring`; input lỗi dùng `--pc-focus-ring-danger`. Không xóa outline mà không thay bằng ring.
- **Reduced motion:** `prefers-reduced-motion: reduce` tắt toàn bộ animation/transition (đã có trong `pc06-premium.css`); mọi animation mới (skeleton, shimmer) phải nằm dưới quy tắc này.
- **Contrast:** chữ chính/muted đã chọn theo thang slate đảm bảo tương phản trên nền tương ứng; khi thêm màu mới phải kiểm contrast tối thiểu 4.5:1 với nền dùng nó (WCAG AA).
- **Motion chuẩn:** duration 120ms cho hover/press, 200ms cho state đổi, 320ms cho overlay/panel; easing duy nhất `--pc-ease`. Không thêm animation trang trí lớn (parallax, scale mạnh).
- **Aria:** giữ nguyên các aria-label/aria-* hiện có khi migrate (đã được các subproject trước tuân thủ).

---

## MỤC 9 — KIỂM THỬ UI (QUY ƯỚC HIỆN HÀNH)

File: `tests/test_design_system.py` (9 class contract test). Quy ước:

1. **Marker in source:** test đọc source template/CSS và assert chứa marker (`pc-card`, `pc-btn`, `pc-nav-item`, token, thứ tự nạp…) — không test visual bằng browser trong suite chuẩn.
2. **Ba mức chấp nhận** (ghi trong docstring test nhóm tương ứng): migrated (assert marker `pc-*`) / bridge-only (chấp nhận Bootstrap + bridge, assert không vỡ contract chức năng) / legacy (chỉ template mồ côi).
3. **Đăng ký màn hình mới:** thêm test class/nhóm mới theo mẫu `AdminPagesContractTests` — nhóm migrated trước, nới lỏng dần nếu trang chỉ đạt mức B.
4. **Render test:** chỉ với trang dễ mock (login, styleguide, dashboard); trang nghiệp vụ phức tạp (task core) dùng source-contract.
5. Suite hiện tại: 265 tests, 3 lỗi có sẵn không liên quan UI — mỗi subproject giao diện phải giữ nguyên con số này (không tăng lỗi).

---

## PHỤ LỤC — TRẠNG THÁI SO VỚI CHUẨN MỰC (tóm tắt điều hành)

| Lĩnh vực | Chuẩn mực | Trạng thái 2026-08-28 |
|---|---|---|
| Token màu/kích thước | Hoàn chỉnh light + dark | ✅ Đạt (+2 token accent violet/pink, `--pc-dur-loop`) |
| Component `pc-*` | 9 nhóm + skeleton + theme Swal | ✅ Đạt (M2, M3) |
| Token hóa màn hình | Mức A lý tưởng | ~60% mức A, ~35% mức B |
| Shell | Token hóa không đổi DOM | ✅ Đạt cả desktop + mobile, font thống nhất Be Vietnam Pro (M1) |
| Pattern hành vi | pc-empty/pc-skeleton/Swal-token | ✅ Đạt — skeleton + Swal theme đã triển khai, pc-empty phổ cập 4 trang, flash mobile về Swal (M3, M4); hex bdhvs-layout đã map hết (M5) |
| Accessibility | Focus ring + reduced motion | ✅ Đạt nền tảng |
| Kiểm thử | Contract marker test | ✅ Đạt, 274 tests |

**Giai đoạn 2 (subproject M1–M6, 2026-08-28):** đã triển khai xong toàn bộ lộ trình nợ
còn lại — shell mobile token + font, `pc-skeleton`, theme Swal theo token, phổ cập
`pc-empty` + flash mobile về Swal, map hex `bdhvs-layout.css`, dọn 2 template mồ côi
(`update.html`, `categories.html`). Việc còn lại: smoke thủ công light/dark trên trình
duyệt thật (M5) và migrate dần các trang mức B khi có lô sửa chạm đến.
