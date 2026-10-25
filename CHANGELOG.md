# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added
- **Agent Hub**: a per-group coordination table for Codex, Claude Code, Cursor and ChatGPT.
  Agents join with a specialty, keep a heartbeat, claim tasks atomically (blocked tasks say
  what is missing and who holds it), message each other, leave a trace (project → day →
  agent) and hand off with a summary. A project drive keeps the human source (`fuente/`,
  phase ZIPs unpacked safely, nested ZIPs one level) and the agents' `live/` folder.
  `kaanbal.hub.json` imports a phase plan as tasks with dependencies. A secretary digest
  works without AI and, with the configured provider, adds risks and proposed tasks.
  19 `hub_*` MCP tools (images returned inline), console views `/hub` and `/hub/:group`,
  new `hub.*` permissions and a ChatGPT prompt to produce phases in this format.
- Business Base launch-time module selection in console/MCP: contact/inbox, catalog,
  appointments (including catalog), or core only. Availability is persisted per
  organization and enforced in the API. Additive migration preserves old copies.
  Team appointments include a weekly calendar in the business timezone with bounded
  date queries and tenant/role isolation. Local copies preserve module selection.
- Business Base Starter preset: a public landing, separate administration and
  customer dashboards, membership-based server entry, personal requests and shared
  inbox. Launch from console/MCP on a root domain or subdomain; plans show page
  URLs and generated repositories preserve the preset for local development.
  Existing presets and data remain intact with an additive experience migration.
- Business Base MCP contract with declared connections and environment names per
  process, local development instructions and explicit captured-email limits.
  Stack plans expose the authenticated creator's group ownership and invalidate
  if that owner changes before application. Existing group ownership is preserved.
  Includes a proposed per-client SMTP profile design, not yet implemented.
- Business Base demo candidate in Stacks: separate PostgreSQL/identity/app,
  source copies pinned to the installed revision, Vault-backed secrets outside
  Git, initialization, worker, captured email and readiness verification.
- **Business Base prototype**: an independently runnable Next.js/PostgreSQL application
  with Keycloak OIDC, verified MFA for administration, organizations, resource permissions,
  landing, catalog, contact/inbox, customer portal, reservations, invitations, audit and mail
  outbox. Local named copies have separate data and identity; a source generator preserves
  the reference. It remains a prototype until the template acceptance and GitOps integration
  are validated. Includes database and real-browser acceptance tests.
- **Systems in the console**: existing application groups gain a display name, accountable
  platform user and lifecycle label. Filter by responsible person and inspect member apps.
  Ownership does not change access control. Newly launched stacks default to their creator
  without overwriting existing group ownership.
- **"Conectar" in the console**: the MCP URL of *this* installation, where to get a token and the
  snippet ready to paste for Claude Code, Cursor, Codex or a stdio client, plus links to the API
  documentation (Swagger UI, ReDoc, `openapi.json`) that FastAPI generates from the running
  version. Nobody has to guess the domain or copy a URL from an example any more.
- `GET /api/v1/mcp/connection` resolves that URL from the cluster itself and says where it came
  from: the `kaanbal-api` Ingress first (what actually answers on the internet), then the MagicDNS
  name when the API is not published, then the `kaanbal-api.<domain>` convention, and only as a
  last resort the address the request arrived at — the console proxies `/api/` under its own Host,
  so the request alone would point agents at a host where `/mcp` does not exist. The answer also
  says whether that URL is reachable from the internet or only through the VPN, so the page does
  not promise a URL nobody can open. It returns no secrets.

## [1.3.0] - 2026-10-19

### Added
- **Human approval for the irreversible.** From a token, running a command in an app or
  as root on a node, merging a PR, upgrading the core, restoring a database and deleting
  an app no longer run on request: the API answers 428 with an `approval_id`, a person
  approves or rejects it in **Access → Requests** (password confirmation), and the agent
  repeats the exact same call with it. Each approval matches a SHA-256 fingerprint of the
  action and its arguments, is single-use and expires in 30 minutes. Console sessions are
  the person and skip the queue; the owner can turn it off (`approval_required: false`).
- **The MCP now administers the platform** (49 platform tools plus 19 autonomy capabilities):
  - *Identity*: `whoami` says which instance a connector talks to (API URL, domains,
    version), with which account and token, and whether it is critical.
    `platform_capabilities` now covers every tool, platform and autonomy alike, with its
    kind (read, plan, action, critical) and what this token is missing.
    `invoke_platform_tool` (announced before, never implemented) now exists.
  - *Understand*: `pipeline_logs` (failed CI steps with the end of their log, masked),
    `app_metrics` (CPU and memory against limits), `list_revisions`, `check_urls`
    (status, latency and TLS expiry of the app's own URLs), `wait_for_deploy`,
    `audit_platform` (split groups, name typos, unused or unbacked databases, unhealthy
    apps), `list_secret_requests`.
  - *Operate*: `restart_app` (rollout restart, GitOps untouched), `rollback_app` and
    `promote_app` (write the image tag in infra-gitops, with a plan), `request_secret`
    (a person pastes a credential in the console; the agent never sees it).
  - *Data*: `list_backups`, `backup_database`, `restore_database` (plan, critical token,
    approval, safety backup first) and `query_database` (read-only SQL with a row limit,
    or MongoDB find/count) for `postgres` and `mongodb` apps. Backups live in the
    platform's GridFS, outside the app's disk; the last 10 per app and environment are kept.
  - *Administer*: `set_app_group`, `set_display_name` and `delete_app` (plan showing who
    depends on it; a database needs a backup from the last 24 h; critical token and approval).
  - `GET /autonomy/access` and the `autonomy_access` / `get_approval` capabilities: an
    agent knows its grants before trying.
  - Workspaces start from the branch that deploys the environment (`develop`, `staging`,
    `main`) or `base_branch`, and their PR targets it.
  - Inventory as MCP resources (`kaanbal://inventario/apps`, `.../apps/{name}`,
    `.../apps/{name}/contrato`) and four new guided flows: `auditar-plataforma`,
    `volver-version`, `cuidar-datos`, `cambiar-codigo`.
- `diagnose_app` explains restarts of a healthy app (OOMKilled, SIGTERM, SIGKILL or
  "Kubernetes did not record the cause") and returns recent Warning events.
- New permissions: `apps.releases.manage`, `apps.secrets.request`, `data.backups.view`,
  `data.backups.create`, `data.backups.restore` (critical), `data.records.read` (critical).
  The operator role gets releases and backups; the agent role gets `data.backups.view`
  and `apps.secrets.request`.
- Laravel 13 backend template with PHP 8.4, Composer, React 19 + Inertia 3,
  PostgreSQL bindings, MVVM-ready layers, health checks and generated tests.
- **Next.js full-stack template** (Next.js 16, App Router, React 19, TypeScript): pages and
  API in one app, so a demo no longer needs a separate frontend, API and database wired by
  hand. It reads a linked database from the conventional names Kaanbal publishes
  (`MONGODB_URI`, `POSTGRES_URL`, `DATABASE_URL`, `PGHOST`…) without configuration, creates
  and seeds its `notes` collection or table on first run, and with no database at all it
  still starts, keeps the data in memory and says so on the page. The image is Next's
  `standalone` output running as a non-root user on port 3000, with `/api/health` as the
  smoke test — it answers without touching the database, so a database outage does not
  restart the pod.
- Two stacks that launch it with its database in one go: `nextjs-mongo` and
  `nextjs-postgres`. The application takes the public URL and can be the domain's homepage;
  the database stays inside the cluster.
- PHP/Composer runtime detection in generated CI workflows and Laravel-compatible
  `APP_KEY` generation for Vault-backed application secrets.
- Optional MCP autonomy under ACL, exact resource grants and time limits: app/node
  repair commands, source workspaces, GitHub PRs and core upgrade tools.
- Critical (full control) tokens require a password confirmation and a risk
  acknowledgement. A dated one lasts at most 24 hours; the owner may also create one that
  never expires, by choosing "No expira nunca" and accepting an explicit warning (for a
  trusted agent or automation; it works until revoked). Tokens support scheduled
  activation, visible revocation and an activity history. Normal tokens may have no
  expiry with an explicit warning.
- The built-in HTTP MCP discovers new governed tools as the platform evolves;
  existing MCP tools and guided flows remain available.

### Changed
- `platform_upgrade` is a critical capability, and `POST /core/upgrade` and
  `DELETE /apps/{id}` require a critical token and approval when called with a token.
- `kaanbal-api`'s ClusterRole may `patch` deployments and statefulsets (only used for the
  restart annotation).

### Upgrade notes
- Autonomy stays disabled by default. Kubernetes permissions for app exec, privileged node
  operations and database backups/queries (`pods/exec` in the app namespaces) require an
  owner-reviewed GitOps change before activation; without them those tools say what is
  missing and everything else works.
- Existing critical tokens keep the permissions they captured: issue a new one to get
  the new `data.*` and `apps.releases.manage` permissions.

### Fixed
- The console sidebar navigation now scrolls independently when its links exceed the
  viewport height, keeping the brand and status/logout controls visible.
- The dashboard offered a Next.js tile pointing at a template id that did not exist
  (`next-app`), so the wizard opened on nothing. It now opens the Next.js template, and a
  test keeps the dashboard's showcase and the catalog from drifting apart again. The
  template list also shows the Next.js and Laravel icons instead of the generic box.

## [1.2.1] - 2026-09-27

### Security
- The API wrote its MongoDB connection string, password included, to its log on every
  start, and the log endpoint returned logs as they were: anyone allowed to diagnose apps
  (the operator and agent roles) could read the platform database's root password from
  the logs of `kaanbal-api`. The startup message now hides the password, and
  `GET /apps/{app}/argocd/logs` masks credentials and tokens in every line. **Rotate the
  datastore root password** of installations where other people could read those logs.

### Changed
- `link_apps` refuses to give a frontend a database's credentials, as `create_app`
  already did: link the database to the API and the frontend to the API's public URL.

## [1.2.0] - 2026-09-27

### Added
- **The MCP now builds, connects and operates, not only diagnoses** (28 tools, up from 13):
  - *Create*: `create_app` (an app from a template, with the Wizard's defaults, optionally
    bound to a database or pointed at its API) and `launch_stack` (database + API + frontend
    in one go, with or without the domain's homepage); `list_templates`.
  - *Connect*: `link_apps` / `unlink_apps`, `set_exposure`, `attach_domain`, `set_homepage`.
  - *Operate*: `start_app`, `stop_app`, `scale_app`; `deploy_status` and `stack_status` to
    follow long operations; `app_logs` now reads the requested environment.
  - *Guide*: `platform_guide` (how the platform works, local development, deploying,
    connecting, exposing, troubleshooting) and `app_contract` (port, health path, variable
    names, links, URLs, branches and local steps of one app).
- **Plan before apply.** Everything that creates something or changes what is visible on
  the internet answers first with a plan (names, URLs, variables that arrive) and a
  `plan_id`, and applies nothing. The same call with the `plan_id` applies it, and only if
  the plan is still identical: the REST API recomputes it and refuses a stale one. The
  REST endpoints accept `dry_run=true` and `plan_id` (`POST /apps`, `POST /stacks`,
  `POST /apps/{app}/domain`, `POST /apps/{app}/homepage` and the new ones below); the
  console keeps applying directly, as before.
- **Links that actually connect.** `POST /api/v1/apps/{app}/links` gives an app what it
  needs to reach another one through the same GitOps path as database bindings: a
  database's credentials plus the engine's standard names (`MONGO_URI`, `DATABASE_URL`…),
  or another app's in-cluster address (`<ALIAS>_HOST/_PORT/_URL`). Values are never
  returned, existing names are never overwritten, and `DELETE /apps/{app}/links/{other}`
  removes exactly what the link added.
- `POST /api/v1/apps/{app}/exposure` changes exposure in the background (state in
  `exposure_change`), because publishing DNS and probing a URL can outlast the 100 s
  Cloudflare allows a request. An app runs one long operation at a time.
- The MCP serves **guided flows** as prompts (`lanzar-sitio`, `nueva-app`, `diagnosticar`,
  `desarrollo-local`, `publicar`, `conectar-apps`; slash commands in Claude Code) and the
  platform guide as resources (`kaanbal://guia/<topic>`).

### Fixed
- Creating an app bound to a database failed at "Resolving database bindings" with
  `'str' object has no attribute 'canonical_aliases'` (since 1.0.0): every app created in
  the Wizard with a database, and the API of every stack. A local variable shadowed the
  module that publishes the engine's standard names. Apps that failed this way stay in
  `error` with nothing deployed; after upgrading, remove the failed record and create
  them again (the Git repository, if it was already created, is reused).
- Launching a stack failed with an internal error right after recording the launch as
  running, which also blocked new launches until it went stale.
- An error while cloning infra-gitops could echo the Git URL, token included, in the
  response of `set_app_variable` and `repair_db_bindings` (and in the API log).
- `app_logs` ignored the environment and the number of lines it was asked for, and
  returned log lines without masking credentials.

## [1.1.1] - 2026-09-27

### Fixed
- A core upgrade run from the node could publish files from the previous version.
  When part of the node's checkout belonged to another user (for example after a
  `sudo git pull`), git could not rewrite those files and the upgrade went on with the
  checkout half updated. The script now returns the checkout to its owner before
  updating it and stops, without deploying, if the checkout does not match the requested
  revision exactly. Upgrades started from the console were not affected.

## [1.1.0] - 2026-09-27

### Added
- **Remote MCP server.** The API serves the MCP protocol itself at `POST /mcp`
  (Streamable HTTP, stateless). Claude Code, Cursor, Codex and any client with HTTP
  support connect with the API URL and a personal access token: nothing to install.
  Every tool goes back through the REST API with the caller's own credential, so
  permissions, token scopes and the activity log are exactly those of the REST API.
  Compatibility is tested with the official MCP SDK client.
- **Diagnosis in plain language**: `GET /api/v1/apps/{app}/diagnosis`, the MCP tool
  `diagnose_app` and a "Diagnose" panel in the console. Deterministic rules explain why
  an app does not start or respond — a variable the code reads but nobody injects, a
  database that rejects the credentials (including a volume left over from a previous
  database with the same name), a new version stuck while the previous one keeps
  serving, images that cannot be pulled, missing dependencies, out of memory, a wrong
  port, rejected health checks — with masked evidence and an action from a safe list.
- **App variables**: `PUT /api/v1/apps/{app}/variables/{name}`, the MCP tool
  `set_app_variable` and one click from the diagnosis. Adds a missing environment
  variable through the same GitOps path as database bindings, or generates a secure
  value. Values are never returned (a freshly generated one is shown once, in the
  console), existing variables are not overwritten without asking, and the variables the
  platform manages are protected. New permission `apps.variables.manage`, included in
  the operator role.

### Changed
- The local `kaanbal-mcp` package is now a minimal stdio bridge to `/mcp` for clients
  that only speak stdio. The tools live in the platform.

### Fixed
- The account created by the installer was migrated to the `operador` role instead of
  `owner` when roles were introduced, losing `core.updates.apply` among others.
- Two core upgrades running at the same time (the console button and the node script)
  could promote an image that neither had finished building. Upgrades now take a lock,
  and the console refuses to start one while another is running, even from the node.

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
