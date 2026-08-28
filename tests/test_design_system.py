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
