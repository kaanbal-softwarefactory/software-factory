"""
Herramientas del Hub de agentes
===============================

Lo que usa un agente (Codex, Claude Code, Cursor, ChatGPT) para coordinarse con los
demás en un proyecto: presentarse, dejar latido y traza, tomar tareas, hablar con
otros agentes y leer la fuente del proyecto. Igual que el resto del MCP, cada una
llama a la REST (/hub/…) con la credencial de quien preguntó.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict
from urllib.parse import quote

from app.mcp.protocol import ToolError

HANDLED = frozenset({
    "hub_projects", "hub_join", "hub_briefing", "hub_sync", "hub_log", "hub_tasks", "hub_create_task",
    "hub_claim_task", "hub_update_task", "hub_message", "hub_files", "hub_read_file", "hub_write_note",
    "hub_trace", "hub_add_lesson", "hub_update_board", "hub_leave", "hub_digest", "hub_guides",
    "hub_checkpoint", "hub_report_feedback",
})

_GROUP = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,99}$")
_SESSION = re.compile(r"^[0-9a-f]{16}$")
_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


def _group(args: Dict[str, Any]) -> str:
    value = str(args.get("group") or "")
    if not _GROUP.match(value):
        raise ToolError("group es el identificador del grupo/proyecto (hub_projects los lista).")
    return value


def _session(args: Dict[str, Any], *, required: bool = True) -> str:
    value = str(args.get("session_id") or "")
    if not value and not required:
        return ""
    if not _SESSION.match(value):
        raise ToolError("session_id es el que devolvió hub_join (16 caracteres hexadecimales).")
    return value


def _task(args: Dict[str, Any]) -> str:
    value = str(args.get("task") or "")
    if not _TASK.match(value):
        raise ToolError("task es la clave (T01) o el id de la tarea.")
    return quote(value, safe="")


def _pick(args: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    return {key: args[key] for key in keys if args.get(key) is not None}


def _content(text_payload: Dict[str, Any], image: Dict[str, Any] = None) -> Dict[str, Any]:
    """Resultado MCP con más de un bloque (texto + imagen). protocol.tool_result lo respeta."""
    blocks = [{"type": "text", "text": json.dumps(text_payload, ensure_ascii=False, indent=2, default=str)}]
    if image:
        blocks.append({"type": "image", "data": image["data"], "mimeType": image["mimeType"]})
    return {"__mcp_content__": blocks}


async def call(client: Any, name: str, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    if name == "hub_projects":
        return await client.get("/hub/projects")
    if name == "hub_guides":
        return await client.get("/hub/guides", _pick(args, "group", "harness", "specialty"))
    if name == "hub_join":
        body = _pick(args, "agent", "harness", "model", "specialty", "focus", "branch")
        result = await client.post(f"/hub/projects/{_group(args)}/sessions", body)
        result["remember"] = (f"Guarda session_id={result.get('session_id')} y group={args.get('group')}: los pide "
                              "cada herramienta del Hub. Llama a hub_sync cada ~2 min o tras cada paso.")
        return result
    if name == "hub_briefing":
        return await client.get(f"/hub/projects/{_group(args)}/briefing")
    if name == "hub_sync":
        return await client.post(f"/hub/sessions/{_session(args)}/heartbeat", _pick(args, "focus", "status", "branch"))
    if name == "hub_checkpoint":
        return await client.post(f"/hub/projects/{_group(args)}/checkpoints", {
            **_pick(args, "summary", "decisions", "next_steps"), "session_id": _session(args)})
    if name == "hub_report_feedback":
        return await client.post(f"/hub/projects/{_group(args)}/feedback", {
            **_pick(args, "title", "description", "kind"), "session_id": _session(args)})
    if name == "hub_log":
        return await client.post(f"/hub/sessions/{_session(args)}/events", _pick(args, "kind", "text", "task", "refs"))
    if name == "hub_leave":
        return await client.post(f"/hub/sessions/{_session(args)}/leave", _pick(args, "summary", "release_tasks"))

    if name == "hub_tasks":
        return await client.get(f"/hub/projects/{_group(args)}/tasks", _pick(args, "status", "area"))
    if name == "hub_create_task":
        body = _pick(args, "title", "description", "key", "area", "phase", "depends_on", "sources", "proposed")
        if _session(args, required=False):
            body["session_id"] = args["session_id"]
        return await client.post(f"/hub/projects/{_group(args)}/tasks", body)
    if name == "hub_claim_task":
        return await client.post(f"/hub/tasks/{_task(args)}/claim", {"session_id": _session(args)})
    if name == "hub_update_task":
        body = _pick(args, "status", "note", "branch", "pr_url", "depends_on", "verification_path", "expected_visible_text")
        body["session_id"] = _session(args)
        return await client.request("PATCH", f"/hub/tasks/{_task(args)}", json=body)

    if name == "hub_message":
        body = _pick(args, "text", "to", "task")
        if _session(args, required=False):
            body["session_id"] = args["session_id"]
        return await client.post(f"/hub/projects/{_group(args)}/messages", body)
    if name == "hub_trace":
        return await client.get(f"/hub/projects/{_group(args)}/trace",
                                _pick(args, "view", "day", "agent", "kind", "session_id", "limit"))
    if name == "hub_add_lesson":
        body = _pick(args, "text", "scope")
        if _session(args, required=False):
            body["session_id"] = args["session_id"]
        return await client.post(f"/hub/projects/{_group(args)}/lessons", body)
    if name == "hub_update_board":
        body = {"content": str(args.get("content") or "")}
        if _session(args, required=False):
            body["session_id"] = args["session_id"]
        return await client.put(f"/hub/projects/{_group(args)}/board", body)
    if name == "hub_digest":
        return await client.post(f"/hub/projects/{_group(args)}/digest", _pick(args, "use_ai", "create_tasks"))

    if name == "hub_files":
        return await client.get(f"/hub/projects/{_group(args)}/files", _pick(args, "prefix"))
    if name == "hub_read_file":
        path = str(args.get("path") or "")
        if not path:
            raise ToolError("path es la ruta del archivo tal como la lista hub_files.")
        data = await client.get(f"/hub/projects/{_group(args)}/files/content", {"path": path, "format": "json"})
        encoded = data.pop("base64", None)
        if encoded:
            return _content({**data, "shown": "imagen adjunta"}, {"data": encoded, "mimeType": data["content_type"]})
        return data
    if name == "hub_write_note":
        body = _pick(args, "path", "content", "base64")
        if _session(args, required=False):
            body["session_id"] = args["session_id"]
        return await client.post(f"/hub/projects/{_group(args)}/notes", body)
    raise ToolError(f"Herramienta desconocida: {name}")
