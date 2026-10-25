"""Regressions for objective enforcement and consistent agent/console context."""
from datetime import timedelta
from fastapi import HTTPException
from test_hub_routes import HubCase, routes


class CoordinationTests(HubCase):
    async def agent(self, name="author", person=None):
        return (await routes.join("app-x", routes.JoinBody(agent=name), person or self.ana))["session_id"]

    async def test_scope_cannot_be_bypassed_with_a_task_key(self):
        await self.upload_phases()
        await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", scope_tasks=["T01"]), self.ana)
        sid = await self.agent()
        with self.assertRaises(HTTPException) as error:
            await routes.claim_task("T03", routes.ClaimBody(session_id=sid), self.ana)
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            await routes.update_task("T03", routes.TaskUpdate(session_id=sid, status="review"), self.ana)

    async def test_peer_review_rejects_a_second_session_with_same_agent_name(self):
        await self.upload_phases()
        await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="peer"), self.ana)
        sid = await self.agent()
        await routes.claim_task("T01", routes.ClaimBody(session_id=sid), self.ana)
        await routes.update_task("T01", routes.TaskUpdate(session_id=sid, status="review"), self.ana)
        second = await self.agent()
        with self.assertRaises(HTTPException):
            await routes.update_task("T01", routes.TaskUpdate(session_id=second, status="done"), self.ana)
        reviewer = await self.agent("reviewer", self.beto)
        result = await routes.update_task("T01", routes.TaskUpdate(session_id=reviewer, status="done", note="Pruebas revisadas"), self.beto)
        self.assertEqual(result["reviewed_by"], "reviewer")

    async def test_patch_cannot_skip_claim_or_dependencies(self):
        await self.upload_phases()
        await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="self"), self.ana)
        sid = await self.agent()
        for status in ("in_progress", "review", "done"):
            with self.assertRaises(HTTPException):
                await routes.update_task("T02", routes.TaskUpdate(session_id=sid, status=status), self.ana)
        task = await routes._task("T02", "app-x")
        with self.assertRaises(HTTPException):
            await routes.update_task(task["_id"], routes.TaskUpdate(status="done"), self.ana)

    async def test_token_cannot_pretend_to_be_a_person_by_omitting_session(self):
        await self.upload_phases()
        task = await routes._task("T01", "app-x")
        self.ana.state.principal.via_token = True
        with self.assertRaises(HTTPException) as error:
            await routes.update_task(task["_id"], routes.TaskUpdate(status="done"), self.ana)
        self.assertEqual(error.exception.status_code, 403)

    async def test_dependencies_reject_unknown_keys_and_cycles(self):
        await self.upload_phases()
        with self.assertRaises(HTTPException):
            await routes.create_task("app-x", routes.TaskCreate(title="Bad", depends_on=["MISSING"]), self.ana)
        task = await routes._task("T01", "app-x")
        with self.assertRaises(HTTPException):
            await routes.update_task(task["_id"], routes.TaskUpdate(depends_on=["T02"]), self.ana)

    async def test_context_marks_notes_as_older_and_counts_dependency_blockers(self):
        await self.upload_phases()
        overview = await routes.project_overview("app-x")
        self.assertEqual(overview["coordination"]["blocked"], 2)
        self.assertEqual(overview["coordination"]["ready"], 2)
        sid = await self.agent()
        await routes.claim_task("T01", routes.ClaimBody(session_id=sid), self.ana)
        task = await routes._task("T01", "app-x")
        await routes.update_task(task["_id"], routes.TaskUpdate(status="done"), self.ana)
        overview = await routes.project_overview("app-x")
        brief = await routes.project_briefing("app-x")
        self.assertTrue(brief["coordination"]["board_stale"])
        self.assertEqual(overview["coordination"]["counts"], brief["coordination"]["counts"])
        self.assertIsNone((await self.db[routes.SESSIONS].find_one({"_id": sid}))["task"])

    async def test_heartbeat_drains_overflow_with_equal_timestamps(self):
        sid = await self.agent()
        at = routes._now() + timedelta(seconds=1)
        for i in range(65):
            await self.db[routes.EVENTS].insert_one({"_id": f"event{i:03}", "group": "app-x", "session_id": None,
                "created_at": at, "text": f"event-{i}", "kind": "note"})
        for i in range(45):
            await self.db[routes.TASKS].insert_one({"_id": f"task{i:03}", "group": "app-x", "key": f"T{i}",
                "updated_at": at, "status": "todo", "title": f"Task {i}"})
        events, tasks = set(), set()
        for _ in range(4):
            sync = await routes.heartbeat(sid, routes.SyncBody(), self.ana)
            events.update(e["text"] for e in sync["events"] if e["text"].startswith("event-"))
            tasks.update(t["id"] for t in sync["tasks_changed"])
        self.assertEqual(len(events), 65)
        self.assertEqual(len(tasks), 45)
        self.assertFalse(sync["has_more"]["events"])
        self.assertEqual(sync["events"], [])

    async def test_scope_preview_and_settings_reach_sync(self):
        await self.upload_phases()
        sid = await self.agent()
        await routes.update_settings("app-x", routes.WorkSettings(mode="autonomous", done_by="peer", scope_tasks=["T02"]), self.ana)
        sync = await routes.heartbeat(sid, routes.SyncBody(), self.ana)
        self.assertEqual(sync["work_mode"]["scope_tasks"], ["T02"])
        self.assertEqual(sync["objective"]["external_dependencies"][0]["ref"], "T01")
        self.assertIn("AUTÓNOMO", sync["protocol"][0])
        with self.assertRaises(HTTPException):
            await routes.update_settings("app-x", routes.WorkSettings(scope_tasks=["NOPE"]), self.ana)

    async def test_guided_mode_normalizes_conflicting_settings(self):
        result = await routes.update_settings("app-x", routes.WorkSettings(mode="guided", done_by="self", auto_accept=True), self.ana)
        self.assertEqual(result["settings"]["done_by"], "person")
        self.assertFalse(result["settings"]["auto_accept"])

    async def test_session_cannot_write_into_another_project(self):
        sid = await self.agent()
        with self.assertRaises(HTTPException):
            await routes.create_task("app-y", routes.TaskCreate(title="Wrong group", session_id=sid), self.ana)
