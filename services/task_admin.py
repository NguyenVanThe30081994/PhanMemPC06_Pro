# -*- coding: utf-8 -*-
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
from report_cycles import config_to_json as report_config_to_json, deadline_for as report_deadline_for
from task_policies import store_viewer_scope, store_manager_scope
from utils import apply_migrations, log_action, push_notif, remove_accents, render_auto_template as render_template
from services.blueprint_parsing import _parse_reference_file_to_blueprint

from services.task_deadline import _parse_task_report_period_from_request
from services.task_guards import _can_delete_task, _can_edit_task, _can_manage_task
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


def _delete_task_route(tid):
    """Route handler: xóa công việc (Pha 2 đợt 12: tách từ routes/tasks.py)."""
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

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


def _edit_task_config(tid):
    """Route handler: sửa cấu hình công việc từ danh sách (Pha 2 đợt 12: tách từ routes/tasks.py)."""
    if not session.get("uid"):
        return redirect(url_for("auth_bp.login"))

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
