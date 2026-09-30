"""
Catálogo canónico de permisos y reglas ACL
==========================================

Un catálogo canónico: **una sola tabla de verdad**. Cada permiso se nombra
`modulo.recurso.accion`, y cada endpoint de la API declara qué permiso exige.

La política es *fail-closed*: un endpoint que no aparezca aquí queda bloqueado
para todo el mundo (salvo superadministradores). Es incómodo a propósito —
obliga a decidir quién puede hacer algo cuando se agrega, no después — y hay un
test que falla si un endpoint registrado no tiene regla.

Hasta ahora Kaanbal solo distinguía "admin" de "user" y no comprobaba nada:
quien iniciaba sesión podía borrar apps, leer credenciales y actualizar el core.
Con varias personas y varios clientes en la misma plataforma, eso no se sostiene.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Tuple

# Riesgo: qué tan caro es equivocarse. La consola lo usa para avisar al asignar.
RISK_NORMAL = "normal"
RISK_HIGH = "alto"
RISK_CRITICAL = "critico"


@dataclass(frozen=True)
class PermissionDef:
    key: str
    module: str
    resource: str
    action: str
    description: str
    risk: str = RISK_NORMAL


@dataclass(frozen=True)
class AclRule:
    method: str
    pattern: str
    permission: Optional[str]

    def matches(self, method: str, path: str) -> bool:
        if self.method != "*" and self.method != method.upper():
            return False
        return bool(re.fullmatch(self.pattern, path.rstrip("/") or "/"))


def permission(key: str, description: str, *, risk: str = RISK_NORMAL) -> PermissionDef:
    module, resource, action = key.split(".", 2)
    return PermissionDef(key, module, resource, action, description, risk)


def rule(method: str, pattern: str, permission_key: Optional[str]) -> AclRule:
    return AclRule(method, pattern, permission_key)


# ── Catálogo ─────────────────────────────────────────────────────────────
PERMISSIONS: Tuple[PermissionDef, ...] = (
    permission("autonomy.policy.manage", "Configurar usuarios, recursos y vigencia para autonomía.", risk=RISK_CRITICAL),
    permission("autonomy.tools.view", "Descubrir capacidades y consultar operaciones propias."),
    permission("autonomy.apps.execute", "Ejecutar comandos con acceso a datos y credenciales de una app.", risk=RISK_CRITICAL),
    permission("autonomy.host.execute", "Ejecutar comandos como root en nodos autorizados.", risk=RISK_CRITICAL),
    permission("autonomy.workspaces.manage", "Crear, editar y ejecutar contenedores de trabajo sin credenciales.", risk=RISK_HIGH),
    permission("autonomy.core.contribute", "Preparar cambios de Kaanbal para revisión del owner.", risk=RISK_HIGH),
    permission("autonomy.changes.propose", "Publicar cambios como rama y pull request.", risk=RISK_HIGH),
    permission("autonomy.changes.merge", "Integrar PRs de apps cuando GitHub permita el merge.", risk=RISK_CRITICAL),
    permission("security.tokens.elevated", "Emitir tokens críticos con contraseña y expiración.", risk=RISK_CRITICAL),
    # Aplicaciones
    permission("apps.apps.view", "Ver las aplicaciones y su estado."),
    permission("apps.apps.create", "Lanzar aplicaciones nuevas."),
    permission("apps.apps.delete", "Eliminar aplicaciones con su repo y sus secretos.", risk=RISK_CRITICAL),
    permission("apps.apps.deploy", "Sincronizar, escalar, encender y apagar ambientes."),
    permission("apps.apps.expose", "Cambiar exposición, dominio, homepage y grupo."),
    permission("apps.apps.diagnose", "Ver logs, pipeline y diagnóstico de una app."),
    permission("apps.maintenance.run", "Limpiezas masivas de secretos y dispositivos huérfanos.", risk=RISK_HIGH),
    permission("apps.variables.manage", "Agregar o cambiar variables de entorno de una app (sin ver sus valores).", risk=RISK_HIGH),
    # Stacks
    permission("stacks.catalog.view", "Ver el catálogo de stacks."),
    permission("stacks.stacks.launch", "Lanzar un stack completo."),
    # Dominios
    permission("domains.domains.view", "Ver los dominios registrados."),
    permission("domains.domains.manage", "Registrar, validar y reparar dominios.", risk=RISK_HIGH),
    permission("domains.domains.delete", "Eliminar un dominio de la plataforma.", risk=RISK_HIGH),
    # Clientes
    permission("clients.clients.view", "Ver los clientes."),
    permission("clients.clients.manage", "Crear y eliminar clientes.", risk=RISK_HIGH),
    # Plantillas
    permission("templates.catalog.view", "Ver el catálogo de plantillas."),
    permission("templates.custom.manage", "Crear, editar y validar plantillas propias."),
    permission("templates.custom.publish", "Aprobar y publicar plantillas para todos.", risk=RISK_HIGH),
    # Vínculos entre servicios
    permission("links.links.view", "Ver el mapa de vínculos entre apps."),
    permission("links.links.manage", "Crear y quitar vínculos entre apps."),
    # Sites (workers, gateways)
    permission("sites.sites.view", "Ver los sites de cómputo registrados."),
    permission("sites.sites.manage", "Registrar y eliminar sites, y fijar su estado deseado.", risk=RISK_HIGH),
    permission("sites.agent.report", "Reportar latido y leer estado deseado (lo usa el agente)."),
    # Core
    permission("core.updates.view", "Ver versión, actualizaciones disponibles y deriva."),
    permission("core.updates.apply", "Actualizar el core de la plataforma.", risk=RISK_CRITICAL),
    permission("core.vault.view", "Ver el estado de Vault."),
    permission("core.vault.reconcile", "Reconciliar los secretos de Vault.", risk=RISK_HIGH),
    # Sistema
    permission("system.health.view", "Ver salud, estadísticas y ambientes."),
    permission("system.cluster.view", "Ver los nodos del clúster."),
    permission("system.sync.run", "Forzar la sincronización con el clúster."),
    permission("system.credentials.view", "Ver qué credenciales están configuradas.", risk=RISK_HIGH),
    permission("system.credentials.manage", "Editar las credenciales de la plataforma.", risk=RISK_CRITICAL),
    permission("system.secrets.view", "Leer secretos de las apps en Vault.", risk=RISK_CRITICAL),
    permission("system.tokens.manage", "Administrar los tokens de despliegue.", risk=RISK_HIGH),
    # Bitácora
    permission("logs.records.view", "Consultar la bitácora de actividad."),
    permission("logs.records.export", "Exportar la bitácora."),
    permission("logs.records.purge", "Borrar la bitácora.", risk=RISK_CRITICAL),
    permission("logs.records.ingest", "Registrar eventos desde otros componentes."),
    # Ajustes
    permission("admin.settings.view", "Ver los ajustes de la plataforma."),
    permission("admin.settings.manage", "Editar los ajustes de la plataforma.", risk=RISK_HIGH),
    # Seguridad
    permission("security.users.view", "Ver las personas con acceso."),
    permission("security.users.manage", "Crear, editar y suspender cuentas.", risk=RISK_CRITICAL),
    permission("security.roles.view", "Ver los roles y sus permisos."),
    permission("security.roles.manage", "Crear y editar roles y su matriz de permisos.", risk=RISK_CRITICAL),
    permission("security.tokens.self", "Crear y revocar los tokens personales propios."),
    permission("security.tokens.admin", "Ver y revocar tokens personales de otras personas.", risk=RISK_CRITICAL),
    # Instalación
    permission("setup.install.run", "Ejecutar la instalación y la configuración inicial.", risk=RISK_CRITICAL),
)

PERMISSION_KEYS = frozenset(item.key for item in PERMISSIONS)
PERMISSIONS_BY_KEY: Dict[str, PermissionDef] = {item.key: item for item in PERMISSIONS}

# Fragmentos de ruta reutilizados. {app_name} y compañía llegan sin resolver al
# middleware, así que las reglas trabajan sobre el path crudo.
_SEG = r"[^/]+"
_ID = r"[0-9a-fA-F]{24}"
_V1 = "/api/v1"

# El MCP remoto vive fuera de /api/v1 para que su URL sea corta y estable.
MCP_PATH = "/mcp"


# ── Reglas ACL ───────────────────────────────────────────────────────────
# Las literales van ANTES que las paramétricas: gana la primera que coincide.
ACL_RULES: Tuple[AclRule, ...] = (
    rule("GET", rf"{_V1}/autonomy/capabilities", "autonomy.tools.view"),
    rule("GET", rf"{_V1}/autonomy/operations/{_SEG}", "autonomy.tools.view"),
    rule("GET", rf"{_V1}/autonomy/policy", "autonomy.policy.manage"),
    rule("PUT", rf"{_V1}/autonomy/policy", "autonomy.policy.manage"),
    rule("POST", rf"{_V1}/autonomy/apps/{_SEG}/execute", "autonomy.apps.execute"),
    rule("POST", rf"{_V1}/autonomy/nodes/{_SEG}/execute", "autonomy.host.execute"),
    rule("POST", rf"{_V1}/autonomy/workspaces", "autonomy.workspaces.manage"),
    rule("POST", rf"{_V1}/autonomy/core/workspaces", "autonomy.core.contribute"),
    rule("GET", rf"{_V1}/autonomy/workspaces/{_SEG}", "autonomy.workspaces.manage"),
    rule("DELETE", rf"{_V1}/autonomy/workspaces/{_SEG}", "autonomy.workspaces.manage"),
    rule("GET", rf"{_V1}/autonomy/workspaces/{_SEG}/(files|diff)", "autonomy.workspaces.manage"),
    rule("POST", rf"{_V1}/autonomy/workspaces/{_SEG}/(initialize|files|execute)", "autonomy.workspaces.manage"),
    rule("POST", rf"{_V1}/autonomy/workspaces/{_SEG}/pull-request", "autonomy.changes.propose"),
    rule("POST", rf"{_V1}/autonomy/workspaces/{_SEG}/merge", "autonomy.changes.merge"),
    rule("POST", rf"{_V1}/security/tokens/elevated", "security.tokens.elevated"),
    rule("GET", rf"{_V1}/security/tokens/{_SEG}/activity", "security.tokens.self"),
    # Autenticación (lo público está más abajo, en PUBLIC_PATHS)
    rule("GET", rf"{_V1}/auth/me", None),
    rule("POST", rf"{_V1}/auth/users", "security.users.manage"),

    # Aplicaciones
    rule("GET", rf"{_V1}/apps", "apps.apps.view"),
    rule("POST", rf"{_V1}/apps", "apps.apps.create"),
    rule("GET", rf"{_V1}/apps/argocd/all", "apps.apps.view"),
    rule("POST", rf"{_V1}/apps/maintenance/{_SEG}", "apps.maintenance.run"),
    rule("DELETE", rf"{_V1}/apps/{_SEG}", "apps.apps.delete"),
    rule("GET", rf"{_V1}/apps/{_SEG}/status/full", "apps.apps.view"),
    rule("GET", rf"{_V1}/apps/{_SEG}/argocd", "apps.apps.view"),
    rule("GET", rf"{_V1}/apps/{_SEG}/argocd/(logs|resources)", "apps.apps.diagnose"),
    rule("POST", rf"{_V1}/apps/{_SEG}/argocd/sync", "apps.apps.deploy"),
    rule("GET", rf"{_V1}/apps/{_SEG}/(pipeline|deploy-log)", "apps.apps.diagnose"),
    rule("GET", rf"{_V1}/apps/{_SEG}/(pipeline|deploy-log)/{_SEG}", "apps.apps.diagnose"),
    rule("POST", rf"{_V1}/apps/{_SEG}/analyze", "apps.apps.diagnose"),
    rule("GET", rf"{_V1}/apps/{_SEG}/repo-status", "apps.apps.diagnose"),
    rule("POST", rf"{_V1}/apps/{_SEG}/refresh-status", "apps.apps.view"),
    # Solo los nombres de las variables, nunca sus valores: por eso alcanza con
    # diagnose y no hace falta system.secrets.view.
    rule("GET", rf"{_V1}/apps/{_SEG}/env-vars", "apps.apps.diagnose"),
    rule("GET", rf"{_V1}/apps/{_SEG}/diagnosis", "apps.apps.diagnose"),
    rule("PUT", rf"{_V1}/apps/{_SEG}/variables/{_SEG}", "apps.variables.manage"),
    rule("POST", rf"{_V1}/apps/{_SEG}/bindings/repair", "apps.apps.deploy"),
    rule("GET", rf"{_V1}/apps/{_SEG}/environments/{_SEG}", "apps.apps.view"),
    rule("POST", rf"{_V1}/apps/{_SEG}/environments/{_SEG}", "apps.apps.deploy"),
    rule("DELETE", rf"{_V1}/apps/{_SEG}/environments/{_SEG}", "apps.apps.deploy"),
    rule("POST", rf"{_V1}/apps/{_SEG}/environments/{_SEG}/(scale|start|stop)", "apps.apps.deploy"),
    rule("GET", rf"{_V1}/apps/{_SEG}/exposure/status", "apps.apps.view"),
    rule("PATCH", rf"{_V1}/apps/{_SEG}/exposure", "apps.apps.expose"),
    rule("POST", rf"{_V1}/apps/{_SEG}/exposure", "apps.apps.expose"),
    # Un vínculo escribe variables en la app (con una base, sus credenciales),
    # pero nadie las ve: por eso alcanza con links.links.manage.
    rule("POST", rf"{_V1}/apps/{_SEG}/links", "links.links.manage"),
    rule("DELETE", rf"{_V1}/apps/{_SEG}/links/{_SEG}", "links.links.manage"),
    rule("GET", rf"{_V1}/apps/{_SEG}/(domain|homepage)", "apps.apps.view"),
    rule("POST", rf"{_V1}/apps/{_SEG}/(domain|homepage)", "apps.apps.expose"),
    rule("PATCH", rf"{_V1}/apps/{_SEG}/(group|display-name|tailscale-tags)", "apps.apps.expose"),
    rule("GET", rf"{_V1}/apps/{_SEG}/tailscale-tags", "apps.apps.view"),
    rule("GET", rf"{_V1}/apps/{_SEG}", "apps.apps.view"),

    # Stacks
    rule("GET", rf"{_V1}/stacks/catalog", "stacks.catalog.view"),
    rule("GET", rf"{_V1}/stacks/runs", "stacks.catalog.view"),
    rule("GET", rf"{_V1}/stacks/runs/{_SEG}", "stacks.catalog.view"),
    rule("POST", rf"{_V1}/stacks", "stacks.stacks.launch"),

    # Dominios
    rule("GET", rf"{_V1}/domains", "domains.domains.view"),
    rule("POST", rf"{_V1}/domains", "domains.domains.manage"),
    rule("POST", rf"{_V1}/domains/verify", "domains.domains.manage"),
    rule("GET", rf"{_V1}/domains/{_SEG}/apps", "domains.domains.view"),
    rule("POST", rf"{_V1}/domains/{_SEG}/(repair|reverify|set-default)", "domains.domains.manage"),
    rule("DELETE", rf"{_V1}/domains/{_SEG}", "domains.domains.delete"),

    # Clientes
    rule("GET", rf"{_V1}/clients", "clients.clients.view"),
    rule("POST", rf"{_V1}/clients", "clients.clients.manage"),
    rule("GET", rf"{_V1}/clients/{_SEG}(/apps)?", "clients.clients.view"),
    rule("DELETE", rf"{_V1}/clients/{_SEG}", "clients.clients.manage"),

    # Plantillas
    rule("GET", rf"{_V1}/templates", "templates.catalog.view"),
    rule("GET", rf"{_V1}/templates/(refresh|creation-modes)", "templates.catalog.view"),
    rule("GET", rf"{_V1}/templates/catalog/{_SEG}", "templates.catalog.view"),
    rule("GET", rf"{_V1}/templates/catalog/{_SEG}/{_SEG}", "templates.catalog.view"),
    rule("GET", rf"{_V1}/templates/categories/list", "templates.catalog.view"),
    rule("POST", rf"{_V1}/templates/analyze-pipeline", "templates.custom.manage"),
    rule("POST", rf"{_V1}/templates/generate-pipeline/{_SEG}", "templates.custom.manage"),
    rule("POST", rf"{_V1}/templates/custom", "templates.custom.manage"),
    rule("PUT", rf"{_V1}/templates/custom/{_SEG}", "templates.custom.manage"),
    rule("DELETE", rf"{_V1}/templates/custom/{_SEG}", "templates.custom.manage"),
    rule("GET", rf"{_V1}/templates/custom/{_SEG}/validation-status", "templates.custom.manage"),
    rule("POST", rf"{_V1}/templates/custom/{_SEG}/(validate|re-validate)", "templates.custom.manage"),
    rule("DELETE", rf"{_V1}/templates/custom/{_SEG}/test-apps", "templates.custom.manage"),
    rule("POST", rf"{_V1}/templates/custom/{_SEG}/(approve|publish)", "templates.custom.publish"),
    # El alta de stacks del catálogo antiguo; el lanzador vive en /stacks.
    rule("POST", rf"{_V1}/templates/catalog/stacks/{_SEG}/deploy", "stacks.stacks.launch"),
    rule("GET", rf"{_V1}/templates/{_SEG}", "templates.catalog.view"),
    rule("GET", rf"{_V1}/templates/{_SEG}/stats", "templates.catalog.view"),

    # Vínculos
    rule("GET", rf"{_V1}/links", "links.links.view"),
    rule("GET", rf"{_V1}/links/diagram", "links.links.view"),
    rule("GET", rf"{_V1}/links/env-literals/{_SEG}/{_SEG}", "links.links.view"),
    rule("GET", rf"{_V1}/links/manifests/{_SEG}", "links.links.view"),
    rule("POST", rf"{_V1}/links", "links.links.manage"),
    rule("DELETE", rf"{_V1}/links/{_SEG}", "links.links.manage"),

    # Sites
    rule("GET", rf"{_V1}/sites", "sites.sites.view"),
    rule("POST", rf"{_V1}/sites", "sites.sites.manage"),
    rule("GET", rf"{_V1}/sites/{_SEG}/(join|desired-state)", "sites.agent.report"),
    rule("POST", rf"{_V1}/sites/{_SEG}/heartbeat", "sites.agent.report"),
    rule("PUT", rf"{_V1}/sites/{_SEG}/desired-state", "sites.sites.manage"),
    rule("GET", rf"{_V1}/sites/{_SEG}", "sites.sites.view"),
    rule("DELETE", rf"{_V1}/sites/{_SEG}", "sites.sites.manage"),

    # Core
    rule("GET", rf"{_V1}/core/(version|updates|releases|drift|upgrade)", "core.updates.view"),
    rule("POST", rf"{_V1}/core/upgrade", "core.updates.apply"),
    rule("GET", rf"{_V1}/core/vault", "core.vault.view"),
    rule("POST", rf"{_V1}/core/vault/reconcile", "core.vault.reconcile"),

    # Sistema
    rule("GET", rf"{_V1}/system/(health|stats|environments|providers)", "system.health.view"),
    rule("GET", rf"{_V1}/system/cluster/nodes", "system.cluster.view"),
    rule("GET", rf"{_V1}/system/deploy-diagnostic", "apps.apps.diagnose"),
    rule("GET", rf"{_V1}/system/sync/status", "system.health.view"),
    rule("POST", rf"{_V1}/system/sync", "system.sync.run"),
    rule("POST", rf"{_V1}/system/argocd/refresh", "system.sync.run"),
    rule("GET", rf"{_V1}/system/credentials/status", "system.credentials.view"),
    rule("GET", rf"{_V1}/system/credentials", "system.credentials.view"),
    rule("GET", rf"{_V1}/system/credentials/raw", "system.credentials.manage"),
    rule("PUT", rf"{_V1}/system/credentials", "system.credentials.manage"),
    rule("POST", rf"{_V1}/system/credentials/import-terraform", "system.credentials.manage"),
    rule("POST", rf"{_V1}/system/import-from-cluster", "system.credentials.manage"),
    rule("POST", rf"{_V1}/system/providers/validate", "system.credentials.manage"),
    rule("GET", rf"{_V1}/system/vault/status", "core.vault.view"),
    rule("GET", rf"{_V1}/system/vault/secrets", "system.secrets.view"),
    rule("GET", rf"{_V1}/system/vault/secrets/{_SEG}/{_SEG}", "system.secrets.view"),
    rule("GET", rf"{_V1}/system/tokens", "system.tokens.manage"),
    rule("POST", rf"{_V1}/system/tokens", "system.tokens.manage"),
    rule("DELETE", rf"{_V1}/system/tokens/{_SEG}", "system.tokens.manage"),

    # Bitácora
    rule("GET", rf"{_V1}/logs", "logs.records.view"),
    rule("GET", rf"{_V1}/logs/stats", "logs.records.view"),
    rule("GET", rf"{_V1}/logs/stats/grouped", "logs.records.view"),
    rule("GET", rf"{_V1}/logs/export(\.csv)?", "logs.records.export"),
    rule("POST", rf"{_V1}/logs/ingest", "logs.records.ingest"),
    rule("DELETE", rf"{_V1}/logs", "logs.records.purge"),

    # Ajustes
    rule("GET", rf"{_V1}/admin/settings", "admin.settings.view"),
    rule("PUT", rf"{_V1}/admin/settings", "admin.settings.manage"),
    rule("GET", rf"{_V1}/config", "admin.settings.view"),
    rule("PUT", rf"{_V1}/config", "admin.settings.manage"),

    # Seguridad
    rule("GET", rf"{_V1}/security/permissions", "security.roles.view"),
    rule("GET", rf"{_V1}/security/roles", "security.roles.view"),
    rule("POST", rf"{_V1}/security/roles", "security.roles.manage"),
    rule("PATCH", rf"{_V1}/security/roles/{_SEG}", "security.roles.manage"),
    rule("DELETE", rf"{_V1}/security/roles/{_SEG}", "security.roles.manage"),
    rule("GET", rf"{_V1}/security/users", "security.users.view"),
    rule("POST", rf"{_V1}/security/users", "security.users.manage"),
    rule("PATCH", rf"{_V1}/security/users/{_SEG}", "security.users.manage"),
    rule("POST", rf"{_V1}/security/users/{_SEG}/password", "security.users.manage"),
    rule("GET", rf"{_V1}/security/me", None),
    rule("GET", rf"{_V1}/security/tokens", "security.tokens.self"),
    rule("POST", rf"{_V1}/security/tokens", "security.tokens.self"),
    rule("DELETE", rf"{_V1}/security/tokens/{_SEG}", "security.tokens.self"),
    rule("GET", rf"{_V1}/security/tokens/all", "security.tokens.admin"),

    # MCP remoto: basta con estar autenticado; cada herramienta exige su propio
    # permiso al pasar por la REST (y el router lo revisa antes, para explicarlo).
    rule("POST", MCP_PATH, None),
    rule("GET", MCP_PATH, None),
    rule("DELETE", MCP_PATH, None),

    # Instalación (ver BOOTSTRAP_PATHS: abiertos solo mientras no hay cuentas)
    rule("GET", rf"{_V1}/setup/status", None),
    rule("POST", rf"{_V1}/setup/validate/{_SEG}", "setup.install.run"),
    rule("POST", rf"{_V1}/setup/(init|install|tunnel|bootstrap-core-ci)", "setup.install.run"),
)


# Sin sesión: la autenticación misma, y los webhooks, que traen su propio secreto.
PUBLIC_PATHS: frozenset = frozenset({
    ("POST", f"{_V1}/auth/token"),
    ("POST", f"{_V1}/auth/signup"),
    ("GET", f"{_V1}/admin/settings-public"),
    ("POST", f"{_V1}/webhooks/deploy"),
    ("POST", f"{_V1}/webhooks/jira"),
})

PUBLIC_PREFIXES: Tuple[str, ...] = (
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static/",
)

# El SSE del deploy no puede mandar cabeceras (EventSource): el id de la app,
# que es un ObjectId, hace de credencial. Ya era así antes de este catálogo.
PUBLIC_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("GET", rf"{_V1}/apps/{_ID}/deploy/stream"),
)

# Instalación: abiertos SOLO mientras la plataforma no tiene ninguna cuenta.
# Es la ventana del instalador; en cuanto existe la primera persona, exigen
# setup.install.run como cualquier otra cosa.
BOOTSTRAP_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("POST", rf"{_V1}/setup/validate/{_SEG}"),
    ("POST", rf"{_V1}/setup/(init|install|tunnel|bootstrap-core-ci)"),
)


# ── Roles del sistema ────────────────────────────────────────────────────
VIEW_PERMISSIONS = tuple(item.key for item in PERMISSIONS if item.action == "view" and item.risk == RISK_NORMAL)

# Lo que necesita un agente (MCP) para entender un problema sin poder tocarlo.
AGENT_PERMISSIONS = (
    "autonomy.tools.view",
    "apps.apps.view", "apps.apps.diagnose", "stacks.catalog.view", "domains.domains.view",
    "clients.clients.view", "templates.catalog.view", "links.links.view", "sites.sites.view",
    "core.updates.view", "core.vault.view", "system.health.view", "system.cluster.view",
    "logs.records.view",
)

OPERATOR_PERMISSIONS = AGENT_PERMISSIONS + (
    "apps.apps.create", "apps.apps.deploy", "apps.apps.expose", "apps.variables.manage",
    "stacks.stacks.launch", "domains.domains.manage", "clients.clients.manage",
    "templates.custom.manage", "links.links.manage", "system.sync.run",
    "logs.records.export", "admin.settings.view", "security.tokens.self",
)

SYSTEM_ROLES: Tuple[dict, ...] = (
    {
        "slug": "agente-ingeniero", "name": "Agente ingeniero",
        "description": "Prepara cambios y PRs en los recursos autorizados por la política.",
        "superadmin": False, "system": True,
        "permissions": sorted(set(AGENT_PERMISSIONS) | {"autonomy.workspaces.manage", "autonomy.core.contribute", "autonomy.changes.propose", "security.tokens.self"}),
    },
    {
        "slug": "owner",
        "name": "Dueño",
        "description": "Control total de la plataforma, incluidas credenciales, actualizaciones y accesos.",
        "superadmin": True,
        "permissions": [],  # superadmin: no necesita lista
        "system": True,
    },
    {
        "slug": "operador",
        "name": "Operador",
        "description": "Lanza y opera apps, stacks y dominios. No toca credenciales, accesos ni el core.",
        "superadmin": False,
        "permissions": sorted(set(OPERATOR_PERMISSIONS)),
        "system": True,
    },
    {
        "slug": "lector",
        "name": "Lector",
        "description": "Solo mira: apps, dominios, stacks y bitácora.",
        "superadmin": False,
        "permissions": sorted(set(VIEW_PERMISSIONS) | {"security.tokens.self"}),
        "system": True,
    },
    {
        "slug": "agente",
        "name": "Agente",
        "description": "Solo lectura, pensado para un asistente conectado por API o MCP.",
        "superadmin": False,
        "permissions": sorted(set(AGENT_PERMISSIONS)),
        "system": True,
    },
)

# Cuentas que ya existían: 'admin' podía todo, 'user' operaba. Nadie pierde
# acceso al actualizar.
LEGACY_ROLE_MAP = {"admin": "owner", "user": "operador"}


# ── Consultas ────────────────────────────────────────────────────────────
def normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _matches_any(patterns: Iterable[Tuple[str, str]], method: str, path: str) -> bool:
    return any(
        (rule_method == "*" or rule_method == method.upper()) and re.fullmatch(pattern, path)
        for rule_method, pattern in patterns
    )


def is_public(method: str, path: str) -> bool:
    """Rutas que no exigen sesión."""
    path = normalize_path(path)
    if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return True
    if (method.upper(), path) in PUBLIC_PATHS:
        return True
    return _matches_any(PUBLIC_PATTERNS, method, path)


def is_bootstrap(method: str, path: str) -> bool:
    """Rutas del instalador, abiertas solo mientras no hay ninguna cuenta."""
    return _matches_any(BOOTSTRAP_PATTERNS, method, normalize_path(path))


def find_rule(method: str, path: str) -> Optional[AclRule]:
    path = normalize_path(path)
    for item in ACL_RULES:
        if item.matches(method, path):
            return item
    return None


def required_permission(method: str, path: str) -> Tuple[bool, Optional[str]]:
    """(hay_regla, permiso). Sin regla, el endpoint queda bloqueado."""
    found = find_rule(method, path)
    if found is None:
        return False, None
    return True, found.permission


def catalog_payload() -> List[dict]:
    """El catálogo tal como lo muestra la consola, con sus endpoints."""
    payload = []
    for item in PERMISSIONS:
        data = asdict(item)
        data["endpoints"] = [
            {"method": acl.method, "pattern": acl.pattern}
            for acl in ACL_RULES if acl.permission == item.key
        ]
        payload.append(data)
    return payload
