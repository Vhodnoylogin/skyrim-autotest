# Owned controller collision preparation: SE1.7.104 candidate

The reference setter `TESObjectREFR::SetCollision(false)` in pinned
CommonLib0c95630 only sets a form flag. A retained SE qualification demonstrated
78 fresh reads with AI/reference collisions off but character-controller
collisions on. Waiting longer or accepting the reference flag cannot fix this.
The added `CharacterCollision.h` adapter performs the missing native call.

## Verified ABI and limits

Static analysis used the exact executable SHA256
`846efccf0c1374d71f892907f46549560f2fcb0a75cb87a3eed438baa0f1402f`
and address library `versionlib-1-7-104-0.bin` SHA256
`8aab3dd251d135b849bd983f86a4a205c920fa3e81f8e30c0e63ccfef9423842`.
The address library's format5 dense RVA array starts at byte96. These are
external inputs; no game binaries, address-library data or SDK is vendored here.

| Actual controller base vtable | AE address-library ID | Getter08 RVA | Setter09 RVA |
| --- | --- | --- | --- |
| `bhkCharProxyController[1]` | 240560 | 0x1098B80 | 0x1098C10 |
| `bhkCharRigidBodyController[0]` | 240580 | 0x109B270 | 0x109B320 |

Both setters consume a uint32 filter in EDX with the controller base in RCX.
CommonLib still declares slot09 as `Unk_09(void)`; calling that declaration would
use the wrong signature. The authored adapter calls the verified typed virtual
slot on an exactly recognized table, resolved through CommonLib's existing
vtable/address-library identifiers. The RVAs above are evidence, not call targets
embedded in the implementation. A different runtime or hooked/foreign vtable
is rejected before AI/reference/controller setters. Slot09 must also equal the
verified setter ID79148(proxy) or79200(rigid), both before freeze and immediately
before dispatch under the lock. The checked pointer is captured for the call.
Replaced targets are rejected; inline hooks at the same address are not detected.

The proxy setter invokes the engine filter-update path. The rigid setter writes
its live filter under the native world lock. No extra speculative broadphase
refresh is added. An outer `BSWriteLockGuard(world->worldLock)` spans fresh
getter, `CFilter::SetNoCollision(true)`, setter and exact readback. The exact
engine's recursive read/write lock ownership was checked independently. This
retains a continuous read/modify/write boundary even for the proxy path.

For the retained sample `136445982 / 0x0822001E`, the requested value is
`136462366 / 0x0822401E`; all bits other than14 remain unchanged. The controller
and world are retained, and their current identities are rechecked before use.
UUID consumption, partial-effect uncertainty and the prohibition on replay remain
unchanged. A fresh independent `visual_state`/inspection must still show AI off,
reference collisions off, controller collisions off and the separate DontMove
hold before matrix measurements. Read-only observations never repair state.

This is an SE1.7.104 source/build candidate. There is no live qualification from
static disassembly, fake dispatch tests or compilation. Other SE/VR versions are
unsupported for the expanded freeze action; ordinary control/read paths retain
their existing policies. Native filter readback does not prove absent contacts
or assess visual quality.

## Reproduce the build without installation

Acquire the same complete source/dependency composition described in
[the menu-QUIT recipe](devbench-menu-quit.md): DevBench5068162, CommonLib0c95630,
cpp-mcp f1117d5 and OpenVR60eb187, the exact external provider API headers, and
the guarded native QUIT patch52f0c4c. Keep foreign sources/tools/generated
outputs outside Git. Stage the authored provider from this revision before
applying QUIT; `tools/apply_devbench_morph_provider.py` now also copies
`native/devbench/CharacterCollision.h` into the host's `src/`.

For an already retained, verified candidate04 source closure, copy it into a
new external build directory without `.git`, `.xmake`, build caches or SDK
libraries. Replace only `src/NPCPersistence.cpp` and add
`src/CharacterCollision.h` from this revision. Require all remaining source,
dependencies, host integration and menu files to retain their hashes. Use the
same external API headers, pinned Xmake and no-deployment/no-prebuilt environment
and flags from the menu recipe. Build CommonLib and the plugin from source.
Retain source closures, compiler/link commands, DLL/PDB and test logs/hashes.

The focused native probe is `native/tests/character_collision_test.cpp`. Compile
it with MSVC C++23, include directories `native/devbench` and the pinned
CommonLib `include/`, force-include `<cstdint>`, `<utility>`, `<string_view>`,
`<string>` and `<format>` for standalone SDK compilation, and link that SDK's
actual `src/RE/C/CFilter.cpp`. It exercises this
production adapter against fake engine/vtable/world seams: both table variants,
the retained filter, unrelated bits, idempotence, unsupported inputs, controller
replacement, ignored writes, changed bits and a lost setter return. These seams
are explicit and do not exercise a running Havok world. The existing Python
visual-freeze/matrix tests retain fresh-read and no-replay coverage.

## Minimum separately authorized qualification

Keep the exact candidate04 executor/deadline implementation and
`se_shutdown:"main-menu-v1"`; change only the explicit provider source/hash in
a **new** immutable plan. Preserve old run files, command intents, accounting
and source custody. This document neither installs a candidate nor clears holds
or authorizes a game session.

1. Verify the exact runtime, source profile, input pins and new loaded DLL.
   Reach common startup/world/gameplay readiness before actor actions.
2. Create one witnessed persistent NPC, settle placement, retain a fresh
   AI/reference/controller/world/root observation, then issue one freeze UUID.
3. Require the receipt's requested filter to equal before OR0x4000 and its
   observed filter to match. Require fresh visual-state/inspection reads across
   ordinary frames with the existing strict frozen predicate and DontMove hold.
   Failure or a lost ACK stays uncertain: collect, do not replay that creation.
4. Prove the second actor and player were not changed by freezing the first.
   Prepare the second actor separately; do not infer roster-wide success.
5. Only after this gate passes, proceed with the origin's unchanged race/model
   transitions and owned save/load/remap. Reobserve and prepare new controller
   instances using fresh guards and new commands after completed operations.
6. Exit through the required native Main Menu route, verify process ending and
   restoration, and collect technical evidence separately from mod results.

A failed gate is a tool failure before matrix measurements. It cannot justify
changing CLAW's runtime or claiming CLAW morph coverage.
