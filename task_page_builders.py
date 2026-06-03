# -*- coding: utf-8 -*-
from datetime import date, datetime


def task_visible_for_user(task, current_uid, can_view_all_tasks=False, is_admin=False, is_executor=False, is_manager=False, is_viewer=False):
    return bool(
        can_view_all_tasks
        or is_admin
        or getattr(task, "author_id", None) == current_uid
        or is_executor
        or is_manager
        or is_viewer
    )


def prepare_task_workspace_record(
    task,
    current_uid,
    is_lead,
    build_summary_fn,
    task_mode_fn,
    task_mode_label_fn,
    task_mode_description_fn,
    task_assignment_status_label_fn,
    can_edit_task_fn,
    can_delete_task_fn,
    task_assignment_display_status_fn,
    build_workspace_attrs_fn,
    today=None,
):
    today = today or date.today()
    summary = build_summary_fn(task, current_uid)
    mode = task_mode_fn(task)
    setattr(task, "task_mode", mode)
    setattr(task, "task_mode_label", task_mode_label_fn(mode))
    setattr(task, "task_mode_description", task_mode_description_fn(mode))
    setattr(task, "progress_percent", summary["progress_percent"])
    setattr(task, "assignee_count", summary["total_assignments"])
    setattr(task, "submitted_assignments", summary["submitted_assignments"])
    setattr(task, "in_progress_assignments", summary["in_progress_assignments"])
    setattr(task, "current_user_assignment", summary["current_assignment"])
    setattr(task, "current_user_status_label", task_assignment_status_label_fn(getattr(summary["current_assignment"], "status", "")))
    setattr(
        task,
        "is_overdue",
        bool(getattr(task, "deadline", None) and getattr(task, "deadline", None) < today and summary["submitted_assignments"] < summary["total_assignments"]),
    )
    setattr(task, "can_edit", can_edit_task_fn(task))
    setattr(task, "can_delete", can_delete_task_fn(task, is_lead=is_lead))

    current_assignment = summary["current_assignment"]
    workspace_attrs = build_workspace_attrs_fn(
        task,
        summary,
        current_uid,
        task_assignment_display_status_fn(getattr(current_assignment, "status", "")),
        today=today,
    )
    for attr_name, attr_value in workspace_attrs.items():
        setattr(task, attr_name, attr_value)
    return task


def sort_task_rows(task, far_future=None):
    far_future = far_future or datetime.max.date()
    updated_at = getattr(task, "updated_at", None) or getattr(task, "created_at", None) or datetime.min
    timestamp_value = updated_at.timestamp() if isinstance(updated_at, datetime) else 0
    return (
        0 if getattr(task, "workspace_needs_attention", False) else 1,
        0 if getattr(task, "is_overdue", False) else 1,
        0 if getattr(task, "deadline", None) else 1,
        getattr(task, "deadline", None) or far_future,
        -timestamp_value,
    )


def build_task_list_page_context(tasks, mode_default):
    visible_tasks = sorted(list(tasks or []), key=sort_task_rows)
    outline_tasks = [task for task in visible_tasks if getattr(task, "task_mode", mode_default) == "OUTLINE"]
    file_tasks = [task for task in visible_tasks if getattr(task, "task_mode", mode_default) == "FILE"]
    form_tasks = [task for task in visible_tasks if getattr(task, "task_mode", mode_default) == "FORM"]
    attention_tasks = [task for task in visible_tasks if getattr(task, "workspace_needs_attention", False)]
    my_tasks = [task for task in visible_tasks if getattr(task, "workspace_role", "") == "my"]
    managed_tasks = [task for task in visible_tasks if getattr(task, "workspace_role", "") == "managed" and task not in my_tasks]
    watch_tasks = [task for task in visible_tasks if getattr(task, "workspace_role", "") == "watch"]
    completed_tasks = [task for task in visible_tasks if getattr(task, "is_complete", False)]
    return {
        "tasks": visible_tasks,
        "attention_tasks": attention_tasks,
        "my_tasks": my_tasks,
        "managed_tasks": managed_tasks,
        "watch_tasks": watch_tasks,
        "outline_tasks": outline_tasks,
        "file_tasks": file_tasks,
        "form_tasks": form_tasks,
        "stats": {
            "total": len(visible_tasks),
            "attention": len(attention_tasks),
            "my": len(my_tasks),
            "managed": len(managed_tasks),
            "completed": len(completed_tasks),
            "outline": len(outline_tasks),
            "file": len(file_tasks),
            "form": len(form_tasks),
        },
    }


def build_task_detail_page_context(
    task,
    current_uid,
    mode,
    can_manage_task_view,
    is_executor,
    build_summary_fn,
    parse_outline_rows_fn,
    build_outline_groups_fn,
    build_file_rows_fn,
    build_form_rows_fn,
    build_form_field_views_fn,
    build_task_detail_context_fn,
):
    summary = build_summary_fn(task, current_uid)
    outline_rows = parse_outline_rows_fn(task, current_uid) if mode == "OUTLINE" else []
    outline_groups = build_outline_groups_fn(task, current_uid) if mode == "OUTLINE" else []
    file_rows = build_file_rows_fn(task, current_uid) if mode == "FILE" else []
    form_fields, form_rows = build_form_rows_fn(task, current_uid) if mode == "FORM" else ([], [])
    form_field_views = build_form_field_views_fn(task) if mode == "FORM" else []

    my_file_assignment = next((row["assignment"] for row in file_rows if row["is_current_user"]), None)
    my_file_submission = next((row["submission"] for row in file_rows if row["is_current_user"]), None)
    my_form_assignment = next((row["assignment"] for row in form_rows if row["is_current_user"]), None)
    my_form_submission = next((row["submission"] for row in form_rows if row["is_current_user"]), None)
    my_form_payload = next((row["payload"] for row in form_rows if row["is_current_user"]), {})

    detail_context = build_task_detail_context_fn(
        task,
        summary,
        mode,
        can_manage_task_view,
        is_executor,
        my_file_assignment=my_file_assignment,
        my_form_assignment=my_form_assignment,
        outline_groups=outline_groups,
    )
    setattr(task, "progress_percent", detail_context["progress_percent"])
    setattr(task, "is_overdue", detail_context["is_overdue"])

    return {
        "summary": summary,
        "outline_rows": outline_rows,
        "outline_groups": outline_groups,
        "file_rows": file_rows,
        "form_fields": form_fields,
        "form_rows": form_rows,
        "form_field_views": form_field_views,
        "my_file_assignment": my_file_assignment,
        "my_file_submission": my_file_submission,
        "my_form_assignment": my_form_assignment,
        "my_form_submission": my_form_submission,
        "my_form_payload": my_form_payload,
        "detail_context": detail_context,
    }
