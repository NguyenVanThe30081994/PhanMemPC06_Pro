# -*- coding: utf-8 -*-
"""
Kiểm tra quyền module task cho route (view/process/exec + ủy quyền).

Tách từ routes/tasks.py (Pha 2). Dùng session + g cache như bản gốc;
is_admin luôn tính từ DB (permissions.current_is_admin), KHÔNG tin session.
"""

from flask import g, has_request_context, session

from models import db, AppRole
from permissions import current_is_admin
from utils import has_module_permission, normalize_permission_payload


def _current_perms():
    if has_request_context():
        cached = getattr(g, "_task_current_perms_cache", None)
        if cached is not None:
            return cached
    role = db.session.get(AppRole, session.get("role_id")) if session.get("role_id") else None
    if role and role.perms:
        try:
            perms = normalize_permission_payload(role.perms, is_admin=current_is_admin(), role_name=getattr(role, "name", ""))
            if has_request_context():
                g._task_current_perms_cache = perms
            return perms
        except Exception:
            return {}
    if has_request_context():
        g._task_current_perms_cache = {}
    return {}


def _can_view_task_module(perms=None):
    perms = perms or _current_perms()
    return has_module_permission(perms, "task", "view", is_admin=current_is_admin())


def _can_process_task_module(perms=None):
    perms = perms or _current_perms()
    from permissions import current_delegation_grants
    return bool(
        has_module_permission(perms, "task", "process", is_admin=current_is_admin())
        or current_delegation_grants("task", "process")
    )


def _can_view_all_tasks(perms=None):
    perms = perms or _current_perms()
    return has_module_permission(perms, "task", "view", is_admin=current_is_admin())


def _can_execute_task_module(perms=None):
    perms = perms or _current_perms()
    from permissions import current_delegation_grants
    return bool(
        has_module_permission(perms, "task", "exec", is_admin=current_is_admin())
        or has_module_permission(perms, "task", "process", is_admin=current_is_admin())
        or current_delegation_grants("task", "exec")
        or current_delegation_grants("task", "process")
    )
