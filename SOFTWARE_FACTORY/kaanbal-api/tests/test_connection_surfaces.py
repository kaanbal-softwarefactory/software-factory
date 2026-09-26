"""Tests for multi-surface connection URLs (Fase 3)."""
from __future__ import annotations

import unittest

from app.services.exposure.connection_surfaces import build_env_surfaces, infer_surfaces


class SurfacesTests(unittest.TestCase):
    def test_n8n_both_splits_editor_and_webhook(self):
        surfaces = infer_surfaces(category="workflow")
        info = build_env_surfaces(
            mode="both",
            public_hostname="n8n.acmeplatform.site",
            ts_hostname="prod-n8n",
            ts_suffix="example.ts.net",
            app_name="n8n",
            env="prod",
            surfaces=surfaces,
        )
        self.assertTrue(info["editor_url"].startswith("http://prod-n8n."))
        self.assertTrue(info["webhook_url"].startswith("https://n8n."))
        self.assertIn("/webhook/", info["webhook_url"])
        self.assertTrue(info["mcp_url"].startswith("https://n8n."))
        self.assertIn("/mcp/", info["mcp_url"])

    def test_backend_public_has_api_and_ws(self):
        info = build_env_surfaces(
            mode="public",
            public_hostname="api.acmeplatform.site",
            ts_hostname="prod-api",
            ts_suffix="example.ts.net",
            app_name="api",
            env="prod",
            category="backend",
        )
        self.assertEqual(info["api_url"], "https://api.acmeplatform.site")
        self.assertTrue(info["ws_url"].endswith("/ws"))

    def test_off_clears_urls(self):
        info = build_env_surfaces(
            mode="off",
            public_hostname="x.example.com",
            ts_hostname="dev-x",
            ts_suffix="tail.ts.net",
            app_name="x",
            env="dev",
            category="frontend",
        )
        self.assertEqual(info["status"], "off")
        self.assertIsNone(info["surfaces"]["ui"]["url"])

    def test_emqx_l4_mqtt_and_l7_dashboard(self):
        info = build_env_surfaces(
            mode="tailscale",
            public_hostname="emqx.acmeplatform.site",
            ts_hostname="prod-emqx",
            ts_suffix="example.ts.net",
            app_name="emqx",
            env="prod",
            category="iot",
            tcp_ports=[
                {"name": "mqtt", "port": 1883},
                {"name": "ws", "port": 8083},
            ],
        )
        self.assertEqual(info["surfaces"]["dashboard"]["layer"], "L7")
        self.assertTrue(info["dashboard_url"].startswith("http://prod-emqx."))
        self.assertEqual(info["tcp"]["mqtt"]["layer"], "L4")
        self.assertTrue(info["tcp"]["mqtt"]["url"].startswith("mqtt://prod-emqx-mqtt."))
        self.assertIn(":1883", info["tcp"]["mqtt"]["url"])
        self.assertEqual(info["surfaces"]["ws"]["layer"], "L4")
        self.assertTrue(info["surfaces"]["ws"]["url"].startswith("ws://"))


if __name__ == "__main__":
    unittest.main()
