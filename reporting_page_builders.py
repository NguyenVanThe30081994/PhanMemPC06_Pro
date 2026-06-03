# -*- coding: utf-8 -*-


def build_cycle_dashboard_maps(
    cycles,
    report_date,
    report_type_getter,
    progress_getter,
    status_getter,
    deadline_text_getter,
    instance_map=None,
):
    instance_map = instance_map or {}
    cycle_report_types = {}
    cycle_progress_map = {}
    cycle_status_map = {}
    cycle_deadline_map = {}
    for cycle in cycles or []:
        report_type = report_type_getter(cycle)
        cycle_report_types[cycle.id] = report_type
        progress = progress_getter(cycle, report_type=report_type, report_date=report_date)
        cycle_progress_map[cycle.id] = progress
        cycle_status_map[cycle.id] = status_getter(
            cycle,
            instance=instance_map.get(cycle.id),
            report_type=report_type,
            report_date=report_date,
            progress=progress,
        )
        cycle_deadline_map[cycle.id] = deadline_text_getter(cycle, report_type=report_type)
    return {
        "cycle_report_types": cycle_report_types,
        "cycle_progress_map": cycle_progress_map,
        "cycle_status_map": cycle_status_map,
        "cycle_deadline_map": cycle_deadline_map,
    }


def build_admin_reporting_dashboard_context(
    templates,
    versions,
    cycles,
    units,
    report_types,
    professional_units,
    recent_submissions,
    current_versions,
    template_report_types,
    cycle_status_map,
    cycle_progress_map,
    cycle_deadline_map,
    hero_stats,
    template_groups,
):
    return {
        "templates": templates,
        "template_groups": template_groups,
        "versions": versions,
        "cycles": cycles,
        "units": units,
        "report_types": report_types,
        "professional_units": professional_units,
        "recent_submissions": recent_submissions,
        "current_versions": current_versions,
        "template_report_types": template_report_types,
        "cycle_status_map": cycle_status_map,
        "cycle_progress_map": cycle_progress_map,
        "cycle_deadline_map": cycle_deadline_map,
        "hero_stats": hero_stats,
        "can_view_cycle_progress": True,
        "is_admin": True,
    }


def build_user_reporting_dashboard_context(
    user,
    unit,
    instances,
    latest_submission_map,
    dashboard_maps,
    hero_stats,
    accessible_cycles,
    can_view_cycle_progress,
    is_admin,
    cycle_groups,
):
    return {
        "templates": [],
        "cycle_groups": cycle_groups,
        "versions": [],
        "cycles": accessible_cycles,
        "units": [unit] if unit else [],
        "report_types": [],
        "recent_submissions": [],
        "current_versions": {},
        "is_admin": is_admin,
        "current_unit": unit,
        "current_user": user,
        "instances": instances,
        "instance_map": {instance.cycle_id: instance for instance in (instances or [])},
        "latest_submission_map": latest_submission_map,
        "cycle_report_types": dashboard_maps["cycle_report_types"],
        "cycle_progress_map": dashboard_maps["cycle_progress_map"],
        "cycle_status_map": dashboard_maps["cycle_status_map"],
        "cycle_deadline_map": dashboard_maps["cycle_deadline_map"],
        "hero_stats": hero_stats,
        "can_view_cycle_progress": can_view_cycle_progress,
    }


def build_cycle_workspace_sheet_views(
    metadata,
    workbook,
    template_version_id,
    report_admin_mode,
    unit,
    existing_values,
    sheet_fields_getter,
    header_range_getter,
    input_row_indexes_getter,
    sheet_has_unit_identity_fields_fn,
    row_matches_unit_fn,
    cell_display_value_fn,
    field_display_name_fn,
    field_levels_fn,
    row_context_label_fn,
):
    sheet_views = []
    for sheet_meta in (metadata.get("sheets", []) if isinstance(metadata, dict) else []):
        ws = workbook[sheet_meta["sheet_name"]]
        sheet_fields = list(sheet_fields_getter(template_version_id, sheet_meta["sheet_name"]) or [])
        editable_fields = [field for field in sheet_fields if getattr(field, "is_visible", False) and getattr(field, "is_editable", False)]
        if not editable_fields:
            editable_fields = [field for field in sheet_fields if getattr(field, "is_editable", False)]
        _, header_end_row = header_range_getter(sheet_meta)
        candidate_row_indexes = input_row_indexes_getter(sheet_meta)
        should_filter_by_unit = (not report_admin_mode) and bool(unit) and sheet_has_unit_identity_fields_fn(sheet_fields)
        row_entries = []
        for row_index in candidate_row_indexes:
            if ws.row_dimensions[row_index].hidden:
                continue
            if should_filter_by_unit and not row_matches_unit_fn(
                ws,
                sheet_fields,
                existing_values,
                sheet_meta["sheet_name"],
                row_index,
                unit,
            ):
                continue
            inputs = []
            for field in editable_fields:
                coord = f"{field.column_letter}{row_index}"
                value = existing_values.get(sheet_meta["sheet_name"], {}).get(coord, ws[coord].value)
                levels = field_levels_fn(field)
                inputs.append(
                    {
                        "cell_address": coord,
                        "value": cell_display_value_fn(value),
                        "field_code": field.field_code,
                        "field_label": field_display_name_fn(field),
                        "field_path": " / ".join(levels[:-1]) if len(levels) > 1 else "",
                    }
                )
            if inputs:
                row_entries.append(
                    {
                        "excel_row": row_index,
                        "title": row_context_label_fn(ws, sheet_fields, existing_values, sheet_meta["sheet_name"], row_index),
                        "inputs": inputs,
                    }
                )
        warning = ""
        if should_filter_by_unit and not row_entries:
            warning = (
                f"Chưa tìm thấy dòng nào trên sheet '{sheet_meta['sheet_name']}' khớp với đơn vị "
                f"'{unit.name}'. Hãy kiểm tra cột đơn vị trong file Excel hoặc tên đơn vị của tài khoản."
            )
        sheet_views.append(
            {
                "sheet_name": sheet_meta["sheet_name"],
                "field_count": len(sheet_meta.get("fields", [])),
                "input_count": len(editable_fields),
                "rows": row_entries,
                "warning": warning,
                "config": {
                    "header_start_row": sheet_meta.get("header_start_row"),
                    "header_end_row": sheet_meta.get("header_end_row"),
                    "unit_start_row": sheet_meta.get("unit_start_row") or sheet_meta.get("data_start_row"),
                    "unit_end_row": sheet_meta.get("unit_end_row") or sheet_meta.get("data_end_row"),
                    "total_start_row": sheet_meta.get("total_start_row"),
                    "total_end_row": sheet_meta.get("total_end_row"),
                    "start_column": sheet_meta.get("start_column"),
                    "end_column": sheet_meta.get("end_column"),
                },
            }
        )
    return sheet_views


def build_cycle_preview_sheets(
    metadata,
    workbook,
    existing_values,
    formula_values,
    header_range_getter,
    column_index_from_string_fn,
    preferred_sticky_column_fn,
    render_sheet_html_fn,
):
    preview_sheets = []
    for sheet_meta in (metadata.get("sheets", []) if isinstance(metadata, dict) else []):
        ws = workbook[sheet_meta["sheet_name"]]
        start_row, header_end_row = header_range_getter(sheet_meta)
        unit_end_row = int(sheet_meta.get("unit_end_row") or sheet_meta.get("data_end_row") or header_end_row + 1)
        total_end_row = int(sheet_meta.get("total_end_row") or 0)
        start_col = column_index_from_string_fn(sheet_meta.get("start_column") or "A")
        end_col = column_index_from_string_fn(sheet_meta.get("end_column") or sheet_meta.get("start_column") or "A")
        sheet_values = {
            **existing_values.get(sheet_meta["sheet_name"], {}),
            **formula_values.get(sheet_meta["sheet_name"], {}),
        }
        sticky_col = preferred_sticky_column_fn(sheet_meta, ws, sheet_values)
        preview_sheets.append(
            {
                "sheet_name": sheet_meta["sheet_name"],
                "html": render_sheet_html_fn(
                    ws,
                    editable_values=sheet_values,
                    field_lookup={},
                    editable=False,
                    start_row=start_row,
                    end_row=max(unit_end_row, total_end_row or 0),
                    min_col=start_col,
                    max_col=end_col,
                    header_end_row=header_end_row,
                    sticky_first_col=sticky_col,
                ),
            }
        )
    return preview_sheets


def build_cycle_history_context(context, history_rows, is_admin, back_url):
    return {
        "cycle": context["cycle"],
        "template": context["template"],
        "report_type": context["report_type"],
        "report_date": context["report_date"],
        "report_date_str": context["report_date"].strftime("%d/%m/%Y") if context["report_date"] else "",
        "current_unit": context["unit"],
        "latest_submission": context["view_submission"],
        "history_rows": history_rows,
        "is_admin": is_admin,
        "back_url": back_url,
    }
