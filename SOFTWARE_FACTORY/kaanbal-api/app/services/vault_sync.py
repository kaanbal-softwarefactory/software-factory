"""
Vault Sync — estado de Vault y reconciliación de secretos de apps
================================================================
Vault se sella en cada reinicio del nodo (Shamir). Mientras está sellado, un
despliegue no puede guardar los secretos que genera: la app arranca igual —el
Secret de Kubernetes sí se crea—, pero Vault queda sin ellos y cualquier app que
después se vincule (un backend que lee la contraseña de su base) falla.

Este módulo cierra esa brecha:

  * status()      — sellado / abierto / inalcanzable, para que la consola lo diga.
  * missing()     — apps cuyo Secret existe en Kubernetes pero no en Vault.
  * reconcile()   — copia esos Secrets a Vault. Nunca sobrescribe: si la ruta ya
                    existe en Vault, Vault manda (alguien pudo rotar un valor).
  * reconcile_loop() — lo anterior cada pocos minutos, para que tras desbloquear
                    Vault todo quede al día sin que nadie tenga que acordarse.

Desbloquear Vault NO se hace aquí: la llave vive solo en el disco del nodo y la
API no la tiene (ni debe tenerla). Eso lo hace el timer del nodo que instala el
instalador (kaanbal-vault-unseal.timer).
"""

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.db import get_db

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 120
SECRET_SUFFIX = "-secrets-"


async def _vault_config() -> Dict[str, str]:
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}
    return {"addr": (config.get("vault_addr") or "").rstrip("/"), "token": config.get("vault_token") or ""}


async def status() -> Dict[str, Any]:
    """Estado de sellado. /sys/seal-status no requiere token."""
    cfg = await _vault_config()
    if not cfg["addr"]:
        return {"reachable": False, "configured": False, "sealed": None}
    try:
        async with httpx.AsyncClient(verify=False, timeout=5) as client:
            resp = await client.get(f"{cfg['addr']}/v1/sys/seal-status")
        data = resp.json()
        return {
            "reachable": True,
            "configured": True,
            "initialized": bool(data.get("initialized")),
            "sealed": bool(data.get("sealed")),
        }
    except Exception as exc:
        return {"reachable": False, "configured": True, "sealed": None, "error": str(exc)[:200]}


def app_secret_from(secrets: List[Any], app_name: str) -> Optional[Any]:
    """Secret más reciente de una app entre los de su namespace.

    kustomize secretGenerator agrega un hash al nombre (<app>-secrets-<hash>) y
    deja versiones anteriores hasta que ArgoCD las poda: se toma la más nueva.
    El prefijo exige el guion final para no confundir 'web' con 'web-api'.
    """
    prefix = f"{app_name}{SECRET_SUFFIX}"
    mine = [s for s in secrets if s.metadata.name.startswith(prefix)
            and "-" not in s.metadata.name[len(prefix):]]
    if not mine:
        return None
    return max(mine, key=lambda s: s.metadata.creation_timestamp)


def _list_secrets_by_namespace(namespaces: List[str]) -> Dict[str, List[Any]]:
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    core = client.CoreV1Api()
    out = {}
    for ns in namespaces:
        try:
            out[ns] = core.list_namespaced_secret(ns).items
        except Exception:
            out[ns] = []
    return out


async def missing() -> Dict[str, Any]:
    """Apps con Secret en Kubernetes que todavía no están en Vault."""
    vault = await status()
    if not vault.get("reachable") or vault.get("sealed"):
        return {"vault": vault, "missing": [], "checked": False}

    cfg = await _vault_config()
    db = get_db()
    apps = await db.apps.find({}, {"name": 1, "environments": 1}).to_list(500)
    namespaces = sorted({env for app in apps for env in (app.get("environments") or ["prod"])})
    secrets_by_ns = await asyncio.to_thread(_list_secrets_by_namespace, namespaces)

    result = []
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        for app in apps:
            for env in app.get("environments") or ["prod"]:
                secret = app_secret_from(secrets_by_ns.get(env, []), app["name"])
                if secret is None or not secret.data:
                    continue
                resp = await client.get(
                    f"{cfg['addr']}/v1/secret/data/{env}/{app['name']}",
                    headers={"X-Vault-Token": cfg["token"]},
                )
                if resp.status_code == 404:
                    result.append({
                        "app": app["name"], "env": env, "secret": secret.metadata.name,
                        "keys": sorted(secret.data.keys()),
                        "_data": secret.data,
                    })
    return {"vault": vault, "missing": result, "checked": True}


async def reconcile() -> Dict[str, Any]:
    """Escribe en Vault los secretos que faltan. Nunca pisa una ruta existente."""
    report = await missing()
    if not report["checked"]:
        return {"vault": report["vault"], "written": [], "failed": [], "reason": "Vault sellado o inalcanzable"}

    cfg = await _vault_config()
    written, failed = [], []
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        for item in report["missing"]:
            data = {k: base64.b64decode(v).decode() for k, v in item["_data"].items()}
            resp = await client.post(
                f"{cfg['addr']}/v1/secret/data/{item['env']}/{item['app']}",
                headers={"X-Vault-Token": cfg["token"]},
                json={"data": data, "options": {"cas": 0}},  # cas=0: solo si no existe
            )
            entry = {"app": item["app"], "env": item["env"], "keys": item["keys"]}
            if resp.status_code in (200, 204):
                written.append(entry)
                logger.info("Vault sync: secret/%s/%s restaurado desde %s", item["env"], item["app"], item["secret"])
            else:
                failed.append({**entry, "status": resp.status_code})
    return {"vault": report["vault"], "written": written, "failed": failed}


def public_view(report: Dict[str, Any]) -> Dict[str, Any]:
    """Quita los datos de los Secrets antes de devolverlos por la API."""
    return {**report, "missing": [
        {k: v for k, v in item.items() if not k.startswith("_")} for item in report.get("missing", [])
    ]}


async def reconcile_loop(interval: int = RECONCILE_INTERVAL_SECONDS):
    """Reconciliación periódica. Silenciosa cuando no hay nada que hacer."""
    while True:
        try:
            result = await reconcile()
            if result.get("written"):
                logger.info("Vault sync: %d secreto(s) restaurado(s)", len(result["written"]))
        except Exception as exc:  # nunca tumbar la API por esto
            logger.warning("Vault sync falló: %s", exc)
        await asyncio.sleep(interval)
