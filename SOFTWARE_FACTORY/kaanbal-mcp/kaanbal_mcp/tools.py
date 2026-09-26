"""
Herramientas que el agente puede usar sobre Kaanbal
===================================================

Casi todo es lectura: ver apps, su salud, sus logs, sus dominios y la bitácora.
Las dos únicas acciones son las que se pueden repetir sin riesgo —sincronizar con
ArgoCD y republicar los nombres de la base—, y solo funcionan si el token las
incluye.

Lo que NO existe a propósito: leer valores de secretos, crear o borrar apps,
tocar credenciales y actualizar el core. Eso se hace desde la consola, con una
persona mirando.

El esquema de argumentos sale de la firma de cada función en server.py; aquí se
declara para qué sirve cada una y qué permiso necesita el token (la API es quien
manda, esto es para poder explicarlo cuando falta).
"""

from __future__ import annotations

from typing import Any, Dict, List

from .client import KaanbalClient

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_apps",
        "description": "Lista las aplicaciones con su dominio, URL pública y estado. Punto de partida para casi todo.",
        "permission": "apps.apps.view",
    },
    {
        "name": "get_app",
        "description": "Detalle de una app: plantilla, ambientes, grupo, dominio y URLs.",
        "permission": "apps.apps.view",
    },
    {
        "name": "app_health",
        "description": (
            "Salud real de una app: estado en ArgoCD por ambiente y resultado del último pipeline. "
            "Lo primero que hay que mirar cuando algo falla."
        ),
        "permission": "apps.apps.view",
    },
    {
        "name": "app_logs",
        "description": (
            "Últimas líneas de log de los pods de una app. Aquí aparece el error concreto: "
            "traceback, variable faltante, imagen que no baja."
        ),
        "permission": "apps.apps.diagnose",
    },
    {
        "name": "app_env_var_names",
        "description": (
            "NOMBRES de las variables de entorno que recibe una app (nunca sus valores). "
            "Sirve para ver si la app pide una variable que nadie le inyecta, que es la causa "
            "más común de que un backend no arranque."
        ),
        "permission": "apps.apps.diagnose",
    },
    {
        "name": "list_domains",
        "description": "Dominios registrados, cuál es el de la instalación y cuántas apps usa cada uno.",
        "permission": "domains.domains.view",
    },
    {
        "name": "list_stacks",
        "description": "Catálogo de stacks disponibles y el estado de los últimos lanzamientos.",
        "permission": "stacks.catalog.view",
    },
    {
        "name": "platform_status",
        "description": "Estado general: versión del core, si hay actualizaciones, salud del sistema y Vault.",
        "permission": "system.health.view",
    },
    {
        "name": "activity",
        "description": (
            "Bitácora reciente: quién hizo qué y cuándo. Útil para saber qué cambió antes de que "
            "algo se rompiera."
        ),
        "permission": "logs.records.view",
    },
    {
        "name": "sync_app",
        "description": "ACCIÓN: pide a ArgoCD que sincronice una app con su manifiesto. Seguro y repetible.",
        "permission": "apps.apps.deploy",
    },
    {
        "name": "repair_db_bindings",
        "description": (
            "ACCIÓN: republica los nombres estándar de la base vinculada (MONGO_URI, DATABASE_URL…) "
            "en una app ya desplegada. Idempotente: si ya los tiene, no cambia nada."
        ),
        "permission": "apps.apps.deploy",
    },
]

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _app_summary(app: Dict[str, Any]) -> Dict[str, Any]:
    """Una app en pocas líneas: lo que el agente necesita para razonar."""
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


async def call_tool(client: KaanbalClient, name: str, arguments: Dict[str, Any]) -> Any:
    """Ejecutar una herramienta. Devuelve datos ya resumidos, no el volcado crudo."""
    args = arguments or {}

    if name == "list_apps":
        apps = await client.get("/apps")
        rows = [_app_summary(app) for app in apps]
        if args.get("domain"):
            rows = [row for row in rows if row["domain"] == args["domain"]]
        if args.get("group"):
            rows = [row for row in rows if row["group"] == args["group"]]
        return {"apps": rows, "total": len(rows)}

    if name == "get_app":
        return _app_summary(await client.get(f"/apps/{args['name']}"))

    if name == "app_health":
        data = await client.get(f"/apps/{args['name']}/status/full")
        argocd = data.get("argocd") or {}
        return {
            "app": args["name"],
            "health": (argocd.get("health") or {}).get("status"),
            "synced": argocd.get("isSynced"),
            "per_env": {
                env: {"health": (value or {}).get("health", {}).get("status"), "exists": (value or {}).get("exists")}
                for env, value in (data.get("argocd_per_env") or {}).items()
            },
            "pipeline": (data.get("pipeline") or {}).get("result"),
            "diagnosis": data.get("diagnosis"),
        }

    if name == "app_logs":
        return await client.get(
            f"/apps/{args['name']}/argocd/logs",
            {"env": args.get("env", "prod"), "lines": args.get("lines", 100)},
        )

    if name == "app_env_var_names":
        return await client.get(f"/apps/{args['name']}/env-vars", {"env": args.get("env", "prod")})

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
        return await client.post(f"/apps/{args['name']}/argocd/sync")

    if name == "repair_db_bindings":
        return await client.post(f"/apps/{args['name']}/bindings/repair")

    raise ValueError(f"Herramienta desconocida: {name}")
