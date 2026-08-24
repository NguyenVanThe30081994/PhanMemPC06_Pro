# -*- coding: utf-8 -*-
"""Kiểm thử phân quyền và luồng phụ sau tạo việc theo đề cương:

- POST /api/create-outline-task: chỉ người có quyền xử lý module Công việc
  (process) được tạo việc; người thường bị chặn 403.
- Sau khi tạo: có phạm vi giao việc, cầu nối runtime (TaskParticipant),
  thông báo trong ứng dụng cho từng người được giao.
- GET /api/outline-assignees: danh bạ chỉ trả cho người có quyền process.
- Trang /outline-giao-viec: chặn người không đủ quyền.
- POST /tasks/outline-parse: yêu cầu quyền tạo công việc.
"""
import json
import unittest
import uuid
from datetime import datetime

from app import app
from models import (
    AppRole,
    Notification,
    Task,
    TaskAssignment,
    TaskComment,
    TaskItem,
    TaskParticipant,
    TaskSubmission,
    User,
    db,
)


class TaskOutlineCreateApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []
        self.created_role_ids = []
        self.created_task_ids = []
        self.csrf_token = "task-outline-api-csrf"

    def tearDown(self):
        with app.app_context():
            for task_id in self.created_task_ids:
                TaskAssignment.query.filter_by(task_id=task_id).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=task_id).delete()
                TaskAssignment.query.filter_by(task_id=task_id).delete()
                TaskParticipant.query.filter_by(task_id=task_id).delete()
                TaskItem.query.filter_by(task_id=task_id).delete()
                TaskComment.query.filter_by(task_id=task_id).delete()
                Task.query.filter_by(id=task_id).delete()
                Notification.query.filter_by(link=f"/tasks/{task_id}").delete()
            for user_id in self.created_user_ids:
                TaskParticipant.query.filter_by(user_id=user_id).delete()
                TaskAssignment.query.filter_by(user_id=user_id).delete()
                User.query.filter_by(id=user_id).delete()
            for role_id in self.created_role_ids:
                AppRole.query.filter_by(id=role_id).delete()
            db.session.commit()

    # ── Dụng cụ ──────────────────────────────────────────────────────────

    def _admin(self):
        with app.app_context():
            return (
                User.query.filter_by(username="admin").first()
                or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            )

    def _create_role(self, name_suffix, perms):
        with app.app_context():
            role = AppRole(
                name=f"outline_api_{name_suffix}_{uuid.uuid4().hex[:6]}",
                perms=json.dumps(perms),
            )
            db.session.add(role)
            db.session.commit()
            self.created_role_ids.append(role.id)
            return role

    def _create_lead_role(self):
        return self._create_role("lead", {"p_task_process": 1, "p_task_view": 1})

    def _create_plain_role(self):
        return self._create_role("plain", {"p_task_view": 0})

    def _create_user(self, role, fullname):
        with app.app_context():
            user = User(
                username=f"outline_api_{uuid.uuid4().hex[:8]}",
                fullname=fullname,
                role_id=role.id if role else None,
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.created_user_ids.append(user.id)
            return user

    def _login(self, user):
        with app.app_context():
            fresh = db.session.get(User, user.id)
            with self.client.session_transaction() as sess:
                sess["uid"] = fresh.id
                sess["username"] = fresh.username
                sess["fullname"] = fresh.fullname
                sess["unit"] = fresh.unit_area or ""
                sess["unit_area"] = fresh.unit_area or ""
                sess["unit_key"] = fresh.unit_key or ""
                sess["role_id"] = fresh.role_id
                sess["must_change"] = False
                sess["is_admin"] = False
                sess["session_version"] = int(fresh.session_version or 0)
                sess["csrf_token"] = self.csrf_token
                sess["last_active"] = datetime.now().timestamp()
                sess["login_nonce"] = "task-outline-api-test"

    @staticmethod
    def _outline_payload(user):
        tree = {
            "title": "Kế hoạch triển khai",
            "subtitle": "Đề cương kiểm thử API",
            "sections": [
                {
                    "id": "n1",
                    "type": "h2",
                    "label": "I",
                    "text": "Chuẩn bị phương tiện",
                    "children": [{"id": "c1", "type": "bullet", "text": "Rà soát thiết bị"}],
                },
                {
                    "id": "n2",
                    "type": "h2",
                    "label": "II",
                    "text": "Chưa gán ai cả",
                    "children": [],
                },
            ],
        }
        return {
            "tree": tree,
            "title": "[TEST] Việc theo đề cương từ API",
            "deadline": "",
            "assignments": {"n1": {"ids": [user.id]}},
        }

    # ── Kiểm thử ─────────────────────────────────────────────────────────

    def test_create_outline_task_forbidden_without_process_perm(self):
        plain_user = self._create_user(self._create_plain_role(), "Cán bộ thường")
        assignee = self._create_user(self._create_plain_role(), "Người nhận thử")
        self._login(plain_user)

        response = self.client.post(
            "/api/create-outline-task",
            data=json.dumps(self._outline_payload(assignee)),
            content_type="application/json",
            headers={"X-CSRF-Token": self.csrf_token},
        )

        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertIn("quyền", body.get("error", ""))

    def test_create_outline_task_success_syncs_runtime_and_notifies(self):
        lead = self._create_user(self._create_lead_role(), "Đội trưởng API")
        assignee = self._create_user(self._create_plain_role(), "Người nhận API")
        self._login(lead)

        response = self.client.post(
            "/api/create-outline-task",
            data=json.dumps(self._outline_payload(assignee)),
            content_type="application/json",
            headers={"X-CSRF-Token": self.csrf_token},
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertTrue(body.get("success"))
        self.assertEqual(body.get("assignments_created"), 1)
        self.assertEqual(body.get("items_created"), 1)
        self.created_task_ids.append(body["task_id"])

        with app.app_context():
            task = db.session.get(Task, body["task_id"])
            self.assertIsNotNone(task)
            self.assertEqual(task.task_mode, "OUTLINE")

            assignments = TaskAssignment.query.filter_by(task_id=task.id).all()
            self.assertEqual(len(assignments), 1)
            self.assertEqual(assignments[0].user_id, assignee.id)

            # Phạm vi giao việc theo cá nhân đã lưu
            scope = json.loads(task.assignment_scope_json or "{}")
            self.assertEqual(scope.get("mode"), "user")
            self.assertIn(assignee.id, scope.get("user_ids") or [])

            # Cầu nối runtime: người nhận xuất hiện trong TaskParticipant
            participants = TaskParticipant.query.filter_by(
                task_id=task.id, user_id=assignee.id, participant_type="executor"
            ).all()
            self.assertTrue(participants)

            # Thông báo trong ứng dụng cho người được giao
            notif = Notification.query.filter_by(
                user_id=assignee.id, link=f"/tasks/{task.id}"
            ).first()
            self.assertIsNotNone(notif)
            self.assertIn(task.title, notif.msg or "")

    def test_outline_assignees_scoped_by_permission(self):
        plain_user = self._create_user(self._create_plain_role(), "Thường dân")
        visible_member = self._create_user(self._create_plain_role(), "Đồng chí Hiện Diện")

        self._login(plain_user)
        denied = self.client.get("/api/outline-assignees")
        self.assertEqual(denied.status_code, 403)

        admin = self._admin()
        self._login(admin)
        allowed = self.client.get("/api/outline-assignees")
        self.assertEqual(allowed.status_code, 200)
        ids = [u["id"] for u in allowed.get_json().get("users") or []]
        self.assertIn(visible_member.id, ids)

    def test_giao_viec_page_blocked_without_process_perm(self):
        plain_user = self._create_user(self._create_plain_role(), "Không giao việc")
        self._login(plain_user)
        response = self.client.get("/outline-giao-viec")
        self.assertEqual(response.status_code, 403)

    def test_outline_parse_requires_process_permission(self):
        plain_user = self._create_user(self._create_plain_role(), "Không phân tích")
        self._login(plain_user)
        response = self.client.post(
            "/tasks/outline-parse",
            data={},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
