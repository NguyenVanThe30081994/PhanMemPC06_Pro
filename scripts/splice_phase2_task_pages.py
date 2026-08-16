# -*- coding: utf-8 -*-
"""Pha 2 đợt 11: tách band page handlers (L581-1943, 9 defs) sang services/task_pages.py
và band google-form v2 (L2081-2537, 6 defs) sang services/task_google_forms_v2.py."""
import ast
import shutil

SRC = "routes/tasks.py"
NEW_A = "services/task_pages.py"
NEW_B = "services/task_google_forms_v2.py"
BACKUP = "/tmp/routes_tasks_backup_pre_task_pages.py"

shutil.copyfile(SRC, BACKUP)

text = open(SRC, encoding="utf-8").read()
lines = text.splitlines()

tree = ast.parse(text)
tops = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
band_a = [n for n in tops if 580 < n.lineno <= 1943]
band_b = [n for n in tops if 2080 < n.lineno <= 2537]
assert len(band_a) == 9, [n.name for n in band_a]
assert len(band_b) == 6, [n.name for n in band_b]
assert band_a[0].lineno == 581 and band_a[-1].end_lineno == 1943, (band_a[0].lineno, band_a[-1].end_lineno)
assert band_b[0].lineno == 2081 and band_b[-1].end_lineno == 2537, (band_b[0].lineno, band_b[-1].end_lineno)
for n in band_a + band_b:
    assert n.decorator_list == [], (n.name,)
    prev = lines[n.lineno - 2]
    assert prev in ("",) or prev.startswith("#"), (n.name, repr(prev))
assert lines[1943] == "", lines[1943]
assert lines[2537] == "", lines[2537]

band_a_text = "\n".join(lines[580:1943])
band_b_text = "\n".join(lines[2080:2537])

HEADER_A = '''# -*- coding: utf-8 -*-
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
    _filter_assignment_rows_for_executor_scope,
    _filter_outline_groups_for_executor_scope,
    _store_uploaded_task_file,
    _sync_assignment_group_submission,
    _task_assignment_progress_groups,
    _task_delivery_contract_groups,
    _task_is_submitted,
)
from services.task_workspace_views import (
    _build_file_task_rows,
    _build_form_task_rows,
    _build_outline_group_rows,
    _clear_outline_import_preview,
    _get_outline_import_preview,
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
)

'''

HEADER_B = '''# -*- coding: utf-8 -*-
"""
Cụm đồng bộ Google Form cho task: trả assignment về (_return_task_assignment_v2),
tạo/cập nhật/xuất bản/nhập cấu trúc/đồng bộ phản hồi Google Form
(_create_task_google_form_v2, _update_task_google_form_v2, _publish_task_google_form_v2,
_import_task_google_form_structure_v2, _sync_google_form_task_v2).

Tách từ routes/tasks.py (Pha 2). routes/tasks.py re-export các tên còn dùng.
"""

from datetime import datetime

from flask import current_app, flash, redirect, request, session, url_for

from models import (
    Task,
    TaskAssignment,
    TaskComment,
    TaskSubmission,
    User,
    db,
)
from google_forms import (
    build_google_forms_service,
    create_google_form,
    extract_google_form_id,
    fetch_google_form_definition,
    fetch_google_form_responses,
    load_google_form_into_builder,
    parse_google_form_definition,
    parse_google_form_responses,
    publish_google_form,
    update_google_form,
)
from permissions import current_is_admin

from services.task_google_forms import (
    _filter_google_form_response_for_assignment,
    _hydrate_google_form_fields,
    _match_google_form_response_to_assignment,
    _merge_google_form_field_targets,
    _normalize_google_form_builder_schema_with_targets,
    _normalize_google_form_match_mode,
    _parse_google_form_builder_schema,
    _replace_task_form_fields,
    _task_google_form_builder,
    _task_google_form_manage_service,
    _task_google_form_runtime,
    _task_google_form_runtime_payload,
    _task_google_form_sync_state,
)
from services.task_guards import (
    _can_edit_task,
    _can_manage_task,
    _can_watch_task,
)
from services.task_import_draft_helpers import _json_dump
from services.task_import_drafts import (
    _task_assignment_scope_lists,
    _validate_task_visibility_before_publish,
)
from services.task_modes import _task_mode
from services.task_permissions import _can_process_task_module, _current_perms
from services.task_runtime_sync import _task_assignment_records
from services.task_units import _dedupe_users
from services.task_workspace_helpers import _sync_assignment_group_submission

'''

module_a_text = HEADER_A + band_a_text + "\n"
module_b_text = HEADER_B + band_b_text + "\n"
ast.parse(module_a_text)
ast.parse(module_b_text)

for label, module_text in (("A", module_a_text), ("B", module_b_text)):
    mod_tree = ast.parse(module_text)
    defined = set()
    for n in mod_tree.body:
        if isinstance(n, ast.FunctionDef):
            defined.add(n.name)
        elif isinstance(n, (ast.ImportFrom, ast.Import)):
            for a in n.names:
                defined.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
        elif isinstance(n, ast.Try):
            for node in ast.walk(n):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            defined.add(t.id)
    import builtins
    builtin_names = set(dir(builtins))
    used = set()
    for fn in [x for x in mod_tree.body if isinstance(x, ast.FunctionDef)]:
        local = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                local.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.add(node.name)
            elif isinstance(node, ast.arg):
                local.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local.add(node.name)
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in local:
                    used.add(node.id)
    missing = sorted(u for u in used if u not in defined and u not in builtin_names)
    assert missing == [], f"thiếu import trong module {label}: {missing}"

with open(NEW_A, "w", encoding="utf-8") as fh:
    fh.write(module_a_text)
with open(NEW_B, "w", encoding="utf-8") as fh:
    fh.write(module_b_text)

REEXPORT_A = (
    "# Pha 2 đợt 11: band page handlers chuyển sang services/task_pages.py.\n"
    "from services.task_pages import (  # noqa: E402\n"
    "    _tasks_page_v2,\n"
    "    _task_detail_v2,\n"
    "    _create_outline_items_v2,\n"
    "    _preview_outline_import_v2,\n"
    "    _update_task_status_v2,\n"
    "    _submit_task_report_v2,\n"
    "    _export_form_task_v2,\n"
    "    _export_outline_word_v2,\n"
    ")"
)
REEXPORT_B = (
    "# Pha 2 đợt 11: band google-form v2 chuyển sang services/task_google_forms_v2.py.\n"
    "from services.task_google_forms_v2 import (  # noqa: E402\n"
    "    _return_task_assignment_v2,\n"
    "    _create_task_google_form_v2,\n"
    "    _update_task_google_form_v2,\n"
    "    _publish_task_google_form_v2,\n"
    "    _import_task_google_form_structure_v2,\n"
    "    _sync_google_form_task_v2,\n"
    ")"
)

BAND_COMMENT = ("# Pha 2 đợt 11: band page handlers (danh sách/chi tiết/đầu mục/trạng thái/nộp/xuất)\n"
                "# + band google-form v2 (trả assignment/tạo/cập nhật/xuất bản/nhập/đồng bộ Google Form)\n"
                "# chuyển sang services/task_pages.py + services/task_google_forms_v2.py.")

new_lines = (
    lines[:580]
    + BAND_COMMENT.splitlines()
    + REEXPORT_A.splitlines()
    + REEXPORT_B.splitlines()
    + [""]
    + lines[1944:2080]
    + [""]
    + lines[2538:]
)

new_text = "\n".join(new_lines) + "\n"
ast.parse(new_text)
with open(SRC, "w", encoding="utf-8") as fh:
    fh.write(new_text)

print("OK: routes/tasks.py", len(lines), "->", len(new_lines), "dòng; module A", len(module_a_text.splitlines()), "dòng; module B", len(module_b_text.splitlines()), "dòng")
