"""Durable, private ASR delivery for an active or periodically woken assisted chat.

This module never starts an AI turn, microphone or game. The host's supported
bridge/heartbeat must invoke claim, process the speech, then acknowledge it. A claim
is delivery evidence, not proof of a reply or permission to repeat an action.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def atomic(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "consumer.lock").open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def records(path):
    """An incomplete final append waits; malformed complete data never gets skipped."""
    data = path.read_bytes()
    complete = data[:data.rfind(b"\n") + 1]
    result = []
    for line in complete.splitlines():
        if not line.strip():
            raise ValueError("Blank record in ASR queue")
        row = json.loads(line.decode("utf-8"))
        if (type(row.get("seq")) is not int or row["seq"] < 1
                or not isinstance(row.get("text"), str) or not row["text"].strip()
                or not isinstance(row.get("at"), str)):
            raise ValueError("Invalid ASR record")
        if result and row["seq"] != result[-1]["seq"] + 1:
            raise ValueError("ASR queue has a duplicate or gap")
        result.append(row)
    return result


class Inbox:
    def __init__(self, folder, thread):
        self.folder = Path(folder).resolve()
        self.thread = str(uuid.UUID(thread))
        self.path = self.folder / "state.json"

    def state(self):
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if state["threadId"] != self.thread:
            raise ValueError("Inbox belongs to another chat")
        return state

    def init(self, heard, after):
        if after < 0:
            raise ValueError("Baseline cannot be negative")
        heard = Path(heard).resolve()
        with locked(self.folder):
            if self.path.exists():
                state = self.state()
                if state["heard"] != str(heard):
                    raise ValueError("Existing inbox uses another queue")
                return {"status": "already_initialized", "cursor": state["cursor"]}
            rows = records(heard)
            baseline = next((r for r in rows if r["seq"] == after), None)
            if after and baseline is None:
                raise ValueError("Baseline record missing")
            atomic(self.path, {"schemaVersion": 1, "threadId": self.thread,
                              "heard": str(heard), "cursor": after,
                              "anchor": digest(baseline) if baseline else None,
                              "pending": None, "acks": [], "startedAt": time.time()})
            return {"status": "initialized", "cursor": after}

    def claim(self):
        with locked(self.folder):
            state = self.state()
            rows = records(Path(state["heard"]))
            if state["cursor"]:
                anchor = next((r for r in rows if r["seq"] == state["cursor"]), None)
                if anchor is None or digest(anchor) != state["anchor"]:
                    raise ValueError("Queue reset/rewrite: explicit reconciliation required")
            pending = state["pending"]
            if pending:
                current = [r for r in rows if pending["firstSeq"] <= r["seq"] <= pending["lastSeq"]]
                if digest(current) != pending["recordsSha256"]:
                    raise ValueError("Pending speech changed")
                # Never silently retry a game mutation after an uncertain prior response.
                return {"status": "pending_review", **pending}
            fresh = [r for r in rows if r["seq"] > state["cursor"]][:64]
            if not fresh:
                return {"status": "quiet", "cursor": state["cursor"]}
            if fresh[0]["seq"] != state["cursor"] + 1:
                raise ValueError("Next speech sequence missing")
            pending = {"id": uuid.uuid4().hex, "threadId": self.thread,
                       "firstSeq": fresh[0]["seq"], "lastSeq": fresh[-1]["seq"],
                       "recordsSha256": digest(fresh), "records": fresh,
                       "claimedAt": time.time()}
            state["pending"] = pending
            atomic(self.path, state)
            return {"status": "claimed", **pending}

    def ack(self, claim_id, records_hash, response_ref):
        if not response_ref.strip():
            raise ValueError("Processing/reply reference required")
        with locked(self.folder):
            state = self.state()
            previous = next((r for r in state["acks"] if r["id"] == claim_id), None)
            if previous:
                if previous["recordsSha256"] != records_hash or previous["responseRef"] != response_ref:
                    raise ValueError("Conflicting acknowledgment")
                return {"status": "already_acknowledged", "cursor": state["cursor"]}
            pending = state["pending"]
            if not pending or pending["id"] != claim_id or pending["recordsSha256"] != records_hash:
                raise ValueError("Acknowledgment does not match pending speech")
            rows = records(Path(state["heard"]))
            current = [r for r in rows if pending["firstSeq"] <= r["seq"] <= pending["lastSeq"]]
            if digest(current) != records_hash:
                raise ValueError("Speech changed before acknowledgment")
            state["cursor"] = pending["lastSeq"]
            state["anchor"] = digest(current[-1])
            state["acks"].append({k: v for k, v in pending.items() if k != "records"})
            state["acks"][-1].update(responseRef=response_ref, acknowledgedAt=time.time())
            state["pending"] = None
            atomic(self.path, state)
            return {"status": "acknowledged", "cursor": state["cursor"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--thread", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--heard", type=Path, required=True)
    init.add_argument("--after", type=int, required=True)
    claim = commands.add_parser("claim")
    claim.add_argument("--wait", type=float, default=0,
                       help="Wait up to 30 seconds, returning immediately on new speech")
    ack = commands.add_parser("ack")
    ack.add_argument("--id", required=True)
    ack.add_argument("--sha256", required=True)
    ack.add_argument("--response-ref", required=True)
    args = parser.parse_args(argv)
    try:
        box = Inbox(args.inbox, args.thread)
        if args.command == "init":
            result = box.init(args.heard, args.after)
        elif args.command == "claim":
            if not 0 <= args.wait <= 30:
                raise ValueError("Wait must be between 0 and 30 seconds")
            deadline = time.monotonic() + args.wait
            while True:
                result = box.claim()
                if result["status"] != "quiet" or time.monotonic() >= deadline:
                    break
                time.sleep(min(.25, max(0, deadline - time.monotonic())))
        else:
            result = box.ack(args.id, args.sha256, args.response_ref)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
