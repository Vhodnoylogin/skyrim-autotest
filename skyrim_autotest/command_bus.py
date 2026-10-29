"""Durable, vendor-neutral command channel. This module never executes actions.

The inbox and outbox use short SQLite transactions, independent of consumers.
Delivery is explicitly acknowledged; an ambiguous delivery is never auto-retried.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
import uuid


class BusError(ValueError):
    """A safe, public error without credentials or database internals."""

    def __init__(self, message, code="invalid", status=400):
        super().__init__(message)
        self.code, self.status = code, status


class _ExpiredClaim(BusError):
    """Commit only the fail-closed uncertainty transition before returning 409."""


APPLICATION_ID = 0x53414342  # SACB: Skyrim Autotest Command Bus.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_EXPECTED_UNSET = object()


def external_path(value, name):
    """Refuse repository/runtime aliases before resolving or creating any path."""
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise BusError(f"{name} must be an absolute external path")
    supplied = Path(value)
    for candidate in (supplied, *supplied.parents):
        try:
            info = candidate.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except (OSError, UnicodeError) as exc:
            raise BusError(f"Cannot inspect {name} path") from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BusError(f"{name} must not use symlinks or reparse-point ancestors")
    resolved = supplied.resolve()
    if resolved.is_relative_to(PACKAGE_ROOT):
        raise BusError(f"{name} must stay outside the source checkout or distribution")
    for parent in (resolved.parent, *resolved.parent.parents):
        try:
            (parent / ".git").lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except (OSError, UnicodeError) as exc:
            raise BusError(f"Cannot inspect {name} repository ancestry") from exc
        raise BusError(f"{name} must stay outside Git repositories")
    return resolved


def _channel_paths(config_path, data):
    config_path = external_path(config_path, "configuration")
    database = external_path(data["database"], "database")
    token = external_path(data["tokenFile"], "tokenFile")
    sidecars = {external_path(str(database) + suffix, "database sidecar") for suffix in ("-wal", "-shm", "-journal")}
    if token == database or config_path in {database, token} or token in sidecars or config_path in sidecars:
        raise BusError("Configuration, database, tokenFile and database sidecars must be distinct")
    return config_path


def _conflict(message):
    return BusError(message, "conflict", 409)


def _identifier(value, name):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise BusError(f"{name} must be a nonempty string of at most 200 characters")
    if value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise BusError(f"{name} contains whitespace or control characters")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise BusError(f"{name} must be valid Unicode") from exc
    return value


def _text(value, name="text", limit=32768):
    if not isinstance(value, str) or not value.strip():
        raise BusError(f"{name} must be nonempty text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise BusError(f"{name} must be valid Unicode") from exc
    if len(encoded) > limit or any(ord(c) < 32 and c not in "\r\n\t" for c in value):
        raise BusError(f"{name} exceeds its size limit or contains control characters")
    return value


def _json(value, limit=16384):
    def check(item, depth=0):
        if depth > 8:
            raise BusError("JSON nesting exceeds eight levels")
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float) and math.isfinite(item):
            return
        if isinstance(item, list):
            for child in item:
                check(child, depth + 1)
            return
        if isinstance(item, dict) and all(isinstance(k, str) for k in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise BusError("Only finite JSON values are supported")
    check(value)
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(result.encode("utf-8")) > limit:
            raise BusError("JSON value exceeds its size limit")
        return result
    except (UnicodeError, ValueError) as exc:
        raise BusError("Invalid JSON value") from exc


def binding_value(binding):
    if not isinstance(binding, dict) or set(binding) != {"provider", "conversationId", "agentId"}:
        raise BusError("binding requires exactly provider, conversationId and agentId")
    return {key: _identifier(binding[key], key) for key in sorted(binding)}


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BusError("Duplicate JSON keys are forbidden")
            result[key] = value
        return result
    def constant(_):
        raise BusError("Nonfinite JSON values are forbidden")
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
        _json(value, limit=131072)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, BusError):
            raise
        raise BusError("Malformed JSON") from exc


class CommandBus:
    """One external SQLite database; connections are never shared across threads."""

    def __init__(self, database, claim_timeout=300, clock=time.time):
        self.database = external_path(database, "database")
        if isinstance(claim_timeout, bool) or not isinstance(claim_timeout, (int, float)) or not 5 <= claim_timeout <= 3600:
            raise BusError("claim timeout must be between 5 and 3600 seconds")
        self.claim_timeout, self.clock = claim_timeout, clock
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            application = con.execute("PRAGMA application_id").fetchone()[0]
            populated = con.execute("SELECT 1 FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone()
            if (version, application) != (1, APPLICATION_ID) and (version != 0 or application != 0 or populated):
                raise BusError("Refusing a foreign or unsupported command database")
            schema = """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, binding TEXT, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commands (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id), binding TEXT NOT NULL,
                    source_id TEXT NOT NULL, source_event_id TEXT NOT NULL, digest TEXT NOT NULL,
                    kind TEXT NOT NULL, text TEXT NOT NULL, priority TEXT NOT NULL,
                    metadata TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                    claim_id TEXT, claim_until REAL, result TEXT,
                    UNIQUE(source_id, source_event_id)
                );
                CREATE INDEX IF NOT EXISTS command_session_order ON commands(session_id, seq);
                CREATE TABLE IF NOT EXISTS outbox (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id), binding TEXT NOT NULL, command_id TEXT,
                    channel TEXT NOT NULL, source_event_id TEXT NOT NULL, digest TEXT NOT NULL,
                    text TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                    claim_id TEXT, consumer_id TEXT, claim_until REAL, result TEXT,
                    UNIQUE(session_id, channel, source_event_id)
                );
                CREATE INDEX IF NOT EXISTS outbox_session_order ON outbox(session_id, channel, seq);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    type TEXT NOT NULL, created REAL NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS event_session_order ON events(session_id, id);
                CREATE TABLE IF NOT EXISTS channel_metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """
            for statement in schema.split(";"):
                if statement.strip():
                    con.execute(statement)
            con.execute(f"PRAGMA application_id={APPLICATION_ID}")
            con.execute("INSERT OR IGNORE INTO channel_metadata(key,value) VALUES ('channelId',?)", (uuid.uuid4().hex,))
            self._identity(con)
        # Set persistent journal mode only after proving that this is our database.
        with closing(self._connect()) as con:
            con.execute("PRAGMA journal_mode=WAL")

    def _connect(self):
        con = sqlite3.connect(str(self.database), timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA busy_timeout=5000")
        return con

    @contextmanager
    def _transaction(self):
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except _ExpiredClaim:
            con.commit()
            raise
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _event(self, con, session, event_type, data):
        cursor = con.execute("INSERT INTO events(session_id,type,created,data) VALUES(?,?,?,?)",
                             (session, event_type, self.clock(), _json(data, 65536)))
        return cursor.lastrowid

    def _session(self, con, session_id, binding=None):
        _identifier(session_id, "sessionId")
        row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise BusError("Session does not exist", "not_found", 404)
        if binding is not None:
            expected = _json(binding_value(binding))
            if row["binding"] != expected:
                raise BusError("Agent binding does not match this session", "binding_mismatch", 403)
        return row

    @staticmethod
    def _command(row, include_claim=False):
        if row is None:
            return None
        result = {"id": row["id"], "sequence": row["seq"], "sessionId": row["session_id"],
                  "binding": json.loads(row["binding"]), "sourceId": row["source_id"],
                  "sourceEventId": row["source_event_id"], "digest": row["digest"],
                  "kind": row["kind"], "text": row["text"], "priority": row["priority"],
                  "metadata": json.loads(row["metadata"]), "state": row["state"], "createdAt": row["created"],
                  "result": json.loads(row["result"]) if row["result"] else None}
        if include_claim:
            result.update(claimId=row["claim_id"], claimUntil=row["claim_until"])
        return result

    @staticmethod
    def _outgoing(row, include_claim=False):
        result = {"id": row["id"], "sequence": row["seq"], "sessionId": row["session_id"],
                  "binding": json.loads(row["binding"]),
                  "commandId": row["command_id"], "channel": row["channel"],
                  "sourceEventId": row["source_event_id"], "digest": row["digest"], "text": row["text"],
                  "state": row["state"], "createdAt": row["created"],
                  "result": json.loads(row["result"]) if row["result"] else None}
        if include_claim:
            result.update(claimId=row["claim_id"], claimUntil=row["claim_until"], consumerId=row["consumer_id"])
        return result

    def create_session(self, sessionId):
        _identifier(sessionId, "sessionId")
        with self._transaction() as con:
            if con.execute("SELECT id FROM sessions WHERE id=?", (sessionId,)).fetchone() is None:
                con.execute("INSERT INTO sessions VALUES(?,NULL,?)", (sessionId, self.clock()))
                self._event(con, sessionId, "session.created", {})
        return {"sessionId": sessionId}

    def bind(self, sessionId, binding):
        value = _json(binding_value(binding))
        with self._transaction() as con:
            row = self._session(con, sessionId)
            if row["binding"] == value:
                return {"sessionId": sessionId, "binding": json.loads(value), "duplicate": True}
            if con.execute("SELECT id FROM commands WHERE session_id=? AND state!='completed' LIMIT 1", (sessionId,)).fetchone():
                raise _conflict("Cannot change binding while commands are unfinished")
            if con.execute("SELECT id FROM outbox WHERE session_id=? AND state!='completed' LIMIT 1", (sessionId,)).fetchone():
                raise _conflict("Cannot change binding while outbound delivery is unfinished")
            con.execute("UPDATE sessions SET binding=? WHERE id=?", (value, sessionId))
            self._event(con, sessionId, "session.bound", {"binding": json.loads(value)})
        return {"sessionId": sessionId, "binding": json.loads(value), "duplicate": False}

    def submit(self, sessionId, sourceId, sourceEventId, kind, text, priority="normal", metadata=None,
               expectedBinding=_EXPECTED_UNSET):
        _identifier(sourceId, "sourceId")
        _identifier(sourceEventId, "sourceEventId")
        _text(text)
        if kind not in ("text", "asr.final"):
            raise BusError("kind must be text or asr.final; provisional ASR is forbidden")
        if priority not in ("normal", "stop", "cancel"):
            raise BusError("priority must be normal, stop or cancel")
        metadata = {} if metadata is None else metadata
        if not isinstance(metadata, dict):
            raise BusError("metadata must be an object")
        metadata_json = _json(metadata)
        content = {"sessionId": sessionId, "sourceId": sourceId, "sourceEventId": sourceEventId,
                   "kind": kind, "text": text, "priority": priority, "metadata": metadata}
        expected_json = None
        if expectedBinding is not _EXPECTED_UNSET:
            content["expectedBinding"] = binding_value(expectedBinding)
            expected_json = _json(content["expectedBinding"])
        digest = hashlib.sha256(_json(content, 65536).encode("utf-8")).hexdigest()
        with self._transaction() as con:
            session = self._session(con, sessionId)
            old = con.execute("SELECT * FROM commands WHERE source_id=? AND source_event_id=?", (sourceId, sourceEventId)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise _conflict("Source event id was already used with different immutable content")
                if expected_json is not None and old["binding"] != expected_json:
                    raise _conflict("Original command target does not match expectedBinding")
                return {"command": self._command(old), "duplicate": True, "acknowledged": True}
            if session["binding"] is None:
                raise _conflict("Bind a specific agent before accepting commands")
            if expected_json is not None and session["binding"] != expected_json:
                raise _conflict("Session binding changed before ingress; expectedBinding does not match")
            item_id = uuid.uuid4().hex
            con.execute("""INSERT INTO commands(id,session_id,binding,source_id,source_event_id,digest,
                           kind,text,priority,metadata,state,created) VALUES(?,?,?,?,?,?,?,?,?,?,'received',?)""",
                        (item_id, sessionId, session["binding"], sourceId, sourceEventId, digest,
                         kind, text, priority, metadata_json, self.clock()))
            self._event(con, sessionId, "command.received", {"commandId": item_id, "sourceId": sourceId,
                        "sourceEventId": sourceEventId, "digest": digest, "priority": priority})
            row = con.execute("SELECT * FROM commands WHERE id=?", (item_id,)).fetchone()
            result = {"command": self._command(row), "duplicate": False, "acknowledged": True}
        return result

    def _expire(self, con, table, sessionId, channel=None):
        clause = "session_id=? AND state IN ('claimed','delivered') AND claim_until<=?"
        params = [sessionId, self.clock()]
        if channel is not None:
            clause += " AND channel=?"
            params.append(channel)
        rows = con.execute(f"SELECT id FROM {table} WHERE {clause}", params).fetchall()
        for row in rows:
            con.execute(f"UPDATE {table} SET state='uncertain' WHERE id=?", (row["id"],))
            self._event(con, sessionId, "command.uncertain" if table == "commands" else "outbox.uncertain",
                        {"id": row["id"], "reason": "claim_expired; delivery must be reconciled explicitly"})

    def next(self, sessionId, binding, *, reviewOf=None):
        # Internal executor review lane. It never reconciles or reclaims an
        # uncertain row. The caller must admit only reads/finish while held.
        if reviewOf is not None:
            if (type(reviewOf) is not list or not reviewOf or len(reviewOf) > 128 or
                    len(set(reviewOf)) != len(reviewOf)):
                raise BusError("reviewOf requires unique prior uncertain command ids")
            for item in reviewOf:
                _identifier(item, "reviewOf commandId")
        with self._transaction() as con:
            session = self._session(con, sessionId, binding)
            self._expire(con, "commands", sessionId)
            if reviewOf is not None:
                rows = con.execute("SELECT * FROM commands WHERE session_id=? ORDER BY seq", (sessionId,)).fetchall()
                for item in reviewOf:
                    prior = next((row for row in rows if row['id'] == item), None)
                    if (prior is None or prior['binding'] != session['binding'] or
                            prior['state'] not in ('uncertain', 'completed')):
                        return {"command": None, "blocked": {"id": item, "state": "review-binding-changed"}}
                row = next((row for row in rows if row['state'] != 'completed' and row['id'] not in reviewOf), None)
            else:
                row = con.execute("SELECT * FROM commands WHERE session_id=? AND state!='completed' ORDER BY seq LIMIT 1", (sessionId,)).fetchone()
            if row is None:
                return {"command": None, "blocked": None}
            if row["state"] != "received":
                return {"command": None, "blocked": {"id": row["id"], "state": row["state"]}}
            if row["binding"] != session["binding"]:
                raise _conflict("Command target does not match the session binding")
            claim = uuid.uuid4().hex
            con.execute("UPDATE commands SET state='claimed',claim_id=?,claim_until=? WHERE id=?",
                        (claim, self.clock() + self.claim_timeout, row["id"]))
            self._event(con, sessionId, "command.claimed", {"commandId": row["id"], "binding": binding_value(binding)})
            if reviewOf is not None:
                self._event(con, sessionId, "command.review-claimed", {"commandId": row['id'], "reviewOf": reviewOf})
            return {"command": self._command(con.execute("SELECT * FROM commands WHERE id=?", (row["id"],)).fetchone(), True), "blocked": None}

    def _claimed(self, con, sessionId, commandId, claimId, binding):
        self._session(con, sessionId, binding)
        _identifier(commandId, "commandId")
        _identifier(claimId, "claimId")
        row = con.execute("SELECT * FROM commands WHERE id=? AND session_id=?", (commandId, sessionId)).fetchone()
        if row is None:
            raise BusError("Command does not exist in this session", "not_found", 404)
        if row["claim_id"] != claimId or row["binding"] != _json(binding_value(binding)):
            raise _conflict("Command claim does not match")
        if row["state"] in ("claimed", "delivered") and row["claim_until"] <= self.clock():
            con.execute("UPDATE commands SET state='uncertain' WHERE id=?", (commandId,))
            self._event(con, sessionId, "command.uncertain", {"id": commandId, "reason": "claim_expired; delivery must be reconciled explicitly"})
            raise _ExpiredClaim("Expired command claim is uncertain and requires reconciliation", "conflict", 409)
        return row

    def delivered(self, sessionId, commandId, claimId, binding):
        with self._transaction() as con:
            row = self._claimed(con, sessionId, commandId, claimId, binding)
            if row["state"] == "delivered":
                return {"command": self._command(row), "duplicate": True}
            if row["state"] != "claimed":
                raise _conflict("Only a currently claimed command can be marked delivered")
            con.execute("UPDATE commands SET state='delivered' WHERE id=?", (commandId,))
            self._event(con, sessionId, "command.delivered", {"commandId": commandId})
            return {"command": self._command(con.execute("SELECT * FROM commands WHERE id=?", (commandId,)).fetchone()), "duplicate": False}

    def renew(self, sessionId, commandId, claimId, binding):
        with self._transaction() as con:
            row = self._claimed(con, sessionId, commandId, claimId, binding)
            if row["state"] not in ("claimed", "delivered"):
                raise _conflict("Only an active claim can be renewed")
            if row["claim_until"] <= self.clock():
                self._expire(con, "commands", sessionId)
                expired = True
            else:
                until = self.clock() + self.claim_timeout
                con.execute("UPDATE commands SET claim_until=? WHERE id=?", (until, commandId))
                expired = False
        if expired:
            raise _conflict("Expired claim is uncertain and requires explicit reconciliation")
        return {"commandId": commandId, "claimUntil": until}

    def complete(self, sessionId, commandId, claimId, binding, result=None):
        value = _json({} if result is None else result)
        with self._transaction() as con:
            row = self._claimed(con, sessionId, commandId, claimId, binding)
            if row["state"] == "completed":
                if row["result"] != value:
                    raise _conflict("Completion was already recorded with another result")
                return {"command": self._command(row), "duplicate": True}
            if row["state"] != "delivered":
                raise _conflict("Record delivery before completion; reconcile uncertain delivery explicitly")
            con.execute("UPDATE commands SET state='completed',result=? WHERE id=?", (value, commandId))
            self._event(con, sessionId, "command.completed", {"commandId": commandId, "result": json.loads(value)})
            return {"command": self._command(con.execute("SELECT * FROM commands WHERE id=?", (commandId,)).fetchone()), "duplicate": False}

    def reconcile(self, sessionId, commandId, binding, disposition, note, result=None):
        _text(note, "note", 4096)
        if disposition not in ("uncertain", "not_delivered", "completed", "abandoned"):
            raise BusError("disposition must be uncertain, not_delivered, completed or abandoned")
        value = _json({} if result is None else result)
        with self._transaction() as con:
            self._session(con, sessionId, binding)
            row = con.execute("SELECT * FROM commands WHERE id=? AND session_id=?", (commandId, sessionId)).fetchone()
            if row is None:
                raise BusError("Command does not exist in this session", "not_found", 404)
            if disposition == "uncertain":
                if row["state"] not in ("claimed", "delivered", "uncertain"):
                    raise _conflict("Only an active delivery can become uncertain")
                state = "uncertain"
            else:
                if row["state"] != "uncertain":
                    raise _conflict("Only an uncertain command can be reconciled")
                state = "received" if disposition == "not_delivered" else "completed"
            if disposition == "abandoned":
                value = _json({"outcome": "abandoned", "note": note})
            clear_claim = state == "received"
            con.execute("UPDATE commands SET state=?, result=?, claim_id=?, claim_until=? WHERE id=?",
                        (state, value if state == "completed" else None,
                         None if clear_claim else row["claim_id"], None if clear_claim else row["claim_until"], commandId))
            self._event(con, sessionId, "command.reconciled", {"commandId": commandId, "disposition": disposition, "note": note})
            return {"command": self._command(con.execute("SELECT * FROM commands WHERE id=?", (commandId,)).fetchone())}

    def _enqueue_outbox(self, con, sessionId, channel, sourceEventId, text, commandId):
        _identifier(sourceEventId, "sourceEventId")
        _text(text)
        digest = hashlib.sha256(_json({"sessionId": sessionId, "channel": channel, "sourceEventId": sourceEventId,
                                      "text": text, "commandId": commandId}, 65536).encode("utf-8")).hexdigest()
        row = con.execute("SELECT * FROM outbox WHERE session_id=? AND channel=? AND source_event_id=?",
                          (sessionId, channel, sourceEventId)).fetchone()
        if row:
            if row["digest"] != digest:
                raise _conflict("Outbox event id was already used with different immutable content")
            return {"item": self._outgoing(row), "duplicate": True}
        item_id = uuid.uuid4().hex
        binding = self._session(con, sessionId)["binding"]
        con.execute("""INSERT INTO outbox(id,session_id,binding,command_id,channel,source_event_id,digest,text,state,created)
                       VALUES(?,?,?,?,?,?,?,?,'pending',?)""", (item_id, sessionId, binding, commandId, channel, sourceEventId, digest, text, self.clock()))
        self._event(con, sessionId, "speech.requested" if channel == "speech" else "response.created",
                    {"outboxId": item_id, "commandId": commandId, "binding": json.loads(binding), "text": text, "digest": digest})
        return {"item": self._outgoing(con.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()), "duplicate": False}

    def respond(self, sessionId, commandId, claimId, binding, sourceEventId, text):
        with self._transaction() as con:
            row = self._claimed(con, sessionId, commandId, claimId, binding)
            if row["state"] not in ("delivered", "completed"):
                raise _conflict("Responses require a delivered command")
            return self._enqueue_outbox(con, sessionId, "response", sourceEventId, text, commandId)

    def speech(self, sessionId, binding, sourceEventId, text, commandId=None):
        with self._transaction() as con:
            self._session(con, sessionId, binding)
            if commandId is not None and not con.execute("SELECT id FROM commands WHERE id=? AND session_id=?", (commandId, sessionId)).fetchone():
                raise BusError("Command does not exist in this session", "not_found", 404)
            return self._enqueue_outbox(con, sessionId, "speech", sourceEventId, text, commandId)

    def outbox_next(self, sessionId, channel, consumerId):
        _identifier(consumerId, "consumerId")
        if channel not in ("speech", "response"):
            raise BusError("channel must be speech or response")
        with self._transaction() as con:
            self._session(con, sessionId)
            self._expire(con, "outbox", sessionId, channel)
            row = con.execute("SELECT * FROM outbox WHERE session_id=? AND channel=? AND state!='completed' ORDER BY seq LIMIT 1", (sessionId, channel)).fetchone()
            if row is None:
                return {"item": None, "blocked": None}
            if row["state"] != "pending":
                return {"item": None, "blocked": {"id": row["id"], "state": row["state"]}}
            claim = uuid.uuid4().hex
            con.execute("UPDATE outbox SET state='claimed',claim_id=?,consumer_id=?,claim_until=? WHERE id=?",
                        (claim, consumerId, self.clock() + self.claim_timeout, row["id"]))
            self._event(con, sessionId, "outbox.claimed", {"outboxId": row["id"], "channel": channel, "consumerId": consumerId})
            return {"item": self._outgoing(con.execute("SELECT * FROM outbox WHERE id=?", (row["id"],)).fetchone(), True), "blocked": None}

    def outbox_complete(self, sessionId, outboxId, claimId, consumerId, result=None):
        value = _json({} if result is None else result)
        with self._transaction() as con:
            row = self._claimed_outbox(con, sessionId, outboxId, claimId, consumerId)
            if row["state"] == "completed":
                if row["result"] != value:
                    raise _conflict("Outbox completion already has another result")
                return {"item": self._outgoing(row), "duplicate": True}
            if row["state"] != "delivered":
                raise _conflict("Record outbound delivery before completion; reconcile uncertainty explicitly")
            con.execute("UPDATE outbox SET state='completed',result=? WHERE id=?", (value, outboxId))
            self._event(con, sessionId, "outbox.completed", {"outboxId": outboxId, "consumerId": consumerId, "result": json.loads(value)})
            return {"item": self._outgoing(con.execute("SELECT * FROM outbox WHERE id=?", (outboxId,)).fetchone()), "duplicate": False}

    def _claimed_outbox(self, con, sessionId, outboxId, claimId, consumerId):
        self._session(con, sessionId)
        for value, name in ((outboxId, "outboxId"), (claimId, "claimId"), (consumerId, "consumerId")):
            _identifier(value, name)
        row = con.execute("SELECT * FROM outbox WHERE id=? AND session_id=?", (outboxId, sessionId)).fetchone()
        if row is None:
            raise BusError("Outbox item does not exist in this session", "not_found", 404)
        if row["claim_id"] != claimId or row["consumer_id"] != consumerId:
            raise _conflict("Outbox claim does not match")
        if row["state"] in ("claimed", "delivered") and row["claim_until"] <= self.clock():
            con.execute("UPDATE outbox SET state='uncertain' WHERE id=?", (outboxId,))
            self._event(con, sessionId, "outbox.uncertain", {"id": outboxId, "reason": "claim_expired; delivery must be reconciled explicitly"})
            raise _ExpiredClaim("Expired outbox claim is uncertain and requires reconciliation", "conflict", 409)
        return row

    def outbox_delivered(self, sessionId, outboxId, claimId, consumerId):
        with self._transaction() as con:
            row = self._claimed_outbox(con, sessionId, outboxId, claimId, consumerId)
            if row["state"] == "delivered":
                return {"item": self._outgoing(row), "duplicate": True}
            if row["state"] != "claimed":
                raise _conflict("Only a currently claimed outbox item can be marked delivered")
            con.execute("UPDATE outbox SET state='delivered' WHERE id=?", (outboxId,))
            self._event(con, sessionId, "outbox.delivered", {"outboxId": outboxId, "consumerId": consumerId})
            return {"item": self._outgoing(con.execute("SELECT * FROM outbox WHERE id=?", (outboxId,)).fetchone()), "duplicate": False}

    def outbox_renew(self, sessionId, outboxId, claimId, consumerId):
        with self._transaction() as con:
            row = self._claimed_outbox(con, sessionId, outboxId, claimId, consumerId)
            if row["state"] not in ("claimed", "delivered"):
                raise _conflict("Only an active outbox claim can be renewed")
            if row["claim_until"] <= self.clock():
                self._expire(con, "outbox", sessionId, row["channel"])
                expired = True
            else:
                until = self.clock() + self.claim_timeout
                con.execute("UPDATE outbox SET claim_until=? WHERE id=?", (until, outboxId))
                expired = False
        if expired:
            raise _conflict("Expired outbox claim is uncertain and requires reconciliation")
        return {"outboxId": outboxId, "claimUntil": until}

    def outbox_reconcile(self, sessionId, outboxId, disposition, note):
        _text(note, "note", 4096)
        if disposition not in ("uncertain", "not_delivered", "completed", "abandoned"):
            raise BusError("Invalid outbox disposition")
        with self._transaction() as con:
            self._session(con, sessionId)
            row = con.execute("SELECT * FROM outbox WHERE id=? AND session_id=?", (outboxId, sessionId)).fetchone()
            if row is None:
                raise BusError("Outbox item does not exist in this session", "not_found", 404)
            if disposition == "uncertain":
                if row["state"] not in ("claimed", "delivered", "uncertain"):
                    raise _conflict("Only an active outbox delivery can become uncertain")
                state = "uncertain"
            else:
                if row["state"] != "uncertain":
                    raise _conflict("Only an uncertain outbox item can be reconciled")
                state = "pending" if disposition == "not_delivered" else "completed"
            con.execute("UPDATE outbox SET state=?,claim_id=NULL,consumer_id=NULL,claim_until=NULL,result=? WHERE id=?",
                        (state, _json({"reconciled": disposition, "note": note}) if state == "completed" else None, outboxId))
            self._event(con, sessionId, "outbox.reconciled", {"outboxId": outboxId, "disposition": disposition, "note": note})
            return {"item": self._outgoing(con.execute("SELECT * FROM outbox WHERE id=?", (outboxId,)).fetchone())}

    def events(self, sessionId, afterId=0, limit=100):
        if type(afterId) is not int or afterId < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise BusError("afterId must be a nonnegative integer and limit an integer in 1..500")
        with closing(self._connect()) as con:
            self._session(con, sessionId)
            rows = con.execute("SELECT * FROM events WHERE session_id=? AND id>? ORDER BY id LIMIT ?", (sessionId, afterId, limit)).fetchall()
            return {"events": [{"id": r["id"], "sessionId": r["session_id"], "type": r["type"], "createdAt": r["created"],
                                "data": json.loads(r["data"])} for r in rows],
                    "nextAfterId": rows[-1]["id"] if rows else afterId}

    def _identity(self, con):
        row = con.execute("SELECT value FROM channel_metadata WHERE key='channelId'").fetchone()
        if row is None or not isinstance(row["value"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["value"]):
            raise BusError("Command channel identity is invalid")
        location = os.path.normcase(str(self.database.resolve()))
        return {"schemaVersion": 1, "channelId": row["value"],
                "databaseLocationSha256": hashlib.sha256(location.encode('utf-8')).hexdigest()}

    def identity(self):
        """Read the durable channel identity without changing session/queue state."""
        with closing(self._connect()) as con:
            return self._identity(con)

    def status(self, sessionId=None):
        with closing(self._connect()) as con:
            if sessionId is None:
                return {"schemaVersion": 1, "sessions": [{"sessionId": r["id"], "binding": json.loads(r["binding"]) if r["binding"] else None}
                        for r in con.execute("SELECT * FROM sessions ORDER BY created,id")]}
            session = self._session(con, sessionId)
            return {"sessionId": sessionId, "binding": json.loads(session["binding"]) if session["binding"] else None,
                    "commands": {r["state"]: r["n"] for r in con.execute("SELECT state,count(*) n FROM commands WHERE session_id=? GROUP BY state", (sessionId,))},
                    "outbox": [{"channel": r["channel"], "state": r["state"], "count": r["n"]} for r in con.execute("SELECT channel,state,count(*) n FROM outbox WHERE session_id=? GROUP BY channel,state", (sessionId,))]}


# One strict dispatch contract shared by HTTP, CLI JSON calls and the stdio bridge.
OPERATIONS = {
    "identity": ("identity", (), ()),
    "sessions": ("create_session", ("sessionId",), ()),
    "bind": ("bind", ("sessionId", "binding"), ()),
    "submit": ("submit", ("sessionId", "sourceId", "sourceEventId", "kind", "text"), ("priority", "metadata", "expectedBinding")),
    "next": ("next", ("sessionId", "binding"), ()),
    "delivered": ("delivered", ("sessionId", "commandId", "claimId", "binding"), ()),
    "renew": ("renew", ("sessionId", "commandId", "claimId", "binding"), ()),
    "complete": ("complete", ("sessionId", "commandId", "claimId", "binding"), ("result",)),
    "reconcile": ("reconcile", ("sessionId", "commandId", "binding", "disposition", "note"), ("result",)),
    "respond": ("respond", ("sessionId", "commandId", "claimId", "binding", "sourceEventId", "text"), ()),
    "speech": ("speech", ("sessionId", "binding", "sourceEventId", "text"), ("commandId",)),
    "outbox-next": ("outbox_next", ("sessionId", "channel", "consumerId"), ()),
    "outbox-delivered": ("outbox_delivered", ("sessionId", "outboxId", "claimId", "consumerId"), ()),
    "outbox-renew": ("outbox_renew", ("sessionId", "outboxId", "claimId", "consumerId"), ()),
    "outbox-complete": ("outbox_complete", ("sessionId", "outboxId", "claimId", "consumerId"), ("result",)),
    "outbox-reconcile": ("outbox_reconcile", ("sessionId", "outboxId", "disposition", "note"), ()),
    "events": ("events", ("sessionId",), ("afterId", "limit")),
    "status": ("status", (), ("sessionId",)),
}


def dispatch(bus, operation, arguments):
    if operation not in OPERATIONS:
        raise BusError("Unknown operation", "not_found", 404)
    method, required, optional = OPERATIONS[operation]
    if not isinstance(arguments, dict) or not set(required) <= set(arguments) or set(arguments) - set(required) - set(optional):
        raise BusError("Operation arguments have missing or unknown fields")
    try:
        return getattr(bus, method)(**arguments)
    except (TypeError, OverflowError, sqlite3.InterfaceError, sqlite3.ProgrammingError) as exc:
        raise BusError("Operation argument type is invalid") from exc


def load_config(path):
    path = external_path(path, "configuration")
    try:
        data = strict_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise BusError("Cannot read command channel configuration") from exc
    allowed = {"schemaVersion", "database", "tokenFile", "host", "port", "maxRequestBytes", "claimTimeoutSeconds"}
    if not isinstance(data, dict) or set(data) - allowed or not {"schemaVersion", "database", "tokenFile"} <= set(data):
        raise BusError("Invalid command channel configuration fields")
    if type(data["schemaVersion"]) is not int or data["schemaVersion"] != 1:
        raise BusError("Unsupported command channel configuration version")
    for key in ("database", "tokenFile"):
        if not isinstance(data[key], str):
            raise BusError(f"{key} must be an absolute external path")
    _channel_paths(path, data)
    if data.get("host", "127.0.0.1") != "127.0.0.1":
        raise BusError("Only the literal loopback host 127.0.0.1 is supported")
    for key, default, lower, upper in (("port", 8767, 1, 65535), ("maxRequestBytes", 65536, 1024, 131072),
                                       ("claimTimeoutSeconds", 300, 5, 3600)):
        value = data.get(key, default)
        if type(value) is not int or not lower <= value <= upper:
            raise BusError(f"Invalid {key}")
        data[key] = value
    data["host"] = "127.0.0.1"
    return data


def read_token(config):
    try:
        with open(config["tokenFile"], "rb") as stream:
            raw = stream.read(513)
        token = raw.decode("ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise BusError("Cannot read command channel token file") from exc
    if len(raw) > 512 or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise BusError("Token must contain 32..256 ASCII URL-safe characters")
    return token


def initialize(config_path, session_id=None):
    config_path = external_path(config_path, "configuration")
    if not config_path.exists():
        data = {"schemaVersion": 1, "database": str(config_path.parent / "commands.sqlite3"),
                "tokenFile": str(config_path.parent / "command-channel.token"), "host": "127.0.0.1", "port": 8767,
                "maxRequestBytes": 65536, "claimTimeoutSeconds": 300}
        _channel_paths(config_path, data)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
    config = load_config(config_path)
    token_path = Path(config["tokenFile"])
    token_path.parent.mkdir(parents=True, exist_ok=True)
    if not token_path.exists():
        fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(secrets.token_urlsafe(32) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    read_token(config)
    bus = CommandBus(config["database"], config["claimTimeoutSeconds"])
    if session_id:
        bus.create_session(session_id)
    return {"config": str(config_path), "sessionId": session_id, "status": bus.status(session_id)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Durable text/final-ASR channel; never executes game actions")
    parser.add_argument("--config", required=True, help="External command-channel.json")
    sub = parser.add_subparsers(dest="operation", required=True)
    init = sub.add_parser("init")
    init.add_argument("--session")
    serve = sub.add_parser("serve")
    serve.add_argument("--ready-file", help="Optional external startup receipt, containing no token")
    sub.add_parser("mcp", help="Serve the minimal stdio MCP bridge")
    for operation in OPERATIONS:
        command = sub.add_parser(operation)
        command.add_argument("--json", default="{}", help="Exact operation JSON object; never put a token here")
        command.add_argument("--json-file", help="Read arguments from an external UTF-8 file")
    args = parser.parse_args(argv)
    try:
        if args.operation == "init":
            result = initialize(args.config, args.session)
        elif args.operation == "serve":
            from .command_bus_http import serve
            serve(args.config, args.ready_file)
            return 0
        elif args.operation == "mcp":
            from .command_bus_mcp import serve_stdio
            serve_stdio(args.config)
            return 0
        else:
            config = load_config(args.config)
            raw = Path(args.json_file).read_text(encoding="utf-8") if args.json_file else args.json
            result = dispatch(CommandBus(config["database"], config["claimTimeoutSeconds"]), args.operation, strict_json(raw))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (BusError, OSError, UnicodeError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, BusError) else "Command channel storage or startup failure",
                          "code": exc.code if isinstance(exc, BusError) else "unavailable"}), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
