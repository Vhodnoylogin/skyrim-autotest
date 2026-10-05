# Scenario and order contract (schemaVersion 1)

A generic scenario contains `name` and nonempty `steps`. Each step needs `name`,
`tool`, `args` (object), a finite `timeout` in (0,180] seconds (default20), and
`assert` rules. `observe:true` allows an explicit observation-only non-polling
step; the whole scenario still needs at least one non-driver assertion.

Each assertion has a dotted JSON `path` (numeric list indexes allowed) and exactly
one of `equals`, `contains`, `min`, `max`, or `exists`. Bounds require finite
numbers, not booleans. A missing path fails; `exists` checks a present field's
non-nullness. Engine tolerances must be explicit in the test's chosen bounds.

```json
{
  "schemaVersion": 1,
  "name": "Owned world is readable",
  "steps": [
    {"name": "state readable", "tool": "inspect", "args": {"kind": "state"},
     "timeout": 20, "poll": true, "assert": [{"path": "", "exists": true}]}
  ]
}
```

Tools other than `driver` route through the fresh owned game's DevBench endpoint.
Choose fields from that installed API's actual structured response. `poll:true`
is allowed only for inspect, menu list/describe, input status/capabilities and
local driver status. Tool errors fail immediately except one bounded case:
polling an `inspect` `world_observer` snapshot may repeat a structured
`ok:false,outcome:"abandoned_before_start"` read. This means the producer did not
start that read; each response and retry remains in the session log. Discovery
(`action:"capabilities"`), mutations, unknown HTTP/tool errors and reads already
started are never automatically repeated. All attempts share the original step
deadline; a late positive result still fails. Assertions are based on returned
data, never inferred from requested actions.

The built-in `vr-hand-probe` has a separate test-cell readiness wait after its
one-time `coc` command. Only that `inspect kind:scene` wait may repeat HTTP
500/502/503/504 responses from `api/tool/inspect`, or a structured scene read
with `ok:false,outcome:"abandoned_before_start"`. These responses are candidate
readiness failures, not a diagnosis of the server. Each keeps its status/body
or structured result in the log. All attempts share 90 seconds, including
owned-process health checks; a late response cannot pass. Matching scene data
must then remain stable for more than four seconds, with errors or a different
cell resetting stability. Persistent failure stops and restores the run.
Health/identity errors, transport loss, malformed responses and other tool
errors remain terminal. This exception does not repeat `coc`, loading, scenario
assertions, or a whole run, and does not apply to generic scene assertions.

`tool:"driver"` supports:
- `args:{"action":"status"}`: local publication state; no hardware ACK.
- `args:{"action":"release"}`: zero pressed/touched/axes, preserve pose.
- `args:{"action":"publish","holdSeconds":1,"frame":<full frame>}`: finite
  lease (0,30] seconds. Each hmd/left/right role has a 12-element row-major 3x4
  absolute rigid pose matrix with translation in metres. Left/right additionally
  have controller `{pressed:<uint64>,touched:<uint64>,axes:[[x,y],...5 pairs]}`.
  The file backend currently maps Vive grip(bit2), trackpad(bit32), trigger(bit33)
  and axis0 X/Y, axis1 X trigger. Extra abstract axes are not qualified controls.
  Matrices require orthonormal positive-determinant rotations; axes stay[-1,1].

Frame publication must be followed by actual game/mod response assertions.
The guardian maintains the frame only while the owned runner remains healthy,
and releases controls at lease expiry within the next one-second heartbeat.
A 0.1-second lease therefore does not promise a precise 0.1-second pulse. The driver's file-reader lease separately
expires after5seconds if publications stop.

A physical integration scenario uses `kind:"vr-hand-probe"`, safe `cell` editor
ID, optional `object` base FormID, `button:"grip"`, `runtimeHiggs` and an authorized
fixture `{saveStem,essSha256,skseSha256}`. Copies are loaded in the isolated
profile; originals are never written. `poseOnly:true` is a narrower motion probe.
`postSteps` extends the built-in probe with generic assertions. Exact typed
objects `{"$state":"probeObject"}` and `{"$state":"id"}` are substituted in
args. There is no string interpolation, expression evaluation or arbitrary state
access. After a load/generation transition, typed dynamic reference substitutions fail
closed: submit another fixture/scenario rather than reusing a prior FormID.
The spawned reference remains live throughout postSteps and is discarded by
owned game shutdown, without a later Delete call that could target a reused ID.
Typed substitutions validate contiguous DevBench lifecycle events; event gaps
and unreconciled racing head counters invalidate the reference. Explicit game
loads, arbitrary console execution and known Papyrus world-changing functions
in postSteps invalidate it before mutation. Literal manually copied FormIDs do
not receive this typed-variable protection; never reuse them across a load.
Lifecycle validation and a subsequent request are separate operations; they do
not provide a producer-side atomic generation token for mutations.

Example post-step: inspect world_observer with
`{"kind":"world_observer","physics":{"refs":[{"$state":"probeObject"}]}}`.
Use the provider's actual capability, availability, phase, generation and event
sequence fields for assertions. A collision object or changed bone position is
not a raw contact. Physics transport uses the provider's declared metadata and
is not hardwired into the executor.
For a positive touching assertion, require a current-generation callback record
for the exact body/reference with signed separation <=0, speculative=false and
disabled=false. Arm the collector before contact-producing motion, inspect its
drop/gap/busy metadata and retain events. Speculative proximity alone is not
touching; empty collection is not absence of contact. Even a touching callback
does not promise the final solver impulse, settled state or deterministic timing.

Orders contain schemaVersion1, unique id (`[a-z0-9][a-z0-9-]{0,79}`), owner,
subject, profile and scenario (relative to the order file). Submission pins the
scenario hash; changes require a new id. Ordered -> running -> reported is the
local queue lifecycle; explicit owner acceptance may close a reported order.

## Explicit background physical VR testing

`kind:"vr-mobility-probe"` is a bounded diagnostic for minimal worlds without
VRIK/HIGGS. It enters the named cell, samples game-accessed OpenVR left/right
tracking, tests one left-trackpad forward input and one right-trackpad jump
candidate, and records actual player displacement/height. Optional
`keyboardDiagnostics:true` separately tests W/SPACE through DevBench's owned
bounded BSInputEventQueue leases; these are not physical-controller proof.
Failed prescribed controls remain failed checks while other bounded diagnostics
continue, then the run fails with the complete mismatch list. Tool errors are
terminal. No scripted player movement or jump substitutes for observed input.

Optional `observer:true` records the current player. A single owned firewood
reference is placed in the neutral hand-ray fixture; one physical trigger press
is sent only if the actual crosshair selects that exact reference. Inventory
pickup is distinct from HIGGS holding. If the ray is unavailable/misses, pickup
is explicitly unavailable, with no activation sent to an unknown object.
`physicalGrab:true` additionally executes the existing QASmoke hand/grip/hold/
release probe and therefore requires its VRIK/HIGGS dependencies. With a pinned
fixture that phase reloads the copied save once; no dynamic reference from the
mobility world is reused afterward. Minimal mode makes no HIGGS hold claim.
OpenVR tracking reads do not prove rendered hand animation. World probes use
engine units; tracking matrices use metres. Boolean scope options and safe cell
IDs are validated before launch. A fixture remains optional and pinned when used.
Common executor bootstrap runs before scenario dispatch. A scenario declares
its initial `cell` and/or pinned `fixture`; it does not implement startup UI.
The platform waits for the identified calibration menu in `VRPlayroom01`, sends
one bounded physical right-trigger press and observes the menu closing. It then
loads the pinned save once when provided, observes postLoadGame, selects the
declared cell once, and requires loaded scene data outside the playroom with no
calibration/main/loading/race menu or message box. Unknown UI receives no guessed
input. Readiness failures never replay load/input/coc mutations. The platform
logs `gameplay-ready` separately from subject assertions. A scenario with neither
cell nor pinned save cannot dispatch mod-test actions. This common path still
needs live qualification; API responsiveness alone cannot establish readiness.

The default physical probe requires the owned game to acquire Windows foreground.
Optional `allowBackgroundVR:true` permits the probe to attempt physical testing
when Windows denies focus, only with driverBackend=file/inputBackend=driver.
The actual foreground result and owned-window/thread diagnostics are recorded.
This does not enable background keyboard/UI automation or change Windows policy.
Both-hand movement, exact-reference grip, stable hold, release and world-presence
assertions are unchanged. Only their observed outcome can qualify that session;
background permission, an advancing health frame or frame publication alone is
not proof. An inactive/paused game must fail its existing response assertions.
