# -*- coding: utf-8 -*-
"""
Kiểm thử toàn diện phân hệ Theo dõi thời hạn hồ sơ & chỉ tiêu hàng ngày:
- Nhận diện 5 cấu trúc biểu mẫu riêng biệt: Tạm trú (10 cột), Thường trú (7 cột),
  Phiếu XM CT10 (header 2 tầng), Tích hợp giấy tờ / ĐDĐT, Làm sạch dữ liệu dân cư.
- Đọc file Excel (.xlsx), dán bảng TSV/CSV, dựng bảng từ tọa độ OCR ảnh chụp.
- Nhập hàng loạt (upsert / replace_pending) và chia tab trên /dossiers.
- Phân quyền đơn vị: mỗi đơn vị chỉ nhìn thấy và tích hoàn thành hồ sơ thuộc đơn vị mình.
"""
import io
import json
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import openpyxl

from app import app
from models import AppRole, AppSetting, Dossier, Unit, User, db
from services.dossier_importer import (
    _cluster_ocr_boxes_to_grid,
    parse_dossier_upload,
)


def _xlsx_bytes(sheets_spec):
    """Tạo file .xlsx in-memory từ dict {sheet_name: {'rows': [...], 'merges': [...]}}."""
    wb = openpyxl.Workbook()
    first = True
    for s_name, spec in sheets_spec.items():
        ws = wb.active if first else wb.create_sheet(title=s_name)
        ws.title = s_name
        first = False
        for r in spec.get("rows", []):
            ws.append(r)
        for m_range in spec.get("merges", []):
            ws.merge_cells(m_range)
        for col_letter, width in (spec.get("col_widths") or {}).items():
            ws.column_dimensions[col_letter].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class DossierImportAndTabsTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        with app.app_context():
            Dossier.query.delete()
            db.session.commit()

            admin_role = AppRole.query.filter_by(name="Quản trị hệ thống").first()
            cax_role = AppRole.query.filter_by(name="Cán bộ CAX").first()
            if not cax_role:
                cax_role = AppRole(name="Cán bộ CAX", level="commune", perms=json.dumps({"task": 2}))
                db.session.add(cax_role)
                db.session.commit()

            def _ensure_unit(code, name):
                u = Unit.query.filter_by(code=code).first()
                if not u:
                    u = Unit(code=code, name=name, level="commune", is_active=True)
                    db.session.add(u)
                    db.session.commit()
                return u

            self.u_at = _ensure_unit("cax_02512_test", "Công an Phường An Tường Test")
            self.u_bt = _ensure_unit("cax_02524_test", "Công an Phường Bình Thuận Test")

            def _ensure_user(username, fullname, role_id, unit_id=None, unit_key=""):
                usr = User.query.filter_by(username=username).first()
                if not usr:
                    usr = User(
                        username=username,
                        fullname=fullname,
                        role_id=role_id,
                        unit_id=unit_id,
                        unit_key=unit_key,
                        is_active=True,
                        must_change_password=False,
                    )
                    usr.set_password("StrongPass1!")
                    db.session.add(usr)
                    db.session.commit()
                return usr.id

            self.admin_uid = _ensure_user("dossier_admin_test", "Admin Test", admin_role.id)
            self.at_uid = _ensure_user(
                "dossier_cax_at", "Cán bộ An Tường", cax_role.id, self.u_at.id, self.u_at.code
            )
            self.bt_uid = _ensure_user(
                "dossier_cax_bt", "Cán bộ Bình Thuận", cax_role.id, self.u_bt.id, self.u_bt.code
            )

    def tearDown(self):
        with app.app_context():
            Dossier.query.delete()
            AppSetting.query.filter_by(key="dossier_column_widths_v1").delete()
            db.session.commit()

    def _login_as(self, uid):
        with app.app_context():
            usr = db.session.get(User, uid)
            sv = int(getattr(usr, "session_version", 0) or 0) if usr else 0
        import time
        with self.client.session_transaction() as sess:
            sess["uid"] = uid
            sess["session_version"] = sv
            sess["last_active"] = time.time()
            sess["csrf_token"] = "test-csrf-token"

    def test_parse_five_distinct_structures(self):
        tomorrow_vn = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
        today_vn = date.today().strftime("%d/%m/%Y")

        # 1. Tạm trú (10 cột + dòng Tổng & bảng thống kê ở cuối)
        tam_tru_bytes = _xlsx_bytes({
            "Danh sách hồ sơ": {
                "rows": [
                    ["DANH SÁCH HỒ SƠ ĐĂNG KÝ TẠM TRÚ"],
                    ["STT", "Số hồ sơ", "Thủ tục", "Ngày nộp hồ sơ", "Ngày tiếp nhận", "Ngày hẹn trả", "Tính đúng hạn", "Cán bộ tiếp nhận", "Đơn vị xử lý", "Trạng thái"],
                    [1, "G01-TAMTRU-001", "Đăng ký tạm trú", today_vn, f"14:46 {today_vn}", tomorrow_vn, "Đúng hạn", "TRẦN VĂN A", "Phường An Tường Test", "Hồ sơ chờ trả lời xác minh"],
                    [2, "G01-TAMTRU-002", "Đăng ký tạm trú", today_vn, None, None, "Đúng hạn", None, "Phường Bình Thuận Test", "Chờ tiếp nhận"],
                    ["Tổng", 2],
                    ["THỐNG KÊ TỔNG HỢP"],
                ],
                "merges": ["A1:J1"],
            }
        })
        # 2. Thường trú (7 cột, không có Ngày hẹn trả, cột đơn vị = Địa bàn tiếp nhận)
        thuong_tru_bytes = _xlsx_bytes({
            "Danh sách hồ sơ": {
                "rows": [
                    ["DANH SÁCH HỒ SƠ ĐĂNG KÝ THƯỜNG TRÚ"],
                    ["STT", "Số hồ sơ", "Thủ tục", "Ngày tiếp nhận", "Cán bộ tiếp nhận", "Địa bàn tiếp nhận", "Trạng thái"],
                    [1, "G01-THUONGTRU-001", "Đăng ký thường trú -", today_vn, "LÊ THỊ B", "Phường An Tường Test", "Hồ sơ chờ phê duyệt"],
                    [2, "G01-THUONGTRU-002", "Xác nhận cư trú", None, None, "Phường Bình Thuận Test", "Chờ tiếp nhận"],
                    ["Tổng cộng", 2],
                ],
                "merges": ["A1:G1"],
            }
        })
        # 3. CT10 (header 2 tầng + dòng Tổng Tỉnh Tuyên Quang)
        ct10_bytes = _xlsx_bytes({
            "Thống kê phiếu xác minh CT10": {
                "rows": [
                    ["THỐNG KÊ PHIẾU XÁC MINH CT10 NGÀY 18/11/2026"],
                    ["STT", "Đơn vị", "Lập phiếu xác minh", None, None, None, None, None, "Trả lời xác minh", None, None, None, None, None, "Quá hạn chưa trả lời"],
                    [None, None, "Tổng", "Hoàn thành lập phiếu", "Chờ phê duyệt", "T.CA trả lại", "Chờ trả lời", "Đơn vị nhận đã trả lời xác minh", "Tổng", "Chờ trả lời", "Đang trả lời", "Chờ phê duyệt", "T.CA trả kết quả", "Đã trả kết quả", None],
                    [1, "Tỉnh Tuyên Quang", 100, 1, 1, 0, 5, 93, 200, 10, 2, 1, 0, 187, 1],
                    [2, "Phường An Tường Test", 25, 0, 0, 0, 0, 25, 88, 0, 0, 0, 0, 88, 0],
                    [3, "Phường Bình Thuận Test", 11, 0, 0, 0, 1, 10, 42, 0, 1, 0, 0, 41, 1],
                ],
                "merges": ["A1:O1", "C2:H2", "I2:N2"],
            }
        })
        # 4. Tích hợp giấy tờ (master + sub-sheet)
        tich_hop_bytes = _xlsx_bytes({
            "CHỈ TIÊU": {
                "rows": [
                    ["BIỂU CHỈ TIÊU KÍCH HOẠT ĐỊNH DANH ĐIỆN TỬ, TÍCH HỢP GIẤY TỜ ĐẾN NGÀY 17/11/2026"],
                    ["STT", "Đơn vị", "Nhân khẩu trên 14 tuổi", "Kích hoạt định danh điện tử mức 2", None, None, "Tích hợp giấy khai sinh", None, None, None],
                    [None, None, None, "Đã được cấp tài khoản ĐDĐT mức 2", "Đã kích hoạt tài khoản ĐDĐT mức 2", "Tỷ lệ", "Chờ xác nhận", "Đã tích hợp", "Từ chối xác nhận", "Tỷ lệ"],
                    [None, "Tổng", 50000, 44000, 43000, 0.86, 1500, 200, 10, 0.12],
                    [1, "Phường An Tường Test", 34253, 31350, 31083, 0.907, 1037, 194, 8, 0.157],
                ],
                "merges": ["A1:J1", "D2:F2", "G2:J2"],
            }
        })
        # 5. Làm sạch dữ liệu dân cư (qua text/CSV dán bảng)
        lam_sach_csv = (
            "CHỈ TIÊU LÀM SẠCH DỮ LIỆU DÂN CƯ NGÀY 18/11/2026\n"
            "STT\tĐơn vị\tTổng cần làm sạch\tĐã làm sạch\tCòn tồn\tTỷ lệ (%)\n"
            "1\tPhường An Tường Test\t245\t210\t35\t85.7%\n"
            "2\tPhường Bình Thuận Test\t100\t100\t0\t100.0%\n"
        )

        with app.app_context():
            r1 = parse_dossier_upload(file_bytes=tam_tru_bytes, filename="HS_tam_tru.xlsx")
            self.assertEqual(r1["detected_tab"], "tam_tru")
            self.assertEqual(r1["total_rows"], 2)
            self.assertTrue(r1["records"][0]["has_deadline"])
            self.assertEqual(r1["records"][0]["unit_code"], "cax_02512_test")
            self.assertEqual(r1["records"][0]["can_bo"], "TRẦN VĂN A")

            r2 = parse_dossier_upload(file_bytes=thuong_tru_bytes, filename="HS_thuong_tru.xlsx")
            self.assertEqual(r2["detected_tab"], "thuong_tru")
            self.assertEqual(r2["total_rows"], 2)
            self.assertFalse(r2["records"][0]["has_deadline"])
            self.assertEqual(r2["records"][1]["ngay_tiep_nhan"], "")
            self.assertEqual(
                r2["raw_headers"],
                [["STT", "Số hồ sơ", "Thủ tục", "Ngày tiếp nhận", "Cán bộ tiếp nhận", "Địa bàn tiếp nhận", "Trạng thái"]],
            )
            self.assertEqual(r2["records"][1]["unit_code"], "cax_02524_test")

            r3 = parse_dossier_upload(file_bytes=ct10_bytes, filename="CT10.xlsx")
            self.assertEqual(r3["detected_tab"], "ct10")
            self.assertEqual(r3["total_rows"], 2)  # Bỏ qua Tỉnh Tuyên Quang
            self.assertEqual(r3["pending_rows"], 1)  # Bình Thuận có tồn & quá hạn
            bt_ct10 = r3["records"][1]
            self.assertEqual(bt_ct10["extra"]["lap_cho_tl"], 1)
            self.assertEqual(bt_ct10["extra"]["tl_dang_tl"], 1)
            self.assertEqual(bt_ct10["extra"]["qua_han"], 1)
            self.assertEqual(len(r3["raw_headers"]), 2)
            self.assertEqual(r3["raw_headers"][0][2], "Lập phiếu xác minh")
            self.assertEqual(r3["raw_headers"][0][8], "Trả lời xác minh")
            self.assertEqual(len(r3["exact_headers"]), 15)
            self.assertEqual(len(r3["col_widths"]), 15)
            self.assertEqual(len(r3["col_ratios"]), 15)
            self.assertEqual(bt_ct10["raw_row"][1], "Phường Bình Thuận Test")
            self.assertEqual(len(bt_ct10["extra"]["row_cells"]), 15)
            self.assertEqual(len(bt_ct10["extra"]["source_header_rows"]), 2)
            self.assertEqual(len(bt_ct10["extra"]["source_headers"]), 15)

            r4 = parse_dossier_upload(file_bytes=tich_hop_bytes, filename="Tich_hop.xlsx")
            self.assertEqual(r4["detected_tab"], "tich_hop")
            self.assertEqual(r4["total_rows"], 1)
            self.assertEqual(r4["records"][0]["extra"]["cho_xac_nhan"], 1037)
            self.assertEqual(r4["records"][0]["extra"]["da_tich_hop"], 194)

            r5 = parse_dossier_upload(raw_text=lam_sach_csv)
            self.assertEqual(r5["detected_tab"], "lam_sach")
            self.assertEqual(r5["total_rows"], 2)
            self.assertEqual(r5["records"][0]["pending_total"], 35)
            self.assertFalse(r5["records"][1]["is_pending"])

    def test_ocr_2d_box_clustering_reconstructs_rows_and_cols(self):
        boxes = [
            {"text": "CHỈ TIÊU LÀM SẠCH DỮ LIỆU DÂN CƯ 18/11/2026", "x": 0.05, "y": 0.05, "w": 0.7, "h": 0.04},
            {"text": "STT", "x": 0.04, "y": 0.16, "w": 0.04, "h": 0.03},
            {"text": "Đơn vị", "x": 0.12, "y": 0.16, "w": 0.12, "h": 0.03},
            {"text": "Đã làm sạch", "x": 0.42, "y": 0.16, "w": 0.16, "h": 0.03},
            {"text": "Còn tồn", "x": 0.68, "y": 0.16, "w": 0.10, "h": 0.03},
            {"text": "1", "x": 0.04, "y": 0.25, "w": 0.02, "h": 0.03},
            {"text": "Phường An Tường Test", "x": 0.12, "y": 0.25, "w": 0.20, "h": 0.03},
            {"text": "120", "x": 0.45, "y": 0.25, "w": 0.05, "h": 0.03},
            {"text": "15", "x": 0.70, "y": 0.25, "w": 0.04, "h": 0.03},
        ]
        grid = _cluster_ocr_boxes_to_grid(boxes)
        self.assertGreaterEqual(len(grid), 3)
        self.assertEqual(grid[2][1], "Phường An Tường Test")
        self.assertEqual(grid[2][3], "15")

    def test_upload_image_route_with_mock_and_unit_isolation_completion(self):
        # Kiểm tra endpoint parse-upload với file PNG (mock OCR portability cho mọi OS)
        self._login_as(self.admin_uid)
        mock_grid = [
            ["CHỈ TIÊU LÀM SẠCH DỮ LIỆU DÂN CƯ 18/11/2026", "", "", ""],
            ["STT", "Đơn vị", "Còn tồn", "Tỷ lệ"],
            ["1", "Phường An Tường Test", "18", "92.5%"],
            ["2", "Phường Bình Thuận Test", "9", "95.0%"],
        ]
        with patch("services.dossier_importer.extract_image_table_grid", return_value=(mock_grid, "mock_vision", None)):
            res = self.client.post(
                "/api/dossiers/parse-upload",
                data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "lam_sach.png")},
                headers={"X-CSRF-Token": "test-csrf-token"},
                content_type="multipart/form-data",
            )
            self.assertEqual(res.status_code, 200)
            payload = res.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["detected_tab"], "lam_sach")
            self.assertEqual(len(payload["records"]), 2)

        # Admin nhập cả 2 đơn vị vào tab lam_sach + 1 hồ sơ Tạm trú cho An Tường
        imp1 = self.client.post(
            "/api/dossiers/bulk-import",
            json={
                "category_tab": "lam_sach",
                "report_date": "2026-11-18",
                "source_type": "image",
                "source_name": "lam_sach.png",
                "records": payload["records"],
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(imp1.status_code, 200)
        self.assertEqual(imp1.get_json()["created"], 2)

        # Upsert cùng bộ records -> không tạo trùng, cập nhật 2 dòng
        imp_dup = self.client.post(
            "/api/dossiers/bulk-import",
            json={
                "category_tab": "lam_sach",
                "report_date": "2026-11-18",
                "import_mode": "upsert",
                "records": payload["records"],
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(imp_dup.status_code, 200)
        self.assertEqual(imp_dup.get_json()["created"], 0)
        self.assertEqual(imp_dup.get_json()["updated"], 2)

        # Nhập thêm 1 hồ sơ Tạm trú thuộc Phường An Tường
        tam_tru_res = self.client.post(
            "/api/dossiers/bulk-import",
            json={
                "category_tab": "tam_tru",
                "records": [
                    {
                        "category_tab": "tam_tru",
                        "ma_ho_so": "G01-TEST-AT-1",
                        "so_ho_so": "G01-TEST-AT-1",
                        "unit_area": "Phường An Tường Test",
                        "han_tra": date.today().strftime("%Y-%m-%d"),
                        "has_deadline": True,
                        "trang_thai": "dang_xu_ly",
                    }
                ],
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(tam_tru_res.status_code, 200)

        # Admin thấy tất cả 3 dòng, đồng thời filter theo tab hoạt động đúng
        admin_list = self.client.get("/api/dossiers").get_json()
        self.assertEqual(admin_list["tab_counts"]["all"]["pending"], 3)
        self.assertEqual(admin_list["tab_counts"]["lam_sach"]["pending"], 2)
        self.assertEqual(admin_list["tab_counts"]["tam_tru"]["pending"], 1)

        # Export Excel trả về 200 hợp lệ
        exp = self.client.get("/api/dossiers/export?category_tab=lam_sach")
        self.assertEqual(exp.status_code, 200)
        wb_out = openpyxl.load_workbook(io.BytesIO(exp.data))
        self.assertGreaterEqual(wb_out.active.max_row, 4)

        # Lấy id dòng của Bình Thuận để test phân quyền
        bt_id = next(d["id"] for d in admin_list["dossiers"] if d["unit_code"] == "cax_02524_test")
        at_ls_id = next(
            d["id"] for d in admin_list["dossiers"] if d["unit_code"] == "cax_02512_test" and d["category_tab"] == "lam_sach"
        )

        # Đăng nhập bằng Cán bộ Công an Phường An Tường -> chỉ nhìn thấy 2 dòng của mình
        self._login_as(self.at_uid)
        at_list = self.client.get("/api/dossiers").get_json()
        self.assertEqual(len(at_list["dossiers"]), 2)
        self.assertTrue(all(d["unit_code"] == "cax_02512_test" for d in at_list["dossiers"]))

        # An Tường KHÔNG được tích hoàn thành hộ Bình Thuận
        forbid = self.client.post(
            f"/api/dossiers/{bt_id}/status",
            json={"trang_thai": "da_tra"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(forbid.status_code, 403)

        # An Tường tích hoàn thành dòng làm sạch của chính mình -> thành công & lưu tên người tích
        ok_tick = self.client.post(
            f"/api/dossiers/{at_ls_id}/status",
            json={"trang_thai": "da_tra", "note": "Đã xử lý 18/18 trường hợp"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(ok_tick.status_code, 200)
        tick_json = ok_tick.get_json()
        self.assertEqual(tick_json["trang_thai"], "da_tra")
        self.assertEqual(tick_json["hoan_thanh_by_name"], "Cán bộ An Tường")

        # Kiểm tra trang /dossiers render đủ 6 tab & modal import
        page_html = self.client.get("/dossiers").get_data(as_text=True)
        for tab_txt in ("Tạm trú", "Thường trú", "Phiếu XM CT10", "Tích hợp giấy tờ", "Làm sạch dữ liệu", "Tải file / Ảnh bảng"):
            self.assertIn(tab_txt, page_html)

    def test_manual_dossier_backward_compat_and_png_vision_smoke(self):
        self._login_as(self.admin_uid)
        res = self.client.post(
            "/api/dossiers",
            json={
                "ma_ho_so": "HS-MANUAL-001",
                "loai": "can-cuoc",
                "han_tra": (date.today() + timedelta(days=1)).strftime("%Y-%m-%d"),
                "ghi_chu": "Kiểm tra tương thích ngược",
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(res.status_code, 200)
        d_id = res.get_json()["id"]

        listed = self.client.get("/api/dossiers?category_tab=khac").get_json()
        self.assertTrue(any(d["id"] == d_id and d["ma_ho_so"] == "HS-MANUAL-001" for d in listed["dossiers"]))

        if sys.platform == "darwin":
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (900, 260), "white")
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
            except Exception:
                font = ImageFont.load_default()
            draw.text((30, 20), "DANH SÁCH HỒ SƠ ĐĂNG KÝ TẠM TRÚ", fill="black", font=font)
            draw.text((30, 70), "STT    Số hồ sơ    Đơn vị xử lý    Ngày hẹn trả", fill="black", font=font)
            draw.text((30, 120), "1    G01-OCR-001    Phường An Tường Test    25/11/2026", fill="black", font=font)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            with app.app_context():
                ocr_res = parse_dossier_upload(file_bytes=buf.getvalue(), filename="tam_tru.png")
                self.assertTrue(ocr_res["ok"])
                self.assertEqual(ocr_res["detected_tab"], "tam_tru")
                self.assertGreaterEqual(len(ocr_res["records"]), 1)

    def test_custom_tam_tru_structure_with_banner_2tier_headers_and_extra_cols(self):
        custom_xlsx = _xlsx_bytes({
            "Dữ liệu": {
                "rows": [
                    ["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"],
                    ["CÔNG AN TỈNH TUYÊN QUANG"],
                    ["BÁO CÁO THEO DÕI HỒ SƠ ĐĂNG KÝ TẠM TRÚ"],
                    ["Từ ngày 01/11/2026 đến 18/11/2026"],
                    [],
                    ["STT", "Thông tin hồ sơ", None, None, "Thời gian giải quyết", None, "Đơn vị thực hiện", "Kết quả"],
                    [None, "Mã hồ sơ", "Họ và tên", "Số ĐDCN", "Ngày nộp", "Ngày hẹn trả", "Địa bàn xử lý", "Trạng thái"],
                    ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)"],
                    [1, "HS-CUSTOM-901", "Nguyễn Văn An", "008090001234", "15/11/2026", "20/11/2026", "Phường An Tường Test", "Đang xác minh"],
                    [2, "HS-CUSTOM-902", "Trần Thị Bình", "008195005678", "16/11/2026", "21/11/2026", "Phường Bình Thuận Test", "Đã trả kết quả"],
                ],
                "merges": ["B6:D6", "E6:F6"],
            }
        })
        with app.app_context():
            res = parse_dossier_upload(file_bytes=custom_xlsx, filename="bao_cao_tong_hop.xlsx")
            self.assertTrue(res["ok"])
            self.assertEqual(res["detected_tab"], "tam_tru")
            self.assertIn("TẠM TRÚ", res["table_title"].upper())
            self.assertEqual(len(res["records"]), 2)
            mapped_fields = {m["field"]: m for m in res["column_mapping"]}
            self.assertIn("so_ho_so", mapped_fields)
            self.assertIn("ngay_nop", mapped_fields)
            self.assertIn("han_tra", mapped_fields)
            self.assertIn("cong_dan", mapped_fields)

            r0 = res["records"][0]
            self.assertEqual(r0["so_ho_so"], "HS-CUSTOM-901")
            self.assertEqual(r0["ngay_nop"], "2026-11-15")
            self.assertEqual(r0["han_tra"], "2026-11-20")
            self.assertTrue(r0["has_deadline"])
            self.assertEqual(r0["cong_dan"], "Nguyễn Văn An")
            self.assertEqual(r0["unit_code"], "cax_02512_test")
            custom_labels = {cf["label"]: cf["value"] for cf in r0["extra"]["custom_fields"]}
            self.assertTrue(any("008090001234" == v for v in custom_labels.values()))

            self.assertEqual(res["records"][1]["trang_thai"], "da_tra")

        self._login_as(self.admin_uid)
        html = self.client.get("/dossiers").get_data(as_text=True)
        self.assertIn("importStructureBox", html)
        self.assertIn("previewTableHead", html)
        self.assertNotIn("Số hồ sơ / Chỉ tiêu", html)
        self.assertNotIn("Ngày tiếp nhận / Hạn trả", html)
        self.assertNotIn("Hạn / Mốc ngày", html)
        self.assertNotIn("Cán bộ TN", html)
        self.assertNotIn("Địa bàn TN", html)
        self.assertIn("Tự động nhận diện", html)
        self.assertNotIn("Dán bảng từ Excel / Zalo", html)
        self.assertNotIn("kéo thả", html)
        self.assertIn("Chọn file Excel / Ảnh", html)
        self.assertIn("document.getElementById('importOverrideTab').value = '';", html)
        self.assertIn("dossierMainColgroup", html)
        self.assertIn("previewTableColgroup", html)
        self.assertIn("computeDossierColumnLayout", html)
        self.assertIn("CT10_FALLBACK_HEADER_ROWS", html)
        self.assertIn("getRowExactSchema", html)

    def test_excel_column_width_ratios_scanned_and_persisted(self):
        thuong_tru_xlsx = _xlsx_bytes({
            "Danh sách hồ sơ": {
                "rows": [
                    ["DANH SÁCH HỒ SƠ ĐĂNG KÝ THƯỜNG TRÚ"],
                    ["STT", "Số hồ sơ", "Thủ tục", "Ngày tiếp nhận", "Cán bộ tiếp nhận", "Địa bàn tiếp nhận", "Trạng thái"],
                    [1, "G01.809.822-261110-890004", "Điều chỉnh thông tin về cư trú trong CSDL cư trú - Thay đổi chủ hộ", "10/11/2026", "PHẠM THẾ QUANG", "Phường An Tường Test", "Hồ sơ chờ trả kết quả"],
                ],
                "col_widths": {"A": 10.0, "B": 28.0, "C": 76.0, "D": 18.0, "E": 26.0, "F": 24.0, "G": 34.0},
            }
        })
        with app.app_context():
            parsed = parse_dossier_upload(file_bytes=thuong_tru_xlsx, filename="HS_thuong_tru.xlsx")
            self.assertTrue(parsed["ok"])
            self.assertEqual(parsed["detected_tab"], "thuong_tru")
            self.assertEqual(parsed["col_widths"], [10.0, 28.0, 76.0, 18.0, 26.0, 24.0, 34.0])
            ratios = parsed["col_ratios"]
            self.assertEqual(len(ratios), 7)
            # Cột Thủ tục (index 2) phải có tỉ lệ rộng nhất
            self.assertEqual(ratios.index(max(ratios)), 2)
            self.assertAlmostEqual(sum(ratios), 100.0, places=0)
            self.assertEqual(parsed["records"][0]["extra"]["source_col_ratios"], ratios)

        self._login_as(self.admin_uid)
        bulk_resp = self.client.post(
            "/api/dossiers/bulk-import",
            json={
                "category_tab": "thuong_tru",
                "report_date": "2026-11-19",
                "source_type": "excel",
                "import_mode": "upsert",
                "records": parsed["records"],
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(bulk_resp.status_code, 200)

        listed = self.client.get("/api/dossiers?category_tab=thuong_tru").get_json()
        dossiers = listed["dossiers"]
        self.assertEqual(len(dossiers), 1)
        self.assertEqual(dossiers[0]["extra"]["source_col_widths"], [10.0, 28.0, 76.0, 18.0, 26.0, 24.0, 34.0])
        self.assertEqual(dossiers[0]["extra"]["source_col_ratios"], ratios)

    def test_two_step_completion_workflow_and_pending_only_list(self):
        from datetime import date

        self._login_as(self.admin_uid)
        today = date.today()
        today_iso = today.isoformat()
        today_vn = today.strftime("%d/%m/%Y")
        headers = ["STT", "Số hồ sơ", "Thủ tục", "Ngày tiếp nhận", "Trạng thái"]

        bulk_resp = self.client.post(
            "/api/dossiers/bulk-import",
            json={
                "category_tab": "thuong_tru",
                "report_date": "2026-11-19",
                "source_type": "excel",
                "import_mode": "upsert",
                "records": [
                    {
                        "ma_ho_so": "HS-CHO-01",
                        "ten_thu_tuc": "Đăng ký thường trú",
                        "ngay_tiep_nhan": None,
                        "trang_thai_nguon": "Chờ tiếp nhận",
                        "don_vi_name": "Xã Phù Lưu",
                        "extra": {
                            "source_headers": headers,
                            "row_cells": ["1", "HS-CHO-01", "Đăng ký thường trú", "", "Chờ tiếp nhận"],
                            "ngay_tiep_nhan_raw": "",
                        },
                    },
                    {
                        "ma_ho_so": "HS-XULY-02",
                        "ten_thu_tuc": "Điều chỉnh thông tin cư trú",
                        "ngay_tiep_nhan": "2026-11-10",
                        "trang_thai_nguon": "Hồ sơ đang xử lý",
                        "don_vi_name": "Phường Minh Xuân",
                        "extra": {
                            "source_headers": headers,
                            "row_cells": ["2", "HS-XULY-02", "Điều chỉnh thông tin cư trú", "10/11/2026", "Hồ sơ đang xử lý"],
                            "ngay_tiep_nhan_raw": "10/11/2026",
                        },
                    },
                    {
                        "ma_ho_so": "HS-BULK-CHO-03",
                        "ten_thu_tuc": "Đăng ký thường trú",
                        "ngay_tiep_nhan": None,
                        "trang_thai_nguon": "Chờ tiếp nhận",
                        "don_vi_name": "Xã Phố Bảng",
                        "extra": {
                            "source_headers": headers,
                            "row_cells": ["3", "HS-BULK-CHO-03", "Đăng ký thường trú", "", "Chờ tiếp nhận"],
                            "ngay_tiep_nhan_raw": "",
                        },
                    },
                    {
                        "ma_ho_so": "HS-BULK-XULY-04",
                        "ten_thu_tuc": "Xóa đăng ký thường trú",
                        "ngay_tiep_nhan": "2026-11-11",
                        "trang_thai_nguon": "Hồ sơ đang xử lý",
                        "don_vi_name": "Phường Bình Thuận",
                        "extra": {
                            "source_headers": headers,
                            "row_cells": ["4", "HS-BULK-XULY-04", "Xóa đăng ký thường trú", "11/11/2026", "Hồ sơ đang xử lý"],
                            "ngay_tiep_nhan_raw": "11/11/2026",
                        },
                    },
                ],
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(bulk_resp.status_code, 200)

        listed_init = self.client.get("/api/dossiers?category_tab=thuong_tru").get_json()
        by_code = {d["ma_ho_so"]: d for d in listed_init["dossiers"]}
        self.assertEqual(set(by_code.keys()), {"HS-CHO-01", "HS-XULY-02", "HS-BULK-CHO-03", "HS-BULK-XULY-04"})

        # Case A: Ho so Cho tiep nhan -> lan 1 an Hoan thanh chi chuyen sang Ho so dang xu ly + gan ngay tiep nhận hom nay
        d_wait = by_code["HS-CHO-01"]
        step1 = self.client.post(
            f"/api/dossiers/{d_wait['id']}/status",
            json={"trang_thai": "da_tra"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(step1.status_code, 200)
        s1_data = step1.get_json()
        self.assertEqual(s1_data["action_stage"], "received")
        self.assertEqual(s1_data["trang_thai"], "dang_xu_ly")
        self.assertEqual(s1_data["ngay_tiep_nhan"], today_iso)
        self.assertEqual(s1_data["ngay_tiep_nhan_vn"], today_vn)
        self.assertEqual(s1_data["trang_thai_nguon"], "Hồ sơ đang xử lý")

        # Van hien thi trong danh sach mac dinh (chua hoan thanh) va dong bo extra.row_cells
        listed_after_step1 = self.client.get("/api/dossiers?category_tab=thuong_tru").get_json()
        map_after_step1 = {d["ma_ho_so"]: d for d in listed_after_step1["dossiers"]}
        self.assertIn("HS-CHO-01", map_after_step1)
        after1 = map_after_step1["HS-CHO-01"]
        self.assertEqual(after1["extra"]["ngay_tiep_nhan_raw"], today_vn)
        self.assertEqual(after1["extra"]["row_cells"][3], today_vn)
        self.assertEqual(after1["extra"]["row_cells"][4], "Hồ sơ đang xử lý")

        # Lan 2 an Hoan thanh -> moi tinh xu ly xong (da_tra) va an khoi danh sach mac dinh
        step2 = self.client.post(
            f"/api/dossiers/{d_wait['id']}/status",
            json={"trang_thai": "da_tra"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(step2.status_code, 200)
        s2_data = step2.get_json()
        self.assertEqual(s2_data["action_stage"], "completed")
        self.assertEqual(s2_data["trang_thai"], "da_tra")

        # Case B: Ho so da co ngay tiep nhan -> an Hoan thanh tinh hoan thanh ngay
        d_recv = by_code["HS-XULY-02"]
        direct_done = self.client.post(
            f"/api/dossiers/{d_recv['id']}/status",
            json={"trang_thai": "da_tra"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(direct_done.status_code, 200)
        dd_data = direct_done.get_json()
        self.assertEqual(dd_data["action_stage"], "completed")
        self.assertEqual(dd_data["trang_thai"], "da_tra")

        listed_after_case_ab = self.client.get("/api/dossiers?category_tab=thuong_tru").get_json()
        codes_after_ab = {d["ma_ho_so"] for d in listed_after_case_ab["dossiers"]}
        self.assertNotIn("HS-CHO-01", codes_after_ab)
        self.assertNotIn("HS-XULY-02", codes_after_ab)
        self.assertEqual(listed_after_case_ab["counts"]["done"], 2)

        # Case C: bulk-status voi danh sach hon hop 1 ho so cho tiep nhan + 1 ho so da tiep nhan
        bulk_wait = by_code["HS-BULK-CHO-03"]
        bulk_recv = by_code["HS-BULK-XULY-04"]
        bulk_done = self.client.post(
            "/api/dossiers/bulk-status",
            json={"ids": [bulk_wait["id"], bulk_recv["id"]], "trang_thai": "da_tra"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(bulk_done.status_code, 200)
        bd_data = bulk_done.get_json()
        self.assertEqual(bd_data["received"], 1)
        self.assertEqual(bd_data["completed"], 1)

        listed_final = self.client.get("/api/dossiers?category_tab=thuong_tru").get_json()
        codes_final = {d["ma_ho_so"]: d for d in listed_final["dossiers"]}
        self.assertIn("HS-BULK-CHO-03", codes_final)
        self.assertEqual(codes_final["HS-BULK-CHO-03"]["ngay_tiep_nhan"], today_iso)
        self.assertEqual(codes_final["HS-BULK-CHO-03"]["trang_thai_nguon"], "Hồ sơ đang xử lý")
        self.assertNotIn("HS-BULK-XULY-04", codes_final)
        self.assertEqual(listed_final["counts"]["done"], 3)

    def test_admin_manual_column_widths_persistence_and_permissions(self):
        layout_key = "dcol_tam_tru_12_abcd1234"
        widths = [32, 44, 215, 290, 110, 118, 110, 96, 155, 165, 210, 160]

        # Can bo don vi KHONG duoc luu cau hinh cot dung chung toan he thong -> 403
        self._login_as(self.at_uid)
        forbid = self.client.post(
            "/api/dossiers/column-widths",
            json={"action": "save", "layout_key": layout_key, "widths": widths},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(forbid.status_code, 403)

        # Admin gui payload khong hop le -> 400
        self._login_as(self.admin_uid)
        bad_req = self.client.post(
            "/api/dossiers/column-widths",
            json={"action": "save", "layout_key": "", "widths": [10]},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(bad_req.status_code, 400)

        # Admin keo chinh do rong cot -> luu thanh cong va phan anh cho ca tai khoan khac
        saved = self.client.post(
            "/api/dossiers/column-widths",
            json={"action": "save", "layout_key": layout_key, "widths": widths},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(saved.status_code, 200)
        saved_json = saved.get_json()
        self.assertTrue(saved_json["ok"])
        self.assertEqual(saved_json["column_widths_map"][layout_key], widths)

        # Tai khoan don vi mo /api/dossiers va /dossiers phai nhan dung do rong Admin da chinh
        self._login_as(self.at_uid)
        api_res = self.client.get("/api/dossiers").get_json()
        self.assertEqual(api_res["column_widths_map"][layout_key], widths)
        page_html = self.client.get("/dossiers").get_data(as_text=True)
        self.assertIn("attachDossierColumnResizers", page_html)
        self.assertIn("btnResetColWidths", page_html)
        self.assertIn(layout_key, page_html)
        self.assertIn("dossierMobileList", page_html)
        self.assertIn("renderMobileCards", page_html)

        # User-Agent mobile nhan dung trang co card view mobile
        mobile_html = self.client.get(
            "/dossiers",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"},
        ).get_data(as_text=True)
        self.assertIn("dossier-mobile-list-wrap", mobile_html)
        self.assertIn("dossier-mcard", mobile_html)

        # Admin khoi phuc mac dinh -> xoa khoi AppSetting
        self._login_as(self.admin_uid)
        reset_res = self.client.post(
            "/api/dossiers/column-widths",
            json={"action": "reset", "layout_key": layout_key},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(reset_res.status_code, 200)
        self.assertNotIn(layout_key, reset_res.get_json()["column_widths_map"])

    def test_stats_counts_change_accurately_per_tab_and_unit_filter(self):
        today = date.today()
        overdue_day = today - timedelta(days=2)
        soon_day = today + timedelta(days=1)
        future_day = today + timedelta(days=10)

        with app.app_context():
            from category_helpers import ensure_unified_category_catalog
            from models import CategoryGroup, CategoryItem

            ensure_unified_category_catalog(commit=True)
            tab_grp = CategoryGroup.query.filter_by(code="dossier_tab").first()
            custom_tab = CategoryItem.query.filter_by(group_id=tab_grp.id, code="ho_so_rieng_test").first()
            if not custom_tab:
                custom_tab = CategoryItem(group_id=tab_grp.id, code="ho_so_rieng_test", name="Hồ sơ riêng test", is_active=True, sort_order=999)
                db.session.add(custom_tab)
                db.session.flush()
            custom_tab_id = custom_tab.id

            rows = [
                # tam_tru: 1 overdue (AT), 1 soon (AT), 1 pending (BT), 1 done (AT), 1 done (BT)
                Dossier(ma_ho_so="STAT-TT-1", category_tab="tam_tru", loai="cu-tru", han_tra=overdue_day, has_deadline=True, trang_thai="dang_xu_ly", unit_code=self.u_at.code, unit_area=self.u_at.name),
                Dossier(ma_ho_so="STAT-TT-2", category_tab="tam_tru", loai="cu-tru", han_tra=soon_day, has_deadline=True, trang_thai="dang_xu_ly", unit_code=self.u_at.code, unit_area=self.u_at.name),
                Dossier(ma_ho_so="STAT-TT-3", category_tab="tam_tru", loai="cu-tru", han_tra=future_day, has_deadline=True, trang_thai="dang_xu_ly", unit_code=self.u_bt.code, unit_area=self.u_bt.name),
                Dossier(ma_ho_so="STAT-TT-4", category_tab="tam_tru", loai="cu-tru", han_tra=today, has_deadline=True, trang_thai="da_tra", unit_code=self.u_at.code, unit_area=self.u_at.name),
                Dossier(ma_ho_so="STAT-TT-5", category_tab="tam_tru", loai="cu-tru", han_tra=today, has_deadline=True, trang_thai="da_tra", unit_code=self.u_bt.code, unit_area=self.u_bt.name),
                # thuong_tru: 2 pending (AT, BT), 1 done (AT)
                Dossier(ma_ho_so="STAT-TH-1", category_tab="thuong_tru", loai="cu-tru", han_tra=today, has_deadline=False, trang_thai="dang_xu_ly", unit_code=self.u_at.code, unit_area=self.u_at.name),
                Dossier(ma_ho_so="STAT-TH-2", category_tab="thuong_tru", loai="cu-tru", han_tra=today, has_deadline=False, trang_thai="dang_xu_ly", unit_code=self.u_bt.code, unit_area=self.u_bt.name),
                Dossier(ma_ho_so="STAT-TH-3", category_tab="thuong_tru", loai="cu-tru", han_tra=today, has_deadline=False, trang_thai="da_tra", unit_code=self.u_at.code, unit_area=self.u_at.name),
                # ct10: 1 overdue (qua_han=3), 1 pending (qua_han=0)
                Dossier(ma_ho_so="STAT-CT-1", category_tab="ct10", loai="cu-tru", han_tra=today, has_deadline=False, trang_thai="dang_xu_ly", unit_code=self.u_at.code, unit_area=self.u_at.name, extra_json=json.dumps({"qua_han": 3})),
                Dossier(ma_ho_so="STAT-CT-2", category_tab="ct10", loai="cu-tru", han_tra=today, has_deadline=False, trang_thai="dang_xu_ly", unit_code=self.u_bt.code, unit_area=self.u_bt.name, extra_json=json.dumps({"qua_han": 0})),
                # custom admin tab: 1 pending, 1 done
                Dossier(ma_ho_so="STAT-CS-1", category_tab="ho_so_rieng_test", loai="khac", han_tra=future_day, has_deadline=True, trang_thai="dang_xu_ly", unit_code=self.u_at.code, unit_area=self.u_at.name),
                Dossier(ma_ho_so="STAT-CS-2", category_tab="ho_so_rieng_test", loai="khac", han_tra=today, has_deadline=True, trang_thai="da_tra", unit_code=self.u_at.code, unit_area=self.u_at.name),
            ]
            db.session.add_all(rows)
            db.session.commit()

        try:
            self._login_as(self.admin_uid)

            # 1. Tat ca -> tong toan bo linh vuc
            all_res = self.client.get("/api/dossiers?trang_thai=dang_xu_ly").get_json()
            self.assertEqual(all_res["counts"], {"overdue": 2, "soon": 1, "pending": 5, "done": 4})

            # 2. Tam tru -> chi cua rieng tam_tru
            tt_res = self.client.get("/api/dossiers?trang_thai=dang_xu_ly&category_tab=tam_tru").get_json()
            self.assertEqual(tt_res["counts"], {"overdue": 1, "soon": 1, "pending": 1, "done": 2})
            self.assertEqual(len(tt_res["dossiers"]), 3)

            # 3. Thuong tru -> chi cua rieng thuong_tru
            th_res = self.client.get("/api/dossiers?trang_thai=dang_xu_ly&category_tab=thuong_tru").get_json()
            self.assertEqual(th_res["counts"], {"overdue": 0, "soon": 0, "pending": 2, "done": 1})
            self.assertEqual(len(th_res["dossiers"]), 2)

            # 4. CT10 -> chi cua rieng ct10
            ct_res = self.client.get("/api/dossiers?trang_thai=dang_xu_ly&category_tab=ct10").get_json()
            self.assertEqual(ct_res["counts"], {"overdue": 1, "soon": 0, "pending": 1, "done": 0})

            # 5. Tab tuy chinh do Admin tao -> tinh dung rieng tab do (khong roi ve 'all')
            cs_res = self.client.get("/api/dossiers?trang_thai=dang_xu_ly&category_tab=ho_so_rieng_test").get_json()
            self.assertEqual(cs_res["counts"], {"overdue": 0, "soon": 0, "pending": 1, "done": 1})

            # 6. Loc theo don vi trong Tam tru -> ca 4 o (ke ca 'done') phai theo dung don vi do
            at_tt = self.client.get(f"/api/dossiers?trang_thai=dang_xu_ly&category_tab=tam_tru&unit_filter={self.u_at.code}").get_json()
            self.assertEqual(at_tt["counts"], {"overdue": 1, "soon": 1, "pending": 0, "done": 1})

            # 7. Bam the loc nhanh state_filter=overdue -> giu nguyen 4 con so cua tab, chi loc danh sach tra ve
            ov_tt = self.client.get("/api/dossiers?trang_thai=dang_xu_ly&category_tab=tam_tru&state_filter=overdue").get_json()
            self.assertEqual(ov_tt["counts"], {"overdue": 1, "soon": 1, "pending": 1, "done": 2})
            self.assertEqual([d["ma_ho_so"] for d in ov_tt["dossiers"]], ["STAT-TT-1"])

            # 8. Bam the Da hoan thanh (state_filter=done) -> hien dung 2 ho so da tra cua Tam tru
            dn_tt = self.client.get("/api/dossiers?trang_thai=da_tra&category_tab=tam_tru&state_filter=done").get_json()
            self.assertEqual(dn_tt["counts"], {"overdue": 1, "soon": 1, "pending": 1, "done": 2})
            self.assertEqual(sorted(d["ma_ho_so"] for d in dn_tt["dossiers"]), ["STAT-TT-4", "STAT-TT-5"])
        finally:
            with app.app_context():
                from category_helpers import safe_delete_category_item
                from models import CategoryItem
                c_item = db.session.get(CategoryItem, custom_tab_id)
                if c_item:
                    safe_delete_category_item(c_item)
