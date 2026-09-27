"""Herramientas del MCP: qué piden, qué devuelven y qué nunca devuelven.

Lo que más importa es lo último: un agente conectado a la plataforma no puede
terminar con un secreto en su contexto.
"""

import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.mcp import catalog, tools  # noqa: E402
from app.mcp.protocol import ToolError  # noqa: E402
from app.services import permissions as perms  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeClient:
    """Responde lo que respondería la API, sin red."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    async def get(self, path, params=None):
        self.calls.append(("GET", path, params or {}))
        return self.responses.get(path, {})

    async def post(self, path, json=None):
        self.calls.append(("POST", path, json or {}))
        return self.responses.get(path, {"ok": True})

    async def put(self, path, json=None):
        self.calls.append(("PUT", path, json or {}))
        return self.responses.get(path, {"ok": True})


APPS = [
    {
        "name": "north-star-bay-api", "template": "fastapi-api", "app_group": "mar",
        "environments": ["prod"], "status": "error", "repo_url": "https://github.com/x/y",
        "domain": {"fqdn": "north-star-bay.store", "public": True,
                   "urls": {"prod": "https://north-star-bay-api.north-star-bay.store"}},
    },
    {
        "name": "homepage", "template": "vue3-spa", "app_group": "northwind", "is_root_domain": True,
        "environments": ["prod"], "status": "running",
        "domain": {"fqdn": "northwindlearning.site", "public": True, "urls": {"prod": "https://northwindlearning.site"}},
    },
]

VALID_ARGS = {"name": "shop-api", "variable": "ADMIN_PASSWORD", "generate": True}


class CatalogTests(unittest.TestCase):
    def test_every_tool_is_complete(self):
        for tool in catalog.TOOLS:
            for key in ("name", "title", "description", "permission", "inputSchema", "annotations"):
                self.assertTrue(tool.get(key) is not None and tool.get(key) != "", f"{tool['name']}: {key}")
            self.assertEqual(tool["inputSchema"]["type"], "object", tool["name"])

    def test_every_permission_exists_in_the_platform(self):
        for tool in catalog.TOOLS:
            self.assertIn(tool["permission"], perms.PERMISSION_KEYS, tool["name"])

    def test_every_tool_in_the_catalog_is_handled(self):
        """Un nombre en el catálogo sin implementación sería una promesa vacía."""
        for tool in catalog.TOOLS:
            try:
                run(tools.call_tool(FakeClient(), tool["name"], dict(VALID_ARGS)))
            except ToolError as exc:
                self.fail(f"{tool['name']} está en el catálogo pero call_tool no lo atiende: {exc}")

    def test_only_three_tools_change_anything(self):
        writers = sorted(t["name"] for t in catalog.TOOLS if not t["annotations"]["readOnlyHint"])
        self.assertEqual(writers, ["repair_db_bindings", "set_app_variable", "sync_app"])

    def test_nothing_reads_secret_values(self):
        for tool in catalog.TOOLS:
            self.assertNotIn(tool["permission"], ("system.secrets.view", "system.credentials.view",
                                                  "system.credentials.manage"), tool["name"])

    def test_no_tool_creates_deletes_or_upgrades(self):
        for tool in catalog.TOOLS:
            action = tool["permission"].rsplit(".", 1)[-1]
            self.assertNotIn(action, ("create", "delete", "launch", "apply", "purge"), tool["name"])
        managers = [t["name"] for t in catalog.TOOLS if t["permission"].endswith(".manage")]
        self.assertEqual(managers, ["set_app_variable"])

    def test_the_client_sees_the_permission_each_tool_needs(self):
        for definition in catalog.definitions():
            tool = catalog.TOOLS_BY_NAME[definition["name"]]
            self.assertIn(tool["permission"], definition["description"])
            self.assertNotIn("permission", definition)

    def test_tools_that_act_on_an_app_require_its_name(self):
        for tool in catalog.TOOLS:
            if "name" in tool["inputSchema"]["properties"]:
                self.assertIn("name", tool["inputSchema"].get("required", []), tool["name"])


class ListingTests(unittest.TestCase):
    def test_apps_come_summarized_with_their_url(self):
        result = run(tools.call_tool(FakeClient({"/apps": APPS}), "list_apps", {}))
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["apps"][0]["domain"], "north-star-bay.store")
        self.assertEqual(result["apps"][0]["urls"]["prod"], "https://north-star-bay-api.north-star-bay.store")
        self.assertTrue(result["apps"][1]["is_homepage"])

    def test_apps_can_be_filtered_by_domain_and_group(self):
        client = FakeClient({"/apps": APPS})
        by_domain = run(tools.call_tool(client, "list_apps", {"domain": "northwindlearning.site"}))
        self.assertEqual([a["name"] for a in by_domain["apps"]], ["homepage"])
        by_group = run(tools.call_tool(client, "list_apps", {"group": "mar"}))
        self.assertEqual([a["name"] for a in by_group["apps"]], ["north-star-bay-api"])


class DiagnosisToolTests(unittest.TestCase):
    def test_health_keeps_what_matters(self):
        client = FakeClient({"/apps/x/status/full": {
            "argocd": {"health": {"status": "Degraded"}, "isSynced": True},
            "argocd_per_env": {"prod": {"health": {"status": "Degraded"}, "exists": True}},
            "pipeline": {"result": "SUCCESSFUL"},
        }})
        result = run(tools.call_tool(client, "app_health", {"name": "x"}))
        self.assertEqual(result["health"], "Degraded")
        self.assertEqual(result["per_env"]["prod"]["health"], "Degraded")

    def test_diagnose_asks_for_the_environment(self):
        client = FakeClient()
        run(tools.call_tool(client, "diagnose_app", {"name": "x", "env": "dev"}))
        self.assertEqual(client.calls[0], ("GET", "/apps/x/diagnosis", {"env": "dev"}))

    def test_env_var_names_asks_the_endpoint_that_hides_values(self):
        client = FakeClient({"/apps/x/env-vars": {"names": ["APP_SECRET", "MONGO_URI"]}})
        result = run(tools.call_tool(client, "app_env_var_names", {"name": "x"}))
        self.assertEqual(client.calls[0], ("GET", "/apps/x/env-vars", {"env": "prod"}))
        self.assertEqual(result["names"], ["APP_SECRET", "MONGO_URI"])


class ActionTests(unittest.TestCase):
    def test_sync_and_repair_call_their_endpoints(self):
        client = FakeClient()
        run(tools.call_tool(client, "sync_app", {"name": "mi-app"}))
        run(tools.call_tool(client, "repair_db_bindings", {"name": "mi-app"}))
        self.assertEqual([c[:2] for c in client.calls],
                         [("POST", "/apps/mi-app/argocd/sync"), ("POST", "/apps/mi-app/bindings/repair")])

    def test_set_variable_puts_only_what_the_api_accepts(self):
        client = FakeClient()
        run(tools.call_tool(client, "set_app_variable", {
            "name": "mi-app", "variable": "ADMIN_PASSWORD", "generate": True, "environments": ["prod"],
        }))
        self.assertEqual(client.calls[0], ("PUT", "/apps/mi-app/variables/ADMIN_PASSWORD",
                                           {"generate": True, "environments": ["prod"]}))

    def test_an_agent_can_never_ask_to_see_a_generated_value(self):
        """`reveal` es para la persona en la consola: el MCP no lo reenvía nunca."""
        client = FakeClient()
        run(tools.call_tool(client, "set_app_variable", {**VALID_ARGS, "reveal": True}))
        self.assertNotIn("reveal", client.calls[0][2])

    def test_arguments_cannot_escape_the_path(self):
        for args in ({"name": "../system/credentials"}, {"name": "Mi App"}, {"name": ""}):
            with self.assertRaises(ToolError):
                run(tools.call_tool(FakeClient(), "get_app", args))
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "set_app_variable", {"name": "x", "variable": "../../X"}))
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "diagnose_app", {"name": "x", "env": "prod/../x"}))

    def test_an_unknown_tool_fails_loudly(self):
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "borrar_todo", {}))


if __name__ == "__main__":
    unittest.main()
