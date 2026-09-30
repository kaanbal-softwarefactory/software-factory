"""POST /mcp de punta a punta: HTTP, permisos y el viaje de vuelta a la REST.

La REST de estas pruebas es falsa, pero el camino es el real: el router del MCP
llama a la app en proceso con el mismo encabezado Authorization que recibió.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.routers import mcp as mcp_router  # noqa: E402
from app.services import access  # noqa: E402

TOKENS = {
    "Bearer kbl_ingeniero_x": access.Principal(username="ana", permissions={"autonomy.tools.view"},
                                               token_id="4", token_name="ingeniero"),
    "Bearer kbl_lector_x": access.Principal(username="ana", permissions={"apps.apps.view"},
                                            token_id="1", token_name="lectura"),
    "Bearer kbl_dueno_x": access.Principal(username="ana", permissions={"apps.apps.view", "apps.variables.manage",
                                                                        "apps.apps.expose", "links.links.manage"},
                                           token_id="2", token_name="todo"),
    "Bearer kbl_nada_x": access.Principal(username="ana", permissions=set(), token_id="3", token_name="vacio"),
}


def build_app():
    app = FastAPI()
    seen = []

    @app.middleware("http")
    async def fake_acl(request: Request, call_next):
        principal = TOKENS.get(request.headers.get("authorization", ""))
        if principal is None:
            return JSONResponse({"detail": "sin sesión"}, status_code=401)
        request.state.principal = principal
        return await call_next(request)

    @app.get("/api/v1/apps")
    async def apps(request: Request):
        seen.append(request.headers.get("authorization"))
        return [{"name": "shop-api", "domain": {"fqdn": "shop.example.com"}}]

    @app.get("/api/v1/autonomy/operations/{operation_id}")
    async def operation(operation_id: str, request: Request):
        seen.append(request.headers.get("authorization"))
        return {"id": operation_id, "state": "succeeded"}

    @app.put("/api/v1/apps/{name}/variables/{variable}")
    async def put_variable(name: str, variable: str, request: Request):
        seen.append(await request.json())
        return {"app": name, "variable": variable, "committed": True}

    @app.post("/api/v1/apps/{name}/homepage")
    async def homepage(name: str, request: Request, dry_run: bool = False, plan_id: str = None):
        seen.append({"dry_run": dry_run, "plan_id": plan_id})
        if dry_run:
            return {"dry_run": True, "plan": {"action": "set_homepage", "app": name}, "plan_id": "0123456789abcdef"}
        if plan_id != "0123456789abcdef":
            return JSONResponse({"detail": "El plan cambió desde que lo viste."}, status_code=409)
        return JSONResponse({"app": name, "promotion": {"state": "running"}}, status_code=202)

    @app.delete("/api/v1/apps/{name}/links/{to}")
    async def unlink(name: str, to: str, dry_run: bool = False):
        seen.append({"delete": f"{name}->{to}", "dry_run": dry_run})
        return {"dry_run": True, "plan": {"action": "unlink_apps"}, "plan_id": "fedcba9876543210"}

    app.include_router(mcp_router.router)
    return app, seen


def rpc(method, params=None, message_id=1):
    return {"jsonrpc": "2.0", "id": message_id, "method": method, **({"params": params} if params else {})}


class McpHttpTests(unittest.TestCase):
    def setUp(self):
        self.app, self.seen = build_app()
        self.client = TestClient(self.app)

    def post(self, body, token="Bearer kbl_lector_x", **headers):
        return self.client.post("/mcp", json=body, headers={"Authorization": token, **headers})

    def test_initialize(self):
        response = self.post(rpc("initialize", {"protocolVersion": "2025-06-18"}))
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "kaanbal")

    def test_a_notification_is_accepted_without_a_body(self):
        response = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b"")

    def test_no_stream_and_no_sessions(self):
        headers = {"Authorization": "Bearer kbl_lector_x"}
        self.assertEqual(self.client.get("/mcp", headers=headers).status_code, 405)
        self.assertEqual(self.client.delete("/mcp", headers=headers).status_code, 405)

    def test_an_unknown_protocol_version_header_is_rejected(self):
        response = self.post(rpc("ping"), **{"MCP-Protocol-Version": "1999-01-01"})
        self.assertEqual(response.status_code, 400)

    def test_the_tool_reaches_the_api_with_the_callers_own_token(self):
        response = self.post(rpc("tools/call", {"name": "list_apps", "arguments": {}}))
        result = response.json()["result"]
        self.assertFalse(result["isError"], result)
        self.assertIn("shop-api", result["content"][0]["text"])
        self.assertEqual(self.seen, ["Bearer kbl_lector_x"])

    def test_discovered_tool_uses_the_existing_http_mcp_and_same_token(self):
        token = "Bearer kbl_ingeniero_x"
        listed = self.post(rpc("tools/list"), token=token).json()["result"]["tools"]
        self.assertIn("get_operation", {entry["name"] for entry in listed})
        result = self.post(rpc("tools/call", {"name": "get_operation", "arguments": {"operation_id": "op-1"}}), token=token).json()["result"]
        self.assertFalse(result["isError"], result)
        self.assertIn("op-1", result["content"][0]["text"])
        self.assertEqual(self.seen, [token])

    def test_a_missing_permission_is_explained_before_calling_the_api(self):
        response = self.post(rpc("tools/call", {"name": "set_app_variable",
                                                "arguments": {"name": "shop-api", "variable": "X_KEY", "generate": True}}))
        result = response.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("apps.variables.manage", result["content"][0]["text"])
        self.assertIn("lectura", result["content"][0]["text"])
        self.assertEqual(self.seen, [])

    def test_with_the_permission_the_action_goes_through(self):
        response = self.post(
            rpc("tools/call", {"name": "set_app_variable",
                               "arguments": {"name": "shop-api", "variable": "X_KEY", "generate": True, "reveal": True}}),
            token="Bearer kbl_dueno_x",
        )
        self.assertFalse(response.json()["result"]["isError"])
        self.assertEqual(self.seen, [{"generate": True}])

    def test_without_a_token_nothing_runs(self):
        self.assertEqual(self.client.post("/mcp", json=rpc("ping")).status_code, 401)

    def test_initialize_announces_guided_flows_and_the_guide(self):
        capabilities = self.post(rpc("initialize", {"protocolVersion": "2025-06-18"})).json()["result"]["capabilities"]
        self.assertIn("prompts", capabilities)
        self.assertIn("resources", capabilities)

    def test_the_guide_needs_no_permission_but_data_does(self):
        guide = self.post(rpc("tools/call", {"name": "platform_guide", "arguments": {"topic": "mcp"}}),
                          token="Bearer kbl_nada_x").json()["result"]
        self.assertFalse(guide["isError"], guide)
        self.assertIn("plan_id", guide["content"][0]["text"])
        apps = self.post(rpc("tools/call", {"name": "list_apps", "arguments": {}}), token="Bearer kbl_nada_x").json()["result"]
        self.assertTrue(apps["isError"])
        self.assertIn("apps.apps.view", apps["content"][0]["text"])

    def test_plan_then_apply_goes_through_the_rest_with_query_parameters(self):
        planned = self.post(rpc("tools/call", {"name": "set_homepage", "arguments": {"name": "tienda"}}),
                            token="Bearer kbl_dueno_x").json()["result"]
        self.assertFalse(planned["isError"], planned)
        self.assertIn("0123456789abcdef", planned["content"][0]["text"])
        applied = self.post(rpc("tools/call", {"name": "set_homepage",
                                               "arguments": {"name": "tienda", "plan_id": "0123456789abcdef"}}),
                            token="Bearer kbl_dueno_x").json()["result"]
        self.assertFalse(applied["isError"], applied)
        self.assertIn('"applied": true', applied["content"][0]["text"])
        self.assertEqual(self.seen, [{"dry_run": True, "plan_id": None}, {"dry_run": False, "plan_id": "0123456789abcdef"}])

    def test_a_stale_plan_is_explained_not_applied(self):
        stale = self.post(rpc("tools/call", {"name": "set_homepage",
                                             "arguments": {"name": "tienda", "plan_id": "aaaaaaaaaaaaaaaa"}}),
                          token="Bearer kbl_dueno_x").json()["result"]
        self.assertTrue(stale["isError"])
        self.assertIn("El plan cambió", stale["content"][0]["text"])

    def test_deletes_travel_through_the_loopback_too(self):
        result = self.post(rpc("tools/call", {"name": "unlink_apps", "arguments": {"name": "tienda-api", "to": "pagos-api"}}),
                           token="Bearer kbl_dueno_x").json()["result"]
        self.assertFalse(result["isError"], result)
        self.assertEqual(self.seen, [{"delete": "tienda-api->pagos-api", "dry_run": True}])


try:
    import jose  # noqa: F401  (dependencia del middleware real)
except ImportError:
    jose = None


@unittest.skipIf(jose is None, "python-jose no está instalado (pip install -r requirements.txt)")
class AccessControlOnMcpTests(unittest.TestCase):
    """El middleware real: /mcp no queda fuera de la autenticación aunque no esté bajo /api."""

    def test_without_a_token_the_answer_says_how_to_authenticate(self):
        from app.middleware.acl import AccessControlMiddleware

        app = FastAPI()
        app.add_middleware(AccessControlMiddleware)
        app.include_router(mcp_router.router)
        response = TestClient(app).post("/mcp", json=rpc("ping"))
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers.get("www-authenticate", "").startswith("Bearer"))
        self.assertIn("Authorization", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
