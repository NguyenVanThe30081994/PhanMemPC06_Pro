# -*- coding: utf-8 -*-
import json


def outline_group_identity(assignments, unit_name_resolver, fallback_index=0):
    if not assignments:
        return {
            "key": f"ungrouped:{fallback_index}",
            "label": "Chưa phân công",
            "mode": "user",
            "mode_label": "Chưa có người nhận",
            "members_label": "",
        }

    assignee_type = str(getattr(assignments[0], "assignee_type", "") or "user").strip().lower()
    if assignee_type == "unit":
        unit_names = sorted({
            unit_name_resolver(getattr(assignment, "user", None)) or "Chưa có đơn vị"
            for assignment in assignments
        })
        label = unit_names[0] if len(unit_names) == 1 else f"{unit_names[0]} +{len(unit_names) - 1} đơn vị"
        return {
            "key": "unit:" + "|".join(unit_names),
            "label": label,
            "mode": "unit",
            "mode_label": "Giao theo đơn vị",
            "members_label": ", ".join(unit_names),
        }

    if assignee_type == "role":
        role_names = sorted({
            (
                getattr(getattr(assignment, "role", None), "name", None)
                or getattr(getattr(getattr(assignment, "user", None), "role", None), "name", None)
                or "Chưa phân vai trò"
            )
            for assignment in assignments
        })
        label = role_names[0] if len(role_names) == 1 else f"{role_names[0]} +{len(role_names) - 1} vai trò"
        return {
            "key": "role:" + "|".join(role_names),
            "label": label,
            "mode": "role",
            "mode_label": "Giao theo vai trò",
            "members_label": ", ".join(role_names),
        }

    user_names = sorted({
        (
            getattr(getattr(assignment, "user", None), "fullname", None)
            or getattr(getattr(assignment, "user", None), "username", None)
            or "Không xác định"
        )
        for assignment in assignments
    })
    label = user_names[0] if len(user_names) == 1 else f"{user_names[0]} +{len(user_names) - 1} cá nhân"
    return {
        "key": "user:" + "|".join(str(getattr(assignment, "user_id", 0) or 0) for assignment in assignments),
        "label": label,
        "mode": "user",
        "mode_label": "Giao theo cá nhân",
        "members_label": ", ".join(user_names),
    }


def build_outline_group_rows(rows, identity_builder):
    group_map = {}
    for index, row in enumerate(rows or [], start=1):
        identity = identity_builder(row["assignments"], fallback_index=index)
        group = group_map.setdefault(
            identity["key"],
            {
                "key": identity["key"],
                "label": identity["label"],
                "mode": identity["mode"],
                "mode_label": identity["mode_label"],
                "members_label": identity["members_label"],
                "rows": [],
                "total_items": 0,
                "fully_submitted_items": 0,
                "my_items": 0,
                "total_assignments": 0,
            },
        )
        group["rows"].append(row)
        group["total_items"] += 1
        group["total_assignments"] += row["total_count"]
        if row["total_count"] and row["submitted_count"] >= row["total_count"]:
            group["fully_submitted_items"] += 1
        if row["my_assignment"]:
            group["my_items"] += 1

    groups = sorted(group_map.values(), key=lambda item: (item["mode"], item["label"].lower()))
    for group in groups:
        group["rows"].sort(key=lambda item: (getattr(item["item"], "sort_order", 0), getattr(item["item"], "id", 0)))
    return groups


def build_file_task_rows(assignments, current_uid, latest_submission_getter):
    rows = []
    for assignment in assignments or []:
        rows.append(
            {
                "assignment": assignment,
                "submission": latest_submission_getter(assignment),
                "is_current_user": getattr(assignment, "user_id", None) == current_uid,
            }
        )
    return rows


def normalize_task_form_field_type(value, allowed_types):
    normalized = str(value or "").strip().lower()
    if normalized in (allowed_types or set()):
        return normalized
    return "text"


def task_form_value_is_empty(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def _json_dict(raw_value):
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def form_field_options(field):
    return _json_dict(getattr(field, "field_options_json", None) or "")


def task_form_submission_payload(submission):
    return _json_dict(getattr(submission, "payload_json", None) or "")


def build_form_task_rows(assignments, fields, current_uid, latest_submission_getter, payload_loader):
    rows = []
    for assignment in assignments or []:
        submission = latest_submission_getter(assignment)
        rows.append(
            {
                "assignment": assignment,
                "submission": submission,
                "payload": payload_loader(submission) if submission else {},
                "is_current_user": getattr(assignment, "user_id", None) == current_uid,
            }
        )
    return list(fields or []), rows


def task_form_field_views(fields, normalize_type_fn, field_options_loader):
    views = []
    for field in fields or []:
        options = field_options_loader(field)
        choices = options.get("choices", [])
        columns = options.get("columns", [])
        views.append(
            {
                "id": field.id,
                "field_key": field.field_key,
                "field_label": field.field_label,
                "field_type": normalize_type_fn(field.field_type),
                "is_required": bool(field.is_required),
                "choices": choices if isinstance(choices, list) else [],
                "columns": columns if isinstance(columns, list) else [],
                "target_type": str(options.get("target_type") or "all").strip().lower() or "all",
                "target_unit_domains": list(options.get("target_unit_domains") or []),
                "target_role_ids": list(options.get("target_role_ids") or []),
                "target_user_ids": list(options.get("target_user_ids") or []),
            }
        )
    return views
