"""Minimal newline-delimited stdio MCP transport, with no host-specific hooks.

Only protocol 2024-11-05, initialize/ping and tools/list/tools/call are supported.
Starting this process gives it the local user's database-file authority. The HTTP
bearer token is not sent over stdio. No tool executes a game or opens audio.
"""
from __future__ import annotations

import json
import sqlite3
import sys

from .command_bus import BusError, CommandBus, OPERATIONS, dispatch, load_config, strict_json


PROTOCOL_VERSION = "2024-11-05"
MAX_LINE_BYTES = 131072


def _property(name):
    if name in ("binding", "expectedBinding"):
        return {"type": "object", "properties": {key: {"type": "string", "minLength": 1, "maxLength": 200}
                for key in ("provider", "conversationId", "agentId")},
                "required": ["provider", "conversationId", "agentId"], "additionalProperties": False}
    if name in ("afterId", "limit"):
        return {"type": "integer", "minimum": 0 if name == "afterId" else 1,
                **({"maximum": 500} if name == "limit" else {})}
    if name == "metadata":
        return {"type": "object"}
    if name == "result":
        return {}
    if name in ("kind", "priority", "channel", "disposition"):
        return {"type": "string", "enum": {"kind": ["text", "asr.final"], "priority": ["normal", "stop", "cancel"],
                "channel": ["response", "speech"], "disposition": ["uncertain", "not_delivered", "completed", "abandoned"]}[name]}
    return {"type": "string", "minLength": 1, "maxLength": 32768 if name == "text" else 4096 if name == "note" else 200}


def tools_list():
    descriptions = {
        "submit": "Durably receive owner text or FINAL ASR, including while the consumer is busy. Never executes it.",
        "next": "Exclusively claim the next command for the exact bound agent. Active or uncertain delivery blocks the queue.",
        "delivered": "Record that the bound host accepted the command BEFORE interpreting or executing any authorized action.",
        "complete": "Record completion and actual result. This is distinct from receipt, delivery and a first response.",
        "respond": "Durably publish a text response in the response outbox; this alone does not display it in a host chat.",
        "speech": "Publish speech.requested for a separately connected sound adapter. Never synthesizes or plays sound.",
        "reconcile": "Explicitly resolve an uncertain delivery from evidence. not_delivered permits retry; never guess it.",
        "outbox-next": "Exclusively claim one response/speech item for an external adapter; never auto-replays uncertain output.",
        "events": "Read durable session events from an external persisted cursor. Reading an event is not action authorization.",
    }
    return [{"name": "command_" + operation.replace("-", "_"),
             "description": descriptions.get(operation, "Command channel " + operation + "; never executes game actions."),
             "inputSchema": {"type": "object", "properties": {name: _property(name) for name in required + optional},
                             "required": list(required), "additionalProperties": False}}
            for operation, (_, required, optional) in OPERATIONS.items()]


class StdioBridge:
    def __init__(self, bus):
        self.bus = bus
        self.initialized = False

    @staticmethod
    def _error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return self._error(None, -32600, "Invalid JSON-RPC request")
        request_id = request.get("id")
        if request_id is not None and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
            return self._error(None, -32600, "Request id must be a string or integer")
        # Notifications never mutate the bus, even if named tools/call.
        if "id" not in request:
            return None
        method = request["method"]
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self._error(request_id, -32602, "params must be an object")
        if method == "initialize":
            if not isinstance(params.get("protocolVersion"), str) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("clientInfo"), dict):
                return self._error(request_id, -32602, "initialize requires protocolVersion, capabilities and clientInfo")
            self.initialized = True
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "skyrim-autotest-command-channel", "version": "1.0.0"}}
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return self._error(request_id, -32000, "Initialize the stdio bridge first")
        elif method == "tools/list":
            if params:
                return self._error(request_id, -32602, "Pagination is not supported")
            result = {"tools": tools_list()}
        elif method == "tools/call":
            if set(params) - {"name", "arguments"} or not isinstance(params.get("name"), str):
                return self._error(request_id, -32602, "tools/call requires name and arguments")
            names = {"command_" + op.replace("-", "_"): op for op in OPERATIONS}
            if params["name"] not in names:
                return self._error(request_id, -32602, "Unknown tool")
            try:
                value = dispatch(self.bus, names[params["name"]], params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, allow_nan=False)}]}
            except BusError as exc:
                result = {"isError": True, "content": [{"type": "text", "text": json.dumps({"error": str(exc), "code": exc.code})}]}
            except (sqlite3.Error, OSError):
                result = {"isError": True, "content": [{"type": "text", "text": "Command channel storage is unavailable"}]}
        else:
            return self._error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve_streams(bus, incoming, outgoing):
    bridge = StdioBridge(bus)
    while True:
        line = incoming.readline(MAX_LINE_BYTES + 1)
        if not line:
            return
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            response = bridge._error(None, -32600, "Message exceeds size limit; connection closing")
            outgoing.write(json.dumps(response) + "\n")
            outgoing.flush()
            return
        try:
            request = strict_json(line)
            response = bridge.handle(request)
        except (BusError, UnicodeError):
            response = bridge._error(None, -32700, "Parse error")
        if response is not None:
            outgoing.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
            outgoing.flush()


def serve_stdio(config_path):
    config = load_config(config_path)
    # JSON-RPC messages are UTF-8 regardless of the Windows console code page.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    serve_streams(CommandBus(config["database"], config["claimTimeoutSeconds"]), sys.stdin, sys.stdout)


if __name__ == "__main__":
    from .command_bus import main
    raise SystemExit(main())
