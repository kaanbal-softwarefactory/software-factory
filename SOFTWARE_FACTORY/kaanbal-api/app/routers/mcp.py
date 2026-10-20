"""
MCP remoto: POST /mcp
=====================

Un agente (Claude, Cursor, Codex…) se conecta con solo la URL de la API y un
token personal, sin instalar nada:

    https://<api-de-tu-célula>/mcp      Authorization: Bearer kbl_...

El middleware de acceso ya autenticó la petición; cada herramienta vuelve a
pasar por la REST con la misma credencial, y el permiso se revisa también aquí
para poder explicarle al agente qué le falta al token antes de intentarlo.
Además de las herramientas, expone flujos guiados (prompts) y la guía de la
plataforma como recursos.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.db import get_db
from app.mcp import catalog, guide, inventory, prompts, protocol, tools
from app.routers import autonomy
from app.mcp.loopback import LoopbackClient
from app.services import mcp_connection as connection
from app.version import VERSION

router = APIRouter()

SERVER_INFO = {"name": "kaanbal", "title": "Kaanbal", "version": VERSION}

INSTRUCTIONS = (
    "Kaanbal es la plataforma donde viven estas aplicaciones: lanza, conecta, publica y opera apps y stacks "
    "(base + API + frontend). Empieza con whoami (a qué instancia le hablas, si hay varios conectores) y "
    "platform_capabilities (qué puede este token y qué le falta). Si no conoces la plataforma, lee platform_guide. "
    "Cuando algo falla, empieza por diagnose_app; para el CI, pipeline_logs; para el consumo, app_metrics. "
    "Lo que crea algo, cambia lo que se ve en internet o cambia qué versión corre (create_app, launch_stack, "
    "link_apps, unlink_apps, set_exposure, attach_domain, set_homepage, rollback_app, promote_app) va en dos pasos: "
    "sin plan_id devuelve el plan y no toca nada; muéstraselo a la persona y aplica con el plan_id solo si lo "
    "aprueba. Lo irreversible (restore_database, delete_app, ejecutar comandos, merge, actualizar el core) exige "
    "además un token crítico y la aprobación de una persona: la API responde con un approval_id, la persona lo "
    "aprueba en la consola (Acceso → Solicitudes) y repites la llamada con él. Las demás acciones actúan directo: "
    "confirma antes. Lo largo corre en segundo plano: espera con wait_for_deploy o stack_status. Nunca vas a ver "
    "el valor de un secreto: si hace falta uno que solo tiene una persona, pídelo con request_secret."
)


def _public_base(request: Request) -> str:
    """La URL con la que llegó el agente, para que whoami diga a qué instancia le habla.

    Detrás del túnel o del ingress, el host real viene en X-Forwarded-*.
    """
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host.split(',')[0].strip()}"


@router.post("/mcp")
async def mcp_messages(request: Request):
    version = request.headers.get("mcp-protocol-version")
    if not protocol.is_supported_version(version):
        return JSONResponse(
            protocol.error_response(None, protocol.INVALID_REQUEST, f"Versión de protocolo no soportada: {version}"),
            status_code=400,
        )

    principal = request.state.principal
    client = LoopbackClient(request.app, request.headers.get("authorization", ""))
    discovered = (await autonomy.capabilities(request))["tools"] if principal.can("autonomy.tools.view") else []
    dynamic = {spec["name"]: spec for spec in discovered}
    definitions = catalog.definitions() + [
        {"name": spec["name"], "title": spec["name"],
         "description": f"{spec['description']} (permiso: {spec['permission']})",
         "inputSchema": spec["input_schema"],
         "annotations": {"title": spec["name"], "readOnlyHint": spec["method"] == "GET",
                          "destructiveHint": spec["method"] != "GET", "openWorldHint": True}}
        for spec in discovered if spec["name"] not in catalog.TOOLS_BY_NAME
    ]

    context = {"api_url": _public_base(request), "discovered": dynamic}

    async def run_tool(name, arguments):
        if name in dynamic and name not in catalog.TOOLS_BY_NAME:
            return await tools.call_discovered_tool(client, dynamic[name], arguments)
        tool = catalog.TOOLS_BY_NAME[name]
        permission = tool["permission"]
        if permission and not principal.can(permission):
            who = f"El token '{principal.token_name}'" if principal.via_token else "Tu cuenta"
            raise protocol.ToolError(
                f"{who} no incluye el permiso '{permission}', que necesita {name}. "
                "Pídeselo a quien administra la plataforma o crea un token con ese alcance en Acceso → Tokens."
            )
        if tool.get("elevated") and principal.via_token and not principal.elevated:
            raise protocol.ToolError(
                f"{name} exige un token crítico (Acceso → Tokens → Control total, confirmado con contraseña y "
                "con vencimiento). Este token es de uso diario."
            )
        return await tools.call_tool(client, name, arguments, context)

    async def read_resource(uri):
        if uri.startswith(inventory.PREFIX):
            return await inventory.read(client, uri)
        return guide.read_resource(uri)

    answer = await protocol.handle_body(
        await request.body(),
        server_info=SERVER_INFO,
        instructions=INSTRUCTIONS,
        tools=definitions,
        run_tool=run_tool,
        prompts=prompts.definitions(),
        get_prompt=prompts.get,
        resources=guide.resources() + inventory.resources(),
        resource_templates=inventory.templates(),
        read_resource=read_resource,
    )
    if answer is None:
        return Response(status_code=202)
    return JSONResponse(answer)


# Sin sesiones ni canal SSE (el servidor nunca le escribe al cliente por su cuenta):
# el estándar pide responder 405 a GET y DELETE en ese caso.
@router.get("/mcp")
async def mcp_no_stream():
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
async def mcp_no_session():
    return Response(status_code=405, headers={"Allow": "POST"})


# ── Cómo conectarse ──────────────────────────────────────────────────────
# Vive bajo /api/v1 (no bajo /mcp) porque quien lo lee es la consola, y la
# consola solo proxea /api/ hacia la API. Un agente ya conectado no lo
# necesita: whoami le dice a qué instancia le está hablando.
connection_router = APIRouter()


@connection_router.get("/connection")
async def mcp_connection(request: Request):
    """La URL real de esta célula, dónde sacar el token y qué pegar en cada cliente."""
    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}
    return connection.info(config, _public_base(request))
