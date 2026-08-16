# -*- coding: utf-8 -*-
"""
Cụm nháp nhập việc (task import drafts): dựng cấu hình làm việc từ blueprint,
phân tích form nháp (đề cương / biểu mẫu / trường báo cáo), xem trước người nhận
theo đơn vị/vai trò, kiểm tra hiển thị trước khi phát hành và phát hành nháp
thành công việc thật (kèm assignment, phạm vi, thông báo, email).

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ.
"""

import json
import logging
from datetime import datetime

from flask import request, session
from werkzeug.datastructures import MultiDict

from category_helpers import canonicalize_category_value, stable_form_category_options
from models import Task, TaskAssignment, TaskFormField, TaskItem, db
from report_cycles import config_to_json as report_config_to_json, parse_config as report_parse_config
from routes.email_service import send_task_assignment_emails
from task_blueprints import (
    normalize_task_workflow_blueprint,
    workflow_blueprint_form_field_defs,
    workflow_blueprint_item_configs,
    workflow_blueprint_report_schema,
    workflow_blueprint_summary_text,
    workflow_blueprint_task_mode,
)
from utils import push_notif, remove_accents

from services.outline_engine import _clean_outline_title
from services.outline_submission import _find_report_secondary_linked_item
from services.task_assignees import (
    _create_assignment_records,
    _resolve_assignees_by_mode,
    _resolve_managers,
    _resolve_viewers,
)
from services.task_categories import (
    _task_domain_options,
    _task_field_options,
    _task_priority_options,
    _task_type_options,
)
from services.task_deadline import _parse_deadline
from services.task_form_fields import _normalize_task_form_field_type
from services.task_google_forms import _task_form_field_db_kwargs
from services.task_import_draft_helpers import (
    _draft_field_options_text,
    _json_dump,
    _json_loads_safe,
    _task_import_field_key,
    _task_import_form_field_options_json,
    _task_import_form_field_target_config,
)
from services.task_report_schema import (
    CHILD_TASK_ALLOWED_REPORT_KINDS,
    DEFAULT_TASK_REPORT_SCHEMA,
    TASK_REPORT_ALLOWED_FIELD_TYPES,
    _normalize_report_target_config,
    _normalize_report_target_domains,
    _normalize_report_target_ids,
    _normalize_task_report_schema,
    _report_checkbox_value,
    _task_report_item_visible_for_user,
)
from services.task_scope import (
    _load_assignment_scope,
    _requested_unit_domains,
    _store_assignment_scope,
    _store_manager_scope,
    _store_viewer_scope,
)
from services.task_units import _dedupe_users, _task_unit_identity

logger = logging.getLogger(__name__)

TASK_IMPORT_ASSIGN_TYPE_LABELS = {
    "unit": "Đơn vị",
    "role": "Vai trò",
    "user": "Cá nhân",
}
TASK_IMPORT_TARGET_TYPE_LABELS = {
    "all": "Tất cả người nhận",
    "unit": "Theo đơn vị",
    "role": "Theo vai trò",
    "user": "Theo cá nhân",
}
TASK_IMPORT_REPORT_KIND_LABELS = {
    "narrative": "Báo cáo lời",
    "number": "Báo cáo số",
}
TASK_IMPORT_FIELD_TYPE_LABELS = {
    "text": "Văn bản",
    "number": "Số",
    "textarea": "Đoạn văn",
    "radio": "Một lựa chọn",
    "checkbox": "Nhiều lựa chọn",
    "table": "Bảng",
}

def _task_import_working_config_from_blueprint(blueprint, source_type="", source_name="", source_ref=""):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized:
        raise ValueError("Blueprint điều hành chưa có nội dung hợp lệ.")

    config = {
        "version": 1,
        "source_type": str(source_type or "").strip(),
        "source_name": str(source_name or normalized.get("title") or "").strip()[:255],
        "source_ref": str(source_ref or "").strip()[:500],
        "source_kind": normalized.get("source_kind") or "custom",
        "collection_mode": normalized.get("collection_mode") or "file",
        "task_mode": workflow_blueprint_task_mode(normalized),
        "title": str(normalized.get("title") or "").strip()[:255],
        "summary": str(workflow_blueprint_summary_text(normalized) or "").strip()[:4000],
        "category": "",
        "domain": "",
        "priority": "Trung bình",
        "task_type": "Công việc thường xuyên",
        "deadline": "",
        "assign_type": "unit",
        "unit_domains": [],
        "role_ids": [],
        "user_ids": [],
        "manager_scope_mode": "none",
        "manager_role_ids": [],
        "manager_user_ids": [],
        "viewer_scope_mode": "none",
        "viewer_role_ids": [],
        "viewer_user_ids": [],
        "items": [],
        "form_fields": [],
        "report_narrative_enabled": True,
        "report_narrative_required": True,
        "report_narrative_label": "Báo cáo lời tổng hợp",
        "report_narrative_target_type": "all",
        "report_narrative_unit_domains": [],
        "report_narrative_role_ids": [],
        "report_narrative_user_ids": [],
        "report_attachment_enabled": False,
        "report_attachment_required": False,
        "report_attachment_label": "Tệp minh chứng",
        "report_attachment_target_type": "all",
        "report_attachment_unit_domains": [],
        "report_attachment_role_ids": [],
        "report_attachment_user_ids": [],
        "report_fields": [],
    }

    if config["collection_mode"] == "outline":
        for item in workflow_blueprint_item_configs(normalized):
            config["items"].append(
                {
                    "title": item.get("title", ""),
                    "guide_text": item.get("guide_text", ""),
                    "report_kind": item.get("report_kind") or "narrative",
                    "attachment_required": bool(item.get("attachment_required")),
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                    "sort_order": item.get("sort_order", len(config["items"])),
                }
            )
    elif config["collection_mode"] == "form":
        used_keys = set()
        for index, field in enumerate(workflow_blueprint_form_field_defs(normalized)):
            target_config = _task_import_form_field_target_config(field)
            field_key = str(field.get("field_key") or "").strip() or _task_import_field_key(
                field.get("field_label") or "",
                index,
                used_keys,
                "field",
            )
            used_keys.add(field_key)
            config["form_fields"].append(
                {
                    "field_key": field_key,
                    "field_label": str(field.get("field_label") or "").strip()[:255],
                    "field_type": _normalize_task_form_field_type(field.get("field_type") or "text"),
                    "field_options_text": _draft_field_options_text(field.get("field_options_json")),
                    "is_required": bool(field.get("is_required")),
                    "target_type": target_config.get("target_type") or "all",
                    "target_unit_domains": target_config.get("target_unit_domains") or [],
                    "target_role_ids": target_config.get("target_role_ids") or [],
                    "target_user_ids": target_config.get("target_user_ids") or [],
                    "sort_order": field.get("sort_order", len(config["form_fields"])),
                }
            )
    else:
        schema = workflow_blueprint_report_schema(normalized) or DEFAULT_TASK_REPORT_SCHEMA
        narrative = schema.get("narrative") or {}
        attachment = schema.get("attachment") or {}
        config["report_narrative_enabled"] = bool(narrative.get("enabled", True))
        config["report_narrative_required"] = bool(narrative.get("required", True))
        config["report_narrative_label"] = str(narrative.get("label") or "Báo cáo lời tổng hợp").strip()[:255]
        config["report_narrative_target_type"] = str(narrative.get("target_type") or "all").strip().lower() or "all"
        config["report_narrative_unit_domains"] = _normalize_report_target_domains(narrative.get("target_unit_domains") or [])
        config["report_narrative_role_ids"] = _normalize_report_target_ids(narrative.get("target_role_ids") or [])
        config["report_narrative_user_ids"] = _normalize_report_target_ids(narrative.get("target_user_ids") or [])
        config["report_attachment_enabled"] = bool(attachment.get("enabled"))
        config["report_attachment_required"] = bool(attachment.get("required"))
        config["report_attachment_label"] = str(attachment.get("label") or "Tệp minh chứng").strip()[:255]
        config["report_attachment_target_type"] = str(attachment.get("target_type") or "all").strip().lower() or "all"
        config["report_attachment_unit_domains"] = _normalize_report_target_domains(attachment.get("target_unit_domains") or [])
        config["report_attachment_role_ids"] = _normalize_report_target_ids(attachment.get("target_role_ids") or [])
        config["report_attachment_user_ids"] = _normalize_report_target_ids(attachment.get("target_user_ids") or [])
        used_keys = set()
        for index, field in enumerate(schema.get("fields") or []):
            field_key = str(field.get("key") or "").strip() or _task_import_field_key(
                field.get("label") or "",
                index,
                used_keys,
                "report",
            )
            used_keys.add(field_key)
            config["report_fields"].append(
                {
                    "key": field_key,
                    "label": str(field.get("label") or "").strip()[:255],
                    "type": str(field.get("type") or "text").strip().lower(),
                    "required": bool(field.get("required")),
                    "placeholder": str(field.get("placeholder") or "").strip()[:255],
                    "help_text": str(field.get("help_text") or "").strip()[:255],
                    "target_type": str(field.get("target_type") or "all").strip().lower() or "all",
                    "target_unit_domains": _normalize_report_target_domains(field.get("target_unit_domains") or []),
                    "target_role_ids": _normalize_report_target_ids(field.get("target_role_ids") or []),
                    "target_user_ids": _normalize_report_target_ids(field.get("target_user_ids") or []),
                    "sort_order": index,
                }
            )
    return config

def _task_import_draft_blueprint(draft):
    return _json_loads_safe(getattr(draft, "workflow_blueprint_json", None), {})

def _task_import_draft_working_config(draft):
    config = _json_loads_safe(getattr(draft, "working_config_json", None), {})
    if config:
        return config
    blueprint = _task_import_draft_blueprint(draft)
    if not blueprint:
        return {}
    return _task_import_working_config_from_blueprint(
        blueprint,
        source_type=getattr(draft, "source_type", ""),
        source_name=getattr(draft, "source_name", ""),
        source_ref=getattr(draft, "source_ref", ""),
    )

def _task_import_parse_id_csv(raw_value):
    return sorted({int(value) for value in str(raw_value or "").split(",") if value.strip().isdigit()})

def _task_import_working_assign_type(value, default=""):
    normalized = str(value or "").strip().lower()
    if normalized in {"unit", "role", "user"}:
        return normalized
    return default

def _task_import_assignment_has_targets(assign_type, unit_domains=None, role_ids=None, user_ids=None, fallback_domain=""):
    normalized = _task_import_working_assign_type(assign_type)
    if normalized == "role":
        return bool([int(role_id) for role_id in (role_ids or []) if str(role_id).isdigit()])
    if normalized == "user":
        return bool([int(user_id) for user_id in (user_ids or []) if str(user_id).isdigit()])
    if normalized == "unit":
        domains = [str(value or "").strip() for value in (unit_domains or []) if str(value or "").strip()]
        return bool(domains or str(fallback_domain or "").strip())
    return False

def _task_import_scope_from_form(form, prefix):
    assign_type = _task_import_working_assign_type(form.get(f"{prefix}_assign_type"), "unit")
    unit_domains = _requested_unit_domains(form, field_name=f"{prefix}_unit_domains", fallback_field=f"{prefix}_unit_domain")
    role_ids = sorted({int(role_id) for role_id in form.getlist(f"{prefix}_role_ids") if str(role_id).isdigit()})
    user_ids = sorted({int(uid) for uid in form.getlist(f"{prefix}_user_ids") if str(uid).isdigit()})
    return {
        "assign_type": assign_type,
        "unit_domains": unit_domains,
        "role_ids": role_ids,
        "user_ids": user_ids,
    }

def _task_import_summary_text(config):
    title = str(config.get("title") or "").strip()
    summary = str(config.get("summary") or "").strip()
    collection_mode = str(config.get("collection_mode") or "").strip()
    if summary:
        return summary
    if collection_mode == "outline":
        titles = [item.get("title") for item in config.get("items", []) if str(item.get("title") or "").strip()]
        if titles:
            preview = ", ".join(titles[:3])
            remainder = max(len(titles) - 3, 0)
            text = f"Đợt điều hành gồm {len(titles)} đầu mục. Trọng tâm: {preview}"
            if remainder:
                text += f" và {remainder} đầu mục khác."
            return text
    if collection_mode == "form":
        labels = [field.get("field_label") for field in config.get("form_fields", []) if str(field.get("field_label") or "").strip()]
        if labels:
            return "Biểu mẫu thu thập: " + ", ".join(labels[:5])
    if collection_mode == "file":
        labels = [field.get("label") for field in config.get("report_fields", []) if str(field.get("label") or "").strip()]
        if labels:
            return "Chỉ tiêu báo cáo: " + ", ".join(labels[:5])
    return title

def _parse_task_import_outline_items_from_form(form):
    titles = form.getlist("item_title")
    guide_texts = form.getlist("item_guide_text")
    report_kinds = form.getlist("item_report_kind")
    attachment_indexes = {value for value in form.getlist("item_attachment_required")}
    assign_types = form.getlist("item_assign_type")
    unit_domains_values = form.getlist("item_unit_domains")
    role_ids_values = form.getlist("item_role_ids")
    user_ids_values = form.getlist("item_user_ids")
    items = []
    seen = set()

    for index, raw_title in enumerate(titles):
        title = _clean_outline_title(raw_title)
        if not title:
            continue
        dedupe_key = title.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        report_kind = str(report_kinds[index] if index < len(report_kinds) else "narrative").strip().lower()
        if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
            report_kind = "narrative"
        raw_unit_domains = str(unit_domains_values[index] if index < len(unit_domains_values) else "").strip()
        unit_domains = _requested_unit_domains(
            MultiDict([("child_domains", value.strip()) for value in raw_unit_domains.split(",") if value.strip()])
        )
        items.append(
            {
                "title": title[:255],
                "guide_text": str(guide_texts[index] if index < len(guide_texts) else "").strip()[:2000],
                "report_kind": report_kind,
                "attachment_required": str(index) in attachment_indexes,
                "assign_type": _task_import_working_assign_type(assign_types[index] if index < len(assign_types) else ""),
                "unit_domains": unit_domains,
                "role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                "user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
                "sort_order": len(items),
            }
        )
    return items

def _parse_task_import_form_fields_from_form(form):
    labels = form.getlist("form_field_label")
    keys = form.getlist("form_field_key")
    field_types = form.getlist("form_field_type")
    option_texts = form.getlist("form_field_options")
    required_indexes = {value for value in form.getlist("form_field_required")}
    target_types = form.getlist("form_field_target_type")
    unit_domains_values = form.getlist("form_field_target_unit_domains")
    role_ids_values = form.getlist("form_field_target_role_ids")
    user_ids_values = form.getlist("form_field_target_user_ids")
    fields = []
    used_keys = set()
    for index, raw_label in enumerate(labels):
        label = str(raw_label or "").strip()
        if not label:
            continue
        field_type = _normalize_task_form_field_type(field_types[index] if index < len(field_types) else "text")
        raw_key = str(keys[index] if index < len(keys) else "").strip()
        field_key = raw_key or _task_import_field_key(label, index, used_keys, "field")
        if field_key in used_keys:
            field_key = _task_import_field_key(label, index, used_keys, "field")
        used_keys.add(field_key)
        option_text = str(option_texts[index] if index < len(option_texts) else "").strip()
        target_config = _normalize_report_target_config(
            {
                "target_type": target_types[index] if index < len(target_types) else "all",
                "target_unit_domains": unit_domains_values[index] if index < len(unit_domains_values) else "",
                "target_role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                "target_user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
            }
        )
        fields.append(
            {
                "field_key": field_key[:100],
                "field_label": label[:255],
                "field_type": field_type,
                "field_options_text": option_text,
                "is_required": str(index) in required_indexes,
                "target_type": target_config.get("target_type") or "all",
                "target_unit_domains": target_config.get("target_unit_domains") or [],
                "target_role_ids": target_config.get("target_role_ids") or [],
                "target_user_ids": target_config.get("target_user_ids") or [],
                "sort_order": len(fields),
            }
        )
    return fields

def _parse_task_import_report_fields_from_form(form):
    labels = form.getlist("report_field_label")
    keys = form.getlist("report_field_key")
    field_types = form.getlist("report_field_type")
    placeholders = form.getlist("report_field_placeholder")
    help_texts = form.getlist("report_field_help_text")
    required_indexes = {value for value in form.getlist("report_field_required")}
    target_types = form.getlist("report_field_target_type")
    unit_domains_values = form.getlist("report_field_target_unit_domains")
    role_ids_values = form.getlist("report_field_target_role_ids")
    user_ids_values = form.getlist("report_field_target_user_ids")
    fields = []
    used_keys = set()
    for index, raw_label in enumerate(labels):
        label = str(raw_label or "").strip()
        if not label:
            continue
        field_type = str(field_types[index] if index < len(field_types) else "text").strip().lower()
        if field_type not in TASK_REPORT_ALLOWED_FIELD_TYPES:
            field_type = "text"
        raw_key = str(keys[index] if index < len(keys) else "").strip()
        field_key = raw_key or _task_import_field_key(label, index, used_keys, "report")
        if field_key in used_keys:
            field_key = _task_import_field_key(label, index, used_keys, "report")
        used_keys.add(field_key)
        fields.append(
            {
                "key": field_key[:100],
                "label": label[:255],
                "type": field_type,
                "required": str(index) in required_indexes,
                "placeholder": str(placeholders[index] if index < len(placeholders) else "").strip()[:255],
                "help_text": str(help_texts[index] if index < len(help_texts) else "").strip()[:255],
                "target_type": _normalize_report_target_config(
                    {
                        "target_type": target_types[index] if index < len(target_types) else "all",
                        "target_unit_domains": unit_domains_values[index] if index < len(unit_domains_values) else "",
                        "target_role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                        "target_user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
                    }
                )["target_type"],
                "target_unit_domains": _normalize_report_target_domains(unit_domains_values[index] if index < len(unit_domains_values) else ""),
                "target_role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                "target_user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
                "sort_order": len(fields),
            }
        )
    return fields

def _parse_task_import_working_config_from_form(draft, form):
    current_config = _task_import_draft_working_config(draft)
    config = dict(current_config or {})
    collection_mode = str(config.get("collection_mode") or "").strip().lower() or "outline"
    task_fields = _task_field_options()
    pro_units = _task_domain_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()

    config["title"] = str(form.get("title") or "").strip()[:255]
    config["summary"] = str(form.get("summary") or "").strip()[:4000]
    config["category"] = canonicalize_category_value(form.get("category") or "", task_fields, prefer_stable=True)
    config["domain"] = canonicalize_category_value(form.get("domain") or "", pro_units, prefer_stable=True)
    config["task_type"] = canonicalize_category_value(form.get("task_type") or "Công việc thường xuyên", task_types, prefer_stable=True)
    config["priority"] = canonicalize_category_value(form.get("priority") or "Trung bình", priority_items, prefer_stable=True)
    config["deadline"] = str(form.get("deadline") or "").strip()[:20]

    scope = _task_import_scope_from_form(form, "draft")
    config.update(scope)

    config["manager_scope_mode"] = str(form.get("manager_scope_mode") or "none").strip().lower()
    config["manager_role_ids"] = sorted({int(role_id) for role_id in form.getlist("manager_role_ids") if str(role_id).isdigit()})
    config["manager_user_ids"] = sorted({int(uid) for uid in form.getlist("manager_user_ids") if str(uid).isdigit()})
    config["viewer_scope_mode"] = str(form.get("viewer_scope_mode") or "none").strip().lower()
    config["viewer_role_ids"] = sorted({int(role_id) for role_id in form.getlist("viewer_role_ids") if str(role_id).isdigit()})
    config["viewer_user_ids"] = sorted({int(uid) for uid in form.getlist("viewer_user_ids") if str(uid).isdigit()})

    if collection_mode == "outline":
        config["items"] = _parse_task_import_outline_items_from_form(form)
    elif collection_mode == "form":
        config["form_fields"] = _parse_task_import_form_fields_from_form(form)
    else:
        config["report_narrative_enabled"] = _report_checkbox_value(form.get("report_narrative_enabled"))
        config["report_narrative_required"] = _report_checkbox_value(form.get("report_narrative_required"))
        config["report_narrative_label"] = str(form.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip()[:255]
        config["report_narrative_target_type"] = str(form.get("report_narrative_target_type") or "all").strip().lower()
        config["report_narrative_unit_domains"] = _requested_unit_domains(form, field_name="report_narrative_unit_domains", fallback_field="")
        config["report_narrative_role_ids"] = sorted({int(role_id) for role_id in form.getlist("report_narrative_role_ids") if str(role_id).isdigit()})
        config["report_narrative_user_ids"] = sorted({int(uid) for uid in form.getlist("report_narrative_user_ids") if str(uid).isdigit()})
        config["report_attachment_enabled"] = _report_checkbox_value(form.get("report_attachment_enabled"))
        config["report_attachment_required"] = _report_checkbox_value(form.get("report_attachment_required"))
        config["report_attachment_label"] = str(form.get("report_attachment_label") or "Tệp minh chứng").strip()[:255]
        config["report_attachment_target_type"] = str(form.get("report_attachment_target_type") or "all").strip().lower()
        config["report_attachment_unit_domains"] = _requested_unit_domains(form, field_name="report_attachment_unit_domains", fallback_field="")
        config["report_attachment_role_ids"] = sorted({int(role_id) for role_id in form.getlist("report_attachment_role_ids") if str(role_id).isdigit()})
        config["report_attachment_user_ids"] = sorted({int(uid) for uid in form.getlist("report_attachment_user_ids") if str(uid).isdigit()})
        config["report_fields"] = _parse_task_import_report_fields_from_form(form)

    if not config.get("summary"):
        config["summary"] = _task_import_summary_text(config)
    return config

def _task_import_report_schema_from_config(config):
    if str(config.get("collection_mode") or "").strip().lower() != "file":
        return None
    raw_schema = {
        "enabled": True,
        "narrative": {
            "enabled": bool(config.get("report_narrative_enabled", True)),
            "required": bool(config.get("report_narrative_required", True)),
            "label": str(config.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip(),
            "target_type": str(config.get("report_narrative_target_type") or "all").strip().lower(),
            "target_unit_domains": _normalize_report_target_domains(config.get("report_narrative_unit_domains") or []),
            "target_role_ids": _normalize_report_target_ids(config.get("report_narrative_role_ids") or []),
            "target_user_ids": _normalize_report_target_ids(config.get("report_narrative_user_ids") or []),
        },
        "attachment": {
            "enabled": bool(config.get("report_attachment_enabled")),
            "required": bool(config.get("report_attachment_required")),
            "label": str(config.get("report_attachment_label") or "Tệp minh chứng").strip(),
            "target_type": str(config.get("report_attachment_target_type") or "all").strip().lower(),
            "target_unit_domains": _normalize_report_target_domains(config.get("report_attachment_unit_domains") or []),
            "target_role_ids": _normalize_report_target_ids(config.get("report_attachment_role_ids") or []),
            "target_user_ids": _normalize_report_target_ids(config.get("report_attachment_user_ids") or []),
        },
        "fields": [
            {
                "key": field.get("key"),
                "label": field.get("label"),
                "type": field.get("type"),
                "required": bool(field.get("required")),
                "placeholder": field.get("placeholder"),
                "help_text": field.get("help_text"),
                "target_type": str(field.get("target_type") or "all").strip().lower(),
                "target_unit_domains": _normalize_report_target_domains(field.get("target_unit_domains") or []),
                "target_role_ids": _normalize_report_target_ids(field.get("target_role_ids") or []),
                "target_user_ids": _normalize_report_target_ids(field.get("target_user_ids") or []),
            }
            for field in (config.get("report_fields") or [])
            if str(field.get("label") or "").strip()
        ],
    }
    return _normalize_task_report_schema(raw_schema)

def _task_import_form_field_defs_from_config(config):
    field_defs = []
    used_keys = set()
    for index, field in enumerate(config.get("form_fields") or []):
        label = str(field.get("field_label") or "").strip()
        if not label:
            continue
        field_key = str(field.get("field_key") or "").strip()
        if not field_key or field_key in used_keys:
            field_key = _task_import_field_key(label, index, used_keys, "field")
        used_keys.add(field_key)
        field_type = _normalize_task_form_field_type(field.get("field_type") or "text")
        field_defs.append(
            {
                "field_key": field_key[:100],
                "field_label": label[:255],
                "field_type": field_type,
                "field_options_json": _task_import_form_field_options_json(
                    field_type,
                    field.get("field_options_text"),
                    {
                        "target_type": field.get("target_type") or "all",
                        "target_unit_domains": field.get("target_unit_domains") or [],
                        "target_role_ids": field.get("target_role_ids") or [],
                        "target_user_ids": field.get("target_user_ids") or [],
                    },
                ),
                "sort_order": len(field_defs),
                "is_required": bool(field.get("is_required")),
            }
        )
    return field_defs

def _task_import_blueprint_from_config(config):
    collection_mode = str(config.get("collection_mode") or "").strip().lower()
    raw_blueprint = {
        "title": str(config.get("title") or "").strip(),
        "summary": str(config.get("summary") or "").strip(),
        "source_kind": str(config.get("source_kind") or "custom").strip().lower(),
        "collection_mode": collection_mode,
    }
    if collection_mode == "outline":
        raw_blueprint["items"] = [
            {
                "title": item.get("title"),
                "guide_text": item.get("guide_text"),
                "report_kind": item.get("report_kind"),
                "attachment_required": bool(item.get("attachment_required")),
            }
            for item in (config.get("items") or [])
            if str(item.get("title") or "").strip()
        ]
    elif collection_mode == "form":
        raw_blueprint["form_fields"] = [
            {
                "label": field.get("field_label"),
                "type": field.get("field_type"),
                "required": bool(field.get("is_required")),
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
                "options": (
                    [item.strip() for item in str(field.get("field_options_text") or "").splitlines() if item.strip()]
                    if str(field.get("field_type") or "").strip().lower() in {"radio", "checkbox"}
                    else [item.strip() for item in str(field.get("field_options_text") or "").split(",") if item.strip()]
                ),
            }
            for field in (config.get("form_fields") or [])
            if str(field.get("field_label") or "").strip()
        ]
    elif collection_mode == "file":
        raw_blueprint["report_schema"] = {
            "enabled": True,
            "narrative": {
                "enabled": bool(config.get("report_narrative_enabled", True)),
                "required": bool(config.get("report_narrative_required", True)),
                "label": config.get("report_narrative_label"),
                "target_type": config.get("report_narrative_target_type") or "all",
                "target_unit_domains": config.get("report_narrative_unit_domains") or [],
                "target_role_ids": config.get("report_narrative_role_ids") or [],
                "target_user_ids": config.get("report_narrative_user_ids") or [],
            },
            "attachment": {
                "enabled": bool(config.get("report_attachment_enabled")),
                "required": bool(config.get("report_attachment_required")),
                "label": config.get("report_attachment_label"),
                "target_type": config.get("report_attachment_target_type") or "all",
                "target_unit_domains": config.get("report_attachment_unit_domains") or [],
                "target_role_ids": config.get("report_attachment_role_ids") or [],
                "target_user_ids": config.get("report_attachment_user_ids") or [],
            },
            "fields": [
                {
                    "key": field.get("key"),
                    "label": field.get("label"),
                    "type": field.get("type"),
                    "required": bool(field.get("required")),
                    "placeholder": field.get("placeholder"),
                    "help_text": field.get("help_text"),
                    "target_type": field.get("target_type") or "all",
                    "target_unit_domains": field.get("target_unit_domains") or [],
                    "target_role_ids": field.get("target_role_ids") or [],
                    "target_user_ids": field.get("target_user_ids") or [],
                }
                for field in (config.get("report_fields") or [])
                if str(field.get("label") or "").strip()
            ],
        }
    return normalize_task_workflow_blueprint(raw_blueprint)


def _parse_task_workflow_blueprint_payload(payload):
    """Phân tích payload blueprint từ request, trả về blueprint đã chuẩn hóa."""
    if isinstance(payload, dict) and isinstance(payload.get("workflow_blueprint"), dict):
        payload = payload.get("workflow_blueprint")

    if not isinstance(payload, dict):
        raise ValueError("Blueprint điều hành không hợp lệ.")

    normalized = normalize_task_workflow_blueprint(payload)
    if not normalized:
        raise ValueError("Blueprint điều hành chưa có nội dung hợp lệ.")
    return normalized


def _task_import_config_stats(config):
    mode = str(config.get("collection_mode") or "").strip().lower()
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    stats = {
        "mode": mode,
        "item_count": 0,
        "field_count": 0,
        "report_field_count": 0,
        "unassigned_count": 0,
    }
    if mode == "outline":
        items = [item for item in (config.get("items") or []) if str(item.get("title") or "").strip()]
        stats["item_count"] = len(items)
        stats["unassigned_count"] = sum(
            1
            for item in items
            if not _task_import_assignment_has_targets(
                item.get("assign_type"),
                unit_domains=item.get("unit_domains"),
                role_ids=item.get("role_ids"),
                user_ids=item.get("user_ids"),
                fallback_domain=fallback_domain,
            )
        )
    elif mode == "form":
        fields = [field for field in (config.get("form_fields") or []) if str(field.get("field_label") or "").strip()]
        stats["field_count"] = len(fields)
        stats["unassigned_count"] = 0 if _task_import_assignment_has_targets(
            config.get("assign_type"),
            unit_domains=config.get("unit_domains"),
            role_ids=config.get("role_ids"),
            user_ids=config.get("user_ids"),
            fallback_domain=fallback_domain,
        ) else 1
    else:
        report_fields = [field for field in (config.get("report_fields") or []) if str(field.get("label") or "").strip()]
        stats["report_field_count"] = len(report_fields)
        stats["unassigned_count"] = 0 if _task_import_assignment_has_targets(
            config.get("assign_type"),
            unit_domains=config.get("unit_domains"),
            role_ids=config.get("role_ids"),
            user_ids=config.get("user_ids"),
            fallback_domain=fallback_domain,
        ) else 1
    return stats

def _task_import_user_unit_label(user, unit_lookup=None):
    unit_lookup = unit_lookup or {}
    raw_value = getattr(user, "unit_area", None) or getattr(user, "unit_key", None) or ""
    canonical_value = canonicalize_category_value(raw_value or "", _task_domain_options(), prefer_stable=True)
    if canonical_value and unit_lookup.get(canonical_value):
        return unit_lookup.get(canonical_value)
    if raw_value:
        return str(raw_value).strip()
    return "Chưa có đơn vị"

def _task_import_scope_target_labels(assign_type, unit_domains=None, role_ids=None, user_ids=None, fallback_domain="", unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    normalized = _task_import_working_assign_type(assign_type)
    if normalized == "unit":
        raw_domains = list(unit_domains or [])
        if not raw_domains and str(fallback_domain or "").strip():
            raw_domains = [fallback_domain]
        labels = [unit_lookup.get(domain) or domain for domain in raw_domains if str(domain or "").strip()]
        return labels
    if normalized == "role":
        return [role_lookup.get(int(role_id), str(role_id)) for role_id in (role_ids or []) if str(role_id).isdigit()]
    if normalized == "user":
        return [user_lookup.get(int(user_id), str(user_id)) for user_id in (user_ids or []) if str(user_id).isdigit()]
    return []

def _task_import_scope_summary(assign_type, unit_domains=None, role_ids=None, user_ids=None, fallback_domain="", unit_lookup=None, role_lookup=None, user_lookup=None):
    raw_type = str(assign_type or "").strip().lower()
    if raw_type == "all":
        return {
            "assign_type": "all",
            "mode_label": TASK_IMPORT_TARGET_TYPE_LABELS["all"],
            "labels": [],
            "text": TASK_IMPORT_TARGET_TYPE_LABELS["all"],
        }
    normalized = _task_import_working_assign_type(raw_type)
    labels = _task_import_scope_target_labels(
        normalized,
        unit_domains=unit_domains,
        role_ids=role_ids,
        user_ids=user_ids,
        fallback_domain=fallback_domain,
        unit_lookup=unit_lookup,
        role_lookup=role_lookup,
        user_lookup=user_lookup,
    )
    mode_label = TASK_IMPORT_ASSIGN_TYPE_LABELS.get(normalized, "Chưa cấu hình")
    if not normalized:
        return {
            "assign_type": "",
            "mode_label": "Chưa cấu hình",
            "labels": [],
            "text": "Chưa gán người thực hiện",
        }
    if labels:
        return {
            "assign_type": normalized,
            "mode_label": mode_label,
            "labels": labels,
            "text": f"{mode_label}: {', '.join(labels)}",
        }
    return {
        "assign_type": normalized,
        "mode_label": mode_label,
        "labels": [],
        "text": f"{mode_label}: chưa có người nhận hợp lệ",
    }

def _task_import_preview_recipient_entry(user, unit_lookup=None, role_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    role_id = getattr(user, "role_id", None)
    return {
        "key": f"user:{user.id}",
        "user_id": user.id,
        "user_name": getattr(user, "fullname", None) or getattr(user, "username", None) or f"User {user.id}",
        "username": getattr(user, "username", None) or "",
        "unit_name": _task_import_user_unit_label(user, unit_lookup=unit_lookup),
        "role_name": role_lookup.get(role_id, "") if role_id else "",
        "outline_items": [],
        "form_fields": [],
        "file_sections": [],
        "delivery_labels": [],
        "warnings": [],
        "item_count": 0,
        "field_count": 0,
        "section_count": 0,
    }

def _task_import_preview_warning_text(message):
    text = str(message or "").strip()
    return text[:400] if text else "Cấu hình người nhận chưa hợp lệ."

def _task_import_preview_submission_group_info(assign_type, user, role_lookup=None, unit_lookup=None):
    role_lookup = role_lookup or {}
    unit_lookup = unit_lookup or {}
    normalized = _task_import_working_assign_type(assign_type)
    user_name = getattr(user, "fullname", None) or getattr(user, "username", None) or f"User {getattr(user, 'id', '')}"
    unit_name = _task_import_user_unit_label(user, unit_lookup=unit_lookup)
    unit_identity = _task_unit_identity(user)
    unit_key = unit_identity.get("unit_key") or remove_accents(unit_name).strip().lower() or f"user:{getattr(user, 'id', 0)}"
    role_id = int(getattr(user, "role_id", None) or 0)
    role_name = role_lookup.get(role_id, "") if role_id else ""

    if normalized == "unit":
        return {
            "mode": "unit",
            "mode_label": "Nộp theo đơn vị",
            "group_key": f"unit:{unit_key}",
            "group_label": f"Đơn vị {unit_name}",
            "member_label": user_name,
        }
    if normalized == "role":
        role_key = role_id or 0
        role_title = role_name or "Chưa phân vai trò"
        return {
            "mode": "role",
            "mode_label": "Nộp theo vai trò",
            "group_key": f"role:{role_key}:unit:{unit_key}",
            "group_label": f"{role_title} - {unit_name}",
            "member_label": user_name,
        }
    return {
        "mode": "user",
        "mode_label": "Nộp cá nhân",
        "group_key": f"user:{int(getattr(user, 'id', 0) or 0)}",
        "group_label": user_name,
        "member_label": user_name,
    }

def _task_import_preview_unit_groups(mode, cards):
    mode_key = str(mode or "").strip().lower()
    unit_map = {}

    def ensure_group(card):
        unit_name = str(card.get("unit_name") or "Chưa có đơn vị").strip() or "Chưa có đơn vị"
        return unit_map.setdefault(
            unit_name,
            {
                "unit_name": unit_name,
                "recipient_count": 0,
                "item_count": 0,
                "field_count": 0,
                "section_count": 0,
                "warning_count": 0,
                "recipient_names": [],
                "delivery_labels": [],
                "payload_labels": [],
            },
        )

    def push_unique(values, value, limit=5):
        text = str(value or "").strip()
        if not text or text in values:
            return
        values.append(text)
        if len(values) > limit:
            del values[limit:]

    for card in cards or []:
        group = ensure_group(card)
        group["recipient_count"] += 1
        group["item_count"] += int(card.get("item_count") or 0)
        group["field_count"] += int(card.get("field_count") or 0)
        group["section_count"] += int(card.get("section_count") or 0)
        group["warning_count"] += len(card.get("warnings") or [])
        push_unique(group["recipient_names"], card.get("user_name"), limit=4)
        for label in (card.get("delivery_labels") or []):
            push_unique(group["delivery_labels"], label, limit=4)
        if mode_key == "outline":
            for item in (card.get("outline_items") or []):
                push_unique(group["payload_labels"], item.get("title"))
        elif mode_key == "form":
            for field in (card.get("form_fields") or []):
                push_unique(group["payload_labels"], field.get("label"))
        else:
            for section in (card.get("file_sections") or []):
                push_unique(group["payload_labels"], section.get("label"))

    return sorted(
        unit_map.values(),
        key=lambda item: (-item["recipient_count"], -item["item_count"] - item["field_count"] - item["section_count"], remove_accents(item["unit_name"]).lower()),
    )

def _task_import_preview_submission_groups(mode, cards):
    mode_key = str(mode or "").strip().lower()
    group_map = {}

    def ensure_group(group_key, group_label, mode_label):
        return group_map.setdefault(
            group_key,
            {
                "group_key": group_key,
                "group_label": group_label,
                "mode_label": mode_label,
                "member_names": [],
                "payload_labels": [],
                "payload_count": 0,
                "recipient_count": 0,
            },
        )

    def push_unique(values, value, limit=6):
        text = str(value or "").strip()
        if not text or text in values:
            return
        values.append(text)
        if len(values) > limit:
            del values[limit:]

    def add_payload(group, payload_label):
        text = str(payload_label or "").strip()
        if not text:
            return
        group["payload_count"] += 1
        push_unique(group["payload_labels"], text)

    for card in cards or []:
        if mode_key == "outline":
            for item in (card.get("outline_items") or []):
                group_key = str(item.get("submission_group_key") or "").strip()
                if not group_key:
                    continue
                group = ensure_group(
                    group_key,
                    item.get("submission_group_label") or card.get("user_name") or "Nhóm nộp",
                    item.get("submission_mode_label") or "Nộp cá nhân",
                )
                push_unique(group["member_names"], card.get("user_name"))
                group["recipient_count"] = len(group["member_names"])
                add_payload(group, item.get("title"))
        elif mode_key == "form":
            group_key = str(card.get("submission_group_key") or "").strip()
            if not group_key:
                continue
            group = ensure_group(
                group_key,
                card.get("submission_group_label") or card.get("user_name") or "Nhóm nộp",
                card.get("submission_mode_label") or "Nộp cá nhân",
            )
            push_unique(group["member_names"], card.get("user_name"))
            group["recipient_count"] = len(group["member_names"])
            for field in (card.get("form_fields") or []):
                add_payload(group, field.get("label"))
        else:
            group_key = str(card.get("submission_group_key") or "").strip()
            if not group_key:
                continue
            group = ensure_group(
                group_key,
                card.get("submission_group_label") or card.get("user_name") or "Nhóm nộp",
                card.get("submission_mode_label") or "Nộp cá nhân",
            )
            push_unique(group["member_names"], card.get("user_name"))
            group["recipient_count"] = len(group["member_names"])
            for section in (card.get("file_sections") or []):
                add_payload(group, section.get("label"))

    return sorted(
        group_map.values(),
        key=lambda item: (-int(item["recipient_count"] or 0), -int(item["payload_count"] or 0), remove_accents(item["group_label"]).lower()),
    )

def _task_import_outline_recipient_preview(config, unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    recipients = {}
    warnings = []

    for item in (config.get("items") or []):
        title = _clean_outline_title(item.get("title"))
        if not title:
            continue
        assign_type = _task_import_working_assign_type(item.get("assign_type"))
        scope_summary = _task_import_scope_summary(
            assign_type,
            unit_domains=item.get("unit_domains") or [],
            role_ids=item.get("role_ids") or [],
            user_ids=item.get("user_ids") or [],
            fallback_domain=fallback_domain,
            unit_lookup=unit_lookup,
            role_lookup=role_lookup,
            user_lookup=user_lookup,
        )
        assignees, error_message = _resolve_assignees_by_mode(
            assign_type,
            domain=fallback_domain,
            unit_domains=item.get("unit_domains") or [],
            target_ids=item.get("user_ids") or [],
            assignee_role_ids=item.get("role_ids") or [],
        )
        if error_message or not assignees:
            warnings.append(
                {
                    "scope": title,
                    "message": _task_import_preview_warning_text(
                        error_message or "Đầu mục này chưa có người nhận hợp lệ."
                    ),
                }
            )
            continue
        row_preview = {
            "title": title,
            "guide_text": str(item.get("guide_text") or "").strip(),
            "report_kind": str(item.get("report_kind") or "narrative").strip().lower() or "narrative",
            "report_kind_label": TASK_IMPORT_REPORT_KIND_LABELS.get(
                str(item.get("report_kind") or "narrative").strip().lower(),
                "Báo cáo lời",
            ),
            "attachment_required": bool(item.get("attachment_required")),
            "delivery_text": scope_summary["text"],
            "delivery_mode": scope_summary["mode_label"],
            "sort_order": int(item.get("sort_order") or 0),
        }
        for assignee in assignees:
            submission_group = _task_import_preview_submission_group_info(
                assign_type,
                assignee,
                role_lookup=role_lookup,
                unit_lookup=unit_lookup,
            )
            entry = recipients.setdefault(
                assignee.id,
                _task_import_preview_recipient_entry(assignee, unit_lookup=unit_lookup, role_lookup=role_lookup),
            )
            preview_payload = dict(
                row_preview,
                submission_group_key=submission_group["group_key"],
                submission_group_label=submission_group["group_label"],
                submission_mode_label=submission_group["mode_label"],
            )
            entry["outline_items"].append(preview_payload)
            if scope_summary["text"] not in entry["delivery_labels"]:
                entry["delivery_labels"].append(scope_summary["text"])

    cards = sorted(
        recipients.values(),
        key=lambda item: (remove_accents(item["unit_name"]).lower(), remove_accents(item["user_name"]).lower()),
    )
    for card in cards:
        card["outline_items"].sort(key=lambda item: (item["sort_order"], remove_accents(item["title"]).lower()))
        card["item_count"] = len(card["outline_items"])
    return {
        "mode": "outline",
        "recipient_count": len(cards),
        "cards": cards,
        "warnings": warnings,
        "unit_groups": _task_import_preview_unit_groups("outline", cards),
        "submission_groups": _task_import_preview_submission_groups("outline", cards),
    }

def _task_import_form_recipient_preview(config, unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    scope_summary = _task_import_scope_summary(
        config.get("assign_type"),
        unit_domains=config.get("unit_domains") or [],
        role_ids=config.get("role_ids") or [],
        user_ids=config.get("user_ids") or [],
        fallback_domain=fallback_domain,
        unit_lookup=unit_lookup,
        role_lookup=role_lookup,
        user_lookup=user_lookup,
    )
    assignees, error_message = _resolve_assignees_by_mode(
        _task_import_working_assign_type(config.get("assign_type"), "unit"),
        domain=fallback_domain,
        unit_domains=config.get("unit_domains") or [],
        target_ids=config.get("user_ids") or [],
        assignee_role_ids=config.get("role_ids") or [],
    )
    warnings = []
    if error_message:
        warnings.append({"scope": "Phân công toàn nhiệm vụ", "message": _task_import_preview_warning_text(error_message)})
    fields = [field for field in (config.get("form_fields") or []) if str(field.get("field_label") or "").strip()]
    cards = []
    for assignee in assignees:
        entry = _task_import_preview_recipient_entry(assignee, unit_lookup=unit_lookup, role_lookup=role_lookup)
        entry["delivery_labels"] = [scope_summary["text"]]
        submission_group = _task_import_preview_submission_group_info(
            config.get("assign_type"),
            assignee,
            role_lookup=role_lookup,
            unit_lookup=unit_lookup,
        )
        entry["submission_group_key"] = submission_group["group_key"]
        entry["submission_group_label"] = submission_group["group_label"]
        entry["submission_mode_label"] = submission_group["mode_label"]
        for field in fields:
            field_config = {
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
            }
            if not _task_report_item_visible_for_user(field_config, assignee):
                continue
            target_summary = _task_import_scope_summary(
                field.get("target_type") or "all",
                unit_domains=field.get("target_unit_domains") or [],
                role_ids=field.get("target_role_ids") or [],
                user_ids=field.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["form_fields"].append(
                {
                    "label": str(field.get("field_label") or "").strip(),
                    "field_type": str(field.get("field_type") or "text").strip().lower() or "text",
                    "field_type_label": TASK_IMPORT_FIELD_TYPE_LABELS.get(
                        str(field.get("field_type") or "text").strip().lower(),
                        "Văn bản",
                    ),
                    "is_required": bool(field.get("is_required")),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": int(field.get("sort_order") or 0),
                }
            )
        entry["form_fields"].sort(key=lambda item: (item["sort_order"], remove_accents(item["label"]).lower()))
        entry["field_count"] = len(entry["form_fields"])
        if not entry["field_count"]:
            entry["warnings"].append("Người nhận này được giao nhiệm vụ nhưng hiện chưa thấy trường biểu mẫu nào.")
        cards.append(entry)

    cards.sort(key=lambda item: (remove_accents(item["unit_name"]).lower(), remove_accents(item["user_name"]).lower()))
    if not fields:
        warnings.append({"scope": "Biểu mẫu", "message": "Chưa có trường biểu mẫu hợp lệ để phát hành."})
    return {
        "mode": "form",
        "recipient_count": len(cards),
        "cards": cards,
        "warnings": warnings,
        "global_delivery_text": scope_summary["text"],
        "unit_groups": _task_import_preview_unit_groups("form", cards),
        "submission_groups": _task_import_preview_submission_groups("form", cards),
    }

def _task_import_file_recipient_preview(config, unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    scope_summary = _task_import_scope_summary(
        config.get("assign_type"),
        unit_domains=config.get("unit_domains") or [],
        role_ids=config.get("role_ids") or [],
        user_ids=config.get("user_ids") or [],
        fallback_domain=fallback_domain,
        unit_lookup=unit_lookup,
        role_lookup=role_lookup,
        user_lookup=user_lookup,
    )
    assignees, error_message = _resolve_assignees_by_mode(
        _task_import_working_assign_type(config.get("assign_type"), "unit"),
        domain=fallback_domain,
        unit_domains=config.get("unit_domains") or [],
        target_ids=config.get("user_ids") or [],
        assignee_role_ids=config.get("role_ids") or [],
    )
    warnings = []
    if error_message:
        warnings.append({"scope": "Phân công toàn nhiệm vụ", "message": _task_import_preview_warning_text(error_message)})

    narrative_cfg = {
        "enabled": bool(config.get("report_narrative_enabled", True)),
        "required": bool(config.get("report_narrative_required", True)),
        "label": str(config.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip(),
        "target_type": config.get("report_narrative_target_type") or "all",
        "target_unit_domains": config.get("report_narrative_unit_domains") or [],
        "target_role_ids": config.get("report_narrative_role_ids") or [],
        "target_user_ids": config.get("report_narrative_user_ids") or [],
    }
    attachment_cfg = {
        "enabled": bool(config.get("report_attachment_enabled")),
        "required": bool(config.get("report_attachment_required")),
        "label": str(config.get("report_attachment_label") or "Tệp minh chứng").strip(),
        "target_type": config.get("report_attachment_target_type") or "all",
        "target_unit_domains": config.get("report_attachment_unit_domains") or [],
        "target_role_ids": config.get("report_attachment_role_ids") or [],
        "target_user_ids": config.get("report_attachment_user_ids") or [],
    }
    report_fields = [field for field in (config.get("report_fields") or []) if str(field.get("label") or "").strip()]
    cards = []
    for assignee in assignees:
        entry = _task_import_preview_recipient_entry(assignee, unit_lookup=unit_lookup, role_lookup=role_lookup)
        entry["delivery_labels"] = [scope_summary["text"]]
        submission_group = _task_import_preview_submission_group_info(
            config.get("assign_type"),
            assignee,
            role_lookup=role_lookup,
            unit_lookup=unit_lookup,
        )
        entry["submission_group_key"] = submission_group["group_key"]
        entry["submission_group_label"] = submission_group["group_label"]
        entry["submission_mode_label"] = submission_group["mode_label"]
        if narrative_cfg["enabled"] and _task_report_item_visible_for_user(narrative_cfg, assignee):
            target_summary = _task_import_scope_summary(
                narrative_cfg.get("target_type") or "all",
                unit_domains=narrative_cfg.get("target_unit_domains") or [],
                role_ids=narrative_cfg.get("target_role_ids") or [],
                user_ids=narrative_cfg.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["file_sections"].append(
                {
                    "label": narrative_cfg["label"] or "Báo cáo lời tổng hợp",
                    "kind": "narrative",
                    "kind_label": "Báo cáo lời",
                    "type_label": "Đoạn văn",
                    "required": bool(narrative_cfg["required"]),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": 0,
                }
            )
        if attachment_cfg["enabled"] and _task_report_item_visible_for_user(attachment_cfg, assignee):
            target_summary = _task_import_scope_summary(
                attachment_cfg.get("target_type") or "all",
                unit_domains=attachment_cfg.get("target_unit_domains") or [],
                role_ids=attachment_cfg.get("target_role_ids") or [],
                user_ids=attachment_cfg.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["file_sections"].append(
                {
                    "label": attachment_cfg["label"] or "Tệp minh chứng",
                    "kind": "attachment",
                    "kind_label": "Minh chứng",
                    "type_label": "Tệp đính kèm",
                    "required": bool(attachment_cfg["required"]),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": 1,
                }
            )
        for index, field in enumerate(report_fields, start=2):
            field_config = {
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
            }
            if not _task_report_item_visible_for_user(field_config, assignee):
                continue
            target_summary = _task_import_scope_summary(
                field.get("target_type") or "all",
                unit_domains=field.get("target_unit_domains") or [],
                role_ids=field.get("target_role_ids") or [],
                user_ids=field.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["file_sections"].append(
                {
                    "label": str(field.get("label") or "").strip(),
                    "kind": "field",
                    "kind_label": "Chỉ tiêu",
                    "type_label": TASK_IMPORT_FIELD_TYPE_LABELS.get(str(field.get("type") or "text").strip().lower(), "Văn bản"),
                    "required": bool(field.get("required")),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": int(field.get("sort_order") or index),
                }
            )
        entry["file_sections"].sort(key=lambda item: (item["sort_order"], remove_accents(item["label"]).lower()))
        entry["section_count"] = len(entry["file_sections"])
        if not entry["section_count"]:
            entry["warnings"].append("Người nhận này được giao nhiệm vụ nhưng hiện chưa thấy phần báo cáo nào.")
        cards.append(entry)

    cards.sort(key=lambda item: (remove_accents(item["unit_name"]).lower(), remove_accents(item["user_name"]).lower()))
    if not narrative_cfg["enabled"] and not attachment_cfg["enabled"] and not report_fields:
        warnings.append({"scope": "Schema báo cáo", "message": "Chưa có nội dung báo cáo hợp lệ để phát hành."})
    return {
        "mode": "file",
        "recipient_count": len(cards),
        "cards": cards,
        "warnings": warnings,
        "global_delivery_text": scope_summary["text"],
        "unit_groups": _task_import_preview_unit_groups("file", cards),
        "submission_groups": _task_import_preview_submission_groups("file", cards),
    }

def _task_import_recipient_preview(config, users=None, roles=None):
    config = config or {}
    active_users = list(users or [])
    role_rows = list(roles or [])
    unit_lookup = {
        str(item.get("value") or "").strip(): str(item.get("name") or item.get("label") or item.get("value") or "").strip()
        for item in stable_form_category_options(_task_domain_options())
        if str(item.get("value") or "").strip()
    }
    role_lookup = {
        int(role.id): str(role.name or f"Vai trò {role.id}").strip()
        for role in role_rows
        if getattr(role, "id", None)
    }
    user_lookup = {
        int(user.id): str(getattr(user, "fullname", None) or getattr(user, "username", None) or f"User {user.id}").strip()
        for user in active_users
        if getattr(user, "id", None)
    }
    mode = str(config.get("collection_mode") or "").strip().lower()
    if mode == "outline":
        return _task_import_outline_recipient_preview(config, unit_lookup=unit_lookup, role_lookup=role_lookup, user_lookup=user_lookup)
    if mode == "form":
        return _task_import_form_recipient_preview(config, unit_lookup=unit_lookup, role_lookup=role_lookup, user_lookup=user_lookup)
    return _task_import_file_recipient_preview(config, unit_lookup=unit_lookup, role_lookup=role_lookup, user_lookup=user_lookup)

def _task_import_form_visible_fields_for_user(config, user):
    ignored_labels = {
        remove_accents(str(label or "")).strip().lower()
        for label in (config.get("validation_ignored_form_field_labels") or [])
        if str(label or "").strip()
    }
    visible_fields = []
    for field in (config.get("form_fields") or []):
        label = str(field.get("field_label") or "").strip()
        if not label:
            continue
        if remove_accents(label).strip().lower() in ignored_labels:
            continue
        field_config = {
            "target_type": field.get("target_type") or "all",
            "target_unit_domains": field.get("target_unit_domains") or [],
            "target_role_ids": field.get("target_role_ids") or [],
            "target_user_ids": field.get("target_user_ids") or [],
        }
        if _task_report_item_visible_for_user(field_config, user):
            visible_fields.append(label)
    return visible_fields

def _task_import_file_visible_sections_for_user(config, user):
    sections = []
    if bool(config.get("report_narrative_enabled", True)):
        narrative_config = {
            "target_type": config.get("report_narrative_target_type") or "all",
            "target_unit_domains": config.get("report_narrative_unit_domains") or [],
            "target_role_ids": config.get("report_narrative_role_ids") or [],
            "target_user_ids": config.get("report_narrative_user_ids") or [],
        }
        if _task_report_item_visible_for_user(narrative_config, user):
            sections.append(str(config.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip())
    if bool(config.get("report_attachment_enabled")):
        attachment_config = {
            "target_type": config.get("report_attachment_target_type") or "all",
            "target_unit_domains": config.get("report_attachment_unit_domains") or [],
            "target_role_ids": config.get("report_attachment_role_ids") or [],
            "target_user_ids": config.get("report_attachment_user_ids") or [],
        }
        if _task_report_item_visible_for_user(attachment_config, user):
            sections.append(str(config.get("report_attachment_label") or "Tệp minh chứng").strip())
    for field in (config.get("report_fields") or []):
        label = str(field.get("label") or "").strip()
        if not label:
            continue
        field_config = {
            "target_type": field.get("target_type") or "all",
            "target_unit_domains": field.get("target_unit_domains") or [],
            "target_role_ids": field.get("target_role_ids") or [],
            "target_user_ids": field.get("target_user_ids") or [],
        }
        if _task_report_item_visible_for_user(field_config, user):
            sections.append(label)
    return sections

def _task_import_validate_publish_visibility(config, assignees):
    mode = str(config.get("collection_mode") or "").strip().lower()
    if mode not in {"form", "file"}:
        return
    empty_payload_users = []
    for assignee in assignees or []:
        if mode == "form":
            visible_payload = _task_import_form_visible_fields_for_user(config, assignee)
        else:
            visible_payload = _task_import_file_visible_sections_for_user(config, assignee)
        if not visible_payload:
            empty_payload_users.append(getattr(assignee, "fullname", None) or getattr(assignee, "username", None) or f"UID {getattr(assignee, 'id', '')}")
    if empty_payload_users:
        label = "trường biểu mẫu" if mode == "form" else "phần báo cáo"
        raise ValueError(
            f"Có {len(empty_payload_users)} người nhận chưa thấy {label} nào: {', '.join(empty_payload_users[:3])}. Hãy rà lại phạm vi giao việc trước khi phát hành."
        )

def _task_visibility_validation_config(task_mode, assign_type, domain="", role_ids=None, user_ids=None, field_defs=None, report_schema=None, ignored_form_field_labels=None):
    normalized_mode = str(task_mode or "").strip().upper()
    config = {
        "collection_mode": "form" if normalized_mode == "FORM" else "file",
        "assign_type": str(assign_type or "").strip().lower(),
        "domain": str(domain or "").strip(),
        "role_ids": list(role_ids or []),
        "user_ids": list(user_ids or []),
    }
    if normalized_mode == "FORM":
        form_fields = []
        for field_def in (field_defs or []):
            options_payload = _json_loads_safe(field_def.get("field_options_json"), {})
            target_config = _normalize_report_target_config(options_payload)
            form_fields.append(
                {
                    "field_key": str(field_def.get("field_key") or "").strip(),
                    "field_label": str(field_def.get("field_label") or "").strip(),
                    "field_type": str(field_def.get("field_type") or "text").strip().lower(),
                    "target_type": target_config.get("target_type") or "all",
                    "target_unit_domains": target_config.get("target_unit_domains") or [],
                    "target_role_ids": target_config.get("target_role_ids") or [],
                    "target_user_ids": target_config.get("target_user_ids") or [],
                }
            )
        config["form_fields"] = form_fields
        config["validation_ignored_form_field_labels"] = [
            str(label or "").strip()
            for label in (ignored_form_field_labels or [])
            if str(label or "").strip()
        ]
        return config

    schema = report_schema if isinstance(report_schema, dict) else {}
    narrative = schema.get("narrative") if isinstance(schema.get("narrative"), dict) else {}
    attachment = schema.get("attachment") if isinstance(schema.get("attachment"), dict) else {}
    config.update(
        {
            "report_narrative_enabled": bool(narrative.get("enabled", True)),
            "report_narrative_required": bool(narrative.get("required", True)),
            "report_narrative_label": str(narrative.get("label") or "Báo cáo lời tổng hợp").strip(),
            "report_narrative_target_type": str(narrative.get("target_type") or "all").strip().lower() or "all",
            "report_narrative_unit_domains": list(narrative.get("target_unit_domains") or []),
            "report_narrative_role_ids": list(narrative.get("target_role_ids") or []),
            "report_narrative_user_ids": list(narrative.get("target_user_ids") or []),
            "report_attachment_enabled": bool(attachment.get("enabled")),
            "report_attachment_required": bool(attachment.get("required")),
            "report_attachment_label": str(attachment.get("label") or "Tệp minh chứng").strip(),
            "report_attachment_target_type": str(attachment.get("target_type") or "all").strip().lower() or "all",
            "report_attachment_unit_domains": list(attachment.get("target_unit_domains") or []),
            "report_attachment_role_ids": list(attachment.get("target_role_ids") or []),
            "report_attachment_user_ids": list(attachment.get("target_user_ids") or []),
            "report_fields": [],
        }
    )
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict):
            continue
        config["report_fields"].append(
            {
                "key": str(field.get("key") or "").strip(),
                "label": str(field.get("label") or "").strip(),
                "type": str(field.get("type") or "text").strip().lower(),
                "required": bool(field.get("required")),
                "target_type": str(field.get("target_type") or "all").strip().lower() or "all",
                "target_unit_domains": list(field.get("target_unit_domains") or []),
                "target_role_ids": list(field.get("target_role_ids") or []),
                "target_user_ids": list(field.get("target_user_ids") or []),
            }
        )
    return config

def _validate_task_visibility_before_publish(task_mode, assignees, *, assign_type="", domain="", role_ids=None, user_ids=None, field_defs=None, report_schema=None, ignored_form_field_labels=None):
    normalized_mode = str(task_mode or "").strip().upper()
    if normalized_mode not in {"FORM", "FILE"}:
        return
    config = _task_visibility_validation_config(
        normalized_mode,
        assign_type,
        domain=domain,
        role_ids=role_ids,
        user_ids=user_ids,
        field_defs=field_defs,
        report_schema=report_schema,
        ignored_form_field_labels=ignored_form_field_labels,
    )
    _task_import_validate_publish_visibility(config, assignees)

def _task_assignment_scope_lists(task):
    scope = _load_assignment_scope(task)
    return {
        "assign_type": str(scope.get("mode") or getattr(task, "assign_type", None) or "").strip().lower(),
        "domain": str(scope.get("domain") or getattr(task, "domain", "") or "").strip(),
        "role_ids": list(scope.get("role_ids") or []),
        "user_ids": list(scope.get("user_ids") or []),
    }

def _task_import_publish_payload(config):
    collection_mode = str(config.get("collection_mode") or "").strip().lower()
    title = str(config.get("title") or "").strip()
    if not title:
        raise ValueError("Tiêu đề nhiệm vụ không được để trống.")

    domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    payload = {
        "title": title[:255],
        "content": _task_import_summary_text(config)[:4000],
        "category": canonicalize_category_value(config.get("category") or "", _task_field_options(), prefer_stable=True),
        "domain": domain,
        "priority": canonicalize_category_value(config.get("priority") or "Trung bình", _task_priority_options(), prefer_stable=True),
        "task_type": canonicalize_category_value(config.get("task_type") or "Công việc thường xuyên", _task_type_options(), prefer_stable=True),
        "deadline": _parse_deadline(MultiDict([("deadline", config.get("deadline") or "")])),
        "report_period_json": None,
        "assign_type": _task_import_working_assign_type(config.get("assign_type"), "unit"),
        "unit_domains": _requested_unit_domains(
            MultiDict([("child_domains", value) for value in (config.get("unit_domains") or [])] + ([("child_domain", domain)] if domain else []))
        ),
        "role_ids": sorted({int(role_id) for role_id in (config.get("role_ids") or []) if str(role_id).isdigit()}),
        "user_ids": sorted({int(user_id) for user_id in (config.get("user_ids") or []) if str(user_id).isdigit()}),
        "manager_scope_mode": str(config.get("manager_scope_mode") or "none").strip().lower(),
        "manager_role_ids": sorted({int(role_id) for role_id in (config.get("manager_role_ids") or []) if str(role_id).isdigit()}),
        "manager_user_ids": sorted({int(user_id) for user_id in (config.get("manager_user_ids") or []) if str(user_id).isdigit()}),
        "viewer_scope_mode": str(config.get("viewer_scope_mode") or "none").strip().lower(),
        "viewer_role_ids": sorted({int(role_id) for role_id in (config.get("viewer_role_ids") or []) if str(role_id).isdigit()}),
        "viewer_user_ids": sorted({int(user_id) for user_id in (config.get("viewer_user_ids") or []) if str(user_id).isdigit()}),
        "collection_mode": collection_mode,
        "task_mode": workflow_blueprint_task_mode({"version": 1, "collection_mode": collection_mode, "items": [], "form_fields": [], "report_schema": None}),
        "outline_items": [],
        "form_fields": [],
        "report_schema": None,
        "assignees": [],
    }

    try:
        report_period = report_parse_config(
            {
                "task_type": payload["task_type"],
                "report_deadline": config.get("deadline") or "",
                "report_period_kind": config.get("report_period_kind") or "",
                "report_period": config.get("report_period") or "",
                "report_weekday": config.get("report_weekday") or "",
                "report_day_of_month": config.get("report_day_of_month") or "",
                "report_month_of_year": config.get("report_month_of_year") or "",
                "report_start_date": config.get("report_start_date") or "",
                "report_end_date": config.get("report_end_date") or "",
                "report_milestones": config.get("report_milestones") or [],
            }
        )
        if report_period:
            payload["report_period_json"] = report_config_to_json(report_period)
    except Exception:
        payload["report_period_json"] = None

    manager_form = MultiDict(
        [("manager_scope_mode", payload["manager_scope_mode"])]
        + [("manager_role_ids", str(role_id)) for role_id in payload["manager_role_ids"]]
        + [("manager_user_ids", str(user_id)) for user_id in payload["manager_user_ids"]]
    )
    viewers_form = MultiDict(
        [("viewer_scope_mode", payload["viewer_scope_mode"])]
        + [("viewer_role_ids", str(role_id)) for role_id in payload["viewer_role_ids"]]
        + [("viewer_user_ids", str(user_id)) for user_id in payload["viewer_user_ids"]]
    )
    managers, manager_error = _resolve_managers(manager_form)
    if manager_error:
        raise ValueError(manager_error)
    viewers, viewer_error = _resolve_viewers(viewers_form)
    if viewer_error:
        raise ValueError(viewer_error)
    payload["managers"] = managers
    payload["viewers"] = viewers

    if collection_mode == "outline":
        payload["task_mode"] = "OUTLINE"
        items = []
        raw_items = config.get("items") or []
        if not raw_items:
            raise ValueError("Cần ít nhất một đầu mục trước khi phát hành.")
        all_assignees = []
        for index, item in enumerate(raw_items, start=1):
            title_item = _clean_outline_title(item.get("title"))
            if not title_item:
                continue
            assign_type = _task_import_working_assign_type(item.get("assign_type"))
            if assign_type not in {"unit", "role", "user"}:
                raise ValueError(f'Nội dung "{title_item}" chưa chọn kiểu giao việc.')
            unit_domains = _requested_unit_domains(
                MultiDict([("child_domains", value) for value in (item.get("unit_domains") or [])] + ([("child_domain", domain)] if domain else []))
            )
            role_ids = sorted({int(role_id) for role_id in (item.get("role_ids") or []) if str(role_id).isdigit()})
            user_ids = sorted({int(user_id) for user_id in (item.get("user_ids") or []) if str(user_id).isdigit()})
            if assign_type == "unit" and not unit_domains and domain:
                unit_domains = [domain]
            assignees, error_message = _resolve_assignees_by_mode(
                assign_type,
                domain=domain,
                unit_domains=unit_domains,
                target_ids=user_ids,
                assignee_role_ids=role_ids,
            )
            if error_message:
                raise ValueError(f'Nội dung "{title_item}": {error_message}')
            if not assignees:
                raise ValueError(f'Nội dung "{title_item}" chưa có người thực hiện.')
            report_kind = str(item.get("report_kind") or "narrative").strip().lower()
            if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
                report_kind = "narrative"
            items.append(
                {
                    "title": title_item[:255],
                    "guide_text": str(item.get("guide_text") or "").strip()[:2000],
                    "report_kind": report_kind,
                    "attachment_required": bool(item.get("attachment_required")),
                    "assign_type": assign_type,
                    "unit_domains": unit_domains,
                    "role_ids": role_ids,
                    "user_ids": user_ids,
                    "assignees": assignees,
                    "sort_order": len(items),
                }
            )
            all_assignees.extend(assignees)
        if not items:
            raise ValueError("Cần ít nhất một đầu mục hợp lệ trước khi phát hành.")
        payload["outline_items"] = items
        payload["assignees"] = _dedupe_users(all_assignees)
        return payload

    if collection_mode == "form":
        payload["task_mode"] = "FORM"
        assignees, error_message = _resolve_assignees_by_mode(
            payload["assign_type"],
            domain=domain,
            unit_domains=payload["unit_domains"],
            target_ids=payload["user_ids"],
            assignee_role_ids=payload["role_ids"],
        )
        if error_message:
            raise ValueError(error_message)
        field_defs = _task_import_form_field_defs_from_config(config)
        if not field_defs:
            raise ValueError("Cần ít nhất một trường biểu mẫu trước khi phát hành.")
        _task_import_validate_publish_visibility(config, assignees)
        payload["assignees"] = assignees
        payload["form_fields"] = field_defs
        return payload

    payload["task_mode"] = "FILE"
    assignees, error_message = _resolve_assignees_by_mode(
        payload["assign_type"],
        domain=domain,
        unit_domains=payload["unit_domains"],
        target_ids=payload["user_ids"],
        assignee_role_ids=payload["role_ids"],
    )
    if error_message:
        raise ValueError(error_message)
    report_schema = _task_import_report_schema_from_config(config)
    if not report_schema:
        raise ValueError("Biểu mẫu báo cáo chưa có nội dung hợp lệ.")
    _task_import_validate_publish_visibility(config, assignees)
    payload["assignees"] = assignees
    payload["report_schema"] = report_schema
    return payload

def _publish_task_import_draft(draft):
    config = _task_import_draft_working_config(draft)
    payload = _task_import_publish_payload(config)

    new_task = Task(
        category=payload["category"],
        domain=payload["domain"],
        title=payload["title"],
        content=payload["content"],
        deadline=payload["deadline"],
        file_path="",
        author_id=session["uid"],
        author_name=session.get("fullname", "Quản trị"),
        priority=payload["priority"],
        task_type=payload["task_type"],
        initial_status="Chưa tiếp nhận",
        task_mode=payload["task_mode"],
    )
    if payload.get("report_period_json"):
        new_task.report_period_json = payload["report_period_json"]
    if payload["report_schema"]:
        new_task.report_schema_json = _json_dump(payload["report_schema"])

    _store_assignment_scope(
        new_task,
        payload["assign_type"],
        domain=payload["domain"],
        role_ids=payload["role_ids"],
        user_ids=payload["user_ids"],
    )
    _store_viewer_scope(
        new_task,
        payload["viewer_scope_mode"],
        role_ids=payload["viewer_role_ids"],
        user_ids=payload["viewer_user_ids"],
    )
    _store_manager_scope(
        new_task,
        payload["manager_scope_mode"],
        role_ids=payload["manager_role_ids"],
        user_ids=payload["manager_user_ids"],
    )
    db.session.add(new_task)
    db.session.flush()

    if payload["task_mode"] == "OUTLINE":
        for index, item in enumerate(payload["outline_items"], start=1):
            item_content = str(item.get("content") or "").strip()
            number_fields = item.get("number_fields") or []
            guide_text = item.get("guide_text")
            if number_fields and not guide_text:
                try:
                    guide_text = json.dumps(number_fields, ensure_ascii=False)
                except Exception:
                    guide_text = None
            sources = item.get("sources") or []
            report_sources_json = None
            if sources:
                try:
                    report_sources_json = json.dumps(sources, ensure_ascii=False)
                except Exception:
                    report_sources_json = None
            task_item = TaskItem(
                task_id=new_task.id,
                item_code=str(index),
                title=item["title"],
                content=item_content or None,
                guide_text=guide_text,
                is_required=True,
                output_type="OUTLINE",
                report_kind=item["report_kind"],
                attachment_required=bool(item["attachment_required"]),
                deadline=new_task.deadline,
                sort_order=item.get("sort_order", index - 1),
                report_sources_json=report_sources_json,
            )
            db.session.add(task_item)
            db.session.flush()
            table_cells = item.get("table_cells") or {}
            if table_cells:
                task_item.table_cells_json = _json_dump(table_cells)
                schema = item.get("table_schema")
                if schema and not new_task.outline_table_schema_json:
                    new_task.outline_table_schema_json = _json_dump(schema)
            if item.get("report_secondary") and item_content:
                linked_item = _find_report_secondary_linked_item(item_content, item.get("unit_domains") or [], new_task.id)
                if linked_item:
                    task_item.linked_item_id = linked_item.id
            _create_assignment_records(
                new_task,
                item["assignees"],
                assign_type=item["assign_type"],
                task_item=task_item,
                title_snapshot=task_item.title,
                role_id=item["role_ids"][0] if len(item["role_ids"]) == 1 else None,
            )
    else:
        _create_assignment_records(
            new_task,
            payload["assignees"],
            assign_type=payload["assign_type"],
            title_snapshot=new_task.title,
            role_id=payload["role_ids"][0] if len(payload["role_ids"]) == 1 else None,
        )
        if payload["task_mode"] == "FORM":
            for field_def in payload["form_fields"]:
                db.session.add(TaskFormField(task_id=new_task.id, **_task_form_field_db_kwargs(field_def)))

    draft.status = "published"
    draft.published_task_id = new_task.id
    draft.published_at = datetime.now()
    draft.updated_at = datetime.now()
    db.session.add(draft)
    db.session.commit()

    assignees = _dedupe_users(payload["assignees"])
    for user in assignees:
        push_notif(user.id, "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")
    # Gửi email kèm cho người được giao (tự bỏ qua nếu MAIL_* chưa cấu hình
    # hoặc user không khai báo email) — song song với thông báo trong app.
    try:
        base_url = f"{request.scheme}://{request.host}"
        send_task_assignment_emails(assignees, new_task, base_url=base_url)
    except Exception as email_error:
        logger.warning(f"Task wizard assignment emails failed: {email_error}")
    return new_task
