# -*- coding: utf-8 -*-
"""
Đọc/lọc trường biểu mẫu (TaskFormField) theo phạm vi người nhận.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ
nên các chỗ gọi hiện có không đổi.
"""

from models import TaskFormField
from services.task_report_schema import _task_report_item_visible_for_user
from task_read_models import form_field_options, normalize_task_form_field_type


TASK_FORM_ALLOWED_FIELD_TYPES = {"text", "number", "textarea", "radio", "checkbox", "table"}


def _normalize_task_form_field_type(value):
    return normalize_task_form_field_type(value, TASK_FORM_ALLOWED_FIELD_TYPES)


def _task_form_fields(task):
    return (
        TaskFormField.query.filter_by(task_id=task.id)
        .order_by(TaskFormField.sort_order.asc(), TaskFormField.id.asc())
        .all()
    )


def _form_field_options(field):
    return form_field_options(field)


def _task_form_field_visible_for_user(field, user):
    return _task_report_item_visible_for_user(_form_field_options(field), user)


def _task_form_fields_for_user(task, user):
    return [field for field in _task_form_fields(task) if _task_form_field_visible_for_user(field, user)]
