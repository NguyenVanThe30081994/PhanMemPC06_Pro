# -*- coding: utf-8 -*-
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from task_page_builders import (
    build_task_detail_page_context,
    build_task_list_page_context,
    prepare_task_workspace_record,
    task_visible_for_user,
)


class TaskPageBuildersTests(unittest.TestCase):
    def test_task_visible_for_user_accepts_any_relevant_role(self):
        task = SimpleNamespace(author_id=10)
        self.assertTrue(task_visible_for_user(task, 99, is_executor=True))
        self.assertTrue(task_visible_for_user(task, 99, is_manager=True))
        self.assertTrue(task_visible_for_user(task, 99, is_viewer=True))
        self.assertFalse(task_visible_for_user(task, 99))

    def test_prepare_task_workspace_record_applies_workspace_attrs(self):
        task = SimpleNamespace(author_id=1, deadline=date(2026, 6, 5))

        def build_summary(_task, _uid):
            return {
                "progress_percent": 50,
                "total_assignments": 2,
                "submitted_assignments": 1,
                "in_progress_assignments": 0,
                "current_assignment": SimpleNamespace(status="assigned"),
            }

        prepared = prepare_task_workspace_record(
            task,
            current_uid=2,
            is_lead=False,
            build_summary_fn=build_summary,
            task_mode_fn=lambda _task: "FILE",
            task_mode_label_fn=lambda mode: f"label:{mode}",
            task_mode_description_fn=lambda mode: f"desc:{mode}",
            task_assignment_status_label_fn=lambda status: f"status:{status}",
            can_edit_task_fn=lambda _task: True,
            can_delete_task_fn=lambda _task, is_lead=False: is_lead,
            task_assignment_display_status_fn=lambda status: f"display:{status}",
            build_workspace_attrs_fn=lambda _task, _summary, _uid, status_text, today=None: {
                "workspace_role": "my",
                "workspace_status_text": status_text,
                "workspace_needs_attention": True,
                "is_complete": False,
            },
            today=date(2026, 6, 3),
        )

        self.assertEqual(prepared.task_mode, "FILE")
        self.assertEqual(prepared.task_mode_label, "label:FILE")
        self.assertEqual(prepared.current_user_status_label, "status:assigned")
        self.assertEqual(prepared.workspace_status_text, "display:assigned")
        self.assertTrue(prepared.can_edit)
        self.assertFalse(prepared.can_delete)

    def test_build_task_list_page_context_sorts_and_groups_tasks(self):
        soon = datetime(2026, 6, 3, 9, 0, 0)
        late = datetime(2026, 6, 2, 9, 0, 0)
        task_a = SimpleNamespace(
            task_mode="FILE",
            workspace_role="watch",
            workspace_needs_attention=False,
            is_overdue=False,
            deadline=None,
            updated_at=late,
            created_at=late,
            is_complete=False,
        )
        task_b = SimpleNamespace(
            task_mode="OUTLINE",
            workspace_role="my",
            workspace_needs_attention=True,
            is_overdue=True,
            deadline=date(2026, 6, 3),
            updated_at=soon,
            created_at=soon,
            is_complete=False,
        )

        context = build_task_list_page_context([task_a, task_b], "FILE")

        self.assertEqual(context["tasks"][0], task_b)
        self.assertEqual(context["attention_tasks"], [task_b])
        self.assertEqual(context["my_tasks"], [task_b])
        self.assertEqual(context["watch_tasks"], [task_a])
        self.assertEqual(context["stats"]["outline"], 1)

    def test_build_task_detail_page_context_extracts_my_assignments(self):
        today = date(2026, 6, 3)
        task = SimpleNamespace(deadline=today + timedelta(days=1))
        assignment = SimpleNamespace(user_id=7, status="assigned")
        submission = SimpleNamespace(payload_json='{"a": 1}')

        context = build_task_detail_page_context(
            task,
            current_uid=7,
            mode="FORM",
            can_manage_task_view=False,
            is_executor=True,
            build_summary_fn=lambda _task, _uid: {
                "progress_percent": 0,
                "total_assignments": 1,
                "submitted_assignments": 0,
                "in_progress_assignments": 0,
            },
            parse_outline_rows_fn=lambda _task, _uid: [],
            build_outline_groups_fn=lambda _task, _uid: [],
            build_file_rows_fn=lambda _task, _uid: [],
            build_form_rows_fn=lambda _task, _uid: (
                ["field1"],
                [{"assignment": assignment, "submission": submission, "payload": {"a": 1}, "is_current_user": True}],
            ),
            build_form_field_views_fn=lambda _task: ["view1"],
            build_task_detail_context_fn=lambda _task, summary, mode, can_manage_task_view, is_executor, **kwargs: {
                "progress_percent": summary["progress_percent"],
                "is_overdue": False,
                "default_tab": "form-submit",
            },
        )

        self.assertEqual(context["form_fields"], ["field1"])
        self.assertEqual(context["my_form_assignment"], assignment)
        self.assertEqual(context["my_form_submission"], submission)
        self.assertEqual(context["my_form_payload"], {"a": 1})
        self.assertEqual(context["detail_context"]["default_tab"], "form-submit")


if __name__ == "__main__":
    unittest.main()
