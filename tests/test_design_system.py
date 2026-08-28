# -*- coding: utf-8 -*-
"""Contract test cho design system premium PC06 (subproject 1).

Kiểm tra: tokens/component tồn tại trong pc06-premium.css, base templates nạp
CSS đúng vị trí, trang login giữ nguyên contract chức năng.
"""
import os
import unittest
import uuid
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

    def test_premium_css_restyles_app_shell(self):
        css = _read(PREMIUM_CSS)
        for selector in (
            ".desktop-sidebar", ".desktop-brand-badge", ".sidebar-nav-link",
            ".nav-link-top", ".mobile-header", ".mobile-bottom-nav",
        ):
            self.assertIn(selector, css, f"Thiếu shell selector {selector}")


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


class AuthScreensContractTests(unittest.TestCase):
    """Contract test các màn hình auth/bảo mật migrate sang pc-* (subproject 2).

    Giữ nguyên contract chức năng: form action, tên input, hidden fields,
    QR/otpauth, script toggle-password; markup chuyển sang class pc-*.
    """

    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []

    def tearDown(self):
        with app.app_context():
            for uid in self.created_user_ids:
                User.query.filter_by(id=uid).delete()
            db.session.commit()

    def _create_user(self):
        with app.app_context():
            user = User(
                username=f"auth_{uuid.uuid4().hex[:8]}",
                fullname="Auth Screen Test",
                unit_area="",
                unit_key="",
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.created_user_ids.append(user.id)
            return user.id

    def _login(self, user_id):
        import time

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
                sess["is_admin"] = False
                sess["session_version"] = int(user.session_version or 0)
                sess["csrf_token"] = "auth-test-csrf"
                sess["last_active"] = datetime.now().timestamp()
                sess["login_nonce"] = "auth-test"
                sess["reauth_at"] = time.time()

    def test_two_factor_login_redirects_without_pending(self):
        res = self.client.get("/login/two-factor")
        self.assertEqual(res.status_code, 302)

    def test_two_factor_login_template_contract(self):
        from flask import render_template as flask_render_template

        with app.test_request_context():
            body = flask_render_template("two_factor_login.html")
        for marker in (
            "pc06-premium.css",
            'action="/login/two-factor"',
            'name="code"',
            'autocomplete="one-time-code"',
            'name="csrf_token"',
            'href="/login"',
            "pc-card",
        ):
            self.assertIn(marker, body)

    def test_two_factor_setup_contract(self):
        uid = self._create_user()
        self._login(uid)
        res = self.client.get("/security/two-factor")
        body = res.get_data(as_text=True)
        self.assertEqual(res.status_code, 200)
        for marker in (
            "pc-card",
            'action="/security/two-factor"',
            'name="action"',
            'value="begin"',
            "pc06-premium.css",
        ):
            self.assertIn(marker, body)

    def test_password_screens_contract(self):
        uid = self._create_user()
        self._login(uid)
        for ua in (None, MOBILE_UA):
            headers = {"User-Agent": ua} if ua else {}
            res = self.client.get("/password", headers=headers)
            body = res.get_data(as_text=True)
            self.assertEqual(res.status_code, 200)
            for marker in (
                'name="old_password"',
                'name="new_password"',
                "toggle-password",
                "pc-input",
            ):
                self.assertIn(marker, body)

    def test_reauth_screens_contract(self):
        uid = self._create_user()
        self._login(uid)
        for ua in (None, MOBILE_UA):
            headers = {"User-Agent": ua} if ua else {}
            res = self.client.get("/reauth?next=/admin", headers=headers)
            body = res.get_data(as_text=True)
            self.assertEqual(res.status_code, 200)
            for marker in ('name="password"', 'name="next"', "toggle-password", "pc-input"):
                self.assertIn(marker, body)


class DashboardScreensContractTests(unittest.TestCase):
    """Contract test nhóm dashboard migrate lên premium tokens (subproject 3).

    Nguồn template phải dùng var(--pc-*), không còn hex palette cũ #0066ff;
    route render 200 cả desktop lẫn mobile; contract canvas/chart data giữ nguyên.
    """

    def setUp(self):
        self.client = app.test_client()

    def _login_admin(self):
        with app.app_context():
            admin = (
                User.query.filter_by(username="admin").first()
                or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            )
        with self.client.session_transaction() as sess:
            sess["uid"] = admin.id
            sess["username"] = admin.username
            sess["fullname"] = admin.fullname
            sess["unit"] = admin.unit_area or ""
            sess["unit_area"] = admin.unit_area or ""
            sess["unit_area_ref"] = admin.unit_area or ""
            sess["unit_key"] = admin.unit_key or ""
            sess["role_id"] = admin.role_id
            sess["must_change"] = False
            sess["is_admin"] = True
            sess["session_version"] = int(admin.session_version or 0)
            sess["csrf_token"] = "dash-test-csrf"
            sess["last_active"] = datetime.now().timestamp()
            sess["login_nonce"] = "dash-test"

    def test_admin_dashboard_source_tokenized(self):
        src = _read(os.path.join(APP_ROOT, "templates", "admin_dashboard.html"))
        self.assertIn("var(--pc-primary)", src)
        self.assertIn("#2b5396", src)
        self.assertNotIn("#0066ff", src)
        self.assertIn('id="overviewBarChart"', src)
        self.assertIn('id="overviewDonutChart"', src)
        self.assertIn("tojson", src)

    def test_admin_dashboard_mobile_source_tokenized(self):
        src = _read(os.path.join(APP_ROOT, "templates", "admin_dashboard_mobile.html"))
        self.assertIn("var(--pc-primary)", src)
        self.assertNotIn("#0066ff", src)
        self.assertIn("dashboard_cards", src)

    def test_report_dashboard_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "report_dashboard.html"))
        for marker in ("pc-page-header", "pc-card", "pc-table", "pc-badge", "pc-alert"):
            self.assertIn(marker, src)
        self.assertIn("url_for('tasks_bp.task_detail'", src)

    def test_admin_dashboard_renders_for_admin_desktop(self):
        self._login_admin()
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        self.assertIn("overviewBarChart", res.get_data(as_text=True))

    def test_admin_dashboard_renders_for_admin_mobile(self):
        self._login_admin()
        res = self.client.get("/admin", headers={"User-Agent": MOBILE_UA})
        self.assertEqual(res.status_code, 200)
        self.assertIn("overview-mobile", res.get_data(as_text=True))

    def test_report_dashboard_renders(self):
        self._login_admin()
        res = self.client.get("/tasks/report-dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn("pc-page-header", res.get_data(as_text=True))


class TaskScreensContractTests(unittest.TestCase):
    """Contract test nhóm màn task đơn giản migrate lên premium tokens (subproject 4a).

    Nguồn template phải dùng pc-* components; route render 200 với markup đúng.
    """

    def setUp(self):
        self.client = app.test_client()

    def _login_admin(self):
        with app.app_context():
            admin = (
                User.query.filter_by(username="admin").first()
                or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            )
        with self.client.session_transaction() as sess:
            sess["uid"] = admin.id
            sess["username"] = admin.username
            sess["fullname"] = admin.fullname
            sess["unit"] = admin.unit_area or ""
            sess["unit_area"] = admin.unit_area or ""
            sess["unit_area_ref"] = admin.unit_area or ""
            sess["unit_key"] = admin.unit_key or ""
            sess["role_id"] = admin.role_id
            sess["must_change"] = False
            sess["is_admin"] = True
            sess["session_version"] = int(admin.session_version or 0)
            sess["csrf_token"] = "task-test-csrf"
            sess["last_active"] = datetime.now().timestamp()
            sess["login_nonce"] = "task-test"

    def test_task_form_aggregation_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "task_form_aggregation.html"))
        for marker in ("pc-page-header", "pc-table", "pc-badge"):
            self.assertIn(marker, src)

    def test_task_import_drafts_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "task_import_drafts.html"))
        for marker in ("pc-page-header", "pc-card", "pc-table", "pc-btn"):
            self.assertIn(marker, src)


class OutlineScreensContractTests(unittest.TestCase):
    """Contract test nhóm outline migrate lên premium tokens (subproject 4b).

    Nguồn template phải dùng pc-* components ở phần container/frame;
    giữ nguyên CSS palette + JS đặc thù của editor.
    """

    def setUp(self):
        self.client = app.test_client()

    def test_outline_editor_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "outline_editor.html"))
        for marker in ("pc-card", "pc-btn"):
            self.assertIn(marker, src)

    def test_outline_assign_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "outline_assign.html"))
        for marker in ("pc-card", "pc-btn"):
            self.assertIn(marker, src)


class TaskCoreContractTests(unittest.TestCase):
    """Contract test nhóm task core migrate lên premium tokens (subproject 4c).

    Token hóa khung ngoài sang pc-*; giữ nguyên CSS nội bộ + JS nghiệp vụ.
    """

    def setUp(self):
        self.client = app.test_client()

    def test_tasks_rebuild_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "tasks_rebuild.html"))
        for marker in ("pc-card", "pc-btn", "pc-table"):
            self.assertIn(marker, src)

    def test_task_detail_rebuild_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "task_detail_rebuild.html"))
        for marker in ("pc-btn", "pc-table"):
            self.assertIn(marker, src)


class ImportDraftContractTests(unittest.TestCase):
    """Contract test trang import draft detail migrate lên premium tokens (subproject 4d).

    Token hóa khung ngoài sang pc-*; giữ nguyên CSS nội bộ + JS nghiệp vụ.
    """

    def setUp(self):
        self.client = app.test_client()

    def test_import_draft_detail_source_uses_premium_components(self):
        src = _read(os.path.join(APP_ROOT, "templates", "task_import_draft_detail.html"))
        for marker in ("pc-card", "pc-btn", "pc-table"):
            self.assertIn(marker, src)


class AdminPagesContractTests(unittest.TestCase):
    """Contract test nhóm trang quản trị migrate lên premium tokens (subproject 5).

    Token hóa khung ngoài sang pc-*; giữ nguyên CSS nội bộ + JS nghiệp vụ.
    """

    def setUp(self):
        self.client = app.test_client()

    def _check_template_markers(self, filename, markers):
        src = _read(os.path.join(APP_ROOT, "templates", filename))
        for m in markers:
            self.assertIn(m, src, f"Missing {m} in {filename}")

    def test_category_admin_source(self):
        self._check_template_markers("category_admin.html", ("pc-card", "pc-btn"))

    def test_categories_uses_legacy_bridge(self):
        """categories.html dùng Bootstrap thuần — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "categories.html"))
        self.assertIn("btn btn-primary", src)

    def test_units_uses_legacy_bridge(self):
        """units.html dùng Bootstrap thuần — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "units.html"))
        self.assertIn("btn-primary", src)

    def test_delegations_uses_legacy_bridge(self):
        """delegations.html dùng Bootstrap thuần — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "delegations.html"))
        self.assertIn("btn-primary", src)

    def test_module_categories_uses_custom_cards(self):
        """module_categories.html dùng pc06-page-summary-card — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "module_categories.html"))
        self.assertIn("pc06-page-summary-card", src)

    def test_shortlinks_uses_custom_cards(self):
        """shortlinks.html dùng pc06-page-summary-card — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "shortlinks.html"))
        self.assertIn("pc06-page-summary-card", src)

    def test_logs_uses_custom_cards(self):
        """logs.html dùng pc06-page-summary-card — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "logs.html"))
        self.assertIn("pc06-page-summary-card", src)

    def test_db_tool_uses_custom_cards(self):
        """db_tool.html dùng pc06-page-summary-card — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "db_tool.html"))
        self.assertIn("pc06-page-summary-card", src)

    def test_system_update_uses_custom_cards(self):
        """system_update.html dùng pc06-page-summary-card — bridge legacy map sang pc-* tokens."""
        src = _read(os.path.join(APP_ROOT, "templates", "system_update.html"))
        self.assertIn("pc06-page-summary-card", src)

    def test_roles_uses_premium_buttons(self):
        """roles.html đã migrate btn-bdhvs sang pc-btn trong subproject SD."""
        src = _read(os.path.join(APP_ROOT, "templates", "roles.html"))
        self.assertIn("pc-btn", src)

    def test_contacts_uses_premium_buttons(self):
        """contacts.html đã migrate btn-bdhvs sang pc-btn trong subproject SD."""
        src = _read(os.path.join(APP_ROOT, "templates", "contacts.html"))
        self.assertIn("pc-btn", src)


class SidebarMenuContractTests(unittest.TestCase):
    """Contract test sidebar menu HỆ THỐNG migrate lên premium tokens (subproject SA).

    Token hóa nav link trong dropdown HỆ THỐNG sang pc-nav-item; giữ nguyên JS/layout.
    """

    def setUp(self):
        self.client = app.test_client()

    def test_base_html_system_submenu_uses_premium_nav(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base.html"))
        # Kiểm tra các nav link trong section HỆ THỐNG có class pc-nav-item
        self.assertIn("pc-nav-item", src)

    def test_base_mobile_html_system_submenu_uses_premium_nav(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base_mobile.html"))
        self.assertIn("pc-nav-item", src)


class ShellMobileTokenTests(unittest.TestCase):
    """Subproject M1: shell mobile dùng token pc-* + font thống nhất Be Vietnam Pro
    (chuẩn mực Mục 5.4 + 7.5 — docs/THIET_KE_TONG_GIAO_DIEN_2026.md)."""

    def test_base_mobile_no_inter_font(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base_mobile.html"))
        self.assertNotIn("family=Inter", src)
        self.assertNotIn("'Inter'", src)

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


class SkeletonComponentTests(unittest.TestCase):
    """Subproject M2: pattern pc-skeleton (chuẩn mực Mục 4.2 —
    docs/THIET_KE_TONG_GIAO_DIEN_2026.md)."""

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


class SwalThemeTests(unittest.TestCase):
    """Subproject M3: SweetAlert2 ăn token pc-* (chuẩn mực Mục 4.3 —
    docs/THIET_KE_TONG_GIAO_DIEN_2026.md)."""

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


class EmptyStateContractTests(unittest.TestCase):
    """Subproject M4: empty state dùng chuẩn pc-empty + flash mobile về Swal
    (chuẩn mực Mục 4.1 + 4.3 — docs/THIET_KE_TONG_GIAO_DIEN_2026.md)."""

    def test_core_pages_use_pc_empty(self):
        for name in ("thong_bao.html", "contacts.html", "roles.html", "tasks_rebuild.html"):
            src = _read(os.path.join(APP_ROOT, "templates", name))
            self.assertIn("pc-empty", src)

    def test_mobile_flash_uses_swal_not_bootstrap_alert(self):
        src = _read(os.path.join(APP_ROOT, "templates", "base_mobile.html"))
        self.assertNotIn("alert-dismissible", src)
        self.assertIn("Toast.fire", src)


class BdhvsLayoutTokenTests(unittest.TestCase):
    """Subproject M5: bdhvs-layout.css hết hardcode brand/semantic hex
    (chuẩn mực Mục 7.3.1 — docs/THIET_KE_TONG_GIAO_DIEN_2026.md)."""

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

    def test_premium_css_defines_accent_tokens(self):
        css = _read(PREMIUM_CSS)
        for token in ("--pc-accent-violet:", "--pc-accent-pink:"):
            self.assertIn(token, css)
