from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os
import secrets
import string
import httpx
import base64
from passlib.context import CryptContext

from app.schemas.setup import SetupRequest, SetupResponse
from app.services.factory_service import FactoryService
from app.routers.auth import get_current_active_user, pwd_context
from app.db import get_db

router = APIRouter()


# ============ VALIDATION MODELS ============

class ValidateGitRequest(BaseModel):
    provider: str = "bitbucket"
    username: str
    token: str
    workspace: str = ""

class ValidateDockerRequest(BaseModel):
    username: str
    token: str

class ValidateCloudflareRequest(BaseModel):
    token: str
    account_id: str


class ValidateTailscaleRequest(BaseModel):
    client_id: str
    client_secret: str
    dns_suffix: str


# ============ VALIDATION ENDPOINTS ============

@router.post("/validate/git")
async def validate_git_credentials(req: ValidateGitRequest):
    """Test Git provider credentials by calling their API."""
    async with httpx.AsyncClient(timeout=15) as client:
        if req.provider == "bitbucket":
            # Bitbucket uses email:app_password or username:app_password
            resp = await client.get(
                f"https://api.bitbucket.org/2.0/repositories/{req.workspace}",
                auth=(req.username, req.token),
                params={"pagelen": 1}
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"valid": True, "message": f"Connected. Workspace '{req.workspace}' has {data.get('size', 0)} repos."}
            elif resp.status_code == 401:
                return {"valid": False, "message": "Authentication failed. Check username and app password."}
            elif resp.status_code == 403:
                return {"valid": False, "message": "Access forbidden. Token may lack repository permissions."}
            elif resp.status_code == 404:
                return {"valid": False, "message": f"Workspace '{req.workspace}' not found. Check the workspace slug."}
            else:
                return {"valid": False, "message": f"Unexpected response: {resp.status_code} - {resp.text[:200]}"}

        elif req.provider == "github":
            resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"token {req.token}", "Accept": "application/vnd.github.v3+json"}
            )
            if resp.status_code == 200:
                user = resp.json().get("login", "")
                return {"valid": True, "message": f"Connected as GitHub user '{user}'."}
            else:
                return {"valid": False, "message": f"GitHub auth failed: {resp.status_code}"}

        elif req.provider == "gitlab":
            resp = await client.get(
                "https://gitlab.com/api/v4/user",
                headers={"PRIVATE-TOKEN": req.token}
            )
            if resp.status_code == 200:
                user = resp.json().get("username", "")
                return {"valid": True, "message": f"Connected as GitLab user '{user}'."}
            else:
                return {"valid": False, "message": f"GitLab auth failed: {resp.status_code}"}

        return {"valid": False, "message": f"Unknown provider: {req.provider}"}


@router.post("/validate/docker")
async def validate_docker_credentials(req: ValidateDockerRequest):
    """Test Docker Hub credentials by calling Docker Hub API."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Docker Hub v2 auth
        resp = await client.post(
            "https://hub.docker.com/v2/users/login/",
            json={"username": req.username, "password": req.token}
        )
        if resp.status_code == 200:
            return {"valid": True, "message": f"Authenticated as Docker Hub user '{req.username}'."}
        elif resp.status_code == 401:
            return {"valid": False, "message": "Authentication failed. Check username and access token."}
        else:
            return {"valid": False, "message": f"Docker Hub error: {resp.status_code} - {resp.text[:200]}"}


@router.post("/validate/cloudflare")
async def validate_cloudflare_credentials(req: ValidateCloudflareRequest):
    """Validate Cloudflare credentials using account/tunnel permissions.

    Some scoped tokens can fail /user/tokens/verify while still being valid for
    account-level APIs. For setup purposes, account + tunnel (+ DNS when possible)
    are the authoritative checks.
    """
    cf_api = "https://api.cloudflare.com/client/v4"
    headers = {"Authorization": f"Bearer {req.token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Token verify is optional (informational only)
        verify_hint = ""
        verify_resp = await client.get(f"{cf_api}/user/tokens/verify", headers=headers)
        if verify_resp.status_code != 200:
            verify_hint = " Token verify endpoint is unavailable for this token scope."
        else:
            try:
                token_status = verify_resp.json().get("result", {}).get("status", "unknown")
                if token_status != "active":
                    verify_hint = f" Token status reported as '{token_status}'."
            except Exception:
                verify_hint = ""

        # 2. Verify account access
        acc_resp = await client.get(f"{cf_api}/accounts/{req.account_id}", headers=headers)
        if acc_resp.status_code == 401:
            return {"valid": False, "message": "Invalid Cloudflare token for account APIs (401 Unauthorized)."}
        if acc_resp.status_code == 403:
            return {"valid": False, "message": "Token cannot access this account. Add 'Account Settings: Read' permission and include your account in resources."}
        if acc_resp.status_code != 200:
            return {"valid": False, "message": f"Cannot access account '{req.account_id}'. Verify the Account ID from your Cloudflare dashboard URL."}

        acc_name = acc_resp.json().get("result", {}).get("name", req.account_id)

        # 3. Check tunnel permission
        tunnel_resp = await client.get(
            f"{cf_api}/accounts/{req.account_id}/cfd_tunnel?is_deleted=false&per_page=1",
            headers=headers
        )
        tunnel_ok = tunnel_resp.status_code == 200

        # 4. Check DNS permission (list zones)
        zones_resp = await client.get(
            f"{cf_api}/zones?account.id={req.account_id}&per_page=5",
            headers=headers
        )
        zones_ok = zones_resp.status_code == 200
        zone_names = []
        if zones_ok:
            zone_names = [z.get("name", "") for z in zones_resp.json().get("result", [])]

        if tunnel_ok and zones_ok:
            count = tunnel_resp.json().get("result_info", {}).get("total_count", 0)
            zones_str = ", ".join(zone_names) if zone_names else "no zones yet"
            return {"valid": True, "message": f"Account '{acc_name}' OK. {count} tunnel(s). Zones: {zones_str}. All permissions verified.{verify_hint}"}
        elif tunnel_ok:
            return {"valid": True, "message": f"Account '{acc_name}' OK. Tunnel permission verified. DNS permission could not be confirmed.{verify_hint}"}
        elif zones_ok:
            zones_str = ", ".join(zone_names) if zone_names else "no zones yet"
            return {"valid": False, "message": f"Account '{acc_name}' OK. DNS zones: {zones_str}. Missing 'Cloudflare Tunnel: Edit' permission."}
        else:
            return {"valid": False, "message": f"Account '{acc_name}' found but token lacks both Tunnel and DNS permissions. Recreate with required permissions."}


@router.post("/validate/tailscale")
async def validate_tailscale_credentials(req: ValidateTailscaleRequest):
    """Validate Tailscale OAuth client by requesting an access token.
    
    Tailscale OAuth uses HTTP Basic Auth (client_id:client_secret)
    with form-encoded body containing grant_type=client_credentials.
    """
    suffix = (req.dns_suffix or "").strip().lower()
    if not suffix.endswith(".ts.net"):
        return {"valid": False, "message": "Invalid DNS suffix format. Expected something like tailXXXX.ts.net"}

    async with httpx.AsyncClient(timeout=15) as client:
        # Tailscale OAuth requires Basic Auth + form-encoded body
        token_resp = await client.post(
            "https://api.tailscale.com/api/v2/oauth/token",
            data="grant_type=client_credentials",
            auth=(req.client_id, req.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_resp.status_code == 401:
            return {
                "valid": False,
                "message": "Invalid Client ID or Client Secret. Regenerate your OAuth client in Tailscale admin console.",
            }

        if token_resp.status_code != 200:
            body_preview = token_resp.text[:200] if token_resp.text else "No response body"
            return {
                "valid": False,
                "message": f"Tailscale auth failed ({token_resp.status_code}): {body_preview}",
            }

        access_token = token_resp.json().get("access_token")
        if not access_token:
            return {"valid": False, "message": "Tailscale auth response missing access_token."}

        # Verify the token works by listing devices (less restrictive than ACL)
        devices_resp = await client.get(
            "https://api.tailscale.com/api/v2/tailnet/-/devices",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if devices_resp.status_code == 200:
            devices = devices_resp.json().get("devices", [])
            return {
                "valid": True,
                "message": f"Tailscale OAuth validated. {len(devices)} device(s) on tailnet. DNS suffix '{suffix}' accepted.",
            }

        # Even if /devices fails, the OAuth token was created — token might have limited scope
        return {
            "valid": True,
            "message": f"Tailscale OAuth credentials valid (token created). DNS suffix '{suffix}' accepted.",
        }


class SetupInstallRequest(BaseModel):
    mode: str
    domain: str = ""
    git_provider: str = "bitbucket"
    git_username: str = ""
    git_token: str = ""
    git_workspace: str = ""
    github_org: str = ""
    github_is_org: Optional[bool] = None
    bitbucket_workspace: str = ""
    dockerhub_username: str = ""
    dockerhub_token: str = ""
    tailscale_client_id: str = ""
    tailscale_client_secret: str = ""
    tailscale_dns_suffix: str = ""
    cloudflare_token: str = ""
    cloudflare_account_id: str = ""
    cloudflare_zone_id: str = ""
    cloudflare_tunnel_id: str = ""
    argocd_password: str = ""
    argocd_server: str = ""
    vault_addr: str = ""
    vault_token: str = ""
    vault_hostname: str = ""
    cluster_ssh_host: str = ""
    # IngressClass realmente instalada (k3s = traefik). Si no coincide con un
    # controlador vivo, las apps se despliegan pero nadie sirve su tráfico.
    ingress_class: str = ""
    # Vacío = TLS terminado en el edge (Cloudflare Tunnel), sin cert-manager.
    ingress_cluster_issuer: str = ""
    admin_user: str
    admin_password: str
    # Procedencia del core (ADR-002). Sin esto la célula no sabe qué versión es
    # y no puede compararse con upstream ni saber a qué volver.
    core_release: Optional[dict] = None


class TunnelRequest(BaseModel):
    domain: str
    cloudflare_token: str
    cloudflare_account_id: str


def get_factory_service():
    return FactoryService()


@router.get("/status")
async def get_setup_status():
    """
    Public endpoint (no auth) — checks if initial setup is complete.
    Used by the frontend to detect first-run and redirect to setup wizard.
    """
    db = get_db()
    user_count = await db.users.count_documents({})
    config = await db.system_config.find_one({"_id": "main"})

    has_creds = False
    if config:
        has_creds = bool(config.get("git_username") and config.get("git_token"))

    return {
        "setup_complete": user_count > 0 and has_creds,
        "has_users": user_count > 0,
        "has_credentials": has_creds
    }


@router.post("/init", response_model=SetupResponse)
async def initialize_factory(
    request: SetupRequest,
    service: FactoryService = Depends(get_factory_service),
    current_user=Depends(get_current_active_user)
):
    result = await service.initialize_factory(request)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/install")
async def run_full_install(request: SetupInstallRequest):
    """
    Public endpoint to bootstrap the platform — creates admin user + saves config.
    First call: creates admin user + saves config.
    Subsequent calls: updates config only (idempotent reinstall support).
    """
    db = get_db()
    user_count = await db.users.count_documents({})
    is_reinstall = user_count > 0

    if not is_reinstall:
        admin_user = {
            "username": request.admin_user,
            "email": f"{request.admin_user}@local.me",
            "hashed_password": pwd_context.hash(request.admin_password),
            "is_active": True,
            "is_superuser": True,
        }
        await db.users.insert_one(admin_user)

    config_update = {"mode": request.mode}
    if request.core_release:
        # Reinstalar no debe borrar la procedencia si el instalador no la manda;
        # solo se pisa cuando viene una nueva.
        config_update["core_release"] = {
            "applied_by": "installer",
            **request.core_release,
            # Siempre la hora del servidor: es cuándo quedó aplicada, no cuándo
            # la armó el instalador.
            "applied_at": datetime.utcnow(),
        }
    if request.domain:
        config_update["domain"] = request.domain
    if request.git_username:
        config_update["git_username"] = request.git_username
        config_update["git_token"] = request.git_token
        config_update["git_provider"] = request.git_provider
        config_update["bitbucket_workspace"] = request.git_workspace
        # Ensure github_token/github_org are set when provider is github
        if request.git_provider == "github":
            config_update["github_token"] = request.git_token
            config_update["github_org"] = request.git_workspace
            # Prefer explicit value from installer; otherwise auto-detect (workspace != PAT user => org)
            if request.github_is_org is not None:
                config_update["github_is_org"] = bool(request.github_is_org)
            else:
                config_update["github_is_org"] = bool(
                    request.git_workspace
                    and request.git_username
                    and request.git_workspace.lower() != request.git_username.lower()
                )
    if request.dockerhub_username:
        config_update["dockerhub_username"] = request.dockerhub_username
        config_update["dockerhub_token"] = request.dockerhub_token
    if request.tailscale_client_id:
        config_update["tailscale_client_id"] = request.tailscale_client_id
        config_update["tailscale_client_secret"] = request.tailscale_client_secret
    if request.tailscale_dns_suffix:
        config_update["tailscale_dns_suffix"] = request.tailscale_dns_suffix
    if request.cloudflare_token:
        config_update["cloudflare_token"] = request.cloudflare_token
        config_update["cloudflare_account_id"] = request.cloudflare_account_id
    if request.cloudflare_zone_id:
        config_update["cloudflare_zone_id"] = request.cloudflare_zone_id
    if request.cloudflare_tunnel_id:
        config_update["cloudflare_tunnel_id"] = request.cloudflare_tunnel_id
    if request.argocd_password:
        config_update["argocd_password"] = request.argocd_password
    if request.argocd_server:
        config_update["argocd_server"] = request.argocd_server
    if request.vault_token:
        config_update["vault_token"] = request.vault_token
    if request.vault_addr:
        config_update["vault_addr"] = request.vault_addr
    if request.vault_hostname:
        config_update["vault_hostname"] = request.vault_hostname
    if request.cluster_ssh_host:
        config_update["cluster_ssh_host"] = request.cluster_ssh_host
    if request.ingress_class:
        config_update["ingress_class"] = request.ingress_class
    # Se escribe siempre (incluso vacío): "sin cert-manager" es una decisión
    # explícita del instalador, no una ausencia de configuración.
    config_update["ingress_cluster_issuer"] = request.ingress_cluster_issuer

    await db.system_config.update_one(
        {"_id": "main"},
        {"$set": config_update},
        upsert=True
    )

    if is_reinstall:
        return {"status": "success", "message": "Configuration updated (reinstall — admin user unchanged)."}
    return {"status": "success", "message": "Configuration saved."}


@router.post("/tunnel")
async def create_cloudflare_tunnel(
    request: TunnelRequest,
    current_user=Depends(get_current_active_user)
):
    """
    Creates a Cloudflare Tunnel + DNS records via the Cloudflare API.
    Returns the tunnel token for cloudflared deployment.
    """
    cf_api = "https://api.cloudflare.com/client/v4"
    headers = {
        "Authorization": f"Bearer {request.cloudflare_token}",
        "Content-Type": "application/json"
    }

    hostname = os.uname().nodename if hasattr(os, 'uname') else "factory"
    tunnel_name = f"software-factory-{hostname}".lower().replace(" ", "-")
    tunnel_secret = base64.b64encode(secrets.token_bytes(32)).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Create tunnel
        create_resp = await client.post(
            f"{cf_api}/accounts/{request.cloudflare_account_id}/cfd_tunnel",
            headers=headers,
            json={"name": tunnel_name, "tunnel_secret": tunnel_secret}
        )

        if create_resp.status_code != 200:
            errors = create_resp.json().get("errors", [])
            msg = errors[0]["message"] if errors else "Failed to create tunnel"
            raise HTTPException(status_code=400, detail=msg)

        tunnel_data = create_resp.json()["result"]
        tunnel_id = tunnel_data["id"]
        tunnel_token = tunnel_data.get("token", "")

        # 2. Configure ingress rules
        await client.put(
            f"{cf_api}/accounts/{request.cloudflare_account_id}/cfd_tunnel/{tunnel_id}/configurations",
            headers=headers,
            json={
                "config": {
                    "ingress": [
                        {
                            "hostname": f"kaanbal-console.{request.domain}",
                            "service": "http://kaanbal-console.prod.svc.cluster.local:80"
                        },
                        {
                            "hostname": f"api.{request.domain}",
                            "service": "http://kaanbal-api.prod.svc.cluster.local:80"
                        },
                        {
                            "hostname": f"*.{request.domain}",
                            "service": "http://ingress-nginx-controller.ingress-nginx.svc.cluster.local:80"
                        },
                        {"service": "http_status:404"}
                    ]
                }
            }
        )

        # 3. Get Zone ID
        zone_resp = await client.get(
            f"{cf_api}/zones?name={request.domain}&status=active",
            headers=headers
        )
        zone_results = zone_resp.json().get("result", [])
        zone_id = zone_results[0]["id"] if zone_results else None

        dns_created = []
        if zone_id:
            cname_target = f"{tunnel_id}.cfargotunnel.com"
            for sub in ["kaanbal-console", "api"]:
                fqdn = f"{sub}.{request.domain}"

                # Check if record exists
                existing_resp = await client.get(
                    f"{cf_api}/zones/{zone_id}/dns_records?type=CNAME&name={fqdn}",
                    headers=headers
                )
                existing = existing_resp.json().get("result", [])

                if existing:
                    await client.put(
                        f"{cf_api}/zones/{zone_id}/dns_records/{existing[0]['id']}",
                        headers=headers,
                        json={"type": "CNAME", "name": fqdn, "content": cname_target, "proxied": True}
                    )
                else:
                    await client.post(
                        f"{cf_api}/zones/{zone_id}/dns_records",
                        headers=headers,
                        json={"type": "CNAME", "name": fqdn, "content": cname_target, "proxied": True}
                    )
                dns_created.append(fqdn)

    # Save tunnel config to MongoDB
    db = get_db()
    await db.system_config.update_one(
        {"_id": "main"},
        {"$set": {
            "cloudflare_token": request.cloudflare_token,
            "cloudflare_account_id": request.cloudflare_account_id,
            "cloudflare_tunnel_id": tunnel_id,
            "cloudflare_tunnel_token": tunnel_token,
            "cloudflare_zone_id": zone_id,
            "domain": request.domain,
            "tunnel_provider": "cloudflare"
        }},
        upsert=True
    )

    return {
        "status": "success",
        "tunnel_id": tunnel_id,
        "dns_records": dns_created,
        "message": f"Tunnel created. DNS: {', '.join(dns_created)}"
    }


class BootstrapCoreCIRequest(BaseModel):
    repos: list[str] = ["kaanbal-api", "kaanbal-console"]


@router.post("/bootstrap-core-ci")
async def bootstrap_core_ci(request: BootstrapCoreCIRequest):
    """Inyecta los secrets de GitHub Actions en los repos del core.

    El instalador construye la primera imagen dentro del cluster, pero a partir
    de ahí quien publica es el workflow de cada repo — y no puede hacerlo sin
    credenciales de Docker Hub ni permiso para escribir en infra-gitops.

    Lo hace el API y no el instalador porque cifrar un secret de Actions exige
    un sealed box de libsodium (PyNaCl), que aquí sí está disponible; el
    instalador corre solo con la stdlib de Python.

    Endpoint público como el resto del bootstrap: solo funciona mientras la
    plataforma tenga credenciales de Git y Docker Hub ya sembradas.
    """
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}

    git_token = config.get("github_token") or config.get("git_token", "")
    workspace = config.get("github_org") or config.get("bitbucket_workspace", "")
    docker_user = config.get("dockerhub_username", "")
    docker_token = config.get("dockerhub_token", "")

    missing = [name for name, value in [
        ("git_token", git_token), ("github_org", workspace),
        ("dockerhub_username", docker_user), ("dockerhub_token", docker_token),
    ] if not value]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan credenciales en system_config: {', '.join(missing)}")

    from app.services.git_provider import get_git_provider

    provider = get_git_provider("github", {
        "git_user": config.get("git_username", ""),
        "git_token": git_token,
        "github_org": workspace,
        "github_token": git_token,
        "github_is_org": config.get("github_is_org"),
    })

    # El workflow de cada repo core usa estos nombres (ver build-deploy.yml).
    variables = [
        {"key": "DOCKERHUB_USERNAME", "value": docker_user, "secured": True},
        {"key": "DOCKERHUB_TOKEN", "value": docker_token, "secured": True},
        {"key": "INFRA_GIT_USER", "value": "x-access-token", "secured": True},
        {"key": "INFRA_GIT_TOKEN", "value": git_token, "secured": True},
    ]

    configured, failed = [], {}
    for repo in request.repos:
        try:
            await provider.set_ci_variables(repo, variables)
            configured.append(repo)
        except Exception as exc:
            failed[repo] = str(exc)[:200]

    return {
        "status": "success" if not failed else "partial",
        "configured": configured,
        "failed": failed,
    }
