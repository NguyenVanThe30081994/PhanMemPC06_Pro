# -*- coding: utf-8 -*-
"""
Kiểm thử hồi quy luồng giao việc theo đơn vị & phân quyền xem/báo cáo công việc:
1. /api/outline-assignees trả đầy đủ `code` + `key` cho đơn vị và `unit_name` + `unit` cho cán bộ.
2. _users_for_unit giải mã chính xác theo cả `Unit.code` (có dấu gạch dưới), tên hiển thị, và `category_item:<id>`.
3. POST /api/create-outline-task gán `unit_domains` tạo TaskAssignment có `user_id` + `unit_id` và bỏ qua giá trị rỗng/preset marker.
4. Tài khoản `Cán bộ báo cáo` chỉ thấy công việc liên quan đến đơn vị/cá nhân mình, thấy biểu mẫu và gửi báo cáo thành công.
"""
import json
import re
import unittest

from app import app
from models import (
    AppRole,
    Task,
    TaskAssignment,
    TaskItem,
    TaskParticipant,
    TaskSubmission,
    Unit,
    User,
    db,
)
from services.task_units import _users_for_unit
from services.task_workspace_views import _outline_display_and_secondary


class UnitAssignmentAndVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created_unit_ids = []
        self.created_user_ids = []
        self.created_role_ids = []
        self.created_task_ids = []
        self.csrf_token = "test-unit-assign-csrf"

        with app.app_context():
            self.role_sys_admin = AppRole.query.filter_by(name="Quản trị hệ thống").first()
            if not self.role_sys_admin:
                self.role_sys_admin = AppRole(
                    name="Quản trị hệ thống",
                    perms=json.dumps({"p_sys_view": 1, "p_task_view": 1, "p_task_process": 1, "p_task_exec": 1}),
                )
                db.session.add(self.role_sys_admin)
                db.session.flush()
                self.created_role_ids.append(self.role_sys_admin.id)

            self.role_bc = AppRole(
                name="Cán bộ báo cáo TestScope",
                perms=json.dumps({"p_dash_view": 1, "p_task_view": 1, "p_task_exec": 1}),
            )
            self.role_unit_admin = AppRole(
                name="Quản trị đơn vị TestScope",
                perms=json.dumps({"p_dash_view": 1, "p_task_view": 1, "p_task_process": 1, "p_task_exec": 1}),
            )
            db.session.add_all([self.role_bc, self.role_unit_admin])
            db.session.flush()
            self.role_bc_id = self.role_bc.id
            self.role_unit_admin_id = self.role_unit_admin.id
            self.created_role_ids.extend([self.role_bc_id, self.role_unit_admin_id])

            self.unit_stp = Unit(
                code="so_tu_phap_test",
                name="Sở Tư pháp Test",
                level="province",
                is_active=True,
            )
            self.unit_other = Unit(
                code="so_khac_test",
                name="Sở Khác Test",
                level="province",
                is_active=True,
            )
            db.session.add_all([self.unit_stp, self.unit_other])
            db.session.flush()
            self.unit_stp_id = self.unit_stp.id
            self.unit_other_id = self.unit_other.id
            self.created_unit_ids.extend([self.unit_stp_id, self.unit_other_id])

            self.admin_sys = User(
                username="sys_admin_unit_test",
                fullname="Quản trị Hệ thống Test",
                role_id=self.role_sys_admin.id,
                is_active=True,
                must_change_password=False,
            )
            self.admin_sys.set_password("TuyenQuang@2026")

            self.bc_stp = User(
                username="bc_sotuphap_test",
                fullname="Cán bộ Sở Tư pháp Test",
                unit_id=self.unit_stp.id,
                unit_area="category_item:999999",
                unit_key="so_tu_phap_test",
                role_id=self.role_bc.id,
                is_active=True,
                must_change_password=False,
            )
            self.bc_stp.set_password("TuyenQuang@2026")

            self.admin_other = User(
                username="admin_sokhac_test",
                fullname="Quản trị Sở Khác Test",
                unit_id=self.unit_other.id,
                unit_area="Sở Khác Test",
                unit_key="so_khac_test",
                role_id=self.role_unit_admin.id,
                is_active=True,
                must_change_password=False,
            )
            self.admin_other.set_password("TuyenQuang@2026")

            db.session.add_all([self.admin_sys, self.bc_stp, self.admin_other])
            db.session.commit()
            self.admin_sys_id = self.admin_sys.id
            self.bc_stp_id = self.bc_stp.id
            self.admin_other_id = self.admin_other.id
            self.created_user_ids.extend([self.admin_sys_id, self.bc_stp_id, self.admin_other_id])

    def tearDown(self):
        with app.app_context():
            for tid in self.created_task_ids:
                TaskAssignment.query.filter_by(task_id=tid).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=tid).delete()
                TaskAssignment.query.filter_by(task_id=tid).delete()
                TaskParticipant.query.filter_by(task_id=tid).delete()
                TaskItem.query.filter_by(task_id=tid).delete()
                Task.query.filter_by(id=tid).delete()
            for uid in self.created_user_ids:
                User.query.filter_by(id=uid).delete()
            for unid in self.created_unit_ids:
                Unit.query.filter_by(id=unid).delete()
            for rid in self.created_role_ids:
                AppRole.query.filter_by(id=rid).delete()
            db.session.commit()

    def _login(self, user, is_admin=False):
        user_id = getattr(user, "id", user)
        with app.app_context():
            u = db.session.get(User, user_id)
            u_data = {
                "uid": u.id,
                "username": u.username,
                "fullname": u.fullname,
                "role_id": u.role_id,
                "session_version": u.session_version or 0,
            }
        with self.client.session_transaction() as sess:
            sess["uid"] = u_data["uid"]
            sess["username"] = u_data["username"]
            sess["fullname"] = u_data["fullname"]
            sess["role_id"] = u_data["role_id"]
            sess["is_admin"] = is_admin
            sess["session_version"] = u_data["session_version"]
            sess["csrf_token"] = self.csrf_token

    def test_outline_assignees_contains_code_and_unit_name(self):
        self._login(self.admin_sys_id, is_admin=True)
        res = self.client.get("/api/outline-assignees")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        units = data.get("units") or []
        users = data.get("users") or []
        stp_unit = next((u for u in units if u.get("key") == "so_tu_phap_test"), None)
        self.assertIsNotNone(stp_unit)
        self.assertEqual(stp_unit.get("code"), "so_tu_phap_test")
        bc_user = next((u for u in users if u.get("username") == "bc_sotuphap_test"), None)
        self.assertIsNotNone(bc_user)
        self.assertIn("unit_name", bc_user)

    def test_users_for_unit_resolves_by_code_and_display_name(self):
        with app.app_context():
            by_code = _users_for_unit("so_tu_phap_test")
            by_name = _users_for_unit("Sở Tư pháp Test")
            self.assertIn(self.bc_stp_id, [u.id for u in by_code])
            self.assertIn(self.bc_stp_id, [u.id for u in by_name])

    def test_assign_unit_outline_task_and_reporter_can_submit(self):
        self._login(self.admin_sys_id, is_admin=True)
        payload = {
            "title": "Đề cương giao cho Sở Tư pháp Test",
            "tree": {
                "title": "Đề cương test",
                "sections": [
                    {
                        "id": "sec-1",
                        "label": "I",
                        "text": "Nhiệm vụ chung",
                        "type": "section",
                        "children": [
                            {"id": "m-1", "label": "1.1", "text": "Báo cáo tiến độ", "type": "h2", "children": []}
                        ],
                    }
                ],
            },
            "assignments": {
                "m-1": {
                    "unit_domains": ["so_tu_phap_test", None, "cac_so_ban_nganh"],
                    "labels": ["Sở Tư pháp Test"],
                }
            },
        }
        res = self.client.post(
            "/api/create-outline-task",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(res.status_code, 200)
        assigned_task_id = res.get_json()["task_id"]
        self.created_task_ids.append(assigned_task_id)

        # Tạo thêm 1 task giao riêng cho Sở Khác để kiểm tra cách ly quyền xem
        other_payload = {
            "title": "Đề cương giao riêng Sở Khác Test",
            "tree": payload["tree"],
            "assignments": {
                "m-1": {"unit_domains": ["so_khac_test"], "labels": ["Sở Khác Test"]}
            },
        }
        res_other = self.client.post(
            "/api/create-outline-task",
            data=json.dumps(other_payload),
            content_type="application/json",
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(res_other.status_code, 200)
        other_task_id = res_other.get_json()["task_id"]
        self.created_task_ids.append(other_task_id)

        with app.app_context():
            rows = TaskAssignment.query.filter_by(task_id=assigned_task_id).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].user_id, self.bc_stp_id)
            self.assertEqual(rows[0].unit_id, self.unit_stp_id)
            item_id = rows[0].task_item_id

        # Đăng nhập bc_sotuphap_test: không thấy task của Sở Khác, thấy và báo cáo được task của mình
        self._login(self.bc_stp_id, is_admin=False)
        list_res = self.client.get("/tasks")
        self.assertEqual(list_res.status_code, 200)
        list_html = list_res.get_data(as_text=True)
        self.assertIn("Đề cương giao cho Sở Tư pháp Test", list_html)
        self.assertNotIn("Đề cương giao riêng Sở Khác Test", list_html)

        forbidden_res = self.client.get(f"/tasks/{other_task_id}", follow_redirects=False)
        self.assertEqual(forbidden_res.status_code, 302)
        self.assertTrue((forbidden_res.headers.get("Location") or "").endswith("/tasks"))
        forbidden_followed = self.client.get(f"/tasks/{other_task_id}", follow_redirects=True)
        self.assertNotIn("Đề cương giao riêng Sở Khác Test", forbidden_followed.get_data(as_text=True))

        detail_res = self.client.get(f"/tasks/{assigned_task_id}")
        self.assertEqual(detail_res.status_code, 200)
        detail_html = detail_res.get_data(as_text=True)
        self.assertIn("Gửi báo cáo", detail_html)

        claim_res = self.client.post(
            f"/tasks/{assigned_task_id}/update_status",
            data={"csrf_token": self.csrf_token, "task_item_id": str(item_id)},
            follow_redirects=False,
        )
        self.assertEqual(claim_res.status_code, 302)

        report_res = self.client.post(
            f"/tasks/{assigned_task_id}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "task_item_id": str(item_id),
                "report_content": "Sở Tư pháp đã hoàn thành báo cáo đúng tiến độ.",
            },
            follow_redirects=False,
        )
        self.assertEqual(report_res.status_code, 302)

        with app.app_context():
            updated_row = TaskAssignment.query.filter_by(
                task_id=assigned_task_id, user_id=self.bc_stp_id
            ).first()
            self.assertIsNotNone(updated_row.last_submission_id)
            self.assertEqual(updated_row.status, "submitted")

        # Quản trị Sở Khác (dù có p_task_process=1) không được phép xem việc chỉ giao cho Sở Tư pháp
        self._login(self.admin_other_id, is_admin=False)
        other_forbidden = self.client.get(f"/tasks/{assigned_task_id}", follow_redirects=False)
        self.assertEqual(other_forbidden.status_code, 302)
        self.assertTrue((other_forbidden.headers.get("Location") or "").endswith("/tasks"))

    def test_admin_dashboard_metrics_match_reporter_scope(self):
        import re as _re

        self._login(self.admin_sys_id, is_admin=True)
        other_payload = {
            "title": "Đề cương riêng Sở Khác Dashboard",
            "tree": {
                "title": "Đề cương",
                "sections": [
                    {
                        "id": "sec-1",
                        "label": "I",
                        "text": "Phần I",
                        "type": "section",
                        "children": [{"id": "m-1", "label": "1.1", "text": "Mục 1", "type": "h2", "children": []}],
                    }
                ],
            },
            "assignments": {"m-1": {"unit_domains": ["so_khac_test"], "labels": ["Sở Khác Test"]}},
        }
        res_other = self.client.post(
            "/api/create-outline-task",
            data=json.dumps(other_payload),
            content_type="application/json",
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(res_other.status_code, 200)
        self.created_task_ids.append(res_other.get_json()["task_id"])

        # Trước khi Sở Tư pháp được giao việc: /admin của bc_sotuphap_test phải báo Số công việc = 0
        self._login(self.bc_stp_id, is_admin=False)
        dash_before = self.client.get("/admin")
        self.assertEqual(dash_before.status_code, 200)
        dash_html = dash_before.get_data(as_text=True)
        self.assertNotIn("Giao việc theo đề cương", dash_html)
        m_before = _re.search(r"Số công việc</span>\s*<strong[^>]*>(\d+)</strong>", dash_html)
        self.assertIsNotNone(m_before)
        self.assertEqual(m_before.group(1), "0")

        # Giao 1 việc cho Sở Tư pháp Test -> /admin của bc_sotuphap_test tăng lên đúng 1
        self._login(self.admin_sys_id, is_admin=True)
        stp_payload = dict(other_payload)
        stp_payload["title"] = "Đề cương giao Sở Tư pháp Dashboard"
        stp_payload["assignments"] = {"m-1": {"unit_domains": ["so_tu_phap_test"], "labels": ["Sở Tư pháp Test"]}}
        res_stp = self.client.post(
            "/api/create-outline-task",
            data=json.dumps(stp_payload),
            content_type="application/json",
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(res_stp.status_code, 200)
        self.created_task_ids.append(res_stp.get_json()["task_id"])

        self._login(self.bc_stp_id, is_admin=False)
        dash_after = self.client.get("/admin")
        self.assertEqual(dash_after.status_code, 200)
        m_after = _re.search(r"Số công việc</span>\s*<strong[^>]*>(\d+)</strong>", dash_after.get_data(as_text=True))
        self.assertIsNotNone(m_after)
        self.assertEqual(m_after.group(1), "1")

    def test_assign_bullet_and_plus_nodes_and_dedupe_overlap(self):
        self._login(self.admin_sys_id, is_admin=True)
        resp = self.client.post(
            "/api/create-outline-task",
            json={
                "title": "Đề cương gán mục lá bullet",
                "deadline": "2026-12-31",
                "task_type": "report",
                "tree": {
                    "title": "Đề cương gán mục lá bullet",
                    "sections": [
                        {
                            "id": "h1-1",
                            "type": "h1",
                            "label": "I",
                            "text": "KẾT QUẢ CÁC MẶT CÔNG TÁC",
                            "children": [
                                {
                                    "id": "h2-1",
                                    "type": "h2",
                                    "label": "1",
                                    "text": "Công tác tham mưu",
                                    "children": [
                                        {
                                            "id": "h3-1",
                                            "type": "h3",
                                            "label": "1.1",
                                            "text": "Các Sở, ban, ngành",
                                            "children": [
                                                {
                                                    "id": "b-1",
                                                    "type": "bullet",
                                                    "label": "-",
                                                    "text": "Tham mưu với Tỉnh ủy, UBND ban hành kế hoạch triển khai Đề án 06.",
                                                    "children": [
                                                        {
                                                            "id": "p-1",
                                                            "type": "plus",
                                                            "label": "+",
                                                            "text": "Chi tiết phụ tổng hợp số liệu.",
                                                            "children": [],
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                "assignments": {
                    "b-1": {
                        "unit_domains": ["so_tu_phap_test"],
                        "user_ids": [self.bc_stp_id],
                        "labels": ["Sở Tư pháp Test", "BC STP Test"],
                    }
                },
            },
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body.get("success"), body)
        self.assertEqual(body.get("items_created"), 1)
        self.assertEqual(body.get("assignments_created"), 1)

        task_id = int(body["task_id"])
        self.created_task_ids.append(task_id)

        with app.app_context():
            items = TaskItem.query.filter_by(task_id=task_id).all()
            self.assertEqual(len(items), 1)
            self.assertIn("[1.1]", items[0].title)
            self.assertIn("Tham mưu với Tỉnh ủy", items[0].title)
            self.assertIn("Tham mưu với Tỉnh ủy, UBND ban hành kế hoạch triển khai Đề án 06.", items[0].content or "")
            self.assertIn("+ Chi tiết phụ tổng hợp số liệu.", items[0].content or "")
            assigns = TaskAssignment.query.filter_by(task_id=task_id).all()
            self.assertEqual(len(assigns), 1)
            self.assertEqual(assigns[0].user_id, self.bc_stp_id)
            self.assertEqual(assigns[0].unit_id, self.unit_stp_id)
            item_id = items[0].id

        self._login(self.bc_stp_id, is_admin=False)
        detail = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Gửi báo cáo", detail.get_data(as_text=True))

        submit_resp = self.client.post(
            f"/tasks/{task_id}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "task_item_id": str(item_id),
                "report_content": "Sở Tư pháp Test đã hoàn thành tham mưu.",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_resp.status_code, 302)
        with app.app_context():
            ta = TaskAssignment.query.filter_by(task_id=task_id, user_id=self.bc_stp_id).first()
            self.assertIsNotNone(ta)
            self.assertEqual(ta.status, "submitted")

    def test_single_unit_with_two_accounts_counts_as_one_submission_and_returns_cleanly(self):
        with app.app_context():
            peer_user = User(
                username="admin_sotuphap_peer_test",
                fullname="Quản trị Sở Tư pháp Peer Test",
                unit_id=self.unit_stp_id,
                unit_area="Sở Tư pháp Test",
                unit_key="so_tu_phap_test",
                role_id=self.role_unit_admin_id,
                is_active=True,
                must_change_password=False,
            )
            peer_user.set_password("TuyenQuang@2026")
            db.session.add(peer_user)
            db.session.commit()
            peer_uid = peer_user.id
            self.created_user_ids.append(peer_uid)

        self._login(self.admin_sys_id, is_admin=True)
        resp = self.client.post(
            "/api/create-outline-task",
            json={
                "title": "Đề cương kiểm thử gộp lượt nộp 1 đơn vị",
                "tree": {
                    "title": "Đề cương",
                    "sections": [
                        {
                            "id": "sec-1",
                            "type": "section",
                            "label": "I",
                            "text": "Kết quả công tác",
                            "children": [
                                {
                                    "id": "h1-1",
                                    "type": "h1",
                                    "label": "1",
                                    "text": "Công tác tham mưu",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                "assignments": {
                    "h1-1": {
                        "unit_domains": ["so_tu_phap_test"],
                        "user_ids": [],
                        "labels": ["Sở Tư pháp Test"],
                    }
                },
            },
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        task_id = int(body["task_id"])
        self.created_task_ids.append(task_id)

        with app.app_context():
            item = TaskItem.query.filter_by(task_id=task_id).first()
            self.assertIsNotNone(item)
            item_id = item.id
            assigns = TaskAssignment.query.filter_by(task_id=task_id).all()
            self.assertEqual(len(assigns), 2)
            self.assertEqual({a.assignee_type for a in assigns}, {"unit"})

        detail = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(detail.status_code, 200)
        html_before = detail.get_data(as_text=True)
        self.assertIn("0/1", html_before)
        self.assertNotIn("0/2", html_before)
        self.assertIn("1 lượt giao", html_before)
        self.assertNotIn("2 lượt giao", html_before)
        self.assertNotIn('id="tab-outline-group-', html_before)
        self.assertNotIn("Thiết lập đầu mục", html_before)
        self.assertNotIn('id="tab-outline-create"', html_before)
        self.assertNotIn('id="pane-outline-create"', html_before)
        self.assertNotIn('id="taskWorkspaceTabs"', html_before)
        self.assertNotIn("data-review-open data-item-id=", html_before)
        self.assertNotIn("Ngăn kéo duyệt", html_before)

        synth_resp = self.client.get(f"/tasks/{task_id}/items/{item_id}/synthesis-data")
        self.assertEqual(synth_resp.status_code, 200)
        synth_data = synth_resp.get_json()
        self.assertTrue(synth_data.get("ok"))
        self.assertEqual(len(synth_data.get("submissions") or []), 1)

        self._login(self.bc_stp_id, is_admin=False)
        submit_resp = self.client.post(
            f"/tasks/{task_id}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "task_item_id": str(item_id),
                "report_content": "Đơn vị đã hoàn thành báo cáo.",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_resp.status_code, 302)

        with app.app_context():
            assigns_after = TaskAssignment.query.filter_by(task_id=task_id).all()
            self.assertEqual({a.status for a in assigns_after}, {"submitted"})
            rep_aid = assigns_after[0].id

        self._login(self.admin_sys_id, is_admin=True)
        detail_after = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(detail_after.status_code, 200)
        html_after = detail_after.get_data(as_text=True)
        self.assertIn("1/1", html_after)
        self.assertIn("100%", html_after)
        self.assertNotIn("2/2", html_after)
        self.assertNotIn('class="pc-inline-report-text', html_after)
        self.assertIn("data-review-open data-item-id=", html_after)
        self.assertIn("Xem báo cáo", html_after)
        payload_match = re.search(
            r'<script type="application/json" class="pc-matrix-row-json"[^>]*>(.*?)</script>',
            html_after,
            re.DOTALL,
        )
        self.assertIsNotNone(payload_match)
        review_payload = json.loads(payload_match.group(1))
        self.assertEqual(
            review_payload["units"][0]["entries"][0]["report_text"],
            "Đơn vị đã hoàn thành báo cáo.",
        )
        self.assertEqual(html_after.count("fa-file-word"), 1)
        self.assertIn("Xuất báo cáo Word", html_after)
        self.assertIn('id="outlineReviewDrawer"', html_after)
        self.assertNotIn("Ngăn kéo duyệt", html_after)
        self.assertLess(
            html_after.index('id="outlineReviewDrawer"'),
            html_after.index("document.getElementById('outlineReviewDrawer')"),
        )
        self.assertLess(
            html_after.index("bootstrap.bundle.min.js"),
            html_after.index("document.getElementById('outlineReviewDrawer')"),
        )
        self.assertIn('class="pc-return-box d-none', html_after)
        self.assertEqual(html_after.count("Trả lại</button>"), 1)

        ret_resp = self.client.post(
            f"/tasks/{task_id}/assignments/{rep_aid}/return",
            data={"csrf_token": self.csrf_token, "return_reason": "Bổ sung số liệu"},
            follow_redirects=False,
        )
        self.assertEqual(ret_resp.status_code, 302)

        with app.app_context():
            assigns_returned = TaskAssignment.query.filter_by(task_id=task_id).all()
            self.assertEqual({a.status for a in assigns_returned}, {"returned"})

        detail_returned = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(detail_returned.status_code, 200)
        html_returned = detail_returned.get_data(as_text=True)
        self.assertIn("0/1", html_returned)
        self.assertNotIn("0/2", html_returned)
        self.assertIn("Bổ sung số liệu", html_returned)

    def test_multi_unit_outline_keeps_four_columns_without_unit_tabs(self):
        unit_codes = []
        with app.app_context():
            for idx in range(1, 9):
                code = f"xa_scale_test_{idx}"
                unit = Unit(
                    code=code,
                    name=f"Xã Thử Nghiệm {idx}",
                    level="commune",
                    is_active=True,
                )
                db.session.add(unit)
                db.session.flush()
                self.created_unit_ids.append(unit.id)
                user = User(
                    username=f"bc_{code}",
                    fullname=f"Cán bộ {unit.name}",
                    unit_id=unit.id,
                    unit_area=unit.name,
                    unit_key=code,
                    role_id=self.role_bc_id,
                    is_active=True,
                    must_change_password=False,
                )
                user.set_password("TuyenQuang@2026")
                db.session.add(user)
                db.session.flush()
                self.created_user_ids.append(user.id)
                unit_codes.append(code)
            db.session.commit()

        self._login(self.admin_sys_id, is_admin=True)
        resp = self.client.post(
            "/api/create-outline-task",
            json={
                "title": "Đề cương quy mô nhiều đơn vị",
                "tree": {
                    "title": "Đề cương",
                    "sections": [
                        {
                            "id": "sec-1",
                            "type": "section",
                            "label": "I",
                            "text": "Nhiệm vụ",
                            "children": [
                                {
                                    "id": "h1-1",
                                    "type": "h1",
                                    "label": "1",
                                    "text": "Báo cáo đồng loạt",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                "assignments": {
                    "h1-1": {
                        "unit_domains": unit_codes,
                        "user_ids": [],
                        "labels": [f"Xã Thử Nghiệm {i}" for i in range(1, 9)],
                    }
                },
            },
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        task_id = int(resp.get_json()["task_id"])
        self.created_task_ids.append(task_id)

        detail = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(detail.status_code, 200)
        html = detail.get_data(as_text=True)
        self.assertNotIn('id="tab-outline-group-', html)
        self.assertIn("Đơn vị thực hiện", html)
        self.assertIn("Đã nộp: 0/8 đơn vị", html)
        self.assertIn('id="outlineMatrixUnitFilter"', html)
        self.assertIn("Xã Thử Nghiệm 8", html)

    def test_outline_display_and_secondary_deduplicates_prefixed_and_truncated_items(self):
        long_text = (
            "Tham mưu với Tỉnh ủy, UBND tỉnh, Ban chỉ đạo, Tổ công tác ban hành các Chỉ thị, "
            "Nghị quyết, chương trình, kế hoạch, văn bản triển khai Đề án 06, cải cách TTHC, "
            "chuyển đổi số tại địa phương theo chỉ đạo của Chính phủ và các văn bản khác do "
            "đơn vị chủ động tham mưu ban hành trong năm công tác."
        )
        truncated_leaf = TaskItem(
            title=("[1.1] " + long_text)[:255],
            content=f"– {long_text}",
        )
        display_title, secondary_text = _outline_display_and_secondary(truncated_leaf)
        self.assertIn(long_text, display_title)
        self.assertTrue(display_title.startswith("[1.1] "))
        self.assertEqual(secondary_text, "")

        leaf_with_subline = TaskItem(
            title="[1.2] Kiểm tra định kỳ",
            content="– Kiểm tra định kỳ\n+ Lập biên bản chi tiết từng đơn vị",
        )
        display_sub, secondary_sub = _outline_display_and_secondary(leaf_with_subline)
        self.assertEqual(display_sub, "[1.2] Kiểm tra định kỳ")
        self.assertEqual(secondary_sub, "+ Lập biên bản chi tiết từng đơn vị")

        guided_heading = TaskItem(
            title="1. Công tác tuyên truyền",
            guide_text="Nêu rõ số lượng tin bài và hiệu quả truyền thông",
            content="– Đẩy mạnh tuyên truyền trên cổng thông tin",
        )
        display_guided, secondary_guided = _outline_display_and_secondary(guided_heading)
        self.assertEqual(display_guided, "1. Công tác tuyên truyền")
        self.assertEqual(secondary_guided, "Nêu rõ số lượng tin bài và hiệu quả truyền thông")

    def test_outline_long_bullet_detail_page_no_duplicate_note_and_renders_clamp(self):
        long_bullet_text = (
            "Tham mưu với Tỉnh ủy, UBND tỉnh, Ban chỉ đạo, Tổ công tác ban hành các Chỉ thị, "
            "Nghị quyết, chương trình, kế hoạch, văn bản triển khai Đề án 06, cải cách TTHC, "
            "chuyển đổi số tại địa phương (theo chỉ đạo của Ban Chỉ đạo Trung ương, Ban Chỉ đạo Chính phủ; "
            "tại các Nghị quyết của Chính phủ và các văn bản khác do đơn vị chủ động tham mưu ban hành)."
        )
        unique_tail = "do đơn vị chủ động tham mưu ban hành)."

        self._login(self.admin_sys_id, is_admin=True)
        resp = self.client.post(
            "/api/create-outline-task",
            json={
                "title": "Đề cương kiểm tra chống lặp và thu gọn",
                "tree": {
                    "title": "Đề cương",
                    "sections": [
                        {
                            "id": "sec-1",
                            "type": "section",
                            "label": "1.1",
                            "text": "Các Sở, ban, ngành",
                            "children": [
                                {
                                    "id": "bullet-1",
                                    "type": "bullet",
                                    "label": "",
                                    "text": long_bullet_text,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                "assignments": {
                    "bullet-1": {
                        "unit_domains": ["so_tu_phap_test"],
                        "user_ids": [],
                        "labels": ["Sở Tư pháp Test"],
                    }
                },
            },
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        task_id = int(resp.get_json()["task_id"])
        self.created_task_ids.append(task_id)

        detail_admin = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(detail_admin.status_code, 200)
        html_admin = detail_admin.get_data(as_text=True)
        # Kiểm tra phần tiêu đề đầy đủ có mặt đúng 1 lần trong bảng (và 1 lần trong JSON drawer), không có khối pc-matrix-item-note trùng lặp
        self.assertIn(unique_tail, html_admin)
        self.assertNotIn('<div class="pc-matrix-item-note', html_admin)
        self.assertIn('data-clamp-block', html_admin)
        self.assertIn('pc-clamp-text pc-clamp-3', html_admin)
        self.assertIn('data-clamp-toggle', html_admin)

        self._login(self.bc_stp_id, is_admin=False)
        detail_unit = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(detail_unit.status_code, 200)
        html_unit = detail_unit.get_data(as_text=True)
        self.assertIn(unique_tail, html_unit)
        self.assertNotIn('<div class="pc-matrix-item-note', html_unit)
        self.assertIn('data-clamp-block', html_unit)


if __name__ == "__main__":
    unittest.main()
