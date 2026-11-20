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

    def test_form_detail_matches_linear_matrix_collapses_unit_and_shows_return_reason(self):
        first_user = self._create_assignee("Đồng chí Minh Xuân 1", "Công an phường Minh Xuân", "minh-xuan")
        second_user = self._create_assignee("Đồng chí Minh Xuân 2", "Công an phường Minh Xuân", "minh-xuan")
        manager_user = self._create_assignee("Đồng chí Quản trị", "Phòng PC06", "pc06")
        with app.app_context():
            admin_role = AppRole.query.filter_by(name="Quản trị hệ thống").first()
            if admin_role:
                manager_user_obj = db.session.get(User, manager_user.id)
                manager_user_obj.role_id = admin_role.id
                db.session.commit()
            task = Task(
                title="[TEST] Biểu mẫu chuẩn Linear",
                content="Kiểm tra nhất quán với đề cương.",
                deadline=date.today(),
                author_id=manager_user.id,
                author_name=manager_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="FORM",
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.flush()
            a1 = TaskAssignment(
                task_id=task.id,
                user_id=first_user.id,
                assignee_type="unit",
                title_snapshot=task.title,
                status="assigned",
                assigned_at=datetime.now(),
            )
            a2 = TaskAssignment(
                task_id=task.id,
                user_id=second_user.id,
                assignee_type="unit",
                title_snapshot=task.title,
                status="assigned",
                assigned_at=datetime.now(),
            )
            db.session.add_all([a1, a2])
            db.session.add(
                TaskFormField(
                    task_id=task.id,
                    field_key="ho_so_tiep_nhan",
                    field_label="Số hồ sơ tiếp nhận",
                    field_type="number",
                    is_required=True,
                    sort_order=0,
                )
            )
            db.session.commit()
            self.task_id = task.id
            a1_id = a1.id

        # Tạo bản nháp rỗng giả lập _lazy_repair_task_runtime -> không hiện nút Xem báo cáo hay 0/1 trường
        with app.app_context():
            draft_sub = TaskSubmission(
                task_id=self.task_id,
                assignment_id=a1_id,
                submitted_by=first_user.id,
                status="draft",
                payload_json=json.dumps({"mode": "form_report", "values": {}}, ensure_ascii=False),
                submitted_at=None,
            )
            db.session.add(draft_sub)
            db.session.flush()
            a1_row = db.session.get(TaskAssignment, a1_id)
            a1_row.last_submission_id = draft_sub.id
            db.session.commit()

        self._login_user(manager_user)
        before_page = self.client.get(f"/tasks/{self.task_id}")
        self.assertEqual(before_page.status_code, 200)
        before_list_html = self._form_list_pane(before_page.get_data(as_text=True))
        before_table_html = before_list_html[
            before_list_html.index('id="formMatrixTable"'):before_list_html.index("</table>")
        ]
        self.assertIn("Chưa tiếp nhận", before_table_html)
        self.assertNotIn("Xem báo cáo", before_table_html)
        self.assertNotIn("data-review-open", before_table_html)
        self.assertNotIn("Đã nhập 0/1 trường", before_table_html)

        # Cán bộ 1 nộp số liệu -> 2 tài khoản cùng đơn vị gộp thành 1 lượt nộp duy nhất
        self._login_user(first_user)
        with self.client.session_transaction() as sess:
            sess["role_id"] = None
        submit_res = self.client.post(
            f"/tasks/{self.task_id}/submit_report",
            data={"csrf_token": self.csrf_token, "form_field_ho_so_tiep_nhan": "25"},
        )
        self.assertEqual(submit_res.status_code, 302)

        # Giao diện của cán bộ nộp không còn thanh tab thừa khi chỉ có 1 chế độ làm việc
        reporter_page = self.client.get(f"/tasks/{self.task_id}")
        reporter_html = reporter_page.get_data(as_text=True)
        self.assertNotIn('id="taskWorkspaceTabs"', reporter_html)
        self.assertIn("Phần việc cần nộp", self._form_submit_pane(reporter_html))

        # Giao diện quản lý dùng bảng Linear gọn gàng, gộp đơn vị, ẩn form cũ
        self._login_user(manager_user)
        manager_page = self.client.get(f"/tasks/{self.task_id}")
        self.assertEqual(manager_page.status_code, 200)
        manager_html = manager_page.get_data(as_text=True)
        self.assertIn("1 lượt giao · Đã nộp <strong>1/1</strong> (100%)", manager_html)
        list_html = self._form_list_pane(manager_html)
        self.assertIn('id="formMatrixTable"', list_html)
        self.assertIn("Xem báo cáo", list_html)
        self.assertIn(f'data-item-id="form-{a1_id}"', list_html)
        self.assertIn("Cộng gộp số liệu tự động", list_html)
        self.assertNotIn("Tổng quan theo vai trò", list_html)
        self.assertNotIn("Tổng quan theo đơn vị", list_html)
        self.assertNotIn("Chi tiết theo cán bộ", list_html)
        self.assertNotIn("Trả lại bổ sung", list_html)

        # Trả lại bài nộp -> đơn vị nhìn thấy lý do yêu cầu bổ sung ngay trong #pane-form-submit
        ret_res = self.client.post(
            f"/tasks/{self.task_id}/assignments/{a1_id}/return",
            data={"csrf_token": self.csrf_token, "return_reason": "Rà lại số liệu tháng 11"},
        )
        self.assertEqual(ret_res.status_code, 302)
        self._login_user(first_user)
        with self.client.session_transaction() as sess:
            sess["role_id"] = None
        returned_page = self.client.get(f"/tasks/{self.task_id}")
        returned_submit_html = self._form_submit_pane(returned_page.get_data(as_text=True))
        self.assertIn("Yêu cầu bổ sung từ người giao: Rà lại số liệu tháng 11", returned_submit_html)

    def test_tasks_page_and_form_assign_page_parallel_workflow(self):
        admin_user = self._create_assignee("Admin Biểu Mẫu", "Hệ thống", "hethong")
        plain_user = self._create_assignee("Cán bộ Thường", "Sở Tư pháp", "sotuphap")
        with app.app_context():
            admin_role = AppRole.query.filter_by(name="Quản trị hệ thống").first()
            if admin_role:
                u = db.session.get(User, admin_user.id)
                u.role_id = admin_role.id
                db.session.commit()
        self._login_user(admin_user)
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
        response = self.client.get("/tasks")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Tạo công việc", html)
        self.assertIn('id="chooseTaskTypeModal"', html)
        self.assertIn("Giao việc theo biểu mẫu", html)
        self.assertIn('href="/bieu-mau-giao-viec"', html)
        self.assertIn('href="/outline-giao-viec"', html)
        self.assertNotIn('data-wizard-source="OUTLINE"', html)
        self.assertNotIn('id="wizardRowAssignModal"', html)

        form_page_res = self.client.get("/bieu-mau-giao-viec")
        self.assertEqual(form_page_res.status_code, 200)
        form_html = form_page_res.get_data(as_text=True)
        self.assertIn("Giao việc theo biểu mẫu", form_html)
        self.assertIn("/api/outline-assignees", form_html)
        self.assertIn("Tải file Excel (.xlsx)", form_html)
        self.assertIn("Kẻ bảng Excel nhanh", form_html)
        self.assertNotIn('data-wizard-source="OUTLINE"', form_html)
        self.assertNotIn('id="wizardRowAssignModal"', form_html)

        self._login_user(plain_user)
        denied = self.client.get("/bieu-mau-giao-viec")
        self.assertEqual(denied.status_code, 403)

    def test_resolve_unit_id_matches_category_item_and_underscored_code(self):
        from models import CategoryItem, Unit
        from routes.admin import _resolve_unit_id
        from services.task_units import _resolve_task_unit_label

        suffix = uuid.uuid4().hex[:6]
        with app.app_context():
            unit = Unit(
                code=f"so_kiem_thu_{suffix}",
                name=f"Sở Kiểm thử {suffix}",
                is_active=True,
            )
            cat_item = CategoryItem(
                code=f"so_kiem_thu_{suffix}",
                name=f"Sở Kiểm thử {suffix}",
                is_active=True,
            )
            db.session.add_all([unit, cat_item])
            db.session.commit()
            try:
                resolved_id = _resolve_unit_id(f"sokiemthu{suffix}", f"category_item:{cat_item.id}")
                self.assertEqual(resolved_id, unit.id)
                self.assertEqual(
                    _resolve_task_unit_label(f"category_item:{cat_item.id}"),
                    f"Sở Kiểm thử {suffix}",
                )
            finally:
                CategoryItem.query.filter_by(id=cat_item.id).delete()
                Unit.query.filter_by(id=unit.id).delete()
                db.session.commit()

    def test_delete_user_cleanly_handles_trusted_device_and_submissions(self):
        from models import UserTrustedDevice
        from routes.admin import _delete_user_cleanly

        victim = self._create_assignee("Tài khoản Xóa Thử", "Sở Tư pháp", "so_tu_phap")
        with app.app_context():
            db.session.add(
                UserTrustedDevice(
                    user_id=victim.id,
                    device_key=f"dev_{uuid.uuid4().hex[:8]}",
                    device_label="Test Browser",
                )
            )
            db.session.commit()
            user_row = db.session.get(User, victim.id)
            _delete_user_cleanly(user_row)
            db.session.commit()
            self.assertIsNone(db.session.get(User, victim.id))
            self.user_ids = [uid for uid in self.user_ids if uid != victim.id]


if __name__ == "__main__":
    unittest.main()
