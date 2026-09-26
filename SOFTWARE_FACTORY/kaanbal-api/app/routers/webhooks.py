"""
Webhooks Router
===============
Endpoints para recibir webhooks de Jira, GitHub, etc.
Compatible con el payload que usas actualmente en n8n.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from datetime import datetime

from app.db import get_db
from app.models import WebhookDeployRequest, AppCreate, ExposureConfig, AppSpecs, ResourceSpec, ExposureType
from app.services.app_deployer import AppDeployer

router = APIRouter()


@router.post("/deploy")
async def webhook_deploy(payload: WebhookDeployRequest, background_tasks: BackgroundTasks):
    """
    Webhook para crear apps desde Jira u otros sistemas.
    
    Acepta el mismo payload que tu flujo de n8n:
    ```json
    {
        "metadata": {"requestId": "req-12346", "deployer": "Jira-Automation"},
        "project": {"workspace": "my-workspace", "name": "my-app", "key": "MYAPP"},
        "app": {"name": "my-app", "template": "vue3-spa", "domain": "example.com"},
        "specs": {"replicas": 2, "port": 80, "resources": {...}},
        "exposure": {"type": "public"},
        "gitConfig": {"user": "your-github-user", "email": "..."}
    }
    ```
    """
    db = get_db()
    
    app_name = payload.app.get("name")
    if not app_name:
        raise HTTPException(status_code=400, detail="app.name is required")
    
    # Verificar si ya existe
    existing = await db.apps.find_one({"name": app_name})
    if existing:
        raise HTTPException(status_code=409, detail=f"App {app_name} already exists")
    
    # Convertir payload al formato interno
    exposure_data = payload.exposure or {}
    specs_data = payload.specs or {}
    resources_data = specs_data.get("resources", {})
    
    app_data = AppCreate(
        name=app_name,
        template=payload.app.get("template", "vue3-spa"),
        description=payload.project.get("description", ""),
        client_id=payload.metadata.get("clientId"),
        exposure=ExposureConfig(
            type=ExposureType(exposure_data.get("type", "public")),
            public_path=exposure_data.get("publicPath", "/"),
            tailscale_hostname=exposure_data.get("tailscaleHostname")
        ),
        specs=AppSpecs(
            replicas=specs_data.get("replicas", 1),
            port=specs_data.get("port", 80),
            resources=ResourceSpec(
                cpu_request=resources_data.get("cpu_request", "100m"),
                cpu_limit=resources_data.get("cpu_limit", "500m"),
                mem_request=resources_data.get("mem_request", "128Mi"),
                mem_limit=resources_data.get("mem_limit", "512Mi")
            )
        )
    )
    
    # Crear registro
    app_doc = {
        "name": app_data.name,
        "template": app_data.template,
        "description": app_data.description,
        "client_id": app_data.client_id,
        "exposure": app_data.exposure.model_dump(),
        "specs": app_data.specs.model_dump(),
        "status": "deploying",
        "webhook_payload": payload.model_dump(),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = await db.apps.insert_one(app_doc)
    app_id = str(result.inserted_id)
    
    # Deploy en background
    deployer = AppDeployer()
    background_tasks.add_task(deployer.deploy_async, app_id, app_data, payload)
    
    return {
        "status": "accepted",
        "app_id": app_id,
        "app_name": app_name,
        "message": "Deployment started"
    }


@router.post("/jira")
async def webhook_jira(payload: dict):
    """
    Webhook específico para eventos de Jira.
    Puedes configurar Jira para enviar eventos aquí.
    """
    # TODO: Parsear eventos de Jira y actuar según el tipo
    event_type = payload.get("webhookEvent", "unknown")
    
    return {
        "status": "received",
        "event": event_type,
        "message": "Jira webhook received"
    }
