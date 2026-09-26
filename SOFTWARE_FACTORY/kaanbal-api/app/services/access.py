"""
Quién es quién y qué puede hacer
================================

Tres piezas, en orden de confianza:

1. **Roles** — un conjunto de permisos con nombre. Los del sistema (dueño,
   operador, lector, agente) se siembran solos y no se editan; los propios sí.
2. **Excepciones por persona** — permisos concedidos o quitados a alguien en
   particular. Quitar gana siempre sobre conceder: si un rol lo da y la
   excepción lo niega, no puede.
3. **Tokens personales** — una credencial por persona y por uso (un agente,
   un MCP, un script). Nunca dan más de lo que su dueño ya tiene: el permiso
   efectivo es la intersección de lo que puede la persona y lo que el token
   declara. Se guardan con hash; el valor completo se ve una sola vez.

La comprobación vive en un middleware (app/middleware/acl.py) para que un
endpoint nuevo no pueda olvidarse de pedir permiso: sin regla, no pasa.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from app.services import permissions as perms

TOKEN_PREFIX = "kbl"
TOKEN_PREFIX_LENGTH = 12
TOKEN_SECRET_LENGTH = 32


# ── Permisos efectivos ───────────────────────────────────────────────────
def role_permissions(role_docs: Iterable[dict]) -> Set[str]:
    """Unión de los permisos de varios roles. Un rol superadmin los da todos."""
    granted: Set[str] = set()
    for role in role_docs:
        if role.get("superadmin"):
            return set(perms.PERMISSION_KEYS)
        granted.update(role.get("permissions") or [])
    return granted & set(perms.PERMISSION_KEYS)


def effective_permissions(user: dict, role_docs: Iterable[dict]) -> Set[str]:
    """Lo que puede una persona: sus roles, ajustado por sus excepciones.

    `permission_overrides` es {clave: "allow"|"deny"}. Negar gana sobre
    conceder, también sobre un rol superadmin: es la única forma de decir
    "esta persona puede todo menos esto".
    """
    if user.get("disabled"):
        return set()

    granted = set(perms.PERMISSION_KEYS) if user.get("superadmin") else set()
    granted |= role_permissions(role_docs)

    overrides = user.get("permission_overrides") or {}
    for key, effect in overrides.items():
        if key not in perms.PERMISSION_KEYS:
            continue
        if str(effect).lower() in ("allow", "grant", "si", "sí", "true"):
            granted.add(key)
        else:
            granted.discard(key)
    return granted


def scoped_permissions(user_permissions: Set[str], scopes: Optional[Sequence[str]]) -> Set[str]:
    """Permisos de un token: nunca más de lo que puede su dueño.

    Sin `scopes` (o vacío) el token hereda todo lo de la persona; con lista,
    solo lo que esté en ambas.
    """
    if not scopes:
        return set(user_permissions)
    return set(user_permissions) & set(scopes)


@dataclass
class Principal:
    """Quien hace la petición: una persona, sola o a través de un token."""

    username: str
    user_id: Optional[str] = None
    permissions: Set[str] = field(default_factory=set)
    superadmin: bool = False
    roles: List[str] = field(default_factory=list)
    token_id: Optional[str] = None
    token_name: Optional[str] = None

    @property
    def via_token(self) -> bool:
        return self.token_id is not None

    def can(self, permission: Optional[str]) -> bool:
        if permission is None:
            return True
        return permission in self.permissions


# ── Tokens personales ────────────────────────────────────────────────────
def fingerprint(raw_token: str) -> str:
    """Hash de un token. Lo guardado nunca permite reconstruirlo."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def token_prefix(raw_token: str) -> str:
    """Parte pública del token: identifica la fila sin revelar el secreto."""
    parts = raw_token.split("_")
    return parts[1] if len(parts) >= 3 and parts[0] == TOKEN_PREFIX else ""


def generate_token() -> tuple[str, str, str]:
    """Nuevo token: (valor completo, prefijo, hash). El valor no se guarda."""
    prefix = secrets.token_hex(TOKEN_PREFIX_LENGTH // 2)
    secret = secrets.token_urlsafe(TOKEN_SECRET_LENGTH)[:TOKEN_SECRET_LENGTH]
    raw = f"{TOKEN_PREFIX}_{prefix}_{secret}"
    return raw, prefix, fingerprint(raw)


def looks_like_token(value: str) -> bool:
    """Distingue un token personal de un JWT sin intentar decodificar nada."""
    return bool(value) and value.startswith(f"{TOKEN_PREFIX}_") and value.count("_") >= 2


def token_matches(raw_token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(fingerprint(raw_token), str(stored_hash or ""))


def token_is_usable(token_doc: dict, *, now: Optional[datetime] = None) -> bool:
    """Un token sirve si no fue revocado y no expiró."""
    if not token_doc or token_doc.get("revoked_at"):
        return False
    expires_at = token_doc.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= (now or datetime.utcnow()):
        return False
    return True


def token_view(token_doc: dict) -> Dict[str, Any]:
    """Lo que se puede mostrar de un token: todo menos el secreto."""
    view = {
        "id": str(token_doc.get("_id")),
        "name": token_doc.get("name"),
        "username": token_doc.get("username"),
        "prefix": token_doc.get("prefix"),
        "scopes": token_doc.get("scopes") or [],
        "created_at": token_doc.get("created_at"),
        "expires_at": token_doc.get("expires_at"),
        "last_used_at": token_doc.get("last_used_at"),
        "revoked_at": token_doc.get("revoked_at"),
    }
    view["state"] = (
        "revocado" if token_doc.get("revoked_at")
        else "expirado" if not token_is_usable(token_doc)
        else "activo"
    )
    for key in ("created_at", "expires_at", "last_used_at", "revoked_at"):
        if isinstance(view.get(key), datetime):
            view[key] = view[key].isoformat() + "Z"
    return view


def validate_scopes(scopes: Optional[Sequence[str]]) -> List[str]:
    """Deja solo permisos que existen; una clave inventada no concede nada."""
    return sorted({s for s in (scopes or []) if s in perms.PERMISSION_KEYS})
