import concurrent.futures
import json
import hashlib
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from skyrim_autotest.command_bus import (
    BusError, CommandBus, PACKAGE_ROOT, dispatch, external_path, initialize, load_config, read_token, strict_json,
)


BINDING = {"provider": "test-provider", "conversationId": "conversation-1", "agentId": "operator-1"}


class CommandBusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "commands.sqlite3"
        self.now = [1000.0]
        self.bus = CommandBus(self.database, claim_timeout=5, clock=lambda: self.now[0])
        self.bus.create_session("session-1")
        self.bus.bind("session-1", BINDING)

    def submit(self, event="event-1", **overrides):
        args = {"sessionId": "session-1", "sourceId": "test-input", "sourceEventId": event,
                "kind": "text", "text": "Check the requested state"}
        args.update(overrides)
        return self.bus.submit(**args)

    def claim(self):
        return self.bus.next("session-1", BINDING)["command"]

    def delivered(self, command):
        return self.bus.delivered("session-1", command["id"], command["claimId"], BINDING)

    def test_restart_dedup_and_immutable_digest(self):
        first = self.submit(metadata={"b": 2, "a": 1})
        self.bus = CommandBus(self.database)
        duplicate = self.submit(metadata={"a": 1, "b": 2})
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["command"]["id"], duplicate["command"]["id"])
        for replacement in ({"text": "different"}, {"priority": "stop"}, {"kind": "asr.final"}, {"metadata": {}}):
            with self.subTest(replacement=replacement), self.assertRaises(BusError):
                self.submit(**replacement)
        self.assertEqual(self.bus.status("session-1")["commands"], {"received": 1})

    def test_source_event_namespace_prevents_wrong_session_replay(self):
        self.submit()
        self.bus.create_session("session-2")
        self.bus.bind("session-2", BINDING)
        with self.assertRaises(BusError):
            self.submit(sessionId="session-2")
        self.assertEqual(self.bus.status("session-2")["commands"], {})

    def test_expected_binding_is_atomic_for_new_ingress_and_sticky_for_duplicates(self):
        observed = self.bus.status("session-1")["binding"]
        other = dict(BINDING, agentId="new-agent")
        self.bus.bind("session-1", other)
        before = self.bus.events("session-1")
        with self.assertRaises(BusError) as caught:
            self.submit(expectedBinding=observed)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.bus.events("session-1"), before)
        self.assertEqual(self.bus.status("session-1")["commands"], {})
        self.bus.bind("session-1", BINDING)
        first = self.submit(expectedBinding=BINDING)
        command = self.claim()
        self.delivered(command)
        self.bus.complete("session-1", command["id"], command["claimId"], BINDING)
        self.bus.bind("session-1", other)
        duplicate = self.submit(expectedBinding=BINDING)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["command"]["id"], first["command"]["id"])
        self.assertEqual(duplicate["command"]["binding"], BINDING)
        self.assertEqual(duplicate["command"]["state"], "completed")
        with self.assertRaises(BusError):
            self.submit(expectedBinding=other)
        self.assertEqual(sum(e["type"] == "command.received" for e in self.bus.events("session-1")["events"]), 1)

    def test_absent_expected_binding_keeps_legacy_digest_and_null_is_invalid(self):
        first = self.submit()
        content = {"sessionId": "session-1", "sourceId": "test-input", "sourceEventId": "event-1", "kind": "text",
                   "text": "Check the requested state", "priority": "normal", "metadata": {}}
        expected_digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(first["command"]["digest"], expected_digest)
        self.assertTrue(self.submit()["duplicate"])
        before = self.bus.events("session-1")
        with self.assertRaises(BusError):
            self.submit("null-target", expectedBinding=None)
        with self.assertRaises(BusError):
            self.submit(expectedBinding=BINDING)
        self.assertEqual(self.bus.events("session-1"), before)

    def test_final_asr_only_and_strict_dispatch(self):
        with self.assertRaises(BusError):
            self.submit(kind="asr.partial")
        result = self.submit(kind="asr.final", text="Проверить состояние")
        self.assertEqual(result["command"]["kind"], "asr.final")
        with self.assertRaises(BusError):
            dispatch(self.bus, "submit", {"sessionId": "session-1", "surprise": True})
        with self.assertRaises(BusError):
            dispatch(self.bus, "events", {"sessionId": "session-1", "afterId": True})

    def test_binding_before_ingress_and_no_rebind_unfinished_work(self):
        self.bus.create_session("unbound")
        with self.assertRaises(BusError):
            self.submit(sessionId="unbound")
        self.submit()
        with self.assertRaises(BusError):
            self.bus.bind("session-1", dict(BINDING, agentId="other"))
        self.assertTrue(self.bus.bind("session-1", BINDING)["duplicate"])

    def test_wrong_binding_session_and_claim_cannot_consume(self):
        self.submit()
        with self.assertRaises(BusError) as caught:
            self.bus.next("session-1", dict(BINDING, conversationId="other"))
        self.assertEqual(caught.exception.status, 403)
        command = self.claim()
        with self.assertRaises(BusError):
            self.bus.delivered("session-1", command["id"], "wrong-claim", BINDING)
        self.bus.create_session("session-2")
        self.bus.bind("session-2", BINDING)
        with self.assertRaises(BusError):
            self.bus.delivered("session-2", command["id"], command["claimId"], BINDING)

    def test_rebind_waits_for_old_outbox_and_preserves_its_target(self):
        self.submit()
        command = self.claim()
        self.delivered(command)
        response = self.bus.respond("session-1", command["id"], command["claimId"], BINDING, "reply", "Finished")
        self.bus.complete("session-1", command["id"], command["claimId"], BINDING)
        other = dict(BINDING, agentId="other")
        with self.assertRaises(BusError):
            self.bus.bind("session-1", other)
        item = self.bus.outbox_next("session-1", "response", "display")["item"]
        self.assertEqual(item["binding"], BINDING)
        self.assertEqual(item["id"], response["item"]["id"])
        self.bus.outbox_delivered("session-1", item["id"], item["claimId"], "display")
        self.bus.outbox_complete("session-1", item["id"], item["claimId"], "display")
        self.bus.bind("session-1", other)

    def test_concurrent_same_event_is_one_durable_command(self):
        barrier = threading.Barrier(12)
        def submit(_):
            barrier.wait()
            return self.submit()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(submit, range(12)))
        self.assertEqual(len({r["command"]["id"] for r in results}), 1)
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        events = self.bus.events("session-1")["events"]
        self.assertEqual(sum(r["type"] == "command.received" for r in events), 1)

    def test_concurrent_consumers_only_one_claim_and_receive_while_busy(self):
        self.submit()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.bus.next("session-1", BINDING), range(8)))
        self.assertEqual(sum(r["command"] is not None for r in results), 1)
        self.assertTrue(all(r["blocked"]["state"] == "claimed" for r in results if r["command"] is None))
        second = self.submit("event-2", kind="asr.final", text="Stop after this operation", priority="stop")
        self.assertTrue(second["acknowledged"])
        self.assertEqual(second["command"]["state"], "received")
        self.assertEqual(self.bus.next("session-1", BINDING)["blocked"]["state"], "claimed")

    def test_received_delivered_response_completed_are_distinct(self):
        self.submit()
        command = self.claim()
        with self.assertRaises(BusError):
            self.bus.complete("session-1", command["id"], command["claimId"], BINDING)
        self.delivered(command)
        self.assertTrue(self.delivered(command)["duplicate"])
        response = self.bus.respond("session-1", command["id"], command["claimId"], BINDING, "reply-1", "Received; checking now")
        self.assertEqual(response["item"]["state"], "pending")
        self.assertEqual(self.bus.status("session-1")["commands"], {"delivered": 1})
        result = {"outcome": "checked", "actionTaken": False}
        done = self.bus.complete("session-1", command["id"], command["claimId"], BINDING, result)
        self.assertEqual(done["command"]["state"], "completed")
        self.assertTrue(self.bus.complete("session-1", command["id"], command["claimId"], BINDING, result)["duplicate"])
        with self.assertRaises(BusError):
            self.bus.complete("session-1", command["id"], command["claimId"], BINDING, {"outcome": "different"})

    def test_crash_claim_is_uncertain_and_blocks_following_commands(self):
        self.submit()
        command = self.claim()
        self.delivered(command)
        self.submit("event-2")
        self.now[0] += 6
        self.bus = CommandBus(self.database, claim_timeout=5, clock=lambda: self.now[0])
        blocked = self.bus.next("session-1", BINDING)
        self.assertIsNone(blocked["command"])
        self.assertEqual(blocked["blocked"], {"id": command["id"], "state": "uncertain"})
        self.assertEqual(self.bus.next("session-1", BINDING)["blocked"]["state"], "uncertain")
        with self.assertRaises(BusError):
            self.bus.complete("session-1", command["id"], command["claimId"], BINDING)
        self.bus.reconcile("session-1", command["id"], BINDING, "completed", "Observed exact operation result", {"outcome": "observed"})
        following = self.claim()
        self.assertEqual(following["sourceEventId"], "event-2")

    def test_only_explicit_not_delivered_releases_a_retry_and_rejects_old_claim(self):
        self.submit()
        old = self.claim()
        self.bus.reconcile("session-1", old["id"], BINDING, "uncertain", "Consumer exited before acknowledgement")
        self.bus.reconcile("session-1", old["id"], BINDING, "not_delivered", "Consumer stopped; verified no delivery or action")
        new = self.claim()
        self.assertEqual(new["id"], old["id"])
        self.assertNotEqual(new["claimId"], old["claimId"])
        with self.assertRaises(BusError):
            self.delivered(old)
        self.delivered(new)

    def test_renew_keeps_busy_consumer_and_expiry_cannot_be_renewed(self):
        self.submit()
        command = self.claim()
        self.now[0] += 4
        self.bus.renew("session-1", command["id"], command["claimId"], BINDING)
        self.now[0] += 4
        self.assertEqual(self.bus.next("session-1", BINDING)["blocked"]["state"], "claimed")
        self.now[0] += 2
        with self.assertRaises(BusError):
            self.bus.renew("session-1", command["id"], command["claimId"], BINDING)
        self.assertEqual(self.bus.status("session-1")["commands"], {"uncertain": 1})

    def test_each_stale_command_operation_persists_uncertain_without_next_poll(self):
        for operation in ("delivered", "complete", "respond", "renew"):
            session = "expiry-" + operation
            self.bus.create_session(session)
            self.bus.bind(session, BINDING)
            self.bus.submit(session, "expiry-source", operation, "text", "Check once")
            command = self.bus.next(session, BINDING)["command"]
            arguments = {"sessionId": session, "binding": BINDING, "commandId": command["id"], "claimId": command["claimId"]}
            if operation != "delivered":
                self.bus.delivered(**arguments)
            self.now[0] += 6
            if operation == "respond":
                arguments.update(sourceEventId="stale-reply", text="Must not publish")
            with self.subTest(operation=operation), self.assertRaises(BusError):
                dispatch(self.bus, operation, arguments)
            reopened = CommandBus(self.database)
            self.assertEqual(reopened.status(session)["commands"], {"uncertain": 1})
            self.assertEqual(reopened.status(session)["outbox"], [])

    def test_speech_outbox_dedup_exclusive_claim_and_uncertain_recovery(self):
        first = self.bus.speech("session-1", BINDING, "speech-1", "Test complete")
        self.assertTrue(self.bus.speech("session-1", BINDING, "speech-1", "Test complete")["duplicate"])
        with self.assertRaises(BusError):
            self.bus.speech("session-1", BINDING, "speech-1", "Changed text")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda n: self.bus.outbox_next("session-1", "speech", f"sound-{n}"), range(4)))
        self.assertEqual(sum(c["item"] is not None for c in claims), 1)
        item = next(c["item"] for c in claims if c["item"])
        with self.assertRaises(BusError):
            self.bus.outbox_complete("session-1", item["id"], item["claimId"], item["consumerId"])
        self.bus.outbox_delivered("session-1", item["id"], item["claimId"], item["consumerId"])
        self.now[0] += 6
        self.assertEqual(self.bus.outbox_next("session-1", "speech", "new-adapter")["blocked"]["state"], "uncertain")
        with self.assertRaises(BusError):
            self.bus.outbox_complete("session-1", item["id"], item["claimId"], item["consumerId"])
        self.bus.outbox_reconcile("session-1", item["id"], "completed", "Adapter evidence confirms actual playback")
        self.assertIsNone(self.bus.outbox_next("session-1", "speech", "new-adapter")["item"])
        events = self.bus.events("session-1")["events"]
        requests = [e for e in events if e["type"] == "speech.requested"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["data"]["outboxId"], first["item"]["id"])

    def test_outbox_wrong_consumer_and_wrong_session_refused(self):
        self.bus.speech("session-1", BINDING, "speech-1", "Checking")
        item = self.bus.outbox_next("session-1", "speech", "sound-1")["item"]
        with self.assertRaises(BusError):
            self.bus.outbox_complete("session-1", item["id"], item["claimId"], "sound-2")
        self.bus.create_session("session-2")
        with self.assertRaises(BusError):
            self.bus.outbox_complete("session-2", item["id"], item["claimId"], "sound-1")
        self.bus.outbox_delivered("session-1", item["id"], item["claimId"], "sound-1")
        self.bus.outbox_complete("session-1", item["id"], item["claimId"], "sound-1", {"displayed": True})
        self.assertTrue(self.bus.outbox_complete("session-1", item["id"], item["claimId"], "sound-1", {"displayed": True})["duplicate"])

    def test_outbox_renew_and_delivery_ack_are_distinct_from_completion(self):
        self.bus.speech("session-1", BINDING, "speech-renew", "Long spoken response")
        item = self.bus.outbox_next("session-1", "speech", "sound")["item"]
        self.now[0] += 4
        self.bus.outbox_renew("session-1", item["id"], item["claimId"], "sound")
        self.now[0] += 4
        delivered = self.bus.outbox_delivered("session-1", item["id"], item["claimId"], "sound")
        self.assertEqual(delivered["item"]["state"], "delivered")
        self.assertTrue(self.bus.outbox_delivered("session-1", item["id"], item["claimId"], "sound")["duplicate"])
        self.now[0] += 2
        with self.assertRaises(BusError):
            self.bus.outbox_renew("session-1", item["id"], item["claimId"], "sound")
        self.assertEqual(self.bus.outbox_next("session-1", "speech", "replacement")["blocked"]["state"], "uncertain")

    def test_each_stale_outbox_operation_persists_uncertain_without_next_poll(self):
        for operation in ("outbox-delivered", "outbox-complete", "outbox-renew"):
            session = "expiry-" + operation
            self.bus.create_session(session)
            self.bus.bind(session, BINDING)
            self.bus.speech(session, BINDING, "speech", "Check once")
            item = self.bus.outbox_next(session, "speech", "sound")["item"]
            arguments = {"sessionId": session, "outboxId": item["id"], "claimId": item["claimId"], "consumerId": "sound"}
            if operation != "outbox-delivered":
                self.bus.outbox_delivered(**arguments)
            self.now[0] += 6
            with self.subTest(operation=operation), self.assertRaises(BusError):
                dispatch(self.bus, operation, arguments)
            self.assertEqual(CommandBus(self.database).status(session)["outbox"], [{"channel": "speech", "state": "uncertain", "count": 1}])

    def test_foreign_sqlite_database_is_preserved_byte_for_byte(self):
        foreign = Path(self.temp.name) / "foreign.sqlite3"
        with sqlite3.connect(foreign) as con:
            con.execute("CREATE TABLE sqliteX (important TEXT)")
            con.execute("INSERT INTO sqliteX VALUES ('preserve me')")
        con.close()
        before = hashlib.sha256(foreign.read_bytes()).hexdigest()
        with self.assertRaises(BusError):
            CommandBus(foreign)
        self.assertEqual(before, hashlib.sha256(foreign.read_bytes()).hexdigest())
        with sqlite3.connect(foreign) as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(con.execute("PRAGMA application_id").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT important FROM sqliteX").fetchone()[0], "preserve me")
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        con.close()

    def test_events_cursor_is_session_scoped_and_contains_no_claim_secret(self):
        self.submit()
        command = self.claim()
        first = self.bus.events("session-1", limit=2)
        later = self.bus.events("session-1", afterId=first["nextAfterId"])
        all_events = first["events"] + later["events"]
        self.assertNotIn(command["claimId"], json.dumps(all_events))
        ids = [e["id"] for e in all_events]
        self.assertEqual(ids, sorted(set(ids)))
        self.bus.create_session("session-2")
        self.assertTrue(all(e["sessionId"] == "session-2" for e in self.bus.events("session-2")["events"]))

    def test_actual_process_exit_preserves_received_and_claimed_items(self):
        source = """import json,os,sys
sys.path.insert(0,sys.argv[1])
from skyrim_autotest.command_bus import CommandBus
b=CommandBus(sys.argv[2],claim_timeout=5)
b.submit('session-1','subprocess','child-event','text','Durable child command')
b.next('session-1',json.loads(sys.argv[3]))
os._exit(23)
"""
        unrelated = Path(self.temp.name) / "unrelated-child-cwd"
        unrelated.mkdir()
        result = subprocess.run([sys.executable, "-I", "-c", source, str(PACKAGE_ROOT), str(self.database), json.dumps(BINDING)],
                                cwd=unrelated, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 23, result.stderr.decode())
        reopened = CommandBus(self.database)
        duplicate = reopened.submit("session-1", "subprocess", "child-event", "text", "Durable child command")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["command"]["state"], "claimed")
        expired = CommandBus(self.database, clock=lambda: 10**12).next("session-1", BINDING)
        self.assertEqual(expired["blocked"]["state"], "uncertain")

    def test_invalid_payloads_do_not_create_events(self):
        before = self.bus.events("session-1")
        invalid = [{"text": " "}, {"text": "x" * 32769}, {"text": "bad\x00"}, {"text": "\ud800"},
                   {"metadata": {"value": float("nan")}}, {"metadata": []}, {"sourceId": "with space"}, {"priority": "immediate"}]
        for payload in invalid:
            with self.subTest(payload=str(payload)[:80]), self.assertRaises(BusError):
                self.submit(**payload)
        self.assertEqual(before, self.bus.events("session-1"))
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', "[" * 20 + "0" + "]" * 20):
            with self.assertRaises(BusError):
                strict_json(raw)

    def test_initialize_is_idempotent_and_token_not_returned(self):
        path = Path(self.temp.name) / "external" / "command-channel.json"
        initialized = initialize(path, "new-session")
        config = load_config(path)
        token = read_token(config)
        self.assertNotIn(token, json.dumps(initialized))
        initialize(path, "new-session")
        self.assertEqual(token, read_token(load_config(path)))
        config["host"] = "0.0.0.0"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaises(BusError):
            load_config(path)

    def config_data(self):
        return {"schemaVersion": 1, "database": str(Path(self.temp.name) / "new.sqlite3"),
                "tokenFile": str(Path(self.temp.name) / "new.token")}

    def test_external_paths_reject_git_and_distribution_before_creation(self):
        git = Path(self.temp.name) / "other-repository"
        git.mkdir()
        (git / ".git").write_text("gitdir: external-metadata", encoding="utf-8")
        for target in (git / "not-created" / "channel.json", PACKAGE_ROOT / "not-created-command-channel" / "channel.json"):
            with self.subTest(target=target), self.assertRaises(BusError):
                initialize(target)
            self.assertFalse(target.parent.exists())
        with self.assertRaises(BusError):
            CommandBus(git / "not-created" / "commands.sqlite3")
        self.assertFalse((git / "not-created").exists())
        path = Path(self.temp.name) / "config.json"
        for field in ("database", "tokenFile"):
            for parent in (git, PACKAGE_ROOT):
                data = self.config_data()
                data[field] = str(parent / "not-created-command-channel" / field)
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(field=field, parent=parent), self.assertRaises(BusError):
                    load_config(path)

    def test_config_database_token_and_sqlite_sidecar_aliases_are_rejected(self):
        path = Path(self.temp.name) / "config.json"
        for suffix in ("", "-wal", "-shm", "-journal"):
            data = self.config_data()
            data["tokenFile"] = data["database"] + suffix
            token = Path(data["tokenFile"])
            token.write_text("A" * 43, encoding="ascii")
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(suffix=suffix), self.assertRaises(BusError):
                initialize(path)
            self.assertEqual(token.read_text(encoding="ascii"), "A" * 43)
        data = self.config_data()
        data["database"] = str(path)
        path.write_text(json.dumps(data), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(BusError):
            initialize(path)
        self.assertEqual(path.read_bytes(), before)

    def test_reparse_attribute_on_existing_ancestor_is_refused_before_mkdir(self):
        ancestor = Path(self.temp.name) / "reparse-ancestor"
        ancestor.mkdir()
        target = ancestor / "not-created" / "channel.json"
        actual_lstat = Path.lstat
        def pretend_reparse(candidate, *args, **kwargs):
            info = actual_lstat(candidate, *args, **kwargs)
            if candidate == ancestor:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with patch.object(Path, "lstat", pretend_reparse), self.assertRaises(BusError):
            initialize(target)
        self.assertFalse(target.parent.exists())

    def test_real_symlink_ancestor_and_token_are_refused_when_supported(self):
        target = Path(self.temp.name) / "target"
        target.mkdir()
        link = Path(self.temp.name) / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"OS does not permit symlink creation: {type(exc).__name__}")
        with self.assertRaises(BusError):
            initialize(link / "not-created" / "channel.json")
        self.assertFalse((target / "not-created").exists())
        config_path = Path(self.temp.name) / "config.json"
        data = self.config_data()
        data["tokenFile"] = str(link / "private.token")
        config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(BusError):
            load_config(config_path)

    def test_relative_runtime_paths_and_existing_invalid_token_are_preserved(self):
        with self.assertRaises(BusError):
            initialize("relative-channel.json")
        path = Path(self.temp.name) / "config.json"
        data = self.config_data()
        data["database"] = "relative.sqlite3"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(BusError):
            load_config(path)
        data = self.config_data()
        token = Path(data["tokenFile"])
        token.write_bytes(b"existing-invalid-owner-secret")
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(BusError):
            initialize(path)
        self.assertEqual(token.read_bytes(), b"existing-invalid-owner-secret")


if __name__ == "__main__":
    unittest.main()
