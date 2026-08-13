# -*- coding: utf-8 -*-
import json
import unittest
from datetime import date, datetime
from types import SimpleNamespace

from app import app
from models import Task, TaskAssignment, TaskItem, TaskSubmission, User, db

from report_cycles import (
    KIND_ONETIME,
    KIND_PERIODIC,
    KIND_MILESTONE,
    KIND_ONGOING,
    current_cycle,
    cycles_between,
    deadline_for,
    kind_from_task_type,
    normalize_config,
    parse_config,
    task_config,
)


class ReportCycleUnitTests(unittest.TestCase):
    """Kiểm thử bộ máy chu kỳ báo cáo (không cần DB)."""

    def test_kind_from_task_type(self):
        self.assertEqual(kind_from_task_type("Báo cáo đột xuất / một lần"), KIND_ONETIME)
        self.assertEqual(kind_from_task_type("Báo cáo định kỳ"), KIND_PERIODIC)
        self.assertEqual(kind_from_task_type("Báo cáo theo mốc / giai đoạn"), KIND_MILESTONE)
        self.assertEqual(kind_from_task_type("Công việc thường xuyên (duy trì)"), KIND_ONGOING)
        self.assertEqual(kind_from_task_type("Công việc thường xuyên"), KIND_ONGOING)
        self.assertEqual(kind_from_task_type(""), KIND_ONETIME)

    def test_parse_config_one_time(self):
        cfg = parse_config(
            {
                "task_type": "Báo cáo đột xuất / một lần",
                "report_deadline": "2026-09-01",
            }
        )
        self.assertEqual(cfg["kind"], KIND_ONETIME)
        self.assertEqual(cfg["deadline"], "2026-09-01")

    def test_parse_config_periodic_from_fields(self):
        cfg = parse_config(
            {
                "report_period_kind": "periodic",
                "report_period": "week",
                "report_weekday": "5",
                "report_start_date": "2026-08-01",
                "report_end_date": "2026-12-31",
            }
        )
        self.assertEqual(cfg["kind"], KIND_PERIODIC)
        self.assertEqual(cfg["period"], "week")
        self.assertEqual(cfg["weekday"], 5)
        self.assertEqual(cfg["start_date"], "2026-08-01")

    def test_parse_config_prefers_json(self):
        cfg = parse_config(
            {
                "report_period_json": json.dumps(
                    {"kind": "periodic", "period": "quarter", "day_of_month": 15},
                    ensure_ascii=False,
                ),
                "report_period_kind": "one_time",
            }
        )
        self.assertEqual(cfg["kind"], KIND_PERIODIC)
        self.assertEqual(cfg["period"], "quarter")
        self.assertEqual(cfg["day_of_month"], 15)

    def test_parse_config_milestone_dates(self):
        cfg = parse_config(
            {
                "report_period_kind": "milestone",
                "report_milestones": "30/08/2026\n15/09/2026,31/12/2026",
            }
        )
        self.assertEqual(cfg["kind"], KIND_MILESTONE)
        self.assertEqual(
            cfg["milestones"], ["2026-08-30", "2026-09-15", "2026-12-31"]
        )

    def test_current_cycle_weekly(self):
        cfg = normalize_config({"kind": "periodic", "period": "week", "weekday": 4})  # Thứ 6
        cycle = current_cycle(cfg, today=date(2026, 8, 13))  # Thứ 5
        self.assertEqual(cycle["due"], "2026-08-14")
        self.assertIn("Tuần", cycle["label"])
        self.assertFalse(cycle["overdue"])

    def test_current_cycle_weekly_overdue(self):
        cfg = normalize_config({"kind": "periodic", "period": "week", "weekday": 4})
        cycle = current_cycle(cfg, today=date(2026, 8, 15))  # Thứ 7 — hạn thứ 6 đã qua
        self.assertEqual(cycle["due"], "2026-08-14")
        self.assertTrue(cycle["overdue"])

    def test_current_cycle_monthly(self):
        cfg = normalize_config({"kind": "periodic", "period": "month", "day_of_month": 20})
        cycle = current_cycle(cfg, today=date(2026, 8, 13))
        self.assertEqual(cycle["key"], "2026-08")
        self.assertEqual(cycle["label"], "Tháng 8/2026")
        self.assertEqual(cycle["due"], "2026-08-20")

    def test_current_cycle_quarterly(self):
        cfg = normalize_config({"kind": "periodic", "period": "quarter", "day_of_month": 5})
        cycle = current_cycle(cfg, today=date(2026, 8, 13))
        self.assertEqual(cycle["key"], "2026-Q3")
        self.assertEqual(cycle["due"], "2026-09-05")
        self.assertEqual(cycle["label"], "Quý 3/2026")

    def test_current_cycle_yearly(self):
        cfg = normalize_config({"kind": "periodic", "period": "year", "month_of_year": 12, "day_of_month": 31})
        cycle = current_cycle(cfg, today=date(2026, 8, 13))
        self.assertEqual(cycle["key"], "2026")
        self.assertEqual(cycle["due"], "2026-12-31")
        self.assertEqual(cycle["label"], "Năm 2026")

    def test_current_cycle_milestone(self):
        cfg = normalize_config(
            {
                "kind": "milestone",
                "milestones": ["2026-08-30", "2026-09-15", "2026-12-31"],
            }
        )
        cycle = current_cycle(cfg, today=date(2026, 8, 13))
        self.assertEqual(cycle["key"], "M1")
        self.assertEqual(cycle["due"], "2026-08-30")
        # Sau mốc cuối -> giữ mốc cuối, đánh quá hạn
        cycle_late = current_cycle(cfg, today=date(2027, 1, 5))
        self.assertEqual(cycle_late["due"], "2026-12-31")
        self.assertTrue(cycle_late["overdue"])

    def test_current_cycle_one_time_and_ongoing(self):
        one = current_cycle(normalize_config({"kind": "one_time", "deadline": "2026-09-01"}), today=date(2026, 8, 13))
        self.assertEqual(one["due"], "2026-09-01")
        self.assertFalse(one["overdue"])

        ongoing = current_cycle(normalize_config({"kind": "ongoing"}), today=date(2026, 8, 13))
        self.assertEqual(ongoing["key"], "ongoing")
        self.assertIsNone(ongoing["due"])

    def test_deadline_for(self):
        cfg = normalize_config({"kind": "periodic", "period": "month", "day_of_month": 20})
        self.assertEqual(deadline_for(cfg, today=date(2026, 8, 13)), date(2026, 8, 20))
        cfg_ongoing = normalize_config({"kind": "ongoing"})
        self.assertIsNone(deadline_for(cfg_ongoing, today=date(2026, 8, 13)))

    def test_cycles_between_months(self):
        cfg = normalize_config({"kind": "periodic", "period": "month", "day_of_month": 5})
        cycles = cycles_between(cfg, date(2026, 8, 1), date(2026, 10, 31))
        keys = [cycle["key"] for cycle in cycles]
        self.assertEqual(keys, ["2026-08", "2026-09", "2026-10"])

    def test_task_config_legacy_fallback(self):
        # Task cũ có deadline -> vẫn là một lần, giữ nguyên hạn
        legacy = SimpleNamespace(report_period_json=None, deadline=date(2026, 9, 1), task_type="Công việc thường xuyên")
        cfg = task_config(legacy)
        self.assertEqual(cfg["kind"], KIND_ONETIME)
        self.assertEqual(cfg["deadline"], "2026-09-01")

        # Task cũ không deadline + loại định kỳ -> suy ra định kỳ
        periodic = SimpleNamespace(report_period_json=None, deadline=None, task_type="Báo cáo định kỳ")
        cfg = task_config(periodic)
        self.assertEqual(cfg["kind"], KIND_PERIODIC)

        # Task mới có report_period_json -> đọc đúng cấu hình
        new_task = SimpleNamespace(
            report_period_json=json.dumps({"kind": "periodic", "period": "year", "month_of_year": 6, "day_of_month": 30}),
            deadline=None,
            task_type="Báo cáo định kỳ",
        )
        cfg = task_config(new_task)
        self.assertEqual(cfg["kind"], KIND_PERIODIC)
        self.assertEqual(cfg["month_of_year"], 6)


class ReportCycleIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp: tạo công việc định kỳ qua wizard + gắn chu kỳ khi nộp."""

    def setUp(self):
        self.client = app.test_client()
        self.created_user_ids = []
        self.created_task_ids = []

    def tearDown(self):
        with app.app_context():
            from models import TaskComment, TaskFormField, TaskParticipant
            for task_id in self.created_task_ids:
                TaskComment.query.filter_by(task_id=task_id).delete()
                TaskAssignment.query.filter_by(task_id=task_id).update(
                    {TaskAssignment.last_submission_id: None}, synchronize_session=False
                )
                TaskSubmission.query.filter_by(task_id=task_id).delete()
                TaskAssignment.query.filter_by(task_id=task_id).delete()
                TaskItem.query.filter_by(task_id=task_id).delete()
                TaskParticipant.query.filter_by(task_id=task_id).delete()
                TaskFormField.query.filter_by(task_id=task_id).delete()
                Task.query.filter_by(id=task_id).delete()
            for user_id in self.created_user_ids:
                TaskParticipant.query.filter_by(user_id=user_id).delete()
                TaskAssignment.query.filter_by(user_id=user_id).delete()
                TaskSubmission.query.filter_by(submitted_by=user_id).delete()
                TaskComment.query.filter_by(user_id=user_id).delete()
                User.query.filter_by(id=user_id).delete()
            db.session.commit()

    def _login(self, user_id, is_admin=True):
        with app.app_context():
            user = db.session.get(User, user_id)
            with self.client.session_transaction() as sess:
                sess["uid"] = user.id
                sess["username"] = user.username
                sess["fullname"] = user.fullname
                sess["unit"] = user.unit_area or ""
                sess["unit_area"] = user.unit_area or ""
                sess["unit_area_ref"] = user.unit_area or ""
                sess["unit_key"] = user.unit_key or ""
                sess["role_id"] = user.role_id
                sess["must_change"] = False
                sess["is_admin"] = is_admin
                sess["session_version"] = int(user.session_version or 0)
                sess["csrf_token"] = "cycle-test-csrf"
                sess["last_active"] = datetime.now().timestamp()

    def _create_user(self, unit_name, unit_key):
        with app.app_context():
            user = User(
                username=f"cycle_{unit_key}_{datetime.now().microsecond}",
                fullname=f"Cán bộ {unit_name}",
                unit_area=unit_name,
                unit_key=unit_key,
                role_id=1,
                is_active=True,
            )
            user.set_password("123456")
            db.session.add(user)
            db.session.commit()
            self.created_user_ids.append(user.id)
            return user.id

    def test_create_periodic_task_and_tag_submission_cycle(self):
        with app.app_context():
            admin = (
                User.query.filter_by(username="admin").first()
                or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
            )
            admin_id = admin.id
        self._login(admin_id)
        unit_id = self._create_user("Đội A", "a")

        create_response = self.client.post(
            "/tasks",
            data={
                "task_mode": "OUTLINE",
                "title": "Wizard báo cáo định kỳ",
                "description": "Báo cáo định kỳ hàng tháng",
                "csrf_token": "cycle-test-csrf",
                "report_period_kind": "periodic",
                "report_period": "month",
                "report_day_of_month": "20",
                "item_title": ["Nội dung định kỳ"],
                "item_report_kind": ["narrative"],
                "item_assign_type": ["unit"],
                "item_domains": ["doi-a"],
                "item_role_ids": [""],
                "item_user_ids": [""],
            },
            follow_redirects=True,
        )
        self.assertEqual(create_response.status_code, 200)

        with app.app_context():
            task = (
                Task.query.filter_by(title="Wizard báo cáo định kỳ")
                .order_by(Task.id.desc())
                .first()
            )
            self.assertIsNotNone(task)
            self.created_task_ids.append(task.id)
            self.assertTrue(task.report_period_json)
            cfg = json.loads(task.report_period_json)
            self.assertEqual(cfg["kind"], "periodic")
            self.assertEqual(cfg["period"], "month")
            self.assertEqual(cfg["day_of_month"], 20)
            # Hạn nộp được tính theo chu kỳ hiện tại (ngày 20 của tháng)
            expected_deadline = deadline_for(normalize_config(cfg))
            self.assertEqual(task.deadline, expected_deadline)
            item = TaskItem.query.filter_by(task_id=task.id).first()
            item_id = item.id
            assignment = TaskAssignment.query.filter_by(task_id=task.id, task_item_id=item_id).first()
            assigned_uid = assignment.user_id
            self.assertEqual(assigned_uid, unit_id)

        self._login(assigned_uid, is_admin=False)
        submit_response = self.client.post(
            f"/tasks/{task.id}/submit_report",
            data={
                "csrf_token": "cycle-test-csrf",
                "task_item_id": str(item_id),
                "report_content": "Đã hoàn thành kỳ này.",
            },
        )
        self.assertEqual(submit_response.status_code, 302)

        with app.app_context():
            submission = (
                TaskSubmission.query.filter_by(task_id=task.id, task_item_id=item_id)
                .order_by(TaskSubmission.id.desc())
                .first()
            )
            self.assertIsNotNone(submission)
            cfg = json.loads(task.report_period_json)
            expected = current_cycle(normalize_config(cfg))
            self.assertEqual(submission.cycle_key, expected["key"])
            self.assertEqual(submission.cycle_label, expected["label"])


if __name__ == "__main__":
    unittest.main()
