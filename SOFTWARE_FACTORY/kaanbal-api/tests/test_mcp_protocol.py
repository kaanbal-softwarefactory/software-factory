"""Protocolo MCP (JSON-RPC 2.0 sobre HTTP, sin estado): lo que un cliente espera de /mcp.

La compatibilidad con el cliente oficial del SDK se prueba en kaanbal-mcp; aquí,
cada respuesta del protocolo, sin red ni base.
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.mcp import protocol  # noqa: E402

TOOLS = [
    {"name": "get_app", "description": "d", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "boom", "description": "d", "inputSchema": {"type": "object", "properties": {}}},
]


async def runner(name, arguments):
    if name == "boom":
        raise RuntimeError("detalle interno que no debe salir")
    if arguments.get("name") == "nope":
        raise protocol.ToolError("No existe nope.")
    return {"name": arguments["name"], "ok": True}


def handle(message):
    return asyncio.run(protocol.handle_message(
        message, server_info={"name": "kaanbal", "version": "t"}, instructions="i", tools=TOOLS, run_tool=runner,
    ))


def handle_body(raw):
    return asyncio.run(protocol.handle_body(
        raw, server_info={"name": "kaanbal", "version": "t"}, instructions="i", tools=TOOLS, run_tool=runner,
    ))


def request(method, params=None, message_id=1):
    message = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class LifecycleTests(unittest.TestCase):
    def test_initialize_echoes_a_version_we_speak(self):
        result = handle(request("initialize", {"protocolVersion": "2025-06-18"}))["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["serverInfo"]["name"], "kaanbal")
        self.assertTrue(result["instructions"])

    def test_an_unknown_version_gets_the_newest_we_know(self):
        result = handle(request("initialize", {"protocolVersion": "2099-01-01"}))["result"]
        self.assertEqual(result["protocolVersion"], protocol.LATEST_VERSION)

    def test_notifications_and_client_responses_get_no_answer(self):
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(handle({"jsonrpc": "2.0", "id": 7, "result": {}}))

    def test_ping(self):
        self.assertEqual(handle(request("ping"))["result"], {})

    def test_unknown_method(self):
        self.assertEqual(handle(request("resources/list"))["error"]["code"], protocol.METHOD_NOT_FOUND)

    def test_not_json_rpc(self):
        self.assertEqual(handle({"id": 1, "method": "ping"})["error"]["code"], protocol.INVALID_REQUEST)
        self.assertEqual(handle("ping")["error"]["code"], protocol.INVALID_REQUEST)

    def test_supported_version_header(self):
        self.assertTrue(protocol.is_supported_version(None))
        self.assertTrue(protocol.is_supported_version("2025-03-26"))
        self.assertFalse(protocol.is_supported_version("1999-01-01"))


class ToolTests(unittest.TestCase):
    def test_list(self):
        names = [t["name"] for t in handle(request("tools/list"))["result"]["tools"]]
        self.assertEqual(names, ["get_app", "boom"])

    def test_call_returns_the_data_as_text(self):
        result = handle(request("tools/call", {"name": "get_app", "arguments": {"name": "shop"}}))["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), {"name": "shop", "ok": True})

    def test_a_tool_error_is_for_the_model_to_read(self):
        result = handle(request("tools/call", {"name": "get_app", "arguments": {"name": "nope"}}))["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["content"][0]["text"], "No existe nope.")

    def test_an_unexpected_failure_does_not_leak_internals(self):
        result = handle(request("tools/call", {"name": "boom", "arguments": {}}))["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("detalle interno", result["content"][0]["text"])

    def test_unknown_tool_and_missing_arguments_are_protocol_errors(self):
        self.assertEqual(handle(request("tools/call", {"name": "rm_rf"}))["error"]["code"], protocol.INVALID_PARAMS)
        missing = handle(request("tools/call", {"name": "get_app", "arguments": {}}))
        self.assertEqual(missing["error"]["code"], protocol.INVALID_PARAMS)
        self.assertIn("name", missing["error"]["message"])

    def test_arguments_must_be_an_object(self):
        answer = handle(request("tools/call", {"name": "get_app", "arguments": ["shop"]}))
        self.assertEqual(answer["error"]["code"], protocol.INVALID_PARAMS)


class BodyTests(unittest.TestCase):
    def test_invalid_json(self):
        self.assertEqual(handle_body(b"{nope")["error"]["code"], protocol.PARSE_ERROR)

    def test_a_batch_answers_only_the_requests(self):
        body = json.dumps([request("ping", message_id=1), {"jsonrpc": "2.0", "method": "notifications/initialized"}])
        answer = handle_body(body.encode())
        self.assertEqual([a["id"] for a in answer], [1])

    def test_a_batch_of_notifications_has_no_answer(self):
        body = json.dumps([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertIsNone(handle_body(body.encode()))

    def test_an_empty_batch(self):
        self.assertEqual(handle_body(b"[]")["error"]["code"], protocol.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
