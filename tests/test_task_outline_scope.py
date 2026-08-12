# -*- coding: utf-8 -*-
import uuid
import unittest
from datetime import date, datetime

from app import app
from models import AppRole, Task, TaskAssignment, TaskComment, TaskItem, TaskParticipant, TaskSubmission, User, db


class TaskOutlineScopeRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.task_id = None
        self.user_ids = []
        self.csrf_token = "task-outline-scope-csrf"

    def tearDown(self):
        with app.app_context():
            if self.task_id:
                TaskAssignment.query.filter_by(task_id=self.task_id).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=self.task_id).delete()
                TaskAssignment.query.filter_by(task_id=self.task_id).delete()
                TaskItem.query.filter_by(task_id=self.task_id).delete()
                TaskParticipant.query.filter_by(task_id=self.task_id).delete()
                TaskComment.query.filter_by(task_id=self.task_id).delete()
                Task.query.filter_by(id=self.task_id).delete()
            for user_id in self.user_ids:
                User.query.filter_by(id=user_id).delete()
            db.session.commit()

    def _create_user(self, fullname, unit_area, unit_key):
        with app.app_context():
            role = AppRole.query.order_by(AppRole.id.asc()).first()
            username = f"outline_scope_{uuid.uuid4().hex[:8]}"
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
            sess["login_nonce"] = "task-outline-scope-test"

    def test_outline_detail_only_shows_assigned_items_for_executor(self):
        current_user = self._create_user("Đồng chí Minh Xuân", "Công an phường Minh Xuân", "minh-xuan")
        other_user = self._create_user("Đồng chí Tân Quang", "Công an phường Tân Quang", "tan-quang")
        author_user = self._create_user("Đồng chí Tác giả", "Phòng PC06", "pc06")

        with app.app_context():
            task = Task(
                title="[TEST] Đề cương giao theo đơn vị",
                content="Mỗi đơn vị chỉ xử lý đầu mục của mình.",
                deadline=date.today(),
                author_id=author_user.id,
                author_name=author_user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                task_mode="OUTLINE",
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.flush()

            first_item = TaskItem(
                task_id=task.id,
                title="Đầu mục Minh Xuân",
                report_kind="narrative",
                status="Chưa tiếp nhận",
                sort_order=0,
            )
            second_item = TaskItem(
                task_id=task.id,
                title="Đầu mục Tân Quang",
                report_kind="narrative",
                status="Chưa tiếp nhận",
                sort_order=1,
            )
            db.session.add_all([first_item, second_item])
            db.session.flush()

            db.session.add_all(
                [
                    TaskAssignment(
                        task_id=task.id,
                        task_item_id=first_item.id,
                        user_id=current_user.id,
                        assignee_type="unit",
                        title_snapshot=first_item.title,
                        status="assigned",
                        assigned_at=datetime.now(),
                    ),
                    TaskAssignment(
                        task_id=task.id,
                        task_item_id=second_item.id,
                        user_id=other_user.id,
                        assignee_type="unit",
                        title_snapshot=second_item.title,
                        status="assigned",
                        assigned_at=datetime.now(),
                    ),
                ]
            )
            db.session.commit()
            self.task_id = task.id

        self._login_user(current_user)
        with self.client.session_transaction() as sess:
            sess["role_id"] = None
        response = self.client.get(f"/tasks/{self.task_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Đầu mục Minh Xuân", html)
        self.assertNotIn("Đầu mục Tân Quang", html)


if __name__ == "__main__":
    unittest.main()
