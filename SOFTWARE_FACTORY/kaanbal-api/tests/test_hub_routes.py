"""Hub de agentes de punta a punta sobre una Mongo en memoria: dos agentes se coordinan."""

import io
import json
import re
import unittest
import zipfile
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routers import hub as routes


# ── Mongo mínima en memoria ──────────────────────────────────────────────
def _get(doc, dotted):
    for part in dotted.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def _matches(doc, query):
    for key, cond in query.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = _get(doc, key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in" and not (value in arg or (isinstance(value, list) and set(value) & set(arg))):
                    return False
                if op == "$ne" and (value == arg or (isinstance(value, list) and arg in value)):
                    return False
                if op == "$gte" and not (value is not None and value >= arg):
                    return False
                if op == "$gt" and not (value is not None and value > arg):
                    return False
                if op == "$lt" and not (value is not None and value < arg):
                    return False
        elif value != cond:
            return False
    return True


def _apply(doc, change, insert=False):
    for key, value in (change.get("$set") or {}).items():
        doc[key] = value
    if insert:
        for key, value in (change.get("$setOnInsert") or {}).items():
            doc.setdefault(key, value)
    for key, value in (change.get("$push") or {}).items():
        doc.setdefault(key, []).append(value)
    for key, value in (change.get("$addToSet") or {}).items():
        if value not in doc.setdefault(key, []):
            doc[key].append(value)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction=1):
        self.rows.sort(key=lambda d: (_get(d, key) is None, _get(d, key)), reverse=direction == -1)
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, n):
        return [deepcopy(r) for r in (self.rows if n is None else self.rows[:n])]


class Collection:
    def __init__(self):
        self.docs = []

    def find(self, query=None, projection=None):
        return Cursor([d for d in self.docs if _matches(d, query or {})])

    async def find_one(self, query, projection=None):
        rows = [d for d in self.docs if _matches(d, query)]
        return deepcopy(rows[0]) if rows else None

    async def insert_one(self, doc):
        self.docs.append(deepcopy(doc))

    async def update_one(self, query, change, upsert=False):
        for doc in self.docs:
            if _matches(doc, query):
                _apply(doc, change)
                return
        if upsert:
            doc = {k: v for k, v in query.items() if not k.startswith("$")}
            _apply(doc, change, insert=True)
            self.docs.append(doc)

    async def update_many(self, query, change):
        for doc in self.docs:
            if _matches(doc, query):
                _apply(doc, change)

    async def find_one_and_update(self, query, change, return_document=None):
        for doc in self.docs:
            if _matches(doc, query):
                _apply(doc, change)
                return deepcopy(doc)
        return None


class Db(dict):
    def __missing__(self, name):
        self[name] = Collection()
        return self[name]

    def __getattr__(self, name):
        return self[name]


class Bucket:
    def __init__(self, files):
        self.files = files
        self.blobs = {}

    async def upload_from_stream(self, filename, data, metadata=None):
        file_id = f"f{len(self.blobs)}"
        self.blobs[file_id] = data
        await self.files.insert_one({"_id": file_id, "filename": filename, "length": len(data), "metadata": metadata})

    async def delete(self, file_id):
        self.files.docs = [d for d in self.files.docs if d["_id"] != file_id]
        self.blobs.pop(file_id, None)

    async def open_download_stream(self, file_id):
        data = self.blobs[file_id]
        return SimpleNamespace(read=AsyncMock(return_value=data))


def request(username, superadmin=False):
    return SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(
        username=username, superadmin=superadmin, token_name=f"{username}-token")))


class Upload:
    def __init__(self, name, data):
        self.filename = name
        self.data = data

    async def read(self, limit=-1):
        return self.data


class HubFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Db()
        self.bucket = Bucket(self.db["hub_files.files"])
        self.patches = [patch.object(routes, "get_db", return_value=self.db),
                        patch.object(routes, "_bucket", return_value=self.bucket),
                        patch.object(routes.activity_log, "log", AsyncMock())]
        for item in self.patches:
            item.start()
        self.ana, self.beto = request("ana"), request("beto")

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()

    async def upload_phases(self):
        plan = {"version": 1, "board": "# App X\nFases 1-4 en fuente/.", "tasks": [
            {"key": "T01", "title": "Auditar repo", "area": "integración"},
            {"key": "T02", "title": "Contrato API", "area": "backend", "depends_on": ["T01"]},
            {"key": "T03", "title": "Design system", "area": "frontend diseño", "depends_on": []},
            {"key": "T04", "title": "Landing", "area": "frontend", "depends_on": ["T02", "T03"]}]}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("fase 1/1.portada.png", b"\x89PNG fake")
            archive.writestr("fase5/kaanbal.hub.json", json.dumps(plan))
            archive.writestr("fase5/00_PRIMERO_LEER.md", "Reglas")
        result = await routes.upload_files("app-x", self.ana, file=Upload("fases.zip", buffer.getvalue()),
                                           dest="fuente", extract=True)
        self.assertEqual(result["plan_found"], "fuente/fase5/kaanbal.hub.json")
        imported = await routes.import_plan("app-x", routes.PlanImport(), self.ana)
        self.assertEqual((imported["created"], imported["board_set"]), (4, True))

    async def test_two_agents_coordinate_through_the_hub(self):
        await self.upload_phases()

        # Agustín llega primero con Codex (Astra), especializado en diseño.
        first = await routes.join("app-x", routes.JoinBody(agent="astra", harness="codex", specialty="diseño frontend",
                                                           focus="design system"), self.ana)
        astra = first["session_id"]
        brief = first["briefing"]
        self.assertIn("primero", brief["situation"])
        self.assertTrue(brief["board"].startswith("# App X"))
        self.assertEqual(brief["tasks"]["available_for_you"][0]["key"], "T03")
        await routes.claim_task("T03", routes.ClaimBody(session_id=astra), self.ana)

        # Andrés entra con Claude, para APIs: ve a Astra en línea y la tarea que tiene.
        second = await routes.join("app-x", routes.JoinBody(agent="claude-api", harness="claude", specialty="backend apis"),
                                   self.beto)
        claude = second["session_id"]
        self.assertEqual([s["agent"] for s in second["briefing"]["team"]], ["astra"])
        self.assertEqual(second["briefing"]["tasks"]["in_progress"][0]["assignee_agent"], "astra")

        # La landing depende del contrato y del design system: el Hub dice qué falta y de quién.
        with self.assertRaises(HTTPException) as caught:
            await routes.claim_task("T04", routes.ClaimBody(session_id=claude), self.beto)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("astra", caught.exception.detail["message"])

        # Nadie toma una tarea ajena en curso.
        with self.assertRaises(HTTPException):
            await routes.claim_task("T03", routes.ClaimBody(session_id=claude), self.beto)

        await routes.claim_task("T01", routes.ClaimBody(session_id=claude), self.beto)
        await routes.send_message("app-x", routes.MessageBody(text="¿Publicas los tokens del design system?",
                                                              to="astra", session_id=claude), self.beto)

        # El latido de Astra trae el mensaje (una sola vez) y lo que hizo Claude.
        sync = await routes.heartbeat(astra, routes.SyncBody(status="Tokens listos en live/"), self.ana)
        self.assertEqual([m["text"] for m in sync["messages"]], ["¿Publicas los tokens del design system?"])
        self.assertIn("claude-api", [e["agent"] for e in sync["events"]])
        again = await routes.heartbeat(astra, routes.SyncBody(), self.ana)
        self.assertEqual(again["messages"], [])

        # Un agente no cambia la tarea en curso de otro; la persona que integra sí puede.
        with self.assertRaises(HTTPException):
            await routes.update_task("T03", routes.TaskUpdate(session_id=claude, status="done"), self.beto)

        await routes.update_task("T03", routes.TaskUpdate(session_id=astra, status="done", pr_url="https://example.com/pr/7"),
                                 self.ana)
        await routes.update_task("T01", routes.TaskUpdate(session_id=claude, status="done"), self.beto)
        await routes.claim_task("T02", routes.ClaimBody(session_id=claude), self.beto)

        # Notas de agente siempre en live/; la fuente es de las personas.
        note = await routes.write_note("app-x", routes.NoteBody(path="contratos/api.md", content="# Contrato",
                                                                session_id=claude), self.beto)
        self.assertEqual(note["path"], "live/contratos/api.md")

        # Al irse con relevo, su tarea en curso queda libre para otro.
        left = await routes.leave(claude, routes.LeaveBody(summary="Contrato en live/contratos/api.md; falta validar."),
                                  self.beto)
        self.assertEqual(left["released_tasks"], ["T02"])
        third = await routes.join("app-x", routes.JoinBody(agent="claude-api", harness="claude"), self.beto)
        self.assertEqual(third["briefing"]["last_handoffs"][0]["text"], "Contrato en live/contratos/api.md; falta validar.")

        tree = await routes.trace("app-x", view="tree")
        agents = {a["agent"] for day in tree["tree"] for a in day["agents"]}
        self.assertTrue({"astra", "claude-api", "ana"} <= agents)

    async def test_a_session_belongs_to_whoever_opened_it(self):
        joined = await routes.join("app-x", routes.JoinBody(agent="astra", harness="codex"), self.ana)
        with self.assertRaises(HTTPException) as caught:
            await routes.heartbeat(joined["session_id"], routes.SyncBody(), self.beto)
        self.assertEqual(caught.exception.status_code, 403)

    async def test_files_are_read_as_text_or_inline_image(self):
        await self.upload_phases()
        text = await routes.file_content("app-x", "fuente/fase5/00_PRIMERO_LEER.md", format="json")
        self.assertEqual(text["text"], "Reglas")
        image = await routes.file_content("app-x", "fuente/fase 1/1.portada.png", format="json")
        self.assertEqual(image["content_type"], "image/png")
        self.assertIn("base64", image)
        listed = await routes.list_files("app-x", prefix="fuente/fase 1")
        self.assertEqual([f["path"] for f in listed["files"]], ["fuente/fase 1/1.portada.png"])

    async def test_the_secretary_works_without_ai(self):
        await self.upload_phases()
        with patch("app.services.ai_service.ai_service.configured", AsyncMock(return_value=False)):
            result = await routes.digest("app-x", routes.DigestBody(), self.ana)
        self.assertFalse(result["ai"])
        self.assertEqual(result["signals"]["ready_to_start"][:2], ["T01 · Auditar repo", "T03 · Design system"])

    async def test_project_identifiers_cannot_be_mongo_expressions(self):
        with self.assertRaises(HTTPException):
            await routes.project_briefing("$where")


if __name__ == "__main__":
    unittest.main()
