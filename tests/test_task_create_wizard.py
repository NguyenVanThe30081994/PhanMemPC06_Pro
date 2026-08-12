# -*- coding: utf-8 -*-
import io
import unittest
import uuid
from datetime import datetime

from app import app
from models import (
    CategoryGroup,
    CategoryItem,
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
            created_category_ids = getattr(self, "created_category_ids", []) or []
            if created_category_ids:
                for cid in created_category_ids:
                    CategoryItem.query.filter_by(group_id=cid).delete()
                    CategoryGroup.query.filter_by(id=cid).delete()
                db.session.commit()
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

    def test_outline_parse_keeps_content_starting_with_so_ban_nganh(self):
        """Nội dung bắt đầu bằng 'Các sở, ban, ngành, Ủy ban nhân dân xã, phường'
        (vd mục 7.2, 8 trong đề cương) phải được giữ làm row chứ không bị lọc nhầm."""
        admin = self._admin()
        self._login(admin.id)

        document = Document()
        document.add_paragraph("I. KẾT QUẢ CÁC MẶT CÔNG TÁC")
        document.add_paragraph("7.2. Về nguồn nhân lực")
        document.add_paragraph("Các sở, ban, ngành, Ủy ban nhân dân xã, phường báo cáo kết quả tập huấn, đào tạo chuyển đổi số trên nền tảng “Bình dân học vụ số”.")
        buffer = io.BytesIO()
        document.save(buffer)

        response = self.client.post(
            "/tasks/outline-parse",
            data={"outline_file": (io.BytesIO(buffer.getvalue()), "de-cuong.docx"), "csrf_token": "wizard-test-csrf"},
            content_type="multipart/form-data",
        )
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        rows = payload["rows"]
        self.assertEqual(len(rows), 1)
        self.assertIn("tập huấn, đào tạo chuyển đổi số", rows[0]["title"])
        self.assertIn("7.2", rows[0]["heading"])

    def test_outline_parse_table_without_stt_column(self):
        """Bảng nhiệm vụ KHÔNG có cột số thứ tự (vd: Nhiệm vụ | Đơn vị | Thời hạn)
        vẫn phải tách được từng dòng thành nội dung gán, dò vai trò cột theo tiêu đề
        và gợi ý đơn vị từ cột 'Đơn vị'."""
        admin = self._admin()
        self._login(admin.id)
        with app.app_context():
            group = CategoryGroup.query.filter_by(name="Đơn vị").first()
            if not group:
                group = CategoryGroup(name="Đơn vị", code="don-vi")
                db.session.add(group)
                db.session.flush()
            item = CategoryItem.query.filter_by(group_id=group.id, name="Sở Tư pháp").first()
            if not item:
                item = CategoryItem(group_id=group.id, name="Sở Tư pháp", code="sotuphap", is_active=True)
                db.session.add(item)
            db.session.commit()
            self.created_category_ids = [group.id, item.id]

        document = Document()
        table = document.add_table(rows=3, cols=3)
        for j, header in enumerate(["Nhiệm vụ", "Đơn vị", "Thời hạn"]):
            table.rows[0].cells[j].text = header
        table.rows[1].cells[0].text = "Xây dựng kế hoạch"
        table.rows[1].cells[1].text = "Sở Tư pháp"
        table.rows[1].cells[2].text = "31/7"
        table.rows[2].cells[0].text = "Đào tạo kỹ năng số"
        table.rows[2].cells[1].text = "Sở Khoa học và Công nghệ"
        table.rows[2].cells[2].text = "30/9"
        buffer = io.BytesIO()
        document.save(buffer)

        response = self.client.post(
            "/tasks/outline-parse",
            data={"outline_file": (io.BytesIO(buffer.getvalue()), "bang-khong-stt.docx"), "csrf_token": "wizard-test-csrf"},
            content_type="multipart/form-data",
        )
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        rows = payload["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "Xây dựng kế hoạch")
        self.assertIn("Cơ quan chủ trì: Sở Tư pháp", rows[0]["content"])
        self.assertIn("Thời gian: 31/7", rows[0]["content"])
        # Cột "Đơn vị" (bỏ dấu -> 'on vi') vẫn phải gợi ý đơn vị
        self.assertIn("sotuphap", rows[0]["unit_domains"])

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
