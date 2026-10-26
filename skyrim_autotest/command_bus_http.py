"""Authenticated loopback HTTP transport for the durable command channel."""
from __future__ import annotations

import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import threading
import time

from .command_bus import BusError, CommandBus, OPERATIONS, _json, dispatch, external_path, load_config, read_token, strict_json


class CommandHTTPClient:
    """Native local client. Only immutable ingress has a bounded retry helper.

    Callers persist sourceEventId before the first attempt, and reuse it after
    process restart. The client does not create source identities or open audio.
    """

    def __init__(self, config_path, timeout=10):
        self.config = load_config(config_path)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise BusError("Client timeout must be in (0,60] seconds")
        self.timeout = timeout

    def call(self, operation, arguments):
        if operation not in OPERATIONS:
            raise BusError("Unknown operation", "not_found", 404)
        _, required, optional = OPERATIONS[operation]
        if not isinstance(arguments, dict) or not set(required) <= set(arguments) or set(arguments) - set(required) - set(optional):
            raise BusError("Operation arguments have missing or unknown fields")
        body = _json(arguments, self.config["maxRequestBytes"]).encode("utf-8")
        connection = http.client.HTTPConnection(self.config["host"], self.config["port"], timeout=self.timeout)
        try:
            connection.request("POST", "/v1/" + operation, body,
                               {"Content-Type": "application/json", "Authorization": "Bearer " + read_token(self.config)})
            response = connection.getresponse()
            # Events can contain bounded text; reject an unexpectedly huge peer reply.
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise BusError("Command channel response exceeds its size limit")
            try:
                value = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise BusError("Invalid command channel response") from exc
            if not isinstance(value, dict):
                raise BusError("Invalid command channel response")
            if response.status != 200:
                # Never include a peer's response in an exception: it could contain secrets.
                raise BusError("Command channel rejected the request", "unavailable" if response.status == 503 else "rejected", response.status)
            return value
        finally:
            connection.close()

    def submit(self, arguments, max_attempts=3):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise BusError("max_attempts must be an integer in 1..5")
        # Freeze caller-owned dictionaries across attempts: a source event has one digest.
        frozen = json.loads(_json(arguments, self.config["maxRequestBytes"]))
        for attempt in range(max_attempts):
            try:
                return self.call("submit", frozen)
            except BusError as exc:
                if exc.status != 503 or attempt + 1 == max_attempts:
                    raise
            except (OSError, http.client.HTTPException):
                if attempt + 1 == max_attempts:
                    raise


class CommandHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 32

    def __init__(self, address, bus, token, max_request_bytes=65536):
        if address[0] != "127.0.0.1":
            raise BusError("HTTP channel must bind the literal loopback address 127.0.0.1")
        self.bus, self.token, self.max_request_bytes = bus, token, max_request_bytes
        self._workers = threading.BoundedSemaphore(32)
        super().__init__(address, CommandHandler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(5)
        return request, address

    def process_request(self, request, client_address):
        if not self._workers.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._workers.release()

    def handle_error(self, request, client_address):
        # Client disconnects must not print content, credentials or tracebacks.
        pass


class CommandHandler(BaseHTTPRequestHandler):
    server_version = "CommandChannel/1"
    sys_version = ""

    def log_message(self, format, *args):
        # No request/access logging: source text and credentials remain private.
        pass

    def _reply(self, status, body):
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            # A lost ACK is recovered by retrying the same source event id.
            pass

    def _authorize(self):
        if self.headers.get_all("Origin") or self.headers.get_all("Sec-Fetch-Site"):
            raise BusError("Browser-origin requests are forbidden", "browser_forbidden", 403)
        hosts = self.headers.get_all("Host", [])
        if hosts != [f"127.0.0.1:{self.server.server_port}"]:
            raise BusError("Host must identify the exact loopback endpoint", "host_forbidden", 403)
        auth = self.headers.get_all("Authorization", [])
        expected = "Bearer " + self.server.token
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode("utf-8"), expected.encode("ascii")):
            raise BusError("Authentication required", "unauthorized", 401)
        if "?" in self.path or "#" in self.path or not self.path.startswith("/v1/"):
            raise BusError("Unknown endpoint", "not_found", 404)

    def _discard_oversize(self, length):
        # Closing a Windows TCP socket with unread input can reset it and discard
        # the 413 reply. Drain ordinary near-limit bodies, with hard byte/time caps;
        # a hostile declared length or a stalled sender must never extend this work.
        remaining = min(length, self.server.max_request_bytes * 2)
        deadline = time.monotonic() + .25
        old_timeout = self.connection.gettimeout()
        try:
            while remaining > 0:
                budget = deadline - time.monotonic()
                if budget <= 0:
                    break
                self.connection.settimeout(min(.05, budget))
                try:
                    chunk = self.rfile.read1(min(16384, remaining))
                except (OSError, socket.timeout):
                    break
                if not chunk:
                    break
                remaining -= len(chunk)
        finally:
            self.connection.settimeout(old_timeout)

    def _handle(self, post):
        try:
            self._authorize()
            operation = self.path[len("/v1/"):]
            if post:
                if self.headers.get_all("Transfer-Encoding"):
                    raise BusError("Transfer encoding is forbidden")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                    raise BusError("One numeric Content-Length is required")
                length = int(lengths[0])
                if length > self.server.max_request_bytes:
                    self._discard_oversize(length)
                    raise BusError("Request exceeds the configured size limit", "too_large", 413)
                types = self.headers.get_all("Content-Type", [])
                if len(types) != 1 or types[0].lower() not in ("application/json", "application/json; charset=utf-8"):
                    raise BusError("Content-Type must be application/json", "unsupported_media_type", 415)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise BusError("Incomplete request body")
                arguments = strict_json(raw.decode("utf-8"))
            else:
                if operation != "status":
                    raise BusError("Only status supports GET", "method_not_allowed", 405)
                arguments = {}
            # dispatch returns only after its transaction COMMIT. No ACK precedes durability.
            result = dispatch(self.server.bus, operation, arguments)
            self._reply(200, result)
        except BusError as exc:
            self._reply(exc.status, {"error": str(exc), "code": exc.code})
        except (UnicodeError, ValueError, OverflowError):
            self._reply(400, {"error": "Invalid request encoding or length", "code": "invalid"})
        except (sqlite3.Error, OSError):
            self._reply(503, {"error": "Command channel storage or transport is unavailable", "code": "unavailable"})

    def do_POST(self):
        self._handle(True)

    def do_GET(self):
        self._handle(False)

    def do_OPTIONS(self):
        self._reply(403, {"error": "Browser-origin requests are forbidden", "code": "browser_forbidden"})


def create_server(config):
    bus = CommandBus(config["database"], config["claimTimeoutSeconds"])
    return CommandHTTPServer((config["host"], config["port"]), bus, read_token(config), config["maxRequestBytes"])


def serve(config_path, ready_file=None):
    config = load_config(config_path)
    server = create_server(config)
    try:
        if ready_file:
            path = external_path(ready_file, "Ready receipt")
            protected = {Path(config["database"]).resolve(), Path(config["tokenFile"]).resolve(), Path(config_path).resolve()}
            protected.update(Path(config["database"] + suffix).resolve() for suffix in ("-wal", "-shm", "-journal"))
            if path in protected:
                raise BusError("Ready receipt must be separate from configuration, token and database")
            path.parent.mkdir(parents=True, exist_ok=True)
            receipt = {"schemaVersion": 1, "host": config["host"], "port": server.server_port,
                       "pid": __import__("os").getpid(), "receiving": True}
            # Receipt means the listening socket exists, not that an AI host is awake.
            # Fresh launch receipts are exclusive. Never replace an existing owner file.
            try:
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(receipt) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError as exc:
                raise BusError("Ready receipt already exists; choose a fresh launch receipt path") from exc
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    from .command_bus import main
    raise SystemExit(main())
