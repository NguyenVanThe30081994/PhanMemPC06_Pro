# -*- coding: utf-8 -*-
import unittest
from unittest import mock

from app import app
from models import AppRole, User, db


class GoogleOAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._config_backup = {
            'GOOGLE_OAUTH_CLIENT_ID': app.config.get('GOOGLE_OAUTH_CLIENT_ID'),
            'GOOGLE_OAUTH_CLIENT_SECRET': app.config.get('GOOGLE_OAUTH_CLIENT_SECRET'),
            'GOOGLE_OAUTH_REDIRECT_URI': app.config.get('GOOGLE_OAUTH_REDIRECT_URI'),
            'GOOGLE_OAUTH_ALLOWED_DOMAINS': app.config.get('GOOGLE_OAUTH_ALLOWED_DOMAINS'),
            'TESTING': app.config.get('TESTING'),
        }
        app.config.update(
            GOOGLE_OAUTH_CLIENT_ID='test-client-id.apps.googleusercontent.com',
            GOOGLE_OAUTH_CLIENT_SECRET='test-client-secret',
            GOOGLE_OAUTH_REDIRECT_URI='http://localhost/auth/google/callback',
            GOOGLE_OAUTH_ALLOWED_DOMAINS=[],
            TESTING=True,
        )
        with app.app_context():
            role = AppRole.query.filter_by(name='Quản trị hệ thống').first()
            self.role_id = role.id if role else None
            user = User.query.filter_by(email='google.user@example.com').first()
            if not user:
                user = User(
                    username='google_oauth_test',
                    fullname='Google OAuth Test',
                    email='google.user@example.com',
                    unit_area='PC06',
                    unit_key='pc06',
                    role_id=self.role_id,
                    is_active=True,
                    must_change_password=False,
                )
                user.set_password('StrongPass1!')
                db.session.add(user)
                db.session.commit()
            self.user_id = user.id

    def tearDown(self):
        app.config.update(self._config_backup)

    def test_google_login_disabled_when_not_configured(self):
        app.config.update(
            GOOGLE_OAUTH_CLIENT_ID='',
            GOOGLE_OAUTH_CLIENT_SECRET='',
        )
        response = self.client.get('/auth/google')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_google_login_redirects_to_google(self):
        response = self.client.get('/auth/google')
        self.assertEqual(response.status_code, 302)
        location = response.headers.get('Location', '')
        self.assertIn('accounts.google.com/o/oauth2/v2/auth', location)
        self.assertIn('client_id=test-client-id.apps.googleusercontent.com', location)
        self.assertIn('code_challenge=', location)
        self.assertIn('state=', location)

    def test_google_callback_invalid_state(self):
        response = self.client.get(
            '/auth/google/callback?code=abc&state=forged.0000'
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_google_callback_full_flow(self):
        # Start the flow to populate session (state/verifier)
        start = self.client.get('/auth/google')
        self.assertEqual(start.status_code, 302)
        location = start.headers.get('Location', '')
        state_param = None
        for part in location.split('&'):
            if part.startswith('state='):
                state_param = part.split('=', 1)[1]
        self.assertTrue(state_param)
        import urllib.parse
        state_value = urllib.parse.unquote(state_param)

        token_payload = {'access_token': 'test-access-token', 'token_type': 'Bearer'}
        userinfo_payload = {'email': 'google.user@example.com', 'name': 'Google OAuth Test'}

        with mock.patch('routes.google_auth.requests.post') as mock_post, \
                mock.patch('routes.google_auth.requests.get') as mock_get:
            mock_post.return_value = mock.Mock(
                raise_for_status=mock.Mock(), json=mock.Mock(return_value=token_payload)
            )
            mock_get.return_value = mock.Mock(
                raise_for_status=mock.Mock(), json=mock.Mock(return_value=userinfo_payload)
            )
            response = self.client.get(f'/auth/google/callback?code=test-code&state={state_value}')

        self.assertEqual(response.status_code, 302)
        # Should land on admin index (admin role)
        self.assertIn('/admin', response.headers.get('Location', ''))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('uid'), self.user_id)

    def test_google_callback_unknown_email(self):
        start = self.client.get('/auth/google')
        location = start.headers.get('Location', '')
        import urllib.parse
        state_value = None
        for part in location.split('&'):
            if part.startswith('state='):
                state_value = urllib.parse.unquote(part.split('=', 1)[1])
        token_payload = {'access_token': 'test-access-token'}
        userinfo_payload = {'email': 'nobody@example.com'}

        with mock.patch('routes.google_auth.requests.post') as mock_post, \
                mock.patch('routes.google_auth.requests.get') as mock_get:
            mock_post.return_value = mock.Mock(
                raise_for_status=mock.Mock(), json=mock.Mock(return_value=token_payload)
            )
            mock_get.return_value = mock.Mock(
                raise_for_status=mock.Mock(), json=mock.Mock(return_value=userinfo_payload)
            )
            response = self.client.get(f'/auth/google/callback?code=test-code&state={state_value}')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('uid'))

    def test_google_callback_allowed_domain_restriction(self):
        app.config.update(GOOGLE_OAUTH_ALLOWED_DOMAINS=['congan.gov.vn'])
        start = self.client.get('/auth/google')
        location = start.headers.get('Location', '')
        import urllib.parse
        state_value = None
        for part in location.split('&'):
            if part.startswith('state='):
                state_value = urllib.parse.unquote(part.split('=', 1)[1])
        token_payload = {'access_token': 'test-access-token'}
        userinfo_payload = {'email': 'google.user@example.com'}

        with mock.patch('routes.google_auth.requests.post') as mock_post, \
                mock.patch('routes.google_auth.requests.get') as mock_get:
            mock_post.return_value = mock.Mock(
                raise_for_status=mock.Mock(), json=mock.Mock(return_value=token_payload)
            )
            mock_get.return_value = mock.Mock(
                raise_for_status=mock.Mock(), json=mock.Mock(return_value=userinfo_payload)
            )
            response = self.client.get(f'/auth/google/callback?code=test-code&state={state_value}')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('uid'))


if __name__ == '__main__':
    unittest.main()
