"""Integración directa a main: compuertas, checks, merge y seguimiento del despliegue."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import hub as routes
from app.services import hub_integration as integration

try:  # discover -s tests (como en CI) o python -m unittest tests.test_hub_integration
    from test_hub_routes import HubCase
except ImportError:
    from tests.test_hub_routes import HubCase

SHA = "a" * 40
MERGE = "b" * 40
DONE = {"_id": "t1", "key": "T09", "title": "API", "status": "done", "branch": "claude/t09",
        "assignee_agent": "claude-api", "reviewed_by": "codex-uiux"}


class FakeGitHub:
    def __init__(self, checks=([{"name": "ci", "status": "completed", "conclusion": "success"}], []),
                 merge=MERGE, runs=None, conflict=False):
        self._checks, self._merge, self._conflict = checks, merge, conflict
        self._runs = runs if runs is not None else [{"name": "deploy", "status": "completed", "conclusion": "success"}]
        self.merged = None

    async def default_branch(self, repo):
        return "main"

    async def branch_head(self, repo, branch):
        return SHA

    async def checks(self, repo, sha):
        return self._checks

    async def merge(self, repo, base, head, message):
        if self._conflict:
            raise integration.IntegrationBlocked("Conflicto al fusionar")
        self.merged = (base, head, message)
        return self._merge

    async def workflow_runs(self, repo, sha):
        return self._runs


async def healthy(app):
    return {"health": {"status": "Healthy"}, "sync": {"status": "Synced"}, "images": [f"user/app:prod-{MERGE[:7]}"]}


async def no_sleep(_):
    return None


class PureRulesTests(unittest.TestCase):
    def test_repository_names_come_from_github_urls_only(self):
        self.assertEqual(integration.repo_from_url("https://github.com/example/app.git"), "example/app")
        self.assertEqual(integration.repo_from_url("git@github.com:example/app.git"), "example/app")
        self.assertIsNone(integration.repo_from_url("https://bitbucket.org/example/app.git"))

    def test_only_cross_reviewed_tasks_with_their_own_branch_are_integrated(self):
        self.assertIsNone(integration.precheck(DONE))
        self.assertIn("done", integration.precheck({**DONE, "status": "review"}))
        self.assertIn("rama", integration.precheck({**DONE, "branch": "main"}))
        self.assertIn("otro agente", integration.precheck({**DONE, "reviewed_by": "claude-api"}))
        self.assertIn("otro agente", integration.precheck({**DONE, "reviewed_by": None}))

    def test_checks_must_exist_and_be_green(self):
        ok = [{"name": "ci", "status": "completed", "conclusion": "success"}]
        self.assertEqual(integration.checks_verdict([], [], True)[0], "missing")
        self.assertEqual(integration.checks_verdict([], [], False)[0], "ok")
        self.assertEqual(integration.checks_verdict(ok, [], True)[0], "ok")
        self.assertEqual(integration.checks_verdict([{"name": "ci", "status": "in_progress"}], [], True)[0], "pending")
        self.assertEqual(integration.checks_verdict(ok + [{"name": "lint", "status": "completed", "conclusion": "failure"}], [], True)[0], "failed")
        self.assertEqual(integration.checks_verdict(ok, [{"context": "legacy", "state": "error"}], True)[0], "failed")

    def test_a_deploy_counts_only_when_argo_runs_the_new_image_healthy(self):
        base = {"health": {"status": "Healthy"}, "sync": {"status": "Synced"}}
        self.assertEqual(integration.deploy_verdict({**base, "images": [f"x:prod-{MERGE[:7]}"]}, MERGE)[0], "deployed")
        self.assertEqual(integration.deploy_verdict({**base, "images": ["x:prod-0000000"]}, MERGE)[0], "waiting")
        self.assertEqual(integration.deploy_verdict({"health": {"status": "Degraded"}, "sync": {}}, MERGE)[0], "unhealthy")
        self.assertEqual(integration.deploy_verdict(None, MERGE)[0], "waiting")


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def run_with(self, gh, task=DONE, require_checks=True, argo=healthy):
        states = []

        async def report(state, detail, extra):
            states.append((state, detail))

        final = await integration.run(task, "example/app", "app", gh, argo, report, require_checks=require_checks,
                                      sleep=no_sleep, check_wait=3, deploy_wait=3)
        return final, states

    async def test_green_checks_merge_into_main_and_follow_the_deploy(self):
        gh = FakeGitHub()
        final, states = await self.run_with(gh)
        self.assertEqual(final, "deployed")
        self.assertEqual([s for s, _ in states], ["checking", "merged", "deployed"])
        self.assertEqual(gh.merged[:2], ("main", "claude/t09"))
        self.assertIn("revisó codex-uiux", gh.merged[2])

    async def test_missing_red_or_conflicting_work_is_not_merged(self):
        for gh, expected in ((FakeGitHub(checks=([], [])), "no tiene checks"),
                             (FakeGitHub(checks=([{"name": "ci", "status": "completed", "conclusion": "failure"}], [])), "rojo"),
                             (FakeGitHub(conflict=True), "Conflicto")):
            final, states = await self.run_with(gh)
            self.assertEqual(final, "blocked")
            self.assertIn(expected, states[-1][1])
            self.assertIsNone(gh.merged)

    async def test_a_failed_pipeline_or_degraded_app_is_reported(self):
        failed = FakeGitHub(runs=[{"name": "deploy", "status": "completed", "conclusion": "failure", "html_url": "u"}])
        self.assertEqual((await self.run_with(failed))[0], "deploy_failed")

        async def degraded(app):
            return {"health": {"status": "Degraded", "message": "CrashLoopBackOff"}, "sync": {"status": "Synced"}}

        final, states = await self.run_with(FakeGitHub(), argo=degraded)
        self.assertEqual(final, "deploy_failed")
        self.assertIn("CrashLoopBackOff", states[-1][1])

    async def test_no_pipeline_for_the_merge_is_reported_as_unknown(self):
        self.assertEqual((await self.run_with(FakeGitHub(runs=[])))[0], "deploy_unknown")


def person(can=True):
    return SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(
        username="ana", superadmin=False, token_name=None, via_token=False, can=lambda permission: can)))


class SettingsAndTriggerTests(HubCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.db.apps.insert_one({"_id": "a1", "name": "app-x-web", "app_group": "app-x",
                                       "repo_url": "https://github.com/example/app-x-web.git"})

    async def test_turning_on_integration_needs_the_critical_permission_and_cross_review(self):
        await self.upload_phases()
        with self.assertRaises(HTTPException) as denied:
            await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="peer", integration="auto"), person(can=False))
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException) as self_review:
            await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="self", integration="auto"), person())
        self.assertEqual(self_review.exception.status_code, 422)
        result = await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="peer", integration="auto"), person())
        self.assertEqual(result["settings"]["integration"], "auto")
        brief = await routes.project_briefing("app-x")
        self.assertIn("Integración automática", " ".join(brief["protocol"]))

    async def test_a_cross_reviewed_task_starts_its_integration_when_closed(self):
        await self.upload_phases()
        await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="peer", integration="auto"), person())
        author = (await routes.join("app-x", routes.JoinBody(agent="claude-api", harness="claude"), self.beto))["session_id"]
        await routes.claim_task("T01", routes.ClaimBody(session_id=author), self.beto)
        await routes.update_task("T01", routes.TaskUpdate(session_id=author, status="review", branch="claude/t01"), self.beto)
        reviewer = (await routes.join("app-x", routes.JoinBody(agent="codex-uiux", harness="codex"), self.ana))["session_id"]
        started = []
        with patch.object(routes, "_start_integration", side_effect=lambda task_id: started.append(task_id) or True):
            await routes.update_task("T01", routes.TaskUpdate(session_id=reviewer, status="done"), self.ana)
        self.assertEqual(len(started), 1)

    async def test_manual_integration_refuses_unreviewed_work(self):
        await self.upload_phases()
        task_id = (await routes.list_tasks("app-x"))["tasks"][0]["id"]
        with self.assertRaises(HTTPException) as caught:
            await routes.integrate_task(task_id, person())
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
