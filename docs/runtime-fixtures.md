# Runtime fixture candidate

These capabilities are implemented and checked offline, but not activated or
qualified in the installed game. Missing providers remain unavailable.

The owner DevBench fork adds `runtime_fixture` at source commit
`fa9c998868471aaa78c694f2e8759b4dc51c50be` in
https://github.com/Vhodnoylogin/devbench. CommonLib remains pinned to
`9106d402cfc7dcbc5bf7458be6748af19d7fc914`. Reacquire and build outside Git,
using a short output path on Windows:

```powershell
python tools/build_devbench_fork.py --runtime-fixtures --build-dir D:/svb-fixture-build
```

This is a separate opt-in candidate. The default recipe retains its previous
compatibility commit. The portable distribution includes our provider source
under native/devbench and its exact-base integration recipe under tools; the
wheel contains runtime clients/docs only. External DevBench/CommonLib source,
SDKs and compiled binaries are not bundled. Preserve their licenses. Build
manifests pin actual output and dependency state; another compiler/package
resolution is not a claim of byte-identical output or live qualification.

`native_runtime_fixtures:true` selects native identity reads. Identity echoes the
requested form/reference and reads the actual base FormID, type and source file
array on the main game thread. `create_runtime_potion` invokes engine duplicate
creation once, requires a newly registered FF-prefixed ALCH base distinct from
the static template, and verifies the actual absent/inherited source-file policy.
A new REFR of a static potion is insufficient. Owner/command creation intents
are retained before mutation, bounded32 per game; `creation_status` is read-only.
Unknown/started timeout results never trigger a repeated allocation.
Runtime tags are bounded16, process/world scoped, invalidated by loads, and never
reused after an uncertain attempt. Native duplicate/source-array behavior and
save/reload behavior need live verification; this adapter does not delete an
uncertain engine form or pretend creation is rolled back inside a running game.

Generic fixture placement measures all fourteen VRIK slot centers and the head
from actual scene transforms and native slot offsets. It checks separation
before allocating a form and again at the settled reference. These positions
are geometric exclusion, not evidence of absent contacts or a solver result.

`pose_hand_at_body_slot` similarly measures actual third-person bone transforms,
slot offset/scale and first-person hand motion. Small calibration probes and
incremental movement retain the original deadline and held input. Reach is
relative to observed body geometry; the old extra0.5m displacement cap is absent.
Mouth exclusion, extreme geometry, singular calibration and stalled progress
remain explicit failures. The other hand's input is preserved. Issued pose/grip
is not proof of physical acquisition: subsequent exact HIGGS identity and native
quantity assertions remain mandatory.

Before activation qualify the exact frozen driver/client/native builds together:
both ALCH source policies and real identities, placement/reach for both hands,
VRIK slot13/14 and rotated/scaled avatar geometry, genuine held-item/inventory
reads, each settings variant through common restart, and full restoration.
Source acceptance of all457 requests in retained order19 is only structural
coverage. New subject diagnostics require the origin's new immutable build/order.
