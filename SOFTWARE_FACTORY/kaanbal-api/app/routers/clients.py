from fastapi import APIRouter, HTTPException, Depends
from typing import List
from datetime import datetime
from bson import ObjectId

from app.db import get_db
from app.models import ClientCreate
from app.routers.auth import get_current_active_user

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get("", response_model=List[dict])
async def list_clients():
    """Listar todos los clientes"""
    db = get_db()
    clients = await db.clients.find().to_list(100)
    for client in clients:
        client["_id"] = str(client["_id"])
    return clients


@router.get("/{client_slug}")
async def get_client(client_slug: str):
    """Obtener detalle de un cliente"""
    db = get_db()
    client = await db.clients.find_one({"slug": client_slug})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client["_id"] = str(client["_id"])
    return client


@router.get("/{client_slug}/apps")
async def get_client_apps(client_slug: str):
    """Obtener apps de un cliente"""
    db = get_db()
    client = await db.clients.find_one({"slug": client_slug})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    apps = await db.apps.find({"client_id": client_slug}).to_list(100)
    for app in apps:
        app["_id"] = str(app["_id"])
    return apps


@router.post("", status_code=201)
async def create_client(client_data: ClientCreate):
    """Crear un nuevo cliente"""
    db = get_db()
    
    existing = await db.clients.find_one({"slug": client_data.slug})
    if existing:
        raise HTTPException(status_code=409, detail="Client already exists")
    
    client_doc = {
        **client_data.model_dump(),
        "apps": [],
        "created_at": datetime.utcnow()
    }
    
    result = await db.clients.insert_one(client_doc)
    return {
        "id": str(result.inserted_id),
        **client_data.model_dump()
    }


@router.delete("/{client_slug}")
async def delete_client(client_slug: str):
    """Eliminar un cliente"""
    db = get_db()
    result = await db.clients.delete_one({"slug": client_slug})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"message": f"Client {client_slug} deleted"}
