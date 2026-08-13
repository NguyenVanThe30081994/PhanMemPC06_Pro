# -*- coding: utf-8 -*-
import glob
import os
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import quote

from openpyxl import Workbook
from flask import session
from sqlalchemy import text
from app import app
from models import (
    Task,
    TaskAssignment,
    TaskItem,
    TaskParticipant,
    TaskSubmission,
    User,
    db,
)
from routes.tasks import (
    _build_child_task_report_dashboard,
    _extract_submission_numeric_value,
    _query_task_scope,
    _sync_task_runtime_models,
    _task_runtime_bridge_needs_sync,
)
from utils import has_module_permission, is_unit_match, normalize_permission_payload


class ProposalRuntimeTests(unittest.TestCase):
    def _login_admin_client(self):
        with app.app_context():
            user = User.query.filter_by(username='admin').first() or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test.")
        client = app.test_client()
        with client.session_transaction() as sess:
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
            sess['session_version'] = int(user.session_version or 0)
            sess['csrf_token'] = 'proposal-runtime-test-csrf'
            sess['last_active'] = datetime.now().timestamp()
            sess['login_nonce'] = 'test-session-token'
        return client, user

    def test_permission_normalization_supports_view_process_exec(self):
        legacy_payload = {
            "p_task_lead": 1,
            "p_news_exec": 1,
            "p_contact_view": 1,
        }
        normalized = normalize_permission_payload(legacy_payload, is_admin=False, role_name="Cán bộ PC06")

        self.assertTrue(has_module_permission(normalized, "task", "view"))
        self.assertTrue(has_module_permission(normalized, "task", "process"))
        self.assertFalse(has_module_permission(normalized, "task", "exec"))

        self.assertTrue(has_module_permission(normalized, "news", "view"))
        self.assertTrue(has_module_permission(normalized, "news", "exec"))
        self.assertFalse(has_module_permission(normalized, "news", "process"))

        self.assertTrue(has_module_permission(normalized, "contact", "view"))
        self.assertFalse(has_module_permission(normalized, "contact", "process"))

    def test_task_runtime_backfill_creates_task_items_participants_submissions(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test runtime bridge.")

            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            task = Task(
                title=f"[TEST] runtime bridge {now_token}",
                content="Task phục vụ test backfill runtime",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            assignment = TaskAssignment(
                task_id=task.id,
                user_id=user.id,
                status="Đang thực hiện",
                report_payload_json=json.dumps({"narrative": "Đã cập nhật dữ liệu test."}, ensure_ascii=False),
                updated_at=datetime.now(),
            )
            db.session.add(assignment)
            child_task = Task(
                category=task.category,
                domain=task.domain,
                title=f"[TEST] child item {now_token}",
                content="Đầu mục thực thi test",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Trung bình",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                parent_task_id=task.id,
                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "meta": {
                            "kind": "simple_child_task",
                            "report_kind": "number",
                            "attachment_required": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
            )
            db.session.add(child_task)
            db.session.commit()

            try:
                task = db.session.get(Task, task.id)
                _sync_task_runtime_models(task)
                db.session.commit()

                task_item_count = TaskItem.query.filter_by(task_id=task.id).count()
                participant_count = _query_task_scope(TaskParticipant, task).filter(
                    TaskParticipant.participant_type == "executor",
                    TaskParticipant.is_active.is_(True),
                ).count()
                submission_count = _query_task_scope(TaskSubmission, task).count()

                self.assertEqual(task_item_count, 1)
                self.assertEqual(participant_count, 1)
                self.assertEqual(submission_count, 1)
                self.assertFalse(_task_runtime_bridge_needs_sync(task))
            finally:
                TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskSubmission.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskParticipant.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                Task.query.filter_by(parent_task_id=task.id).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                Task.query.filter_by(id=task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_task_runtime_backfill_skips_assignment_without_user(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test runtime bridge.")
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            task = Task(
                title=f"[TEST] orphan assignment {now_token}",
                content="Task phục vụ test assignment lỗi",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            broken_assignment = TaskAssignment(
                task_id=task.id,
                user_id=None,
                status="Chưa tiếp nhận",
                updated_at=datetime.now(),
            )
            db.session.add(broken_assignment)
            db.session.commit()

            try:
                task = db.session.get(Task, task.id)
                _sync_task_runtime_models(task)
                db.session.commit()
                submission_count = _query_task_scope(TaskSubmission, task).count()
                self.assertEqual(submission_count, 0)
                self.assertFalse(_task_runtime_bridge_needs_sync(task))
            finally:
                TaskSubmission.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskParticipant.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                Task.query.filter_by(id=task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_task_list_stays_read_only_but_task_detail_lazy_repairs_runtime(self):
        client, user = self._login_admin_client()
        with app.app_context():
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
            task = Task(
                title=f"[TEST] lazy repair {now_token}",
                content="Task phục vụ test lazy repair runtime",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            assignment = TaskAssignment(
                task_id=task.id,
                user_id=user.id,
                status="Đang thực hiện",
                report_payload_json=json.dumps({"narrative": "Đã có báo cáo cũ."}, ensure_ascii=False),
                updated_at=datetime.now(),
            )
            db.session.add(assignment)
            db.session.commit()
            task_id = task.id

        try:
            list_response = client.get("/tasks")
            self.assertEqual(list_response.status_code, 200)
            with app.app_context():
                task = db.session.get(Task, task_id)
                self.assertEqual(_query_task_scope(TaskParticipant, task).count(), 0)
                self.assertEqual(_query_task_scope(TaskSubmission, task).count(), 0)
                self.assertTrue(_task_runtime_bridge_needs_sync(task))

            detail_response = client.get(f"/tasks/{task_id}")
            self.assertEqual(detail_response.status_code, 200)
            with app.app_context():
                task = db.session.get(Task, task_id)
                self.assertEqual(_query_task_scope(TaskParticipant, task).count(), 1)
                self.assertEqual(_query_task_scope(TaskSubmission, task).count(), 1)
                self.assertFalse(_task_runtime_bridge_needs_sync(task))
        finally:
            with app.app_context():
                TaskSubmission.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                TaskParticipant.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                TaskItem.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                Task.query.filter_by(id=task_id).delete(synchronize_session=False)
                db.session.commit()

    def test_child_task_report_dashboard_classifies_progress_and_quality(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test dashboard task con.")
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            parent_task = Task(
                title=f"[TEST] child dashboard {now_token}",
                content="Task cha phục vụ test dashboard",
                deadline=datetime.now().date() + timedelta(days=3),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                created_at=datetime.now(),
            )
            db.session.add(parent_task)
            db.session.commit()

            child_specs = [
                ("Đầu việc 1", datetime.now().date() + timedelta(days=1), "Hoàn thành", {"narrative": "Đã báo cáo"}, datetime.now()),
                ("Đầu việc 2", datetime.now().date() - timedelta(days=1), "Đang thực hiện", None, datetime.now()),
                ("Đầu việc 3", datetime.now().date() + timedelta(days=2), "Chưa tiếp nhận", None, datetime.now()),
            ]
            child_ids = []
            try:
                for title, deadline, status, payload, updated_at in child_specs:
                    child_task = Task(
                        title=f"[TEST] {title} {now_token}",
                        content="Task con phục vụ test dashboard",
                        deadline=deadline,
                        author_id=user.id,
                        author_name=user.fullname,
                        priority="Trung bình",
                        task_type="Công việc thường xuyên",
                        initial_status=status,
                        parent_task_id=parent_task.id,
                        created_at=datetime.now(),
                    )
                    db.session.add(child_task)
                    db.session.flush()
                    assignment = TaskAssignment(
                        task_id=child_task.id,
                        user_id=user.id,
                        status=status,
                        report_payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
                        updated_at=updated_at,
                    )
                    db.session.add(assignment)
                    child_ids.append(child_task.id)
                db.session.commit()

                child_tasks = Task.query.filter(Task.id.in_(child_ids)).order_by(Task.id.asc()).all()
                dashboard = _build_child_task_report_dashboard(child_tasks)

                self.assertEqual(dashboard["total_units"], 1)
                self.assertEqual(dashboard["total_child_tasks"], 3)
                self.assertEqual(dashboard["total_overdue_tasks"], 1)
                self.assertEqual(dashboard["progress_groups"][1]["count"], 1)
                self.assertEqual(dashboard["quality_groups"][1]["count"], 1)

                unit_row = dashboard["unit_rows"][0]
                self.assertEqual(unit_row["progress_code"], "reporting_in_progress")
                self.assertEqual(unit_row["quality_code"], "partial_overdue")
                self.assertEqual(unit_row["child_task_count"], 3)
                self.assertEqual(unit_row["missing_count"], 2)
                self.assertEqual(unit_row["overdue_count"], 1)
            finally:
                TaskAssignment.query.filter(TaskAssignment.task_id.in_(child_ids)).delete(synchronize_session=False)
                Task.query.filter(Task.id.in_(child_ids)).delete(synchronize_session=False)
                Task.query.filter_by(id=parent_task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_numeric_submission_extractor_returns_none_for_blank_value(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test numeric extractor.")
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            task = Task(
                title=f"[TEST] numeric blank {now_token}",
                content="Task phục vụ test payload số rỗng",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "meta": {
                            "kind": "simple_child_task",
                            "report_kind": "number",
                            "attachment_required": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            try:
                payload = {"values": {"child_task_number": None}}
                self.assertIsNone(_extract_submission_numeric_value(task, payload))
            finally:
                Task.query.filter_by(id=task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_delete_child_task_redirects_back_to_parent_detail(self):
        client, user = self._login_admin_client()
        with app.app_context():
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
            parent_task = Task(
                title=f"[TEST] parent redirect {now_token}",
                content="Task cha phục vụ test redirect",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                created_at=datetime.now(),
            )
            db.session.add(parent_task)
            db.session.commit()

            child_task = Task(
                title=f"[TEST] child redirect {now_token}",
                content="Task con phục vụ test redirect",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                parent_task_id=parent_task.id,
                created_at=datetime.now(),
            )
            db.session.add(child_task)
            db.session.commit()
            parent_id = parent_task.id
            child_id = child_task.id

        try:
            response = client.post(
                f"/tasks/{child_id}/delete",
                data={"csrf_token": "proposal-runtime-test-csrf"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers.get("Location", "").endswith(f"/tasks/{parent_id}"))
        finally:
            with app.app_context():
                Task.query.filter_by(parent_task_id=parent_id).delete(synchronize_session=False)
                Task.query.filter_by(id=parent_id).delete(synchronize_session=False)
                db.session.commit()

    def test_session_timeout_uses_configured_lifetime_and_renders_session_scoped_activity_key(self):
        client, user = self._login_admin_client()
        with client.session_transaction() as sess:
            sess['last_active'] = datetime.now().timestamp() - 1900
            sess['login_nonce'] = 'scoped-activity-key'

        response = client.get("/tasks")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(f'const SESSION_MARKER = "{user.id}:scoped-activity-key";', html)
        self.assertIn("pc06_last_activity:${SESSION_MARKER}", html)
        self.assertNotIn("const SYNC_KEY = 'pc06_last_activity';", html)

    def test_is_unit_match_accepts_cax_abbreviation_for_xa_units(self):
        self.assertTrue(is_unit_match("Xã Yên Minh", "CAX Yên Minh"))
