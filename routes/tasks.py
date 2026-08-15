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
from permissions import current_is_admin
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

# Pha 2: hằng số + helper mode/trạng thái đã tách sang services/task_modes.py.
# Import re-export ở đây giữ nguyên tên cũ cho mọi nơi đang dùng (migrate.py,
# tests, và chính các hàm bên dưới trong file này).
from services.task_modes import (  # noqa: E402
    PENDING_STATUSES,
    IN_PROGRESS_STATUS,
    COMPLETED_STATUS,
    TASK_MODE_ALLOWED,
    TASK_MODE_DEFAULT,
    TASK_MODE_LABELS,
    TASK_MODE_DESCRIPTIONS,
    TASK_ASSIGNMENT_STATUS_LABELS,
    _normalize_status,
    _normalize_task_mode,
    _requested_task_mode,
    _task_mode,
    _task_mode_label,
    _task_mode_description,
    _task_assignment_status_label,
    _task_assignment_display_status,
    _task_assignment_status_class,
)

from services.task_runtime_sync import (  # noqa: E402
    CHILD_TASK_NUMBER_FIELD_KEY,
    REPORT_ATTACHMENT_RE,
    REPORT_PREFIX,
    _assignment_has_report_submission,
    _assignment_has_report_submission_legacy,
    _assignment_numeric_report_value,
    _assignment_report_comment_snapshots,
    _assignment_report_snapshot,
    _assignment_report_snapshot_map,
    _backfill_task_runtime_models,
    _ensure_task_assignment_bridge,
    _ensure_task_runtime_bridge,
    _extract_submission_numeric_value,
    _infer_submission_type,
    _latest_assignment_submission,
    _lazy_repair_task_runtime,
    _parse_assignment_payload,
    _parse_report_comment_content,
    _parse_report_number,
    _parse_structured_task_report_payload,
    _query_task_scope,
    _resolve_scope_users,
    _structured_payload_has_content,
    _submission_has_report_content,
    _sync_task_items,
    _sync_task_participants,
    _sync_task_runtime_models,
    _sync_task_submissions,
    _task_assignment_for_user,
    _task_assignment_records,
    _task_assignment_rows,
    _task_executor_user_ids,
    _task_item_status_from_task,
    _task_latest_reporting_assignment,
    _task_report_meta,
    _task_runtime_bridge_needs_sync,
    _task_runtime_expected_counts,
    _task_scope_identity,
    _task_simple_child_report_kind,
    _task_submission_sort_key,
    _task_user_is_executor,
    _upsert_task_submission_from_assignment,
    _visible_child_tasks_by_parent_for_user,
    _visible_child_tasks_for_user,
)

from services.task_report_schema import (  # noqa: E402
    CHILD_TASK_ALLOWED_REPORT_KINDS,
    DEFAULT_TASK_REPORT_SCHEMA,
    TASK_REPORT_ALLOWED_FIELD_TYPES,
    TASK_REPORT_ALLOWED_TARGET_TYPES,
    _load_task_report_schema,
    _normalize_child_task_report_meta,
    _normalize_report_target_config,
    _normalize_report_target_domains,
    _normalize_report_target_ids,
    _normalize_task_report_schema,
    _parse_task_report_schema_from_request,
    _report_checkbox_value,
    _task_report_field_key,
    _task_report_item_visible_for_user,
    _task_report_schema_seed,
    _task_report_user_matches_units,
)

# Pha 2 đợt 6: cụm nháp nhập việc (36 helper L554-2232 cũ + 4 nhãn TASK_IMPORT_*_LABELS)
# chuyển sang services/task_import_drafts.py; _create_assignment_records chuyển sang
# services/task_assignees.py; gỡ mã chết _sync_task_assignments (không còn nơi gọi).
from services.task_import_drafts import (  # noqa: E402
    TASK_IMPORT_ASSIGN_TYPE_LABELS,
    TASK_IMPORT_FIELD_TYPE_LABELS,
    TASK_IMPORT_REPORT_KIND_LABELS,
    TASK_IMPORT_TARGET_TYPE_LABELS,
    _parse_task_import_working_config_from_form,
    _publish_task_import_draft,
    _task_assignment_scope_lists,
    _task_import_blueprint_from_config,
    _task_import_config_stats,
    _task_import_draft_blueprint,
    _task_import_draft_working_config,
    _task_import_parse_id_csv,
    _task_import_recipient_preview,
    _task_import_working_config_from_blueprint,
    _validate_task_visibility_before_publish,
)
from services.task_form_fields import (  # noqa: E402
    TASK_FORM_ALLOWED_FIELD_TYPES,
    _form_field_options,
    _normalize_task_form_field_type,
    _task_form_field_visible_for_user,
    _task_form_fields,
    _task_form_fields_for_user,
)

from services.task_import_draft_helpers import (  # noqa: E402
    _draft_field_options_json,
    _draft_field_options_text,
    _json_dump,
    _json_loads_safe,
    _task_import_field_key,
    _task_import_form_field_options_json,
    _task_import_form_field_target_config,
    _task_import_source_label,
    _task_import_status_label,
)
from services.task_google_forms import (  # noqa: E402
    TASK_GOOGLE_FORM_MATCH_MODE_LABELS,
    _apply_task_google_form_view_state,
    _filter_google_form_response_for_assignment,
    _google_form_assignment_matches_response,
    _hydrate_google_form_fields,
    _match_google_form_response_to_assignment,
    _merge_google_form_field_targets,
    _normalize_google_form_builder_schema_with_targets,
    _normalize_google_form_match_mode,
    _parse_google_form_builder_schema,
    _replace_task_form_fields,
    _task_form_field_db_kwargs,
    _task_google_form_builder,
    _task_google_form_manage_service,
    _task_google_form_match_label,
    _task_google_form_response_match_value,
    _task_google_form_runtime,
    _task_google_form_runtime_payload,
    _task_google_form_sync_state,
    _task_google_form_target_lookup,
)

TASK_IMPORT_DRAFT_ALLOWED_STATUSES = {"draft", "published", "failed"}
TASK_IMPORT_SOURCE_TYPES = {"docx_outline", "docx_report_outline", "xlsx_form", "google_form_remote", "blueprint_json"}
# Pha 2 đợt 5: cụm helper màn xem báo cáo (điều kiện tiến độ/chất lượng task con,
# dashboard báo cáo task con, biểu mẫu/ngữ cảnh báo cáo có cấu trúc) chuyển sang
# services/task_report_views.py; gỡ kèm mã chết không còn nơi gọi:
# _build_simple_child_task_schema, _child_task_numeric_total, _build_child_task_unit_summary,
# _build_child_task_reporting_matrix, _task_download_slug, _task_report_download_name,
# _build_unit_report_cards, _build_unit_report_groups, _build_discussion_threads,
# _build_unit_report_summary.
from services.task_report_views import (  # noqa: E402
    CHILD_TASK_PROGRESS_CONDITIONS,
    CHILD_TASK_QUALITY_CONDITIONS,
    _build_assignment_report_context,
    _build_child_task_report_dashboard,
    _build_structured_task_report_comment,
    _build_structured_task_report_form,
    _child_task_condition_meta,
    _format_report_number,
    _parse_structured_file_report_submission,
    _structured_task_report_summary_lines,
    _task_report_value_preview,
)

# Pha 2: helper báo cáo Đề án 06 chuyển sang services/task_da06.py.
from services.task_da06 import (  # noqa: E402
    DA06_SO_NGANH_RULES,
    DA06_TASK_MARKERS,
    DA06_TCT_ROLE_MARKERS,
    DA06_TTPVHCC_USERNAME,
    _build_da06_management_view,
    _build_da06_task_form,
    _da06_so_nganh_dvc_rows,
    _da06_tct_sections,
    _da06_user_profile,
    _has_da06_value,
    _is_da06_month_task,
    _normalized_text,
)


# Pha 2: helper danh mục phân loại task chuyển sang services/task_categories.py.
from services.task_categories import (  # noqa: E402
    _task_domain_options,
    _task_field_options,
    _task_type_options,
    _task_priority_options,
    _task_assignment_unit_options,
    _task_field_display,
    _decorate_task_categories,
)

# Pha 2: helper quyền module task chuyển sang services/task_permissions.py.
from services.task_permissions import (  # noqa: E402
    _current_perms,
    _can_view_task_module,
    _can_process_task_module,
    _can_view_all_tasks,
    _can_execute_task_module,
)


# Pha 2: helper hạn nộp + chu kỳ báo cáo chuyển sang services/task_deadline.py.
from services.task_deadline import (  # noqa: E402
    _parse_deadline,
    _task_report_period,
    _parse_task_report_period_from_request,
    _task_current_cycle,
    _task_report_kind_label,
    _computed_task_deadline,
)

# Pha 2: helper đối sánh đơn vị chuyển sang services/task_units.py.
from services.task_units import (  # noqa: E402
    _dedupe_users,
    _user_unit_key,
    _is_generic_task_unit_key,
    _is_generic_task_unit_name,
    _looks_like_task_unit_name,
    _resolve_task_unit_label,
    _task_unit_identity,
    _users_for_unit,
    _is_commune_role,
    _resolve_role_assignees,
    _task_assignee_unit_name,
)

# Pha 2: wrapper scope chuyển sang services/task_scope.py.
from services.task_scope import (  # noqa: E402
    _load_assignment_scope,
    _load_viewer_scope,
    _load_manager_scope,
    _store_assignment_scope,
    _store_viewer_scope,
    _store_manager_scope,
)

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

# Pha 2: helper scope + tham số người nhận chuyển sang services/task_scope.py.
from services.task_scope import (  # noqa: E402
    _infer_viewer_context,
    _infer_manager_context,
    _scope_preview_names,
    _build_scope_summary,
    _requested_role_ids,
    _requested_user_ids,
    _requested_unit_domains,
    _requested_viewer_role_ids,
    _requested_viewer_user_ids,
    _requested_manager_role_ids,
    _requested_manager_user_ids,
    _parse_bulk_child_task_titles,
)

# Pha 2: engine phân tích đề cương chuyển sang services/outline_engine.py.
from services.outline_engine import (  # noqa: E402
    OUTLINE_ASSIGNEE_HINT_KEYWORDS,
    OUTLINE_ASSIGNEE_NORM_KEYWORDS,
    _OUTLINE_METRIC_KEYWORDS,
    _OUTLINE_NUMBER_TOKEN,
    _OUTLINE_UNIT_STOPWORDS,
    _append_outline_bullet,
    _clean_outline_title,
    _extract_number_fields_from_text,
    _find_all_outline_assignee_matches,
    _flatten_hierarchy_to_rows,
    _get_heading_level,
    _is_outline_heading,
    _is_outline_structural_heading,
    _looks_like_outline_assignee_text,
    _mask_outline_dates_and_years,
    _normalize_outline_match_text,
    _outline_blank_numeric,
    _outline_build_number_field,
    _outline_number_metric,
    _outline_number_unit,
    _outline_skeleton_text,
    _outline_sources_json,
    _paragraph_is_outline_item,
    _parse_outline_blank_value,
    _parse_outline_docx_titles,
    _parse_outline_pdf_text,
    _parse_outline_pdf_titles,
    _parse_outline_text_titles,
    _parse_outline_upload_titles,
    _parse_outline_with_hierarchy,
    _parse_vn_number,
    _pdf_decode_string_token,
    _pdf_text_stdlib,
    _resolve_outline_assignee_hint,
    _resolve_outline_rows_assignments,
    _strip_outline_assignee_suffix,
    _task_assignment_catalog,
)
from services.outline_engine import TASK_OUTLINE_ALLOWED_EXTENSIONS  # noqa: E402

# Pha 2: helper nộp báo cáo đề cương chuyển sang services/outline_submission.py.
from services.outline_submission import (  # noqa: E402
    _find_report_secondary_linked_item,
    _unit_domain_user_ids,
    _propagate_submission_to_linked_items,
    _outline_merged_content,
    _outline_submission_values,
    _outline_blank_input_html,
    _render_blank_editor_html,
    _parse_task_submission_payload,
)

# Pha 2: phân tích đề cương thành dòng chuyển sang services/outline_rows.py.
from services.outline_rows import (  # noqa: E402
    _split_outline_paragraphs_into_blocks,
    OUTLINE_TABLE_ROLE_LABELS,
    _table_build_schema,
    _table_column_role,
    _table_header_based_rows,
    _table_rows_to_outline_rows,
    _parse_outline_docx_rows,
    _parse_outline_pdf_rows,
    _blocks_to_outline_rows,
    _parse_outline_text_rows,
    _parse_outline_upload_rows,
)

# Pha 2: phân tích blueprint chuyển sang services/blueprint_parsing.py.
from services.blueprint_parsing import (  # noqa: E402
    TASK_BLUEPRINT_IMPORT_ALLOWED_EXTENSIONS,
    TASK_BLUEPRINT_IMPORT_MODES,
    _blueprint_title_from_filename,
    _coerce_excel_sample_text,
    _looks_like_number,
    _infer_excel_blueprint_field_type,
    _pick_excel_header_row,
    _parse_excel_template_blueprint,
    _blueprint_form_fields_from_google_form_payload,
    _parse_google_form_reference_to_blueprint,
    _parse_reference_file_to_blueprint,
)

# Pha 2 đợt 6: cụm nháp nhập việc (cấu hình làm việc từ blueprint, phân tích form,
# xem trước người nhận, phát hành nháp) chuyển sang services/task_import_drafts.py.

# Pha 2: cụm đồng bộ runtime task (scope/participant/item/submission/backfill)
# đã chuyển sang services/task_runtime_sync.py.
# Pha 2: phân giải người nhận/người xem/người xử lý + tạo bản ghi assignment
# chuyển sang services/task_assignees.py.
from services.task_assignees import (  # noqa: E402
    _create_assignment_records,
    _resolve_assignees,
    _resolve_assignees_by_mode,
    _resolve_managers,
    _resolve_viewers,
)

# Pha 2 đợt 8: cụm helper quyền + lọc bình luận chuyển sang services/task_guards.py.
from services.task_guards import (  # noqa: E402
    _load_task_parent,
    _can_manage_task,
    _can_edit_task,
    _can_delete_task,
    _can_watch_task,
    _can_view_task,
    _filter_comments_for_viewer,
)

# Pha 2: các helper lược đồ biểu mẫu báo cáo (report schema) đã chuyển sang
# services/task_report_schema.py.

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
# Pha 2 đợt 7: cụm helper thẻ đơn vị/nhóm vai trò/nhóm nộp/lưu tệp (band 689-1096 cũ)
# chuyển sang services/task_workspace_helpers.py.
# Pha 2: helper báo cáo Đề án 06 đã chuyển sang services/task_da06.py;
# _save_task_attachment không còn nơi gọi (mã chết) nên gỡ hẳn.
# Pha 2 đợt 7: cụm helper nhóm assignment/tiến độ/nộp chuyển sang
# services/task_workspace_helpers.py (gỡ kèm def chết _latest_assignment_submission).
from services.task_workspace_helpers import (  # noqa: E402
    _build_rebuilt_task_summary,
    _filter_assignment_rows_for_executor_scope,
    _filter_outline_groups_for_executor_scope,
    _store_uploaded_task_file,
    _sync_assignment_group_submission,
    _task_assignment_progress_groups,
    _task_assignments_query,
    _task_delivery_contract_groups,
    _task_file_path,
    _task_is_submitted,
    _task_items_for_task,
)

# Pha 2 đợt 9: band helper màn làm việc (chi tiết task, bảng/dòng đề cương,
# cấu hình đầu mục/trường biểu mẫu từ request, dòng file/form) chuyển sang
# services/task_workspace_views.py; _is_category_item_reference gỡ (mã chết).
# Pha 2 đợt 9: cụm helper view đề cương/biểu mẫu/dòng tác vụ chuyển sang
# services/task_workspace_views.py.
from services.task_workspace_views import (  # noqa: E402
    _outline_table_schema_map,
    _outline_item_table_cells,
    _render_outline_table_html,
    _parse_outline_item_rows,
    _outline_item_number_fields,
    _parse_outline_item_configs_from_request,
    _resolve_outline_item_assignment,
    _parse_task_form_fields_from_request,
    _build_form_task_rows,
    _task_form_field_views_for_user,
)

def _tasks_page_v2():
    perms = _current_perms()
    can_view_all_tasks = _can_view_all_tasks(perms)
    is_lead = _can_process_task_module(perms)
    is_admin = bool(current_is_admin())
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
    is_admin = bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
        bool(current_is_admin())
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
    return bool(current_is_admin() or _can_process_task_module(perms))

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
    is_admin = bool(current_is_admin())
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
    is_admin = bool(current_is_admin())
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
    if not (bool(current_is_admin()) or _can_process_task_module(perms)):
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
    if not (bool(current_is_admin()) or _can_process_task_module(perms)):
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
    is_admin = bool(current_is_admin())

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
        bool(current_is_admin())
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
