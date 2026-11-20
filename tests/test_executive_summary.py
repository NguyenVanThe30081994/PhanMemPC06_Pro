# -*- coding: utf-8 -*-
"""
Kiểm thử màn hình & API Tổng hợp nhanh Lãnh đạo (/tong-quan-lanh-dao, /api/executive-summary,
/api/executive-summary/export):
- Tổng hợp số liệu hồ sơ theo từng lĩnh vực, trạng thái (quá hạn / sắp hạn / đang xử lý / xong) và CT10 extra_json.
- Xếp hạng đơn vị cần đôn đốc theo mức độ ưu tiên & lọc theo lĩnh vực / từ khóa / chỉ sát-quá hạn.
- Phân quyền phạm vi: Quản trị hệ thống & Lãnh đạo - Chỉ huy CAT xem toàn tỉnh; Cán bộ CAX chỉ xem đơn vị mình.
- Xuất Excel tổng hợp 3 sheet hợp lệ & hiển thị chuẩn trên Desktop + Mobile User-Agent.
"""

import io
import json
import unittest
from datetime import date, timedelta

import openpyxl

from app import app
from models import AppRole, Dossier, Task, TaskAssignment, Unit, User, db


class ExecutiveSummaryTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self._created_task_ids = []
        with app.app_context():
            Dossier.query.delete()
            db.session.commit()

            admin_role = AppRole.query.filter_by(name="Quản trị hệ thống").first()
            cat_leader_role = AppRole.query.filter_by(name="Lãnh đạo - Chỉ huy CAT").first()
            if not cat_leader_role:
                cat_leader_role = AppRole(
                    name="Lãnh đạo - Chỉ huy CAT",
                    perms=json.dumps({"p_dash_view": 1, "p_task_view": 1}),
                )
                db.session.add(cat_leader_role)
                db.session.commit()

            cax_role = AppRole.query.filter_by(name="Cán bộ CAX").first()
            if not cax_role:
                cax_role = AppRole(
                    name="Cán bộ CAX",
                    perms=json.dumps({"p_dash_view": 1, "p_task_view": 1, "p_task_exec": 1}),
                )
                db.session.add(cax_role)
                db.session.commit()

            def _ensure_unit(code, name):
                u = Unit.query.filter_by(code=code).first()
                if not u:
                    u = Unit(code=code, name=name, level="commune", is_active=True)
                    db.session.add(u)
                    db.session.commit()
                return u

            self.u_a = _ensure_unit("exec_unit_a", "Phường Minh Xuân Exec")
            self.u_b = _ensure_unit("exec_unit_b", "Xã Hồng Sơn Exec")
            self.u_a_code = self.u_a.code
            self.u_b_code = self.u_b.code

            def _ensure_user(username, fullname, role_id, unit_id=None, unit_key="", unit_area=""):
                usr = User.query.filter_by(username=username).first()
                if not usr:
                    usr = User(
                        username=username,
                        fullname=fullname,
                        role_id=role_id,
                        unit_id=unit_id,
                        unit_key=unit_key,
                        unit_area=unit_area,
                        is_active=True,
                        must_change_password=False,
                    )
                    usr.set_password("StrongPass1!")
                    db.session.add(usr)
                    db.session.commit()
                return usr.id

            self.admin_uid = _ensure_user("exec_admin_test", "Admin Exec", admin_role.id)
            self.leader_uid = _ensure_user("exec_cat_leader", "Lãnh đạo CAT Test", cat_leader_role.id)
            self.cax_a_uid = _ensure_user(
                "exec_cax_a",
                "Cán bộ Minh Xuân",
                cax_role.id,
                self.u_a.id,
                self.u_a.code,
                self.u_a.name,
            )

            today = date.today()
            samples = [
                # Đơn vị A: 1 quá hạn tạm trú, 1 sắp hạn tạm trú, 1 xong thường trú
                Dossier(
                    ma_ho_so="EX-001",
                    so_ho_so="EX-001",
                    category_tab="tam_tru",
                    loai="cu-tru",
                    thu_tuc="Đăng ký tạm trú",
                    ngay_tiep_nhan=today - timedelta(days=5),
                    han_tra=today - timedelta(days=1),
                    has_deadline=True,
                    trang_thai="dang_xu_ly",
                    unit_code=self.u_a.code,
                    unit_key=self.u_a.code,
                    unit_area=self.u_a.name,
                    created_by=self.admin_uid,
                ),
                Dossier(
                    ma_ho_so="EX-002",
                    so_ho_so="EX-002",
                    category_tab="tam_tru",
                    loai="cu-tru",
                    thu_tuc="Đăng ký tạm trú",
                    ngay_tiep_nhan=today,
                    han_tra=today + timedelta(days=1),
                    has_deadline=True,
                    trang_thai="dang_xu_ly",
                    unit_code=self.u_a.code,
                    unit_key=self.u_a.code,
                    unit_area=self.u_a.name,
                    created_by=self.admin_uid,
                ),
                Dossier(
                    ma_ho_so="EX-003",
                    so_ho_so="EX-003",
                    category_tab="thuong_tru",
                    loai="cu-tru",
                    thu_tuc="Đăng ký thường trú",
                    ngay_tiep_nhan=today - timedelta(days=3),
                    han_tra=today + timedelta(days=4),
                    has_deadline=True,
                    trang_thai="da_tra",
                    unit_code=self.u_a.code,
                    unit_key=self.u_a.code,
                    unit_area=self.u_a.name,
                    created_by=self.admin_uid,
                ),
                # Đơn vị B: 2 quá hạn (1 tạm trú + 1 CT10 có qua_han=3), 1 đang xử lý thường trú
                Dossier(
                    ma_ho_so="EX-004",
                    so_ho_so="EX-004",
                    category_tab="tam_tru",
                    loai="cu-tru",
                    thu_tuc="Đăng ký tạm trú",
                    ngay_tiep_nhan=today - timedelta(days=6),
                    han_tra=today - timedelta(days=2),
                    has_deadline=True,
                    trang_thai="dang_xu_ly",
                    unit_code=self.u_b.code,
                    unit_key=self.u_b.code,
                    unit_area=self.u_b.name,
                    created_by=self.admin_uid,
                ),
                Dossier(
                    ma_ho_so="EX-005",
                    so_ho_so="EX-005",
                    category_tab="ct10",
                    loai="cu-tru",
                    thu_tuc="Phiếu XM CT10",
                    ngay_tiep_nhan=today,
                    han_tra=today,
                    has_deadline=False,
                    trang_thai="dang_xu_ly",
                    unit_code=self.u_b.code,
                    unit_key=self.u_b.code,
                    unit_area=self.u_b.name,
                    extra_json=json.dumps({"tong_phieu": 10, "da_tra_loi": 6, "chua_tra_loi": 4, "qua_han": 3}),
                    created_by=self.admin_uid,
                ),
                Dossier(
                    ma_ho_so="EX-006",
                    so_ho_so="EX-006",
                    category_tab="thuong_tru",
                    loai="cu-tru",
                    thu_tuc="Đăng ký thường trú",
                    ngay_tiep_nhan=today,
                    han_tra=today + timedelta(days=6),
                    has_deadline=True,
                    trang_thai="dang_xu_ly",
                    unit_code=self.u_b.code,
                    unit_key=self.u_b.code,
                    unit_area=self.u_b.name,
                    created_by=self.admin_uid,
                ),
            ]
            db.session.add_all(samples)

            # Thêm 1 công việc mẫu để kiểm chứng phần tổng hợp báo cáo công việc
            t = Task(
                title="Báo cáo tiến độ Đề án 06 tuần",
                deadline=today - timedelta(days=1),
                author_id=self.admin_uid,
            )
            db.session.add(t)
            db.session.flush()
            self._created_task_ids.append(t.id)
            db.session.add(
                TaskAssignment(task_id=t.id, user_id=self.cax_a_uid, status="pending")
            )
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            Dossier.query.delete()
            if self._created_task_ids:
                TaskAssignment.query.filter(TaskAssignment.task_id.in_(self._created_task_ids)).delete(
                    synchronize_session=False
                )
                Task.query.filter(Task.id.in_(self._created_task_ids)).delete(
                    synchronize_session=False
                )
            db.session.commit()

    def _login_as(self, uid):
        import time
        with app.app_context():
            usr = db.session.get(User, uid)
            role = db.session.get(AppRole, usr.role_id) if usr.role_id else None
            sv = int(getattr(usr, "session_version", 0) or 0) if usr else 0
        with self.client.session_transaction() as sess:
            sess["uid"] = uid
            sess["username"] = usr.username
            sess["fullname"] = usr.fullname
            sess["role_name"] = role.name if role else ""
            sess["session_version"] = sv
            sess["last_active"] = time.time()
            sess["csrf_token"] = "test-csrf-token"

    def test_province_leader_and_admin_see_full_executive_summary(self):
        for uid in (self.admin_uid, self.leader_uid):
            self._login_as(uid)
            page = self.client.get("/tong-quan-lanh-dao")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Tổng hợp số liệu", page.get_data(as_text=True))

            res = self.client.get("/api/executive-summary")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["is_province_wide"])
            self.assertEqual(data["scope_label"], "Toàn tỉnh")

            ov = data["overall"]
            self.assertEqual(ov["total"], 6)
            self.assertEqual(ov["overdue"], 3)  # EX-001, EX-004, EX-005 (CT10 qua_han=3)
            self.assertEqual(ov["soon"], 1)     # EX-002
            self.assertEqual(ov["pending"], 1)  # EX-006
            self.assertEqual(ov["done"], 1)     # EX-003
            self.assertEqual(ov["urgent"], 4)

            # CT10 extra_json totals
            self.assertEqual(data["ct10_totals"]["tong_phieu"], 10)
            self.assertEqual(data["ct10_totals"]["da_tra_loi"], 6)
            self.assertEqual(data["ct10_totals"]["qua_han"], 3)

            # Đơn vị B có 2 quá hạn -> xếp #1 trước Đơn vị A (1 quá hạn)
            self.assertEqual(len(data["by_unit"]), 2)
            self.assertEqual(data["by_unit"][0]["unit_code"], self.u_b_code)
            self.assertEqual(data["by_unit"][0]["overdue"], 2)
            self.assertEqual(data["by_unit"][1]["unit_code"], self.u_a_code)
            self.assertEqual(data["by_unit"][1]["overdue"], 1)

            # Lọc theo lĩnh vực tam_tru
            res_tab = self.client.get("/api/executive-summary?tab=tam_tru")
            self.assertEqual(res_tab.status_code, 200)
            data_tab = res_tab.get_json()
            self.assertEqual(data_tab["filtered_overall"]["total"], 3)
            self.assertEqual(data_tab["filtered_overall"]["overdue"], 2)
            self.assertEqual(data_tab["filtered_overall"]["soon"], 1)

            # Tổng hợp báo cáo công việc
            self.assertGreaterEqual(data["tasks"]["total_tasks"], 1)
            self.assertGreaterEqual(data["tasks"]["overdue_tasks"], 1)

    def test_unit_officer_is_strictly_scoped_to_own_unit(self):
        self._login_as(self.cax_a_uid)
        res = self.client.get("/api/executive-summary")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["is_province_wide"])
        self.assertEqual(data["overall"]["total"], 3)
        self.assertEqual(data["overall"]["overdue"], 1)
        self.assertEqual(data["overall"]["soon"], 1)
        self.assertEqual(data["overall"]["done"], 1)
        self.assertEqual(len(data["by_unit"]), 1)
        self.assertEqual(data["by_unit"][0]["unit_code"], self.u_a_code)

    def test_export_excel_contains_three_sheets_and_mobile_ua_renders(self):
        self._login_as(self.admin_uid)
        mob = self.client.get(
            "/tong-quan-lanh-dao",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"},
        )
        self.assertEqual(mob.status_code, 200)
        self.assertIn("Tổng hợp số liệu", mob.get_data(as_text=True))

        exp = self.client.get("/api/executive-summary/export")
        self.assertEqual(exp.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(exp.data))
        self.assertEqual(wb.sheetnames, ["Theo lĩnh vực", "Theo đơn vị", "Báo cáo công việc"])


if __name__ == "__main__":
    unittest.main()
