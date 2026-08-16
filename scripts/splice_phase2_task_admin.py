# -*- coding: utf-8 -*-
"""Pha 2 đợt 10: tách band task-admin + task-import pages (L2608-3274, 21 defs)
sang services/task_admin.py."""
import ast
import shutil

SRC = "routes/tasks.py"
NEW = "services/task_admin.py"
BACKUP = "/tmp/routes_tasks_backup_pre_task_admin.py"

shutil.copyfile(SRC, BACKUP)

text = open(SRC, encoding="utf-8").read()
lines = text.splitlines()

tree = ast.parse(text)
tops = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
band = [n for n in tops if 2556 < n.lineno <= 3223]
assert len(band) == 21, [n.name for n in band]
assert band[0].lineno == 2557 and band[-1].end_lineno == 3223, (band[0].lineno, band[-1].end_lineno)
for n in band:
    assert n.decorator_list == [], (n.name,)
    prev = lines[n.lineno - 2]
    assert prev in ("",) or prev.startswith("#"), (n.name, repr(prev))
assert lines[3223] == "", lines[3223]

band_lines = lines[2556:3223]
band_text = "\n".join(band_lines)

HEADER = '''# -*- coding: utf-8 -*-
"""
Cụm task-admin + task-import: xóa sạch task (purge), đảm bảo schema, trang trí
task cho danh sách, submenu/hướng dẫn import, lịch sử import, ngữ cảnh khối lượng
công việc đang hoạt động, phân tích/áp dụng AI cho draft, trang draft (list/detail),
tạo/lưu/xuất bản/analyze/apply draft.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py re-export các tên còn dùng.
"""

import json
import os
from datetime import datetime, timedelta

from flask import current_app, flash, g, jsonify, redirect, request, session, url_for
from sqlalchemy.orm import joinedload

from models import (
    AppRole,
    Task,
    TaskAssignment,
    TaskComment,
    TaskFormField,
    TaskImportDraft,
    TaskItem,
    TaskParticipant,
    TaskSubmission,
    TaskSubmissionFile,
    User,
    db,
)
from category_helpers import (
    canonicalize_category_value,
    resolve_category_display,
    stable_form_category_options,
)
from task_blueprints import (
    workflow_blueprint_example_catalog,
    workflow_blueprint_preview_data,
)
from task_import_ai import analyze_task_import_config, apply_ai_analysis_to_config
from permissions import current_is_admin
from utils import apply_migrations, push_notif, remove_accents, render_auto_template as render_template
from services.blueprint_parsing import _parse_reference_file_to_blueprint

from services.task_modes import COMPLETED_STATUS, IN_PROGRESS_STATUS, _normalize_status
from services.task_permissions import _can_process_task_module, _current_perms
from services.task_categories import _task_domain_options, _task_field_options, _task_priority_options, _task_type_options
from services.task_units import _task_unit_identity
from services.task_runtime_sync import (
    _backfill_task_runtime_models,
    _infer_assignment_context,
    _task_assignment_records,
    _task_assignment_rows,
    _task_scope_identity,
    _query_task_scope,
)
from services.task_workspace_helpers import _task_file_path
from services.task_import_draft_helpers import (
    TASK_IMPORT_SOURCE_TYPES,
    _json_dump,
    _task_import_source_label,
    _task_import_status_label,
)
from services.task_import_drafts import (
    _parse_task_workflow_blueprint_payload,
    _parse_task_import_working_config_from_form,
    _task_import_draft_blueprint,
    _task_import_draft_working_config,
    _task_import_working_config_from_blueprint,
    _task_import_recipient_preview,
    _publish_task_import_draft,
    _task_import_blueprint_from_config,
    _task_import_config_stats,
    TASK_IMPORT_ASSIGN_TYPE_LABELS,
    TASK_IMPORT_FIELD_TYPE_LABELS,
    TASK_IMPORT_REPORT_KIND_LABELS,
    TASK_IMPORT_TARGET_TYPE_LABELS,
)

'''

module_text = HEADER + band_text + "\n"
ast.parse(module_text)

# --- kiểm tra mọi tên dùng trong band đều đã import/định nghĩa ---
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
assert missing == [], f"thiếu import trong module mới: {missing}"

with open(NEW, "w", encoding="utf-8") as fh:
    fh.write(module_text)

REEXPORT = (
    "# Pha 2 đợt 10: band task-admin + task-import pages chuyển sang services/task_admin.py.\n"
    "from services.task_admin import (  # noqa: E402\n"
    "    _purge_task,\n"
    "    _ensure_task_schema,\n"
    "    _task_import_draft_render_context,\n"
    "    _task_import_drafts_page,\n"
    "    _create_task_import_draft_v2,\n"
    "    _task_import_draft_detail_page,\n"
    "    _save_task_import_draft_v2,\n"
    "    _publish_task_import_draft_v2,\n"
    "    _analyze_task_import_draft_ai_v2,\n"
    "    _apply_task_import_draft_ai_v2,\n"
    ")"
)

BAND_COMMENT = ("# Pha 2 đợt 10: band task-admin (purge/schema/decorate) + task-import pages\n"
                "# (submenu/history/workload/AI/draft pages) chuyển sang services/task_admin.py.")

new_lines = (
    lines[:2556]
    + BAND_COMMENT.splitlines()
    + REEXPORT.splitlines()
    + [""]
    + lines[3224:]
)

new_text = "\n".join(new_lines) + "\n"
ast.parse(new_text)
with open(SRC, "w", encoding="utf-8") as fh:
    fh.write(new_text)

print("OK: routes/tasks.py", len(lines), "->", len(new_lines), "dòng; module mới", len(module_text.splitlines()), "dòng")
