# Nền tảng thiết kế premium — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây tầng design system premium (tokens + component `pc-*`) trên nền Bootstrap 5, nâng cấp shell ứng dụng, pilot trang login (desktop + mobile) và trang style guide nội bộ — subproject 1 của lộ trình 6 subproject làm mới toàn bộ giao diện.

**Architecture:** Một file CSS mới `static/css/pc06-premium.css` nạp cuối `<head>` chứa: tokens → bridge biến legacy → Bootstrap overrides → components `pc-*` → shell → motion/a11y. CSS cũ giữ nguyên làm fallback; tầng "bridge" ánh xạ biến legacy (`--primary`, `--bg-surface`…) sang token mới để cả trang chưa migrate cũng hưởng palette mới. Shell được premium-hóa bằng CSS trên class hiện có (không dựng lại DOM) để không vỡ JS.

**Tech Stack:** Flask/Jinja (không đổi backend), Bootstrap 5.3.2 CDN, Font Awesome 6, Be Vietnam Pro, `unittest` + `app.test_client()` (chạy qua `python3 run_tests.py`), browser-use MCP để kiểm tra trực quan.

**Spec:** `docs/superpowers/specs/2026-08-28-nen-tang-thiet-ke-premium-design.md`

## Global Constraints

- Giữ nguyên 100% chức năng: KHÔNG đổi route, endpoint, tên `name`/`id` của input, JS hook, models, migrations.
- KHÔNG xóa hoặc sửa nội dung CSS cũ (`style.css`, `bdhvs-layout.css`, `flat-theme.css`, `mobile-responsive.css`, `category-picker.css`).
- `pc06-premium.css` nạp cuối `<head>`: trong `base.html` đặt ngay sau `{% block extra_head %}{% endblock %}`; trong `base_mobile.html` đặt ngay sau link `flat-theme.css`; luôn kèm `?v=1.0.0`.
- Font duy nhất toàn app: Be Vietnam Pro (400/500/600/700/800).
- Mọi token/component hoạt động ở cả `:root` (light) và `[data-theme="dark"]`.
- Không thêm dependency Python, không build tooling, không tự host CDN.
- Luôn chạy test bằng `python3 run_tests.py` (runner tự cô lập SQLite — KHÔNG chạy unittest trực tiếp trên DB thật).
- Bảng màu/giá trị token bên dưới là ĐÃ CHỐT — không tự ý đổi palette; chỉ tinh chỉnh khoảng cách/layout nếu vỡ.

## File Structure

- Create: `static/css/pc06-premium.css` — toàn bộ design system (tokens, bridge, overrides, components, shell, login helpers, motion/a11y).
- Create: `templates/styleguide.html` — trang tra cứu design system, extends `base.html`, dùng `{% block content %}`.
- Create: `tests/test_design_system.py` — contract test (token, component, wiring, pilot login, quyền styleguide).
- Modify: `templates/base.html:675-676` — thêm link premium CSS sau block `extra_head`.
- Modify: `templates/base_mobile.html:471-473` — thêm link premium CSS sau `flat-theme.css`.
- Modify: `templates/login.html` — viết lại markup trên hệ `pc-*` (giữ nguyên form/JS/modal).
- Modify: `templates/login_mobile.html` — viết lại nội dung block (giữ extends `base_mobile.html`).
- Modify: `routes/admin.py:791` (sau `category_admin`) — thêm route `/admin/styleguide`.
- Modify: `CHANGELOG.md` — entry tổng kết ở Task 8.

---

### Task 1: Tokens + bridge + Bootstrap overrides + nối CSS vào base templates

**Files:**
- Create: `static/css/pc06-premium.css`
- Create: `tests/test_design_system.py` (phần token + wiring)
- Modify: `templates/base.html:675-676`
- Modify: `templates/base_mobile.html:471-473`

**Interfaces:**
- Consumes: không có (task đầu).
- Produces: mọi token `--pc-*` (Task 2–7 dùng), các biến legacy được bắc cầu (`--primary`, `--bg-surface`, `--text-main`, `--border`, `--shadow-*`, `--radius-*`, `--transition`…), helper đọc file CSS trong test.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_design_system.py`:

```python
# -*- coding: utf-8 -*-
"""Contract test cho design system premium PC06 (subproject 1).

Kiểm tra: tokens/component tồn tại trong pc06-premium.css, base templates nạp
CSS đúng vị trí, trang login giữ nguyên contract chức năng.
"""
import os
import unittest
from datetime import datetime

from app import app
from models import User, db

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREMIUM_CSS = os.path.join(APP_ROOT, "static", "css", "pc06-premium.css")

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class DesignSystemContractTests(unittest.TestCase):
    def test_premium_css_defines_core_tokens(self):
        css = _read(PREMIUM_CSS)
        for token in (
            "--pc-primary:", "--pc-primary-soft:", "--pc-bg:", "--pc-bg-subtle:",
            "--pc-bg-card:", "--pc-text:", "--pc-text-muted:", "--pc-border:",
            "--pc-radius-md:", "--pc-shadow-md:", "--pc-space-4:", "--pc-text-body:",
            "--pc-dur-base:", "--pc-ease:", "--pc-z-modal:", "--pc-focus-ring:",
        ):
            self.assertIn(token, css, f"Thiếu token {token} trong pc06-premium.css")
        self.assertIn('[data-theme="dark"]', css)
        self.assertIn("prefers-reduced-motion", css)

    def test_premium_css_bridges_legacy_vars(self):
        css = _read(PREMIUM_CSS)
        for legacy in (
            "--primary: var(--pc-primary)", "--bg-surface: var(--pc-bg-card)",
            "--bg-body: var(--pc-bg)", "--text-main: var(--pc-text)",
            "--border: var(--pc-border)",
        ):
            self.assertIn(legacy, css, f"Thiếu bridge {legacy}")

    def test_base_templates_load_premium_css_after_flat_theme(self):
        for name in ("base.html", "base_mobile.html"):
            html = _read(os.path.join(APP_ROOT, "templates", name))
            idx_flat = html.find("flat-theme.css")
            idx_premium = html.find("pc06-premium.css")
            self.assertNotEqual(idx_flat, -1, f"{name} mất flat-theme.css?")
            self.assertNotEqual(idx_premium, -1, f"{name} chưa nạp pc06-premium.css")
            self.assertGreater(idx_premium, idx_flat, f"{name}: premium phải nạp SAU flat-theme")
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python3 run_tests.py tests.test_design_system`
Expected: FAIL — `FileNotFoundError: ... pc06-premium.css` (file chưa tồn tại). Nếu runner không nhận tham số module, chạy `python3 run_tests.py` và tìm 3 test mới fail trong output.

- [ ] **Step 3: Tạo `static/css/pc06-premium.css` với tokens + bridge + overrides + nền + motion**

```css
/* ============================================================
   PC06 PREMIUM DESIGN SYSTEM — Subproject 1
   Nạp cuối <head>, sau flat-theme.css. Component dùng tiền tố pc-.
   Spec: docs/superpowers/specs/2026-08-28-nen-tang-thiet-ke-premium-design.md
   ============================================================ */

/* ---------- 1. Tokens ---------- */
:root {
    /* Primary — navy premium */
    --pc-primary-50: #f2f6fc;
    --pc-primary-100: #e3ebf7;
    --pc-primary-200: #c5d7ee;
    --pc-primary-300: #98b7df;
    --pc-primary-400: #6491cb;
    --pc-primary-500: #3f6db3;
    --pc-primary-600: #2b5396;
    --pc-primary-700: #24437a;
    --pc-primary-800: #203963;
    --pc-primary-900: #1d3053;
    --pc-primary-950: #121f38;
    --pc-primary: var(--pc-primary-600);
    --pc-primary-strong: var(--pc-primary-700);
    --pc-primary-soft: var(--pc-primary-50);
    --pc-primary-ring: rgba(43, 83, 150, 0.28);

    /* Semantic */
    --pc-success: #15803d;
    --pc-success-bg: #ecfdf3;
    --pc-success-border: #bbe7c9;
    --pc-success-text: #14532d;
    --pc-warning: #b45309;
    --pc-warning-bg: #fffbeb;
    --pc-warning-border: #fde5ae;
    --pc-warning-text: #7c3d05;
    --pc-danger: #dc2626;
    --pc-danger-bg: #fef2f2;
    --pc-danger-border: #fecaca;
    --pc-danger-text: #7f1d1d;
    --pc-info: #0369a1;
    --pc-info-bg: #f0f9ff;
    --pc-info-border: #bae6fd;
    --pc-info-text: #075985;

    /* Neutral (slate) */
    --pc-neutral-0: #ffffff;
    --pc-neutral-50: #f8fafc;
    --pc-neutral-100: #f1f5f9;
    --pc-neutral-200: #e2e8f0;
    --pc-neutral-300: #cbd5e1;
    --pc-neutral-400: #94a3b8;
    --pc-neutral-500: #64748b;
    --pc-neutral-600: #475569;
    --pc-neutral-700: #334155;
    --pc-neutral-800: #1e293b;
    --pc-neutral-900: #0f172a;
    --pc-neutral-950: #020617;

    /* Surface & text */
    --pc-bg: var(--pc-neutral-50);
    --pc-bg-subtle: var(--pc-neutral-100);
    --pc-bg-card: var(--pc-neutral-0);
    --pc-border: var(--pc-neutral-200);
    --pc-border-strong: var(--pc-neutral-300);
    --pc-text: var(--pc-neutral-800);
    --pc-text-muted: var(--pc-neutral-500);
    --pc-text-subtle: var(--pc-neutral-400);

    /* Typography */
    --pc-font-sans: 'Be Vietnam Pro', 'Segoe UI', system-ui, -apple-system, sans-serif;
    --pc-text-display: 2rem;
    --pc-text-h1: 1.75rem;
    --pc-text-h2: 1.375rem;
    --pc-text-h3: 1.125rem;
    --pc-text-body: .9375rem;
    --pc-text-sm: .8125rem;
    --pc-text-xs: .6875rem;
    --pc-leading-tight: 1.25;
    --pc-leading-body: 1.6;
    --pc-tracking-wide: .06em;

    /* Spacing — bước 4px */
    --pc-space-1: .25rem;
    --pc-space-2: .5rem;
    --pc-space-3: .75rem;
    --pc-space-4: 1rem;
    --pc-space-5: 1.25rem;
    --pc-space-6: 1.5rem;
    --pc-space-7: 2rem;
    --pc-space-8: 2.5rem;
    --pc-space-9: 3rem;
    --pc-space-10: 4rem;
    --pc-space-11: 5rem;
    --pc-space-12: 6rem;

    /* Radius */
    --pc-radius-sm: 8px;
    --pc-radius-md: 12px;
    --pc-radius-lg: 16px;
    --pc-radius-xl: 22px;
    --pc-radius-pill: 999px;

    /* Shadow */
    --pc-shadow-xs: 0 1px 2px rgba(15, 23, 42, .05);
    --pc-shadow-sm: 0 1px 3px rgba(15, 23, 42, .07), 0 1px 2px rgba(15, 23, 42, .04);
    --pc-shadow-md: 0 6px 16px -4px rgba(15, 23, 42, .10);
    --pc-shadow-lg: 0 16px 40px -8px rgba(15, 23, 42, .16);
    --pc-shadow-overlay: 0 24px 64px -12px rgba(15, 23, 42, .25);

    /* Motion */
    --pc-dur-fast: 120ms;
    --pc-dur-base: 200ms;
    --pc-dur-slow: 320ms;
    --pc-ease: cubic-bezier(.2, 0, 0, 1);

    /* Z-index */
    --pc-z-dropdown: 1000;
    --pc-z-sticky: 1020;
    --pc-z-modal: 1055;
    --pc-z-toast: 1080;

    /* Focus */
    --pc-focus-ring: 0 0 0 3px var(--pc-primary-ring);
    --pc-focus-ring-danger: 0 0 0 3px rgba(220, 38, 38, .20);
}

[data-theme="dark"] {
    --pc-primary-600: #4f7fd0;
    --pc-primary-700: #6b95dd;
    --pc-primary-300: #9db9e6;
    --pc-primary-50: rgba(79, 127, 208, .14);
    --pc-primary-ring: rgba(79, 127, 208, .35);

    --pc-success: #4ade80;
    --pc-success-bg: rgba(34, 197, 94, .12);
    --pc-success-border: rgba(74, 222, 128, .30);
    --pc-success-text: #86efac;
    --pc-warning: #fbbf24;
    --pc-warning-bg: rgba(245, 158, 11, .12);
    --pc-warning-border: rgba(251, 191, 36, .30);
    --pc-warning-text: #fcd34d;
    --pc-danger: #f87171;
    --pc-danger-bg: rgba(239, 68, 68, .12);
    --pc-danger-border: rgba(248, 113, 113, .30);
    --pc-danger-text: #fca5a5;
    --pc-info: #38bdf8;
    --pc-info-bg: rgba(14, 165, 233, .12);
    --pc-info-border: rgba(56, 189, 248, .30);
    --pc-info-text: #7dd3fc;

    --pc-bg: #0b1220;
    --pc-bg-subtle: #0e1627;
    --pc-bg-card: #111b2e;
    --pc-border: #22304a;
    --pc-border-strong: #2e3f5e;
    --pc-text: #e7edf7;
    --pc-text-muted: #9fb0c8;
    --pc-text-subtle: #64778f;

    --pc-shadow-xs: 0 1px 2px rgba(2, 6, 23, .5);
    --pc-shadow-sm: 0 1px 3px rgba(2, 6, 23, .6);
    --pc-shadow-md: 0 6px 16px -4px rgba(2, 6, 23, .55);
    --pc-shadow-lg: 0 16px 40px -8px rgba(2, 6, 23, .6);
    --pc-shadow-overlay: 0 24px 64px -12px rgba(2, 6, 23, .7);
}

/* ---------- 2. Bridge: biến legacy → token (trang cũ hưởng palette mới) ---------- */
:root {
    --primary: var(--pc-primary);
    --primary-light: var(--pc-primary-400);
    --primary-soft: var(--pc-primary-soft);
    --primary-rgb: 43, 83, 150;
    --primary-gradient: linear-gradient(180deg, var(--pc-primary) 0%, var(--pc-primary) 100%);
    --bg-body: var(--pc-bg);
    --bg-surface: var(--pc-bg-card);
    --bg-sidebar: var(--pc-bg-card);
    --bg-subtle: var(--pc-bg-subtle);
    --text-main: var(--pc-text);
    --text-muted: var(--pc-text-muted);
    --border: var(--pc-border);
    --border-light: var(--pc-border);
    --shadow-sm: var(--pc-shadow-xs);
    --shadow-md: var(--pc-shadow-sm);
    --shadow-lg: var(--pc-shadow-md);
    --shadow-lvl1: var(--pc-shadow-xs);
    --shadow-lvl2: var(--pc-shadow-sm);
    --shadow-lvl3: var(--pc-shadow-md);
    --shadow-primary: 0 8px 20px var(--pc-primary-ring);
    --radius-sm: var(--pc-radius-sm);
    --radius-md: var(--pc-radius-md);
    --radius-lg: var(--pc-radius-lg);
    --corner-card: var(--pc-radius-lg);
    --transition: all var(--pc-dur-fast) var(--pc-ease);
}

[data-theme="dark"] {
    --primary-light: var(--pc-primary-300);
    --primary-rgb: 79, 127, 208;
}

/* ---------- 3. Bootstrap overrides + nền ---------- */
:root {
    --bs-primary: var(--pc-primary);
    --bs-primary-rgb: 43, 83, 150;
    --bs-body-bg: var(--pc-bg);
    --bs-body-color: var(--pc-text);
    --bs-border-color: var(--pc-border);
    --bs-link-color: var(--pc-primary);
    --bs-link-hover-color: var(--pc-primary-strong);
    --bs-font-sans-serif: var(--pc-font-sans);
}

[data-theme="dark"] {
    --bs-primary-rgb: 79, 127, 208;
}

body {
    font-family: var(--pc-font-sans);
    font-size: var(--pc-text-body);
    background: var(--pc-bg);
    color: var(--pc-text);
}

a { color: var(--pc-primary); }
a:hover { color: var(--pc-primary-strong); }

.btn-primary { background: var(--pc-primary); border-color: var(--pc-primary); }
.btn-primary:hover, .btn-primary:focus, .btn-primary:active {
    background: var(--pc-primary-strong);
    border-color: var(--pc-primary-strong);
}
.btn-outline-primary { color: var(--pc-primary); border-color: var(--pc-primary); }
.btn-outline-primary:hover { background: var(--pc-primary); border-color: var(--pc-primary); color: #fff; }
.text-primary { color: var(--pc-primary) !important; }
.bg-primary { background-color: var(--pc-primary) !important; }
.form-control:focus, .form-select:focus {
    border-color: var(--pc-primary);
    box-shadow: 0 0 0 .25rem var(--pc-primary-soft);
}
.form-check-input:checked { background-color: var(--pc-primary); border-color: var(--pc-primary); }
.form-check-input:focus { border-color: var(--pc-primary); box-shadow: var(--pc-focus-ring); }

/* ---------- Motion & a11y ---------- */
:focus-visible { outline: none; box-shadow: var(--pc-focus-ring); }

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: .01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .01ms !important;
        scroll-behavior: auto !important;
    }
}
```

- [ ] **Step 4: Nối CSS vào `templates/base.html`**

Tìm đoạn cuối head:

```html
    {% block extra_head %}{% endblock %}
</head>
```

Sửa thành:

```html
    {% block extra_head %}{% endblock %}
    <link rel="stylesheet" href="{{ url_for('static', filename='css/pc06-premium.css') }}?v=1.0.0">
</head>
```

- [ ] **Step 5: Nối CSS vào `templates/base_mobile.html`**

Tìm đoạn cuối head:

```html
    <link rel="stylesheet" href="{{ url_for('static', filename='css/mobile-responsive.css') }}?v=20260428">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/flat-theme.css') }}?v=1.0.0">
</head>
```

Thêm ngay sau dòng `flat-theme.css`:

```html
    <link rel="stylesheet" href="{{ url_for('static', filename='css/pc06-premium.css') }}?v=1.0.0">
</head>
```

- [ ] **Step 6: Chạy test để xác nhận pass**

Run: `python3 run_tests.py`
Expected: toàn bộ suite OK, bao gồm 3 test mới của `DesignSystemContractTests`.

- [ ] **Step 7: Commit**

```bash
git add static/css/pc06-premium.css tests/test_design_system.py templates/base.html templates/base_mobile.html
git commit -m "Giao diện: thêm design tokens premium + bridge legacy, nạp pc06-premium.css vào base templates"
```

---

### Task 2: Components `pc-*` phần 1 — button, form, card, alert, badge

**Files:**
- Modify: `static/css/pc06-premium.css` (thêm section "4. Components")
- Modify: `tests/test_design_system.py` (thêm test component)

**Interfaces:**
- Consumes: token Task 1 (`--pc-*`).
- Produces: `.pc-btn` (+ `-primary/-secondary/-ghost/-danger/-sm/-lg/-loading`), `.pc-form-group`, `.pc-label`, `.pc-input`, `.pc-select`, `.pc-help`, `.pc-error`, `.pc-invalid`, `.pc-card` (+ `-header/-body/-footer`), `.pc-alert` (+ `-success/-warning/-danger/-info`), `.pc-badge` (+ `-primary/-success/-warning/-danger/-info/-neutral`). Task 4–7 dùng các class này.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_design_system.py`, trong class `DesignSystemContractTests`:

```python
    def test_premium_css_defines_components_part1(self):
        css = _read(PREMIUM_CSS)
        for cls in (
            ".pc-btn", ".pc-btn-primary", ".pc-btn-secondary", ".pc-btn-ghost",
            ".pc-btn-danger", ".pc-btn-sm", ".pc-btn-lg", ".pc-btn-loading",
            ".pc-form-group", ".pc-label", ".pc-input", ".pc-select", ".pc-help",
            ".pc-error", ".pc-invalid",
            ".pc-card", ".pc-card-header", ".pc-card-body", ".pc-card-footer",
            ".pc-alert", ".pc-alert-success", ".pc-alert-warning",
            ".pc-alert-danger", ".pc-alert-info",
            ".pc-badge", ".pc-badge-primary", ".pc-badge-neutral",
        ):
            self.assertIn(cls, css, f"Thiếu component {cls} trong pc06-premium.css")
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python3 run_tests.py`
Expected: FAIL tại `test_premium_css_defines_components_part1` (thiếu `.pc-btn`).

- [ ] **Step 3: Thêm section components phần 1 vào `pc06-premium.css`**

Append sau section Motion & a11y:

```css
/* ---------- 4. Components ---------- */

/* Buttons */
.pc-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: .5rem;
    font-family: inherit;
    font-weight: 600;
    font-size: var(--pc-text-body);
    line-height: 1.2;
    letter-spacing: .01em;
    padding: .7rem 1.25rem;
    border-radius: var(--pc-radius-md);
    border: 1px solid transparent;
    cursor: pointer;
    text-decoration: none;
    white-space: nowrap;
    transition: background-color var(--pc-dur-fast) var(--pc-ease),
                border-color var(--pc-dur-fast) var(--pc-ease),
                color var(--pc-dur-fast) var(--pc-ease),
                box-shadow var(--pc-dur-fast) var(--pc-ease),
                transform var(--pc-dur-fast) var(--pc-ease);
}
.pc-btn:hover { text-decoration: none; }
.pc-btn:active { transform: translateY(1px); }
.pc-btn:focus-visible { box-shadow: var(--pc-focus-ring); }
.pc-btn:disabled, .pc-btn.disabled { opacity: .55; pointer-events: none; }

.pc-btn-primary { background: var(--pc-primary); color: #fff; }
.pc-btn-primary:hover { background: var(--pc-primary-strong); color: #fff; box-shadow: var(--pc-shadow-sm); }

.pc-btn-secondary { background: var(--pc-bg-card); color: var(--pc-text); border-color: var(--pc-border-strong); }
.pc-btn-secondary:hover { background: var(--pc-bg-subtle); border-color: var(--pc-primary); color: var(--pc-primary); }

.pc-btn-ghost { background: transparent; color: var(--pc-text-muted); }
.pc-btn-ghost:hover { background: var(--pc-bg-subtle); color: var(--pc-text); }

.pc-btn-danger { background: var(--pc-danger); color: #fff; }
.pc-btn-danger:hover { background: var(--pc-danger-text); color: #fff; box-shadow: var(--pc-shadow-sm); }

.pc-btn-sm { padding: .45rem .875rem; font-size: var(--pc-text-sm); border-radius: var(--pc-radius-sm); }
.pc-btn-lg { padding: .9rem 1.5rem; font-size: var(--pc-text-h3); border-radius: var(--pc-radius-lg); }
.pc-btn-loading { pointer-events: none; opacity: .75; }

/* Forms */
.pc-form-group { margin-bottom: var(--pc-space-5); }
.pc-label {
    display: block;
    font-size: var(--pc-text-xs);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: var(--pc-tracking-wide);
    color: var(--pc-text-muted);
    margin-bottom: .5rem;
}
.pc-input, .pc-select {
    display: block;
    width: 100%;
    background: var(--pc-bg-subtle);
    color: var(--pc-text);
    border: 1px solid var(--pc-border);
    border-radius: var(--pc-radius-md);
    padding: .65rem .875rem;
    font-size: var(--pc-text-body);
    font-family: inherit;
    transition: border-color var(--pc-dur-fast) var(--pc-ease),
                box-shadow var(--pc-dur-fast) var(--pc-ease),
                background-color var(--pc-dur-fast) var(--pc-ease);
}
.pc-input::placeholder { color: var(--pc-text-subtle); }
.pc-input:focus, .pc-select:focus {
    outline: none;
    background: var(--pc-bg-card);
    border-color: var(--pc-primary);
    box-shadow: var(--pc-focus-ring);
}
.pc-input:disabled, .pc-select:disabled { opacity: .6; cursor: not-allowed; }
.pc-input[readonly] { background: var(--pc-bg-subtle); }
.pc-invalid, .pc-input.pc-invalid { border-color: var(--pc-danger); }
.pc-input.pc-invalid:focus { box-shadow: var(--pc-focus-ring-danger); }
.pc-help { font-size: var(--pc-text-sm); color: var(--pc-text-muted); margin-top: .375rem; }
.pc-error {
    display: flex;
    align-items: center;
    gap: .375rem;
    font-size: var(--pc-text-sm);
    color: var(--pc-danger);
    margin-top: .375rem;
}

/* Cards */
.pc-card {
    background: var(--pc-bg-card);
    border: 1px solid var(--pc-border);
    border-radius: var(--pc-radius-lg);
    box-shadow: var(--pc-shadow-xs);
}
.pc-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--pc-space-3);
    padding: var(--pc-space-4) var(--pc-space-5);
    border-bottom: 1px solid var(--pc-border);
}
.pc-card-body { padding: var(--pc-space-5); }
.pc-card-footer {
    padding: var(--pc-space-4) var(--pc-space-5);
    border-top: 1px solid var(--pc-border);
}

/* Alerts */
.pc-alert {
    display: flex;
    align-items: flex-start;
    gap: .75rem;
    padding: .875rem 1rem;
    border: 1px solid transparent;
    border-radius: var(--pc-radius-md);
    font-size: var(--pc-text-sm);
    font-weight: 500;
}
.pc-alert-success { background: var(--pc-success-bg); border-color: var(--pc-success-border); color: var(--pc-success-text); }
.pc-alert-warning { background: var(--pc-warning-bg); border-color: var(--pc-warning-border); color: var(--pc-warning-text); }
.pc-alert-danger { background: var(--pc-danger-bg); border-color: var(--pc-danger-border); color: var(--pc-danger-text); }
.pc-alert-info { background: var(--pc-info-bg); border-color: var(--pc-info-border); color: var(--pc-info-text); }

/* Badges */
.pc-badge {
    display: inline-flex;
    align-items: center;
    gap: .375rem;
    padding: .25rem .625rem;
    border-radius: var(--pc-radius-pill);
    border: 1px solid transparent;
    font-size: var(--pc-text-xs);
    font-weight: 700;
    letter-spacing: .02em;
    line-height: 1.2;
}
.pc-badge-primary { background: var(--pc-primary-soft); color: var(--pc-primary); }
.pc-badge-success { background: var(--pc-success-bg); color: var(--pc-success-text); border-color: var(--pc-success-border); }
.pc-badge-warning { background: var(--pc-warning-bg); color: var(--pc-warning-text); border-color: var(--pc-warning-border); }
.pc-badge-danger { background: var(--pc-danger-bg); color: var(--pc-danger-text); border-color: var(--pc-danger-border); }
.pc-badge-info { background: var(--pc-info-bg); color: var(--pc-info-text); border-color: var(--pc-info-border); }
.pc-badge-neutral { background: var(--pc-bg-subtle); color: var(--pc-text-muted); border-color: var(--pc-border); }
```

- [ ] **Step 4: Chạy toàn bộ test**

Run: `python3 run_tests.py`
Expected: toàn bộ suite OK, `test_premium_css_defines_components_part1` PASS.

- [ ] **Step 5: Commit**

```bash
git add static/css/pc06-premium.css tests/test_design_system.py
git commit -m "Giao diện: component pc-* phần 1 (button, form, card, alert, badge)"
```

---

### Task 3: Components `pc-*` phần 2 — table, modal, nav, page-header, empty, pagination + login helpers

**Files:**
- Modify: `static/css/pc06-premium.css`

**Interfaces:**
- Consumes: token Task 1.
- Produces: `.pc-table`/`.pc-table-hover`, override Bootstrap modal (`.modal-content` + `.pc-modal`), `.pc-nav-item`/`.pc-topbar`/`.pc-sidebar`/`.pc-nav-section`, `.pc-page-header`/`.pc-page-title`/`.pc-page-actions`, `.pc-empty`/`.pc-empty-icon`/`.pc-empty-title`, `.pc-pagination`, `.pc-login-divider`/`.pc-login-google`. Ghi chú: spec §5 gọi tên `.pc-modal` — implement bằng override `.modal-content` toàn cục kèm selector `.pc-modal` để dùng như class trực tiếp trên modal-content.

- [ ] **Step 1: Viết test thất bại cho phần 2**

Thêm vào `tests/test_design_system.py`, trong class `DesignSystemContractTests`:

```python
    def test_premium_css_defines_components_part2(self):
        css = _read(PREMIUM_CSS)
        for cls in (
            ".pc-table", ".pc-table-hover",
            ".pc-nav-item", ".pc-topbar", ".pc-sidebar", ".pc-nav-section",
            ".pc-modal", ".pc-page-header", ".pc-page-title", ".pc-page-actions",
            ".pc-empty", ".pc-empty-icon", ".pc-empty-title",
            ".pc-pagination",
            ".pc-login-divider", ".pc-login-google",
        ):
            self.assertIn(cls, css, f"Thiếu component {cls} trong pc06-premium.css")
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python3 run_tests.py`
Expected: FAIL tại `test_premium_css_defines_components_part2`.

- [ ] **Step 3: Append section phần 2 vào `pc06-premium.css`**

```css
/* Tables */
.pc-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: var(--pc-text-body);
    color: var(--pc-text);
}
.pc-table thead th {
    font-size: var(--pc-text-xs);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: var(--pc-tracking-wide);
    color: var(--pc-text-muted);
    background: var(--pc-bg-subtle);
    text-align: left;
    white-space: nowrap;
    padding: .625rem .875rem;
    border-bottom: 1px solid var(--pc-border);
}
.pc-table tbody td {
    padding: .75rem .875rem;
    border-bottom: 1px solid var(--pc-border);
    vertical-align: middle;
}
.pc-table tbody tr:last-child td { border-bottom: 0; }
.pc-table-hover tbody tr { transition: background-color var(--pc-dur-fast) var(--pc-ease); }
.pc-table-hover tbody tr:hover { background: var(--pc-bg-subtle); }

/* Modal — override Bootstrap (dùng class .pc-modal trực tiếp cũng được) */
.modal-content, .pc-modal {
    background: var(--pc-bg-card);
    color: var(--pc-text);
    border: 1px solid var(--pc-border);
    border-radius: var(--pc-radius-xl);
    box-shadow: var(--pc-shadow-overlay);
}
.modal-header { border-bottom: 1px solid var(--pc-border); padding: var(--pc-space-5) var(--pc-space-6); }
.modal-title { font-weight: 700; font-size: var(--pc-text-h3); color: var(--pc-text); }
.modal-body { padding: var(--pc-space-6); color: var(--pc-text); }
.modal-footer { border-top: 1px solid var(--pc-border); padding: var(--pc-space-4) var(--pc-space-6); }

/* Nav */
.pc-topbar {
    background: var(--pc-bg-card);
    border-bottom: 1px solid var(--pc-border);
    box-shadow: var(--pc-shadow-xs);
}
.pc-sidebar {
    background: var(--pc-bg-card);
    border-right: 1px solid var(--pc-border);
}
.pc-nav-section {
    font-size: var(--pc-text-xs);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: var(--pc-tracking-wide);
    color: var(--pc-text-subtle);
    padding: var(--pc-space-3) var(--pc-space-3) var(--pc-space-1);
}
.pc-nav-item {
    display: inline-flex;
    align-items: center;
    gap: .5rem;
    padding: .5rem .875rem;
    border-radius: var(--pc-radius-pill);
    color: var(--pc-text-muted);
    font-weight: 600;
    font-size: var(--pc-text-sm);
    text-decoration: none;
    transition: background-color var(--pc-dur-fast) var(--pc-ease),
                color var(--pc-dur-fast) var(--pc-ease);
}
.pc-nav-item:hover { background: var(--pc-primary-soft); color: var(--pc-primary); }
.pc-nav-item.active { background: var(--pc-primary); color: #fff; box-shadow: var(--pc-shadow-sm); }

/* Page header */
.pc-page-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--pc-space-4);
    margin-bottom: var(--pc-space-6);
}
.pc-page-title {
    margin: 0;
    font-size: var(--pc-text-h1);
    font-weight: 800;
    letter-spacing: -.02em;
    color: var(--pc-text);
}
.pc-page-actions { display: flex; align-items: center; gap: .625rem; }

/* Empty state */
.pc-empty { text-align: center; padding: var(--pc-space-9) var(--pc-space-6); color: var(--pc-text-muted); }
.pc-empty-icon { font-size: 2rem; color: var(--pc-text-subtle); margin-bottom: var(--pc-space-3); }
.pc-empty-title { font-weight: 700; color: var(--pc-text); margin-bottom: .25rem; }

/* Pagination */
.pc-pagination { display: inline-flex; gap: .25rem; }
.pc-pagination .page-link {
    min-width: 2.25rem;
    text-align: center;
    padding: .45rem .625rem;
    border: 1px solid var(--pc-border);
    border-radius: var(--pc-radius-sm);
    background: var(--pc-bg-card);
    color: var(--pc-text-muted);
    font-size: var(--pc-text-sm);
    font-weight: 600;
    transition: background-color var(--pc-dur-fast) var(--pc-ease),
                border-color var(--pc-dur-fast) var(--pc-ease),
                color var(--pc-dur-fast) var(--pc-ease);
}
.pc-pagination .page-link:hover { border-color: var(--pc-primary); color: var(--pc-primary); background: var(--pc-primary-soft); }
.pc-pagination .page-item.active .page-link {
    background: var(--pc-primary);
    border-color: var(--pc-primary);
    color: #fff;
    box-shadow: var(--pc-shadow-sm);
}
.pc-pagination .page-item.disabled .page-link { opacity: .5; background: var(--pc-bg-subtle); }

/* Login helpers (pilot) */
.pc-login-divider {
    display: flex;
    align-items: center;
    gap: var(--pc-space-3);
    margin: var(--pc-space-6) 0;
    color: var(--pc-text-subtle);
    font-size: var(--pc-text-xs);
    font-weight: 700;
    letter-spacing: var(--pc-tracking-wide);
}
.pc-login-divider::before, .pc-login-divider::after { content: ""; flex: 1; height: 1px; background: var(--pc-border); }
.pc-login-google {
    width: 100%;
    background: var(--pc-bg-card);
    border-color: var(--pc-border-strong);
    color: var(--pc-text);
}
.pc-login-google:hover { border-color: var(--pc-primary); background: var(--pc-bg-subtle); color: var(--pc-text); box-shadow: var(--pc-shadow-xs); }
```

- [ ] **Step 4: Chạy toàn bộ test**

Run: `python3 run_tests.py`
Expected: toàn bộ suite OK, `test_premium_css_defines_components_part2` PASS.

- [ ] **Step 5: Commit**

```bash
git add static/css/pc06-premium.css tests/test_design_system.py
git commit -m "Giao diện: hoàn tất thư viện component pc-* (table, modal, nav, page-header, empty, pagination)"
```

---

### Task 4: Premium hóa app shell bằng CSS trên class hiện có

**Files:**
- Modify: `static/css/pc06-premium.css` (thêm section "5. App shell")
- Modify: `tests/test_design_system.py` (thêm test shell)

**Interfaces:**
- Consumes: token Task 1.
- Produces: shell token hóa — KHÔNG đổi DOM `base.html`/`base_mobile.html`, mọi id/JS giữ nguyên. Các class hiện có được restyle: `.desktop-sidebar`, `.desktop-brand-badge`, `.sidebar-nav-link`, `.nav-link-top`, `.mobile-header`, `.mobile-bottom-nav`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_design_system.py`, class `DesignSystemContractTests`:

```python
    def test_premium_css_restyles_app_shell(self):
        css = _read(PREMIUM_CSS)
        for selector in (
            ".desktop-sidebar", ".desktop-brand-badge", ".sidebar-nav-link",
            ".nav-link-top", ".mobile-header", ".mobile-bottom-nav",
        ):
            self.assertIn(selector, css, f"Thiếu shell selector {selector}")
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python3 run_tests.py`
Expected: FAIL tại `test_premium_css_restyles_app_shell`.

- [ ] **Step 3: Append section shell vào `pc06-premium.css`**

```css
/* ---------- 5. App shell — token hóa class hiện có, KHÔNG đổi DOM ---------- */
.desktop-sidebar {
    background: var(--pc-bg-card);
    border-right: 1px solid var(--pc-border);
}
.desktop-brand-badge {
    background: var(--pc-primary);
    color: #fff;
    border-radius: var(--pc-radius-md);
    box-shadow: var(--pc-shadow-sm);
}
.sidebar-nav-link {
    color: var(--pc-text-muted);
    border-radius: var(--pc-radius-md);
    transition: background-color var(--pc-dur-fast) var(--pc-ease),
                color var(--pc-dur-fast) var(--pc-ease);
}
.sidebar-nav-link:hover { background: var(--pc-primary-soft); color: var(--pc-primary); }
.sidebar-nav-link.active { background: var(--pc-primary); color: #fff; box-shadow: var(--pc-shadow-sm); }

.nav-link-top {
    border-radius: var(--pc-radius-pill);
    color: var(--pc-text-muted);
    font-weight: 600;
    transition: background-color var(--pc-dur-fast) var(--pc-ease),
                color var(--pc-dur-fast) var(--pc-ease);
}
.nav-link-top:hover { background: var(--pc-primary-soft); color: var(--pc-primary); }
.nav-link-top.active { background: var(--pc-primary); color: #fff; box-shadow: var(--pc-shadow-sm); }

.mobile-header {
    background: var(--pc-bg-card);
    border-bottom: 1px solid var(--pc-border);
    box-shadow: var(--pc-shadow-xs);
}
.mobile-bottom-nav {
    background: var(--pc-bg-card);
    border-top: 1px solid var(--pc-border);
    box-shadow: 0 -2px 10px rgba(2, 6, 23, .06);
}
.mobile-bottom-nav .nav-item { color: var(--pc-text-muted); }
.mobile-bottom-nav .nav-item.active { color: var(--pc-primary); }
```

- [ ] **Step 4: Chạy toàn bộ test**

Run: `python3 run_tests.py`
Expected: toàn bộ suite OK.

- [ ] **Step 5: Kiểm tra trực quan nhanh (không bắt buộc đăng nhập)**

Chạy `./START_SERVER_MAC.sh` (hoặc `python3 app.py`), mở `http://localhost:5000/login` bằng browser-use, chụp screenshot; xác nhận không lỗi console CSS (404 asset). Tắt server sau khi kiểm tra.

- [ ] **Step 6: Commit**

```bash
git add static/css/pc06-premium.css tests/test_design_system.py
git commit -m "Giao diện: premium hóa app shell (sidebar, top nav, mobile header/bottom nav) bằng token"
```

---

### Task 5: Pilot login desktop — viết lại `login.html` trên hệ `pc-*`

**Files:**
- Modify: `templates/login.html` (thay toàn bộ nội dung)
- Modify: `tests/test_design_system.py` (thêm `LoginPilotTests`)

**Interfaces:**
- Consumes: component Task 2–3, token Task 1.
- Produces: trang login desktop premium; **contract chức năng bất biến**: `form method="POST"`, input `name="username"`/`name="password"` (`id="password_field"`), hidden `csrf_token`, JS tiêm CSRF, `togglePasswordVisibility`, `id="eye_icon"`, link `/auth/google` (điều kiện config), modal `id="forgotModal"` với `data-bs-toggle`/`data-bs-dismiss` nguyên vẹn, xử lý `clear_storage`, Enter-submit.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_design_system.py`:

```python
class LoginPilotTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_login_desktop_uses_design_system_and_keeps_contract(self):
        res = self.client.get("/login")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("pc06-premium.css", body)
        self.assertIn("pc-login", body)
        self.assertIn('name="username"', body)
        self.assertIn('name="password"', body)
        self.assertIn('id="password_field"', body)
        self.assertIn('id="forgotModal"', body)
        self.assertIn("togglePasswordVisibility", body)
        self.assertIn("csrf_token", body)

    def test_login_mobile_keeps_contract(self):
        res = self.client.get("/login", headers={"User-Agent": MOBILE_UA})
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("pc06-premium.css", body)
        self.assertIn("pc-login", body)
        self.assertIn('name="username"', body)
        self.assertIn('name="password"', body)
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python3 run_tests.py`
Expected: FAIL tại `test_login_desktop_uses_design_system_and_keeps_contract` (chưa có `pc-login`/`pc06-premium.css` trong login.html).

- [ ] **Step 3: Thay toàn bộ nội dung `templates/login.html`**

```html
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="csrf-token" content="{{ csrf_token_value }}">
    <title>Đăng nhập – HỆ THỐNG PC06</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/pc06-premium.css') }}?v=1.0.0">
    <style>
        .pc-login-bg {
            position: fixed;
            inset: 0;
            z-index: 0;
            background: url('/static/img/cand_logo_bg.jpg') center/cover no-repeat;
        }
        .pc-login-bg::after {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(18, 31, 56, .84) 0%, rgba(43, 83, 150, .60) 100%);
        }
        .pc-login-shell {
            position: relative;
            z-index: 1;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: var(--pc-space-6);
        }
        .pc-login-card { width: 100%; max-width: 460px; padding: 44px 40px; }
        .pc-login-logo {
            width: 72px;
            height: 72px;
            margin: 0 auto var(--pc-space-6);
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: var(--pc-radius-lg);
            background: var(--pc-primary);
            color: #fff;
            font-size: 30px;
            box-shadow: var(--pc-shadow-md);
        }
        .pc-login-title {
            font-size: var(--pc-text-h1);
            font-weight: 800;
            letter-spacing: -.02em;
            text-align: center;
            color: var(--pc-text);
            margin-bottom: 6px;
        }
        .pc-login-subtitle {
            font-size: var(--pc-text-body);
            color: var(--pc-text-muted);
            text-align: center;
            margin-bottom: var(--pc-space-8);
        }
        .pc-input-suffix {
            border-top-left-radius: 0;
            border-bottom-left-radius: 0;
            border-left: 0;
        }
        @media (max-width: 575px) {
            .pc-login-card { padding: 32px 24px; }
        }
    </style>
</head>
<body>
    <div class="pc-login-bg" aria-hidden="true"></div>
    <div class="pc-login-shell">
        <div class="pc-card pc-login-card pc-login">
            <div class="pc-login-logo"><i class="fa-solid fa-shield-halved"></i></div>
            <h1 class="pc-login-title">HỆ THỐNG PC06</h1>
            <p class="pc-login-subtitle">Đăng nhập để tiếp tục làm việc</p>

            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="pc-alert {{ 'pc-alert-danger' if category == 'error' else 'pc-alert-' ~ category }} mb-3">
                      <i class="fa-solid fa-circle-exclamation mt-1"></i>
                      <div>{{ message }}</div>
                  </div>
                {% endfor %}
              {% endif %}
            {% endwith %}

            <form method="POST">
                <input type="hidden" name="csrf_token" value="{{ csrf_token_value }}">
                <div class="pc-form-group">
                    <label class="pc-label" for="username_field">Tên tài khoản</label>
                    <input type="text" id="username_field" name="username" class="pc-input" placeholder="Nhập tên đăng nhập..." required autocomplete="username">
                </div>

                <div class="pc-form-group">
                    <label class="pc-label d-flex justify-content-between align-items-center" for="password_field">
                        Mật khẩu
                        <a href="#" data-bs-toggle="modal" data-bs-target="#forgotModal" style="text-transform:none; letter-spacing:0;">Quên mật khẩu?</a>
                    </label>
                    <div class="d-flex">
                        <input type="password" name="password" id="password_field" class="pc-input" placeholder="Nhập mật khẩu..." required autocomplete="current-password" style="border-top-right-radius: 0; border-bottom-right-radius: 0;">
                        <button class="pc-btn pc-btn-secondary pc-input-suffix" type="button" onclick="togglePasswordVisibility()" aria-label="Hiện hoặc ẩn mật khẩu">
                            <i class="fa-regular fa-eye-slash" id="eye_icon"></i>
                        </button>
                    </div>
                </div>

                <button type="submit" class="pc-btn pc-btn-primary w-100">
                    ĐĂNG NHẬP HỆ THỐNG <i class="fa-solid fa-arrow-right ms-2"></i>
                </button>
            </form>

            {% if config.get('GOOGLE_OAUTH_CLIENT_ID') and config.get('GOOGLE_OAUTH_CLIENT_SECRET') %}
            <div class="pc-login-divider">HOẶC</div>
            <a href="/auth/google" class="pc-btn pc-login-google">
                <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
                    <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.7-.4-3.9z"/>
                    <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
                    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
                    <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.7l6.2 5.2C36.9 41.4 44 36 44 24c0-1.3-.1-2.7-.4-3.9z"/>
                </svg>
                Đăng nhập bằng Google
            </a>
            {% endif %}
        </div>
    </div>

    <!-- Forgot Password Modal -->
    <div class="modal fade" id="forgotModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content pc-modal">
                <div class="modal-header">
                    <h5 class="modal-title">Khôi phục mật khẩu</h5>
                    <button type="button" class="btn-close" data-bs-toggle="modal"></button>
                </div>
                <div class="modal-body text-center py-4">
                    <div class="d-inline-flex align-items-center justify-content-center rounded-circle mb-3"
                         style="width:72px; height:72px; background:var(--pc-primary-soft); color:var(--pc-primary);">
                        <i class="fa-solid fa-shield-halved fs-2"></i>
                    </div>
                    <p class="mb-0 px-3 fw-medium">Để bảo mật hệ thống, vui lòng liên hệ <strong>Quản trị viên</strong> hoặc <strong>Đội Tham mưu</strong> để được cấp lại mật khẩu mới.</p>
                </div>
                <div class="modal-footer justify-content-center">
                    <button type="button" class="pc-btn pc-btn-primary" data-bs-dismiss="modal">ĐÃ HIỂU</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        (function () {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
            document.querySelectorAll('form').forEach((form) => {
                let input = form.querySelector('input[name="csrf_token"]');
                if (!input) {
                    input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = 'csrf_token';
                    form.appendChild(input);
                }
                input.value = csrfToken;
            });
        })();

        // Security: Clear activity tracker if logged out
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('clear_storage') === 'true') {
            localStorage.removeItem('pc06_last_activity');
            Object.keys(localStorage).forEach((key) => {
                if (key.startsWith('pc06_last_activity:')) {
                    localStorage.removeItem(key);
                }
            });
        }

        function togglePasswordVisibility() {
            const pw = document.getElementById('password_field');
            const icon = document.getElementById('eye_icon');
            if (pw.type === 'password') {
                pw.type = 'text';
                icon.classList.remove('fa-eye');
                icon.classList.add('fa-eye-slash');
            } else {
                pw.type = 'password';
                icon.classList.remove('fa-eye-slash');
                icon.classList.add('fa-eye');
            }
        }

        // Enter key to login
        document.querySelectorAll('input').forEach(input => {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    document.querySelector('form').submit();
                }
            });
        });
    </script>
</body>
</html>
```

Lưu ý: giữ nguyên attribute `data-bs-toggle="modal"` (không có `data-bs-dismiss`) trên nút `.btn-close` của modal giống bản cũ — không tự "sửa" hành vi.

- [ ] **Step 4: Chạy test**

Run: `python3 run_tests.py`
Expected: `test_login_desktop_uses_design_system_and_keeps_contract` PASS; `test_login_mobile_keeps_contract` vẫn FAIL (chờ Task 6).

- [ ] **Step 5: Kiểm tra trực quan**

Chạy server, browser-use mở `http://localhost:5000/login` viewport desktop: nhập thử (form hợp lệ), bấm nút hiện/ẩn mật khẩu, mở modal "Quên mật khẩu" rồi đóng bằng nút ĐÃ HIỂU, kiểm tra không lỗi console. Không cần đăng nhập thật.

- [ ] **Step 6: Commit**

```bash
git add templates/login.html tests/test_design_system.py
git commit -m "Giao diện: pilot login desktop theo design system premium, giữ nguyên contract chức năng"
```

---

### Task 6: Pilot login mobile — viết lại `login_mobile.html`

**Files:**
- Modify: `templates/login_mobile.html` (thay toàn bộ nội dung)

**Interfaces:**
- Consumes: token + component trong `pc06-premium.css` (đã nạp qua `base_mobile.html` từ Task 1), helper `.pc-login-divider`/`.pc-login-google` Task 3.
- Produces: login mobile premium; giữ extends `base_mobile.html`, giữ block `title`/`head`/`content`, giữ `name="username"`/`name="password"`, hidden csrf, link `/auth/google` điều kiện config.

- [ ] **Step 1: Thay toàn bộ nội dung `templates/login_mobile.html`**

```html
{% extends "base_mobile.html" %}

{% block title %}Đăng nhập PC06 Mobile{% endblock %}

{% block head %}
<style>
    body { background: var(--pc-bg); }
    .main-content { padding-top: 0; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
    .pc-login-mobile { width: 100%; max-width: 420px; padding: var(--pc-space-6) var(--pc-space-5); text-align: center; }
    .pc-login-mobile .pc-login-logo {
        width: 80px;
        height: 80px;
        margin: 0 auto var(--pc-space-5);
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: var(--pc-radius-lg);
        background: var(--pc-primary);
        color: #fff;
        font-size: 32px;
        box-shadow: var(--pc-shadow-md);
    }
    .pc-login-mobile .pc-login-title {
        font-size: 24px;
        font-weight: 800;
        letter-spacing: -.02em;
        color: var(--pc-text);
        margin-bottom: 6px;
    }
    .pc-login-mobile .pc-login-subtitle {
        font-size: var(--pc-text-body);
        color: var(--pc-text-muted);
        margin-bottom: var(--pc-space-8);
    }
</style>
{% endblock %}

{% block content %}
<div class="pc-login-mobile pc-login">
    <div class="pc-login-logo"><i class="fa-solid fa-shield-halved"></i></div>
    <h1 class="pc-login-title">PC06 TỔNG HỢP</h1>
    <p class="pc-login-subtitle">Chào mừng bạn quay trở lại hệ thống</p>

    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token_value }}">
        <div class="pc-form-group text-start">
            <label class="pc-label" for="uInput"><i class="fa-solid fa-user me-2"></i>Tên đăng nhập</label>
            <input type="text" name="username" class="pc-input" id="uInput" placeholder="Tên đăng nhập" required autofocus autocomplete="username">
        </div>

        <div class="pc-form-group text-start">
            <label class="pc-label" for="pInput"><i class="fa-solid fa-lock me-2"></i>Mật khẩu</label>
            <input type="password" name="password" class="pc-input" id="pInput" placeholder="Mật khẩu" required autocomplete="current-password">
        </div>

        <button type="submit" class="pc-btn pc-btn-primary w-100 mt-2" aria-label="Đăng nhập">
            <i class="fa-solid fa-right-to-bracket me-2"></i>ĐĂNG NHẬP
        </button>
    </form>

    {% if config.get('GOOGLE_OAUTH_CLIENT_ID') and config.get('GOOGLE_OAUTH_CLIENT_SECRET') %}
    <div class="pc-login-divider">HOẶC</div>
    <a href="/auth/google" class="pc-btn pc-login-google">
        <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.7-.4-3.9z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.7l6.2 5.2C36.9 41.4 44 36 44 24c0-1.3-.1-2.7-.4-3.9z"/>
        </svg>
        Đăng nhập bằng Google
    </a>
    {% endif %}

    <p class="mt-5 mb-0" style="font-size: var(--pc-text-xs); color: var(--pc-text-muted);">&copy; 2026 PC06. Đã tối ưu cho thiết bị di động.</p>
</div>
{% endblock %}
```

- [ ] **Step 2: Chạy toàn bộ test**

Run: `python3 run_tests.py`
Expected: toàn bộ suite OK (kể cả `test_login_mobile_keeps_contract`).

- [ ] **Step 3: Kiểm tra trực quan mobile**

browser-use mở `http://localhost:5000/login` với mobile viewport (hoặc UA mobile): giao diện card, nhập liệu, nút bấm hoạt động; không lỗi console.

- [ ] **Step 4: Commit**

```bash
git add templates/login_mobile.html
git commit -m "Giao diện: pilot login mobile theo design system premium"
```

---

### Task 7: Style guide — route admin + template (TDD đầy đủ)

**Files:**
- Create: `templates/styleguide.html`
- Modify: `routes/admin.py:791` (thêm route sau `category_admin`)
- Modify: `tests/test_design_system.py` (thêm `StyleguideAccessTests`)

**Interfaces:**
- Consumes: component Task 2–3; guard chuẩn của repo `can_module('sys', 'view')` (pattern giống `db_tool`/`category_admin`); `render_template` trong `routes/admin.py` là `render_auto_template` (tự fallback desktop khi không có `styleguide_mobile.html` — KHÔNG cần tạo bản mobile).
- Produces: `GET /admin/styleguide` — 302 về login nếu chưa đăng nhập hoặc không có quyền `sys.view`; 200 với admin, hiển thị tokens + toàn bộ component ở 2 theme.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_design_system.py` (thêm `import uuid` trên đầu file):

```python
class StyleguideAccessTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []

    def tearDown(self):
        with app.app_context():
            for uid in self.created_user_ids:
                User.query.filter_by(id=uid).delete()
            db.session.commit()

    def _admin(self):
        with app.app_context():
            return (
                User.query.filter_by(username="admin").first()
                or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            )

    def _create_plain_user(self):
        with app.app_context():
            user = User(
                username=f"sg_{uuid.uuid4().hex[:8]}",
                fullname="Styleguide Test",
                unit_area="",
                unit_key="",
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.created_user_ids.append(user.id)
            return user.id

    def _login(self, user_id, is_admin):
        with app.app_context():
            user = db.session.get(User, user_id)
            with self.client.session_transaction() as sess:
                sess["uid"] = user.id
                sess["username"] = user.username
                sess["fullname"] = user.fullname
                sess["unit"] = user.unit_area or ""
                sess["unit_area"] = user.unit_area or ""
                sess["unit_area_ref"] = user.unit_area or ""
                sess["unit_key"] = user.unit_key or ""
                sess["role_id"] = user.role_id
                sess["must_change"] = False
                sess["is_admin"] = is_admin
                sess["session_version"] = int(user.session_version or 0)
                sess["csrf_token"] = "sg-test-csrf"
                sess["last_active"] = datetime.now().timestamp()
                sess["login_nonce"] = "sg-test"

    def test_styleguide_requires_login(self):
        res = self.client.get("/admin/styleguide")
        self.assertEqual(res.status_code, 302)

    def test_styleguide_denies_non_admin(self):
        uid = self._create_plain_user()
        self._login(uid, is_admin=False)
        res = self.client.get("/admin/styleguide")
        self.assertEqual(res.status_code, 302)

    def test_styleguide_renders_for_admin(self):
        admin = self._admin()
        self._login(admin.id, is_admin=True)
        res = self.client.get("/admin/styleguide")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        for marker in ("pc-btn", "pc-card", "pc-table", "pc-badge", "--pc-primary"):
            self.assertIn(marker, body)
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python3 run_tests.py`
Expected: FAIL — `test_styleguide_requires_login` nhận 404 thay vì 302 (route chưa tồn tại).

- [ ] **Step 3: Thêm route vào `routes/admin.py`**

Ngay sau hàm `category_admin` (khoảng dòng 791), thêm:

```python
@admin_bp.route('/admin/styleguide')
def styleguide():
    """Style guide nội bộ của design system premium (chỉ admin/sys.view)."""
    from permissions import can_module
    if not can_module('sys', 'view'): return redirect(url_for('auth_bp.login'))
    return render_template('styleguide.html', title='Style Guide – PC06 Design System')
```

- [ ] **Step 4: Tạo `templates/styleguide.html`**

```html
{% extends "base.html" %}

{% block content %}
<div class="container-fluid py-4 px-3 px-lg-4">
    <div class="pc-page-header">
        <div>
            <h1 class="pc-page-title">PC06 Design System</h1>
            <p class="mb-0" style="color: var(--pc-text-muted);">
                Subproject 1 — tokens <code>--pc-*</code>, component <code>pc-*</code>, light/dark.
                Chuyển theme bằng nút trên thanh công cụ để kiểm tra cả hai chế độ.
            </p>
        </div>
        <div class="pc-page-actions">
            <span class="pc-badge pc-badge-primary">v1.0.0</span>
        </div>
    </div>

    <!-- Tokens: bảng màu -->
    <div class="pc-card mb-4">
        <div class="pc-card-header"><h2 class="h5 mb-0">Color tokens</h2></div>
        <div class="pc-card-body">
            <div class="row g-3">
                {% for name in ['--pc-primary', '--pc-primary-strong', '--pc-success', '--pc-warning', '--pc-danger', '--pc-info'] %}
                <div class="col-6 col-md-4 col-lg-2">
                    <div style="height:64px; border-radius:var(--pc-radius-md); border:1px solid var(--pc-border); background: var({{ name }});"></div>
                    <code class="small">{{ name }}</code>
                </div>
                {% endfor %}
                {% for name in ['--pc-bg', '--pc-bg-subtle', '--pc-bg-card', '--pc-border', '--pc-text', '--pc-text-muted'] %}
                <div class="col-6 col-md-4 col-lg-2">
                    <div style="height:64px; border-radius:var(--pc-radius-md); border:1px solid var(--pc-border); background: var({{ name }});"></div>
                    <code class="small">{{ name }}</code>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <!-- Typography -->
    <div class="pc-card mb-4">
        <div class="pc-card-header"><h2 class="h5 mb-0">Typography — Be Vietnam Pro</h2></div>
        <div class="pc-card-body">
            <p style="font-size:var(--pc-text-display); font-weight:800; margin-bottom:var(--pc-space-2);">Display 32px</p>
            <p style="font-size:var(--pc-text-h1); font-weight:700; margin-bottom:var(--pc-space-2);">Heading 1 — 28px</p>
            <p style="font-size:var(--pc-text-h2); font-weight:700; margin-bottom:var(--pc-space-2);">Heading 2 — 22px</p>
            <p style="font-size:var(--pc-text-h3); font-weight:600; margin-bottom:var(--pc-space-2);">Heading 3 — 18px</p>
            <p style="margin-bottom:var(--pc-space-2);">Body — 15px, dòng chuẩn cho nội dung nghiệp vụ.</p>
            <p style="font-size:var(--pc-text-sm); color:var(--pc-text-muted); margin-bottom:0;">Small — 13px cho chú thích.</p>
        </div>
    </div>

    <!-- Buttons -->
    <div class="pc-card mb-4">
        <div class="pc-card-header"><h2 class="h5 mb-0">Buttons</h2></div>
        <div class="pc-card-body d-flex flex-wrap gap-2 align-items-center">
            <button class="pc-btn pc-btn-primary">Primary</button>
            <button class="pc-btn pc-btn-secondary">Secondary</button>
            <button class="pc-btn pc-btn-ghost">Ghost</button>
            <button class="pc-btn pc-btn-danger">Danger</button>
            <button class="pc-btn pc-btn-primary pc-btn-sm">Small</button>
            <button class="pc-btn pc-btn-primary pc-btn-lg">Large</button>
            <button class="pc-btn pc-btn-primary" disabled>Disabled</button>
            <button class="pc-btn pc-btn-primary pc-btn-loading">Loading…</button>
        </div>
    </div>

    <!-- Forms -->
    <div class="pc-card mb-4">
        <div class="pc-card-header"><h2 class="h5 mb-0">Forms</h2></div>
        <div class="pc-card-body">
            <div class="row g-4">
                <div class="col-md-6">
                    <div class="pc-form-group">
                        <label class="pc-label">Ô nhập chuẩn</label>
                        <input class="pc-input" placeholder="Nhập nội dung...">
                        <div class="pc-help">Văn bản hỗ trợ dưới ô nhập.</div>
                    </div>
                    <div class="pc-form-group">
                        <label class="pc-label">Trạng thái lỗi</label>
                        <input class="pc-input pc-invalid" value="Giá trị sai">
                        <div class="pc-error"><i class="fa-solid fa-circle-exclamation"></i> Dữ liệu không hợp lệ.</div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="pc-form-group">
                        <label class="pc-label">Select</label>
                        <select class="pc-select"><option>Tùy chọn một</option><option>Tùy chọn hai</option></select>
                    </div>
                    <div class="pc-form-group">
                        <label class="pc-label">Disabled</label>
                        <input class="pc-input" disabled value="Không chỉnh sửa được">
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Alerts & badges -->
    <div class="pc-card mb-4">
        <div class="pc-card-header"><h2 class="h5 mb-0">Alerts &amp; badges</h2></div>
        <div class="pc-card-body">
            <div class="pc-alert pc-alert-success mb-2"><i class="fa-solid fa-circle-check mt-1"></i><div>Thao tác thành công.</div></div>
            <div class="pc-alert pc-alert-warning mb-2"><i class="fa-solid fa-triangle-exclamation mt-1"></i><div>Sắp đến hạn nộp báo cáo.</div></div>
            <div class="pc-alert pc-alert-danger mb-2"><i class="fa-solid fa-circle-exclamation mt-1"></i><div>Có lỗi xảy ra, vui lòng thử lại.</div></div>
            <div class="pc-alert pc-alert-info mb-3"><i class="fa-solid fa-circle-info mt-1"></i><div>Hệ thống sẽ bảo trì lúc 22:00.</div></div>
            <div class="d-flex flex-wrap gap-2">
                <span class="pc-badge pc-badge-primary">OUTLINE</span>
                <span class="pc-badge pc-badge-info">FILE</span>
                <span class="pc-badge pc-badge-success">Đã nộp</span>
                <span class="pc-badge pc-badge-warning">Chờ bổ sung</span>
                <span class="pc-badge pc-badge-danger">Quá hạn</span>
                <span class="pc-badge pc-badge-neutral">Nháp</span>
            </div>
        </div>
    </div>

    <!-- Table -->
    <div class="pc-card mb-4">
        <div class="pc-card-header"><h2 class="h5 mb-0">Table</h2></div>
        <div class="pc-card-body p-0">
            <table class="pc-table pc-table-hover">
                <thead><tr><th>Đơn vị</th><th>Đầu mục</th><th>Trạng thái</th><th>Hạn nộp</th></tr></thead>
                <tbody>
                    <tr><td>Đội 1</td><td>Báo cáo tuần 34</td><td><span class="pc-badge pc-badge-success">Đã nộp</span></td><td>28/08/2026</td></tr>
                    <tr><td>Đội 2</td><td>Báo cáo tuần 34</td><td><span class="pc-badge pc-badge-warning">Chờ bổ sung</span></td><td>29/08/2026</td></tr>
                    <tr><td>Đội 3</td><td>Báo cáo tuần 34</td><td><span class="pc-badge pc-badge-danger">Quá hạn</span></td><td>25/08/2026</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Empty state + pagination -->
    <div class="row g-4 mb-4">
        <div class="col-lg-6">
            <div class="pc-card h-100">
                <div class="pc-card-header"><h2 class="h5 mb-0">Empty state</h2></div>
                <div class="pc-empty">
                    <div class="pc-empty-icon"><i class="fa-regular fa-folder-open"></i></div>
                    <div class="pc-empty-title">Chưa có dữ liệu</div>
                    <div>Thử thay đổi bộ lọc hoặc tạo mới bản ghi.</div>
                </div>
            </div>
        </div>
        <div class="col-lg-6">
            <div class="pc-card h-100">
                <div class="pc-card-header"><h2 class="h5 mb-0">Pagination &amp; modal</h2></div>
                <div class="pc-card-body">
                    <nav><ul class="pagination pc-pagination mb-4">
                        <li class="page-item disabled"><a class="page-link" href="#">«</a></li>
                        <li class="page-item active"><a class="page-link" href="#">1</a></li>
                        <li class="page-item"><a class="page-link" href="#">2</a></li>
                        <li class="page-item"><a class="page-link" href="#">3</a></li>
                        <li class="page-item"><a class="page-link" href="#">»</a></li>
                    </ul></nav>
                    <button class="pc-btn pc-btn-secondary" data-bs-toggle="modal" data-bs-target="#sgDemoModal">Mở modal mẫu</button>
                </div>
            </div>
        </div>
    </div>
</div>

<div class="modal fade" id="sgDemoModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content pc-modal">
            <div class="modal-header">
                <h5 class="modal-title">Modal mẫu</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng"></button>
            </div>
            <div class="modal-body">Modal đã nhận nền, viền và radius theo token.</div>
            <div class="modal-footer">
                <button type="button" class="pc-btn pc-btn-secondary" data-bs-dismiss="modal">Đóng</button>
                <button type="button" class="pc-btn pc-btn-primary" data-bs-dismiss="modal">Xác nhận</button>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Chạy toàn bộ test**

Run: `python3 run_tests.py`
Expected: toàn bộ suite OK, cả 3 test styleguide PASS.

- [ ] **Step 6: Kiểm tra trực quan (nếu có tài khoản admin local)**

Đăng nhập admin trên trình duyệt, mở `/admin/styleguide`, duyệt từng section ở light và dark (nút chuyển theme). Nếu không có sẵn tài khoản, dựa vào test render ở Step 5 và ghi chú trong báo cáo.

- [ ] **Step 7: Commit**

```bash
git add routes/admin.py templates/styleguide.html tests/test_design_system.py
git commit -m "Giao diện: thêm /admin/styleguide — trang tra cứu design system premium (chỉ admin)"
```

---

### Task 8: Hồi quy tổng thể + CHANGELOG + nghiệm thu

**Files:**
- Modify: `CHANGELOG.md` (thêm entry mới trên cùng, sau dòng `# CHANGELOG / TIMELINE`)

**Interfaces:**
- Consumes: toàn bộ Task 1–7.
- Produces: xác nhận nghiệm thu theo spec §10; entry CHANGELOG.

- [ ] **Step 1: Chạy toàn bộ suite**

Run: `python3 run_tests.py`
Expected: tất cả test OK (suite cũ 222 + 9 test mới; không có failure/error). Nếu số test cũ khác 222 do trạng thái repo, tiêu chí là KHÔNG có test nào FAIL so với trước khi bắt đầu plan này.

- [ ] **Step 2: Kiểm tra trình duyệt theo checklist spec §10**

Chạy `./START_SERVER_MAC.sh`, dùng browser-use:
1. `/login` desktop: render, nhập sai mật khẩu → alert lỗi premium; nút hiện/ẩn mật khẩu; modal quên mật khẩu; không lỗi console.
2. `/login` mobile (viewport/UA mobile): render `login_mobile.html`, form hoạt động.
3. Chuyển theme light/dark trên trang login (nếu có nút) và trên shell sau đăng nhập (nếu đăng nhập được): không vỡ màu, không flash.
4. Sau đăng nhập (nếu có tài khoản): mở dashboard, trang task, 1 trang admin — layout không vỡ, chức năng cũ chạy.
5. `/admin/styleguide` (đã đăng nhập admin): đủ section, cả 2 theme.

- [ ] **Step 3: Thêm entry CHANGELOG**

Chèn ngay sau dòng `# CHANGELOG / TIMELINE` trong `CHANGELOG.md`:

```markdown
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
```

- [ ] **Step 4: Commit cuối**

```bash
git add CHANGELOG.md
git commit -m "Giao diện: CHANGELOG subproject 1 — nền tảng thiết kế premium"
```

- [ ] **Step 5: Báo cáo nghiệm thu**

Tổng kết cho user: kết quả test, screenshot các trang đã kiểm tra, những điểm cần đăng nhập mới xem được (nếu có), và nhắc bước kế tiếp: brainstorming subproject 2 (Auth & bảo mật) khi sẵn sàng.
