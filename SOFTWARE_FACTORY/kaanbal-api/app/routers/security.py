"""
Security Router — personas, roles y tokens personales
=====================================================

Todo lo que define quién entra y qué puede hacer. Los permisos que exige cada
endpoint de aquí están en el catálogo (app/services/permissions.py), igual que
los del resto de la API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.db import get_db
from app.models import User
from app.routers.auth import get_current_active_user, get_password_hash
from app.services import access, access_store
from app.services import permissions as perms
from app.services.activity_log import activity_log, CATEGORY_AUTH

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])

MAX_TOKEN_DAYS = 365


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=10)
    email: Optional[str] = None
    roles: List[str] = Field(default_factory=lambda: ["lector"])


class UserUpdate(BaseModel):
    email: Optional[str] = None
    roles: Optional[List[str]] = None
    disabled: Optional[bool] = None
    permission_overrides: Optional[Dict[str, str]] = None


class PasswordReset(BaseModel):
    password: str = Field(..., min_length=10)


class RoleUpsert(BaseModel):
    name: str = Field(..., min_length=3, max_length=60)
    description: str = ""
    permissions: List[str] = Field(default_factory=list)


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=60)
    scopes: List[str] = Field(default_factory=list, description="Permisos del token; vacío = los de la persona")
    expires_in_days: Optional[int] = Field(default=90, ge=1, le=MAX_TOKEN_DAYS)


def _principal(request: Request) -> access.Principal:
    """El middleware ya resolvió quién hace la petición."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Sesión no resuelta")
    return principal


def _user_view(user: dict, roles_by_slug: Dict[str, dict]) -> dict:
    granted = access.effective_permissions(user, [roles_by_slug[s] for s in (user.get("roles") or []) if s in roles_by_slug])
    return {
        "id": str(user.get("_id")),
        "username": user.get("username"),
        "email": user.get("email"),
        "disabled": bool(user.get("disabled")),
        "superadmin": bool(user.get("superadmin")),
        "roles": user.get("roles") or [],
        "permission_overrides": user.get("permission_overrides") or {},
        "permissions": sorted(granted),
        "created_at": user.get("created_at"),
    }


# ── Catálogo y sesión ────────────────────────────────────────────────────
@router.get("/permissions")
async def list_permissions():
    """Catálogo canónico: qué permisos existen y qué endpoints controla cada uno."""
    return {"permissions": perms.catalog_payload()}


@router.get("/me")
async def whoami(request: Request):
    """Quién soy y qué puedo hacer. La consola oculta lo que no está aquí."""
    principal = _principal(request)
    return {
        "username": principal.username,
        "roles": principal.roles,
        "superadmin": principal.superadmin,
        "permissions": sorted(principal.permissions),
        "via_token": principal.via_token,
        "token_name": principal.token_name,
    }


# ── Roles ────────────────────────────────────────────────────────────────
@router.get("/roles")
async def list_roles():
    db = get_db()
    roles = await db[access_store.ROLES].find().sort("slug", 1).to_list(100)
    for role in roles:
        role["_id"] = str(role["_id"])
        role["users"] = await db[access_store.USERS].count_documents({"roles": role["slug"]})
    return {"roles": roles}


@router.post("/roles", status_code=201)
async def create_role(body: RoleUpsert, current_user: User = Depends(get_current_active_user)):
    """Crear un rol propio. Los del sistema vienen con el producto."""
    db = get_db()
    slug = "-".join(body.name.lower().split())[:40]
    if await db[access_store.ROLES].find_one({"slug": slug}):
        raise HTTPException(status_code=409, detail=f"Ya existe un rol '{slug}'.")

    role = {
        "slug": slug,
        "name": body.name,
        "description": body.description,
        "superadmin": False,
        "permissions": access.validate_scopes(body.permissions),
        "system": False,
        "created_at": datetime.utcnow(),
    }
    await db[access_store.ROLES].insert_one(role)
    await activity_log.log(
        "security.role.created", category=CATEGORY_AUTH, actor=current_user.username,
        target=slug, detail={"permissions": role["permissions"]},
    )
    role["_id"] = str(role["_id"])
    return role


@router.patch("/roles/{slug}")
async def update_role(slug: str, body: RoleUpsert, current_user: User = Depends(get_current_active_user)):
    db = get_db()
    role = await db[access_store.ROLES].find_one({"slug": slug})
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    if role.get("system"):
        raise HTTPException(
            status_code=409,
            detail=f"'{role['name']}' es un rol del sistema y no se edita. Crea uno propio a partir de él.",
        )
    await db[access_store.ROLES].update_one({"slug": slug}, {"$set": {
        "name": body.name,
        "description": body.description,
        "permissions": access.validate_scopes(body.permissions),
        "updated_at": datetime.utcnow(),
    }})
    await activity_log.log(
        "security.role.updated", category=CATEGORY_AUTH, actor=current_user.username, target=slug,
    )
    return {"slug": slug, "message": "Rol actualizado"}


@router.delete("/roles/{slug}")
async def delete_role(slug: str, current_user: User = Depends(get_current_active_user)):
    db = get_db()
    role = await db[access_store.ROLES].find_one({"slug": slug})
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    if role.get("system"):
        raise HTTPException(status_code=409, detail="Los roles del sistema no se eliminan.")
    in_use = await db[access_store.USERS].count_documents({"roles": slug})
    if in_use:
        raise HTTPException(status_code=409, detail=f"{in_use} persona(s) tienen ese rol. Quítaselo primero.")
    await db[access_store.ROLES].delete_one({"slug": slug})
    await activity_log.log(
        "security.role.deleted", category=CATEGORY_AUTH, actor=current_user.username, target=slug,
    )
    return {"slug": slug, "message": "Rol eliminado"}


# ── Personas ─────────────────────────────────────────────────────────────
@router.get("/users")
async def list_users():
    db = get_db()
    roles_by_slug = {r["slug"]: r for r in await db[access_store.ROLES].find().to_list(100)}
    users = await db[access_store.USERS].find().sort("username", 1).to_list(200)
    return {"users": [_user_view(user, roles_by_slug) for user in users]}


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, current_user: User = Depends(get_current_active_user)):
    """Alta de una persona con sus roles."""
    db = get_db()
    username = body.username.strip().lower()
    if await db[access_store.USERS].find_one({"username": username}):
        raise HTTPException(status_code=409, detail=f"Ya existe la cuenta '{username}'.")

    roles = await access_store.get_roles(body.roles)
    if len(roles) != len(set(body.roles)):
        raise HTTPException(status_code=422, detail="Alguno de los roles no existe.")

    user = {
        "username": username,
        "email": body.email,
        "hashed_password": get_password_hash(body.password),
        "role": "admin" if any(r.get("superadmin") for r in roles) else "user",  # compat
        "roles": list(body.roles),
        "superadmin": False,
        "permission_overrides": {},
        "disabled": False,
        "created_at": datetime.utcnow(),
        "created_by": current_user.username,
    }
    await db[access_store.USERS].insert_one(user)
    await activity_log.log(
        "security.user.created", category=CATEGORY_AUTH, actor=current_user.username,
        target=username, detail={"roles": body.roles},
    )
    roles_by_slug = {r["slug"]: r for r in roles}
    return _user_view(user, roles_by_slug)


@router.patch("/users/{username}")
async def update_user(username: str, body: UserUpdate, request: Request, current_user: User = Depends(get_current_active_user)):
    db = get_db()
    user = await db[access_store.USERS].find_one({"username": username})
    if not user:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    updates: Dict[str, Any] = {"updated_at": datetime.utcnow()}
    if body.email is not None:
        updates["email"] = body.email
    if body.roles is not None:
        roles = await access_store.get_roles(body.roles)
        if len(roles) != len(set(body.roles)):
            raise HTTPException(status_code=422, detail="Alguno de los roles no existe.")
        updates["roles"] = list(body.roles)
    if body.permission_overrides is not None:
        updates["permission_overrides"] = {
            key: value for key, value in body.permission_overrides.items() if key in perms.PERMISSION_KEYS
        }
    if body.disabled is not None:
        # Quedarse sin nadie que administre deja la plataforma sin dueño.
        if body.disabled and username == _principal(request).username:
            raise HTTPException(status_code=409, detail="No puedes suspender tu propia cuenta.")
        updates["disabled"] = body.disabled

    await db[access_store.USERS].update_one({"username": username}, {"$set": updates})
    await activity_log.log(
        "security.user.updated", category=CATEGORY_AUTH, actor=current_user.username,
        target=username, detail={k: v for k, v in updates.items() if k != "updated_at"},
    )
    roles_by_slug = {r["slug"]: r for r in await db[access_store.ROLES].find().to_list(100)}
    return _user_view(await db[access_store.USERS].find_one({"username": username}), roles_by_slug)


@router.post("/users/{username}/password")
async def reset_password(username: str, body: PasswordReset, current_user: User = Depends(get_current_active_user)):
    db = get_db()
    if not await db[access_store.USERS].find_one({"username": username}):
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    await db[access_store.USERS].update_one(
        {"username": username},
        {"$set": {"hashed_password": get_password_hash(body.password), "updated_at": datetime.utcnow()}},
    )
    await activity_log.log(
        "security.user.password.reset", category=CATEGORY_AUTH, level="warn",
        actor=current_user.username, target=username,
    )
    return {"username": username, "message": "Contraseña actualizada"}


# ── Tokens personales ────────────────────────────────────────────────────
@router.get("/tokens")
async def list_my_tokens(request: Request):
    """Mis tokens. El valor completo no se puede volver a ver."""
    return {"tokens": await access_store.list_tokens(_principal(request).username)}


@router.get("/tokens/all")
async def list_all_tokens():
    """Todos los tokens de la plataforma (para auditar y revocar)."""
    return {"tokens": await access_store.list_tokens()}


@router.post("/tokens", status_code=201)
async def create_token(body: TokenCreate, request: Request):
    """Crear un token personal. Se muestra una sola vez: si se pierde, se revoca y se crea otro."""
    principal = _principal(request)
    if principal.via_token:
        raise HTTPException(
            status_code=403,
            detail="Un token no puede crear otros tokens. Hazlo desde la consola con tu sesión.",
        )

    scopes = access.validate_scopes(body.scopes)
    fuera = sorted(set(scopes) - principal.permissions)
    if fuera:
        raise HTTPException(
            status_code=403,
            detail=f"No puedes dar a un token permisos que tú no tienes: {', '.join(fuera)}.",
        )

    expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    created = await access_store.create_token(
        username=principal.username, name=body.name, scopes=scopes, expires_at=expires_at,
    )
    await activity_log.log(
        "security.token.created", category=CATEGORY_AUTH, actor=principal.username,
        target=body.name, detail={"scopes": scopes, "expires_at": expires_at},
    )
    return {
        **created,
        "warning": "Guárdalo ahora: no se vuelve a mostrar.",
    }


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str, request: Request):
    """Revocar un token. Solo los propios, salvo que se tenga security.tokens.admin."""
    principal = _principal(request)
    scope_owner = None if principal.can("security.tokens.admin") else principal.username
    if not await access_store.revoke_token(token_id, username=scope_owner):
        raise HTTPException(status_code=404, detail="Token no encontrado o ya revocado")
    await activity_log.log(
        "security.token.revoked", category=CATEGORY_AUTH, actor=principal.username, target=token_id,
    )
    return {"id": token_id, "message": "Token revocado"}
