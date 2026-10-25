"""Conexión GitHub personal: cada persona conecta su propia cuenta una vez.

La persona pega su token en la consola (nunca por chat ni por un token de
agente). Kaanbal lo valida contra GitHub, lo guarda cifrado con una clave
derivada de SECRET_KEY y no lo vuelve a mostrar. Los agentes que actúan con un
token de esa persona abren workspaces sobre cualquier repo al que ella tenga
acceso: el código viaja al contenedor sin credenciales y los commits los firma
la API con el token de la persona.
"""
from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.db import get_db
from app.services.autonomy_policy import AutonomyError

COLLECTION = "github_accounts"
_TOKEN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,255}|github_pat_[A-Za-z0-9_]{20,255})")


def _cipher() -> Fernet:
    from app.config import settings
    key = hashlib.sha256(b"kaanbal-github-account-v1:" + settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(token: str) -> str:
    return _cipher().encrypt(token.encode()).decode()


def unseal(blob: str) -> str:
    try:
        return _cipher().decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError):
        # Cambió SECRET_KEY (o se reinstaló): la persona debe reconectar.
        raise AutonomyError("La conexión GitHub ya no se puede leer; vuelve a conectarla en Conectar → GitHub.", 409)


def public(doc: dict | None) -> dict:
    if not doc:
        return {"connected": False}
    result = {"connected": True, **{k: doc.get(k) for k in ("login", "name", "scopes", "token_hint", "kind")}}
    for key in ("connected_at", "checked_at"):
        if isinstance(doc.get(key), datetime):
            result[key] = doc[key].isoformat() + "Z"
    return result


async def _github(token: str, path: str, params=None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        return await client.get("https://api.github.com" + path, params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})


async def connect(principal, token: str) -> dict:
    if principal.via_token:
        raise AutonomyError("La conexión GitHub la hace la persona desde la consola, no un token de agente.", 403)
    token = (token or "").strip()
    if not _TOKEN.fullmatch(token):
        raise AutonomyError("Pega un token de GitHub (ghp_… o github_pat_…).", 422)
    response = await _github(token, "/user")
    if response.status_code == 401:
        raise AutonomyError("GitHub rechazó el token: revisa que esté vigente.", 422)
    if response.status_code >= 300:
        raise AutonomyError(f"GitHub respondió HTTP {response.status_code}; intenta de nuevo.", 424)
    user = response.json()
    scopes = [s.strip() for s in response.headers.get("x-oauth-scopes", "").split(",") if s.strip()]
    now = datetime.utcnow()
    doc = {"_id": principal.username, "login": user.get("login"), "name": user.get("name"),
           "scopes": scopes, "kind": "fine-grained" if token.startswith("github_pat_") else "classic",
           "token_hint": token[-4:], "token": seal(token), "connected_at": now, "checked_at": now}
    await get_db()[COLLECTION].replace_one({"_id": principal.username}, doc, upsert=True)
    return public(doc)


async def status(principal) -> dict:
    return public(await get_db()[COLLECTION].find_one({"_id": principal.username}))


async def disconnect(principal) -> dict:
    if principal.via_token:
        raise AutonomyError("Desconectar GitHub se hace desde la consola.", 403)
    await get_db()[COLLECTION].delete_one({"_id": principal.username})
    return {"connected": False}


async def token_for(username: str) -> str:
    doc = await get_db()[COLLECTION].find_one({"_id": username})
    if not doc:
        raise AutonomyError("Conecta tu cuenta de GitHub en la consola (Conectar → GitHub) para trabajar sobre tus repos.", 409)
    return unseal(doc["token"])


async def repositories(principal, query: str = "", limit: int = 50) -> dict:
    token = await token_for(principal.username)
    response = await _github(token, "/user/repos", {"per_page": 100, "sort": "pushed",
                                                    "affiliation": "owner,collaborator,organization_member"})
    if response.status_code >= 300:
        raise AutonomyError(f"GitHub respondió HTTP {response.status_code} al listar tus repos.", 424)
    needle = (query or "").lower()
    rows = [{"repo": r["full_name"], "private": r.get("private"), "default_branch": r.get("default_branch"),
             "can_push": bool((r.get("permissions") or {}).get("push")), "pushed_at": r.get("pushed_at")}
            for r in response.json() if needle in r["full_name"].lower()]
    return {"repos": rows[:limit], "total": len(rows)}
