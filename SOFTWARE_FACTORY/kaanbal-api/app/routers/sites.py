"""
Sites Router — registro unificado de cómputo (BLUEPRINT RFC-0001 §2)
====================================================================
Una sola tabla para: VPS workers, PC local, gateways IoT de clientes y
GPU efímera. La UI de "mis workers" y la de "gateways de mis clientes"
es esta misma colección filtrada por type y client_id.

Sites edge reconcilian por PULL: el cerebro publica desired-state
(retenido, vía EMQX) y el gateway-agent lo aplica y reporta status.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime

import httpx

from app.db import get_db
from app.models import SiteCreate, SiteHeartbeat, SiteType
from app.routers.auth import get_current_active_user

router = APIRouter(dependencies=[Depends(get_current_active_user)])


async def _publish_desired_state_mqtt(site_name: str, payload: dict) -> bool:
    """Best-effort: publicar desired-state retenido vía EMQX REST API.
    Si EMQX no está configurado, el edge lo recogerá por polling/reconexión."""
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}
    api_url = config.get("emqx_api_url")
    api_key = config.get("emqx_api_key")
    api_secret = config.get("emqx_api_secret")
    if not (api_url and api_key and api_secret):
        return False
    try:
        import json as _json
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{api_url.rstrip('/')}/api/v5/publish",
                auth=(api_key, api_secret),
                json={
                    "topic": f"gw/{site_name}/desired-state",
                    "payload": _json.dumps(payload),
                    "qos": 1,
                    "retain": True,
                },
            )
            return resp.status_code in (200, 202)
    except Exception:
        return False


@router.get("", response_model=List[dict])
async def list_sites(
    type: Optional[SiteType] = Query(default=None),
    client_id: Optional[str] = Query(default=None),
):
    """Listar sites (filtros: type=edge → flota IoT; client_id → por cliente)"""
    db = get_db()
    query = {}
    if type:
        query["type"] = type.value
    if client_id:
        query["client_id"] = client_id
    sites = await db.sites.find(query).to_list(200)
    for site in sites:
        site["_id"] = str(site["_id"])
    return sites


@router.post("", status_code=201)
async def register_site(site_data: SiteCreate):
    """Registrar un site nuevo (worker, PC local, gateway de cliente, GPU efímera)"""
    db = get_db()

    existing = await db.sites.find_one({"name": site_data.name})
    if existing:
        raise HTTPException(status_code=409, detail="Site already registered")

    if site_data.client_id:
        client = await db.clients.find_one({"slug": site_data.client_id})
        if not client:
            raise HTTPException(status_code=404, detail=f"Client '{site_data.client_id}' not found")

    doc = {
        **site_data.model_dump(),
        "type": site_data.type.value,
        "status": "joining",
        "resources": {},
        "desired_state_version": None,
        "last_heartbeat": None,
        "joined_at": datetime.utcnow(),
    }
    result = await db.sites.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


@router.get("/{site_name}")
async def get_site(site_name: str):
    """Detalle de un site"""
    db = get_db()
    site = await db.sites.find_one({"name": site_name})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    site["_id"] = str(site["_id"])
    return site


@router.post("/{site_name}/heartbeat")
async def site_heartbeat(site_name: str, hb: SiteHeartbeat):
    """El agente del site reporta estado y recursos (cpu/mem/disk, apps corriendo)"""
    db = get_db()
    site = await db.sites.find_one({"name": site_name})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    update = {
        "status": hb.status,
        "resources": hb.resources,
        "last_heartbeat": datetime.utcnow(),
    }
    if hb.agent_version:
        update["agent_version"] = hb.agent_version
    if hb.apps is not None:
        update["running_apps"] = hb.apps
    if hb.applied_state_version is not None:
        update["applied_state_version"] = hb.applied_state_version

    await db.sites.update_one({"name": site_name}, {"$set": update})

    desired = await db.site_desired_states.find_one({"_id": site_name})
    return {
        "message": "ok",
        "desired_state_version": (desired or {}).get("version"),
        "in_sync": bool(desired) and desired.get("version") == hb.applied_state_version,
    }


@router.put("/{site_name}/desired-state")
async def set_desired_state(site_name: str, state: dict):
    """Publicar el estado deseado de un site edge: catálogo de apps del cliente,
    dashboard default, config. El gateway lo aplica por pull (estilo ArgoCD de borde)."""
    db = get_db()
    site = await db.sites.find_one({"name": site_name})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    previous = await db.site_desired_states.find_one({"_id": site_name})
    version = ((previous or {}).get("version") or 0) + 1

    doc = {
        "_id": site_name,
        "version": version,
        "state": state,
        "updated_at": datetime.utcnow(),
    }
    await db.site_desired_states.replace_one({"_id": site_name}, doc, upsert=True)
    await db.sites.update_one({"name": site_name}, {"$set": {"desired_state_version": version}})

    published = await _publish_desired_state_mqtt(site_name, {"version": version, "state": state})
    return {"message": "Desired state saved", "version": version, "mqtt_published": published}


@router.get("/{site_name}/desired-state")
async def get_desired_state(site_name: str):
    """Estado deseado vigente de un site edge"""
    db = get_db()
    desired = await db.site_desired_states.find_one({"_id": site_name})
    if not desired:
        raise HTTPException(status_code=404, detail="No desired state set for this site")
    return desired


@router.get("/{site_name}/join")
async def get_join_instructions(site_name: str):
    """Instrucciones para unir el site al plano de control según su tipo"""
    db = get_db()
    site = await db.sites.find_one({"name": site_name})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    config = await db.system_config.find_one({"_id": "main"}) or {}
    master_host = config.get("cluster_ssh_host", "<MASTER_HOST>")

    if site["type"] in (SiteType.CLOUD.value, SiteType.LOCAL.value):
        return {
            "type": site["type"],
            "steps": [
                "1. Instalar Tailscale y unirse a la tailnet: curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up",
                "2. Obtener el token del master: ssh al master y leer /var/lib/rancher/k3s/server/node-token",
                f"3. Unirse como agente: curl -sfL https://get.k3s.io | K3S_URL=https://{master_host}:6443 K3S_TOKEN=<NODE_TOKEN> sh -s - agent --node-name {site['name']}",
                f"4. Confirmar registro: el heartbeat cambia este site a 'online' (POST /api/v1/sites/{site['name']}/heartbeat)",
            ],
            "note": "Para célula independiente (no worker), usar tools/install-local.sh en su lugar.",
        }

    if site["type"] == SiteType.EDGE.value:
        return {
            "type": "edge",
            "steps": [
                "1. Flashear/preparar el gateway con Docker + Tailscale (ver iot-edge-gateway/README.md)",
                f"2. Configurar .env: GW_ID={site['name']}, EMQX del cerebro y credenciales bridge",
                "3. docker compose up -d — el agente se suscribe a su desired-state y reporta status",
                f"4. Publicar catálogo: PUT /api/v1/sites/{site['name']}/desired-state",
            ],
        }

    return {
        "type": "ephemeral",
        "steps": [
            "Los sites efímeros se crean/destruyen por el flujo de Terraform (fase 5)",
            "El workflow: crear instancia → join automático → entrenar → drain → destroy",
        ],
    }


@router.delete("/{site_name}")
async def delete_site(site_name: str):
    """Dar de baja un site (drain manual antes si tiene apps)"""
    db = get_db()
    result = await db.sites.delete_one({"name": site_name})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Site not found")
    await db.site_desired_states.delete_one({"_id": site_name})
    return {"message": f"Site {site_name} deleted"}
