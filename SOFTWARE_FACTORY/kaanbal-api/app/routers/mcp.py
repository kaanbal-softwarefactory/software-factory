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

from app.mcp import catalog, guide, prompts, protocol, tools
from app.mcp.loopback import LoopbackClient
from app.version import VERSION

router = APIRouter()

SERVER_INFO = {"name": "kaanbal", "title": "Kaanbal", "version": VERSION}

INSTRUCTIONS = (
    "Kaanbal es la plataforma donde viven estas aplicaciones: lanza, conecta, publica y opera apps y stacks "
    "(base + API + frontend). Si no conoces la plataforma, lee platform_guide. Cuando algo falla, empieza por "
    "diagnose_app: dice en lenguaje simple qué pasa, con la evidencia y la acción que lo arregla. "
    "Todo lo que crea algo o cambia lo que se ve en internet (create_app, launch_stack, link_apps, unlink_apps, "
    "set_exposure, attach_domain, set_homepage) va en dos pasos: sin plan_id devuelve el plan y no toca nada; "
    "muéstraselo a la persona y aplica repitiendo la llamada con el plan_id solo si lo aprueba. Las demás acciones "
    "(start_app, stop_app, scale_app, sync_app, repair_db_bindings, set_app_variable) actúan directo: confirma "
    "antes. Lo largo corre en segundo plano: síguelo con deploy_status o stack_status. Nunca vas a poder leer el "
    "valor de un secreto, ni borrar apps, ni actualizar el core: eso se hace en la consola."
)


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

    async def run_tool(name, arguments):
        permission = catalog.TOOLS_BY_NAME[name]["permission"]
        if permission and not principal.can(permission):
            who = f"El token '{principal.token_name}'" if principal.via_token else "Tu cuenta"
            raise protocol.ToolError(
                f"{who} no incluye el permiso '{permission}', que necesita {name}. "
                "Pídeselo a quien administra la plataforma o crea un token con ese alcance en Acceso → Tokens."
            )
        return await tools.call_tool(client, name, arguments)

    answer = await protocol.handle_body(
        await request.body(),
        server_info=SERVER_INFO,
        instructions=INSTRUCTIONS,
        tools=catalog.definitions(),
        run_tool=run_tool,
        prompts=prompts.definitions(),
        get_prompt=prompts.get,
        resources=guide.resources(),
        read_resource=guide.read_resource,
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
