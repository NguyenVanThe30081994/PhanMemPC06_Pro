# -*- coding: utf-8 -*-
"""
Tổng hợp số liệu biểu mẫu (FORM) theo trường × assignment, hỗ trợ chuyển chu kỳ
cho task định kỳ.

Pha 3 Feature 1. Không có scheduler — request-driven web view.
"""

from datetime import datetime, timedelta
from flask import flash, redirect, request, session, url_for
from sqlalchemy.orm import joinedload

from models import Task, TaskAssignment, TaskSubmission, User, db
from permissions import current_is_admin
from report_cycles import task_config, cycles_between
from services.task_form_fields import _task_form_fields
from services.task_guards import _can_edit_task, _can_manage_task, _can_watch_task
from services.task_modes import _task_assignment_status_label
from services.task_permissions import _can_process_task_module, _current_perms
from services.task_units import _task_assignee_unit_name
from services.excel_form_template import (
    _ascii_vn,
    _excel_payload_rows,
    _parse_numeric_value,
    evaluate_summary_row_values,
    format_excel_cell_display,
    load_excel_form_schema,
)
from task_read_models import task_form_submission_payload
from utils import render_auto_template as render_template


def _form_available_cycles(task):
    """Danh sách chu kỳ có sẵn cho task (chỉ khi periodic)."""
    cfg = task_config(task)
    if cfg.get("kind") != "periodic":
        return []
    today = datetime.now().date()
    start = (getattr(task, "created_at", None) or datetime.now()).date()
    end = today + timedelta(days=32)  # dư một chu kỳ
    return cycles_between(cfg, start, end)


def _build_form_aggregation_rows(task, current_uid, cycle_key=None):
    """Trả (fields, rows) với TẤT CẢ submission per assignment, lọc cycle_key nếu có.

    Khác _build_form_task_rows (chỉ lấy submission mới nhất/assignment):
    lấy tất cả TaskSubmission per assignment, order submitted_at desc.
    """
    fields = _task_form_fields(task)
    assignments = (
        TaskAssignment.query.options(joinedload(TaskAssignment.user))
        .filter_by(task_id=task.id)
        .filter(TaskAssignment.task_item_id.is_(None))
        .all()
    )

    rows = []
    for assignment in assignments:
        user = getattr(assignment, "user", None)
        query = TaskSubmission.query.filter_by(assignment_id=assignment.id)
        if cycle_key:
            query = query.filter_by(cycle_key=cycle_key)
        submissions = (
            query.order_by(TaskSubmission.submitted_at.desc(), TaskSubmission.id.desc())
            .all()
        )
        if not submissions:
            # Hàng trống cho assignment chưa nộp
            rows.append({
                "assignment": assignment,
                "submission": None,
                "payload": {},
                "is_current_user": getattr(assignment, "user_id", None) == current_uid,
            })
        else:
            for submission in submissions:
                rows.append({
                    "assignment": assignment,
                    "submission": submission,
                    "payload": task_form_submission_payload(submission) if submission else {},
                    "is_current_user": getattr(assignment, "user_id", None) == current_uid,
                })
    return fields, rows


def _form_data_aggregation_view(tid):
    """Handler: xem tổng hợp số liệu FORM theo field."""
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
        or _can_watch_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền xem dữ liệu biểu mẫu.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    cycle_key = request.args.get("cycle_key") or None
    fields, rows = _build_form_aggregation_rows(task, session["uid"], cycle_key=cycle_key)
    available_cycles = _form_available_cycles(task)
    current_cycle = None
    if available_cycles and not cycle_key:
        # Mặc định chọn chu kỳ mới nhất
        current_cycle = available_cycles[-1]
        cycle_key = current_cycle["key"]
    elif available_cycles and cycle_key:
        for c in available_cycles:
            if c["key"] == cycle_key:
                current_cycle = c
                break
        if not current_cycle:
            current_cycle = available_cycles[-1]

    excel_schema = load_excel_form_schema(task)
    excel_aggregation = _build_excel_aggregation_view(excel_schema, rows) if excel_schema else None

    return render_template(
        "task_form_aggregation.html",
        task=task,
        fields=fields,
        rows=rows,
        excel_schema=excel_schema,
        excel_aggregation=excel_aggregation,
        available_cycles=available_cycles,
        current_cycle=current_cycle,
        cycle_key=cycle_key,
        _task_assignee_unit_name=_task_assignee_unit_name,
        _task_assignment_status_label=_task_assignment_status_label,
        _flatten_value=_flatten_form_value,
    )


def _format_agg_num(val):
    return str(int(val)) if float(val).is_integer() else f"{val:g}"


def _build_excel_aggregation_view(excel_schema, rows):
    columns = excel_schema.get("columns") or []
    is_unit_rows = bool(excel_schema.get("assign_row_mode") == "unit_rows" and excel_schema.get("unit_col_index") is not None)
    unit_col_idx = excel_schema.get("unit_col_index")
    allow_add_rows = bool(excel_schema.get("allow_add_rows", True))
    is_fixed = bool(not is_unit_rows and excel_schema.get("has_prefilled_rows") and not allow_add_rows)
    show_unit_prefix_col = (not is_fixed) and (not is_unit_rows)
    unit_entries = []
    submitted_unit_count = 0

    for row in rows or []:
        assignment = row.get("assignment")
        user = getattr(assignment, "user", None) if assignment else None
        user_name = getattr(user, "fullname", None) or getattr(user, "username", None) or ""
        unit_name = _task_assignee_unit_name(user) if user else user_name
        submission = row.get("submission")
        raw_excel_rows = _excel_payload_rows(row.get("payload"), schema=excel_schema)
        formatted_rows = [
            [
                format_excel_cell_display(r_vals[c_i] if c_i < len(r_vals) else "", col)
                for c_i, col in enumerate(columns)
            ]
            for r_vals in raw_excel_rows
        ]
        if raw_excel_rows:
            submitted_unit_count += 1
        unit_entries.append({
            "unit_name": unit_name,
            "user_name": user_name,
            "submitted": bool(raw_excel_rows),
            "submitted_at": submission.submitted_at.strftime("%d/%m/%Y %H:%M") if submission and submission.submitted_at else "",
            "rows": raw_excel_rows,
            "display_rows": formatted_rows,
        })

    col_totals = [0.0 for _ in columns]
    col_has_num = [False for _ in columns]
    merged_rows = []

    if is_unit_rows:
        import re as _re
        sub_by_unit = {}
        for entry in unit_entries:
            norm_u = _re.sub(r"\s+", " ", _ascii_vn(entry["unit_name"]).lower()).strip()
            if norm_u and entry["rows"]:
                sub_by_unit.setdefault(norm_u, []).extend(entry["rows"])
        if not allow_add_rows:
            used = set()
            for r_idx, tpl_row in enumerate(excel_schema.get("template_rows") or []):
                u_label = str(tpl_row[unit_col_idx] if unit_col_idx < len(tpl_row) else "")
                norm_u = _re.sub(r"\s+", " ", _ascii_vn(u_label).lower()).strip()
                if norm_u and norm_u in sub_by_unit and sub_by_unit[norm_u]:
                    used.add(norm_u)
                    raw_row = list(sub_by_unit[norm_u][0])
                    is_sub = True
                else:
                    raw_row = list(tpl_row)
                    is_sub = False
                disp_row = []
                for c_idx, col in enumerate(columns):
                    val = raw_row[c_idx] if c_idx < len(raw_row) else ""
                    if is_sub and col.get("type") == "number" and col.get("role") != "formula" and not col.get("is_percent"):
                        num = _parse_numeric_value(val)
                        if num is not None:
                            col_totals[c_idx] += num
                            col_has_num[c_idx] = True
                    disp_row.append(format_excel_cell_display(val, col))
                merged_rows.append({"unit_name": u_label, "cells": disp_row, "submitted": is_sub})
            for entry in unit_entries:
                norm_u = _re.sub(r"\s+", " ", _ascii_vn(entry["unit_name"]).lower()).strip()
                if entry["rows"] and norm_u not in used:
                    used.add(norm_u)
                    for r_vals in entry["rows"]:
                        disp_row = []
                        for c_idx, col in enumerate(columns):
                            val = r_vals[c_idx] if c_idx < len(r_vals) else ""
                            if col.get("type") == "number" and col.get("role") != "formula" and not col.get("is_percent"):
                                num = _parse_numeric_value(val)
                                if num is not None:
                                    col_totals[c_idx] += num
                                    col_has_num[c_idx] = True
                            disp_row.append(format_excel_cell_display(val, col))
                        merged_rows.append({"unit_name": entry["unit_name"], "cells": disp_row, "submitted": True})
        else:
            row_seq = 0
            for entry in unit_entries:
                for r_vals in entry["rows"]:
                    row_seq += 1
                    disp_row = []
                    for c_idx, col in enumerate(columns):
                        if col.get("is_stt"):
                            disp_row.append(str(row_seq))
                            continue
                        val = r_vals[c_idx] if c_idx < len(r_vals) else ""
                        if col.get("type") == "number" and col.get("role") != "formula" and not col.get("is_percent"):
                            num = _parse_numeric_value(val)
                            if num is not None:
                                col_totals[c_idx] += num
                                col_has_num[c_idx] = True
                        disp_row.append(format_excel_cell_display(val, col))
                    merged_rows.append({"unit_name": entry["unit_name"], "cells": disp_row, "submitted": True})
    elif is_fixed:
        template_rows = excel_schema.get("template_rows") or []
        for r_idx, tpl_row in enumerate(template_rows):
            out_row = []
            for c_idx, col in enumerate(columns):
                if col.get("type") == "number":
                    total = 0.0
                    has_val = False
                    for entry in unit_entries:
                        if r_idx < len(entry["rows"]) and c_idx < len(entry["rows"][r_idx]):
                            num = _parse_numeric_value(entry["rows"][r_idx][c_idx])
                            if num is not None:
                                total += num
                                has_val = True
                    if has_val:
                        out_row.append(_format_agg_num(total))
                        col_totals[c_idx] += total
                        col_has_num[c_idx] = True
                    else:
                        out_row.append("0")
                else:
                    out_row.append(tpl_row[c_idx] if c_idx < len(tpl_row) else "")
            merged_rows.append({"unit_name": "", "cells": out_row})
    else:
        for entry in unit_entries:
            for r_vals in entry["rows"]:
                cells = [r_vals[c_i] if c_i < len(r_vals) else "" for c_i in range(len(columns))]
                disp_cells = []
                for c_idx, col in enumerate(columns):
                    if col.get("type") == "number" and col.get("role") != "formula" and not col.get("is_percent"):
                        num = _parse_numeric_value(cells[c_idx])
                        if num is not None:
                            col_totals[c_idx] += num
                            col_has_num[c_idx] = True
                    disp_cells.append(format_excel_cell_display(cells[c_idx], col))
                merged_rows.append({
                    "unit_name": entry["unit_name"],
                    "cells": disp_cells,
                })

    raw_totals_vec = [col_totals[c_i] if col_has_num[c_i] else None for c_i in range(len(columns))]
    summary_raw = evaluate_summary_row_values(excel_schema, raw_totals_vec)
    column_totals = [
        format_excel_cell_display(summary_raw[c_idx], columns[c_idx])
        if summary_raw[c_idx] != ""
        else (
            _format_agg_num(col_totals[c_idx])
            if (columns[c_idx].get("type") == "number" and col_has_num[c_idx] and not columns[c_idx].get("is_percent"))
            else ""
        )
        for c_idx in range(len(columns))
    ]
    return {
        "is_fixed_indicators": is_fixed,
        "is_unit_rows": is_unit_rows,
        "show_unit_prefix_col": show_unit_prefix_col,
        "unit_col_index": unit_col_idx,
        "merged_rows": merged_rows,
        "column_totals": column_totals,
        "unit_entries": unit_entries,
        "submitted_unit_count": submitted_unit_count,
    }



def _flatten_form_value(value):
    """Làm phẳng giá trị field để hiển thị trong bảng.

    Giống logic flatten trong _export_form_task_v2 (services/task_pages.py:1300-1305).
    """
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return " || ".join(" | ".join(str(cell) for cell in item) for item in value)
        return ", ".join(str(item) for item in value)
    return str(value) if value is not None else ""