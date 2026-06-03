# -*- coding: utf-8 -*-
import json


ASSIGNMENT_SCOPE_ALLOWED_MODES = {"unit", "role", "user"}
PARTICIPANT_SCOPE_ALLOWED_MODES = {"none", "role", "user"}


def _normalized_int_list(values):
    return sorted({int(value) for value in (values or []) if str(value).isdigit()})


def assignment_scope_payload(assign_type, domain="", role_ids=None, user_ids=None):
    normalized_mode = assign_type if assign_type in ASSIGNMENT_SCOPE_ALLOWED_MODES else "unit"
    payload = {
        "mode": normalized_mode,
        "domain": (domain or "").strip(),
        "role_ids": _normalized_int_list(role_ids),
        "user_ids": _normalized_int_list(user_ids),
    }
    if normalized_mode == "unit":
        payload["role_ids"] = []
        payload["user_ids"] = []
    elif normalized_mode == "role":
        payload["user_ids"] = []
    elif normalized_mode == "user":
        payload["role_ids"] = []
    return payload


def participant_scope_payload(mode="none", role_ids=None, user_ids=None):
    normalized_mode = mode if mode in PARTICIPANT_SCOPE_ALLOWED_MODES else "none"
    payload = {
        "mode": normalized_mode,
        "role_ids": _normalized_int_list(role_ids),
        "user_ids": _normalized_int_list(user_ids),
    }
    if normalized_mode == "role":
        payload["user_ids"] = []
    elif normalized_mode == "user":
        payload["role_ids"] = []
    else:
        payload["role_ids"] = []
        payload["user_ids"] = []
    return payload


def viewer_scope_payload(mode="none", role_ids=None, user_ids=None):
    return participant_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)


def manager_scope_payload(mode="none", role_ids=None, user_ids=None):
    return participant_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)


def _load_json_payload(raw_value):
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_assignment_scope(task):
    if not task:
        return {}

    payload = _load_json_payload(getattr(task, "assignment_scope_json", None))
    assign_type = payload.get("mode") or getattr(task, "assign_type", None)
    if not getattr(task, "assignment_scope_json", None) and not assign_type:
        return {}

    return assignment_scope_payload(
        assign_type,
        domain=payload.get("domain") or getattr(task, "domain", "") or "",
        role_ids=payload.get("role_ids") or [],
        user_ids=payload.get("user_ids") or [],
    )


def load_viewer_scope(task):
    if not task:
        return viewer_scope_payload("none")
    payload = _load_json_payload(getattr(task, "viewer_scope_json", None))
    return viewer_scope_payload(
        payload.get("mode") or "none",
        role_ids=payload.get("role_ids") or [],
        user_ids=payload.get("user_ids") or [],
    )


def load_manager_scope(task):
    if not task:
        return manager_scope_payload("none")
    payload = _load_json_payload(getattr(task, "manager_scope_json", None))
    return manager_scope_payload(
        payload.get("mode") or "none",
        role_ids=payload.get("role_ids") or [],
        user_ids=payload.get("user_ids") or [],
    )


def store_assignment_scope(task, assign_type, domain="", role_ids=None, user_ids=None):
    payload = assignment_scope_payload(assign_type, domain=domain, role_ids=role_ids, user_ids=user_ids)
    task.assign_type = payload["mode"]
    task.assignment_scope_json = json.dumps(payload, ensure_ascii=False)
    return payload


def store_viewer_scope(task, mode="none", role_ids=None, user_ids=None):
    payload = viewer_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)
    task.viewer_scope_json = json.dumps(payload, ensure_ascii=False)
    return payload


def store_manager_scope(task, mode="none", role_ids=None, user_ids=None):
    payload = manager_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)
    task.manager_scope_json = json.dumps(payload, ensure_ascii=False)
    return payload


def scope_preview_names(names, empty_label="Chưa cấu hình riêng"):
    cleaned_names = [str(name).strip() for name in (names or []) if str(name).strip()]
    if not cleaned_names:
        return empty_label
    if len(cleaned_names) <= 2:
        return ", ".join(cleaned_names)
    return f"{', '.join(cleaned_names[:2])} +{len(cleaned_names) - 2}"


def build_scope_summary(context, role_lookup=None, user_lookup=None, none_label="Chưa cấu hình riêng"):
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    mode = (context or {}).get("mode") or "none"
    role_ids = (context or {}).get("role_ids") or []
    user_ids = (context or {}).get("user_ids") or []

    if mode == "role":
        role_names = [role_lookup.get(role_id) for role_id in role_ids if role_lookup.get(role_id)]
        return {
            "mode": "role",
            "mode_label": "Theo vai trò",
            "value_label": scope_preview_names(role_names, empty_label="Chưa chọn vai trò"),
            "count": len(role_names),
        }

    if mode == "user":
        user_names = [user_lookup.get(user_id) for user_id in user_ids if user_lookup.get(user_id)]
        return {
            "mode": "user",
            "mode_label": "Theo cá nhân",
            "value_label": scope_preview_names(user_names, empty_label="Chưa chọn tài khoản"),
            "count": len(user_names),
        }

    return {
        "mode": "none",
        "mode_label": "Mặc định",
        "value_label": none_label,
        "count": 0,
    }


def scope_allows_user(scope, user):
    if not scope or not user:
        return False
    mode = (scope.get("mode") or "none").strip().lower()
    if mode == "role":
        return getattr(user, "role_id", None) in (scope.get("role_ids") or [])
    if mode == "user":
        return getattr(user, "id", None) in (scope.get("user_ids") or [])
    return False


def can_manage_task(task, session_uid, is_admin, can_process_module, load_manager_scope_fn, user=None, load_parent_task_fn=None):
    if not task or not session_uid:
        return False
    if is_admin or getattr(task, "author_id", None) == session_uid or can_process_module:
        return True
    if not user:
        return False
    if scope_allows_user(load_manager_scope_fn(task), user):
        return True
    parent_task = load_parent_task_fn(task) if load_parent_task_fn else getattr(task, "parent_task", None)
    if parent_task:
        return can_manage_task(
            parent_task,
            session_uid,
            is_admin,
            can_process_module,
            load_manager_scope_fn,
            user=user,
            load_parent_task_fn=load_parent_task_fn,
        )
    return False


def can_delete_task(task, session_uid, is_admin=False, is_lead=False, can_manage=False):
    if not task or not session_uid:
        return False
    if is_admin or getattr(task, "author_id", None) == session_uid or is_lead:
        return True
    return bool(can_manage)


def can_watch_task(task, load_viewer_scope_fn, user=None, load_parent_task_fn=None):
    if not task or not user:
        return False
    if scope_allows_user(load_viewer_scope_fn(task), user):
        return True
    parent_task = load_parent_task_fn(task) if load_parent_task_fn else getattr(task, "parent_task", None)
    if parent_task:
        return can_watch_task(
            parent_task,
            load_viewer_scope_fn,
            user=user,
            load_parent_task_fn=load_parent_task_fn,
        )
    return False


def can_view_task(task, session_uid, is_admin=False, is_lead=False, is_executor=False, can_manage=False, can_watch=False, has_visible_child_tasks=False):
    if not task or not session_uid:
        return False
    if is_admin or is_lead or getattr(task, "author_id", None) == session_uid:
        return True
    if is_executor or can_manage or can_watch:
        return True
    return bool(has_visible_child_tasks)
