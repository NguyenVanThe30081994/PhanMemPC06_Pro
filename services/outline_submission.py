# -*- coding: utf-8 -*-
"""
Nộp báo cáo theo đề cương: liên kết đầu mục trùng (báo cáo phụ), lan truyền
submission, ghép/giá trị ô trống và HTML editor ô số liệu.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

import html
import json
from datetime import datetime

from flask import session

from models import TaskAssignment, TaskComment, TaskItem, TaskSubmission, db
from services.outline_engine import _normalize_outline_match_text
from services.task_units import _users_for_unit


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



def _parse_task_submission_payload(submission):
    raw_payload = getattr(submission, "payload_json", None) or ""
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

