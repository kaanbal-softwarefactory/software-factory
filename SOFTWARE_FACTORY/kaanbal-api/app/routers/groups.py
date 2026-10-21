"""Groups become named systems with an accountable platform user."""
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import get_db
from app.models import User
from app.routers.auth import get_current_active_user
from app.services import app_groups
from app.services.activity_log import activity_log, CATEGORY_APP

router = APIRouter(dependencies=[Depends(get_current_active_user)])


class GroupUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    owner: Optional[str] = Field(default=None, max_length=100)
    stage: Literal["prototype", "active", "reference", "archived"] = "active"


@router.get("")
async def list_groups(owner: Optional[str] = None):
    db = get_db()
    apps = await db.apps.find({}, {"name": 1, "app_group": 1, "template": 1,
                                  "status": 1, "environments": 1}).to_list(None)
    metadata = await db.app_groups.find({}).to_list(None)
    groups = app_groups.inventory(apps, metadata, owner)
    return {"groups": groups, "total": len(groups)}


@router.get("/owners")
async def group_owners():
    # Only identifiers suitable for assignment; never return credentials, email or roles.
    users = await get_db().users.find({"disabled": {"$ne": True}}, {"username": 1}).sort("username", 1).to_list(None)
    return {"owners": [user["username"] for user in users]}


@router.put("/{slug}")
async def update_group(slug: str, body: GroupUpdate, current_user: User = Depends(get_current_active_user)):
    if not app_groups.valid_slug(slug) or not body.name.strip():
        raise HTTPException(422, "Grupo inválido; usa un identificador en minúsculas, números, guiones o guion bajo")
    db = get_db()
    if body.owner and not await db.users.find_one({"username": body.owner, "disabled": {"$ne": True}}, {"_id": 1}):
        raise HTTPException(422, "El responsable debe ser una cuenta activa de Kaanbal")
    values = body.model_dump()
    values["name"] = body.name.strip()
    await db.app_groups.update_one({"_id": slug}, {"$set": {**values, "updated_at": datetime.utcnow()},
                                                   "$setOnInsert": {"created_at": datetime.utcnow()}}, upsert=True)
    await activity_log.log("group.updated", category=CATEGORY_APP, actor=current_user.username,
                           target=slug, detail=values)
    return {"slug": slug, **values}
