# Assisted chat voice delivery

Current Polygon runtime uses [operator-owned setup/direct polling](voice-operator.md).
The cross-chat bridge described below is historical and must not be used for
this owner's manual sessions. No development-chat relay or per-utterance app message.

The external ASR backend and model remain separately acquired dependencies.
Do not bundle executables, models, recordings or transcripts in this repository.
An alive listener and a transcript do not prove the chat answered. The original
`voice-next.py` is pull-only: an idle AI chat must be woken by its host.

Version0.2.0 supplies a whole-utterance capture companion and buffered delivery.
Use [voice v2](voice-v2.md) for new setup, acquisition, migration and qualification.
The existing running listener/inbox is never replaced or upgraded automatically.

`skyrim_autotest.voice_inbox` is an optional stdlib-only companion. It never
touches the game, MO2, VR driver, listener process or shared voice cursor.
Use the existing listener; do not start a second one or force ownership.

For the current real-time session, an explicitly authorized **active chat bridge**
can keep a turn open and run v2 `admit --wait 2` repeatedly. It returns immediately
on speech (poll interval250ms), then the active agent uses its supported host
message tool to deliver that claim to the exact operator thread. Send only the
claim reference/hash; speech stays in the external inbox. Persist successful
host message receipts by claim ID. Dispatch reservation precedes sending;
uncertain delivery is not a request to send again. New speech is admitted while
earlier requests await completion. The operator records its first actual reply,
then processes/answers and acknowledges completion of the same claim. Measure
actual latency; model scheduling and ASR
still add time. This bridge only works **while its agent turn is active**. Ending
that turn, application exit, context errors or sleeping the machine suspends
real-time delivery. Keep microphone and unacknowledged records intact. Do not
advertise this as an independently running voice service.
The reproducible Codex host adapter source is
`integrations/codex-voice-bridge.js`: run it within an authorized active
`functions.exec` with `VOICE_BRIDGE_CONFIG={repository,inbox,threadId,durationSeconds}`.
Paths must be absolute and duration at most300 seconds per invocation. It is not
a Node executable and cannot wake itself after the host turn ends. Preserve its
external dispatch receipts and reconcile pending speech before restarting.

For delayed background delivery, configure a **supported thread heartbeat** in the AI desktop host, targeting the
exact assisted operator chat. An example interval is one minute; scheduling,
busy turns, ASR inference and host availability add latency. This is periodic
delivery, not a low-latency voice call. If the app is closed/sleeping or heartbeat
is paused, speech accumulates without a timely reply. Do not start another
app-server against a live desktop thread as a workaround. A separately managed
API client may use the documented turn/start or turn/steer protocol only with an
explicit supported endpoint and its own verified ownership/configuration.

Initialize an external private inbox with an explicitly reviewed baseline:

The following commands describe the retained **legacy serialized v1 inbox**.
The published active adapter now requires v2; use voice-v2.md for its commands.

```text
python -m skyrim_autotest.voice_inbox --inbox C:/TestBench/voice/polygon --thread <UUID> init --heard C:/TestBench/voice/heard.jsonl --after <SEQ>
python -m skyrim_autotest.voice_inbox --inbox C:/TestBench/voice/polygon --thread <UUID> claim
python -m skyrim_autotest.voice_inbox --inbox C:/TestBench/voice/polygon --thread <UUID> ack --id <ID> --sha256 <HASH> --response-ref <EXTERNAL-RECEIPT-OR-TURN-REFERENCE>
```

The heartbeat claims speech, handles it in the operator chat, records a local
processing/reply reference, and acknowledges that exact claim. Do not ack just
because capture/health succeeded. `quiet` means no new complete record: remain
silent. `pending_review` is the **same** unacknowledged delivery: inspect the
operator's prior action/reply receipt before doing anything again. Never blindly
repeat a game mutation. Missing/ambiguous prior outcome needs reconciliation,
not replay. Acknowledgment is processing bookkeeping, not proof of an audible
reply or exactly-once external actions. Keep action-specific idempotency checks.

Queue rewrite/truncation, duplicate/gapped sequence or malformed complete data
blocks delivery instead of dropping speech. Incomplete final appends wait.
Initialization never resets an existing inbox. One OS lock protects claims and
acknowledgments; retain private inboxes/receipts outside Git. A restarted listener
may retain the same durable queue; do not reset the cursor just for PID changes.

Text is the primary reply channel. Use short synthesized speech exceptionally;
select the headset output explicitly and distinguish playback from owner-heard
confirmation. Stop the microphone only on the owner's explicit instruction,
including after game exit. A wake-word recognition is not guaranteed ASR truth;
ambiguous/destructive commands need confirmation, not invented intent.

Qualification needs a **fresh real spoken phrase**, automatically delivered by
the active bridge or heartbeat and answered in the target chat without an intervening typed
message. Record ASR sequence/time, claim ID, automatic turn and actual response;
measure latency. Synthetic files/unit tests do not qualify this live path.

## Interactive requests and screenshots

"Give me items" defaults to adding them to the player's **inventory** (for
example `player.additem <form> <count>`), not spawning physical objects at the
player's feet. World spawning needs an explicit owner request or scenario.
Do not repeat a previously executed request when correcting its interpretation.
ASR ambiguity is clarified by the operator, not silently turned into an action.

For an explicit screenshot request use the optional companion:

```text
python -m skyrim_autotest.assisted_capture --out C:/TestBench/voice/shots --id voice-<SEQ> --identity C:/TestBench/manual-game-identity.json --port <VERIFIED-PORT> --voice-output "EXACT HEADSET OUTPUT"
```

The identity file is the already verified manual game's exact `{pid,birth,path}`;
do not discover an arbitrary foreground process. The command synchronously
announces capture/counts down through the explicit Russian headset output,
checks identity again, calls DevBench capture once, and validates an actual fresh
PNG/BMP file in its unique external output directory. It uses no F12, keyboard,
focus request or restart. `auto` selects DevBench's sole registered provider or
its native fallback; multiple providers/unsupported image format/renderer not
producing a frame produces an explicit unavailable reason. No fallback retry
after an uncertain capture. Duplicate request IDs never recapture.

The image receipt is not a visual verdict. Open the actual image, show/link it
in chat and check scene/content, retaining native/provider degraded metadata.
The voice response is short; analysis remains text. A minimized/not-rendering
game may fail even though foreground is not a prerequisite. Do not steal focus
to conceal that limitation. Live background-frame qualification is pending;
unit tests only verify countdown/capture/file guards. If no game is running,
report capture unavailable rather than launch one.

## Microphone input diagnosis

The shared WinMM companion measures actual input without restarting the existing
ASR singleton, changing system defaults/mute/gain, or silently choosing another
microphone:

```text
python -m skyrim_autotest.microphone_probe
python -m skyrim_autotest.microphone_probe --device "Steam Streaming" --seconds 6 --output C:/TestBench/voice/levels.json
```

Use a unique enumerated name fragment (WinMM names are truncated), with a bounded
1..30-second sample. No raw audio is saved by default. For explicit offline ASR
diagnosis, add `--wav <NEW-EXTERNAL-WAV>`; existing recordings never overwrite.
Outputs include received bytes, measured peak/RMS/dBFS and per-second buckets.
Enumeration and capture/level checks need no spoken phrase. Recognition can use
any fresh owner speech recorded during the sample; a prescribed phrase is only
an optional aid for identifying and comparing transcripts. A prerecorded test
file exercises the recognizer, not the live headset microphone or chat delivery.
Silence/noise/game sound is not recognition of human speech. Near-silent input
while the owner actually speaks suggests upstream routing/mute/transport trouble;
a quiet sample while they do not speak establishes no microphone defect.

Report the exact current listener/device, capture quality and actual accepted
owner transcript separately. The headset/streaming application's permission,
mute and microphone slider may require the owner's in-headset inspection. Do not
reinstall drivers, restart their game/headset, increase gain blindly or mask this
with a desktop microphone. A speech input path needs a fresh real owner utterance;
then qualify delivery/response latency independently.
