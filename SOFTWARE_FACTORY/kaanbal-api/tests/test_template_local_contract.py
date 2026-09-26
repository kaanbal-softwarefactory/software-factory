"""Contrato de desarrollo local en los templates.

Kaanbal crea el repositorio pasando cada archivo por los mismos reemplazos y por
Jinja (AppDeployer._copy_template_code). Estas pruebas renderizan los templates
igual que el deployer y comprueban lo que recibe quien clona el repo: los
nombres de variables que Kaanbal inyecta de verdad, y nada de sintaxis de
plantilla a medio resolver.
"""

import os
import sys
import unittest
from pathlib import Path

try:
    from jinja2 import Template
except ImportError:  # entorno sin las dependencias de la API
    Template = None

TEMPLATES = Path(__file__).resolve().parents[2] / "kaanbal-templates" / "templates"
BACKEND = TEMPLATES / "backend" / "fastapi-api"
FRONTEND = TEMPLATES / "frontend" / "vue3-spa"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


needs_jinja = unittest.skipIf(Template is None, "jinja2 no está instalado (pip install -r requirements.txt)")


def scaffold(path: Path, app_name: str = "orbit-api", domain: str = "north-star-bay.store", **config) -> str:
    """Mismo tratamiento que da el deployer a cada archivo del template."""
    content = path.read_text(encoding="utf-8")
    for old, new in (("placeholder-app", app_name), ("example.com", domain)):
        content = content.replace(old, new)
    return Template(content).render(APP_NAME=app_name, **config)


@needs_jinja
class BackendContractTests(unittest.TestCase):
    def test_the_api_reads_the_names_kaanbal_injects(self):
        """Los mismos nombres que publica app/services/db_env.py."""
        from app.services import db_env

        rendered = scaffold(BACKEND / "db.py")
        for name in ("MONGO_URI", "MONGODB_URI", "DATABASE_URL"):
            self.assertIn(name, rendered)
            self.assertIn(name, db_env.CANONICAL_NAMES)

    def test_the_first_run_creates_the_database(self):
        """El caso que siempre pasa: nadie creó la base todavía."""
        rendered = scaffold(BACKEND / "db.py")
        self.assertIn("create_index", rendered)
        self.assertIn("CREATE TABLE IF NOT EXISTS", rendered)

    def test_local_defaults_point_to_docker_compose(self):
        rendered = scaffold(BACKEND / "db.py")
        self.assertIn("mongodb://localhost:27017", rendered)
        self.assertIn("postgresql://postgres:postgres@localhost:5432", rendered)

    def test_env_example_never_carries_a_real_secret(self):
        rendered = scaffold(BACKEND / ".env.example")
        self.assertIn("MONGO_URI=mongodb://localhost", rendered)
        self.assertNotIn("svc.cluster.local", rendered)

    def test_dotenv_is_ignored_by_git(self):
        self.assertIn(".env", scaffold(BACKEND / ".gitignore").split("\n"))

    def test_compose_follows_the_engine_of_the_stack(self):
        mongo = scaffold(BACKEND / "docker-compose.yml")
        postgres = scaffold(BACKEND / "docker-compose.yml", DB_ENGINE="postgres")
        self.assertIn("mongo:7", mongo)
        self.assertNotIn("postgres:16", mongo)
        self.assertIn("postgres:16", postgres)
        self.assertNotIn("mongo:7", postgres)

    def test_app_name_replaces_the_placeholder(self):
        self.assertIn('APP_NAME = os.getenv("APP_NAME", "orbit-api")', scaffold(BACKEND / "db.py"))


@needs_jinja
class FrontendContractTests(unittest.TestCase):
    def test_production_env_gets_the_real_api_url(self):
        rendered = scaffold(FRONTEND / ".env.production", API_URL="https://orbit-api.north-star-bay.store")
        self.assertIn("VITE_API_URL=https://orbit-api.north-star-bay.store", rendered)

    def test_without_a_stack_the_url_is_empty_and_the_app_uses_same_origin(self):
        self.assertIn("VITE_API_URL=", scaffold(FRONTEND / ".env.production"))
        self.assertIn("import.meta.env.VITE_API_URL || ''", scaffold(FRONTEND / "src" / "App.vue"))

    def test_development_env_points_to_the_local_api(self):
        self.assertIn("VITE_API_URL=http://localhost:8000", scaffold(FRONTEND / ".env.development"))

    def test_vue_interpolation_survives_the_scaffold(self):
        """El deployer pasa todo por Jinja: sin protección, {{ }} de Vue se borraba."""
        rendered = scaffold(FRONTEND / "src" / "App.vue")
        self.assertIn("{{ health.status }}", rendered)
        self.assertIn("{{ item.name }}", rendered)
        self.assertNotIn("raw %}", rendered)


@needs_jinja
class AgentsContractTests(unittest.TestCase):
    """El archivo que lee el agente de quien clona el repo."""

    def test_both_templates_ship_instructions(self):
        for path in (BACKEND / "AGENTS.md", FRONTEND / "AGENTS.md"):
            self.assertTrue(path.exists(), f"falta {path.name}")

    def test_they_survive_the_scaffold_without_template_syntax(self):
        for path in (BACKEND / "AGENTS.md", FRONTEND / "AGENTS.md"):
            rendered = scaffold(path)
            self.assertNotIn("{%", rendered)
            self.assertIn("orbit-api", rendered)

    def test_backend_instructions_name_the_variables_and_the_first_run(self):
        rendered = scaffold(BACKEND / "AGENTS.md")
        self.assertIn("MONGO_URI", rendered)
        self.assertIn("DATABASE_URL", rendered)
        self.assertIn("docker compose up", rendered)
        self.assertIn("idempotente", rendered)

    def test_frontend_instructions_explain_the_two_env_files(self):
        rendered = scaffold(FRONTEND / "AGENTS.md")
        self.assertIn(".env.development", rendered)
        self.assertIn(".env.production", rendered)
        self.assertIn("VITE_API_URL", rendered)


if __name__ == "__main__":
    unittest.main()
