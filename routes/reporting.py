# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from flask import Blueprint, current_app, flash, jsonify, redirect, request, session, send_file, url_for
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from models import (
    db,
    ReportAuditLog,
    ReportCycle,
    ReportExportJob,
    ReportInstance,
    ReportSubmission,
    ReportSubmissionCell,
    ReportSubmissionValue,
    ReportTemplate,
    ReportTemplateField,
    ReportTemplateSheet,
    ReportTemplateVersion,
    ReportType,
    ReportUnit,
    ReportValidationLog,
    User,
)
from report_engine import normalize_code, parse_workbook, render_sheet_html, safe_filename, write_workbook_copy
from utils import extract_unit_key, log_action, render_auto_template as render_template

reporting_bp = Blueprint("reporting_bp", __name__)


def _is_admin():
    return bool(session.get("is_admin"))


def _require_login():
    return bool(session.get("uid"))


def _ensure_default_types():
    defaults = [
        ("daily", "Hằng ngày", "daily", "Báo cáo hằng ngày"),
        ("periodic", "Định kỳ", "periodic", "Báo cáo định kỳ"),
        ("ad_hoc", "Đột xuất", "ad_hoc", "Báo cáo đột xuất"),
    ]
    changed = False
    for code, name, freq, desc in defaults:
        if not ReportType.query.filter_by(code=code).first():
            db.session.add(ReportType(code=code, name=name, frequency=freq, description=desc))
            changed = True
    if changed:
        db.session.commit()


def _sync_units_from_users():
    users = (
        User.query.filter(User.is_active.is_(True))
        .order_by(User.unit_area.asc(), User.fullname.asc())
        .all()
    )
    seen = set()
    changed = False
    for user in users:
        key = normalize_code(user.unit_key or user.unit_area or user.username)
        name = (user.unit_area or user.unit_key or user.fullname or user.username or "").strip()
        if not key or not name or key in seen:
            continue
        seen.add(key)
        unit = ReportUnit.query.filter_by(code=key).first()
        if not unit:
            db.session.add(ReportUnit(code=key, name=name, source="user", is_active=True))
            changed = True
        elif unit.name != name:
            unit.name = name
            unit.source = "user"
            changed = True
    if changed:
        db.session.commit()


def _current_user_report_unit():
    if not session.get("uid"):
        return None
    user = db.session.get(User, session.get("uid"))
    if not user:
        return None
    key = normalize_code(user.unit_key or extract_unit_key(user.unit_area or user.fullname or user.username))
    if key:
        unit = ReportUnit.query.filter_by(code=key, is_active=True).first()
        if unit:
            return unit
    if user.unit_area:
        key = normalize_code(user.unit_area)
        unit = ReportUnit.query.filter_by(code=key, is_active=True).first()
        if unit:
            return unit
    return None


def _template_version(template):
    version = (
        ReportTemplateVersion.query.filter_by(template_id=template.id, is_current=True)
        .order_by(ReportTemplateVersion.version_no.desc())
        .first()
    )
    if version:
        return version
    return (
        ReportTemplateVersion.query.filter_by(template_id=template.id)
        .order_by(ReportTemplateVersion.version_no.desc())
        .first()
    )


def _template_file_path(version):
    return version.source_path if version else None


def _scope_unit_ids(cycle):
    try:
        data = json.loads(cycle.scope_json or "[]")
        return {int(v) for v in data if str(v).isdigit()}
    except Exception:
        return set()


def _cycle_accessible(cycle, unit_id, is_admin=False):
    if is_admin:
        return True
    if not unit_id:
        return False
    scope = _scope_unit_ids(cycle)
    return not scope or unit_id in scope


def _get_cycle_instance(cycle, unit, user):
    instance = ReportInstance.query.filter_by(
        cycle_id=cycle.id,
        report_unit_id=unit.id if unit else None,
    ).first()
    if not instance and unit:
        instance = ReportInstance(
            cycle_id=cycle.id,
            report_unit_id=unit.id,
            assigned_user_id=user.id if user else None,
            status="draft",
        )
        db.session.add(instance)
        db.session.commit()
    return instance


def _latest_submission(instance_id):
    return (
        ReportSubmission.query.filter_by(instance_id=instance_id)
        .order_by(ReportSubmission.version_no.desc(), ReportSubmission.created_at.desc())
        .first()
    )


def _submission_cell_values(submission_id):
    values = {}
    rows = (
        ReportSubmissionCell.query.filter_by(submission_id=submission_id)
        .order_by(ReportSubmissionCell.id.asc())
        .all()
    )
    for row in rows:
        values.setdefault(row.sheet_name, {})[row.cell_address] = row.raw_value or ""
    return values


def _audit(action, object_type, object_id, details=""):
    try:
        db.session.add(
            ReportAuditLog(
                actor_user_id=session.get("uid"),
                action=action,
                module="report",
                object_type=object_type,
                object_id=object_id,
                details=details,
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        log_action(session.get("uid"), session.get("fullname", ""), action, "Báo cáo", details)
    except Exception:
        pass


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
    return None


def _save_submission(instance, payload, final_submit=False):
    cycle = db.session.get(ReportCycle, instance.cycle_id)
    template_version = db.session.get(ReportTemplateVersion, cycle.template_version_id)
    sheet_meta = json.loads(template_version.metadata_json or "{}").get("sheets", [])
    sheets = {sheet["sheet_name"]: sheet for sheet in sheet_meta}

    payload_sheets = payload.get("sheets", {}) if isinstance(payload, dict) else {}
    errors = []
    normalized = {}

    existing_version = (
        ReportSubmission.query.filter_by(instance_id=instance.id)
        .count()
    )
    submission = ReportSubmission(
        instance_id=instance.id,
        version_no=existing_version + 1,
        status="submitted" if final_submit else "draft",
        note=payload.get("note", "") if isinstance(payload, dict) else "",
        submitted_at=datetime.now() if final_submit else None,
    )
    db.session.add(submission)
    db.session.flush()

    for sheet_name, cells in payload_sheets.items():
        if sheet_name not in sheets:
            continue
        sheet_fields = ReportTemplateField.query.filter_by(
            version_id=template_version.id,
            sheet_name=sheet_name,
        ).all()
        field_by_col = {f.column_index: f for f in sheet_fields}
        sheet_values = cells if isinstance(cells, dict) else {}
        for cell_address, raw_value in sheet_values.items():
            col_letters = "".join(ch for ch in cell_address if ch.isalpha())
            row_digits = "".join(ch for ch in cell_address if ch.isdigit())
            if not col_letters or not row_digits:
                continue
            column_index = column_index_from_string(col_letters)
            field = field_by_col.get(column_index)
            field_code = field.field_code if field else ""
            text_value = "" if raw_value is None else str(raw_value).strip()
            number_value = None
            if field and field.data_type in {"number", "float", "decimal"}:
                try:
                    number_value = float(text_value.replace(",", ""))
                except Exception:
                    number_value = None
            db.session.add(
                ReportSubmissionCell(
                    submission_id=submission.id,
                    sheet_name=sheet_name,
                    cell_address=cell_address,
                    raw_value=text_value,
                    is_formula=False,
                    formula_text="",
                )
            )
            if field_code:
                db.session.add(
                    ReportSubmissionValue(
                        submission_id=submission.id,
                        sheet_name=sheet_name,
                        field_code=field_code,
                        cell_address=cell_address,
                        value_text=text_value,
                        value_number=number_value,
                        value_json=json.dumps({"cell": cell_address, "value": text_value}, ensure_ascii=False),
                    )
                )
        for field in sheet_fields:
            if field.is_required:
                has_value = any(v.field_code == field.field_code and (v.value_text or v.value_number is not None) for v in ReportSubmissionValue.query.filter_by(submission_id=submission.id).all())
                if not has_value:
                    errors.append((sheet_name, field.field_code, "Trường bắt buộc chưa có dữ liệu"))
                    db.session.add(
                        ReportValidationLog(
                            submission_id=submission.id,
                            sheet_name=sheet_name,
                            field_code=field.field_code,
                            cell_address="",
                            severity="error",
                            message="Trường bắt buộc chưa có dữ liệu",
                        )
                    )

    if errors and final_submit:
        submission.status = "draft"
        instance.status = "draft"
        db.session.commit()
        return submission, errors

    if final_submit:
        instance.status = "submitted"
        instance.submitted_at = datetime.now()
        instance.locked_at = datetime.now()
    else:
        instance.status = "draft"

    db.session.commit()
    return submission, errors


def _export_submission(submission):
    instance = db.session.get(ReportInstance, submission.instance_id)
    cycle = db.session.get(ReportCycle, instance.cycle_id)
    version = db.session.get(ReportTemplateVersion, cycle.template_version_id)
    output_name = safe_filename(f"{version.template_id}_cycle_{cycle.id}_submission_{submission.id}.xlsx")
    output_path = os.path.join(current_app.root_path, "report_exports", output_name)
    values = _submission_cell_values(submission.id)
    write_workbook_copy(version.source_path, output_path, values)
    job = ReportExportJob(
        cycle_id=cycle.id,
        submission_id=submission.id,
        status="done",
        output_path=output_path,
        finished_at=datetime.now(),
    )
    db.session.add(job)
    db.session.commit()
    return output_path


@reporting_bp.route("/admin/reports")
def admin_dashboard():
    if not _is_admin():
        return redirect(url_for("auth_bp.login"))
    _ensure_default_types()
    _sync_units_from_users()

    templates = ReportTemplate.query.order_by(ReportTemplate.updated_at.desc()).all()
    versions = ReportTemplateVersion.query.order_by(ReportTemplateVersion.created_at.desc()).all()
    cycles = ReportCycle.query.order_by(ReportCycle.created_at.desc()).all()
    units = ReportUnit.query.order_by(ReportUnit.name.asc()).all()
    report_types = ReportType.query.order_by(ReportType.name.asc()).all()
    recent_submissions = ReportSubmission.query.order_by(ReportSubmission.created_at.desc()).limit(20).all()

    current_versions = {}
    for template in templates:
        current_versions[template.id] = _template_version(template)

    return render_template(
        "reporting_dashboard.html",
        templates=templates,
        versions=versions,
        cycles=cycles,
        units=units,
        report_types=report_types,
        recent_submissions=recent_submissions,
        current_versions=current_versions,
        is_admin=True,
    )


@reporting_bp.route("/admin/reports/upload", methods=["POST"])
def upload_template():
    if not _is_admin():
        return redirect(url_for("auth_bp.login"))

    file = request.files.get("template_file")
    if not file or not file.filename.lower().endswith(".xlsx"):
        flash("Chỉ nhận file .xlsx", "danger")
        return redirect(url_for("reporting_bp.admin_dashboard"))

    code = normalize_code(request.form.get("code") or file.filename.rsplit(".", 1)[0]) or f"template_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    name = (request.form.get("name") or file.filename.rsplit(".", 1)[0]).strip()
    description = (request.form.get("description") or "").strip()
    header_rows = int(request.form.get("header_rows") or 2)
    data_start_row = int(request.form.get("data_start_row") or max(header_rows + 1, 3))
    notes = (request.form.get("notes") or "").strip()

    template = ReportTemplate.query.filter_by(code=code).first()
    if not template:
        template = ReportTemplate(code=code, name=name, description=description, status="active")
        db.session.add(template)
        db.session.flush()
    else:
        template.name = name
        template.description = description
        template.status = "active"
        db.session.flush()

    existing_versions = ReportTemplateVersion.query.filter_by(template_id=template.id).count()
    version_no = existing_versions + 1
    filename = safe_filename(f"{code}_v{version_no}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx")
    storage_path = os.path.join(current_app.root_path, "report_templates", filename)
    file.save(storage_path)

    metadata = parse_workbook(storage_path, header_rows=header_rows, data_start_row=data_start_row)
    for version in ReportTemplateVersion.query.filter_by(template_id=template.id).all():
        version.is_current = False

    version = ReportTemplateVersion(
        template_id=template.id,
        version_no=version_no,
        source_filename=secure_filename(file.filename),
        source_path=storage_path,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        notes=notes,
        is_current=True,
    )
    db.session.add(version)
    db.session.flush()

    for sheet in metadata.get("sheets", []):
        db.session.add(
            ReportTemplateSheet(
                version_id=version.id,
                sheet_name=sheet["sheet_name"],
                order_index=sheet["order_index"],
                header_rows=sheet["header_rows"],
                data_start_row=sheet["data_start_row"],
                data_end_row=sheet["data_end_row"],
                unit_key_column="A",
                can_input=True,
                visible_in_preview=True,
                summary_json=json.dumps({
                    "fields": len(sheet.get("fields", [])),
                    "input_cells": len(sheet.get("input_cells", [])),
                }, ensure_ascii=False),
            )
        )
        for field in sheet.get("fields", []):
            db.session.add(
                ReportTemplateField(
                    version_id=version.id,
                    sheet_name=sheet["sheet_name"],
                    field_code=field["field_code"],
                    field_name=field["field_name"],
                    column_index=field["column_index"],
                    column_letter=field["column_letter"],
                    data_type=field["data_type"],
                    input_mode=field["input_mode"],
                    is_required=field["is_required"],
                    is_visible=field["is_visible"],
                    is_editable=field["is_editable"],
                    default_value=field["default_value"],
                    validation_rule=field["validation_rule"],
                    dictionary_source=field["dictionary_source"],
                    formula_expression=field["formula_expression"],
                    aggregation_type=field["aggregation_type"],
                    display_order=field["display_order"],
                    path_code=field["path_code"],
                )
            )

    db.session.commit()
    _audit("upload_template", "report_template", template.id, name)
    flash("Đã tạo mẫu báo cáo mới.", "success")
    return redirect(url_for("reporting_bp.template_detail", template_id=template.id))


@reporting_bp.route("/admin/reports/templates/<int:template_id>")
def template_detail(template_id):
    if not _is_admin():
        return redirect(url_for("auth_bp.login"))
    template = db.session.get(ReportTemplate, template_id)
    if not template:
        return "Not Found", 404
    versions = ReportTemplateVersion.query.filter_by(template_id=template.id).order_by(ReportTemplateVersion.version_no.desc()).all()
    current_version = _template_version(template)
    sheets = []
    fields = []
    if current_version:
        sheets = ReportTemplateSheet.query.filter_by(version_id=current_version.id).order_by(ReportTemplateSheet.order_index.asc()).all()
        fields = ReportTemplateField.query.filter_by(version_id=current_version.id).order_by(ReportTemplateField.sheet_name.asc(), ReportTemplateField.display_order.asc()).all()
    metadata = json.loads(current_version.metadata_json or "{}") if current_version else {}
    return render_template(
        "reporting_template_detail.html",
        template=template,
        versions=versions,
        current_version=current_version,
        sheets=sheets,
        fields=fields,
        metadata=metadata,
    )


@reporting_bp.route("/admin/reports/templates/<int:template_id>/versions/<int:version_id>/activate", methods=["POST"])
def activate_version(template_id, version_id):
    if not _is_admin():
        return redirect(url_for("auth_bp.login"))
    ReportTemplateVersion.query.filter_by(template_id=template_id).update({"is_current": False})
    version = db.session.get(ReportTemplateVersion, version_id)
    if version:
        version.is_current = True
        db.session.commit()
        _audit("activate_version", "report_template_version", version.id, f"template={template_id}")
        flash("Đã kích hoạt phiên bản mẫu.", "success")
    return redirect(url_for("reporting_bp.template_detail", template_id=template_id))


@reporting_bp.route("/admin/reports/units/sync", methods=["POST"])
def sync_units():
    if not _is_admin():
        return redirect(url_for("auth_bp.login"))
    _sync_units_from_users()
    flash("Đã đồng bộ đơn vị từ tài khoản.", "success")
    return redirect(url_for("reporting_bp.admin_dashboard"))


@reporting_bp.route("/admin/reports/cycles", methods=["POST"])
def create_cycle():
    if not _is_admin():
        return redirect(url_for("auth_bp.login"))
    template_version_id = int(request.form.get("template_version_id") or 0)
    report_type_id = int(request.form.get("report_type_id") or 0)
    name = (request.form.get("name") or "").strip()
    if not template_version_id or not report_type_id or not name:
        flash("Thiếu dữ liệu tạo kỳ báo cáo.", "danger")
        return redirect(url_for("reporting_bp.admin_dashboard"))

    unit_ids = [int(v) for v in request.form.getlist("unit_ids") if str(v).isdigit()]
    if not unit_ids:
        unit_ids = [u.id for u in ReportUnit.query.filter_by(is_active=True).all()]

    cycle = ReportCycle(
        template_version_id=template_version_id,
        report_type_id=report_type_id,
        name=name,
        open_at=_parse_dt(request.form.get("open_at")),
        close_at=_parse_dt(request.form.get("close_at")),
        due_at=_parse_dt(request.form.get("due_at")),
        auto_lock_at=_parse_dt(request.form.get("auto_lock_at")),
        status="open",
        scope_json=json.dumps(unit_ids, ensure_ascii=False),
        is_locked=False,
        note=(request.form.get("note") or "").strip(),
    )
    db.session.add(cycle)
    db.session.flush()

    for unit_id in unit_ids:
        unit = db.session.get(ReportUnit, unit_id)
        user = None
        if unit:
            user = (
                User.query.filter(
                    or_(User.unit_key == unit.code, User.unit_area == unit.name)
                )
                .order_by(User.id.asc())
                .first()
            )
        db.session.add(
            ReportInstance(
                cycle_id=cycle.id,
                report_unit_id=unit_id,
                assigned_user_id=user.id if user else None,
                status="draft",
            )
        )

    db.session.commit()
    _audit("create_cycle", "report_cycle", cycle.id, name)
    flash("Đã mở kỳ báo cáo.", "success")
    return redirect(url_for("reporting_bp.admin_dashboard"))


@reporting_bp.route("/reports")
def user_dashboard():
    if not _require_login():
        return redirect(url_for("auth_bp.login"))
    _ensure_default_types()
    _sync_units_from_users()

    user = db.session.get(User, session.get("uid"))
    unit = _current_user_report_unit()
    is_admin = _is_admin()
    cycles = ReportCycle.query.order_by(ReportCycle.created_at.desc()).all()
    accessible_cycles = [cycle for cycle in cycles if _cycle_accessible(cycle, unit.id if unit else None, is_admin)]
    instances = []
    if unit:
        instances = ReportInstance.query.filter_by(report_unit_id=unit.id).order_by(ReportInstance.opened_at.desc()).all()

    return render_template(
        "reporting_dashboard.html",
        templates=[],
        versions=[],
        cycles=accessible_cycles,
        units=[unit] if unit else [],
        report_types=[],
        recent_submissions=[],
        current_versions={},
        is_admin=is_admin,
        current_unit=unit,
        current_user=user,
        instances=instances,
    )


@reporting_bp.route("/reports/cycles/<int:cycle_id>")
def cycle_workspace(cycle_id):
    if not _require_login():
        return redirect(url_for("auth_bp.login"))
    _ensure_default_types()
    _sync_units_from_users()

    cycle = db.session.get(ReportCycle, cycle_id)
    if not cycle:
        return "Not Found", 404
    unit = _current_user_report_unit()
    if not unit and _is_admin():
        scope_ids = list(_scope_unit_ids(cycle))
        if scope_ids:
            unit = db.session.get(ReportUnit, scope_ids[0])
        if not unit:
            unit = ReportUnit.query.filter_by(is_active=True).order_by(ReportUnit.name.asc()).first()
    if not _cycle_accessible(cycle, unit.id if unit else None, _is_admin()):
        return "Forbidden", 403

    user = db.session.get(User, session.get("uid"))
    instance = _get_cycle_instance(cycle, unit, user)
    template_version = db.session.get(ReportTemplateVersion, cycle.template_version_id)
    template = db.session.get(ReportTemplate, template_version.template_id)
    metadata = json.loads(template_version.metadata_json or "{}")
    workbook = load_workbook(template_version.source_path, data_only=False)
    latest_submission = _latest_submission(instance.id)
    existing_values = _submission_cell_values(latest_submission.id) if latest_submission else {}
    sheet_views = []
    for sheet_meta in metadata.get("sheets", []):
        ws = workbook[sheet_meta["sheet_name"]]
        lookup = {field.column_index: field.field_code for field in ReportTemplateField.query.filter_by(version_id=template_version.id, sheet_name=sheet_meta["sheet_name"]).all()}
        sheet_views.append({
            "sheet_name": sheet_meta["sheet_name"],
            "html": render_sheet_html(ws, editable_values=existing_values.get(sheet_meta["sheet_name"], {}), field_lookup=lookup, editable=not cycle.is_locked and cycle.status != "closed"),
            "field_count": len(sheet_meta.get("fields", [])),
            "input_count": len(sheet_meta.get("input_cells", [])),
        })

    return render_template(
        "report_cycle_form.html",
        cycle=cycle,
        template=template,
        template_version=template_version,
        instance=instance,
        sheet_views=sheet_views,
        latest_submission=latest_submission,
        current_unit=unit,
        is_admin=_is_admin(),
        editable=not cycle.is_locked and cycle.status != "closed",
    )


def _payload_from_request():
    payload = request.form.get("payload_json")
    if payload:
        try:
            return json.loads(payload)
        except Exception:
            return {}
    if request.is_json:
        return request.get_json(silent=True) or {}
    return {}


@reporting_bp.route("/reports/cycles/<int:cycle_id>/save", methods=["POST"])
def save_cycle(cycle_id):
    if not _require_login():
        return redirect(url_for("auth_bp.login"))
    cycle = db.session.get(ReportCycle, cycle_id)
    unit = _current_user_report_unit()
    if not cycle or not _cycle_accessible(cycle, unit.id if unit else None, _is_admin()):
        return "Forbidden", 403
    user = db.session.get(User, session.get("uid"))
    instance = _get_cycle_instance(cycle, unit, user)
    payload = _payload_from_request()
    submission, errors = _save_submission(instance, payload, final_submit=False)
    _audit("save_draft", "report_submission", submission.id, f"cycle={cycle.id}")
    flash("Đã lưu nháp báo cáo.", "success")
    return redirect(url_for("reporting_bp.cycle_workspace", cycle_id=cycle.id))


@reporting_bp.route("/reports/cycles/<int:cycle_id>/submit", methods=["POST"])
def submit_cycle(cycle_id):
    if not _require_login():
        return redirect(url_for("auth_bp.login"))
    cycle = db.session.get(ReportCycle, cycle_id)
    unit = _current_user_report_unit()
    if not cycle or not _cycle_accessible(cycle, unit.id if unit else None, _is_admin()):
        return "Forbidden", 403
    user = db.session.get(User, session.get("uid"))
    instance = _get_cycle_instance(cycle, unit, user)
    payload = _payload_from_request()
    submission, errors = _save_submission(instance, payload, final_submit=True)
    if errors:
        flash("Còn dữ liệu bắt buộc chưa hoàn tất, hệ thống đã giữ ở trạng thái nháp.", "warning")
        return redirect(url_for("reporting_bp.cycle_workspace", cycle_id=cycle.id))
    output_path = _export_submission(submission)
    submission.file_path = output_path
    db.session.commit()
    _audit("submit_report", "report_submission", submission.id, f"cycle={cycle.id}")
    flash("Đã gửi báo cáo.", "success")
    return redirect(url_for("reporting_bp.cycle_workspace", cycle_id=cycle.id))


@reporting_bp.route("/reports/submissions/<int:submission_id>/download")
def download_submission(submission_id):
    if not _require_login():
        return redirect(url_for("auth_bp.login"))
    submission = db.session.get(ReportSubmission, submission_id)
    if not submission:
        return "Not Found", 404
    if not submission.file_path or not os.path.exists(submission.file_path):
        submission.file_path = _export_submission(submission)
        db.session.commit()
    return send_file(submission.file_path, as_attachment=True, download_name=os.path.basename(submission.file_path))
