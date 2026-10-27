# Durable text and voice command channel

Authenticated `identity` (POST `/v1/identity` with `{}`) returns schemaVersion1
and the persistent opaque `channelId` of this command database, plus
`databaseLocationSha256`: the SHA256 of its canonical, case-normalized absolute
database path. A copy retaining the same UUID at another path cannot identify
the selected local database. The actual path is not returned. This operation reads no
queue contents and changes no session/delivery state. Existing owned schema1
databases acquire this metadata without changing their queues or ownership
guards. The HTTP client, CLI and stdio bridge share this operation. The identity
is a database/channel identifier, not a credential. An older receiver without
this operation cannot be adopted by an explicitly managed held run; see
[interactive endpoint ownership](interactive-session.md).

The command channel receives text and **final** ASR into an external SQLite inbox,
including while the bound AI consumer is busy. It exposes the same operations through
Python, authenticated loopback HTTP, a CLI and an optional stdio MCP bridge. The bus
never interprets commands, starts games, executes game actions, opens a microphone,
transcribes audio, synthesizes speech or sends messages to another chat.

Sound is a separately connected application. It submits finalized transcripts and
consumes `speech.requested` output. Text responses use a separate response outbox.
Receipt, host delivery, first response, completion and actual sound playback are
distinct facts. An inbox ACK does not establish any of the later facts.

## External setup and persistent reception

Use a directory outside the source checkout, distribution and game/MO2 files. The
installed wheel makes the following module available from any working directory.
With an unpacked portable distribution, run the module from that distribution's
directory or use `python C:/Tools/skyrim-autotest/run.py --config C:/TestBench/channel/command-channel.json channel <operation>`.

```powershell
python -m skyrim_autotest.command_bus --config C:/TestBench/channel/command-channel.json init --session operator-session-1
```

Initialization is idempotent. It generates a random bearer token in a separate file
and creates a channel database. It prints no token. The resulting external config is:

```json
{
  "schemaVersion": 1,
  "database": "C:/TestBench/channel/commands.sqlite3",
  "tokenFile": "C:/TestBench/channel/command-channel.token",
  "host": "127.0.0.1",
  "port": 8767,
  "maxRequestBytes": 65536,
  "claimTimeoutSeconds": 300
}
```

Only the literal IPv4 loopback host is supported. Configuration, database, token and
ready-receipt paths must be absolute, outside Git repositories and the current source
checkout/distribution, and have no symlink or Windows reparse-point ancestors. Config,
token and database paths must be distinct, including SQLite's WAL/shared-memory/journal
sidecars. These checks run before initialization creates directories or files. Existing
invalid tokens are refused and preserved. Keep the directory private to the operating-system account;
Windows ACLs determine which other users can read it. The token file's creation mode
alone is not a Windows ACL guarantee. All adapters with this token have channel-wide
authority. This is a local trusted-adapter boundary, not per-adapter access control.
Direct Python/CLI/MCP access instead relies on the user's filesystem authority.

Bind the session to an explicit provider, conversation and agent. These are opaque
identifiers supplied by the real host; the bus does not discover or validate a vendor's
chat IDs. Store this JSON in an external UTF-8 `binding.json`:

```json
{
  "sessionId": "operator-session-1",
  "binding": {
    "provider": "your-host",
    "conversationId": "actual-conversation-id",
    "agentId": "actual-agent-id"
  }
}
```

```powershell
python -m skyrim_autotest.command_bus --config C:/TestBench/channel/command-channel.json bind --json-file C:/TestBench/channel/binding.json
```

Run the server in a separate persistent process. In PowerShell, for an installed wheel:

```powershell
$channelPython = (Get-Command python).Source
Start-Process -FilePath $channelPython -WindowStyle Hidden -ArgumentList @(
  '-m', 'skyrim_autotest.command_bus',
  '--config', 'C:/TestBench/channel/command-channel.json', 'serve',
  '--ready-file', 'C:/TestBench/channel/start-20261026-01.json'
)
```

Use a fresh absolute ready-file path per launch. An existing file is preserved and
startup refuses it. A ready receipt describes the bound listening socket at startup;
it can remain after process exit. Confirm current health with authenticated `status`,
not the old receipt. A port already in use also refuses startup. The server remains
independent of a consumer's task. Persistent reception lasts while this process runs;
no login service, watchdog, scheduled task or boot registration is installed.

## Producer helper: text or external final ASR

The stdlib client reads the external token file itself and never puts it in a URL or
command line. It connects directly to the exact loopback endpoint without redirects.

```python
from skyrim_autotest.command_bus_http import CommandHTTPClient

client = CommandHTTPClient("C:/TestBench/channel/command-channel.json")
ack = client.submit({
    "sessionId": "operator-session-1",
    "sourceId": "external-asr-installation-1",
    "sourceEventId": "persisted-final-segment-000042",
    "expectedBinding": {"provider": "your-host", "conversationId": "actual-conversation-id", "agentId": "actual-agent-id"},
    "kind": "asr.final",
    "text": "Report the current test state",
    "priority": "normal",
    "metadata": {"language": "en"}
})
assert ack["acknowledged"]
```

For typed input, use `kind: "text"` and a separate stable source namespace. The sound
adapter must decide that an utterance is final before submitting it. Partial,
provisional and interrupted utterances must not be submitted as `asr.final`; other ASR
kinds are rejected. The bus does not have audio with which to verify a producer's claim.

Persist the source event ID and exact payload **before** the first attempt, and retain
them across producer restarts. `(sourceId, sourceEventId)` is unique across the database,
including across sessions. A duplicate with identical canonical immutable content
returns the original command ID and `duplicate:true`. Changed session, text, kind,
priority or metadata under that same ID returns a conflict. Use a new event ID for a
new utterance; do not reset counters on restart.

Use optional `expectedBinding` when the producer pins an exact target agent. New
ingress checks it inside the same SQLite transaction as insertion; a rebind after
an earlier status read returns conflict without receiving a command for the new
agent. This target expectation joins immutable content only when supplied, keeping
legacy requests/digests unchanged when absent. An exact duplicate still returns
its original command and target after a later permitted rebind; it cannot deliver
new work. Explicit null or changed expectations are refused. The ASR forwarder
uses this atomic target check; the returned command exposes its target in `binding`.

The server commits with SQLite FULL synchronization before replying with an ACK.
`client.submit` retries transport loss or HTTP 503 at most three times by default,
using a frozen identical payload. A lost final ACK can be recovered later with the
same event ID. A response that was lost does not authorize a second logical command.
The generic `client.call` performs exactly one attempt and never retries delivery or
external actions. The tests exercise loss of the submit ACK after the database commit.
Durability still depends on the OS/storage honoring SQLite's synchronization; this
does not provide replication or protect against disk loss. Copying a live database
file without its WAL is not a supported backup method.

## Bound consumer and ordered mutation responsibility

An agent consumes only its exact binding:

```python
binding = {"provider": "your-host", "conversationId": "actual-conversation-id", "agentId": "actual-agent-id"}
session = "operator-session-1"
claimed = client.call("next", {"sessionId": session, "binding": binding})
command = claimed["command"]
if command is not None:
    receipt = {"sessionId": session, "binding": binding,
               "commandId": command["id"], "claimId": command["claimId"]}
    # Persist this claim in the host before acknowledging delivery.
    client.call("delivered", receipt)
    client.call("respond", dict(receipt, sourceEventId="reply-for-" + command["id"],
                                text="Received. Checking the requested state."))
    # Interpret within the owner's actual authorization and the host's serialized
    # action executor. No action is performed by this example or by the bus.
    client.call("complete", dict(receipt, result={"outcome": "received-by-example", "actionTaken": False}))
```

The state sequence is `received -> claimed -> delivered -> completed`. Only one
unfinished command can be claimed in each session. Commands remain in reception
sequence, including `stop`/`cancel` priority annotations. Those annotations never
interrupt a running mutation, bypass ordering or authorize game control. A host may
observe events and implement an authorized cooperative stop at its own safe boundary.
Multiple sessions do not provide a global game mutex; all actual game/file mutations
must still use the existing serialized executor and ownership/admission rules.

A claim is an exclusive delivery reservation, not a game-action lease. Persist the
claim before delivery, record `delivered` before acting, and renew it during long work
with `renew` using the same receipt. The timeout is 5..3600 seconds, default 300.
An expired active claim becomes `uncertain` when polled or used; expiry is durably
recorded before a stale operation is refused. A busy consumer does not hold a SQLite
transaction while it works, so producers can continue receiving durable ACKs.

The next command remains blocked by `claimed`, `delivered` or `uncertain` work. A
restart cannot silently reclaim an expired command. For an ambiguous host failure,
`reconcile` with `disposition:"uncertain"` and a factual `note` records the ambiguity.
Resolve an uncertain command only from evidence:

| Disposition | Meaning |
| --- | --- |
| `completed` | The exact result is known; store it in `result` and close the command. |
| `abandoned` | Close without executing/replaying it, retaining the reason. |
| `not_delivered` | Requeue the same command only after proving that delivery/action did not occur and stopping the old consumer. |

`not_delivered` invalidates the old claim. The bus cannot stop an external action
already running, prove a consumer has exited or make an external side effect atomic
with SQLite. Never choose it merely because a delivery ACK is missing. A command
whose delivery is uncertain is never automatically redelivered. Rebinding is refused
while commands **or outbound deliveries** remain unfinished. Old outbox records retain
their immutable target binding after a later permitted rebind.

## Response and speech outboxes

`respond` creates a durable `response.created` item, separately from command completion.
An actual host UI adapter claims the `response` channel and delivers it to the specified
target. Writing the outbox does not display a reply in an arbitrary chat.

The bound AI requests optional sound explicitly:

```python
client.call("speech", {"sessionId": session, "binding": binding,
                       "sourceEventId": "speech-for-command-000042",
                       "text": "The requested check is complete."})
```

This records `speech.requested`. A separately installed sound adapter uses the same
durable outbox claim protocol; the core supplies no microphone or synthesis backend:

```python
item = client.call("outbox-next", {"sessionId": session, "channel": "speech",
                                  "consumerId": "external-sound-adapter-1"})["item"]
if item is not None:
    assert item["binding"] == binding  # Verify the actual intended destination.
    receipt = {"sessionId": session, "outboxId": item["id"],
               "claimId": item["claimId"], "consumerId": "external-sound-adapter-1"}
    # Adapter persists its receipt first, then accepts responsibility for output.
    client.call("outbox-delivered", receipt)
    # The external adapter performs synthesis/playback once here, records its actual
    # outcome, and only then calls outbox-complete. This example plays no audio.
    client.call("outbox-complete", dict(receipt, result={"outcome": "example-only", "audioPlayed": False}))
```

Outbound states are `pending -> claimed -> delivered -> completed`. Acceptance by
the adapter is distinct from completed playback. Use `outbox-renew` during long
output. Both `speech` and `response` are independently ordered and exclusive per
session. Outbound event IDs are unique within `(sessionId, channel, sourceEventId)`;
changed immutable content conflicts. Stale claims become `uncertain`, block later
output and require `outbox-reconcile` with the same four dispositions and an evidence
note. Reading a replayed `speech.requested` event must not replay sound. Use its
outbox ID and claim state; preserve adapter receipts/cursors across restarts. An
output ACK that was lost may be repeated with the same claim and result, but sound
or UI side effects must not be blindly repeated. The bus cannot certify hardware
playback; the adapter's real evidence determines its reported result.

## Exact transport operations

All HTTP operations are `POST http://127.0.0.1:8767/v1/<operation>` with one
`Authorization: Bearer <token>` header, one `Content-Length` and JSON content type.
Only `GET /v1/status` is also supported. No query strings, redirects, CORS, browser
origins or transfer encoding are accepted. `Origin` and `Sec-Fetch-Site` requests
are refused even when they contain the token. The Host header must identify the
exact loopback endpoint. Token rotation requires restarting the server.

| Operation | Required JSON fields | Optional fields |
| --- | --- | --- |
| `sessions` | `sessionId` | — |
| `bind` | `sessionId`, `binding` | — |
| `submit` | `sessionId`, `sourceId`, `sourceEventId`, `kind`, `text` | `priority`, `metadata`, `expectedBinding` |
| `next` | `sessionId`, `binding` | — |
| `delivered`, `renew` | `sessionId`, `binding`, `commandId`, `claimId` | — |
| `complete` | same receipt | `result` |
| `respond` | same receipt, `sourceEventId`, `text` | — |
| `reconcile` | `sessionId`, `binding`, `commandId`, `disposition`, `note` | `result` |
| `speech` | `sessionId`, `binding`, `sourceEventId`, `text` | `commandId` |
| `outbox-next` | `sessionId`, `channel`, `consumerId` | — |
| `outbox-delivered`, `outbox-renew` | `sessionId`, `outboxId`, `claimId`, `consumerId` | — |
| `outbox-complete` | same outbound receipt | `result` |
| `outbox-reconcile` | `sessionId`, `outboxId`, `disposition`, `note` | — |
| `events` | `sessionId` | `afterId`, `limit` |
| `status` | — | `sessionId` |

Unknown fields, duplicate JSON keys, nonfinite numbers and excessive nesting are
rejected. Text is limited to 32768 UTF-8 bytes; metadata/results to 16384 bytes;
notes to 4096 bytes; identifiers to 200 characters without whitespace/control
characters. The HTTP request cap defaults to 65536 bytes and is bounded at 131072.
Workers are bounded at 32 with five-second socket timeouts.
For oversized-body rejection the server discards at most twice the configured
request cap within a 250ms budget, preventing an unread near-limit body from
resetting the 413 response on Windows. Excessively large or stalled senders are
then disconnected; there is no unbounded request drain.
Events are durable,
session-scoped and ordered by ID; `events` returns `nextAfterId`, for an external
persisted cursor, and at most 500 entries. Reading events neither acknowledges
delivery nor authorizes action. Inbox/outbox retention and disk monitoring are the
operator's responsibility; no automatic purge removes deduplication history.

Every operation is also available locally:

```powershell
python -m skyrim_autotest.command_bus --config C:/TestBench/channel/command-channel.json status
python -m skyrim_autotest.command_bus --config C:/TestBench/channel/command-channel.json submit --json-file C:/TestBench/channel/final-utterance.json
python -m skyrim_autotest.command_bus --config C:/TestBench/channel/command-channel.json next --json-file C:/TestBench/channel/binding.json
```

The local CLI bypasses HTTP and requires direct database access. It reads exact
operation JSON via `--json-file` or `--json`. Runtime files contain user commands
and replies; keep them and credentials outside Git. A foreign/nonempty SQLite
database is refused unless it carries this channel's application ID and schema
version. Do not point the channel at another application's database.

## Optional stdio MCP bridge and host responsibility

Configure a host capable of spawning an stdio server with this command/arguments:

```json
{
  "command": "python",
  "args": ["-m", "skyrim_autotest.command_bus", "--config", "C:/TestBench/channel/command-channel.json", "mcp"]
}
```

The server implements pinned MCP `2024-11-05` newline-delimited stdio,
`initialize`, `ping`, `tools/list` and `tools/call`. Tool names are `command_` plus
the operation, replacing hyphens with underscores: for example `command_submit`,
`command_next` and `command_outbox_delivered`. Tool schemas use the fields above.
It advertises tools only; no sampling, resources, subscriptions, pagination or
host-specific chat hooks are supplied. Notifications never execute bus mutations.
See the official pinned [lifecycle](https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle),
[transports](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports)
and [tools](https://modelcontextprotocol.io/specification/2024-11-05/server/tools)
contracts. Offline protocol tests do not establish acceptance by every AI client.

The host must poll/consume the channel during an active operator turn or provide
its own supported scheduling/event integration. Neither HTTP nor stdio can force
an arbitrary idle AI host to wake, interrupt an in-progress model response or
display an outbox reply automatically. The release supplies durable reception
and explicit APIs/instructions; actual host scheduling and external sound must
be connected and qualified separately. Historical voice sessions/listeners are
not migrated, restarted or routed through another developer chat.

## Offline verification

```powershell
python -m unittest discover -s tests -p "test_command_bus*.py" -q
```

Tests cover simultaneous producers/consumers, reception during a busy delivery,
restart/source deduplication, an abruptly exiting subprocess, lost submit ACK,
wrong binding/session/claim, changed immutable content, stale-claim refusal and
persisted uncertainty for every claim-consuming operation, separate text/speech
outboxes, explicit output delivery/completion, HTTP authentication/origin/Host/size
guards, safe ready-file handling, preservation of a foreign SQLite database and
stdio MCP framing/tools. No game, live microphone, synthesis or host wake is
exercised by these tests.
