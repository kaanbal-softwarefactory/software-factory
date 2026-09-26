"""
Core Upgrade Service — ejecutar el upgrade del engine desde la consola (ADR-002)
===============================================================================
La API no ejecuta el upgrade: lanza un Job de Kubernetes y reporta su estado.

Motivo: el upgrade reemplaza la imagen de la propia `kaanbal-api`. Si el proceso
de la API condujera la transacción, el momento de promover su nueva imagen
mataría al conductor a mitad de camino y la célula quedaría a medias, sin nadie
que verifique ni revierta. El Job es otro pod: sobrevive a ese reemplazo, y la
consola simplemente se reconecta.

El Job corre la misma transacción que `tools/core-upgrade.sh` en el nodo (preflight,
deriva, sync, build, promoción, verificación, rollback, procedencia). Una sola
implementación para la ruta manual y la del botón: no pueden divergir.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.db import get_db
from app.services import core_release

logger = logging.getLogger(__name__)

NAMESPACE = "prod"
SERVICE_ACCOUNT = "kaanbal-upgrader"
COMPONENT_LABEL = "kaanbal-engine.io/component"
COMPONENT_VALUE = "upgrader"

# Donde el Job descarga el monorepo. Sale del ajuste de la celula (ver
# core_release.get_upstream): fijarlo aqui ataria la celula a un repo para siempre.
_CLONE_URL_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}\.git$"
)


def upstream_clone_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


DEFAULT_UPSTREAM_URL = upstream_clone_url(*core_release.parse_upstream(core_release.DEFAULT_UPSTREAM))

# Imagen con bash, git, kubectl, python3 y curl. El tag se alinea con la versión
# del clúster: kubectl solo garantiza compatibilidad a ±1 versión menor.
TOOLS_IMAGE = "alpine/k8s"
TOOLS_FALLBACK_TAG = "1.36.4"

# Un upgrade que tarda más de esto está colgado; mejor que Kubernetes lo corte a
# que la consola muestre "en curso" para siempre.
ACTIVE_DEADLINE_SECONDS = 3600
LOG_TAIL_LINES = 200

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")


class UpgradeError(Exception):
    """El upgrade no se puede lanzar (ya hay uno, falta configuración, etc.)."""


def tools_image_for(server_version: Optional[str]) -> str:
    """alpine/k8s:<mayor>.<menor>.0 alineado con el clúster, o el tag probado."""
    match = re.match(r"v?(\d+)\.(\d+)", server_version or "")
    if not match:
        return f"{TOOLS_IMAGE}:{TOOLS_FALLBACK_TAG}"
    return f"{TOOLS_IMAGE}:{match.group(1)}.{match.group(2)}.0"


def build_job_manifest(
    *, name: str, org: str, ref: str, actor: str, image: str,
    upstream_repo: str = DEFAULT_UPSTREAM_URL,
) -> Dict[str, Any]:
    """Manifiesto del Job de upgrade. Puro: sin clúster, para poder testearlo."""
    if not _REF_RE.match(ref or ""):
        raise UpgradeError(f"Revisión inválida: {ref!r}")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$", org or ""):
        raise UpgradeError(f"Org de GitHub inválida: {org!r}")
    # Va como variable de entorno a un `git clone`: solo https a github.com.
    if not _CLONE_URL_RE.match(upstream_repo or ""):
        raise UpgradeError(f"Repositorio upstream inválido: {upstream_repo!r}")

    # El ref y la org ya están validados; aun así viajan como variables de
    # entorno y no interpolados en el script, para que nunca se interpreten.
    script = "\n".join([
        "set -euo pipefail",
        'git clone --quiet --depth 50 "$UPSTREAM_REPO" /work/sf',
        'git -C /work/sf fetch --quiet --depth 50 origin "$UPGRADE_REF"',
        "git -C /work/sf checkout --quiet --detach FETCH_HEAD",
        'echo "[kaanbal-upgrade] Monorepo descargado: $(git -C /work/sf rev-parse --short HEAD)"',
        'exec bash /work/sf/SOFTWARE_FACTORY/tools/core-upgrade.sh --ref "$UPGRADE_REF"',
    ])

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "labels": {COMPONENT_LABEL: COMPONENT_VALUE},
            "annotations": {
                "kaanbal-engine.io/actor": actor,
                "kaanbal-engine.io/ref": ref,
                "kaanbal-engine.io/upstream": upstream_repo,
            },
        },
        "spec": {
            # Un upgrade fallido ya se revierte solo; reintentarlo a ciegas
            # repetiría la transacción sin que nadie lo decidiera.
            "backoffLimit": 0,
            "activeDeadlineSeconds": ACTIVE_DEADLINE_SECONDS,
            # Se conserva un día para poder leer el log después.
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "metadata": {"labels": {COMPONENT_LABEL: COMPONENT_VALUE, "job-name": name}},
                "spec": {
                    "serviceAccountName": SERVICE_ACCOUNT,
                    "restartPolicy": "Never",
                    "containers": [{
                        "name": "upgrade",
                        "image": image,
                        "command": ["bash", "-c", script],
                        "env": [
                            {"name": "UPSTREAM_REPO", "value": upstream_repo},
                            {"name": "UPGRADE_REF", "value": ref},
                            {"name": "KAANBAL_ORG", "value": org},
                            {"name": "KAANBAL_SOURCE", "value": "/work/sf"},
                            # El checkout ya está hecho: el script no debe
                            # re-descargar ni re-ejecutarse.
                            {"name": "KAANBAL_UPGRADE_REEXEC", "value": "1"},
                            {"name": "HOME", "value": "/tmp"},
                        ],
                        "resources": {
                            "requests": {"cpu": "50m", "memory": "128Mi"},
                            "limits": {"cpu": "1", "memory": "512Mi"},
                        },
                        "volumeMounts": [{"name": "work", "mountPath": "/work"}],
                    }],
                    "volumes": [{"name": "work", "emptyDir": {}}],
                },
            },
        },
    }


def _clients():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.BatchV1Api(), client.CoreV1Api(), client.VersionApi()


def _job_state(job) -> str:
    status = job.status
    if status.succeeded:
        return "succeeded"
    if status.failed:
        return "failed"
    return "running"


def _summarize(job) -> Dict[str, Any]:
    annotations = job.metadata.annotations or {}
    return {
        "name": job.metadata.name,
        "state": _job_state(job),
        "ref": annotations.get("kaanbal-engine.io/ref"),
        "actor": annotations.get("kaanbal-engine.io/actor"),
        "started_at": job.status.start_time.isoformat() if job.status.start_time else None,
        "finished_at": job.status.completion_time.isoformat() if job.status.completion_time else None,
    }


def _upgrade_jobs(batch) -> List[Any]:
    jobs = batch.list_namespaced_job(
        NAMESPACE, label_selector=f"{COMPONENT_LABEL}={COMPONENT_VALUE}",
    ).items
    return sorted(jobs, key=lambda j: j.metadata.creation_timestamp, reverse=True)


async def start_upgrade(*, actor: str, ref: str = "main") -> Dict[str, Any]:
    """Lanza el Job de upgrade. Uno a la vez.

    Dos upgrades simultáneos escribirían tags en infra-gitops a la vez y dejarían
    un estado que ninguno de los dos sabe revertir.
    """
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}
    org = (config.get("github_org") or config.get("bitbucket_workspace") or "").strip()
    if not org:
        raise UpgradeError("La célula no tiene org de GitHub configurada.")

    batch, _core, version_api = _clients()
    running = [j for j in _upgrade_jobs(batch) if _job_state(j) == "running"]
    if running:
        raise UpgradeError(f"Ya hay un upgrade en curso: {running[0].metadata.name}")

    try:
        server_version = version_api.get_code().git_version
    except Exception:
        server_version = None

    owner, repo = await core_release.get_upstream(config)
    name = f"kaanbal-upgrade-{int(time.time())}"
    manifest = build_job_manifest(
        name=name, org=org, ref=ref, actor=actor, image=tools_image_for(server_version),
        upstream_repo=upstream_clone_url(owner, repo),
    )
    batch.create_namespaced_job(NAMESPACE, manifest)
    logger.info("Upgrade %s lanzado por %s (ref=%s, upstream=%s/%s)", name, actor, ref, owner, repo)
    return {"name": name, "state": "running", "ref": ref, "actor": actor, "upstream": f"{owner}/{repo}"}


async def upgrade_status(name: Optional[str] = None) -> Dict[str, Any]:
    """Estado del último upgrade (o de uno por nombre) con la cola de su log.

    Se lee del clúster, no de la API: si la API se reinició a mitad del upgrade,
    la consola igual recupera el progreso.
    """
    batch, core, _version = _clients()
    jobs = _upgrade_jobs(batch)
    if name:
        jobs = [j for j in jobs if j.metadata.name == name]
    if not jobs:
        return {"exists": False}

    job = jobs[0]
    summary = {"exists": True, **_summarize(job), "log": ""}
    pods = core.list_namespaced_pod(NAMESPACE, label_selector=f"job-name={job.metadata.name}").items
    if pods:
        try:
            summary["log"] = core.read_namespaced_pod_log(
                pods[0].metadata.name, NAMESPACE, tail_lines=LOG_TAIL_LINES,
            )
        except Exception:
            summary["log"] = ""  # el contenedor aún no arranca
    return summary
