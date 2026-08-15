# -*- coding: utf-8 -*-
"""
Cụm helper dựng màn làm việc theo hình thái: chi tiết task, đọc/tái hiện bảng đề cương,
dòng đầu mục đề cương (kèm submission/người nhận), cấu hình đầu mục + trường biểu mẫu
từ request/session, nhận diện nhóm đề cương và các dòng file/form.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py re-export các tên còn dùng.
"""

import html
import json
import re

from flask import session
from werkzeug.datastructures import MultiDict
from werkzeug.utils import secure_filename

from task_read_models import (
    build_file_task_rows,
    build_form_task_rows,
    build_outline_group_rows,
    outline_group_identity,
    task_form_field_views,
    task_form_submission_payload,
    task_form_value_is_empty,
)
from task_workspace import build_task_detail_context
from utils import remove_accents

from services.outline_engine import _clean_outline_title, _extract_number_fields_from_text
from services.outline_submission import (
    _parse_task_submission_payload,
    _render_blank_editor_html,
)
from services.task_assignees import _resolve_assignees, _resolve_assignees_by_mode
from services.task_form_fields import (
    _form_field_options,
    _normalize_task_form_field_type,
    _task_form_fields,
    _task_form_fields_for_user,
)
from services.task_import_draft_helpers import (
    _task_import_form_field_options_json,
    _task_import_parse_id_csv,
)
from services.task_modes import TASK_ASSIGNMENT_STATUS_LABELS, _normalize_status
from services.task_report_schema import (
    CHILD_TASK_ALLOWED_REPORT_KINDS,
    _load_task_report_schema,
    _normalize_report_target_config,
    _task_report_item_visible_for_user,
)
from services.task_runtime_sync import _latest_assignment_submission
from services.task_scope import _requested_role_ids, _requested_unit_domains
from services.task_units import _task_assignee_unit_name
from services.task_workspace_helpers import (
    _task_assignments_query,
    _task_is_submitted,
    _task_items_for_task,
)

def _task_detail_context(task, summary, mode, can_manage_task_view, can_submit, my_file_assignment=None, my_form_assignment=None, outline_groups=None):
    return build_task_detail_context(
        task,
        summary,
        mode,
        can_manage_task_view,
        can_submit,
        TASK_ASSIGNMENT_STATUS_LABELS,
        _normalize_status,
        my_file_assignment=my_file_assignment,
        my_form_assignment=my_form_assignment,
        outline_groups=outline_groups,
    )

def _outline_table_schema_map(task):
    """Đọc cấu trúc cột bảng của task (đã lưu khi tạo từ đề cương dạng bảng)."""
    if not task:
        return None
    raw = str(getattr(task, "outline_table_schema_json", "") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, list):
        return None
    schema_map = {}
    for col in parsed:
        if not isinstance(col, dict):
            continue
        index_value = col.get("index")
        if index_value is not None:
            schema_map[str(index_value)] = col
    return schema_map or None


def _outline_item_table_cells(item):
    """Đọc ô dữ liệu theo cột của đầu mục (nếu đầu mục được tạo từ bảng)."""
    if not item:
        return {}
    raw = str(getattr(item, "table_cells_json", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _render_outline_table_html(schema_map, cells, fallback_content=""):
    """Dựng bảng tái hiện (chỉ các cột được tích hiển thị) cho tài khoản đơn vị nhận.

    schema_map: {chỉ_số_cột: {index, header, role, visible}} từ task.
    cells: {chỉ_số_cột: giá trị} của đầu mục.
    """
    if not schema_map or not cells:
        return ""
    columns = sorted(schema_map.values(), key=lambda col: int(col.get("index") or 0))
    columns = [col for col in columns if col.get("visible")]
    if not columns:
        return ""
    header_cells = "".join(
        f"<th class='text-nowrap'>{html.escape(str(col.get('header') or ''))}</th>" for col in columns
    )
    body_cells = []
    for col in columns:
        value = str(cells.get(str(col.get("index")), "") or "").strip()
        if not value and col.get("role") == "content":
            value = str(fallback_content or "").strip()
        body_cells.append(f"<td>{html.escape(value)}</td>")
    return (
        "<div class='table-responsive'><table class='table table-sm table-bordered outline-table-render mb-0'>"
        f"<thead><tr>{header_cells}</tr></thead><tbody><tr>{''.join(body_cells)}</tr></tbody></table></div>"
    )


def _parse_outline_item_rows(task, current_uid):
    rows = []
    for item in _task_items_for_task(task):
        assignments = _task_assignments_query(task, task_item_id=item.id).all()
        my_assignment = next((assignment for assignment in assignments if assignment.user_id == current_uid), None)
        latest_submissions = {
            assignment.id: _latest_assignment_submission(assignment)
            for assignment in assignments
        }
        secondary_text = ""
        for candidate in [getattr(item, "guide_text", None), getattr(item, "content", None)]:
            candidate_text = str(candidate or "").strip()
            if not candidate_text:
                continue
            if candidate_text.startswith("{") or candidate_text.startswith("["):
                # guide_text dạng JSON (trường số liệu) — không hiển thị thô
                continue
            if re.sub(r"\s+", " ", candidate_text).strip().lower() == re.sub(r"\s+", " ", str(item.title or "")).strip().lower():
                continue
            secondary_text = candidate_text
            break
        my_submission = latest_submissions.get(getattr(my_assignment, "id", None))
        number_fields = _outline_item_number_fields(item)
        my_submission_payload = _parse_task_submission_payload(my_submission) if my_submission else {}
        values = my_submission_payload.get("values") if isinstance(my_submission_payload, dict) else None
        if not isinstance(values, dict):
            values = {}
        content = str(getattr(item, "content", "") or "")
        table_cells = _outline_item_table_cells(item)
        table_render_html = ""
        if table_cells:
            table_render_html = _render_outline_table_html(_outline_table_schema_map(task), table_cells, content)
        if table_render_html:
            # Bảng đã tái hiện đầy đủ các cột -> không lặp lại nội dung gộp ở secondary_text
            secondary_text = ""
        rows.append(
            {
                "item": item,
                "assignments": assignments,
                "my_assignment": my_assignment,
                "my_submission": my_submission,
                "my_submission_payload": my_submission_payload,
                "number_fields": number_fields,
                "blank_editor_html": _render_blank_editor_html(content, number_fields, values) if item.report_kind == "number" else "",
                "submitted_count": sum(1 for assignment in assignments if _task_is_submitted(assignment)),
                "total_count": len(assignments),
                "latest_submissions": latest_submissions,
                "secondary_text": secondary_text,
                "table_render_html": table_render_html,
            }
        )
    return rows

def _task_item_synthesis_text(item):
    """Văn bản tổng hợp của đầu mục (quản trị soạn) — rỗng nếu chưa tổng hợp."""
    if not item:
        return ""
    return str(getattr(item, "synthesis_content", None) or "").strip()


def _outline_item_number_fields(item):
    """Lấy danh sách trường số liệu của đầu mục (từ guide_text JSON, hoặc dò lại từ nội dung)."""
    if not item:
        return []
    guide = str(getattr(item, "guide_text", "") or "").strip()
    if guide:
        try:
            parsed = json.loads(guide)
            if isinstance(parsed, dict):
                fields = parsed.get("fields") or []
            elif isinstance(parsed, list):
                fields = parsed
            else:
                fields = []
            fields = [
                f for f in fields
                if isinstance(f, dict) and str(f.get("label") or "").strip()
            ]
            if fields:
                return fields
        except Exception:
            pass
    return _extract_number_fields_from_text(str(getattr(item, "content", "") or ""))

def _parse_outline_item_configs_from_request(form):
    titles = form.getlist("item_title")
    contents = form.getlist("item_content")
    number_fields_values = form.getlist("item_number_fields")
    report_kinds = form.getlist("item_report_kind")
    enabled_indexes = {value for value in form.getlist("item_enabled")}
    attachment_indexes = {value for value in form.getlist("item_attachment_required")}
    assign_types = form.getlist("item_assign_type")
    domains = form.getlist("item_domain")
    domains_values = form.getlist("item_domains")
    role_ids_values = form.getlist("item_role_ids")
    user_ids_values = form.getlist("item_user_ids")
    parent_values = form.getlist("item_parent")
    inherit_values = form.getlist("item_inherit")
    report_secondary_values = form.getlist("item_report_secondary")
    sources_values = form.getlist("item_sources")
    heading_values = form.getlist("item_heading")
    table_cells_values = form.getlist("item_table_cells")
    table_schema = []
    try:
        raw_schema = str(form.get("item_table_schema") or "").strip()
        if raw_schema:
            parsed_schema = json.loads(raw_schema)
            if isinstance(parsed_schema, list):
                table_schema = [
                    {
                        "index": int(col.get("index", 0)),
                        "header": str(col.get("header") or "")[:200],
                        "role": str(col.get("role") or "other").strip() or "other",
                        "visible": bool(col.get("visible")),
                    }
                    for col in parsed_schema
                    if isinstance(col, dict)
                ]
    except Exception:
        table_schema = []
    configs = []
    seen = set()

    for index, raw_title in enumerate(titles):
        if enabled_indexes and str(index) not in enabled_indexes:
            continue
        # Giữ số hiệu mục (vd: "1.1. Các Sở...") để các mục cùng tên ở phần khác
        # nhau của đề cương không bị gộp nhầm; chỉ bỏ dấu đầu dòng nếu có.
        cleaned_title = re.sub(r"^\s*(?:[-–—•*+]\s*|\+\s*)\s*", "", str(raw_title or "").strip())
        cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip(" .:")
        if not cleaned_title:
            continue
        # Với dòng bullet, các mục con cùng tên có thể lặp lại ở nhiều mục khác
        # nhau trong đề cương -> khử trùng theo (heading, title) chứ không theo title.
        raw_parent = str(parent_values[index] if index < len(parent_values) else "").strip()
        raw_heading = str(heading_values[index] if index < len(heading_values) else "").strip()
        dedupe_key = (cleaned_title.lower(), raw_heading.lower(), raw_parent)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        report_kind = str(report_kinds[index] if index < len(report_kinds) else "narrative").strip().lower()
        if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
            report_kind = "narrative"
        assign_type = str(assign_types[index] if index < len(assign_types) else "").strip().lower()
        if assign_type not in {"unit", "role", "user"}:
            assign_type = ""
        domain = str(domains[index] if index < len(domains) else "").strip()
        raw_unit_domains = str(domains_values[index] if index < len(domains_values) else "").strip()
        raw_role_ids = str(role_ids_values[index] if index < len(role_ids_values) else "").strip()
        raw_user_ids = str(user_ids_values[index] if index < len(user_ids_values) else "").strip()
        unit_domains = _requested_unit_domains(
            MultiDict([("child_domains", value.strip()) for value in raw_unit_domains.split(",") if value.strip()] + ([("child_domain", domain)] if domain else []))
        )
        content_text = str(contents[index] if index < len(contents) else "").strip()
        raw_number_fields = str(number_fields_values[index] if index < len(number_fields_values) else "").strip()
        try:
            number_fields = json.loads(raw_number_fields) if raw_number_fields else []
        except Exception:
            number_fields = []
        raw_table_cells = str(table_cells_values[index] if index < len(table_cells_values) else "").strip()
        try:
            table_cells = json.loads(raw_table_cells) if raw_table_cells else {}
            if not isinstance(table_cells, dict):
                table_cells = {}
        except Exception:
            table_cells = {}
        parent_index = int(raw_parent) if raw_parent.isdigit() else None
        configs.append(
            {
                "form_index": index,
                "title": cleaned_title[:255],
                "content": content_text[:3000],
                "report_kind": report_kind,
                "number_fields": number_fields,
                "attachment_required": str(index) in attachment_indexes,
                "assign_type": assign_type,
                "domain": domain[:255],
                "unit_domains": unit_domains,
                "role_ids": sorted({int(value) for value in raw_role_ids.split(",") if value.strip().isdigit()}),
                "user_ids": sorted({int(value) for value in raw_user_ids.split(",") if value.strip().isdigit()}),
                "parent_index": parent_index,
                "inherit": str(index) in inherit_values,
                "report_secondary": (
                    index < len(report_secondary_values)
                    and str(report_secondary_values[index]).strip() == "1"
                ),
                "sources": [
                    source.strip()
                    for source in str(sources_values[index] if index < len(sources_values) else "").split(",")
                    if source.strip()
                ],
                "table_schema": table_schema if table_cells else [],
                "table_cells": table_cells,
            }
        )
    return configs

def _outline_import_preview_session_key(task_id):
    current_uid = int(session.get("uid") or 0)
    return f"task:outline_import_preview:{int(task_id)}:{current_uid}"

def _get_outline_import_preview(task_id):
    raw_value = session.get(_outline_import_preview_session_key(task_id))
    if not isinstance(raw_value, list):
        return []
    rows = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        title = _clean_outline_title(item.get("title"))
        if not title:
            continue
        report_kind = str(item.get("report_kind") or "narrative").strip().lower()
        if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
            report_kind = "narrative"
        assign_type = str(item.get("assign_type") or "").strip().lower()
        if assign_type not in {"unit", "role", "user"}:
            assign_type = ""
        rows.append(
            {
                "title": title[:255],
                "content": str(item.get("content") or "").strip()[:3000],
                "heading": str(item.get("heading") or "").strip()[:255],
                "parent_row_index": item.get("parent_row_index"),
                "report_kind": report_kind,
                "attachment_required": bool(item.get("attachment_required")),
                "assign_type": assign_type,
                "domain": str(item.get("domain") or "").strip()[:255],
                "unit_domains": _requested_unit_domains(
                    MultiDict([("child_domains", value) for value in (item.get("unit_domains") or [])] + ([("child_domain", item.get("domain"))] if item.get("domain") else []))
                ),
                "role_ids": sorted({int(role_id) for role_id in (item.get("role_ids") or []) if str(role_id).isdigit()}),
                "user_ids": sorted({int(user_id) for user_id in (item.get("user_ids") or []) if str(user_id).isdigit()}),
            }
        )
    return rows

def _set_outline_import_preview(task_id, rows):
    session[_outline_import_preview_session_key(task_id)] = rows
    session.modified = True

def _clear_outline_import_preview(task_id):
    session.pop(_outline_import_preview_session_key(task_id), None)
    session.modified = True

def _resolve_outline_item_assignment(item_config, form, parent_task):
    assign_type = str(item_config.get("assign_type") or "").strip().lower()
    unit_domains = _requested_unit_domains(
        MultiDict([("child_domains", value) for value in (item_config.get("unit_domains") or [])] + ([("child_domain", item_config.get("domain"))] if item_config.get("domain") else []))
    )
    role_ids = sorted({int(role_id) for role_id in (item_config.get("role_ids") or []) if str(role_id).isdigit()})
    user_ids = sorted({int(user_id) for user_id in (item_config.get("user_ids") or []) if str(user_id).isdigit()})
    domain = str(item_config.get("domain") or "").strip()

    if assign_type in {"unit", "role", "user"}:
        assignees, error_message = _resolve_assignees_by_mode(
            assign_type,
            domain=domain or parent_task.domain or "",
            unit_domains=unit_domains,
            target_ids=user_ids,
            assignee_role_ids=role_ids,
        )
        return assignees, error_message, assign_type, role_ids

    fallback_domain = (form.get("child_domain") or parent_task.domain or "").strip()
    assignees, error_message = _resolve_assignees(form, fallback_domain)
    selected_role_ids = _requested_role_ids(form)
    return assignees, error_message, form.get("assign_type", "unit"), selected_role_ids

def _outline_group_identity(assignments, fallback_index=0):
    return outline_group_identity(assignments, _task_assignee_unit_name, fallback_index=fallback_index)

def _build_outline_group_rows(task, current_uid):
    rows = _parse_outline_item_rows(task, current_uid)
    return build_outline_group_rows(rows, _outline_group_identity)

def _build_file_task_rows(task, current_uid):
    assignments = _task_assignments_query(task).all()
    return build_file_task_rows(assignments, current_uid, _latest_assignment_submission)

def _task_form_value_is_empty(value):
    return task_form_value_is_empty(value)

def _parse_task_form_fields_from_request(form):
    labels = form.getlist("form_field_label")
    field_types = form.getlist("form_field_type")
    required_indexes = {value for value in form.getlist("form_field_required")}
    options_values = form.getlist("form_field_options")
    target_types = form.getlist("form_field_target_type")
    unit_domains_values = form.getlist("form_field_target_unit_domains")
    role_ids_values = form.getlist("form_field_target_role_ids")
    user_ids_values = form.getlist("form_field_target_user_ids")
    fields = []
    for index, raw_label in enumerate(labels):
        label = (raw_label or "").strip()
        if not label:
            continue
        field_type = _normalize_task_form_field_type(field_types[index] if index < len(field_types) else "text")
        raw_options = (options_values[index] if index < len(options_values) else "").strip()
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
                "field_key": secure_filename(remove_accents(label).replace(" ", "_")) or f"field_{index+1}",
                "field_label": label,
                "field_type": field_type,
                "field_options_json": _task_import_form_field_options_json(field_type, raw_options, target_config),
                "sort_order": len(fields),
                "is_required": str(index) in required_indexes,
            }
        )
    return fields

# Pha 2: đọc/lọc trường biểu mẫu chuyển sang services/task_form_fields.py.

def _task_form_submission_payload(submission):
    return task_form_submission_payload(submission)

def _build_form_task_rows(task, current_uid):
    assignments = _task_assignments_query(task).all()
    fields = _task_form_fields(task)
    return build_form_task_rows(
        assignments,
        fields,
        current_uid,
        _latest_assignment_submission,
        _task_form_submission_payload,
    )

def _task_form_field_views(task):
    return task_form_field_views(_task_form_fields(task), _normalize_task_form_field_type, _form_field_options)

def _task_form_field_views_for_user(task, user):
    return task_form_field_views(_task_form_fields_for_user(task, user), _normalize_task_form_field_type, _form_field_options)

