"""La página de conexión dice la URL real de esta célula, no una de ejemplo."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mcp import catalog  # noqa: E402
from app.services import mcp_connection, permissions  # noqa: E402

CONFIG = {"domain": "Example.com", "tailscale_dns_suffix": "tailnet-1234.ts.net"}


class ResolveUrlTests(unittest.TestCase):
    def test_the_ingress_wins_because_es_lo_que_responde_en_internet(self):
        with patch.object(mcp_connection, "ingress_host", return_value="kaanbal-api.example.com"):
            url, source, reach = mcp_connection.resolve_api_url(CONFIG, "https://consola.example.com")
        self.assertEqual(url, "https://kaanbal-api.example.com")
        self.assertEqual(source, "ingress")
        self.assertEqual(reach, "internet")

    def test_without_an_ingress_the_api_only_answers_inside_the_vpn(self):
        with patch.object(mcp_connection, "ingress_host", return_value=None):
            url, source, reach = mcp_connection.resolve_api_url(CONFIG, "https://consola.example.com")
        self.assertEqual(url, "https://kaanbal-api.tailnet-1234.ts.net")
        self.assertEqual(source, "tailnet")
        self.assertEqual(reach, "vpn")

    def test_with_only_the_domain_it_uses_the_convention(self):
        with patch.object(mcp_connection, "ingress_host", return_value=None):
            url, source, reach = mcp_connection.resolve_api_url({"domain": "Example.com"}, "")
        self.assertEqual(url, "https://kaanbal-api.example.com")
        self.assertEqual(source, "domain")
        self.assertEqual(reach, "unknown")

    def test_as_a_last_resort_the_address_the_request_came_from(self):
        with patch.object(mcp_connection, "ingress_host", return_value=None):
            url, source, _ = mcp_connection.resolve_api_url({}, "https://kaanbal-api.example.com/")
        self.assertEqual(url, "https://kaanbal-api.example.com")
        self.assertEqual(source, "request")

    def test_the_console_host_never_becomes_the_mcp_url_when_the_cluster_knows_better(self):
        # La consola proxea /api con su propio Host: si eso ganara, el agente
        # apuntaría a un host donde /mcp no existe.
        with patch.object(mcp_connection, "ingress_host", return_value="kaanbal-api.example.com"):
            info = mcp_connection.info(CONFIG, "https://kaanbal-console.example.com")
        self.assertNotIn("console", info["mcp_url"])


class ConnectionInfoTests(unittest.TestCase):
    def setUp(self):
        with patch.object(mcp_connection, "ingress_host", return_value="kaanbal-api.example.com"):
            self.info = mcp_connection.info(CONFIG, "")

    def test_the_mcp_url_is_the_api_plus_mcp(self):
        self.assertEqual(self.info["api_url"], "https://kaanbal-api.example.com")
        self.assertEqual(self.info["mcp_url"], "https://kaanbal-api.example.com/mcp")

    def test_it_also_points_at_the_api_documentation(self):
        self.assertEqual(self.info["docs"]["api"], "https://kaanbal-api.example.com/docs")
        self.assertEqual(self.info["docs"]["openapi"], "https://kaanbal-api.example.com/openapi.json")

    def test_it_explains_where_the_url_came_from_and_who_can_reach_it(self):
        self.assertTrue(self.info["source_label"])
        self.assertTrue(self.info["reach_label"])

    def test_every_client_snippet_carries_this_instance_url(self):
        ids = {client["id"] for client in self.info["clients"]}
        self.assertEqual(ids, {"claude-code", "http", "stdio"})
        for client in self.info["clients"]:
            self.assertIn("kaanbal-api.example.com", client["snippet"], client["id"])

    def test_no_snippet_ships_a_usable_token(self):
        for client in self.info["clients"]:
            self.assertIn("kbl_TU_TOKEN", client["snippet"])

    def test_the_stdio_bridge_gets_the_api_url_not_the_mcp_path(self):
        stdio = next(c for c in self.info["clients"] if c["id"] == "stdio")
        self.assertIn('"KAANBAL_URL": "https://kaanbal-api.example.com"', stdio["snippet"])

    def test_it_counts_the_tools_the_catalog_really_has(self):
        self.assertEqual(self.info["tools"]["total"], len(catalog.TOOLS))
        self.assertEqual(
            sum(self.info["tools"]["by_group"].values()), len(catalog.TOOLS)
        )
        self.assertGreater(self.info["tools"]["elevated"], 0)

    def test_it_says_where_the_token_is_created(self):
        self.assertEqual(self.info["auth"]["where"], "Acceso → Tokens")


class AccessRuleTests(unittest.TestCase):
    def test_the_endpoint_has_an_access_rule_and_is_not_public(self):
        # Vive bajo /api/v1 porque la consola solo proxea /api/ hacia la API.
        found = permissions.find_rule("GET", "/api/v1/mcp/connection")
        self.assertIsNotNone(found, "sin regla, la API bloquea el endpoint")
        self.assertIsNone(found.permission, "basta con estar autenticado")
        self.assertFalse(permissions.is_public("GET", "/api/v1/mcp/connection"))

    def test_it_does_not_collide_with_the_mcp_endpoint_itself(self):
        self.assertIsNone(permissions.find_rule("GET", "/mcp").permission)
        self.assertTrue(permissions.find_rule("POST", "/mcp"))

    def test_the_router_is_mounted_where_the_console_can_reach_it(self):
        # Sin el prefijo, la consola pediría /mcp/connection y nginx no lo proxea.
        main = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn('mcp.connection_router, prefix="/api/v1/mcp"', main)


class ConsoleTests(unittest.TestCase):
    """La consola tiene que poder abrir la página y pedir el endpoint."""

    def setUp(self):
        self.console = Path(__file__).resolve().parents[2] / "kaanbal-console" / "src"

    def test_the_view_exists_and_asks_for_the_connection_endpoint(self):
        view = (self.console / "views" / "Connect.vue").read_text(encoding="utf-8")
        self.assertIn("api.get('/mcp/connection')", view)

    def test_the_route_and_the_menu_point_at_it(self):
        router = (self.console / "router" / "index.js").read_text(encoding="utf-8")
        app = (self.console / "App.vue").read_text(encoding="utf-8")
        self.assertIn("path: '/connect'", router)
        self.assertIn("views/Connect.vue", router)
        self.assertIn('to="/connect"', app)


if __name__ == "__main__":
    unittest.main()
