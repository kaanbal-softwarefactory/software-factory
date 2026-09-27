"""
Tests del lanzamiento del upgrade desde la consola (ADR-002).

  1. El Job corre con su propia ServiceAccount, sin reintentos ciegos.
  2. El ref y la org nunca se interpolan en el script (no inyección).
  3. Un solo upgrade a la vez.
  4. La imagen de herramientas se alinea con la versión del clúster.

Standalone: py tests/test_core_upgrade.py
"""
import asyncio
import os
import sys
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "app.db" not in sys.modules:
    _db_stub = types.ModuleType("app.db")
    _db_stub.get_db = lambda: None
    sys.modules["app.db"] = _db_stub

from app.services import core_upgrade as cu  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class ManifestTests(unittest.TestCase):
    def _manifest(self, **overrides):
        args = dict(name="kaanbal-upgrade-1", org="northwindlearning", ref="main",
                    actor="alice", image="alpine/k8s:1.36.0")
        args.update(overrides)
        return cu.build_job_manifest(**args)

    def test_runs_with_dedicated_service_account_and_no_retries(self):
        spec = self._manifest()["spec"]
        self.assertEqual(spec["template"]["spec"]["serviceAccountName"], "kaanbal-upgrader")
        self.assertEqual(spec["backoffLimit"], 0)
        self.assertEqual(spec["template"]["spec"]["restartPolicy"], "Never")
        self.assertIn("activeDeadlineSeconds", spec)

    def test_ref_and_org_travel_as_env_not_inside_the_script(self):
        container = self._manifest(ref="feature/x")["spec"]["template"]["spec"]["containers"][0]
        script = container["command"][2]
        self.assertNotIn("feature/x", script)
        self.assertNotIn("northwindlearning", script)
        env = {e["name"]: e["value"] for e in container["env"]}
        self.assertEqual(env["UPGRADE_REF"], "feature/x")
        self.assertEqual(env["KAANBAL_ORG"], "northwindlearning")
        self.assertEqual(env["KAANBAL_UPGRADE_REEXEC"], "1")

    def test_rejects_refs_that_could_break_out_of_the_shell(self):
        for bad in ("main; rm -rf /", "$(whoami)", "`id`", "-x", "", "a b"):
            with self.assertRaises(cu.UpgradeError, msg=bad):
                self._manifest(ref=bad)

    def _env(self, manifest):
        container = manifest["spec"]["template"]["spec"]["containers"][0]
        return {e["name"]: e["value"] for e in container["env"]}

    def test_the_official_repo_is_cloned_by_default(self):
        self.assertEqual(
            self._env(self._manifest())["UPSTREAM_REPO"],
            "https://github.com/kaanbal-softwarefactory/software-factory.git",
        )

    def test_clones_the_upstream_the_cell_is_configured_for(self):
        manifest = self._manifest(upstream_repo="https://github.com/acme/fork.git")
        self.assertEqual(self._env(manifest)["UPSTREAM_REPO"], "https://github.com/acme/fork.git")
        self.assertEqual(
            manifest["metadata"]["annotations"]["kaanbal-engine.io/upstream"],
            "https://github.com/acme/fork.git",
        )

    def test_the_upstream_never_travels_inside_the_script(self):
        script = self._manifest(upstream_repo="https://github.com/acme/fork.git")[
            "spec"]["template"]["spec"]["containers"][0]["command"][2]
        self.assertNotIn("acme/fork", script)

    def test_rejects_upstreams_that_are_not_github_https_repos(self):
        for bad in ("http://github.com/a/b.git", "https://evil.example/a/b.git", "https://github.com/a/b",
                    "git@github.com:a/b.git", "https://github.com/a/b.git; rm -rf /",
                    "https://github.com/a/b.git\nx", "https://user:pw@github.com/a/b.git", ""):
            with self.assertRaises(cu.UpgradeError, msg=bad):
                self._manifest(upstream_repo=bad)

    def test_rejects_invalid_org(self):
        for bad in ("org; id", "../x", ""):
            with self.assertRaises(cu.UpgradeError, msg=bad):
                self._manifest(org=bad)

    def test_labels_identify_upgrade_jobs(self):
        manifest = self._manifest()
        self.assertEqual(manifest["metadata"]["labels"][cu.COMPONENT_LABEL], cu.COMPONENT_VALUE)


class ToolsImageTests(unittest.TestCase):
    def test_aligns_with_cluster_minor_version(self):
        self.assertEqual(cu.tools_image_for("v1.36.4+k3s1"), "alpine/k8s:1.36.0")
        self.assertEqual(cu.tools_image_for("v1.35.2"), "alpine/k8s:1.35.0")

    def test_unknown_version_uses_tested_tag(self):
        self.assertEqual(cu.tools_image_for(None), f"alpine/k8s:{cu.TOOLS_FALLBACK_TAG}")


def _job(name, *, active=False, succeeded=None, failed=None):
    return types.SimpleNamespace(
        metadata=types.SimpleNamespace(
            name=name, annotations={}, creation_timestamp=datetime.now(timezone.utc),
        ),
        status=types.SimpleNamespace(
            succeeded=succeeded, failed=failed, active=1 if active else None,
            start_time=None, completion_time=None,
        ),
    )


class FakeBatch:
    def __init__(self, jobs):
        self.jobs = jobs
        self.created = []

    def list_namespaced_job(self, namespace, label_selector=None):
        return types.SimpleNamespace(items=self.jobs)

    def create_namespaced_job(self, namespace, body):
        self.created.append(body)


class FakeDB:
    def __init__(self, config):
        async def find_one(*a, **kw):
            return config
        self.system_config = types.SimpleNamespace(find_one=find_one)


class NotFound(Exception):
    status = 404


class FakeCore:
    """El ConfigMap del candado: existe solo mientras corre un upgrade."""

    def __init__(self, lock=None):
        self.lock = lock

    def read_namespaced_config_map(self, name, namespace):
        if self.lock is None:
            raise NotFound()
        return types.SimpleNamespace(data=self.lock)


class StartUpgradeTests(unittest.TestCase):
    def _start(self, jobs, config=None, lock=None):
        batch = FakeBatch(jobs)
        version = types.SimpleNamespace(get_code=lambda: types.SimpleNamespace(git_version="v1.36.4+k3s1"))
        db = FakeDB(config if config is not None else {"github_org": "northwindlearning"})
        with mock.patch.object(cu, "get_db", return_value=db), \
             mock.patch.object(cu, "_clients", return_value=(batch, FakeCore(lock), version)):
            result = run(cu.start_upgrade(actor="alice"))
        return batch, result

    def test_refuses_while_the_node_script_holds_the_lock(self):
        """El script del nodo no crea Jobs: sin el candado, el botón lanzaría un segundo upgrade."""
        lock = {"holder": "nodo-1234", "since": str(int(time.time()) - 120)}
        with self.assertRaises(cu.UpgradeError) as ctx:
            self._start([], lock=lock)
        self.assertIn("nodo-1234", str(ctx.exception))

    def test_an_expired_lock_does_not_block(self):
        lock = {"holder": "nodo-1234", "since": str(int(time.time()) - cu.LOCK_TTL_SECONDS - 60)}
        batch, _ = self._start([], lock=lock)
        self.assertEqual(len(batch.created), 1)

    def test_refuses_while_another_upgrade_runs(self):
        """Dos upgrades a la vez dejarían infra-gitops en un estado irreversible."""
        with self.assertRaises(cu.UpgradeError):
            self._start([_job("kaanbal-upgrade-1", active=True)])

    def test_finished_upgrades_do_not_block(self):
        batch, result = self._start([_job("kaanbal-upgrade-1", succeeded=1),
                                     _job("kaanbal-upgrade-0", failed=1)])
        self.assertEqual(len(batch.created), 1)
        self.assertEqual(result["state"], "running")
        image = batch.created[0]["spec"]["template"]["spec"]["containers"][0]["image"]
        self.assertEqual(image, "alpine/k8s:1.36.0")

    def test_requires_github_org(self):
        with self.assertRaises(cu.UpgradeError):
            self._start([], config={})

    def test_uses_the_upstream_configured_in_the_cell(self):
        batch, result = self._start([], config={"github_org": "acme", "core_upstream": "acme/fork"})
        container = batch.created[0]["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e["value"] for e in container["env"]}
        self.assertEqual(env["UPSTREAM_REPO"], "https://github.com/acme/fork.git")
        self.assertEqual(result["upstream"], "acme/fork")

    def test_without_configuration_it_uses_the_official_repo(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("KAANBAL_UPSTREAM", None)
            _, result = self._start([])
        self.assertEqual(result["upstream"], "kaanbal-softwarefactory/software-factory")


class LockHolderTests(unittest.TestCase):
    NOW = 1_800_000_000

    def test_no_lock_means_free(self):
        self.assertIsNone(cu.lock_holder(None, now=self.NOW))
        self.assertIsNone(cu.lock_holder({}, now=self.NOW))

    def test_a_fresh_lock_names_who_holds_it(self):
        got = cu.lock_holder({"holder": "kaanbal-upgrade-1-abc", "since": str(self.NOW - 600)}, now=self.NOW)
        self.assertIn("kaanbal-upgrade-1-abc", got)
        self.assertIn("10 min", got)

    def test_an_abandoned_lock_expires(self):
        stale = {"holder": "x", "since": str(self.NOW - cu.LOCK_TTL_SECONDS - 1)}
        self.assertIsNone(cu.lock_holder(stale, now=self.NOW))

    def test_a_malformed_lock_is_ignored(self):
        self.assertIsNone(cu.lock_holder({"holder": "x", "since": "ayer"}, now=self.NOW))

    def test_the_api_and_the_script_agree_on_the_lock(self):
        """Si el nombre o la caducidad divergieran, el botón no vería el candado del nodo."""
        script = (Path(__file__).resolve().parents[2] / "tools" / "core-upgrade.sh").read_text(encoding="utf-8")
        self.assertIn(f"LOCK_NAME={cu.LOCK_NAME}\n", script.replace("\r\n", "\n"))
        self.assertIn(f"LOCK_TTL_SECONDS=${{LOCK_TTL_SECONDS:-{cu.LOCK_TTL_SECONDS}}}", script)


if __name__ == "__main__":
    unittest.main()
