"""
El inventario como recursos del MCP
===================================

Además de herramientas, el agente puede adjuntar a su contexto el estado de la
plataforma como recursos (en Claude Code, con @): la lista de apps, el detalle
de una app y su contrato. Se leen con la credencial de quien pregunta, igual que
las herramientas, así que cada token ve solo lo que puede ver.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

PREFIX = "kaanbal://inventario/"
APPS = PREFIX + "apps"
APP_TEMPLATE = PREFIX + "apps/{name}"
CONTRACT_TEMPLATE = PREFIX + "apps/{name}/contrato"


def resources() -> List[Dict[str, str]]:
    return [{
        "uri": APPS, "name": "apps", "title": "Inventario de apps",
        "description": "Todas las apps con dominio, URLs, grupo, estado y operaciones en curso.",
        "mimeType": "application/json",
    }]


def templates() -> List[Dict[str, str]]:
    return [
        {"uriTemplate": APP_TEMPLATE, "name": "app", "title": "Detalle de una app",
         "description": "Plantilla, ambientes, exposición, grupo, dominio, URLs y operaciones en curso.",
         "mimeType": "application/json"},
        {"uriTemplate": CONTRACT_TEMPLATE, "name": "contrato", "title": "Contrato de una app",
         "description": "Puerto, salud, variables (solo nombres), vínculos, ramas y pasos de desarrollo local.",
         "mimeType": "application/json"},
    ]


async def read(client: Any, uri: str) -> Dict[str, str]:
    """KeyError si la URI no es del inventario; ToolError si la API dice que no."""
    from app.mcp.tools import call_tool

    rest = uri[len(PREFIX):]
    parts = rest.split("/")
    if rest == "apps":
        data = await call_tool(client, "list_apps", {})
    elif len(parts) == 2 and parts[0] == "apps" and parts[1]:
        data = await call_tool(client, "get_app", {"name": parts[1]})
    elif len(parts) == 3 and parts[0] == "apps" and parts[2] == "contrato":
        data = await call_tool(client, "app_contract", {"name": parts[1]})
    else:
        raise KeyError(uri)
    return {"uri": uri, "mimeType": "application/json",
            "text": json.dumps(data, ensure_ascii=False, indent=2, default=str)}
