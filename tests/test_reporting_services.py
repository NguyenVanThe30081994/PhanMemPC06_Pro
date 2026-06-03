# -*- coding: utf-8 -*-
import unittest
from datetime import date
from types import SimpleNamespace

from reporting_services import (
    default_cycle_back_url,
    resolve_cycle_context,
    route_with_back,
    safe_back_url,
    workspace_route_values,
)


class ReportingServicesTests(unittest.TestCase):
    def test_workspace_route_values_and_back_helpers(self):
        cycle = SimpleNamespace(id=9)
        unit = SimpleNamespace(id=3)

        values = workspace_route_values(cycle, unit=unit, report_date=date(2026, 6, 3), can_manage_templates=True)
        url = route_with_back(
            "reporting_bp.cycle_workspace",
            cycle,
            lambda endpoint, **kwargs: f"{endpoint}:{kwargs}",
            back_url="/reports",
            unit=unit,
            report_date=date(2026, 6, 3),
            can_manage_templates=True,
        )

        self.assertEqual(values, {"cycle_id": 9, "unit_id": 3, "report_date": "2026-06-03"})
        self.assertEqual(safe_back_url("/reports?a=1"), "/reports?a=1")
        self.assertEqual(safe_back_url("https://x"), "")
        self.assertIn("back", url)

    def test_default_cycle_back_url_uses_admin_route_when_requested(self):
        cycle = SimpleNamespace(id=5)
        self.assertEqual(
            default_cycle_back_url(
                cycle,
                lambda endpoint, **kwargs: f"{endpoint}:{kwargs}",
                report_date=date(2026, 6, 3),
                is_admin=True,
            ),
            "reporting_bp.admin_cycle_detail:{'cycle_id': 5, 'report_date': '2026-06-03'}",
        )
        self.assertEqual(
            default_cycle_back_url(cycle, lambda endpoint, **kwargs: endpoint, is_admin=False),
            "reporting_bp.user_dashboard",
        )

    def test_resolve_cycle_context_builds_daily_locked_view(self):
        cycle = SimpleNamespace(id=1, template_version_id=10)
        unit = SimpleNamespace(id=7)
        user = SimpleNamespace(id=11)
        template_version = SimpleNamespace(id=10, template_id=22)
        template = SimpleNamespace(id=22)
        report_type = SimpleNamespace(code="daily")
        effective_state = {
            "report_date": date(2026, 6, 2),
            "latest_submission": "effective-sub",
            "history": ["effective-history"],
            "existing_values": {"x": 1},
            "daily_submissions": ["effective-daily"],
        }
        working_state = {
            "latest_submission": "working-sub",
            "history": ["working-history"],
            "existing_values": {"y": 2},
            "daily_submissions": ["working-daily"],
        }
        entry_state = {
            "latest_submission": "entry-sub",
            "history": ["entry-history"],
            "existing_values": {"z": 3},
        }

        context = resolve_cycle_context(
            cycle_id=1,
            prefer_all_units=False,
            can_manage_templates=False,
            request_unit_id="",
            request_report_date="2026-06-01",
            finalize_due_daily_cycles_fn=lambda cycle_id=None: None,
            get_cycle_fn=lambda cycle_id: cycle,
            resolve_cycle_unit_fn=lambda cycle: unit,
            cycle_accessible_fn=lambda cycle, unit_id, is_admin: True,
            get_user_fn=lambda: user,
            get_cycle_instance_fn=lambda cycle, unit, user: SimpleNamespace(id=33),
            get_template_version_fn=lambda template_version_id: template_version,
            get_template_fn=lambda template_id: template,
            report_type_fn=lambda cycle: report_type,
            is_cycle_view_locked_fn=lambda cycle: True,
            parse_date_fn=lambda raw_value: date(2026, 6, 1) if raw_value else None,
            effective_daily_cutoff_date_fn=lambda cycle, instance_id: date(2026, 6, 2),
            resolve_entry_submission_state_fn=lambda *args, **kwargs: entry_state,
            resolve_working_submission_state_fn=lambda *args, **kwargs: working_state,
            resolve_effective_instance_state_fn=lambda *args, **kwargs: effective_state,
        )

        self.assertEqual(context["cycle"], cycle)
        self.assertEqual(context["unit"], unit)
        self.assertEqual(context["user"], user)
        self.assertEqual(context["report_date"], date(2026, 6, 2))
        self.assertEqual(context["latest_submission"], "effective-sub")
        self.assertEqual(context["view_submission"], "effective-sub")
        self.assertEqual(context["working_values"], {"x": 1})
        self.assertTrue(context["view_locked"])

    def test_resolve_cycle_context_returns_none_for_inaccessible_cycle(self):
        context = resolve_cycle_context(
            cycle_id=1,
            prefer_all_units=False,
            can_manage_templates=False,
            request_unit_id="",
            request_report_date="",
            finalize_due_daily_cycles_fn=lambda cycle_id=None: None,
            get_cycle_fn=lambda cycle_id: SimpleNamespace(id=1, template_version_id=2),
            resolve_cycle_unit_fn=lambda cycle: SimpleNamespace(id=7),
            cycle_accessible_fn=lambda cycle, unit_id, is_admin: False,
            get_user_fn=lambda: None,
            get_cycle_instance_fn=lambda cycle, unit, user: None,
            get_template_version_fn=lambda template_version_id: None,
            get_template_fn=lambda template_id: None,
            report_type_fn=lambda cycle: None,
            is_cycle_view_locked_fn=lambda cycle: False,
            parse_date_fn=lambda raw_value: None,
            effective_daily_cutoff_date_fn=lambda cycle, instance_id: None,
            resolve_entry_submission_state_fn=lambda *args, **kwargs: {},
            resolve_working_submission_state_fn=lambda *args, **kwargs: {},
            resolve_effective_instance_state_fn=lambda *args, **kwargs: {},
        )
        self.assertIsNone(context)


if __name__ == "__main__":
    unittest.main()
