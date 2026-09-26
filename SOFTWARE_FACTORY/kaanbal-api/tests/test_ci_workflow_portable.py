"""
El workflow de CI que genera Kaanbal debe ser portable entre apps y células.

Caso real (producción, 2026-09-22): un agente subió a acme-org/homepage
y /enterprise código traído de otro proyecto, con su workflow. Ese workflow
tenía escritos la cuenta de Docker Hub (andresupmh), el infra-gitops de otra org
(your-org) y otro nombre de app (por1). Docker Hub rechazó
el push; de haber pasado, habría escrito en el repo de otra organización.

Standalone: py tests/test_ci_workflow_portable.py
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "app.db" not in sys.modules:
    _db_stub = types.ModuleType("app.db")
    _db_stub.get_db = lambda: None
    sys.modules["app.db"] = _db_stub

from app.services.git_provider import GitHubProvider  # noqa: E402

CELL = {"docker": "cuenta-de-esta-celula", "org": "org-de-esta-celula", "app": "mi-app"}


def _workflow():
    provider = GitHubProvider({"github_org": CELL["org"], "github_token": "t", "git_token": "t"})
    _, content = provider.generate_ci_yaml(
        app_name=CELL["app"],
        environments=["prod"],
        image="node:20",
        build_steps="",
        dockerhub_user=CELL["docker"],
        workspace_or_org=CELL["org"],
        pipeline_email="pipeline@example.com",
        infra_repo="infra-gitops",
        pkg_manager="npm",
    )
    return content


def _executable_lines(content):
    """Sin comentarios ni el título: lo que realmente decide a dónde se publica."""
    return [
        line for line in content.splitlines()
        if not line.lstrip().startswith("#") and not line.startswith("name:")
    ]


class PortableWorkflowTests(unittest.TestCase):
    def test_no_cell_specific_value_is_hardcoded(self):
        body = "\n".join(_executable_lines(_workflow()))
        for value in CELL.values():
            self.assertNotIn(value, body, f"'{value}' quedó escrito en el workflow")

    def test_values_come_from_the_repo_running_it(self):
        content = _workflow()
        self.assertIn("APP_NAME: ${{ github.event.repository.name }}", content)
        self.assertIn("DOCKERHUB_USER: ${{ secrets.DOCKERHUB_USERNAME }}", content)
        self.assertIn("github.com/${GITHUB_REPOSITORY_OWNER}/infra-gitops.git", content)

    def test_image_and_overlay_use_the_same_resolved_values(self):
        content = _workflow()
        self.assertIn("tags: ${{ env.DOCKERHUB_USER }}/${{ env.APP_NAME }}:", content)
        self.assertIn("cd apps/${APP_NAME}/overlays/$DEPLOY_ENV", content)
        self.assertIn("newName: ${DOCKERHUB_USER}/${APP_NAME}", content)


if __name__ == "__main__":
    unittest.main()
