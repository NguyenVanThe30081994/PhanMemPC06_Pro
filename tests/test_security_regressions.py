# -*- coding: utf-8 -*-
import json
import os
import time
import unittest
from datetime import datetime

from app import app
from models import AIAssistantConfig, AppRole, Notification, User, db
from security_utils.runtime_security import build_ip_network_hint, fingerprint_security_value


class SecurityRegressionTests(unittest.TestCase):
    TEST_USER_AGENT = 'SecurityRegressionTest/1.0'

    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []
        self.created_role_ids = []
        self.created_upload_paths = []
        self._ai_config_snapshot = None
        with app.app_context():
            config = AIAssistantConfig.query.first()
            if config:
                self._ai_config_snapshot = {
                    'id': config.id,
                    'provider': config.provider,
                    'model_name': config.model_name,
                    'api_key': config.api_key,
                    'api_key_encrypted': config.api_key_encrypted,
                    'system_prompt': config.system_prompt,
                    'is_active': config.is_active,
                }

    def tearDown(self):
        with app.app_context():
            if self.created_user_ids:
                Notification.query.filter(Notification.user_id.in_(self.created_user_ids)).delete(synchronize_session=False)
                User.query.filter(User.id.in_(self.created_user_ids)).delete(synchronize_session=False)
            if self.created_role_ids:
                AppRole.query.filter(AppRole.id.in_(self.created_role_ids)).delete(synchronize_session=False)
            if self._ai_config_snapshot is None:
                AIAssistantConfig.query.delete(synchronize_session=False)
            else:
                config = db.session.get(AIAssistantConfig, self._ai_config_snapshot['id'])
                if not config:
                    config = AIAssistantConfig(id=self._ai_config_snapshot['id'])
                    db.session.add(config)
                config.provider = self._ai_config_snapshot['provider']
                config.model_name = self._ai_config_snapshot['model_name']
                config.api_key = self._ai_config_snapshot['api_key']
                config.api_key_encrypted = self._ai_config_snapshot['api_key_encrypted']
                config.system_prompt = self._ai_config_snapshot['system_prompt']
                config.is_active = self._ai_config_snapshot['is_active']
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

    def test_ranking_page_allows_dashboard_view_role(self):
        user = self._create_user_with_role(
            'security_rank_view',
            perms={'p_dash_view': 1},
        )
        self._login_session(user)

        response = self.client.get('/ranking', headers={'User-Agent': self.TEST_USER_AGENT})
        self.assertEqual(response.status_code, 200)

    def test_ranking_save_forbidden_without_manage_permission(self):
        user = self._create_user_with_role(
            'security_rank_blocked',
            perms={'p_dash_view': 1},
        )
        self._login_session(user)

        response = self.client.post(
            '/ranking/api/save',
            json={'unit_id': 1, 'indicator_id': 1, 'value': 5},
            headers={'X-CSRF-Token': 'security-regression-csrf', 'User-Agent': self.TEST_USER_AGENT},
        )
        self.assertEqual(response.status_code, 403)

    def test_notifications_api_sanitizes_payload(self):
        user = self._create_user_with_role(
            'security_notif_user',
            perms={'p_dash_view': 1},
        )
        with app.app_context():
            db.session.add(Notification(
                user_id=user.id,
                title='Bảng tin <img src=x onerror=alert(1)>',
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

    def test_ai_api_key_is_encrypted_at_rest(self):
        user = self._create_user_with_role('security_admin_ai')
        self._login_admin_session(user)

        response = self.client.post(
            '/admin/ai-settings',
            data={
                'csrf_token': 'security-regression-csrf',
                'provider': 'openai',
                'model_name': 'gpt-4.1-mini',
                'api_key': 'sk-test-super-secret',
                'is_active': 'on',
            },
            headers={'User-Agent': self.TEST_USER_AGENT},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            config = AIAssistantConfig.query.first()
            self.assertIsNotNone(config)
            self.assertFalse(bool((config.api_key or '').strip()))
            self.assertTrue(bool((config.api_key_encrypted or '').strip()))
            self.assertNotIn('sk-test-super-secret', config.api_key_encrypted or '')
            self.assertEqual(config.get_api_key(app.secret_key), 'sk-test-super-secret')

    def test_login_redirect_with_clear_storage_sets_clear_site_data_header(self):
        response = self.client.get('/login?clear_storage=true')
        self.assertEqual(response.status_code, 200)
        self.assertIn('cookies', response.headers.get('Clear-Site-Data', ''))


if __name__ == '__main__':
    unittest.main()
