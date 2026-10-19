"""HTTP boundaries for critical tokens and autonomy, with external I/O mocked."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules["app.db"] = types.SimpleNamespace(get_db=lambda: None)
sys.modules["app.config"] = types.SimpleNamespace(settings=types.SimpleNamespace(SECRET_KEY="test-only-signing-key"))

async def current_user():
    return types.SimpleNamespace(username="admin")

sys.modules["app.routers.auth"] = types.SimpleNamespace(get_current_active_user=current_user, get_password_hash=lambda x: x, verify_password=lambda clear, hashed: clear == "test-password" and hashed == "test-hash")
sys.modules["app.services.activity_log"] = types.SimpleNamespace(activity_log=types.SimpleNamespace(log=AsyncMock()), CATEGORY_AUTH="auth")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.middleware import acl
from app.routers import security, autonomy
from app.services import access, autonomy as service, step_up
from app.services.permissions import PERMISSION_KEYS


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.actor = access.Principal(username="admin", permissions=set(PERMISSION_KEYS))
        self.authenticate = patch.object(acl, "authenticate", AsyncMock(side_effect=lambda _: self.actor))
        self.authenticate.start()
        self.addCleanup(self.authenticate.stop)
        app = FastAPI()
        app.include_router(security.router, prefix="/api/v1/security")
        app.include_router(autonomy.router, prefix="/api/v1/autonomy")
        app.add_middleware(acl.AccessControlMiddleware)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def payload(self):
        return {"name": "Critical incident", "admin_username": "admin", "admin_password": "test-password", "risk_acknowledged": True,
                "expires_in_days": None, "not_before": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}

    def test_critical_token_requires_ack_password_and_session(self):
        with patch.object(step_up, "confirm", AsyncMock()) as confirm, patch.object(security.access_store, "create_token", AsyncMock(return_value={"id": "new"})) as create:
            response = self.client.post("/api/v1/security/tokens/elevated", json={**self.payload(), "risk_acknowledged": False})
            self.assertEqual(response.status_code, 403)
            create.assert_not_awaited()
            response = self.client.post("/api/v1/security/tokens/elevated", json=self.payload())
            self.assertEqual(response.status_code, 201)
            confirm.assert_awaited_once()
            self.assertTrue(create.await_args.kwargs["elevated"])
            self.assertEqual(create.await_args.kwargs["scopes"], sorted(PERMISSION_KEYS))

    def test_critical_token_is_permanent_only_on_purpose_and_dated_ones_last_24_hours(self):
        """El owner puede crear control total sin vencimiento, pero solo pidiéndolo de forma expresa."""
        with patch.object(step_up, "confirm", AsyncMock()), patch.object(security.access_store, "create_token", AsyncMock(return_value={"id": "new"})) as create:
            for updates in ({"expires_at": None}, {"expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}):
                response = self.client.post("/api/v1/security/tokens/elevated", json={**self.payload(), **updates})
                self.assertEqual(response.status_code, 422)
            create.assert_not_awaited()
            permanent = self.client.post("/api/v1/security/tokens/elevated",
                                         json={**self.payload(), "expires_at": None, "no_expiry_acknowledged": True})
            self.assertEqual(permanent.status_code, 201, permanent.text)
            self.assertIsNone(create.await_args.kwargs["expires_at"])
            self.assertTrue(create.await_args.kwargs["elevated"])
            self.assertIn("sin vencimiento", permanent.json()["warning"])

    def test_normal_permanent_token_requires_explicit_warning_ack(self):
        body = {"name": "Normal agent", "scopes": ["apps.apps.view"], "expires_in_days": None}
        with patch.object(security.access_store, "create_token", AsyncMock(return_value={"id": "normal"})) as create:
            self.assertEqual(self.client.post("/api/v1/security/tokens", json=body).status_code, 422)
            self.assertEqual(self.client.post("/api/v1/security/tokens", json={**body, "no_expiry_acknowledged": True}).status_code, 201)
            self.assertIsNone(create.await_args.kwargs["expires_at"])

    def test_unauthorized_execution_never_reaches_cluster(self):
        self.actor.permissions = {"autonomy.tools.view"}
        with patch.object(service.cluster, "app_execute") as execute:
            result = self.client.post("/api/v1/autonomy/apps/demo-api/execute", json={"command": "echo ok", "reason": "Diagnosis"})
            self.assertEqual(result.status_code, 403)
            execute.assert_not_called()

    def test_owner_without_resource_grant_is_denied(self):
        with patch.object(service, "configuration", AsyncMock(return_value={})), patch.object(service.cluster, "app_execute") as execute:
            result = self.client.post("/api/v1/autonomy/apps/demo-api/execute", json={"command": "echo ok", "reason": "Diagnosis"})
            self.assertEqual(result.status_code, 403)
            execute.assert_not_called()

    def test_validation_errors_remain_422(self):
        result = self.client.post("/api/v1/autonomy/apps/demo-api/execute", json={"command": "echo ok", "reason": "Diagnosis", "timeout_seconds": 9999})
        self.assertEqual(result.status_code, 422)

    def test_discovery_contains_complete_argument_schemas(self):
        response = self.client.get("/api/v1/autonomy/capabilities")
        self.assertEqual(response.status_code, 200)
        for tool in response.json()["tools"]:
            self.assertEqual(set(tool["input_schema"]["properties"]), set(tool["path_args"] + tool["query_args"] + tool["body_args"]))
        by_name = {tool["name"]: tool for tool in response.json()["tools"]}
        self.assertIn("ref", by_name["platform_upgrade"]["input_schema"]["properties"])

    def test_denied_token_calls_are_logged_without_request_body(self):
        self.actor = access.Principal(username="admin", token_id="audit-token", permissions=set())
        db = MagicMock()
        record = db.__getitem__.return_value.insert_one = AsyncMock()
        with patch.object(acl, "get_db", return_value=db):
            response = self.client.post("/api/v1/autonomy/apps/demo-api/execute", json={"command": "sensitive data", "reason": "Diagnosis"})
        self.assertEqual(response.status_code, 403)
        record.assert_awaited_once()
        entry = record.await_args.args[0]
        self.assertEqual(entry["credential_id"], "audit-token")
        self.assertEqual(entry["status"], 403)
        self.assertNotIn("sensitive data", str(entry))

    def test_tokens_cannot_reauthenticate_or_create_critical_tokens(self):
        principal = access.Principal(username="admin", token_id="old", elevated=True)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(step_up.confirm(principal, "admin", "test-password", action="critical"))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_step_up_checks_database_password_and_rate_limits(self):
        counter = types.SimpleNamespace(create_index=AsyncMock(), find_one_and_update=AsyncMock(return_value={"count": 1}))
        db = MagicMock()
        db.__getitem__.return_value = counter
        db.users = types.SimpleNamespace(find_one=AsyncMock(return_value={"hashed_password": "test-hash"}))
        with patch.object(step_up, "get_db", return_value=db):
            with self.assertRaises(Exception) as error:
                asyncio.run(step_up.confirm(self.actor, "admin", "wrong", action="critical"))
            self.assertEqual(error.exception.status_code, 403)
            self.assertEqual(asyncio.run(step_up.confirm(self.actor, "admin", "test-password", action="critical"))["method"], "password")
            counter.find_one_and_update.return_value = {"count": 6}
            with self.assertRaises(Exception) as error:
                asyncio.run(step_up.confirm(self.actor, "admin", "test-password", action="critical"))
            self.assertEqual(error.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
