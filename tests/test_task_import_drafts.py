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
                "form_field_target_type": ["unit", "all"],
                "form_field_target_unit_domains": ["minh-xuan", ""],
                "form_field_target_role_ids": ["", ""],
                "form_field_target_user_ids": ["", ""],
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
            fields = TaskFormField.query.filter_by(task_id=task.id).order_by(TaskFormField.sort_order.asc()).all()
            self.assertEqual(len(fields), 2)
            self.assertIn('"target_type": "unit"', fields[0].field_options_json or "")
            self.assertIn('"target_unit_domains": ["minh-xuan"]', fields[0].field_options_json or "")
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

    def test_can_analyze_and_apply_ai_for_outline_draft(self):
        self._login_admin_session()
        assignee = self._create_assignee("Nguyễn Văn A")
        blueprint = {
            "title": "Nháp AI điều hành",
            "source_kind": "directive",
            "collection_mode": "outline",
            "items": [
                {
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ và file minh chứng",
                    "report_kind": "narrative",
                    "attachment_required": False,
                }
            ],
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

        analyze_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-analyze",
            json={"use_provider": False},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(analyze_response.status_code, 200)
        analyze_payload = analyze_response.get_json()
        self.assertTrue(analyze_payload["ok"])
        self.assertEqual(analyze_payload["analysis"]["outline_items"][0]["suggestion"]["assign_type"], "user")

        apply_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-apply",
            json={"mode": "safe"},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.get_json()
        self.assertTrue(apply_payload["ok"])

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            item = config["items"][0]
            self.assertEqual(item["assign_type"], "user")
            self.assertEqual(item["user_ids"], [assignee.id])
            self.assertEqual(item["report_kind"], "number")
            self.assertTrue(item["attachment_required"])

    def test_ai_analyze_uses_current_workload_from_live_assignments(self):
        self._login_admin_session()
        assignee = self._create_assignee("Nguyễn Văn A")
        with app.app_context():
            for index in range(6):
                task = Task(
                    title=f"Tác vụ đang mở {index}",
                    content="workload",
                    author_id=1,
                    author_name="Admin",
                    task_mode="FILE",
                    priority="Cao" if index < 2 else "Trung bình",
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
                        status="in_progress",
                        assigned_at=datetime.now(),
                    )
                )
                self._track_task(task.id)
            db.session.commit()

        blueprint = {
            "title": "Nháp AI theo tải thực tế",
            "source_kind": "directive",
            "collection_mode": "outline",
            "items": [
                {
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ",
                    "report_kind": "narrative",
                    "attachment_required": False,
                }
            ],
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

        analyze_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-analyze",
            json={"use_provider": False},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(analyze_response.status_code, 200)
        payload = analyze_response.get_json()

        self.assertTrue(payload["ok"])
        suggestion = payload["analysis"]["outline_items"][0]["suggestion"]
        self.assertGreater(float(suggestion.get("workload_penalty") or 0.0), 0.0)
        self.assertTrue(any(str(signal.get("key") or "").startswith("workload_") for signal in (suggestion.get("fit_signals") or [])))

    def test_can_apply_selected_ai_sections_without_touching_other_parts(self):
        self._login_admin_session()
        assignee = self._create_assignee("Nguyễn Văn A")
        blueprint = {
            "title": "",
            "source_kind": "directive",
            "collection_mode": "outline",
            "items": [
                {
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ và file minh chứng",
                    "report_kind": "narrative",
                    "attachment_required": False,
                }
            ],
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

        analyze_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-analyze",
            json={"use_provider": False},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(analyze_response.status_code, 200)

        apply_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-apply",
            json={"mode": "safe", "sections": ["metadata"]},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.get_json()
        self.assertTrue(apply_payload["ok"])

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            item = config["items"][0]
            self.assertTrue(config["title"])
            self.assertEqual(item["assign_type"], "")
            self.assertEqual(item["user_ids"], [])
            self.assertEqual(item["report_kind"], "narrative")
            self.assertFalse(item["attachment_required"])
            self.assertEqual(config["ai_last_sections"], ["metadata"])

    def test_can_apply_ai_to_single_outline_item_only(self):
        self._login_admin_session()
        assignee_a = self._create_assignee("Nguyễn Văn A")
        assignee_b = self._create_assignee("Nguyễn Văn B")
        blueprint = {
            "title": "Nháp điều hành nhiều dòng",
            "source_kind": "directive",
            "collection_mode": "outline",
            "items": [
                {
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ",
                    "report_kind": "narrative",
                    "attachment_required": False,
                },
                {
                    "title": "Nguyễn Văn B tổng hợp file minh chứng",
                    "report_kind": "narrative",
                    "attachment_required": False,
                },
            ],
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

        analyze_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-analyze",
            json={"use_provider": False},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(analyze_response.status_code, 200)

        apply_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-apply",
            json={
                "mode": "safe",
                "sections": ["outline_items"],
                "selection": {"outline_indexes": [1]},
            },
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.get_json()
        self.assertTrue(apply_payload["ok"])

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            first_item = config["items"][0]
            second_item = config["items"][1]
            self.assertEqual(first_item["assign_type"], "")
            self.assertEqual(first_item["user_ids"], [])
            self.assertFalse(first_item["attachment_required"])
            self.assertEqual(second_item["assign_type"], "user")
            self.assertEqual(second_item["user_ids"], [assignee_b.id])
            self.assertTrue(second_item["attachment_required"])
            self.assertEqual(config["ai_last_sections"], ["outline_items"])
            self.assertEqual(config["ai_last_selection"]["outline_indexes"], [1])

    def test_can_apply_outline_alternative_choice_from_ai(self):
        self._login_admin_session()
        assignee_a = self._create_assignee("Nguyễn Văn A")
        assignee_b = self._create_assignee("Nguyễn Văn B")
        blueprint = {
            "title": "Nháp điều hành có alternative",
            "source_kind": "directive",
            "collection_mode": "outline",
            "items": [
                {
                    "title": "Dòng có nhiều phương án",
                    "report_kind": "narrative",
                    "attachment_required": False,
                }
            ],
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

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            config["ai_analysis"] = {
                "recommended_updates": {},
                "outline_items": [
                    {
                        "index": 0,
                        "title": "Dòng có nhiều phương án",
                        "suggestion": {
                            "assign_type": "user",
                            "unit_domains": [],
                            "role_ids": [],
                            "user_ids": [assignee_a.id],
                            "confidence_score": 0.88,
                            "confidence_label": "rất cao",
                            "display_targets": ["Nguyễn Văn A"],
                            "reasons": ["Khớp trực tiếp với cá nhân Nguyễn Văn A."],
                            "report_kind": "narrative",
                            "attachment_required": False,
                            "alternatives": [
                                {
                                    "assign_type": "user",
                                    "unit_domains": [],
                                    "role_ids": [],
                                    "user_ids": [assignee_b.id],
                                    "confidence_score": 0.67,
                                    "confidence_label": "cao",
                                    "display_targets": ["Nguyễn Văn B"],
                                    "reasons": ["Phương án thay thế theo lịch sử xử lý."],
                                }
                            ],
                        },
                    }
                ],
            }
            draft.working_config_json = json.dumps(config, ensure_ascii=False)
            db.session.add(draft)
            db.session.commit()

        apply_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/ai-apply",
            json={
                "mode": "safe",
                "sections": ["outline_items"],
                "selection": {
                    "outline_indexes": [0],
                    "outline_alternative_indexes": {"0": 0},
                },
            },
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.get_json()
        self.assertTrue(apply_payload["ok"])

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            item = config["items"][0]
            self.assertEqual(item["assign_type"], "user")
            self.assertEqual(item["user_ids"], [assignee_b.id])
            self.assertEqual(config["ai_last_selection"]["outline_alternative_indexes"], {"0": 0})

    def test_render_context_builds_outline_recipient_preview(self):
        self._login_admin_session()
        assignee = self._create_assignee("Đồng chí Preview Outline")
        blueprint = {
            "title": "Nháp preview outline",
            "source_kind": "directive",
            "collection_mode": "outline",
            "items": [{"title": "Đầu mục tổng hợp tuần"}],
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

        with app.app_context():
            from routes.tasks import _task_import_draft_render_context

            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            config["items"][0].update(
                {
                    "guide_text": "Báo cáo tiến độ trong tuần",
                    "report_kind": "number",
                    "attachment_required": True,
                    "assign_type": "user",
                    "user_ids": [assignee.id],
                }
            )
            draft.working_config_json = json.dumps(config, ensure_ascii=False)
            db.session.add(draft)
            db.session.commit()

            with app.test_request_context(f"/tasks/import-drafts/{draft_id}"):
                context = _task_import_draft_render_context(draft)
            preview = context["recipient_preview"]
            self.assertEqual(preview["mode"], "outline")
            self.assertEqual(preview["recipient_count"], 1)
            self.assertEqual(preview["cards"][0]["user_name"], "Đồng chí Preview Outline")
            self.assertEqual(preview["cards"][0]["outline_items"][0]["title"], "Đầu mục tổng hợp tuần")
            self.assertEqual(preview["cards"][0]["outline_items"][0]["report_kind_label"], "Báo cáo số")
            self.assertTrue(preview["cards"][0]["outline_items"][0]["attachment_required"])
            self.assertEqual(preview["unit_groups"][0]["unit_name"], "Công an phường Minh Xuân")
            self.assertEqual(preview["unit_groups"][0]["item_count"], 1)
            self.assertEqual(preview["submission_groups"][0]["mode_label"], "Nộp cá nhân")
            self.assertEqual(preview["submission_groups"][0]["payload_count"], 1)

    def test_render_context_builds_form_recipient_preview_with_field_visibility(self):
        self._login_admin_session()
        assignee = self._create_assignee("Đồng chí Preview Form")
        other_user = self._create_assignee("Đồng chí Không Nhận Field")
        blueprint = {
            "title": "Nháp preview form",
            "source_kind": "google_form",
            "collection_mode": "form",
            "form_fields": [{"label": "Chỉ tiêu 1", "type": "number", "required": True}],
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

        with app.app_context():
            from routes.tasks import _task_import_draft_render_context

            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            config.update(
                {
                    "assign_type": "user",
                    "user_ids": [assignee.id, other_user.id],
                    "form_fields": [
                        {
                            "field_key": "chi_tieu_1",
                            "field_label": "Chỉ tiêu 1",
                            "field_type": "number",
                            "field_options_text": "",
                            "is_required": True,
                            "target_type": "user",
                            "target_unit_domains": [],
                            "target_role_ids": [],
                            "target_user_ids": [assignee.id],
                            "sort_order": 0,
                        }
                    ],
                }
            )
            draft.working_config_json = json.dumps(config, ensure_ascii=False)
            db.session.add(draft)
            db.session.commit()

            with app.test_request_context(f"/tasks/import-drafts/{draft_id}"):
                context = _task_import_draft_render_context(draft)
            preview = context["recipient_preview"]
            self.assertEqual(preview["mode"], "form")
            self.assertEqual(preview["recipient_count"], 2)
            first_card = next(card for card in preview["cards"] if card["user_id"] == assignee.id)
            second_card = next(card for card in preview["cards"] if card["user_id"] == other_user.id)
            self.assertEqual(first_card["field_count"], 1)
            self.assertEqual(first_card["form_fields"][0]["label"], "Chỉ tiêu 1")
            self.assertEqual(second_card["field_count"], 0)
            self.assertTrue(second_card["warnings"])
            self.assertEqual(preview["unit_groups"][0]["field_count"], 1)
            self.assertEqual(preview["unit_groups"][0]["recipient_count"], 2)

    def test_render_context_builds_role_submission_group_preview(self):
        self._login_admin_session()
        assignee_a = self._create_assignee("Đồng chí Vai trò A")
        assignee_b = self._create_assignee("Đồng chí Vai trò B")
        blueprint = {
            "title": "Nháp preview role group",
            "source_kind": "google_form",
            "collection_mode": "form",
            "form_fields": [{"label": "Chỉ tiêu Vai trò", "type": "number", "required": True}],
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

        with app.app_context():
            from routes.tasks import _task_import_draft_render_context

            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            config.update(
                {
                    "assign_type": "role",
                    "role_ids": [assignee_a.role_id],
                    "user_ids": [],
                    "unit_domains": [],
                    "form_fields": [
                        {
                            "field_key": "chi_tieu_vai_tro",
                            "field_label": "Chỉ tiêu Vai trò",
                            "field_type": "number",
                            "field_options_text": "",
                            "is_required": True,
                            "target_type": "all",
                            "target_unit_domains": [],
                            "target_role_ids": [],
                            "target_user_ids": [],
                            "sort_order": 0,
                        }
                    ],
                }
            )
            draft.working_config_json = json.dumps(config, ensure_ascii=False)
            db.session.add(draft)
            db.session.commit()

            with app.test_request_context(f"/tasks/import-drafts/{draft_id}"):
                context = _task_import_draft_render_context(draft)
            preview = context["recipient_preview"]
            self.assertEqual(preview["mode"], "form")
            self.assertGreaterEqual(preview["recipient_count"], 2)
            matched_group = next(
                group for group in preview["submission_groups"]
                if group["mode_label"] == "Nộp theo vai trò"
                and "Đồng chí Vai trò A" in group["member_names"]
                and "Đồng chí Vai trò B" in group["member_names"]
            )
            self.assertGreaterEqual(matched_group["recipient_count"], 2)
            self.assertGreaterEqual(matched_group["payload_count"], 2)

    def test_render_context_builds_file_recipient_preview_with_unit_group_summary(self):
        self._login_admin_session()
        assignee = self._create_assignee("Đồng chí Preview File")
        blueprint = {
            "title": "Nháp preview file",
            "source_kind": "report",
            "collection_mode": "file",
            "report_schema": {
                "narrative": {"enabled": True, "required": True, "label": "Thuyết minh"},
                "attachment": {"enabled": True, "required": False, "label": "Phụ lục"},
                "fields": [{"label": "Chỉ tiêu A", "type": "number", "required": True}],
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

        with app.app_context():
            from routes.tasks import _task_import_draft_render_context

            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            config.update(
                {
                    "assign_type": "user",
                    "user_ids": [assignee.id],
                    "report_narrative_enabled": True,
                    "report_narrative_required": True,
                    "report_narrative_label": "Thuyết minh",
                    "report_attachment_enabled": True,
                    "report_attachment_required": False,
                    "report_attachment_label": "Phụ lục",
                    "report_fields": [
                        {
                            "key": "chi_tieu_a",
                            "label": "Chỉ tiêu A",
                            "type": "number",
                            "required": True,
                            "placeholder": "",
                            "help_text": "",
                            "target_type": "all",
                            "target_unit_domains": [],
                            "target_role_ids": [],
                            "target_user_ids": [],
                            "sort_order": 0,
                        }
                    ],
                }
            )
            draft.working_config_json = json.dumps(config, ensure_ascii=False)
            db.session.add(draft)
            db.session.commit()

            with app.test_request_context(f"/tasks/import-drafts/{draft_id}"):
                context = _task_import_draft_render_context(draft)
            preview = context["recipient_preview"]
            self.assertEqual(preview["mode"], "file")
            self.assertEqual(preview["recipient_count"], 1)
            self.assertEqual(preview["cards"][0]["section_count"], 3)
            self.assertEqual(preview["unit_groups"][0]["section_count"], 3)
            self.assertIn("Thuyết minh", preview["unit_groups"][0]["payload_labels"])
            self.assertEqual(preview["submission_groups"][0]["mode_label"], "Nộp cá nhân")

    def test_draft_detail_page_shows_recipient_preview_and_csrf_fields(self):
        self._login_admin_session()
        assignee = self._create_assignee("Đồng chí Preview Page")
        blueprint = {
            "title": "Nháp preview page",
            "source_kind": "directive",
            "collection_mode": "outline",
            "items": [{"title": "Nội dung phát hành"}],
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

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            config = json.loads(draft.working_config_json)
            config["items"][0].update({"assign_type": "user", "user_ids": [assignee.id]})
            draft.working_config_json = json.dumps(config, ensure_ascii=False)
            db.session.add(draft)
            db.session.commit()

        response = self.client.get(f"/tasks/import-drafts/{draft_id}")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("Bước 3: Xem trước đầu ra cho đơn vị", content)
        self.assertIn("Nhóm nộp sau phát hành", content)
        self.assertIn("Đồng chí Preview Page", content)
        self.assertIn("đơn vị", content.lower())
        self.assertGreaterEqual(content.count('name="csrf_token"'), 2)

    def test_publish_form_draft_blocks_when_some_assignee_has_no_visible_field(self):
        self._login_admin_session()
        assignee_a = self._create_assignee("Đồng chí Có Field")
        assignee_b = self._create_assignee("Đồng chí Không Có Field")
        blueprint = {
            "title": "Nháp form cần chặn publish",
            "source_kind": "google_form",
            "collection_mode": "form",
            "form_fields": [{"label": "Chỉ tiêu A", "type": "number", "required": True}],
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
                "title": "Nháp form cần chặn publish",
                "summary": "Một người nhận không thấy field nào.",
                "category": "",
                "domain": "",
                "task_type": "Công việc thường xuyên",
                "priority": "Trung bình",
                "deadline": "",
                "draft_assign_type": "user",
                "draft_user_ids": [str(assignee_a.id), str(assignee_b.id)],
                "manager_scope_mode": "none",
                "viewer_scope_mode": "none",
                "form_field_label": ["Chỉ tiêu A"],
                "form_field_key": ["chi_tieu_a"],
                "form_field_type": ["number"],
                "form_field_options": [""],
                "form_field_required": ["1"],
                "form_field_target_type": ["user"],
                "form_field_target_unit_domains": [""],
                "form_field_target_role_ids": [""],
                "form_field_target_user_ids": [str(assignee_a.id)],
            },
        )
        self.assertEqual(save_response.status_code, 302)

        publish_response = self.client.post(
            f"/tasks/import-drafts/{draft_id}/publish",
            data={"csrf_token": self.csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(publish_response.status_code, 200)
        content = publish_response.get_data(as_text=True)
        self.assertIn("chưa thấy trường biểu mẫu nào", content)

        with app.app_context():
            draft = db.session.get(TaskImportDraft, draft_id)
            self.assertEqual(draft.status, "failed")
            self.assertFalse(draft.published_task_id)


if __name__ == "__main__":
    unittest.main()
