# -*- coding: utf-8 -*-
"""
Lược đồ biểu mẫu báo cáo (report schema) và phạm vi người nhận theo cấu hình.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

import json

from werkzeug.utils import secure_filename

from models import User
from utils import is_unit_match, remove_accents


TASK_REPORT_ALLOWED_FIELD_TYPES = {"number", "text", "textarea"}
TASK_REPORT_ALLOWED_TARGET_TYPES = {"all", "unit", "role", "user"}
CHILD_TASK_ALLOWED_REPORT_KINDS = {"narrative", "number"}
DEFAULT_TASK_REPORT_SCHEMA = {
    "enabled": False,
    "narrative": {
        "enabled": True,
        "label": "Báo cáo lời tổng hợp",
        "required": True,
        "placeholder": "Nêu rõ kết quả, tồn tại và kiến nghị nếu có",
        "target_type": "all",
        "target_unit_domains": [],
        "target_role_ids": [],
        "target_user_ids": [],
    },
    "attachment": {
        "enabled": False,
        "label": "Tệp minh chứng",
        "required": False,
        "target_type": "all",
        "target_unit_domains": [],
        "target_role_ids": [],
        "target_user_ids": [],
    },
    "fields": [],
}


def _report_checkbox_value(value):
    return str(value or "").strip().lower() in {"1", "true", "on", "yes"}


def _task_report_field_key(label, index, used_keys):
    raw_key = secure_filename(remove_accents(label or "").replace(" ", "_")).strip("_")
    key = raw_key or f"field_{index + 1}"
    while key in used_keys:
        key = f"{key}_{len(used_keys) + 1}"
    used_keys.add(key)
    return key


def _normalize_report_target_ids(values):
    normalized = []
    for value in values if isinstance(values, (list, tuple, set)) else []:
        text = str(value or "").strip()
        if not text.isdigit():
            continue
        numeric_value = int(text)
        if numeric_value not in normalized:
            normalized.append(numeric_value)
    return normalized


def _normalize_report_target_domains(values):
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    elif not isinstance(values, (list, tuple, set)):
        values = []
    normalized = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = remove_accents(text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text[:255])
    return normalized


def _normalize_report_target_config(raw_config, defaults=None):
    defaults = defaults or {}
    target_type = str(raw_config.get("target_type") or defaults.get("target_type") or "all").strip().lower()
    if target_type not in TASK_REPORT_ALLOWED_TARGET_TYPES:
        target_type = "all"
    return {
        "target_type": target_type,
        "target_unit_domains": _normalize_report_target_domains(
            raw_config.get("target_unit_domains", defaults.get("target_unit_domains", []))
        ),
        "target_role_ids": _normalize_report_target_ids(
            raw_config.get("target_role_ids", defaults.get("target_role_ids", []))
        ),
        "target_user_ids": _normalize_report_target_ids(
            raw_config.get("target_user_ids", defaults.get("target_user_ids", []))
        ),
    }


def _task_report_user_matches_units(user, target_unit_domains):
    if not user:
        return False
    target_domains = _normalize_report_target_domains(target_unit_domains)
    if not target_domains:
        return False
    user_unit_candidates = [
        getattr(user, "unit_area", None),
        getattr(user, "unit_area_display", None),
        getattr(user, "unit_key", None),
        ]
    return any(
        is_unit_match(candidate, target_domain)
        for candidate in user_unit_candidates if str(candidate or "").strip()
        for target_domain in target_domains
    )


def _task_report_item_visible_for_user(item_config, user):
    if not item_config or not user:
        return False

    target_type = str(item_config.get("target_type") or "all").strip().lower()
    if target_type == "unit":
        return _task_report_user_matches_units(user, item_config.get("target_unit_domains") or [])
    if target_type == "role":
        role_id = getattr(user, "role_id", None)
        return bool(role_id and role_id in (item_config.get("target_role_ids") or []))
    if target_type == "user":
        user_id = getattr(user, "id", None)
        return bool(user_id and user_id in (item_config.get("target_user_ids") or []))
    return True


def _normalize_child_task_report_meta(raw_meta, fields, attachment):
    raw_meta = raw_meta if isinstance(raw_meta, dict) else {}
    kind = str(raw_meta.get("kind") or "").strip().lower()
    if kind != "simple_child_task":
        return {}

    report_kind = str(raw_meta.get("report_kind") or "").strip().lower()
    if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
        report_kind = "number" if any(field.get("type") == "number" for field in fields) else "narrative"

    number_field_key = ""
    if report_kind == "number":
        number_field_key = next((field.get("key") or "" for field in fields if field.get("type") == "number"), "")

    return {
        "kind": "simple_child_task",
        "report_kind": report_kind,
        "attachment_required": bool(attachment.get("enabled") and attachment.get("required")),
        "number_field_key": number_field_key,
    }


def _normalize_task_report_schema(raw_schema):
    if not isinstance(raw_schema, dict):
        return None

    narrative_input = raw_schema.get("narrative") if isinstance(raw_schema.get("narrative"), dict) else {}
    attachment_input = raw_schema.get("attachment") if isinstance(raw_schema.get("attachment"), dict) else {}
    used_keys = set()
    fields = []
    for index, item in enumerate(raw_schema.get("fields") if isinstance(raw_schema.get("fields"), list) else []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        field_type = str(item.get("type") or "number").strip().lower()
        if field_type not in TASK_REPORT_ALLOWED_FIELD_TYPES:
            field_type = "number"
        fields.append(
            {
                "key": _task_report_field_key(item.get("key") or label, index, used_keys),
                "label": label[:255],
                "type": field_type,
                "required": _report_checkbox_value(item.get("required")),
                "placeholder": str(item.get("placeholder") or "").strip()[:255],
                "help_text": str(item.get("help_text") or "").strip()[:255],
                **_normalize_report_target_config(item),
            }
        )

    narrative = {
        "enabled": _report_checkbox_value(narrative_input.get("enabled", True)),
        "label": str(narrative_input.get("label") or DEFAULT_TASK_REPORT_SCHEMA["narrative"]["label"]).strip()[:255],
        "required": _report_checkbox_value(narrative_input.get("required", True)),
        "placeholder": str(
            narrative_input.get("placeholder") or DEFAULT_TASK_REPORT_SCHEMA["narrative"]["placeholder"]
        ).strip()[:255],
        **_normalize_report_target_config(narrative_input, DEFAULT_TASK_REPORT_SCHEMA["narrative"]),
    }
    attachment = {
        "enabled": _report_checkbox_value(attachment_input.get("enabled")),
        "label": str(attachment_input.get("label") or DEFAULT_TASK_REPORT_SCHEMA["attachment"]["label"]).strip()[:255],
        "required": _report_checkbox_value(attachment_input.get("required")),
        **_normalize_report_target_config(attachment_input, DEFAULT_TASK_REPORT_SCHEMA["attachment"]),
    }

    enabled = _report_checkbox_value(raw_schema.get("enabled")) or bool(fields) or narrative["enabled"] or attachment["enabled"]
    if not enabled:
        return None

    return {
        "version": 1,
        "enabled": True,
        "narrative": narrative,
        "attachment": attachment,
        "fields": fields,
        "meta": _normalize_child_task_report_meta(raw_schema.get("meta"), fields, attachment),
    }


def _load_task_report_schema(task):
    if not task:
        return None

    cached = getattr(task, "_task_report_schema_cache", None)
    if cached is not None:
        return cached

    raw_schema = getattr(task, "report_schema_json", None) or ""
    if not raw_schema:
        setattr(task, "_task_report_schema_cache", None)
        return None

    try:
        parsed = json.loads(raw_schema)
    except Exception:
        setattr(task, "_task_report_schema_cache", None)
        return None

    normalized = _normalize_task_report_schema(parsed)
    setattr(task, "_task_report_schema_cache", normalized)
    return normalized


def _task_report_schema_seed(task=None):
    schema = _load_task_report_schema(task)
    if schema:
        return schema
    return json.loads(json.dumps(DEFAULT_TASK_REPORT_SCHEMA))


def _parse_task_report_schema_from_request(form):
    if not _report_checkbox_value(form.get("report_schema_enabled")):
        return None

    raw_schema = (form.get("report_schema_json") or "").strip()
    if not raw_schema:
        return _normalize_task_report_schema(DEFAULT_TASK_REPORT_SCHEMA)

    try:
        parsed = json.loads(raw_schema)
    except Exception as exc:
        raise ValueError("Biểu mẫu báo cáo không hợp lệ.") from exc

    normalized = _normalize_task_report_schema(parsed)
    if not normalized:
        raise ValueError("Biểu mẫu báo cáo chưa có nội dung hợp lệ.")
    return normalized
