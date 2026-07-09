# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from task_read_models import (
    build_file_task_rows,
    build_form_task_rows,
    build_outline_group_rows,
    form_field_options,
    normalize_task_form_field_type,
    outline_group_identity,
    task_form_field_views,
    task_form_submission_payload,
    task_form_value_is_empty,
)


class TaskReadModelsTests(unittest.TestCase):
    def test_outline_group_identity_supports_unit_and_empty_assignments(self):
        unit_assignment = SimpleNamespace(assignee_type="unit", user=SimpleNamespace(unit_name="Đội 1"))

        identity = outline_group_identity(
            [unit_assignment],
            lambda user: getattr(user, "unit_name", ""),
            fallback_index=2,
        )
        empty_identity = outline_group_identity([], lambda _user: "", fallback_index=2)

        self.assertEqual(identity["mode"], "unit")
        self.assertEqual(identity["label"], "Đội 1")
        self.assertEqual(empty_identity["key"], "ungrouped:2")

    def test_build_outline_group_rows_aggregates_counts_and_sorts_rows(self):
        row_a = {
            "assignments": [SimpleNamespace(assignee_type="user", user_id=1, user=SimpleNamespace(fullname="B"))],
            "item": SimpleNamespace(sort_order=2, id=10),
            "total_count": 1,
            "submitted_count": 1,
            "my_assignment": None,
        }
        row_b = {
            "assignments": [SimpleNamespace(assignee_type="user", user_id=1, user=SimpleNamespace(fullname="B"))],
            "item": SimpleNamespace(sort_order=1, id=9),
            "total_count": 2,
            "submitted_count": 0,
            "my_assignment": SimpleNamespace(user_id=99),
        }

        groups = build_outline_group_rows(
            [row_a, row_b],
            lambda assignments, fallback_index=0: outline_group_identity(assignments, lambda _user: "", fallback_index=fallback_index),
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["total_items"], 2)
        self.assertEqual(groups[0]["fully_submitted_items"], 1)
        self.assertEqual(groups[0]["my_items"], 1)
        self.assertEqual(groups[0]["rows"][0]["item"].id, 9)

    def test_build_file_and_form_rows_mark_current_user_and_parse_payload(self):
        assignments = [
            SimpleNamespace(id=1, user_id=7),
            SimpleNamespace(id=2, user_id=9),
        ]
        submissions = {
            1: SimpleNamespace(payload_json='{"answer": 1}'),
            2: None,
        }
        fields = [SimpleNamespace(id=3)]

        file_rows = build_file_task_rows(assignments, 7, lambda assignment: submissions.get(assignment.id))
        returned_fields, form_rows = build_form_task_rows(
            assignments,
            fields,
            7,
            lambda assignment: submissions.get(assignment.id),
            task_form_submission_payload,
        )

        self.assertTrue(file_rows[0]["is_current_user"])
        self.assertEqual(returned_fields, fields)
        self.assertEqual(form_rows[0]["payload"], {"answer": 1})
        self.assertEqual(form_rows[1]["payload"], {})

    def test_form_helpers_normalize_types_and_parse_options(self):
        field = SimpleNamespace(
            id=10,
            field_key="status",
            field_label="Trạng thái",
            field_type="RADIO",
            is_required=1,
            field_options_json='{"choices":["Mới","Cũ"],"target_type":"unit","target_unit_domains":["minh-xuan"]}',
        )

        self.assertEqual(normalize_task_form_field_type("RADIO", {"text", "radio"}), "radio")
        self.assertEqual(form_field_options(field)["choices"], ["Mới", "Cũ"])

        views = task_form_field_views(
            [field],
            lambda value: normalize_task_form_field_type(value, {"text", "radio"}),
            form_field_options,
        )
        self.assertEqual(views[0]["choices"], ["Mới", "Cũ"])
        self.assertTrue(views[0]["is_required"])
        self.assertEqual(views[0]["target_type"], "unit")
        self.assertEqual(views[0]["target_unit_domains"], ["minh-xuan"])

    def test_task_form_value_is_empty_handles_none_string_and_list(self):
        self.assertTrue(task_form_value_is_empty(None))
        self.assertTrue(task_form_value_is_empty("   "))
        self.assertTrue(task_form_value_is_empty([]))
        self.assertFalse(task_form_value_is_empty("x"))


if __name__ == "__main__":
    unittest.main()
