"""Contrato de la plantilla Laravel sin tocar los templates existentes."""

import base64
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "kaanbal-templates"
LARAVEL = TEMPLATES / "templates" / "backend" / "laravel-inertia-react"

sys.path.insert(0, str(ROOT / "kaanbal-api"))

from app.services.template_spec import TemplateSpec  # noqa: E402
from app.services.project_runtime import detect_project_runtime  # noqa: E402
from jinja2 import Template  # noqa: E402


class LaravelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((TEMPLATES / "catalog.json").read_text(encoding="utf-8"))
        self.template = next(
            item for item in self.catalog["templates"]
            if item["id"] == "laravel-inertia-react"
        )

    def test_catalog_registers_a_ready_backend(self):
        self.assertEqual(self.template["category"], "backend")
        self.assertEqual(self.template["port"], 8000)
        self.assertEqual(self.template["health_check_path"], "/health")
        self.assertIn("scaffold", self.template["creation_modes"])

    def test_scaffold_uses_composer_inertia_and_react(self):
        composer = json.loads((LARAVEL / "composer.json").read_text(encoding="utf-8"))
        package = json.loads((LARAVEL / "package.json").read_text(encoding="utf-8"))
        self.assertIn("laravel/framework", composer["require"])
        self.assertIn("inertiajs/inertia-laravel", composer["require"])
        self.assertIn("initialize", composer["scripts"])
        self.assertIn("@inertiajs/react", package["dependencies"])
        self.assertIn("react", package["dependencies"])

    def test_scaffold_has_php_runtime_health_test_and_mvvm_layers(self):
        dockerfile = (LARAVEL / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("php:${PHP_VERSION}-cli-alpine", dockerfile)
        self.assertIn("composer install", dockerfile)
        self.assertTrue((LARAVEL / "tests" / "Feature" / "HealthTest.php").exists())
        self.assertTrue((LARAVEL / "app" / "ViewModels" / "HomeViewModel.php").exists())
        self.assertTrue((LARAVEL / "resources" / "js" / "view-models" / "use-home-view-model.ts").exists())
        self.assertIn("/health", (LARAVEL / "routes" / "web.php").read_text(encoding="utf-8"))

    def test_app_key_is_a_valid_laravel_key(self):
        secrets = TemplateSpec(self.template).generate_secrets("dev", "sample-app")
        key = secrets["APP_KEY"]
        self.assertRegex(key, r"^base64:[A-Za-z0-9+/]{43}=$")
        self.assertEqual(len(base64.b64decode(key.removeprefix("base64:"))), 32)

    def test_no_secret_is_committed_in_the_example_environment(self):
        env = (LARAVEL / ".env.example").read_text(encoding="utf-8")
        self.assertRegex(env, r"(?m)^APP_KEY=$")
        self.assertNotRegex(env, re.compile(r"(?m)^APP_KEY=base64:"))

    def test_scaffold_configuration_renders_php_version_and_app_name(self):
        dockerfile = Template((LARAVEL / "Dockerfile").read_text(encoding="utf-8")).render(
            APP_NAME="sample-app", php_version="8.4"
        )
        readme = (LARAVEL / "README.md").read_text(encoding="utf-8").replace(
            "placeholder-app", "sample-app"
        )
        self.assertIn("ARG PHP_VERSION=8.4", dockerfile)
        self.assertIn("FROM php:${PHP_VERSION}-cli-alpine", dockerfile)
        self.assertNotIn("{{", dockerfile)
        self.assertIn("# sample-app", readme)


class LaravelGeneratorTests(unittest.TestCase):
    def test_composer_takes_precedence_in_a_full_stack_laravel_project(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            app_path = Path(directory)
            (app_path / "composer.json").write_text("{}", encoding="utf-8")
            (app_path / "package.json").write_text("{}", encoding="utf-8")
            self.assertEqual(detect_project_runtime(str(app_path)), "php")


if __name__ == "__main__":
    unittest.main()
