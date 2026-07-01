# -*- coding: utf-8 -*-
import io
import json
import uuid
import unittest
from datetime import datetime
from unittest.mock import patch

from app import app
from models import (
    AppRole,
    Task,
    TaskAssignment,
    TaskComment,
    TaskFormField,
    TaskImportDraft,
    TaskItem,
    TaskSubmission,
    User,
    db,
)

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None


class TaskImportDraftRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.draft_ids = []
        self.task_ids = []
        self.user_ids = []
        self.csrf_token = "task-import-draft-test-csrf"

    def tearDown(self):
        with app.app_context():
            for draft_id in self.draft_ids:
                TaskImportDraft.query.filter_by(id=draft_id).delete()
            for task_id in self.task_ids:
                TaskSubmission.query.filter_by(task_id=task_id).delete()
                TaskAssignment.query.filter_by(task_id=task_id).delete()
                TaskFormField.query.filter_by(task_id=task_id).delete()
                TaskItem.query.filter_by(task_id=task_id).delete()
                TaskComment.query.filter_by(task_id=task_id).delete()
                Task.query.filter_by(id=task_id).delete()
            for user_id in self.user_ids:
                User.query.filter_by(id=user_id).delete()
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
            sess["csrf_token"] = self.csrf_token
            sess["last_active"] = datetime.now().timestamp()
            sess["login_nonce"] = "task-import-draft-test"
        return user

    def _create_assignee(self, fullname):
        with app.app_context():
            role = AppRole.query.order_by(AppRole.id.asc()).first()
            username = f"tid_user_{uuid.uuid4().hex[:8]}"
            user = User(
                username=username,
                fullname=fullname,
                role_id=getattr(role, "id", None),
                unit_area="Công an phường Minh Xuân",
                unit_key="minhxuan",
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.user_ids.append(user.id)
            return user

    def _track_latest_draft(self):
        with app.app_context():
            draft = TaskImportDraft.query.order_by(TaskImportDraft.id.desc()).first()
            self.assertIsNotNone(draft)
            self.draft_ids.append(draft.id)
            return draft.id

    def _track_task(self, task_id):
        if task_id not in self.task_ids:
            self.task_ids.append(task_id)

    def test_can_create_outline_import_draft_from_text_file(self):
        self._login_admin_session()

        response = self.client.post(
            "/tasks/import-drafts/create",
            data={
                "csrf_token": self.csrf_token,
                "source_type": "docx_outline",
                "source_file": (
                    io.BytesIO("1. Nhiệm vụ thứ nhất\n2. Nhiệm vụ thứ hai".encode("utf-8")),
                    "cong-tac-tuan.txt",
                ),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 302)
        draft_id = self._track_latest_draft()
        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            self.assertEqual(draft.source_type, "docx_outline")
            config = json.loads(draft.working_config_json)
            self.assertEqual(config["collection_mode"], "outline")
            self.assertEqual(len(config["items"]), 2)

    def test_rejects_legacy_doc_with_conversion_guidance(self):
        self._login_admin_session()
        with app.app_context():
            before_count = TaskImportDraft.query.count()

        response = self.client.post(
            "/tasks/import-drafts/create",
            data={
                "csrf_token": self.csrf_token,
                "source_type": "docx_outline",
                "source_file": (io.BytesIO(b"legacy"), "ke-hoach.doc"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("File .doc chưa được hỗ trợ", response.get_data(as_text=True))
        self.assertIn(".docx", response.get_data(as_text=True))
        with app.app_context():
            after_count = TaskImportDraft.query.count()
            self.assertEqual(after_count, before_count)

    def test_can_create_google_form_import_draft(self):
        self._login_admin_session()
        form_payload = {
            "formId": "gf-draft-123",
            "info": {"title": "Google Form báo cáo nhanh"},
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
                }
            ],
        }

        with patch("routes.tasks.build_google_forms_service", return_value=object()), patch(
            "routes.tasks.load_google_form_into_builder",
            return_value={"builder_schema": {"form_info": {"title": "Google Form báo cáo nhanh"}}, "form_payload": form_payload},
        ):
            response = self.client.post(
                "/tasks/import-drafts/create",
                data={
                    "csrf_token": self.csrf_token,
                    "source_type": "google_form_remote",
                    "blueprint_form_reference": "https://docs.google.com/forms/d/gf-draft-123/viewform",
                },
            )

        self.assertEqual(response.status_code, 302)
        draft_id = self._track_latest_draft()
        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            self.assertEqual(config["collection_mode"], "form")
            self.assertEqual(len(config["form_fields"]), 1)
            self.assertEqual(draft.source_ref, "https://docs.google.com/forms/d/gf-draft-123/viewform")

    def test_can_save_and_publish_outline_draft(self):
        self._login_admin_session()
        assignee = self._create_assignee("Đồng chí Outline")

        create_response = self.client.post(
            "/tasks/import-drafts/create",
            data={
                "csrf_token": self.csrf_token,
                "source_type": "docx_outline",
                "source_file": (
                    io.BytesIO("1. Đầu mục A\n2. Đầu mục B".encode("utf-8")),
                    "outline.txt",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(create_response.status_code, 302)
        draft_id = self._track_latest_draft()

        save_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/save",
            data={
                "csrf_token": self.csrf_token,
                "title": "Công tác tuần đã duyệt",
                "summary": "Tổng hợp đầu mục tuần.",
                "category": "",
                "domain": "",
                "task_type": "Công việc thường xuyên",
                "priority": "Trung bình",
                "deadline": "",
                "draft_assign_type": "user",
                "draft_user_ids": [str(assignee.id)],
                "manager_scope_mode": "none",
                "viewer_scope_mode": "none",
                "item_title": ["Đầu mục A", "Đầu mục B"],
                "item_guide_text": ["Theo dõi tiến độ", "Báo cáo số liệu"],
                "item_report_kind": ["narrative", "number"],
                "item_attachment_required": ["1"],
                "item_assign_type": ["user", "user"],
                "item_unit_domains": ["", ""],
                "item_role_ids": ["", ""],
                "item_user_ids": [str(assignee.id), str(assignee.id)],
            },
        )
        self.assertEqual(save_response.status_code, 302)

        publish_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/publish",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(publish_response.status_code, 302)

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            self.assertEqual(draft.status, "published")
            self.assertIsNotNone(draft.published_task_id)
            self._track_task(draft.published_task_id)

            task = db.session.get(Task, draft.published_task_id)
            self.assertEqual(task.task_mode, "OUTLINE")
            items = TaskItem.query.filter_by(task_id=task.id).order_by(TaskItem.sort_order.asc()).all()
            self.assertEqual(len(items), 2)
            self.assertEqual(items[1].report_kind, "number")
            self.assertTrue(items[1].attachment_required)
            self.assertEqual(TaskAssignment.query.filter_by(task_id=task.id).count(), 2)

    def test_can_save_and_publish_form_draft_from_xlsx(self):
        if Workbook is None:
            self.skipTest("openpyxl is not installed")

        self._login_admin_session()
        assignee = self._create_assignee("Đồng chí Form")

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Bao cao"
        sheet.append(["Đơn vị báo cáo", "Tổng số hồ sơ"])
        sheet.append(["Công an phường Minh Xuân", 12])
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)

        create_response = self.client.post(
            "/tasks/import-drafts/create",
            data={
                "csrf_token": self.csrf_token,
                "source_type": "xlsx_form",
                "source_file": (buffer, "bao-cao.xlsx"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(create_response.status_code, 302)
        draft_id = self._track_latest_draft()

        save_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/save",
            data={
                "csrf_token": self.csrf_token,
                "title": "Biểu mẫu tiến độ tháng",
                "summary": "Thu thập số liệu tiến độ.",
                "category": "",
                "domain": "",
                "task_type": "Công việc thường xuyên",
                "priority": "Trung bình",
                "deadline": "",
                "draft_assign_type": "user",
                "draft_user_ids": [str(assignee.id)],
                "manager_scope_mode": "none",
                "viewer_scope_mode": "none",
                "form_field_label": ["Đơn vị báo cáo", "Tổng số hồ sơ"],
                "form_field_key": ["don_vi_bao_cao", "tong_so_ho_so"],
                "form_field_type": ["text", "number"],
                "form_field_options": ["", ""],
                "form_field_required": ["0", "1"],
            },
        )
        self.assertEqual(save_response.status_code, 302)

        publish_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/publish",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(publish_response.status_code, 302)

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            self.assertEqual(draft.status, "published")
            self._track_task(draft.published_task_id)

            task = db.session.get(Task, draft.published_task_id)
            self.assertEqual(task.task_mode, "FORM")
            self.assertEqual(TaskFormField.query.filter_by(task_id=task.id).count(), 2)
            self.assertEqual(TaskAssignment.query.filter_by(task_id=task.id).count(), 1)

    def test_can_save_and_publish_file_draft_from_blueprint_json(self):
        self._login_admin_session()
        assignee = self._create_assignee("Đồng chí File")
        blueprint = {
            "title": "Báo cáo tháng 6",
            "source_kind": "sectioned_report",
            "collection_mode": "file",
            "report_schema": {
                "enabled": True,
                "narrative": {"enabled": True, "required": True, "label": "Nội dung tổng hợp"},
                "attachment": {"enabled": True, "required": False, "label": "Phụ lục minh chứng"},
                "fields": [
                    {"label": "Số hồ sơ", "type": "number", "required": True},
                    {"label": "Nhận xét", "type": "textarea", "required": False},
                ],
            },
        }

        create_response = self.client.post(
            "/tasks/import-drafts/create",
            data={
                "csrf_token": self.csrf_token,
                "source_type": "blueprint_json",
                "workflow_blueprint_json": json.dumps(blueprint, ensure_ascii=False),
            },
        )
        self.assertEqual(create_response.status_code, 302)
        draft_id = self._track_latest_draft()

        save_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/save",
            data={
                "csrf_token": self.csrf_token,
                "title": "Báo cáo tháng 6 đã duyệt",
                "summary": "Thu thập báo cáo tổng hợp theo file.",
                "category": "",
                "domain": "",
                "task_type": "Công việc thường xuyên",
                "priority": "Trung bình",
                "deadline": "",
                "draft_assign_type": "user",
                "draft_user_ids": [str(assignee.id)],
                "manager_scope_mode": "none",
                "viewer_scope_mode": "none",
                "report_narrative_enabled": "1",
                "report_narrative_required": "1",
                "report_narrative_label": "Nội dung tổng hợp",
                "report_attachment_enabled": "1",
                "report_attachment_label": "Phụ lục minh chứng",
                "report_field_label": ["Số hồ sơ", "Nhận xét"],
                "report_field_key": ["so_ho_so", "nhan_xet"],
                "report_field_type": ["number", "textarea"],
                "report_field_placeholder": ["0", "Nhập nhận xét"],
                "report_field_help_text": ["Tổng số hồ sơ", "Đánh giá chung"],
                "report_field_required": ["0"],
            },
        )
        self.assertEqual(save_response.status_code, 302)

        publish_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/publish",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(publish_response.status_code, 302)

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            self.assertEqual(draft.status, "published")
            self._track_task(draft.published_task_id)

            task = db.session.get(Task, draft.published_task_id)
            self.assertEqual(task.task_mode, "FILE")
            report_schema = json.loads(task.report_schema_json)
            self.assertEqual(len(report_schema["fields"]), 2)
            self.assertTrue(report_schema["attachment"]["enabled"])
            self.assertEqual(TaskAssignment.query.filter_by(task_id=task.id).count(), 1)


if __name__ == "__main__":
    unittest.main()
