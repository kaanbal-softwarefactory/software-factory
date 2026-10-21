"""The agent-facing contract must agree with the deployed managed stack."""
import asyncio
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.mcp import business_contract, tools
from app.services import business_stack
from app.mcp.protocol import ToolError


class Client:
    async def get(self, path, params=None):
        return {
            "/apps/system-demo": {"name": "system-demo", "template": "business-base", "category": "backend",
                                   "app_group": "shared-group", "repo_url": "https://github.com/example/system-demo",
                                   "environments": ["prod"], "domain": {"urls": {"prod": "https://app.example.com"}},
                                   "template_config": {"SMTP_PASSWORD": "CHANGE_ME_NOT_EXPOSED"}},
            "/templates/business-base": {"id": "business-base", "port": 3000, "health_check_path": "/api/ready"},
            "/apps/system-demo/env-vars": {"names": []},
            "/links": [],
            "/groups": {"groups": [{"slug": "another-group", "owner": "other-owner"},
                                      {"slug": "shared-group", "owner": "developer-a"}]},
        }.get(path, {})


class BusinessMcpContractTests(unittest.TestCase):
    def test_empty_legacy_inventory_does_not_erase_the_declared_runtime_contract(self):
        contract = asyncio.run(tools._app_contract(Client(), "system-demo", "prod"))
        self.assertEqual(contract["runtime"]["health_path"], "/api/ready")
        self.assertEqual(contract["runtime"]["liveness_path"], "/api/health")
        self.assertEqual(contract["group"], {"name": "shared-group", "owner": "developer-a"})
        self.assertEqual(contract["variables"]["source"], "declared_contract")
        self.assertFalse(contract["variables"]["runtime_inventory_verified"])
        self.assertIn("PGPASSWORD", contract["variables"]["platform"])
        self.assertNotIn("MIGRATION_PGPASSWORD", contract["variables"]["platform"])
        self.assertNotIn("CHANGE_ME_NOT_EXPOSED", json.dumps(contract))
        self.assertTrue(any("local:up" in s for s in contract["local_steps"]))
        self.assertFalse(contract["managed_stack"]["email"]["external_delivery"])

    def test_declared_process_names_match_generated_manifests(self):
        config = {"BUSINESS_PROFILE": "demo", "BUSINESS_APP": "system-demo", "BUSINESS_DB_APP": "system-demo-db",
                  "BUSINESS_IDENTITY_APP": "system-demo-identity"}
        for template, app in [("business-base", "system-demo"), ("business-identity", "system-demo-identity"), ("business-postgres", "system-demo-db")]:
            contract = business_contract.describe(template, app)
            docs = business_stack.render(template, app, config, domain="example.com", image="example/app:demo")
            found = {}
            for doc in docs:
                if doc["kind"] != "Deployment":
                    continue
                spec = doc["spec"]["template"]["spec"]
                for c in spec["containers"] + spec.get("initContainers", []):
                    process = ("bootstrap" if c["name"] == "initialize" else "worker" if c["name"] == "worker" else
                               "web" if template == "business-base" and c["name"] == app else
                               "identity" if template == "business-identity" else "postgres" if template == "business-postgres" else None)
                    if process:
                        found[process] = sorted(e["name"] for e in c["env"])
            self.assertEqual(contract["environment_by_process"], found)

    def test_group_metadata_unavailable_does_not_invent_an_owner(self):
        class Restricted(Client):
            async def get(self, path, params=None):
                if path == "/groups":
                    raise ToolError("not permitted")
                return await super().get(path, params)
        result = asyncio.run(tools._app_contract(Restricted(), "system-demo", "prod"))
        self.assertIsNone(result["group"]["owner"])

    def test_database_and_identity_contracts_resolve_the_same_system(self):
        for template, name in [("business-base", "system-demo"), ("business-identity", "system-demo-identity"), ("business-postgres", "system-demo-db")]:
            contract = business_contract.describe(template, name)
            self.assertEqual(contract["components"]["app"], "system-demo")
            self.assertEqual(contract["ownership"]["source"], "authenticated_kaanbal_user")
        self.assertIsNone(business_contract.describe("nextjs-fullstack", "system-demo"))


if __name__ == "__main__":
    unittest.main()
