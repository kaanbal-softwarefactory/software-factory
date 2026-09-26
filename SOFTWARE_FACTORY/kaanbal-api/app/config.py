import logging
import secrets

from pydantic_settings import BaseSettings
from typing import Optional

from app.defaults import (
    MONGODB_URI,
    SECRET_KEY_DEV,
    WORKSPACE_PATH,
)

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # MongoDB
    mongodb_uri: str = MONGODB_URI

    # Git/Bitbucket - MUST be configured via .env, env vars, or system_config
    git_username: str = ""
    git_token: str = ""
    bitbucket_workspace: str = ""
    infra_repo_url: str = ""

    # DockerHub - MUST be configured
    dockerhub_username: str = ""
    dockerhub_token: str = ""

    # Domain - MUST be configured
    domain: str = ""

    # Workspace paths (use /tmp for container compatibility)
    workspace_path: str = WORKSPACE_PATH

    # Security. Sin valor, se genera una clave efímera (ver ensure_signing_key).
    SECRET_KEY: str = ""

    class Config:
        env_file = ".env"


def ensure_signing_key(current: str) -> str:
    """Clave con la que se firman las sesiones: la configurada, o una efímera.

    Un valor por defecto escrito en el código es una clave que conoce cualquiera
    que lea el repositorio: con ella se fabrica un token de administrador. En un
    clúster la clave llega de un Secret obligatorio (el pod no arranca sin él),
    pero una API levantada fuera de esos manifiestos —un `docker run`, un
    entorno de pruebas— la heredaría en silencio. Ahora, sin clave, cada proceso
    genera la suya: las sesiones no sobreviven a un reinicio, pero nadie puede
    forjarlas.
    """
    if current and current != SECRET_KEY_DEV:
        return current
    logger.warning(
        "SECRET_KEY no está definida (o es la clave de desarrollo histórica): se usa una "
        "clave efímera. Las sesiones se cierran al reiniciar; define SECRET_KEY para conservarlas."
    )
    return secrets.token_urlsafe(48)


settings = Settings()
settings.SECRET_KEY = ensure_signing_key(settings.SECRET_KEY)
