# -*- coding: utf-8 -*-
import json
import uuid
import unittest
from datetime import datetime
from unittest.mock import patch

from app import app
from models import AppRole, Task, TaskAssignment, TaskComment, TaskFormField, TaskSubmission, User, db


FORM_PAYLOAD = {
    "formId": "abc123FORM",
    "info": {"title": "Thu thập báo cáo nhanh"},
    "revisionId": "rev-1",
    "responderUri": "https://docs.google.com/forms/d/abc123FORM/viewform",
    "publishSettings": {"publishState": {"isPublished": False, "isAcceptingResponses": False}},
    "items": [
        {
            "itemId": "item-1",
            "title": "Đơn vị báo cáo",
            "questionItem": {
                "question": {
                    "questionId": "q-unit",
                    "required": True,
                    "textQuestion": {},
                }
            },
        },
        {
            "itemId": "item-2",
            "title": "Tổng số hồ sơ",
            "questionItem": {
                "question": {
                    "questionId": "q-total",
                    "textQuestion": {},
                }
            },
        },
    ],
}

RESPONSES_PAYLOAD = [
    {
        "responseId": "resp-1",
        "lastSubmittedTime": "2026-06-08T09:30:00Z",
        "answers": {
            "q-unit": {"textAnswers": {"answers": [{"value": "Công an phường Minh Xuân"}]}},
            "q-total": {"textAnswers": {"answers": [{"value": "12"}]}},
        },
    }
]


class TaskGoogleFormRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.task_id = None
        self.assignee_id = None

    def tearDown(self):
        with app.app_context():
            if self.task_id:
                TaskSubmission.query.filter_by(task_id=self.task_id).delete()
                TaskAssignment.query.filter_by(task_id=self.task_id).delete()
                TaskFormField.query.filter_by(task_id=self.task_id).delete()
                TaskComment.query.filter_by(task_id=self.task_id).delete()
                Task.query.filter_by(id=self.task_id).delete()
            if self.assignee_id:
                User.query.filter_by(id=self.assignee_id).delete()
            db.session.commit()

    def _login_admin_session(self):
        with app.app_context():
            user = User.query.filter_by(username="admin").first() or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user)

        with self.client.session_transaction() as sess:
            sess["uid"] = user.id
            sess["username"] = user.username
            sess["fullname"] = user.fullname
            sess["unit"] = user.unit_area or ""
            sess["unit_area"] = user.unit_area or ""
            sess["unit_area_ref"] = user.unit_area or ""
            sess["unit_key"] = user.unit_key or ""
            sess["role_id"] = user.role_id
            sess["must_change"] = False
            sess["is_admin"] = True
            sess["last_active"] = datetime.now().timestamp()
            sess["login_nonce"] = "task-google-form-test"
        return user

    def _create_assignee(self):
        with app.app_context():
            role = AppRole.query.order_by(AppRole.id.asc()).first()
            username = f"gf_user_{uuid.uuid4().hex[:8]}"
            user = User(
                username=username,
                fullname="Đồng chí Minh Xuân",
                role_id=getattr(role, "id", None),
                unit_area="Công an phường Minh Xuân",
                unit_key="minhxuan",
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.assignee_id = user.id
            return user

    def test_can_create_google_form_task_via_tasks_route(self):
        self._login_admin_session()
        assignee = self._create_assignee()

        with patch("routes.tasks._hydrate_google_form_fields", return_value=[]):
            response = self.client.post(
                "/tasks",
                data={
                    "task_mode": "FORM",
                    "form_provider": "google",
                    "title": "Thu thập phản hồi Google Form",
                    "description": "Test create google form task",
                    "assign_type": "user",
                    "target_users": [str(assignee.id)],
                    "google_form_url": "https://docs.google.com/forms/d/abc123FORM/viewform",
                    "google_form_match_mode": "unit",
                    "google_form_match_field": "Đơn vị báo cáo",
                    "google_form_builder_json": json.dumps(
                        {
                            "form_info": {"title": "Thu thập phản hồi Google Form", "description": "Test create google form task"},
                            "publish_settings": {"isPublished": False, "isAcceptingResponses": False},
                            "matching": {"mode": "unit", "match_field": "Đơn vị báo cáo"},
                            "items": [
                                {"kind": "text", "title": "Đơn vị báo cáo", "required": True},
                                {"kind": "text", "title": "Tổng số hồ sơ"},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            task = Task.query.filter_by(title="Thu thập phản hồi Google Form").order_by(Task.id.desc()).first()
            self.assertIsNotNone(task)
            self.task_id = task.id
            self.assertEqual(task.task_mode, "FORM")
            self.assertEqual(task.form_provider, "google")
            self.assertEqual(task.google_form_id, "abc123FORM")
            self.assertEqual(task.google_form_match_mode, "unit")
            self.assertEqual(task.google_form_match_field, "Đơn vị báo cáo")
            self.assertTrue(bool(task.google_form_builder_json))

    def test_can_create_google_form_real_form_from_builder_route(self):
        self._login_admin_session()
        assignee = self._create_assignee()
        with app.app_context():
            task = Task(
                title="Builder managed google form",
                content="builder",
                author_id=1,
                author_name="Admin",
                task_mode="FORM",
                form_provider="google",
                google_form_builder_json=json.dumps(
                    {
                        "form_info": {"title": "Builder managed google form", "description": "builder"},
                        "publish_settings": {"isPublished": False, "isAcceptingResponses": False},
                        "matching": {"mode": "unit", "match_field": "Đơn vị báo cáo"},
                        "items": [{"kind": "text", "title": "Đơn vị báo cáo", "required": True}],
                    },
                    ensure_ascii=False,
                ),
            )
            db.session.add(task)
            db.session.flush()
            db.session.add(
                TaskAssignment(
                    task_id=task.id,
                    user_id=assignee.id,
                    assignee_type="user",
                    title_snapshot=task.title,
                    status="assigned",
                    assigned_at=datetime.now(),
                )
            )
            db.session.commit()
            self.task_id = task.id

        app.config["GOOGLE_FORMS_ENABLED"] = True
        with patch("routes.tasks.build_google_forms_service", return_value=object()), patch(
            "routes.tasks.create_google_form",
            return_value={
                "form_id": "abc123FORM",
                "form_url": "https://docs.google.com/forms/d/abc123FORM/viewform",
                "edit_url": "https://docs.google.com/forms/d/abc123FORM/edit",
                "revision_id": "rev-2",
                "publish_settings": {"publishState": {"isPublished": False, "isAcceptingResponses": False}},
            },
        ):
            response = self.client.post(f"/tasks/{self.task_id}/google-form/create")

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            task = db.session.get(Task, self.task_id)
            self.assertEqual(task.google_form_id, "abc123FORM")
            runtime = json.loads(task.google_form_runtime_json)
            self.assertEqual(runtime["revision_id"], "rev-2")

    def test_can_publish_and_import_google_form_routes(self):
        self._login_admin_session()
        assignee = self._create_assignee()
        with app.app_context():
            task = Task(
                title="Legacy google form task",
                content="legacy",
                author_id=1,
                author_name="Admin",
                task_mode="FORM",
                form_provider="google",
                google_form_url="https://docs.google.com/forms/d/abc123FORM/viewform",
                google_form_id="abc123FORM",
                google_form_match_mode="unit",
                google_form_match_field="Đơn vị báo cáo",
                initial_status="Chưa tiếp nhận",
            )
            db.session.add(task)
            db.session.flush()
            db.session.add(
                TaskAssignment(
                    task_id=task.id,
                    user_id=assignee.id,
                    assignee_type="user",
                    title_snapshot=task.title,
                    status="assigned",
                    assigned_at=datetime.now(),
                )
            )
            db.session.commit()
            self.task_id = task.id

        app.config["GOOGLE_FORMS_ENABLED"] = True
        with patch("routes.tasks.build_google_forms_service", return_value=object()), patch(
            "routes.tasks.publish_google_form",
            return_value={"publishSettings": {"publishState": {"isPublished": True, "isAcceptingResponses": True}}},
        ):
            response = self.client.post(f"/tasks/{self.task_id}/google-form/publish")
        self.assertEqual(response.status_code, 302)

        with patch("routes.tasks.build_google_forms_service", return_value=object()), patch(
            "routes.tasks.load_google_form_into_builder",
            return_value={"builder_schema": {
                "form_info": {"title": "Imported form", "description": "legacy"},
                "publish_settings": {"isPublished": False, "isAcceptingResponses": False, "responderAccess": "anyone_with_link"},
                "matching": {"mode": "unit", "match_field": "Đơn vị báo cáo"},
                "items": [{"kind": "text", "title": "Đơn vị báo cáo", "required": True, "options": [], "rows": [], "columns": [], "settings": {}, "pc06_item_id": "gf_1"}],
            }, "form_payload": FORM_PAYLOAD},
        ):
            response = self.client.post(f"/tasks/{self.task_id}/google-form/import-structure")
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            task = db.session.get(Task, self.task_id)
            self.assertTrue(bool(task.google_form_builder_json))
            runtime = json.loads(task.google_form_runtime_json)
            self.assertEqual(runtime["form_id"], "abc123FORM")

    def test_sync_google_form_route_creates_submission_and_updates_assignment(self):
        self._login_admin_session()
        assignee = self._create_assignee()

        with app.app_context():
            task = Task(
                title="Google form sync task",
                content="sync",
                author_id=1,
                author_name="Admin",
                task_mode="FORM",
                form_provider="google",
                google_form_url="https://docs.google.com/forms/d/abc123FORM/viewform",
                google_form_id="abc123FORM",
                google_form_match_mode="unit",
                google_form_match_field="Đơn vị báo cáo",
                initial_status="Chưa tiếp nhận",
            )
            db.session.add(task)
            db.session.flush()
            db.session.add(
                TaskAssignment(
                    task_id=task.id,
                    user_id=assignee.id,
                    assignee_type="user",
                    title_snapshot=task.title,
                    status="assigned",
                    assigned_at=datetime.now(),
                )
            )
            db.session.commit()
            self.task_id = task.id

        app.config["GOOGLE_FORMS_ENABLED"] = True
        with patch("routes.tasks.build_google_forms_service", return_value=object()), patch(
            "routes.tasks.fetch_google_form_definition", return_value=FORM_PAYLOAD
        ), patch("routes.tasks.fetch_google_form_responses", return_value=RESPONSES_PAYLOAD):
            response = self.client.post(f"/tasks/{self.task_id}/sync-google-form")

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            assignment = TaskAssignment.query.filter_by(task_id=self.task_id, user_id=assignee.id).first()
            submission = TaskSubmission.query.filter_by(task_id=self.task_id, assignment_id=assignment.id).first()
            task = db.session.get(Task, self.task_id)

            self.assertIsNotNone(submission)
            self.assertEqual(assignment.status, "submitted")
            self.assertEqual(submission.external_source, "google_form")
            self.assertEqual(submission.external_submission_id, "resp-1")
            payload = json.loads(submission.payload_json)
            self.assertEqual(payload["google_q_q-total"], "12")
            sync_state = json.loads(task.google_form_sync_state_json)
            self.assertEqual(sync_state["matched_total"], 1)
            self.assertEqual(sync_state["unmatched_total"], 0)


if __name__ == "__main__":
    unittest.main()
