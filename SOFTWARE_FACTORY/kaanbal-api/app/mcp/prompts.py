"""
Flujos guiados (prompts del MCP)
================================

Recetas que la persona elige por nombre —en Claude Code aparecen como comandos
`/`— y que le dicen al agente, paso a paso, cómo hacer bien lo más común: lanzar
un sitio, crear una pieza, diagnosticar, preparar el desarrollo local, publicar
en un dominio y conectar dos apps. Siempre con el plan a la vista antes de aplicar.

Este módulo no importa nada de `app.*`: el test de compatibilidad lo carga solo.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping


def _arg(name: str, description: str, required: bool = False) -> Dict[str, Any]:
    return {"name": name, "description": description, "required": required}


def _opt(value: Any, text: str) -> str:
    return text.format(value) if value not in (None, "") else ""


def _yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"si", "sí", "yes", "true", "1", "y"}


PLAN_RULE = (
    "Regla de oro: toda herramienta que crea o cambia algo visible primero devuelve un plan y un "
    "plan_id sin aplicar nada. Muéstrame ese plan en palabras simples y aplica (repitiendo la "
    "llamada con el plan_id) solo si digo que sí."
)


def _launch_site(args: Mapping[str, Any]) -> str:
    homepage = _yes(args.get("homepage"))
    return "\n".join([
        "Quiero lanzar un sitio completo en Kaanbal (base de datos + API + frontend)"
        + _opt(args.get("nombre"), " llamado '{}'")
        + _opt(args.get("dominio"), " en el dominio {}")
        + (", ocupando la raíz del dominio (homepage)" if homepage else "") + ".",
        "",
        "1. Usa list_stacks y list_domains para elegir stack y dominio; si hay más de una opción razonable, pregúntame.",
        "2. Llama a launch_stack sin plan_id y muéstrame el plan: nombres de cada pieza, URLs, cómo se conectan y si alguna choca.",
        "3. Si lo apruebo, repite launch_stack con el plan_id.",
        "4. Sigue el avance con stack_status(run_id) cada minuto y avísame cuando cada pieza esté lista o si falla (en ese caso, diagnose_app de esa pieza).",
        "5. Al terminar, dame las URLs y usa app_contract de la API y del frontend para explicarme cómo trabajar en local.",
        "",
        PLAN_RULE,
    ])


def _new_app(args: Mapping[str, Any]) -> str:
    return "\n".join([
        "Quiero crear una app nueva en Kaanbal"
        + _opt(args.get("plantilla"), " con la plantilla '{}'")
        + _opt(args.get("nombre"), " llamada '{}'")
        + _opt(args.get("conectar_a"), ", conectada a '{}'") + ".",
        "",
        "1. Si falta la plantilla, usa list_templates y ayúdame a elegir según lo que quiero construir.",
        "2. Si va conectada a algo: una base se pasa como database=, y la API de un frontend como api= (tiene que ser pública).",
        "3. Llama a create_app sin plan_id y muéstrame el plan: nombre final, URLs, repositorio y base conectada.",
        "4. Si lo apruebo, repite create_app con el plan_id y sigue el avance con deploy_status hasta que esté lista.",
        "5. Termina con app_contract: qué variables recibe, cómo correrla en local y cómo desplegar cambios.",
        "",
        PLAN_RULE,
    ])


def _diagnose(args: Mapping[str, Any]) -> str:
    env = args.get("ambiente") or "prod"
    return "\n".join([
        f"La app '{args.get('app')}' tiene un problema en {env}. Averigua qué pasa y propón cómo arreglarlo.",
        "",
        f"1. Empieza por diagnose_app(name='{args.get('app')}', env='{env}') y explícame el hallazgo en lenguaje simple.",
        "2. Si hace falta más contexto, usa app_logs, app_health y activity (qué cambió justo antes).",
        "3. Propón la acción concreta que sugiere el diagnóstico. No la ejecutes sin que yo diga que sí.",
        "4. Después de aplicarla, vuelve a correr diagnose_app para confirmar que quedó bien.",
        "",
        "Nunca vas a ver valores de secretos; si el arreglo necesita uno, dime qué variable falta y usa "
        "set_app_variable con generate=true cuando sea una contraseña o clave.",
    ])


def _local_dev(args: Mapping[str, Any]) -> str:
    return "\n".join([
        f"Quiero trabajar en local en la app '{args.get('app')}' con la misma configuración que en Kaanbal.",
        "",
        f"1. Usa app_contract(name='{args.get('app')}') para saber su plantilla, puerto, ruta de salud, variables que recibe y ramas.",
        "2. Lee platform_guide(topic='desarrollo-local') y arma los pasos exactos para esta app: clonar, .env con los mismos "
        "nombres (valores locales, nunca los de producción), base local con docker compose y cómo correrla.",
        "3. Si la app usa base de datos, explícame cómo manejar cambios de esquema sin romper producción (expandir y después contraer).",
        "4. Termina con cómo publicar mis cambios: qué rama va a qué ambiente y cómo seguir el despliegue.",
    ])


def _publish(args: Mapping[str, Any]) -> str:
    homepage = _yes(args.get("homepage"))
    return "\n".join([
        f"Quiero publicar la app '{args.get('app')}'"
        + _opt(args.get("dominio"), " en el dominio {}")
        + (" como homepage (en la raíz del dominio)" if homepage else "") + ".",
        "",
        f"1. Mira cómo está hoy con get_app(name='{args.get('app')}') y list_domains.",
        "2. Si su prod no es pública, set_exposure con per_env={\"prod\": \"public\"} (muéstrame el plan).",
        "3. Si hay que cambiar de dominio, attach_domain (muéstrame qué URL aparece y cuál deja de responder).",
        "4. Si va en la raíz, set_homepage (muéstrame el plan)." if homepage else
        "4. No toques el homepage del dominio.",
        "5. Cada cambio corre en segundo plano: sigue deploy_status hasta que la URL responda y dámela.",
        "",
        PLAN_RULE,
    ])


def _connect(args: Mapping[str, Any]) -> str:
    return "\n".join([
        f"Quiero que la app '{args.get('app')}' pueda hablar con '{args.get('con')}'.",
        "",
        "1. Con get_app de las dos, dime qué tipo de conexión es: una base (recibe credenciales y MONGO_URI/DATABASE_URL…) "
        "o un servicio interno (recibe <ALIAS>_URL). Si la primera es un frontend, explícame por qué no se conecta así y qué hacer.",
        f"2. Llama a link_apps(name='{args.get('app')}', to='{args.get('con')}') sin plan_id y muéstrame qué variables "
        "recibe en cada ambiente (solo nombres).",
        "3. Si lo apruebo, repite con el plan_id. La app se reinicia sola; confirma con deploy_status y app_env_var_names.",
        "4. Dime qué nombres de variable tiene que usar el código.",
        "",
        PLAN_RULE,
    ])


PROMPTS: List[Dict[str, Any]] = [
    {
        "name": "lanzar-sitio",
        "title": "Lanzar un sitio completo",
        "description": "Base + API + frontend ya conectados, con o sin homepage, con el plan a la vista antes de crear nada.",
        "arguments": [
            _arg("nombre", "Nombre base del sitio (las piezas se llaman <nombre>, <nombre>-api, <nombre>-db)."),
            _arg("dominio", "Dominio donde vive (por defecto, el de la plataforma)."),
            _arg("homepage", "sí/no: el frontend ocupa la raíz del dominio."),
        ],
        "render": _launch_site,
    },
    {
        "name": "nueva-app",
        "title": "Crear una app",
        "description": "Una pieza suelta (API, frontend, base, n8n…) desde una plantilla, opcionalmente conectada.",
        "arguments": [
            _arg("plantilla", "Plantilla (list_templates las muestra)."),
            _arg("nombre", "Nombre de la app."),
            _arg("conectar_a", "Base de datos o API a la que se conecta."),
        ],
        "render": _new_app,
    },
    {
        "name": "diagnosticar",
        "title": "Diagnosticar una app",
        "description": "Qué le pasa a una app que no arranca o no responde, y la acción que lo arregla.",
        "arguments": [
            _arg("app", "Nombre de la app.", required=True),
            _arg("ambiente", "prod, staging o dev (por defecto prod)."),
        ],
        "render": _diagnose,
    },
    {
        "name": "desarrollo-local",
        "title": "Preparar el desarrollo local",
        "description": "Cómo correr una app en tu máquina con la misma configuración que en Kaanbal, y cómo desplegar.",
        "arguments": [_arg("app", "Nombre de la app.", required=True)],
        "render": _local_dev,
    },
    {
        "name": "publicar",
        "title": "Publicar en un dominio",
        "description": "Hacer pública una app, moverla de dominio o darle la raíz (homepage).",
        "arguments": [
            _arg("app", "Nombre de la app.", required=True),
            _arg("dominio", "Dominio destino."),
            _arg("homepage", "sí/no: ocupa la raíz del dominio."),
        ],
        "render": _publish,
    },
    {
        "name": "conectar-apps",
        "title": "Conectar dos apps",
        "description": "Que una app hable con su base o con otro servicio, sin ver ni copiar credenciales.",
        "arguments": [
            _arg("app", "La app que se conecta (la que usa).", required=True),
            _arg("con", "La base o el servicio al que se conecta.", required=True),
        ],
        "render": _connect,
    },
]

PROMPTS_BY_NAME: Dict[str, Dict[str, Any]] = {item["name"]: item for item in PROMPTS}


def definitions() -> List[Dict[str, Any]]:
    """Lo que ve el cliente en prompts/list."""
    return [{key: item[key] for key in ("name", "title", "description", "arguments")} for item in PROMPTS]


def get(name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
    """prompts/get. KeyError si no existe; ValueError si falta un argumento obligatorio."""
    item = PROMPTS_BY_NAME[name]
    arguments = dict(arguments or {})
    missing = [arg["name"] for arg in item["arguments"] if arg["required"] and not str(arguments.get(arg["name"]) or "").strip()]
    if missing:
        raise ValueError(f"El flujo {name} necesita: {', '.join(missing)}")
    render: Callable[[Mapping[str, Any]], str] = item["render"]
    return {
        "description": item["description"],
        "messages": [{"role": "user", "content": {"type": "text", "text": render(arguments)}}],
    }
