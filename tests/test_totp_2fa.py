# -*- coding: utf-8 -*-
"""Kiểm thử xác thực hai lớp TOTP (Đợt C3,
docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md):

- Đăng nhập đúng mật khẩu khi đã bật 2FA → dừng ở bước nhập mã, CHƯA có phiên.
- Nhập đúng mã TOTP → phiên đăng nhập đầy đủ.
- Nhập sai quá số lần → hủy phiên chờ, phải đăng nhập lại.
- Luồng tự kích hoạt: tạo khóa (lưu mã hóa), quét QR (otpauth), bật bằng mã hợp lệ.
- Tắt 2FA bắt buộc mật khẩu đúng.
- User chưa bật 2FA đăng nhập như cũ.
"""
import io
import time
import unittest
import uuid

import pyotp

from app import app
from models import AppRole, LoginSecurityState, User, UserTrustedDevice, db
from security_utils.runtime_security import decrypt_secret_value


class TotpTwoFactorTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.csrf_token = "totp-test-csrf"
        self.created_user_ids = []
        self.role_id = None

    def tearDown(self):
        with app.app_context():
            for user_id in self.created_user_ids:
                # Dọn dữ liệu tham chiếu user trước (SQLite ép FK)
                UserTrustedDevice.query.filter_by(user_id=user_id).delete()
            db.session.commit()
            for user_id in self.created_user_ids:
                usr = db.session.get(User, user_id)
                if usr:
                    LoginSecurityState.query.filter(
                        LoginSecurityState.scope_key == (usr.username or '').lower()
                    ).delete(synchronize_session=False)
                    User.query.filter_by(id=user_id).delete()
            db.session.commit()

    # ── Dụng cụ ──────────────────────────────────────────────────────────

    def _plain_role(self):
        if self.role_id:
            return self.role_id
        with app.app_context():
            role = AppRole.query.filter_by(name="Cán bộ CAX").first() or (
                AppRole.query.order_by(AppRole.id.asc()).first()
            )
            self.role_id = role.id if role else None
            return self.role_id

    def _create_user(self, username=None):
        with app.app_context():
            user = User(
                username=username or f"totp_{uuid.uuid4().hex[:8]}",
                fullname="Cán bộ 2FA",
                role_id=self._plain_role(),
                is_active=True,
                must_change_password=False,
            )
            user.set_password("StrongPass1!")
            db.session.add(user)
            db.session.commit()
            self.created_user_ids.append(user.id)
            return user

    def _fresh(self, user_id):
        with app.app_context():
            return db.session.get(User, user_id)

    def _set_secret(self, user_id, secret):
        """Ghi trực tiếp secret (mã hóa như route làm) cho kịch bản đã bật 2FA."""
        from security_utils.runtime_security import encrypt_secret_value
        with app.app_context():
            usr = db.session.get(User, user_id)
            key = app.secret_key or app.config.get('SECRET_KEY') or ''
            usr.totp_secret_encrypted = encrypt_secret_value(key, secret)
            usr.totp_enabled = True
            db.session.commit()

    def _read_secret(self, user_id):
        with app.app_context():
            usr = db.session.get(User, user_id)
            key = app.secret_key or app.config.get('SECRET_KEY') or ''
            return decrypt_secret_value(key, usr.totp_secret_encrypted)

    def _login_password_step(self, user):
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = self.csrf_token
        return self.client.post(
            "/login",
            data={"username": user.username, "password": "StrongPass1!", "csrf_token": self.csrf_token},
            follow_redirects=False,
        )

    # ── Kiểm thử ─────────────────────────────────────────────────────────

    def test_login_with_2fa_requires_totp_code(self):
        user = self._create_user()
        secret = pyotp.random_base32()
        self._set_secret(user.id, secret)

        response = self._login_password_step(user)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/two-factor", response.headers.get("Location", ""))

        # Chưa có phiên đăng nhập đầy đủ
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("uid"))
            self.assertIsNotNone(sess.get("twofactor_pending"))

    def test_correct_totp_code_completes_login(self):
        user = self._create_user()
        secret = pyotp.random_base32()
        self._set_secret(user.id, secret)

        self._login_password_step(user)
        code = pyotp.TOTP(secret).now()
        response = self.client.post(
            "/login/two-factor",
            data={"code": code, "csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/login", response.headers.get("Location", ""))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("uid"), user.id)
            self.assertIsNone(sess.get("twofactor_pending"))

    def test_wrong_code_five_times_clears_pending(self):
        user = self._create_user()
        secret = pyotp.random_base32()
        self._set_secret(user.id, secret)

        self._login_password_step(user)
        last_response = None
        for _ in range(5):
            last_response = self.client.post(
                "/login/two-factor",
                data={"code": "000000", "csrf_token": self.csrf_token},
                follow_redirects=False,
            )
        # Lần thứ 5 sai -> hủy phiên chờ và quay về trang đăng nhập
        self.assertEqual(last_response.status_code, 302)
        self.assertIn("/login", last_response.headers.get("Location", ""))
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("twofactor_pending"))
            self.assertIsNone(sess.get("uid"))

    def test_enrollment_flow_creates_encrypted_secret_and_enables(self):
        user = self._create_user()
        with self.client.session_transaction() as sess:
            sess["uid"] = user.id
            sess["username"] = user.username
            sess["fullname"] = user.fullname
            sess["role_id"] = user.role_id
            sess["must_change"] = False
            sess["is_admin"] = False
            sess["session_version"] = int(user.session_version or 0)
            sess["csrf_token"] = self.csrf_token
            sess["reauth_at"] = time.time()          # vừa xác minh lại cho khu nhạy cảm
            sess["last_active"] = time.time()
            sess["login_nonce"] = "totp-test"

        # Bước 1: tạo khóa
        self.client.post(
            "/security/two-factor",
            data={"action": "begin", "csrf_token": self.csrf_token},
        )
        fresh = self._fresh(user.id)
        self.assertTrue(fresh.totp_secret_encrypted)
        self.assertNotIn("JBSWY3DPEHPK3PXP", fresh.totp_secret_encrypted or "")  # không lưu plaintext
        self.assertFalse(fresh.totp_enabled)

        # Bước 2: trang thiết lập hiển thị mã QR (otpauth://)
        page = self.client.get("/security/two-factor")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("data:image/png;base64,", html)

        # Bước 3: kích hoạt bằng mã hợp lệ (route redirect về trang thiết lập)
        secret = self._read_secret(user.id)
        code = pyotp.TOTP(secret).now()
        enable_response = self.client.post(
            "/security/two-factor",
            data={"action": "enable", "code": code, "csrf_token": self.csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(enable_response.status_code, 200)
        self.assertTrue(self._fresh(user.id).totp_enabled)

    def test_disable_requires_correct_password(self):
        user = self._create_user()
        secret = pyotp.random_base32()
        self._set_secret(user.id, secret)
        with self.client.session_transaction() as sess:
            sess["uid"] = user.id
            sess["username"] = user.username
            sess["fullname"] = user.fullname
            sess["role_id"] = user.role_id
            sess["must_change"] = False
            sess["is_admin"] = False
            sess["session_version"] = int(user.session_version or 0)
            sess["csrf_token"] = self.csrf_token
            sess["reauth_at"] = time.time()
            sess["last_active"] = time.time()
            sess["login_nonce"] = "totp-test"

        wrong_pw = self.client.post(
            "/security/two-factor",
            data={"action": "disable", "password": "WrongPass9!", "csrf_token": self.csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(wrong_pw.status_code, 200)
        self.assertTrue(self._fresh(user.id).totp_enabled)

        ok = self.client.post(
            "/security/two-factor",
            data={"action": "disable", "password": "StrongPass1!", "csrf_token": self.csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(ok.status_code, 200)
        fresh = self._fresh(user.id)
        self.assertFalse(fresh.totp_enabled)
        self.assertIsNone(fresh.totp_secret_encrypted)

    def test_login_unaffected_without_2fa(self):
        user = self._create_user()
        response = self._login_password_step(user)
        self.assertEqual(response.status_code, 302)
        location = response.headers.get("Location", "")
        self.assertNotIn("/login/two-factor", location)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("uid"), user.id)


if __name__ == "__main__":
    unittest.main()
