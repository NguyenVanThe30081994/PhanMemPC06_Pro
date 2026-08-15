# -*- coding: utf-8 -*-
"""
Cấu hình builder + đối sánh phản hồi Google Form của nhiệm vụ FORM.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi. Riêng `_task_google_form_manage_service`
chỉ được các endpoint v2 còn nằm trong routes/tasks.py gọi, nên mock
`routes.tasks.build_google_forms_service` trong test vẫn hiệu lực.
"""

from flask import current_app
from sqlalchemy.orm import joinedload

from google_forms import (
    GOOGLE_FORMS_MANAGE_SCOPES,
    builder_schema_to_task_form_fields,
    build_google_forms_service,
    normalize_google_form_builder_schema,
)
from models import TaskAssignment, TaskFormField, User, db
from services.task_form_fields import (
    _normalize_task_form_field_type,
    _task_form_fields,
    _task_form_fields_for_user,
)
from services.task_report_schema import _normalize_report_target_config
from utils import is_unit_match

import json


TASK_GOOGLE_FORM_MATCH_MODE_LABELS = {
    "unit": "Đối sánh theo đơn vị báo cáo",
    "respondent_email": "Đối sánh theo email người trả lời",
}


def _json_loads_safe(raw_value, default):
    try:
        parsed = json.loads(raw_value or "")
    except Exception:
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _json_dump(raw_value):
    return json.dumps(raw_value, ensure_ascii=False)


def _normalize_google_form_match_mode(value):
    normalized = str(value or "").strip().lower()
    if normalized in TASK_GOOGLE_FORM_MATCH_MODE_LABELS:
        return normalized
    return "unit"


def _normalize_google_form_builder_schema_with_targets(raw_schema, fallback_title="", fallback_description=""):
    normalized = normalize_google_form_builder_schema(
        raw_schema,
        fallback_title=fallback_title,
        fallback_description=fallback_description,
    )
    raw_items = raw_schema.get("items") if isinstance(raw_schema, dict) and isinstance(raw_schema.get("items"), list) else []
    target_by_item_id = {}
    target_by_label = {}
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        target_config = _normalize_report_target_config(raw_item)
        item_id = str(raw_item.get("pc06_item_id") or f"index:{index}").strip()
        label_key = str(raw_item.get("title") or "").strip().lower()
        target_by_item_id[item_id] = target_config
        if label_key and label_key not in target_by_label:
            target_by_label[label_key] = target_config

    for index, item in enumerate(normalized.get("items") or []):
        item_id = str(item.get("pc06_item_id") or f"index:{index}").strip()
        label_key = str(item.get("title") or "").strip().lower()
        target_config = target_by_item_id.get(item_id) or target_by_label.get(label_key) or {}
        item.update(target_config)
    return normalized


def _parse_google_form_builder_schema(raw_builder_json, fallback_title="", fallback_description=""):
    text = str(raw_builder_json or "").strip()
    if not text:
        raise ValueError("Cần cấu hình schema builder cho Google Form.")
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise ValueError("Schema builder Google Form không phải JSON hợp lệ.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Schema builder Google Form phải là một JSON object.")
    try:
        return _normalize_google_form_builder_schema_with_targets(
            parsed,
            fallback_title=fallback_title,
            fallback_description=fallback_description,
        )
    except Exception as exc:
        raise ValueError(str(exc) or "Schema builder Google Form không hợp lệ.") from exc


def _hydrate_google_form_fields(builder_schema):
    normalized = _normalize_google_form_builder_schema_with_targets(builder_schema, fallback_title="Biểu mẫu")
    target_by_item_id = {}
    target_by_label = {}
    for index, item in enumerate(normalized.get("items") or []):
        item_id = str(item.get("pc06_item_id") or f"index:{index}").strip()
        label_key = str(item.get("title") or "").strip().lower()
        target_config = _normalize_report_target_config(item)
        target_by_item_id[item_id] = target_config
        if label_key and label_key not in target_by_label:
            target_by_label[label_key] = target_config

    field_defs = builder_schema_to_task_form_fields(normalized)
    for field_def in field_defs:
        options_payload = _json_loads_safe(field_def.get("field_options_json"), {})
        item_id = str(options_payload.get("pc06_item_id") or "").strip()
        label_key = str(field_def.get("field_label") or "").strip().lower()
        target_config = target_by_item_id.get(item_id) or target_by_label.get(label_key) or {}
        if target_config.get("target_type") != "all":
            options_payload["target_type"] = target_config.get("target_type")
        if target_config.get("target_unit_domains"):
            options_payload["target_unit_domains"] = target_config.get("target_unit_domains")
        if target_config.get("target_role_ids"):
            options_payload["target_role_ids"] = target_config.get("target_role_ids")
        if target_config.get("target_user_ids"):
            options_payload["target_user_ids"] = target_config.get("target_user_ids")
        field_def["field_options_json"] = _json_dump(options_payload) if options_payload else None
    return field_defs


def _task_google_form_runtime(task):
    return _json_loads_safe(getattr(task, "google_form_runtime_json", None), {})


def _task_google_form_sync_state(task):
    return _json_loads_safe(getattr(task, "google_form_sync_state_json", None), {})


def _task_google_form_builder(task):
    return _json_loads_safe(getattr(task, "google_form_builder_json", None), {})


def _task_google_form_runtime_payload(task, form_payload=None, base_runtime=None):
    runtime = dict(base_runtime or {})
    if not isinstance(form_payload, dict):
        return runtime

    info = form_payload.get("info") if isinstance(form_payload.get("info"), dict) else {}
    form_id = str(form_payload.get("formId") or runtime.get("form_id") or getattr(task, "google_form_id", "") or "").strip()
    form_url = str(
        form_payload.get("responderUri")
        or runtime.get("form_url")
        or getattr(task, "google_form_url", "")
        or (f"https://docs.google.com/forms/d/{form_id}/viewform" if form_id else "")
    ).strip()
    runtime.update(
        {
            "form_id": form_id,
            "form_url": form_url,
            "edit_url": str(runtime.get("edit_url") or (f"https://docs.google.com/forms/d/{form_id}/edit" if form_id else "")).strip(),
            "revision_id": str(form_payload.get("revisionId") or runtime.get("revision_id") or "").strip(),
            "publish_settings": form_payload.get("publishSettings") or runtime.get("publish_settings") or {},
            "title": str(info.get("title") or runtime.get("title") or "").strip(),
            "description": str(info.get("description") or runtime.get("description") or "").strip(),
        }
    )
    return runtime


def _task_google_form_target_lookup(task=None, builder_schema=None):
    by_question_id = {}
    by_label = {}

    if task:
        for field in _task_form_fields(task):
            options_payload = _json_loads_safe(getattr(field, "field_options_json", None), {})
            target_config = _normalize_report_target_config(options_payload)
            question_id = str(options_payload.get("question_id") or options_payload.get("pc06_item_id") or "").strip()
            label_key = str(getattr(field, "field_label", "") or "").strip().lower()
            if question_id and question_id not in by_question_id:
                by_question_id[question_id] = target_config
            if label_key and label_key not in by_label:
                by_label[label_key] = target_config

    if isinstance(builder_schema, dict):
        for item in builder_schema.get("items") or []:
            if not isinstance(item, dict):
                continue
            target_config = _normalize_report_target_config(item)
            question_id = str(item.get("pc06_item_id") or "").strip()
            label_key = str(item.get("title") or "").strip().lower()
            if question_id and question_id not in by_question_id:
                by_question_id[question_id] = target_config
            if label_key and label_key not in by_label:
                by_label[label_key] = target_config

    return by_question_id, by_label


def _merge_google_form_field_targets(field_defs, task=None, builder_schema=None):
    by_question_id, by_label = _task_google_form_target_lookup(task=task, builder_schema=builder_schema)
    merged_defs = []
    for field_def in field_defs or []:
        options_payload = _json_loads_safe(field_def.get("field_options_json"), {})
        question_id = str(options_payload.get("question_id") or options_payload.get("pc06_item_id") or "").strip()
        label_key = str(field_def.get("field_label") or "").strip().lower()
        target_config = by_question_id.get(question_id) or by_label.get(label_key) or {}
        if target_config.get("target_type") != "all":
            options_payload["target_type"] = target_config.get("target_type")
        if target_config.get("target_unit_domains"):
            options_payload["target_unit_domains"] = target_config.get("target_unit_domains")
        if target_config.get("target_role_ids"):
            options_payload["target_role_ids"] = target_config.get("target_role_ids")
        if target_config.get("target_user_ids"):
            options_payload["target_user_ids"] = target_config.get("target_user_ids")
        updated_field = dict(field_def)
        updated_field["field_options_json"] = _json_dump(options_payload) if options_payload else None
        merged_defs.append(updated_field)
    return merged_defs


def _replace_task_form_fields(task, field_defs):
    TaskFormField.query.filter_by(task_id=task.id).delete()
    for field_def in field_defs or []:
        db.session.add(TaskFormField(task_id=task.id, **_task_form_field_db_kwargs(field_def)))


def _task_form_field_db_kwargs(field_def):
    return {
        "field_key": str(field_def.get("field_key") or "").strip()[:100],
        "field_label": str(field_def.get("field_label") or "").strip()[:255],
        "field_type": _normalize_task_form_field_type(field_def.get("field_type") or "text"),
        "field_options_json": field_def.get("field_options_json"),
        "sort_order": int(field_def.get("sort_order") or 0),
        "is_required": bool(field_def.get("is_required")),
    }


def _task_google_form_manage_service():
    return build_google_forms_service(current_app.config, scopes=GOOGLE_FORMS_MANAGE_SCOPES)


def _task_google_form_match_label(task):
    return TASK_GOOGLE_FORM_MATCH_MODE_LABELS.get(
        _normalize_google_form_match_mode(getattr(task, "google_form_match_mode", "")),
        TASK_GOOGLE_FORM_MATCH_MODE_LABELS["unit"],
    )


def _apply_task_google_form_view_state(task):
    if not task:
        return

    runtime = _task_google_form_runtime(task)
    sync_state = _task_google_form_sync_state(task)
    builder = _task_google_form_builder(task)

    if getattr(task, "google_form_id", None) or getattr(task, "google_form_url", None):
        runtime.setdefault("form_id", getattr(task, "google_form_id", None) or "")
        runtime.setdefault("form_url", getattr(task, "google_form_url", None) or "")
        if runtime.get("form_id") and not runtime.get("edit_url"):
            runtime["edit_url"] = f"https://docs.google.com/forms/d/{runtime['form_id']}/edit"
    if runtime.get("title") and not sync_state.get("form_title"):
        sync_state["form_title"] = runtime.get("title")

    setattr(task, "google_form_runtime", runtime)
    setattr(task, "google_form_sync_state", sync_state)
    setattr(task, "google_form_builder", builder)
    setattr(task, "google_form_builder_managed", bool(builder))
    setattr(task, "google_form_match_mode_label", _task_google_form_match_label(task))


def _task_google_form_response_match_value(task, response_row):
    mode = _normalize_google_form_match_mode(getattr(task, "google_form_match_mode", "unit"))
    if mode == "respondent_email":
        return str(response_row.get("respondent_email") or "").strip()

    match_field = str(getattr(task, "google_form_match_field", "") or "").strip()
    payload_by_label = response_row.get("payload_by_label") if isinstance(response_row.get("payload_by_label"), dict) else {}
    if match_field:
        return str(payload_by_label.get(match_field) or "").strip()
    for value in payload_by_label.values():
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _google_form_assignment_matches_response(task, assignment, response_row):
    user = getattr(assignment, "user", None)
    if not user:
        return False

    match_value = _task_google_form_response_match_value(task, response_row)
    if not match_value:
        return False

    mode = _normalize_google_form_match_mode(getattr(task, "google_form_match_mode", "unit"))
    if mode == "respondent_email":
        user_candidates = {
            str(getattr(user, "username", "") or "").strip().lower(),
            str(getattr(user, "fullname", "") or "").strip().lower(),
        }
        return match_value.strip().lower() in user_candidates

    return any(
        is_unit_match(candidate, match_value)
        for candidate in [
            getattr(user, "unit_area", None),
            getattr(user, "unit_key", None),
            getattr(user, "fullname", None),
        ]
        if str(candidate or "").strip()
    )


def _match_google_form_response_to_assignment(task, response_row):
    assignments = (
        TaskAssignment.query.options(joinedload(TaskAssignment.user))
        .filter_by(task_id=task.id)
        .order_by(TaskAssignment.id.asc())
        .all()
    )
    for assignment in assignments:
        if _google_form_assignment_matches_response(task, assignment, response_row):
            return assignment
    return None


def _filter_google_form_response_for_assignment(task, assignment, response_row):
    raw_payload = response_row.get("payload") if isinstance(response_row.get("payload"), dict) else {}
    raw_payload_by_label = response_row.get("payload_by_label") if isinstance(response_row.get("payload_by_label"), dict) else {}
    user = getattr(assignment, "user", None)
    if not user and getattr(assignment, "user_id", None):
        user = db.session.get(User, assignment.user_id)
    if not user:
        return {
            "payload": dict(raw_payload),
            "payload_by_label": dict(raw_payload_by_label),
            "ignored_keys": [],
            "visible_field_count": 0,
        }

    visible_fields = _task_form_fields_for_user(task, user)
    visible_keys = {str(getattr(field, "field_key", "") or "").strip() for field in visible_fields if str(getattr(field, "field_key", "") or "").strip()}
    visible_labels = {str(getattr(field, "field_label", "") or "").strip() for field in visible_fields if str(getattr(field, "field_label", "") or "").strip()}
    filtered_payload = {
        key: value
        for key, value in raw_payload.items()
        if str(key or "").strip() in visible_keys
    }
    filtered_payload_by_label = {}
    for label, value in raw_payload_by_label.items():
        normalized_label = str(label or "").strip()
        root_label = normalized_label.split(" / ", 1)[0].strip()
        if root_label in visible_labels:
            filtered_payload_by_label[normalized_label] = value

    ignored_keys = [
        str(key or "").strip()
        for key in raw_payload.keys()
        if str(key or "").strip() and str(key or "").strip() not in filtered_payload
    ]
    return {
        "payload": filtered_payload,
        "payload_by_label": filtered_payload_by_label,
        "ignored_keys": ignored_keys,
        "visible_field_count": len(visible_keys),
    }
