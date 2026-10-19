"""
Operar una app en caliente: versiones, reinicio, rollback, promoción y consumo
============================================================================

GitOps sigue siendo la fuente de verdad. Lo que cambia qué imagen corre
(rollback y promoción) escribe `newTag` en el overlay del ambiente en
infra-gitops, igual que lo hace el pipeline, y ArgoCD lo despliega; nunca se
parchea el clúster por fuera. El próximo build del pipeline vuelve a escribir su
propio tag, que es lo esperado: un rollback dura hasta el siguiente despliegue.

Reiniciar sí toca el clúster directo, con la misma anotación que usa
`kubectl rollout restart`: no cambia nada de lo que declara GitOps (ArgoCD no lo
ve como deriva) y los pods se reemplazan de a uno.

Las funciones puras (tags, planes, métricas) se prueban sin clúster; las que
leen o escriben el clúster o el repositorio están separadas al final.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_NEW_TAG = re.compile(r"(?m)^(\s*newTag:\s*)(['\"]?)([^'\"\s#]+)(['\"]?)(.*)$")
RESTARTED_AT = "kubectl.kubernetes.io/restartedAt"
# Un frontend lleva hornadas en el build las URLs de su ambiente (VITE_API_URL…):
# su imagen de staging no sirve en prod. Se promueve fusionando la rama.
NO_IMAGE_PROMOTION = {"frontend"}


class OperationError(ValueError):
    """La operación no se puede hacer así. El mensaje es para la persona."""


# ── Tags e imágenes ──────────────────────────────────────────────────────
def image_tag(image: str) -> str:
    image = image or ""
    if "@" in image:
        return image.split("@", 1)[1]
    last = image.rsplit("/", 1)[-1]
    return last.rsplit(":", 1)[1] if ":" in last else "latest"


def read_tag(kustomization: str) -> Optional[str]:
    match = _NEW_TAG.search(kustomization or "")
    return match.group(3) if match else None


def write_tag(kustomization: str, tag: str) -> str:
    if not TAG.match(tag or ""):
        raise OperationError(f"'{tag}' no es un tag de imagen válido.")
    if not _NEW_TAG.search(kustomization or ""):
        raise OperationError("El overlay no declara la imagen (newTag): la app usa una imagen oficial fija.")
    return _NEW_TAG.sub(lambda m: f"{m.group(1)}{m.group(2)}{tag}{m.group(4)}{m.group(5)}", kustomization, count=1)


def revisions_view(revisions: List[Mapping[str, Any]], current_tag: Optional[str]) -> List[Dict[str, Any]]:
    """Las versiones que corrieron, de la más nueva a la más vieja, sin repetir tag."""
    seen, rows = set(), []
    for item in sorted(revisions, key=lambda r: r.get("revision") or 0, reverse=True):
        tag = image_tag(str(item.get("image") or ""))
        if tag in seen:
            continue
        seen.add(tag)
        rows.append({
            "tag": tag, "image": item.get("image"), "revision": item.get("revision"),
            "created": item.get("created"), "serving": bool(item.get("ready")),
            "current": tag == current_tag,
        })
    return rows


# ── Planes ───────────────────────────────────────────────────────────────
def rollback_plan(app: str, env: str, current: Optional[str], target: str,
                  known: List[Mapping[str, Any]]) -> Dict[str, Any]:
    if not current:
        raise OperationError("La app no tiene una imagen versionada en GitOps: no hay a qué versión volver.")
    if not TAG.match(target or ""):
        raise OperationError(f"'{target}' no es un tag de imagen válido.")
    tags = [row["tag"] for row in known]
    if target not in tags:
        listed = ", ".join(tags[:8]) or "ninguna"
        raise OperationError(f"{target} no es una versión que haya corrido en {env} (conocidas: {listed}). "
                             "Usa list_revisions para ver las disponibles.")
    if target == current:
        raise OperationError(f"{app} ya declara {target} en {env}.")
    return {
        "action": "rollback", "app": app, "env": env, "from_tag": current, "to_tag": target,
        "effects": [
            f"infra-gitops: apps/{app}/overlays/{env}/kustomization.yaml pasa de {current} a {target}.",
            "ArgoCD reemplaza los pods con la versión anterior (unos minutos).",
            "El próximo push a la rama del ambiente vuelve a desplegar una versión nueva.",
        ],
        "not_reverted": "Datos y migraciones de base: si la versión nueva cambió el esquema, la anterior puede no entenderlo.",
    }


def promote_plan(app: Mapping[str, Any], source: str, target: str,
                 source_tag: Optional[str], target_tag: Optional[str]) -> Dict[str, Any]:
    name = app.get("name")
    environments = list(app.get("environments") or ["prod"])
    for env in (source, target):
        if env not in environments:
            raise OperationError(f"{name} no tiene ambiente '{env}'.")
    if source == target:
        raise OperationError("Origen y destino son el mismo ambiente.")
    if str(app.get("category") or "") in NO_IMAGE_PROMOTION:
        raise OperationError(
            "Un frontend lleva en su build las URLs de su ambiente: su imagen no se puede mover a otro. "
            "Promuévelo fusionando la rama (por ejemplo staging → main) y deja que el pipeline construya.")
    if not source_tag or not target_tag:
        raise OperationError("La app no tiene imagen versionada en GitOps en ambos ambientes.")
    if source_tag == target_tag:
        raise OperationError(f"{target} ya corre {source_tag}.")
    return {
        "action": "promote", "app": name, "from_env": source, "to_env": target,
        "from_tag": target_tag, "to_tag": source_tag,
        "effects": [
            f"infra-gitops: apps/{name}/overlays/{target}/kustomization.yaml pasa de {target_tag} a {source_tag} "
            f"(la imagen que hoy corre en {source}).",
            f"ArgoCD despliega esa imagen en {target} con las variables y secretos de {target}.",
        ],
    }


# ── Métricas ─────────────────────────────────────────────────────────────
_CPU = {"n": 1e-6, "u": 1e-3, "m": 1.0, "": 1000.0}
_MEMORY = {"Ki": 1 / 1024, "Mi": 1.0, "Gi": 1024.0, "Ti": 1024.0 ** 2, "K": 1e3 / 1048576,
           "M": 1e6 / 1048576, "G": 1e9 / 1048576, "": 1 / 1048576}


def millicores(value: Any) -> Optional[float]:
    match = re.fullmatch(r"([0-9.]+)([num]?)", str(value or ""))
    return round(float(match.group(1)) * _CPU[match.group(2)], 1) if match else None


def mebibytes(value: Any) -> Optional[float]:
    match = re.fullmatch(r"([0-9.]+)(Ki|Mi|Gi|Ti|K|M|G)?", str(value or ""))
    return round(float(match.group(1)) * _MEMORY[match.group(2) or ""], 1) if match else None


def _percent(used: Optional[float], limit: Optional[float]) -> Optional[int]:
    return round(100 * used / limit) if used is not None and limit else None


def metrics_view(usage: List[Mapping[str, Any]], pods: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Consumo por pod contra sus límites, con avisos en lenguaje simple."""
    by_pod = {row["pod"]: row for row in usage}
    rows, notes = [], []
    for pod in pods:
        used = by_pod.get(pod["name"], {})
        cpu, memory = millicores(used.get("cpu")), mebibytes(used.get("memory"))
        cpu_limit, memory_limit = millicores(pod.get("cpu_limit")), mebibytes(pod.get("memory_limit"))
        row = {
            "pod": pod["name"], "ready": pod.get("ready"), "restarts": pod.get("restarts", 0),
            "cpu_m": cpu, "cpu_limit_m": cpu_limit, "cpu_pct": _percent(cpu, cpu_limit),
            "memory_mib": memory, "memory_limit_mib": memory_limit, "memory_pct": _percent(memory, memory_limit),
        }
        rows.append(row)
        if (row["memory_pct"] or 0) >= 85:
            notes.append(f"{pod['name']} usa {row['memory_pct']}% de su memoria: cerca de que Kubernetes lo detenga (OOMKilled).")
        if (row["cpu_pct"] or 0) >= 90:
            notes.append(f"{pod['name']} está al {row['cpu_pct']}% de su CPU: responde lento bajo carga.")
        if memory_limit is None:
            notes.append(f"{pod['name']} no tiene límite de memoria: puede afectar a otras apps del nodo.")
    if not usage and pods:
        notes.append("El clúster no reporta consumo (metrics-server no responde): solo se muestran límites y reinicios.")
    return {"pods": rows, "notes": notes}


# ── Clúster ──────────────────────────────────────────────────────────────
def _clients():
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


def collect_revisions(app: str, env: str) -> List[Dict[str, Any]]:
    client = _clients()
    apps_api = client.AppsV1Api()
    rows = []
    for rs in apps_api.list_namespaced_replica_set(env, label_selector=f"app={app}").items:
        if app not in [owner.name for owner in (rs.metadata.owner_references or [])]:
            continue
        rows.append({
            "revision": int((rs.metadata.annotations or {}).get("deployment.kubernetes.io/revision", "0") or 0),
            "image": rs.spec.template.spec.containers[0].image,
            "ready": rs.status.ready_replicas or 0,
            "created": _iso(rs.metadata.creation_timestamp),
        })
    return rows


def restart(app: str, env: str) -> Dict[str, Any]:
    from kubernetes.client.rest import ApiException

    client = _clients()
    apps_api = client.AppsV1Api()
    now = datetime.now(timezone.utc).isoformat()
    patch = {"spec": {"template": {"metadata": {"annotations": {RESTARTED_AT: now}}}}}
    for kind, patcher in (("Deployment", apps_api.patch_namespaced_deployment),
                          ("StatefulSet", apps_api.patch_namespaced_stateful_set)):
        try:
            patcher(app, env, patch)
            return {"app": app, "env": env, "kind": kind, "restarted_at": now}
        except ApiException as exc:
            if exc.status != 404:
                raise
    raise OperationError(f"No hay nada desplegado de {app} en {env}.")


def collect_metrics(app: str, env: str) -> Dict[str, Any]:
    client = _clients()
    core = client.CoreV1Api()
    pods = []
    for pod in core.list_namespaced_pod(env, label_selector=f"app={app}").items:
        container = next((c for c in pod.spec.containers if c.name == app), pod.spec.containers[0])
        limits = (container.resources.limits or {}) if container.resources else {}
        status = (pod.status.container_statuses or [None])[0]
        pods.append({"name": pod.metadata.name, "ready": bool(status and status.ready),
                     "restarts": status.restart_count if status else 0,
                     "cpu_limit": limits.get("cpu"), "memory_limit": limits.get("memory")})
    usage = []
    try:
        answer = client.CustomObjectsApi().list_namespaced_custom_object(
            "metrics.k8s.io", "v1beta1", env, "pods", label_selector=f"app={app}")
        for item in answer.get("items", []):
            containers = item.get("containers") or []
            mine = next((c for c in containers if c.get("name") == app), containers[0] if containers else {})
            usage.append({"pod": item["metadata"]["name"], **(mine.get("usage") or {})})
    except Exception:
        usage = []
    return metrics_view(usage, pods)


# ── GitOps ───────────────────────────────────────────────────────────────
async def gitops_tags(app: str, envs: List[str], *, write: Optional[Mapping[str, str]] = None,
                      message: str = "") -> Dict[str, Optional[str]]:
    """Lee el tag declarado en cada overlay; con `write` ({env: tag}) lo cambia y empuja."""
    from app.services.app_deployer import AppDeployer

    deployer = AppDeployer()
    await deployer._load_credentials()
    work = tempfile.mkdtemp(prefix="kaanbal-release-")
    infra = os.path.join(work, "infra-gitops")
    try:
        result = subprocess.run(["git", "clone", "--depth", "1", deployer.provider.get_auth_clone_url("infra-gitops"), infra],
                                capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            raise OperationError("No se pudo leer infra-gitops. Revisa la credencial de Git de la plataforma.")
        tags: Dict[str, Optional[str]] = {}
        for env in envs:
            path = os.path.join(infra, "apps", app, "overlays", env, "kustomization.yaml")
            if not os.path.isfile(path):
                tags[env] = None
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            tags[env] = read_tag(text)
            if write and env in write:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(write_tag(text, write[env]))
        if write:
            await deployer._push_infra(infra, app, list(write), message=message or f"chore({app}): release")
        return tags
    finally:
        shutil.rmtree(work, ignore_errors=True)
