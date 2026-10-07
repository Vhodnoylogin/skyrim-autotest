# Semantic platform backend

`platform` is an executor-local tool, not a new game HTTP endpoint. A Polygon
platform manifest can map polygon-actions/1 to `platform_mapping.operations()`.
The mapping is a candidate only; the operator must qualify exact source/binary,
configuration, request semantics and observed fields before dispatching mod work.
The originating mod order remains independent of provider selection.

The common executor must finish gameplay bootstrap before semantic requests.
Every operation keeps its enclosing step's absolute deadline. Nested DevBench
calls retain owned-process/health checks and raw evidence; mutations are never
retried. Only semantic read operations can poll. Unsupported actions, fields,
identities and units fail closed rather than becoming successful observations.

The actor/base/morph candidate additionally supports `quantity` selectors
`actor-base-identity`, `actor-base-weight`, `body-morph-storage`, and actions
`set-race`, `set-sex`, `set-weight`, `set-body-morph`, `update-body-model`.
Actor requests require exact hexadecimal reference and base identities. Native
Papyrus actor/base sex, race, weight and keyed NiOverride storage are observed;
Observer session/generation/runtime handle bracket reads. Player reads include
these actor fields alongside health. A different base or incarnation fails.
Mutations run once and only readback may poll within the original deadline.
Sex changes use one fenced `player.sexchange` only when actual sex differs;
non-player sex mutation is unavailable. Weight uses explicit 0..100 units and
morphs use dimensionless coefficients. Update completion means the native
NiOverride function completed and loaded actor data returned; it does not
certify renderer synchronization, TRI deformation or final physics. This
extension requires its own actual game qualification before activation.

The speech candidate maps ordinary native SpeechBroker availability, interface,
adapters, ASR source, registered namespaces, localized vocabulary and existing
utterance data. Recognition counts use actual nonempty text and native vocabulary
score strictly above the requested threshold; awards additionally require native
IsWinner. Reads never inject utterances, register participants or bid. Returned
utterance records retain the subject probe's fields and millisecond latency;
they use bounded read batches, not an atomic auction snapshot. Batches contain
only explicitly allowlisted getters, at most16 calls and four workers, bracketed
by the same owned game identity and one absolute deadline. Missing/failed items
fail the read; there is no setter, fallback or automatic request replay. A changed
utterance text between record reads invalidates that record. Optional configured
subscriber namespaces avoid routing generic reads through Demo Subscriber.

One ordinary SelfTest request is recorded durably before dispatch. The current
SpeechBroker.log must contain exactly one newly appended localized start token;
only its matching native pong message establishes roundtrip completion. Log
rotation/replacement, process change, overlapping starts or missing templates
are unavailable. Pending evidence is not completion. Request timeouts never
replay. This adapter requires live qualification with genuine audio/model output;
offline checks or native request completion do not attest speech recognition.

Enabling owned saves is a capability setting, not a requirement that every test
load a fixture. Prelaunch mapping challenges remain mandatory for pinned-save
scenarios and any declared owned save/load/restart action, including postSteps.
A new game with none of these skips only the unused challenge. Runtime native
save-directory and nonce verification remain mandatory whenever a save action
actually requests the MO2 alias; late undeclared use cannot waive those guards.

New Game's initial cell is selected by the game and installed alternate start.
The executor verifies fresh main-menu/loading/cell events against the actual
native loaded player/cell, then completes known character creation and quiet
initial-world readiness. Only afterward may it request the declared fixture
cell once and verify fresh final gameplay readiness. Initial world, fixture
transition and subject-test start remain separate technical facts. A save-load
lifecycle during New Game is still rejected; unknown character UI is not guessed.

Implemented provider translations are scene/menu readiness, player health,
installed form lookup, exact reference/native loose stack quantity, inventory,
VRIK slot state, HIGGS held reference, existing Observer physics snapshots,
bounded physical controller poses/grip/release and explicit fixture-only
spawn/inventory/health/hand seeding. There is no subject-name switch. The current
candidate fixture adapter supports up to16 independently tagged single-item
references per world and the explicitly accepted placement specification. Tags
are never overwritten, and reused reference IDs are rejected conservatively.
The legacy probeObject stores the shared lifecycle cursor anchor; consuming
that first item does not invalidate other tags. No reference-incarnation proof
is implied. The new multi-tag behavior requires separate live qualification. Dynamic-reference reads are protected by the existing
contiguous lifecycle cursor; a world change invalidates tags. This is not an
atomic engine generation transaction.

Reference stack quantity requires the owner DevBench fork's `quantityItems`
native field; a PlaceAtMe requested count is never substituted. Papyrus reports
numeric form types, so requested four-character type checks use inspect refs.
Base plugin/local identity is read from the actual base and installed mod name,
not copied from an expected item. The legacy path rejects light/dynamic bases;
the opt-in [runtime fixture candidate](runtime-fixtures.md) reads actual dynamic
base/source identity through the owner DevBench fork. Effective subject settings
and assignment counts use [native state bindings](subject-state-provider.md).

Physical reach measures a local tracking-to-hand transform using three five-
centimetre pose offsets; a singular transform or excessive reach fails. This
requires separate live qualification of geometry and control routing. Fixed
poses are issued input, not proof of reaching a pouch/mouth. Publication retains
the existing30second bounded lease across intervening reads, with explicit
release/next action and guardian ownership checks. It is not a driver ACK.

A platform can explicitly prepare open hands at configured
controller_start_positions_metres after common gameplay readiness and before
subject steps. This lets a floor fixture begin with hands near the floor rather
than spend its bounded reach lowering from a chest-height default. The actual
subsequent movement remains measured and bounded by the observed body workspace
and the original operation deadline. The initial pose and configuration are separately pinned/qualified;
there is no hidden pre-positioning inside a bounded reach or assertion waiver.

For explicitly configured automatic controller initialization, the common stage
focuses the owned game, enables normal player controls and verifies movement,
fighting, looking and activation before publishing the initial pose. Every
physical controller action rechecks owned foreground. A measured reach adds a
neutral interval and actual menu/HIGGS CanGrabObject observations before its one
grip transition. After the requested hold it logs the actual held reference;
failed acquisition records tracked input only after that interval, since reading
controller state may dispatch callbacks. Focus/readiness/publication do not
replace the subject's subsequent exact-reference assertions. This repair is a
candidate until live qualification proves its behavior with the pinned platform.

Gameplay checks request native menu flags through menu list includeFlags=true.
An open custom rollover name alone is not a blocking dialog. Actual pause/modal/
freeze flags block; cursor/menu-context ownership blocks a non-always-open menu.
Missing/unavailable/inconsistent flag records block conservatively. No unknown
menu is dismissed or permitted by a name whitelist. The new menu provider and
this classification still require a live pinned qualification before dispatch.

`hand.continuousHold.seconds` represents the elapsed interval of bounded samples
with the same exact HIGGS reference. Each sample rechecks lifecycle continuity;
more than0.5seconds between samples fails. The response retains every sample,
maximum gap, sampled basis and unobservedIntervals=true. This cannot prove the
absence of a drop/regrab between samples. An operator must not qualify it for
a subject requiring an atomic uninterrupted hold event stream. Missing physics,
contacts or final solver data remains unavailable, never an empty collision set.

The backend does not qualify itself, install/stage tools, load worlds, dismiss
menus, modify a source profile, release queue work or declare mod acceptance.
The new regressions verify missing identity/quantity, lifecycle invalidation,
one-time fixture mutation, bootstrap/deadline gates and read-only polling.
Live platform qualification and a conducted subject test remain separate facts.


Physical small-bottle approach keeps a candidate hand-node stand-off of12 game
units behind and10 above the observed reference. The earlier7/7 candidate pushed
the dynamic bottle before its grip edge in run20261007-105504-b826e7. This is
platform geometry, not a measured palm transform or selection acknowledgement.
Keep dynamic reobservation, small increments and exact HIGGS held-reference
assertions. Live qualification is required.

Pose-and-grip motion interpolates rigid device poses in increments at most.01m,
with a50ms minimum settling interval. Previous controller buttons stay held during
the motion; requested grip changes occur at the endpoint. The original absolute
operation deadline and final pose/hold assertions remain mandatory. This avoids
teleporting a held object with a.9m hand jump; interpolation alone is not proof
of retained HIGGS ownership.

Candidate `world.read` observation `form.alchemy` accepts a plugin/localId form
selector and requires actual ALCH type. It reads native Potion IsPoison, IsHostile,
IsFood, GetNumEffects and each effect's identity, magnitude, area and duration,
plus MagicEffect hostile/detrimental flags (1/4). At most32 effects are supported;
missing/wrong-typed values fail, never become false flags. `alchemy.effects`
contains index/runtimeId/detrimental/hostile/magnitude/area/durationSeconds.
`hasDetrimentalEffect` is the OR of actual effect flags, distinct from potion
poison classification. Requested names/types never substitute for these values.
These are sequential read-only queries, not an atomic form snapshot. Raw provider
responses remain in normal logs. Qualification must verify real healing, poison
and incompatible-effect identities before any subject filter test.

The next candidate supports `create_fixture_reference` quantityItems5 through
one native DropObject after adding exactly5to attempt-owned player inventory.
Actual GetItemCount must observe the staging delta and restored baseline. Native
inspect refs must observe quantityItems5on the returned single exact reference
before placement; no PlaceAtMe5or requested quantity substitution is accepted.
Mutations are never retried; split/null/incorrect-count results fail fixture
preparation. Only1and5are currently supported. `hand.held_item` now requires
actual native quantity on the sampled held reference and exposes
hand.quantity.items; HIGGS splitting a stack is visible, not hidden. This is a
sequential observation, not uninterrupted holding proof. Both changes require
new live qualification before the operator may deploy them.

Focus recovery candidate: a transient denied owned-game foreground request
releases active controls once, suppresses heartbeat/publication and waits up to
30seconds inside the existing phase/action deadline. Owned process identity is
rechecked by each native focus attempt. Successful recovery never restores old
buttons; if active controls were released, the interrupted action fails rather
than being replayed. Neutral startup can continue once focus is measured.
Explicit background physical routing remains opt-in; this does not authorize
background UI input. Timeout remains terminal with full logs and recovery.

Known startup notification answers use the owned DevBench native deferred menu
queue, not OS keyboard/mouse. Their route therefore requires no Windows
foreground. Exact current body/buttons, visible/native queue identity, replay
guards and actual closure/native progress remain mandatory; unknown modals still
block. This removes a redundant focus gate for that native operation only.
Physical controls retain explicit background policy and OS UI input retains
its separate ownership/focus requirements. New route requires live qualification.

Owned save/load candidate requires explicit allow_owned_save_load:true. Before
launch the common executor writes an absolute sLocalSavePath only in the owned
test profile Skyrim.ini. Every operation verifies the loaded native setting
matches that exact owned directory, rejects links/foreign profiles, and never
accepts a caller-supplied path or save name.

`input.perform` save_game/load_game take saveTag and scope:
owned-disposable-profile. Save tags are unique per attempt (limit8), names are
attempt-derived, and mutations execute once. Completion requires a fresh
contiguous SKSE saveGame event and a stable valid ESS/SKSE pair; Windows hashes
use exclusive read handles to reject concurrent writers. Evidence records native
event plus quiescent bytes, not an engine atomic save transaction. save.state
exposes completed, ownedByAttempt, essSha256, skseSha256. Changed generated bytes
fail before load. Both files remain archived in the attempt-owned profile.

Load invalidates existing tags before its one request, then requires ordered
unique preLoadGame/postLoadGame, same process identity, and the common executor's
quiet gameplay readiness and controller initialization. Old tag names cannot be
reused later in the attempt. lifecycle.state with afterSaveTag exposes worldReady,
pidChanged, generationChanged, oldReferenceTagsInvalidated. Generation denotes
observed native load transition plus executor epoch, never an atomic producer
generation. All nested common-readiness calls retain the action deadline.

Same-process save/load and the later restart_game extension each need separate
live qualification. No save/load capability is qualified by non-game tests. Operator must
qualify actual saved/restored inventory, generated hashes, ordered lifecycle,
common readiness, tag invalidation and full environment restoration separately.


Observed-body incremental reach candidate (owner-directed policy revision):
maximumReachMetres is retained as a legacy request field and logged, but no longer
acts as a cumulative travel cap from the hand's previous pose. A0.7m move can be
normal if both endpoints are in the avatar's workspace. This change requires a
new qualified platform; do not rewrite retained orders/packets. The new source
uses one Observer task per sample for exact target scene transform and the
first-person upper-arm, forearm and hand nodes. Native local model bounds are
transformed by observed row-major rotation/scale/translation, consistently for
approach and final pregrip validation. Missing nodes, units, handles, generations
or transforms stop before Grip; no fallback to guessed Euler angles or origin.

The generous shoulder-relative workspace radius is twice the observed arm-chain
length plus0.2m, capped at2m; invalid/extreme segment lengths stop. It allows
bending and VR-avatar variation and is not anatomical inverse kinematics. Each
motion increment is at most0.01m; unchanged absolute deadline,256increment hard
limit,5seconds without actual hand movement, native menus and exact HIGGS held
reference checks remain. Body workspace and incremental motion are candidate
observations until actual game qualification; input publication is never Grip
consumption proof. Initial calibration still uses three0.05m tracking probes.

Disposable fixture references receive separate20-game-unit-spaced initial slots
in a heading-rotated4x4 layout. One native spawn/drop and one initial MoveTo per
reference are retained. No item teleport or directGrabObject is used during
physical reach. Physics can move these objects after placement; stability is
not reachability. The next actual body/target sample is authoritative and rejects
an extreme target. Separate slots reduce initial overlap; they cannot guarantee
no contact or prevent inherited DropObject velocity.


Palm-cast targeting successor: qualification03 proved physical approach but the
actual HIGGS held reference was a neighboring wrong-effect bottle. The12/10
stand-off above is superseded. physical_grip_geometry is a pinned provider
configuration with palmPositionGameUnits[3], palmDirection[3] and
nearCastDistanceMetres. Obtain these from the actual winning HIGGS INI and pin
that input/source recipe in the platform. Runtime GetSetting(NearCastDistance)
must match; the executor never writes HIGGS settings. The HIGGS constructor
captures palm position, while hand rotation/scale come from current observed
first-person skeletal transforms. Left-hand X is mirrored as in HIGGS.

The next desired hand-node position puts the model-bounds center at the
configured palm near-cast endpoint. Conversion of cast metres to game units uses
the measured tracking Jacobian rather than a guessed70constant. Reobserve and
move incrementally; the cast model is not an acknowledgement of HIGGS selection.
Exact HIGGS held identity and native stack count remain mandatory afterward.
Missing geometry fails preparation/action instead of using the old stand-off.

Do not invoke DevBench input.observe between Grip and subject assertions. It can
dispatch controller callbacks and change the very state being tested. A mismatch
logs actual GetGrabbedObject identity and existing published/raw Observer data
without another controller read. This prevents diagnostics from erasing a
wrong-reference acquisition before the test observes it.

MO2 virtual-save successor: MO2 can override the prepared absolute setting with
`__MO_Saves\\`. A post-launch external nonce file was not visible during actual
qualification03, before any game save mutation. The successor stages a fresh
nonce copy of the pinned valid fixture ESS before launch. With owned local
saves/settings enabled, the game's default directory must enumerate that exact
nonce and successfully read its header. The owned copy/hash/path and expected
logical directory are rechecked before saves/loads. The probe is retained in the
archived attempt profile as evidence; it is never loaded. Generic relative paths
still fail. This attests observed USVFS mapping, not atomic filesystem ownership.
Original/global saves must remain unchanged and actual generated pairs must
still pass event/hash/completion checks. This successor needs game qualification.

`object.perform` tag_held_reference captures an already held actual reference,
bracketing an Observer runtime handle/session/load-generation read with native
HIGGS held-reference reads. It never spawns/grabs or assumes the drawn item is
the old seed. New tags cannot reuse existing/invalidated names. Later use checks
the captured incarnation, rejecting the same recycled formID with another handle
or changed session/generation. These sequential samples cannot prove continuity
between reads. Actual drawn-item qualification is required before deployment.

Owned game-only restart candidate uses the same input.perform scope/saveTag and
requires an already completed owned save pair. It releases controls, invalidates
old tags, preserves a separate before-restart log segment, requests one owned
game exit and one SKSE launch through the unchanged MO2 instance/profile. Only
the exact owned game may be forcibly stopped after its graceful deadline; foreign
processes block the transition. SteamVR/MO2/profile are not restarted. Fresh
matching process identity, DevBench frames/task queue, the common startup screen,
native save mapping, ordered load events and common quiet gameplay readiness
must all complete before another subject action. The original action deadline
is retained; the guardian's durable expected-exit window is <=180seconds and
never disables runner/deadline recovery. Incomplete transitions cannot replay;
the restart budget is derived from the exact frozen scenario before setup. Each
declared restart step owns one durable slot, including future settings-variant
steps only when their own implementation is supported. The next exact step and
unchanged scenario must match; replay, skipped slots, incomplete transitions and
an eighth restart in a seven-restart scenario fail before exit/relaunch. No budget
grants launch authority or extends a deadline. Every reserved segment is retained
and required by final collection; a missing segment fails collection independently
of safe restoration. Historical two-segment recovery remains supported. Restart,
saved inventory recovery, process
identity change, log segmentation and final restoration require live qualification.

Every owned lifecycle poll retains its raw response envelope with exact process,
requested cursor, load ordinal and restart ordinal before validation. Completed
loads preserve their ordered native event pairs and world epoch in append-only
attempt history and a completion journal record; later loads do not overwrite
earlier proof. Restart history also retains its matching load transition. A queued
or incomplete operation cannot be replayed. The SKSE loader has its own process
role and never counts as an actual Skyrim VR process.

Common readiness reads actual native menu flags, never a HUD-only menu-name
allowlist or image classification. Nonblocking overlays may remain open. It
requires an actual loaded player, nonempty matching world cell and eight quiet
seconds. Known startup notifications use their existing identity-checked native
answer path. In an already loaded world, known navigation gates (Console,
TweenMenu, Journal Menu, InventoryMenu, MagicMenu, MapMenu, StatsMenu,
FavoritesMenu) get at most one native hide request per readiness transition.
Verify closure, then restart the quiet interval. Unknown choices, unavailable
flags, main menu, loading and character creation are never generically hidden.
Physical actions check this common recovery before motion and again before Grip;
the original deadline and reference-generation checks remain. Reads never trigger
recovery and subject actions are never replayed. Game qualification must include
an intentionally opened navigation menu and actual successful physical action.

Before a game-only restart relaunch, enumerate and log exact residual processes.
Wait up to eight seconds for an already owned SKSE loader to exit naturally,
request one graceful close, wait three seconds, then permit termination of that
exact owned identity with creation-time recheck and four-second confirmation.
Foreign/unidentified/reused identities or unexpected games block relaunch.
All waits use the original action deadline. No other launch-chain process is
adopted or stopped. This repair requires live restart qualification.

An enumerated process may already have exited before its native identity read.
Unavailable identities trigger read-only bounded resampling, never ownership
inference or termination. Relaunch still requires the entire game/loader list
to become empty. A later readable foreign/reused identity blocks immediately;
an unreadable entry that persists beyond the wait blocks without any mutation.

Common startup and quiet-world reads may wait when the exact pinned DevBench
pre-execution timeout says a queued task was abandoned before starting. Supported
reads are inspect state/scene, menu list/describe and Papyrus describe. Retain
every failure and require an actual successful response within the original
deadline; cap the first postrestart task-ready observation at35seconds. Generic
HTTP504, started-task timeout, arbitrary server/transport failure and all
mutations remain terminal. This is a readiness wait, never a repeated launch,
load, button, answer or subject action. Eight-second quiet-world confirmation
still follows the successful native reads.

After a completed owned load, generic hand reads and newly captured held tags
use that load's current process, world generation and contiguous lifecycle
cursor. They do not require the invalidated old probe reference to become live
again. Old tags remain removed/invalidated. A later load, event gap, unreadable
stream, mismatched process/epoch or incomplete transition rejects the guard;
an observed invalidation is retained so it cannot be adopted by another read.
HIGGS hand reads and held tagging remain bracketed by lifecycle checks. Once a
fresh fixture binds a new probe, its existing creation-time lifecycle guard is
used. This is sampled sequential evidence, not an atomic world snapshot.


Common bootstrap checks are executor evidence, separate from subject checkpoints.
A newly recorded bootstrap check carries provenance with schemaVersion1,
component="skyrim-autotest", stage="bootstrap", role="tooling", the exact native
runId and a unique per-run checkId. It appears in state/result checks and a matching
executor-check event (name/result/provenance) in steps.jsonl. Consumers verify the
pinned same-run state, result and event before classifying auxiliary technical
coverage. The name or provenance flag alone is not proof. A technical check never
establishes subject start or subject coverage. Legacy artifacts stay unchanged;
missing corroboration remains unknown rather than silently becoming a tool pass.
