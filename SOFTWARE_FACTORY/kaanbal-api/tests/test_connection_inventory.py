"""Tests for connection inventory desired/observed."""
from __future__ import annotations

import unittest

from app.services.exposure.inventory import (
    apply_observed,
    build_desired_env,
    build_desired_inventory,
    summarize_inventory,
)


class InventoryTests(unittest.TestCase):
    def test_prod_public_canonical_host_has_no_prod_prefix(self):
        row = build_desired_env(
            app_name="test-vue",
            env="prod",
            mode="public",
            public_hostname="test-vue.acmeplatform.site",
            ts_hostname="prod-test-vue",
            ts_suffix="example.ts.net",
            category="frontend",
        )
        self.assertEqual(row["desired"]["public_hostname"], "test-vue.acmeplatform.site")
        self.assertEqual(row["desired"]["channel"], "public")
        self.assertTrue(row["connection"]["public_url"].startswith("https://test-vue."))
        self.assertNotIn("prod-test-vue.softwarefactory", row["connection"]["public_url"] or "")

    def test_staging_public_uses_env_prefix(self):
        inv = build_desired_inventory(
            app_name="test-vue",
            per_env={"staging": "public", "prod": "tailscale"},
            public_host_fn=lambda e: (
                f"{e}-test-vue.acmeplatform.site" if e != "prod"
                else "test-vue.acmeplatform.site"
            ),
            ts_suffix="example.ts.net",
            category="frontend",
        )
        self.assertEqual(
            inv["by_env"]["staging"]["desired"]["hostname"],
            "staging-test-vue.acmeplatform.site",
        )
        self.assertEqual(inv["by_env"]["prod"]["desired"]["channel"], "tailscale")

    def test_public_validated_when_ingress_and_http_ok(self):
        row = build_desired_env(
            app_name="test-vue",
            env="prod",
            mode="public",
            public_hostname="test-vue.acmeplatform.site",
            ts_hostname="prod-test-vue",
            ts_suffix="x.ts.net",
            category="frontend",
        )
        row = apply_observed(
            row,
            ingress_hosts=["test-vue.acmeplatform.site"],
            http_probe={"ok": True, "status_code": 200, "detail": "HTTP 200"},
        )
        self.assertEqual(row["status"], "validated")

    def test_public_drift_when_wrong_ingress_host(self):
        row = build_desired_env(
            app_name="test-vue",
            env="prod",
            mode="public",
            public_hostname="test-vue.acmeplatform.site",
            ts_hostname="prod-test-vue",
            ts_suffix="x.ts.net",
            category="frontend",
        )
        row = apply_observed(
            row,
            ingress_hosts=["prod-test-vue.acmeplatform.site"],
            http_probe={"ok": False, "status_code": 404},
        )
        self.assertEqual(row["status"], "drift")
        self.assertIn("canonical public host", row["last_error"] or "")

    def test_tailscale_pending_without_device(self):
        row = build_desired_env(
            app_name="test-vue",
            env="staging",
            mode="tailscale",
            public_hostname="staging-test-vue.acmeplatform.site",
            ts_hostname="staging-test-vue",
            ts_suffix="x.ts.net",
            category="frontend",
        )
        row = apply_observed(
            row,
            ingress_hosts=[],
            ts={"exists": True, "ready": True},
            ts_device_listed=False,
        )
        self.assertEqual(row["status"], "pending")

    def test_summarize_inventory(self):
        inv = {
            "by_env": {
                "prod": {"status": "validated"},
                "staging": {"status": "pending"},
            }
        }
        s = summarize_inventory(inv)
        self.assertFalse(s["validated"])
        self.assertEqual(s["pending"], ["staging"])


if __name__ == "__main__":
    unittest.main()
