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
    _infer_assignment_context,
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
    _parse_task_workflow_blueprint_payload,
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
    TASK_IMPORT_SOURCE_TYPES,
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
# Pha 2 đợt 10: TASK_IMPORT_SOURCE_TYPES chuyển sang services/task_import_draft_helpers.py.
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
    _is_commune_role,
    _task_assignee_unit_name,
)

# Pha 2: wrapper scope chuyển sang services/task_scope.py.
from services.task_scope import (  # noqa: E402
    _load_viewer_scope,
    _load_manager_scope,
    _store_assignment_scope,
    _store_viewer_scope,
    _store_manager_scope,
)

# Pha 2 đợt 10: _infer_assignment_context chuyển sang services/task_runtime_sync.py.
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
# Pha 2 đợt 12: _parse_outline_file_for_create chuyển sang services/outline_rows.py.
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
    _parse_outline_file_for_create,
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

# Pha 2 đợt 11: _parse_task_workflow_blueprint_from_request chuyển sang services/blueprint_parsing.py.
# Pha 2 đợt 12: _preview_workflow_blueprint, _import_workflow_blueprint chuyển sang services/blueprint_parsing.py.
from services.blueprint_parsing import (  # noqa: E402
    _parse_task_workflow_blueprint_from_request,
    _preview_workflow_blueprint,
    _import_workflow_blueprint,
)
# Pha 2 đợt 10: _parse_task_workflow_blueprint_payload chuyển sang services/task_import_drafts.py.
# Pha 2 đợt 7: cụm helper thẻ đơn vị/nhóm vai trò/nhóm nộp/lưu tệp (band 689-1096 cũ)
# chuyển sang services/task_workspace_helpers.py.
# Pha 2: helper báo cáo Đề án 06 đã chuyển sang services/task_da06.py;
# _save_task_attachment không còn nơi gọi (mã chết) nên gỡ hẳn.
# Pha 2 đợt 7: cụm helper nhóm assignment/tiến độ/nộp chuyển sang
# services/task_workspace_helpers.py (gỡ kèm def chết _latest_assignment_submission).
from services.task_workspace_helpers import (  # noqa: E402
    _build_rebuilt_task_summary,
    _download_task_submission_file_v2,
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
    _task_detail_context,
    _outline_table_schema_map,
    _outline_item_table_cells,
    _render_outline_table_html,
    _parse_outline_item_rows,
    _task_item_synthesis_text,
    _outline_item_number_fields,
    _parse_outline_item_configs_from_request,
    _get_outline_import_preview,
    _set_outline_import_preview,
    _clear_outline_import_preview,
    _resolve_outline_item_assignment,
    _build_outline_group_rows,
    _build_file_task_rows,
    _task_form_value_is_empty,
    _parse_task_form_fields_from_request,
    _build_form_task_rows,
    _task_form_field_views,
    _task_form_field_views_for_user,
)

# Pha 2 đợt 11: band page handlers (danh sách/chi tiết/đầu mục/trạng thái/nộp/xuất)
# + band google-form v2 (trả assignment/tạo/cập nhật/xuất bản/nhập/đồng bộ Google Form)
# chuyển sang services/task_pages.py + services/task_google_forms_v2.py.
# Pha 2 đợt 11: band page handlers chuyển sang services/task_pages.py.
from services.task_pages import (  # noqa: E402
    _tasks_page_v2,
    _task_detail_v2,
    _create_outline_items_v2,
    _preview_outline_import_v2,
    _update_task_status_v2,
    _submit_task_report_v2,
    _export_form_task_v2,
    _export_outline_word_v2,
)
# Pha 2 đợt 11: band google-form v2 chuyển sang services/task_google_forms_v2.py.
from services.task_google_forms_v2 import (  # noqa: E402
    _return_task_assignment_v2,
    _create_task_google_form_v2,
    _update_task_google_form_v2,
    _publish_task_google_form_v2,
    _import_task_google_form_structure_v2,
    _sync_google_form_task_v2,
)

# Pha 2 đợt 12: band synthesis (aggregate/synthesis-data/synthesize) chuyển sang
# services/task_synthesis.py.
from services.task_synthesis import (  # noqa: E402
    _toggle_task_item_aggregate,
    _task_item_synthesis_data,
    _save_task_item_synthesis,
)

@tasks_bp.route("/tasks/<int:tid>/items/<int:item_id>/aggregate", methods=["POST"])
def toggle_task_item_aggregate(tid, item_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))
    _ensure_task_schema()
    return _toggle_task_item_aggregate(tid, item_id)

@tasks_bp.route("/tasks/<int:tid>/items/<int:item_id>/synthesis-data")
def task_item_synthesis_data(tid, item_id):
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Chưa đăng nhập."}), 401
    _ensure_task_schema()
    return _task_item_synthesis_data(tid, item_id)

@tasks_bp.route("/tasks/<int:tid>/items/<int:item_id>/synthesize", methods=["POST"])
def save_task_item_synthesis(tid, item_id):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))
    _ensure_task_schema()
    return _save_task_item_synthesis(tid, item_id)



# Pha 2 đợt 10: band task-admin (purge/schema/decorate) + task-import pages
# (submenu/history/workload/AI/draft pages) chuyển sang services/task_admin.py.
# Pha 2 đợt 10: band task-admin + task-import pages chuyển sang services/task_admin.py.
from services.task_admin import (  # noqa: E402
    _purge_task,
    _ensure_task_schema,
    _delete_task_route,
    _edit_task_config,
    _task_import_draft_render_context,
    _task_import_drafts_page,
    _create_task_import_draft_v2,
    _task_import_draft_detail_page,
    _save_task_import_draft_v2,
    _publish_task_import_draft_v2,
    _analyze_task_import_draft_ai_v2,
    _apply_task_import_draft_ai_v2,
)

# Pha 3: các view mới — import cuối file để tránh circular import.
from services.task_form_aggregation import _form_data_aggregation_view  # noqa: E402
from services.global_search import _global_search_page  # noqa: E402
from services.report_dashboard import _report_dashboard_page  # noqa: E402

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
    return _preview_workflow_blueprint()

@tasks_bp.route("/tasks/workflow-blueprint-import", methods=["POST"])
def import_workflow_blueprint():
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401
    _ensure_task_schema()
    return _import_workflow_blueprint()

@tasks_bp.route("/tasks/outline-parse", methods=["POST"])
def parse_outline_file_for_create():
    """Phân tích đề cương ngay trong bước tạo công việc (wizard).

    Hỗ trợ nhiều file (file chính + file phụ): nội dung trùng giữa các file
    được gộp thành 1 đầu mục kèm cờ report_secondary + danh sách file nguồn.
    """
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Phiên làm việc đã hết hạn."}), 401
    _ensure_task_schema()
    return _parse_outline_file_for_create()

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
    return _delete_task_route(tid)

@tasks_bp.route("/tasks/<int:tid>/edit_config", methods=["POST"])
def edit_task_config(tid):
    """Route để sửa cấu hình công việc từ danh sách."""
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _edit_task_config(tid)

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
    return _download_task_submission_file_v2(tid, file_id)

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

# Pha 3 Feature 1 — Tổng hợp số liệu FORM
@tasks_bp.route("/tasks/<int:tid>/form-data")
def form_data_aggregation(tid):
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _form_data_aggregation_view(tid)

# Pha 3 Feature 2 — Tìm kiếm toàn cục
@tasks_bp.route("/tasks/search")
def global_search():
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _global_search_page()

# Pha 3 Feature 3 — Bảng điều khiển báo cáo định kỳ
@tasks_bp.route("/tasks/report-dashboard")
def report_dashboard():
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

    _ensure_task_schema()
    return _report_dashboard_page()
