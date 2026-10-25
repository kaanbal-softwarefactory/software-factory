"""Conexión GitHub personal: cifrado, quién puede conectarla y qué se expone."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import github_accounts as accounts
from app.services.access import Principal
from app.services.autonomy_policy import AutonomyError

TOKEN = "ghp_" + "x" * 36


class Store:
    def __init__(self):
        self.rows = {}

    async def replace_one(self, query, doc, upsert=False):
        self.rows[query["_id"]] = dict(doc)

    async def find_one(self, query):
        return self.rows.get(query["_id"])

    async def delete_one(self, query):
        self.rows.pop(query["_id"], None)


class Response:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body


class GitHubAccountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store()
        db = {accounts.COLLECTION: self.store}
        for item in (patch.object(accounts, "get_db", return_value=db),):
            item.start()
            self.addCleanup(item.stop)
        self.person = Principal(username="andres")

    def test_sealed_token_is_not_readable_and_round_trips(self):
        blob = accounts.seal(TOKEN)
        self.assertNotIn(TOKEN, blob)
        self.assertEqual(accounts.unseal(blob), TOKEN)
        with self.assertRaises(AutonomyError):
            accounts.unseal("not-a-sealed-token")

    async def test_person_connects_and_status_never_returns_the_token(self):
        github = AsyncMock(return_value=Response(200, {"login": "andres-gh", "name": "Andrés"}, {"x-oauth-scopes": "repo, workflow"}))
        with patch.object(accounts, "_github", github):
            result = await accounts.connect(self.person, TOKEN)
        self.assertEqual((result["login"], result["scopes"], result["token_hint"]), ("andres-gh", ["repo", "workflow"], "xxxx"))
        self.assertNotIn(TOKEN, str(result))
        self.assertNotIn(TOKEN, str(self.store.rows))  # guardado cifrado
        self.assertNotIn(TOKEN, str(await accounts.status(self.person)))
        self.assertEqual(await accounts.token_for("andres"), TOKEN)
        await accounts.disconnect(self.person)
        self.assertFalse((await accounts.status(self.person))["connected"])
        with self.assertRaises(AutonomyError):
            await accounts.token_for("andres")

    async def test_agent_tokens_cannot_connect_and_bad_tokens_are_rejected(self):
        with self.assertRaises(AutonomyError) as error:
            await accounts.connect(Principal(username="andres", token_id="t1"), TOKEN)
        self.assertEqual(error.exception.status, 403)
        with self.assertRaises(AutonomyError):
            await accounts.connect(self.person, "not-a-token")
        with patch.object(accounts, "_github", AsyncMock(return_value=Response(401, {}))), self.assertRaises(AutonomyError):
            await accounts.connect(self.person, TOKEN)
        self.assertEqual(self.store.rows, {})

    async def test_repositories_are_filtered_and_summarized(self):
        self.store.rows["andres"] = {"token": accounts.seal(TOKEN)}
        repos = [{"full_name": "siboenglishnest/site", "private": True, "default_branch": "main", "permissions": {"push": True}},
                 {"full_name": "other/lib", "private": False, "default_branch": "dev", "permissions": {}}]
        with patch.object(accounts, "_github", AsyncMock(return_value=Response(200, repos))):
            result = await accounts.repositories(self.person, "sibo")
        self.assertEqual(result["repos"], [{"repo": "siboenglishnest/site", "private": True, "default_branch": "main",
                                            "can_push": True, "pushed_at": None}])


if __name__ == "__main__":
    unittest.main()
