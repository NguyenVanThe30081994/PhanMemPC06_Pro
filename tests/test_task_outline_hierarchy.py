# -*- coding: utf-8 -*-
"""
Kiểm thử mô hình phân cấp tài khoản & thẩm quyền giao việc theo chính quyền 2 cấp:
1. Cấp Tỉnh (Sở/Ban/Ngành): Được giao việc xuống Cấp Xã và giao việc ngang hàng giữa các Sở.
2. Cấp Xã (UBND Xã, Công an Xã): Chỉ được giao việc nội bộ đơn vị hoặc phối hợp đồng cấp Xã.
   TUYỆT ĐỐI KHÔNG ĐƯỢC giao việc cho Cấp Tỉnh / Sở (bị chặn 403).
3. /api/outline-assignees tự động lọc danh bạ và preset theo cấp của người gọi.
"""
import json
import unittest

from app import app
from models import (
    AppRole,
    Task,
    TaskAssignment,
    TaskItem,
    TaskParticipant,
    TaskSubmission,
    Unit,
    User,
    db,
)


class TaskOutlineHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created_unit_ids = []
        self.created_user_ids = []
        self.created_task_ids = []
        self.csrf_token = "test-hierarchy-csrf"

        with app.app_context():
            # Đảm bảo vai trò
            self.role_admin_donvi = AppRole.query.filter_by(name='Quản trị đơn vị').first()
            if not self.role_admin_donvi:
                self.role_admin_donvi = AppRole(
                    name='Quản trị đơn vị',
                    perms=json.dumps({'p_dash': 1, 'p_task': 1, 'p_task_process': 1, 'p_user': 1})
                )
                db.session.add(self.role_admin_donvi)
                db.session.commit()

            # Tạo đơn vị Tỉnh & Xã
            self.unit_so = Unit(code='so_test_hier', name='Sở Test Phân Cấp', level='province', is_active=True)
            self.unit_xa = Unit(code='ubnd_xa_test_hier', name='UBND Xã Test Phân Cấp', level='commune', is_active=True)
            db.session.add_all([self.unit_so, self.unit_xa])
            db.session.commit()
            self.created_unit_ids.extend([self.unit_so.id, self.unit_xa.id])

            # Tạo User Tỉnh & User Xã
            self.user_tinh = User(
                username='user_so_test',
                fullname='Cán bộ Sở Test',
                unit_id=self.unit_so.id,
                unit_area=self.unit_so.name,
                unit_key=self.unit_so.code,
                role_id=self.role_admin_donvi.id,
                is_active=True,
                must_change_password=False
            )
            self.user_tinh.set_password('TuyenQuang@2026')

            self.user_xa = User(
                username='user_xa_test',
                fullname='Cán bộ Xã Test',
                unit_id=self.unit_xa.id,
                unit_area=self.unit_xa.name,
                unit_key=self.unit_xa.code,
                role_id=self.role_admin_donvi.id,
                is_active=True,
                must_change_password=False
            )
            self.user_xa.set_password('TuyenQuang@2026')

            db.session.add_all([self.user_tinh, self.user_xa])
            db.session.commit()
            self.created_user_ids.extend([self.user_tinh.id, self.user_xa.id])

    def tearDown(self):
        with app.app_context():
            for tid in self.created_task_ids:
                TaskAssignment.query.filter_by(task_id=tid).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=tid).delete()
                TaskAssignment.query.filter_by(task_id=tid).delete()
                TaskParticipant.query.filter_by(task_id=tid).delete()
                TaskItem.query.filter_by(task_id=tid).delete()
                Task.query.filter_by(id=tid).delete()
            for uid in self.created_user_ids:
                User.query.filter_by(id=uid).delete()
            for unid in self.created_unit_ids:
                Unit.query.filter_by(id=unid).delete()
            db.session.commit()

    def _login(self, user):
        with self.client.session_transaction() as sess:
            sess['uid'] = user.id
            sess['username'] = user.username
            sess['fullname'] = user.fullname
            sess['role_id'] = user.role_id
            sess['session_version'] = user.session_version or 0
            sess['csrf_token'] = self.csrf_token

    def test_commune_assignees_excludes_province(self):
        """Tài khoản cấp Xã chỉ nhìn thấy cấp Xã, không thấy các Sở/Tỉnh."""
        self._login(self.user_xa)
        res = self.client.get('/api/outline-assignees')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertEqual(data.get('caller_level'), 'commune')
        # Danh sách đơn vị không được chứa bất kỳ Sở nào
        for u in data.get('units') or []:
            self.assertNotEqual(u.get('group'), 'province', f"Commune sees province unit: {u}")
        # Danh sách user không được chứa cán bộ Tỉnh
        for u in data.get('users') or []:
            self.assertNotEqual(u.get('group'), 'province', f"Commune sees province user: {u}")
        # Presets không có khối 19 sở hay toàn tỉnh
        preset_ids = [p['id'] for p in data.get('presets') or []]
        self.assertNotIn('toan_tinh', preset_ids)
        self.assertNotIn('khoi_so_nganh', preset_ids)

    def test_province_assignees_includes_all(self):
        """Tài khoản cấp Tỉnh nhìn thấy cả Sở và Xã."""
        self._login(self.user_tinh)
        res = self.client.get('/api/outline-assignees')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertEqual(data.get('caller_level'), 'province')
        preset_ids = [p['id'] for p in data.get('presets') or []]
        self.assertIn('toan_tinh', preset_ids)
        self.assertIn('khoi_so_nganh', preset_ids)
        self.assertIn('khoi_ubnd_xa', preset_ids)

    def test_commune_cannot_assign_to_province(self):
        """Tài khoản cấp Xã cố tình giao việc cho Sở/Tỉnh sẽ bị chặn 403."""
        self._login(self.user_xa)
        payload = {
            'title': 'Xã giao việc cho Tỉnh (Vi phạm phân cấp)',
            'tree': {
                'title': 'Đề cương test',
                'sections': [
                    {'id': 'sec-1', 'label': 'I', 'text': 'Phần Một', 'type': 'section', 'children': [
                        {'id': 'm-1', 'label': '1.1', 'text': 'Nhiệm vụ', 'type': 'h2', 'children': []}
                    ]}
                ]
            },
            'assignments': {
                'm-1': {
                    'ids': [self.user_tinh.id],  # Cố tình gán cán bộ Sở
                    'labels': [self.user_tinh.fullname]
                }
            }
        }
        res = self.client.post(
            '/api/create-outline-task',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-CSRF-Token': self.csrf_token}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn('Thẩm quyền cấp Xã không thể giao việc cho đơn vị Cấp Tỉnh', res.get_json().get('error', ''))

    def test_province_can_assign_to_province_and_commune(self):
        """Tài khoản cấp Tỉnh được phép giao việc cho Sở khác hoặc cho Xã."""
        self._login(self.user_tinh)
        payload = {
            'title': 'Tỉnh giao việc xuống Xã',
            'tree': {
                'title': 'Đề cương test',
                'sections': [
                    {'id': 'sec-1', 'label': 'I', 'text': 'Phần Một', 'type': 'section', 'children': [
                        {'id': 'm-1', 'label': '1.1', 'text': 'Nhiệm vụ', 'type': 'h2', 'children': []}
                    ]}
                ]
            },
            'assignments': {
                'm-1': {
                    'ids': [self.user_xa.id],  # Gán cho cán bộ Xã
                    'labels': [self.user_xa.fullname]
                }
            }
        }
        res = self.client.post(
            '/api/create-outline-task',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-CSRF-Token': self.csrf_token}
        )
        self.assertEqual(res.status_code, 200)
        task_id = res.get_json().get('task_id')
        self.assertIsNotNone(task_id)
        self.created_task_ids.append(task_id)


if __name__ == '__main__':
    unittest.main()
