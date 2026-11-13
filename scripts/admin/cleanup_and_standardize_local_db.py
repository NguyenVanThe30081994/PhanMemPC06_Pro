# -*- coding: utf-8 -*-
"""
scripts/admin/cleanup_and_standardize_local_db.py

Làm sạch và chuẩn hóa toàn bộ CSDL SQLite local theo đúng cơ cấu CHÍNH QUYỀN 2 CẤP:
1. Bảng Unit: Đúng 268 đơn vị (1 Hệ thống, 19 Sở Ban Ngành, 124 UBND Xã, 124 Công an Xã).
   Xóa sạch 267 bản ghi thừa tq_* (id >= 269).
2. Bảng CategoryItem (nhóm contact_unit):
   Xóa toàn bộ các mục generic cấp huyện cũ (Công an huyện, Công an thị xã, Công an thành phố, Phòng PC06, ...).
   Đồng bộ 267 đơn vị chuẩn vào CategoryItem để mọi module dùng danh mục đều hiển thị nhất quán.
3. Bảng User:
   Chuẩn hóa 535 tài khoản (1 admin hệ thống, 19*2=38 cán bộ cấp tỉnh, 124*2=248 cán bộ UBND xã, 124*2=248 cán bộ CAX).
   Mỗi đơn vị có 1 Quản trị (admin_*) và 1 Cán bộ báo cáo (bc_*).
   Liên kết unit_id, unit_area, unit_key đồng bộ 100%.
   Đặt lại mật khẩu mặc định: TuyenQuang@2026 (admin hệ thống: Dancu@123).
"""

import os
import sys
from pathlib import Path
from werkzeug.security import generate_password_hash

from _admin_script_guard import bootstrap_project_root, require_confirmation

ROOT_DIR = bootstrap_project_root()

from app import app
from models import db, Unit, User, AppRole, CategoryGroup, CategoryItem

PROVINCE_UNITS_DATA = [
    {"code": "vp_ubnd", "name": "Văn phòng UBND tỉnh", "short": "vpubnd"},
    {"code": "tt_pvhcc", "name": "Trung tâm Phục vụ hành chính công", "short": "pvhcc"},
    {"code": "cong_an_tinh", "name": "Công an tỉnh Tuyên Quang", "short": "catinh"},
    {"code": "so_tu_phap", "name": "Sở Tư pháp", "short": "sotuphap"},
    {"code": "so_y_te", "name": "Sở Y tế", "short": "soyte"},
    {"code": "so_gddt", "name": "Sở Giáo dục và Đào tạo", "short": "sogddt"},
    {"code": "so_noi_vu", "name": "Sở Nội vụ", "short": "sonoivu"},
    {"code": "so_tai_chinh", "name": "Sở Tài chính", "short": "sotaichinh"},
    {"code": "bhxh_tinh", "name": "Bảo hiểm xã hội tỉnh", "short": "bhxhtinh"},
    {"code": "cuc_thue_tinh", "name": "Thuế tỉnh", "short": "thuetinh"},
    {"code": "so_nn_mt", "name": "Sở Nông nghiệp và Môi trường", "short": "sonnmt"},
    {"code": "nhnn_khuvuc4", "name": "Ngân hàng Nhà nước chi nhánh khu vực 4", "short": "nhnnkv4"},
    {"code": "so_dt_tg", "name": "Sở Dân tộc và Tôn giáo", "short": "sodttg"},
    {"code": "so_cong_thuong", "name": "Sở Công Thương", "short": "socongthuong"},
    {"code": "so_xay_dung", "name": "Sở Xây dựng", "short": "soxaydung"},
    {"code": "so_vhttdl", "name": "Sở Văn hóa, Thể thao và Du lịch", "short": "sovhttdl"},
    {"code": "so_khcn", "name": "Sở Khoa học và Công nghệ", "short": "sokhcn"},
    {"code": "thanh_tra_tinh", "name": "Thanh tra tỉnh", "short": "thanhtratinh"},
    {"code": "bql_khu_cong_nghiep", "name": "Ban Quản lý các Khu công nghiệp tỉnh", "short": "bqlkcn"},
]

def clean_and_standardize():
    with app.app_context():
        print("=== BẮT ĐẦU CHUẨN HÓA CSDL LOCAL PC06 PRO ===")

        # 1. Xóa các Unit thừa có id >= 269 hoặc code bắt đầu bằng tq_
        deleted_units = Unit.query.filter(Unit.code.like("tq_%")).delete(synchronize_session=False)
        print(f"1. Đã xóa {deleted_units} đơn vị thừa 'tq_*' trong bảng Unit.")

        # Đảm bảo đơn vị Hệ thống có level = 'province'
        hethong = Unit.query.filter_by(code="hethong").first()
        if hethong:
            hethong.level = "province"

        # Đảm bảo 19 Sở ban ngành có level = 'province'
        for p in PROVINCE_UNITS_DATA:
            u = Unit.query.filter_by(code=p["code"]).first()
            if u:
                u.level = "province"
                u.name = p["name"]

        # Đảm bảo các xã/phường có level = 'commune'
        Unit.query.filter(Unit.code.like("ubnd_%")).update({"level": "commune"}, synchronize_session=False)
        Unit.query.filter(Unit.code.like("cax_%")).update({"level": "commune"}, synchronize_session=False)

        total_units = Unit.query.count()
        prov_units = Unit.query.filter_by(level="province").count()
        ubnd_units = Unit.query.filter(Unit.code.like("ubnd_%")).count()
        cax_units = Unit.query.filter(Unit.code.like("cax_%")).count()
        print(f"   -> Bảng Unit hiện có: {total_units} đơn vị (Tỉnh: {prov_units}, UBND Xã: {ubnd_units}, CAX: {cax_units})")

        # 2. Chuẩn hóa nhóm danh mục contact_unit
        cat_group = CategoryGroup.query.filter_by(code="contact_unit").first()
        if not cat_group:
            cat_group = CategoryGroup(code="contact_unit", name="Đơn vị", is_active=True, sort_order=0)
            db.session.add(cat_group)
            db.session.flush()

        # Xóa các mục generic / đơn vị cũ không còn nằm trong bảng Unit đang hoạt động
        active_unit_codes = [
            u.code for u in Unit.query.filter(Unit.is_active.is_(True), Unit.code != 'hethong').all()
        ]
        del_cat = CategoryItem.query.filter(
            CategoryItem.group_id == cat_group.id,
            ~CategoryItem.code.in_(active_unit_codes)
        ).delete(synchronize_session=False)
        print(f"2. Đã xóa {del_cat} mục danh mục thừa/cũ ngoài 267 đơn vị chuẩn trong contact_unit.")

        # Đồng bộ toàn bộ các đơn vị từ bảng Unit vào CategoryItem
        all_active_units = Unit.query.filter(Unit.is_active.is_(True), Unit.code != 'hethong').all()
        synced_cats = 0
        for idx, u in enumerate(all_active_units, start=1):
            ci = CategoryItem.query.filter_by(group_id=cat_group.id, code=u.code).first()
            if not ci:
                ci = CategoryItem(
                    group_id=cat_group.id,
                    code=u.code,
                    name=u.name,
                    is_active=True,
                    sort_order=idx
                )
                db.session.add(ci)
                synced_cats += 1
            else:
                ci.name = u.name
                ci.is_active = True
                ci.sort_order = idx

        print(f"   -> Đã đồng bộ {synced_cats} mục mới vào nhóm danh mục Đơn vị (Tổng: {CategoryItem.query.filter_by(group_id=cat_group.id).count()})")

        # 3. Chuẩn hóa tài khoản User
        pw_hash_default = generate_password_hash("TuyenQuang@2026", method="pbkdf2:sha256")
        pw_hash_admin = generate_password_hash("Dancu@123", method="pbkdf2:sha256")

        # Cập nhật admin hệ thống
        admin_user = User.query.filter_by(username="admin").first()
        if admin_user:
            admin_user.password_hash = pw_hash_admin
            admin_user.unit_area = "Hệ thống"
            admin_user.unit_key = "hethong"

        # Cập nhật unit_id, unit_area, unit_key cho các tài khoản đơn vị
        role_admin = AppRole.query.filter_by(name="Quản trị đơn vị").first()
        role_bc = AppRole.query.filter_by(name="Cán bộ báo cáo").first()

        # A. Cấp Tỉnh
        for p in PROVINCE_UNITS_DATA:
            unit = Unit.query.filter_by(code=p["code"]).first()
            if not unit:
                continue
            for prefix, role in [("admin", role_admin), ("bc", role_bc)]:
                uname = f"{prefix}_{p['short']}"
                usr = User.query.filter_by(username=uname).first()
                if usr:
                    usr.unit_id = unit.id
                    usr.unit_area = unit.name
                    usr.unit_key = unit.code
                    usr.role_id = role.id if role else usr.role_id
                    usr.password_hash = pw_hash_default
                    usr.is_active = True

        # B. Cấp Xã - UBND
        for u in Unit.query.filter(Unit.code.like("ubnd_%")).all():
            c_code = u.code.replace("ubnd_", "")
            for prefix, role in [("admin", role_admin), ("bc", role_bc)]:
                uname = f"{prefix}_ubnd_{c_code}"
                usr = User.query.filter_by(username=uname).first()
                if usr:
                    usr.unit_id = u.id
                    usr.unit_area = u.name
                    usr.unit_key = u.code
                    usr.role_id = role.id if role else usr.role_id
                    usr.password_hash = pw_hash_default
                    usr.is_active = True

        # C. Cấp Xã - CAX
        for u in Unit.query.filter(Unit.code.like("cax_%")).all():
            c_code = u.code.replace("cax_", "")
            for prefix, role in [("admin", role_admin), ("bc", role_bc)]:
                uname = f"{prefix}_cax_{c_code}"
                usr = User.query.filter_by(username=uname).first()
                if usr:
                    usr.unit_id = u.id
                    usr.unit_area = u.name
                    usr.unit_key = u.code
                    usr.role_id = role.id if role else usr.role_id
                    usr.password_hash = pw_hash_default
                    usr.is_active = True

        db.session.commit()
        total_users = User.query.count()
        print(f"3. Đã chuẩn hóa toàn bộ {total_users} tài khoản người dùng.")
        print(f"   -> Mật khẩu tài khoản admin hệ thống: Dancu@123")
        print(f"   -> Mật khẩu 534 tài khoản đơn vị: TuyenQuang@2026")
        print("=== HOÀN TẤT CHUẨN HÓA CSDL THÀNH CÔNG ===")

if __name__ == "__main__":
    require_confirmation("cleanup_and_standardize_local_db.py")
    clean_and_standardize()
