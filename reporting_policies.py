# -*- coding: utf-8 -*-


REPORT_WORKSPACE_PERMISSIONS = [
    ("form", "view"),
    ("input", "view"),
    ("input", "process"),
    ("input", "exec"),
    ("stat", "view"),
    ("stat", "process"),
    ("stat", "exec"),
]

REPORT_PROGRESS_PERMISSIONS = [
    ("form", "view"),
    ("form", "process"),
    ("input", "view"),
    ("input", "process"),
    ("input", "exec"),
    ("stat", "view"),
    ("stat", "process"),
    ("stat", "exec"),
]


def has_any_module_permission(perms, permission_pairs, permission_checker, is_admin=False):
    if is_admin:
        return True
    return any(
        permission_checker(perms, module_name, action_name, is_admin=is_admin)
        for module_name, action_name in (permission_pairs or [])
    )


def can_manage_report_templates(perms, permission_checker, is_admin=False):
    return bool(permission_checker(perms, "form", "process", is_admin=is_admin))


def can_access_report_workspace(perms, permission_checker, is_admin=False):
    return has_any_module_permission(
        perms,
        REPORT_WORKSPACE_PERMISSIONS,
        permission_checker,
        is_admin=is_admin,
    )


def can_view_report_progress(perms, permission_checker, is_admin=False):
    return has_any_module_permission(
        perms,
        REPORT_PROGRESS_PERMISSIONS,
        permission_checker,
        is_admin=is_admin,
    )


def filter_report_manager_users(users, current_uid, role_permission_loader, permission_checker, is_admin=False):
    recipients = []
    for user in users or []:
        if current_uid and getattr(user, "id", None) == current_uid:
            continue
        role = getattr(user, "role", None)
        perms = role_permission_loader(role)
        if (
            permission_checker(perms, "form", "process", is_admin=is_admin)
            or permission_checker(perms, "input", "process", is_admin=is_admin)
            or permission_checker(perms, "stat", "process", is_admin=is_admin)
        ):
            recipients.append(user)
    return recipients
