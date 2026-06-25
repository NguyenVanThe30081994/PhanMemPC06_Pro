# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import time
import unittest

from app import app
from models import AppRole, LoginSecurityState, Notification, User, UserTrustedDevice, db
from security_utils.runtime_security import build_ip_network_hint, fingerprint_security_value


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._config_backup = {
            'LOGIN_FAILURE_WINDOW_SECONDS': app.config.get('LOGIN_FAILURE_WINDOW_SECONDS'),
            'LOGIN_MAX_FAILURES_PER_USER': app.config.get('LOGIN_MAX_FAILURES_PER_USER'),
            'LOGIN_MAX_FAILURES_PER_IP': app.config.get('LOGIN_MAX_FAILURES_PER_IP'),
            'LOGIN_LOCKOUT_SECONDS': app.config.get('LOGIN_LOCKOUT_SECONDS'),
            'LOGIN_LOCKOUT_MULTIPLIER_MAX': app.config.get('LOGIN_LOCKOUT_MULTIPLIER_MAX'),
            'LOGIN_USER_LOCK_SCHEDULE': app.config.get('LOGIN_USER_LOCK_SCHEDULE'),
            'LOGIN_IP_LOCK_SCHEDULE': app.config.get('LOGIN_IP_LOCK_SCHEDULE'),
            'LOGIN_COLLAPSE_REPEAT_PASSWORD': app.config.get('LOGIN_COLLAPSE_REPEAT_PASSWORD'),
            'LOGIN_LOCKOUT_DECAY_SECONDS': app.config.get('LOGIN_LOCKOUT_DECAY_SECONDS'),
            'SECURITY_REAUTH_WINDOW_SECONDS': app.config.get('SECURITY_REAUTH_WINDOW_SECONDS'),
            'SECURITY_DEVICE_COOKIE_NAME': app.config.get('SECURITY_DEVICE_COOKIE_NAME'),
            'SECURITY_DEVICE_COOKIE_MAX_AGE': app.config.get('SECURITY_DEVICE_COOKIE_MAX_AGE'),
            'AUTH_FAILURE_DELAY_MS': app.config.get('AUTH_FAILURE_DELAY_MS'),
        }
        app.config.update(
            LOGIN_FAILURE_WINDOW_SECONDS=300,
            LOGIN_MAX_FAILURES_PER_USER=5,
            LOGIN_MAX_FAILURES_PER_IP=50,
            LOGIN_LOCKOUT_SECONDS=60,
            LOGIN_LOCKOUT_MULTIPLIER_MAX=4,
            LOGIN_USER_LOCK_SCHEDULE='60,300,900',
            LOGIN_IP_LOCK_SCHEDULE='300,900',
            LOGIN_COLLAPSE_REPEAT_PASSWORD=True,
            LOGIN_LOCKOUT_DECAY_SECONDS=86400,
            SECURITY_REAUTH_WINDOW_SECONDS=1,
            SECURITY_DEVICE_COOKIE_NAME='pc06_device_test',
            SECURITY_DEVICE_COOKIE_MAX_AGE=3600,
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
            admin_role = AppRole.query.filter_by(name='Quản trị hệ thống').first()
            if not admin_role:
                admin_role = AppRole(name='Quản trị hệ thống', perms='{}')
                db.session.add(admin_role)
                db.session.flush()
            admin_user = User.query.filter_by(username='auth_security_admin').first()
            if not admin_user:
                admin_user = User(
                    username='auth_security_admin',
                    fullname='Auth Security Admin',
                    unit_area='PC06',
                    unit_key='pc06',
                    is_active=True,
                    must_change_password=False,
                    role_id=admin_role.id,
                )
                admin_user.set_password('AdminStrong1!')
                db.session.add(admin_user)
            else:
                admin_user.is_active = True
                admin_user.must_change_password = False
                admin_user.role_id = admin_role.id
                admin_user.set_password('AdminStrong1!')
            LoginSecurityState.query.filter(
                LoginSecurityState.scope_key.in_(['auth_security_test', '127.0.0.1'])
            ).delete(synchronize_session=False)
            Notification.query.filter(Notification.user_id.in_([user.id, admin_user.id])).delete(synchronize_session=False)
            UserTrustedDevice.query.filter(UserTrustedDevice.user_id.in_([user.id, admin_user.id])).delete(synchronize_session=False)
            db.session.commit()

    def tearDown(self):
        app.config.update(**self._config_backup)
        with app.app_context():
            LoginSecurityState.query.filter(
                LoginSecurityState.scope_key.in_(['auth_security_test', '127.0.0.1'])
            ).delete(synchronize_session=False)
            user_ids = [row[0] for row in db.session.query(User.id).filter(User.username.in_(['auth_security_test', 'auth_security_admin'])).all()]
            if user_ids:
                Notification.query.filter(Notification.user_id.in_(user_ids)).delete(synchronize_session=False)
                UserTrustedDevice.query.filter(UserTrustedDevice.user_id.in_(user_ids)).delete(synchronize_session=False)
            db.session.commit()

    def _set_admin_session(self, client, user_agent='AdminTest/1.0', ip='127.0.0.1'):
        with app.app_context():
            admin_user = User.query.filter_by(username='auth_security_admin').first()
            self.assertIsNotNone(admin_user)
            session_version = int(admin_user.session_version or 0)
        with client.session_transaction() as sess:
            sess['uid'] = admin_user.id
            sess['username'] = admin_user.username
            sess['fullname'] = admin_user.fullname
            sess['unit'] = admin_user.unit_area
            sess['unit_area'] = admin_user.unit_area
            sess['unit_area_ref'] = admin_user.unit_area
            sess['unit_key'] = admin_user.unit_key
            sess['role_id'] = admin_user.role_id
            sess['must_change'] = False
            sess['is_admin'] = True
            sess['last_active'] = time.time()
            sess['login_nonce'] = 'test-login-nonce'
            sess['session_version'] = session_version
            sess['session_user_agent_hash'] = fingerprint_security_value(
                app.secret_key,
                'user_agent',
                user_agent,
            )
            sess['session_ip_hint'] = build_ip_network_hint(ip)
            sess['csrf_token'] = 'test-csrf-token'
            sess['reauth_at'] = 0

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

    def test_login_lockout_escalates_after_distinct_failures(self):
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get('csrf_token')
        for attempt in range(4):
            response = self.client.post(
                '/login',
                data={
                    'username': 'auth_security_test',
                    'password': f'wrong-pass-{attempt}',
                    'csrf_token': csrf_token,
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('Thông tin đăng nhập không hợp lệ.'.encode('utf-8'), response.data)

        lock_response = self.client.post(
            '/login',
            data={'username': 'auth_security_test', 'password': 'wrong-pass-4', 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(lock_response.status_code, 200)
        self.assertIn('Tài khoản đang tạm khóa'.encode('utf-8'), lock_response.data)

        with app.app_context():
            username_state = LoginSecurityState.query.filter_by(
                scope_type='username',
                scope_key='auth_security_test',
            ).first()
            self.assertIsNotNone(username_state)
            self.assertEqual(username_state.lock_count, 1)
            first_lock_seconds = int((username_state.locked_until - datetime.utcnow()).total_seconds())
            self.assertGreaterEqual(first_lock_seconds, 45)
            username_state.locked_until = datetime.utcnow() - timedelta(seconds=1)
            db.session.commit()

        for attempt in range(5, 9):
            response = self.client.post(
                '/login',
                data={
                    'username': 'auth_security_test',
                    'password': f'wrong-pass-{attempt}',
                    'csrf_token': csrf_token,
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('Thông tin đăng nhập không hợp lệ.'.encode('utf-8'), response.data)

        second_lock_response = self.client.post(
            '/login',
            data={'username': 'auth_security_test', 'password': 'wrong-pass-9', 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(second_lock_response.status_code, 200)
        self.assertIn('Tài khoản đang tạm khóa'.encode('utf-8'), second_lock_response.data)

        with app.app_context():
            username_state = LoginSecurityState.query.filter_by(
                scope_type='username',
                scope_key='auth_security_test',
            ).first()
            self.assertIsNotNone(username_state)
            self.assertEqual(username_state.lock_count, 2)
            second_lock_seconds = int((username_state.locked_until - datetime.utcnow()).total_seconds())
            self.assertGreaterEqual(second_lock_seconds, 240)

        blocked_response = self.client.post(
            '/login',
            data={'username': 'auth_security_test', 'password': 'StrongPass1!', 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(blocked_response.status_code, 200)
        self.assertIn('Tài khoản đang tạm khóa'.encode('utf-8'), blocked_response.data)

    def test_repeated_same_wrong_password_does_not_trigger_user_lockout(self):
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get('csrf_token')

        for _ in range(6):
            response = self.client.post(
                '/login',
                data={'username': 'auth_security_test', 'password': 'cached-old-password', 'csrf_token': csrf_token},
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('Thông tin đăng nhập không hợp lệ.'.encode('utf-8'), response.data)

        with app.app_context():
            username_state = LoginSecurityState.query.filter_by(
                scope_type='username',
                scope_key='auth_security_test',
            ).first()
            self.assertIsNotNone(username_state)
            self.assertEqual(username_state.failed_attempts, 1)
            self.assertIsNone(username_state.locked_until)

    def test_lockout_decay_resets_escalation_after_quiet_period(self):
        with app.app_context():
            username_state = LoginSecurityState.query.filter_by(
                scope_type='username',
                scope_key='auth_security_test',
            ).first()
            if not username_state:
                username_state = LoginSecurityState(
                    scope_type='username',
                    scope_key='auth_security_test',
                )
                db.session.add(username_state)
            username_state.lock_count = 2
            username_state.failed_attempts = 0
            username_state.locked_until = None
            username_state.first_failed_at = None
            username_state.last_failed_at = datetime.utcnow() - timedelta(days=2)
            username_state.last_failed_secret_hash = None
            db.session.commit()

        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get('csrf_token')

        for attempt in range(4):
            response = self.client.post(
                '/login',
                data={
                    'username': 'auth_security_test',
                    'password': f'decay-pass-{attempt}',
                    'csrf_token': csrf_token,
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('Thông tin đăng nhập không hợp lệ.'.encode('utf-8'), response.data)

        lock_response = self.client.post(
            '/login',
            data={'username': 'auth_security_test', 'password': 'decay-pass-4', 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(lock_response.status_code, 200)
        self.assertIn('Tài khoản đang tạm khóa'.encode('utf-8'), lock_response.data)

        with app.app_context():
            username_state = LoginSecurityState.query.filter_by(
                scope_type='username',
                scope_key='auth_security_test',
            ).first()
            self.assertIsNotNone(username_state)
            self.assertEqual(username_state.lock_count, 1)

    def test_successful_login_registers_new_device_and_alerts_once(self):
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get('csrf_token')

        headers = {'User-Agent': 'UnitTestBrowser/1.0'}
        response = self.client.post(
            '/login',
            data={
                'username': 'auth_security_test',
                'password': 'StrongPass1!',
                'csrf_token': csrf_token,
            },
            headers=headers,
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(app.config.get('SECURITY_DEVICE_COOKIE_NAME'), response.headers.get('Set-Cookie', ''))

        with app.app_context():
            user = User.query.filter_by(username='auth_security_test').first()
            self.assertEqual(UserTrustedDevice.query.filter_by(user_id=user.id).count(), 1)
            self.assertEqual(
                Notification.query.filter_by(user_id=user.id, title='Cảnh báo bảo mật').count(),
                1,
            )

        self.client.get('/logout', follow_redirects=False)
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get('csrf_token')

        second_response = self.client.post(
            '/login',
            data={
                'username': 'auth_security_test',
                'password': 'StrongPass1!',
                'csrf_token': csrf_token,
            },
            headers=headers,
            follow_redirects=False,
        )
        self.assertEqual(second_response.status_code, 302)

        with app.app_context():
            user = User.query.filter_by(username='auth_security_test').first()
            self.assertEqual(UserTrustedDevice.query.filter_by(user_id=user.id).count(), 1)
            self.assertEqual(
                Notification.query.filter_by(user_id=user.id, title='Cảnh báo bảo mật').count(),
                1,
            )

    def test_security_page_requires_recent_reauthentication(self):
        admin_client = app.test_client()
        self._set_admin_session(admin_client)
        response = admin_client.get(
            '/admin/system/update',
            headers={'User-Agent': 'AdminTest/1.0'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/reauth', response.headers.get('Location', ''))

    def test_session_is_invalidated_when_security_version_changes(self):
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
            headers={'User-Agent': 'VersionCheck/1.0'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            user = User.query.filter_by(username='auth_security_test').first()
            user.session_version = int(user.session_version or 0) + 1
            db.session.commit()

        protected_response = self.client.get(
            '/tasks',
            headers={'User-Agent': 'VersionCheck/1.0'},
            follow_redirects=False,
        )
        self.assertEqual(protected_response.status_code, 302)
        self.assertIn('/login', protected_response.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
