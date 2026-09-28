"""
La API llamándose a sí misma, con la credencial de quien habló con el MCP
=======================================================================

Las herramientas del MCP no tocan la base ni el clúster directamente: llaman a
los mismos endpoints REST que usa la consola, en proceso (sin red), con el
mismo encabezado Authorization que trajo la petición al MCP. Así el control de
acceso, el alcance del token y la bitácora son los de siempre, sin duplicarlos.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from app.mcp.protocol import ToolError

TIMEOUT_SECONDS = 180.0


class LoopbackClient:
    def __init__(self, app: Any, authorization: str, *, timeout: float = TIMEOUT_SECONDS):
        self.app = app
        self.authorization = authorization
        self.timeout = timeout

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://kaanbal-api", timeout=self.timeout) as client:
            response = await client.request(
                method, f"/api/v1{path}", headers={"Authorization": self.authorization}, **kwargs,
            )
        return unwrap(response)

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("GET", path, params={k: v for k, v in (params or {}).items() if v is not None})

    async def post(self, path: str, json: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("POST", path, json=json or {})

    async def put(self, path: str, json: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("PUT", path, json=json or {})


def unwrap(response: httpx.Response) -> Any:
    """La respuesta REST como datos, o un error que el agente pueda explicarle a la persona."""
    if response.status_code == 401:
        raise ToolError("El token no es válido o fue revocado. Crea uno nuevo en la consola, en Acceso → Tokens.")
    if response.status_code == 403:
        raise ToolError(f"{_detail(response)} Si hace falta, crea otro token con ese alcance en Acceso → Tokens.")
    if response.status_code == 404:
        raise ToolError(_detail(response) or "No existe eso en esta plataforma.")
    if response.status_code in (400, 409, 422):
        # Rechazos con motivo (un plan que choca, un nombre tomado): el detalle ya es para la persona.
        raise ToolError(_detail(response) or f"La API rechazó la petición ({response.status_code}).")
    if response.status_code >= 400:
        raise ToolError(f"La API respondió {response.status_code}: {_detail(response)}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:4000]}


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail or "")
