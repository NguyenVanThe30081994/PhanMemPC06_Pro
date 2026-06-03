# -*- coding: utf-8 -*-
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from task_workspace import (
    build_task_detail_context,
    build_task_workspace_attrs,
    summarize_task_assignments,
    task_assignment_display_status,
    task_deadline_display,
    task_workspace_tone,
)


def _normalize_status(status):
    return "Chưa tiếp nhận" if status in {"", None, "Chưa bắt đầu"} else status


def _is_submitted(assignment):
    return str(getattr(assignment, "status", "") or "").strip().lower() in {"submitted", "completed"}


STATUS_LABELS = {
    "assigned": "Chưa tiếp nhận",
    "in_progress": "Đang thực hiện",
    "submitted": "Đã nộp",
    "returned": "Bị trả lại",
    "completed": "Hoàn thành",
    "overdue": "Quá hạn",
}


class TaskWorkspaceTests(unittest.TestCase):
    def test_task_assignment_display_status_uses_mapping_then_normalizer(self):
        self.assertEqual(
            task_assignment_display_status("submitted", STATUS_LABELS, _normalize_status),
            "Đã nộp",
        )
        self.assertEqual(
            task_assignment_display_status("Chưa bắt đầu", STATUS_LABELS, _normalize_status),
            "Chưa tiếp nhận",
        )

    def test_summarize_task_assignments_builds_progress_and_current_assignment(self):
        assignments = [
            SimpleNamespace(user_id=10, status="assigned"),
            SimpleNamespace(user_id=20, status="submitted"),
            SimpleNamespace(user_id=30, status="in_progress"),
        ]

        summary = summarize_task_assignments(assignments, 30, _is_submitted)

        self.assertEqual(summary["total_assignments"], 3)
        self.assertEqual(summary["submitted_assignments"], 1)
        self.assertEqual(summary["in_progress_assignments"], 1)
        self.assertEqual(summary["current_assignment"].user_id, 30)
        self.assertEqual(summary["progress_percent"], 33)

    def test_task_deadline_display_and_workspace_tone(self):
        today = date(2026, 6, 3)
        self.assertEqual(task_deadline_display(today, today=today), "Đến hạn hôm nay")
        self.assertEqual(task_deadline_display(today + timedelta(days=1), today=today), "Hạn ngày mai")
        self.assertEqual(task_deadline_display(today - timedelta(days=2), today=today), "Quá hạn 2 ngày")
        self.assertEqual(task_workspace_tone("Quá hạn cần xử lý"), "danger")
        self.assertEqual(task_workspace_tone("Đã hoàn tất"), "success")
        self.assertEqual(task_workspace_tone("Đang triển khai"), "warning")
        self.assertEqual(task_workspace_tone("Chưa phân công"), "muted")

    def test_build_task_detail_context_defaults_to_submit_tab_for_current_executor(self):
        today = date(2026, 6, 3)
        task = SimpleNamespace(deadline=today + timedelta(days=2))
        summary = {
            "total_assignments": 2,
            "submitted_assignments": 0,
            "in_progress_assignments": 1,
            "progress_percent": 0,
        }
        assignment = SimpleNamespace(status="assigned")

        context = build_task_detail_context(
            task,
            summary,
            "FILE",
            can_manage_task_view=False,
            can_submit=True,
            status_labels=STATUS_LABELS,
            normalize_status=_normalize_status,
            my_file_assignment=assignment,
            today=today,
        )

        self.assertEqual(context["default_tab"], "file-submit")
        self.assertEqual(context["submit_status_text"], "Chưa tiếp nhận")
        self.assertEqual(context["next_step_title"], "Tiếp nhận rồi nộp báo cáo")
        self.assertEqual(context["status_tone"], "warning")

    def test_build_task_workspace_attrs_flags_attention_for_my_overdue_task(self):
        today = date(2026, 6, 3)
        task = SimpleNamespace(
            author_id=99,
            can_edit=False,
            deadline=today - timedelta(days=1),
            is_overdue=True,
            content="Mô tả công việc rất dài" * 20,
            assignee_count=2,
            submitted_assignments=1,
            in_progress_assignments=0,
            progress_percent=50,
        )
        summary = {
            "total_assignments": 2,
            "submitted_assignments": 1,
            "in_progress_assignments": 0,
            "progress_percent": 50,
            "current_assignment": SimpleNamespace(user_id=10, status="in_progress"),
        }

        attrs = build_task_workspace_attrs(
            task,
            summary,
            current_uid=10,
            current_status_text="Đang thực hiện",
            today=today,
        )

        self.assertEqual(attrs["workspace_role"], "my")
        self.assertEqual(attrs["workspace_status_text"], "Quá hạn cần xử lý")
        self.assertEqual(attrs["workspace_tone"], "danger")
        self.assertTrue(attrs["workspace_needs_attention"])
        self.assertTrue(attrs["workspace_preview_text"].endswith("..."))


if __name__ == "__main__":
    unittest.main()
