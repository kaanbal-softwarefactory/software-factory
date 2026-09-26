"""
Core Router — version y actualizaciones del engine (ADR-002)
============================================================
Endpoints de solo lectura sobre la procedencia del core. Aplicar un upgrade
es una transaccion aparte y la conduce un Job de Kubernetes, no este proceso:
si `kaanbal-api` promoviera su propia imagen, el proceso que conduce el upgrade
seria el que muere a mitad de camino.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.routers.auth import get_current_active_user
from app.services import core_release, core_upgrade, vault_sync
from app.services.activity_log import activity_log, CATEGORY_SYSTEM

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get("/version")
async def get_core_version():
    """Que version corre esta celula."""
    return await core_release.read_provenance()


@router.get("/updates")
async def get_core_updates():
    """Hay algo mas nuevo publicado, y esta celula esta modificada."""
    return await core_release.check_updates()


@router.get("/releases")
async def get_core_releases(limit: int = 20):
    """Releases publicadas upstream, con notas."""
    return {"releases": await core_release.list_releases(limit=limit)}


@router.get("/drift")
async def get_core_drift():
    """Componentes del core modificados localmente."""
    return await core_release.detect_drift()


@router.post("/upgrade", status_code=202)
async def start_core_upgrade(body: Optional[dict] = None, current_user=Depends(get_current_active_user)):
    """Lanza el upgrade del engine como Job. Responde de inmediato.

    La deriva se revisa aquí además de en el Job: es mejor que la consola lo
    diga antes de lanzar nada que ver fallar el Job a los pocos segundos.
    """
    ref = str((body or {}).get("ref") or "main")
    drift = await core_release.detect_drift()
    if drift.get("any_custom"):
        custom = [n for n, c in (drift.get("components") or {}).items() if c.get("custom")]
        raise HTTPException(
            status_code=409,
            detail=f"Hay cambios locales en {', '.join(custom)}. Resuelve la deriva antes de actualizar.",
        )
    try:
        result = await core_upgrade.start_upgrade(actor=current_user.username, ref=ref)
    except core_upgrade.UpgradeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("No se pudo lanzar el upgrade")
        raise HTTPException(status_code=424, detail=f"No se pudo lanzar el upgrade: {exc}"[:300])

    await activity_log.log(
        "core.upgrade.started", category=CATEGORY_SYSTEM,
        actor=current_user.username, target=result["name"], detail={"ref": ref},
    )
    return result


@router.get("/vault")
async def get_vault_status():
    """Estado de Vault y apps cuyos secretos no llegaron a Vault."""
    return vault_sync.public_view(await vault_sync.missing())


@router.post("/vault/reconcile")
async def reconcile_vault(current_user=Depends(get_current_active_user)):
    """Restaura en Vault los secretos que faltan. No sobrescribe rutas existentes.

    La API no puede desbloquear Vault (la llave vive solo en el nodo); si está
    sellado lo dice en vez de fallar a medias.
    """
    result = await vault_sync.reconcile()
    if result.get("written"):
        await activity_log.log(
            "core.vault.reconciled", category=CATEGORY_SYSTEM, actor=current_user.username,
            target="vault", detail={"written": result["written"]},
        )
    return result


@router.get("/upgrade")
async def get_core_upgrade(name: Optional[str] = None):
    """Estado y log del último upgrade (o de uno por nombre)."""
    try:
        return await core_upgrade.upgrade_status(name)
    except Exception as exc:
        raise HTTPException(status_code=424, detail=f"No se pudo leer el estado del upgrade: {exc}"[:300])
