# -*- coding: utf-8 -*-
"""
scripts/admin/seed_two_tier_government_accounts.py

Khởi tạo danh sách đơn vị và tài khoản người dùng theo mô hình CHÍNH QUYỀN 2 CẤP
(Tỉnh - Xã) phục vụ triển khai Đề án 06 tỉnh Tuyên Quang (sau sắp xếp ĐVHC 2026).

Cơ cấu đơn vị (267 đơn vị chuẩn):
  1. Cấp Tỉnh: 19 Sở, Ban, Ngành (level='province').
  2. Cấp Xã: 124 Xã, Phường x 2 ngành dọc = 248 đơn vị (UBND Xã/Phường và Công an Xã/Phường, level='commune').

Cơ cấu tài khoản trong mỗi đơn vị (534 tài khoản):
  - 1 Tài khoản Quản trị đơn vị (`admin_<ma>`): quản trị nội bộ, tiếp nhận, phân công.
  - 1 Tài khoản Cán bộ báo cáo (`bc_<ma>`): tiếp nhận, nhập số liệu, nộp báo cáo.

Cách chạy trên DirectAdmin / cPanel (SSH hoặc Terminal):
  - Xem trước (không ghi DB, không xuất file mật khẩu):
      python scripts/admin/seed_two_tier_government_accounts.py --dry-run
  - Khởi tạo tài khoản còn thiếu (giữ nguyên mật khẩu tài khoản đã tồn tại):
      PC06_CONFIRM=YES python scripts/admin/seed_two_tier_government_accounts.py
  - Khởi tạo với mật khẩu khởi tạo tự chọn:
      PC06_CONFIRM=YES python scripts/admin/seed_two_tier_government_accounts.py --password=Dancu@2026
  - Đồng bộ lại VÀ đặt lại mật khẩu cho cả tài khoản đã tồn tại:
      PC06_CONFIRM=YES python scripts/admin/seed_two_tier_government_accounts.py --reset-existing
  - Chỉ định đường dẫn xuất CSV bàn giao (mặc định lưu vào BACKUP_FOLDER ngoài public_html):
      PC06_CONFIRM=YES python scripts/admin/seed_two_tier_government_accounts.py --export-csv=~/accounts_2026.csv
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

try:
    from _admin_script_guard import bootstrap_project_root, require_confirmation
except ImportError:
    from scripts.admin._admin_script_guard import bootstrap_project_root, require_confirmation

bootstrap_project_root()

from werkzeug.security import generate_password_hash
from app import app
from models import AppRole, CategoryGroup, CategoryItem, Unit, User, db
from utils import ensure_standard_system_roles

# 19 Sở, Ban, Ngành cấp tỉnh chuẩn theo ĐVHC sau sắp xếp (đồng bộ seed_categories.py & outline.py)
PROVINCE_UNITS = [
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

DEFAULT_INIT_PASSWORD = "TuyenQuang@2026"
_KEEP_PASSWORD_NOTE = "(giữ nguyên mật khẩu hiện tại)"


def ensure_roles(dry_run=False):
    """Đảm bảo đủ 8 vai trò chuẩn và trả về cặp (Quản trị đơn vị, Cán bộ báo cáo)."""
    if not dry_run:
        ensure_standard_system_roles(force_update_perms=False)
    role_admin = AppRole.query.filter_by(name="Quản trị đơn vị").first()
    role_reporter = AppRole.query.filter_by(name="Cán bộ báo cáo").first()
    return role_admin, role_reporter


def _ensure_system_unit(dry_run=False):
    """Đảm bảo đơn vị Hệ thống tồn tại ở level='province'."""
    hethong = Unit.query.filter_by(code="hethong").first()
    if not hethong and not dry_run:
        hethong = Unit(code="hethong", name="Hệ thống", level="province", is_active=True, sort_order=0)
        db.session.add(hethong)
        db.session.flush()
    elif hethong and not dry_run:
        hethong.level = "province"
        hethong.is_active = True


def _seed_unit_and_accounts(
    *,
    u_code,
    u_name,
    unit_level,
    cap_label,
    khoi_label,
    account_suffix,
    sort_order,
    group,
    role_admin,
    role_reporter,
    precalc_hash,
    init_password,
    dry_run,
    reset_existing,
    export_rows,
    counters,
):
    """Tạo/đồng bộ 1 Unit, 1 CategoryItem (contact_unit) và 2 User (admin + báo cáo)."""
    unit = Unit.query.filter_by(code=u_code).first()
    if not unit:
        unit = Unit(code=u_code, name=u_name, level=unit_level, is_active=True, sort_order=sort_order)
        if not dry_run:
            db.session.add(unit)
            db.session.flush()
        counters["units_created"] += 1
    elif not dry_run:
        unit.name = u_name
        unit.level = unit_level
        unit.is_active = True
        unit.sort_order = sort_order

    if not dry_run and group and group.id:
        c_item = CategoryItem.query.filter(
            CategoryItem.group_id == group.id,
            db.or_(CategoryItem.code == u_code, CategoryItem.name == u_name),
        ).first()
        if not c_item:
            db.session.add(
                CategoryItem(
                    group_id=group.id,
                    code=u_code,
                    name=u_name,
                    is_active=True,
                    sort_order=sort_order,
                )
            )
        else:
            c_item.code = u_code
            c_item.name = u_name
            c_item.is_active = True
            c_item.sort_order = sort_order

    accounts = (
        {
            "username": f"admin_{account_suffix}",
            "fullname": f"Quản trị - {u_name}",
            "role": role_admin,
            "role_name": "Quản trị đơn vị",
        },
        {
            "username": f"bc_{account_suffix}",
            "fullname": f"Cán bộ báo cáo - {u_name}",
            "role": role_reporter,
            "role_name": "Cán bộ báo cáo",
        },
    )

    for acc in accounts:
        usr = User.query.filter_by(username=acc["username"]).first()
        is_new = usr is None
        password_changed = is_new or reset_existing

        if is_new:
            counters["users_created"] += 1
            if not dry_run:
                usr = User(username=acc["username"])
        else:
            counters["users_updated"] += 1

        if not dry_run and usr is not None:
            usr.fullname = acc["fullname"]
            usr.role_id = acc["role"].id if acc["role"] else usr.role_id
            usr.unit_area = u_name
            usr.unit_key = u_code
            usr.unit_id = unit.id if unit and unit.id else usr.unit_id
            usr.is_active = True
            if password_changed:
                usr.must_change_password = True
                usr.password_hash = precalc_hash
            db.session.add(usr)

        if is_new:
            status_label = "Mới tạo"
        elif reset_existing:
            status_label = "Đặt lại mật khẩu"
        else:
            status_label = "Đồng bộ (giữ mật khẩu)"

        export_rows.append(
            {
                "cap": cap_label,
                "khoi": khoi_label,
                "don_vi": u_name,
                "unit_code": u_code,
                "vai_tro": acc["role_name"],
                "username": acc["username"],
                "password": init_password if password_changed else _KEEP_PASSWORD_NOTE,
                "trang_thai": status_label,
            }
        )


def _resolve_default_export_path():
    """Lưu CSV ngoài public_html (BACKUP_FOLDER thuộc PC06_DATA_DIR hoặc backups/)."""
    backup_folder = (app.config.get("BACKUP_FOLDER") or "").strip()
    if backup_folder:
        return Path(backup_folder) / "danh_sach_tai_khoan_chinh_quyen_2_cap.csv"
    return Path(app.root_path) / "backups" / "danh_sach_tai_khoan_chinh_quyen_2_cap.csv"


def _write_export_csv(csv_path, export_rows):
    csv_path = Path(csv_path).expanduser().resolve()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["cap", "khoi", "don_vi", "unit_code", "vai_tro", "username", "password", "trang_thai"],
        )
        writer.writeheader()
        writer.writerows(export_rows)
    try:
        os.chmod(csv_path, 0o600)
    except OSError:
        pass
    return csv_path


def run_seed(
    dry_run=False,
    init_password=DEFAULT_INIT_PASSWORD,
    reset_existing=False,
    export_csv=None,
    no_export_csv=False,
):
    """Khởi tạo 267 đơn vị và 534 tài khoản chính quyền 2 cấp Tuyên Quang."""
    fixture_path = Path(app.root_path) / "testdata" / "tuyen_quang_124_units.json"
    if not fixture_path.exists():
        raise FileNotFoundError(f"Không tìm thấy fixture 124 xã tại: {fixture_path}")

    with open(fixture_path, "r", encoding="utf-8") as f:
        commune_list = json.load(f)

    print("=== BẮT ĐẦU SEED TÀI KHOẢN CHÍNH QUYỀN 2 CẤP (TỈNH - XÃ) ===")
    print(f"Chế độ: {'DRY RUN (Xem thử, KHÔNG ghi DB)' if dry_run else 'THI HÀNH THẬT'}")
    print(f"Cập nhật tài khoản đã có: {'Đặt lại mật khẩu' if reset_existing else 'Giữ nguyên mật khẩu hiện tại'}")
    print(f"Tổng số Sở, Ban, Ngành cấp tỉnh: {len(PROVINCE_UNITS)}")
    print(f"Tổng số Xã, Phường cấp cơ sở: {len(commune_list)} (chia 2 khối UBND và Công an)")
    print("-----------------------------------------------------------------")

    precalc_hash = generate_password_hash(init_password, method="pbkdf2:sha256")
    role_admin, role_reporter = ensure_roles(dry_run=dry_run)
    _ensure_system_unit(dry_run=dry_run)

    group = CategoryGroup.query.filter_by(code="contact_unit").first()
    if not group and not dry_run:
        group = CategoryGroup(code="contact_unit", name="Đơn vị", is_active=True, sort_order=0)
        db.session.add(group)
        db.session.flush()

    export_rows = []
    counters = {"units_created": 0, "users_created": 0, "users_updated": 0}

    # 1. CẤP TỈNH: 19 SỞ BAN NGÀNH
    for idx, p_unit in enumerate(PROVINCE_UNITS, start=1):
        _seed_unit_and_accounts(
            u_code=p_unit["code"],
            u_name=p_unit["name"],
            unit_level="province",
            cap_label="Cấp Tỉnh",
            khoi_label="Sở, Ban, Ngành",
            account_suffix=p_unit["short"],
            sort_order=idx,
            group=group,
            role_admin=role_admin,
            role_reporter=role_reporter,
            precalc_hash=precalc_hash,
            init_password=init_password,
            dry_run=dry_run,
            reset_existing=reset_existing,
            export_rows=export_rows,
            counters=counters,
        )

    # 2. CẤP XÃ: 124 XÃ / PHƯỜNG (Khối UBND xã và Khối Công an xã)
    for idx, c_item in enumerate(commune_list, start=100):
        c_code = str(c_item["code"]).strip()
        c_name = str(c_item["name"]).strip()

        _seed_unit_and_accounts(
            u_code=f"ubnd_{c_code}",
            u_name=f"UBND {c_name}",
            unit_level="commune",
            cap_label="Cấp Xã",
            khoi_label="UBND Xã, Phường",
            account_suffix=f"ubnd_{c_code}",
            sort_order=idx * 2,
            group=group,
            role_admin=role_admin,
            role_reporter=role_reporter,
            precalc_hash=precalc_hash,
            init_password=init_password,
            dry_run=dry_run,
            reset_existing=reset_existing,
            export_rows=export_rows,
            counters=counters,
        )

        _seed_unit_and_accounts(
            u_code=f"cax_{c_code}",
            u_name=f"Công an {c_name}",
            unit_level="commune",
            cap_label="Cấp Xã",
            khoi_label="Công an Xã, Phường",
            account_suffix=f"cax_{c_code}",
            sort_order=idx * 2 + 1,
            group=group,
            role_admin=role_admin,
            role_reporter=role_reporter,
            precalc_hash=precalc_hash,
            init_password=init_password,
            dry_run=dry_run,
            reset_existing=reset_existing,
            export_rows=export_rows,
            counters=counters,
        )

    if not dry_run:
        db.session.commit()
        print("[HOAN TAT] Đã ghi thành công toàn bộ dữ liệu vào Database!")

    written_csv = None
    should_write_csv = (not no_export_csv) and (not dry_run or bool(export_csv))
    if should_write_csv:
        target_csv = export_csv or _resolve_default_export_path()
        written_csv = _write_export_csv(target_csv, export_rows)

    print("-----------------------------------------------------------------")
    print("Tổng kết:")
    print(f" - Số đơn vị xử lý: {len(PROVINCE_UNITS) + len(commune_list) * 2}")
    print(f" - Số đơn vị tạo mới trong Unit: {counters['units_created']}")
    print(f" - Số tài khoản tạo mới: {counters['users_created']}")
    print(f" - Số tài khoản đã có (đồng bộ): {counters['users_updated']}")
    print(f" - Tổng tài khoản trong danh sách: {len(export_rows)}")
    if written_csv:
        print(f" - File CSV bàn giao (chmod 600): {written_csv}")
    else:
        print(" - File CSV bàn giao: không xuất ở chế độ này")
    print("=================================================================")

    return {
        "units_processed": len(PROVINCE_UNITS) + len(commune_list) * 2,
        "units_created": counters["units_created"],
        "users_created": counters["users_created"],
        "users_updated": counters["users_updated"],
        "total_accounts": len(export_rows),
        "csv_path": str(written_csv) if written_csv else "",
    }


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Khởi tạo hàng loạt 267 đơn vị và 534 tài khoản chính quyền 2 cấp Tuyên Quang.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Xem trước số lượng, không ghi vào DB.")
    parser.add_argument("--password", default=DEFAULT_INIT_PASSWORD, help="Mật khẩu khởi tạo cho tài khoản mới.")
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="Đặt lại mật khẩu cả cho tài khoản đã tồn tại (mặc định giữ nguyên).",
    )
    parser.add_argument("--export-csv", default="", help="Đường dẫn tùy chọn để xuất CSV bàn giao tài khoản.")
    parser.add_argument("--no-export-csv", action="store_true", help="Không ghi file CSV ra đĩa.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    if not args.dry_run:
        require_confirmation("seed_two_tier_government_accounts.py")

    init_pw = (args.password or "").strip() or DEFAULT_INIT_PASSWORD
    with app.app_context():
        run_seed(
            dry_run=args.dry_run,
            init_password=init_pw,
            reset_existing=args.reset_existing,
            export_csv=args.export_csv or None,
            no_export_csv=args.no_export_csv,
        )
