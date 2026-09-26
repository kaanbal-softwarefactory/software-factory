"""Unit tests for EMQX Edge multi-channel exposure helpers."""
import unittest

from app.services.exposure.channels import (
    normalize_channels,
    sanitize_public_channels,
    apply_edge_profile,
    derive_env_mode,
    public_ws_hostname,
    build_port_exposure_for_envs,
)
from app.services.managed.emqx_edge import (
    is_emqx_template,
    render_bootstrap_job,
    connection_hints,
)


class TestChannels(unittest.TestCase):
    def test_normalize_string_and_list(self):
        self.assertEqual(normalize_channels("tailscale"), ["tailscale"])
        self.assertEqual(normalize_channels(["lan", "lan", "tailscale"]), ["lan", "tailscale"])
        self.assertEqual(normalize_channels({"channels": ["internal", "public"]}), ["internal", "public"])
        self.assertEqual(normalize_channels("off"), [])

    def test_forbid_public_mqtt(self):
        ch = sanitize_public_channels("mqtt", ["internal", "lan", "public", "tailscale"])
        self.assertNotIn("public", ch)
        self.assertIn("lan", ch)

    def test_allow_public_ws(self):
        ch = sanitize_public_channels("ws", ["internal", "public"])
        self.assertIn("public", ch)

    def test_edge_profile_defaults(self):
        ports = [{"name": "mqtt"}, {"name": "ws"}, {"name": "dashboard"}]
        edge = apply_edge_profile(ports)
        self.assertEqual(edge["mqtt"], ["internal", "lan", "tailscale"])
        self.assertIn("public", edge["ws"])
        self.assertNotIn("public", edge["dashboard"])

    def test_derive_env_mode_both(self):
        mode = derive_env_mode({
            "mqtt": ["lan", "tailscale"],
            "ws": ["public", "lan"],
        })
        self.assertEqual(mode, "both")

    def test_public_ws_hostname(self):
        self.assertEqual(public_ws_hostname("acuaponia-mqtt", "acmeplatform.site"), "mqtt-acuaponia-mqtt.acmeplatform.site")

    def test_build_port_exposure(self):
        pe = build_port_exposure_for_envs(["prod"], {"mqtt": ["lan", "tailscale"]})
        self.assertEqual(pe["prod"]["mqtt"], ["lan", "tailscale"])


class TestEmqxEdge(unittest.TestCase):
    def test_is_emqx(self):
        self.assertTrue(is_emqx_template("emqx"))
        self.assertFalse(is_emqx_template("n8n"))

    def test_bootstrap_job_contains_users(self):
        yaml = render_bootstrap_job("acuaponia-mqtt", topic_prefix="acuaponia")
        self.assertIn("mqtt-bootstrap", yaml)
        self.assertIn("authentication", yaml)
        self.assertIn("PostSync", yaml)

    def test_connection_hints(self):
        h = connection_hints("acuaponia-mqtt", "prod", domain="acmeplatform.site", lan_ip="192.168.1.10")
        self.assertIn("1883", h["internal"]["mqtt"])
        self.assertIn("192.168.1.10", h["lan"]["mqtt"])
        self.assertIn("wss://mqtt-acuaponia-mqtt", h["public"]["websocket"])


if __name__ == "__main__":
    unittest.main()
