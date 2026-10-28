# Bounded SE gameplay

The `se-gameplay` platform domain operates inside the executor's existing owned
SE process, disposable profile and current guarded world generation. It creates
no second game owner. Native input acknowledgements and actual gameplay
observations are recorded separately. Offline tests do not qualify a provider.

Requests use `tool: "platform"` with `operation` and `request`. Every request
contains `domain: "se-gameplay"`; only the following exact fields are accepted.

| Operation | Action or observation | Additional request fields |
| --- | --- | --- |
| `input.perform` | `action: "move"` | `direction: "forward"`, `"back"`, `"left"` or `"right"`; `durationSeconds: 0.05..1` |
| `input.perform` | `action: "inventory-open"` or `"inventory-close"` | None |
| `input.perform` | `action: "weapon-draw"` or `"weapon-sheathe"` | None |
| `input.perform` | `action: "pickup"` | `referenceTag` |
| `input.perform` | `action: "equip"` or `"unequip"` | `referenceTag`, `mechanism: "papyrus-native"` |
| `input.perform` | `action: "attack"` | `actorTag`, `durationSeconds: 0.01..0.15` |
| `object.perform` | `action: "create-pickup-fixture"` | `referenceTag`, `item`, `distanceGameUnits: 50..120` |
| `object.perform` | `action: "create-combat-fixture"` | `actorTag`, `base`, `distanceGameUnits: 60..100` |
| `world.read` | `observation: "snapshot"` | Optional `item` |

An `item` has exactly `plugin`, nonzero hexadecimal `localId` and `type` (`WEAP`,
`ARMO` or `MISC`). A combat `base` has exactly `plugin` and `localId`; its actual
resolved type must be `NPC_`. Plugin selectors accept ordinary `.esm`/`.esp`
files and full non-light static IDs. Tags are lowercase identifiers of at most
64 characters, starting with a letter and containing letters, digits or hyphens.
At most eight fixture tags may be attempted in one run.

For example, one bounded movement request is:

```json
{
  "operation": "input.perform",
  "request": {
    "domain": "se-gameplay",
    "action": "move",
    "direction": "forward",
    "durationSeconds": 0.2
  }
}
```

Every successful action returns `gameplay: {completed: true, action: ...}` only
after an actual readback. Movement returns observed before/after coordinates
and `movement.distanceGameUnits` (horizontal displacement of at least one game
unit). Menu actions require the opposite initial state and return
`inventory.open`. Weapon actions require the opposite settled state and return
`weapon.drawn`. Pickup returns the exact created reference and observed
`pickup.quantityDeltaItems` of one. Equipment returns `equipment.equipped`,
`runtimeId`, its explicit native mechanism and `menuSelectionProven: false`.
An attack returns `combat.healthBeforePoints`, `healthAfterPoints`, a negative
`healthDeltaPoints`, `targetAlive: true` and `attackInputs: 1`.

The snapshot reads current player health and position, the complete player
inventory (bounded to 256 base entries), actual equipped hand/ammunition forms
and inventory-menu state. An optional item is independently resolved and returns
`item.runtimeId`, `quantityItems` and `equipped`. It can therefore inspect a
retained static item after a save/load without using an old fixture reference.
Save/load and process exit remain the common executor's separate operations.

Before returning to Main Menu, this route reads SKSE's actual cached crosshair
reference. If nonempty, one native player `SetAngle(float,float,float)` aims
upward while preserving the observed roll/yaw. Two separately polled native
`Game.GetCurrentCrosshairRef()` None results are mandatory before world teardown;
no reference is deleted and no SKSE memory is patched. This releases the strong
reference while the actor/base data still exists. SKSE2.3.1's static
[`g_curCrosshairRef`](https://github.com/ianpatt/skse64/blob/25b72352adb6543fa6d0bd3795780672b2e238e0/skse64/Hooks_Gameplay.cpp)
otherwise can release an Actor during CRT teardown after base data is gone,
as observed in the retained1.7.104 quit dump. A surviving cached target or
uncertain aim receipt prevents another world/menu mutation; original-grace
observation and the existing guarded fallback remain distinct from success.
This adjustment happens after scenario checks, as common session cleanup.

The optional diagnostic `se_shutdown: "main-menu-v1"` uses native `Game.QuitToMainMenu`,
observes a fresh contiguous Main Menu opening, then invokes the unique enabled
stock `$QUIT` entry (index9) and its actual `MainConfirm` selection through the
native provider. Each transition has a separate durable, one-shot intent. Only
the exact final desktop-quit intent counts as an owned quit request; returning
to Main Menu alone does not. The entire route retains its original45second
bound on recovery, without replay. It requires the additive QUIT operations in
[DevBench 52f0c4c](https://github.com/Vhodnoylogin/devbench/commit/52f0c4ca92231226a99032b0e305f9cf6c3030a9).
A native callback or closed menu is not actual process-exit proof. Unavailable
menu/API state is retained before the caller's existing guarded fallback.
It is not the default exit route: the live pitch adjustment did not clear the
cached target within its bound. That failure is retained; use the window route.

New SE templates and the setup example select `se_shutdown: "window-close-v1"`.
It posts ordinary `WM_CLOSE` only to windows whose current PID/birth/path still
match the owned game, saves the single request intent and native window receipts,
then waits up to30seconds on the original bound. A receipt needs at least one
accepted typed WM_CLOSE; it is never process-exit proof. Actual verified exit0
and no forced stop are still required. Recovery and later cleanup do not repost
the request. A failure can reach the existing guarded force fallback, which
always fails technical execution. Unknown termination also fails execution while
retaining passed scenario checks. This route needs no desktop focus or in-game
quit interface. Existing configurations without the policy retain legacy QQQ.

SE cleanup records one owned quit request and waits for its original bounded
grace before considering the existing window-close fallback. Recovery never
replays that request or extends its deadline. `gameTermination` comes from exact
native process-exit observations: nonzero or forced game exit fails technical
execution even when all action checks passed. It does not rewrite those checks.
Normal closure requires observed exit0 plus an owned quit request; missing exit
telemetry remains unknown.
After the quit request, read-only exit polling keeps the retained game handle
and captures its final code before another shutdown guard can fail. Strict
foreign-session checks still precede all process/file actions. An unidentified
snapshot row for an owned process or child may be reobserved within the existing
two-second bound; parentage never permits adoption or termination.

SE owned loads also read the game's actual localized confirmation strings and
observe message-box opening events during the original load deadline. A matching
discard-progress confirmation gets one recorded answer; unknown/corrupt/content
warnings retain their exact native body/buttons and fail immediately. An answer
does not replace ordered pre/postLoadGame or the restored-equipment assertion.

The corrected provider load path is published in the owner DevBench fork at
commit `b734f6de888e73db2148eae411f276355ed6f883`:
[source](https://github.com/Vhodnoylogin/devbench/commit/b734f6de888e73db2148eae411f276355ed6f883).
It keeps named-file validation and requests native `Game.LoadGame` through SKSE's
event-processing route. It does not suppress content warnings or establish load
completion. Reacquire/build the source with the fork's
[provider build instructions](https://github.com/Vhodnoylogin/devbench/blob/b734f6de888e73db2148eae411f276355ed6f883/docs/autotest-provider-tools.md);
SDKs, headers, compiler/debugger binaries and DLL outputs remain external to Git.

## Native provider contracts

The native `input` tool must advertise `devbench.input` version 2.0, keyboard
contract version 1, `Skyrim.BSInputEventQueue` injection, DirectInput scan codes,
actual readiness, a key catalog and the bounded `tap` action. Each pulse uses
`owner: "autotest-<run id>"`; matching down/up generations, completed release
and a fresh empty held-key status are required. Unsupported mappings, an
existing synthetic hold, a stalled pulse or uncertain completion stop the action.
No desktop keyboard/mouse injection or guessed default keys are used.

`Input.GetMappedKey(control, deviceType)` supplies the actual keyboard or mouse
mapping. The reviewed SKSE64 `Input.psc` controls are `Forward`, `Back`,
`Strafe Left`, `Strafe Right`, `Quick Inventory`, `Activate`, `Ready Weapon` and
`Right Attack/Block`. The native source implementation is
`src/KeyboardInput.cpp` and its catalog is `src/KeyboardInputState.cpp`.
Live Papyrus metadata must match each exact native signature before calls.

`inspect scene`, `player`, `inventory` and `refs` supply actual position, health,
equipment and count observations; `menu list includeFlags:true` supplies current
native menu flags. Unknown blocking menus stop input. World Observer supplies
exact reference runtime handle/session/generation.
These contracts are defined in DevBench `src/Tools.cpp` and the provider's
read-only World Observer extension. Missing fields stop the operation.

Equipment uses the actual native `Actor.EquipItem(Form,Bool,Bool)` or
`Actor.UnequipItem(Form,Bool,Bool)` operation and then verifies unchanged quantity,
the actual inventory worn flag and weapon hand identity. This tests equipment
state changes; it makes no inventory-row selection or UI-navigation claim.

## Fixture scope and limits

Both factories record durable creation intent before one native `PlaceAtMe`.
The returned dynamic reference, resolved base, same process, run, world generation
and observed incarnation form their creation witness in `seGameplayFixtures`.
An attempted tag cannot be reused. Every tag becomes invalid after any load,
including a same-process load; old FormIDs are never automatically rebound.

The game can recycle a consumed item's numeric dynamic FormID for a later
`PlaceAtMe`. Pickup therefore retains its exact `consumedReferenceObservation`
and marks `retiredWorldReference` only after the explicit native absence response
`count: 0, refs: []`. An unloaded reference does not authorize numeric ID reuse.
Every older matching tag must be a picked-up item with that complete retirement
proof in the same run, process and world generation, and retain its old observed
incarnation. After the new single spawn, actual reference/base types and a
different observed runtime handle in the same native session/generation are
required before any placement or health mutation. The new fixture retains a
`referenceReuseWitness` containing both identities and the retirement receipts.
The original item tag continues to select its inventory base and historical
reference; it is never retargeted to the new world object. Active aliases,
missing proof, reused handles and stale generations stop the attempted creation
without issuing another spawn.

The pickup factory creates one item, observes its loaded reference, keyframes
it with `SetMotionType(4,false)` and places it along measured player pitch/yaw
from the actual first-person camera position. If necessary, a separately
recorded fixture-only camera operation selects first person. Actual crosshair
selection of that exact reference remains mandatory before one mapped Activate
input. The item must add exactly one to the measured inventory count and either
disappear from an actual exact-form native lookup (`count: 0, refs: []`) or have
an actual `Is3DLoaded: false` read while that exact reference still exists.
Deleted references are not passed as Papyrus `self`. Missing/malformed lookup
fields, another identity and transport failures never count as disappearance;
`pickup.worldReferenceState` records `absent` or `unloaded` with the raw lookup.
This is a controlled pickup fixture, not a physics or
general aiming qualification.

The combat factory creates one nonpersistent NPC in front of the player,
issues one native `SetRestrained` call, prepares 1000 health, retains collisions
and verifies actual health, reference identity and stable placement. The staged
SE Observer does not expose a restraint flag; native call completion is recorded
without claiming that unavailable readback. These are explicit fixture mutations.
One short ordinary attack input is permitted for that target. No
Papyrus damage operation is used. Actual exact-target crosshair, a settled drawn
weapon, stable preattack health samples, negative target-health delta and survival
are required. `combat.matchedPlayerHitObserved` remains false and `damageBasis`
describes the temporal measurements. Lack of damage
is failure; another attack is never issued automatically. These sequential
observations describe this controlled interval, not an atomic causal event
stream or general combat qualification.

The domain provides no look/mouse-motion action, inventory navigation, arbitrary
key/script/console route, reference adoption, save remapping or VR action.
Reads may poll only within the inherited absolute deadline. Mutations execute
once; uncertain spawn, pickup, equipment and attack state retains its durable
intent and cannot become a successful result or an automatic replay.

## External USVFS acquisition

The reviewed MO2 2.5.2 installation uses the official
[USVFS 0.5.7.2 archive](https://github.com/ModOrganizer2/usvfs/releases/download/v0.5.7.2/usvfs_v0.5.7.2.7z),
with SHA-256
`c6252eed78ee1c307733a4412cb68522cffc48107be4795c4e38b2b8d7c76d01`.
Keep the archive, extracted binaries/PDBs, hash manifest and backups outside Git.
Before replacement, require a cold MO2 and no remaining users of its shared VFS.
Back up and verify all four files, then replace `usvfs_x64.dll`, `usvfs_x86.dll`,
`usvfs_proxy_x64.exe` and `usvfs_proxy_x86.exe` as one coherent release and verify
their installed hashes. Mixing old and new users/files is unsafe across the
Boost shared-memory ABI change. This acquisition does not establish that the
update alone fixes shutdown; actual owned process-exit evidence remains required.

## Qualified basic SE composition — 28 October 2026

Polygon run `20261028-175824-9c9a70` completed all 16 declared basic checks plus
native New Game bootstrap: movement, exact pickup, inventory open/close, native
equip, draw, one controlled attack, sheathe, owned save, unequip, same-process
load and fresh saved-equipment restoration. Observed movement was 204.7114 game
units; pickup added exactly one item; target health changed 1000 to 995.59998 after
one input. The damage assertion is sampled health change, not a matched hit event.

One native close invocation posted WM_CLOSE to three verified owned windows,
received accepted receipts and observed actual native exit0 within 1.9 seconds.
No forced game stop or recovery occurred. Worker exit was 0; files/profile were
restored, collection finished and the nonempty copied profile was archived and
removed from MO2's ordinary list. Historical failed packets remain unchanged.

Exact executable code: [Skyrim Autotest a05102d](https://github.com/Vhodnoylogin/skyrim-autotest/commit/a05102d9b2dc89790f7de693b5d096459bf1ecc7).
Game: Skyrim SE 1.7.104, SKSE64 2.3.1, Realm of Lorkhan and the five declared managed
tool/start mods in the isolated copy. Provider code:
[DevBench 52f0c4c](https://github.com/Vhodnoylogin/devbench/commit/52f0c4ca92231226a99032b0e305f9cf6c3030a9),
DLL SHA256 `3c6d7e199c14760ad0998cf8f11b983e164feb325a4e218b4cb2b9f4b825697f`.
ObserverSE DLL SHA256 `7e81410b2b446f6606715e3f4b0f00466a1eac655d4b1789c32a77aaf5260c0a`.
MO2 2.5.2 uses the official USVFS set described above. Dashboard projection code:
[fc790a8](https://github.com/Vhodnoylogin/skyrim-poligon-dashboard/commit/fc790a8ba06122ff1744f838ee2b314e9a71919d).
Source and exact portable extraction each ran 299 focused tests: 297 passed,
two Windows symlink-create privilege skips. The unchanged native DLL had 318
passing cases; Dashboard had 17 targeted passing cases.

Tested portable archive SHA256:
`43054bc874fc9b4ea99bea726f1aa1bcdc516c0b166072606aa0d1865bb774cc`.
The included agent-kit example and explicit `se_shutdown: "window-close-v1"`
configuration describe this route. Rebuilt/replaced providers and other fixtures
need their own reviewed pins and qualification. This baseline does not establish
inventory-row navigation, general combat AI, physical contacts, rendered output,
VR, audio or acceptance of any subject mod.
