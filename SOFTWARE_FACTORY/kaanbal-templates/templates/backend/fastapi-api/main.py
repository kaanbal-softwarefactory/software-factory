"""placeholder-app — API desplegada con Kaanbal.

La conexión a la base vive en db.py y sale de variables de entorno: el mismo
código corre contra el docker-compose local y contra la base del clúster.
Lee AGENTS.md antes de tocar nada si estás automatizando cambios.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import Store

store = Store()

# El frontend del stack pega desde el navegador: sin CORS, el navegador corta.
# En local vale cualquiera; en el clúster, el origen que Kaanbal publicó.
ALLOWED_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "*").split(",") if o]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Primera vez: crea base, colección o tabla e índices. Es idempotente.
    store.init()
    yield
    store.close()


app = FastAPI(title="placeholder-app", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ItemIn(BaseModel):
    name: str


@app.get("/health")
def health():
    """Lo que mira Kubernetes y también el frontend para saber si hay base."""
    return {"status": "ok", "app": "placeholder-app", "engine": store.engine, "database": store.ping()}


@app.get("/")
def root():
    return {"message": "placeholder-app is running", "docs": "/docs"}


@app.get("/items")
def list_items():
    return {"items": store.list_items()}


@app.post("/items", status_code=201)
def create_item(item: ItemIn):
    name = item.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name no puede estar vacío")
    return store.add_item(name)
