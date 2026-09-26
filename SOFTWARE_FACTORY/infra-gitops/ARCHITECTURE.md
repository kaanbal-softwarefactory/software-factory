# Kaanbal Engine — Infrastructure & Architecture

> GitOps manifests, Kubernetes resources, and ArgoCD configuration.
>
> Last updated: 2026-03-19

## Overview

This repo holds the Kubernetes manifests that ArgoCD watches. When the API deploys an app,
it writes K8s manifests here → ArgoCD auto-syncs → app runs in the cluster.

## Repo Structure

```
infra-gitops/
├── apps/                    # User-deployed apps (ArgoCD auto-discovery)
│   └── <app-name>/
│       ├── base/            # Kustomize base (deployment, service, ingress)
│       └── overlays/
│           ├── dev/
│           ├── staging/
│           └── prod/
├── argocd/                  # ArgoCD configuration
│   ├── applications/        # Core app definitions
│   └── applicationsets/     # Auto-discovery generators
├── core/                    # Platform infrastructure
│   ├── config/              # ConfigMaps, system config
│   ├── namespaces/          # Namespace definitions
│   └── secrets/             # Secret templates
├── scripts/                 # Operational scripts
└── terraform/               # IaC (EC2, networking)
    ├── main.tf
    ├── variables.tf
    └── terraform.tfvars     # Credentials (git-ignored)
```

## Repository Map

| Repo | Purpose | CI/CD |
|------|---------|-------|
| **softwarefactory** | Installer (bash, dashboard UI) | GitHub Releases |
| **kaanbal-api** | Backend API (FastAPI) | GitHub Actions → Docker Hub → ArgoCD |
| **kaanbal-console** | Web dashboard (Vue 3) | GitHub Actions → Docker Hub → ArgoCD |
| **kaanbal-templates** | Template catalog (JSON) | Manual push |
| **infra-gitops** | K8s manifests (this repo) | ArgoCD auto-sync |

All repos live under [github.com/kaanbal-softwarefactory](https://github.com/kaanbal-softwarefactory).

## Deployment Flow

```
1. Developer pushes code → GitHub repo
2. GitHub Actions → Build Docker image → Push to Docker Hub
3. Action updates infra-gitops overlays/<env>/kustomization.yaml (newTag)
4. ArgoCD detects change → Syncs to K8s cluster
5. Cloudflare DNS auto-created (CNAME) → App available at <app>.domain.com
```

### Kustomize Convention

- **Base** `kustomization.yaml`: Only lists `resources:`, NO `images:` section
- **Overlay** `kustomization.yaml`: Defines `images:` with `newTag` for CI updates
- Pipeline updates ONLY the overlay, never the base

## Install Flow

```bash
# On a fresh Ubuntu 22.04+ server:
git clone https://github.com/kaanbal-softwarefactory/software-factory.git
cd software-factory
bash install.sh
```

The installer deploys K3s, ArgoCD, MongoDB, kaanbal-api, kaanbal-console, and opens a
dashboard at `:3000`. After setup, the Kaanbal Console is available at `:30080`.

## URL Patterns

| Service | URL |
|---------|-----|
| Kaanbal Console | `https://kaanbal-console.<domain>` |
| Kaanbal API | `https://kaanbal-api.<domain>` |
| User apps (prod) | `https://<app>.<domain>` |
| User apps (dev/staging) | `http://<env>-<app>.<tailnet>.ts.net` |

## Core Components

| Component | Purpose |
|-----------|---------|
| K3s | Lightweight Kubernetes |
| ArgoCD | GitOps controller (selfHeal: true) |
| Traefik / Nginx Ingress | HTTP routing + TLS |
| cert-manager | Let's Encrypt certificates |
| Vault | Secret management |
| Tailscale Operator | VPN access for non-prod environments |
| Cloudflare Tunnel | Public access without open ports |

## Philosophy

> "Infrastructure should be invisible. Developers should focus on code."

1. **GitOps First** — all changes via Git commits
2. **API First** — UI is just another API client
3. **Portable** — one command = full platform
4. **Extensible** — templates for any technology
