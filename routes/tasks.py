# -*- coding: utf-8 -*-
import json
import io
import os
import re
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, g, has_request_context, redirect, request, session, url_for, send_file
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename
try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

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
REPORT_PREFIX = "[BÁO CÁO]"
REPORT_ATTACHMENT_RE = re.compile(r"\s*\(Đính kèm:\s*([^)]+)\)\s*$")


def _task_domain_options():
    return module_category_options("tasks", "domain", "Đội nghiệp vụ")


def _task_field_options():
    return module_category_options("news", "category", "Lĩnh vực", "Đội nghiệp vụ")


def _task_type_options():
    return module_category_options("tasks", "task_type", "Loại công việc")


def _task_priority_options():
    return module_category_options("tasks", "priority", "Mức độ ưu tiên")


def _task_assignment_unit_options():
    if has_request_context():
        cached = getattr(g, "_task_assignment_unit_options", None)
        if cached is not None:
            return cached

    merged = []
    seen = set()
    for options in (
        module_category_options("contacts", "unit_name", "Đơn vị"),
        _task_domain_options(),
    ):
        for item in options or []:
            stable_value = (item.get("stable_value") or "").strip()
            option_key = stable_value or (item.get("value") or "").strip() or (item.get("name") or "").strip()
            if not option_key or option_key in seen:
                continue
            seen.add(option_key)
            merged.append(item)

    if has_request_context():
        g._task_assignment_unit_options = merged
    return merged


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


def _is_category_item_reference(value):
    return bool(re.fullmatch(r"category_item:\d+", (value or "").strip().lower()))


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
    return _task_unit_identity(user).get("unit_key", "")


def _is_generic_task_unit_key(value):
    if _is_category_item_reference(value):
        return True
    normalized = re.sub(r"[^a-z0-9]", "", remove_accents(value or "")).strip().lower()
    return normalized in {
        "",
        "sobannganh",
        "sobannganhcaptinh",
        "khoisobannganh",
        "xa",
        "phuong",
        "huyen",
        "quan",
        "tp",
        "thi",
        "tran",
        "capxa",
        "caphuong",
        "caphuyen",
        "captinh",
        "congancapxa",
        "congancaphuong",
        "congancaphuongxa",
        "congancaphuyen",
        "congancaptinh",
        "ubndcapxa",
        "ubndcaphuong",
        "ubndcaphuyen",
        "ubndcaptinh",
        "hethong",
    }


def _is_generic_task_unit_name(value):
    if _is_category_item_reference(value):
        return True
    normalized = re.sub(r"[^a-z0-9]", "", remove_accents(value or "")).strip().lower()
    return normalized in {
        "",
        "sobannganh",
        "sobannganhcaptinh",
        "khoisobannganh",
        "congancapxa",
        "congancaphuong",
        "congancaphuongxa",
        "congancaphuyen",
        "congancaptinh",
        "ubndcapxa",
        "ubndcaphuong",
        "ubndcaphuyen",
        "ubndcaptinh",
        "capxa",
        "caphuong",
        "caphuyen",
        "captinh",
        "hethong",
    }


def _looks_like_task_unit_name(value):
    normalized = re.sub(r"\s+", " ", remove_accents(value or "")).strip().lower()
    return any(
        token in normalized
        for token in [
            "cong an",
            "ubnd",
            "doi ",
            "phong ",
            "ban ",
            "so ",
            "bao hiem xa hoi",
            "chi cuc",
            "cuc ",
            "thanh tra",
            "thue ",
            "trung tam",
            "truong ",
            "vien ",
            "xa ",
            "phuong ",
            "thi tran",
            "huyen ",
            "quan ",
        ]
    )


def _resolve_task_unit_label(value):
    raw_value = (value or "").strip()
    if not raw_value:
        return ""
    resolved = resolve_category_display(
        raw_value,
        _task_assignment_unit_options(),
        fallback_label="",
    ).get("display_name", "")
    resolved = (resolved or "").strip()
    return resolved or raw_value


def _task_unit_identity(user):
    if not user:
        return {"unit_name": "Chưa có đơn vị", "unit_key": ""}

    stored_key = (getattr(user, "unit_key", "") or "").strip()
    unit_area_display = _resolve_task_unit_label(getattr(user, "unit_area_display", None) or "")
    unit_area = (getattr(user, "unit_area", None) or "").strip()
    resolved_unit_area = _resolve_task_unit_label(unit_area)
    fullname = (getattr(user, "fullname", None) or "").strip()
    username = (getattr(user, "username", None) or "").strip()

    unit_name = ""
    unit_name_source = ""
    for candidate in [unit_area_display, resolved_unit_area, unit_area]:
        if candidate and not _is_generic_task_unit_name(candidate):
            unit_name = candidate
            unit_name_source = "unit_area"
            break

    if not unit_name:
        for candidate in [fullname, username]:
            if candidate and _looks_like_task_unit_name(candidate):
                unit_name = candidate
                unit_name_source = "identity"
                break

    if not unit_name:
        unit_name = resolved_unit_area or unit_area_display or unit_area or fullname or username or "Chưa có đơn vị"
        unit_name_source = "fallback"

    key_candidates = []
    if unit_name_source == "identity":
        key_candidates.extend([unit_name, fullname, username])
        if stored_key and not _is_generic_task_unit_key(stored_key):
            key_candidates.append(stored_key)
    else:
        if stored_key and not _is_generic_task_unit_key(stored_key):
            key_candidates.append(stored_key)
        key_candidates.extend([unit_name, resolved_unit_area, unit_area_display, unit_area, fullname, username])

    unit_key = ""
    for candidate in key_candidates:
        key = extract_unit_key(candidate)
        if key and not _is_generic_task_unit_key(key):
            unit_key = key.strip()
            break

    if not unit_key:
        fallback_key = stored_key if stored_key and not _is_category_item_reference(stored_key) else ""
        unit_key = (fallback_key or extract_unit_key(unit_name) or unit_name.lower()).strip()

    return {
        "unit_name": unit_name,
        "unit_key": unit_key,
    }


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


def _assignment_scope_payload(assign_type, domain="", role_ids=None, user_ids=None):
    normalized_mode = assign_type if assign_type in {"unit", "role", "user"} else "unit"
    payload = {
        "mode": normalized_mode,
        "domain": (domain or "").strip(),
        "role_ids": sorted({int(role_id) for role_id in (role_ids or []) if str(role_id).isdigit()}),
        "user_ids": sorted({int(user_id) for user_id in (user_ids or []) if str(user_id).isdigit()}),
    }
    if normalized_mode == "unit":
        payload["role_ids"] = []
        payload["user_ids"] = []
    elif normalized_mode == "role":
        payload["user_ids"] = []
    elif normalized_mode == "user":
        payload["role_ids"] = []
    return payload


def _load_assignment_scope(task):
    if not task:
        return {}

    payload = {}
    raw_payload = getattr(task, "assignment_scope_json", None)
    if raw_payload:
        try:
            payload = json.loads(raw_payload) or {}
        except Exception:
            payload = {}

    assign_type = payload.get("mode") or getattr(task, "assign_type", None)
    if not raw_payload and not assign_type:
        return {}

    domain = payload.get("domain") or getattr(task, "domain", "") or ""
    role_ids = payload.get("role_ids") or []
    user_ids = payload.get("user_ids") or []

    return _assignment_scope_payload(assign_type, domain=domain, role_ids=role_ids, user_ids=user_ids)


def _store_assignment_scope(task, assign_type, domain="", role_ids=None, user_ids=None):
    payload = _assignment_scope_payload(assign_type, domain=domain, role_ids=role_ids, user_ids=user_ids)
    task.assign_type = payload["mode"]
    task.assignment_scope_json = json.dumps(payload, ensure_ascii=False)
    return payload


def _infer_assignment_context(task):
    assignments = task.assignments or []
    assigned_user_ids = [assignment.user_id for assignment in assignments if assignment.user_id]
    stored_scope = _load_assignment_scope(task)
    if stored_scope.get("mode") in {"unit", "role", "user"}:
        return {
            "mode": stored_scope["mode"],
            "domain": stored_scope.get("domain") or getattr(task, "domain", "") or "",
            "role_ids": stored_scope.get("role_ids") or [],
            "user_ids": stored_scope.get("user_ids") or assigned_user_ids,
        }

    context = {
        "mode": "unit",
        "domain": getattr(task, "domain", "") or "",
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


def _requested_role_ids(form):
    role_ids = [int(role_id) for role_id in form.getlist("assignee_role_ids") if str(role_id).isdigit()]
    if not role_ids:
        assignee_role_id = form.get("assignee_role_id")
        if assignee_role_id and str(assignee_role_id).isdigit():
            role_ids = [int(assignee_role_id)]
    return sorted(set(role_ids))


def _requested_user_ids(form):
    return sorted({int(uid) for uid in form.getlist("target_users") if str(uid).isdigit()})


def _should_refresh_assignments(task, form, domain):
    if form.get("refresh_assignments") == "1":
        return True

    current_context = _infer_assignment_context(task)
    requested_mode = form.get("assign_type", current_context.get("mode") or "unit")

    if requested_mode != current_context.get("mode"):
        return True

    if requested_mode == "unit":
        return (domain or "") != ((current_context.get("domain") or task.domain) or "")

    if requested_mode == "role":
        return _requested_role_ids(form) != sorted(current_context.get("role_ids") or [])

    if requested_mode == "user":
        return _requested_user_ids(form) != sorted(current_context.get("user_ids") or [])

    return False


def _resolve_assignees(form, domain):
    assign_type = form.get("assign_type", "unit")
    target_ids = _requested_user_ids(form)
    assignee_role_ids = _requested_role_ids(form)

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


def _sync_task_assignments(task, assignees):
    existing_assignments = {assignment.user_id: assignment for assignment in task.assignments}
    new_assignee_ids = {user.id for user in assignees}
    new_assignees_to_notify = []

    for assignment in list(task.assignments):
        if assignment.user_id not in new_assignee_ids:
            db.session.delete(assignment)

    for user in assignees:
        if user.id not in existing_assignments:
            db.session.add(
                TaskAssignment(task_id=task.id, user_id=user.id, status="Chưa tiếp nhận")
            )
            new_assignees_to_notify.append(user)

    return len(new_assignee_ids), new_assignees_to_notify


def _can_edit_task(task):
    if not task or not session.get("uid"):
        return False
    return bool(session.get("is_admin")) or task.author_id == session.get("uid")


def _can_view_task(task, is_lead=False):
    if not task or not session.get("uid"):
        return False
    if session.get("is_admin") or is_lead or task.author_id == session.get("uid"):
        return True
    return any(assignment.user_id == session.get("uid") for assignment in (task.assignments or []))


def _filter_comments_for_viewer(task, comments, viewer, can_manage_all=False):
    if can_manage_all or not viewer:
        return comments

    viewer_unit_key = _user_unit_key(viewer)
    comment_user_ids = sorted({
        user_id
        for comment in comments
        for user_id in [getattr(comment, "user_id", None), getattr(comment, "assignee_id", None)]
        if user_id
    })
    comment_users = {}
    if comment_user_ids:
        comment_users = {
            user.id: user
            for user in User.query.filter(User.id.in_(comment_user_ids)).all()
        }

    visible_comments = []
    for comment in comments:
        comment_user_id = getattr(comment, "user_id", None)
        comment_assignee_id = getattr(comment, "assignee_id", 0) or 0
        if comment_user_id == viewer.id:
            visible_comments.append(comment)
            continue

        if comment_user_id == task.author_id:
            if not comment_assignee_id:
                visible_comments.append(comment)
                continue
            target_user = comment_users.get(comment_assignee_id)
            if target_user and viewer_unit_key and _user_unit_key(target_user) == viewer_unit_key:
                visible_comments.append(comment)
                continue

        comment_user = comment_users.get(comment_user_id)
        if comment_user and viewer_unit_key and _user_unit_key(comment_user) == viewer_unit_key:
            visible_comments.append(comment)

    return visible_comments


def _build_assignment_report_context(user_assign, comments):
    latest_report = next(
        (
            comment
            for comment in comments
            if getattr(comment, "user_id", None) == getattr(user_assign, "user_id", None)
            and (getattr(comment, "content", "") or "").startswith("[BÁO CÁO]")
        ),
        None,
    ) if user_assign else None

    return {
        "latest_report_at": getattr(latest_report, "created_at", None),
        "latest_report_content": getattr(latest_report, "content", "") if latest_report else "",
        "result_file": getattr(user_assign, "result_file", "") if user_assign else "",
        "status": _normalize_status(getattr(user_assign, "status", "")) if user_assign else "Chưa tiếp nhận",
    }


def _parse_report_comment_content(content):
    raw_content = (content or "").strip()
    if raw_content.startswith(REPORT_PREFIX):
        raw_content = raw_content[len(REPORT_PREFIX):].strip()

    attachment_name = ""
    attachment_match = REPORT_ATTACHMENT_RE.search(raw_content)
    if attachment_match:
        attachment_name = (attachment_match.group(1) or "").strip()
        raw_content = REPORT_ATTACHMENT_RE.sub("", raw_content).strip()

    return raw_content, attachment_name


def _task_download_slug(value, fallback):
    ascii_text = remove_accents(value or "").strip().replace(" ", "_")
    safe_value = secure_filename(ascii_text)
    return safe_value or fallback


def _task_report_download_name(task, unit_name, original_name):
    _root, ext = os.path.splitext(original_name or "")
    unit_slug = _task_download_slug(unit_name, "don_vi")
    task_slug = _task_download_slug(getattr(task, "title", ""), f"task_{getattr(task, 'id', 'file')}")
    ext = ext or os.path.splitext(original_name or "")[1] or ""
    return f"{unit_slug}_{task_slug}{ext}"


def _build_unit_report_cards(task, assigns, comments):
    latest_reports_by_user = {}
    for comment in comments or []:
        if not (getattr(comment, "content", "") or "").startswith(REPORT_PREFIX):
            continue
        if not getattr(comment, "user_id", None):
            continue

        body_text, attachment_name = _parse_report_comment_content(getattr(comment, "content", "") or "")
        current_item = latest_reports_by_user.get(comment.user_id)
        if current_item is None or getattr(comment, "created_at", None) and comment.created_at > current_item["created_at"]:
            latest_reports_by_user[comment.user_id] = {
                "created_at": getattr(comment, "created_at", None),
                "body_text": body_text,
                "attachment_name": attachment_name,
                "user_name": getattr(comment, "user_name", "") or "",
            }

    unit_cards = {}
    for assignment, user in assigns or []:
        if not user:
            continue

        unit_identity = _task_unit_identity(user)
        unit_name = unit_identity["unit_name"] or "Chưa có đơn vị"
        unit_key = unit_identity["unit_key"] or unit_name.lower()
        card = unit_cards.setdefault(
            unit_key,
            {
                "unit_key": unit_key,
                "unit_name": unit_name,
                "status": "Chưa báo cáo",
                "latest_report_at": None,
                "latest_report_user_name": "",
                "latest_report_excerpt": "",
                "assignee_names": [],
                "assignee_user_ids": [],
                "primary_assignee_id": user.id,
                "attachments": [],
                "has_report": False,
            },
        )

        display_name = getattr(user, "fullname", None) or getattr(user, "username", None) or f"UID {user.id}"
        if display_name not in card["assignee_names"]:
            card["assignee_names"].append(display_name)
        if user.id not in card["assignee_user_ids"]:
            card["assignee_user_ids"].append(user.id)

        report_item = latest_reports_by_user.get(user.id)
        file_name = (report_item or {}).get("attachment_name") or getattr(assignment, "result_file", "") or ""
        if file_name:
            download_name = _task_report_download_name(task, unit_name, file_name)
            if not any(item["file_name"] == file_name and item["user_id"] == user.id for item in card["attachments"]):
                card["attachments"].append(
                    {
                        "file_name": file_name,
                        "download_name": download_name,
                        "user_id": user.id,
                        "user_name": display_name,
                    }
                )

        if report_item:
            card["has_report"] = True
            report_time = report_item.get("created_at")
            if report_time and (card["latest_report_at"] is None or report_time > card["latest_report_at"]):
                card["latest_report_at"] = report_time
                card["latest_report_user_name"] = report_item.get("user_name") or display_name
                card["latest_report_excerpt"] = report_item.get("body_text") or ""

    summary_rows, _summary_stats = _build_unit_report_summary(assigns, comments, task.deadline)
    summary_by_unit = {
        (row.get("unit_key") or row.get("unit_name", "").lower()): row
        for row in summary_rows
    }

    cards = []
    for unit_key, card in unit_cards.items():
        summary_row = summary_by_unit.get(card["unit_key"] or card["unit_name"].lower())
        if summary_row:
            card["status"] = summary_row.get("status", card["status"])
        card["assignee_names"].sort()
        card["attachments"].sort(key=lambda item: item["file_name"].lower())
        card["assignee_count"] = len(card["assignee_names"])
        preview_names = card["assignee_names"][:3]
        preview_text = ", ".join(preview_names)
        remaining_count = max(card["assignee_count"] - len(preview_names), 0)
        if remaining_count:
            preview_text = f"{preview_text} +{remaining_count}" if preview_text else f"+{remaining_count}"
        card["assignee_preview"] = preview_text
        excerpt = (card.get("latest_report_excerpt") or "").strip()
        card["latest_report_excerpt_preview"] = (excerpt[:220].rstrip() + "…") if len(excerpt) > 220 else excerpt
        cards.append(card)

    cards.sort(
        key=lambda item: (
            0 if item["has_report"] else 1,
            -(item["latest_report_at"].timestamp()) if item["latest_report_at"] else float("inf"),
            item["unit_name"].lower(),
        )
    )
    return cards


def _build_unit_report_groups(cards):
    cards = cards or []
    group_specs = [
        ("reported", "Đã báo cáo", lambda card: bool(card.get("has_report"))),
        ("unreported", "Chưa báo cáo", lambda card: not bool(card.get("has_report"))),
        ("on_time", "Đúng hạn", lambda card: card.get("status") == "Báo cáo đúng hạn"),
        ("overdue", "Quá hạn", lambda card: card.get("status") == "Báo cáo quá hạn"),
    ]

    groups = []
    for key, label, matcher in group_specs:
        matched_cards = [card for card in cards if matcher(card)]
        groups.append(
            {
                "key": key,
                "label": label,
                "count": len(matched_cards),
                "cards": matched_cards,
            }
        )
    return groups


def _build_discussion_threads(assigns, comments):
    threads = {}
    assigned_users = {}

    for assignment, user in assigns or []:
        if not user:
            continue
        unit_identity = _task_unit_identity(user)
        unit_name = unit_identity["unit_name"]
        unit_key = unit_identity["unit_key"] or unit_name.lower()
        thread = threads.setdefault(
            unit_key,
            {
                "unit_key": unit_key,
                "unit_name": unit_name,
                "assignee_names": [],
                "assignee_user_ids": [],
                "primary_assignee_id": user.id,
                "comments": [],
            },
        )
        assigned_users[user.id] = user
        display_name = getattr(user, "fullname", None) or getattr(user, "username", None) or f"UID {user.id}"
        if display_name not in thread["assignee_names"]:
            thread["assignee_names"].append(display_name)
        if user.id not in thread["assignee_user_ids"]:
            thread["assignee_user_ids"].append(user.id)

    if not threads:
        return []

    ordered_unit_keys = list(threads.keys())
    for comment in comments or []:
        if (getattr(comment, "content", "") or "").startswith(REPORT_PREFIX):
            continue

        thread_key = None
        target_assignee_id = getattr(comment, "assignee_id", 0) or 0
        if target_assignee_id and target_assignee_id in assigned_users:
            target_user = assigned_users[target_assignee_id]
            target_identity = _task_unit_identity(target_user)
            target_unit_name = target_identity["unit_name"]
            thread_key = target_identity["unit_key"] or target_unit_name.lower()
        elif getattr(comment, "user_id", None) in assigned_users:
            author_user = assigned_users.get(comment.user_id)
            author_identity = _task_unit_identity(author_user)
            author_unit_name = author_identity["unit_name"]
            thread_key = author_identity["unit_key"] or author_unit_name.lower()
        elif len(ordered_unit_keys) == 1:
            thread_key = ordered_unit_keys[0]

        if thread_key and thread_key in threads:
            threads[thread_key]["comments"].append(comment)

    output = []
    for thread in threads.values():
        thread["assignee_names"].sort()
        thread["comments"].sort(key=lambda item: getattr(item, "created_at", datetime.min))
        thread["comment_count"] = len(thread["comments"])
        latest_comment = thread["comments"][-1] if thread["comments"] else None
        latest_content = (getattr(latest_comment, "content", "") or "").strip() if latest_comment else ""
        thread["latest_comment_at"] = getattr(latest_comment, "created_at", None) if latest_comment else None
        thread["latest_comment_user_name"] = getattr(latest_comment, "user_name", "") if latest_comment else ""
        thread["latest_comment_preview"] = latest_content
        output.append(thread)

    output.sort(
        key=lambda item: (
            0 if item["comments"] else 1,
            -(item["latest_comment_at"].timestamp()) if item.get("latest_comment_at") else float("inf"),
            item["unit_name"].lower(),
        )
    )
    return output


def _build_assignment_unit_cards(assigns):
    unit_cards = {}
    for assignment, user in assigns or []:
        if not user:
            continue

        unit_identity = _task_unit_identity(user)
        unit_name = unit_identity["unit_name"]
        unit_key = unit_identity["unit_key"] or unit_name.lower()
        card = unit_cards.setdefault(
            unit_key,
            {
                "unit_key": unit_key,
                "unit_name": unit_name,
                "members": [],
                "status": "Chưa tiếp nhận",
                "completed_count": 0,
                "accepted_count": 0,
                "total_count": 0,
            },
        )

        normalized_status = _normalize_status(getattr(assignment, "status", ""))
        display_name = getattr(user, "fullname", None) or getattr(user, "username", None) or f"UID {user.id}"
        card["members"].append(
            {
                "user_id": user.id,
                "name": display_name,
                "status": normalized_status,
                "has_file": bool(getattr(assignment, "result_file", "")),
            }
        )
        card["total_count"] += 1
        if normalized_status != "Chưa tiếp nhận":
            card["accepted_count"] += 1
        if normalized_status == COMPLETED_STATUS:
            card["completed_count"] += 1

    output = []
    for card in unit_cards.values():
        if card["completed_count"] == card["total_count"] and card["total_count"] > 0:
            card["status"] = COMPLETED_STATUS
        elif card["accepted_count"] > 0:
            card["status"] = IN_PROGRESS_STATUS
        else:
            card["status"] = "Chưa tiếp nhận"
        card["members"].sort(key=lambda item: item["name"].lower())
        output.append(card)

    output.sort(key=lambda item: item["unit_name"].lower())
    return output


def _build_assignment_role_groups(assigns):
    role_groups = {}
    for assignment, user in assigns or []:
        if not user:
            continue

        role_name = ((getattr(getattr(user, "role", None), "name", None) or "").strip() or "Chưa phân vai trò")
        role_key = remove_accents(role_name).strip().lower() or "chua-phan-vai-tro"
        group = role_groups.setdefault(
            role_key,
            {
                "role_key": role_key,
                "role_name": role_name,
                "units": {},
                "status": "Chưa tiếp nhận",
                "completed_count": 0,
                "accepted_count": 0,
                "total_count": 0,
                "unit_count": 0,
            },
        )

        unit_identity = _task_unit_identity(user)
        unit_name = unit_identity["unit_name"]
        unit_key = unit_identity["unit_key"] or unit_name.lower()
        unit_card = group["units"].setdefault(
            unit_key,
            {
                "unit_key": unit_key,
                "unit_name": unit_name,
                "status": "Chưa tiếp nhận",
                "completed_count": 0,
                "accepted_count": 0,
                "total_count": 0,
                "progress_text": "0/0",
            },
        )

        normalized_status = _normalize_status(getattr(assignment, "status", ""))
        unit_card["total_count"] += 1
        group["total_count"] += 1
        if normalized_status != "Chưa tiếp nhận":
            unit_card["accepted_count"] += 1
            group["accepted_count"] += 1
        if normalized_status == COMPLETED_STATUS:
            unit_card["completed_count"] += 1
            group["completed_count"] += 1

    output = []
    for group in role_groups.values():
        units = []
        for unit_card in group["units"].values():
            if unit_card["completed_count"] == unit_card["total_count"] and unit_card["total_count"] > 0:
                unit_card["status"] = COMPLETED_STATUS
            elif unit_card["accepted_count"] > 0:
                unit_card["status"] = IN_PROGRESS_STATUS
            else:
                unit_card["status"] = "Chưa tiếp nhận"
            unit_card["progress_text"] = f"{unit_card['completed_count']}/{unit_card['total_count']}"
            units.append(unit_card)

        units.sort(key=lambda item: item["unit_name"].lower())
        group["units"] = units
        group["unit_count"] = len(units)
        if group["completed_count"] == group["total_count"] and group["total_count"] > 0:
            group["status"] = COMPLETED_STATUS
        elif group["accepted_count"] > 0:
            group["status"] = IN_PROGRESS_STATUS
        else:
            group["status"] = "Chưa tiếp nhận"
        output.append(group)

    output.sort(key=lambda item: item["role_name"].lower())
    return output


def _task_file_root():
    task_dir = current_app.config.get("TASK_FOLDER") or os.path.join(current_app.root_path, "task_files")
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def _task_file_path(file_name):
    if not file_name:
        return ""
    return os.path.join(_task_file_root(), file_name)


def _task_assignee_unit_name(user):
    return _task_unit_identity(user).get("unit_name", "Chưa có đơn vị")


def _purge_task(task):
    if not task:
        return

    file_names = set()
    if task.file_path:
        file_names.add(task.file_path)

    for assignment in task.assignments or []:
        if assignment.result_file:
            file_names.add(assignment.result_file)

    for file_name in file_names:
        file_path = _task_file_path(file_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                current_app.logger.warning(f"Không thể xóa file công việc: {file_path}")

    TaskComment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
    db.session.delete(task)


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


def _build_unit_report_summary(assigns, comments, deadline):
    report_times_by_user = {}
    for comment in comments or []:
        if not (getattr(comment, "content", "") or "").startswith("[BÁO CÁO]"):
            continue
        if not getattr(comment, "user_id", None) or not getattr(comment, "created_at", None):
            continue
        current_first = report_times_by_user.get(comment.user_id)
        if current_first is None or comment.created_at < current_first:
            report_times_by_user[comment.user_id] = comment.created_at

    unit_rows = {}
    for assignment, user in assigns or []:
        if not user:
            continue
        unit_identity = _task_unit_identity(user)
        unit_name = unit_identity["unit_name"] or "Chưa có đơn vị"
        unit_key = unit_identity["unit_key"] or unit_name.lower()
        row = unit_rows.setdefault(
            unit_key,
            {
                "unit_key": unit_key,
                "unit_name": unit_name,
                "assignee_names": [],
                "reporter_names": [],
                "first_report_at": None,
            },
        )
        display_name = getattr(user, "fullname", None) or getattr(user, "username", None) or f"UID {user.id}"
        if display_name not in row["assignee_names"]:
            row["assignee_names"].append(display_name)

        report_at = report_times_by_user.get(user.id)
        if report_at:
            if display_name not in row["reporter_names"]:
                row["reporter_names"].append(display_name)
            if row["first_report_at"] is None or report_at < row["first_report_at"]:
                row["first_report_at"] = report_at

    status_order = {
        "Chưa báo cáo": 0,
        "Báo cáo quá hạn": 1,
        "Báo cáo đúng hạn": 2,
    }
    rows = []
    for row in unit_rows.values():
        row["assignee_count"] = len(row["assignee_names"])
        row["reporter_count"] = len(row["reporter_names"])
        row["has_report"] = row["first_report_at"] is not None
        row["is_overdue_report"] = bool(
            row["has_report"] and deadline and row["first_report_at"].date() > deadline
        )
        row["is_on_time_report"] = bool(row["has_report"] and not row["is_overdue_report"])
        if not row["has_report"]:
            row["status"] = "Chưa báo cáo"
        elif row["is_overdue_report"]:
            row["status"] = "Báo cáo quá hạn"
        else:
            row["status"] = "Báo cáo đúng hạn"
        rows.append(row)

    rows.sort(key=lambda item: (status_order.get(item["status"], 99), item["unit_name"].lower()))
    stats = {
        "total_units": len(rows),
        "reported_units": sum(1 for row in rows if row["has_report"]),
        "unreported_units": sum(1 for row in rows if not row["has_report"]),
        "overdue_units": sum(1 for row in rows if row["is_overdue_report"]),
        "on_time_units": sum(1 for row in rows if row["is_on_time_report"]),
    }
    return rows, stats


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
            attachment.save(_task_file_path(attachment_name))

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
        _store_assignment_scope(
            new_task,
            request.form.get("assign_type", "unit"),
            domain=domain,
            role_ids=_requested_role_ids(request.form),
            user_ids=_requested_user_ids(request.form),
        )
        db.session.add(new_task)
        db.session.flush()

        _sync_task_assignments(new_task, assignees)

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
        setattr(task, "can_edit", _can_edit_task(task))
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
    if not _can_view_task(task, is_lead=is_lead):
        flash("Bạn không có quyền xem công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    assigns = (
        db.session.query(TaskAssignment, User)
        .join(User, TaskAssignment.user_id == User.id)
        .filter(TaskAssignment.task_id == tid)
        .order_by(TaskAssignment.updated_at.desc(), User.fullname.asc())
        .all()
    )
    current_user = db.session.get(User, session["uid"])
    assign_users = [user for _, user in assigns]
    unit_options = module_category_options("contacts", "unit_name", "Đơn vị")
    sync_record_categories(assign_users, unit_options, attr_name="unit_area", prefer_stable=True)
    apply_reference_display(
        assign_users,
        "unit_area",
        _task_assignment_unit_options(),
        display_attr="unit_area_display",
        fallback_label="Chưa có đơn vị",
    )

    task_metrics = _decorate_task(task, session["uid"], is_lead)
    user_assign = task_metrics["user_assignment"]
    can_manage_task_view = bool(is_lead or can_edit_task)
    if not can_manage_task_view and not user_assign:
        flash("Bạn không có quyền xem công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    comments = TaskComment.query.filter_by(task_id=tid).order_by(TaskComment.created_at.desc()).all()
    visible_comments = _filter_comments_for_viewer(task, comments, current_user, can_manage_all=can_manage_task_view)
    assignment_context = _infer_assignment_context(task)
    discussion_comments = visible_comments
    unit_report_rows, unit_report_stats = ([], {
        "total_units": 0,
        "reported_units": 0,
        "unreported_units": 0,
        "overdue_units": 0,
        "on_time_units": 0,
    })
    unit_report_cards = []
    unit_report_groups = []
    discussion_threads = []
    assignment_role_groups = []
    assignment_unit_cards = _build_assignment_unit_cards(assigns)
    assignment_unit_progress = {
        "completed_units": sum(1 for card in assignment_unit_cards if card.get("status") == COMPLETED_STATUS),
        "total_units": len(assignment_unit_cards),
    }
    if can_manage_task_view:
        discussion_comments = [
            comment for comment in visible_comments
            if not (getattr(comment, "content", "") or "").startswith(REPORT_PREFIX)
        ]
        assignment_role_groups = _build_assignment_role_groups(assigns)
        unit_report_rows, unit_report_stats = _build_unit_report_summary(assigns, comments, task.deadline)
        unit_report_cards = _build_unit_report_cards(task, assigns, comments)
        unit_report_groups = _build_unit_report_groups(unit_report_cards)
        discussion_threads = [thread for thread in _build_discussion_threads(assigns, discussion_comments) if thread.get("comments")]
    elif user_assign:
        discussion_comments = [
            comment for comment in visible_comments
            if not (getattr(comment, "content", "") or "").startswith(REPORT_PREFIX)
        ]
        discussion_threads = [
            thread
            for thread in _build_discussion_threads(assigns, discussion_comments)
            if user_assign.user_id in (thread.get("assignee_user_ids") or [])
        ]
    report_context = _build_assignment_report_context(user_assign, visible_comments)
    limited_assignment_view = bool(user_assign and not can_manage_task_view)

    if request.method == "POST":
        if not (can_manage_task_view or user_assign):
            flash("Bạn không có quyền phản hồi công việc này.", "danger")
            return redirect(url_for("tasks_bp.tasks"))

        content = (request.form.get("content") or "").strip()
        requested_assignee_id = request.form.get("assignee_id", "").strip()
        assignee_id = int(requested_assignee_id) if requested_assignee_id.isdigit() else 0
        valid_assignee_ids = {assignment.user_id for assignment, _user in assigns if assignment.user_id}

        if can_manage_task_view:
            assignee_id = assignee_id if assignee_id in valid_assignee_ids else 0
        elif user_assign:
            assignee_id = user_assign.user_id

        if content:
            db.session.add(
                TaskComment(
                    task_id=tid,
                    user_id=session["uid"],
                    user_name=session.get("fullname", "Người dùng"),
                    content=content,
                    assignee_id=assignee_id,
                )
            )
            db.session.commit()
            flash("Đã gửi phản hồi.", "success")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))

    return render_template(
        "task_detail.html",
        task=task,
        comments=visible_comments,
        discussion_comments=discussion_comments,
        discussion_threads=discussion_threads,
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
        unit_report_rows=unit_report_rows,
        unit_report_stats=unit_report_stats,
        unit_report_cards=unit_report_cards,
        unit_report_groups=unit_report_groups,
        assignment_role_groups=assignment_role_groups,
        assignment_unit_progress=assignment_unit_progress,
        can_manage_task_view=can_manage_task_view,
        limited_assignment_view=limited_assignment_view,
        report_context=report_context,
    )


@tasks_bp.route("/tasks/<int:tid>/assignees/<int:user_id>/report-download")
def download_task_report_file(tid, user_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    perms = _current_perms()
    is_lead = perms.get("p_task_lead") or session.get("is_admin")
    can_manage_task_view = bool(is_lead or _can_edit_task(task))
    if not _can_view_task(task, is_lead=is_lead):
        flash("Bạn không có quyền tải tệp của công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    if not can_manage_task_view and session.get("uid") != user_id:
        flash("Bạn chỉ có thể tải tệp báo cáo của mình.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    assign = TaskAssignment.query.filter_by(task_id=tid, user_id=user_id).first()
    if not assign or not assign.result_file:
        flash("Không tìm thấy tệp báo cáo cần tải.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    file_path = _task_file_path(assign.result_file)
    if not os.path.exists(file_path):
        flash("Tệp báo cáo không còn tồn tại trên hệ thống.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    target_user = db.session.get(User, user_id)
    if target_user:
        unit_options = module_category_options("contacts", "unit_name", "Đơn vị")
        sync_record_categories([target_user], unit_options, attr_name="unit_area", prefer_stable=True)
        apply_reference_display(
            [target_user],
            "unit_area",
            unit_options,
            display_attr="unit_area_display",
            fallback_label="Chưa có đơn vị",
        )

    unit_name = _task_assignee_unit_name(target_user)
    download_name = _task_report_download_name(task, unit_name, assign.result_file)
    return send_file(file_path, as_attachment=True, download_name=download_name)


@tasks_bp.route("/tasks/<int:tid>/unit-report-export")
def export_task_unit_report(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    if Workbook is None:
        flash("Máy chủ chưa cài thư viện xuất Excel.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    perms = _current_perms()
    is_lead = perms.get("p_task_lead") or session.get("is_admin")
    if not (is_lead or _can_edit_task(task)):
        flash("Bạn không có quyền xuất thống kê báo cáo của công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

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
    apply_reference_display(
        assign_users,
        "unit_area",
        _task_assignment_unit_options(),
        display_attr="unit_area_display",
        fallback_label="Chưa có đơn vị",
    )
    comments = TaskComment.query.filter_by(task_id=tid).order_by(TaskComment.created_at.desc()).all()
    unit_report_rows, unit_report_stats = _build_unit_report_summary(assigns, comments, task.deadline)

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Tong hop"
    summary_sheet.append(["Công việc", task.title])
    summary_sheet.append(["Người giao", task.author_name or ""])
    summary_sheet.append(["Hạn xử lý", task.deadline.strftime("%d/%m/%Y") if task.deadline else "Chưa có"])
    summary_sheet.append(["Ngày xuất", datetime.now().strftime("%d/%m/%Y %H:%M")])
    summary_sheet.append([])
    summary_sheet.append(["Chỉ số", "Số lượng"])
    summary_sheet.append(["Tổng số đơn vị", unit_report_stats["total_units"]])
    summary_sheet.append(["Đơn vị đã báo cáo", unit_report_stats["reported_units"]])
    summary_sheet.append(["Đơn vị chưa báo cáo", unit_report_stats["unreported_units"]])
    summary_sheet.append(["Đơn vị báo cáo đúng hạn", unit_report_stats["on_time_units"]])
    summary_sheet.append(["Đơn vị báo cáo quá hạn", unit_report_stats["overdue_units"]])

    detail_sheet = workbook.create_sheet("Chi tiet don vi")
    detail_sheet.append([
        "Đơn vị",
        "Số cán bộ nhận việc",
        "Cán bộ nhận việc",
        "Số cán bộ đã báo cáo",
        "Cán bộ đã báo cáo",
        "Báo cáo đầu tiên",
        "Hạn xử lý",
        "Trạng thái",
    ])
    for row in unit_report_rows:
        detail_sheet.append([
            row["unit_name"],
            row["assignee_count"],
            ", ".join(row["assignee_names"]),
            row["reporter_count"],
            ", ".join(row["reporter_names"]),
            row["first_report_at"].strftime("%d/%m/%Y %H:%M") if row["first_report_at"] else "",
            task.deadline.strftime("%d/%m/%Y") if task.deadline else "",
            row["status"],
        ])

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    safe_name = secure_filename(task.title or f"task_{task.id}") or f"task_{task.id}"
    filename = f"thong_ke_bao_cao_{safe_name}_{task.id}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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

    requested_assign_type = request.form.get("assign_type", _infer_assignment_context(task).get("mode") or "unit")
    requested_role_ids = _requested_role_ids(request.form)
    requested_user_ids = _requested_user_ids(request.form)
    refreshed_assignee_count = None
    new_assignees_to_notify = []
    if _should_refresh_assignments(task, request.form, domain):
        assignees, error_message = _resolve_assignees(request.form, domain)
        if error_message:
            flash(error_message, "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))

        refreshed_assignee_count, new_assignees_to_notify = _sync_task_assignments(task, assignees)
        _store_assignment_scope(
            task,
            requested_assign_type,
            domain=domain,
            role_ids=requested_role_ids,
            user_ids=requested_user_ids,
        )

    task.title = title
    task.category = category
    task.domain = domain
    task.content = content
    task.priority = priority
    task.task_type = task_type
    task.deadline = _parse_deadline(request.form)
    if refreshed_assignee_count is None:
        current_scope = _load_assignment_scope(task)
        _store_assignment_scope(
            task,
            requested_assign_type,
            domain=domain,
            role_ids=requested_role_ids if requested_assign_type == "role" else current_scope.get("role_ids"),
            user_ids=requested_user_ids if requested_assign_type == "user" else current_scope.get("user_ids"),
        )

    attachment = request.files.get("task_file")
    if attachment and attachment.filename:
        attachment_name = secure_filename(attachment.filename)
        attachment.save(_task_file_path(attachment_name))
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


@tasks_bp.route("/tasks/<int:tid>/delete", methods=["POST"])
def delete_task(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    if not _can_edit_task(task):
        flash("Bạn không có quyền xóa công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task_title = task.title
    _purge_task(task)
    db.session.commit()

    log_action(
        session["uid"],
        session.get("fullname", "Quản trị"),
        "Xóa công việc",
        "Công việc",
        f"Task #{tid} | {task_title}",
    )
    flash("Đã xóa công việc đã giao.", "success")
    return redirect(url_for("tasks_bp.tasks"))


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
        report_file.save(_task_file_path(attachment_name))

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
