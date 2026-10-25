"""Hub de agentes: sesiones, traza, tareas, mensajes y archivos por proyecto (grupo).

La lógica vive en app/services/agent_hub.py; aquí solo se guarda y se lee. Quien
escribe es siempre el principal de la petición: una sesión de agente solo la puede
usar la persona (o el token) que la abrió.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from app.db import get_db
from app.services import agent_hub as hub
from app.services import agent_hub_guides as guides
from app.services import hub_integration as integration
from app.services import hub_workspace as workspace
from app.services.activity_log import activity_log, CATEGORY_APP

router = APIRouter()

PROJECTS, SESSIONS, EVENTS, TASKS = "hub_projects", "hub_sessions", "hub_events", "hub_tasks"
MESSAGES, LESSONS, BOARDS, BUCKET = "hub_messages", "hub_lessons", "hub_board_history", "hub_files"
UPLOADS, UPLOAD_PARTS = "hub_uploads", "hub_upload_parts"
CHECKPOINTS = "hub_checkpoints"


# ── Utilidades ───────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.utcnow()


def _new_id() -> str:
    return uuid4().hex[:16]


def _principal(request: Request) -> Any:
    return request.state.principal


def _group(slug: str) -> str:
    if not hub.valid_group(slug):
        raise HTTPException(422, "Proyecto inválido: usa el identificador del grupo (minúsculas, números y guiones).")
    return slug


def _bad(exc: hub.HubError) -> HTTPException:
    return HTTPException(422, str(exc))


def _bucket():
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket

    return AsyncIOMotorGridFSBucket(get_db(), bucket_name=BUCKET)


def _files():
    return get_db()[f"{BUCKET}.files"]


async def _project(group: str) -> Dict[str, Any]:
    """El proyecto del Hub; si todavía no existe, uno vacío con el nombre del grupo."""
    db = get_db()
    project = await db[PROJECTS].find_one({"_id": group})
    meta = await db.app_groups.find_one({"_id": group}) or {}
    base = {"_id": group, "name": meta.get("name") or group, "description": meta.get("description") or "",
            "owner": meta.get("owner"), "board": ""}
    if group == workspace.PLATFORM_GROUP:
        base.update(name=workspace.PLATFORM_NAME, description=workspace.PLATFORM_DESCRIPTION, scope="platform")
    return {**base, **(project or {})}


async def _touch_project(group: str, **fields: Any) -> None:
    await get_db()[PROJECTS].update_one(
        {"_id": group}, {"$set": {"updated_at": _now(), **fields}, "$setOnInsert": {"created_at": _now()}}, upsert=True)


async def _event(group: str, kind: str, text: str, *, session: Optional[Dict[str, Any]] = None,
                 person: Optional[str] = None, task_ref: Optional[str] = None, refs: Optional[List[str]] = None,
                 agent: Optional[str] = None) -> Dict[str, Any]:
    doc = {"_id": _new_id(), "group": group, "kind": kind, "text": text[:4000], "created_at": _now(),
           "session_id": (session or {}).get("_id"), "agent": agent or (session or {}).get("agent"),
           "harness": (session or {}).get("harness"), "person": person or (session or {}).get("person"),
           "task_ref": task_ref, "refs": refs or []}
    await get_db()[EVENTS].insert_one(doc)
    await _touch_project(group, last_activity=doc["created_at"])
    return doc


async def _own_session(request: Request, session_id: str) -> Dict[str, Any]:
    if not hub.valid_id(session_id):
        raise HTTPException(422, "session_id inválido: usa el que devolvió hub_join.")
    session = await get_db()[SESSIONS].find_one({"_id": session_id})
    if not session:
        raise HTTPException(404, "Esa sesión no existe. Vuelve a entrar con hub_join.")
    principal = _principal(request)
    if session.get("person") != principal.username and not principal.superadmin:
        raise HTTPException(403, "Esa sesión es de otra persona: abre la tuya con hub_join.")
    if session.get("left_at"):
        raise HTTPException(409, "Esa sesión ya se cerró con hub_leave. Abre otra con hub_join.")
    # Cualquier acción del agente cuenta como latido: en tareas largas se olvida hub_sync y aparecía inactivo.
    now = _now()
    await get_db()[SESSIONS].update_one({"_id": session_id}, {"$set": {"last_seen": now}})
    session["last_seen"] = now
    return session


async def _optional_session(request: Request, session_id: Optional[str], group: Optional[str] = None) -> Optional[Dict[str, Any]]:
    session = await _own_session(request, session_id) if session_id else None
    if session and group and session["group"] != group:
        raise HTTPException(422, "La sesión es de otro proyecto.")
    return session


async def _group_tasks(group: str) -> List[Dict[str, Any]]:
    return await get_db()[TASKS].find({"group": group}).sort("created_at", 1).to_list(None)


async def _group_sessions(group: str, days: int = 7) -> List[Dict[str, Any]]:
    since = _now() - timedelta(days=days)
    return await get_db()[SESSIONS].find({"group": group, "last_seen": {"$gte": since}}).sort("last_seen", -1).to_list(200)


async def _recent_events(group: str, limit: int = 30) -> List[Dict[str, Any]]:
    return await get_db()[EVENTS].find({"group": group}).sort("created_at", -1).limit(limit).to_list(limit)


async def _lessons(group: str) -> List[Dict[str, Any]]:
    query = {"$or": [{"group": group}, {"scope": "platform"}]}
    return await get_db()[LESSONS].find(query).sort("created_at", -1).limit(20).to_list(20)


async def _file_rows(group: str) -> List[Dict[str, Any]]:
    rows = await _files().find({"metadata.group": group}).sort("filename", 1).to_list(None)
    return [{"path": row["filename"], "size": row.get("length", 0),
             "content_type": (row.get("metadata") or {}).get("content_type"),
             "uploaded_by": (row.get("metadata") or {}).get("uploaded_by"),
             "uploaded_at": row.get("uploadDate")} for row in rows]


async def _briefing(group: str, me: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    db = get_db()
    handoffs = await db[EVENTS].find({"group": group, "kind": "handoff"}).sort("created_at", -1).limit(3).to_list(3)
    result = hub.briefing(await _project(group), sessions=await _group_sessions(group), tasks=await _group_tasks(group),
                        events=await _recent_events(group, 15), handoffs=handoffs, lessons=await _lessons(group),
                        files=await _file_rows(group), now=_now(), me=me,
                        settings=(await _project(group)).get("settings"))
    result["workspace"] = await _workspace_context(group)
    return result


async def _workspace_context(group: str) -> Dict[str, Any]:
    db = get_db()
    project = await _project(group)
    config = await db.system_config.find_one({"_id": "main"}) or {}
    apps = await db.apps.find({"app_group": group}).to_list(100)
    from app.services import domain_service
    resolved = []
    for app in apps:
        try:
            domain = (await domain_service.resolve_for_app(app)).get("fqdn")
        except Exception:  # el contexto nunca tumba el briefing: sin dominio, la tarjeta va sin URL
            domain = None
        resolved.append({**app, "domain": domain or config.get("domain") or ""})
    checkpoints = await db[CHECKPOINTS].find({"group": group}).sort("updated_at", -1).limit(8).to_list(8)
    result = workspace.snapshot(project, await _group_tasks(group), await _group_sessions(group),
                                await _recent_events(group, 50), checkpoints, now=_now())
    result["services"] = workspace.service_cards(resolved, config.get("domain") or "")
    return result


async def _store_file(group: str, path: str, data: bytes, actor: str, origin: str) -> Dict[str, Any]:
    """Guarda (o reemplaza) un archivo del drive del proyecto en GridFS."""
    for old in await _files().find({"metadata.group": group, "filename": path}, {"_id": 1}).to_list(None):
        await _bucket().delete(old["_id"])
    ctype = hub.content_type(path)
    await _bucket().upload_from_stream(path, data, metadata={
        "group": group, "content_type": ctype, "sha256": hashlib.sha256(data).hexdigest(),
        "uploaded_by": actor, "origin": origin})
    return {"path": path, "size": len(data), "content_type": ctype}


async def _read_file(group: str, path: str) -> tuple[Dict[str, Any], bytes]:
    row = await _files().find_one({"metadata.group": group, "filename": path})
    if not row:
        raise HTTPException(404, f"No existe '{path}' en el proyecto. hub_files lista lo que hay.")
    stream = await _bucket().open_download_stream(row["_id"])
    return row, await stream.read()


# ── Proyectos ────────────────────────────────────────────────────────────
@router.get("/projects")
async def list_projects():
    """Vista general: cada grupo con su actividad en el Hub."""
    db = get_db()
    now = _now()
    groups = {item["_id"]: item for item in await db.app_groups.find({}).to_list(None)}
    projects = {item["_id"]: item for item in await db[PROJECTS].find({}).to_list(None)}
    projects.setdefault(workspace.PLATFORM_GROUP, {"name": workspace.PLATFORM_NAME,
                                                "description": workspace.PLATFORM_DESCRIPTION, "scope": "platform"})
    active = await db[SESSIONS].find({"last_seen": {"$gte": now - hub.IDLE}, "left_at": None}).to_list(None)
    all_tasks = await db[TASKS].find({}, {"group": 1, "status": 1, "key": 1, "title": 1, "phase": 1,
                                         "depends_on": 1, "updated_at": 1, "assignee_agent": 1}).to_list(None)
    rows = []
    for slug in sorted(set(groups) | set(projects)):
        meta, project = groups.get(slug) or {}, projects.get(slug) or {}
        agents = [hub.public_session(s, now) for s in active if s.get("group") == slug]
        tasks = [t for t in all_tasks if t.get("group") == slug]
        state = hub.coordination_state(project, tasks, [], now)
        rows.append({
            "group": slug, "name": project.get("name") or meta.get("name") or slug, "owner": meta.get("owner"),
            "scope": "platform" if slug == workspace.PLATFORM_GROUP else "project",
            "stage": meta.get("stage", "active"), "description": project.get("description") or meta.get("description") or "",
            "agents_online": [a for a in agents if a["presence"] in ("online", "idle")],
            "open_tasks": sum(t.get("status") in hub.OPEN_STATUSES for t in tasks),
            "blocked_tasks": state["blocked"],
            "ready_tasks": state["ready"], "review_tasks": state["counts"]["review"],
            "objective": hub.objective_progress(tasks, hub.work_settings(project.get("settings"))),
            "last_activity": project.get("last_activity"), "in_hub": slug in projects,
            "mode": hub.work_settings(project.get("settings"))["mode"],
        })
    rows.sort(key=lambda r: r["last_activity"] or datetime.min, reverse=True)
    return {"projects": rows, "total": len(rows)}


@router.get("/projects/{group}")
async def project_overview(group: str):
    group = _group(group)
    now = _now()
    project = await _project(group)
    sessions = await _group_sessions(group)
    tasks = await _group_tasks(group)
    events = await _recent_events(group, 200)
    index = hub.index_tasks(tasks)
    settings = hub.work_settings(project.get("settings"))
    return {
        "project": {k: project.get(k) for k in ("_id", "name", "description", "owner", "board", "board_updated_by",
                                                 "board_updated_at", "last_digest", "last_activity")},
        "settings": settings,
        "workspace": await _workspace_context(group),
        "objective": hub.objective_progress(tasks, settings),
        "coordination": hub.coordination_state(project, tasks, sessions, now),
        "sessions": [hub.public_session(s, now) for s in sessions],
        "tasks": [hub.public_task(t, index) for t in tasks],
        "events": [{**hub.compact_event(e), "id": e["_id"], "person": e.get("person"), "harness": e.get("harness")}
                   for e in events[:60]],
        "signals": hub.digest_signals(sessions=sessions, tasks=tasks, events=events, now=now),
        "files": hub.files_summary(await _file_rows(group)),
        "lessons": [{"scope": l.get("scope"), "text": l.get("text"), "agent": l.get("agent"), "at": l.get("created_at")}
                    for l in await _lessons(group)],
    }


@router.get("/projects/{group}/briefing")
async def project_briefing(group: str):
    return await _briefing(_group(group))


class BoardUpdate(BaseModel):
    content: str = Field(max_length=20_000)
    session_id: Optional[str] = None


@router.put("/projects/{group}/board")
async def update_board(group: str, body: BoardUpdate, request: Request):
    group = _group(group)
    session = await _optional_session(request, body.session_id, group)
    actor = (session or {}).get("agent") or _principal(request).username
    previous = (await _project(group)).get("board") or ""
    await get_db()[BOARDS].insert_one({"group": group, "content": previous, "replaced_by": actor, "at": _now()})
    await _touch_project(group, board=body.content.strip(), board_updated_by=actor, board_updated_at=_now())
    await _event(group, "board", f"Actualizó el tablero ({len(previous)} → {len(body.content.strip())} caracteres).",
                 session=session, person=_principal(request).username, agent=actor)
    return {"group": group, "board": body.content.strip(), "updated_by": actor}


class WorkSettings(BaseModel):
    mode: Literal["guided", "autonomous"] = "guided"
    done_by: Literal["person", "peer", "self"] = "person"
    auto_accept: bool = False
    objective: str = Field(default="", max_length=500)
    scope_phases: List[str] = Field(default_factory=list, max_length=20)
    scope_tasks: List[str] = Field(default_factory=list, max_length=100)
    integration: Literal["manual", "auto"] = "manual"
    require_checks: bool = True
    integration_app: str = Field(default="", max_length=63)
    # prod + rama vacía = la rama principal del repo (main directo, como hasta ahora).
    integration_env: Literal["dev", "prod"] = "prod"
    integration_branch: str = Field(default="", max_length=120)


@router.put("/projects/{group}/settings")
async def update_settings(group: str, body: WorkSettings, request: Request):
    """Modo de trabajo del proyecto: guiado (personas aprueban) o autónomo hasta cumplir un objetivo."""
    group = _group(group)
    try:
        settings = hub.work_settings(body.model_dump())
        if [k for k in body.scope_tasks if not hub.task_key(k)]:
            raise hub.HubError("Hay claves de tarea vacías en el objetivo.")
    except hub.HubError as exc:
        raise _bad(exc)
    actor = _principal(request).username
    previous = hub.work_settings((await _project(group)).get("settings"))
    integration_changed = any(settings[k] != previous[k] for k in (
        "integration", "require_checks", "integration_app", "integration_env", "integration_branch"))
    if integration_changed and not _principal(request).can("hub.integration.manage"):
        raise HTTPException(403, "Cambiar la integración a main exige el permiso hub.integration.manage: despliega sin intervención humana.")
    if settings["integration"] == "auto" and settings["done_by"] == "self":
        raise HTTPException(422, "La integración automática exige revisión de otro agente o de una persona (cierre: peer o person).")
    if settings["integration_env"] == "dev" and settings["integration_branch"] in ("", "main", "master"):
        raise HTTPException(422, "Dev necesita una rama distinta de main, normalmente develop.")
    if settings["integration_branch"] and not integration.valid_branch(settings["integration_branch"]):
        raise HTTPException(422, "Rama de integración inválida.")
    if settings["integration"] == "auto":
        try:
            await _integration_target(group, settings)
        except integration.IntegrationBlocked as exc:
            raise HTTPException(422, str(exc))
    tasks = await _group_tasks(group)
    known = hub.index_tasks(tasks)
    unknown = [key for key in settings["scope_tasks"] if key not in known]
    if unknown:
        raise HTTPException(422, "Tareas del objetivo inexistentes: " + ", ".join(unknown))
    await _touch_project(group, settings=settings)
    label = "autónomo" if settings["mode"] == "autonomous" else "guiado"
    scope = ", ".join(settings["scope_phases"] + settings["scope_tasks"]) or "todo el proyecto"
    await _event(group, "board", f"Modo {label} ({scope}); cierre: {settings['done_by']}"
                 + (f". Objetivo: {settings['objective']}" if settings["objective"] else "."), person=actor, agent=actor)
    await activity_log.log("hub.settings.updated", category=CATEGORY_APP, actor=actor, target=group, detail=settings)
    tasks = await _group_tasks(group)
    return {"settings": settings, "objective": hub.objective_progress(tasks, settings)}


# ── Sesiones ─────────────────────────────────────────────────────────────
class JoinBody(BaseModel):
    agent: str
    harness: str = "otro"
    model: str = Field(default="", max_length=60)
    specialty: str = Field(default="", max_length=200)
    focus: str = Field(default="", max_length=500)
    branch: str = Field(default="", max_length=120)


@router.post("/projects/{group}/sessions")
async def join(group: str, body: JoinBody, request: Request):
    group = _group(group)
    try:
        agent = hub.agent_name(body.agent)
    except hub.HubError as exc:
        raise _bad(exc)
    principal = _principal(request)
    now = _now()
    session = {"_id": _new_id(), "group": group, "agent": agent, "harness": hub.harness(body.harness),
               "model": body.model.strip(), "specialty": body.specialty.strip(), "focus": body.focus.strip(),
               "branch": body.branch.strip() or None, "person": principal.username, "token": principal.token_name,
               "started_at": now, "last_seen": now, "cursor": now, "left_at": None, "task": None}
    await get_db()[SESSIONS].insert_one(session)
    await _event(group, "join", f"Entró como {session['harness']}" + (f" ({session['specialty']})" if session["specialty"] else "")
                 + (f". Foco: {session['focus']}" if session["focus"] else "."), session=session)
    await activity_log.log("hub.session.joined", category=CATEGORY_APP, actor=principal.username, target=group,
                           detail={"agent": agent, "harness": session["harness"]})
    return {"session_id": session["_id"], "briefing": await _briefing(group, session)}


class SyncBody(BaseModel):
    focus: Optional[str] = Field(default=None, max_length=500)
    status: Optional[str] = Field(default=None, max_length=300)
    branch: Optional[str] = Field(default=None, max_length=120)


@router.post("/sessions/{session_id}/heartbeat")
async def heartbeat(session_id: str, body: SyncBody, request: Request):
    """Latido: actualiza presencia y devuelve lo nuevo desde el último sync."""
    session = await _own_session(request, session_id)
    db = get_db()
    now = _now()
    cursor = session.get("cursor") or session["started_at"]
    updates: Dict[str, Any] = {"last_seen": now}
    if body.focus is not None:
        updates["focus"] = body.focus.strip()
    if body.branch is not None:
        updates["branch"] = body.branch.strip() or None
    await db[SESSIONS].update_one({"_id": session_id}, {"$set": updates})
    if body.status:
        await _event(session["group"], "progress", body.status.strip(), session=session, task_ref=session.get("task"))
    # Leído por agente, no por sesión: al volver con otra sesión no se reentrega lo ya visto ni lo que envió él mismo.
    inbox_query = {"group": session["group"], "from_session": {"$ne": session_id},
                   "from_agent": {"$ne": session["agent"]}, "read_by": {"$ne": session_id},
                   "read_by_agents": {"$ne": session["agent"]},
                   "to": {"$in": ["all", session_id, session["agent"]]},
                   "created_at": {"$gte": session["started_at"] - timedelta(hours=24)}}
    inbox = await db[MESSAGES].find(inbox_query).sort("created_at", 1).limit(50).to_list(50)
    if inbox:
        await db[MESSAGES].update_many({"_id": {"$in": [m["_id"] for m in inbox]}},
                                       {"$addToSet": {"read_by": session_id, "read_by_agents": session["agent"]}})
    async def page(collection, field, name, limit, extra=None):
        checkpoint = session.get(name) or {"at": cursor, "id": ""}
        query = {"group": session["group"], **(extra or {}), "$or": [
            {field: {"$gt": checkpoint["at"]}},
            {field: checkpoint["at"], "_id": {"$gt": checkpoint["id"]}}]}
        rows = await db[collection].find(query).sort([(field, 1), ("_id", 1)]).limit(limit + 1).to_list(limit + 1)
        selected = rows[:limit]
        if selected:
            last = selected[-1]
            await db[SESSIONS].update_one({"_id": session_id}, {"$set": {name: {"at": last[field], "id": last["_id"]}}})
        return selected, len(rows) > limit

    news, more_events = await page(EVENTS, "created_at", "event_cursor", 30, {"session_id": {"$ne": session_id}})
    changed, more_tasks = await page(TASKS, "updated_at", "task_cursor", 20)
    team = [hub.public_session(s, now) for s in await _group_sessions(session["group"], days=1)
            if s["_id"] != session_id and hub.presence(s, now) in ("online", "idle")]
    settings = hub.work_settings((await _project(session["group"])).get("settings"))
    objective = hub.objective_progress(await _group_tasks(session["group"]), settings)
    return {
        "messages": [{"id": m["_id"], "from": m.get("from_agent") or m.get("person"), "to": m.get("to"),
                      "text": m.get("text"), "at": m.get("created_at"), "task": m.get("task_ref")} for m in inbox],
        "events": [hub.compact_event(e) for e in news],
        "tasks_changed": [hub.compact_task(t) for t in changed],
        "team": team,
        "work_mode": settings,
        "objective": objective,
        "protocol": hub.work_rules(settings),
        "has_more": {"events": more_events, "tasks": more_tasks, "messages": len(inbox) == 50},
        "next_sync_seconds": 0 if more_events or more_tasks or len(inbox) == 50 else hub.HEARTBEAT_HINT_SECONDS,
    }


class LogBody(BaseModel):
    kind: str = "progress"
    text: str = Field(min_length=1, max_length=4000)
    task: Optional[str] = Field(default=None, max_length=32)
    refs: List[str] = Field(default_factory=list, max_length=10)


@router.post("/sessions/{session_id}/events")
async def log_event(session_id: str, body: LogBody, request: Request):
    session = await _own_session(request, session_id)
    if body.kind not in hub.AGENT_EVENT_KINDS:
        raise HTTPException(422, f"kind va en: {', '.join(hub.AGENT_EVENT_KINDS)}.")
    refs = [str(ref)[:300] for ref in body.refs]
    event = await _event(session["group"], body.kind, body.text.strip(), session=session,
                         task_ref=body.task or session.get("task"), refs=refs)
    await get_db()[SESSIONS].update_one({"_id": session_id}, {"$set": {"last_seen": _now()}})
    return {"id": event["_id"], "kind": body.kind, "at": event["created_at"]}


class LeaveBody(BaseModel):
    summary: str = Field(min_length=1, max_length=6000)
    release_tasks: bool = True


@router.post("/sessions/{session_id}/leave")
async def leave(session_id: str, body: LeaveBody, request: Request):
    """Cierra la sesión con un relevo: lo primero que leerá el siguiente agente."""
    session = await _own_session(request, session_id)
    db = get_db()
    released = []
    if body.release_tasks:
        # También las bloqueadas: si no, quedan a nombre de una sesión cerrada y nadie las puede retomar.
        for task in await db[TASKS].find({"assignee_session": session_id,
                                          "status": {"$in": ["in_progress", "blocked"]}}).to_list(None):
            # Una bloqueada sigue bloqueada (su nota explica por qué); solo deja de tener dueño.
            status = "todo" if task["status"] == "in_progress" else task["status"]
            # Solo si nadie la cambió entre la lectura y aquí: si una persona la reasignó, no se pisa al dueño nuevo.
            result = await db[TASKS].update_one(
                {"_id": task["_id"], "assignee_session": session_id, "status": task["status"],
                 "updated_at": task.get("updated_at")},
                {"$set": {"status": status, "assignee_session": None, "assignee_agent": None, "updated_at": _now()},
                 "$push": {"notes": {"at": _now(), "by": session["agent"], "text": "Liberada al cerrar sesión."}}})
            if result.matched_count:
                released.append(task.get("key") or task["_id"])
    await db[SESSIONS].update_one({"_id": session_id}, {"$set": {"left_at": _now(), "last_seen": _now(),
                                                                 "summary": body.summary.strip()}})
    await _event(session["group"], "handoff", body.summary.strip(), session=session, task_ref=session.get("task"))
    return {"closed": True, "released_tasks": released}


# ── Tareas ───────────────────────────────────────────────────────────────
@router.get("/projects/{group}/tasks")
async def list_tasks(group: str, status: Optional[str] = None, area: Optional[str] = None):
    group = _group(group)
    tasks = await _group_tasks(group)
    index = hub.index_tasks(tasks)
    rows = [t for t in tasks if (not status or t.get("status") == status)
            and (not area or str(t.get("area") or "").lower() == area.lower())]
    return {"tasks": [hub.public_task(t, index) for t in rows], "total": len(rows)}


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    key: Optional[str] = None
    area: str = Field(default="", max_length=40)
    phase: str = Field(default="", max_length=40)
    depends_on: List[str] = Field(default_factory=list, max_length=20)
    sources: List[str] = Field(default_factory=list, max_length=20)
    session_id: Optional[str] = None
    proposed: bool = False


@router.post("/projects/{group}/tasks")
async def create_task(group: str, body: TaskCreate, request: Request):
    group = _group(group)
    session = await _optional_session(request, body.session_id, group)
    try:
        key = hub.task_key(body.key)
        depends = [k for k in (hub.task_key(d) for d in body.depends_on) if k]
        sources = [hub.normalize_path(s) for s in body.sources]
    except hub.HubError as exc:
        raise _bad(exc)
    db = get_db()
    if key and await db[TASKS].find_one({"group": group, "key": key}, {"_id": 1}):
        raise HTTPException(409, f"Ya existe la tarea {key} en este proyecto.")
    now = _now()
    settings = hub.work_settings((await _project(group)).get("settings"))
    # Lo que crea un agente queda como propuesta si él lo pide; en modo autónomo con aceptación automática, la
    # propuesta dentro del objetivo queda lista para tomarse. Lo que crea el plan o una persona, listo.
    accepted = body.proposed and settings["mode"] == "autonomous" and settings["auto_accept"] and hub.in_scope(
        {"phase": body.phase.strip(), "key": key}, settings)
    proposed = body.proposed and not accepted
    task = {"_id": _new_id(), "group": group, "key": key, "title": body.title.strip(),
            "description": body.description.strip(), "area": body.area.strip(), "phase": body.phase.strip(),
            "depends_on": depends, "sources": sources, "status": "proposed" if proposed else "todo",
            "assignee_session": None, "assignee_agent": None, "branch": None, "pr_url": None, "notes": [],
            "created_by": (session or {}).get("agent") or _principal(request).username,
            "created_at": now, "updated_at": now}
    try:
        hub.validate_dependencies(task, await _group_tasks(group))
    except hub.HubError as exc:
        raise _bad(exc)
    await db[TASKS].insert_one(task)
    await _event(group, "task", f"Creó {hub.task_label(task)}" + (" (propuesta)" if proposed else "")
                 + (" (aceptada sola: modo autónomo)" if accepted else "") + ".",
                 session=session, person=_principal(request).username, task_ref=key or task["_id"],
                 agent=(session or {}).get("agent"))
    return hub.public_task(task)


async def _task(ref: str, group: Optional[str] = None) -> Dict[str, Any]:
    """Por id; con el proyecto conocido (la sesión), también por clave del plan (T01)."""
    if hub.valid_id(ref):
        query: Dict[str, Any] = {"_id": ref}
    else:
        try:
            key = hub.task_key(ref)
        except hub.HubError as exc:
            raise _bad(exc)
        if not key or not group:
            raise HTTPException(422, "Usa el id de la tarea, o su clave junto con session_id.")
        query = {"group": group, "key": key}
    task = await get_db()[TASKS].find_one(query)
    if not task:
        raise HTTPException(404, f"No existe la tarea {ref}. hub_tasks lista las del proyecto.")
    return task


class ClaimBody(BaseModel):
    session_id: str


@router.post("/tasks/{task_id}/claim")
async def claim_task(task_id: str, body: ClaimBody, request: Request):
    """Toma una tarea de forma atómica; si depende de algo pendiente, dice qué y de quién."""
    session = await _own_session(request, body.session_id)
    task = await _task(task_id, session["group"])
    task_id = task["_id"]
    if task["group"] != session["group"]:
        raise HTTPException(422, "La tarea es de otro proyecto.")
    index = hub.index_tasks(await _group_tasks(task["group"]))
    settings = hub.work_settings((await _project(task["group"])).get("settings"))
    if settings["mode"] == "autonomous" and not hub.in_scope(task, settings):
        raise HTTPException(409, "Esta tarea está fuera del objetivo activo. Toma una del briefing o pide ampliar el alcance.")
    db = get_db()
    holder = task.get("assignee_session")
    holder_left = bool(holder and holder != session["_id"]
                       and ((await db[SESSIONS].find_one({"_id": holder}, {"left_at": 1})) or {}).get("left_at"))
    problem = hub.claim_check(task, index, session, holder_left=holder_left)
    if problem:
        raise HTTPException(409, {"message": f"{problem['reason']} {problem.get('hint', '')}".strip(), **problem})
    now = _now()
    free = [{"assignee_session": None}, {"assignee_session": session["_id"]}]
    if holder_left:
        free.append({"assignee_session": holder})
    # La rama es de la tarea: no se hereda de la sesión (un agente pasa por varias tareas).
    claimed = await db[TASKS].find_one_and_update(
        {"_id": task_id, "status": {"$in": ["todo", "blocked", "in_progress"]}, "$or": free},
        {"$set": {"status": "in_progress", "assignee_session": session["_id"], "assignee_agent": session["agent"],
                  "updated_at": now}},
        return_document=ReturnDocument.AFTER)
    if not claimed:
        raise HTTPException(409, {"message": "Otro agente la tomó un instante antes. Elige otra tarea disponible.",
                                  "pending": []})
    await db[SESSIONS].update_one({"_id": session["_id"]}, {"$set": {"task": task.get("key") or task_id, "last_seen": now}})
    await _event(task["group"], "task", f"Tomó {hub.task_label(task)}.", session=session, task_ref=task.get("key") or task_id)
    return hub.public_task(claimed, index)


class TaskUpdate(BaseModel):
    session_id: Optional[str] = None
    status: Optional[Literal["proposed", "todo", "in_progress", "blocked", "review", "done", "dropped"]] = None
    note: str = Field(default="", max_length=2000)
    branch: Optional[str] = Field(default=None, max_length=120)
    pr_url: Optional[str] = Field(default=None, max_length=300)
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=4000)
    area: Optional[str] = Field(default=None, max_length=40)
    phase: Optional[str] = Field(default=None, max_length=40)
    depends_on: Optional[List[str]] = Field(default=None, max_length=20)
    verification_path: Optional[str] = Field(default=None, max_length=200, pattern=r"^/[^?#\\\r\n]*$")
    expected_visible_text: Optional[str] = Field(default=None, max_length=300)

    @field_validator("verification_path")
    @classmethod
    def local_verification_path(cls, value):
        if value and value.startswith("//"):
            raise ValueError("La ruta debe pertenecer a la app; no uses otro dominio.")
        return value


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate, request: Request):
    session = await _optional_session(request, body.session_id)
    if not session and getattr(_principal(request), "via_token", False):
        raise HTTPException(403, "Para actualizar tareas con un token usa session_id de hub_join. El cierre humano se hace desde la consola.")
    task = await _task(task_id, (session or {}).get("group"))
    task_id = task["_id"]
    if session and task["group"] != session["group"]:
        raise HTTPException(422, "La tarea es de otro proyecto.")
    holder = task.get("assignee_session")
    settings = hub.work_settings((await _project(task["group"])).get("settings"))
    if session:
        if settings["mode"] == "autonomous" and not hub.in_scope(task, settings):
            raise HTTPException(409, "Esta tarea está fuera del objetivo activo.")
        if body.status == "in_progress" and (holder != session["_id"] or task["status"] != "in_progress"):
            raise HTTPException(409, "Usa hub_claim_task para tomar la tarea y comprobar sus dependencias.")
        if body.status in ("review", "blocked") and holder != session["_id"]:
            raise HTTPException(409, "Solo el agente que tomó la tarea puede enviarla a revisión o marcarla bloqueada.")
        if task["status"] == "proposed" and body.status not in (None, "proposed"):
            raise HTTPException(409, "La propuesta debe aceptarse desde la consola antes de tomarla.")
    # Un agente no le cambia la tarea en curso a otro; una persona (sin sesión) sí puede: es quien integra.
    if session and holder and holder != session["_id"] and task.get("status") == "in_progress":
        raise HTTPException(409, f"{hub.task_label(task)} la tiene {task.get('assignee_agent')}: mándale un mensaje.")
    if body.status == "done":
        problem = hub.done_check(task, session, settings)
        if problem:
            raise HTTPException(409, problem)
    values: Dict[str, Any] = {"updated_at": _now()}
    try:
        if body.depends_on is not None:
            values["depends_on"] = [k for k in (hub.task_key(d) for d in body.depends_on) if k]
    except hub.HubError as exc:
        raise _bad(exc)
    for field in ("title", "description", "area", "phase", "branch", "pr_url", "verification_path", "expected_visible_text"):
        value = getattr(body, field)
        if value is not None:
            values[field] = (value.strip() or None) if field in ("branch", "pr_url") else value.strip()
    if values.get("pr_url") and not hub.valid_pr_url(values["pr_url"]):
        raise HTTPException(422, "pr_url debe ser un pull request ya creado (…/pull/123 o …/merge_requests/123). "
                                 "Un enlace de compare no es un PR: déjalo en la nota y avisa a una persona.")
    if body.status:
        values["status"] = body.status
        if body.status in ("todo", "proposed", "dropped"):
            values.update(assignee_session=None, assignee_agent=None)
    actor = (session or {}).get("agent") or _principal(request).username
    try:
        hub.validate_dependencies({**task, **values}, await _group_tasks(task["group"]))
    except hub.HubError as exc:
        raise _bad(exc)
    if body.status in ("in_progress", "review", "done"):
        pending = hub.pending_dependencies({**task, **values}, hub.index_tasks(await _group_tasks(task["group"])))
        if pending:
            raise HTTPException(409, "Antes deben terminar: " + ", ".join(p["ref"] for p in pending))
    if body.status == "done":
        values.update(reviewed_by=actor, reviewed_at=_now())
    elif body.status and task["status"] == "done":
        values.update(reviewed_by=None, reviewed_at=None)
    change: Dict[str, Any] = {"$set": values}
    if body.note.strip():
        change["$push"] = {"notes": {"at": _now(), "by": actor, "text": body.note.strip()}}
    updated = await get_db()[TASKS].find_one_and_update(
        {"_id": task_id, "status": task["status"], "updated_at": task.get("updated_at")}, change,
        return_document=ReturnDocument.AFTER)
    if not updated:
        raise HTTPException(409, "La tarea cambió mientras la editabas. Actualiza y vuelve a intentarlo.")
    if body.status and body.status != "in_progress" and holder:
        await get_db()[SESSIONS].update_one(
            {"_id": holder, "task": task.get("key") or task_id}, {"$set": {"task": None}})
    parts = []
    if body.status:
        parts.append(f"estado {body.status}")
    if values.get("pr_url"):
        parts.append(f"PR {values['pr_url']}")
    if body.note.strip():
        parts.append(body.note.strip()[:200])
    summary = f"{hub.task_label(task)}: " + (", ".join(parts) or "editada")
    await _event(task["group"], "task", summary, session=session, person=_principal(request).username,
                 task_ref=task.get("key") or task_id, agent=actor)
    if body.status == "done":
        await _announce_objective(task["group"])
        if hub.work_settings((await _project(task["group"])).get("settings"))["integration"] == "auto":
            _start_integration(task_id)
    return hub.public_task(updated)


# ── Integración a main ────────────────────────────────────────────────────
_JOBS: Dict[str, Any] = {}  # tareas en integración en este proceso (evita dos a la vez)
_INTEGRATION_LOCKS: Dict[str, Any] = {}


async def _integration_target(group: str, settings: Dict[str, Any]) -> Tuple[str, str]:
    """(app, repo owner/name) que recibe las integraciones del proyecto."""
    if group == workspace.PLATFORM_GROUP:
        raise integration.IntegrationBlocked("El núcleo de Kaanbal se actualiza manualmente; no se despliega desde el Hub.")
    query: Dict[str, Any] = {"app_group": group, "repo_url": {"$nin": [None, ""]}}
    if settings.get("integration_app"):
        query["name"] = settings["integration_app"]
    apps = await get_db().apps.find(query, {"name": 1, "repo_url": 1, "environments": 1}).to_list(20)
    if len(apps) != 1:
        names = ", ".join(a["name"] for a in apps) or "el grupo no tiene apps con repositorio"
        raise integration.IntegrationBlocked(f"Elige la app que recibe las integraciones (integration_app): {names}.")
    repo = integration.repo_from_url(apps[0]["repo_url"])
    if not repo:
        raise integration.IntegrationBlocked("La integración directa solo admite repositorios de GitHub.")
    if settings.get("integration_env", "dev") not in (apps[0].get("environments") or ["prod"]):
        raise integration.IntegrationBlocked("Prepara primero el ambiente Dev del stack completo desde el proyecto.")
    return apps[0]["name"], repo


def _start_integration(task_id: str) -> bool:
    if task_id in _JOBS and not _JOBS[task_id].done():
        return False
    _JOBS[task_id] = asyncio.create_task(_integration_job(task_id))
    return True


async def _integration_job(task_id: str) -> str:
    task = await get_db()[TASKS].find_one({"_id": task_id})
    if not task:
        return "blocked"
    # One deployment at a time per project, so two agents do not overwrite the
    # expected image while the first task is still being verified.
    lock = _INTEGRATION_LOCKS.setdefault(task["group"], asyncio.Lock())
    async with lock:
        return await _run_integration_job(task_id)


async def _run_integration_job(task_id: str) -> str:
    db = get_db()
    task = await db[TASKS].find_one({"_id": task_id})
    group = task["group"]
    settings = hub.work_settings((await _project(group)).get("settings"))
    label = hub.task_label(task)
    notify = [a for a in (task.get("assignee_agent"),) if a]

    async def report(state: str, detail: str, extra: Dict[str, Any]) -> None:
        prior = (await db[TASKS].find_one({"_id": task_id}) or {}).get("integration") or {}
        record = {**prior, "state": state, "detail": detail, "at": _now(),
                  "environment": settings["integration_env"], **extra}
        change: Dict[str, Any] = {"$set": {"integration": record, "updated_at": _now()}}
        if state in ("blocked", "deploy_failed"):
            change["$set"]["status"] = "blocked"
            change["$push"] = {"notes": {"at": _now(), "by": "kaanbal", "text": f"No se integró: {detail}"}}
        await db[TASKS].update_one({"_id": task_id}, change)
        await _event(group, "task", f"{label} · integración {state}: {detail}", agent="kaanbal",
                     task_ref=task.get("key") or task_id)
        if state in ("blocked", "deploy_failed", "deployed", "verified", "deploy_unknown"):
            for to in notify + ["people"]:
                await db[MESSAGES].insert_one({"_id": _new_id(), "group": group, "to": to, "text": f"{label}: {detail}"[:4000],
                                               "task_ref": task.get("key"), "from_session": None, "from_agent": "kaanbal",
                                               "person": None, "created_at": _now(), "read_by": []})

    try:
        app, repo = await _integration_target(group, settings)
        config = await db.system_config.find_one({"_id": "main"}) or {}
        gh = integration.GitHubIntegration(config.get("github_token") or config.get("git_token") or "")
    except integration.IntegrationBlocked as exc:
        await report("blocked", str(exc), {})
        return "blocked"
    from app.services.argocd_service import argocd_service

    async def env_status(name):
        return await argocd_service.get_env_status(name, settings["integration_env"])

    app_doc = await db.apps.find_one({"name": app}) or {}
    async def smoke(sha):
        from app.services import domain_service
        domain = (await domain_service.resolve_for_app(app_doc)).get("fqdn")
        if not domain:
            return {"ok": False, "detail": "Falta el dominio del ambiente; no se puede comprobar su URL."}
        url = "https://" + domain_service.public_host(app, settings["integration_env"], domain)
        return await integration.verify_business_app(url, path=task.get("verification_path") or "/",
                                                     expected_text=task.get("expected_visible_text") or "")

    return await integration.run(task, repo, app, gh, env_status, report,
                                 require_checks=settings["require_checks"],
                                 base_branch=settings["integration_branch"] or None, environment=settings["integration_env"],
                                 verify=smoke if app_doc.get("template") == "business-base" else None)


@router.post("/tasks/{task_id}/integrate")
async def integrate_task(task_id: str, request: Request):
    """Integra ya una tarea cerrada (también en modo manual): checks, merge a main y seguimiento del despliegue."""
    task = await _task(task_id)
    problem = integration.precheck(task)
    if problem:
        raise HTTPException(409, problem)
    started = _start_integration(task["_id"])
    await _event(task["group"], "task", f"{hub.task_label(task)}: integración pedida por {_principal(request).username}.",
                 person=_principal(request).username, task_ref=task.get("key") or task["_id"])
    return {"started": started, "task": task.get("key") or task["_id"],
            "hint": "Sigue el avance en la traza o en el detalle de la tarea (integration)."}


async def _announce_objective(group: str) -> None:
    """Al cumplirse el objetivo, avisa a las personas qué fusionar: los agentes se detienen y nadie más lo diría."""
    project = await _project(group)
    settings = hub.work_settings(project.get("settings"))
    objective = hub.objective_progress(await _group_tasks(group), settings)
    if not objective["complete"]:
        return
    signature = f"{settings['objective']}|{','.join(settings['scope_phases'] + settings['scope_tasks'])}"
    if project.get("objective_announced") == signature:
        return
    await _touch_project(group, objective_announced=signature)
    lines = [f"- {d['task']}: " + (d["pr_url"] or f"rama {d['branch']}") for d in objective["deliveries"]]
    text = (f"Objetivo cumplido ({objective['done']}/{objective['total']}): {settings['objective'] or 'alcance actual'}. "
            "Los agentes se detienen. Para seguir: revisa y fusiona lo entregado y elige el siguiente objetivo en "
            "'Cambiar modo'." + ("\n" + "\n".join(lines) if lines else ""))
    await get_db()[MESSAGES].insert_one({"_id": _new_id(), "group": group, "to": "people", "text": text[:4000],
                                         "task_ref": None, "from_session": None, "from_agent": "kaanbal",
                                         "person": None, "created_at": _now(), "read_by": []})
    await _event(group, "board", text[:4000], agent="kaanbal")


# ── Mensajes ─────────────────────────────────────────────────────────────
class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    to: str = Field(default="all", max_length=48)
    session_id: Optional[str] = None
    task: Optional[str] = Field(default=None, max_length=32)


@router.post("/projects/{group}/messages")
async def send_message(group: str, body: MessageBody, request: Request):
    """De un agente a otro (por nombre o sesión), a todos, o a las personas ('people')."""
    group = _group(group)
    session = await _optional_session(request, body.session_id, group)
    to = body.to.strip() or "all"
    if to not in ("all", "people") and not hub.valid_id(to):
        try:
            to = hub.agent_name(to)
        except hub.HubError as exc:
            raise _bad(exc)
    doc = {"_id": _new_id(), "group": group, "to": to, "text": body.text.strip(), "task_ref": body.task,
           "from_session": (session or {}).get("_id"), "from_agent": (session or {}).get("agent"),
           "person": _principal(request).username, "created_at": _now(), "read_by": []}
    await get_db()[MESSAGES].insert_one(doc)
    sender = doc["from_agent"] or doc["person"]
    await _event(group, "message", f"{sender} → {to}: {doc['text'][:300]}", session=session,
                 person=doc["person"], task_ref=body.task, agent=doc["from_agent"])
    return {"id": doc["_id"], "to": to, "at": doc["created_at"]}


@router.get("/projects/{group}/messages")
async def list_messages(group: str, limit: int = Query(default=50, ge=1, le=200)):
    group = _group(group)
    rows = await get_db()[MESSAGES].find({"group": group}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"messages": [{"id": m["_id"], "from": m.get("from_agent") or m.get("person"), "to": m.get("to"),
                          "text": m.get("text"), "at": m.get("created_at"), "task": m.get("task_ref"),
                          "read": len(m.get("read_by") or [])} for m in rows]}


# ── Traza ────────────────────────────────────────────────────────────────
@router.get("/projects/{group}/trace")
async def trace(group: str, view: Literal["tree", "list"] = "list", day: Optional[str] = None,
                agent: Optional[str] = None, kind: Optional[str] = None, session_id: Optional[str] = None,
                limit: int = Query(default=100, ge=1, le=500)):
    group = _group(group)
    query: Dict[str, Any] = {"group": group}
    if day:
        try:
            start = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(422, "day va como AAAA-MM-DD.")
        query["created_at"] = {"$gte": start, "$lt": start + timedelta(days=1)}
    if agent:
        query["agent"] = agent
    if kind:
        query["kind"] = kind
    if session_id:
        query["session_id"] = session_id
    db = get_db()
    if view == "tree":
        rows = await db[EVENTS].find(query, {"created_at": 1, "agent": 1, "person": 1, "kind": 1, "session_id": 1}) \
            .sort("created_at", -1).limit(3000).to_list(3000)
        return {"group": group, "tree": hub.trace_tree(rows)}
    rows = await db[EVENTS].find(query).sort("created_at", -1).limit(limit).to_list(limit)
    return {"group": group, "events": [{**hub.compact_event(e), "id": e["_id"], "session_id": e.get("session_id"),
                                        "harness": e.get("harness"), "person": e.get("person"), "refs": e.get("refs") or []}
                                       for e in rows]}


# ── Lecciones ────────────────────────────────────────────────────────────
class LessonBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    scope: Literal["project", "platform"] = "project"
    session_id: Optional[str] = None


@router.post("/projects/{group}/lessons")
async def add_lesson(group: str, body: LessonBody, request: Request):
    group = _group(group)
    session = await _optional_session(request, body.session_id, group)
    doc = {"_id": _new_id(), "group": group, "scope": body.scope, "text": body.text.strip(),
           "agent": (session or {}).get("agent"), "person": _principal(request).username, "created_at": _now()}
    await get_db()[LESSONS].insert_one(doc)
    await _event(group, "lesson", f"Lección ({body.scope}): {doc['text'][:300]}", session=session,
                 person=doc["person"], agent=doc["agent"])
    return {"id": doc["_id"], "scope": body.scope}


@router.get("/lessons")
async def list_lessons(scope: Optional[Literal["project", "platform"]] = None, limit: int = Query(default=100, ge=1, le=500)):
    query = {"scope": scope} if scope else {}
    rows = await get_db()[LESSONS].find(query).sort("created_at", -1).limit(limit).to_list(limit)
    return {"lessons": [{"id": l["_id"], "group": l.get("group"), "scope": l.get("scope"), "text": l.get("text"),
                         "agent": l.get("agent"), "person": l.get("person"), "at": l.get("created_at")} for l in rows]}


# ── Archivos ─────────────────────────────────────────────────────────────
@router.get("/projects/{group}/files")
async def list_files(group: str, prefix: str = ""):
    group = _group(group)
    rows = await _file_rows(group)
    if prefix:
        try:
            clean = hub.normalize_path(prefix)
        except hub.HubError as exc:
            raise _bad(exc)
        rows = [r for r in rows if r["path"] == clean or r["path"].startswith(clean + "/")]
    return {"group": group, "files": rows, "summary": hub.files_summary(rows)}


@router.get("/projects/{group}/files/content")
async def file_content(group: str, path: str, format: Literal["raw", "json"] = "raw"):
    """`raw` para la consola (vista previa, descarga); `json` para el MCP: texto o imagen en base64."""
    group = _group(group)
    try:
        path = hub.normalize_path(path)
    except hub.HubError as exc:
        raise _bad(exc)
    row, data = await _read_file(group, path)
    ctype = (row.get("metadata") or {}).get("content_type") or hub.content_type(path)
    if format == "raw":
        return Response(content=data, media_type=ctype, headers={
            "Content-Disposition": f"inline; filename=\"{path.rsplit('/', 1)[-1].encode('ascii', 'ignore').decode() or 'archivo'}\"",
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
    result: Dict[str, Any] = {"path": path, "content_type": ctype, "size": len(data)}
    if hub.is_text(path) or ctype.startswith("text/"):
        text = data.decode("utf-8", errors="replace")
        result.update(text=text[:hub.MAX_TEXT_CHARS], truncated=len(text) > hub.MAX_TEXT_CHARS)
    elif ctype in hub.IMAGE_TYPES and len(data) <= hub.MAX_INLINE_IMAGE_BYTES:
        result["base64"] = base64.b64encode(data).decode("ascii")
    else:
        result["note"] = "Archivo binario o demasiado grande para mostrarlo aquí; ábrelo desde la consola."
    return result


@router.post("/projects/{group}/files")
async def upload_files(group: str, request: Request, file: UploadFile = File(...), dest: str = Form(hub.SOURCE_ROOT),
                       extract: bool = Form(True)):
    """Sube un archivo o un ZIP en una sola petición (para lo grande, mejor /uploads por partes)."""
    group = _group(group)
    data = await file.read(hub.MAX_UPLOAD_BYTES + 1)
    if len(data) > hub.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"El archivo pasa de {hub.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return await _ingest(group, file.filename or "archivo", data, dest, extract, _principal(request).username)


async def _ingest(group: str, filename: str, data: bytes, dest: str, extract: bool, actor: str) -> Dict[str, Any]:
    """Guarda un archivo subido; un ZIP se descomprime en `dest` (los ZIP internos, un nivel)."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1] or "archivo"
    try:
        if extract and name.lower().endswith(".zip"):
            entries = hub.extract_zip(data, dest)
        else:
            entries = [(hub.normalize_path(f"{dest}/{name}"), data)]
    except hub.HubError as exc:
        raise _bad(exc)
    stored = [await _store_file(group, path, content, actor, origin=name) for path, content in entries]
    await _touch_project(group)
    await _event(group, "file", f"Subió {name}: {len(stored)} archivo(s) en {dest}/.", person=actor)
    await activity_log.log("hub.files.uploaded", category=CATEGORY_APP, actor=actor, target=group,
                           detail={"name": name, "files": len(stored)})
    plan = hub.find_plan(p for p, _ in entries)
    return {"stored": len(stored), "bytes": sum(item["size"] for item in stored), "dest": dest,
            "plan_found": plan, "files": stored[:200]}


# ── Subida por partes ────────────────────────────────────────────────────
# Una petición larga la corta el proxy (túnel, ingress) en conexiones lentas. Por partes,
# cada petición es corta, se ve el avance y una parte que falla se reintenta sola.
class UploadStart(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    size: int = Field(ge=1, le=hub.MAX_UPLOAD_BYTES)
    dest: str = Field(default=hub.SOURCE_ROOT, max_length=200)
    extract: bool = True


@router.post("/projects/{group}/uploads")
async def start_upload(group: str, body: UploadStart, request: Request):
    group = _group(group)
    try:
        dest = hub.normalize_path(body.dest)
    except hub.HubError as exc:
        raise _bad(exc)
    db = get_db()
    stale = await db[UPLOADS].find({"created_at": {"$lt": _now() - hub.UPLOAD_TTL}}, {"_id": 1}).to_list(None)
    for old in stale:
        await db[UPLOAD_PARTS].delete_many({"upload": old["_id"]})
        await db[UPLOADS].delete_one({"_id": old["_id"]})
    chunks = hub.chunk_count(body.size)
    upload = {"_id": _new_id(), "group": group, "name": body.name, "size": body.size, "dest": dest,
              "extract": body.extract, "chunks": chunks, "person": _principal(request).username, "created_at": _now()}
    await db[UPLOADS].insert_one(upload)
    return {"upload_id": upload["_id"], "chunk_bytes": hub.CHUNK_BYTES, "chunks": chunks}


async def _own_upload(request: Request, upload_id: str) -> Dict[str, Any]:
    if not hub.valid_id(upload_id):
        raise HTTPException(422, "upload_id inválido.")
    upload = await get_db()[UPLOADS].find_one({"_id": upload_id})
    if not upload:
        raise HTTPException(404, "Esa subida no existe o venció: vuelve a empezarla.")
    if upload.get("person") != _principal(request).username:
        raise HTTPException(403, "Esa subida es de otra persona.")
    return upload


@router.get("/uploads/{upload_id}")
async def upload_status(upload_id: str, request: Request):
    """Qué partes ya llegaron: para reanudar sin volver a mandarlas."""
    upload = await _own_upload(request, upload_id)
    parts = await get_db()[UPLOAD_PARTS].find({"upload": upload_id}, {"index": 1}).to_list(None)
    return {"upload_id": upload_id, "chunks": upload["chunks"], "received": sorted(p["index"] for p in parts)}


@router.put("/uploads/{upload_id}/chunks/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request):
    upload = await _own_upload(request, upload_id)
    if not 0 <= index < upload["chunks"]:
        raise HTTPException(422, f"La parte {index} no existe: van de 0 a {upload['chunks'] - 1}.")
    data = await request.body()
    if len(data) != hub.chunk_length(upload["size"], index):
        raise HTTPException(422, f"La parte {index} debe medir {hub.chunk_length(upload['size'], index)} bytes.")
    await get_db()[UPLOAD_PARTS].update_one({"_id": f"{upload_id}:{index}"}, {"$set": {
        "upload": upload_id, "index": index, "data": data, "at": _now()}}, upsert=True)
    return {"index": index, "bytes": len(data)}


@router.post("/uploads/{upload_id}/complete")
async def complete_upload(upload_id: str, request: Request):
    """Une las partes y guarda el archivo como en una subida normal (un ZIP se descomprime)."""
    upload = await _own_upload(request, upload_id)
    db = get_db()
    parts = await db[UPLOAD_PARTS].find({"upload": upload_id}).sort("index", 1).to_list(None)
    missing = sorted(set(range(upload["chunks"])) - {p["index"] for p in parts})
    if missing:
        raise HTTPException(409, {"message": f"Faltan {len(missing)} parte(s); reenvíalas y vuelve a completar.",
                                  "missing": missing[:50]})
    data = b"".join(bytes(p["data"]) for p in parts)
    if len(data) != upload["size"]:
        raise HTTPException(409, "El archivo unido no mide lo anunciado: vuelve a empezar la subida.")
    result = await _ingest(upload["group"], upload["name"], data, upload["dest"], upload["extract"], upload["person"])
    await db[UPLOAD_PARTS].delete_many({"upload": upload_id})
    await db[UPLOADS].delete_one({"_id": upload_id})
    return result


class NoteBody(BaseModel):
    path: str
    content: str = ""
    base64: Optional[str] = None
    session_id: Optional[str] = None


@router.post("/projects/{group}/notes")
async def write_note(group: str, body: NoteBody, request: Request):
    """Lo que escribe un agente: siempre bajo live/ (fuente/ es de las personas)."""
    group = _group(group)
    session = await _optional_session(request, body.session_id, group)
    try:
        path = hub.normalize_path(body.path)
    except hub.HubError as exc:
        raise _bad(exc)
    if not hub.is_live_path(path):
        path = f"{hub.LIVE_ROOT}/{path}"
    if body.base64:
        try:
            data = base64.b64decode(body.base64, validate=True)
        except ValueError:
            raise HTTPException(422, "base64 inválido.")
    else:
        data = body.content.encode("utf-8")
    if len(data) > hub.MAX_NOTE_BYTES:
        raise HTTPException(413, "La nota pasa de 2 MB: divídela o súbela desde la consola.")
    actor = (session or {}).get("agent") or _principal(request).username
    stored = await _store_file(group, path, data, actor, origin="nota")
    await _event(group, "file", f"Escribió {path}.", session=session, person=_principal(request).username,
                 refs=[path], agent=(session or {}).get("agent"))
    return stored


@router.delete("/projects/{group}/files")
async def delete_files(group: str, path: str, request: Request):
    """Quita un archivo o una carpeta completa del drive del proyecto."""
    group = _group(group)
    try:
        clean = hub.normalize_path(path)
    except hub.HubError as exc:
        raise _bad(exc)
    rows = [r for r in await _files().find({"metadata.group": group}, {"_id": 1, "filename": 1}).to_list(None)
            if r["filename"] == clean or r["filename"].startswith(clean + "/")]
    for row in rows:
        await _bucket().delete(row["_id"])
    if rows:
        await _event(group, "file", f"Quitó {clean} ({len(rows)} archivo(s)).", person=_principal(request).username)
    return {"deleted": len(rows)}


class PlanImport(BaseModel):
    path: Optional[str] = None
    replace_board: bool = False


@router.post("/projects/{group}/plan/import")
async def import_plan(group: str, body: PlanImport, request: Request):
    """Crea o actualiza las tareas del kaanbal.hub.json del drive (por key; no toca su estado)."""
    group = _group(group)
    rows = await _file_rows(group)
    path = body.path or hub.find_plan(r["path"] for r in rows)
    if not path:
        raise HTTPException(404, f"No hay {hub.PLAN_FILE} en el proyecto. Súbelo con las fases o indica path.")
    try:
        _, data = await _read_file(group, hub.normalize_path(path))
        plan = hub.parse_plan(data)
    except hub.HubError as exc:
        raise _bad(exc)
    db = get_db()
    created = updated = 0
    actor = _principal(request).username
    for item in plan["tasks"]:
        existing = await db[TASKS].find_one({"group": group, "key": item["key"]})
        if existing:
            await db[TASKS].update_one({"_id": existing["_id"]}, {"$set": {**item, "updated_at": _now()}})
            updated += 1
        else:
            await db[TASKS].insert_one({"_id": _new_id(), "group": group, **item, "status": "todo",
                                        "assignee_session": None, "assignee_agent": None, "branch": None,
                                        "pr_url": None, "notes": [], "created_by": f"plan:{path}",
                                        "created_at": _now(), "updated_at": _now()})
            created += 1
    project = await _project(group)
    board_set = bool(plan["board"]) and (body.replace_board or not project.get("board"))
    if board_set:
        await _touch_project(group, board=plan["board"], board_updated_by=f"plan:{path}", board_updated_at=_now())
    await _event(group, "task", f"Importó el plan {path}: {created} nuevas, {updated} actualizadas.", person=actor)
    return {"path": path, "created": created, "updated": updated, "board_set": board_set}


# ── Secretario ───────────────────────────────────────────────────────────
class DigestBody(BaseModel):
    use_ai: bool = True
    create_tasks: bool = False


@router.post("/projects/{group}/digest")
async def digest(group: str, body: DigestBody, request: Request):
    """Resumen del estado para las personas; con IA, además, riesgos y tareas sugeridas (como propuestas)."""
    from app.services.ai_service import ai_service

    group = _group(group)
    now = _now()
    project = await _project(group)
    sessions, tasks = await _group_sessions(group), await _group_tasks(group)
    events = await _recent_events(group, 200)
    signals = hub.digest_signals(sessions=sessions, tasks=tasks, events=events, now=now)
    written: Dict[str, Any] = {}
    ai_used = False
    if body.use_ai and await ai_service.configured():
        answer = await ai_service.ask(hub.digest_prompt(project, signals, events), json_mode=True, max_tokens=900,
                                      system="Eres el secretario de un equipo de agentes de código. Respondes en JSON.")
        written = hub.parse_digest(answer)
        ai_used = bool(written)
    proposed = []
    if body.create_tasks:
        for item in written.get("suggested_tasks") or []:
            task = {"_id": _new_id(), "group": group, "key": None, "title": item["title"], "description": item["why"],
                    "area": item["area"], "phase": "", "depends_on": [], "sources": [], "status": "proposed",
                    "assignee_session": None, "assignee_agent": None, "branch": None, "pr_url": None, "notes": [],
                    "created_by": "secretario", "created_at": now, "updated_at": now}
            await get_db()[TASKS].insert_one(task)
            proposed.append(task["_id"])
    result = {"at": now, "ai": ai_used, "signals": signals, **written, "proposed_task_ids": proposed}
    await _touch_project(group, last_digest=result)
    text = written.get("summary") or (f"{len(signals['online'])} agente(s) en línea, {len(signals['alerts'])} alerta(s), "
                                      f"{len(signals['ready_to_start'])} tarea(s) lista(s) para empezar.")
    await _event(group, "digest", text, agent="secretario", person=_principal(request).username)
    return result


# ── Guías ────────────────────────────────────────────────────────────────
@router.get("/guides")
async def hub_guides(group: str = "", harness: str = "", specialty: str = "", agent: str = ""):
    """Textos para arrancar: prompt de fases para ChatGPT, mensaje inicial de un agente y bloque para AGENTS.md."""
    slug = group if hub.valid_group(group) else "<grupo>"
    try:
        name = hub.agent_name(agent) if agent.strip() else ""
    except hub.HubError:
        name = ""
    return {"chatgpt_phases": guides.CHATGPT_PHASES_PROMPT, "agent_start": guides.agent_start_prompt(
        slug, harness[:30], specialty[:120], name), "repo_snippet": guides.REPO_SNIPPET, "protocol": hub.PROTOCOL,
        "plan_file": hub.PLAN_FILE}


# ── Contexto compartido y mejora de la plataforma ─────────────────────────
class CheckpointBody(BaseModel):
    session_id: str
    summary: str = Field(min_length=1, max_length=2000)
    decisions: List[str] = Field(default_factory=list, max_length=5)
    next_steps: List[str] = Field(default_factory=list, max_length=5)


@router.post("/projects/{group}/checkpoints")
async def save_checkpoint(group: str, body: CheckpointBody, request: Request):
    group = _group(group)
    session = await _optional_session(request, body.session_id, group)
    if not session:
        raise HTTPException(422, "Guarda el resumen con el session_id que te dio hub_join en este proyecto.")
    if not body.summary.strip() or any(len(item) > 400 for item in body.decisions + body.next_steps):
        raise HTTPException(422, "Escribe un resumen y hasta cinco decisiones/pasos de 400 caracteres cada uno.")
    doc = {"group": group, "agent": session["agent"], "person": session["person"],
           "summary": body.summary.strip(), "decisions": body.decisions, "next_steps": body.next_steps,
           "session_id": session["_id"], "updated_at": _now()}
    await get_db()[CHECKPOINTS].update_one({"_id": f"{group}:{session['agent']}:{session['person']}"},
                                          {"$set": doc}, upsert=True)
    await _event(group, "checkpoint", body.summary, session=session,
                 refs=["Resumen compartido del proyecto"])
    return {"saved": True, "checkpoint": doc}


class FeedbackBody(BaseModel):
    session_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    kind: Literal["friction", "idea", "bug"] = "friction"


@router.post("/projects/{group}/feedback")
async def report_feedback(group: str, body: FeedbackBody, request: Request):
    group = _group(group)
    session = await _optional_session(request, body.session_id, group)
    if not session and getattr(_principal(request), "via_token", False):
        raise HTTPException(403, "Un agente reporta con el session_id del proyecto de origen.")
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(422, "Escribe el título y lo observado.")
    actor = (session or {}).get("agent") or _principal(request).username
    key = "F-" + _new_id()[:8]
    doc = {"_id": _new_id(), "group": workspace.PLATFORM_GROUP, "key": key, "title": body.title.strip(),
           "description": body.description.strip(), "status": "proposed", "area": "plataforma",
           "phase": "Mejoras", "depends_on": [], "sources": [], "notes": [],
           "created_by": actor, "created_at": _now(), "updated_at": _now(),
           "origin": {"group": group, "agent": actor, "person": _principal(request).username, "kind": body.kind}}
    await get_db()[TASKS].insert_one(doc)
    await _touch_project(workspace.PLATFORM_GROUP, name=workspace.PLATFORM_NAME,
                         description=workspace.PLATFORM_DESCRIPTION)
    await _event(workspace.PLATFORM_GROUP, "feedback", f"{key} · {body.title.strip()} (desde {group})",
                 person=_principal(request).username, agent=actor, task_ref=key, refs=[f"/hub/{group}"])
    if group != workspace.PLATFORM_GROUP:
        await _event(group, "feedback", f"Reportó {key} a Software Factory: {body.title.strip()}",
                     session=session, person=_principal(request).username, agent=actor,
                     refs=[f"/hub/{workspace.PLATFORM_GROUP}"])
    return {"task": hub.public_task(doc), "origin_group": group, "platform_group": workspace.PLATFORM_GROUP}
