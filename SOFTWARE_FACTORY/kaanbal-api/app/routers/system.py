"""
System Configuration & API Tokens Router
Gestiona credenciales del sistema y tokens de acceso programático
"""
import secrets
from datetime import datetime, timedelta
from typing import List, Optional
import httpx

from fastapi import APIRouter, Depends, HTTPException, status, Header, BackgroundTasks
from pydantic import BaseModel
from app.models import (
    SystemConfig, SystemConfigUpdate, 
    APIToken, APITokenCreate, APITokenCreated
)
from app.db import get_db
from app.routers.auth import get_current_active_user
from app.defaults import VAULT_ADDR, VAULT_HOSTNAME, TAILSCALE_DNS_SUFFIX

router = APIRouter(dependencies=[Depends(get_current_active_user)])


def _mask_secret_value(value: str) -> str:
    if value is None:
        return ""
    string_value = str(value)
    if len(string_value) <= 4:
        return "*" * len(string_value)
    return f"{string_value[:2]}{'*' * (len(string_value) - 4)}{string_value[-2:]}"


def _build_vault_ui_url(config: dict) -> str:
    vault_hostname = config.get("vault_hostname", VAULT_HOSTNAME)
    tailscale_suffix = config.get("tailscale_dns_suffix", TAILSCALE_DNS_SUFFIX)
    if not vault_hostname:
        return ""
    return f"https://{vault_hostname}.{tailscale_suffix}"

# ============ SYSTEM CONFIG ============

@router.get("/credentials", response_model=SystemConfig)
async def get_system_credentials(current_user = Depends(get_current_active_user)):
    """
    Obtiene las credenciales actuales del sistema (enmascaradas)
    """
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"})
    
    if not config:
        # Valores por defecto si no existe config
        return SystemConfig(
            git_provider="bitbucket",
            git_username="",
            git_token_masked="****",
            bitbucket_email="",
            bitbucket_workspace="",
            infra_repo_url="",
            domain="",
            dockerhub_username="",
            dockerhub_token_masked="****",
            github_org="",
            github_token_masked="****",
            github_is_org=False,
        )
    
    return SystemConfig(
        git_provider=config.get("git_provider", "bitbucket"),
        git_username=config.get("git_username", ""),
        git_token_masked=f"****{config.get('git_token', '')[-4:]}" if config.get("git_token") else "****",
        bitbucket_email=config.get("bitbucket_email", ""),
        bitbucket_workspace=config.get("bitbucket_workspace", ""),
        infra_repo_url=config.get("infra_repo_url", ""),
        domain=config.get("domain", ""),
        dockerhub_username=config.get("dockerhub_username", ""),
        dockerhub_token_masked=f"****{config.get('dockerhub_token', '')[-4:]}" if config.get("dockerhub_token") else "****",
        github_org=config.get("github_org", ""),
        github_token_masked=f"****{config.get('github_token', '')[-4:]}" if config.get("github_token") else "****",
        github_is_org=config.get("github_is_org", False),
        ai_provider=config.get("ai_provider", "deepseek"),
        ai_model=config.get("ai_model", "deepseek-chat"),
        ai_base_url=config.get("ai_base_url", "https://api.deepseek.com"),
        ai_api_key_masked=f"****{config.get('ai_api_key', '')[-4:]}" if config.get("ai_api_key") else "****",
        argocd_server=config.get("argocd_server", "http://argocd-server.argocd.svc.cluster.local:80"),
        argocd_username=config.get("argocd_username", "admin"),
        argocd_password_masked=f"****{config.get('argocd_password', '')[-4:]}" if config.get("argocd_password") else "****"
    )


@router.put("/credentials")
async def update_system_credentials(
    update: SystemConfigUpdate,
    current_user = Depends(get_current_active_user)
):
    """
    Actualiza credenciales del sistema.
    Solo actualiza los campos que se envían (no nulos)
    """
    db = get_db()
    
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()
    update_data["updated_by"] = current_user.username
    
    await db.system_config.update_one(
        {"_id": "main"},
        {"$set": update_data},
        upsert=True
    )
    
    return {"message": "Credentials updated successfully", "updated_fields": list(update_data.keys())}


@router.get("/credentials/raw")
async def get_raw_credentials(current_user = Depends(get_current_active_user)):
    """
    Obtiene credenciales SIN enmascarar (solo para uso interno/debug)
    ⚠️ Endpoint sensible
    """
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"})
    
    if not config:
        raise HTTPException(status_code=404, detail="No configuration found")
    
    # Remover _id de MongoDB
    config.pop("_id", None)
    return config


# ============ GIT PROVIDERS ============

@router.get("/providers")
async def list_git_providers(current_user = Depends(get_current_active_user)):
    """
    List available git providers and their configuration status.
    Only providers with valid credentials appear as selectable for deploys.
    """
    from app.services.git_provider import PROVIDERS, get_git_provider

    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}

    providers = []
    for name, cls in PROVIDERS.items():
        info = {
            "name": name,
            "display_name": cls.display_name,
            "configured": False,
            "active": config.get("git_provider", "bitbucket") == name,
        }
        if name == "bitbucket":
            info["configured"] = bool(
                config.get("git_token") and config.get("bitbucket_workspace")
            )
            info["workspace"] = config.get("bitbucket_workspace", "")
        elif name == "github":
            info["configured"] = bool(
                config.get("github_token") and config.get("github_org")
            )
            info["org"] = config.get("github_org", "")
            info["is_org"] = config.get("github_is_org", False)

        providers.append(info)

    return {"providers": providers}


class ProviderValidateRequest(BaseModel):
    provider: str
    # Optional overrides for testing credentials before saving
    token: Optional[str] = None
    workspace: Optional[str] = None  # Bitbucket workspace
    org: Optional[str] = None        # GitHub org/user
    is_org: Optional[bool] = None


@router.post("/providers/validate")
async def validate_provider(
    req: ProviderValidateRequest,
    current_user = Depends(get_current_active_user),
):
    """
    Validate credentials for a git provider.
    Can test with overrides before saving to system_config.
    """
    from app.services.git_provider import get_git_provider

    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}

    # Build credentials dict, preferring overrides
    credentials = {
        "git_user": config.get("git_username", ""),
        "git_token": config.get("git_token", ""),
        "bb_workspace": req.workspace or config.get("bitbucket_workspace", ""),
        "bitbucket_email": config.get("bitbucket_email", ""),
        "github_org": req.org or config.get("github_org", ""),
        "github_token": req.token or config.get("github_token", ""),
        "github_is_org": req.is_org if req.is_org is not None else config.get("github_is_org", False),
    }
    # Allow token override for bitbucket too
    if req.provider == "bitbucket" and req.token:
        credentials["git_token"] = req.token

    try:
        provider = get_git_provider(req.provider, credentials)
        result = await provider.validate_credentials()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return {"valid": False, "provider": req.provider, "error": str(e)}


@router.get("/vault/status")
async def get_vault_status(current_user = Depends(get_current_active_user)):
    """Returns Vault connectivity and configuration status for UI dashboards."""
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}

    vault_addr = config.get("vault_addr", VAULT_ADDR)
    vault_token = config.get("vault_token", "")
    ui_url = _build_vault_ui_url(config)

    status_payload = {
        "configured": bool(vault_addr and vault_token),
        "vault_addr": vault_addr,
        "vault_ui_url": ui_url,
        "reachable": False,
        "sealed": None,
        "initialized": None,
        "version": None,
        "health_status_code": None,
        "error": None,
    }

    if not vault_addr:
        status_payload["error"] = "vault_addr not configured"
        return status_payload

    try:
        async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
            response = await client.get(f"{vault_addr}/v1/sys/health")
            status_payload["health_status_code"] = response.status_code
            status_payload["reachable"] = response.status_code in (200, 429, 472, 473, 501, 503)

            if response.headers.get("content-type", "").startswith("application/json"):
                health = response.json()
                status_payload["sealed"] = health.get("sealed")
                status_payload["initialized"] = health.get("initialized")
                status_payload["version"] = health.get("version")
    except Exception as e:
        status_payload["error"] = str(e)

    return status_payload


@router.get("/vault/secrets")
async def list_vault_secrets(env: Optional[str] = None, current_user = Depends(get_current_active_user)):
    """Lists secret paths from Vault KV v2 metadata by environment."""
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}

    vault_addr = config.get("vault_addr", VAULT_ADDR)
    vault_token = config.get("vault_token", "")

    if not vault_addr or not vault_token:
        raise HTTPException(status_code=400, detail="Vault is not configured (vault_addr/vault_token)")

    target_envs = [env] if env else ["dev", "staging", "prod"]
    result = {"envs": {}, "errors": {}}

    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        for env_name in target_envs:
            try:
                response = await client.get(
                    f"{vault_addr}/v1/secret/metadata/{env_name}",
                    headers={"X-Vault-Token": vault_token},
                    params={"list": "true"}
                )

                if response.status_code == 404:
                    result["envs"][env_name] = []
                    continue

                if response.status_code != 200:
                    result["errors"][env_name] = f"HTTP {response.status_code}: {response.text[:180]}"
                    result["envs"][env_name] = []
                    continue

                payload = response.json()
                keys = payload.get("data", {}).get("keys", [])
                result["envs"][env_name] = sorted(keys)
            except Exception as e:
                result["errors"][env_name] = str(e)
                result["envs"][env_name] = []

    return result


@router.get("/vault/secrets/{env}/{app_name}")
async def get_vault_secret(env: str, app_name: str, reveal: bool = False, current_user = Depends(get_current_active_user)):
    """Reads a specific secret in Vault KV v2: secret/{env}/{app_name}."""
    if env not in {"dev", "staging", "prod"}:
        raise HTTPException(status_code=400, detail="env must be one of: dev, staging, prod")

    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}

    vault_addr = config.get("vault_addr", VAULT_ADDR)
    vault_token = config.get("vault_token", "")

    if not vault_addr or not vault_token:
        raise HTTPException(status_code=400, detail="Vault is not configured (vault_addr/vault_token)")

    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        response = await client.get(
            f"{vault_addr}/v1/secret/data/{env}/{app_name}",
            headers={"X-Vault-Token": vault_token}
        )

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Secret not found")

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Vault error: {response.text[:220]}")

    payload = response.json().get("data", {})
    data_values = payload.get("data", {})
    metadata = payload.get("metadata", {})

    if not reveal:
        data_values = {k: _mask_secret_value(v) for k, v in data_values.items()}

    return {
        "env": env,
        "app_name": app_name,
        "reveal": reveal,
        "keys": sorted(list(data_values.keys())),
        "data": data_values,
        "metadata": {
            "version": metadata.get("version"),
            "created_time": metadata.get("created_time"),
            "deletion_time": metadata.get("deletion_time"),
            "destroyed": metadata.get("destroyed"),
        }
    }


# ============ API TOKENS ============

@router.get("/tokens", response_model=List[APIToken])
async def list_api_tokens(current_user = Depends(get_current_active_user)):
    """
    Lista todos los API tokens del usuario actual
    """
    db = get_db()
    tokens = await db.api_tokens.find({"user": current_user.username}).to_list(100)
    
    result = []
    for t in tokens:
        result.append(APIToken(
            _id=str(t["_id"]),
            name=t["name"],
            scopes=t["scopes"],
            key_prefix=t["key"][:8] + "...",
            is_active=t.get("is_active", True),
            created_at=t["created_at"],
            last_used_at=t.get("last_used_at")
        ))
    
    return result


@router.post("/tokens", response_model=APITokenCreated, status_code=201)
async def create_api_token(
    token_data: APITokenCreate,
    current_user = Depends(get_current_active_user)
):
    """
    Crea un nuevo API Token.
    ⚠️ El token completo solo se muestra UNA VEZ en esta respuesta.
    """
    db = get_db()
    
    # Generar token seguro
    key = secrets.token_hex(32)  # 64 caracteres
    
    token_doc = {
        "user": current_user.username,
        "name": token_data.name,
        "key": key,
        "scopes": token_data.scopes,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "last_used_at": None
    }
    
    result = await db.api_tokens.insert_one(token_doc)
    
    return APITokenCreated(
        id=str(result.inserted_id),
        name=token_data.name,
        key=key,  # Solo esta vez se muestra completo
        scopes=token_data.scopes
    )


@router.delete("/tokens/{token_id}")
async def revoke_api_token(
    token_id: str,
    current_user = Depends(get_current_active_user)
):
    """
    Revoca (elimina) un API Token
    """
    from bson import ObjectId
    
    db = get_db()
    
    result = await db.api_tokens.delete_one({
        "_id": ObjectId(token_id),
        "user": current_user.username
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Token not found")
    
    return {"message": "Token revoked successfully"}


# ============ VALIDATE API TOKEN (para uso externo) ============

async def validate_api_token(api_key: str = Header(None, alias="X-API-Key")):
    """
    Valida un API Token y retorna el usuario/scopes.
    Usar como dependencia en endpoints que aceptan API Keys.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key required"
        )
    
    db = get_db()
    token = await db.api_tokens.find_one({"key": api_key, "is_active": True})
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API Key"
        )
    
    # Actualizar last_used_at
    await db.api_tokens.update_one(
        {"_id": token["_id"]},
        {"$set": {"last_used_at": datetime.utcnow()}}
    )
    
    return {
        "user": token["user"],
        "scopes": token["scopes"],
        "token_name": token["name"]
    }


def require_scope(required_scope: str):
    """
    Decorador para verificar que el token tiene el scope necesario.
    Uso: @router.get("/...", dependencies=[Depends(require_scope("apps:create"))])
    """
    async def checker(token_info: dict = Depends(validate_api_token)):
        if required_scope not in token_info["scopes"] and "admin" not in token_info["scopes"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token requires scope: {required_scope}"
            )
        return token_info
    return checker


# ============ TERRAFORM IMPORT ============

class TerraformCredentials(BaseModel):
    """Credenciales que se importan desde terraform.tfvars"""
    git_username: Optional[str] = None
    git_token: Optional[str] = None
    bitbucket_email: Optional[str] = None
    bitbucket_workspace: Optional[str] = None
    dockerhub_username: Optional[str] = None
    dockerhub_password: Optional[str] = None  # terraform usa "password", nosotros "token"
    domain: Optional[str] = None
    infra_repo_url: Optional[str] = None
    templates_repo: Optional[str] = None


@router.post("/credentials/import-terraform")
async def import_from_terraform(
    creds: TerraformCredentials,
    current_user = Depends(get_current_active_user)
):
    """
    Importa credenciales desde terraform.tfvars.
    Útil para sincronizar después de `terraform apply`.
    
    Ejemplo de uso:
    ```python
    # Script Python para leer terraform.tfvars y enviar aquí
    import hcl2
    with open('terraform.tfvars') as f:
        tfvars = hcl2.load(f)
    requests.post('/api/v1/system/credentials/import-terraform', json=tfvars)
    ```
    """
    db = get_db()
    
    update_data = {}
    
    # Mapeo de nombres terraform → nombres sistema
    mappings = {
        "git_username": "git_username",
        "git_token": "git_token",
        "bitbucket_email": "bitbucket_email",
        "bitbucket_workspace": "bitbucket_workspace",
        "dockerhub_username": "dockerhub_username",
        "dockerhub_password": "dockerhub_token",  # terraform usa password, nosotros token
        "domain": "domain",
        "infra_repo_url": "infra_repo_url",
        "templates_repo": "templates_repo",
    }
    
    for tf_key, sys_key in mappings.items():
        value = getattr(creds, tf_key, None)
        if value:
            update_data[sys_key] = value
    
    if not update_data:
        return {"message": "No credentials to import", "imported": 0}
    
    update_data["updated_at"] = datetime.utcnow()
    update_data["updated_by"] = f"{current_user.username} (terraform-import)"
    
    await db.system_config.update_one(
        {"_id": "main"},
        {"$set": update_data},
        upsert=True
    )
    
    return {
        "message": "Credentials imported from terraform successfully",
        "imported_fields": list(update_data.keys())
    }


@router.get("/environments")
async def list_environments():
    """
    Lista los ambientes disponibles para despliegue.
    """
    return [
        {"id": "dev", "name": "Development", "description": "For testing and development", "namespace": "dev"},
        {"id": "staging", "name": "Staging", "description": "Pre-production testing", "namespace": "staging"},
        {"id": "prod", "name": "Production", "description": "Live environment", "namespace": "prod"},
    ]


from pydantic import BaseModel as PydanticBaseModel
from fastapi import BackgroundTasks
import asyncio

class CredentialsStatusResponse(PydanticBaseModel):
    """Estado de las credenciales del sistema"""
    configured: bool
    git_configured: bool
    docker_configured: bool
    missing_fields: List[str]


# ============ GLOBAL SYNC ============

# Almacenamiento en memoria para el estado del sync
_sync_state = {
    "is_syncing": False,
    "last_sync_at": None,
    "last_sync_result": None,
    "last_sync_errors": [],
    "sync_progress": None
}


async def _perform_global_sync():
    """Ejecuta la sincronización global de todas las apps."""
    global _sync_state
    
    from app.services.argocd_service import ArgoCDService
    from app.db import get_db
    
    _sync_state["is_syncing"] = True
    _sync_state["sync_progress"] = {"stage": "starting", "percent": 0}
    
    results = {
        "apps_updated": 0,
        "apps_synced": 0,
        "pipelines_checked": 0,
        "errors": []
    }
    
    try:
        db = get_db()
        argo = ArgoCDService()
        
        # Stage 1: Get all apps from DB (10%)
        _sync_state["sync_progress"] = {"stage": "loading_apps", "percent": 10}
        apps = await db.apps.find({}).to_list(100)
        
        if not apps:
            _sync_state["sync_progress"] = {"stage": "completed", "percent": 100}
            _sync_state["last_sync_result"] = results
            _sync_state["is_syncing"] = False
            return results
        
        total_apps = len(apps)
        
        # Stage 2: Sync ArgoCD status for each app (10-70%)
        _sync_state["sync_progress"] = {"stage": "syncing_argocd", "percent": 15}
        
        for i, app in enumerate(apps):
            app_name = app.get("name", "unknown")
            percent = 15 + int((i / total_apps) * 55)
            _sync_state["sync_progress"] = {
                "stage": "syncing_argocd", 
                "percent": percent,
                "current_app": app_name
            }
            
            try:
                # Get ArgoCD status
                argo_data = await argo.get_application_status(app_name)
                
                update_data = {
                    "updated_at": datetime.utcnow()
                }
                
                if argo_data:
                    update_data["argocd_status"] = argo_data.get("health", {}).get("status", "Unknown")
                    update_data["argocd_sync_status"] = argo_data.get("sync", {}).get("status", "Unknown")
                    
                    # Extract pod info if available
                    resources = argo_data.get("resources", [])
                    pods = [r for r in resources if r.get("kind") == "Pod"]
                    if pods:
                        update_data["pod_count"] = len(pods)
                        update_data["pods_ready"] = len([p for p in pods if p.get("health", {}).get("status") == "Healthy"])
                    
                    results["apps_synced"] += 1
                else:
                    update_data["argocd_status"] = "NotDeployed"
                    update_data["argocd_sync_status"] = "Unknown"
                
                await db.apps.update_one(
                    {"_id": app["_id"]},
                    {"$set": update_data}
                )
                results["apps_updated"] += 1
                
            except Exception as e:
                results["errors"].append({
                    "app": app_name,
                    "error": str(e)
                })
        
        # Stage 3: Check pipeline status (70-90%)
        _sync_state["sync_progress"] = {"stage": "checking_pipelines", "percent": 75}
        
        from app.services.pipeline_service import PipelineService
        pipeline_svc = PipelineService()
        
        for i, app in enumerate(apps):
            app_name = app.get("name", "unknown")
            repo_name = app.get("repository_name") or app_name
            
            percent = 75 + int((i / total_apps) * 15)
            _sync_state["sync_progress"] = {
                "stage": "checking_pipelines", 
                "percent": percent,
                "current_app": app_name
            }
            
            try:
                # Get latest pipeline
                pipeline_status = await pipeline_svc.get_pipeline_status(repo_name)
                
                if pipeline_status and pipeline_status.get("state") != "error":
                    await db.apps.update_one(
                        {"_id": app["_id"]},
                        {"$set": {
                            "last_pipeline_status": pipeline_status.get("result", pipeline_status.get("state", "Unknown")),
                            "last_pipeline_at": pipeline_status.get("completed_on") or pipeline_status.get("created_on"),
                            "last_pipeline_uuid": pipeline_status.get("uuid")
                        }}
                    )
                    results["pipelines_checked"] += 1
                    
            except Exception as e:
                # Pipeline check is non-critical, just log
                pass
        
        # Stage 4: Finalize (90-100%)
        _sync_state["sync_progress"] = {"stage": "finalizing", "percent": 95}
        
        # Save sync record to DB
        await db.sync_history.insert_one({
            "type": "global_sync",
            "completed_at": datetime.utcnow(),
            "results": results,
            "triggered_by": "manual"
        })
        
        _sync_state["sync_progress"] = {"stage": "completed", "percent": 100}
        _sync_state["last_sync_at"] = datetime.utcnow()
        _sync_state["last_sync_result"] = results
        _sync_state["last_sync_errors"] = results["errors"]
        
    except Exception as e:
        _sync_state["sync_progress"] = {"stage": "error", "percent": 0}
        results["errors"].append({"global": str(e)})
        _sync_state["last_sync_errors"] = results["errors"]
        
    finally:
        _sync_state["is_syncing"] = False
    
    return results


@router.post("/sync")
async def trigger_global_sync(
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_active_user)
):
    """
    Trigger a global sync of all applications.
    
    This syncs:
    - ArgoCD health and sync status for all apps
    - Latest pipeline status from Bitbucket
    - Updates all app records in the database
    
    Runs in background, use /sync/status to check progress.
    """
    global _sync_state
    
    if _sync_state["is_syncing"]:
        return {
            "status": "already_running",
            "message": "A sync is already in progress",
            "progress": _sync_state["sync_progress"]
        }
    
    background_tasks.add_task(_perform_global_sync)
    
    return {
        "status": "started",
        "message": "Global sync started in background",
        "check_status": "/api/v1/system/sync/status"
    }


@router.get("/sync/status")
async def get_sync_status():
    """
    Get the current sync status and last sync results.
    """
    return {
        "is_syncing": _sync_state["is_syncing"],
        "progress": _sync_state["sync_progress"],
        "last_sync_at": _sync_state["last_sync_at"].isoformat() if _sync_state["last_sync_at"] else None,
        "last_sync_result": _sync_state["last_sync_result"],
        "last_sync_errors": _sync_state["last_sync_errors"]
    }


# ============ SYSTEM STATS ============

@router.get("/stats")
async def get_system_stats():
    """
    Get global system statistics.
    
    Returns counts of apps by status, template, environment,
    plus recent activity metrics.
    """
    db = get_db()
    
    # Get all apps
    apps = await db.apps.find({}).to_list(100)
    
    # Count by status
    status_counts = {}
    for app in apps:
        st = app.get("argocd_status", "Unknown")
        status_counts[st] = status_counts.get(st, 0) + 1
    
    # Count by template
    template_counts = {}
    for app in apps:
        tpl = app.get("template_id", "unknown")
        template_counts[tpl] = template_counts.get(tpl, 0) + 1
    
    # Count by environment
    env_counts = {}
    for app in apps:
        envs = app.get("environments", [])
        for env in envs:
            env_counts[env] = env_counts.get(env, 0) + 1
    
    # Recent activity (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_apps = await db.apps.count_documents({
        "created_at": {"$gte": seven_days_ago}
    })
    
    # Get sync history
    last_syncs = await db.sync_history.find({}).sort("completed_at", -1).limit(5).to_list(5)
    
    return {
        "total_apps": len(apps),
        "apps_by_status": status_counts,
        "apps_by_template": template_counts,
        "apps_by_environment": env_counts,
        "apps_created_last_7_days": recent_apps,
        "last_sync": _sync_state["last_sync_at"].isoformat() if _sync_state["last_sync_at"] else None,
        "sync_history": [{
            "completed_at": s["completed_at"].isoformat() if s.get("completed_at") else None,
            "apps_updated": s.get("results", {}).get("apps_updated", 0),
            "errors": len(s.get("results", {}).get("errors", []))
        } for s in last_syncs]
    }


# ============ HEALTH CHECK ============

@router.get("/health")
async def system_health():
    """
    Comprehensive system health check.
    
    Checks connectivity to:
    - MongoDB
    - ArgoCD API
    - Bitbucket API
    """
    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {}
    }
    
    # Check MongoDB
    try:
        db = get_db()
        await db.command("ping")
        health["services"]["mongodb"] = {"status": "healthy"}
    except Exception as e:
        health["services"]["mongodb"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"
    
    # Check ArgoCD
    try:
        from app.services.argocd_service import ArgoCDService
        argo = ArgoCDService()
        # Quick health check
        apps = await argo.list_applications()
        health["services"]["argocd"] = {
            "status": "healthy",
            "app_count": len(apps) if apps else 0
        }
    except Exception as e:
        health["services"]["argocd"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"
    
    # Check Bitbucket
    try:
        from app.services.pipeline_service import PipelineService
        pipeline_svc = PipelineService()
        # Quick check - test credentials by getting any app pipeline
        test_status = await pipeline_svc.get_pipeline_status("kaanbal-api")
        if test_status.get("state") == "error" and "credentials" in test_status.get("error", "").lower():
            health["services"]["bitbucket"] = {"status": "unhealthy", "error": "Credentials not configured"}
            health["status"] = "degraded"
        else:
            health["services"]["bitbucket"] = {"status": "healthy"}
    except Exception as e:
        health["services"]["bitbucket"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"
    
    return health


@router.post("/argocd/refresh")
async def refresh_argocd_all(
    current_user = Depends(get_current_active_user)
):
    """
    Force ArgoCD to hard-refresh all applications (re-read from Git).
    Invalidates manifest cache and forces a fresh pull.
    """
    from app.services.argocd_service import ArgoCDService

    argo = ArgoCDService()
    results = await argo.refresh_all_applications(hard=True)
    return results


@router.get("/credentials/status", response_model=CredentialsStatusResponse)
async def get_credentials_status():
    """
    Verifica si las credenciales están configuradas.
    Útil para mostrar warnings en el UI.
    """
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"})
    
    missing = []
    git_ok = False
    docker_ok = False
    
    if not config:
        return CredentialsStatusResponse(
            configured=False,
            git_configured=False,
            docker_configured=False,
            missing_fields=["git_username", "git_token", "dockerhub_username", "dockerhub_token"]
        )
    
    # Check git
    if config.get("git_username") and config.get("git_token"):
        git_ok = True
    else:
        if not config.get("git_username"):
            missing.append("git_username")
        if not config.get("git_token"):
            missing.append("git_token")
    
    # Check docker
    if config.get("dockerhub_username") and config.get("dockerhub_token"):
        docker_ok = True
    else:
        if not config.get("dockerhub_username"):
            missing.append("dockerhub_username")
        if not config.get("dockerhub_token"):
            missing.append("dockerhub_token")
    
    return CredentialsStatusResponse(
        configured=git_ok and docker_ok,
        git_configured=git_ok,
        docker_configured=docker_ok,
        missing_fields=missing
    )


@router.get("/deploy-diagnostic")
async def deploy_diagnostic(current_user = Depends(get_current_active_user)):
    """
    Diagnóstico completo del proceso de deploy.
    Verifica cada paso sin ejecutar nada destructivo.
    """
    import subprocess, shutil, re
    from app.config import settings as app_settings
    
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"})
    
    results = {
        "status": "ok",
        "checks": {},
        "credentials_source": "settings_fallback",
        "errors": []
    }
    
    # 1. Check credentials source
    if config:
        results["credentials_source"] = "mongodb"
        git_user = config.get("git_username", "")
        git_token = config.get("git_token", "")
        bb_workspace = config.get("bitbucket_workspace", app_settings.bitbucket_workspace)
        bb_email = config.get("bitbucket_email", "")
        dockerhub_user = config.get("dockerhub_username", "")
        dockerhub_token = config.get("dockerhub_token", "")
        templates_repo = config.get("templates_repo", "kaanbal-templates")
    else:
        git_user = app_settings.git_username
        git_token = app_settings.git_token
        bb_workspace = app_settings.bitbucket_workspace
        bb_email = ""
        dockerhub_user = app_settings.dockerhub_username
        dockerhub_token = app_settings.dockerhub_token
        templates_repo = "kaanbal-templates"
    
    # Masked view of credentials
    results["checks"]["credentials"] = {
        "git_username": git_user[:3] + "***" if git_user else "❌ MISSING",
        "git_token": git_token[:6] + "***" if git_token else "❌ MISSING",
        "bitbucket_workspace": bb_workspace or "❌ MISSING",
        "bitbucket_email": bb_email[:5] + "***" if bb_email else "⚠️ empty (will use git_username)",
        "dockerhub_username": dockerhub_user[:3] + "***" if dockerhub_user else "❌ MISSING",
        "dockerhub_token": dockerhub_token[:6] + "***" if dockerhub_token else "❌ MISSING",
        "templates_repo": templates_repo,
    }
    
    # 2. Validate git URL construction (the actual bug we're checking)
    auth_url = f"https://{git_user}:{git_token}@bitbucket.org/{bb_workspace}"
    # Check for problematic characters
    url_issues = []
    if "@" in git_user:
        url_issues.append(f"git_username contains '@' ({git_user[:5]}***) — this will break git HTTPS URLs!")
    if ":" in git_user:
        url_issues.append(f"git_username contains ':' — this will break git HTTPS URLs!")
    if not git_user:
        url_issues.append("git_username is empty!")
    if not git_token:
        url_issues.append("git_token is empty!")
    if not bb_workspace:
        url_issues.append("bitbucket_workspace is empty!")
    
    results["checks"]["git_url"] = {
        "constructed_url": f"https://{git_user[:3]}***:***@bitbucket.org/{bb_workspace}/REPO.git",
        "issues": url_issues if url_issues else ["✅ URL looks valid"]
    }
    if url_issues:
        results["errors"].extend(url_issues)
    
    # 3. Test git ls-remote (lightweight — no clone, just check auth)
    test_repo_url = f"https://{git_user}:{git_token}@bitbucket.org/{bb_workspace}/infra-gitops.git"
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", test_repo_url],
            capture_output=True, text=True, timeout=15
        )
        if proc.returncode == 0:
            branch_count = len(proc.stdout.strip().split("\n")) if proc.stdout.strip() else 0
            results["checks"]["git_auth"] = {
                "status": "✅ OK",
                "message": f"Successfully authenticated. Found {branch_count} branch(es) in infra-gitops."
            }
        else:
            stderr = re.sub(r'https://[^@]+@', 'https://***@', proc.stderr)
            results["checks"]["git_auth"] = {
                "status": "❌ FAILED",
                "message": f"git ls-remote failed: {stderr}"
            }
            results["errors"].append(f"Git auth failed: {stderr}")
    except subprocess.TimeoutExpired:
        results["checks"]["git_auth"] = {"status": "❌ TIMEOUT", "message": "git ls-remote timed out (15s)"}
        results["errors"].append("Git auth timed out")
    except Exception as e:
        sanitized = re.sub(r'https://[^@]+@', 'https://***@', str(e))
        results["checks"]["git_auth"] = {"status": "❌ ERROR", "message": sanitized}
        results["errors"].append(sanitized)
    
    # 4. Test templates repo
    templates_url = f"https://{git_user}:{git_token}@bitbucket.org/{bb_workspace}/{templates_repo}.git"
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", templates_url],
            capture_output=True, text=True, timeout=15
        )
        if proc.returncode == 0:
            results["checks"]["templates_repo"] = {"status": "✅ OK", "message": f"Templates repo '{templates_repo}' accessible."}
        else:
            stderr = re.sub(r'https://[^@]+@', 'https://***@', proc.stderr)
            results["checks"]["templates_repo"] = {"status": "❌ FAILED", "message": stderr}
            results["errors"].append(f"Templates repo failed: {stderr}")
    except Exception as e:
        sanitized = re.sub(r'https://[^@]+@', 'https://***@', str(e))
        results["checks"]["templates_repo"] = {"status": "❌ ERROR", "message": sanitized}
    
    # 5. Test Bitbucket API with email
    import httpx
    api_auth_user = bb_email if bb_email else git_user
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.bitbucket.org/2.0/repositories/{bb_workspace}?pagelen=1",
                auth=(api_auth_user, git_token)
            )
            if resp.status_code == 200:
                results["checks"]["bitbucket_api"] = {
                    "status": "✅ OK",
                    "message": f"API auth works with '{api_auth_user[:5]}***'. Workspace '{bb_workspace}' accessible."
                }
            else:
                results["checks"]["bitbucket_api"] = {
                    "status": "❌ FAILED",
                    "message": f"HTTP {resp.status_code}: {resp.text[:200]}"
                }
                results["errors"].append(f"Bitbucket API: HTTP {resp.status_code}")
    except Exception as e:
        results["checks"]["bitbucket_api"] = {"status": "❌ ERROR", "message": str(e)[:200]}
    
    # 6. Workspace path check
    workspace_path = app_settings.workspace_path
    try:
        import os
        os.makedirs(workspace_path, exist_ok=True)
        test_file = os.path.join(workspace_path, ".diag-test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        results["checks"]["workspace"] = {"status": "✅ OK", "path": workspace_path, "writable": True}
    except Exception as e:
        results["checks"]["workspace"] = {"status": "❌ FAILED", "path": workspace_path, "error": str(e)}
        results["errors"].append(f"Workspace not writable: {e}")
    
    # Final status
    if results["errors"]:
        results["status"] = "errors_found"
    
    return results


# ============ IMPORT FROM CLUSTER ============

@router.post("/import-from-cluster")
async def import_apps_from_cluster(current_user = Depends(get_current_active_user)):
    """
    Reads K8s Ingresses from dev/staging/prod namespaces to derive the real
    exposure per environment for each app, then upserts into MongoDB.
    
    This is idempotent: safe to run multiple times.
    - New apps → inserted with inferred data
    - Existing apps → exposure fields updated from K8s truth
    
    Use after terraform destroy+apply to restore MongoDB integrity.
    """
    import ssl
    import json as _json

    NAMESPACES = ["dev", "staging", "prod"]
    INFRA_APPS = {
        "kaanbal-api", "kaanbal-console", "datastore", "argocd-server",
        "vault", "tailscale-operator", "traefik", "cert-manager",
    }
    # Category hints from known templates (best-effort)
    TEMPLATE_HINTS = {
        "vue-medical-001":  ("vue3-spa",    "frontend"),
        "api-medical-001":  ("fastapi-api", "backend"),
        "mongo-med-001":    ("mongodb",     "database"),
        "mysql-bio-001":    ("mysql",       "database"),
        "postgresql-001":   ("postgresql",  "database"),
        "broker-test-001":  ("emqx",        "iot"),
    }
    # Port hints from templates that have multi-port definitions
    # Used to backfill exposure.ports when port data is missing from MongoDB
    PORT_HINTS: dict[str, dict] = {}
    try:
        from app.services.template_service import TemplateService
        _ts = TemplateService()
        _all_templates = await _ts.get_templates()
        for tmpl in _all_templates:
            tmpl_id = tmpl.get("id", "")
            if tmpl.get("ports"):
                PORT_HINTS[tmpl_id] = {
                    "ports": tmpl["ports"],
                    "port_defaults": tmpl.get("port_defaults", {}),
                }
    except Exception:
        pass  # Catalog unavailable — skip port backfill

    import os
    sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    sa_ca_path    = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    kube_host     = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    kube_port     = os.getenv("KUBERNETES_SERVICE_PORT", "443")
    kube_api      = f"https://{kube_host}:{kube_port}"

    if not os.path.exists(sa_token_path):
        raise HTTPException(status_code=503, detail="Not running inside a Kubernetes cluster")

    with open(sa_token_path) as f:
        sa_token = f.read().strip()

    headers = {"Authorization": f"Bearer {sa_token}"}

    # per_app_exposure[app_name][namespace] = "public"|"tailscale"|"internal"
    per_app_exposure: dict[str, dict[str, str]] = {}
    # per_app_ts_urls[app_name][namespace] = "https://actual-ts-hostname.ts.net"
    per_app_ts_urls: dict[str, dict[str, str]] = {}

    async with httpx.AsyncClient(verify=sa_ca_path, timeout=15.0) as client:
        for ns in NAMESPACES:
            url = f"{kube_api}/apis/networking.k8s.io/v1/namespaces/{ns}/ingresses"
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
            except Exception as e:
                continue  # namespace may not exist yet

            items = resp.json().get("items", [])
            for ingress in items:
                labels     = ingress.get("metadata", {}).get("labels", {})
                spec       = ingress.get("spec", {})
                status     = ingress.get("status", {})
                ing_class  = spec.get("ingressClassName", "")
                app_label  = labels.get("app", "")

                if not app_label or app_label in INFRA_APPS:
                    continue

                # Determine exposure type from ingressClass
                if ing_class == "tailscale":
                    exp_type = "tailscale"
                elif ing_class in ("nginx", "traefik"):
                    exp_type = "public"
                else:
                    exp_type = "internal"

                if app_label not in per_app_exposure:
                    per_app_exposure[app_label] = {}

                # Capture actual Tailscale URL from Ingress status (loadBalancer hostname)
                if ing_class == "tailscale":
                    lb_ingresses = status.get("loadBalancer", {}).get("ingress", [])
                    if lb_ingresses:
                        actual_hostname = lb_ingresses[0].get("hostname", "")
                        if actual_hostname:
                            if app_label not in per_app_ts_urls:
                                per_app_ts_urls[app_label] = {}
                            # Only store the "primary" ingress URL per env (first one; avoid dashboard overriding main)
                            ing_name = ingress.get("metadata", {}).get("name", "")
                            existing_url = per_app_ts_urls[app_label].get(ns)
                            # Prefer the named {app}-ts ingress over dashboard/extra ingresses
                            is_primary = ing_name == f"{app_label}-ts"
                            if not existing_url or is_primary:
                                per_app_ts_urls[app_label][ns] = f"https://{actual_hostname}"

                # If we already saw a different exposure type for this env,
                # mark as "both" (nginx + tailscale together)
                existing = per_app_exposure[app_label].get(ns)
                if existing and existing != exp_type:
                    per_app_exposure[app_label][ns] = "both"
                else:
                    per_app_exposure[app_label][ns] = exp_type

    # ── Upsert into MongoDB ──────────────────────────────────────────────────
    db = get_db()
    inserted = []
    updated  = []
    skipped  = []

    # Also include apps with zero ingresses (internal/database apps)
    # Fetch all ArgoCD apps to get the full list
    # (reuse apps already in MongoDB + any new ones from ArgoCD app names)
    existing_apps = await db.apps.find({}, {"name": 1, "template": 1, "category": 1}).to_list(200)
    existing_names = {a["name"] for a in existing_apps}

    # Merge: known apps from MongoDB + discovered from ingresses
    all_app_names = existing_names | set(per_app_exposure.keys())

    for app_name in sorted(all_app_names):
        env_map = per_app_exposure.get(app_name, {})  # {} = no ingresses = internal

        # Derive overall exposure type
        all_types = set(env_map.values())
        if not all_types:
            overall_type = "internal"
        elif all_types == {"public"}:
            overall_type = "public"
        elif all_types == {"tailscale"}:
            overall_type = "tailscale"
        elif "public" in all_types and "tailscale" in all_types:
            overall_type = "both"
        else:
            overall_type = list(all_types)[0]

        # Build per_env only if there's variation across envs
        per_env = env_map if len(set(env_map.values())) > 1 or (env_map and overall_type == "both") else None

        # Build connection_info.per_env_exposure with actual Tailscale URLs from K8s status
        app_ts_urls = per_app_ts_urls.get(app_name, {})
        per_env_exposure = {}
        for env, exp_type in env_map.items():
            env_info: dict = {"type": exp_type}
            if exp_type == "tailscale" and app_ts_urls.get(env):
                ts_url = app_ts_urls[env]
                env_info["tailscale_url"] = ts_url
                # Extract hostname from URL for backwards compat
                ts_hostname = ts_url.replace("https://", "").split(".")[0] if ts_url else None
                env_info["tailscale_hostname"] = ts_hostname
            per_env_exposure[env] = env_info

        # Fetch existing record early so we can extend per_env_exposure with internal envs
        tmpl, cat = TEMPLATE_HINTS.get(app_name, ("unknown", "backend"))
        existing = await db.apps.find_one({"name": app_name})

        # Extend per_env_exposure to include "internal" entries for envs without K8s ingresses.
        # Without this fix, envs with no ingress (internal) disappear from per_env_exposure,
        # causing the UI to fall back to the app-level 'both' type and show spurious buttons.
        if existing:
            app_envs = existing.get("environments", [])
            existing_pe = existing.get("connection_info", {}).get("per_env_exposure", {})
            existing_per_env_map = existing.get("exposure", {}).get("per_env") or {}
            for env in app_envs:
                if env not in per_env_exposure:
                    # Preserve original per_env_exposure entry or default to internal
                    per_env_exposure[env] = existing_pe.get(env, {"type": "internal"})
            # Rebuild full exposure.per_env including internal envs so the per-env map
            # always covers every deployed environment explicitly.
            full_env_map = dict(env_map)
            for env in app_envs:
                if env not in full_env_map:
                    full_env_map[env] = existing_per_env_map.get(env, "internal")
            all_types_full = set(full_env_map.values())
            if len(all_types_full) > 1 or (full_env_map and overall_type == "both"):
                per_env = full_env_map

        exposure_doc = {
            "exposure.type": overall_type,
            "exposure.per_env": per_env,
            "updated_at": datetime.utcnow(),
        }

        # Update connection_info.per_env_exposure (now includes internal envs)
        if per_env_exposure:
            exposure_doc["connection_info.per_env_exposure"] = per_env_exposure

        if existing and not existing.get("exposure", {}).get("ports"):
            app_template_id = existing.get("template", tmpl)
            if app_template_id in PORT_HINTS:
                exposure_doc["exposure.ports"] = PORT_HINTS[app_template_id]["ports"]
                exposure_doc["exposure.port_exposure"] = PORT_HINTS[app_template_id]["port_defaults"]

        # Check if app already exists (re-use fetched result)
        if existing:
            # Only update exposure fields — preserve everything else
            await db.apps.update_one(
                {"name": app_name},
                {"$set": exposure_doc}
            )
            updated.append({"name": app_name, "exposure": overall_type, "per_env": per_env})
        else:
            # Insert new record with inferred metadata
            envs = sorted(env_map.keys()) or ["prod"]
            new_doc = {
                "name":          app_name,
                "template":      tmpl,
                "category":      cat,
                "description":   f"Imported from cluster: {app_name}",
                "environments":  envs,
                "creation_mode": "config-only",
                "status":        "healthy",
                "exposure": {
                    "type":     overall_type,
                    "per_env":  per_env,
                    "public_path": "/",
                },
                "specs": {
                    "replicas": 1,
                    "port": 80,
                    "resources": {
                        "cpu_request": "100m", "cpu_limit": "500m",
                        "mem_request": "128Mi", "mem_limit": "512Mi",
                    },
                },
                "argocd_status":      "Unknown",
                "argocd_sync_status": "Unknown",
                "imported_from_cluster": True,
                "created_at":  datetime.utcnow(),
                "updated_at":  datetime.utcnow(),
            }
            await db.apps.insert_one(new_doc)
            inserted.append({"name": app_name, "exposure": overall_type, "per_env": per_env})

    return {
        "status":   "ok",
        "inserted": len(inserted),
        "updated":  len(updated),
        "apps":     inserted + updated,
        "message":  f"{len(inserted)} apps inserted, {len(updated)} updated from K8s ingresses",
    }


@router.get("/cluster/nodes")
async def cluster_nodes():
    """Fleet view: nodes, CPU/RAM, pressures, and pods grouped by node."""
    from app.services.cluster_inventory import fetch_cluster_inventory
    return await fetch_cluster_inventory()
