"""El puente stdio: reenvía cada mensaje tal cual y traduce los errores de HTTP a JSON-RPC."""

import json
import os
import sys
import unittest

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kaanbal_mcp import bridge  # noqa: E402


def make_bridge(handler):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(record))
    return bridge.Bridge("https://api.example.com/mcp", "kbl_a_b", http=http), seen


def rpc(method, message_id=1, **params):
    return json.dumps({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})


class ForwardTests(unittest.TestCase):
    def test_a_request_goes_out_as_is_with_the_token(self):
        b, seen = make_bridge(lambda r: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}}))
        answer = b.forward(rpc("ping"))
        self.assertEqual(json.loads(answer)["result"], {})
        self.assertEqual(seen[0].headers["authorization"], "Bearer kbl_a_b")
        self.assertEqual(json.loads(seen[0].content)["method"], "ping")

    def test_after_initialize_every_request_declares_the_version(self):
        def handler(request):
            body = json.loads(request.content)
            result = {"protocolVersion": "2025-06-18"} if body["method"] == "initialize" else {}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        b, seen = make_bridge(handler)
        b.forward(rpc("initialize", protocolVersion="2025-06-18"))
        b.forward(rpc("tools/list", message_id=2))
        self.assertNotIn("mcp-protocol-version", seen[0].headers)
        self.assertEqual(seen[1].headers["mcp-protocol-version"], "2025-06-18")

    def test_a_notification_writes_nothing(self):
        b, _ = make_bridge(lambda r: httpx.Response(202))
        self.assertIsNone(b.forward(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})))

    def test_a_revoked_token_becomes_a_readable_error(self):
        b, _ = make_bridge(lambda r: httpx.Response(401, json={"detail": "no"}))
        error = json.loads(b.forward(rpc("tools/list", message_id=5)))
        self.assertEqual(error["id"], 5)
        self.assertIn("token", error["error"]["message"])

    def test_the_platform_being_down_is_an_error_not_a_crash(self):
        def refuse(request):
            raise httpx.ConnectError("sin red")

        b, _ = make_bridge(refuse)
        self.assertIn("No se pudo conectar", json.loads(b.forward(rpc("ping")))["error"]["message"])

    def test_garbage_in_is_a_parse_error(self):
        b, _ = make_bridge(lambda r: httpx.Response(200))
        self.assertEqual(json.loads(b.forward("{no"))["error"]["code"], -32700)


class ConfigTests(unittest.TestCase):
    def test_the_endpoint_comes_from_the_api_url(self):
        self.assertEqual(bridge.endpoint("https://api.example.com/"), "https://api.example.com/mcp")
        self.assertEqual(bridge.endpoint("https://api.example.com/mcp"), "https://api.example.com/mcp")

    def test_it_refuses_to_start_without_credentials(self):
        for env in ({}, {"KAANBAL_URL": "https://x"}):
            with self.assertRaises(bridge.BridgeConfigError):
                bridge.config_from_env(env)
        self.assertEqual(bridge.config_from_env({"KAANBAL_URL": "https://x", "KAANBAL_TOKEN": "kbl_a_b"}),
                         ("https://x/mcp", "kbl_a_b"))


if __name__ == "__main__":
    unittest.main()
