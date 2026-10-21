"""Existing labels remain visible; assigning an owner never changes visibility."""
import unittest
from app.services import app_groups
from app.services.permissions import required_permission


class GroupTests(unittest.TestCase):
    def test_existing_groups_and_ungrouped_apps_are_not_lost(self):
        groups = app_groups.inventory([
            {"name": "demo-api", "app_group": "demo"},
            {"name": "demo-db", "app_group": "demo"}, {"name": "orphan"}], [])
        self.assertEqual([(g["slug"], g["app_count"]) for g in groups], [("demo", 2), ("", 1)])

    def test_owner_is_optional_filter_not_implicit_access_control(self):
        metadata = [{"_id": "demo", "owner": "developer", "name": "Demo"}, {"_id": "empty"}]
        self.assertEqual(len(app_groups.inventory([], metadata)), 2)
        self.assertEqual(app_groups.inventory([], metadata, "developer")[0]["slug"], "demo")
        self.assertEqual(app_groups.inventory([], metadata, "")[0]["slug"], "empty")

    def test_owner_changes_require_management_permission(self):
        self.assertEqual(required_permission("PUT", "/api/v1/groups/demo"), (True, "apps.apps.expose"))
        self.assertEqual(required_permission("GET", "/api/v1/groups"), (True, "apps.apps.view"))

    def test_invalid_group_keys_rejected(self):
        for slug in ["", "a/b", "$where", "Uppercase", "x" * 101]:
            self.assertFalse(app_groups.valid_slug(slug))
