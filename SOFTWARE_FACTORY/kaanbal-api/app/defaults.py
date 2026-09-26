"""
Kaanbal API - Centralized Defaults
=================================
Single source of truth for ALL default/fallback values used across the application.
Services should import from here instead of scattering magic strings.

These are FALLBACK values only. In production, values come from:
  1. MongoDB system_config (highest priority)
  2. Environment variables
  3. These defaults (lowest priority)
"""

# -- Database --
MONGODB_URI = "mongodb://datastore:27017/forge"

# -- Security --
SECRET_KEY_DEV = "supersecretkey_dev_only"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

# -- Vault --
VAULT_ADDR = "http://vault.vault.svc.cluster.local:8200"
VAULT_HOSTNAME = "vault-vault-ui-ingress"

# -- Tailscale --
# Fallback only. In production this should come from MongoDB system_config.
TAILSCALE_DNS_SUFFIX = "example.ts.net"
TAILSCALE_API_BASE = "https://api.tailscale.com/api/v2"
TAILSCALE_OAUTH_URL = "https://api.tailscale.com/api/v2/oauth/token"

# -- ArgoCD --
# In-cluster DNS (not ClusterIP — that changes per deploy).
# ArgoCD Helm chart exposes 80 and 443; plain HTTP on :80 returns 307 → HTTPS,
# which breaks session POST unless the client follows redirects or uses :443.
ARGOCD_SERVER = "https://argocd-server.argocd.svc.cluster.local:443"
ARGOCD_USERNAME = "admin"

# -- Ingress --
# k3s ships Traefik as the default IngressClass. Declaring a class with no
# controller behind it produces Ingresses that are accepted by the API server
# but never serve traffic, which looks like a broken app for no visible reason.
# The installer writes the real class into system_config; this is the fallback.
INGRESS_CLASS = "traefik"
# Empty means TLS is terminated at the edge (Cloudflare Tunnel) and cert-manager
# is not involved. Set to e.g. "letsencrypt-prod" only when issuing in-cluster.
INGRESS_CLUSTER_ISSUER = ""

# -- Workspace --
WORKSPACE_PATH = "/tmp/kaanbal-workdir"
TEMPLATES_REPO = "kaanbal-templates"

# -- Pipeline --
PIPELINE_EMAIL_DOMAIN_FALLBACK = "kaanbal.local"
PIPELINE_GIT_USER = "Kaanbal Engine"

# -- Activity Logs --
LOG_RETENTION_DAYS = 90
LOG_FORWARDING_TIMEOUT_SEC = 5
LOG_FORWARDING_MIN_LEVEL = "error"

# -- Bitbucket API --
BITBUCKET_API_BASE = "https://api.bitbucket.org"

# -- GitHub API --
GITHUB_API_BASE = "https://api.github.com"

# -- Exposure Rules --
# Allowed exposure types per template category (enforced in deployer + UI)
# Per-environment model: each env selects ONE mode (internal/tailscale/public).
# 'both' is a computed aggregate (mixed envs) - not a selectable option.
# frontend:   public or VPN (internal makes no sense for a UI)
# backend:    internal, VPN, or public (full flexibility)
# database:   internal or VPN (never expose publicly)
# monitoring: VPN only
# devtools:   VPN only
# workflow:   VPN or public (webhooks need public)
# iot:        internal, VPN, or public
# Allowed exposure modes per template category (lifecycle bitácora Fase 0).
# `off` is always allowed at switch-time even if omitted here for create defaults.
EXPOSURE_RULES = {
    "frontend":   ["public", "tailscale", "lan", "off"],
    "backend":    ["internal", "tailscale", "public", "lan", "off"],
    "database":   ["internal", "tailscale", "lan", "off"],  # NEVER public
    "monitoring": ["tailscale", "lan", "off"],
    "devtools":   ["tailscale", "lan", "off"],
    "workflow":   ["tailscale", "public", "lan", "off"],  # v1: full channel per env (no Mixed in create UI)
    "iot":        ["internal", "tailscale", "public", "lan", "off"],
}
EXPOSURE_RULES_DEFAULT = ["internal", "tailscale", "public", "lan", "off"]
