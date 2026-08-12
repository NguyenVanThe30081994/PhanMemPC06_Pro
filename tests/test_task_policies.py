# -*- coding: utf-8 -*-
import json
import unittest
from types import SimpleNamespace

from task_policies import (
    assignment_scope_payload,
    build_scope_summary,
    can_delete_task,
    can_manage_task,
    can_view_task,
    can_watch_task,
    load_assignment_scope,
    load_manager_scope,
    load_viewer_scope,
    scope_preview_names,
    store_assignment_scope,
    store_manager_scope,
    store_viewer_scope,
)


class TaskPoliciesTests(unittest.TestCase):
    def test_assignment_scope_payload_normalizes_mode_and_ids(self):
        payload = assignment_scope_payload("role", domain="  PC06 ", role_ids=["3", "1", "3"], user_ids=["9"])
        self.assertEqual(payload["mode"], "role")
        self.assertEqual(payload["domain"], "PC06")
        self.assertEqual(payload["role_ids"], [1, 3])
        self.assertEqual(payload["user_ids"], [])

    def test_load_and_store_scope_payloads_roundtrip(self):
        task = SimpleNamespace(assign_type="", domain="Đội 1")

        stored_assignment = store_assignment_scope(task, "user", domain="Đội 1", role_ids=["5"], user_ids=["8", "2", "8"])
        stored_viewer = store_viewer_scope(task, "role", role_ids=["7", "4"])
        stored_manager = store_manager_scope(task, "user", user_ids=["15"])

        self.assertEqual(load_assignment_scope(task), stored_assignment)
        self.assertEqual(load_viewer_scope(task), stored_viewer)
        self.assertEqual(load_manager_scope(task), stored_manager)
        self.assertEqual(json.loads(task.assignment_scope_json)["user_ids"], [2, 8])

    def test_load_assignment_scope_falls_back_to_assign_type_when_json_invalid(self):
        task = SimpleNamespace(assign_type="unit", domain="Đội 2", assignment_scope_json="{invalid}")
        self.assertEqual(
            load_assignment_scope(task),
            {"mode": "unit", "domain": "Đội 2", "role_ids": [], "user_ids": []},
        )

    def test_scope_summary_compacts_names(self):
        summary = build_scope_summary(
            {"mode": "user", "user_ids": [1, 2, 3]},
            user_lookup={1: "An", 2: "Bình", 3: "Cường"},
        )
        self.assertEqual(summary["mode_label"], "Theo cá nhân")
        self.assertEqual(summary["value_label"], "An, Bình +1")
        self.assertEqual(scope_preview_names([], empty_label="Trống"), "Trống")

    def test_can_manage_and_watch_inherit_from_parent_scope(self):
        user = SimpleNamespace(id=20, role_id=8)
        parent_task = SimpleNamespace(author_id=99, manager_scope_json='{"mode":"user","user_ids":[20]}', viewer_scope_json="")
        child_task = SimpleNamespace(author_id=99, manager_scope_json="", viewer_scope_json="", parent_task=parent_task)

        self.assertTrue(
            can_manage_task(
                child_task,
                session_uid=20,
                is_admin=False,
                can_process_module=False,
                load_manager_scope_fn=load_manager_scope,
                user=user,
                load_parent_task_fn=lambda task: getattr(task, "parent_task", None),
            )
        )

        parent_task.viewer_scope_json = '{"mode":"role","role_ids":[8]}'
        self.assertTrue(
            can_watch_task(
                child_task,
                load_viewer_scope_fn=load_viewer_scope,
                user=user,
                load_parent_task_fn=lambda task: getattr(task, "parent_task", None),
            )
        )

    def test_can_view_and_delete_use_composed_flags(self):
        task = SimpleNamespace(author_id=40)

        self.assertTrue(
            can_view_task(
                task,
                session_uid=10,
                is_admin=False,
                is_lead=False,
                is_executor=False,
                can_manage=False,
                can_watch=False,
                has_visible_child_tasks=True,
            )
        )
        # is_lead (quyền xử lý module) KHÔNG còn đủ để xóa việc của người khác;
        # chỉ admin, người tạo hoặc người được ủy quyền manage mới xóa được.
        self.assertFalse(
            can_delete_task(
                task,
                session_uid=10,
                is_admin=False,
                is_lead=True,
                can_manage=False,
            )
        )
        self.assertTrue(
            can_delete_task(
                task,
                session_uid=10,
                is_admin=False,
                is_lead=True,
                can_manage=True,
            )
        )
        self.assertTrue(
            can_delete_task(
                task,
                session_uid=40,
                is_admin=False,
                is_lead=False,
                can_manage=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
