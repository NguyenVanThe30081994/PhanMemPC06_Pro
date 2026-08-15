# -*- coding: utf-8 -*-
"""
Chế độ công việc (OUTLINE/FILE/FORM) + nhãn trạng thái assignment.

Tách từ routes/tasks.py (Pha 2) — cluster đầu tiên, chỉ chứa hằng số và
hàm thuần (không đụng DB/request), dùng chung cho route, service và test.
routes/tasks.py vẫn re-export toàn bộ tên cũ nên mã gọi hiện có không đổi.
"""

from task_workspace import task_assignment_display_status

PENDING_STATUSES = {"Chưa tiếp nhận", "Chưa bắt đầu", None, ""}
IN_PROGRESS_STATUS = "Đang thực hiện"
COMPLETED_STATUS = "Hoàn thành"

TASK_MODE_ALLOWED = {"OUTLINE", "FILE", "FORM"}
TASK_MODE_DEFAULT = "FILE"
TASK_MODE_LABELS = {
    "OUTLINE": "Theo đề cương",
    "FILE": "Nộp file",
    "FORM": "Biểu mẫu",
}
TASK_MODE_DESCRIPTIONS = {
    "OUTLINE": "Tạo đợt giao việc theo đề cương, chia thành các đầu mục và giao từng mục cho đơn vị hoặc cá nhân.",
    "FILE": "Giao việc trực tiếp và yêu cầu nộp nội dung, file minh chứng hoặc văn bản tổng hợp.",
    "FORM": "Thu thập dữ liệu theo biểu mẫu động, phù hợp để tổng hợp số liệu và xuất báo cáo.",
}
TASK_ASSIGNMENT_STATUS_LABELS = {
    "assigned": "Chưa tiếp nhận",
    "in_progress": "Đang thực hiện",
    "submitted": "Đã nộp",
    "returned": "Bị trả lại",
    "completed": "Hoàn thành",
    "overdue": "Quá hạn",
}


def _normalize_status(status):
    return "Chưa tiếp nhận" if status in PENDING_STATUSES else status


def _normalize_task_mode(value):
    normalized = str(value or "").strip().upper()
    if normalized in TASK_MODE_ALLOWED:
        return normalized
    return ""


def _requested_task_mode(form, fallback=TASK_MODE_DEFAULT):
    requested = _normalize_task_mode(form.get("task_mode"))
    if requested:
        return requested
    normalized_fallback = _normalize_task_mode(fallback)
    return normalized_fallback or TASK_MODE_DEFAULT


def _task_mode(task, has_child_tasks=None):
    if not task:
        return TASK_MODE_DEFAULT
    cached = getattr(task, "_task_mode_cache", None)
    if cached:
        return cached

    explicit = _normalize_task_mode(getattr(task, "task_mode", None))
    if explicit:
        setattr(task, "_task_mode_cache", explicit)
        return explicit

    inferred = TASK_MODE_DEFAULT
    setattr(task, "_task_mode_cache", inferred)
    return inferred


def _task_mode_label(task_mode):
    normalized = _normalize_task_mode(task_mode)
    return TASK_MODE_LABELS.get(normalized, TASK_MODE_LABELS[TASK_MODE_DEFAULT])


def _task_mode_description(task_mode):
    normalized = _normalize_task_mode(task_mode)
    return TASK_MODE_DESCRIPTIONS.get(normalized, TASK_MODE_DESCRIPTIONS[TASK_MODE_DEFAULT])


def _task_assignment_status_label(status):
    return TASK_ASSIGNMENT_STATUS_LABELS.get(str(status or "").strip().lower(), "Chưa tiếp nhận")


def _task_assignment_display_status(status):
    return task_assignment_display_status(status, TASK_ASSIGNMENT_STATUS_LABELS, _normalize_status)


def _task_assignment_status_class(status):
    normalized = str(status or "").strip().lower()
    if normalized in {"completed", "submitted"}:
        return "done"
    if normalized in {"in_progress", "returned"}:
        return "doing"
    if normalized == "overdue":
        return "danger"
    return "todo"
