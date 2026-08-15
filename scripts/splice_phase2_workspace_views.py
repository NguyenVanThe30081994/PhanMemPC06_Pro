# -*- coding: utf-8 -*-
"""Pha 2 đợt 9: tách band helper view đề cương/biểu mẫu/dòng tác vụ +
cấu hình đầu mục từ request/session (L624..trước _tasks_page_v2) sang
services/task_workspace_views.py; gỡ def chết _is_category_item_reference."""
import ast
import shutil

SRC = "routes/tasks.py"
NEW = "services/task_workspace_views.py"
BACKUP = "/tmp/routes_tasks_backup_pre_workspace_views.py"

shutil.copyfile(SRC, BACKUP)

text = open(SRC, encoding="utf-8").read()
lines = text.splitlines()

def find(predicate, start=0):
    for i in range(start, len(lines)):
        if predicate(lines[i]):
            return i
    raise AssertionError("không tìm thấy dòng khớp")

# --- anchors theo nội dung ---
i_dead = find(lambda s: s == "def _is_category_item_reference(value):")
assert lines[i_dead + 1].startswith("    return bool(re.fullmatch(r\"category_item"), lines[i_dead + 1]
assert lines[i_dead - 1] == "" and lines[i_dead + 2] == "", (lines[i_dead - 1], lines[i_dead + 2])

i_band_start = find(lambda s: s.startswith("def _task_detail_context("))
i_band_end = find(lambda s: s == "def _tasks_page_v2():", i_band_start)
assert lines[i_band_start - 1] == "", lines[i_band_start - 1]

band_lines = lines[i_band_start:i_band_end]
band_text = "\n".join(band_lines)

# --- kiểm tra cấu trúc band ---
band_tree = ast.parse(band_text)
band_defs = [n for n in band_tree.body if isinstance(n, ast.FunctionDef)]
band_names = [n.name for n in band_defs]
assert band_names == [
    "_task_detail_context",
    "_outline_table_schema_map",
    "_outline_item_table_cells",
    "_render_outline_table_html",
    "_parse_outline_item_rows",
    "_task_item_synthesis_text",
    "_outline_item_number_fields",
    "_parse_outline_item_configs_from_request",
    "_outline_import_preview_session_key",
    "_get_outline_import_preview",
    "_set_outline_import_preview",
    "_clear_outline_import_preview",
    "_resolve_outline_item_assignment",
    "_outline_group_identity",
    "_build_outline_group_rows",
    "_build_file_task_rows",
    "_task_form_value_is_empty",
    "_parse_task_form_fields_from_request",
    "_task_form_submission_payload",
    "_build_form_task_rows",
    "_task_form_field_views",
    "_task_form_field_views_for_user",
], band_names
for n in band_defs:
    assert n.decorator_list == [], (n.name,)
    prev = band_lines[n.lineno - 2]
    assert prev == "" or prev.startswith("#"), (n.name, prev)

HEADER = '''# -*- coding: utf-8 -*-
"""
Cụm helper dựng màn làm việc theo hình thái: chi tiết task, đọc/tái hiện bảng đề cương,
dòng đầu mục đề cương (kèm submission/người nhận), cấu hình đầu mục + trường biểu mẫu
từ request/session, nhận diện nhóm đề cương và các dòng file/form.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py re-export các tên còn dùng.
"""

import html
import json
import re

from flask import session
from werkzeug.datastructures import MultiDict
from werkzeug.utils import secure_filename

from task_read_models import (
    build_file_task_rows,
    build_form_task_rows,
    build_outline_group_rows,
    outline_group_identity,
    task_form_field_views,
    task_form_submission_payload,
    task_form_value_is_empty,
)
from task_workspace import build_task_detail_context
from utils import remove_accents

from services.outline_engine import _clean_outline_title, _extract_number_fields_from_text
from services.outline_submission import (
    _parse_task_submission_payload,
    _render_blank_editor_html,
)
from services.task_assignees import _resolve_assignees, _resolve_assignees_by_mode
from services.task_form_fields import (
    _form_field_options,
    _normalize_task_form_field_type,
    _task_form_fields,
    _task_form_fields_for_user,
)
from services.task_import_draft_helpers import (
    _task_import_form_field_options_json,
    _task_import_parse_id_csv,
)
from services.task_modes import TASK_ASSIGNMENT_STATUS_LABELS, _normalize_status
from services.task_report_schema import (
    CHILD_TASK_ALLOWED_REPORT_KINDS,
    _load_task_report_schema,
    _normalize_report_target_config,
    _task_report_item_visible_for_user,
)
from services.task_runtime_sync import _latest_assignment_submission
from services.task_scope import _requested_role_ids, _requested_unit_domains
from services.task_units import _task_assignee_unit_name
from services.task_workspace_helpers import (
    _task_assignments_query,
    _task_is_submitted,
    _task_items_for_task,
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
    "# Pha 2 đợt 9: cụm helper view đề cương/biểu mẫu/dòng tác vụ chuyển sang\n"
    "# services/task_workspace_views.py.\n"
    "from services.task_workspace_views import (  # noqa: E402\n"
    "    _outline_table_schema_map,\n"
    "    _outline_item_table_cells,\n"
    "    _render_outline_table_html,\n"
    "    _parse_outline_item_rows,\n"
    "    _outline_item_number_fields,\n"
    "    _parse_outline_item_configs_from_request,\n"
    "    _resolve_outline_item_assignment,\n"
    "    _parse_task_form_fields_from_request,\n"
    "    _build_form_task_rows,\n"
    "    _task_form_field_views_for_user,\n"
    ")"
)

BAND_COMMENT = ("# Pha 2 đợt 9: band helper màn làm việc (chi tiết task, bảng/dòng đề cương,\n"
                "# cấu hình đầu mục/trường biểu mẫu từ request, dòng file/form) chuyển sang\n"
                "# services/task_workspace_views.py; _is_category_item_reference gỡ (mã chết).")

new_lines = (
    lines[:i_dead]                       # bỏ def chết _is_category_item_reference (2 dòng)
    + lines[i_dead + 2:i_band_start]
    + BAND_COMMENT.splitlines()
    + REEXPORT.splitlines()
    + [""]
    + lines[i_band_end:]
)

new_text = "\n".join(new_lines) + "\n"
ast.parse(new_text)
with open(SRC, "w", encoding="utf-8") as fh:
    fh.write(new_text)

print("OK: routes/tasks.py", len(lines), "->", len(new_lines), "dòng; module mới", len(module_text.splitlines()), "dòng")
