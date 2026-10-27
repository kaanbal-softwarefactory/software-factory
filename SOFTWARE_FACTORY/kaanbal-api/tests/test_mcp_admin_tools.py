"""Herramientas de administración del MCP: identidad, capacidades, versiones, datos y lo irreversible."""

import asyncio
import json
import os
import sys
import types
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.mcp import admin_tools, catalog, inventory, protocol, tools  # noqa: E402
from app.mcp.protocol import ToolError  # noqa: E402
from tests.test_mcp_tools import FakeClient  # noqa: E402


def run(coro):
    return asyncio.run(coro)


READER = {"username": "ana", "roles": ["agente"], "permissions": ["apps.apps.view", "apps.apps.diagnose",
                                                                   "autonomy.tools.view"],
          "via_token": True, "token_name": "lectura", "elevated": False}
OWNER = {**READER, "permissions": sorted(set(READER["permissions"]) | {"apps.apps.delete", "data.backups.view",
                                                                       "data.records.read"}),
         "token_name": "control-total", "elevated": True}
ACCESS = {"autonomy_enabled": True, "features": {"runtime": False, "workspace": True, "host": False, "merge": False},
          "approval_required": True, "grants": [{"apps": ["tienda"], "environments": ["dev"]}]}


class IdentityTests(unittest.TestCase):
    def test_whoami_names_the_instance(self):
        client = FakeClient({"/security/me": READER, "/core/version": {"version": "1.3.0", "upstream": "org/kaanbal"},
                             "/domains": [{"fqdn": "example.com", "is_default": True}, {"fqdn": "example.org"}],
                             "/autonomy/access": ACCESS})
        result = run(tools.call_tool(client, "whoami", {}, {"api_url": "https://api.example.com"}))
        self.assertEqual(result["instance"]["mcp_url"], "https://api.example.com/mcp")
        self.assertEqual(result["instance"]["default_domain"], "example.com")
        self.assertEqual(result["instance"]["version"], "1.3.0")
        self.assertEqual(result["account"]["token"], "lectura")
        self.assertFalse(result["account"]["elevated"])

    def test_whoami_works_with_a_token_that_sees_little(self):
        client = FakeClient({"/security/me": {**READER, "permissions": []},
                             "/core/version": ToolError("sin permiso"), "/domains": ToolError("sin permiso"),
                             "/autonomy/access": ToolError("sin permiso")})
        result = run(tools.call_tool(client, "whoami", {}, {}))
        self.assertIsNone(result["instance"]["version"])
        self.assertIsInstance(result["autonomy"], str)

    def capabilities(self, me, access=ACCESS, **args):
        client = FakeClient({"/security/me": me, "/autonomy/access": access})
        return run(tools.call_tool(client, "platform_capabilities", args))

    def test_capabilities_cover_every_tool_and_say_what_is_missing(self):
        result = self.capabilities(READER)
        rows = {row["name"]: row for row in result["tools"]}
        for tool in catalog.TOOLS:
            self.assertIn(tool["name"], rows)
        self.assertIn("platform_upgrade", rows)
        self.assertTrue(rows["list_apps"]["available"])
        self.assertIn("permiso apps.apps.delete", rows["delete_app"]["missing"])
        self.assertIn("token crítico", rows["delete_app"]["missing"])
        self.assertEqual(rows["delete_app"]["kind"], "crítica")
        self.assertTrue(rows["delete_app"]["human_approval"])
        self.assertIn("la política no enciende 'host'", rows["execute_node_command"]["missing"])
        self.assertEqual(rows["rollback_app"]["kind"], "plan")

    def test_only_available(self):
        result = self.capabilities(OWNER, only_available=True)
        self.assertTrue(all(row["available"] for row in result["tools"]))
        self.assertIn("delete_app", {row["name"] for row in result["tools"]})

    def test_critical_token_bypass_is_reflected_in_discovery(self):
        elevated = {**OWNER, "permissions": sorted(set(OWNER["permissions"]) | {
            "autonomy.apps.execute", "autonomy.host.execute", "autonomy.changes.merge", "autonomy.workspaces.manage",
            "autonomy.core.contribute",
        })}
        access = {**ACCESS, "features": {"runtime": True, "workspace": True, "host": True, "merge": True},
                  "grants": [], "elevated_tokens_bypass_grants": True}
        rows = {row["name"]: row for row in self.capabilities(elevated, access=access)["tools"]}
        self.assertTrue(rows["execute_app_command"]["available"])
        self.assertTrue(rows["execute_node_command"]["available"])

    def test_invoke_platform_tool_only_reaches_discovered_capabilities(self):
        spec = {"name": "get_operation", "method": "GET", "path": "/autonomy/operations/{operation_id}",
                "path_args": ["operation_id"], "query_args": [], "body_args": [], "required": ["operation_id"]}
        client = FakeClient({"/autonomy/operations/op-1": {"state": "succeeded"}})
        result = run(tools.call_tool(client, "invoke_platform_tool",
                                     {"tool": "get_operation", "arguments": {"operation_id": "op-1"}},
                                     {"discovered": {"get_operation": spec}}))
        self.assertEqual(result, {"state": "succeeded"})
        with self.assertRaises(ToolError) as caught:
            run(tools.call_tool(client, "invoke_platform_tool", {"tool": "rm_everything"}, {"discovered": {}}))
        self.assertIn("no es una capacidad", str(caught.exception))


class ReleaseToolTests(unittest.TestCase):
    def test_rollback_shows_the_plan_first(self):
        client = FakeClient()
        result = run(tools.call_tool(client, "rollback_app", {"name": "tienda", "env": "prod", "tag": "prod-aaa"}))
        self.assertFalse(result["applied"])
        method, path, params, body = client.calls[0]
        self.assertEqual((method, path, params, body),
                         ("POST", "/apps/tienda/environments/prod/rollback", {"dry_run": "true"}, {"tag": "prod-aaa"}))

    def test_pipeline_logs_mask_credentials_and_point_at_the_failure(self):
        client = FakeClient({"/apps/tienda/pipeline/logs": {"pipeline_info": {"build_number": 7}, "steps": [
            {"name": "build", "result": "SUCCESSFUL", "logs": "ok"},
            {"name": "push", "result": "FAILED", "logs": "login https://bot:hunter22@registry.example.com\ndenied"},
        ]}, "/apps/tienda/pipeline/history": {"pipelines": [{"build_number": 7}]}})
        result = run(tools.call_tool(client, "pipeline_logs", {"name": "tienda"}))
        self.assertNotIn("hunter22", json.dumps(result))
        self.assertNotIn("log_tail", result["steps"][0])
        self.assertIn("push", result["hint"])

    def test_wait_for_deploy_returns_as_soon_as_it_is_done(self):
        client = FakeClient({"/apps/tienda": {"name": "tienda", "status": "running"}})
        result = run(tools.call_tool(client, "wait_for_deploy", {"name": "tienda", "timeout_seconds": 10}))
        self.assertTrue(result["waited_until_done"])


DB = {"_id": "65a000000000000000000009", "name": "tienda-db", "template": "mongodb", "environments": ["prod"],
      "domain": {"urls": {}}}


def recent():
    return datetime.now(timezone.utc).isoformat()


class DataToolTests(unittest.TestCase):
    def test_restore_passes_env_plan_and_approval(self):
        client = FakeClient()
        run(tools.call_tool(client, "restore_database", {"name": "tienda-db", "backup_id": "abc123",
                                                         "plan_id": "0123456789abcdef",
                                                         "approval_id": "a" * 20}))
        method, path, params, _ = client.calls[0]
        self.assertEqual(path, "/apps/tienda-db/backups/abc123/restore")
        self.assertEqual(params, {"env": "prod", "approval_id": "a" * 20, "plan_id": "0123456789abcdef"})

    def test_a_malformed_approval_is_refused_before_calling(self):
        client = FakeClient()
        with self.assertRaises(ToolError):
            run(tools.call_tool(client, "restore_database", {"name": "tienda-db", "backup_id": "abc",
                                                             "plan_id": "0123456789abcdef", "approval_id": "x"}))
        self.assertEqual(client.calls, [])

    def test_query_goes_to_the_rest_with_its_environment(self):
        client = FakeClient()
        run(tools.call_tool(client, "query_database", {"name": "tienda-db", "operation": "find", "collection": "orders"}))
        self.assertEqual(client.calls[0], ("POST", "/apps/tienda-db/query",
                                           {"operation": "find", "collection": "orders", "env": "prod"}))


class DeleteTests(unittest.TestCase):
    def client(self, backups):
        return FakeClient({"/apps/tienda-db": DB, "/links": [{"from_app": "tienda-api", "to_app": "tienda-db"}],
                           "/apps/tienda-db/backups": {"operations": backups}})

    def test_a_database_without_a_recent_backup_is_not_planned(self):
        with self.assertRaises(ToolError) as caught:
            run(tools.call_tool(self.client([]), "delete_app", {"name": "tienda-db"}))
        self.assertIn("backup_database", str(caught.exception))

    def test_plan_then_delete_with_approval(self):
        backups = [{"id": "b1", "kind": "backup", "state": "succeeded", "created_at": recent(), "env": "prod"}]
        client = self.client(backups)
        planned = run(tools.call_tool(client, "delete_app", {"name": "tienda-db"}))
        self.assertFalse(planned["applied"])
        self.assertEqual(planned["plan"]["used_by"], ["tienda-api"])
        self.assertFalse(any(call[0] == "DELETE" for call in client.calls))
        applied = run(tools.call_tool(client, "delete_app", {"name": "tienda-db", "plan_id": planned["plan_id"],
                                                             "approval_id": "c" * 20}))
        self.assertTrue(applied["applied"])
        delete = [call for call in client.calls if call[0] == "DELETE"]
        self.assertEqual(delete, [("DELETE", f"/apps/{DB['_id']}", {"approval_id": "c" * 20}, None)])

    def test_a_stale_plan_deletes_nothing(self):
        backups = [{"id": "b1", "kind": "backup", "state": "succeeded", "created_at": recent()}]
        client = self.client(backups)
        with self.assertRaises(ToolError):
            run(tools.call_tool(client, "delete_app", {"name": "tienda-db", "plan_id": "ffffffffffffffff"}))
        self.assertFalse(any(call[0] == "DELETE" for call in client.calls))

    def test_without_backup_is_written_in_the_plan(self):
        planned = run(tools.call_tool(self.client([]), "delete_app", {"name": "tienda-db", "without_backup": True}))
        self.assertTrue(planned["plan"]["without_backup"])


class AuditToolTests(unittest.TestCase):
    def test_the_audit_uses_what_the_token_can_see(self):
        apps = [{"name": "tienda-api", "app_group": "tienda", "domain": {}},
                {"name": "tienda-db", "template": "mongodb", "app_group": "otro", "domain": {}}]
        client = FakeClient({"/apps": apps, "/links": [{"from_app": "tienda-api", "to_app": "tienda-db"}],
                             "/apps/argocd/all": ToolError("sin permiso"),
                             "/apps/tienda-db/backups": ToolError("sin permiso")})
        report = run(tools.call_tool(client, "audit_platform", {}))
        self.assertIn("group_split", {f["code"] for f in report["findings"]})
        self.assertTrue(any("data.backups.view" in note for note in report["notes"]))


class ResourceTests(unittest.TestCase):
    def test_inventory_is_listed_and_read_with_the_callers_token(self):
        self.assertEqual(inventory.resources()[0]["uri"], "kaanbal://inventario/apps")
        client = FakeClient({"/apps": [{"name": "tienda", "domain": {}}]})
        content = run(inventory.read(client, "kaanbal://inventario/apps"))
        self.assertIn("tienda", content["text"])
        with self.assertRaises(KeyError):
            run(inventory.read(client, "kaanbal://inventario/otra-cosa/x/y/z"))

    def test_the_protocol_awaits_an_async_reader_and_lists_templates(self):
        async def reader(uri):
            return {"uri": uri, "text": "ok"}

        common = dict(server_info={"name": "k"}, instructions="", tools=[], run_tool=None,
                      read_resource=reader, resource_templates=inventory.templates())
        read = run(protocol.handle_message({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                                            "params": {"uri": "kaanbal://x"}}, **common))
        self.assertEqual(read["result"]["contents"][0]["text"], "ok")
        listed = run(protocol.handle_message({"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list"}, **common))
        self.assertEqual(len(listed["result"]["resourceTemplates"]), 2)


class CatalogShapeTests(unittest.TestCase):
    def test_every_new_tool_is_dispatched(self):
        for name in admin_tools.HANDLED:
            self.assertIn(name, catalog.TOOLS_BY_NAME, name)


if __name__ == "__main__":
    unittest.main()
