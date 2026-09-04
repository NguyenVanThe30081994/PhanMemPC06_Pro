# -*- coding: utf-8 -*-
"""Test tính năng reset mật khẩu hàng loạt theo đơn vị được tích chọn.

Endpoint: POST /admin/users/reset-password-by-units
- Nhận `unit_values` (JSON list các stable-value của danh mục Đơn vị),
  `temporary_password`, `confirm_password`.
- Reset toàn bộ tài khoản thuộc các đơn vị đã chọn, bỏ qua admin hệ thống,
  bật `must_change_password` và tăng `session_version` (thu hồi phiên đang mở).

Lưu ý: các helper DB luôn trả về id (int), không trả ORM object — object sẽ
bị detach khi thoát `app.app_context()`.
"""
import json
import time
import unittest

from app import app
from models import AppRole, CategoryGroup, CategoryItem, SystemLog, User, db
from security_utils.runtime_security import build_ip_network_hint, fingerprint_security_value


TEST_PASSWORD = 'Pc06BulkReset!2026'
# Tên nhóm danh mục mà `_unit_category_options()` resolve (module contacts/unit_name
# hoặc fallback theo tên). Test tạo nhóm đúng tên này để stable_value khớp resolver.
UNIT_GROUP_NAME = 'Đơn vị'


class BulkResetPasswordByUnitsTests(unittest.TestCase):
    TEST_USER_AGENT = 'BulkResetByUnitsTest/1.0'

    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []
        self.created_role_ids = []
        self.created_category_ids = []
        self.created_group_ids = []
        self.created_log_ids = []

        with app.app_context():
            # Nhóm danh mục "Đơn vị" — reuse nếu đã seed, tạo mới nếu chưa có.
            group = CategoryGroup.query.filter_by(name=UNIT_GROUP_NAME).first()
            if not group:
                group = CategoryGroup(name=UNIT_GROUP_NAME, code='don_vi', is_active=True)
                db.session.add(group)
                db.session.flush()
                self.created_group_ids.append(group.id)

            unit_a = self._make_unit_item(group, 'don_vi_a', 'Đơn vị A')
            unit_b = self._make_unit_item(group, 'don_vi_b', 'Đơn vị B')
            unit_c = self._make_unit_item(group, 'don_vi_c', 'Đơn vị C')
            self.unit_a_value = f"category_item:{unit_a.id}"
            self.unit_b_value = f"category_item:{unit_b.id}"
            self.unit_c_value = f"category_item:{unit_c.id}"

            # 3 tài khoản đơn vị A, 2 tài khoản đơn vị B, 1 tài khoản đơn vị C.
            self.unit_a_ids = [self._make_user(f'a_user_{i}', 'Đơn vị A', 'don_vi_a') for i in range(3)]
            self.unit_b_ids = [self._make_user(f'b_user_{i}', 'Đơn vị B', 'don_vi_b') for i in range(2)]
            self.unit_c_ids = [self._make_user(f'c_user_{i}', 'Đơn vị C', 'don_vi_c') for i in range(1)]

            # Tài khoản admin hệ thống (username == 'admin') — luôn phải được giữ lại.
            admin = User.query.filter_by(username='admin').first()
            self.admin_id = admin.id if admin else None
            if admin:
                admin.password_hash = 'original-admin-hash'
                admin.must_change_password = False
                admin.session_version = 0
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            if self.created_user_ids:
                User.query.filter(User.id.in_(self.created_user_ids)).delete(synchronize_session=False)
            if self.created_role_ids:
                AppRole.query.filter(AppRole.id.in_(self.created_role_ids)).delete(synchronize_session=False)
            if self.created_category_ids:
                CategoryItem.query.filter(CategoryItem.id.in_(self.created_category_ids)).delete(synchronize_session=False)
            if self.created_group_ids:
                CategoryGroup.query.filter(CategoryGroup.id.in_(self.created_group_ids)).delete(synchronize_session=False)
            if self.created_log_ids:
                SystemLog.query.filter(SystemLog.id.in_(self.created_log_ids)).delete(synchronize_session=False)
            if self.admin_id:
                admin = db.session.get(User, self.admin_id)
                if admin:
                    admin.password_hash = 'original-admin-hash'
                    admin.must_change_password = False
                    admin.session_version = 0
            db.session.commit()

    # ── helpers (chỉ gọi trong app.app_context() của caller) ───────────────
    def _make_unit_item(self, group, code, name):
        item = CategoryItem(group_id=group.id, code=code, name=name, is_active=True)
        db.session.add(item)
        db.session.flush()
        self.created_category_ids.append(item.id)
        return item

    def _make_user(self, username, unit_area, unit_key, password=TEST_PASSWORD):
        User.query.filter_by(username=username).delete(synchronize_session=False)
        user = User(
            username=username,
            fullname=username,
            unit_area=unit_area,
            unit_key=unit_key,
            is_active=True,
            must_change_password=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        self.created_user_ids.append(user.id)
        return user.id

    def _make_operator_user(self, username='operator_user'):
        """User có quyền user.process nhưng KHÔNG phải admin hệ thống. Trả về id."""
        with app.app_context():
            User.query.filter_by(username=username).delete(synchronize_session=False)
            AppRole.query.filter_by(name=f'role_{username}').delete(synchronize_session=False)
            db.session.commit()
            role = AppRole(name=f'role_{username}', perms=json.dumps({'p_user_process': 1}, ensure_ascii=False))
            db.session.add(role)
            db.session.flush()
            self.created_role_ids.append(role.id)
            uid = self._make_user(username, 'Đơn vị vận hành', 'van_hanh')
            user = db.session.get(User, uid)
            user.role_id = role.id
            db.session.commit()
            return uid

    def _login(self, uid):
        with app.app_context():
            user = db.session.get(User, uid)
            user_payload = {
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
            sess.update(user_payload)
            sess['must_change'] = False
            sess['is_admin'] = False
            sess['last_active'] = time.time()
            sess['login_nonce'] = 'bulk-reset-by-units-session'
            sess['session_user_agent_hash'] = fingerprint_security_value(
                app.secret_key, 'user_agent', self.TEST_USER_AGENT
            )
            sess['session_ip_hint'] = build_ip_network_hint('127.0.0.1')
            sess['csrf_token'] = 'bulk-reset-by-units-csrf'
            sess['reauth_at'] = time.time()

    def _post_reset(self, unit_values, password=TEST_PASSWORD, confirm=None):
        if confirm is None:
            confirm = password
        return self.client.post(
            '/admin/users/reset-password-by-units',
            data={
                'csrf_token': 'bulk-reset-by-units-csrf',
                'unit_values': json.dumps(unit_values),
                'temporary_password': password,
                'confirm_password': confirm,
            },
            headers={'User-Agent': self.TEST_USER_AGENT},
        )

    def _user_snapshot(self, uid):
        """Đọc thuộc tính cần assert ngay trong context, trả dict plain."""
        with app.app_context():
            user = db.session.get(User, uid)
            return {
                'password_hash': user.password_hash,
                'must_change_password': bool(user.must_change_password),
                'session_version': int(user.session_version or 0),
                'check_password': user.check_password(TEST_PASSWORD),
            }

    # ── tests ──────────────────────────────────────────────────────────────
    def test_resets_only_selected_units_and_preserves_admin(self):
        operator = self._make_operator_user()
        self._login(operator)

        response = self._post_reset([self.unit_a_value])
        self.assertEqual(response.status_code, 302)  # redirect về /roles

        # Toàn bộ user đơn vị A đã đổi mật khẩu + bị buộc đổi khi đăng nhập.
        for uid in self.unit_a_ids:
            snap = self._user_snapshot(uid)
            self.assertTrue(snap['check_password'])
            self.assertTrue(snap['must_change_password'])
            self.assertGreater(snap['session_version'], 0)

        # User đơn vị B và C không bị đụng tới.
        for uid in self.unit_b_ids + self.unit_c_ids:
            snap = self._user_snapshot(uid)
            self.assertFalse(snap['must_change_password'])
            self.assertEqual(snap['session_version'], 0)

        # Admin hệ thống được giữ nguyên.
        if self.admin_id:
            snap = self._user_snapshot(self.admin_id)
            self.assertEqual(snap['password_hash'], 'original-admin-hash')
            self.assertFalse(snap['must_change_password'])

    def test_multiple_units_reset_together(self):
        operator = self._make_operator_user()
        self._login(operator)

        response = self._post_reset([self.unit_a_value, self.unit_b_value])
        self.assertEqual(response.status_code, 302)

        for uid in self.unit_a_ids + self.unit_b_ids:
            snap = self._user_snapshot(uid)
            self.assertTrue(snap['check_password'])
            self.assertTrue(snap['must_change_password'])

        # Đơn vị C vẫn nguyên.
        for uid in self.unit_c_ids:
            snap = self._user_snapshot(uid)
            self.assertFalse(snap['must_change_password'])

    def test_empty_unit_list_is_rejected(self):
        operator = self._make_operator_user()
        self._login(operator)

        response = self._post_reset([])
        self.assertEqual(response.status_code, 302)

        # Không ai bị reset.
        for uid in self.unit_a_ids + self.unit_b_ids + self.unit_c_ids:
            snap = self._user_snapshot(uid)
            self.assertFalse(snap['must_change_password'])

    def test_password_mismatch_is_rejected(self):
        operator = self._make_operator_user()
        self._login(operator)

        response = self._post_reset([self.unit_a_value], password=TEST_PASSWORD, confirm='Different!Pass1')
        self.assertEqual(response.status_code, 302)

        for uid in self.unit_a_ids:
            snap = self._user_snapshot(uid)
            self.assertFalse(snap['must_change_password'])
            self.assertTrue(snap['check_password'])  # mật khẩu cũ còn hiệu lực

    def test_weak_password_is_rejected(self):
        operator = self._make_operator_user()
        self._login(operator)

        response = self._post_reset([self.unit_a_value], password='123', confirm='123')
        self.assertEqual(response.status_code, 302)

        for uid in self.unit_a_ids:
            snap = self._user_snapshot(uid)
            self.assertFalse(snap['must_change_password'])

    def test_permission_denied_without_user_process(self):
        # User không có quyền user.process.
        with app.app_context():
            plain = self._make_user('plain_user', 'Đơn vị A', 'don_vi_a')
            db.session.commit()
        self._login(plain)

        response = self._post_reset([self.unit_a_value])
        self.assertEqual(response.status_code, 302)

        for uid in self.unit_a_ids:
            snap = self._user_snapshot(uid)
            self.assertFalse(snap['must_change_password'])

    def test_logs_action_with_unit_count(self):
        operator = self._make_operator_user()
        self._login(operator)

        self._post_reset([self.unit_a_value, self.unit_b_value])

        with app.app_context():
            log = SystemLog.query.filter_by(action='Reset mật khẩu hàng loạt theo đơn vị').order_by(
                SystemLog.id.desc()
            ).first()
            self.assertIsNotNone(log)
            self.created_log_ids.append(log.id)
            self.assertIn('so_don_vi=2', log.details)
            self.assertIn('so_luong=5', log.details)  # 3 user A + 2 user B


if __name__ == '__main__':
    unittest.main()
