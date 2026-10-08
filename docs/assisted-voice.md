# Assisted chat voice delivery

The external ASR listener and model remain separately acquired dependencies.
Do not bundle executables, models, recordings or transcripts in this repository.
An alive listener and a transcript do not prove the chat answered. The original
`voice-next.py` is pull-only: an idle AI chat must be woken by its host.

`skyrim_autotest.voice_inbox` is an optional stdlib-only companion. It never
touches the game, MO2, VR driver, listener process or shared voice cursor.
Use the existing listener; do not start a second one or force ownership.

For the current real-time session, an explicitly authorized **active chat bridge**
can keep a turn open and run `claim --wait 30` repeatedly. It returns immediately
on speech (poll interval 250 ms), then the active agent uses its supported host
message tool to deliver that claim to the exact operator thread. Send only the
claim reference/hash; speech stays in the external inbox. Persist successful
host message receipts by claim ID before considering another delivery. Pending
delivery is not a request to send again. The operator processes/answers and
acknowledges the same claim. Measure actual latency; model scheduling and ASR
still add time. This bridge only works **while its agent turn is active**. Ending
that turn, application exit, context errors or sleeping the machine suspends
real-time delivery. Keep microphone and unacknowledged records intact. Do not
advertise this as an independently running voice service.

For delayed background delivery, configure a **supported thread heartbeat** in the AI desktop host, targeting the
exact assisted operator chat. An example interval is one minute; scheduling,
busy turns, ASR inference and host availability add latency. This is periodic
delivery, not a low-latency voice call. If the app is closed/sleeping or heartbeat
is paused, speech accumulates without a timely reply. Do not start another
app-server against a live desktop thread as a workaround. A separately managed
API client may use the documented turn/start or turn/steer protocol only with an
explicit supported endpoint and its own verified ownership/configuration.

Initialize an external private inbox with an explicitly reviewed baseline:

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
