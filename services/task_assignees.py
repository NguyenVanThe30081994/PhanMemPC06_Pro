# -*- coding: utf-8 -*-
"""
Phân giải người nhận việc từ form: theo đơn vị / vai trò / cá nhân, cùng danh sách
người xem và người xử lý (viewer/manager scope).

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ.
"""

from datetime import datetime

from models import TaskAssignment, User, db
from services.task_scope import (
    _requested_manager_role_ids,
    _requested_manager_user_ids,
    _requested_role_ids,
    _requested_unit_domains,
    _requested_user_ids,
    _requested_viewer_role_ids,
    _requested_viewer_user_ids,
)
from services.task_units import _dedupe_users, _resolve_role_assignees, _users_for_unit


def _resolve_assignees(form, domain):
    assign_type = form.get("assign_type", "unit")
    target_ids = _requested_user_ids(form)
    assignee_role_ids = _requested_role_ids(form)
    unit_domains = _requested_unit_domains(form)
    return _resolve_assignees_by_mode(
        assign_type,
        domain=domain,
        unit_domains=unit_domains,
        target_ids=target_ids,
        assignee_role_ids=assignee_role_ids,
    )

def _resolve_assignees_by_mode(assign_type, domain="", unit_domains=None, target_ids=None, assignee_role_ids=None):
    target_ids = sorted({int(uid) for uid in (target_ids or []) if str(uid).isdigit()})
    assignee_role_ids = sorted({int(role_id) for role_id in (assignee_role_ids or []) if str(role_id).isdigit()})
    unit_domains = [str(value or "").strip() for value in (unit_domains or []) if str(value or "").strip()]

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

    if not unit_domains:
        if domain:
            unit_domains = [domain]
        else:
            return [], "Cần chọn ít nhất một đơn vị nghiệp vụ trước khi giao theo đơn vị."

    users = []
    missing_domains = []
    for unit_domain in unit_domains:
        unit_users = _users_for_unit(unit_domain)
        if unit_users:
            users.extend(unit_users)
        else:
            missing_domains.append(unit_domain)
    users = _dedupe_users(users)
    if not users:
        if missing_domains:
            return [], f"Không tìm thấy cán bộ hoạt động nào thuộc các đơn vị đã chọn: {', '.join(missing_domains)}."
        return [], "Không tìm thấy cán bộ hoạt động nào thuộc các đơn vị đã chọn."
    return users, None

def _resolve_viewers(form):
    mode = form.get("viewer_scope_mode", "none")
    role_ids = _requested_viewer_role_ids(form)
    user_ids = _requested_viewer_user_ids(form)

    if mode == "role":
        if not role_ids:
            return [], "Cần chọn ít nhất một vai trò xem việc."
        users = []
        for role_id in role_ids:
            users.extend(_resolve_role_assignees(role_id))
        users = _dedupe_users(users)
        if not users:
            return [], "Không có cán bộ hoạt động nào thuộc các vai trò xem việc đã chọn."
        return users, None

    if mode == "user":
        if not user_ids:
            return [], "Cần chọn ít nhất một tài khoản xem việc."
        users = (
            User.query.filter(User.id.in_(user_ids), User.is_active.is_(True))
            .order_by(User.fullname.asc())
            .all()
        )
        if not users:
            return [], "Danh sách tài khoản xem việc không hợp lệ hoặc đã bị khóa."
        return _dedupe_users(users), None

    return [], None

def _resolve_managers(form):
    mode = form.get("manager_scope_mode", "none")
    role_ids = _requested_manager_role_ids(form)
    user_ids = _requested_manager_user_ids(form)

    if mode == "role":
        if not role_ids:
            return [], "Cần chọn ít nhất một vai trò xử lý công việc."
        users = []
        for role_id in role_ids:
            users.extend(_resolve_role_assignees(role_id))
        users = _dedupe_users(users)
        if not users:
            return [], "Không có cán bộ hoạt động nào thuộc các vai trò xử lý đã chọn."
        return users, None

    if mode == "user":
        if not user_ids:
            return [], "Cần chọn ít nhất một tài khoản xử lý công việc."
        users = (
            User.query.filter(User.id.in_(user_ids), User.is_active.is_(True))
            .order_by(User.fullname.asc())
            .all()
        )
        if not users:
            return [], "Danh sách tài khoản xử lý không hợp lệ hoặc đã bị khóa."
        return _dedupe_users(users), None

    return [], None


def _create_assignment_records(task, assignees, assign_type="user", task_item=None, title_snapshot="", is_required=True, role_id=None):
    created = []
    for user in assignees or []:
        assignment = TaskAssignment(
            task_id=task.id,
            task_item_id=getattr(task_item, "id", None),
            user_id=user.id,
            assignee_type=assign_type,
            role_id=role_id if role_id else (getattr(user, "role_id", None) if assign_type == "role" else None),
            title_snapshot=title_snapshot or getattr(task_item, "title", None) or task.title,
            status="assigned",
            is_required=bool(is_required),
            assigned_at=datetime.now(),
        )
        db.session.add(assignment)
        created.append(assignment)
    return created
