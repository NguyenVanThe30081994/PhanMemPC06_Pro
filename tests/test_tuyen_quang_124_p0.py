# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import app
from models import User, db


class TuyenQuang124P0Tests(unittest.TestCase):
    """Contract cho bộ seed và phép đo P0 124 xã/phường."""

    def setUp(self):
        self.created_user_ids = []

    def tearDown(self):
        with app.app_context():
            for user_id in self.created_user_ids:
                User.query.filter_by(id=user_id).delete()
            db.session.commit()

    def test_official_fixture_has_117_communes_and_7_wards(self):
        from services.tuyen_quang_124_p0 import load_tuyen_quang_units

        units = load_tuyen_quang_units()
        self.assertEqual(len(units), 124)
        self.assertEqual(sum(item["kind"] == "phường" for item in units), 7)
        self.assertEqual(sum(item["kind"] == "xã" for item in units), 117)
        self.assertEqual(len({item["code"] for item in units}), 124)

    def test_seed_creates_one_idempotent_test_account_per_unit(self):
        from services.tuyen_quang_124_p0 import seed_tuyen_quang_test_accounts

        with app.app_context():
            result = seed_tuyen_quang_test_accounts(prefix="TEST124_")
            self.created_user_ids.extend(result["created_user_ids"])
            self.assertEqual(result["created"], 124)
            self.assertEqual(result["total"], 124)
            self.assertEqual(len(result["accounts"]), 124)
            self.assertTrue(all(account["username"].startswith("TEST124_") for account in result["accounts"]))

            rerun = seed_tuyen_quang_test_accounts(prefix="TEST124_")
            self.created_user_ids.extend(rerun["created_user_ids"])
            self.assertEqual(rerun["created"], 0)
            self.assertEqual(rerun["total"], 124)
            self.assertEqual(len({account["username"] for account in rerun["accounts"]}), 124)

    def test_p0_assignment_matrix_for_75_items_is_9300(self):
        from services.tuyen_quang_124_p0 import expected_assignment_count

        self.assertEqual(expected_assignment_count(item_count=75, unit_count=124), 9300)

    def test_outline_matrix_reuses_unit_identity_for_repeated_assignments(self):
        import services.task_pages as task_pages

        user_a = SimpleNamespace(id=101)
        user_b = SimpleNamespace(id=102)
        assignment_a = SimpleNamespace(id=1, user=user_a, user_id=101, status="assigned")
        assignment_b = SimpleNamespace(id=2, user=user_b, user_id=102, status="assigned")
        item = SimpleNamespace(report_kind="narrative")
        fake_rows = [
            {
                "item": item,
                "assignments": [assignment_a, assignment_b],
                "latest_submissions": {},
            }
        ]
        with patch.object(task_pages, "_parse_outline_item_rows", return_value=fake_rows), patch.object(
            task_pages,
            "_task_assignee_unit_name",
            side_effect=lambda user: "Đơn vị A" if user.id == 101 else "Đơn vị B",
        ) as identity_mock:
            task_pages._build_outline_progress_matrix(SimpleNamespace(), 1)
        self.assertLessEqual(identity_mock.call_count, 2)

    def test_category_resolver_is_cached_for_one_request(self):
        from category_helpers import category_resolver

        options = [{"id": 1, "code": "tq00691", "value": "tq00691", "name": "Phường Hà Giang 2"}]
        with app.test_request_context("/tasks/1"):
            first = category_resolver(options)
            second = category_resolver(list(options))
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
