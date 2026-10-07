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

Implemented provider translations are scene/menu readiness, player health,
installed form lookup, exact reference/native loose stack quantity, inventory,
VRIK slot state, HIGGS held reference, existing Observer physics snapshots,
bounded physical controller poses/grip/release and explicit fixture-only
spawn/inventory/health/hand seeding. There is no subject-name switch. The current
fixture adapter supports one tagged reference and the explicitly accepted
placement specification. Dynamic-reference reads are protected by the existing
contiguous lifecycle cursor; a world change invalidates tags. This is not an
atomic engine generation transaction.

Reference stack quantity requires the owner DevBench fork's `quantityItems`
native field; a PlaceAtMe requested count is never substituted. Papyrus reports
numeric form types, so requested four-character type checks use inspect refs.
Base plugin/local identity is read from the actual base and installed mod name,
not copied from an expected item. Light/dynamic base IDs are unsupported here.

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
subsequent movement remains measured and bounded by the unchanged subject
maximum. The initial pose and configuration are separately pinned/qualified;
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
Keep the original request reach bound, dynamic reobservation, small increments
and exact HIGGS held-reference assertions. Live qualification is required.

Pose-and-grip motion interpolates rigid device poses in increments at most.01m,
with a50ms minimum settling interval. Previous controller buttons stay held during
the motion; requested grip changes occur at the endpoint. The original absolute
operation deadline and final pose/hold assertions remain mandatory. This avoids
teleporting a held object with a.9m hand jump; interpolation alone is not proof
of retained HIGGS ownership.
