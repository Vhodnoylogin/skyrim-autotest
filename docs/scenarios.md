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
local driver status. Tool errors fail immediately. Assertions are based on
returned data, never inferred from requested actions.

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
access. After a load/generation transition, dynamic reference substitutions are
invalid: submit another fixture/scenario rather than reusing a prior FormID.

Example post-step: inspect world_observer with
`{"kind":"world_observer","physics":{"refs":[{"$state":"probeObject"}]}}`.
Use the provider's actual capability, availability, phase, generation and event
sequence fields for assertions. A collision object or changed bone position is
not a raw contact. Physics transport uses the provider's declared metadata and
is not hardwired into the executor.

Orders contain schemaVersion1, unique id (`[a-z0-9][a-z0-9-]{0,79}`), owner,
subject, profile and scenario (relative to the order file). Submission pins the
scenario hash; changes require a new id. Ordered -> running -> reported is the
local queue lifecycle; explicit owner acceptance may close a reported order.

## Explicit background physical VR testing

The default physical probe requires the owned game to acquire Windows foreground.
Optional `allowBackgroundVR:true` permits the probe to attempt physical testing
when Windows denies focus, only with driverBackend=file/inputBackend=driver.
The actual foreground result and owned-window/thread diagnostics are recorded.
This does not enable background keyboard/UI automation or change Windows policy.
Both-hand movement, exact-reference grip, stable hold, release and world-presence
assertions are unchanged. Only their observed outcome can qualify that session;
background permission, an advancing health frame or frame publication alone is
not proof. An inactive/paused game must fail its existing response assertions.
