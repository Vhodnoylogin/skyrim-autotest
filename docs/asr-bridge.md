# Connect an external final-ASR backend to the command channel

`asr-bridge` is a protocol adapter. It reads an existing external `heard.jsonl`
and submits validated final speech to the neutral command API. It never opens a
microphone, runs Whisper, reads a WAV/model, synthesizes sound, interprets a
phrase or performs a game action. Audio capture/ASR stays separately installed,
configured and started under its existing single-listener ownership.

The bridge runs independently of the AI host. It can keep receiving final
utterances while the operator is busy, and the durable bus retains them in
order. A queued command is not an AI reply, host wakeup, game action or guarantee
that an inactive agent will resume. The AI host needs its own supported polling
or wake mechanism.

## Prepare the actual operator session

Use [the command channel](command-channel.md) configuration produced by setup,
then initialize/start that independent receiver explicitly. Create a dedicated
human-conversation session and bind it to the actual operator's provider,
conversation ID and agent ID. For example, save an external session file:

```json
{"sessionId":"owner-conversation-20261026"}
```

Save a separate binding file, replacing the descriptive values with verified
actual host identifiers:

```json
{
  "sessionId": "owner-conversation-20261026",
  "binding": {
    "provider": "ACTUAL_AI_HOST",
    "conversationId": "ACTUAL_OWNER_CHAT_ID",
    "agentId": "ACTUAL_OPERATOR_AGENT_ID"
  }
}
```

```powershell
python C:/Tools/skyrim-autotest/run.py --config C:/TestBench/config/command-channel.json channel sessions --json-file C:/TestBench/operator-session.json
python C:/Tools/skyrim-autotest/run.py --config C:/TestBench/config/command-channel.json channel bind --json-file C:/TestBench/operator-binding.json
```

Do not target the executor's `game-<run id>` machine-action session. The bridge
publishes `kind:asr.final` human text. Only the authorized operator interprets
that text and prepares a separately explicit machine request. The bridge never
turns ASR into `operator.actions` or an executable JSON tool command. Keep this
operator binding stable while its forwarder is active; changes stop forwarding.

## Supply an existing final-speech source

Point to the existing backend's actual `heard.jsonl`. Reuse its listener and
source folder when they are already active; do not start a second microphone
owner. The existing optional listener can be started separately in an installed
Autotest environment, using external Whisper CLI/model configuration:

```powershell
python -m skyrim_autotest.voice_listener --asr-config C:/VoiceBackend/asr.json --session C:/VoiceSessions/NEW_SESSION --device "EXACT_AUTHORIZED_INPUT_NAME" --listen-lock C:/TestBench/voice/shared/listen.lock --operator-thread ACTUAL_OWNER_CHAT_ID
```

This is a separate backend command, not a bridge side effect. Use the owner's
existing shared lock location and a new backend session folder; do not delete a
listener lock or take over an existing process. `asr.json` points to separately
acquired CLI/model files. No sound engine or model is installed by this adapter.
See [optional voice setup](voice-v2.md) for that backend's independent limits.

The accepted input contract is the existing listener's revision-2
`speech.final` JSONL record: sequential integer `seq` starting at 1, nonempty
bounded text, unique 32-character lower-case hexadecimal `utteranceId`,
`audioSha256`, and actual boolean `accepted`, `executable`, `final`,
`audioComplete` all true with `endpointReason:pause`. Unknown fields/shapes,
provisional, rejected or interrupted records stop forwarding; nothing is silently
skipped. The adapter does not reopen audio or assess transcription accuracy.

## Establish a reviewed baseline once

Choose a new private cursor path belonging only to this forwarder. It must differ
from the speech source, any existing shared voice cursor, receiver configuration,
token, database and its sidecars. All paths are explicit and absolute, outside
Git/distributions, with no symlink/junction/reparse ancestry.

For a new empty, reviewed capture source, `--after 0` means forward every future
complete accepted record. If records already exist, review them and select the
last sequence intentionally excluded, for example `--after 42`. Zero on a
nonempty source forwards all existing records; it is not an implicit safe reset.

```powershell
python C:/Tools/skyrim-autotest/run.py asr-bridge --channel-config C:/TestBench/config/command-channel.json --source C:/VoiceSessions/NEW_SESSION/heard.jsonl --state C:/TestBench/runtime/bridges/operator-asr.cursor.json --session owner-conversation-20261026 --source-id headset.voice --after 0 --once
```

`--once` forwards only the complete records available at the start of that call,
then returns counts/cursor status. To keep reception independent of the AI host,
restart the same forwarder without `--after`:

```powershell
python C:/Tools/skyrim-autotest/run.py asr-bridge --channel-config C:/TestBench/config/command-channel.json --source C:/VoiceSessions/NEW_SESSION/heard.jsonl --state C:/TestBench/runtime/bridges/operator-asr.cursor.json --session owner-conversation-20261026 --source-id headset.voice --serve
```

For an installed package the equivalent entrypoint is
`python -m skyrim_autotest.asr_bridge` with the same arguments. `--after` is required
only when the cursor does not exist and is refused for an existing cursor. There
is no reset switch. Stop the independent forwarder with Ctrl+C or through its
verified process owner; it never stops capture, changes the game's mutex or
terminates another listener.

For a new cursor with explicit `--after 0`, `--serve` also waits when the producer
has not created its source file yet. It creates neither the producer file nor an
invented source identity; the actual first complete utterance is pinned and
forwarded when the source appears. A source that disappears after a cursor
exists is a provenance failure, rather than a new waiting baseline. An initially
unbound operator session likewise waits with the cursor retained until its first
actual binding exists. After a binding has been pinned, its disappearance or
change stops forwarding.

## Durability and refusal behavior

A private OS file lock serializes this cursor's forwarder. It is separate from
the game-session mutex and the source backend's capture/consumer locks. The own
cursor records source path/file identity, channel configuration hash, exact target
session/source IDs, queue namespace, source-prefix hashes and acknowledged
sequence. It stores no recognized phrase or credential content.

The event ID is the fixed queue namespace plus the immutable utterance ID; its
text, ASR kind and audio-hash metadata remain unchanged across retries. Submission
uses `CommandHTTPClient.submit` and verifies the durable ACK before atomically
advancing the cursor. A crash or lost ACK between receiver commit and cursor save
resubmits the same event ID; receiver deduplication returns the original command
rather than creating a new one. Repeated words in different utterances remain
separate events. Rejected/mismatched ACKs do not advance the cursor.

The source is read-only and bounded to 32MiB. Only complete newline-terminated
JSON records can advance the cursor. An incomplete last line waits; even its
observed bytes are hash-pinned so rewriting that tail is detected. Truncation,
replacement, prefix rewrite, sequence/utterance duplicates, gaps, malformed
complete lines, altered own cursor or changed source/session/configuration
identity stop rather than reset or skip. Preserve the files and reconcile the
cause. Start a deliberately new source/cursor only with a new reviewed baseline;
never copy or reset an old queue to replay uncertain speech.

When the receiver is temporarily unavailable, `--serve` retains its cursor and
retries on a bounded half-second polling interval, with finite HTTP attempts.
Ordinary quiet/busy periods leave it running. Integrity failures or receiver
refusals stop explicitly; they do not stop the external recorder. Logs contain
only counts/status or safe error messages, never phrases or token contents.
`--once` returns exit 0 on a completed pass and 2 on a refusal/unavailable receiver.
These protocol checks do not qualify live audio, recognition, host responsiveness
or an end-to-end assisted game session.
