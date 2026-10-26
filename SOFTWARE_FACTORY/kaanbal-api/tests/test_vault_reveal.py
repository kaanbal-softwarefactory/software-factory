"""Revelar valores de Vault deja huella; verlos enmascarados no."""
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import mock

from app.routers import system


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"data": {"data": {"OWNER_PASSWORD": "abcdefghij", "CUSTOMER_PASSWORD": "klmnopqrst"},
                         "metadata": {"version": 3}}}


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return _Response()


class _Collection:
    async def find_one(self, *args, **kwargs):
        return {"vault_addr": "http://vault.test", "vault_token": "t"}


class VaultRevealAuditTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.audited = []
        audited = self.audited

        @asynccontextmanager
        async def fake_audit(principal, action, target, reason, **metadata):
            audited.append((principal, action, target, metadata))
            yield {}

        self.principal = SimpleNamespace(username="andres", token_id=None)
        self.request = SimpleNamespace(state=SimpleNamespace(principal=self.principal))
        for patcher in (
            mock.patch.object(system, "get_db", lambda: SimpleNamespace(system_config=_Collection())),
            mock.patch.object(system.httpx, "AsyncClient", _Client),
            mock.patch.object(system.autonomy_service, "audit", fake_audit),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_revealing_values_is_audited_with_key_names_only(self):
        result = await system.get_vault_secret("prod", "demo", self.request, reveal=True, current_user=None)
        self.assertEqual(result["data"]["OWNER_PASSWORD"], "abcdefghij")
        self.assertEqual(len(self.audited), 1)
        principal, action, target, metadata = self.audited[0]
        self.assertIs(principal, self.principal)
        self.assertEqual((action, target), ("vault.secret.reveal", "prod/demo"))
        self.assertEqual(metadata["keys"], ["CUSTOMER_PASSWORD", "OWNER_PASSWORD"])
        self.assertNotIn("abcdefghij", repr(self.audited))

    async def test_masked_view_is_not_a_reveal_and_hides_the_middle(self):
        result = await system.get_vault_secret("prod", "demo", self.request, reveal=False, current_user=None)
        self.assertEqual(self.audited, [])
        self.assertEqual(result["data"]["OWNER_PASSWORD"], "ab******ij")

    async def test_values_are_not_returned_when_the_audit_cannot_be_written(self):
        @asynccontextmanager
        async def broken_audit(*args, **kwargs):
            raise RuntimeError("mongo caído")
            yield

        with mock.patch.object(system.autonomy_service, "audit", broken_audit):
            with self.assertRaises(RuntimeError):
                await system.get_vault_secret("prod", "demo", self.request, reveal=True, current_user=None)


if __name__ == "__main__":
    unittest.main()
