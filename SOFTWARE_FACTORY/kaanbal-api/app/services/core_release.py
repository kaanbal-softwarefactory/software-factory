"""
Core Release Service — procedencia y actualizaciones del core (ADR-002)
======================================================================
Responde tres preguntas que hoy una celula no puede responder:

  1. Que version soy.                    -> read_provenance()
  2. Hay algo mas nuevo publicado.       -> check_updates()
  3. Estoy modificada localmente.        -> detect_drift()

Una celula sin procedencia no puede compararse con upstream ni saber a que
volver si un upgrade sale mal, asi que todo lo demas cuelga de esto.

La release es un artefacto inmutable publicado como GitHub Release en el
monorepo, fijada por digest y no por tag: un tag puede moverse, un digest no.
Eso es lo que hace que dos celulas en la misma version corran el mismo binario
y que el rollback sea exacto.

Solo lectura. Aplicar un upgrade es otra cosa y vive en su propio modulo.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.db import get_db

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Repo publico que publica las releases del engine.
#
# Es configurable porque el proyecto ya cambio de casa una vez y una celula no
# debe necesitar una imagen nueva para saber donde buscar actualizaciones. Orden:
# ajuste de la celula (system_config.core_upstream) -> KAANBAL_UPSTREAM -> este.
DEFAULT_UPSTREAM = "kaanbal-softwarefactory/software-factory"
UPSTREAM_ENV = "KAANBAL_UPSTREAM"
# Donde vivia el proyecto antes de la v1. Se conserva para reconocer en logs y
# docs las celulas instaladas alli: su commit ya no existe en el historial nuevo.
LEGACY_UPSTREAM = "ProyectosUniUAEH/software-factory"

_UPSTREAM_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})$")

# Los tres componentes que forman el engine. Coincide con
# installer/corebuild.py: CORE_COMPONENTS.
CORE_COMPONENTS = ("kaanbal-api", "kaanbal-console", "kaanbal-agent")

CHANNEL_STABLE = "stable"
CHANNEL_DEV = "dev"
CHANNEL_CUSTOM = "custom"


def _gh_headers(token: str = "") -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _config() -> Dict[str, Any]:
    db = get_db()
    return await db.system_config.find_one({"_id": "main"}) or {}


def parse_upstream(value: Any) -> Optional[Tuple[str, str]]:
    """'owner/repo' -> (owner, repo); None si no es un repo de GitHub valido.

    El valor termina en una URL de API y en el `git clone` de un Job, asi que
    solo pasan los caracteres que GitHub permite: sin esquemas, sin rutas extra.
    """
    text = str(value or "").strip()
    if text.endswith(".git"):
        text = text[: -len(".git")]
    match = _UPSTREAM_RE.match(text)
    if not match or match.group(2) in (".", ".."):
        return None
    return match.group(1), match.group(2)


async def get_upstream(config: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """Repo del que esta celula recibe actualizaciones: (owner, repo).

    Un valor invalido se ignora en vez de romper las actualizaciones: una celula
    que ya no puede consultar upstream tampoco puede arreglarse desde la consola.
    """
    if config is None:
        config = await _config()
    for candidate in (config.get("core_upstream"), os.environ.get(UPSTREAM_ENV), DEFAULT_UPSTREAM):
        parsed = parse_upstream(candidate)
        if parsed:
            return parsed
        if candidate:
            logger.warning("Upstream invalido ignorado: %r", candidate)
    return parse_upstream(DEFAULT_UPSTREAM)  # type: ignore[return-value]


async def read_provenance() -> Dict[str, Any]:
    """Que version corre esta celula.

    Una instalacion anterior a ADR-002 no tiene procedencia. En vez de inventar
    una, se reporta `unknown`: decir "v1.0.0" sin saberlo haria que la celula
    creyera estar al dia y nunca se actualizara.
    """
    config = await _config()
    release = config.get("core_release") or {}
    if not release:
        return {
            "known": False,
            "channel": CHANNEL_STABLE,
            "version": "unknown",
            "upstream_sha": None,
            "upstream": None,
            "components": {},
            "reason": (
                "Esta celula se instalo antes de que se registrara la "
                "procedencia del core. Aplica una release para fijarla."
            ),
        }
    return {
        "known": True,
        "channel": release.get("channel") or CHANNEL_STABLE,
        "version": release.get("version") or "unknown",
        "upstream_sha": release.get("upstream_sha"),
        "upstream": release.get("upstream"),
        "components": release.get("components") or {},
        "applied_at": release.get("applied_at"),
        "applied_by": release.get("applied_by"),
    }


async def list_releases(limit: int = 20) -> List[Dict[str, Any]]:
    """Releases publicadas upstream, de la mas nueva a la mas vieja."""
    config = await _config()
    token = config.get("github_token") or config.get("git_token") or ""
    owner, repo = await get_upstream(config)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases?per_page={limit}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=_gh_headers(token))
            if resp.status_code != 200:
                logger.warning("GitHub releases HTTP %s: %s", resp.status_code, resp.text[:200])
                return []
            payload = resp.json()
    except Exception as exc:
        logger.warning("No se pudieron consultar releases upstream: %s", exc)
        return []

    releases = []
    for item in payload:
        if item.get("draft"):
            continue
        releases.append({
            "version": item.get("tag_name"),
            "name": item.get("name"),
            "notes": item.get("body") or "",
            "prerelease": bool(item.get("prerelease")),
            "published_at": item.get("published_at"),
            "url": item.get("html_url"),
        })
    return releases


# Rutas del monorepo que cambian lo que corre una célula. Un commit que solo
# toca docs/ no justifica un upgrade.
ENGINE_PATHS = (
    "SOFTWARE_FACTORY/kaanbal-api/",
    "SOFTWARE_FACTORY/kaanbal-console/",
    "SOFTWARE_FACTORY/kaanbal-agent/",
    "SOFTWARE_FACTORY/kaanbal-templates/",
    "SOFTWARE_FACTORY/infra-gitops/",
    "SOFTWARE_FACTORY/installer/",
    "SOFTWARE_FACTORY/tools/",
)


def _component_of(path: str) -> Optional[str]:
    for prefix in ENGINE_PATHS:
        if path.startswith(prefix):
            return prefix.rstrip("/").split("/")[-1]
    return None


async def upstream_commits(base_sha: Optional[str], branch: str = "main") -> Dict[str, Any]:
    """Commits de `branch` en el monorepo que esta célula todavía no aplicó.

    Canal dev: una célula sigue commits, no releases. Se compara el commit del
    que salió (procedencia) contra la punta de la rama, y se separa lo que toca
    el engine de lo que no, para no sugerir un upgrade por un cambio en docs.
    """
    config = await _config()
    token = config.get("github_token") or config.get("git_token") or ""
    owner, repo = await get_upstream(config)
    repo_url = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            head_resp = await client.get(f"{repo_url}/commits/{branch}", headers=_gh_headers(token))
            if head_resp.status_code != 200:
                return {"available": False, "reason": f"GitHub respondió HTTP {head_resp.status_code}"}
            head = head_resp.json()
            head_sha = head["sha"]

            if not base_sha:
                return {
                    "available": True, "head_sha": head_sha, "ahead_by": None,
                    "commits": [], "components": [], "touches_engine": True,
                    "reason": "Sin procedencia: no se sabe qué commits faltan.",
                }
            if base_sha == head_sha:
                return {"available": True, "head_sha": head_sha, "ahead_by": 0,
                        "commits": [], "components": [], "touches_engine": False}

            cmp_resp = await client.get(f"{repo_url}/compare/{base_sha}...{head_sha}", headers=_gh_headers(token))
            if cmp_resp.status_code in (404, 422):
                # GitHub no conoce ese commit en este repo: la celula salio de otro
                # (el proyecto se mudo) o el historial se reescribio. No hay que
                # comparar, pero si algo que ofrecer: la ultima revision. Sin esto
                # la consola diria "no se pudo comparar" y la celula quedaria
                # atada a un repo que ya nadie mantiene, sin aviso.
                return {
                    "available": True, "head_sha": head_sha, "ahead_by": None,
                    "commits": [], "components": [], "touches_engine": True,
                    "history_unknown": True,
                    "reason": (
                        f"El commit instalado ({base_sha[:7]}) no existe en {owner}/{repo}: "
                        f"el proyecto se mudó o reescribió su historial. "
                        f"Se ofrece la última revisión de {branch}."
                    ),
                }
            if cmp_resp.status_code != 200:
                return {"available": False, "reason": f"No se pudo comparar {base_sha[:7]} con {branch}"}
            cmp = cmp_resp.json()
    except Exception as exc:
        logger.warning("No se pudieron consultar commits upstream: %s", exc)
        return {"available": False, "reason": "Sin conexión con GitHub"}

    if cmp.get("status") in ("behind", "diverged"):
        # La célula corre algo que main ya no contiene (rama, force-push). No se
        # sugiere "actualizar" hacia atrás en silencio.
        return {"available": True, "head_sha": head_sha, "ahead_by": cmp.get("ahead_by", 0),
                "commits": [], "components": [], "touches_engine": False,
                "reason": f"La célula corre un commit que no está en {branch} ({cmp.get('status')})."}

    components = sorted({c for c in (_component_of(f.get("filename", "")) for f in cmp.get("files") or []) if c})
    commits = [
        {
            "sha": item["sha"],
            "message": (item["commit"]["message"] or "").splitlines()[0],
            "author": (item["commit"].get("author") or {}).get("name"),
            "date": (item["commit"].get("author") or {}).get("date"),
            "url": item.get("html_url"),
        }
        for item in reversed(cmp.get("commits") or [])
    ]
    return {
        "available": True,
        "head_sha": head_sha,
        "ahead_by": cmp.get("ahead_by", len(commits)),
        "commits": commits,
        "components": components,
        "touches_engine": bool(components),
    }


# Repos standalone que el upgrade sobrescribe: si alguien los tunea, hay deriva.
DRIFT_REPOS = CORE_COMPONENTS + ("kaanbal-templates",)

# Commits que escribe Kaanbal. Misma definición que tools/core-upgrade.sh: si la
# API y el script discreparan, la consola bloquearía upgrades que el script deja
# pasar (o al revés).
OWN_COMMIT_PREFIXES = ("bootstrap:", "upgrade: sync")


def foreign_commits(commits: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Commits hechos fuera de Kaanbal sobre un repo standalone, desde HEAD.

    Se recorre la historia hasta el último commit propio (instalador o upgrade);
    todo lo que haya antes es un cambio a mano. Comparar HEAD contra la
    procedencia no sirve: un upgrade interrumpido tras sincronizar mueve HEAD con
    un commit propio y aparecería como "modificado localmente" sin serlo.
    Una historia sin ningún commit propio es desconocida y cuenta como deriva.
    """
    foreign = []
    for commit in commits:
        message = ((commit.get("commit") or {}).get("message") or "")
        if message.startswith(OWN_COMMIT_PREFIXES):
            return foreign
        foreign.append({"sha": (commit.get("sha") or "")[:7], "message": message.splitlines()[0][:80]})
    return foreign or [{"sha": "?", "message": "sin commits de Kaanbal: historia desconocida"}]


async def detect_drift() -> Dict[str, Any]:
    """Componentes modificados localmente respecto a la release aplicada.

    Tunear el core es legitimo, asi que la deriva es un estado que se reporta,
    no un error. Lo que no es aceptable es pisarla en silencio durante un
    upgrade: por eso se detecta antes de ofrecer uno.
    """
    config = await _config()
    provenance = await read_provenance()
    recorded = provenance.get("components") or {}
    org = (config.get("github_org") or config.get("bitbucket_workspace") or "").strip()
    token = config.get("github_token") or config.get("git_token") or ""

    if not org or not token:
        return {"detectable": False, "reason": "Sin org o token de GitHub configurados", "components": {}}
    if not provenance["known"]:
        return {
            "detectable": False,
            "reason": "Sin procedencia registrada: no hay contra que comparar",
            "components": {},
        }

    components: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for name in DRIFT_REPOS:
            url = f"{GITHUB_API}/repos/{org}/{name}/commits?per_page=100"
            try:
                resp = await client.get(url, headers=_gh_headers(token))
                commits = resp.json() if resp.status_code == 200 else None
            except Exception as exc:
                logger.warning("drift check %s: %s", name, exc)
                commits = None

            if not isinstance(commits, list) or not commits:
                components[name] = {"custom": False, "unknown": True, "foreign_commits": []}
                continue
            foreign = foreign_commits(commits)
            components[name] = {
                "custom": bool(foreign),
                "unknown": False,
                "head_sha": commits[0].get("sha"),
                "expected_sha": (recorded.get(name) or {}).get("repo_sha"),
                "foreign_commits": foreign,
            }

    any_custom = any(c.get("custom") for c in components.values())
    return {"detectable": True, "any_custom": any_custom, "components": components}


async def check_updates() -> Dict[str, Any]:
    """Resumen que consume la consola: version actual, disponible y deriva.

    No aplica nada. El disparo del upgrade es manual y con changelog a la vista
    (ADR-002): un cambio malo aplicado solo llegaria a todos los clientes sin
    que nadie lo intercepte.
    """
    provenance = await read_provenance()
    drift = await detect_drift()
    channel = provenance.get("channel") or CHANNEL_STABLE
    owner, repo = await get_upstream()
    source = f"{owner}/{repo}"

    if channel == CHANNEL_DEV:
        # dev sigue commits de main: cada commit que toca el engine es un upgrade
        # posible. Así el autor valida en su propia célula antes de publicar una
        # release para stable.
        upstream = await upstream_commits(provenance.get("upstream_sha"))
        update_available = bool(upstream.get("available") and upstream.get("touches_engine"))
        return {
            "current": provenance,
            "channel": channel,
            "source": source,
            "tracking": "commits",
            "upstream": upstream,
            "latest": {"version": f"dev-{upstream['head_sha'][:7]}", "sha": upstream["head_sha"]}
            if upstream.get("head_sha") else None,
            "update_available": update_available,
            "pending_releases": [],
            "drift": drift,
            "blocked_by_drift": bool(drift.get("any_custom")) and update_available,
        }

    releases = await list_releases()
    candidates = [r for r in releases if not r["prerelease"]]
    latest = candidates[0] if candidates else None

    current_version = provenance.get("version")
    update_available = bool(
        latest and current_version and latest["version"] and latest["version"] != current_version
    )
    # Una celula sin procedencia no puede afirmar que esta al dia; ofrecerle la
    # ultima release es la forma de fijarla.
    if latest and not provenance["known"]:
        update_available = True

    pending = []
    if latest and current_version:
        for release in candidates:
            if release["version"] == current_version:
                break
            pending.append(release)

    return {
        "current": provenance,
        "channel": channel,
        "source": source,
        "tracking": "releases",
        "latest": latest,
        "update_available": update_available,
        "pending_releases": pending,
        "drift": drift,
        "blocked_by_drift": bool(drift.get("any_custom")) and update_available,
    }


async def write_provenance(
    *,
    version: str,
    upstream_sha: Optional[str],
    components: Dict[str, Any],
    channel: str = CHANNEL_STABLE,
    applied_by: str = "installer",
    upstream: Optional[str] = None,
) -> Dict[str, Any]:
    """Fija la procedencia de la celula. La escribe el instalador y cada upgrade."""
    from datetime import datetime

    db = get_db()
    release = {
        "version": version,
        "upstream_sha": upstream_sha,
        # De que repo salio ese SHA: sin esto, un SHA "desconocido" no se puede
        # distinguir de una celula que vino de otro origen.
        "upstream": upstream,
        "components": components,
        "channel": channel,
        "applied_at": datetime.utcnow(),
        "applied_by": applied_by,
    }
    await db.system_config.update_one(
        {"_id": "main"}, {"$set": {"core_release": release}}, upsert=True,
    )
    logger.info("Core provenance set: %s (%s)", version, channel)
    return release
