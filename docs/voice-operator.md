# Operator-owned assisted voice (0.2.2)

Polygon owns its microphone setup and consumes speech in its own active turn.
The development chat only receives a deliberately requested tooling report and
returns one repair result. Do not run the cross-chat bridge or send a message
per utterance. No game, MO2, profile, driver, AI API, credentials or installation
is touched by these commands. Models/Whisper/audio remain external.

## Owner says the manual game is running

Run from the installed package or this repository:

```text
python -X utf8 -m skyrim_autotest.voice_operator --config <ABSOLUTE-EXTERNAL-CONFIG> ensure --owner-ref <ACTUAL-HUMAN-MESSAGE-REFERENCE>
```

This action requires the direct owner's actual manual-session start. A discussion
about yesterday's running game is not a start. Configuration is machine-local:

```json
{
  "threadId": "00000000-0000-0000-0000-000000000000",
  "runtime": "C:/TestBench/voice/operator",
  "listenLock": "C:/TestBench/voice/listen.lock",
  "asrConfig": "C:/TestBench/voice/asr.json",
  "device": "EXACT UNIQUE HEADSET NAME FRAGMENT",
  "wake": "полигон",
  "pause": 1.6,
  "port": 8931,
  "dialogSeconds": 14400
}
```

Replace the thread/device/paths; use the original shared singleton lock. Do not
use a different lock to bypass another listener. Configuration and output must
remain outside Git. The listener selects a unique input, never the Windows
default; it does not change gain or mute settings. The ASR config is the existing
external JSON with cli/model/language paths, including Speech Broker's model.

`ensure` serializes preparation, reuses the exact healthy saved binding and
preserves its inbox/cursors. A dead binding/lock is archived, not discarded.
Unknown live or reused/uninspectable PIDs block; no process is killed or taken
over. A new listener is hidden, owns a fresh session and starts one new buffered
inbox at0. Startup health requires live PID/birth/path, recent continuous capture,
the exact queue and matching singleton. Spawn failure/unknown startup is retained
for reconciliation; do not blindly repeat, clear locks or spawn alternatives.

For a deliberately reviewed existing listener, an optional `existing` object
contains its exact `pid`, absolute `session` and absolute `inbox`. Its inbox must
already exist, belong to Polygon and match the session queue. There is no invented
baseline or automatic cursor reset. Legacy locks additionally require birth to
agree with their original lock timestamp. A changed identity blocks.

New0.2.2 listeners receive a durable bounded conversation-open request from
`ensure`; capture acknowledges it before `conversation_open` is reported. No
fixed test phrase or initial wake word is needed after this typed owner start.
It opens a bounded four-hour dialog by default (`dialogSeconds`1..14400);
ordinary pauses do not close that owner-opened dialog. New starts explicitly
reopen it; a longer session needs an explicit current continuation reference. Natural addressed
speech can also open the ordinary wake window. Conversation-open/close affects
the gate, never the microphone. Invalid/stale/foreign controls are recorded and
ignored. No speech captured before the control may enter because of that control.

A healthy older0.2.1 listener cannot acquire this capability by editing source.
It is reused without restart and returns
`legacy_listener_requires_ordinary_address`: an ordinary fresh addressed phrase,
not a fixed test string, opens its existing gate. Report this limitation honestly.
The currently running listener must not be hot-upgraded during an owner session.

Capture-ready is not proof that ASR recognized the owner or that the chat answered.
Confirm those separately on naturally occurring fresh speech. Do not fabricate
a microphone success from a stale health file or an empty/noisy transcript.

## Direct receive, answer and completion

In Polygon's own active turn, use bounded waits between inspection/actions:

```text
python -X utf8 -m skyrim_autotest.voice_operator --config <CONFIG> poll --wait 30
```

`delivered` contains exact id/hash/sequence and final utterances. This returns
directly to Polygon as a tool result; it never calls a chat message API.
Read/process fresh speech in that chat once. A receipt is durably stored BEFORE
returning stdout. If the host loses that result or the operator is interrupted,
the next poll reports `pending_review`, not a repeated command. Inspect the exact
saved entry before reconciling. Earlier unfinished commands do not block fresh
speech. A wait also waits for fresh speech when only older pending entries remain.
Quiet/pending unchanged states cause no owner-facing status messages.

Primary communication is text; use short voice exceptionally. Answer actual
requests and provide current test instructions. Do not emit a boilerplate reply
for every ASR fragment. Background/non-directed/ambiguous speech is retained as
unavailable intent and must not cause game actions. ASR text is fallible, not
speaker authentication. Preserve mutation order and request-specific action IDs.
For screenshots preserve announcement, countdown, actual capture and image
verification; do not repeat a screenshot after an uncertain prior attempt.

Use the exact returned inbox/id/hash to record first actual reply and completion:

```text
python -m skyrim_autotest.voice_inbox --inbox <INBOX> --thread <POLYGON-UUID> reply --id <ID> --sha256 <HASH> --response-ref <ACTUAL-MESSAGE-REFERENCE>
python -m skyrim_autotest.voice_inbox --inbox <INBOX> --thread <POLYGON-UUID> ack --id <ID> --sha256 <HASH> --response-ref <EXTERNAL-PROCESSING-RECEIPT>
```

`replyRecordedAt` is bookkeeping. `firstVisibleReplyAt` stays null unless the
actual message Unix timestamp is supplied using `reply --visible-at`; never put
the later acknowledgement time there. Legacy `firstReplyAt` remains compatible
and is explicitly marked bookkeeping. Old records are not rewritten. Completion
is distinct from delivery and reply; the processed cursor moves only over the
contiguous completed prefix. Host dispatches from an older bridge are preserved
and never automatically redelivered through direct polling.

## Boundaries and qualification

Polling consumes speech only while Polygon's turn is active. When it ends or the
desktop sleeps/closes, audio/ASR may continue but replies need Polygon to resume
through its supported host. This implementation does not provide independent
idle push, guaranteed response time or a way to talk to a stopped listener to
start itself. No second app-server or hidden other-chat relay is supplied.

Keep capture running until the owner explicitly stops it; ending a test or
closing/crashing the game alone is not a microphone stop. These tools deliberately
provide no force/kill command. Changes are prepared offline; adopting the updated
listener and a fresh end-to-end owner-start/dialog/response check remain Polygon's
separately authorized qualification, not a completed game test by this chat.

ASR can misrecognize names and split a slow semantic sentence at a long pause.
Keep every original clip/segment and review adjacent utterances together when
needed. A configurable longer pause can help but increases latency; it is not
proof of word-perfect recognition. Do not silently rewrite words, execute a
partial instruction or claim a model defect without original-audio evidence.
