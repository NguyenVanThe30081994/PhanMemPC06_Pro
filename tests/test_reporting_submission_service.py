# -*- coding: utf-8 -*-
import unittest
from datetime import date
from types import SimpleNamespace

from reporting_submission_service import (
    export_submission,
    payload_from_request,
    save_submission,
    submission_error_message,
)


class _FakeRequest:
    def __init__(self, payload_json=None, is_json=False, json_payload=None):
        self.form = {"payload_json": payload_json} if payload_json is not None else {}
        self.is_json = is_json
        self._json_payload = json_payload

    def get_json(self, silent=True):
        return self._json_payload


class ReportingSubmissionServiceTests(unittest.TestCase):
    def test_payload_from_request_and_error_message(self):
        self.assertEqual(payload_from_request(_FakeRequest(payload_json='{"a":1}')), {"a": 1})
        self.assertEqual(payload_from_request(_FakeRequest(is_json=True, json_payload={"b": 2})), {"b": 2})
        self.assertEqual(submission_error_message([("Sheet1", "Field1", "Lỗi")], "fallback"), "Lỗi")

    def test_save_submission_handles_required_field_errors(self):
        added = []
        commits = []
        flushes = []
        submission_holder = {}

        def make_submission_fn(**kwargs):
            obj = SimpleNamespace(id=101, **kwargs)
            submission_holder["submission"] = obj
            return obj

        submission, errors = save_submission(
            instance=SimpleNamespace(id=1, cycle_id=2, report_unit_id=3, assigned_user_id=9, user_id=9, status="draft"),
            payload={"note": "abc", "sheets": {"Sheet1": {"A1": ""}}},
            final_submit=True,
            report_date=None,
            get_cycle_fn=lambda cycle_id: SimpleNamespace(id=2, template_version_id=4, name="Cycle"),
            get_template_version_fn=lambda template_version_id: SimpleNamespace(id=4, template_id=5, metadata_json='{"sheets":[{"sheet_name":"Sheet1"}]}', source_filename="src.xlsx", source_path="/tmp/src.xlsx"),
            report_type_fn=lambda cycle: SimpleNamespace(code="monthly"),
            ensure_reporting_period_fn=lambda cycle, report_type=None: SimpleNamespace(id=6),
            get_report_unit_fn=lambda report_unit_id: SimpleNamespace(id=3, name="Đội 1"),
            normalize_sheet_values_fn=lambda values: values,
            resolve_daily_submission_date_fn=lambda cycle, report_date=None, instance_id=None: date(2026, 6, 3),
            has_later_daily_submission_fn=lambda instance_id, report_date: False,
            daily_snapshot_submissions_through_date_fn=lambda instance_id, report_date: [],
            effective_daily_cell_values_fn=lambda submissions, template_version_id: {},
            merge_sheet_values_fn=lambda base_values, payload_sheets: payload_sheets,
            make_submission_fn=make_submission_fn,
            add_fn=lambda obj: added.append(obj),
            flush_fn=lambda: flushes.append(True),
            count_submissions_fn=lambda instance_id: 0,
            load_sheet_fields_fn=lambda version_id, sheet_name: [SimpleNamespace(column_index=1, field_code="f1", data_type="text", is_required=True)],
            column_index_from_string_fn=lambda letters: 1,
            make_submission_cell_fn=lambda **kwargs: SimpleNamespace(**kwargs),
            make_submission_value_fn=lambda **kwargs: SimpleNamespace(**kwargs),
            field_display_name_fn=lambda field: "Trường 1",
            make_validation_log_fn=lambda **kwargs: SimpleNamespace(**kwargs),
            commit_fn=lambda: commits.append(True),
            export_submission_fn=lambda submission, values=None, commit=False: "/tmp/out.xlsx",
            write_submission_backup_fn=lambda submission, stored_values: None,
            rollback_fn=lambda: None,
            logger=None,
            current_session_uid=9,
        )

        self.assertIsNotNone(submission)
        self.assertTrue(errors)
        self.assertEqual(submission.status, "draft")
        self.assertGreaterEqual(len(commits), 1)
        self.assertTrue(flushes)

    def test_export_submission_builds_output_path_and_job(self):
        added = []
        commits = []
        submission = SimpleNamespace(id=11, instance_id=8, processed_file_path="")

        output_path = export_submission(
            submission,
            values={"Sheet1": {"A1": "x"}},
            commit=True,
            get_instance_fn=lambda instance_id: SimpleNamespace(id=8, cycle_id=7),
            get_cycle_fn=lambda cycle_id: SimpleNamespace(id=7, template_version_id=6),
            get_version_fn=lambda template_version_id: SimpleNamespace(template_id=5, source_path="/tmp/src.xlsx"),
            safe_filename_fn=lambda value: value,
            report_export_folder="/exports",
            normalize_sheet_values_fn=lambda values: values,
            submission_cell_values_fn=lambda submission_id: {},
            write_workbook_copy_fn=lambda source_path, output_path, values: None,
            make_report_export_job_fn=lambda **kwargs: SimpleNamespace(**kwargs),
            add_fn=lambda obj: added.append(obj),
            commit_fn=lambda: commits.append(True),
            os_path_join_fn=lambda root, name: f"{root}/{name}",
            os_path_basename_fn=lambda path: path.rsplit("/", 1)[-1],
        )

        self.assertEqual(output_path, "/exports/5_cycle_7_submission_11.xlsx")
        self.assertEqual(submission.processed_file_path, output_path)
        self.assertEqual(len(added), 1)
        self.assertEqual(len(commits), 1)


if __name__ == "__main__":
    unittest.main()
