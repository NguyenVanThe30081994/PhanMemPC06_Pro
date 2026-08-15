# -*- coding: utf-8 -*-
"""
Cụm helper dựng màn xem báo cáo task: hằng số điều kiện tiến độ/chất lượng task con,
dashboard báo cáo task con theo đơn vị, xem trước/tóm tắt giá trị báo cáo, dựng
biểu mẫu + ngữ cảnh báo cáo có cấu trúc và kiểm tra đầu vào nộp báo cáo file.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ.
"""

from datetime import datetime
from decimal import Decimal

from services.task_modes import _normalize_status
from services.task_report_schema import (
    _load_task_report_schema,
    _task_report_item_visible_for_user,
)
from services.task_runtime_sync import (
    _assignment_report_snapshot,
    _parse_report_number,
    _parse_structured_task_report_payload,
    _task_assignment_rows,
)
from services.task_units import _task_unit_identity


def _format_report_number(value):
    if value is None:
        return ""
    normalized = value.quantize(Decimal("1")) if value == value.to_integral() else value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text

CHILD_TASK_PROGRESS_CONDITIONS = (
    {
        "code": "reported_complete",
        "label": "Đã báo cáo",
        "description": "Hoàn thành báo cáo toàn bộ nhiệm vụ",
        "filename_suffix": "tien_do_da_bao_cao",
    },
    {
        "code": "reporting_in_progress",
        "label": "Đang báo cáo",
        "description": "Chưa hoàn thành toàn bộ nhiệm vụ",
        "filename_suffix": "tien_do_dang_bao_cao",
    },
    {
        "code": "not_reported",
        "label": "Chưa báo cáo",
        "description": "Chưa tiếp nhận",
        "filename_suffix": "tien_do_chua_bao_cao",
    },
)
CHILD_TASK_QUALITY_CONDITIONS = (
    {
        "code": "on_time",
        "label": "Đúng hạn",
        "description": "100% nhiệm vụ đúng hạn",
        "filename_suffix": "chat_luong_dung_han",
    },
    {
        "code": "partial_overdue",
        "label": "Quá hạn một phần",
        "description": "Một phần nhiệm vụ quá hạn",
        "filename_suffix": "chat_luong_qua_han_mot_phan",
    },
    {
        "code": "fully_overdue",
        "label": "Quá hạn báo cáo",
        "description": "100% nhiệm vụ quá hạn",
        "filename_suffix": "chat_luong_qua_han_bao_cao",
    },
)


def _child_task_condition_meta(dimension, code):
    catalog = CHILD_TASK_PROGRESS_CONDITIONS if dimension == "progress" else CHILD_TASK_QUALITY_CONDITIONS
    for item in catalog:
        if item["code"] == code:
            return item
    return None

def _build_child_task_report_dashboard(child_tasks):
    now_date = datetime.now().date()
    unit_rows = {}

    for child_task in child_tasks or []:
        assignment_rows = _task_assignment_rows(child_task, ensure_bridge=False)
        task_units = {}

        for assignment, user in assignment_rows:
            if not user:
                continue
            unit_identity = _task_unit_identity(user)
            unit_key = unit_identity.get("unit_key") or f"user_{user.id}"
            task_unit = task_units.setdefault(
                unit_key,
                {
                    "unit_key": unit_key,
                    "unit_name": unit_identity.get("unit_name") or getattr(user, "fullname", None) or f"UID {user.id}",
                    "accepted": False,
                    "reported": False,
                    "reported_at": None,
                },
            )

            normalized_status = _normalize_status(getattr(assignment, "status", ""))
            if normalized_status != "Chưa tiếp nhận":
                task_unit["accepted"] = True

            report_snapshot = _assignment_report_snapshot(assignment)
            if not report_snapshot.get("has_report"):
                continue
            report_time = report_snapshot.get("reported_at") or report_snapshot.get("first_report_at")
            if task_unit["reported_at"] is None or (report_time and report_time >= task_unit["reported_at"]):
                task_unit["reported"] = True
                task_unit["reported_at"] = report_time

        for task_unit in task_units.values():
            deadline = getattr(child_task, "deadline", None)
            is_overdue = False
            if deadline:
                if task_unit["reported"] and task_unit["reported_at"]:
                    is_overdue = task_unit["reported_at"].date() > deadline
                else:
                    is_overdue = deadline < now_date

            unit_row = unit_rows.setdefault(
                task_unit["unit_key"],
                {
                    "unit_key": task_unit["unit_key"],
                    "unit_name": task_unit["unit_name"],
                    "child_task_count": 0,
                    "accepted_count": 0,
                    "reported_count": 0,
                    "missing_count": 0,
                    "overdue_count": 0,
                    "on_time_count": 0,
                    "reported_items": [],
                    "missing_items": [],
                    "overdue_items": [],
                    "all_items": [],
                },
            )

            unit_row["child_task_count"] += 1
            if task_unit["accepted"]:
                unit_row["accepted_count"] += 1
            if task_unit["reported"]:
                unit_row["reported_count"] += 1
            else:
                unit_row["missing_count"] += 1
            if is_overdue:
                unit_row["overdue_count"] += 1
            else:
                unit_row["on_time_count"] += 1

            task_item = {
                "task_id": child_task.id,
                "task_title": child_task.title,
                "deadline": deadline,
                "accepted": task_unit["accepted"],
                "reported": task_unit["reported"],
                "reported_at": task_unit["reported_at"],
                "is_overdue": is_overdue,
            }
            unit_row["all_items"].append(task_item)
            if task_unit["reported"]:
                unit_row["reported_items"].append(task_item)
            else:
                unit_row["missing_items"].append(task_item)
            if is_overdue:
                unit_row["overdue_items"].append(task_item)

    unit_row_items = []
    for unit_row in unit_rows.values():
        total_count = unit_row["child_task_count"]
        if unit_row["reported_count"] == total_count and total_count > 0:
            unit_row["progress_code"] = "reported_complete"
        elif unit_row["accepted_count"] == 0:
            unit_row["progress_code"] = "not_reported"
        else:
            unit_row["progress_code"] = "reporting_in_progress"

        if unit_row["overdue_count"] == 0:
            unit_row["quality_code"] = "on_time"
        elif unit_row["overdue_count"] == total_count and total_count > 0:
            unit_row["quality_code"] = "fully_overdue"
        else:
            unit_row["quality_code"] = "partial_overdue"

        progress_meta = _child_task_condition_meta("progress", unit_row["progress_code"]) or {}
        quality_meta = _child_task_condition_meta("quality", unit_row["quality_code"]) or {}
        unit_row["progress_label"] = progress_meta.get("label", "")
        unit_row["progress_description"] = progress_meta.get("description", "")
        unit_row["quality_label"] = quality_meta.get("label", "")
        unit_row["quality_description"] = quality_meta.get("description", "")
        unit_row["reported_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row["missing_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row["overdue_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row["all_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row_items.append(unit_row)

    unit_row_items.sort(
        key=lambda item: (
            item["progress_code"] == "reported_complete",
            item["quality_code"] == "on_time",
            -item["missing_count"],
            -item["overdue_count"],
            item["unit_name"].lower(),
        )
    )

    progress_groups = []
    for item in CHILD_TASK_PROGRESS_CONDITIONS:
        matched_units = [unit_row for unit_row in unit_row_items if unit_row["progress_code"] == item["code"]]
        progress_groups.append({**item, "count": len(matched_units), "units": matched_units})

    quality_groups = []
    for item in CHILD_TASK_QUALITY_CONDITIONS:
        matched_units = [unit_row for unit_row in unit_row_items if unit_row["quality_code"] == item["code"]]
        quality_groups.append({**item, "count": len(matched_units), "units": matched_units})

    return {
        "total_units": len(unit_row_items),
        "total_child_tasks": sum(unit_row["child_task_count"] for unit_row in unit_row_items),
        "total_missing_tasks": sum(unit_row["missing_count"] for unit_row in unit_row_items),
        "total_overdue_tasks": sum(unit_row["overdue_count"] for unit_row in unit_row_items),
        "unit_rows": unit_row_items,
        "progress_groups": progress_groups,
        "quality_groups": quality_groups,
        "child_task_count_by_unit": {
            unit_row["unit_key"]: unit_row["child_task_count"]
            for unit_row in unit_row_items
        },
    }

def _task_report_value_preview(value, limit=120):
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"

def _structured_task_report_summary_lines(schema, payload, limit=4):
    if not schema or not payload:
        return []

    lines = []
    narrative_text = str(payload.get("narrative") or "").strip()
    if narrative_text:
        label = (schema.get("narrative") or {}).get("label") or "Báo cáo lời"
        lines.append(f"{label}: {_task_report_value_preview(narrative_text, 160)}")

    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    for field in schema.get("fields", []):
        value = str(values.get(field.get("key")) or "").strip()
        if not value:
            continue
        lines.append(f"{field.get('label')}: {_task_report_value_preview(value, 120)}")
        if len(lines) >= limit:
            break

    return lines[:limit]

def _build_structured_task_report_comment(schema, payload):
    summary_lines = _structured_task_report_summary_lines(schema, payload, limit=5)
    if summary_lines:
        return " | ".join(summary_lines)
    return "Đã cập nhật biểu mẫu báo cáo."

def _build_structured_task_report_form(task, user_assign, current_user):
    schema = _load_task_report_schema(task)
    if not task or not user_assign or not schema or not current_user:
        return None

    report_snapshot = _assignment_report_snapshot(user_assign)
    payload = _parse_structured_task_report_payload(user_assign) or {}
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    attachment_name = (
        str(payload.get("attachment_name") or "").strip()
        or str(report_snapshot.get("attachment_name") or "").strip()
    )
    fields = []
    for field in schema.get("fields", []):
        fields.append(
            {
                "key": field.get("key"),
                "label": field.get("label"),
                "type": field.get("type"),
                "required": bool(field.get("required")),
                "placeholder": field.get("placeholder") or "",
                "help_text": field.get("help_text") or "",
                "value": str(values.get(field.get("key")) or ""),
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
            }
        )
    visible_fields = [field for field in fields if _task_report_item_visible_for_user(field, current_user)]
    narrative_cfg = schema.get("narrative") or {}
    attachment_cfg = schema.get("attachment") or {}
    visible_narrative = bool(narrative_cfg.get("enabled")) and _task_report_item_visible_for_user(narrative_cfg, current_user)
    visible_attachment = bool(attachment_cfg.get("enabled")) and _task_report_item_visible_for_user(attachment_cfg, current_user)
    has_visible_content = visible_narrative or visible_attachment or bool(visible_fields)

    return {
        "narrative": {
            "enabled": visible_narrative,
            "label": narrative_cfg.get("label") or "Báo cáo lời tổng hợp",
            "required": bool(narrative_cfg.get("required")),
            "placeholder": narrative_cfg.get("placeholder") or "",
            "value": str(payload.get("narrative") or ""),
        },
        "attachment": {
            "enabled": visible_attachment,
            "label": attachment_cfg.get("label") or "Tệp minh chứng",
            "required": bool(attachment_cfg.get("required")),
            "value": attachment_name,
        },
        "fields": visible_fields,
        "updated_at": payload.get("updated_at", "") or (
            report_snapshot["reported_at"].strftime("%d/%m/%Y %H:%M")
            if report_snapshot.get("reported_at")
            else ""
        ),
        "summary_lines": _structured_task_report_summary_lines(schema, payload, limit=6),
        "has_visible_content": has_visible_content,
    }

def _build_assignment_report_context(user_assign, comments, task=None):
    report_snapshot = _assignment_report_snapshot(user_assign, comments=comments)
    report_schema = _load_task_report_schema(task)
    structured_payload = _parse_structured_task_report_payload(user_assign) if user_assign and report_schema else None
    attachment_label = ((report_schema or {}).get("attachment") or {}).get("label") or "Tệp minh chứng"
    summary_lines = _structured_task_report_summary_lines(report_schema, structured_payload, limit=4)
    if not summary_lines and report_snapshot.get("summary_text"):
        summary_lines = [_task_report_value_preview(report_snapshot.get("summary_text"), 180)]

    return {
        "latest_report_at": report_snapshot.get("reported_at"),
        "latest_report_content": report_snapshot.get("summary_text", ""),
        "result_file": report_snapshot.get("attachment_name", ""),
        "status": _normalize_status(getattr(user_assign, "status", "")) if user_assign else "Chưa tiếp nhận",
        "attachment_label": attachment_label,
        "summary_lines": summary_lines,
        "has_structured_payload": bool(structured_payload),
    }

def _parse_structured_file_report_submission(task, assignment, current_user, form, report_file):
    report_form = _build_structured_task_report_form(task, assignment, current_user)
    if not report_form or not report_form.get("has_visible_content"):
        return None

    missing_labels = []
    values = {}
    attachment_required = bool(report_form["attachment"].get("enabled") and report_form["attachment"].get("required"))
    existing_attachment_name = str(report_form["attachment"].get("value") or "").strip()

    if report_form["narrative"].get("enabled"):
        narrative_value = str(form.get("report_narrative") or form.get("report_content") or "").strip()
        if report_form["narrative"].get("required") and not narrative_value:
            missing_labels.append(report_form["narrative"].get("label") or "Báo cáo lời")
    else:
        narrative_value = ""

    for field in report_form.get("fields") or []:
        field_key = str(field.get("key") or "").strip()
        if not field_key:
            continue
        raw_value = str(form.get(f"report_field_{field_key}") or "").strip()
        normalized_value = raw_value
        if str(field.get("type") or "text").strip().lower() == "number" and raw_value:
            normalized_value = _format_report_number(_parse_report_number(raw_value))
        if field.get("required") and not normalized_value:
            missing_labels.append(field.get("label") or field_key)
        values[field_key] = normalized_value

    if attachment_required and not ((report_file and report_file.filename) or existing_attachment_name):
        missing_labels.append(report_form["attachment"].get("label") or "Tệp minh chứng")

    if missing_labels:
        raise ValueError("Cần điền các nội dung bắt buộc: " + ", ".join(missing_labels) + ".")

    payload = {
        "mode": "structured_task_report",
        "narrative": narrative_value,
        "values": values,
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    if existing_attachment_name:
        payload["attachment_name"] = existing_attachment_name
    return {
        "submission_type": "FILE",
        "narrative": narrative_value,
        "numeric_value": None,
        "payload": payload,
        "report_form": report_form,
    }
