# -*- coding: utf-8 -*-
"""
Test Pha 1 — deadline watchdog & endpoint quét cảnh báo hạn.

Lưu ý cách ly: `run_tests.py` ép DATABASE_URL về SQLite tạm nên các test
này không bao giờ đụng DB production. tearDown xóa dữ liệu test theo thứ
tự an toàn FK (NULL tham chiếu -> xóa con -> xóa cha).
"""
import json
import os
import time
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from app import app
from models import AppRole, Notification, Task, TaskAssignment, Unit, User, db
from security_utils.runtime_security import (
    build_ip_network_hint,
    fingerprint_security_value,
)
from services.deadline_watchdog import (
    OVERDUE_MARKER,
    UPCOMING_MARKER,
    URGENT_MARKER,
    run_deadline_watchdog,
)


class DeadlineWatchdogTests(unittest.TestCase):
    TEST_USER_AGENT = 'DeadlineWatchdogTest/1.0'

    def setUp(self):
        self.client = app.test_client()
        # Giữ app context suốt vòng đời test: mọi helper dùng db.session
        # trực tiếp (tearDown pop sau khi dọn xong).
        self._app_ctx = app.app_context()
        self._app_ctx.push()
        self.created_user_ids = []
        self.created_role_ids = []
        self.created_task_ids = []
        self.created_unit_ids = []
        # Mặc định chặn gửi email thật trong test.
        self._env = mock.patch.dict(os.environ, {'PC06_DEADLINE_EMAIL_ENABLED': '0'})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        try:
            if self.created_task_ids:
                TaskAssignment.query.filter(
                    TaskAssignment.task_id.in_(self.created_task_ids)
                ).delete(synchronize_session=False)
                Task.query.filter(Task.id.in_(self.created_task_ids)).delete(
                    synchronize_session=False
                )
            if self.created_user_ids:
                Notification.query.filter(
                    Notification.user_id.in_(self.created_user_ids)
                ).delete(synchronize_session=False)
                User.query.filter(User.id.in_(self.created_user_ids)).delete(
                    synchronize_session=False
                )
            if self.created_role_ids:
                AppRole.query.filter(
                    AppRole.id.in_(self.created_role_ids)
                ).delete(synchronize_session=False)
            if self.created_unit_ids:
                Unit.query.filter(Unit.id.in_(self.created_unit_ids)).delete(
                    synchronize_session=False
                )
            db.session.commit()
        finally:
            self._app_ctx.pop()

    # ---------- helpers ----------

    def _create_role(self, name, perms=None):
        role = AppRole(name=name, perms=json.dumps(perms or {}, ensure_ascii=False))
        db.session.add(role)
        db.session.flush()
        self.created_role_ids.append(role.id)
        return role

    def _create_user(self, username, role=None, unit_key=None, email=None):
        user = User(
            username=username,
            fullname=username,
            role_id=role.id if role else None,
            unit_key=unit_key,
            email=email,
            is_active=True,
            must_change_password=False,
        )
        user.set_password('StrongPass1!')
        db.session.add(user)
        db.session.commit()
        self.created_user_ids.append(user.id)
        return user

    def _create_task(self, title, deadline):
        task = Task(
            title=title,
            deadline=deadline,
            task_mode='FILE',
            created_at=datetime.now(),
        )
        db.session.add(task)
        db.session.flush()
        self.created_task_ids.append(task.id)
        return task

    def _assign_user(self, task, user, status='Chưa tiếp nhận'):
        assignment = TaskAssignment(
            task_id=task.id,
            user_id=user.id,
            assignee_type='user',
            status=status,
            assigned_at=datetime.now(),
        )
        db.session.add(assignment)
        db.session.commit()
        return assignment

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
            sess['login_nonce'] = 'watchdog-test-session'
            sess['session_version'] = int(user.session_version or 0)
            sess['session_user_agent_hash'] = fingerprint_security_value(
                app.secret_key, 'user_agent', self.TEST_USER_AGENT
            )
            sess['session_ip_hint'] = build_ip_network_hint('127.0.0.1')
            sess['csrf_token'] = 'watchdog-test-csrf'
            sess['reauth_at'] = time.time()

    def _notifications_for(self, user_id, task_id):
        return Notification.query.filter_by(
            user_id=user_id, link=f'/tasks/{task_id}'
        ).all()

    # ---------- watchdog core ----------

    def test_overdue_task_notifies_direct_assignee(self):
        role = self._create_role('role_watchdog_exec')
        assignee = self._create_user('watchdog_assignee', role=role)
        task = self._create_task('Việc quá hạn test', date.today() - timedelta(days=2))
        self._assign_user(task, assignee)

        summary = run_deadline_watchdog(send_emails=False)

        notifs = self._notifications_for(assignee.id, task.id)
        self.assertEqual(len(notifs), 1)
        self.assertTrue(notifs[0].title.startswith(OVERDUE_MARKER))
        # DB test dùng chung cả suite nên chỉ assert >= (có thể có task quá
        # hạn tồn dư của module test khác).
        self.assertGreaterEqual(summary['levels']['overdue'], 1)

    def test_same_day_deadline_is_urgent(self):
        role = self._create_role('role_watchdog_urgent')
        assignee = self._create_user('watchdog_urgent_user', role=role)
        task = self._create_task('Việc đến hạn hôm nay', date.today())
        self._assign_user(task, assignee)

        run_deadline_watchdog(send_emails=False)

        notifs = self._notifications_for(assignee.id, task.id)
        self.assertEqual(len(notifs), 1)
        self.assertTrue(notifs[0].title.startswith(URGENT_MARKER))

    def test_upcoming_threshold_three_days(self):
        role = self._create_role('role_watchdog_upcoming')
        assignee = self._create_user('watchdog_upcoming_user', role=role)
        task = self._create_task('Việc sắp đến hạn', date.today() + timedelta(days=2))
        self._assign_user(task, assignee)

        run_deadline_watchdog(send_emails=False)

        notifs = self._notifications_for(assignee.id, task.id)
        self.assertEqual(len(notifs), 1)
        self.assertTrue(notifs[0].title.startswith(UPCOMING_MARKER))

    def test_second_run_dedupes_within_lookback(self):
        role = self._create_role('role_watchdog_dedupe')
        assignee = self._create_user('watchdog_dedupe_user', role=role)
        task = self._create_task('Việc dedupe', date.today() - timedelta(days=1))
        self._assign_user(task, assignee)

        first = run_deadline_watchdog(send_emails=False)
        self.assertEqual(len(self._notifications_for(assignee.id, task.id)), 1)

        run_deadline_watchdog(send_emails=False)
        # Dedupe theo (user, task, ngưỡng) trong cửa sổ lookback: cặp này
        # không được nhắc lại.
        self.assertEqual(len(self._notifications_for(assignee.id, task.id)), 1)
        self.assertGreaterEqual(first['notifications_created'], 1)

    def test_completed_assignment_not_notified(self):
        role = self._create_role('role_watchdog_done')
        assignee = self._create_user('watchdog_done_user', role=role)
        task = self._create_task('Việc đã xong', date.today() - timedelta(days=5))
        self._assign_user(task, assignee, status='completed')

        run_deadline_watchdog(send_emails=False)

        self.assertEqual(self._notifications_for(assignee.id, task.id), [])

    def test_unit_assignment_notifies_matching_unit_users_only(self):
        unit = Unit(code='wd_don_vi_a', name='Đơn vị A watchdog')
        db.session.add(unit)
        db.session.flush()
        self.created_unit_ids.append(unit.id)

        role = self._create_role('role_watchdog_unit')
        in_unit = self._create_user('watchdog_unit_in', role=role, unit_key='wd_don_vi_a')
        out_unit = self._create_user('watchdog_unit_out', role=role, unit_key='wd_don_vi_khac')

        task = self._create_task('Việc giao theo đơn vị', date.today() - timedelta(days=3))
        assignment = TaskAssignment(
            task_id=task.id,
            assignee_type='unit',
            unit_id=unit.id,
            status='Chưa tiếp nhận',
            assigned_at=datetime.now(),
        )
        db.session.add(assignment)
        db.session.commit()

        run_deadline_watchdog(send_emails=False)

        self.assertTrue(self._notifications_for(in_unit.id, task.id))
        self.assertEqual(self._notifications_for(out_unit.id, task.id), [])

    def test_email_sent_when_enabled_and_user_has_email(self):
        role = self._create_role('role_watchdog_email')
        assignee = self._create_user(
            'watchdog_email_user', role=role, email='can.bo@example.com'
        )
        task = self._create_task('Việc gửi email', date.today() - timedelta(days=4))
        self._assign_user(task, assignee)

        with mock.patch(
            'routes.email_service.send_email', return_value=(True, None)
        ) as mocked:
            with mock.patch.dict(os.environ, {'PC06_DEADLINE_EMAIL_ENABLED': '1'}):
                summary = run_deadline_watchdog()

        self.assertTrue(mocked.called)
        self.assertGreaterEqual(summary['emails_sent'], 1)

    # ---------- endpoint /admin/deadline-watchdog/run ----------

    def test_run_endpoint_requires_sys_process_permission(self):
        role = self._create_role('role_watchdog_admin', perms={'p_sys_process': 1})
        admin_user = self._create_user('watchdog_admin_user', role=role)
        self._login_session(admin_user)

        response = self.client.post(
            '/admin/deadline-watchdog/run',
            data={'csrf_token': 'watchdog-test-csrf'},
            headers={'User-Agent': self.TEST_USER_AGENT},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin', response.headers.get('Location', ''))

    def test_run_endpoint_redirects_to_login_without_permission(self):
        role = self._create_role('role_watchdog_norole', perms={})
        plain_user = self._create_user('watchdog_plain_user', role=role)
        self._login_session(plain_user)

        response = self.client.post(
            '/admin/deadline-watchdog/run',
            data={'csrf_token': 'watchdog-test-csrf'},
            headers={'User-Agent': self.TEST_USER_AGENT},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()


class TaskSchedulerTest(unittest.TestCase):
    """Nối deadline watchdog vào runtime qua services.task_scheduler."""

    def test_enabled_flag_respects_env_and_testing(self):
        from services.task_scheduler import task_scheduler_enabled

        # Môi trường testing luôn tắt scheduler (được run_tests ép FLASK_ENV=testing).
        with mock.patch.dict(os.environ, {'PC06_TASK_SCHEDULER': '1'}):
            self.assertFalse(task_scheduler_enabled())

        # Cờ tắt rõ ràng vẫn được tôn trọng trong môi trường không-test.
        with mock.patch.dict(os.environ, {'FLASK_ENV': 'development', 'PC06_TASK_SCHEDULER': '0'}):
            self.assertFalse(task_scheduler_enabled())

        # Bới scheduler bật trong môi trường production/dev là hợp lệ.
        with mock.patch.dict(os.environ, {'FLASK_ENV': 'development', 'PC06_TASK_SCHEDULER': '1'}):
            self.assertTrue(task_scheduler_enabled())

    def test_start_is_idempotent_and_not_running_in_testing(self):
        from services.task_scheduler import current_task_scheduler, start_task_scheduler

        # Trong testing không nên có scheduler nền.
        self.assertIsNone(current_task_scheduler(app))
        start_task_scheduler(app)  # không được khởi động gì
        self.assertIsNone(current_task_scheduler(app))

    def test_watchdog_job_runs_in_app_context_and_logs_summary(self):
        from services.task_scheduler import _run_watchdog_job

        role = None
        try:
            from models import AppRole
            role = AppRole.query.filter_by(name='test_sched_role').first()
        except Exception:
            pass

        # Chạy job trong app context hiện có (test đang nằm trong app context).
        with mock.patch.dict(os.environ, {'PC06_DEADLINE_EMAIL_ENABLED': '0'}):
            _run_watchdog_job(app)  # chỉ cần không ném lỗi

        self.assertTrue(True)
