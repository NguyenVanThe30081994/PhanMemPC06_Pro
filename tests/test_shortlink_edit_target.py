# -*- coding: utf-8 -*-
"""Test hồi quy chức năng "sửa file nguồn không đổi QR/link" của module QR và liên kết.

Bất biến cốt lõi:
- POST /links/edit/<id> ĐỔI được `original_url` (file nguồn) nhưng KHÔNG BAO GIỜ
  đổi `short_code`, kể cả khi form gửi lên một `custom_code` khác.
- Vì QR chỉ mã hóa <host>/s/<short_code>, ảnh QR xuất ra trước và sau khi sửa
  phải giống hệt nhau (bytes PNG bằng nhau).
- /s/<code> sau khi sửa phải redirect tới URL mới.
- Người dùng khác (không phải admin, không phải chủ link) không được sửa.
"""
import time
import unittest

from app import app
from models import ShortLink, SystemLog, User, db
from security_utils.runtime_security import build_ip_network_hint, fingerprint_security_value

TEST_PASSWORD = 'Pc06Shortlink!2026'


class ShortlinkEditTargetTests(unittest.TestCase):
    TEST_USER_AGENT = 'ShortlinkEditTest/1.0'
    CSRF = 'shortlink-edit-csrf'

    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []
        self.created_link_ids = []
        self.created_log_ids = []

        with app.app_context():
            self.owner = self._make_user('slk_owner')
            self.other = self._make_user('slk_other')
            link = ShortLink(
                short_code='abc123',
                original_url='https://example.org/sai.pdf',
                custom_name='Tệp gửi sai',
                info='',
                created_by=self.owner,
            )
            db.session.add(link)
            db.session.commit()
            self.link_id = link.id
            self.created_link_ids.append(link.id)
            self.owner_name = 'Người tạo link'

    def tearDown(self):
        with app.app_context():
            if self.created_link_ids:
                ShortLink.query.filter(ShortLink.id.in_(self.created_link_ids)).delete(synchronize_session=False)
            if self.created_user_ids:
                User.query.filter(User.id.in_(self.created_user_ids)).delete(synchronize_session=False)
            logs = SystemLog.query.filter_by(action='Sửa liên kết rút gọn').all()
            for log in logs:
                self.created_log_ids.append(log.id)
            if self.created_log_ids:
                SystemLog.query.filter(SystemLog.id.in_(self.created_log_ids)).delete(synchronize_session=False)
            db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────
    def _make_user(self, username):
        User.query.filter_by(username=username).delete(synchronize_session=False)
        user = User(username=username, fullname=username, is_active=True, must_change_password=False)
        user.set_password(TEST_PASSWORD)
        db.session.add(user)
        db.session.flush()
        self.created_user_ids.append(user.id)
        return user.id

    def _login(self, uid):
        with app.app_context():
            user = db.session.get(User, uid)
            payload = {
                'uid': user.id,
                'username': user.username,
                'fullname': user.fullname,
                'unit': user.unit_area or '',
                'unit_area': user.unit_area or '',
                'unit_key': user.unit_key or '',
                'role_id': user.role_id,
                'session_version': int(user.session_version or 0),
            }
        with self.client.session_transaction() as sess:
            sess.update(payload)
            sess['must_change'] = False
            sess['is_admin'] = False
            sess['last_active'] = time.time()
            sess['login_nonce'] = 'shortlink-edit-session'
            sess['session_user_agent_hash'] = fingerprint_security_value(
                app.secret_key, 'user_agent', self.TEST_USER_AGENT
            )
            sess['session_ip_hint'] = build_ip_network_hint('127.0.0.1')
            sess['csrf_token'] = self.CSRF
            sess['reauth_at'] = time.time()

    def _post_edit(self, link_id, data, uid_field='original_url'):
        return self.client.post(
            f'/links/edit/{link_id}',
            data=data,
            headers={'User-Agent': self.TEST_USER_AGENT},
        )

    def _link_snapshot(self, link_id=None, code=None):
        with app.app_context():
            if link_id is not None:
                link = db.session.get(ShortLink, link_id)
            else:
                link = ShortLink.query.filter_by(short_code=code).first()
            if not link:
                return None
            return {
                'short_code': link.short_code,
                'original_url': link.original_url,
                'custom_name': link.custom_name,
                'info': link.info,
                'clicks': int(link.clicks or 0),
            }

    # ── tests ──────────────────────────────────────────────────────────────
    def test_edit_changes_source_url_but_keeps_short_code(self):
        self._login(self.owner)
        resp = self._post_edit(self.link_id, {
            'csrf_token': self.CSRF,
            'original_url': 'https://example.org/dung.pdf',
            'custom_name': 'Tệp gửi đúng',
            'info': 'đã thay tệp',
        })
        self.assertEqual(resp.status_code, 302)

        snap = self._link_snapshot(link_id=self.link_id)
        self.assertEqual(snap['short_code'], 'abc123')  # mã không đổi → QR/link giữ nguyên
        self.assertEqual(snap['original_url'], 'https://example.org/dung.pdf')
        self.assertEqual(snap['custom_name'], 'Tệp gửi đúng')

    def test_edit_ignores_short_code_sent_from_form(self):
        """Dù form gửi kèm custom_code khác (form cũ/tấn công), short_code phải giữ nguyên."""
        self._login(self.owner)
        resp = self._post_edit(self.link_id, {
            'csrf_token': self.CSRF,
            'original_url': 'https://example.org/dung.pdf',
            'custom_code': 'code-moi-999',
        })
        self.assertEqual(resp.status_code, 302)

        snap = self._link_snapshot(link_id=self.link_id)
        self.assertEqual(snap['short_code'], 'abc123')
        self.assertIsNone(self._link_snapshot(code='code-moi-999'))

        # /s/<mã cũ> giờ trỏ tới tệp mới
        redirect = self.client.get('/s/abc123', headers={'User-Agent': self.TEST_USER_AGENT})
        self.assertEqual(redirect.status_code, 302)
        self.assertIn('dung.pdf', redirect.headers.get('Location', ''))

    def test_qr_image_is_byte_identical_after_edit(self):
        self._login(self.owner)
        qr_before = self.client.get('/download-qr/abc123', headers={'User-Agent': self.TEST_USER_AGENT})
        self.assertEqual(qr_before.status_code, 200)

        self._post_edit(self.link_id, {
            'csrf_token': self.CSRF,
            'original_url': 'https://example.org/dung.pdf',
        })

        qr_after = self.client.get('/download-qr/abc123', headers={'User-Agent': self.TEST_USER_AGENT})
        self.assertEqual(qr_after.status_code, 200)
        self.assertEqual(qr_before.data, qr_after.data, 'Ảnh QR phải không đổi sau khi sửa file nguồn')

    def test_edit_rejects_invalid_or_empty_url(self):
        self._login(self.owner)
        resp = self._post_edit(self.link_id, {
            'csrf_token': self.CSRF,
            'original_url': 'javascript:alert(1)',
        })
        self.assertEqual(resp.status_code, 302)
        snap = self._link_snapshot(link_id=self.link_id)
        self.assertEqual(snap['original_url'], 'https://example.org/sai.pdf')

        resp = self._post_edit(self.link_id, {'csrf_token': self.CSRF, 'original_url': ''})
        self.assertEqual(resp.status_code, 302)
        snap = self._link_snapshot(link_id=self.link_id)
        self.assertEqual(snap['original_url'], 'https://example.org/sai.pdf')

    def test_other_user_cannot_edit(self):
        self._login(self.other)
        resp = self._post_edit(self.link_id, {
            'csrf_token': self.CSRF,
            'original_url': 'https://evil.example/other.pdf',
        })
        self.assertEqual(resp.status_code, 302)
        snap = self._link_snapshot(link_id=self.link_id)
        self.assertEqual(snap['original_url'], 'https://example.org/sai.pdf')

    def test_edit_writes_system_log(self):
        self._login(self.owner)
        self._post_edit(self.link_id, {
            'csrf_token': self.CSRF,
            'original_url': 'https://example.org/dung.pdf',
        })
        with app.app_context():
            log = SystemLog.query.filter_by(action='Sửa liên kết rút gọn').order_by(SystemLog.id.desc()).first()
            self.assertIsNotNone(log)
            self.assertIn('abc123', log.details or '')
            self.assertIn('dung.pdf', log.details or '')


if __name__ == '__main__':
    unittest.main()
