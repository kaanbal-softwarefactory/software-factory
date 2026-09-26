import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


SERVER = Path(__file__).with_name("server.py")


class InstallerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["KAANBAL_INSTALLER_STATE_DIR"] = str(root / "state")
        os.environ["KAANBAL_CREDENTIALS_FILE"] = str(root / "installer.env")
        spec = importlib.util.spec_from_file_location("kaanbal_installer_test", SERVER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        self.tmp.cleanup()

    def test_env_import_hides_secrets(self):
        values = self.module.parse_env_text(
            "DOMAIN=example.test\n"
            "CF_TOKEN=secret\n"
            "GITHUB_ORG=demo\n"
            "KAANBAL_ADMIN_USER=admin\n"
            "KAANBAL_ADMIN_PASS=longpassword12\n"
        )
        self.module.save_credentials(values)
        status = self.module.credentials_status()
        self.assertEqual(status["values"]["domain"], "example.test")
        self.assertIn("cf_token", status["secret_configured"])
        self.assertNotIn("cf_token", status["values"])
        if os.name != "nt":
            self.assertEqual(os.stat(self.module.CREDENTIALS_FILE).st_mode & 0o777, 0o600)

    def test_state_snapshot_omits_passwords_and_ai_keys(self):
        self.module.STATE["phase"] = "done"
        self.module.STATE["ai_providers"] = [{"provider": "x", "api_key": "secret"}]
        self.module.STATE["handoff"] = {"argocd_password": "secret", "node": "lab"}
        self.module.persist_state()
        raw = Path(self.module.STATE_FILE).read_text(encoding="utf-8")
        self.assertNotIn("secret", raw)
        self.assertIn('"phase": "done"', raw)

    def test_commands_redact_saved_tokens(self):
        self.module.save_credentials({"gitops_token": "ghp_super_secret"})
        command = "git clone https://x-access-token:ghp_super_secret@github.com/demo/repo.git"
        redacted = self.module.redact(command)
        self.assertNotIn("ghp_super_secret", redacted)
        self.assertIn("***", redacted)


if __name__ == "__main__":
    unittest.main()
