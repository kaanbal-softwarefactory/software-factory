"""
Cliente de la API de Kaanbal para el MCP
========================================

Una sola credencial: el token personal de quien lo configuró. El token decide
qué puede ver el agente, no este código — si el token no trae un permiso, la
API responde 403 y aquí se traduce a un mensaje que dice qué falta y dónde
arreglarlo.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

DEFAULT_TIMEOUT = 30.0


class KaanbalError(RuntimeError):
    """Error que el agente puede leer y explicarle a la persona."""


class KaanbalClient:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or os.getenv("KAANBAL_URL", "")).rstrip("/")
        self.token = token or os.getenv("KAANBAL_TOKEN", "")
        self.timeout = timeout
        if not self.base_url:
            raise KaanbalError("Falta KAANBAL_URL (por ejemplo https://kaanbal-api.example.com).")
        if not self.token:
            raise KaanbalError("Falta KAANBAL_TOKEN. Créalo en la consola, en Acceso → Tokens.")

    async def request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}/api/v1{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

        if response.status_code == 401:
            raise KaanbalError(
                "El token no es válido o fue revocado. Crea uno nuevo en la consola, en Acceso → Tokens."
            )
        if response.status_code == 403:
            detail = _detail(response)
            raise KaanbalError(
                f"{detail} Si hace falta, crea otro token con ese alcance en Acceso → Tokens."
            )
        if response.status_code == 404:
            raise KaanbalError(_detail(response) or "No existe eso en esta plataforma.")
        if response.status_code >= 400:
            raise KaanbalError(f"La API respondió {response.status_code}: {_detail(response)}")

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text[:4000]}

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("GET", path, params={k: v for k, v in (params or {}).items() if v is not None})

    async def post(self, path: str, json: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("POST", path, json=json or {})


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail or "")
