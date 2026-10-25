"""Fallas encontradas en el piloto con Codex (nube) y Claude: cada una con su prueba."""

import unittest

from fastapi import HTTPException

from app.middleware.acl import mcp_auth_problem
from app.routers import hub as routes
from app.routers.mcp import forwarded_scheme

try:  # discover -s tests (como en CI) o python -m unittest tests.test_hub_pilot_findings
    from test_hub_routes import HubCase
except ImportError:
    from tests.test_hub_routes import HubCase


class SessionHandoverTests(HubCase):
    async def join(self, agent, person, branch=""):
        body = routes.JoinBody(agent=agent, harness="codex", branch=branch)
        return (await routes.join("app-x", body, person))["session_id"]

    async def test_a_blocked_task_is_released_when_its_session_leaves(self):
        await self.upload_phases()
        first = await self.join("codex-uiux", self.ana)
        await routes.claim_task("T03", routes.ClaimBody(session_id=first), self.ana)
        await routes.update_task("T03", routes.TaskUpdate(session_id=first, status="blocked", note="Sin acceso a GitHub"), self.ana)
        left = await routes.leave(first, routes.LeaveBody(summary="Me voy"), self.ana)
        self.assertEqual(left["released_tasks"], ["T03"])
        task = (await routes.list_tasks("app-x", status="blocked"))["tasks"][0]
        self.assertEqual((task["key"], task["assignee_session"]), ("T03", None))  # sigue bloqueada, sin dueño
        second = await self.join("codex-uiux", self.ana)
        claimed = await routes.claim_task("T03", routes.ClaimBody(session_id=second), self.ana)
        self.assertEqual(claimed["assignee_session"], second)

    async def test_a_task_held_by_a_closed_session_can_be_taken_back(self):
        await self.upload_phases()
        first = await self.join("codex-uiux", self.ana)
        await routes.claim_task("T03", routes.ClaimBody(session_id=first), self.ana)
        await routes.update_task("T03", routes.TaskUpdate(session_id=first, status="blocked"), self.ana)
        await routes.leave(first, routes.LeaveBody(summary="Me voy", release_tasks=False), self.ana)
        second = await self.join("codex-uiux", self.ana)
        claimed = await routes.claim_task("T03", routes.ClaimBody(session_id=second), self.ana)
        self.assertEqual(claimed["assignee_agent"], "codex-uiux")

    async def test_a_task_held_by_an_active_agent_explains_who_has_it(self):
        await self.upload_phases()
        holder = await self.join("codex-uiux", self.ana)
        await routes.claim_task("T03", routes.ClaimBody(session_id=holder), self.ana)
        await routes.update_task("T03", routes.TaskUpdate(session_id=holder, status="blocked"), self.ana)
        other = await self.join("claude-api", self.beto)
        with self.assertRaises(HTTPException) as caught:
            await routes.claim_task("T03", routes.ClaimBody(session_id=other), self.beto)
        self.assertIn("La tiene codex-uiux", caught.exception.detail["message"])

    async def test_leaving_does_not_clear_a_task_reassigned_in_the_meantime(self):
        """Carrera señalada por codex-uiux: entre leer y soltar, otra sesión toma la tarea."""
        await self.upload_phases()
        first = await self.join("codex-uiux", self.ana)
        await routes.claim_task("T03", routes.ClaimBody(session_id=first), self.ana)
        tasks = self.db["hub_tasks"]
        original = tasks.update_one

        async def reassign_then_update(query, change, upsert=False):
            if change.get("$push", {}).get("notes", {}).get("text") == "Liberada al cerrar sesión.":
                doc = next(d for d in tasks.docs if d.get("key") == "T03")
                doc.update(assignee_session="f" * 16, assignee_agent="claude-api", updated_at=doc["updated_at"].replace(year=2099))
            return await original(query, change, upsert)

        tasks.update_one = reassign_then_update
        left = await routes.leave(first, routes.LeaveBody(summary="Me voy"), self.ana)
        tasks.update_one = original
        self.assertEqual(left["released_tasks"], [])
        doc = next(d for d in tasks.docs if d.get("key") == "T03")
        self.assertEqual((doc["assignee_agent"], doc["status"]), ("claude-api", "in_progress"))

    async def test_claiming_does_not_copy_the_session_branch_into_the_task(self):
        await self.upload_phases()
        session = await self.join("claude-api", self.beto, branch="claude/t03-api-contract")
        claimed = await routes.claim_task("T01", routes.ClaimBody(session_id=session), self.beto)
        self.assertIsNone(claimed["branch"])


class ConnectionDiagnosticsTests(unittest.TestCase):
    def test_mcp_explains_why_the_credential_was_rejected_without_echoing_it(self):
        self.assertIn("Falta el token", mcp_auth_problem(""))
        self.assertIn("repite 'Bearer'", mcp_auth_problem("Bearer Bearer kbl_abc123"))
        self.assertIn("forma 'Bearer", mcp_auth_problem("kbl_abc123"))
        message = mcp_auth_problem("Bearer kbl_secretvalue")
        self.assertIn("no es válido", message)
        self.assertNotIn("secretvalue", message)

    def test_https_behind_a_tunnel_is_detected(self):
        self.assertEqual(forwarded_scheme({"x-forwarded-proto": "http", "cf-visitor": '{"scheme":"https"}'}, "http"), "https")
        self.assertEqual(forwarded_scheme({"x-forwarded-proto": "https,http"}, "http"), "https")
        self.assertEqual(forwarded_scheme({"x-forwarded-proto": "http", "x-forwarded-port": "443"}, "http"), "https")
        self.assertEqual(forwarded_scheme({"forwarded": "for=203.0.113.7;proto=https"}, "http"), "https")
        self.assertEqual(forwarded_scheme({"x-forwarded-proto": "http"}, "http"), "http")
        self.assertEqual(forwarded_scheme({}, "http"), "http")


if __name__ == "__main__":
    unittest.main()
