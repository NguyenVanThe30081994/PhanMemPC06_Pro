# -*- coding: utf-8 -*-
import unittest

from task_import_ai import analyze_task_import_config, apply_ai_analysis_to_config


class TaskImportAITests(unittest.TestCase):
    def test_analyze_outline_suggests_user_assignment_numeric_and_attachment(self):
        config = {
            "title": "",
            "summary": "",
            "source_name": "Công tác tuần",
            "collection_mode": "outline",
            "domain": "",
            "priority": "Trung bình",
            "items": [
                {
                    "title": "Đồng chí Nguyễn Văn A tổng hợp số hồ sơ và file minh chứng",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [{"type": "user", "id": 9, "label": "Nguyễn Văn A"}],
            "unit_lookup": {},
            "role_lookup": {},
            "user_lookup": {9: "Nguyễn Văn A"},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)
        suggestion = analysis["outline_items"][0]["suggestion"]

        self.assertFalse(analysis["publish_ready"])
        self.assertEqual(suggestion["assign_type"], "user")
        self.assertEqual(suggestion["user_ids"], [9])
        self.assertEqual(suggestion["report_kind"], "number")
        self.assertTrue(suggestion["attachment_required"])
        self.assertEqual(analysis["specialist_brief"]["delivery_model_label"], "Phát hành thành task OUTLINE")

    def test_analyze_assignment_includes_alternatives(self):
        config = {
            "title": "Giao việc tổng hợp",
            "summary": "Nguyễn Văn A hoặc Đội tổng hợp thực hiện.",
            "collection_mode": "outline",
            "domain": "",
            "items": [
                {
                    "title": "Nguyễn Văn A phối hợp Đội Tổng hợp báo cáo số liệu",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [{"type": "unit", "id": None, "value": "doi-tong-hop", "label": "Đội Tổng hợp"}],
            "field_catalog": [],
            "role_catalog": [{"type": "role", "id": 3, "label": "Cán bộ tổng hợp"}],
            "user_catalog": [{"type": "user", "id": 9, "label": "Nguyễn Văn A"}],
            "unit_lookup": {"doi-tong-hop": "Đội Tổng hợp"},
            "role_lookup": {3: "Cán bộ tổng hợp"},
            "user_lookup": {9: "Nguyễn Văn A"},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)
        suggestion = analysis["outline_items"][0]["suggestion"]

        self.assertEqual(suggestion["assign_type"], "user")
        self.assertTrue(suggestion["alternatives"])
        self.assertTrue(suggestion["fit_signals"])
        self.assertIn("semantic_score", suggestion["score_breakdown"])
        self.assertTrue(any(item["assign_type"] in {"unit", "role"} for item in suggestion["alternatives"]))

    def test_analyze_assignment_prefers_history_with_better_execution_rate(self):
        config = {
            "title": "Chuyên đề cư trú",
            "summary": "",
            "collection_mode": "outline",
            "domain": "",
            "items": [
                {
                    "title": "Chuyên đề cư trú",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [],
            "unit_lookup": {},
            "role_lookup": {},
            "user_lookup": {},
            "report_templates": [],
            "history_entries": [
                {
                    "title": "Chuyên đề cư trú định kỳ",
                    "assign_type": "user",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [9],
                    "total_assignments": 5,
                    "submitted_assignments": 1,
                    "completed_assignments": 0,
                    "submitted_rate": 0.2,
                    "completed_rate": 0.0,
                    "on_time_assignments": 1,
                    "late_assignments": 0,
                    "on_time_rate": 0.2,
                    "deadline_tracked": True,
                },
                {
                    "title": "Chuyên đề cư trú định kỳ",
                    "assign_type": "unit",
                    "unit_domains": ["doi-tong-hop"],
                    "role_ids": [],
                    "user_ids": [],
                    "total_assignments": 5,
                    "submitted_assignments": 5,
                    "completed_assignments": 5,
                    "submitted_rate": 1.0,
                    "completed_rate": 1.0,
                    "on_time_assignments": 5,
                    "late_assignments": 0,
                    "on_time_rate": 1.0,
                    "deadline_tracked": True,
                },
            ],
        }

        analysis = analyze_task_import_config(config, context)
        suggestion = analysis["outline_items"][0]["suggestion"]
        history_match = suggestion["history_matches"][0]

        self.assertEqual(suggestion["assign_type"], "unit")
        self.assertEqual(suggestion["unit_domains"], ["doi-tong-hop"])
        self.assertGreater(history_match["history_quality_score"], history_match["score"])
        self.assertEqual(history_match["assign_type"], "unit")
        self.assertTrue(suggestion["fit_signals"])
        self.assertIn("on_time_rate", suggestion["score_breakdown"])
        self.assertTrue(any("Lịch sử thực hiện" in reason for reason in suggestion["reasons"]))
        self.assertTrue(any("Đúng hạn" in reason for reason in suggestion["reasons"]))

    def test_analyze_assignment_prefers_history_matching_domain_and_category(self):
        config = {
            "title": "Báo cáo chuyên đề cư trú",
            "summary": "",
            "collection_mode": "outline",
            "category": "cu-tru",
            "domain": "doi-canh-sat",
            "items": [
                {
                    "title": "Báo cáo chuyên đề cư trú",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [],
            "unit_lookup": {},
            "role_lookup": {},
            "user_lookup": {},
            "report_templates": [],
            "history_entries": [
                {
                    "title": "Báo cáo chuyên đề cư trú",
                    "category": "khac",
                    "domain": "doi-khac",
                    "assign_type": "user",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [9],
                    "total_assignments": 4,
                    "submitted_assignments": 4,
                    "completed_assignments": 4,
                    "submitted_rate": 1.0,
                    "completed_rate": 1.0,
                    "on_time_assignments": 4,
                    "late_assignments": 0,
                    "on_time_rate": 1.0,
                    "deadline_tracked": True,
                },
                {
                    "title": "Báo cáo chuyên đề cư trú",
                    "category": "cu-tru",
                    "domain": "doi-canh-sat",
                    "assign_type": "unit",
                    "unit_domains": ["doi-canh-sat"],
                    "role_ids": [],
                    "user_ids": [],
                    "total_assignments": 3,
                    "submitted_assignments": 2,
                    "completed_assignments": 2,
                    "submitted_rate": 0.6667,
                    "completed_rate": 0.6667,
                    "on_time_assignments": 2,
                    "late_assignments": 0,
                    "on_time_rate": 0.6667,
                    "deadline_tracked": True,
                },
            ],
        }

        analysis = analyze_task_import_config(config, context)
        suggestion = analysis["outline_items"][0]["suggestion"]
        history_match = suggestion["history_matches"][0]

        self.assertEqual(suggestion["assign_type"], "unit")
        self.assertEqual(history_match["domain"], "doi-canh-sat")
        self.assertGreater(history_match["domain_match_bonus"], 0)
        self.assertGreater(history_match["category_match_bonus"], 0)
        self.assertTrue(any(signal["key"] == "domain_match" for signal in suggestion["fit_signals"]))
        self.assertTrue(any("Trùng đội nghiệp vụ" in reason for reason in suggestion["reasons"]))

    def test_analyze_file_report_fields_suggests_unit_scope_and_workflow_stages(self):
        config = {
            "title": "Báo cáo chuyên đề theo đơn vị",
            "summary": "Tách chỉ tiêu theo từng đơn vị.",
            "collection_mode": "file",
            "domain": "",
            "assign_type": "unit",
            "unit_domains": ["pc06"],
            "role_ids": [],
            "user_ids": [],
            "report_narrative_enabled": True,
            "report_fields": [
                {
                    "label": "Chỉ tiêu Công an phường Minh Xuân",
                    "type": "number",
                    "required": True,
                    "target_type": "all",
                }
            ],
        }
        context = {
            "unit_catalog": [{"type": "unit", "id": None, "value": "minh-xuan", "label": "Công an phường Minh Xuân"}],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [],
            "unit_lookup": {"minh-xuan": "Công an phường Minh Xuân"},
            "role_lookup": {},
            "user_lookup": {},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)
        field_suggestion = analysis["report_fields"][0]["suggestion"]

        self.assertEqual(analysis["assignment_strategy"]["mode"], "task_level_with_field_scope")
        self.assertEqual(field_suggestion["target_type"], "unit")
        self.assertEqual(field_suggestion["target_unit_domains"], ["minh-xuan"])
        self.assertTrue(any(stage["key"] == "proposal" for stage in analysis["workflow_stages"]))
        self.assertTrue(any("Chỉ tiêu" in action or "phạm vi" in action for action in analysis["recommended_actions"]))
        self.assertEqual(analysis["specialist_brief"]["delivery_model_label"], "Phát hành thành task FILE")
        self.assertIn("chuẩn hóa", analysis["specialist_brief"]["input_summary"].lower())

    def test_analyze_form_fields_suggests_unit_scope(self):
        config = {
            "title": "Biểu mẫu theo đơn vị",
            "summary": "Mỗi đơn vị nhập phần của mình.",
            "collection_mode": "form",
            "domain": "",
            "assign_type": "unit",
            "unit_domains": ["pc06"],
            "role_ids": [],
            "user_ids": [],
            "form_fields": [
                {
                    "field_label": "Chỉ tiêu Công an phường Minh Xuân",
                    "field_type": "number",
                    "field_options_text": "",
                    "target_type": "all",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [{"type": "unit", "id": None, "value": "minh-xuan", "label": "Công an phường Minh Xuân"}],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [],
            "unit_lookup": {"minh-xuan": "Công an phường Minh Xuân"},
            "role_lookup": {},
            "user_lookup": {},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)
        field_suggestion = analysis["form_fields"][0]["suggestion"]

        self.assertEqual(analysis["assignment_strategy"]["mode"], "task_level_with_field_scope")
        self.assertEqual(field_suggestion["target_type"], "unit")
        self.assertEqual(field_suggestion["target_unit_domains"], ["minh-xuan"])
        self.assertTrue(any("field biểu mẫu" in action or "phạm vi" in action for action in analysis["recommended_actions"]))

    def test_analyze_form_detects_recipient_without_visible_fields(self):
        config = {
            "title": "Biểu mẫu báo cáo phân phần",
            "summary": "Hai người nhận nhưng chỉ một người có field.",
            "collection_mode": "form",
            "domain": "",
            "assign_type": "user",
            "unit_domains": [],
            "role_ids": [],
            "user_ids": [11, 12],
            "form_fields": [
                {
                    "field_label": "Chỉ tiêu của A",
                    "field_type": "number",
                    "field_options_text": "",
                    "target_type": "user",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [11],
                }
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [
                {"type": "user", "id": 11, "label": "Nguyễn Văn A"},
                {"type": "user", "id": 12, "label": "Nguyễn Văn B"},
            ],
            "recipient_catalog": [
                {"id": 11, "label": "Nguyễn Văn A", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
                {"id": 12, "label": "Nguyễn Văn B", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "tan-quang", "unit_name": "Công an phường Tân Quang", "unit_key": "tanquang"},
            ],
            "unit_lookup": {},
            "role_lookup": {1: "Cán bộ"},
            "user_lookup": {11: "Nguyễn Văn A", 12: "Nguyễn Văn B"},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)

        self.assertFalse(analysis["publish_ready"])
        self.assertEqual(len(analysis["recipient_insights"]["empty_payload_recipients"]), 1)
        self.assertEqual(analysis["recipient_insights"]["empty_payload_recipients"][0]["user_name"], "Nguyễn Văn B")
        self.assertTrue(any("chưa thấy nội dung báo cáo nào" in blocker for blocker in analysis["blockers"]))

    def test_analyze_outline_detects_overloaded_recipient(self):
        config = {
            "title": "Điều hành nhiều đầu mục",
            "summary": "",
            "collection_mode": "outline",
            "domain": "",
            "items": [
                {"title": "Mục 1", "assign_type": "user", "user_ids": [11], "unit_domains": [], "role_ids": []},
                {"title": "Mục 2", "assign_type": "user", "user_ids": [11], "unit_domains": [], "role_ids": []},
                {"title": "Mục 3", "assign_type": "user", "user_ids": [11], "unit_domains": [], "role_ids": []},
                {"title": "Mục 4", "assign_type": "user", "user_ids": [11], "unit_domains": [], "role_ids": []},
                {"title": "Mục 5", "assign_type": "user", "user_ids": [12], "unit_domains": [], "role_ids": []},
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [
                {"type": "user", "id": 11, "label": "Nguyễn Văn A"},
                {"type": "user", "id": 12, "label": "Nguyễn Văn B"},
            ],
            "recipient_catalog": [
                {"id": 11, "label": "Nguyễn Văn A", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
                {"id": 12, "label": "Nguyễn Văn B", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
            ],
            "unit_lookup": {},
            "role_lookup": {1: "Cán bộ"},
            "user_lookup": {11: "Nguyễn Văn A", 12: "Nguyễn Văn B"},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)

        self.assertTrue(analysis["publish_ready"])
        self.assertEqual(len(analysis["recipient_insights"]["overloaded_recipients"]), 1)
        self.assertEqual(analysis["recipient_insights"]["overloaded_recipients"][0]["user_name"], "Nguyễn Văn A")
        self.assertTrue(any("Cân nhắc chia lại đầu mục" in item for item in analysis["opportunities"]))

    def test_analyze_assignment_prefers_history_when_direct_user_is_overloaded(self):
        config = {
            "title": "Nguyễn Văn A báo cáo cư trú",
            "summary": "",
            "collection_mode": "outline",
            "category": "cu-tru",
            "domain": "doi-tong-hop",
            "items": [
                {
                    "title": "Nguyễn Văn A báo cáo cư trú",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [{"type": "unit", "id": None, "value": "doi-tong-hop", "label": "Đội Tổng hợp"}],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [{"type": "user", "id": 11, "label": "Nguyễn Văn A"}],
            "unit_lookup": {"doi-tong-hop": "Đội Tổng hợp"},
            "role_lookup": {},
            "user_lookup": {11: "Nguyễn Văn A"},
            "report_templates": [],
            "history_entries": [
                {
                    "title": "Nguyễn Văn A báo cáo cư trú",
                    "category": "cu-tru",
                    "domain": "doi-tong-hop",
                    "assign_type": "unit",
                    "unit_domains": ["doi-tong-hop"],
                    "role_ids": [],
                    "user_ids": [],
                    "total_assignments": 6,
                    "submitted_assignments": 6,
                    "completed_assignments": 6,
                    "submitted_rate": 1.0,
                    "completed_rate": 1.0,
                    "on_time_assignments": 6,
                    "late_assignments": 0,
                    "on_time_rate": 1.0,
                    "deadline_tracked": True,
                }
            ],
            "user_workload_map": {
                11: {
                    "active_assignments": 8,
                    "overdue_assignments": 2,
                    "due_soon_assignments": 1,
                }
            },
            "role_workload_map": {},
            "unit_workload_map": {
                "doi-tong-hop": {
                    "active_assignments": 1,
                    "overdue_assignments": 0,
                    "due_soon_assignments": 0,
                }
            },
        }

        analysis = analyze_task_import_config(config, context)
        suggestion = analysis["outline_items"][0]["suggestion"]

        self.assertEqual(suggestion["assign_type"], "unit")
        self.assertEqual(suggestion["unit_domains"], ["doi-tong-hop"])
        self.assertTrue(any(item.get("workload_penalty", 0) > 0 for item in suggestion["alternatives"]))
        self.assertTrue(any("tải vận hành cao" in warning.lower() for warning in analysis["warnings"]))

    def test_analyze_recipient_insights_surfaces_high_current_workload(self):
        config = {
            "title": "Biểu mẫu chuyên đề",
            "summary": "",
            "collection_mode": "form",
            "domain": "",
            "assign_type": "user",
            "unit_domains": [],
            "role_ids": [],
            "user_ids": [11, 12],
            "form_fields": [
                {
                    "field_label": "Tổng số hồ sơ",
                    "field_type": "number",
                    "field_options_text": "",
                    "target_type": "all",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [
                {"type": "user", "id": 11, "label": "Nguyễn Văn A"},
                {"type": "user", "id": 12, "label": "Nguyễn Văn B"},
            ],
            "recipient_catalog": [
                {"id": 11, "label": "Nguyễn Văn A", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
                {"id": 12, "label": "Nguyễn Văn B", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "tan-quang", "unit_name": "Công an phường Tân Quang", "unit_key": "tanquang"},
            ],
            "unit_lookup": {},
            "role_lookup": {1: "Cán bộ"},
            "user_lookup": {11: "Nguyễn Văn A", 12: "Nguyễn Văn B"},
            "report_templates": [],
            "history_entries": [],
            "user_workload_map": {
                11: {
                    "active_assignments": 6,
                    "overdue_assignments": 1,
                    "due_soon_assignments": 2,
                }
            },
            "role_workload_map": {},
            "unit_workload_map": {},
        }

        analysis = analyze_task_import_config(config, context)

        self.assertEqual(len(analysis["recipient_insights"]["high_workload_recipients"]), 1)
        self.assertEqual(analysis["recipient_insights"]["high_workload_recipients"][0]["user_name"], "Nguyễn Văn A")
        self.assertEqual(analysis["recipient_insights"]["rows"][0]["active_assignments"], 6)
        self.assertTrue(any("tải vận hành cao" in warning.lower() for warning in analysis["warnings"]))

    def test_analyze_form_coordination_audit_surfaces_fragmented_unit(self):
        config = {
            "title": "Biểu mẫu phối hợp trong cùng đơn vị",
            "summary": "",
            "collection_mode": "form",
            "domain": "",
            "assign_type": "user",
            "unit_domains": [],
            "role_ids": [],
            "user_ids": [21, 22],
            "form_fields": [
                {
                    "field_label": "Tổng số hồ sơ",
                    "field_type": "number",
                    "field_options_text": "",
                    "target_type": "all",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [
                {"type": "user", "id": 21, "label": "Nguyễn Văn A"},
                {"type": "user", "id": 22, "label": "Nguyễn Văn B"},
            ],
            "recipient_catalog": [
                {"id": 21, "label": "Nguyễn Văn A", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
                {"id": 22, "label": "Nguyễn Văn B", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
            ],
            "unit_lookup": {},
            "role_lookup": {1: "Cán bộ"},
            "user_lookup": {21: "Nguyễn Văn A", 22: "Nguyễn Văn B"},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)
        recipient_insights = analysis["recipient_insights"]

        self.assertTrue(analysis["publish_ready"])
        self.assertEqual(len(recipient_insights["submission_groups"]), 2)
        self.assertEqual(len(recipient_insights["fragmented_units"]), 1)
        self.assertEqual(recipient_insights["fragmented_units"][0]["unit_name"], "Công an phường Minh Xuân")
        self.assertTrue(any("nhiều nhóm nộp" in warning.lower() for warning in analysis["warnings"]))

    def test_analyze_file_coordination_audit_builds_unit_delivery_matrix(self):
        config = {
            "title": "Báo cáo file theo đơn vị",
            "summary": "",
            "collection_mode": "file",
            "domain": "",
            "assign_type": "unit",
            "unit_domains": ["minh-xuan"],
            "role_ids": [],
            "user_ids": [],
            "report_narrative_enabled": True,
            "report_narrative_label": "Nhận định tổng hợp",
            "report_attachment_enabled": False,
            "report_fields": [
                {
                    "label": "Tổng số hồ sơ",
                    "type": "number",
                    "required": True,
                    "target_type": "all",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [],
                }
            ],
        }
        context = {
            "unit_catalog": [],
            "field_catalog": [],
            "role_catalog": [],
            "user_catalog": [
                {"type": "user", "id": 31, "label": "Nguyễn Văn A"},
                {"type": "user", "id": 32, "label": "Nguyễn Văn B"},
            ],
            "recipient_catalog": [
                {"id": 31, "label": "Nguyễn Văn A", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
                {"id": 32, "label": "Nguyễn Văn B", "role_id": 1, "role_name": "Cán bộ", "unit_domain": "minh-xuan", "unit_name": "Công an phường Minh Xuân", "unit_key": "minhxuan"},
            ],
            "unit_lookup": {},
            "role_lookup": {1: "Cán bộ"},
            "user_lookup": {31: "Nguyễn Văn A", 32: "Nguyễn Văn B"},
            "report_templates": [],
            "history_entries": [],
        }

        analysis = analyze_task_import_config(config, context)
        recipient_insights = analysis["recipient_insights"]

        self.assertEqual(len(recipient_insights["submission_groups"]), 1)
        self.assertEqual(recipient_insights["submission_groups"][0]["mode_label"], "Nộp theo đơn vị")
        self.assertIn("Tổng số hồ sơ", recipient_insights["submission_groups"][0]["payload_labels"])
        self.assertIn("Nhận định tổng hợp", recipient_insights["submission_groups"][0]["payload_labels"])
        self.assertEqual(recipient_insights["unit_delivery_matrix"][0]["submission_group_count"], 1)
        self.assertEqual(recipient_insights["unit_delivery_matrix"][0]["payload_count"], 2)

    def test_apply_analysis_fills_missing_values_safely(self):
        config = {
            "title": "",
            "summary": "",
            "collection_mode": "form",
            "domain": "",
            "priority": "Trung bình",
            "assign_type": "",
            "unit_domains": [],
            "role_ids": [],
            "user_ids": [],
            "form_fields": [{"field_label": "Tổng số hồ sơ"}],
        }
        analysis = {
            "recommended_updates": {
                "title": "Biểu mẫu thu thập báo cáo",
                "summary": "Thu thập dữ liệu định kỳ.",
                "domain": "doi-tham-muu",
                "category": "",
                "priority": "Cao",
            },
            "global_assignment": {
                "assign_type": "user",
                "unit_domains": [],
                "role_ids": [],
                "user_ids": [12],
            },
        }

        updated, applied = apply_ai_analysis_to_config(config, analysis, mode="safe")

        self.assertEqual(updated["title"], "Biểu mẫu thu thập báo cáo")
        self.assertEqual(updated["summary"], "Thu thập dữ liệu định kỳ.")
        self.assertEqual(updated["domain"], "doi-tham-muu")
        self.assertEqual(updated["priority"], "Cao")
        self.assertEqual(updated["assign_type"], "user")
        self.assertEqual(updated["user_ids"], [12])
        self.assertTrue(applied)

    def test_apply_analysis_assigns_form_field_targets_safely(self):
        config = {
            "title": "Biểu mẫu theo đơn vị",
            "summary": "Mỗi đơn vị nhập phần mình phụ trách.",
            "collection_mode": "form",
            "domain": "",
            "priority": "Trung bình",
            "assign_type": "unit",
            "unit_domains": ["pc06"],
            "role_ids": [],
            "user_ids": [],
            "form_fields": [
                {
                    "field_label": "Chỉ tiêu Công an phường Minh Xuân",
                    "field_key": "chi_tieu_minh_xuan",
                    "field_type": "number",
                    "field_options_text": "",
                    "target_type": "all",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [],
                }
            ],
        }
        analysis = {
            "recommended_updates": {},
            "global_assignment": {
                "assign_type": "unit",
                "unit_domains": ["pc06"],
                "role_ids": [],
                "user_ids": [],
            },
            "form_fields": [
                {
                    "index": 0,
                    "suggestion": {
                        "target_type": "unit",
                        "target_unit_domains": ["minh-xuan"],
                        "target_role_ids": [],
                        "target_user_ids": [],
                        "confidence_score": 0.91,
                    },
                }
            ],
        }

        updated, applied = apply_ai_analysis_to_config(config, analysis, mode="safe")

        self.assertEqual(updated["form_fields"][0]["target_type"], "unit")
        self.assertEqual(updated["form_fields"][0]["target_unit_domains"], ["minh-xuan"])
        self.assertTrue(any("phạm vi nhập liệu" in item for item in applied))

    def test_apply_analysis_can_limit_to_metadata_only(self):
        config = {
            "title": "",
            "summary": "",
            "collection_mode": "form",
            "domain": "",
            "priority": "Trung bình",
            "assign_type": "",
            "unit_domains": [],
            "role_ids": [],
            "user_ids": [],
            "form_fields": [{"field_label": "Tổng số hồ sơ"}],
        }
        analysis = {
            "recommended_updates": {
                "title": "Biểu mẫu thu thập báo cáo",
                "summary": "Thu thập dữ liệu định kỳ.",
                "domain": "doi-tham-muu",
                "priority": "Cao",
            },
            "global_assignment": {
                "assign_type": "user",
                "unit_domains": [],
                "role_ids": [],
                "user_ids": [12],
            },
        }

        updated, applied = apply_ai_analysis_to_config(config, analysis, mode="safe", sections=["metadata"])

        self.assertEqual(updated["title"], "Biểu mẫu thu thập báo cáo")
        self.assertEqual(updated["summary"], "Thu thập dữ liệu định kỳ.")
        self.assertEqual(updated["domain"], "doi-tham-muu")
        self.assertEqual(updated["priority"], "Cao")
        self.assertEqual(updated["assign_type"], "")
        self.assertEqual(updated["user_ids"], [])
        self.assertTrue(any("tiêu đề" in item.lower() for item in applied))

    def test_apply_analysis_can_limit_to_outline_items_only(self):
        config = {
            "title": "Nháp điều hành",
            "summary": "Tổng hợp đầu mục",
            "collection_mode": "outline",
            "domain": "",
            "priority": "Trung bình",
            "items": [
                {
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ và file minh chứng",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                }
            ],
        }
        analysis = {
            "recommended_updates": {"title": "Không dùng ở test này"},
            "outline_items": [
                {
                    "index": 0,
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ và file minh chứng",
                    "suggestion": {
                        "assign_type": "user",
                        "unit_domains": [],
                        "role_ids": [],
                        "user_ids": [9],
                        "report_kind": "number",
                        "attachment_required": True,
                    },
                }
            ],
        }

        updated, applied = apply_ai_analysis_to_config(config, analysis, mode="safe", sections=["outline_items"])

        self.assertEqual(updated["title"], "Nháp điều hành")
        self.assertEqual(updated["items"][0]["assign_type"], "user")
        self.assertEqual(updated["items"][0]["user_ids"], [9])
        self.assertEqual(updated["items"][0]["report_kind"], "number")
        self.assertTrue(updated["items"][0]["attachment_required"])
        self.assertTrue(any("phân công" in item.lower() for item in applied))

    def test_apply_analysis_can_limit_to_single_outline_index(self):
        config = {
            "title": "Nháp điều hành",
            "summary": "Tổng hợp đầu mục",
            "collection_mode": "outline",
            "domain": "",
            "priority": "Trung bình",
            "items": [
                {
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                },
                {
                    "title": "Nguyễn Văn B tổng hợp file minh chứng",
                    "guide_text": "",
                    "report_kind": "narrative",
                    "attachment_required": False,
                    "assign_type": "",
                    "unit_domains": [],
                    "role_ids": [],
                    "user_ids": [],
                },
            ],
        }
        analysis = {
            "recommended_updates": {},
            "outline_items": [
                {
                    "index": 0,
                    "title": "Nguyễn Văn A tổng hợp số hồ sơ",
                    "suggestion": {
                        "assign_type": "user",
                        "unit_domains": [],
                        "role_ids": [],
                        "user_ids": [9],
                        "report_kind": "number",
                        "attachment_required": False,
                    },
                },
                {
                    "index": 1,
                    "title": "Nguyễn Văn B tổng hợp file minh chứng",
                    "suggestion": {
                        "assign_type": "user",
                        "unit_domains": [],
                        "role_ids": [],
                        "user_ids": [10],
                        "report_kind": "narrative",
                        "attachment_required": True,
                    },
                },
            ],
        }

        updated, applied = apply_ai_analysis_to_config(
            config,
            analysis,
            mode="safe",
            sections=["outline_items"],
            selection={"outline_indexes": [1]},
        )

        self.assertEqual(updated["items"][0]["assign_type"], "")
        self.assertEqual(updated["items"][0]["report_kind"], "narrative")
        self.assertEqual(updated["items"][1]["assign_type"], "user")
        self.assertEqual(updated["items"][1]["user_ids"], [10])
        self.assertTrue(updated["items"][1]["attachment_required"])
        self.assertEqual(updated["ai_last_selection"]["outline_indexes"], [1])
        self.assertTrue(any("minh chứng" in item.lower() or "phân công" in item.lower() for item in applied))

    def test_apply_analysis_can_use_global_assignment_alternative(self):
        config = {
            "title": "Biểu mẫu báo cáo",
            "summary": "Phân công toàn nhiệm vụ.",
            "collection_mode": "form",
            "domain": "",
            "priority": "Trung bình",
            "assign_type": "",
            "unit_domains": [],
            "role_ids": [],
            "user_ids": [],
            "form_fields": [{"field_label": "Tổng số hồ sơ"}],
        }
        analysis = {
            "recommended_updates": {},
            "global_assignment": {
                "assign_type": "user",
                "unit_domains": [],
                "role_ids": [],
                "user_ids": [9],
                "alternatives": [
                    {
                        "assign_type": "unit",
                        "unit_domains": ["doi-tong-hop"],
                        "role_ids": [],
                        "user_ids": [],
                        "confidence_score": 0.61,
                        "confidence_label": "cao",
                        "display_targets": ["Đội Tổng hợp"],
                        "reasons": ["Khớp với đơn vị Đội Tổng hợp."],
                    }
                ],
            },
        }

        updated, applied = apply_ai_analysis_to_config(
            config,
            analysis,
            mode="safe",
            sections=["global_assignment"],
            selection={"global_assignment_alternative_index": 0},
        )

        self.assertEqual(updated["assign_type"], "unit")
        self.assertEqual(updated["unit_domains"], ["doi-tong-hop"])
        self.assertEqual(updated["ai_last_selection"]["global_assignment_alternative_index"], 0)
        self.assertTrue(any("toàn nhiệm vụ" in item.lower() for item in applied))

    def test_apply_analysis_can_use_field_alternative(self):
        config = {
            "title": "Biểu mẫu theo đơn vị",
            "summary": "Mỗi đơn vị nhập phần mình phụ trách.",
            "collection_mode": "form",
            "domain": "",
            "priority": "Trung bình",
            "assign_type": "unit",
            "unit_domains": ["pc06"],
            "role_ids": [],
            "user_ids": [],
            "form_fields": [
                {
                    "field_label": "Chỉ tiêu theo đơn vị",
                    "field_key": "chi_tieu_don_vi",
                    "field_type": "number",
                    "field_options_text": "",
                    "target_type": "all",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [],
                }
            ],
        }
        analysis = {
            "recommended_updates": {},
            "global_assignment": {"assign_type": "unit", "unit_domains": ["pc06"], "role_ids": [], "user_ids": []},
            "form_fields": [
                {
                    "index": 0,
                    "suggestion": {
                        "target_type": "unit",
                        "target_unit_domains": ["minh-xuan"],
                        "target_role_ids": [],
                        "target_user_ids": [],
                        "confidence_score": 0.91,
                        "alternatives": [
                            {
                                "assign_type": "unit",
                                "unit_domains": ["tan-quang"],
                                "role_ids": [],
                                "user_ids": [],
                                "confidence_score": 0.64,
                                "confidence_label": "cao",
                                "display_targets": ["Công an phường Tân Quang"],
                                "reasons": ["Khớp với đơn vị Công an phường Tân Quang."],
                            }
                        ],
                    },
                }
            ],
        }

        updated, applied = apply_ai_analysis_to_config(
            config,
            analysis,
            mode="safe",
            sections=["form_fields"],
            selection={"form_field_indexes": [0], "form_field_alternative_indexes": {"0": 0}},
        )

        self.assertEqual(updated["form_fields"][0]["target_type"], "unit")
        self.assertEqual(updated["form_fields"][0]["target_unit_domains"], ["tan-quang"])
        self.assertEqual(updated["ai_last_selection"]["form_field_alternative_indexes"], {0: 0})
        self.assertTrue(any("phạm vi nhập liệu" in item.lower() for item in applied))

    def test_apply_analysis_assigns_file_field_targets_safely(self):
        config = {
            "title": "Báo cáo theo đơn vị",
            "summary": "Tổng hợp chỉ tiêu theo địa bàn.",
            "collection_mode": "file",
            "domain": "",
            "priority": "Trung bình",
            "assign_type": "unit",
            "unit_domains": ["pc06"],
            "role_ids": [],
            "user_ids": [],
            "report_fields": [
                {
                    "label": "Chỉ tiêu Công an phường Minh Xuân",
                    "key": "chi_tieu_minh_xuan",
                    "type": "number",
                    "target_type": "all",
                    "target_unit_domains": [],
                    "target_role_ids": [],
                    "target_user_ids": [],
                }
            ],
        }
        analysis = {
            "recommended_updates": {},
            "global_assignment": {
                "assign_type": "unit",
                "unit_domains": ["pc06"],
                "role_ids": [],
                "user_ids": [],
            },
            "report_fields": [
                {
                    "index": 0,
                    "suggestion": {
                        "target_type": "unit",
                        "target_unit_domains": ["minh-xuan"],
                        "target_role_ids": [],
                        "target_user_ids": [],
                        "confidence_score": 0.92,
                    },
                }
            ],
        }

        updated, applied = apply_ai_analysis_to_config(config, analysis, mode="safe")

        self.assertEqual(updated["report_fields"][0]["target_type"], "unit")
        self.assertEqual(updated["report_fields"][0]["target_unit_domains"], ["minh-xuan"])
        self.assertTrue(any("phạm vi báo cáo" in item for item in applied))


if __name__ == "__main__":
    unittest.main()
