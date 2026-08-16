# -*- coding: utf-8 -*-
"""
Helper nháp nhập việc (task import draft): nhãn trạng thái, tiện ích JSON,
cấu hình lựa chọn trường biểu mẫu.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

import json

from werkzeug.utils import secure_filename

from services.task_report_schema import _normalize_report_target_config
from utils import remove_accents

TASK_IMPORT_SOURCE_TYPES = {"docx_outline", "docx_report_outline", "xlsx_form", "google_form_remote", "blueprint_json"}


def _task_import_status_label(status):
    normalized = str(status or "").strip().lower()
    if normalized == "published":
        return "Đã phát hành"
    if normalized == "failed":
        return "Lỗi phát hành"
    return "Đang soạn"


def _task_import_source_label(source_type):
    normalized = str(source_type or "").strip().lower()
    labels = {
        "docx_outline": "Word/TXT -> đề cương công tác",
        "docx_report_outline": "Word/TXT -> đề cương báo cáo theo mục",
        "xlsx_form": "Excel -> biểu mẫu số liệu",
        "google_form_remote": "Google Form -> biểu mẫu",
        "blueprint_json": "Blueprint JSON nâng cao",
    }
    return labels.get(normalized, normalized or "Không xác định")


def _json_loads_safe(raw_value, default):
    try:
        parsed = json.loads(raw_value or "")
    except Exception:
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _json_dump(raw_value):
    return json.dumps(raw_value, ensure_ascii=False)


def _draft_field_options_text(field_options_json):
    payload = _json_loads_safe(field_options_json, {})
    if payload.get("choices"):
        return "\n".join(str(item).strip() for item in payload.get("choices", []) if str(item).strip())
    if payload.get("columns"):
        return ", ".join(str(item).strip() for item in payload.get("columns", []) if str(item).strip())
    return ""


def _draft_field_options_json(field_type, raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return None
    payload = {}
    if field_type in {"radio", "checkbox"}:
        payload["choices"] = [item.strip() for item in text.splitlines() if item.strip()]
    elif field_type == "table":
        payload["columns"] = [item.strip() for item in text.split(",") if item.strip()]
    return _json_dump(payload) if payload else None


def _task_import_form_field_target_config(raw_field):
    option_payload = _json_loads_safe(raw_field.get("field_options_json"), {})
    return _normalize_report_target_config(
        {
            "target_type": raw_field.get("target_type", option_payload.get("target_type", "all")),
            "target_unit_domains": raw_field.get("target_unit_domains", option_payload.get("target_unit_domains", [])),
            "target_role_ids": raw_field.get("target_role_ids", option_payload.get("target_role_ids", [])),
            "target_user_ids": raw_field.get("target_user_ids", option_payload.get("target_user_ids", [])),
        }
    )


def _task_import_form_field_options_json(field_type, raw_value, target_config=None):
    payload = _json_loads_safe(_draft_field_options_json(field_type, raw_value), {})
    normalized_target = _normalize_report_target_config(target_config or {})
    if normalized_target.get("target_type") != "all":
        payload["target_type"] = normalized_target.get("target_type")
    if normalized_target.get("target_unit_domains"):
        payload["target_unit_domains"] = normalized_target.get("target_unit_domains")
    if normalized_target.get("target_role_ids"):
        payload["target_role_ids"] = normalized_target.get("target_role_ids")
    if normalized_target.get("target_user_ids"):
        payload["target_user_ids"] = normalized_target.get("target_user_ids")
    return _json_dump(payload) if payload else None


def _task_import_field_key(label, index, used_keys, fallback_prefix):
    base = secure_filename(remove_accents(label).replace(" ", "_")) or f"{fallback_prefix}_{index + 1}"
    candidate = base[:100]
    if candidate not in used_keys:
        used_keys.add(candidate)
        return candidate
    suffix = 2
    while True:
        deduped = f"{candidate[:95]}_{suffix}"
        if deduped not in used_keys:
            used_keys.add(deduped)
            return deduped
        suffix += 1
