# -*- coding: utf-8 -*-
import unittest
from datetime import datetime

from app import app
from models import AttendanceConfig, User, db


class AttendanceRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def _login_admin_session(self):
        with app.app_context():
            user = User.query.filter_by(username='admin').first() or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một tài khoản để test route điểm danh.")

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
            sess['is_admin'] = True
            sess['last_active'] = datetime.now().timestamp()
            sess['login_nonce'] = 'attendance-test-session'
        return user

    def test_attendance_page_renders_for_logged_in_admin(self):
        self._login_admin_session()

        with app.app_context():
            config = AttendanceConfig(
                name='Test attendance route',
                mode='schedule',
                schedule_times_json='["08:00","11:00"]',
                active_weekdays_json='[0,1,2,3,4,5,6]',
                early_checkin_minutes=15,
                late_allow_minutes=45,
                is_active=True,
            )
            db.session.add(config)
            db.session.commit()
            config_id = config.id

        try:
            response = self.client.get('/attendance')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Điểm danh'.encode('utf-8'), response.data)
            self.assertIn('ảnh minh chứng'.encode('utf-8'), response.data)
        finally:
            with app.app_context():
                AttendanceConfig.query.filter_by(id=config_id).delete()
                db.session.commit()

    def test_attendance_page_renders_public_mode_without_login(self):
        with app.app_context():
            config = AttendanceConfig(
                name='Public attendance test',
                mode='schedule',
                schedule_times_json='["08:00","11:00"]',
                active_weekdays_json='[0,1,2,3,4,5,6]',
                early_checkin_minutes=15,
                late_allow_minutes=45,
                is_active=True,
            )
            db.session.add(config)
            db.session.commit()
            config_id = config.id

        try:
            response = self.client.get('/attendance')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Không cần đăng nhập'.encode('utf-8'), response.data)
            self.assertIn('Chọn đơn vị'.encode('utf-8'), response.data)
        finally:
            with app.app_context():
                AttendanceConfig.query.filter_by(id=config_id).delete()
                db.session.commit()

    def test_public_attendance_url_renders_without_login(self):
        with app.app_context():
            config = AttendanceConfig(
                name='Direct public attendance test',
                mode='schedule',
                schedule_times_json='["08:00","11:00"]',
                active_weekdays_json='[0,1,2,3,4,5,6]',
                early_checkin_minutes=15,
                late_allow_minutes=45,
                is_active=True,
            )
            db.session.add(config)
            db.session.commit()
            config_id = config.id

        try:
            response = self.client.get('/diem-danh')
            self.assertEqual(response.status_code, 200)
            self.assertIn('/diem-danh'.encode('utf-8'), response.data)
            self.assertIn('Điểm danh trực tiếp theo đơn vị'.encode('utf-8'), response.data)
        finally:
            with app.app_context():
                AttendanceConfig.query.filter_by(id=config_id).delete()
                db.session.commit()


if __name__ == '__main__':
    unittest.main()
