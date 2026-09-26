"""
Servidor MCP de Kaanbal
=======================

Expone la plataforma a un agente (Claude Code, Codex, Cursor) por stdio. Corre
en la máquina de cada quien y se autentica con **su** token personal: lo que el
agente ve es exactamente lo que esa persona puede ver, ni más.

    KAANBAL_URL=https://kaanbal-api.example.com \
    KAANBAL_TOKEN=kbl_... \
    python -m kaanbal_mcp

Cada herramienta es una función con tipos: de ahí sale el esquema que ve el
agente. La lógica vive en tools.py (probada sin red); aquí solo se conecta.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from mcp.server.mcpserver import MCPServer

from .client import KaanbalClient, KaanbalError
from .tools import TOOLS_BY_NAME, call_tool

logging.basicConfig(level=os.getenv("KAANBAL_MCP_LOG", "INFO"))
logger = logging.getLogger("kaanbal-mcp")

server = MCPServer(
    "kaanbal",
    instructions=(
        "Kaanbal es la plataforma donde viven estas aplicaciones. Para diagnosticar algo que "
        "falla: app_health primero, luego app_logs, y app_env_var_names si el error menciona una "
        "variable de entorno. Nunca vas a poder leer el valor de un secreto, y solo dos "
        "herramientas cambian algo (sync_app y repair_db_bindings)."
    ),
)


async def _run(_tool: str, /, **arguments: Any) -> str:
    """Ejecutar una herramienta y devolver JSON legible (o el error, explicado).

    El nombre de la herramienta va como posicional puro (`/`): varias herramientas
    reciben un argumento llamado `name`, y con un parámetro normal chocaban.
    """
    try:
        client = KaanbalClient()
        result = await call_tool(client, _tool, {k: v for k, v in arguments.items() if v is not None})
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except KaanbalError as exc:
        # El agente necesita leer el motivo, no un stacktrace.
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo en la herramienta %s", _tool)
        return json.dumps({"error": f"No se pudo ejecutar {_tool}: {exc}"}, ensure_ascii=False)


async def list_apps(domain: Optional[str] = None, group: Optional[str] = None) -> str:
    return await _run("list_apps", domain=domain, group=group)


async def get_app(name: str) -> str:
    return await _run("get_app", name=name)


async def app_health(name: str) -> str:
    return await _run("app_health", name=name)


async def app_logs(name: str, env: str = "prod", lines: int = 100) -> str:
    return await _run("app_logs", name=name, env=env, lines=lines)


async def app_env_var_names(name: str, env: str = "prod") -> str:
    return await _run("app_env_var_names", name=name, env=env)


async def list_domains() -> str:
    return await _run("list_domains")


async def list_stacks() -> str:
    return await _run("list_stacks")


async def platform_status() -> str:
    return await _run("platform_status")


async def activity(limit: int = 25, category: Optional[str] = None) -> str:
    return await _run("activity", limit=limit, category=category)


async def sync_app(name: str) -> str:
    return await _run("sync_app", name=name)


async def repair_db_bindings(name: str) -> str:
    return await _run("repair_db_bindings", name=name)


HANDLERS: Dict[str, Any] = {
    "list_apps": list_apps,
    "get_app": get_app,
    "app_health": app_health,
    "app_logs": app_logs,
    "app_env_var_names": app_env_var_names,
    "list_domains": list_domains,
    "list_stacks": list_stacks,
    "platform_status": platform_status,
    "activity": activity,
    "sync_app": sync_app,
    "repair_db_bindings": repair_db_bindings,
}


def register(target: MCPServer) -> None:
    """Registrar el catálogo. El permiso va en la descripción para que el agente
    pueda explicar qué falta cuando la API responde que no."""
    for name, handler in HANDLERS.items():
        spec = TOOLS_BY_NAME[name]
        target.add_tool(
            handler,
            name=name,
            description=f"{spec['description']} (permiso del token: {spec['permission']})",
        )


register(server)


def run() -> None:
    server.run("stdio")


if __name__ == "__main__":
    run()
