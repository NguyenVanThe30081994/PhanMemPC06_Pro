# Giao diện Giai đoạn 2 — Triển khai chuẩn mực từ Tổng thiết kế (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khắc phục 5 nhóm nợ còn lại ghi trong `docs/THIET_KE_TONG_GIAO_DIEN_2026.md` (Mục "PHỤ LỤC"): shell mobile token + font, `pc-skeleton`, theme Swal theo token, phổ cập `pc-empty` + flash mobile, map hex `bdhvs-layout.css`, dọn template mồ côi.

**Architecture:** Không tạo file CSS mới — mọi component mới (`pc-skeleton`, theme Swal `pc-swal-*`) thêm vào `static/css/pc06-premium.css` đúng cấu trúc mục 4 hiện có, bump `?v=`. Shell mobile bỏ biến hex inline, trỏ về token qua alias. Mỗi task có contract test marker trong `tests/test_design_system.py` theo mẫu hiện hành và commit riêng kèm entry `CHANGELOG.md`.

**Tech Stack:** Flask + Jinja, Bootstrap 5.3.2, SweetAlert2 11, CSS custom properties, unittest (runner `python3 run_tests.py`).

**Spec:** `docs/THIET_KE_TONG_GIAO_DIEN_2026.md` (chính là spec — kế hoạch này đối chiếu từng mục của nó)

## Global Constraints

- Không đổi route, tên field form, endpoint, id/hook JS nghiệp vụ (spec Mục 1.2 nguyên tắc 1).
- Token-first: cấm hardcode hex/px mới; giá trị mới phải thành token `--pc-*` trước (Mục 1.2 nguyên tắc 2).
- `pc06-premium.css` giữ vị trí nạp cuối `<head>` trong cả 2 base — test `test_base_templates_load_premium_css_after_flat_theme` khóa thứ tự này.
- Suite baseline: **265 tests, 3 lỗi có sẵn** — mọi task phải giữ nguyên số lỗi (không tăng).
- Chạy test: `python3 run_tests.py` (runner ép SQLite tạm — KHÔNG dùng `python3 -m unittest` trực tiếp vì test render chạm DB).
- Sửa file CSS nào thì bump `?v=` của chính file đó trong mọi template nạp nó: `style.css ?v=4.2.0`, `bdhvs-layout.css ?v=2.1.0`, `pc06-premium.css ?v=1.0.0` (cả `templates/base.html` lẫn `templates/base_mobile.html`).
- Mỗi task kết thúc bằng commit riêng + entry đầu `CHANGELOG.md` theo format hiện hành: `## 2026-08-28 (Giao diện — Subproject M<N>: <tóm tắt>)`.
- Font: 'Be Vietnam Pro' trong URL Google Fonts là `Be+Vietnam+Pro` (weights 400;500;600;700;800).

---

### Task 1: Shell mobile token hóa + font thống nhất Be Vietnam Pro

**Files:**
- Modify: `templates/base_mobile.html` (dòng 10 font link; dòng 17–55 khối `<style>` đầu; dòng 62 body font)
- Modify: `templates/base.html:12` (font URL bỏ Inter)
- Test: `tests/test_design_system.py` (thêm class mới cuối file)

**Interfaces:**
- Consumes: token `--pc-*` + bridge biến legacy đã có trong `pc06-premium.css` mục 1–2.
- Produces: `base_mobile.html` không còn hex trong khối biến đầu trang; font toàn hệ thống là Be Vietnam Pro. Task sau không phụ thuộc chi tiết nào từ task này.

- [ ] **Step 1: Viết test fail** — thêm vào cuối `tests/test_design_system.py`:

```python
class ShellMobileTokenTests(unittest.TestCase):
    """Subproject M1: shell mobile dùng token pc-* + font thống nhất Be Vietnam Pro
    (chuẩn mực Mục 5.4 + 7.5 — docs/THIET_KE_TONG_GIAO_DIEN_2026.md)."""

    def test_base_mobile_no_inter_font(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base_mobile.html"))
        self.assertNotIn("Inter", src)

    def test_base_mobile_inline_vars_use_pc_tokens(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base_mobile.html"))
        for token_ref in (
            "--primary: var(--pc-primary)",
            "--bg-body: var(--pc-bg)",
            "--bg-surface: var(--pc-bg-card)",
            "--text-main: var(--pc-text)",
            "--text-muted: var(--pc-text-muted)",
            "--border: var(--pc-border)",
        ):
            self.assertIn(token_ref, src)
        self.assertNotIn("--primary: #0066ff", src)

    def test_base_font_url_unified(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base.html"))
        self.assertIn("Be+Vietnam+Pro", src)
        self.assertNotIn("family=Inter", src)
```

- [ ] **Step 2: Chạy xác nhận fail** — `python3 run_tests.py`; 3 test mới của `ShellMobileTokenTests` FAIL.

- [ ] **Step 3: Sửa `base_mobile.html`:**
  1. Dòng 10, thay URL font: `<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">`
  2. Thay toàn bộ khối `:root { ... }` đầu `<style>` (dòng 18–40, gồm cả `[data-theme="dark"]` biến) bằng:

```css
        :root {
            --primary: var(--pc-primary);
            --primary-dark: var(--pc-primary-strong);
            --primary-light: var(--pc-primary-soft);
            --bg-body: var(--pc-bg);
            --bg-surface: var(--pc-bg-card);
            --bg-surface-rgb: 255, 255, 255;
            --text-main: var(--pc-text);
            --text-muted: var(--pc-text-muted);
            --border: var(--pc-border);
            --nav-height: 65px;
            --safe-bottom: env(safe-area-inset-bottom, 0px);
        }

        [data-theme="dark"] {
            --bg-surface-rgb: 17, 27, 46;
        }
```

  3. Giữ nguyên khối "Dark Mode Global Dynamic Overrides" (dòng 42–54 — các rule `.text-dark`, `.bg-white`… vẫn hợp lệ vì biến giờ resolve về token).
  4. Dòng 62: `font-family: var(--pc-font-sans, sans-serif);`

- [ ] **Step 4: Sửa `base.html:12`** — font URL chỉ còn `family=Be+Vietnam+Pro:wght@400;500;600;700;800` (bỏ `&family=Inter:wght@400;500;600;700`). Lưu ý `thong_bao.html:425,453` có chuỗi `font-family:Inter` trong CSS sinh tài liệu in/export — **giữ nguyên** (không phải shell).

- [ ] **Step 5: Chạy test pass** — `python3 run_tests.py`; `ShellMobileTokenTests` PASS, tổng vẫn 3 lỗi có sẵn.

- [ ] **Step 6: Commit + CHANGELOG** — entry: `## 2026-08-28 (Giao diện — Subproject M1: Shell mobile token hóa + font thống nhất)`; mô tả: bỏ Inter, biến mobile trỏ token, 3 test mới.

```bash
git add templates/base_mobile.html templates/base.html tests/test_design_system.py CHANGELOG.md
git commit -m "Giao diện: subproject M1 — shell mobile dùng token pc-*, thống nhất font Be Vietnam Pro"
```

---

### Task 2: Component `pc-skeleton` theo chuẩn mực Mục 4.2

**Files:**
- Modify: `static/css/pc06-premium.css` (thêm token `--pc-dur-loop` vào mục 1; thêm block skeleton cuối mục 4)
- Modify: `templates/base.html:676`, `templates/base_mobile.html:473` (bump `?v=1.0.0` → `?v=1.1.0`)
- Modify: `docs/THIET_KE_TONG_GIAO_DIEN_2026.md` (câu "animation shimmer bằng `--pc-dur-slow`" → "`--pc-dur-loop`")
- Test: `tests/test_design_system.py`

**Interfaces:**
- Produces: class `pc-skeleton`, `pc-skeleton-line`, `pc-skeleton-circle`, `pc-skeleton-card` + token `--pc-dur-loop: 1.4s` — Task 4+ không dùng, nhưng là API công khai cho template tương lai (quy tắc: spinner chỉ trong nút, khu vực async dùng skeleton).

- [ ] **Step 1: Viết test fail** — thêm method vào `DesignSystemContractTests` (hoặc class mới `SkeletonComponentTests`):

```python
class SkeletonComponentTests(unittest.TestCase):
    """Subproject M2: pattern pc-skeleton (chuẩn mực Mục 4.2)."""

    def test_premium_css_defines_skeleton(self):
        css = _read(PREMIUM_CSS)
        for cls in (
            "--pc-dur-loop:",
            ".pc-skeleton", ".pc-skeleton-line",
            ".pc-skeleton-circle", ".pc-skeleton-card",
            "@keyframes pc-skeleton-shimmer",
            '[data-theme="dark"] .pc-skeleton::after',
        ):
            self.assertIn(cls, css)
```

- [ ] **Step 2: Chạy xác nhận fail** — `python3 run_tests.py`.

- [ ] **Step 3: Thêm CSS** — trong `pc06-premium.css`:
  1. Mục 1 `:root`, sau khối Motion, thêm: `--pc-dur-loop: 1.4s;`
  2. Cuối mục 4 Components (trước mục 5 App shell), thêm:

```css
/* Skeleton — chuẩn mực Mục 4.2 (THIET_KE_TONG_GIAO_DIEN_2026.md) */
.pc-skeleton {
    position: relative;
    overflow: hidden;
    background: var(--pc-bg-subtle);
    border-radius: var(--pc-radius-md);
}
.pc-skeleton::after {
    content: "";
    position: absolute;
    inset: 0;
    transform: translateX(-100%);
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, .55), transparent);
    animation: pc-skeleton-shimmer var(--pc-dur-loop) var(--pc-ease) infinite;
}
[data-theme="dark"] .pc-skeleton::after {
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, .12), transparent);
}
@keyframes pc-skeleton-shimmer {
    100% { transform: translateX(100%); }
}
.pc-skeleton-line { height: 1em; }
.pc-skeleton-circle { border-radius: var(--pc-radius-pill); }
.pc-skeleton-card { height: 5rem; }
```

  (Global `prefers-reduced-motion` sẵn có ở mục Motion tự tắt shimmer.)
  3. Bump `pc06-premium.css` → `?v=1.1.0` trong cả 2 base template.
  4. Sửa câu trong spec Mục 4.2: "animation shimmer bằng `--pc-dur-loop` + `--pc-ease`".

- [ ] **Step 4: Chạy test pass** — `python3 run_tests.py`.

- [ ] **Step 5: Commit + CHANGELOG** — entry `Subproject M2: pattern pc-skeleton`.

```bash
git add static/css/pc06-premium.css templates/base.html templates/base_mobile.html tests/test_design_system.py docs/THIET_KE_TONG_GIAO_DIEN_2026.md CHANGELOG.md
git commit -m "Giao diện: subproject M2 — thêm pattern pc-skeleton + token --pc-dur-loop"
```

---

### Task 3: Theme SweetAlert2 theo token (chuẩn mực Mục 4.3)

**Files:**
- Modify: `static/css/pc06-premium.css` (block `.pc-swal-*` cuối mục 4) + bump `?v=1.1.0` → `?v=1.2.0` (2 base)
- Modify: `templates/base.html:1078-1102` (helper `pcAlert`/`pcConfirm`) + khối flash `base.html:~883-898`
- Modify: `templates/base_mobile.html:658-682` (2 helper này)
- Test: `tests/test_design_system.py`

**Interfaces:**
- Consumes: class `pc-btn`/`pc-btn-primary`/`pc-btn-danger`/`pc-btn-secondary` có sẵn.
- Produces: class CSS `pc-swal-popup`, `pc-swal-title`, `pc-swal-html`, `pc-swal-confirm`, `pc-swal-cancel` — Task 4 (flash mobile) dùng `popup/title/htmlContainer`; helper `pcAlert`/`pcConfirm` giữ nguyên chữ ký `(message, type)` / `(message)`.

- [ ] **Step 1: Viết test fail:**

```python
class SwalThemeTests(unittest.TestCase):
    """Subproject M3: SweetAlert2 ăn token pc-* (chuẩn mực Mục 4.3)."""

    def test_premium_css_defines_swal_theme(self):
        css = _read(PREMIUM_CSS)
        for cls in (
            ".pc-swal-popup", ".pc-swal-title", ".pc-swal-html",
            ".pc-swal-confirm", ".pc-swal-cancel",
        ):
            self.assertIn(cls, css)

    def test_pc_dialog_helpers_use_swal_theme(self):
        for name in ("base.html", "base_mobile.html"):
            src = _read(os.path.join(APP_ROOT, "templates", name))
            self.assertIn("pc-swal-popup", src)
            self.assertNotIn("btn btn-primary px-4", src)
            self.assertNotIn("btn btn-danger px-4 me-2", src)
```

- [ ] **Step 2: Chạy xác nhận fail.**

- [ ] **Step 3: Thêm CSS vào cuối mục 4 của `pc06-premium.css`:**

```css
/* SweetAlert2 theme theo token — chuẩn mực Mục 4.3 */
.pc-swal-popup {
    background: var(--pc-bg-card) !important;
    color: var(--pc-text) !important;
    border: 1px solid var(--pc-border);
    border-radius: var(--pc-radius-xl) !important;
    box-shadow: var(--pc-shadow-overlay);
    font-family: var(--pc-font-sans);
}
.pc-swal-title { color: var(--pc-text) !important; font-size: var(--pc-text-h3) !important; font-weight: 800; }
.pc-swal-html { color: var(--pc-text-muted) !important; }
.pc-swal-confirm, .pc-swal-cancel { box-shadow: none !important; }
```

  Bump `?v=1.2.0` trong cả 2 base.

- [ ] **Step 4: Sửa helper JS** (nội dung giống hệt nhau ở cả 2 base — `base.html:1078-1102`, `base_mobile.html:658-682`):

  `pcAlert`:
```js
            Swal.fire({
                icon: type || 'info',
                text: message,
                confirmButtonText: 'Đã hiểu',
                buttonsStyling: false,
                customClass: {
                    popup: 'pc-swal-popup',
                    title: 'pc-swal-title',
                    htmlContainer: 'pc-swal-html',
                    confirmButton: 'pc-btn pc-btn-primary pc-swal-confirm'
                }
            });
```

  `pcConfirm`:
```js
            return Swal.fire({
                title: 'Xác nhận',
                text: message || 'Bạn có chắc chắn?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Đồng ý',
                cancelButtonText: 'Hủy',
                reverseButtons: true,
                buttonsStyling: false,
                customClass: {
                    popup: 'pc-swal-popup',
                    title: 'pc-swal-title',
                    htmlContainer: 'pc-swal-html',
                    confirmButton: 'pc-btn pc-btn-danger pc-swal-confirm me-2',
                    cancelButton: 'pc-btn pc-btn-secondary pc-swal-cancel'
                }
            }).then(function (result) { return result.isConfirmed; });
```

- [ ] **Step 5: Sửa khối flash desktop** (`base.html` ~883–898): giữ cấu trúc Toast/mixin, thêm customClass + escape `|tojson`:

```js
                    Toast.fire({ icon: 'success', title: {{ message|tojson }} });
                    {% else %}
                    Swal.fire({
                        icon: '{{ "error" if category == "danger" else category }}',
                        text: {{ message|tojson }},
                        confirmButtonColor: 'var(--bs-primary)',
                        customClass: {
                            popup: 'pc-swal-popup',
                            title: 'pc-swal-title',
                            htmlContainer: 'pc-swal-html'
                        }
                    });
```

- [ ] **Step 6: Chạy test pass** — `python3 run_tests.py`.

- [ ] **Step 7: Commit + CHANGELOG** — entry `Subproject M3: theme SweetAlert2 theo token pc-*`.

```bash
git add static/css/pc06-premium.css templates/base.html templates/base_mobile.html tests/test_design_system.py CHANGELOG.md
git commit -m "Giao diện: subproject M3 — SweetAlert2 dùng theme pc-swal-* theo token"
```

---

### Task 4: Phổ cập `pc-empty` + flash mobile về Swal (chuẩn mực Mục 4.1 + 4.3)

**Files:**
- Modify: `templates/thong_bao.html:155-165` (2 khối empty)
- Check + modify nếu có cùng pattern: `templates/thong_bao_mobile.html` (grep `notify-empty`)
- Modify: `templates/contacts.html:178-182`
- Modify: `templates/roles.html:149-152`
- Modify: `templates/tasks_rebuild.html:141-145, 172-176, ~2567-2571` (3 khối `task-empty-state`) + xóa rule `.task-empty-state` trong `<style>` nội bộ nếu có
- Modify: `templates/base_mobile.html:515-524` (flash Bootstrap alert → Swal)
- Test: `tests/test_design_system.py`

**Interfaces:**
- Consumes: `pc-empty`/`pc-empty-icon`/`pc-empty-title` (đã có), `pc-swal-popup/title/htmlContainer` (Task 3), helper Swal.
- Produces: không có API mới — chỉ markup. Test contract khóa 4 file chứa `pc-empty`.

- [ ] **Step 1: Viết test fail:**

```python
class EmptyStateContractTests(unittest.TestCase):
    """Subproject M4: empty state dùng chuẩn pc-empty + flash mobile về Swal (Mục 4.1)."""

    def test_core_pages_use_pc_empty(self):
        for name in ("thong_bao.html", "contacts.html", "roles.html", "tasks_rebuild.html"):
            src = _read(os.path.join(APP_ROOT, "templates", name))
            self.assertIn("pc-empty", src)

    def test_mobile_flash_uses_swal_not_bootstrap_alert(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base_mobile.html"))
        self.assertNotIn("alert-dismissible", src)
        self.assertIn("Toast.fire", src)
```

- [ ] **Step 2: Chạy xác nhận fail.**

- [ ] **Step 3: Migrate markup** — 4 file, thay theo đúng ngữ cảnh hiện có:

  `thong_bao.html` (2 khối, giữ `id="notifyNoResults"` ở khối đầu):
```html
                <section class="pc-empty" id="notifyNoResults">
                    <div class="pc-empty-icon"><i class="fa-solid fa-bullhorn"></i></div>
                    <div class="pc-empty-title">Chưa có thông báo phù hợp</div>
                </section>
```
  (khối thứ hai: tiêu đề `Chưa có thông báo`, không có id)

  `contacts.html`:
```html
            <section class="pc-empty">
                <div class="pc-empty-icon"><i class="fa-solid fa-address-book"></i></div>
                <div class="pc-empty-title">Chưa có liên hệ</div>
            </section>
```

  `roles.html` (trong bảng):
```html
                            <tr>
                                <td colspan="{{ 6 if can_manage_roles else 5 }}" class="p-0">
                                    <div class="pc-empty">
                                        <div class="pc-empty-icon"><i class="fa-solid fa-user-slash"></i></div>
                                        <div class="pc-empty-title">Không có tài khoản trong vai trò đang chọn.</div>
                                    </div>
                                </td>
                            </tr>
```

  `tasks_rebuild.html` (3 khối — icon lần lượt `fa-check-circle`, `fa-inbox`, `fa-folder-open`):
```html
            <div class="pc-empty">
                <div class="pc-empty-icon"><i class="fa-solid fa-check-circle"></i></div>
                <div class="pc-empty-title">Không có công việc cần xử lý ngay.</div>
            </div>
```
  Bỏ inline `style="font-size: 3rem;"` và class `text-success`/`text-muted` trên icon (chuẩn icon 2rem từ CSS). Grep `task-empty-state` trong file: nếu `<style>` nội bộ còn rule `.task-empty-state` thì xóa rule đó.

  Chạy `grep -n 'notify-empty' templates/thong_bao_mobile.html` — nếu có khối empty tương tự, migrate y hệt pattern `pc-empty` và thêm `"thong_bao_mobile.html"` vào list test Step 1.

- [ ] **Step 4: Flash mobile** — thay khối `{% with messages ... %}` tại `base_mobile.html:515-524` bằng (parity với desktop, thêm customClass của Task 3):

```html
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
            <script>
                document.addEventListener('DOMContentLoaded', function () {
                    const Toast = Swal.mixin({
                        toast: true,
                        position: 'top-end',
                        showConfirmButton: false,
                        timer: 3000,
                        timerProgressBar: true
                    });
                    {% for category, message in messages %}
                    {% if category == 'success' %}
                    Toast.fire({ icon: 'success', title: {{ message|tojson }} });
                    {% else %}
                    Swal.fire({
                        icon: '{{ "error" if category == "danger" else category }}',
                        text: {{ message|tojson }},
                        confirmButtonColor: 'var(--bs-primary)',
                        customClass: {
                            popup: 'pc-swal-popup',
                            title: 'pc-swal-title',
                            htmlContainer: 'pc-swal-html'
                        }
                    });
                    {% endif %}
                    {% endfor %}
                });
            </script>
            {% endif %}
        {% endwith %}
```

  (Swal nạp `defer` trước đó nên đã sẵn sàng khi `DOMContentLoaded` fired.)

- [ ] **Step 5: Chạy test pass** — `python3 run_tests.py`.

- [ ] **Step 6: Commit + CHANGELOG** — entry `Subproject M4: phổ cập pc-empty + flash mobile về Swal`.

```bash
git add templates/thong_bao.html templates/thong_bao_mobile.html templates/contacts.html templates/roles.html templates/tasks_rebuild.html templates/base_mobile.html tests/test_design_system.py CHANGELOG.md
git commit -m "Giao diện: subproject M4 — pc-empty chuẩn hóa 4 trang, flash mobile dùng Swal theo token"
```

---

### Task 5: Map hex `bdhvs-layout.css` sang token (chuẩn mực Mục 7.3.1)

**Files:**
- Modify: `static/css/bdhvs-layout.css` (toàn bộ hex theo bảng dưới)
- Modify: `static/css/pc06-premium.css` (thêm 2 accent token vào `:root` mục 1) + bump `?v=1.2.0` → `?v=1.3.0`
- Modify: `templates/base.html:15` + `templates/base_mobile.html` (bump `bdhvs-layout.css ?v=2.1.0` → `?v=2.2.0`)
- Test: `tests/test_design_system.py`

**Interfaces:**
- Consumes: toàn bộ token `--pc-*` hiện có + 2 token mới `--pc-accent-violet`, `--pc-accent-pink`.
- Produces: `bdhvs-layout.css` không còn brand/semantic hex — các selector `bdhvs-*`, `pc06-*` hưởng palette premium qua token.

**Bảng map (áp dụng cho MỌI vị trí trong file, kể cả trong block `[data-theme="dark"]` — token neutral bất biến theo theme nên 1:1; token semantic tự đổi đúng theo theme):**

| Hex cũ | Token mới | Ghi chú |
|---|---|---|
| `#0f172a` | `var(--pc-neutral-900)` | 16 chỗ |
| `#64748b` | `var(--pc-neutral-500)` | 13 chỗ |
| `#0052cc` | `var(--pc-primary-strong)` | 9 chỗ — chủ ý chuyển sang navy |
| `#0066ff` | `var(--pc-primary)` | 7 chỗ — chủ ý |
| `#dbeafe` | `var(--pc-primary-100)` | |
| `#e2e8f0` | `var(--pc-neutral-200)` | |
| `#f8fafc` | `var(--pc-bg)` | |
| `#f1f5f9` | `var(--pc-bg-subtle)` | |
| `#fef3c7` | `var(--pc-warning-bg)` | |
| `#fee2e2` | `var(--pc-danger-bg)` | |
| `#eff6ff` | `var(--pc-primary-50)` | |
| `#10b981` | `var(--pc-success)` | |
| `#f59e0b` | `var(--pc-warning)` | |
| `#e0f2fe` | `var(--pc-primary-50)` | |
| `#dcfce7` | `var(--pc-success-bg)` | |
| `#d1fae5` | `var(--pc-success-bg)` | |
| `#bfdbfe` | `var(--pc-primary-200)` | |
| `#bae6fd` | `var(--pc-info-border)` | |
| `#b91c1c` | `var(--pc-danger)` | |
| `#92400e` | `var(--pc-warning-text)` | |
| `#8b5cf6` | `var(--pc-accent-violet)` | token mới |
| `#ec4899` | `var(--pc-accent-pink)` | token mới |
| `#1e3a8a` | `var(--pc-primary-900)` | |
| `#082f49` | `var(--pc-primary-950)` | |
| `#166534` | `var(--pc-success-text)` | |
| `#475569` | `var(--pc-neutral-600)` | |
| `#334155` | `var(--pc-neutral-700)` | |
| `#1e293b` | `var(--pc-neutral-800)` | |
| `#f0fdf4` | `var(--pc-success-bg)` | |
| `#fff`, `#ffffff` | **giữ nguyên** | chữ trắng trên nền màu — đúng cả 2 theme |

- [ ] **Step 1: Viết test fail:**

```python
class BdhvsLayoutTokenTests(unittest.TestCase):
    """Subproject M5: bdhvs-layout.css hết hardcode brand/semantic hex (Mục 7.3.1)."""

    def test_bdhvs_layout_no_hardcoded_hex(self):
        css = _read(os.path.join(APP_ROOT, "static", "css", "bdhvs-layout.css"))
        for banned in (
            "#0066ff", "#0052cc", "#dbeafe", "#bfdbfe", "#eff6ff", "#e0f2fe",
            "#bae6fd", "#1e3a8a", "#082f49", "#f59e0b", "#92400e", "#fef3c7",
            "#fee2e2", "#b91c1c", "#10b981", "#166534", "#dcfce7", "#d1fae5",
            "#f0fdf4", "#8b5cf6", "#ec4899", "#0f172a", "#64748b", "#e2e8f0",
            "#f8fafc", "#f1f5f9", "#475569", "#334155", "#1e293b",
        ):
            self.assertNotIn(banned, css)
```

- [ ] **Step 2: Chạy xác nhận fail.**

- [ ] **Step 3: Thêm 2 token accent** vào `pc06-premium.css` `:root` (sau khối Semantic):

```css
    /* Accent phụ trợ (icon màu) — dùng hạn chế, không làm màu chức năng */
    --pc-accent-violet: #8b5cf6;
    --pc-accent-pink: #ec4899;
```

- [ ] **Step 4: Áp bảng map** cho `bdhvs-layout.css` — sửa từng dòng (dùng grep -n theo từng hex để không sót). Sau khi xong chạy `grep -oE '#[0-9a-fA-F]{3,6}\b' static/css/bdhvs-layout.css | sort -u` — kết quả chỉ còn `#fff`/`#ffffff`. Bump version: `bdhvs-layout.css ?v=2.2.0` (cả 2 base), `pc06-premium.css ?v=1.3.0` (cả 2 base).

- [ ] **Step 5: Smoke thủ công** — chạy server (`./start_server.sh` hoặc `python3 app.py`), mở `/admin`, `/tasks`, `/thong-bao` ở cả light + dark, xác nhận không vỡ màu (panel navy, icon accent, hero). Không có browser test tự động cho bước này.

- [ ] **Step 6: Chạy test pass** — `python3 run_tests.py`.

- [ ] **Step 7: Commit + CHANGELOG** — entry `Subproject M5: bdhvs-layout.css map hết hex sang token`.

```bash
git add static/css/bdhvs-layout.css static/css/pc06-premium.css templates/base.html templates/base_mobile.html tests/test_design_system.py CHANGELOG.md
git commit -m "Giao diện: subproject M5 — bdhvs-layout.css hết hardcode hex, thêm token accent violet/pink"
```

---

### Task 6: Dọn template mồ côi (`update.html`, `categories.html`)

**Files:**
- Delete: `templates/update.html`, `templates/categories.html`
- Modify: `tests/test_design_system.py` (xóa `test_categories_uses_legacy_bridge`)
- Test: `tests/test_design_system.py`

**Interfaces:**
- Consumes: không.
- Produces: không — chỉ dọn. `system_update.html` KHÔNG liên quan (có route `admin_bp.system_update`, giữ nguyên).

- [ ] **Step 1: Verify mồ côi** — `grep -rn "update\.html\|'categories\.html'\|\"categories\.html\"" routes/ services/ app.py task_page_builders.py task_workspace.py tests/ --include='*.py' | grep -v module_categories | grep -v category_admin | grep -v system_update` — kết quả chỉ được có `tests/test_design_system.py:500` (test đọc source). Nếu thấy bất kỳ render nào khác → DỪNG, báo cáo lại.

- [ ] **Step 2: Xóa test đọc source mồ côi** — xóa method `test_categories_uses_legacy_bridge` (`tests/test_design_system.py:498-501`) cùng docstring; docstring class `AdminPagesContractTests` không cần sửa (không liệt kê tên file categories).

- [ ] **Step 3: Xóa 2 file:**

```bash
git rm templates/update.html templates/categories.html
```

- [ ] **Step 4: Chạy test** — `python3 run_tests.py`: 264 tests (265 − 1 test đã xóa), vẫn 3 lỗi có sẵn.

- [ ] **Step 5: Commit + CHANGELOG** — entry `Subproject M6: dọn template mồ côi update.html + categories.html`.

```bash
git add tests/test_design_system.py CHANGELOG.md
git commit -m "Giao diện: subproject M6 — dọn template mồ côi update.html + categories.html"
```

---

## Self-Review (đã chạy khi viết kế hoạch)

1. **Spec coverage:** 5 dòng "Lộ trình gợi ý" trong Phụ lục spec → Task 1 (shell mobile + font), Task 2 (pc-skeleton), Task 3 (theme Swal), Task 4 (pc-empty + flash mobile), Task 5 (hex bdhvs + token accent), Task 6 (mồ côi). Đủ.
2. **Placeholder scan:** mọi step có code/lệnh cụ thể; không TBD/TODO.
3. **Type consistency:** tên class `pc-swal-*` thống nhất giữa Task 3 (định nghĩa) và Task 4 (sử dụng); version bump tuần tự 1.0.0 → 1.1.0 (M2) → 1.2.0 (M3) → 1.3.0 (M5); chữ ký helper giữ nguyên.
