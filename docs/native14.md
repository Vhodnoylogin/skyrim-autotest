# Passive native14 observation consumer

The `vrik_native14_v1` producer records facts at VRIK's existing native fourteen-slot
branches. It is a subject-provided diagnostic source, not a control or equipment
transaction API. The executor's stdlib-only consumer validates and selects that
producer's version1 data. Neither component alone qualifies a platform in game.

Raw transport remains the existing DevBench route:

```json
{"kind":"vrik_native14_v1"}
```

POST this object to `/api/tool/inspect` on the separately verified owned host.
REST returns its result directly. No extra inspect request properties or new host
ABI are required. Discover the exact key and check actual ownership, gameplay
readiness and provider qualification before a subject scenario. A health response,
registered extension, HTTP200 or valid offline JSON does not prove those stages.

## File validation and public Python helpers

An already collected file can be checked without configuration or a game:

```powershell
python -m skyrim_autotest validate-native14 --snapshot C:/TestBench/native14.json --expected-pid 1234 --max-age-micros 500000
```

Both PID and acceptable sample age are explicit caller requirements. For an offline
file they verify claimed metadata only, not a currently running process or live
freshness. The command does not contact, install, launch or mutate a game. It reads
at most2MiB, rejects duplicate keys and JSON NaN/Infinity constants, and returns
input SHA256 with `gameTestingPerformed:false`. Failure uses exit2. Add repeated
`--measure PATH` for explicitly observed finite measurements, or
`--haptics-baseline FILE` for a complete retained request interval after an actual
pre-action snapshot. The consumer checks both snapshots, scope-count delta and
retained process-wide sequences, exact load/body context and inclusive frame range.
History/counts clear on load while event sequences do not; empty baseline history
has no known last sequence and must not be treated as sequence zero. Never fabricate
an earlier baseline to widen coverage. Missing/overwritten intervals, context
changes and backward/future attribution are errors, not zero requests.

The importable functions are `native14.validate`, `native14.measurement` and
`native14.new_haptic_requests(snapshot, baseline=baseline)`. The raw validated dictionary is copied, retaining
decimal uint64 strings and exact IEEE bits. Native NaN/infinity use value:null with
their bits and remain diagnostic data; they cannot become finite measurements.
Selection must honor field availability masks: zero-filled unobserved values are
unavailable. Producer enum/mask/phase details must come from its actual versioned
contract, never a guessed VRIK implementation. Unsupported measurement paths are
refused explicitly. Raw data should still be retained alongside selected values.

Paths use dotted keys and zero-based array indices, for example
`frame.slots.0.local.position.0.value` or `frame.hands.0.probe.0.bits`.
The native slot identity itself remains numbered1..14. A numeric object's
`.value` requires finite observed data; `.bits` retains its IEEE representation.
Context flag bits are sampled values, not availability bits: a complete frame
can legitimately observe false context values. Gate and scene dependencies use
their producer-documented masks, not the presence of zero-filled fields.

This complete-frame consumer deliberately refuses pending/unavailable frames.
The producer may retain historical haptic events in those states; an independent
pending-event reader is outside this release's qualified offline scope.

The caller that collects live evidence owns before/after process creation-time
and endpoint checks, load/body/frame continuity and operation deadlines. This
file consumer does not cancel tasks, authenticate producer identity, maintain a
live stream cursor, execute a subject scenario or grant queue/launch authority.
Compare actual ordered fresh frames for a transition; a single copied frame is
not a complete history or one atomic snapshot of every engine operation.
The producer's body generation tracks an observed root/load identity proxy;
it does not certify every model/subnode lifetime or detect pointer reuse.
Fixture and actual model identity therefore need independent control.

## What the producer can support after live qualification

The recorded placement/policy source, status and consumed bank revisions can
distinguish legacy and shared reads. Status alone is insufficient: an absent
optional bank can coexist with a valid legacy path. Ordered slot records,
available local/world pose values, per-hand gate decisions and selected hover
can support actual native14 read/decision checks. Scene-graph decisions/counts
can support narrowly stated scene-state checks. Haptic history proves only
native14 request-site events in its complete retained interval and exact token.

It does not prove rendered pixels, ancestor visibility/occlusion, hardware
delivery, unobserved Papyrus equipment transactions or absence of events outside
the retained interval. Equipment/inventory changes need independent game-state
observations. INI/save/load comparisons need fresh actual post-transition data,
not requested settings or file hashes alone. Shape-only fixtures and offline
producer/consumer tests are never mod-test results.

The existing frozen platform and pending DevBench readiness/decoder qualification
are unchanged. They do not include this producer. A future candidate must pin the
real subject/provider builds and qualify transport, availability, lifecycle,
physical input/result mapping and restoration separately before native14 subject
acceptance. This document creates no order and installs no subject DLL.
