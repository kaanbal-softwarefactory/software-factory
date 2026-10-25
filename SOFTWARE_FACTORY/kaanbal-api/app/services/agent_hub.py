"""
Hub de agentes: la mesa donde se coordinan los agentes de un proyecto
=====================================================================

Kaanbal no desarrolla: lo hacen Codex, Claude Code, Cursor o ChatGPT con su propio
harness. El Hub es lo que tienen en común cuando trabajan en el mismo proyecto
(un grupo de Kaanbal):

- **Sesiones**: cada agente que entra se presenta (quién es, qué harness usa, en qué
  es bueno) y deja latido. Así el siguiente sabe quién está en línea.
- **Traza**: lo que hace cada sesión, en eventos cortos (avance, decisión, bloqueo,
  pregunta, relevo). Se lee por proyecto → día → agente sin cargar todo el histórico.
- **Tareas** con dependencias: se toman de forma atómica; si dependen de algo sin
  terminar, el Hub dice qué falta y quién lo tiene.
- **Tablero**: el archivo central del proyecto. Lo primero que lee quien llega.
- **Archivos**: la fuente (el ZIP de fases que sube una persona) y `live/`, la carpeta
  de trabajo donde los agentes dejan notas, contratos e informes.
- **Lecciones**: lo aprendido, del proyecto o de la plataforma (sirven en otros proyectos).
- **Secretario**: un resumen del estado, determinista y, si hay IA configurada,
  redactado por ella. Solo informa y propone tareas: no decide ni programa.

Este módulo es lógica pura (sin base de datos) para poder probarla sola; el router
`app/routers/hub.py` guarda y lee.
"""

from __future__ import annotations

import io
import json
import mimetypes
import posixpath
import re
import unicodedata
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# ── Vocabulario ──────────────────────────────────────────────────────────
HARNESSES = ("codex", "claude", "cursor", "chatgpt", "kaanbal", "otro")
EVENT_KINDS = ("join", "leave", "progress", "decision", "blocker", "question", "handoff",
               "lesson", "note", "task", "file", "board", "digest", "message")
# Las que escribe un agente con hub_log; el resto las pone el propio Hub.
AGENT_EVENT_KINDS = ("progress", "decision", "blocker", "question", "note")
TASK_STATUSES = ("proposed", "todo", "in_progress", "blocked", "review", "done", "dropped")
OPEN_STATUSES = ("todo", "in_progress", "blocked", "review")
CLOSED_STATUSES = ("done", "dropped")
LESSON_SCOPES = ("project", "platform")

# Presencia: un agente que no da señales en 3 min está ocupado o pensando; en 15, se fue.
ONLINE = timedelta(minutes=3)
IDLE = timedelta(minutes=15)
HEARTBEAT_HINT_SECONDS = 120

# Carpetas del drive del proyecto.
SOURCE_ROOT = "fuente"   # lo que suben las personas: fases, imágenes, briefs
LIVE_ROOT = "live"       # donde escriben los agentes
PLAN_FILE = "kaanbal.hub.json"

# Límites de archivos: un ZIP de fases con imágenes ronda decenas de MB.
MAX_UPLOAD_BYTES = 120 * 1024 * 1024
MAX_EXTRACTED_BYTES = 400 * 1024 * 1024
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_ENTRIES = 3000
MAX_NOTE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 60_000
MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024
# Subida por partes: cada parte cabe holgada en un documento de Mongo y en una petición corta.
CHUNK_BYTES = 4 * 1024 * 1024
UPLOAD_TTL = timedelta(hours=24)
SKIPPED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".htm", ".css", ".js",
                   ".ts", ".tsx", ".jsx", ".vue", ".py", ".sql", ".xml", ".svg", ".env.example", ".toml"}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

_SLUG = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,99}$")
_AGENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,47}$")
_HEX_ID = re.compile(r"^[0-9a-f]{16}$")
_TASK_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class HubError(ValueError):
    """Una petición que el Hub no puede aceptar, explicada para quien la hizo."""


# ── Validación ───────────────────────────────────────────────────────────
def valid_group(value: str) -> bool:
    return bool(_SLUG.fullmatch(value or ""))


def valid_id(value: str) -> bool:
    return bool(_HEX_ID.fullmatch(value or ""))


def agent_name(value: Any) -> str:
    name = str(value or "").strip()
    if not _AGENT.fullmatch(name):
        raise HubError("El nombre del agente va de 1 a 48 caracteres: letras, números, espacio, punto o guion.")
    return name


def harness(value: Any) -> str:
    name = str(value or "").strip().lower()
    return name if name in HARNESSES else "otro"


def clean_text(value: Any, limit: int, *, required: bool = False, what: str = "El texto") -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if required and not text:
        raise HubError(f"{what} no puede ir vacío.")
    if len(text) > limit:
        raise HubError(f"{what} pasa de {limit} caracteres: resume o deja el detalle en un archivo de live/.")
    return text


def task_key(value: Any) -> Optional[str]:
    key = str(value or "").strip()
    if not key:
        return None
    if not _TASK_KEY.fullmatch(key):
        raise HubError(f"'{key}' no es una clave de tarea válida (p. ej. T01, W2-api).")
    return key


def normalize_path(value: Any) -> str:
    """Ruta relativa y limpia dentro del drive del proyecto, o HubError.

    Nada de rutas absolutas, unidades de Windows, `..` ni caracteres de control:
    los nombres vienen de ZIPs ajenos (zip-slip) y de agentes.
    """
    raw = unicodedata.normalize("NFC", str(value or "")).replace("\\", "/").strip()
    if not raw or _CONTROL.search(raw) or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise HubError(f"Ruta inválida: '{raw[:80]}'.")
    parts = [part.strip() for part in raw.split("/") if part.strip() not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise HubError(f"Ruta inválida: '{raw[:80]}'.")
    path = "/".join(parts)
    if len(path) > 400 or any(len(part) > 160 for part in parts):
        raise HubError("La ruta es demasiado larga.")
    return path


def is_live_path(path: str) -> bool:
    return path == LIVE_ROOT or path.startswith(LIVE_ROOT + "/")


def content_type(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".md"):
        return "text/markdown"
    guessed = mimetypes.guess_type(lowered)[0]
    if guessed:
        return guessed
    return "text/plain" if is_text(path) else "application/octet-stream"


def is_text(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in TEXT_EXTENSIONS)


def chunk_count(size: int) -> int:
    return max(1, -(-size // CHUNK_BYTES))


def chunk_length(size: int, index: int) -> int:
    """Lo que debe medir la parte `index` de un archivo de `size` bytes."""
    return min(CHUNK_BYTES, size - index * CHUNK_BYTES)


# ── Presencia ────────────────────────────────────────────────────────────
def presence(session: Mapping[str, Any], now: datetime) -> str:
    if session.get("left_at"):
        return "left"
    seen = session.get("last_seen") or session.get("started_at")
    if not isinstance(seen, datetime):
        return "offline"
    age = now - seen
    if age <= ONLINE:
        return "online"
    if age <= IDLE:
        return "idle"
    return "offline"


def public_session(session: Mapping[str, Any], now: datetime) -> Dict[str, Any]:
    return {
        "id": session["_id"], "agent": session.get("agent"), "harness": session.get("harness"),
        "model": session.get("model") or None, "person": session.get("person"),
        "specialty": session.get("specialty") or "", "focus": session.get("focus") or "",
        "task": session.get("task") or None, "branch": session.get("branch") or None,
        "presence": presence(session, now), "started_at": session.get("started_at"),
        "last_seen": session.get("last_seen"), "left_at": session.get("left_at"),
    }


# ── Tareas ───────────────────────────────────────────────────────────────
def task_label(task: Mapping[str, Any]) -> str:
    return f"{task.get('key') or task['_id']} · {task.get('title')}"


def pending_dependencies(task: Mapping[str, Any], tasks_by_ref: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Dependencias que todavía no están hechas, con quién las tiene.

    Una dependencia que no existe también bloquea: mejor preguntar que avanzar
    sobre un contrato que nadie escribió.
    """
    missing = []
    for ref in task.get("depends_on") or []:
        dep = tasks_by_ref.get(ref)
        if dep is None:
            missing.append({"ref": ref, "status": "missing", "holder": None, "title": None})
        elif dep.get("status") != "done":
            missing.append({"ref": ref, "status": dep.get("status"), "holder": dep.get("assignee_agent"),
                            "title": dep.get("title")})
    return missing


def index_tasks(tasks: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    index: Dict[str, Mapping[str, Any]] = {}
    for task in tasks:
        index[task["_id"]] = task
        if task.get("key"):
            index[task["key"]] = task
    return index


def claim_check(task: Mapping[str, Any], tasks_by_ref: Mapping[str, Mapping[str, Any]],
                session: Mapping[str, Any], holder_left: bool = False) -> Optional[Dict[str, Any]]:
    """None si la sesión puede tomar la tarea; si no, por qué y qué hacer mientras.

    `holder_left`: la sesión que la tenía ya cerró (hub_leave), así que la tarea está libre aunque
    conserve su nombre; si no, una sesión nueva del mismo agente no podría retomarla.
    """
    holder_session = task.get("assignee_session")
    if holder_session == session["_id"] and task.get("status") == "in_progress":
        return None
    if task.get("status") not in ("todo", "blocked"):
        holder = task.get("assignee_agent")
        return {"reason": f"La tarea está en '{task.get('status')}'" + (f" con {holder}" if holder else "") + ".",
                "pending": []}
    if holder_session and holder_session != session["_id"] and not holder_left:
        return {"reason": f"La tiene {task.get('assignee_agent') or 'otro agente'} (en '{task.get('status')}').",
                "pending": [], "hint": "Pídele con hub_message que la suelte (status todo) o toma otra tarea."}
    pending = pending_dependencies(task, tasks_by_ref)
    if pending:
        names = ", ".join(f"{item['ref']} ({item['status']}{', ' + item['holder'] if item['holder'] else ''})"
                          for item in pending)
        return {"reason": f"Depende de trabajo sin terminar: {names}.", "pending": pending,
                "hint": "Pide a quien la tiene que publique lo que necesitas (hub_message) o toma otra tarea "
                        "disponible mientras tanto."}
    return None


def available_tasks(tasks: List[Mapping[str, Any]], specialty: str = "") -> List[Mapping[str, Any]]:
    """Tareas libres con dependencias resueltas; primero las del área del agente."""
    index = index_tasks(tasks)
    free = [t for t in tasks if t.get("status") == "todo" and not pending_dependencies(t, index)]
    words = {w for w in re.split(r"[^a-záéíóúñ0-9]+", specialty.lower()) if len(w) > 2}

    def score(task: Mapping[str, Any]) -> Tuple[int, str]:
        area = str(task.get("area") or "").lower()
        hit = any(word in area or area in word for word in words) if area else False
        return (0 if hit else 1, str(task.get("key") or task.get("title")))

    return sorted(free, key=score)


def public_task(task: Mapping[str, Any], index: Mapping[str, Mapping[str, Any]] = None) -> Dict[str, Any]:
    data = {
        "id": task["_id"], "key": task.get("key"), "title": task.get("title"),
        "description": task.get("description") or "", "area": task.get("area") or "",
        "phase": task.get("phase") or "", "status": task.get("status"),
        "depends_on": task.get("depends_on") or [], "sources": task.get("sources") or [],
        "assignee_agent": task.get("assignee_agent"), "assignee_session": task.get("assignee_session"),
        "branch": task.get("branch"), "pr_url": task.get("pr_url"), "notes": task.get("notes") or [],
        "created_by": task.get("created_by"), "updated_at": task.get("updated_at"),
        "reviewed_by": task.get("reviewed_by"), "reviewed_at": task.get("reviewed_at"),
    }
    if index is not None:
        data["waiting_on"] = pending_dependencies(task, index)
    return data


# ── Traza ────────────────────────────────────────────────────────────────
def compact_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    return {"at": event.get("created_at"), "agent": event.get("agent"), "kind": event.get("kind"),
            "text": event.get("text"), "task": event.get("task_ref")}


def trace_tree(events: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Proyecto → día → agente, con cuántos eventos y los tipos que dejó cada uno."""
    days: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for event in events:
        at = event.get("created_at")
        day = at.strftime("%Y-%m-%d") if isinstance(at, datetime) else "sin-fecha"
        agent = event.get("agent") or event.get("person") or "persona"
        slot = days.setdefault(day, {}).setdefault(agent, {"agent": agent, "events": 0, "kinds": {},
                                                           "sessions": set(), "last": None})
        slot["events"] += 1
        kind = event.get("kind") or "note"
        slot["kinds"][kind] = slot["kinds"].get(kind, 0) + 1
        if event.get("session_id"):
            slot["sessions"].add(event["session_id"])
        if isinstance(at, datetime) and (slot["last"] is None or at > slot["last"]):
            slot["last"] = at
    tree = []
    for day in sorted(days, reverse=True):
        agents = [{**slot, "sessions": sorted(slot["sessions"])} for slot in days[day].values()]
        agents.sort(key=lambda item: item["last"] or datetime.min, reverse=True)
        tree.append({"day": day, "agents": agents, "events": sum(a["events"] for a in agents)})
    return tree


# ── Modo de trabajo ──────────────────────────────────────────────────────
# Guiado: los agentes proponen y esperan el visto bueno; una persona cierra cada tarea.
# Autónomo: dentro del objetivo toman, cierran y aceptan sus propias propuestas sin esperar a nadie,
# hasta que el objetivo se cumple. Fusionar a main (y por tanto desplegar) sigue siendo de personas.
WORK_MODES = ("guided", "autonomous")
DONE_BY = ("person", "peer", "self")
DEFAULT_SETTINGS: Dict[str, Any] = {"mode": "guided", "done_by": "person", "auto_accept": False,
                                    "objective": "", "scope_phases": [], "scope_tasks": []}

GUIDED_RULES = [
    "Modo GUIADO: propón a la persona qué tarea vas a tomar y espera su visto bueno antes de hub_claim_task.",
    "Al terminar márcala review con rama/PR: una persona la revisa y la cierra.",
]
AUTONOMOUS_RULES = [
    "Modo AUTÓNOMO: no pidas permiso para tomar tareas del objetivo; tómalas en orden de dependencias y avanza "
    "hasta cumplirlo.",
    "Las decisiones que son de personas: regístralas con hub_log kind=question, aplica la opción más conservadora "
    "y documentada, y sigue con otra tarea en vez de quedarte esperando.",
    "Nunca fusiones a main ni despliegues: abre un PR por tarea. Las personas fusionan.",
    "Cuando objective.complete sea true, deja de tomar tareas y cierra con hub_leave y un relevo.",
]
DONE_RULES = {
    "person": "Una persona cierra las tareas: tú las dejas en review.",
    "peer": "Revisión entre agentes: deja tu tarea en review y pide a otro agente (hub_message) que la revise; "
            "quien revisa la marca done. No cierres las tuyas.",
    "self": "Cierras tus tareas tú mismo (done) cuando cumplen su criterio y su PR está abierto con pruebas.",
}


def work_settings(raw: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """La configuración del proyecto con valores por defecto y saneada."""
    raw = raw or {}
    settings = {**DEFAULT_SETTINGS, **{k: raw[k] for k in DEFAULT_SETTINGS if k in raw}}
    if settings["mode"] not in WORK_MODES:
        settings["mode"] = "guided"
    if settings["done_by"] not in DONE_BY:
        settings["done_by"] = "person"
    settings["auto_accept"] = bool(settings["auto_accept"])
    settings["objective"] = str(settings["objective"] or "")[:500]
    settings["scope_phases"] = [str(p)[:40] for p in settings["scope_phases"] or []][:20]
    settings["scope_tasks"] = [k for k in (task_key(t) for t in settings["scope_tasks"] or []) if k][:100]
    if settings["mode"] == "guided":
        settings.update(done_by="person", auto_accept=False)
    return settings


def in_scope(task: Mapping[str, Any], settings: Mapping[str, Any]) -> bool:
    phases, keys = settings.get("scope_phases") or [], settings.get("scope_tasks") or []
    if not phases and not keys:
        return True
    return (task.get("phase") or "") in phases or (task.get("key") or "") in keys


def objective_progress(tasks: List[Mapping[str, Any]], settings: Mapping[str, Any]) -> Dict[str, Any]:
    scoped = [t for t in tasks if in_scope(t, settings) and t.get("status") not in ("dropped", "proposed")]
    done = sum(1 for t in scoped if t.get("status") == "done")
    index = index_tasks(tasks)
    external = {p["ref"]: p for t in scoped for p in pending_dependencies(t, index)
                if not in_scope(index.get(p["ref"], {}), settings) or p["status"] == "missing"}
    return {"text": settings.get("objective") or "", "phases": list(settings.get("scope_phases") or []),
            "tasks": list(settings.get("scope_tasks") or []), "done": done, "total": len(scoped),
            "ready": sum(t.get("status") == "todo" and not pending_dependencies(t, index) for t in scoped),
            "review": sum(t.get("status") == "review" for t in scoped),
            "external_dependencies": list(external.values()),
            "remaining": [task_label(t) for t in scoped if t.get("status") != "done"][:20],
            "complete": bool(scoped) and done == len(scoped)}


def work_rules(settings: Mapping[str, Any]) -> List[str]:
    base = AUTONOMOUS_RULES if settings.get("mode") == "autonomous" else GUIDED_RULES
    return base + [DONE_RULES[settings.get("done_by") or "person"]]


def done_check(task: Mapping[str, Any], session: Optional[Mapping[str, Any]],
               settings: Mapping[str, Any]) -> Optional[str]:
    """None si quien pide cerrar la tarea puede hacerlo; si no, qué hacer en su lugar.

    Una persona (sin sesión de agente) siempre puede: es quien integra.
    """
    if session is None:
        return None
    done_by = settings.get("done_by") or "person"
    if done_by == "person":
        return "En este proyecto una persona cierra las tareas: márcala review con su rama/PR."
    if done_by == "peer":
        if (task.get("assignee_session") == session.get("_id")
                or task.get("assignee_agent") == session.get("agent")):
            return "Revisión entre agentes: márcala review y pide a otro agente que la revise y la cierre."
        if task.get("status") != "review":
            return "Solo se cierra una tarea que está en review."
    if done_by == "self" and (task.get("assignee_session") != session.get("_id")
                              or task.get("status") not in ("in_progress", "review")):
        return "Toma la tarea con hub_claim_task antes de cerrarla. Solo puedes cerrar tus tareas."
    return None


def validate_dependencies(task: Mapping[str, Any], tasks: List[Mapping[str, Any]]) -> None:
    """Validate edits as well as imports; references may be a key or an id."""
    graph = [t for t in tasks if t["_id"] != task["_id"]] + [task]
    index = index_tasks(graph)
    visiting, visited = set(), set()

    def visit(item):
        ident = item["_id"]
        if ident in visiting:
            raise HubError("Las dependencias forman un ciclo. Revisa las tareas que deben terminar primero.")
        if ident in visited:
            return
        visiting.add(ident)
        for ref in item.get("depends_on") or []:
            if ref not in index:
                raise HubError(f"La dependencia {ref} no existe en este proyecto.")
            visit(index[ref])
        visiting.remove(ident)
        visited.add(ident)

    visit(task)


def coordination_state(project, tasks, sessions, now):
    """Authoritative current state, independent of manually authored board text."""
    index = index_tasks(tasks)
    counts = {s: sum(t.get("status") == s for t in tasks) for s in TASK_STATUSES}
    waiting = [t for t in tasks if t.get("status") in ("todo", "blocked")
               and pending_dependencies(t, index)]
    latest = max((t["updated_at"] for t in tasks if isinstance(t.get("updated_at"), datetime)), default=None)
    board_at = project.get("board_updated_at")
    return {"counts": counts, "ready": len(available_tasks(tasks)), "waiting": len(waiting),
            "blocked": len({t["_id"] for t in waiting} | {t["_id"] for t in tasks if t.get("status") == "blocked"}),
            "active": sum(presence(s, now) == "online" for s in sessions),
            "quiet": sum(presence(s, now) == "idle" for s in sessions),
            "board_stale": bool(project.get("board") and latest and (not board_at or latest > board_at)),
            "tasks_updated_at": latest, "as_of": now}


def compact_task(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Lo justo para el latido: el detalle está en hub_tasks."""
    return {"key": task.get("key"), "id": task["_id"], "title": task.get("title"), "status": task.get("status"),
            "assignee_agent": task.get("assignee_agent"), "pr_url": task.get("pr_url")}


# ── Briefing ─────────────────────────────────────────────────────────────
PROTOCOL = [
    "Preséntate con hub_join y guarda tu session_id: es tu identidad en este proyecto.",
    "Lee el tablero y los últimos relevos antes de tocar código; no leas todo el histórico.",
    "Toma una tarea con hub_claim_task antes de editar. Si depende de algo sin terminar, el Hub te dice quién lo "
    "tiene: pídeselo con hub_message o toma otra tarea disponible.",
    f"Llama a hub_sync cada ~{HEARTBEAT_HINT_SECONDS // 60} minutos o después de cada paso importante: deja latido, "
    "recibes mensajes y ves qué hicieron los demás.",
    "Registra decisiones, bloqueos y preguntas con hub_log (cortos, con archivos o PR si los hay).",
    "Respeta el ownership del área: no edites archivos de otra tarea en curso; si cruzas, pide contrato o PR.",
    "Los archivos de fuente/ son de las personas (solo lectura). Lo tuyo va en live/ con hub_write_note.",
    "Al terminar una tarea sigue la regla de cierre de este proyecto (arriba) y deja rama/PR; al irte usa "
    "hub_leave con un relevo que sirva al siguiente agente.",
    "Si aprendiste algo útil para otros proyectos, déjalo con hub_add_lesson (scope platform).",
]


def files_summary(files: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    folders: Dict[str, int] = {}
    total = 0
    size = 0
    plan = False
    for item in files:
        total += 1
        size += int(item.get("size") or 0)
        path = item.get("path") or ""
        parts = path.split("/")
        folder = "/".join(parts[:2]) if len(parts) > 2 else parts[0]
        folders[folder] = folders.get(folder, 0) + 1
        plan = plan or path.endswith(PLAN_FILE)
    return {"total": total, "bytes": size, "folders": dict(sorted(folders.items())), "has_plan": plan}


def briefing(project: Mapping[str, Any], *, sessions: List[Mapping[str, Any]], tasks: List[Mapping[str, Any]],
             events: List[Mapping[str, Any]], handoffs: List[Mapping[str, Any]], lessons: List[Mapping[str, Any]],
             files: List[Mapping[str, Any]], now: datetime, me: Optional[Mapping[str, Any]] = None,
             settings: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Lo mínimo que necesita un agente que llega: no el histórico, el estado."""
    settings = work_settings(settings)
    index = index_tasks(tasks)
    team = [public_session(s, now) for s in sessions if presence(s, now) in ("online", "idle")
            and (me is None or s["_id"] != me["_id"])]
    specialty = str((me or {}).get("specialty") or "")
    open_tasks = [t for t in tasks if t.get("status") in OPEN_STATUSES]
    in_progress = [public_task(t) for t in open_tasks if t.get("status") in ("in_progress", "review")]
    blocked = [public_task(t, index) for t in open_tasks
               if t.get("status") == "blocked" or (t.get("status") == "todo" and pending_dependencies(t, index))]
    # Con objetivo, solo se ofrece lo que está dentro: lo demás espera a otro objetivo.
    available = [public_task(t) for t in available_tasks(tasks, specialty)
                 if settings["mode"] != "autonomous" or in_scope(t, settings)][:8]
    done = sum(1 for t in tasks if t.get("status") == "done")
    alone = not team
    return {
        "project": {"group": project.get("_id"), "name": project.get("name") or project.get("_id"),
                    "description": project.get("description") or ""},
        "situation": ("Eres el primero en línea: organiza el trabajo, revisa la fuente y deja el tablero claro "
                      "para quien llegue.") if alone else
                     f"Hay {len(team)} agente(s) trabajando: coordina con ellos antes de tomar algo que cruce su área.",
        "board": project.get("board") or "",
        "coordination": coordination_state(project, tasks, sessions, now),
        "board_notice": "El tablero es contexto manual. Para el estado actual usa coordination y tasks.",
        "team": team,
        "progress": {"done": done, "open": len(open_tasks), "total": len(tasks)},
        "work_mode": {"mode": settings["mode"], "done_by": settings["done_by"], "auto_accept": settings["auto_accept"]},
        "objective": objective_progress(tasks, settings),
        "tasks": {"available_for_you": available, "in_progress": in_progress, "blocked": blocked},
        "recent": [compact_event(e) for e in events[:15]],
        "last_handoffs": [{"agent": h.get("agent"), "at": h.get("created_at"), "text": h.get("text")}
                          for h in handoffs[:3]],
        "lessons": [{"scope": item.get("scope"), "text": item.get("text"), "by": item.get("agent")}
                    for item in lessons[:10]],
        "files": files_summary(files),
        "protocol": work_rules(settings) + PROTOCOL,
        "heartbeat_seconds": HEARTBEAT_HINT_SECONDS,
    }


# ── Secretario ───────────────────────────────────────────────────────────
STALE = timedelta(hours=6)


def digest_signals(*, sessions: List[Mapping[str, Any]], tasks: List[Mapping[str, Any]],
                   events: List[Mapping[str, Any]], now: datetime) -> Dict[str, Any]:
    """Lo que un secretario atento notaría, sin IA: cifras y alertas concretas."""
    by_session = {s["_id"]: s for s in sessions}
    alerts: List[Dict[str, Any]] = []
    for task in tasks:
        status = task.get("status")
        if status == "in_progress":
            holder = by_session.get(task.get("assignee_session") or "")
            if holder is None or presence(holder, now) in ("offline", "left"):
                alerts.append({"kind": "orphan", "task": task_label(task),
                               "text": f"{task_label(task)} sigue en curso pero {task.get('assignee_agent') or 'nadie'} "
                                       "ya no está en línea. Libérala o pide el relevo."})
            elif isinstance(task.get("updated_at"), datetime) and now - task["updated_at"] > STALE:
                alerts.append({"kind": "stale", "task": task_label(task),
                               "text": f"{task_label(task)} lleva más de 6 h sin novedades."})
        if status == "blocked":
            alerts.append({"kind": "blocked", "task": task_label(task),
                           "text": f"{task_label(task)} está bloqueada."})
        if status == "review":
            alerts.append({"kind": "review", "task": task_label(task),
                           "text": f"{task_label(task)} espera revisión" + (f" ({task['pr_url']})" if task.get("pr_url") else "") + "."})
        if status == "proposed":
            alerts.append({"kind": "proposed", "task": task_label(task),
                           "text": f"{task_label(task)} es una propuesta: una persona la acepta o la descarta."})
    ready = [task_label(t) for t in available_tasks(tasks)]
    since = now - timedelta(hours=24)
    recent = [e for e in events if isinstance(e.get("created_at"), datetime) and e["created_at"] >= since]
    questions = [compact_event(e) for e in recent if e.get("kind") == "question"]
    blockers = [compact_event(e) for e in recent if e.get("kind") == "blocker"]
    online = [public_session(s, now) for s in sessions if presence(s, now) == "online"]
    counts: Dict[str, int] = {}
    for task in tasks:
        counts[task.get("status") or "todo"] = counts.get(task.get("status") or "todo", 0) + 1
    phases: Dict[str, Dict[str, int]] = {}
    for task in tasks:
        if task.get("status") in ("dropped", "proposed"):
            continue
        phase = task.get("phase") or "sin fase"
        slot = phases.setdefault(phase, {"done": 0, "total": 0})
        slot["total"] += 1
        slot["done"] += 1 if task.get("status") == "done" else 0
    return {"online": online, "task_counts": counts, "phases": phases, "alerts": alerts,
            "ready_to_start": ready[:10], "open_questions": questions[:10], "recent_blockers": blockers[:10],
            "events_24h": len(recent)}


def digest_prompt(project: Mapping[str, Any], signals: Mapping[str, Any], events: List[Mapping[str, Any]]) -> str:
    compact = [compact_event(e) for e in events[:60]]
    return (
        "Eres el secretario de un equipo de agentes de código que trabajan juntos en un proyecto. No programas ni "
        "decides: informas a las personas qué está pasando, qué problemas aparecieron y qué tareas convendría "
        "agregar. Sé breve, concreto y en español.\n\n"
        f"Proyecto: {project.get('name') or project.get('_id')}\n"
        f"Tablero (extracto):\n{str(project.get('board') or '')[:3000]}\n\n"
        f"Señales:\n{json.dumps(signals, ensure_ascii=False, default=str)[:6000]}\n\n"
        f"Últimos eventos:\n{json.dumps(compact, ensure_ascii=False, default=str)[:8000]}\n\n"
        'Responde SOLO JSON: {"summary": "3-5 frases", "risks": ["..."], '
        '"suggested_tasks": [{"title": "...", "area": "frontend|backend|diseño|integración|qa|otro", '
        '"why": "..."}], "for_people": ["lo que una persona debe decidir o probar"]}'
    )


def parse_digest(answer: Any) -> Dict[str, Any]:
    """La respuesta de la IA, saneada: si no tiene forma, se ignora y queda el resumen determinista."""
    if not isinstance(answer, dict) or answer.get("error"):
        return {}
    suggestions = []
    for item in answer.get("suggested_tasks") or []:
        if isinstance(item, dict) and str(item.get("title") or "").strip():
            suggestions.append({"title": str(item["title"]).strip()[:160], "area": str(item.get("area") or "")[:40],
                                "why": str(item.get("why") or "")[:400]})
    return {
        "summary": str(answer.get("summary") or answer.get("response") or "")[:2000],
        "risks": [str(r)[:300] for r in (answer.get("risks") or []) if r][:8],
        "suggested_tasks": suggestions[:6],
        "for_people": [str(r)[:300] for r in (answer.get("for_people") or []) if r][:6],
    }


# ── ZIP de fases ─────────────────────────────────────────────────────────
def _skip(name: str) -> bool:
    parts = name.split("/")
    return any(p.lower() in SKIPPED_NAMES or p == "__MACOSX" or p.startswith("._") for p in parts)


def extract_zip(data: bytes, dest: str, *, nested: bool = True) -> List[Tuple[str, bytes]]:
    """Archivos de un ZIP como (ruta, bytes) bajo `dest`, sin escapar de él.

    Los ZIP de fases suelen traer otros ZIP adentro (una fase por archivo): se abren
    un nivel, en una carpeta con su nombre, y el ZIP interno no se guarda para no
    duplicar. Límites de tamaño y cantidad frenan bombas de compresión.
    """
    dest = normalize_path(dest)
    out: List[Tuple[str, bytes]] = []
    budget = [MAX_EXTRACTED_BYTES]

    def walk(blob: bytes, base: str, depth: int) -> None:
        try:
            archive = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile as exc:
            raise HubError("El archivo no es un ZIP válido.") from exc
        with archive:
            for info in archive.infolist():
                if info.is_dir() or _skip(info.filename):
                    continue
                if len(out) >= MAX_ENTRIES:
                    raise HubError(f"El ZIP tiene más de {MAX_ENTRIES} archivos.")
                if info.file_size > MAX_FILE_BYTES:
                    raise HubError(f"'{info.filename}' pasa de {MAX_FILE_BYTES // (1024 * 1024)} MB.")
                if info.flag_bits & 0x1:
                    raise HubError("El ZIP está cifrado: súbelo sin contraseña.")
                path = normalize_path(f"{base}/{info.filename}")
                budget[0] -= info.file_size
                if budget[0] < 0:
                    raise HubError(f"El contenido descomprimido pasa de {MAX_EXTRACTED_BYTES // (1024 * 1024)} MB.")
                content = archive.read(info)
                if len(content) != info.file_size:
                    raise HubError(f"'{info.filename}' no coincide con el tamaño declarado.")
                if nested and depth == 0 and path.lower().endswith(".zip"):
                    walk(content, path[:-4], depth + 1)
                    continue
                out.append((path, content))

    walk(data, dest, 0)
    return out


# ── Plan (kaanbal.hub.json) ──────────────────────────────────────────────
def parse_plan(raw: Any) -> Dict[str, Any]:
    """El plan de trabajo que acompaña a las fases: tablero y tareas con dependencias.

    Formato (version 1):
    {"version": 1, "board": "markdown", "tasks": [{"key": "T01", "title": "...", "area": "backend",
      "phase": "W0", "depends_on": ["T00"], "description": "...", "sources": ["fuente/..."]}]}
    """
    if isinstance(raw, (bytes, str)):
        try:
            raw = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HubError(f"{PLAN_FILE} no es JSON válido: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise HubError(f"{PLAN_FILE} necesita \"version\": 1.")
    items = raw.get("tasks") or []
    if not isinstance(items, list) or len(items) > 300:
        raise HubError("tasks debe ser una lista de hasta 300 tareas.")
    tasks = []
    keys = set()
    for item in items:
        if not isinstance(item, dict):
            raise HubError("Cada tarea es un objeto.")
        key = task_key(item.get("key"))
        if not key:
            raise HubError("Cada tarea del plan necesita key (T01, W2-api…).")
        if key in keys:
            raise HubError(f"La clave {key} se repite.")
        keys.add(key)
        tasks.append({
            "key": key,
            "title": clean_text(item.get("title"), 160, required=True, what=f"El título de {key}"),
            "description": clean_text(item.get("description"), 4000, what=f"La descripción de {key}"),
            "area": clean_text(item.get("area"), 40),
            "phase": clean_text(item.get("phase"), 40),
            "depends_on": [k for k in (task_key(d) for d in (item.get("depends_on") or [])) if k],
            "sources": [normalize_path(s) for s in (item.get("sources") or [])][:20],
        })
    for task in tasks:
        unknown = [d for d in task["depends_on"] if d not in keys]
        if unknown:
            raise HubError(f"{task['key']} depende de claves que no están en el plan: {', '.join(unknown)}.")
    _reject_cycles(tasks)
    return {"board": clean_text(raw.get("board"), 20_000), "tasks": tasks}


def _reject_cycles(tasks: List[Mapping[str, Any]]) -> None:
    graph = {t["key"]: list(t["depends_on"]) for t in tasks}
    state: Dict[str, int] = {}

    def visit(key: str, trail: List[str]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise HubError("El plan tiene dependencias circulares: " + " → ".join(trail + [key]) + ".")
        state[key] = 1
        for dep in graph.get(key, []):
            visit(dep, trail + [key])
        state[key] = 2

    for key in graph:
        visit(key, [])


def find_plan(paths: Iterable[str]) -> Optional[str]:
    """El kaanbal.hub.json menos profundo del drive (el de la fase de coordinación)."""
    candidates = [p for p in paths if posixpath.basename(p) == PLAN_FILE]
    return min(candidates, key=lambda p: (p.count("/"), p)) if candidates else None
