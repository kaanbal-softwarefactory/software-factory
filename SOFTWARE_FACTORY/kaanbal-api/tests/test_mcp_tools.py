"""Herramientas del MCP: qué piden, qué devuelven y qué nunca devuelven.

Lo que más importa: un agente conectado a la plataforma no puede terminar con un
secreto en su contexto, y nada que cree algo o cambie lo que se ve en internet
se aplica sin que antes se haya mostrado su plan.
"""

import asyncio
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.mcp import catalog, guide, tools  # noqa: E402
from app.mcp.protocol import ToolError  # noqa: E402
from app.services import permissions as perms  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeClient:
    """Responde lo que respondería la API, sin red.

    `responses` va por ruta, o por (método, ruta) cuando el mismo camino responde
    distinto según el método. Un valor que es una excepción se lanza.
    """

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def _answer(self, method, path, default):
        value = self.responses.get((method, path), self.responses.get(path, default))
        if isinstance(value, Exception):
            raise value
        return value

    async def request(self, method, path, params=None, json=None):
        self.calls.append((method, path, params or {}, json))
        if (params or {}).get("dry_run"):
            default = {"dry_run": True, "plan": {"action": "x"}, "plan_id": "0123456789abcdef"}
        else:
            default = {"ok": True}
        return self._answer(method, path, default)

    async def get(self, path, params=None):
        self.calls.append(("GET", path, params or {}))
        return self._answer("GET", path, {})

    async def post(self, path, json=None):
        self.calls.append(("POST", path, json or {}))
        return self._answer("POST", path, {"ok": True})

    async def put(self, path, json=None):
        self.calls.append(("PUT", path, json or {}))
        return self._answer("PUT", path, {"ok": True})


APPS = [
    {
        "name": "north-star-bay-api", "template": "fastapi-api", "app_group": "mar",
        "environments": ["prod"], "status": "error", "repo_url": "https://github.com/x/y",
        "domain": {"fqdn": "north-star-bay.store", "public": True,
                   "urls": {"prod": "https://north-star-bay-api.north-star-bay.store"}},
    },
    {
        "name": "homepage", "template": "vue3-spa", "app_group": "northwind", "is_root_domain": True,
        "environments": ["prod"], "status": "running", "exposure_change": {"state": "running"},
        "domain": {"fqdn": "northwindlearning.site", "public": True, "urls": {"prod": "https://northwindlearning.site"}},
    },
]

DOMAINS = [
    {"_id": "65a000000000000000000001", "fqdn": "ejemplo.com", "is_default": True},
    {"_id": "65a000000000000000000002", "fqdn": "nuevo.com", "is_default": False},
]
FASTAPI = {"id": "fastapi-api", "category": "backend", "status": "ready", "port": 8000,
           "creation_modes": ["scaffold", "empty", "upload"]}
VUE = {"id": "vue3-spa", "category": "frontend", "status": "ready", "port": 80, "creation_modes": ["scaffold"]}
TIENDA_DB = {"name": "tienda-db", "template": "mongodb", "environments": ["prod"]}

PLAN_ID = "0123456789abcdef"
PLANNED = ["create_app", "launch_stack", "link_apps", "unlink_apps", "set_exposure", "attach_domain", "set_homepage"]
WRITERS = sorted(PLANNED + ["start_app", "stop_app", "scale_app", "sync_app", "repair_db_bindings", "set_app_variable"])


class CatalogTests(unittest.TestCase):
    def test_every_tool_is_complete(self):
        for tool in catalog.TOOLS:
            for key in ("name", "title", "description", "inputSchema", "annotations"):
                self.assertTrue(tool.get(key), f"{tool['name']}: {key}")
            self.assertEqual(tool["inputSchema"]["type"], "object", tool["name"])
            self.assertIn(tool["group"], catalog.GROUPS, tool["name"])

    def test_only_the_guide_needs_no_permission(self):
        """La guía es texto fijo; todo lo que toca datos de la plataforma exige su permiso."""
        free = [tool["name"] for tool in catalog.TOOLS if tool["permission"] is None]
        self.assertEqual(free, ["platform_guide"])

    def test_every_permission_exists_in_the_platform(self):
        for tool in catalog.TOOLS:
            if tool["permission"] is not None:
                self.assertIn(tool["permission"], perms.PERMISSION_KEYS, tool["name"])

    def test_every_tool_in_the_catalog_is_handled(self):
        """Un nombre en el catálogo sin implementación sería una promesa vacía."""
        for tool in catalog.TOOLS:
            try:
                run(tools.call_tool(FakeClient(), tool["name"], {}))
            except ToolError as exc:
                self.assertNotIn("Herramienta desconocida", str(exc), tool["name"])

    def test_the_writers_are_exactly_these(self):
        """Agregar una herramienta que cambia algo tiene que ser una decisión, no un descuido."""
        writers = sorted(t["name"] for t in catalog.TOOLS if not t["annotations"]["readOnlyHint"])
        self.assertEqual(writers, WRITERS)

    def test_what_creates_or_publishes_shows_its_plan_first(self):
        for name in PLANNED:
            tool = catalog.TOOLS_BY_NAME[name]
            self.assertTrue(tool["plan_first"], name)
            self.assertIn("plan_id", tool["inputSchema"]["properties"], name)
            self.assertNotIn("plan_id", tool["inputSchema"].get("required", []), name)
        for tool in catalog.TOOLS:
            if tool["annotations"].get("openWorldHint"):
                self.assertTrue(tool["plan_first"], f"{tool['name']} toca el mundo de afuera sin plan")

    def test_read_only_tools_only_need_read_permissions(self):
        for tool in catalog.TOOLS:
            if tool["annotations"]["readOnlyHint"] and tool["permission"]:
                self.assertIn(tool["permission"].rsplit(".", 1)[-1], ("view", "diagnose"), tool["name"])

    def test_nothing_reads_secret_values(self):
        for tool in catalog.TOOLS:
            self.assertNotIn(tool["permission"], ("system.secrets.view", "system.credentials.view",
                                                  "system.credentials.manage"), tool["name"])

    def test_nothing_deletes_apps_or_domains_or_touches_the_core_or_access(self):
        for tool in catalog.TOOLS:
            permission = tool["permission"] or ""
            self.assertNotIn(permission.rsplit(".", 1)[-1], ("delete", "apply", "purge", "reconcile"), tool["name"])
            self.assertFalse(permission.startswith(("security.", "setup.", "system.credentials", "system.tokens")),
                             tool["name"])
            for word in ("delete", "purge", "upgrade", "borrar"):
                self.assertNotIn(word, tool["name"])
        managers = sorted(t["name"] for t in catalog.TOOLS if (t["permission"] or "").endswith(".manage"))
        self.assertEqual(managers, ["link_apps", "set_app_variable", "unlink_apps"])

    def test_the_client_sees_the_permission_each_tool_needs(self):
        for definition in catalog.definitions():
            tool = catalog.TOOLS_BY_NAME[definition["name"]]
            self.assertIn(tool["permission"] or "cualquier token", definition["description"])
            for internal in ("permission", "group", "plan_first"):
                self.assertNotIn(internal, definition)

    def test_tools_that_act_on_an_app_require_its_name(self):
        for tool in catalog.TOOLS:
            if "name" in tool["inputSchema"]["properties"]:
                self.assertIn("name", tool["inputSchema"].get("required", []), tool["name"])

    def test_the_guide_topics_in_the_schema_exist(self):
        self.assertEqual(catalog.GUIDE_TOPICS, guide.topic_names())


class ListingTests(unittest.TestCase):
    def test_apps_come_summarized_with_their_url(self):
        result = run(tools.call_tool(FakeClient({"/apps": APPS}), "list_apps", {}))
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["apps"][0]["domain"], "north-star-bay.store")
        self.assertEqual(result["apps"][0]["urls"]["prod"], "https://north-star-bay-api.north-star-bay.store")
        self.assertTrue(result["apps"][1]["is_homepage"])
        self.assertEqual(result["apps"][1]["in_progress"], ["exposure_change"])

    def test_apps_can_be_filtered_by_domain_and_group(self):
        client = FakeClient({"/apps": APPS})
        by_domain = run(tools.call_tool(client, "list_apps", {"domain": "northwindlearning.site"}))
        self.assertEqual([a["name"] for a in by_domain["apps"]], ["homepage"])
        by_group = run(tools.call_tool(client, "list_apps", {"group": "mar"}))
        self.assertEqual([a["name"] for a in by_group["apps"]], ["north-star-bay-api"])

    def test_templates_say_how_they_are_created(self):
        client = FakeClient({"/templates": [FASTAPI, {"id": "mongodb", "creation_modes": ["config-only"]}]})
        result = run(tools.call_tool(client, "list_templates", {"category": "backend"}))
        self.assertEqual(client.calls[0], ("GET", "/templates", {"category": "backend"}))
        self.assertEqual([t["creation"] for t in result["templates"]], ["repositorio con código", "imagen oficial"])


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

    def test_logs_come_from_the_right_environment_with_secrets_masked(self):
        ndjson = "\n".join([
            json.dumps({"result": {"content": "conectando a mongodb://admin:s3cr3t0@tienda-db:27017", "podName": "api-1"}}),
            json.dumps({"result": {"content": "Authorization: Bearer abcdefghijklmnop", "podName": "api-1"}}),
            json.dumps({"result": {"content": "", "last": True}}),
        ])
        client = FakeClient({"/apps/x/argocd/logs": {"logs": ndjson, "app_name": "x-dev"}})
        result = run(tools.call_tool(client, "app_logs", {"name": "x", "env": "dev", "lines": 50}))
        self.assertEqual(client.calls[0], ("GET", "/apps/x/argocd/logs", {"env": "dev", "lines": 50}))
        self.assertEqual(len(result["lines"]), 2)
        self.assertTrue(result["lines"][0].startswith("[api-1] "))
        text = " ".join(result["lines"])
        self.assertNotIn("s3cr3t0", text)
        self.assertNotIn("abcdefghijklmnop", text)

    def test_logs_keep_only_the_last_lines(self):
        client = FakeClient({"/apps/x/argocd/logs": {"logs": "\n".join(f"linea {i}" for i in range(20))}})
        result = run(tools.call_tool(client, "app_logs", {"name": "x", "lines": 3}))
        self.assertEqual(result["lines"], ["linea 17", "linea 18", "linea 19"])


class StatusToolTests(unittest.TestCase):
    def test_deploy_status_follows_a_running_change(self):
        client = FakeClient({
            "/apps/x": {"name": "x", "status": "running", "exposure_change": {"state": "running", "per_env": {"prod": "public"}},
                        "domain": {"urls": {"prod": "https://x.ejemplo.com"}}},
            "/logs": {"logs": [{"timestamp": "2026-09-27T10:00:00Z", "action": "deploy.push", "level": "info",
                                "detail": {"event": {"message": "Code pushed"}}}]},
            "/apps/x/status/full": {"argocd_per_env": {"prod": {"health": {"status": "Healthy"}}}},
        })
        result = run(tools.call_tool(client, "deploy_status", {"name": "x"}))
        self.assertIn("exposure_change", result["operations"])
        self.assertIn("en curso", result["hint"])
        self.assertEqual(result["recent_activity"][0]["message"], "Code pushed")
        self.assertEqual(result["health"], {"prod": "Healthy"})

    def test_deploy_status_works_without_access_to_the_activity_log(self):
        client = FakeClient({
            "/apps/x": {"name": "x", "status": "error", "error": "fallo con https://tok:en@github.com"},
            "/logs": ToolError("sin permiso"),
            "/apps/x/status/full": ToolError("sin permiso"),
        })
        result = run(tools.call_tool(client, "deploy_status", {"name": "x"}))
        self.assertIsNone(result["recent_activity"])
        self.assertIn("diagnose_app", result["hint"])
        self.assertNotIn("tok:en", result["error"])

    def test_stack_status_needs_a_real_run_id(self):
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "stack_status", {"run_id": "../../x"}))
        run_id = "65a0000000000000000000ff"
        client = FakeClient({f"/stacks/runs/{run_id}": {"state": "failed", "components": [
            {"role": "database", "name": "o-db", "state": "ready"},
            {"role": "backend", "name": "o-api", "state": "failed", "error": "boom"},
        ]}})
        result = run(tools.call_tool(client, "stack_status", {"run_id": run_id}))
        self.assertEqual(result["components"][1]["error"], "boom")
        self.assertIn("diagnose_app", result["hint"])


class PlanFirstTests(unittest.TestCase):
    """Sin plan_id: dry_run y nada aplicado. Con plan_id: se aplica ese plan."""

    def create_client(self, extra=None):
        return FakeClient({"/templates/fastapi-api": FASTAPI, "/templates/vue3-spa": VUE, "/domains": DOMAINS,
                           "/apps/tienda-db": TIENDA_DB, **(extra or {})})

    def test_without_plan_id_nothing_is_applied(self):
        client = self.create_client()
        result = run(tools.call_tool(client, "create_app", {"name": "tienda-api", "template": "fastapi-api",
                                                            "database": "tienda-db"}))
        method, path, params, body = client.calls[-1]
        self.assertEqual((method, path, params), ("POST", "/apps", {"dry_run": "true"}))
        self.assertEqual(body["database_bindings"]["prod"][0]["app_name"], "tienda-db")
        self.assertFalse(result["applied"])
        self.assertEqual(result["plan_id"], PLAN_ID)
        self.assertIn(PLAN_ID, result["next"])

    def test_with_plan_id_the_same_request_is_applied(self):
        client = self.create_client({("POST", "/apps"): {"name": "tienda-api", "status": "deploying"}})
        result = run(tools.call_tool(client, "create_app", {"name": "tienda-api", "template": "fastapi-api",
                                                            "domain": "nuevo.com", "plan_id": PLAN_ID}))
        method, path, params, body = client.calls[-1]
        self.assertEqual(params, {"plan_id": PLAN_ID})
        self.assertEqual(body["domain_id"], "65a000000000000000000002")
        self.assertTrue(result["applied"])
        self.assertIn("deploy_status", result["next"])

    def test_a_made_up_plan_id_is_refused_before_calling_the_api(self):
        client = self.create_client()
        with self.assertRaises(ToolError):
            run(tools.call_tool(client, "set_homepage", {"name": "tienda", "plan_id": "aplicalo-ya"}))
        self.assertEqual(client.calls, [])

    def test_an_unknown_domain_lists_the_registered_ones(self):
        with self.assertRaises(ToolError) as ctx:
            run(tools.call_tool(self.create_client(), "attach_domain", {"name": "tienda", "domain": "otro.com"}))
        self.assertIn("nuevo.com", str(ctx.exception))

    def test_blueprint_refusals_reach_the_agent(self):
        with self.assertRaises(ToolError) as ctx:
            run(tools.call_tool(self.create_client(), "create_app",
                                {"name": "tienda", "template": "vue3-spa", "database": "tienda-db"}))
        self.assertIn("frontend", str(ctx.exception))

    def test_launch_stack_resolves_the_domain_and_keeps_the_base_name(self):
        client = self.create_client()
        run(tools.call_tool(client, "launch_stack", {"stack": "vue-fastapi-mongo", "base_name": "orbita",
                                                     "domain": "ejemplo.com", "homepage": True}))
        _, path, params, body = client.calls[-1]
        self.assertEqual((path, params), ("/stacks", {"dry_run": "true"}))
        self.assertEqual(body["domain_id"], "65a000000000000000000001")
        self.assertEqual((body["name"], body["homepage"], body["environments"]), ("orbita", True, ["prod"]))

    def test_links_go_to_the_consumer_and_unlinks_are_deletes(self):
        client = self.create_client()
        run(tools.call_tool(client, "link_apps", {"name": "tienda-api", "to": "tienda-db", "alias": "principal"}))
        run(tools.call_tool(client, "unlink_apps", {"name": "tienda-api", "to": "tienda-db"}))
        self.assertEqual(client.calls[0][:2], ("POST", "/apps/tienda-api/links"))
        self.assertEqual(client.calls[0][3], {"to_app": "tienda-db", "alias": "PRINCIPAL"})
        self.assertEqual(client.calls[1][:3], ("DELETE", "/apps/tienda-api/links/tienda-db", {"dry_run": "true"}))

    def test_exposure_modes_are_checked_before_asking(self):
        client = self.create_client()
        with self.assertRaises(ToolError):
            run(tools.call_tool(client, "set_exposure", {"name": "x", "per_env": {"prod": "abierto"}}))
        run(tools.call_tool(client, "set_exposure", {"name": "x", "per_env": {"dev": "tailscale"}}))
        self.assertEqual(client.calls[-1][1:], ("/apps/x/exposure", {"dry_run": "true"}, {"per_env": {"dev": "tailscale"}}))


class OperateTests(unittest.TestCase):
    def test_sync_and_repair_call_their_endpoints(self):
        client = FakeClient()
        run(tools.call_tool(client, "sync_app", {"name": "mi-app"}))
        run(tools.call_tool(client, "repair_db_bindings", {"name": "mi-app"}))
        self.assertEqual([c[:2] for c in client.calls],
                         [("POST", "/apps/mi-app/argocd/sync"), ("POST", "/apps/mi-app/bindings/repair")])

    def test_power_tools(self):
        client = FakeClient()
        run(tools.call_tool(client, "stop_app", {"name": "mi-app", "env": "dev"}))
        run(tools.call_tool(client, "start_app", {"name": "mi-app", "env": "dev"}))
        run(tools.call_tool(client, "scale_app", {"name": "mi-app", "replicas": 3}))
        self.assertEqual(client.calls, [
            ("POST", "/apps/mi-app/environments/dev/stop", {}),
            ("POST", "/apps/mi-app/environments/dev/start", {}),
            ("POST", "/apps/mi-app/environments/prod/scale", {"replicas": 3}),
        ])

    def test_scaling_to_zero_or_absurd_numbers_is_refused(self):
        for replicas in (0, 11, True, "3"):
            with self.assertRaises(ToolError):
                run(tools.call_tool(FakeClient(), "scale_app", {"name": "mi-app", "replicas": replicas}))

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
        run(tools.call_tool(client, "set_app_variable", {"name": "shop-api", "variable": "X_KEY",
                                                         "generate": True, "reveal": True}))
        self.assertNotIn("reveal", client.calls[0][2])

    def test_arguments_cannot_escape_the_path(self):
        for args in ({"name": "../system/credentials"}, {"name": "Mi App"}, {"name": ""}):
            with self.assertRaises(ToolError):
                run(tools.call_tool(FakeClient(), "get_app", args))
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "set_app_variable", {"name": "x", "variable": "../../X"}))
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "diagnose_app", {"name": "x", "env": "prod/../x"}))
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "unlink_apps", {"name": "x", "to": "../../system"}))
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "create_app", {"name": "x-api", "template": "../secretos"}))

    def test_an_unknown_tool_fails_loudly(self):
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "borrar_todo", {}))


class GuideTests(unittest.TestCase):
    def test_the_guide_starts_with_the_platform(self):
        result = run(tools.call_tool(FakeClient(), "platform_guide", {}))
        self.assertEqual(result["topic"], "plataforma")
        self.assertIn("desarrollo-local", result["other_topics"])

    def test_every_topic_is_readable_and_unknown_ones_are_refused(self):
        for topic in guide.topic_names():
            self.assertTrue(run(tools.call_tool(FakeClient(), "platform_guide", {"topic": topic}))["text"])
        with self.assertRaises(ToolError):
            run(tools.call_tool(FakeClient(), "platform_guide", {"topic": "secretos"}))

    def test_the_contract_explains_an_api(self):
        client = FakeClient({
            "/apps/tienda-api": {"name": "tienda-api", "template": "fastapi-api", "category": "backend",
                                 "environments": ["dev", "prod"], "repo_url": "https://github.com/o/tienda-api",
                                 "domain": {"urls": {"prod": "https://tienda-api.ejemplo.com"}, "modes": {"prod": "public"}}},
            "/templates/fastapi-api": FASTAPI,
            "/links": [{"to_app": "pagos-api", "from_env": "prod", "kind": "service", "alias": "PAGOS_API",
                        "published_names": ["PAGOS_API_URL"]}],
            "/apps/tienda-api/env-vars": {"names": ["APP_SECRET", "MONGO_URI", "TIENDA_DB_HOST", "TIENDA_DB_URI",
                                                    "PAGOS_API_URL", "ADMIN_PASSWORD"]},
        })
        result = run(tools.call_tool(client, "app_contract", {"name": "tienda-api"}))
        self.assertEqual(result["runtime"], {"port": 8000, "health_path": "/health"})
        self.assertEqual(result["deploy"]["branches"], {"dev": "develop", "prod": "main"})
        variables = result["variables"]
        self.assertEqual(variables["platform"], ["APP_SECRET", "MONGO_URI", "TIENDA_DB_HOST", "TIENDA_DB_URI"])
        self.assertEqual(variables["links"], ["PAGOS_API_URL"])
        self.assertEqual(variables["own"], ["ADMIN_PASSWORD"])
        # El .env de ejemplo usa los nombres estándar, no los que dependen de cómo se llame la base.
        self.assertIn("MONGO_URI=mongodb://localhost:27017", variables["local_env_example"])
        self.assertNotIn("TIENDA_DB_URI", variables["local_env_example"])
        self.assertTrue(any("8000" in rule for rule in result["rules"]))

    def test_the_contract_of_an_official_image_has_no_pipeline(self):
        client = FakeClient({
            "/apps/tienda-db": {"name": "tienda-db", "template": "mongodb", "category": "database", "environments": ["prod"]},
            "/links": [],
            "/apps/tienda-db/env-vars": ToolError("El token no incluye apps.apps.diagnose"),
        })
        result = run(tools.call_tool(client, "app_contract", {"name": "tienda-db"}))
        self.assertIn("Imagen oficial", result["deploy"]["how"])
        self.assertIn("apps.apps.diagnose", result["variables"]["unavailable"])


if __name__ == "__main__":
    unittest.main()
