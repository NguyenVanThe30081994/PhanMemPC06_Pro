# -*- coding: utf-8 -*-
import unittest

from app import app
from models import LoginSecurityState, User, db


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._config_backup = {
            'LOGIN_FAILURE_WINDOW_SECONDS': app.config.get('LOGIN_FAILURE_WINDOW_SECONDS'),
            'LOGIN_MAX_FAILURES_PER_USER': app.config.get('LOGIN_MAX_FAILURES_PER_USER'),
            'LOGIN_MAX_FAILURES_PER_IP': app.config.get('LOGIN_MAX_FAILURES_PER_IP'),
            'LOGIN_LOCKOUT_SECONDS': app.config.get('LOGIN_LOCKOUT_SECONDS'),
            'LOGIN_LOCKOUT_MULTIPLIER_MAX': app.config.get('LOGIN_LOCKOUT_MULTIPLIER_MAX'),
            'AUTH_FAILURE_DELAY_MS': app.config.get('AUTH_FAILURE_DELAY_MS'),
        }
        app.config.update(
            LOGIN_FAILURE_WINDOW_SECONDS=300,
            LOGIN_MAX_FAILURES_PER_USER=3,
            LOGIN_MAX_FAILURES_PER_IP=50,
            LOGIN_LOCKOUT_SECONDS=60,
            LOGIN_LOCKOUT_MULTIPLIER_MAX=1,
            AUTH_FAILURE_DELAY_MS=0,
        )
        with app.app_context():
            user = User.query.filter_by(username='auth_security_test').first()
            if not user:
                user = User(
                    username='auth_security_test',
                    fullname='Auth Security Test',
                    unit_area='PC06',
                    unit_key='pc06',
                    is_active=True,
                    must_change_password=False,
                )
                user.set_password('StrongPass1!')
                db.session.add(user)
            else:
                user.is_active = True
                user.must_change_password = False
                user.set_password('StrongPass1!')
            LoginSecurityState.query.filter(
                LoginSecurityState.scope_key.in_(['auth_security_test', '127.0.0.1'])
            ).delete(synchronize_session=False)
            db.session.commit()

    def tearDown(self):
        app.config.update(**self._config_backup)
        with app.app_context():
            LoginSecurityState.query.filter(
                LoginSecurityState.scope_key.in_(['auth_security_test', '127.0.0.1'])
            ).delete(synchronize_session=False)
            db.session.commit()

    def test_unauthenticated_page_redirects_to_login(self):
        response = self.client.get('/admin', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_unauthenticated_api_returns_401(self):
        response = self.client.get('/api/category-picker')
        self.assertEqual(response.status_code, 401)

    def test_login_page_sets_security_headers(self):
        response = self.client.get('/login', headers={'X-Forwarded-Proto': 'https'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(response.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
        self.assertIn("default-src 'self'", response.headers.get('Content-Security-Policy', ''))
        self.assertIn('max-age=', response.headers.get('Strict-Transport-Security', ''))

    def test_login_post_requires_csrf_token(self):
        self.client.get('/login')
        response = self.client.post(
            '/login',
            data={'username': 'auth_security_test', 'password': 'StrongPass1!'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

    def test_login_post_accepts_valid_csrf_token(self):
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get('csrf_token')
        response = self.client.post(
            '/login',
            data={
                'username': 'auth_security_test',
                'password': 'StrongPass1!',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_security_txt_is_public(self):
        response = self.client.get('/.well-known/security.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/plain')
        self.assertIn('Contact:'.encode('utf-8'), response.data)
        self.assertIn('Policy:'.encode('utf-8'), response.data)

    def test_login_lockout_blocks_after_repeated_failures(self):
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get('csrf_token')
        for attempt in range(2):
            response = self.client.post(
                '/login',
                data={'username': 'auth_security_test', 'password': 'wrong-pass', 'csrf_token': csrf_token},
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('Thông tin đăng nhập không hợp lệ.'.encode('utf-8'), response.data)

        lock_response = self.client.post(
            '/login',
            data={'username': 'auth_security_test', 'password': 'wrong-pass', 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(lock_response.status_code, 200)
        self.assertIn('Tài khoản đang tạm khóa'.encode('utf-8'), lock_response.data)

        blocked_response = self.client.post(
            '/login',
            data={'username': 'auth_security_test', 'password': 'StrongPass1!', 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(blocked_response.status_code, 200)
        self.assertIn('Tài khoản đang tạm khóa'.encode('utf-8'), blocked_response.data)


if __name__ == '__main__':
    unittest.main()
