"""Offline security and contribution contracts; no cluster, credentials or network."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import io
import os
import shutil
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import access, permissions, autonomy_cluster as cluster, autonomy_workspace_files as files
from app.services.autonomy_policy import AutonomyError, authorize, require_elevated, safe_path
from app.services.autonomy_catalog import capabilities_for
from app.services.autonomy_github import GitHubBroker, validate_changes, repository


def actor(**kw):
    return access.Principal(username="example-agent", permissions=set(permissions.PERMISSION_KEYS), token_id="token-a", **kw)


def policy():
    return {"enabled": True, "workspace_enabled": True, "runtime_enabled": True, "host_enabled": True,
            "grants": [{"username": "example-agent", "apps": ["demo-api"], "environments": ["dev"], "nodes": ["lab-1"], "core": True}]}


class AuthorizationTests(unittest.TestCase):
    def test_owner_cannot_bypass_resource_policy(self):
        for kwargs in ({"app": "another-app", "env": "dev"}, {"app": "demo-api", "env": "prod"}):
            with self.assertRaises(AutonomyError):
                authorize(policy(), actor(superadmin=True), feature="runtime", **kwargs)
        authorize(policy(), actor(), feature="runtime", app="demo-api", env="dev")

    def test_features_disabled_by_default(self):
        with self.assertRaises(AutonomyError):
            authorize({}, actor(), feature="host", node="lab-1")

    def test_host_is_granted_by_exact_node(self):
        authorize(policy(), actor(), feature="host", node="lab-1")
        with self.assertRaises(AutonomyError):
            authorize(policy(), actor(), feature="host", node="lab-2")

    def test_token_constraint_and_expiry_are_enforced(self):
        cfg = policy()
        cfg["grants"][0]["token_id"] = "token-b"
        with self.assertRaises(AutonomyError):
            authorize(cfg, actor(), feature="workspace", app="demo-api", env="dev")
        cfg["grants"][0]["token_id"] = "token-a"
        for expiry in ("invalid", "2020-01-01T00:00:00Z", "2099-01-01T00:00:00"):
            cfg["grants"][0]["expires_at"] = expiry
            with self.assertRaises(AutonomyError):
                authorize(cfg, actor(), feature="workspace", app="demo-api", env="dev")

    def test_legacy_owner_token_is_not_elevated(self):
        with self.assertRaises(AutonomyError):
            require_elevated(actor(superadmin=True))
        require_elevated(actor(elevated=True))

    def test_discovery_hides_critical_tools_from_normal_tokens(self):
        normal = {t["name"] for t in capabilities_for(actor())["tools"]}
        elevated = {t["name"] for t in capabilities_for(actor(elevated=True))["tools"]}
        self.assertNotIn("execute_node_command", normal)
        self.assertIn("execute_node_command", elevated)
        self.assertIn("run_workspace_command", normal)

    def test_every_dynamic_route_has_matching_acl(self):
        from app.services.autonomy_catalog import TOOLS
        import re
        for tool in TOOLS:
            path = re.sub(r"\{[^}]+\}", "example", tool["path"])
            self.assertEqual(permissions.required_permission(tool["method"], "/api/v1" + path), (True, tool["permission"]))


class TokenWindowTests(unittest.TestCase):
    def test_start_expiry_revocation_and_elevated_without_expiry(self):
        now = datetime(2026, 9, 30, tzinfo=timezone.utc)
        valid = {"not_before": now, "expires_at": now + timedelta(hours=1), "elevated": True}
        self.assertTrue(access.token_is_usable(valid, now=now))
        self.assertFalse(access.token_is_usable(valid, now=now - timedelta(seconds=1)))
        self.assertFalse(access.token_is_usable(valid, now=now + timedelta(hours=1)))
        self.assertFalse(access.token_is_usable({**valid, "revoked_at": now}, now=now))
        self.assertFalse(access.token_is_usable({"elevated": True}, now=now))


class IsolationTests(unittest.TestCase):
    def test_workbench_source_edit_delete_and_diff_roundtrip(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("repo/app.py", "print('before')\n")
            archive.writestr("repo/old.txt", "retired\n")
            archive.writestr("repo/.env.example", "ignored placeholder")
        git_dir = str(Path(shutil.which("git")).parent)
        with tempfile.TemporaryDirectory() as folder, patch.object(files.os, "defpath", git_dir + os.pathsep + os.defpath):
            root = Path(folder) / "repo"
            baseline = files.dispatch({"action": "initialize", "archive": base64.b64encode(stream.getvalue()).decode()}, root)
            self.assertFalse((root / ".env.example").exists())
            self.assertEqual(files.dispatch({"action": "snapshot", "baseline": baseline["baseline"]}, root)["changes"], [])
            files.dispatch({"action": "write", "path": "app.py", "content": "print('after')\n"}, root)
            files.dispatch({"action": "write", "path": "old.txt", "content": None}, root)
            files.dispatch({"action": "write", "path": "new.txt", "content": "new file\n"}, root)
            changes = files.dispatch({"action": "snapshot", "baseline": baseline["baseline"]}, root)["changes"]
            by_path = {c["path"]: c["content"] for c in changes}
            self.assertEqual(by_path, {"app.py": "print('after')\n", "old.txt": None, "new.txt": "new file\n"})
            validate_changes(changes)

    def test_workbench_has_no_platform_credentials_or_host_access(self):
        manifest = cluster.workspace_manifest("work-example", "test/workbench:1", 600)
        spec = manifest["spec"]
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertNotIn("hostPID", spec)
        self.assertNotIn("hostNetwork", spec)
        for volume in spec["volumes"]:
            self.assertEqual(set(volume), {"name", "emptyDir"})
        security = spec["containers"][0]["securityContext"]
        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertTrue(security["readOnlyRootFilesystem"])
        self.assertEqual(security["capabilities"]["drop"], ["ALL"])

    def test_host_job_is_one_shot_and_targets_only_exact_node(self):
        manifest = cluster.host_manifest("repair-x", "test/workbench:1", "lab-1", "printf done", 12)
        self.assertEqual(manifest["spec"]["backoffLimit"], 0)
        spec = manifest["spec"]["template"]["spec"]
        self.assertEqual(spec["nodeName"], "lab-1")
        self.assertEqual(spec["containers"][0]["command"][-1], "printf done")

    def test_paths_and_repository_cannot_escape(self):
        for value in ("../x", "/tmp/x", "x/../../y", "a\\b", ".git/config", ".env", "x/key.pem", "a//b"):
            with self.assertRaises(AutonomyError):
                safe_path(value)
        with self.assertRaises(AutonomyError):
            repository("https://github.com.evil/a/b")

    def test_secrets_and_special_modes_cannot_be_published(self):
        with self.assertRaises(AutonomyError):
            validate_changes([{"path": "a.py", "mode": "120000", "content": "x"}])
        with self.assertRaises(AutonomyError):
            validate_changes([{"path": "a.py", "mode": "100644", "content": "super-sensitive-test-value"}], secrets=["super-sensitive-test-value"])
        # Source that names password fields is valid code, not a leaked secret.
        validate_changes([{"path": "a.py", "mode": "100644", "content": "password = Field(repr=False)"}])

    def test_archive_traversal_is_rejected_before_reading(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr("repo/../../escape.txt", "bad")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                files.initialize(Path(folder) / "repo", base64.b64encode(stream.getvalue()).decode())
            self.assertFalse((Path(folder) / "escape.txt").exists())


class GitHubContracts(unittest.IsolatedAsyncioTestCase):
    async def test_merge_checks_exact_head_and_never_merges_core(self):
        gh = GitHubBroker("test-credential")
        gh.request = AsyncMock()
        ws = {"target": "core"}
        with self.assertRaises(AutonomyError):
            await gh.merge(ws, "a" * 40)
        gh.request.assert_not_called()
        ws = {"target": "app", "repo": "owner/app", "branch": "codex/x", "base_branch": "main", "published_sha": "a" * 40, "pull_request": {"number": 5}}
        gh.request.return_value = {"head": {"sha": "b" * 40, "ref": "codex/x"}, "base": {"ref": "main"}, "mergeable_state": "clean"}
        with self.assertRaises(AutonomyError):
            await gh.merge(ws, "a" * 40)
        self.assertEqual(gh.request.await_count, 1)

    async def test_publish_reuses_a_branch_and_pr_after_lost_response(self):
        gh = GitHubBroker("test-credential")
        gh.request = AsyncMock(side_effect=[[{"ref": "refs/heads/codex/x", "object": {"sha": "a" * 40}}], [{"number": 5, "html_url": "https://github.com/owner/app/pull/5"}]])
        result = await gh.publish({"repo": "owner/app", "push_repo": "owner/app", "branch": "codex/x", "base_branch": "main", "target": "app"}, "a" * 40, "change", "description")
        self.assertEqual(result["number"], 5)
        self.assertTrue(all(call.args[0] == "GET" for call in gh.request.await_args_list))


if __name__ == "__main__":
    unittest.main()
