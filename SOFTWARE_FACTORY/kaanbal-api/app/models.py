from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime
from enum import Enum


class ExposureType(str, Enum):
    """Modos de exposición por ambiente (ver docs/EXPOSURE_LIFECYCLE_BITACORA.md).

    public     → Ingress + Cloudflare HTTPS + subdominio
    tailscale  → MagicDNS VPN
    lan        → NodePort / IP de red local del nodo
    internal   → solo ClusterIP {app}.{env}.svc.cluster.local
    off        → sin expositores + replicas=0
    both       → atajo multi-superficie (paths públicos + resto VPN)
    """
    PUBLIC = "public"
    TAILSCALE = "tailscale"
    BOTH = "both"
    INTERNAL = "internal"
    LAN = "lan"
    OFF = "off"


class User(BaseModel):
    username: str
    email: Optional[str] = None
    disabled: Optional[bool] = None
    role: str = "user"  # "admin" or "user"


class UserInDB(User):
    hashed_password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class PortDefinition(BaseModel):
    """Definition of a single port exposed by an application"""
    name: str = Field(..., description="Port identifier, e.g. 'mqtt', 'dashboard', 'http'")
    port: int = Field(..., description="Port number, e.g. 1883, 18083, 80")
    protocol: str = Field(default="TCP", description="TCP or UDP")
    description: str = Field(default="", description="Human-readable description")


class ResourceSpec(BaseModel):
    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    mem_request: str = "128Mi"
    mem_limit: str = "512Mi"


class AppSpecs(BaseModel):
    replicas: int = 1
    port: int = 80
    resources: ResourceSpec = ResourceSpec()


class ExposureConfig(BaseModel):
    type: ExposureType = ExposureType.INTERNAL
    public_path: str = "/"
    tailscale_hostname: Optional[str] = None
    per_env: Optional[Dict[str, ExposureType]] = None
    # Multi-port support: per-port-per-env exposure
    ports: Optional[List[PortDefinition]] = Field(default=None, description="Port definitions for multi-port apps")
    # Legacy: { env: { port: "tailscale" } }
    # Edge:   { env: { port: ["internal","lan","tailscale"] } }
    port_exposure: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Per-env per-port channels. Values may be a mode string or a list of channels: "
            "{ 'prod': { 'mqtt': ['internal','lan','tailscale'], 'ws': ['public','lan'] } }"
        ),
    )


class Environment(str, Enum):
    """Ambientes de despliegue disponibles"""
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class CreationMode(str, Enum):
    """Modos de creación de apps"""
    SCAFFOLD = "scaffold"      # Crear desde CLI oficial (vue create, etc)
    EMPTY = "empty"            # Repo vacío, usuario sube código
    UPLOAD = "upload"          # Usuario sube ZIP o importa repo
    CONFIG_ONLY = "config-only"  # Solo K8s manifests, sin código


class AppStatus(str, Enum):
    """Estados de una app durante su ciclo de vida"""
    CREATED = "created"                # Registro creado, sin repo
    REPO_READY = "repo_ready"          # Repo existe, esperando código
    AWAITING_CODE = "awaiting_code"    # Repo vacío, usuario debe pushear
    PIPELINE_RUNNING = "pipeline_running"  # Pipeline ejecutándose
    PIPELINE_FAILED = "pipeline_failed"   # Pipeline falló
    IMAGE_READY = "image_ready"        # Docker image lista
    DEPLOYING = "deploying"            # ArgoCD sync en progreso
    HEALTHY = "healthy"                # Todo funcionando
    DEGRADED = "degraded"              # Algunos ambientes con problemas
    OFFLINE = "offline"                # App detenida intencionalmente


# ============ PRIMITIVOS V1 (BLUEPRINT RFC-0001) ============
# Domain, ServiceLink y Site son las 3 entidades que unifican
# DevOps + MLOps + IoT fleet. Ver BLUEPRINT.md §2-§3.


class DomainCreate(BaseModel):
    """Request para registrar un dominio adicional (multi-dominio)"""
    fqdn: str = Field(..., description="Dominio completo, ej: example.com")
    cloudflare_zone_id: Optional[str] = Field(default=None, description="Zone ID en Cloudflare (auto-detectable)")
    tunnel_id: Optional[str] = Field(default=None, description="Túnel CF propio; None = comparte el túnel default")
    is_default: bool = Field(default=False, description="Dominio por defecto para apps sin domain_id")
    client_id: Optional[str] = Field(default=None, description="Dominio dedicado de un cliente (white-label)")


class Domain(BaseModel):
    """Dominio en la base de datos. La instalación crea el primero (is_default=True)."""
    id: str = Field(alias="_id")
    fqdn: str
    cloudflare_zone_id: Optional[str] = None
    tunnel_id: Optional[str] = None
    is_default: bool = False
    client_id: Optional[str] = None
    created_at: datetime

    class Config:
        populate_by_name = True


class LinkVisibility(str, Enum):
    """Visibilidad de un puerto/servicio dentro de la matriz de vinculación"""
    PUBLIC = "public"          # internet vía Cloudflare Tunnel
    VPN = "vpn"                # tailnet (Tailscale operator)
    PRIVATE = "private"        # solo su namespace (default-deny)
    APP_SCOPED = "app-scoped"  # solo las apps explícitamente vinculadas


class ServiceLinkCreate(BaseModel):
    """Request para vincular dos apps (generaliza database_bindings).

    Un link genera: NetworkPolicy, variables {ALIAS}_*, ACLs (EMQX/Tailscale)
    y una arista en el diagrama de arquitectura.
    """
    from_app: str = Field(..., description="App consumidora (slug)")
    from_env: str = Field(..., description="Ambiente del consumidor: dev|staging|prod")
    to_app: str = Field(..., description="App proveedora (slug)")
    to_env: str = Field(..., description="Ambiente del proveedor")
    port_name: str = Field(default="http", description="Puerto lógico del proveedor (PortDefinition.name)")
    port_number: Optional[int] = Field(default=None, description="Puerto numérico; si None se resuelve del template/app")
    alias: Optional[str] = Field(default=None, description="Prefijo de variables inyectadas; default: TO_APP en mayúsculas")
    visibility: LinkVisibility = LinkVisibility.APP_SCOPED
    description: str = ""


class ServiceLink(BaseModel):
    """Vínculo app→app en la base de datos"""
    id: str = Field(alias="_id")
    from_app: str
    from_env: str
    to_app: str
    to_env: str
    port_name: str = "http"
    port_number: Optional[int] = None
    alias: str
    visibility: LinkVisibility = LinkVisibility.APP_SCOPED
    description: str = ""
    created_at: datetime

    class Config:
        populate_by_name = True


class SiteType(str, Enum):
    """Tipo de nodo de cómputo. Una sola tabla para workers, edge y GPU efímera."""
    CLOUD = "cloud"          # VPS/EC2 con k3s completo
    LOCAL = "local"          # PC del usuario (WSL2/Linux)
    EDGE = "edge"            # gateway IoT de un cliente (Pi, placa)
    EPHEMERAL = "ephemeral"  # instancia GPU creada por Terraform, se destruye al terminar


class SiteCreate(BaseModel):
    """Request para registrar un site (worker, PC local, gateway de cliente)"""
    name: str = Field(..., description="Slug único, ej: pc-alice, gw-acme-01")
    type: SiteType
    client_id: Optional[str] = Field(default=None, description="Solo sites edge de un cliente")
    labels: Dict[str, str] = Field(default_factory=dict, description='Capacidades: {"gpu": "true", "arch": "arm64"}')
    connectivity: str = Field(default="tailscale", description="tailscale | public-ip")
    agent: str = Field(default="k3s+argocd", description="k3s+argocd | k3s+fleet | gateway-agent")
    description: str = ""


class Site(BaseModel):
    """Site en la base de datos"""
    id: str = Field(alias="_id")
    name: str
    type: SiteType
    client_id: Optional[str] = None
    labels: Dict[str, str] = {}
    connectivity: str = "tailscale"
    agent: str = "k3s+argocd"
    description: str = ""
    status: str = "joining"  # joining | online | offline | draining
    resources: Dict[str, Any] = {}  # cpu, mem, disk reportados por heartbeat
    desired_state_version: Optional[int] = None  # última versión publicada (sites edge)
    last_heartbeat: Optional[datetime] = None
    joined_at: datetime

    class Config:
        populate_by_name = True


class SiteHeartbeat(BaseModel):
    """Payload que reporta el agente de un site"""
    status: str = "online"
    resources: Dict[str, Any] = Field(default_factory=dict)
    applied_state_version: Optional[int] = Field(default=None, description="Versión de desired-state aplicada (edge)")
    agent_version: Optional[str] = None
    apps: Optional[List[str]] = Field(default=None, description="Apps corriendo localmente (edge)")


class EnvironmentPlacement(BaseModel):
    """Dónde corre cada ambiente de una app (placement explícito v1)"""
    env: str = Field(..., description="dev | staging | prod")
    site_id: str = Field(..., description="Site destino; 'auto' reservado para scheduling v2")
    storage_class: str = Field(default="local-path", description="local-path | longhorn | objeto S3/MinIO")


class AppCreate(BaseModel):
    """Request body para crear una nueva app"""
    name: str = Field(..., description="Nombre de la app (slug)")
    template: str = Field(..., description="Template a usar: vue3-spa, fastapi-api, etc.")
    category: Optional[str] = Field(default=None, description="Template category: frontend, backend, database, workflow, etc.")
    app_group: Optional[str] = Field(default=None, description="Optional logical group for organizing related apps in UI")
    description: str = ""
    client_id: Optional[str] = None
    domain_id: Optional[str] = Field(default=None, description="Dominio del app; None = dominio default de la instalación")
    placements: Optional[List[EnvironmentPlacement]] = Field(default=None, description="Placement explícito por ambiente; None = site primario")
    environments: List[str] = Field(default=["dev"], description="Environments to deploy: dev, staging, prod")
    creation_mode: CreationMode = Field(default=CreationMode.SCAFFOLD, description="How to create the app")
    scaffold_option: Optional[str] = Field(default=None, description="Which scaffold to use (vue3, react, etc)")
    git_provider: Optional[str] = Field(default=None, description="Git provider override: bitbucket, github (uses system default if None)")
    protocols: List[str] = Field(default_factory=list, description="Optional protocol hints: http, websocket, grpc, tcp")
    database_bindings: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        default=None,
        description="Per-backend-env database links, e.g. { 'dev': [{app_name, env, alias}], 'prod': [...] }"
    )
    template_config: Optional[Dict[str, Any]] = Field(default=None, description="Dynamic config based on template schema")
    exposure: ExposureConfig = ExposureConfig()
    specs: AppSpecs = AppSpecs()


class App(BaseModel):
    """App en la base de datos"""
    id: str = Field(alias="_id")
    name: str
    template: str
    app_group: Optional[str] = None
    description: str = ""
    client_id: Optional[str] = None
    domain_id: Optional[str] = None
    placements: Optional[List[EnvironmentPlacement]] = None
    environments: List[str] = ["prod"]  # Array of environments: dev, staging, prod
    creation_mode: str = "scaffold"  # scaffold, empty, upload, config-only
    exposure: ExposureConfig
    specs: AppSpecs
    status: str = "created"  # created, repo_ready, awaiting_code, pipeline_running, pipeline_failed, healthy, degraded, offline
    repo_url: Optional[str] = None
    subdomain: Optional[str] = None
    # Pipeline tracking
    last_pipeline_status: Optional[str] = None  # SUCCESSFUL, FAILED, IN_PROGRESS
    last_pipeline_build: Optional[int] = None   # Build number
    last_pipeline_at: Optional[datetime] = None
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    class Config:
        populate_by_name = True


class ClientCreate(BaseModel):
    """Request body para crear un cliente"""
    name: str
    slug: str = Field(..., description="Identificador único (ej: acme-corp)")
    contact_email: str
    plan: str = "starter"  # starter, pro, enterprise


class Client(BaseModel):
    """Cliente en la base de datos"""
    id: str = Field(alias="_id")
    name: str
    slug: str
    contact_email: str
    plan: str
    apps: List[str] = []  # Lista de app IDs
    created_at: datetime
    
    class Config:
        populate_by_name = True


class SystemConfig(BaseModel):
    """Configuración del sistema"""
    git_provider: Optional[str] = "bitbucket"
    git_username: str
    git_token_masked: str  # Solo mostrar últimos 4 chars
    bitbucket_email: str
    bitbucket_workspace: str
    infra_repo_url: str
    domain: str
    dockerhub_username: str
    dockerhub_token_masked: str
    # GitHub
    github_org: Optional[str] = ""
    github_token_masked: Optional[str] = "****"
    github_is_org: Optional[bool] = False
    # AI Config
    ai_provider: Optional[str] = "deepseek"
    ai_model: Optional[str] = "deepseek-chat"
    ai_base_url: Optional[str] = "https://api.deepseek.com"
    ai_api_key_masked: Optional[str] = "****"
    # ArgoCD Config
    argocd_server: Optional[str] = "http://argocd-server.argocd.svc.cluster.local:80"
    argocd_username: Optional[str] = "admin"
    argocd_password_masked: Optional[str] = "****"


class SystemConfigUpdate(BaseModel):
    """Para actualizar configuración"""
    # Platform
    mode: Optional[str] = None
    domain: Optional[str] = None
    # Git
    git_provider: Optional[str] = None
    git_username: Optional[str] = None
    git_token: Optional[str] = None
    bitbucket_email: Optional[str] = None
    bitbucket_workspace: Optional[str] = None
    # GitHub
    github_org: Optional[str] = None
    github_token: Optional[str] = None
    github_is_org: Optional[bool] = None
    # Docker
    dockerhub_username: Optional[str] = None
    dockerhub_token: Optional[str] = None
    # Cloudflare
    cloudflare_token: Optional[str] = None
    cloudflare_account_id: Optional[str] = None
    # Tailscale
    tailscale_client_id: Optional[str] = None
    tailscale_client_secret: Optional[str] = None
    tailscale_dns_suffix: Optional[str] = None
    # AI Config
    ai_provider: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_model: Optional[str] = None
    ai_base_url: Optional[str] = None
    # ArgoCD Config
    argocd_server: Optional[str] = None
    argocd_username: Optional[str] = None
    argocd_password: Optional[str] = None


# ============ API TOKENS ============

class APITokenCreate(BaseModel):
    """Request para crear un API Token"""
    name: str = Field(..., description="Nombre descriptivo (ej: Jira Integration)")
    scopes: List[str] = Field(default=["read"], description="Permisos: read, write, apps:create, apps:delete, templates:manage")


class APIToken(BaseModel):
    """API Token en respuesta (sin key completa)"""
    id: str = Field(alias="_id")
    name: str
    scopes: List[str]
    key_prefix: str  # Solo primeros 8 chars
    is_active: bool = True
    created_at: datetime
    last_used_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True


class APITokenCreated(BaseModel):
    """Respuesta al crear token (única vez que se muestra key completa)"""
    id: str
    name: str
    key: str  # ⚠️ Solo se muestra UNA VEZ
    scopes: List[str]
    message: str = "Guarda este token, no podrás verlo de nuevo"


class WebhookDeployRequest(BaseModel):
    """Payload para webhook de deploy (compatible con tu n8n actual)"""
    metadata: Dict = {}
    project: Dict
    app: Dict
    specs: Dict = {}
    exposure: Optional[Dict] = None
    gitConfig: Dict = {}
    infra: Dict = {}


# ============ CUSTOM TEMPLATES ============

class TemplateStatus(str, Enum):
    """Estados de validación de un template personalizado"""
    DRAFT = "draft"              # Recién creado, sin validar
    VALIDATING = "validating"    # Pruebas en progreso
    VALIDATION_FAILED = "validation_failed"  # Alguna prueba falló
    READY = "ready"              # Validado y listo para usar


class TemplateTestApp(BaseModel):
    """App temporal de prueba para validar un template"""
    environment: str              # dev, staging, prod
    app_name: str                 # Nombre de la app de prueba
    status: str = "pending"       # pending, deploying, healthy, failed
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


class CustomTemplateCreate(BaseModel):
    """Request para crear un template personalizado"""
    id: str = Field(..., description="Slug único, ej: vue3-dashboard")
    name: str = Field(..., description="Nombre display")
    description: str = ""
    category: str = Field(..., description="frontend, backend, database, service")
    icon: str = "cube"
    stack: List[str] = []
    base_template: Optional[str] = None  # Si es variante de otro
    environments: List[str] = Field(default=["dev", "prod"], description="Ambientes que soporta")
    creation_modes: List[str] = Field(default=["scaffold", "empty"], description="Modos de creación permitidos")
    # Pipeline config
    dockerfile_template: Optional[str] = None
    pipeline_template: Optional[str] = None
    # K8s config
    default_port: int = 80
    default_replicas: int = 1
    health_check_path: str = "/"


class CustomTemplate(BaseModel):
    """Template personalizado en la base de datos"""
    id: str = Field(alias="_id")
    name: str
    description: str = ""
    category: str
    icon: str = "cube"
    stack: List[str] = []
    base_template: Optional[str] = None
    environments: List[str] = ["dev", "prod"]
    creation_modes: List[str] = ["scaffold", "empty"]
    # Status de validación
    status: TemplateStatus = TemplateStatus.DRAFT
    test_apps: List[TemplateTestApp] = []
    validation_started_at: Optional[datetime] = None
    validation_completed_at: Optional[datetime] = None
    # Pipeline config
    dockerfile_template: Optional[str] = None
    pipeline_template: Optional[str] = None
    # K8s config
    default_port: int = 80
    default_replicas: int = 1
    health_check_path: str = "/"
    # Metadata
    created_by: str = "system"
    created_at: datetime = None
    updated_at: datetime = None
    
    class Config:
        populate_by_name = True
