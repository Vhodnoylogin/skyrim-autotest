# SE matrix lifecycle candidate

Compound semantic steps retain their original absolute monotonic deadline, even
when the scenario allows 60, 90, 120 or 180 seconds. A strict fixture/binding,
inspection or freeze primitive receives at most 30 seconds from the remaining
parent budget; an owned load retains its existing 90-second primitive bound.
Each external native evaluator (baseline or hypothetical counterfactual) receives
at most 30 seconds from the freshly checked remaining parent budget. Its input
pin checks and both CLI commands share that one child budget.
Creating another child budget never extends the parent or retries a command.
Public direct bindings still reject deadlines over 30 seconds. An uncertain
creation/load intent remains terminal and is never treated as a completed actor
or as proof that no side effects occurred. These bounds require exact live
qualification before replacing an installed platform.

This additive source capability supports exactly two owned persistent NPCs,
without calling OBody or requiring its assignment/generation service. It is an
offline-verified candidate. It is **not a qualified installed platform** and
does not select the global Polygon configuration, install a provider or start
a game. The legacy six-NPC/OBody morph session is unchanged.

Use the ordinary executor's completed common startup/readiness stage. Freeze
the source profile, winning body resources, subject build and installed native
providers separately. The subject's two-actor fixture remains unchanged; do not
pad it to six. Global AI/collision control is not required by the corrected UNP
fixture. The adapter supplies no new startup route and does not adopt actors or
accept old FF references.

## Configuration and binding

Add `matrixLifecycle` to either `native_session` or `interactive_session`, with
`nativeBindings` and `npcPersistence:true`. Do not also declare `morphSession`.
The edition must be explicitly `se`. Required matrix fields:

| Field | Meaning |
|---|---|
| `maximumFixtures` | Integer `2`, exact owned creation/save roster |
| `beastRace` | Actual allowed race FormID; original human race is independently witnessed at creation |
| `bindings` | Role to an existing frozen native binding ID |
| `sourceMorphs` | Complete ordinary source-name catalog; `[]` is valid for weight-only bodies |
| `traitSources` | Explicit supported `$human.face.*` / `$human.height` scalar catalog |
| `publicTargets` | Complete public target catalog, including inactive/zero outputs, maximum64 |
| `ownKey` | Actual subject contribution key |
| `evaluator` | Pinned external native executable/XML, described below |
| `counterfactualSourceMorphs` | Optional frozen ordinary names for hypothetical offline controls; these are never claimed observed |
| `freezeActors` | Optional explicit Bool; `true` prepares and measures per-actor AI/collision-off plus locomotion hold |

Required binding roles are `status` (Int), `error` (String), `humanWeight` and
`beastWeight` (Float), `hasHumanTrait` (Bool, extra String parameter),
`getHumanTrait` (Float, extra String), `configure` (Bool, extra String),
`refresh`/`clear` (Bool), and `race` (Actor.SetRace with observed race completion).
Every role has exactly one guarded owned actor. The existing frozen-binding
metadata checks validate the real native signature before invoking it.

The optional `selectedFamily` role is a read-only actor-to-String callback.
For CLAW it requires the separately built/installed `GetMorphFamily` producer
addition. `GetAssigned` is not a substitute: it returns empty for an enabled
matrix link. Omit the role until the actual provider has been independently
qualified; observation reports `available:false,value:null`. Neither the
requested family nor the offline CLI profile is in-game selection evidence.

`configure`/`refresh` return queue admission, **not completion**. Read status,
actual selection and independent raw outputs afterward. Cached human traits
are explicitly identified as subject diagnostics, not independent measurements
of engine head/stature or rendered appearance. False availability retains null;
the callback's arithmetic return is recorded separately and never becomes zero
observation evidence.

## Actions and observation

### Per-actor inspection preparation

For an inspection fixture requiring AI/collision-off, freeze `freezeActors:true`
in the matrix policy and include one exact native `Actor.SetDontMove(Bool)`
member binding (mutate, None, actorSelf, native-return) in `nativeBindings`.
Omitting the option preserves the prior matrix path. It never means global
AI/collision state, and no console toggle is issued.

After each ordinary persistent creation, the same once-only semantic action
uses [the existing visual-freeze protocol](visual-freeze.md) before returning
preparation success. It independently reads AI, the reference collision flag and
the current character-controller CFilter. All three must be off; actual
`dontMove` must also be true. A missing controller is unavailable. A false
reference flag with an enabled controller is incomplete and cannot admit a
baseline. This source candidate does not assert that the public reference setter
will change the controller filter on every runtime; exact engine qualification
must establish that before the platform is selected.

Race/link operations and the owned remapped load reapply this preparation under
their own durable transition identity. One load can prepare both actual creations;
it cannot replay a command on either actor. A lost ACK, partial state or timeout
keeps an unsettled intent and blocks further matrix writes. Read-only diagnosis
remains possible. A queue-admitted refresh/configure is still not completed work:
subsequent observations must witness the actual settled subject state and freeze.

Matrix measurements and actor inspections bracket the entire current owned
roster with fresh freeze/hold reads and compare process/world/race/root identity.
They never issue repair setters. A model change or reset freeze blocks the
measurement without retaining a baseline; prepare explicitly with a fresh
`object.perform` request using domain `actor-visual-freeze`, action
`freeze-owned-reference-once` and the owned `actor.fixtureTag`, after any earlier
transition has completed unambiguously. This does not replay an uncertain action.
The corresponding `world.read` uses only domain and actor and reports actual
state. For naming/unequipping/holding through `actor-fixture-inspection`, use
`collisionPolicy:"preserve-current"`; those actions preserve the verified off
state. The earlier retain-enabled inspection path remains available separately.

Results retain `inspectionFreeze`, `fixture.visualFrozen`, `fixture.dontMove`,
`actor.aiEnabled`, `actor.collisionsEnabled` (controller) and
`actor.referenceCollisionsEnabled`. Raw inspection and visual-state envelopes
remain separate. These sampled facts are not proof of continuous immobility,
absent contacts, stopped animation or disabled third-party physics.

### Owned lifecycle

Existing `actor-fixture`, `actor-fixture-identity`, `actor-race`, `morph-link`,
`actor-fixture-inspection` and `save-state` semantics use the new opt-in route.
Creation uses `maximumCreations:2` and the existing persistent, bounded relative
placement contract. Both adapter and global fixture registries must cover exactly
the same owned attempts. Every creation/race/family/save mutation retains its
durable once-only command identity; uncertain actions are never replayed.

One save/load retains exactly those two creation witnesses. Native form and VM
remapping, exact roster verification, same-process ownership, common postload
readiness and atomic registry rebinding remain mandatory. No new SKSE persistence
ABI is needed: the existing native provider already accepts nonempty rosters
up to16, while this adapter admits exactly2.

The new read-only domain is:

```json
{"operation":"world.read","request":{"domain":"actor-matrix-state","actor":{"fixtureTag":"OwnedFemale"},"stage":"human","captureSnapshot":"human-before","familyId":"EXACT_FAMILY_ID"}}
```

For `stage:"beast"`, supply `baselineSnapshot:"human-before"`. The baseline
must be from this same actor creation/process/family and its witnessed original
human race; the current race must equal the configured beast race. Loads resolve
the current actor through the existing native remap, never by an old reference
number. Snapshot labels are immutable: collect a new label for another read;
do not poll or reuse a label after an uncertain observation.

The result preserves complete requested SKEE aggregates, name presence and
every enumerated contribution key, identity/world/model stamps, actual raw and
normalized NPC weight, typed trait availability, selected family, raw callback
diagnostics, native inputs/predictions and all requested target values/presence.
Reads bracket native callbacks and external evaluation with independent SKEE
samples. This is sequential observation, not an atomic engine snapshot or global
discovery of every morph name. Failed/truncated/unavailable reads never become
an empty source map.

`matrix.mismatchCount` counts float32 coefficient differences across the full
target catalog. Also assert `matrix.nativeParityAvailable`, observed family,
status, source/weight/trait preservation and the scenario's expected identities.
Numeric zero is distinct from key absence: use `ownKeyPresentCount` and
`zeroExpectedOwnKeyPresentCount` for removal/zero-ownership requirements.
Missing baseline input traits remain unavailable even if a later sample has them.
Functional mechanism evidence does not establish visual quality or physics.

`platform_mapping.matrix_operations()` exports the explicit candidate fields,
including the complete vector objects. `operations()` remains unchanged. The
operator must freeze/qualify its own exact SE mapping/attempt plan; this function
does not promote a candidate or rewrite the old VR platform.

## Native prediction and counterfactuals

`evaluator` contains absolute `executable`, `matrix`, `executableSha256`,
`matrixSha256`, and optionally `sourcePins:[{path,sha256}]`. Acquire/build the
subject's existing shared-native CLI separately and pin the same matrix and
kernel/conversion source closure used for the game build. Keep external programs,
XML selections, binaries and SDKs outside this repository. Do not copy matrix
arithmetic into the executor.

The current CLI source is [CLAW](https://github.com/Vhodnoylogin/claw), target
`claw-preset-tool` in `src/main/cpp/CMakeLists.txt`. Obtain the exact subject
revision and configure a fresh external CMake build from that source directory;
build only `claw-preset-tool` in Release. This engine-independent target links
`claw-preset-core`/the shared kernel and the source-pinned pugixml dependency;
it does not need SKSE plugin loading. Follow that revision's build README,
retain compiler/CMake/dependency/source pins and hash the resulting executable.
The candidate's reviewed external executable is an input, never vendored in
Autotest Git or silently downloaded by the runtime.

The provider runs `matrix-info XML FAMILY` and
`matrix XML FAMILY --actor-weight-raw WEIGHT` under one deadline, using explicit
tab-separated source/value stdin. It verifies file pins before/between/after
calls, the family graph, finite float32 inputs/results and complete native output
coverage. Failed execution or changed/missing inputs is unavailable. The caller
must also verify this frozen XML equals the actual installed matrix winner.

The observer can include `counterfactual:{weightRaw:100}` or
`counterfactual:{sources:{"EXPLICIT_FROZEN_CONTROL_NAME":0.75}}`. These change only
the external native prediction, hold other baseline inputs fixed and retain a
separate hypothetical result. They perform no SKEE/game write. A noninterference
claim requires a genuinely changed ordinary input; an empty override is no proof.
Unavailable human traits follow the native evaluator's neutral-input diagnostics,
remain unavailable, and cannot qualify complete observed-input parity.

## Remaining live qualification

Before selection as a testing platform, the environment owner must separately
admit the exact installed SE composition and test: common startup/readiness;
two independent persistent creations with measured distinct weights and body VFS
winners; raw available-empty source reads and target/trait/selection metadata;
race/refresh and shared-native parity; one exact two-actor save/load/remap;
return/retransform; original source/key preservation; ordinary menu exit and
complete restoration/collection. Failed provider metadata or unavailable family
remains a preparation limitation. Offline tests do not release a game launch,
install files, create an order or establish mod acceptance.
