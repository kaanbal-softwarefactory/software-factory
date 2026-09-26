"""Herramientas del MCP: qué pide, qué devuelve y qué nunca devuelve.

Lo que más importa aquí es lo último: un agente conectado a la plataforma no
puede terminar con un secreto en su contexto.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kaanbal_mcp import tools  # noqa: E402
from kaanbal_mcp.client import KaanbalClient, KaanbalError  # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


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


class CatalogTests(unittest.TestCase):
    def test_every_tool_declares_what_it_needs(self):
        for tool in tools.TOOLS:
            self.assertTrue(tool["description"].strip(), tool["name"])
            self.assertIn(".", tool["permission"])

    def test_every_tool_in_the_catalog_is_actually_handled(self):
        """Un nombre en el catálogo sin implementación sería una promesa vacía."""
        for tool in tools.TOOLS:
            try:
                run(tools.call_tool(FakeClient(), tool["name"], {"name": "x"}))
            except ValueError:
                self.fail(f"{tool['name']} está en el catálogo pero call_tool no lo atiende")

    def test_only_two_tools_change_anything(self):
        acciones = [t["name"] for t in tools.TOOLS if t["permission"] == "apps.apps.deploy"]
        self.assertEqual(sorted(acciones), ["repair_db_bindings", "sync_app"])

    def test_nothing_reads_secret_values(self):
        """Ninguna herramienta pide el permiso de leer secretos."""
        for tool in tools.TOOLS:
            self.assertNotEqual(tool["permission"], "system.secrets.view", tool["name"])
            self.assertNotEqual(tool["permission"], "system.credentials.view", tool["name"])

    def test_no_tool_creates_or_deletes(self):
        prohibidos = ("create", "delete", "launch", "upgrade", "manage")
        for tool in tools.TOOLS:
            action = tool["permission"].rsplit(".", 1)[-1]
            self.assertNotIn(action, prohibidos, tool["name"])


class ListingTests(unittest.TestCase):
    def test_apps_come_summarized_with_their_url(self):
        client = FakeClient({"/apps": APPS})
        result = run(tools.call_tool(client, "list_apps", {}))
        self.assertEqual(result["total"], 2)
        first = result["apps"][0]
        self.assertEqual(first["name"], "north-star-bay-api")
        self.assertEqual(first["domain"], "north-star-bay.store")
        self.assertEqual(first["urls"]["prod"], "https://north-star-bay-api.north-star-bay.store")

    def test_apps_can_be_filtered_by_domain_and_group(self):
        client = FakeClient({"/apps": APPS})
        by_domain = run(tools.call_tool(client, "list_apps", {"domain": "northwindlearning.site"}))
        self.assertEqual([a["name"] for a in by_domain["apps"]], ["homepage"])
        by_group = run(tools.call_tool(client, "list_apps", {"group": "mar"}))
        self.assertEqual([a["name"] for a in by_group["apps"]], ["north-star-bay-api"])

    def test_the_homepage_is_marked(self):
        client = FakeClient({"/apps": APPS})
        result = run(tools.call_tool(client, "list_apps", {}))
        self.assertTrue(result["apps"][1]["is_homepage"])


class DiagnosisTests(unittest.TestCase):
    def test_health_keeps_what_matters(self):
        client = FakeClient({"/apps/x/status/full": {
            "argocd": {"health": {"status": "Degraded"}, "isSynced": True},
            "argocd_per_env": {"prod": {"health": {"status": "Degraded"}, "exists": True}},
            "pipeline": {"result": "SUCCESSFUL"},
            "diagnosis": "CrashLoopBackOff",
        }})
        result = run(tools.call_tool(client, "app_health", {"name": "x"}))
        self.assertEqual(result["health"], "Degraded")
        self.assertTrue(result["synced"])
        self.assertEqual(result["pipeline"], "SUCCESSFUL")
        self.assertEqual(result["per_env"]["prod"]["health"], "Degraded")

    def test_env_var_names_asks_the_endpoint_that_hides_values(self):
        client = FakeClient({"/apps/x/env-vars": {"app": "x", "env": "prod", "names": ["APP_SECRET", "MONGO_URI"]}})
        result = run(tools.call_tool(client, "app_env_var_names", {"name": "x"}))
        self.assertEqual(client.calls[0], ("GET", "/apps/x/env-vars", {"env": "prod"}))
        self.assertEqual(result["names"], ["APP_SECRET", "MONGO_URI"])

    def test_logs_respect_the_environment_asked(self):
        client = FakeClient()
        run(tools.call_tool(client, "app_logs", {"name": "x", "env": "dev", "lines": 20}))
        self.assertEqual(client.calls[0], ("GET", "/apps/x/argocd/logs", {"env": "dev", "lines": 20}))


class ActionTests(unittest.TestCase):
    def test_sync_calls_argocd(self):
        client = FakeClient()
        run(tools.call_tool(client, "sync_app", {"name": "mi-app"}))
        self.assertEqual(client.calls[0][:2], ("POST", "/apps/mi-app/argocd/sync"))

    def test_repair_calls_the_bindings_endpoint(self):
        client = FakeClient()
        run(tools.call_tool(client, "repair_db_bindings", {"name": "mi-app"}))
        self.assertEqual(client.calls[0][:2], ("POST", "/apps/mi-app/bindings/repair"))

    def test_an_unknown_tool_fails_loudly(self):
        with self.assertRaises(ValueError):
            run(tools.call_tool(FakeClient(), "borrar_todo", {}))


try:
    from kaanbal_mcp import server as mcp_server
except ImportError:  # sin el SDK instalado (pip install -r requirements.txt)
    mcp_server = None


@unittest.skipIf(mcp_server is None, "el SDK mcp no está instalado")
class ServerWiringTests(unittest.TestCase):
    def test_every_tool_has_a_handler_registered(self):
        self.assertEqual(sorted(mcp_server.HANDLERS), sorted(t["name"] for t in tools.TOOLS))

    def test_a_tool_argument_called_name_does_not_collide(self):
        """Regresión: _run(name, **args) chocaba con las herramientas que reciben `name`."""
        import inspect

        params = list(inspect.signature(mcp_server._run).parameters.values())
        self.assertEqual(params[0].kind, inspect.Parameter.POSITIONAL_ONLY)
        self.assertNotEqual(params[0].name, "name")


class ClientTests(unittest.TestCase):
    def test_it_refuses_to_start_without_credentials(self):
        for env in ({}, {"KAANBAL_URL": "https://x"}):
            with self.assertRaises(KaanbalError):
                KaanbalClient(base_url=env.get("KAANBAL_URL", ""), token="")

    def test_the_url_loses_its_trailing_slash(self):
        client = KaanbalClient(base_url="https://api.x/", token="kbl_a_b")
        self.assertEqual(client.base_url, "https://api.x")


if __name__ == "__main__":
    unittest.main()
