"""
App Deployer Service
====================
Replica la lógica de tu flujo de n8n para crear apps:
1. Crear proyecto/repo en Bitbucket
2. Clonar template
3. Personalizar archivos (sed replacements)
4. Push al nuevo repo
5. Agregar manifests k8s a infra-gitops
6. Push infra-gitops (ArgoCD detecta y despliega)

Soporta múltiples ambientes: dev, staging, prod
"""

import asyncio
import os
import re
import shutil
import subprocess
import logging
import secrets as secrets_module
import string
from typing import Optional
from datetime import datetime
from bson import ObjectId
import httpx

from app.config import settings
from app.defaults import (
    VAULT_ADDR,
    VAULT_HOSTNAME,
    TEMPLATES_REPO,
    PIPELINE_EMAIL_DOMAIN_FALLBACK,
    TAILSCALE_DNS_SUFFIX,
    TAILSCALE_API_BASE,
    TAILSCALE_OAUTH_URL,
    INGRESS_CLASS,
    INGRESS_CLUSTER_ISSUER,
)

logger = logging.getLogger(__name__)


class ScaffoldUnavailableError(Exception):
    """Raised when a template scaffold pre-condition is not met."""
    def __init__(self, template: str, message: str, resolution: str):
        super().__init__(message)
        self.template = template
        self.message = message
        self.resolution = resolution

    def to_dict(self) -> dict:
        return {
            "error": "scaffold_unavailable",
            "template": self.template,
            "message": self.message,
            "resolution": self.resolution,
        }


from app.models import AppCreate, WebhookDeployRequest, CreationMode
from app.db import get_db
from app.services import db_env, tailscale_guard
from app.services.template_service import TemplateService
from app.services.template_spec import TemplateSpec
from app.services.git_provider import GitProvider, get_git_provider, build_provider_from_config

# Protocol → Ingress annotations. Dual nginx+traefik so either controller works
# (lab/core use Traefik; older templates still mention nginx class names).
_PROTOCOL_NGINX_ANNOTATIONS = {
    "websocket": {
        "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "86400",
        "nginx.ingress.kubernetes.io/proxy-send-timeout": "86400",
        "traefik.ingress.kubernetes.io/service.sticky.cookie": "true",
        "traefik.ingress.kubernetes.io/router.middlewares": "",  # placeholder; timeouts via entrypoints
    },
    "sse": {
        "nginx.ingress.kubernetes.io/proxy-buffering": "off",
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
        "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
        "traefik.ingress.kubernetes.io/service.sticky.cookie": "true",
    },
    "grpc": {
        "nginx.ingress.kubernetes.io/backend-protocol": "GRPC",
        "traefik.ingress.kubernetes.io/service.serversscheme": "h2c",
    },
    "mqtt": {
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "86400",
        "nginx.ingress.kubernetes.io/proxy-send-timeout": "86400",
    },
}

# Prefer Traefik keys when generating fresh ingresses (lab default).
_PROTOCOL_TRAEFIK_ANNOTATIONS = {
    "websocket": {
        "traefik.ingress.kubernetes.io/service.sticky.cookie": "true",
    },
    "sse": {
        "traefik.ingress.kubernetes.io/service.sticky.cookie": "true",
    },
    "grpc": {
        "traefik.ingress.kubernetes.io/service.serversscheme": "h2c",
    },
}


class AppDeployer:
    def __init__(self):
        self.workspace = settings.workspace_path
        self.bb_workspace = settings.bitbucket_workspace
        # Credenciales se cargan dinámicamente desde MongoDB
        self._credentials = None
        self.template_service = TemplateService()
        # Git provider (loaded lazily via _load_credentials)
        self._provider: GitProvider | None = None
        # Dominio efectivo de la operación en curso (multi-dominio, RFC-0001 §3.1).
        # None = usar el dominio de la instalación. Cada request construye su
        # propio AppDeployer, así que este contexto no se comparte entre deploys.
        self._domain_ctx: dict | None = None

    async def bind_domain(self, app_doc: dict | None = None, domain_id: str | None = None):
        """Fija el dominio bajo el que corre esta operación.

        Resuelve domain_id → dominio default → dominio del instalador. Todo lo
        que lee `self.domain` (FQDN público, TLS, DNS, sustitución de templates)
        pasa a operar sobre el dominio de la app sin cambiar sus firmas.
        """
        from app.services import domain_service

        doc = dict(app_doc or {})
        if domain_id:
            doc["domain_id"] = domain_id
        resolved = await domain_service.resolve_for_app(doc)
        self._domain_ctx = {
            "fqdn": resolved.get("fqdn") or "",
            "zone_id": resolved.get("cloudflare_zone_id") or "",
            "tunnel_id": resolved.get("tunnel_id") or "",
            "domain_id": str(resolved["_id"]) if resolved.get("_id") else None,
        }
        logger.info(
            "Deploy bound to domain %s (source=%s)",
            self._domain_ctx["fqdn"], resolved.get("source"),
        )
        return self._domain_ctx

    async def _load_credentials(self, provider_override: str = None):
        """Carga credenciales desde MongoDB (system_config) y construye el git provider"""
        if self._credentials and self._provider and not provider_override:
            return self._credentials
            
        db = get_db()
        config = await db.system_config.find_one({"_id": "main"})
        
        if config:
            self._credentials = {
                "git_user": config.get("git_username", settings.git_username),
                "git_token": config.get("git_token", settings.git_token),
                "bb_workspace": config.get("bitbucket_workspace", settings.bitbucket_workspace),
                "domain": config.get("domain", settings.domain),
                "dockerhub_username": config.get("dockerhub_username", settings.dockerhub_username),
                "dockerhub_token": config.get("dockerhub_token", settings.dockerhub_token),
                "bitbucket_email": config.get("bitbucket_email", ""),
                "templates_repo": config.get("templates_repo", TEMPLATES_REPO),
                "tailscale_dns_suffix": config.get("tailscale_dns_suffix", TAILSCALE_DNS_SUFFIX),
                "tailscale_client_id": config.get("tailscale_client_id", ""),
                "tailscale_client_secret": config.get("tailscale_client_secret", ""),
                "vault_addr": config.get("vault_addr", VAULT_ADDR),
                "vault_token": config.get("vault_token", ""),
                "vault_hostname": config.get("vault_hostname", VAULT_HOSTNAME),
                "elastic_ip": config.get("cluster_ssh_host", ""),
                "ssh_key_path": config.get("ssh_key_path", ""),
                # Ingress controller realmente instalado en el cluster
                "ingress_class": config.get("ingress_class", INGRESS_CLASS),
                "ingress_cluster_issuer": config.get(
                    "ingress_cluster_issuer", INGRESS_CLUSTER_ISSUER),
                # Git provider selection
                "git_provider": config.get("git_provider", "bitbucket"),
                # GitHub-specific
                "github_org": config.get("github_org", ""),
                "github_token": config.get("github_token", "") or config.get("git_token", ""),
                # None = auto-detect in GitHubProvider._is_org() (org name != PAT user => org)
                "github_is_org": config.get("github_is_org") if "github_is_org" in config else None,
                # Cloudflare
                "cloudflare_token": config.get("cloudflare_token", ""),
                "cloudflare_account_id": config.get("cloudflare_account_id", ""),
                "cloudflare_tunnel_id": config.get("cloudflare_tunnel_id", ""),
                "cloudflare_zone_id": config.get("cloudflare_zone_id", ""),
            }
        else:
            # Fallback a settings/env vars
            self._credentials = {
                "git_user": settings.git_username,
                "git_token": settings.git_token,
                "bb_workspace": settings.bitbucket_workspace,
                "domain": settings.domain,
                "dockerhub_username": settings.dockerhub_username,
                "dockerhub_token": settings.dockerhub_token,
                "bitbucket_email": "",
                "templates_repo": TEMPLATES_REPO,
                "tailscale_dns_suffix": TAILSCALE_DNS_SUFFIX,
                "tailscale_client_id": "",
                "tailscale_client_secret": "",
                "vault_addr": VAULT_ADDR,
                "vault_token": "",
                "vault_hostname": VAULT_HOSTNAME,
                "elastic_ip": "",
                "ssh_key_path": "",
                "ingress_class": INGRESS_CLASS,
                "ingress_cluster_issuer": INGRESS_CLUSTER_ISSUER,
                "git_provider": "bitbucket",
                "github_org": "",
                "github_token": "",
                "github_is_org": None,
                # Cloudflare
                "cloudflare_token": "",
                "cloudflare_account_id": "",
                "cloudflare_tunnel_id": "",
                "cloudflare_zone_id": "",
            }
        
        # Build git provider
        provider_name = provider_override or self._credentials.get("git_provider", "bitbucket")
        self._provider = get_git_provider(provider_name, self._credentials)
        
        return self._credentials
    
    @property
    def provider(self) -> GitProvider:
        """Current git provider (set during _load_credentials)"""
        if not self._provider:
            raise RuntimeError("Call _load_credentials() before accessing provider")
        return self._provider
    @property
    def git_user(self):
        return self._credentials["git_user"] if self._credentials else settings.git_username
    
    @property
    def git_token(self):
        return self._credentials["git_token"] if self._credentials else settings.git_token
    
    @property
    def domain(self):
        """FQDN base de la operación en curso (dominio de la app, o el de la instalación)."""
        if self._domain_ctx and self._domain_ctx.get("fqdn"):
            return self._domain_ctx["fqdn"]
        return self._credentials["domain"] if self._credentials else settings.domain

    @property
    def cloudflare_zone_id(self):
        """Zone del dominio en curso. Nunca el zone cacheado del default: eso
        crearía los registros DNS de un dominio dentro de la zona de otro."""
        if self._domain_ctx:
            return self._domain_ctx.get("zone_id") or ""
        return (self._credentials or {}).get("cloudflare_zone_id", "")

    @property
    def cloudflare_tunnel_id(self):
        """Túnel del dominio en curso; los dominios sin túnel propio comparten el default."""
        if self._domain_ctx and self._domain_ctx.get("tunnel_id"):
            return self._domain_ctx["tunnel_id"]
        return (self._credentials or {}).get("cloudflare_tunnel_id", "")

    @property
    def ingress_class(self):
        """IngressClass real del cluster (k3s trae Traefik, no nginx)."""
        if not self._credentials:
            return INGRESS_CLASS
        return self._credentials.get("ingress_class") or INGRESS_CLASS

    @property
    def ingress_cluster_issuer(self):
        """ClusterIssuer de cert-manager, o "" si el TLS lo termina el edge."""
        if not self._credentials:
            return INGRESS_CLUSTER_ISSUER
        return self._credentials.get("ingress_cluster_issuer") or ""

    def _public_ingress_annotations(self, protocols=None):
        """Anotaciones de un Ingress público según lo instalado en el cluster."""
        annotations = {}
        if self.ingress_cluster_issuer:
            annotations["cert-manager.io/cluster-issuer"] = self.ingress_cluster_issuer
        if protocols:
            annotations.update(self._get_protocol_annotations(protocols))
        return annotations

    def _public_ingress_tls(self, hosts, secret_name):
        """Bloque TLS solo si cert-manager va a emitir el certificado.

        Detrás de Cloudflare Tunnel el certificado lo pone el edge y el túnel
        entra por HTTP: pedir TLS aquí solo genera secrets que nadie rellena.
        """
        if not self.ingress_cluster_issuer:
            return None
        return [{"hosts": hosts, "secretName": secret_name}]

    def _ingress_host_json6902_ops(self, host: str, tls_secret: str, indent: str = "    ") -> str:
        """JSON6902 ops to set Ingress host; TLS ops only when cluster-issuer is set.

        Base docker-hub Ingress omits spec.tls when INGRESS_CLUSTER_ISSUER is empty
        (Cloudflare edge TLS). Unconditional replace on /spec/tls/0/hosts/0 then
        breaks kustomize: 'doc is missing path: /spec/tls/0/hosts/0'.
        """
        ops = (
            f"{indent}- op: replace\n"
            f"{indent}  path: /spec/rules/0/host\n"
            f"{indent}  value: {host}\n"
        )
        if self.ingress_cluster_issuer:
            ops += (
                f"{indent}- op: replace\n"
                f"{indent}  path: /spec/tls/0/hosts/0\n"
                f"{indent}  value: {host}\n"
                f"{indent}- op: replace\n"
                f"{indent}  path: /spec/tls/0/secretName\n"
                f"{indent}  value: {tls_secret}\n"
            )
        return ops

    def _get_protocol_annotations(self, protocols: list) -> dict:
        """Merged Ingress annotations for real-time protocols (nginx + Traefik keys)."""
        merged = {}
        for p in (protocols or []):
            merged.update(_PROTOCOL_NGINX_ANNOTATIONS.get(p, {}))
            merged.update(_PROTOCOL_TRAEFIK_ANNOTATIONS.get(p, {}))
        # Drop empty placeholder values
        return {k: v for k, v in merged.items() if v != ""}

    def _is_root_domain_request(self, app_data: AppCreate) -> bool:
        # Una app ya creada lo lleva en su documento (is_root_domain); el Wizard
        # lo manda en template_config al crearla. Sin mirar lo primero, cualquier
        # operación posterior —reexponer, mudar de dominio, agregar ambiente—
        # reconstruía el homepage como <app>.<dominio> y lo sacaba de la raíz.
        if bool(getattr(app_data, "is_root_domain", False)):
            return True
        cfg = getattr(app_data, "template_config", {}) or {}
        for key in ("use_root_domain", "root_domain", "is_root_app"):
            val = cfg.get(key)
            if isinstance(val, bool) and val:
                return True
            if isinstance(val, str) and val.strip().lower() in {"1", "true", "yes", "on", "y"}:
                return True
            if isinstance(val, (int, float)) and val != 0:
                return True
        return False

    def _build_public_host(self, app_name: str, env: str, app_data: Optional[AppCreate] = None) -> str:
        use_root_domain = bool(app_data and self._is_root_domain_request(app_data))
        if env == "prod" and use_root_domain:
            return self.domain
        if env == "prod":
            return f"{app_name}.{self.domain}"
        return f"{env}-{app_name}.{self.domain}"

    def _build_public_host_tokenized(self, app_name: str, env: str, app_data: Optional[AppCreate] = None) -> str:
        """Legacy token placeholder hostnames — use configured domain, not hardcoded domains."""
        use_root_domain = bool(app_data and self._is_root_domain_request(app_data))
        domain = self.domain or "kaanbal.local"
        if env == "prod" and use_root_domain:
            return domain
        if env == "prod":
            return f"{app_name}.{domain}"
        return f"{env}-{app_name}.{domain}"

    def _sanitize_error(self, error_msg: str) -> str:
        """Strip credentials/tokens from error messages before exposing to users"""
        msg = str(error_msg)
        # Remove git token
        if self._credentials:
            token = self._credentials.get("git_token", "")
            if token:
                msg = msg.replace(token, "***")
            user = self._credentials.get("git_user", "")
            if user:
                msg = msg.replace(user, "***")
            email = self._credentials.get("bitbucket_email", "")
            if email:
                msg = msg.replace(email, "***")
            docker_token = self._credentials.get("dockerhub_token", "")
            if docker_token:
                msg = msg.replace(docker_token, "***")
        # Also strip from settings fallback
        for secret in [settings.git_token, settings.git_username]:
            if secret:
                msg = msg.replace(secret, "***")
        # Remove any remaining https://user:token@ patterns
        import re
        msg = re.sub(r'https://[^@]+@', 'https://***@', msg)
        return msg
        
    async def deploy(self, app_data: AppCreate, progress_callback=None) -> dict:
        """Deploy - returns when done. Optional progress_callback for SSE streaming."""

        async def emit(step: str, message: str, status: str = "running"):
            if progress_callback:
                await progress_callback({
                    "step": step,
                    "message": message,
                    "status": status,
                    "timestamp": datetime.utcnow().isoformat()
                })

        # Cargar credenciales de MongoDB (+ build git provider)
        # Allow per-deploy provider override via app_data or default from system_config
        provider_override = getattr(app_data, 'git_provider', None)
        await self._load_credentials(provider_override=provider_override)
        await emit("credentials", f"Credentials loaded (provider: {self.provider.display_name})")

        # Multi-dominio: fijar el dominio antes de calcular cualquier FQDN, TLS o DNS.
        await self.bind_domain(domain_id=getattr(app_data, "domain_id", None))
        await emit("domain", f"Domain: {self.domain}")

        app_name = app_data.name
        template_id = app_data.template
        environments = getattr(app_data, 'environments', ['prod'])
        template_config = getattr(app_data, 'template_config', {}) or {}

        # Get template details (or build synthetic for custom docker images)
        custom_docker = getattr(app_data, 'custom_docker', None)
        if template_id == '__custom__' and custom_docker:
            await emit("template", f"Custom Docker image: {custom_docker.get('image', 'unknown')}")
            docker_image = custom_docker.get('image', '')
            custom_port = custom_docker.get('port', 8080)
            custom_storage = custom_docker.get('storage')
            custom_mount = custom_docker.get('mount_path', '/data')
            template_details = {
                "id": "__custom__",
                "name": f"Custom: {docker_image.split(':')[0]}",
                "description": f"Custom deployment of {docker_image}",
                "category": "custom",
                "docker_image": docker_image,
                "port": custom_port,
                "creation_modes": ["config-only"],
                "needs_repo": False,
                "status": "ready",
                "env_vars": [],
                "secrets": [],
                "volumes": [{"name": "data", "mount_path": custom_mount, "size": custom_storage}] if custom_storage else [],
                "config_schema": {},
            }
            await emit("template", f"Custom image configured: {docker_image} (port {custom_port})", "success")
        else:
            await emit("template", f"Loading template: {template_id}")
            template_details = await self.template_service.get_template_details(template_id)
            if not template_details:
                 raise Exception(f"Template {template_id} not found in catalog")
            await emit("template", f"Template loaded: {template_details.get('name', template_id)}", "success")

        # Build TemplateSpec — single source of truth for template behavior
        spec = TemplateSpec(template_details)

        # Auto-detect creation_mode from template if caller used default (scaffold)
        # Config-only templates (databases, EMQX, etc.) don't need repo/scaffold
        template_creation_modes = template_details.get("creation_modes", [])
        needs_repo = template_details.get("needs_repo", True)
        if app_data.creation_mode == CreationMode.SCAFFOLD:
            if not needs_repo and "config-only" in template_creation_modes:
                app_data.creation_mode = CreationMode.CONFIG_ONLY
                await emit("template", "Auto-detected config-only mode (no repo needed)")
            elif "config-only" in template_creation_modes and "scaffold" not in template_creation_modes:
                app_data.creation_mode = CreationMode.CONFIG_ONLY
                await emit("template", "Auto-detected config-only mode (template does not support scaffold)")

        # Sync specs.port from template catalog if the frontend sent the default (80)
        # This ensures Tailscale Ingress, connection_info, etc. all use the correct port
        template_port = template_details.get("port")
        if template_port and app_data.specs and app_data.specs.port == 80 and template_port != 80:
            app_data.specs.port = template_port

        # Pre-deploy gate: verify Tailscale operator is healthy before creating
        # tailscale-exposed apps. Prevents silent failures where proxy pods never start.
        needs_tailscale = any(
            self._get_env_exposure(app_data, env) in ("tailscale", "both")
            for env in environments
        )
        if needs_tailscale:
            ts_ok, ts_msg = await self._check_tailscale_operator_health()
            if not ts_ok:
                raise ScaffoldUnavailableError(
                    template=template_id,
                    message=ts_msg,
                    resolution="Check 'kubectl get pods -n tailscale' and wait for the operator to be Running before retrying."
                )
            await emit("tailscale", ts_msg, "success")

        # Ensure workspace directory exists — use per-deploy unique subdirectory
        # to prevent race conditions when multiple deploys run concurrently.
        import uuid
        deploy_id = uuid.uuid4().hex[:8]
        deploy_workspace = f"{self.workspace}/deploy-{app_name}-{deploy_id}"
        os.makedirs(deploy_workspace, exist_ok=True)

        # Paths
        templates_repo = self._credentials.get("templates_repo", TEMPLATES_REPO)
        templates_path_clone = f"{deploy_workspace}/kaanbal-templates-clone"
        new_app_path = f"{deploy_workspace}/{app_name}"
        infra_path = f"{deploy_workspace}/infra-gitops"

        try:
            # 1. Clonar repos necesarios (templates monorepo + infra)
            await emit("clone", "Cloning template and infrastructure repositories...")
            await self._clone_repos(templates_repo, infra_path, templates_path_clone)
            await emit("clone", "Repositories cloned", "success")

            # 2. Crear repo en proveedor git (skip for config-only)
            repo_url = ""
            if app_data.creation_mode != CreationMode.CONFIG_ONLY:
                await emit("repo", f"Creating {self.provider.display_name} repository: {app_name}")
                repo_url = await self.provider.create_repo(app_name)
                await emit("repo", f"Repository created: {app_name}", "success")
            
            # 3. Preparar código de la aplicación
            if app_data.creation_mode == CreationMode.SCAFFOLD:
                await emit("scaffold", "Scaffolding application from template...")
                await self._scaffold_app(new_app_path, app_name, template_details, app_data, templates_path_clone)
                await emit("scaffold", "Application scaffolded", "success")

            elif app_data.creation_mode == CreationMode.EMPTY:
                await emit("scaffold", "Creating empty repository structure...")
                await self._create_empty_app(new_app_path, app_name)
                await emit("scaffold", "Empty repository created", "success")

            elif app_data.creation_mode == CreationMode.CONFIG_ONLY:
                 await emit("scaffold", "Config-only mode - no code generation needed", "success")

            else: # UPLOAD / COPY (Legacy)
                 # Determine template source path
                 category = template_details.get("category", "frontend")
                 template_src = os.path.join(templates_path_clone, f"templates/{category}/{template_id}")
                 
                 # Fallback support for flat structure
                 if not os.path.exists(template_src):
                     template_src = os.path.join(templates_path_clone, template_id)
                     
                 if not os.path.exists(template_src):
                     raise Exception(f"Template source not found at {template_src}")
                     
                 await self._copy_template_code(template_src, new_app_path, app_data)

            # 4. Pipeline & Dockerfile setup (if applicable)
            if app_data.creation_mode != CreationMode.CONFIG_ONLY:
                # If scaffolded or empty, we might need to inject standard pipeline/dockerfile
                await emit("pipeline", "Generating CI/CD pipeline and Dockerfile...")
                await self._setup_pipeline_and_docker(new_app_path, template_details, app_data, environments, templates_path_clone)
                await emit("pipeline", "Pipeline configured", "success")

                # 5. Push al nuevo repo (pipelines NOT enabled yet — no auto-trigger)
                await emit("push", f"Pushing code to repository...")
                await self._push_new_repo(new_app_path, repo_url, app_name)
                await emit("push", "Code pushed to repository", "success")
            
            # 6. Agregar manifests a infra-gitops
            # Locate k8s source
            await emit("k8s", "Preparing Kubernetes manifests...")
            k8s_base = template_details.get("k8s_base")
            if k8s_base:
                k8s_src = os.path.join(templates_path_clone, k8s_base)
            else:
                # Guess based on legacy structure
                category = template_details.get("category", "")
                k8s_src = os.path.join(templates_path_clone, f"templates/{category}/{template_id}/k8s")
                if not os.path.exists(k8s_src):
                    k8s_src = os.path.join(templates_path_clone, template_id, "k8s")

            if os.path.exists(k8s_src) and os.listdir(os.path.join(k8s_src, "base", "") if os.path.isdir(os.path.join(k8s_src, "base")) else k8s_src):
                await self._add_to_infra(infra_path, k8s_src, app_data, environments, spec)
                await emit("k8s", f"Kubernetes manifests added for {len(environments)} environment(s)", "success")
            elif template_details.get("docker_image"):
                # Dynamic manifest generation for Docker Hub services
                await emit("k8s", f"Generating K8s manifests for {template_details['docker_image']}...")
                self._generate_docker_hub_manifests(infra_path, app_name, template_details, app_data, environments)
                # Now run _add_to_infra-like overlay processing (exposure, tailscale, etc.)
                docker_dest = os.path.join(infra_path, "apps", app_name)
                await self._process_overlays_for_docker_hub(docker_dest, app_name, app_data, environments, spec)
                await emit("k8s", f"Kubernetes manifests generated for {len(environments)} environment(s)", "success")
            else:
                await emit("k8s", "No K8s templates found - skipping manifests", "success")

            # 6b. Generate random secrets and write to Vault + patch overlays
            await emit("secrets", f"Generating secrets for {len(environments)} environment(s)...")
            env_secrets = self._generate_app_secrets_from_spec(spec, app_name, environments)

            # 6b-bis. Resolve database bindings: read DB secrets from Vault, build
            # connection URIs per binding and merge them into env_secrets for the
            # backend so they are mounted as env vars in the deployment.
            if getattr(app_data, "database_bindings", None):
                await emit("db_bindings", "Resolving database bindings...")
                db_env_vars = await self._resolve_database_bindings(app_name, app_data, environments, emit)
                if db_env_vars:
                    for env, vars_map in db_env_vars.items():
                        env_secrets.setdefault(env, {}).update(vars_map)
                    await emit("db_bindings", f"Linked DBs injected into {len(db_env_vars)} environment(s)", "success")
                else:
                    await emit("db_bindings", "No database bindings produced env vars", "warning")

            for env in environments:
                self._patch_overlay_secrets(infra_path, app_name, env, env_secrets)
            await emit("secrets", "Secrets generated and patched into overlays", "success")

            await emit("vault", "Writing secrets to Vault...")
            vault_result = await self._write_secrets_to_vault(app_name, env_secrets, emit)
            if vault_result:
                await emit("vault", "All secrets written to Vault", "success")
            else:
                await emit("vault", "Vault not configured - secrets only in kustomize overlays", "warning")

            # 7. Push infra-gitops
            await emit("infra_push", "Pushing infrastructure changes to GitOps repo...")
            await self._push_infra(infra_path, app_name, environments)
            await emit("infra_push", "Infrastructure updated (ArgoCD will sync)", "success")

            # 7b. Create Cloudflare DNS via DnsPublisherService (retries, independent)
            from app.services.exposure import DnsPublisherService, TailscalePublisherService

            has_public = any(
                self._get_env_exposure(app_data, env) in ("public", "both")
                for env in environments
            )
            has_ts = any(
                self._get_env_exposure(app_data, env) in ("tailscale", "both")
                for env in environments
            )
            if has_public:
                public_fqdns = []
                for env in environments:
                    env_exposure = self._get_env_exposure(app_data, env)
                    if env_exposure in ("public", "both"):
                        public_fqdns.append(self._build_public_host(app_name, env, app_data))
                public_fqdns = list(dict.fromkeys(public_fqdns))

                await emit("dns", f"Creating DNS records ({len(public_fqdns)}): {', '.join(public_fqdns)}...")

                async def _create_all_dns(_hostname=None):
                    return await self._setup_cloudflare_dns(app_name, public_fqdns)

                dns_pub = DnsPublisherService()
                # One publisher call covers the batch; create_fn ignores per-host arg.
                dns_result = await dns_pub.publish(
                    hostname=public_fqdns[0] if public_fqdns else app_name,
                    domain=self.domain,
                    ensure=True,
                    create_fn=_create_all_dns,
                )
                if dns_result.ok:
                    await emit(
                        "dns",
                        f"DNS records ready (attempts={dns_result.attempts}): {', '.join(public_fqdns)}",
                        "success",
                    )
                elif dns_result.status == "pending":
                    await emit("dns", f"DNS pending: {dns_result.detail}", "warning")
                else:
                    await emit("dns", "Cloudflare not configured - create DNS record manually", "warning")

            if has_ts:
                ts_suffix = self._credentials.get("tailscale_dns_suffix", TAILSCALE_DNS_SUFFIX)
                ts_pub = TailscalePublisherService()
                for env in environments:
                    if self._get_env_exposure(app_data, env) not in ("tailscale", "both"):
                        continue
                    magic = f"{env}-{app_name}.{ts_suffix}"
                    await emit("tailscale", f"Waiting Tailscale device {magic}...")
                    ts_result = await ts_pub.publish(magic_hostname=magic, ensure=True)
                    level = "success" if ts_result.ok else (
                        "warning" if ts_result.status == "pending" else "warning"
                    )
                    await emit(
                        "tailscale",
                        f"{magic}: {ts_result.detail} (attempts={ts_result.attempts})",
                        level,
                    )
            
            if app_data.creation_mode != CreationMode.CONFIG_ONLY:
                # 8. Configure CI/CD variables (BEFORE enabling CI)
                await emit("pipeline_vars", "Configuring CI/CD variables...")
                await self._configure_ci_variables(app_name)
                await emit("pipeline_vars", "CI/CD variables configured", "success")

                # 9. Enable CI/CD
                await emit("enable_pipelines", "Enabling CI/CD...")
                await self.provider.enable_ci(app_name)
                await emit("enable_pipelines", "CI/CD enabled", "success")

                # 10. Create environment branches
                await emit("branches", f"Creating environment branches: {', '.join(environments)}")
                await self._create_environment_branches(new_app_path, repo_url, environments)
                await emit("branches", "Environment branches created", "success")

                # 11. Trigger first CI run for each branch
                await emit("first_pipelines", "Triggering first CI/CD runs...")
                await self._trigger_initial_ci(app_name, environments)
                await emit("first_pipelines", "Initial CI/CD runs triggered for all environments", "success")
            
            # Scan rendered manifests for template-owned Tailscale Ingresses
            # (e.g. EMQX dashboard ingress defined in base/ingress.yaml)
            # Must happen BEFORE cleanup since infra_path is deleted
            template_ts_ingresses = self._scan_template_tailscale_ingresses(
                infra_path, app_name, environments
            )

            # Cleanup — remove entire per-deploy workspace
            self._cleanup([deploy_workspace])

            subdomain = self._build_public_host(app_name, "prod", app_data)

            # Get tailscale_dns_suffix from credentials (loaded from system_config)
            ts_dns_suffix = self._credentials.get("tailscale_dns_suffix", TAILSCALE_DNS_SUFFIX)
            vault_hostname = self._credentials.get("vault_hostname", VAULT_HOSTNAME)

            # Build connection metadata for the deployed app
            port = spec.port
            # vault_hostname may be just the hostname or full FQDN — handle both
            if vault_hostname and vault_hostname.endswith(f".{ts_dns_suffix}"):
                vault_ui_url = f"https://{vault_hostname}"
            elif vault_hostname:
                vault_ui_url = f"https://{vault_hostname}.{ts_dns_suffix}"
            else:
                vault_ui_url = f"https://vault.{self.domain}"

            # Build public URL for the app
            app_url = f"https://{subdomain}"
            is_tcp = spec.is_tcp
            tcp_port = spec.tcp_port if is_tcp else None
            tailscale_tcp_ports = spec.tailscale_tcp_ports
            connection_info = {
                "internal_dns_pattern": f"{app_name}.{{env}}.svc.cluster.local",
                "port": port,
                "secrets_name": f"{app_name}-secrets",
                "vault_path": f"secret/{{env}}/{app_name}",
                "vault_ui": vault_ui_url,
                "tailscale_dns_suffix": ts_dns_suffix,
                "is_tcp_service": is_tcp,
                "tcp_port": tcp_port,
                "per_env_exposure": {},
            }
            # Add multi-port TCP info if template has tailscale_tcp_ports
            if tailscale_tcp_ports:
                tcp_port_info = {}
                for tp in tailscale_tcp_ports:
                    pname = tp.get("name", "tcp")
                    pnum = tp.get("port")
                    tcp_port_info[pname] = {
                        "port": pnum,
                        "hostname_pattern": f"{{env}}-{app_name}-{pname}",
                        "host_pattern": f"{{env}}-{app_name}-{pname}.{ts_dns_suffix}",
                    }
                connection_info["tailscale_tcp_ports"] = tcp_port_info
            for env in environments:
                env_exposure = self._get_env_exposure(app_data, env)
                # For TCP services (Service-based exposure), Tailscale uses the annotation hostname directly
                # For web apps (Service-based exposure), hostname is set via tailscale.com/hostname annotation
                if env_exposure in ("tailscale", "both"):
                    if is_tcp:
                        ts_hostname = f"{env}-{app_name}"
                    elif tailscale_tcp_ports:
                        # Multi-port TCP app: primary TS hostname is the first TCP port's Service
                        first_tcp = tailscale_tcp_ports[0]
                        ts_hostname = f"{env}-{app_name}-{first_tcp.get('name', 'tcp')}"
                    else:
                        # Service-based exposure: hostname is set via tailscale.com/hostname annotation
                        ts_hostname = f"{env}-{app_name}"
                else:
                    ts_hostname = None

                # If deployer didn't set tailscale but template defines its own TS Ingress,
                # use the template-owned hostname (e.g. EMQX dashboard)
                if not ts_hostname and env in template_ts_ingresses:
                    ts_hostname = template_ts_ingresses[env]
                    # Override exposure type since template provides Tailscale access
                    env_exposure = "tailscale"

                env_info = {
                    "type": env_exposure,
                    "tailscale_hostname": ts_hostname,
                    "tailscale_url": f"http://{ts_hostname}.{ts_dns_suffix}" if ts_hostname else None,
                }
                # For TCP services, add direct TCP connection info
                if is_tcp and ts_hostname:
                    env_info["tailscale_tcp_host"] = f"{ts_hostname}.{ts_dns_suffix}"
                    env_info["tailscale_tcp_port"] = tcp_port
                # For multi-port TCP apps, add per-port TCP connection info
                if tailscale_tcp_ports and env_exposure in ("tailscale", "both"):
                    tcp_env_ports = {}
                    for tp in tailscale_tcp_ports:
                        pname = tp.get("name", "tcp") if isinstance(tp, dict) else str(tp)
                        pnum = tp.get("port") if isinstance(tp, dict) else None
                        tcp_env_ports[pname] = {
                            "port": pnum,
                            "tailscale_hostname": f"{env}-{app_name}-{pname}",
                            "tailscale_host": f"{env}-{app_name}-{pname}.{ts_dns_suffix}",
                        }
                    env_info["tailscale_tcp_ports"] = tcp_env_ports

                # Fase 3: multi-surface URLs (editor/webhook/mcp/api/ws/dashboard)
                try:
                    from app.services.exposure.connection_surfaces import (
                        build_env_surfaces, infer_surfaces,
                    )
                    public_host = self._build_public_host(app_name, env, app_data)
                    cat = (getattr(app_data, "category", None) or
                           (spec.category if spec else "") or "")
                    tcp_list = []
                    for tp in (tailscale_tcp_ports or []):
                        if isinstance(tp, dict):
                            tcp_list.append(tp)
                        else:
                            tcp_list.append({"name": str(tp)})
                    surfaces = build_env_surfaces(
                        mode=env_exposure,
                        public_hostname=public_host,
                        ts_hostname=ts_hostname or f"{env}-{app_name}",
                        ts_suffix=ts_dns_suffix,
                        app_name=app_name,
                        env=env,
                        category=cat,
                        tcp_ports=tcp_list or None,
                        surfaces=infer_surfaces(spec=spec, category=cat),
                    )
                    for key in (
                        "editor_url", "webhook_url", "mcp_url", "api_url",
                        "ws_url", "health_url", "dashboard_url", "surfaces",
                        "public_url", "cluster_url", "status", "tcp",
                    ):
                        if key in surfaces:
                            env_info[key] = surfaces[key]
                except Exception as exc:
                    logger.warning("connection surfaces failed for %s/%s: %s", app_name, env, exc)

                connection_info["per_env_exposure"][env] = env_info

            # Include multi-port info from template catalog so the UI can display all ports
            template_ports = template_details.get("ports")  # e.g. EMQX: 5 ports, n8n: 3 ports
            template_port_defaults = template_details.get("port_defaults")  # per-port default exposure

            return {
                "repo_url": repo_url,
                "subdomain": subdomain,
                "url": app_url,
                "environments": environments,
                "connection_info": connection_info,
                "template_ports": template_ports,
                "template_port_defaults": template_port_defaults,
                "status": "success"
            }
            
        except Exception as e:
            self._cleanup([deploy_workspace])
            raise Exception(self._sanitize_error(str(e)))
    
    async def deploy_async(self, app_id: str, app_data: AppCreate, payload: WebhookDeployRequest):
        """Deploy asincrono para background tasks"""
        db = get_db()
        try:
            result = await self.deploy(app_data)
            # Build update dict
            update_fields = {
                "status": "running",
                "repo_url": result.get("repo_url"),
                "subdomain": result.get("subdomain"),
                "url": result.get("url"),
                "connection_info": result.get("connection_info"),
                "updated_at": datetime.utcnow()
            }
            # Persist multi-port info from template so UI can render per-port links
            if result.get("template_ports"):
                update_fields["exposure.ports"] = result["template_ports"]
            if result.get("template_port_defaults"):
                update_fields["exposure.port_exposure"] = result["template_port_defaults"]
            await db.apps.update_one(
                {"_id": ObjectId(app_id)},
                {"$set": update_fields}
            )
        except Exception as e:
            await db.apps.update_one(
                {"_id": ObjectId(app_id)},
                {"$set": {
                    "status": "error",
                    "error": str(e),
                    "updated_at": datetime.utcnow()
                }}
            )
    
    async def _clone_repos(self, templates_repo: str, infra_path: str, templates_path: str):
        """Clonar templates monorepo e infra-gitops using current git provider"""
        # Use provider for authenticated clone URLs
        infra_auth_url = self.provider.get_auth_clone_url("infra-gitops")
        templates_auth_url = self.provider.get_auth_clone_url(templates_repo)
        
        # Clone infra
        if not os.path.exists(infra_path):
            try:
                subprocess.run(
                    ["git", "clone", infra_auth_url, infra_path],
                    check=True, capture_output=True
                )
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or b'').decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else str(e.stderr or '')
                raise Exception(self._sanitize_error(f"Failed to clone infra-gitops: {stderr}"))
        
        # Clone templates monorepo
        if not os.path.exists(templates_path):
            try:
                subprocess.run(
                    ["git", "clone", templates_auth_url, templates_path],
                    check=True, capture_output=True
                )
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or b'').decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else str(e.stderr or '')
                raise Exception(self._sanitize_error(f"Failed to clone templates repo: {stderr}"))
    
    async def _create_bitbucket_repo(self, app_name: str) -> str:
        """Crear repo en Bitbucket"""
        bb_workspace = self._credentials["bb_workspace"]
        bb_email = self._credentials.get("bitbucket_email", self.git_user)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.bitbucket.org/2.0/repositories/{bb_workspace}/{app_name}",
                auth=(bb_email, self.git_token),  # Bitbucket usa email:token
                json={"scm": "git", "is_private": True}
            )
            # 200 o 409 (ya existe) son OK
            if response.status_code not in [200, 201, 409]:
                raise Exception(f"Failed to create repo: {response.text}")
        
        return f"https://bitbucket.org/{bb_workspace}/{app_name}.git"
    
    
    async def _scaffold_app(self, new_app_path: str, app_name: str, template_details: dict, app_data: AppCreate, templates_path_clone: str = None):
        """Generar app usando comando CLI (scaffold)"""
        if os.path.exists(new_app_path):
            shutil.rmtree(new_app_path)
        os.makedirs(new_app_path, exist_ok=True)
            
        scaffold_config = template_details.get("scaffold", {})
        command = scaffold_config.get("command")
        
        # Use passed templates_path_clone, fallback to old workspace path for backward compat
        if not templates_path_clone:
            templates_path_clone = f"{self.workspace}/kaanbal-templates-clone"
        
        if not command:
            # Template-files based scaffold: copy pre-built template files
            if scaffold_config.get("template_files"):
                source_dir = str(scaffold_config.get("source", "") or "").strip()

                template_src = None
                # 1) Prefer explicit scaffold.source, but NEVER allow empty (repo root)
                if source_dir:
                    candidate = os.path.join(templates_path_clone, source_dir)
                    if os.path.exists(candidate):
                        template_src = candidate

                # 2) Fallback: category-based path (catalog v4 standard)
                if not template_src:
                    category = template_details.get("category", "")
                    tpl_id = template_details.get("id", "")
                    candidate = os.path.join(templates_path_clone, f"templates/{category}/{tpl_id}")
                    if os.path.exists(candidate):
                        template_src = candidate

                if not template_src:
                    tpl_id = template_details.get("id", "unknown")
                    tpl_cat = template_details.get("category", "")
                    raise ScaffoldUnavailableError(
                        template=tpl_id,
                        message=(
                            f"Scaffold source for '{tpl_id}' not found. "
                            f"Expected at scaffold.source='{source_dir}' or "
                            f"templates/{tpl_cat}/{tpl_id} in kaanbal-templates."
                        ),
                        resolution=(
                            f"The kaanbal-templates repository is missing scaffold files for '{tpl_id}'. "
                            "Run the installer to repopulate the templates repository."
                        ),
                    )
                await self._copy_template_code(template_src, new_app_path, app_data)
                return
            raise Exception("No scaffold command defined for this template")
            
        # Render command with Jinja2 (supports conditionals like {% if use_router %}--router{% endif %})
        from jinja2 import Template
        template_config = getattr(app_data, 'template_config', {}) or {}

        # Vue-specific scaffold modes:
        # - latest: use npm create vue@latest
        # - version: use npm create vue@<requested>
        # - custom-template: copy local/custom template folder instead of running CLI
        template_id = template_details.get("id", "")
        if template_id == "vue3-spa":
            scaffold_source = str(template_config.get("scaffold_source", "latest")).strip().lower()
            if scaffold_source == "custom-template":
                custom_template_path = str(template_config.get("custom_template_path", "")).strip()
                if not custom_template_path:
                    raise Exception("custom_template_path is required when scaffold_source is 'custom-template'")

                resolved_template_path = self._resolve_custom_template_path(custom_template_path, template_details)
                await self._copy_template_code(resolved_template_path, new_app_path, app_data)
                return

            # If npm is not available in this runtime (common in the kaanbal-api Python container),
            # fall back to copying the prebuilt template from the templates monorepo.
            # This prevents scaffold failures like exit status 127.
            if shutil.which("npm") is None:
                fallback_candidates = [
                    os.path.join(templates_path_clone, "vue3-spa"),
                    os.path.join(templates_path_clone, "templates/frontend/vue3-spa"),
                ]
                fallback_src = next((p for p in fallback_candidates if os.path.exists(p) and os.listdir(p)), None)
                if not fallback_src:
                    raise ScaffoldUnavailableError(
                        template="vue3-spa",
                        message=(
                            "Vue scaffolding requires npm. npm is not available on this cluster node "
                            "and no pre-built fallback template was found in kaanbal-templates."
                        ),
                        resolution=(
                            "The kaanbal-templates repository needs scaffold files at "
                            "templates/frontend/vue3-spa/. Run the installer to repopulate, "
                            "or use creation_mode='upload' to provide a pre-built Docker image."
                        ),
                    )
                await self._copy_template_code(fallback_src, new_app_path, app_data)
                return

            vue_cli_version = str(template_config.get("vue_cli_version", "latest")).strip()
            if scaffold_source == "version" and vue_cli_version:
                command = command.replace("vue@latest", f"vue@{vue_cli_version}")

        # React scaffold fallback for legacy catalogs that still ship a CLI command.
        # In clustered installs kaanbal-api usually has no npm binary, so for react-spa
        # we must prefer template files when available.
        if template_id == "react-spa" and scaffold_config.get("template_files"):
            if shutil.which("npm") is None:
                fallback_candidates = [
                    os.path.join(templates_path_clone, "react-spa"),
                    os.path.join(templates_path_clone, "templates/frontend/react-spa"),
                ]
                fallback_src = next((p for p in fallback_candidates if os.path.exists(p) and os.listdir(p)), None)
                if not fallback_src:
                    raise ScaffoldUnavailableError(
                        template="react-spa",
                        message=(
                            "React scaffolding requires npm. npm is not available on this cluster node "
                            "and no pre-built fallback template was found in kaanbal-templates."
                        ),
                        resolution=(
                            "The kaanbal-templates repository needs scaffold files at "
                            "templates/frontend/react-spa/. Run the installer to repopulate, "
                            "or use creation_mode='upload' to provide a pre-built Docker image."
                        ),
                    )
                await self._copy_template_code(fallback_src, new_app_path, app_data)
                return
        
        # Context for template
        ctx = {
            "APP_NAME": app_name,
            **template_config
        }
        
        try:
             # Basic variable replacement first (legacy support)
             tmplated = command.replace("{{APP_NAME}}", app_name)
             # Then Jinja2 rendering
             command_rendered = Template(tmplated).render(**ctx)
             # Basic cleanup of extra spaces
             command = " ".join(command_rendered.split())
        except Exception as e:
             logger.error(f"Failed to render scaffold command: {e}")
             # Fallback to simple replace
             command = command.replace("{{APP_NAME}}", app_name)
        
        logger_cmd = command # For logging purposes
        if self.git_token: # censor token if present
             logger_cmd = command.replace(self.git_token, "***")
        logger.info(f"Executing scaffold: {logger_cmd}")
        
        # NOTE: Some commands (npm create) are interactive. 
        # We assume the command is non-interactive or has flags to make it so.
        # e.g. "npm create vue@latest my-app -- --typescript"
        
        try:
            # We run the command in the PARENT directory of new_app_path because 
            # most scaffolds create the directory themselves.
            cwd = os.path.dirname(new_app_path)
            
            # Use shell=True to handle npm/npx/pip commands correctly on certain OS
            subprocess.run(command, cwd=cwd, shell=True, check=True)
            
            # Post commands
            post_commands = scaffold_config.get("post_commands", [])
            for cmd_tmpl in post_commands:
                # Render post commands too
                try:
                    cmd_tmpl = cmd_tmpl.replace("{{APP_NAME}}", app_name)
                    cmd = Template(cmd_tmpl).render(**ctx)
                except:
                    cmd = cmd_tmpl.replace("{{APP_NAME}}", app_name)
                    
                # If command involves changing dir to app, run it inside app dir
                if f"cd {app_name}" in cmd or f"cd {{APP_NAME}}" in cmd:
                    # Strip the cd part and run the rest inside new_app_path
                    real_cmd = cmd.replace(f"cd {app_name}", "").replace(f"cd {{APP_NAME}}", "").strip()
                    if real_cmd.startswith("&&"): real_cmd = real_cmd[2:].strip()
                    
                    if real_cmd:
                        subprocess.run(real_cmd, cwd=new_app_path, shell=True, check=True)
                else:
                    subprocess.run(cmd, cwd=cwd, shell=True, check=True)
                
        except subprocess.CalledProcessError as e:
            raise Exception(f"Scaffold command failed: {str(e)}")

    def _resolve_custom_template_path(self, custom_template_path: str, template_details: dict) -> str:
        """Resolve a custom template path for scaffold_source=custom-template."""
        normalized = custom_template_path.replace("\\", "/").strip()
        category = template_details.get("category", "")
        template_id = template_details.get("id", "")

        candidates = []
        if os.path.isabs(normalized):
            candidates.append(normalized)

        candidates.extend([
            os.path.join(self.workspace, normalized),
            os.path.join(self.workspace, "kaanbal-templates-clone", normalized),
            os.path.join(self.workspace, "kaanbal-templates-clone", "templates", category, template_id, normalized),
            os.path.join(self.workspace, "kaanbal-templates-clone", "templates", category, normalized),
        ])

        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate

        searched = "\n- ".join(candidates)
        raise Exception(
            f"Custom template path not found: {custom_template_path}. Searched:\n- {searched}"
        )

    async def _create_empty_app(self, new_app_path: str, app_name: str):
        """Crear directorio vacío para app mode=empty"""
        if os.path.exists(new_app_path):
            shutil.rmtree(new_app_path)
        os.makedirs(new_app_path, exist_ok=True)
        # Create a README
        with open(os.path.join(new_app_path, "README.md"), "w") as f:
            f.write(f"# {app_name}\n\nProject created via Kaanbal Engine.")

    async def _copy_template_code(self, template_path: str, new_app_path: str, app_data: AppCreate):
        """Copiar template y personalizar (Legacy _prepare_app_code)"""
        # Copiar
        if os.path.exists(new_app_path):
            shutil.rmtree(new_app_path)
        shutil.copytree(template_path, new_app_path)

        # Eliminar .git y k8s (k8s are handled separately via infra-gitops)
        git_dir = os.path.join(new_app_path, ".git")
        k8s_dir = os.path.join(new_app_path, "k8s")
        if os.path.exists(git_dir):
            shutil.rmtree(git_dir)
        if os.path.exists(k8s_dir):
            shutil.rmtree(k8s_dir)

        # Prepare template context for Jinja2 rendering
        from jinja2 import Template
        template_config = getattr(app_data, 'template_config', {}) or {}
        template_context = {
            'APP_NAME': app_data.name,
            **template_config
        }

        # Reemplazos
        replacements = [
            ("placeholder-app", app_data.name),
            ("example.com", self.domain),
            ("automation.com.mx", self.domain),
        ]

        for root, dirs, files in os.walk(new_app_path):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # Apply string replacements first
                    for old, new in replacements:
                        content = content.replace(old, new)

                    # Then try Jinja2 rendering for template files (enables conditional blocks)
                    try:
                        content = Template(content).render(**template_context)
                    except:
                        pass  # If not a template, just use the content as-is

                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                except:
                    pass  # Skip binary files

    async def _setup_pipeline_and_docker(self, app_path: str, template_details: dict, app_data: AppCreate, environments: list, templates_repo_path: str):
        """Ensure CI/CD config file and Dockerfile exist (provider-agnostic)"""
        template_config = getattr(app_data, 'template_config', {}) or {}
        pipeline_mode = str(
            template_config.get("pipeline_mode")
            or template_details.get("pipeline_strategy")
            or "dynamic"
        ).strip().lower()
        
        # 1. CI/CD config file (bitbucket-pipelines.yml or .github/workflows/deploy.yml)
        ci_filename = self.provider.get_ci_filename()
        ci_path = os.path.join(app_path, ci_filename)
        if pipeline_mode != "template":
            await self._generate_dynamic_pipeline(app_path, app_data, environments, template_details)
        elif not os.path.exists(ci_path):
            # Check if template has a specific pipeline file defined
            tpl_pipeline_rel = template_details.get("pipeline") # e.g. "templates/frontend/vue3/pipeline.yml"
            
            if tpl_pipeline_rel and os.path.exists(os.path.join(templates_repo_path, tpl_pipeline_rel)):
                # Copy from template source (only valid for matching provider)
                shutil.copy(os.path.join(templates_repo_path, tpl_pipeline_rel), ci_path)
            else:
                # Generate dynamic pipeline
                await self._generate_dynamic_pipeline(app_path, app_data, environments, template_details)
        
        # 2. Dockerfile
        dockerfile_path = os.path.join(app_path, "Dockerfile")
        if not os.path.exists(dockerfile_path):
            tpl_docker_rel = template_details.get("dockerfile")
            
            if tpl_docker_rel and os.path.exists(os.path.join(templates_repo_path, tpl_docker_rel)):
                shutil.copy(os.path.join(templates_repo_path, tpl_docker_rel), dockerfile_path)
            else:
                 # TODO: Generate generic Dockerfile?
                 pass

    async def _push_new_repo(self, new_app_path: str, repo_url: str, app_name: str):
        """Inicializar y push nuevo repo (provider-agnostic)"""
        import time
        # Get authenticated URL from provider
        auth_repo_url = self.provider.get_auth_clone_url(app_name)

        # Local-only commands (no retry needed)
        local_commands = [
            ["git", "init"],
            ["git", "config", "user.email", f"kaanbal@{self.domain}"],
            ["git", "config", "user.name", "Kaanbal Engine"],
            ["git", "add", "."],
            # [skip ci]: este push ocurre antes de cargar los secrets del repo.
            # En GitHub Actions el workflow corre en cuanto llega el push y fallaba
            # con "Username and password required"; _trigger_initial_ci lanza el
            # build de main a propósito cuando los secrets ya existen.
            ["git", "commit", "-m", f"feat: Initial commit ({app_name}) [skip ci]"],
            ["git", "branch", "-M", "main"],
            ["git", "remote", "add", "origin", auth_repo_url],
        ]
        for cmd in local_commands:
            result = subprocess.run(cmd, cwd=new_app_path, capture_output=True, text=True)
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise Exception(self._sanitize_error(f"Git push failed: {error_msg}"))

        # Wait for remote repository to be fully provisioned before pushing.
        # GitHub/Bitbucket sometimes return 201 on create_repo before the repo
        # is reachable via git protocol — retry the push with backoff.
        push_cmd = ["git", "push", "-u", "origin", "main", "--force"]
        max_attempts = 8
        last_error = "Unknown error"
        for attempt in range(1, max_attempts + 1):
            result = subprocess.run(push_cmd, cwd=new_app_path, capture_output=True, text=True)
            if result.returncode == 0:
                break
            last_error = result.stderr or result.stdout or "Unknown error"
            if attempt < max_attempts:
                time.sleep(min(3 * attempt, 15))
        else:
            raise Exception(self._sanitize_error(f"Git push failed after {max_attempts} attempts: {last_error}"))
    
    async def _add_to_infra(self, infra_path: str, k8s_source_path: str, app_data: AppCreate, environments: list, spec: TemplateSpec = None):
        """
        Agregar manifests k8s a infra-gitops.
        
        Estructura: apps/{app_name}/
                    ├── base/
                    └── overlays/
                        ├── dev/
                        ├── staging/
                        └── prod/
        
        Solo se agregan los overlays para los environments seleccionados.
        """
        app_name = app_data.name
        
        if not os.path.exists(k8s_source_path):
            return
        
        # Directorio destino único para la app
        dest_dir = os.path.join(infra_path, "apps", app_name)
        
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        os.makedirs(dest_dir, exist_ok=True)
        
        # Copiar base
        base_src = os.path.join(k8s_source_path, "base")
        base_dest = os.path.join(dest_dir, "base")
        if os.path.exists(base_src):
            shutil.copytree(base_src, base_dest)
        
        # Crear directorio overlays
        overlays_dest = os.path.join(dest_dir, "overlays")
        os.makedirs(overlays_dest, exist_ok=True)
        
        # Reemplazos base
        # NOTE: Only replace "placeholder-app" (the canonical placeholder in templates).
        # Avoid replacing template_id blindly — e.g. "mongodb" is a substring of
        # "mongo:7" image references in deployment.yaml and would corrupt them.
        dockerhub_user = self._credentials.get("dockerhub_username", "") if self._credentials else ""
        replacements = [
            ("placeholder-app", app_name),
            ("example.com", self.domain),
            ("automation.com.mx", self.domain),
        ]
        # Replace docker hub username placeholder if it differs from the template default
        if dockerhub_user:
            replacements.append(("andresbardaleswork", dockerhub_user))
            if dockerhub_user != "andresbardalescalva":
                replacements.append(("andresbardalescalva", dockerhub_user))
        
        # Add replacements from template_config (optional)
        template_config = getattr(app_data, 'template_config', {}) or {}
        for k, v in template_config.items():
            replacements.append((f"{{{{{k}}}}}", str(v)))
        
        # Copiar solo los overlays de los environments seleccionados
        for env in environments:
            overlay_src = os.path.join(k8s_source_path, "overlays", env)
            overlay_dest = os.path.join(overlays_dest, env)
            
            if os.path.exists(overlay_src):
                shutil.copytree(overlay_src, overlay_dest)
            else:
                # Si no existe el overlay, crear uno básico
                os.makedirs(overlay_dest, exist_ok=True)
                self._create_basic_overlay(overlay_dest, app_name, env, app_data)
        
        # For config-only apps, strip the 'images:' section from kustomization overlays
        # so the base image (e.g. n8nio/n8n) is used directly without Docker Hub override.
        # Templates may include 'images:' for scaffold mode (pipeline updates the tag),
        # but config-only apps have no pipeline, so the tag would remain 'pending-initial-build'.
        if app_data.creation_mode == CreationMode.CONFIG_ONLY:
            for env in environments:
                kust_path = os.path.join(overlays_dest, env, "kustomization.yaml")
                if os.path.exists(kust_path):
                    with open(kust_path, 'r') as f:
                        content = f.read()
                    # Remove images: block (images: + subsequent indented lines)
                    content = re.sub(
                        r'\n# [^\n]*pipeline[^\n]*\n# [^\n]*\nimages:\n(?:[ \t]+.*\n)*',
                        '\n',
                        content,
                        flags=re.IGNORECASE
                    )
                    # Also try without comment prefix
                    content = re.sub(
                        r'\nimages:\n(?:[ \t]+.*\n)*',
                        '\n',
                        content
                    )
                    with open(kust_path, 'w') as f:
                        f.write(content)

        # Generate Tailscale exposure per env if exposure requires it
        # For database templates (mongo, postgres, redis), use L4 TCP Service
        # For multi-port apps with tailscale_tcp_ports (e.g. EMQX), use L4 TCP Service per TCP port
        # For web/API templates, use Service-based exposure (HTTP via tailscale.com/expose annotation)
        is_tcp = spec.is_tcp if spec else self._is_tcp_service(app_data.template or "")
        tailscale_tcp_ports = spec.tailscale_tcp_ports if spec else []
        public_paths = spec.public_paths if spec else []
        for env in environments:
            overlay_dest = os.path.join(overlays_dest, env)
            env_exposure = self._get_env_exposure(app_data, env)

            # Per-port path: if the app declares a port_exposure matrix, emit
            # one resource per port and *replace* the single-host base Ingress
            # so it does not duplicate hosts.
            used_per_port = False
            if not is_tcp:
                used_per_port = await self._generate_per_port_exposure(overlay_dest, app_name, env, app_data, spec)
            if used_per_port:
                self._remove_nginx_ingress_for_tailscale_only(overlay_dest, app_name)
                continue

            if env_exposure in ("tailscale", "both"):
                if is_tcp:
                    await self._generate_tailscale_tcp_service(overlay_dest, app_name, env, app_data, spec)
                elif tailscale_tcp_ports:
                    # Multi-port app with specific TCP ports needing L4 Service
                    # (e.g. EMQX MQTT port — template already handles HTTP Tailscale access via base ingress)
                    await self._generate_tailscale_tcp_services(overlay_dest, app_name, env, app_data, spec, tailscale_tcp_ports)
                else:
                    await self._generate_tailscale_ingress(overlay_dest, app_name, env, app_data, spec)
            # For "both" with public_paths defined: replace full-path nginx Ingress
            # with a path-restricted one (e.g. /webhook/*, /form/* only public, UI via Tailscale)
            if env_exposure == "both" and public_paths and not is_tcp:
                self._generate_webhook_ingress(overlay_dest, app_name, env, public_paths, app_data, spec)
            # For tailscale-only or internal web/API apps, remove the base nginx Ingress
            # (template overlays include a host-replace patch by default)
            if env_exposure in ("tailscale", "internal") and not is_tcp:
                self._upsert_ingress_delete_patch(overlay_dest, "placeholder-app")
            # For public (non-prod) web/API apps, ensure the overlay has a proper
            # host-replace Ingress patch. Some templates ship with $patch:delete
            # in dev/staging overlays — convert it back to a host-replace patch.
            if env_exposure in ("public", "both") and not is_tcp:
                self._ensure_nginx_ingress_for_public(overlay_dest, app_name, env, app_data)
                self._upsert_ingress_host_patch(overlay_dest, app_name, env, app_data, "placeholder-app")

            self._sync_tailscale_svc_kustomize_refs(overlay_dest)

        # Aplicar reemplazos en todos los YAMLs
        for root, dirs, files in os.walk(dest_dir):
            for file in files:
                if file.endswith('.yaml') or file.endswith('.yml'):
                    filepath = os.path.join(root, file)
                    with open(filepath, 'r') as f:
                        content = f.read()

                    for old, new in replacements:
                        content = content.replace(old, new)

                    with open(filepath, 'w') as f:
                        f.write(content)

        # Post-process: for root-domain apps, fix prod overlay host from
        # "{app}.{domain}" to "{domain}" and TLS secret accordingly.
        # Must run AFTER global replacements so we match final domain values.
        if self._is_root_domain_request(app_data) and "prod" in environments:
            prod_kust = os.path.join(overlays_dest, "prod", "kustomization.yaml")
            if os.path.exists(prod_kust):
                with open(prod_kust, 'r') as f:
                    c = f.read()
                c = c.replace(f"{app_name}.{self.domain}", self.domain)
                c = c.replace(f"tls-{app_name}", "tls-root")
                with open(prod_kust, 'w') as f:
                    f.write(c)
            # Also fix the base ingress if it contains the app-prefixed host
            base_ing = os.path.join(dest_dir, "base", "ingress.yaml")
            if os.path.exists(base_ing):
                with open(base_ing, 'r') as f:
                    c = f.read()
                # Base ingress keeps the subdomain form; prod overlay overrides it.
                # No change needed here — base is used by dev/staging overlays which
                # should keep the app-prefixed host.

        # Post-process: patch env var domains to use Tailscale hostnames
        # for environments where the public domain shouldn't be used in env vars.
        # Must run AFTER global replacements so we match the actual domain names.
        base_dest = os.path.join(dest_dir, "base")
        private_env_vars = spec.private_env_vars if spec else []
        for env in environments:
            overlay_dest = os.path.join(overlays_dest, env)
            env_exposure = self._get_env_exposure(app_data, env)
            if env_exposure == "tailscale":
                self._patch_env_domains_for_exposure(
                    overlay_dest, base_dest, app_name, env, "tailscale"
                )
            elif env_exposure == "both" and private_env_vars:
                self._patch_env_domains_for_exposure(
                    overlay_dest, base_dest, app_name, env, "both",
                    private_env_vars=private_env_vars
                )

    def _generate_docker_hub_manifests(self, infra_path: str, app_name: str, template_details: dict, app_data: AppCreate, environments: list):
        """
        Generate K8s manifests dynamically from catalog metadata for Docker Hub services.
        Creates StatefulSet (if volumes) or Deployment, Service, and optionally Ingress.
        """
        import yaml as pyyaml

        docker_image = template_details.get("docker_image", "")
        catalog_ports = template_details.get("ports", [])
        volumes = template_details.get("volumes", [])
        secrets_def = template_details.get("secrets", [])
        env_vars_def = template_details.get("env_vars", [])
        user_env_vars = getattr(app_data, "env_vars", None) or {}
        template_config = getattr(app_data, "template_config", {}) or {}
        # Merge config_schema defaults for any missing template_config keys
        config_schema = template_details.get("config_schema", {})
        for schema_key, schema_def in config_schema.items():
            if schema_key not in template_config and "default" in schema_def:
                template_config[schema_key] = schema_def["default"]
        # Allow Edge profile to override PVC size via template_config.storage_size
        if template_config.get("storage_size") and volumes:
            volumes = [{**vol, "size": str(template_config["storage_size"])} for vol in volumes]
        is_stateful = bool(volumes)
        main_port = template_details.get("port", 80)
        raw_container = template_details.get("id", app_name)
        # Sanitize container name: K8s requires lowercase RFC 1123 labels
        import re as _re
        container_name = _re.sub(r'[^a-z0-9-]', '', raw_container.lower().replace("_", "-")).strip("-") or app_name

        # Resolve image tag from template_config (e.g. emqx_version, grafana_version, redis_version)
        for key, val in template_config.items():
            if "version" in key.lower() and val:
                # Replace the tag in docker_image
                parts = docker_image.rsplit(":", 1)
                docker_image = f"{parts[0]}:{val}"
                break

        # Resolve template variables in volumes/env_vars (e.g. {{storage_size}})
        def resolve_tpl(s: str) -> str:
            for k, v in template_config.items():
                s = s.replace(f"{{{{{k}}}}}", str(v))
            # Also resolve app-level placeholders. self.domain (no _credentials)
            # para que {{DOMAIN}} respete el dominio de la app, no el de la
            # instalación.
            s = s.replace("{{APP_NAME}}", app_name)
            s = s.replace("{{DOMAIN}}", self.domain or "")
            return s

        # Build destination directory
        dest_dir = os.path.join(infra_path, "apps", app_name)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        base_dir = os.path.join(dest_dir, "base")
        os.makedirs(base_dir, exist_ok=True)

        # --- Build env section ---
        env_list = []
        # Add catalog-defined env vars (with defaults, resolved)
        for ev in env_vars_def:
            name = ev["name"]
            # User-provided value takes priority
            value = user_env_vars.get(name) or resolve_tpl(ev.get("default", ""))
            if value:  # Skip empty values
                env_list.append({"name": name, "value": value})

        # Add user-provided env vars not in catalog definition
        catalog_var_names = {ev["name"] for ev in env_vars_def}
        for name, value in user_env_vars.items():
            if name not in catalog_var_names and value:
                env_list.append({"name": name, "value": value})

        # Add secrets as env vars from secretKeyRef
        for sec in secrets_def:
            env_list.append({
                "name": sec["name"],
                "valueFrom": {
                    "secretKeyRef": {
                        "name": f"{app_name}-secrets",
                        "key": sec["name"]
                    }
                }
            })

        # --- Build ports section ---
        container_ports = []
        if catalog_ports:
            for p in catalog_ports:
                container_ports.append({
                    "containerPort": p["port"],
                    "name": p["name"][:15],  # K8s name limit
                    "protocol": p.get("protocol", "TCP")
                })
        else:
            container_ports.append({
                "containerPort": main_port,
                "name": "http",
                "protocol": "TCP"
            })

        # --- Build volume mounts ---
        volume_mounts = []
        for vol in volumes:
            volume_mounts.append({
                "name": vol["name"],
                "mountPath": vol["mount_path"]
            })

        # --- Build container spec ---
        # Per-template resource defaults (n8n OOMs at 512Mi during migrations).
        tpl_id = (template_details.get("id") or "").lower()
        resources = template_details.get("resources") or {}
        default_limits = {"cpu": "500m", "memory": "512Mi"}
        default_requests = {"cpu": "100m", "memory": "256Mi"}
        if tpl_id == "n8n" or template_details.get("category") == "workflow":
            default_limits = {"cpu": "1000m", "memory": "2Gi"}
            default_requests = {"cpu": "100m", "memory": "512Mi"}
        container = {
            "name": container_name,
            "image": docker_image,
            "envFrom": [{
                "secretRef": {
                    "name": f"{app_name}-secrets",
                    "optional": True,
                }
            }],
            "ports": container_ports,
            "resources": {
                "requests": resources.get("requests") or default_requests,
                "limits": resources.get("limits") or default_limits,
            }
        }
        if env_list:
            container["env"] = env_list
        if volume_mounts:
            container["volumeMounts"] = volume_mounts

        # Add health check if defined
        health_ep = template_details.get("health_endpoint")
        if health_ep and not template_details.get("is_tcp"):
            container["livenessProbe"] = {
                "httpGet": {"path": health_ep, "port": main_port},
                "initialDelaySeconds": 30,
                "periodSeconds": 30,
                "timeoutSeconds": 10,
                "failureThreshold": 5
            }
            container["readinessProbe"] = {
                "httpGet": {"path": health_ep, "port": main_port},
                "initialDelaySeconds": 10,
                "periodSeconds": 10,
                "timeoutSeconds": 5,
                "failureThreshold": 3
            }

        # --- Generate StatefulSet or Deployment ---
        if is_stateful:
            vct = []
            for vol in volumes:
                size = resolve_tpl(vol.get("size", "5Gi"))
                vct.append({
                    "metadata": {"name": vol["name"]},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "resources": {"requests": {"storage": size}}
                    }
                })

            workload = {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "metadata": {
                    "name": app_name,
                    "namespace": "prod",
                    "labels": {"app": app_name}
                },
                "spec": {
                    "serviceName": app_name,
                    "replicas": 1,
                    "selector": {"matchLabels": {"app": app_name}},
                    "template": {
                        "metadata": {"labels": {"app": app_name}},
                        "spec": {"containers": [container]}
                    },
                    "volumeClaimTemplates": vct
                }
            }
            workload_file = "statefulset.yaml"
        else:
            workload = {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {
                    "name": app_name,
                    "namespace": "prod",
                    "labels": {"app": app_name}
                },
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app": app_name}},
                    "template": {
                        "metadata": {"labels": {"app": app_name}},
                        "spec": {"containers": [container]}
                    }
                }
            }
            workload_file = "deployment.yaml"

        # Write workload YAML
        with open(os.path.join(base_dir, workload_file), 'w') as f:
            pyyaml.dump(workload, f, default_flow_style=False, sort_keys=False)

        # --- Generate Service ---
        svc_ports = []
        if catalog_ports:
            for p in catalog_ports:
                svc_ports.append({
                    "port": p["port"],
                    "targetPort": p["port"],
                    "protocol": p.get("protocol", "TCP"),
                    "name": p["name"][:15]
                })
        else:
            svc_ports.append({
                "port": main_port,
                "targetPort": main_port,
                "protocol": "TCP",
                "name": "http"
            })

        svc = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": app_name,
                "namespace": "prod",
                "labels": {"app": app_name}
            },
            "spec": {
                "selector": {"app": app_name},
                "ports": svc_ports
            }
        }
        # Headless service for StatefulSets (stable DNS for peers / PVC)
        if is_stateful:
            svc["spec"]["clusterIP"] = "None"

        with open(os.path.join(base_dir, "service.yaml"), 'w') as f:
            pyyaml.dump(svc, f, default_flow_style=False, sort_keys=False)

        # HTTP Ingress needs a ClusterIP backend — Traefik/nginx break on headless.
        # For StatefulSet HTTP apps (n8n, etc.) expose a companion ClusterIP service.
        service_type = (template_details.get("service_type") or "").lower()
        category = (template_details.get("category") or "").lower()
        is_tcp = bool(
            template_details.get("is_tcp")
            or service_type == "tcp"
            or category in ("database", "cache", "queue")
        )
        wants_http = not is_tcp
        http_svc_name = app_name
        resources_list = [workload_file, "service.yaml"]

        if is_stateful and wants_http:
            http_svc_name = f"{app_name}-http"
            # Multi-port managed services (EMQX): companion ClusterIP must expose
            # every listener so Ingress/LAN backends are not limited to main_port.
            if catalog_ports and len(catalog_ports) > 1:
                http_ports = [{
                    "port": p["port"],
                    "targetPort": p["port"],
                    "protocol": p.get("protocol", "TCP"),
                    "name": p["name"][:15],
                } for p in catalog_ports]
            else:
                http_ports = [{
                    "port": main_port,
                    "targetPort": main_port,
                    "protocol": "TCP",
                    "name": "http",
                }]
            http_svc = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": http_svc_name,
                    "namespace": "prod",
                    "labels": {"app": app_name, "kaanbal.io/role": "http-ingress"}
                },
                "spec": {
                    "type": "ClusterIP",
                    "selector": {"app": app_name},
                    "ports": http_ports,
                },
            }
            with open(os.path.join(base_dir, "service-http.yaml"), "w") as f:
                pyyaml.dump(http_svc, f, default_flow_style=False, sort_keys=False)
            resources_list.append("service-http.yaml")

        # EMQX Edge: MQTT auth bootstrap Job (PostSync)
        from .managed.emqx_edge import is_emqx_template, render_bootstrap_job
        if is_emqx_template(template_details.get("id", ""), template_details.get("category", ""), template_details):
            topic_prefix = str(template_config.get("topic_prefix") or "acuaponia")
            # Persist topic prefix into secrets pattern via env if not already
            job_yaml = render_bootstrap_job(app_name, topic_prefix=topic_prefix, dashboard_port=main_port)
            with open(os.path.join(base_dir, "mqtt-bootstrap-job.yaml"), "w") as f:
                f.write(job_yaml)
            resources_list.append("mqtt-bootstrap-job.yaml")

        # PVC retain hint on StatefulSet volumeClaimTemplates
        if is_stateful and workload.get("spec", {}).get("volumeClaimTemplates"):
            for vct_item in workload["spec"]["volumeClaimTemplates"]:
                meta = vct_item.setdefault("metadata", {})
                anns = meta.setdefault("annotations", {})
                anns["software-factory.io/retain-on-delete"] = "true"
                anns["argocd.argoproj.io/sync-options"] = "Prune=false"
            with open(os.path.join(base_dir, workload_file), "w") as f:
                pyyaml.dump(workload, f, default_flow_style=False, sort_keys=False)

        # --- Generate Ingress for HTTP services ---
        # Previously required health_endpoint — that blocked n8n/emqx (no probe).
        # Any non-TCP catalog service gets a base Ingress; overlays delete it when
        # exposure is tailscale/internal.
        if wants_http:
            app_protocols = getattr(app_data, "protocols", None) if app_data else None
            if not app_protocols:
                app_protocols = []

            template_config = getattr(app_data, "template_config", {}) or {} if app_data else {}
            if template_config.get("enable_websocket", False) and "websocket" not in app_protocols:
                app_protocols = list(app_protocols or []) + ["websocket"]

            ingress_annotations = self._public_ingress_annotations(app_protocols)
            ingress_tls = self._public_ingress_tls(
                [f"{app_name}.{self.domain}"], f"tls-{app_name}")

            ingress = {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "Ingress",
                "metadata": {
                    "name": app_name,
                    "namespace": "prod",
                    "annotations": ingress_annotations
                },
                "spec": {
                    "ingressClassName": self.ingress_class,
                    **({"tls": ingress_tls} if ingress_tls else {}),
                    "rules": [{
                        "host": f"{app_name}.{self.domain}",
                        "http": {
                            "paths": [{
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": http_svc_name,
                                        "port": {"number": main_port}
                                    }
                                }
                            }]
                        }
                    }]
                }
            }
            with open(os.path.join(base_dir, "ingress.yaml"), 'w') as f:
                pyyaml.dump(ingress, f, default_flow_style=False, sort_keys=False)
            resources_list.append("ingress.yaml")

        # --- Generate kustomization.yaml ---
        kust = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": resources_list
        }
        with open(os.path.join(base_dir, "kustomization.yaml"), 'w') as f:
            pyyaml.dump(kust, f, default_flow_style=False, sort_keys=False)

        # --- Generate overlays ---
        wk = "StatefulSet" if is_stateful else "Deployment"
        for env in environments:
            overlay_dir = os.path.join(dest_dir, "overlays", env)
            os.makedirs(overlay_dir, exist_ok=True)
            self._create_basic_overlay(overlay_dir, app_name, env, app_data, workload_kind=wk)

    async def _process_overlays_for_docker_hub(self, dest_dir: str, app_name: str, app_data: AppCreate, environments: list, spec):
        """Process overlay generation for docker-hub services (exposure, tailscale, DNS replacement)."""
        overlays_dest = os.path.join(dest_dir, "overlays")
        is_tcp = spec.is_tcp if spec else False
        tailscale_tcp_ports = spec.tailscale_tcp_ports if spec else []

        # Apply domain/name replacements across all YAMLs
        dockerhub_user = self._credentials.get("dockerhub_username", "") if self._credentials else ""
        replacements = [
            ("placeholder-app", app_name),
            ("example.com", self.domain),
            ("automation.com.mx", self.domain),
        ]
        if dockerhub_user:
            replacements.append(("andresbardaleswork", dockerhub_user))

        for root, dirs, files in os.walk(dest_dir):
            for file in files:
                if file.endswith('.yaml') or file.endswith('.yml'):
                    filepath = os.path.join(root, file)
                    with open(filepath, 'r') as f:
                        content = f.read()
                    for old, new in replacements:
                        content = content.replace(old, new)
                    with open(filepath, 'w') as f:
                        f.write(content)

        # Generate Tailscale/Ingress exposure per env
        public_paths = spec.public_paths if spec else []
        private_env_vars = spec.private_env_vars if spec else []
        for env in environments:
            overlay_dest = os.path.join(overlays_dest, env)
            env_exposure = self._get_env_exposure(app_data, env)

            # Per-port exposure short-circuit (same logic as _add_to_infra)
            used_per_port = False
            if not is_tcp:
                used_per_port = await self._generate_per_port_exposure(overlay_dest, app_name, env, app_data, spec)
            if used_per_port:
                self._remove_nginx_ingress_for_tailscale_only(overlay_dest, app_name)
                continue

            if env_exposure in ("tailscale", "both"):
                if is_tcp:
                    await self._generate_tailscale_tcp_service(overlay_dest, app_name, env, app_data, spec)
                elif tailscale_tcp_ports:
                    await self._generate_tailscale_tcp_services(overlay_dest, app_name, env, app_data, spec, tailscale_tcp_ports)
                else:
                    await self._generate_tailscale_ingress(overlay_dest, app_name, env, app_data, spec)
            # Mirror scaffold path: both + public_paths → path-restricted public Ingress
            if env_exposure == "both" and public_paths and not is_tcp:
                self._generate_webhook_ingress(overlay_dest, app_name, env, public_paths, app_data, spec)
            if env_exposure in ("tailscale", "internal") and not is_tcp:
                # Prefer converting an existing host-replace patch; otherwise append delete.
                self._upsert_ingress_delete_patch(overlay_dest, app_name)
            if env_exposure in ("public", "both") and not is_tcp:
                self._ensure_nginx_ingress_for_public(overlay_dest, app_name, env, app_data)
                self._upsert_ingress_host_patch(overlay_dest, app_name, env, app_data, app_name)

            self._sync_tailscale_svc_kustomize_refs(overlay_dest)

        # Mirror scaffold: patch env domains for Tailscale / both private vars
        base_dest = os.path.join(dest_dir, "base")
        for env in environments:
            overlay_dest = os.path.join(overlays_dest, env)
            env_exposure = self._get_env_exposure(app_data, env)
            if env_exposure == "tailscale":
                self._patch_env_domains_for_exposure(
                    overlay_dest, base_dest, app_name, env, "tailscale"
                )
            elif env_exposure == "both" and private_env_vars:
                self._patch_env_domains_for_exposure(
                    overlay_dest, base_dest, app_name, env, "both",
                    private_env_vars=private_env_vars,
                )

    def _scan_template_tailscale_ingresses(self, infra_path: str, app_name: str, environments: list) -> dict:
        """
        Scan rendered manifests for Tailscale Ingress resources defined by the template
        (not generated by the deployer). Examples: EMQX dashboard ingress.

        Returns dict: {env: tailscale_hostname} for each env that has a template-owned TS ingress.
        The hostname follows the Tailscale Operator pattern: {namespace}-{ingressName}-ingress
        """
        import yaml as pyyaml
        result = {}
        app_dir = os.path.join(infra_path, "apps", app_name)
        if not os.path.exists(app_dir):
            return result

        # Scan base directory for Tailscale Ingress resources
        base_dir = os.path.join(app_dir, "base")
        ts_ingress_names = []
        if os.path.exists(base_dir):
            for fname in os.listdir(base_dir):
                if not (fname.endswith('.yaml') or fname.endswith('.yml')):
                    continue
                fpath = os.path.join(base_dir, fname)
                try:
                    with open(fpath, 'r') as f:
                        content = f.read()
                    for doc in pyyaml.safe_load_all(content):
                        if not doc or not isinstance(doc, dict):
                            continue
                        kind = doc.get('kind', '')
                        spec = doc.get('spec', {}) or {}
                        ingress_class = spec.get('ingressClassName', '')
                        if kind == 'Ingress' and ingress_class == 'tailscale':
                            ingress_name = doc.get('metadata', {}).get('name', '')
                            if ingress_name:
                                ts_ingress_names.append(ingress_name)
                except Exception:
                    continue

        # Also scan overlay directories for additional TS ingresses
        for env in environments:
            overlay_dir = os.path.join(app_dir, "overlays", env)
            if os.path.exists(overlay_dir):
                for fname in os.listdir(overlay_dir):
                    if not (fname.endswith('.yaml') or fname.endswith('.yml')):
                        continue
                    # Skip deployer-generated tailscale files
                    if fname in ('tailscale-ingress.yaml', 'tailscale-tcp-service.yaml', 'tailscale-svc.yaml'):
                        continue
                    fpath = os.path.join(overlay_dir, fname)
                    try:
                        with open(fpath, 'r') as f:
                            content = f.read()
                        for doc in pyyaml.safe_load_all(content):
                            if not doc or not isinstance(doc, dict):
                                continue
                            kind = doc.get('kind', '')
                            spec = doc.get('spec', {}) or {}
                            ingress_class = spec.get('ingressClassName', '')
                            if kind == 'Ingress' and ingress_class == 'tailscale':
                                ingress_name = doc.get('metadata', {}).get('name', '')
                                if ingress_name and ingress_name not in ts_ingress_names:
                                    ts_ingress_names.append(ingress_name)
                    except Exception:
                        continue

        # Map each env to the first template-owned TS ingress hostname
        # Operator pattern: {namespace}-{ingressName}-ingress
        if ts_ingress_names:
            for env in environments:
                # Use the first TS ingress found (typically the dashboard/UI)
                result[env] = f"{env}-{ts_ingress_names[0]}-ingress"

        return result

    async def _check_tailscale_operator_health(self) -> tuple[bool, str]:
        """Check if the Tailscale operator pod is Running/Ready before allowing tailscale-exposed deploys.

        Returns (healthy: bool, message: str).
        Runs 'kubectl get deploy operator -n tailscale' via subprocess.
        If kubectl is unavailable or the check times out, returns (True, warning)
        so the deploy is not blocked by infra access issues.
        """
        try:
            result = subprocess.run(
                ["kubectl", "get", "deployment", "operator", "-n", "tailscale",
                 "-o", "jsonpath={.status.availableReplicas}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                # Operator namespace/deployment not found — not installed or not yet ready
                return False, "Tailscale operator deployment not found in namespace 'tailscale'. Ensure the platform is fully installed before deploying Tailscale-exposed apps."
            available = result.stdout.strip()
            if not available or available == "0":
                return False, "Tailscale operator has 0 available replicas. Wait for it to become Ready before deploying Tailscale-exposed apps."
            return True, f"Tailscale operator healthy ({available} replica(s) available)"
        except FileNotFoundError:
            # kubectl not on PATH — running outside cluster, skip check
            return True, "kubectl not available — skipping Tailscale operator health check"
        except subprocess.TimeoutExpired:
            return True, "Tailscale operator health check timed out — proceeding anyway"
        except Exception as e:
            logger.warning("Tailscale operator health check failed: %s", e)
            return True, f"Tailscale operator health check skipped: {e}"

    def _get_env_exposure(self, app_data: AppCreate, env: str) -> str:
        """Get the effective exposure type for a specific environment.

        Priority order:
        1. port_exposure matrix (multi-port / multi-channel): derive from channels.
        2. per_env dict (single-exposure apps): direct env key lookup.
        3. exposure.type fallback.
        4. 'internal' hard default.
        """
        if app_data.exposure:
            # Multi-port path: port_exposure takes priority over per_env
            if app_data.exposure.port_exposure:
                from .exposure.channels import derive_env_mode
                env_ports = app_data.exposure.port_exposure.get(env, {})
                if env_ports:
                    return derive_env_mode(env_ports)
            # Single-port path
            if app_data.exposure.per_env:
                return app_data.exposure.per_env.get(env, app_data.exposure.type or "internal")
            return app_data.exposure.type or "internal"
        return "internal"

    def _is_tcp_service(self, template_id: str) -> bool:
        """Check if the template is a raw TCP service (database) that needs L4 exposure instead of L7 Ingress."""
        tid = template_id.lower()
        return any(db in tid for db in ("mongo", "postgres", "redis", "mysql", "mariadb"))

    def _get_tcp_port(self, template_id: str, app_data: AppCreate) -> int:
        """Get the default TCP port for a database template."""
        tid = template_id.lower()
        if "mongo" in tid:
            return 27017
        elif "postgres" in tid:
            return 5432
        elif "redis" in tid:
            return 6379
        elif "mysql" in tid or "mariadb" in tid:
            return 3306
        # Fallback to app specs port
        if app_data.specs and app_data.specs.port:
            return app_data.specs.port
        return 80

    def _get_default_tags(self, template_id: str, spec: TemplateSpec = None) -> str:
        """Get default Tailscale ACL tags based on template type.
        Prefers TemplateSpec (data-driven), falls back to legacy string matching."""
        if spec:
            return spec.tailscale_tags_str
        # Legacy fallback
        tid = template_id.lower()
        tags = ["tag:k8s"]
        if any(db in tid for db in ("mongo", "postgres", "redis", "mysql", "mariadb")):
            tags.append("tag:database")
        return ",".join(tags)

    async def _get_app_tags(self, app_name: str, template_id: str, spec: TemplateSpec = None) -> str:
        """Get Tailscale tags: saved tags from MongoDB (if any), else defaults."""
        try:
            db = get_db()
            app_doc = await db.apps.find_one({"name": app_name}, {"tailscale_tags": 1})
            if app_doc and app_doc.get("tailscale_tags"):
                return ",".join(app_doc["tailscale_tags"])
        except Exception:
            pass
        return self._get_default_tags(template_id, spec)

    async def _generate_tailscale_tcp_service(self, overlay_path: str, app_name: str, env: str, app_data: AppCreate, spec: TemplateSpec = None):
        """
        Generate a Tailscale L4 TCP Service (LoadBalancer) for database apps.
        Unlike Ingress (L7/HTTPS), this exposes raw TCP on the actual port,
        making databases reachable at {hostname}.tailnet:port from any Tailnet device.
        """
        template_id = app_data.template or ""
        port = spec.tcp_port if spec else self._get_tcp_port(template_id, app_data)
        ts_hostname = f"{env}-{app_name}"
        tags = await self._get_app_tags(app_name, template_id, spec)

        svc_yaml = f"""# Tailscale L4 TCP access - generated by Kaanbal Engine
# Exposes raw TCP (port {port}) on the Tailnet for direct database connectivity
apiVersion: v1
kind: Service
metadata:
  name: {app_name}-ts
  labels:
    app: {app_name}
    software-factory.io/exposure: private-tcp
  annotations:
    argocd.argoproj.io/sync-options: ServerSideApply=true
    tailscale.com/expose: "true"
    tailscale.com/hostname: "{ts_hostname}"
    tailscale.com/tags: "{tags}"
spec:
  type: LoadBalancer
  loadBalancerClass: tailscale
  selector:
    app: {app_name}
  ports:
  - port: {port}
    targetPort: {port}
    protocol: TCP
    name: tcp
"""
        svc_path = os.path.join(overlay_path, "tailscale-svc.yaml")
        with open(svc_path, 'w') as f:
            f.write(svc_yaml)

        # Add to kustomization.yaml resources
        kustomization_path = os.path.join(overlay_path, "kustomization.yaml")
        if os.path.exists(kustomization_path):
            with open(kustomization_path, 'r') as f:
                content = f.read()
            if "tailscale-svc.yaml" not in content:
                content = re.sub(
                    r'([ \t]*)- \.\./.\./base',
                    r'\1- ../../base\n\1- tailscale-svc.yaml',
                    content,
                    count=1
                )
                with open(kustomization_path, 'w') as f:
                    f.write(content)

    async def _generate_tailscale_tcp_services(self, overlay_path: str, app_name: str, env: str,
                                                app_data: AppCreate, spec: TemplateSpec,
                                                tcp_ports: list[dict]):
        """
        Generate Tailscale L4 TCP Service(s) for specific ports of a multi-port app.

        For apps like EMQX that have both TCP (MQTT 1883) and HTTP (Dashboard 18083) ports,
        the template base already handles HTTP Tailscale access (dashboard Ingress). This method
        creates L4 LoadBalancer Services only for the raw TCP ports that can't use L7 Ingress.

        Each TCP port gets its own Service with hostname pattern: {env}-{app_name}-{port_name}
        e.g. dev-emqxtest-mqtt → reachable at dev-emqxtest-mqtt.tailnet:1883
        """
        template_id = app_data.template or ""
        tags = await self._get_app_tags(app_name, template_id, spec)

        documents = []
        for port_def in tcp_ports:
            port_name = port_def.get("name", "tcp")
            port_num = port_def.get("port", 1883)
            ts_hostname = f"{env}-{app_name}-{port_name}"

            svc_yaml = f"""# Tailscale L4 TCP access for {port_name} - generated by Kaanbal Engine
# Exposes raw TCP (port {port_num}) on the Tailnet for direct {port_name} connectivity
apiVersion: v1
kind: Service
metadata:
  name: {app_name}-{port_name}-ts
  labels:
    app: {app_name}
    software-factory.io/exposure: private-tcp
  annotations:
    argocd.argoproj.io/sync-options: ServerSideApply=true
    tailscale.com/expose: "true"
    tailscale.com/hostname: "{ts_hostname}"
    tailscale.com/tags: "{tags}"
spec:
  type: LoadBalancer
  loadBalancerClass: tailscale
  selector:
    app: {app_name}
  ports:
  - port: {port_num}
    targetPort: {port_num}
    protocol: TCP
    name: {port_name}"""
            documents.append(svc_yaml)

        content = "\n---\n".join(documents) + "\n"
        # Use tailscale-ingress.yaml filename for consistency with kustomization references
        svc_path = os.path.join(overlay_path, "tailscale-ingress.yaml")
        with open(svc_path, 'w') as f:
            f.write(content)

        # Add to kustomization.yaml resources
        kustomization_path = os.path.join(overlay_path, "kustomization.yaml")
        if os.path.exists(kustomization_path):
            with open(kustomization_path, 'r') as f:
                kust_content = f.read()
            if "tailscale-ingress.yaml" not in kust_content:
                kust_content = re.sub(
                    r'([ \t]*)- \.\./.\./base',
                    r'\1- ../../base\n\1- tailscale-ingress.yaml',
                    kust_content,
                    count=1
                )
                with open(kustomization_path, 'w') as f:
                    f.write(kust_content)

    # -------------------------------------------------------------------------
    # Per-port exposure (multi-port apps): generate one Ingress/TS Service per
    # port based on the port_exposure matrix. Backward-compatible: only kicks
    # in when app_data.exposure.port_exposure has entries.
    # -------------------------------------------------------------------------
    async def _generate_per_port_exposure(self, overlay_path: str, app_name: str, env: str,
                                          app_data: AppCreate, spec: TemplateSpec = None) -> bool:
        """Emit per-port exposure resources for multi-channel matrices.

        Supports legacy single-mode strings and Edge channels lists:
          { "mqtt": ["internal","lan","tailscale"], "ws": [...,"public"] }

        Rules:
          - public is forbidden on mqtt/mqtt_tls (no HTTP Ingress → :1883)
          - public ws → host mqtt-{app}.{domain}, path /mqtt
          - lan → LoadBalancer Service (K3s ServiceLB) on requested ports
          - tailscale → per-port Tailscale expose Service
          - internal → ClusterIP base service only
        """
        from .exposure.channels import (
            normalize_channels,
            sanitize_public_channels,
            public_ws_hostname,
            apply_edge_profile,
        )
        from .managed.emqx_edge import is_emqx_template

        exposure = getattr(app_data, "exposure", None)
        port_exposure = getattr(exposure, "port_exposure", None) or {}
        env_ports = port_exposure.get(env) or {}
        ports_def = getattr(exposure, "ports", None) or (spec.ports if spec else None) or []
        template_config = getattr(app_data, "template_config", None) or {}
        template_id = (app_data.template or "") if app_data else ""

        # Auto-fill Edge profile when empty but template is EMQX edge
        if not env_ports and is_emqx_template(template_id, template_details={"id": template_id}):
            profile = (template_config.get("profile") or "edge").lower()
            if profile == "edge":
                env_ports = apply_edge_profile(
                    [{"name": p.name if hasattr(p, "name") else p["name"]} for p in ports_def] or None,
                    enable_lan=True,
                    enable_tailscale=True,
                    enable_public_ws=True,
                    enable_public_dashboard=False,
                )

        if not env_ports or not ports_def:
            return False

        port_map = {p.name if hasattr(p, "name") else p["name"]:
                    (p.port if hasattr(p, "port") else p["port"]) for p in ports_def}

        domain = self.domain
        tags = await self._get_app_tags(app_name, app_data.template or "", spec)
        protocols = getattr(app_data, "protocols", None) or []

        generated_public: list[tuple[str, int, str]] = []
        generated_ts: list[tuple[str, int, str]] = []
        lan_ports: list[tuple[str, int]] = []

        # Prefer ClusterIP companion for Ingress backends when StatefulSet headless
        backend_svc = f"{app_name}-http" if os.path.exists(
            os.path.join(os.path.dirname(overlay_path), "..", "base", "service-http.yaml")
        ) or os.path.exists(
            os.path.join(overlay_path, "..", "..", "base", "service-http.yaml")
        ) else app_name
        # Resolve relative to infra apps/{app}/base from overlay overlays/{env}
        base_http = os.path.normpath(os.path.join(overlay_path, "..", "..", "base", "service-http.yaml"))
        if os.path.exists(base_http):
            backend_svc = f"{app_name}-http"

        for port_name, raw_mode in env_ports.items():
            port_num = port_map.get(port_name)
            if not port_num:
                continue

            channels = sanitize_public_channels(port_name, normalize_channels(raw_mode))
            if not channels:
                continue

            if "public" in channels:
                pname = (port_name or "").lower()
                if pname in ("ws", "websocket"):
                    host = public_ws_hostname(app_name, domain, env)
                    path = "/mqtt"
                elif pname == "dashboard":
                    if env == "prod":
                        host = f"dashboard-{app_name}.{domain}"
                    else:
                        host = f"{env}-dashboard-{app_name}.{domain}"
                    path = "/"
                else:
                    # Should have been stripped for mqtt; skip defensively
                    logger.warning("Skipping public exposure for forbidden/unknown port %s", port_name)
                    host = None
                    path = "/"
                if host:
                    self._write_public_ingress_for_port(
                        overlay_path, app_name, port_name, port_num, host, protocols,
                        ingress_path=path, backend_service=backend_svc,
                    )
                    generated_public.append((port_name, port_num, host))

            if "tailscale" in channels:
                ts_host = f"{env}-{app_name}-{port_name}"[:63]
                self._write_tailscale_svc_for_port(overlay_path, app_name, port_name, port_num, ts_host, tags)
                generated_ts.append((port_name, port_num, ts_host))

            if "lan" in channels:
                lan_ports.append((port_name, port_num))

            # internal: base ClusterIP already exposes the port

        if lan_ports:
            self._write_lan_svc(overlay_path, app_name, lan_ports)

        if generated_public or generated_ts or lan_ports:
            logger.info(
                f"[{env}] Generated per-port exposure for {app_name}: "
                f"public={[h for _,_,h in generated_public]} "
                f"tailscale={[h for _,_,h in generated_ts]} "
                f"lan={[p for p,_ in lan_ports]}"
            )
            return True
        return False

    def _write_lan_svc(self, overlay_path: str, app_name: str, lan_ports: list[tuple[str, int]]):
        """Publish selected ports on the node LAN IP via K3s ServiceLB (LoadBalancer)."""
        if not lan_ports:
            return
        port_lines = []
        for port_name, port_num in lan_ports:
            port_lines.append(
                f"    - name: {port_name[:15]}\n"
                f"      port: {port_num}\n"
                f"      targetPort: {port_num}\n"
                f"      protocol: TCP\n"
            )
        ports_yaml = "".join(port_lines)
        svc_yaml = f"""# Auto-generated LAN LoadBalancer (K3s ServiceLB) - Kaanbal Engine
apiVersion: v1
kind: Service
metadata:
  name: {app_name}-lan
  labels:
    app: {app_name}
    software-factory.io/exposure: lan
  annotations:
    argocd.argoproj.io/sync-options: ServerSideApply=true
spec:
  type: LoadBalancer
  selector:
    app: {app_name}
  ports:
{ports_yaml}"""
        filename = "lan-svc.yaml"
        with open(os.path.join(overlay_path, filename), "w") as f:
            f.write(svc_yaml)
        self._add_kustomize_resource(overlay_path, filename)

    def _write_public_ingress_for_port(self, overlay_path: str, app_name: str, port_name: str,
                                       port_num: int, host: str, protocols: list[str],
                                       ingress_path: str = "/", backend_service: str = None):
        """Write a public Ingress for one exposed port. Idempotent."""
        ann = {"nginx.ingress.kubernetes.io/ssl-redirect": "false"}
        if self.ingress_cluster_issuer:
            ann["cert-manager.io/cluster-issuer"] = self.ingress_cluster_issuer
        # WebSocket / MQTT-over-WS needs upgrade headers
        pname = (port_name or "").lower()
        if pname in ("ws", "websocket") or "websocket" in (protocols or []):
            ann["nginx.ingress.kubernetes.io/proxy-http-version"] = "1.1"
            ann["nginx.ingress.kubernetes.io/upstream-hash-by"] = "$remote_addr"
            ann["traefik.ingress.kubernetes.io/router.middlewares"] = ""
        ann.update(self._get_protocol_annotations(protocols))
        if "grpc" not in pname:
            ann.pop("nginx.ingress.kubernetes.io/backend-protocol", None)
        # Drop empty middleware annotation
        if ann.get("traefik.ingress.kubernetes.io/router.middlewares") == "":
            ann.pop("traefik.ingress.kubernetes.io/router.middlewares", None)
        ann_lines = "".join(f'    {k}: "{v}"\n' for k, v in ann.items())

        tls_yaml = ""
        if self.ingress_cluster_issuer:
            tls_yaml = (f"  tls:\n    - hosts:\n        - {host}\n"
                        f"      secretName: tls-{app_name}-{port_name}\n")

        if not ingress_path:
            ingress_path = "/ws" if port_name == "websocket" else "/"
        svc_name = backend_service or app_name

        ingress_yaml = f"""# Auto-generated per-port public Ingress ({port_name}) - Kaanbal Engine
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {app_name}-{port_name}
  labels:
    app: {app_name}
    software-factory.io/exposure: public
    software-factory.io/port: "{port_name}"
  annotations:
{ann_lines}spec:
  ingressClassName: {self.ingress_class}
{tls_yaml}  rules:
    - host: {host}
      http:
        paths:
          - path: {ingress_path}
            pathType: Prefix
            backend:
              service:
                name: {svc_name}
                port:
                  number: {port_num}
"""
        filename = f"public-ingress-{port_name}.yaml"
        with open(os.path.join(overlay_path, filename), "w") as f:
            f.write(ingress_yaml)
        self._add_kustomize_resource(overlay_path, filename)

    def _write_tailscale_svc_for_port(self, overlay_path: str, app_name: str, port_name: str,
                                      port_num: int, ts_hostname: str, tags: str):
        """Write a Tailscale-expose Service for one port. Idempotent."""
        svc_yaml = f"""# Auto-generated per-port Tailscale Service ({port_name}) - Kaanbal Engine
# Reachable at {ts_hostname}.<tailnet-suffix>
apiVersion: v1
kind: Service
metadata:
  name: {app_name}-ts-{port_name}
  labels:
    app: {app_name}
    software-factory.io/exposure: tailscale
    software-factory.io/port: "{port_name}"
  annotations:
    argocd.argoproj.io/sync-options: ServerSideApply=true
    tailscale.com/expose: "true"
    tailscale.com/hostname: "{ts_hostname}"
    tailscale.com/tags: "{tags}"
spec:
  type: ClusterIP
  selector:
    app: {app_name}
  ports:
    - port: {port_num}
      targetPort: {port_num}
      protocol: TCP
      name: {port_name[:15]}
"""
        filename = f"tailscale-svc-{port_name}.yaml"
        with open(os.path.join(overlay_path, filename), "w") as f:
            f.write(svc_yaml)
        self._add_kustomize_resource(overlay_path, filename)

    def _add_kustomize_resource(self, overlay_path: str, filename: str):
        """Append a resource entry to overlay's kustomization.yaml if missing."""
        kust = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.exists(kust):
            with open(kust, "w") as f:
                f.write(
                    "apiVersion: kustomize.config.k8s.io/v1beta1\n"
                    "kind: Kustomization\n"
                    "resources:\n"
                    "  - ../../base\n"
                    f"  - {filename}\n"
                )
            return
        with open(kust, "r") as f:
            content = f.read()
        if filename in content:
            return
        if "resources:" in content:
            content = re.sub(
                r"(resources:[ \t]*\n)",
                rf"\1  - {filename}\n",
                content,
                count=1,
            )
        else:
            content += f"\nresources:\n  - ../../base\n  - {filename}\n"
        with open(kust, "w") as f:
            f.write(content)

    def _sync_tailscale_svc_kustomize_refs(self, overlay_path: str):
        """Align kustomization resources with tailscale Service YAMLs on disk.

        Vue/React dev overlays historically listed tailscale-svc.yaml even when
        exposure is public/internal, which breaks kustomize if the file was never
        generated.
        """
        kust_path = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.isdir(overlay_path) or not os.path.exists(kust_path):
            return

        with open(kust_path, "r") as f:
            content = f.read()
        original = content

        for fname in os.listdir(overlay_path):
            if not (fname.startswith("tailscale-svc") and fname.endswith(".yaml")):
                continue
            if fname not in content:
                content = re.sub(
                    r"([ \t]*)- \.\./\.\./base",
                    rf"\1- ../../base\n\1- {fname}",
                    content,
                    count=1,
                )

        for line in original.splitlines():
            match = re.match(r"^[ \t]*- (tailscale-svc[-\w]*\.yaml)\s*$", line)
            if not match:
                continue
            fname = match.group(1)
            if not os.path.exists(os.path.join(overlay_path, fname)):
                content = re.sub(
                    rf"^[ \t]*- {re.escape(fname)}\s*\n",
                    "",
                    content,
                    flags=re.MULTILINE,
                )

        if content != original:
            with open(kust_path, "w") as f:
                f.write(content)
            logger.info("Synced tailscale-svc refs in %s", kust_path)

    async def _generate_tailscale_ingress(self, overlay_path: str, app_name: str, env: str, app_data: AppCreate, spec: TemplateSpec = None):
        """
        Generate a Tailscale Service-based exposure for web apps.
        Uses a K8s Service with tailscale.com/expose annotation (L4 proxy),
        which works without HTTPS certificate support on the Tailscale account.
        The Tailscale Operator creates a proxy pod that forwards HTTP traffic.
        Accessible at http://{env}-{app_name}.{tailnet_dns_suffix}
        """
        port = app_data.specs.port if app_data.specs and app_data.specs.port else 80
        ts_hostname = f"{env}-{app_name}"
        tags = await self._get_app_tags(app_name, app_data.template or '', spec)

        svc_yaml = f"""# Tailscale private access (Service-based) - generated by Kaanbal Engine
# Accessible at http://{ts_hostname}.{{tailnet_suffix}}
apiVersion: v1
kind: Service
metadata:
  name: {app_name}-ts
  labels:
    app: {app_name}
    software-factory.io/exposure: private
  annotations:
    argocd.argoproj.io/sync-options: ServerSideApply=true
    tailscale.com/expose: "true"
    tailscale.com/hostname: "{ts_hostname}"
    tailscale.com/tags: "{tags}"
spec:
  type: ClusterIP
  selector:
    app: {app_name}
  ports:
  - port: 80
    targetPort: {port}
    protocol: TCP
    name: http
"""
        svc_path = os.path.join(overlay_path, "tailscale-svc.yaml")
        with open(svc_path, 'w') as f:
            f.write(svc_yaml)

        # Add to kustomization.yaml resources
        kustomization_path = os.path.join(overlay_path, "kustomization.yaml")
        if os.path.exists(kustomization_path):
            with open(kustomization_path, 'r') as f:
                content = f.read()
            if "tailscale-svc.yaml" not in content:
                content = re.sub(
                    r'([ \t]*)- \.\./.\./base',
                    r'\1- ../../base\n\1- tailscale-svc.yaml',
                    content,
                    count=1
                )
                with open(kustomization_path, 'w') as f:
                    f.write(content)

    # Regex for an Ingress target+patch block. Tolerates blank lines inside
    # the patch body (some templates / serializers insert empty lines).
    _INGRESS_PATCH_RE = re.compile(
        r'^([ ]*)(?:#[^\n]*\n\s*)?- target:\s*\n'
        r'(?:[ \t]*\n)*'
        r'\s+kind:\s*Ingress\s*\n'
        r'(?:[ \t]*\n)*'
        r'\s+name:\s*([\w-]+)\s*\n'
        r'(?:[ \t]*\n)*'
        r'\s+patch:\s*\|-\s*\n'
        r'((?:[ \t]*\n|[ \t]+.*\n)*)',
        re.MULTILINE,
    )

    def _remove_nginx_ingress_for_tailscale_only(self, overlay_path: str, app_name: str):
        """For tailscale-only web/API apps: replace nginx Ingress host-replace
        patch with $patch:delete so the base Ingress is completely removed.

        Template overlays ship with an Ingress host-replace patch by default.
        When exposure=tailscale we must convert that into a strategic-merge
        delete so nginx does not create a duplicate host rule.

        Runs BEFORE global placeholder replacements, so matches template
        placeholder names too (e.g. 'placeholder-app').
        """
        kust_path = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.exists(kust_path):
            return

        with open(kust_path, 'r') as f:
            content = f.read()

        match = self._INGRESS_PATCH_RE.search(content)
        if not match:
            logger.debug(f"No Ingress patch found in {kust_path} — skipping tailscale-only conversion")
            return

        indent = match.group(1)   # e.g. "  " (2 spaces)
        name = match.group(2)     # e.g. "placeholder-app"

        replacement = (
            f"{indent}# Tailscale-only — remove base nginx Ingress to avoid host conflicts\n"
            f"{indent}- target:\n"
            f"{indent}    kind: Ingress\n"
            f"{indent}    name: {name}\n"
            f"{indent}  patch: |-\n"
            f"{indent}    $patch: delete\n"
            f"{indent}    apiVersion: networking.k8s.io/v1\n"
            f"{indent}    kind: Ingress\n"
            f"{indent}    metadata:\n"
            f"{indent}      name: {name}\n"
        )

        content = content[:match.start()] + replacement + content[match.end():]

        with open(kust_path, 'w') as f:
            f.write(content)
        logger.info(f"Converted Ingress patch to $patch:delete in {kust_path} (tailscale-only)")

    def _append_ingress_kustomize_block(self, overlay_path: str, block: str):
        """Append an Ingress patch block to kustomization.yaml (creates patches: if missing)."""
        kust_path = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.exists(kust_path):
            return
        with open(kust_path, 'r') as f:
            content = f.read()
        if "patches:" in content:
            content = content.rstrip() + "\n" + block
        else:
            content = content.rstrip() + "\n\npatches:\n" + block
        with open(kust_path, 'w') as f:
            f.write(content)

    def _upsert_ingress_delete_patch(self, overlay_path: str, ingress_name: str = "placeholder-app"):
        """Ensure overlay deletes the base nginx Ingress (tailscale/internal only)."""
        kust_path = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.exists(kust_path):
            return
        with open(kust_path, 'r') as f:
            content = f.read()
        if self._INGRESS_PATCH_RE.search(content):
            self._remove_nginx_ingress_for_tailscale_only(overlay_path, ingress_name)
            return
        block = (
            f"  # Tailscale-only — remove base nginx Ingress to avoid host conflicts\n"
            f"  - target:\n"
            f"      kind: Ingress\n"
            f"      name: {ingress_name}\n"
            f"    patch: |-\n"
            f"      $patch: delete\n"
            f"      apiVersion: networking.k8s.io/v1\n"
            f"      kind: Ingress\n"
            f"      metadata:\n"
            f"        name: {ingress_name}\n"
        )
        self._append_ingress_kustomize_block(overlay_path, block)
        logger.info(f"Appended Ingress $patch:delete in {kust_path}")

    def _upsert_ingress_host_patch(self, overlay_path: str, app_name: str, env: str,
                                   app_data: Optional[AppCreate] = None,
                                   ingress_name: str = "placeholder-app"):
        """Ensure overlay patches Ingress host for public/both exposure."""
        kust_path = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.exists(kust_path):
            return
        with open(kust_path, 'r') as f:
            content = f.read()
        match = self._INGRESS_PATCH_RE.search(content)
        host = self._build_public_host_tokenized(app_name, env, app_data)
        tls_suffix = "root" if (app_data and self._is_root_domain_request(app_data) and env == "prod") else (
            app_name if env == "prod" else f"{env}-{app_name}"
        )
        if match:
            patch_body = match.group(3) or ""
            if "$patch: delete" in patch_body or "$patch:delete" in patch_body:
                # Convert delete → host-replace (public exposure on a tailscale-default overlay)
                self._ensure_nginx_ingress_for_public(overlay_path, app_name, env, app_data)
            # Already has an Ingress patch (host-replace or freshly converted)
            return
        block = (
            f"  - target:\n"
            f"      kind: Ingress\n"
            f"      name: {ingress_name}\n"
            f"    patch: |-\n"
            f"{self._ingress_host_json6902_ops(host, f'tls-{tls_suffix}', indent='      ')}"
        )
        self._append_ingress_kustomize_block(overlay_path, block)
        logger.info(f"Appended Ingress host patch ({host}) in {kust_path}")

    def _ensure_nginx_ingress_for_public(self, overlay_path: str, app_name: str, env: str, app_data: Optional[AppCreate] = None):
        """For public web/API apps: ensure the overlay has a proper host-replace
        Ingress patch. Some templates ship with $patch:delete in non-prod overlays
        (e.g. vue3-spa assumes dev/staging are tailscale-only). When the user
        selects public exposure, convert the $patch:delete back to a host-replace.

        Runs BEFORE global placeholder replacements, so matches template
        placeholder names (e.g. 'placeholder-app') as well as the real app name.
        """
        kust_path = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.exists(kust_path):
            return

        with open(kust_path, 'r') as f:
            content = f.read()

        match = self._INGRESS_PATCH_RE.search(content)
        if not match:
            return

        patch_body = match.group(3) or ""
        if "$patch: delete" not in patch_body and "$patch:delete" not in patch_body:
            # Already a host-replace patch — nothing to do
            return

        indent = match.group(1)
        name = match.group(2)

        host_tokenized = self._build_public_host_tokenized(app_name, env, app_data)
        use_root_domain = bool(app_data and self._is_root_domain_request(app_data) and env == "prod")
        tls_suffix = "root" if use_root_domain else (app_name if env == "prod" else f"{env}-{app_name}")

        # Replace entire $patch:delete block with a clean JSON6902 host-replace
        # (never leave leftover lines — that breaks kustomize PatchTransformer).
        replacement = (
            f"{indent}- target:\n"
            f"{indent}    kind: Ingress\n"
            f"{indent}    name: {name}\n"
            f"{indent}  patch: |-\n"
            f"{self._ingress_host_json6902_ops(host_tokenized, f'tls-{tls_suffix}', indent=indent + '    ')}"
        )

        content = content[:match.start()] + replacement + content[match.end():]

        with open(kust_path, 'w') as f:
            f.write(content)
        logger.info(f"Restored Ingress host-replace patch in {kust_path} (public exposure for {env})")

    def _generate_webhook_ingress(self, overlay_path: str, app_name: str, env: str,
                                   public_paths: list[str], app_data: AppCreate,
                                   spec: TemplateSpec = None):
        """Generate a path-restricted public nginx Ingress for 'both' exposure.

        When a template defines public_paths (e.g. ["/webhook/*", "/form/*"]),
        only those paths are exposed publicly via nginx. The full UI remains
        accessible only via the Tailscale Ingress.

        Steps:
        1. Delete the base full-path nginx Ingress via kustomize $patch:delete
        2. Create a new webhook-ingress.yaml with only the specified paths
        3. Register it as a kustomize resource
        """
        port = app_data.specs.port if app_data.specs and app_data.specs.port else 80

        host = self._build_public_host(app_name, env, app_data)

        # Convert glob paths to nginx Ingress paths
        # /webhook/* → /webhook, /webhook-test/* → /webhook-test, /form/* → /form
        ingress_paths = []
        for p in public_paths:
            # Strip trailing /* or * for Prefix matching
            clean = p.rstrip("*").rstrip("/")
            if not clean:
                clean = "/"
            ingress_paths.append(clean)
        # Deduplicate while preserving order
        seen = set()
        unique_paths = []
        for p in ingress_paths:
            if p not in seen:
                seen.add(p)
                unique_paths.append(p)

        # Build path rules YAML
        path_rules = ""
        for p in unique_paths:
            path_rules += f"""      - path: {p}
        pathType: Prefix
        backend:
          service:
            name: {app_name}
            port:
              number: {port}
"""

        # Protocol-specific annotations for webhook ingress
        proto_ann_yaml = ""
        app_protocols = getattr(app_data, "protocols", None) if app_data else None
        if app_protocols:
            for k, v in self._get_protocol_annotations(app_protocols).items():
                proto_ann_yaml += f'    {k}: "{v}"\n'

        issuer_ann = ""
        webhook_tls = ""
        if self.ingress_cluster_issuer:
            issuer_ann = f'    cert-manager.io/cluster-issuer: "{self.ingress_cluster_issuer}"\n'
            webhook_tls = (f"  tls:\n  - hosts:\n    - {host}\n"
                           f"    secretName: tls-{env}-{app_name}-webhook\n")

        ingress_yaml = f"""# Public webhook/API ingress - generated by Kaanbal Engine
# Only exposes specific paths publicly. Full UI access via Tailscale VPN.
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {app_name}-webhook
  labels:
    app: {app_name}
    software-factory.io/exposure: public-paths
  annotations:
{issuer_ann}    nginx.ingress.kubernetes.io/ssl-redirect: "false"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
{proto_ann_yaml}
spec:
  ingressClassName: {self.ingress_class}
{webhook_tls}  rules:
  - host: {host}
    http:
      paths:
{path_rules}"""

        # Write the webhook ingress file
        ingress_path = os.path.join(overlay_path, "webhook-ingress.yaml")
        with open(ingress_path, 'w') as f:
            f.write(ingress_yaml)

        # Remove the base full-path nginx Ingress (replace patch with $patch:delete)
        self._remove_nginx_ingress_for_tailscale_only(overlay_path, app_name)

        # Add webhook-ingress.yaml to kustomization.yaml resources
        kustomization_path = os.path.join(overlay_path, "kustomization.yaml")
        if os.path.exists(kustomization_path):
            with open(kustomization_path, 'r') as f:
                content = f.read()
            if "webhook-ingress.yaml" not in content:
                content = re.sub(
                    r'([ \t]*)- \.\./\.\./base',
                    r'\1- ../../base\n\1- webhook-ingress.yaml',
                    content,
                    count=1
                )
                with open(kustomization_path, 'w') as f:
                    f.write(content)

        logger.info(f"Generated webhook-ingress.yaml for {app_name}/{env} with paths: {unique_paths}")

    def _patch_env_domains_for_exposure(self, overlay_path: str, base_path: str,
                                         app_name: str, env: str,
                                         env_exposure: str,
                                         private_env_vars: list = None):
        """Post-process overlay env var patches to use Tailscale hostnames.

        After global placeholder replacements, overlay kustomization.yaml env var
        patches reference the public domain (e.g., staging-app.domain.com).  For
        tailscale-only envs those should point to the Tailscale FQDN.  For "both"
        envs with private_env_vars, only the specified env vars get patched.

        Args:
            overlay_path: Path to the overlay directory (e.g., .../overlays/staging)
            base_path: Path to the base k8s directory (e.g., .../base)
            app_name: Actual app name after placeholder replacement
            env: Environment name (dev/staging/prod)
            env_exposure: "tailscale" or "both"
            private_env_vars: For "both" mode — env var names to convert to Tailscale
        """
        import yaml as pyyaml

        ts_suffix = self._credentials.get("tailscale_dns_suffix", TAILSCALE_DNS_SUFFIX)
        ts_fqdn = f"{env}-{app_name}.{ts_suffix}"

        # Compute public domain for this environment
        if env == "prod":
            public_domain = f"{app_name}.{self.domain}"
        elif env == "staging":
            public_domain = f"staging-{app_name}.{self.domain}"
        else:
            public_domain = f"{env}-{app_name}.{self.domain}"

        kust_path = os.path.join(overlay_path, "kustomization.yaml")
        if not os.path.exists(kust_path):
            return

        with open(kust_path, 'r') as f:
            content = f.read()

        modified = False

        if env_exposure == "tailscale":
            # Tailscale-only: replace ALL occurrences of public domain with Tailscale FQDN.
            # At this point the Ingress patches are already $patch:delete, so only env var
            # values and misc references remain.
            if public_domain in content:
                content = content.replace(public_domain, ts_fqdn)
                modified = True

            # Also handle env vars that come from the base deployment (not overridden
            # in the overlay). Scan the base deployment for domain-referencing env vars
            # and add patches for any that the overlay doesn't already cover.
            deploy_path = os.path.join(base_path, "deployment.yaml")
            if os.path.exists(deploy_path):
                with open(deploy_path, 'r') as f:
                    deploy_data = pyyaml.safe_load(f)
                containers = (deploy_data or {}).get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
                if containers:
                    env_vars = containers[0].get("env", [])
                    missing_patches = []
                    for idx, var in enumerate(env_vars):
                        value = str(var.get("value", ""))
                        env_path = f"/spec/template/spec/containers/0/env/{idx}/value"
                        if self.domain in value and env_path not in content:
                            new_value = value.replace(public_domain, ts_fqdn)
                            # Also replace the base prod domain (no env prefix)
                            new_value = new_value.replace(f"{app_name}.{self.domain}", ts_fqdn)
                            missing_patches.append(f"    - op: replace\n      path: {env_path}\n      value: \"{new_value}\"")
                    if missing_patches:
                        # Append to the Deployment patch block
                        deploy_patch_re = re.compile(
                            r'(- target:\s*\n\s+kind:\s*Deployment\s*\n\s+name:\s*[\w-]+\s*\n\s+patch:\s*\|-\s*\n(?:[ \t]+.*\n)*)',
                            re.MULTILINE
                        )
                        match = deploy_patch_re.search(content)
                        if match:
                            insert_pos = match.end()
                            extra = "\n".join(missing_patches) + "\n"
                            content = content[:insert_pos] + extra + content[insert_pos:]
                            modified = True

        elif env_exposure == "both" and private_env_vars:
            # Only patch specific env vars to use Tailscale FQDN.
            # These are typically the editor/UI URL env vars.
            deploy_path = os.path.join(base_path, "deployment.yaml")
            if not os.path.exists(deploy_path):
                return
            with open(deploy_path, 'r') as f:
                deploy_data = pyyaml.safe_load(f)
            containers = (deploy_data or {}).get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            if not containers:
                return
            env_vars = containers[0].get("env", [])

            new_ops = []
            for idx, var in enumerate(env_vars):
                name = var.get("name", "")
                value = str(var.get("value", ""))
                if name not in private_env_vars:
                    continue
                if self.domain not in value:
                    continue
                env_path = f"/spec/template/spec/containers/0/env/{idx}/value"
                # Check if overlay already patches this env var
                if env_path in content:
                    # Replace the domain in the existing patch value
                    pattern = re.compile(
                        rf'(path:\s*{re.escape(env_path)}\s*\n\s+value:\s*"?)([^"\n]+)("?)',
                        re.MULTILINE
                    )
                    m = pattern.search(content)
                    if m:
                        old_val = m.group(2)
                        new_val = old_val.replace(public_domain, ts_fqdn)
                        if new_val == old_val:
                            # Try replacing base domain (prod has no prefix)
                            new_val = old_val.replace(f"{app_name}.{self.domain}", ts_fqdn)
                        content = content[:m.start(2)] + new_val + content[m.end(2):]
                        modified = True
                else:
                    # Need to add a new patch op
                    new_value = value.replace(f"{app_name}.{self.domain}", ts_fqdn)
                    new_ops.append(f"    - op: replace\n      path: {env_path}\n      value: \"{new_value}\"")

            if new_ops:
                deploy_patch_re = re.compile(
                    r'(- target:\s*\n\s+kind:\s*Deployment\s*\n\s+name:\s*[\w-]+\s*\n\s+patch:\s*\|-\s*\n(?:[ \t]+.*\n)*)',
                    re.MULTILINE
                )
                match = deploy_patch_re.search(content)
                if match:
                    insert_pos = match.end()
                    extra = "\n".join(new_ops) + "\n"
                    content = content[:insert_pos] + extra + content[insert_pos:]
                    modified = True

        if modified:
            with open(kust_path, 'w') as f:
                f.write(content)
            logger.info(f"Patched env var domains for {app_name}/{env} (exposure={env_exposure}, tailscale_fqdn={ts_fqdn})")

    def _generate_password(self, length: int = 24) -> str:
        """Generate a cryptographically secure random password"""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets_module.choice(alphabet) for _ in range(length))

    def _generate_app_secrets_from_spec(self, spec: TemplateSpec, app_name: str, environments: list) -> dict:
        """
        Generate random credentials per environment using TemplateSpec (data-driven).
        Reads secret definitions from catalog.json — no hardcoded template checks.
        Returns: {env: {key: value, ...}, ...}
        """
        env_secrets = {}
        for env in environments:
            env_secrets[env] = spec.generate_secrets(env, app_name)
        return env_secrets

    def _generate_app_secrets(self, app_name: str, template_id: str, environments: list) -> dict:
        """
        LEGACY: Generate random credentials per environment for an app.
        Kept for backward compatibility with delete_app and other callers.
        New deploys use _generate_app_secrets_from_spec().
        Returns: {env: {key: value, ...}, ...}
        """
        env_secrets = {}
        for env in environments:
            if "mongo" in template_id.lower():
                prefix = env[:3]
                env_secrets[env] = {
                    "MONGO_USER": f"{prefix}admin",
                    "MONGO_PASSWORD": self._generate_password(),
                }
            elif "postgres" in template_id.lower():
                prefix = env[:3]
                env_secrets[env] = {
                    "POSTGRES_USER": f"{prefix}admin",
                    "POSTGRES_PASSWORD": self._generate_password(),
                    "POSTGRES_DB": app_name.replace("-", "_"),
                }
            elif "redis" in template_id.lower():
                env_secrets[env] = {
                    "REDIS_PASSWORD": self._generate_password(),
                }
            elif "mysql" in template_id.lower() or "mariadb" in template_id.lower():
                prefix = env[:3]
                env_secrets[env] = {
                    "MYSQL_ROOT_PASSWORD": self._generate_password(),
                    "MYSQL_USER": f"{prefix}admin",
                    "MYSQL_PASSWORD": self._generate_password(),
                    "MYSQL_DATABASE": app_name.replace("-", "_"),
                }
            elif "n8n" in template_id.lower():
                env_secrets[env] = {
                    "N8N_ENCRYPTION_KEY": self._generate_password(),
                    "APP_SECRET": self._generate_password(),
                }
            elif "emqx" in template_id.lower():
                env_secrets[env] = {
                    "EMQX_DASHBOARD__DEFAULT_PASSWORD": self._generate_password(),
                }
            else:
                env_secrets[env] = {
                    "APP_SECRET": self._generate_password(),
                }
        return env_secrets

    # -------------------------------------------------------------------------
    # Database bindings: read DB secrets from Vault, build connection URIs and
    # inject them into the backend's overlay secretGenerator. This is what
    # powers the "Use existing databases" wizard step.
    # -------------------------------------------------------------------------

    _DB_PORT_DEFAULTS = {
        "mongodb": 27017,
        "mongo": 27017,
        "postgres": 5432,
        "postgresql": 5432,
        "mysql": 3306,
        "mariadb": 3306,
        "redis": 6379,
    }

    def _detect_db_template(self, binding_template: Optional[str], db_doc: Optional[dict]) -> str:
        """Return a normalized template id (mongodb|postgres|mysql|redis|generic)."""
        candidate = (binding_template or (db_doc or {}).get("template") or "").lower()
        if "mongo" in candidate:
            return "mongodb"
        if "postgres" in candidate:
            return "postgres"
        if "mysql" in candidate or "mariadb" in candidate:
            return "mysql"
        if "redis" in candidate:
            return "redis"
        return candidate or "generic"

    def _build_db_connection_string(self, template_id: str, host: str, port: int, secrets: dict, db_name: str) -> dict:
        """
        Build a connection URI + components for a given database template.

        Returns: { "uri": "...", "host": "...", "port": "...", "user": "...",
                   "password": "...", "database": "..." }
        Only keys with values are returned.
        """
        sec = {k.upper(): v for k, v in (secrets or {}).items() if v is not None}
        port_str = str(port)
        comp = {"HOST": host, "PORT": port_str, "DATABASE": db_name}

        if template_id == "mongodb":
            user = sec.get("MONGO_USER") or sec.get("MONGO_INITDB_ROOT_USERNAME") or "admin"
            password = sec.get("MONGO_PASSWORD") or sec.get("MONGO_INITDB_ROOT_PASSWORD") or ""
            auth = f"{user}:{password}@" if password else ""
            uri = f"mongodb://{auth}{host}:{port}/{db_name}?authSource=admin"
            comp.update({"USER": user, "PASSWORD": password, "URI": uri})
            return comp

        if template_id == "postgres":
            user = sec.get("POSTGRES_USER") or "postgres"
            password = sec.get("POSTGRES_PASSWORD") or ""
            db = sec.get("POSTGRES_DB") or db_name
            comp["DATABASE"] = db
            auth = f"{user}:{password}@" if password else f"{user}@"
            uri = f"postgresql://{auth}{host}:{port}/{db}"
            comp.update({"USER": user, "PASSWORD": password, "URI": uri})
            return comp

        if template_id == "mysql":
            user = sec.get("MYSQL_USER") or "root"
            password = sec.get("MYSQL_PASSWORD") or sec.get("MYSQL_ROOT_PASSWORD") or ""
            db = sec.get("MYSQL_DATABASE") or db_name
            comp["DATABASE"] = db
            auth = f"{user}:{password}@" if password else f"{user}@"
            uri = f"mysql://{auth}{host}:{port}/{db}"
            comp.update({"USER": user, "PASSWORD": password, "URI": uri})
            return comp

        if template_id == "redis":
            password = sec.get("REDIS_PASSWORD") or ""
            auth = f":{password}@" if password else ""
            uri = f"redis://{auth}{host}:{port}/0"
            comp.update({"PASSWORD": password, "URI": uri})
            return comp

        # Generic: best-effort. Look for any URI-like secret, else build host:port only.
        for k in ("URI", "CONNECTION_STRING", "URL"):
            if k in sec:
                comp["URI"] = sec[k]
                break
        for k in ("USER", "USERNAME", "PASSWORD", "PASS"):
            if k in sec:
                comp[k.replace("PASS", "PASSWORD").replace("USERNAME", "USER")] = sec[k]
        return comp

    async def _read_app_secrets(self, app_name: str, env: str) -> dict:
        """Credenciales de una app: Vault primero, el Secret del clúster como respaldo.

        Vault se sella en cada reinicio del nodo. Si un backend se vincula a su base
        mientras está sellado —o si la base se desplegó con Vault sellado y aún no se
        reconcilió—, leer solo Vault le daría credenciales vacías y no conectaría. El
        Secret de Kubernetes tiene los mismos datos: ambos salen de lo que Kaanbal
        generó al desplegar la base.
        """
        secrets = await self._read_vault_secrets(app_name, env)
        if secrets:
            return secrets
        try:
            import base64
            from app.services import vault_sync

            by_ns = await asyncio.to_thread(vault_sync._list_secrets_by_namespace, [env])
            secret = vault_sync.app_secret_from(by_ns.get(env, []), app_name)
            if secret is not None and secret.data:
                logger.info(f"Credenciales de {env}/{app_name} leídas del Secret del clúster (Vault sin la ruta)")
                return {k: base64.b64decode(v).decode() for k, v in secret.data.items()}
        except Exception as e:
            logger.info(f"Respaldo desde el clúster falló para {env}/{app_name}: {e}")
        return {}

    async def _read_vault_secrets(self, app_name: str, env: str) -> dict:
        """Read KV v2 secret data from Vault. Returns {} on any failure."""
        if not self._credentials:
            return {}
        vault_addr = self._credentials.get("vault_addr", "")
        vault_token = self._credentials.get("vault_token", "")
        if not vault_addr or not vault_token:
            return {}
        url = f"{vault_addr}/v1/secret/data/{env}/{app_name}"
        try:
            async with httpx.AsyncClient(verify=False, timeout=10) as client:
                resp = await client.get(url, headers={"X-Vault-Token": vault_token})
            if resp.status_code != 200:
                logger.info(f"Vault read returned HTTP {resp.status_code} for {env}/{app_name}")
                return {}
            payload = resp.json() or {}
            return ((payload.get("data") or {}).get("data") or {})
        except Exception as e:
            logger.info(f"Vault read error for {env}/{app_name}: {e}")
            return {}

    def _normalize_db_bindings(self, app_data: AppCreate) -> dict:
        """Convert app_data.database_bindings into a clean dict[env, list[dict]]."""
        raw = getattr(app_data, "database_bindings", None)
        if not raw:
            return {}
        clean: dict = {}
        for env, bindings in raw.items():
            if not bindings:
                continue
            items = []
            for b in bindings:
                d = b.model_dump() if hasattr(b, "model_dump") else dict(b)
                if not d.get("app_name") or not d.get("env"):
                    continue
                d.setdefault("alias", d.get("template") or "db")
                # Sanitize alias to upper-case identifier
                alias = re.sub(r"[^A-Za-z0-9]+", "_", str(d["alias"])).strip("_").upper() or "DB"
                d["alias"] = alias
                items.append(d)
            if items:
                clean[env] = items
        return clean

    async def _resolve_database_bindings(self, app_name: str, app_data: AppCreate, environments: list, emit=None) -> dict:
        """
        For each backend env, resolve every bound database into env vars.

        Returns: { env: { ENV_VAR_NAME: value, ... } }
        Vars produced per binding:
            {ALIAS}_URI, {ALIAS}_HOST, {ALIAS}_PORT,
            {ALIAS}_USER, {ALIAS}_PASSWORD, {ALIAS}_DATABASE (when applicable)
        """
        bindings_per_env = self._normalize_db_bindings(app_data)
        if not bindings_per_env:
            return {}

        # Load referenced apps once so we can detect their template if not given
        db = get_db()
        unique_apps = {b["app_name"] for env_list in bindings_per_env.values() for b in env_list}
        apps_index: dict[str, dict] = {}
        if unique_apps:
            cursor = db.apps.find({"name": {"$in": list(unique_apps)}}, {"name": 1, "template": 1, "category": 1})
            async for doc in cursor:
                apps_index[doc["name"]] = doc

        result: dict[str, dict] = {}
        for backend_env, bindings in bindings_per_env.items():
            env_vars: dict[str, str] = {}
            resolved: list[tuple[str, dict]] = []  # (motor, componentes) para los nombres convencionales
            for b in bindings:
                db_app = b["app_name"]
                # El ambiente de la base. No se llama db_env: taparía al módulo db_env, que
                # se usa abajo para los nombres estándar (y rompía todo vínculo con una base).
                bound_env = b["env"]
                db_doc = apps_index.get(db_app)
                template_id = self._detect_db_template(b.get("template"), db_doc)
                host = f"{db_app}.{bound_env}.svc.cluster.local"
                port = self._DB_PORT_DEFAULTS.get(template_id, 0)
                if port == 0:
                    logger.warning(f"Skipping binding for {db_app}/{bound_env}: unknown template '{template_id}'")
                    if emit:
                        await emit("db_bindings", f"Unknown DB template for {db_app}/{bound_env}, skipped", "warning")
                    continue

                secrets = await self._read_app_secrets(db_app, bound_env)
                if not secrets and emit:
                    await emit(
                        "db_bindings",
                        f"No se encontraron credenciales de {db_app}/{bound_env} ni en Vault ni en el clúster",
                        "warning",
                    )
                conn = self._build_db_connection_string(
                    template_id=template_id,
                    host=host,
                    port=port,
                    secrets=secrets,
                    db_name=app_name.replace("-", "_"),
                )
                alias = b["alias"]
                for key, val in conn.items():
                    if val is None or val == "":
                        continue
                    env_vars[f"{alias}_{key}"] = str(val)
                resolved.append((template_id, conn))

                # n8n (and similar) expect DB_TYPE + DB_POSTGRESDB_* — not only DB_HOST.
                consumer_tpl = (getattr(app_data, "template", None) or "").lower()
                if template_id == "postgres" and (
                    "n8n" in consumer_tpl or consumer_tpl.endswith("n8n")
                ):
                    env_vars["DB_TYPE"] = "postgresdb"
                    if conn.get("HOST"):
                        env_vars["DB_POSTGRESDB_HOST"] = str(conn["HOST"])
                    if conn.get("PORT"):
                        env_vars["DB_POSTGRESDB_PORT"] = str(conn["PORT"])
                    if conn.get("DATABASE"):
                        env_vars["DB_POSTGRESDB_DATABASE"] = str(conn["DATABASE"])
                    if conn.get("USER"):
                        env_vars["DB_POSTGRESDB_USER"] = str(conn["USER"])
                    if conn.get("PASSWORD"):
                        env_vars["DB_POSTGRESDB_PASSWORD"] = str(conn["PASSWORD"])
                    env_vars["DB_POSTGRESDB_SSL_ENABLED"] = "false"
                    env_vars.setdefault("N8N_LISTEN_ADDRESS", "0.0.0.0")
                    env_vars.setdefault("NODE_OPTIONS", "--max-old-space-size=1024")

                if emit:
                    await emit(
                        "db_bindings",
                        f"{backend_env}: linked {db_app}/{bound_env} as {alias} ({template_id})",
                        "success",
                    )
            # Nombres convencionales del motor (MONGO_URI, DATABASE_URL, PGHOST...):
            # la app no tiene por qué saber cómo se llama la base en esta
            # instalación. Nunca pisan una variable ya definida.
            for name, value in db_env.canonical_aliases(resolved).items():
                env_vars.setdefault(name, value)

            if env_vars:
                result[backend_env] = env_vars

        return result

    async def _write_secrets_to_vault(self, app_name: str, env_secrets: dict, emit=None):
        """
        Write generated secrets to Vault KV v2 engine.
        Path: secret/data/{env}/{app_name}
        """
        vault_addr = self._credentials.get("vault_addr", "")
        vault_token = self._credentials.get("vault_token", "")

        if not vault_addr or not vault_token:
            logger.warning("Vault not configured (vault_addr/vault_token missing) - skipping Vault write")
            return False

        wrote_any = False
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            for env, secrets_data in env_secrets.items():
                vault_path = f"{vault_addr}/v1/secret/data/{env}/{app_name}"
                try:
                    if emit:
                        await emit("vault", f"Writing secrets to Vault ({env})...")
                    resp = await client.post(
                        vault_path,
                        headers={"X-Vault-Token": vault_token},
                        json={"data": secrets_data}
                    )
                    if resp.status_code in (200, 204):
                        logger.info(f"Wrote secrets to Vault: secret/{env}/{app_name}")
                        if emit:
                            keys = ", ".join(secrets_data.keys())
                            await emit("vault", f"Vault ({env}): {keys} written", "success")
                        wrote_any = True
                    elif resp.status_code == 503 and "sealed" in resp.text.lower():
                        # Vault se sella en cada reinicio del nodo. La app sigue
                        # desplegándose (su Secret de Kubernetes sí se crea) y
                        # vault_sync copia los secretos a Vault cuando se desbloquee.
                        logger.warning(f"Vault sealed: secret/{env}/{app_name} pending until unseal")
                        if emit:
                            await emit(
                                "vault",
                                f"Vault ({env}) está sellado: la app se despliega igual y sus secretos "
                                "se guardarán en Vault automáticamente cuando se desbloquee.",
                                "warning",
                            )
                    else:
                        logger.warning(f"Vault write failed for {env}/{app_name}: HTTP {resp.status_code} - {resp.text}")
                        if emit:
                            await emit("vault", f"Vault ({env}): write failed (HTTP {resp.status_code})", "error")
                except Exception as e:
                    logger.warning(f"Vault write error for {env}/{app_name}: {e}")
                    if emit:
                        await emit("vault", f"Vault ({env}): connection error", "error")

        return wrote_any

    def _patch_overlay_secrets(self, infra_path: str, app_name: str, env: str, env_secrets: dict):
        """
        Patch kustomization.yaml in an overlay to use generated passwords
        instead of hardcoded template values.

        Uses 'behavior: replace' only when the base kustomization already
        defines a Secret resource with the same name (to avoid kustomize
        name-collision errors).  Otherwise creates the secret fresh.
        """
        overlay_kust = os.path.join(infra_path, "apps", app_name, "overlays", env, "kustomization.yaml")
        if not os.path.exists(overlay_kust):
            return

        with open(overlay_kust, 'r') as f:
            content = f.read()

        secrets_data = env_secrets.get(env, {})
        if not secrets_data:
            return

        # Determine if the base kustomization includes a secret.yaml resource.
        # If it does, kustomize already defines a Secret with the app name, and
        # the overlay secretGenerator must use 'behavior: replace' to avoid
        # "already registered id" errors.
        secret_name = f"{app_name}-secrets"
        base_has_secret = False
        base_kust_path = os.path.join(infra_path, "apps", app_name, "base", "kustomization.yaml")
        if os.path.exists(base_kust_path):
            with open(base_kust_path, 'r') as bf:
                base_content = bf.read()
            # Check if secret.yaml is listed in resources
            if 'secret.yaml' in base_content:
                base_has_secret = True

        behavior_line = "    behavior: replace\n" if base_has_secret else ""

        # Check if secretGenerator already exists
        if "secretGenerator:" in content:
            # Replace existing literals with new generated values
            lines = content.split('\n')
            new_lines = []
            in_literals = False
            literals_done = False
            for line in lines:
                if 'literals:' in line and not literals_done:
                    in_literals = True
                    new_lines.append(line)
                    # Insert new generated literals
                    for key, val in secrets_data.items():
                        new_lines.append(f'      - {key}={val}')
                    literals_done = True
                    continue
                if in_literals:
                    # Skip old literal lines (starting with spaces + -)
                    stripped = line.strip()
                    if stripped.startswith('- ') and '=' in stripped:
                        continue  # Skip old literal
                    else:
                        in_literals = False
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            content = '\n'.join(new_lines)
        else:
            # No secretGenerator exists - add one
            literals = '\n'.join([f'      - {k}={v}' for k, v in secrets_data.items()])
            content += f"""
# Generated secrets by Kaanbal Engine
secretGenerator:
  - name: {secret_name}
{behavior_line}    literals:
{literals}
"""

        with open(overlay_kust, 'w') as f:
            f.write(content)

    def _read_overlay_literals(self, infra_path: str, app_name: str, env: str) -> Optional[dict]:
        """Variables que el overlay de un ambiente inyecta hoy en la app.

        Lee el primer bloque `literals:` del secretGenerator, que es el que
        escribe _patch_overlay_secrets. None = la app no tiene ese overlay.
        """
        overlay_kust = os.path.join(infra_path, "apps", app_name, "overlays", env, "kustomization.yaml")
        if not os.path.exists(overlay_kust):
            return None

        with open(overlay_kust, "r") as f:
            return db_env.parse_kustomize_literals(f.read())

    async def repair_db_bindings(self, app_name: str, environments: list) -> dict:
        """Publicar los nombres convencionales del motor en una app ya desplegada.

        Las variables de un vínculo se escriben en el overlay al crear la app,
        así que una app creada antes de esto solo tiene las del prefijo
        (NORTH_STAR_BAY_BD_URI) y su código, que pide MONGO_URI, no arranca.
        Relee lo que ya está inyectado —ahí está el vínculo—, agrega lo que
        falta y lo deja en infra-gitops; ArgoCD hace el resto.

        No toca ninguna variable existente: solo agrega nombres que no estaban.
        """
        await self._load_credentials()
        infra_path = os.path.join(self.workspace, "infra-gitops")
        if os.path.exists(infra_path):
            shutil.rmtree(infra_path)
        subprocess.run(
            ["git", "clone", self.provider.get_auth_clone_url("infra-gitops"), infra_path],
            check=True, capture_output=True,
        )

        report: dict = {"app": app_name, "environments": {}, "added": 0, "committed": False}
        changed: list = []
        try:
            for env in environments:
                literals = self._read_overlay_literals(infra_path, app_name, env)
                if literals is None:
                    report["environments"][env] = {"status": "sin_overlay", "added": []}
                    continue
                missing = db_env.missing_aliases(literals)
                if not missing:
                    report["environments"][env] = {"status": "al_dia", "added": []}
                    continue
                self._patch_overlay_secrets(infra_path, app_name, env, {env: {**literals, **missing}})
                report["environments"][env] = {"status": "actualizado", "added": sorted(missing)}
                report["added"] += len(missing)
                changed.append(env)

            if changed:
                await self._push_infra(
                    infra_path, app_name, changed,
                    message=f"fix({app_name}): nombres de conexión del motor en {', '.join(changed)}",
                )
                report["committed"] = True
        finally:
            shutil.rmtree(infra_path, ignore_errors=True)

        return report

    async def set_app_variable(self, app_name: str, variable: str, value: str, environments: list, *, overwrite: bool = False) -> dict:
        """Agregar (o, con overwrite, cambiar) una variable en los overlays de una app.

        Mismo camino que los vínculos de base: el secretGenerator del overlay en
        infra-gitops. ArgoCD aplica el cambio y la app se reinicia con la variable.
        Si un ambiente rechaza el cambio, no se publica ninguno.
        """
        from app.services import app_variables

        await self._load_credentials()
        infra_path = os.path.join(self.workspace, "infra-gitops")
        if os.path.exists(infra_path):
            shutil.rmtree(infra_path)
        subprocess.run(
            ["git", "clone", self.provider.get_auth_clone_url("infra-gitops"), infra_path],
            check=True, capture_output=True,
        )

        report: dict = {"app": app_name, "variable": variable, "environments": {}, "committed": False}
        try:
            planned = {}
            for env in environments:
                literals = self._read_overlay_literals(infra_path, app_name, env)
                if literals is None:
                    report["environments"][env] = "sin_overlay"
                    continue
                state, new_literals = app_variables.plan(literals, variable, value, overwrite=overwrite)
                report["environments"][env] = state
                if state != app_variables.UNCHANGED:
                    planned[env] = new_literals

            for env, new_literals in planned.items():
                self._patch_overlay_secrets(infra_path, app_name, env, {env: new_literals})
            if planned:
                await self._push_infra(
                    infra_path, app_name, list(planned),
                    message=f"feat({app_name}): variable {variable} en {', '.join(planned)}",
                )
                report["committed"] = True
        finally:
            shutil.rmtree(infra_path, ignore_errors=True)

        return report

    def _create_basic_overlay(self, overlay_path: str, app_name: str, env: str, app_data: AppCreate = None, workload_kind: str = "Deployment"):
        """Crear un overlay básico si no existe en el template"""
        # Determinar prefijo de subdominio
        if env == "prod":
            subdomain = app_name
            replicas = 2
        elif env == "staging":
            subdomain = f"staging-{app_name}"
            replicas = 1
        else:  # dev
            subdomain = f"dev-{app_name}"
            replicas = 1

        # Override replicas if specified
        if app_data and app_data.specs:
             # Use user value for replicas (applied to all envs or custom logic could go here)
             replicas = app_data.specs.replicas

        is_config_only = app_data and app_data.creation_mode == CreationMode.CONFIG_ONLY

        # Build kustomization sections
        images_section = ""
        if not is_config_only:
            dockerhub_user = self._credentials.get("dockerhub_username", "") if self._credentials else ""
            images_section = f"""
images:
  - name: nginx:stable-alpine
    newName: {dockerhub_user}/{app_name}
    newTag: pending-initial-build
"""

        ingress_patch = ""
        # Scaffold AND config-only HTTP apps need ingress host/delete patches.
        # Config-only docker-hub manifests now ship a base Ingress for non-TCP.
        env_exposure = self._get_env_exposure(app_data, env) if app_data else "public"
        needs_ingress_patch = True
        if is_config_only and app_data and getattr(app_data, "category", None) in (
            "database", "cache", "queue"
        ):
            needs_ingress_patch = False
        if needs_ingress_patch:
            if env == "prod" or env_exposure in ("public", "both"):
                # Keep/patch the base nginx Ingress with the correct host
                if env_exposure not in ("tailscale", "internal"):
                    host_value = f"{subdomain}.{self.domain}"
                    ingress_patch = (
                        f"\n- target:\n"
                        f"    kind: Ingress\n"
                        f"    name: {app_name}\n"
                        f"  patch: |-\n"
                        f"{self._ingress_host_json6902_ops(host_value, f'tls-{subdomain}', indent='    ')}"
                    )
                else:
                    ingress_patch = f"""
# {env.capitalize()} uses Tailscale only — remove base nginx Ingress to avoid host conflicts
- target:
    kind: Ingress
    name: {app_name}
  patch: |-
    $patch: delete
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata:
      name: {app_name}"""
            else:
                # Tailscale-only / internal: remove the base nginx Ingress
                ingress_patch = f"""
# {env.capitalize()} uses Tailscale only — remove base nginx Ingress to avoid host conflicts
- target:
    kind: Ingress
    name: {app_name}
  patch: |-
    $patch: delete
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata:
      name: {app_name}"""

        kustomization = f"""apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
namespace: {env}

commonLabels:
  environment: {env}
{images_section}
patches:
- target:
    kind: {workload_kind}
    name: {app_name}
  patch: |-
    - op: replace
      path: /spec/replicas
      value: {replicas}
{ingress_patch}
"""
        with open(os.path.join(overlay_path, "kustomization.yaml"), 'w') as f:
            f.write(kustomization)
    
    def _validate_generated_overlays(self, infra_path: str, app_name: str, environments: list) -> None:
        """Run `kustomize build` on each generated overlay before commit.

        Graceful degradation: if the kustomize binary is not on PATH the check
        is skipped with a warning so local/dev environments without kustomize
        installed still work. The production image installs kustomize so the
        gate is effective there.
        """
        kustomize_bin = shutil.which("kustomize")
        if not kustomize_bin:
            logger.warning(
                "kustomize binary not found in PATH; skipping pre-push overlay validation. "
                "Install kustomize to enable this safety gate."
            )
            return

        app_dir = os.path.join(infra_path, "apps", app_name)
        if not os.path.isdir(app_dir):
            return

        validated = []
        for env in environments:
            overlay_path = os.path.join(app_dir, "overlays", env)
            if not os.path.isdir(overlay_path):
                continue
            result = subprocess.run(
                [kustomize_bin, "build", overlay_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "unknown error").strip()
                # Prefer the real Error: line over deprecation warnings
                error_lines = [
                    ln for ln in err.splitlines()
                    if ln.strip().startswith("Error:")
                ]
                if error_lines:
                    err = " | ".join(error_lines)
                raise Exception(
                    f"Generated manifests invalid for {app_name}/{env}: "
                    f"{self._sanitize_error(err)}"
                )
            validated.append(env)

        if validated:
            logger.info(
                f"kustomize build OK for {app_name} overlays: {', '.join(validated)}"
            )

    async def _push_infra(self, infra_path: str, app_name: str, environments: list, message: str = None):
        """Commit y push cambios a infra-gitops"""
        envs_str = ", ".join(environments)
        commit_message = message or f"feat: Add {app_name} to apps ({envs_str})"

        # Pre-push validation: kustomize build of every generated overlay.
        # Fails loud BEFORE the commit so we never push a YAML that ArgoCD
        # would reject (historical bugs: kustomization indentation, ingress
        # malformed, blocked annotations, missing envFrom secretRef).
        self._validate_generated_overlays(infra_path, app_name, environments)

        # Config commands — safe to ignore errors
        for cmd in [
            ["git", "config", "user.email", f"kaanbal@{self.domain}"],
            ["git", "config", "user.name", "Kaanbal Engine"],
        ]:
            subprocess.run(cmd, cwd=infra_path, capture_output=True)
        
        # Stage all changes
        subprocess.run(["git", "add", "."], cwd=infra_path, check=True, capture_output=True)
        
        # Commit — may fail if no changes (that's OK)
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=infra_path, capture_output=True, text=True
        )
        if commit_result.returncode != 0:
            # "nothing to commit" is fine, anything else is a real error
            if "nothing to commit" in (commit_result.stdout + commit_result.stderr):
                logger.info(f"No infra changes to commit for {app_name}")
                return
            raise Exception(f"Git commit failed for infra-gitops: {self._sanitize_error(commit_result.stderr or commit_result.stdout)}")
        
        # Pull with rebase to avoid conflicts with CD pipeline pushes
        pull_result = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=infra_path, capture_output=True, text=True
        )
        if pull_result.returncode != 0:
            logger.warning(f"Git pull --rebase failed for infra-gitops: {pull_result.stderr}")
            # Try without rebase
            subprocess.run(
                ["git", "rebase", "--abort"],
                cwd=infra_path, capture_output=True
            )
        
        # Push — THIS MUST SUCCEED
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=infra_path, capture_output=True, text=True
        )
        if push_result.returncode != 0:
            error_msg = push_result.stderr or push_result.stdout or "Unknown push error"
            raise Exception(f"Failed to push infra-gitops: {self._sanitize_error(error_msg)}")

    async def _cache_zone_id(self, zone_id: str) -> None:
        """Guarda el zone_id resuelto donde pertenece según el dominio en curso."""
        db = get_db()
        bound_id = (self._domain_ctx or {}).get("domain_id")
        if bound_id:
            from bson import ObjectId
            from bson.errors import InvalidId

            try:
                await db.domains.update_one(
                    {"_id": ObjectId(bound_id)},
                    {"$set": {"cloudflare_zone_id": zone_id}},
                )
            except InvalidId:
                pass
            self._domain_ctx["zone_id"] = zone_id
            return

        await db.system_config.update_one(
            {"_id": "main"}, {"$set": {"cloudflare_zone_id": zone_id}},
        )
        if self._credentials is not None:
            self._credentials["cloudflare_zone_id"] = zone_id

    async def _setup_cloudflare_dns(self, app_name: str, fqdns: Optional[list[str]] = None) -> bool:
        """Create a Cloudflare DNS CNAME record for a public app.
        
        Uses an explicitly configured tunnel id when tunnel-based routing is enabled.
        If a wildcard DNS record already exists for the domain, this is a no-op.
        Returns True if record was created, False if Cloudflare is not configured.
        """
        cf_token = self._credentials.get("cloudflare_token", "")
        cf_account = self._credentials.get("cloudflare_account_id", "")
        cf_tunnel_id = self.cloudflare_tunnel_id
        cf_zone_id = self.cloudflare_zone_id

        if not cf_token or not cf_account:
            logger.warning("Cloudflare not configured - skipping DNS record creation")
            return False

        cf_api = "https://api.cloudflare.com/client/v4"
        headers = {
            "Authorization": f"Bearer {cf_token}",
            "Content-Type": "application/json",
        }
        records = fqdns if fqdns else [f"{app_name}.{self.domain}"]

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Resolve zone_id if not cached
                if not cf_zone_id:
                    zone_resp = await client.get(
                        f"{cf_api}/zones?name={self.domain}&status=active",
                        headers=headers,
                    )
                    zones = zone_resp.json().get("result", [])
                    if zones:
                        cf_zone_id = zones[0]["id"]
                        # Cachear el zone donde corresponda: en el documento del
                        # dominio si la operación está atada a uno, y solo en
                        # system_config cuando se trata del dominio de la instalación.
                        await self._cache_zone_id(cf_zone_id)
                    else:
                        logger.warning(f"No Cloudflare zone found for {self.domain}")
                        return False

                # Un wildcard (*.dominio) no cubre la raíz. Sin esto una app raíz
                # (homepage) quedaba sana en el clúster pero el dominio seguía
                # mostrando la página del registrador.
                apex = (self.domain or "").lower()
                if apex and any(str(r).lower() == apex for r in records):
                    from app.services import domain_service
                    tunnel = cf_tunnel_id or await domain_service.installation_tunnel_id(
                        client, await domain_service.get_system_config(),
                    )
                    taken = await domain_service.ensure_apex_routed(apex, zone_id=cf_zone_id, tunnel_id=tunnel)
                    if taken.get("replaced"):
                        logger.warning("Raíz %s tomada por la app raíz; se reemplazó: %s", apex, taken["replaced"])
                    records = [r for r in records if str(r).lower() != apex]
                    if not records:
                        return True

                # If wildcard DNS already exists, do not create per-app records.
                wildcard_resp = await client.get(
                    f"{cf_api}/zones/{cf_zone_id}/dns_records?name=*.{self.domain}",
                    headers=headers,
                )
                wildcard_records = wildcard_resp.json().get("result", [])
                if wildcard_records:
                    logger.info(
                        "Wildcard DNS record detected for domain - skipping per-app Cloudflare DNS records"
                    )
                    return True

                # Do NOT auto-discover tunnel ids. This can bind apps to stale/dead tunnels.
                if not cf_tunnel_id:
                    logger.warning(
                        "cloudflare_tunnel_id is not configured - skipping tunnel CNAME creation"
                    )
                    return False

                cname_target = f"{cf_tunnel_id}.cfargotunnel.com"

                for fqdn in records:
                    # Check if DNS record already exists
                    existing_resp = await client.get(
                        f"{cf_api}/zones/{cf_zone_id}/dns_records?type=CNAME&name={fqdn}",
                        headers=headers,
                    )
                    existing = existing_resp.json().get("result", [])

                    if existing:
                        # Update existing record
                        await client.put(
                            f"{cf_api}/zones/{cf_zone_id}/dns_records/{existing[0]['id']}",
                            headers=headers,
                            json={"type": "CNAME", "name": fqdn, "content": cname_target, "proxied": True},
                        )
                        logger.info(f"Updated Cloudflare DNS: {fqdn} -> {cname_target}")
                    else:
                        # Create new record
                        create_resp = await client.post(
                            f"{cf_api}/zones/{cf_zone_id}/dns_records",
                            headers=headers,
                            json={"type": "CNAME", "name": fqdn, "content": cname_target, "proxied": True},
                        )
                        if create_resp.status_code != 200:
                            logger.error(f"Failed to create DNS record {fqdn}: {create_resp.text}")
                            return False
                        logger.info(f"Created Cloudflare DNS: {fqdn} -> {cname_target}")

                return True
        except Exception as e:
            logger.error(f"Cloudflare DNS setup failed: {e}")
            return False

    async def _delete_cloudflare_dns(self, fqdns: Optional[list[str]] = None) -> bool:
        """Delete Cloudflare CNAME records for public hosts (idempotent).

        Used when switching an env away from public/both. Does not touch
        wildcard records. Returns True if deleted or already absent.
        """
        cf_token = self._credentials.get("cloudflare_token", "")
        cf_account = self._credentials.get("cloudflare_account_id", "")
        cf_zone_id = self.cloudflare_zone_id
        if not cf_token or not cf_account:
            logger.warning("Cloudflare not configured - skipping DNS delete")
            return False
        records = [r for r in (fqdns or []) if r]
        if not records:
            return True

        cf_api = "https://api.cloudflare.com/client/v4"
        headers = {
            "Authorization": f"Bearer {cf_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if not cf_zone_id:
                    zone_resp = await client.get(
                        f"{cf_api}/zones?name={self.domain}&status=active",
                        headers=headers,
                    )
                    zones = zone_resp.json().get("result", [])
                    if not zones:
                        return False
                    cf_zone_id = zones[0]["id"]

                for fqdn in records:
                    existing_resp = await client.get(
                        f"{cf_api}/zones/{cf_zone_id}/dns_records?type=CNAME&name={fqdn}",
                        headers=headers,
                    )
                    existing = existing_resp.json().get("result", [])
                    for rec in existing:
                        del_resp = await client.delete(
                            f"{cf_api}/zones/{cf_zone_id}/dns_records/{rec['id']}",
                            headers=headers,
                        )
                        if del_resp.status_code not in (200, 404):
                            logger.warning(
                                "CF DNS delete %s failed: %s", fqdn, del_resp.text[:200]
                            )
                        else:
                            logger.info("Deleted Cloudflare DNS: %s", fqdn)
                return True
        except Exception as e:
            logger.error(f"Cloudflare DNS delete failed: {e}")
            return False

    async def _configure_ci_variables(self, app_name: str):
        """Configure CI/CD variables using the current git provider"""
        # Build INFRA_REPO_AUTH based on provider type
        if self.provider.name == "github":
            # GitHub: x-access-token:{token}
            infra_auth = f"x-access-token:{self._credentials.get('github_token', self._credentials.get('git_token', ''))}"
        else:
            # Bitbucket: user:token
            infra_auth = f"{self.git_user}:{self.git_token}"

        variables = [
            {"key": "DOCKERHUB_USERNAME", "value": self._credentials.get("dockerhub_username", ""), "secured": False},
            {"key": "DOCKERHUB_PASSWORD", "value": self._credentials.get("dockerhub_token", ""), "secured": True},
            {"key": "INFRA_REPO_AUTH", "value": infra_auth, "secured": True},
        ]
        
        await self.provider.set_ci_variables(app_name, variables)

    # Legacy alias for backward compatibility
    async def _configure_pipeline_vars(self, app_name: str):
        """Deprecated: use _configure_ci_variables"""
        await self._configure_ci_variables(app_name)

    async def _trigger_initial_ci(self, app_name: str, environments: list):
        """Trigger the first CI run for the main branch only.
        
        develop/staging branches are already triggered automatically by
        the branch push in _create_environment_branches (step 10).
        main needs an explicit trigger because it was pushed before
        CI was enabled.
        """
        # Only trigger main — other branches auto-trigger on push
        if "prod" not in environments:
            logger.info("No prod environment — skipping main CI trigger")
            return

        try:
            result = await self.provider.trigger_ci(app_name, "main")
            if result:
                logger.info(f"Triggered CI for {app_name}/main (prod) via {self.provider.display_name}")
            else:
                logger.warning(f"CI trigger for {app_name}/main returned None")
        except Exception as e:
            logger.warning(f"Could not trigger CI for {app_name}/main: {e}")

    # Legacy alias for backward compatibility
    async def _trigger_initial_pipelines(self, app_name: str, environments: list):
        """Deprecated: use _trigger_initial_ci"""
        await self._trigger_initial_ci(app_name, environments)
    
    def _cleanup(self, paths: list):
        """Limpiar directorios temporales"""
        for path in paths:
            if path and os.path.exists(path):
                try:
                    shutil.rmtree(path)
                except:
                    pass

    async def _create_environment_branches(self, app_path: str, repo_url: str, environments: list):
        """Crear branches para cada environment seleccionado"""
        # Map environment to branch name
        env_branches = {
            "dev": "develop",
            "staging": "staging", 
            "prod": "main"  # main ya existe
        }
        
        # Auth URL already set on remote from _push_new_repo, no need to re-auth
        
        for env in environments:
            branch = env_branches.get(env)
            if branch and branch != "main":  # main ya existe
                try:
                    # Crear branch desde main
                    subprocess.run(
                        ["git", "checkout", "-b", branch],
                        cwd=app_path, check=True, capture_output=True
                    )
                    result = subprocess.run(
                        ["git", "push", "-u", "origin", branch],
                        cwd=app_path, capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        logger.error(f"Failed to push branch {branch}: {self._sanitize_error(result.stderr)}")
                    # Volver a main
                    subprocess.run(
                        ["git", "checkout", "main"],
                        cwd=app_path, capture_output=True
                    )
                except subprocess.CalledProcessError as e:
                    stderr = getattr(e, 'stderr', b'')
                    if isinstance(stderr, bytes):
                        stderr = stderr.decode('utf-8', errors='replace')
                    logger.error(f"Failed to create branch {branch} for {env}: {self._sanitize_error(str(stderr))}")

    async def _generate_dynamic_pipeline(self, app_path: str, app_data, environments: list, template_details: dict = None):
        """
        Generate CI/CD config file dynamically based on the current git provider.
        Uses provider.generate_ci_yaml() to produce the correct format.
        """
        app_name = app_data.name
        dockerhub_user = self._credentials.get("dockerhub_username", "")
        workspace_or_org = self.provider._namespace()
        pipeline_email = f"pipeline@{self.domain}" if self.domain else f"pipeline@{PIPELINE_EMAIL_DOMAIN_FALLBACK}"
        template_config = getattr(app_data, 'template_config', {}) or {}
        
        # Detectar tipo de proyecto
        has_package_json = os.path.exists(os.path.join(app_path, "package.json"))
        has_requirements = os.path.exists(os.path.join(app_path, "requirements.txt"))
        
        # Detect package manager for Node projects
        pkg_manager = "npm"
        if has_package_json:
            if os.path.exists(os.path.join(app_path, "pnpm-lock.yaml")):
                pkg_manager = "pnpm"
            elif os.path.exists(os.path.join(app_path, "yarn.lock")):
                pkg_manager = "yarn"
            else:
                try:
                    import json as _json
                    with open(os.path.join(app_path, "package.json"), "r") as _f:
                        _pkg = _json.load(_f)
                    if "pnpm" in _pkg.get("packageManager", ""):
                        pkg_manager = "pnpm"
                    elif "yarn" in _pkg.get("packageManager", ""):
                        pkg_manager = "yarn"
                except Exception:
                    pass

        if has_package_json:
            node_ver = template_config.get("node_version", "20")
            image = f"node:{node_ver}-alpine"
            has_lockfile = (
                os.path.exists(os.path.join(app_path, "pnpm-lock.yaml"))
                or os.path.exists(os.path.join(app_path, "package-lock.json"))
                or os.path.exists(os.path.join(app_path, "yarn.lock"))
            )
            if pkg_manager == "pnpm":
                install_cmd = "corepack enable && pnpm install" + (" --frozen-lockfile" if has_lockfile else "")
                build_cmd = "pnpm run build"
            elif pkg_manager == "yarn":
                install_cmd = "yarn install" + (" --frozen-lockfile" if has_lockfile else "")
                build_cmd = "yarn build"
            else:
                install_cmd = "npm ci" if has_lockfile else "npm install"
                build_cmd = "npm run build"
            build_steps = f"""      - step:
          name: "📦 Install & Build"
          caches:
            - node
          script:
            - {install_cmd}
            - {build_cmd}
          artifacts:
            - dist/**"""
        elif has_requirements:
            py_ver = template_config.get("python_version", "3.11")
            image = f"python:{py_ver}-slim"
            build_steps = """      - step:
          name: "📦 Install Dependencies"
          caches:
            - pip
          script:
            - pip install -r requirements.txt
          artifacts:
            - ./**"""
        else:
            image = "alpine:latest"
            build_steps = """      - step:
          name: "📦 Prepare"
          script:
            - echo "No build step required"
          artifacts:
            - ./**"""
        
        # Use provider to generate the CI YAML
        ci_filepath, ci_content = self.provider.generate_ci_yaml(
            app_name=app_name,
            environments=environments,
            image=image,
            build_steps=build_steps,
            dockerhub_user=dockerhub_user,
            workspace_or_org=workspace_or_org,
            pipeline_email=pipeline_email,
            infra_repo="infra-gitops",
            pkg_manager=pkg_manager if has_package_json else None,
        )
        
        # Ensure parent directories exist (GitHub needs .github/workflows/)
        full_path = os.path.join(app_path, ci_filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(ci_content)

    async def _enable_pipelines(self, app_name: str):
        """Enable CI/CD for the repo using the current provider"""
        await self.provider.enable_ci(app_name)

    async def delete_app(self, app_name: str, environments: list[str] | None = None, provider_name: str = None):
        """
        Elimina una app completa:
        1. Git Repo (via provider)
        2. Directorio en infra-gitops
        3. Secretos en Vault
        4. Tailscale devices
        """
        await self._load_credentials(provider_override=provider_name)
        target_envs = sorted(set((environments or []) + ["dev", "staging", "prod"]))

        cleanup_report = {
            "app_name": app_name,
            "git_repo": {"deleted": False, "status": "unknown", "provider": self.provider.display_name},
            "infra": {"removed": False, "status": "unknown"},
            "vault": {"enabled": False, "deleted_paths": [], "missing_paths": [], "failed_paths": []},
            "tailscale": {"enabled": False, "deleted": [], "not_found": True, "failed": []}
        }

        # 1. Delete Git Repo via provider
        try:
            deleted = await self.provider.delete_repo(app_name)
            cleanup_report["git_repo"] = {
                "deleted": deleted,
                "status": "deleted" if deleted else "not_found",
                "provider": self.provider.display_name,
            }
        except Exception as e:
            cleanup_report["git_repo"] = {"deleted": False, "status": f"error:{e}", "provider": self.provider.display_name}
            logger.warning(f"Failed to delete {self.provider.display_name} repo {app_name}: {e}")

        # 2. Delete from infra-gitops
        infra_path = os.path.join(self.workspace, "infra-gitops")

        # Clone infra-gitops using provider auth
        auth_infra_url = self.provider.get_auth_clone_url("infra-gitops")

        if os.path.exists(infra_path):
            shutil.rmtree(infra_path)

        subprocess.run(["git", "clone", auth_infra_url, infra_path], check=True, capture_output=True)

        # Configurar git user
        subprocess.run(["git", "config", "user.email", f"kaanbal@{self.domain}"], cwd=infra_path)
        subprocess.run(["git", "config", "user.name", "Kaanbal Engine"], cwd=infra_path)

        app_dir = os.path.join(infra_path, "apps", app_name)
        
        if os.path.exists(app_dir):
            # Eliminar directorio
            subprocess.run(["git", "rm", "-r", f"apps/{app_name}"], cwd=infra_path, check=True)
            
            # Commit y Push
            subprocess.run(["git", "commit", "-m", f"chore: delete app {app_name}"], cwd=infra_path, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=infra_path, check=True)
            cleanup_report["infra"] = {"removed": True, "status": "deleted"}
        else:
            cleanup_report["infra"] = {"removed": False, "status": "not_found"}

        # 3. Delete app secrets from Vault (hard delete metadata path)
        cleanup_report["vault"] = await self._delete_vault_app_secrets(app_name, target_envs)

        # 4. Delete Tailscale devices (Ingress and TCP Service devices)
        cleanup_report["tailscale"] = await self._delete_tailscale_devices(app_name, target_envs)
        
        # Cleanup local
        if os.path.exists(infra_path):
            shutil.rmtree(infra_path)
        
        return cleanup_report

    async def _delete_vault_app_secrets(self, app_name: str, environments: list[str]) -> dict:
        vault_addr = self._credentials.get("vault_addr", "")
        vault_token = self._credentials.get("vault_token", "")

        result = {
            "enabled": bool(vault_addr and vault_token),
            "deleted_paths": [],
            "missing_paths": [],
            "failed_paths": []
        }

        if not result["enabled"]:
            return result

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            for env in sorted(set(environments)):
                metadata_url = f"{vault_addr}/v1/secret/metadata/{env}/{app_name}"
                try:
                    response = await client.delete(
                        metadata_url,
                        headers={"X-Vault-Token": vault_token}
                    )
                    path = f"secret/{env}/{app_name}"
                    if response.status_code == 204:
                        result["deleted_paths"].append(path)
                    elif response.status_code == 404:
                        result["missing_paths"].append(path)
                    else:
                        result["failed_paths"].append({
                            "path": path,
                            "status": response.status_code,
                            "error": response.text[:180]
                        })
                except Exception as e:
                    result["failed_paths"].append({
                        "path": f"secret/{env}/{app_name}",
                        "status": "exception",
                        "error": str(e)
                    })

        return result

    # ---- Tailscale API Methods ----

    async def _get_tailscale_api_token(self) -> str | None:
        """
        Exchange Tailscale OAuth client credentials for a short-lived API token.
        Returns the access_token string, or None if credentials are missing/invalid.
        """
        client_id = self._credentials.get("tailscale_client_id", "")
        client_secret = self._credentials.get("tailscale_client_secret", "")
        if not client_id or not client_secret:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    TAILSCALE_OAUTH_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "client_credentials",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 200:
                    return resp.json().get("access_token")
                logger.warning(f"Tailscale OAuth failed: {resp.status_code} {resp.text[:200]}")
                return None
        except Exception as e:
            logger.warning(f"Tailscale OAuth exception: {e}")
            return None

    async def _list_tailscale_devices(self, api_token: str) -> list[dict]:
        """List all devices in the tailnet."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{TAILSCALE_API_BASE}/tailnet/-/devices",
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                if resp.status_code == 200:
                    return resp.json().get("devices", [])
                logger.warning(f"Tailscale list devices failed: {resp.status_code}")
                return []
        except Exception as e:
            logger.warning(f"Tailscale list devices exception: {e}")
            return []

    async def _delete_tailscale_device(self, api_token: str, device_id: str) -> bool:
        """Delete a single Tailscale device by ID. Returns True on success."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(
                    f"{TAILSCALE_API_BASE}/device/{device_id}",
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Tailscale delete device {device_id} exception: {e}")
            return False

    async def _delete_tailscale_devices(self, app_name: str, environments: list[str]) -> dict:
        """
        Delete all Tailscale devices associated with an app across all environments.
        
        Hostname patterns to match:
        - Ingress-based (web apps): {env}-{app_name}-ts-ingress
        - TCP Service-based (databases): {env}-{app_name}
        """
        result = {
            "enabled": False,
            "deleted": [],
            "not_found": True,
            "failed": [],
        }

        api_token = await self._get_tailscale_api_token()
        if not api_token:
            logger.info("Tailscale API credentials not configured, skipping device cleanup")
            return result

        result["enabled"] = True

        # Build set of hostname patterns to match for this app
        target_hostnames = set()
        for env in environments:
            # Ingress pattern (web apps): {env}-{app_name}-ts-ingress
            target_hostnames.add(f"{env}-{app_name}-ts-ingress")
            # TCP Service pattern (databases): {env}-{app_name}
            target_hostnames.add(f"{env}-{app_name}")

        # Also check stored tailscale_hostname from MongoDB
        db = get_db()
        app_doc = await db.apps.find_one(
            {"name": app_name},
            {"connection_info.per_env_exposure": 1}
        )
        if app_doc:
            per_env = app_doc.get("connection_info", {}).get("per_env_exposure", {})
            for env_data in per_env.values():
                ts_hostname = env_data.get("tailscale_hostname", "")
                if ts_hostname:
                    target_hostnames.add(ts_hostname)

        devices = await self._list_tailscale_devices(api_token)

        for device in devices:
            hostname = device.get("hostname", "")
            device_id = device.get("id", "")
            if hostname in target_hostnames:
                result["not_found"] = False
                success = await self._delete_tailscale_device(api_token, device_id)
                if success:
                    result["deleted"].append({"hostname": hostname, "id": device_id})
                    logger.info(f"Deleted Tailscale device: {hostname} ({device_id})")
                else:
                    result["failed"].append({"hostname": hostname, "id": device_id})
                    logger.warning(f"Failed to delete Tailscale device: {hostname} ({device_id})")

        return result

    async def cleanup_orphan_tailscale_devices(self, active_app_names: set[str], environments: list[str], dry_run: bool = False) -> dict:
        """
        Find and optionally delete Tailscale devices that don't belong to any active app.
        Ignores system devices (tailscale-operator, vault-*, personal machines, infra services).
        Also checks stored connection_info.per_env_exposure tailscale_hostname values from MongoDB.
        """
        await self._load_credentials()
        result = {
            "enabled": False,
            "dry_run": dry_run,
            "active_apps": sorted(active_app_names),
            "orphans": [],
            "deleted": [],
            "failed": [],
            "system_devices": [],
        }

        api_token = await self._get_tailscale_api_token()
        if not api_token:
            return result

        result["enabled"] = True
        devices = await self._list_tailscale_devices(api_token)

        # Dispositivos que nunca se tocan: los de la plataforma, más los que la
        # instalación declare en system_config.tailscale_protected_prefixes (sus
        # propias máquinas). Ver app/services/tailscale_guard.py.
        system_prefixes = tailscale_guard.DEFAULT_PROTECTED_PREFIXES

        # Build known hostnames set: standard patterns + stored tailscale_hostname from DB
        known_hostnames = set()
        for env in environments:
            for app_name in active_app_names:
                known_hostnames.add(f"{env}-{app_name}-ts-ingress")
                known_hostnames.add(f"{env}-{app_name}")

        # Also collect tailscale_hostname values from all active apps in MongoDB
        db = get_db()
        app_docs = await db.apps.find(
            {"name": {"$in": list(active_app_names)}},
            {"name": 1, "connection_info.per_env_exposure": 1}
        ).to_list(300)
        for doc in app_docs:
            per_env = doc.get("connection_info", {}).get("per_env_exposure", {})
            for env_data in per_env.values():
                ts_hostname = env_data.get("tailscale_hostname", "")
                if ts_hostname:
                    known_hostnames.add(ts_hostname)

        # Also load infra_tailscale_hostnames from system_config (manually managed services)
        ts_dns_suffix = self._credentials.get("tailscale_dns_suffix", TAILSCALE_DNS_SUFFIX)
        config = await db.system_config.find_one({"_id": "main"})
        system_prefixes = tailscale_guard.protected_prefixes(config)
        if config:
            for h in config.get("infra_tailscale_hostnames", []):
                # Strip FQDN suffix if present, store the bare hostname
                known_hostnames.add(h.replace(f".{ts_dns_suffix}", ""))

        for device in devices:
            hostname = device.get("hostname", "")
            device_id = device.get("id", "")

            # Skip system devices
            if any(hostname.startswith(p) for p in system_prefixes):
                result["system_devices"].append(hostname)
                continue

            # Check against all known hostnames (patterns + DB-stored)
            if hostname in known_hostnames:
                continue

            result["orphans"].append({"hostname": hostname, "id": device_id})
            if not dry_run:
                success = await self._delete_tailscale_device(api_token, device_id)
                if success:
                    result["deleted"].append(hostname)
                else:
                    result["failed"].append(hostname)

        return result

    async def cleanup_orphan_vault_secrets(self, active_app_names: set[str], environments: list[str], dry_run: bool = False) -> dict:
        await self._load_credentials()
        vault_addr = self._credentials.get("vault_addr", "")
        vault_token = self._credentials.get("vault_token", "")

        report = {
            "enabled": bool(vault_addr and vault_token),
            "dry_run": dry_run,
            "active_apps": sorted(active_app_names),
            "orphans": {},
            "deleted": [],
            "failed": []
        }

        if not report["enabled"]:
            return report

        envs = sorted(set(environments or ["dev", "staging", "prod"]))

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            for env in envs:
                try:
                    list_response = await client.get(
                        f"{vault_addr}/v1/secret/metadata/{env}",
                        headers={"X-Vault-Token": vault_token},
                        params={"list": "true"}
                    )

                    if list_response.status_code == 404:
                        report["orphans"][env] = []
                        continue

                    if list_response.status_code != 200:
                        report["failed"].append({
                            "path": f"secret/{env}",
                            "status": list_response.status_code,
                            "error": list_response.text[:180]
                        })
                        report["orphans"][env] = []
                        continue

                    keys = list_response.json().get("data", {}).get("keys", [])
                    normalized = [k.rstrip("/") for k in keys if k]
                    orphans = sorted([k for k in normalized if k not in active_app_names])
                    report["orphans"][env] = orphans

                    if dry_run:
                        continue

                    for orphan in orphans:
                        delete_response = await client.delete(
                            f"{vault_addr}/v1/secret/metadata/{env}/{orphan}",
                            headers={"X-Vault-Token": vault_token}
                        )
                        path = f"secret/{env}/{orphan}"
                        if delete_response.status_code in [204, 404]:
                            report["deleted"].append(path)
                        else:
                            report["failed"].append({
                                "path": path,
                                "status": delete_response.status_code,
                                "error": delete_response.text[:180]
                            })
                except Exception as e:
                    report["failed"].append({
                        "path": f"secret/{env}",
                        "status": "exception",
                        "error": str(e)
                    })

        return report