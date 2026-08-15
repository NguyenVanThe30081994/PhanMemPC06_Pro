# -*- coding: utf-8 -*-
"""
Phân tích hạn nộp + cấu hình 'cách báo cáo' (chu kỳ) của công việc.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

from datetime import datetime, timedelta

from report_cycles import (
    KIND_LABELS as REPORT_KIND_LABELS,
    PERIOD_LABELS as REPORT_PERIOD_LABELS,
    current_cycle as report_current_cycle,
    deadline_for as report_deadline_for,
    normalize_config as report_normalize_config,
    parse_config as report_parse_config,
    task_config as report_task_config,
)


def _parse_deadline(form):
    deadline_type = form.get("deadline_type", "custom")
    deadline_raw = form.get("deadline")
    now = datetime.now()

    if deadline_type == "custom" and deadline_raw:
        try:
            return datetime.strptime(deadline_raw, "%Y-%m-%d").date()
        except Exception:
            return None

    if deadline_type == "week":
        weekday = int(form.get("weekday", 0))
        days_until = (weekday - now.weekday()) % 7
        if days_until == 0:
            days_until = 7
        return (now + timedelta(days=days_until)).date()

    if deadline_type == "month":
        day_of_month = int(form.get("day_of_month", 1))
        try:
            return datetime(now.year, now.month, day_of_month).date()
        except Exception:
            return datetime(now.year, now.month, 28).date()

    if deadline_type == "quarter":
        day_of_month = int(form.get("day_of_month", 1))
        target_month = ((now.month - 1) // 3 + 1) * 3
        try:
            return datetime(now.year, target_month, day_of_month).date()
        except Exception:
            return datetime(now.year, target_month, 28).date()

    if deadline_type == "6months":
        day_of_month = int(form.get("day_of_month", 1))
        month_of_period = int(form.get("month_of_period", 6))
        try:
            return datetime(now.year, month_of_period, day_of_month).date()
        except Exception:
            return datetime(now.year, month_of_period, 28).date()

    if deadline_type == "year":
        day_of_month = int(form.get("day_of_month", 31))
        month_of_period = int(form.get("month_of_period", 12))
        try:
            return datetime(now.year, month_of_period, day_of_month).date()
        except Exception:
            return datetime(now.year, month_of_period, 28).date()

    return None


def _task_report_period(task):
    """Cấu hình cách báo cáo của công việc (dict chuẩn hóa)."""
    try:
        return report_task_config(task)
    except Exception:
        return report_normalize_config({})


def _parse_task_report_period_from_request(form, task_type=""):
    """Đọc cấu hình 'cách báo cáo' từ form tạo / sửa công việc."""
    data = dict(form or {})
    if task_type and not data.get("task_type"):
        data["task_type"] = task_type
    try:
        return report_parse_config(data)
    except Exception:
        return report_normalize_config({})


def _task_current_cycle(task, today=None):
    try:
        return report_current_cycle(_task_report_period(task), today=today)
    except Exception:
        return None


def _task_report_kind_label(task):
    cfg = _task_report_period(task)
    kind = str(cfg.get("kind") or "one_time").strip()
    label = REPORT_KIND_LABELS.get(kind)
    if not label:
        return "Báo cáo đột xuất / một lần"
    period = cfg.get("period")
    if kind == "periodic" and period in REPORT_PERIOD_LABELS:
        label = f"{label} — {REPORT_PERIOD_LABELS[period]}"
    return label


def _computed_task_deadline(form, task_type=""):
    """Hạn nộp theo 'cách báo cáo' — hạn của chu kỳ hiện tại khi tạo công việc."""
    try:
        cfg = _parse_task_report_period_from_request(form, task_type=task_type)
        return report_deadline_for(cfg)
    except Exception:
        return None
