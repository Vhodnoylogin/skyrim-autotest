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
