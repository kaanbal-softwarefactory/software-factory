"""
Stacks Router — lanzar base + API + frontend en una operación
=============================================================

Cada pieza se crea por el mismo camino que el Wizard (create_app_record +
_run_deploy), no por uno paralelo: mismas validaciones, mismo deployer, mismos
manifiestos. Lo que agrega este router es el orden y el cableado.

Las piezas se despliegan **en serie**: la API se vincula a las credenciales que
la base escribió en Vault, y el frontend se construye con la URL real de la API.
Si una pieza falla, el stack se detiene ahí y lo ya creado se queda en pie (es
una app normal, se puede reintentar o borrar desde Applications).
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import get_db
from app.models import AppCreate, User
from app.routers.apps import _run_deploy, create_app_record
from app.routers.auth import get_current_active_user
from app.services import activity_log, domain_service, stack_launcher
from app.services.activity_log import CATEGORY_APP
from app.services.template_service import TemplateService

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])
template_service = TemplateService()

# Un stack completo despliega tres apps; si lleva más de esto colgado, algo se rompió.
STACK_RUN_STALE_SECONDS = 45 * 60


class StackLaunchRequest(BaseModel):
    stack_id: str = Field(..., description="Id del stack en el catálogo")
    name: str = Field("", description="Nombre base; las piezas se llaman <base>, <base>-api, <base>-db")
    domain_id: Optional[str] = Field(default=None, description="Dominio del stack; None = el default")
    environments: List[str] = Field(default_factory=lambda: ["prod"])
    homepage: bool = Field(default=False, description="El frontend ocupa la raíz del dominio")
    group: Optional[str] = Field(default=None, description="Grupo lógico; por defecto, el nombre base")
    description: str = ""


def _run_view(run: dict | None) -> dict | None:
    """Estado de un lanzamiento, tal como lo muestra la consola."""
    if not run:
        return None
    view = dict(run)
    view["_id"] = str(run["_id"])
    started = run.get("started_at")
    if run.get("state") == "running" and isinstance(started, datetime):
        if (datetime.utcnow() - started).total_seconds() > STACK_RUN_STALE_SECONDS:
            view["state"] = "interrupted"
            view["error"] = "El lanzamiento se interrumpió (la API se reinició). Revisa las apps creadas."
    for key in ("started_at", "finished_at"):
        if isinstance(view.get(key), datetime):
            view[key] = view[key].isoformat() + "Z"
    for component in view.get("components", []):
        for key in ("started_at", "finished_at"):
            if isinstance(component.get(key), datetime):
                component[key] = component[key].isoformat() + "Z"
    return view


async def _resolve_domain(domain_id: Optional[str]) -> dict:
    db = get_db()
    if domain_id:
        try:
            target = await db.domains.find_one({"_id": ObjectId(domain_id)})
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid domain id")
        if not target:
            raise HTTPException(status_code=404, detail="Domain not found")
        return target
    return await domain_service.resolve_for_app(None)


@router.get("/catalog")
async def list_stacks(popular_only: bool = False):
    """Stacks disponibles, con el detalle de cada pieza ya resuelto."""
    stacks = await template_service.get_stacks(popular_only=popular_only)
    templates = {t["id"]: t for t in await template_service.get_templates()}
    for stack in stacks:
        for component in stack.get("components", []):
            template = templates.get(component.get("template")) or {}
            component["template_name"] = template.get("name") or component.get("template")
            component["icon"] = template.get("icon")
            component["port"] = template.get("port")
    return {"stacks": stacks, "total": len(stacks)}


@router.get("/runs")
async def list_stack_runs(limit: int = 10):
    """Últimos lanzamientos, el más reciente primero."""
    db = get_db()
    runs = await db.stack_runs.find().sort("started_at", -1).to_list(max(1, min(limit, 50)))
    return {"runs": [_run_view(run) for run in runs]}


@router.get("/runs/{run_id}")
async def get_stack_run(run_id: str):
    """Estado de un lanzamiento: en qué pieza va y cómo terminó cada una."""
    db = get_db()
    try:
        run = await db.stack_runs.find_one({"_id": ObjectId(run_id)})
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid run id")
    if not run:
        raise HTTPException(status_code=404, detail="Stack run not found")
    return _run_view(run)


@router.post("", status_code=202)
async def launch_stack(
    request: StackLaunchRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
):
    """Lanzar un stack completo. Responde 202; el progreso está en /stacks/runs/{id}."""
    db = get_db()
    stack = await template_service.get_stack_details(request.stack_id)
    if not stack:
        raise HTTPException(status_code=404, detail=f"Stack '{request.stack_id}' not found")

    target_domain = await _resolve_domain(request.domain_id)
    fqdn = str(target_domain.get("fqdn") or "").strip().lower()
    if not fqdn:
        raise HTTPException(status_code=400, detail="Platform domain is not configured")
    domain_id = str(target_domain["_id"]) if target_domain.get("_id") else None

    # El plan se calcula antes de crear nada: si algo choca, no queda medio stack.
    existing = await db.apps.find({}, {"name": 1}).to_list(500)
    try:
        plan = stack_launcher.build_plan(
            stack=stack,
            base_name=request.name,
            domain_fqdn=fqdn,
            domain_id=domain_id,
            environments=request.environments,
            homepage=request.homepage,
            group=request.group,
            taken_names=[app["name"] for app in existing],
        )
    except stack_launcher.StackPlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if plan["homepage"]:
        index = await domain_service.domains_index()
        for other in await db.apps.find({"is_root_domain": True}).to_list(100):
            if domain_service.describe_app_domain(other, index).get("fqdn") == fqdn:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"La raíz de {fqdn} ya la ocupa '{other['name']}'. Lanza el stack sin homepage "
                        "o elige otro dominio."
                    ),
                )

    running = await db.stack_runs.find_one({"state": "running"})
    if running and _run_view(running)["state"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Ya hay un stack lanzándose ('{running.get('base')}'). Espera a que termine.",
        )

    run_doc = {
        "stack_id": plan["stack_id"],
        "stack_name": plan["stack_name"],
        "base": plan["base"],
        "group": plan["group"],
        "domain": fqdn,
        "domain_id": domain_id,
        "environments": plan["environments"],
        "homepage": plan["homepage"],
        "state": "running",
        "actor": current_user.username,
        "started_at": datetime.utcnow(),
        "components": [
            {
                "role": component["role"],
                "name": component["name"],
                "template": component["template"],
                "url": f"https://{component['public_host']}" if component.get("public_host") else None,
                "state": "pending",
            }
            for component in plan["components"]
        ],
    }
    result = await db.stack_runs.insert_one(run_doc)
    run_id = str(result.inserted_id)

    await activity_log.log(
        "stack.launch.started", category=CATEGORY_APP, actor=current_user.username,
        target=plan["base"],
        detail={"stack": plan["stack_id"], "domain": fqdn, "homepage": plan["homepage"]},
    )

    background_tasks.add_task(_run_stack, run_id, plan, request.description, current_user.username)
    return {"run_id": run_id, **_run_view({**run_doc, "_id": result.inserted_id})}


async def _run_stack(run_id: str, plan: dict, description: str, actor: str):
    """Crear y desplegar cada pieza en orden, esperando a que la anterior termine."""
    db = get_db()
    run_oid = ObjectId(run_id)

    for index, component in enumerate(plan["components"]):
        field = f"components.{index}"
        await db.stack_runs.update_one({"_id": run_oid}, {"$set": {
            f"{field}.state": "deploying", f"{field}.started_at": datetime.utcnow(),
        }})
        try:
            payload = stack_launcher.app_create_payload(component, description=description)
            app_data = AppCreate(**payload)
            created = await create_app_record(app_data, actor)
            queue: asyncio.Queue = asyncio.Queue()
            await _run_deploy(created["id"], app_data, queue, actor)

            # _run_deploy no propaga el error: el estado real está en la app.
            app_doc = await db.apps.find_one({"_id": ObjectId(created["id"])}, {"status": 1, "error": 1, "url": 1})
            if (app_doc or {}).get("status") == "error":
                raise RuntimeError((app_doc or {}).get("error") or "el despliegue falló")

            await db.stack_runs.update_one({"_id": run_oid}, {"$set": {
                f"{field}.state": "ready",
                f"{field}.app_id": created["id"],
                f"{field}.finished_at": datetime.utcnow(),
            }})
        except Exception as exc:
            logger.exception("stack %s failed at %s", plan["base"], component["name"])
            message = str(exc)[:300]
            await db.stack_runs.update_one({"_id": run_oid}, {"$set": {
                f"{field}.state": "failed",
                f"{field}.error": message,
                f"{field}.finished_at": datetime.utcnow(),
                "state": "failed",
                "error": f"{component['name']}: {message}",
                "finished_at": datetime.utcnow(),
            }})
            await activity_log.error(
                "stack.launch.failed", category=CATEGORY_APP, actor=actor, target=plan["base"],
                detail={"stack": plan["stack_id"], "component": component["name"], "error": message},
                exc=exc,
            )
            return

    await db.stack_runs.update_one({"_id": run_oid}, {"$set": {
        "state": "succeeded",
        "urls": stack_launcher.public_urls(plan),
        "finished_at": datetime.utcnow(),
    }})
    await activity_log.log(
        "stack.launch.completed", category=CATEGORY_APP, actor=actor, target=plan["base"],
        detail={"stack": plan["stack_id"], "urls": stack_launcher.public_urls(plan)},
    )
