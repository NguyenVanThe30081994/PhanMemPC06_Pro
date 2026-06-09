# -*- coding: utf-8 -*-
import unittest

from google_forms import (
    build_google_form_create_requests,
    builder_schema_from_form_definition,
    extract_google_form_id,
    normalize_google_form_builder_schema,
    parse_google_form_definition,
    parse_google_form_responses,
)


FORM_PAYLOAD = {
    "formId": "abc123FORM",
    "info": {"title": "Thu thập báo cáo nhanh"},
    "items": [
        {
            "itemId": "item-1",
            "title": "Đơn vị báo cáo",
            "questionItem": {
                "question": {
                    "questionId": "q-unit",
                    "required": True,
                    "textQuestion": {},
                }
            },
        },
        {
            "itemId": "item-2",
            "title": "Tổng số hồ sơ",
            "questionItem": {
                "question": {
                    "questionId": "q-total",
                    "scaleQuestion": {"low": 1, "high": 10},
                }
            },
        },
        {
            "itemId": "item-3",
            "title": "Trạng thái",
            "questionItem": {
                "question": {
                    "questionId": "q-status",
                    "choiceQuestion": {
                        "type": "RADIO",
                        "options": [{"value": "Mới"}, {"value": "Hoàn thành"}],
                    },
                }
            },
        },
        {
            "itemId": "item-4",
            "title": "Khó khăn",
            "questionItem": {
                "question": {
                    "questionId": "q-note",
                    "textQuestion": {"paragraph": True},
                }
            },
        },
    ],
}


RESPONSES_PAYLOAD = [
    {
        "responseId": "resp-1",
        "respondentEmail": "user@example.com",
        "lastSubmittedTime": "2026-06-08T09:30:00Z",
        "answers": {
            "q-unit": {"textAnswers": {"answers": [{"value": "Công an phường Minh Xuân"}]}},
            "q-total": {"textAnswers": {"answers": [{"value": "8"}]}},
            "q-status": {"textAnswers": {"answers": [{"value": "Hoàn thành"}]}},
            "q-note": {"textAnswers": {"answers": [{"value": "Không có"}]}},
        },
    }
]


class GoogleFormsTests(unittest.TestCase):
    def test_extract_google_form_id_from_url_or_raw_id(self):
        self.assertEqual(
            extract_google_form_id("https://docs.google.com/forms/d/abc123FORM/viewform"),
            "abc123FORM",
        )
        self.assertEqual(extract_google_form_id("abc123FORMxyz987654321"), "abc123FORMxyz987654321")
        self.assertEqual(extract_google_form_id(""), "")

    def test_parse_google_form_definition_maps_supported_field_types(self):
        fields, question_map = parse_google_form_definition(FORM_PAYLOAD)

        self.assertEqual(len(fields), 4)
        self.assertEqual(fields[0]["field_key"], "google_q_q-unit")
        self.assertEqual(fields[1]["field_type"], "number")
        self.assertEqual(fields[2]["field_type"], "radio")
        self.assertEqual(question_map["q-note"]["field_type"], "textarea")

    def test_parse_google_form_responses_maps_answers_to_field_keys(self):
        fields, parsed = parse_google_form_responses(FORM_PAYLOAD, RESPONSES_PAYLOAD)

        self.assertEqual(len(fields), 4)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["response_id"], "resp-1")
        self.assertEqual(parsed[0]["respondent_email"], "user@example.com")
        self.assertEqual(parsed[0]["payload"]["google_q_q-status"], "Hoàn thành")
        self.assertEqual(parsed[0]["payload_by_label"]["Đơn vị báo cáo"], "Công an phường Minh Xuân")
        self.assertIsNotNone(parsed[0]["submitted_at"])

    def test_normalize_builder_schema_and_create_requests(self):
        schema = normalize_google_form_builder_schema(
            {
                "form_info": {"title": "Builder test", "description": "desc"},
                "publish_settings": {"isPublished": False, "isAcceptingResponses": False},
                "matching": {"mode": "unit", "match_field": "Đơn vị báo cáo"},
                "items": [
                    {"kind": "text", "title": "Đơn vị báo cáo", "required": True},
                    {"kind": "radio", "title": "Trạng thái", "options": ["Mới", "Xong"]},
                    {
                        "kind": "grid_radio",
                        "title": "Tiến độ",
                        "rows": ["Hàng 1", "Hàng 2"],
                        "columns": ["Tốt", "Chậm"],
                    },
                    {"kind": "page_break", "title": "Trang 2"},
                ],
            }
        )
        requests = build_google_form_create_requests(schema)
        self.assertEqual(schema["form_info"]["title"], "Builder test")
        self.assertEqual(len(requests), 4)
        self.assertIn("createItem", requests[0])
        self.assertEqual(
            requests[1]["createItem"]["item"]["questionItem"]["question"]["choiceQuestion"]["type"],
            "RADIO",
        )
        self.assertIn("questionGroupItem", requests[2]["createItem"]["item"])
        self.assertIn("pageBreakItem", requests[3]["createItem"]["item"])

    def test_builder_schema_from_form_definition_imports_items(self):
        imported = builder_schema_from_form_definition(FORM_PAYLOAD)
        self.assertEqual(imported["form_info"]["title"], "Thu thập báo cáo nhanh")
        self.assertEqual(imported["items"][0]["kind"], "text")
        self.assertEqual(imported["items"][1]["kind"], "scale")


if __name__ == "__main__":
    unittest.main()
