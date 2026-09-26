"""Regression cases: incomplete installations must not report success."""
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server
import unattended
import vault_bootstrap


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "recovery.json"
        self.material = {"root_token": "synthetic-root", "unseal_keys_b64": ["synthetic-key"]}

    def runner(self, initialized=False, fail_unseal=False, fail_mount=False):
        state = {"initialized": initialized, "sealed": True}
        def run(args, input_text=None):
            self.assertNotIn("synthetic-root", " ".join(args))
            self.assertNotIn("synthetic-key", " ".join(args))
            if "status" in args:
                return (2 if state["sealed"] else 0), json.dumps(state)
            if "init" in args:
                state["initialized"] = True
                return 0, json.dumps(self.material)
            command = args[-1]
            if "operator unseal" in command:
                self.assertEqual(json.loads(self.path.read_text()), self.material)
                if fail_unseal:
                    return 1, "synthetic failure"
                state["sealed"] = False
                return 0, ""
            if "secrets list" in command:
                return (1, "") if fail_mount else (0, '{"secret/":{"type":"kv","options":{"version":"2"}}}')
            self.fail("Unexpected Vault operation")
        return run

    def test_recovery_persisted_before_unseal(self):
        token = vault_bootstrap.bootstrap(self.runner(), self.path)
        self.assertEqual(token, "synthetic-root")
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_failed_unseal_raises_and_preserves_material(self):
        with self.assertRaisesRegex(RuntimeError, "desbloquearse"):
            vault_bootstrap.bootstrap(self.runner(fail_unseal=True), self.path)
        self.assertTrue(self.path.exists())

    def test_existing_vault_failed_unseal_never_returns_token(self):
        vault_bootstrap.save_recovery(self.material, self.path)
        with self.assertRaisesRegex(RuntimeError, "desbloquearse"):
            vault_bootstrap.bootstrap(self.runner(initialized=True, fail_unseal=True), self.path)

    def test_recovery_never_initializes_empty_storage(self):
        with self.assertRaisesRegex(RuntimeError, "restaura sus datos"):
            vault_bootstrap.bootstrap(self.runner(), self.path, allow_init=False)

    def test_existing_material_prevents_reinitialization(self):
        vault_bootstrap.save_recovery(self.material, self.path)
        with self.assertRaisesRegex(RuntimeError, "restaura sus datos"):
            vault_bootstrap.bootstrap(self.runner(), self.path)

    def test_kv_access_failure_is_fatal(self):
        with self.assertRaisesRegex(RuntimeError, "no autoriza"):
            vault_bootstrap.bootstrap(self.runner(fail_mount=True), self.path)


class ReadinessTests(unittest.TestCase):
    def test_shell_exposes_lan_only_when_explicit(self):
        script = (Path(__file__).parents[1] / "install.sh").read_text(encoding="utf-8")
        self.assertIn('--lan) ACCESS_MODE="lan"', script)
        self.assertIn('--tailscale) ACCESS_MODE="tailscale"', script)
        self.assertIn('KAANBAL_INSTALLER_HOST=${INSTALLER_HOST}', script)
        self.assertIn('http://%s:3000/?token=%s', script)
        self.assertIn('"http://${PROBE_HOST}:3000/"', script)
        self.assertNotIn('KAANBAL_INSTALLER_HOST=0.0.0.0', script)
        self.assertIn('tailscale ip -4', script)

    def test_agent_inherits_selected_access_address(self):
        source = (Path(__file__).parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("ACUA_HOST", "127.0.0.1")', source)
        self.assertNotIn('"ACUA_HOST": "127.0.0.1"', source)

    def test_public_bootstrap_has_scoped_clean_reset(self):
        script = (Path(__file__).parents[2] / "install.sh").read_text(encoding="utf-8")
        self.assertIn('--reset) RESET=true', script)
        self.assertIn("if $RESET && $CUSTOM_DESTINATION", script)
        self.assertIn('reset-local.sh" --yes --wipe-credentials', script)
        self.assertIn('as_root rm -rf -- "$DESTINATION"', script)
        self.assertNotIn("docker system prune", script)

    def post(self, path, payload):
        handler = object.__new__(server.Handler)
        handler.path = path
        raw = json.dumps(payload).encode()
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        handler._auth_ok = lambda: True
        handler._json = lambda status, data: (status, data)
        return handler.do_POST()

    def test_invalid_browser_install_never_saves_or_starts(self):
        with patch.object(server, "INSTALLING", False), patch.object(server, "load_credentials", return_value={}), patch.object(server, "save_credentials") as save, patch.object(server, "preflight_install", return_value=({}, ["provider rejected"])):
            status, _ = self.post("/api/install", {})
        self.assertEqual(status, 400)
        save.assert_not_called()

    def test_failed_real_login_keeps_installer_available(self):
        state = {"phase": "done", "handoff": {"engine_ready": True}, "steps": {}}
        creds = {"admin_user": "demo", "admin_pass": "synthetic-password"}
        with patch.object(server, "STATE", state), patch.object(server, "TOKEN_REVOKED", False), patch.object(server, "load_credentials", return_value=creds), patch.object(server, "confirm_admin_access", return_value=False):
            status, _ = self.post("/api/finalize", {"username": "demo", "password": "synthetic-password"})
            self.assertFalse(server.TOKEN_REVOKED)
        self.assertEqual(status, 401)

    def test_vpn_confirmation_is_required_before_finalization(self):
        state = {"phase": "done", "handoff": {"engine_ready": True, "vpn_verification_required": True}, "steps": {}}
        creds = {"admin_user": "demo", "admin_pass": "synthetic-password"}
        with patch.object(server, "STATE", state), patch.object(server, "load_credentials", return_value=creds), patch.object(server, "confirm_admin_access") as login:
            status, _ = self.post("/api/finalize", {"username": "demo", "password": "synthetic-password"})
        self.assertEqual(status, 409)
        login.assert_not_called()

    def test_incomplete_config_never_calls_providers(self):
        with patch.object(unattended, "preflight") as provider:
            _, errors = server.preflight_install({"admin_pass": "long-synthetic-password"})
        self.assertTrue(errors)
        provider.assert_not_called()

    def test_browser_preserves_ai_provider_selection(self):
        cfg, _ = unattended.normalize({"ai_providers": [{"provider": "demo", "api_key": "synthetic"}]})
        self.assertEqual(cfg["ai_providers"][0]["provider"], "demo")

    def test_grant_checks_ports_and_restrictions(self):
        wanted = {"src": ["autogroup:member"], "dst": ["tag:k8s"], "ip": ["*"]}
        self.assertFalse(server._grant_covers([{**wanted, "ip": ["tcp:80"]}], wanted))
        self.assertFalse(server._grant_covers([{**wanted, "srcPosture": ["posture:managed"]}], wanted))
        self.assertTrue(server._grant_covers([wanted], wanted))

    def test_oauth_is_not_a_connectivity_check(self):
        with patch.object(server, "http_json", return_value=(200, {"access_token": "synthetic"})):
            result = server.validate_tailscale("demo", "demo")
        self.assertTrue(result["valid"])
        self.assertNotIn("VPN lista", result["message"])

    def test_unresolved_vpn_does_not_report_healthy(self):
        with patch.object(unattended, "resolves", return_value=False):
            healthy, _ = unattended.verify({"mode": "local", "console_exposure": "tailnet",
                                            "tailscale_dns": "example.ts.net"}, {"engine_ready": True})
        self.assertFalse(healthy)

    def test_resolved_but_unreachable_vpn_does_not_report_healthy(self):
        with patch.object(unattended, "resolves", return_value=True), patch.object(server, "probe_public_url", return_value=(False, "timeout")):
            healthy, _ = unattended.verify({"mode": "local", "console_exposure": "tailnet",
                                            "tailscale_dns": "example.ts.net"}, {"engine_ready": True})
        self.assertFalse(healthy)


if __name__ == "__main__":
    unittest.main()
