# -*- coding: utf-8 -*-
"""
Cụm helper màn làm việc (workspace): thẻ tiến độ theo đơn vị, nhóm theo vai trò,
nhóm tiến độ assignment, nhóm hợp đồng giao việc theo chế độ nộp, lọc theo phạm vi
người xử lý, lưu tệp đính kèm, khóa nhóm nộp + đồng bộ submission trong nhóm,
truy vấn assignment/đầu mục và trạng thái nộp.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export các tên còn dùng.
"""

import os
from datetime import datetime

from flask import current_app
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from models import TaskAssignment, TaskItem, TaskSubmission, User, db
from task_workspace import (
    summarize_task_assignments,
    task_assignment_submit_scope,
    task_deadline_display,
    task_workspace_tone,
)
from utils import remove_accents

from services.task_modes import (
    COMPLETED_STATUS,
    IN_PROGRESS_STATUS,
    TASK_ASSIGNMENT_STATUS_LABELS,
    _normalize_status,
)
from services.task_report_schema import (
    _load_task_report_schema,
    _task_report_item_visible_for_user,
)
from services.task_form_fields import _task_form_fields_for_user
from services.task_runtime_sync import _assignment_report_snapshot
from services.task_units import _task_assignee_unit_name, _task_unit_identity

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

# Pha 2: helper báo cáo Đề án 06 đã chuyển sang services/task_da06.py;
# _save_task_attachment không còn nơi gọi (mã chết) nên gỡ hẳn.
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

def _task_is_submitted(assignment):
    return str(getattr(assignment, "status", "") or "").strip().lower() in {"submitted", "completed"}

def _build_rebuilt_task_summary(task, current_uid):
    assignments = TaskAssignment.query.filter_by(task_id=task.id).all()
    return summarize_task_assignments(assignments, current_uid, _task_is_submitted)

def _task_deadline_display(deadline):
    return task_deadline_display(deadline)

def _task_workspace_tone(status_text, is_overdue=False):
    return task_workspace_tone(status_text, is_overdue=is_overdue)
