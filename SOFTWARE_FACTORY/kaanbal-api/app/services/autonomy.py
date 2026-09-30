"""Governed operations and ephemeral source workspaces.

Audit intent is persisted before effects. Authorization is repeated on every
request; a stored workspace is not an independent bearer capability.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.db import get_db
from app.services import autonomy_cluster as cluster
from app.services.autonomy_github import GitHubBroker, repository, validate_changes, contains_credential
from app.services.autonomy_policy import AutonomyError, authorize, digest, redact, require_elevated, require_permission, resource_name, node_name, safe_path

FILE_PROTOCOL = Path(__file__).with_name("autonomy_workspace_files.py").read_text(encoding="utf-8")


async def configuration():
    return await get_db().system_config.find_one({"_id": "main"}) or {}


def broker(config):
    return GitHubBroker(config.get("github_token") or config.get("git_token") or "")


def image(policy):
    value = policy.get("workbench_image", "")
    if not value or ":" not in value or value.endswith(":latest"):
        raise AutonomyError("Configura workbench_image con una versión o digest del ejecutor construido por el owner.")
    return value


def public_workspace(ws):
    result = {k: ws.get(k) for k in ("id", "target", "app", "env", "repo", "push_repo", "base_sha", "base_branch", "branch", "state", "expires_at", "pull_request", "published_sha")}
    if isinstance(result.get("expires_at"), datetime):
        result["expires_at"] = result["expires_at"].isoformat() + "Z"
    return result


async def init_indexes():
    db = get_db()
    for collection in ("autonomy_operations", "token_activity"):
        await db[collection].create_index("timestamp", expireAfterSeconds=90 * 86400)
        await db[collection].create_index([("credential_id", 1), ("timestamp", -1)])
    await db["autonomy_workspaces"].create_index("expires_at")


@asynccontextmanager
async def audit(principal, action, target, reason, **metadata):
    op = {"_id": uuid4().hex, "actor": principal.username, "credential_id": principal.token_id,
          "action": action, "target": target, "reason": redact(reason), "metadata": metadata,
          "state": "started", "timestamp": datetime.utcnow()}
    await get_db()["autonomy_operations"].insert_one(op)
    try:
        yield op
    except BaseException:
        await get_db()["autonomy_operations"].update_one({"_id": op["_id"]}, {"$set": {"state": "unknown" if op.get("state") == "unknown" else "failed", "finished_at": datetime.utcnow()}})
        raise
    else:
        await get_db()["autonomy_operations"].update_one({"_id": op["_id"]}, {"$set": {"state": op.get("state", "completed") if op.get("state") != "started" else "completed", "job": op.get("job"), "finished_at": datetime.utcnow()}})
        if principal.token_id:
            await get_db()["token_activity"].insert_one({"credential_id": principal.token_id, "actor": principal.username,
                "timestamp": datetime.utcnow(), "action": action, "target": target, "operation_id": op["_id"],
                "command_sha256": metadata.get("command_sha256"), "status": "completed" if op.get("state") == "started" else op.get("state")})


async def registered_app(name, env):
    resource_name(name)
    resource_name(env)
    app = await get_db().apps.find_one({"name": name})
    if not app or env not in (app.get("environments") or ["prod"]):
        raise AutonomyError("App o ambiente no registrado.", 404)
    # Core components require the separate host capability, never an app alias.
    if name.startswith("kaanbal-") or name in {"vault", "argocd", "datastore", "tailscale-operator"}:
        raise AutonomyError("Los componentes de plataforma no se ejecutan como apps de usuario.", 403)
    return app


async def execute_app(principal, name, env, command, seconds, reason):
    require_permission(principal, "autonomy.apps.execute")
    require_elevated(principal)
    cfg = await configuration()
    authorize(cfg.get("autonomy", {}), principal, feature="runtime", app=name, env=env)
    await registered_app(name, env)
    async with audit(principal, "app.execute", name, reason, env=env, command_sha256=digest(command)) as op:
        try:
            result = await asyncio.to_thread(cluster.app_execute, name, env, command, seconds)
        except Exception:
            op["state"] = "unknown"
            raise AutonomyError(f"Resultado incierto de la operación {op['_id']}. Comprueba la app antes de repetir el comando.", 502)
        op["state"] = "succeeded" if result["exit_code"] == 0 else "timed_out" if result["timed_out"] else "failed"
        result["output"] = redact(result["output"], [cfg.get("github_token"), cfg.get("git_token")])
        return {"operation_id": op["_id"], **result}


async def execute_host(principal, node, command, seconds, reason):
    require_permission(principal, "autonomy.host.execute")
    require_elevated(principal)
    cfg = await configuration()
    policy = cfg.get("autonomy", {})
    authorize(policy, principal, feature="host", node=node)
    node_name(node)
    async with audit(principal, "host.execute", node, reason, command_sha256=digest(command)) as op:
        op["job"] = "repair-" + op["_id"][:24]
        # Persist the deterministic job name before launch, including ambiguous network failures.
        await get_db()["autonomy_operations"].update_one({"_id": op["_id"]}, {"$set": {"job": op["job"]}})
        try:
            await asyncio.to_thread(cluster.start_host, op["job"], image(policy), node, command, seconds)
        except Exception:
            op["state"] = "unknown"
            raise AutonomyError(f"Lanzamiento incierto. Consulta get_operation con {op['_id']} antes de repetir el comando.", 502)
        op["state"] = "running"
        return {"operation_id": op["_id"], "state": "running"}


async def operation(principal, identifier):
    op = await get_db()["autonomy_operations"].find_one({"_id": identifier, "actor": principal.username, "credential_id": principal.token_id})
    if not op:
        raise AutonomyError("Operación no encontrada para esta sesión/token.", 404)
    result = {k: op.get(k) for k in ("action", "target", "state", "timestamp", "reason")}
    if isinstance(result.get("timestamp"), datetime):
        result["timestamp"] = result["timestamp"].isoformat() + "Z"
    if op["action"] == "host.execute" and op.get("job"):
        require_permission(principal, "autonomy.host.execute")
        require_elevated(principal)
        cfg = await configuration()
        authorize(cfg.get("autonomy", {}), principal, feature="host", node=op["target"])
        status = await asyncio.to_thread(cluster.host_status, op["job"])
        status["output"] = redact(status["output"], [cfg.get("github_token"), cfg.get("git_token")])
        result.update(status)
    return {"id": identifier, **result}


async def open_workspace(principal, *, target, app, env, reason):
    require_permission(principal, "autonomy.workspaces.manage")
    if target == "core":
        require_permission(principal, "autonomy.core.contribute")
    cfg = await configuration()
    policy = cfg.get("autonomy", {})
    authorize(policy, principal, feature="workspace", app=app if target == "app" else "", env=env, core=target == "core")
    if target == "app":
        record = await registered_app(app, env)
        repo = repository(record.get("repo_url"))
        from app.services.core_release import get_upstream
        if repo.lower() == "/".join(await get_upstream(cfg)).lower():
            raise AutonomyError("El repositorio de Kaanbal se modifica mediante una contribución al core.", 403)
    else:
        from app.services.core_release import get_upstream
        repo = "/".join(await get_upstream(cfg))
    github = broker(cfg)
    base = await github.base(repo)
    push_repo = await github.contribution_target(repo, policy.get("core_fork", "") if target == "core" else "")
    identifier = uuid4().hex
    lifetime = policy.get("workspace_lifetime_seconds", 3600)
    ws = {"_id": identifier, "id": identifier, "actor": principal.username, "credential_id": principal.token_id,
          "target": target, "app": app if target == "app" else "", "env": env, "repo": repo,
          "push_repo": push_repo, **base, "branch": f"codex/kaanbal-{identifier[:16]}",
          "pod": f"work-{identifier}", "state": "pending", "expires_at": datetime.utcnow() + timedelta(seconds=lifetime)}
    async with audit(principal, "workspace.create", repo, reason):
        await get_db()["autonomy_workspaces"].insert_one(ws)
        try:
            await asyncio.to_thread(cluster.create_workspace, ws["pod"], image(policy), lifetime)
        except Exception:
            await get_db()["autonomy_workspaces"].update_one({"_id": identifier}, {"$set": {"state": "failed"}})
            raise
    return public_workspace(ws)


async def workspace(principal, identifier, *, live=True):
    ws = await get_db()["autonomy_workspaces"].find_one({"_id": identifier, "actor": principal.username, "credential_id": principal.token_id})
    if not ws:
        raise AutonomyError("Workspace no encontrado para esta sesión/token.", 404)
    require_permission(principal, "autonomy.workspaces.manage")
    if ws["target"] == "core":
        require_permission(principal, "autonomy.core.contribute")
    cfg = await configuration()
    authorize(cfg.get("autonomy", {}), principal, feature="workspace", app=ws["app"], env=ws["env"], core=ws["target"] == "core")
    if live and (ws["expires_at"] <= datetime.utcnow() or ws["state"] in {"closed", "expired", "failed"}):
        raise AutonomyError("El workspace expiró o fue cerrado. Crea otro.", 410)
    return ws, cfg


@asynccontextmanager
async def locked(ws):
    lease = uuid4().hex
    doc = await get_db()["autonomy_workspaces"].find_one_and_update({"_id": ws["id"],
        "$or": [{"busy_until": {"$exists": False}}, {"busy_until": {"$lt": datetime.utcnow()}}]},
        {"$set": {"busy_until": datetime.utcnow() + timedelta(minutes=10), "lease": lease}}, return_document=True)
    if not doc:
        raise AutonomyError("El workspace tiene otra operación en curso.")
    ws.update(doc)  # re-read state under the lease; another request may have published meanwhile
    try:
        yield
    finally:
        await get_db()["autonomy_workspaces"].update_one({"_id": ws["id"], "lease": lease}, {"$unset": {"busy_until": "", "lease": ""}})


async def initialize(principal, identifier):
    ws, cfg = await workspace(principal, identifier)
    async with locked(ws):
        if ws.get("baseline"):
            return public_workspace(ws)
        if ws["state"] != "pending" or await asyncio.to_thread(cluster.workspace_phase, ws["pod"]) != "Running":
            raise AutonomyError("El contenedor todavía no está listo; consulta su estado y reintenta.")
        async with audit(principal, "workspace.initialize", identifier, "Preparar código fuente"):
            archive = await broker(cfg).archive(ws["repo"], ws["base_sha"])
            try:
                result = await asyncio.to_thread(cluster.workspace_python, ws["pod"], FILE_PROTOCOL, {"action": "initialize", "archive": base64.b64encode(archive).decode()})
            except Exception:
                await get_db()["autonomy_workspaces"].update_one({"_id": identifier}, {"$set": {"state": "failed"}})
                await asyncio.to_thread(cluster.remove_workspace, ws["pod"])
                raise
            ws.update(state="ready", baseline=result["baseline"])
            await get_db()["autonomy_workspaces"].update_one({"_id": identifier}, {"$set": {"state": "ready", "baseline": ws["baseline"]}})
    return public_workspace(ws)


def ready(ws, *, mutable=False):
    if ws["state"] not in {"ready", "published"}:
        raise AutonomyError("Inicializa el workspace antes de usar archivos o comandos.")
    if mutable and ws.get("published_sha"):
        raise AutonomyError("Este workspace ya preparó un PR. Crea otro para cambios adicionales.")


async def files(principal, identifier, *, path=None, content=None, write=False):
    ws, cfg = await workspace(principal, identifier)
    ready(ws, mutable=write)
    if path:
        safe_path(path)
    payload = {"action": "write" if write else "read" if path else "list", "path": path, "content": content}
    if write and content is not None and contains_credential(content, [cfg.get("github_token"), cfg.get("git_token")]):
        raise AutonomyError("Posible credencial en el contenido; retírala antes de guardar.", 422)
    async with locked(ws):
        ready(ws, mutable=write)
        async with audit(principal, "workspace.file.write" if write else "workspace.file.read", identifier, "Editar archivo" if write else "Consultar código", path=path):
            return await asyncio.to_thread(cluster.workspace_python, ws["pod"], FILE_PROTOCOL, payload)


async def changes(ws, cfg):
    result = await asyncio.to_thread(cluster.workspace_python, ws["pod"], FILE_PROTOCOL, {"action": "snapshot", "baseline": ws["baseline"]})
    items = result["changes"]
    if items:
        items = validate_changes(items, secrets=[cfg.get("github_token"), cfg.get("git_token")])
    return items


async def diff(principal, identifier):
    ws, cfg = await workspace(principal, identifier)
    ready(ws)
    async with locked(ws):
        ready(ws)
        items = await changes(ws, cfg)
        return {"changes": items, "digest": digest(items), "base_sha": ws["base_sha"]}


async def run_workspace(principal, identifier, command, seconds, reason):
    ws, _ = await workspace(principal, identifier)
    ready(ws, mutable=True)
    async with locked(ws):
        ready(ws, mutable=True)
        async with audit(principal, "workspace.execute", identifier, reason, command_sha256=digest(command)) as op:
            result = await asyncio.to_thread(cluster.execute, cluster.WORKSPACE_NAMESPACE, ws["pod"],
                cluster.shell_command("cd /workspace/repo && " + command, seconds), container="workbench", seconds=seconds)
            result["output"] = redact(result["output"])
            op["state"] = "succeeded" if result["exit_code"] == 0 else "timed_out" if result["timed_out"] else "failed"
            return {"operation_id": op["_id"], **result}


async def publish(principal, identifier, title, body, expected_digest):
    require_permission(principal, "autonomy.changes.propose")
    ws, cfg = await workspace(principal, identifier)
    ready(ws)
    if contains_credential(title + body, [cfg.get("github_token"), cfg.get("git_token")]):
        raise AutonomyError("Posible credencial en el título o descripción del PR.", 422)
    async with locked(ws):
        ready(ws)
        if ws.get("pull_request"):
            return public_workspace(ws)
        github = broker(cfg)
        if not ws.get("published_sha"):
            items = await changes(ws, cfg)
            if not items or digest(items) != expected_digest:
                raise AutonomyError("Los archivos cambiaron o están vacíos. Lee el diff y usa su digest antes de publicar.")
            validate_changes(items, secrets=[github.token])
            async with audit(principal, "workspace.commit", identifier, title, change_digest=expected_digest):
                ws["published_sha"] = await github.commit(ws, items, title)
                await get_db()["autonomy_workspaces"].update_one({"_id": identifier}, {"$set": {"published_sha": ws["published_sha"]}})
        async with audit(principal, "workspace.pull_request", identifier, title):
            pr = await github.publish(ws, ws["published_sha"], title, body)
            ws.update(pull_request=pr, state="published")
            await get_db()["autonomy_workspaces"].update_one({"_id": identifier}, {"$set": {"pull_request": pr, "state": "published"}})
        return public_workspace(ws)


async def merge(principal, identifier, expected_sha):
    require_permission(principal, "autonomy.changes.merge")
    require_elevated(principal)
    ws, cfg = await workspace(principal, identifier, live=False)
    authorize(cfg.get("autonomy", {}), principal, feature="merge", app=ws["app"], env=ws["env"])
    if not ws.get("pull_request"):
        raise AutonomyError("El workspace todavía no tiene PR.")
    async with locked(ws):
        async with audit(principal, "workspace.merge", identifier, "Integrar PR de app", expected_sha=expected_sha):
            return await broker(cfg).merge(ws, expected_sha)


async def close(principal, identifier):
    ws, _ = await workspace(principal, identifier, live=False)
    async with locked(ws):
        async with audit(principal, "workspace.close", identifier, "Cerrar contenedor temporal"):
            await asyncio.to_thread(cluster.remove_workspace, ws["pod"])
            await get_db()["autonomy_workspaces"].update_one({"_id": identifier}, {"$set": {"state": "closed"}})
    return {"id": identifier, "state": "closed"}


async def cleanup_loop():
    import logging
    while True:
        try:
            rows = await get_db()["autonomy_workspaces"].find({"expires_at": {"$lt": datetime.utcnow()}, "state": {"$nin": ["expired", "closed"]}}).to_list(100)
            for ws in rows:
                await asyncio.to_thread(cluster.remove_workspace, ws["pod"])
                await get_db()["autonomy_workspaces"].update_one({"_id": ws["id"]}, {"$set": {"state": "expired"}})
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).warning("No se pudieron recoger workspaces expirados")
        await asyncio.sleep(60)
