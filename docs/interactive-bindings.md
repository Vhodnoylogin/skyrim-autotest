# Created-NPC bindings for an owned interactive session

This opt-in route supplies controlled NPC creation and declaratively selected native
Papyrus calls inside the existing [interactive session](interactive-session.md).
It has no microphone, host wake, camera, console, arbitrary script evaluation or
independent game launch. It is disabled when `interactive_session.nativeBindings`
is absent or null. Preparing a policy does not authorize a launch or establish live
qualification of an installed game/mod combination.

The policy belongs to the separately frozen platform configuration. Commands select
one declared binding ID and typed values; they cannot supply a script, function,
signature, policy, selector wrapper or callback. The runtime compares its normalized
policy to `state.configuration.interactive_session.nativeBindings` on every call.
Native metadata proves a callable signature. The policy author must separately
review the function's real meaning and the owner's requested scope; metadata alone
cannot prove that a declaration marked `read` has no effects.

## Frozen policy

The example below is **not enabled by default**. Replace the sample NPC base with
the actual runtime IDs of explicitly approved disposable fixtures. The owner-provided
OBody 5.2 declarations and installed native metadata must agree; no substitute
`ApplyPresetByName` fallback is used. Actor IDs are supplied only after controlled
creation returns its witnessed dynamic reference.

```json
{
  "schemaVersion": 1,
  "fixtureActorBases": ["0x00013475"],
  "allowedRaceForms": ["0x00013746", "0x000CDD84"],
  "bindings": [
    {
      "id": "npc_race",
      "script": "Actor",
      "function": "SetRace",
      "scope": "member",
      "params": ["Race"],
      "returnType": "None",
      "effect": "mutate",
      "actorSelf": true,
      "actorArgs": [],
      "raceArgs": [0],
      "completion": "actor-race"
    },
    {
      "id": "human_preset",
      "script": "OBodyNative",
      "function": "AssignPresetToActor",
      "scope": "global",
      "params": ["Actor", "String", "Bool", "Bool"],
      "returnType": "Bool",
      "effect": "mutate",
      "actorSelf": false,
      "actorArgs": [0],
      "raceArgs": [],
      "completion": "native-return"
    },
    {
      "id": "human_catalog",
      "script": "OBodyNative",
      "function": "GetAllPossiblePresets",
      "scope": "global",
      "params": ["Actor"],
      "returnType": "String[]",
      "effect": "read",
      "actorSelf": false,
      "actorArgs": [0],
      "raceArgs": [],
      "completion": "native-return"
    },
    {
      "id": "source_keyed_morph",
      "script": "NiOverride",
      "function": "GetBodyMorph",
      "scope": "global",
      "params": ["ObjectReference", "String", "String"],
      "returnType": "Float",
      "effect": "read",
      "actorSelf": false,
      "actorArgs": [0],
      "raceArgs": [],
      "completion": "native-return"
    }
  ]
}
```

`bindings` contains 1..64 declarations. Every declaration requires exactly the fields
shown. IDs are opaque bounded identifiers; script/function names are individual
identifiers. Callable declarations cannot be duplicated. Types normalize by case;
supported scalar types are `Bool`, `Int`, `Float`, `String`, `Actor`,
`ObjectReference`, `Form`, `Race`, and return-only `None`. Primitive arrays are
supported. Integers use the Papyrus signed 32-bit range; floats must be finite and
fit float32; strings are at most 4096 UTF-8 bytes; arrays contain at most 4096 items.

Member calls require `actorSelf:true` and an explicit actor self. Global calls
forbid self. Every Actor/ObjectReference parameter must be listed in `actorArgs`;
every Race/Form parameter must be listed in `raceArgs`. These index sets cannot
overlap. Race arguments must be exact members of `allowedRaceForms`, whose entries
and fixture bases normalize to eight-digit runtime hexadecimal identities. Every
mutator requires at least one guarded actor target. Standard world/load/save,
creation, deletion and movement functions are refused through this binding route;
controlled creation has its own protocol below.

The following additional owner-supplied OBody declarations can be represented with
the same explicit fields and must pass actual installed metadata checks:

| Global function | Parameters | Return | Effect / actor indexes |
| --- | --- | --- | --- |
| `GetPresetAssignedToActor` | `Actor` | `String` | `read`, `[0]` |
| `GetFemaleDatabaseSize` | none | `Int` | `read`, `[]` |
| `GetMaleDatabaseSize` | none | `Int` | `read`, `[]` |

Explicitly declared member calls such as `SetDontMove(Bool)`, `EnableAI(Bool)`,
`SetActorValue(String, Float)`, `StopCombat()`, `StopCombatAlarm()` and
`UnequipAll()` can use the same actor witness guard if actual native metadata
matches their frozen signatures. Creation requests the locomotion blocker below
without sending AI, collision, equipment or aggression setters. Supply only the exact
separately authorized preparation commands. This route does not add an aggregate
SKEE read: `NiOverride.GetBodyMorphs` is not an available Papyrus substitute for
an independently qualified native aggregate provider.

## Controlled creation and proof of ownership

An allowed base is insufficient to adopt an existing NPC. All actor targets,
including actor-bearing reads, must have been newly created by this run through
`fixture-create`. Existing placed NPCs, the player, static references, imported
records, stale worlds and uncertain creations are rejected.

Send a machine envelope through the current `game-<run id>` session with
`sourceId:"operator.actions"`, `kind:"text"` and a stable new source event ID:

```json
{
  "schemaVersion": 1,
  "operation": "fixture-create",
  "request": {
    "tag": "M1",
    "base": "0x00013475",
    "forwardGameUnits": 200,
    "rightGameUnits": 50
  },
  "timeoutSeconds": 30
}
```

Tags are unique across all attempted creations, including failures, with a maximum
of sixteen per run. Forward is 0..1000, right is -1000..1000, and horizontal distance
is 50..1000 Skyrim game units. Positions are relative to the actual player heading
on the current floor plane. The operator must choose an appropriate clear location;
coordinate/readback checks do not prove an empty floor, collision clearance or
stable future physics.

Creation qualifies the actual native member signatures for `PlaceAtMe(Form, Int,
Bool, Bool) -> ObjectReference`, `MoveTo(ObjectReference, Float, Float, Float,
Bool) -> None`, `SetAngle(Float, Float, Float) -> None`,
`Actor.SetDontMove(Bool) -> None`, and the required getters.
It checks the exact owned game, disposable profile, current guarded world and fresh
gameplay/menu readiness. The base must resolve through `inspect refs` as exactly
the approved NPC base; actual base sex/race/weight and the loaded player are read.
A complete untruncated census of at most 1024 loaded actor references is captured
before creation, without asking for actor inventory/equipment or photography data.

The executor durably records an intent before one `PlaceAtMe` call with count 1,
force-persist false and initially-disabled false. The native returned reference
must be a new distinct `0xFF...` reference, absent from the preceding census and
every existing fixture record. A witnessed actor must match its base, initial
native sex/race, observer session/load generation and runtime incarnation, and
have loaded 3D. The executor then calls `Actor.SetDontMove(true)` once on that
exact witnessed reference, before one `MoveTo` and one `SetAngle`. Each mutation,
including the locomotion blocker, has its own durable intent/returned step. A lost
setter callback leaves uncertainty and stops before placement. The route does not
disable AI/collision, issue TAI/TCL or edit inventory. The setter callback is not an
independent measurement of locomotion, enabled AI or collision state. Actual position
must be within four game units and heading within one degree of the requested
placement. Player movement before placement or a changed world/incarnation stops
the operation; the executor does not silently recompute or repeat it.

`state.interactiveActorFixtures[tag]` retains the current run/game/world, exact
reference/base, creation ID, the native-return witness, preceding-census digest,
observer incarnation, actual sex/race and placement. Only `status:"created"`
records can authorize later bindings. A lost callback, partial placement, wrong
identity or unavailable readback records `uncertain`; there is no search/adoption,
automatic deletion, retry, tag reuse or reference recovery path. A killed process
can leave an earlier durable intent, which also cannot authorize actor actions.
The witness is evidence kept by the trusted executor, not an unforgeable receipt
against a process that can edit its runtime files. Native callback and sequential
observer reads are not an atomic engine transaction.

## Typed requests and actual results

Use the exact newly returned actor reference and its approved base:

```json
{
  "schemaVersion": 1,
  "operation": "binding",
  "bindingId": "human_preset",
  "args": [
    {"reference": "0xFF000123", "base": "0x00013475"},
    "Exact human preset from the actual catalog",
    true,
    false
  ],
  "timeoutSeconds": 20
}
```

All arguments are required, including both OBody booleans; no Papyrus defaults or
neutral fills are guessed. Actor arguments use `{reference,base}`, never `selected`
or an arbitrary `{form:...}` wrapper. Race arguments are explicit whitelisted hex
strings. A member race request adds `self`:

```json
{
  "schemaVersion": 1,
  "operation": "binding",
  "bindingId": "npc_race",
  "self": {"reference": "0xFF000123", "base": "0x00013475"},
  "args": ["0x000CDD84"],
  "timeoutSeconds": 20
}
```

Before invocation, the runtime requires one unique live metadata entry in the
declared global/member scope with the exact parameters, return type and native
flag. Actual actor observations must match the same-run created witness, including
reference/base/sex, loaded 3D and runtime incarnation. Checks bracket the native
call and use the common absolute deadline, with at most thirty seconds remaining.
No declared invocation is automatically repeated after error, late return, lost
callback, changed world or mismatched identity. The enclosing bus retains delivery
uncertainty and refuses replay; directly retrying this Python helper is unsupported.

`Actor.SetRace` is reserved for the exact `actor-race` contract. It uses the existing
`actor_domain.perform` setter once and polls only actual actor race/load/incarnation
reads afterward. A successful result reports `domainCompletion:
"observed-race-readback"`; it does not prove model deformation or rendered appearance.
Other mutators report their actual typed native return with `domainCompletion:
"unverified"`, including when OBody returns true. Native success, assignment state,
keyed source values, actual applied morphs and visual acceptance remain separate.
Read native assignment/catalog/keyed-state evidence explicitly. Large typed read
results are handled by the enclosing loop's external evidence/receipt mechanism.

## Integration contract and offline checks

The existing interactive executor owns delivery, serialization, deadlines and
restoration. It requires the `papyrus` tool allowlist for these operations:

```python
normalized = interactive_bindings.validate(settings.get("nativeBindings"))
result = fixture_actors.create(session, envelope["request"], absolute_deadline, normalized)
result = interactive_bindings.guarded_call(session, binding_request, absolute_deadline, normalized)
```

`binding_request` contains only `bindingId`, `args`, and optional `self`.
`fixture_actors.validate_request` performs side-effect-free request validation.
`fixture_actors.guard(session, actor_spec, deadline, policy)` provides the same
created-witness/native identity guard for existing semantic preset mutations.
It creates/adopts no record. The final module remains independent of any camera
provider and never requires full actor inventory availability.

```powershell
python -m unittest discover -s tests -p "test_interactive_bindings.py" -q
python -m unittest discover -s tests -p "test_fixture_actors.py" -q
```

Tests use simulated owned-game/provider responses and actual shared actor-domain
validation. They cover disabled/default scope, frozen policy, wrong metadata and
global/member signatures, actual type checks, existing-player/NPC refusal,
creation intents and callback loss, wrong base/reference, incomplete creation,
old tags/worlds/incarnations, one setter invocation, race readback and no uncertain
replay. They do not launch Skyrim or qualify these new routes in a live game.
