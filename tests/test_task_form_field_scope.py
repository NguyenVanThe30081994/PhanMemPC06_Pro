# -*- coding: utf-8 -*-
import json
import uuid
import unittest
from datetime import date, datetime

from app import app
from models import AppRole, Task, TaskAssignment, TaskComment, TaskFormField, TaskParticipant, TaskSubmission, User, db


class TaskFormFieldScopeRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.task_id = None
        self.user_ids = []
        self.csrf_token = "task-form-field-scope-csrf"

    def tearDown(self):
        with app.app_context():
            if self.task_id:
                TaskAssignment.query.filter_by(task_id=self.task_id).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=self.task_id).delete()
                TaskAssignment.query.filter_by(task_id=self.task_id).delete()
                TaskFormField.query.filter_by(task_id=self.task_id).delete()
                TaskParticipant.query.filter_by(task_id=self.task_id).delete()
                TaskComment.query.filter_by(task_id=self.task_id).delete()
                Task.query.filter_by(id=self.task_id).delete()
            for user_id in self.user_ids:
                User.query.filter_by(id=user_id).delete()
            db.session.commit()

    def _create_assignee(self, fullname, unit_area, unit_key):
        with app.app_context():
            # Vai trò hạn chế (không quản trị): is_admin tính từ role_id trong
            # DB; vai trò quản trị sẽ khiến mọi người dùng nhìn thấy toàn bộ
            # đơn vị, làm hỏng các test kiểm tra scope theo đơn vị.
            role = AppRole.query.filter_by(name="Cán bộ CAX").first() or AppRole.query.order_by(AppRole.id.asc()).first()
            username = f"form_scope_{uuid.uuid4().hex[:8]}"
            user = User(
                username=username,
                fullname=fullname,
                role_id=getattr(role, "id", None),
                unit_area=unit_area,
                unit_key=unit_key,
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.user_ids.append(user.id)
            return user

    def _login_user(self, user):
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
            sess["is_admin"] = False
            sess["session_version"] = int(user.session_version or 0)
            sess["csrf_token"] = self.csrf_token
            sess["last_active"] = datetime.now().timestamp()
            sess["login_nonce"] = "task-form-field-scope-test"

    def _create_form_task(self, target_user, other_user):
        with app.app_context():
            task = Task(
                title="[TEST] Biểu mẫu theo đơn vị",
                content="Mỗi đơn vị chỉ nhìn thấy trường được giao.",
                deadline=date.today(),
                author_id=target_user.id,
                author_name=target_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FORM",
                                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.flush()
            db.session.add_all(
                [
                    TaskAssignment(
                        task_id=task.id,
                        user_id=target_user.id,
                        assignee_type="user",
                        title_snapshot=task.title,
                        status="assigned",
                        assigned_at=datetime.now(),
                    ),
                    TaskAssignment(
                        task_id=task.id,
                        user_id=other_user.id,
                        assignee_type="user",
                        title_snapshot=task.title,
                        status="assigned",
                        assigned_at=datetime.now(),
                    ),
                ]
            )
            db.session.add_all(
                [
                    TaskFormField(
                        task_id=task.id,
                        field_key="chi_tieu_minh_xuan",
                        field_label="Chỉ tiêu Minh Xuân",
                        field_type="number",
                        is_required=True,
                        sort_order=0,
                        field_options_json=json.dumps(
                            {"target_type": "unit", "target_unit_domains": ["minh-xuan"]},
                            ensure_ascii=False,
                        ),
                    ),
                    TaskFormField(
                        task_id=task.id,
                        field_key="chi_tieu_tan_quang",
                        field_label="Chỉ tiêu Tân Quang",
                        field_type="number",
                        is_required=True,
                        sort_order=1,
                        field_options_json=json.dumps(
                            {"target_type": "unit", "target_unit_domains": ["tan-quang"]},
                            ensure_ascii=False,
                        ),
                    ),
                ]
            )
            db.session.commit()
            self.task_id = task.id

    def _form_submit_pane(self, html):
        marker = 'id="pane-form-submit"'
        start = html.find(marker)
        if start < 0:
            return html
        end = html.find('id="pane-form-list"', start)
        return html[start:end] if end > start else html[start:]

    def _form_list_pane(self, html):
        marker = 'id="pane-form-list"'
        start = html.find(marker)
        if start < 0:
            return html
        end = html.find('id="pane-form-submit"', start)
        return html[start:end] if end > start else html[start:]

    def test_task_detail_only_shows_visible_form_fields_for_each_unit(self):
        target_user = self._create_assignee("Đồng chí Minh Xuân", "Công an phường Minh Xuân", "minh-xuan")
        other_user = self._create_assignee("Đồng chí Tân Quang", "Công an phường Tân Quang", "tan-quang")
        self._create_form_task(target_user, other_user)

        self._login_user(target_user)
        target_response = self.client.get(f"/tasks/{self.task_id}")
        self.assertEqual(target_response.status_code, 200)
        target_html = self._form_submit_pane(target_response.get_data(as_text=True))
        self.assertIn("Chỉ tiêu Minh Xuân", target_html)
        self.assertNotIn("Chỉ tiêu Tân Quang", target_html)

        self._login_user(other_user)
        other_response = self.client.get(f"/tasks/{self.task_id}")
        self.assertEqual(other_response.status_code, 200)
        other_html = self._form_submit_pane(other_response.get_data(as_text=True))
        self.assertIn("Chỉ tiêu Tân Quang", other_html)
        self.assertNotIn("Chỉ tiêu Minh Xuân", other_html)

    def test_submit_form_only_persists_visible_scoped_fields(self):
        target_user = self._create_assignee("Đồng chí Minh Xuân", "Công an phường Minh Xuân", "minh-xuan")
        other_user = self._create_assignee("Đồng chí Tân Quang", "Công an phường Tân Quang", "tan-quang")
        self._create_form_task(target_user, other_user)
        self._login_user(target_user)

        response = self.client.post(
            f"/tasks/{self.task_id}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "form_field_chi_tieu_minh_xuan": "11",
            },
        )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            assignment = TaskAssignment.query.filter_by(task_id=self.task_id, user_id=target_user.id).first()
            submission = TaskSubmission.query.filter_by(task_id=self.task_id, assignment_id=assignment.id).order_by(TaskSubmission.id.desc()).first()
            self.assertIsNotNone(submission)
            self.assertEqual(assignment.status, "submitted")
            payload = json.loads(submission.payload_json)
            self.assertEqual(payload["chi_tieu_minh_xuan"], 11.0)
            self.assertNotIn("chi_tieu_tan_quang", payload)

    def test_submit_form_syncs_same_unit_assignments_when_assigned_by_unit(self):
        first_user = self._create_assignee("Đồng chí Minh Xuân A", "Công an phường Minh Xuân", "minh-xuan")
        second_user = self._create_assignee("Đồng chí Minh Xuân B", "Công an phường Minh Xuân", "minh-xuan")
        with app.app_context():
            task = Task(
                title="[TEST] Biểu mẫu giao theo đơn vị",
                content="Một đơn vị chỉ cần một người nộp.",
                deadline=date.today(),
                author_id=first_user.id,
                author_name=first_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FORM",
                                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.flush()
            db.session.add_all(
                [
                    TaskAssignment(
                        task_id=task.id,
                        user_id=first_user.id,
                        assignee_type="unit",
                        title_snapshot=task.title,
                        status="assigned",
                        assigned_at=datetime.now(),
                    ),
                    TaskAssignment(
                        task_id=task.id,
                        user_id=second_user.id,
                        assignee_type="unit",
                        title_snapshot=task.title,
                        status="assigned",
                        assigned_at=datetime.now(),
                    ),
                ]
            )
            db.session.add(
                TaskFormField(
                    task_id=task.id,
                    field_key="chi_tieu_minh_xuan",
                    field_label="Chỉ tiêu Minh Xuân",
                    field_type="number",
                    is_required=True,
                    sort_order=0,
                    field_options_json=json.dumps(
                        {"target_type": "unit", "target_unit_domains": ["minh-xuan"]},
                        ensure_ascii=False,
                    ),
                )
            )
            db.session.commit()
            self.task_id = task.id

        self._login_user(first_user)
        response = self.client.post(
            f"/tasks/{self.task_id}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "form_field_chi_tieu_minh_xuan": "17",
            },
        )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            first_assignment = TaskAssignment.query.filter_by(task_id=self.task_id, user_id=first_user.id).first()
            second_assignment = TaskAssignment.query.filter_by(task_id=self.task_id, user_id=second_user.id).first()
            self.assertEqual(first_assignment.status, "submitted")
            self.assertEqual(second_assignment.status, "submitted")
            self.assertEqual(second_assignment.last_submission_id, first_assignment.last_submission_id)

    def test_task_detail_shows_unit_submission_hint_for_form_task(self):
        first_user = self._create_assignee("Đồng chí Minh Xuân A", "Công an phường Minh Xuân", "minh-xuan")
        second_user = self._create_assignee("Đồng chí Minh Xuân B", "Công an phường Minh Xuân", "minh-xuan")
        with app.app_context():
            task = Task(
                title="[TEST] Biểu mẫu giao theo đơn vị",
                content="Một đơn vị chỉ cần một người nộp.",
                deadline=date.today(),
                author_id=first_user.id,
                author_name=first_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FORM",
                                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.flush()
            db.session.add_all(
                [
                    TaskAssignment(task_id=task.id, user_id=first_user.id, assignee_type="unit", title_snapshot=task.title, status="assigned", assigned_at=datetime.now()),
                    TaskAssignment(task_id=task.id, user_id=second_user.id, assignee_type="unit", title_snapshot=task.title, status="assigned", assigned_at=datetime.now()),
                ]
            )
            db.session.add(
                TaskFormField(
                    task_id=task.id,
                    field_key="chi_tieu_minh_xuan",
                    field_label="Chỉ tiêu Minh Xuân",
                    field_type="number",
                    is_required=True,
                    sort_order=0,
                    field_options_json=json.dumps(
                        {"target_type": "unit", "target_unit_domains": ["minh-xuan"]},
                        ensure_ascii=False,
                    ),
                )
            )
            db.session.commit()
            self.task_id = task.id

        self._login_user(first_user)
        with self.client.session_transaction() as sess:
            sess["role_id"] = None
        response = self.client.get(f"/tasks/{self.task_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Nộp theo đơn vị", html)
        self.assertIn("hệ thống sẽ ghi nhận cho cả đơn vị", html)
        self.assertIn("Phạm Vi Đã Phát Hành", html)
        self.assertIn("Đơn vị Công an phường Minh Xuân", html)
        self.assertIn("Chỉ tiêu Minh Xuân", html)

    def test_form_list_only_shows_same_unit_group_for_executor(self):
        first_user = self._create_assignee("Đồng chí Minh Xuân A", "Công an phường Minh Xuân", "minh-xuan")
        second_user = self._create_assignee("Đồng chí Tân Quang", "Công an phường Tân Quang", "tan-quang")
        author_user = self._create_assignee("Đồng chí Tác giả", "Phòng PC06", "pc06")
        with app.app_context():
            task = Task(
                title="[TEST] Biểu mẫu giao theo đơn vị",
                content="Mỗi đơn vị chỉ theo dõi phần của mình.",
                deadline=date.today(),
                author_id=author_user.id,
                author_name=author_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FORM",
                                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.flush()
            db.session.add_all(
                [
                    TaskAssignment(task_id=task.id, user_id=first_user.id, assignee_type="unit", title_snapshot=task.title, status="submitted", assigned_at=datetime.now()),
                    TaskAssignment(task_id=task.id, user_id=second_user.id, assignee_type="unit", title_snapshot=task.title, status="submitted", assigned_at=datetime.now()),
                ]
            )
            db.session.commit()
            self.task_id = task.id

        self._login_user(first_user)
        with self.client.session_transaction() as sess:
            sess["role_id"] = None
        response = self.client.get(f"/tasks/{self.task_id}")

        self.assertEqual(response.status_code, 200)
        list_html = self._form_list_pane(response.get_data(as_text=True))
        self.assertIn("Đồng chí Minh Xuân A", list_html)
        self.assertNotIn("Đồng chí Tân Quang", list_html)
        self.assertNotIn("Công an phường Tân Quang", list_html)


if __name__ == "__main__":
    unittest.main()
