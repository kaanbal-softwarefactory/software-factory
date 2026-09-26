# Kaanbal Engine — Software Factory

Open-source PaaS for deploying applications on any Linux VPS with Kubernetes (K3s), GitOps (ArgoCD), and a web console.

## Quick Start

### Install directly on Ubuntu Server

```bash
git clone https://github.com/kaanbal-softwarefactory/software-factory.git
cd software-factory/SOFTWARE_FACTORY
sudo bash ./install.sh
```

The command prints a temporary `http://<server-ip>:3000/?token=...` URL. Complete
the wizard, confirm the platform administrator login, and the privileged
installer automatically revokes its token and shuts down.

To repeat a clean DEV/lab installation while keeping credentials and external
GitHub/Cloudflare resources:

```bash
sudo bash ./install.sh --reset-local --preserve-credentials
```

## Repository Layout

```
SOFTWARE_FACTORY/
├── tools/                ← install helpers (install-from-env.ps1, sync scripts)
├── installer/            ← temporary web installer
├── install.sh            ← privileged bootstrap + reset entrypoint
├── kaanbal-api/          ← FastAPI backend
├── kaanbal-console/      ← Vue 3 web dashboard
├── kaanbal-templates/    ← deployable app templates + catalog
└── infra-gitops/         ← Kubernetes GitOps manifests
```

During installation the wizard lets you select the GitHub organization and
creates the missing core repositories there.

## Requirements

| Requirement | Minimum |
|-------------|---------|
| OS | Ubuntu 22.04+ |
| RAM | 4 GB |
| Disk | 20 GB free |
| CPU | 2 cores |

You also need a GitHub PAT with `repo` + `read:org` (and organization admin
membership to create repos), Docker Hub, Cloudflare for public TLS/tunnel, and
optionally Tailscale for private exposure.

## Configuration

You can fill credentials in the wizard, upload a local `.env`, or preseed
`/etc/kaanbal/installer.env` (mode 600):

- `GITHUB_ORG` / `GITOPS_TOKEN` — GitHub org and PAT
- `KB_DOCKER_USER` / `KB_DOCKER_TOKEN` — Docker Hub credentials
- `KB_CLOUDFLARE_TOKEN` / `KB_CLOUDFLARE_ACCOUNT_ID` — Cloudflare API
- `KB_TAILSCALE_*` — Tailscale OAuth credentials (optional)

See [installer/README.md](installer/README.md) for lifecycle and reset details.

## License

Apache 2.0 — see [LICENSE](../LICENSE).
