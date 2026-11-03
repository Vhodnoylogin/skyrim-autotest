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

The native provider uses the public CommonLib `Actor::EnableAI(false)` and
`TESObjectREFR::SetCollision(false)` APIs. The latter **only changes the
reference collision flag** in the reviewed CommonLib implementation. Therefore
`HasCollision()==false` is retained separately and cannot establish controller
collision state. The provider independently asks the current character controller
for its `CFilter` and reads `QNoCollision()`. With no loaded controller the
collision domain is unavailable and preparation refuses before issuing setters.
No undocumented Havok fields, virtual offsets or fallback collision writes are
used. If the controller filter never follows the reference flag, preparation
times out honestly; this candidate does not solve that missing engine behavior.

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

The first real SE probe must establish whether the public reference setter also
produces the required controller filter state on the supported runtime. Until
that succeeds, this remains an offline candidate rather than a ready visual
fixture or a claim of physical collision disablement.

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
