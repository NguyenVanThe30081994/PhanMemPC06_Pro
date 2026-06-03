# -*- coding: utf-8 -*-
from datetime import date


def submission_timeliness(cycle, submission, report_type=None, report_type_getter=None, business_date_getter=None):
    if not submission:
        return "Chưa nộp"
    report_type = report_type or (report_type_getter(cycle) if report_type_getter else None)
    submitted_at = submission.submitted_at or submission.created_at
    if not submitted_at:
        return "Đã lưu"
    report_code = getattr(report_type, "code", "") if report_type else ""
    if report_code == "daily":
        business_date = business_date_getter(submission) if business_date_getter else None
        if cycle:
            report_day = (cycle.open_at or cycle.created_at or submitted_at).date()
        else:
            report_day = business_date or submitted_at.date()
        if business_date == report_day:
            return "Đúng ngày"
        if business_date:
            return f"Báo cáo ngày {business_date.strftime('%d/%m/%Y')}"
        return f"Báo cáo ngày {submitted_at.strftime('%d/%m/%Y')}"
    if cycle and getattr(cycle, "due_at", None):
        return "Đúng hạn" if submitted_at <= cycle.due_at else "Quá hạn"
    return "Đã báo cáo"


def resolve_working_submission_state(
    instance,
    template_version,
    report_type=None,
    report_date=None,
    daily_snapshot_submissions_through_date_fn=None,
    submission_history_through_date_fn=None,
    effective_daily_cell_values_fn=None,
    latest_submission_fn=None,
    submission_history_fn=None,
    submission_cell_values_fn=None,
):
    if not instance or not template_version:
        return {
            "latest_submission": None,
            "history": [],
            "existing_values": {},
            "daily_submissions": [],
        }
    if report_type and getattr(report_type, "code", None) == "daily" and report_date:
        daily_submissions = daily_snapshot_submissions_through_date_fn(instance.id, report_date)
        latest_submission = daily_submissions[-1] if daily_submissions else None
        history = submission_history_through_date_fn(instance.id, report_date)
        existing_values = effective_daily_cell_values_fn(daily_submissions, template_version.id)
        return {
            "latest_submission": latest_submission,
            "history": history,
            "existing_values": existing_values,
            "daily_submissions": daily_submissions,
        }

    latest_submission = latest_submission_fn(instance.id)
    history = submission_history_fn(instance.id)
    existing_values = submission_cell_values_fn(latest_submission.id) if latest_submission else {}
    return {
        "latest_submission": latest_submission,
        "history": history,
        "existing_values": existing_values,
        "daily_submissions": [],
    }


def resolve_entry_submission_state(
    instance,
    template_version,
    report_type=None,
    report_date=None,
    latest_submission_for_date_fn=None,
    submission_history_fn=None,
    latest_submission_fn=None,
    submission_cell_values_fn=None,
):
    if not instance or not template_version:
        return {
            "latest_submission": None,
            "history": [],
            "existing_values": {},
        }
    if report_type and getattr(report_type, "code", None) == "daily" and report_date:
        latest_submission = latest_submission_for_date_fn(instance.id, report_date)
        history = submission_history_fn(instance.id, report_date=report_date)
        existing_values = submission_cell_values_fn(latest_submission.id) if latest_submission else {}
        return {
            "latest_submission": latest_submission,
            "history": history,
            "existing_values": existing_values,
        }

    latest_submission = latest_submission_fn(instance.id)
    history = submission_history_fn(instance.id)
    existing_values = submission_cell_values_fn(latest_submission.id) if latest_submission else {}
    return {
        "latest_submission": latest_submission,
        "history": history,
        "existing_values": existing_values,
    }


def resolve_effective_instance_state(
    instance,
    cycle,
    template_version,
    report_type=None,
    effective_daily_cutoff_date_fn=None,
    resolve_working_submission_state_fn=None,
):
    if not instance or not cycle or not template_version:
        return {
            "latest_submission": None,
            "history": [],
            "existing_values": {},
            "daily_submissions": [],
            "report_date": None,
            "mode": "empty",
        }
    if report_type and getattr(report_type, "code", None) == "daily":
        cutoff_date = effective_daily_cutoff_date_fn(cycle, instance.id)
        state = resolve_working_submission_state_fn(
            instance,
            template_version,
            report_type=report_type,
            report_date=cutoff_date,
        )
        state["report_date"] = cutoff_date
        state["mode"] = "daily_cumulative"
        return state

    state = resolve_working_submission_state_fn(
        instance,
        template_version,
        report_type=report_type,
        report_date=None,
    )
    state["report_date"] = None
    state["mode"] = "latest_snapshot"
    return state


def cycle_view_export_context(
    context,
    report_admin_mode,
    request_unit_id,
    exportable,
    list_cycle_instances_fn,
    daily_snapshot_submissions_through_date_fn,
    effective_daily_cell_values_fn,
    latest_submission_fn,
    merged_submission_cell_values_fn,
    normalize_code_fn,
):
    cycle = context["cycle"]
    template_version = context["template_version"]
    report_type = context["report_type"]
    report_date = context["report_date"]
    admin_all_units = report_admin_mode and not request_unit_id

    if admin_all_units:
        instances = list_cycle_instances_fn(cycle.id)
        latest_submissions = []
        if report_type and getattr(report_type, "code", None) == "daily" and report_date:
            existing_values = {}
            for instance in instances:
                submissions = daily_snapshot_submissions_through_date_fn(instance.id, report_date)
                if not submissions:
                    continue
                latest_submissions.append(submissions[-1])
                unit_values = effective_daily_cell_values_fn(submissions, template_version.id)
                for sheet_name, cells in unit_values.items():
                    existing_values.setdefault(sheet_name, {}).update(cells)
            mode = "daily_cumulative"
        else:
            latest_submissions = [
                submission
                for instance in instances
                for submission in [latest_submission_fn(instance.id)]
                if submission
            ]
            existing_values = merged_submission_cell_values_fn(latest_submissions)
            mode = "latest_snapshot"
        effective_at = max(
            (
                submission.submitted_at or submission.created_at
                for submission in latest_submissions
                if submission and (submission.submitted_at or submission.created_at)
            ),
            default=None,
        )
        return {
            "template_version": template_version,
            "report_type": report_type,
            "report_date": report_date,
            "existing_values": existing_values,
            "latest_submission": latest_submissions[-1] if latest_submissions else None,
            "has_data": exportable,
            "mode": mode,
            "scope_label": "toan_bo_don_vi",
            "effective_at": effective_at,
            "admin_all_units": True,
        }

    unit = context["unit"]
    latest_submission = context["view_submission"]
    existing_values = context.get("working_values", {}) or {}
    return {
        "template_version": template_version,
        "report_type": report_type,
        "report_date": report_date,
        "existing_values": existing_values,
        "latest_submission": latest_submission,
        "has_data": exportable,
        "mode": "daily_cumulative" if report_type and getattr(report_type, "code", None) == "daily" and report_date else "latest_snapshot",
        "scope_label": normalize_code_fn(unit.name) if unit else "khong_xac_dinh",
        "effective_at": (latest_submission.submitted_at or latest_submission.created_at) if latest_submission else None,
        "admin_all_units": False,
    }


def history_rows_for_submissions(
    submissions,
    template_version,
    report_type,
    include_unit=False,
    include_actor=False,
    cycle=None,
    load_workbook_fn=None,
    load_fields_fn=None,
    load_users_fn=None,
    load_instances_fn=None,
    load_units_fn=None,
    build_submission_summary_fn=None,
    submission_status_label_fn=None,
    submission_timeliness_fn=None,
):
    if not submissions or not template_version:
        return []

    workbook = load_workbook_fn(template_version.source_path)
    fields = list(load_fields_fn(template_version.id) or [])
    field_lookup = {(field.sheet_name, field.field_code): field for field in fields}
    sheet_fields = {}
    for field in fields:
        sheet_fields.setdefault(field.sheet_name, []).append(field)

    user_ids = {submission.submitted_by for submission in submissions if submission.submitted_by}
    user_map = {user.id: user for user in load_users_fn(user_ids)} if user_ids else {}
    instance_ids = {submission.instance_id for submission in submissions if submission.instance_id}
    instances = list(load_instances_fn(instance_ids)) if instance_ids else []
    instance_map = {instance.id: instance for instance in instances}
    unit_ids = {instance.report_unit_id for instance in instances if getattr(instance, "report_unit_id", None)}
    unit_map = {unit.id: unit for unit in load_units_fn(unit_ids)} if unit_ids else {}

    rows = []
    for submission in submissions:
        summary = build_submission_summary_fn(
            submission,
            template_version,
            workbook=workbook,
            field_lookup=field_lookup,
            sheet_fields=sheet_fields,
        )
        row = {
            "submission": submission,
            "submitted_at": submission.submitted_at or submission.created_at,
            "content_text": summary["text"],
            "content_count": summary["count"],
            "status_label": submission_status_label_fn(submission),
            "timeliness": submission_timeliness_fn(cycle, submission, report_type=report_type),
        }
        if include_actor:
            row["actor"] = user_map.get(submission.submitted_by)
        if include_unit:
            instance = instance_map.get(submission.instance_id)
            row["unit"] = unit_map.get(instance.report_unit_id) if instance and getattr(instance, "report_unit_id", None) else None
            row["instance"] = instance
        rows.append(row)
    return rows
