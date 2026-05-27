# -*- coding: utf-8 -*-
import os
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import quote

from openpyxl import Workbook
from sqlalchemy import text
from app import app
from models import (
    ReportCycle,
    ReportInstance,
    ReportingPeriod,
    ReportTemplate,
    ReportTemplateField,
    ReportTemplateVersion,
    ReportType,
    ReportUnit,
    Task,
    TaskAssignment,
    TaskItem,
    TaskParticipant,
    TaskReportLink,
    TaskSubmission,
    User,
    db,
)
from routes.tasks import (
    _build_child_task_report_dashboard,
    _extract_submission_numeric_value,
    _query_task_scope,
    _sync_task_runtime_models,
    _task_runtime_bridge_needs_sync,
)
from utils import has_module_permission, normalize_permission_payload


class ProposalRuntimeTests(unittest.TestCase):
    def _login_admin_client(self):
        with app.app_context():
            user = User.query.filter_by(username='admin').first() or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test.")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
            sess['username'] = user.username
            sess['fullname'] = user.fullname
            sess['unit'] = user.unit_area or ''
            sess['unit_area'] = user.unit_area or ''
            sess['unit_area_ref'] = user.unit_area or ''
            sess['unit_key'] = user.unit_key or ''
            sess['role_id'] = user.role_id
            sess['must_change'] = False
            sess['is_admin'] = True
            sess['last_active'] = datetime.now().timestamp()
            sess['login_nonce'] = 'test-session-token'
        return client, user

    def _build_report_cycle_fixture(self, report_type_code="daily"):
        with app.app_context():
            report_type = ReportType.query.filter_by(code=report_type_code).first()
            if report_type is None:
                report_type = ReportType(
                    code=report_type_code,
                    name="Báo cáo ngày" if report_type_code == "daily" else "Báo cáo định kỳ",
                    frequency=report_type_code,
                    is_active=True,
                )
                db.session.add(report_type)
                db.session.flush()

            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
            unit = ReportUnit(
                code=f"test_unit_{now_token}",
                name=f"Đơn vị test {now_token}",
                source="test",
                is_active=True,
            )
            db.session.add(unit)
            db.session.flush()

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Sheet1"
            sheet["A1"] = "Đơn vị"
            sheet["B1"] = "Số liệu"
            sheet["A2"] = unit.name
            sheet["B2"] = 1

            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir="/private/tmp")
            handle.close()
            workbook.save(handle.name)

            metadata = {
                "sheets": [
                    {
                        "sheet_name": "Sheet1",
                        "order_index": 0,
                        "header_rows": 1,
                        "header_start_row": 1,
                        "header_end_row": 1,
                        "data_start_row": 2,
                        "data_end_row": 2,
                        "unit_start_row": 2,
                        "unit_end_row": 2,
                        "total_start_row": 2,
                        "total_end_row": 2,
                        "start_column": "A",
                        "end_column": "B",
                        "fields": [
                            {
                                "field_code": "so_lieu",
                                "field_name": "Số liệu",
                                "column_index": 2,
                                "column_letter": "B",
                                "data_type": "number",
                                "input_mode": "text",
                                "is_required": False,
                                "is_visible": True,
                                "is_editable": True,
                                "default_value": "",
                                "validation_rule": "",
                                "dictionary_source": "",
                                "formula_expression": "",
                                "aggregation_type": "",
                                "display_order": 1,
                                "path_code": "",
                            }
                        ],
                    }
                ]
            }

            template = ReportTemplate(
                code=f"test_template_{now_token}",
                name=f"Template test {now_token}",
                report_type_id=report_type.id,
                professional_unit="PC06",
                status="active",
            )
            db.session.add(template)
            db.session.flush()

            version = ReportTemplateVersion(
                template_id=template.id,
                version_no=1,
                source_filename=os.path.basename(handle.name),
                source_path=handle.name,
                metadata_json=json.dumps(metadata, ensure_ascii=False),
                is_current=True,
            )
            db.session.add(version)
            db.session.flush()

            db.session.add(
                ReportTemplateField(
                    version_id=version.id,
                    sheet_name="Sheet1",
                    field_code="so_lieu",
                    field_name="Số liệu",
                    display_name="Số liệu",
                    column_index=2,
                    column_letter="B",
                    data_type="number",
                    input_mode="text",
                    is_required=False,
                    is_visible=True,
                    is_editable=True,
                    default_value="",
                    validation_rule="",
                    dictionary_source="",
                    formula_expression="",
                    aggregation_type="",
                    display_order=1,
                    path_code="",
                )
            )

            cycle = ReportCycle(
                template_version_id=version.id,
                report_type_id=report_type.id,
                name=f"Cycle test {now_token}",
                open_at=datetime.now(),
                due_at=datetime.now() + timedelta(days=1),
                status="open",
                scope_json=json.dumps({"unit_ids": [unit.id], "mode": "targeted"}, ensure_ascii=False),
                is_locked=False,
            )
            db.session.add(cycle)
            db.session.commit()

            return {
                "cycle_id": cycle.id,
                "template_id": template.id,
                "version_id": version.id,
                "unit_id": unit.id,
                "report_type_id": report_type.id,
                "workbook_path": handle.name,
            }

    def _cleanup_report_cycle_fixture(self, fixture):
        with app.app_context():
            ReportInstance.query.filter_by(cycle_id=fixture["cycle_id"]).delete(synchronize_session=False)
            ReportingPeriod.query.filter_by(template_id=fixture["template_id"]).delete(synchronize_session=False)
            ReportCycle.query.filter_by(id=fixture["cycle_id"]).delete(synchronize_session=False)
            ReportTemplateField.query.filter_by(version_id=fixture["version_id"]).delete(synchronize_session=False)
            ReportTemplateVersion.query.filter_by(id=fixture["version_id"]).delete(synchronize_session=False)
            ReportTemplate.query.filter_by(id=fixture["template_id"]).delete(synchronize_session=False)
            ReportUnit.query.filter_by(id=fixture["unit_id"]).delete(synchronize_session=False)
            db.session.commit()
        workbook_path = fixture.get("workbook_path")
        if workbook_path and os.path.exists(workbook_path):
            os.remove(workbook_path)

    def _build_legacy_template_delete_fixture(self):
        with app.app_context():
            user = User.query.filter_by(username='admin').first() or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có user để test xóa template legacy bridge.")

            report_type = ReportType.query.filter_by(code="daily").first()
            if report_type is None:
                report_type = ReportType(
                    code="daily",
                    name="Báo cáo ngày",
                    frequency="daily",
                    is_active=True,
                )
                db.session.add(report_type)
                db.session.flush()

            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Sheet1"
            sheet["A1"] = "Đơn vị"
            sheet["B1"] = "Số liệu"
            sheet["A2"] = "Đơn vị legacy"
            sheet["B2"] = 7

            workbook_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir="/private/tmp")
            workbook_handle.close()
            workbook.save(workbook_handle.name)

            submission_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir="/private/tmp")
            submission_file.close()
            processed_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir="/private/tmp")
            processed_file.close()
            original_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir="/private/tmp")
            original_file.close()
            error_file = tempfile.NamedTemporaryFile(delete=False, suffix=".log", dir="/private/tmp")
            error_file.close()
            attachment_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir="/private/tmp")
            attachment_file.close()
            export_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir="/private/tmp")
            export_file.close()

            metadata = {
                "sheets": [
                    {
                        "sheet_name": "Sheet1",
                        "order_index": 0,
                        "header_rows": 1,
                        "header_start_row": 1,
                        "header_end_row": 1,
                        "data_start_row": 2,
                        "data_end_row": 2,
                        "unit_start_row": 2,
                        "unit_end_row": 2,
                        "total_start_row": 2,
                        "total_end_row": 2,
                        "start_column": "A",
                        "end_column": "B",
                        "fields": [],
                    }
                ]
            }

            template = ReportTemplate(
                code=f"legacy_delete_template_{now_token}",
                name=f"Legacy delete template {now_token}",
                report_type_id=report_type.id,
                professional_unit="PC06",
                status="active",
            )
            db.session.add(template)
            db.session.flush()

            version = ReportTemplateVersion(
                template_id=template.id,
                version_no=1,
                source_filename=os.path.basename(workbook_handle.name),
                source_path=workbook_handle.name,
                metadata_json=json.dumps(metadata, ensure_ascii=False),
                is_current=True,
            )
            db.session.add(version)
            db.session.flush()

            db.session.add(
                ReportTemplateField(
                    version_id=version.id,
                    sheet_name="Sheet1",
                    field_code="legacy_value",
                    field_name="Số liệu legacy",
                    display_name="Số liệu legacy",
                    column_index=2,
                    column_letter="B",
                    data_type="number",
                    input_mode="text",
                    is_required=False,
                    is_visible=True,
                    is_editable=True,
                    default_value="",
                    validation_rule="",
                    dictionary_source="",
                    formula_expression="",
                    aggregation_type="",
                    display_order=1,
                    path_code="",
                )
            )
            db.session.flush()

            created_at = datetime.now()
            db.session.execute(
                text(
                    """
                    INSERT OR REPLACE INTO form_template (
                        id, code, name, description, category, report_type, frequency,
                        deadline_rule, excel_template_blob, is_active, created_by, created_at,
                        updated_at, department
                    ) VALUES (
                        :id, :code, :name, :description, :category, :report_type, :frequency,
                        :deadline_rule, :excel_template_blob, :is_active, :created_by, :created_at,
                        :updated_at, :department
                    )
                    """
                ),
                {
                    "id": template.id,
                    "code": template.code,
                    "name": template.name,
                    "description": "fixture legacy form template",
                    "category": "fixture",
                    "report_type": "periodic",
                    "frequency": "daily",
                    "deadline_rule": "D+1",
                    "excel_template_blob": None,
                    "is_active": 1,
                    "created_by": user.id,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "department": "PC06",
                },
            )
            db.session.execute(
                text(
                    """
                    INSERT OR REPLACE INTO form_version (
                        id, template_id, version_number, metadata_json, is_published,
                        effective_from, effective_to, created_at, created_by
                    ) VALUES (
                        :id, :template_id, :version_number, :metadata_json, :is_published,
                        :effective_from, :effective_to, :created_at, :created_by
                    )
                    """
                ),
                {
                    "id": version.id,
                    "template_id": template.id,
                    "version_number": "v1.0",
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                    "is_published": 1,
                    "effective_from": None,
                    "effective_to": None,
                    "created_at": created_at,
                    "created_by": user.id,
                },
            )
            db.session.execute(
                text(
                    """
                    INSERT INTO form_field (
                        version_id, field_code, field_name, field_type, data_type, is_required,
                        is_readonly, is_calculated, calculation_formula, default_value,
                        options_json, validation_rules_json, display_order, section,
                        excel_cell_ref, help_text
                    ) VALUES (
                        :version_id, :field_code, :field_name, :field_type, :data_type, :is_required,
                        :is_readonly, :is_calculated, :calculation_formula, :default_value,
                        :options_json, :validation_rules_json, :display_order, :section,
                        :excel_cell_ref, :help_text
                    )
                    """
                ),
                {
                    "version_id": version.id,
                    "field_code": f"legacy_field_{now_token}",
                    "field_name": "Legacy field",
                    "field_type": "number",
                    "data_type": "number",
                    "is_required": 0,
                    "is_readonly": 0,
                    "is_calculated": 0,
                    "calculation_formula": "",
                    "default_value": "",
                    "options_json": "[]",
                    "validation_rules_json": "[]",
                    "display_order": 1,
                    "section": "main",
                    "excel_cell_ref": "B2",
                    "help_text": "",
                },
            )
            legacy_field_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            period_code = f"LEGACY_PERIOD_{now_token}"
            db.session.execute(
                text(
                    """
                    INSERT INTO reporting_period (
                        template_id, code, name, period_type, is_adhoc, start_date, end_date,
                        deadline, is_locked, created_at, created_by
                    ) VALUES (
                        :template_id, :code, :name, :period_type, :is_adhoc, :start_date, :end_date,
                        :deadline, :is_locked, :created_at, :created_by
                    )
                    """
                ),
                {
                    "template_id": template.id,
                    "code": period_code,
                    "name": f"Kỳ legacy {now_token}",
                    "period_type": "daily",
                    "is_adhoc": 0,
                    "start_date": date.today(),
                    "end_date": date.today(),
                    "deadline": created_at,
                    "is_locked": 0,
                    "created_at": created_at,
                    "created_by": user.id,
                },
            )
            period_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_instance (
                        template_id, version_id, period_id, user_id, org_unit, status,
                        submitted_at, locked_at, locked_by, created_at, updated_at
                    ) VALUES (
                        :template_id, :version_id, :period_id, :user_id, :org_unit, :status,
                        :submitted_at, :locked_at, :locked_by, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "template_id": template.id,
                    "version_id": version.id,
                    "period_id": period_id,
                    "user_id": user.id,
                    "org_unit": "Đơn vị legacy",
                    "status": "draft",
                    "submitted_at": None,
                    "locked_at": None,
                    "locked_by": None,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )
            instance_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_submission (
                        template_id, template_version_id, period_id, report_period, reporting_unit,
                        submitted_by, submitted_at, status, original_filename, original_file_path,
                        processed_file_path, error_file_path, total_rows, valid_rows, invalid_rows,
                        warning_count, metadata_json, created_at, updated_at, instance_id,
                        version_no, note, file_path
                    ) VALUES (
                        :template_id, :template_version_id, :period_id, :report_period, :reporting_unit,
                        :submitted_by, :submitted_at, :status, :original_filename, :original_file_path,
                        :processed_file_path, :error_file_path, :total_rows, :valid_rows, :invalid_rows,
                        :warning_count, :metadata_json, :created_at, :updated_at, :instance_id,
                        :version_no, :note, :file_path
                    )
                    """
                ),
                {
                    "template_id": template.id,
                    "template_version_id": version.id,
                    "period_id": period_id,
                    "report_period": date.today().strftime("%Y-%m-%d"),
                    "reporting_unit": "Đơn vị legacy",
                    "submitted_by": user.id,
                    "submitted_at": created_at,
                    "status": "submitted",
                    "original_filename": os.path.basename(original_file.name),
                    "original_file_path": original_file.name,
                    "processed_file_path": processed_file.name,
                    "error_file_path": error_file.name,
                    "total_rows": 1,
                    "valid_rows": 1,
                    "invalid_rows": 0,
                    "warning_count": 0,
                    "metadata_json": "{}",
                    "created_at": created_at,
                    "updated_at": created_at,
                    "instance_id": instance_id,
                    "version_no": 1,
                    "note": "legacy submission",
                    "file_path": submission_file.name,
                },
            )
            submission_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_submission_value (
                        submission_id, sheet_name, field_code, cell_address, value_text, value_number, value_json
                    ) VALUES (
                        :submission_id, :sheet_name, :field_code, :cell_address, :value_text, :value_number, :value_json
                    )
                    """
                ),
                {
                    "submission_id": submission_id,
                    "sheet_name": "Sheet1",
                    "field_code": "legacy_value",
                    "cell_address": "B2",
                    "value_text": "7",
                    "value_number": 7,
                    "value_json": "{}",
                },
            )
            submission_value_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_submission_cell (
                        submission_id, sheet_name, cell_address, raw_value, is_formula, formula_text
                    ) VALUES (
                        :submission_id, :sheet_name, :cell_address, :raw_value, :is_formula, :formula_text
                    )
                    """
                ),
                {
                    "submission_id": submission_id,
                    "sheet_name": "Sheet1",
                    "cell_address": "B2",
                    "raw_value": "7",
                    "is_formula": 0,
                    "formula_text": "",
                },
            )
            submission_cell_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_validation_log (
                        submission_id, sheet_name, field_code, cell_address, severity, message, created_at
                    ) VALUES (
                        :submission_id, :sheet_name, :field_code, :cell_address, :severity, :message, :created_at
                    )
                    """
                ),
                {
                    "submission_id": submission_id,
                    "sheet_name": "Sheet1",
                    "field_code": "legacy_value",
                    "cell_address": "B2",
                    "severity": "warning",
                    "message": "legacy validation log",
                    "created_at": created_at,
                },
            )
            validation_log_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_validation_error (
                        submission_id, sheet_name, section_code, row_index, column_index,
                        cell_address, field_code, error_code, error_message, severity
                    ) VALUES (
                        :submission_id, :sheet_name, :section_code, :row_index, :column_index,
                        :cell_address, :field_code, :error_code, :error_message, :severity
                    )
                    """
                ),
                {
                    "submission_id": submission_id,
                    "sheet_name": "Sheet1",
                    "section_code": "main",
                    "row_index": 2,
                    "column_index": 2,
                    "cell_address": "B2",
                    "field_code": "legacy_value",
                    "error_code": "LEGACY",
                    "error_message": "legacy validation error",
                    "severity": "warning",
                },
            )
            validation_error_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_workflow_history (
                        submission_id, from_status, to_status, action, comment, actor_id, acted_at
                    ) VALUES (
                        :submission_id, :from_status, :to_status, :action, :comment, :actor_id, :acted_at
                    )
                    """
                ),
                {
                    "submission_id": submission_id,
                    "from_status": "draft",
                    "to_status": "submitted",
                    "action": "submit",
                    "comment": "legacy workflow history",
                    "actor_id": user.id,
                    "acted_at": created_at,
                },
            )
            workflow_history_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_data_row (
                        submission_id, sheet_code, section_code, row_index, status, metadata_json
                    ) VALUES (
                        :submission_id, :sheet_code, :section_code, :row_index, :status, :metadata_json
                    )
                    """
                ),
                {
                    "submission_id": submission_id,
                    "sheet_code": "Sheet1",
                    "section_code": "main",
                    "row_index": 2,
                    "status": "valid",
                    "metadata_json": "{}",
                },
            )
            data_row_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_data_cell (
                        row_id, field_code, excel_address, raw_value, normalized_value, value_type, formula_text
                    ) VALUES (
                        :row_id, :field_code, :excel_address, :raw_value, :normalized_value, :value_type, :formula_text
                    )
                    """
                ),
                {
                    "row_id": data_row_id,
                    "field_code": "legacy_value",
                    "excel_address": "B2",
                    "raw_value": "7",
                    "normalized_value": "7",
                    "value_type": "number",
                    "formula_text": "",
                },
            )
            data_cell_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_field_value (
                        instance_id, field_code, value, value_type, row_index, created_at, updated_at
                    ) VALUES (
                        :instance_id, :field_code, :value, :value_type, :row_index, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "instance_id": instance_id,
                    "field_code": "legacy_value",
                    "value": "7",
                    "value_type": "number",
                    "row_index": 2,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )
            field_value_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_attachment (
                        instance_id, field_code, filename, file_path, file_size, mime_type, uploaded_by, uploaded_at
                    ) VALUES (
                        :instance_id, :field_code, :filename, :file_path, :file_size, :mime_type, :uploaded_by, :uploaded_at
                    )
                    """
                ),
                {
                    "instance_id": instance_id,
                    "field_code": "minh_chung",
                    "filename": os.path.basename(attachment_file.name),
                    "file_path": attachment_file.name,
                    "file_size": os.path.getsize(attachment_file.name),
                    "mime_type": "application/pdf",
                    "uploaded_by": user.id,
                    "uploaded_at": created_at,
                },
            )
            attachment_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            db.session.execute(
                text(
                    """
                    INSERT INTO report_export_job (
                        submission_id, status, output_path, error_message, created_at, finished_at
                    ) VALUES (
                        :submission_id, :status, :output_path, :error_message, :created_at, :finished_at
                    )
                    """
                ),
                {
                    "submission_id": submission_id,
                    "status": "done",
                    "output_path": export_file.name,
                    "error_message": "",
                    "created_at": created_at,
                    "finished_at": created_at,
                },
            )
            export_job_id = db.session.execute(text("SELECT last_insert_rowid()")).scalar()

            backup_dir = os.path.join(
                app.config["BACKUP_FOLDER"],
                "report_submissions",
                "cycle_0",
                f"instance_{instance_id}",
            )
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, f"submission_{submission_id}.json")
            with open(backup_path, "w", encoding="utf-8") as handle:
                json.dump({"submission_id": submission_id}, handle, ensure_ascii=False)

            db.session.commit()

            return {
                "template_id": template.id,
                "version_id": version.id,
                "legacy_field_id": legacy_field_id,
                "period_id": period_id,
                "instance_id": instance_id,
                "submission_id": submission_id,
                "submission_value_id": submission_value_id,
                "submission_cell_id": submission_cell_id,
                "validation_log_id": validation_log_id,
                "validation_error_id": validation_error_id,
                "workflow_history_id": workflow_history_id,
                "data_row_id": data_row_id,
                "data_cell_id": data_cell_id,
                "field_value_id": field_value_id,
                "attachment_id": attachment_id,
                "export_job_id": export_job_id,
                "period_code": period_code,
                "workbook_path": workbook_handle.name,
                "submission_file_path": submission_file.name,
                "processed_file_path": processed_file.name,
                "original_file_path": original_file.name,
                "error_file_path": error_file.name,
                "attachment_file_path": attachment_file.name,
                "export_file_path": export_file.name,
                "backup_path": backup_path,
            }

    def _cleanup_legacy_template_delete_fixture(self, fixture):
        if not fixture:
            return
        with app.app_context():
            for statement, params in [
                ("DELETE FROM report_data_cell WHERE id = :id", {"id": fixture["data_cell_id"]}),
                ("DELETE FROM report_data_row WHERE id = :id", {"id": fixture["data_row_id"]}),
                ("DELETE FROM report_submission_value WHERE id = :id", {"id": fixture["submission_value_id"]}),
                ("DELETE FROM report_submission_cell WHERE id = :id", {"id": fixture["submission_cell_id"]}),
                ("DELETE FROM report_validation_log WHERE id = :id", {"id": fixture["validation_log_id"]}),
                ("DELETE FROM report_validation_error WHERE id = :id", {"id": fixture["validation_error_id"]}),
                ("DELETE FROM report_workflow_history WHERE id = :id", {"id": fixture["workflow_history_id"]}),
                ("DELETE FROM report_export_job WHERE id = :id", {"id": fixture["export_job_id"]}),
                ("DELETE FROM report_attachment WHERE id = :id", {"id": fixture["attachment_id"]}),
                ("DELETE FROM report_field_value WHERE id = :id", {"id": fixture["field_value_id"]}),
                ("DELETE FROM report_submission WHERE id = :id", {"id": fixture["submission_id"]}),
                ("DELETE FROM report_instance WHERE id = :id", {"id": fixture["instance_id"]}),
                ("DELETE FROM reporting_period WHERE id = :id", {"id": fixture["period_id"]}),
                ("DELETE FROM form_field WHERE id = :id", {"id": fixture["legacy_field_id"]}),
                ("DELETE FROM form_version WHERE id = :id", {"id": fixture["version_id"]}),
                ("DELETE FROM form_template WHERE id = :id", {"id": fixture["template_id"]}),
            ]:
                db.session.execute(text(statement), params)
            ReportTemplateField.query.filter_by(version_id=fixture["version_id"]).delete(synchronize_session=False)
            ReportTemplateVersion.query.filter_by(id=fixture["version_id"]).delete(synchronize_session=False)
            ReportTemplate.query.filter_by(id=fixture["template_id"]).delete(synchronize_session=False)
            db.session.commit()

        for path in [
            fixture["workbook_path"],
            fixture["submission_file_path"],
            fixture["processed_file_path"],
            fixture["original_file_path"],
            fixture["error_file_path"],
            fixture["attachment_file_path"],
            fixture["export_file_path"],
            fixture["backup_path"],
        ]:
            if path and os.path.exists(path):
                os.remove(path)

    def test_permission_normalization_supports_view_process_exec(self):
        legacy_payload = {
            "p_task_lead": 1,
            "p_news_exec": 1,
            "p_contact_view": 1,
        }
        normalized = normalize_permission_payload(legacy_payload, is_admin=False, role_name="Cán bộ PC06")

        self.assertTrue(has_module_permission(normalized, "task", "view"))
        self.assertTrue(has_module_permission(normalized, "task", "process"))
        self.assertFalse(has_module_permission(normalized, "task", "exec"))

        self.assertTrue(has_module_permission(normalized, "news", "view"))
        self.assertTrue(has_module_permission(normalized, "news", "exec"))
        self.assertFalse(has_module_permission(normalized, "news", "process"))

        self.assertTrue(has_module_permission(normalized, "contact", "view"))
        self.assertFalse(has_module_permission(normalized, "contact", "process"))

    def test_task_runtime_backfill_creates_task_items_participants_submissions_and_links(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test runtime bridge.")

            template = ReportTemplate.query.order_by(ReportTemplate.id.asc()).first()
            linked_template_ids = [template.id] if template else []
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            task = Task(
                title=f"[TEST] runtime bridge {now_token}",
                content="Task phục vụ test backfill runtime",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                linked_report_templates_json=json.dumps(linked_template_ids, ensure_ascii=False) if linked_template_ids else None,
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            assignment = TaskAssignment(
                task_id=task.id,
                user_id=user.id,
                status="Đang thực hiện",
                report_payload_json=json.dumps({"narrative": "Đã cập nhật dữ liệu test."}, ensure_ascii=False),
                updated_at=datetime.now(),
            )
            db.session.add(assignment)
            child_task = Task(
                category=task.category,
                domain=task.domain,
                title=f"[TEST] child item {now_token}",
                content="Đầu mục thực thi test",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Trung bình",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                parent_task_id=task.id,
                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "meta": {
                            "kind": "simple_child_task",
                            "report_kind": "number",
                            "attachment_required": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
            )
            db.session.add(child_task)
            db.session.commit()

            try:
                task = db.session.get(Task, task.id)
                _sync_task_runtime_models(task)
                db.session.commit()

                task_item_count = TaskItem.query.filter_by(task_id=task.id).count()
                participant_count = _query_task_scope(TaskParticipant, task).filter(
                    TaskParticipant.participant_type == "executor",
                    TaskParticipant.is_active.is_(True),
                ).count()
                submission_count = _query_task_scope(TaskSubmission, task).count()
                report_link_count = _query_task_scope(TaskReportLink, task).count()

                self.assertEqual(task_item_count, 1)
                self.assertEqual(participant_count, 1)
                self.assertEqual(submission_count, 1)
                self.assertEqual(report_link_count, len(linked_template_ids))
                self.assertFalse(_task_runtime_bridge_needs_sync(task))
            finally:
                TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskSubmission.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskParticipant.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskReportLink.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                Task.query.filter_by(parent_task_id=task.id).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                Task.query.filter_by(id=task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_task_runtime_backfill_skips_assignment_without_user(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test runtime bridge.")
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            task = Task(
                title=f"[TEST] orphan assignment {now_token}",
                content="Task phục vụ test assignment lỗi",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            broken_assignment = TaskAssignment(
                task_id=task.id,
                user_id=None,
                status="Chưa tiếp nhận",
                updated_at=datetime.now(),
            )
            db.session.add(broken_assignment)
            db.session.commit()

            try:
                task = db.session.get(Task, task.id)
                _sync_task_runtime_models(task)
                db.session.commit()
                submission_count = _query_task_scope(TaskSubmission, task).count()
                self.assertEqual(submission_count, 0)
                self.assertFalse(_task_runtime_bridge_needs_sync(task))
            finally:
                TaskSubmission.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskParticipant.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskReportLink.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskItem.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=task.id).delete(synchronize_session=False)
                Task.query.filter_by(id=task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_task_list_stays_read_only_but_task_detail_lazy_repairs_runtime(self):
        client, user = self._login_admin_client()
        with app.app_context():
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
            task = Task(
                title=f"[TEST] lazy repair {now_token}",
                content="Task phục vụ test lazy repair runtime",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            assignment = TaskAssignment(
                task_id=task.id,
                user_id=user.id,
                status="Đang thực hiện",
                report_payload_json=json.dumps({"narrative": "Đã có báo cáo cũ."}, ensure_ascii=False),
                updated_at=datetime.now(),
            )
            db.session.add(assignment)
            db.session.commit()
            task_id = task.id

        try:
            list_response = client.get("/tasks")
            self.assertEqual(list_response.status_code, 200)
            with app.app_context():
                task = db.session.get(Task, task_id)
                self.assertEqual(_query_task_scope(TaskParticipant, task).count(), 0)
                self.assertEqual(_query_task_scope(TaskSubmission, task).count(), 0)
                self.assertTrue(_task_runtime_bridge_needs_sync(task))

            detail_response = client.get(f"/tasks/{task_id}")
            self.assertEqual(detail_response.status_code, 200)
            with app.app_context():
                task = db.session.get(Task, task_id)
                self.assertEqual(_query_task_scope(TaskParticipant, task).count(), 1)
                self.assertEqual(_query_task_scope(TaskSubmission, task).count(), 1)
                self.assertFalse(_task_runtime_bridge_needs_sync(task))
        finally:
            with app.app_context():
                TaskSubmission.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                TaskParticipant.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                TaskReportLink.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                TaskItem.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                TaskAssignment.query.filter_by(task_id=task_id).delete(synchronize_session=False)
                Task.query.filter_by(id=task_id).delete(synchronize_session=False)
                db.session.commit()

    def test_child_task_report_dashboard_classifies_progress_and_quality(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test dashboard task con.")
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            parent_task = Task(
                title=f"[TEST] child dashboard {now_token}",
                content="Task cha phục vụ test dashboard",
                deadline=datetime.now().date() + timedelta(days=3),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                created_at=datetime.now(),
            )
            db.session.add(parent_task)
            db.session.commit()

            child_specs = [
                ("Đầu việc 1", datetime.now().date() + timedelta(days=1), "Hoàn thành", {"narrative": "Đã báo cáo"}, datetime.now()),
                ("Đầu việc 2", datetime.now().date() - timedelta(days=1), "Đang thực hiện", None, datetime.now()),
                ("Đầu việc 3", datetime.now().date() + timedelta(days=2), "Chưa tiếp nhận", None, datetime.now()),
            ]
            child_ids = []
            try:
                for title, deadline, status, payload, updated_at in child_specs:
                    child_task = Task(
                        title=f"[TEST] {title} {now_token}",
                        content="Task con phục vụ test dashboard",
                        deadline=deadline,
                        author_id=user.id,
                        author_name=user.fullname,
                        priority="Trung bình",
                        task_type="Công việc thường xuyên",
                        initial_status=status,
                        parent_task_id=parent_task.id,
                        created_at=datetime.now(),
                    )
                    db.session.add(child_task)
                    db.session.flush()
                    assignment = TaskAssignment(
                        task_id=child_task.id,
                        user_id=user.id,
                        status=status,
                        report_payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
                        updated_at=updated_at,
                    )
                    db.session.add(assignment)
                    child_ids.append(child_task.id)
                db.session.commit()

                child_tasks = Task.query.filter(Task.id.in_(child_ids)).order_by(Task.id.asc()).all()
                dashboard = _build_child_task_report_dashboard(child_tasks)

                self.assertEqual(dashboard["total_units"], 1)
                self.assertEqual(dashboard["total_child_tasks"], 3)
                self.assertEqual(dashboard["total_overdue_tasks"], 1)
                self.assertEqual(dashboard["progress_groups"][1]["count"], 1)
                self.assertEqual(dashboard["quality_groups"][1]["count"], 1)

                unit_row = dashboard["unit_rows"][0]
                self.assertEqual(unit_row["progress_code"], "reporting_in_progress")
                self.assertEqual(unit_row["quality_code"], "partial_overdue")
                self.assertEqual(unit_row["child_task_count"], 3)
                self.assertEqual(unit_row["missing_count"], 2)
                self.assertEqual(unit_row["overdue_count"], 1)
            finally:
                TaskAssignment.query.filter(TaskAssignment.task_id.in_(child_ids)).delete(synchronize_session=False)
                Task.query.filter(Task.id.in_(child_ids)).delete(synchronize_session=False)
                Task.query.filter_by(id=parent_task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_numeric_submission_extractor_returns_none_for_blank_value(self):
        with app.app_context():
            user = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            self.assertIsNotNone(user, "Cần có ít nhất một user active để test numeric extractor.")
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

            task = Task(
                title=f"[TEST] numeric blank {now_token}",
                content="Task phục vụ test payload số rỗng",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Đang thực hiện",
                report_schema_json=json.dumps(
                    {
                        "enabled": True,
                        "meta": {
                            "kind": "simple_child_task",
                            "report_kind": "number",
                            "attachment_required": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
            )
            db.session.add(task)
            db.session.commit()

            try:
                payload = {"values": {"child_task_number": None}}
                self.assertIsNone(_extract_submission_numeric_value(task, payload))
            finally:
                Task.query.filter_by(id=task.id).delete(synchronize_session=False)
                db.session.commit()

    def test_delete_child_task_redirects_back_to_parent_detail(self):
        client, user = self._login_admin_client()
        with app.app_context():
            now_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
            parent_task = Task(
                title=f"[TEST] parent redirect {now_token}",
                content="Task cha phục vụ test redirect",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                created_at=datetime.now(),
            )
            db.session.add(parent_task)
            db.session.commit()

            child_task = Task(
                title=f"[TEST] child redirect {now_token}",
                content="Task con phục vụ test redirect",
                deadline=date.today(),
                author_id=user.id,
                author_name=user.fullname,
                priority="Cao",
                task_type="Công việc thường xuyên",
                initial_status="Chưa tiếp nhận",
                parent_task_id=parent_task.id,
                created_at=datetime.now(),
            )
            db.session.add(child_task)
            db.session.commit()
            parent_id = parent_task.id
            child_id = child_task.id

        try:
            response = client.post(f"/tasks/{child_id}/delete", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers.get("Location", "").endswith(f"/tasks/{parent_id}"))
        finally:
            with app.app_context():
                Task.query.filter_by(parent_task_id=parent_id).delete(synchronize_session=False)
                Task.query.filter_by(id=parent_id).delete(synchronize_session=False)
                db.session.commit()

    def test_report_workspace_preview_and_history_preserve_workspace_return_url(self):
        client, _user = self._login_admin_client()
        fixture = self._build_report_cycle_fixture(report_type_code="daily")
        report_date = date.today().strftime("%Y-%m-%d")
        workspace_url = f"/reports/cycles/{fixture['cycle_id']}?unit_id={fixture['unit_id']}&report_date={report_date}"
        encoded_back = quote(workspace_url, safe="/")

        try:
            response = client.get(workspace_url)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn(
                f"/reports/cycles/{fixture['cycle_id']}/view?unit_id={fixture['unit_id']}&amp;report_date={report_date}&amp;back=/reports/cycles/{fixture['cycle_id']}",
                html,
            )
            self.assertIn(
                f"/reports/cycles/{fixture['cycle_id']}/history?unit_id={fixture['unit_id']}&amp;report_date={report_date}&amp;back=/reports/cycles/{fixture['cycle_id']}",
                html,
            )
            self.assertIn(f"unit_id%3D{fixture['unit_id']}%26report_date%3D{report_date}", html)
        finally:
            self._cleanup_report_cycle_fixture(fixture)

    def test_report_preview_and_history_back_button_return_to_workspace(self):
        client, _user = self._login_admin_client()
        fixture = self._build_report_cycle_fixture(report_type_code="daily")
        report_date = date.today().strftime("%Y-%m-%d")
        workspace_url = f"/reports/cycles/{fixture['cycle_id']}?unit_id={fixture['unit_id']}&report_date={report_date}"
        encoded_back = quote(workspace_url, safe="/")
        escaped_workspace_url = escape(workspace_url, quote=True)

        try:
            preview_response = client.get(
                f"/reports/cycles/{fixture['cycle_id']}/view?unit_id={fixture['unit_id']}&report_date={report_date}&back={encoded_back}"
            )
            self.assertEqual(preview_response.status_code, 200)
            self.assertIn(f'href="{escaped_workspace_url}"', preview_response.get_data(as_text=True))

            history_response = client.get(
                f"/reports/cycles/{fixture['cycle_id']}/history?unit_id={fixture['unit_id']}&report_date={report_date}&back={encoded_back}"
            )
            self.assertEqual(history_response.status_code, 200)
            self.assertIn(f'href="{escaped_workspace_url}"', history_response.get_data(as_text=True))
        finally:
            self._cleanup_report_cycle_fixture(fixture)

    def test_session_timeout_uses_configured_lifetime_and_renders_session_scoped_activity_key(self):
        client, user = self._login_admin_client()
        with client.session_transaction() as sess:
            sess['last_active'] = datetime.now().timestamp() - 1900
            sess['login_nonce'] = 'scoped-activity-key'

        response = client.get("/tasks")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(f'const SESSION_MARKER = "{user.id}:scoped-activity-key";', html)
        self.assertIn("pc06_last_activity:${SESSION_MARKER}", html)
        self.assertNotIn("const SYNC_KEY = 'pc06_last_activity';", html)

    def test_delete_template_cleans_legacy_bridge_rows_before_removing_report_versions(self):
        client, _user = self._login_admin_client()
        fixture = self._build_legacy_template_delete_fixture()

        try:
            response = client.post(
                f"/admin/reports/templates/{fixture['template_id']}/delete",
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)

            with app.app_context():
                self.assertIsNone(db.session.get(ReportTemplate, fixture["template_id"]))
                self.assertIsNone(db.session.get(ReportTemplateVersion, fixture["version_id"]))

                for table_name, row_id in [
                    ("form_template", fixture["template_id"]),
                    ("form_version", fixture["version_id"]),
                    ("form_field", fixture["legacy_field_id"]),
                    ("reporting_period", fixture["period_id"]),
                    ("report_instance", fixture["instance_id"]),
                    ("report_submission", fixture["submission_id"]),
                    ("report_submission_value", fixture["submission_value_id"]),
                    ("report_submission_cell", fixture["submission_cell_id"]),
                    ("report_validation_log", fixture["validation_log_id"]),
                    ("report_validation_error", fixture["validation_error_id"]),
                    ("report_workflow_history", fixture["workflow_history_id"]),
                    ("report_data_row", fixture["data_row_id"]),
                    ("report_data_cell", fixture["data_cell_id"]),
                    ("report_field_value", fixture["field_value_id"]),
                    ("report_attachment", fixture["attachment_id"]),
                    ("report_export_job", fixture["export_job_id"]),
                ]:
                    remaining = db.session.execute(
                        text(f"SELECT COUNT(*) FROM {table_name} WHERE id = :row_id"),
                        {"row_id": row_id},
                    ).scalar()
                    self.assertEqual(remaining, 0, f"{table_name} vẫn còn bản ghi {row_id}")

            for path in [
                fixture["workbook_path"],
                fixture["submission_file_path"],
                fixture["processed_file_path"],
                fixture["original_file_path"],
                fixture["error_file_path"],
                fixture["attachment_file_path"],
                fixture["export_file_path"],
                fixture["backup_path"],
            ]:
                self.assertFalse(os.path.exists(path), f"File chưa được dọn: {path}")
        finally:
            self._cleanup_legacy_template_delete_fixture(fixture)


if __name__ == "__main__":
    unittest.main()
