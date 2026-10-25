"""
Integración directa a main desde el Hub
=======================================

En proyectos que lo activan, una tarea revisada por otro agente (o por una persona) se integra
sola en la rama principal del repositorio de la app con la credencial GitHub de Kaanbal, sin PR:

1. Comprobaciones: la tarea está *done* con rama y la cerró alguien distinto de quien la hizo; los
   checks de GitHub del último commit de la rama terminaron en verde (sin checks no se integra si el
   proyecto los exige); la rama se puede fusionar sin conflictos.
2. Merge de la rama en main (`POST /repos/{repo}/merges`).
3. Seguimiento: el pipeline del commit de merge y la salud en Argo hasta ver la versión nueva sana.

Si algo falla, la tarea vuelve a *blocked* con el motivo y se avisa al agente y a las personas.
Nunca se aplica al core de Kaanbal: solo a repositorios de apps.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import httpx

INTEGRATION_MODES = ("manual", "auto")
OK_CONCLUSIONS = {"success", "neutral", "skipped"}
_REPO_URL = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")


class IntegrationBlocked(Exception):
    """No se integra: el motivo es para la traza y para el agente que debe corregirlo."""


def repo_from_url(url: str) -> Optional[str]:
    match = _REPO_URL.search((url or "").strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def precheck(task: Mapping[str, Any]) -> Optional[str]:
    """Motivo por el que la tarea todavía no puede integrarse, o None."""
    if task.get("status") != "done":
        return "La tarea no está cerrada (done)."
    branch = task.get("branch") or ""
    if not branch or not _BRANCH.match(branch) or branch in ("main", "master"):
        return "La tarea no tiene una rama de trabajo propia (hub_update_task con branch)."
    reviewer, author = task.get("reviewed_by"), task.get("assignee_agent")
    if not reviewer or (author and reviewer == author):
        return "La integración automática exige que la cierre otro agente o una persona."
    return None


def checks_verdict(check_runs: List[Mapping[str, Any]], statuses: List[Mapping[str, Any]],
                   require_checks: bool) -> Tuple[str, str]:
    """('ok' | 'pending' | 'failed' | 'missing', detalle) a partir de check runs y commit statuses."""
    if not check_runs and not statuses:
        return ("missing", "La rama no tiene checks de CI.") if require_checks else ("ok", "Sin checks (no exigidos).")
    pending = [c.get("name") for c in check_runs if c.get("status") != "completed"]
    pending += [s.get("context") for s in statuses if s.get("state") == "pending"]
    failed = [c.get("name") for c in check_runs
              if c.get("status") == "completed" and c.get("conclusion") not in OK_CONCLUSIONS]
    failed += [s.get("context") for s in statuses if s.get("state") in ("failure", "error")]
    if failed:
        return "failed", "Checks en rojo: " + ", ".join(str(n) for n in failed[:5])
    if pending:
        return "pending", "Checks en curso: " + ", ".join(str(n) for n in pending[:5])
    return "ok", f"{len(check_runs) + len(statuses)} check(s) en verde."


def deploy_verdict(status: Optional[Mapping[str, Any]], sha: str) -> Tuple[str, str]:
    """('deployed' | 'waiting' | 'unhealthy', detalle) desde el estado de Argo de la app."""
    if not status or not status.get("exists", True):
        return "waiting", "Argo todavía no reporta la app."
    health = (status.get("health") or {}).get("status", "Unknown")
    sync = (status.get("sync") or {}).get("status", "Unknown")
    images = status.get("images") or []
    fresh = not images or any(sha[:7] in str(image) for image in images)
    if health == "Degraded":
        return "unhealthy", f"Argo: Degraded ({(status.get('health') or {}).get('message') or 'sin detalle'})."
    if health == "Healthy" and sync == "Synced" and fresh:
        return "deployed", "Argo: Healthy y Synced con la versión nueva."
    return "waiting", f"Argo: {health} / {sync}" + ("" if fresh else " (aún con la imagen anterior)") + "."


class GitHubIntegration:
    """Lo mínimo de la API de GitHub que necesita la integración, con la credencial de la plataforma."""

    def __init__(self, token: str):
        if not token:
            raise IntegrationBlocked("Kaanbal no tiene credencial de GitHub configurada.")
        self.token = token

    async def _request(self, method: str, path: str, *, body=None, params=None) -> Tuple[int, Any]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, "https://api.github.com" + path, json=body, params=params, headers={
                "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"})
        return response.status_code, (response.json() if response.content else {})

    async def default_branch(self, repo: str) -> str:
        code, data = await self._request("GET", f"/repos/{repo}")
        if code != 200:
            raise IntegrationBlocked(f"GitHub no deja leer {repo} (HTTP {code}).")
        return data["default_branch"]

    async def branch_head(self, repo: str, branch: str) -> str:
        code, data = await self._request("GET", f"/repos/{repo}/commits/{branch}")
        if code != 200:
            raise IntegrationBlocked(f"La rama {branch} no existe en {repo}.")
        return data["sha"]

    async def checks(self, repo: str, sha: str) -> Tuple[list, list]:
        _, runs = await self._request("GET", f"/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100})
        _, combined = await self._request("GET", f"/repos/{repo}/commits/{sha}/status")
        return (runs or {}).get("check_runs", []), (combined or {}).get("statuses", [])

    async def merge(self, repo: str, base: str, head: str, message: str) -> Optional[str]:
        """sha del merge; None si la rama ya estaba integrada."""
        code, data = await self._request("POST", f"/repos/{repo}/merges",
                                         body={"base": base, "head": head, "commit_message": message})
        if code == 201:
            return data["sha"]
        if code == 204:
            return None
        if code == 409:
            raise IntegrationBlocked(f"Conflicto al fusionar {head} en {base}: actualiza la rama con {base} y vuelve a pedir revisión.")
        if code in (403, 404):
            raise IntegrationBlocked(f"La credencial de Kaanbal no puede escribir en {base} de {repo} (HTTP {code}); revisa permisos o protección de rama.")
        raise IntegrationBlocked(f"GitHub rechazó el merge (HTTP {code}).")

    async def workflow_runs(self, repo: str, sha: str) -> list:
        _, data = await self._request("GET", f"/repos/{repo}/actions/runs", params={"head_sha": sha, "per_page": 20})
        return (data or {}).get("workflow_runs", [])


Report = Callable[[str, str, Dict[str, Any]], Awaitable[None]]


async def run(task: Mapping[str, Any], repo: str, app_name: str, gh: Any, argo_status: Callable[[str], Awaitable[Any]],
              report: Report, *, require_checks: bool = True, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
              check_wait: int = 40, deploy_wait: int = 60, interval: float = 15) -> str:
    """Integra la rama de la tarea y sigue el despliegue. Devuelve el estado final.

    `report(state, detail, extra)` guarda cada paso (la tarea y la traza). Estados: checking, merged,
    deployed, deploy_failed, deploy_unknown y blocked (con motivo).
    """
    try:
        problem = precheck(task)
        if problem:
            raise IntegrationBlocked(problem)
        branch = task["branch"]
        base = await gh.default_branch(repo)
        head = await gh.branch_head(repo, branch)
        await report("checking", f"Revisando checks de {branch} ({head[:7]}).", {"head": head})
        for _ in range(check_wait):
            verdict, detail = checks_verdict(*(await gh.checks(repo, head)), require_checks)
            if verdict != "pending":
                break
            await sleep(interval)
        if verdict != "ok":
            raise IntegrationBlocked(detail if verdict != "pending" else detail + " (se agotó la espera).")
        label = task.get("key") or task.get("_id")
        merge_sha = await gh.merge(repo, base, branch, f"Integra {label}: {task.get('title')} (Hub de Kaanbal, revisó {task.get('reviewed_by')})")
        if merge_sha is None:
            await report("merged", f"{branch} ya estaba integrada en {base}.", {"base": base})
            return "merged"
        await report("merged", f"{branch} integrada en {base} ({merge_sha[:7]}). Siguiendo el despliegue.",
                     {"base": base, "sha": merge_sha})
    except IntegrationBlocked as exc:
        await report("blocked", str(exc), {})
        return "blocked"

    # Despliegue: el pipeline del commit de merge y después Argo.
    seen_pipeline = False
    for _ in range(deploy_wait):
        runs = await gh.workflow_runs(repo, merge_sha)
        if runs:
            seen_pipeline = True
            failed = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") not in OK_CONCLUSIONS]
            if failed:
                await report("deploy_failed", f"Pipeline en rojo: {failed[0].get('name')} ({failed[0].get('html_url', '')}).", {})
                return "deploy_failed"
            if all(r.get("status") == "completed" for r in runs):
                verdict, detail = deploy_verdict(await argo_status(app_name), merge_sha)
                if verdict == "deployed":
                    await report("deployed", detail, {})
                    return "deployed"
                if verdict == "unhealthy":
                    await report("deploy_failed", detail, {})
                    return "deploy_failed"
        await sleep(interval)
    if not seen_pipeline:
        await report("deploy_unknown", "No apareció un pipeline para el commit integrado; revisa el CI de la app.", {})
        return "deploy_unknown"
    await report("deploy_failed", "La versión nueva no quedó sana a tiempo; revisa diagnose_app y pipeline_logs.", {})
    return "deploy_failed"
