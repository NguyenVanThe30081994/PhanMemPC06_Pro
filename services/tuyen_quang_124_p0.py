# -*- coding: utf-8 -*-
"""Fixture và seed an toàn cho kiểm thử P0 124 xã/phường Tuyên Quang.

Module này chỉ tạo tài khoản có tiền tố được truyền vào (mặc định
``TEST124_``), không đụng tới tài khoản thật. CLI chạy P0 bắt buộc dùng một
database SQLite cô lập; module vẫn có thể được gọi trong test context.
"""

import json
from pathlib import Path

from models import AppRole, CategoryGroup, CategoryItem, Unit, User, db


APP_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = APP_ROOT / "testdata" / "tuyen_quang_124_units.json"
DEFAULT_PREFIX = "TEST124_"
DEFAULT_PASSWORD = "Pc06Test!124"


def load_tuyen_quang_units():
    """Đọc và kiểm tra danh sách 124 đơn vị chính thức."""
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        units = json.load(handle)
    if not isinstance(units, list) or len(units) != 124:
        raise ValueError("Fixture Tuyên Quang phải có đúng 124 đơn vị.")
    codes = {str(item.get("code") or "").strip() for item in units}
    if len(codes) != 124 or "" in codes:
        raise ValueError("Fixture Tuyên Quang có mã đơn vị trùng hoặc rỗng.")
    kind_counts = {kind: sum(item.get("kind") == kind for item in units) for kind in ("xã", "phường")}
    if kind_counts != {"xã": 117, "phường": 7}:
        raise ValueError(f"Cơ cấu fixture không đúng: {kind_counts}")
    return units


def expected_assignment_count(item_count, unit_count=124):
    """Số phân công kỳ vọng khi mỗi đầu mục giao cho mọi đơn vị."""
    item_count = int(item_count)
    unit_count = int(unit_count)
    if item_count < 0 or unit_count < 0:
        raise ValueError("Số đầu mục và số đơn vị không được âm.")
    return item_count * unit_count


def _get_reporting_role():
    role = AppRole.query.filter_by(name="Cán bộ CAX").first()
    if role is None:
        role = AppRole.query.filter_by(name="Cán bộ CAT").first()
    if role is None:
        role = AppRole.query.order_by(AppRole.id.asc()).first()
    if role is None:
        raise RuntimeError("Chưa có vai trò để tạo tài khoản báo cáo kiểm thử.")
    return role


def _get_unit_category_group():
    group = CategoryGroup.query.filter_by(code="contact_unit").first()
    if group is None:
        group = CategoryGroup.query.filter_by(name="Đơn vị").first()
    if group is None:
        group = CategoryGroup(code="contact_unit", name="Đơn vị", is_active=True, sort_order=0)
        db.session.add(group)
        db.session.flush()
    return group


def seed_tuyen_quang_test_accounts(prefix=DEFAULT_PREFIX, password=DEFAULT_PASSWORD):
    """Tạo/cập nhật đúng một tài khoản test cho mỗi xã/phường.

    Hàm idempotent: chạy lại không tạo thêm user. ``created_user_ids`` chỉ
    chứa user mới tạo để test teardown có thể dọn dữ liệu của nó.
    """
    prefix = str(prefix or DEFAULT_PREFIX).strip()
    if not prefix or len(prefix) > 35 or not prefix.replace("_", "").isalnum():
        raise ValueError("Prefix tài khoản không hợp lệ.")
    units = load_tuyen_quang_units()
    role = _get_reporting_role()
    category_group = _get_unit_category_group()
    accounts = []
    created_user_ids = []
    created_count = 0
    updated_count = 0

    for sort_order, item in enumerate(units, start=1):
        code = str(item["code"]).strip()
        name = str(item["name"]).strip()
        unit_key = f"tq{code}"
        unit = Unit.query.filter_by(code=code).first()
        if unit is None:
            unit = Unit(code=code, name=name, level="commune", is_active=True, sort_order=sort_order)
            db.session.add(unit)
            db.session.flush()
        else:
            unit.name = name
            unit.level = "commune"
            unit.is_active = True
            unit.sort_order = sort_order

        item_row = CategoryItem.query.filter_by(group_id=category_group.id, code=unit_key).first()
        if item_row is None:
            item_row = CategoryItem(
                group_id=category_group.id,
                code=unit_key,
                name=name,
                is_active=True,
                sort_order=sort_order,
            )
            db.session.add(item_row)
            db.session.flush()
        else:
            item_row.name = name
            item_row.is_active = True
            item_row.sort_order = sort_order

        username = f"{prefix}{code}"
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username)
            db.session.add(user)
            created_count += 1
            db.session.flush()
            created_user_ids.append(user.id)
        else:
            updated_count += 1
        user.fullname = f"Tài khoản test — {name}"
        user.role_id = role.id
        user.unit_area = unit_key
        user.unit_key = unit_key
        user.unit_id = unit.id
        user.is_active = True
        user.must_change_password = False
        user.set_password(password)
        accounts.append(
            {
                "username": username,
                "password": password,
                "code": code,
                "name": name,
                "kind": item["kind"],
                "unit_id": unit.id,
                "unit_key": unit_key,
            }
        )

    db.session.commit()
    return {
        "created": created_count,
        "updated": updated_count,
        "total": len(accounts),
        "unit_count": len(units),
        "role_id": role.id,
        "accounts": accounts,
        "created_user_ids": created_user_ids,
    }
