# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
import zipfile

from app import app
from security_utils.runtime_security import (
    ensure_persistent_secret_key,
    generate_temporary_password,
    resolve_safe_path,
    safe_extract_zip,
)
from security_utils.security_helpers import get_client_ip


class RuntimeSecurityTests(unittest.TestCase):
    def setUp(self):
        self._trusted_proxy_backup = app.config.get("TRUSTED_PROXY_CIDRS")

    def tearDown(self):
        app.config["TRUSTED_PROXY_CIDRS"] = self._trusted_proxy_backup

    def test_persistent_secret_key_is_stable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_a = ensure_persistent_secret_key(temp_dir, "")
            secret_b = ensure_persistent_secret_key(temp_dir, "")
            self.assertEqual(secret_a, secret_b)
            self.assertTrue(os.path.exists(os.path.join(temp_dir, ".secret_key")))

    def test_get_client_ip_ignores_forwarded_header_from_untrusted_source(self):
        with app.test_request_context(
            "/",
            environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        ):
            app.config["TRUSTED_PROXY_CIDRS"] = "127.0.0.1/8"
            self.assertEqual(get_client_ip(), "8.8.8.8")

    def test_get_client_ip_uses_forwarded_header_from_trusted_proxy(self):
        with app.test_request_context(
            "/",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers={"X-Forwarded-For": "1.2.3.4, 127.0.0.1"},
        ):
            app.config["TRUSTED_PROXY_CIDRS"] = "127.0.0.1/8"
            self.assertEqual(get_client_ip(), "1.2.3.4")

    def test_resolve_safe_path_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                resolve_safe_path(temp_dir, "../outside.txt", allow_missing=True)

    def test_safe_extract_zip_blocks_zip_slip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = os.path.join(temp_dir, "payload.zip")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "blocked")

            with self.assertRaises(ValueError):
                safe_extract_zip(archive_path, temp_dir)

    def test_generated_temporary_password_is_strong(self):
        password = generate_temporary_password()
        self.assertGreaterEqual(len(password), 12)
        self.assertTrue(any(ch.islower() for ch in password))
        self.assertTrue(any(ch.isupper() for ch in password))
        self.assertTrue(any(ch.isdigit() for ch in password))
        self.assertTrue(any(not ch.isalnum() for ch in password))


if __name__ == "__main__":
    unittest.main()
