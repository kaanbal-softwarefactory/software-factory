"""HUB2: resumen compartido, reportes a Software Factory y contexto del proyecto."""

import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import hub as routes
from app.services import agent_hub as hub
from app.services import hub_workspace as workspace
from tests.test_hub_routes import HubCase, request


def agent_request(username):
    """Una persona a través de un token de agente (via_token)."""
    return SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(
        username=username, superadmin=False, token_name=f"{username}-token", via_token=True)))


class SharedContextTests(HubCase):
    async def test_checkpoints_build_the_shared_summary_one_per_agent(self):
        joined = await routes.join("app-x", routes.JoinBody(agent="astra", harness="codex"), self.ana)
        sid = joined["session_id"]
        await routes.save_checkpoint("app-x", routes.CheckpointBody(session_id=sid, summary="Landing a medias",
                                                                    next_steps=["Terminar portafolio"]), self.ana)
        await routes.save_checkpoint("app-x", routes.CheckpointBody(session_id=sid, summary="Landing lista",
                                                                    decisions=["Fotos placeholder"]), self.ana)
        overview = await routes.project_overview("app-x")
        checkpoints = overview["workspace"]["checkpoints"]
        self.assertEqual([c["summary"] for c in checkpoints], ["Landing lista"])  # el último del agente reemplaza
        self.assertEqual(checkpoints[0]["decisions"], ["Fotos placeholder"])
        self.assertIn("no recibe automáticamente", overview["workspace"]["conversation_notice"])
        brief = await routes.project_briefing("app-x")
        self.assertEqual(brief["workspace"]["checkpoints"][0]["agent"], "astra")

    async def test_a_checkpoint_needs_a_session_of_that_project(self):
        other = await routes.join("app-y", routes.JoinBody(agent="astra", harness="codex"), self.ana)
        with self.assertRaises(HTTPException) as caught:
            await routes.save_checkpoint("app-x", routes.CheckpointBody(session_id=other["session_id"], summary="x"), self.ana)
        self.assertEqual(caught.exception.status_code, 422)
        with self.assertRaises(HTTPException):
            await routes.save_checkpoint("app-x", routes.CheckpointBody(session_id="", summary="x"), self.ana)

    async def test_feedback_lands_in_software_factory_with_its_origin_in_both_traces(self):
        joined = await routes.join("app-x", routes.JoinBody(agent="astra", harness="codex"), self.ana)
        result = await routes.report_feedback("app-x", routes.FeedbackBody(
            session_id=joined["session_id"], title="hub_read_file no muestra imágenes en Codex",
            description="La imagen llega pero el cliente no la renderiza.", kind="friction"), self.ana)
        task = result["task"]
        self.assertEqual((task["status"], task["origin"]["group"], task["origin"]["agent"]), ("proposed", "app-x", "astra"))
        platform = await routes.trace(workspace.PLATFORM_GROUP, view="list", day=None, agent=None, kind=None, session_id=None, limit=50)
        origin = await routes.trace("app-x", view="list", day=None, agent=None, kind=None, session_id=None, limit=50)
        self.assertTrue(any(e["kind"] == "feedback" and "app-x" in e["text"] for e in platform["events"]))
        self.assertTrue(any(e["kind"] == "feedback" and task["key"] in e["text"] for e in origin["events"]))
        projects = {p["group"]: p for p in (await routes.list_projects())["projects"]}
        self.assertEqual(projects[workspace.PLATFORM_GROUP]["scope"], "platform")

    async def test_an_agent_token_reports_only_from_its_session(self):
        with self.assertRaises(HTTPException) as caught:
            await routes.report_feedback("app-x", routes.FeedbackBody(title="x", description="y"), agent_request("ana"))
        self.assertEqual(caught.exception.status_code, 403)


class SettingsCompatibilityTests(unittest.TestCase):
    def test_integration_keeps_targeting_main_unless_a_project_chooses_dev(self):
        settings = hub.work_settings({})
        self.assertEqual((settings["integration_env"], settings["integration_branch"]), ("prod", ""))
        legacy = hub.work_settings({"integration": "auto", "integration_app": "web"})  # guardado antes de HUB2
        self.assertEqual((legacy["integration_env"], legacy["integration_branch"]), ("prod", ""))
        dev = hub.work_settings({"integration_env": "dev"})
        self.assertEqual((dev["integration_env"], dev["integration_branch"]), ("dev", "develop"))

    def test_verification_path_stays_inside_the_app(self):
        with self.assertRaises(ValidationError):
            routes.TaskUpdate(session_id="s", verification_path="//evil.example.com/")
        with self.assertRaises(ValidationError):
            routes.TaskUpdate(session_id="s", verification_path="https://example.com/")
        self.assertEqual(routes.TaskUpdate(session_id="s", verification_path="/servicios").verification_path, "/servicios")


class ServiceCardTests(unittest.TestCase):
    def test_databases_and_internal_services_have_no_public_url(self):
        cards = workspace.service_cards([
            {"name": "web", "environments": ["prod"], "template": "business-base"},
            {"name": "web-db", "environments": ["prod"], "template": "business-postgres"},
            {"name": "api", "environments": ["prod"], "exposure": "internal"}], "example.com")
        urls = {c["name"]: c["urls"] for c in cards}
        self.assertEqual(urls, {"web": {"prod": "https://web.example.com"}, "web-db": {}, "api": {}})


if __name__ == "__main__":
    unittest.main()
