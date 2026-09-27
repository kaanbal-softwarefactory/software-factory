"""
Lo que hace cada herramienta del MCP
====================================

Cada herramienta llama a la API REST con la credencial de quien preguntó (ver
loopback.py): el permiso, el alcance del token y la bitácora son exactamente
los de la REST. Aquí solo se valida la forma de los argumentos y se resume la
respuesta para que el agente razone con lo necesario, no con el volcado crudo.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Protocol

from app.mcp.protocol import ToolError

_APP_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ENV = re.compile(r"^[a-z]{2,16}$")


class ApiClient(Protocol):
    async def get(self, path: str, params: Dict[str, Any] = None) -> Any: ...
    async def post(self, path: str, json: Dict[str, Any] = None) -> Any: ...
    async def put(self, path: str, json: Dict[str, Any] = None) -> Any: ...


def _app(args: Dict[str, Any]) -> str:
    name = str(args.get("name") or "")
    if not _APP_NAME.match(name):
        raise ToolError(f"'{name}' no es un nombre de app válido: usa el nombre interno que da list_apps.")
    return name


def _env(args: Dict[str, Any]) -> str:
    env = str(args.get("env") or "prod")
    if not _ENV.match(env):
        raise ToolError(f"'{env}' no es un ambiente válido (prod, staging, dev).")
    return env


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
    }


async def call_tool(client: ApiClient, name: str, args: Dict[str, Any]) -> Any:
    args = args or {}

    if name == "list_apps":
        rows = [_app_summary(app) for app in await client.get("/apps")]
        if args.get("domain"):
            rows = [row for row in rows if row["domain"] == args["domain"]]
        if args.get("group"):
            rows = [row for row in rows if row["group"] == args["group"]]
        return {"apps": rows, "total": len(rows)}

    if name == "get_app":
        return _app_summary(await client.get(f"/apps/{_app(args)}"))

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
        return await client.get(
            f"/apps/{_app(args)}/argocd/logs",
            {"env": _env(args), "lines": args.get("lines", 100)},
        )

    if name == "app_env_var_names":
        return await client.get(f"/apps/{_app(args)}/env-vars", {"env": _env(args)})

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

    if name == "list_stacks":
        catalog = await client.get("/stacks/catalog")
        runs = await client.get("/stacks/runs", {"limit": 5})
        return {"stacks": catalog.get("stacks", []), "recent_runs": runs.get("runs", [])}

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
        return await client.get("/logs", {"limit": args.get("limit", 25), "category": args.get("category")})

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

    raise ToolError(f"Herramienta desconocida: {name}")
