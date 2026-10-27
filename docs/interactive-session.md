# Bounded interactive owned session (candidate)

This optional hold-open route needs separate live qualification. Offline tests do
not establish a ready human game session or complete CLAW transformation support.
It uses the ordinary owned startup, common gameplay readiness, declared
preparation steps, mutex, heartbeat, guardian and restoration. It starts no
receiver, microphone, model, speech output, game or recovery process of its own.
The default executor remains a bounded one-shot run when this option is absent.

The SE source candidate additionally admits strict read-only
`inspect kind=world_observer` requests over this same owned transport. This is
not admitted into a previously frozen platform automatically. Polygon must
separately qualify the exact Observer, SKEE/OBody providers and new executor
candidate; updating source creates no game or subject-test authorization.
Snapshot fields are `refs`, `nodes`, `actors`, `skee`, `obody`, `cbpc` and
`timeoutMs`, with strict bounded subfields and no mutation/capture escape.
`capabilities` accepts only `kind` and `action`. This additive contract is SE
only; existing VR observations keep their separate qualified route.

For example, submit the following machine command through the current run's
ordinary command channel with `sourceId:operator.actions` and a fresh event ID:

```json
{"schemaVersion":1,"operation":"tool","tool":"inspect",
 "args":{"kind":"world_observer","refs":["0x14"],"actors":true,
   "skee":{"refs":["0x14"],"morphs":["Breasts","Waist"]},
   "obody":{"refs":["0x14"],"afterSequence":0,"maximumEvents":64},"timeoutMs":1500},
 "timeoutSeconds":2}
```

Replace actor IDs and morph names with the actual fixture. Results use the
existing inline/artifact registry and retain raw availability/quality/epoch/loss
fields. A delivered or recorded read does not mean complete observations or a
passed subject assertion. Do not infer contact negatives, application/render
completion, continuous root identity or save/load support from this read route.
Snapshot timeout defaults to1500ms, must be100..3000ms and fit the enclosing
command deadline. Query JSON is capped at16KiB; physics capture, setters and
extra fields are rejected before delivery. Sound and launch handling are unchanged.

The operator's separate, explicit authorization for an interactive session must
be recorded in the ordinary platform attempt. Do not replay an old one-shot
order to obtain a held-open game. Keep this platform setting outside schema-2
subject orders:

```json
{
  "interactive_session": {
    "channelConfig": "C:/TestBench/se/config-040/command-channel.json",
    "maximumSeconds": 1800,
    "allowedTools": ["inspect", "menu", "input", "platform"],
    "sourceId": "operator.actions"
  }
}
```

`maximumSeconds` is an explicit integer from 1 to 14400. Tools must be a unique
nonempty subset of `inspect`, `menu`, `input`, `papyrus`, `platform`, `native14`
and `driver`. SE rejects VR-only native14/driver requests. A selected tool still
needs its existing acquired/configured provider; listing it grants no native
capability or live qualification.

An optional `nativeBindings` platform policy can declare a finite typed native
interface. Its absence disables binding requests. The policy is validated and
frozen with this exact attempt's configuration; it cannot be supplied or changed
by an incoming command. The `papyrus` tool must also appear in `allowedTools`.

## Independent receiver and distinct action session

A separately started neutral command receiver may accept owner text/final ASR
while the game executor or an agent is busy. Initialize its external channel
configuration and optionally start its HTTP server through the documented
[channel interface](command-channel.md). Neither the interactive loop nor setup
starts that server or any voice adapter. A fresh ready-file target must be
separate from all existing configuration, token and database files.

The human conversation session belongs to its exact AI-host binding. Its raw
messages and ASR are never interpreted by the game loop. An authorized operator
agent interprets a particular human request and submits an explicit machine
operation to a different action session. The existing game executor remains the
only game/session owner; an adapter or subagent receives no second native mutex.

After common initialization the executor saves and logs
`state.interactiveSession` with:

- `sessionId`: `game-` followed by this exact owned run ID;
- binding: provider `skyrim-autotest`, conversationId equal to the run ID, agentId
  `owned-game-executor`;
- exact `sourceId:operator.actions`, configuration reference and finite window.

Use that saved ID exactly. Every run receives a fresh session; existing action
sessions and reconnect attempts are refused. Commands in previous sessions stay
there and are never drained into the new game. Readiness metadata means the
bounded machine-action loop is accepting requests; it is not a subject verdict.

For example, save an external submission envelope for one current scene read:

```json
{
  "sessionId": "game-ACTUAL_CURRENT_RUN_ID",
  "sourceId": "operator.actions",
  "sourceEventId": "CURRENT_RUN_ID-scene-001",
  "kind": "text",
  "text": "{\"schemaVersion\":1,\"operation\":\"tool\",\"tool\":\"inspect\",\"args\":{\"kind\":\"scene\"},\"timeoutSeconds\":10}"
}
```

Submit through the external channel, independently of the held game:

```powershell
python C:/Tools/skyrim-autotest/run.py --config C:/TestBench/se/config-040/command-channel.json channel submit --json-file C:/TestBench/requests/current-scene.json
```

A request uses `schemaVersion:1`, `operation:tool`, one allowed `tool`, object
`args` and finite `timeoutSeconds` in (0,30]. Stable source-event IDs deduplicate
repeated submissions. A lost receipt is never a reason to invent a fresh event
ID for the same uncertain action. Read completion/events or inspect evidence.

## Deliberately narrow action policy

- `inspect`: `state`, `scene`, `mods` or `player`, with no extra parameters.
- `menu`: `list` with optional boolean `includeFlags`, or `describe` with one
  explicit menu name. Startup selection/confirmation and UI invocation are absent.
- `input`: status/capabilities, or owned keyboard down/up for W/A/S/D/SPACE.
  The owner must be `autotest-<current run id>`. Down requires a server `maxHoldMs`
  lease from 100 to 1000, fitting both the request timeout and actual remaining
  session/claim deadline at dispatch. Fresh `devbench.input` 2.0, keyboard v1
  capabilities must report available/ready, the exact injection/encoding,
  supported key and owner-release actions. No activation, menu-navigation,
  console, save or quickload keys.
- `papyrus`: a fixed list of known native read functions on Game, Actor,
  ActorBase and ObjectReference. Arbitrary scripts, setters, selector wrappers
  and Actor.SetRace are unavailable.
- `platform`: existing validated read operations, bounded controller operations,
  and `assign-morph-preset`, `clear-morph-preset`, `configure-morph-link`,
  `disable-morph-link`, `refresh-morph-preset`. Preset actions retain exact actor
  reference/base identity, native metadata and before/after incarnation guards
  from the existing adapter. Native admission is not completed transformation,
  measured morph application or rendered appearance.
- `driver`: existing complete-frame/lease validation; hold fits the request bound.
- `native14`: existing configured/pinned read validation in the same reference
  world, with its existing freshness/availability guards.

Console/game tools, save/load/restart, arbitrary fixture creation, world replacement,
reference deletion and semantic set-race/sex/weight/body-morph actions are refused.
The default route supplies no NPC transformation/race change. A separately
declared typed native binding can expose a narrow candidate under the guards
below; arbitrary raw Papyrus remains unavailable. Actual Actor.SetRace and
OBody/CLAW NPC morph and appearance qualification are still required. Preparing
the API does not qualify a race change or establish the owner's full intended
NPC transformation. Existing morph preset support retains the limits in
[morph presets](morph-presets.md).

## Optional typed native binding request

The frozen `nativeBindings` policy names exact scripts, functions, native types,
member/global scope, read/mutate effect, actor/race argument positions and return
evidence. The separate binding validator limits its fixture bases and target
race forms. Each request selects only one declared ID:

```json
{
  "schemaVersion": 1,
  "operation": "binding",
  "bindingId": "npc_race",
  "args": ["0x00013746"],
  "self": {"reference": "0xACTUALREF", "base": "0xACTUALBASE"},
  "timeoutSeconds": 10
}
```

The identity placeholders illustrate shape only; actual references/bases and
arguments must satisfy the selected frozen policy. Actor-typed arguments carry
the same exact `{reference,base}` pair. A global binding omits `self` as required
by its declaration. Scripts, functions, selectors or a replacement policy cannot
appear in a request. An absent/unlisted binding or missing papyrus allowlist is
rejected before the guarded call. Normal request schema/time bounds still apply.

For a declared mutating binding, the loop applies fresh native gameplay/menu
readiness before delivery. After durable delivery it invokes
`interactive_bindings.guarded_call` once with the actual remaining deadline.
That adapter verifies frozen-policy equality, typed values, current native
metadata, exact owned fixture actor/base/world identity, permitted race forms
and its configured readback contract. A read binding uses the frozen effect
declaration; signature metadata alone cannot prove absence of side effects.
Returned native data/admission and actual subject appearance
are separate evidence. A timeout or unknown result stops the hold and retains
uncertainty; it never retries the native call. A binding does not restart a game,
change the owning session or remove the need for live qualification.

## Create a witnessed disposable NPC

Binding and preset mutations may target only an actor newly created by this
owned run through the explicit fixture route. An existing NPC or player cannot
be adopted merely because its base matches a whitelist. Creation requires the
same frozen `nativeBindings` policy and papyrus allowlist, plus fresh native
gameplay/menu readiness. It has no camera or photography dependency:

```json
{
  "schemaVersion": 1,
  "operation": "fixture-create",
  "request": {
    "tag": "ownedNpcOne",
    "base": "0x00000456",
    "forwardGameUnits": 150,
    "rightGameUnits": 0
  },
  "timeoutSeconds": 10
}
```

Use an actual permitted NPC base from the frozen policy. The fixture adapter
validates bounded placement and a unique bounded tag, issues creation once after
durable delivery, and records a same-run creation witness and actual native
reference/base/incarnation. Only a successfully created registry entry can pass
later binding or preset ownership guards. Use exactly the returned actor pair in
the next explicit request. A changed world/actor, absent or failed witness,
existing actor or unknown creation outcome refuses further mutation; no implicit
replacement or replay occurs. The owned game ends through ordinary restoration;
the loop does not issue an unsafe later Delete against a possibly reused ID.

The semantic assign/clear/configure/disable/refresh morph-preset route also
requires this frozen fixture policy and the same creation-witness guard before
its existing native metadata/incarnation checks. Preparing these interfaces does
not establish actual race change, applied OBody/CLAW morphs or rendered NPC
appearance. Those native paths still require independent live qualification.

## Completion, uncertainty and stopping

The loop durably claims a request, validates its source/type/schema/policy, records
delivery, then invokes the tool once through the current `session.tool`. It logs
the returned result and records completion separately. No action is polled,
automatically repeated or inferred successful from transport receipts. The
executor reads the actual current scene and native menu flags before each
mutation and applies the same shared `gameplay_ready` predicate as ordinary
bootstrap. A blocking menu, unavailable contract or insufficient remaining lease
budget rejects the action without executing it. These sequential guards are not
an atomic engine-world transaction. The
remaining session window and claim lease further bound each call. A wrong source,
raw ASR, malformed JSON or unsupported request is recorded as rejected with
`executed:false` and completed without calling a game tool. The same finite hold
continues; rejected commands are not successful subject checks. Raw ASR text is
never parsed as an action. A late return, unknown/lost result, bus storage/claim
error, heartbeat failure or game identity loss ends the loop with a technical
reason and retains uncertain delivery records for explicit review. Later queued
actions are not executed after such a failure.

Results up to 16KiB remain unchanged in the completion receipt. Larger JSON
results, including full preset catalogues, are preserved without truncation as
exact canonical UTF-8 JSON bytes in
`<run>/interactive-results/<command UUID>.json`, with a 16MiB maximum. The file
is atomically created without overwriting another result, verified, and saved in
`state.interactiveArtifacts` before completion. The bus receives a compact
`{outcome:"result-recorded",evidence:{path,sha256,bytes,format:"json"}}` reference.
The run collector pins the registered file; a reference is not a subject verdict.
Duplicate evidence publication verifies identical bytes. Oversized data, changed
existing evidence or a failed write/save stops with uncertainty and never retries
the action. Small results retain their ordinary JSON shape.

To end normally, submit a new uniquely identified envelope to the same current
machine session whose text is:

```json
{"schemaVersion":1,"operation":"finish"}
```

The finish receipt returns control to ordinary teardown/restoration and copied
profile archival. Reaching the finite deadline also ends the hold; it never
extends the window, reopens a game or starts another attempt. An ordinary stopped
or failed loop does not bypass restoration, release an old Polygon hold or grant
a new game launch. Keep raw evidence and report actual outcomes separately from
owner acceptance and subject-test success.

If any owned keyboard down was attempted, normal finish and failure both perform
one bounded three-second cleanup: `releaseAll` for exactly this run's owner and a
status readback. No force/all-owner operation is used. Empty failed/pending lists
and no matching owner in the returned held-key inventory are required before
recording `keyboardRelease.verified:true`. Missing/changed native identity prevents
touching a foreign game; failed or unavailable release evidence is retained and
never converted into success. The keyboard's own finite leases remain a separate
safety limit. Cleanup neither interprets another command nor replays a mutation.

