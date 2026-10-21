"""
Herramientas del MCP de Kaanbal
===============================

Siete grupos, en el orden en que se trabaja:

- **Entender**: identidad y capacidades del token, listar, detallar, diagnosticar,
  logs (de la app y del pipeline), consumo, URLs, versiones, bitácora y auditoría.
- **Crear**: una app desde una plantilla o un stack completo (base + API + frontend).
- **Conectar**: vincular apps, exposición, dominio y homepage.
- **Operar**: encender, apagar, escalar, reiniciar, sincronizar, reparar, variables,
  secretos pedidos a una persona, rollback y promoción entre ambientes.
- **Datos**: respaldos, restauración y consultas de solo lectura de las bases.
- **Administrar**: grupo y nombre visible, y borrar una app.
- **Guiar**: la guía de la plataforma y el contrato de cada app.

Lo que crea algo, cambia lo que se ve en internet o cambia qué versión corre va en
dos pasos (`plan_first`): sin plan_id devuelve el plan y no toca nada; con el
plan_id, lo aplica si el plan sigue siendo el mismo. Lo irreversible (restaurar
una base, borrar una app) además exige un token crítico (`elevated`) y la
aprobación de una persona en la consola (`approval`). Lo que no existe a
propósito: leer el valor de un secreto o tocar las credenciales y los accesos de
la plataforma.

Cada herramienta declara el permiso que exige la API; el cliente lo ve en la
descripción para poder explicar qué le falta al token cuando la API dice que no.
Este módulo no importa nada de `app.*`: el test de compatibilidad lo carga solo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
SAFE_ACTION = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
CONFIG_ACTION = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}
# Toca el mundo de afuera: repositorios en GitHub, DNS en Cloudflare, dispositivos en Tailscale.
PUBLIC_ACTION = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}
POWER_OFF = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}

GROUPS = ("entender", "crear", "conectar", "operar", "datos", "administrar", "guiar")
EXPOSURE_MODES = ["public", "tailscale", "lan", "internal", "off", "both"]
GUIDE_TOPICS = ["plataforma", "desarrollo-local", "desplegar", "conectar", "exponer", "mcp", "problemas"]

_APP = {"type": "string", "description": "Nombre interno de la app (el que aparece en list_apps)."}
_ENV = {"type": "string", "description": "Ambiente: prod, staging o dev. Por defecto prod.", "default": "prod"}
_ENVS = {"type": "array", "items": {"type": "string", "enum": ["dev", "staging", "prod"]},
         "description": "Ambientes. Prod siempre se incluye."}
_PLAN_ID = {
    "type": "string",
    "pattern": "^[0-9a-f]{16}$",
    "description": (
        "Omítelo para ver el plan sin aplicar nada. Para aplicar, repite la llamada con los mismos "
        "argumentos y el plan_id que devolvió el plan, después de que la persona lo apruebe."
    ),
}
_PLAN_NOTE = " Primero devuelve el plan y un plan_id sin tocar nada; se aplica repitiendo la llamada con ese plan_id."
_APPROVAL = {
    "type": "string",
    "pattern": "^[0-9a-f]{20}$",
    "description": (
        "Al aplicar desde un token, la API pide aprobación humana y devuelve un approval_id. Cuando una "
        "persona la apruebe en la consola (Acceso → Solicitudes), repite la llamada con plan_id y approval_id."
    ),
}
_APPROVAL_NOTE = " Exige token crítico y aprobación de una persona en la consola (approval_id)."
_ELEVATED_NOTE = " Exige un token crítico (confirmado con contraseña y con vencimiento)."


def _schema(properties: Dict[str, Any] = None, required: List[str] = ()) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = list(required)
    return schema


def _tool(name: str, title: str, group: str, permission: Optional[str], description: str,
          schema: Dict[str, Any], annotations: Dict[str, Any], *, plan_first: bool = False,
          elevated: bool = False, approval: bool = False) -> Dict[str, Any]:
    if plan_first:
        schema["properties"]["plan_id"] = _PLAN_ID
        description += _PLAN_NOTE
    if approval:
        schema["properties"]["approval_id"] = _APPROVAL
        description += _APPROVAL_NOTE
    elif elevated:
        description += _ELEVATED_NOTE
    return {
        "name": name, "title": title, "group": group, "permission": permission,
        "description": description, "inputSchema": schema, "annotations": annotations,
        "plan_first": plan_first, "elevated": elevated or approval, "approval": approval,
    }


TOOLS: List[Dict[str, Any]] = [
    # ── Entender ─────────────────────────────────────────────────────────
    _tool("whoami", "Quién soy en esta plataforma", "entender", None,
          "Instancia a la que apunta este conector (URL de la API, dominio principal, versión), la cuenta y el "
          "token (si es crítico y cuándo vence), y la política de autonomía que le aplica. Úsala primero cuando "
          "haya varios conectores de Kaanbal: dice exactamente a qué plataforma le vas a hablar.",
          _schema(), READ_ONLY),
    _tool("platform_capabilities", "Capacidades de este token", "entender", None,
          "TODAS las herramientas de este MCP (las de la plataforma y las de autonomía), cada una con: tipo "
          "(consulta, plan, acción, crítica), el permiso que exige, si este token puede usarla ahora y, si no, "
          "qué le falta (permiso, token crítico, aprobación humana o concesión de la política).",
          _schema({"only_available": {"type": "boolean", "default": False,
                                      "description": "Solo las que este token puede usar ahora."}}), READ_ONLY),
    _tool("list_apps", "Listar apps", "entender", "apps.apps.view",
          "Lista las aplicaciones con su dominio, URL pública y estado. Punto de partida para casi todo.",
          _schema({
              "domain": {"type": "string", "description": "Solo las apps de este dominio."},
              "group": {"type": "string", "description": "Solo las apps de este grupo."},
          }), READ_ONLY),
    _tool("get_app", "Detalle de una app", "entender", "apps.apps.view",
          "Detalle de una app: plantilla, ambientes, exposición, grupo, dominio, URLs y operaciones en curso.",
          _schema({"name": _APP}, ["name"]), READ_ONLY),
    _tool("app_health", "Salud de una app", "entender", "apps.apps.view",
          "Estado en ArgoCD por ambiente y resultado del último pipeline.",
          _schema({"name": _APP}, ["name"]), READ_ONLY),
    _tool("diagnose_app", "Diagnosticar una app", "entender", "apps.apps.diagnose",
          "Por qué una app no arranca o no responde, en lenguaje simple: variable que falta, base que "
          "rechaza las credenciales, versión nueva atascada, imagen que no baja, memoria, sonda de salud "
          "rechazada… Con la evidencia (sin secretos) y la acción que lo arregla. Empieza por aquí cuando algo falla.",
          _schema({"name": _APP, "env": _ENV}, ["name"]), READ_ONLY),
    _tool("app_logs", "Logs de una app", "entender", "apps.apps.diagnose",
          "Últimas líneas de log de los pods de una app en un ambiente, con credenciales y tokens enmascarados.",
          _schema({
              "name": _APP,
              "env": _ENV,
              "lines": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
          }, ["name"]), READ_ONLY),
    _tool("app_env_var_names", "Variables de una app (solo nombres)", "entender", "apps.apps.diagnose",
          "NOMBRES de las variables de entorno que recibe una app, nunca sus valores. Sirve para ver si la "
          "app pide una variable que nadie le inyecta.",
          _schema({"name": _APP, "env": _ENV}, ["name"]), READ_ONLY),
    _tool("deploy_status", "Estado de un despliegue", "entender", "apps.apps.view",
          "En qué va una app: alta en curso, cambio de exposición, mudanza de dominio u homepage, sus últimos "
          "pasos y la salud por ambiente. Úsalo para seguir lo que se lanzó hasta que termine.",
          _schema({"name": _APP}, ["name"]), READ_ONLY),
    _tool("stack_status", "Estado de un stack", "entender", "stacks.catalog.view",
          "En qué pieza va el lanzamiento de un stack y cómo terminó cada una.",
          _schema({"run_id": {"type": "string", "description": "El run_id que devolvió launch_stack."}}, ["run_id"]),
          READ_ONLY),
    _tool("list_domains", "Dominios", "entender", "domains.domains.view",
          "Dominios registrados, cuál es el de la instalación y cuántas apps usa cada uno.",
          _schema(), READ_ONLY),
    _tool("list_templates", "Plantillas", "entender", "templates.catalog.view",
          "Plantillas con las que se crea una app (frontend, API, base, n8n…), con su categoría y puerto.",
          _schema({"category": {"type": "string", "description": "frontend, backend, database, workflow, iot…"}}),
          READ_ONLY),
    _tool("list_stacks", "Stacks", "entender", "stacks.catalog.view",
          "Stacks que se lanzan de una vez (base + API + frontend ya conectados) y los últimos lanzamientos.",
          _schema(), READ_ONLY),
    _tool("platform_status", "Estado de la plataforma", "entender", "system.health.view",
          "Versión del core, si hay actualizaciones, salud del sistema y Vault.",
          _schema(), READ_ONLY),
    _tool("activity", "Bitácora", "entender", "logs.records.view",
          "Quién hizo qué y cuándo. Útil para saber qué cambió antes de que algo se rompiera.",
          _schema({
              "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
              "category": {"type": "string", "description": "Filtrar por categoría (app, deploy, auth, system…)."},
              "target": {"type": "string", "description": "Solo lo que tocó a esta app."},
          }), READ_ONLY),
    _tool("list_revisions", "Versiones de una app", "entender", "apps.apps.diagnose",
          "Las imágenes que corrieron en un ambiente (de la más nueva a la más vieja), cuál declara GitOps y cuál "
          "sirve hoy. Es la lista de versiones a las que rollback_app puede volver.",
          _schema({"name": _APP, "env": _ENV}, ["name"]), READ_ONLY),
    _tool("pipeline_logs", "Logs del pipeline", "entender", "apps.apps.diagnose",
          "Por qué falló el build o la publicación de la imagen: estado del último pipeline, los pasos que fallaron "
          "con el final de su log (credenciales enmascaradas) y los últimos pipelines. app_logs muestra los pods; "
          "esto muestra el CI.",
          _schema({"name": _APP, "history": {"type": "integer", "minimum": 0, "maximum": 10, "default": 5},
                   "max_chars": {"type": "integer", "minimum": 500, "maximum": 20000, "default": 6000}}, ["name"]),
          READ_ONLY),
    _tool("app_metrics", "Consumo de una app", "entender", "apps.apps.diagnose",
          "CPU y memoria de cada pod contra sus límites, reinicios y avisos (cerca de quedarse sin memoria, sin "
          "límite, CPU saturada).",
          _schema({"name": _APP, "env": _ENV}, ["name"]), READ_ONLY),
    _tool("check_urls", "¿Responde su URL?", "entender", "apps.apps.view",
          "Prueba desde la plataforma las URLs públicas de la app: código HTTP, tiempo de respuesta y certificado "
          "TLS (emisor y días para vencer). Solo las URLs de esa app.",
          _schema({"name": _APP}, ["name"]), READ_ONLY),
    _tool("wait_for_deploy", "Esperar un despliegue", "entender", "apps.apps.view",
          "Espera, del lado del servidor, a que termine lo que está en curso en una app (alta, exposición, dominio, "
          "homepage, rollback) y devuelve el estado final. Evita consultar deploy_status una y otra vez.",
          _schema({"name": _APP, "timeout_seconds": {"type": "integer", "minimum": 10, "maximum": 150, "default": 90}},
                  ["name"]), READ_ONLY),
    _tool("audit_platform", "Auditar la plataforma", "entender", "apps.apps.view",
          "Revisa todo el inventario y devuelve hallazgos con severidad y la herramienta que los arregla: piezas "
          "conectadas en grupos distintos, nombres con errores de escritura, bases sin uso o sin respaldo, apps en "
          "error o no sanas, apps sin grupo o sin nombre visible. No cambia nada.",
          _schema({"include_health": {"type": "boolean", "default": True},
                   "include_backups": {"type": "boolean", "default": True}}), READ_ONLY),
    _tool("list_secret_requests", "Secretos pedidos", "entender", "apps.apps.diagnose",
          "Las variables secretas que se pidieron para una app con request_secret y si una persona ya las capturó.",
          _schema({"name": _APP}, ["name"]), READ_ONLY),

    # ── Crear ────────────────────────────────────────────────────────────
    _tool("create_app", "Crear una app", "crear", "apps.apps.create",
          "ACCIÓN: crea una app desde una plantilla, con los mismos valores por defecto que el Wizard de la "
          "consola (repositorio con código y pipeline, o imagen oficial para bases). Opcional: conectada a una "
          "base (database=) o, si es un frontend, a su API pública (api=).",
          _schema({
              "name": {**_APP, "description": "Nombre de la nueva app: minúsculas, dígitos y guiones (3 a 63)."},
              "template": {"type": "string", "description": "Plantilla (list_templates)."},
              "environments": _ENVS,
              "exposure": {"type": "string", "enum": ["public", "tailscale", "internal", "lan"],
                           "description": "Por defecto, el de su categoría: web pública en prod y dev/staging por VPN; bases internas."},
              "domain": {"type": "string", "description": "Dominio (list_domains). Por defecto, el de la instalación."},
              "homepage": {"type": "boolean", "default": False, "description": "Ocupa la raíz del dominio."},
              "group": {"type": "string", "description": "Grupo para ordenarla junto a sus piezas."},
              "description": {"type": "string"},
              "database": {"type": "string", "description": "Base de datos (app existente) a la que se conecta."},
              "api": {"type": "string", "description": "Para un frontend: la API pública a la que apunta."},
          }, ["name", "template"]), PUBLIC_ACTION, plan_first=True),
    _tool("launch_stack", "Lanzar un stack", "crear", "stacks.stacks.launch",
          "ACCIÓN: lanza un sistema completo de una vez, en orden y ya cableado: base → API vinculada a la "
          "base → frontend que apunta a la API. Para una base de negocio con login/MFA, usa business-base-demo "
          "(PostgreSQL → Keycloak → Next.js con worker). El responsable de un grupo nuevo es el usuario del token MCP; "
          "se conserva el de un grupo existente. Con homepage=true la app principal ocupa la raíz del dominio.",
          _schema({
              "stack": {"type": "string", "description": "Id del stack (list_stacks)."},
              "base_name": {"type": "string", "description": "Nombre base: las piezas se llaman <base>, <base>-api, <base>-db. Por defecto, el del dominio."},
              "business_name": {"type": "string", "description": "Marca para business-base-demo (hasta 100 caracteres)."},
              "business_preset": {"type": "string", "enum": ["starter", "services", "barber"], "description": "starter: landing en /, administración en /admin y clientes en /client, sin catálogo/citas iniciales. services y barber incluyen agenda y servicios de ejemplo."},
              "domain": {"type": "string", "description": "Dominio (list_domains). Por defecto, el de la instalación."},
              "homepage": {"type": "boolean", "default": False},
              "environments": _ENVS,
              "group": {"type": "string"},
              "description": {"type": "string"},
          }, ["stack"]), PUBLIC_ACTION, plan_first=True),

    # ── Conectar ─────────────────────────────────────────────────────────
    _tool("link_apps", "Vincular dos apps", "conectar", "links.links.manage",
          "ACCIÓN: le da a una app las variables para hablar con otra, sin que nadie vea los valores. Con una "
          "base: sus credenciales y los nombres estándar (MONGO_URI, DATABASE_URL…). Con otra app: su dirección "
          "interna (<ALIAS>_URL). Cada ambiente con el mismo ambiente de la otra.",
          _schema({
              "name": {**_APP, "description": "La app que usa (la que recibe las variables)."},
              "to": {"type": "string", "description": "La base o el servicio al que se conecta."},
              "alias": {"type": "string", "description": "Prefijo de las variables. Por defecto, el nombre de la otra app en mayúsculas."},
              "environments": {"type": "array", "items": {"type": "string"}, "description": "Por defecto, los que comparten."},
          }, ["name", "to"]), CONFIG_ACTION, plan_first=True),
    _tool("unlink_apps", "Quitar un vínculo", "conectar", "links.links.manage",
          "ACCIÓN: quita de una app exactamente las variables que puso un vínculo hecho con link_apps.",
          _schema({"name": _APP, "to": {"type": "string", "description": "La otra app del vínculo."}}, ["name", "to"]),
          CONFIG_ACTION, plan_first=True),
    _tool("set_exposure", "Cambiar la exposición", "conectar", "apps.apps.expose",
          "ACCIÓN: quién llega a cada ambiente: public (internet), tailscale (VPN), lan, internal (solo el "
          "clúster), off (apagado) o both. Publica o retira DNS y Tailscale y prueba las URLs, en segundo plano.",
          _schema({
              "name": _APP,
              "per_env": {"type": "object", "additionalProperties": {"type": "string", "enum": EXPOSURE_MODES},
                          "description": "Modo por ambiente, por ejemplo {\"prod\": \"public\", \"dev\": \"tailscale\"}."},
          }, ["name", "per_env"]), PUBLIC_ACTION, plan_first=True),
    _tool("attach_domain", "Mudar a otro dominio", "conectar", "apps.apps.expose",
          "ACCIÓN: muda una app pública a otro dominio registrado. La URL nueva se prueba antes de retirar la "
          "vieja; corre en segundo plano.",
          _schema({"name": _APP, "domain": {"type": "string", "description": "Dominio destino (list_domains)."}},
                  ["name", "domain"]), PUBLIC_ACTION, plan_first=True),
    _tool("set_homepage", "Dar la raíz del dominio", "conectar", "apps.apps.expose",
          "ACCIÓN: convierte una app en el homepage de su dominio (https://dominio). Solo uno por dominio y su "
          "prod tiene que ser pública; corre en segundo plano.",
          _schema({"name": _APP}, ["name"]), PUBLIC_ACTION, plan_first=True),

    # ── Operar ───────────────────────────────────────────────────────────
    _tool("start_app", "Encender un ambiente", "operar", "apps.apps.deploy",
          "ACCIÓN: enciende un ambiente apagado con sus réplicas habituales (o las que indiques).",
          _schema({"name": _APP, "env": _ENV, "replicas": {"type": "integer", "minimum": 1, "maximum": 10}}, ["name"]),
          SAFE_ACTION),
    _tool("stop_app", "Apagar un ambiente", "operar", "apps.apps.deploy",
          "ACCIÓN: apaga un ambiente (0 réplicas): deja de responder hasta que lo enciendas. No borra datos.",
          _schema({"name": _APP, "env": _ENV}, ["name"]), POWER_OFF),
    _tool("scale_app", "Escalar un ambiente", "operar", "apps.apps.deploy",
          "ACCIÓN: fija cuántas copias corren en un ambiente (1 a 10). Para apagar usa stop_app.",
          _schema({"name": _APP, "env": _ENV, "replicas": {"type": "integer", "minimum": 1, "maximum": 10}},
                  ["name", "replicas"]), SAFE_ACTION),
    _tool("sync_app", "Sincronizar con ArgoCD", "operar", "apps.apps.deploy",
          "ACCIÓN: pide a ArgoCD que sincronice una app con su manifiesto. Seguro y repetible.",
          _schema({"name": _APP}, ["name"]), SAFE_ACTION),
    _tool("repair_db_bindings", "Republicar la conexión a la base", "operar", "apps.apps.deploy",
          "ACCIÓN: republica los nombres estándar de la base vinculada (MONGO_URI, DATABASE_URL…) en una app ya "
          "desplegada. Idempotente: si ya los tiene, no cambia nada.",
          _schema({"name": _APP}, ["name"]), SAFE_ACTION),
    _tool("set_app_variable", "Agregar una variable a una app", "operar", "apps.variables.manage",
          "ACCIÓN: agrega a una app una variable de entorno que le falta (por ejemplo ADMIN_PASSWORD). Con "
          "generate=true la plataforma crea un valor aleatorio seguro que nadie ve. No pisa una variable existente "
          "salvo overwrite=true, y nunca toca las que gestiona la plataforma (la conexión a la base). La app se "
          "reinicia sola con la variable nueva.",
          _schema({
              "name": _APP,
              "variable": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,63}$", "description": "Nombre de la variable, en mayúsculas."},
              "value": {"type": "string", "description": "Valor. Omítelo y usa generate=true para contraseñas o claves."},
              "generate": {"type": "boolean", "description": "Generar un valor aleatorio seguro.", "default": False},
              "overwrite": {"type": "boolean", "description": "Reemplazar el valor si la variable ya existe.", "default": False},
              "environments": {"type": "array", "items": {"type": "string"}, "description": "Por defecto, todos los de la app."},
          }, ["name", "variable"]), CONFIG_ACTION),
    _tool("restart_app", "Reiniciar un ambiente", "operar", "apps.apps.deploy",
          "ACCIÓN: reinicia los pods de un ambiente de a uno (como kubectl rollout restart), sin apagarlo y sin "
          "cambiar nada de GitOps. Útil tras rotar una credencial externa o cuando la app quedó en mal estado.",
          _schema({"name": _APP, "env": _ENV}, ["name"]), SAFE_ACTION),
    _tool("request_secret", "Pedir un secreto a una persona", "operar", "apps.secrets.request",
          "ACCIÓN: pide a una persona que capture el valor de una variable secreta que solo ella tiene (clave de un "
          "proveedor, token de un servicio externo). El agente nunca ve el valor: la persona lo pega en la consola, "
          "en Acceso → Solicitudes, y la app lo recibe. Para contraseñas internas usa set_app_variable con generate=true.",
          _schema({
              "name": _APP,
              "variable": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,63}$", "description": "Nombre de la variable."},
              "reason": {"type": "string", "description": "Para qué hace falta y de dónde se obtiene (lo lee la persona)."},
              "environments": {"type": "array", "items": {"type": "string"}, "description": "Por defecto, todos los de la app."},
          }, ["name", "variable", "reason"]), SAFE_ACTION),
    _tool("rollback_app", "Volver a una versión anterior", "operar", "apps.releases.manage",
          "ACCIÓN: vuelve un ambiente a una imagen que ya corrió (list_revisions), escribiendo su tag en GitOps; "
          "ArgoCD la despliega. No revierte cambios de esquema en la base. Dura hasta el próximo despliegue.",
          _schema({"name": _APP, "env": _ENV,
                   "tag": {"type": "string", "description": "Tag de la versión (list_revisions)."}}, ["name", "tag"]),
          CONFIG_ACTION, plan_first=True),
    _tool("promote_app", "Promover entre ambientes", "operar", "apps.releases.manage",
          "ACCIÓN: lleva a un ambiente la imagen exacta que corre en otro (por defecto staging → prod), escribiendo "
          "su tag en GitOps. No aplica a frontends: su build lleva las URLs de su ambiente (se promueven fusionando la rama).",
          _schema({"name": _APP,
                   "from_env": {"type": "string", "default": "staging"},
                   "to_env": {"type": "string", "default": "prod"}}, ["name"]),
          CONFIG_ACTION, plan_first=True),
    _tool("invoke_platform_tool", "Invocar una capacidad de la plataforma", "operar", "autonomy.tools.view",
          "Llama por nombre a una capacidad de autonomía que la plataforma publica (platform_capabilities las "
          "lista), aunque este cliente haya cargado la lista de herramientas antes de una actualización. Las "
          "irreversibles siguen pidiendo token crítico y aprobación humana.",
          _schema({"tool": {"type": "string", "description": "Nombre de la capacidad."},
                   "arguments": {"type": "object", "description": "Sus argumentos, como los describe platform_capabilities."}},
                  ["tool"]),
          {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}),

    # ── Datos ────────────────────────────────────────────────────────────
    _tool("list_backups", "Respaldos de una base", "datos", "data.backups.view",
          "Respaldos y restauraciones de una base (postgres o mongodb): cuándo, de qué ambiente, tamaño, huella y "
          "estado. Se guardan fuera del disco de la base (sobreviven si se borra) y se conservan los últimos 10.",
          _schema({"name": _APP}, ["name"]), READ_ONLY),
    _tool("backup_database", "Respaldar una base", "datos", "data.backups.create",
          "ACCIÓN: toma un respaldo completo de una base (pg_dump / mongodump) en segundo plano. No detiene la base. "
          "Hazlo antes de migraciones, restauraciones o cambios grandes.",
          _schema({"name": _APP, "env": _ENV}, ["name"]),
          {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}),
    _tool("restore_database", "Restaurar una base", "datos", "data.backups.restore",
          "ACCIÓN IRREVERSIBLE: reemplaza los datos de una base con un respaldo (list_backups). Antes toma un "
          "respaldo de seguridad del estado actual. Las apps conectadas pueden ver errores mientras corre.",
          _schema({"name": _APP, "env": _ENV,
                   "backup_id": {"type": "string", "description": "Id del respaldo (list_backups)."}},
                  ["name", "backup_id"]),
          POWER_OFF | {"idempotentHint": False}, plan_first=True, approval=True),
    _tool("query_database", "Consultar una base (solo lectura)", "datos", "data.records.read",
          "Lee datos de una base. Postgres: una sentencia SELECT/WITH/SHOW/EXPLAIN en transacción de solo lectura, "
          "con tope de filas y tiempo. MongoDB: operation collections, count o find con filter/projection/sort. "
          "Nunca escribe. Los datos pueden ser personales: pide solo lo necesario.",
          _schema({
              "name": _APP, "env": _ENV,
              "sql": {"type": "string", "description": "Postgres: la consulta."},
              "operation": {"type": "string", "enum": ["collections", "find", "count"], "description": "MongoDB."},
              "database": {"type": "string", "description": "MongoDB: base (por defecto, la de la app)."},
              "collection": {"type": "string", "description": "MongoDB: colección."},
              "filter": {"type": "object"}, "projection": {"type": "object"}, "sort": {"type": "object"},
              "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
          }, ["name"]), READ_ONLY, elevated=True),

    # ── Administrar ──────────────────────────────────────────────────────
    _tool("set_app_group", "Cambiar el grupo", "administrar", "apps.apps.expose",
          "ACCIÓN: mueve una app a un grupo (o lo quita con group vacío) para ordenarla junto a sus piezas en la "
          "consola. No cambia URLs, repositorio ni despliegue.",
          _schema({"name": _APP, "group": {"type": "string", "description": "Grupo; vacío para quitarlo."}},
                  ["name", "group"]), SAFE_ACTION),
    _tool("set_display_name", "Cambiar el nombre visible", "administrar", "apps.apps.expose",
          "ACCIÓN: el nombre con el que se ve la app en la consola. El nombre interno no cambia: es su identidad en "
          "el repositorio, el clúster, el DNS y Vault.",
          _schema({"name": _APP, "display_name": {"type": "string", "description": "Hasta 60 caracteres; vacío lo quita."}},
                  ["name", "display_name"]), SAFE_ACTION),
    _tool("delete_app", "Eliminar una app", "administrar", "apps.apps.delete",
          "ACCIÓN IRREVERSIBLE: elimina una app con su repositorio, secretos, overlays y despliegues. El plan muestra "
          "quién depende de ella; una base exige un respaldo de las últimas 24 h (o without_backup=true, que queda "
          "en el plan).",
          _schema({"name": _APP,
                   "without_backup": {"type": "boolean", "default": False,
                                      "description": "Borrar una base sin respaldo reciente. Queda escrito en el plan."}},
                  ["name"]),
          POWER_OFF | {"idempotentHint": False}, plan_first=True, approval=True),

    # ── Guiar ────────────────────────────────────────────────────────────
    _tool("platform_guide", "Guía de Kaanbal", "guiar", None,
          "Cómo funciona la plataforma y cómo trabajar bien sobre ella: organización, desarrollo local, "
          "despliegue, conexiones, exposición, este MCP y qué hacer cuando algo falla.",
          _schema({"topic": {"type": "string", "enum": GUIDE_TOPICS, "default": "plataforma"}}), READ_ONLY),
    _tool("app_contract", "Contrato de una app", "guiar", "apps.apps.view",
          "Lo que una app necesita para vivir en Kaanbal y cómo trabajar en ella: plantilla, puerto, ruta de "
          "salud, variables que recibe (solo nombres), vínculos, URLs, repositorio y qué rama despliega a cada "
          "ambiente, con los pasos de desarrollo local.",
          _schema({"name": _APP, "env": _ENV}, ["name"]), READ_ONLY),
]

TOOLS_BY_NAME: Dict[str, Dict[str, Any]] = {tool["name"]: tool for tool in TOOLS}


def definitions() -> List[Dict[str, Any]]:
    """Lo que ve el cliente en tools/list."""
    return [
        {
            "name": tool["name"],
            "title": tool["title"],
            "description": (
                f"{tool['description']} (permiso del token: {tool['permission']})" if tool["permission"]
                else f"{tool['description']} (cualquier token)"
            ),
            "inputSchema": tool["inputSchema"],
            "annotations": {"title": tool["title"], **tool["annotations"]},
        }
        for tool in TOOLS
    ]
