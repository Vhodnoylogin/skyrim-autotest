import io
import json
from pathlib import Path
import tempfile
import unittest

from skyrim_autotest.command_bus import CommandBus
from skyrim_autotest.command_bus_mcp import MAX_LINE_BYTES, StdioBridge, serve_streams


class CommandMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bus = CommandBus(Path(self.temp.name) / "commands.sqlite3")
        self.bridge = StdioBridge(self.bus)

    @staticmethod
    def request(method, params=None, request_id=1):
        return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {} if params is None else params}

    def initialize(self):
        return self.bridge.handle(self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                                              "clientInfo": {"name": "offline-test", "version": "1"}}))

    def test_initialize_and_list_stable_tools(self):
        self.assertIn("error", self.bridge.handle(self.request("tools/list")))
        result = self.initialize()
        self.assertEqual(result["result"]["protocolVersion"], "2024-11-05")
        tools = self.bridge.handle(self.request("tools/list"))["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertTrue({"command_next", "command_submit", "command_respond", "command_speech", "command_outbox_next"} <= names)
        self.assertTrue(all(tool["inputSchema"]["additionalProperties"] is False for tool in tools))

    def test_calls_use_real_bus_and_notifications_cannot_mutate(self):
        self.initialize()
        params = {"name": "command_sessions", "arguments": {"sessionId": "mcp-session"}}
        ignored = {"jsonrpc": "2.0", "method": "tools/call", "params": params}
        self.assertIsNone(self.bridge.handle(ignored))
        self.assertEqual(self.bus.status()["sessions"], [])
        result = self.bridge.handle(self.request("tools/call", params))
        value = json.loads(result["result"]["content"][0]["text"])
        self.assertEqual(value["sessionId"], "mcp-session")
        self.assertEqual(self.bus.status()["sessions"][0]["sessionId"], "mcp-session")

    def test_invalid_tool_args_are_mcp_tool_errors(self):
        self.initialize()
        response = self.bridge.handle(self.request("tools/call", {"name": "command_submit", "arguments": {"execute": True}}))
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(self.bus.status()["sessions"], [])
        response = self.bridge.handle(self.request("tools/call", {"name": "missing", "arguments": {}}))
        self.assertEqual(response["error"]["code"], -32602)

    def test_stdio_framing_parse_errors_unicode_and_no_extra_output(self):
        messages = ["{broken", json.dumps(self.request("ping")),
                    json.dumps(self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "тест"}})),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    json.dumps(self.request("tools/call", {"name": "command_sessions", "arguments": {"sessionId": "сеанс"}}))]
        outgoing = io.StringIO()
        serve_streams(self.bus, io.StringIO("\n".join(messages) + "\n"), outgoing)
        responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual(len(responses), 4)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(json.loads(responses[-1]["result"]["content"][0]["text"])["sessionId"], "сеанс")

    def test_oversize_message_closes_without_mutation(self):
        outgoing = io.StringIO()
        serve_streams(self.bus, io.StringIO("x" * (MAX_LINE_BYTES + 1) + "\n"), outgoing)
        self.assertEqual(json.loads(outgoing.getvalue())["error"]["code"], -32600)
        self.assertEqual(self.bus.status()["sessions"], [])


if __name__ == "__main__":
    unittest.main()
