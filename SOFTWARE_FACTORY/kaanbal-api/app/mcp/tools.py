"""
Lo que hace cada herramienta del MCP
====================================

Cada herramienta llama a la API REST con la credencial de quien preguntó (ver
loopback.py): el permiso, el alcance del token y la bitácora son exactamente
los de la REST. Aquí solo se valida la forma de los argumentos y se resume la
respuesta para que el agente razone con lo necesario, no con el volcado crudo.

Las que crean o cambian lo visible pasan por _plan_or_apply: sin plan_id piden
a la REST un dry_run y devuelven el plan; con plan_id aplican, y la REST vuelve
a calcular el plan y solo sigue si es el mismo (ver app/services/plans.py).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Protocol, Tuple

from app.mcp import catalog, guide
from app.mcp.protocol import ToolError
from app.services import app_blueprint, db_env
from app.services.diagnosis import mask

_APP_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ENV = re.compile(r"^[a-z]{2,16}$")
_PLAN_ID = re.compile(r"^[0-9a-f]{16}$")
_CATALOG_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_OBJECT_ID = re.compile(r"^[0-9a-f]{24}$")
_FQDN = re.compile(r"^(?=.{3,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$")
_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")
_BASE_NAME = re.compile(r"^[A-Za-z0-9 _-]{0,50}$")

OPERATIONS = ("exposure_change", "domain_move", "root_promotion")
BRANCHES = {"dev": "develop", "staging": "staging", "prod": "main"}


class ApiClient(Protocol):
    async def request(self, method: str, path: str, **kwargs: Any) -> Any: ...
    async def get(self, path: str, params: Dict[str, Any] = None) -> Any: ...
    async def post(self, path: str, json: Dict[str, Any] = None) -> Any: ...
    async def put(self, path: str, json: Dict[str, Any] = None) -> Any: ...


# ── Argumentos ───────────────────────────────────────────────────────────
def _name(value: Any, what: str = "app") -> str:
    name = str(value or "")
    if not _APP_NAME.match(name):
        raise ToolError(f"'{name}' no es un nombre de {what} válido: usa el nombre interno que da list_apps.")
    return name


def _app(args: Dict[str, Any]) -> str:
    return _name(args.get("name"))


def _env(args: Dict[str, Any]) -> str:
    env = str(args.get("env") or "prod")
    if not _ENV.match(env):
        raise ToolError(f"'{env}' no es un ambiente válido (prod, staging, dev).")
    return env


def _environments(value: Any) -> Optional[List[str]]:
    if value in (None, []):
        return None
    if not isinstance(value, list) or not all(isinstance(env, str) and _ENV.match(env) for env in value):
        raise ToolError("environments debe ser una lista como [\"dev\", \"prod\"].")
    return list(value)


def _catalog_id(value: Any, what: str) -> str:
    ident = str(value or "")
    if not _CATALOG_ID.match(ident):
        raise ToolError(f"'{ident}' no es un id de {what} válido (list_templates / list_stacks los muestran).")
    return ident


def _replicas(value: Any, *, required: bool) -> Optional[int]:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise ToolError("replicas va de 1 a 10. Para apagar un ambiente usa stop_app.")
    return value


def _plan_id(args: Dict[str, Any]) -> Optional[str]:
    value = args.get("plan_id")
    if value in (None, ""):
        return None
    if not _PLAN_ID.match(str(value)):
        raise ToolError("plan_id no es válido: usa el que devolvió el plan (16 caracteres).")
    return str(value)


async def _domain_id(client: ApiClient, fqdn: Any) -> str:
    wanted = str(fqdn or "").strip().lower()
    if not _FQDN.match(wanted):
        raise ToolError(f"'{fqdn}' no es un dominio válido.")
    domains = await client.get("/domains")
    for domain in domains:
        if str(domain.get("fqdn") or "").lower() == wanted:
            return str(domain["_id"])
    known = ", ".join(sorted(str(d.get("fqdn")) for d in domains)) or "ninguno"
    raise ToolError(f"{wanted} no está registrado en la plataforma (registrados: {known}). Se registra en la consola.")


# ── Plan → aplicar ───────────────────────────────────────────────────────
async def _plan_or_apply(client: ApiClient, method: str, path: str, args: Dict[str, Any],
                         body: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
    """(aplicado, respuesta). Sin plan_id: el plan, sin tocar nada."""
    plan_id = _plan_id(args)
    if plan_id is None:
        answer = await client.request(method, path, params={"dry_run": "true"}, json=body)
        planned = {
            "applied": False,
            "plan": answer.get("plan"),
            "plan_id": answer.get("plan_id"),
            "next": (
                "Nada se aplicó todavía. Muéstrale el plan a la persona y, si lo aprueba, repite esta "
                f"llamada con los mismos argumentos y plan_id=\"{answer.get('plan_id')}\"."
            ),
        }
        if answer.get("notices"):
            planned["notices"] = answer["notices"]
        return False, planned
    return True, await client.request(method, path, params={"plan_id": plan_id}, json=body)


# ── Resúmenes ────────────────────────────────────────────────────────────
def _running(app: Dict[str, Any]) -> List[str]:
    return [key for key in OPERATIONS if (app.get(key) or {}).get("state") == "running"]


def _app_summary(app: Dict[str, Any]) -> Dict[str, Any]:
    domain = app.get("domain") or {}
    return {
        "name": app.get("name"),
        "display_name": app.get("display_name"),
        "template": app.get("template"),
        "group": app.get("app_group"),
        "environments": app.get("environments") or [],
        "status": app.get("status"),
        "is_homepage": bool(app.get("is_root_domain")),
        "domain": domain.get("fqdn"),
        "urls": domain.get("urls") or {},
        "public": bool(domain.get("public")),
        "repo": app.get("repo_url"),
        "in_progress": _running(app),
    }


def _app_detail(app: Dict[str, Any]) -> Dict[str, Any]:
    domain = app.get("domain") or {}
    return {
        **_app_summary(app),
        "category": app.get("category"),
        "description": app.get("description"),
        "exposure": domain.get("modes") or {},
        "error": mask(str(app["error"])) if app.get("error") else None,
        "operations": {key: app[key] for key in OPERATIONS if app.get(key)},
    }


def _log_lines(text: str, limit: int) -> List[str]:
    """El NDJSON de ArgoCD → '[pod] línea', con secretos enmascarados."""
    lines: List[str] = []
    for raw in (text or "").splitlines():
        line = raw
        try:
            entry = (json.loads(raw) or {}).get("result") or {}
            if isinstance(entry, dict) and "content" in entry:
                if not entry.get("content") and entry.get("last"):
                    continue
                pod = entry.get("podName")
                line = f"[{pod}] {entry.get('content', '')}" if pod else str(entry.get("content", ""))
        except (ValueError, AttributeError):
            pass
        lines.append(mask(line))
    return lines[-limit:]


def _activity_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    detail = entry.get("detail") or {}
    event = detail.get("event") if isinstance(detail, dict) else None
    message = (event or {}).get("message") if isinstance(event, dict) else None
    item = {"at": entry.get("timestamp"), "action": entry.get("action"), "level": entry.get("level"),
            "message": mask(str(message)) if message else None}
    return {key: value for key, value in item.items() if value not in (None, "")}


# ── Contrato de una app ──────────────────────────────────────────────────
def _variable_groups(names: List[str], link_names: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Separa lo que pone la plataforma, lo que ponen los vínculos y lo propio de la app."""
    from_links = {name for names_ in link_names.values() for name in names_}
    # Una base vinculada al crear la app deja <PREFIJO>_URI (o _URL) junto a <PREFIJO>_HOST.
    prefixes = {
        name[: -len(suffix)] for name in names for suffix in ("_URI", "_URL")
        if name.endswith(suffix) and f"{name[: -len(suffix)]}_HOST" in names
    }
    platform, links, own = [], [], []
    for name in sorted(names):
        if name in from_links:
            links.append(name)
        elif name in db_env.CANONICAL_NAMES or name == "APP_SECRET" or any(name.startswith(f"{p}_") for p in prefixes):
            platform.append(name)
        else:
            own.append(name)
    return {"platform": platform, "links": links, "own": own}


LOCAL_HINTS = {
    "MONGO_URI": "mongodb://localhost:27017", "MONGODB_URI": "mongodb://localhost:27017",
    "MONGO_URL": "mongodb://localhost:27017", "MONGODB_URL": "mongodb://localhost:27017",
    "DATABASE_URL": "(la de tu base local, p. ej. postgresql://postgres:postgres@localhost:5432/postgres)",
    "POSTGRES_URI": "postgresql://postgres:postgres@localhost:5432/postgres",
    "PGHOST": "localhost", "PGPORT": "5432", "PGUSER": "postgres", "PGPASSWORD": "postgres", "PGDATABASE": "postgres",
    "REDIS_URL": "redis://localhost:6379/0",
    "CORS_ORIGINS": "http://localhost:5173",
    "APP_SECRET": "cualquier-valor-local",
}


def _local_env_example(groups: Dict[str, List[str]]) -> str:
    lines = ["# .env de desarrollo local: mismos nombres que en Kaanbal, valores tuyos. Nunca lo subas al repo."]
    for name in groups["platform"]:
        if name in db_env.CANONICAL_NAMES or name == "APP_SECRET":
            lines.append(f"{name}={LOCAL_HINTS.get(name, '')}")
    for name in groups["links"] + groups["own"]:
        lines.append(f"{name}={LOCAL_HINTS.get(name, '')}")
    return "\n".join(lines)


def _local_steps(template: str, category: str) -> List[str]:
    if category == "backend" and "fastapi" in template:
        return [
            "cp .env.example .env   # y ajusta los nombres de 'variables' con valores locales",
            "docker compose up -d   # la base, en tu máquina",
            "pip install -r requirements.txt",
            "uvicorn main:app --reload --port 8000   # /health dice si la base responde",
        ]
    if category == "frontend":
        return [
            "npm install",
            "npm run dev   # http://localhost:5173",
            "VITE_API_URL en .env.development apunta a tu API local; .env.production, a la API publicada.",
        ]
    if category == "database":
        return ["Es una base: en local usa la de docker compose de la API que la consume, con los mismos nombres de variables."]
    return ["Sin receta local para esta plantilla: corre su imagen con las variables de 'variables' en un .env."]


def _contract_rules(category: str, port: Any, health: Optional[str]) -> List[str]:
    rules = ["Toda la configuración llega por variables de entorno; nada de URLs ni credenciales en el código."]
    if port:
        rules.append(f"No cambies el puerto {port}" + (f" ni la ruta {health}" if health else "") +
                     ": el clúster los usa para saber si la app está viva.")
    if category == "frontend":
        rules.append("Todo lo que entra en el build lo ve quien abre la página: ningún secreto en el frontend.")
    rules.append("No edites manifiestos de Kubernetes en el repo de la app: los gobierna Kaanbal en infra-gitops.")
    rules.append("El contenedor es efímero y puede haber varias copias: el estado va en la base.")
    return rules


async def _app_contract(client: ApiClient, app: str, env: str) -> Dict[str, Any]:
    doc = await client.get(f"/apps/{app}")
    template_id = str(doc.get("template") or "")
    template: Dict[str, Any] = {}
    if _CATALOG_ID.match(template_id):
        try:
            template = await client.get(f"/templates/{template_id}")
        except ToolError:
            template = {}
    category = str(doc.get("category") or template.get("category") or "")
    port = template.get("port") or (doc.get("specs") or {}).get("port")
    health = "/health" if "fastapi" in template_id else ("/" if category == "frontend" else None)

    link_names: Dict[str, List[str]] = {}
    links: List[Dict[str, Any]] = []
    try:
        for link in await client.get("/links", {"from_app": app}):
            links.append({key: link.get(key) for key in ("to_app", "from_env", "kind", "alias", "port_name")})
            if link.get("from_env") == env:
                link_names[link.get("to_app")] = list(link.get("published_names") or [])
    except ToolError:
        links = []

    variables: Dict[str, Any]
    try:
        names = (await client.get(f"/apps/{app}/env-vars", {"env": env})).get("names") or []
        groups = _variable_groups(names, link_names)
        variables = {"env": env, **groups, "local_env_example": _local_env_example(groups)}
    except ToolError as exc:
        variables = {"env": env, "unavailable": str(exc)}

    has_repo = bool(doc.get("repo_url"))
    environments = list(doc.get("environments") or ["prod"])
    domain = doc.get("domain") or {}
    return {
        "app": app,
        "template": template_id,
        "category": category,
        "environments": environments,
        "runtime": {"port": port, "health_path": health},
        "urls": domain.get("urls") or {},
        "exposure": domain.get("modes") or {},
        "is_homepage": bool(doc.get("is_root_domain")),
        "repository": doc.get("repo_url"),
        "deploy": (
            {"branches": {e: BRANCHES[e] for e in environments if e in BRANCHES},
             "how": "git push a la rama del ambiente → el pipeline construye y publica la imagen → ArgoCD la despliega."}
            if has_repo else
            {"how": "Imagen oficial, sin repositorio ni pipeline: se despliega tal cual."}
        ),
        "variables": variables,
        "links": links,
        "local_steps": _local_steps(template_id, category),
        "rules": _contract_rules(category, port, health),
        "more": "platform_guide(topic='desarrollo-local') y platform_guide(topic='desplegar').",
    }


# ── Despacho ─────────────────────────────────────────────────────────────
async def call_tool(client: ApiClient, name: str, args: Dict[str, Any]) -> Any:
    args = args or {}

    # Entender
    if name == "list_apps":
        rows = [_app_summary(app) for app in await client.get("/apps")]
        if args.get("domain"):
            rows = [row for row in rows if row["domain"] == args["domain"]]
        if args.get("group"):
            rows = [row for row in rows if row["group"] == args["group"]]
        return {"apps": rows, "total": len(rows)}

    if name == "get_app":
        return _app_detail(await client.get(f"/apps/{_app(args)}"))

    if name == "app_health":
        app = _app(args)
        data = await client.get(f"/apps/{app}/status/full")
        argocd = data.get("argocd") or {}
        return {
            "app": app,
            "health": (argocd.get("health") or {}).get("status"),
            "synced": argocd.get("isSynced"),
            "per_env": {
                env: {"health": (value or {}).get("health", {}).get("status"), "exists": (value or {}).get("exists")}
                for env, value in (data.get("argocd_per_env") or {}).items()
            },
            "pipeline": (data.get("pipeline") or {}).get("result"),
            "diagnosis": data.get("diagnosis"),
        }

    if name == "diagnose_app":
        return await client.get(f"/apps/{_app(args)}/diagnosis", {"env": _env(args)})

    if name == "app_logs":
        app, env = _app(args), _env(args)
        lines = args.get("lines", 100)
        if isinstance(lines, bool) or not isinstance(lines, int) or not 1 <= lines <= 500:
            raise ToolError("lines va de 1 a 500.")
        data = await client.get(f"/apps/{app}/argocd/logs", {"env": env, "lines": lines})
        if data.get("error"):
            return {"app": app, "env": env, "error": mask(str(data["error"]))}
        return {"app": app, "env": env, "source": data.get("app_name"), "lines": _log_lines(data.get("logs") or "", lines)}

    if name == "app_env_var_names":
        return await client.get(f"/apps/{_app(args)}/env-vars", {"env": _env(args)})

    if name == "deploy_status":
        app = _app(args)
        doc = await client.get(f"/apps/{app}")
        operations = {key: doc[key] for key in OPERATIONS if doc.get(key)}
        try:
            entries = (await client.get("/logs", {"target": app, "limit": 8})).get("logs") or []
            activity: Optional[List[Dict[str, Any]]] = [_activity_entry(entry) for entry in entries]
        except ToolError:
            activity = None  # el token no ve la bitácora: el resto igual sirve
        health = None
        try:
            full = await client.get(f"/apps/{app}/status/full")
            health = {env: ((value or {}).get("health") or {}).get("status")
                      for env, value in (full.get("argocd_per_env") or {}).items()}
        except ToolError:
            pass
        status = doc.get("status")
        if status == "deploying" or _running(doc):
            hint = "Sigue en curso: vuelve a consultar en un minuto."
        elif status == "error":
            hint = "El alta falló: diagnose_app dice por qué."
        elif health and any(value != "Healthy" for value in health.values()):
            hint = "Desplegada, pero no todo está sano: usa diagnose_app en el ambiente que falla."
        else:
            hint = "Lista."
        return {
            "app": app,
            "status": status,
            "error": mask(str(doc["error"])) if doc.get("error") else None,
            "urls": (doc.get("domain") or {}).get("urls") or {},
            "health": health,
            "operations": operations,
            "recent_activity": activity,
            "hint": hint,
        }

    if name == "stack_status":
        run_id = str(args.get("run_id") or "")
        if not _OBJECT_ID.match(run_id):
            raise ToolError("run_id no es válido: usa el que devolvió launch_stack.")
        run = await client.get(f"/stacks/runs/{run_id}")
        components = [
            {key: component.get(key) for key in ("role", "name", "state", "url", "error") if component.get(key)}
            for component in run.get("components") or []
        ]
        state = run.get("state")
        hint = {
            "running": "Sigue en curso: cada pieza tarda unos minutos.",
            "succeeded": "Listo.",
            "failed": "Se detuvo en la pieza que falló: diagnose_app de esa pieza dice por qué.",
            "interrupted": "Se interrumpió: revisa las apps creadas con deploy_status.",
        }.get(state, "")
        return {"run_id": run_id, "stack": run.get("stack_name"), "base": run.get("base"), "state": state,
                "error": run.get("error"), "urls": run.get("urls"), "components": components, "hint": hint}

    if name == "list_domains":
        domains = await client.get("/domains")
        return {"domains": [
            {
                "fqdn": domain.get("fqdn"),
                "is_default": bool(domain.get("is_default")),
                "status": domain.get("status"),
                "apps": domain.get("apps_count"),
            }
            for domain in domains
        ]}

    if name == "list_templates":
        params = {"category": str(args["category"])} if args.get("category") else None
        templates = await client.get("/templates", params)
        return {"templates": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "category": item.get("category"),
                "description": item.get("description"),
                "status": item.get("status"),
                "port": item.get("port"),
                "creation": "imagen oficial" if (item.get("creation_modes") or []) == ["config-only"] else "repositorio con código",
                "custom": bool(item.get("is_custom")),
            }
            for item in templates
        ]}

    if name == "list_stacks":
        catalog_ = await client.get("/stacks/catalog")
        runs = await client.get("/stacks/runs", {"limit": 5})
        return {"stacks": catalog_.get("stacks", []), "recent_runs": runs.get("runs", [])}

    if name == "platform_status":
        version = await client.get("/core/version")
        updates = await client.get("/core/updates")
        health = await client.get("/system/health")
        return {
            "version": version,
            "updates_available": updates.get("available"),
            "pending_commits": len(updates.get("commits") or []),
            "health": health,
        }

    if name == "activity":
        target = _name(args["target"]) if args.get("target") else None
        return await client.get("/logs", {"limit": args.get("limit", 25), "category": args.get("category"), "target": target})

    # Crear
    if name == "create_app":
        app = _app(args)
        template = await client.get(f"/templates/{_catalog_id(args.get('template'), 'plantilla')}")
        database = await client.get(f"/apps/{_name(args['database'], 'base')}") if args.get("database") else None
        api = await client.get(f"/apps/{_name(args['api'], 'API')}") if args.get("api") else None
        domain_id = await _domain_id(client, args["domain"]) if args.get("domain") else None
        try:
            payload = app_blueprint.build(
                template, name=app, environments=_environments(args.get("environments")),
                exposure=args.get("exposure"), domain_id=domain_id, homepage=bool(args.get("homepage")),
                group=args.get("group"), description=str(args.get("description") or ""),
                database=database, api=api,
            )
        except app_blueprint.BlueprintError as exc:
            raise ToolError(str(exc))
        applied, result = await _plan_or_apply(client, "POST", "/apps", args, payload)
        if not applied:
            return result
        return {"applied": True, "app": result.get("name"), "status": result.get("status"),
                "next": f"Se está creando. Sigue el avance con deploy_status(name='{result.get('name')}'): tarda unos minutos."}

    if name == "launch_stack":
        base_name = str(args.get("base_name") or "")
        if not _BASE_NAME.match(base_name):
            raise ToolError("base_name: letras, dígitos, espacios y guiones (hasta 50).")
        body: Dict[str, Any] = {
            "stack_id": _catalog_id(args.get("stack"), "stack"),
            "name": base_name,
            "environments": _environments(args.get("environments")) or ["prod"],
            "homepage": bool(args.get("homepage")),
            "group": str(args["group"]) if args.get("group") else None,
            "description": str(args.get("description") or ""),
        }
        if args.get("domain"):
            body["domain_id"] = await _domain_id(client, args["domain"])
        applied, result = await _plan_or_apply(client, "POST", "/stacks", args, body)
        if not applied:
            return result
        run_id = result.get("run_id")
        return {
            "applied": True, "run_id": run_id, "state": result.get("state"),
            "components": [{key: c.get(key) for key in ("role", "name", "url")} for c in result.get("components") or []],
            "next": f"Sigue el avance con stack_status(run_id='{run_id}'): cada pieza tarda unos minutos.",
        }

    # Conectar
    if name == "link_apps":
        app, to = _app(args), _name(args.get("to"))
        body = {"to_app": to}
        if args.get("alias"):
            if not _ALIAS.match(str(args["alias"])):
                raise ToolError("alias: letras, dígitos y guion bajo, empezando por letra (se usa en mayúsculas).")
            body["alias"] = str(args["alias"]).upper()
        environments = _environments(args.get("environments"))
        if environments:
            body["environments"] = environments
        applied, result = await _plan_or_apply(client, "POST", f"/apps/{app}/links", args, body)
        if not applied:
            return result
        return {"applied": True, **{key: result.get(key) for key in ("app", "to", "kind", "alias", "environments", "message")}}

    if name == "unlink_apps":
        app, to = _app(args), _name(args.get("to"))
        applied, result = await _plan_or_apply(client, "DELETE", f"/apps/{app}/links/{to}", args)
        if not applied:
            return result
        return {"applied": True, **{key: result.get(key) for key in ("app", "to", "environments", "message")}}

    if name == "set_exposure":
        app = _app(args)
        per_env = args.get("per_env")
        if not isinstance(per_env, dict) or not per_env:
            raise ToolError("per_env debe ser un objeto como {\"prod\": \"public\"}.")
        clean: Dict[str, str] = {}
        for env, mode in per_env.items():
            if not _ENV.match(str(env)) or str(mode) not in catalog.EXPOSURE_MODES:
                raise ToolError(f"{env}: {mode} no vale. Modos: {', '.join(catalog.EXPOSURE_MODES)}.")
            clean[str(env)] = str(mode)
        applied, result = await _plan_or_apply(client, "POST", f"/apps/{app}/exposure", args, {"per_env": clean})
        if not applied:
            return result
        return {"applied": True, "app": app, "change": result.get("change"),
                "next": f"Corre en segundo plano: deploy_status(name='{app}') dice cuándo terminó y si las URLs responden."}

    if name == "attach_domain":
        app = _app(args)
        body = {"domain_id": await _domain_id(client, args.get("domain"))}
        applied, result = await _plan_or_apply(client, "POST", f"/apps/{app}/domain", args, body)
        if not applied:
            return result
        return {"applied": True, "app": app, "move": result.get("move"),
                "next": f"Corre en segundo plano: deploy_status(name='{app}') dice cuándo respondió la URL nueva."}

    if name == "set_homepage":
        app = _app(args)
        applied, result = await _plan_or_apply(client, "POST", f"/apps/{app}/homepage", args, {})
        if not applied:
            return result
        return {"applied": True, "app": app, "promotion": result.get("promotion"),
                "next": f"Corre en segundo plano: deploy_status(name='{app}') dice cuándo quedó en la raíz."}

    # Operar
    if name == "start_app":
        app, env = _app(args), _env(args)
        replicas = _replicas(args.get("replicas"), required=False)
        return await client.post(f"/apps/{app}/environments/{env}/start", {"replicas": replicas} if replicas else {})

    if name == "stop_app":
        app, env = _app(args), _env(args)
        return await client.post(f"/apps/{app}/environments/{env}/stop")

    if name == "scale_app":
        app, env = _app(args), _env(args)
        replicas = _replicas(args.get("replicas"), required=True)
        return await client.post(f"/apps/{app}/environments/{env}/scale", {"replicas": replicas})

    if name == "sync_app":
        return await client.post(f"/apps/{_app(args)}/argocd/sync")

    if name == "repair_db_bindings":
        return await client.post(f"/apps/{_app(args)}/bindings/repair")

    if name == "set_app_variable":
        app = _app(args)
        variable = str(args.get("variable") or "")
        if not _VARIABLE.match(variable):
            raise ToolError(f"'{variable}' no es un nombre de variable válido: mayúsculas, dígitos y guion bajo.")
        body = {key: args[key] for key in ("value", "generate", "overwrite", "environments") if args.get(key) is not None}
        return await client.put(f"/apps/{app}/variables/{variable}", body)

    # Guiar
    if name == "platform_guide":
        topic = str(args.get("topic") or guide.DEFAULT_TOPIC)
        if topic not in guide.TOPICS:
            raise ToolError(f"Tema desconocido. Temas: {', '.join(guide.topic_names())}.")
        return {"topic": topic, "title": guide.TOPICS[topic]["title"], "text": guide.text(topic),
                "other_topics": [name_ for name_ in guide.topic_names() if name_ != topic]}

    if name == "app_contract":
        return await _app_contract(client, _app(args), _env(args))

    raise ToolError(f"Herramienta desconocida: {name}")
