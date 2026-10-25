"""Hub de agentes: reglas puras (rutas, ZIP, presencia, dependencias, plan, briefing, secretario)."""

import io
import json
import unittest
import zipfile
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services import agent_hub as hub
from app.services import agent_hub_guides as guides

NOW = datetime(2026, 10, 24, 18, 0, 0)


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def task(key, status="todo", depends=(), area="", **extra):
    return {"_id": f"{key.lower():0>16}"[-16:], "key": key, "title": f"Tarea {key}", "status": status,
            "depends_on": list(depends), "area": area, **extra}


class PathTests(unittest.TestCase):
    def test_names_from_foreign_zips_cannot_escape_the_project(self):
        for bad in ("../secreto", "fuente/../../x", "/etc/passwd", "C:/Windows/x", "a/\x00b", "", "   "):
            with self.assertRaises(hub.HubError, msg=bad):
                hub.normalize_path(bad)

    def test_real_phase_names_with_spaces_and_backslashes_are_kept(self):
        self.assertEqual(hub.normalize_path("fuente\\fase 1\\1.portada.png"), "fuente/fase 1/1.portada.png")
        self.assertEqual(hub.normalize_path("./live//notas/./a.md"), "live/notas/a.md")

    def test_live_is_the_agents_folder(self):
        self.assertTrue(hub.is_live_path("live/contratos/api.md"))
        self.assertFalse(hub.is_live_path("lively/x.md"))
        self.assertFalse(hub.is_live_path("fuente/a.md"))


class ZipTests(unittest.TestCase):
    def test_phase_zip_opens_inner_zips_one_level_without_keeping_them(self):
        inner = make_zip({"Fase_3/README.md": "admin", "Fase_3/01.png": b"\x89PNG"})
        outer = make_zip({"fase 1/1.portada.png": b"\x89PNG", "fase 3/Fase_3.zip": inner,
                          "__MACOSX/fase 1/._x": "basura", "fase 1/.DS_Store": "basura"})
        paths = sorted(path for path, _ in hub.extract_zip(outer, "fuente"))
        self.assertEqual(paths, ["fuente/fase 1/1.portada.png", "fuente/fase 3/Fase_3/Fase_3/01.png",
                                 "fuente/fase 3/Fase_3/Fase_3/README.md"])

    def test_zip_slip_entries_are_rejected(self):
        with self.assertRaises(hub.HubError):
            hub.extract_zip(make_zip({"../../fuera.txt": "x"}), "fuente")

    def test_decompressed_size_is_capped(self):
        with patch.object(hub, "MAX_EXTRACTED_BYTES", 10):
            with self.assertRaises(hub.HubError):
                hub.extract_zip(make_zip({"a.txt": "0123456789abc"}), "fuente")

    def test_not_a_zip_is_explained(self):
        with self.assertRaises(hub.HubError):
            hub.extract_zip(b"no soy zip", "fuente")


class PresenceTests(unittest.TestCase):
    def test_presence_follows_the_heartbeat(self):
        self.assertEqual(hub.presence({"last_seen": NOW - timedelta(minutes=1)}, NOW), "online")
        self.assertEqual(hub.presence({"last_seen": NOW - timedelta(minutes=10)}, NOW), "idle")
        self.assertEqual(hub.presence({"last_seen": NOW - timedelta(hours=1)}, NOW), "offline")
        self.assertEqual(hub.presence({"last_seen": NOW, "left_at": NOW}, NOW), "left")


class TaskTests(unittest.TestCase):
    def test_a_task_waits_for_its_dependencies_and_says_who_has_them(self):
        tasks = [task("T01", "in_progress", assignee_agent="codex-api"), task("T02", depends=["T01"])]
        problem = hub.claim_check(tasks[1], hub.index_tasks(tasks), {"_id": "s"})
        self.assertIn("T01", problem["reason"])
        self.assertIn("codex-api", problem["reason"])
        self.assertEqual(problem["pending"][0]["holder"], "codex-api")

    def test_a_missing_dependency_also_blocks(self):
        tasks = [task("T02", depends=["T99"])]
        self.assertEqual(hub.claim_check(tasks[0], hub.index_tasks(tasks), {"_id": "s"})["pending"][0]["status"], "missing")

    def test_a_task_in_progress_by_someone_else_cannot_be_claimed(self):
        busy = task("T01", "in_progress", assignee_session="otra", assignee_agent="astra")
        self.assertIn("astra", hub.claim_check(busy, hub.index_tasks([busy]), {"_id": "mia"})["reason"])

    def test_available_tasks_put_the_agents_area_first(self):
        tasks = [task("T01", area="backend"), task("T02", area="frontend"), task("T03", "done"),
                 task("T04", area="frontend", depends=["T05"]), task("T05", area="backend")]
        keys = [t["key"] for t in hub.available_tasks(tasks, "diseño y frontend")]
        self.assertEqual(keys, ["T02", "T01", "T05"])


class PlanTests(unittest.TestCase):
    def test_a_valid_plan_is_normalized(self):
        plan = hub.parse_plan(json.dumps({"version": 1, "board": "# Proyecto", "tasks": [
            {"key": "T01", "title": "Auditar", "area": "integración", "phase": "W0"},
            {"key": "T02", "title": "Contrato", "depends_on": ["T01"], "sources": ["fuente\\fase 5\\a.md"]}]}))
        self.assertEqual(plan["board"], "# Proyecto")
        self.assertEqual(plan["tasks"][1]["sources"], ["fuente/fase 5/a.md"])

    def test_plans_with_cycles_unknown_or_repeated_keys_are_rejected(self):
        cases = [
            [{"key": "A", "title": "a", "depends_on": ["B"]}, {"key": "B", "title": "b", "depends_on": ["A"]}],
            [{"key": "A", "title": "a", "depends_on": ["Z"]}],
            [{"key": "A", "title": "a"}, {"key": "A", "title": "otra"}],
            [{"title": "sin clave"}],
        ]
        for tasks in cases:
            with self.assertRaises(hub.HubError, msg=tasks):
                hub.parse_plan({"version": 1, "tasks": tasks})
        with self.assertRaises(hub.HubError):
            hub.parse_plan("{no es json")

    def test_the_shallowest_plan_wins(self):
        self.assertEqual(hub.find_plan(["fuente/a/b/kaanbal.hub.json", "fuente/kaanbal.hub.json", "x.json"]),
                         "fuente/kaanbal.hub.json")
        self.assertIsNone(hub.find_plan(["fuente/a.md"]))


class TraceTests(unittest.TestCase):
    def test_trace_is_project_day_agent(self):
        events = [
            {"created_at": NOW, "agent": "astra", "kind": "progress", "session_id": "s1"},
            {"created_at": NOW - timedelta(minutes=5), "agent": "astra", "kind": "decision", "session_id": "s1"},
            {"created_at": NOW - timedelta(days=1), "agent": "claude-api", "kind": "join", "session_id": "s2"},
            {"created_at": NOW, "person": "ana", "kind": "file"},
        ]
        tree = hub.trace_tree(events)
        self.assertEqual([day["day"] for day in tree], ["2026-10-24", "2026-10-23"])
        astra = next(a for a in tree[0]["agents"] if a["agent"] == "astra")
        self.assertEqual(astra["events"], 2)
        self.assertEqual(astra["kinds"], {"progress": 1, "decision": 1})
        self.assertIn("ana", [a["agent"] for a in tree[0]["agents"]])


class BriefingTests(unittest.TestCase):
    def brief(self, sessions, me=None):
        return hub.briefing({"_id": "app-x", "name": "App X", "board": "# Tablero"}, sessions=sessions,
                            tasks=[task("T01", area="frontend"), task("T02", depends=["T01"])], events=[],
                            handoffs=[{"agent": "astra", "text": "Dejé el design system", "created_at": NOW}],
                            lessons=[], files=[{"path": "fuente/fase 1/a.png", "size": 3}], now=NOW, me=me)

    def test_the_first_agent_is_told_to_organize(self):
        result = self.brief([])
        self.assertIn("primero", result["situation"])
        self.assertEqual(result["board"], "# Tablero")
        self.assertEqual(result["last_handoffs"][0]["text"], "Dejé el design system")
        self.assertEqual([t["key"] for t in result["tasks"]["available_for_you"]], ["T01"])
        self.assertEqual([t["key"] for t in result["tasks"]["blocked"]], ["T02"])

    def test_the_second_agent_sees_the_first_but_not_itself(self):
        astra = {"_id": "a" * 16, "agent": "astra", "harness": "codex", "last_seen": NOW, "started_at": NOW}
        me = {"_id": "b" * 16, "agent": "claude-api", "last_seen": NOW, "started_at": NOW, "specialty": "apis"}
        result = self.brief([astra, me], me=me)
        self.assertEqual([s["agent"] for s in result["team"]], ["astra"])
        self.assertIn("coordina", result["situation"])


class SecretaryTests(unittest.TestCase):
    def test_signals_catch_orphan_blocked_and_review_tasks(self):
        gone = {"_id": "a" * 16, "agent": "astra", "last_seen": NOW - timedelta(hours=2), "started_at": NOW}
        tasks = [task("T01", "in_progress", assignee_session="a" * 16, assignee_agent="astra"),
                 task("T02", "blocked"), task("T03", "review", pr_url="https://example.com/pr/1"),
                 task("T04", "done", phase="W0"), task("T05", phase="W0")]
        signals = hub.digest_signals(sessions=[gone], tasks=tasks, events=[], now=NOW)
        kinds = sorted(alert["kind"] for alert in signals["alerts"])
        self.assertEqual(kinds, ["blocked", "orphan", "review"])
        self.assertEqual(signals["phases"]["W0"], {"done": 1, "total": 2})
        self.assertEqual(signals["ready_to_start"], ["T05 · Tarea T05"])

    def test_ai_answers_are_sanitized_and_errors_ignored(self):
        self.assertEqual(hub.parse_digest({"error": "AI API error: 401"}), {})
        parsed = hub.parse_digest({"summary": "Va bien", "suggested_tasks": [{"title": "  QA  ", "area": "qa"}, {"x": 1}]})
        self.assertEqual(parsed["suggested_tasks"], [{"title": "QA", "area": "qa", "why": ""}])


class GuideTests(unittest.TestCase):
    def test_the_chatgpt_prompt_describes_the_plan_format_the_hub_reads(self):
        self.assertIn(hub.PLAN_FILE, guides.CHATGPT_PHASES_PROMPT)
        self.assertIn('"version": 1', guides.CHATGPT_PHASES_PROMPT)
        self.assertIn("hub_join(group='app-x'", guides.agent_start_prompt("app-x", "codex", "diseño"))


if __name__ == "__main__":
    unittest.main()
