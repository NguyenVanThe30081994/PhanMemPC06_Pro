# -*- coding: utf-8 -*-
"""
Đồng bộ runtime task: cầu nối Task/TaskAssignment sang TaskItem/TaskParticipant/
TaskSubmission, hàng assignment, snapshot báo cáo và backfill toàn DB.

Tách từ routes/tasks.py (Pha 2, cụm runtime-sync). routes/tasks.py vẫn re-export
toàn bộ tên cũ nên migrate.py, các route và test không đổi.
"""

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import current_app
from sqlalchemy.orm import joinedload

from models import (
    Task,
    TaskAssignment,
    TaskItem,
    TaskParticipant,
    TaskSubmission,
    User,
    db,
)
from services.outline_submission import _parse_task_submission_payload
from services.task_modes import COMPLETED_STATUS, IN_PROGRESS_STATUS, _normalize_status
from services.task_report_schema import CHILD_TASK_ALLOWED_REPORT_KINDS, _load_task_report_schema
from services.task_scope import _load_assignment_scope, _load_manager_scope, _load_viewer_scope
from services.task_units import _dedupe_users, _resolve_role_assignees

REPORT_PREFIX = "[BÁO CÁO]"
REPORT_ATTACHMENT_RE = re.compile(r"\s*\(Đính kèm:\s*([^)]+)\)\s*$")
CHILD_TASK_NUMBER_FIELD_KEY = "reported_value"


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

def _parse_report_number(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Giá trị số không hợp lệ.") from exc

def _task_submission_sort_key(submission):
    return (
        getattr(submission, "submitted_at", None)
        or getattr(submission, "updated_at", None)
        or getattr(submission, "created_at", None)
        or datetime.min
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

def _task_report_meta(schema):
    meta = (schema or {}).get("meta")
    return meta if isinstance(meta, dict) else {}

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
