# -*- coding: utf-8 -*-
import time
import unittest

from app import app
from models import User
from security_utils.runtime_security import build_ip_network_hint, fingerprint_security_value


class MartyrAdnMapRouteTests(unittest.TestCase):
    TEST_USER_AGENT = 'MartyrAdnMapRouteTest/1.0'

    def setUp(self):
        self.client = app.test_client()

    def _login_session(self):
        with app.app_context():
            user = User.query.filter_by(username='admin').first() or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, 'Cần có ít nhất một tài khoản để test route ADN.')

        with self.client.session_transaction() as sess:
            sess['uid'] = user.id
            sess['username'] = user.username
            sess['fullname'] = user.fullname
            sess['unit'] = user.unit_area or ''
            sess['unit_area'] = user.unit_area or ''
            sess['unit_area_ref'] = user.unit_area or ''
            sess['unit_key'] = user.unit_key or ''
            sess['role_id'] = user.role_id
            sess['must_change'] = False
            sess['is_admin'] = bool(getattr(user, 'is_admin', False)) or user.username == 'admin'
            sess['last_active'] = time.time()
            sess['login_nonce'] = 'martyr-adn-map-route-test'
            sess['session_version'] = int(user.session_version or 0)
            sess['session_user_agent_hash'] = fingerprint_security_value(app.secret_key, 'user_agent', self.TEST_USER_AGENT)
            sess['session_ip_hint'] = build_ip_network_hint('127.0.0.1')
            sess['reauth_at'] = time.time()
            sess['csrf_token'] = 'martyr-adn-map-csrf'

    def test_route_is_public(self):
        response = self.client.get('/ban-do-adn-liet-si', follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn('15 điểm tập kết ADN'.encode('utf-8'), response.data)

    def test_logged_in_user_can_open_map(self):
        self._login_session()
        response = self.client.get('/ban-do-adn-liet-si', headers={'User-Agent': self.TEST_USER_AGENT})
        self.assertEqual(response.status_code, 200)
        self.assertIn('15 điểm tập kết ADN'.encode('utf-8'), response.data)


if __name__ == '__main__':
    unittest.main()
