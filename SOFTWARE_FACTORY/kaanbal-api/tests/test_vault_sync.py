"""
Tests de la reconciliación de secretos con Vault.

El caso real (laboratorio, 2026-09-21): el nodo se reinició, Vault quedó sellado y
north-star-bay-bd se desplegó sin guardar sus credenciales en Vault. Un backend
vinculado habría recibido credenciales vacías.

Standalone: py tests/test_vault_sync.py
"""
import asyncio
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "app.db" not in sys.modules:
    _db_stub = types.ModuleType("app.db")
    _db_stub.get_db = lambda: None
    sys.modules["app.db"] = _db_stub

from app.services import vault_sync as vs  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _secret(name, minutes_ago=0, data=None):
    return types.SimpleNamespace(
        metadata=types.SimpleNamespace(
            name=name,
            creation_timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        ),
        data=data or {"K": "dg=="},
    )


class AppSecretLookupTests(unittest.TestCase):
    def test_picks_the_newest_generated_secret(self):
        """secretGenerator deja versiones viejas hasta que ArgoCD las poda."""
        secrets = [
            _secret("north-star-bay-bd-secrets-old1111", minutes_ago=30),
            _secret("north-star-bay-bd-secrets-new2222", minutes_ago=1),
        ]
        got = vs.app_secret_from(secrets, "north-star-bay-bd")
        self.assertEqual(got.metadata.name, "north-star-bay-bd-secrets-new2222")

    def test_does_not_confuse_apps_with_shared_prefix(self):
        """north-star-bay no debe tomar el Secret de north-star-bay-bd."""
        secrets = [_secret("north-star-bay-bd-secrets-dccg9tm977")]
        self.assertIsNone(vs.app_secret_from(secrets, "north-star-bay"))

    def test_finds_its_own_secret_among_similar_names(self):
        secrets = [
            _secret("north-star-bay-bd-secrets-dccg9tm977"),
            _secret("north-star-bay-secrets-2b9kkt9h57"),
        ]
        got = vs.app_secret_from(secrets, "north-star-bay")
        self.assertEqual(got.metadata.name, "north-star-bay-secrets-2b9kkt9h57")


class PublicViewTests(unittest.TestCase):
    def test_never_exposes_secret_values(self):
        report = {"missing": [{"app": "db", "env": "prod", "keys": ["PASS"], "_data": {"PASS": "c2VjcmV0"}}]}
        view = vs.public_view(report)
        self.assertNotIn("_data", view["missing"][0])
        self.assertEqual(view["missing"][0]["keys"], ["PASS"])


class ReconcileTests(unittest.TestCase):
    def test_sealed_vault_writes_nothing(self):
        sealed = {"vault": {"reachable": True, "sealed": True}, "missing": [], "checked": False}
        with mock.patch.object(vs, "missing", new=mock.AsyncMock(return_value=sealed)):
            result = run(vs.reconcile())
        self.assertEqual(result["written"], [])
        self.assertIn("sellado", result["reason"])

    def test_writes_missing_secret_without_overwriting(self):
        """cas=0: Vault acepta la escritura solo si la ruta no existe."""
        report = {
            "vault": {"reachable": True, "sealed": False}, "checked": True,
            "missing": [{"app": "north-star-bay-bd", "env": "prod", "secret": "s",
                         "keys": ["MONGO_INITDB_ROOT_PASSWORD"],
                         "_data": {"MONGO_INITDB_ROOT_PASSWORD": "cHc="}}],
        }
        posted = []

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, **kw):
                posted.append((url, kw["json"]))
                return types.SimpleNamespace(status_code=200)

        with mock.patch.object(vs, "missing", new=mock.AsyncMock(return_value=report)), \
             mock.patch.object(vs, "_vault_config", new=mock.AsyncMock(return_value={"addr": "http://v", "token": "t"})), \
             mock.patch.object(vs.httpx, "AsyncClient", return_value=Client()):
            result = run(vs.reconcile())

        self.assertEqual(len(result["written"]), 1)
        url, body = posted[0]
        self.assertTrue(url.endswith("/v1/secret/data/prod/north-star-bay-bd"))
        self.assertEqual(body["options"], {"cas": 0})
        self.assertEqual(body["data"], {"MONGO_INITDB_ROOT_PASSWORD": "pw"})


if __name__ == "__main__":
    unittest.main()
