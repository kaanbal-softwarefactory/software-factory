"""
Protocolo MCP sobre HTTP, sin estado
===================================

El MCP de Kaanbal vive dentro de la API: JSON-RPC 2.0 por POST /mcp, el
transporte "Streamable HTTP" del estándar. Solo expone herramientas, así que no
necesita sesiones ni un canal SSE: cada petición trae su token, se responde en
JSON y no queda nada guardado.

No usa el SDK oficial porque el SDK exige versiones de pydantic y starlette que
la API no tiene; el test de compatibilidad del paquete kaanbal-mcp corre el
cliente oficial contra este módulo. Por eso aquí no se importa nada de `app.*`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Union

logger = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LATEST_VERSION = SUPPORTED_VERSIONS[0]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

ToolRunner = Callable[[str, Dict[str, Any]], Awaitable[Any]]
Response = Union[Dict[str, Any], List[Dict[str, Any]]]


class ToolError(Exception):
    """Una herramienta no pudo hacer su trabajo. El agente lee el mensaje."""


def error_response(message_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _result(message_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def negotiate(requested: Any) -> str:
    """La versión que pide el cliente si la hablamos; si no, la más nueva que conocemos."""
    return requested if requested in SUPPORTED_VERSIONS else LATEST_VERSION


def is_supported_version(value: Optional[str]) -> bool:
    return value is None or value in SUPPORTED_VERSIONS


def tool_result(payload: Any, *, is_error: bool = False) -> Dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _missing_arguments(tool: Mapping[str, Any], arguments: Mapping[str, Any]) -> List[str]:
    required = (tool.get("inputSchema") or {}).get("required") or []
    return [name for name in required if arguments.get(name) in (None, "")]


async def handle_message(
    message: Any,
    *,
    server_info: Mapping[str, Any],
    instructions: str,
    tools: Sequence[Mapping[str, Any]],
    run_tool: ToolRunner,
) -> Optional[Dict[str, Any]]:
    """Responder un mensaje JSON-RPC. None cuando no lleva respuesta (notificaciones)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        message_id = message.get("id") if isinstance(message, dict) else None
        return error_response(message_id, INVALID_REQUEST, "Se esperaba un mensaje JSON-RPC 2.0.")

    method = message.get("method")
    if method is None or "id" not in message:
        # Notificaciones (notifications/initialized…) y respuestas del cliente: este
        # servidor nunca le pide nada al cliente, así que no hay nada que contestar.
        return None

    message_id = message["id"]
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return error_response(message_id, INVALID_PARAMS, "params debe ser un objeto.")

    if method == "initialize":
        return _result(message_id, {
            "protocolVersion": negotiate(params.get("protocolVersion")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": dict(server_info),
            "instructions": instructions,
        })
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(message_id, {"tools": [dict(tool) for tool in tools]})
    if method == "tools/call":
        return await _call_tool(message_id, params, tools, run_tool)
    return error_response(message_id, METHOD_NOT_FOUND, f"Método no soportado: {method}")


async def _call_tool(message_id: Any, params: Dict[str, Any], tools: Sequence[Mapping[str, Any]], run_tool: ToolRunner):
    name = params.get("name")
    tool = next((t for t in tools if t.get("name") == name), None)
    if tool is None:
        return error_response(message_id, INVALID_PARAMS, f"Herramienta desconocida: {name}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return error_response(message_id, INVALID_PARAMS, "arguments debe ser un objeto.")
    missing = _missing_arguments(tool, arguments)
    if missing:
        return error_response(message_id, INVALID_PARAMS, f"{name} necesita: {', '.join(missing)}")

    try:
        payload = await run_tool(name, arguments)
    except ToolError as exc:
        return _result(message_id, tool_result(str(exc), is_error=True))
    except Exception:  # noqa: BLE001 — un fallo de una herramienta no tumba la conexión
        logger.exception("La herramienta MCP %s falló", name)
        return _result(message_id, tool_result(f"No se pudo ejecutar {name}. Revisa la bitácora de la API.", is_error=True))
    return _result(message_id, tool_result(payload))


async def handle_body(raw: bytes, **kwargs: Any) -> Optional[Response]:
    """Cuerpo HTTP completo → respuesta. Acepta lotes (los pide el protocolo 2025-03-26)."""
    try:
        message = json.loads(raw or b"")
    except (ValueError, UnicodeDecodeError):
        return error_response(None, PARSE_ERROR, "El cuerpo no es JSON válido.")

    if isinstance(message, list):
        if not message:
            return error_response(None, INVALID_REQUEST, "El lote está vacío.")
        responses = [await handle_message(item, **kwargs) for item in message]
        answered = [response for response in responses if response is not None]
        return answered or None
    return await handle_message(message, **kwargs)
