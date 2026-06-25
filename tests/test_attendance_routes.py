# -*- coding: utf-8 -*-
import os
import time
import unittest
from datetime import datetime

from app import app
from models import AttendanceConfig, AttendanceSubmission, CategoryGroup, CategoryItem, User, db
from security_utils.runtime_security import build_ip_network_hint, fingerprint_security_value


class AttendanceRouteTests(unittest.TestCase):
    TEST_USER_AGENT = 'AttendanceRouteTest/1.0'

    def setUp(self):
        self.client = app.test_client()

    def _issue_csrf_token(self):
        with self.client.session_transaction() as sess:
            sess['csrf_token'] = 'attendance-test-csrf'
            return sess['csrf_token']

    def _ensure_unit_test_items(self):
        with app.app_context():
            group = CategoryGroup.query.filter_by(code='contact_unit').first()
            if not group:
                group = CategoryGroup(code='contact_unit', name='Đơn vị', is_active=True, sort_order=0)
                db.session.add(group)
                db.session.flush()

            item_codes = ['attendance_test_unit_a', 'attendance_test_unit_b']
            items = []
            for index, code in enumerate(item_codes, start=1):
                item = CategoryItem.query.filter_by(group_id=group.id, code=code).first()
                if not item:
                    item = CategoryItem(
                        group_id=group.id,
                        code=code,
                        name=f'Đơn vị test {index}',
                        is_active=True,
                        sort_order=900 + index,
                    )
                    db.session.add(item)
            db.session.commit()
            for code in item_codes:
                item = CategoryItem.query.filter_by(group_id=group.id, code=code).first()
                items.append({
                    'id': item.id,
                    'name': item.name,
                    'unit_key': f'category_item:{item.id}',
                })
            return items

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
            sess['last_active'] = time.time()
            sess['login_nonce'] = 'attendance-test-session'
            sess['session_version'] = int(user.session_version or 0)
            sess['session_user_agent_hash'] = fingerprint_security_value(app.secret_key, 'user_agent', self.TEST_USER_AGENT)
            sess['session_ip_hint'] = build_ip_network_hint('127.0.0.1')
            sess['reauth_at'] = time.time()
        return user

    def test_attendance_page_renders_for_logged_in_admin(self):
        admin_user = self._login_admin_session()

        with app.app_context():
            config = AttendanceConfig(
                name='Test attendance route',
                mode='schedule',
                schedule_times_json='["08:00","11:00"]',
                active_weekdays_json='[0,1,2,3,4,5,6]',
                early_checkin_minutes=15,
                late_allow_minutes=45,
                is_active=True,
                target_type='role',
                target_role_id=admin_user.role_id,
            )
            db.session.add(config)
            db.session.commit()
            config_id = config.id

        try:
            response = self.client.get('/attendance', headers={'User-Agent': self.TEST_USER_AGENT})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Điểm danh'.encode('utf-8'), response.data)
            self.assertIn('Tạo nhiệm vụ điểm danh'.encode('utf-8'), response.data)
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
            self.assertIn('Điểm danh cần đăng nhập'.encode('utf-8'), response.data)
            self.assertIn('Đăng nhập'.encode('utf-8'), response.data)
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
            self.assertIn('Điểm danh cần đăng nhập'.encode('utf-8'), response.data)
            self.assertIn('Đăng nhập'.encode('utf-8'), response.data)
        finally:
            with app.app_context():
                AttendanceConfig.query.filter_by(id=config_id).delete()
                db.session.commit()

    def test_admin_can_create_update_and_delete_attendance_config(self):
        admin_user = self._login_admin_session()
        csrf_token = self._issue_csrf_token()

        create_response = self.client.post(
            '/attendance/config',
            data={
                'csrf_token': csrf_token,
                'name': 'CRUD attendance config',
                'day_start_time': '08:00',
                'day_end_time': '10:00',
                'interval_minutes': '30',
                'late_allow_minutes': '20',
                'target_type': 'role',
                'target_role_id': str(admin_user.role_id),
            },
            headers={'User-Agent': self.TEST_USER_AGENT},
        )
        self.assertEqual(create_response.status_code, 302)

        config_id = None
        try:
            with app.app_context():
                config = AttendanceConfig.query.filter_by(name='CRUD attendance config').order_by(AttendanceConfig.id.desc()).first()
                self.assertIsNotNone(config)
                config_id = config.id
                self.assertEqual(config.target_role_id, admin_user.role_id)

            update_response = self.client.post(
                '/attendance/config',
                data={
                    'csrf_token': csrf_token,
                    'config_id': str(config_id),
                    'name': 'CRUD attendance config updated',
                    'day_start_time': '09:30',
                    'day_end_time': '11:30',
                    'interval_minutes': '15',
                    'late_allow_minutes': '10',
                    'target_type': 'role',
                    'target_role_id': str(admin_user.role_id),
                },
                headers={'User-Agent': self.TEST_USER_AGENT},
            )
            self.assertEqual(update_response.status_code, 302)

            with app.app_context():
                updated = db.session.get(AttendanceConfig, config_id)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.name, 'CRUD attendance config updated')
                self.assertEqual(updated.mode, 'interval')
                self.assertEqual(updated.day_start_time, '09:30')
                self.assertEqual(updated.day_end_time, '11:30')
                self.assertEqual(updated.interval_minutes, 15)
                self.assertEqual(updated.late_allow_minutes, 10)
                self.assertEqual(updated.target_role_id, admin_user.role_id)

            delete_response = self.client.post(
                f'/attendance/config/{config_id}/delete',
                data={'csrf_token': csrf_token},
                headers={'User-Agent': self.TEST_USER_AGENT},
            )
            self.assertEqual(delete_response.status_code, 302)

            with app.app_context():
                self.assertIsNone(db.session.get(AttendanceConfig, config_id))
        finally:
            if config_id:
                with app.app_context():
                    AttendanceConfig.query.filter_by(id=config_id).delete()
                    db.session.commit()

    def test_admin_can_update_and_delete_attendance_submission(self):
        admin_user = self._login_admin_session()
        unit_items = self._ensure_unit_test_items()
        csrf_token = self._issue_csrf_token()

        config_id = None
        submission_id = None
        proof_path = None
        try:
            with app.app_context():
                config = AttendanceConfig(
                    name='Submission CRUD config',
                    mode='schedule',
                    schedule_times_json='["08:00"]',
                    active_weekdays_json='[0,1,2,3,4,5,6]',
                    early_checkin_minutes=15,
                    late_allow_minutes=45,
                    is_active=True,
                )
                db.session.add(config)
                db.session.flush()
                config_id = config.id

                proof_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'attendance_proofs', 'tests')
                os.makedirs(proof_dir, exist_ok=True)
                proof_filename = 'attendance_submission_crud.txt'
                proof_path = os.path.join('attendance_proofs', 'tests', proof_filename)
                with open(os.path.join(proof_dir, proof_filename), 'w', encoding='utf-8') as handle:
                    handle.write('proof')

                submission = AttendanceSubmission(
                    config_id=config.id,
                    user_id=admin_user.id,
                    unit_area=unit_items[0]['name'],
                    unit_key=unit_items[0]['unit_key'],
                    slot_key='2026-06-02_08:00',
                    slot_label='08:00',
                    slot_date=datetime.now().date(),
                    due_at=datetime.now(),
                    window_start_at=datetime.now(),
                    window_end_at=datetime.now(),
                    proof_filename=proof_filename,
                    proof_path=proof_path,
                    note='Initial submission note',
                    submitted_at=datetime.now(),
                )
                db.session.add(submission)
                db.session.commit()
                submission_id = submission.id

            update_response = self.client.post(
                f'/attendance/submission/{submission_id}/update',
                data={
                    'csrf_token': csrf_token,
                    'unit_key': unit_items[1]['unit_key'],
                    'note': 'Updated submission note',
                },
                headers={'User-Agent': self.TEST_USER_AGENT},
            )
            self.assertEqual(update_response.status_code, 302)

            with app.app_context():
                updated = db.session.get(AttendanceSubmission, submission_id)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.unit_key, unit_items[1]['unit_key'])
                self.assertEqual(updated.unit_area, unit_items[1]['name'])
                self.assertEqual(updated.note, 'Updated submission note')

            delete_response = self.client.post(
                f'/attendance/submission/{submission_id}/delete',
                data={'csrf_token': csrf_token},
                headers={'User-Agent': self.TEST_USER_AGENT},
            )
            self.assertEqual(delete_response.status_code, 302)

            with app.app_context():
                self.assertIsNone(db.session.get(AttendanceSubmission, submission_id))
            self.assertFalse(os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], proof_path)))
        finally:
            with app.app_context():
                if submission_id:
                    AttendanceSubmission.query.filter_by(id=submission_id).delete()
                if config_id:
                    AttendanceConfig.query.filter_by(id=config_id).delete()
                db.session.commit()
            if proof_path:
                absolute_proof = os.path.join(app.config['UPLOAD_FOLDER'], proof_path)
                if os.path.exists(absolute_proof):
                    os.remove(absolute_proof)


if __name__ == '__main__':
    unittest.main()
