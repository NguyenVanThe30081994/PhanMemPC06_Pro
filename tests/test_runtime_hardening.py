# -*- coding: utf-8 -*-
"""Kiểm thử gia cố runtime theo docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md:

- A1: utils.get_client_ip dùng bản trusted-proxy (chỉ nhận X-Forwarded-For
  khi remote_addr thuộc TRUSTED_PROXY_CIDRS).
- A2: force_https_redirect khi PC06_FORCE_HTTPS bật; miễn health check;
  không redirect khi request đã HTTPS.
- A4: utils.check_csrf_token so sánh constant-time, an toàn với kiểu khác str.
"""
import unittest

from app import app
from utils import check_csrf_token, get_client_ip


class ClientIpTrustedProxyTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._cidrs_backup = app.config.get('TRUSTED_PROXY_CIDRS')

    def tearDown(self):
        app.config['TRUSTED_PROXY_CIDRS'] = self._cidrs_backup

    def test_forwarded_for_honored_when_proxy_trusted(self):
        # remote_addr = 127.0.0.1 (nằm trong CIDR tin cậy mặc định)
        with app.test_request_context(
            '/',
            environ_base={'REMOTE_ADDR': '127.0.0.1'},
            headers={'X-Forwarded-For': '203.0.113.7, 10.0.0.1'},
        ):
            self.assertEqual(get_client_ip(), '203.0.113.7')

    def test_forwarded_for_ignored_when_proxy_not_trusted(self):
        app.config['TRUSTED_PROXY_CIDRS'] = ''
        with app.test_request_context(
            '/',
            environ_base={'REMOTE_ADDR': '203.0.113.9'},
            headers={'X-Forwarded-For': '203.0.113.7'},
        ):
            # Proxy không đáng tin -> bỏ qua header, dùng remote_addr thật
            self.assertEqual(get_client_ip(), '203.0.113.9')

    def test_falls_back_to_remote_addr_without_header(self):
        with app.test_request_context('/', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
            self.assertEqual(get_client_ip(), '127.0.0.1')


class ForceHttpsRedirectTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._flag_backup = app.config.get('PC06_FORCE_HTTPS')

    def tearDown(self):
        app.config['PC06_FORCE_HTTPS'] = self._flag_backup

    def test_http_request_redirects_to_https_when_enabled(self):
        app.config['PC06_FORCE_HTTPS'] = True
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers.get('Location'), 'https://localhost/login')

    def test_https_request_not_redirected(self):
        app.config['PC06_FORCE_HTTPS'] = True
        response = self.client.get('/login', headers={'X-Forwarded-Proto': 'https'})
        self.assertEqual(response.status_code, 200)

    def test_disabled_flag_keeps_http(self):
        app.config['PC06_FORCE_HTTPS'] = False
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)

    def test_health_endpoints_exempt(self):
        app.config['PC06_FORCE_HTTPS'] = True
        response = self.client.get('/health')
        self.assertNotEqual(response.status_code, 308)


class CheckCsrfTokenTests(unittest.TestCase):
    def test_matching_tokens_pass(self):
        self.assertTrue(check_csrf_token('token-a', 'token-a'))

    def test_mismatched_tokens_fail(self):
        self.assertFalse(check_csrf_token('token-a', 'token-b'))

    def test_empty_values_fail(self):
        self.assertFalse(check_csrf_token('', 'token'))
        self.assertFalse(check_csrf_token('token', None))

    def test_non_string_inputs_safe(self):
        self.assertTrue(check_csrf_token(12345, '12345'))
        self.assertFalse(check_csrf_token(12345, '54321'))


if __name__ == '__main__':
    unittest.main()
