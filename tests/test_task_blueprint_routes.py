# -*- coding: utf-8 -*-
import io
import json
import uuid
import unittest
from datetime import datetime
from unittest.mock import patch

from app import app
from models import AppRole, Task, TaskAssignment, TaskComment, TaskFormField, TaskItem, TaskSubmission, User, db
try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None


class TaskBlueprintRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.task_ids = []
        self.assignee_id = None

    def tearDown(self):
        with app.app_context():
            for task_id in self.task_ids:
                TaskSubmission.query.filter_by(task_id=task_id).delete()
                TaskAssignment.query.filter_by(task_id=task_id).delete()
                TaskFormField.query.filter_by(task_id=task_id).delete()
                TaskItem.query.filter_by(task_id=task_id).delete()
                TaskComment.query.filter_by(task_id=task_id).delete()
                Task.query.filter_by(id=task_id).delete()
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
            sess["session_version"] = int(user.session_version or 0)
            sess["csrf_token"] = "task-blueprint-test-csrf"
            sess["last_active"] = datetime.now().timestamp()
            sess["login_nonce"] = "task-blueprint-test"
        return user

    def _create_assignee(self):
        with app.app_context():
            role = AppRole.query.order_by(AppRole.id.asc()).first()
            username = f"bp_user_{uuid.uuid4().hex[:8]}"
            user = User(
                username=username,
                fullname="Đồng chí Blueprint",
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

    def test_can_create_outline_task_from_workflow_blueprint(self):
        self._login_admin_session()
        assignee = self._create_assignee()
        blueprint = {
            "title": "Công tác tuần Đội 1",
            "source_kind": "directive",
            "cadence": "weekly",
            "items": [
                {"title": "Đầu mục 1", "report_kind": "narrative"},
                {"title": "Chỉ tiêu 2", "report_kind": "number", "attachment_required": True},
            ],
        }

        response = self.client.post(
            "/tasks",
            data={
                "csrf_token": "task-blueprint-test-csrf",
                "workflow_blueprint_json": json.dumps(blueprint, ensure_ascii=False),
                "assign_type": "user",
                "target_users": [str(assignee.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            task = Task.query.filter_by(title="Công tác tuần Đội 1").order_by(Task.id.desc()).first()
            self.assertIsNotNone(task)
            self.task_ids.append(task.id)
            self.assertEqual(task.task_mode, "OUTLINE")
            items = TaskItem.query.filter_by(task_id=task.id).order_by(TaskItem.sort_order.asc()).all()
            self.assertEqual(len(items), 2)
            self.assertEqual(items[1].report_kind, "number")
            self.assertTrue(items[1].attachment_required)
            self.assertEqual(TaskAssignment.query.filter_by(task_id=task.id).count(), 2)

    def test_can_create_form_task_from_workflow_blueprint(self):
        self._login_admin_session()
        assignee = self._create_assignee()
        blueprint = {
            "title": "Thu thập tiến độ triển khai",
            "source_kind": "google_form",
            "collection_mode": "form",
            "form_fields": [
                {"label": "Đơn vị báo cáo", "type": "text", "required": True},
                {"label": "Tổng số hồ sơ", "type": "number", "required": True},
            ],
        }

        response = self.client.post(
            "/tasks",
            data={
                "csrf_token": "task-blueprint-test-csrf",
                "workflow_blueprint_json": json.dumps(blueprint, ensure_ascii=False),
                "assign_type": "user",
                "target_users": [str(assignee.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            task = Task.query.filter_by(title="Thu thập tiến độ triển khai").order_by(Task.id.desc()).first()
            self.assertIsNotNone(task)
            self.task_ids.append(task.id)
            self.assertEqual(task.task_mode, "FORM")
            self.assertEqual(TaskFormField.query.filter_by(task_id=task.id).count(), 2)

    def test_can_preview_workflow_blueprint(self):
        self._login_admin_session()
        response = self.client.post(
            "/tasks/workflow-blueprint-preview",
            json={
                "workflow_blueprint": {
                    "title": "Báo cáo tháng",
                    "source_kind": "sectioned_report",
                    "collection_mode": "file",
                    "report_schema": {
                        "enabled": True,
                        "narrative": {"enabled": True, "required": True},
                        "fields": [{"label": "Số hồ sơ", "type": "number"}],
                    },
                }
            },
            headers={"X-CSRF-Token": "task-blueprint-test-csrf"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["preview"]["task_mode"], "FILE")
        self.assertEqual(payload["preview"]["report_field_count"], 1)

    def test_can_import_outline_blueprint_from_text_file(self):
        self._login_admin_session()
        response = self.client.post(
            "/tasks/workflow-blueprint-import",
            data={
                "csrf_token": "task-blueprint-test-csrf",
                "blueprint_import_mode": "docx_outline",
                "blueprint_source_file": (
                    io.BytesIO("1. Nội dung thứ nhất\n2. Nội dung thứ hai".encode("utf-8")),
                    "cong-tac-tuan.txt",
                ),
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": "task-blueprint-test-csrf"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["preview"]["task_mode"], "OUTLINE")
        self.assertEqual(payload["preview"]["item_count"], 2)
        self.assertEqual(payload["workflow_blueprint"]["source_kind"], "directive")

    def test_can_import_form_blueprint_from_xlsx_file(self):
        if Workbook is None:
            self.skipTest("openpyxl is not installed")
        self._login_admin_session()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Tien do"
        sheet.append(["Đơn vị báo cáo", "Tổng số hồ sơ", "Nhận xét"])
        sheet.append(["Công an phường Minh Xuân", 12, "Đã cập nhật"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)

        response = self.client.post(
            "/tasks/workflow-blueprint-import",
            data={
                "csrf_token": "task-blueprint-test-csrf",
                "blueprint_import_mode": "xlsx_form",
                "blueprint_source_file": (buffer, "bao-cao-mau.xlsx"),
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": "task-blueprint-test-csrf"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["preview"]["task_mode"], "FORM")
        self.assertEqual(payload["preview"]["form_field_count"], 3)
        self.assertEqual(payload["workflow_blueprint"]["source_kind"], "excel_template")

    def test_can_import_form_blueprint_from_google_form_reference(self):
        self._login_admin_session()
        form_payload = {
            "formId": "abc123FORM",
            "info": {"title": "Thu thập phản hồi Google Form", "description": "builder"},
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

        with patch("services.blueprint_parsing.build_google_forms_service", return_value=object()), patch(
            "services.blueprint_parsing.load_google_form_into_builder",
            return_value={"builder_schema": {"form_info": {"title": "Thu thập phản hồi Google Form"}}, "form_payload": form_payload},
        ):
            response = self.client.post(
                "/tasks/workflow-blueprint-import",
                data={
                    "csrf_token": "task-blueprint-test-csrf",
                    "blueprint_import_mode": "google_form_remote",
                    "blueprint_form_reference": "https://docs.google.com/forms/d/abc123FORM/viewform",
                },
                headers={"X-CSRF-Token": "task-blueprint-test-csrf"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["preview"]["task_mode"], "FORM")
        self.assertEqual(payload["preview"]["form_field_count"], 2)
        self.assertEqual(payload["workflow_blueprint"]["source_kind"], "google_form")


if __name__ == "__main__":
    unittest.main()
