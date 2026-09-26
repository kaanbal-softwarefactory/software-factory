"""
Admin Settings Router
====================
Manages system configuration and settings accessible to admins.
Provides centralized configuration for:
- Domain
- ArgoCD URL
- Vault hostname
- Tailscale DNS suffix
- And other system-wide settings
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.db import get_db
from app.defaults import VAULT_ADDR, TEMPLATES_REPO, ARGOCD_USERNAME
from app.routers.auth import get_current_active_user

router = APIRouter()


class SettingsResponse(BaseModel):
    """Settings configuration response model"""
    _id: str = "main"
    domain: str
    argocd_url: str
    argocd_server: Optional[str] = None
    argocd_username: Optional[str] = None
    cluster_ssh_host: str = ""
    vault_hostname: str
    vault_addr: str
    vault_token_masked: str
    tailscale_dns_suffix: str
    bitbucket_workspace: str
    bitbucket_email: Optional[str] = None
    templates_repo: str
    dockerhub_username: Optional[str] = None
    dockerhub_token_masked: Optional[str] = None  # masked for display
    git_username: Optional[str] = None
    git_token_masked: Optional[str] = None  # masked for display
    git_provider: Optional[str] = None
    github_org: Optional[str] = None
    github_token_masked: Optional[str] = None
    github_is_org: Optional[bool] = None
    logs_retention_days: int = 90
    logs_forwarding_webhook_url_masked: Optional[str] = None
    logs_forwarding_min_level: Optional[str] = "error"


class SettingsUpdate(BaseModel):
    """Settings update request model (all fields optional)"""
    domain: Optional[str] = None
    argocd_url: Optional[str] = None
    argocd_server: Optional[str] = None
    argocd_username: Optional[str] = None
    argocd_password: Optional[str] = None
    cluster_ssh_host: Optional[str] = None
    vault_hostname: Optional[str] = None
    vault_addr: Optional[str] = None
    vault_token: Optional[str] = None
    tailscale_dns_suffix: Optional[str] = None
    bitbucket_workspace: Optional[str] = None
    bitbucket_email: Optional[str] = None
    templates_repo: Optional[str] = None
    dockerhub_username: Optional[str] = None
    dockerhub_token: Optional[str] = None  # stored in MongoDB, not in env
    git_username: Optional[str] = None
    git_token: Optional[str] = None  # stored in MongoDB, not in env
    # Git provider selection
    git_provider: Optional[str] = None  # "bitbucket" | "github"
    github_org: Optional[str] = None
    github_token: Optional[str] = None
    github_is_org: Optional[bool] = None
    # Cloudflare
    cloudflare_token: Optional[str] = None
    cloudflare_account_id: Optional[str] = None
    cloudflare_tunnel_id: Optional[str] = None
    cloudflare_zone_id: Optional[str] = None
    # Activity logs
    logs_retention_days: Optional[int] = None
    logs_forwarding_webhook_url: Optional[str] = None
    logs_forwarding_min_level: Optional[str] = None


async def verify_admin(current_user = Depends(get_current_active_user)):
    """Verify that user has admin role"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required"
        )
    return current_user


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(current_user = Depends(verify_admin)):
    """
    Get current system settings.
    Admin only.
    """
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"})

    if not config:
        # Return default/empty settings
        return SettingsResponse(
            domain="",
            argocd_url="",
            cluster_ssh_host="",
            vault_hostname="",
            vault_addr=VAULT_ADDR,
            vault_token_masked="****",
            tailscale_dns_suffix="",
            bitbucket_workspace="",
            bitbucket_email="",
            templates_repo=TEMPLATES_REPO,
            dockerhub_username="",
        dockerhub_token_masked="",
        )

    return SettingsResponse(
        _id=config.get("_id", "main"),
        domain=config.get("domain", ""),
        argocd_url=config.get("argocd_url", ""),
        argocd_server=config.get("argocd_server", ""),
        argocd_username=config.get("argocd_username", ARGOCD_USERNAME),
        cluster_ssh_host=config.get("cluster_ssh_host", ""),
        vault_hostname=config.get("vault_hostname", ""),
        vault_addr=config.get("vault_addr", VAULT_ADDR),
        vault_token_masked=f"****{config.get('vault_token', '')[-4:]}" if config.get("vault_token") else "****",
        tailscale_dns_suffix=config.get("tailscale_dns_suffix", ""),
        bitbucket_workspace=config.get("bitbucket_workspace", ""),
        bitbucket_email=config.get("bitbucket_email", ""),
        templates_repo=config.get("templates_repo", TEMPLATES_REPO),
        dockerhub_username=config.get("dockerhub_username", ""),
        dockerhub_token_masked=f"****{config.get('dockerhub_token', '')[-4:]}" if config.get("dockerhub_token") else "",
        git_username=config.get("git_username", ""),
        git_token_masked=f"****{config.get('git_token', '')[-4:]}" if config.get("git_token") else "",
        git_provider=config.get("git_provider", "bitbucket"),
        github_org=config.get("github_org", ""),
        github_token_masked=f"****{config.get('github_token', '')[-4:]}" if config.get("github_token") else "",
        github_is_org=config.get("github_is_org", False),
        logs_retention_days=int(config.get("logs_retention_days", 90) or 90),
        logs_forwarding_webhook_url_masked=(
            f"****{str(config.get('logs_forwarding_webhook_url', ''))[-12:]}"
            if config.get("logs_forwarding_webhook_url") else ""
        ),
        logs_forwarding_min_level=config.get("logs_forwarding_min_level", "error"),
    )


@router.put("/settings")
async def update_settings(
    update: SettingsUpdate,
    current_user = Depends(verify_admin)
):
    """
    Update system settings.
    Admin only. Only sends non-null fields.
    """
    db = get_db()

    # Filter out None values
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}

    if not update_data:
        return {"message": "No fields to update"}

    if "logs_retention_days" in update_data:
        days = int(update_data["logs_retention_days"])
        if days < 1 or days > 3650:
            raise HTTPException(status_code=422, detail="logs_retention_days must be between 1 and 3650")

    if "logs_forwarding_min_level" in update_data:
        allowed = {"debug", "info", "warn", "error"}
        if str(update_data["logs_forwarding_min_level"]).lower() not in allowed:
            raise HTTPException(status_code=422, detail="logs_forwarding_min_level must be one of: debug, info, warn, error")

    # Add audit fields
    update_data["updated_at"] = datetime.utcnow()
    update_data["updated_by"] = current_user.username

    # Update in MongoDB
    result = await db.system_config.update_one(
        {"_id": "main"},
        {"$set": update_data},
        upsert=True
    )

    return {
        "message": "Settings updated successfully",
        "updated_fields": list(update_data.keys()),
        "modified_count": result.modified_count
    }


@router.get("/settings-public")
async def get_settings_public():
    """
    Get NON-SENSITIVE settings (public endpoint, no auth required).
    Only returns non-sensitive runtime config used by frontend URL builders.
    No credentials are exposed.
    """
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"})

    if not config:
        return {
            "domain": "",
            "argocd_url": "",
            "cluster_ssh_host": "",
            "vault_hostname": "",
            "tailscale_dns_suffix": "",
            "git_provider": "bitbucket",
            "bitbucket_workspace": "",
            "github_org": "",
            "templates_repo": TEMPLATES_REPO,
        }

    return {
        "domain": config.get("domain", ""),
        "argocd_url": config.get("argocd_url", ""),
        "cluster_ssh_host": config.get("cluster_ssh_host", ""),
        "vault_hostname": config.get("vault_hostname", ""),
        "tailscale_dns_suffix": config.get("tailscale_dns_suffix", ""),
        "git_provider": config.get("git_provider", "bitbucket"),
        "bitbucket_workspace": config.get("bitbucket_workspace", ""),
        "github_org": config.get("github_org", ""),
        "templates_repo": config.get("templates_repo", TEMPLATES_REPO),
    }
