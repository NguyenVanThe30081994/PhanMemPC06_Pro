# -*- coding: utf-8 -*-
import json
import os
import re
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, request, session, url_for
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from category_helpers import (
    apply_reference_display,
    canonicalize_category_value,
    category_filter_counts,
    module_category_options,
    resolve_category_display,
    stable_form_category_options,
    sync_record_categories,
)
from models import AppRole, RankingUnit, Task, TaskAssignment, TaskComment, User, db
from utils import (
    apply_migrations,
    extract_unit_key,
    log_action,
    is_unit_match,
    normalize_unit_name,
    push_global_notif,
    push_notif,
    remove_accents,
    render_auto_template as render_template,
)

tasks_bp = Blueprint("tasks_bp", __name__)

PENDING_STATUSES = {"Chưa tiếp nhận", "Chưa bắt đầu", None, ""}
IN_PROGRESS_STATUS = "Đang thực hiện"
COMPLETED_STATUS = "Hoàn thành"


def _task_domain_options():
    return module_category_options("tasks", "domain", "Đội nghiệp vụ")


def _task_field_options():
    return module_category_options("news", "category", "Lĩnh vực", "Đội nghiệp vụ")


def _task_type_options():
    return module_category_options("tasks", "task_type", "Loại công việc")


def _task_priority_options():
    return module_category_options("tasks", "priority", "Mức độ ưu tiên")


def _task_field_display(value, options, fallback_label):
    return resolve_category_display(value, options, fallback_label=fallback_label)


def _decorate_task_categories(task, field_options, domain_options, type_options, priority_options):
    field_info = _task_field_display(task.category, field_options, "Chưa phân lĩnh vực")
    domain_info = _task_field_display(task.domain, domain_options, "Chưa phân đơn vị")
    type_info = _task_field_display(task.task_type, type_options, "Công việc thường xuyên")
    priority_info = _task_field_display(task.priority, priority_options, "Trung bình")

    setattr(task, "category_display", field_info["display_name"])
    setattr(task, "category_filter", field_info["filter_value"])
    setattr(task, "domain_display", domain_info["display_name"])
    setattr(task, "domain_filter", domain_info["filter_value"])
    setattr(task, "task_type_display", type_info["display_name"])
    setattr(task, "priority_display", priority_info["display_name"])

    return {
        "category": field_info,
        "domain": domain_info,
        "task_type": type_info,
        "priority": priority_info,
    }


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


def _user_unit_key(user):
    if not user:
        return ""
    return (getattr(user, "unit_key", "") or extract_unit_key(getattr(user, "fullname", "") or getattr(user, "unit_area", "") or getattr(user, "username", ""))).strip()


def _users_for_unit(unit_name):
    domain_options = _task_domain_options()
    canonical_unit = canonicalize_category_value(unit_name or "", domain_options, prefer_stable=True)
    resolved_unit = resolve_category_display(canonical_unit or unit_name, domain_options, fallback_label="").get("display_name", "")
    unit_key = extract_unit_key(resolved_unit or unit_name)
    query = User.query.filter(User.is_active.is_(True))
    if unit_key:
        users = query.filter(User.unit_key == unit_key).order_by(User.fullname.asc()).all()
        if users:
            return users

    if canonical_unit or resolved_unit:
        users = query.filter(User.unit_area.in_([value for value in {canonical_unit, resolved_unit} if value])).order_by(User.fullname.asc()).all()
        if users:
            return users

    users = query.order_by(User.fullname.asc()).all()
    return [user for user in users if is_unit_match(user.unit_area or user.fullname or user.username, resolved_unit or unit_name)]


def _is_commune_role(role_name):
    normalized = re.sub(r"\s+", " ", remove_accents(role_name or "")).strip().lower()
    return any(
        token in normalized
        for token in ["cap xa", "cong an cap xa", "xa thi tran", "phuong thi tran"]
    )


def _resolve_role_assignees(role_id):
    role = db.session.get(AppRole, role_id)
    users = (
        User.query.filter_by(role_id=role_id, is_active=True)
        .order_by(User.fullname.asc())
        .all()
    )

    if role and _is_commune_role(role.name):
        ranking_unit_keys = {
            extract_unit_key(unit_name)
            for unit_name, in db.session.query(RankingUnit.name).all()
            if unit_name and str(unit_name).strip()
        }

        if ranking_unit_keys:
            commune_users = (
                User.query.filter(User.is_active.is_(True), User.unit_area.isnot(None))
                .order_by(User.fullname.asc())
                .all()
            )
            for user in commune_users:
                if _user_unit_key(user) in ranking_unit_keys:
                    users.append(user)

    return _dedupe_users(users)


def _infer_assignment_context(task):
    assignments = task.assignments or []
    assigned_user_ids = [assignment.user_id for assignment in assignments if assignment.user_id]
    context = {
        "mode": "unit",
        "role_ids": [],
        "user_ids": assigned_user_ids,
    }

    if not assigned_user_ids:
        return context

    assigned_users = User.query.filter(User.id.in_(assigned_user_ids)).all()
    if not assigned_users:
        return context

    if task.domain:
        domain_user_ids = {user.id for user in _users_for_unit(task.domain)}
        if domain_user_ids and domain_user_ids == set(assigned_user_ids):
            return context

    role_ids = sorted({user.role_id for user in assigned_users if user.role_id})
    if role_ids:
        role_user_ids = set()
        for role_id in role_ids:
            role_user_ids.update(user.id for user in _resolve_role_assignees(role_id))
        if role_user_ids and role_user_ids == set(assigned_user_ids):
            context["mode"] = "role"
            context["role_ids"] = role_ids
            return context

    context["mode"] = "user"
    return context


def _resolve_assignees(form, domain):
    assign_type = form.get("assign_type", "unit")
    target_ids = [int(uid) for uid in form.getlist("target_users") if str(uid).isdigit()]
    assignee_role_ids = [int(role_id) for role_id in form.getlist("assignee_role_ids") if str(role_id).isdigit()]
    if not assignee_role_ids:
        assignee_role_id = form.get("assignee_role_id")
        if assignee_role_id and str(assignee_role_id).isdigit():
            assignee_role_ids = [int(assignee_role_id)]

    if assign_type == "role":
        if not assignee_role_ids:
            return [], "Cần chọn ít nhất một vai trò nhận việc."
        users = []
        for role_id in assignee_role_ids:
            users.extend(_resolve_role_assignees(role_id))
        users = _dedupe_users(users)
        if not users:
            return [], "Không có cán bộ hoạt động nào thuộc các vai trò đã chọn."
        return users, None

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

    users = _users_for_unit(domain)
    if not users:
        return [], f"Không tìm thấy cán bộ hoạt động nào thuộc đơn vị {domain}."
    return _dedupe_users(users), None


def _can_edit_task(task):
    if not task or not session.get("uid"):
        return False
    return bool(session.get("is_admin")) or task.author_id == session.get("uid")


def _ensure_task_schema():
    try:
        apply_migrations(current_app)
    except Exception as migration_error:
        current_app.logger.warning(f"TASKS migration safeguard failed: {migration_error}")


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

    _ensure_task_schema()

    pro_units = _task_domain_options()
    task_fields = _task_field_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()
    status_items = module_category_options("tasks", "initial_status", "Trạng thái công việc")
    current_domain = canonicalize_category_value(
        request.args.get("domain", "ALL"),
        pro_units,
        prefer_stable=True,
    ) if request.args.get("domain") not in {None, "", "ALL"} else "ALL"
    current_field = canonicalize_category_value(
        request.args.get("field", "ALL"),
        task_fields,
        prefer_stable=True,
    ) if request.args.get("field") not in {None, "", "ALL"} else "ALL"
    now_dt = datetime.now()

    perms = _current_perms()
    is_lead = perms.get("p_task_lead") or session.get("is_admin")
    is_admin = bool(session.get("is_admin"))

    active_users = User.query.filter_by(is_active=True).order_by(User.unit_area.asc(), User.fullname.asc()).all()
    active_users = apply_reference_display(
        sync_record_categories(active_users, module_category_options("contacts", "unit_name", "Đơn vị"), attr_name="unit_area", prefer_stable=True),
        "unit_area",
        module_category_options("contacts", "unit_name", "Đơn vị"),
        display_attr="unit_area_display",
        fallback_label="Chưa có đơn vị",
    )
    roles = AppRole.query.order_by(AppRole.name.asc()).all()

    if request.method == "POST" and is_lead:
        title = (request.form.get("title") or "").strip()
        category = canonicalize_category_value(
            request.form.get("category") or "",
            task_fields,
            prefer_stable=True,
        )
        domain = canonicalize_category_value(
            request.form.get("unit_name") or request.form.get("domain") or "",
            pro_units,
            prefer_stable=True,
        )
        content = (request.form.get("description") or request.form.get("content") or "").strip()
        priority = canonicalize_category_value(
            request.form.get("priority") or "Trung bình",
            priority_items,
            prefer_stable=True,
        )
        task_type = canonicalize_category_value(
            request.form.get("task_type") or "Công việc thường xuyên",
            task_types,
            prefer_stable=True,
        )

        if not title:
            flash("Tiêu đề công việc không được để trống.", "danger")
            return redirect(url_for("tasks_bp.tasks"))

        if task_fields and not category:
            flash("Cần chọn lĩnh vực công việc.", "danger")
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
            category=category,
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

        domain_display = resolve_category_display(domain, pro_units, fallback_label=domain).get("display_name") or domain
        category_display = resolve_category_display(category, task_fields, fallback_label=category).get("display_name") or category

        notify_message = (
            f"Đơn vị {domain_display} được giao: {new_task.title}"
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
    if current_field != "ALL":
        query = query.filter_by(category=current_field)
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
    all_tasks = sync_record_categories(all_tasks, task_fields, attr_name="category", prefer_stable=True)
    all_tasks = sync_record_categories(all_tasks, pro_units, attr_name="domain", prefer_stable=True)
    all_tasks = sync_record_categories(all_tasks, task_types, attr_name="task_type", prefer_stable=True)
    all_tasks = sync_record_categories(all_tasks, priority_items, attr_name="priority", prefer_stable=True)
    task_filters_source = []
    uncategorized_count = 0

    for task in all_tasks:
        task_metrics = _decorate_task(task, session["uid"], is_lead)
        category_meta = _decorate_task_categories(task, task_fields, pro_units, task_types, priority_items)
        if task_metrics["is_overdue"]:
            overdue_count += 1
        if task_metrics["display_status"] == COMPLETED_STATUS:
            completed_count += 1
        if category_meta["category"]["option"]:
            task_filters_source.append({"category_filter": task.category_filter})
        elif not task.category:
            uncategorized_count += 1
            task_filters_source.append({"category_filter": "__uncategorized__"})
        else:
            task_filters_source.append({"category_filter": task.category_filter})

    field_counts = {
        item["filter_value"]: item["count"]
        for item in category_filter_counts(
            task_filters_source,
            task_fields,
            empty_label="Chưa phân lĩnh vực",
        )
    }
    uncategorized_count = field_counts.get("__uncategorized__", 0)

    return render_template(
        "tasks.html",
        tasks=all_tasks,
        users=active_users,
        roles=roles,
        pro_units=stable_form_category_options(pro_units),
        pro_unit_labels=pro_units,
        task_fields=task_fields,
        field_counts=field_counts,
        uncategorized_count=uncategorized_count,
        task_types=stable_form_category_options(task_types),
        task_type_labels=task_types,
        priority_items=stable_form_category_options(priority_items),
        priority_labels=priority_items,
        status_items=status_items,
        current_domain=current_domain,
        current_field=current_field,
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

    _ensure_task_schema()

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    pro_units = _task_domain_options()
    task_fields = _task_field_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()
    sync_record_categories([task], task_fields, attr_name="category", prefer_stable=True)
    sync_record_categories([task], pro_units, attr_name="domain", prefer_stable=True)
    sync_record_categories([task], task_types, attr_name="task_type", prefer_stable=True)
    sync_record_categories([task], priority_items, attr_name="priority", prefer_stable=True)
    _decorate_task_categories(task, task_fields, pro_units, task_types, priority_items)
    active_users = User.query.filter_by(is_active=True).order_by(User.unit_area.asc(), User.fullname.asc()).all()
    active_users = apply_reference_display(
        sync_record_categories(active_users, module_category_options("contacts", "unit_name", "Đơn vị"), attr_name="unit_area", prefer_stable=True),
        "unit_area",
        module_category_options("contacts", "unit_name", "Đơn vị"),
        display_attr="unit_area_display",
        fallback_label="Chưa có đơn vị",
    )
    roles = AppRole.query.order_by(AppRole.name.asc()).all()
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
    assign_users = [user for _, user in assigns]
    unit_options = module_category_options("contacts", "unit_name", "Đơn vị")
    sync_record_categories(assign_users, unit_options, attr_name="unit_area", prefer_stable=True)
    apply_reference_display(assign_users, "unit_area", unit_options, display_attr="unit_area_display", fallback_label="Chưa có đơn vị")

    task_metrics = _decorate_task(task, session["uid"], is_lead)
    user_assign = task_metrics["user_assignment"]
    assignment_context = _infer_assignment_context(task)

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
        pro_units=stable_form_category_options(pro_units),
        task_fields=stable_form_category_options(task_fields),
        task_types=stable_form_category_options(task_types),
        priority_items=stable_form_category_options(priority_items),
        users=active_users,
        roles=roles,
        assignment_context=assignment_context,
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

    _ensure_task_schema()

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    if not _can_edit_task(task):
        flash("Bạn không có quyền sửa công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    title = (request.form.get("title") or "").strip()
    task_fields = _task_field_options()
    pro_units = _task_domain_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()

    category = canonicalize_category_value(
        request.form.get("category") or task.category or "",
        task_fields,
        prefer_stable=True,
    )
    domain = canonicalize_category_value(
        request.form.get("domain") or "",
        pro_units,
        prefer_stable=True,
    )
    content = (request.form.get("content") or "").strip()
    priority = canonicalize_category_value(
        request.form.get("priority") or "Trung bình",
        priority_items,
        prefer_stable=True,
    )
    task_type = canonicalize_category_value(
        request.form.get("task_type") or "Công việc thường xuyên",
        task_types,
        prefer_stable=True,
    )

    if not title:
        flash("Tiêu đề công việc không được để trống.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.title = title
    task.category = category
    task.domain = domain
    task.content = content
    task.priority = priority
    task.task_type = task_type
    task.deadline = _parse_deadline(request.form)

    refreshed_assignee_count = None
    new_assignees_to_notify = []
    if request.form.get("refresh_assignments") == "1":
        assignees, error_message = _resolve_assignees(request.form, task.domain)
        if error_message:
            flash(error_message, "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))

        existing_assignments = {assignment.user_id: assignment for assignment in task.assignments}
        new_assignee_ids = {user.id for user in assignees}

        for assignment in list(task.assignments):
            if assignment.user_id not in new_assignee_ids:
                db.session.delete(assignment)

        for user in assignees:
            if user.id not in existing_assignments:
                db.session.add(
                    TaskAssignment(task_id=task.id, user_id=user.id, status="Chưa tiếp nhận")
                )
                new_assignees_to_notify.append(user)

        refreshed_assignee_count = len(new_assignee_ids)

    attachment = request.files.get("task_file")
    if attachment and attachment.filename:
        attachment_name = secure_filename(attachment.filename)
        attachment.save(os.path.join(current_app.root_path, "task_files", attachment_name))
        task.file_path = attachment_name

    db.session.commit()

    for user in new_assignees_to_notify:
        push_notif(user.id, "Cập nhật công việc", f"Bạn vừa được bổ sung vào công việc: {task.title}", f"/tasks/{task.id}")

    log_action(
        session["uid"],
        session.get("fullname", "Quản trị"),
        "Cập nhật công việc",
        "Công việc",
        f"Task #{task.id} | {task.title}" + (
            f" | cap_nhat_phan_cong={refreshed_assignee_count}" if refreshed_assignee_count is not None else ""
        ),
    )
    success_message = "Đã cập nhật công việc."
    if refreshed_assignee_count is not None:
        success_message = f"Đã cập nhật công việc và đồng bộ {refreshed_assignee_count} người được giao."
    flash(success_message, "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))


@tasks_bp.route("/tasks/<int:tid>/update_status", methods=["POST"])
def update_task_status(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

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

    _ensure_task_schema()

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
