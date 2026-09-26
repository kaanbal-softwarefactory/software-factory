"""
Domains Router — multi-dominio (BLUEPRINT RFC-0001 §3.1)
========================================================
De "1 instalación = 1 dominio" a N dominios como entidad de primera clase.
Migración transparente: el dominio guardado por el instalador en system_config
se auto-siembra como Domain default la primera vez que se consulta.

Dar de alta un dominio no es solo insertar un documento: hay que agregarle
reglas al túnel de Cloudflare y crear el DNS wildcard, o el dominio queda
registrado pero sin ruta de entrada. Por eso el alta valida primero
(`POST /verify`) y provisiona después.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId

from app.db import get_db
from app.models import DomainCreate
from app.routers.auth import get_current_active_user
from app.services import domain_service
from app.services.activity_log import activity_log, CATEGORY_SYSTEM

router = APIRouter(dependencies=[Depends(get_current_active_user)])


async def _ensure_seed_default():
    """Si no hay dominios pero el instalador ya fijó uno, sembrarlo como default."""
    db = get_db()
    count = await db.domains.count_documents({})
    if count > 0:
        return
    config = await db.system_config.find_one({"_id": "main"})
    if config and config.get("domain"):
        await db.domains.insert_one({
            "fqdn": config["domain"],
            "cloudflare_zone_id": config.get("cloudflare_zone_id"),
            "tunnel_id": config.get("cloudflare_tunnel_id"),
            "is_default": True,
            "client_id": None,
            "status": "active",
            "created_at": datetime.utcnow(),
            "seeded_from": "system_config",
        })


def _oid(domain_id: str) -> ObjectId:
    try:
        return ObjectId(domain_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid domain id")


@router.get("", response_model=List[dict])
async def list_domains():
    """Listar dominios (siembra el default desde system_config si es la primera vez)"""
    await _ensure_seed_default()
    db = get_db()
    domains = await db.domains.find().to_list(100)
    for domain in domains:
        domain["_id"] = str(domain["_id"])
        domain["apps_count"] = await domain_service.count_apps_using(
            domain["_id"], is_default=bool(domain.get("is_default")),
        )
    return domains


@router.post("/verify")
async def verify_domain(body: dict):
    """Validar un dominio ANTES de registrarlo. No modifica nada.

    Devuelve un check por condición para que el alta explique qué falta en vez
    de fallar con un error opaco.
    """
    fqdn = str(body.get("fqdn") or "").strip().lower()
    if not fqdn:
        raise HTTPException(status_code=400, detail="fqdn is required")
    return await domain_service.verify(fqdn, tunnel_id=body.get("tunnel_id") or "")


@router.post("", status_code=201)
async def create_domain(domain_data: DomainCreate):
    """Registrar un dominio adicional y cablearlo en Cloudflare.

    Valida la zona, agrega las reglas del túnel y crea el DNS wildcard + raíz.
    Si la validación falla el dominio no se registra: un dominio a medio cablear
    es peor que ninguno, porque las apps que lo elijan desplegarían a la nada.
    """
    await _ensure_seed_default()
    db = get_db()

    fqdn = domain_data.fqdn.strip().lower()
    existing = await db.domains.find_one({"fqdn": fqdn})
    if existing:
        raise HTTPException(status_code=409, detail="Domain already registered")

    config = await db.system_config.find_one({"_id": "main"}) or {}
    tunnel_id = domain_data.tunnel_id or config.get("cloudflare_tunnel_id", "")

    report = await domain_service.verify(fqdn, tunnel_id=tunnel_id)
    if not report["ok"]:
        failures = [c for c in report["checks"] if c["status"] == "fail"]
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"{fqdn} no pasó la validación y no fue registrado.",
                "checks": report["checks"],
                "blocking": [c["label"] for c in failures],
            },
        )

    zone_id = domain_data.cloudflare_zone_id or report["zone_id"]
    tunnel_id = report.get("tunnel_id") or tunnel_id
    try:
        provisioned = await domain_service.provision(fqdn, zone_id=zone_id, tunnel_id=tunnel_id)
    except domain_service.DomainError as exc:
        raise HTTPException(status_code=424, detail=str(exc))

    total = await db.domains.count_documents({})
    is_default = domain_data.is_default or total == 0
    if is_default:
        await db.domains.update_many({}, {"$set": {"is_default": False}})

    doc = {
        "fqdn": fqdn,
        "cloudflare_zone_id": zone_id,
        "tunnel_id": tunnel_id,
        "is_default": is_default,
        "client_id": domain_data.client_id,
        "status": "active",
        # Si la raíz apunta a otro origen se respetó; la consola lo muestra.
        "apex": provisioned.get("apex") or {"routed": True},
        "verified_at": datetime.utcnow(),
        "created_at": datetime.utcnow(),
    }
    result = await db.domains.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    doc["apps_count"] = 0
    doc["provisioned"] = provisioned.get("provisioned", [])
    doc["checks"] = report["checks"]

    await activity_log.log(
        "domain.created",
        category=CATEGORY_SYSTEM,
        target=fqdn,
        detail={"zone_id": zone_id, "tunnel_id": tunnel_id, "is_default": is_default},
    )
    return doc


@router.post("/{domain_id}/reverify")
async def reverify_domain(domain_id: str):
    """Re-validar un dominio ya registrado y refrescar su estado."""
    db = get_db()
    oid = _oid(domain_id)
    domain = await db.domains.find_one({"_id": oid})
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    report = await domain_service.verify(domain["fqdn"], tunnel_id=domain.get("tunnel_id") or "")
    await db.domains.update_one(
        {"_id": oid},
        {"$set": {
            "status": "active" if report["ok"] else "unverified",
            "cloudflare_zone_id": report.get("zone_id") or domain.get("cloudflare_zone_id"),
            "verified_at": datetime.utcnow(),
        }},
    )
    return report


@router.post("/{domain_id}/repair")
async def repair_domain(domain_id: str):
    """Reaplicar reglas de túnel y DNS de un dominio ya registrado (idempotente).

    Útil cuando el túnel se recreó o alguien borró el wildcard a mano.
    """
    db = get_db()
    oid = _oid(domain_id)
    domain = await db.domains.find_one({"_id": oid})
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    config = await db.system_config.find_one({"_id": "main"}) or {}
    tunnel_id = domain.get("tunnel_id") or config.get("cloudflare_tunnel_id", "")
    report = await domain_service.verify(domain["fqdn"], tunnel_id=tunnel_id)
    if not report["ok"]:
        raise HTTPException(status_code=422, detail={"checks": report["checks"]})

    zone_id = report.get("zone_id") or domain.get("cloudflare_zone_id")
    tunnel_id = report.get("tunnel_id") or tunnel_id
    try:
        provisioned = await domain_service.provision(
            domain["fqdn"], zone_id=zone_id, tunnel_id=tunnel_id,
        )
    except domain_service.DomainError as exc:
        raise HTTPException(status_code=424, detail=str(exc))

    # Si el dominio tiene una app raíz (homepage), su raíz debe apuntar al túnel
    # aunque hoy apunte al registrador: la app ya decidió ocuparla. Así Recablear
    # arregla homepages desplegadas antes de que el deployer tomara la raíz.
    root_query = {"is_root_domain": True, "domain_id": domain_id}
    if domain.get("is_default"):
        root_query = {"is_root_domain": True, "$or": [
            {"domain_id": domain_id}, {"domain_id": None}, {"domain_id": {"$exists": False}},
        ]}
    root_app = await db.apps.find_one(root_query, {"name": 1})
    if root_app:
        try:
            apex_result = await domain_service.ensure_apex_routed(
                domain["fqdn"], zone_id=zone_id, tunnel_id=tunnel_id,
            )
            provisioned["apex"] = {"routed": True, "root_app": root_app["name"],
                                   "replaced": apex_result.get("replaced", [])}
        except domain_service.DomainError as exc:
            raise HTTPException(status_code=424, detail=str(exc))

    await db.domains.update_one(
        {"_id": oid},
        {"$set": {
            "status": "active",
            "apex": provisioned.get("apex") or {"routed": True},
            "cloudflare_zone_id": zone_id,
            "tunnel_id": tunnel_id,
            "verified_at": datetime.utcnow(),
        }},
    )
    return {"message": f"{domain['fqdn']} recableado", **provisioned}


@router.post("/{domain_id}/set-default")
async def set_default_domain(domain_id: str):
    """Marcar un dominio como default (apps sin domain_id lo usan)"""
    db = get_db()
    oid = _oid(domain_id)
    domain = await db.domains.find_one({"_id": oid})
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    await db.domains.update_many({}, {"$set": {"is_default": False}})
    await db.domains.update_one({"_id": oid}, {"$set": {"is_default": True}})
    return {"message": f"Domain {domain['fqdn']} is now default"}


@router.get("/{domain_id}/apps")
async def get_domain_apps(domain_id: str):
    """Apps agrupadas bajo este dominio (el default incluye apps sin domain_id)"""
    db = get_db()
    oid = _oid(domain_id)
    domain = await db.domains.find_one({"_id": oid})
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    query = {"domain_id": domain_id}
    if domain.get("is_default"):
        query = {"$or": [{"domain_id": domain_id}, {"domain_id": None}, {"domain_id": {"$exists": False}}]}
    apps = await db.apps.find(query).to_list(200)
    for app in apps:
        app["_id"] = str(app["_id"])
    return apps


@router.delete("/{domain_id}")
async def delete_domain(domain_id: str):
    """Eliminar un dominio: solo si ninguna app lo referencia.

    El conteo incluye las apps sin domain_id cuando el dominio es el default:
    esas apps también dependen de él aunque nunca lo hayan nombrado.
    """
    db = get_db()
    oid = _oid(domain_id)
    domain = await db.domains.find_one({"_id": oid})
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    is_default = bool(domain.get("is_default"))
    apps_count = await domain_service.count_apps_using(domain_id, is_default=is_default)
    if apps_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{apps_count} app(s) siguen usando {domain['fqdn']}. Muévelas a otro "
                "dominio desde su exposición antes de eliminarlo."
            ),
        )

    total = await db.domains.count_documents({})
    if is_default and total > 1:
        raise HTTPException(status_code=409, detail="Set another domain as default first")

    # Retirar el cableado en Cloudflare; si falla, el registro se conserva para
    # no dejar reglas colgadas sin dueño visible en la consola.
    try:
        removed = await domain_service.deprovision(
            domain["fqdn"],
            zone_id=domain.get("cloudflare_zone_id") or "",
            tunnel_id=domain.get("tunnel_id") or "",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=424,
            detail=f"No se pudo retirar la configuración en Cloudflare: {exc}",
        )

    await db.domains.delete_one({"_id": oid})
    await activity_log.log(
        "domain.deleted",
        category=CATEGORY_SYSTEM,
        target=domain["fqdn"],
        detail=removed,
    )
    return {"message": f"Domain {domain['fqdn']} deleted", **removed}
