# -*- coding: utf-8 -*-
"""
Kiểm thử cơ chế Quản trị danh mục tập trung & Đồng bộ 2 chiều:
- Gom tự động danh mục từ các chức năng (Unit, Task, NotificationDoc, NewsDoc, DocumentLib, ShortLink, Contact, Dossier) về Quản trị danh mục.
- Tính lũy đẳng (idempotent) khi gom nhiều lần, không tạo trùng.
- Thao tác trên /admin/module-categories: đổi tên (rename_item), ẩn/hiện (toggle_item), sắp xếp (move_item), gộp (merge_item), xóa an toàn (delete_item), liên kết field (save_binding), giữ nguyên ngữ cảnh lọc (?pane=...&group=...).
- Đồng bộ 2 chiều giữa /admin/units <-> nhóm Đơn vị (contact_unit) và cập nhật sang /dossiers, /tasks, ShortLink, Contact.
- Chuyển hướng /admin/categories -> /admin/module-categories?pane=categories.
"""
import json
import re
import time
import unittest
from datetime import date

from app import app
from category_helpers import (
    ensure_unified_category_catalog,
    harvest_feature_categories_to_admin,
    module_category_options,
    resolve_category_display,
)
from models import (
    AppRole,
    CategoryGroup,
    CategoryItem,
    CategoryItemAlias,
    Contact,
    Dossier,
    ModuleFieldBinding,
    ModuleRegistry,
    NotificationDoc,
    ShortLink,
    Task,
    Unit,
    User,
    db,
)


class UnifiedCategoriesTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        with app.app_context():
            ensure_unified_category_catalog(commit=True)
            admin_role = AppRole.query.filter_by(name="Quản trị hệ thống").first()
            if not admin_role:
                admin_role = AppRole(name="Quản trị hệ thống", level="system", perms=json.dumps({"sys": 2, "task": 2}))
                db.session.add(admin_role)
                db.session.commit()
            usr = User.query.filter_by(username="unified_cat_admin").first()
            if not usr:
                usr = User(
                    username="unified_cat_admin",
                    fullname="Admin Danh Mục",
                    role_id=admin_role.id,
                    is_active=True,
                    must_change_password=False,
                )
                usr.set_password("StrongPass1!")
                db.session.add(usr)
                db.session.commit()
            self.admin_uid = usr.id

    def tearDown(self):
        with app.app_context():
            Dossier.query.filter(Dossier.ma_ho_so.like("HS-UNIFIED-%")).delete(synchronize_session=False)
            Task.query.filter(Task.title.like("[UCAT-TEST]%")).delete(synchronize_session=False)
            NotificationDoc.query.filter(NotificationDoc.title.like("[UCAT-TEST]%")).delete(synchronize_session=False)
            ShortLink.query.filter(ShortLink.short_code.like("ucat_%")).delete(synchronize_session=False)
            Contact.query.filter(Contact.name.like("[UCAT-TEST]%")).delete(synchronize_session=False)
            Unit.query.filter(Unit.code.like("ucat_unit_%")).delete(synchronize_session=False)
            db.session.commit()

    def _login_admin(self):
        with app.app_context():
            usr = db.session.get(User, self.admin_uid)
            sv = int(getattr(usr, "session_version", 0) or 0) if usr else 0
        with self.client.session_transaction() as sess:
            sess["uid"] = self.admin_uid
            sess["session_version"] = sv
            sess["last_active"] = time.time()
            sess["csrf_token"] = "test-csrf-token"

    def _post_admin(self, url, data):
        payload = dict(data)
        payload.setdefault("csrf_token", "test-csrf-token")
        return self.client.post(url, data=payload, follow_redirects=False)

    def test_ensure_unified_catalog_and_harvest_idempotent(self):
        with app.app_context():
            db.session.add(Task(title="[UCAT-TEST] Nhiệm vụ 1", category="Chuyển đổi số cơ sở XYZ", domain="Đội An ninh mạng Test", task_type="Báo cáo đột xuất Test", priority="Khẩn cấp Test"))
            db.session.add(NotificationDoc(title="[UCAT-TEST] TB 1", category="Cảnh báo lừa đảo Test", kind="text"))
            db.session.add(ShortLink(short_code="ucat_sl1", original_url="https://example.com", category="Tài liệu nội bộ Test", domain="Đội Tổng hợp Test"))
            db.session.add(Contact(name="[UCAT-TEST] Cán bộ 1", phone="0912345678", contact_group="Tổ công tác đặc biệt Test", role="Tổ trưởng Test", unit_name="Đơn vị thử nghiệm XYZ"))
            db.session.add(Dossier(ma_ho_so="HS-UNIFIED-01", loai="Hồ sơ đặc thù Test", category_tab="tam_tru", so_ho_so="HS-UNIFIED-01", thu_tuc="Đăng ký tạm trú", han_tra=date.today(), trang_thai="dang_xu_ly"))
            db.session.add(Unit(code="ucat_unit_harvest", name="Công an Xã Đồng Văn Test", level="commune", is_active=True))
            db.session.commit()

            stats1 = harvest_feature_categories_to_admin(commit=True)
            self.assertGreater(stats1.get("added_items", 0), 0)

            dossiers_mod = ModuleRegistry.query.filter_by(code="dossiers").first()
            self.assertIsNotNone(dossiers_mod)
            tasks_mod = ModuleRegistry.query.filter_by(code="tasks").first()
            self.assertIsNotNone(ModuleFieldBinding.query.filter_by(module_id=tasks_mod.id, field_code="category").first())
            self.assertIsNotNone(ModuleFieldBinding.query.filter_by(module_id=dossiers_mod.id, field_code="category_tab").first())
            self.assertIsNotNone(ModuleFieldBinding.query.filter_by(module_id=dossiers_mod.id, field_code="loai").first())

            expected_in_groups = [
                ("news_domain", "Chuyển đổi số cơ sở XYZ"),
                ("news_domain", "Cảnh báo lừa đảo Test"),
                ("news_domain", "Tài liệu nội bộ Test"),
                ("task_unit", "Đội An ninh mạng Test"),
                ("task_unit", "Đội Tổng hợp Test"),
                ("task_type", "Báo cáo đột xuất Test"),
                ("task_priority", "Khẩn cấp Test"),
                ("contact_group", "Tổ công tác đặc biệt Test"),
                ("contact_role", "Tổ trưởng Test"),
                ("contact_unit", "Đơn vị thử nghiệm XYZ"),
                ("contact_unit", "Công an Xã Đồng Văn Test"),
                ("dossier_type", "Hồ sơ đặc thù Test"),
            ]
            for gcode, iname in expected_in_groups:
                grp = CategoryGroup.query.filter_by(code=gcode).first()
                self.assertIsNotNone(grp, f"Missing group {gcode}")
                found = CategoryItem.query.filter_by(group_id=grp.id, name=iname).first()
                self.assertIsNotNone(found, f"Expected '{iname}' harvested into '{gcode}'")

            # Lần 2 không được sinh trùng
            stats2 = harvest_feature_categories_to_admin(commit=True)
            self.assertEqual(stats2.get("added_items", 0), 0)

    def test_admin_actions_propagate_to_dossiers_tasks_and_records(self):
        self._login_admin()

        with app.app_context():
            tab_grp = CategoryGroup.query.filter_by(code="dossier_tab").first()
            loai_grp = CategoryGroup.query.filter_by(code="dossier_type").first()
            domain_grp = CategoryGroup.query.filter_by(code="news_domain").first()
            self.assertIsNotNone(tab_grp)
            self.assertIsNotNone(loai_grp)
            self.assertIsNotNone(domain_grp)

            tam_tru_item = CategoryItem.query.filter_by(group_id=tab_grp.id, code="tam_tru").first()
            loai_src = CategoryItem(group_id=loai_grp.id, code="loai-cu-test", name="Loại cũ cần gộp", is_active=True, sort_order=910)
            loai_dst = CategoryItem(group_id=loai_grp.id, code="loai-moi-test", name="Loại chuẩn sau gộp", is_active=True, sort_order=920)
            domain_item = CategoryItem(group_id=domain_grp.id, code="lv-cu-test", name="Lĩnh vực thử nghiệm A", is_active=True, sort_order=900)
            db.session.add_all([loai_src, loai_dst, domain_item])
            db.session.flush()

            tam_tru_id = tam_tru_item.id
            loai_src_id = loai_src.id
            loai_dst_id = loai_dst.id
            domain_item_id = domain_item.id
            tab_gid = tab_grp.id
            loai_gid = loai_grp.id
            domain_gid = domain_grp.id

            db.session.add(Dossier(
                ma_ho_so="HS-UNIFIED-02",
                loai=loai_src.code,
                category_tab="tam_tru",
                so_ho_so="HS-UNIFIED-02",
                thu_tuc="Đăng ký tạm trú",
                han_tra=date.today(),
                trang_thai="dang_xu_ly",
            ))
            db.session.add(Task(
                title="[UCAT-TEST] Nhiệm vụ đồng bộ",
                category="Lĩnh vực thử nghiệm A",
                domain="Đội Tổng hợp",
            ))
            db.session.add(ShortLink(
                short_code="ucat_sl2",
                original_url="https://example.org",
                category=f"category_item:{domain_item_id}",
                domain="",
            ))
            db.session.commit()

        # 1. Đổi tên item thuộc nhóm news_domain & dossier_tab
        resp = self._post_admin("/admin/module-categories", {
            "action": "rename_item",
            "item_id": str(domain_item_id),
            "item_name": "Lĩnh vực chuẩn mới B",
            "return_pane": "categories",
            "selected_group": str(domain_gid),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("pane=categories", resp.headers["Location"])
        self.assertIn(f"group={domain_gid}", resp.headers["Location"])

        resp_tab = self._post_admin("/admin/module-categories", {
            "action": "rename_item",
            "item_id": str(tam_tru_id),
            "item_name": "Tạm trú Đã Đổi Tên",
            "return_pane": "categories",
            "selected_group": str(tab_gid),
        })
        self.assertEqual(resp_tab.status_code, 302)

        with app.app_context():
            task_row = Task.query.filter_by(title="[UCAT-TEST] Nhiệm vụ đồng bộ").first()
            self.assertEqual(task_row.category, f"category_item:{domain_item_id}")
            resolved_task = resolve_category_display(task_row.category, module_category_options("tasks", "category"))
            self.assertEqual(resolved_task["display_name"], "Lĩnh vực chuẩn mới B")
            alias = CategoryItemAlias.query.filter_by(item_id=domain_item_id, alias_name="Lĩnh vực thử nghiệm A").first()
            self.assertIsNotNone(alias)
            sl_row = ShortLink.query.filter_by(short_code="ucat_sl2").first()
            resolved_sl = resolve_category_display(sl_row.category, module_category_options("notify", "category"))
            self.assertEqual(resolved_sl["display_name"], "Lĩnh vực chuẩn mới B")

        page_tasks = self.client.get("/tasks")
        self.assertEqual(page_tasks.status_code, 200)
        tasks_html = page_tasks.get_data(as_text=True)
        visible_tasks_text = re.sub(r"<[^>]+>", " ", tasks_html)
        self.assertIn("Lĩnh vực chuẩn mới B", visible_tasks_text)
        self.assertNotIn(f"category_item:{domain_item_id}", visible_tasks_text)

        api_dossiers = self.client.get("/api/dossiers?category_tab=tam_tru")
        self.assertEqual(api_dossiers.status_code, 200)
        dossiers_json = api_dossiers.get_json()
        matched_rows = [r for r in dossiers_json["dossiers"] if r["ma_ho_so"] == "HS-UNIFIED-02"]
        self.assertEqual(len(matched_rows), 1)
        self.assertEqual(matched_rows[0]["category_tab_label"], "Tạm trú Đã Đổi Tên")
        self.assertEqual(dossiers_json["tab_counts"]["tam_tru"]["pending"], 1)

        page_dossiers = self.client.get("/dossiers")
        self.assertIn("Tạm trú Đã Đổi Tên", page_dossiers.get_data(as_text=True))

        # 2. Gộp loại hồ sơ (merge_item): mọi hồ sơ loai cũ chuyển sang loai mới
        resp_merge = self._post_admin("/admin/module-categories", {
            "action": "merge_item",
            "source_item_id": str(loai_src_id),
            "target_item_id": str(loai_dst_id),
            "return_pane": "categories",
            "selected_group": str(loai_gid),
        })
        self.assertEqual(resp_merge.status_code, 302)
        with app.app_context():
            self.assertIsNone(db.session.get(CategoryItem, loai_src_id))
            dos = Dossier.query.filter_by(ma_ho_so="HS-UNIFIED-02").first()
            self.assertEqual(dos.loai, "loai-moi-test")

        # 3. Ẩn mục (toggle_item) nhưng lịch sử vẫn hiển thị nhãn đúng, sau đó khôi phục
        self._post_admin("/admin/module-categories", {
            "action": "toggle_item",
            "item_id": str(domain_item_id),
            "return_pane": "categories",
            "selected_group": str(domain_gid),
        })
        with app.app_context():
            opts = module_category_options("notify", "category")
            self.assertNotIn("Lĩnh vực chuẩn mới B", [o["name"] for o in opts])
            sl_row = ShortLink.query.filter_by(short_code="ucat_sl2").first()
            resolved_hidden = resolve_category_display(sl_row.category, opts)
            self.assertEqual(resolved_hidden["display_name"], "Lĩnh vực chuẩn mới B")
            self.assertFalse(resolved_hidden["display_name"].startswith("category_item:"))

        # 4. Sắp xếp lên/xuống (move_item)
        self._post_admin("/admin/module-categories", {
            "action": "move_item",
            "item_id": str(loai_dst_id),
            "direction": "up",
            "return_pane": "categories",
            "selected_group": str(loai_gid),
        })
        with app.app_context():
            loai_items = CategoryItem.query.filter_by(group_id=loai_gid).order_by(CategoryItem.sort_order, CategoryItem.id).all()
            loai_ids = [x.id for x in loai_items]
            self.assertLess(loai_ids.index(loai_dst_id), len(loai_ids) - 1)

        # 5. Xóa an toàn (delete_item): không để lại category_item:<id> mồ côi
        self._post_admin("/admin/module-categories", {
            "action": "delete_item",
            "item_id": str(domain_item_id),
            "return_pane": "categories",
            "selected_group": str(domain_gid),
        })
        with app.app_context():
            self.assertIsNone(db.session.get(CategoryItem, domain_item_id))
            sl_row = ShortLink.query.filter_by(short_code="ucat_sl2").first()
            self.assertEqual(sl_row.category, "Lĩnh vực chuẩn mới B")

        # Dọn gọn item thử nghiệm (bao gồm item đã nhận alias từ merge)
        self._post_admin("/admin/module-categories", {
            "action": "delete_item",
            "item_id": str(loai_dst_id),
            "return_pane": "categories",
            "selected_group": str(loai_gid),
        })
        with app.app_context():
            self.assertIsNone(db.session.get(CategoryItem, loai_dst_id))
            t_item = db.session.get(CategoryItem, tam_tru_id)
            if t_item:
                t_item.name = "Tạm trú"
            db.session.commit()

    def test_unit_bidirectional_sync_and_admin_categories_redirect(self):
        self._login_admin()

        # /admin/categories phải chuyển hướng về màn hình quản trị tập trung
        redir = self.client.get("/admin/categories", follow_redirects=False)
        self.assertEqual(redir.status_code, 302)
        self.assertIn("/admin/module-categories?pane=categories", redir.headers["Location"])

        # Thêm đơn vị trên /admin/units -> tự đồng bộ vào contact_unit
        self._post_admin("/admin/units", {
            "action": "add_unit",
            "name": "Phòng Kiểm Thử Sync",
            "code": "ucat_unit_sync",
            "level": "province",
        })
        with app.app_context():
            unit = Unit.query.filter_by(code="ucat_unit_sync").first()
            self.assertIsNotNone(unit)
            unit_grp = CategoryGroup.query.filter_by(code="contact_unit").first()
            cat_item = CategoryItem.query.filter_by(group_id=unit_grp.id, name="Phòng Kiểm Thử Sync").first()
            self.assertIsNotNone(cat_item)
            cat_id = cat_item.id
            unit_id = unit.id

        # Đổi tên bên Quản trị danh mục -> Unit phải tự cập nhật
        self._post_admin("/admin/module-categories", {
            "action": "rename_item",
            "item_id": str(cat_id),
            "item_name": "Phòng Kiểm Thử Đã Đổi",
            "return_pane": "categories",
        })
        with app.app_context():
            unit = db.session.get(Unit, unit_id)
            self.assertEqual(unit.name, "Phòng Kiểm Thử Đã Đổi")

        # Sửa ngược lại từ /admin/units -> CategoryItem phải tự cập nhật
        self._post_admin("/admin/units", {
            "action": "edit_unit",
            "unit_id": str(unit_id),
            "name": "Phòng Kiểm Thử Cuối",
            "code": "ucat_unit_sync",
            "level": "province",
            "is_active": "1",
        })
        with app.app_context():
            cat_item = db.session.get(CategoryItem, cat_id)
            self.assertEqual(cat_item.name, "Phòng Kiểm Thử Cuối")

        # Xóa unit -> CategoryItem tương ứng bị xóa theo
        self._post_admin("/admin/units", {
            "action": "delete_unit",
            "unit_id": str(unit_id),
        })
        with app.app_context():
            self.assertIsNone(Unit.query.filter_by(code="ucat_unit_sync").first())
            self.assertIsNone(db.session.get(CategoryItem, cat_id))

    def test_harvest_all_post_and_save_binding(self):
        self._login_admin()
        with app.app_context():
            tasks_mod = ModuleRegistry.query.filter_by(code="tasks").first()
            news_grp = CategoryGroup.query.filter_by(code="news_domain").first()
            tasks_mod_id = tasks_mod.id
            news_gid = news_grp.id

        res_harvest = self._post_admin("/admin/module-categories", {
            "action": "harvest_all",
            "return_pane": "categories",
        })
        self.assertEqual(res_harvest.status_code, 302)

        res_bind = self._post_admin("/admin/module-categories", {
            "action": "save_binding",
            "module_id": str(tasks_mod_id),
            "field_code": "category",
            "field_label": "Lĩnh vực công việc",
            "group_id": str(news_gid),
            "return_pane": "bindings",
        })
        self.assertEqual(res_bind.status_code, 302)
        self.assertIn("pane=bindings", res_bind.headers["Location"])

        page = self.client.get("/admin/module-categories?pane=bindings")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Sổ theo dõi hồ sơ", html)
        self.assertIn("Phân hệ hồ sơ", html)
        self.assertIn("Loại hồ sơ", html)


if __name__ == "__main__":
    unittest.main()
