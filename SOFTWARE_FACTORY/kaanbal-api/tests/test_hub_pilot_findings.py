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


class SecondIterationTests(HubCase):
    """Segunda ronda del piloto: lo que se aprendió coordinando W1 entre Claude y Codex."""

    async def join(self, agent, person):
        return (await routes.join("app-x", routes.JoinBody(agent=agent, harness="claude"), person))["session_id"]

    async def test_a_returning_agent_does_not_receive_again_what_it_read_or_sent(self):
        await self.upload_phases()
        claude = await self.join("claude-api", self.beto)
        codex = await self.join("codex-uiux", self.ana)
        await routes.send_message("app-x", routes.MessageBody(text="hola a todos", to="all", session_id=claude), self.beto)
        await routes.send_message("app-x", routes.MessageBody(text="revisa T03", to="claude-api", session_id=codex), self.ana)
        first = await routes.heartbeat(claude, routes.SyncBody(), self.beto)
        self.assertEqual([m["text"] for m in first["messages"]], ["revisa T03"])  # no recibe su propio 'all'
        await routes.leave(claude, routes.LeaveBody(summary="Me voy"), self.beto)
        again = await self.join("claude-api", self.beto)
        self.assertEqual((await routes.heartbeat(again, routes.SyncBody(), self.beto))["messages"], [])

    async def test_any_agent_action_counts_as_a_heartbeat(self):
        await self.upload_phases()
        session = await self.join("claude-api", self.beto)
        doc = next(d for d in self.db["hub_sessions"].docs if d["_id"] == session)
        doc["last_seen"] = doc["last_seen"].replace(year=2000)
        await routes.write_note("app-x", routes.NoteBody(path="informe.md", content="x", session_id=session), self.beto)
        doc = next(d for d in self.db["hub_sessions"].docs if d["_id"] == session)
        self.assertGreater(doc["last_seen"].year, 2000)

    async def test_pr_url_only_accepts_a_created_pull_request(self):
        await self.upload_phases()
        session = await self.join("claude-api", self.beto)
        await routes.claim_task("T01", routes.ClaimBody(session_id=session), self.beto)
        compare = "https://github.com/example/app/compare/main...claude/t01?expand=1"
        with self.assertRaises(HTTPException) as caught:
            await routes.update_task("T01", routes.TaskUpdate(session_id=session, pr_url=compare), self.beto)
        self.assertIn("compare", caught.exception.detail)
        updated = await routes.update_task("T01", routes.TaskUpdate(session_id=session, pr_url="https://github.com/example/app/pull/7"), self.beto)
        self.assertEqual(updated["pr_url"], "https://github.com/example/app/pull/7")

    async def test_people_are_told_once_what_to_merge_when_the_objective_is_met(self):
        await self.upload_phases()
        await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="self", objective="Auditoría",
                                                                  scope_tasks=["T01"]), self.ana)
        session = await self.join("claude-api", self.beto)
        await routes.claim_task("T01", routes.ClaimBody(session_id=session), self.beto)
        await routes.update_task("T01", routes.TaskUpdate(session_id=session, branch="claude/t01-audit"), self.beto)
        await routes.update_task("T01", routes.TaskUpdate(session_id=session, status="done"), self.beto)
        people = [m for m in self.db["hub_messages"].docs if m["to"] == "people"]
        self.assertEqual(len(people), 1)
        self.assertIn("Objetivo cumplido", people[0]["text"])
        self.assertIn("claude/t01-audit", people[0]["text"])
        overview = await routes.project_overview("app-x")
        self.assertEqual(overview["objective"]["deliveries"], [{"task": "T01", "branch": "claude/t01-audit", "pr_url": None}])


class ToolFeedbackTests(unittest.TestCase):
    def test_validation_errors_become_one_sentence_per_field(self):
        from app.mcp.loopback import validation_message
        message = validation_message([
            {"type": "string_too_long", "loc": ["body", "status"], "msg": "String should have at most 300 characters",
             "ctx": {"max_length": 300}},
            {"type": "missing", "loc": ["body", "summary"], "msg": "Field required"},
        ])
        self.assertEqual(message, "Revisa los datos: status: máximo 300 caracteres; summary: falta.")

    def test_the_start_prompt_names_the_agent_and_checks_repository_access(self):
        from app.services import agent_hub_guides as guides
        prompt = guides.agent_start_prompt("app-x", "codex", "diseño", "codex-uiux")
        self.assertIn("agent='codex-uiux'", prompt)
        self.assertIn("git ls-remote", prompt)
        self.assertIn("compare va en la nota", prompt)
