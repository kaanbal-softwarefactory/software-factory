"""Business credentials must fail closed, never rotate on retries or enter Git."""
import asyncio
import base64
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import business_deployer as bd


class CredentialsTests(unittest.TestCase):
    def test_vault_existing_credentials_do_not_generate_or_overwrite(self):
        import httpx
        values = {"PGPASSWORD": "CHANGE_ME"}
        calls = []
        def handle(request):
            calls.append(request.method)
            return httpx.Response(200, json={"data": {"data": values}})
        real_client = httpx.AsyncClient
        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle))
        generate = AsyncMock()
        deployer = types.SimpleNamespace(_credentials={"vault_addr": "http://vault.example.com", "vault_token": "CHANGE_ME"})
        with patch.object(bd.httpx, "AsyncClient", client):
            result = asyncio.run(bd._vault_credentials(deployer, "business-demo", generate))
        self.assertEqual(result, values)
        self.assertEqual(calls, ["GET"])
        generate.assert_not_awaited()

    def test_vault_unavailable_has_no_fallback(self):
        deployer = types.SimpleNamespace(_credentials={})
        with self.assertRaises(ValueError):
            asyncio.run(bd._vault_credentials(deployer, "business-demo", AsyncMock()))

    def test_materialized_secret_is_immutable_and_never_overwrites_conflict(self):
        from kubernetes import client, config
        data = {"PGPASSWORD": base64.b64encode(b"CHANGE_ME").decode()}
        existing = types.SimpleNamespace(data=data)
        api = types.SimpleNamespace(read_namespaced_secret=lambda *a, **kw: existing)
        with patch.object(config, "load_incluster_config"), patch.object(client, "CoreV1Api", return_value=api):
            bd.materialize_secret("business-demo", {"PGPASSWORD": "CHANGE_ME"})
            with self.assertRaises(ValueError):
                bd.materialize_secret("business-demo", {"PGPASSWORD": "CHANGE_ME_DIFFERENT"})

    def test_initial_materialization_creates_only_expected_secret(self):
        from kubernetes import client, config
        from kubernetes.client.exceptions import ApiException
        created = []
        def read(*args, **kwargs):
            raise ApiException(status=404)
        api = types.SimpleNamespace(read_namespaced_secret=read, create_namespaced_secret=lambda ns, secret, **kw: created.append((ns,secret)))
        with patch.object(config, "load_incluster_config"), patch.object(client, "CoreV1Api", return_value=api):
            bd.materialize_secret("business-demo", {"PGPASSWORD": "CHANGE_ME"})
        self.assertEqual(created[0][0], "prod")
        self.assertEqual(created[0][1].metadata.name, "business-demo-secrets")
        self.assertTrue(created[0][1].immutable)


if __name__ == "__main__":
    unittest.main()
