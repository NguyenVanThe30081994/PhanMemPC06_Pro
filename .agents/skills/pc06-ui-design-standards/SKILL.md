---
name: pc06-ui-design-standards
description: Production UI/UX design standards and multi-viewport verification protocol for PhanMemPC06_Pro, distilled from top GitHub design skills (ui-ux-pro-max-skill, Vercel web-design-guidelines, Anthropic frontend-design). Activate whenever building, editing, or auditing any template or stylesheet.
---

# PC06 Pro — UI/UX Design Standards & Verification Protocol

Distilled from **ui-ux-pro-max-skill**, **Vercel Web Interface Guidelines**, and **Anthropic Frontend Design (`SKILL.md`)**, tailored for Vietnam GovTech / Police internal administration systems.

## 1. Information Architecture & Visual Hierarchy
1. **The 2-Second Test:** Any screen must immediately surface its primary data or action within 2 seconds. Never hide the main data table behind a separate "Filter" tab — keep filters as a compact 1-row inline bar directly above the content.
2. **One Primary Action per View:** Each section/header gets at most ONE primary CTA button (`pc-btn-primary`). Secondary actions use neutral/outline styles (`pc-btn-secondary`). Destructive actions use restrained danger styling.
3. **Zero Decorative Icon Clutter:** Never wrap plain text cards or navigation tiles in heavy colored icon squares when text alone is clearer. Keep icons strictly functional (small inline action triggers on tight mobile toolbars or status cues).
4. **No Redundant Chrome or Double Headings:** Never repeat a section title immediately above an identical card title. Eliminate filler headings ("Bàn Làm Việc Chức Năng") and awkward literal role titles ("Tổng hợp nhanh Lãnh đạo" → "Tổng hợp số liệu").
5. **Meaningful Density & Whitespace:** Use a consistent `4px / 8px` spacing scale (`4, 8, 12, 16, 20, 24px`). Avoid raw `<code>` pink/magenta developer strings in user-facing Vietnamese UI; use muted secondary metadata instead.

## 2. CSS Layout Engineering Rules (Anti-Regression)
1. **Never Use Fragile `auto-fit, minmax(180px+, 1fr)` Inside Split Bars:** On `1024px–1200px` laptops, a narrow `1fr` column next to action buttons collapses `minmax(180px)` cards into a vertical 1-column stack. Use explicit column counts (`repeat(3, minmax(0, 1fr))` / `repeat(2, minmax(0, 1fr))`) or wrap the outer bar below `1180px`.
2. **Never Leave Row `flex-basis` Active When Switching to `flex-direction: column`:** If a child has `flex: 1 1 240px` on Desktop (`row`), switching the container to `flex-direction: column` on Mobile turns `240px` into a **240px vertical height gap**! Always reset `flex: 0 0 auto` on mobile or use CSS Grid (`grid-template-columns: 1fr`).
3. **Never Combine Global `white-space: nowrap` with `table-layout: fixed`:** Legacy `style.css` sets `white-space: nowrap` on `.table td`. Every responsive mobile table MUST explicitly enforce `white-space: normal !important; overflow-wrap: anywhere; overflow: hidden;` on text cells and reserve exact fixed widths on action columns (`width: 100px–108px`).
4. **Strict Container Containment (`min-width: 0`, Zero Clipping):** Every card footer, toolbar, and button row must fit inside `316px` (inner width on `390px` mobile) with `box-sizing: border-box` and zero elements poking outside borders.
5. **Inline Horizontal Filter Bars on Desktop:** Short controls (`Từ ngày` `150px`, `Đến ngày` `150px`, `Người dùng` `200px`, `Lọc`, `Đặt lại`) belong on **1 single compact horizontal row** on Desktop, never stacked into 4 full-width rows!
6. **Unified 3-Tier Control Height Scale (`--pc-control-h-sm: 34px`, `--pc-control-h-md: 40px`, `--pc-control-h-lg: 46px`):**
   - ALL inputs, search boxes (`.pc06-search-control`), date pickers, dropdowns (`.form-select`, `.pc-select`), section tabs (`.pc06-section-menu-tab`), and buttons (`.pc-btn`) on the same row MUST share exact pixel height (`40px` standard or `34px` compact) and matching radius (`10px` / `8px`).
   - Native `<select>` MUST use `padding-block: 0; line-height: normal;` with explicit `height` so option text is 100% vertically centered across Chromium/Safari/Firefox (never floating near the top border).
   - Never override `height` on `.form-control`/`.form-select` inside a template without matching `min-height` or using the design token scale.
7. **Cache Busting:** Whenever editing `static/css/*.css`, ALWAYS bump `?v=` in EVERY template loading it.

## 3. Mandatory Multi-Viewport Visual Verification Gate
Never declare a UI task done from HTTP 200 or a single desktop viewport alone. Every UI change MUST be verified at **3 breakpoints**:
- **Mobile (`390px`):** `scrollWidth <= 390`, `2×2` or `3-col` summary grids, zero orphan wrapped buttons, zero text/button overlap, zero elements escaping card borders.
- **Laptop (`1024px–1100px`):** Summary bars, toolbars, and split panes do NOT collapse into awkward vertical stacks.
- **Desktop (`1280px+`):** Compact 1-row filter bars, wide readable inputs (`> 220px`), balanced whitespace, clean empty states for charts/tables.
- **Dark Mode + Light Mode:** Zero invisible text, zero hardcoded `#fff`/`#000` backgrounds without `[data-theme="dark"]` or `var(--pc-*)` tokens.
- **Zero JS console errors & Zero HTTP ≥ 400 responses.**
