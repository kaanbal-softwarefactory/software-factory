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
from urllib.parse import urlsplit

INTEGRATION_MODES = ("manual", "auto")
OK_CONCLUSIONS = {"success", "neutral", "skipped"}
_REPO_URL = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")


def valid_branch(value: str) -> bool:
    return bool(_BRANCH.fullmatch(value or "") and not any(x in value for x in ("..", "//", "@{"))
                and not value.startswith(("/", ".")) and not value.endswith(("/", ".", ".lock")))


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
    if not valid_branch(branch) or branch in ("main", "master", "develop"):
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
    if require_checks and not (any(c.get("conclusion") == "success" for c in check_runs)
                               or any(s.get("state") == "success" for s in statuses)):
        return "missing", "No hay un check ejecutado con éxito; solo omisiones o resultados neutrales."
    return "ok", f"{len(check_runs) + len(statuses)} check(s) en verde."


def deploy_verdict(status: Optional[Mapping[str, Any]], sha: str) -> Tuple[str, str]:
    """('deployed' | 'waiting' | 'unhealthy', detalle) desde el estado de Argo de la app."""
    if not status or not status.get("exists", True):
        return "waiting", "Argo todavía no reporta la app."
    health = (status.get("health") or {}).get("status", "Unknown")
    sync = (status.get("sync") or {}).get("status", "Unknown")
    images = status.get("images") or []
    fresh = any(re.search(r"[-:]" + re.escape(sha[:7]) + r"(?:$|@)", str(image)) for image in images)
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
        code, runs = await self._request("GET", f"/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100})
        status_code, combined = await self._request("GET", f"/repos/{repo}/commits/{sha}/status", params={"per_page": 100})
        if code != 200 or status_code != 200:
            raise IntegrationBlocked("No se pudieron verificar los checks de GitHub; no se integra sin evidencia.")
        if (runs or {}).get("total_count", 0) > 100 or (combined or {}).get("total_count", 0) > 100:
            raise IntegrationBlocked("Hay más de 100 checks; revisa el resultado completo antes de integrar.")
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

    async def promotion_pr(self, repo: str, sha: str, *, title: str, body: str) -> dict:
        """Pin the verified Dev commit; never let later develop pushes change this PR."""
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise IntegrationBlocked("Falta el commit completo verificado en Dev.")
        branch = "release/dev-" + sha
        base = await self.default_branch(repo)
        code, ref = await self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        if code == 404:
            code, ref = await self._request("POST", f"/repos/{repo}/git/refs", body={"ref": "refs/heads/" + branch, "sha": sha})
            if code not in (200, 201):
                raise IntegrationBlocked("GitHub no permitió crear la rama candidata para la promoción.")
        elif code != 200:
            raise IntegrationBlocked("No se pudo comprobar la rama candidata de promoción.")
        if (ref.get("object") or {}).get("sha") != sha:
            raise IntegrationBlocked("La rama candidata existente no coincide; no se sobrescribe.")
        owner = repo.split("/")[0]
        code, existing = await self._request("GET", f"/repos/{repo}/pulls", params={"state": "open", "base": base, "head": f"{owner}:{branch}"})
        if code != 200:
            raise IntegrationBlocked("No se pudieron consultar los PR de promoción.")
        if existing:
            return {"url": existing[0]["html_url"], "number": existing[0]["number"], "sha": sha, "branch": branch, "base": base}
        code, pull = await self._request("POST", f"/repos/{repo}/pulls", body={"base": base, "head": branch, "title": title[:160], "body": body})
        if code != 201:
            raise IntegrationBlocked("No se pudo abrir el PR. Revisa permisos o si Dev ya está integrado en producción.")
        return {"url": pull["html_url"], "number": pull["number"], "sha": sha, "branch": branch, "base": base}


Report = Callable[[str, str, Dict[str, Any]], Awaitable[None]]


async def verify_business_app(url: str, *, path: str = "/", expected_text: str = "") -> dict:
    """An actual HTTPS request to the assigned app, not a PID or an Argo badge.

    This is a technical smoke test. It does not claim to inspect a visual design.
    Redirects are not followed (including redirects to an identity provider).
    """
    if not path.startswith("/") or path.startswith("//") or any(c in path for c in ("?", "#", "\\", "\r", "\n")):
        raise IntegrationBlocked("La ruta de prueba debe ser local a la app, sin consultas ni credenciales.")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise IntegrationBlocked("La prueba requiere la URL HTTPS asignada a la app.")
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        ready = await client.get(base + "/api/ready")
        if ready.status_code != 200 or ready.json().get("status") != "ready":
            return {"ok": False, "url": base, "scope": "technical-smoke", "detail": "La app no confirmó disponibilidad de sus dependencias."}
        async with client.stream("GET", base + path) as response:
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 1024 * 1024:
                    return {"ok": False, "url": base + path, "detail": "La respuesta superó el límite de la prueba."}
                chunks.append(chunk)
            text = b"".join(chunks).decode("utf-8", errors="replace")
            ok = response.status_code == 200 and bool(text.strip()) and (not expected_text or expected_text in text)
    return {"ok": ok, "url": base + path, "scope": "technical-smoke", "status": response.status_code,
            "expected_text_matched": bool(expected_text) and expected_text in text,
            "visual_acceptance": "pending",
            "detail": ("Dev responde y pasó la prueba técnica. Abre la app para aceptar el resultado visual."
                       if ok else "La ruta de prueba no devuelve el resultado esperado; no anuncies el cambio como verificado.")}


async def run(task: Mapping[str, Any], repo: str, app_name: str, gh: Any, argo_status: Callable[[str], Awaitable[Any]],
              report: Report, *, require_checks: bool = True, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
              check_wait: int = 40, deploy_wait: int = 60, interval: float = 15,
              base_branch: Optional[str] = None, environment: str = "prod",
              verify: Optional[Callable[[str], Awaitable[dict]]] = None) -> str:
    """Integra la rama de la tarea y sigue el despliegue. Devuelve el estado final.

    `report(state, detail, extra)` guarda cada paso (la tarea y la traza). Estados: checking, merged,
    deployed, deploy_failed, deploy_unknown y blocked (con motivo).
    """
    try:
        problem = precheck(task)
        if problem:
            raise IntegrationBlocked(problem)
        branch = task["branch"]
        base = base_branch or await gh.default_branch(repo)
        if not valid_branch(base) or branch == base:
            raise IntegrationBlocked("La rama de tarea debe ser distinta de la rama de integración.")
        head = await gh.branch_head(repo, branch)
        await report("checking", f"Revisando checks de {branch} ({head[:7]}).", {"head": head, "environment": environment, "base": base})
        for _ in range(check_wait):
            verdict, detail = checks_verdict(*(await gh.checks(repo, head)), require_checks)
            if verdict != "pending":
                break
            await sleep(interval)
        if verdict != "ok":
            raise IntegrationBlocked(detail if verdict != "pending" else detail + " (se agotó la espera).")
        if await gh.branch_head(repo, branch) != head:
            raise IntegrationBlocked("La rama cambió durante la comprobación. Revisa el commit nuevo antes de integrar.")
        label = task.get("key") or task.get("_id")
        merge_sha = await gh.merge(repo, base, head, f"Integra {label}: {task.get('title')} (Hub de Kaanbal, revisó {task.get('reviewed_by')})")
        if merge_sha is None:
            merge_sha = await gh.branch_head(repo, base)
        await report("merged", f"{branch} integrada en {base} ({merge_sha[:7]}). Siguiendo el despliegue.",
                     {"base": base, "sha": merge_sha})
    except IntegrationBlocked as exc:
        await report("blocked", str(exc), {})
        return "blocked"

    # Despliegue: el pipeline del commit de merge y después Argo.
    seen_pipeline = False
    for _ in range(deploy_wait):
        try:
            runs = await gh.workflow_runs(repo, merge_sha)
        except Exception:
            await report("deploy_unknown", "No se pudo consultar el pipeline; la integración no equivale a un despliegue confirmado.", {})
            return "deploy_unknown"
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
                    if verify is not None:
                        try:
                            proof = await verify(merge_sha)
                        except Exception:
                            proof = {"ok": False, "detail": "La comprobación funcional no respondió correctamente."}
                        if proof.get("ok"):
                            await report("verified", proof.get("detail") or "La comprobación funcional pasó.",
                                         {"verification": proof, "url": proof.get("url")})
                            return "verified"
                        await report("deploy_failed", proof.get("detail") or "Falta comprobar el funcionamiento de la nueva versión.",
                                     {"verification": proof})
                        return "deploy_failed"
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
