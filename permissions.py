# -*- coding: utf-8 -*-
"""
Module phân quyền tập trung.

Nguyên tắc:
- KHÔNG tin giá trị is_admin lưu trong session (có thể stale khi đổi vai trò giữa phiên).
- Mỗi request tính lại authz từ DB: is_admin, perms (hợp của tất cả vai trò hiệu lực).
- Mọi route phải chặn bằng require_perm(module, tier) thay vì kiểm tra is_admin rời rạc.
"""
import json
from functools import wraps

from flask import g, session, request, redirect, url_for, flash, abort

from models import db, AppRole
from utils import (
    _role_name_key,
    match_standard_role,
    normalize_permission_payload,
    has_module_permission,
    has_any_module_permission,
)


ADMIN_ROLE_NAMES = ("quản trị hệ thống", "admin_system", "admin")


def is_admin_role(role):
    """Một vai trò có phải vai trò quản trị hệ thống hay không."""
    if not role:
        return False
    key = _role_name_key(role.name)
    if key in ADMIN_ROLE_NAMES:
        return True
    # Khớp gần qua alias chuẩn
    role_def = match_standard_role(role.name)
    return bool(role_def and role_def.get("level") == "system")


def user_effective_roles(user):
    """Danh sách vai trò hiệu lực của user: vai trò chính + vai trò phụ (UserRole).

    Trả về list AppRole, không trùng.
    """
    roles = []
    if not user:
        return roles
    try:
        if user.role_id:
            primary = db.session.get(AppRole, user.role_id)
            if primary:
                roles.append(primary)
        for user_role in (user.user_roles or []):
            extra = db.session.get(AppRole, user_role.role_id) if user_role.role_id else None
            if extra and all(r.id != extra.id for r in roles):
                roles.append(extra)
    except Exception:
        pass
    return roles


def user_is_admin(user):
    """User có bất kỳ vai trò quản trị hệ thống nào không. Không có bypass username."""
    if not user:
        return False
    return any(is_admin_role(role) for role in user_effective_roles(user))


def user_perms_payload(user):
    """Hợp (union) quyền của tất cả vai trò hiệu lực, đã chuẩn hóa.

    Trả về (perms_dict, role_name, is_admin) — role_name là tên vai trò chính.
    """
    if not user:
        return {}, "Thành viên", False
    is_admin = user_is_admin(user)
    merged = {}
    for role in user_effective_roles(user):
        if not role or not role.perms:
            continue
        try:
            parsed = json.loads(role.perms) if isinstance(role.perms, str) else dict(role.perms or {})
            for key, value in parsed.items():
                merged[key] = merged.get(key, 0) or value
        except Exception:
            continue
    primary = db.session.get(AppRole, user.role_id) if user.role_id else None
    role_name = primary.name if primary else "Thành viên"
    normalized = normalize_permission_payload(merged, is_admin=is_admin, role_name=role_name)
    return normalized, role_name, is_admin


def load_current_authz():
    """Tính authz cho user hiện tại (từ session.uid) và cache vào g.

    Trả về dict {user, is_admin, perms, role_name}.
    """
    cached = getattr(g, "_authz", None)
    if cached is not None:
        return cached
    uid = session.get("uid")
    if not uid:
        g._authz = {"user": None, "is_admin": False, "perms": {}, "role_name": "Thành viên"}
        return g._authz
    user = db.session.get(__import__("models", fromlist=["User"]).User, uid)
    if not user:
        g._authz = {"user": None, "is_admin": False, "perms": {}, "role_name": "Thành viên"}
        return g._authz
    perms, role_name, is_admin = user_perms_payload(user)
    g._authz = {"user": user, "is_admin": is_admin, "perms": perms, "role_name": role_name}
    return g._authz


def current_authz():
    return load_current_authz()


def current_user():
    return load_current_authz()["user"]


def current_is_admin():
    return bool(load_current_authz()["is_admin"])


def current_perms():
    return load_current_authz()["perms"]


def current_role_name():
    return load_current_authz()["role_name"]


def can_module(module_code, tier="view"):
    """Kiểm tra quyền module theo authz hiện tại (dùng cho route server-side).

    Bao gồm quyền được ủy quyền tạm thời (delegation) ở mức process/exec.
    """
    authz = load_current_authz()
    if has_module_permission(
        authz["perms"],
        module_code,
        tier=tier,
        is_admin=authz["is_admin"],
        role_name=authz["role_name"],
    ):
        return True
    normalized_tier = (tier or "view").strip().lower()
    if normalized_tier in {"process", "exec"}:
        return current_delegation_grants(module_code, normalized_tier)
    return False


def can_any_module(module_codes, tier="view"):
    authz = load_current_authz()
    return has_any_module_permission(
        authz["perms"],
        module_codes,
        tier=tier,
        is_admin=authz["is_admin"],
        role_name=authz["role_name"],
    )


def can_manage_with_system(module_code):
    return bool(can_module(module_code, "process") or can_module("sys", "process"))


def user_delegated_modules(user):
    """Set các module user đang được ủy quyền (chưa hết hạn, còn hiệu lực). '*' = toàn bộ."""
    if not user:
        return set()
    from datetime import date
    from models import Delegation
    today = date.today()
    result = set()
    try:
        rows = Delegation.query.filter_by(delegatee_id=user.id, is_active=True).all()
        for d in rows:
            if d.from_date and d.from_date > today:
                continue
            if d.to_date and d.to_date < today:
                continue
            result.add((d.module_code or '*').strip() or '*')
    except Exception:
        pass
    return result


def is_delegated_for(user, module_code):
    """User có được ủy quyền module cụ thể không."""
    if not user:
        return False
    modules = user_delegated_modules(user)
    return '*' in modules or (module_code or '').strip() in modules


def current_delegation_grants(module_code, tier='process'):
    """User hiện tại được ủy quyền (bởi người có quyền) module ở mức tier không.

    Delegatee được hưởng đúng quyền tier của delegator (không vượt quá).
    """
    user = current_user()
    if not user or not is_delegated_for(user, module_code):
        return False
    from datetime import date
    from models import Delegation
    today = date.today()
    try:
        rows = Delegation.query.filter_by(delegatee_id=user.id, is_active=True).all()
        for d in rows:
            module = (d.module_code or '*').strip() or '*'
            if module != '*' and module != (module_code or '').strip():
                continue
            if d.from_date and d.from_date > today:
                continue
            if d.to_date and d.to_date < today:
                continue
            delegator = db.session.get(__import__("models", fromlist=["User"]).User, d.delegator_id)
            if not delegator:
                continue
            dperms, dname, disadmin = user_perms_payload(delegator)
            if has_module_permission(dperms, module_code, tier=tier, is_admin=disadmin, role_name=dname):
                return True
    except Exception:
        pass
    return False


def can_manage_module_object(module_code, obj_creator_id=None, obj_unit_scope=None):
    """Object-level control cho các module nghiệp vụ (thông báo, danh bạ, tài liệu...).

    Cho phép khi:
    - Quản trị hệ thống, hoặc
    - Có quyền process module, hoặc
    - Người tạo object (obj_creator_id == uid), hoặc
    - Đơn vị của user thuộc phạm vi đơn vị của object (data-scope theo cây).
    """
    authz = load_current_authz()
    user = authz["user"]
    if not user:
        return False
    if authz["is_admin"]:
        return True
    if has_module_permission(authz["perms"], module_code, "process", is_admin=authz["is_admin"], role_name=authz["role_name"]):
        return True
    if has_module_permission(authz["perms"], "sys", "process", is_admin=authz["is_admin"], role_name=authz["role_name"]):
        return True
    if obj_creator_id and int(obj_creator_id) == int(user.id):
        return True
    if obj_unit_scope:
        from utils import unit_subtree_ids
        subtree = unit_subtree_ids(getattr(user, "unit_id", None))
        if any(int(unit_id) in subtree for unit_id in (obj_unit_scope if isinstance(obj_unit_scope, (list, tuple, set)) else [obj_unit_scope])):
            return True
    return False


def require_perm(module_code, tier="view"):
    """Decorator chặn route theo quyền module (chuẩn hóa mọi nơi).

    - Chưa đăng nhập → redirect login
    - Không đủ quyền → 403
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("uid"):
                flash("Vui lòng đăng nhập để tiếp tục", "warning")
                return redirect(url_for("auth_bp.login"))
            if not can_module(module_code, tier):
                if request.endpoint and request.endpoint.startswith("api_bp."):
                    return abort(403)
                flash("Bạn không có quyền thực hiện thao tác này", "danger")
                return redirect(url_for("tasks_bp.tasks"))
            return f(*args, **kwargs)
        return wrapper
    return decorator
