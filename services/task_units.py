# -*- coding: utf-8 -*-
"""
Nhận diện / đối sánh đơn vị (unit matching) và quy đổi người nhận theo đơn vị/vai trò.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

import re

from flask import g, has_request_context

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

    unit_obj = getattr(user, "unit", None)
    if not unit_obj and getattr(user, "unit_id", None) and hasattr(user, "__table__"):
        unit_obj = db.session.get(Unit, user.unit_id)
    if unit_obj and getattr(unit_obj, "name", None):
        unit_name = str(unit_obj.name).strip()
        raw_code = str(getattr(unit_obj, "code", "") or "").strip()
        unit_key = (extract_unit_key(raw_code or unit_name) or extract_unit_key(unit_name) or unit_name.lower()).strip()
        return {
            "unit_name": unit_name,
            "unit_key": unit_key,
        }

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
    if not user:
        return "Chưa có đơn vị"
    cache_key = getattr(user, "id", None) or ("object", id(user))
    if has_request_context():
        cache = getattr(g, "_task_assignee_unit_name_cache", None)
        if cache is None:
            cache = {}
            g._task_assignee_unit_name_cache = cache
        if cache_key in cache:
            return cache[cache_key]
    unit_name = _task_unit_identity(user).get("unit_name", "Chưa có đơn vị")
    if has_request_context():
        g._task_assignee_unit_name_cache[cache_key] = unit_name
    return unit_name


def _resolve_unit_record(unit_ref):
    raw = str(unit_ref or "").strip()
    if not raw:
        return None
    from models import Unit

    unit = Unit.query.filter(
        Unit.is_active.is_(True),
        db.or_(Unit.code == raw, Unit.name == raw),
    ).first()
    if unit:
        return unit

    unit_options = _task_assignment_unit_options()
    canonical = canonicalize_category_value(raw, unit_options, prefer_stable=True)
    resolved = resolve_category_display(canonical or raw, unit_options, fallback_label="").get("display_name", "")
    candidates = {value for value in {raw, canonical, resolved} if value}
    if candidates:
        unit = Unit.query.filter(
            Unit.is_active.is_(True),
            db.or_(Unit.code.in_(candidates), Unit.name.in_(candidates)),
        ).first()
        if unit:
            return unit

    target_key = extract_unit_key(resolved or raw)
    if target_key:
        for candidate_unit in Unit.query.filter(Unit.is_active.is_(True)).all():
            if (
                extract_unit_key(candidate_unit.code or "") == target_key
                or extract_unit_key(candidate_unit.name or "") == target_key
            ):
                return candidate_unit
    return None


def _users_for_unit(unit_name):
    raw_unit = str(unit_name or "").strip()
    if not raw_unit:
        return []

    unit_options = _task_assignment_unit_options()
    canonical_unit = canonicalize_category_value(raw_unit, unit_options, prefer_stable=True)
    resolved_unit = resolve_category_display(canonical_unit or raw_unit, unit_options, fallback_label="").get("display_name", "")
    target_unit = _resolve_unit_record(raw_unit)
    unit_key = extract_unit_key(
        (target_unit.name if target_unit else "") or resolved_unit or raw_unit
    )

    query = User.query.filter(User.is_active.is_(True))
    direct_conditions = []
    if target_unit:
        direct_conditions.append(User.unit_id == target_unit.id)
    text_candidates = {
        value for value in {
            raw_unit,
            canonical_unit,
            resolved_unit,
            getattr(target_unit, "code", "") or "",
            getattr(target_unit, "name", "") or "",
        } if value
    }
    if unit_key:
        text_candidates.add(unit_key)
    if text_candidates:
        direct_conditions.append(User.unit_key.in_(text_candidates))
        direct_conditions.append(User.unit_area.in_(text_candidates))

    if direct_conditions:
        users = query.filter(db.or_(*direct_conditions)).order_by(User.fullname.asc()).all()
        if users:
            return _dedupe_users(users)

    # Fallback: đối sánh chuẩn hóa theo unit_key không dấu gạch dưới hoặc tên đơn vị đã giải mã
    active_users = query.order_by(User.fullname.asc()).all()
    target_label = getattr(target_unit, "name", "") or resolved_unit or raw_unit
    matched = []
    for user in active_users:
        identity = _task_unit_identity(user)
        user_key = extract_unit_key(user.unit_key or identity.get("unit_name", ""))
        if unit_key and user_key and user_key == unit_key:
            matched.append(user)
            continue
        user_label = identity.get("unit_name") or user.unit_area or user.fullname or user.username
        if is_unit_match(user_label, target_label):
            matched.append(user)
    return _dedupe_users(matched)


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
