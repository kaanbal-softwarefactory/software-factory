"""
Middleware de control de acceso
===============================

Autentica (sesión o token personal) y comprueba el permiso que exige el
endpoint, según el catálogo de app/services/permissions.py.

Va en un middleware y no en cada router a propósito: así un endpoint nuevo no
puede olvidarse de pedir permiso. Si no tiene regla en el catálogo, se bloquea
y el error dice exactamente qué falta agregar.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import get_db
from app.defaults import JWT_ALGORITHM
from app.services import access, access_store
from app.services import permissions as perms

logger = logging.getLogger(__name__)

# La ventana de instalación se consulta muy seguido; basta con revisarla
# cada pocos segundos (una vez que hay cuentas, ya no vuelve a abrirse).
_BOOTSTRAP_CACHE = {"checked_at": 0.0, "open": False}
_BOOTSTRAP_TTL_SECONDS = 15


async def _bootstrap_window_open() -> bool:
    """¿La plataforma todavía no tiene ninguna cuenta?"""
    if _BOOTSTRAP_CACHE["open"] is False and _BOOTSTRAP_CACHE["checked_at"] > 0:
        # Ya se cerró: no vuelve a abrirse mientras la API siga viva.
        if time.monotonic() - _BOOTSTRAP_CACHE["checked_at"] < _BOOTSTRAP_TTL_SECONDS:
            return False
    try:
        is_open = await access_store.count_users() == 0
    except Exception:  # sin base todavía: se comporta como instalación nueva
        is_open = True
    _BOOTSTRAP_CACHE.update({"checked_at": time.monotonic(), "open": is_open})
    return is_open


def _bearer(request) -> Optional[str]:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def _principal_from_jwt(token: str) -> Optional[access.Principal]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = await get_db()[access_store.USERS].find_one({"username": username})
    if not user or user.get("disabled"):
        return None
    return await access_store.principal_from_user(user)


async def authenticate(request) -> Optional[access.Principal]:
    """Sesión de la consola o token personal; ambos llegan como Bearer."""
    token = _bearer(request)
    if not token:
        return None
    if access.looks_like_token(token):
        return await access_store.principal_from_token(token)
    return await _principal_from_jwt(token)


def _deny(status_code: int, detail: str, **extra) -> JSONResponse:
    return JSONResponse({"detail": detail, **extra}, status_code=status_code)


class AccessControlMiddleware(BaseHTTPMiddleware):
    """Autentica y autoriza cada petición a la API."""

    async def dispatch(self, request, call_next):
        method = request.method.upper()
        path = perms.normalize_path(request.url.path)

        if method == "OPTIONS" or perms.is_public(method, path):
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Instalación: abierta solo mientras no existe ninguna cuenta.
        if perms.is_bootstrap(method, path) and await _bootstrap_window_open():
            return await call_next(request)

        principal = await authenticate(request)
        if principal is None:
            return _deny(401, "Inicia sesión para continuar.", code="not_authenticated")

        has_rule, permission = perms.required_permission(method, path)
        if not has_rule:
            # Fail-closed: preferimos un endpoint inaccesible a uno abierto por olvido.
            logger.error("Endpoint sin regla ACL: %s %s", method, path)
            return _deny(
                403,
                f"{method} {path} no tiene regla de acceso declarada. "
                "Agrégala en app/services/permissions.py antes de usarla.",
                code="acl_rule_missing",
            )

        if not principal.can(permission):
            detail = f"Tu cuenta no tiene el permiso '{permission}'."
            if principal.via_token:
                detail = (
                    f"El token '{principal.token_name}' no incluye el permiso '{permission}'. "
                    "Crea uno nuevo con ese alcance o usa tu sesión."
                )
            return _deny(403, detail, code="permission_denied", permission=permission)

        request.state.principal = principal
        return await call_next(request)
