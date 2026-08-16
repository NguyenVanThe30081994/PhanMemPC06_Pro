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

    return render_template(
        "task_form_aggregation.html",
        task=task,
        fields=fields,
        rows=rows,
        available_cycles=available_cycles,
        current_cycle=current_cycle,
        cycle_key=cycle_key,
        _task_assignee_unit_name=_task_assignee_unit_name,
        _task_assignment_status_label=_task_assignment_status_label,
        _flatten_value=_flatten_form_value,
    )



def _flatten_form_value(value):
    """Làm phẳng giá trị field để hiển thị trong bảng.

    Giống logic flatten trong _export_form_task_v2 (services/task_pages.py:1300-1305).
    """
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return " || ".join(" | ".join(str(cell) for cell in item) for item in value)
        return ", ".join(str(item) for item in value)
    return str(value) if value is not None else ""