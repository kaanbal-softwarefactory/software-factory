"""
Herramientas del MCP de Kaanbal
===============================

Cinco grupos, en el orden en que se trabaja:

- **Entender**: listar, detallar, diagnosticar, logs, bitácora, estado de un despliegue.
- **Crear**: una app desde una plantilla o un stack completo (base + API + frontend).
- **Conectar**: vincular apps, exposición, dominio y homepage.
- **Operar**: encender, apagar, escalar, sincronizar, reparar y agregar variables.
- **Guiar**: la guía de la plataforma y el contrato de cada app.

Lo que crea algo o cambia lo que se ve en internet va en dos pasos (`plan_first`):
sin plan_id devuelve el plan y no toca nada; con el plan_id, lo aplica si el plan
sigue siendo el mismo. Lo que no existe a propósito: borrar apps o dominios, leer
el valor de un secreto, tocar las credenciales de la plataforma y actualizar el
core. Eso se hace desde la consola, con una persona mirando.

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

GROUPS = ("entender", "crear", "conectar", "operar", "guiar")
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


def _schema(properties: Dict[str, Any] = None, required: List[str] = ()) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = list(required)
    return schema


def _tool(name: str, title: str, group: str, permission: Optional[str], description: str,
          schema: Dict[str, Any], annotations: Dict[str, Any], *, plan_first: bool = False) -> Dict[str, Any]:
    if plan_first:
        schema["properties"]["plan_id"] = _PLAN_ID
        description += _PLAN_NOTE
    return {
        "name": name, "title": title, "group": group, "permission": permission,
        "description": description, "inputSchema": schema, "annotations": annotations,
        "plan_first": plan_first,
    }


TOOLS: List[Dict[str, Any]] = [
    # ── Entender ─────────────────────────────────────────────────────────
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
          "base → frontend que apunta a la API. Con homepage=true el frontend ocupa la raíz del dominio.",
          _schema({
              "stack": {"type": "string", "description": "Id del stack (list_stacks)."},
              "base_name": {"type": "string", "description": "Nombre base: las piezas se llaman <base>, <base>-api, <base>-db. Por defecto, el del dominio."},
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
