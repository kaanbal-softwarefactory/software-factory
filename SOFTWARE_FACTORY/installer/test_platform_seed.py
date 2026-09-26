"""GitHub identity must resolve before platform configuration is sent."""
import json
import unittest
from unittest.mock import patch

import server


class GitHubIdentityTests(unittest.TestCase):
    def test_seed_reaches_api_with_resolved_identity(self):
        cfg = {"gitops_token": "synthetic", "github_org": "lab-org"}
        with patch.object(server, "_github_api", return_value=(200, {"login": "alice"})), \
             patch.object(server, "PortForward") as forward, \
             patch.object(server, "http_json", return_value=(503, {})) as post:
            forward.return_value.__enter__.return_value.ready = True
            ok, _ = server.seed_platform(cfg, "")
        self.assertFalse(ok)
        payload = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(payload["git_username"], "alice")
        self.assertEqual(payload["git_workspace"], "lab-org")
        self.assertTrue(payload["github_is_org"])
        self.assertEqual(cfg["github_login"], "alice")

    def test_validated_login_needs_no_network(self):
        with patch.object(server, "_github_api") as api:
            self.assertEqual(server._resolve_github_login({"github_login": " alice "}), "alice")
        api.assert_not_called()

    def test_token_owner_is_not_destination_org(self):
        with patch.object(server, "_github_api", return_value=(200, {"login": "alice"})) as api:
            self.assertEqual(server._resolve_github_login({
                "gitops_token": " synthetic ", "github_org": "lab-org"}), "alice")
        api.assert_called_once_with("GET", "/user", "synthetic")

    def test_missing_token_does_not_use_org(self):
        with patch.object(server, "_github_api") as api:
            self.assertEqual(server._resolve_github_login({"github_org": "lab-org"}), "")
        api.assert_not_called()

    def test_invalid_identity_stops_seed_before_posting_credentials(self):
        for response in [(401, {}), (0, {}), (200, []), (200, {}), (200, {"login": None})]:
            with self.subTest(response=response), \
                 patch.object(server, "_github_api", return_value=response), \
                 patch.object(server, "http_json") as post:
                with self.assertRaisesRegex(RuntimeError, "usuario de GitHub"):
                    server.seed_platform({"gitops_token": "synthetic"}, "")
                post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
