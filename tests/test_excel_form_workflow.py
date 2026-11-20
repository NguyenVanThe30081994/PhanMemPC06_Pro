# -*- coding: utf-8 -*-
import io
import json
import os
import unittest
import uuid
from datetime import datetime

from openpyxl import Workbook, load_workbook

from app import app
from models import (
    AppRole,
    Notification,
    Task,
    TaskAssignment,
    TaskComment,
    TaskFormField,
    TaskParticipant,
    TaskSubmission,
    TaskSubmissionFile,
    User,
    db,
)
from services.excel_form_template import (
    parse_excel_template_layout,
    parse_staged_filename,
)
from services.task_runtime_sync import _submission_has_report_content
from services.task_workspace_helpers import _task_file_path


def _build_merged_indicator_template_bytes():
    """Tạo file .xlsx mẫu có banner, header gộp 2 tầng, 3 dòng chỉ tiêu và dòng Tổng cộng."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Chi tieu"
    ws["A1"] = "BÁO CÁO KẾT QUẢ GIẢI QUYẾT THỦ TỤC HÀNH CHÍNH"
    ws.merge_cells("A1:D1")

    ws["A2"] = "STT"
    ws["B2"] = "Chỉ tiêu báo cáo"
    ws["C2"] = "Hồ sơ tiếp nhận"
    ws["C3"] = "Trực tuyến"
    ws["D3"] = "Trực tiếp"
    ws.merge_cells("A2:A3")
    ws.merge_cells("B2:B3")
    ws.merge_cells("C2:D2")

    rows = [
        ["1", "Hồ sơ đăng ký cư trú", "", ""],
        ["2", "Hồ sơ cấp căn cước", "", ""],
        ["3", "Hồ sơ xác nhận thông tin", "", ""],
    ]
    for r_idx, row in enumerate(rows, start=4):
        for c_idx, val in enumerate(row, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)

    ws["A7"] = "Tổng cộng"
    ws.merge_cells("A7:B7")
    ws["C7"] = "=SUM(C4:C6)"
    ws["D7"] = "=SUM(D4:D6)"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _build_dynamic_merged_template_bytes():
    """Tạo file .xlsx danh sách động (không khóa dòng) có header gộp 2 tầng."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Danh sach"
    ws["A1"] = "THỐNG KÊ HỒ SƠ TỒN ĐỌNG QUÁ HẠN"
    ws.merge_cells("A1:D1")

    ws["A2"] = "STT"
    ws["B2"] = "Tên thủ tục"
    ws["C2"] = "Số liệu hồ sơ"
    ws["C3"] = "Số lượng quá hạn"
    ws["D3"] = "Đã xử lý xong"
    ws.merge_cells("A2:A3")
    ws.merge_cells("B2:B3")
    ws.merge_cells("C2:D2")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class ExcelFormWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.task_ids = []
        self.user_ids = []
        self.staged_files = []
        self.csrf_token = f"excel-csrf-{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        with app.app_context():
            for tid in self.task_ids:
                task = db.session.get(Task, tid)
                if task and task.file_path:
                    fpath = _task_file_path(task.file_path)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                sub_ids = [
                    s.id for s in TaskSubmission.query.filter_by(task_id=tid).all()
                ]
                if sub_ids:
                    for sf in TaskSubmissionFile.query.filter(
                        TaskSubmissionFile.submission_id.in_(sub_ids)
                    ).all():
                        if sf.stored_path and os.path.exists(sf.stored_path):
                            try:
                                os.remove(sf.stored_path)
                            except OSError:
                                pass
                    TaskSubmissionFile.query.filter(
                        TaskSubmissionFile.submission_id.in_(sub_ids)
                    ).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=tid).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=tid).delete()
                TaskAssignment.query.filter_by(task_id=tid).delete()
                TaskFormField.query.filter_by(task_id=tid).delete()
                TaskParticipant.query.filter_by(task_id=tid).delete()
                TaskComment.query.filter_by(task_id=tid).delete()
                Notification.query.filter_by(link=f"/tasks/{tid}").delete()
                Task.query.filter_by(id=tid).delete()
            if self.user_ids:
                Notification.query.filter(Notification.user_id.in_(self.user_ids)).delete(
                    synchronize_session=False
                )
            for uid in self.user_ids:
                User.query.filter_by(id=uid).delete()
            db.session.commit()

            for staged in self.staged_files:
                cleaned = parse_staged_filename(staged)
                if cleaned:
                    spath = _task_file_path(cleaned)
                    if os.path.exists(spath):
                        try:
                            os.remove(spath)
                        except OSError:
                            pass

    def _create_user(self, fullname, unit_area, unit_key, *, admin=False):
        with app.app_context():
            if admin:
                role = AppRole.query.filter_by(name="Quản trị hệ thống").first()
            else:
                role = (
                    AppRole.query.filter_by(name="Cán bộ CAX").first()
                    or AppRole.query.order_by(AppRole.id.asc()).first()
                )
            user = User(
                username=f"excel_u_{uuid.uuid4().hex[:8]}",
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

    def _login(self, user, *, is_admin=False):
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
            sess["is_admin"] = bool(is_admin)
            sess["session_version"] = int(getattr(user, "session_version", 0) or 0)
            sess["csrf_token"] = self.csrf_token
            sess["last_active"] = datetime.now().timestamp()
            sess["login_nonce"] = "excel-form-workflow-test"

    def test_parse_merged_excel_template_preserves_headers_and_indicators(self):
        buf = _build_merged_indicator_template_bytes()
        schema = parse_excel_template_layout(buf, filename="bao_cao_tthc.xlsx")
        self.assertEqual(schema["kind"], "excel_template")
        self.assertEqual(schema["suggested_title"], "BÁO CÁO KẾT QUẢ GIẢI QUYẾT THỦ TỤC HÀNH CHÍNH")
        self.assertEqual(len(schema["columns"]), 4)
        self.assertEqual(schema["columns"][0]["is_stt"], True)
        self.assertEqual(schema["columns"][2]["type"], "number")
        self.assertEqual(schema["columns"][3]["type"], "number")
        self.assertEqual(schema["columns"][2]["full_label"], "Hồ sơ tiếp nhận — Trực tuyến")
        self.assertEqual(len(schema["header_grid"]), 2)
        self.assertEqual(schema["header_grid"][0][0]["rowspan"], 2)
        self.assertEqual(schema["header_grid"][0][2]["colspan"], 2)
        self.assertTrue(schema["has_prefilled_rows"])
        self.assertFalse(schema["allow_add_rows"])
        self.assertTrue(schema["has_summary_row"])
        self.assertEqual(len(schema["template_rows"]), 3)
        self.assertEqual(schema["template_rows"][0][1], "Hồ sơ đăng ký cư trú")

    def test_excel_preview_api_supports_upload_and_quick_columns(self):
        admin_user = self._create_user("Admin Preview", "Hệ thống", "hethong", admin=True)
        self._login(admin_user, is_admin=True)

        buf = _build_dynamic_merged_template_bytes()
        res = self.client.post(
            "/api/tasks/excel-template-preview",
            headers={"X-CSRF-Token": self.csrf_token},
            data={"excel_file": (buf, "ton_dong.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["staged_filename"].startswith("staged_excel_"))
        self.staged_files.append(payload["staged_filename"])
        self.assertTrue(payload["schema"]["allow_add_rows"])
        self.assertEqual(len(payload["schema"]["columns"]), 4)

        quick_res = self.client.post(
            "/api/tasks/excel-template-preview",
            headers={"X-CSRF-Token": self.csrf_token},
            data={
                "title": "Bảng theo dõi nhanh",
                "quick_columns_json": json.dumps([
                    {"label": "STT", "type": "text"},
                    {"label": "Nội dung", "type": "text"},
                    {"label": "Số lượng", "type": "number"},
                ]),
            },
        )
        self.assertEqual(quick_res.status_code, 200)
        q_json = quick_res.get_json()
        self.assertTrue(q_json["ok"])
        self.assertEqual([c["type"] for c in q_json["schema"]["columns"]], ["text", "text", "number"])
        self.assertEqual(len(q_json["schema"]["header_grid"]), 1)
        self.assertEqual(q_json["schema"]["template_rows"][0][0], "1")

    def test_end_to_end_prefilled_excel_upload_submit_aggregate_and_export(self):
        admin_user = self._create_user("Admin Giao", "Hệ thống", "hethong", admin=True)
        u1 = self._create_user("Cán bộ Xã A", "Công an Xã A", "cong an xa a")
        u2 = self._create_user("Cán bộ Xã B", "Công an Xã B", "cong an xa b")

        self._login(admin_user, is_admin=True)
        tpl_buf = _build_merged_indicator_template_bytes()
        create_res = self.client.post(
            "/tasks",
            data={
                "csrf_token": self.csrf_token,
                "task_mode": "FORM",
                "form_provider": "excel",
                "title": "Biểu mẫu TTHC tháng 11",
                "assign_type": "user",
                "target_users": [str(u1.id), str(u2.id)],
                "excel_template_file": (tpl_buf, "bieu_mau_tthc.xlsx"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(create_res.status_code, 302)

        with app.app_context():
            task = Task.query.filter_by(title="Biểu mẫu TTHC tháng 11").order_by(Task.id.desc()).first()
            self.assertIsNotNone(task)
            self.task_ids.append(task.id)
            self.assertEqual(task.form_provider, "excel")
            self.assertTrue(task.file_path)
            self.assertTrue(os.path.exists(_task_file_path(task.file_path)))
            tid = task.id

        # Unit 1: view page, download template, submit via web grid JSON
        self._login(u1, is_admin=False)
        detail_u1 = self.client.get(f"/tasks/{tid}")
        self.assertEqual(detail_u1.status_code, 200)
        html_u1 = detail_u1.get_data(as_text=True)
        self.assertIn("pcExcelSubmitGrid", html_u1)
        self.assertIn("Hồ sơ tiếp nhận", html_u1)
        self.assertIn("Trực tuyến", html_u1)
        self.assertIn("Trực tiếp", html_u1)
        self.assertIn(json.dumps("Hồ sơ đăng ký cư trú"), html_u1)

        dl_u1 = self.client.get(f"/tasks/{tid}/excel-template.xlsx")
        self.assertEqual(dl_u1.status_code, 200)
        wb_dl = load_workbook(io.BytesIO(dl_u1.data))
        self.assertEqual(wb_dl.active["B4"].value, "Hồ sơ đăng ký cư trú")

        u1_rows = [
            ["1", "Hồ sơ đăng ký cư trú", "10", "5"],
            ["2", "Hồ sơ cấp căn cước", "20", "3"],
            ["3", "Hồ sơ xác nhận thông tin", "7", "2"],
        ]
        sub_u1 = self.client.post(
            f"/tasks/{tid}/submit_report",
            data={"csrf_token": self.csrf_token, "excel_rows_json": json.dumps(u1_rows)},
            follow_redirects=False,
        )
        self.assertEqual(sub_u1.status_code, 302)

        with app.app_context():
            sub_obj = (
                TaskSubmission.query.filter_by(task_id=tid, submitted_by=u1.id)
                .order_by(TaskSubmission.id.desc())
                .first()
            )
            self.assertTrue(_submission_has_report_content(sub_obj))

        # Unit 2: download template, fill workbook, preview via API, then submit .xlsx directly
        self._login(u2, is_admin=False)
        wb_u2 = load_workbook(_build_merged_indicator_template_bytes())
        ws_u2 = wb_u2.active
        ws_u2["C4"] = 4
        ws_u2["D4"] = 1
        ws_u2["C5"] = 6
        ws_u2["D5"] = 2
        ws_u2["C6"] = 3
        ws_u2["D6"] = 1
        u2_stream = io.BytesIO()
        wb_u2.save(u2_stream)
        u2_bytes = u2_stream.getvalue()

        up_preview = self.client.post(
            f"/tasks/{tid}/excel-upload-preview",
            headers={"X-CSRF-Token": self.csrf_token},
            data={"excel_file": (io.BytesIO(u2_bytes), "xa_b_nop.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(up_preview.status_code, 200)
        up_json = up_preview.get_json()
        self.assertTrue(up_json["ok"])
        self.assertEqual(up_json["rows"][0][2], "4")

        sub_u2 = self.client.post(
            f"/tasks/{tid}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "excel_submission_file": (io.BytesIO(u2_bytes), "xa_b_nop.xlsx"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(sub_u2.status_code, 302)

        # Admin views detail, form-data aggregation, and downloads merged workbook
        self._login(admin_user, is_admin=True)
        admin_detail = self.client.get(f"/tasks/{tid}")
        self.assertEqual(admin_detail.status_code, 200)
        admin_html = admin_detail.get_data(as_text=True)
        self.assertIn("Cộng gộp số liệu tự động", admin_html)
        self.assertIn("Đã nộp 3 dòng Excel", admin_html)

        agg_page = self.client.get(f"/tasks/{tid}/form-data")
        self.assertEqual(agg_page.status_code, 200)
        agg_html = agg_page.get_data(as_text=True)
        self.assertIn("Bảng tổng hợp số liệu Excel", agg_html)
        self.assertIn("14", agg_html)  # Row 1 Online: 10 + 4

        exp_res = self.client.get(f"/tasks/{tid}/export-form.xlsx")
        self.assertEqual(exp_res.status_code, 200)
        wb_exp = load_workbook(io.BytesIO(exp_res.data))
        self.assertIn("Tong hop", wb_exp.sheetnames)
        self.assertIn("Chi tiet don vi", wb_exp.sheetnames)
        ws_sum = wb_exp["Tong hop"]
        self.assertEqual(ws_sum["C4"].value, 14)  # 10 + 4
        self.assertEqual(ws_sum["D4"].value, 6)   # 5 + 1
        self.assertEqual(ws_sum["C5"].value, 26)  # 20 + 6
        self.assertEqual(ws_sum["C7"].value, "=SUM(C4:C6)")  # Original template formula preserved

        # Test return assignment UX
        with app.app_context():
            a1 = TaskAssignment.query.filter_by(task_id=tid, user_id=u1.id, task_item_id=None).first()
            a1_id = a1.id
        ret_res = self.client.post(
            f"/tasks/{tid}/assignments/{a1_id}/return",
            data={"csrf_token": self.csrf_token, "return_reason": "Kiểm tra lại mục 2"},
            follow_redirects=False,
        )
        self.assertEqual(ret_res.status_code, 302)
        self._login(u1, is_admin=False)
        u1_ret_html = self.client.get(f"/tasks/{tid}").get_data(as_text=True)
        self.assertIn("Yêu cầu bổ sung từ người giao: Kiểm tra lại mục 2", u1_ret_html)

    def test_dynamic_multi_row_merged_template_export_shifts_columns_cleanly(self):
        admin_user = self._create_user("Admin Động", "Hệ thống", "hethong", admin=True)
        u1 = self._create_user("Đơn vị 1", "UBND Xã 1", "ubnd xa 1")
        u2 = self._create_user("Đơn vị 2", "UBND Xã 2", "ubnd xa 2")

        self._login(admin_user, is_admin=True)
        create_res = self.client.post(
            "/tasks",
            data={
                "csrf_token": self.csrf_token,
                "task_mode": "FORM",
                "form_provider": "excel",
                "title": "Hồ sơ tồn động đa dòng",
                "assign_type": "user",
                "target_users": [str(u1.id), str(u2.id)],
                "excel_template_file": (_build_dynamic_merged_template_bytes(), "ton_dong.xlsx"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(create_res.status_code, 302)
        with app.app_context():
            task = Task.query.filter_by(title="Hồ sơ tồn động đa dòng").order_by(Task.id.desc()).first()
            self.task_ids.append(task.id)
            tid = task.id

        self._login(u1, is_admin=False)
        self.client.post(
            f"/tasks/{tid}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "excel_rows_json": json.dumps([
                    ["1", "Thủ tục A", "3", "1"],
                    ["2", "Thủ tục B", "5", "2"],
                ]),
            },
        )
        self._login(u2, is_admin=False)
        self.client.post(
            f"/tasks/{tid}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "excel_rows_json": json.dumps([
                    ["1", "Thủ tục C", "4", "4"],
                ]),
            },
        )

        self._login(admin_user, is_admin=True)
        exp_res = self.client.get(f"/tasks/{tid}/export-form.xlsx")
        self.assertEqual(exp_res.status_code, 200)
        wb_exp = load_workbook(io.BytesIO(exp_res.data))
        ws = wb_exp.active
        self.assertEqual(ws["A2"].value, "Đơn vị báo cáo")
        # Merged header C2:D2 from template must shift +1 col -> D2:E2
        merged_coords = {str(rng) for rng in ws.merged_cells.ranges}
        self.assertIn("D2:E2", merged_coords)
        self.assertIn("A2:A3", merged_coords)
        self.assertEqual(ws["A1"].value, "THỐNG KÊ HỒ SƠ TỒN ĐỌNG QUÁ HẠN")
        self.assertEqual(ws["D4"].value, 3)  # Col C original shifted -> D, row 4
        self.assertEqual(ws["D5"].value, 5)
        self.assertEqual(ws["D6"].value, 4)
        self.assertEqual(ws["A7"].value, "Tổng cộng")
        self.assertEqual(ws["D7"].value, "=SUM(D4:D6)")
        self.assertEqual(ws["E7"].value, "=SUM(E4:E6)")

    def test_delete_outline_and_excel_tasks_with_item_submissions_and_draft_fk_succeeds(self):
        from models import TaskImportDraft, TaskItem

        admin_user = self._create_user("Admin Xóa", "Hệ thống", "hethong", admin=True)
        u1 = self._create_user("Đơn vị Xóa", "Sở Tư pháp", "sotuphap")

        with app.app_context():
            outline_task = Task(
                title="Đề cương kiểm tra xóa FK",
                content="Nội dung đề cương",
                author_id=admin_user.id,
                author_name=admin_user.fullname,
                task_mode="OUTLINE",
                file_path="attached_outline_test.txt",
            )
            db.session.add(outline_task)
            db.session.flush()
            attached_path = _task_file_path("attached_outline_test.txt")
            os.makedirs(os.path.dirname(attached_path), exist_ok=True)
            with open(attached_path, "w", encoding="utf-8") as fh:
                fh.write("tailieu")

            parent_item = TaskItem(task_id=outline_task.id, item_code="1", title="Mục cha", output_type="OUTLINE")
            db.session.add(parent_item)
            db.session.flush()
            child_item = TaskItem(
                task_id=outline_task.id,
                parent_item_id=parent_item.id,
                item_code="1.1",
                title="Mục con",
                output_type="OUTLINE",
            )
            db.session.add(child_item)
            db.session.flush()

            part = TaskParticipant(task_id=outline_task.id, task_item_id=child_item.id, user_id=u1.id, participant_type="executor")
            assign = TaskAssignment(task_id=outline_task.id, task_item_id=child_item.id, user_id=u1.id, status="submitted")
            db.session.add_all([part, assign])
            db.session.flush()

            sub = TaskSubmission(
                task_id=outline_task.id,
                task_item_id=child_item.id,
                assignment_id=assign.id,
                submitted_by=u1.id,
                submission_type="OUTLINE",
                status="submitted",
                narrative_content="Báo cáo hoàn thành",
            )
            db.session.add(sub)
            db.session.flush()
            assign.last_submission_id = sub.id
            sub_file_path = _task_file_path("sub_attach_test.txt")
            with open(sub_file_path, "w", encoding="utf-8") as fh:
                fh.write("minhchung")
            db.session.add(
                TaskSubmissionFile(
                    submission_id=sub.id,
                    original_name="minhchung.txt",
                    stored_name="sub_attach_test.txt",
                    stored_path=sub_file_path,
                )
            )
            draft = TaskImportDraft(
                source_name="nhap_import.docx",
                source_type="outline_file",
                status="published",
                created_by=admin_user.id,
                published_task_id=outline_task.id,
            )
            db.session.add(draft)
            db.session.commit()
            oid = outline_task.id
            draft_id = draft.id

        # Xác nhận /dl_file phục vụ được task.file_path cho admin/executor
        self._login(u1, is_admin=False)
        dl_res = self.client.get("/dl_file/attached_outline_test.txt")
        self.assertEqual(dl_res.status_code, 200)
        self.assertEqual(dl_res.data, b"tailieu")
        dl_res.close()

        # Xóa task có đầy đủ FK lồng nhau -> phải trả 302 (không 500) và dọn sạch DB/file
        self._login(admin_user, is_admin=True)
        del_res = self.client.post(
            f"/tasks/{oid}/delete",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(del_res.status_code, 302)
        with app.app_context():
            self.assertIsNone(db.session.get(Task, oid))
            self.assertEqual(TaskAssignment.query.filter_by(task_id=oid).count(), 0)
            self.assertEqual(TaskSubmission.query.filter_by(task_id=oid).count(), 0)
            self.assertEqual(TaskItem.query.filter_by(task_id=oid).count(), 0)
            d_obj = db.session.get(TaskImportDraft, draft_id)
            self.assertIsNotNone(d_obj)
            self.assertIsNone(d_obj.published_task_id)
            db.session.delete(d_obj)
            db.session.commit()
        self.assertFalse(os.path.exists(attached_path))
        self.assertFalse(os.path.exists(sub_file_path))

    def test_parse_top_summary_formula_percent_and_unit_suggestion(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "Chi tieu"
        ws["A1"] = "BIỂU THỐNG KÊ THEO ĐƠN VỊ"
        ws.merge_cells("A1:E1")
        ws["A2"] = "STT"
        ws["B2"] = "Đơn vị"
        ws["C2"] = "Tổng số"
        ws["D2"] = "Kết quả thực hiện"
        ws["D3"] = "Đã xong"
        ws["E3"] = "Tỷ lệ"
        ws.merge_cells("A2:A3")
        ws.merge_cells("B2:B3")
        ws.merge_cells("C2:C3")
        ws.merge_cells("D2:E2")
        ws["B4"] = "Tổng"
        ws["C4"] = "=SUM(C5:C6)"
        ws["D4"] = "=SUM(D5:D6)"
        ws["E4"] = "=D4/C4"
        ws["E4"].number_format = "0.0%"
        ws["A5"], ws["B5"], ws["C5"], ws["D5"], ws["E5"] = 1, "Xã A", 100, 75, "=D5/C5"
        ws["E5"].number_format = "0.0%"
        ws["A6"], ws["B6"], ws["C6"], ws["D6"], ws["E6"] = 2, "Xã B", 200, 100, "=D6/C6"
        ws["E6"].number_format = "0.0%"

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        schema = parse_excel_template_layout(buf, filename="chi_tieu_don_vi.xlsx")
        self.assertEqual(schema["summary_position"], "top")
        self.assertEqual(schema["summary_row_excel"], 4)
        self.assertEqual(schema["data_start_row"], 5)
        self.assertEqual(schema["suggested_unit_col_index"], 1)
        f_col = schema["columns"][4]
        self.assertEqual(f_col["role"], "formula")
        self.assertEqual(f_col["formula"], "=D{r}/C{r}")
        self.assertTrue(f_col["is_percent"])

    def test_unit_rows_excel_workflow_recomputes_formulas_isolates_rows_and_exports(self):
        from models import Unit

        admin_user = self._create_user("Admin Form Unit", "Hệ thống", "hethong", admin=True)
        u1 = self._create_user("CB Xã Alpha", "Công an Xã Alpha", "ca_xa_alpha")
        u2 = self._create_user("CB Xã Beta", "Công an Xã Beta", "ca_xa_beta")

        wb = Workbook()
        ws = wb.active
        ws.title = "Bao cao"
        ws["A1"] = "THỐNG KÊ ĐƠN VỊ"
        ws.merge_cells("A1:E1")
        ws["A2"], ws["B2"], ws["C2"], ws["D2"], ws["E2"] = "STT", "Đơn vị", "Chỉ tiêu", "Đã đạt", "Tỷ lệ"
        ws["B3"] = "Tổng"
        ws["C3"], ws["D3"], ws["E3"] = "=SUM(C4:C5)", "=SUM(D4:D5)", "=D3/C3"
        ws["E3"].number_format = "0.0%"
        ws["A4"], ws["B4"], ws["C4"], ws["D4"], ws["E4"] = 1, "", "", "", "=D4/C4"
        ws["E4"].number_format = "0.0%"
        tpl_buf = io.BytesIO()
        wb.save(tpl_buf)
        tpl_buf.seek(0)

        self._login(admin_user, is_admin=True)
        with app.app_context():
            for code, name in [("ca_xa_alpha", "Công an Xã Alpha"), ("ca_xa_beta", "Công an Xã Beta")]:
                if not Unit.query.filter_by(code=code).first():
                    db.session.add(Unit(code=code, name=name, is_active=True))
            db.session.commit()

        generated_rows = [
            ["1", "Công an Xã Alpha", "", "", ""],
            ["2", "Công an Xã Beta", "", "", ""],
        ]
        unit_assignments = [
            {"row_index": 0, "unit_code": "ca_xa_alpha", "unit_name": "Công an Xã Alpha"},
            {"row_index": 1, "unit_code": "ca_xa_beta", "unit_name": "Công an Xã Beta"},
        ]
        res = self.client.post(
            "/tasks",
            data={
                "csrf_token": self.csrf_token,
                "task_mode": "FORM",
                "form_provider": "excel",
                "title": "Báo cáo phân dòng đơn vị",
                "assign_type": "user",
                "target_users": [str(u1.id), str(u2.id)],
                "excel_template_file": (tpl_buf, "phan_dong.xlsx"),
                "excel_allow_add_rows": "0",
                "excel_unit_col_index": "1",
                "excel_assign_row_mode": "unit_rows",
                "excel_col_roles_json": json.dumps({"1": "unit", "4": "formula"}),
                "excel_col_types_json": json.dumps({"2": "number", "3": "number", "4": "number"}),
                "excel_col_data_types_json": json.dumps({"2": "number", "3": "integer", "4": "formula"}),
                "excel_col_formulas_json": json.dumps({"4": "=D/C"}),
                "excel_col_percents_json": json.dumps({"4": True}),
                "excel_generated_rows_json": json.dumps(generated_rows),
                "excel_unit_row_assignments_json": json.dumps(unit_assignments),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        with app.app_context():
            task = Task.query.filter_by(title="Báo cáo phân dòng đơn vị").order_by(Task.id.desc()).first()
            self.assertIsNotNone(task)
            self.task_ids.append(task.id)
            tid = task.id

        # Đơn vị 1 chỉ thấy dòng Công an Xã Alpha + tải template riêng 1 dòng + gửi không cần tự điền công thức
        self._login(u1, is_admin=False)
        u1_detail = self.client.get(f"/tasks/{tid}").get_data(as_text=True)
        self.assertIn("Công an Xã Alpha", u1_detail)
        self.assertNotIn(json.dumps("Công an Xã Beta"), u1_detail)
        m_init = __import__("re").search(r"const initialRows = (\[.*?\]);", u1_detail)
        self.assertIsNotNone(m_init)
        parsed_init = json.loads(m_init.group(1))
        self.assertEqual(len(parsed_init), 1)
        self.assertEqual(parsed_init[0][1], "Công an Xã Alpha")

        dl_u1 = self.client.get(f"/tasks/{tid}/excel-template.xlsx")
        self.assertEqual(dl_u1.status_code, 200)
        wb_u1_tpl = load_workbook(io.BytesIO(dl_u1.data), data_only=False)
        ws_u1 = wb_u1_tpl.active
        self.assertEqual(ws_u1["B4"].value, "Công an Xã Alpha")
        self.assertIsNone(ws_u1["B5"].value)
        self.assertEqual(ws_u1["E4"].value, "=D4/C4")

        sub_res = self.client.post(
            f"/tasks/{tid}/submit_report",
            data={
                "csrf_token": self.csrf_token,
                "excel_rows_json": json.dumps([["1", "Giả mạo tên khác", "200", "150", "999"]]),
            },
            follow_redirects=False,
        )
        self.assertEqual(sub_res.status_code, 302)
        with app.app_context():
            sub = TaskSubmission.query.filter_by(task_id=tid, submitted_by=u1.id).order_by(TaskSubmission.id.desc()).first()
            payload = json.loads(sub.payload_json)
            self.assertEqual(payload["rows"][0][1], "Công an Xã Alpha")
            self.assertEqual(float(payload["rows"][0][4]), 0.75)

        # Admin xem bảng tổng hợp và xuất Excel không trùng cột Đơn vị báo cáo
        self._login(admin_user, is_admin=True)
        agg_html = self.client.get(f"/tasks/{tid}/form-data").get_data(as_text=True)
        self.assertIn("75.0%", agg_html)
        self.assertIn("Công an Xã Beta", agg_html)
        self.assertNotIn("Đơn vị báo cáo", agg_html)

        exp_res = self.client.get(f"/tasks/{tid}/export-form.xlsx")
        self.assertEqual(exp_res.status_code, 200)
        wb_exp = load_workbook(io.BytesIO(exp_res.data), data_only=False)
        ws_exp = wb_exp.active
        self.assertEqual(ws_exp["B2"].value, "Đơn vị")
        self.assertEqual(ws_exp["B4"].value, "Công an Xã Alpha")
        self.assertEqual(ws_exp["C4"].value, 200)
        self.assertEqual(ws_exp["D4"].value, 150)
        self.assertEqual(ws_exp["E4"].value, "=D4/C4")
        self.assertEqual(ws_exp["B5"].value, "Công an Xã Beta")
        self.assertEqual(ws_exp["C3"].value, "=SUM(C4:C5)")
        self.assertEqual(ws_exp["E3"].value, "=D3/C3")

    def test_form_assign_daily_period_and_multi_col_select_hooks(self):
        admin_user = self._create_user("Admin UI Hook", "PC06", "pc06", admin=True)
        self._login(admin_user, is_admin=True)

        form_html = self.client.get("/bieu-mau-giao-viec").get_data(as_text=True)
        self.assertIn('<option value="day">Hàng ngày</option>', form_html)
        self.assertIn("selectedColIndices", form_html)
        self.assertIn("btnClearMultiCol", form_html)
        self.assertIn("data-report-daily-anchor", form_html)

        outline_html = self.client.get("/outline-giao-viec").get_data(as_text=True)
        self.assertIn('<option value="day">Hàng ngày</option>', outline_html)
        self.assertIn("dailyField", outline_html)

        tasks_html = self.client.get("/tasks").get_data(as_text=True)
        self.assertIn('<option value="day">Hàng ngày</option>', tasks_html)
        self.assertIn("data-report-daily-anchor", tasks_html)

    def test_unsaved_config_exit_guard_and_draft_restore_hooks(self):
        admin_user = self._create_user("Admin Guard Hook", "PC06", "pc06", admin=True)
        self._login(admin_user, is_admin=True)

        guard_js_res = self.client.get("/static/js/unsaved-guard.js")
        self.assertEqual(guard_js_res.status_code, 200)
        guard_js = guard_js_res.get_data(as_text=True)
        self.assertIn("pcPromptUnsavedExit", guard_js)
        self.assertIn("pcAttachUnsavedGuard", guard_js)
        self.assertIn("pcSerializeForm", guard_js)

        form_html = self.client.get("/bieu-mau-giao-viec").get_data(as_text=True)
        self.assertIn("unsaved-guard.js", form_html)
        self.assertIn("formUnsavedGuard", form_html)
        self.assertIn("formDraftRestoreBanner", form_html)
        self.assertIn("btnRestoreFormDraft", form_html)

        outline_html = self.client.get("/outline-giao-viec").get_data(as_text=True)
        self.assertIn("outlineUnsavedGuard", outline_html)
        self.assertIn("outlineDraftRestoreBanner", outline_html)
        self.assertIn("btnChangeOutlineDoc", outline_html)

        tasks_html = self.client.get("/tasks").get_data(as_text=True)
        self.assertIn("isEditConfigDirty", tasks_html)
        self.assertIn("pcPromptUnsavedExit", tasks_html)
        self.assertIn("editConfigGuard", tasks_html)


if __name__ == "__main__":
    unittest.main()
