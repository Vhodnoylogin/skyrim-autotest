# Owned-reference visual freeze candidate

This source candidate adds `actor-visual-freeze` for one **already created**,
actually witnessed persistent disposable NPC. It does not spawn, adopt, position,
rename, unequip or transform an actor. It does not set global AI or collision
flags, issue console commands, freeze animations/physics or change the existing
`actor-fixture-inspection` retain-enabled contract. No live qualification is
implied by source tests or a compiled provider.

Both operations run within the existing owner, frozen native binding policy,
`npcPersistence:true` and enabled `morphSession`, or an explicit SE
`matrixLifecycle` with `freezeActors:true`:

```json
{"operation":"world.read","request":{
  "domain":"actor-visual-freeze","actor":{"fixtureTag":"MThin"}}}
```

```json
{"operation":"object.perform","request":{
  "domain":"actor-visual-freeze","actor":{"fixtureTag":"MThin"},
  "action":"freeze-owned-reference-once"}}
```

The request accepts no raw reference, script/function, console string, state
toggle, player selector or unfreeze operation. It uses the actual held semantic
command identity. The executor validates the creation witness, current game,
Observer incarnation, persistent reference/base/VM correspondence, current cell
and race before requesting an explicit native set-to-off operation. The native
request additionally guards its own provider session/world generation and a
sampled root token. Tokens are process-local identities; unobserved pointer
reuse between samples is not detectable.

The provider uses CommonLib `Actor::EnableAI(false)` and
`TESObjectREFR::SetCollision(false)` for AI and the reference flag. The latter
**only changes the reference flag** and cannot disable a live controller. The
expanded provider also calls the independently verified SE1.7.104 controller
filter setter; see [its exact runtime contract and build recipe](controller-collision.md).
The runtime, actual controller vtable and Havok world must be supported before
any freeze setter. Other runtimes, including VR, currently refuse this expanded
freeze action. Existing read-only observations remain available.

The typed engine call sets only `CFilter::kNoCollision`, preserving every other
filter bit, under the controller world's write lock. It uses no raw Havok field
writes, global toggles or guessed filter-update calls. Its receipt records the
before/requested/after filter values and whether a controller setter was issued.
The provider independently reads `GetCollisionFilterInfo`/`QNoCollision()` again;
an ignored or mismatched setter cannot pass. A missing controller/world remains
unavailable. Neither reference state nor a returned setter substitutes for that
fresh controller observation.

`actor.aiEnabled` and `actor.collisionsEnabled` are actual returned facts.
`fixture.visualFrozen` requires AI off, reference collision flag off **and** the
current controller's no-collision filter set. It is not proof of absent contacts,
solver results, unchanged pixels, stopped idle animations or disabled CBPC/FSMP.

Each mutation persists intent before one native request, then obtains fresh
guarded state reads within the original absolute deadline. The native provider
also consumes its unique request ID before setters. An ACK loss, partial result,
changed identity or deadline failure leaves an uncertain intent and forbids
further mutation of that creation identity. Read-only diagnosis remains allowed;
observing the desired state does not authorize replay. A new command after a
**completed** operation is idempotent: no toggle occurs and already-off setters
are not issued again. No previous completed observation is represented as fresh.

In the legacy morph-session path, race and save/load transitions do not
automatically reapply freeze. The additive SE matrix path with `freezeActors:true`
reapplies preparation after creation, race/link operations and remapped load; see
[the matrix lifecycle contract](se-matrix-lifecycle.md). Reads only verify state;
they never repair it or issue setters. Read the
new current state after the ordinary transition settles. If needed, explicitly
issue a new command with its own identity; postload references must have actual
SKSE form/VM remap evidence. Old FF IDs or cached handles cannot substitute.

## Qualification checklist

1. Pin the executor, authored provider source, exact compiled DevBench DLL and
   matching CommonLib dependency; qualify this expanded protocol separately.
2. Create a persistent witnessed NPC through the ordinary fixture route. Read
   current AI, reference collision flag and controller filter independently.
3. Issue one freeze command. Require its unique native receipt plus fresh reads
   with all three states off; observe stable position without inferring contacts.
4. Execute the ordinary human/beast race transitions, allow model settlement,
   and read the new race/root identity and flags. If reset, use a new explicit
   command only after the prior one completed; retain all intermediate evidence.
5. Perform the separately admitted owned save/load. Require actual remapped
   reference/VM identity, then read flags; never reuse pre-load native guards.
6. Test two actors independently: freezing one must leave the other's flags and
   the player's state unchanged. Preserve prior physics/retain-enabled scenarios.
7. Retain an intentional lost-ACK test: one attempted mutation, uncertain state,
   no second call even under a new command ID, with read-only diagnosis available.

The first real SE probe must establish that the new explicit controller setter
produces the independently observed filter state and survives ordinary engine
updates. Until then this remains an offline candidate. Readback alone does not
establish physical contact suppression, stable rendering or visual quality.

## Integration and acquisition

This implementation reuses the same repository's reviewed source commit
`31a84e0` rather than creating another control protocol. Its additional native
`inspection.worldGeneration` is the actual current visibility-provider generation,
allowing the independent inspection and visual-state reads to reject a transition
between them. Rebuild the expanded native provider from this executor revision:
the old DLL is not enough. `native/devbench/NPCPersistence.cpp` and the existing
provider integration recipe are the source of this additive protocol. Acquire the
pinned DevBench/CommonLib dependencies using the repository's native build guides;
keep binaries, SDKs and build outputs external. No third-party source is vendored.

`fixture.dontMove` comes from the independent native inspection, separate from
`fixture.visualFrozen`. The read-only `require_frozen` guard requires both true.
This establishes sampled state only, not continuous unobserved immobility or
absence of physical contacts. Complete creation/game/generation/incarnation/VM
custody must remain unchanged through each sequential read. Each durable mutation
key includes the actor's creation identity, so one owned load command can prepare
two remapped actors without admitting a replay on either actor.
