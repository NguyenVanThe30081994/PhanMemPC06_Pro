# Nền tảng thiết kế premium — Design Spec (Subproject 1)

**Ngày:** 2026-08-28
**Trạng thái:** Đã duyệt thiết kế, chờ triển khai
**Phạm vi:** Subproject 1 trong lộ trình 6 subproject làm mới toàn bộ giao diện PhanMemPC06_Pro

---

## 1. Bối cảnh

PhanMemPC06_Pro là hệ thống quản lý giao việc / báo cáo (Flask + Jinja, ~45
template gồm bản desktop và `*_mobile.html` riêng). Giao diện hiện dùng
Bootstrap 5 (CDN) + Font Awesome + ~120KB CSS tùy chỉnh
(`style.css`, `bdhvs-layout.css`, `flat-theme.css`, `mobile-responsive.css`),
đã có cơ chế theme light/dark qua `data-theme` + `localStorage`.

Mục tiêu tổng thể: làm mới **toàn bộ giao diện phần mềm, mọi chức năng, mọi
link** theo chuẩn premium. Vì phạm vi quá lớn cho một spec, lộ trình chia
thành 6 subproject; tài liệu này chốt subproject đầu tiên — **nền tảng thiết
kế** — làm cơ sở cho 5 subproject sau.

## 2. Các quyết định đã chốt

| Quyết định | Lựa chọn |
|---|---|
| Lộ trình tổng | 6 subproject: (1) Nền tảng thiết kế → (2) Auth & bảo mật → (3) Dashboards → (4) Phân hệ Task → (5) Trang quản trị → (6) Trang còn lại. Subproject 1 chặn tất cả các phần sau. |
| Thẩm mỹ | Premium (chuẩn cao cấp, tham chiếu skill `high-end-visual-design` và `design-taste-frontend` đã cài trong `skills/` của repo) |
| Nền CSS | Giữ Bootstrap 5, thêm tầng tokens + component CSS đè lên (Approach A — "Premium Overlay") |
| Mobile | Giữ cơ chế template kép (desktop + `*_mobile.html`), design system phục vụ cả hai |
| Bàn giao | Foundation đầy đủ + pilot trang login (desktop & mobile) + trang style guide nội bộ |
| Nguyên tắc | Giữ nguyên 100% chức năng: không đổi route, tên field, endpoint, model. Chỉ đổi tầng trình bày. |

## 3. Kiến trúc tầng CSS

### 3.1 File mới duy nhất: `static/css/pc06-premium.css`

Thứ tự load thực tế hiện nay (đã kiểm chứng trong template):

- `base.html`: head nạp bootstrap CDN → font-awesome CDN → fonts →
  `style.css` → `bdhvs-layout.css` → `category-picker.css`; **cuối body** nạp
  `mobile-responsive.css` → `flat-theme.css`.
- `base_mobile.html`: head nạp fonts → font-awesome CDN → bootstrap CDN →
  `category-picker.css`; **cuối body** nạp `mobile-responsive.css` →
  `flat-theme.css`.

Quy tắc: `pc06-premium.css` được nạp **sau `flat-theme.css` tại cùng vị trí
cuối body** ở cả hai template (kèm `?v=<bump>`), đảm bảo thắng cascade.

Cấu trúc bên trong file, theo đúng thứ tự:

1. **Tokens** — CSS custom properties trong `:root` (light) và
   `[data-theme="dark"]` (dark).
2. **Bootstrap overrides** — ánh xạ biến Bootstrap (`--bs-*` khi cần) và đè
   các component Bootstrap theo token.
3. **Components `pc-*`** — xem mục 5.
4. **Motion & a11y** — transition chuẩn, `prefers-reduced-motion`,
   `:focus-visible`.

### 3.2 Quy ước loại dần CSS cũ (cho subproject 2–6)

- Không xóa bất kỳ file CSS cũ nào trong subproject 1.
- Khi một subproject sau chạm vào trang nào, markup trang đó chuyển sang
  class `pc-*`.
- Chỉ xóa một block CSS cũ sau khi `grep` toàn bộ `templates/` xác nhận
  không selector nào của block còn được dùng.

## 4. Design tokens

Tiền tố thống nhất: `--pc-`. Các nhóm bắt buộc:

### 4.1 Màu sắc

- `--pc-primary-50 … --pc-primary-900`: thang màu chính, hướng navy premium
  (giá trị cụ thể chốt khi triển khai theo guidance của skill design, phải
  đạt tương phản WCAG AA cho chữ trên nền).
- Semantic: `--pc-success`, `--pc-warning`, `--pc-danger`, `--pc-info` + biến
  kèm `-bg`, `-border`, `-text` cho mỗi loại.
- Neutral: `--pc-neutral-0 … --pc-neutral-950` (khoảng 11 bậc).
- Surface: `--pc-bg` (nền trang), `--pc-bg-subtle` (vùng trũng),
  `--pc-bg-card` (card), `--pc-border` (viền mặc định).
- Text: `--pc-text`, `--pc-text-muted`, `--pc-text-subtle`.
- Tất cả token trên có giá trị riêng trong `[data-theme="dark"]`; chuyển
  theme không được gây flash (script đặt `data-theme` hiện có đã chạy trước
  render — giữ nguyên).

### 4.2 Typography

- Font toàn app: **Be Vietnam Pro** (400/500/600/700/800). `login.html` hiện
  dùng Montserrat + Inter, `base.html` dùng Inter/Be Vietnam Pro — đồng bộ về
  một font duy nhất.
- Scale: `--pc-text-display`, `-h1`, `-h2`, `-h3`, `-body`, `-sm`, `-xs` kèm
  line-height tương ứng (`--pc-leading-*`).
- `--pc-tracking-tight/normal/wide` cho label viết hoa nhỏ.

### 4.3 Spacing, radius, shadow, motion, z-index

- Spacing: `--pc-space-1 … --pc-space-12`, bước 4px.
- Radius: `--pc-radius-sm` / `md` / `lg` / `xl` / `pill`.
- Shadow: `--pc-shadow-xs` / `sm` / `md` / `lg` / `overlay` (thang tăng dần;
  dark theme dùng shadow trầm + border tinh tế thay vì bóng đen đặc).
- Motion: `--pc-dur-fast` (≤120ms), `--pc-dur-base` (≈200ms),
  `--pc-dur-slow` (≈320ms), `--pc-ease` (ease-out chuẩn). Toàn bộ animation
  tôn trọng `prefers-reduced-motion: reduce`.
- Z-index: `--pc-z-dropdown`, `-sticky`, `-modal`, `-toast` theo bậc thang
  cố định, không dùng số tùy tiện trong component.

## 5. Thư viện component `pc-*`

Chỉ xây các component đang được dùng thật trong hệ template (không thêm
component suy đoán). Danh sách chốt:

| Component | Class chính | Ghi chú |
|---|---|---|
| Button | `.pc-btn` + `-primary` `-secondary` `-ghost` `-danger` + `-sm` `-lg` + `-loading` | Trạng thái disabled, loading spinner |
| Form | `.pc-form-group`, `.pc-label`, `.pc-input`, `.pc-select`, `.pc-help`, `.pc-invalid` | Focus ring chuẩn, invalid state đỏ + icon |
| Card | `.pc-card`, `.pc-card-header`, `.pc-card-body`, `.pc-card-footer` | Nền surface, radius/shadow theo token |
| Table | `.pc-table` (+ `.pc-table-hover`) | Header subtle, row hover, responsive wrap |
| Alert | `.pc-alert` + `-success` `-warning` `-danger` `-info` | Dùng cho flash messages |
| Badge | `.pc-badge` + các biến thể màu + variant trạng thái task | Đồng bộ màu trạng thái `task_mode`/assignment |
| Nav | `.pc-topbar`, `.pc-sidebar`, `.pc-nav-item`, `.pc-nav-section` | Dùng trong shell ứng dụng |
| Modal | `.pc-modal` (đè Bootstrap modal) | Header/body/footer theo token |
| Page header | `.pc-page-header`, `.pc-page-title`, `.pc-page-actions` | Chuẩn hóa đầu trang |
| Empty state | `.pc-empty`, `.pc-empty-icon`, `.pc-empty-title` | Cho bảng/danh sách rỗng |
| Pagination | `.pc-pagination` | Đè Bootstrap pagination |

Mọi component phải render đúng ở cả 2 theme light/dark và breakpoint mobile.

## 6. Nâng cấp `base.html` / `base_mobile.html`

- Thiết kế lại shell ứng dụng bằng token mới: topbar, điều hướng, container
  nội dung chính, footer.
- **Giữ nguyên 100% hành vi JS hiện có**: đặt `data-theme` sớm, nút chuyển
  theme, meta CSRF, nhận diện thiết bị, khối Việt hóa thông báo trình duyệt,
  khối chặn DevTools, hệ thống thông báo (notification), các script CDN
  (SweetAlert2, Chart.js).
- Chuyển các khối `<style>` inline trong `base.html` vào
  `pc06-premium.css` nơi có thể; chỗ phụ thuộc trạng thái động thì giữ lại
  nhưng dọn về chọn lọc theo token.

## 7. Pilot: trang login (desktop + mobile)

`login.html` và `login_mobile.html` là trang standalone (không extends base).

- Viết lại markup bằng hệ `pc-*`; nạp Bootstrap + Font Awesome + font +
  `pc06-premium.css` trực tiếp trong `<head>`.
- Desktop: bố cục 2 vùng — panel giới thiệu/thương hiệu + card form.
  Mobile: card toàn màn hình.
- **Bắt buộc giữ nguyên về chức năng:**
  - `form method="POST"`, input `name="username"`, `name="password"`
    (`id="password_field"`), thuộc tính `autocomplete`.
  - JS tự tiêm `csrf_token` vào form.
  - Nút/ link Google OAuth tới `/auth/google`.
  - Modal khôi phục mật khẩu.
  - Luồng chuyển hướng 2FA hiện có.
  - Ảnh nền `static/img/cand_logo_bg.jpg`: được phép xử lý lại bằng lớp phủ
    token (overlay/gradient) cho hợp thẩm mỹ premium nhưng không xóa file và
    không đổi đường dẫn.

## 8. Trang style guide

- Route mới: `/admin/styleguide` trong `routes/admin.py`, **chỉ admin** (dùng
  cơ chế phân quyền hiện hành; không sinh hệ phân quyền mới).
- Template `styleguide.html` extends `base.html`.
- Nội dung: bảng màu (primary, semantic, neutral), mẫu typography, toàn bộ
  component `pc-*` ở các trạng thái chính, minh họa light/dark cạnh nhau.
- Mục đích: nghiệm thu subproject 1 và làm tài liệu tham chiếu trực quan cho
  subproject 2–6.

## 9. Trạng thái & lỗi

- Input: invalid (kèm thông báo), disabled, readonly, focus.
- Button: disabled, loading.
- Flash/alert: 4 biến thể semantic, dùng lại cơ chế flash hiện có.
- Bảng/danh sách: empty state chuẩn.
- Giữ nguyên khối JS Việt hóa thông báo trình duyệt của base.

## 10. Kiểm thử & nghiệm thu

1. **Unit test:** chạy toàn bộ suite hiện có (kỳ vọng 222 test OK — không
   đụng routes/models/logic).
2. **Thủ công trên trình duyệt** (server local qua `START_SERVER_MAC.sh`):
   - Login desktop: đăng nhập thành công, sai mật khẩu (thông báo lỗi), nút
     Google OAuth, modal khôi phục mật khẩu, chuyển hướng 2FA.
   - Login mobile (giả lập UA mobile): cùng các bước trên với
     `login_mobile.html`.
   - Light/dark: chuyển theme trên login, shell ứng dụng, style guide —
     không flash, không vỡ màu.
   - Style guide render đủ section ở cả 2 theme.
   - Kiểm tra nhanh 3–4 trang trọng yếu sau đăng nhập (dashboard,
     tasks_rebuild, một trang admin): không vỡ layout, chức năng cũ chạy.
3. **Tiêu chí đạt:**
   - Toàn bộ 45 template còn hoạt động; không xóa CSS cũ.
   - Tokens + components phủ đủ mục 4–5; hoạt động ở 2 theme.
   - Login (2 bản) và style guide đạt chuẩn premium.

## 11. Ngoài phạm vi (subproject này)

- Không đổi routes/API/logic nghiệp vụ, models, migrations.
- Không restyle các trang ngoài shell + login + style guide (thuộc
  subproject 2–6).
- Không gộp template desktop/mobile (tách subproject riêng sau này nếu cần).
- Không thêm build tooling (Sass/PostCSS), không tự host CDN.

## 12. Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| Xung đột cascade với CSS cũ | `pc06-premium.css` load cuối; chọn lọc có chủ đích, tránh `!important` tràn lan |
| Vỡ trang chưa migrate | CSS cũ giữ nguyên làm fallback; kiểm tra nhanh các trang trọng yếu |
| Khác biệt 2 theme | Token bắt buộc có cặp light/dark; style guide hiển thị song song |
| Phụ thuộc CDN (Bootstrap/FA/font) | Giữ nguyên hiện trạng (đã quyết định); ghi nhận làm cải tiến riêng sau này |
