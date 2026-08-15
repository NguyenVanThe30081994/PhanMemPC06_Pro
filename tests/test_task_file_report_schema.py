# -*- coding: utf-8 -*-
import json
import uuid
import unittest
from datetime import date, datetime

from app import app
from models import (
    AppRole,
    Task,
    TaskAssignment,
    TaskComment,
    TaskParticipant,
    TaskSubmission,
    User,
    db,
)


class TaskFileReportSchemaRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.task_id = None
        self.assignee_ids = []
        self.csrf_token = "task-file-report-schema-csrf"

    def tearDown(self):
        with app.app_context():
            if self.task_id:
                TaskAssignment.query.filter_by(task_id=self.task_id).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=self.task_id).delete()
                TaskComment.query.filter_by(task_id=self.task_id).delete()
                TaskParticipant.query.filter_by(task_id=self.task_id).delete()
                TaskAssignment.query.filter_by(task_id=self.task_id).delete()
                Task.query.filter_by(id=self.task_id).delete()
            for assignee_id in self.assignee_ids:
                User.query.filter_by(id=assignee_id).delete()
            db.session.commit()

    def _create_assignee(self, fullname="Đồng chí File Schema", unit_area="Công an phường Minh Xuân", unit_key="minhxuan"):
        with app.app_context():
            # Vai trò hạn chế (không quản trị): is_admin tính từ role_id trong
            # DB; vai trò quản trị sẽ khiến mọi người dùng nhìn thấy toàn bộ
            # đơn vị, làm hỏng các test kiểm tra scope theo đơn vị.
            role = AppRole.query.filter_by(name="Cán bộ CAX").first() or AppRole.query.order_by(AppRole.id.asc()).first()
            username = f"file_schema_{uuid.uuid4().hex[:8]}"
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
            self.assignee_ids.append(user.id)
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
            sess["login_nonce"] = "task-file-report-schema-test"

    def _file_list_pane(self, html):
        marker = 'id="pane-file-list"'
        start = html.find(marker)
        if start < 0:
            return html
        end = html.find('id="pane-file-submit"', start)
        return html[start:end] if end > start else html[start:]

    def _create_file_task(self, assignee):
        with app.app_context():
            task = Task(
                title="[TEST] Báo cáo file có schema",
                content="Thu thập báo cáo theo schema cấu trúc.",
                deadline=date.today(),
                author_id=assignee.id,
                author_name=assignee.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FILE",
                                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "narrative": {
                            "enabled": True,
                            "required": True,
                            "label": "Nhận định tổng hợp",
                            "placeholder": "Nhập nhận định",
                        },
                        "attachment": {
                            "enabled": False,
                            "required": False,
                            "label": "Tệp minh chứng",
                        },
                        "fields": [
                            {
                                "key": "tong_so_ho_so",
                                "label": "Tổng số hồ sơ",
                                "type": "number",
                                "required": True,
                                "placeholder": "0",
                            },
                            {
                                "key": "ghi_chu",
                                "label": "Ghi chú",
                                "type": "textarea",
                                "required": False,
                                "placeholder": "Ghi chú thêm",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
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

    def test_task_detail_renders_structured_file_report_form(self):
        assignee = self._create_assignee()
        self._create_file_task(assignee)
        self._login_user(assignee)

        response = self.client.get(f"/tasks/{self.task_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Nhận định tổng hợp", html)
        self.assertIn("Tổng số hồ sơ", html)
        self.assertIn("Ghi chú", html)

    def test_task_detail_hides_unit_targeted_fields_for_other_unit(self):
        target_user = self._create_assignee(fullname="Đồng chí Minh Xuân", unit_area="Công an phường Minh Xuân", unit_key="minhxuan")
        other_user = self._create_assignee(fullname="Đồng chí Tân Quang", unit_area="Công an phường Tân Quang", unit_key="tanquang")
        with app.app_context():
            task = Task(
                title="[TEST] Báo cáo file theo đơn vị",
                content="Schema chia theo đơn vị.",
                deadline=date.today(),
                author_id=target_user.id,
                author_name=target_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FILE",
                                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "narrative": {"enabled": False},
                        "attachment": {"enabled": False},
                        "fields": [
                            {
                                "key": "chi_tieu_minh_xuan",
                                "label": "Chỉ tiêu Minh Xuân",
                                "type": "number",
                                "required": True,
                                "target_type": "unit",
                                "target_unit_domains": ["Công an phường Minh Xuân"],
                            },
                            {
                                "key": "chi_tieu_tan_quang",
                                "label": "Chỉ tiêu Tân Quang",
                                "type": "number",
                                "required": True,
                                "target_type": "unit",
                                "target_unit_domains": ["Công an phường Tân Quang"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.flush()
            for user in [target_user, other_user]:
                db.session.add(
                    TaskAssignment(
                        task_id=task.id,
                        user_id=user.id,
                        assignee_type="user",
                        title_snapshot=task.title,
                        status="assigned",
                        assigned_at=datetime.now(),
                    )
                )
            db.session.commit()
            self.task_id = task.id

        self._login_user(target_user)
        target_response = self.client.get(f"/tasks/{self.task_id}")
        self.assertEqual(target_response.status_code, 200)
        target_html = target_response.get_data(as_text=True)
        self.assertIn("Chỉ tiêu Minh Xuân", target_html)
        self.assertNotIn("Chỉ tiêu Tân Quang", target_html)

        self._login_user(other_user)
        other_response = self.client.get(f"/tasks/{self.task_id}")
        self.assertEqual(other_response.status_code, 200)
        other_html = other_response.get_data(as_text=True)
        self.assertIn("Chỉ tiêu Tân Quang", other_html)
        self.assertNotIn("Chỉ tiêu Minh Xuân", other_html)

    def test_submit_file_report_persists_structured_payload(self):
        assignee = self._create_assignee()
        self._create_file_task(assignee)
        self._login_user(assignee)

        response = self.client.post(
            f"/tasks/{self.task_id}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "report_narrative": "Đã tổng hợp đầy đủ.",
                "report_field_tong_so_ho_so": "12",
                "report_field_ghi_chu": "Không có vướng mắc.",
            },
        )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            assignment = TaskAssignment.query.filter_by(task_id=self.task_id, user_id=assignee.id).first()
            submission = TaskSubmission.query.filter_by(task_id=self.task_id, assignment_id=assignment.id).order_by(TaskSubmission.id.desc()).first()
            self.assertIsNotNone(submission)
            self.assertEqual(assignment.status, "submitted")
            self.assertEqual(submission.narrative_content, "Đã tổng hợp đầy đủ.")

            payload = json.loads(submission.payload_json)
            self.assertEqual(payload["mode"], "structured_task_report")
            self.assertEqual(payload["narrative"], "Đã tổng hợp đầy đủ.")
            self.assertEqual(payload["values"]["tong_so_ho_so"], "12")
            self.assertEqual(payload["values"]["ghi_chu"], "Không có vướng mắc.")

    def test_submit_file_report_syncs_same_unit_assignments_when_assigned_by_unit(self):
        first_user = self._create_assignee(fullname="Đồng chí Minh Xuân A", unit_area="Công an phường Minh Xuân", unit_key="minh-xuan")
        second_user = self._create_assignee(fullname="Đồng chí Minh Xuân B", unit_area="Công an phường Minh Xuân", unit_key="minh-xuan")
        with app.app_context():
            task = Task(
                title="[TEST] Báo cáo file giao theo đơn vị",
                content="Một đơn vị nộp một lần.",
                deadline=date.today(),
                author_id=first_user.id,
                author_name=first_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FILE",
                                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "narrative": {
                            "enabled": True,
                            "required": True,
                            "label": "Nhận định tổng hợp",
                        },
                        "attachment": {"enabled": False, "required": False, "label": "Tệp minh chứng"},
                        "fields": [
                            {"key": "tong_so_ho_so", "label": "Tổng số hồ sơ", "type": "number", "required": True}
                        ],
                    },
                    ensure_ascii=False,
                ),
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
            db.session.commit()
            self.task_id = task.id

        self._login_user(first_user)
        response = self.client.post(
            f"/tasks/{self.task_id}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "report_narrative": "Đơn vị đã tổng hợp.",
                "report_field_tong_so_ho_so": "25",
            },
        )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            first_assignment = TaskAssignment.query.filter_by(task_id=self.task_id, user_id=first_user.id).first()
            second_assignment = TaskAssignment.query.filter_by(task_id=self.task_id, user_id=second_user.id).first()
            self.assertEqual(first_assignment.status, "submitted")
            self.assertEqual(second_assignment.status, "submitted")
            self.assertEqual(second_assignment.last_submission_id, first_assignment.last_submission_id)

    def test_task_detail_shows_unit_submission_hint_for_file_task(self):
        first_user = self._create_assignee(fullname="Đồng chí Minh Xuân A", unit_area="Công an phường Minh Xuân", unit_key="minh-xuan")
        second_user = self._create_assignee(fullname="Đồng chí Minh Xuân B", unit_area="Công an phường Minh Xuân", unit_key="minh-xuan")
        with app.app_context():
            task = Task(
                title="[TEST] Báo cáo file giao theo đơn vị",
                content="Một đơn vị nộp một lần.",
                deadline=date.today(),
                author_id=first_user.id,
                author_name=first_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FILE",
                                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "narrative": {"enabled": True, "required": True, "label": "Nhận định tổng hợp"},
                        "attachment": {"enabled": False, "required": False, "label": "Tệp minh chứng"},
                        "fields": [{"key": "tong_so_ho_so", "label": "Tổng số hồ sơ", "type": "number", "required": True}],
                    },
                    ensure_ascii=False,
                ),
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
            db.session.commit()
            self.task_id = task.id

        self._login_user(first_user)
        response = self.client.get(f"/tasks/{self.task_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Nộp theo đơn vị", html)
        self.assertIn("hệ thống sẽ ghi nhận cho cả đơn vị", html)
        self.assertIn("Phạm Vi Đã Phát Hành", html)
        self.assertIn("Đơn vị Công an phường Minh Xuân", html)
        self.assertIn("Tổng số hồ sơ", html)

    def test_file_list_only_shows_same_unit_group_for_executor(self):
        first_user = self._create_assignee(fullname="Đồng chí Minh Xuân A", unit_area="Công an phường Minh Xuân", unit_key="minh-xuan")
        second_user = self._create_assignee(fullname="Đồng chí Tân Quang", unit_area="Công an phường Tân Quang", unit_key="tan-quang")
        author_user = self._create_assignee(fullname="Đồng chí Tác giả", unit_area="Phòng PC06", unit_key="pc06")
        with app.app_context():
            task = Task(
                title="[TEST] Báo cáo file giao theo đơn vị",
                content="Mỗi đơn vị chỉ theo dõi phần của mình.",
                deadline=date.today(),
                author_id=author_user.id,
                author_name=author_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FILE",
                                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "narrative": {"enabled": True, "required": True, "label": "Nhận định tổng hợp"},
                        "attachment": {"enabled": False, "required": False, "label": "Tệp minh chứng"},
                        "fields": [{"key": "tong_so_ho_so", "label": "Tổng số hồ sơ", "type": "number", "required": True}],
                    },
                    ensure_ascii=False,
                ),
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
        list_html = self._file_list_pane(response.get_data(as_text=True))
        self.assertIn("Đồng chí Minh Xuân A", list_html)
        self.assertNotIn("Đồng chí Tân Quang", list_html)
        self.assertNotIn("Công an phường Tân Quang", list_html)


if __name__ == "__main__":
    unittest.main()
