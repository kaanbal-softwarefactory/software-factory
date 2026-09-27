"""
Herramientas del MCP de Kaanbal
===============================

Casi todo es lectura. Tres herramientas cambian algo, y ninguna puede leer el
valor de un secreto: sincronizar con ArgoCD, republicar los nombres estándar de
la base y agregar una variable de entorno que le falta a una app.

Lo que no existe a propósito: crear o borrar apps, tocar las credenciales de la
plataforma y actualizar el core. Eso se hace desde la consola, con una persona
mirando.

Cada herramienta declara el permiso que exige la API; el cliente lo ve en la
descripción para poder explicar qué le falta al token cuando la API dice que no.
Este módulo no importa nada de `app.*`: el test de compatibilidad lo carga solo.
"""

from __future__ import annotations

from typing import Any, Dict, List

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
SAFE_ACTION = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
CONFIG_ACTION = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}

_APP = {"type": "string", "description": "Nombre interno de la app (el que aparece en list_apps)."}
_ENV = {"type": "string", "description": "Ambiente: prod, staging o dev. Por defecto prod.", "default": "prod"}


def _schema(properties: Dict[str, Any] = None, required: List[str] = ()) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = list(required)
    return schema


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_apps",
        "title": "Listar apps",
        "description": "Lista las aplicaciones con su dominio, URL pública y estado. Punto de partida para casi todo.",
        "permission": "apps.apps.view",
        "inputSchema": _schema({
            "domain": {"type": "string", "description": "Solo las apps de este dominio."},
            "group": {"type": "string", "description": "Solo las apps de este grupo."},
        }),
        "annotations": READ_ONLY,
    },
    {
        "name": "get_app",
        "title": "Detalle de una app",
        "description": "Detalle de una app: plantilla, ambientes, grupo, dominio y URLs.",
        "permission": "apps.apps.view",
        "inputSchema": _schema({"name": _APP}, ["name"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "app_health",
        "title": "Salud de una app",
        "description": "Estado en ArgoCD por ambiente y resultado del último pipeline.",
        "permission": "apps.apps.view",
        "inputSchema": _schema({"name": _APP}, ["name"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "diagnose_app",
        "title": "Diagnosticar una app",
        "description": (
            "Por qué una app no arranca o no responde, en lenguaje simple: variable que falta, "
            "base que rechaza las credenciales, versión nueva atascada, imagen que no baja, memoria, "
            "sonda de salud rechazada… Con la evidencia (sin secretos) y la acción que lo arregla. "
            "Empieza por aquí cuando algo falla."
        ),
        "permission": "apps.apps.diagnose",
        "inputSchema": _schema({"name": _APP, "env": _ENV}, ["name"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "app_logs",
        "title": "Logs de una app",
        "description": "Últimas líneas de log de los pods de una app: traceback, variable faltante, imagen que no baja.",
        "permission": "apps.apps.diagnose",
        "inputSchema": _schema({
            "name": _APP,
            "env": _ENV,
            "lines": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        }, ["name"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "app_env_var_names",
        "title": "Variables de una app (solo nombres)",
        "description": (
            "NOMBRES de las variables de entorno que recibe una app, nunca sus valores. Sirve para ver "
            "si la app pide una variable que nadie le inyecta."
        ),
        "permission": "apps.apps.diagnose",
        "inputSchema": _schema({"name": _APP, "env": _ENV}, ["name"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "list_domains",
        "title": "Dominios",
        "description": "Dominios registrados, cuál es el de la instalación y cuántas apps usa cada uno.",
        "permission": "domains.domains.view",
        "inputSchema": _schema(),
        "annotations": READ_ONLY,
    },
    {
        "name": "list_stacks",
        "title": "Stacks",
        "description": "Catálogo de stacks disponibles y el estado de los últimos lanzamientos.",
        "permission": "stacks.catalog.view",
        "inputSchema": _schema(),
        "annotations": READ_ONLY,
    },
    {
        "name": "platform_status",
        "title": "Estado de la plataforma",
        "description": "Versión del core, si hay actualizaciones, salud del sistema y Vault.",
        "permission": "system.health.view",
        "inputSchema": _schema(),
        "annotations": READ_ONLY,
    },
    {
        "name": "activity",
        "title": "Bitácora",
        "description": "Quién hizo qué y cuándo. Útil para saber qué cambió antes de que algo se rompiera.",
        "permission": "logs.records.view",
        "inputSchema": _schema({
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
            "category": {"type": "string", "description": "Filtrar por categoría (app, auth, system…)."},
        }),
        "annotations": READ_ONLY,
    },
    {
        "name": "sync_app",
        "title": "Sincronizar con ArgoCD",
        "description": "ACCIÓN: pide a ArgoCD que sincronice una app con su manifiesto. Seguro y repetible.",
        "permission": "apps.apps.deploy",
        "inputSchema": _schema({"name": _APP}, ["name"]),
        "annotations": SAFE_ACTION,
    },
    {
        "name": "repair_db_bindings",
        "title": "Republicar la conexión a la base",
        "description": (
            "ACCIÓN: republica los nombres estándar de la base vinculada (MONGO_URI, DATABASE_URL…) en una "
            "app ya desplegada. Idempotente: si ya los tiene, no cambia nada."
        ),
        "permission": "apps.apps.deploy",
        "inputSchema": _schema({"name": _APP}, ["name"]),
        "annotations": SAFE_ACTION,
    },
    {
        "name": "set_app_variable",
        "title": "Agregar una variable a una app",
        "description": (
            "ACCIÓN: agrega a una app una variable de entorno que le falta (por ejemplo ADMIN_PASSWORD). "
            "Con generate=true la plataforma crea un valor aleatorio seguro que nadie ve. No pisa una "
            "variable existente salvo overwrite=true, y nunca toca las que gestiona la plataforma "
            "(la conexión a la base). La app se reinicia sola con la variable nueva."
        ),
        "permission": "apps.variables.manage",
        "inputSchema": _schema({
            "name": _APP,
            "variable": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,63}$", "description": "Nombre de la variable, en mayúsculas."},
            "value": {"type": "string", "description": "Valor. Omítelo y usa generate=true para contraseñas o claves."},
            "generate": {"type": "boolean", "description": "Generar un valor aleatorio seguro.", "default": False},
            "overwrite": {"type": "boolean", "description": "Reemplazar el valor si la variable ya existe.", "default": False},
            "environments": {"type": "array", "items": {"type": "string"}, "description": "Por defecto, todos los de la app."},
        }, ["name", "variable"]),
        "annotations": CONFIG_ACTION,
    },
]

TOOLS_BY_NAME: Dict[str, Dict[str, Any]] = {tool["name"]: tool for tool in TOOLS}


def definitions() -> List[Dict[str, Any]]:
    """Lo que ve el cliente en tools/list."""
    return [
        {
            "name": tool["name"],
            "title": tool["title"],
            "description": f"{tool['description']} (permiso del token: {tool['permission']})",
            "inputSchema": tool["inputSchema"],
            "annotations": {"title": tool["title"], **tool["annotations"]},
        }
        for tool in TOOLS
    ]
