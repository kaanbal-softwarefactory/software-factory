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
    "Bearer kbl_lector_x": access.Principal(username="ana", permissions={"apps.apps.view"},
                                            token_id="1", token_name="lectura"),
    "Bearer kbl_dueno_x": access.Principal(username="ana", permissions={"apps.apps.view", "apps.variables.manage"},
                                           token_id="2", token_name="todo"),
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

    @app.put("/api/v1/apps/{name}/variables/{variable}")
    async def put_variable(name: str, variable: str, request: Request):
        seen.append(await request.json())
        return {"app": name, "variable": variable, "committed": True}

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
