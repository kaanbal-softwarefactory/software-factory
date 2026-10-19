"""
Operación avanzada de apps: versiones, rollback, datos y secretos pedidos
========================================================================

Endpoints que usan la consola y el MCP para operar una app ya desplegada sin
salirse de GitOps ni ver secretos:

- versiones que corrieron, reinicio, rollback y promoción entre ambientes;
- consumo de CPU y memoria, y si la URL pública responde (con su certificado);
- respaldos, restauración y consultas de solo lectura de las bases;
- variables secretas que un agente pide y una persona captura.

Rollback, promoción y restauración siguen el patrón de planes (dry_run →
plan_id). Restaurar, además, pide aprobación humana cuando llega con un token.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.db import get_db
from app.models import User
from app.routers.auth import get_current_active_user
from app.services import agent_requests, app_operations, data_operations, plans
from app.services.activity_log import activity_log, CATEGORY_APP

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])
requests_router = APIRouter(dependencies=[Depends(get_current_active_user)])


async def _app(name: str, env: Optional[str] = None) -> Dict[str, Any]:
    app = await get_db().apps.find_one({"name": name})
    if not app:
        raise HTTPException(404, "App not found")
    if env is not None and env not in (app.get("environments") or ["prod"]):
        raise HTTPException(404, f"{name} no tiene ambiente '{env}'")
    return app


def _plan_error(exc: Exception) -> HTTPException:
    return HTTPException(409, str(exc))


# ── Versiones ────────────────────────────────────────────────────────────
@router.get("/{app_name}/revisions")
async def list_revisions(app_name: str, env: str = "prod"):
    """Las imágenes que corrieron en un ambiente, la declarada en GitOps y cuál sirve hoy."""
    await _app(app_name, env)
    try:
        revisions = await asyncio.to_thread(app_operations.collect_revisions, app_name, env)
    except Exception as exc:
        logger.warning("No se pudieron leer las versiones de %s/%s: %s", app_name, env, exc)
        raise HTTPException(502, "No se pudo leer el clúster")
    try:
        current = (await app_operations.gitops_tags(app_name, [env])).get(env)
    except Exception:
        current = None
    rows = app_operations.revisions_view(revisions, current)
    return {"app": app_name, "env": env, "declared_tag": current, "revisions": rows}


@router.post("/{app_name}/environments/{env}/restart")
async def restart_environment(app_name: str, env: str, current_user: User = Depends(get_current_active_user)):
    """Reinicia los pods de a uno (como `kubectl rollout restart`). No cambia nada de GitOps."""
    await _app(app_name, env)
    try:
        result = await asyncio.to_thread(app_operations.restart, app_name, env)
    except app_operations.OperationError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        logger.warning("No se pudo reiniciar %s/%s: %s", app_name, env, exc)
        raise HTTPException(502, "No se pudo reiniciar la app en el clúster")
    await activity_log.log("app.env.restarted", category=CATEGORY_APP, actor=current_user.username,
                           target=app_name, detail={"env": env})
    return {**result, "message": "Reiniciando: los pods se reemplazan de a uno. Sigue el avance con deploy_status."}


@router.post("/{app_name}/environments/{env}/rollback")
async def rollback_environment(app_name: str, env: str, body: dict, dry_run: bool = False,
                               plan_id: Optional[str] = None, current_user: User = Depends(get_current_active_user)):
    """Vuelve a una imagen que ya corrió en ese ambiente, escribiendo su tag en GitOps."""
    await _app(app_name, env)
    target = str((body or {}).get("tag") or "")
    try:
        current = (await app_operations.gitops_tags(app_name, [env])).get(env)
        known = app_operations.revisions_view(
            await asyncio.to_thread(app_operations.collect_revisions, app_name, env), current)
        plan = app_operations.rollback_plan(app_name, env, current, target, known)
        if dry_run:
            return JSONResponse(plans.dry_run_answer("rollback", plan))
        plans.verify("rollback", plan, plan_id)
        await app_operations.gitops_tags(app_name, [env], write={env: target},
                                         message=f"chore({app_name}): rollback {env} a {target}")
    except (app_operations.OperationError, plans.PlanMismatch) as exc:
        raise _plan_error(exc)
    await activity_log.log("app.release.rollback", category=CATEGORY_APP, actor=current_user.username,
                           target=app_name, detail={"env": env, "from": plan["from_tag"], "to": target})
    return {"applied": True, **plan,
            "message": "GitOps actualizado: ArgoCD despliega la versión anterior en unos minutos."}


@router.post("/{app_name}/promote")
async def promote(app_name: str, body: dict, dry_run: bool = False, plan_id: Optional[str] = None,
                  current_user: User = Depends(get_current_active_user)):
    """Lleva a un ambiente la imagen que corre en otro (staging → prod)."""
    app = await _app(app_name)
    source, target = str((body or {}).get("from_env") or "staging"), str((body or {}).get("to_env") or "prod")
    try:
        if source not in (app.get("environments") or []) or target not in (app.get("environments") or []):
            raise app_operations.OperationError(f"{app_name} no tiene ambos ambientes ({source}, {target}).")
        tags = await app_operations.gitops_tags(app_name, [source, target])
        plan = app_operations.promote_plan(app, source, target, tags.get(source), tags.get(target))
        if dry_run:
            return JSONResponse(plans.dry_run_answer("promote", plan))
        plans.verify("promote", plan, plan_id)
        await app_operations.gitops_tags(app_name, [target], write={target: plan["to_tag"]},
                                         message=f"chore({app_name}): promover {plan['to_tag']} de {source} a {target}")
    except (app_operations.OperationError, plans.PlanMismatch) as exc:
        raise _plan_error(exc)
    await activity_log.log("app.release.promoted", category=CATEGORY_APP, actor=current_user.username,
                           target=app_name, detail={"from_env": source, "to_env": target, "tag": plan["to_tag"]})
    return {"applied": True, **plan, "message": f"GitOps actualizado: ArgoCD despliega {plan['to_tag']} en {target}."}


# ── Consumo y disponibilidad ─────────────────────────────────────────────
@router.get("/{app_name}/metrics")
async def app_metrics(app_name: str, env: str = "prod"):
    await _app(app_name, env)
    try:
        return {"app": app_name, "env": env, **await asyncio.to_thread(app_operations.collect_metrics, app_name, env)}
    except Exception as exc:
        logger.warning("No se pudo leer el consumo de %s/%s: %s", app_name, env, exc)
        raise HTTPException(502, "No se pudo leer el clúster")


@router.get("/{app_name}/probe")
async def probe_urls(app_name: str):
    """Prueba desde la plataforma las URLs que la app tiene asignadas (y solo esas)."""
    from app.services import domain_service, url_probe

    app = await _app(app_name)
    urls = domain_service.describe_app_domain(app, await domain_service.domains_index()).get("urls") or {}
    if not urls:
        return {"app": app_name, "results": {}, "message": "La app no tiene URLs públicas (es interna o por VPN)."}
    results = await asyncio.gather(*(url_probe.probe(url) for url in urls.values()))
    return {"app": app_name, "results": dict(zip(urls.keys(), results))}


# ── Datos ────────────────────────────────────────────────────────────────
def _database(app: Dict[str, Any]) -> str:
    try:
        return data_operations.engine_of(app)
    except data_operations.DataError as exc:
        raise HTTPException(400, str(exc))


@router.get("/{app_name}/backups")
async def list_backups(app_name: str):
    app = await _app(app_name)
    _database(app)
    return {"app": app_name, "operations": await data_operations.listing(app_name), "keep": data_operations.KEEP}


@router.post("/{app_name}/backups", status_code=202)
async def create_backup(app_name: str, background: BackgroundTasks, env: str = "prod",
                        current_user: User = Depends(get_current_active_user)):
    app = await _app(app_name, env)
    _database(app)
    doc = await data_operations.start("backup", app, env, current_user.username)
    background.add_task(data_operations.backup, doc)
    await activity_log.log("data.backup.started", category=CATEGORY_APP, actor=current_user.username,
                           target=app_name, detail={"env": env, "operation": doc["_id"]})
    return {**data_operations.public(doc),
            "message": "Respaldando en segundo plano. Consulta list_backups hasta que diga succeeded."}


@router.post("/{app_name}/backups/{backup_id}/restore", status_code=202)
async def restore_backup(app_name: str, backup_id: str, request: Request, background: BackgroundTasks,
                         env: str = "prod", dry_run: bool = False, plan_id: Optional[str] = None,
                         approval_id: Optional[str] = None, current_user: User = Depends(get_current_active_user)):
    app = await _app(app_name, env)
    _database(app)
    source = await data_operations.find(app_name, backup_id)
    if not source:
        raise HTTPException(404, "Respaldo no encontrado para esta base.")
    try:
        plan = data_operations.restore_plan(app, env, source)
        if dry_run:
            return JSONResponse(plans.dry_run_answer("restore_database", plan))
        plans.verify("restore_database", plan, plan_id)
    except (data_operations.DataError, plans.PlanMismatch) as exc:
        raise _plan_error(exc)
    from app.services import approvals
    await approvals.gate(request, action="data.restore", target=f"{app_name}/{env}",
                         payload={"backup_id": backup_id, "plan": plan},
                         summary=f"Reemplazar los datos de {app_name} en {env} con el respaldo {backup_id} "
                                 f"({source.get('created_at')}, {source.get('size')} bytes)",
                         approval_id=approval_id)
    doc = await data_operations.start("restore", app, env, current_user.username, backup_id=backup_id)
    background.add_task(data_operations.restore, doc, app, source)
    await activity_log.log("data.restore.started", category=CATEGORY_APP, actor=current_user.username,
                           target=app_name, detail={"env": env, "backup": backup_id, "operation": doc["_id"]})
    return {**data_operations.public(doc), "plan": plan,
            "message": "Restaurando en segundo plano (primero un respaldo de seguridad). Sigue el estado con list_backups."}


@router.post("/{app_name}/query")
async def query_database(app_name: str, body: dict, request: Request,
                         current_user: User = Depends(get_current_active_user)):
    """Lectura de datos: Postgres en transacción de solo lectura; MongoDB con find acotado."""
    from app.services.autonomy_policy import AutonomyError, require_elevated

    body = body or {}
    env = str(body.get("env") or "prod")
    app = await _app(app_name, env)
    _database(app)
    try:
        require_elevated(request.state.principal)
    except AutonomyError as exc:
        raise HTTPException(exc.status, str(exc))
    try:
        result = await data_operations.query(app, env, body)
    except data_operations.DataError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.warning("Consulta fallida en %s/%s: %s", app_name, env, type(exc).__name__)
        raise HTTPException(502, "No se pudo ejecutar la consulta en el pod de la base")
    await activity_log.log("data.query", category=CATEGORY_APP, actor=current_user.username, target=app_name,
                           detail={"env": env, "engine": result.get("engine")})
    return {"app": app_name, **result}


# ── Secretos pedidos ─────────────────────────────────────────────────────
@router.get("/{app_name}/secret-requests")
async def app_secret_requests(app_name: str):
    await _app(app_name)
    return {"app": app_name, "requests": await agent_requests.for_app(app_name)}


@router.post("/{app_name}/secret-requests", status_code=201)
async def request_secret(app_name: str, body: dict, request: Request):
    app = await _app(app_name)
    body = body or {}
    try:
        return await agent_requests.create(request.state.principal, app, str(body.get("variable") or ""),
                                           str(body.get("reason") or ""), body.get("environments"))
    except agent_requests.RequestError as exc:
        raise HTTPException(400, str(exc))


@requests_router.get("")
async def list_secret_requests(state: Optional[str] = "pending"):
    return {"requests": await agent_requests.listing(state or None)}


@requests_router.post("/{request_id}/fulfill")
async def fulfill_secret_request(request_id: str, body: dict, current_user: User = Depends(get_current_active_user)):
    """Una persona captura el valor. Se guarda igual que set_app_variable y nunca vuelve en la respuesta."""
    from app.routers.apps import set_app_variable

    try:
        pending = await agent_requests.claim(request_id)
    except agent_requests.RequestError as exc:
        raise HTTPException(409, str(exc))
    value = str((body or {}).get("value") or "")
    if not value:
        raise HTTPException(400, "Falta el valor.")
    answer = await set_app_variable(pending["app"], pending["variable"],
                                    {"value": value, "overwrite": bool((body or {}).get("overwrite")),
                                     "environments": pending.get("environments")}, current_user)
    try:
        closed = await agent_requests.close(request_id, state=agent_requests.FULFILLED, actor=current_user.username)
    except agent_requests.RequestError as exc:
        raise HTTPException(409, str(exc))
    answer.pop("value", None)
    return {"request": closed, "variable": answer}


@requests_router.post("/{request_id}/cancel")
async def cancel_secret_request(request_id: str, current_user: User = Depends(get_current_active_user)):
    try:
        return await agent_requests.close(request_id, state=agent_requests.CANCELLED, actor=current_user.username)
    except agent_requests.RequestError as exc:
        raise HTTPException(409, str(exc))
