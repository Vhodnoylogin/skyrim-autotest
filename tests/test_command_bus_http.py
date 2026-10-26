import concurrent.futures
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest.command_bus import BusError, CommandBus
from skyrim_autotest.command_bus_http import CommandHTTPClient, CommandHTTPServer, serve


BINDING = {"provider": "test", "conversationId": "chat", "agentId": "agent"}
TOKEN = "test-token-with-at-least-thirty-two-characters"


class CommandHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "commands.sqlite3"
        self.bus = CommandBus(self.database)
        self.bus.create_session("session")
        self.bus.bind("session", BINDING)
        self.server = CommandHTTPServer(("127.0.0.1", 0), self.bus, TOKEN, 65536)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.config_path = Path(self.temp.name) / "command-channel.json"
        token_path = Path(self.temp.name) / "token"
        token_path.write_text(TOKEN, encoding="ascii")
        self.config_path.write_text(json.dumps({"schemaVersion": 1, "database": str(self.database), "tokenFile": str(token_path),
                                               "host": "127.0.0.1", "port": self.server.server_port}), encoding="utf-8")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.temp.cleanup()

    def request(self, operation, arguments=None, headers=None, raw=None, method="POST"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        body = json.dumps({} if arguments is None else arguments).encode("utf-8") if raw is None else raw
        actual_headers = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}
        if headers:
            actual_headers.update(headers)
        connection.request(method, "/v1/" + operation, body if method == "POST" else None, actual_headers)
        response = connection.getresponse()
        status, data, result_headers = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return status, data, result_headers

    @staticmethod
    def submission(event="event-1"):
        return {"sessionId": "session", "sourceId": "http-input", "sourceEventId": event,
                "kind": "asr.final", "text": "Проверить текущее состояние"}

    def test_ack_is_visible_in_independent_connection_and_restart_dedup(self):
        status, first, _ = self.request("submit", self.submission())
        self.assertEqual(status, 200)
        self.assertTrue(first["acknowledged"])
        reopened = CommandBus(self.database)
        self.assertEqual(reopened.status("session")["commands"], {"received": 1})
        self.server.bus = reopened
        status, duplicate, _ = self.request("submit", self.submission())
        self.assertEqual(status, 200)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["command"]["id"], duplicate["command"]["id"])

    def test_new_final_asr_received_during_busy_consumer(self):
        self.request("submit", self.submission())
        status, result, _ = self.request("next", {"sessionId": "session", "binding": BINDING})
        self.assertEqual(status, 200)
        command = result["command"]
        self.request("delivered", {"sessionId": "session", "binding": BINDING,
                                   "commandId": command["id"], "claimId": command["claimId"]})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: self.request("submit", self.submission(f"busy-event-{n}")), range(8)))
        self.assertTrue(all(r[0] == 200 and r[1]["acknowledged"] for r in results))
        status, result, _ = self.request("next", {"sessionId": "session", "binding": BINDING})
        self.assertEqual(result["blocked"]["state"], "delivered")
        self.assertEqual(CommandBus(self.database).status("session")["commands"], {"delivered": 1, "received": 8})

    def test_client_lost_submit_ack_retries_same_persisted_event_once(self):
        client = CommandHTTPClient(self.config_path)
        actual_call = client.call
        calls = []
        def lose_first_ack(operation, arguments):
            result = actual_call(operation, arguments)
            calls.append(json.dumps(arguments, sort_keys=True))
            if len(calls) == 1:
                raise ConnectionResetError("simulated lost ACK after server commit")
            return result
        client.call = lose_first_ack
        result = client.submit(self.submission("persisted-segment-id"))
        self.assertTrue(result["duplicate"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(self.bus.status("session")["commands"], {"received": 1})

    def test_speech_client_claim_delivery_completion_without_audio(self):
        client = CommandHTTPClient(self.config_path)
        client.call("speech", {"sessionId": "session", "binding": BINDING, "sourceEventId": "speech-1", "text": "Ready"})
        item = client.call("outbox-next", {"sessionId": "session", "channel": "speech", "consumerId": "external-sound"})["item"]
        receipt = {"sessionId": "session", "outboxId": item["id"], "claimId": item["claimId"], "consumerId": "external-sound"}
        delivered = client.call("outbox-delivered", receipt)
        self.assertEqual(delivered["item"]["state"], "delivered")
        completed = client.call("outbox-complete", dict(receipt, result={"outcome": "offline-adapter-test", "audioPlayed": False}))
        self.assertEqual(completed["item"]["state"], "completed")

    def test_auth_browser_origin_host_and_query_rejected_without_cors(self):
        attempts = [("status", {"Authorization": "Bearer wrong"}, 401),
                    ("status", {"Origin": "https://example.invalid"}, 403),
                    ("status", {"Origin": "null"}, 403),
                    ("status", {"Sec-Fetch-Site": "same-origin"}, 403),
                    ("status", {"Host": "attacker.invalid"}, 403),
                    ("status?token=" + TOKEN, {}, 404)]
        for operation, headers, expected in attempts:
            with self.subTest(headers=headers):
                status, body, result_headers = self.request(operation, headers=headers)
                self.assertEqual(status, expected)
                self.assertFalse(any(k.lower().startswith("access-control-") for k in result_headers))
                self.assertNotIn(TOKEN, json.dumps(body))

    def test_size_encoding_json_and_content_type_caps(self):
        attempts = [(b"x" * 65537, {}, 413), (b'{"sessionId":"session","sessionId":"other"}', {}, 400),
                    (b'{"x":NaN}', {}, 400), (b"\xff", {}, 400),
                    (b"{}", {"Content-Type": "text/plain"}, 415),
                    (b"{}", {"Transfer-Encoding": "chunked"}, 400)]
        for raw, headers, expected in attempts:
            with self.subTest(expected=expected, raw=raw[:40]):
                status, _, _ = self.request("submit", headers=headers, raw=raw)
                self.assertEqual(status, expected)
        self.assertEqual(self.bus.status("session")["commands"], {})

    def test_near_limit_rejections_reliably_deliver_413_over_real_http(self):
        # Windows may reset a TCP connection if a rejection closes unread body
        # bytes. Repeated real sends exercise the header/body arrival race.
        for attempt in range(16):
            length = self.server.max_request_bytes + (1 if attempt % 2 else 16384)
            status, result, _ = self.request("submit", raw=b"x" * length)
            self.assertEqual(status, 413)
            self.assertEqual(result["code"], "too_large")
        self.assertEqual(self.bus.status("session")["commands"], {})

    def test_huge_declared_length_without_body_has_bounded_rejection_wait(self):
        request = (f"POST /v1/submit HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n"
                   f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\n"
                   "Content-Length: 1000000000000\r\n\r\n")
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as client:
            client.sendall(request.encode("ascii"))
            response = client.recv(4096)
        self.assertIn(b"413", response.split(b"\r\n", 1)[0])
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(self.bus.status("session")["commands"], {})

    def test_wrong_agent_and_unknown_fields_are_rejected(self):
        self.request("submit", self.submission())
        status, _, _ = self.request("next", {"sessionId": "session", "binding": dict(BINDING, agentId="other")})
        self.assertEqual(status, 403)
        bad = dict(self.submission(), execute=True)
        status, _, _ = self.request("submit", bad)
        self.assertEqual(status, 400)
        status, _, _ = self.request("not-a-route", {})
        self.assertEqual(status, 404)

    def test_duplicate_host_or_authorization_is_rejected(self):
        for extra in (f"Host: 127.0.0.1:{self.server.server_port}\r\n", f"Authorization: Bearer {TOKEN}\r\n"):
            request = (f"POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n"
                       f"Authorization: Bearer {TOKEN}\r\n{extra}Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}")
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5) as client:
                client.sendall(request.encode("ascii"))
                response = client.recv(4096)
            self.assertNotIn(b"200 OK", response)
            self.assertTrue(b"403" in response or b"401" in response)

    def test_get_status_requires_auth_and_non_loopback_bind_is_forbidden(self):
        status, body, _ = self.request("status", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(body["sessions"][0]["sessionId"], "session")
        status, _, _ = self.request("events", method="GET")
        self.assertEqual(status, 405)
        with self.assertRaises(BusError):
            CommandHTTPServer(("0.0.0.0", 0), self.bus, TOKEN)

    def test_ready_receipt_never_replaces_existing_files(self):
        existing = Path(self.temp.name) / "valuable-file.json"
        existing.write_text("original owner data", encoding="utf-8")
        fake = Mock(server_port=self.server.server_port)
        with patch("skyrim_autotest.command_bus_http.create_server", return_value=fake):
            with self.assertRaises(BusError):
                serve(self.config_path, existing)
        self.assertEqual(existing.read_text(encoding="utf-8"), "original owner data")
        fake.server_close.assert_called_once()
        fake.serve_forever.assert_not_called()

    def test_ready_receipt_is_new_absolute_and_protects_sqlite_sidecars(self):
        fake = Mock(server_port=self.server.server_port)
        fake.serve_forever.side_effect = KeyboardInterrupt
        path = Path(self.temp.name) / "fresh-start.json"
        with patch("skyrim_autotest.command_bus_http.create_server", return_value=fake):
            serve(self.config_path, path)
        self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["receiving"])
        for target in ("relative-receipt.json", str(self.database) + "-wal", str(self.database) + "-shm"):
            with self.subTest(target=target), patch("skyrim_autotest.command_bus_http.create_server", return_value=Mock(server_port=1234)):
                with self.assertRaises(BusError):
                    serve(self.config_path, target)


if __name__ == "__main__":
    unittest.main()
