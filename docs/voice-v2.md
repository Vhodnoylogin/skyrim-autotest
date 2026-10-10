# Assisted voice v2 (executor0.2.0)

For current Polygon sessions use [voice_operator ensure/poll](voice-operator.md)
introduced in0.2.2. The cross-chat host bridge below is retained history, not the
current runtime path. Old pending deliveries/cursors stay unchanged.

Patch0.2.1 fixes live Windows reader/ACK contention: initialization checks lock
file size without reading the locked byte. CLI operations wait up to250ms for
the consumer lock, then return `busy`, retryable, `before_inbox_access` (exit3).
The host adapter retries only that known pre-access result up to four calls.
Post-access write failures and uncertain host sends remain terminal/reconciled;
neither is retried as busy. This changes no queue schema or action acknowledgment.
The patch was prepared after the owner's manual game closed; the healthy live
listener was not restarted. Source concurrency tests do not replace live acceptance.

This external companion fixes two independently observed mechanisms: the old
private inbox withheld new dispatch until prior processing finished, and the
old stream wrapper discarded audio timing while trimming overlapping text.
It makes no game/MO2/driver changes. Text remains the primary response channel;
short synthesized speech is exceptional. Existing screenshot announcement,
countdown and verified-image requirements remain mandatory.

## Receive independently of completion

Create a NEW external buffered inbox with an explicitly reviewed queue baseline:

```text
python -m skyrim_autotest.voice_inbox --inbox C:/TestBench/voice/operator-v2 --thread <EXACT-UUID> init --heard C:/TestBench/voice/session/heard.jsonl --after 0 --buffered
python -m skyrim_autotest.voice_inbox --inbox C:/TestBench/voice/operator-v2 --thread <EXACT-UUID> admit --wait 2
```

Legacy inboxes retain `claim`/`ack`. To opt into v2 on the SAME queue, explicitly
run `upgrade` after reconciling/acknowledging the legacy pending request. This
preserves its processed cursor and anchors. It never jumps to a new baseline,
replays an old action or repoints an inbox to another source queue. A replacement
listener owns a new queue/session and consequently needs a new private inbox.

`admit` persists received records and an admission cursor, independent of the
processed cursor. It returns the oldest still-unsent delivery. The host adapter
reserves it with `dispatch --id <ID> --sha256 <HASH>` BEFORE sending the file/hash
pointer. A successful host send is recorded with the same command plus
`--receipt-ref <EXTERNAL-HOST-RECEIPT>`. New records continue to be admitted and
sent while previous requests await answers. Host delivery is not execution.

In the operator chat, provide a brief actual text receipt before lengthy work;
record that with `reply --id <ID> --sha256 <HASH> --response-ref <ACTUAL-REPLY>`.
Only after completing/clarifying the request, record the processing outcome with
`ack --id <ID> --sha256 <HASH> --response-ref <FINAL-LOCAL-RECEIPT>`. Neither `admit`
nor `dispatch` acknowledges completion. Out-of-order completion is retained;
the processed cursor advances only over a contiguous completed prefix.

Prefer short status answers and explicit screenshot requests before lengthy
analysis. Keep game mutations in owner order and use action-specific idempotency.
Do not execute provisional/incomplete audio or guess ambiguous speech. A received
pointer cannot grant launch authority. The operator's first reply and final
completion times are distinct. A brief receipt is not evidence a screenshot or
other action succeeded.

The updated `integrations/codex-voice-bridge.js` runs in an authorized active
Codex `functions.exec` host with the existing `VOICE_BRIDGE_CONFIG`. It requires
v2, does not upgrade silently, and dispatches without waiting for action ACK.
Its bounded watch remains at most300seconds; it cannot wake itself after the
host turn ends. Model scheduling, a busy operator and slow tools can still delay
actual replies. No independent idle push or guaranteed low-latency response is
claimed. The portable build includes the adapter; the stdlib-built wheel carries
it under `skyrim_autotest/integrations/` as source for the host.

A send exception, rejection, application exit or uncertain receipt leaves the
delivery in `dispatching` for explicit reconciliation. It is never resent blindly.
New speech is preserved separately; uncertainties about game mutations must
still hold further conflicting actions. `status` validates queue anchors and all
admitted record hashes. State/transcripts/host receipts stay outside Git.

## Whole-utterance listening

The new listener continuously captures shared WinMM PCM16 mono16kHz on a capture
loop, spools pause-delimited WAVs, and runs the external Whisper CLI in a separate
FIFO worker. Recognition or a busy AI never blocks audio capture. There is no
rolling8second ASR window and no character-overlap trimming. Actual repeated
words remain in the result. Whisper may still misrecognize or omit words.

The energy endpoint gate is a heuristic, not a trained VAD or proof of human
speech. Configure it against actual headset audio. Defaults: energy RMS100,
silence1.6seconds,400ms pre-roll, maximum120seconds per utterance (configurable
5..300). The longer pause preserved the recorded slow phrase that a900ms pause
split. A longer pause increases endpoint latency; a pause during thinking can
still split a semantic instruction. Retained raw audio and operator review are
essential; do not advertise word-perfect completeness. Noise may extend an
utterance and very quiet speech may be below the gate. System gain is unchanged.

Every utterance has one ID: `speech.started` revision0 (no text/no executable
command), `audio.final` revision1 and `speech.final` revision2 with preserved ASR
segments. Only complete pause-ended audio whose final transcript passes the
explicit wake/conversation gate enters `heard.jsonl`. Incomplete capture, exceeded
duration, ASR failure, exhausted input buffers and full pending backlog are
explicit faults, never successful empty data or executable partial commands.
Source WAVs, segment JSON and combined backend diagnostics remain external.
Restart does not replay them automatically.

Use existing external `asr.json` with absolute `cli`, `model`, `language` fields.
It need not be changed. Speech Broker's model resources are reusable; neither
Speech Broker nor the running game is required for this out-of-process channel.
Do not copy model weights or third-party executables into this repository.

Offline preparation, with an authorized existing PCM WAV and NEW output folder:

```text
python -m skyrim_autotest.voice_listener --asr-config C:/TestBench/voice/asr.json --session C:/TestBench/voice/replay-new --replay-wav C:/TestBench/voice/recording.wav --wake полигон
```

Live replacement at an owner-authorized listening transition:

```text
python -m skyrim_autotest.voice_listener --asr-config C:/TestBench/voice/asr.json --session C:/TestBench/voice/live-new --device "Steam Streaming" --listen-lock C:/TestBench/voice/listen.lock --wake полигон --serve 8931
```

Select a unique explicit enumerated WinMM name fragment. There is no default
fallback, device gain change, forced takeover or process termination. The live
command refuses any existing shared `listen.lock`; reconcile/stop the previous
listener only under the owner's explicit instruction. Never use an alternative
lock path to circumvent it. The v2 command owns its new external audio queue and
does not append to or reset the old shared queue/cursor. Bind its exact new queue
to the operator inbox/bridge. Keep it listening until the owner explicitly stops
it; game/session closure alone does not stop listening.

`health.json` records capture activity, sample count, backlog, errors and accepted
sequence. Optional localhost GET `/api/health` and `/api/events?since=N` expose
the same state/final accepted records. No POST speech endpoint is supplied;
use the existing explicitly selected headset synthesis tool. A fatal capture
fault exits visibly and preserves its audio/spool; it never silently switches
devices or resumes an incomplete command. Review that fault before restarting.

## Acquisition and measurement

Whisper CLI source/options are pinned to the observed external recipe
[whisper.cpp b5130](https://github.com/ggml-org/whisper.cpp/tree/b5130), especially
`examples/cli/cli.cpp`. Obtain/build the Windows CLI outside Git; record actual
executable/model hashes in your external deployment receipt. The current model
recipe is [Speech Broker model-whisper-ru](https://github.com/Vhodnoylogin/speechbroker/tree/main/model-whisper-ru),
including its weights/SOURCE and SHA256SUMS. This tool reads that already installed
external model path; the model itself is not part of our distribution. A directory
called b5130 alone does not attest the installed binary's provenance.

Per utterance: start/end sample offsets and rate, endpoint/capture wall times,
ASR start/end, final admission timestamp, audio digest and preserved segments.
Per private delivery: received, dispatch-start, successful host receipt, first
actual reply and completed times/references. Sample offsets describe audio
coverage; energy onset/end are200ms estimates, not exact human phonetic timing.
Replay wall times measure offline processing, not historical speech-to-reply
latency. Host bookkeeping is not proof a human saw/heard a reply.

Offline evidence on2026-10-09: exact-byte preservation of a synthetic15second
utterance, concurrent spooling while ASR is blocked, later host delivery while
earlier requests are incomplete, and a real prior headset WAV recognized with
the installed CLI/small model. The corrected pause produces one transcript
containing "Полигон, ты меня слышишь?"; its initial "Приём" remains misrecognized.
These checks do not qualify live v2 capture, word completeness, fresh response
latency, headset speech output or the entire manual game path. No live listener
or manual game was replaced during preparation.
