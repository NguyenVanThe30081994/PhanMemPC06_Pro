# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, request, session, url_for
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from category_helpers import get_category_items, get_module_field_items
from models import AppRole, Task, TaskAssignment, TaskComment, User, db
from utils import (
    apply_migrations,
    log_action,
    push_global_notif,
    push_notif,
    render_auto_template as render_template,
)

tasks_bp = Blueprint("tasks_bp", __name__)

PENDING_STATUSES = {"Chưa tiếp nhận", "Chưa bắt đầu", None, ""}
IN_PROGRESS_STATUS = "Đang thực hiện"
COMPLETED_STATUS = "Hoàn thành"


def _current_perms():
    role = db.session.get(AppRole, session.get("role_id")) if session.get("role_id") else None
    if role and role.perms:
        try:
            return json.loads(role.perms)
        except Exception:
            return {}
    return {}


def _normalize_status(status):
    return "Chưa tiếp nhận" if status in PENDING_STATUSES else status


def _parse_deadline(form):
    deadline_type = form.get("deadline_type", "custom")
    deadline_raw = form.get("deadline")
    now = datetime.now()

    if deadline_type == "custom" and deadline_raw:
        try:
            return datetime.strptime(deadline_raw, "%Y-%m-%d").date()
        except Exception:
            return None

    if deadline_type == "week":
        weekday = int(form.get("weekday", 0))
        days_until = (weekday - now.weekday()) % 7
        if days_until == 0:
            days_until = 7
        return (now + timedelta(days=days_until)).date()

    if deadline_type == "month":
        day_of_month = int(form.get("day_of_month", 1))
        try:
            return datetime(now.year, now.month, day_of_month).date()
        except Exception:
            return datetime(now.year, now.month, 28).date()

    if deadline_type == "quarter":
        day_of_month = int(form.get("day_of_month", 1))
        target_month = ((now.month - 1) // 3 + 1) * 3
        try:
            return datetime(now.year, target_month, day_of_month).date()
        except Exception:
            return datetime(now.year, target_month, 28).date()

    if deadline_type == "6months":
        day_of_month = int(form.get("day_of_month", 1))
        month_of_period = int(form.get("month_of_period", 6))
        try:
            return datetime(now.year, month_of_period, day_of_month).date()
        except Exception:
            return datetime(now.year, month_of_period, 28).date()

    if deadline_type == "year":
        day_of_month = int(form.get("day_of_month", 31))
        month_of_period = int(form.get("month_of_period", 12))
        try:
            return datetime(now.year, month_of_period, day_of_month).date()
        except Exception:
            return datetime(now.year, month_of_period, 28).date()

    return None


def _dedupe_users(users):
    unique_users = []
    seen_ids = set()
    for user in users:
        if user and user.id not in seen_ids:
            seen_ids.add(user.id)
            unique_users.append(user)
    return unique_users


def _resolve_assignees(form, domain):
    assign_type = form.get("assign_type", "unit")
    target_ids = [int(uid) for uid in form.getlist("target_users") if str(uid).isdigit()]
    assignee_role_id = form.get("assignee_role_id")

    if assign_type == "role":
        if not assignee_role_id or not str(assignee_role_id).isdigit():
            return [], "Cần chọn vai trò nhận việc."
        users = (
            User.query.filter_by(role_id=int(assignee_role_id), is_active=True)
            .order_by(User.fullname.asc())
            .all()
        )
        if not users:
            return [], "Không có cán bộ hoạt động nào thuộc vai trò đã chọn."
        return _dedupe_users(users), None

    if assign_type == "user":
        if not target_ids:
            return [], "Cần chọn ít nhất một cán bộ nhận việc."
        users = (
            User.query.filter(User.id.in_(target_ids), User.is_active.is_(True))
            .order_by(User.fullname.asc())
            .all()
        )
        if not users:
            return [], "Danh sách cán bộ nhận việc không hợp lệ hoặc đã bị khóa."
        return _dedupe_users(users), None

    if not domain:
        return [], "Cần chọn đơn vị nghiệp vụ trước khi giao theo đơn vị."

    users = (
        User.query.filter_by(unit_area=domain, is_active=True)
        .order_by(User.fullname.asc())
        .all()
    )
    if not users:
        return [], f"Không tìm thấy cán bộ hoạt động nào thuộc đơn vị {domain}."
    return _dedupe_users(users), None


def _can_edit_task(task):
    if not task or not session.get("uid"):
        return False
    return bool(session.get("is_admin")) or task.author_id == session.get("uid")


def _decorate_task(task, current_uid, is_lead):
    assignments = task.assignments or []
    normalized_statuses = [_normalize_status(a.status) for a in assignments]
    total_assignments = len(assignments)
    accepted_assignments = sum(status != "Chưa tiếp nhận" for status in normalized_statuses)
    completed_assignments = sum(status == COMPLETED_STATUS for status in normalized_statuses)
    user_assignment = next((a for a in assignments if a.user_id == current_uid), None)
    current_user_status = _normalize_status(user_assignment.status) if user_assignment else None

    if is_lead:
        if total_assignments == 0:
            display_status = _normalize_status(task.initial_status)
            progress_percent = 0
        elif completed_assignments == total_assignments:
            display_status = COMPLETED_STATUS
            progress_percent = 100
        elif accepted_assignments == 0:
            display_status = f"Chưa tiếp nhận (0/{total_assignments})"
            progress_percent = 0
        else:
            display_status = f"Đang thực hiện ({accepted_assignments}/{total_assignments})"
            progress_percent = round((completed_assignments / total_assignments) * 100)
    else:
        display_status = current_user_status or _normalize_status(task.initial_status)
        if display_status == COMPLETED_STATUS:
            progress_percent = 100
        elif display_status == IN_PROGRESS_STATUS:
            progress_percent = 60
        else:
            progress_percent = 0

    is_completed = (
        completed_assignments == total_assignments and total_assignments > 0
        if is_lead
        else display_status == COMPLETED_STATUS
    )
    is_overdue = bool(task.deadline and task.deadline < datetime.now().date() and not is_completed)

    setattr(task, "display_status", display_status)
    setattr(task, "progress_percent", progress_percent)
    setattr(task, "is_overdue", is_overdue)
    setattr(task, "assignee_count", total_assignments)
    setattr(task, "accepted_assignments", accepted_assignments)
    setattr(task, "completed_assignments", completed_assignments)
    setattr(task, "current_user_status", current_user_status)

    return {
        "display_status": display_status,
        "progress_percent": progress_percent,
        "is_overdue": is_overdue,
        "total_assignments": total_assignments,
        "accepted_assignments": accepted_assignments,
        "completed_assignments": completed_assignments,
        "current_user_status": current_user_status,
        "user_assignment": user_assignment,
    }


@tasks_bp.route("/tasks", methods=["GET", "POST"])
def tasks():
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    try:
        apply_migrations(current_app)
    except Exception as migration_error:
        current_app.logger.warning(f"TASKS migration safeguard failed: {migration_error}")

    pro_units = get_module_field_items("tasks", "domain") or get_category_items("Đội nghiệp vụ")
    task_types = get_module_field_items("tasks", "task_type") or get_category_items("Loại công việc")
    priority_items = get_module_field_items("tasks", "priority") or get_category_items("Mức độ ưu tiên")
    status_items = get_module_field_items("tasks", "initial_status") or get_category_items("Trạng thái công việc")
    current_domain = request.args.get("domain", "ALL")
    now_dt = datetime.now()

    perms = _current_perms()
    is_lead = perms.get("p_task_lead") or session.get("is_admin")
    is_admin = bool(session.get("is_admin"))

    active_users = User.query.filter_by(is_active=True).order_by(User.unit_area.asc(), User.fullname.asc()).all()
    roles = AppRole.query.order_by(AppRole.name.asc()).all()

    if request.method == "POST" and is_lead:
        title = (request.form.get("title") or "").strip()
        domain = (request.form.get("unit_name") or request.form.get("domain") or "").strip()
        content = (request.form.get("description") or request.form.get("content") or "").strip()
        priority = request.form.get("priority") or "Trung bình"
        task_type = request.form.get("task_type") or "Công việc thường xuyên"

        if not title:
            flash("Tiêu đề công việc không được để trống.", "danger")
            return redirect(url_for("tasks_bp.tasks"))

        assignees, error_message = _resolve_assignees(request.form, domain)
        if error_message:
            flash(error_message, "danger")
            return redirect(url_for("tasks_bp.tasks"))

        attachment = request.files.get("task_file") or request.files.get("file")
        attachment_name = ""
        if attachment and attachment.filename:
            attachment_name = secure_filename(attachment.filename)
            attachment.save(os.path.join(current_app.root_path, "task_files", attachment_name))

        new_task = Task(
            domain=domain,
            title=title,
            content=content,
            deadline=_parse_deadline(request.form),
            file_path=attachment_name,
            author_id=session["uid"],
            author_name=session.get("fullname", "Quản trị"),
            priority=priority,
            task_type=task_type,
            initial_status="Chưa tiếp nhận",
        )
        db.session.add(new_task)
        db.session.flush()

        for user in assignees:
            db.session.add(
                TaskAssignment(task_id=new_task.id, user_id=user.id, status="Chưa tiếp nhận")
            )

        db.session.commit()

        notify_message = (
            f"Đơn vị {domain} được giao: {new_task.title}"
            if request.form.get("assign_type", "unit") == "unit"
            else f"Bạn vừa được giao: {new_task.title}"
        )
        for user in assignees:
            push_notif(user.id, "Công việc mới", notify_message, f"/tasks/{new_task.id}")

        log_action(
            session["uid"],
            session.get("fullname", "Quản trị"),
            "Giao công việc mới",
            "Công việc",
            f"{new_task.title} | {len(assignees)} người nhận",
        )
        push_global_notif(
            "Công việc mới",
            f"Có công việc mới: {new_task.title}",
            f"/tasks/{new_task.id}",
            exclude_uid=session.get("uid"),
        )

        flash(f"Đã giao công việc cho {len(assignees)} cán bộ.", "success")
        return redirect(url_for("tasks_bp.tasks"))

    query = Task.query.options(joinedload(Task.assignments))
    if current_domain != "ALL":
        query = query.filter_by(domain=current_domain)

    if is_lead:
        all_tasks = query.order_by(Task.created_at.desc()).all()
    else:
        all_tasks = (
            query.join(TaskAssignment, Task.id == TaskAssignment.task_id)
            .filter(TaskAssignment.user_id == session["uid"])
            .order_by(Task.created_at.desc())
            .all()
        )

    total_count = len(all_tasks)
    overdue_count = 0
    completed_count = 0

    for task in all_tasks:
        task_metrics = _decorate_task(task, session["uid"], is_lead)
        if task_metrics["is_overdue"]:
            overdue_count += 1
        if task_metrics["display_status"] == COMPLETED_STATUS:
            completed_count += 1

    return render_template(
        "tasks.html",
        tasks=all_tasks,
        users=active_users,
        roles=roles,
        pro_units=pro_units,
        task_types=task_types,
        priority_items=priority_items,
        status_items=status_items,
        current_domain=current_domain,
        now_dt=now_dt,
        is_lead=is_lead,
        is_admin=is_admin,
        stats={
            "total": total_count,
            "completed": completed_count,
            "pending": total_count - completed_count,
            "overdue": overdue_count,
        },
    )


@tasks_bp.route("/tasks/<int:tid>", methods=["GET", "POST"])
def task_detail(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    pro_units = get_module_field_items("tasks", "domain") or get_category_items("Đội nghiệp vụ")
    task_types = get_module_field_items("tasks", "task_type") or get_category_items("Loại công việc")
    priority_items = get_module_field_items("tasks", "priority") or get_category_items("Mức độ ưu tiên")
    perms = _current_perms()
    is_lead = perms.get("p_task_lead") or session.get("is_admin")
    can_edit_task = _can_edit_task(task)
    comments = TaskComment.query.filter_by(task_id=tid).order_by(TaskComment.created_at.desc()).all()
    assigns = (
        db.session.query(TaskAssignment, User)
        .join(User, TaskAssignment.user_id == User.id)
        .filter(TaskAssignment.task_id == tid)
        .order_by(TaskAssignment.updated_at.desc(), User.fullname.asc())
        .all()
    )

    task_metrics = _decorate_task(task, session["uid"], is_lead)
    user_assign = task_metrics["user_assignment"]

    if request.method == "POST":
        content = (request.form.get("content") or "").strip()
        if content:
            db.session.add(
                TaskComment(
                    task_id=tid,
                    user_id=session["uid"],
                    user_name=session.get("fullname", "Người dùng"),
                    content=content,
                )
            )
            db.session.commit()
            flash("Đã gửi phản hồi.", "success")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))

    return render_template(
        "task_detail.html",
        task=task,
        comments=comments,
        assigns=assigns,
        pro_units=pro_units,
        task_types=task_types,
        priority_items=priority_items,
        now_dt=datetime.now(),
        is_lead=is_lead,
        can_edit_task=can_edit_task,
        user_assign=user_assign,
        progress_percent=task_metrics["progress_percent"],
    )


@tasks_bp.route("/tasks/<int:tid>/edit", methods=["POST"])
def edit_task(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    if not _can_edit_task(task):
        flash("Bạn không có quyền sửa công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    title = (request.form.get("title") or "").strip()
    domain = (request.form.get("domain") or "").strip()
    content = (request.form.get("content") or "").strip()
    priority = (request.form.get("priority") or "Trung bình").strip()
    task_type = (request.form.get("task_type") or "Công việc thường xuyên").strip()

    if not title:
        flash("Tiêu đề công việc không được để trống.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.title = title
    task.domain = domain
    task.content = content
    task.priority = priority
    task.task_type = task_type
    task.deadline = _parse_deadline(request.form)

    attachment = request.files.get("task_file")
    if attachment and attachment.filename:
        attachment_name = secure_filename(attachment.filename)
        attachment.save(os.path.join(current_app.root_path, "task_files", attachment_name))
        task.file_path = attachment_name

    db.session.commit()

    log_action(
        session["uid"],
        session.get("fullname", "Quản trị"),
        "Cập nhật công việc",
        "Công việc",
        f"Task #{task.id} | {task.title}",
    )
    flash("Đã cập nhật công việc.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))


@tasks_bp.route("/tasks/<int:tid>/update_status", methods=["POST"])
def update_task_status(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    action = request.form.get("action")
    assign = TaskAssignment.query.filter_by(task_id=tid, user_id=session["uid"]).first()

    if not assign:
        flash("Bạn không được giao công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if action == "accept":
        assign.status = IN_PROGRESS_STATUS
        db.session.commit()
        flash("Đã tiếp nhận công việc.", "success")

    return redirect(url_for("tasks_bp.task_detail", tid=tid))


@tasks_bp.route("/tasks/<int:tid>/submit_report", methods=["POST"])
def submit_task_report(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    report_content = (request.form.get("report_content") or "").strip()
    mark_completed = request.form.get("mark_completed")
    report_file = request.files.get("report_file")

    assign = TaskAssignment.query.filter_by(task_id=tid, user_id=session["uid"]).first()
    if not assign:
        flash("Bạn không được giao công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    attachment_name = ""
    if report_file and report_file.filename:
        attachment_name = secure_filename(report_file.filename)
        report_file.save(os.path.join(current_app.root_path, "task_files", attachment_name))

    if report_content:
        report_message = f"[BÁO CÁO] {report_content}"
        if attachment_name:
            report_message += f" (Đính kèm: {attachment_name})"
        db.session.add(
            TaskComment(
                task_id=tid,
                user_id=session["uid"],
                user_name=session.get("fullname", "Người dùng"),
                content=report_message,
            )
        )

    if mark_completed == "1":
        assign.status = COMPLETED_STATUS
    elif _normalize_status(assign.status) == "Chưa tiếp nhận":
        assign.status = IN_PROGRESS_STATUS

    if attachment_name:
        assign.result_file = attachment_name

    db.session.commit()
    flash("Đã gửi báo cáo công việc.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))
