"""
Accesos en MongoDB: roles, personas y tokens personales
=======================================================

La lógica de quién puede qué vive en access.py (pura y probada). Aquí está lo
que toca la base: sembrar los roles del sistema, migrar las cuentas que ya
existían y resolver la credencial de cada petición.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.db import get_db
from app.services import access
from app.services import permissions as perms

logger = logging.getLogger(__name__)

ROLES = "roles"
TOKENS = "access_tokens"
USERS = "users"


async def ensure_seed() -> None:
    """Sembrar roles del sistema y poner al día las cuentas anteriores.

    Se llama al arrancar la API. Es idempotente: los roles del sistema se
    reescriben desde el código (son parte del producto, no se editan) y los
    roles propios no se tocan.
    """
    db = get_db()
    for role in perms.SYSTEM_ROLES:
        await db[ROLES].update_one(
            {"slug": role["slug"]},
            {
                "$set": {**role, "updated_at": datetime.utcnow()},
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            upsert=True,
        )

    # Cuentas anteriores al catálogo: 'admin' podía todo, 'user' operaba.
    # Sin esto, al actualizar nadie tendría permisos y la consola quedaría muda.
    async for user in db[USERS].find({"roles": {"$exists": False}}):
        legacy = str(user.get("role") or "user").lower()
        slug = perms.LEGACY_ROLE_MAP.get(legacy, "operador")
        await db[USERS].update_one(
            {"_id": user["_id"]},
            {"$set": {
                "roles": [slug],
                "superadmin": slug == "owner",
                "permission_overrides": user.get("permission_overrides") or {},
                "updated_at": datetime.utcnow(),
            }},
        )
        logger.info("Cuenta %s migrada al rol '%s'", user.get("username"), slug)


async def count_users() -> int:
    return await get_db()[USERS].count_documents({})


async def get_roles(slugs: Sequence[str]) -> List[dict]:
    if not slugs:
        return []
    return await get_db()[ROLES].find({"slug": {"$in": list(slugs)}}).to_list(50)


async def principal_from_user(user: dict, *, token: Optional[dict] = None) -> access.Principal:
    """Permisos efectivos de una persona, recortados por el token si viene por uno."""
    role_slugs = user.get("roles") or []
    granted = access.effective_permissions(user, await get_roles(role_slugs))
    if token is not None:
        granted = access.scoped_permissions(granted, token.get("scopes"))
    return access.Principal(
        username=user.get("username", ""),
        user_id=str(user.get("_id")) if user.get("_id") else None,
        permissions=granted,
        superadmin=bool(user.get("superadmin")),
        roles=list(role_slugs),
        token_id=str(token["_id"]) if token else None,
        token_name=token.get("name") if token else None,
    )


async def principal_from_token(raw_token: str) -> Optional[access.Principal]:
    """Resolver un token personal. Devuelve None si no sirve (revocado, expirado…)."""
    db = get_db()
    prefix = access.token_prefix(raw_token)
    if not prefix:
        return None
    token = await db[TOKENS].find_one({"prefix": prefix})
    if not token or not access.token_matches(raw_token, token.get("token_hash", "")):
        return None
    if not access.token_is_usable(token):
        return None
    user = await db[USERS].find_one({"username": token.get("username")})
    if not user or user.get("disabled"):
        return None

    # Para poder ver en la consola qué token sigue vivo y cuál sobra.
    await db[TOKENS].update_one({"_id": token["_id"]}, {"$set": {"last_used_at": datetime.utcnow()}})
    return await principal_from_user(user, token=token)


async def create_token(
    *, username: str, name: str, scopes: Optional[Sequence[str]] = None,
    expires_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Crear un token personal. El valor completo se devuelve una sola vez."""
    raw, prefix, token_hash = access.generate_token()
    doc = {
        "username": username,
        "name": name.strip()[:60] or "token",
        "prefix": prefix,
        "token_hash": token_hash,
        "scopes": access.validate_scopes(scopes),
        "created_at": datetime.utcnow(),
        "expires_at": expires_at,
        "last_used_at": None,
        "revoked_at": None,
    }
    result = await get_db()[TOKENS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return {"token": raw, **access.token_view(doc)}


async def list_tokens(username: Optional[str] = None) -> List[dict]:
    query = {"username": username} if username else {}
    docs = await get_db()[TOKENS].find(query).sort("created_at", -1).to_list(200)
    return [access.token_view(doc) for doc in docs]


async def revoke_token(token_id: str, *, username: Optional[str] = None) -> bool:
    """Revocar un token. Con `username`, solo si es de esa persona."""
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        query: Dict[str, Any] = {"_id": ObjectId(token_id)}
    except InvalidId:
        return False
    if username:
        query["username"] = username
    result = await get_db()[TOKENS].update_one(
        {**query, "revoked_at": None}, {"$set": {"revoked_at": datetime.utcnow()}}
    )
    return result.modified_count > 0
