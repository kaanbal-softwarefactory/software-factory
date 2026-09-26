# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-26

First public release.

This repository starts a new history. The project previously lived in
`ProyectosUniUAEH/software-factory`, whose earlier history is intentionally not carried
over. Installations that predate this release should follow
[docs/guides/MIGRATION.md](docs/guides/MIGRATION.md).

### Added

**Installer**
- Public bootstrap (`install.sh`) that downloads the whole script and a pinned revision
  before running anything, and a web wizard that installs K3s, Argo CD, Vault, ingress and
  the Kaanbal core on a single Ubuntu server.
- Access modes for the wizard: LAN, Tailscale and SSH tunnel. The temporary token is
  revoked and the service shuts down once the final login is confirmed.
- Unattended mode (`--unattended --env <file>`) that shares validation with the wizard.
- Vault recovery material kept before unsealing, with a `--recover` command.
- GitOps baseline rendered per installation from templates, with a declared allowlist
  of what is published to the operator's `infra-gitops` repository.

**Control plane (API and console)**
- Application lifecycle from templates: repository, generated CI, image build, manifests
  in `infra-gitops`, Argo CD sync, per-environment start, stop and scale.
- Exposure control per environment: internal, LAN, Tailscale VPN or public through a
  Cloudflare Tunnel, with DNS and health probes.
- Several domains per installation, a homepage per domain, and a "Sites" view that groups
  each homepage with its API and database. Existing apps can be promoted to homepage.
- Stacks: launch a database, an API and a frontend in one operation, already wired, with
  the option to serve the frontend at the root of a domain.
- Database bindings that inject conventional variable names (`MONGO_URI`,
  `DATABASE_URL`, `PG*`, `MYSQL_*`, `REDIS_URL`) next to the prefixed ones, and a repair
  action for apps created before that.
- Service links with generated NetworkPolicies, and a registry of sites (workers, edge
  gateways) with desired-state reconciliation.
- Activity log, Vault synchronization and reconciliation, and cluster inventory.

**Security**
- Roles with a canonical permission catalog and per-endpoint ACL that fails closed: an
  endpoint without a rule is denied, and a test fails if one is added without it.
- Per-person permission overrides, where a denial always wins.
- Personal access tokens: hashed at rest, shown once, scoped, expiring, revocable, and
  never able to exceed their owner.
- The API no longer falls back to a known signing key: without `SECRET_KEY` it generates
  an ephemeral one.

**Updates**
- Core upgrades from the console as a Kubernetes Job with verification, automatic
  rollback, drift detection and recorded provenance ([ADR-002](docs/adr/002-actualizacion-del-core.md)).
- The upstream repository is configurable (`core_upstream`, `KAANBAL_UPSTREAM`,
  `KAANBAL_REPO` for installs), and a cell whose installed commit is unknown to the
  upstream is offered the latest revision instead of a comparison that cannot run.

**Templates and tooling**
- Templates: Vue 3, React, FastAPI, MongoDB, PostgreSQL, n8n and EMQX, and a
  [template spec](SOFTWARE_FACTORY/docs/TEMPLATE_SPEC.md) for community templates.
- The FastAPI and Vue 3 templates ship a local-development contract: environment variables
  with the same names locally and in the cluster, a `docker-compose.yml` for the database,
  an idempotent first-run initializer, and an `AGENTS.md` for AI coding assistants.
- MCP server that lets an AI agent inspect apps, health, logs and variable *names* with a
  scoped, read-only token. It never returns secret values.
- Acuaponsito, an embeddable agent runtime, and a command-center UI prototype.

### Known limitations

See "Status and known limitations" in the [README](README.md#status-and-known-limitations).
