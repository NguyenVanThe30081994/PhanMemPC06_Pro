# -*- coding: utf-8 -*-
import csv
import os
from pathlib import Path
import unittest

from app import app
from models import AppRole, CategoryGroup, CategoryItem, Unit, User, db
from scripts.admin import seed_two_tier_government_accounts as seeder


class SeedTwoTierGovernmentAccountsTests(unittest.TestCase):
    """Kiểm thử script seed 267 đơn vị & 534 tài khoản + cấu hình .htaccess."""

    def setUp(self):
        with app.app_context():
            self._orig_unit_ids = {u.id for u in Unit.query.with_entities(Unit.id).all()}
            self._orig_user_ids = {u.id for u in User.query.with_entities(User.id).all()}
            self._orig_cat_item_ids = {c.id for c in CategoryItem.query.with_entities(CategoryItem.id).all()}
            self._orig_group_ids = {g.id for g in CategoryGroup.query.with_entities(CategoryGroup.id).all()}
        self._created_files = []

    def tearDown(self):
        for file_path in self._created_files:
            try:
                os.remove(file_path)
            except OSError:
                pass
        with app.app_context():
            new_users = set(u.id for u in User.query.with_entities(User.id).all()) - self._orig_user_ids
            if new_users:
                User.query.filter(User.id.in_(new_users)).delete(synchronize_session=False)
            new_items = set(c.id for c in CategoryItem.query.with_entities(CategoryItem.id).all()) - self._orig_cat_item_ids
            if new_items:
                CategoryItem.query.filter(CategoryItem.id.in_(new_items)).delete(synchronize_session=False)
            new_groups = set(g.id for g in CategoryGroup.query.with_entities(CategoryGroup.id).all()) - self._orig_group_ids
            if new_groups:
                CategoryGroup.query.filter(CategoryGroup.id.in_(new_groups)).delete(synchronize_session=False)
            new_units = set(u.id for u in Unit.query.with_entities(Unit.id).all()) - self._orig_unit_ids
            if new_units:
                Unit.query.filter(Unit.id.in_(new_units)).delete(synchronize_session=False)
            db.session.commit()

    def test_dry_run_makes_zero_db_and_csv_writes(self):
        with app.app_context():
            before_units = Unit.query.count()
            before_users = User.query.count()
            summary = seeder.run_seed(dry_run=True, init_password="TestSeed@2026")
            db.session.rollback()

            self.assertEqual(summary["units_processed"], 271)
            self.assertEqual(summary["total_accounts"], 1061)
            self.assertEqual(summary["csv_path"], "")
            self.assertEqual(Unit.query.count(), before_units)
            self.assertEqual(User.query.count(), before_users)

    def test_seed_creates_267_units_534_accounts_and_preserves_passwords_on_rerun(self):
        with app.app_context():
            summary = seeder.run_seed(dry_run=False, init_password="InitSeed@2026")
            if summary["csv_path"]:
                self._created_files.append(summary["csv_path"])

            self.assertEqual(summary["units_processed"], 271)
            self.assertEqual(summary["total_accounts"], 1061)
            self.assertTrue(summary["csv_path"])

            # CSV phải nằm ngoài exports/ (trong BACKUP_FOLDER)
            csv_path = Path(summary["csv_path"])
            self.assertTrue(csv_path.exists())
            self.assertNotIn("exports", csv_path.parts)

            with open(csv_path, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1061)

            # Kiểm tra 19 sở ngành chuẩn mới (có pvhcc, sonnmt, sodttg; không có tq_* hay sở cũ)
            self.assertIsNotNone(Unit.query.filter_by(code="tt_pvhcc", level="province").first())
            self.assertIsNone(Unit.query.filter_by(code="so_tttt").first())
            self.assertEqual(Unit.query.filter(Unit.code.like("tq_%")).count(), 0)

            # Kiểm tra chuẩn tên tài khoản Sở ngành, Công an xã/phường, UBND xã/phường, Phòng nội bộ CAT
            for uname in (
                "caxminhquang",
                "caxminhquang_chihuy",
                "caxminhquang_canbo",
                "caxminhquang_quantri",
                "capantuong",
                "capantuong_chihuy",
                "capantuong_canbo",
                "capantuong_quantri",
                "ubndxaminhquang",
                "ubndphuongantuong",
                "ubndxaminhquang_lanhdao",
                "ubndxaminhquang_chuyenvien",
                "ubndxaminhquang_quantri",
                "sokhoahoccongnghe_lanhdao",
                "sokhoahoccongnghe_chuyenvien",
                "sokhoahoccongnghe_quantri",
                "thammuu_quantri",
                "thammuu_lanhdao",
                "thammuu_canbo",
            ):
                self.assertIsNotNone(User.query.filter_by(username=uname).first(), f"Missing account: {uname}")

            bc_tu_phap = User.query.filter_by(username="sotuphap_chuyenvien").first()
            admin_tu_phap = User.query.filter_by(username="sotuphap_quantri").first()
            ld_tu_phap = User.query.filter_by(username="sotuphap_lanhdao").first()
            self.assertIsNotNone(bc_tu_phap)
            self.assertIsNotNone(admin_tu_phap)
            self.assertIsNotNone(ld_tu_phap)
            self.assertEqual(bc_tu_phap.unit_key, "so_tu_phap")
            self.assertTrue(bc_tu_phap.check_password("InitSeed@2026"))
            self.assertEqual(bc_tu_phap.role.name, "Cán bộ báo cáo")
            self.assertEqual(admin_tu_phap.role.name, "Quản trị đơn vị")
            self.assertEqual(ld_tu_phap.role.name, "Lãnh đạo đơn vị")

            # Đảm bảo contact_unit có đủ Unit (bao gồm cấp tỉnh và cấp xã) và không nhân bản CategoryItem có code slug cũ
            contact_group = CategoryGroup.query.filter_by(code="contact_unit").first()
            self.assertIsNotNone(contact_group)
            CategoryItem.query.filter_by(group_id=contact_group.id, code="vp_ubnd").update({"code": "van_phong_ubnd_tinh"})
            db.session.commit()
            seeder.run_seed(dry_run=False, init_password="InitSeed@2026", no_export_csv=True)
            self.assertEqual(
                CategoryItem.query.filter_by(group_id=contact_group.id, name="Văn phòng UBND tỉnh").count(),
                1,
            )
            self.assertIsNotNone(
                CategoryItem.query.filter_by(group_id=contact_group.id, code="vp_ubnd").first()
            )
            self.assertIsNotNone(
                CategoryItem.query.filter_by(group_id=contact_group.id, code="ubnd_00691").first()
            )
            self.assertIsNotNone(
                CategoryItem.query.filter_by(group_id=contact_group.id, code="cax_00691").first()
            )

            # Người dùng đổi mật khẩu -> chạy lại không --reset-existing phải giữ nguyên mật khẩu
            bc_tu_phap.set_password("CustomChanged!99")
            bc_tu_phap.must_change_password = False
            db.session.commit()

            rerun = seeder.run_seed(dry_run=False, init_password="InitSeed@2026", no_export_csv=True)
            self.assertEqual(rerun["users_created"], 0)
            bc_tu_phap = User.query.filter_by(username="sotuphap_chuyenvien").first()
            self.assertTrue(bc_tu_phap.check_password("CustomChanged!99"))
            self.assertFalse(bc_tu_phap.must_change_password)

            # Chỉ reset khi bật --reset-existing
            seeder.run_seed(
                dry_run=False,
                init_password="ResetSeed@2026",
                reset_existing=True,
                no_export_csv=True,
            )
            bc_tu_phap = User.query.filter_by(username="sotuphap_chuyenvien").first()
            self.assertTrue(bc_tu_phap.check_password("ResetSeed@2026"))
            self.assertTrue(bc_tu_phap.must_change_password)

    def test_htaccess_blocks_sensitive_directories_and_files(self):
        htaccess_path = Path(app.root_path) / ".htaccess"
        content = htaccess_path.read_text(encoding="utf-8")
        for protected_dir in ("backups", "exports", "logs", "tmp", "scripts", "tests", "docs", "testdata"):
            self.assertIn(protected_dir, content)
        for protected_file in (".env", ".secret_key", "passenger_wsgi", "requirements", "migrate", "seed_categories"):
            self.assertIn(protected_file, content)


if __name__ == "__main__":
    unittest.main()
