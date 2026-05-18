# -*- coding: utf-8 -*-
import json
import unittest
from datetime import date, datetime

from app import app
from models import ReportTemplate, Task, TaskAssignment, TaskItem, TaskParticipant, TaskReportLink, TaskSubmission, User, db
from routes.tasks import _query_task_scope, _sync_task_runtime_models, _task_runtime_bridge_needs_sync
from utils import has_module_permission, normalize_permission_payload


class ProposalRuntimeTests(unittest.TestCase):
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

    def test_task_runtime_backfill_creates_task_items_participants_submissions_and_links(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test runtime bridge.")

            template = ReportTemplate.query.order_by(ReportTemplate.id.asc()).first()
            linked_template_ids = [template.id] if template else []
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
                linked_report_templates_json=json.dumps(linked_template_ids, ensure_ascii=False) if linked_template_ids else None,
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
                report_link_count = _query_task_scope(TaskReportLink, task).count()

                self.assertEqual(task_item_count, 1)
                self.assertEqual(participant_count, 1)
                self.assertEqual(submission_count, 1)
                self.assertEqual(report_link_count, len(linked_template_ids))
                self.assertFalse(_task_runtime_bridge_needs_sync(task))
            finally:
                TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskSubmission.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskParticipant.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskReportLink.query.filter_by(task_id=task.id).delete(synchronize_session=False)
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
                TaskReportLink.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                Task.query.filter_by(id=task.id).delete(synchronize_session=False)
                db.session.commit()


if __name__ == "__main__":
    unittest.main()
