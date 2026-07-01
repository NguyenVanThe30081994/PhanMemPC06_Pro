# -*- coding: utf-8 -*-
import unittest

from task_blueprints import (
    workflow_blueprint_example_catalog,
    normalize_task_workflow_blueprint,
    workflow_blueprint_form_field_defs,
    workflow_blueprint_item_configs,
    workflow_blueprint_preview_data,
    workflow_blueprint_report_schema,
    workflow_blueprint_summary_text,
    workflow_blueprint_task_mode,
    workflow_blueprint_workflow_mode,
)


class TaskBlueprintTests(unittest.TestCase):
    def test_outline_blueprint_creates_items_and_infers_mode(self):
        blueprint = normalize_task_workflow_blueprint(
            {
                "title": "Công tác tuần",
                "source_kind": "directive",
                "cadence": "weekly",
                "items": [
                    {"title": "Đầu mục 1", "report_kind": "narrative"},
                    {"title": "Chỉ tiêu 2", "report_kind": "number", "attachment_required": True},
                ],
            }
        )

        self.assertEqual(blueprint["collection_mode"], "outline")
        self.assertEqual(workflow_blueprint_task_mode(blueprint), "OUTLINE")
        self.assertEqual(workflow_blueprint_workflow_mode(blueprint), "child_tasks")
        self.assertEqual(len(workflow_blueprint_item_configs(blueprint)), 2)
        self.assertEqual(workflow_blueprint_item_configs(blueprint)[1]["report_kind"], "number")

    def test_form_blueprint_creates_internal_form_fields(self):
        blueprint = normalize_task_workflow_blueprint(
            {
                "title": "Thu thập tiến độ",
                "source_kind": "google_form",
                "collection_mode": "form",
                "form_fields": [
                    {"label": "Đơn vị", "type": "text", "required": True},
                    {"label": "Tổng số hồ sơ", "type": "number"},
                    {"label": "Lĩnh vực", "type": "radio", "choices": ["A", "B"]},
                ],
            }
        )

        fields = workflow_blueprint_form_field_defs(blueprint)
        self.assertEqual(workflow_blueprint_task_mode(blueprint), "FORM")
        self.assertEqual(len(fields), 3)
        self.assertEqual(fields[0]["field_label"], "Đơn vị")
        self.assertTrue(fields[0]["is_required"])
        self.assertIn('"choices": ["A", "B"]', fields[2]["field_options_json"])

    def test_file_blueprint_creates_structured_report_schema(self):
        blueprint = normalize_task_workflow_blueprint(
            {
                "title": "Báo cáo tháng",
                "source_kind": "sectioned_report",
                "collection_mode": "file",
                "report_schema": {
                    "enabled": True,
                    "narrative": {"enabled": True, "required": True, "label": "Nội dung tổng hợp"},
                    "attachment": {"enabled": True, "required": False, "label": "Phụ lục"},
                    "fields": [
                        {"label": "Số hồ sơ", "type": "number", "required": True},
                        {"label": "Nhận xét", "type": "textarea"},
                    ],
                },
            }
        )

        schema = workflow_blueprint_report_schema(blueprint)
        self.assertEqual(workflow_blueprint_task_mode(blueprint), "FILE")
        self.assertTrue(schema["narrative"]["enabled"])
        self.assertTrue(schema["attachment"]["enabled"])
        self.assertEqual(schema["fields"][0]["type"], "number")
        self.assertIn("Chỉ tiêu báo cáo", workflow_blueprint_summary_text(blueprint))

    def test_preview_payload_summarizes_outline_blueprint(self):
        blueprint = normalize_task_workflow_blueprint(
            {
                "title": "Công tác tuần",
                "source_kind": "directive",
                "cadence": "weekly",
                "items": [
                    {"title": "Đầu mục 1", "report_kind": "narrative"},
                    {"title": "Chỉ tiêu 2", "report_kind": "number"},
                ],
            }
        )

        preview = workflow_blueprint_preview_data(blueprint)
        self.assertEqual(preview["task_mode"], "OUTLINE")
        self.assertEqual(preview["item_count"], 2)
        self.assertIn("Đầu mục 1", preview["item_titles"])

    def test_example_catalog_contains_supported_presets(self):
        examples = workflow_blueprint_example_catalog()
        keys = {item["key"] for item in examples}
        self.assertIn("weekly_outline", keys)
        self.assertIn("google_form", keys)
        self.assertIn("monthly_file", keys)


if __name__ == "__main__":
    unittest.main()
