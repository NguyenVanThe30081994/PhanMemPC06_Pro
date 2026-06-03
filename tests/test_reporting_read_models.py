# -*- coding: utf-8 -*-
import unittest
from datetime import date, datetime
from types import SimpleNamespace

from reporting_read_models import (
    cycle_view_export_context,
    history_rows_for_submissions,
    resolve_effective_instance_state,
    resolve_entry_submission_state,
    resolve_working_submission_state,
    submission_timeliness,
)


class ReportingReadModelsTests(unittest.TestCase):
    def test_submission_timeliness_handles_daily_and_deadline(self):
        cycle = SimpleNamespace(open_at=datetime(2026, 6, 3, 8, 0), created_at=datetime(2026, 6, 3, 7, 0), due_at=datetime(2026, 6, 4, 10, 0))
        submission = SimpleNamespace(submitted_at=datetime(2026, 6, 3, 9, 0), created_at=datetime(2026, 6, 3, 8, 30))

        self.assertEqual(
            submission_timeliness(cycle, submission, report_type=SimpleNamespace(code="daily"), business_date_getter=lambda _submission: date(2026, 6, 3)),
            "Báo cáo ngày 03/06/2026",
        )
        self.assertEqual(
            submission_timeliness(cycle, submission, report_type=SimpleNamespace(code="monthly"), business_date_getter=lambda _submission: None),
            "Đúng hạn",
        )

    def test_resolve_working_and_entry_submission_state(self):
        instance = SimpleNamespace(id=1)
        template_version = SimpleNamespace(id=2)
        daily_sub = [SimpleNamespace(id=11), SimpleNamespace(id=12)]

        working = resolve_working_submission_state(
            instance,
            template_version,
            report_type=SimpleNamespace(code="daily"),
            report_date=date(2026, 6, 3),
            daily_snapshot_submissions_through_date_fn=lambda instance_id, report_date: daily_sub,
            submission_history_through_date_fn=lambda instance_id, report_date: ["h1"],
            effective_daily_cell_values_fn=lambda submissions, template_version_id: {"Sheet1": {"A1": "x"}},
            latest_submission_fn=lambda instance_id: None,
            submission_history_fn=lambda instance_id: [],
            submission_cell_values_fn=lambda submission_id: {},
        )
        entry = resolve_entry_submission_state(
            instance,
            template_version,
            report_type=SimpleNamespace(code="daily"),
            report_date=date(2026, 6, 3),
            latest_submission_for_date_fn=lambda instance_id, report_date: SimpleNamespace(id=13),
            submission_history_fn=lambda instance_id, report_date=None: ["h2"],
            latest_submission_fn=lambda instance_id: None,
            submission_cell_values_fn=lambda submission_id: {"Sheet1": {"A1": "y"}},
        )

        self.assertEqual(working["latest_submission"].id, 12)
        self.assertEqual(working["existing_values"], {"Sheet1": {"A1": "x"}})
        self.assertEqual(entry["latest_submission"].id, 13)
        self.assertEqual(entry["existing_values"], {"Sheet1": {"A1": "y"}})

    def test_resolve_effective_instance_state_sets_mode(self):
        state = resolve_effective_instance_state(
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            SimpleNamespace(id=3),
            report_type=SimpleNamespace(code="daily"),
            effective_daily_cutoff_date_fn=lambda cycle, instance_id: date(2026, 6, 2),
            resolve_working_submission_state_fn=lambda instance, template_version, report_type=None, report_date=None: {
                "latest_submission": "sub",
                "history": [],
                "existing_values": {},
                "daily_submissions": [],
            },
        )
        self.assertEqual(state["mode"], "daily_cumulative")
        self.assertEqual(state["report_date"], date(2026, 6, 2))

    def test_cycle_view_export_context_supports_admin_all_units(self):
        context = {
            "cycle": SimpleNamespace(id=4),
            "template_version": SimpleNamespace(id=5),
            "report_type": SimpleNamespace(code="daily"),
            "report_date": date(2026, 6, 3),
            "unit": SimpleNamespace(name="Đội 1"),
            "view_submission": None,
            "working_values": {},
        }
        export_context = cycle_view_export_context(
            context,
            report_admin_mode=True,
            request_unit_id="",
            exportable=True,
            list_cycle_instances_fn=lambda cycle_id: [SimpleNamespace(id=1)],
            daily_snapshot_submissions_through_date_fn=lambda instance_id, report_date: [SimpleNamespace(id=10, submitted_at=datetime(2026, 6, 3, 9, 0), created_at=datetime(2026, 6, 3, 8, 0))],
            effective_daily_cell_values_fn=lambda submissions, template_version_id: {"Sheet1": {"A1": "x"}},
            latest_submission_fn=lambda instance_id: None,
            merged_submission_cell_values_fn=lambda submissions: {},
            normalize_code_fn=lambda value: value.lower(),
        )
        self.assertTrue(export_context["admin_all_units"])
        self.assertEqual(export_context["scope_label"], "toan_bo_don_vi")

    def test_history_rows_for_submissions_enriches_actor_and_unit(self):
        submission = SimpleNamespace(id=1, submitted_by=9, instance_id=7, submitted_at=datetime(2026, 6, 3, 9, 0), created_at=datetime(2026, 6, 3, 8, 0))
        rows = history_rows_for_submissions(
            [submission],
            SimpleNamespace(id=4, source_path="/tmp/x.xlsx"),
            SimpleNamespace(code="monthly"),
            include_unit=True,
            include_actor=True,
            cycle=SimpleNamespace(due_at=None),
            load_workbook_fn=lambda path: "workbook",
            load_fields_fn=lambda version_id: [SimpleNamespace(sheet_name="Sheet1", field_code="f1")],
            load_users_fn=lambda user_ids: [SimpleNamespace(id=9, fullname="A")],
            load_instances_fn=lambda instance_ids: [SimpleNamespace(id=7, report_unit_id=3)],
            load_units_fn=lambda unit_ids: [SimpleNamespace(id=3, name="Đội 1")],
            build_submission_summary_fn=lambda submission, template_version, workbook=None, field_lookup=None, sheet_fields=None: {"text": "abc", "count": 1},
            submission_status_label_fn=lambda submission: "Đã gửi",
            submission_timeliness_fn=lambda cycle, submission, report_type=None: "Đúng hạn",
        )
        self.assertEqual(rows[0]["actor"].fullname, "A")
        self.assertEqual(rows[0]["unit"].name, "Đội 1")
        self.assertEqual(rows[0]["content_text"], "abc")


if __name__ == "__main__":
    unittest.main()
