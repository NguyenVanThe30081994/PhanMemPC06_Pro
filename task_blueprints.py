# -*- coding: utf-8 -*-
import json
import re
import unicodedata


WORKFLOW_BLUEPRINT_ALLOWED_SOURCE_KINDS = {
    "directive",
    "sectioned_report",
    "google_form",
    "excel_template",
    "report_template",
    "custom",
}
WORKFLOW_BLUEPRINT_ALLOWED_COLLECTION_MODES = {"outline", "form", "file"}
WORKFLOW_BLUEPRINT_ALLOWED_CADENCES = {
    "once",
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "semiannual",
    "yearly",
    "ad_hoc",
}
WORKFLOW_BLUEPRINT_ALLOWED_REPORT_KINDS = {"narrative", "number"}
WORKFLOW_BLUEPRINT_ALLOWED_FORM_FIELD_TYPES = {
    "text",
    "number",
    "textarea",
    "radio",
    "checkbox",
    "table",
}
WORKFLOW_BLUEPRINT_ALLOWED_REPORT_FIELD_TYPES = {"text", "number", "textarea"}
WORKFLOW_BLUEPRINT_ALLOWED_TARGET_TYPES = {"all", "unit", "role", "user"}

DEFAULT_BLUEPRINT_TITLE = "Điều hành và thu báo cáo"
WORKFLOW_BLUEPRINT_EXAMPLES = [
    {
        "key": "weekly_outline",
        "label": "Công tác tuần",
        "description": "Tách thành các đầu mục giao việc và báo cáo kết quả hằng tuần.",
        "payload": {
            "title": "Công tác tuần Đội 1",
            "source_kind": "directive",
            "cadence": "weekly",
            "collection_mode": "outline",
            "summary": "Các đầu mục trọng tâm cần triển khai và báo cáo kết quả trong tuần.",
            "items": [
                {
                    "title": "Đôn đốc xử lý hồ sơ cư trú",
                    "report_kind": "narrative",
                    "attachment_required": False,
                },
                {
                    "title": "Tổng hợp số lượng hồ sơ quá hạn",
                    "report_kind": "number",
                    "attachment_required": True,
                },
            ],
        },
    },
    {
        "key": "google_form",
        "label": "Thu thập biểu mẫu",
        "description": "Thu số liệu nhanh từ đơn vị theo cấu trúc gần với Google Form.",
        "payload": {
            "title": "Thu thập tiến độ triển khai",
            "source_kind": "google_form",
            "cadence": "monthly",
            "collection_mode": "form",
            "form_fields": [
                {"label": "Đơn vị báo cáo", "type": "text", "required": True},
                {"label": "Tổng số hồ sơ", "type": "number", "required": True},
                {"label": "Khó khăn, vướng mắc", "type": "textarea", "required": False},
            ],
        },
    },
    {
        "key": "monthly_file",
        "label": "Báo cáo tổng hợp",
        "description": "Báo cáo lời có cấu trúc, kèm chỉ tiêu và phụ lục minh chứng.",
        "payload": {
            "title": "Báo cáo tổng hợp tháng",
            "source_kind": "sectioned_report",
            "cadence": "monthly",
            "collection_mode": "file",
            "report_schema": {
                "enabled": True,
                "narrative": {
                    "enabled": True,
                    "required": True,
                    "label": "Nội dung tổng hợp",
                },
                "attachment": {
                    "enabled": True,
                    "required": False,
                    "label": "Phụ lục minh chứng",
                },
                "fields": [
                    {
                        "label": "Số văn bản đã tham mưu",
                        "type": "number",
                        "required": False,
                    },
                    {
                        "label": "Nhận xét chung",
                        "type": "textarea",
                        "required": False,
                    },
                ],
            },
        },
    },
]


def _normalize_text(value, default="", limit=None):
    text = str(value or default).strip()
    if limit is not None:
        return text[:limit]
    return text


def _normalize_slug(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _normalize_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "co", "có"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "khong", "không"}:
        return False
    return bool(default)


def _normalize_choice(value, allowed, default=""):
    normalized = str(value or "").strip().lower()
    if normalized in allowed:
        return normalized
    return default


def _unique_key(label, index, used_keys, fallback_prefix):
    base = _normalize_slug(label) or f"{fallback_prefix}_{index + 1}"
    key = base[:100]
    if key not in used_keys:
        used_keys.add(key)
        return key
    suffix = 2
    while True:
        candidate = f"{base[:95]}_{suffix}"
        if candidate not in used_keys:
            used_keys.add(candidate)
            return candidate
        suffix += 1


def _normalize_choice_list(raw_value):
    if isinstance(raw_value, dict):
        if isinstance(raw_value.get("choices"), list):
            return [str(item).strip() for item in raw_value.get("choices", []) if str(item).strip()]
        if isinstance(raw_value.get("columns"), list):
            return [str(item).strip() for item in raw_value.get("columns", []) if str(item).strip()]
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        return [item.strip() for item in raw_value.splitlines() if item.strip()]
    return []


def _normalize_target_type(value):
    return _normalize_choice(value, WORKFLOW_BLUEPRINT_ALLOWED_TARGET_TYPES, default="all")


def _normalize_target_domains(raw_value):
    if isinstance(raw_value, str):
        values = [item.strip() for item in raw_value.split(",") if item.strip()]
    elif isinstance(raw_value, list):
        values = [str(item).strip() for item in raw_value if str(item).strip()]
    else:
        values = []
    return list(dict.fromkeys(values))


def _normalize_target_ids(raw_value):
    values = []
    if isinstance(raw_value, str):
        candidates = [item.strip() for item in raw_value.split(",") if item.strip()]
    elif isinstance(raw_value, list):
        candidates = raw_value
    else:
        candidates = []
    for candidate in candidates:
        text = str(candidate).strip()
        if text.isdigit():
            values.append(int(text))
    return sorted(set(values))


def _normalize_outline_items(raw_items):
    items = []
    for index, raw_item in enumerate(raw_items if isinstance(raw_items, list) else []):
        if not isinstance(raw_item, dict):
            continue
        title = _normalize_text(raw_item.get("title"), limit=255)
        if not title:
            continue
        report_kind = _normalize_choice(
            raw_item.get("report_kind") or raw_item.get("response_kind"),
            WORKFLOW_BLUEPRINT_ALLOWED_REPORT_KINDS,
            default="narrative",
        )
        items.append(
            {
                "title": title,
                "description": _normalize_text(raw_item.get("description"), limit=1000),
                "guide_text": _normalize_text(raw_item.get("guide_text"), limit=2000),
                "report_kind": report_kind,
                "attachment_required": _normalize_bool(raw_item.get("attachment_required")),
                "is_required": _normalize_bool(raw_item.get("is_required"), default=True),
                "sort_order": len(items),
                "source_ref": _normalize_text(raw_item.get("source_ref"), limit=255),
            }
        )
    return items


def _normalize_form_fields(raw_fields):
    fields = []
    used_keys = set()
    for index, raw_field in enumerate(raw_fields if isinstance(raw_fields, list) else []):
        if not isinstance(raw_field, dict):
            continue
        label = _normalize_text(raw_field.get("label") or raw_field.get("title"), limit=255)
        if not label:
            continue
        field_type = _normalize_choice(
            raw_field.get("type"),
            WORKFLOW_BLUEPRINT_ALLOWED_FORM_FIELD_TYPES,
            default="text",
        )
        option_payload = {}
        if field_type in {"radio", "checkbox"}:
            choices = _normalize_choice_list(raw_field.get("options") or raw_field.get("choices"))
            if choices:
                option_payload["choices"] = choices
        elif field_type == "table":
            columns = _normalize_choice_list(raw_field.get("options") or raw_field.get("columns"))
            if columns:
                option_payload["columns"] = columns
        target_type = _normalize_target_type(raw_field.get("target_type"))
        target_unit_domains = _normalize_target_domains(raw_field.get("target_unit_domains"))
        target_role_ids = _normalize_target_ids(raw_field.get("target_role_ids"))
        target_user_ids = _normalize_target_ids(raw_field.get("target_user_ids"))
        if target_type != "all":
            option_payload["target_type"] = target_type
        if target_unit_domains:
            option_payload["target_unit_domains"] = target_unit_domains
        if target_role_ids:
            option_payload["target_role_ids"] = target_role_ids
        if target_user_ids:
            option_payload["target_user_ids"] = target_user_ids
        fields.append(
            {
                "field_key": _unique_key(label, index, used_keys, "field"),
                "field_label": label,
                "field_type": field_type,
                "field_options_json": json.dumps(option_payload, ensure_ascii=False) if option_payload else None,
                "sort_order": len(fields),
                "is_required": _normalize_bool(raw_field.get("required")),
                "target_type": target_type,
                "target_unit_domains": target_unit_domains,
                "target_role_ids": target_role_ids,
                "target_user_ids": target_user_ids,
            }
        )
    return fields


def _normalize_report_schema(raw_schema):
    raw_schema = raw_schema if isinstance(raw_schema, dict) else {}
    used_keys = set()
    fields = []
    for index, raw_field in enumerate(raw_schema.get("fields") if isinstance(raw_schema.get("fields"), list) else []):
        if not isinstance(raw_field, dict):
            continue
        label = _normalize_text(raw_field.get("label"), limit=255)
        if not label:
            continue
        field_type = _normalize_choice(
            raw_field.get("type"),
            WORKFLOW_BLUEPRINT_ALLOWED_REPORT_FIELD_TYPES,
            default="text",
        )
        fields.append(
            {
                "key": _unique_key(raw_field.get("key") or label, index, used_keys, "value"),
                "label": label,
                "type": field_type,
                "required": _normalize_bool(raw_field.get("required")),
                "placeholder": _normalize_text(raw_field.get("placeholder"), limit=255),
                "help_text": _normalize_text(raw_field.get("help_text"), limit=255),
                "target_type": "all",
                "target_role_ids": [],
                "target_user_ids": [],
            }
        )

    narrative_input = raw_schema.get("narrative") if isinstance(raw_schema.get("narrative"), dict) else {}
    attachment_input = raw_schema.get("attachment") if isinstance(raw_schema.get("attachment"), dict) else {}
    normalized = {
        "enabled": _normalize_bool(raw_schema.get("enabled"), default=True),
        "narrative": {
            "enabled": _normalize_bool(narrative_input.get("enabled"), default=True),
            "label": _normalize_text(narrative_input.get("label"), default="Báo cáo lời tổng hợp", limit=255),
            "required": _normalize_bool(narrative_input.get("required"), default=True),
            "placeholder": _normalize_text(
                narrative_input.get("placeholder"),
                default="Nêu rõ kết quả, tồn tại và kiến nghị nếu có",
                limit=255,
            ),
            "target_type": "all",
            "target_role_ids": [],
            "target_user_ids": [],
        },
        "attachment": {
            "enabled": _normalize_bool(attachment_input.get("enabled")),
            "label": _normalize_text(attachment_input.get("label"), default="Tệp minh chứng", limit=255),
            "required": _normalize_bool(attachment_input.get("required")),
            "target_type": "all",
            "target_role_ids": [],
            "target_user_ids": [],
        },
        "fields": fields,
        "meta": {},
    }
    if not (
        normalized["enabled"]
        and (
            normalized["narrative"]["enabled"]
            or normalized["attachment"]["enabled"]
            or normalized["fields"]
        )
    ):
        return None
    return normalized


def _is_normalized_workflow_blueprint(raw_blueprint):
    if not isinstance(raw_blueprint, dict):
        return False
    if raw_blueprint.get("version") != 1:
        return False
    collection_mode = raw_blueprint.get("collection_mode")
    if collection_mode not in WORKFLOW_BLUEPRINT_ALLOWED_COLLECTION_MODES:
        return False

    items = raw_blueprint.get("items")
    if items is not None:
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                return False

    form_fields = raw_blueprint.get("form_fields")
    if form_fields is not None:
        if not isinstance(form_fields, list):
            return False
        for field in form_fields:
            if not isinstance(field, dict):
                return False
            if not field.get("field_key") or not field.get("field_label"):
                return False

    report_schema = raw_blueprint.get("report_schema")
    if report_schema is not None:
        if not isinstance(report_schema, dict):
            return False
        if "fields" not in report_schema or "narrative" not in report_schema or "attachment" not in report_schema:
            return False

    return True


def normalize_task_workflow_blueprint(raw_blueprint):
    if not isinstance(raw_blueprint, dict):
        return None
    if _is_normalized_workflow_blueprint(raw_blueprint):
        return raw_blueprint

    source_kind = _normalize_choice(
        raw_blueprint.get("source_kind"),
        WORKFLOW_BLUEPRINT_ALLOWED_SOURCE_KINDS,
        default="custom",
    )
    cadence = _normalize_choice(
        raw_blueprint.get("cadence"),
        WORKFLOW_BLUEPRINT_ALLOWED_CADENCES,
        default="ad_hoc",
    )
    items = _normalize_outline_items(raw_blueprint.get("items"))
    form_fields = _normalize_form_fields(raw_blueprint.get("form_fields"))
    report_schema = _normalize_report_schema(
        raw_blueprint.get("report_schema") or raw_blueprint.get("response_schema")
    )

    collection_mode = _normalize_choice(
        raw_blueprint.get("collection_mode"),
        WORKFLOW_BLUEPRINT_ALLOWED_COLLECTION_MODES,
    )
    if not collection_mode:
        if items:
            collection_mode = "outline"
        elif form_fields:
            collection_mode = "form"
        else:
            collection_mode = "file"

    title = _normalize_text(raw_blueprint.get("title"), limit=255)
    if not title:
        if items:
            title = items[0]["title"][:255]
        elif raw_blueprint.get("form_name"):
            title = _normalize_text(raw_blueprint.get("form_name"), limit=255)
        else:
            title = DEFAULT_BLUEPRINT_TITLE

    summary = _normalize_text(raw_blueprint.get("summary") or raw_blueprint.get("description"), limit=4000)
    if not summary and items:
        preview_titles = ", ".join(item["title"] for item in items[:3])
        remainder = max(len(items) - 3, 0)
        summary = f"Blueprint điều hành gồm {len(items)} đầu mục. Trọng tâm: {preview_titles}"
        if remainder:
            summary += f" và {remainder} đầu mục khác."

    blueprint = {
        "version": 1,
        "title": title,
        "summary": summary,
        "source_kind": source_kind,
        "cadence": cadence,
        "collection_mode": collection_mode,
        "items": items,
        "form_fields": form_fields,
        "report_schema": report_schema,
        "meta": raw_blueprint.get("meta") if isinstance(raw_blueprint.get("meta"), dict) else {},
    }

    if collection_mode == "outline" and not items:
        return None
    if collection_mode == "form" and not form_fields:
        return None
    if collection_mode == "file" and not report_schema:
        blueprint["report_schema"] = _normalize_report_schema(
            {
                "enabled": True,
                "narrative": {"enabled": True, "required": True},
                "attachment": {"enabled": False, "required": False},
                "fields": [],
            }
        )

    return blueprint


def workflow_blueprint_task_mode(blueprint):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized:
        return "FILE"
    if normalized["collection_mode"] == "outline":
        return "OUTLINE"
    if normalized["collection_mode"] == "form":
        return "FORM"
    return "FILE"


def workflow_blueprint_workflow_mode(blueprint):
    return "child_tasks" if workflow_blueprint_task_mode(blueprint) == "OUTLINE" else "summary_report"


def workflow_blueprint_item_configs(blueprint):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized or normalized["collection_mode"] != "outline":
        return []
    return list(normalized["items"])


def workflow_blueprint_form_field_defs(blueprint):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized or normalized["collection_mode"] != "form":
        return []
    return list(normalized["form_fields"])


def workflow_blueprint_report_schema(blueprint):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized or normalized["collection_mode"] != "file":
        return None
    return normalized.get("report_schema")


def workflow_blueprint_summary_text(blueprint):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized:
        return ""
    lines = []
    if normalized.get("summary"):
        lines.append(normalized["summary"])
    if normalized["collection_mode"] == "outline" and normalized["items"]:
        preview = "; ".join(item["title"] for item in normalized["items"][:5])
        lines.append(f"Đầu mục triển khai: {preview}")
    if normalized["collection_mode"] == "form" and normalized["form_fields"]:
        preview = ", ".join(field["field_label"] for field in normalized["form_fields"][:5])
        lines.append(f"Trường thu thập: {preview}")
    if normalized["collection_mode"] == "file" and normalized.get("report_schema"):
        field_labels = [
            field["label"]
            for field in normalized["report_schema"].get("fields", [])[:5]
        ]
        if field_labels:
            lines.append("Chỉ tiêu báo cáo: " + ", ".join(field_labels))
    return "\n".join(line for line in lines if line).strip()


def workflow_blueprint_preview_data(blueprint):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized:
        return None

    report_schema = normalized.get("report_schema") or {}
    report_fields = report_schema.get("fields", []) if isinstance(report_schema, dict) else []
    return {
        "title": normalized.get("title", ""),
        "summary": workflow_blueprint_summary_text(normalized),
        "source_kind": normalized.get("source_kind", "custom"),
        "cadence": normalized.get("cadence", "ad_hoc"),
        "collection_mode": normalized.get("collection_mode", "file"),
        "task_mode": workflow_blueprint_task_mode(normalized),
        "workflow_mode": workflow_blueprint_workflow_mode(normalized),
        "item_count": len(normalized.get("items") or []),
        "form_field_count": len(normalized.get("form_fields") or []),
        "report_field_count": len(report_fields),
        "narrative_enabled": bool(((report_schema.get("narrative") or {}).get("enabled"))),
        "attachment_enabled": bool(((report_schema.get("attachment") or {}).get("enabled"))),
        "item_titles": [item.get("title", "") for item in (normalized.get("items") or [])[:5] if item.get("title")],
        "form_field_labels": [
            field.get("field_label", "")
            for field in (normalized.get("form_fields") or [])[:5]
            if field.get("field_label")
        ],
        "report_field_labels": [field.get("label", "") for field in report_fields[:5] if field.get("label")],
    }


def workflow_blueprint_example_catalog():
    return list(WORKFLOW_BLUEPRINT_EXAMPLES)
