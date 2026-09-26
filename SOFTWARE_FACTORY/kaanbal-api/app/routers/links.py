"""
Service Links Router — matriz de vinculación (BLUEPRINT RFC-0001 §3.2)
======================================================================
"Soy backend, me pueden ver: público, vpn, o solo estas apps."
Una tabla → NetworkPolicies + variables de entorno + diagrama.
Generaliza database_bindings (que sigue funcionando; los links de BD
son un caso particular con port_name=db).
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId

from app.db import get_db
from app.models import ServiceLinkCreate
from app.routers.auth import get_current_active_user
from app.services import link_service

router = APIRouter(dependencies=[Depends(get_current_active_user)])

_VALID_ENVS = {"dev", "staging", "prod"}


_PORT_NAME_DEFAULTS = {
    "http": 80,
    "https": 443,
    "db": None,  # resolved from template below
    "postgres": 5432,
    "postgresql": 5432,
    "mongo": 27017,
    "mongodb": 27017,
    "mysql": 3306,
    "redis": 6379,
    "mqtt": 1883,
    "ws": 8083,
    "dashboard": 18083,
    "amqp": 5672,
}

_TEMPLATE_PORT_DEFAULTS = {
    "mongodb": 27017,
    "mongo": 27017,
    "postgres": 5432,
    "postgresql": 5432,
    "mysql": 3306,
    "redis": 6379,
    "n8n": 5678,
    "emqx": 18083,
    "fastapi-api": 8000,
}


async def _resolve_port_number(db, app_name: str, port_name: str) -> Optional[int]:
    """Resolver el puerto numérico desde la definición multi-puerto de la app,
    o su puerto principal / template como fallback."""
    app = await db.apps.find_one({"name": app_name})
    if not app:
        return None
    exposure = app.get("exposure") or {}
    for port_def in exposure.get("ports") or []:
        if port_def.get("name") == port_name:
            return port_def.get("port")
    specs = app.get("specs") or {}
    if specs.get("port") and port_name in ("http", "https", ""):
        return specs.get("port")

    # Logical DB/MQTT aliases → template defaults (database_bindings parity)
    named = _PORT_NAME_DEFAULTS.get(port_name)
    if named:
        return named

    template = (app.get("template") or app.get("template_id") or "").lower()
    for key, port in _TEMPLATE_PORT_DEFAULTS.items():
        if key in template:
            if port_name in ("db", "http", "tcp", ""):
                return port
            if port_name in key or key in port_name:
                return port
            # e.g. port_name=db + template=postgres
            if port_name == "db" and key in ("postgres", "postgresql", "mongodb", "mongo", "mysql", "redis"):
                return port
    if port_name == "db":
        for key, port in _TEMPLATE_PORT_DEFAULTS.items():
            if key in template:
                return port
    return specs.get("port")


@router.get("", response_model=List[dict])
async def list_links(
    from_app: Optional[str] = Query(default=None),
    to_app: Optional[str] = Query(default=None),
    env: Optional[str] = Query(default=None, description="Filtra links cuyo proveedor o consumidor esté en este env"),
):
    """Listar la matriz de vinculación (con filtros opcionales)"""
    db = get_db()
    query = {}
    if from_app:
        query["from_app"] = from_app
    if to_app:
        query["to_app"] = to_app
    if env:
        query["$or"] = [{"from_env": env}, {"to_env": env}]
    links = await db.service_links.find(query).to_list(500)
    for link in links:
        link["_id"] = str(link["_id"])
    return links


@router.post("", status_code=201)
async def create_link(link_data: ServiceLinkCreate):
    """Vincular dos apps: consumidor → proveedor por un puerto lógico"""
    db = get_db()

    if link_data.from_env not in _VALID_ENVS or link_data.to_env not in _VALID_ENVS:
        raise HTTPException(status_code=400, detail=f"Environments must be one of {sorted(_VALID_ENVS)}")
    if link_data.from_app == link_data.to_app and link_data.from_env == link_data.to_env:
        raise HTTPException(status_code=400, detail="An app cannot link to itself in the same environment")

    for app_name in (link_data.from_app, link_data.to_app):
        exists = await db.apps.find_one({"name": app_name})
        if not exists:
            raise HTTPException(status_code=404, detail=f"App '{app_name}' not found")

    duplicate = await db.service_links.find_one({
        "from_app": link_data.from_app,
        "from_env": link_data.from_env,
        "to_app": link_data.to_app,
        "to_env": link_data.to_env,
        "port_name": link_data.port_name,
    })
    if duplicate:
        raise HTTPException(status_code=409, detail="Link already exists")

    port_number = link_data.port_number
    if port_number is None:
        port_number = await _resolve_port_number(db, link_data.to_app, link_data.port_name)

    doc = {
        "from_app": link_data.from_app,
        "from_env": link_data.from_env,
        "to_app": link_data.to_app,
        "to_env": link_data.to_env,
        "port_name": link_data.port_name,
        "port_number": port_number,
        "alias": link_data.alias or link_service.default_alias(link_data.to_app),
        "visibility": link_data.visibility.value,
        "description": link_data.description,
        "created_at": datetime.utcnow(),
    }
    result = await db.service_links.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    doc["env_literals"] = link_service.build_env_literals(doc)
    return doc


@router.delete("/{link_id}")
async def delete_link(link_id: str):
    """Eliminar un vínculo"""
    db = get_db()
    try:
        oid = ObjectId(link_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid link id")
    result = await db.service_links.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"message": "Link deleted"}


@router.get("/diagram")
async def get_architecture_diagram():
    """El diagrama de arquitectura: apps agrupadas por dominio, sites,
    nodos Internet/VPN y aristas por cada vínculo. Un SELECT renderizado."""
    db = get_db()
    apps = await db.apps.find().to_list(200)
    links = await db.service_links.find().to_list(500)
    domains = await db.domains.find().to_list(100)
    sites = await db.sites.find().to_list(100)
    return link_service.build_diagram(apps, links, domains, sites)


@router.get("/manifests/{env}")
async def get_generated_manifests(env: str):
    """NetworkPolicies generadas para un ambiente, listas para escribirse en
    infra-gitops (overlays/<env>/netpol-<app>.yaml). Solo cubre apps que son
    proveedoras de al menos un link: opt-in gradual, no rompe apps sin vincular."""
    if env not in _VALID_ENVS:
        raise HTTPException(status_code=400, detail=f"Environment must be one of {sorted(_VALID_ENVS)}")
    db = get_db()
    links = await db.service_links.find({"to_env": env}).to_list(500)

    # Derivar exposición pública/vpn por app para conservar acceso de ingress/tailnet
    app_exposures = {}
    provider_names = {link["to_app"] for link in links}
    for app_name in provider_names:
        app = await db.apps.find_one({"name": app_name})
        exposure = (app or {}).get("exposure") or {}
        exp_type = exposure.get("type", "internal")
        public = exp_type in ("public", "both")
        vpn = exp_type in ("tailscale", "both")
        env_ports = (exposure.get("port_exposure") or {}).get(env, {})
        public = public or any(level == "public" for level in env_ports.values())
        vpn = vpn or any(level == "tailscale" for level in env_ports.values())
        app_exposures[app_name] = {"public": public, "vpn": vpn}

    manifests = link_service.generate_policies_for_env(env, links, app_exposures)
    return {
        "env": env,
        "count": len(manifests),
        "files": {f"apps/{name}/overlays/{env}/netpol-{name}.yaml": yaml for name, yaml in manifests.items()},
    }


@router.get("/env-literals/{app_name}/{env}")
async def get_env_literals(app_name: str, env: str):
    """Variables {ALIAS}_* que la app consumidora recibe por sus links salientes.
    Punto de integración para el deployer (mismo contrato que database_bindings)."""
    db = get_db()
    links = await db.service_links.find({"from_app": app_name, "from_env": env}).to_list(100)
    literals = []
    for link in links:
        literals.extend(link_service.build_env_literals(link))
    return {"app": app_name, "env": env, "literals": literals}
