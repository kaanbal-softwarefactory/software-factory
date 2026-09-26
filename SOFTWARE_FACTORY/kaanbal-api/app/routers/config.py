from fastapi import APIRouter, Depends
from app.config import settings
from app.models import SystemConfig
from app.routers.auth import get_current_active_user

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get("")
async def get_config():
    """Obtener configuración actual del sistema"""
    return SystemConfig(
        git_username=settings.git_username,
        git_token_masked=f"****{settings.git_token[-4:]}" if settings.git_token else "",
        bitbucket_workspace=settings.bitbucket_workspace,
        infra_repo_url=settings.infra_repo_url,
        domain=settings.domain,
        dockerhub_username=settings.dockerhub_username
    )


@router.put("")
async def update_config(config: dict):
    """
    Actualizar configuración.
    Nota: En producción, esto debería actualizar un Secret de K8s
    """
    # TODO: Implementar actualización de secrets
    return {"message": "Config update not implemented yet - use K8s secrets"}
