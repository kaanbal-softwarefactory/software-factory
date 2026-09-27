"""
Puente stdio → MCP remoto de Kaanbal
===================================

Kaanbal sirve su MCP en la propia API (POST /mcp): Claude Code, Cursor, Codex y
cualquier cliente con soporte HTTP se conectan con la URL y un token, sin
instalar nada. Este puente es solo para clientes que únicamente saben lanzar un
proceso y hablarle por stdio: reenvía cada mensaje, tal cual, a la API.

Las herramientas viven en la plataforma; aquí no hay ninguna.

    KAANBAL_URL=https://kaanbal-api.example.com KAANBAL_TOKEN=kbl_... python -m kaanbal_mcp
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

import httpx

TIMEOUT_SECONDS = 180.0


class BridgeConfigError(RuntimeError):
    pass


def endpoint(base_url: str) -> str:
    """URL del MCP remoto a partir de la de la API (acepta también la del MCP)."""
    url = (base_url or "").strip().rstrip("/")
    return url if url.endswith("/mcp") else f"{url}/mcp"


def config_from_env(env=os.environ) -> tuple:
    url, token = env.get("KAANBAL_URL", ""), env.get("KAANBAL_TOKEN", "")
    if not url:
        raise BridgeConfigError("Falta KAANBAL_URL (por ejemplo https://kaanbal-api.example.com).")
    if not token:
        raise BridgeConfigError("Falta KAANBAL_TOKEN. Créalo en la consola, en Acceso → Tokens.")
    return endpoint(url), token


def _error(message: Any, text: str) -> Optional[str]:
    """Error JSON-RPC para una petición; las notificaciones no llevan respuesta."""
    if not isinstance(message, dict) or "id" not in message or "method" not in message:
        return None
    return json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32000, "message": text}},
                      ensure_ascii=False)


class Bridge:
    def __init__(self, url: str, token: str, http: Optional[httpx.Client] = None):
        self.url = url
        self.token = token
        self.http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
        self.version: Optional[str] = None

    def forward(self, line: str) -> Optional[str]:
        """Un mensaje del cliente → la respuesta que hay que escribirle (o None)."""
        try:
            message = json.loads(line)
        except ValueError:
            return json.dumps({"jsonrpc": "2.0", "id": None,
                               "error": {"code": -32700, "message": "El mensaje no es JSON válido."}})

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        try:
            response = self.http.post(self.url, content=line.encode("utf-8"), headers=headers)
        except httpx.HTTPError as exc:
            return _error(message, f"No se pudo conectar con {self.url}: {exc}")

        if response.status_code == 202:
            return None
        if response.status_code == 401:
            return _error(message, "El token no es válido o fue revocado. Crea uno nuevo en Acceso → Tokens.")
        if response.status_code >= 400 and "application/json" not in response.headers.get("content-type", ""):
            return _error(message, f"La plataforma respondió {response.status_code}.")
        try:
            answer = response.json()
        except ValueError:
            return _error(message, "La plataforma devolvió una respuesta que no es JSON.")
        if response.status_code >= 400 and isinstance(answer, dict) and "jsonrpc" not in answer:
            return _error(message, str(answer.get("detail") or f"La plataforma respondió {response.status_code}."))

        if isinstance(message, dict) and message.get("method") == "initialize" and isinstance(answer, dict):
            self.version = (answer.get("result") or {}).get("protocolVersion") or self.version
        return json.dumps(answer, ensure_ascii=False)


def main() -> None:
    try:
        url, token = config_from_env()
    except BridgeConfigError as exc:
        print(f"kaanbal-mcp: {exc}", file=sys.stderr)
        sys.exit(2)

    bridge = Bridge(url, token)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        answer = bridge.forward(line)
        if answer is not None:
            sys.stdout.write(answer + "\n")
            sys.stdout.flush()
