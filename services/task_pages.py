# -*- coding: utf-8 -*-
"""
Cụm page handler task: trang danh sách/chỉnh sửa công việc (_tasks_page_v2), chi tiết
task (_task_detail_v2), tạo đầu mục đề cương (_create_outline_items_v2), xem trước
import đề cương (_preview_outline_import_v2), cập nhật trạng thái (_update_task_status_v2),
nộp báo cáo (_submit_task_report_v2), xuất biểu mẫu/Word (_export_form_task_v2,
_export_outline_word_v2), ma trận tiến độ đề cương (_build_outline_progress_matrix).

Tách từ routes/tasks.py (Pha 2). routes/tasks.py re-export các tên còn dùng.
"""

import io
import json
import os
import re
import uuid
from datetime import datetime

from flask import flash, redirect, request, send_file, session, url_for
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

from models import (
    AppRole,
    Task,
    TaskAssignment,
    TaskComment,
    TaskFormField,
    TaskItem,
    TaskSubmission,
    TaskSubmissionFile,
    User,
    db,
)
from category_helpers import (
    apply_reference_display,
    canonicalize_category_value,
    module_category_options,
    stable_form_category_options,
    sync_record_categories,
)
from google_forms import extract_google_form_id
from permissions import current_is_admin
from report_cycles import config_to_json as report_config_to_json
from task_blueprints import (
    workflow_blueprint_example_catalog,
    workflow_blueprint_form_field_defs,
    workflow_blueprint_item_configs,
    workflow_blueprint_report_schema,
    workflow_blueprint_summary_text,
    workflow_blueprint_task_mode,
)
from task_page_builders import (
    build_task_detail_page_context,
    build_task_list_page_context,
    prepare_task_workspace_record,
    task_visible_for_user,
)
from task_workspace import (
    build_task_workspace_attrs,
)
from utils import (
    push_notif,
    remove_accents,
    render_auto_template as render_template,
)
from routes.email_service import send_task_assignment_emails

logger = __import__('logging').getLogger(__name__)

from services.blueprint_parsing import _parse_task_workflow_blueprint_from_request
from services.outline_engine import (
    _outline_blank_numeric,
    _outline_sources_json,
    _parse_outline_blank_value,
    _parse_outline_upload_titles,
)
from services.outline_rows import _parse_outline_upload_rows
from services.outline_submission import (
    _find_report_secondary_linked_item,
    _outline_merged_content,
    _outline_submission_values,
    _propagate_submission_to_linked_items,
)
from services.task_assignees import (
    _create_assignment_records,
    _resolve_assignees,
    _resolve_managers,
    _resolve_viewers,
)
from services.task_categories import (
    _decorate_task_categories,
    _task_domain_options,
    _task_field_options,
    _task_priority_options,
    _task_type_options,
)
from services.task_deadline import (
    _computed_task_deadline,
    _parse_deadline,
    _parse_task_report_period_from_request,
    _task_current_cycle,
    _task_report_kind_label,
    _task_report_period,
)
from services.task_form_fields import (
    _normalize_task_form_field_type,
    _task_form_fields_for_user,
)
from services.task_google_forms import (
    _apply_task_google_form_view_state,
    _hydrate_google_form_fields,
    _normalize_google_form_match_mode,
    _parse_google_form_builder_schema,
    _task_form_field_db_kwargs,
)
from services.task_guards import (
    _can_delete_task,
    _can_edit_task,
    _can_manage_task,
    _can_watch_task,
)
from services.task_import_draft_helpers import _json_dump
from services.task_import_drafts import _validate_task_visibility_before_publish
from services.task_modes import (
    TASK_ASSIGNMENT_STATUS_LABELS,
    TASK_MODE_DEFAULT,
    _requested_task_mode,
    _task_assignment_display_status,
    _task_assignment_status_class,
    _task_assignment_status_label,
    _task_mode,
    _task_mode_description,
    _task_mode_label,
)
from services.task_permissions import (
    _can_process_task_module,
    _can_view_all_tasks,
    _current_perms,
)
from services.task_report_schema import (
    CHILD_TASK_ALLOWED_REPORT_KINDS,
    _load_task_report_schema,
    _parse_task_report_schema_from_request,
    _report_checkbox_value,
)
from services.task_report_views import (
    _build_assignment_report_context,
    _build_structured_task_report_comment,
    _build_structured_task_report_form,
    _parse_structured_file_report_submission,
)
from services.task_runtime_sync import _lazy_repair_task_runtime
from services.task_scope import (
    _parse_bulk_child_task_titles,
    _requested_manager_role_ids,
    _requested_manager_user_ids,
    _requested_role_ids,
    _requested_user_ids,
    _requested_viewer_role_ids,
    _requested_viewer_user_ids,
    _store_assignment_scope,
    _store_manager_scope,
    _store_viewer_scope,
)
from services.task_units import _task_assignee_unit_name
from services.task_workspace_helpers import (
    _build_rebuilt_task_summary,
    _collapse_logical_task_assignments,
    _filter_assignment_rows_for_executor_scope,
    _filter_outline_groups_for_executor_scope,
    _store_uploaded_task_file,
    _sync_assignment_group_submission,
    _task_assignment_progress_groups,
    _task_delivery_contract_groups,
    _task_file_path,
    _task_is_submitted,
)
from services.excel_form_template import (
    _excel_payload_rows,
    _parse_numeric_value,
    apply_excel_schema_overrides,
    build_aggregated_excel_workbook,
    format_excel_cell_display,
    form_fields_from_excel_schema,
    generate_quick_excel_template_bytes,
    load_excel_form_schema,
    normalize_submitted_excel_rows,
    parse_excel_template_layout,
    parse_staged_filename,
    parse_uploaded_submission_excel,
    resolve_unit_rows_for_user,
)
from services.task_workspace_views import (
    _assignment_return_reason,
    _build_file_task_rows,
    _build_form_task_rows,
    _build_outline_group_rows,
    _clear_outline_import_preview,
    _get_outline_import_preview,
    _outline_display_and_secondary,
    _outline_item_number_fields,
    _outline_item_table_cells,
    _outline_table_schema_map,
    _parse_outline_item_configs_from_request,
    _parse_outline_item_rows,
    _parse_task_form_fields_from_request,
    _resolve_outline_item_assignment,
    _set_outline_import_preview,
    _task_detail_context,
    _task_form_field_views,
    _task_form_field_views_for_user,
    _task_form_value_is_empty,
    _task_item_synthesis_text,
    _task_return_comments,
)


def _parse_item_deadline(value, fallback=None):
    """Chuẩn hóa deadline riêng của dòng; nếu không đủ ngày thì dùng hạn Task."""
    raw = str(value or "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return fallback


def _store_excel_template_bytes(raw_bytes):
    """Lưu file .xlsx mẫu cố định của biểu mẫu và trả tên lưu trữ."""
    stored_name = f"excel_tpl_{uuid.uuid4().hex[:12]}.xlsx"
    target_path = _task_file_path(stored_name)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "wb") as fp:
        fp.write(raw_bytes)
    return stored_name


def _parse_json_form_field(form, field_name, expected_type, default=None):
    raw = (form.get(field_name) or "").strip()
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, expected_type):
            return parsed
    except Exception:
        pass
    return default


def _prepare_excel_form_bundle(form, files, fallback_title=""):
    """Nạp và phân tích biểu mẫu Excel từ file tải lên, file staged, hoặc cột nhanh."""
    uploaded = files.get("excel_template_file") or files.get("excel_file")
    staged_name = parse_staged_filename(form.get("staged_excel_template"))
    quick_raw = (form.get("quick_excel_columns_json") or "").strip()

    raw_bytes = None
    source_filename = ""
    staged_path_to_cleanup = ""
    quick_explicit_types = {}
    quick_explicit_roles = {}
    quick_explicit_formulas = {}
    quick_explicit_percents = {}

    if uploaded and uploaded.filename:
        raw_bytes = uploaded.read()
        source_filename = uploaded.filename
        if staged_name:
            possible_staged = _task_file_path(staged_name)
            if os.path.exists(possible_staged):
                staged_path_to_cleanup = possible_staged
    elif staged_name:
        staged_path = _task_file_path(staged_name)
        if not os.path.exists(staged_path):
            raise ValueError("File Excel mẫu tạm thời đã hết hạn hoặc không còn tồn tại. Vui lòng tải lại file .xlsx.")
        with open(staged_path, "rb") as fp:
            raw_bytes = fp.read()
        source_filename = (form.get("staged_excel_original_name") or "").strip() or "bieu_mau.xlsx"
        staged_path_to_cleanup = staged_path
    elif quick_raw:
        try:
            quick_cols = json.loads(quick_raw)
        except Exception:
            quick_cols = []
        if not isinstance(quick_cols, list) or not quick_cols:
            raise ValueError("Cấu hình cột biểu mẫu Excel chưa hợp lệ.")
        buf = generate_quick_excel_template_bytes(fallback_title, quick_cols)
        raw_bytes = buf.getvalue()
        source_filename = "bieu_mau_excel.xlsx"
        clean_quick_cols = [c for c in quick_cols if str(c.get("label") or "").strip()]
        for idx, col in enumerate(clean_quick_cols):
            idx_key = str(idx)
            if col.get("type") in {"text", "number"}:
                quick_explicit_types[idx_key] = col.get("type")
            if col.get("role") in {"stt", "unit", "data", "formula"}:
                quick_explicit_roles[idx_key] = col.get("role")
            if col.get("formula"):
                quick_explicit_formulas[idx_key] = col.get("formula")
            if col.get("is_percent"):
                quick_explicit_percents[idx_key] = True
    else:
        return None

    schema = parse_excel_template_layout(io.BytesIO(raw_bytes), filename=source_filename)

    allow_raw = str(form.get("excel_allow_add_rows") or "").strip().lower()
    allow_override = None if allow_raw == "" else (allow_raw in {"1", "true", "yes", "on"})

    col_types = dict(quick_explicit_types)
    col_types.update(_parse_json_form_field(form, "excel_col_types_json", dict, {}) or {})

    col_roles = dict(quick_explicit_roles)
    col_roles.update(_parse_json_form_field(form, "excel_col_roles_json", dict, {}) or {})

    col_data_types = _parse_json_form_field(form, "excel_col_data_types_json", dict, None)

    col_formulas = dict(quick_explicit_formulas)
    col_formulas.update(_parse_json_form_field(form, "excel_col_formulas_json", dict, {}) or {})

    col_percents = dict(quick_explicit_percents)
    col_percents.update(_parse_json_form_field(form, "excel_col_percents_json", dict, {}) or {})

    col_readonly = _parse_json_form_field(form, "excel_col_readonly_json", list, None)
    unit_col_index = (form.get("excel_unit_col_index") or "").strip()
    assign_row_mode = (form.get("excel_assign_row_mode") or "").strip() or None
    generated_rows = _parse_json_form_field(form, "excel_generated_rows_json", list, None)
    unit_row_assignments = _parse_json_form_field(form, "excel_unit_row_assignments_json", list, None)

    schema = apply_excel_schema_overrides(
        schema,
        allow_add_rows=allow_override,
        column_types=col_types,
        column_readonly=col_readonly,
        column_roles=col_roles or None,
        column_data_types=col_data_types,
        column_formulas=col_formulas or None,
        column_percents=col_percents or None,
        unit_col_index=unit_col_index if unit_col_index != "" else None,
        assign_row_mode=assign_row_mode,
        template_rows=generated_rows,
        unit_row_assignments=unit_row_assignments,
    )
    return {
        "schema": schema,
        "bytes": raw_bytes,
        "staged_path_to_cleanup": staged_path_to_cleanup,
    }


def _load_form_assign_reference_context(include_people=False):
    """Tải dữ liệu danh mục và người dùng phục vụ tạo/chỉnh sửa công việc biểu mẫu."""
    task_fields = _task_field_options()
    pro_units = _task_domain_options()
    task_types = _task_type_options()
    priority_items = _task_priority_options()
    active_users = []
    roles = []
    if include_people:
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
    return {
        "task_fields": task_fields,
        "pro_units": pro_units,
        "task_types": task_types,
        "priority_items": priority_items,
        "active_users": active_users,
        "roles": roles,
    }


def _form_assign_page_v2():
    """Trang giao việc theo biểu mẫu Excel độc lập (song song với /outline-giao-viec)."""
    perms = _current_perms()
    is_lead = _can_process_task_module(perms)
    is_admin = bool(current_is_admin())
    if not (is_lead or is_admin):
        return ("Bạn không có quyền giao công việc.", 403)

    refs = _load_form_assign_reference_context(include_people=True)
    sidebar_submenu_items = [
        {
            "label": "Giao theo Đề cương văn bản",
            "href": "/outline-giao-viec",
            "count": None,
            "active": False,
        },
        {
            "label": "Giao theo Biểu mẫu Excel",
            "href": "/bieu-mau-giao-viec",
            "count": None,
            "active": True,
        },
        {
            "label": "Danh sách công việc",
            "href": url_for("tasks_bp.tasks"),
            "count": None,
            "active": False,
        },
        {
            "label": "Báo cáo định kỳ",
            "href": url_for("tasks_bp.report_dashboard"),
            "count": None,
            "active": False,
        },
    ]
    return render_template(
        "form_assign.html",
        users=refs["active_users"],
        roles=refs["roles"],
        pro_units=stable_form_category_options(refs["pro_units"]),
        task_fields=refs["task_fields"],
        task_types=stable_form_category_options(refs["task_types"]),
        priority_items=stable_form_category_options(refs["priority_items"]),
        is_lead=is_lead,
        is_admin=is_admin,
        submenu_parent="tasks",
        sidebar_submenu_title="Công việc",
        sidebar_submenu_items=sidebar_submenu_items,
    )


def _tasks_page_v2():
    perms = _current_perms()
    can_view_all_tasks = _can_view_all_tasks(perms)
    is_lead = _can_process_task_module(perms)
    is_admin = bool(current_is_admin())
    current_user = db.session.get(User, session["uid"])

    refs = _load_form_assign_reference_context(include_people=(is_lead or is_admin))
    task_fields = refs["task_fields"]
    pro_units = refs["pro_units"]
    task_types = refs["task_types"]
    priority_items = refs["priority_items"]
    active_users = refs["active_users"]
    roles = refs["roles"]

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

        wants_excel_form = bool(
            task_mode == "FORM"
            and form_provider != "google"
            and (
                form_provider == "excel"
                or (request.files.get("excel_template_file") and request.files.get("excel_template_file").filename)
                or parse_staged_filename(request.form.get("staged_excel_template"))
                or (request.form.get("quick_excel_columns_json") or "").strip()
            )
        )
        excel_bundle = None
        if wants_excel_form:
            form_provider = "excel"
            try:
                excel_bundle = _prepare_excel_form_bundle(request.form, request.files, fallback_title=title)
            except ValueError as excel_err:
                flash(str(excel_err), "danger")
                return redirect(url_for("tasks_bp.tasks"))
            if not excel_bundle:
                flash("Vui lòng tải lên file Excel mẫu (.xlsx) hoặc khai báo cột biểu mẫu.", "danger")
                return redirect(url_for("tasks_bp.tasks"))
            if not title:
                title = excel_bundle["schema"].get("suggested_title") or ""

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
                        deadline=_parse_item_deadline(item_config.get("deadline"), new_task.deadline),
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
            if form_provider == "excel" and excel_bundle:
                field_defs = form_fields_from_excel_schema(excel_bundle["schema"])
            elif form_provider == "google":
                field_defs = google_form_field_defs
            else:
                field_defs = _parse_task_form_fields_from_request(request.form)
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
            if form_provider == "excel" and excel_bundle:
                stored_excel_name = _store_excel_template_bytes(excel_bundle["bytes"])
                if not new_task.file_path:
                    new_task.file_path = stored_excel_name
                new_task.outline_table_schema_json = _json_dump(excel_bundle["schema"])
                staged_cleanup = excel_bundle.get("staged_path_to_cleanup")
                if staged_cleanup and os.path.exists(staged_cleanup):
                    try:
                        os.remove(staged_cleanup)
                    except OSError:
                        pass
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
        executor_cond = TaskAssignment.user_id == session["uid"]
        if getattr(current_user, "unit_id", None):
            executor_cond = db.or_(
                executor_cond,
                db.and_(
                    TaskAssignment.assignee_type == "unit",
                    TaskAssignment.user_id.is_(None),
                    TaskAssignment.unit_id == current_user.unit_id,
                ),
            )
        is_executor = (
            TaskAssignment.query.filter(TaskAssignment.task_id == task.id, executor_cond).first()
            is not None
        )
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
    if is_lead or is_admin:
        sidebar_submenu_items.insert(0, {
            "label": "Giao theo Đề cương văn bản",
            "href": "/outline-giao-viec",
            "count": None,
            "active": False,
        })
        sidebar_submenu_items.insert(1, {
            "label": "Giao theo Biểu mẫu Excel",
            "href": "/bieu-mau-giao-viec",
            "count": None,
            "active": False,
        })
        sidebar_submenu_items.append({
            "label": "Báo cáo định kỳ",
            "href": url_for("tasks_bp.report_dashboard"),
            "count": None,
            "active": False,
        })

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
    is_admin = bool(current_is_admin())
    current_user = db.session.get(User, session["uid"])
    executor_cond = TaskAssignment.user_id == session["uid"]
    if getattr(current_user, "unit_id", None):
        executor_cond = db.or_(
            executor_cond,
            db.and_(
                TaskAssignment.assignee_type == "unit",
                TaskAssignment.user_id.is_(None),
                TaskAssignment.unit_id == current_user.unit_id,
            ),
        )
    is_executor = (
        TaskAssignment.query.filter(TaskAssignment.task_id == task.id, executor_cond).first()
        is not None
    )
    can_manage_task_view = bool(is_admin or _can_edit_task(task) or _can_manage_task(task, user=current_user))
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
    form_return_comments = _task_return_comments(task) if mode == "FORM" else []
    my_file_report_form = _build_structured_task_report_form(task, detail_page_context["my_file_assignment"], current_user) if mode == "FILE" and detail_page_context["my_file_assignment"] else None
    my_form_field_views = _task_form_field_views_for_user(task, current_user) if mode == "FORM" and detail_page_context["my_form_assignment"] else []
    my_form_return_reason = (
        _assignment_return_reason(detail_page_context["my_form_assignment"], form_return_comments)
        or str(getattr(detail_page_context["my_form_assignment"], "return_reason", "") or "").strip()
    ) if mode == "FORM" and detail_page_context["my_form_assignment"] else ""
    if mode == "FILE":
        for row in detail_page_context["file_rows"]:
            row["report_context"] = _build_assignment_report_context(row["assignment"], file_report_comments, task=task)
    file_progress_groups = _task_assignment_progress_groups(detail_page_context["file_rows"]) if mode == "FILE" else {"unit_cards": [], "role_groups": []}
    form_progress_groups = _task_assignment_progress_groups(detail_page_context["form_rows"]) if mode == "FORM" else {"unit_cards": [], "role_groups": []}
    form_matrix = _build_form_progress_matrix(
        task,
        detail_page_context["form_field_views"],
        detail_page_context["form_rows"],
        return_comments=form_return_comments,
        include_payload=bool(can_manage_task_view or can_watch_task_view),
    ) if mode == "FORM" else None
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
    excel_schema = load_excel_form_schema(task) if mode == "FORM" else None
    my_excel_rows = []
    client_excel_schema = excel_schema
    if excel_schema:
        saved_excel_rows = _excel_payload_rows(detail_page_context["my_form_payload"], schema=excel_schema)
        my_excel_rows = saved_excel_rows if saved_excel_rows else resolve_unit_rows_for_user(excel_schema, current_user)
        if excel_schema.get("assign_row_mode") == "unit_rows":
            client_excel_schema = dict(
                excel_schema,
                template_rows=my_excel_rows,
                unit_row_assignments=[],
            )

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
        form_matrix=form_matrix,
        excel_schema=client_excel_schema,
        my_excel_rows=my_excel_rows,
        form_assignment_unit_cards=form_progress_groups["unit_cards"],
        form_assignment_role_groups=form_progress_groups["role_groups"],
        my_file_assignment=detail_page_context["my_file_assignment"],
        my_file_submission=detail_page_context["my_file_submission"],
        my_form_assignment=detail_page_context["my_form_assignment"],
        my_form_submission=detail_page_context["my_form_submission"],
        my_form_payload=detail_page_context["my_form_payload"],
        my_form_field_views=my_form_field_views,
        my_form_return_reason=my_form_return_reason,
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
            deadline=_parse_item_deadline(item_config.get("deadline"), parent_task.deadline),
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
        excel_schema = load_excel_form_schema(task)
        if excel_schema:
            excel_submission_file = request.files.get("excel_submission_file")
            if not (excel_submission_file and excel_submission_file.filename):
                if report_file and report_file.filename and os.path.splitext(report_file.filename)[1].lower() == ".xlsx":
                    excel_submission_file = report_file
            raw_rows_json = (request.form.get("excel_rows_json") or "").strip()

            if excel_submission_file and excel_submission_file.filename:
                try:
                    raw_rows = parse_uploaded_submission_excel(excel_submission_file, excel_schema)
                except ValueError as exc:
                    flash(str(exc), "danger")
                    return redirect(url_for("tasks_bp.task_detail", tid=tid))
                excel_submission_file.stream.seek(0)
                report_file = excel_submission_file
            elif raw_rows_json:
                try:
                    raw_rows = json.loads(raw_rows_json)
                except Exception:
                    flash("Dữ liệu bảng Excel không hợp lệ.", "danger")
                    return redirect(url_for("tasks_bp.task_detail", tid=tid))
            else:
                flash("Cần nhập dữ liệu vào bảng Excel hoặc tải lên file .xlsx trước khi gửi.", "danger")
                return redirect(url_for("tasks_bp.task_detail", tid=tid))

            try:
                submit_unit_name = _task_assignee_unit_name(current_user) if current_user else None
                clean_rows, totals = normalize_submitted_excel_rows(
                    excel_schema,
                    raw_rows,
                    unit_name=submit_unit_name,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("tasks_bp.task_detail", tid=tid))

            payload = {
                "mode": "excel_sheet",
                "rows": clean_rows,
                "totals": totals,
            }
            numeric_value = sum(totals.values()) if totals else None
            narrative = ""
        else:
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
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
        or _can_watch_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền xuất dữ liệu biểu mẫu.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    safe_name = secure_filename(task.title or f"task_{task.id}") or f"task_{task.id}"
    excel_schema = load_excel_form_schema(task)
    if excel_schema:
        fields, rows = _build_form_task_rows(task, session["uid"])
        matrix = _build_form_progress_matrix(
            task,
            _task_form_field_views(task),
            rows,
            include_payload=True,
        )
        template_path = _task_file_path(task.file_path) if task.file_path else None
        output = build_aggregated_excel_workbook(
            task,
            excel_schema,
            matrix["rows"],
            template_path=template_path,
        )
        return send_file(
            output,
            as_attachment=True,
            download_name=f"tong_hop_{safe_name}_{task.id}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

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

def _outline_matrix_display_title(item, content_text=None):
    """Trả về tên/nội dung đầy đủ của đầu mục, tránh bị cắt cụt ở mốc 255 ký tự."""
    display_title, _ = _outline_display_and_secondary(item, content_text=content_text)
    return display_title


def _outline_assignment_report_entry(assignment, submission, item, content_text, number_fields, user, return_reason=""):
    """Chuẩn hóa nội dung báo cáo và tệp đính kèm của một lượt giao cho ma trận & ngăn kéo duyệt."""
    submitter_name = (
        getattr(user, "fullname", None)
        or getattr(user, "username", None)
        or "Cán bộ"
    )
    submitted_dt = (
        getattr(submission, "submitted_at", None)
        or getattr(submission, "updated_at", None)
        or getattr(submission, "created_at", None)
        if submission
        else None
    )
    submitted_at = submitted_dt.strftime("%d/%m/%Y %H:%M") if submitted_dt else ""
    narrative_text = str(getattr(submission, "narrative_content", "") or "").strip() if submission else ""
    numeric_text = (
        ("%g" % submission.numeric_value)
        if submission and getattr(submission, "numeric_value", None) is not None
        else ""
    )
    merged_text = ""
    if getattr(item, "report_kind", None) == "number" and number_fields and submission:
        values = _outline_submission_values(submission)
        merged_text = _outline_merged_content(content_text, number_fields, values).strip()
    report_text = merged_text or narrative_text or (f"Số liệu báo cáo: {numeric_text}" if numeric_text else "")
    files = [
        {
            "id": file.id,
            "name": file.original_name or file.stored_name or f"Tệp #{file.id}",
        }
        for file in (getattr(submission, "files", None) or [])
    ]
    assignment_id = getattr(assignment, "id", None)
    assignment_status = getattr(assignment, "status", "")
    return {
        "assignment": assignment,
        "assignment_id": assignment_id,
        "status": assignment_status,
        "status_label": _task_assignment_status_label(assignment_status),
        "status_class": _task_assignment_status_class(assignment_status),
        "submitted": _task_is_submitted(assignment),
        "submission": submission,
        "submitter_name": submitter_name,
        "submitted_at": submitted_at,
        "report_text": report_text,
        "numeric_text": numeric_text,
        "files": files,
        "return_reason": return_reason or str(getattr(assignment, "return_reason", "") or "").strip(),
    }


def _build_outline_progress_matrix(task, current_uid):
    """Ma trận tiến độ: hàng = đầu mục, cột = đơn vị nhận việc."""
    rows = _parse_outline_item_rows(task, current_uid)
    return_comments = _task_return_comments(task)
    user_cache = {}
    unit_name_cache = {}

    missing_uids = set()
    for row in rows:
        for assignment in row["assignments"]:
            uid = getattr(assignment, "user_id", None)
            attached_user = getattr(assignment, "user", None)
            if attached_user is not None and uid:
                user_cache[uid] = attached_user
            elif uid and uid not in user_cache:
                missing_uids.add(uid)
    if missing_uids:
        for fetched_user in User.query.filter(User.id.in_(missing_uids)).all():
            user_cache[fetched_user.id] = fetched_user

    def assignment_user(assignment):
        uid = getattr(assignment, "user_id", None)
        return getattr(assignment, "user", None) or user_cache.get(uid)

    def assignment_unit_name(assignment):
        user = assignment_user(assignment)
        cache_key = getattr(user, "id", None) or ("object", id(user))
        if cache_key not in unit_name_cache:
            unit_name_cache[cache_key] = _task_assignee_unit_name(user)
        return unit_name_cache[cache_key]

    unit_names = []
    for row in rows:
        for assignment in row["assignments"]:
            unit_name = assignment_unit_name(assignment)
            if unit_name not in unit_names:
                unit_names.append(unit_name)
    unit_names.sort(key=lambda name: remove_accents(name).lower())

    matrix_rows = []
    for idx, row in enumerate(rows, start=1):
        item = row["item"]
        content_text = str(getattr(item, "content", "") or "")
        number_fields = row.get("number_fields") or []
        display_title = row.get("display_title") or _outline_matrix_display_title(item, content_text)
        cells = []
        item_submitted = 0
        item_total = 0
        assignments_by_unit = {}
        for assignment in row["assignments"]:
            assignments_by_unit.setdefault(assignment_unit_name(assignment), []).append(assignment)
        for unit_name in unit_names:
            unit_assignments = assignments_by_unit.get(unit_name, [])
            logical_unit_assignments = _collapse_logical_task_assignments(unit_assignments)
            unit_submitted = sum(1 for assignment in logical_unit_assignments if _task_is_submitted(assignment))
            unit_total = len(logical_unit_assignments)
            item_submitted += unit_submitted
            item_total += unit_total
            cell_numbers = []
            for assignment in logical_unit_assignments:
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
            assignment_entries = [
                _outline_assignment_report_entry(
                    assignment,
                    row["latest_submissions"].get(assignment.id),
                    item,
                    content_text,
                    number_fields,
                    assignment_user(assignment),
                    return_reason=_assignment_return_reason(assignment, return_comments),
                )
                for assignment in logical_unit_assignments
            ]
            cells.append(
                {
                    "unit_name": unit_name,
                    "submitted_count": unit_submitted,
                    "total_count": unit_total,
                    "done": bool(logical_unit_assignments) and unit_submitted >= unit_total,
                    "numbers": cell_numbers,
                    "assignments": assignment_entries,
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
        assigned_cells = [cell for cell in cells if cell["total_count"] > 0]
        percent = round(item_submitted / item_total * 100) if item_total else 0
        matrix_rows.append(
            {
                "item": item,
                "display_title": display_title,
                "secondary_text": row.get("secondary_text") or "",
                "table_render_html": row.get("table_render_html") or "",
                "cells": cells,
                "assigned_cells": assigned_cells,
                "submitted_count": item_submitted,
                "total_count": item_total,
                "done": item_total > 0 and item_submitted >= item_total,
                "percent": percent,
                "aggregate_total": aggregate_total,
                "aggregate_count": aggregate_count,
                "review_payload": {
                    "item_id": getattr(item, "id", None),
                    "index": idx,
                    "item_title": display_title,
                    "secondary_text": row.get("secondary_text") or "",
                    "submitted_count": item_submitted,
                    "total_count": item_total,
                    "percent": percent,
                    "aggregate_total": aggregate_total,
                    "units": [
                        {
                            "unit_name": cell["unit_name"],
                            "done": cell["done"],
                            "submitted_count": cell["submitted_count"],
                            "total_count": cell["total_count"],
                            "entries": [
                                {
                                    "assignment_id": entry["assignment_id"],
                                    "submitter_name": entry["submitter_name"],
                                    "status": entry["status"],
                                    "status_label": entry["status_label"],
                                    "submitted": entry["submitted"],
                                    "submitted_at": entry["submitted_at"],
                                    "report_text": entry["report_text"],
                                    "return_reason": entry["return_reason"],
                                    "files": entry["files"],
                                }
                                for entry in cell["assignments"]
                            ],
                        }
                        for cell in assigned_cells
                    ],
                },
            }
        )

    total_submitted = sum(matrix_row["submitted_count"] for matrix_row in matrix_rows)
    total_count = sum(matrix_row["total_count"] for matrix_row in matrix_rows)
    return {
        "unit_names": unit_names,
        "unit_count": len(unit_names),
        "rows": matrix_rows,
        "total_submitted": total_submitted,
        "total_count": total_count,
        "percent": round(total_submitted / total_count * 100) if total_count else 0,
    }


def _format_form_field_display_value(value):
    """Định dạng giá trị trường biểu mẫu gọn gàng để hiển thị trong ngăn kéo duyệt."""
    if value is None:
        return ""
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return "; ".join(" | ".join(str(cell) for cell in row) for row in value)
        return ", ".join(str(item) for item in value if str(item).strip())
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).strip()


def _build_form_progress_matrix(task, form_field_views, form_rows, return_comments=None, include_payload=False):
    """Chuẩn hóa danh sách tiến độ nộp biểu mẫu theo đơn vị/đối tượng, đồng bộ với ma trận đề cương."""
    row_by_assignment_id = {}
    raw_assignments = []
    for row in form_rows or []:
        assignment = row.get("assignment")
        if not assignment:
            continue
        raw_assignments.append(assignment)
        row_by_assignment_id[getattr(assignment, "id", id(assignment))] = row

    logical_assignments = _collapse_logical_task_assignments(raw_assignments)
    submitter_uids = {
        getattr(row.get("submission"), "submitted_by", None)
        for row in row_by_assignment_id.values()
        if row.get("submission") and getattr(row.get("submission"), "submitted_by", None)
    }
    user_cache = {}
    if submitter_uids:
        for fetched_user in User.query.filter(User.id.in_(submitter_uids)).all():
            user_cache[fetched_user.id] = fetched_user

    return_comments = return_comments if return_comments is not None else _task_return_comments(task)
    excel_schema = load_excel_form_schema(task)
    excel_cols = (excel_schema.get("columns") or []) if excel_schema else []
    if excel_schema:
        numeric_totals = {
            col["field_key"]: {
                "field_label": col.get("full_label") or col.get("label") or col["field_key"],
                "total": 0.0,
                "count": 0,
            }
            for col in excel_cols
            if col.get("type") == "number" and col.get("role") != "formula" and not col.get("is_percent")
        }
    else:
        numeric_totals = {
            field["field_key"]: {"field_label": field["field_label"], "total": 0.0, "count": 0}
            for field in (form_field_views or [])
            if field.get("field_type") == "number"
        }

    files_by_sub_id = {}
    if include_payload:
        sub_ids = {
            getattr(row.get("submission"), "id", None)
            for row in row_by_assignment_id.values()
            if row.get("submission")
        }
        sub_ids.discard(None)
        if sub_ids:
            for sf in TaskSubmissionFile.query.filter(TaskSubmissionFile.submission_id.in_(sub_ids)).order_by(TaskSubmissionFile.id.asc()).all():
                files_by_sub_id.setdefault(sf.submission_id, []).append(
                    {"id": sf.id, "name": sf.original_name or sf.stored_name or f"tep_{sf.id}"}
                )

    matrix_rows = []
    unit_names = []
    submitted_count = 0
    returned_count = 0

    for idx, assignment in enumerate(logical_assignments, start=1):
        row = row_by_assignment_id.get(getattr(assignment, "id", id(assignment)), {})
        user = getattr(assignment, "user", None)
        user_name = getattr(user, "fullname", None) or getattr(user, "username", None) or "Không xác định"
        unit_name = _task_assignee_unit_name(user) if user else user_name
        if unit_name not in unit_names:
            unit_names.append(unit_name)

        status = str(getattr(assignment, "status", "") or "assigned").strip().lower()
        status_label = _task_assignment_status_label(status)
        submitted = _task_is_submitted(assignment)
        if submitted:
            submitted_count += 1
        elif status == "returned":
            returned_count += 1

        submission = row.get("submission")
        payload = row.get("payload") or {}
        sub_status = (
            str(getattr(submission, "status", "") or "").strip().lower()
            if submission
            else ""
        )
        excel_rows = _excel_payload_rows(payload, schema=excel_schema) if excel_schema else []
        if excel_schema:
            has_content = bool(excel_rows)
        else:
            has_content = any(
                not _task_form_value_is_empty(payload.get(field["field_key"], ""))
                for field in (form_field_views or [])
            )
        has_real_submission = bool(
            submitted
            or sub_status in {"submitted", "completed", "returned"}
            or getattr(submission, "submitted_at", None) is not None
            or has_content
        )
        submitter_user = (
            user_cache.get(getattr(submission, "submitted_by", None))
            if (submission and has_real_submission)
            else None
        )
        submitter_name = (
            getattr(submitter_user, "fullname", None)
            or getattr(submitter_user, "username", None)
            or user_name
        )
        submitted_dt = (
            getattr(submission, "submitted_at", None)
            or getattr(submission, "updated_at", None)
            or getattr(submission, "created_at", None)
            if (submission and has_real_submission)
            else None
        )
        submitted_at = submitted_dt.strftime("%d/%m/%Y %H:%M") if submitted_dt else ""
        return_reason = (
            _assignment_return_reason(assignment, return_comments)
            or str(getattr(assignment, "return_reason", "") or "").strip()
        )
        answered_count = 0
        total_fields_count = len(excel_cols) if excel_schema else len(form_field_views or [])
        field_lines = []
        excel_table_payload = None
        if has_real_submission:
            if excel_schema:
                answered_count = len(excel_rows)
                if include_payload and excel_rows:
                    unit_counted_cols = set()
                    for r_vals in excel_rows:
                        for c_idx, col in enumerate(excel_cols):
                            fkey = col.get("field_key")
                            if col.get("type") != "number" or fkey not in numeric_totals:
                                continue
                            raw_cell = r_vals[c_idx] if c_idx < len(r_vals) else ""
                            num_val = _parse_numeric_value(raw_cell)
                            if num_val is not None:
                                numeric_totals[fkey]["total"] += num_val
                                unit_counted_cols.add(fkey)
                    for fkey in unit_counted_cols:
                        numeric_totals[fkey]["count"] += 1
                if include_payload or row.get("is_current_user"):
                    formatted_rows = [
                        [
                            format_excel_cell_display(r_vals[c_i] if c_i < len(r_vals) else "", col)
                            for c_i, col in enumerate(excel_cols)
                        ]
                        for r_vals in excel_rows
                    ]
                    excel_table_payload = {
                        "columns": [
                            {
                                "label": col.get("full_label") or col.get("label") or f"Cột {c_i + 1}",
                                "type": col.get("type") or "text",
                            }
                            for c_i, col in enumerate(excel_cols)
                        ],
                        "rows": formatted_rows,
                    }
                    report_text_summary = f"Đã nộp {len(excel_rows)} dòng dữ liệu bảng Excel." if excel_rows else ""
                else:
                    report_text_summary = ""
                report_text = report_text_summary
            else:
                for field in form_field_views or []:
                    raw_val = payload.get(field["field_key"], "")
                    is_empty = _task_form_value_is_empty(raw_val)
                    if not is_empty:
                        answered_count += 1
                        if include_payload and field["field_key"] in numeric_totals:
                            num_val = _outline_blank_numeric(raw_val)
                            if num_val is not None:
                                numeric_totals[field["field_key"]]["total"] += num_val
                                numeric_totals[field["field_key"]]["count"] += 1
                    if include_payload or row.get("is_current_user"):
                        formatted_val = _format_form_field_display_value(raw_val)
                        field_lines.append(f"• {field['field_label']}: {formatted_val or 'Chưa nhập'}")
                report_text = "\n".join(field_lines)
        else:
            report_text = ""

        sub_files = files_by_sub_id.get(getattr(submission, "id", None), []) if (has_real_submission and (include_payload or row.get("is_current_user"))) else []
        assignment_id = getattr(assignment, "id", idx)
        drawer_key = f"form-{assignment_id}"
        matrix_rows.append(
            {
                "index": idx,
                "assignment": assignment,
                "assignment_id": assignment_id,
                "drawer_key": drawer_key,
                "unit_name": unit_name,
                "user_name": user_name,
                "submitter_name": submitter_name,
                "status": status,
                "status_label": status_label,
                "submitted": submitted,
                "has_submission": has_real_submission,
                "submitted_at": submitted_at,
                "answered_count": answered_count,
                "total_fields": total_fields_count,
                "is_excel_form": bool(excel_schema),
                "payload": payload if (include_payload or row.get("is_current_user")) else {},
                "return_reason": return_reason,
                "is_current_user": bool(row.get("is_current_user")),
                "review_payload": {
                    "item_id": drawer_key,
                    "index": "",
                    "item_title": unit_name,
                    "secondary_text": f"Người phụ trách: {submitter_name}" if submitter_name and submitter_name != unit_name else "",
                    "submitted_count": 1 if submitted else 0,
                    "total_count": 1,
                    "percent": 100 if submitted else 0,
                    "aggregate_total": None,
                    "units": [
                        {
                            "unit_name": unit_name,
                            "done": submitted,
                            "submitted_count": 1 if submitted else 0,
                            "total_count": 1,
                            "entries": [
                                {
                                    "assignment_id": assignment_id,
                                    "submitter_name": submitter_name,
                                    "status": status,
                                    "status_label": status_label,
                                    "submitted": submitted,
                                    "submitted_at": submitted_at,
                                    "report_text": report_text,
                                    "excel_table": excel_table_payload,
                                    "return_reason": return_reason,
                                    "files": sub_files,
                                }
                            ],
                        }
                    ],
                },
            }
        )

    unit_names.sort(key=lambda name: remove_accents(name).lower())
    total_count = len(matrix_rows)
    numeric_aggregates = [
        item for item in numeric_totals.values() if item["count"] > 0
    ]
    return {
        "rows": matrix_rows,
        "unit_names": unit_names,
        "total_count": total_count,
        "submitted_count": submitted_count,
        "returned_count": returned_count,
        "percent": round(submitted_count / total_count * 100) if total_count else 0,
        "numeric_aggregates": numeric_aggregates,
        "is_excel_form": bool(excel_schema),
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
        bool(current_is_admin())
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
        logical_assignments = _collapse_logical_task_assignments(row["assignments"])
        number_fields = _outline_item_number_fields(item)
        submitted_with_values = []
        for assignment in logical_assignments:
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
        for assignment in logical_assignments:
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
