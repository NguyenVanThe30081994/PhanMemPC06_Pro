# -*- coding: utf-8 -*-
import io
import unittest
import uuid
from datetime import datetime

from app import app
from models import (
    Task,
    TaskAssignment,
    TaskComment,
    TaskFormField,
    TaskItem,
    TaskParticipant,
    TaskSubmission,
    User,
    db,
)
from docx import Document


class TaskCreateWizardTests(unittest.TestCase):
    """Kiểm thử wizard tạo công việc mới:

    - Phân tích đề cương ngay trong lúc tạo (endpoint /tasks/outline-parse).
    - Lấy trường từ biểu mẫu báo cáo có sẵn (endpoint /tasks/form-template-preview).
    - Tạo công việc theo đề cương kèm danh sách việc nhỏ + gán từng việc trong một POST.
    """

    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []
        self.created_task_ids = []

    def tearDown(self):
        with app.app_context():
            for task_id in self.created_task_ids:
                TaskComment.query.filter_by(task_id=task_id).delete()
                TaskSubmission.query.filter_by(task_id=task_id).delete()
                TaskAssignment.query.filter_by(task_id=task_id).delete()
                TaskItem.query.filter_by(task_id=task_id).delete()
                TaskParticipant.query.filter_by(task_id=task_id).delete()
                TaskFormField.query.filter_by(task_id=task_id).delete()
                Task.query.filter_by(id=task_id).delete()
            for user_id in self.created_user_ids:
                TaskParticipant.query.filter_by(user_id=user_id).delete()
                TaskAssignment.query.filter_by(user_id=user_id).delete()
                TaskSubmission.query.filter_by(submitted_by=user_id).delete()
                TaskComment.query.filter_by(user_id=user_id).delete()
                User.query.filter_by(id=user_id).delete()
            db.session.commit()

    def _admin(self):
        with app.app_context():
            return (
                User.query.filter_by(username="admin").first()
                or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            )

    def _login(self, user_id, is_admin=True):
        with app.app_context():
            user = db.session.get(User, user_id)
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
                sess["is_admin"] = is_admin
                sess["session_version"] = int(user.session_version or 0)
                sess["csrf_token"] = "wizard-test-csrf"
                sess["last_active"] = datetime.now().timestamp()
                sess["login_nonce"] = "wizard-test"

    def _create_user(self, unit_area, unit_key):
        with app.app_context():
            user = User(
                username=f"wizard_{uuid.uuid4().hex[:8]}",
                fullname=f"Cán bộ {uuid.uuid4().hex[:6]}",
                unit_area=unit_area,
                unit_key=unit_key,
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.created_user_ids.append(user.id)
            return user.id

    def test_outline_parse_endpoint_returns_rows(self):
        admin = self._admin()
        self._login(admin.id)

        document = Document()
        document.add_paragraph("ĐỀ CƯƠNG")
        document.add_paragraph("1. Việc nhỏ A")
        document.add_paragraph("2. Việc nhỏ B")
        buffer = io.BytesIO()
        document.save(buffer)

        response = self.client.post(
            "/tasks/outline-parse",
            data={"outline_file": (io.BytesIO(buffer.getvalue()), "de-cuong.docx"), "csrf_token": "wizard-test-csrf"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        # Mỗi mục (heading có số hiệu) là một row; tiêu đề giữ số hiệu mục.
        self.assertEqual([row["title"] for row in payload["rows"]], ["1. Việc nhỏ A", "2. Việc nhỏ B"])

    def test_delete_task_with_assignments_and_submissions(self):
        """Xóa công việc OUTLINE đã có assignment + submission (draft) phải sạch."""
        admin = self._admin()
        self._login(admin.id)
        self._create_user("Đội A", "a")

        response = self.client.post(
            "/tasks",
            data={
                "task_mode": "OUTLINE",
                "title": "Wizard xóa có giao việc",
                "description": "Xóa thử",
                "csrf_token": "wizard-test-csrf",
                "item_title": ["1.1. Mục A"],
                "item_content": ["- Dòng 1\n- Dòng 2"],
                "item_report_kind": ["narrative"],
                "item_assign_type": ["unit"],
                "item_domains": ["doi-a"],
                "item_role_ids": [""],
                "item_user_ids": [""],
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            task = (
                Task.query.filter_by(title="Wizard xóa có giao việc")
                .order_by(Task.id.desc())
                .first()
            )
            self.assertIsNotNone(task)
            task_id = task.id
            self.assertGreater(TaskAssignment.query.filter_by(task_id=task_id).count(), 0)
            self.assertGreater(TaskSubmission.query.filter_by(task_id=task_id).count(), 0)

        delete_response = self.client.post(f"/tasks/{task_id}/delete", data={"csrf_token": "wizard-test-csrf"}, follow_redirects=True)
        self.assertEqual(delete_response.status_code, 200)
        with app.app_context():
            self.assertIsNone(Task.query.filter_by(id=task_id).first())
            self.assertEqual(TaskItem.query.filter_by(task_id=task_id).count(), 0)
            self.assertEqual(TaskAssignment.query.filter_by(task_id=task_id).count(), 0)
            self.assertEqual(TaskSubmission.query.filter_by(task_id=task_id).count(), 0)

    def test_create_outline_task_with_items_in_one_post(self):
        admin = self._admin()
        self._login(admin.id)
        unit_a_id = self._create_user("Đội A", "a")
        unit_b_id = self._create_user("Đội B", "b")

        response = self.client.post(
            "/tasks",
            data={
                "task_mode": "OUTLINE",
                "title": "Wizard giao việc theo đề cương",
                "description": "Tạo từ wizard",
                "csrf_token": "wizard-test-csrf",
                "item_title": ["Việc nhỏ 1", "Việc nhỏ 2"],
                "item_report_kind": ["narrative", "number"],
                "item_attachment_required": ["0"],
                "item_assign_type": ["unit", "unit"],
                "item_domains": ["doi-a", "doi-b"],
                "item_role_ids": ["", ""],
                "item_user_ids": ["", ""],
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            task = (
                Task.query.filter_by(title="Wizard giao việc theo đề cương")
                .order_by(Task.id.desc())
                .first()
            )
            self.assertIsNotNone(task)
            self.created_task_ids.append(task.id)
            items = (
                TaskItem.query.filter_by(task_id=task.id)
                .order_by(TaskItem.sort_order.asc())
                .all()
            )
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0].report_kind, "narrative")
            self.assertEqual(items[1].report_kind, "number")
            assignment_0 = TaskAssignment.query.filter_by(task_id=task.id, task_item_id=items[0].id).all()
            assignment_1 = TaskAssignment.query.filter_by(task_id=task.id, task_item_id=items[1].id).all()
            self.assertEqual([a.user_id for a in assignment_0], [unit_a_id])
            self.assertEqual([a.user_id for a in assignment_1], [unit_b_id])


if __name__ == "__main__":
    unittest.main()
