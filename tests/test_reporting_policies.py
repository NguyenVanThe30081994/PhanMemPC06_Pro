# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from reporting_policies import (
    can_access_report_workspace,
    can_manage_report_templates,
    can_view_report_progress,
    filter_report_manager_users,
)


def _permission_checker(perms, module_name, action_name, is_admin=False):
    if is_admin:
        return True
    return bool((perms or {}).get(f"{module_name}:{action_name}"))


class ReportingPoliciesTests(unittest.TestCase):
    def test_can_manage_report_templates_uses_form_process(self):
        self.assertTrue(
            can_manage_report_templates({"form:process": True}, _permission_checker, is_admin=False)
        )
        self.assertFalse(
            can_manage_report_templates({"form:view": True}, _permission_checker, is_admin=False)
        )

    def test_workspace_and_progress_permissions_follow_matrix(self):
        self.assertTrue(
            can_access_report_workspace({"input:exec": True}, _permission_checker, is_admin=False)
        )
        self.assertTrue(
            can_view_report_progress({"form:process": True}, _permission_checker, is_admin=False)
        )
        self.assertFalse(
            can_view_report_progress({"task:view": True}, _permission_checker, is_admin=False)
        )

    def test_filter_report_manager_users_skips_current_user_and_keeps_processors(self):
        role_a = SimpleNamespace(perms={"form:process": True})
        role_b = SimpleNamespace(perms={"task:view": True})
        users = [
            SimpleNamespace(id=1, role=role_a),
            SimpleNamespace(id=2, role=role_b),
            SimpleNamespace(id=3, role=role_a),
        ]

        recipients = filter_report_manager_users(
            users,
            current_uid=1,
            role_permission_loader=lambda role: getattr(role, "perms", {}),
            permission_checker=_permission_checker,
            is_admin=False,
        )

        self.assertEqual([user.id for user in recipients], [3])


if __name__ == "__main__":
    unittest.main()
