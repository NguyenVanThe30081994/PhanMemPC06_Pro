# -*- coding: utf-8 -*-
import json
import io
import os
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, g, has_request_context, jsonify, redirect, request, session, url_for, send_file
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename
try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None
try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

from category_helpers import (
    apply_reference_display,
    canonicalize_category_value,
    category_filter_counts,
    module_category_options,
    resolve_category_display,
    stable_form_category_options,
    sync_record_categories,
)
from models import (
    AppRole,
    RankingUnit,
    ReportCycle,
    ReportInstance,
    ReportTemplate,
    ReportType,
    ReportTemplateVersion,
    Task,
    TaskAssignment,
    TaskComment,
    TaskItem,
    TaskParticipant,
    TaskReportLink,
    TaskSubmission,
    User,
    db,
)
from utils import (
    apply_migrations,
    extract_unit_key,
    has_module_permission,
    log_action,
    is_unit_match,
    normalize_permission_payload,
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
TASK_REPORT_ALLOWED_FIELD_TYPES = {"number", "text", "textarea"}
TASK_REPORT_ALLOWED_TARGET_TYPES = {"all", "role", "user"}
TASK_SCOPE_ALLOWED_MODES = {"none", "role", "user"}
TASK_OUTLINE_ALLOWED_EXTENSIONS = {".docx", ".txt"}
DEFAULT_TASK_REPORT_SCHEMA = {
    "enabled": False,
    "narrative": {
        "enabled": True,
        "label": "Báo cáo lời tổng hợp",
        "required": True,
        "placeholder": "Nêu rõ kết quả, tồn tại và kiến nghị nếu có",
        "target_type": "all",
        "target_role_ids": [],
        "target_user_ids": [],
    },
    "attachment": {
        "enabled": False,
        "label": "Tệp minh chứng",
        "required": False,
        "target_type": "all",
        "target_role_ids": [],
        "target_user_ids": [],
    },
    "fields": [],
}
CHILD_TASK_ALLOWED_REPORT_KINDS = {"narrative", "number"}
CHILD_TASK_NUMBER_FIELD_KEY = "reported_value"

DA06_TASK_MARKERS = ("bao cao de an 06 thang", "bao cao de an06 thang", "bao cao da06 thang")
DA06_TCT_ROLE_MARKERS = ("to cong tac cap xa",)
DA06_TTPVHCC_USERNAME = "ttpvhcctq"
DA06_SO_NGANH_RULES = [
    {"unit_markers": ("bao hiem xa hoi", "bhxh"), "label": "Lĩnh vực Bảo hiểm xã hội", "dvc_titles": ["Giải quyết hưởng trợ cấp thất nghiệp", "Đăng ký tham gia đóng bảo hiểm xã hội tự nguyện", "Đăng ký đóng, cấp thẻ bảo hiểm y tế", "Giải quyết hưởng bảo hiểm xã hội một lần", "Giải quyết hưởng chế độ ốm đau, thai sản, trợ cấp dưỡng sức phục hồi sức khỏe"]},
    {"unit_markers": ("thue",), "label": "Lĩnh vực Thuế", "dvc_titles": ["Đăng ký thuế lần đầu, đăng ký thay đổi thông tin đăng ký thuế đối với người nộp thuế là hộ gia đình, cá nhân", "Thanh toán nghĩa vụ tài chính trong thực hiện thủ tục hành chính về đất đai đối với hộ gia đình, cá nhân", "Thanh toán nghĩa vụ tài chính trong thực hiện thủ tục hành chính về đất đai đối với doanh nghiệp", "Nộp thuế, lệ phí trước bạ đối với doanh nghiệp", "Liên thông các thủ tục Đăng ký thành lập hợp tác xã/liên hiệp hợp tác xã và đăng ký thuế", "Nhóm thủ tục Đăng ký thành lập hộ kinh doanh và Đăng ký thuế", "Thanh toán trực tuyến nghĩa vụ tài chính nộp thuế, lệ phí trước bạ đối với hợp tác xã, doanh nghiệp trong thực hiện thủ tục hành chính về đất đai"]},
    {"unit_markers": ("tu phap",), "label": "Lĩnh vực Tư pháp", "dvc_titles": ["Đăng ký khai sinh", "Đăng ký khai tử", "Đăng ký kết hôn", "Liên thông đăng ký khai sinh đăng ký thường trú - cấp thẻ bảo hiểm y tế cho trẻ dưới 6 tuổi", "Liên thông đăng ký khai tử - Xóa đăng ký thường trú - Trợ cấp mai táng phí", "Nhóm thủ tục cấp Giấy xác nhận tình trạng hôn nhân và Đăng ký kết hôn", "Nhóm thủ tục thay đổi, cải chính, bổ sung thông tin hộ tịch - Điều chỉnh thông tin về cư trú trong Cơ sở dữ liệu về cư trú - Cấp lại thẻ Căn cước công dân / Đổi thẻ Căn cước công dân"]},
    {"unit_markers": ("giao duc", "dao tao"), "label": "Lĩnh vực Giáo dục và Đào tạo", "dvc_titles": ["Đăng kí dự thi tốt nghiệp THPT quốc gia và xét tuyển đại học, cao đẳng", "Công nhận bằng tốt nghiệp trung học cơ sở, bằng tốt nghiệp trung học phổ thông, giấy chứng nhận hoàn thành chương trình giáo dục phổ thông do cơ sở giáo dục nước ngoài cấp để sử dụng tại Việt Nam"]},
    {"unit_markers": ("nong nghiep", "moi truong", "tai nguyen"), "label": "Lĩnh vực Nông nghiệp và Môi trường", "dvc_titles": ["Đăng ký biến động đối với trường hợp đổi tên hoặc thay đổi thông tin về người sử dụng đất", "Đăng ký biến động quyền sử dụng đất, quyền sở hữu tài sản gắn liền với đất trong các trường hợp chuyển đổi, chuyển nhượng, cho thuê, cho thuê lại, thừa kế, tặng cho, góp vốn bằng quyền sử dụng đất"]},
    {"unit_markers": ("cong thuong", "dien luc"), "label": "Lĩnh vực Công Thương", "dvc_titles": ["Cấp điện mới từ lưới điện hạ áp (220/380V)", "Mở rộng việc kết nối, chia sẻ dữ liệu dân cư của Cơ sở dữ liệu quốc gia về dân cư để thực hiện các dịch vụ cung cấp điện còn lại", "Thay đổi chủ thể hợp đồng mua bán điện", "Kết nối, chia sẻ dữ liệu doanh nghiệp của Cơ sở dữ liệu quốc gia về đăng ký doanh nghiệp để thực hiện các dịch vụ cung cấp điện cho doanh nghiệp"]},
    {"unit_markers": ("noi vu",), "label": "Lĩnh vực Nội vụ", "dvc_titles": ["Thăm viếng mộ liệt sĩ"]},
    {"unit_markers": ("toa an",), "label": "Lĩnh vực Tòa án", "dvc_titles": ["Thu, nộp tạm ứng án phí, lệ phí tòa án"]},
    {"unit_markers": ("y te",), "label": "Lĩnh vực Y tế", "dvc_titles": []},
]


def _task_domain_options():
    return module_category_options("tasks", "domain", "Đội nghiệp vụ")


def _task_field_options():
    return module_category_options("news", "category", "Lĩnh vực", "Đội nghiệp vụ")


def _task_type_options():
    return module_category_options("tasks", "task_type", "Loại công việc")


def _task_priority_options():
    return module_category_options("tasks", "priority", "Mức độ ưu tiên")


def _task_report_templates():
    templates = (
        ReportTemplate.query.filter_by(status="active")
        .order_by(ReportTemplate.updated_at.desc())
        .all()
    )
    report_types = {
        item.id: item
        for item in ReportType.query.filter(ReportType.id.in_([template.report_type_id for template in templates if template.report_type_id])).all()
    } if templates else {}

    for template in templates:
        professional_unit = resolve_category_display(
            getattr(template, "professional_unit", None),
            _task_domain_options(),
            fallback_label="Chưa phân đội",
        ).get("display_name") or "Chưa phân đội"
        setattr(template, "professional_unit_display", professional_unit)
        setattr(template, "report_type_display", getattr(report_types.get(template.report_type_id), "name", "Chưa phân loại"))
    return templates


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
            return normalize_permission_payload(role.perms, is_admin=session.get("is_admin"), role_name=getattr(role, "name", ""))
        except Exception:
            return {}
    return {}


def _can_view_task_module(perms=None):
    perms = perms or _current_perms()
    return has_module_permission(perms, "task", "view", is_admin=session.get("is_admin"))


def _can_process_task_module(perms=None):
    perms = perms or _current_perms()
    return has_module_permission(perms, "task", "process", is_admin=session.get("is_admin"))


def _can_view_all_tasks(perms=None):
    perms = perms or _current_perms()
    return has_module_permission(perms, "task", "view", is_admin=session.get("is_admin"))


def _can_execute_task_module(perms=None):
    perms = perms or _current_perms()
    return bool(
        has_module_permission(perms, "task", "exec", is_admin=session.get("is_admin"))
        or has_module_permission(perms, "task", "process", is_admin=session.get("is_admin"))
    )


def _can_manage_report_links():
    perms = _current_perms()
    return has_module_permission(perms, "form", "process", is_admin=session.get("is_admin"))


def _can_open_report_workspace():
    perms = _current_perms()
    return bool(
        has_module_permission(perms, "form", "view", is_admin=session.get("is_admin"))
        or has_module_permission(perms, "input", "view", is_admin=session.get("is_admin"))
        or has_module_permission(perms, "input", "process", is_admin=session.get("is_admin"))
        or has_module_permission(perms, "input", "exec", is_admin=session.get("is_admin"))
        or has_module_permission(perms, "stat", "view", is_admin=session.get("is_admin"))
        or has_module_permission(perms, "stat", "process", is_admin=session.get("is_admin"))
        or has_module_permission(perms, "stat", "exec", is_admin=session.get("is_admin"))
    )


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


def _participant_scope_payload(mode="none", role_ids=None, user_ids=None):
    normalized_mode = mode if mode in TASK_SCOPE_ALLOWED_MODES else "none"
    payload = {
        "mode": normalized_mode,
        "role_ids": sorted({int(role_id) for role_id in (role_ids or []) if str(role_id).isdigit()}),
        "user_ids": sorted({int(user_id) for user_id in (user_ids or []) if str(user_id).isdigit()}),
    }
    if normalized_mode == "role":
        payload["user_ids"] = []
    elif normalized_mode == "user":
        payload["role_ids"] = []
    else:
        payload["role_ids"] = []
        payload["user_ids"] = []
    return payload


def _viewer_scope_payload(mode="none", role_ids=None, user_ids=None):
    return _participant_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)


def _manager_scope_payload(mode="none", role_ids=None, user_ids=None):
    return _participant_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)


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


def _load_viewer_scope(task):
    if not task:
        return _viewer_scope_payload("none")

    raw_payload = getattr(task, "viewer_scope_json", None)
    if not raw_payload:
        return _viewer_scope_payload("none")

    try:
        payload = json.loads(raw_payload) or {}
    except Exception:
        payload = {}

    return _viewer_scope_payload(
        payload.get("mode") or "none",
        role_ids=payload.get("role_ids") or [],
        user_ids=payload.get("user_ids") or [],
    )


def _load_manager_scope(task):
    if not task:
        return _manager_scope_payload("none")

    raw_payload = getattr(task, "manager_scope_json", None)
    if not raw_payload:
        return _manager_scope_payload("none")

    try:
        payload = json.loads(raw_payload) or {}
    except Exception:
        payload = {}

    return _manager_scope_payload(
        payload.get("mode") or "none",
        role_ids=payload.get("role_ids") or [],
        user_ids=payload.get("user_ids") or [],
    )


def _store_assignment_scope(task, assign_type, domain="", role_ids=None, user_ids=None):
    payload = _assignment_scope_payload(assign_type, domain=domain, role_ids=role_ids, user_ids=user_ids)
    task.assign_type = payload["mode"]
    task.assignment_scope_json = json.dumps(payload, ensure_ascii=False)
    return payload


def _store_viewer_scope(task, mode="none", role_ids=None, user_ids=None):
    payload = _viewer_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)
    task.viewer_scope_json = json.dumps(payload, ensure_ascii=False)
    return payload


def _store_manager_scope(task, mode="none", role_ids=None, user_ids=None):
    payload = _manager_scope_payload(mode, role_ids=role_ids, user_ids=user_ids)
    task.manager_scope_json = json.dumps(payload, ensure_ascii=False)
    return payload


def _infer_assignment_context(task):
    assignment_rows = _task_assignment_rows(task, ensure_bridge=False)
    assigned_user_ids = [assignment.user_id for assignment, _user in assignment_rows if assignment.user_id]
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
    cleaned_names = [str(name).strip() for name in (names or []) if str(name).strip()]
    if not cleaned_names:
        return empty_label
    if len(cleaned_names) <= 2:
        return ", ".join(cleaned_names)
    return f"{', '.join(cleaned_names[:2])} +{len(cleaned_names) - 2}"


def _build_scope_summary(context, role_lookup=None, user_lookup=None, none_label="Chưa cấu hình riêng"):
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
            "value_label": _scope_preview_names(role_names, empty_label="Chưa chọn vai trò"),
            "count": len(role_names),
        }

    if mode == "user":
        user_names = [user_lookup.get(user_id) for user_id in user_ids if user_lookup.get(user_id)]
        return {
            "mode": "user",
            "mode_label": "Theo cá nhân",
            "value_label": _scope_preview_names(user_names, empty_label="Chưa chọn tài khoản"),
            "count": len(user_names),
        }

    return {
        "mode": "none",
        "mode_label": "Mặc định",
        "value_label": none_label,
        "count": 0,
    }


def _requested_role_ids(form):
    role_ids = [int(role_id) for role_id in form.getlist("assignee_role_ids") if str(role_id).isdigit()]
    if not role_ids:
        assignee_role_id = form.get("assignee_role_id")
        if assignee_role_id and str(assignee_role_id).isdigit():
            role_ids = [int(assignee_role_id)]
    return sorted(set(role_ids))


def _requested_user_ids(form):
    return sorted({int(uid) for uid in form.getlist("target_users") if str(uid).isdigit()})


def _requested_viewer_role_ids(form):
    return sorted({int(role_id) for role_id in form.getlist("viewer_role_ids") if str(role_id).isdigit()})


def _requested_viewer_user_ids(form):
    return sorted({int(uid) for uid in form.getlist("viewer_user_ids") if str(uid).isdigit()})


def _requested_manager_role_ids(form):
    return sorted({int(role_id) for role_id in form.getlist("manager_role_ids") if str(role_id).isdigit()})


def _requested_manager_user_ids(form):
    return sorted({int(uid) for uid in form.getlist("manager_user_ids") if str(uid).isdigit()})


def _requested_linked_report_template_ids(form):
    return sorted({int(template_id) for template_id in form.getlist("linked_report_template_ids") if str(template_id).isdigit()})


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


def _clean_outline_title(raw_value):
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*(?:[-*+•]|[0-9]{1,3}[.)]|[A-Za-z][.)]|[IVXLCDMivxlcdm]+[.)])\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    return cleaned


def _parse_outline_docx_titles(file_storage):
    if DocxDocument is None:
        raise ValueError("Máy chủ chưa cài thư viện đọc file Word (.docx).")

    try:
        file_storage.stream.seek(0)
        file_bytes = file_storage.stream.read()
        document = DocxDocument(io.BytesIO(file_bytes))
    except Exception:
        raise ValueError("Không đọc được file đề cương Word. Hãy thử lại với file .docx rõ nội dung đầu mục.")

    candidates = []
    fallback_lines = []
    for paragraph in document.paragraphs:
        raw_text = str(getattr(paragraph, "text", "") or "").strip()
        if not raw_text:
            continue
        cleaned = _clean_outline_title(raw_text)
        if len(cleaned) < 3:
            continue
        fallback_lines.append(cleaned)
        style_name = str(getattr(getattr(paragraph, "style", None), "name", "") or "").strip().lower()
        is_outline_like = bool(
            re.match(r"^\s*(?:[-*+•]|[0-9]{1,3}[.)]|[A-Za-z][.)]|[IVXLCDMivxlcdm]+[.)])\s*", raw_text)
            or any(token in style_name for token in ("heading", "list", "bullet", "number"))
        )
        if is_outline_like:
            candidates.append(cleaned)

    chosen_lines = candidates or fallback_lines
    return _parse_bulk_child_task_titles("\n".join(chosen_lines))


def _parse_outline_text_titles(file_storage):
    try:
        file_storage.stream.seek(0)
        raw_bytes = file_storage.stream.read()
    except Exception:
        raise ValueError("Không đọc được file đề cương văn bản.")

    raw_text = ""
    for encoding in ("utf-8", "utf-8-sig", "cp1258"):
        try:
            raw_text = raw_bytes.decode(encoding)
            break
        except Exception:
            raw_text = ""
    if not raw_text:
        raise ValueError("File đề cương văn bản không đúng định dạng UTF-8.")
    return _parse_bulk_child_task_titles(raw_text)


def _parse_outline_upload_titles(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return []

    extension = os.path.splitext(file_storage.filename or "")[1].lower()
    if extension not in TASK_OUTLINE_ALLOWED_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ đề cương dạng .docx hoặc .txt.")

    if extension == ".docx":
        return _parse_outline_docx_titles(file_storage)
    return _parse_outline_text_titles(file_storage)


def _load_linked_report_template_ids_legacy(task):
    if not task:
        return []
    raw_value = getattr(task, "linked_report_templates_json", None) or ""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return sorted({int(template_id) for template_id in parsed if str(template_id).isdigit()})


def _task_scope_identity(task):
    if not task:
        return None, None
    root_task = task.parent_task or task
    if getattr(root_task, "parent_task_id", None):
        root_task = Task.query.filter_by(id=root_task.parent_task_id).first() or root_task
    task_item_id = task.id if getattr(task, "parent_task_id", None) else None
    return root_task.id, task_item_id


def _query_task_scope(model, task):
    task_id, task_item_id = _task_scope_identity(task)
    query = model.query.filter(model.task_id == task_id)
    if task_item_id:
        return query.filter(model.task_item_id == task_item_id)
    return query.filter(model.task_item_id.is_(None))


def _task_assignment_records(task):
    if not task or not getattr(task, "id", None):
        return []
    return (
        TaskAssignment.query.filter_by(task_id=task.id)
        .order_by(TaskAssignment.updated_at.desc(), TaskAssignment.id.desc())
        .all()
    )


def _task_executor_user_ids(task):
    if not task:
        return []

    participant_ids = [
        participant.user_id
        for participant in _query_task_scope(TaskParticipant, task)
        .filter(
            TaskParticipant.participant_type == "executor",
            TaskParticipant.is_active.is_(True),
        )
        .all()
        if getattr(participant, "user_id", None)
    ]
    if participant_ids:
        return sorted(set(participant_ids))

    return sorted({
        assignment.user_id
        for assignment in _task_assignment_records(task)
        if getattr(assignment, "user_id", None)
    })


def _task_user_is_executor(task, user_id):
    return bool(user_id and user_id in _task_executor_user_ids(task))


def _visible_child_tasks_for_user(parent_task_id, user_id):
    if not parent_task_id or not user_id:
        return []
    child_tasks = (
        Task.query.options(joinedload(Task.assignments))
        .filter_by(parent_task_id=parent_task_id)
        .order_by(Task.created_at.asc())
        .all()
    )
    visible_tasks = []
    for child_task in child_tasks:
        _ensure_task_runtime_bridge(child_task)
        if _task_user_is_executor(child_task, user_id):
            visible_tasks.append(child_task)
    return visible_tasks


def _load_linked_report_template_ids(task):
    if not task:
        return []

    ids = [
        int(link.report_template_id)
        for link in _query_task_scope(TaskReportLink, task).filter(TaskReportLink.report_template_id.isnot(None)).all()
        if getattr(link, "report_template_id", None)
    ]
    if ids:
        return sorted(set(ids))
    return _load_linked_report_template_ids_legacy(task)


def _resolve_scope_users(mode, role_ids=None, user_ids=None):
    if mode == "role":
        users = []
        for role_id in role_ids or []:
            users.extend(_resolve_role_assignees(role_id))
        return _dedupe_users(users)
    if mode == "user" and user_ids:
        return (
            User.query.filter(User.id.in_(user_ids), User.is_active.is_(True))
            .order_by(User.fullname.asc())
            .all()
        )
    return []


def _sync_task_participants(task, assignees=None, managers=None, viewers=None):
    if not task or not getattr(task, "id", None):
        return []

    task_id, task_item_id = _task_scope_identity(task)
    assignment_scope = _load_assignment_scope(task)
    manager_scope = _load_manager_scope(task)
    viewer_scope = _load_viewer_scope(task)
    assignees = _dedupe_users(
        assignees
        if assignees is not None
        else [assignment.user for assignment in _task_assignment_records(task) if getattr(assignment, "user", None)]
    )
    managers = _dedupe_users(managers if managers is not None else _resolve_scope_users(manager_scope.get("mode"), role_ids=manager_scope.get("role_ids"), user_ids=manager_scope.get("user_ids")))
    viewers = _dedupe_users(viewers if viewers is not None else _resolve_scope_users(viewer_scope.get("mode"), role_ids=viewer_scope.get("role_ids"), user_ids=viewer_scope.get("user_ids")))

    desired = {}
    for user in assignees:
        desired[(user.id, "executor")] = {
            "role_id": getattr(user, "role_id", None),
            "source_type": "assignment_scope",
            "source_ref": assignment_scope.get("mode") or getattr(task, "assign_type", None) or "unit",
        }
    for user in managers:
        desired[(user.id, "manager")] = {
            "role_id": getattr(user, "role_id", None),
            "source_type": "manager_scope",
            "source_ref": manager_scope.get("mode") or "none",
        }
    for user in viewers:
        desired[(user.id, "watcher")] = {
            "role_id": getattr(user, "role_id", None),
            "source_type": "viewer_scope",
            "source_ref": viewer_scope.get("mode") or "none",
        }

    existing = {
        (participant.user_id, participant.participant_type): participant
        for participant in _query_task_scope(TaskParticipant, task).all()
    }

    touched = []
    for key, meta in desired.items():
        participant = existing.pop(key, None)
        if not participant:
            participant = TaskParticipant(
                task_id=task_id,
                task_item_id=task_item_id,
                user_id=key[0],
                participant_type=key[1],
            )
            db.session.add(participant)
        participant.role_id = meta.get("role_id")
        participant.source_type = meta.get("source_type") or "direct"
        participant.source_ref = meta.get("source_ref") or ""
        participant.is_active = True
        touched.append(participant)

    for participant in existing.values():
        db.session.delete(participant)

    return touched


def _infer_submission_type(task, payload):
    report_kind = _task_simple_child_report_kind(task)
    if report_kind == "number":
        return "number"
    if isinstance(payload, dict) and payload.get("mode") == "structured_task_report":
        return "structured"
    if isinstance(payload, dict) and payload:
        return "payload"
    return "narrative"


def _extract_submission_numeric_value(task, payload):
    if not isinstance(payload, dict):
        return None
    if _task_simple_child_report_kind(task) != "number":
        return None
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    raw_value = values.get(CHILD_TASK_NUMBER_FIELD_KEY)
    try:
        parsed = _parse_report_number(raw_value)
    except ValueError:
        return None
    if parsed is None:
        return None
    return float(parsed)


def _upsert_task_submission_from_assignment(task, assignment, payload=None):
    if not task or not assignment:
        return None
    if not getattr(assignment, "user_id", None):
        current_app.logger.warning(
            "Skip task submission backfill for assignment without user_id: task=%s assignment=%s",
            getattr(task, "id", None),
            getattr(assignment, "id", None),
        )
        return None

    task_id, task_item_id = _task_scope_identity(task)
    payload = payload if payload is not None else _parse_assignment_payload(assignment)
    participant = _query_task_scope(TaskParticipant, task).filter(
        TaskParticipant.user_id == assignment.user_id,
        TaskParticipant.participant_type == "executor",
    ).first()
    submission = (
        _query_task_scope(TaskSubmission, task)
        .filter(TaskSubmission.assignment_id == assignment.id)
        .order_by(TaskSubmission.updated_at.desc(), TaskSubmission.id.desc())
        .first()
    )
    if not submission:
        submission = TaskSubmission(
            task_id=task_id,
            task_item_id=task_item_id,
            assignment_id=assignment.id,
            submitted_by=assignment.user_id,
        )
        db.session.add(submission)

    attachment_name = (getattr(assignment, "result_file", None) or "").strip() or (payload.get("attachment_name") if isinstance(payload, dict) else "") or ""
    has_payload_content = False
    if isinstance(payload, dict):
        if payload.get("mode") == "structured_task_report":
            has_payload_content = _structured_payload_has_content(payload)
        else:
            has_payload_content = bool(
                str(payload.get("narrative") or payload.get("narrative_report") or "").strip()
                or str(payload.get("attachment_name") or "").strip()
                or (
                    isinstance(payload.get("values"), dict)
                    and any(str(value or "").strip() for value in payload.get("values", {}).values())
                )
            )
    submission.participant_id = getattr(participant, "id", None)
    submission.submission_type = _infer_submission_type(task, payload)
    submission.status = "submitted" if (has_payload_content or attachment_name) else "draft"
    submission.narrative_content = (
        (payload.get("narrative") if isinstance(payload, dict) else None)
        or (payload.get("narrative_report") if isinstance(payload, dict) else None)
        or ""
    )
    submission.numeric_value = _extract_submission_numeric_value(task, payload)
    submission.payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
    submission.attachment_name = attachment_name or None
    submission.attachment_path = attachment_name or None
    submission.submitted_at = (
        getattr(assignment, "updated_at", None)
        if (has_payload_content or attachment_name)
        else None
    )
    return submission


def _sync_task_submissions(task):
    for assignment in _task_assignment_records(task):
        if not getattr(assignment, "user_id", None):
            continue
        _upsert_task_submission_from_assignment(task, assignment)


def _sync_task_report_links(task, template_ids=None):
    if not task or not getattr(task, "id", None):
        return []
    desired_ids = sorted({int(template_id) for template_id in (template_ids if template_ids is not None else _load_linked_report_template_ids_legacy(task)) if str(template_id).isdigit()})
    existing_links = {
        int(link.report_template_id): link
        for link in _query_task_scope(TaskReportLink, task).filter(TaskReportLink.sync_mode == "template").all()
        if getattr(link, "report_template_id", None)
    }
    task_id, task_item_id = _task_scope_identity(task)
    touched = []
    for template_id in desired_ids:
        link = existing_links.pop(template_id, None)
        if not link:
            link = TaskReportLink(
                task_id=task_id,
                task_item_id=task_item_id,
                report_template_id=template_id,
                sync_mode="template",
                is_primary=True,
            )
            db.session.add(link)
        touched.append(link)
    for link in existing_links.values():
        db.session.delete(link)
    return touched


def _task_item_status_from_task(task):
    assignment_records = _task_assignment_records(task)
    if not assignment_records:
        return _normalize_status(getattr(task, "initial_status", None)) or "Chưa tiếp nhận"
    statuses = [_normalize_status(assignment.status) for assignment in assignment_records]
    if statuses and all(status == COMPLETED_STATUS for status in statuses):
        return COMPLETED_STATUS
    if any(status != "Chưa tiếp nhận" for status in statuses):
        return IN_PROGRESS_STATUS
    return "Chưa tiếp nhận"


def _sync_task_items(task):
    if not task or not getattr(task, "id", None):
        return []

    root_task = task.parent_task or task
    if getattr(root_task, "parent_task_id", None):
        root_task = Task.query.filter_by(id=root_task.parent_task_id).first() or root_task

    child_tasks = (
        Task.query.options(joinedload(Task.assignments))
        .filter_by(parent_task_id=root_task.id)
        .order_by(Task.created_at.asc(), Task.id.asc())
        .all()
    )
    existing = {
        item.source_task_id: item
        for item in TaskItem.query.filter_by(task_id=root_task.id).all()
        if getattr(item, "source_task_id", None)
    }
    touched = []
    for sort_order, child_task in enumerate(child_tasks, start=1):
        child_schema = _load_task_report_schema(child_task)
        child_meta = _task_report_meta(child_schema)
        report_kind = _task_simple_child_report_kind(child_task) or child_meta.get("report_kind") or "narrative"
        item = existing.pop(child_task.id, None)
        if not item:
            item = TaskItem(task_id=root_task.id, source_task_id=child_task.id)
            db.session.add(item)
        item.title = child_task.title
        item.content = child_task.content
        item.report_kind = report_kind
        item.attachment_required = bool(child_meta.get("attachment_required"))
        item.status = _task_item_status_from_task(child_task)
        item.deadline = child_task.deadline
        item.sort_order = sort_order
        touched.append(item)

    for obsolete in existing.values():
        db.session.delete(obsolete)

    return touched


def _sync_task_runtime_models(task, assignees=None, managers=None, viewers=None, linked_report_template_ids=None, include_children=False):
    if not task:
        return
    _sync_task_items(task)
    _sync_task_participants(task, assignees=assignees, managers=managers, viewers=viewers)
    _sync_task_submissions(task)
    _sync_task_report_links(task, template_ids=linked_report_template_ids)
    if include_children:
        for child_task in task.child_tasks or []:
            _sync_task_runtime_models(child_task)


def _ensure_task_assignment_bridge(task):
    if not task or not getattr(task, "id", None):
        return False

    participant_user_ids = [
        participant.user_id
        for participant in _query_task_scope(TaskParticipant, task)
        .filter(
            TaskParticipant.participant_type == "executor",
            TaskParticipant.is_active.is_(True),
        )
        .all()
        if getattr(participant, "user_id", None)
    ]
    if not participant_user_ids:
        return False

    existing_assignments = {
        assignment.user_id: assignment
        for assignment in _task_assignment_records(task)
        if getattr(assignment, "user_id", None)
    }
    changed = False
    initial_status = _normalize_status(getattr(task, "initial_status", None)) or "Chưa tiếp nhận"
    for user_id in sorted(set(participant_user_ids)):
        if user_id in existing_assignments:
            continue
        task.assignments.append(
            TaskAssignment(
                task_id=task.id,
                user_id=user_id,
                status=initial_status,
            )
        )
        changed = True
    return changed


def _task_runtime_expected_counts(task):
    if not task:
        return {"task_items": 0, "executor_participants": 0, "submissions": 0, "report_links": 0}

    assignment_records = _task_assignment_records(task)
    executor_participants = len({
        assignment.user_id
        for assignment in assignment_records
        if getattr(assignment, "user_id", None)
    })
    submissions = sum(1 for assignment in assignment_records if getattr(assignment, "user_id", None))
    report_links = len(_load_linked_report_template_ids_legacy(task))
    task_items = Task.query.filter_by(parent_task_id=task.id).count() if not getattr(task, "parent_task_id", None) else 0
    return {
        "task_items": task_items,
        "executor_participants": executor_participants,
        "submissions": submissions,
        "report_links": report_links,
    }


def _task_runtime_bridge_needs_sync(task):
    if not task or not getattr(task, "id", None):
        return False

    expected = _task_runtime_expected_counts(task)
    task_item_count = TaskItem.query.filter_by(task_id=task.id).count() if not getattr(task, "parent_task_id", None) else 0
    participant_count = _query_task_scope(TaskParticipant, task).filter(
        TaskParticipant.participant_type == "executor",
        TaskParticipant.is_active.is_(True),
    ).count()
    submission_count = _query_task_scope(TaskSubmission, task).count()
    link_count = _query_task_scope(TaskReportLink, task).count()

    if expected["task_items"] and task_item_count < expected["task_items"]:
        return True
    if expected["executor_participants"] and participant_count < expected["executor_participants"]:
        return True
    if expected["submissions"] and submission_count < expected["submissions"]:
        return True
    if expected["report_links"] and link_count < expected["report_links"]:
        return True
    return False


def _ensure_task_runtime_bridge(task, include_children=False):
    if not task:
        return False

    changed = False
    if _ensure_task_assignment_bridge(task):
        changed = True
    if _task_runtime_bridge_needs_sync(task):
        _sync_task_runtime_models(task)
        changed = True

    if include_children:
        child_tasks = getattr(task, "child_tasks", None)
        if child_tasks is None:
            child_tasks = (
                Task.query.options(joinedload(Task.assignments))
                .filter_by(parent_task_id=task.id)
                .order_by(Task.created_at.asc())
                .all()
            )
        for child_task in child_tasks or []:
            if _ensure_task_runtime_bridge(child_task, include_children=False):
                changed = True
    return changed


def _task_assignment_for_user(task, user_id, create_from_executor=False):
    if not task or not user_id:
        return None

    for assignment in _task_assignment_records(task):
        if getattr(assignment, "user_id", None) == user_id:
            return assignment

    if create_from_executor and _task_user_is_executor(task, user_id):
        if _ensure_task_assignment_bridge(task):
            db.session.flush()
        for assignment in _task_assignment_records(task):
            if getattr(assignment, "user_id", None) == user_id:
                return assignment

    return TaskAssignment.query.filter_by(task_id=task.id, user_id=user_id).first()


def _task_latest_reporting_assignment(task):
    if not task:
        return None

    reporting_assignments = [
        assignment
        for assignment in _task_assignment_records(task)
        if _assignment_has_report_submission(assignment)
    ]
    if not reporting_assignments:
        return None
    return max(
        reporting_assignments,
        key=lambda assignment: _assignment_report_snapshot(assignment).get("latest_report_at") or getattr(assignment, "updated_at", None) or datetime.min,
    )


def _task_assignment_rows(task, ensure_bridge=False):
    if not task:
        return []

    if ensure_bridge and _ensure_task_runtime_bridge(task):
        db.session.flush()

    rows = []
    for assignment in _task_assignment_records(task):
        user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
        if not user:
            continue
        rows.append((assignment, user))

    rows.sort(
        key=lambda item: (
            -(getattr(item[0], "updated_at", None) or datetime.min).timestamp()
            if (getattr(item[0], "updated_at", None) or None)
            else float("inf"),
            (getattr(item[1], "fullname", None) or getattr(item[1], "username", None) or "").lower(),
        )
    )
    return rows


def _backfill_task_runtime_models(batch_size=250):
    normalized_batch_size = max(int(batch_size or 0), 1)
    scanned_count = 0
    changed_count = 0
    last_task_id = 0

    while True:
        tasks = (
            Task.query.options(joinedload(Task.assignments))
            .filter(Task.id > last_task_id)
            .order_by(Task.id.asc())
            .limit(normalized_batch_size)
            .all()
        )
        if not tasks:
            break

        batch_changed = False
        for task in tasks:
            scanned_count += 1
            last_task_id = max(last_task_id, task.id or 0)
            if _ensure_task_runtime_bridge(task):
                changed_count += 1
                batch_changed = True

        if batch_changed:
            db.session.commit()

        if len(tasks) < normalized_batch_size:
            break

    return {
        "scanned": scanned_count,
        "changed": changed_count,
    }


def _task_template_current_cycle(template):
    if not template:
        return None
    version_ids = [
        row.id
        for row in ReportTemplateVersion.query.filter_by(template_id=template.id).all()
    ]
    if not version_ids:
        return None
    cycles = (
        ReportCycle.query.filter(ReportCycle.template_version_id.in_(version_ids))
        .order_by(ReportCycle.created_at.desc())
        .all()
    )
    for cycle in cycles:
        if cycle.status != "closed":
            return cycle
    return cycles[0] if cycles else None


def _build_linked_report_template_views(task, can_manage_report_admin=False, can_open_report_workspace=False):
    template_ids = _load_linked_report_template_ids(task)
    if not template_ids:
        return []

    templates = {
        template.id: template
        for template in ReportTemplate.query.filter(ReportTemplate.id.in_(template_ids)).all()
    }
    report_types = {
        item.id: item
        for item in ReportType.query.filter(
            ReportType.id.in_([template.report_type_id for template in templates.values() if template.report_type_id])
        ).all()
    } if templates else {}

    views = []
    for template_id in template_ids:
        template = templates.get(template_id)
        if not template:
            continue
        cycle = _task_template_current_cycle(template)
        instances = ReportInstance.query.filter_by(cycle_id=cycle.id).all() if cycle else []
        total_units = len(instances)
        submitted_units = sum(
            1 for instance in instances
            if (getattr(instance, "status", "") or "").strip().lower() == "submitted" or getattr(instance, "submitted_at", None)
        )
        draft_units = sum(
            1 for instance in instances
            if (getattr(instance, "status", "") or "").strip().lower() == "draft"
        )
        professional_unit_display = resolve_category_display(
            getattr(template, "professional_unit", None),
            _task_domain_options(),
            fallback_label="Chưa phân đội",
        ).get("display_name") or "Chưa phân đội"
        report_type = report_types.get(template.report_type_id)
        views.append(
            {
                "template_id": template.id,
                "template_name": template.name,
                "report_type_name": getattr(report_type, "name", "Chưa phân loại"),
                "professional_unit_display": professional_unit_display,
                "cycle_id": getattr(cycle, "id", None),
                "cycle_name": getattr(cycle, "name", "") or "Chưa có đợt báo cáo",
                "cycle_status": getattr(cycle, "status", "") or "draft",
                "is_locked": bool(getattr(cycle, "is_locked", False)),
                "due_at": getattr(cycle, "due_at", None),
                "total_units": total_units,
                "submitted_units": submitted_units,
                "draft_units": draft_units,
                "progress_percent": int(round((submitted_units / total_units) * 100)) if total_units else 0,
                "manage_url": url_for("reporting_bp.admin_cycle_detail", cycle_id=cycle.id) if cycle and can_manage_report_admin else "",
                "workspace_url": url_for("reporting_bp.cycle_workspace", cycle_id=cycle.id) if cycle and can_open_report_workspace else "",
                "status_label": (
                    "Đã đóng" if getattr(cycle, "status", "") == "closed"
                    else "Đã khóa" if getattr(cycle, "is_locked", False)
                    else "Đang mở" if cycle
                    else "Chưa cấu hình đợt báo cáo"
                ),
            }
        )
    return views


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


def _sync_task_assignments(task, assignees):
    assignment_records = _task_assignment_records(task)
    existing_assignments = {assignment.user_id: assignment for assignment in assignment_records}
    new_assignee_ids = {user.id for user in assignees}
    new_assignees_to_notify = []

    for assignment in assignment_records:
        if assignment.user_id not in new_assignee_ids:
            db.session.delete(assignment)

    for user in assignees:
        if user.id not in existing_assignments:
            db.session.add(
                TaskAssignment(task_id=task.id, user_id=user.id, status="Chưa tiếp nhận")
            )
            new_assignees_to_notify.append(user)

    return len(new_assignee_ids), new_assignees_to_notify


def _can_manage_task(task, user=None):
    if not task or not session.get("uid"):
        return False
    if bool(session.get("is_admin")) or task.author_id == session.get("uid") or _can_process_task_module():
        return True

    if user is None:
        uid = session.get("uid")
        user = db.session.get(User, uid) if uid else None
    if not user:
        return False

    manager_scope = _load_manager_scope(task)
    mode = manager_scope.get("mode") or "none"
    if mode == "role" and getattr(user, "role_id", None) in (manager_scope.get("role_ids") or []):
        return True
    if mode == "user" and getattr(user, "id", None) in (manager_scope.get("user_ids") or []):
        return True

    parent_task = getattr(task, "parent_task", None)
    if not parent_task and getattr(task, "parent_task_id", None):
        parent_task = Task.query.filter_by(id=task.parent_task_id).first()
    if parent_task:
        return _can_manage_task(parent_task, user=user)
    return False


def _can_edit_task(task):
    return _can_manage_task(task)


def _can_delete_task(task, is_lead=False):
    if not task or not session.get("uid"):
        return False
    if bool(session.get("is_admin")) or task.author_id == session.get("uid"):
        return True
    if is_lead:
        return True
    return _can_manage_task(task)


def _can_watch_task(task, user=None):
    if not task:
        return False

    if user is None:
        uid = session.get("uid")
        user = db.session.get(User, uid) if uid else None
    if not user:
        return False

    viewer_scope = _load_viewer_scope(task)
    mode = viewer_scope.get("mode") or "none"
    if mode == "role" and getattr(user, "role_id", None) in (viewer_scope.get("role_ids") or []):
        return True
    if mode == "user" and getattr(user, "id", None) in (viewer_scope.get("user_ids") or []):
        return True

    parent_task = getattr(task, "parent_task", None)
    if not parent_task and getattr(task, "parent_task_id", None):
        parent_task = Task.query.filter_by(id=task.parent_task_id).first()
    if parent_task:
        return _can_watch_task(parent_task, user=user)
    return False


def _can_view_task(task, is_lead=False):
    if not task or not session.get("uid"):
        return False
    if session.get("is_admin") or is_lead or task.author_id == session.get("uid"):
        return True
    if _task_user_is_executor(task, session.get("uid")):
        return True
    if _can_manage_task(task):
        return True
    if _can_watch_task(task):
        return True
    return bool(_visible_child_tasks_for_user(task.id, session.get("uid")))


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

def _report_checkbox_value(value):
    return str(value or "").strip().lower() in {"1", "true", "on", "yes"}


def _task_report_field_key(label, index, used_keys):
    raw_key = secure_filename(remove_accents(label or "").replace(" ", "_")).strip("_")
    key = raw_key or f"field_{index + 1}"
    while key in used_keys:
        key = f"{key}_{len(used_keys) + 1}"
    used_keys.add(key)
    return key


def _normalize_report_target_ids(values):
    normalized = []
    for value in values if isinstance(values, (list, tuple, set)) else []:
        text = str(value or "").strip()
        if not text.isdigit():
            continue
        numeric_value = int(text)
        if numeric_value not in normalized:
            normalized.append(numeric_value)
    return normalized


def _normalize_report_target_config(raw_config, defaults=None):
    defaults = defaults or {}
    target_type = str(raw_config.get("target_type") or defaults.get("target_type") or "all").strip().lower()
    if target_type not in TASK_REPORT_ALLOWED_TARGET_TYPES:
        target_type = "all"
    return {
        "target_type": target_type,
        "target_role_ids": _normalize_report_target_ids(
            raw_config.get("target_role_ids", defaults.get("target_role_ids", []))
        ),
        "target_user_ids": _normalize_report_target_ids(
            raw_config.get("target_user_ids", defaults.get("target_user_ids", []))
        ),
    }


def _task_report_item_visible_for_user(item_config, user):
    if not item_config or not user:
        return False

    target_type = str(item_config.get("target_type") or "all").strip().lower()
    if target_type == "role":
        role_id = getattr(user, "role_id", None)
        return bool(role_id and role_id in (item_config.get("target_role_ids") or []))
    if target_type == "user":
        user_id = getattr(user, "id", None)
        return bool(user_id and user_id in (item_config.get("target_user_ids") or []))
    return True


def _normalize_child_task_report_meta(raw_meta, fields, attachment):
    raw_meta = raw_meta if isinstance(raw_meta, dict) else {}
    kind = str(raw_meta.get("kind") or "").strip().lower()
    if kind != "simple_child_task":
        return {}

    report_kind = str(raw_meta.get("report_kind") or "").strip().lower()
    if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
        report_kind = "number" if any(field.get("type") == "number" for field in fields) else "narrative"

    number_field_key = ""
    if report_kind == "number":
        number_field_key = next((field.get("key") or "" for field in fields if field.get("type") == "number"), "")

    return {
        "kind": "simple_child_task",
        "report_kind": report_kind,
        "attachment_required": bool(attachment.get("enabled") and attachment.get("required")),
        "number_field_key": number_field_key,
    }


def _normalize_task_report_schema(raw_schema):
    if not isinstance(raw_schema, dict):
        return None

    narrative_input = raw_schema.get("narrative") if isinstance(raw_schema.get("narrative"), dict) else {}
    attachment_input = raw_schema.get("attachment") if isinstance(raw_schema.get("attachment"), dict) else {}
    used_keys = set()
    fields = []
    for index, item in enumerate(raw_schema.get("fields") if isinstance(raw_schema.get("fields"), list) else []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        field_type = str(item.get("type") or "number").strip().lower()
        if field_type not in TASK_REPORT_ALLOWED_FIELD_TYPES:
            field_type = "number"
        fields.append(
            {
                "key": _task_report_field_key(item.get("key") or label, index, used_keys),
                "label": label[:255],
                "type": field_type,
                "required": _report_checkbox_value(item.get("required")),
                "placeholder": str(item.get("placeholder") or "").strip()[:255],
                "help_text": str(item.get("help_text") or "").strip()[:255],
                **_normalize_report_target_config(item),
            }
        )

    narrative = {
        "enabled": _report_checkbox_value(narrative_input.get("enabled", True)),
        "label": str(narrative_input.get("label") or DEFAULT_TASK_REPORT_SCHEMA["narrative"]["label"]).strip()[:255],
        "required": _report_checkbox_value(narrative_input.get("required", True)),
        "placeholder": str(
            narrative_input.get("placeholder") or DEFAULT_TASK_REPORT_SCHEMA["narrative"]["placeholder"]
        ).strip()[:255],
        **_normalize_report_target_config(narrative_input, DEFAULT_TASK_REPORT_SCHEMA["narrative"]),
    }
    attachment = {
        "enabled": _report_checkbox_value(attachment_input.get("enabled")),
        "label": str(attachment_input.get("label") or DEFAULT_TASK_REPORT_SCHEMA["attachment"]["label"]).strip()[:255],
        "required": _report_checkbox_value(attachment_input.get("required")),
        **_normalize_report_target_config(attachment_input, DEFAULT_TASK_REPORT_SCHEMA["attachment"]),
    }

    enabled = _report_checkbox_value(raw_schema.get("enabled")) or bool(fields) or narrative["enabled"] or attachment["enabled"]
    if not enabled:
        return None

    return {
        "version": 1,
        "enabled": True,
        "narrative": narrative,
        "attachment": attachment,
        "fields": fields,
        "meta": _normalize_child_task_report_meta(raw_schema.get("meta"), fields, attachment),
    }


def _load_task_report_schema(task):
    if not task:
        return None

    cached = getattr(task, "_task_report_schema_cache", None)
    if cached is not None:
        return cached

    raw_schema = getattr(task, "report_schema_json", None) or ""
    if not raw_schema:
        setattr(task, "_task_report_schema_cache", None)
        return None

    try:
        parsed = json.loads(raw_schema)
    except Exception:
        setattr(task, "_task_report_schema_cache", None)
        return None

    normalized = _normalize_task_report_schema(parsed)
    setattr(task, "_task_report_schema_cache", normalized)
    return normalized


def _task_report_schema_seed(task=None):
    schema = _load_task_report_schema(task)
    if schema:
        return schema
    return json.loads(json.dumps(DEFAULT_TASK_REPORT_SCHEMA))


def _parse_task_report_schema_from_request(form):
    if not _report_checkbox_value(form.get("report_schema_enabled")):
        return None

    raw_schema = (form.get("report_schema_json") or "").strip()
    if not raw_schema:
        return _normalize_task_report_schema(DEFAULT_TASK_REPORT_SCHEMA)

    try:
        parsed = json.loads(raw_schema)
    except Exception as exc:
        raise ValueError("Biểu mẫu báo cáo không hợp lệ.") from exc

    normalized = _normalize_task_report_schema(parsed)
    if not normalized:
        raise ValueError("Biểu mẫu báo cáo chưa có nội dung hợp lệ.")
    return normalized


def _parse_report_number(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Giá trị số không hợp lệ.") from exc


def _format_report_number(value):
    if value is None:
        return ""
    normalized = value.quantize(Decimal("1")) if value == value.to_integral() else value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _build_simple_child_task_schema(report_kind="narrative", attachment_required=False):
    normalized_kind = str(report_kind or "narrative").strip().lower()
    if normalized_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
        normalized_kind = "narrative"

    raw_schema = {
        "enabled": True,
        "narrative": {
            "enabled": normalized_kind == "narrative",
            "label": "Nội dung báo cáo",
            "required": normalized_kind == "narrative",
            "placeholder": "Nhập nội dung báo cáo",
            "target_type": "all",
            "target_role_ids": [],
            "target_user_ids": [],
        },
        "attachment": {
            "enabled": bool(attachment_required),
            "label": "Tệp minh chứng",
            "required": bool(attachment_required),
            "target_type": "all",
            "target_role_ids": [],
            "target_user_ids": [],
        },
        "fields": [],
        "meta": {
            "kind": "simple_child_task",
            "report_kind": normalized_kind,
        },
    }
    if normalized_kind == "number":
        raw_schema["fields"] = [
            {
                "key": CHILD_TASK_NUMBER_FIELD_KEY,
                "label": "Số liệu báo cáo",
                "type": "number",
                "required": True,
                "placeholder": "Nhập số cần báo cáo",
                "help_text": "",
                "target_type": "all",
                "target_role_ids": [],
                "target_user_ids": [],
            }
        ]
    return _normalize_task_report_schema(raw_schema)


def _parse_structured_task_report_payload(assignment):
    latest_submission = _latest_assignment_submission(assignment)
    if latest_submission:
        payload = _parse_task_submission_payload(latest_submission)
        if payload.get("mode") == "structured_task_report":
            return payload
    payload = _parse_assignment_payload(assignment)
    if payload.get("mode") != "structured_task_report":
        return None
    return payload


def _task_submission_sort_key(submission):
    return (
        getattr(submission, "submitted_at", None)
        or getattr(submission, "updated_at", None)
        or getattr(submission, "created_at", None)
        or datetime.min
    )


def _parse_task_submission_payload(submission):
    raw_payload = getattr(submission, "payload_json", None) or ""
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_assignment_submission(assignment):
    submission_records = getattr(assignment, "submission_records", None) or []
    if not submission_records and getattr(assignment, "id", None):
        submission_records = (
            TaskSubmission.query.filter_by(assignment_id=assignment.id)
            .order_by(TaskSubmission.updated_at.desc(), TaskSubmission.id.desc())
            .all()
        )
    if not submission_records:
        return None
    return sorted(
        submission_records,
        key=_task_submission_sort_key,
        reverse=True,
    )[0]


def _submission_has_report_content(submission):
    if not submission:
        return False
    payload = _parse_task_submission_payload(submission)
    if payload.get("mode") == "structured_task_report":
        return _structured_payload_has_content(payload)
    if (
        str(getattr(submission, "narrative_content", "") or "").strip()
        or getattr(submission, "numeric_value", None) is not None
        or str(getattr(submission, "attachment_name", "") or "").strip()
    ):
        return True
    if str(payload.get("narrative") or payload.get("narrative_report") or "").strip():
        return True
    if isinstance(payload.get("values"), dict) and any(
        str(value or "").strip() for value in payload.get("values", {}).values()
    ):
        return True
    return bool(str(payload.get("attachment_name") or "").strip())


def _assignment_report_comment_snapshots(comments, user_id):
    latest_item = None
    first_time = None
    for comment in comments or []:
        if getattr(comment, "user_id", None) != user_id:
            continue
        if not (getattr(comment, "content", "") or "").startswith(REPORT_PREFIX):
            continue
        created_at = getattr(comment, "created_at", None)
        if created_at and (first_time is None or created_at < first_time):
            first_time = created_at
        if latest_item is None or (
            created_at and created_at > getattr(latest_item, "created_at", None)
        ):
            latest_item = comment
    return latest_item, first_time


def _assignment_report_snapshot(assignment, comments=None):
    empty_snapshot = {
        "source": "",
        "payload": {},
        "attachment_name": "",
        "reported_at": None,
        "first_report_at": None,
        "excerpt": "",
        "summary_text": "",
        "submission": None,
        "has_report": False,
    }
    if not assignment:
        return empty_snapshot

    latest_submission = _latest_assignment_submission(assignment)
    if latest_submission and _submission_has_report_content(latest_submission):
        payload = _parse_task_submission_payload(latest_submission)
        attachment_name = (
            str(getattr(latest_submission, "attachment_name", "") or "").strip()
            or str(payload.get("attachment_name") or "").strip()
            or str(getattr(assignment, "result_file", "") or "").strip()
        )
        excerpt = str(
            getattr(latest_submission, "narrative_content", None)
            or payload.get("narrative")
            or payload.get("narrative_report")
            or ""
        ).strip()
        reported_at = _task_submission_sort_key(latest_submission)
        if reported_at == datetime.min:
            reported_at = None
        return {
            "source": "submission",
            "payload": payload,
            "attachment_name": attachment_name,
            "reported_at": reported_at,
            "first_report_at": reported_at,
            "excerpt": excerpt,
            "summary_text": excerpt,
            "submission": latest_submission,
            "has_report": True,
        }

    latest_comment, first_comment_at = _assignment_report_comment_snapshots(
        comments,
        getattr(assignment, "user_id", None),
    )
    legacy_payload = _parse_assignment_payload(assignment)
    attachment_name = (
        str(legacy_payload.get("attachment_name") or "").strip()
        or str(getattr(assignment, "result_file", "") or "").strip()
    )
    excerpt = str(
        legacy_payload.get("narrative")
        or legacy_payload.get("narrative_report")
        or ""
    ).strip()
    summary_text = excerpt
    latest_report_at = None
    if latest_comment:
        summary_text, comment_attachment_name = _parse_report_comment_content(
            getattr(latest_comment, "content", "") or ""
        )
        if not attachment_name:
            attachment_name = comment_attachment_name
        if not excerpt:
            excerpt = summary_text
        latest_report_at = getattr(latest_comment, "created_at", None)

    if not latest_report_at and _assignment_has_report_submission_legacy(assignment):
        latest_report_at = getattr(assignment, "updated_at", None)

    has_report = bool(
        latest_report_at
        or attachment_name
        or excerpt
        or summary_text
        or _assignment_has_report_submission_legacy(assignment)
    )
    return {
        "source": "legacy_comment" if latest_comment else ("legacy_payload" if has_report else ""),
        "payload": legacy_payload,
        "attachment_name": attachment_name,
        "reported_at": latest_report_at,
        "first_report_at": first_comment_at or latest_report_at,
        "excerpt": excerpt,
        "summary_text": summary_text,
        "submission": None,
        "has_report": has_report,
    }


def _assignment_numeric_report_value(task, assignment):
    schema = _load_task_report_schema(task)
    number_field_key = (
        _task_report_meta(schema).get("number_field_key")
        or CHILD_TASK_NUMBER_FIELD_KEY
    )
    latest_submission = _latest_assignment_submission(assignment)
    if latest_submission and getattr(latest_submission, "numeric_value", None) is not None:
        try:
            return Decimal(str(latest_submission.numeric_value))
        except Exception:
            pass
    payload = _parse_structured_task_report_payload(assignment)
    values = payload.get("values") if isinstance(payload, dict) else {}
    raw_value = values.get(number_field_key) if isinstance(values, dict) else ""
    try:
        return _parse_report_number(raw_value)
    except ValueError:
        return None


def _task_report_value_preview(value, limit=120):
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _structured_task_report_summary_lines(schema, payload, limit=4):
    if not schema or not payload:
        return []

    lines = []
    narrative_text = str(payload.get("narrative") or "").strip()
    if narrative_text:
        label = (schema.get("narrative") or {}).get("label") or "Báo cáo lời"
        lines.append(f"{label}: {_task_report_value_preview(narrative_text, 160)}")

    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    for field in schema.get("fields", []):
        value = str(values.get(field.get("key")) or "").strip()
        if not value:
            continue
        lines.append(f"{field.get('label')}: {_task_report_value_preview(value, 120)}")
        if len(lines) >= limit:
            break

    return lines[:limit]


def _task_report_meta(schema):
    meta = (schema or {}).get("meta")
    return meta if isinstance(meta, dict) else {}


def _task_is_simple_child_report(task):
    return _task_report_meta(_load_task_report_schema(task)).get("kind") == "simple_child_task"


def _task_simple_child_report_kind(task):
    meta = _task_report_meta(_load_task_report_schema(task))
    kind = str(meta.get("report_kind") or "").strip().lower()
    return kind if kind in CHILD_TASK_ALLOWED_REPORT_KINDS else ""


def _structured_payload_has_content(payload):
    if not isinstance(payload, dict):
        return False
    if str(payload.get("narrative") or "").strip():
        return True
    if str(payload.get("attachment_name") or "").strip():
        return True
    values = payload.get("values")
    return bool(
        isinstance(values, dict)
        and any(str(value or "").strip() for value in values.values())
    )


def _assignment_has_report_submission_legacy(assignment):
    payload = _parse_assignment_payload(assignment)
    if payload.get("mode") == "structured_task_report":
        return _structured_payload_has_content(payload)
    if str(payload.get("narrative") or payload.get("narrative_report") or "").strip():
        return True
    if isinstance(payload.get("values"), dict) and any(
        str(value or "").strip() for value in payload.get("values", {}).values()
    ):
        return True
    if str(payload.get("attachment_name") or "").strip():
        return True
    return bool(
        (getattr(assignment, "report_payload_json", None) or "").strip()
        or (getattr(assignment, "result_file", None) or "").strip()
    )


def _assignment_has_report_submission(assignment):
    latest_submission = _latest_assignment_submission(assignment)
    if latest_submission and _submission_has_report_content(latest_submission):
        return True
    return _assignment_has_report_submission_legacy(assignment)


def _child_task_numeric_total(task):
    schema = _load_task_report_schema(task)
    meta = _task_report_meta(schema)
    if meta.get("kind") != "simple_child_task" or meta.get("report_kind") != "number":
        return None

    total = Decimal("0")
    has_value = False
    for assignment, _user in _task_assignment_rows(task, ensure_bridge=True):
        numeric_value = _assignment_numeric_report_value(task, assignment)
        if numeric_value is None:
            continue
        total += numeric_value
        has_value = True
    return _format_report_number(total) if has_value else None


def _build_child_task_unit_summary(task):
    unit_rows = {}
    assignment_rows = _task_assignment_rows(task, ensure_bridge=True)
    for assignment, user in assignment_rows:
        unit_identity = _task_unit_identity(user)
        unit_key = unit_identity.get("unit_key") or f"user_{user.id}"
        row = unit_rows.setdefault(
            unit_key,
            {
                "unit_name": unit_identity.get("unit_name") or getattr(user, "fullname", None) or f"UID {user.id}",
                "latest_assignment": None,
                "latest_snapshot": None,
                "latest_report_at": None,
            },
        )
        snapshot = _assignment_report_snapshot(assignment)
        if not snapshot.get("has_report"):
            continue
        updated_at = snapshot.get("reported_at")
        if row["latest_report_at"] is None or (updated_at and updated_at >= row["latest_report_at"]):
            row["latest_report_at"] = updated_at
            row["latest_assignment"] = assignment
            row["latest_snapshot"] = snapshot

    total_units = len(unit_rows)
    reported_units = sum(1 for row in unit_rows.values() if row.get("latest_assignment"))
    numeric_total = None
    if _task_simple_child_report_kind(task) == "number":
        total = Decimal("0")
        has_value = False
        for row in unit_rows.values():
            assignment = row.get("latest_assignment")
            if not assignment:
                continue
            numeric_value = _assignment_numeric_report_value(task, assignment)
            if numeric_value is None:
                continue
            total += numeric_value
            has_value = True
        numeric_total = _format_report_number(total) if has_value else None

    return {
        "total_units": total_units or len(assignment_rows),
        "reported_units": reported_units,
        "numeric_total": numeric_total,
    }


def _build_child_task_reporting_matrix(child_tasks):
    task_rows = []
    unit_rows = {}

    for child_task in child_tasks or []:
        assignment_rows = _task_assignment_rows(child_task, ensure_bridge=True)
        expected_units = {}
        reported_units = {}

        for assignment, user in assignment_rows:
            unit_identity = _task_unit_identity(user)
            unit_key = unit_identity.get("unit_key") or f"user_{user.id}"
            expected_unit = expected_units.setdefault(
                unit_key,
                {
                    "unit_key": unit_key,
                    "unit_name": unit_identity.get("unit_name") or getattr(user, "fullname", None) or f"UID {user.id}",
                    "latest_report_at": None,
                },
            )
            report_snapshot = _assignment_report_snapshot(assignment)
            if not report_snapshot.get("has_report"):
                continue
            report_time = report_snapshot.get("reported_at")
            current_reported = reported_units.get(unit_key)
            if current_reported is None or (
                report_time and (current_reported.get("latest_report_at") is None or report_time >= current_reported.get("latest_report_at"))
            ):
                expected_unit["latest_report_at"] = report_time
                reported_units[unit_key] = {
                    "unit_key": unit_key,
                    "unit_name": expected_unit["unit_name"],
                    "latest_report_at": report_time,
                }

        missing_units = [
            item for key, item in expected_units.items()
            if key not in reported_units
        ]
        reported_unit_items = list(reported_units.values())
        reported_unit_items.sort(key=lambda item: item["unit_name"].lower())
        missing_units.sort(key=lambda item: item["unit_name"].lower())

        task_rows.append(
            {
                "task_id": child_task.id,
                "title": child_task.title,
                "reported_units": len(reported_unit_items),
                "total_units": len(expected_units),
                "missing_units": len(missing_units),
                "numeric_total": getattr(child_task, "number_total", None),
                "reported_unit_items": reported_unit_items,
                "missing_unit_items": missing_units,
            }
        )

        for unit_key, item in expected_units.items():
            unit_row = unit_rows.setdefault(
                unit_key,
                {
                    "unit_key": unit_key,
                    "unit_name": item["unit_name"],
                    "reported_count": 0,
                    "total_count": 0,
                    "reported_items": [],
                    "missing_items": [],
                },
            )
            unit_row["total_count"] += 1
            unit_item = {
                "task_id": child_task.id,
                "task_title": child_task.title,
            }
            if unit_key in reported_units:
                unit_row["reported_count"] += 1
                unit_row["reported_items"].append(
                    {
                        **unit_item,
                        "reported_at": reported_units[unit_key].get("latest_report_at"),
                    }
                )
            else:
                unit_row["missing_items"].append(unit_item)

    task_rows.sort(key=lambda item: (item["missing_units"] == 0, item["title"].lower()))
    unit_row_items = list(unit_rows.values())
    for unit_row in unit_row_items:
        unit_row["missing_count"] = max(unit_row["total_count"] - unit_row["reported_count"], 0)
        unit_row["reported_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row["missing_items"].sort(key=lambda item: item["task_title"].lower())
    unit_row_items.sort(key=lambda item: (-item["missing_count"], item["unit_name"].lower()))

    return {
        "task_rows": task_rows,
        "unit_rows": unit_row_items,
    }


def _build_structured_task_report_comment(schema, payload):
    summary_lines = _structured_task_report_summary_lines(schema, payload, limit=5)
    if summary_lines:
        return " | ".join(summary_lines)
    return "Đã cập nhật biểu mẫu báo cáo."


def _build_structured_task_report_form(task, user_assign, current_user):
    schema = _load_task_report_schema(task)
    if not task or not user_assign or not schema or not current_user:
        return None

    report_snapshot = _assignment_report_snapshot(user_assign)
    payload = _parse_structured_task_report_payload(user_assign) or {}
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    attachment_name = (
        str(payload.get("attachment_name") or "").strip()
        or str(report_snapshot.get("attachment_name") or "").strip()
    )
    fields = []
    for field in schema.get("fields", []):
        fields.append(
            {
                "key": field.get("key"),
                "label": field.get("label"),
                "type": field.get("type"),
                "required": bool(field.get("required")),
                "placeholder": field.get("placeholder") or "",
                "help_text": field.get("help_text") or "",
                "value": str(values.get(field.get("key")) or ""),
                "target_type": field.get("target_type") or "all",
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
            }
        )
    visible_fields = [field for field in fields if _task_report_item_visible_for_user(field, current_user)]
    narrative_cfg = schema.get("narrative") or {}
    attachment_cfg = schema.get("attachment") or {}
    visible_narrative = bool(narrative_cfg.get("enabled")) and _task_report_item_visible_for_user(narrative_cfg, current_user)
    visible_attachment = bool(attachment_cfg.get("enabled")) and _task_report_item_visible_for_user(attachment_cfg, current_user)
    has_visible_content = visible_narrative or visible_attachment or bool(visible_fields)

    return {
        "narrative": {
            "enabled": visible_narrative,
            "label": narrative_cfg.get("label") or "Báo cáo lời tổng hợp",
            "required": bool(narrative_cfg.get("required")),
            "placeholder": narrative_cfg.get("placeholder") or "",
            "value": str(payload.get("narrative") or ""),
        },
        "attachment": {
            "enabled": visible_attachment,
            "label": attachment_cfg.get("label") or "Tệp minh chứng",
            "required": bool(attachment_cfg.get("required")),
            "value": attachment_name,
        },
        "fields": visible_fields,
        "updated_at": payload.get("updated_at", "") or (
            report_snapshot["reported_at"].strftime("%d/%m/%Y %H:%M")
            if report_snapshot.get("reported_at")
            else ""
        ),
        "summary_lines": _structured_task_report_summary_lines(schema, payload, limit=6),
        "has_visible_content": has_visible_content,
    }


def _build_assignment_report_context(user_assign, comments, task=None):
    report_snapshot = _assignment_report_snapshot(user_assign, comments=comments)
    report_schema = _load_task_report_schema(task)
    structured_payload = _parse_structured_task_report_payload(user_assign) if user_assign and report_schema else None
    attachment_label = ((report_schema or {}).get("attachment") or {}).get("label") or "Tệp minh chứng"
    summary_lines = _structured_task_report_summary_lines(report_schema, structured_payload, limit=4)
    if not summary_lines and report_snapshot.get("summary_text"):
        summary_lines = [_task_report_value_preview(report_snapshot.get("summary_text"), 180)]

    return {
        "latest_report_at": report_snapshot.get("reported_at"),
        "latest_report_content": report_snapshot.get("summary_text", ""),
        "result_file": report_snapshot.get("attachment_name", ""),
        "status": _normalize_status(getattr(user_assign, "status", "")) if user_assign else "Chưa tiếp nhận",
        "attachment_label": attachment_label,
        "summary_lines": summary_lines,
        "has_structured_payload": bool(structured_payload),
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

        report_item = _assignment_report_snapshot(assignment, comments=comments)
        file_name = report_item.get("attachment_name") or ""
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

        if report_item.get("has_report"):
            card["has_report"] = True
            report_time = report_item.get("reported_at")
            if report_time and (card["latest_report_at"] is None or report_time > card["latest_report_at"]):
                card["latest_report_at"] = report_time
                card["latest_report_user_name"] = display_name
                card["latest_report_excerpt"] = report_item.get("summary_text") or report_item.get("excerpt") or ""

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
                "has_file": bool(_assignment_report_snapshot(assignment).get("attachment_name")),
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


def _is_da06_month_task(task):
    text = remove_accents(f"{getattr(task, 'title', '')} {getattr(task, 'content', '')}").strip().lower()
    return any(marker in text for marker in DA06_TASK_MARKERS)


def _normalized_text(value):
    return remove_accents(value or "").strip().lower()


def _da06_user_profile(user):
    username = (getattr(user, "username", None) or "").strip().lower()
    role_name = _normalized_text(getattr(getattr(user, "role", None), "name", None) or "")
    unit_name = _normalized_text(getattr(user, "unit_area_display", None) or getattr(user, "unit_area", None) or "")
    if username == DA06_TTPVHCC_USERNAME:
        return {"kind": "tthcc", "label": "Trung tâm Phục vụ hành chính công"}
    if any(marker in role_name for marker in DA06_TCT_ROLE_MARKERS):
        return {"kind": "tct_xa", "label": "Tổ công tác cấp xã"}
    for rule in DA06_SO_NGANH_RULES:
        if any(marker in unit_name for marker in rule["unit_markers"]):
            return {"kind": "so_nganh", "label": rule["label"], "rule": rule}
    return {"kind": "so_nganh", "label": "Sở, ban, ngành", "rule": None}


def _parse_assignment_payload(assignment):
    latest_submission = _latest_assignment_submission(assignment)
    if latest_submission:
        payload = _parse_task_submission_payload(latest_submission)
        if payload:
            return payload
    raw_payload = getattr(assignment, "report_payload_json", None) or ""
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_task_attachment(file_storage, task_id, user_id, label):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    original_name = secure_filename(file_storage.filename)
    if not original_name:
        return None
    base_name, ext = os.path.splitext(original_name)
    attachment_name = secure_filename(
        f"da06_{task_id}_{user_id}_{secure_filename(remove_accents(label or 'tep').replace(' ', '_'))}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    )
    file_storage.save(_task_file_path(attachment_name))
    return attachment_name


def _da06_tct_sections(payload):
    attachments = payload.get("attachments", {}) if isinstance(payload.get("attachments"), dict) else {}
    return [
        {"key": "tuyen_truyen_total", "label": "Tổng số lượt tuyên truyền", "type": "number", "value": payload.get("tuyen_truyen_total", "")},
        {"key": "tuyen_truyen_forms", "label": "Hình thức tuyên truyền", "type": "textarea", "value": payload.get("tuyen_truyen_forms", "")},
        {"key": "current_tasks", "label": "Các nhiệm vụ hiện hành", "type": "textarea", "value": payload.get("current_tasks", "")},
        {"key": "van_ban_y_kien_count", "label": "Số văn bản tham gia ý kiến", "type": "number", "value": payload.get("van_ban_y_kien_count", "")},
        {"key": "van_ban_chi_dao", "label": "Các văn bản chỉ đạo triển khai thực hiện", "type": "textarea", "value": payload.get("van_ban_chi_dao", "")},
        {"key": "tuyen_truyen_attachment", "label": "Tài liệu minh chứng tuyên truyền", "type": "file", "value": attachments.get("tuyen_truyen_attachment", "")},
        {"key": "van_ban_y_kien_attachment", "label": "Tài liệu minh chứng văn bản tham gia ý kiến", "type": "file", "value": attachments.get("van_ban_y_kien_attachment", "")},
        {"key": "van_ban_chi_dao_attachment", "label": "Tài liệu minh chứng văn bản chỉ đạo", "type": "file", "value": attachments.get("van_ban_chi_dao_attachment", "")},
    ]


def _da06_so_nganh_dvc_rows(rule, payload):
    existing = payload.get("dvc_items", {}) if isinstance(payload.get("dvc_items"), dict) else {}
    rows = []
    for title in (rule or {}).get("dvc_titles", []):
        item_payload = existing.get(title, {}) if isinstance(existing.get(title), dict) else {}
        item_key = secure_filename(remove_accents(title).replace(" ", "_")) or f"dvc_{len(rows) + 1}"
        rows.append(
            {
                "title": title,
                "item_key": item_key,
                "fields": [
                    {"key": "total", "label": "Tổng số hồ sơ", "value": item_payload.get("total", "")},
                    {"key": "online", "label": "Trực tuyến", "value": item_payload.get("online", "")},
                    {"key": "rate", "label": "Tỷ lệ (%)", "value": item_payload.get("rate", "")},
                    {"key": "data_source", "label": "Nguồn dữ liệu kết nối, chia sẻ", "value": item_payload.get("data_source", "")},
                    {"key": "benefit", "label": "Người dân được hưởng lợi", "value": item_payload.get("benefit", "")},
                    {"key": "issues", "label": "Tồn tại", "value": item_payload.get("issues", "")},
                    {"key": "solution", "label": "Giải pháp", "value": item_payload.get("solution", "")},
                ],
            }
        )
    return rows


def _build_da06_task_form(task, user_assign, current_user):
    if not task or not user_assign or not current_user or not _is_da06_month_task(task):
        return None
    payload = _parse_assignment_payload(user_assign)
    profile = _da06_user_profile(current_user)
    form = {
        "kind": profile["kind"],
        "label": profile["label"],
        "narrative_value": payload.get("narrative_report", ""),
        "dvc_rows": [],
        "tct_fields": [],
        "tthcc_attachment": ((payload.get("attachments") or {}) if isinstance(payload.get("attachments"), dict) else {}).get("phu_luc_2_attachment", ""),
        "updated_at": payload.get("updated_at", ""),
    }
    if profile["kind"] == "tct_xa":
        form["tct_fields"] = _da06_tct_sections(payload)
    elif profile["kind"] == "tthcc":
        form["tthcc_note"] = payload.get("tthcc_note", "")
    else:
        rule = profile.get("rule")
        form["dvc_rows"] = _da06_so_nganh_dvc_rows(rule, payload)
    return form


def _has_da06_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_da06_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_da06_value(item) for item in value)
    return True


def _build_da06_management_view(assigns):
    group_map = {}
    for assignment, user in assigns or []:
        if not user:
            continue

        profile = _da06_user_profile(user)
        unit_identity = _task_unit_identity(user)
        unit_key = unit_identity["unit_key"] or unit_identity["unit_name"].lower()
        group_key = profile["kind"]
        group = group_map.setdefault(
            group_key,
            {
                "key": group_key,
                "label": profile["label"],
                "units": {},
                "total_units": 0,
                "reported_units": 0,
            },
        )

        payload = _parse_assignment_payload(assignment)
        attachments = payload.get("attachments", {}) if isinstance(payload.get("attachments"), dict) else {}
        unit = group["units"].setdefault(
            unit_key,
            {
                "unit_name": unit_identity["unit_name"],
                "status": "Chưa tiếp nhận",
                "has_report": False,
                "updated_at": None,
                "summary_lines": [],
            },
        )

        normalized_status = _normalize_status(getattr(assignment, "status", ""))
        if normalized_status == COMPLETED_STATUS:
            unit["status"] = COMPLETED_STATUS
        elif normalized_status == IN_PROGRESS_STATUS and unit["status"] != COMPLETED_STATUS:
            unit["status"] = IN_PROGRESS_STATUS

        report_lines = []
        has_report = False
        if profile["kind"] == "tct_xa":
            has_report = any(
                _has_da06_value(payload.get(key))
                for key in [
                    "tuyen_truyen_total",
                    "tuyen_truyen_forms",
                    "current_tasks",
                    "van_ban_y_kien_count",
                    "van_ban_chi_dao",
                ]
            ) or bool(attachments)
            attachment_count = sum(1 for key in ["tuyen_truyen_attachment", "van_ban_y_kien_attachment", "van_ban_chi_dao_attachment"] if attachments.get(key))
            report_lines = [
                f"Tuyên truyền: {payload.get('tuyen_truyen_total') or '0'} lượt",
                f"Văn bản tham gia ý kiến: {payload.get('van_ban_y_kien_count') or '0'}",
                f"Minh chứng: {attachment_count}/3 tệp",
            ]
        elif profile["kind"] == "tthcc":
            note_ready = _has_da06_value(payload.get("tthcc_note"))
            appendix_ready = bool(attachments.get("phu_luc_2_attachment"))
            has_report = note_ready or appendix_ready
            report_lines = [
                f"Ghi chú tổng hợp: {'Đã cập nhật' if note_ready else 'Chưa cập nhật'}",
                f"Phụ lục 2: {'Đã tải lên' if appendix_ready else 'Chưa tải lên'}",
            ]
        else:
            dvc_items = payload.get("dvc_items", {}) if isinstance(payload.get("dvc_items"), dict) else {}
            dvc_total = len((profile.get("rule") or {}).get("dvc_titles", []))
            dvc_ready = 0
            for item in dvc_items.values():
                if isinstance(item, dict) and any(_has_da06_value(value) for value in item.values()):
                    dvc_ready += 1
            narrative_ready = _has_da06_value(payload.get("narrative_report"))
            has_report = narrative_ready or dvc_ready > 0
            report_lines = [
                f"Báo cáo lời: {'Đã cập nhật' if narrative_ready else 'Chưa cập nhật'}",
                f"DVC: {dvc_ready}/{dvc_total}" if dvc_total else "DVC: Không áp dụng",
            ]

        if has_report:
            unit["has_report"] = True
        updated_at = getattr(assignment, "updated_at", None)
        if updated_at and (unit["updated_at"] is None or updated_at > unit["updated_at"]):
            unit["updated_at"] = updated_at
            unit["summary_lines"] = report_lines

    groups = []
    for group in group_map.values():
        units = sorted(group["units"].values(), key=lambda item: item["unit_name"].lower())
        group["units"] = units
        group["total_units"] = len(units)
        group["reported_units"] = sum(1 for item in units if item["has_report"])
        groups.append(group)

    groups.sort(key=lambda item: item["label"].lower())
    return groups


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

    child_tasks = Task.query.options(joinedload(Task.assignments)).filter_by(parent_task_id=task.id).all()
    for child_task in child_tasks:
        _purge_task(child_task)

    file_names = set()
    if task.file_path:
        file_names.add(task.file_path)

    for assignment in _task_assignment_records(task):
        if assignment.result_file:
            file_names.add(assignment.result_file)
    for submission in _query_task_scope(TaskSubmission, task).all():
        attachment_name = (
            str(getattr(submission, "attachment_name", "") or "").strip()
            or str(getattr(submission, "attachment_path", "") or "").strip()
        )
        if attachment_name:
            file_names.add(attachment_name)

    for file_name in file_names:
        file_path = _task_file_path(file_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                current_app.logger.warning(f"Không thể xóa file công việc: {file_path}")

    task_id, task_item_id = _task_scope_identity(task)
    participant_query = TaskParticipant.query.filter(TaskParticipant.task_id == task_id)
    submission_query = TaskSubmission.query.filter(TaskSubmission.task_id == task_id)
    link_query = TaskReportLink.query.filter(TaskReportLink.task_id == task_id)
    if task_item_id:
        participant_query = participant_query.filter(TaskParticipant.task_item_id == task_item_id)
        submission_query = submission_query.filter(TaskSubmission.task_item_id == task_item_id)
        link_query = link_query.filter(TaskReportLink.task_item_id == task_item_id)
    else:
        participant_query = participant_query.filter(TaskParticipant.task_item_id.is_(None))
        submission_query = submission_query.filter(TaskSubmission.task_item_id.is_(None))
        link_query = link_query.filter(TaskReportLink.task_item_id.is_(None))
    submission_query.delete(synchronize_session=False)
    participant_query.delete(synchronize_session=False)
    link_query.delete(synchronize_session=False)
    if getattr(task, "parent_task_id", None):
        TaskItem.query.filter_by(source_task_id=task.id).delete(synchronize_session=False)
    else:
        TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
    TaskComment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
    db.session.delete(task)


def _ensure_task_schema():
    try:
        apply_migrations(current_app)
    except Exception as migration_error:
        current_app.logger.warning(f"TASKS migration safeguard failed: {migration_error}")
    runtime_flags = current_app.extensions.setdefault("pc06_runtime_flags", {})
    if runtime_flags.get("task_runtime_backfill_done"):
        return
    try:
        backfill_result = _backfill_task_runtime_models()
        runtime_flags["task_runtime_backfill_done"] = True
        current_app.logger.info(
            "Task runtime backfill completed: scanned=%s changed=%s",
            backfill_result.get("scanned", 0),
            backfill_result.get("changed", 0),
        )
    except Exception as backfill_error:
        current_app.logger.warning(f"TASKS runtime backfill failed: {backfill_error}")


def _decorate_task(task, current_uid, is_lead):
    assignments = [assignment for assignment, _user in _task_assignment_rows(task, ensure_bridge=False)]
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

        report_at = _assignment_report_snapshot(assignment, comments=comments).get("first_report_at")
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
    is_lead = _can_process_task_module(perms)
    can_view_all_tasks = _can_view_all_tasks(perms)
    is_admin = bool(session.get("is_admin"))
    current_user = db.session.get(User, session["uid"])

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

        try:
            report_schema = _parse_task_report_schema_from_request(request.form)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("tasks_bp.tasks"))
        linked_report_template_ids = _requested_linked_report_template_ids(request.form)

        assignees, error_message = _resolve_assignees(request.form, domain)
        if error_message:
            flash(error_message, "danger")
            return redirect(url_for("tasks_bp.tasks"))
        managers, manager_error_message = _resolve_managers(request.form)
        if manager_error_message:
            flash(manager_error_message, "danger")
            return redirect(url_for("tasks_bp.tasks"))
        viewers, viewer_error_message = _resolve_viewers(request.form)
        if viewer_error_message:
            flash(viewer_error_message, "danger")
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
            report_schema_json=json.dumps(report_schema, ensure_ascii=False) if report_schema else None,
            linked_report_templates_json=json.dumps(linked_report_template_ids, ensure_ascii=False) if linked_report_template_ids else None,
        )
        _store_assignment_scope(
            new_task,
            request.form.get("assign_type", "unit"),
            domain=domain,
            role_ids=_requested_role_ids(request.form),
            user_ids=_requested_user_ids(request.form),
        )
        _store_viewer_scope(
            new_task,
            request.form.get("viewer_scope_mode", "none"),
            role_ids=_requested_viewer_role_ids(request.form),
            user_ids=_requested_viewer_user_ids(request.form),
        )
        _store_manager_scope(
            new_task,
            request.form.get("manager_scope_mode", "none"),
            role_ids=_requested_manager_role_ids(request.form),
            user_ids=_requested_manager_user_ids(request.form),
        )
        db.session.add(new_task)
        db.session.flush()

        _sync_task_assignments(new_task, assignees)
        _sync_task_runtime_models(
            new_task,
            assignees=assignees,
            managers=managers,
            viewers=viewers,
            linked_report_template_ids=linked_report_template_ids,
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
        assignee_ids = {user.id for user in assignees}
        manager_ids = set()
        for user in managers:
            if user.id in assignee_ids:
                continue
            manager_ids.add(user.id)
            push_notif(user.id, "Xử lý công việc", f"Bạn được giao quyền xử lý công việc: {new_task.title}", f"/tasks/{new_task.id}")
        for user in viewers:
            if user.id in assignee_ids or user.id in manager_ids:
                continue
            push_notif(user.id, "Theo dõi công việc", f"Bạn được thêm vào danh sách xem việc: {new_task.title}", f"/tasks/{new_task.id}")

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

    all_candidate_tasks = query.order_by(Task.created_at.desc()).all()
    runtime_bridge_changed = False
    for candidate_task in all_candidate_tasks:
        if _ensure_task_runtime_bridge(candidate_task):
            runtime_bridge_changed = True
    if runtime_bridge_changed:
        db.session.commit()

    if can_view_all_tasks:
        all_tasks = [task for task in all_candidate_tasks if not task.parent_task_id]
    else:
        visible_child_tasks_by_parent = {}
        for parent_task in (task for task in all_candidate_tasks if not task.parent_task_id):
            child_tasks_for_user = _visible_child_tasks_for_user(parent_task.id, session["uid"])
            if child_tasks_for_user:
                visible_child_tasks_by_parent[parent_task.id] = child_tasks_for_user
        child_parent_ids = set(visible_child_tasks_by_parent.keys())
        all_tasks = []
        for task in all_candidate_tasks:
            if task.parent_task_id:
                continue
            is_direct_assignment = _task_user_is_executor(task, session["uid"])
            is_manager = _can_manage_task(task, user=current_user)
            is_viewer = _can_watch_task(task, user=current_user)
            if not is_direct_assignment and task.id not in child_parent_ids and not is_viewer and not is_manager:
                continue
            if not is_direct_assignment and task.id in visible_child_tasks_by_parent:
                child_tasks_for_user = visible_child_tasks_by_parent.get(task.id) or []
                total_children = len(child_tasks_for_user)
                completed_children = 0
                started_children = 0
                for child_task in child_tasks_for_user:
                    child_metrics = _decorate_task(child_task, session["uid"], False)
                    child_status = child_metrics["display_status"]
                    if child_status == COMPLETED_STATUS:
                        completed_children += 1
                        started_children += 1
                    elif child_status != "Chưa tiếp nhận":
                        started_children += 1
                if total_children and completed_children == total_children:
                    task.display_status = COMPLETED_STATUS
                    task.progress_percent = 100
                elif started_children:
                    task.display_status = f"Đang thực hiện ({started_children}/{total_children})"
                    task.progress_percent = round((completed_children / total_children) * 100) if total_children else 0
                else:
                    task.display_status = f"Chưa tiếp nhận (0/{total_children})"
                    task.progress_percent = 0
                task.current_user_status = task.display_status
                task._visible_child_tasks_for_user = child_tasks_for_user
            if is_manager:
                task._manager_observe_task = True
            if is_viewer:
                task._viewer_observe_task = True
            all_tasks.append(task)

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
        is_executor_view = _task_user_is_executor(task, session["uid"])
        if not can_view_all_tasks and getattr(task, "_visible_child_tasks_for_user", None) is not None and not is_executor_view:
            task_metrics = {
                "display_status": getattr(task, "display_status", "Chưa tiếp nhận"),
                "progress_percent": getattr(task, "progress_percent", 0),
                "is_overdue": bool(task.deadline and task.deadline < datetime.now().date() and getattr(task, "display_status", "") != COMPLETED_STATUS),
                "total_assignments": len(_task_assignment_rows(task, ensure_bridge=False)),
                "accepted_assignments": 0,
                "completed_assignments": 0,
                "current_user_status": getattr(task, "current_user_status", None),
                "user_assignment": None,
            }
            setattr(task, "is_overdue", task_metrics["is_overdue"])
            setattr(task, "assignee_count", task_metrics["total_assignments"])
            setattr(task, "accepted_assignments", task_metrics["accepted_assignments"])
            setattr(task, "completed_assignments", task_metrics["completed_assignments"])
        elif not can_view_all_tasks and (getattr(task, "_viewer_observe_task", False) or getattr(task, "_manager_observe_task", False)) and not is_executor_view:
            task_metrics = _decorate_task(task, session["uid"], True)
        else:
            task_metrics = _decorate_task(task, session["uid"], can_view_all_tasks)
        setattr(task, "can_edit", _can_edit_task(task))
        setattr(task, "can_delete", _can_delete_task(task, is_lead=is_lead))
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
        default_task_report_schema=_task_report_schema_seed(),
        report_templates=_task_report_templates(),
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
    parent_task = None
    if task.parent_task_id:
        parent_task = Task.query.filter_by(id=task.parent_task_id).first()
        if parent_task:
            sync_record_categories([parent_task], task_fields, attr_name="category", prefer_stable=True)
            sync_record_categories([parent_task], pro_units, attr_name="domain", prefer_stable=True)
            sync_record_categories([parent_task], task_types, attr_name="task_type", prefer_stable=True)
            sync_record_categories([parent_task], priority_items, attr_name="priority", prefer_stable=True)
            _decorate_task_categories(parent_task, task_fields, pro_units, task_types, priority_items)
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
    is_lead = _can_process_task_module(perms)
    can_view_all_tasks = _can_view_all_tasks(perms)
    can_edit_task = _can_edit_task(task)
    can_delete_task = _can_delete_task(task, is_lead=is_lead)
    current_user = db.session.get(User, session["uid"])
    can_manager_task_view = _can_manage_task(task, user=current_user)
    can_watch_task_view = _can_watch_task(task, user=current_user)
    visible_child_tasks_for_user = (
        _visible_child_tasks_for_user(task.id, session["uid"])
        if not (session.get("is_admin") or can_view_all_tasks or task.author_id == session.get("uid"))
        else []
    )
    if not _can_view_task(task, is_lead=can_view_all_tasks) and not visible_child_tasks_for_user:
        flash("Bạn không có quyền xem công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    if _ensure_task_runtime_bridge(task, include_children=True):
        db.session.commit()

    assigns = _task_assignment_rows(task, ensure_bridge=False)
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

    task_metrics = _decorate_task(task, session["uid"], can_view_all_tasks)
    user_assign = task_metrics["user_assignment"]
    can_manage_task_view = bool(is_lead or can_edit_task or can_manager_task_view)
    can_observe_task_view = bool(can_manage_task_view or can_watch_task_view or can_view_all_tasks)
    if not can_manage_task_view and not can_watch_task_view and not can_view_all_tasks and not user_assign and not visible_child_tasks_for_user:
        flash("Bạn không có quyền xem công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    comments = TaskComment.query.filter_by(task_id=tid).order_by(TaskComment.created_at.desc()).all()
    visible_comments = _filter_comments_for_viewer(task, comments, current_user, can_manage_all=can_observe_task_view)
    assignment_context = _infer_assignment_context(task)
    manager_context = _infer_manager_context(task)
    viewer_context = _infer_viewer_context(task)
    manager_role_ids = manager_context.get("role_ids") or []
    viewer_role_ids = viewer_context.get("role_ids") or []
    manager_user_ids = manager_context.get("user_ids") or []
    viewer_user_ids = viewer_context.get("user_ids") or []
    scope_role_ids = sorted({int(role_id) for role_id in (manager_role_ids + viewer_role_ids) if str(role_id).isdigit()})
    scope_user_ids = sorted({int(user_id) for user_id in (manager_user_ids + viewer_user_ids) if str(user_id).isdigit()})
    scope_role_lookup = {
        role.id: role.name
        for role in (AppRole.query.filter(AppRole.id.in_(scope_role_ids)).all() if scope_role_ids else [])
    }
    scope_user_lookup = {}
    if scope_user_ids:
        scope_users = User.query.filter(User.id.in_(scope_user_ids)).all()
        sync_record_categories(scope_users, unit_options, attr_name="unit_area", prefer_stable=True)
        apply_reference_display(
            scope_users,
            "unit_area",
            _task_assignment_unit_options(),
            display_attr="unit_area_display",
            fallback_label="Chưa có đơn vị",
        )
        scope_user_lookup = {
            user.id: f"{user.fullname}{f' - {user.unit_area_display}' if getattr(user, 'unit_area_display', None) else ''}"
            for user in scope_users
        }
    manager_scope_summary = _build_scope_summary(
        manager_context,
        role_lookup=scope_role_lookup,
        user_lookup=scope_user_lookup,
        none_label="Chỉ người giao việc hoặc quản trị xử lý",
    )
    viewer_scope_summary = _build_scope_summary(
        viewer_context,
        role_lookup=scope_role_lookup,
        user_lookup=scope_user_lookup,
        none_label="Chỉ người giao việc và người thực hiện xem",
    )
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
    da06_management_view = []
    task_report_schema = _load_task_report_schema(task)
    linked_report_templates = _build_linked_report_template_views(
        task,
        can_manage_report_admin=_can_manage_report_links(),
        can_open_report_workspace=_can_open_report_workspace(),
    )
    child_tasks = []
    task_has_child_tasks = False
    child_task_stats = {"total": 0, "completed": 0, "in_progress": 0}
    child_task_reporting_matrix = {"task_rows": [], "unit_rows": []}
    assignment_unit_cards = _build_assignment_unit_cards(assigns)
    assignment_unit_progress = {
        "completed_units": sum(1 for card in assignment_unit_cards if card.get("status") == COMPLETED_STATUS),
        "total_units": len(assignment_unit_cards),
    }
    if can_observe_task_view:
        child_tasks = Task.query.options(joinedload(Task.assignments)).filter_by(parent_task_id=task.id).order_by(Task.created_at.asc()).all()
    elif visible_child_tasks_for_user:
        child_tasks = visible_child_tasks_for_user

    if child_tasks:
        child_bridge_changed = False
        for child_task in child_tasks:
            if _ensure_task_runtime_bridge(child_task):
                child_bridge_changed = True
        if child_bridge_changed:
            db.session.commit()
        task_has_child_tasks = True
        sync_record_categories(child_tasks, task_fields, attr_name="category", prefer_stable=True)
        sync_record_categories(child_tasks, pro_units, attr_name="domain", prefer_stable=True)
        sync_record_categories(child_tasks, task_types, attr_name="task_type", prefer_stable=True)
        sync_record_categories(child_tasks, priority_items, attr_name="priority", prefer_stable=True)
        for child_task in child_tasks:
            child_metrics = _decorate_task(child_task, session["uid"], can_observe_task_view)
            _decorate_task_categories(child_task, task_fields, pro_units, task_types, priority_items)
            setattr(child_task, "can_edit", _can_edit_task(child_task))
            setattr(child_task, "can_delete", _can_delete_task(child_task, is_lead=is_lead))
            setattr(child_task, "current_user_status", child_metrics["current_user_status"])
            child_viewer_assign = _task_assignment_for_user(child_task, session["uid"], create_from_executor=True)
            child_schema = _load_task_report_schema(child_task)
            child_meta = _task_report_meta(child_schema)
            child_unit_summary = _build_child_task_unit_summary(child_task)
            setattr(child_task, "report_kind", _task_simple_child_report_kind(child_task) or "narrative")
            setattr(child_task, "report_kind_label", "Báo cáo số" if getattr(child_task, "report_kind", "") == "number" else "Báo cáo lời")
            setattr(child_task, "attachment_required", bool(child_meta.get("attachment_required")))
            setattr(child_task, "reported_assignments", sum(1 for assignment, _user in _task_assignment_rows(child_task, ensure_bridge=False) if _assignment_has_report_submission(assignment)))
            setattr(child_task, "reported_units", child_unit_summary.get("reported_units", 0))
            setattr(child_task, "total_units", child_unit_summary.get("total_units", 0))
            setattr(child_task, "number_total", child_unit_summary.get("numeric_total"))
            setattr(child_task, "viewer_assignment", child_viewer_assign)
            setattr(child_task, "report_form", _build_structured_task_report_form(child_task, child_viewer_assign, current_user) if child_viewer_assign and child_schema else None)
            setattr(child_task, "action_label", "Cập nhật" if child_viewer_assign and _assignment_has_report_submission(child_viewer_assign) else "Thực hiện")
            child_task_stats["total"] += 1
            if child_metrics["display_status"] == COMPLETED_STATUS:
                child_task_stats["completed"] += 1
            elif child_metrics["display_status"] != "Chưa tiếp nhận":
                child_task_stats["in_progress"] += 1
        child_task_reporting_matrix = _build_child_task_reporting_matrix(child_tasks)
    if can_observe_task_view:
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
    report_context = _build_assignment_report_context(user_assign, visible_comments, task=task)
    limited_assignment_view = bool(user_assign and not can_manage_task_view)
    structured_task_report_form = _build_structured_task_report_form(task, user_assign, current_user)
    da06_task_form = _build_da06_task_form(task, user_assign, current_user)
    if _is_da06_month_task(task) and can_observe_task_view:
        da06_management_view = _build_da06_management_view(assigns)

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
        report_templates=_task_report_templates(),
        assignment_context=assignment_context,
        manager_context=manager_context,
        manager_scope_summary=manager_scope_summary,
        viewer_context=viewer_context,
        viewer_scope_summary=viewer_scope_summary,
        now_dt=datetime.now(),
        is_lead=is_lead,
        can_edit_task=can_edit_task,
        can_delete_task=can_delete_task,
        user_assign=user_assign,
        progress_percent=task_metrics["progress_percent"],
        unit_report_rows=unit_report_rows,
        unit_report_stats=unit_report_stats,
        unit_report_cards=unit_report_cards,
        unit_report_groups=unit_report_groups,
        assignment_role_groups=assignment_role_groups,
        assignment_unit_progress=assignment_unit_progress,
        can_manage_task_view=can_manage_task_view,
        can_observe_task_view=can_observe_task_view,
        limited_assignment_view=limited_assignment_view,
        report_context=report_context,
        parent_task=parent_task,
        child_tasks=child_tasks,
        child_task_stats=child_task_stats,
        child_task_reporting_matrix=child_task_reporting_matrix,
        task_has_child_tasks=task_has_child_tasks,
        task_report_schema=task_report_schema,
        task_report_schema_seed=_task_report_schema_seed(task),
        linked_report_templates=linked_report_templates,
        linked_report_template_ids=_load_linked_report_template_ids(task),
        structured_task_report_form=structured_task_report_form,
        da06_task_form=da06_task_form,
        da06_management_view=da06_management_view,
    )


@tasks_bp.route("/tasks/<int:tid>/da06-save", methods=["POST"])
def save_da06_task_report(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    if _ensure_task_runtime_bridge(task):
        db.session.commit()
    if not _is_da06_month_task(task):
        flash("Công việc này không dùng biểu mẫu ĐA06 tháng.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    assign = _task_assignment_for_user(task, session["uid"], create_from_executor=True)
    if not assign:
        flash("Bạn không có quyền cập nhật biểu mẫu của công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    current_user = db.session.get(User, session["uid"])
    profile = _da06_user_profile(current_user)
    payload = _parse_assignment_payload(assign)
    attachments = payload.get("attachments", {}) if isinstance(payload.get("attachments"), dict) else {}

    if profile["kind"] == "tct_xa":
        payload["tuyen_truyen_total"] = (request.form.get("tuyen_truyen_total") or "").strip()
        payload["tuyen_truyen_forms"] = (request.form.get("tuyen_truyen_forms") or "").strip()
        payload["current_tasks"] = (request.form.get("current_tasks") or "").strip()
        payload["van_ban_y_kien_count"] = (request.form.get("van_ban_y_kien_count") or "").strip()
        payload["van_ban_chi_dao"] = (request.form.get("van_ban_chi_dao") or "").strip()
        for key, label in (
            ("tuyen_truyen_attachment", "tuyen_truyen"),
            ("van_ban_y_kien_attachment", "van_ban_y_kien"),
            ("van_ban_chi_dao_attachment", "van_ban_chi_dao"),
        ):
            saved_name = _save_task_attachment(request.files.get(key), tid, session["uid"], label)
            if saved_name:
                attachments[key] = saved_name
    elif profile["kind"] == "tthcc":
        payload["tthcc_note"] = (request.form.get("tthcc_note") or "").strip()
        saved_name = _save_task_attachment(request.files.get("phu_luc_2_attachment"), tid, session["uid"], "phu_luc_2")
        if saved_name:
            attachments["phu_luc_2_attachment"] = saved_name
    else:
        payload["narrative_report"] = (request.form.get("narrative_report") or "").strip()
        dvc_items = {}
        for rule_title in (profile.get("rule") or {}).get("dvc_titles", []):
            item_key = secure_filename(remove_accents(rule_title).replace(" ", "_")) or f"dvc_{len(dvc_items)+1}"
            dvc_items[rule_title] = {
                "total": (request.form.get(f"{item_key}_total") or "").strip(),
                "online": (request.form.get(f"{item_key}_online") or "").strip(),
                "rate": (request.form.get(f"{item_key}_rate") or "").strip(),
                "data_source": (request.form.get(f"{item_key}_data_source") or "").strip(),
                "benefit": (request.form.get(f"{item_key}_benefit") or "").strip(),
                "issues": (request.form.get(f"{item_key}_issues") or "").strip(),
                "solution": (request.form.get(f"{item_key}_solution") or "").strip(),
            }
        payload["dvc_items"] = dvc_items

    payload["attachments"] = attachments
    payload["updated_at"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    assign.report_payload_json = json.dumps(payload, ensure_ascii=False)
    if _normalize_status(assign.status) in PENDING_STATUSES:
        assign.status = IN_PROGRESS_STATUS
    _upsert_task_submission_from_assignment(task, assign, payload)
    db.session.commit()
    flash("Đã lưu biểu mẫu ĐA06 tháng.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))


@tasks_bp.route("/tasks/<int:tid>/da06-attachment/<string:attachment_key>")
def download_da06_task_attachment(tid, attachment_key):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    if _ensure_task_runtime_bridge(task):
        db.session.commit()

    perms = _current_perms()
    is_lead = _can_process_task_module(perms)
    can_view_all_tasks = _can_view_all_tasks(perms)
    can_manage_task_view = bool(is_lead or _can_edit_task(task))
    can_watch_task_view = _can_watch_task(task)
    if not _can_view_task(task, is_lead=can_view_all_tasks):
        flash("Báº¡n khÃ´ng cÃ³ quyá»n táº£i minh chá»©ng cá»§a cÃ´ng viá»‡c nÃ y.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    assign = _task_assignment_for_user(task, session["uid"], create_from_executor=True)
    if not can_manage_task_view and not can_watch_task_view and not can_view_all_tasks and not assign:
        flash("Báº¡n khÃ´ng cÃ³ quyá»n táº£i minh chá»©ng nÃ y.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if (can_manage_task_view or can_watch_task_view or can_view_all_tasks) and not assign:
        assign = _task_latest_reporting_assignment(task)

    payload = _parse_assignment_payload(assign)
    attachments = payload.get("attachments", {}) if isinstance(payload.get("attachments"), dict) else {}
    file_name = (attachments.get(attachment_key) or "").strip()
    if not file_name:
        flash("KhÃ´ng tÃ¬m tháº¥y tá»‡p minh chá»©ng cáº§n táº£i.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    file_path = _task_file_path(file_name)
    if not os.path.exists(file_path):
        flash("Tá»‡p minh chá»©ng khÃ´ng cÃ²n tá»“n táº¡i trÃªn há»‡ thá»‘ng.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    return send_file(file_path, as_attachment=True, download_name=file_name)


@tasks_bp.route("/tasks/<int:tid>/assignees/<int:user_id>/report-download")
def download_task_report_file(tid, user_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    if _ensure_task_runtime_bridge(task):
        db.session.commit()

    perms = _current_perms()
    is_lead = _can_process_task_module(perms)
    can_view_all_tasks = _can_view_all_tasks(perms)
    can_manage_task_view = bool(is_lead or _can_edit_task(task))
    can_watch_task_view = _can_watch_task(task)
    if not _can_view_task(task, is_lead=can_view_all_tasks):
        flash("Bạn không có quyền tải tệp của công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    if not can_manage_task_view and not can_watch_task_view and not can_view_all_tasks and session.get("uid") != user_id:
        flash("Bạn chỉ có thể tải tệp báo cáo của mình.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    assign = _task_assignment_for_user(task, user_id)
    file_name = _assignment_report_snapshot(assign).get("attachment_name") if assign else ""
    if not assign or not file_name:
        flash("Không tìm thấy tệp báo cáo cần tải.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    file_path = _task_file_path(file_name)
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
    download_name = _task_report_download_name(task, unit_name, file_name)
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
    is_lead = _can_process_task_module(perms)
    if not (is_lead or _can_edit_task(task)):
        flash("Bạn không có quyền xuất thống kê báo cáo của công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    assigns = _task_assignment_rows(task, ensure_bridge=True)
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

    if "report_schema_enabled" in request.form or "report_schema_json" in request.form:
        try:
            report_schema = _parse_task_report_schema_from_request(request.form)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
    else:
        report_schema = _load_task_report_schema(task)

    requested_assign_type = request.form.get("assign_type", _infer_assignment_context(task).get("mode") or "unit")
    requested_role_ids = _requested_role_ids(request.form)
    requested_user_ids = _requested_user_ids(request.form)
    requested_manager_mode = request.form.get("manager_scope_mode", _infer_manager_context(task).get("mode") or "none")
    requested_manager_role_ids = _requested_manager_role_ids(request.form)
    requested_manager_user_ids = _requested_manager_user_ids(request.form)
    requested_viewer_mode = request.form.get("viewer_scope_mode", _infer_viewer_context(task).get("mode") or "none")
    requested_viewer_role_ids = _requested_viewer_role_ids(request.form)
    requested_viewer_user_ids = _requested_viewer_user_ids(request.form)
    linked_report_template_ids = _requested_linked_report_template_ids(request.form)
    assignees = [user for _assignment, user in _task_assignment_rows(task, ensure_bridge=True)]
    refreshed_assignee_count = None
    new_assignees_to_notify = []
    old_manager_scope = _load_manager_scope(task)
    old_managers = []
    if old_manager_scope.get("mode") == "role":
        for role_id in old_manager_scope.get("role_ids") or []:
            old_managers.extend(_resolve_role_assignees(role_id))
        old_managers = _dedupe_users(old_managers)
    elif old_manager_scope.get("mode") == "user" and old_manager_scope.get("user_ids"):
        old_managers = (
            User.query.filter(User.id.in_(old_manager_scope.get("user_ids") or []), User.is_active.is_(True))
            .order_by(User.fullname.asc())
            .all()
        )
    managers, manager_error_message = _resolve_managers(request.form)
    if manager_error_message:
        flash(manager_error_message, "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    old_viewer_scope = _load_viewer_scope(task)
    old_viewers = []
    if old_viewer_scope.get("mode") == "role":
        for role_id in old_viewer_scope.get("role_ids") or []:
            old_viewers.extend(_resolve_role_assignees(role_id))
        old_viewers = _dedupe_users(old_viewers)
    elif old_viewer_scope.get("mode") == "user" and old_viewer_scope.get("user_ids"):
        old_viewers = (
            User.query.filter(User.id.in_(old_viewer_scope.get("user_ids") or []), User.is_active.is_(True))
            .order_by(User.fullname.asc())
            .all()
        )
    viewers, viewer_error_message = _resolve_viewers(request.form)
    if viewer_error_message:
        flash(viewer_error_message, "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
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
    task.report_schema_json = json.dumps(report_schema, ensure_ascii=False) if report_schema else None
    task.linked_report_templates_json = (
        json.dumps(linked_report_template_ids, ensure_ascii=False) if linked_report_template_ids else None
    )
    setattr(task, "_task_report_schema_cache", report_schema)
    _store_manager_scope(
        task,
        requested_manager_mode,
        role_ids=requested_manager_role_ids,
        user_ids=requested_manager_user_ids,
    )
    _store_viewer_scope(
        task,
        requested_viewer_mode,
        role_ids=requested_viewer_role_ids,
        user_ids=requested_viewer_user_ids,
    )
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

    _sync_task_runtime_models(
        task,
        assignees=assignees,
        managers=managers,
        viewers=viewers,
        linked_report_template_ids=linked_report_template_ids,
    )
    db.session.commit()

    for user in new_assignees_to_notify:
        push_notif(user.id, "Cập nhật công việc", f"Bạn vừa được bổ sung vào công việc: {task.title}", f"/tasks/{task.id}")
    old_manager_ids = {user.id for user in (old_managers or [])}
    old_viewer_ids = {user.id for user in (old_viewers or [])}
    assignee_ids = {assignment.user_id for assignment, _user in _task_assignment_rows(task, ensure_bridge=False) if assignment.user_id}
    manager_ids = {user.id for user in managers}
    for user in managers:
        if user.id in old_manager_ids or user.id in assignee_ids:
            continue
        push_notif(user.id, "Xử lý công việc", f"Bạn được giao quyền xử lý công việc: {task.title}", f"/tasks/{task.id}")
    for user in viewers:
        if user.id in old_viewer_ids or user.id in assignee_ids or user.id in manager_ids:
            continue
        push_notif(user.id, "Theo dõi công việc", f"Bạn được thêm vào danh sách xem việc: {task.title}", f"/tasks/{task.id}")

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


@tasks_bp.route("/tasks/<int:tid>/children/create", methods=["POST"])
def create_child_task(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    parent_task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not parent_task:
        return "Not Found", 404

    if not _can_edit_task(parent_task):
        flash("Bạn không có quyền tạo task con cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    title = (request.form.get("title") or "").strip()
    bulk_titles = _parse_bulk_child_task_titles(request.form.get("bulk_titles") or request.form.get("bulk_items"))
    common_note = (request.form.get("description") or request.form.get("content") or "").strip()
    outline_file = request.files.get("outline_file")
    if outline_file and outline_file.filename:
        try:
            bulk_titles.extend(_parse_outline_upload_titles(outline_file))
        except ValueError as outline_error:
            flash(str(outline_error), "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        bulk_titles = _parse_bulk_child_task_titles("\n".join(bulk_titles))

    domain = (request.form.get("child_domain") or parent_task.domain or "").strip()
    assign_type = request.form.get("assign_type", "role")
    if assign_type not in {"unit", "role", "user"}:
        assign_type = "role"
    child_report_kind = str(request.form.get("child_report_kind") or "narrative").strip().lower()
    if child_report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
        child_report_kind = "narrative"
    child_attachment_required = _report_checkbox_value(request.form.get("child_attachment_required"))
    child_report_schema = _build_simple_child_task_schema(child_report_kind, child_attachment_required)

    if title and not bulk_titles:
        bulk_titles = [title]

    if not bulk_titles:
        flash("Cần nhập ít nhất một đầu mục để tạo task con.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    assignees, error_message = _resolve_assignees(request.form, domain)
    if error_message:
        flash(error_message, "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    attachment = request.files.get("task_file") or request.files.get("file")
    attachment_name = ""
    if attachment and attachment.filename:
        attachment_name = secure_filename(attachment.filename)
        attachment.save(_task_file_path(attachment_name))

    created_tasks = []
    requested_role_ids = _requested_role_ids(request.form)
    requested_user_ids = _requested_user_ids(request.form)
    for item_title in bulk_titles:
        item_content = common_note or item_title
        child_task = Task(
            category=parent_task.category,
            domain=domain,
            title=item_title,
            content=item_content,
            deadline=parent_task.deadline,
            file_path=attachment_name,
            author_id=session["uid"],
            author_name=session.get("fullname", "Quản trị"),
            priority=parent_task.priority,
            task_type=parent_task.task_type,
            initial_status="Chưa tiếp nhận",
            parent_task_id=parent_task.id,
            report_schema_json=json.dumps(child_report_schema, ensure_ascii=False) if child_report_schema else None,
        )
        _store_assignment_scope(
            child_task,
            assign_type,
            domain=domain,
            role_ids=requested_role_ids,
            user_ids=requested_user_ids,
        )
        db.session.add(child_task)
        db.session.flush()
        _sync_task_assignments(child_task, assignees)
        _sync_task_runtime_models(child_task, assignees=assignees)
        created_tasks.append(child_task)
    db.session.commit()

    for user in assignees:
        push_notif(
            user.id,
            "Task con mới",
            f"Bạn vừa được giao {len(created_tasks)} task con trong công việc: {parent_task.title}",
            f"/tasks/{parent_task.id}",
        )

    log_action(
        session["uid"],
        session.get("fullname", "Quản trị"),
        "Tạo hàng loạt task con",
        "Công việc",
        f"parent={parent_task.id} | so_luong={len(created_tasks)} | kieu={child_report_kind} | tep={int(child_attachment_required)}",
    )
    flash(f"Đã tạo và giao {len(created_tasks)} task con.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))


@tasks_bp.route("/tasks/<int:tid>/children/outline-preview", methods=["POST"])
def preview_child_task_outline(tid):
    if not session.get("uid"):
        return jsonify({"ok": False, "message": "Bạn cần đăng nhập lại."}), 401

    _ensure_task_schema()

    parent_task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not parent_task:
        return jsonify({"ok": False, "message": "Không tìm thấy công việc cha."}), 404

    if not _can_edit_task(parent_task):
        return jsonify({"ok": False, "message": "Bạn không có quyền đọc đề cương cho công việc này."}), 403

    outline_file = request.files.get("outline_file")
    if not outline_file or not getattr(outline_file, "filename", ""):
        return jsonify({"ok": False, "message": "Hãy chọn file đề cương trước."}), 400

    try:
        titles = _parse_outline_upload_titles(outline_file)
    except ValueError as outline_error:
        return jsonify({"ok": False, "message": str(outline_error)}), 400

    return jsonify({
        "ok": True,
        "count": len(titles),
        "titles": titles,
    })


@tasks_bp.route("/tasks/<int:tid>/delete", methods=["POST"])
def delete_task(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    perms = _current_perms()
    is_lead = _can_process_task_module(perms)
    if not _can_delete_task(task, is_lead=is_lead):
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
    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    if _ensure_task_runtime_bridge(task):
        db.session.commit()
    assign = _task_assignment_for_user(task, session["uid"], create_from_executor=True)

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

    task = Task.query.options(joinedload(Task.assignments)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    if _ensure_task_runtime_bridge(task):
        db.session.commit()

    mark_completed = request.form.get("mark_completed")

    assign = _task_assignment_for_user(task, session["uid"], create_from_executor=True)
    if not assign:
        flash("Bạn không được giao công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    report_schema = _load_task_report_schema(task)
    if report_schema:
        current_user = db.session.get(User, session["uid"])
        report_file = request.files.get("report_file")
        attachment_name = (getattr(assign, "result_file", "") or "").strip()
        if report_file and report_file.filename:
            attachment_name = secure_filename(report_file.filename)
            report_file.save(_task_file_path(attachment_name))

        values = {}
        missing_labels = []
        invalid_number_labels = []
        for field in report_schema.get("fields", []):
            if not _task_report_item_visible_for_user(field, current_user):
                continue
            form_key = f"report_field_{field.get('key')}"
            raw_value = (request.form.get(form_key) or "").strip()
            if field.get("type") == "number" and raw_value:
                try:
                    raw_value = _format_report_number(_parse_report_number(raw_value))
                except ValueError:
                    invalid_number_labels.append(field.get("label") or "Chỉ tiêu số liệu")
            values[field.get("key")] = raw_value
            if field.get("required") and not raw_value:
                missing_labels.append(field.get("label"))

        narrative_cfg = report_schema.get("narrative") or {}
        attachment_cfg = report_schema.get("attachment") or {}
        narrative_visible = bool(narrative_cfg.get("enabled")) and _task_report_item_visible_for_user(narrative_cfg, current_user)
        attachment_visible = bool(attachment_cfg.get("enabled")) and _task_report_item_visible_for_user(attachment_cfg, current_user)
        narrative_value = (request.form.get("report_narrative") or "").strip() if narrative_visible else ""
        if narrative_visible and narrative_cfg.get("required") and not narrative_value:
            missing_labels.append(narrative_cfg.get("label") or "Báo cáo lời tổng hợp")

        if attachment_visible and attachment_cfg.get("required") and not attachment_name:
            missing_labels.append(attachment_cfg.get("label") or "Tệp minh chứng")

        if missing_labels:
            flash("Cần hoàn thiện các mục bắt buộc: " + ", ".join(missing_labels) + ".", "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        if invalid_number_labels:
            flash("Các mục sau chỉ cho phép nhập số: " + ", ".join(invalid_number_labels) + ".", "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))

        payload = {
            "mode": "structured_task_report",
            "schema_version": report_schema.get("version", 1),
            "narrative": narrative_value,
            "values": values,
            "attachment_name": attachment_name,
            "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        assign.report_payload_json = json.dumps(payload, ensure_ascii=False)
        if attachment_name:
            assign.result_file = attachment_name

        report_message = f"{REPORT_PREFIX} {_build_structured_task_report_comment(report_schema, payload)}"
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

        if task.parent_task_id and _task_is_simple_child_report(task):
            assign.status = COMPLETED_STATUS
        elif mark_completed == "1":
            assign.status = COMPLETED_STATUS
        elif _normalize_status(assign.status) == "Chưa tiếp nhận":
            assign.status = IN_PROGRESS_STATUS

        _upsert_task_submission_from_assignment(task, assign, payload)
        db.session.commit()
        flash("Đã gửi báo cáo công việc.", "success")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    report_content = (request.form.get("report_content") or "").strip()
    report_file = request.files.get("report_file")
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

    if task.parent_task_id:
        assign.status = COMPLETED_STATUS
    elif mark_completed == "1":
        assign.status = COMPLETED_STATUS
    elif _normalize_status(assign.status) == "Chưa tiếp nhận":
        assign.status = IN_PROGRESS_STATUS

    if attachment_name:
        assign.result_file = attachment_name

    legacy_payload = {
        "mode": "legacy_task_report",
        "narrative": report_content,
        "attachment_name": attachment_name,
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    _upsert_task_submission_from_assignment(task, assign, legacy_payload)
    db.session.commit()
    flash("Đã gửi báo cáo công việc.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))
