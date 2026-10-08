# Actor fixtures and passive contacts (candidate)

These generic operations require a separately qualified platform. Source support
and offline tests do not qualify the installed game. Existing platforms and
immutable subject orders are unaffected. Use Observer 0.2.5 for actor-state and
bounded-capture requests, and0.2.6 for reference scale percent; acquire/build it
separately, never vendor its DLL here.

`world.read` accepts an exact `actor: {plugin, localId}` and these observations:

| Observation | Extra request fields | Evidence |
| --- | --- | --- |
| `actor.scene` | none | Actual source plugin/local ID, live reference handle, loaded 3D and actor state |
| `scene.node` | `nodeName`, `perspective: "third-person"` | Actual engine world transform and worldBound in game units |
| `actor.skeleton_physics` | `nodeNames` (1..16), same perspective | Requested nodes and raw native rigid bodies with exact source-node mappings where available |
| `actor.contact_capture` | `afterSequence`, `maximumSamples` (1..256), `captureWindowSeconds` (0.1..60, whole milliseconds) | One nonce-bound, fixed-duration native capture |
| `actor.contacts` | `afterSequence`, `maximumSamples` | Reads the existing capture; cannot start or extend it |

Source plugin/local identity, runtime handle, Observer session and load generation
must remain consistent. Missing nodes return unavailable; absent collision bodies
are never synthesized from a skeleton node. The engine's worldBound is neither a
file/NIF radius nor proof of collision shape or rendered visibility. Physics
callbacks and main-thread scene reads are asynchronous, not one atomic sample.

Fixture actions require an operator-pinned `fixture_actor_allowlist` containing
at most16 exact selectors, an owned disposable test profile and completed common
gameplay readiness. The player cannot be a fixture target. Only allow expendable
NPCs in a disposable save. Preparation never rewrites base weight, base height,
reference scale or race to make a fixture pass.
The executor restores the profile/save files, not a persistent in-memory actor.

`object.perform prepare_fixture_actor` takes `actor`, `equipment: "unequip_all"`,
`expectedScale` (0.1..3, whole percent), `expectedWeightPercent` (0..100) and
`movement` (enabled or disabled). Expected scale is the stored **reference**
scale: actual native uint16 refScale percent divided by100. The engine GetScale
and scene transform can additionally include actor height (for example reference1
with effective1.03). Both quantities are retained separately; no hardcoded race
coefficient, changed tolerance or inferred echo substitutes for the native field.
Initial reference scale and base weight must match before any fixture mutation.
Only SetRestrained and UnequipAll execute once; reads verify actual equipment and
restraint while requiring the same base identity, weight, reference and effective
scales unchanged. A callback alone never passes preparation.
`set_fixture_actor_movement` takes actor/movement and verifies
native restraint. Disabled means restrained voluntary movement; external physics
can still move the actor. `push_fixture_actor` takes `source: "player"`, exact
`target` and `strength` (0.01..10). `pushCompleted` means the native Papyrus call
returned on the same live target; its explicit completionBasis does **not** prove
displacement, touching or solver acceptance. Use independent physical observations
for those effects.

One capture attempt per actor/run is durable before submission. Reads bind the
same nonce, reference, world, generation, subscription epoch and absolute native
start/end times. They never rearm, replay a failed start or change the sample
limit. The collector retains at most256 ring events per response, records gaps,
drop counts, truncation and original body selection, and preserves raw data.
Each positive normalized sample requires its actual callback phase, native time
inside the capture window, world/generation, increasing sequence and a selected
body UID. Signed separation is converted only with finite reciprocal native
bhkWorld scales; its raw Havok value remains available. Body selection changes
prevent a positive normalized contact claim.

After successful scenario steps, the common executor lets any remaining passive
window finish **before** closing the game, then verifies native window completion
and collects a final raw snapshot. This is evidence completion, not extra subject
checks or repeated actions. A conservative host wait never claims clock mapping.
Process/heartbeat loss stops waiting. Failed scenarios restore promptly and mark
unfinished captures interrupted. `actor-captures.json` and hash-verified raw
responses enter the ordinary evidence manifest. Missing/tampered required files
fail collection without preventing restoration.

Empty samples never prove no collision. Callback delivery, speculative/disabled
flags and a completed window do not prove continuous contact coverage or final
solver use. Sleeping bodies, callback delays, drops and unsupported character
proxies remain explicit limitations. No target mod's filters/impulses are altered
by observation.
