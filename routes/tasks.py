# -*- coding: utf-8 -*-
import html
import io
import json
import os
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, g, has_request_context, jsonify, redirect, request, session, url_for, send_file
from sqlalchemy.orm import joinedload
from werkzeug.datastructures import MultiDict
from werkzeug.utils import secure_filename
try:
    from openpyxl import Workbook, load_workbook
except ImportError:
    Workbook = None
    load_workbook = None
try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None
try:
    import fitz as PdfDocument  # pymupdf
    if not hasattr(PdfDocument, "open"):
        PdfDocument = None
except ImportError:
    PdfDocument = None

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
    Task,
    TaskImportDraft,
    TaskAssignment,
    TaskComment,
    TaskItem,
    TaskParticipant,
    TaskFormField,
    TaskSubmission,
    TaskSubmissionFile,
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
from routes.email_service import send_task_assignment_emails

logger = __import__('logging').getLogger(__name__)

from task_workspace import (
    build_task_detail_context,
    build_task_workspace_attrs,
    summarize_task_assignments,
    task_assignment_submit_scope,
    task_assignment_display_status,
    task_deadline_display,
    task_workspace_tone,
)
from report_cycles import (
    KIND_LABELS as REPORT_KIND_LABELS,
    PERIOD_LABELS as REPORT_PERIOD_LABELS,
    WEEKDAY_LABELS as REPORT_WEEKDAY_LABELS,
    config_to_json as report_config_to_json,
    current_cycle as report_current_cycle,
    cycle_summary_text as report_cycle_summary_text,
    deadline_for as report_deadline_for,
    normalize_config as report_normalize_config,
    parse_config as report_parse_config,
    task_config as report_task_config,
)
from task_import_ai import (
    analyze_task_import_config,
    apply_ai_analysis_to_config,
)
from task_policies import (
    build_scope_summary,
    can_delete_task,
    can_manage_task,
    can_view_task,
    can_watch_task,
    load_assignment_scope,
    load_manager_scope,
    load_viewer_scope,
    scope_preview_names,
    store_assignment_scope,
    store_manager_scope,
    store_viewer_scope,
)
from task_read_models import (
    build_file_task_rows,
    build_form_task_rows,
    build_outline_group_rows,
    form_field_options,
    normalize_task_form_field_type,
    outline_group_identity,
    task_form_field_views,
    task_form_submission_payload,
    task_form_value_is_empty,
)
from task_page_builders import (
    build_task_detail_page_context,
    build_task_list_page_context,
    prepare_task_workspace_record,
    task_visible_for_user,
)
from task_blueprints import (
    workflow_blueprint_example_catalog,
    normalize_task_workflow_blueprint,
    workflow_blueprint_preview_data,
    workflow_blueprint_form_field_defs,
    workflow_blueprint_item_configs,
    workflow_blueprint_report_schema,
    workflow_blueprint_summary_text,
    workflow_blueprint_task_mode,
)
from google_forms import (
    GOOGLE_FORMS_MANAGE_SCOPES,
    build_google_forms_service,
    builder_schema_to_task_form_fields,
    create_google_form,
    extract_google_form_id,
    fetch_google_form_definition,
    fetch_google_form_responses,
    load_google_form_into_builder,
    normalize_google_form_builder_schema,
    parse_google_form_definition,
    parse_google_form_responses,
    publish_google_form,
    update_google_form,
)

tasks_bp = Blueprint("tasks_bp", __name__)

PENDING_STATUSES = {"Chưa tiếp nhận", "Chưa bắt đầu", None, ""}
IN_PROGRESS_STATUS = "Đang thực hiện"
COMPLETED_STATUS = "Hoàn thành"
REPORT_PREFIX = "[BÁO CÁO]"
REPORT_ATTACHMENT_RE = re.compile(r"\s*\(Đính kèm:\s*([^)]+)\)\s*$")
TASK_REPORT_ALLOWED_FIELD_TYPES = {"number", "text", "textarea"}
TASK_REPORT_ALLOWED_TARGET_TYPES = {"all", "unit", "role", "user"}
TASK_OUTLINE_ALLOWED_EXTENSIONS = {".docx", ".txt", ".pdf"}
TASK_MODE_ALLOWED = {"OUTLINE", "FILE", "FORM"}
TASK_MODE_DEFAULT = "FILE"
TASK_MODE_LABELS = {
    "OUTLINE": "Theo đề cương",
    "FILE": "Nộp file",
    "FORM": "Biểu mẫu",
}
TASK_IMPORT_ASSIGN_TYPE_LABELS = {
    "unit": "Đơn vị",
    "role": "Vai trò",
    "user": "Cá nhân",
}
TASK_IMPORT_TARGET_TYPE_LABELS = {
    "all": "Tất cả người nhận",
    "unit": "Theo đơn vị",
    "role": "Theo vai trò",
    "user": "Theo cá nhân",
}
TASK_IMPORT_REPORT_KIND_LABELS = {
    "narrative": "Báo cáo lời",
    "number": "Báo cáo số",
}
TASK_IMPORT_FIELD_TYPE_LABELS = {
    "text": "Văn bản",
    "number": "Số",
    "textarea": "Đoạn văn",
    "radio": "Một lựa chọn",
    "checkbox": "Nhiều lựa chọn",
    "table": "Bảng",
}
TASK_MODE_DESCRIPTIONS = {
    "OUTLINE": "Tạo đợt giao việc theo đề cương, chia thành các đầu mục và giao từng mục cho đơn vị hoặc cá nhân.",
    "FILE": "Giao việc trực tiếp và yêu cầu nộp nội dung, file minh chứng hoặc văn bản tổng hợp.",
    "FORM": "Thu thập dữ liệu theo biểu mẫu động, phù hợp để tổng hợp số liệu và xuất báo cáo.",
}
TASK_ASSIGNMENT_STATUS_LABELS = {
    "assigned": "Chưa tiếp nhận",
    "in_progress": "Đang thực hiện",
    "submitted": "Đã nộp",
    "returned": "Bị trả lại",
    "completed": "Hoàn thành",
    "overdue": "Quá hạn",
}
TASK_FORM_ALLOWED_FIELD_TYPES = {"text", "number", "textarea", "radio", "checkbox", "table"}
TASK_GOOGLE_FORM_MATCH_MODE_LABELS = {
    "unit": "Đối sánh theo đơn vị báo cáo",
    "respondent_email": "Đối sánh theo email người trả lời",
}
TASK_BLUEPRINT_IMPORT_ALLOWED_EXTENSIONS = {".docx", ".txt", ".xlsx"}
TASK_BLUEPRINT_IMPORT_MODES = {
    "docx_outline": {
        "source_kind": "directive",
        "collection_mode": "outline",
        "default_title": "Đề cương công tác",
    },
    "docx_report_outline": {
        "source_kind": "sectioned_report",
        "collection_mode": "outline",
        "default_title": "Đề cương báo cáo",
    },
    "xlsx_form": {
        "source_kind": "excel_template",
        "collection_mode": "form",
        "default_title": "Biểu mẫu số liệu",
    },
    "google_form_remote": {
        "source_kind": "google_form",
        "collection_mode": "form",
        "default_title": "Biểu mẫu Google Form",
    },
}
TASK_IMPORT_DRAFT_ALLOWED_STATUSES = {"draft", "published", "failed"}
TASK_IMPORT_SOURCE_TYPES = {"docx_outline", "docx_report_outline", "xlsx_form", "google_form_remote", "blueprint_json"}
DEFAULT_TASK_REPORT_SCHEMA = {
    "enabled": False,
    "narrative": {
        "enabled": True,
        "label": "Báo cáo lời tổng hợp",
        "required": True,
        "placeholder": "Nêu rõ kết quả, tồn tại và kiến nghị nếu có",
        "target_type": "all",
        "target_unit_domains": [],
        "target_role_ids": [],
        "target_user_ids": [],
    },
    "attachment": {
        "enabled": False,
        "label": "Tệp minh chứng",
        "required": False,
        "target_type": "all",
        "target_unit_domains": [],
        "target_role_ids": [],
        "target_user_ids": [],
    },
    "fields": [],
}
CHILD_TASK_ALLOWED_REPORT_KINDS = {"narrative", "number"}
CHILD_TASK_NUMBER_FIELD_KEY = "reported_value"
CHILD_TASK_PROGRESS_CONDITIONS = (
    {
        "code": "reported_complete",
        "label": "Đã báo cáo",
        "description": "Hoàn thành báo cáo toàn bộ nhiệm vụ",
        "filename_suffix": "tien_do_da_bao_cao",
    },
    {
        "code": "reporting_in_progress",
        "label": "Đang báo cáo",
        "description": "Chưa hoàn thành toàn bộ nhiệm vụ",
        "filename_suffix": "tien_do_dang_bao_cao",
    },
    {
        "code": "not_reported",
        "label": "Chưa báo cáo",
        "description": "Chưa tiếp nhận",
        "filename_suffix": "tien_do_chua_bao_cao",
    },
)
CHILD_TASK_QUALITY_CONDITIONS = (
    {
        "code": "on_time",
        "label": "Đúng hạn",
        "description": "100% nhiệm vụ đúng hạn",
        "filename_suffix": "chat_luong_dung_han",
    },
    {
        "code": "partial_overdue",
        "label": "Quá hạn một phần",
        "description": "Một phần nhiệm vụ quá hạn",
        "filename_suffix": "chat_luong_qua_han_mot_phan",
    },
    {
        "code": "fully_overdue",
        "label": "Quá hạn báo cáo",
        "description": "100% nhiệm vụ quá hạn",
        "filename_suffix": "chat_luong_qua_han_bao_cao",
    },
)

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

def _normalize_task_mode(value):
    normalized = str(value or "").strip().upper()
    if normalized in TASK_MODE_ALLOWED:
        return normalized
    return ""

def _requested_task_mode(form, fallback=TASK_MODE_DEFAULT):
    requested = _normalize_task_mode(form.get("task_mode"))
    if requested:
        return requested
    normalized_fallback = _normalize_task_mode(fallback)
    return normalized_fallback or TASK_MODE_DEFAULT

def _task_mode(task, has_child_tasks=None):
    if not task:
        return TASK_MODE_DEFAULT
    cached = getattr(task, "_task_mode_cache", None)
    if cached:
        return cached

    explicit = _normalize_task_mode(getattr(task, "task_mode", None))
    if explicit:
        setattr(task, "_task_mode_cache", explicit)
        return explicit

    inferred = TASK_MODE_DEFAULT
    setattr(task, "_task_mode_cache", inferred)
    return inferred

def _task_mode_label(task_mode):
    normalized = _normalize_task_mode(task_mode)
    return TASK_MODE_LABELS.get(normalized, TASK_MODE_LABELS[TASK_MODE_DEFAULT])

def _task_mode_description(task_mode):
    normalized = _normalize_task_mode(task_mode)
    return TASK_MODE_DESCRIPTIONS.get(normalized, TASK_MODE_DESCRIPTIONS[TASK_MODE_DEFAULT])

def _task_assignment_status_label(status):
    return TASK_ASSIGNMENT_STATUS_LABELS.get(str(status or "").strip().lower(), "Chưa tiếp nhận")

def _task_assignment_display_status(status):
    return task_assignment_display_status(status, TASK_ASSIGNMENT_STATUS_LABELS, _normalize_status)

def _task_assignment_status_class(status):
    normalized = str(status or "").strip().lower()
    if normalized in {"completed", "submitted"}:
        return "done"
    if normalized in {"in_progress", "returned"}:
        return "doing"
    if normalized == "overdue":
        return "danger"
    return "todo"

def _task_domain_options():
    return module_category_options("tasks", "domain", "Đội nghiệp vụ")

def _task_field_options():
    return module_category_options("notify", "category", "Lĩnh vực", "Đội nghiệp vụ")

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
    if has_request_context():
        cached = getattr(g, "_task_current_perms_cache", None)
        if cached is not None:
            return cached
    role = db.session.get(AppRole, session.get("role_id")) if session.get("role_id") else None
    if role and role.perms:
        try:
            perms = normalize_permission_payload(role.perms, is_admin=session.get("is_admin"), role_name=getattr(role, "name", ""))
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

def _task_report_period(task):
    """Cấu hình cách báo cáo của công việc (dict chuẩn hóa)."""
    try:
        return report_task_config(task)
    except Exception:
        return report_normalize_config({})

def _parse_task_report_period_from_request(form, task_type=""):
    """Đọc cấu hình 'cách báo cáo' từ form tạo / sửa công việc."""
    data = dict(form or {})
    if task_type and not data.get("task_type"):
        data["task_type"] = task_type
    try:
        return report_parse_config(data)
    except Exception:
        return report_normalize_config({})

def _task_current_cycle(task, today=None):
    try:
        return report_current_cycle(_task_report_period(task), today=today)
    except Exception:
        return None

def _task_report_kind_label(task):
    cfg = _task_report_period(task)
    kind = str(cfg.get("kind") or "one_time").strip()
    label = REPORT_KIND_LABELS.get(kind)
    if not label:
        return "Báo cáo đột xuất / một lần"
    period = cfg.get("period")
    if kind == "periodic" and period in REPORT_PERIOD_LABELS:
        label = f"{label} — {REPORT_PERIOD_LABELS[period]}"
    return label

def _computed_task_deadline(form, task_type=""):
    """Hạn nộp theo 'cách báo cáo' — hạn của chu kỳ hiện tại khi tạo công việc."""
    try:
        cfg = _parse_task_report_period_from_request(form, task_type=task_type)
        return report_deadline_for(cfg)
    except Exception:
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

    return _dedupe_users(users)

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

def _clean_outline_title(raw_value):
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*(?:[-*+•]\s*|\+\s*|(?:[0-9]{1,3}\.){1,4}\s*|[0-9]{1,3}[.)]\s*|[A-Za-z][.)]\s*|[IVXLCDMivxlcdm]+[.)]\s*)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    return cleaned

def _is_outline_structural_heading(raw_text, cleaned_text):
    raw_text = str(raw_text or "").strip()
    cleaned_text = str(cleaned_text or "").strip()
    if not cleaned_text:
        return True

    normalized = remove_accents(cleaned_text.replace("Đ", "D").replace("đ", "d")).lower()
    compact = re.sub(r"\s+", " ", normalized).strip()
    has_bullet_prefix = bool(re.match(r"^\s*(?:[-*+•]|\+)\s*", raw_text))
    has_multi_numbering = bool(re.match(r"^\s*(?:(?:[0-9]{1,3}\.){1,4}|[IVXLCDMivxlcdm]+\.)", raw_text))

    if compact.startswith("de cuong bao cao") or compact.startswith("trong trien khai"):
        return True

    if re.match(r"^\s*[IVXLCDMivxlcdm]+\.\s+", raw_text):
        return True

    if re.match(r"^\s*[0-9]{1,3}\.\s+[A-ZĂÂĐÊÔƠƯÀÁẢÃẠẮẰẲẴẶẤẦẨẪẬÈÉẺẼẸẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌỐỒỔỖỘỚỜỞỠỢÙÚỦŨỤỨỪỬỮỰỲÝỶỸỴ\s]+$", raw_text):
        return True

    structural_markers = (
        "nhan xet, danh gia",
        "ve hoan thien the che",
        "ve cai cach tthc",
        "ve phat trien kinh te xa hoi",
        "ve phat trien cong dan so",
        "ve ket noi, chia se, tao lap du lieu",
        "ve nguon nhan luc",
        "ve trien khai cac mo hinh diem cua de an 06",
        "ve du lieu",
        "ve ha tang cong nghe thong tin",
        "ve an ninh an toan",
        "ve kinh phi",
        "ve nguon nhan luc",
        "trien khai cac giai phap thanh toan khong dung tien mat",
        "trien khai cac cong cu so va tien ich so cho nguoi dan",
        "pho cap ky nang so",
        "co che khuyen khich cong dan tham gia tren moi truong so",
        "trung tam phuc vu hanh chinh cong",
        "thue tinh",
    )
    if compact in structural_markers:
        return True

    if compact.startswith("cac so, ban, nganh") and compact.endswith("bao cao ket qua") and len(compact) < 60 and ":" not in compact:
        return True
    if compact.startswith("cac so, ban, nganh") and compact.endswith("bao cao ve") and len(compact) < 60 and ":" not in compact:
        return True
    # Cảnh giác: dòng nội dung cũng có thể bắt đầu bằng "Các sở, ban, ngành,
    # Ủy ban nhân dân xã, phường báo cáo..." nhưng LÀ NỘI DUNG cần gán (vd mục
    # 7.2, 8 trong đề cương). Chỉ coi là tiêu đề mục khi dòng ngắn, kiểu tiêu đề
    # (kết thúc bằng "báo cáo kết quả" / "báo cáo về") và không có dấu hai chấm.
    if compact.startswith("cac so, ban, nganh, uy ban nhan dan xa, phuong") and not has_bullet_prefix:
        if len(compact) < 60 and ":" not in compact and (
            compact.endswith("bao cao ket qua") or compact.endswith("bao cao ve")
        ):
            return True
    if compact.startswith("voi chinh phu") or compact.startswith("voi bo, nganh trung uong") or compact.startswith("voi uy ban nhan dan tinh") or compact.startswith("voi so, ban, nganh"):
        return True

    if has_multi_numbering and len(cleaned_text) < 40 and ":" not in cleaned_text and not any(
        keyword in compact for keyword in ("bao cao", "ton tai", "nhiem vu trong tam", "kien nghi", "de xuat")
    ):
        return True

    return False

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
    for paragraph in document.paragraphs:
        raw_text = str(getattr(paragraph, "text", "") or "").strip()
        if not raw_text:
            continue
        cleaned = _clean_outline_title(raw_text)
        if len(cleaned) < 3:
            continue
        style_name = str(getattr(getattr(paragraph, "style", None), "name", "") or "").strip().lower()
        is_outline_like = bool(
            re.match(r"^\s*(?:[-*+•]|\+|(?:[0-9]{1,3}\.){1,4}|[0-9]{1,3}[.)]|[A-Za-z][.)]|[IVXLCDMivxlcdm]+[.)])\s*", raw_text)
            or any(token in style_name for token in ("heading", "list", "bullet", "number"))
        )
        if is_outline_like and not _is_outline_structural_heading(raw_text, cleaned):
            candidates.append(cleaned)

    if not candidates:
        for paragraph in document.paragraphs:
            raw_text = str(getattr(paragraph, "text", "") or "").strip()
            if not raw_text:
                continue
            cleaned = _clean_outline_title(raw_text)
            if len(cleaned) < 3 or _is_outline_structural_heading(raw_text, cleaned):
                continue
            candidates.append(cleaned)

    return _parse_bulk_child_task_titles("\n".join(candidates))

def _pdf_decode_string_token(token):
    """Giải mã chuỗi văn bản PDF (nội dung giữa cặp ngoặc) — xử lý escape \\(, \\), \\\\, octal."""
    out = bytearray()
    i = 0
    n = len(token)
    while i < n:
        ch = token[i]
        if ch == 0x5C:  # backslash
            if i + 1 >= n:
                break
            nxt = token[i + 1]
            simple = {0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09, 0x62: 0x08, 0x66: 0x0C}  # n r t b f
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
            elif nxt in (0x28, 0x29, 0x5C):  # ( ) \
                out.append(nxt)
                i += 2
            elif 0x30 <= nxt <= 0x37:  # octal \ddd
                j = i + 1
                octal = 0
                count = 0
                while j < n and count < 3 and 0x30 <= token[j] <= 0x37:
                    octal = octal * 8 + (token[j] - 0x30)
                    j += 1
                    count += 1
                out.append(octal & 0xFF)
                i = j
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(ch)
            i += 1
    return bytes(out)


def _pdf_text_stdlib(data):
    """Trích văn bản từ PDF bằng thư viện chuẩn (zlib) — fallback khi máy chủ chưa
    cài pymupdf. Chỉ xử lý được PDF có text stream FlateDecode (không phải ảnh chụp)."""
    import zlib

    page_texts = []
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end_marker = data.find(b"endstream", start)
        if end_marker < 0:
            continue
        raw = data[start:end_marker]
        header = data[max(0, m.start() - 300):m.start()]
        if b"/FlateDecode" not in header:
            continue
        content = None
        for candidate in (raw, raw.rstrip(b"\r\n\x00 ")):
            try:
                content = zlib.decompress(candidate)
                break
            except Exception:
                continue
        if not content:
            continue
        # Chỉ xử lý content stream thật (có BT/ET đánh dấu bắt đầu văn bản).
        # Tránh chạy regex trên stream nhị phân (ảnh/font) chứa byte "Tj"/"TJ" ngẫu nhiên.
        if b"BT" not in content or not (b"Tj" in content or b"TJ" in content):
            continue
        text_parts = []
        for tm in re.finditer(rb"\((?:\\.|[^()])*\)\s*Tj|\[(?:[^\[\]]*)\]\s*TJ", content):
            token = tm.group(0)
            if token.endswith(b"Tj"):
                inner = token[token.find(b"(") + 1:token.rfind(b")")]
                text_parts.append(_pdf_decode_string_token(inner))
            else:
                arr_inner = token[1:token.rfind(b"]")]
                for sm in re.finditer(rb"\((?:\\.|[^()])*\)", arr_inner):
                    inner = sm.group(0)[1:-1]
                    text_parts.append(_pdf_decode_string_token(inner))
        if text_parts:
            page_texts.append(b"".join(text_parts).decode("utf-8", errors="replace"))
    return "\n".join(page_texts)


def _parse_outline_pdf_text(file_storage):
    """Trích dòng chữ từ file PDF: ưu tiên pymupdf, fallback thư viện chuẩn.
    Trả về (lines, error) — lines rỗng kèm error nếu không đọc được."""
    try:
        file_storage.stream.seek(0)
        data = file_storage.stream.read()
    except Exception:
        return [], "Không đọc được file PDF."
    if not data:
        return [], "File PDF rỗng."
    lines = []
    if PdfDocument is not None:
        try:
            document = PdfDocument.open(stream=data, filetype="pdf")
            try:
                for page in document:
                    for line in (str(getattr(page, "get_text", lambda: "")() or "")).splitlines():
                        cleaned = str(line or "").strip()
                        if cleaned:
                            lines.append(cleaned)
            finally:
                try:
                    document.close()
                except Exception:
                    pass
        except Exception:
            lines = []
    if not lines:
        raw_text = _pdf_text_stdlib(data)
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        if PdfDocument is None:
            return [], (
                "Máy chủ chưa cài thư viện đọc PDF (pymupdf). Hãy chạy: pip install pymupdf "
                "trên máy chủ rồi thử lại."
            )
        return [], (
            "File PDF không có nội dung chữ để phân tích (có thể là file ảnh chụp/scanned). "
            "Hãy tải bản .docx hoặc file PDF có chữ rõ ràng."
        )
    return lines, None


def _parse_outline_pdf_titles(file_storage):
    lines, error = _parse_outline_pdf_text(file_storage)
    if error:
        raise ValueError(error)
    return _parse_bulk_child_task_titles("\n".join(lines))


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
        raise ValueError("Chỉ hỗ trợ đề cương dạng .docx, .txt hoặc .pdf.")

    if extension == ".docx":
        return _parse_outline_docx_titles(file_storage)
    if extension == ".pdf":
        return _parse_outline_pdf_titles(file_storage)
    return _parse_outline_text_titles(file_storage)

OUTLINE_ASSIGNEE_HINT_KEYWORDS = (
    "đơn vị thực hiện",
    "cơ quan thực hiện",
    "đơn vị chủ trì",
    "đơn vị",
    "giao cho",
    "người thực hiện",
    "cán bộ phụ trách",
    "người phụ trách",
    "phụ trách",
    "chủ trì",
    "thực hiện",
    "phối hợp",
    "bộ phận",
)
OUTLINE_ASSIGNEE_NORM_KEYWORDS = (
    "don vi thuc hien",
    "co quan thuc hien",
    "don vi chu tri",
    "don vi",
    "giao cho",
    "nguoi thuc hien",
    "can bo phu trach",
    "nguoi phu trach",
    "phu trach",
    "chu tri",
    "thuc hien",
    "phoi hop",
    "bo phan",
)

def _normalize_outline_match_text(value):
    text = str(value or "").replace("Đ", "D").replace("đ", "d")
    normalized = remove_accents(text)
    normalized = normalized.lower()
    normalized = re.sub("[.,;:()\\[\\]\"'“”‘’]", " ", normalized)
    normalized = re.sub(r"[\s\-_/|]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()

def _task_assignment_catalog():
    """Danh mục đơn vị / vai trò / cán bộ để đối sánh 'giao cho ai' trong đề cương."""
    catalog = {"units": [], "roles": [], "users": []}
    seen_keys = set()
    for item in _task_assignment_unit_options():
        key = (item.get("value") or item.get("stable_value") or item.get("name") or "").strip()
        name = (item.get("name") or item.get("value") or key or "").strip()
        if not key or key in seen_keys or len(_normalize_outline_match_text(name)) < 3:
            continue
        seen_keys.add(key)
        catalog["units"].append({"key": key, "name": name, "match": _normalize_outline_match_text(name)})
    for role in AppRole.query.order_by(AppRole.name.asc()).all():
        role_name = str(role.name or "").strip()
        if len(_normalize_outline_match_text(role_name)) < 3:
            continue
        catalog["roles"].append({"id": role.id, "name": role_name, "match": _normalize_outline_match_text(role_name)})
    for user in User.query.filter(User.is_active.is_(True)).order_by(User.fullname.asc()).all():
        matches = []
        for label in (user.fullname, user.username):
            normalized = _normalize_outline_match_text(label)
            if len(normalized) >= 3 and normalized not in matches:
                matches.append(normalized)
        if matches:
            catalog["users"].append({"id": user.id, "fullname": user.fullname, "matches": matches})
    return catalog

def _find_all_outline_assignee_matches(normalized_text, catalog):
    """Tìm mọi đơn vị / vai trò / cá nhân xuất hiện trong chuỗi, không trùng lặp."""
    candidates = []
    for user in catalog["users"]:
        for label in user["matches"]:
            if len(label) >= 3:
                candidates.append(("user", label, user))
    for role in catalog["roles"]:
        if len(role["match"]) >= 3:
            candidates.append(("role", role["match"], role))
    for unit in catalog["units"]:
        if len(unit["match"]) >= 3:
            candidates.append(("unit", unit["match"], unit))
    candidates.sort(key=lambda item: len(item[1]), reverse=True)

    found = []
    for kind, label, target in candidates:
        search_from = 0
        while True:
            idx = normalized_text.find(label, search_from)
            if idx == -1:
                break
            if not any(idx < end and idx + len(label) > start for start, end, _kind, _target in found):
                found.append((idx, idx + len(label), kind, target))
                break
            search_from = idx + 1
    found.sort(key=lambda item: item[0])
    return found

def _resolve_outline_assignee_hint(hint_text, catalog):
    """Nhận diện cấu hình gán việc (đơn vị / vai trò / cá nhân) từ một đoạn chữ."""
    if not hint_text or not str(hint_text).strip():
        return None

    raw = str(hint_text).strip()
    keyword_pattern = (
        r"(?:đơn vị thực hiện|cơ quan thực hiện|đơn vị chủ trì|giao cho|người thực hiện|"
        r"cán bộ phụ trách|người phụ trách|đơn vị|phụ trách|chủ trì|thực hiện|phối hợp|bộ phận)"
        r"\s*[:：]\s*(.+)"
    )
    keyword_match = re.search(keyword_pattern, raw, re.IGNORECASE)
    if keyword_match:
        raw = keyword_match.group(1)

    normalized = _normalize_outline_match_text(raw)
    matched = {"units": [], "roles": [], "users": []}
    matched_labels = []
    for _start, _end, kind, target in _find_all_outline_assignee_matches(normalized, catalog):
        if kind == "unit":
            if target["key"] not in matched["units"]:
                matched["units"].append(target["key"])
                matched_labels.append(target["name"])
        elif kind == "role":
            if target["id"] not in matched["roles"]:
                matched["roles"].append(target["id"])
                matched_labels.append(target["name"])
        else:
            if target["id"] not in matched["users"]:
                matched["users"].append(target["id"])
                matched_labels.append(target["fullname"])

    if matched["users"]:
        return {"assign_type": "user", "unit_domains": [], "role_ids": [], "user_ids": matched["users"], "labels": matched_labels}
    if matched["roles"]:
        return {"assign_type": "role", "unit_domains": [], "role_ids": matched["roles"], "user_ids": [], "labels": matched_labels}
    if matched["units"]:
        return {"assign_type": "unit", "unit_domains": matched["units"], "role_ids": [], "user_ids": [], "labels": matched_labels}
    return None

def _strip_outline_assignee_suffix(title, catalog):
    """Tách phần 'giao cho ai' nằm ngay trong tiêu đề đầu mục (nếu có)."""
    raw = str(title or "").strip()
    for separator in (" — ", " – ", " - ", " (", "(", "[", ": "):
        if separator not in raw:
            continue
        left, right = raw.split(separator, 1)
        right = right.strip().rstrip(")]")
        if _resolve_outline_assignee_hint(right, catalog):
            return left.strip(), right
    return raw, ""

def _looks_like_outline_assignee_text(text, catalog):
    normalized = _normalize_outline_match_text(text)
    if len(normalized) < 3:
        return False
    if any(keyword in normalized for keyword in OUTLINE_ASSIGNEE_NORM_KEYWORDS):
        return True
    return _resolve_outline_assignee_hint(text, catalog) is not None

def _resolve_outline_rows_assignments(rows, catalog):
    resolved = []
    seen = set()
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        dedupe_key = _normalize_outline_match_text(title)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        hint = " | ".join(part for part in [row.get("hint") or ""] if part)
        assignment = _resolve_outline_assignee_hint(hint, catalog)
        resolved.append(
            {
                "title": title[:255],
                "assign_type": assignment["assign_type"] if assignment else "",
                "domain": "",
                "unit_domains": assignment["unit_domains"] if assignment else [],
                "role_ids": assignment["role_ids"] if assignment else [],
                "user_ids": assignment["user_ids"] if assignment else [],
                "assignee_hint": hint,
                "assignee_detected": bool(
                    assignment
                    and (assignment["unit_domains"] or assignment["role_ids"] or assignment["user_ids"])
                ),
            }
        )
    return resolved

def _paragraph_is_outline_item(text):
    raw_text = str(text or "").strip()
    if not raw_text:
        return False
    cleaned = _clean_outline_title(raw_text)
    if len(cleaned) < 3:
        return False
    if re.match(r"^\s*[IVXLCDMivxlcdm]+\.\s+", raw_text):
        return False
    if re.match(r"^\s*(?:[-*+•]|\+)\s*", raw_text):
        return True
    if re.match(r"^\s*(?:(?:[0-9]{1,3}\.){1,4}|[0-9]{1,3}[.)]|[A-Za-z][.)])\s+", raw_text):
        return True
    return False


def _is_outline_heading(text, style_name=""):
    raw = str(text or "").strip()
    if not raw:
        return False
    # DOCX heading style
    if style_name and any(token in str(style_name).lower() for token in ("heading", "title", "đề mục", "tieu de")):
        return True
    # Common heading patterns: A. I. 1. 1.1. a) (1)
    if re.match(r"^\s*(?:[A-Z][\.\)])\s*\S", raw):
        return True
    if re.match(r"^\s*(?:[IVXLCDM]+[\.\)])\s*\S", raw):
        return True
    if re.match(r"^\s*(?:\d{1,3}\.){1,4}\s+\S", raw):
        return True
    if re.match(r"^\s*\d{1,3}[\.\)]\s+\S", raw):
        return True
    if re.match(r"^\s*[a-z][\.\)]\s+\S", raw, re.IGNORECASE):
        return True
    if re.match(r"^\s*\(\d{1,3}\)\s+\S", raw):
        return True


def _get_heading_level(raw_text):
    """Return the hierarchy level and normalized marker for a heading."""
    raw = str(raw_text or "").strip()
    if not raw:
        return (0, "")
    # Roman/letter chapters are top-level containers. Chấp nhận dấu chấm tùy
    # chọn (vd: "III KIẾN NGHỊ, ĐỀ XUẤT") vì nhiều đề cương viết thiếu dấu chấm.
    roman_match = re.match(r"^\s*([IVXLCDM]+)\.?\s+", raw)
    if roman_match:
        return (1, roman_match.group(1))
    letter_match = re.match(r"^\s*([A-Z])\.\s+", raw)
    if letter_match:
        return (1, letter_match.group(1))
    # Numeric headings: 1., 1), 1.1, 1.1., 1.1.1, ...
    # Numeric levels start at 2 so they nest below Roman/letter chapters.
    numeric_match = re.match(r"^\s*(\d{1,3}(?:\.\d{1,3})*)[\.\)]?\s+(.+)$", raw)
    if numeric_match:
        number_part = numeric_match.group(1)
        return (number_part.count(".") + 2, number_part)
    return (0, "")

def _parse_outline_with_hierarchy(paragraphs, is_docx=False):
    """Parse đề cương với hierarchy đa cấp.
    
    Cấu trúc:
    - Level 1: I, II, III hoặc A, B, C (chương/phần lớn)
    - Level 2: 1, 2, 3 (mục lớn)
    - Level 3: 1.1, 1.2, 1.1.1 (mục con)
    - Content: các gạch đầu dòng (+, -, •) thuộc về mục cha gần nhất
    
    Trả về danh sách items với structure:
    [
        {
            "level": 1,
            "title": "I. KẾT QUẢ CÁC MẶT CÔNG TÁC",
            "number": "I",
            "children": [
                {
                    "level": 2,
                    "title": "1. CÔNG TÁC THAM MƯU...",
                    "number": "1",
                    "children": [
                        {
                            "level": 3,
                            "title": "1.1. Các Sở, ban, ngành...",
                            "number": "1.1",
                            "content_lines": ["- Dòng 1", "+ Dòng 2"],  # các gạch đầu dòng
                            "children": []
                        }
                    ]
                }
            ]
        }
    ]
    """
    items = []
    stack = []  # Stack để track parent items: [(level, item), ...]
    
    for para in paragraphs:
        if is_docx:
            text = str(getattr(para, "text", "") or "").strip()
            style_name = str(getattr(getattr(para, "style", None), "name", "") or "").strip()
        else:
            text = str(para or "").strip()
            style_name = ""
        
        if not text:
            continue
        
        # Check if this is a heading
        level, number = _get_heading_level(text)
        
        if level > 0:
            # Đây là heading
            title = text.strip()
            # Clean the title by removing the number prefix for storage
            clean_title = re.sub(r"^\s*(?:[IVXLCDM]+|[A-Z]|\d{1,3}(?:\.\d{1,3})*)[\.\)]?\s*", "", title).strip()
            
            new_item = {
                "level": level,
                "title": clean_title[:255],
                "full_title": title[:255],
                "number": number,
                "content_lines": [],
                "bullets": [],
                "children": []
            }
            
            # Pop stack until we find parent with level < current level
            while stack and stack[-1][0] >= level:
                stack.pop()
            
            # Add to parent's children or root
            if stack:
                parent_item = stack[-1][1]
                parent_item["children"].append(new_item)
            else:
                items.append(new_item)
            
            stack.append((level, new_item))
        else:
            # Đây là content line (gạch đầu dòng). Giữ nguyên cấp lồng nhau:
            # - / • / * : gạch đầu dòng cấp 1 (1 nội dung để gán)
            # +         : nội dung con nằm trong gạch đầu dòng cấp 1 liền trước
            if stack:
                current_parent = stack[-1][1]
                if not _is_outline_structural_heading(text, text):
                    _append_outline_bullet(current_parent, text)
            elif items:
                _append_outline_bullet(items[0], text)
    
    return items


def _append_outline_bullet(item, raw_text):
    """Thêm một dòng nội dung vào mục, giữ cấu trúc cha/con:
    gạch đầu dòng '-' là bullet cấp 1; dòng '+' là con của bullet cấp 1 liền trước.
    Dòng thường (không có ký hiệu) cũng là bullet cấp 1.
    """
    text = str(raw_text or "").strip()
    if not text:
        return
    item.setdefault("content_lines", []).append(text)
    bullets = item.setdefault("bullets", [])
    if re.match(r"^\s*\+", text):
        if bullets:
            bullets[-1].setdefault("children", []).append({"text": text, "type": "plus", "children": []})
        else:
            bullets.append({"text": text, "type": "plus", "children": []})
    else:
        bullet_type = "dash" if re.match(r"^\s*[-–—•*]", text) else "para"
        bullets.append({"text": text, "type": bullet_type, "children": []})


def _flatten_hierarchy_to_rows(hierarchy_items, catalog=None):
    """Chuyển cây đề cương thành danh sách dòng để gán việc.

    Mỗi GẠCH ĐẦU DÒNG cấp 1 ('-', '•', '*') là MỘT nội dung để gán (row riêng).
    Dòng '+' nằm dưới một gạch đầu dòng là NỘI DUNG CON của gạch đó (row con,
    có parent_row_index trỏ về row cha). Mặc định gán cho gạch đầu dòng sẽ tự
    gán cho các nội dung con, nhưng quản trị vẫn sửa được riêng từng dòng con.

    - Tiêu đề row = chính nội dung gạch đầu dòng (đã bỏ ký hiệu), không cần lặp
      lại tiêu đề mục vì đường dẫn mục đã đủ chi tiết (vd: I. » 1. » 1.1. ...).
    - Mục lá không có gạch đầu dòng -> tự nó là 1 việc (đầu mục chỉ có tiêu đề).
    - Mục trung gian (chỉ chứa mục con) -> không tạo việc, chỉ đệ quy xuống mục con.
    """
    rows = []
    seen = set()

    def make_row(text, full_heading, number, level, parent_row_index=None):
        raw = str(text or "").strip()
        if not raw:
            return None
        # Bỏ ký hiệu gạch đầu dòng ở đầu dòng: '-', '–', '—', '•', '*', '+'
        title = re.sub(r"^\s*(?:[-–—•*+]\s*|\+\s*)\s*", "", raw).strip()
        title = re.sub(r"\s+", " ", title).strip(" .:")
        if len(title) < 3:
            return None
        dedupe = _normalize_outline_match_text(f"{full_heading} {title}")
        if dedupe in seen:
            return None
        seen.add(dedupe)
        full_text = f"{full_heading}\n{raw}" if raw else full_heading
        assignment = _resolve_outline_assignee_hint(full_text, catalog) if catalog else None
        number_fields = _extract_number_fields_from_text(raw)
        return {
            "title": title[:255],
            "content": raw[:3000],
            "heading": full_heading[:255],
            "level": level,
            "number": number,
            "parent_row_index": parent_row_index,
            "has_numbers": bool(number_fields),
            "number_fields": number_fields,
            "skeleton": _outline_skeleton_text(raw[:3000], number_fields),
            "assign_type": assignment["assign_type"] if assignment else "",
            "domain": "",
            "unit_domains": assignment["unit_domains"] if assignment else [],
            "role_ids": assignment["role_ids"] if assignment else [],
            "user_ids": assignment["user_ids"] if assignment else [],
            "assignee_hint": full_text[:500],
            "assignee_detected": bool(assignment and (assignment["unit_domains"] or assignment["role_ids"] or assignment["user_ids"])),
        }

    def process_item(item, parent_heading=""):
        # Build full heading path
        full_heading = item.get("full_title", item.get("title", ""))
        if parent_heading:
            full_heading = f"{parent_heading} » {full_heading}"

        cleaned_title = _clean_outline_title(item.get("title", ""))
        number = str(item.get("number") or "").strip()
        bullets = item.get("bullets") or []
        has_children = bool(item.get("children"))

        if bullets:
            # Mỗi gạch đầu dòng cấp 1 là 1 nội dung để gán; '+' là nội dung con.
            for bullet in bullets:
                parent_row = make_row(bullet.get("text"), full_heading, number, item.get("level", 3))
                parent_row_index = None
                if parent_row:
                    parent_row_index = len(rows)
                    rows.append(parent_row)
                for child in bullet.get("children") or []:
                    child_row = make_row(
                        child.get("text"),
                        full_heading,
                        number,
                        item.get("level", 3) + 1,
                        parent_row_index=parent_row_index,
                    )
                    if child_row:
                        rows.append(child_row)
        elif not has_children and len(cleaned_title) >= 3:
            # Mục lá không có gạch đầu dòng -> tự nó là 1 việc (đầu mục chỉ có tiêu đề).
            row_title = f"{number}. {cleaned_title}" if number else cleaned_title
            row = make_row(row_title, full_heading, number, item.get("level", 1))
            if row:
                rows.append(row)
        # Process children
        for child in item.get("children", []):
            process_item(child, full_heading)

    for item in hierarchy_items:
        process_item(item)

    return rows


    return False


_OUTLINE_METRIC_KEYWORDS = [
    "tổng số", "tổng", "số lượng", "số", "đạt", "có", "trên", "dưới", "vượt", "chiếm",
    "tỷ lệ", "tỉ lệ", "tỷ suất", "tỉ suất", "phần trăm", "%", "bằng", "đến", "trong đó",
    "lũy kế", "còn", "đã", "được", "giải quyết", "tiếp nhận", "xử lý", "hoàn thành",
    "tăng", "giảm", "so với", "mức", "chỉ số", "kpi", "chỉ tiêu", "dư nợ", "người",
    "hồ sơ", "lượt", "trạm", "tài khoản", "đơn vị", "cơ sở", "yêu cầu", "thông tin",
    "trường hợp", "khoản", "đồng", "tỷ", "triệu", "căn cước", "thẻ", "tài khoản",
]

_OUTLINE_NUMBER_TOKEN = r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?"

_OUTLINE_UNIT_STOPWORDS = {
    "và", "của", "trong", "đến", "so", "với", "theo", "đạt", "chiếm", "từ", "đã",
    "được", "có", "tổng", "số", "là", "các", "khoảng", "gồm", "năm", "tháng", "ngày",
    "trên", "dưới", "vượt", "bằng", "tăng", "giảm", "còn", "để", "không", "tại", "về",
    "đồng", "trong đó", "toàn", "tỉnh", "huyện", "xã", "phường", "cấp", "kỳ", "thời điểm",
}


def _mask_outline_dates_and_years(text):
    """Thay ngày tháng, năm và số hiệu văn bản bằng ký tự cùng độ dài để
    không trùng với số liệu báo cáo. Phân số thật (54.105/57.417) không bị che."""
    masked = list(text)
    for match in re.finditer(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text):
        for i in range(match.start(), match.end()):
            masked[i] = "#"
    for match in re.finditer(r"(?<![\d/.])(?:19|20)\d{2}(?![\d/.])", text):
        for i in range(match.start(), match.end()):
            masked[i] = "#"
    # Số hiệu văn bản: 66.7/2025, 18/2023, 05/2025/NQ-CP... (RHS 2-4 chữ số, không phải phân số)
    for match in re.finditer(r"\d{1,3}(?:\.\d{1,3})*/\d{2,4}(?![\d.,])", text):
        for i in range(match.start(), match.end()):
            masked[i] = "#"
    # Số hiệu văn bản dạng 7709/QĐ-CAT-ANM, 18/CT-TTg: số + "/" theo sau bởi chữ cái
    for match in re.finditer(r"\d{2,}(?:\.\d+)*/(?=[A-Za-zÀ-Ỹà-ỹ])", text):
        for i in range(match.start(), match.end()):
            masked[i] = "#"
    return "".join(masked)


def _outline_number_metric(text, start, end, value):
    """Đánh giá 1 số/1 cặp số có phải số liệu báo cáo (metric) không."""
    if value.endswith("%") or "/" in value:
        return True
    compact = value.replace(".", "").replace(",", "").replace("%", "")
    if len(compact) >= 6:
        return True
    before = text[max(0, start - 25):start].lower()
    has_keyword = any(keyword in before for keyword in _OUTLINE_METRIC_KEYWORDS)
    unit = _outline_number_unit(text, end)
    if len(compact) >= 3 and (has_keyword or unit):
        return True
    if len(compact) == 2 and has_keyword and unit:
        return True
    return False


def _outline_number_unit(text, end):
    """Lấy đơn vị theo sau số (vd: %, tỷ đồng, người, hồ sơ)."""
    after = text[end:end + 40]
    match = re.match(r"\s*(%|%%)\s*", after)
    if match:
        return "%"
    match = re.match(r"\s*([\w\u00C0-\u1EF9]+(?:\s+[\w\u00C0-\u1EF9]+)?)", after)
    if not match:
        return ""
    unit = match.group(1).strip()
    first_word = unit.split()[0].lower()
    if first_word in _OUTLINE_UNIT_STOPWORDS or re.match(r"^(năm|tháng|ngày)$", first_word):
        return ""
    if unit.endswith(",") or unit.endswith(";") or unit.endswith("."):
        unit = unit[:-1]
    return unit[:30]


def _extract_number_fields_from_text(text):
    """Trích xuất các trường số liệu từ nội dung đề cương.

    Trả về danh sách dict: {blank_id, label, value, unit, kind, start, end}.
    - Cặp X/Y (54.105/57.417) -> 1 ô trống, kind="pair", value="X/Y".
    - Ngày tháng (13/7/2026), năm (2026), số hiệu văn bản (18/CT-TTg, số 66.7/2025)
      bị loại.
    - start/end là khoảng vị trí trong text gốc để thay ô trống / merge lại.
    """
    if not text:
        return []
    masked = _mask_outline_dates_and_years(text)
    fields = []
    seen_spans = set()
    blank_id = 0
    number_pattern = re.compile(_OUTLINE_NUMBER_TOKEN)
    pair_pattern = re.compile(
        r"(" + _OUTLINE_NUMBER_TOKEN + r")\s*/\s*(" + _OUTLINE_NUMBER_TOKEN + r")"
    )
    index = 0
    while index < len(text):
        pair = pair_pattern.match(masked, index)
        if pair:
            side1 = pair.group(1).replace(".", "").replace(",", "")
            side2 = pair.group(2).replace(".", "").replace(",", "")
            if re.match(r"^(19|20)\d{2}$", side1) or re.match(r"^(19|20)\d{2}$", side2):
                # Cặp chứa năm (số hiệu văn bản 66.7/2025, 18/2023...) — bỏ qua
                index = pair.end()
                continue
            value = pair.group(1) + "/" + pair.group(2)
            start, end = pair.span()
            if _outline_number_metric(text, start, end, value):
                blank_id += 1
                fields.append(
                    _outline_build_number_field(text, start, end, value, "pair", blank_id)
                )
                seen_spans.add((start, end))
                index = end
                continue
        number = number_pattern.match(masked, index)
        if not number:
            index += 1
            continue
        value = number.group(0)
        start, end = number.span()
        if (start, end) in seen_spans:
            index = end
            continue
        # Token khớp thiếu: số dài hơn bị cắt (vd "7709" -> "770") — bỏ qua để tránh sai lệch
        if end < len(masked) and masked[end].isdigit():
            index = end
            continue
        # Số hiệu văn bản dạng 18/CT-TTg, 66.7/2025 — theo sau là "/" (có thể có khoảng trắng)
        if re.match(r"\s*/", masked[end:]):
            index = end
            continue
        compact = value.replace(".", "").replace(",", "").replace("%", "")
        if len(compact) < 2 and not value.endswith("%"):
            index = end
            continue
        kind = "percent" if value.endswith("%") else "plain"
        if _outline_number_metric(text, start, end, value):
            blank_id += 1
            fields.append(
                _outline_build_number_field(text, start, end, value, kind, blank_id)
            )
            seen_spans.add((start, end))
        index = end
    return fields


def _outline_build_number_field(text, start, end, value, kind, blank_id):
    before = text[max(0, start - 80):start].strip()
    label = before.split(";")[-1].split(".")[-1].split(",")[-1].strip()
    label = re.sub(
        r"^\s*(?:và|hoặc|cùng|các|của|để|được|đã|có|là|từ|trong|đến)\s+",
        "",
        label,
        flags=re.IGNORECASE,
    ).strip()
    if len(label) < 2 or len(label) > 120:
        label = before[-60:].strip() if len(before) > 60 else before.strip()
        label = re.sub(
            r"^\s*(?:và|hoặc|cùng|các|của|để|được|đã|có|là|từ|trong|đến)\s+",
            "",
            label,
            flags=re.IGNORECASE,
        ).strip()
    label = re.sub(r"\s+(?:là|của|và|đạt|có|các)$", "", label, flags=re.IGNORECASE).strip()
    if len(label) < 2:
        label = f"Số liệu {blank_id}"
    unit = _outline_number_unit(text, end)
    return {
        "blank_id": blank_id,
        "label": label[:120],
        "value": value,
        "unit": unit[:30],
        "kind": kind,
        "start": start,
        "end": end,
    }


def _parse_vn_number(text):
    """Parse số theo cả định dạng VN (1.234,5 / 85,5) lẫn quốc tế (85.5 / 1234.5)."""
    if text is None:
        return None
    text = str(text).strip().replace("%", "").replace(" ", "")
    if not text or not re.match(r"^[\d.,]+$", text):
        return None
    try:
        if "," in text and "." in text:
            return float(text.replace(".", "").replace(",", "."))
        if "," in text:
            return float(text.replace(",", "."))
        if "." in text:
            parts = text.split(".")
            if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) > 1):
                return float(text.replace(".", ""))
            return float(text)
        return float(text)
    except ValueError:
        return None


def _parse_outline_blank_value(text):
    """Giá trị ô trống: chuỗi thô nếu là cặp X/Y, float nếu là số thường; None nếu lỗi."""
    if not text:
        return None
    text = str(text).strip()
    pair = re.match(r"^([\d.,]+)\s*/\s*([\d.,]+)$", text)
    if pair and _parse_vn_number(pair.group(1)) is not None and _parse_vn_number(pair.group(2)) is not None:
        return text
    return _parse_vn_number(text)


def _outline_blank_numeric(value):
    """Giá trị số của 1 ô trống để cộng gộp (cặp X/Y lấy tử số)."""
    if value is None:
        return None
    text = str(value).strip()
    match = re.match(r"([\d.,]+)", text)
    if not match:
        return None
    return _parse_vn_number(match.group(1))


def _outline_sources_json(sources):
    if not sources:
        return None
    try:
        return json.dumps([str(source).strip() for source in sources if str(source).strip()], ensure_ascii=False)
    except Exception:
        return None


def _outline_skeleton_text(text, fields):
    """Văn bản với mỗi số liệu thay bằng dấu [...] để xem trước trong wizard."""
    if not fields:
        return text
    result = []
    cursor = 0
    for field in sorted(fields, key=lambda f: f.get("start", 0)):
        start = int(field.get("start", 0))
        end = int(field.get("end", 0))
        if start < cursor or start > len(text) or end > len(text):
            continue
        result.append(text[cursor:start])
        result.append("[...]")
        cursor = end
    result.append(text[cursor:])
    return "".join(result)


def _find_report_secondary_linked_item(content, unit_domains, exclude_task_id):
    """Tìm đầu mục trùng nội dung ở task đã phát hành để liên kết 'báo cáo phụ'.

    Chỉ liên kết khi đơn vị được giao giống nhau (cùng domain) để việc tự động
    điền vào các file khi nộp báo cáo là hợp lệ.
    """
    normalized = _normalize_outline_match_text(str(content or ""))
    if not normalized:
        return None
    candidates = (
        TaskItem.query.filter(
            TaskItem.task_id != exclude_task_id,
            TaskItem.content.isnot(None),
            TaskItem.output_type == "OUTLINE",
        )
        .order_by(TaskItem.id.desc())
        .limit(400)
        .all()
    )
    domain_set = set(unit_domains or [])
    for candidate in candidates:
        if not candidate.content:
            continue
        if _normalize_outline_match_text(str(candidate.content)) != normalized:
            continue
        # Cùng người/đơn vị được giao mới liên kết (so user_id thực tế để tránh
        # lệch khóa đơn vị giữa các nguồn dữ liệu)
        candidate_assignments = TaskAssignment.query.filter_by(task_id=candidate.task_id, task_item_id=candidate.id).all()
        candidate_user_ids = {int(getattr(assignment, "user_id", 0) or 0) for assignment in candidate_assignments}
        if not domain_set or not candidate_user_ids:
            return None
        # Đơn vị được giao trong config (unit_domains) -> user thuộc các đơn vị đó
        target_user_ids = _unit_domain_user_ids(domain_set)
        if target_user_ids & candidate_user_ids:
            return candidate
    return None


def _unit_domain_user_ids(domain_set):
    """Tập user_id thuộc các đơn vị (cùng logic với _resolve_assignees_by_mode)."""
    user_ids = set()
    for domain in domain_set:
        for user in _users_for_unit(domain):
            user_ids.add(user.id)
    return user_ids


def _propagate_submission_to_linked_items(task, item, assignment, submission):
    """Nộp báo cáo 1 đầu mục -> tự động điền vào các đầu mục liên kết (báo cáo phụ)."""
    if not item or not assignment or not submission:
        return
    linked_items = []
    if getattr(item, "linked_item_id", None):
        linked = db.session.get(TaskItem, item.linked_item_id)
        if linked and linked.id != item.id:
            linked_items.append(linked)
    for linked in (getattr(item, "linked_items", None) or []):
        if linked.id != item.id and linked not in linked_items:
            linked_items.append(linked)
    for linked in linked_items:
        linked_assignment = TaskAssignment.query.filter_by(
            task_id=linked.task_id,
            task_item_id=linked.id,
            user_id=assignment.user_id,
        ).first()
        if not linked_assignment:
            continue
        existing = (
            TaskSubmission.query.filter_by(
                task_id=linked.task_id,
                task_item_id=linked.id,
                assignment_id=linked_assignment.id,
            )
            .order_by(TaskSubmission.id.desc())
            .first()
        )
        target_submission = existing
        if existing:
            existing.narrative_content = submission.narrative_content
            existing.numeric_value = submission.numeric_value
            existing.payload_json = submission.payload_json
            existing.status = submission.status
            existing.submitted_at = submission.submitted_at
            existing.updated_at = datetime.now()
        else:
            target_submission = TaskSubmission(
                task_id=linked.task_id,
                task_item_id=linked.id,
                assignment_id=linked_assignment.id,
                submitted_by=assignment.user_id,
                submission_type=submission.submission_type,
                status=submission.status,
                narrative_content=submission.narrative_content,
                numeric_value=submission.numeric_value,
                payload_json=submission.payload_json,
                submitted_at=submission.submitted_at,
            )
            db.session.add(target_submission)
            db.session.flush()
        linked_assignment.status = "submitted"
        linked_assignment.submitted_at = datetime.now()
        linked_assignment.updated_at = datetime.now()
        linked_assignment.last_submission_id = getattr(target_submission, "id", None)
        db.session.add(
            TaskComment(
                task_id=linked.task_id,
                user_id=assignment.user_id,
                user_name=session.get("fullname", "Người dùng"),
                content="[TỰ ĐỘNG] Đã điền báo cáo từ đầu mục liên kết (báo cáo phụ).",
            )
        )


def _outline_merged_content(content, fields, values):
    """Ghép giá trị đã nộp vào văn bản gốc tại đúng vị trí ô trống."""
    if not content:
        return content
    values = values or {}
    if "[...]" in content:
        # Nội dung là bản mẫu chứa marker [...] — thay từng marker bằng giá trị nộp
        sorted_fields = sorted(fields or [], key=lambda f: int(f.get("start", 0) or 0))
        parts = content.split("[...]")
        merged = [parts[0]]
        for idx in range(len(parts) - 1):
            field = sorted_fields[idx] if idx < len(sorted_fields) else {}
            blank_id = field.get("blank_id")
            submitted = values.get(str(blank_id), values.get(blank_id, ""))
            if submitted in (None, ""):
                submitted = field.get("value", "")
            merged.append(str(submitted))
            merged.append(parts[idx + 1])
        return "".join(merged)
    if not fields:
        return content
    result = []
    cursor = 0
    for field in sorted(fields, key=lambda f: f.get("start", 0)):
        start = int(field.get("start", 0))
        end = int(field.get("end", 0))
        if start < cursor or start > len(content) or end > len(content):
            continue
        result.append(content[cursor:start])
        blank_id = field.get("blank_id")
        submitted = values.get(str(blank_id), values.get(blank_id, ""))
        if submitted in (None, ""):
            submitted = field.get("value", "")
        result.append(str(submitted))
        cursor = end
    result.append(content[cursor:])
    return "".join(result)


def _outline_submission_values(submission):
    """Lấy dict values (blank_id -> giá trị) từ 1 submission."""
    payload = _parse_task_submission_payload(submission) if submission else {}
    if not isinstance(payload, dict):
        return {}
    values = payload.get("values")
    return values if isinstance(values, dict) else {}


def _outline_blank_input_html(blank_id, submitted, placeholder, unit=None, label=None):
    """Một ô nhập inline cho 1 ô trống số liệu.

    Nhãn/đơn vị nằm sẵn trong văn bản xung quanh marker nên không chèn thêm span
    (tránh lặp chữ); placeholder giữ số gốc làm tham chiếu cho đơn vị điền.
    """
    if submitted is None:
        submitted = ""
    width = (max(len(str(submitted)), len(placeholder or "")) * 9 + 30) if (submitted or placeholder) else 90
    return (
        f'<input class="form-control form-control-sm d-inline-block outline-blank-input" '
        f'name="report_number_value_{blank_id}" type="text" '
        f'style="width: {width}px;" '
        f'value="{html.escape(str(submitted))}" '
        f'placeholder="{html.escape(placeholder or "")}" data-outline-blank>'
    )


def _render_blank_editor_html(content, fields, values=None):
    """HTML cho đơn vị: câu văn với ô nhập inline tại từng số liệu.

    - Nội dung chứa marker [...] (bản mẫu đã xóa số): thay từng marker bằng ô nhập.
    - Nội dung chứa số gốc (dữ liệu cũ): chèn ô nhập theo start/end của fields.
    values: dict blank_id(str/int) -> giá trị đã nộp.
    """
    if not content:
        return ""
    values = values or {}
    if "[...]" in content:
        sorted_fields = sorted(fields or [], key=lambda f: int(f.get("start", 0) or 0))
        parts = content.split("[...]")
        result = [html.escape(parts[0])]
        for idx in range(len(parts) - 1):
            field = sorted_fields[idx] if idx < len(sorted_fields) else {"blank_id": idx + 1, "value": "", "unit": "", "label": "Số liệu"}
            blank_id = field.get("blank_id") or (idx + 1)
            submitted = values.get(str(blank_id), values.get(blank_id, ""))
            result.append(
                _outline_blank_input_html(
                    blank_id, submitted, field.get("value", "") or "",
                    field.get("unit", "") or "", field.get("label", "") or "",
                )
            )
            result.append(html.escape(parts[idx + 1]))
        return "".join(result)
    if not fields:
        return html.escape(content)
    result = []
    cursor = 0
    for field in sorted(fields, key=lambda f: f.get("start", 0)):
        start = int(field.get("start", 0))
        end = int(field.get("end", 0))
        if start < cursor or start > len(content) or end > len(content):
            continue
        result.append(html.escape(content[cursor:start]))
        blank_id = field.get("blank_id")
        submitted = values.get(str(blank_id), values.get(blank_id, ""))
        result.append(
            _outline_blank_input_html(
                blank_id, submitted, field.get("value", "") or "",
                field.get("unit", "") or "", field.get("label", "") or "",
            )
        )
        cursor = end
    result.append(html.escape(content[cursor:]))
    return "".join(result)


def _split_outline_paragraphs_into_blocks(paragraphs, is_docx=False):
    """Chia danh sách paragraphs thành các block (heading + content paragraphs)."""
    blocks = []
    current_heading = None
    current_content = []
    current_heading_text = ""
    current_heading_style = ""

    for para in paragraphs:
        if is_docx:
            text = str(getattr(para, "text", "") or "").strip()
            style_name = str(getattr(getattr(para, "style", None), "name", "") or "").strip()
        else:
            text = str(para or "").strip()
            style_name = ""
        if not text:
            continue
        if _is_outline_heading(text, style_name):
            if current_heading is not None or current_content:
                blocks.append({
                    "heading": current_heading_text,
                    "content": " ".join(current_content).strip(),
                })
            current_heading = text
            current_heading_text = text
            current_content = []
        else:
            if current_heading is None:
                # Leading text before any heading: treat as heading with no title
                current_heading = ""
                current_heading_text = ""
            current_content.append(text)

    if current_heading is not None or current_content:
        blocks.append({
            "heading": current_heading_text,
            "content": " ".join(current_content).strip(),
        })
    return blocks

OUTLINE_TABLE_ROLE_LABELS = {
    "stt": "Số thứ tự",
    "content": "Nội dung nhiệm vụ",
    "lead": "Đơn vị chủ trì",
    "coordinate": "Đơn vị phối hợp",
    "deadline": "Thời gian",
    "product": "Sản phẩm, kết quả",
    "note": "Ghi chú",
    "other": "Cột khác",
}


def _table_build_schema(header_cells):
    """Dựng cấu trúc cột bảng từ dòng tiêu đề: mỗi cột có index/header/role/visible.

    - role: tự nhận diện qua _table_column_role (content/lead/coordinate/deadline/...)
    - visible: cột có hiển thị cho đơn vị nhận hay không (mặc định hiện content/lead/
      coordinate/deadline; cột Stt, Sản phẩm, Ghi chú, cột khác mặc định ẩn — quản trị
      có thể tích/bỏ tích trong wizard).
    """
    roles = _table_column_role(header_cells)
    schema = []
    for idx, header in enumerate(header_cells):
        role = next((role for role, col_idx in roles.items() if col_idx == idx), "other")
        if role == "index":
            role = "stt"
        visible = role in ("content", "lead", "coordinate", "deadline")
        schema.append(
            {
                "index": idx,
                "header": re.sub(r"\s+", " ", str(header or "").strip())[:200],
                "role": role,
                "visible": visible,
            }
        )
    return schema


def _table_column_role(cells):
    """Dò vai trò từng cột của bảng theo dòng tiêu đề (bảng không có cột Stt).
    Trả về {vai_trò: chỉ_số_cột} (vd: {"content": 0, "lead": 1, "deadline": 2})."""
    roles = {}
    for idx, header in enumerate(cells):
        key = remove_accents(str(header or "").strip().lower())
        key = re.sub(r"[^a-z0-9 ]", " ", key)
        key = re.sub(r"\s+", " ", key).strip()
        if key in ("stt", "tt", "so", "so thu tu"):
            roles.setdefault("index", idx)
        elif key == "noi dung" or "noi dung" in key or "nhiem vu" in key or "cong viec" in key or key == "viec":
            roles.setdefault("content", idx)
        elif "chu tri" in key or key in ("don vi", "on vi") or ("thuc hien" in key and ("don vi" in key or "on vi" in key)):
            roles.setdefault("lead", idx)
        elif "phoi hop" in key:
            roles.setdefault("coordinate", idx)
        elif "thoi gian" in key or "thoi han" in key or "thoi diem" in key:
            roles.setdefault("deadline", idx)
        elif "san pham" in key or "ket qua" in key:
            roles.setdefault("product", idx)
        elif "ghi chu" in key:
            roles.setdefault("note", idx)
    return roles


def _table_header_based_rows(table, catalog=None, seen=None):
    """Xử lý bảng KHÔNG có cột số thứ tự (Stt/La Mã): dò vai trò cột theo tiêu đề
    (vd: Nhiệm vụ | Đơn vị | Thời hạn) và biến mỗi dòng dữ liệu thành 1 nội dung gán.
    """
    seen = seen if seen is not None else set()
    rows = []
    data_rows = list(table.rows)
    if not data_rows:
        return rows
    first_cells = [re.sub(r"\s+", " ", (c.text or "").strip().replace("\n", " ")) for c in data_rows[0].cells]
    roles = _table_column_role(first_cells)
    schema = _table_build_schema(first_cells)
    start = 1 if roles else 0
    for row in data_rows[start:]:
        cells = [re.sub(r"\s+", " ", (c.text or "").strip().replace("\n", " ")) for c in row.cells]
        if not any(cells):
            continue
        if roles:
            content = cells[roles["content"]] if roles.get("content", -1) >= 0 else ""
            lead = cells[roles["lead"]] if roles.get("lead", -1) >= 0 else ""
            coordinate = cells[roles["coordinate"]] if roles.get("coordinate", -1) >= 0 else ""
            deadline = cells[roles["deadline"]] if roles.get("deadline", -1) >= 0 else ""
            product = cells[roles["product"]] if roles.get("product", -1) >= 0 else ""
            if not content:
                # Không tìm thấy cột nội dung rõ ràng -> lấy ô có nội dung dài nhất
                content = max(cells, key=len) if cells else ""
        else:
            content = max(cells, key=len) if cells else ""
            lead = coordinate = deadline = product = ""
        if not content:
            continue
        unit_domains = []
        if catalog and lead:
            assignment = _resolve_outline_assignee_hint(f"Cơ quan chủ trì: {lead}", catalog)
            if assignment:
                unit_domains = assignment.get("unit_domains") or []
        content_parts = [content]
        if lead:
            content_parts.append(f"Cơ quan chủ trì: {lead}")
        if coordinate:
            content_parts.append(f"Cơ quan phối hợp: {coordinate}")
        if deadline:
            content_parts.append(f"Thời gian: {deadline}")
        if product:
            content_parts.append(f"Sản phẩm, kết quả: {product}")
        raw = f"- {' | '.join(content_parts)}"
        dedupe = _normalize_outline_match_text(f" {content}")
        if dedupe in seen:
            continue
        seen.add(dedupe)
        rows.append(
            {
                "title": content[:255],
                "content": raw[:3000],
                "heading": "",
                "level": 2,
                "number": "",
                "parent_row_index": None,
                "has_numbers": False,
                "number_fields": [],
                "assign_type": "unit" if unit_domains else "",
                "domain": "",
                "unit_domains": unit_domains,
                "role_ids": [],
                "user_ids": [],
                "assignee_hint": f"Cơ quan chủ trì: {lead}" if lead else "",
                "assignee_detected": bool(unit_domains),
                "table_schema": schema,
                "table_cells": {str(idx): cell for idx, cell in enumerate(cells)},
            }
        )
    return rows


def _table_rows_to_outline_rows(document, catalog=None):
    """Chuyển các BẢNG nhiệm vụ trong đề cương (cột: Stt | Nội dung nhiệm vụ |
    Cơ quan, đơn vị chủ trì | Cơ quan, đơn vị phối hợp | Thời gian | Sản phẩm, kết quả | Ghi chú)
    thành các dòng gán việc:
    - Dòng mục (ô đầu là số La Mã I, II, III...) -> tiêu đề mục (heading).
    - Dòng nhiệm vụ (ô đầu là số 1, 2, 3...) -> 1 nội dung để gán, ĐƠN VỊ CHỦ TRÌ
      được gán sẵn từ cột "Cơ quan, đơn vị chủ trì" (khớp với danh mục đơn vị).
    - Bảng không có cột Stt -> dò vai trò cột theo tiêu đề (fallback).
    """
    rows = []
    seen = set()
    for table in document.tables:
        current_heading = ""
        table_had_numeric = False
        header_cells = [re.sub(r"\s+", " ", (c.text or "").strip().replace("\n", " ")) for c in table.rows[0].cells] if table.rows else []
        schema = _table_build_schema(header_cells)
        roles = _table_column_role(header_cells)
        for row in table.rows:
            cells = [re.sub(r"\s+", " ", (c.text or "").strip().replace("\n", " ")) for c in row.cells]
            if not cells or not cells[0]:
                continue
            first = cells[0].strip()
            if first.lower().startswith("stt") or first.lower() == "tt":
                continue
            # Dòng mục: ô đầu là số La Mã
            if re.match(r"^[IVXLCDM]+$", first):
                title = next((c for c in cells[1:] if c and c.strip() and c.strip() != first), "")
                if title:
                    current_heading = f"{first}. {title.strip()}"[:255]
                continue
            # Dòng nhiệm vụ: ô đầu là số thứ tự
            if re.match(r"^\d{1,3}$", first):
                content_index = roles.get("content")
                lead_index = roles.get("lead")
                coordinate_index = roles.get("coordinate")
                deadline_index = roles.get("deadline")
                product_index = roles.get("product")
                if content_index is None:
                    content_index = 1 if len(cells) > 1 else 0
                content = cells[content_index].strip() if content_index < len(cells) else ""
                lead = cells[lead_index].strip() if lead_index is not None and lead_index < len(cells) else ""
                coordinate = cells[coordinate_index].strip() if coordinate_index is not None and coordinate_index < len(cells) else ""
                deadline = cells[deadline_index].strip() if deadline_index is not None and deadline_index < len(cells) else ""
                product = cells[product_index].strip() if product_index is not None and product_index < len(cells) else ""
                if not content:
                    continue
                # Gán sẵn đơn vị chủ trì (chỉ cột Chủ trì, không lấy cột Phối hợp)
                unit_domains = []
                if catalog and lead:
                    assignment = _resolve_outline_assignee_hint(f"Cơ quan chủ trì: {lead}", catalog)
                    if assignment:
                        unit_domains = assignment.get("unit_domains") or []
                content_parts = [content]
                if lead:
                    content_parts.append(f"Cơ quan chủ trì: {lead}")
                if coordinate:
                    content_parts.append(f"Cơ quan phối hợp: {coordinate}")
                if deadline:
                    content_parts.append(f"Thời gian: {deadline}")
                if product:
                    content_parts.append(f"Sản phẩm, kết quả: {product}")
                raw = f"- {' | '.join(content_parts)}"
                dedupe = _normalize_outline_match_text(f"{current_heading} {content}")
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                table_had_numeric = True
                rows.append(
                    {
                        "title": content[:255],
                        "content": raw[:3000],
                        "heading": current_heading[:255],
                        "level": 2,
                        "number": first,
                        "parent_row_index": None,
                        "has_numbers": False,
                        "number_fields": [],
                        "assign_type": "unit" if unit_domains else "",
                        "domain": "",
                        "unit_domains": unit_domains,
                        "role_ids": [],
                        "user_ids": [],
                        "assignee_hint": f"Cơ quan chủ trì: {lead}",
                        "assignee_detected": bool(unit_domains),
                        "table_schema": schema,
                        "table_cells": {str(idx): cell for idx, cell in enumerate(cells)},
                    }
                )
        # Bảng không có dòng số thứ tự nào -> thử dò cột theo tiêu đề
        if not table_had_numeric:
            rows.extend(_table_header_based_rows(table, catalog=catalog, seen=seen))
    return rows


def _parse_outline_docx_rows(file_storage):
    """Parse Word docx với hierarchy awareness (đoạn văn + bảng nhiệm vụ)."""
    if DocxDocument is None:
        raise ValueError("Máy chủ chưa cài thư viện đọc file Word (.docx).")

    try:
        file_storage.stream.seek(0)
        file_bytes = file_storage.stream.read()
        document = DocxDocument(io.BytesIO(file_bytes))
    except Exception:
        raise ValueError("Không đọc được file đề cương Word. Hãy thử lại với file .docx rõ nội dung đầu mục.")

    catalog = _task_assignment_catalog()
    paragraphs = list(document.paragraphs)
    hierarchy_items = _parse_outline_with_hierarchy(paragraphs, is_docx=True)
    rows = _flatten_hierarchy_to_rows(hierarchy_items, catalog=catalog)
    # Gộp thêm các dòng từ BẢNG nhiệm vụ (nếu file Word có bảng)
    if getattr(document, "tables", None):
        table_rows = _table_rows_to_outline_rows(document, catalog=catalog)
        rows.extend(table_rows)
    return rows


def _parse_outline_pdf_rows(file_storage):
    """Parse file PDF (báo cáo / đề cương): trích chữ từng trang -> dòng -> cây mục lục."""
    lines, error = _parse_outline_pdf_text(file_storage)
    if error:
        raise ValueError(error)

    catalog = _task_assignment_catalog()
    hierarchy_items = _parse_outline_with_hierarchy(lines, is_docx=False)
    rows = _flatten_hierarchy_to_rows(hierarchy_items, catalog=catalog)
    # Gộp thêm dòng từ các bảng trong PDF nếu có (bảng nhiệm vụ dạng chữ)
    try:
        file_storage.stream.seek(0)
        document = PdfDocument.open(stream=file_storage.stream.read(), filetype="pdf")
        for page in document:
            try:
                for table in (getattr(page, "find_tables", lambda: None)() or {}).tables:
                    data = table.extract()
                    if not data or not data[0] or not any(data[0]):
                        continue
                    headers = [re.sub(r"\s+", " ", str(c or "").strip().replace("\n", " ")) for c in data[0]]
                    roles = _table_column_role(headers)
                    schema = _table_build_schema(headers)
                    seen = {_normalize_outline_match_text(str(r.get("title") or "")) for r in rows}
                    for data_row in data[1:]:
                        cells = [re.sub(r"\s+", " ", str(c or "").strip().replace("\n", " ")) for c in data_row]
                        if not any(cells):
                            continue
                        content = cells[roles["content"]] if roles.get("content", -1) >= 0 else (max(cells, key=len) if cells else "")
                        if not content:
                            continue
                        lead = cells[roles["lead"]] if roles.get("lead", -1) >= 0 else ""
                        deadline = cells[roles["deadline"]] if roles.get("deadline", -1) >= 0 else ""
                        coordinate = cells[roles["coordinate"]] if roles.get("coordinate", -1) >= 0 else ""
                        product = cells[roles["product"]] if roles.get("product", -1) >= 0 else ""
                        if _normalize_outline_match_text(content) in seen:
                            continue
                        seen.add(_normalize_outline_match_text(content))
                        unit_domains = []
                        if catalog and lead:
                            assignment = _resolve_outline_assignee_hint(f"Cơ quan chủ trì: {lead}", catalog)
                            if assignment:
                                unit_domains = assignment.get("unit_domains") or []
                        content_parts = [content]
                        if lead:
                            content_parts.append(f"Cơ quan chủ trì: {lead}")
                        if coordinate:
                            content_parts.append(f"Cơ quan phối hợp: {coordinate}")
                        if deadline:
                            content_parts.append(f"Thời gian: {deadline}")
                        if product:
                            content_parts.append(f"Sản phẩm, kết quả: {product}")
                        rows.append(
                            {
                                "title": content[:255],
                                "content": f"- {' | '.join(content_parts)}"[:3000],
                                "heading": "",
                                "level": 2,
                                "number": "",
                                "parent_row_index": None,
                                "has_numbers": False,
                                "number_fields": [],
                                "assign_type": "unit" if unit_domains else "",
                                "domain": "",
                                "unit_domains": unit_domains,
                                "role_ids": [],
                                "user_ids": [],
                                "assignee_hint": f"Cơ quan chủ trì: {lead}" if lead else "",
                                "assignee_detected": bool(unit_domains),
                                "table_schema": schema,
                                "table_cells": {str(idx): cell for idx, cell in enumerate(cells)},
                            }
                        )
            except Exception:
                continue
        document.close()
    except Exception:
        pass
    return rows


def _blocks_to_outline_rows(blocks):
    catalog = _task_assignment_catalog()
    rows = []
    seen = set()
    for block in blocks:
        heading = str(block.get("heading") or "").strip()
        content = str(block.get("content") or "").strip()
        if not content and not heading:
            continue
        # Use heading as title fallback, but prefer a short title from content first sentence
        title = heading
        if not title:
            sentences = re.split(r"[.!?]\s+", content)
            title = sentences[0].strip() if sentences else content
        cleaned_title = _clean_outline_title(title)
        if len(cleaned_title) < 3:
            continue
        dedupe = _normalize_outline_match_text(cleaned_title)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        # Try to find assignee hint in heading/content or suffix
        full_text = " ".join([part for part in [heading, content] if part])
        title_for_hint, suffix_hint = _strip_outline_assignee_suffix(cleaned_title, catalog)
        hint_parts = [part for part in [suffix_hint] if part]
        if _looks_like_outline_assignee_text(content, catalog):
            hint_parts.append(content)
        number_fields = _extract_number_fields_from_text(content)
        assignment = _resolve_outline_assignee_hint(" | ".join(hint_parts), catalog)
        rows.append(
            {
                "title": cleaned_title[:255],
                "content": content[:2000],
                "heading": heading[:255],
                "has_numbers": bool(number_fields),
                "number_fields": number_fields,
                "skeleton": _outline_skeleton_text(content[:2000], number_fields),
                "assign_type": assignment["assign_type"] if assignment else "",
                "domain": "",
                "unit_domains": assignment["unit_domains"] if assignment else [],
                "role_ids": assignment["role_ids"] if assignment else [],
                "user_ids": assignment["user_ids"] if assignment else [],
                "assignee_hint": " | ".join(hint_parts),
                "assignee_detected": bool(
                    assignment and (assignment["unit_domains"] or assignment["role_ids"] or assignment["user_ids"])
                ),
            }
        )
    return rows

def _parse_outline_text_rows(file_storage):
    """Parse text file với hierarchy awareness."""
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

    lines = [line.strip() for line in raw_text.splitlines()]
    # Parse với hierarchy
    hierarchy_items = _parse_outline_with_hierarchy(lines, is_docx=False)
    catalog = _task_assignment_catalog()
    return _flatten_hierarchy_to_rows(hierarchy_items, catalog=catalog)

def _parse_outline_upload_rows(file_storage):
    """Đọc đề cương (.docx/.txt) -> đầu mục kèm người nhận được tự nhận diện."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return []

    extension = os.path.splitext(file_storage.filename or "")[1].lower()
    if extension not in TASK_OUTLINE_ALLOWED_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ đề cương dạng .docx, .txt hoặc .pdf.")

    if extension == ".docx":
        return _parse_outline_docx_rows(file_storage)
    if extension == ".pdf":
        return _parse_outline_pdf_rows(file_storage)
    return _parse_outline_text_rows(file_storage)

def _blueprint_title_from_filename(filename, fallback):
    stem = os.path.splitext(os.path.basename(str(filename or "").strip()))[0]
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return (stem or fallback or "Điều hành và thu báo cáo")[:255]

def _coerce_excel_sample_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Có" if value else "Không"
    return str(value).strip()

def _looks_like_number(value):
    text = _coerce_excel_sample_text(value).replace(",", "").strip()
    if not text:
        return False
    try:
        Decimal(text)
        return True
    except (InvalidOperation, ValueError):
        return False

def _infer_excel_blueprint_field_type(label, samples):
    compact_label = remove_accents(str(label or "")).strip().lower()
    if any(token in compact_label for token in ("so ", "số ", "tong", "tổng", "ty le", "tỷ lệ", "%", "chi tieu", "chỉ tiêu")):
        return "number"

    non_empty_samples = [_coerce_excel_sample_text(value) for value in (samples or []) if _coerce_excel_sample_text(value)]
    if not non_empty_samples:
        return "text"

    numeric_ratio = sum(1 for value in non_empty_samples if _looks_like_number(value)) / max(len(non_empty_samples), 1)
    if numeric_ratio >= 0.7:
        return "number"

    if max(len(value) for value in non_empty_samples) >= 80:
        return "textarea"
    return "text"

def _pick_excel_header_row(rows):
    best_index = None
    best_score = -1
    for index, row in enumerate(rows[:10]):
        non_empty = [cell for cell in row if cell]
        if len(non_empty) < 2:
            continue
        unique_count = len({cell.lower() for cell in non_empty})
        score = unique_count * 10 - index
        if score > best_score:
            best_score = score
            best_index = index
    return 0 if best_index is None and rows else best_index

def _parse_excel_template_blueprint(file_storage):
    if load_workbook is None:
        raise ValueError("Máy chủ chưa cài thư viện đọc file Excel (.xlsx).")

    extension = os.path.splitext(file_storage.filename or "")[1].lower()
    if extension == ".xls":
        raise ValueError("Hiện mới hỗ trợ file Excel .xlsx. Hãy chuyển file .xls sang .xlsx trước khi nạp.")

    try:
        file_storage.stream.seek(0)
        workbook = load_workbook(io.BytesIO(file_storage.stream.read()), data_only=True)
    except Exception:
        raise ValueError("Không đọc được file Excel. Hãy kiểm tra lại định dạng .xlsx.")

    worksheet = None
    for candidate in workbook.worksheets:
        if candidate.max_row <= 0 or candidate.max_column <= 0:
            continue
        worksheet = candidate
        break
    if worksheet is None:
        raise ValueError("Không tìm thấy sheet dữ liệu hợp lệ trong file Excel.")

    rows = []
    for row in worksheet.iter_rows(values_only=True):
        normalized_row = [_coerce_excel_sample_text(value) for value in row]
        if any(normalized_row):
            rows.append(normalized_row)
    if not rows:
        raise ValueError("File Excel chưa có dữ liệu để suy luận biểu mẫu.")

    header_index = _pick_excel_header_row(rows)
    if header_index is None:
        raise ValueError("Không xác định được dòng tiêu đề trong file Excel.")

    header_row = rows[header_index]
    header_cells = [
        (column_index, label.strip())
        for column_index, label in enumerate(header_row)
        if str(label or "").strip()
    ]
    if not header_cells:
        raise ValueError("Không tìm thấy cột hợp lệ trong dòng tiêu đề Excel.")

    sample_rows = rows[header_index + 1 : header_index + 16]
    form_fields = []
    for column_index, label in header_cells:
        samples = [
            sample_row[column_index]
            for sample_row in sample_rows
            if column_index < len(sample_row) and _coerce_excel_sample_text(sample_row[column_index])
        ]
        form_fields.append(
            {
                "label": label[:255],
                "type": _infer_excel_blueprint_field_type(label, samples),
                "required": False,
            }
        )

    blueprint = normalize_task_workflow_blueprint(
        {
            "title": _blueprint_title_from_filename(file_storage.filename, worksheet.title or "Biểu mẫu số liệu"),
            "source_kind": "excel_template",
            "collection_mode": "form",
            "form_fields": form_fields,
            "meta": {
                "sheet_name": worksheet.title,
                "header_row_index": header_index + 1,
            },
        }
    )
    if not blueprint:
        raise ValueError("Không thể chuyển file Excel thành blueprint hợp lệ.")
    return blueprint

def _blueprint_form_fields_from_google_form_payload(form_payload):
    raw_fields = []
    field_defs, _question_map = parse_google_form_definition(form_payload)
    for field_def in field_defs:
        options_payload = {}
        raw_options = field_def.get("field_options_json")
        if raw_options:
            try:
                options_payload = json.loads(raw_options)
            except Exception:
                options_payload = {}

        raw_field = {
            "label": field_def.get("field_label", ""),
            "type": field_def.get("field_type") or "text",
            "required": bool(field_def.get("is_required")),
        }
        if raw_field["type"] in {"radio", "checkbox"}:
            raw_field["choices"] = list(options_payload.get("choices") or [])
        elif raw_field["type"] == "table":
            raw_field["columns"] = list(options_payload.get("columns") or [])
        raw_fields.append(raw_field)
    return raw_fields

def _parse_google_form_reference_to_blueprint(form_reference):
    form_id = extract_google_form_id(form_reference)
    if not form_id:
        raise ValueError("Không nhận diện được Google Form URL hoặc form ID.")

    try:
        service = build_google_forms_service(current_app.config)
        imported = load_google_form_into_builder(service, form_id)
    except Exception as exc:
        raise ValueError(str(exc) or "Không thể đọc cấu trúc Google Form.") from exc

    form_payload = imported.get("form_payload") if isinstance(imported, dict) else {}
    info = form_payload.get("info") if isinstance(form_payload, dict) else {}
    title = str((info or {}).get("title") or "").strip()[:255]
    if not title:
        title = TASK_BLUEPRINT_IMPORT_MODES["google_form_remote"]["default_title"]

    blueprint = normalize_task_workflow_blueprint(
        {
            "title": title,
            "source_kind": "google_form",
            "collection_mode": "form",
            "form_fields": _blueprint_form_fields_from_google_form_payload(form_payload),
            "meta": {
                "google_form_id": form_id,
                "google_form_url": form_reference,
            },
        }
    )
    if not blueprint:
        raise ValueError("Không thể chuyển Google Form thành blueprint hợp lệ.")
    return blueprint

def _parse_reference_file_to_blueprint(file_storage, import_mode, form_reference=""):
    import_config = TASK_BLUEPRINT_IMPORT_MODES.get(str(import_mode or "").strip())
    if not import_config:
        raise ValueError("Chưa chọn kiểu phân tích tài liệu tham chiếu.")

    if import_mode == "google_form_remote":
        return _parse_google_form_reference_to_blueprint(form_reference)

    if not file_storage or not getattr(file_storage, "filename", ""):
        raise ValueError("Cần chọn tài liệu tham chiếu trước khi phân tích.")

    extension = os.path.splitext(file_storage.filename or "")[1].lower()
    if extension == ".doc":
        raise ValueError("File .doc chưa được hỗ trợ. Hãy chuyển sang .docx trước khi nạp.")
    if extension == ".xls":
        raise ValueError("Hiện mới hỗ trợ file Excel .xlsx. Hãy chuyển file .xls sang .xlsx trước khi nạp.")
    if extension not in TASK_BLUEPRINT_IMPORT_ALLOWED_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ tài liệu .docx, .txt hoặc .xlsx.")

    if import_mode == "xlsx_form":
        return _parse_excel_template_blueprint(file_storage)

    titles = _parse_outline_upload_titles(file_storage)
    if not titles:
        raise ValueError("Không tìm thấy đầu mục hợp lệ trong tài liệu tham chiếu.")

    blueprint = normalize_task_workflow_blueprint(
        {
            "title": _blueprint_title_from_filename(file_storage.filename, import_config["default_title"]),
            "source_kind": import_config["source_kind"],
            "collection_mode": import_config["collection_mode"],
            "items": [
                {
                    "title": title,
                    "report_kind": "narrative",
                    "attachment_required": False,
                }
                for title in titles
            ],
        }
    )
    if not blueprint:
        raise ValueError("Không thể chuyển tài liệu tham chiếu thành blueprint hợp lệ.")
    return blueprint

def _task_import_status_label(status):
    normalized = str(status or "").strip().lower()
    if normalized == "published":
        return "Đã phát hành"
    if normalized == "failed":
        return "Lỗi phát hành"
    return "Đang soạn"

def _task_import_source_label(source_type):
    normalized = str(source_type or "").strip().lower()
    labels = {
        "docx_outline": "Word/TXT -> đề cương công tác",
        "docx_report_outline": "Word/TXT -> đề cương báo cáo theo mục",
        "xlsx_form": "Excel -> biểu mẫu số liệu",
        "google_form_remote": "Google Form -> biểu mẫu",
        "blueprint_json": "Blueprint JSON nâng cao",
    }
    return labels.get(normalized, normalized or "Không xác định")

def _json_loads_safe(raw_value, default):
    try:
        parsed = json.loads(raw_value or "")
    except Exception:
        return default
    return parsed if isinstance(parsed, type(default)) else default

def _json_dump(raw_value):
    return json.dumps(raw_value, ensure_ascii=False)

def _draft_field_options_text(field_options_json):
    payload = _json_loads_safe(field_options_json, {})
    if payload.get("choices"):
        return "\n".join(str(item).strip() for item in payload.get("choices", []) if str(item).strip())
    if payload.get("columns"):
        return ", ".join(str(item).strip() for item in payload.get("columns", []) if str(item).strip())
    return ""

def _draft_field_options_json(field_type, raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return None
    payload = {}
    if field_type in {"radio", "checkbox"}:
        payload["choices"] = [item.strip() for item in text.splitlines() if item.strip()]
    elif field_type == "table":
        payload["columns"] = [item.strip() for item in text.split(",") if item.strip()]
    return _json_dump(payload) if payload else None

def _task_import_form_field_target_config(raw_field):
    option_payload = _json_loads_safe(raw_field.get("field_options_json"), {})
    return _normalize_report_target_config(
        {
            "target_type": raw_field.get("target_type", option_payload.get("target_type", "all")),
            "target_unit_domains": raw_field.get("target_unit_domains", option_payload.get("target_unit_domains", [])),
            "target_role_ids": raw_field.get("target_role_ids", option_payload.get("target_role_ids", [])),
            "target_user_ids": raw_field.get("target_user_ids", option_payload.get("target_user_ids", [])),
        }
    )

def _task_import_form_field_options_json(field_type, raw_value, target_config=None):
    payload = _json_loads_safe(_draft_field_options_json(field_type, raw_value), {})
    normalized_target = _normalize_report_target_config(target_config or {})
    if normalized_target.get("target_type") != "all":
        payload["target_type"] = normalized_target.get("target_type")
    if normalized_target.get("target_unit_domains"):
        payload["target_unit_domains"] = normalized_target.get("target_unit_domains")
    if normalized_target.get("target_role_ids"):
        payload["target_role_ids"] = normalized_target.get("target_role_ids")
    if normalized_target.get("target_user_ids"):
        payload["target_user_ids"] = normalized_target.get("target_user_ids")
    return _json_dump(payload) if payload else None

def _normalize_google_form_match_mode(value):
    normalized = str(value or "").strip().lower()
    if normalized in TASK_GOOGLE_FORM_MATCH_MODE_LABELS:
        return normalized
    return "unit"

def _normalize_google_form_builder_schema_with_targets(raw_schema, fallback_title="", fallback_description=""):
    normalized = normalize_google_form_builder_schema(
        raw_schema,
        fallback_title=fallback_title,
        fallback_description=fallback_description,
    )
    raw_items = raw_schema.get("items") if isinstance(raw_schema, dict) and isinstance(raw_schema.get("items"), list) else []
    target_by_item_id = {}
    target_by_label = {}
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        target_config = _normalize_report_target_config(raw_item)
        item_id = str(raw_item.get("pc06_item_id") or f"index:{index}").strip()
        label_key = str(raw_item.get("title") or "").strip().lower()
        target_by_item_id[item_id] = target_config
        if label_key and label_key not in target_by_label:
            target_by_label[label_key] = target_config

    for index, item in enumerate(normalized.get("items") or []):
        item_id = str(item.get("pc06_item_id") or f"index:{index}").strip()
        label_key = str(item.get("title") or "").strip().lower()
        target_config = target_by_item_id.get(item_id) or target_by_label.get(label_key) or {}
        item.update(target_config)
    return normalized

def _parse_google_form_builder_schema(raw_builder_json, fallback_title="", fallback_description=""):
    text = str(raw_builder_json or "").strip()
    if not text:
        raise ValueError("Cần cấu hình schema builder cho Google Form.")
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise ValueError("Schema builder Google Form không phải JSON hợp lệ.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Schema builder Google Form phải là một JSON object.")
    try:
        return _normalize_google_form_builder_schema_with_targets(
            parsed,
            fallback_title=fallback_title,
            fallback_description=fallback_description,
        )
    except Exception as exc:
        raise ValueError(str(exc) or "Schema builder Google Form không hợp lệ.") from exc

def _hydrate_google_form_fields(builder_schema):
    normalized = _normalize_google_form_builder_schema_with_targets(builder_schema, fallback_title="Biểu mẫu")
    target_by_item_id = {}
    target_by_label = {}
    for index, item in enumerate(normalized.get("items") or []):
        item_id = str(item.get("pc06_item_id") or f"index:{index}").strip()
        label_key = str(item.get("title") or "").strip().lower()
        target_config = _normalize_report_target_config(item)
        target_by_item_id[item_id] = target_config
        if label_key and label_key not in target_by_label:
            target_by_label[label_key] = target_config

    field_defs = builder_schema_to_task_form_fields(normalized)
    for field_def in field_defs:
        options_payload = _json_loads_safe(field_def.get("field_options_json"), {})
        item_id = str(options_payload.get("pc06_item_id") or "").strip()
        label_key = str(field_def.get("field_label") or "").strip().lower()
        target_config = target_by_item_id.get(item_id) or target_by_label.get(label_key) or {}
        if target_config.get("target_type") != "all":
            options_payload["target_type"] = target_config.get("target_type")
        if target_config.get("target_unit_domains"):
            options_payload["target_unit_domains"] = target_config.get("target_unit_domains")
        if target_config.get("target_role_ids"):
            options_payload["target_role_ids"] = target_config.get("target_role_ids")
        if target_config.get("target_user_ids"):
            options_payload["target_user_ids"] = target_config.get("target_user_ids")
        field_def["field_options_json"] = _json_dump(options_payload) if options_payload else None
    return field_defs

def _task_google_form_runtime(task):
    return _json_loads_safe(getattr(task, "google_form_runtime_json", None), {})

def _task_google_form_sync_state(task):
    return _json_loads_safe(getattr(task, "google_form_sync_state_json", None), {})

def _task_google_form_builder(task):
    return _json_loads_safe(getattr(task, "google_form_builder_json", None), {})

def _task_google_form_runtime_payload(task, form_payload=None, base_runtime=None):
    runtime = dict(base_runtime or {})
    if not isinstance(form_payload, dict):
        return runtime

    info = form_payload.get("info") if isinstance(form_payload.get("info"), dict) else {}
    form_id = str(form_payload.get("formId") or runtime.get("form_id") or getattr(task, "google_form_id", "") or "").strip()
    form_url = str(
        form_payload.get("responderUri")
        or runtime.get("form_url")
        or getattr(task, "google_form_url", "")
        or (f"https://docs.google.com/forms/d/{form_id}/viewform" if form_id else "")
    ).strip()
    runtime.update(
        {
            "form_id": form_id,
            "form_url": form_url,
            "edit_url": str(runtime.get("edit_url") or (f"https://docs.google.com/forms/d/{form_id}/edit" if form_id else "")).strip(),
            "revision_id": str(form_payload.get("revisionId") or runtime.get("revision_id") or "").strip(),
            "publish_settings": form_payload.get("publishSettings") or runtime.get("publish_settings") or {},
            "title": str(info.get("title") or runtime.get("title") or "").strip(),
            "description": str(info.get("description") or runtime.get("description") or "").strip(),
        }
    )
    return runtime

def _task_google_form_target_lookup(task=None, builder_schema=None):
    by_question_id = {}
    by_label = {}

    if task:
        for field in _task_form_fields(task):
            options_payload = _json_loads_safe(getattr(field, "field_options_json", None), {})
            target_config = _normalize_report_target_config(options_payload)
            question_id = str(options_payload.get("question_id") or options_payload.get("pc06_item_id") or "").strip()
            label_key = str(getattr(field, "field_label", "") or "").strip().lower()
            if question_id and question_id not in by_question_id:
                by_question_id[question_id] = target_config
            if label_key and label_key not in by_label:
                by_label[label_key] = target_config

    if isinstance(builder_schema, dict):
        for item in builder_schema.get("items") or []:
            if not isinstance(item, dict):
                continue
            target_config = _normalize_report_target_config(item)
            question_id = str(item.get("pc06_item_id") or "").strip()
            label_key = str(item.get("title") or "").strip().lower()
            if question_id and question_id not in by_question_id:
                by_question_id[question_id] = target_config
            if label_key and label_key not in by_label:
                by_label[label_key] = target_config

    return by_question_id, by_label

def _merge_google_form_field_targets(field_defs, task=None, builder_schema=None):
    by_question_id, by_label = _task_google_form_target_lookup(task=task, builder_schema=builder_schema)
    merged_defs = []
    for field_def in field_defs or []:
        options_payload = _json_loads_safe(field_def.get("field_options_json"), {})
        question_id = str(options_payload.get("question_id") or options_payload.get("pc06_item_id") or "").strip()
        label_key = str(field_def.get("field_label") or "").strip().lower()
        target_config = by_question_id.get(question_id) or by_label.get(label_key) or {}
        if target_config.get("target_type") != "all":
            options_payload["target_type"] = target_config.get("target_type")
        if target_config.get("target_unit_domains"):
            options_payload["target_unit_domains"] = target_config.get("target_unit_domains")
        if target_config.get("target_role_ids"):
            options_payload["target_role_ids"] = target_config.get("target_role_ids")
        if target_config.get("target_user_ids"):
            options_payload["target_user_ids"] = target_config.get("target_user_ids")
        updated_field = dict(field_def)
        updated_field["field_options_json"] = _json_dump(options_payload) if options_payload else None
        merged_defs.append(updated_field)
    return merged_defs

def _replace_task_form_fields(task, field_defs):
    TaskFormField.query.filter_by(task_id=task.id).delete()
    for field_def in field_defs or []:
        db.session.add(TaskFormField(task_id=task.id, **_task_form_field_db_kwargs(field_def)))

def _task_google_form_manage_service():
    return build_google_forms_service(current_app.config, scopes=GOOGLE_FORMS_MANAGE_SCOPES)

def _task_google_form_match_label(task):
    return TASK_GOOGLE_FORM_MATCH_MODE_LABELS.get(
        _normalize_google_form_match_mode(getattr(task, "google_form_match_mode", "")),
        TASK_GOOGLE_FORM_MATCH_MODE_LABELS["unit"],
    )

def _apply_task_google_form_view_state(task):
    if not task:
        return

    runtime = _task_google_form_runtime(task)
    sync_state = _task_google_form_sync_state(task)
    builder = _task_google_form_builder(task)

    if getattr(task, "google_form_id", None) or getattr(task, "google_form_url", None):
        runtime.setdefault("form_id", getattr(task, "google_form_id", None) or "")
        runtime.setdefault("form_url", getattr(task, "google_form_url", None) or "")
        if runtime.get("form_id") and not runtime.get("edit_url"):
            runtime["edit_url"] = f"https://docs.google.com/forms/d/{runtime['form_id']}/edit"
    if runtime.get("title") and not sync_state.get("form_title"):
        sync_state["form_title"] = runtime.get("title")

    setattr(task, "google_form_runtime", runtime)
    setattr(task, "google_form_sync_state", sync_state)
    setattr(task, "google_form_builder", builder)
    setattr(task, "google_form_builder_managed", bool(builder))
    setattr(task, "google_form_match_mode_label", _task_google_form_match_label(task))

def _task_google_form_response_match_value(task, response_row):
    mode = _normalize_google_form_match_mode(getattr(task, "google_form_match_mode", "unit"))
    if mode == "respondent_email":
        return str(response_row.get("respondent_email") or "").strip()

    match_field = str(getattr(task, "google_form_match_field", "") or "").strip()
    payload_by_label = response_row.get("payload_by_label") if isinstance(response_row.get("payload_by_label"), dict) else {}
    if match_field:
        return str(payload_by_label.get(match_field) or "").strip()
    for value in payload_by_label.values():
        text = str(value or "").strip()
        if text:
            return text
    return ""

def _google_form_assignment_matches_response(task, assignment, response_row):
    user = getattr(assignment, "user", None)
    if not user:
        return False

    match_value = _task_google_form_response_match_value(task, response_row)
    if not match_value:
        return False

    mode = _normalize_google_form_match_mode(getattr(task, "google_form_match_mode", "unit"))
    if mode == "respondent_email":
        user_candidates = {
            str(getattr(user, "username", "") or "").strip().lower(),
            str(getattr(user, "fullname", "") or "").strip().lower(),
        }
        return match_value.strip().lower() in user_candidates

    return any(
        is_unit_match(candidate, match_value)
        for candidate in [
            getattr(user, "unit_area", None),
            getattr(user, "unit_key", None),
            getattr(user, "fullname", None),
        ]
        if str(candidate or "").strip()
    )

def _match_google_form_response_to_assignment(task, response_row):
    assignments = (
        TaskAssignment.query.options(joinedload(TaskAssignment.user))
        .filter_by(task_id=task.id)
        .order_by(TaskAssignment.id.asc())
        .all()
    )
    for assignment in assignments:
        if _google_form_assignment_matches_response(task, assignment, response_row):
            return assignment
    return None

def _filter_google_form_response_for_assignment(task, assignment, response_row):
    raw_payload = response_row.get("payload") if isinstance(response_row.get("payload"), dict) else {}
    raw_payload_by_label = response_row.get("payload_by_label") if isinstance(response_row.get("payload_by_label"), dict) else {}
    user = getattr(assignment, "user", None)
    if not user and getattr(assignment, "user_id", None):
        user = db.session.get(User, assignment.user_id)
    if not user:
        return {
            "payload": dict(raw_payload),
            "payload_by_label": dict(raw_payload_by_label),
            "ignored_keys": [],
            "visible_field_count": 0,
        }

    visible_fields = _task_form_fields_for_user(task, user)
    visible_keys = {str(getattr(field, "field_key", "") or "").strip() for field in visible_fields if str(getattr(field, "field_key", "") or "").strip()}
    visible_labels = {str(getattr(field, "field_label", "") or "").strip() for field in visible_fields if str(getattr(field, "field_label", "") or "").strip()}
    filtered_payload = {
        key: value
        for key, value in raw_payload.items()
        if str(key or "").strip() in visible_keys
    }
    filtered_payload_by_label = {}
    for label, value in raw_payload_by_label.items():
        normalized_label = str(label or "").strip()
        root_label = normalized_label.split(" / ", 1)[0].strip()
        if root_label in visible_labels:
            filtered_payload_by_label[normalized_label] = value

    ignored_keys = [
        str(key or "").strip()
        for key in raw_payload.keys()
        if str(key or "").strip() and str(key or "").strip() not in filtered_payload
    ]
    return {
        "payload": filtered_payload,
        "payload_by_label": filtered_payload_by_label,
        "ignored_keys": ignored_keys,
        "visible_field_count": len(visible_keys),
    }

def _task_import_field_key(label, index, used_keys, fallback_prefix):
    base = secure_filename(remove_accents(label).replace(" ", "_")) or f"{fallback_prefix}_{index + 1}"
    candidate = base[:100]
    if candidate not in used_keys:
        used_keys.add(candidate)
        return candidate
    suffix = 2
    while True:
        deduped = f"{candidate[:95]}_{suffix}"
        if deduped not in used_keys:
            used_keys.add(deduped)
            return deduped
        suffix += 1

def _task_import_working_config_from_blueprint(blueprint, source_type="", source_name="", source_ref=""):
    normalized = normalize_task_workflow_blueprint(blueprint)
    if not normalized:
        raise ValueError("Blueprint điều hành chưa có nội dung hợp lệ.")

    config = {
        "version": 1,
        "source_type": str(source_type or "").strip(),
        "source_name": str(source_name or normalized.get("title") or "").strip()[:255],
        "source_ref": str(source_ref or "").strip()[:500],
        "source_kind": normalized.get("source_kind") or "custom",
        "collection_mode": normalized.get("collection_mode") or "file",
        "task_mode": workflow_blueprint_task_mode(normalized),
        "title": str(normalized.get("title") or "").strip()[:255],
        "summary": str(workflow_blueprint_summary_text(normalized) or "").strip()[:4000],
        "category": "",
        "domain": "",
        "priority": "Trung bình",
        "task_type": "Công việc thường xuyên",
        "deadline": "",
        "assign_type": "unit",
        "unit_domains": [],
        "role_ids": [],
        "user_ids": [],
        "manager_scope_mode": "none",
        "manager_role_ids": [],
        "manager_user_ids": [],
        "viewer_scope_mode": "none",
        "viewer_role_ids": [],
        "viewer_user_ids": [],
        "items": [],
        "form_fields": [],
        "report_narrative_enabled": True,
        "report_narrative_required": True,
        "report_narrative_label": "Báo cáo lời tổng hợp",
        "report_narrative_target_type": "all",
        "report_narrative_unit_domains": [],
        "report_narrative_role_ids": [],
        "report_narrative_user_ids": [],
        "report_attachment_enabled": False,
        "report_attachment_required": False,
        "report_attachment_label": "Tệp minh chứng",
        "report_attachment_target_type": "all",
        "report_attachment_unit_domains": [],
        "report_attachment_role_ids": [],
        "report_attachment_user_ids": [],
        "report_fields": [],
    }

    if config["collection_mode"] == "outline":
        for item in workflow_blueprint_item_configs(normalized):
            config["items"].append(
                {
                    "title": item.get("title", ""),
                    "guide_text": item.get("guide_text", ""),
                    "report_kind": item.get("report_kind") or "narrative",
                    "attachment_required": bool(item.get("attachment_required")),
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                    "sort_order": item.get("sort_order", len(config["items"])),
                }
            )
    elif config["collection_mode"] == "form":
        used_keys = set()
        for index, field in enumerate(workflow_blueprint_form_field_defs(normalized)):
            target_config = _task_import_form_field_target_config(field)
            field_key = str(field.get("field_key") or "").strip() or _task_import_field_key(
                field.get("field_label") or "",
                index,
                used_keys,
                "field",
            )
            used_keys.add(field_key)
            config["form_fields"].append(
                {
                    "field_key": field_key,
                    "field_label": str(field.get("field_label") or "").strip()[:255],
                    "field_type": _normalize_task_form_field_type(field.get("field_type") or "text"),
                    "field_options_text": _draft_field_options_text(field.get("field_options_json")),
                    "is_required": bool(field.get("is_required")),
                    "target_type": target_config.get("target_type") or "all",
                    "target_unit_domains": target_config.get("target_unit_domains") or [],
                    "target_role_ids": target_config.get("target_role_ids") or [],
                    "target_user_ids": target_config.get("target_user_ids") or [],
                    "sort_order": field.get("sort_order", len(config["form_fields"])),
                }
            )
    else:
        schema = workflow_blueprint_report_schema(normalized) or DEFAULT_TASK_REPORT_SCHEMA
        narrative = schema.get("narrative") or {}
        attachment = schema.get("attachment") or {}
        config["report_narrative_enabled"] = bool(narrative.get("enabled", True))
        config["report_narrative_required"] = bool(narrative.get("required", True))
        config["report_narrative_label"] = str(narrative.get("label") or "Báo cáo lời tổng hợp").strip()[:255]
        config["report_narrative_target_type"] = str(narrative.get("target_type") or "all").strip().lower() or "all"
        config["report_narrative_unit_domains"] = _normalize_report_target_domains(narrative.get("target_unit_domains") or [])
        config["report_narrative_role_ids"] = _normalize_report_target_ids(narrative.get("target_role_ids") or [])
        config["report_narrative_user_ids"] = _normalize_report_target_ids(narrative.get("target_user_ids") or [])
        config["report_attachment_enabled"] = bool(attachment.get("enabled"))
        config["report_attachment_required"] = bool(attachment.get("required"))
        config["report_attachment_label"] = str(attachment.get("label") or "Tệp minh chứng").strip()[:255]
        config["report_attachment_target_type"] = str(attachment.get("target_type") or "all").strip().lower() or "all"
        config["report_attachment_unit_domains"] = _normalize_report_target_domains(attachment.get("target_unit_domains") or [])
        config["report_attachment_role_ids"] = _normalize_report_target_ids(attachment.get("target_role_ids") or [])
        config["report_attachment_user_ids"] = _normalize_report_target_ids(attachment.get("target_user_ids") or [])
        used_keys = set()
        for index, field in enumerate(schema.get("fields") or []):
            field_key = str(field.get("key") or "").strip() or _task_import_field_key(
                field.get("label") or "",
                index,
                used_keys,
                "report",
            )
            used_keys.add(field_key)
            config["report_fields"].append(
                {
                    "key": field_key,
                    "label": str(field.get("label") or "").strip()[:255],
                    "type": str(field.get("type") or "text").strip().lower(),
                    "required": bool(field.get("required")),
                    "placeholder": str(field.get("placeholder") or "").strip()[:255],
                    "help_text": str(field.get("help_text") or "").strip()[:255],
                    "target_type": str(field.get("target_type") or "all").strip().lower() or "all",
                    "target_unit_domains": _normalize_report_target_domains(field.get("target_unit_domains") or []),
                    "target_role_ids": _normalize_report_target_ids(field.get("target_role_ids") or []),
                    "target_user_ids": _normalize_report_target_ids(field.get("target_user_ids") or []),
                    "sort_order": index,
                }
            )
    return config

def _task_import_draft_blueprint(draft):
    return _json_loads_safe(getattr(draft, "workflow_blueprint_json", None), {})

def _task_import_draft_working_config(draft):
    config = _json_loads_safe(getattr(draft, "working_config_json", None), {})
    if config:
        return config
    blueprint = _task_import_draft_blueprint(draft)
    if not blueprint:
        return {}
    return _task_import_working_config_from_blueprint(
        blueprint,
        source_type=getattr(draft, "source_type", ""),
        source_name=getattr(draft, "source_name", ""),
        source_ref=getattr(draft, "source_ref", ""),
    )

def _task_import_parse_id_csv(raw_value):
    return sorted({int(value) for value in str(raw_value or "").split(",") if value.strip().isdigit()})

def _task_import_working_assign_type(value, default=""):
    normalized = str(value or "").strip().lower()
    if normalized in {"unit", "role", "user"}:
        return normalized
    return default

def _task_import_assignment_has_targets(assign_type, unit_domains=None, role_ids=None, user_ids=None, fallback_domain=""):
    normalized = _task_import_working_assign_type(assign_type)
    if normalized == "role":
        return bool([int(role_id) for role_id in (role_ids or []) if str(role_id).isdigit()])
    if normalized == "user":
        return bool([int(user_id) for user_id in (user_ids or []) if str(user_id).isdigit()])
    if normalized == "unit":
        domains = [str(value or "").strip() for value in (unit_domains or []) if str(value or "").strip()]
        return bool(domains or str(fallback_domain or "").strip())
    return False

def _task_import_scope_from_form(form, prefix):
    assign_type = _task_import_working_assign_type(form.get(f"{prefix}_assign_type"), "unit")
    unit_domains = _requested_unit_domains(form, field_name=f"{prefix}_unit_domains", fallback_field=f"{prefix}_unit_domain")
    role_ids = sorted({int(role_id) for role_id in form.getlist(f"{prefix}_role_ids") if str(role_id).isdigit()})
    user_ids = sorted({int(uid) for uid in form.getlist(f"{prefix}_user_ids") if str(uid).isdigit()})
    return {
        "assign_type": assign_type,
        "unit_domains": unit_domains,
        "role_ids": role_ids,
        "user_ids": user_ids,
    }

def _task_import_summary_text(config):
    title = str(config.get("title") or "").strip()
    summary = str(config.get("summary") or "").strip()
    collection_mode = str(config.get("collection_mode") or "").strip()
    if summary:
        return summary
    if collection_mode == "outline":
        titles = [item.get("title") for item in config.get("items", []) if str(item.get("title") or "").strip()]
        if titles:
            preview = ", ".join(titles[:3])
            remainder = max(len(titles) - 3, 0)
            text = f"Đợt điều hành gồm {len(titles)} đầu mục. Trọng tâm: {preview}"
            if remainder:
                text += f" và {remainder} đầu mục khác."
            return text
    if collection_mode == "form":
        labels = [field.get("field_label") for field in config.get("form_fields", []) if str(field.get("field_label") or "").strip()]
        if labels:
            return "Biểu mẫu thu thập: " + ", ".join(labels[:5])
    if collection_mode == "file":
        labels = [field.get("label") for field in config.get("report_fields", []) if str(field.get("label") or "").strip()]
        if labels:
            return "Chỉ tiêu báo cáo: " + ", ".join(labels[:5])
    return title

def _parse_task_import_outline_items_from_form(form):
    titles = form.getlist("item_title")
    guide_texts = form.getlist("item_guide_text")
    report_kinds = form.getlist("item_report_kind")
    attachment_indexes = {value for value in form.getlist("item_attachment_required")}
    assign_types = form.getlist("item_assign_type")
    unit_domains_values = form.getlist("item_unit_domains")
    role_ids_values = form.getlist("item_role_ids")
    user_ids_values = form.getlist("item_user_ids")
    items = []
    seen = set()

    for index, raw_title in enumerate(titles):
        title = _clean_outline_title(raw_title)
        if not title:
            continue
        dedupe_key = title.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        report_kind = str(report_kinds[index] if index < len(report_kinds) else "narrative").strip().lower()
        if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
            report_kind = "narrative"
        raw_unit_domains = str(unit_domains_values[index] if index < len(unit_domains_values) else "").strip()
        unit_domains = _requested_unit_domains(
            MultiDict([("child_domains", value.strip()) for value in raw_unit_domains.split(",") if value.strip()])
        )
        items.append(
            {
                "title": title[:255],
                "guide_text": str(guide_texts[index] if index < len(guide_texts) else "").strip()[:2000],
                "report_kind": report_kind,
                "attachment_required": str(index) in attachment_indexes,
                "assign_type": _task_import_working_assign_type(assign_types[index] if index < len(assign_types) else ""),
                "unit_domains": unit_domains,
                "role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                "user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
                "sort_order": len(items),
            }
        )
    return items

def _parse_task_import_form_fields_from_form(form):
    labels = form.getlist("form_field_label")
    keys = form.getlist("form_field_key")
    field_types = form.getlist("form_field_type")
    option_texts = form.getlist("form_field_options")
    required_indexes = {value for value in form.getlist("form_field_required")}
    target_types = form.getlist("form_field_target_type")
    unit_domains_values = form.getlist("form_field_target_unit_domains")
    role_ids_values = form.getlist("form_field_target_role_ids")
    user_ids_values = form.getlist("form_field_target_user_ids")
    fields = []
    used_keys = set()
    for index, raw_label in enumerate(labels):
        label = str(raw_label or "").strip()
        if not label:
            continue
        field_type = _normalize_task_form_field_type(field_types[index] if index < len(field_types) else "text")
        raw_key = str(keys[index] if index < len(keys) else "").strip()
        field_key = raw_key or _task_import_field_key(label, index, used_keys, "field")
        if field_key in used_keys:
            field_key = _task_import_field_key(label, index, used_keys, "field")
        used_keys.add(field_key)
        option_text = str(option_texts[index] if index < len(option_texts) else "").strip()
        target_config = _normalize_report_target_config(
            {
                "target_type": target_types[index] if index < len(target_types) else "all",
                "target_unit_domains": unit_domains_values[index] if index < len(unit_domains_values) else "",
                "target_role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                "target_user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
            }
        )
        fields.append(
            {
                "field_key": field_key[:100],
                "field_label": label[:255],
                "field_type": field_type,
                "field_options_text": option_text,
                "is_required": str(index) in required_indexes,
                "target_type": target_config.get("target_type") or "all",
                "target_unit_domains": target_config.get("target_unit_domains") or [],
                "target_role_ids": target_config.get("target_role_ids") or [],
                "target_user_ids": target_config.get("target_user_ids") or [],
                "sort_order": len(fields),
            }
        )
    return fields

def _parse_task_import_report_fields_from_form(form):
    labels = form.getlist("report_field_label")
    keys = form.getlist("report_field_key")
    field_types = form.getlist("report_field_type")
    placeholders = form.getlist("report_field_placeholder")
    help_texts = form.getlist("report_field_help_text")
    required_indexes = {value for value in form.getlist("report_field_required")}
    target_types = form.getlist("report_field_target_type")
    unit_domains_values = form.getlist("report_field_target_unit_domains")
    role_ids_values = form.getlist("report_field_target_role_ids")
    user_ids_values = form.getlist("report_field_target_user_ids")
    fields = []
    used_keys = set()
    for index, raw_label in enumerate(labels):
        label = str(raw_label or "").strip()
        if not label:
            continue
        field_type = str(field_types[index] if index < len(field_types) else "text").strip().lower()
        if field_type not in TASK_REPORT_ALLOWED_FIELD_TYPES:
            field_type = "text"
        raw_key = str(keys[index] if index < len(keys) else "").strip()
        field_key = raw_key or _task_import_field_key(label, index, used_keys, "report")
        if field_key in used_keys:
            field_key = _task_import_field_key(label, index, used_keys, "report")
        used_keys.add(field_key)
        fields.append(
            {
                "key": field_key[:100],
                "label": label[:255],
                "type": field_type,
                "required": str(index) in required_indexes,
                "placeholder": str(placeholders[index] if index < len(placeholders) else "").strip()[:255],
                "help_text": str(help_texts[index] if index < len(help_texts) else "").strip()[:255],
                "target_type": _normalize_report_target_config(
                    {
                        "target_type": target_types[index] if index < len(target_types) else "all",
                        "target_unit_domains": unit_domains_values[index] if index < len(unit_domains_values) else "",
                        "target_role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                        "target_user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
                    }
                )["target_type"],
                "target_unit_domains": _normalize_report_target_domains(unit_domains_values[index] if index < len(unit_domains_values) else ""),
                "target_role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                "target_user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
                "sort_order": len(fields),
            }
        )
    return fields

def _parse_task_import_working_config_from_form(draft, form):
    current_config = _task_import_draft_working_config(draft)
    config = dict(current_config or {})
    collection_mode = str(config.get("collection_mode") or "").strip().lower() or "outline"
    task_fields = _task_field_options()
    pro_units = _task_domain_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()

    config["title"] = str(form.get("title") or "").strip()[:255]
    config["summary"] = str(form.get("summary") or "").strip()[:4000]
    config["category"] = canonicalize_category_value(form.get("category") or "", task_fields, prefer_stable=True)
    config["domain"] = canonicalize_category_value(form.get("domain") or "", pro_units, prefer_stable=True)
    config["task_type"] = canonicalize_category_value(form.get("task_type") or "Công việc thường xuyên", task_types, prefer_stable=True)
    config["priority"] = canonicalize_category_value(form.get("priority") or "Trung bình", priority_items, prefer_stable=True)
    config["deadline"] = str(form.get("deadline") or "").strip()[:20]

    scope = _task_import_scope_from_form(form, "draft")
    config.update(scope)

    config["manager_scope_mode"] = str(form.get("manager_scope_mode") or "none").strip().lower()
    config["manager_role_ids"] = sorted({int(role_id) for role_id in form.getlist("manager_role_ids") if str(role_id).isdigit()})
    config["manager_user_ids"] = sorted({int(uid) for uid in form.getlist("manager_user_ids") if str(uid).isdigit()})
    config["viewer_scope_mode"] = str(form.get("viewer_scope_mode") or "none").strip().lower()
    config["viewer_role_ids"] = sorted({int(role_id) for role_id in form.getlist("viewer_role_ids") if str(role_id).isdigit()})
    config["viewer_user_ids"] = sorted({int(uid) for uid in form.getlist("viewer_user_ids") if str(uid).isdigit()})

    if collection_mode == "outline":
        config["items"] = _parse_task_import_outline_items_from_form(form)
    elif collection_mode == "form":
        config["form_fields"] = _parse_task_import_form_fields_from_form(form)
    else:
        config["report_narrative_enabled"] = _report_checkbox_value(form.get("report_narrative_enabled"))
        config["report_narrative_required"] = _report_checkbox_value(form.get("report_narrative_required"))
        config["report_narrative_label"] = str(form.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip()[:255]
        config["report_narrative_target_type"] = str(form.get("report_narrative_target_type") or "all").strip().lower()
        config["report_narrative_unit_domains"] = _requested_unit_domains(form, field_name="report_narrative_unit_domains", fallback_field="")
        config["report_narrative_role_ids"] = sorted({int(role_id) for role_id in form.getlist("report_narrative_role_ids") if str(role_id).isdigit()})
        config["report_narrative_user_ids"] = sorted({int(uid) for uid in form.getlist("report_narrative_user_ids") if str(uid).isdigit()})
        config["report_attachment_enabled"] = _report_checkbox_value(form.get("report_attachment_enabled"))
        config["report_attachment_required"] = _report_checkbox_value(form.get("report_attachment_required"))
        config["report_attachment_label"] = str(form.get("report_attachment_label") or "Tệp minh chứng").strip()[:255]
        config["report_attachment_target_type"] = str(form.get("report_attachment_target_type") or "all").strip().lower()
        config["report_attachment_unit_domains"] = _requested_unit_domains(form, field_name="report_attachment_unit_domains", fallback_field="")
        config["report_attachment_role_ids"] = sorted({int(role_id) for role_id in form.getlist("report_attachment_role_ids") if str(role_id).isdigit()})
        config["report_attachment_user_ids"] = sorted({int(uid) for uid in form.getlist("report_attachment_user_ids") if str(uid).isdigit()})
        config["report_fields"] = _parse_task_import_report_fields_from_form(form)

    if not config.get("summary"):
        config["summary"] = _task_import_summary_text(config)
    return config

def _task_import_report_schema_from_config(config):
    if str(config.get("collection_mode") or "").strip().lower() != "file":
        return None
    raw_schema = {
        "enabled": True,
        "narrative": {
            "enabled": bool(config.get("report_narrative_enabled", True)),
            "required": bool(config.get("report_narrative_required", True)),
            "label": str(config.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip(),
            "target_type": str(config.get("report_narrative_target_type") or "all").strip().lower(),
            "target_unit_domains": _normalize_report_target_domains(config.get("report_narrative_unit_domains") or []),
            "target_role_ids": _normalize_report_target_ids(config.get("report_narrative_role_ids") or []),
            "target_user_ids": _normalize_report_target_ids(config.get("report_narrative_user_ids") or []),
        },
        "attachment": {
            "enabled": bool(config.get("report_attachment_enabled")),
            "required": bool(config.get("report_attachment_required")),
            "label": str(config.get("report_attachment_label") or "Tệp minh chứng").strip(),
            "target_type": str(config.get("report_attachment_target_type") or "all").strip().lower(),
            "target_unit_domains": _normalize_report_target_domains(config.get("report_attachment_unit_domains") or []),
            "target_role_ids": _normalize_report_target_ids(config.get("report_attachment_role_ids") or []),
            "target_user_ids": _normalize_report_target_ids(config.get("report_attachment_user_ids") or []),
        },
        "fields": [
            {
                "key": field.get("key"),
                "label": field.get("label"),
                "type": field.get("type"),
                "required": bool(field.get("required")),
                "placeholder": field.get("placeholder"),
                "help_text": field.get("help_text"),
                "target_type": str(field.get("target_type") or "all").strip().lower(),
                "target_unit_domains": _normalize_report_target_domains(field.get("target_unit_domains") or []),
                "target_role_ids": _normalize_report_target_ids(field.get("target_role_ids") or []),
                "target_user_ids": _normalize_report_target_ids(field.get("target_user_ids") or []),
            }
            for field in (config.get("report_fields") or [])
            if str(field.get("label") or "").strip()
        ],
    }
    return _normalize_task_report_schema(raw_schema)

def _task_import_form_field_defs_from_config(config):
    field_defs = []
    used_keys = set()
    for index, field in enumerate(config.get("form_fields") or []):
        label = str(field.get("field_label") or "").strip()
        if not label:
            continue
        field_key = str(field.get("field_key") or "").strip()
        if not field_key or field_key in used_keys:
            field_key = _task_import_field_key(label, index, used_keys, "field")
        used_keys.add(field_key)
        field_type = _normalize_task_form_field_type(field.get("field_type") or "text")
        field_defs.append(
            {
                "field_key": field_key[:100],
                "field_label": label[:255],
                "field_type": field_type,
                "field_options_json": _task_import_form_field_options_json(
                    field_type,
                    field.get("field_options_text"),
                    {
                        "target_type": field.get("target_type") or "all",
                        "target_unit_domains": field.get("target_unit_domains") or [],
                        "target_role_ids": field.get("target_role_ids") or [],
                        "target_user_ids": field.get("target_user_ids") or [],
                    },
                ),
                "sort_order": len(field_defs),
                "is_required": bool(field.get("is_required")),
            }
        )
    return field_defs

def _task_form_field_db_kwargs(field_def):
    return {
        "field_key": str(field_def.get("field_key") or "").strip()[:100],
        "field_label": str(field_def.get("field_label") or "").strip()[:255],
        "field_type": _normalize_task_form_field_type(field_def.get("field_type") or "text"),
        "field_options_json": field_def.get("field_options_json"),
        "sort_order": int(field_def.get("sort_order") or 0),
        "is_required": bool(field_def.get("is_required")),
    }

def _task_import_blueprint_from_config(config):
    collection_mode = str(config.get("collection_mode") or "").strip().lower()
    raw_blueprint = {
        "title": str(config.get("title") or "").strip(),
        "summary": str(config.get("summary") or "").strip(),
        "source_kind": str(config.get("source_kind") or "custom").strip().lower(),
        "collection_mode": collection_mode,
    }
    if collection_mode == "outline":
        raw_blueprint["items"] = [
            {
                "title": item.get("title"),
                "guide_text": item.get("guide_text"),
                "report_kind": item.get("report_kind"),
                "attachment_required": bool(item.get("attachment_required")),
            }
            for item in (config.get("items") or [])
            if str(item.get("title") or "").strip()
        ]
    elif collection_mode == "form":
        raw_blueprint["form_fields"] = [
            {
                "label": field.get("field_label"),
                "type": field.get("field_type"),
                "required": bool(field.get("is_required")),
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
                "options": (
                    [item.strip() for item in str(field.get("field_options_text") or "").splitlines() if item.strip()]
                    if str(field.get("field_type") or "").strip().lower() in {"radio", "checkbox"}
                    else [item.strip() for item in str(field.get("field_options_text") or "").split(",") if item.strip()]
                ),
            }
            for field in (config.get("form_fields") or [])
            if str(field.get("field_label") or "").strip()
        ]
    elif collection_mode == "file":
        raw_blueprint["report_schema"] = {
            "enabled": True,
            "narrative": {
                "enabled": bool(config.get("report_narrative_enabled", True)),
                "required": bool(config.get("report_narrative_required", True)),
                "label": config.get("report_narrative_label"),
                "target_type": config.get("report_narrative_target_type") or "all",
                "target_unit_domains": config.get("report_narrative_unit_domains") or [],
                "target_role_ids": config.get("report_narrative_role_ids") or [],
                "target_user_ids": config.get("report_narrative_user_ids") or [],
            },
            "attachment": {
                "enabled": bool(config.get("report_attachment_enabled")),
                "required": bool(config.get("report_attachment_required")),
                "label": config.get("report_attachment_label"),
                "target_type": config.get("report_attachment_target_type") or "all",
                "target_unit_domains": config.get("report_attachment_unit_domains") or [],
                "target_role_ids": config.get("report_attachment_role_ids") or [],
                "target_user_ids": config.get("report_attachment_user_ids") or [],
            },
            "fields": [
                {
                    "key": field.get("key"),
                    "label": field.get("label"),
                    "type": field.get("type"),
                    "required": bool(field.get("required")),
                    "placeholder": field.get("placeholder"),
                    "help_text": field.get("help_text"),
                    "target_type": field.get("target_type") or "all",
                    "target_unit_domains": field.get("target_unit_domains") or [],
                    "target_role_ids": field.get("target_role_ids") or [],
                    "target_user_ids": field.get("target_user_ids") or [],
                }
                for field in (config.get("report_fields") or [])
                if str(field.get("label") or "").strip()
            ],
        }
    return normalize_task_workflow_blueprint(raw_blueprint)

def _task_import_config_stats(config):
    mode = str(config.get("collection_mode") or "").strip().lower()
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    stats = {
        "mode": mode,
        "item_count": 0,
        "field_count": 0,
        "report_field_count": 0,
        "unassigned_count": 0,
    }
    if mode == "outline":
        items = [item for item in (config.get("items") or []) if str(item.get("title") or "").strip()]
        stats["item_count"] = len(items)
        stats["unassigned_count"] = sum(
            1
            for item in items
            if not _task_import_assignment_has_targets(
                item.get("assign_type"),
                unit_domains=item.get("unit_domains"),
                role_ids=item.get("role_ids"),
                user_ids=item.get("user_ids"),
                fallback_domain=fallback_domain,
            )
        )
    elif mode == "form":
        fields = [field for field in (config.get("form_fields") or []) if str(field.get("field_label") or "").strip()]
        stats["field_count"] = len(fields)
        stats["unassigned_count"] = 0 if _task_import_assignment_has_targets(
            config.get("assign_type"),
            unit_domains=config.get("unit_domains"),
            role_ids=config.get("role_ids"),
            user_ids=config.get("user_ids"),
            fallback_domain=fallback_domain,
        ) else 1
    else:
        report_fields = [field for field in (config.get("report_fields") or []) if str(field.get("label") or "").strip()]
        stats["report_field_count"] = len(report_fields)
        stats["unassigned_count"] = 0 if _task_import_assignment_has_targets(
            config.get("assign_type"),
            unit_domains=config.get("unit_domains"),
            role_ids=config.get("role_ids"),
            user_ids=config.get("user_ids"),
            fallback_domain=fallback_domain,
        ) else 1
    return stats

def _task_import_user_unit_label(user, unit_lookup=None):
    unit_lookup = unit_lookup or {}
    raw_value = getattr(user, "unit_area", None) or getattr(user, "unit_key", None) or ""
    canonical_value = canonicalize_category_value(raw_value or "", _task_domain_options(), prefer_stable=True)
    if canonical_value and unit_lookup.get(canonical_value):
        return unit_lookup.get(canonical_value)
    if raw_value:
        return str(raw_value).strip()
    return "Chưa có đơn vị"

def _task_import_scope_target_labels(assign_type, unit_domains=None, role_ids=None, user_ids=None, fallback_domain="", unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    normalized = _task_import_working_assign_type(assign_type)
    if normalized == "unit":
        raw_domains = list(unit_domains or [])
        if not raw_domains and str(fallback_domain or "").strip():
            raw_domains = [fallback_domain]
        labels = [unit_lookup.get(domain) or domain for domain in raw_domains if str(domain or "").strip()]
        return labels
    if normalized == "role":
        return [role_lookup.get(int(role_id), str(role_id)) for role_id in (role_ids or []) if str(role_id).isdigit()]
    if normalized == "user":
        return [user_lookup.get(int(user_id), str(user_id)) for user_id in (user_ids or []) if str(user_id).isdigit()]
    return []

def _task_import_scope_summary(assign_type, unit_domains=None, role_ids=None, user_ids=None, fallback_domain="", unit_lookup=None, role_lookup=None, user_lookup=None):
    raw_type = str(assign_type or "").strip().lower()
    if raw_type == "all":
        return {
            "assign_type": "all",
            "mode_label": TASK_IMPORT_TARGET_TYPE_LABELS["all"],
            "labels": [],
            "text": TASK_IMPORT_TARGET_TYPE_LABELS["all"],
        }
    normalized = _task_import_working_assign_type(raw_type)
    labels = _task_import_scope_target_labels(
        normalized,
        unit_domains=unit_domains,
        role_ids=role_ids,
        user_ids=user_ids,
        fallback_domain=fallback_domain,
        unit_lookup=unit_lookup,
        role_lookup=role_lookup,
        user_lookup=user_lookup,
    )
    mode_label = TASK_IMPORT_ASSIGN_TYPE_LABELS.get(normalized, "Chưa cấu hình")
    if not normalized:
        return {
            "assign_type": "",
            "mode_label": "Chưa cấu hình",
            "labels": [],
            "text": "Chưa gán người thực hiện",
        }
    if labels:
        return {
            "assign_type": normalized,
            "mode_label": mode_label,
            "labels": labels,
            "text": f"{mode_label}: {', '.join(labels)}",
        }
    return {
        "assign_type": normalized,
        "mode_label": mode_label,
        "labels": [],
        "text": f"{mode_label}: chưa có người nhận hợp lệ",
    }

def _task_import_preview_recipient_entry(user, unit_lookup=None, role_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    role_id = getattr(user, "role_id", None)
    return {
        "key": f"user:{user.id}",
        "user_id": user.id,
        "user_name": getattr(user, "fullname", None) or getattr(user, "username", None) or f"User {user.id}",
        "username": getattr(user, "username", None) or "",
        "unit_name": _task_import_user_unit_label(user, unit_lookup=unit_lookup),
        "role_name": role_lookup.get(role_id, "") if role_id else "",
        "outline_items": [],
        "form_fields": [],
        "file_sections": [],
        "delivery_labels": [],
        "warnings": [],
        "item_count": 0,
        "field_count": 0,
        "section_count": 0,
    }

def _task_import_preview_warning_text(message):
    text = str(message or "").strip()
    return text[:400] if text else "Cấu hình người nhận chưa hợp lệ."

def _task_import_preview_submission_group_info(assign_type, user, role_lookup=None, unit_lookup=None):
    role_lookup = role_lookup or {}
    unit_lookup = unit_lookup or {}
    normalized = _task_import_working_assign_type(assign_type)
    user_name = getattr(user, "fullname", None) or getattr(user, "username", None) or f"User {getattr(user, 'id', '')}"
    unit_name = _task_import_user_unit_label(user, unit_lookup=unit_lookup)
    unit_identity = _task_unit_identity(user)
    unit_key = unit_identity.get("unit_key") or remove_accents(unit_name).strip().lower() or f"user:{getattr(user, 'id', 0)}"
    role_id = int(getattr(user, "role_id", None) or 0)
    role_name = role_lookup.get(role_id, "") if role_id else ""

    if normalized == "unit":
        return {
            "mode": "unit",
            "mode_label": "Nộp theo đơn vị",
            "group_key": f"unit:{unit_key}",
            "group_label": f"Đơn vị {unit_name}",
            "member_label": user_name,
        }
    if normalized == "role":
        role_key = role_id or 0
        role_title = role_name or "Chưa phân vai trò"
        return {
            "mode": "role",
            "mode_label": "Nộp theo vai trò",
            "group_key": f"role:{role_key}:unit:{unit_key}",
            "group_label": f"{role_title} - {unit_name}",
            "member_label": user_name,
        }
    return {
        "mode": "user",
        "mode_label": "Nộp cá nhân",
        "group_key": f"user:{int(getattr(user, 'id', 0) or 0)}",
        "group_label": user_name,
        "member_label": user_name,
    }

def _task_import_preview_unit_groups(mode, cards):
    mode_key = str(mode or "").strip().lower()
    unit_map = {}

    def ensure_group(card):
        unit_name = str(card.get("unit_name") or "Chưa có đơn vị").strip() or "Chưa có đơn vị"
        return unit_map.setdefault(
            unit_name,
            {
                "unit_name": unit_name,
                "recipient_count": 0,
                "item_count": 0,
                "field_count": 0,
                "section_count": 0,
                "warning_count": 0,
                "recipient_names": [],
                "delivery_labels": [],
                "payload_labels": [],
            },
        )

    def push_unique(values, value, limit=5):
        text = str(value or "").strip()
        if not text or text in values:
            return
        values.append(text)
        if len(values) > limit:
            del values[limit:]

    for card in cards or []:
        group = ensure_group(card)
        group["recipient_count"] += 1
        group["item_count"] += int(card.get("item_count") or 0)
        group["field_count"] += int(card.get("field_count") or 0)
        group["section_count"] += int(card.get("section_count") or 0)
        group["warning_count"] += len(card.get("warnings") or [])
        push_unique(group["recipient_names"], card.get("user_name"), limit=4)
        for label in (card.get("delivery_labels") or []):
            push_unique(group["delivery_labels"], label, limit=4)
        if mode_key == "outline":
            for item in (card.get("outline_items") or []):
                push_unique(group["payload_labels"], item.get("title"))
        elif mode_key == "form":
            for field in (card.get("form_fields") or []):
                push_unique(group["payload_labels"], field.get("label"))
        else:
            for section in (card.get("file_sections") or []):
                push_unique(group["payload_labels"], section.get("label"))

    return sorted(
        unit_map.values(),
        key=lambda item: (-item["recipient_count"], -item["item_count"] - item["field_count"] - item["section_count"], remove_accents(item["unit_name"]).lower()),
    )

def _task_import_preview_submission_groups(mode, cards):
    mode_key = str(mode or "").strip().lower()
    group_map = {}

    def ensure_group(group_key, group_label, mode_label):
        return group_map.setdefault(
            group_key,
            {
                "group_key": group_key,
                "group_label": group_label,
                "mode_label": mode_label,
                "member_names": [],
                "payload_labels": [],
                "payload_count": 0,
                "recipient_count": 0,
            },
        )

    def push_unique(values, value, limit=6):
        text = str(value or "").strip()
        if not text or text in values:
            return
        values.append(text)
        if len(values) > limit:
            del values[limit:]

    def add_payload(group, payload_label):
        text = str(payload_label or "").strip()
        if not text:
            return
        group["payload_count"] += 1
        push_unique(group["payload_labels"], text)

    for card in cards or []:
        if mode_key == "outline":
            for item in (card.get("outline_items") or []):
                group_key = str(item.get("submission_group_key") or "").strip()
                if not group_key:
                    continue
                group = ensure_group(
                    group_key,
                    item.get("submission_group_label") or card.get("user_name") or "Nhóm nộp",
                    item.get("submission_mode_label") or "Nộp cá nhân",
                )
                push_unique(group["member_names"], card.get("user_name"))
                group["recipient_count"] = len(group["member_names"])
                add_payload(group, item.get("title"))
        elif mode_key == "form":
            group_key = str(card.get("submission_group_key") or "").strip()
            if not group_key:
                continue
            group = ensure_group(
                group_key,
                card.get("submission_group_label") or card.get("user_name") or "Nhóm nộp",
                card.get("submission_mode_label") or "Nộp cá nhân",
            )
            push_unique(group["member_names"], card.get("user_name"))
            group["recipient_count"] = len(group["member_names"])
            for field in (card.get("form_fields") or []):
                add_payload(group, field.get("label"))
        else:
            group_key = str(card.get("submission_group_key") or "").strip()
            if not group_key:
                continue
            group = ensure_group(
                group_key,
                card.get("submission_group_label") or card.get("user_name") or "Nhóm nộp",
                card.get("submission_mode_label") or "Nộp cá nhân",
            )
            push_unique(group["member_names"], card.get("user_name"))
            group["recipient_count"] = len(group["member_names"])
            for section in (card.get("file_sections") or []):
                add_payload(group, section.get("label"))

    return sorted(
        group_map.values(),
        key=lambda item: (-int(item["recipient_count"] or 0), -int(item["payload_count"] or 0), remove_accents(item["group_label"]).lower()),
    )

def _task_import_outline_recipient_preview(config, unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    recipients = {}
    warnings = []

    for item in (config.get("items") or []):
        title = _clean_outline_title(item.get("title"))
        if not title:
            continue
        assign_type = _task_import_working_assign_type(item.get("assign_type"))
        scope_summary = _task_import_scope_summary(
            assign_type,
            unit_domains=item.get("unit_domains") or [],
            role_ids=item.get("role_ids") or [],
            user_ids=item.get("user_ids") or [],
            fallback_domain=fallback_domain,
            unit_lookup=unit_lookup,
            role_lookup=role_lookup,
            user_lookup=user_lookup,
        )
        assignees, error_message = _resolve_assignees_by_mode(
            assign_type,
            domain=fallback_domain,
            unit_domains=item.get("unit_domains") or [],
            target_ids=item.get("user_ids") or [],
            assignee_role_ids=item.get("role_ids") or [],
        )
        if error_message or not assignees:
            warnings.append(
                {
                    "scope": title,
                    "message": _task_import_preview_warning_text(
                        error_message or "Đầu mục này chưa có người nhận hợp lệ."
                    ),
                }
            )
            continue
        row_preview = {
            "title": title,
            "guide_text": str(item.get("guide_text") or "").strip(),
            "report_kind": str(item.get("report_kind") or "narrative").strip().lower() or "narrative",
            "report_kind_label": TASK_IMPORT_REPORT_KIND_LABELS.get(
                str(item.get("report_kind") or "narrative").strip().lower(),
                "Báo cáo lời",
            ),
            "attachment_required": bool(item.get("attachment_required")),
            "delivery_text": scope_summary["text"],
            "delivery_mode": scope_summary["mode_label"],
            "sort_order": int(item.get("sort_order") or 0),
        }
        for assignee in assignees:
            submission_group = _task_import_preview_submission_group_info(
                assign_type,
                assignee,
                role_lookup=role_lookup,
                unit_lookup=unit_lookup,
            )
            entry = recipients.setdefault(
                assignee.id,
                _task_import_preview_recipient_entry(assignee, unit_lookup=unit_lookup, role_lookup=role_lookup),
            )
            preview_payload = dict(
                row_preview,
                submission_group_key=submission_group["group_key"],
                submission_group_label=submission_group["group_label"],
                submission_mode_label=submission_group["mode_label"],
            )
            entry["outline_items"].append(preview_payload)
            if scope_summary["text"] not in entry["delivery_labels"]:
                entry["delivery_labels"].append(scope_summary["text"])

    cards = sorted(
        recipients.values(),
        key=lambda item: (remove_accents(item["unit_name"]).lower(), remove_accents(item["user_name"]).lower()),
    )
    for card in cards:
        card["outline_items"].sort(key=lambda item: (item["sort_order"], remove_accents(item["title"]).lower()))
        card["item_count"] = len(card["outline_items"])
    return {
        "mode": "outline",
        "recipient_count": len(cards),
        "cards": cards,
        "warnings": warnings,
        "unit_groups": _task_import_preview_unit_groups("outline", cards),
        "submission_groups": _task_import_preview_submission_groups("outline", cards),
    }

def _task_import_form_recipient_preview(config, unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    scope_summary = _task_import_scope_summary(
        config.get("assign_type"),
        unit_domains=config.get("unit_domains") or [],
        role_ids=config.get("role_ids") or [],
        user_ids=config.get("user_ids") or [],
        fallback_domain=fallback_domain,
        unit_lookup=unit_lookup,
        role_lookup=role_lookup,
        user_lookup=user_lookup,
    )
    assignees, error_message = _resolve_assignees_by_mode(
        _task_import_working_assign_type(config.get("assign_type"), "unit"),
        domain=fallback_domain,
        unit_domains=config.get("unit_domains") or [],
        target_ids=config.get("user_ids") or [],
        assignee_role_ids=config.get("role_ids") or [],
    )
    warnings = []
    if error_message:
        warnings.append({"scope": "Phân công toàn nhiệm vụ", "message": _task_import_preview_warning_text(error_message)})
    fields = [field for field in (config.get("form_fields") or []) if str(field.get("field_label") or "").strip()]
    cards = []
    for assignee in assignees:
        entry = _task_import_preview_recipient_entry(assignee, unit_lookup=unit_lookup, role_lookup=role_lookup)
        entry["delivery_labels"] = [scope_summary["text"]]
        submission_group = _task_import_preview_submission_group_info(
            config.get("assign_type"),
            assignee,
            role_lookup=role_lookup,
            unit_lookup=unit_lookup,
        )
        entry["submission_group_key"] = submission_group["group_key"]
        entry["submission_group_label"] = submission_group["group_label"]
        entry["submission_mode_label"] = submission_group["mode_label"]
        for field in fields:
            field_config = {
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
            }
            if not _task_report_item_visible_for_user(field_config, assignee):
                continue
            target_summary = _task_import_scope_summary(
                field.get("target_type") or "all",
                unit_domains=field.get("target_unit_domains") or [],
                role_ids=field.get("target_role_ids") or [],
                user_ids=field.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["form_fields"].append(
                {
                    "label": str(field.get("field_label") or "").strip(),
                    "field_type": str(field.get("field_type") or "text").strip().lower() or "text",
                    "field_type_label": TASK_IMPORT_FIELD_TYPE_LABELS.get(
                        str(field.get("field_type") or "text").strip().lower(),
                        "Văn bản",
                    ),
                    "is_required": bool(field.get("is_required")),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": int(field.get("sort_order") or 0),
                }
            )
        entry["form_fields"].sort(key=lambda item: (item["sort_order"], remove_accents(item["label"]).lower()))
        entry["field_count"] = len(entry["form_fields"])
        if not entry["field_count"]:
            entry["warnings"].append("Người nhận này được giao nhiệm vụ nhưng hiện chưa thấy trường biểu mẫu nào.")
        cards.append(entry)

    cards.sort(key=lambda item: (remove_accents(item["unit_name"]).lower(), remove_accents(item["user_name"]).lower()))
    if not fields:
        warnings.append({"scope": "Biểu mẫu", "message": "Chưa có trường biểu mẫu hợp lệ để phát hành."})
    return {
        "mode": "form",
        "recipient_count": len(cards),
        "cards": cards,
        "warnings": warnings,
        "global_delivery_text": scope_summary["text"],
        "unit_groups": _task_import_preview_unit_groups("form", cards),
        "submission_groups": _task_import_preview_submission_groups("form", cards),
    }

def _task_import_file_recipient_preview(config, unit_lookup=None, role_lookup=None, user_lookup=None):
    unit_lookup = unit_lookup or {}
    role_lookup = role_lookup or {}
    user_lookup = user_lookup or {}
    fallback_domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    scope_summary = _task_import_scope_summary(
        config.get("assign_type"),
        unit_domains=config.get("unit_domains") or [],
        role_ids=config.get("role_ids") or [],
        user_ids=config.get("user_ids") or [],
        fallback_domain=fallback_domain,
        unit_lookup=unit_lookup,
        role_lookup=role_lookup,
        user_lookup=user_lookup,
    )
    assignees, error_message = _resolve_assignees_by_mode(
        _task_import_working_assign_type(config.get("assign_type"), "unit"),
        domain=fallback_domain,
        unit_domains=config.get("unit_domains") or [],
        target_ids=config.get("user_ids") or [],
        assignee_role_ids=config.get("role_ids") or [],
    )
    warnings = []
    if error_message:
        warnings.append({"scope": "Phân công toàn nhiệm vụ", "message": _task_import_preview_warning_text(error_message)})

    narrative_cfg = {
        "enabled": bool(config.get("report_narrative_enabled", True)),
        "required": bool(config.get("report_narrative_required", True)),
        "label": str(config.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip(),
        "target_type": config.get("report_narrative_target_type") or "all",
        "target_unit_domains": config.get("report_narrative_unit_domains") or [],
        "target_role_ids": config.get("report_narrative_role_ids") or [],
        "target_user_ids": config.get("report_narrative_user_ids") or [],
    }
    attachment_cfg = {
        "enabled": bool(config.get("report_attachment_enabled")),
        "required": bool(config.get("report_attachment_required")),
        "label": str(config.get("report_attachment_label") or "Tệp minh chứng").strip(),
        "target_type": config.get("report_attachment_target_type") or "all",
        "target_unit_domains": config.get("report_attachment_unit_domains") or [],
        "target_role_ids": config.get("report_attachment_role_ids") or [],
        "target_user_ids": config.get("report_attachment_user_ids") or [],
    }
    report_fields = [field for field in (config.get("report_fields") or []) if str(field.get("label") or "").strip()]
    cards = []
    for assignee in assignees:
        entry = _task_import_preview_recipient_entry(assignee, unit_lookup=unit_lookup, role_lookup=role_lookup)
        entry["delivery_labels"] = [scope_summary["text"]]
        submission_group = _task_import_preview_submission_group_info(
            config.get("assign_type"),
            assignee,
            role_lookup=role_lookup,
            unit_lookup=unit_lookup,
        )
        entry["submission_group_key"] = submission_group["group_key"]
        entry["submission_group_label"] = submission_group["group_label"]
        entry["submission_mode_label"] = submission_group["mode_label"]
        if narrative_cfg["enabled"] and _task_report_item_visible_for_user(narrative_cfg, assignee):
            target_summary = _task_import_scope_summary(
                narrative_cfg.get("target_type") or "all",
                unit_domains=narrative_cfg.get("target_unit_domains") or [],
                role_ids=narrative_cfg.get("target_role_ids") or [],
                user_ids=narrative_cfg.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["file_sections"].append(
                {
                    "label": narrative_cfg["label"] or "Báo cáo lời tổng hợp",
                    "kind": "narrative",
                    "kind_label": "Báo cáo lời",
                    "type_label": "Đoạn văn",
                    "required": bool(narrative_cfg["required"]),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": 0,
                }
            )
        if attachment_cfg["enabled"] and _task_report_item_visible_for_user(attachment_cfg, assignee):
            target_summary = _task_import_scope_summary(
                attachment_cfg.get("target_type") or "all",
                unit_domains=attachment_cfg.get("target_unit_domains") or [],
                role_ids=attachment_cfg.get("target_role_ids") or [],
                user_ids=attachment_cfg.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["file_sections"].append(
                {
                    "label": attachment_cfg["label"] or "Tệp minh chứng",
                    "kind": "attachment",
                    "kind_label": "Minh chứng",
                    "type_label": "Tệp đính kèm",
                    "required": bool(attachment_cfg["required"]),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": 1,
                }
            )
        for index, field in enumerate(report_fields, start=2):
            field_config = {
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
            }
            if not _task_report_item_visible_for_user(field_config, assignee):
                continue
            target_summary = _task_import_scope_summary(
                field.get("target_type") or "all",
                unit_domains=field.get("target_unit_domains") or [],
                role_ids=field.get("target_role_ids") or [],
                user_ids=field.get("target_user_ids") or [],
                unit_lookup=unit_lookup,
                role_lookup=role_lookup,
                user_lookup=user_lookup,
            )
            entry["file_sections"].append(
                {
                    "label": str(field.get("label") or "").strip(),
                    "kind": "field",
                    "kind_label": "Chỉ tiêu",
                    "type_label": TASK_IMPORT_FIELD_TYPE_LABELS.get(str(field.get("type") or "text").strip().lower(), "Văn bản"),
                    "required": bool(field.get("required")),
                    "target_text": target_summary["text"] if target_summary["assign_type"] else TASK_IMPORT_TARGET_TYPE_LABELS["all"],
                    "sort_order": int(field.get("sort_order") or index),
                }
            )
        entry["file_sections"].sort(key=lambda item: (item["sort_order"], remove_accents(item["label"]).lower()))
        entry["section_count"] = len(entry["file_sections"])
        if not entry["section_count"]:
            entry["warnings"].append("Người nhận này được giao nhiệm vụ nhưng hiện chưa thấy phần báo cáo nào.")
        cards.append(entry)

    cards.sort(key=lambda item: (remove_accents(item["unit_name"]).lower(), remove_accents(item["user_name"]).lower()))
    if not narrative_cfg["enabled"] and not attachment_cfg["enabled"] and not report_fields:
        warnings.append({"scope": "Schema báo cáo", "message": "Chưa có nội dung báo cáo hợp lệ để phát hành."})
    return {
        "mode": "file",
        "recipient_count": len(cards),
        "cards": cards,
        "warnings": warnings,
        "global_delivery_text": scope_summary["text"],
        "unit_groups": _task_import_preview_unit_groups("file", cards),
        "submission_groups": _task_import_preview_submission_groups("file", cards),
    }

def _task_import_recipient_preview(config, users=None, roles=None):
    config = config or {}
    active_users = list(users or [])
    role_rows = list(roles or [])
    unit_lookup = {
        str(item.get("value") or "").strip(): str(item.get("name") or item.get("label") or item.get("value") or "").strip()
        for item in stable_form_category_options(_task_domain_options())
        if str(item.get("value") or "").strip()
    }
    role_lookup = {
        int(role.id): str(role.name or f"Vai trò {role.id}").strip()
        for role in role_rows
        if getattr(role, "id", None)
    }
    user_lookup = {
        int(user.id): str(getattr(user, "fullname", None) or getattr(user, "username", None) or f"User {user.id}").strip()
        for user in active_users
        if getattr(user, "id", None)
    }
    mode = str(config.get("collection_mode") or "").strip().lower()
    if mode == "outline":
        return _task_import_outline_recipient_preview(config, unit_lookup=unit_lookup, role_lookup=role_lookup, user_lookup=user_lookup)
    if mode == "form":
        return _task_import_form_recipient_preview(config, unit_lookup=unit_lookup, role_lookup=role_lookup, user_lookup=user_lookup)
    return _task_import_file_recipient_preview(config, unit_lookup=unit_lookup, role_lookup=role_lookup, user_lookup=user_lookup)

def _task_import_form_visible_fields_for_user(config, user):
    ignored_labels = {
        remove_accents(str(label or "")).strip().lower()
        for label in (config.get("validation_ignored_form_field_labels") or [])
        if str(label or "").strip()
    }
    visible_fields = []
    for field in (config.get("form_fields") or []):
        label = str(field.get("field_label") or "").strip()
        if not label:
            continue
        if remove_accents(label).strip().lower() in ignored_labels:
            continue
        field_config = {
            "target_type": field.get("target_type") or "all",
            "target_unit_domains": field.get("target_unit_domains") or [],
            "target_role_ids": field.get("target_role_ids") or [],
            "target_user_ids": field.get("target_user_ids") or [],
        }
        if _task_report_item_visible_for_user(field_config, user):
            visible_fields.append(label)
    return visible_fields

def _task_import_file_visible_sections_for_user(config, user):
    sections = []
    if bool(config.get("report_narrative_enabled", True)):
        narrative_config = {
            "target_type": config.get("report_narrative_target_type") or "all",
            "target_unit_domains": config.get("report_narrative_unit_domains") or [],
            "target_role_ids": config.get("report_narrative_role_ids") or [],
            "target_user_ids": config.get("report_narrative_user_ids") or [],
        }
        if _task_report_item_visible_for_user(narrative_config, user):
            sections.append(str(config.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip())
    if bool(config.get("report_attachment_enabled")):
        attachment_config = {
            "target_type": config.get("report_attachment_target_type") or "all",
            "target_unit_domains": config.get("report_attachment_unit_domains") or [],
            "target_role_ids": config.get("report_attachment_role_ids") or [],
            "target_user_ids": config.get("report_attachment_user_ids") or [],
        }
        if _task_report_item_visible_for_user(attachment_config, user):
            sections.append(str(config.get("report_attachment_label") or "Tệp minh chứng").strip())
    for field in (config.get("report_fields") or []):
        label = str(field.get("label") or "").strip()
        if not label:
            continue
        field_config = {
            "target_type": field.get("target_type") or "all",
            "target_unit_domains": field.get("target_unit_domains") or [],
            "target_role_ids": field.get("target_role_ids") or [],
            "target_user_ids": field.get("target_user_ids") or [],
        }
        if _task_report_item_visible_for_user(field_config, user):
            sections.append(label)
    return sections

def _task_import_validate_publish_visibility(config, assignees):
    mode = str(config.get("collection_mode") or "").strip().lower()
    if mode not in {"form", "file"}:
        return
    empty_payload_users = []
    for assignee in assignees or []:
        if mode == "form":
            visible_payload = _task_import_form_visible_fields_for_user(config, assignee)
        else:
            visible_payload = _task_import_file_visible_sections_for_user(config, assignee)
        if not visible_payload:
            empty_payload_users.append(getattr(assignee, "fullname", None) or getattr(assignee, "username", None) or f"UID {getattr(assignee, 'id', '')}")
    if empty_payload_users:
        label = "trường biểu mẫu" if mode == "form" else "phần báo cáo"
        raise ValueError(
            f"Có {len(empty_payload_users)} người nhận chưa thấy {label} nào: {', '.join(empty_payload_users[:3])}. Hãy rà lại phạm vi giao việc trước khi phát hành."
        )

def _task_visibility_validation_config(task_mode, assign_type, domain="", role_ids=None, user_ids=None, field_defs=None, report_schema=None, ignored_form_field_labels=None):
    normalized_mode = str(task_mode or "").strip().upper()
    config = {
        "collection_mode": "form" if normalized_mode == "FORM" else "file",
        "assign_type": str(assign_type or "").strip().lower(),
        "domain": str(domain or "").strip(),
        "role_ids": list(role_ids or []),
        "user_ids": list(user_ids or []),
    }
    if normalized_mode == "FORM":
        form_fields = []
        for field_def in (field_defs or []):
            options_payload = _json_loads_safe(field_def.get("field_options_json"), {})
            target_config = _normalize_report_target_config(options_payload)
            form_fields.append(
                {
                    "field_key": str(field_def.get("field_key") or "").strip(),
                    "field_label": str(field_def.get("field_label") or "").strip(),
                    "field_type": str(field_def.get("field_type") or "text").strip().lower(),
                    "target_type": target_config.get("target_type") or "all",
                    "target_unit_domains": target_config.get("target_unit_domains") or [],
                    "target_role_ids": target_config.get("target_role_ids") or [],
                    "target_user_ids": target_config.get("target_user_ids") or [],
                }
            )
        config["form_fields"] = form_fields
        config["validation_ignored_form_field_labels"] = [
            str(label or "").strip()
            for label in (ignored_form_field_labels or [])
            if str(label or "").strip()
        ]
        return config

    schema = report_schema if isinstance(report_schema, dict) else {}
    narrative = schema.get("narrative") if isinstance(schema.get("narrative"), dict) else {}
    attachment = schema.get("attachment") if isinstance(schema.get("attachment"), dict) else {}
    config.update(
        {
            "report_narrative_enabled": bool(narrative.get("enabled", True)),
            "report_narrative_required": bool(narrative.get("required", True)),
            "report_narrative_label": str(narrative.get("label") or "Báo cáo lời tổng hợp").strip(),
            "report_narrative_target_type": str(narrative.get("target_type") or "all").strip().lower() or "all",
            "report_narrative_unit_domains": list(narrative.get("target_unit_domains") or []),
            "report_narrative_role_ids": list(narrative.get("target_role_ids") or []),
            "report_narrative_user_ids": list(narrative.get("target_user_ids") or []),
            "report_attachment_enabled": bool(attachment.get("enabled")),
            "report_attachment_required": bool(attachment.get("required")),
            "report_attachment_label": str(attachment.get("label") or "Tệp minh chứng").strip(),
            "report_attachment_target_type": str(attachment.get("target_type") or "all").strip().lower() or "all",
            "report_attachment_unit_domains": list(attachment.get("target_unit_domains") or []),
            "report_attachment_role_ids": list(attachment.get("target_role_ids") or []),
            "report_attachment_user_ids": list(attachment.get("target_user_ids") or []),
            "report_fields": [],
        }
    )
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict):
            continue
        config["report_fields"].append(
            {
                "key": str(field.get("key") or "").strip(),
                "label": str(field.get("label") or "").strip(),
                "type": str(field.get("type") or "text").strip().lower(),
                "required": bool(field.get("required")),
                "target_type": str(field.get("target_type") or "all").strip().lower() or "all",
                "target_unit_domains": list(field.get("target_unit_domains") or []),
                "target_role_ids": list(field.get("target_role_ids") or []),
                "target_user_ids": list(field.get("target_user_ids") or []),
            }
        )
    return config

def _validate_task_visibility_before_publish(task_mode, assignees, *, assign_type="", domain="", role_ids=None, user_ids=None, field_defs=None, report_schema=None, ignored_form_field_labels=None):
    normalized_mode = str(task_mode or "").strip().upper()
    if normalized_mode not in {"FORM", "FILE"}:
        return
    config = _task_visibility_validation_config(
        normalized_mode,
        assign_type,
        domain=domain,
        role_ids=role_ids,
        user_ids=user_ids,
        field_defs=field_defs,
        report_schema=report_schema,
        ignored_form_field_labels=ignored_form_field_labels,
    )
    _task_import_validate_publish_visibility(config, assignees)

def _task_assignment_scope_lists(task):
    scope = _load_assignment_scope(task)
    return {
        "assign_type": str(scope.get("mode") or getattr(task, "assign_type", None) or "").strip().lower(),
        "domain": str(scope.get("domain") or getattr(task, "domain", "") or "").strip(),
        "role_ids": list(scope.get("role_ids") or []),
        "user_ids": list(scope.get("user_ids") or []),
    }

def _task_import_publish_payload(config):
    collection_mode = str(config.get("collection_mode") or "").strip().lower()
    title = str(config.get("title") or "").strip()
    if not title:
        raise ValueError("Tiêu đề nhiệm vụ không được để trống.")

    domain = canonicalize_category_value(config.get("domain") or "", _task_domain_options(), prefer_stable=True)
    payload = {
        "title": title[:255],
        "content": _task_import_summary_text(config)[:4000],
        "category": canonicalize_category_value(config.get("category") or "", _task_field_options(), prefer_stable=True),
        "domain": domain,
        "priority": canonicalize_category_value(config.get("priority") or "Trung bình", _task_priority_options(), prefer_stable=True),
        "task_type": canonicalize_category_value(config.get("task_type") or "Công việc thường xuyên", _task_type_options(), prefer_stable=True),
        "deadline": _parse_deadline(MultiDict([("deadline", config.get("deadline") or "")])),
        "report_period_json": None,
        "assign_type": _task_import_working_assign_type(config.get("assign_type"), "unit"),
        "unit_domains": _requested_unit_domains(
            MultiDict([("child_domains", value) for value in (config.get("unit_domains") or [])] + ([("child_domain", domain)] if domain else []))
        ),
        "role_ids": sorted({int(role_id) for role_id in (config.get("role_ids") or []) if str(role_id).isdigit()}),
        "user_ids": sorted({int(user_id) for user_id in (config.get("user_ids") or []) if str(user_id).isdigit()}),
        "manager_scope_mode": str(config.get("manager_scope_mode") or "none").strip().lower(),
        "manager_role_ids": sorted({int(role_id) for role_id in (config.get("manager_role_ids") or []) if str(role_id).isdigit()}),
        "manager_user_ids": sorted({int(user_id) for user_id in (config.get("manager_user_ids") or []) if str(user_id).isdigit()}),
        "viewer_scope_mode": str(config.get("viewer_scope_mode") or "none").strip().lower(),
        "viewer_role_ids": sorted({int(role_id) for role_id in (config.get("viewer_role_ids") or []) if str(role_id).isdigit()}),
        "viewer_user_ids": sorted({int(user_id) for user_id in (config.get("viewer_user_ids") or []) if str(user_id).isdigit()}),
        "collection_mode": collection_mode,
        "task_mode": workflow_blueprint_task_mode({"version": 1, "collection_mode": collection_mode, "items": [], "form_fields": [], "report_schema": None}),
        "outline_items": [],
        "form_fields": [],
        "report_schema": None,
        "assignees": [],
    }

    try:
        report_period = report_parse_config(
            {
                "task_type": payload["task_type"],
                "report_deadline": config.get("deadline") or "",
                "report_period_kind": config.get("report_period_kind") or "",
                "report_period": config.get("report_period") or "",
                "report_weekday": config.get("report_weekday") or "",
                "report_day_of_month": config.get("report_day_of_month") or "",
                "report_month_of_year": config.get("report_month_of_year") or "",
                "report_start_date": config.get("report_start_date") or "",
                "report_end_date": config.get("report_end_date") or "",
                "report_milestones": config.get("report_milestones") or [],
            }
        )
        if report_period:
            payload["report_period_json"] = report_config_to_json(report_period)
    except Exception:
        payload["report_period_json"] = None

    manager_form = MultiDict(
        [("manager_scope_mode", payload["manager_scope_mode"])]
        + [("manager_role_ids", str(role_id)) for role_id in payload["manager_role_ids"]]
        + [("manager_user_ids", str(user_id)) for user_id in payload["manager_user_ids"]]
    )
    viewers_form = MultiDict(
        [("viewer_scope_mode", payload["viewer_scope_mode"])]
        + [("viewer_role_ids", str(role_id)) for role_id in payload["viewer_role_ids"]]
        + [("viewer_user_ids", str(user_id)) for user_id in payload["viewer_user_ids"]]
    )
    managers, manager_error = _resolve_managers(manager_form)
    if manager_error:
        raise ValueError(manager_error)
    viewers, viewer_error = _resolve_viewers(viewers_form)
    if viewer_error:
        raise ValueError(viewer_error)
    payload["managers"] = managers
    payload["viewers"] = viewers

    if collection_mode == "outline":
        payload["task_mode"] = "OUTLINE"
        items = []
        raw_items = config.get("items") or []
        if not raw_items:
            raise ValueError("Cần ít nhất một đầu mục trước khi phát hành.")
        all_assignees = []
        for index, item in enumerate(raw_items, start=1):
            title_item = _clean_outline_title(item.get("title"))
            if not title_item:
                continue
            assign_type = _task_import_working_assign_type(item.get("assign_type"))
            if assign_type not in {"unit", "role", "user"}:
                raise ValueError(f'Nội dung "{title_item}" chưa chọn kiểu giao việc.')
            unit_domains = _requested_unit_domains(
                MultiDict([("child_domains", value) for value in (item.get("unit_domains") or [])] + ([("child_domain", domain)] if domain else []))
            )
            role_ids = sorted({int(role_id) for role_id in (item.get("role_ids") or []) if str(role_id).isdigit()})
            user_ids = sorted({int(user_id) for user_id in (item.get("user_ids") or []) if str(user_id).isdigit()})
            if assign_type == "unit" and not unit_domains and domain:
                unit_domains = [domain]
            assignees, error_message = _resolve_assignees_by_mode(
                assign_type,
                domain=domain,
                unit_domains=unit_domains,
                target_ids=user_ids,
                assignee_role_ids=role_ids,
            )
            if error_message:
                raise ValueError(f'Nội dung "{title_item}": {error_message}')
            if not assignees:
                raise ValueError(f'Nội dung "{title_item}" chưa có người thực hiện.')
            report_kind = str(item.get("report_kind") or "narrative").strip().lower()
            if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
                report_kind = "narrative"
            items.append(
                {
                    "title": title_item[:255],
                    "guide_text": str(item.get("guide_text") or "").strip()[:2000],
                    "report_kind": report_kind,
                    "attachment_required": bool(item.get("attachment_required")),
                    "assign_type": assign_type,
                    "unit_domains": unit_domains,
                    "role_ids": role_ids,
                    "user_ids": user_ids,
                    "assignees": assignees,
                    "sort_order": len(items),
                }
            )
            all_assignees.extend(assignees)
        if not items:
            raise ValueError("Cần ít nhất một đầu mục hợp lệ trước khi phát hành.")
        payload["outline_items"] = items
        payload["assignees"] = _dedupe_users(all_assignees)
        return payload

    if collection_mode == "form":
        payload["task_mode"] = "FORM"
        assignees, error_message = _resolve_assignees_by_mode(
            payload["assign_type"],
            domain=domain,
            unit_domains=payload["unit_domains"],
            target_ids=payload["user_ids"],
            assignee_role_ids=payload["role_ids"],
        )
        if error_message:
            raise ValueError(error_message)
        field_defs = _task_import_form_field_defs_from_config(config)
        if not field_defs:
            raise ValueError("Cần ít nhất một trường biểu mẫu trước khi phát hành.")
        _task_import_validate_publish_visibility(config, assignees)
        payload["assignees"] = assignees
        payload["form_fields"] = field_defs
        return payload

    payload["task_mode"] = "FILE"
    assignees, error_message = _resolve_assignees_by_mode(
        payload["assign_type"],
        domain=domain,
        unit_domains=payload["unit_domains"],
        target_ids=payload["user_ids"],
        assignee_role_ids=payload["role_ids"],
    )
    if error_message:
        raise ValueError(error_message)
    report_schema = _task_import_report_schema_from_config(config)
    if not report_schema:
        raise ValueError("Biểu mẫu báo cáo chưa có nội dung hợp lệ.")
    _task_import_validate_publish_visibility(config, assignees)
    payload["assignees"] = assignees
    payload["report_schema"] = report_schema
    return payload

def _publish_task_import_draft(draft):
    config = _task_import_draft_working_config(draft)
    payload = _task_import_publish_payload(config)

    new_task = Task(
        category=payload["category"],
        domain=payload["domain"],
        title=payload["title"],
        content=payload["content"],
        deadline=payload["deadline"],
        file_path="",
        author_id=session["uid"],
        author_name=session.get("fullname", "Quản trị"),
        priority=payload["priority"],
        task_type=payload["task_type"],
        initial_status="Chưa tiếp nhận",
        task_mode=payload["task_mode"],
    )
    if payload.get("report_period_json"):
        new_task.report_period_json = payload["report_period_json"]
    if payload["report_schema"]:
        new_task.report_schema_json = _json_dump(payload["report_schema"])

    _store_assignment_scope(
        new_task,
        payload["assign_type"],
        domain=payload["domain"],
        role_ids=payload["role_ids"],
        user_ids=payload["user_ids"],
    )
    _store_viewer_scope(
        new_task,
        payload["viewer_scope_mode"],
        role_ids=payload["viewer_role_ids"],
        user_ids=payload["viewer_user_ids"],
    )
    _store_manager_scope(
        new_task,
        payload["manager_scope_mode"],
        role_ids=payload["manager_role_ids"],
        user_ids=payload["manager_user_ids"],
    )
    db.session.add(new_task)
    db.session.flush()

    if payload["task_mode"] == "OUTLINE":
        for index, item in enumerate(payload["outline_items"], start=1):
            item_content = str(item.get("content") or "").strip()
            number_fields = item.get("number_fields") or []
            guide_text = item.get("guide_text")
            if number_fields and not guide_text:
                try:
                    guide_text = json.dumps(number_fields, ensure_ascii=False)
                except Exception:
                    guide_text = None
            sources = item.get("sources") or []
            report_sources_json = None
            if sources:
                try:
                    report_sources_json = json.dumps(sources, ensure_ascii=False)
                except Exception:
                    report_sources_json = None
            task_item = TaskItem(
                task_id=new_task.id,
                item_code=str(index),
                title=item["title"],
                content=item_content or None,
                guide_text=guide_text,
                is_required=True,
                output_type="OUTLINE",
                report_kind=item["report_kind"],
                attachment_required=bool(item["attachment_required"]),
                deadline=new_task.deadline,
                sort_order=item.get("sort_order", index - 1),
                report_sources_json=report_sources_json,
            )
            db.session.add(task_item)
            db.session.flush()
            table_cells = item.get("table_cells") or {}
            if table_cells:
                task_item.table_cells_json = _json_dump(table_cells)
                schema = item.get("table_schema")
                if schema and not new_task.outline_table_schema_json:
                    new_task.outline_table_schema_json = _json_dump(schema)
            if item.get("report_secondary") and item_content:
                linked_item = _find_report_secondary_linked_item(item_content, item.get("unit_domains") or [], new_task.id)
                if linked_item:
                    task_item.linked_item_id = linked_item.id
            _create_assignment_records(
                new_task,
                item["assignees"],
                assign_type=item["assign_type"],
                task_item=task_item,
                title_snapshot=task_item.title,
                role_id=item["role_ids"][0] if len(item["role_ids"]) == 1 else None,
            )
    else:
        _create_assignment_records(
            new_task,
            payload["assignees"],
            assign_type=payload["assign_type"],
            title_snapshot=new_task.title,
            role_id=payload["role_ids"][0] if len(payload["role_ids"]) == 1 else None,
        )
        if payload["task_mode"] == "FORM":
            for field_def in payload["form_fields"]:
                db.session.add(TaskFormField(task_id=new_task.id, **_task_form_field_db_kwargs(field_def)))

    draft.status = "published"
    draft.published_task_id = new_task.id
    draft.published_at = datetime.now()
    draft.updated_at = datetime.now()
    db.session.add(draft)
    db.session.commit()

    for user in _dedupe_users(payload["assignees"]):
        push_notif(user.id, "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")
    return new_task

def _task_scope_identity(task):
    if not task:
        return None, None
    cached = getattr(task, "_task_scope_identity_cache", None)
    if cached is not None:
        return cached
    root_task = task.parent_task or task
    if getattr(root_task, "parent_task_id", None):
        root_task = Task.query.filter_by(id=root_task.parent_task_id).first() or root_task
    task_item_id = task.id if getattr(task, "parent_task_id", None) else None
    cached = (root_task.id, task_item_id)
    setattr(task, "_task_scope_identity_cache", cached)
    return cached

def _query_task_scope(model, task):
    task_id, task_item_id = _task_scope_identity(task)
    query = model.query.filter(model.task_id == task_id)
    if task_item_id:
        return query.filter(model.task_item_id == task_item_id)
    return query.filter(model.task_item_id.is_(None))

def _task_assignment_records(task):
    if not task or not getattr(task, "id", None):
        return []
    assignment_records = getattr(task, "assignments", None)
    if assignment_records is not None:
        return sorted(
            assignment_records,
            key=lambda assignment: (
                getattr(assignment, "updated_at", None) or datetime.min,
                getattr(assignment, "id", 0) or 0,
            ),
            reverse=True,
        )
    return (
        TaskAssignment.query.filter_by(task_id=task.id)
        .order_by(TaskAssignment.updated_at.desc(), TaskAssignment.id.desc())
        .all()
    )

def _task_executor_user_ids(task):
    if not task:
        return []
    cached = getattr(task, "_task_executor_user_ids_cache", None)
    if cached is not None:
        return cached

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
        cached = sorted(set(participant_ids))
        setattr(task, "_task_executor_user_ids_cache", cached)
        return cached

    cached = sorted({
        assignment.user_id
        for assignment in _task_assignment_records(task)
        if getattr(assignment, "user_id", None)
    })
    setattr(task, "_task_executor_user_ids_cache", cached)
    return cached

def _task_user_is_executor(task, user_id):
    return bool(user_id and user_id in _task_executor_user_ids(task))

def _visible_child_tasks_for_user(parent_task_id, user_id):
    if not parent_task_id or not user_id:
        return []
    child_tasks = (
        Task.query.options(joinedload(Task.assignments).joinedload(TaskAssignment.user))
        .filter_by(parent_task_id=parent_task_id)
        .order_by(Task.created_at.asc())
        .all()
    )
    visible_tasks = []
    for child_task in child_tasks:
        if _task_user_is_executor(child_task, user_id):
            visible_tasks.append(child_task)
    return visible_tasks

def _visible_child_tasks_by_parent_for_user(parent_task_ids, user_id):
    normalized_parent_ids = sorted({int(parent_id) for parent_id in (parent_task_ids or []) if str(parent_id).isdigit()})
    if not normalized_parent_ids or not user_id:
        return {}

    child_tasks = (
        Task.query.options(joinedload(Task.assignments).joinedload(TaskAssignment.user))
        .filter(Task.parent_task_id.in_(normalized_parent_ids))
        .order_by(Task.parent_task_id.asc(), Task.created_at.asc(), Task.id.asc())
        .all()
    )
    visible_by_parent = {}
    for child_task in child_tasks:
        if any(getattr(assignment, "user_id", None) == user_id for assignment in _task_assignment_records(child_task)):
            visible_by_parent.setdefault(child_task.parent_task_id, []).append(child_task)
    return visible_by_parent

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

def _sync_task_runtime_models(task, assignees=None, managers=None, viewers=None, include_children=False):
    if not task:
        return
    _sync_task_items(task)
    _sync_task_participants(task, assignees=assignees, managers=managers, viewers=viewers)
    _sync_task_submissions(task)
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
        return {"task_items": 0, "executor_participants": 0, "submissions": 0}

    assignment_records = _task_assignment_records(task)
    executor_participants = len({
        assignment.user_id
        for assignment in assignment_records
        if getattr(assignment, "user_id", None)
    })
    submissions = sum(1 for assignment in assignment_records if getattr(assignment, "user_id", None))
    task_items = Task.query.filter_by(parent_task_id=task.id).count() if not getattr(task, "parent_task_id", None) else 0
    return {
        "task_items": task_items,
        "executor_participants": executor_participants,
        "submissions": submissions,
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

    if expected["task_items"] and task_item_count < expected["task_items"]:
        return True
    if expected["executor_participants"] and participant_count < expected["executor_participants"]:
        return True
    if expected["submissions"] and submission_count < expected["submissions"]:
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

def _lazy_repair_task_runtime(task, include_children=False, child_tasks=None, commit=True):
    if not task:
        return False

    changed = _ensure_task_runtime_bridge(task, include_children=include_children)
    if child_tasks and not include_children:
        for child_task in child_tasks:
            if _ensure_task_runtime_bridge(child_task, include_children=False):
                changed = True

    if not changed:
        return False

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return True

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
        setattr(task, "_task_assignment_rows_cache", None)

    if not ensure_bridge:
        cached_rows = getattr(task, "_task_assignment_rows_cache", None)
        if cached_rows is not None:
            return cached_rows

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
    if not ensure_bridge:
        setattr(task, "_task_assignment_rows_cache", rows)
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

def _load_task_parent(task):
    parent_task = getattr(task, "parent_task", None)
    if not parent_task and getattr(task, "parent_task_id", None):
        parent_task = Task.query.filter_by(id=task.parent_task_id).first()
    return parent_task

def _can_manage_task(task, user=None):
    if user is None:
        uid = session.get("uid")
        user = db.session.get(User, uid) if uid else None
    return can_manage_task(
        task,
        session_uid=session.get("uid"),
        is_admin=bool(session.get("is_admin")),
        can_process_module=_can_process_task_module(),
        load_manager_scope_fn=_load_manager_scope,
        user=user,
        load_parent_task_fn=_load_task_parent,
    )

def _can_edit_task(task):
    return _can_manage_task(task)

def _can_delete_task(task, is_lead=False):
    return can_delete_task(
        task,
        session_uid=session.get("uid"),
        is_admin=bool(session.get("is_admin")),
        is_lead=is_lead,
        can_manage=_can_manage_task(task),
    )

def _can_watch_task(task, user=None):
    if user is None:
        uid = session.get("uid")
        user = db.session.get(User, uid) if uid else None
    return can_watch_task(
        task,
        load_viewer_scope_fn=_load_viewer_scope,
        user=user,
        load_parent_task_fn=_load_task_parent,
    )

def _can_view_task(task, is_lead=False):
    return can_view_task(
        task,
        session_uid=session.get("uid"),
        is_admin=bool(session.get("is_admin")),
        is_lead=is_lead,
        is_executor=_task_user_is_executor(task, session.get("uid")),
        can_manage=_can_manage_task(task),
        can_watch=_can_watch_task(task),
        has_visible_child_tasks=bool(_visible_child_tasks_for_user(task.id, session.get("uid"))) if task else False,
    )

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

def _normalize_report_target_domains(values):
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    elif not isinstance(values, (list, tuple, set)):
        values = []
    normalized = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = remove_accents(text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text[:255])
    return normalized

def _normalize_report_target_config(raw_config, defaults=None):
    defaults = defaults or {}
    target_type = str(raw_config.get("target_type") or defaults.get("target_type") or "all").strip().lower()
    if target_type not in TASK_REPORT_ALLOWED_TARGET_TYPES:
        target_type = "all"
    return {
        "target_type": target_type,
        "target_unit_domains": _normalize_report_target_domains(
            raw_config.get("target_unit_domains", defaults.get("target_unit_domains", []))
        ),
        "target_role_ids": _normalize_report_target_ids(
            raw_config.get("target_role_ids", defaults.get("target_role_ids", []))
        ),
        "target_user_ids": _normalize_report_target_ids(
            raw_config.get("target_user_ids", defaults.get("target_user_ids", []))
        ),
    }

def _task_report_user_matches_units(user, target_unit_domains):
    if not user:
        return False
    target_domains = _normalize_report_target_domains(target_unit_domains)
    if not target_domains:
        return False
    user_unit_candidates = [
        getattr(user, "unit_area", None),
        getattr(user, "unit_area_display", None),
        getattr(user, "unit_key", None),
        ]
    return any(
        is_unit_match(candidate, target_domain)
        for candidate in user_unit_candidates if str(candidate or "").strip()
        for target_domain in target_domains
    )

def _task_report_item_visible_for_user(item_config, user):
    if not item_config or not user:
        return False

    target_type = str(item_config.get("target_type") or "all").strip().lower()
    if target_type == "unit":
        return _task_report_user_matches_units(user, item_config.get("target_unit_domains") or [])
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

def _parse_task_workflow_blueprint_from_request(form):
    raw_blueprint = (form.get("workflow_blueprint_json") or "").strip()
    if not raw_blueprint:
        return None

    try:
        parsed = json.loads(raw_blueprint)
    except Exception as exc:
        raise ValueError("Blueprint điều hành không hợp lệ.") from exc

    normalized = normalize_task_workflow_blueprint(parsed)
    if not normalized:
        raise ValueError("Blueprint điều hành chưa có nội dung hợp lệ.")
    return normalized

def _parse_task_workflow_blueprint_payload(payload):
    if isinstance(payload, dict) and isinstance(payload.get("workflow_blueprint"), dict):
        payload = payload.get("workflow_blueprint")

    if not isinstance(payload, dict):
        raise ValueError("Blueprint điều hành không hợp lệ.")

    normalized = normalize_task_workflow_blueprint(payload)
    if not normalized:
        raise ValueError("Blueprint điều hành chưa có nội dung hợp lệ.")
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
            "target_unit_domains": [],
            "target_role_ids": [],
            "target_user_ids": [],
        },
        "attachment": {
            "enabled": bool(attachment_required),
            "label": "Tệp minh chứng",
            "required": bool(attachment_required),
            "target_type": "all",
            "target_unit_domains": [],
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
                "target_unit_domains": [],
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
    if comments is None:
        cached_snapshot = getattr(assignment, "_task_report_snapshot_cache", None)
        if cached_snapshot is not None:
            return cached_snapshot

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
        snapshot = {
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
        if comments is None:
            setattr(assignment, "_task_report_snapshot_cache", snapshot)
        return snapshot

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
    snapshot = {
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
    if comments is None:
        setattr(assignment, "_task_report_snapshot_cache", snapshot)
    return snapshot

def _assignment_report_snapshot_map(assigns, comments=None):
    snapshot_map = {}
    for assignment, _user in assigns or []:
        if not assignment or not getattr(assignment, "id", None):
            continue
        snapshot_map[assignment.id] = _assignment_report_snapshot(assignment, comments=comments)
    return snapshot_map

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
    for assignment, _user in _task_assignment_rows(task, ensure_bridge=False):
        numeric_value = _assignment_numeric_report_value(task, assignment)
        if numeric_value is None:
            continue
        total += numeric_value
        has_value = True
    return _format_report_number(total) if has_value else None

def _build_child_task_unit_summary(task):
    unit_rows = {}
    assignment_rows = _task_assignment_rows(task, ensure_bridge=False)
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
        assignment_rows = _task_assignment_rows(child_task, ensure_bridge=False)
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

def _child_task_condition_meta(dimension, code):
    catalog = CHILD_TASK_PROGRESS_CONDITIONS if dimension == "progress" else CHILD_TASK_QUALITY_CONDITIONS
    for item in catalog:
        if item["code"] == code:
            return item
    return None

def _build_child_task_report_dashboard(child_tasks):
    now_date = datetime.now().date()
    unit_rows = {}

    for child_task in child_tasks or []:
        assignment_rows = _task_assignment_rows(child_task, ensure_bridge=False)
        task_units = {}

        for assignment, user in assignment_rows:
            if not user:
                continue
            unit_identity = _task_unit_identity(user)
            unit_key = unit_identity.get("unit_key") or f"user_{user.id}"
            task_unit = task_units.setdefault(
                unit_key,
                {
                    "unit_key": unit_key,
                    "unit_name": unit_identity.get("unit_name") or getattr(user, "fullname", None) or f"UID {user.id}",
                    "accepted": False,
                    "reported": False,
                    "reported_at": None,
                },
            )

            normalized_status = _normalize_status(getattr(assignment, "status", ""))
            if normalized_status != "Chưa tiếp nhận":
                task_unit["accepted"] = True

            report_snapshot = _assignment_report_snapshot(assignment)
            if not report_snapshot.get("has_report"):
                continue
            report_time = report_snapshot.get("reported_at") or report_snapshot.get("first_report_at")
            if task_unit["reported_at"] is None or (report_time and report_time >= task_unit["reported_at"]):
                task_unit["reported"] = True
                task_unit["reported_at"] = report_time

        for task_unit in task_units.values():
            deadline = getattr(child_task, "deadline", None)
            is_overdue = False
            if deadline:
                if task_unit["reported"] and task_unit["reported_at"]:
                    is_overdue = task_unit["reported_at"].date() > deadline
                else:
                    is_overdue = deadline < now_date

            unit_row = unit_rows.setdefault(
                task_unit["unit_key"],
                {
                    "unit_key": task_unit["unit_key"],
                    "unit_name": task_unit["unit_name"],
                    "child_task_count": 0,
                    "accepted_count": 0,
                    "reported_count": 0,
                    "missing_count": 0,
                    "overdue_count": 0,
                    "on_time_count": 0,
                    "reported_items": [],
                    "missing_items": [],
                    "overdue_items": [],
                    "all_items": [],
                },
            )

            unit_row["child_task_count"] += 1
            if task_unit["accepted"]:
                unit_row["accepted_count"] += 1
            if task_unit["reported"]:
                unit_row["reported_count"] += 1
            else:
                unit_row["missing_count"] += 1
            if is_overdue:
                unit_row["overdue_count"] += 1
            else:
                unit_row["on_time_count"] += 1

            task_item = {
                "task_id": child_task.id,
                "task_title": child_task.title,
                "deadline": deadline,
                "accepted": task_unit["accepted"],
                "reported": task_unit["reported"],
                "reported_at": task_unit["reported_at"],
                "is_overdue": is_overdue,
            }
            unit_row["all_items"].append(task_item)
            if task_unit["reported"]:
                unit_row["reported_items"].append(task_item)
            else:
                unit_row["missing_items"].append(task_item)
            if is_overdue:
                unit_row["overdue_items"].append(task_item)

    unit_row_items = []
    for unit_row in unit_rows.values():
        total_count = unit_row["child_task_count"]
        if unit_row["reported_count"] == total_count and total_count > 0:
            unit_row["progress_code"] = "reported_complete"
        elif unit_row["accepted_count"] == 0:
            unit_row["progress_code"] = "not_reported"
        else:
            unit_row["progress_code"] = "reporting_in_progress"

        if unit_row["overdue_count"] == 0:
            unit_row["quality_code"] = "on_time"
        elif unit_row["overdue_count"] == total_count and total_count > 0:
            unit_row["quality_code"] = "fully_overdue"
        else:
            unit_row["quality_code"] = "partial_overdue"

        progress_meta = _child_task_condition_meta("progress", unit_row["progress_code"]) or {}
        quality_meta = _child_task_condition_meta("quality", unit_row["quality_code"]) or {}
        unit_row["progress_label"] = progress_meta.get("label", "")
        unit_row["progress_description"] = progress_meta.get("description", "")
        unit_row["quality_label"] = quality_meta.get("label", "")
        unit_row["quality_description"] = quality_meta.get("description", "")
        unit_row["reported_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row["missing_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row["overdue_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row["all_items"].sort(key=lambda item: item["task_title"].lower())
        unit_row_items.append(unit_row)

    unit_row_items.sort(
        key=lambda item: (
            item["progress_code"] == "reported_complete",
            item["quality_code"] == "on_time",
            -item["missing_count"],
            -item["overdue_count"],
            item["unit_name"].lower(),
        )
    )

    progress_groups = []
    for item in CHILD_TASK_PROGRESS_CONDITIONS:
        matched_units = [unit_row for unit_row in unit_row_items if unit_row["progress_code"] == item["code"]]
        progress_groups.append({**item, "count": len(matched_units), "units": matched_units})

    quality_groups = []
    for item in CHILD_TASK_QUALITY_CONDITIONS:
        matched_units = [unit_row for unit_row in unit_row_items if unit_row["quality_code"] == item["code"]]
        quality_groups.append({**item, "count": len(matched_units), "units": matched_units})

    return {
        "total_units": len(unit_row_items),
        "total_child_tasks": sum(unit_row["child_task_count"] for unit_row in unit_row_items),
        "total_missing_tasks": sum(unit_row["missing_count"] for unit_row in unit_row_items),
        "total_overdue_tasks": sum(unit_row["overdue_count"] for unit_row in unit_row_items),
        "unit_rows": unit_row_items,
        "progress_groups": progress_groups,
        "quality_groups": quality_groups,
        "child_task_count_by_unit": {
            unit_row["unit_key"]: unit_row["child_task_count"]
            for unit_row in unit_row_items
        },
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
                "target_unit_domains": field.get("target_unit_domains") or [],
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

def _parse_structured_file_report_submission(task, assignment, current_user, form, report_file):
    report_form = _build_structured_task_report_form(task, assignment, current_user)
    if not report_form or not report_form.get("has_visible_content"):
        return None

    missing_labels = []
    values = {}
    attachment_required = bool(report_form["attachment"].get("enabled") and report_form["attachment"].get("required"))
    existing_attachment_name = str(report_form["attachment"].get("value") or "").strip()

    if report_form["narrative"].get("enabled"):
        narrative_value = str(form.get("report_narrative") or form.get("report_content") or "").strip()
        if report_form["narrative"].get("required") and not narrative_value:
            missing_labels.append(report_form["narrative"].get("label") or "Báo cáo lời")
    else:
        narrative_value = ""

    for field in report_form.get("fields") or []:
        field_key = str(field.get("key") or "").strip()
        if not field_key:
            continue
        raw_value = str(form.get(f"report_field_{field_key}") or "").strip()
        normalized_value = raw_value
        if str(field.get("type") or "text").strip().lower() == "number" and raw_value:
            normalized_value = _format_report_number(_parse_report_number(raw_value))
        if field.get("required") and not normalized_value:
            missing_labels.append(field.get("label") or field_key)
        values[field_key] = normalized_value

    if attachment_required and not ((report_file and report_file.filename) or existing_attachment_name):
        missing_labels.append(report_form["attachment"].get("label") or "Tệp minh chứng")

    if missing_labels:
        raise ValueError("Cần điền các nội dung bắt buộc: " + ", ".join(missing_labels) + ".")

    payload = {
        "mode": "structured_task_report",
        "narrative": narrative_value,
        "values": values,
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    if existing_attachment_name:
        payload["attachment_name"] = existing_attachment_name
    return {
        "submission_type": "FILE",
        "narrative": narrative_value,
        "numeric_value": None,
        "payload": payload,
        "report_form": report_form,
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

def _build_unit_report_cards(task, assigns, comments, report_snapshots=None):
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

        report_item = (report_snapshots or {}).get(getattr(assignment, "id", None)) or _assignment_report_snapshot(assignment, comments=comments)
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

    summary_rows, _summary_stats = _build_unit_report_summary(assigns, comments, task.deadline, report_snapshots=report_snapshots)
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

def _build_assignment_unit_cards(assigns, report_snapshots=None):
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
                "has_file": bool(((report_snapshots or {}).get(getattr(assignment, "id", None)) or _assignment_report_snapshot(assignment)).get("attachment_name")),
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

def _build_assignment_role_groups(assigns, child_task_counts_by_unit=None):
    child_task_counts_by_unit = child_task_counts_by_unit or {}
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
                "child_task_count": 0,
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
                "child_task_count": child_task_counts_by_unit.get(unit_key, 0),
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
        group["child_task_count"] = sum(unit_card.get("child_task_count", 0) for unit_card in units)
        if group["completed_count"] == group["total_count"] and group["total_count"] > 0:
            group["status"] = COMPLETED_STATUS
        elif group["accepted_count"] > 0:
            group["status"] = IN_PROGRESS_STATUS
        else:
            group["status"] = "Chưa tiếp nhận"
        output.append(group)

    output.sort(key=lambda item: item["role_name"].lower())
    return output

def _task_assignment_progress_groups(rows):
    assignment_pairs = []
    report_snapshots = {}
    assignee_types = set()

    for row in rows or []:
        assignment = row.get("assignment") if isinstance(row, dict) else None
        if not assignment:
            continue
        user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
        if not user:
            continue
        assignment_pairs.append((assignment, user))
        report_snapshots[getattr(assignment, "id", None)] = _assignment_report_snapshot(assignment)
        assignee_types.add(str(getattr(assignment, "assignee_type", "") or "user").strip().lower())

    return {
        "unit_cards": _build_assignment_unit_cards(assignment_pairs, report_snapshots=report_snapshots) if assignee_types & {"unit", "role"} else [],
        "role_groups": _build_assignment_role_groups(assignment_pairs) if "role" in assignee_types else [],
    }

def _task_file_delivery_labels_for_user(task, user):
    schema = _load_task_report_schema(task) or {}
    labels = []
    narrative = schema.get("narrative") if isinstance(schema.get("narrative"), dict) else {}
    attachment = schema.get("attachment") if isinstance(schema.get("attachment"), dict) else {}
    if bool(narrative.get("enabled", True)) and _task_report_item_visible_for_user(
        {
            "target_type": narrative.get("target_type") or "all",
            "target_unit_domains": narrative.get("target_unit_domains") or [],
            "target_role_ids": narrative.get("target_role_ids") or [],
            "target_user_ids": narrative.get("target_user_ids") or [],
        },
        user,
    ):
        labels.append(str(narrative.get("label") or "Báo cáo lời tổng hợp").strip())
    if bool(attachment.get("enabled")) and _task_report_item_visible_for_user(
        {
            "target_type": attachment.get("target_type") or "all",
            "target_unit_domains": attachment.get("target_unit_domains") or [],
            "target_role_ids": attachment.get("target_role_ids") or [],
            "target_user_ids": attachment.get("target_user_ids") or [],
        },
        user,
    ):
        labels.append(str(attachment.get("label") or "Tệp minh chứng").strip())
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict):
            continue
        label = str(field.get("label") or "").strip()
        if not label:
            continue
        if _task_report_item_visible_for_user(
            {
                "target_type": field.get("target_type") or "all",
                "target_unit_domains": field.get("target_unit_domains") or [],
                "target_role_ids": field.get("target_role_ids") or [],
                "target_user_ids": field.get("target_user_ids") or [],
            },
            user,
        ):
            labels.append(label)
    return labels

def _task_form_delivery_labels_for_user(task, user):
    return [
        str(getattr(field, "field_label", "") or "").strip()
        for field in _task_form_fields_for_user(task, user)
        if str(getattr(field, "field_label", "") or "").strip()
    ]

def _task_delivery_contract_groups(task, mode, rows):
    normalized_mode = str(mode or "").strip().upper()
    groups = {}

    def ensure_group(group_key, group_label, mode_label):
        return groups.setdefault(
            group_key,
            {
                "group_key": group_key,
                "group_label": group_label,
                "mode_label": mode_label,
                "member_names": [],
                "payload_labels": [],
                "recipient_count": 0,
                "payload_count": 0,
            },
        )

    def push_unique(values, value, limit=8):
        text = str(value or "").strip()
        if not text or text in values:
            return
        values.append(text)
        if len(values) > limit:
            del values[limit:]

    for row in (rows or []):
        assignment = row.get("assignment") if isinstance(row, dict) else None
        user = getattr(assignment, "user", None) if assignment else None
        if not assignment or not user:
            continue
        group_key = _task_assignment_submission_group_key(assignment)
        submit_scope = task_assignment_submit_scope(assignment)
        if submit_scope.get("mode") == "unit":
            group_label = f"Đơn vị {_task_assignee_unit_name(user)}"
        elif submit_scope.get("mode") == "role":
            role_name = (
                getattr(getattr(user, "role", None), "name", None)
                or getattr(getattr(assignment, "role", None), "name", None)
                or "Chưa phân vai trò"
            )
            group_label = f"{str(role_name).strip() or 'Chưa phân vai trò'} - {_task_assignee_unit_name(user)}"
        else:
            group_label = getattr(user, "fullname", None) or getattr(user, "username", None) or f"UID {user.id}"
        group = ensure_group(group_key, group_label, submit_scope.get("label") or "Nộp cá nhân")
        push_unique(group["member_names"], getattr(user, "fullname", None) or getattr(user, "username", None) or f"UID {user.id}")
        if normalized_mode == "FILE":
            visible_labels = _task_file_delivery_labels_for_user(task, user)
        elif normalized_mode == "FORM":
            visible_labels = _task_form_delivery_labels_for_user(task, user)
        else:
            visible_labels = []
        for label in visible_labels:
            group["payload_count"] += 1
            push_unique(group["payload_labels"], label)
        group["recipient_count"] = len(group["member_names"])

    return sorted(
        groups.values(),
        key=lambda item: (-int(item["recipient_count"] or 0), -int(item["payload_count"] or 0), remove_accents(item["group_label"]).lower()),
    )

def _filter_assignment_rows_for_executor_scope(rows, current_assignment):
    if not current_assignment:
        return []
    group_key = _task_assignment_submission_group_key(current_assignment)
    return [
        row
        for row in (rows or [])
        if _task_assignment_submission_group_key(row.get("assignment")) == group_key
    ]

def _filter_outline_groups_for_executor_scope(groups):
    return [group for group in (groups or []) if int(group.get("my_items") or 0) > 0]

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

def _store_uploaded_task_file(file_storage, task_id, assignment_id, prefix="report"):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    original_name = secure_filename(file_storage.filename)
    if not original_name:
        return None
    _base_name, ext = os.path.splitext(original_name)
    ext = ext.lower()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    stored_name = secure_filename(f"{prefix}_{task_id}_{assignment_id}_{timestamp}{ext}")
    stored_path = _task_file_path(stored_name)
    file_storage.save(stored_path)
    return {
        "original_name": original_name,
        "stored_name": stored_name,
        "stored_path": stored_path,
        "file_ext": ext,
        "mime_type": getattr(file_storage, "mimetype", "") or "",
        "file_size": os.path.getsize(stored_path) if os.path.exists(stored_path) else 0,
    }

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

def _task_assignment_submission_group_key(assignment):
    if not assignment:
        return ""
    assignee_type = str(getattr(assignment, "assignee_type", "") or "user").strip().lower()
    if assignee_type == "user":
        return f"user:{int(getattr(assignment, 'user_id', 0) or 0)}"

    user = getattr(assignment, "user", None)
    if not user and getattr(assignment, "user_id", None):
        user = db.session.get(User, assignment.user_id)
    if not user:
        return f"{assignee_type}:unknown"

    unit_identity = _task_unit_identity(user)
    unit_key = unit_identity["unit_key"] or unit_identity["unit_name"].lower()
    if assignee_type == "role":
        role_id = int(getattr(assignment, "role_id", None) or getattr(user, "role_id", None) or 0)
        return f"role:{role_id}:unit:{unit_key}"
    if assignee_type == "unit":
        return f"unit:{unit_key}"
    return f"user:{int(getattr(assignment, 'user_id', 0) or 0)}"

def _task_assignment_group_members(task, assignment):
    if not task or not assignment:
        return []
    assignee_type = str(getattr(assignment, "assignee_type", "") or "user").strip().lower()
    if assignee_type not in {"unit", "role"}:
        return [assignment]

    query = TaskAssignment.query.options(joinedload(TaskAssignment.user)).filter_by(
        task_id=task.id,
        assignee_type=assignee_type,
    )
    if getattr(assignment, "task_item_id", None):
        query = query.filter_by(task_item_id=assignment.task_item_id)
    else:
        query = query.filter(TaskAssignment.task_item_id.is_(None))
    group_key = _task_assignment_submission_group_key(assignment)
    return [candidate for candidate in query.all() if _task_assignment_submission_group_key(candidate) == group_key]

def _sync_assignment_group_submission(task, assignment, submission, *, report_payload_json="", result_file="", submitted_at=None, updated_at=None, status="submitted"):
    if not task or not assignment:
        return []
    peers = _task_assignment_group_members(task, assignment)
    if len(peers) <= 1:
        return peers
    submitted_at = submitted_at or getattr(submission, "submitted_at", None) or datetime.now()
    updated_at = updated_at or datetime.now()
    for peer in peers:
        if getattr(peer, "id", None) == getattr(assignment, "id", None):
            continue
        peer.status = status
        peer.submitted_at = submitted_at
        peer.last_submission_id = getattr(submission, "id", None)
        if report_payload_json:
            peer.report_payload_json = report_payload_json
        if result_file:
            peer.result_file = result_file
        peer.updated_at = updated_at
    return peers

def _task_assignments_query(task, task_item_id=None):
    query = TaskAssignment.query.options(joinedload(TaskAssignment.user)).filter_by(task_id=task.id)
    if task_item_id is None:
        return query.filter(TaskAssignment.task_item_id.is_(None))
    return query.filter_by(task_item_id=task_item_id)

def _task_items_for_task(task):
    return (
        TaskItem.query.filter_by(task_id=task.id)
        .order_by(TaskItem.sort_order.asc(), TaskItem.id.asc())
        .all()
    )

def _latest_assignment_submission(assignment):
    if not assignment:
        return None
    if getattr(assignment, "last_submission", None):
        return assignment.last_submission
    return (
        TaskSubmission.query.options(joinedload(TaskSubmission.files))
        .filter_by(assignment_id=assignment.id)
        .order_by(TaskSubmission.created_at.desc(), TaskSubmission.id.desc())
        .first()
    )

def _task_is_submitted(assignment):
    return str(getattr(assignment, "status", "") or "").strip().lower() in {"submitted", "completed"}

def _build_rebuilt_task_summary(task, current_uid):
    assignments = TaskAssignment.query.filter_by(task_id=task.id).all()
    return summarize_task_assignments(assignments, current_uid, _task_is_submitted)

def _task_deadline_display(deadline):
    return task_deadline_display(deadline)

def _task_workspace_tone(status_text, is_overdue=False):
    return task_workspace_tone(status_text, is_overdue=is_overdue)

def _task_detail_context(task, summary, mode, can_manage_task_view, can_submit, my_file_assignment=None, my_form_assignment=None, outline_groups=None):
    return build_task_detail_context(
        task,
        summary,
        mode,
        can_manage_task_view,
        can_submit,
        TASK_ASSIGNMENT_STATUS_LABELS,
        _normalize_status,
        my_file_assignment=my_file_assignment,
        my_form_assignment=my_form_assignment,
        outline_groups=outline_groups,
    )

def _outline_table_schema_map(task):
    """Đọc cấu trúc cột bảng của task (đã lưu khi tạo từ đề cương dạng bảng)."""
    if not task:
        return None
    raw = str(getattr(task, "outline_table_schema_json", "") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, list):
        return None
    schema_map = {}
    for col in parsed:
        if not isinstance(col, dict):
            continue
        index_value = col.get("index")
        if index_value is not None:
            schema_map[str(index_value)] = col
    return schema_map or None


def _outline_item_table_cells(item):
    """Đọc ô dữ liệu theo cột của đầu mục (nếu đầu mục được tạo từ bảng)."""
    if not item:
        return {}
    raw = str(getattr(item, "table_cells_json", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _render_outline_table_html(schema_map, cells, fallback_content=""):
    """Dựng bảng tái hiện (chỉ các cột được tích hiển thị) cho tài khoản đơn vị nhận.

    schema_map: {chỉ_số_cột: {index, header, role, visible}} từ task.
    cells: {chỉ_số_cột: giá trị} của đầu mục.
    """
    if not schema_map or not cells:
        return ""
    columns = sorted(schema_map.values(), key=lambda col: int(col.get("index") or 0))
    columns = [col for col in columns if col.get("visible")]
    if not columns:
        return ""
    header_cells = "".join(
        f"<th class='text-nowrap'>{html.escape(str(col.get('header') or ''))}</th>" for col in columns
    )
    body_cells = []
    for col in columns:
        value = str(cells.get(str(col.get("index")), "") or "").strip()
        if not value and col.get("role") == "content":
            value = str(fallback_content or "").strip()
        body_cells.append(f"<td>{html.escape(value)}</td>")
    return (
        "<div class='table-responsive'><table class='table table-sm table-bordered outline-table-render mb-0'>"
        f"<thead><tr>{header_cells}</tr></thead><tbody><tr>{''.join(body_cells)}</tr></tbody></table></div>"
    )


def _parse_outline_item_rows(task, current_uid):
    rows = []
    for item in _task_items_for_task(task):
        assignments = _task_assignments_query(task, task_item_id=item.id).all()
        my_assignment = next((assignment for assignment in assignments if assignment.user_id == current_uid), None)
        latest_submissions = {
            assignment.id: _latest_assignment_submission(assignment)
            for assignment in assignments
        }
        secondary_text = ""
        for candidate in [getattr(item, "guide_text", None), getattr(item, "content", None)]:
            candidate_text = str(candidate or "").strip()
            if not candidate_text:
                continue
            if candidate_text.startswith("{") or candidate_text.startswith("["):
                # guide_text dạng JSON (trường số liệu) — không hiển thị thô
                continue
            if re.sub(r"\s+", " ", candidate_text).strip().lower() == re.sub(r"\s+", " ", str(item.title or "")).strip().lower():
                continue
            secondary_text = candidate_text
            break
        my_submission = latest_submissions.get(getattr(my_assignment, "id", None))
        number_fields = _outline_item_number_fields(item)
        my_submission_payload = _parse_task_submission_payload(my_submission) if my_submission else {}
        values = my_submission_payload.get("values") if isinstance(my_submission_payload, dict) else None
        if not isinstance(values, dict):
            values = {}
        content = str(getattr(item, "content", "") or "")
        table_cells = _outline_item_table_cells(item)
        table_render_html = ""
        if table_cells:
            table_render_html = _render_outline_table_html(_outline_table_schema_map(task), table_cells, content)
        if table_render_html:
            # Bảng đã tái hiện đầy đủ các cột -> không lặp lại nội dung gộp ở secondary_text
            secondary_text = ""
        rows.append(
            {
                "item": item,
                "assignments": assignments,
                "my_assignment": my_assignment,
                "my_submission": my_submission,
                "my_submission_payload": my_submission_payload,
                "number_fields": number_fields,
                "blank_editor_html": _render_blank_editor_html(content, number_fields, values) if item.report_kind == "number" else "",
                "submitted_count": sum(1 for assignment in assignments if _task_is_submitted(assignment)),
                "total_count": len(assignments),
                "latest_submissions": latest_submissions,
                "secondary_text": secondary_text,
                "table_render_html": table_render_html,
            }
        )
    return rows

def _task_item_synthesis_text(item):
    """Văn bản tổng hợp của đầu mục (quản trị soạn) — rỗng nếu chưa tổng hợp."""
    if not item:
        return ""
    return str(getattr(item, "synthesis_content", None) or "").strip()


def _outline_item_number_fields(item):
    """Lấy danh sách trường số liệu của đầu mục (từ guide_text JSON, hoặc dò lại từ nội dung)."""
    if not item:
        return []
    guide = str(getattr(item, "guide_text", "") or "").strip()
    if guide:
        try:
            parsed = json.loads(guide)
            if isinstance(parsed, dict):
                fields = parsed.get("fields") or []
            elif isinstance(parsed, list):
                fields = parsed
            else:
                fields = []
            fields = [
                f for f in fields
                if isinstance(f, dict) and str(f.get("label") or "").strip()
            ]
            if fields:
                return fields
        except Exception:
            pass
    return _extract_number_fields_from_text(str(getattr(item, "content", "") or ""))

def _parse_outline_item_configs_from_request(form):
    titles = form.getlist("item_title")
    contents = form.getlist("item_content")
    number_fields_values = form.getlist("item_number_fields")
    report_kinds = form.getlist("item_report_kind")
    enabled_indexes = {value for value in form.getlist("item_enabled")}
    attachment_indexes = {value for value in form.getlist("item_attachment_required")}
    assign_types = form.getlist("item_assign_type")
    domains = form.getlist("item_domain")
    domains_values = form.getlist("item_domains")
    role_ids_values = form.getlist("item_role_ids")
    user_ids_values = form.getlist("item_user_ids")
    parent_values = form.getlist("item_parent")
    inherit_values = form.getlist("item_inherit")
    report_secondary_values = form.getlist("item_report_secondary")
    sources_values = form.getlist("item_sources")
    heading_values = form.getlist("item_heading")
    table_cells_values = form.getlist("item_table_cells")
    table_schema = []
    try:
        raw_schema = str(form.get("item_table_schema") or "").strip()
        if raw_schema:
            parsed_schema = json.loads(raw_schema)
            if isinstance(parsed_schema, list):
                table_schema = [
                    {
                        "index": int(col.get("index", 0)),
                        "header": str(col.get("header") or "")[:200],
                        "role": str(col.get("role") or "other").strip() or "other",
                        "visible": bool(col.get("visible")),
                    }
                    for col in parsed_schema
                    if isinstance(col, dict)
                ]
    except Exception:
        table_schema = []
    configs = []
    seen = set()

    for index, raw_title in enumerate(titles):
        if enabled_indexes and str(index) not in enabled_indexes:
            continue
        # Giữ số hiệu mục (vd: "1.1. Các Sở...") để các mục cùng tên ở phần khác
        # nhau của đề cương không bị gộp nhầm; chỉ bỏ dấu đầu dòng nếu có.
        cleaned_title = re.sub(r"^\s*(?:[-–—•*+]\s*|\+\s*)\s*", "", str(raw_title or "").strip())
        cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip(" .:")
        if not cleaned_title:
            continue
        # Với dòng bullet, các mục con cùng tên có thể lặp lại ở nhiều mục khác
        # nhau trong đề cương -> khử trùng theo (heading, title) chứ không theo title.
        raw_parent = str(parent_values[index] if index < len(parent_values) else "").strip()
        raw_heading = str(heading_values[index] if index < len(heading_values) else "").strip()
        dedupe_key = (cleaned_title.lower(), raw_heading.lower(), raw_parent)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        report_kind = str(report_kinds[index] if index < len(report_kinds) else "narrative").strip().lower()
        if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
            report_kind = "narrative"
        assign_type = str(assign_types[index] if index < len(assign_types) else "").strip().lower()
        if assign_type not in {"unit", "role", "user"}:
            assign_type = ""
        domain = str(domains[index] if index < len(domains) else "").strip()
        raw_unit_domains = str(domains_values[index] if index < len(domains_values) else "").strip()
        raw_role_ids = str(role_ids_values[index] if index < len(role_ids_values) else "").strip()
        raw_user_ids = str(user_ids_values[index] if index < len(user_ids_values) else "").strip()
        unit_domains = _requested_unit_domains(
            MultiDict([("child_domains", value.strip()) for value in raw_unit_domains.split(",") if value.strip()] + ([("child_domain", domain)] if domain else []))
        )
        content_text = str(contents[index] if index < len(contents) else "").strip()
        raw_number_fields = str(number_fields_values[index] if index < len(number_fields_values) else "").strip()
        try:
            number_fields = json.loads(raw_number_fields) if raw_number_fields else []
        except Exception:
            number_fields = []
        raw_table_cells = str(table_cells_values[index] if index < len(table_cells_values) else "").strip()
        try:
            table_cells = json.loads(raw_table_cells) if raw_table_cells else {}
            if not isinstance(table_cells, dict):
                table_cells = {}
        except Exception:
            table_cells = {}
        parent_index = int(raw_parent) if raw_parent.isdigit() else None
        configs.append(
            {
                "form_index": index,
                "title": cleaned_title[:255],
                "content": content_text[:3000],
                "report_kind": report_kind,
                "number_fields": number_fields,
                "attachment_required": str(index) in attachment_indexes,
                "assign_type": assign_type,
                "domain": domain[:255],
                "unit_domains": unit_domains,
                "role_ids": sorted({int(value) for value in raw_role_ids.split(",") if value.strip().isdigit()}),
                "user_ids": sorted({int(value) for value in raw_user_ids.split(",") if value.strip().isdigit()}),
                "parent_index": parent_index,
                "inherit": str(index) in inherit_values,
                "report_secondary": (
                    index < len(report_secondary_values)
                    and str(report_secondary_values[index]).strip() == "1"
                ),
                "sources": [
                    source.strip()
                    for source in str(sources_values[index] if index < len(sources_values) else "").split(",")
                    if source.strip()
                ],
                "table_schema": table_schema if table_cells else [],
                "table_cells": table_cells,
            }
        )
    return configs

def _outline_import_preview_session_key(task_id):
    current_uid = int(session.get("uid") or 0)
    return f"task:outline_import_preview:{int(task_id)}:{current_uid}"

def _get_outline_import_preview(task_id):
    raw_value = session.get(_outline_import_preview_session_key(task_id))
    if not isinstance(raw_value, list):
        return []
    rows = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        title = _clean_outline_title(item.get("title"))
        if not title:
            continue
        report_kind = str(item.get("report_kind") or "narrative").strip().lower()
        if report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
            report_kind = "narrative"
        assign_type = str(item.get("assign_type") or "").strip().lower()
        if assign_type not in {"unit", "role", "user"}:
            assign_type = ""
        rows.append(
            {
                "title": title[:255],
                "content": str(item.get("content") or "").strip()[:3000],
                "heading": str(item.get("heading") or "").strip()[:255],
                "parent_row_index": item.get("parent_row_index"),
                "report_kind": report_kind,
                "attachment_required": bool(item.get("attachment_required")),
                "assign_type": assign_type,
                "domain": str(item.get("domain") or "").strip()[:255],
                "unit_domains": _requested_unit_domains(
                    MultiDict([("child_domains", value) for value in (item.get("unit_domains") or [])] + ([("child_domain", item.get("domain"))] if item.get("domain") else []))
                ),
                "role_ids": sorted({int(role_id) for role_id in (item.get("role_ids") or []) if str(role_id).isdigit()}),
                "user_ids": sorted({int(user_id) for user_id in (item.get("user_ids") or []) if str(user_id).isdigit()}),
            }
        )
    return rows

def _set_outline_import_preview(task_id, rows):
    session[_outline_import_preview_session_key(task_id)] = rows
    session.modified = True

def _clear_outline_import_preview(task_id):
    session.pop(_outline_import_preview_session_key(task_id), None)
    session.modified = True

def _resolve_outline_item_assignment(item_config, form, parent_task):
    assign_type = str(item_config.get("assign_type") or "").strip().lower()
    unit_domains = _requested_unit_domains(
        MultiDict([("child_domains", value) for value in (item_config.get("unit_domains") or [])] + ([("child_domain", item_config.get("domain"))] if item_config.get("domain") else []))
    )
    role_ids = sorted({int(role_id) for role_id in (item_config.get("role_ids") or []) if str(role_id).isdigit()})
    user_ids = sorted({int(user_id) for user_id in (item_config.get("user_ids") or []) if str(user_id).isdigit()})
    domain = str(item_config.get("domain") or "").strip()

    if assign_type in {"unit", "role", "user"}:
        assignees, error_message = _resolve_assignees_by_mode(
            assign_type,
            domain=domain or parent_task.domain or "",
            unit_domains=unit_domains,
            target_ids=user_ids,
            assignee_role_ids=role_ids,
        )
        return assignees, error_message, assign_type, role_ids

    fallback_domain = (form.get("child_domain") or parent_task.domain or "").strip()
    assignees, error_message = _resolve_assignees(form, fallback_domain)
    selected_role_ids = _requested_role_ids(form)
    return assignees, error_message, form.get("assign_type", "unit"), selected_role_ids

def _outline_group_identity(assignments, fallback_index=0):
    return outline_group_identity(assignments, _task_assignee_unit_name, fallback_index=fallback_index)

def _build_outline_group_rows(task, current_uid):
    rows = _parse_outline_item_rows(task, current_uid)
    return build_outline_group_rows(rows, _outline_group_identity)

def _build_file_task_rows(task, current_uid):
    assignments = _task_assignments_query(task).all()
    return build_file_task_rows(assignments, current_uid, _latest_assignment_submission)

def _normalize_task_form_field_type(value):
    return normalize_task_form_field_type(value, TASK_FORM_ALLOWED_FIELD_TYPES)

def _task_form_value_is_empty(value):
    return task_form_value_is_empty(value)

def _task_form_fields(task):
    return (
        TaskFormField.query.filter_by(task_id=task.id)
        .order_by(TaskFormField.sort_order.asc(), TaskFormField.id.asc())
        .all()
    )

def _parse_task_form_fields_from_request(form):
    labels = form.getlist("form_field_label")
    field_types = form.getlist("form_field_type")
    required_indexes = {value for value in form.getlist("form_field_required")}
    options_values = form.getlist("form_field_options")
    target_types = form.getlist("form_field_target_type")
    unit_domains_values = form.getlist("form_field_target_unit_domains")
    role_ids_values = form.getlist("form_field_target_role_ids")
    user_ids_values = form.getlist("form_field_target_user_ids")
    fields = []
    for index, raw_label in enumerate(labels):
        label = (raw_label or "").strip()
        if not label:
            continue
        field_type = _normalize_task_form_field_type(field_types[index] if index < len(field_types) else "text")
        raw_options = (options_values[index] if index < len(options_values) else "").strip()
        target_config = _normalize_report_target_config(
            {
                "target_type": target_types[index] if index < len(target_types) else "all",
                "target_unit_domains": unit_domains_values[index] if index < len(unit_domains_values) else "",
                "target_role_ids": _task_import_parse_id_csv(role_ids_values[index] if index < len(role_ids_values) else ""),
                "target_user_ids": _task_import_parse_id_csv(user_ids_values[index] if index < len(user_ids_values) else ""),
            }
        )
        fields.append(
            {
                "field_key": secure_filename(remove_accents(label).replace(" ", "_")) or f"field_{index+1}",
                "field_label": label,
                "field_type": field_type,
                "field_options_json": _task_import_form_field_options_json(field_type, raw_options, target_config),
                "sort_order": len(fields),
                "is_required": str(index) in required_indexes,
            }
        )
    return fields

def _form_field_options(field):
    return form_field_options(field)

def _task_form_field_visible_for_user(field, user):
    return _task_report_item_visible_for_user(_form_field_options(field), user)

def _task_form_fields_for_user(task, user):
    return [field for field in _task_form_fields(task) if _task_form_field_visible_for_user(field, user)]

def _task_form_submission_payload(submission):
    return task_form_submission_payload(submission)

def _build_form_task_rows(task, current_uid):
    assignments = _task_assignments_query(task).all()
    fields = _task_form_fields(task)
    return build_form_task_rows(
        assignments,
        fields,
        current_uid,
        _latest_assignment_submission,
        _task_form_submission_payload,
    )

def _task_form_field_views(task):
    return task_form_field_views(_task_form_fields(task), _normalize_task_form_field_type, _form_field_options)

def _task_form_field_views_for_user(task, user):
    return task_form_field_views(_task_form_fields_for_user(task, user), _normalize_task_form_field_type, _form_field_options)

def _tasks_page_v2():
    perms = _current_perms()
    can_view_all_tasks = _can_view_all_tasks(perms)
    is_lead = _can_process_task_module(perms)
    is_admin = bool(session.get("is_admin"))
    current_user = db.session.get(User, session["uid"])

    task_fields = _task_field_options()
    pro_units = _task_domain_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()
    active_users = []
    roles = []

    if is_lead or is_admin:
        active_users = User.query.filter_by(is_active=True).order_by(User.unit_area.asc(), User.fullname.asc()).all()
        active_users = apply_reference_display(
            sync_record_categories(
                active_users,
                module_category_options("contacts", "unit_name", "Đơn vị"),
                attr_name="unit_area",
                prefer_stable=True,
            ),
            "unit_area",
            module_category_options("contacts", "unit_name", "Đơn vị"),
            display_attr="unit_area_display",
            fallback_label="Chưa có đơn vị",
        )
        roles = AppRole.query.order_by(AppRole.name.asc()).all()

    if request.method == "POST" and is_lead:
        title = (request.form.get("title") or "").strip()
        task_mode = _requested_task_mode(request.form)
        form_provider = str(request.form.get("form_provider") or "internal").strip().lower()
        category = canonicalize_category_value(request.form.get("category") or "", task_fields, prefer_stable=True)
        domain = canonicalize_category_value(
            request.form.get("unit_name") or request.form.get("domain") or "",
            pro_units,
            prefer_stable=True,
        )
        content = (request.form.get("description") or request.form.get("content") or "").strip()
        priority = canonicalize_category_value(request.form.get("priority") or "Trung bình", priority_items, prefer_stable=True)
        task_type = canonicalize_category_value(request.form.get("task_type") or "Công việc thường xuyên", task_types, prefer_stable=True)
        try:
            workflow_blueprint = _parse_task_workflow_blueprint_from_request(request.form)
        except ValueError as blueprint_error:
            flash(str(blueprint_error), "danger")
            return redirect(url_for("tasks_bp.tasks"))

        if workflow_blueprint:
            task_mode = workflow_blueprint_task_mode(workflow_blueprint)
            title = title or workflow_blueprint.get("title", "")
            if not content:
                content = workflow_blueprint_summary_text(workflow_blueprint)

        if not title:
            flash("Tiêu đề công việc không được để trống.", "danger")
            return redirect(url_for("tasks_bp.tasks"))

        try:
            report_schema = _parse_task_report_schema_from_request(request.form)
        except ValueError as report_schema_error:
            flash(str(report_schema_error), "danger")
            return redirect(url_for("tasks_bp.tasks"))
        if not report_schema and workflow_blueprint:
            report_schema = workflow_blueprint_report_schema(workflow_blueprint)

        google_form_builder = None
        google_form_field_defs = []
        google_form_url = ""
        google_form_id = ""
        google_form_match_mode = "unit"
        google_form_match_field = ""
        if task_mode == "FORM" and form_provider == "google":
            google_form_url = str(request.form.get("google_form_url") or "").strip()[:500]
            try:
                google_form_builder = _parse_google_form_builder_schema(
                    request.form.get("google_form_builder_json"),
                    fallback_title=title,
                    fallback_description=content,
                )
            except ValueError as builder_error:
                flash(str(builder_error), "danger")
                return redirect(url_for("tasks_bp.tasks"))
            google_form_field_defs = _hydrate_google_form_fields(google_form_builder)
            google_form_id = extract_google_form_id(google_form_url)
            builder_matching = google_form_builder.get("matching") if isinstance(google_form_builder.get("matching"), dict) else {}
            google_form_match_mode = _normalize_google_form_match_mode(
                request.form.get("google_form_match_mode") or builder_matching.get("mode") or "unit"
            )
            google_form_match_field = str(
                request.form.get("google_form_match_field")
                or builder_matching.get("match_field")
                or ""
            ).strip()[:255]

        managers, manager_error_message = _resolve_managers(request.form)
        if manager_error_message:
            flash(manager_error_message, "danger")
            return redirect(url_for("tasks_bp.tasks"))
        viewers, viewer_error_message = _resolve_viewers(request.form)
        if viewer_error_message:
            flash(viewer_error_message, "danger")
            return redirect(url_for("tasks_bp.tasks"))

        assignees = []
        blueprint_items = workflow_blueprint_item_configs(workflow_blueprint) if workflow_blueprint else []
        assign_type = request.form.get("assign_type", "unit")
        assign_role_ids = _requested_role_ids(request.form)
        assign_user_ids = _requested_user_ids(request.form)
        if task_mode in {"FILE", "FORM"} or blueprint_items:
            assignees, error_message = _resolve_assignees(request.form, domain)
            if error_message:
                flash(error_message, "danger")
                return redirect(url_for("tasks_bp.tasks"))

        attachment = request.files.get("task_file") or request.files.get("file")
        attachment_name = ""
        if attachment and attachment.filename:
            attachment_meta = _store_uploaded_task_file(attachment, "task", "template", prefix="task")
            attachment_name = attachment_meta["stored_name"] if attachment_meta else ""

        new_task = Task(
            category=category,
            domain=domain,
            title=title,
            content=content,
            deadline=_computed_task_deadline(request.form, task_type=task_type) or _parse_deadline(request.form),
            file_path=attachment_name,
            author_id=session["uid"],
            author_name=session.get("fullname", "Quản trị"),
            priority=priority,
            task_type=task_type,
            initial_status="Chưa tiếp nhận",
            task_mode=task_mode,
            form_provider=form_provider if task_mode == "FORM" else "internal",
        )
        report_period = _parse_task_report_period_from_request(request.form, task_type=task_type)
        if report_period:
            new_task.report_period_json = report_config_to_json(report_period)
        if report_schema:
            new_task.report_schema_json = json.dumps(report_schema, ensure_ascii=False)
        if task_mode == "FORM" and form_provider == "google":
            new_task.google_form_url = google_form_url or None
            new_task.google_form_id = google_form_id or None
            new_task.google_form_match_mode = google_form_match_mode
            new_task.google_form_match_field = google_form_match_field or None
            new_task.google_form_builder_json = _json_dump(google_form_builder)
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

        if task_mode in {"FILE", "FORM"}:
            _create_assignment_records(
                new_task,
                assignees,
                assign_type=request.form.get("assign_type", "unit"),
                title_snapshot=new_task.title,
            )

        if task_mode == "OUTLINE":
            outline_item_configs = _parse_outline_item_configs_from_request(request.form)
            if not outline_item_configs and not blueprint_items:
                bulk_titles = _parse_bulk_child_task_titles(
                    request.form.get("bulk_titles") or request.form.get("bulk_items")
                )
                outline_file = request.files.get("outline_file")
                if outline_file and outline_file.filename and not bulk_titles:
                    try:
                        bulk_titles.extend(_parse_outline_upload_titles(outline_file))
                    except ValueError:
                        bulk_titles = []
                if bulk_titles:
                    child_report_kind = str(request.form.get("child_report_kind") or "narrative").strip().lower()
                    if child_report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
                        child_report_kind = "narrative"
                    attachment_required = _report_checkbox_value(request.form.get("child_attachment_required"))
                    outline_item_configs = [
                        {
                            "title": item_title,
                            "report_kind": child_report_kind,
                            "attachment_required": bool(attachment_required),
                        }
                        for item_title in bulk_titles
                    ]

            if outline_item_configs:
                created_item_by_form_index = {}
                for index, item_config in enumerate(outline_item_configs, start=1):
                    item_content = str(item_config.get("content") or "").strip()
                    number_fields = item_config.get("number_fields") or []
                    guide_text = None
                    if number_fields:
                        try:
                            guide_text = json.dumps(number_fields, ensure_ascii=False)
                        except Exception:
                            guide_text = None
                    parent_item_id = None
                    parent_index = item_config.get("parent_index")
                    if parent_index is not None and parent_index in created_item_by_form_index:
                        parent_item_id = created_item_by_form_index[parent_index]
                    task_item = TaskItem(
                        task_id=new_task.id,
                        parent_item_id=parent_item_id,
                        item_code=str(index),
                        title=item_config["title"],
                        content=item_content or None,
                        guide_text=guide_text,
                        is_required=True,
                        output_type="OUTLINE",
                        report_kind=item_config.get("report_kind") or "narrative",
                        attachment_required=bool(item_config.get("attachment_required")),
                        deadline=new_task.deadline,
                        sort_order=index,
                        report_sources_json=_outline_sources_json(item_config.get("sources") or []),
                    )
                    db.session.add(task_item)
                    db.session.flush()
                    table_cells = item_config.get("table_cells") or {}
                    if table_cells:
                        task_item.table_cells_json = json.dumps(table_cells, ensure_ascii=False)
                        schema = item_config.get("table_schema") or []
                        if schema and not new_task.outline_table_schema_json:
                            new_task.outline_table_schema_json = json.dumps(schema, ensure_ascii=False)
                    if item_config.get("report_secondary") and item_content:
                        linked_item = _find_report_secondary_linked_item(
                            item_content,
                            item_config.get("unit_domains") or [],
                            new_task.id,
                        )
                        if linked_item:
                            task_item.linked_item_id = linked_item.id
                    created_item_by_form_index[item_config["form_index"]] = task_item.id
                    if (
                        item_config.get("inherit")
                        and parent_index is not None
                        and parent_index in created_item_by_form_index
                    ):
                        # Dòng con kế thừa gán từ mục cha: tạo assignment giống cha
                        parent_item = TaskItem.query.filter_by(id=created_item_by_form_index[parent_index]).first()
                        if parent_item:
                            parent_assignments = TaskAssignment.query.filter_by(
                                task_id=new_task.id, task_item_id=parent_item.id
                            ).all()
                            for parent_assignment in parent_assignments:
                                db.session.add(
                                    TaskAssignment(
                                        task_id=new_task.id,
                                        task_item_id=task_item.id,
                                        user_id=parent_assignment.user_id,
                                        assignee_type=parent_assignment.assignee_type,
                                        role_id=parent_assignment.role_id,
                                        title_snapshot=item_config["title"],
                                        status="assigned",
                                        is_required=True,
                                        assigned_at=datetime.now(),
                                    )
                                )
                            continue
                    item_assignees, item_error_message, item_assign_type, item_role_ids = _resolve_outline_item_assignment(
                        item_config, request.form, new_task
                    )
                    if item_error_message:
                        flash(f'Nội dung "{item_config.get("title", "")}": {item_error_message}', "danger")
                        db.session.rollback()
                        return redirect(url_for("tasks_bp.tasks"))
                    _create_assignment_records(
                        new_task,
                        item_assignees,
                        assign_type=item_assign_type,
                        task_item=task_item,
                        title_snapshot=task_item.title,
                        role_id=item_role_ids[0] if len(item_role_ids) == 1 else None,
                    )
            elif blueprint_items:
                for index, item_config in enumerate(blueprint_items, start=1):
                    task_item = TaskItem(
                        task_id=new_task.id,
                        item_code=str(index),
                        title=item_config["title"],
                        content=item_config.get("description"),
                        guide_text=item_config.get("guide_text"),
                        is_required=bool(item_config.get("is_required", True)),
                        output_type="OUTLINE",
                        report_kind=item_config.get("report_kind") or "narrative",
                        attachment_required=bool(item_config.get("attachment_required")),
                        deadline=new_task.deadline,
                        sort_order=item_config.get("sort_order", index - 1),
                    )
                    db.session.add(task_item)
                    db.session.flush()
                    _create_assignment_records(
                        new_task,
                        assignees,
                        assign_type=request.form.get("assign_type", "unit"),
                        task_item=task_item,
                        title_snapshot=task_item.title,
                    )

        if task_mode == "FORM":
            field_defs = google_form_field_defs if form_provider == "google" else _parse_task_form_fields_from_request(request.form)
            if not field_defs and workflow_blueprint:
                field_defs = workflow_blueprint_form_field_defs(workflow_blueprint)
            if not field_defs and form_provider != "google":
                flash("Cần cấu hình ít nhất một trường dữ liệu cho biểu mẫu.", "danger")
                db.session.rollback()
                return redirect(url_for("tasks_bp.tasks"))
            try:
                _validate_task_visibility_before_publish(
                    "FORM",
                    assignees,
                    assign_type=assign_type,
                    domain=domain,
                    role_ids=assign_role_ids,
                    user_ids=assign_user_ids,
                    field_defs=field_defs,
                    ignored_form_field_labels=[google_form_match_field] if form_provider == "google" and google_form_match_field else [],
                )
            except ValueError as visibility_error:
                flash(str(visibility_error), "danger")
                db.session.rollback()
                return redirect(url_for("tasks_bp.tasks"))
            for field_def in field_defs:
                db.session.add(TaskFormField(task_id=new_task.id, **_task_form_field_db_kwargs(field_def)))
        elif task_mode == "FILE":
            try:
                _validate_task_visibility_before_publish(
                    "FILE",
                    assignees,
                    assign_type=assign_type,
                    domain=domain,
                    role_ids=assign_role_ids,
                    user_ids=assign_user_ids,
                    report_schema=report_schema,
                )
            except ValueError as visibility_error:
                flash(str(visibility_error), "danger")
                db.session.rollback()
                return redirect(url_for("tasks_bp.tasks"))

        db.session.commit()

        for user in assignees:
            push_notif(user.id, "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")

        # Send email notifications to assigned users
        try:
            protocol = request.scheme
            host = request.host
            base_url = f"{protocol}://{host}"
            email_result = send_task_assignment_emails(assignees, new_task, base_url=base_url)
            if email_result.get("skipped"):
                for uid, reason in email_result["skipped"]:
                    logger.warning(f"Email skipped for user {uid}: {reason}")
        except Exception as e:
            logger.error(f"Failed to send task assignment emails: {e}")

        flash("Đã tạo công việc mới.", "success")
        return redirect(url_for("tasks_bp.task_detail", tid=new_task.id))

    candidate_tasks = (
        Task.query.options(joinedload(Task.assignments).joinedload(TaskAssignment.user))
        .filter(Task.parent_task_id.is_(None))
        .order_by(Task.created_at.desc(), Task.id.desc())
        .all()
    )

    visible_tasks = []
    for task in candidate_tasks:
        is_executor = TaskAssignment.query.filter_by(task_id=task.id, user_id=session["uid"]).first() is not None
        is_manager = _can_manage_task(task, user=current_user)
        is_viewer = _can_watch_task(task, user=current_user)
        if not task_visible_for_user(
            task,
            session["uid"],
            can_view_all_tasks=can_view_all_tasks,
            is_admin=is_admin,
            is_executor=is_executor,
            is_manager=is_manager,
            is_viewer=is_viewer,
        ):
            continue

        sync_record_categories([task], task_fields, attr_name="category", prefer_stable=True)
        sync_record_categories([task], pro_units, attr_name="domain", prefer_stable=True)
        sync_record_categories([task], task_types, attr_name="task_type", prefer_stable=True)
        sync_record_categories([task], priority_items, attr_name="priority", prefer_stable=True)
        _decorate_task_categories(task, task_fields, pro_units, task_types, priority_items)
        visible_tasks.append(
            prepare_task_workspace_record(
                task,
                session["uid"],
                is_lead,
                _build_rebuilt_task_summary,
                _task_mode,
                _task_mode_label,
                _task_mode_description,
                _task_assignment_status_label,
                _can_edit_task,
                _can_delete_task,
                _task_assignment_display_status,
                build_task_workspace_attrs,
                today=datetime.now().date(),
            )
        )

    list_context = build_task_list_page_context(visible_tasks, TASK_MODE_DEFAULT)
    current_task_view = (request.args.get("view") or "attention").strip().lower()
    sidebar_submenu_items = []
    if list_context["attention_tasks"]:
        sidebar_submenu_items.append({
            "label": "Cần xử lý ngay",
            "href": url_for("tasks_bp.tasks", view="attention") + "#attention-tasks",
            "count": len(list_context["attention_tasks"]),
            "active": current_task_view == "attention",
        })
    sidebar_submenu_items.extend([
        {
            "label": "Việc của tôi",
            "href": url_for("tasks_bp.tasks", view="my") + "#my-tasks",
            "count": len(list_context["my_tasks"]),
            "active": current_task_view == "my",
        },
        {
            "label": "Tôi giao / theo dõi",
            "href": url_for("tasks_bp.tasks", view="managed") + "#managed-tasks",
            "count": len(list_context["managed_tasks"]),
            "active": current_task_view == "managed",
        },
        {
            "label": "Chỉ xem / tra cứu",
            "href": url_for("tasks_bp.tasks", view="watch") + "#watch-tasks",
            "count": len(list_context["watch_tasks"]),
            "active": current_task_view == "watch",
        },
    ])

    return render_template(
        "tasks_rebuild.html",
        tasks=list_context["tasks"],
        attention_tasks=list_context["attention_tasks"],
        my_tasks=list_context["my_tasks"],
        managed_tasks=list_context["managed_tasks"],
        watch_tasks=list_context["watch_tasks"],
        outline_tasks=list_context["outline_tasks"],
        file_tasks=list_context["file_tasks"],
        form_tasks=list_context["form_tasks"],
        users=active_users,
        roles=roles,
        pro_units=stable_form_category_options(pro_units),
        task_fields=task_fields,
        task_types=stable_form_category_options(task_types),
        priority_items=stable_form_category_options(priority_items),
        is_lead=is_lead,
        is_admin=is_admin,
        stats=list_context["stats"],
        workflow_blueprint_examples=workflow_blueprint_example_catalog(),
        sidebar_submenu_parent="tasks",
        sidebar_submenu_title="Công việc",
        sidebar_submenu_items=sidebar_submenu_items,
    )

def _task_detail_v2(tid):
    task = Task.query.options(joinedload(Task.assignments).joinedload(TaskAssignment.user)).filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    perms = _current_perms()
    can_view_all_tasks = _can_view_all_tasks(perms)
    is_lead = _can_process_task_module(perms)
    is_admin = bool(session.get("is_admin"))
    current_user = db.session.get(User, session["uid"])
    is_executor = TaskAssignment.query.filter_by(task_id=task.id, user_id=session["uid"]).first() is not None
    can_manage_task_view = bool(is_admin or is_lead or _can_edit_task(task) or _can_manage_task(task, user=current_user))
    can_watch_task_view = bool(_can_watch_task(task, user=current_user))

    if not (can_view_all_tasks or can_manage_task_view or can_watch_task_view or is_executor or task.author_id == session["uid"]):
        flash("Bạn không có quyền xem công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    _lazy_repair_task_runtime(task, include_children=False, commit=True)

    pro_units = _task_domain_options()
    task_fields = _task_field_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()
    sync_record_categories([task], task_fields, attr_name="category", prefer_stable=True)
    sync_record_categories([task], pro_units, attr_name="domain", prefer_stable=True)
    sync_record_categories([task], task_types, attr_name="task_type", prefer_stable=True)
    sync_record_categories([task], priority_items, attr_name="priority", prefer_stable=True)
    _decorate_task_categories(task, task_fields, pro_units, task_types, priority_items)

    mode = _task_mode(task)
    setattr(task, "task_mode", mode)
    setattr(task, "task_mode_label", _task_mode_label(mode))
    setattr(task, "task_mode_description", _task_mode_description(mode))
    if mode == "FORM" and str(getattr(task, "form_provider", "") or "").strip().lower() == "google":
        _apply_task_google_form_view_state(task)

    detail_page_context = build_task_detail_page_context(
        task,
        session["uid"],
        mode,
        can_manage_task_view,
        is_executor,
        _build_rebuilt_task_summary,
        _parse_outline_item_rows,
        _build_outline_group_rows,
        _build_file_task_rows,
        _build_form_task_rows,
        _task_form_field_views,
        _task_detail_context,
    )
    if mode == "OUTLINE" and not (can_manage_task_view or can_watch_task_view):
        detail_page_context["outline_groups"] = _filter_outline_groups_for_executor_scope(detail_page_context["outline_groups"])
        visible_item_ids = {
            getattr(row.get("item"), "id", None)
            for group in detail_page_context["outline_groups"]
            for row in (group.get("rows") or [])
        }
        detail_page_context["outline_rows"] = [
            row for row in (detail_page_context["outline_rows"] or [])
            if getattr(row.get("item"), "id", None) in visible_item_ids
        ]
    elif mode == "FILE" and not (can_manage_task_view or can_watch_task_view):
        detail_page_context["file_rows"] = _filter_assignment_rows_for_executor_scope(
            detail_page_context["file_rows"],
            detail_page_context["my_file_assignment"],
        )
    elif mode == "FORM" and not (can_manage_task_view or can_watch_task_view):
        detail_page_context["form_rows"] = _filter_assignment_rows_for_executor_scope(
            detail_page_context["form_rows"],
            detail_page_context["my_form_assignment"],
        )
    file_report_comments = TaskComment.query.filter_by(task_id=task.id).order_by(TaskComment.created_at.asc(), TaskComment.id.asc()).all() if mode == "FILE" else []
    my_file_report_form = _build_structured_task_report_form(task, detail_page_context["my_file_assignment"], current_user) if mode == "FILE" and detail_page_context["my_file_assignment"] else None
    my_form_field_views = _task_form_field_views_for_user(task, current_user) if mode == "FORM" and detail_page_context["my_form_assignment"] else []
    if mode == "FILE":
        for row in detail_page_context["file_rows"]:
            row["report_context"] = _build_assignment_report_context(row["assignment"], file_report_comments, task=task)
    file_progress_groups = _task_assignment_progress_groups(detail_page_context["file_rows"]) if mode == "FILE" else {"unit_cards": [], "role_groups": []}
    form_progress_groups = _task_assignment_progress_groups(detail_page_context["form_rows"]) if mode == "FORM" else {"unit_cards": [], "role_groups": []}
    delivery_contract_rows = []
    if mode == "FILE":
        delivery_contract_rows = detail_page_context["file_rows"]
        if is_executor and detail_page_context["my_file_assignment"]:
            delivery_contract_rows = _filter_assignment_rows_for_executor_scope(
                delivery_contract_rows,
                detail_page_context["my_file_assignment"],
            )
    elif mode == "FORM":
        delivery_contract_rows = detail_page_context["form_rows"]
        if is_executor and detail_page_context["my_form_assignment"]:
            delivery_contract_rows = _filter_assignment_rows_for_executor_scope(
                delivery_contract_rows,
                detail_page_context["my_form_assignment"],
            )
    delivery_contract_groups = _task_delivery_contract_groups(task, mode, delivery_contract_rows) if mode in {"FILE", "FORM"} else []
    active_users = []
    roles = []
    if can_manage_task_view:
        active_users = User.query.filter_by(is_active=True).order_by(User.unit_area.asc(), User.fullname.asc()).all()
        active_users = apply_reference_display(
            sync_record_categories(
                active_users,
                module_category_options("contacts", "unit_name", "Đơn vị"),
                attr_name="unit_area",
                prefer_stable=True,
            ),
            "unit_area",
            module_category_options("contacts", "unit_name", "Đơn vị"),
            display_attr="unit_area_display",
            fallback_label="Chưa có đơn vị",
        )
        roles = AppRole.query.order_by(AppRole.name.asc()).all()
    outline_import_preview_rows = _get_outline_import_preview(task.id) if mode == "OUTLINE" and can_manage_task_view else []
    outline_matrix = _build_outline_progress_matrix(task, session["uid"]) if mode == "OUTLINE" else None

    return render_template(
        "task_detail_rebuild.html",
        task=task,
        pro_units=stable_form_category_options(pro_units),
        task_fields=stable_form_category_options(task_fields),
        task_types=stable_form_category_options(task_types),
        priority_items=stable_form_category_options(priority_items),
        can_edit_task=_can_edit_task(task),
        can_delete_task=_can_delete_task(task, is_lead=is_lead),
        can_manage_task_view=can_manage_task_view,
        can_watch_task_view=can_watch_task_view,
        can_submit=is_executor,
        is_lead=is_lead,
        is_admin=is_admin,
        users=active_users,
        roles=roles,
        outline_rows=detail_page_context["outline_rows"],
        outline_groups=detail_page_context["outline_groups"],
        outline_import_preview_rows=outline_import_preview_rows,
        outline_matrix=outline_matrix,
        file_rows=detail_page_context["file_rows"],
        file_assignment_unit_cards=file_progress_groups["unit_cards"],
        file_assignment_role_groups=file_progress_groups["role_groups"],
        delivery_contract_groups=delivery_contract_groups,
        my_file_report_form=my_file_report_form,
        form_fields=detail_page_context["form_fields"],
        form_field_views=detail_page_context["form_field_views"],
        form_rows=detail_page_context["form_rows"],
        form_assignment_unit_cards=form_progress_groups["unit_cards"],
        form_assignment_role_groups=form_progress_groups["role_groups"],
        my_file_assignment=detail_page_context["my_file_assignment"],
        my_file_submission=detail_page_context["my_file_submission"],
        my_form_assignment=detail_page_context["my_form_assignment"],
        my_form_submission=detail_page_context["my_form_submission"],
        my_form_payload=detail_page_context["my_form_payload"],
        my_form_field_views=my_form_field_views,
        summary=detail_page_context["summary"],
        detail_context=detail_page_context["detail_context"],
        status_labels=TASK_ASSIGNMENT_STATUS_LABELS,
        report_period=_task_report_period(task),
        report_kind_label=_task_report_kind_label(task),
        current_cycle=_task_current_cycle(task),
    )

def _create_outline_items_v2(tid):
    parent_task = Task.query.filter_by(id=tid).first()
    if not parent_task:
        return "Not Found", 404

    if _task_mode(parent_task) != "OUTLINE":
        flash("Công việc này không dùng chế độ đề cương.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if not _can_edit_task(parent_task):
        flash("Bạn không có quyền thêm đầu mục cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    item_configs = _parse_outline_item_configs_from_request(request.form)
    bulk_titles = _parse_bulk_child_task_titles(request.form.get("bulk_titles") or request.form.get("bulk_items"))
    outline_file = request.files.get("outline_file")
    if outline_file and outline_file.filename and not item_configs:
        try:
            bulk_titles.extend(_parse_outline_upload_titles(outline_file))
        except ValueError as outline_error:
            flash(str(outline_error), "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        bulk_titles = _parse_bulk_child_task_titles("\n".join(bulk_titles))

    if not item_configs:
        child_report_kind = str(request.form.get("child_report_kind") or "narrative").strip().lower()
        if child_report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
            child_report_kind = "narrative"
        attachment_required = _report_checkbox_value(request.form.get("child_attachment_required"))
        item_configs = [
            {
                "title": item_title,
                "report_kind": child_report_kind,
                "attachment_required": bool(attachment_required),
            }
            for item_title in bulk_titles
        ]

    if not item_configs:
        flash("Cần tạo ít nhất một nội dung báo cáo trước khi gán.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    current_count = TaskItem.query.filter_by(task_id=parent_task.id).count()

    created_item_by_form_index = {}
    for index, item_config in enumerate(item_configs, start=1):
        item_content = str(item_config.get("content") or "").strip()
        number_fields = item_config.get("number_fields") or []
        guide_text = None
        if number_fields:
            try:
                guide_text = json.dumps(number_fields, ensure_ascii=False)
            except Exception:
                guide_text = None
        parent_item_id = None
        parent_index = item_config.get("parent_index")
        if parent_index is not None and parent_index in created_item_by_form_index:
            parent_item_id = created_item_by_form_index[parent_index]
        task_item = TaskItem(
            task_id=parent_task.id,
            parent_item_id=parent_item_id,
            item_code=str(current_count + index),
            title=item_config["title"],
            content=item_content or None,
            guide_text=guide_text,
            is_required=True,
            output_type="OUTLINE",
            report_kind=item_config["report_kind"],
            attachment_required=bool(item_config["attachment_required"]),
            deadline=parent_task.deadline,
            sort_order=current_count + index,
        )
        db.session.add(task_item)
        db.session.flush()
        created_item_by_form_index[item_config.get("form_index", index - 1)] = task_item.id
        if (
            item_config.get("inherit")
            and parent_index is not None
            and parent_index in created_item_by_form_index
        ):
            # Dòng con kế thừa gán từ mục cha: tạo assignment giống cha
            parent_item = TaskItem.query.filter_by(id=created_item_by_form_index[parent_index]).first()
            if parent_item:
                parent_assignments = TaskAssignment.query.filter_by(
                    task_id=parent_task.id, task_item_id=parent_item.id
                ).all()
                for parent_assignment in parent_assignments:
                    db.session.add(
                        TaskAssignment(
                            task_id=parent_task.id,
                            task_item_id=task_item.id,
                            user_id=parent_assignment.user_id,
                            assignee_type=parent_assignment.assignee_type,
                            role_id=parent_assignment.role_id,
                            title_snapshot=item_config["title"],
                            status="assigned",
                            is_required=True,
                            assigned_at=datetime.now(),
                        )
                    )
                continue
        assignees, error_message, assign_type, role_ids = _resolve_outline_item_assignment(item_config, request.form, parent_task)
        if error_message:
            flash(f'Nội dung "{item_config["title"]}": {error_message}', "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        _create_assignment_records(
            parent_task,
            assignees,
            assign_type=assign_type,
            task_item=task_item,
            title_snapshot=item_config["title"],
            role_id=role_ids[0] if len(role_ids) == 1 else None,
        )

    db.session.commit()
    _clear_outline_import_preview(parent_task.id)
    flash(f"Đã thêm {len(item_configs)} đầu mục.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _preview_outline_import_v2(tid):
    parent_task = Task.query.filter_by(id=tid).first()
    if not parent_task:
        return "Not Found", 404

    if _task_mode(parent_task) != "OUTLINE":
        flash("Công việc này không dùng chế độ đề cương.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if not _can_edit_task(parent_task):
        flash("Bạn không có quyền nạp đề cương cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    outline_file = request.files.get("outline_file")
    if not outline_file or not outline_file.filename:
        flash("Cần chọn file đề cương trước khi nạp.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        parsed_rows = _parse_outline_upload_rows(outline_file)
    except ValueError as outline_error:
        flash(str(outline_error), "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if not parsed_rows:
        flash("Không tìm thấy đầu mục hợp lệ trong file đề cương.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    default_report_kind = str(request.form.get("child_report_kind") or "narrative").strip().lower()
    if default_report_kind not in CHILD_TASK_ALLOWED_REPORT_KINDS:
        default_report_kind = "narrative"
    attachment_required = _report_checkbox_value(request.form.get("child_attachment_required"))

    preview_rows = []
    detected_count = 0
    for row in parsed_rows:
        assignee_detected = bool(row.get("assignee_detected"))
        preview_rows.append(
            {
                "title": row["title"],
                "content": row.get("content") or "",
                "heading": row.get("heading") or "",
                "parent_row_index": row.get("parent_row_index"),
                "report_kind": default_report_kind,
                "attachment_required": bool(attachment_required),
                "assign_type": row.get("assign_type") or "",
                "domain": row.get("domain") or "",
                "unit_domains": row.get("unit_domains") or [],
                "role_ids": row.get("role_ids") or [],
                "user_ids": row.get("user_ids") or [],
                "assignee_hint": row.get("assignee_hint") or "",
            }
        )
        if assignee_detected:
            detected_count += 1
    _set_outline_import_preview(parent_task.id, preview_rows)
    if detected_count:
        flash(
            f"Đã nạp {len(preview_rows)} nội dung từ đề cương; tự nhận diện người nhận cho {detected_count} đầu mục. "
            "Kiểm tra cột 'Người nhận' rồi bấm Tạo khi chính xác.",
            "success",
        )
    else:
        flash(
            f"Đã nạp {len(preview_rows)} nội dung từ đề cương. Chưa phát hiện 'giao cho ai' trong file, "
            "bạn gán người nhận ở bước 2 trước khi tạo.",
            "info",
        )
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _update_task_status_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    task_item_id = request.form.get("task_item_id", "").strip()
    query = TaskAssignment.query.filter_by(task_id=tid, user_id=session["uid"])
    if task_item_id.isdigit():
        query = query.filter_by(task_item_id=int(task_item_id))
    else:
        query = query.filter(TaskAssignment.task_item_id.is_(None))
    assignment = query.first()
    if not assignment:
        flash("Bạn không được giao nội dung này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    assignment.status = "in_progress"
    assignment.updated_at = datetime.now()
    db.session.commit()
    flash("Đã tiếp nhận công việc.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _submit_task_report_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    mode = _task_mode(task)
    item = None
    query = TaskAssignment.query.filter_by(task_id=tid, user_id=session["uid"])
    task_item_id = request.form.get("task_item_id", "").strip()
    if mode == "OUTLINE":
        if not task_item_id.isdigit():
            flash("Thiếu đầu mục cần báo cáo.", "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        item = TaskItem.query.filter_by(id=int(task_item_id), task_id=tid).first()
        if not item:
            flash("Không tìm thấy đầu mục cần báo cáo.", "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        query = query.filter_by(task_item_id=item.id)
    else:
        query = query.filter(TaskAssignment.task_item_id.is_(None))

    assignment = query.first()
    if not assignment:
        flash("Bạn không được giao nội dung này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    narrative = (request.form.get("report_content") or request.form.get("report_narrative") or "").strip()
    report_file = request.files.get("report_file")
    numeric_value = None
    payload = {}
    structured_submission = None
    current_user = db.session.get(User, session["uid"])

    if mode == "OUTLINE" and item and item.report_kind == "number":
        # Nhận số liệu theo từng ô trống (report_number_value_<blank_id>)
        per_field_values = {}
        for field_key, raw_field in request.form.items():
            if field_key.startswith("report_number_value_"):
                field_idx = field_key[len("report_number_value_"):]
                field_text = str(raw_field or "").strip()
                if field_text:
                    parsed = _parse_outline_blank_value(field_text)
                    if parsed is None:
                        flash("Số liệu không hợp lệ.", "danger")
                        return redirect(url_for("tasks_bp.task_detail", tid=tid))
                    per_field_values[field_idx] = parsed
        raw_value = (request.form.get("report_number") or "").strip()
        if per_field_values:
            if not raw_value:
                raw_value = str(next(iter(per_field_values.values())))
            payload["values"] = per_field_values
            numeric_value = _outline_blank_numeric(raw_value)
            payload["reported_value"] = numeric_value
        else:
            if not raw_value:
                flash("Cần nhập số liệu cho đầu mục này.", "danger")
                return redirect(url_for("tasks_bp.task_detail", tid=tid))
            numeric_value = _outline_blank_numeric(raw_value)
            if numeric_value is None:
                flash("Số liệu không hợp lệ.", "danger")
                return redirect(url_for("tasks_bp.task_detail", tid=tid))
            payload["reported_value"] = numeric_value

    if mode == "FORM":
        missing_labels = []
        visible_form_fields = _task_form_fields_for_user(task, current_user)
        if not visible_form_fields:
            flash("Bạn chưa được giao trường dữ liệu nào trong biểu mẫu này.", "warning")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        for field in visible_form_fields:
            field_key = f"form_field_{field.field_key}"
            field_type = _normalize_task_form_field_type(field.field_type)
            if field_type == "checkbox":
                value = request.form.getlist(field_key)
            else:
                value = (request.form.get(field_key) or "").strip()
            if field_type == "number" and not _task_form_value_is_empty(value):
                try:
                    if isinstance(value, str):
                        value = float(value.replace(",", ""))
                except ValueError:
                    flash(f"Trường {field.field_label} phải là số hợp lệ.", "danger")
                    return redirect(url_for("tasks_bp.task_detail", tid=tid))
            if field_type == "table" and isinstance(value, str):
                table_rows = []
                for line in value.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    table_rows.append([cell.strip() for cell in line.split("|")])
                value = table_rows
            if getattr(field, "is_required", False) and _task_form_value_is_empty(value):
                missing_labels.append(field.field_label)
            payload[field.field_key] = value
        if missing_labels:
            flash("Cần điền các trường bắt buộc: " + ", ".join(missing_labels) + ".", "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        narrative = ""
    elif mode == "FILE":
        try:
            structured_submission = _parse_structured_file_report_submission(
                task,
                assignment,
                current_user,
                request.form,
                report_file,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        if structured_submission:
            narrative = structured_submission["narrative"]
            numeric_value = structured_submission["numeric_value"]
            payload = structured_submission["payload"]

    if mode != "FORM" and not narrative and not report_file and numeric_value is None:
        if not structured_submission:
            flash("Cần nhập nội dung hoặc đính kèm tệp báo cáo.", "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))

    submission = TaskSubmission(
        task_id=task.id,
        task_item_id=getattr(item, "id", None),
        assignment_id=assignment.id,
        submitted_by=session["uid"],
        submission_type=mode,
        status="submitted",
        narrative_content=narrative or None,
        numeric_value=numeric_value,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        submitted_at=datetime.now(),
    )
    current_cycle = _task_current_cycle(task)
    if current_cycle:
        submission.cycle_key = str(current_cycle.get("key") or "")[:50] or None
        submission.cycle_label = str(current_cycle.get("label") or "")[:100] or None
    db.session.add(submission)
    db.session.flush()

    if report_file and report_file.filename:
        file_meta = _store_uploaded_task_file(report_file, task.id, assignment.id, prefix="submission")
        if file_meta:
            db.session.add(
                TaskSubmissionFile(
                    submission_id=submission.id,
                    original_name=file_meta["original_name"],
                    stored_name=file_meta["stored_name"],
                    stored_path=file_meta["stored_path"],
                    file_ext=file_meta["file_ext"],
                    mime_type=file_meta["mime_type"],
                    file_size=file_meta["file_size"],
                )
            )
            submission.attachment_name = file_meta["original_name"]
            submission.attachment_path = file_meta["stored_path"]
            assignment.result_file = file_meta["stored_name"]
            if structured_submission:
                payload["attachment_name"] = file_meta["original_name"]

    assignment.status = "submitted"
    assignment.submitted_at = datetime.now()
    assignment.last_submission_id = submission.id
    assignment.report_payload_json = json.dumps(
        {
            "mode": payload.get("mode") if isinstance(payload, dict) else None,
            "narrative": narrative,
            "numeric_value": numeric_value,
            "payload": payload,
            "values": payload.get("values", {}) if isinstance(payload, dict) else {},
            "attachment_name": payload.get("attachment_name", "") if isinstance(payload, dict) else "",
            "submitted_at": submission.submitted_at.strftime("%d/%m/%Y %H:%M"),
        },
        ensure_ascii=False,
    )
    assignment.updated_at = datetime.now()
    _sync_assignment_group_submission(
        task,
        assignment,
        submission,
        report_payload_json=assignment.report_payload_json or "",
        result_file=assignment.result_file or "",
        submitted_at=assignment.submitted_at,
        updated_at=assignment.updated_at,
        status="submitted",
    )

    comment_text = narrative or ('Đã cập nhật biểu mẫu báo cáo' if structured_submission else ('Đã nộp biểu mẫu' if mode == 'FORM' else 'Đã nộp báo cáo'))
    if structured_submission:
        comment_text = _build_structured_task_report_comment(_load_task_report_schema(task), payload)
    db.session.add(
        TaskComment(
            task_id=task.id,
            user_id=session["uid"],
            user_name=session.get("fullname", "Người dùng"),
            content=f"[BÁO CÁO] {comment_text}",
        )
    )
    _propagate_submission_to_linked_items(task, item, assignment, submission)
    db.session.commit()
    flash("Đã gửi báo cáo.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _export_form_task_v2(tid):
    if Workbook is None:
        flash("Máy chủ chưa cài thư viện xuất Excel.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
        or _can_watch_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền xuất dữ liệu biểu mẫu.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    fields, rows = _build_form_task_rows(task, session["uid"])
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Du lieu"
    headers = ["Đơn vị", "Người nhận", "Trạng thái", "Thời điểm nộp"]
    headers.extend([field.field_label for field in fields])
    sheet.append(headers)

    for row in rows:
        user = getattr(row["assignment"], "user", None)
        user_name = getattr(user, "fullname", None) or getattr(user, "username", None) or ""
        unit_name = _task_assignee_unit_name(user) if user else ""
        submission = row["submission"]
        payload = row["payload"] or {}
        data_row = [
            unit_name,
            user_name,
            _task_assignment_status_label(row["assignment"].status),
            submission.submitted_at.strftime("%d/%m/%Y %H:%M") if submission and submission.submitted_at else "",
        ]
        for field in fields:
            value = payload.get(field.field_key, "")
            if isinstance(value, list):
                if value and isinstance(value[0], list):
                    value = " || ".join(" | ".join(str(cell) for cell in item) for item in value)
                else:
                    value = ", ".join(str(item) for item in value)
            data_row.append(value)
        sheet.append(data_row)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    safe_name = secure_filename(task.title or f"task_{task.id}") or f"task_{task.id}"
    return send_file(
        output,
        as_attachment=True,
        download_name=f"du_lieu_bieu_mau_{safe_name}_{task.id}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

def _build_outline_progress_matrix(task, current_uid):
    """Ma trận tiến độ: hàng = đầu mục, cột = đơn vị nhận việc."""
    rows = _parse_outline_item_rows(task, current_uid)
    unit_names = []
    for row in rows:
        for assignment in row["assignments"]:
            user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
            unit_name = _task_assignee_unit_name(user)
            if unit_name not in unit_names:
                unit_names.append(unit_name)
    unit_names.sort(key=lambda name: remove_accents(name).lower())

    matrix_rows = []
    for row in rows:
        item = row["item"]
        cells = []
        item_submitted = 0
        item_total = len(row["assignments"])
        for unit_name in unit_names:
            unit_assignments = []
            for assignment in row["assignments"]:
                user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
                if _task_assignee_unit_name(user) == unit_name:
                    unit_assignments.append(assignment)
            unit_submitted = sum(1 for assignment in unit_assignments if _task_is_submitted(assignment))
            item_submitted += unit_submitted
            cell_numbers = []
            for assignment in unit_assignments:
                submission = row["latest_submissions"].get(assignment.id)
                if not submission or item.report_kind != "number":
                    continue
                values = _outline_submission_values(submission)
                first_value = next(iter(values.values()), None)
                cell_numbers.append(
                    {
                        "unit_name": unit_name,
                        "values": values,
                        "first_value": first_value,
                        "numeric": _outline_blank_numeric(first_value),
                        "submitted": _task_is_submitted(assignment),
                    }
                )
            cells.append(
                {
                    "unit_name": unit_name,
                    "submitted_count": unit_submitted,
                    "total_count": len(unit_assignments),
                    "done": bool(unit_assignments) and unit_submitted >= len(unit_assignments),
                    "numbers": cell_numbers,
                    "assignments": [
                        {
                            "assignment": assignment,
                            "status": assignment.status,
                            "status_label": _task_assignment_status_label(assignment.status),
                            "status_class": _task_assignment_status_class(assignment.status),
                            "submitted": _task_is_submitted(assignment),
                            "submission": row["latest_submissions"].get(assignment.id),
                        }
                        for assignment in unit_assignments
                    ],
                }
            )
        aggregate_total = None
        aggregate_count = 0
        if item.report_kind == "number":
            numeric_values = []
            for cell in cells:
                for number in cell["numbers"]:
                    if number.get("numeric") is not None:
                        numeric_values.append(number["numeric"])
            aggregate_count = len(numeric_values)
            if numeric_values:
                aggregate_total = sum(numeric_values)
        matrix_rows.append(
            {
                "item": item,
                "cells": cells,
                "submitted_count": item_submitted,
                "total_count": item_total,
                "done": item_total > 0 and item_submitted >= item_total,
                "percent": round(item_submitted / item_total * 100) if item_total else 0,
                "aggregate_total": aggregate_total,
                "aggregate_count": aggregate_count,
            }
        )

    total_submitted = sum(matrix_row["submitted_count"] for matrix_row in matrix_rows)
    total_count = sum(matrix_row["total_count"] for matrix_row in matrix_rows)
    return {
        "unit_names": unit_names,
        "rows": matrix_rows,
        "total_submitted": total_submitted,
        "total_count": total_count,
        "percent": round(total_submitted / total_count * 100) if total_count else 0,
    }

def _export_outline_word_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    if _task_mode(task) != "OUTLINE":
        flash("Công việc này không phải dạng báo cáo văn bản theo đề cương.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
        or _can_watch_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền xuất báo cáo tổng hợp.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if DocxDocument is None:
        flash("Máy chủ chưa cài thư viện tạo file Word.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    rows = _parse_outline_item_rows(task, session["uid"])
    table_schema_map = _outline_table_schema_map(task)
    document = DocxDocument()
    document.add_heading(str(task.title or f"Công việc #{task.id}"), level=0)

    meta_parts = []
    if task.author_name:
        meta_parts.append(f"Đơn vị giao việc: {task.author_name}")
    if task.deadline:
        meta_parts.append(f"Hạn nộp: {task.deadline.strftime('%d/%m/%Y')}")
    if task.priority:
        meta_parts.append(f"Ưu tiên: {task.priority}")
    if meta_parts:
        meta_paragraph = document.add_paragraph()
        meta_run = meta_paragraph.add_run(" — ".join(meta_parts))
        meta_run.bold = True
    if task.content:
        document.add_paragraph(str(task.content))

    if not rows:
        document.add_paragraph("Chưa có đầu mục nào được thiết lập cho công việc này.")
    for index, row in enumerate(rows, start=1):
        item = row["item"]
        item_code = str(getattr(item, "item_code", None) or index)
        content = str(getattr(item, "content", "") or "")
        document.add_heading(f"{item_code}. {item.title}", level=1)
        # Tái hiện bảng (chỉ các cột được tích hiển thị) nếu đầu mục từ đề cương dạng bảng
        item_table_cells = _outline_item_table_cells(item)
        if table_schema_map and item_table_cells:
            columns = sorted(table_schema_map.values(), key=lambda col: int(col.get("index") or 0))
            columns = [col for col in columns if col.get("visible")]
            if columns:
                outline_table = document.add_table(rows=2, cols=len(columns))
                outline_table.style = "Table Grid"
                for col_index, col in enumerate(columns):
                    outline_table.rows[0].cells[col_index].text = str(col.get("header") or "")
                    value = str(item_table_cells.get(str(col.get("index")), "") or "").strip()
                    if not value and col.get("role") == "content":
                        value = content
                    outline_table.rows[1].cells[col_index].text = value
        if not row["assignments"]:
            document.add_paragraph("Chưa giao đơn vị nào cho đầu mục này.")
        synthesis = _task_item_synthesis_text(item)
        if synthesis:
            document.add_paragraph(synthesis)
        number_fields = _outline_item_number_fields(item)
        submitted_with_values = []
        for assignment in row["assignments"]:
            submission = row["latest_submissions"].get(assignment.id)
            if not submission:
                continue
            user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
            submitted_with_values.append((assignment, submission, user, _outline_submission_values(submission)))
        # Văn bản tổng hợp: nội dung gốc với số liệu đã nộp ghép vào
        if item.report_kind == "number" and number_fields and submitted_with_values:
            merged_parts = []
            for position, (assignment, submission, user, values) in enumerate(submitted_with_values, start=1):
                unit_name = _task_assignee_unit_name(user)
                merged = _outline_merged_content(content, number_fields, values)
                merged_parts.append(f"Số liệu {position} - {unit_name}: {merged.strip()}")
            merged_paragraph = document.add_paragraph()
            merged_run = merged_paragraph.add_run("\n".join(merged_parts))
            merged_run.bold = True
            # Cộng gộp khi quản trị bật
            if item.allow_aggregate:
                numeric_values = [
                    _outline_blank_numeric(value)
                    for values in (v for _, _, _, v in submitted_with_values)
                    for value in values.values()
                ]
                numeric_values = [value for value in numeric_values if value is not None]
                if numeric_values:
                    aggregate_paragraph = document.add_paragraph()
                    aggregate_run = aggregate_paragraph.add_run(
                        f"Tổng cộng: {sum(numeric_values):,.0f}".replace(",", ".")
                    )
                    aggregate_run.bold = True
        # Đã có văn bản tổng hợp của quản trị -> không lặp lại nội dung từng đơn vị.
        if synthesis:
            continue
        for assignment in row["assignments"]:
            user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
            unit_name = _task_assignee_unit_name(user)
            user_name = getattr(user, "fullname", None) or getattr(user, "username", None) or "Cán bộ"
            submission = row["latest_submissions"].get(assignment.id)
            status_label = _task_assignment_status_label(assignment.status)
            header = document.add_paragraph()
            header.add_run(f"{unit_name} — {user_name} ({status_label})").bold = True
            if not submission:
                document.add_paragraph("Chưa có nội dung báo cáo.")
                continue
            if item.report_kind == "number" and number_fields:
                values = _outline_submission_values(submission)
                field_lines = []
                for field in number_fields:
                    blank_id = field.get("blank_id")
                    submitted = values.get(str(blank_id), values.get(blank_id, ""))
                    if submitted in (None, ""):
                        submitted = field.get("value", "")
                    field_lines.append(f"- {field.get('label', '')}: {submitted} {field.get('unit', '')}".strip())
                if field_lines:
                    document.add_paragraph("\n".join(field_lines))
            elif item.report_kind == "number" and submission.numeric_value is not None:
                document.add_paragraph(f"Số liệu: {submission.numeric_value:g}")
            if submission.narrative_content:
                document.add_paragraph(str(submission.narrative_content))
            for file in (getattr(submission, "files", None) or []):
                document.add_paragraph(f"File minh chứng: {file.original_name or file.stored_name}")
            if getattr(submission, "submitted_at", None):
                submitted_paragraph = document.add_paragraph()
                submitted_run = submitted_paragraph.add_run(
                    f"(Nộp lúc {submission.submitted_at.strftime('%d/%m/%Y %H:%M')})"
                )
                submitted_run.italic = True

    output = io.BytesIO()
    document.save(output)
    output.seek(0)
    safe_name = secure_filename(task.title or f"task_{task.id}") or f"task_{task.id}"
    return send_file(
        output,
        as_attachment=True,
        download_name=f"bao_cao_tong_hop_{safe_name}_{task.id}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

@tasks_bp.route("/tasks/<int:tid>/items/<int:item_id>/aggregate", methods=["POST"])
def toggle_task_item_aggregate(tid, item_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    item = TaskItem.query.filter_by(id=item_id, task_id=tid).first()
    if not item:
        flash("Không tìm thấy đầu mục.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage:
        flash("Bạn không có quyền thay đổi cài đặt đầu mục này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    item.allow_aggregate = not bool(item.allow_aggregate)
    item.updated_at = datetime.now()
    db.session.commit()
    flash("Đã bật cộng gộp số liệu cho đầu mục." if item.allow_aggregate else "Đã tắt cộng gộp số liệu.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid) + "#pane-outline-matrix")

@tasks_bp.route("/tasks/<int:tid>/items/<int:item_id>/synthesis-data")
def task_item_synthesis_data(tid, item_id):
    """Dữ liệu cho màn tổng hợp: từng đơn vị đã nộp gì cho đầu mục này."""
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Chưa đăng nhập."}), 401

    _ensure_task_schema()
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return jsonify({"ok": False, "error": "Không tìm thấy công việc."}), 404
    item = TaskItem.query.filter_by(id=item_id, task_id=tid).first()
    if not item:
        return jsonify({"ok": False, "error": "Không tìm thấy đầu mục."}), 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage:
        return jsonify({"ok": False, "error": "Bạn không có quyền tổng hợp báo cáo."}), 403

    number_fields = _outline_item_number_fields(item)
    content = str(getattr(item, "content", "") or "")
    assignments = _task_assignments_query(task, task_item_id=item.id).all()
    submissions = []
    for assignment in assignments:
        submission = _latest_assignment_submission(assignment)
        user = getattr(assignment, "user", None) or db.session.get(User, getattr(assignment, "user_id", None))
        values = _outline_submission_values(submission)
        merged_text = ""
        if item.report_kind == "number" and number_fields and submission:
            merged_text = _outline_merged_content(content, number_fields, values).strip()
        files = []
        for file in (getattr(submission, "files", None) or []):
            files.append({"name": file.original_name or file.stored_name, "id": file.id})
        submissions.append(
            {
                "assignment_id": assignment.id,
                "unit_name": _task_assignee_unit_name(user),
                "submitter_name": getattr(user, "fullname", None) or getattr(user, "username", None) or "Cán bộ",
                "status": _task_assignment_status_label(assignment.status),
                "submitted_at": submission.submitted_at.strftime("%d/%m/%Y %H:%M") if submission and submission.submitted_at else "",
                "narrative": str(getattr(submission, "narrative_content", "") or "").strip() if submission else "",
                "merged_text": merged_text,
                "numeric_value": ("%g" % submission.numeric_value) if submission and submission.numeric_value is not None else "",
                "files": files,
                "has_submission": bool(submission and (_submission_has_report_content(submission) or merged_text or files)),
            }
        )

    return jsonify(
        {
            "ok": True,
            "item": {
                "id": item.id,
                "item_code": getattr(item, "item_code", None) or "",
                "title": getattr(item, "title", "") or "",
                "report_kind": item.report_kind or "narrative",
                "synthesis": _task_item_synthesis_text(item),
                "synthesis_updated_at": item.synthesis_updated_at.strftime("%d/%m/%Y %H:%M") if getattr(item, "synthesis_updated_at", None) else "",
            },
            "submissions": submissions,
        }
    )

@tasks_bp.route("/tasks/<int:tid>/items/<int:item_id>/synthesize", methods=["POST"])
def save_task_item_synthesis(tid, item_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    item = TaskItem.query.filter_by(id=item_id, task_id=tid).first()
    if not item:
        flash("Không tìm thấy đầu mục.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage:
        flash("Bạn không có quyền tổng hợp báo cáo của đầu mục này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    synthesis = (request.form.get("synthesis_content") or "").strip()
    item.synthesis_content = synthesis or None
    item.synthesis_updated_at = datetime.now() if synthesis else None
    item.updated_at = datetime.now()
    db.session.commit()
    if synthesis:
        flash(f"Đã lưu văn bản tổng hợp cho đầu mục {item.item_code or item.title}.", "success")
    else:
        flash(f"Đã xóa văn bản tổng hợp của đầu mục {item.item_code or item.title} — xuất Word sẽ gộp tự động như cũ.", "warning")
    return redirect(url_for("tasks_bp.task_detail", tid=tid) + "#pane-outline-matrix")

def _return_task_assignment_v2(tid, assignment_id):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    assignment = TaskAssignment.query.filter_by(id=assignment_id, task_id=tid).first()
    if not assignment:
        flash("Không tìm thấy phần việc cần trả lại.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
        or _can_watch_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền trả lại phần việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    reason = (request.form.get("return_reason") or "").strip()[:500]
    assignment.status = "returned"
    assignment.returned_at = datetime.now()
    assignment.updated_at = datetime.now()
    db.session.add(
        TaskComment(
            task_id=task.id,
            user_id=session["uid"],
            user_name=session.get("fullname", "Quản trị"),
            content=f"[TRẢ LẠI] {reason or 'Yêu cầu bổ sung nội dung'}",
        )
    )
    db.session.commit()
    flash("Đã trả lại phần việc để bổ sung.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _create_task_google_form_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền tạo Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if _task_mode(task) != "FORM":
        flash("Công việc này không dùng chế độ biểu mẫu.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        builder_schema = _parse_google_form_builder_schema(
            getattr(task, "google_form_builder_json", None),
            fallback_title=task.title or "Biểu mẫu",
            fallback_description=task.content or "",
        )
        service = _task_google_form_manage_service()
        runtime = create_google_form(
            service,
            builder_schema,
            title=task.title or builder_schema.get("form_info", {}).get("title") or "Biểu mẫu",
            description=task.content or builder_schema.get("form_info", {}).get("description") or "",
        )
    except Exception as exc:
        flash(str(exc) or "Không thể tạo Google Form thật.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.form_provider = "google"
    task.google_form_builder_json = _json_dump(builder_schema)
    task.google_form_id = str(runtime.get("form_id") or "").strip() or None
    task.google_form_url = str(runtime.get("form_url") or "").strip() or task.google_form_url
    task.google_form_match_mode = _normalize_google_form_match_mode(
        task.google_form_match_mode or builder_schema.get("matching", {}).get("mode") or "unit"
    )
    task.google_form_match_field = str(
        task.google_form_match_field or builder_schema.get("matching", {}).get("match_field") or ""
    ).strip()[:255] or None
    task.google_form_runtime_json = _json_dump(_task_google_form_runtime_payload(task, runtime.get("raw"), runtime))
    actual_fields, _question_map = parse_google_form_definition(runtime.get("raw") or {})
    field_defs = _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema) if actual_fields else _hydrate_google_form_fields(builder_schema)
    assignment_scope = _task_assignment_scope_lists(task)
    assignees = [assignment.user for assignment in _task_assignment_records(task) if getattr(assignment, "user", None)]
    try:
        _validate_task_visibility_before_publish(
            "FORM",
            _dedupe_users(assignees),
            assign_type=assignment_scope["assign_type"],
            domain=assignment_scope["domain"],
            role_ids=assignment_scope["role_ids"],
            user_ids=assignment_scope["user_ids"],
            field_defs=field_defs,
            ignored_form_field_labels=[task.google_form_match_field] if task.google_form_match_field else [],
        )
    except ValueError as visibility_error:
        flash(str(visibility_error), "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if actual_fields:
        _replace_task_form_fields(task, field_defs)
    db.session.add(task)
    db.session.commit()
    flash("Đã tạo Google Form thật từ builder.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _update_task_google_form_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền cập nhật Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if _task_mode(task) != "FORM":
        flash("Công việc này không dùng chế độ biểu mẫu.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        builder_schema = _parse_google_form_builder_schema(
            request.form.get("google_form_builder_json") or getattr(task, "google_form_builder_json", None),
            fallback_title=task.title or "Biểu mẫu",
            fallback_description=task.content or "",
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.form_provider = "google"
    task.google_form_builder_json = _json_dump(builder_schema)
    task.google_form_match_mode = _normalize_google_form_match_mode(
        builder_schema.get("matching", {}).get("mode") or task.google_form_match_mode or "unit"
    )
    task.google_form_match_field = str(
        builder_schema.get("matching", {}).get("match_field") or task.google_form_match_field or ""
    ).strip()[:255] or None

    assignment_scope = _task_assignment_scope_lists(task)
    assignees = _dedupe_users([assignment.user for assignment in _task_assignment_records(task) if getattr(assignment, "user", None)])
    if not getattr(task, "google_form_id", None):
        hydrated_fields = _hydrate_google_form_fields(builder_schema)
        try:
            _validate_task_visibility_before_publish(
                "FORM",
                assignees,
                assign_type=assignment_scope["assign_type"],
                domain=assignment_scope["domain"],
                role_ids=assignment_scope["role_ids"],
                user_ids=assignment_scope["user_ids"],
                field_defs=hydrated_fields,
                ignored_form_field_labels=[task.google_form_match_field] if task.google_form_match_field else [],
            )
        except ValueError as visibility_error:
            flash(str(visibility_error), "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        if hydrated_fields:
            _replace_task_form_fields(task, hydrated_fields)
        db.session.add(task)
        db.session.commit()
        flash("Đã lưu schema builder Google Form.", "success")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        service = _task_google_form_manage_service()
        runtime = update_google_form(
            service,
            task.google_form_id,
            builder_schema,
            revision_id=_task_google_form_runtime(task).get("revision_id"),
        )
    except Exception as exc:
        flash(str(exc) or "Không thể cập nhật Google Form thật.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.google_form_url = str(runtime.get("form_url") or task.google_form_url or "").strip() or None
    task.google_form_runtime_json = _json_dump(_task_google_form_runtime_payload(task, runtime.get("raw"), runtime))
    actual_fields, _question_map = parse_google_form_definition(runtime.get("raw") or {})
    field_defs = _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema) if actual_fields else []
    try:
        _validate_task_visibility_before_publish(
            "FORM",
            assignees,
            assign_type=assignment_scope["assign_type"],
            domain=assignment_scope["domain"],
            role_ids=assignment_scope["role_ids"],
            user_ids=assignment_scope["user_ids"],
            field_defs=field_defs,
            ignored_form_field_labels=[task.google_form_match_field] if task.google_form_match_field else [],
        )
    except ValueError as visibility_error:
        flash(str(visibility_error), "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if actual_fields:
        _replace_task_form_fields(task, field_defs)
    db.session.add(task)
    db.session.commit()
    flash("Đã cập nhật Google Form thật theo builder.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _publish_task_google_form_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền phát hành Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if not getattr(task, "google_form_id", None):
        flash("Công việc này chưa có Google Form thật để phát hành.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    is_published = str(request.form.get("is_published") or "true").strip().lower() in {"1", "true", "yes", "on"}
    accept_responses = str(request.form.get("accept_responses") or "true").strip().lower() in {"1", "true", "yes", "on"}
    try:
        service = _task_google_form_manage_service()
        publish_result = publish_google_form(
            service,
            task.google_form_id,
            is_published=is_published,
            accept_responses=accept_responses,
        )
    except Exception as exc:
        flash(str(exc) or "Không thể đổi trạng thái phát hành Google Form.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    runtime = _task_google_form_runtime(task)
    runtime["publish_settings"] = publish_result.get("publishSettings") or runtime.get("publish_settings") or {}
    task.google_form_runtime_json = _json_dump(runtime)
    db.session.add(task)
    db.session.commit()
    flash("Đã cập nhật trạng thái phát hành Google Form.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _import_task_google_form_structure_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền nhập cấu trúc Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    form_reference = str(request.form.get("google_form_url") or getattr(task, "google_form_url", None) or getattr(task, "google_form_id", None) or "").strip()
    form_id = extract_google_form_id(form_reference)
    if not form_id:
        flash("Không nhận diện được Google Form URL hoặc form ID.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        service = build_google_forms_service(current_app.config)
        imported = load_google_form_into_builder(service, form_id)
    except Exception as exc:
        flash(str(exc) or "Không thể nhập cấu trúc từ Google Form.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    builder_schema = imported.get("builder_schema") if isinstance(imported, dict) else {}
    form_payload = imported.get("form_payload") if isinstance(imported, dict) else {}
    if not isinstance(builder_schema, dict):
        flash("Google Form không trả về schema builder hợp lệ.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    builder_schema.setdefault("matching", {})
    builder_schema["matching"]["mode"] = _normalize_google_form_match_mode(
        request.form.get("google_form_match_mode") or task.google_form_match_mode or builder_schema["matching"].get("mode") or "unit"
    )
    builder_schema["matching"]["match_field"] = str(
        request.form.get("google_form_match_field") or task.google_form_match_field or builder_schema["matching"].get("match_field") or ""
    ).strip()[:255]
    builder_schema = _normalize_google_form_builder_schema_with_targets(
        builder_schema,
        fallback_title=task.title or "Biểu mẫu",
        fallback_description=task.content or "",
    )

    task.form_provider = "google"
    task.google_form_id = form_id
    task.google_form_url = str(
        (form_payload.get("responderUri") if isinstance(form_payload, dict) else "") or form_reference
    ).strip()[:500] or None
    task.google_form_match_mode = builder_schema.get("matching", {}).get("mode") or "unit"
    task.google_form_match_field = builder_schema.get("matching", {}).get("match_field") or None
    task.google_form_builder_json = _json_dump(builder_schema)
    task.google_form_runtime_json = _json_dump(
        _task_google_form_runtime_payload(task, form_payload, base_runtime=_task_google_form_runtime(task))
    )
    actual_fields, _question_map = parse_google_form_definition(form_payload or {})
    if actual_fields:
        _replace_task_form_fields(task, _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema))
    db.session.add(task)
    db.session.commit()
    flash("Đã nhập cấu trúc từ Google Form vào builder.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _sync_google_form_task_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    is_executor = TaskAssignment.query.filter_by(task_id=task.id, user_id=session["uid"]).first() is not None
    if not (can_manage_task_view or is_executor):
        flash("Bạn không có quyền đồng bộ phản hồi Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if not getattr(task, "google_form_id", None):
        flash("Công việc này chưa có Google Form thật để đồng bộ.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        service = build_google_forms_service(current_app.config)
        form_payload = fetch_google_form_definition(service, task.google_form_id)
        responses_payload = fetch_google_form_responses(service, task.google_form_id)
        actual_fields, parsed_responses = parse_google_form_responses(form_payload, responses_payload)
    except Exception as exc:
        flash(str(exc) or "Không thể đồng bộ phản hồi Google Form.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if actual_fields:
        builder_schema = _task_google_form_builder(task)
        _replace_task_form_fields(task, _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema))

    matched_total = 0
    unmatched_total = 0
    ignored_scoped_fields_total = 0
    ignored_scoped_response_ids = []
    now = datetime.now()
    for response_row in parsed_responses:
        assignment = _match_google_form_response_to_assignment(task, response_row)
        if not assignment:
            unmatched_total += 1
            continue
        filtered_response = _filter_google_form_response_for_assignment(task, assignment, response_row)
        filtered_payload = filtered_response.get("payload") or {}
        filtered_payload_by_label = filtered_response.get("payload_by_label") or {}
        ignored_keys = list(filtered_response.get("ignored_keys") or [])
        if ignored_keys:
            ignored_scoped_fields_total += len(ignored_keys)
            ignored_scoped_response_ids.append(
                {
                    "response_id": response_row.get("response_id"),
                    "user_id": getattr(assignment, "user_id", None),
                    "ignored_keys": ignored_keys,
                }
            )

        submission = (
            TaskSubmission.query.filter_by(
                task_id=task.id,
                assignment_id=assignment.id,
                external_source="google_form",
                external_submission_id=response_row.get("response_id"),
            )
            .order_by(TaskSubmission.id.desc())
            .first()
        )
        if not submission:
            submission = TaskSubmission(
                task_id=task.id,
                assignment_id=assignment.id,
                submitted_by=assignment.user_id,
                external_source="google_form",
                external_submission_id=response_row.get("response_id"),
            )
            db.session.add(submission)
            db.session.flush()

        submission.submission_type = "FORM"
        submission.status = "submitted"
        submission.payload_json = _json_dump(filtered_payload)
        submission.submitted_at = response_row.get("submitted_at") or now
        submission.synced_at = now

        assignment.status = "submitted"
        assignment.submitted_at = submission.submitted_at
        assignment.last_submission_id = submission.id
        assignment.report_payload_json = _json_dump(
            {
                "mode": "google_form_sync",
                "payload": filtered_payload,
                "payload_by_label": filtered_payload_by_label,
                "external_submission_id": response_row.get("response_id"),
                "ignored_scoped_keys": ignored_keys,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
            }
        )
        assignment.updated_at = now
        _sync_assignment_group_submission(
            task,
            assignment,
            submission,
            report_payload_json=assignment.report_payload_json or "",
            result_file=assignment.result_file or "",
            submitted_at=assignment.submitted_at,
            updated_at=assignment.updated_at,
            status="submitted",
        )
        matched_total += 1

    sync_state = _task_google_form_sync_state(task)
    info = form_payload.get("info") if isinstance(form_payload.get("info"), dict) else {}
    sync_state.update(
        {
            "form_id": str(form_payload.get("formId") or task.google_form_id or "").strip(),
            "form_title": str(info.get("title") or sync_state.get("form_title") or task.title or "").strip(),
            "matched_total": matched_total,
            "unmatched_total": unmatched_total,
            "ignored_scoped_fields_total": ignored_scoped_fields_total,
            "ignored_scoped_response_ids": ignored_scoped_response_ids[:10],
            "last_sync_at": now.isoformat(),
        }
    )
    task.google_form_url = str(
        form_payload.get("responderUri") or task.google_form_url or f"https://docs.google.com/forms/d/{task.google_form_id}/viewform"
    ).strip()[:500] or None
    task.google_form_runtime_json = _json_dump(
        _task_google_form_runtime_payload(task, form_payload, base_runtime=_task_google_form_runtime(task))
    )
    task.google_form_sync_state_json = _json_dump(sync_state)
    db.session.add(task)
    db.session.commit()
    flash("Đã đồng bộ phản hồi Google Form vào công việc.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

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
    assignment_query = TaskAssignment.query.filter(TaskAssignment.task_id == task_id)
    form_field_query = TaskFormField.query.filter(TaskFormField.task_id == task_id)
    if task_item_id:
        participant_query = participant_query.filter(TaskParticipant.task_item_id == task_item_id)
        submission_query = submission_query.filter(TaskSubmission.task_item_id == task_item_id)
    else:
        participant_query = participant_query.filter(TaskParticipant.task_item_id.is_(None))
        submission_query = submission_query.filter(TaskSubmission.task_item_id.is_(None))
    submission_ids = [submission_id for submission_id, in submission_query.with_entities(TaskSubmission.id).all()]
    if submission_ids:
        TaskSubmissionFile.query.filter(TaskSubmissionFile.submission_id.in_(submission_ids)).delete(synchronize_session=False)
    # Gỡ tham chiếu last_submission_id trước khi xóa submission để tránh vi phạm
    # khóa ngoại task_assignment.last_submission_id -> task_submission.id
    # (PRAGMA foreign_keys=ON được bật ở mọi kết nối SQLite).
    TaskAssignment.query.filter(
        TaskAssignment.task_id == task_id,
        TaskAssignment.last_submission_id.isnot(None),
    ).update({TaskAssignment.last_submission_id: None}, synchronize_session=False)
    submission_query.delete(synchronize_session=False)
    # Xóa assignment sau khi đã xóa submission (submission.assignment_id trỏ vào
    # assignment) và trước khi xóa task_item (assignment.task_item_id trỏ vào item).
    assignment_query.delete(synchronize_session=False)
    participant_query.delete(synchronize_session=False)
    form_field_query.delete(synchronize_session=False)
    if getattr(task, "parent_task_id", None):
        TaskItem.query.filter_by(source_task_id=task.id).delete(synchronize_session=False)
    else:
        TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
    TaskComment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
    db.session.delete(task)

def _ensure_task_schema(run_runtime_backfill=False):
    try:
        apply_migrations(current_app)
    except Exception as migration_error:
        current_app.logger.warning(f"TASKS migration safeguard failed: {migration_error}")
    if not run_runtime_backfill:
        return
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

def _build_unit_report_summary(assigns, comments, deadline, report_snapshots=None):
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

        report_item = (report_snapshots or {}).get(getattr(assignment, "id", None)) or _assignment_report_snapshot(assignment, comments=comments)
        report_at = report_item.get("first_report_at")
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

def _task_import_submenu_items(active_key="drafts"):
    return [
        {
            "label": "Danh sách công việc",
            "href": url_for("tasks_bp.tasks"),
            "count": None,
            "active": active_key == "tasks",
        },
        {
            "label": "Nháp import",
            "href": url_for("tasks_bp.task_import_drafts"),
            "count": None,
            "active": active_key == "drafts",
        },
    ]

def _task_import_ai_runtime():
    # Chức năng Trợ lý AI đã bị gỡ: chỉ còn lõi phân tích quy tắc nội bộ (không cần internet/API key).
    return {
        "provider": "internal",
        "model": "",
        "label": "AI nội bộ",
        "configured": False,
    }

def _task_import_ai_catalog(item_type, items):
    catalog = []
    for item in items or []:
        catalog.append(
            {
                "type": item_type,
                "id": item.get("id"),
                "value": item.get("value"),
                "label": item.get("name") or item.get("label") or item.get("fullname") or item.get("username") or "",
            }
        )
    return catalog

def _task_import_history_entries(limit=80):
    tasks = (
        Task.query.options(joinedload(Task.assignments))
        .filter(Task.parent_task_id.is_(None))
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(limit)
        .all()
    )
    history_entries = []
    for task in tasks:
        title = str(getattr(task, "title", "") or "").strip()
        if not title:
            continue
        assignment_context = _infer_assignment_context(task)
        unit_domains = []
        if assignment_context.get("mode") == "unit":
            domain_value = str(assignment_context.get("domain") or getattr(task, "domain", "") or "").strip()
            if domain_value:
                unit_domains = [domain_value]
        assignment_rows = list(getattr(task, "assignments", None) or [])
        total_assignments = len(assignment_rows)
        submitted_assignments = sum(
            1
            for assignment in assignment_rows
            if str(getattr(assignment, "status", "") or "").strip().lower() in {"submitted", "completed"}
            or getattr(assignment, "submitted_at", None)
        )
        completed_assignments = sum(
            1
            for assignment in assignment_rows
            if str(getattr(assignment, "status", "") or "").strip().lower() == "completed"
            or getattr(assignment, "completed_at", None)
        )
        deadline = getattr(task, "deadline", None)
        on_time_assignments = 0
        late_assignments = 0
        if deadline:
            for assignment in assignment_rows:
                report_time = (
                    getattr(assignment, "completed_at", None)
                    or getattr(assignment, "submitted_at", None)
                )
                if not report_time:
                    continue
                if report_time.date() <= deadline:
                    on_time_assignments += 1
                else:
                    late_assignments += 1
        history_entries.append(
            {
                "title": title[:255],
                "category": str(getattr(task, "category", "") or "").strip()[:100],
                "domain": str(getattr(task, "domain", "") or "").strip()[:100],
                "assign_type": assignment_context.get("mode") or "",
                "unit_domains": unit_domains,
                "role_ids": list(assignment_context.get("role_ids") or []),
                "user_ids": list(assignment_context.get("user_ids") or [])[:8],
                "total_assignments": total_assignments,
                "submitted_assignments": submitted_assignments,
                "completed_assignments": completed_assignments,
                "submitted_rate": round((submitted_assignments / total_assignments), 4) if total_assignments else 0.0,
                "completed_rate": round((completed_assignments / total_assignments), 4) if total_assignments else 0.0,
                "on_time_assignments": on_time_assignments,
                "late_assignments": late_assignments,
                "on_time_rate": round((on_time_assignments / total_assignments), 4) if total_assignments and deadline else 0.0,
                "deadline_tracked": bool(deadline),
            }
        )
    return history_entries

def _task_import_active_workload_context():
    assignments = (
        TaskAssignment.query.options(
            joinedload(TaskAssignment.user),
            joinedload(TaskAssignment.task),
            joinedload(TaskAssignment.task_item),
        )
        .join(Task, TaskAssignment.task_id == Task.id)
        .filter(Task.parent_task_id.is_(None))
        .filter(TaskAssignment.user_id.isnot(None))
        .all()
    )

    today = datetime.now().date()
    user_map = {}
    role_map = {}
    unit_map = {}
    user_seen = set()
    role_seen = set()
    unit_seen = set()

    def ensure_bucket(mapping, key):
        return mapping.setdefault(
            key,
            {
                "active_assignments": 0,
                "overdue_assignments": 0,
                "due_soon_assignments": 0,
                "high_priority_assignments": 0,
                "titles": [],
            },
        )

    def push_title(bucket, title):
        title_text = str(title or "").strip()
        if not title_text or title_text in bucket["titles"]:
            return
        bucket["titles"].append(title_text)
        if len(bucket["titles"]) > 5:
            del bucket["titles"][5:]

    def apply_bucket(bucket, unique_key, title, deadline, priority):
        if unique_key in bucket_seen:
            return
        bucket_seen.add(unique_key)
        bucket["active_assignments"] += 1
        if deadline:
            if deadline < today:
                bucket["overdue_assignments"] += 1
            elif (deadline - today).days <= 3:
                bucket["due_soon_assignments"] += 1
        if str(priority or "").strip().lower() == "cao":
            bucket["high_priority_assignments"] += 1
        push_title(bucket, title)

    for assignment in assignments:
        user = getattr(assignment, "user", None)
        task = getattr(assignment, "task", None)
        if not user or not task or not getattr(user, "is_active", False):
            continue
        if _normalize_status(getattr(assignment, "status", "")) == COMPLETED_STATUS or getattr(assignment, "completed_at", None):
            continue

        task_item = getattr(assignment, "task_item", None)
        title_text = (
            getattr(task_item, "title", None)
            or getattr(assignment, "title_snapshot", None)
            or getattr(task, "title", None)
            or ""
        )
        deadline = getattr(task_item, "deadline", None) or getattr(task, "deadline", None)
        priority = getattr(task, "priority", None)
        task_key = (int(getattr(task, "id", 0) or 0), int(getattr(task_item, "id", 0) or 0))
        user_key = (int(getattr(user, "id", 0) or 0),) + task_key
        bucket_seen = user_seen
        apply_bucket(ensure_bucket(user_map, int(user.id)), user_key, title_text, deadline, priority)

        unit_identity = _task_unit_identity(user)
        unit_key_value = str(unit_identity.get("unit_domain") or unit_identity.get("unit_key") or "").strip()
        if unit_key_value:
            unit_scope_key = (unit_key_value, str(getattr(assignment, "assignee_type", "") or "user").strip().lower(), int(getattr(assignment, "role_id", 0) or 0)) + task_key
            bucket_seen = unit_seen
            apply_bucket(ensure_bucket(unit_map, unit_key_value), unit_scope_key, title_text, deadline, priority)

        role_id = int(getattr(user, "role_id", None) or getattr(assignment, "role_id", None) or 0)
        if role_id:
            role_scope_key = (role_id, unit_key_value) + task_key
            bucket_seen = role_seen
            apply_bucket(ensure_bucket(role_map, role_id), role_scope_key, title_text, deadline, priority)

    return {
        "user_workload_map": user_map,
        "role_workload_map": role_map,
        "unit_workload_map": unit_map,
    }

def _task_import_ai_context():
    pro_units = stable_form_category_options(_task_domain_options())
    task_fields = stable_form_category_options(_task_field_options())
    active_users = User.query.filter_by(is_active=True).order_by(User.fullname.asc()).all()
    roles = AppRole.query.order_by(AppRole.name.asc()).all()
    unit_lookup = {item["value"]: item["name"] for item in pro_units if item.get("value")}
    role_lookup = {role.id: role.name for role in roles}
    user_lookup = {user.id: user.fullname or user.username or f"UID {user.id}" for user in active_users}
    return {
        "unit_catalog": _task_import_ai_catalog("unit", pro_units),
        "field_catalog": _task_import_ai_catalog("field", task_fields),
        "role_catalog": [
            {
                "type": "role",
                "id": role.id,
                "label": role.name or "",
            }
            for role in roles
        ],
        "user_catalog": [
            {
                "type": "user",
                "id": user.id,
                "label": user.fullname or user.username or "",
            }
            for user in active_users
        ],
        "unit_lookup": unit_lookup,
        "role_lookup": role_lookup,
        "user_lookup": user_lookup,
        "recipient_catalog": [
            {
                "id": user.id,
                "label": user.fullname or user.username or f"UID {user.id}",
                "username": user.username or "",
                "role_id": user.role_id,
                "role_name": role_lookup.get(user.role_id, ""),
                "unit_domain": canonicalize_category_value(user.unit_area or user.unit_key or "", pro_units, prefer_stable=True),
                "unit_name": resolve_category_display(
                    canonicalize_category_value(user.unit_area or user.unit_key or "", pro_units, prefer_stable=True) or (user.unit_area or user.unit_key or ""),
                    pro_units,
                    fallback_label=user.unit_area or user.unit_key or "",
                ).get("display_name", "") if (user.unit_area or user.unit_key) else "",
                "unit_key": user.unit_key or "",
            }
            for user in active_users
        ],
        "history_entries": _task_import_history_entries(),
        **_task_import_active_workload_context(),
    }

def _task_import_ai_analysis(config, use_provider=False):
    # use_provider không còn tác dụng sau khi gỡ Trợ lý AI: luôn chạy phân tích quy tắc nội bộ.
    context = _task_import_ai_context()
    heuristic_analysis = analyze_task_import_config(config, context)
    heuristic_analysis["llm_meta"] = {
        "configured": False,
        "reason": "Trợ lý AI ngoài đã bị gỡ; chỉ dùng phân tích quy tắc nội bộ.",
    }
    return heuristic_analysis

def _can_manage_task_imports(perms=None):
    return bool(session.get("is_admin") or _can_process_task_module(perms))

def _task_import_drafts_query():
    return TaskImportDraft.query.order_by(TaskImportDraft.updated_at.desc(), TaskImportDraft.id.desc())

def _task_import_draft_or_404(draft_id):
    return TaskImportDraft.query.filter_by(id=draft_id).first()

def _task_import_draft_render_context(draft, active_key="drafts"):
    task_fields = _task_field_options()
    pro_units = _task_domain_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()
    active_users = User.query.filter_by(is_active=True).order_by(User.fullname.asc()).all()
    roles = AppRole.query.order_by(AppRole.name.asc()).all()
    config = _task_import_draft_working_config(draft)
    blueprint = _task_import_blueprint_from_config(config) or _task_import_draft_blueprint(draft)
    preview = workflow_blueprint_preview_data(blueprint) if blueprint else None
    stats = _task_import_config_stats(config)
    recipient_preview = _task_import_recipient_preview(config, users=active_users, roles=roles)
    return {
        "draft": draft,
        "config": config,
        "preview": preview,
        "draft_stats": stats,
        "recipient_preview": recipient_preview,
        "users": active_users,
        "roles": roles,
        "pro_units": stable_form_category_options(pro_units),
        "task_fields": task_fields,
        "task_types": stable_form_category_options(task_types),
        "priority_items": stable_form_category_options(priority_items),
        "workflow_blueprint_examples": workflow_blueprint_example_catalog(),
        "ai_runtime": _task_import_ai_runtime(),
        "status_label": _task_import_status_label(getattr(draft, "status", "")),
        "source_label": _task_import_source_label(getattr(draft, "source_type", "")),
        "sidebar_submenu_parent": "tasks",
        "sidebar_submenu_title": "Công việc",
        "sidebar_submenu_items": _task_import_submenu_items(active_key=active_key),
    }

def _task_import_drafts_page():
    perms = _current_perms()
    if not _can_manage_task_imports(perms):
        flash("Bạn không có quyền quản trị nháp import.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    draft_rows = []
    for draft in _task_import_drafts_query().all():
        config = _task_import_draft_working_config(draft)
        draft_rows.append(
            {
                "draft": draft,
                "config": config,
                "stats": _task_import_config_stats(config),
                "status_label": _task_import_status_label(draft.status),
                "source_label": _task_import_source_label(draft.source_type),
            }
        )

    return render_template(
        "task_import_drafts.html",
        draft_rows=draft_rows,
        workflow_blueprint_examples=workflow_blueprint_example_catalog(),
        sidebar_submenu_parent="tasks",
        sidebar_submenu_title="Công việc",
        sidebar_submenu_items=_task_import_submenu_items(active_key="drafts"),
    )

def _create_task_import_draft_v2():
    perms = _current_perms()
    if not _can_manage_task_imports(perms):
        flash("Bạn không có quyền tạo nháp import.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    source_type = str(request.form.get("source_type") or "").strip().lower()
    if source_type not in TASK_IMPORT_SOURCE_TYPES:
        flash("Chưa chọn nguồn import hợp lệ.", "danger")
        return redirect(url_for("tasks_bp.task_import_drafts"))

    source_name = ""
    source_ref = ""
    try:
        if source_type == "google_form_remote":
            source_ref = str(request.form.get("blueprint_form_reference") or "").strip()
            blueprint = _parse_reference_file_to_blueprint(None, source_type, form_reference=source_ref)
            source_name = str((blueprint or {}).get("title") or "Google Form").strip()[:255]
        elif source_type == "blueprint_json":
            raw_blueprint = (request.form.get("workflow_blueprint_json") or "").strip()
            if not raw_blueprint:
                raise ValueError("Cần nhập blueprint JSON trước khi tạo nháp.")
            blueprint = _parse_task_workflow_blueprint_payload(json.loads(raw_blueprint))
            source_name = str((blueprint or {}).get("title") or "Blueprint điều hành").strip()[:255]
            source_ref = "manual_blueprint"
        else:
            source_file = request.files.get("source_file")
            blueprint = _parse_reference_file_to_blueprint(source_file, source_type)
            source_name = str(getattr(source_file, "filename", "") or (blueprint or {}).get("title") or "").strip()[:255]
            source_ref = source_name
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tasks_bp.task_import_drafts"))
    except Exception as exc:
        flash(str(exc) or "Không thể tạo nháp import từ nguồn đã chọn.", "danger")
        return redirect(url_for("tasks_bp.task_import_drafts"))

    draft = TaskImportDraft(
        source_type=source_type,
        source_name=source_name,
        source_ref=source_ref,
        workflow_blueprint_json=_json_dump(blueprint),
        working_config_json=_json_dump(
            _task_import_working_config_from_blueprint(
                blueprint,
                source_type=source_type,
                source_name=source_name,
                source_ref=source_ref,
            )
        ),
        status="draft",
        created_by=session["uid"],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.session.add(draft)
    db.session.commit()
    flash("Đã tạo nháp import mới.", "success")
    return redirect(url_for("tasks_bp.task_import_draft_detail", draft_id=draft.id))

def _task_import_draft_detail_page(draft_id):
    perms = _current_perms()
    if not _can_manage_task_imports(perms):
        flash("Bạn không có quyền xem nháp import.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    draft = _task_import_draft_or_404(draft_id)
    if not draft:
        return "Not Found", 404

    return render_template("task_import_draft_detail.html", **_task_import_draft_render_context(draft))

def _save_task_import_draft_v2(draft_id):
    perms = _current_perms()
    if not _can_manage_task_imports(perms):
        flash("Bạn không có quyền cập nhật nháp import.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    draft = _task_import_draft_or_404(draft_id)
    if not draft:
        return "Not Found", 404
    if str(draft.status or "").strip().lower() == "published":
        flash("Nháp đã phát hành không thể chỉnh sửa nghiệp vụ.", "warning")
        return redirect(url_for("tasks_bp.task_import_draft_detail", draft_id=draft.id))

    try:
        config = _parse_task_import_working_config_from_form(draft, request.form)
    except Exception as exc:
        flash(str(exc) or "Không thể lưu cấu hình nháp.", "danger")
        return redirect(url_for("tasks_bp.task_import_draft_detail", draft_id=draft.id))

    draft.working_config_json = _json_dump(config)
    draft.status = "draft"
    draft.updated_at = datetime.now()
    db.session.add(draft)
    db.session.commit()
    flash("Đã lưu nháp import.", "success")
    return redirect(url_for("tasks_bp.task_import_draft_detail", draft_id=draft.id))

def _publish_task_import_draft_v2(draft_id):
    perms = _current_perms()
    if not _can_manage_task_imports(perms):
        flash("Bạn không có quyền phát hành nháp import.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    draft = _task_import_draft_or_404(draft_id)
    if not draft:
        return "Not Found", 404
    if str(draft.status or "").strip().lower() == "published" and draft.published_task_id:
        flash("Nháp này đã phát hành trước đó.", "warning")
        return redirect(url_for("tasks_bp.task_detail", tid=draft.published_task_id))

    try:
        new_task = _publish_task_import_draft(draft)
    except Exception as exc:
        db.session.rollback()
        draft = _task_import_draft_or_404(draft_id)
        if draft:
            draft.status = "failed"
            draft.updated_at = datetime.now()
            db.session.add(draft)
            db.session.commit()
        flash(str(exc) or "Không thể phát hành nháp import.", "danger")
        return redirect(url_for("tasks_bp.task_import_draft_detail", draft_id=draft_id))

    flash("Đã phát hành nháp import thành nhiệm vụ.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=new_task.id))

def _analyze_task_import_draft_ai_v2(draft_id):
    perms = _current_perms()
    if not _can_manage_task_imports(perms):
        return jsonify({"ok": False, "error": "Bạn không có quyền phân tích nháp import."}), 403

    draft = _task_import_draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "Không tìm thấy nháp import."}), 404

    payload = request.get_json(silent=True) or {}
    use_provider = bool(payload.get("use_provider"))
    config = _task_import_draft_working_config(draft)
    analysis = _task_import_ai_analysis(config, use_provider=use_provider)
    config["ai_analysis"] = analysis
    config["ai_last_analyzed_at"] = datetime.now().isoformat(timespec="seconds")
    draft.working_config_json = _json_dump(config)
    draft.updated_at = datetime.now()
    db.session.add(draft)
    db.session.commit()
    return jsonify({"ok": True, "analysis": analysis})

def _apply_task_import_draft_ai_v2(draft_id):
    perms = _current_perms()
    if not _can_manage_task_imports(perms):
        return jsonify({"ok": False, "error": "Bạn không có quyền áp dụng gợi ý AI."}), 403

    draft = _task_import_draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "Không tìm thấy nháp import."}), 404
    if str(draft.status or "").strip().lower() == "published":
        return jsonify({"ok": False, "error": "Nháp đã phát hành, không thể áp dụng lại gợi ý AI."}), 400

    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode") or "safe").strip().lower() or "safe"
    sections = payload.get("sections")
    selection = payload.get("selection")
    config = _task_import_draft_working_config(draft)
    analysis = config.get("ai_analysis") if isinstance(config.get("ai_analysis"), dict) else None
    if not analysis:
        analysis = _task_import_ai_analysis(config, use_provider=False)
    updated_config, applied = apply_ai_analysis_to_config(
        config,
        analysis,
        mode=mode,
        sections=sections,
        selection=selection,
    )
    updated_config["ai_analysis"] = analysis
    draft.working_config_json = _json_dump(updated_config)
    draft.status = "draft"
    draft.updated_at = datetime.now()
    db.session.add(draft)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "analysis": analysis,
            "applied": applied,
            "stats": _task_import_config_stats(updated_config),
        }
    )

@tasks_bp.route("/tasks", methods=["GET", "POST"])
def tasks():
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _tasks_page_v2()

@tasks_bp.route("/tasks/import-drafts", methods=["GET"])
def task_import_drafts():
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _task_import_drafts_page()

@tasks_bp.route("/tasks/import-drafts/create", methods=["POST"])
def create_task_import_draft():
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _create_task_import_draft_v2()

@tasks_bp.route("/tasks/import-drafts/<int:draft_id>", methods=["GET"])
def task_import_draft_detail(draft_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _task_import_draft_detail_page(draft_id)

@tasks_bp.route("/tasks/import-drafts/<int:draft_id>/save", methods=["POST"])
def save_task_import_draft(draft_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _save_task_import_draft_v2(draft_id)

@tasks_bp.route("/tasks/import-drafts/<int:draft_id>/publish", methods=["POST"])
def publish_task_import_draft(draft_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _publish_task_import_draft_v2(draft_id)

@tasks_bp.route("/tasks/import-drafts/<int:draft_id>/ai-analyze", methods=["POST"])
def analyze_task_import_draft_ai(draft_id):
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401

    _ensure_task_schema()
    return _analyze_task_import_draft_ai_v2(draft_id)

@tasks_bp.route("/tasks/import-drafts/<int:draft_id>/ai-apply", methods=["POST"])
def apply_task_import_draft_ai(draft_id):
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401

    _ensure_task_schema()
    return _apply_task_import_draft_ai_v2(draft_id)

@tasks_bp.route("/tasks/workflow-blueprint-preview", methods=["POST"])
def preview_workflow_blueprint():
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401

    _ensure_task_schema()

    perms = _current_perms()
    is_admin = bool(session.get("is_admin"))
    if not (is_admin or _can_process_task_module(perms)):
        return jsonify({"ok": False, "error": "Bạn không có quyền phân tích blueprint."}), 403

    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = request.form.to_dict(flat=True)
            raw_blueprint = (payload.get("workflow_blueprint_json") or "").strip()
            if raw_blueprint:
                payload = json.loads(raw_blueprint)
        blueprint = _parse_task_workflow_blueprint_payload(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "error": "Blueprint điều hành không hợp lệ."}), 400

    return jsonify({"ok": True, "preview": workflow_blueprint_preview_data(blueprint)})

@tasks_bp.route("/tasks/workflow-blueprint-import", methods=["POST"])
def import_workflow_blueprint():
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401

    _ensure_task_schema()

    perms = _current_perms()
    is_admin = bool(session.get("is_admin"))
    if not (is_admin or _can_process_task_module(perms)):
        return jsonify({"ok": False, "error": "Bạn không có quyền phân tích tài liệu tham chiếu."}), 403

    file_storage = request.files.get("blueprint_source_file")
    import_mode = (request.form.get("blueprint_import_mode") or "").strip()
    form_reference = (request.form.get("blueprint_form_reference") or "").strip()
    try:
        blueprint = _parse_reference_file_to_blueprint(file_storage, import_mode, form_reference=form_reference)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "workflow_blueprint": blueprint,
            "preview": workflow_blueprint_preview_data(blueprint),
        }
    )

@tasks_bp.route("/tasks/outline-parse", methods=["POST"])
def parse_outline_file_for_create():
    """Phân tích đề cương ngay trong bước tạo công việc (wizard).

    Hỗ trợ nhiều file (file chính + file phụ): nội dung trùng giữa các file
    được gộp thành 1 đầu mục kèm cờ report_secondary + danh sách file nguồn.
    """
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401

    _ensure_task_schema()
    perms = _current_perms()
    if not (bool(session.get("is_admin")) or _can_process_task_module(perms)):
        return jsonify({"ok": False, "error": "Bạn không có quyền tạo công việc."}), 403

    outline_files = request.files.getlist("outline_file")
    outline_files = [file for file in outline_files if file and file.filename]
    if not outline_files:
        return jsonify({"ok": False, "error": "Cần chọn ít nhất một file đề cương trước khi phân tích."}), 400
    try:
        parsed_groups = []
        for outline_file in outline_files:
            rows = _parse_outline_upload_rows(outline_file)
            parsed_groups.append((outline_file.filename, rows))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        # Không được để lọt exception -> 500 HTML khiến trình duyệt báo
        # "The string did not match the expected pattern" (JSON.parse vỡ).
        current_app.logger.exception("Lỗi phân tích đề cương")
        return (
            jsonify({"ok": False, "error": "Lỗi hệ thống khi phân tích file. Hãy kiểm tra nhật ký server hoặc thử file khác."}),
            500,
        )
    merged_rows = _merge_outline_rows_groups(parsed_groups)
    if not merged_rows:
        return jsonify({"ok": False, "error": "Không tìm thấy đầu mục hợp lệ trong các file đề cương."}), 400
    return jsonify({"ok": True, "rows": merged_rows, "merged": len(parsed_groups) > 1})


def _merge_outline_rows_groups(groups):
    """Gộp kết quả parse nhiều file: nội dung trùng (title+content) thành 1 đầu mục.

    groups: list[(filename, rows)]. Row gộp có thêm report_secondary + sources.
    """
    merged = {}
    order = []
    for filename, rows in groups:
        for row in rows or []:
            title = str(row.get("title") or "")
            content = str(row.get("content") or "")
            key = _normalize_outline_match_text(f"{title} {content}")
            if not key:
                continue
            if key in merged:
                entry = merged[key]
                entry["sources"].add(filename)
                # Giữ row giàu thông tin hơn (có gợi ý đơn vị / số liệu)
                existing = entry["row"]
                if not existing.get("unit_domains") and row.get("unit_domains"):
                    entry["row"] = row
                elif not existing.get("number_fields") and row.get("number_fields"):
                    entry["row"] = row
                continue
            merged[key] = {"row": dict(row), "sources": {filename}}
            order.append(key)
    result = []
    for key in order:
        entry = merged[key]
        row = entry["row"]
        row["report_secondary"] = len(entry["sources"]) > 1
        row["sources"] = sorted(entry["sources"])
        result.append(row)
    return result

@tasks_bp.route("/tasks/form-template-preview", methods=["POST"])
def preview_form_template_fields_for_create():
    """Lấy các trường của file Excel mẫu cho task FORM."""
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401

    _ensure_task_schema()
    perms = _current_perms()
    if not (bool(session.get("is_admin")) or _can_process_task_module(perms)):
        return jsonify({"ok": False, "error": "Bạn không có quyền tạo công việc."}), 403

    excel_file = request.files.get("excel_file")
    if excel_file and excel_file.filename:
        try:
            blueprint = _parse_excel_template_blueprint(excel_file)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        fields = workflow_blueprint_form_field_defs(blueprint)
        return jsonify({"ok": True, "source": "excel", "fields": fields})

    return jsonify({"ok": False, "error": "Cần chọn file Excel mẫu."}), 400

@tasks_bp.route("/tasks/<int:tid>", methods=["GET", "POST"])
def task_detail(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _task_detail_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/children/create", methods=["POST"])
def create_child_task(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _create_outline_items_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/outline/import-preview", methods=["POST"])
def preview_outline_import(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _preview_outline_import_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/google-form/create", methods=["POST"])
def create_task_google_form(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _create_task_google_form_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/google-form/update", methods=["POST"])
def update_task_google_form(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _update_task_google_form_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/google-form/publish", methods=["POST"])
def publish_task_google_form(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _publish_task_google_form_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/google-form/import-structure", methods=["POST"])
def import_task_google_form_structure(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _import_task_google_form_structure_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/sync-google-form", methods=["POST"])
def sync_google_form_task(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _sync_google_form_task_v2(tid)

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
    parent_task_id = task.parent_task_id
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
    if parent_task_id:
        return redirect(url_for("tasks_bp.task_detail", tid=parent_task_id))
    return redirect(url_for("tasks_bp.tasks"))

@tasks_bp.route("/tasks/<int:tid>/edit_config", methods=["POST"])
def edit_task_config(tid):
    """Route để sửa cấu hình công việc từ danh sách."""
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    task = Task.query.filter_by(id=tid).first()
    if not task:
        flash("Công việc không tồn tại.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    perms = _current_perms()
    is_lead = _can_process_task_module(perms)
    is_admin = bool(session.get("is_admin"))

    if not _can_edit_task(task) and not is_admin and not is_lead:
        flash("Bạn không có quyền sửa công việc này.", "danger")
        return redirect(url_for("tasks_bp.tasks"))

    # Lấy dữ liệu từ form
    title = request.form.get("title", "").strip()
    deadline_str = request.form.get("deadline", "").strip()
    category = request.form.get("category", "").strip()
    domain = request.form.get("domain", "").strip()
    task_type = request.form.get("task_type", "").strip()
    priority = request.form.get("priority", "").strip()
    description = request.form.get("description", "").strip()

    # Cập nhật thông tin công việc
    if title:
        task.title = title
    if deadline_str:
        try:
            task.deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except ValueError:
            task.deadline = None
    if category:
        task.category = category
    if domain:
        task.domain = domain
    if task_type:
        task.task_type = task_type
    if priority:
        task.priority = priority
    task.content = description

    # Cách báo cáo (loại công việc + chu kỳ / hạn nộp) — chỉ cập nhật khi form
    # gửi lên một cấu hình JSON rõ ràng (modal sửa cấu hình hiện chưa prefill
    # dữ liệu công việc, nên không được ghi đè cấu hình đang có)
    if request.form.get("report_period_json"):
        report_period = _parse_task_report_period_from_request(request.form, task_type=task_type or task.task_type)
        if report_period:
            task.report_period_json = report_config_to_json(report_period)
            computed_deadline = report_deadline_for(report_period)
            if computed_deadline:
                task.deadline = computed_deadline
            elif report_period.get("kind") == "ongoing":
                task.deadline = None

    # Cập nhật scope nếu có
    viewer_scope_mode = request.form.get("viewer_scope_mode", "").strip()
    if viewer_scope_mode:
        viewer_role_ids = request.form.getlist("viewer_role_ids")
        viewer_user_ids = request.form.getlist("viewer_user_ids")
        store_viewer_scope(task, mode=viewer_scope_mode, role_ids=viewer_role_ids, user_ids=viewer_user_ids)

    manager_scope_mode = request.form.get("manager_scope_mode", "").strip()
    if manager_scope_mode:
        manager_role_ids = request.form.getlist("manager_role_ids")
        manager_user_ids = request.form.getlist("manager_user_ids")
        store_manager_scope(task, mode=manager_scope_mode, role_ids=manager_role_ids, user_ids=manager_user_ids)

    db.session.commit()

    log_action(
        session["uid"],
        session.get("fullname", "Quản trị"),
        "Sửa cấu hình công việc",
        "Công việc",
        f"Task #{tid} | {task.title}",
    )
    flash("Đã cập nhật cấu hình công việc.", "success")
    return redirect(url_for("tasks_bp.tasks"))

@tasks_bp.route("/tasks/<int:tid>/update_status", methods=["POST"])
def update_task_status(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _update_task_status_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/submit_report", methods=["POST"])
def submit_task_report(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _submit_task_report_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/submission-files/<int:file_id>")
def download_task_submission_file_v2(tid, file_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()

    file_row = (
        TaskSubmissionFile.query.options(
            joinedload(TaskSubmissionFile.submission).joinedload(TaskSubmission.assignment)
        )
        .filter_by(id=file_id)
        .first()
    )
    if not file_row or not file_row.submission or file_row.submission.task_id != tid:
        return "Not Found", 404

    assignment = getattr(file_row.submission, "assignment", None)
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    perms = _current_perms()
    can_view_all_tasks = _can_view_all_tasks(perms)
    current_user = db.session.get(User, session["uid"])
    can_manage_task_view = bool(
        bool(session.get("is_admin"))
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
        or _can_watch_task(task, user=current_user)
    )
    if not can_manage_task_view and getattr(assignment, "user_id", None) != session["uid"]:
        flash("Bạn không có quyền tải tệp này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    file_path = file_row.stored_path or _task_file_path(file_row.stored_name or "")
    if not file_path or not os.path.exists(file_path):
        flash("Tệp không còn tồn tại trên hệ thống.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    download_name = file_row.original_name or file_row.stored_name or f"task_{tid}_file"
    return send_file(file_path, as_attachment=True, download_name=download_name)

@tasks_bp.route("/tasks/<int:tid>/export-form.xlsx")
def export_form_task_v2(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _export_form_task_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/export-outline.docx")
def export_outline_task_word(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _export_outline_word_v2(tid)

@tasks_bp.route("/tasks/<int:tid>/assignments/<int:assignment_id>/return", methods=["POST"])
def return_task_assignment(tid, assignment_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _return_task_assignment_v2(tid, assignment_id)
