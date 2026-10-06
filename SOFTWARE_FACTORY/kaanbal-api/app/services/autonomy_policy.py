"""Resource grants for agent operations, intersected with existing ACLs."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath


class AutonomyError(Exception):
    def __init__(self, detail: str, status: int = 409):
        super().__init__(detail)
        self.status = status


def require_permission(principal, permission: str) -> None:
    if not principal.can(permission):
        raise AutonomyError(f"Falta el permiso {permission}.", 403)


def authorize(policy: dict, principal, *, feature: str, app: str = "", env: str = "", node: str = "", core: bool = False) -> None:
    if not policy.get("enabled") or not policy.get(f"{feature}_enabled"):
        raise AutonomyError(f"La capacidad {feature} no está habilitada en la política de autonomía.", 403)
    now = datetime.now(timezone.utc)
    for grant in policy.get("grants", []):
        if grant.get("username") != principal.username:
            continue
        if grant.get("token_id") and grant["token_id"] != principal.token_id:
            continue
        if grant.get("expires_at"):
            try:
                expiry = datetime.fromisoformat(str(grant["expires_at"]).replace("Z", "+00:00"))
                if expiry.tzinfo is None or expiry <= now:
                    continue
            except (ValueError, TypeError):
                continue
        if core and not grant.get("core"):
            continue
        if node and node not in grant.get("nodes", []):
            continue
        if app and app not in grant.get("apps", []):
            continue
        if env and env not in grant.get("environments", []):
            continue
        return
    raise AutonomyError("La política no concede este recurso a la persona/token, o la concesión expiró.", 403)


def require_elevated(principal):
    if principal.via_token and not principal.elevated:
        raise AutonomyError("Esta acción exige un token crítico (control total, confirmado con contraseña).", 403)


def resource_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value or ""):
        raise AutonomyError("Nombre de recurso inválido.", 422)
    return value


def node_name(value: str) -> str:
    if not value or len(value) > 253:
        raise AutonomyError("Nombre de nodo inválido.", 422)
    for label in value.split("."):
        resource_name(label)
    return value


def safe_path(value: str) -> str:
    if not value or len(value) > 500 or "\\" in value or any(ord(c) < 32 for c in value):
        raise AutonomyError("Ruta de archivo inválida.", 422)
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise AutonomyError("La ruta debe permanecer dentro del repositorio.", 422)
    if any(p.lower() == ".git" or p.lower().startswith(".env") or p.lower().endswith((".pem", ".key")) for p in path.parts):
        raise AutonomyError("El workbench no publica ni lee credenciales o metadatos Git.", 422)
    return value


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def redact(text: str, secrets=()) -> str:
    for value in sorted({str(s) for s in secrets if s and len(str(s)) >= 4}, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    text = re.sub(r"(?i)(?:gh[pousr]_[\w]+|github_pat_[\w]+|kbl_[\w-]+)", "[REDACTED]", text)
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?im)((?:password|passwd|token|secret|api_key)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return text
