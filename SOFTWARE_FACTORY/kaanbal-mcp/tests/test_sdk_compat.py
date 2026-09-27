"""El MCP de la plataforma, hablado por el cliente oficial del SDK.

La API implementa el protocolo sin el SDK (sus dependencias chocan con las de la
API), así que la prueba de que un cliente real lo entiende es esta: el cliente
oficial se conecta por HTTP al protocolo y al catálogo reales, cargados desde el
código de la API, e inicializa, lista y llama herramientas.
"""

import asyncio
import importlib.util
import socket
import threading
import time
import unittest
from pathlib import Path

REMOTE = Path(__file__).resolve().parents[2] / "kaanbal-api" / "app" / "mcp"
TOKEN = "Bearer kbl_prueba_x"

try:
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route
except ImportError:  # sin el SDK instalado (pip install -r requirements.txt)
    uvicorn = None


def load(name):
    spec = importlib.util.spec_from_file_location(f"kaanbal_remote_{name}", REMOTE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipIf(uvicorn is None or not REMOTE.exists(), "hace falta el SDK mcp y el código de la API al lado")
class OfficialClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        protocol, catalog = load("protocol"), load("catalog")

        async def run_tool(name, arguments):
            if name == "diagnose_app":
                return {"app": arguments["name"], "status": "ok", "summary": "Todo en orden"}
            raise protocol.ToolError(f"{name} no está disponible en esta prueba")

        async def endpoint(request):
            if request.method != "POST":
                return Response(status_code=405, headers={"Allow": "POST"})
            if request.headers.get("authorization") != TOKEN:
                return JSONResponse({"detail": "sin token"}, status_code=401)
            answer = await protocol.handle_body(
                await request.body(), server_info={"name": "kaanbal", "version": "prueba"},
                instructions="prueba", tools=catalog.definitions(), run_tool=run_tool,
            )
            return Response(status_code=202) if answer is None else JSONResponse(answer)

        app = Starlette(routes=[Route("/mcp", endpoint, methods=["GET", "POST", "DELETE"])])
        port = free_port()
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 10
        while not cls.server.started and time.time() < deadline:
            time.sleep(0.05)
        cls.url = f"http://127.0.0.1:{port}/mcp"
        cls.catalog = catalog

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)

    def scenario(self):
        async def run():
            async with create_mcp_http_client(headers={"Authorization": TOKEN}) as http:
                async with streamable_http_client(self.url, http_client=http) as (read, write):
                    async with ClientSession(read, write) as session:
                        init = await session.initialize()
                        listed = await session.list_tools()
                        ok = await session.call_tool("diagnose_app", {"name": "shop-api"})
                        refused = await session.call_tool("sync_app", {"name": "shop-api"})
                        return init, listed, ok, refused

        return asyncio.run(run())

    def test_the_official_client_initializes_lists_and_calls_tools(self):
        init, listed, ok, refused = self.scenario()
        self.assertEqual(init.server_info.name if hasattr(init, "server_info") else init.serverInfo.name, "kaanbal")
        names = sorted(tool.name for tool in listed.tools)
        self.assertEqual(names, sorted(t["name"] for t in self.catalog.TOOLS))
        self.assertFalse(ok.is_error if hasattr(ok, "is_error") else ok.isError)
        self.assertIn("Todo en orden", ok.content[0].text)
        self.assertTrue(refused.is_error if hasattr(refused, "is_error") else refused.isError)
        self.assertIn("no está disponible", refused.content[0].text)


if __name__ == "__main__":
    unittest.main()
