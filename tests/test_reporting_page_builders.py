# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from reporting_page_builders import (
    build_admin_reporting_dashboard_context,
    build_cycle_dashboard_maps,
    build_cycle_history_context,
    build_cycle_preview_sheets,
    build_cycle_workspace_sheet_views,
    build_user_reporting_dashboard_context,
)


class _Cell:
    def __init__(self, value):
        self.value = value


class _RowDimension:
    def __init__(self, hidden=False):
        self.hidden = hidden


class _Worksheet:
    def __init__(self, values=None, hidden_rows=None):
        self._values = values or {}
        self.row_dimensions = {
            index: _RowDimension(index in (hidden_rows or set()))
            for index in range(1, 20)
        }

    def __getitem__(self, coord):
        return _Cell(self._values.get(coord))


class ReportingPageBuildersTests(unittest.TestCase):
    def test_build_cycle_dashboard_maps_collects_all_maps(self):
        cycles = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        context = build_cycle_dashboard_maps(
            cycles,
            "2026-06-03",
            lambda cycle: f"type:{cycle.id}",
            lambda cycle, report_type=None, report_date=None: f"progress:{cycle.id}:{report_type}:{report_date}",
            lambda cycle, instance=None, report_type=None, report_date=None, progress=None: f"status:{cycle.id}:{progress}",
            lambda cycle, report_type=None: f"deadline:{cycle.id}:{report_type}",
            instance_map={1: "instance-1"},
        )

        self.assertEqual(context["cycle_report_types"][1], "type:1")
        self.assertEqual(context["cycle_progress_map"][2], "progress:2:type:2:2026-06-03")
        self.assertEqual(context["cycle_status_map"][1], "status:1:progress:1:type:1:2026-06-03")
        self.assertEqual(context["cycle_deadline_map"][2], "deadline:2:type:2")

    def test_build_cycle_workspace_sheet_views_filters_rows_and_builds_warning(self):
        workbook = {"Sheet1": _Worksheet(values={"B2": "x", "B3": "y"}, hidden_rows={4})}
        field = SimpleNamespace(
            is_visible=True,
            is_editable=True,
            column_letter="B",
            field_code="f1",
            levels=["Nhóm", "Trường"],
        )

        views = build_cycle_workspace_sheet_views(
            {"sheets": [{"sheet_name": "Sheet1", "fields": [1], "header_end_row": 1, "data_start_row": 2, "data_end_row": 4}]},
            workbook,
            1,
            report_admin_mode=False,
            unit=SimpleNamespace(name="Đội 1"),
            existing_values={},
            sheet_fields_getter=lambda version_id, sheet_name: [field],
            header_range_getter=lambda sheet_meta: (1, 1),
            input_row_indexes_getter=lambda sheet_meta: [2, 3, 4],
            sheet_has_unit_identity_fields_fn=lambda fields: True,
            row_matches_unit_fn=lambda ws, sheet_fields, existing_values, sheet_name, row_index, unit: row_index == 2,
            cell_display_value_fn=lambda value: str(value or ""),
            field_display_name_fn=lambda field: "Trường",
            field_levels_fn=lambda field: field.levels,
            row_context_label_fn=lambda ws, sheet_fields, existing_values, sheet_name, row_index: f"Dòng {row_index}",
        )

        self.assertEqual(len(views[0]["rows"]), 1)
        self.assertEqual(views[0]["rows"][0]["excel_row"], 2)
        self.assertEqual(views[0]["rows"][0]["inputs"][0]["field_path"], "Nhóm")

        warning_views = build_cycle_workspace_sheet_views(
            {"sheets": [{"sheet_name": "Sheet1", "fields": [1], "header_end_row": 1, "data_start_row": 2, "data_end_row": 3}]},
            workbook,
            1,
            report_admin_mode=False,
            unit=SimpleNamespace(name="Đội 1"),
            existing_values={},
            sheet_fields_getter=lambda version_id, sheet_name: [field],
            header_range_getter=lambda sheet_meta: (1, 1),
            input_row_indexes_getter=lambda sheet_meta: [3],
            sheet_has_unit_identity_fields_fn=lambda fields: True,
            row_matches_unit_fn=lambda *args, **kwargs: False,
            cell_display_value_fn=lambda value: str(value or ""),
            field_display_name_fn=lambda field: "Trường",
            field_levels_fn=lambda field: field.levels,
            row_context_label_fn=lambda *args, **kwargs: "Dòng",
        )
        self.assertIn("Đội 1", warning_views[0]["warning"])

    def test_build_cycle_preview_sheets_renders_html_payload(self):
        workbook = {"Sheet1": _Worksheet()}
        preview_sheets = build_cycle_preview_sheets(
            {"sheets": [{"sheet_name": "Sheet1", "start_column": "A", "end_column": "C", "header_end_row": 2, "data_end_row": 5}]},
            workbook,
            {"Sheet1": {"A2": "x"}},
            {"Sheet1": {"B2": "y"}},
            header_range_getter=lambda sheet_meta: (1, 2),
            column_index_from_string_fn=lambda value: {"A": 1, "C": 3}[value],
            preferred_sticky_column_fn=lambda sheet_meta, ws, sheet_values: 1,
            render_sheet_html_fn=lambda ws, **kwargs: f"html:{kwargs['min_col']}:{kwargs['max_col']}",
        )
        self.assertEqual(preview_sheets[0]["html"], "html:1:3")

    def test_dashboard_context_builders_keep_expected_fields(self):
        admin_context = build_admin_reporting_dashboard_context(
            templates=[1],
            versions=[2],
            cycles=[3],
            units=[4],
            report_types=[5],
            professional_units=[6],
            recent_submissions=[7],
            current_versions={8: 9},
            template_report_types={10: 11},
            cycle_status_map={1: "s"},
            cycle_progress_map={1: "p"},
            cycle_deadline_map={1: "d"},
            hero_stats={"total": 1},
            template_groups=["g"],
        )
        user_context = build_user_reporting_dashboard_context(
            user="u",
            unit="unit",
            instances=[SimpleNamespace(cycle_id=1)],
            latest_submission_map={1: "sub"},
            dashboard_maps={
                "cycle_report_types": {1: "t"},
                "cycle_progress_map": {1: "p"},
                "cycle_status_map": {1: "s"},
                "cycle_deadline_map": {1: "d"},
            },
            hero_stats={"total": 1},
            accessible_cycles=["c"],
            can_view_cycle_progress=True,
            is_admin=False,
            cycle_groups=["group"],
        )
        history_context = build_cycle_history_context(
            {
                "cycle": "cycle",
                "template": "template",
                "report_type": "rtype",
                "report_date": SimpleNamespace(strftime=lambda fmt: "03/06/2026"),
                "unit": "unit",
                "view_submission": "sub",
            },
            history_rows=["row"],
            is_admin=False,
            back_url="/reports",
        )

        self.assertEqual(admin_context["template_groups"], ["g"])
        self.assertEqual(user_context["instance_map"][1].cycle_id, 1)
        self.assertEqual(history_context["history_rows"], ["row"])


if __name__ == "__main__":
    unittest.main()
