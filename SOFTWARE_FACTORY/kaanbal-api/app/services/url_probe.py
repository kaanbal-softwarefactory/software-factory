"""
¿Responde la URL pública y cuándo vence su certificado?
======================================================

Lo que ve quien abre la app desde internet: código HTTP, tiempo de respuesta y
el certificado TLS (quién lo emite y cuántos días le quedan). Solo se prueban
las URLs que la plataforma le asignó a la app: el endpoint no es un proxy para
llegar a cualquier host desde dentro del clúster.
"""

from __future__ import annotations

import asyncio
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

TIMEOUT_SECONDS = 10.0
CERT_WARNING_DAYS = 14


def tls_view(cert: Optional[Mapping[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    """El certificado en términos útiles. Puro: lo prueba el test."""
    if not cert or not cert.get("notAfter"):
        return None
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc)
    issuer = dict(item[0] for item in cert.get("issuer") or () if item)
    days = (expires - now).days
    return {"expires_at": expires.isoformat(), "days_left": days,
            "issuer": issuer.get("organizationName") or issuer.get("commonName"),
            "warning": days < CERT_WARNING_DAYS}


def verdict(result: Mapping[str, Any]) -> str:
    if result.get("error"):
        return f"No responde: {result['error']}"
    status = result.get("status") or 0
    tls = result.get("tls") or {}
    if status >= 500:
        text = f"Responde {status}: la app está caída o falla al atender."
    elif status >= 400:
        text = f"Responde {status}: el servidor contesta, pero la ruta no existe o pide acceso."
    else:
        text = f"Responde {status} en {result.get('latency_ms')} ms."
    if tls.get("warning"):
        text += f" El certificado vence en {tls['days_left']} días."
    return text


async def _certificate(host: str, port: int) -> Optional[Dict[str, Any]]:
    context = ssl.create_default_context()
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, ssl=context, server_hostname=host),
                                            TIMEOUT_SECONDS)
    try:
        return writer.get_extra_info("ssl_object").getpeercert()
    finally:
        writer.close()


async def probe(url: str) -> Dict[str, Any]:
    import httpx

    parsed = urlparse(url)
    result: Dict[str, Any] = {"url": url}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "kaanbal-probe"})
        result.update(status=response.status_code, latency_ms=round((time.monotonic() - started) * 1000),
                      final_url=str(response.url) if str(response.url) != url else None)
    except httpx.HTTPError as exc:
        result["error"] = type(exc).__name__
    if parsed.scheme == "https" and parsed.hostname:
        try:
            result["tls"] = tls_view(await _certificate(parsed.hostname, parsed.port or 443), datetime.now(timezone.utc))
        except (OSError, asyncio.TimeoutError, ssl.SSLError) as exc:
            result["tls"] = {"error": type(exc).__name__}
    result["ok"] = not result.get("error") and (result.get("status") or 0) < 400
    result["verdict"] = verdict(result)
    return {key: value for key, value in result.items() if value is not None}
