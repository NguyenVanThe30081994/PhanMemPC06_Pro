# -*- coding: utf-8 -*-
import json
from datetime import datetime


def payload_from_request(request_obj):
    payload = request_obj.form.get("payload_json")
    if payload:
        try:
            return json.loads(payload)
        except Exception:
            return {}
    if request_obj.is_json:
        return request_obj.get_json(silent=True) or {}
    return {}


def submission_error_message(errors, fallback):
    if not errors:
        return fallback
    first = errors[0]
    if isinstance(first, (tuple, list)) and len(first) >= 3:
        return str(first[2])
    if isinstance(first, (tuple, list)) and first:
        return str(first[0])
    return str(first)


def save_submission(
    instance,
    payload,
    final_submit=False,
    report_date=None,
    get_cycle_fn=None,
    get_template_version_fn=None,
    report_type_fn=None,
    ensure_reporting_period_fn=None,
    get_report_unit_fn=None,
    normalize_sheet_values_fn=None,
    resolve_daily_submission_date_fn=None,
    has_later_daily_submission_fn=None,
    daily_snapshot_submissions_through_date_fn=None,
    effective_daily_cell_values_fn=None,
    merge_sheet_values_fn=None,
    make_submission_fn=None,
    add_fn=None,
    flush_fn=None,
    count_submissions_fn=None,
    load_sheet_fields_fn=None,
    column_index_from_string_fn=None,
    make_submission_cell_fn=None,
    make_submission_value_fn=None,
    field_display_name_fn=None,
    make_validation_log_fn=None,
    commit_fn=None,
    export_submission_fn=None,
    write_submission_backup_fn=None,
    rollback_fn=None,
    logger=None,
    current_session_uid=None,
):
    cycle = get_cycle_fn(instance.cycle_id)
    template_version = get_template_version_fn(cycle.template_version_id)
    report_type = report_type_fn(cycle)
    period = ensure_reporting_period_fn(cycle, report_type=report_type)
    report_unit = get_report_unit_fn(instance.report_unit_id) if getattr(instance, "report_unit_id", None) else None
    sheet_meta = json.loads(template_version.metadata_json or "{}").get("sheets", [])
    sheets = {sheet["sheet_name"]: sheet for sheet in sheet_meta}

    payload_sheets = normalize_sheet_values_fn(payload.get("sheets", {}) if isinstance(payload, dict) else {})
    errors = []
    stored_sheet_values = payload_sheets

    existing_version = count_submissions_fn(instance.id)
    metadata_payload = {"note": payload.get("note", "") if isinstance(payload, dict) else ""}
    if report_type and getattr(report_type, "code", None) == "daily":
        report_date = resolve_daily_submission_date_fn(cycle, report_date=report_date, instance_id=instance.id)
        if has_later_daily_submission_fn(instance.id, report_date):
            return None, [f"Không thể cập nhật ngày {report_date.strftime('%d/%m/%Y')} vì đã có báo cáo ngày mới hơn."]
        metadata_payload["report_date"] = report_date.strftime("%Y-%m-%d")
        metadata_payload["storage_mode"] = "full_snapshot"
        metadata_payload["entry_values"] = payload_sheets
        base_submissions = daily_snapshot_submissions_through_date_fn(instance.id, report_date)
        base_values = effective_daily_cell_values_fn(base_submissions, template_version.id)
        stored_sheet_values = merge_sheet_values_fn(base_values, payload_sheets)

    submission = make_submission_fn(
        template_id=template_version.template_id,
        template_version_id=template_version.id,
        period_id=period.id if period else cycle.id,
        report_period=cycle.name,
        reporting_unit=report_unit.name if report_unit else "",
        submitted_by=current_session_uid or instance.assigned_user_id or instance.user_id or 0,
        instance_id=instance.id,
        version_no=existing_version + 1,
        status="submitted" if final_submit else "draft",
        original_filename=template_version.source_filename,
        original_file_path=template_version.source_path,
        processed_file_path="",
        error_file_path="",
        total_rows=0,
        valid_rows=0,
        invalid_rows=0,
        warning_count=0,
        metadata_json=json.dumps(metadata_payload, ensure_ascii=False),
        note=payload.get("note", "") if isinstance(payload, dict) else "",
        submitted_at=datetime.now() if final_submit else None,
    )
    add_fn(submission)
    flush_fn()

    submission_value_rows = []
    for sheet_name, cells in stored_sheet_values.items():
        if sheet_name not in sheets:
            continue
        sheet_fields = list(load_sheet_fields_fn(template_version.id, sheet_name) or [])
        field_by_col = {field.column_index: field for field in sheet_fields}
        for cell_address, raw_value in cells.items():
            col_letters = "".join(ch for ch in cell_address if ch.isalpha())
            row_digits = "".join(ch for ch in cell_address if ch.isdigit())
            if not col_letters or not row_digits:
                continue
            column_index = column_index_from_string_fn(col_letters)
            field = field_by_col.get(column_index)
            field_code = field.field_code if field else ""
            text_value = "" if raw_value is None else str(raw_value).strip()
            number_value = None
            if field and getattr(field, "data_type", None) in {"number", "float", "decimal"}:
                try:
                    number_value = float(text_value.replace(",", ""))
                except Exception:
                    number_value = None
            add_fn(
                make_submission_cell_fn(
                    submission_id=submission.id,
                    sheet_name=sheet_name,
                    cell_address=cell_address,
                    raw_value=text_value,
                    is_formula=False,
                    formula_text="",
                )
            )
            if field_code:
                value_row = make_submission_value_fn(
                    submission_id=submission.id,
                    sheet_name=sheet_name,
                    field_code=field_code,
                    cell_address=cell_address,
                    value_text=text_value,
                    value_number=number_value,
                    value_json=json.dumps({"cell": cell_address, "value": text_value}, ensure_ascii=False),
                )
                submission_value_rows.append(value_row)
                add_fn(value_row)
        for field in sheet_fields:
            if getattr(field, "is_required", False):
                has_value = any(
                    value_row.sheet_name == sheet_name
                    and value_row.field_code == field.field_code
                    and (value_row.value_text or value_row.value_number is not None)
                    for value_row in submission_value_rows
                )
                if not has_value:
                    field_label = field_display_name_fn(field)
                    errors.append((sheet_name, field_label, "Trường bắt buộc chưa có dữ liệu"))
                    add_fn(
                        make_validation_log_fn(
                            submission_id=submission.id,
                            sheet_name=sheet_name,
                            field_code=field.field_code,
                            cell_address="",
                            severity="error",
                            message=f"Trường '{field_label}' chưa có dữ liệu",
                        )
                    )

    if errors and final_submit:
        submission.status = "draft"
        instance.status = "draft"
        commit_fn()
        return submission, errors

    if final_submit:
        instance.status = "submitted"
        instance.submitted_at = datetime.now()
        instance.locked_at = datetime.now()
    else:
        instance.status = "draft"
        instance.updated_at = datetime.now()

    commit_fn()
    try:
        export_path = export_submission_fn(submission, values=stored_sheet_values, commit=False)
        submission.processed_file_path = export_path
        if final_submit:
            submission.file_path = export_path
        write_submission_backup_fn(submission, stored_sheet_values)
        commit_fn()
    except Exception:
        if logger:
            logger.exception("Unable to persist report submission artifacts", exc_info=True)
        rollback_fn()
    return submission, errors


def export_submission(
    submission,
    values=None,
    commit=True,
    get_instance_fn=None,
    get_cycle_fn=None,
    get_version_fn=None,
    safe_filename_fn=None,
    report_export_folder="",
    normalize_sheet_values_fn=None,
    submission_cell_values_fn=None,
    write_workbook_copy_fn=None,
    make_report_export_job_fn=None,
    add_fn=None,
    commit_fn=None,
    os_path_join_fn=None,
    os_path_basename_fn=None,
    now_fn=None,
):
    now_fn = now_fn or datetime.now
    instance = get_instance_fn(submission.instance_id)
    cycle = get_cycle_fn(instance.cycle_id)
    version = get_version_fn(cycle.template_version_id)
    output_name = safe_filename_fn(f"{version.template_id}_cycle_{cycle.id}_submission_{submission.id}.xlsx")
    output_path = os_path_join_fn(report_export_folder, output_name)
    normalized_values = normalize_sheet_values_fn(values or submission_cell_values_fn(submission.id))
    write_workbook_copy_fn(version.source_path, output_path, normalized_values)
    add_fn(
        make_report_export_job_fn(
            cycle_id=cycle.id,
            submission_id=submission.id,
            status="done",
            output_path=output_path,
            finished_at=now_fn(),
        )
    )
    submission.processed_file_path = output_path
    if commit:
        commit_fn()
    return output_path
