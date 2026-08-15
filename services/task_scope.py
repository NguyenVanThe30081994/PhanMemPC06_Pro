# -*- coding: utf-8 -*-
"""
Phạm vi giao việc / xem / quản lý (scope) + đọc tham số người nhận từ form.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi. Riêng `_infer_assignment_context` còn ở
routes/tasks.py vì phụ thuộc `_task_assignment_rows` (chưa tách).
"""

from category_helpers import canonicalize_category_value
from services.task_categories import _task_domain_options
from task_policies import (
    build_scope_summary,
    load_assignment_scope,
    load_manager_scope,
    load_viewer_scope,
    scope_preview_names,
    store_assignment_scope,
    store_manager_scope,
    store_viewer_scope,
)

import re


def _load_assignment_scope(task):
    return load_assignment_scope(task)


def _load_viewer_scope(task):
    return load_viewer_scope(task)


def _load_manager_scope(task):
    return load_manager_scope(task)


def _store_assignment_scope(task, assign_type, domain="", role_ids=None, user_ids=None):
    return store_assignment_scope(task, assign_type, domain=domain, role_ids=role_ids, user_ids=user_ids)


def _store_viewer_scope(task, mode="none", role_ids=None, user_ids=None):
    return store_viewer_scope(task, mode=mode, role_ids=role_ids, user_ids=user_ids)


def _store_manager_scope(task, mode="none", role_ids=None, user_ids=None):
    return store_manager_scope(task, mode=mode, role_ids=role_ids, user_ids=user_ids)


def _infer_viewer_context(task):
    stored_scope = _load_viewer_scope(task)
    return {
        "mode": stored_scope.get("mode") or "none",
        "role_ids": stored_scope.get("role_ids") or [],
        "user_ids": stored_scope.get("user_ids") or [],
    }


def _infer_manager_context(task):
    stored_scope = _load_manager_scope(task)
    return {
        "mode": stored_scope.get("mode") or "none",
        "role_ids": stored_scope.get("role_ids") or [],
        "user_ids": stored_scope.get("user_ids") or [],
    }


def _scope_preview_names(names, empty_label="Chưa cấu hình riêng"):
    return scope_preview_names(names, empty_label=empty_label)


def _build_scope_summary(context, role_lookup=None, user_lookup=None, none_label="Chưa cấu hình riêng"):
    return build_scope_summary(context, role_lookup=role_lookup, user_lookup=user_lookup, none_label=none_label)


def _requested_role_ids(form):
    role_ids = [int(role_id) for role_id in form.getlist("assignee_role_ids") if str(role_id).isdigit()]
    if not role_ids:
        assignee_role_id = form.get("assignee_role_id")
        if assignee_role_id and str(assignee_role_id).isdigit():
            role_ids = [int(assignee_role_id)]
    return sorted(set(role_ids))


def _requested_user_ids(form):
    return sorted({int(uid) for uid in form.getlist("target_users") if str(uid).isdigit()})


def _requested_unit_domains(form, field_name="child_domains", fallback_field="child_domain"):
    domains = []
    raw_values = form.getlist(field_name)
    if not raw_values:
        fallback_value = form.get(fallback_field)
        if fallback_value:
            raw_values = [fallback_value]
    seen = set()
    domain_options = _task_domain_options()
    for raw_value in raw_values:
        normalized = canonicalize_category_value(raw_value or "", domain_options, prefer_stable=True)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        domains.append(normalized)
    return domains


def _requested_viewer_role_ids(form):
    return sorted({int(role_id) for role_id in form.getlist("viewer_role_ids") if str(role_id).isdigit()})


def _requested_viewer_user_ids(form):
    return sorted({int(uid) for uid in form.getlist("viewer_user_ids") if str(uid).isdigit()})


def _requested_manager_role_ids(form):
    return sorted({int(role_id) for role_id in form.getlist("manager_role_ids") if str(role_id).isdigit()})


def _requested_manager_user_ids(form):
    return sorted({int(uid) for uid in form.getlist("manager_user_ids") if str(uid).isdigit()})


def _parse_bulk_child_task_titles(raw_value):
    titles = []
    seen = set()
    for line in str(raw_value or "").splitlines():
        cleaned = re.sub(r"^\s*(?:[-*+]|[0-9]+[.)])\s*", "", line).strip()
        if not cleaned:
            continue
        normalized = re.sub(r"\s+", " ", cleaned)
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        titles.append(normalized[:255])
    return titles
