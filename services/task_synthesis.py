# -*- coding: utf-8 -*-
"""
Cụm tổng hợp số liệu đầu mục (item): bật/tắt cộng gộp, xem dữ liệu tổng hợp,
lưu văn bản tổng hợp. Tách từ routes/tasks.py (Pha 2 đợt 12). routes/tasks.py
vẫn giữ decorator route và re-export các tên còn dùng.
"""

from datetime import datetime

from flask import flash, jsonify, redirect, request, session, url_for

from models import Task, TaskItem, User, db
from permissions import current_is_admin

from services.task_admin import _ensure_task_schema
from services.task_guards import _can_edit_task, _can_manage_task
from services.task_modes import _task_assignment_status_label
from services.task_permissions import _can_process_task_module, _current_perms
from services.outline_submission import _outline_merged_content, _outline_submission_values
from services.task_runtime_sync import _latest_assignment_submission, _submission_has_report_content
from services.task_units import _task_assignee_unit_name
from services.task_workspace_helpers import _task_assignments_query
from services.task_workspace_views import _outline_item_number_fields, _task_item_synthesis_text


def _toggle_task_item_aggregate(tid, item_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    item = TaskItem.query.filter_by(id=item_id, task_id=tid).first()
    if not item:
        flash("Không tìm thấy đầu mục.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage:
        flash("Bạn không có quyền thay đổi cài đặt đầu mục này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    item.allow_aggregate = not bool(item.allow_aggregate)
    item.updated_at = datetime.now()
    db.session.commit()
    flash("Đã bật cộng gộp số liệu cho đầu mục." if item.allow_aggregate else "Đã tắt cộng gộp số liệu.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid) + "#pane-outline-matrix")


def _task_item_synthesis_data(tid, item_id):
    """Dữ liệu cho màn tổng hợp: từng đơn vị đã nộp gì cho đầu mục này."""
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Chưa đăng nhập."}), 401

    _ensure_task_schema()
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return jsonify({"ok": False, "error": "Không tìm thấy công việc."}), 404
    item = TaskItem.query.filter_by(id=item_id, task_id=tid).first()
    if not item:
        return jsonify({"ok": False, "error": "Không tìm thấy đầu mục."}), 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage:
        return jsonify({"ok": False, "error": "Bạn không có quyền tổng hợp báo cáo."}), 403

    number_fields = _outline_item_number_fields(item)
    content = str(getattr(item, "content", "") or "")
    assignments = _task_assignments_query(task, task_item_id=item.id).all()
    submissions = []
    for assignment in assignments:
        submission = _latest_assignment_submission(assignment)
        user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
        values = _outline_submission_values(submission)
        merged_text = ""
        if item.report_kind == "number" and number_fields and submission:
            merged_text = _outline_merged_content(content, number_fields, values).strip()
        files = []
        for file in (getattr(submission, "files", None) or []):
            files.append({"name": file.original_name or file.stored_name, "id": file.id})
        submissions.append(
            {
                "assignment_id": assignment.id,
                "unit_name": _task_assignee_unit_name(user),
                "submitter_name": getattr(user, "fullname", None) or getattr(user, "username", None) or "Cán bộ",
                "status": _task_assignment_status_label(assignment.status),
                "submitted_at": submission.submitted_at.strftime("%d/%m/%Y %H:%M") if submission and submission.submitted_at else "",
                "narrative": str(getattr(submission, "narrative_content", "") or "").strip() if submission else "",
                "merged_text": merged_text,
                "numeric_value": ("%g" % submission.numeric_value) if submission and submission.numeric_value is not None else "",
                "files": files,
                "has_submission": bool(submission and (_submission_has_report_content(submission) or merged_text or files)),
            }
        )

    return jsonify(
        {
            "ok": True,
            "item": {
                "id": item.id,
                "item_code": getattr(item, "item_code", None) or "",
                "title": getattr(item, "title", "") or "",
                "report_kind": item.report_kind or "narrative",
                "synthesis": _task_item_synthesis_text(item),
                "synthesis_updated_at": item.synthesis_updated_at.strftime("%d/%m/%Y %H:%M") if getattr(item, "synthesis_updated_at", None) else "",
            },
            "submissions": submissions,
        }
    )


def _save_task_item_synthesis(tid, item_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    item = TaskItem.query.filter_by(id=item_id, task_id=tid).first()
    if not item:
        flash("Không tìm thấy đầu mục.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage:
        flash("Bạn không có quyền tổng hợp báo cáo của đầu mục này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    synthesis = (request.form.get("synthesis_content") or "").strip()
    item.synthesis_content = synthesis or None
    item.synthesis_updated_at = datetime.now() if synthesis else None
    item.updated_at = datetime.now()
    db.session.commit()
    if synthesis:
        flash(f"Đã lưu văn bản tổng hợp cho đầu mục {item.item_code or item.title}.", "success")
    else:
        flash(f"Đã xóa văn bản tổng hợp của đầu mục {item.item_code or item.title} — xuất Word sẽ gộp tự động như cũ.", "warning")
    return redirect(url_for("tasks_bp.task_detail", tid=tid) + "#pane-outline-matrix")
