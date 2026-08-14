# -*- coding: utf-8 -*-
"""
Kiểm tra mô hình phân quyền tập trung (permissions.py):
- is_admin được tính lại từ DB mỗi request, không phụ thuộc session cũ
- Bỏ bypass username == 'admin'
- Quyền = hợp của vai trò chính + vai trò phụ (UserRole)
- unit_subtree_ids (data-scope theo cây đơn vị)
- Ủy quyền tạm thời (Delegation) cấp đúng quyền của người ủy quyền
- permission_log ghi nhận thay đổi phân quyền
"""
import unittest

from app import app
from models import (
    AppRole,
    Delegation,
    PermissionLog,
    Unit,
    User,
    UserRole,
    db,
)


class PermissionModelTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with app.app_context():
            self.admin_role_id = AppRole.query.filter_by(name='Quản trị hệ thống').first().id
            self.cax_role_id = AppRole.query.filter_by(name='Cán bộ CAX').first().id
            self.cat_role_id = AppRole.query.filter_by(name='Cán bộ CAT').first().id

            unit_a = Unit(code='unit_a_test', name='Công an tỉnh (test)', level='province')
            db.session.add(unit_a)
            db.session.commit()
            unit_b = Unit(code='unit_b_test', name='CA huyện B (test)', level='district', parent_id=unit_a.id)
            db.session.add(unit_b)
            db.session.commit()
            unit_c = Unit(code='unit_c_test', name='CA xã C (test)', level='commune', parent_id=unit_b.id)
            db.session.add(unit_c)
            db.session.commit()
            self.unit_a_id = unit_a.id
            self.unit_b_id = unit_b.id
            self.unit_c_id = unit_c.id

            user = User(
                username='perm_test_user',
                fullname='Người test phân quyền',
                unit_id=self.unit_b_id,
                role_id=self.cax_role_id,
                is_active=True,
                must_change_password=False,
            )
            user.set_password('StrongPass1!')
            db.session.add(user)
            db.session.commit()
            self.uid = user.id

    def tearDown(self):
        with app.app_context():
            UserRole.query.filter_by(user_id=self.uid).delete()
            Delegation.query.filter(
                (Delegation.delegator_id == self.uid) | (Delegation.delegatee_id == self.uid)
            ).delete()
            PermissionLog.query.filter_by(user_id=self.uid).delete()
            db.session.delete(db.session.get(User, self.uid))
            for unit_id in (self.unit_c_id, self.unit_b_id, self.unit_a_id):
                unit = db.session.get(Unit, unit_id)
                if unit:
                    db.session.delete(unit)
            db.session.commit()

    def _session_login(self, uid, reauth=True):
        import time
        with app.app_context():
            user = db.session.get(User, uid)
            role_id = user.role_id if user else None
            session_version = getattr(user, 'session_version', 0) or 0
        with self.client.session_transaction() as sess:
            sess['uid'] = uid
            sess['username'] = 'perm_test_user'
            sess['role_id'] = role_id
            sess['session_version'] = session_version
            sess['last_active'] = time.time()
            if reauth:
                # admin cần xác minh lại trước khi vào endpoint nhạy cảm
                sess['reauth_at'] = time.time()

    def test_is_admin_derived_from_db_not_session(self):
        """is_admin phải phản ánh vai trò HIỆN TẠI trong DB, không phải giá trị cũ lúc đăng nhập."""
        from permissions import user_is_admin
        with app.app_context():
            user = db.session.get(User, self.uid)
            # Cán bộ CAX → không phải admin
            self.assertFalse(user_is_admin(user))
            # Đổi vai trò thành Quản trị hệ thống → phải admin ngay (không cần đăng nhập lại)
            user.role_id = self.admin_role_id
            db.session.commit()
            self.assertTrue(user_is_admin(user))
            # Thu hồi lại → không còn admin
            user.role_id = self.cax_role_id
            db.session.commit()
            self.assertFalse(user_is_admin(user))

    def test_admin_username_no_longer_bypasses(self):
        """Tài khoản tên 'admin' KHÔNG còn tự động là superuser."""
        from permissions import user_is_admin
        with app.app_context():
            admin_user = User.query.filter_by(username='admin').first()
            original_role_id = admin_user.role_id if admin_user else None
            if admin_user:
                admin_user.role_id = self.cax_role_id
                db.session.commit()
            try:
                if admin_user:
                    self.assertFalse(user_is_admin(db.session.get(User, admin_user.id)))
            finally:
                if admin_user and original_role_id is not None:
                    admin_user = db.session.get(User, admin_user.id)
                    admin_user.role_id = original_role_id
                    db.session.commit()

    def test_extra_roles_union_permissions(self):
        """User có vai trò chính CAX (exec) + vai trò phụ CAT (process) → có cả exec lẫn process."""
        from permissions import user_perms_payload
        with app.app_context():
            db.session.add(UserRole(user_id=self.uid, role_id=self.cat_role_id))
            db.session.commit()
            user = db.session.get(User, self.uid)
            perms, role_name, is_admin = user_perms_payload(user)
            self.assertEqual(role_name, 'Cán bộ CAX')
            self.assertFalse(is_admin)
            # exec từ CAX
            self.assertTrue(perms.get('p_task_exec'))
            # process từ CAT phụ
            self.assertTrue(perms.get('p_task_process'))

    def test_require_perm_blocks_unauthorized(self):
        """Route gated sys.view (db-tool) chặn user chỉ có quyền xem công việc."""
        with app.app_context():
            user = db.session.get(User, self.uid)
            user.role_id = self.cax_role_id
            db.session.commit()
        self._session_login(self.uid)
        # Cán bộ CAX không có quyền sys → không vào được trang db-tool
        response = self.client.get('/admin/db-tool')
        self.assertNotEqual(response.status_code, 200)

    def test_admin_can_access_sys_page(self):
        with app.app_context():
            user = db.session.get(User, self.uid)
            user.role_id = self.admin_role_id
            db.session.commit()
        self._session_login(self.uid)
        response = self.client.get('/admin/db-tool')
        self.assertEqual(response.status_code, 200)

    def test_unit_subtree_ids(self):
        from utils import unit_subtree_ids
        with app.app_context():
            ids = unit_subtree_ids(self.unit_a_id)
            self.assertIn(self.unit_a_id, ids)
            self.assertIn(self.unit_b_id, ids)
            self.assertIn(self.unit_c_id, ids)
            # Con chỉ trả về chính nó
            ids_c = unit_subtree_ids(self.unit_c_id)
            self.assertEqual(ids_c, [self.unit_c_id])

    def test_delegation_grants_process(self):
        """User B được ủy quyền từ User A (A có quyền xử lý công việc) → B được xử lý như A."""
        from datetime import date, timedelta
        from permissions import can_module
        with app.app_context():
            delegator = User(
                username='perm_test_delegator',
                fullname='Người ủy quyền',
                role_id=self.cat_role_id,  # Cán bộ CAT: task process
                is_active=True,
                must_change_password=False,
            )
            delegator.set_password('StrongPass1!')
            db.session.add(delegator)
            db.session.commit()
            delegator_id = delegator.id
            d = Delegation(
                delegator_id=delegator_id,
                delegatee_id=self.uid,
                module_code='task',
                from_date=date.today() - timedelta(days=1),
                to_date=date.today() + timedelta(days=7),
                is_active=True,
            )
            db.session.add(d)
            db.session.commit()
            try:
                import time as _time
                with app.test_request_context('/'):
                    from flask import session
                    session['uid'] = self.uid
                    session['username'] = 'perm_test_user'
                    session['role_id'] = self.cax_role_id
                    session['session_version'] = 0
                    session['last_active'] = _time.time()
                    # user được ủy quyền có quyền xử lý công việc của người ủy quyền
                    self.assertTrue(can_module('task', 'process'))
                    # nhưng không được cấp quyền module khác
                    self.assertFalse(can_module('notify', 'process'))
            finally:
                with app.app_context():
                    Delegation.query.filter_by(delegatee_id=self.uid).delete()
                    db.session.delete(db.session.get(User, delegator_id))
                    db.session.commit()

    def test_expired_delegation_no_longer_grants(self):
        from datetime import date, timedelta
        from permissions import can_module
        with app.app_context():
            delegator = User(
                username='perm_test_delegator2',
                fullname='Người ủy quyền 2',
                role_id=self.cat_role_id,
                is_active=True,
                must_change_password=False,
            )
            delegator.set_password('StrongPass1!')
            db.session.add(delegator)
            db.session.commit()
            delegator_id = delegator.id
            db.session.add(Delegation(
                delegator_id=delegator_id,
                delegatee_id=self.uid,
                module_code='task',
                from_date=date.today() - timedelta(days=10),
                to_date=date.today() - timedelta(days=3),
                is_active=True,
            ))
            db.session.commit()
            try:
                import time as _time
                with app.test_request_context('/'):
                    from flask import session
                    session['uid'] = self.uid
                    session['username'] = 'perm_test_user'
                    session['role_id'] = self.cax_role_id
                    session['session_version'] = 0
                    session['last_active'] = _time.time()
                    self.assertFalse(can_module('task', 'process'))
            finally:
                with app.app_context():
                    Delegation.query.filter_by(delegatee_id=self.uid).delete()
                    db.session.delete(db.session.get(User, delegator_id))
                    db.session.commit()

    def test_permission_log_written(self):
        from utils import log_permission_change
        with app.app_context():
            log_permission_change(
                'assign_role', 'user', 'perm_test_user',
                'role_id=1', user_id=self.uid, username='perm_test_user',
            )
            log = PermissionLog.query.filter_by(
                user_id=self.uid, action='assign_role', target_name='perm_test_user'
            ).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.target_type, 'user')

    def test_seed_units_from_users_links_unit_id(self):
        from utils import seed_units_from_users
        with app.app_context():
            user = db.session.get(User, self.uid)
            user.unit_id = None
            user.unit_key = 'unit_b_test'
            user.unit_area = 'CA huyện B (test)'
            db.session.commit()
            seed_units_from_users()
            user = db.session.get(User, self.uid)
            self.assertEqual(user.unit_id, self.unit_b_id)


if __name__ == '__main__':
    unittest.main()
