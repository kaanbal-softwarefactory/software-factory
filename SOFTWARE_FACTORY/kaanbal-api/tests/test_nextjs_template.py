"""Contrato de la plantilla Next.js full-stack y de sus stacks."""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "kaanbal-templates"
CONSOLE = ROOT / "kaanbal-console"
NEXTJS = TEMPLATES / "templates" / "backend" / "nextjs-fullstack"

sys.path.insert(0, str(ROOT / "kaanbal-api"))

from app.services.db_env import ENGINE_ALIASES, GENERIC_URL  # noqa: E402
from app.services.template_spec import TemplateSpec  # noqa: E402
from jinja2 import Template  # noqa: E402


def _read(*parts: str) -> str:
    return (NEXTJS.joinpath(*parts)).read_text(encoding="utf-8")


class NextjsCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((TEMPLATES / "catalog.json").read_text(encoding="utf-8"))
        self.template = next(
            item for item in self.catalog["templates"] if item["id"] == "nextjs-fullstack"
        )

    def test_catalog_registers_a_ready_backend_on_its_own_port(self):
        self.assertEqual(self.template["category"], "backend")
        self.assertEqual(self.template["port"], 3000)
        self.assertEqual(self.template["health_check_path"], "/api/health")
        self.assertEqual(self.template["service_type"], "http")
        self.assertEqual(self.template["status"], "ready")
        self.assertIn("scaffold", self.template["creation_modes"])

    def test_the_scaffold_lives_where_the_deployer_looks_for_it(self):
        # app_deployer busca templates/<category>/<id> cuando no hay scaffold.source.
        self.assertTrue(NEXTJS.is_dir())
        self.assertEqual(
            json.loads(_read("template.json"))["scaffold"]["template_files"], True
        )

    def test_scaffold_is_a_next_app_router_project(self):
        package = json.loads(_read("package.json"))
        self.assertIn("next", package["dependencies"])
        self.assertIn("react", package["dependencies"])
        self.assertIn("typescript", package["devDependencies"])
        self.assertEqual(package["scripts"]["build"], "next build")
        for path in ("app/page.tsx", "app/layout.tsx", "app/api/notes/route.ts", "lib/notes.ts"):
            self.assertTrue(NEXTJS.joinpath(*path.split("/")).exists(), path)

    def test_the_image_is_a_standalone_node_server_without_root(self):
        dockerfile = _read("Dockerfile")
        self.assertIn('output: "standalone"', _read("next.config.ts"))
        self.assertIn("FROM node:${NODE_VERSION}-alpine AS runtime", dockerfile)
        self.assertIn("/app/.next/standalone", dockerfile)
        self.assertIn("USER node", dockerfile)
        self.assertIn("EXPOSE 3000", dockerfile)
        self.assertIn('CMD ["node", "server.js"]', dockerfile)

    def test_health_answers_without_touching_the_database(self):
        health = _read("app", "api", "health", "route.ts")
        self.assertIn("export async function GET", health)
        self.assertNotIn("lib/notes", health)
        self.assertNotIn("mongodb", health)

    def test_the_data_layer_reads_the_names_kaanbal_publishes(self):
        notes = _read("lib", "notes.ts")
        for name in ENGINE_ALIASES["mongodb"]["URI"]:
            self.assertIn(name, notes, f"la plantilla ignora {name}")
        for name in ENGINE_ALIASES["postgres"]["URI"]:
            self.assertIn(name, notes, f"la plantilla ignora {name}")
        for component in ("HOST", "USER", "PASSWORD", "DATABASE"):
            for name in ENGINE_ALIASES["postgres"][component]:
                self.assertIn(name, notes, f"la plantilla ignora {name}")
        self.assertIn(GENERIC_URL, notes)

    def test_without_a_database_the_app_still_starts(self):
        notes = _read("lib", "notes.ts")
        self.assertIn('kind: "memory"', notes)

    def test_no_secret_is_committed_in_the_example_environment(self):
        env = _read(".env.example")
        self.assertNotRegex(env, re.compile(r"(?m)^[A-Z_]+=.*://[^:]+:(?!CHANGE_ME)[^@\s]+@"))
        self.assertIn("CHANGE_ME", env)

    def test_the_generated_secret_has_the_declared_length(self):
        secrets = TemplateSpec(self.template).generate_secrets("dev", "sample-app")
        self.assertEqual(len(secrets["APP_SECRET"]), 32)

    def test_scaffold_configuration_renders_the_node_version(self):
        dockerfile = Template(_read("Dockerfile")).render(APP_NAME="sample-app", node_version="22")
        self.assertIn("ARG NODE_VERSION=22", dockerfile)
        self.assertNotIn("{{", dockerfile)

    def test_the_manifests_expose_the_same_port_and_health_path(self):
        deployment = _read("k8s", "base", "deployment.yaml")
        service = _read("k8s", "base", "service.yaml")
        self.assertIn("containerPort: 3000", deployment)
        self.assertEqual(deployment.count("path: /api/health"), 3)  # liveness, readiness, startup
        self.assertIn("targetPort: 3000", service)


class NextjsStackTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((TEMPLATES / "catalog.json").read_text(encoding="utf-8"))
        self.stacks = {item["id"]: item for item in self.catalog["stacks"]}
        self.template_ids = {item["id"] for item in self.catalog["templates"]}

    def test_both_stacks_exist_and_name_real_templates(self):
        for stack_id, database in (("nextjs-mongo", "mongodb"), ("nextjs-postgres", "postgres")):
            stack = self.stacks[stack_id]
            templates = [component["template"] for component in stack["components"]]
            self.assertEqual(templates, [database, "nextjs-fullstack"])
            for template in templates:
                self.assertIn(template, self.template_ids)

    def test_the_app_is_the_homepage_and_the_database_stays_inside(self):
        for stack_id in ("nextjs-mongo", "nextjs-postgres"):
            components = {c["role"]: c for c in self.stacks[stack_id]["components"]}
            self.assertEqual(components["database"]["exposure"], "internal")
            self.assertEqual(components["backend"]["exposure"], "public")
            self.assertEqual(components["backend"]["binds"], "database")
            self.assertTrue(components["backend"]["can_be_homepage"])

    def test_a_full_stack_app_needs_no_separate_frontend(self):
        for stack_id in ("nextjs-mongo", "nextjs-postgres"):
            roles = [c["role"] for c in self.stacks[stack_id]["components"]]
            self.assertNotIn("frontend", roles)


class ConsoleCatalogTests(unittest.TestCase):
    """La consola no debe ofrecer plantillas que el catálogo no tiene."""

    def test_the_dashboard_showcase_points_at_real_templates(self):
        catalog = json.loads((TEMPLATES / "catalog.json").read_text(encoding="utf-8"))
        known = {item["id"] for item in catalog["templates"]}
        dashboard = (CONSOLE / "src" / "views" / "Dashboard.vue").read_text(encoding="utf-8")
        offered = re.findall(r"templateId: '([^']+)'", dashboard)
        self.assertTrue(offered)
        for template_id in offered:
            self.assertIn(template_id, known, f"el panel ofrece '{template_id}', que no está en el catálogo")


if __name__ == "__main__":
    unittest.main()
