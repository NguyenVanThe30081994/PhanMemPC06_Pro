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
