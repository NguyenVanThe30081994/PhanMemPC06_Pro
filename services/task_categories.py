# -*- coding: utf-8 -*-
"""
Helper danh mục phân loại công việc (lĩnh vực / đội nghiệp vụ / loại / ưu tiên).

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

from flask import g, has_request_context

from category_helpers import module_category_options, resolve_category_display


def _task_domain_options():
    return module_category_options("tasks", "domain", "Đội nghiệp vụ")


def _task_field_options():
    return module_category_options("notify", "category", "Lĩnh vực", "Đội nghiệp vụ")


def _task_type_options():
    return module_category_options("tasks", "task_type", "Loại công việc")


def _task_priority_options():
    return module_category_options("tasks", "priority", "Mức độ ưu tiên")


def _task_assignment_unit_options():
    if has_request_context():
        cached = getattr(g, "_task_assignment_unit_options", None)
        if cached is not None:
            return cached

    merged = []
    seen = set()
    for options in (
        module_category_options("contacts", "unit_name", "Đơn vị"),
        _task_domain_options(),
    ):
        for item in options or []:
            stable_value = (item.get("stable_value") or "").strip()
            option_key = stable_value or (item.get("value") or "").strip() or (item.get("name") or "").strip()
            if not option_key or option_key in seen:
                continue
            seen.add(option_key)
            merged.append(item)

    if has_request_context():
        g._task_assignment_unit_options = merged
    return merged


def _task_field_display(value, options, fallback_label):
    return resolve_category_display(value, options, fallback_label=fallback_label)


def _decorate_task_categories(task, field_options, domain_options, type_options, priority_options):
    field_info = _task_field_display(task.category, field_options, "Chưa phân lĩnh vực")
    domain_info = _task_field_display(task.domain, domain_options, "Chưa phân đơn vị")
    type_info = _task_field_display(task.task_type, type_options, "Công việc thường xuyên")
    priority_info = _task_field_display(task.priority, priority_options, "Trung bình")

    setattr(task, "category_display", field_info["display_name"])
    setattr(task, "category_filter", field_info["filter_value"])
    setattr(task, "domain_display", domain_info["display_name"])
    setattr(task, "domain_filter", domain_info["filter_value"])
    setattr(task, "task_type_display", type_info["display_name"])
    setattr(task, "priority_display", priority_info["display_name"])

    return {
        "category": field_info,
        "domain": domain_info,
        "task_type": type_info,
        "priority": priority_info,
    }
