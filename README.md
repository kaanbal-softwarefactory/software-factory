<div align="center">

# Kaanbal

**A self-hosted platform to deploy and operate applications on your own server,
with GitHub, GitOps and Kubernetes.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v1.0.0-informational.svg)](CHANGELOG.md)

[Español](README.es.md) · [Install guide](docs/guides/INSTALL_UBUNTU.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

</div>

---

## What is Kaanbal?

Kaanbal turns a single Ubuntu server, or a VPS, into a small platform-as-a-service.
You install it with one command, finish a guided setup in your browser, and then
launch applications — frontend, API, database, workflows — from a web console.

Every application gets its own GitHub repository and CI pipeline. What runs is
described by Kubernetes manifests committed to a GitOps repository and reconciled
by Argo CD, so the state of your platform is always in Git. Secrets live in Vault,
never in Git.

Each application can be reachable **on your LAN**, **privately over a Tailscale VPN**
or **publicly through a Cloudflare Tunnel**, chosen per application and per environment.

## Features

- **One-command install.** A bootstrap script plus a web wizard. The installer uses
  only the Python standard library, so nothing has to be `pip install`ed on the server.
- **Web console.** Applications, templates, stacks, domains, links between services,
  sites, activity log, updates and access control.
- **Templates.** Vue 3, React, FastAPI, MongoDB, PostgreSQL, n8n and EMQX out of the
  box, plus a [documented spec](SOFTWARE_FACTORY/docs/TEMPLATE_SPEC.md) for community templates.
- **Stacks.** Launch database, API and frontend together, already wired: the API is
  bound to its database and the frontend is built with the real URL of its API.
  A stack can take the root of a domain as its homepage.
- **GitOps by default.** One repository and CI pipeline per app, generated manifests,
  Argo CD sync. `infra-gitops` is the source of truth for what runs.
- **Several domains per installation.** Each domain gets its own site: a homepage
  plus the APIs and databases that belong to it.
- **Exposure control.** Internal, LAN, VPN or public, per environment.
- **Secrets in Vault**, generated per app. Bindings inject the variable names your
  code already expects: `MONGO_URI`, `DATABASE_URL`, `PGHOST`, `REDIS_URL`, …
- **Access control.** Roles, per-endpoint permissions that fail closed (an endpoint
  with no rule is denied), per-person exceptions, and personal access tokens that can
  never do more than their owner.
- **Safe core updates.** Upgrade from the console as a Kubernetes Job that verifies
  the result and rolls back automatically.
- **MCP server built in.** Connect Claude Code, Cursor or Codex with just a URL and a
  personal token (`https://<your-api>/mcp`): your agent diagnoses failures in plain
  language, launches apps and full stacks, links them, publishes them on your domains and
  operates them — always showing the plan before applying those changes, and guided by the
  platform itself. Optional critical operations require explicit resource grants and a
  short-lived elevated token; commands within that scope may expose sensitive data.
- **Acuaponsito.** An embeddable agent runtime with a live character, where every
  action needs human approval.

## Architecture

```text
 ┌──────────────────┐        ┌────────────────────────┐        ┌──────────┐
 │ kaanbal-console  │───────▶│      kaanbal-api       │───────▶│ MongoDB  │
 │  (Vue 3)         │        │  (FastAPI, ACL, tokens)│        └──────────┘
 └──────────────────┘        └───────────┬────────────┘
   AI agents · /mcp ───────────────────▶ │
                                         │  GitHub · Docker Hub · Cloudflare · Tailscale
                                         ▼
                           ┌────────────────────────┐   sync    ┌───────────────┐
                           │  infra-gitops (Git)    │──────────▶│    Argo CD    │
                           └────────────────────────┘           └───────┬───────┘
                                                                        ▼
                                          K3s cluster: your apps · Vault · ingress · tunnel / VPN
```

## Quick start

**You need**

- A dedicated Ubuntu Server (22.04 or newer) with OpenSSH and `sudo`, at least 4 GB of
  RAM (the installer refuses less) and Internet access.
- A GitHub user or organization and a personal access token (classic, with `repo`,
  `workflow` and `read:org`). Kaanbal creates repositories there.
- A Docker Hub account and an access token. Images are published there today.
- Optional: a domain in Cloudflare for public exposure, and a Tailscale tailnet for
  private exposure.

**Install**, from an SSH session on the server:

```bash
( set -e; if ! command -v curl >/dev/null; then sudo apt-get update; sudo apt-get install -y curl ca-certificates; fi; revision=main; script=$(mktemp); trap 'rm -f "$script"' EXIT; curl --fail --show-error --location "https://raw.githubusercontent.com/kaanbal-softwarefactory/software-factory/${revision}/install.sh" --output "$script"; bash "$script" --ref "$revision" --lan )
```

The command downloads the whole script before running it, and prints a temporary URL
such as `http://192.168.1.50:3000/?token=…`. Open it in a browser on the same network,
create the administrator and enter your provider credentials in the wizard — never in
a chat or a file. When you confirm the final login, the installer revokes its token and
shuts itself down.

- Use `--tailscale` instead of `--lan` if the server is already on your tailnet, or
  `--ssh-tunnel` if the local network is not trusted.
- Replace `main` with a commit SHA or tag to repeat exactly the same code. `main` moves.
- To install from a fork or a mirror: `KAANBAL_REPO=https://github.com/<you>/<fork>.git bash install.sh …`
- `--reset` removes a previous Kaanbal installation on that machine, including its data
  and credentials. Use it only to repeat clean test installs.

The full walkthrough — SSH keys, tunnel, providers, Vault recovery and reboot — is in the
[install guide](docs/guides/INSTALL_UBUNTU.md) (Spanish).

## Documentation

Most documentation is written in Spanish for now. Translations are very welcome.

| | |
|---|---|
| [Install guide](docs/guides/INSTALL_UBUNTU.md) | Ubuntu, SSH, providers, Vault, reboot |
| [Migrating from the previous repository](docs/guides/MIGRATION.md) | For installations that predate v1.0.0 |
| [Architecture](docs/architecture/KAANBAL_LOCAL_V0.md) · [Blueprint](SOFTWARE_FACTORY/BLUEPRINT.md) · [GitOps](SOFTWARE_FACTORY/infra-gitops/ARCHITECTURE.md) | How the pieces fit |
| [Architecture decisions](docs/adr/) | Why core updates work the way they do |
| [Template spec](SOFTWARE_FACTORY/docs/TEMPLATE_SPEC.md) | How to write a community template |
| [MCP server](SOFTWARE_FACTORY/kaanbal-mcp/README.md) | Connect an AI agent to your platform |

## Repository layout

```text
install.sh                     public bootstrap: download, verify, run the installer
SOFTWARE_FACTORY/
├── installer/                 web installer (Python standard library)
├── kaanbal-api/               FastAPI control plane
├── kaanbal-console/           Vue 3 console
├── kaanbal-mcp/               stdio bridge to the built-in MCP server
├── kaanbal-templates/         template catalog
├── kaanbal-agent/             agent command-center UI (prototype)
├── acuaponsito/               embeddable agent runtime
├── infra-gitops/              GitOps baseline, rendered for each installation
└── tools/                     operational scripts: upgrade, rebuild, reset
docs/                          architecture, decisions, guides
```

## Development

```bash
# API
cd SOFTWARE_FACTORY/kaanbal-api && pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py'

# Installer
python -m pip install PyYAML==6.0.2
python -m unittest discover -s SOFTWARE_FACTORY/installer -p 'test_*.py'

# Console
cd SOFTWARE_FACTORY/kaanbal-console && npm ci && npm run build

# MCP server
cd SOFTWARE_FACTORY/kaanbal-mcp && pip install -r requirements.txt && python -m unittest discover -s tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Status and known limitations

v1.0.0 is the first public release of a platform its maintainers run themselves.
It is not a hardened enterprise product; please read this before relying on it.

- A full install on Ubuntu 26.04 has not been validated end to end, and the K3s, Argo CD
  and Tailscale versions the installer downloads are not pinned.
- Vault is unsealed manually after a reboot; there is no auto-unseal. The installer keeps
  recovery material on the server, and you must back it up somewhere else.
- The API is bootstrapped with a Vault root token. Replacing it with a scoped,
  renewable credential is pending.
- Docker Hub is required today; a local builder with an alternative registry is not
  implemented yet.
- There has been no independent security review. Report vulnerabilities privately as
  described in [SECURITY.md](SECURITY.md).

## License

Kaanbal is released under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
