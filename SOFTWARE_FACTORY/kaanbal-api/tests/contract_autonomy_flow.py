"""Offline service workflow: real file/Git operations, simulated Mongo/K8s/GitHub."""
from copy import deepcopy
from datetime import datetime
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules["app.db"] = types.SimpleNamespace(get_db=lambda: None)

from app.services import autonomy as service, autonomy_workspace_files as files, core_release
from app.services.access import Principal
from app.services.permissions import PERMISSION_KEYS
from app.services.autonomy_policy import AutonomyError


class Collection:
    def __init__(self):
        self.rows = []

    def match(self, row, query):
        for key, value in query.items():
            if key == "$or":
                if not any(self.match(row, condition) for condition in value):
                    return False
            elif isinstance(value, dict):
                if "$exists" in value and (key in row) != value["$exists"]:
                    return False
                if "$lt" in value and (key not in row or row[key] >= value["$lt"]):
                    return False
            elif row.get(key) != value:
                return False
        return True

    async def insert_one(self, doc):
        self.rows.append(deepcopy(doc))

    async def find_one(self, query):
        return next((deepcopy(row) for row in self.rows if self.match(row, query)), None)

    async def update_one(self, query, update, **kwargs):
        return await self.find_one_and_update(query, update)

    async def find_one_and_update(self, query, update, **kwargs):
        row = next((row for row in self.rows if self.match(row, query)), None)
        if row is None:
            return None
        row.update(deepcopy(update.get("$set", {})))
        for key in update.get("$unset", {}):
            row.pop(key, None)
        return deepcopy(row)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.actor = Principal(username="example-agent", token_id="token-a", permissions=set(PERMISSION_KEYS), elevated=True)
        self.db = {key: Collection() for key in ("autonomy_workspaces", "autonomy_operations", "token_activity")}
        self.config = {"autonomy": {"enabled": True, "workspace_enabled": True, "merge_enabled": True,
            "workbench_image": "local/workbench:1", "grants": [{"username": "example-agent", "token_id": "token-a",
                "apps": ["demo-api"], "environments": ["dev"], "core": True}]}}
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("repo/app.py", "print('original')\n")
        self.github = types.SimpleNamespace(token="test-provider-credential",
            base=AsyncMock(return_value={"base_sha": "a" * 40, "base_tree": "b" * 40, "base_branch": "main"}),
            contribution_target=AsyncMock(return_value="owner/app"), archive=AsyncMock(return_value=archive.getvalue()),
            commit=AsyncMock(return_value="c" * 40), publish=AsyncMock(return_value={"number": 5, "html_url": "https://github.com/owner/app/pull/5"}),
            merge=AsyncMock(return_value={"merged": True}))
        patches = [patch.object(service, "get_db", return_value=self.db),
            patch.object(service, "configuration", AsyncMock(return_value=self.config)),
            patch.object(service, "registered_app", AsyncMock(return_value={"repo_url": "owner/app"})),
            patch.object(core_release, "get_upstream", AsyncMock(return_value=("owner", "core"))),
            patch.object(service, "broker", return_value=self.github),
            patch.object(service.cluster, "create_workspace"), patch.object(service.cluster, "remove_workspace"),
            patch.object(service.cluster, "workspace_phase", return_value="Running"),
            patch.object(service.cluster, "workspace_python", side_effect=lambda pod, script, payload: files.dispatch(payload, self.root / pod)),
            patch.object(files.os, "defpath", str(Path(shutil.which("git")).parent) + os.pathsep + os.defpath)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    async def prepare(self):
        ws = await service.open_workspace(self.actor, target="app", app="demo-api", env="dev", reason="Improve app")
        await service.initialize(self.actor, ws["id"])
        await service.files(self.actor, ws["id"], path="app.py", content="print('improved')\n", write=True)
        return ws, await service.diff(self.actor, ws["id"])

    async def test_prepare_review_publish_retry_merge_and_close(self):
        ws, diff = await self.prepare()
        self.assertEqual(diff["changes"][0]["content"], "print('improved')\n")
        with self.assertRaises(AutonomyError):
            await service.publish(self.actor, ws["id"], "Improve app", "Reviewed change", "0" * 64)
        self.github.commit.assert_not_awaited()
        self.github.publish.side_effect = [AutonomyError("simulated lost response"), self.github.publish.return_value]
        with self.assertRaises(AutonomyError):
            await service.publish(self.actor, ws["id"], "Improve app", "Reviewed change", diff["digest"])
        with self.assertRaises(AutonomyError):
            await service.files(self.actor, ws["id"], path="app.py", content="unexpected", write=True)
        published = await service.publish(self.actor, ws["id"], "Improve app", "Reviewed change", diff["digest"])
        self.assertEqual(published["pull_request"]["number"], 5)
        self.github.commit.assert_awaited_once()
        self.assertTrue((await service.merge(self.actor, ws["id"], "c" * 40))["merged"])
        self.assertEqual((await service.close(self.actor, ws["id"]))["state"], "closed")
        events = self.db["token_activity"].rows
        self.assertTrue(any(event["action"] == "workspace.merge" for event in events))
        self.assertTrue(all(event["credential_id"] == "token-a" for event in events))

    async def test_workspace_rechecks_credential_policy_expiry_and_concurrency(self):
        ws, _ = await self.prepare()
        with self.assertRaises(AutonomyError):
            await service.diff(Principal(username="example-agent", token_id="other", permissions=set(PERMISSION_KEYS)), ws["id"])
        self.config["autonomy"]["grants"] = []
        with self.assertRaises(AutonomyError):
            await service.diff(self.actor, ws["id"])
        self.config["autonomy"]["grants"] = [{"username": "example-agent", "apps": ["demo-api"], "environments": ["dev"]}]
        document = self.db["autonomy_workspaces"].rows[0]
        document["busy_until"] = datetime(2099, 1, 1)
        with self.assertRaises(AutonomyError):
            await service.diff(self.actor, ws["id"])
        document.pop("busy_until")
        document["expires_at"] = datetime(2020, 1, 1)
        with self.assertRaises(AutonomyError) as error:
            await service.diff(self.actor, ws["id"])
        self.assertEqual(error.exception.status, 410)


if __name__ == "__main__":
    unittest.main()
