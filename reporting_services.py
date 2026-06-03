# -*- coding: utf-8 -*-
from datetime import date


def workspace_route_values(cycle, unit=None, report_date=None, can_manage_templates=False):
    values = {"cycle_id": cycle.id}
    if unit and can_manage_templates:
        values["unit_id"] = unit.id
    if report_date:
        values["report_date"] = report_date.strftime("%Y-%m-%d")
    return values


def safe_back_url(raw_value):
    value = str(raw_value or "").strip()
    if not value or not value.startswith("/") or value.startswith("//"):
        return ""
    return value


def default_cycle_back_url(cycle, url_builder, report_date=None, is_admin=False):
    if is_admin:
        values = {}
        if report_date:
            values["report_date"] = report_date.strftime("%Y-%m-%d")
        return url_builder("reporting_bp.admin_cycle_detail", cycle_id=cycle.id, **values)
    return url_builder("reporting_bp.user_dashboard")


def route_with_back(endpoint, cycle, url_builder, back_url="", unit=None, report_date=None, can_manage_templates=False):
    values = workspace_route_values(
        cycle,
        unit=unit,
        report_date=report_date,
        can_manage_templates=can_manage_templates,
    )
    if back_url:
        values["back"] = back_url
    return url_builder(endpoint, **values)


def resolve_cycle_context(
    cycle_id,
    prefer_all_units,
    can_manage_templates,
    request_unit_id,
    request_report_date,
    finalize_due_daily_cycles_fn,
    get_cycle_fn,
    resolve_cycle_unit_fn,
    cycle_accessible_fn,
    get_user_fn,
    get_cycle_instance_fn,
    get_template_version_fn,
    get_template_fn,
    report_type_fn,
    is_cycle_view_locked_fn,
    parse_date_fn,
    effective_daily_cutoff_date_fn,
    resolve_entry_submission_state_fn,
    resolve_working_submission_state_fn,
    resolve_effective_instance_state_fn,
):
    finalize_due_daily_cycles_fn(cycle_id=cycle_id)
    cycle = get_cycle_fn(cycle_id)
    if not cycle:
        return None

    admin_all_units = bool(prefer_all_units and can_manage_templates and not request_unit_id)
    unit = None if admin_all_units else resolve_cycle_unit_fn(cycle)
    if not cycle_accessible_fn(cycle, getattr(unit, "id", None) if unit else None, can_manage_templates):
        return None

    user = get_user_fn()
    instance = None if admin_all_units else get_cycle_instance_fn(cycle, unit, user)
    template_version = get_template_version_fn(cycle.template_version_id)
    template = get_template_fn(template_version.template_id) if template_version else None
    report_type = report_type_fn(cycle)
    view_locked = is_cycle_view_locked_fn(cycle)

    report_date = None
    if report_type and getattr(report_type, "code", None) == "daily":
        requested_report_date = parse_date_fn(request_report_date or "")
        if view_locked:
            report_date = effective_daily_cutoff_date_fn(cycle, instance.id if instance else None)
        elif requested_report_date:
            report_date = requested_report_date
        else:
            report_date = date.today()

    entry_state = resolve_entry_submission_state_fn(
        instance,
        template_version,
        report_type=report_type,
        report_date=report_date,
    )
    working_state = resolve_working_submission_state_fn(
        instance,
        template_version,
        report_type=report_type,
        report_date=report_date,
    )
    effective_state = resolve_effective_instance_state_fn(
        instance,
        cycle,
        template_version,
        report_type=report_type,
    )

    return {
        "cycle": cycle,
        "unit": unit,
        "user": user,
        "instance": instance,
        "template_version": template_version,
        "template": template,
        "report_type": report_type,
        "report_date": effective_state["report_date"] if view_locked and effective_state.get("report_date") else report_date,
        "latest_submission": effective_state["latest_submission"] if view_locked else entry_state["latest_submission"],
        "submission_history": effective_state["history"] if view_locked else entry_state["history"],
        "entry_values": effective_state["existing_values"] if view_locked else entry_state["existing_values"],
        "view_submission": effective_state["latest_submission"] if view_locked else working_state["latest_submission"],
        "view_history": effective_state["history"] if view_locked else working_state["history"],
        "working_values": effective_state["existing_values"] if view_locked else working_state["existing_values"],
        "daily_submissions": effective_state["daily_submissions"] if view_locked else working_state["daily_submissions"],
        "view_locked": view_locked,
    }
