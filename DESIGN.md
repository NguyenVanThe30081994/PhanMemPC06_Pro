# Design System: PhanMemPC06_Pro (PC06 Executive Platform)

## 1. Visual Theme & Atmosphere
- **Atmosphere:** Rigorous, executive, and calm institutional design. High-clarity administrative system for governance, digital transformation, and executive task management (Đề án 06).
- **Density:** 7/10 (Cockpit / Daily App Balanced) — high data density with precise whitespace, strict horizontal rhythm, and zero visual clutter.
- **Variance:** 4/10 (Offset Asymmetric / Predictable Structured) — stable grid structure for tables and forms, asymmetric split cards for executive KPIs and summary views.
- **Motion:** 4/10 (Fluid Micro-Interactions) — instant feedback, subtle spring physics (`cubic-bezier(.2, 0, 0, 1)`), no distracting loops in administrative workflows.

## 2. Color Palette & Roles
- **Canvas Light** (`#f8fafc` / `--pc-bg`) — Primary application background surface (Slate-50).
- **Pure Surface Card** (`#ffffff` / `--pc-bg-card`) — Card and modular container background.
- **Deep Navy Ink** (`#2b5396` / `--pc-primary`) — Primary brand tone, action anchors, and active states.
- **Strong Navy** (`#24437a` / `--pc-primary-strong`) — Hover/active state on primary controls.
- **Soft Tint Blue** (`#f2f6fc` / `--pc-primary-soft`) — Subtle highlight, tag backgrounds, active row fills.
- **Slate Text Ink** (`#1e293b` / `--pc-text`) — Primary high-contrast body typography (Slate-800).
- **Muted Slate** (`#64748b` / `--pc-text-muted`) — Labels, timestamps, secondary metadata (Slate-500).
- **Whisper Border** (`#e2e8f0` / `--pc-border`) — Card boundaries and table dividers (Slate-200).
- **Semantic Accents:**
  - Success: `#15803d` / Bg: `#ecfdf3` / Border: `#bbe7c9` (Hoàn thành / Đạt)
  - Warning: `#b45309` / Bg: `#fffbeb` / Border: `#fde5ae` (Gần hạn / Cảnh báo)
  - Danger: `#dc2626` / Bg: `#fef2f2` / Border: `#fecaca` (Quá hạn / Lỗi)
  - Info: `#0369a1` / Bg: `#f0f9ff` / Border: `#bae6fd` (Hướng dẫn / Đang xử lý)
- **Dark Mode Surface:** `#0b1220` canvas, `#111b2e` cards, `#e7edf7` text, `#22304a` borders.

## 3. Typography Rules
- **Display / Headlines:** `Be Vietnam Pro` (Weights 600, 700, 800) — Track-tight (-0.02em), clean baseline, weight-driven hierarchy.
- **Body:** `Be Vietnam Pro` (Weights 400, 500) — Relaxed line height (`1.6`), max 75 characters per column in reading mode.
- **Mono / Data:** `SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace` — For task codes, shortlinks, OTP, and dense status statistics.
- **Banned:** `Inter`, `Times New Roman`, generic neon typography, and excessive gradient text headings.

## 4. Component Stylings
- **Buttons (`.pc-btn`):** Tactile push (`transform: translateY(-1px)` on hover, `translateY(0)` on active). 12px padding, 8-12px border radius. No neon glow, no bloated drop-shadows.
- **Cards (`.pc-card`):** Rounded 12-16px (`--pc-radius-md` to `lg`), 1px structural border (`--pc-border`), crisp soft shadow (`--pc-shadow-xs` / `--pc-shadow-sm`).
- **Data Tables (`.pc-table`):** Compact row height, sticky header support, zebra or hover tint with `--pc-primary-soft`, numbers right-aligned with monospace font.
- **Badges (`.pc-badge`):** Pill/rounded tag format, muted semantic backgrounds with high-contrast text.
- **Inputs & Forms (`.pc-input`, `.form-control`):** Clean border, no floating label obscurities, clear accent focus ring (`--pc-primary-ring`).
- **Loaders & Empty States:** Skeleton shimmer matching table/card layouts; composed empty state with icon and action button.

## 5. Layout Principles
- **Grid Structure:** CSS Grid / Flexbox with standard 4px spacing scale (`--pc-space-1` to `--pc-space-12`).
- **Split Screen / Asymmetric KPI:** Executive overview uses multi-tier metric counters with progress bars, not monotonous identical boxes.
- **Responsive Strategy:** 
  - Desktop: Sidebar navigation + top breadcrumb bar + expansive dashboard container.
  - Mobile: Dual-template fallback (`*_mobile.html`), bottom action bar, single-column stack, minimum 44px tap target.
- **Containment:** Max width container bounding for ultra-wide screens to prevent table stretching.

## 6. Motion & Interaction
- **Physics:** Micro-transitions `120ms` to `200ms` using `cubic-bezier(.2, 0, 0, 1)`.
- **Feedback:** SweetAlert2 integration for dialogs/confirmations, non-blocking toast notifications.
- **Performance:** Hardware-accelerated transitions via `transform` and `opacity`.

## 7. Anti-Patterns (AI Tells & UI Flaws Banned)
- ❌ No emojis in formal government labels or headers (use Font Awesome icons exclusively).
- ❌ No hardcoded hex values in template styles (always map to `--pc-*` tokens).
- ❌ No pure black (`#000000`) backgrounds or borders.
- ❌ No AI purple/neon glow gradients.
- ❌ No centered single-button hero designs on data dashboards.
- ❌ No unstyled default file input widgets or unpadded input fields.
