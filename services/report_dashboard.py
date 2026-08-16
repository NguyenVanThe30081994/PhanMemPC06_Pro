# -*- coding: utf-8 -*-
"""
Bảng điều khiển báo cáo định kỳ: tổng hợp tiến độ nộp theo chu kỳ × đơn vị
cho các task có 'cách báo cáo' = định kỳ.

Pha 3 Feature 3. Request-driven (không scheduler).
"""

from flask import session
from sqlalchemy.orm import joinedload

from models import Task, TaskAssignment, TaskSubmission, User, db
from permissions import current_is_admin
from services.task_deadline import _task_current_cycle, _task_report_kind_label, _task_report_period
from services.task_guards import _can_manage_task, _can_watch_task
from services.task_permissions import _can_view_all_tasks, _current_perms
from services.task_units import _task_assignee_unit_name
from task_page_builders import task_visible_for_user
from utils import render_auto_template as render_template


def _task_periodic_submission(assignment, cycle_key):
    """Submission theo chu kỳ của assignment (nếu có cycle_key), ngược lại lấy mới nhất."""
    if cycle_key:
        submission = (
            TaskSubmission.query.filter_by(
                assignment_id=assignment.id,
                cycle_key=cycle_key,
            )
            .order_by(TaskSubmission.submitted_at.desc(), TaskSubmission.id.desc())
            .first()
        )
        if submission:
            return submission
    return (
        TaskSubmission.query.filter_by(assignment_id=assignment.id)
        .order_by(TaskSubmission.submitted_at.desc(), TaskSubmission.id.desc())
        .first()
    )


def _build_report_dashboard_data(uid, perms):
    """Cho mỗi periodic task: cycle hiện tại + nhóm đơn vị × trạng thái nộp."""
    can_view_all_tasks = _can_view_all_tasks(perms)
    is_admin = bool(current_is_admin())
    current_user = db.session.get(User, uid)

    candidate_tasks = (
        Task.query.options(joinedload(Task.assignments).joinedload(TaskAssignment.user))
        .filter(Task.parent_task_id.is_(None))
        .order_by(Task.created_at.desc(), Task.id.desc())
        .all()
    )

    cards = []
    for task in candidate_tasks:
        cfg = _task_report_period(task)
        if cfg.get("kind") != "periodic":
            continue

        is_executor = bool(
            TaskAssignment.query.filter_by(task_id=task.id, user_id=uid).first()
        )
        is_manager = _can_manage_task(task, user=current_user)
        is_viewer = _can_watch_task(task, user=current_user)
        if not task_visible_for_user(
            task, uid,
            can_view_all_tasks=can_view_all_tasks,
            is_admin=is_admin,
            is_executor=is_executor,
            is_manager=is_manager,
            is_viewer=is_viewer,
        ):
            continue

        current_cycle = _task_current_cycle(task)
        if not current_cycle:
            continue
        cycle_key = current_cycle.get("key")

        units = {}
        assignments = (
            TaskAssignment.query.options(joinedload(TaskAssignment.user))
            .filter_by(task_id=task.id)
            .filter(TaskAssignment.task_item_id.is_(None))
            .all()
        )
        for assignment in assignments:
            user = getattr(assignment, "user", None)
            if not user:
                continue
            unit_name = _task_assignee_unit_name(user) or "Chưa có đơn vị"
            unit = units.setdefault(
                unit_name,
                {"unit_name": unit_name, "assignees": [], "submitted": 0, "total": 0},
            )
            submission = _task_periodic_submission(assignment, cycle_key)
            status = "submitted" if submission else "pending"
            unit["assignees"].append(
                {
                    "name": getattr(user, "fullname", None) or getattr(user, "username", None) or f"UID {user.id}",
                    "status": status,
                    "submitted_at": (
                        submission.submitted_at.strftime("%d/%m/%Y %H:%M")
                        if submission and submission.submitted_at
                        else ""
                    ),
                }
            )
            unit["total"] += 1
            if status == "submitted":
                unit["submitted"] += 1

        for unit in units.values():
            unit["assignees"].sort(key=lambda item: item["name"].lower())
        unit_list = sorted(units.values(), key=lambda item: item["unit_name"].lower())

        total_units = len(unit_list)
        reported_units = sum(1 for unit in unit_list if unit["submitted"] > 0)
        total_assignments = sum(unit["total"] for unit in unit_list)
        submitted_assignments = sum(unit["submitted"] for unit in unit_list)
        progress = round((submitted_assignments * 100.0 / total_assignments)) if total_assignments else 0

        cards.append(
            {
                "task": task,
                "report_kind_label": _task_report_kind_label(task),
                "current_cycle": current_cycle,
                "units": unit_list,
                "total_units": total_units,
                "reported_units": reported_units,
                "total_assignments": total_assignments,
                "submitted_assignments": submitted_assignments,
                "progress": progress,
            }
        )

    cards.sort(
        key=lambda card: (
            (card["current_cycle"].get("due") or "9999-12-31"),
            card["task"].title.lower(),
        )
    )
    return cards


def _report_dashboard_page():
    """Handler: bảng điều khiển báo cáo định kỳ."""
    uid = session["uid"]
    perms = _current_perms()
    cards = _build_report_dashboard_data(uid, perms)
    return render_template(
        "report_dashboard.html",
        cards=cards,
    )