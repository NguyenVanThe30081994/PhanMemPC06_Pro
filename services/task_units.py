# -*- coding: utf-8 -*-
"""
Nhận diện / đối sánh đơn vị (unit matching) và quy đổi người nhận theo đơn vị/vai trò.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

import re

from category_helpers import canonicalize_category_value, resolve_category_display
from models import AppRole, User, db
from services.task_categories import _task_assignment_unit_options, _task_domain_options
from utils import extract_unit_key, is_unit_match, remove_accents


def _dedupe_users(users):
    unique_users = []
    seen_ids = set()
    for user in users:
        if user and user.id not in seen_ids:
            seen_ids.add(user.id)
            unique_users.append(user)
    return unique_users


def _user_unit_key(user):
    return _task_unit_identity(user).get("unit_key", "")


def _is_category_item_reference_local(value):
    return bool(re.fullmatch(r"category_item:\d+", (value or "").strip().lower()))


def _is_generic_task_unit_key(value):
    if _is_category_item_reference_local(value):
        return True
    normalized = re.sub(r"[^a-z0-9]", "", remove_accents(value or "")).strip().lower()
    return normalized in {
        "",
        "sobannganh",
        "sobannganhcaptinh",
        "khoisobannganh",
        "xa",
        "phuong",
        "huyen",
        "quan",
        "tp",
        "thi",
        "tran",
        "capxa",
        "caphuong",
        "caphuyen",
        "captinh",
        "congancapxa",
        "congancaphuong",
        "congancaphuongxa",
        "congancaphuyen",
        "congancaptinh",
        "ubndcapxa",
        "ubndcaphuong",
        "ubndcaphuyen",
        "ubndcaptinh",
        "hethong",
    }


def _is_generic_task_unit_name(value):
    if _is_category_item_reference_local(value):
        return True
    normalized = re.sub(r"[^a-z0-9]", "", remove_accents(value or "")).strip().lower()
    return normalized in {
        "",
        "sobannganh",
        "sobannganhcaptinh",
        "khoisobannganh",
        "congancapxa",
        "congancaphuong",
        "congancaphuongxa",
        "congancaphuyen",
        "congancaptinh",
        "ubndcapxa",
        "ubndcaphuong",
        "ubndcaphuyen",
        "ubndcaptinh",
        "capxa",
        "caphuong",
        "caphuyen",
        "captinh",
        "hethong",
    }


def _looks_like_task_unit_name(value):
    normalized = re.sub(r"\s+", " ", remove_accents(value or "")).strip().lower()
    return any(
        token in normalized
        for token in [
            "cong an",
            "ubnd",
            "doi ",
            "phong ",
            "ban ",
            "so ",
            "bao hiem xa hoi",
            "chi cuc",
            "cuc ",
            "thanh tra",
            "thue ",
            "trung tam",
            "truong ",
            "vien ",
            "xa ",
            "phuong ",
            "thi tran",
            "huyen ",
            "quan ",
        ]
    )


def _resolve_task_unit_label(value):
    raw_value = (value or "").strip()
    if not raw_value:
        return ""
    resolved = resolve_category_display(
        raw_value,
        _task_assignment_unit_options(),
        fallback_label="",
    ).get("display_name", "")
    resolved = (resolved or "").strip()
    return resolved or raw_value


def _task_unit_identity(user):
    if not user:
        return {"unit_name": "Chưa có đơn vị", "unit_key": ""}

    stored_key = (getattr(user, "unit_key", "") or "").strip()
    unit_area_display = _resolve_task_unit_label(getattr(user, "unit_area_display", None) or "")
    unit_area = (getattr(user, "unit_area", None) or "").strip()
    resolved_unit_area = _resolve_task_unit_label(unit_area)
    fullname = (getattr(user, "fullname", None) or "").strip()
    username = (getattr(user, "username", None) or "").strip()

    unit_name = ""
    unit_name_source = ""
    for candidate in [unit_area_display, resolved_unit_area, unit_area]:
        if candidate and not _is_generic_task_unit_name(candidate):
            unit_name = candidate
            unit_name_source = "unit_area"
            break

    if not unit_name:
        for candidate in [fullname, username]:
            if candidate and _looks_like_task_unit_name(candidate):
                unit_name = candidate
                unit_name_source = "identity"
                break

    if not unit_name:
        unit_name = resolved_unit_area or unit_area_display or unit_area or fullname or username or "Chưa có đơn vị"
        unit_name_source = "fallback"

    key_candidates = []
    if unit_name_source == "identity":
        key_candidates.extend([unit_name, fullname, username])
        if stored_key and not _is_generic_task_unit_key(stored_key):
            key_candidates.append(stored_key)
    else:
        if stored_key and not _is_generic_task_unit_key(stored_key):
            key_candidates.append(stored_key)
        key_candidates.extend([unit_name, resolved_unit_area, unit_area_display, unit_area, fullname, username])

    unit_key = ""
    for candidate in key_candidates:
        key = extract_unit_key(candidate)
        if key and not _is_generic_task_unit_key(key):
            unit_key = key.strip()
            break

    if not unit_key:
        fallback_key = stored_key if stored_key and not _is_category_item_reference_local(stored_key) else ""
        unit_key = (fallback_key or extract_unit_key(unit_name) or unit_name.lower()).strip()

    return {
        "unit_name": unit_name,
        "unit_key": unit_key,
    }


def _task_assignee_unit_name(user):
    return _task_unit_identity(user).get("unit_name", "Chưa có đơn vị")


def _users_for_unit(unit_name):
    domain_options = _task_domain_options()
    canonical_unit = canonicalize_category_value(unit_name or "", domain_options, prefer_stable=True)
    resolved_unit = resolve_category_display(canonical_unit or unit_name, domain_options, fallback_label="").get("display_name", "")
    unit_key = extract_unit_key(resolved_unit or unit_name)
    query = User.query.filter(User.is_active.is_(True))
    if unit_key:
        users = query.filter(User.unit_key == unit_key).order_by(User.fullname.asc()).all()
        if users:
            return users

    if canonical_unit or resolved_unit:
        users = query.filter(User.unit_area.in_([value for value in {canonical_unit, resolved_unit} if value])).order_by(User.fullname.asc()).all()
        if users:
            return users

    users = query.order_by(User.fullname.asc()).all()
    return [user for user in users if is_unit_match(user.unit_area or user.fullname or user.username, resolved_unit or unit_name)]


def _is_commune_role(role_name):
    normalized = re.sub(r"\s+", " ", remove_accents(role_name or "")).strip().lower()
    return any(
        token in normalized
        for token in ["cap xa", "cong an cap xa", "xa thi tran", "phuong thi tran"]
    )


def _resolve_role_assignees(role_id):
    role = db.session.get(AppRole, role_id)
    users = (
        User.query.filter_by(role_id=role_id, is_active=True)
        .order_by(User.fullname.asc())
        .all()
    )

    return _dedupe_users(users)
