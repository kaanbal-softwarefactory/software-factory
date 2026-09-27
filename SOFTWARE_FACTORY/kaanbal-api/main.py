"""
Kaanbal API - Kaanbal Engine Core Backend
==========================================
API principal que maneja:
- Creación de apps desde templates
- Gestión de clientes
- Configuración del sistema
- Webhooks para Jira/externos
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import asyncio
import os
import logging

from app.config import settings
from app.routers import apps, clients, config, webhooks, health, templates, setup, auth, system, admin, logs, domains, links, sites, security, stacks, core, mcp
from app.db import connect_db, close_db
from app.middleware.acl import AccessControlMiddleware
from app.services.activity_log import activity_log, CATEGORY_API, CATEGORY_ERROR
from app.version import VERSION

logger = logging.getLogger(__name__)


def _build_cors_origins():
    """Build CORS origins dynamically from DOMAIN env var. No hardcoded domains."""
    domain = os.getenv("DOMAIN", settings.domain or "localhost")
    origins = [
        "http://localhost:5000",
        "http://localhost:5173",
    ]
    if domain and domain != "localhost":
        origins.append(f"https://kaanbal-console.{domain}")
    # Tailscale origin: built at runtime from kaanbal-console Tailscale ingress pattern
    # The Tailscale suffix comes from MongoDB system_config at runtime, not hardcoded
    ts_suffix = os.getenv("TAILSCALE_DNS_SUFFIX", "")
    if ts_suffix:
        origins.append(f"https://kaanbal-kaanbal-console-ingress.{ts_suffix}")
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await connect_db()
    await activity_log.init()
    # Roles del sistema y migración de las cuentas anteriores al catálogo de
    # permisos: sin esto, al actualizar nadie tendría permisos.
    from app.services import access_store
    await access_store.ensure_seed()
    # Secretos que no llegaron a Vault (p. ej. se desplegó con Vault sellado tras
    # un reinicio) se restauran solos cuando Vault vuelve a estar abierto.
    from app.services import vault_sync
    vault_task = asyncio.create_task(vault_sync.reconcile_loop())
    yield
    # Shutdown
    vault_task.cancel()
    await close_db()


app = FastAPI(
    title="Kaanbal API",
    description="Kaanbal Engine Core Backend - Administra apps, clientes y configuración",
    version=VERSION,
    lifespan=lifespan
)

# Control de acceso: autentica (sesión o token personal) y exige el permiso
# que declara el catálogo. Se agrega antes que CORS para que se ejecute después
# (Starlette aplica los middlewares en orden inverso) y las respuestas 401/403
# lleguen al navegador con sus cabeceras CORS.
app.add_middleware(AccessControlMiddleware)

# CORS - Origins built dynamically from DOMAIN env var (no hardcoded domains)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = request_id
    started = perf_counter()

    actor = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        actor = "authenticated"

    try:
        response = await call_next(request)
        duration_ms = round((perf_counter() - started) * 1000, 2)
        status_code = response.status_code
        level = "error" if status_code >= 500 else "warn" if status_code >= 400 else "info"

        await activity_log.log(
            "api.request",
            category=CATEGORY_API,
            level=level,
            actor=actor,
            detail={
                "query_params": dict(request.query_params),
            },
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            ip=request.client.host if request.client else None,
        )
        response.headers["X-Request-Id"] = request_id
        return response
    except Exception as exc:
        duration_ms = round((perf_counter() - started) * 1000, 2)
        await activity_log.error(
            "api.exception",
            category=CATEGORY_ERROR,
            actor=actor,
            detail={"query_params": dict(request.query_params)},
            exc=exc,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=duration_ms,
            ip=request.client.host if request.client else None,
        )
        logger.exception("Unhandled API exception")
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})

# Routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(health.router, tags=["Health"])
app.include_router(apps.router, prefix="/api/v1/apps", tags=["Apps"])
app.include_router(apps.stream_router, prefix="/api/v1/apps", tags=["Apps"])
app.include_router(templates.router, prefix="/api/v1/templates", tags=["Templates"])
app.include_router(setup.router, prefix="/api/v1/setup", tags=["Setup"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System & Tokens"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin Settings"])
app.include_router(clients.router, prefix="/api/v1/clients", tags=["Clients"])
app.include_router(domains.router, prefix="/api/v1/domains", tags=["Domains"])
app.include_router(core.router, prefix="/api/v1/core", tags=["Core Updates"])
app.include_router(links.router, prefix="/api/v1/links", tags=["Service Links"])
app.include_router(security.router, prefix="/api/v1/security", tags=["Security"])
app.include_router(stacks.router, prefix="/api/v1/stacks", tags=["Stacks"])
app.include_router(sites.router, prefix="/api/v1/sites", tags=["Sites"])
app.include_router(config.router, prefix="/api/v1/config", tags=["Config"])
app.include_router(logs.router, prefix="/api/v1/logs", tags=["Activity Logs"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(mcp.router, tags=["MCP"])


@app.get("/")
async def root():
    return {
        "name": "Kaanbal API",
        "version": VERSION,
        "status": "running",
        "docs": "/docs"
    }
