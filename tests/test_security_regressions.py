# -*- coding: utf-8 -*-
import json
import os
import time
import unittest
from datetime import datetime

from app import app
from models import AppRole, Notification, User, db
from security_utils.runtime_security import build_ip_network_hint, fingerprint_security_value


class SecurityRegressionTests(unittest.TestCase):
    TEST_USER_AGENT = 'SecurityRegressionTest/1.0'

    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []
        self.created_role_ids = []
        self.created_upload_paths = []

    def tearDown(self):
        with app.app_context():
            if self.created_user_ids:
                Notification.query.filter(Notification.user_id.in_(self.created_user_ids)).delete(synchronize_session=False)
                User.query.filter(User.id.in_(self.created_user_ids)).delete(synchronize_session=False)
            if self.created_role_ids:
                AppRole.query.filter(AppRole.id.in_(self.created_role_ids)).delete(synchronize_session=False)
            db.session.commit()

        for path in self.created_upload_paths:
            if os.path.exists(path):
                os.remove(path)

    def _create_user_with_role(self, username, perms=None):
        with app.app_context():
            User.query.filter_by(username=username).delete(synchronize_session=False)
            AppRole.query.filter_by(name=f"role_{username}").delete(synchronize_session=False)
            db.session.commit()
            role = AppRole(name=f"role_{username}", perms=json.dumps(perms or {}, ensure_ascii=False))
            db.session.add(role)
            db.session.flush()
            user = User(
                username=username,
                fullname=username,
                role_id=role.id,
                unit_area='PC06',
                unit_key='pc06',
                is_active=True,
                must_change_password=False,
            )
            user.set_password('StrongPass1!')
            db.session.add(user)
            db.session.commit()
            self.created_role_ids.append(role.id)
            self.created_user_ids.append(user.id)
            return user

    def _login_session(self, user):
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
            sess['is_admin'] = False
            sess['last_active'] = time.time()
            sess['login_nonce'] = 'security-regression-session'
            sess['session_version'] = int(user.session_version or 0)
            sess['session_user_agent_hash'] = fingerprint_security_value(app.secret_key, 'user_agent', self.TEST_USER_AGENT)
            sess['session_ip_hint'] = build_ip_network_hint('127.0.0.1')
            sess['csrf_token'] = 'security-regression-csrf'
            sess['reauth_at'] = time.time()

    def _login_admin_session(self, user):
        self._login_session(user)
        with self.client.session_transaction() as sess:
            sess['is_admin'] = True

    def test_notifications_api_sanitizes_payload(self):
        user = self._create_user_with_role(
            'security_notif_user',
            perms={'p_dash_view': 1},
        )
        with app.app_context():
            # Tiêu đề chứa "công việc" để infer_notification_source xếp vào
            # nguồn 'task' — endpoint /api/notifications chỉ trả về thông báo
            # thuộc nguồn đã nhận diện (task/news/library/report).
            db.session.add(Notification(
                user_id=user.id,
                title='Công việc mới <img src=x onerror=alert(1)>',
                msg='Xin chao<script>alert(1)</script>',
                link='javascript:alert(1)',
            ))
            db.session.commit()
        self._login_session(user)

        response = self.client.get('/api/notifications', headers={'User-Agent': self.TEST_USER_AGENT})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload)
        self.assertEqual(payload[0]['link'], '')
        self.assertNotIn('<', payload[0]['title'])
        self.assertNotIn('<', payload[0]['msg'])

    def test_dl_file_rejects_unregistered_file_names(self):
        user = self._create_user_with_role(
            'security_download_user',
            perms={'p_dash_view': 1},
        )
        self._login_session(user)

        upload_root = app.config['UPLOAD_FOLDER']
        test_path = os.path.join(upload_root, 'unregistered_security_test.txt')
        with open(test_path, 'w', encoding='utf-8') as handle:
            handle.write('private')
        self.created_upload_paths.append(test_path)

        response = self.client.get('/dl_file/unregistered_security_test.txt', headers={'User-Agent': self.TEST_USER_AGENT})
        self.assertEqual(response.status_code, 404)

    def test_db_reset_is_disabled_by_default(self):
        user = self._create_user_with_role('security_admin_reset')
        self._login_admin_session(user)

        response = self.client.post(
            '/admin/db-manage',
            data={'action': 'reset', 'csrf_token': 'security-regression-csrf'},
            headers={'User-Agent': self.TEST_USER_AGENT},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_db_backup_is_disabled_by_default(self):
        user = self._create_user_with_role('security_admin_backup')
        self._login_admin_session(user)

        response = self.client.post(
            '/admin/db-manage',
            data={'action': 'backup', 'csrf_token': 'security-regression-csrf'},
            headers={'User-Agent': self.TEST_USER_AGENT},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_git_pull_is_disabled_by_default(self):
        user = self._create_user_with_role('security_admin_gitpull')
        self._login_admin_session(user)

        response = self.client.post(
            '/admin/system/git-pull',
            data={'csrf_token': 'security-regression-csrf'},
            headers={'User-Agent': self.TEST_USER_AGENT},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_web_system_update_is_disabled_by_default(self):
        user = self._create_user_with_role('security_admin_update')
        self._login_admin_session(user)

        response = self.client.post(
            '/admin/system/update',
            data={'csrf_token': 'security-regression-csrf'},
            headers={'User-Agent': self.TEST_USER_AGENT},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_login_redirect_with_clear_storage_sets_clear_site_data_header(self):
        response = self.client.get('/login?clear_storage=true')
        self.assertEqual(response.status_code, 200)
        self.assertIn('cookies', response.headers.get('Clear-Site-Data', ''))


if __name__ == '__main__':
    unittest.main()
